from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from database.models import Food, Meal, MealItem, MealPlan, Product
from services import inventory_service as inv
from services import nutrition_service as ns
from services import pricing_service as pr
from services import profile_service as ps
from services import shopping_service as sh


def food(s, taco_id):
    return s.scalar(select(Food).where(Food.taco_id == taco_id))


def make_plan(s, profile_id, people=1):
    plan = MealPlan(profile_id=profile_id, name="t", start_date=date.today(), days=2, people=people)
    s.add(plan)
    s.flush()
    for d in range(2):
        m1 = Meal(plan_id=plan.id, day_index=d, position=0, meal_type="Almoço")
        m1.items = [MealItem(food_id=food(s, 3).id, grams=140), MealItem(food_id=food(s, 410).id, grams=105)]
        m2 = Meal(plan_id=plan.id, day_index=d, position=1, meal_type="Jantar")
        m2.items = [MealItem(food_id=food(s, 410).id, grams=105), MealItem(food_id=food(s, 488).id, grams=100)]
        s.add_all([m1, m2])
    s.flush()
    return ns.load_plan(s, plan.id)


@pytest.fixture()
def prof(s):
    return ps.create_profile(s, "C", 30, 80, 180)


def test_consolidates_repeated_ingredients(s, prof):
    plan = make_plan(s, prof.id)
    req = sh.consolidate(plan)
    frango_cru = food(s, 409)
    # 4 porções de 105 g grelhado → 420 / 0,70 = 600 g cru, uma linha só
    assert req[frango_cru.id].grams == pytest.approx(Decimal(600), abs=Decimal("0.01"))
    assert req[food(s, 4).id].grams == pytest.approx(Decimal(100), abs=Decimal("0.01"))  # 280 g cozido / 2,8


def test_people_multiplier(s, prof):
    plan = make_plan(s, prof.id, people=3)
    assert sh.consolidate(plan)[food(s, 409).id].grams == pytest.approx(Decimal(1800), abs=Decimal("0.01"))


def test_packages_and_cost(s, prof):
    prod = s.scalar(select(Product).where(Product.name == "Peito de frango (filé)"))
    pr.add_quote(s, prod.id, "21,90", 1, "kg")
    ovo = s.scalar(select(Product).where(Product.name == "Ovo branco"))
    pr.add_quote(s, ovo.id, "9,60", 1, "duzia")
    plan = make_plan(s, prof.id)
    lines = {ln.food.taco_id: ln for ln in sh.plan_lines(s, prof.id, plan)}
    frango = lines[409]
    assert frango.packages == 1 and frango.cost == Decimal("21.90")
    assert frango.consumed_cost == Decimal("13.14")  # 600 g × 21,90/kg
    ovos = lines[489]
    # 200 g cozido / 1,0 → 200 g cru / 0,88 casca = 227,3 g → 4,5 ovos → 1 dúzia
    assert ovos.packages == 1 and ovos.cost == Decimal("9.60")
    arroz = lines[4]
    assert arroz.quote is None and arroz.cost is None  # sem preço: não inventa valor


def test_stock_is_deducted_and_expired_ignored(s, prof):
    plan = make_plan(s, prof.id)
    frango = food(s, 409)
    inv.add_item(s, prof.id, frango.id, "0,4", "kg")
    inv.add_item(s, prof.id, frango.id, 1, "kg", expires_on=date.today() - timedelta(days=1))
    lines = {ln.food.id: ln for ln in sh.plan_lines(s, prof.id, plan)}
    assert lines[frango.id].stock_g == Decimal("400.0")
    assert lines[frango.id].buy_g == pytest.approx(Decimal(200), abs=Decimal("0.01"))


def test_enough_stock_is_not_bought(s, prof):
    plan = make_plan(s, prof.id)
    inv.add_item(s, prof.id, food(s, 4).id, 5, "kg")
    sl = sh.create_list(s, prof.id, plan, "x")
    assert food(s, 4).id not in {it.food_id for it in sl.items}


def test_unit_stock_requires_weight(s, prof):
    from utils.units import UnitError
    with pytest.raises(UnitError):
        inv.add_item(s, prof.id, food(s, 489).id, 6, "un")
    inv.add_item(s, prof.id, food(s, 489).id, 6, "un", grams_per_unit=50)
    assert sh.available_stock(s, prof.id)[food(s, 489).id] == Decimal(300)


def test_list_totals_and_purchase(s, prof):
    prod = s.scalar(select(Product).where(Product.name == "Peito de frango (filé)"))
    pr.add_quote(s, prod.id, "21,90", 1, "kg")
    plan = make_plan(s, prof.id)
    sl = sh.create_list(s, prof.id, plan, "x", budget=Decimal("100"))
    sl = sh.load_list(s, sl.id)
    item = next(i for i in sl.items if i.product_id == prod.id)
    sh.mark_purchased(s, item, True, paid_price="19,90", add_to_stock=True, profile_id=prof.id)
    t = sh.totals(sl)
    assert t.paid == Decimal("19.90")
    assert t.vs_estimate == Decimal("2.00")
    assert t.vs_budget == Decimal("100") - t.projected
    assert sh.available_stock(s, prof.id)[item.food_id] == Decimal("1000.000")
    sh.mark_purchased(s, item, False)
    assert sh.totals(sl).paid == Decimal("0.00")
