from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from services import goal_service as gls
from services import nutrition_service as ns
from services import profile_service as ps


@pytest.fixture()
def prof(s):
    p = ps.create_profile(s, "M", 30, 90, 178)
    p.sex, p.activity_level, p.goal, p.target_weight_kg = "M", "moderado", "emagrecimento", 80
    s.flush()
    return p


def test_loss_scenarios_are_ordered_and_safe(prof):
    scs = gls.compute(prof, 90)
    assert [x.key for x in scs] == gls.KEYS
    assert scs[0].weeks > scs[1].weeks > scs[2].weeks
    assert scs[0].kcal > scs[1].kcal > scs[2].kcal >= gls.kcal_floor(prof, 90)
    assert scs[2].protein_g >= scs[0].protein_g
    # 0,5% de 90 kg por semana ≈ 0,45 kg; 10 kg em ~23 semanas com o ritmo proporcional
    assert scs[0].weekly_kg == pytest.approx(-0.45, abs=0.01)
    assert 20 <= scs[0].weeks <= 25
    assert scs[0].date == date.today() + timedelta(weeks=scs[0].weeks)
    for sc in scs:
        assert abs(sc.protein_g * 4 + sc.fat_g * 9 + sc.carbs_g * 4 - sc.kcal) < 20


def test_floor_limits_aggressive_loss(prof):
    prof.activity_level, prof.age, prof.height_cm = "sedentario", 60, 160
    sc = gls.build(prof, 90, "intenso")
    assert sc.kcal == round(gls.kcal_floor(prof, 90))
    assert any("piso" in n for n in sc.notes)


def test_gain_scenarios(prof):
    prof.target_weight_kg, prof.goal = 95, "hipertrofia"
    scs = gls.compute(prof, 90)
    tdee = ps.estimate_energy(prof, 90).tdee
    assert [x.kcal - tdee for x in scs] == pytest.approx([200, 350, 500], abs=1)
    assert all(x.weekly_kg > 0 for x in scs)


def test_requires_target(prof):
    prof.target_weight_kg = None
    with pytest.raises(ValueError):
        gls.compute(prof, 90)
    prof.target_weight_kg = 90.2
    with pytest.raises(ValueError):
        gls.compute(prof, 90)


def test_ai_review_is_bounded_and_saved(s, prof):
    base = gls.compute(prof, 90)
    review = SimpleNamespace(scenarios=[
        SimpleNamespace(key="conservador", kcal_adjust=-400, meals_per_day=9, tips="Café reforçado."),
        SimpleNamespace(key="rapido", kcal_adjust=50, meals_per_day=5, tips=""),
    ])
    out, rejected = gls.apply_review(prof, 90, base, review)
    assert out[0].kcal == base[0].kcal - 150 and out[0].meals_per_day == 6 and out[0].tips == "Café reforçado."
    assert out[0].weeks < base[0].weeks  # mais déficit, prazo recalculado
    assert out[1].kcal == base[1].kcal + 50 and out[1].meals_per_day == 5
    assert out[2] == base[2]
    assert rejected and "limitado" in rejected[0]
    gp = gls.save(s, prof, 90, out, chosen="rapido", analysis="ok", origin="gemini")
    assert gls.active(s, prof.id).id == gp.id
    t = gls.daily_targets(s, prof)
    assert (t.kcal, t.meals_per_day, t.source) == (out[1].kcal, 5, "Mais rápido")
    assert "5 refeições" in gls.context_line(gp)
    gp2 = gls.save(s, prof, 90, base)
    s.refresh(gp)
    assert not gp.is_active and gls.active(s, prof.id).id == gp2.id


def test_expected_weight_and_staleness(s, prof):
    gp = gls.save(s, prof, 90, gls.compute(prof, 90))
    sc = gls.chosen_scenario(gp)
    assert gls.expected_weight(gp, sc, gp.created_at.date()) == pytest.approx(90)
    assert gls.expected_weight(gp, sc, sc.date + timedelta(days=30)) == pytest.approx(80)
    assert gls.is_stale(gp, prof, 90) is None
    assert gls.is_stale(gp, prof, 86.5)
    prof.target_weight_kg = 78
    assert "meta" in gls.is_stale(gp, prof, 90)


def test_daily_targets_without_goal(s, prof):
    e = ps.estimate_energy(prof)
    t = gls.daily_targets(s, prof)
    assert (t.kcal, t.meals_per_day, t.source) == (round(e.target_kcal), 4, "estimativa")


@pytest.mark.parametrize("meals", [3, 4, 5, 6])
def test_local_plan_meal_count(s, prof, meals):
    plan = ns.generate_local_plan(s, prof, 1, 2200, 150, meals=meals)
    plan = ns.load_plan(s, plan.id)
    assert [m.meal_type for m in plan.meals] == ns.MEAL_SETS[meals]
    sm = ns.summarize(s, plan)
    assert abs(sm.avg_macros.kcal - 2200) / 2200 < 0.2
