"""Validação das saídas do Gemini e das ações do chat, sem chamar a API."""
import pytest
from pydantic import ValidationError

from services import ai_planner
from services import chat_service as cs
from services import gemini_service as gs
from services import nutrition_service as ns
from services import profile_service as ps


def test_menu_validator_rejects_unknown_ids_and_bad_totals(s):
    foods = ns.core_foods(s)
    by = {f.id: f for f in foods}
    ai_planner._FOODS_CACHE.update(by)
    arroz = next(f for f in foods if f.taco_id == 3)
    plan = gs.GMPlan(days=[gs.GMDay(meals=[gs.GMMeal(meal_type="Almoço", title="x", preparation="y", items=[
        gs.GMItem(food_id=arroz.id, grams=100), gs.GMItem(food_id=999999, grams=100)])])])
    errs = ai_planner._menu_validator(set(by), 1, 2000, 120)(plan)
    assert any("999999" in e for e in errs)
    assert any("kcal" in e for e in errs)


def test_structured_retry_then_fail(s, monkeypatch):
    calls = []

    class Resp:
        parsed = None
        text = '{"days": []}'
        usage_metadata = None

    def fake_call(sess, **kw):
        calls.append(kw["contents"])
        return Resp()

    monkeypatch.setattr(gs, "_call", fake_call)
    with pytest.raises(gs.GeminiInvalidOutput):
        gs.generate_structured(s, "p", gs.GMPlan, purpose="t", profile_id=None, validator=lambda o: ["ruim"])
    assert len(calls) == 2 and "ruim" in calls[1]


def test_chat_tool_args_validated():
    with pytest.raises(ValidationError):
        cs.GerarCardapio.model_validate({"dias": 10})
    with pytest.raises(ValidationError):
        cs.RegistrarPeso.model_validate({"peso_kg": 900})
    assert cs.AtualizarPreco.model_validate({"produto": "frango", "preco": 23.9}).unidade == "kg"


def test_write_actions_require_resolution(s):
    p = ps.create_profile(s, "Chat", 30, 80, 180)
    with pytest.raises(ValueError):
        cs.prepare_write(s, p, "atualizar_preco", cs.AtualizarPreco(produto="caviar", preco=10))
    desc, args = cs.prepare_write(s, p, "atualizar_preco", cs.AtualizarPreco(produto="patinho", preco=34.9))
    assert "Patinho" in desc and args["product_id"]
    with pytest.raises(ValueError):
        cs.prepare_write(s, p, "substituir_exercicio", cs.SubstituirExercicio(exercicio_atual="a", novo_exercicio="b"))


def test_tool_declarations_cover_all_tools():
    names = {d.name for d in cs.tool_declarations()[0].function_declarations}
    assert {"gerar_treino", "substituir_exercicio", "registrar_treino", "gerar_cardapio", "substituir_alimento",
            "atualizar_preco", "gerar_lista_compras", "consultar_estoque", "registrar_peso"} <= names


class _FakeModels:
    def __init__(self, failures):
        self.failures, self.calls = list(failures), 0

    def generate_content(self, **kw):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)

        class Resp:
            usage_metadata = None
        return Resp()


def _api_error(cls, code, status):
    return cls(code, {"error": {"code": code, "status": status, "message": "falha simulada"}})


def _fake_client(monkeypatch, failures):
    models = _FakeModels(failures)
    monkeypatch.setattr(gs, "client", lambda: type("C", (), {"models": models})())
    monkeypatch.setattr(gs, "RETRY_DELAYS", (0, 0))
    return models


def test_server_error_is_retried_then_succeeds(s, monkeypatch):
    from google.genai import errors
    models = _fake_client(monkeypatch, [_api_error(errors.ServerError, 503, "UNAVAILABLE")])
    gs._call(s, contents="p", config=None, purpose="t", profile_id=None)
    assert models.calls == 2


def test_server_error_gives_up_with_clear_message(s, monkeypatch):
    from google.genai import errors
    models = _fake_client(monkeypatch, [_api_error(errors.ServerError, 503, "UNAVAILABLE")] * 3)
    with pytest.raises(gs.GeminiUnavailable, match="sobrecarregado"):
        gs._call(s, contents="p", config=None, purpose="t", profile_id=None)
    assert models.calls == 3


