"""Integração com o Gemini (SDK google-genai).

Princípios:
- Nenhuma chamada automática: toda geração parte de um clique do usuário.
- Respostas estruturadas validadas por Pydantic; IDs precisam existir no catálogo enviado.
- Plano inconsistente → uma nova tentativa com a lista de erros; persistindo, não salva.
- Contexto enviado é compacto (economia de tokens) e nunca inclui segredos.
"""
from __future__ import annotations

import json
import time
from typing import TypeVar

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from config.settings import GEMINI_MODEL_DEFAULT, GROQ_MODEL_DEFAULT, gemini_api_key, groq_api_key, logger
from database.models import AIInsight, AIUsage, Setting

T = TypeVar("T", bound=BaseModel)

SYSTEM_BASE = (
    "Você é o assistente do FitOS, um app pessoal de treino e alimentação. Você NÃO é médico, nutricionista "
    "nem educador físico habilitado e deixa isso claro quando o assunto pedir avaliação profissional. "
    "Seja conservador: sem restrição calórica extrema, sem progressões agressivas, sem prometer resultados em "
    "prazo fixo. Responda em português do Brasil, de forma direta e sem floreios."
)
MODEL_CHOICES = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]


class GeminiUnavailable(RuntimeError):
    pass


class GeminiInvalidOutput(RuntimeError):
    def __init__(self, msg: str, errors: list[str]):
        super().__init__(msg)
        self.errors = errors


def current_model(s: Session) -> str:
    st = s.get(Setting, "gemini_model")
    return (st.value if st and st.value else GEMINI_MODEL_DEFAULT)


def is_configured() -> bool:
    return gemini_api_key() is not None or groq_api_key() is not None


_client = None


def client():
    global _client
    key = gemini_api_key()
    if not key:
        raise GeminiUnavailable("GEMINI_API_KEY não configurada no arquivo .env")
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=key)
    return _client


def _log_usage(s: Session, profile_id: int | None, purpose: str, model: str, resp, ok: bool) -> None:
    um = getattr(resp, "usage_metadata", None) if resp is not None else None
    s.add(AIUsage(profile_id=profile_id, purpose=purpose, model=model, ok=ok,
                  input_tokens=getattr(um, "prompt_token_count", None),
                  output_tokens=getattr(um, "candidates_token_count", None)))


# Erros 5xx são do lado do Google (sobrecarga, falha interna) e não cobram tokens: vale tentar de novo.
RETRY_DELAYS = (2, 6)


def _failure_message(exc: Exception, model: str) -> str:
    code = getattr(exc, "code", None)
    if code == 503:
        return (f"O Gemini está sobrecarregado agora (503) e não respondeu após {len(RETRY_DELAYS) + 1} tentativas. "
                "Tente de novo em alguns minutos ou escolha outro modelo em Configurações.")
    if isinstance(code, int) and code >= 500:
        return (f"O Gemini teve um erro interno ({code}) após {len(RETRY_DELAYS) + 1} tentativas. Tente de novo "
                "em alguns minutos ou escolha outro modelo em Configurações.")
    if code == 429:
        return "A cota do Gemini acabou (429). Aguarde a renovação ou use um modelo “lite” em Configurações."
    if code in (401, 403):
        return f"O Gemini recusou a chave ({code}). Confira GEMINI_API_KEY no arquivo .env."
    if code == 404:
        return f"O modelo “{model}” não foi encontrado (404). Escolha outro em Configurações."
    return (f"Falha ao chamar o Gemini ({type(exc).__name__}{f' {code}' if code else ''}). "
            "Verifique a conexão, a chave e o modelo em Configurações.")


