"""Estoque doméstico (despensa)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from database.models import Food, InventoryItem
from utils.units import D, UnitError, normalize_unit


def list_items(s: Session, profile_id: int) -> list[InventoryItem]:
    return list(s.scalars(select(InventoryItem).where(InventoryItem.profile_id == profile_id)
                          .options(joinedload(InventoryItem.food)).order_by(InventoryItem.expires_on.is_(None),
                                                                           InventoryItem.expires_on)))


def add_item(s: Session, profile_id: int, food_id: int, quantity, unit: str, *, expires_on: date | None = None,
             grams_per_unit: float | None = None, notes: str | None = None) -> InventoryItem:
    if not s.get(Food, food_id):
        raise UnitError("Alimento inexistente.")
    q = D(quantity)
    if q <= 0:
        raise UnitError("Quantidade deve ser maior que zero.")
    u = normalize_unit(unit)
    if u in ("un", "duzia") and not grams_per_unit:
        raise UnitError("Para itens em unidade informe o peso médio por unidade (g), usado nas conversões.")
    it = InventoryItem(profile_id=profile_id, food_id=food_id, quantity=q, unit=u, expires_on=expires_on,
                       grams_per_unit=grams_per_unit or None, notes=notes or None)
    s.add(it)
    s.flush()
    return it


def update_quantity(s: Session, item_id: int, profile_id: int, quantity) -> None:
    it = s.get(InventoryItem, item_id)
    if not it or it.profile_id != profile_id:
        raise UnitError("Item não encontrado.")
    q = D(quantity)
    if q < 0:
        raise UnitError("Quantidade inválida.")
    if q == 0:
        s.delete(it)
    else:
        it.quantity = q


def expiring(items: list[InventoryItem], days: int = 3) -> list[InventoryItem]:
    lim = date.today() + timedelta(days=days)
    return [i for i in items if i.expires_on and i.expires_on <= lim]


def stock_summary_text(items: list[InventoryItem]) -> str:
    """Resumo compacto para contexto de IA."""
    parts = []
    for i in items:
        exp = f", vence {i.expires_on:%d/%m}" if i.expires_on else ""
        parts.append(f"{i.food.short_name or i.food.name} [id {i.food_id}]: {Decimal(i.quantity):g} {i.unit}{exp}")
    return "; ".join(parts) or "estoque vazio"
