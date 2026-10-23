"""Biblioteca local de exercícios e sincronização com as fontes externas."""
from __future__ import annotations

import json
from functools import lru_cache

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from config.settings import ASSETS_DIR, logger
from database.models import Exercise
from integrations import exercisedb, wger
from integrations.base import IntegrationUnavailable
from services.seed import apply_exercise_curation, upsert_exercises

BODY_PARTS_PT = {
    "chest": "Peito", "back": "Costas", "shoulders": "Ombros", "upper arms": "Braços", "lower arms": "Antebraços",
    "upper legs": "Coxas e glúteos", "lower legs": "Panturrilhas", "waist": "Abdômen", "cardio": "Cardio",
    "neck": "Pescoço",
}
EQUIPMENT_PT = {
    "barbell": "Barra", "dumbbell": "Halteres", "cable": "Polia", "leverage machine": "Máquina",
    "sled machine": "Máquina (leg press/hack)", "smith machine": "Smith", "bodyweight": "Peso corporal",
    "resistance band": "Elástico", "kettlebell": "Kettlebell", "ez bar": "Barra W", "stability ball": "Bola suíça",
    "weighted": "Peso corporal com carga", "assisted": "Máquina assistida", "medicine ball": "Medicine ball",
}

MUSCLES_PT = {
    "abdominals": "abdômen", "abductors": "abdutores", "adductors": "adutores", "ankle stabilizers":
    "estabilizadores do tornozelo", "ankles": "tornozelos", "back": "costas", "biceps": "bíceps", "brachialis":
    "braquial", "calves": "panturrilhas", "cardiovascular system": "sistema cardiovascular", "core": "core",
    "deltoids": "deltoides", "erector spinae": "eretores da coluna", "feet": "pés", "forearms": "antebraços",
    "glutes": "glúteos", "grip muscles": "músculos da pegada", "hamstrings": "posteriores da coxa", "hands": "mãos",
    "hip flexors": "flexores do quadril", "latissimus dorsi": "latíssimo do dorso (dorsal)", "levator scapulae":
    "levantador da escápula", "obliques": "oblíquos", "pectorals": "peitoral", "quadriceps": "quadríceps",
    "rear deltoids": "deltoide posterior", "rhomboids": "romboides", "rotator cuff": "manguito rotador",
    "serratus anterior": "serrátil anterior", "soleus": "sóleo", "sternocleidomastoid": "esternocleidomastoideo",
    "tibialis anterior": "tibial anterior", "trapezius": "trapézio", "triceps": "tríceps", "upper back":
    "parte alta das costas", "wrist extensors": "extensores do punho", "wrist flexors": "flexores do punho",
    "wrists": "punhos",
}


def muscle_pt(name: str | None) -> str | None:
    return MUSCLES_PT.get(name.lower(), name) if name else name


def search(s: Session, text: str = "", body_part: str | None = None, equipment: str | None = None,
           only_core: bool = False, source: str | None = None, limit: int = 60) -> list[Exercise]:
    stmt = select(Exercise)
    if text:
        like = f"%{text.strip()}%"
        stmt = stmt.where(or_(Exercise.name_pt.ilike(like), Exercise.name_original.ilike(like),
                              Exercise.primary_muscle.ilike(like)))
    if body_part:
        stmt = stmt.where(Exercise.body_part == body_part)
    if equipment:
        stmt = stmt.where(Exercise.equipment == equipment)
    if only_core:
        stmt = stmt.where(Exercise.is_core)
    if source:
        stmt = stmt.where(Exercise.source == source)
    stmt = stmt.order_by(Exercise.is_core.desc(), Exercise.name_pt.is_(None), Exercise.name_pt, Exercise.name_original)
    return list(s.scalars(stmt.limit(limit)))


def distinct_values(s: Session, column) -> list[str]:
    return [v for v in s.scalars(select(column).distinct().order_by(column)) if v]


def display_name(e: Exercise) -> str:
    return e.name_pt or e.name_original


@lru_cache(maxsize=2)
def _pt_sentences(kind: str = "revisada") -> dict[str, str]:
    """Tradução frase a frase dos passos do ExerciseDB: "revisada" à mão (cobre os exercícios principais) ou
    "automática" (Argos Translate + glossário, gerada por scripts/traduzir_instrucoes.py)."""
    name = {"revisada": "exercicios_pt.json", "automática": "exercicios_pt_auto.json"}[kind]
    path = ASSETS_DIR / name
    return json.loads(path.read_text()) if path.exists() else {}


def _split(text: str | None) -> list[str]:
    return [x.strip() for x in (text or "").split("\n") if x.strip()]


def instructions_pt(e: Exercise) -> tuple[list[str], str | None]:
    """(passos, origem da tradução). Ordem: salva ("salva") → revisada → automática → original (None)."""
    if e.instructions_pt:
        return _split(e.instructions_pt), "salva"
    steps = _split(e.instructions)
    reviewed, auto = _pt_sentences("revisada"), _pt_sentences("automática")
    if steps and all(x in reviewed for x in steps):
        return [reviewed[x] for x in steps], "revisada"
    if steps and all(x in reviewed or x in auto for x in steps):
        return [reviewed.get(x) or auto[x] for x in steps], "automática"
    return steps, None


class _Steps(BaseModel):
    steps: list[str]


def translate_with_gemini(s: Session, exercise_id: int, profile_id: int | None) -> list[str]:
    """Uma chamada ao Gemini, só a pedido; o resultado fica salvo no exercício."""
    from services import gemini_service as gs

    e = s.get(Exercise, exercise_id)
    steps = _split(e.instructions)
    if not steps:
        return []
    prompt = ("Traduza para o português do Brasil estes passos de execução de um exercício de musculação. Mantenha a "
              "mesma quantidade e ordem de passos, linguagem de academia, frases curtas, sem acrescentar conteúdo.\n"
              f"Exercício: {e.name_original}\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(steps, 1)))
    out = gs.generate_structured(s, prompt, _Steps, purpose="traducao", profile_id=profile_id,
                                 validator=lambda o: [] if len(o.steps) == len(steps) and all(x.strip() for x in o.steps)
                                 else [f"devolva exatamente {len(steps)} passos não vazios"])
    e.instructions_pt = "\n".join(x.strip() for x in out.steps)
    return out.steps


def sync_exercisedb(s: Session) -> tuple[int, str]:
    try:
        rows = [exercisedb.normalize(r) for r in exercisedb.iter_exercises()]
    except IntegrationUnavailable as exc:
        logger.warning("ExerciseDB indisponível: %s", exc)
        return 0, f"ExerciseDB indisponível: {exc}"
    n = upsert_exercises(s, rows)
    missing = apply_exercise_curation(s)
    return n, f"{len(rows)} exercícios verificados, {n} novos." + (f" Curados ausentes: {missing}" if missing else "")


def sync_wger(s: Session) -> tuple[int, str]:
    try:
        rows = [r for r in (wger.normalize(x) for x in wger.iter_exercises()) if r]
    except IntegrationUnavailable as exc:
        logger.warning("wger indisponível: %s", exc)
        return 0, f"wger indisponível: {exc}"
    n = upsert_exercises(s, rows)
    return n, f"{len(rows)} exercícios com mídia no wger, {n} novos."
