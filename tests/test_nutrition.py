from decimal import Decimal

import pytest
from sqlalchemy import select

from database.models import Food, Product
from services import nutrition_service as ns
from services import pricing_service as pr
from services import profile_service as ps


def food(s, taco_id):
    return s.scalar(select(Food).where(Food.taco_id == taco_id))


def test_taco_values_loaded(s):
    arroz = food(s, 3)  # Arroz, tipo 1, cozido
    assert arroz.nutrients.kcal == pytest.approx(128, abs=1)
    m = ns.food_macros(arroz, 150)
    assert m.kcal == pytest.approx(arroz.nutrients.kcal * 1.5)
    assert not m.incomplete


def test_macros_sum(s):
    a = ns.food_macros(food(s, 3), 100)
    b = ns.food_macros(food(s, 410), 100)
    t = a + b
    assert t.protein == pytest.approx(a.protein + b.protein)


def test_cooked_to_raw_purchase(s):
    arroz_cozido = food(s, 3)
    raw, grams = ns.purchase_requirement(arroz_cozido, 280)
    assert raw.taco_id == 4
    assert grams == pytest.approx(280 / 2.8)


def test_edible_factor_applied(s):
    banana = food(s, 182)
    pf, grams = ns.purchase_requirement(banana, 65)
    assert pf.id == banana.id
    assert grams == pytest.approx(100)  # 65 g comestíveis / 0,65


def test_raw_and_edible_combined(s):
    batata = food(s, 88)  # batata-doce cozida -> crua com fator 0,85
    raw, grams = ns.purchase_requirement(batata, 95)
    assert raw.taco_id == 89
    assert grams == pytest.approx(95 / 0.95 / 0.85)


def test_item_cost_uses_decimal_and_people(s):
    prod = s.scalar(select(Product).where(Product.name == "Peito de frango (filé)"))
    pr.add_quote(s, prod.id, "20,00", 1, "kg")
    prices = pr.price_per_gram_map(s)
    grelhado = food(s, 410)
    ic = ns.item_cost(grelhado, 140, prices, people=2)
    # 140 g grelhado / 0,70 = 200 g cru por pessoa → 400 g → R$ 8,00
    assert ic.purchase_grams == pytest.approx(400)
    assert ic.cost == Decimal("8.00")


def test_unit_products_need_weight(s):
    ovo = s.scalar(select(Product).where(Product.name == "Ovo branco"))
    pr.add_quote(s, ovo.id, "9,60", 1, "duzia")
    v = pr.best_quote_for_food(s, ovo.food_id)
    assert v.per_gram == Decimal("0.80") / Decimal(50)


def test_cheapest_quote_wins(s):
    prod = s.scalar(select(Product).where(Product.name == "Arroz branco tipo 1"))
    pr.add_quote(s, prod.id, "27,50", 5, "kg", establishment="A")
    pr.add_quote(s, prod.id, "6,00", 1, "kg", establishment="B")
    best = pr.best_quote_for_food(s, prod.food_id)
    assert best.quote.establishment.name == "A"
    comp = pr.compare_establishments(s)[0]
    assert comp.spread_pct == Decimal("9.1")


def test_latest_quote_per_establishment(s):
    from datetime import date, timedelta
    prod = s.scalar(select(Product).where(Product.name == "Patinho"))
    pr.add_quote(s, prod.id, "30,00", 1, "kg", establishment="A", quoted_on=date.today() - timedelta(days=10))
    pr.add_quote(s, prod.id, "35,00", 1, "kg", establishment="A")
    best = pr.best_quote_for_food(s, prod.food_id)
    assert best.quote.price == Decimal("35.00")


def test_invalid_quote_rejected(s):
    from utils.units import UnitError
    prod = s.scalar(select(Product).where(Product.name == "Patinho"))
    with pytest.raises(UnitError):
        pr.add_quote(s, prod.id, "0", 1, "kg")
    with pytest.raises(UnitError):
        pr.add_quote(s, prod.id, "10", 0, "kg")


def test_energy_estimate_marks_provisional(s):
    p = ps.create_profile(s, "X", 30, 80, 180)
    e = ps.estimate_energy(p)
    assert e.is_provisional and e.range_kcal is not None
    p.sex, p.activity_level, p.goal = "M", "moderado", "manutencao"
    e = ps.estimate_energy(p)
    assert not e.is_provisional
    assert e.bmr == round(10 * 80 + 6.25 * 180 - 5 * 30 + 5)
    assert e.target_kcal == round(e.bmr * 1.55) or abs(e.target_kcal - e.tdee) <= 1


def test_weight_loss_never_below_floor(s):
    p = ps.create_profile(s, "Y", 60, 50, 150)
    p.sex, p.activity_level, p.goal = "F", "sedentario", "emagrecimento"
    e = ps.estimate_energy(p)
    assert e.target_kcal >= max(1200, e.bmr)


def test_local_plan_hits_targets(s):
    p = ps.create_profile(s, "Z", 30, 75, 175)
    plan = ns.generate_local_plan(s, p, 7, 2300, 140)
    sm = ns.summarize(s, ns.load_plan(s, plan.id))
    assert len(sm.day_macros) == 7
    for m in sm.day_macros.values():
        assert m.kcal == pytest.approx(2300, rel=0.12)
        assert m.protein >= 140 * 0.85


def test_restrictions_exclude_foods(s):
    p = ps.create_profile(s, "V", 30, 70, 170)
    p.restrictions = "vegetariano, sem lactose"
    foods = ns.core_foods(s)
    excl = ns.excluded_food_ids(foods, p)
    names = {f.short_name for f in foods if f.id in excl}
    assert "Peito de frango grelhado" in names and "Leite integral" in names
    assert "Tofu" not in names and "Ovo cozido" not in names


def test_economize_reduces_cost_and_keeps_protein(s):
    p = ps.create_profile(s, "E", 30, 75, 175)
    for name, price in [("Peito de frango (filé)", "19,90"), ("Patinho", "45,00"), ("Acém moído", "29,90"),
                        ("Coxa de frango", "12,90"), ("Arroz branco tipo 1", "5,50"), ("Feijão carioca", "8,90")]:
        prod = s.scalar(select(Product).where(Product.name == name))
        pr.add_quote(s, prod.id, price, 1, "kg")
    plan = ns.load_plan(s, ns.generate_local_plan(s, p, 7, 2300, 140).id)
    before = ns.summarize(s, plan)
    new, subs = ns.economize_plan(s, plan, None, p)
    after = ns.summarize(s, ns.load_plan(s, new.id))
    assert after.total_cost <= before.total_cost
    assert after.avg_macros.protein >= before.avg_macros.protein * 0.9
    assert new.parent_id == plan.id
