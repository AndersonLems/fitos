"""Perfil e estimativas energéticas parametrizadas.

Equação de Mifflin-St Jeor (1990) para gasto basal; fatores de atividade usuais.
Quando falta um dado, o valor usado é marcado como provisório — nunca é apresentado como
informação do usuário.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Measurement, Profile

GOALS = {"emagrecimento": "Emagrecimento", "hipertrofia": "Hipertrofia",
         "recomposicao": "Recomposição corporal", "manutencao": "Manutenção"}
ACTIVITY = {  # fator, rótulo
    "sedentario": (1.2, "Sedentário (pouco ou nenhum exercício)"),
    "leve": (1.375, "Leve (1–3 treinos/semana)"),
    "moderado": (1.55, "Moderado (3–5 treinos/semana)"),
    "intenso": (1.725, "Intenso (6–7 treinos/semana)"),
    "muito_intenso": (1.9, "Muito intenso (trabalho físico + treino)"),
}
EXPERIENCE = {"iniciante": "Iniciante (menos de 6 meses)", "intermediario": "Intermediário (6 meses a 2 anos)",
              "avancado": "Avançado (mais de 2 anos)"}
WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

GOAL_ADJUST = {"emagrecimento": -0.15, "hipertrofia": 0.10, "recomposicao": -0.05, "manutencao": 0.0}
PROTEIN_G_PER_KG = {"emagrecimento": 1.8, "hipertrofia": 1.8, "recomposicao": 2.0, "manutencao": 1.4}
MIN_KCAL = {"F": 1200, "M": 1500, None: 1400}


@dataclass
class EnergyEstimate:
    bmr: float
    tdee: float
    target_kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    provisional: list[str] = field(default_factory=list)
    range_kcal: tuple[float, float] | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_provisional(self) -> bool:
        return bool(self.provisional)


def bmi(weight_kg: float, height_cm: float) -> float:
    h = height_cm / 100
    return weight_kg / (h * h)


def bmi_label(value: float) -> str:
    if value < 18.5:
        return "abaixo da faixa de referência"
    if value < 25:
        return "dentro da faixa de referência"
    if value < 30:
        return "acima da faixa de referência (sobrepeso)"
    return "obesidade pela classificação da OMS"


BMI_CAVEAT = ("O IMC não distingue massa muscular de gordura nem considera distribuição corporal; "
              "é um indicador populacional, não um diagnóstico individual.")


def mifflin(weight_kg: float, height_cm: float, age: int, sex: str | None) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "M":
        return base + 5
    if sex == "F":
        return base - 161
    return base - 78  # média entre as constantes; só usado como provisório


def estimate_energy(p: Profile, weight_kg: float | None = None) -> EnergyEstimate:
    w = weight_kg or p.weight_kg
    prov: list[str] = []
    notes: list[str] = []
    bmr = mifflin(w, p.height_cm, p.age, p.sex)
    rng = None
    if p.sex not in ("M", "F"):
        prov.append("sexo para estimativa fisiológica")
        rng = (mifflin(w, p.height_cm, p.age, "F"), mifflin(w, p.height_cm, p.age, "M"))
    if p.activity_level in ACTIVITY:
        factor = ACTIVITY[p.activity_level][0]
    else:
        factor = 1.2
        prov.append("nível de atividade (usado: sedentário)")
    tdee = bmr * factor
    goal = p.goal if p.goal in GOAL_ADJUST else "manutencao"
    if p.goal not in GOAL_ADJUST:
        prov.append("objetivo (usado: manutenção)")
    target = tdee * (1 + GOAL_ADJUST[goal])
    floor = max(MIN_KCAL[p.sex if p.sex in ("M", "F") else None], bmr)
    if goal == "emagrecimento" and target < floor:
        target = floor
        notes.append("Meta limitada para não ficar abaixo do gasto basal estimado (sem restrição excessiva).")
    # proteína pelo peso; com IMC ≥ 30 usa o peso correspondente a IMC 27 (evita superestimar)
    ref_w = w
    if bmi(w, p.height_cm) >= 30:
        ref_w = 27 * (p.height_cm / 100) ** 2
        notes.append("Proteína calculada sobre peso de referência (IMC 27), pois o IMC atual é ≥ 30.")
    protein = PROTEIN_G_PER_KG[goal] * ref_w
    fat = max(0.6 * ref_w, target * 0.25 / 9)
    carbs = max(0.0, (target - protein * 4 - fat * 9) / 4)
    if rng:
        rng = tuple(round(x * factor * (1 + GOAL_ADJUST[goal])) for x in rng)
    return EnergyEstimate(round(bmr), round(tdee), round(target), round(protein), round(fat), round(carbs),
                          prov, rng, notes)


def missing_for_personalization(p: Profile) -> list[str]:
    checks = [("sexo para estimativas", p.sex), ("objetivo", p.goal), ("nível de atividade", p.activity_level),
              ("experiência de treino", p.experience), ("dias disponíveis", p.training_weekdays),
              ("tempo por treino", p.session_minutes), ("equipamentos", p.equipment)]
    return [label for label, v in checks if not v]


def list_profiles(s: Session) -> list[Profile]:
    return list(s.scalars(select(Profile).order_by(Profile.name)))


def create_profile(s: Session, name: str, age: int, weight_kg: float, height_cm: float) -> Profile:
    validate_basics(age, weight_kg, height_cm)
    name = (name or "").strip()
    if not name:
        raise ValueError("Informe um nome para o perfil.")
    p = Profile(name=name[:80], age=int(age), weight_kg=float(weight_kg), height_cm=float(height_cm), people_count=1)
    s.add(p)
    s.flush()
    s.add(Measurement(profile_id=p.id, measured_on=date.today(), weight_kg=float(weight_kg),
                      notes="Peso informado no cadastro"))
    return p


def validate_basics(age, weight_kg, height_cm) -> None:
    if not (12 <= int(age) <= 100):
        raise ValueError("Idade deve estar entre 12 e 100 anos.")
    if not (30 <= float(weight_kg) <= 300):
        raise ValueError("Peso deve estar entre 30 e 300 kg.")
    if not (120 <= float(height_cm) <= 230):
        raise ValueError("Altura deve estar entre 120 e 230 cm.")


def latest_weight(s: Session, profile_id: int) -> float | None:
    return s.scalar(select(Measurement.weight_kg).where(
        Measurement.profile_id == profile_id, Measurement.weight_kg.is_not(None))
        .order_by(Measurement.measured_on.desc(), Measurement.id.desc()).limit(1))


def record_weight(s: Session, profile_id: int, weight_kg: float, on: date | None = None, notes: str | None = None) -> Measurement:
    if not (30 <= float(weight_kg) <= 300):
        raise ValueError("Peso deve estar entre 30 e 300 kg.")
    m = Measurement(profile_id=profile_id, measured_on=on or date.today(), weight_kg=float(weight_kg), notes=notes)
    s.add(m)
    p = s.get(Profile, profile_id)
    if p and (on is None or on >= date.today()):
        p.weight_kg = float(weight_kg)
    return m
