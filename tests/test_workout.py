from datetime import date, timedelta

import pytest

from database.models import Exercise
from services import profile_service as ps
from services import workout_service as ws


@pytest.fixture()
def lib(s):
    rows = [("supino", "chest_press", "barbell"), ("supino m", "chest_press", "leverage machine"),
            ("remada", "row", "cable"), ("agacha", "squat", "barbell"), ("leg", "leg_press", "sled machine"),
            ("terra", "hinge", "barbell"), ("afundo", "lunge", "dumbbell"), ("desenv", "shoulder_press", "dumbbell"),
            ("flexora", "knee_flex", "leverage machine"), ("abd", "core", "bodyweight"),
            ("puxada", "vertical_pull", "cable"), ("lateral", "lateral_raise", "dumbbell")]
    for i, (n, slot, eq) in enumerate(rows):
        s.add(Exercise(source="manual", source_id=str(i), name_original=n, name_pt=n, slot=slot, equipment=eq,
                       is_core=True, difficulty="iniciante"))
    s.flush()


def plan_for(s, **kw):
    p = ps.create_profile(s, "W", 30, 80, 180)
    for k, v in kw.items():
        setattr(p, k, v)
    days, warns = ws.local_plan_draft(s, p)
    return p, ws.load_plan(s, ws.save_plan(s, p.id, "f", days, origin="local").id), warns


def test_split_follows_weekdays(s, lib):
    p, plan, _ = plan_for(s, training_weekdays=[0, 2, 4])
    assert [d.weekday for d in plan.days] == [0, 2, 4]
    assert plan.days[0].title.startswith("SEGUNDA")


def test_injury_avoids_patterns_and_warns(s, lib):
    _, plan, warns = plan_for(s, training_weekdays=[0, 2], injuries="dor no joelho")
    slots = {e.exercise.slot for d in plan.days for e in d.exercises}
    assert "lunge" not in slots
    assert any("joelho" in w for w in warns)


def test_equipment_filter(s, lib):
    _, plan, _ = plan_for(s, training_weekdays=[0], equipment=["máquinas"])
    assert {e.exercise.equipment for d in plan.days for e in d.exercises} <= {"leverage machine", "sled machine"}


def test_override_and_versions(s, lib):
    p, plan, _ = plan_for(s, training_weekdays=[0, 2, 4])
    thursday = date(2026, 10, 22)
    assert ws.todays_workout(s, p.id, plan, thursday).rest_day
    ws.set_override(s, p.id, thursday, plan.days[1].id)
    assert ws.todays_workout(s, p.id, plan, thursday).day.id == plan.days[1].id
    v2 = ws.load_plan(s, ws.adjust_volume(s, plan, +1).id)
    assert v2.version == 2 and v2.parent_id == plan.id
    # a troca feita na versão anterior continua valendo pela posição do dia
    assert ws.todays_workout(s, p.id, v2, thursday).day.position == 1


def _session(s, p, plan, load, reps, *, pain=False, fatigue=7):
    sess = ws.start_session(s, p.id, plan, plan.days[0], date.today() - timedelta(days=1))
    for x in ws.session_sets(s, sess.id):
        ws.save_set(s, x.id, p.id, load_kg=load, reps=reps, completed=True)
    ws.finish_session(s, sess.id, p.id, fatigue=fatigue, pain=pain, pain_notes=None, recovery="boa", notes=None)
    return sess


def test_progression_increase_only_when_top_of_range(s, lib):
    p, plan, _ = plan_for(s, training_weekdays=[0])
    pe = plan.days[0].exercises[0]
    sess = _session(s, p, plan, 50, pe.reps_max)
    sug = ws.suggest_progression(pe, ws.last_sets(s, p.id, pe.exercise_id), sess)
    assert sug.action == "aumentar" and 50 < sug.new_load <= 50 * 1.06


def test_no_increase_with_pain_or_high_fatigue(s, lib):
    p, plan, _ = plan_for(s, training_weekdays=[0])
    pe = plan.days[0].exercises[0]
    sess = _session(s, p, plan, 50, pe.reps_max, pain=True)
    sug = ws.suggest_progression(pe, ws.last_sets(s, p.id, pe.exercise_id), sess)
    assert sug.action in ("reduzir", "manter") and (sug.new_load or 0) <= 50
    sess2 = _session(s, p, plan, 50, pe.reps_max, fatigue=9)
    assert ws.suggest_progression(pe, ws.last_sets(s, p.id, pe.exercise_id), sess2).action == "manter"


def test_set_validation(s, lib):
    p, plan, _ = plan_for(s, training_weekdays=[0])
    sess = ws.start_session(s, p.id, plan, plan.days[0])
    x = ws.session_sets(s, sess.id)[0]
    with pytest.raises(ValueError):
        ws.save_set(s, x.id, p.id, load_kg=-5, reps=10, completed=True)
    with pytest.raises(ValueError):
        ws.save_set(s, x.id, p.id + 999, load_kg=5, reps=10, completed=True)
