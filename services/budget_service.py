"""Orçamento de alimentação: valor fixo do perfil, ajustável mês a mês."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import MonthlyBudget, Profile
from utils.units import money


def month_key(ref: date | None = None) -> str:
    return (ref or date.today()).strftime("%Y-%m")


def month_override(s: Session, profile_id: int, month: str) -> MonthlyBudget | None:
    return s.scalar(select(MonthlyBudget).where(MonthlyBudget.profile_id == profile_id, MonthlyBudget.month == month))


def budget_for(s: Session, profile: Profile, month: str | None = None) -> Decimal | None:
    """Orçamento do mês: o valor definido para aquele mês ou, sem ele, o fixo do perfil."""
    row = month_override(s, profile.id, month or month_key())
    return row.amount if row else profile.monthly_food_budget


def budgets_by_month(s: Session, profile: Profile, months: list[str]) -> dict[str, Decimal | None]:
    rows = {b.month: b.amount for b in s.scalars(select(MonthlyBudget).where(MonthlyBudget.profile_id == profile.id))}
    return {m: rows.get(m, profile.monthly_food_budget) for m in months}


def set_month_budget(s: Session, profile_id: int, month: str, amount) -> None:
    """Define o orçamento de um mês; None volta a usar o valor fixo do perfil."""
    row = month_override(s, profile_id, month)
    if amount in (None, ""):
        if row:
            s.delete(row)
        return
    value = money(amount)
    if value <= 0:
        raise ValueError("O orçamento deve ser maior que zero.")
    if row:
        row.amount = value
    else:
        s.add(MonthlyBudget(profile_id=profile_id, month=month, amount=value))
    s.flush()
