"""Planos de treino, versões, sessões, registro de séries e progressão conservadora."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from database.models import (
    DayOverride, Exercise, PlannedExercise, Profile, SetLog, WorkoutDay, WorkoutPlan, WorkoutSession,
)
from services.catalog_data import EQUIPMENT_GROUPS
from services.profile_service import WEEKDAYS

COMPOUND = {"chest_press", "chest_incline", "vertical_pull", "row", "squat", "leg_press", "hinge", "lunge",
            "shoulder_press"}
LOWER = {"squat", "leg_press", "hinge", "lunge", "knee_ext", "knee_flex", "glute", "calf"}

# dias-modelo: título e padrões de movimento em ordem
DAY_TEMPLATES = {
    "full_a": ("CORPO INTEIRO A", ["squat", "chest_press", "row", "shoulder_press", "knee_flex", "core"]),
    "full_b": ("CORPO INTEIRO B", ["hinge", "chest_incline", "vertical_pull", "lunge", "lateral_raise", "core"]),
    "full_c": ("CORPO INTEIRO C", ["leg_press", "chest_press", "row", "glute", "biceps", "triceps"]),
    "upper_a": ("SUPERIORES A — PEITO, COSTAS E OMBROS", ["chest_press", "row", "shoulder_press", "vertical_pull",
                                                         "lateral_raise", "triceps", "biceps"]),
    "lower_a": ("INFERIORES A — QUADRÍCEPS E GLÚTEOS", ["squat", "hinge", "leg_press", "knee_ext", "calf", "core"]),
    "upper_b": ("SUPERIORES B — COSTAS, PEITO E BRAÇOS", ["vertical_pull", "chest_incline", "row", "chest_fly",
                                                         "rear_delt", "biceps", "triceps"]),
    "lower_b": ("INFERIORES B — POSTERIORES E GLÚTEOS", ["hinge", "lunge", "knee_flex", "glute", "calf", "core"]),
    "push": ("PEITO, OMBROS E TRÍCEPS", ["chest_press", "chest_incline", "shoulder_press", "chest_fly",
                                        "lateral_raise", "triceps"]),
    "pull": ("COSTAS, POSTERIOR DE OMBRO E BÍCEPS", ["vertical_pull", "row", "row", "rear_delt", "biceps", "biceps"]),
    "legs": ("PERNAS E CORE", ["squat", "leg_press", "hinge", "knee_flex", "calf", "core"]),
}
SPLITS = {
    1: ["full_a"], 2: ["full_a", "full_b"], 3: ["full_a", "full_b", "full_c"],
    4: ["upper_a", "lower_a", "upper_b", "lower_b"], 5: ["push", "pull", "legs", "upper_a", "lower_b"],
    6: ["push", "pull", "legs", "push", "pull", "legs"], 7: ["push", "pull", "legs", "push", "pull", "legs"],
}
INJURY_RULES = {  # palavra no texto de limitações -> (padrões evitados, equipamentos evitados nesses padrões)
    "joelho": ({"lunge"}, set()),
    "lombar": ({"hinge"}, {"barbell"}),
    "coluna": ({"hinge"}, {"barbell"}),
    "hérnia": ({"hinge"}, {"barbell"}),
    "ombro": ({"lateral_raise"}, {"barbell"}),
    "punho": (set(), {"barbell"}),
    "cotovelo": (set(), {"barbell"}),
}


def allowed_equipment(profile: Profile) -> set[str] | None:
    groups = profile.equipment or []
    if not groups:
        return None  # não informado: sem filtro (academia comum presumida apenas na ficha local, e avisado)
    eq = set()
    for g in groups:
        eq |= EQUIPMENT_GROUPS.get(g, set())
    return eq


def core_exercises(s: Session) -> list[Exercise]:
    return list(s.scalars(select(Exercise).where(Exercise.is_core).order_by(Exercise.id)))


def _injury_filters(profile: Profile) -> tuple[set[str], dict[str, set[str]], list[str]]:
    txt = (profile.injuries or "").lower()
    avoid_slots: set[str] = set()
    avoid_equip: dict[str, set[str]] = {}
    notes = []
    for kw, (slots, equips) in INJURY_RULES.items():
        if kw in txt:
            avoid_slots |= slots
            for sl in ({"squat", "hinge", "row", "shoulder_press"} if equips else set()):
                avoid_equip.setdefault(sl, set()).update(equips)
            notes.append(kw)
    return avoid_slots, avoid_equip, notes


def pick_exercise(options: list[Exercise], slot: str, variant: int, *, equipment: set[str] | None,
                  experience: str | None, avoid_equip: dict[str, set[str]], used: set[int]) -> Exercise | None:
    opts = [e for e in options if e.slot == slot and e.id not in used]
    if equipment is not None:
        opts = [e for e in opts if (e.equipment or "") in equipment] or []
    if experience in (None, "iniciante"):
        opts = [e for e in opts if e.difficulty != "avançado"] or opts
    bad = avoid_equip.get(slot, set())
    opts = [e for e in opts if (e.equipment or "") not in bad] or opts
    if not opts:
        return None
    return opts[variant % len(opts)]


def prescription(slot: str, experience: str | None, goal: str | None) -> tuple[int, int, int, int]:
    """(séries, reps mín, reps máx, descanso s) — prescrição conservadora."""
    sets = {"iniciante": 2, None: 3, "intermediario": 3, "avancado": 4}.get(experience, 3)
    if slot == "cardio":
        return 1, 10, 20, 0  # minutos
    if slot == "core":
        return min(sets, 3), 10, 15, 60
    if slot in COMPOUND:
        lo, hi = (6, 10) if experience == "avancado" and goal == "hipertrofia" else (8, 12)
        return sets, lo, hi, 120 if slot in LOWER else 90
    return sets, 10, 15, 60


def _estimate_minutes(items: list[tuple[int, int]]) -> float:
    return sum(sets * (40 + rest) / 60 + 1.5 for sets, rest in items)


@dataclass
class DraftExercise:
    exercise: Exercise
    sets: int
    reps_min: int
    reps_max: int
    rest: int
    notes: str | None = None


@dataclass
class DraftDay:
    title: str
    weekday: int | None
    exercises: list[DraftExercise]


def local_plan_draft(s: Session, profile: Profile) -> tuple[list[DraftDay], list[str]]:
    """Ficha determinística a partir do perfil (sem IA). Devolve dias e avisos."""
    warnings = []
    weekdays = sorted(profile.training_weekdays or [])
    n = len(weekdays) or 3
    if not weekdays:
        warnings.append("Dias de treino não informados: usada divisão de 3 dias, sem dia da semana fixo.")
    equipment = allowed_equipment(profile)
    if equipment is None:
        warnings.append("Equipamentos não informados: considerada academia com máquinas, barras, halteres e polia.")
    avoid_slots, avoid_equip, inj = _injury_filters(profile)
    if inj:
        warnings.append("Limitações consideradas (" + ", ".join(inj) + "): alguns movimentos foram evitados. "
                        "Confirme os exercícios com um profissional que conheça sua condição.")
    minutes = profile.session_minutes or 60
    exs = core_exercises(s)
    days = []
    counts: dict[str, int] = {}
    for i, key in enumerate(SPLITS[min(max(n, 1), 7)]):
        title, slots = DAY_TEMPLATES[key]
        variant = counts.get(key, 0)
        counts[key] = variant + 1
        used: set[int] = set()
        items: list[DraftExercise] = []
        for j, slot in enumerate(slots):
            if slot in avoid_slots:
                continue
            ex = pick_exercise(exs, slot, variant + j, equipment=equipment, experience=profile.experience,
                               avoid_equip=avoid_equip, used=used)
            if not ex:
                continue
            sets, lo, hi, rest = prescription(slot, profile.experience, profile.goal)
            if _estimate_minutes([(d.sets, d.rest) for d in items] + [(sets, rest)]) > minutes:
                break
            used.add(ex.id)
            items.append(DraftExercise(ex, sets, lo, hi, rest))
        wd = weekdays[i] if i < len(weekdays) else None
        prefix = f"{WEEKDAYS[wd].upper()} — " if wd is not None else f"TREINO {chr(65 + i)} — "
        days.append(DraftDay(prefix + title, wd, items))
    return days, warnings


def _next_version(s: Session, profile_id: int) -> int:
    return (s.scalar(select(func.max(WorkoutPlan.version)).where(WorkoutPlan.profile_id == profile_id)) or 0) + 1


def save_plan(s: Session, profile_id: int, name: str, days: list[DraftDay], *, origin: str,
              parent_id: int | None = None, change_note: str | None = None, rationale: str | None = None) -> WorkoutPlan:
    for old in s.scalars(select(WorkoutPlan).where(WorkoutPlan.profile_id == profile_id, WorkoutPlan.is_active)):
        old.is_active = False
    plan = WorkoutPlan(profile_id=profile_id, name=name[:120], version=_next_version(s, profile_id),
                       parent_id=parent_id, is_active=True, origin=origin, change_note=change_note,
                       rationale=rationale)
    s.add(plan)
    s.flush()
    for pos, d in enumerate(days):
        day = WorkoutDay(plan_id=plan.id, position=pos, weekday=d.weekday, title=d.title[:120])
        day.exercises = [PlannedExercise(exercise_id=e.exercise.id, position=k, sets=e.sets, reps_min=e.reps_min,
                                         reps_max=e.reps_max, rest_seconds=e.rest, notes=e.notes)
                         for k, e in enumerate(d.exercises)]
        s.add(day)
    s.flush()
    return plan


def load_plan(s: Session, plan_id: int) -> WorkoutPlan | None:
    return s.scalar(select(WorkoutPlan).where(WorkoutPlan.id == plan_id).options(
        selectinload(WorkoutPlan.days).selectinload(WorkoutDay.exercises).joinedload(PlannedExercise.exercise)))


def active_plan(s: Session, profile_id: int) -> WorkoutPlan | None:
    pid = s.scalar(select(WorkoutPlan.id).where(WorkoutPlan.profile_id == profile_id, WorkoutPlan.is_active)
                   .order_by(WorkoutPlan.id.desc()).limit(1))
    return load_plan(s, pid) if pid else None


def plan_versions(s: Session, profile_id: int) -> list[WorkoutPlan]:
    return list(s.scalars(select(WorkoutPlan).where(WorkoutPlan.profile_id == profile_id)
                          .order_by(WorkoutPlan.version.desc())))


def draft_from_plan(plan: WorkoutPlan) -> list[DraftDay]:
    return [DraftDay(d.title, d.weekday, [DraftExercise(e.exercise, e.sets, e.reps_min, e.reps_max, e.rest_seconds,
                                                        e.notes) for e in d.exercises]) for d in plan.days]


def new_version(s: Session, plan: WorkoutPlan, days: list[DraftDay], note: str) -> WorkoutPlan:
    for d in days:
        for e in d.exercises:
            validate_prescription(e.sets, e.reps_min, e.reps_max, e.rest)
    return save_plan(s, plan.profile_id, plan.name, days, origin="manual" if plan.origin == "manual" else plan.origin,
                     parent_id=plan.id, change_note=note, rationale=plan.rationale)


def validate_prescription(sets: int, reps_min: int, reps_max: int, rest: int) -> None:
    if not (1 <= sets <= 8):
        raise ValueError("Séries devem ficar entre 1 e 8.")
    if not (1 <= reps_min <= reps_max <= 50):
        raise ValueError("Repetições inválidas (mín ≤ máx, até 50).")
    if not (0 <= rest <= 600):
        raise ValueError("Descanso deve ficar entre 0 e 600 s.")


def replace_exercise(s: Session, plan: WorkoutPlan, planned_id: int, new_exercise_id: int, note: str | None = None) -> WorkoutPlan:
    ex = s.get(Exercise, new_exercise_id)
    if not ex:
        raise ValueError("Exercício substituto não existe na biblioteca.")
    days = draft_from_plan(plan)
    found = None
    for d, day in zip(days, plan.days):
        for de, pe in zip(d.exercises, day.exercises):
            if pe.id == planned_id:
                found = (de.exercise.name_pt or de.exercise.name_original)
                de.exercise = ex
    if not found:
        raise ValueError("Exercício não pertence à ficha ativa.")
    return new_version(s, plan, days, note or f"Troca: {found} → {ex.name_pt or ex.name_original}")


def adjust_volume(s: Session, plan: WorkoutPlan, delta_sets: int, note: str | None = None) -> WorkoutPlan:
    days = draft_from_plan(plan)
    for d in days:
        for e in d.exercises:
            e.sets = max(1, min(6, e.sets + delta_sets))
    return new_version(s, plan, days, note or f"Volume {'+' if delta_sets > 0 else ''}{delta_sets} série(s) por exercício")


def similar_exercises(s: Session, ex: Exercise, limit: int = 30) -> list[Exercise]:
    if ex.slot:
        rows = list(s.scalars(select(Exercise).where(Exercise.slot == ex.slot, Exercise.id != ex.id)))
        if rows:
            return rows
    stmt = select(Exercise).where(Exercise.id != ex.id)
    if ex.primary_muscle:
        stmt = stmt.where(Exercise.primary_muscle == ex.primary_muscle)
    elif ex.body_part:
        stmt = stmt.where(Exercise.body_part == ex.body_part)
    return list(s.scalars(stmt.order_by(Exercise.is_core.desc(), Exercise.name_original).limit(limit)))


# --------------------------------------------------------------------------- treino do dia

def scheduled_day(plan: WorkoutPlan, on: date) -> WorkoutDay | None:
    for d in plan.days:
        if d.weekday == on.weekday():
            return d
    return None


def next_in_rotation(s: Session, profile_id: int, plan: WorkoutPlan) -> WorkoutDay | None:
    """Para fichas sem dia fixo: o dia seguinte ao último treino realizado nesta ficha."""
    if not plan.days:
        return None
    last = s.scalar(select(WorkoutSession).where(WorkoutSession.profile_id == profile_id,
                                                 WorkoutSession.plan_id == plan.id)
                    .order_by(WorkoutSession.performed_on.desc(), WorkoutSession.id.desc()).limit(1))
    if not last or last.day_id is None:
        return plan.days[0]
    ids = [d.id for d in plan.days]
    if last.day_id not in ids:
        return plan.days[0]
    return plan.days[(ids.index(last.day_id) + 1) % len(ids)]


@dataclass
class TodayWorkout:
    day: WorkoutDay | None
    overridden: bool
    rest_day: bool


def todays_workout(s: Session, profile_id: int, plan: WorkoutPlan, on: date | None = None) -> TodayWorkout:
    on = on or date.today()
    ov = s.scalar(select(DayOverride).where(DayOverride.profile_id == profile_id, DayOverride.on_date == on))
    if ov and (ov.day_id is None or any(d.id == ov.day_id for d in plan.days)):
        day = next((d for d in plan.days if d.id == ov.day_id), None)
        return TodayWorkout(day, True, ov.day_id is None)
    if ov:  # troca feita numa versão anterior da ficha: vale o dia na mesma posição
        old = s.get(WorkoutDay, ov.day_id)
        if old and old.position < len(plan.days):
            return TodayWorkout(plan.days[old.position], True, False)
    if any(d.weekday is not None for d in plan.days):
        day = scheduled_day(plan, on)
        return TodayWorkout(day, False, day is None)
    return TodayWorkout(next_in_rotation(s, profile_id, plan), False, False)


def set_override(s: Session, profile_id: int, on: date, day_id: int | None) -> None:
    ov = s.scalar(select(DayOverride).where(DayOverride.profile_id == profile_id, DayOverride.on_date == on))
    if ov is None:
        ov = DayOverride(profile_id=profile_id, on_date=on)
        s.add(ov)
    ov.day_id = day_id


def clear_override(s: Session, profile_id: int, on: date) -> None:
    ov = s.scalar(select(DayOverride).where(DayOverride.profile_id == profile_id, DayOverride.on_date == on))
    if ov:
        s.delete(ov)


def swap_weekdays(s: Session, plan: WorkoutPlan, day_a: int, day_b: int) -> WorkoutPlan:
    """Troca permanentemente os dias da semana de dois treinos (gera nova versão)."""
    days = draft_from_plan(plan)
    ids = [d.id for d in plan.days]
    a, b = days[ids.index(day_a)], days[ids.index(day_b)]
    a.weekday, b.weekday = b.weekday, a.weekday
    for d in (a, b):
        if d.weekday is not None and " — " in d.title:
            d.title = f"{WEEKDAYS[d.weekday].upper()} — {d.title.split(' — ', 1)[1]}"
    days.sort(key=lambda d: (d.weekday is None, d.weekday if d.weekday is not None else 0))
    return new_version(s, plan, days, "Troca de dias da semana")


# --------------------------------------------------------------------------- sessões

def last_sets(s: Session, profile_id: int, exercise_id: int) -> list[SetLog]:
    sid = s.scalar(select(SetLog.session_id).join(WorkoutSession).where(
        WorkoutSession.profile_id == profile_id, SetLog.exercise_id == exercise_id, SetLog.completed)
        .order_by(WorkoutSession.performed_on.desc(), SetLog.session_id.desc()).limit(1))
    if not sid:
        return []
    return list(s.scalars(select(SetLog).where(SetLog.session_id == sid, SetLog.exercise_id == exercise_id)
                          .order_by(SetLog.set_number)))


def start_session(s: Session, profile_id: int, plan: WorkoutPlan, day: WorkoutDay, on: date | None = None) -> WorkoutSession:
    """Cria a sessão com as séries planejadas, pré-preenchidas com a última carga usada."""
    sess = WorkoutSession(profile_id=profile_id, plan_id=plan.id, day_id=day.id, performed_on=on or date.today())
    s.add(sess)
    s.flush()
    for pe in day.exercises:
        prev = last_sets(s, profile_id, pe.exercise_id)
        prev_load = max((x.load_kg or 0 for x in prev), default=None) or pe.target_load_kg
        for n in range(1, pe.sets + 1):
            s.add(SetLog(session_id=sess.id, planned_exercise_id=pe.id, exercise_id=pe.exercise_id, set_number=n,
                         load_kg=prev_load, reps=None, completed=False))
    s.flush()
    return sess


def open_session(s: Session, profile_id: int, on: date | None = None) -> WorkoutSession | None:
    return s.scalar(select(WorkoutSession).where(
        WorkoutSession.profile_id == profile_id, WorkoutSession.performed_on == (on or date.today()),
        WorkoutSession.finished_at.is_(None)).order_by(WorkoutSession.id.desc()).limit(1))


def session_sets(s: Session, session_id: int) -> list[SetLog]:
    return list(s.scalars(select(SetLog).where(SetLog.session_id == session_id)
                          .order_by(SetLog.planned_exercise_id, SetLog.set_number)))


def save_set(s: Session, set_id: int, profile_id: int, *, load_kg: float | None, reps: int | None,
             completed: bool, difficulty: str | None = None) -> None:
    sl = s.get(SetLog, set_id)
    if not sl or sl.session.profile_id != profile_id:
        raise ValueError("Série não encontrada.")
    if load_kg is not None and not (0 <= load_kg <= 600):
        raise ValueError("Carga fora da faixa (0–600 kg).")
    if reps is not None and not (0 <= reps <= 100):
        raise ValueError("Repetições fora da faixa (0–100).")
    sl.load_kg, sl.reps, sl.completed, sl.difficulty = load_kg, reps, completed, difficulty


def finish_session(s: Session, session_id: int, profile_id: int, *, fatigue: int | None, pain: bool,
                   pain_notes: str | None, recovery: str | None, notes: str | None) -> None:
    sess = s.get(WorkoutSession, session_id)
    if not sess or sess.profile_id != profile_id:
        raise ValueError("Sessão não encontrada.")
    if fatigue is not None and not (1 <= fatigue <= 10):
        raise ValueError("Esforço percebido deve ser de 1 a 10.")
    sess.fatigue, sess.pain, sess.pain_notes, sess.recovery, sess.notes = fatigue, pain, pain_notes, recovery, notes
    sess.finished_at = datetime.now()


def sessions_in_week(s: Session, profile_id: int, ref: date | None = None) -> int:
    ref = ref or date.today()
    start = ref - timedelta(days=ref.weekday())
    return s.scalar(select(func.count(WorkoutSession.id)).where(
        WorkoutSession.profile_id == profile_id, WorkoutSession.performed_on >= start,
        WorkoutSession.performed_on <= ref, WorkoutSession.finished_at.is_not(None))) or 0


def history_dataframe(s: Session, profile_id: int):
    import pandas as pd
    rows = s.execute(select(WorkoutSession.performed_on, WorkoutSession.id, WorkoutSession.fatigue,
                            WorkoutSession.pain, SetLog.exercise_id, Exercise.name_pt, Exercise.name_original,
                            SetLog.set_number, SetLog.load_kg, SetLog.reps, SetLog.completed)
                     .join(SetLog, SetLog.session_id == WorkoutSession.id)
                     .join(Exercise, Exercise.id == SetLog.exercise_id)
                     .where(WorkoutSession.profile_id == profile_id)).all()
    df = pd.DataFrame(rows, columns=["data", "sessao", "esforco", "dor", "exercise_id", "nome_pt", "nome",
                                     "serie", "carga", "reps", "concluida"])
    if not df.empty:
        df["exercicio"] = df["nome_pt"].fillna(df["nome"])
        df["volume"] = df["carga"].fillna(0) * df["reps"].fillna(0)
        df["e1rm"] = df.apply(lambda r: (r["carga"] or 0) * (1 + (r["reps"] or 0) / 30) if r["concluida"] else None,
                              axis=1)
    return df


# --------------------------------------------------------------------------- progressão

@dataclass
class Suggestion:
    action: str  # aumentar | manter | reduzir | sem_dados
    text: str
    new_load: float | None = None


def suggest_progression(pe: PlannedExercise, sets: list[SetLog], session: WorkoutSession | None) -> Suggestion:
    """Dupla progressão conservadora. Nunca aplica automaticamente; nunca sobe carga com dor."""
    done = [x for x in sets if x.completed and x.reps is not None]
    if not done:
        return Suggestion("sem_dados", "Registre uma sessão para receber sugestão.")
    load = max((x.load_kg or 0) for x in done)
    if session and session.pain:
        return Suggestion("reduzir" if load else "manter",
                          "Houve dor na última sessão: não aumente a carga. Reduza ou troque o exercício e, "
                          "se a dor persistir, procure avaliação profissional.",
                          round(load * 0.9 * 2) / 2 if load else None)
    if session and ((session.fatigue or 0) >= 9 or session.recovery == "ruim"):
        return Suggestion("manter", "Esforço muito alto ou recuperação ruim: mantenha a carga na próxima sessão.", load)
    if any(x.difficulty == "falha" for x in done) or any(x.reps < pe.reps_min for x in done):
        return Suggestion("manter", f"Algumas séries ficaram abaixo de {pe.reps_min} repetições. Mantenha a carga; "
                                    "se repetir em duas sessões, reduza cerca de 5–10%.", load)
    if len(done) >= pe.sets and all(x.reps >= pe.reps_max for x in done) and not any(
            x.difficulty == "dificil" for x in done):
        step = max(2.0 if pe.exercise.slot in LOWER else 1.0, round(load * (0.05 if pe.exercise.slot in LOWER else 0.025)))
        new = round((load + step) * 2) / 2 if load else None
        txt = (f"Todas as séries no topo da faixa ({pe.reps_max} reps). Sugestão: subir para {new:g} kg e voltar a "
               f"{pe.reps_min} reps." if new else "Todas as séries no topo da faixa. Aumente a dificuldade levemente.")
        return Suggestion("aumentar", txt, new)
    return Suggestion("manter", f"Mantenha {load:g} kg e busque +1 repetição por série até {pe.reps_max}.", load)
