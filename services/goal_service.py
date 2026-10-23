"""Prazo para a meta de peso: três cenários (conservador, mais rápido, intenso).

O Python calcula tudo pelo balanço energético (≈7.700 kcal por kg de tecido, aproximação usual):
- perda: ritmo em % do peso por semana, com as calorias recalculadas a cada 4 semanas para manter o
  ritmo; nunca abaixo do piso (gasto basal estimado ou 1.200/1.500 kcal);
- ganho: superávit fixo; parte do ganho é gordura e o ritmo real depende do treino.
A IA, a pedido, só revisa dentro de limites (±150 kcal, 3–6 refeições) e escreve a análise; o Python
valida e recalcula prazos e macros depois da revisão.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import GoalPlan, Profile
from services import profile_service as ps

KCAL_PER_KG = 7700
KEYS = ["conservador", "rapido", "intenso"]
LABELS = {"conservador": "Conservador", "rapido": "Mais rápido", "intenso": "Intenso"}
LOSS_RATE = {"conservador": 0.005, "rapido": 0.0075, "intenso": 0.01}  # fração do peso por semana
GAIN_SURPLUS = {"conservador": 200, "rapido": 350, "intenso": 500}  # kcal/dia
PROTEIN_LOSS = {"conservador": 1.8, "rapido": 2.0, "intenso": 2.2}  # g/kg: déficit maior, mais proteína
PROTEIN_GAIN = {"conservador": 1.6, "rapido": 1.8, "intenso": 2.0}
MAX_AI_ADJUST = 150
MEALS_RANGE = (3, 6)
MAX_WEEKS = 260
CAVEATS = {
    "conservador": "Ritmo sustentável, com pouca fome extra e melhor preservação de massa muscular.",
    "rapido": "Exige mais adesão; mantenha a proteína alta e o treino de força.",
    "intenso": "Limite superior usual. Mais fome e cansaço; reavalie se o treino ou o sono piorarem. "
               "Com doenças, medicação ou histórico de transtorno alimentar, só com acompanhamento profissional.",
}


@dataclass
class Scenario:
    key: str
    label: str
    kcal: int
    protein_g: int
    fat_g: int
    carbs_g: int
    meals_per_day: int
    weekly_kg: float  # negativo = perda
    weeks: int
    target_date: str  # ISO
    notes: list[str] = field(default_factory=list)
    tips: str | None = None

    @property
    def date(self) -> date:
        return date.fromisoformat(self.target_date)


def default_meals(kcal: float) -> int:
    return 3 if kcal < 1600 else 4 if kcal < 2600 else 5 if kcal < 3200 else 6


def _macros(p: Profile, weight: float, kcal: float, protein_per_kg: float) -> tuple[int, int, int]:
    ref_w = 27 * (p.height_cm / 100) ** 2 if ps.bmi(weight, p.height_cm) >= 30 else weight
    protein = protein_per_kg * ref_w
    fat = max(0.6 * ref_w, kcal * 0.25 / 9)
    carbs = max(0.0, (kcal - protein * 4 - fat * 9) / 4)
    return round(protein), round(fat), round(carbs)


def kcal_floor(p: Profile, weight: float) -> float:
    e = ps.estimate_energy(p, weight)
    return max(ps.MIN_KCAL[p.sex if p.sex in ("M", "F") else None], e.bmr)


def build(p: Profile, weight: float, key: str, kcal: float | None = None, meals: int | None = None,
          tips: str | None = None) -> Scenario:
    """Cenário a partir do ritmo padrão da chave ou, se `kcal` vier (revisão da IA), dessas calorias."""
    target = p.target_weight_kg
    e = ps.estimate_energy(p, weight)
    tdee, floor = e.tdee, kcal_floor(p, weight)
    notes: list[str] = []
    today = date.today()
    if target < weight:
        if kcal is None:
            kcal = tdee - LOSS_RATE[key] * weight * KCAL_PER_KG / 7
        if kcal < floor:
            kcal = floor
            notes.append("Calorias limitadas ao piso de segurança; o ritmo ficou menor que o padrão deste cenário.")
        deficit = tdee - kcal
        if deficit < 50:
            raise ValueError("O gasto estimado já está perto do piso de calorias: não há déficit seguro para "
                             "calcular um prazo. Revise o nível de atividade no perfil.")
        rate = deficit * 7 / KCAL_PER_KG / weight  # fração do peso por semana, mantida com reajustes
        weeks = math.ceil(math.log(target / weight) / math.log(1 - rate))
        weekly = -rate * weight
        protein, fat, carbs = _macros(p, weight, kcal, PROTEIN_LOSS[key])
    else:
        if kcal is None:
            kcal = tdee + GAIN_SURPLUS[key]
        surplus = kcal - tdee
        if surplus < 50:
            raise ValueError("Para ganhar peso as calorias precisam ficar acima do gasto estimado.")
        weekly = surplus * 7 / KCAL_PER_KG
        weeks = math.ceil((target - weight) / weekly)
        notes.append("Parte do ganho é gordura; com treino de força consistente a proporção de músculo é maior.")
        protein, fat, carbs = _macros(p, weight, kcal, PROTEIN_GAIN[key])
    if weeks > MAX_WEEKS:
        notes.append("Prazo acima de 5 anos: considere metas intermediárias.")
        weeks = MAX_WEEKS
    if e.provisional:
        notes.append("Estimativa provisória (faltam: " + ", ".join(e.provisional) + ").")
    meals = meals or default_meals(kcal)
    return Scenario(key, LABELS[key], round(kcal), protein, fat, carbs, meals, round(weekly, 2), weeks,
                    (today + timedelta(weeks=weeks)).isoformat(), notes, tips)


def compute(p: Profile, weight: float) -> list[Scenario]:
    if not p.target_weight_kg:
        raise ValueError("Defina a meta de peso em Meu perfil para calcular os prazos.")
    if abs(p.target_weight_kg - weight) < 0.5:
        raise ValueError("A meta está a menos de 0,5 kg do peso atual: o foco agora é manutenção.")
    return [build(p, weight, k) for k in KEYS]


def apply_review(p: Profile, weight: float, base: list[Scenario], review) -> tuple[list[Scenario], list[str]]:
    """Aplica a revisão da IA dentro dos limites; devolve os cenários e os ajustes recusados."""
    by_key = {r.key: r for r in review.scenarios}
    rejected: list[str] = []
    out = []
    for sc in base:
        r = by_key.get(sc.key)
        if r is None:
            out.append(sc)
            continue
        adj = max(-MAX_AI_ADJUST, min(MAX_AI_ADJUST, r.kcal_adjust))
        if adj != r.kcal_adjust:
            rejected.append(f"{sc.label}: ajuste de {r.kcal_adjust} kcal limitado a {adj:+d}")
        meals = min(MEALS_RANGE[1], max(MEALS_RANGE[0], r.meals_per_day))
        try:
            out.append(build(p, weight, sc.key, kcal=sc.kcal + adj, meals=meals, tips=(r.tips or "").strip() or None))
        except ValueError as exc:
            rejected.append(f"{sc.label}: {exc}")
            out.append(sc)
    return out, rejected


def save(s: Session, p: Profile, weight: float, scenarios: list[Scenario], *, chosen: str | None = None,
         analysis: str | None = None, origin: str = "local") -> GoalPlan:
    for old in s.scalars(select(GoalPlan).where(GoalPlan.profile_id == p.id, GoalPlan.is_active)):
        old.is_active = False
    e = ps.estimate_energy(p, weight)
    gp = GoalPlan(profile_id=p.id, start_weight_kg=weight, target_weight_kg=p.target_weight_kg, tdee_kcal=e.tdee,
                  scenarios=[asdict(x) for x in scenarios], chosen=chosen if chosen in KEYS else "conservador",
                  analysis=analysis, origin=origin)
    s.add(gp)
    s.flush()
    return gp


def active(s: Session, profile_id: int) -> GoalPlan | None:
    return s.scalar(select(GoalPlan).where(GoalPlan.profile_id == profile_id, GoalPlan.is_active)
                    .order_by(GoalPlan.id.desc()).limit(1))


def scenarios_of(gp: GoalPlan) -> list[Scenario]:
    return [Scenario(**x) for x in gp.scenarios]


def chosen_scenario(gp: GoalPlan | None) -> Scenario | None:
    if gp is None:
        return None
    return next((x for x in scenarios_of(gp) if x.key == gp.chosen), None)


def expected_weight(gp: GoalPlan, sc: Scenario, on: date | None = None) -> float:
    """Peso esperado numa data pelo cenário (perda proporcional ao peso; ganho linear)."""
    weeks = max(0.0, ((on or date.today()) - gp.created_at.date()).days / 7)
    w0, target = gp.start_weight_kg, gp.target_weight_kg
    if target < w0:
        rate = -sc.weekly_kg / w0
        return max(target, w0 * (1 - rate) ** weeks)
    return min(target, w0 + sc.weekly_kg * weeks)


def is_stale(gp: GoalPlan, p: Profile, weight: float) -> str | None:
    """Motivo para recalcular (meta mudou, peso andou muito ou o plano está velho)."""
    if p.target_weight_kg != gp.target_weight_kg:
        return "a meta de peso mudou"
    if (date.today() - gp.created_at.date()).days >= 28:
        return "já se passaram 4 semanas (o gasto muda com o peso)"
    if abs(weight - gp.start_weight_kg) >= 3:
        return "o peso mudou mais de 3 kg desde o cálculo"
    return None


def context_line(gp: GoalPlan | None) -> str | None:
    """Resumo do cenário escolhido para os prompts da IA."""
    sc = chosen_scenario(gp)
    if sc is None:
        return None
    return (f"Plano de meta ({sc.label.lower()}): de {gp.start_weight_kg:g} kg para {gp.target_weight_kg:g} kg até "
            f"{sc.date:%d/%m/%Y} ({sc.weekly_kg:+.2f} kg/semana); {sc.kcal} kcal/dia, proteína {sc.protein_g} g, "
            f"gordura {sc.fat_g} g, carboidratos {sc.carbs_g} g, {sc.meals_per_day} refeições por dia.")


def weight_trend(weights) -> dict:
    """Ritmo registrado nas últimas 4 semanas (média móvel), para a análise e para a tela."""
    if weights is None or len(weights) < 2:
        return {"pesagens": 0 if weights is None else len(weights), "kg_semana_4sem": None}
    last = weights[weights["data"] >= weights["data"].max() - timedelta(days=28)]
    days = (last["data"].iloc[-1] - last["data"].iloc[0]).days if len(last) >= 2 else 0
    rate = None
    if days >= 7:
        rate = round(float(last["media7"].iloc[-1] - last["media7"].iloc[0]) / days * 7, 2)
    return {"pesagens": int(len(weights)), "pesagens_4sem": int(len(last)), "kg_semana_4sem": rate}


@dataclass
class DailyTargets:
    kcal: int
    protein_g: int
    fat_g: int
    carbs_g: int
    meals_per_day: int
    source: str  # rótulo do cenário ou "estimativa"


def daily_targets(s: Session, p: Profile, weight: float | None = None) -> DailyTargets:
    """Metas do dia: as do cenário escolhido no plano de meta ou, sem ele, a estimativa do perfil."""
    sc = chosen_scenario(active(s, p.id))
    if sc:
        return DailyTargets(sc.kcal, sc.protein_g, sc.fat_g, sc.carbs_g, sc.meals_per_day, sc.label)
    e = ps.estimate_energy(p, weight)
    return DailyTargets(round(e.target_kcal), round(e.protein_g), round(e.fat_g), round(e.carbs_g), 4, "estimativa")
