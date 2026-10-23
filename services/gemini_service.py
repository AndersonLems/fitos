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

from config.settings import GEMINI_MODEL_DEFAULT, gemini_api_key, logger
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
    return gemini_api_key() is not None


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


def _call(s: Session, *, contents, config, purpose: str, profile_id: int | None):
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


def generate_structured(s: Session, prompt: str, schema: type[T], *, purpose: str, profile_id: int | None,
                        validator=None, system: str = SYSTEM_BASE) -> T:
    """Gera JSON validado. `validator(obj) -> list[str]` devolve erros de negócio."""
    from google.genai import types

    cfg = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                      response_schema=schema, temperature=0.4)
    errors: list[str] = []
    text = prompt
    for attempt in range(2):
        resp = _call(s, contents=text, config=cfg, purpose=purpose, profile_id=profile_id)
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
    raise GeminiInvalidOutput("O Gemini devolveu um plano inconsistente duas vezes; nada foi salvo.", errors)


def generate_text(s: Session, prompt: str, *, purpose: str, profile_id: int | None, max_tokens: int = 700) -> str:
    from google.genai import types
    cfg = types.GenerateContentConfig(system_instruction=SYSTEM_BASE, temperature=0.5, max_output_tokens=max_tokens)
    resp = _call(s, contents=prompt, config=cfg, purpose=purpose, profile_id=profile_id)
    return (resp.text or "").strip()


def save_insight(s: Session, profile_id: int, kind: str, content: str) -> AIInsight:
    ins = AIInsight(profile_id=profile_id, kind=kind, content=content, model=current_model(s))
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