def test_client_error_is_not_retried(s, monkeypatch):
    from google.genai import errors
    models = _fake_client(monkeypatch, [_api_error(errors.ClientError, 429, "RESOURCE_EXHAUSTED")])
    with pytest.raises(gs.GeminiUnavailable, match="cota"):
        gs._call(s, contents="p", config=None, purpose="t", profile_id=None)
    assert models.calls == 1


@pytest.fixture(autouse=True)
def no_live_groq(monkeypatch):
    monkeypatch.setattr(gs, "groq_api_key", lambda: None)


def test_gemini_failure_uses_groq(s, monkeypatch):
    from types import SimpleNamespace
    from services import groq_service
    from database.models import AIUsage
    from sqlalchemy import select
    monkeypatch.setattr(gs, "groq_api_key", lambda: "test")
    monkeypatch.setattr(gs, "client", lambda: (_ for _ in ()).throw(gs.GeminiUnavailable("offline")))
    monkeypatch.setattr(groq_service, "generate_content", lambda **kw: SimpleNamespace(text="Olá", usage_metadata=None))
    assert gs.generate_text(s, "oi", purpose="test", profile_id=None) == "Olá"
    assert gs.last_provider(s) == "groq"
    profile = ps.create_profile(s, "Fallback", 30, 80, 180)
    assert gs.save_insight(s, profile.id, "test", "Olá").model == gs.GROQ_MODEL_DEFAULT
    assert s.scalar(select(AIUsage).where(AIUsage.model == gs.GROQ_MODEL_DEFAULT)).ok


def test_invalid_gemini_plan_uses_validated_groq(s, monkeypatch):
    from types import SimpleNamespace
    from services import groq_service
    monkeypatch.setattr(gs, "groq_api_key", lambda: "test")
    monkeypatch.setattr(gs, "_call", lambda *a, **kw: SimpleNamespace(parsed=None, text='{"days": []}'))
    monkeypatch.setattr(groq_service, "generate_content", lambda **kw: SimpleNamespace(
        parsed=None, text='{"days": [{"meals": []}]}', usage_metadata=None))
    plan = gs.generate_structured(s, "p", gs.GMPlan, purpose="test", profile_id=None,
                                  validator=lambda p: [] if p.days else ["faltam dias"])
    assert len(plan.days) == 1
    assert gs.last_provider(s) == "groq"


def test_both_providers_fail(s, monkeypatch):
    from services import groq_service
    monkeypatch.setattr(gs, "groq_api_key", lambda: "test")
    monkeypatch.setattr(gs, "client", lambda: (_ for _ in ()).throw(gs.GeminiUnavailable("offline")))
    monkeypatch.setattr(groq_service, "generate_content", lambda **kw: (_ for _ in ()).throw(ValueError("secret")))
    with pytest.raises(gs.GeminiUnavailable, match="GroqCloud também") as err:
        gs.generate_text(s, "p", purpose="test", profile_id=None)
    assert "secret" not in str(err.value)


def test_groq_adapter_tools_and_usage(monkeypatch):
    from services import groq_service as oa
    from google.genai import types
    import httpx
    monkeypatch.setattr(oa, "groq_api_key", lambda: "test")
    def handle(request):
        import json
        body = json.loads(request.content)
        assert request.url.host == "api.groq.com"
        assert any(t["function"]["name"] == "registrar_peso" for t in body["tools"])
        assert body["messages"][1]["content"] == "registre 80 kg"
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
            "content": None, "tool_calls": [{"type": "function", "function": {
                "name": "registrar_peso", "arguments": '{"peso_kg": 80}'}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    real_client = httpx.Client
    monkeypatch.setattr(oa.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handle)))
    resp = oa.generate_content(contents="registre 80 kg", config=types.GenerateContentConfig(tools=cs.tool_declarations()))
    assert resp.function_calls[0].args == {"peso_kg": 80}
    assert resp.usage_metadata.prompt_token_count == 10
    assert resp.candidates[0].content.parts[0].function_call.name == "registrar_peso"
