"""Instruções de execução em português: dicionário local e tradução a pedido."""
import json

import pytest

from config.settings import DATA_DIR
from database.models import Exercise
from integrations import exercisedb
from services import exercise_service as es
from services import gemini_service as gs
from services.catalog_data import CORE_EXERCISES

CACHE = DATA_DIR / "exercisedb.json"


@pytest.mark.skipif(not CACHE.exists(), reason="catálogo do ExerciseDB não baixado nesta máquina")
def test_all_core_exercises_have_portuguese_steps():
    by_name = {}
    for r in json.loads(CACHE.read_text()):
        n = exercisedb.normalize(r)
        by_name.setdefault(n["name_original"].lower(), n)
    missing = []
    for name, pt, *_ in CORE_EXERCISES:
        ex = Exercise(name_original=name, instructions=by_name[name.lower()]["instructions"])
        steps, translated = es.instructions_pt(ex)
        if not (translated and steps):
            missing.append(pt)
    assert not missing, missing


def test_untranslated_keeps_original_and_saved_translation_wins():
    ex = Exercise(name_original="x", instructions="Do something unusual.\nThen stop.")
    assert es.instructions_pt(ex) == (["Do something unusual.", "Then stop."], False)
    ex.instructions_pt = "Faça algo incomum.\nDepois pare."
    assert es.instructions_pt(ex) == (["Faça algo incomum.", "Depois pare."], True)


def test_translate_with_gemini_saves_and_checks_step_count(s, monkeypatch):
    ex = Exercise(source="exercisedb", source_id="t1", name_original="odd move",
                  instructions="Do something unusual.\nThen stop.")
    s.add(ex)
    s.flush()
    answers = [['{"steps": ["só um passo"]}'], ['{"steps": ["Faça algo incomum.", "Depois pare."]}']]

    class Resp:
        parsed = None
        usage_metadata = None

        def __init__(self, text):
            self.text = text

    calls = []

    def fake_call(sess, **kw):
        calls.append(kw["purpose"])
        return Resp(answers[len(calls) - 1][0])

    monkeypatch.setattr(gs, "_call", fake_call)
    assert es.translate_with_gemini(s, ex.id, None) == ["Faça algo incomum.", "Depois pare."]
    assert calls == ["traducao", "traducao"]  # a primeira resposta tinha passos de menos
    assert es.instructions_pt(ex) == (["Faça algo incomum.", "Depois pare."], True)


def test_muscle_names_in_portuguese():
    assert es.muscle_pt("latissimus dorsi").startswith("latíssimo")
    assert es.muscle_pt("Pectorals") == "peitoral"
    assert es.muscle_pt("unknown thing") == "unknown thing" and es.muscle_pt(None) is None