def _call_gemini(s: Session, *, contents, config, purpose: str, profile_id: int | None):
    model = current_model(s)
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            resp = client().models.generate_content(model=model, contents=contents, config=config)
            break
        except GeminiUnavailable:
            raise
        except Exception as exc:  # erros de rede/cota: registra sem expor a chave
            code = getattr(exc, "code", None)
            logger.error("Gemini falhou (%s, %s, tentativa %s): %s %s %s", purpose, model, attempt + 1,
                         type(exc).__name__, code or "", str(getattr(exc, "message", "") or "")[:200])
            if isinstance(code, int) and code >= 500 and attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            _log_usage(s, profile_id, purpose, model, None, False)
            raise GeminiUnavailable(_failure_message(exc, model)) from exc
    _log_usage(s, profile_id, purpose, model, resp, True)
    return resp


def last_model(s: Session) -> str:
    return s.info.get("ai_model", current_model(s))


def last_provider(s: Session) -> str:
    return s.info.get("ai_provider", "gemini")


def _call_groq(s: Session, **kwargs):
    from services.groq_service import generate_content
    try:
        resp = generate_content(contents=kwargs["contents"], config=kwargs["config"])
    except Exception as exc:
        _log_usage(s, kwargs["profile_id"], kwargs["purpose"], GROQ_MODEL_DEFAULT, None, False)
        logger.warning("GroqCloud falhou (%s): %s", kwargs["purpose"], type(exc).__name__)
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429:
            raise GeminiUnavailable("O GroqCloud atingiu a cota ou o limite de requisições (429). Confira o uso da API GroqCloud.") from exc
        raise GeminiUnavailable("O GroqCloud também não respondeu. Confira a chave GroqCloud, a cota e a conexão.") from exc
    _log_usage(s, kwargs["profile_id"], kwargs["purpose"], GROQ_MODEL_DEFAULT, resp, True)
    s.info.update(ai_model=GROQ_MODEL_DEFAULT, ai_provider="groq")
    return resp


def _call(s: Session, **kwargs):
    try:
        resp = _call_gemini(s, **kwargs)
        if hasattr(resp, "text") and not (resp.text or "").strip() and not getattr(resp, "function_calls", None):
            raise GeminiUnavailable("O Gemini devolveu uma resposta vazia.")
    except GeminiUnavailable as exc:
        if not groq_api_key():
            raise
        logger.info("Gemini indisponível; tentando GroqCloud (%s)", kwargs["purpose"])
        try:
            return _call_groq(s, **kwargs)
        except GeminiUnavailable as fallback_exc:
            raise GeminiUnavailable(f"{exc} {fallback_exc}") from fallback_exc
    s.info.update(ai_model=current_model(s), ai_provider="gemini")
    return resp


def generate_structured(s: Session, prompt: str, schema: type[T], *, purpose: str, profile_id: int | None,
                        validator=None, system: str = SYSTEM_BASE) -> T:
    """Gera JSON validado. `validator(obj) -> list[str]` devolve erros de negócio."""
    from google.genai import types

    cfg = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                      response_schema=schema, temperature=0.4)
    errors: list[str] = []
    text = prompt
    for attempt in range(4 if groq_api_key() else 2):
        call = _call_groq if attempt >= 2 else _call
        resp = call(s, contents=text, config=cfg, purpose=purpose, profile_id=profile_id)
        try:
            obj = resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(resp.text or "")
        except (ValidationError, ValueError) as exc:
            errors = [f"JSON fora do formato: {str(exc)[:300]}"]
        else:
            errors = validator(obj) if validator else []
            if not errors:
                return obj
        logger.warning("Gemini %s: saída inválida (tentativa %s): %s", purpose, attempt + 1, errors[:5])
        text = (prompt + "\n\nSua resposta anterior foi rejeitada pela validação do sistema pelos motivos abaixo. "
                "Corrija e responda novamente no mesmo formato:\n- " + "\n- ".join(errors[:15]))
    raise GeminiInvalidOutput("A IA devolveu respostas inconsistentes; nada foi salvo.", errors)


