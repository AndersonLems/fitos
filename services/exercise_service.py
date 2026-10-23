"""Biblioteca local de exercícios e sincronização com as fontes externas."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from config.settings import logger
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
