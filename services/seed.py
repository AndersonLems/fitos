"""Carga inicial: TACO, catálogo de exercícios e produtos-base (sem preços)."""
from __future__ import annotations

import csv
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import ASSETS_DIR, DATA_DIR, logger
from database.models import Exercise, Food, FoodNutrients, Product
from integrations import exercisedb
from services.catalog_data import (
    COMMON_ERRORS, CORE_EXERCISES, CORE_FOODS, DEFAULT_PRODUCTS, EDIBLE_SOURCE, YIELD_REFERENCE,
    YIELD_REFERENCE_SOURCE, YIELD_SOURCE,
)

TACO_SOURCE = "TACO 4ª ed. (NEPA/UNICAMP, 2011)"


def _f(v: str | None) -> float | None:
    v = (v or "").strip()
    if not v or v.upper() in {"NA", "TR", "*"}:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _state_from_name(name: str) -> str:
    n = name.lower()
    if re.search(r"\b(cru|crua|crus)\b", n):
        return "cru"
    if re.search(r"cozid|grelhad|assad|frit|refogad", n):
        return "cozido"
    return "pronto"


def seed_foods(s: Session) -> int:
    if s.scalar(select(Food.id).limit(1)):
        return 0
    cats = {r["id"]: r["name"] for r in csv.DictReader(open(ASSETS_DIR / "taco/categories.csv", encoding="utf-8"))}
    nut = {r["foodId"]: r for r in csv.DictReader(open(ASSETS_DIR / "taco/nutrients.csv", encoding="utf-8"))}
    by_taco: dict[int, Food] = {}
    for r in csv.DictReader(open(ASSETS_DIR / "taco/food.csv", encoding="utf-8")):
        n = nut.get(r["id"], {})
        food = Food(taco_id=int(r["id"]), name=r["name"].strip(), category=cats.get(r["categoryId"]),
                    state=_state_from_name(r["name"]), source=TACO_SOURCE, edible_factor=1.0)
        food.nutrients = FoodNutrients(
            kcal=_f(n.get("kcal")), protein_g=_f(n.get("protein")), carbs_g=_f(n.get("carbohydrates")),
            fat_g=_f(n.get("lipids")), fiber_g=_f(n.get("dietaryFiber")), sodium_mg=_f(n.get("sodium")),
            moisture_g=_f(n.get("moisture")))
        s.add(food)
        by_taco[food.taco_id] = food
    s.flush()
    for taco_id, short, group, state, raw_id, edible in CORE_FOODS:
        f = by_taco[taco_id]
        f.short_name, f.group, f.state, f.is_core = short, group, state, True
        if edible:
            f.edible_factor, f.edible_source = edible, EDIBLE_SOURCE
        if raw_id:
            raw = by_taco[raw_id]
            f.raw_food_id = raw.id
            mr, mc = raw.nutrients.moisture_g, f.nutrients.moisture_g
            if taco_id in YIELD_REFERENCE:
                f.yield_factor, f.yield_source = YIELD_REFERENCE[taco_id], YIELD_REFERENCE_SOURCE
            elif mr is not None and mc is not None and mc < 100:
                f.yield_factor = round(max(0.4, min(3.5, (100 - mr) / (100 - mc))), 2)
                f.yield_source = YIELD_SOURCE
    logger.info("TACO carregada: %s alimentos", len(by_taco))
    return len(by_taco)


def upsert_exercises(s: Session, rows: list[dict]) -> int:
    existing = {(e.source, e.source_id): e for e in s.scalars(select(Exercise))}
    n = 0
    for row in rows:
        key = (row["source"], row["source_id"])
        ex = existing.get(key)
        if ex is None:
            ex = Exercise(**row)
            s.add(ex)
            existing[key] = ex
            n += 1
        else:
            for k, v in row.items():
                if k != "name_pt" or v:  # não sobrescrever tradução curada
                    setattr(ex, k, v)
    s.flush()
    return n


def apply_exercise_curation(s: Session) -> list[str]:
    """Marca os exercícios curados; devolve os nomes não encontrados no catálogo."""
    by_name: dict[str, Exercise] = {}
    for e in s.scalars(select(Exercise).where(Exercise.source == exercisedb.SOURCE).order_by(Exercise.id)):
        by_name.setdefault(e.name_original.lower(), e)
    missing = []
    for name, pt, slot, diff in CORE_EXERCISES:
        e = by_name.get(name.lower())
        if not e:
            missing.append(name)
            continue
        e.name_pt, e.slot, e.difficulty, e.is_core = pt, slot, diff, True
        e.common_errors = COMMON_ERRORS.get(slot)
    if missing:
        logger.warning("exercícios curados ausentes no catálogo: %s", missing)
    return missing


def seed_exercises(s: Session, allow_network: bool = True) -> int:
    if s.scalar(select(Exercise.id).limit(1)):
        return 0
    cache = DATA_DIR / "exercisedb.json"
    if cache.exists():
        raw = json.loads(cache.read_text())
    elif allow_network:
        raw = list(exercisedb.iter_exercises())
        cache.write_text(json.dumps(raw, ensure_ascii=False))
    else:
        return 0
    n = upsert_exercises(s, [exercisedb.normalize(r) for r in raw])
    apply_exercise_curation(s)
    return n


def seed_products(s: Session) -> int:
    if s.scalar(select(Product.id).limit(1)):
        return 0
    foods = {f.taco_id: f for f in s.scalars(select(Food).where(Food.taco_id.is_not(None)))}
    for name, cat, taco_id, gpu, dens in DEFAULT_PRODUCTS:
        s.add(Product(name=name, category=cat, food_id=foods[taco_id].id, grams_per_unit=gpu, density_g_ml=dens))
    return len(DEFAULT_PRODUCTS)


def seed_all(s: Session, allow_network: bool = True) -> dict:
    out = {"foods": seed_foods(s)}
    s.flush()
    out["products"] = seed_products(s)
    try:
        out["exercises"] = seed_exercises(s, allow_network)
    except Exception as exc:  # catálogo externo indisponível não impede o app de abrir
        logger.warning("catálogo de exercícios não carregado: %s", exc)
        out["exercises"] = 0
    return out
