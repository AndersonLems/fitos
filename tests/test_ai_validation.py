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
