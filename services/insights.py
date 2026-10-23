"""Fatos agregados do perfil e recomendações por regras (sem IA)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Measurement, Profile, Purchase, WorkoutSession
from services import nutrition_service as ns
from services import profile_service as ps
from services.budget_service import budget_for
from services import workout_service as ws
from services.inventory_service import expiring, list_items
from utils.units import money


def weights_df(s: Session, profile_id: int) -> pd.DataFrame:
    rows = s.execute(select(Measurement.measured_on, Measurement.weight_kg).where(
        Measurement.profile_id == profile_id, Measurement.weight_kg.is_not(None))
        .order_by(Measurement.measured_on, Measurement.id)).all()
    df = pd.DataFrame(rows, columns=["data", "peso"])
    if not df.empty:
        df = df.groupby("data", as_index=False).last()
        df["data"] = pd.to_datetime(df["data"])
        df["media7"] = df.set_index("data")["peso"].rolling("7D").mean().values
    return df


def weekly_sessions(s: Session, profile_id: int, weeks: int = 8) -> pd.DataFrame:
    start = date.today() - timedelta(days=date.today().weekday() + 7 * (weeks - 1))
    rows = s.scalars(select(WorkoutSession.performed_on).where(
        WorkoutSession.profile_id == profile_id, WorkoutSession.performed_on >= start,
        WorkoutSession.finished_at.is_not(None))).all()
    idx = [start + timedelta(days=7 * i) for i in range(weeks)]
    counts = {d: 0 for d in idx}
    for d in rows:
        counts[d - timedelta(days=d.weekday())] = counts.get(d - timedelta(days=d.weekday()), 0) + 1
    return pd.DataFrame({"semana": list(counts), "treinos": list(counts.values())})


def month_spending(s: Session, profile_id: int, ref: date | None = None) -> Decimal:
    ref = ref or date.today()
    start = ref.replace(day=1)
    vals = s.scalars(select(Purchase.amount).where(Purchase.profile_id == profile_id,
                                                   Purchase.purchased_on >= start)).all()
    return money(sum(vals, Decimal(0)))


@dataclass
class Facts:
    profile: Profile
    weight: float
    energy: ps.EnergyEstimate
    weights: pd.DataFrame
    sessions_week: int
    planned_week: int
    today_title: str | None
    plan_cost_daily: Decimal | None
    plan_unpriced: int
    month_spent: Decimal
    consumed: ns.Macros
    expiring: list[str]
    missing: list[str]
    month_budget: Decimal | None = None  # orçamento do mês corrente (ajuste do mês ou fixo do perfil)

    def as_dict(self) -> dict:
        w = self.weights
        trend = None
        if len(w) >= 2:
            last30 = w[w["data"] >= w["data"].max() - pd.Timedelta(days=30)]
            if len(last30) >= 2:
                trend = round(float(last30["peso"].iloc[-1] - last30["peso"].iloc[0]), 1)
        return {"peso_atual": self.weight, "variacao_30d_kg": trend, "meta_peso": self.profile.target_weight_kg,
                "meta_kcal": self.energy.target_kcal, "meta_proteina_g": self.energy.protein_g,
                "estimativa_provisoria": self.energy.provisional, "treinos_semana": self.sessions_week,
                "treinos_previstos_semana": self.planned_week, "treino_hoje": self.today_title,
                "custo_cardapio_dia": str(self.plan_cost_daily) if self.plan_cost_daily is not None else None,
                "itens_sem_preco": self.plan_unpriced, "gasto_mes": str(self.month_spent),
                "orcamento_mes": str(self.month_budget) if self.month_budget else None,
                "consumido_hoje_kcal": round(self.consumed.kcal), "vencendo": self.expiring,
                "dados_faltando": self.missing}


def collect(s: Session, p: Profile) -> Facts:
    weight = ps.latest_weight(s, p.id) or p.weight_kg
    energy = ps.estimate_energy(p, weight)
    plan = ws.active_plan(s, p.id)
    today_title = None
    planned_week = 0
    if plan:
        t = ws.todays_workout(s, p.id, plan)
        today_title = t.day.title if t.day else None
        planned_week = len(plan.days)
    mp = ns.active_plan(s, p.id)
    cost_daily, unpriced = None, 0
    if mp:
        sm = ns.summarize(s, mp)
        cost_daily, unpriced = sm.avg_daily_cost(), len(sm.unpriced)
    consumed, _ = ns.consumed(s, p.id)
    exp = [i.food.short_name or i.food.name for i in expiring(list_items(s, p.id))]
    return Facts(p, weight, energy, weights_df(s, p.id), ws.sessions_in_week(s, p.id), planned_week, today_title,
                 cost_daily, unpriced, month_spending(s, p.id), consumed, exp, ps.missing_for_personalization(p),
                 budget_for(s, p))


def rule_recommendations(f: Facts) -> list[str]:
    out = []
    if f.missing:
        out.append("Complete em Meu Perfil: " + ", ".join(f.missing[:4]) + " — as estimativas ficam mais precisas.")
    w = f.weights
    if len(w) < 2:
        out.append("Registre o peso 2–3 vezes por semana, no mesmo horário, para enxergar a tendência real.")
    elif f.profile.goal == "emagrecimento" and len(w) >= 4:
        last = w[w["data"] >= w["data"].max() - pd.Timedelta(days=28)]
        if len(last) >= 3:
            weekly = (last["media7"].iloc[-1] - last["media7"].iloc[0]) / max(1, (last["data"].iloc[-1] - last["data"].iloc[0]).days) * 7
            if weekly < -0.01 * f.weight:
                out.append("A média de peso está caindo mais de 1% por semana. Considere reduzir o déficit para "
                           "preservar massa muscular.")
            elif weekly > -0.001 * f.weight:
                out.append("A média de peso está estável há 4 semanas. Revise a adesão ao cardápio antes de "
                           "reduzir calorias.")
    if f.planned_week and f.sessions_week < f.planned_week and date.today().weekday() >= 4:
        out.append(f"{f.sessions_week} de {f.planned_week} treinos feitos nesta semana. Se a rotina apertou, "
                   "use “mudar treino de hoje” para priorizar o dia mais importante.")
    if f.plan_unpriced:
        out.append(f"{f.plan_unpriced} alimento(s) do cardápio estão sem preço cadastrado; o custo exibido está "
                   "incompleto.")
    b = f.month_budget
    if b and f.plan_cost_daily is not None and f.plan_cost_daily * 30 * max(1, f.profile.people_count or 1) > b:
        out.append("O cardápio ativo projeta gasto acima do orçamento mensal. Gere a versão econômica em "
                   "Meu Plano Alimentar.")
    if f.expiring:
        out.append("Vencendo em até 3 dias: " + ", ".join(f.expiring[:5]) + ". Use em “O que posso preparar hoje?”.")
    if not out:
        out.append("Tudo em dia. Mantenha os registros de treino e peso para as próximas análises.")
    return out