def generate_structured_from_image(s: Session, image: bytes, mime_type: str, prompt: str, schema: type[T], *,
                                   purpose: str, profile_id: int | None) -> T:
    """Leitura de foto com saída estruturada. Só no Gemini: o adaptador GroqCloud repassa apenas texto."""
    from google.genai import types

    cfg = types.GenerateContentConfig(system_instruction=SYSTEM_BASE, response_mime_type="application/json",
                                      response_schema=schema, temperature=0.1)
    contents = [types.Part.from_bytes(data=image, mime_type=mime_type), prompt]
    resp = _call_gemini(s, contents=contents, config=cfg, purpose=purpose, profile_id=profile_id)
    s.info.update(ai_model=current_model(s), ai_provider="gemini")
    try:
        return resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(resp.text or "")
    except (ValidationError, ValueError) as exc:
        raise GeminiInvalidOutput("A IA não devolveu a leitura no formato esperado.", [str(exc)[:300]]) from exc


def generate_text(s: Session, prompt: str, *, purpose: str, profile_id: int | None, max_tokens: int = 700) -> str:
    from google.genai import types
    cfg = types.GenerateContentConfig(system_instruction=SYSTEM_BASE, temperature=0.5, max_output_tokens=max_tokens)
    resp = _call(s, contents=prompt, config=cfg, purpose=purpose, profile_id=profile_id)
    return (resp.text or "").strip()


def save_insight(s: Session, profile_id: int, kind: str, content: str) -> AIInsight:
    ins = AIInsight(profile_id=profile_id, kind=kind, content=content, model=last_model(s))
    s.add(ins)
    s.flush()
    return ins


def last_insight(s: Session, profile_id: int, kind: str) -> AIInsight | None:
    from sqlalchemy import select
    return s.scalar(select(AIInsight).where(AIInsight.profile_id == profile_id, AIInsight.kind == kind)
                    .order_by(AIInsight.id.desc()).limit(1))


def compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------- esquemas

class GWExercise(BaseModel):
    exercise_id: int
    sets: int = Field(ge=1, le=8)
    reps_min: int = Field(ge=1, le=50)
    reps_max: int = Field(ge=1, le=50)
    rest_seconds: int = Field(ge=0, le=600)
    notes: str | None = None


class GWDay(BaseModel):
    title: str
    weekday: int | None = Field(default=None, description="0=segunda … 6=domingo")
    exercises: list[GWExercise]


class GWPlan(BaseModel):
    name: str
    rationale: str = Field(description="Explicação curta da divisão e da progressão proposta")
    days: list[GWDay]


class GMItem(BaseModel):
    food_id: int
    grams: float = Field(description="porção consumida em gramas, no estado do alimento do catálogo")


class GMMeal(BaseModel):
    meal_type: str
    title: str
    preparation: str
    items: list[GMItem]


class GMDay(BaseModel):
    meals: list[GMMeal]


class GMPlan(BaseModel):
    days: list[GMDay]
    notes: str | None = None


class GMissing(BaseModel):
    name: str
    grams: float


class GRecipe(BaseModel):
    name: str
    prep_minutes: int
    instructions: str
    items: list[GMItem]
    missing: list[GMissing] = Field(default_factory=list, description="ingredientes que faltam em casa")


class GRecipes(BaseModel):
    recipes: list[GRecipe]


class GGoalScenario(BaseModel):
    key: str = Field(description="conservador | rapido | intenso")
    kcal_adjust: int = Field(description="ajuste nas calorias diárias calculadas, entre -150 e 150 (0 se ok)")
    meals_per_day: int = Field(ge=3, le=6)
    tips: str = Field(description="1–2 frases práticas para seguir este cenário")


class GGoalReview(BaseModel):
    analysis: str = Field(description="análise curta em markdown (até 8 linhas): o que os dados mostram, "
                                      "o que é realista e quando reavaliar")
    recommended: str = Field(description="conservador | rapido | intenso")
    scenarios: list[GGoalScenario]
