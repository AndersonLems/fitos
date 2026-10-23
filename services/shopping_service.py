"""Lista de compras: consolidação do cardápio, desconto do estoque, embalagens e custos."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from database.models import Food, InventoryItem, MealPlan, PriceQuote, Product, Purchase, ShoppingItem, ShoppingList
from services.nutrition_service import purchase_requirement
from services.pricing_service import QuoteView, grams_per_base, price_per_gram_map
from utils.units import D, UnitError, convert_between, fmt_qty, money, packages_needed, to_base


@dataclass
class Requirement:
    food: Food
    grams: Decimal  # peso comprado necessário (já com rendimento, perdas e nº de pessoas)


def consolidate(plan: MealPlan, day_indexes: set[int] | None = None) -> dict[int, Requirement]:
    """Soma a necessidade de compra de cada alimento no período (ingredientes repetidos viram uma linha)."""
    out: dict[int, Requirement] = {}
    for meal in plan.meals:
        if day_indexes is not None and meal.day_index not in day_indexes:
            continue
        for it in meal.items:
            pf, g = purchase_requirement(it.food, it.grams)
            g_total = D(round(g, 3)) * plan.people
            if pf.id in out:
                out[pf.id].grams += g_total
            else:
                out[pf.id] = Requirement(pf, g_total)
    return out


def inventory_grams(item: InventoryItem, density_g_ml: float | None = None) -> Decimal | None:
    """Quantidade do estoque em gramas (None se a unidade não for conversível)."""
    q, base = to_base(item.quantity, item.unit)
    try:
        return convert_between(q, base, "g", grams_per_unit=item.grams_per_unit, density_g_ml=density_g_ml)
    except UnitError:
        return None


def _densities(s: Session) -> dict[int, float]:
    out: dict[int, float] = {}
    for p in s.scalars(select(Product).where(Product.density_g_ml.is_not(None), Product.food_id.is_not(None))):
        out.setdefault(p.food_id, p.density_g_ml)
    return out


def available_stock(s: Session, profile_id: int, on: date | None = None) -> dict[int, Decimal]:
    """Estoque utilizável por alimento (em gramas), ignorando itens vencidos."""
    on = on or date.today()
    dens = _densities(s)
    out: dict[int, Decimal] = {}
    for it in s.scalars(select(InventoryItem).where(InventoryItem.profile_id == profile_id)):
        if it.expires_on and it.expires_on < on:
            continue
        g = inventory_grams(it, dens.get(it.food_id))
        if g is None or g <= 0:
            continue
        out[it.food_id] = out.get(it.food_id, Decimal(0)) + g
    return out


@dataclass
class ListLine:
    food: Food
    need_g: Decimal
    stock_g: Decimal
    buy_g: Decimal
    quote: QuoteView | None
    packages: int | None
    package_label: str | None
    cost: Decimal | None  # custo das embalagens inteiras
    consumed_cost: Decimal | None  # custo proporcional ao que será consumido


def plan_lines(s: Session, profile_id: int, plan: MealPlan, *, day_indexes: set[int] | None = None,
               use_stock: bool = True, prices: dict[int, QuoteView] | None = None) -> list[ListLine]:
    prices = prices if prices is not None else price_per_gram_map(s)
    stock = available_stock(s, profile_id) if use_stock else {}
    lines = []
    for fid, req in consolidate(plan, day_indexes).items():
        st = min(stock.get(fid, Decimal(0)), req.grams)
        buy = max(Decimal(0), req.grams - st)
        q = prices.get(fid)
        pk = label = cost = consumed = None
        if q is not None:
            gpb = grams_per_base(q.product, q.base_unit)
            pkg_base, _ = to_base(q.quote.package_qty, q.quote.unit)
            need_base = buy / gpb if gpb else None
            if need_base is not None:
                pk = packages_needed(need_base, pkg_base)
                label = f"{fmt_qty(pkg_base, q.base_unit)} · {q.product.name}"
                cost = money(q.quote.price * pk)
                consumed = money(q.per_gram * req.grams)
        lines.append(ListLine(req.food, req.grams, st, buy, q, pk, label, cost, consumed))
    lines.sort(key=lambda line: (line.food.group or "", line.food.short_name or line.food.name))
    return lines


def create_list(s: Session, profile_id: int, plan: MealPlan, name: str, *, day_indexes: set[int] | None = None,
                budget: Decimal | None = None, use_stock: bool = True) -> ShoppingList:
    sl = ShoppingList(profile_id=profile_id, meal_plan_id=plan.id, name=name[:120], budget=budget)
    s.add(sl)
    s.flush()
    for ln in plan_lines(s, profile_id, plan, day_indexes=day_indexes, use_stock=use_stock):
        if ln.buy_g <= 0:
            continue  # estoque cobre a necessidade
        s.add(ShoppingItem(
            list_id=sl.id, food_id=ln.food.id, label=ln.food.short_name or ln.food.name,
            product_id=ln.quote.product.id if ln.quote else None, quote_id=ln.quote.quote.id if ln.quote else None,
            needed_base=ln.need_g.quantize(Decimal("0.001")), stock_base=ln.stock_g.quantize(Decimal("0.001")),
            to_buy_base=ln.buy_g.quantize(Decimal("0.001")), base_unit="g", packages=ln.packages,
            package_label=ln.package_label, estimated_cost=ln.cost,
            establishment_id=ln.quote.quote.establishment_id if ln.quote else None))
    s.flush()
    return sl


def load_list(s: Session, list_id: int) -> ShoppingList | None:
    return s.scalar(select(ShoppingList).where(ShoppingList.id == list_id).options(
        joinedload(ShoppingList.items).joinedload(ShoppingItem.food),
        joinedload(ShoppingList.items).joinedload(ShoppingItem.product)))


@dataclass
class ListTotals:
    estimated: Decimal
    paid: Decimal
    estimated_of_purchased: Decimal
    pending_estimated: Decimal
    budget: Decimal | None

    @property
    def projected(self) -> Decimal:
        return self.paid + self.pending_estimated

    @property
    def vs_budget(self) -> Decimal | None:
        return None if self.budget is None else self.budget - self.projected

    @property
    def vs_estimate(self) -> Decimal:
        return self.estimated_of_purchased - self.paid


def totals(sl: ShoppingList) -> ListTotals:
    est = paid = est_bought = pending = Decimal(0)
    for it in sl.items:
        e = it.estimated_cost or Decimal(0)
        est += e
        if it.purchased:
            paid += it.paid_price if it.paid_price is not None else e
            est_bought += e
        else:
            pending += e
    return ListTotals(money(est), money(paid), money(est_bought), money(pending), sl.budget)


def mark_purchased(s: Session, item: ShoppingItem, purchased: bool, *, paid_price=None, qty=None,
                   add_to_stock: bool = False, profile_id: int | None = None) -> None:
    item.purchased = purchased
    if not purchased:
        item.paid_price = None
        item.purchased_qty = None
        for p in s.scalars(select(Purchase).where(Purchase.shopping_item_id == item.id)):
            s.delete(p)
        return
    item.paid_price = money(paid_price) if paid_price not in (None, "") else item.estimated_cost
    item.purchased_qty = D(qty) if qty not in (None, "") else (D(item.packages) if item.packages else None)
    pid = profile_id or item.shopping_list.profile_id
    if item.paid_price is not None:
        s.add(Purchase(profile_id=pid, shopping_item_id=item.id, product_id=item.product_id,
                       establishment_id=item.establishment_id, purchased_on=date.today(),
                       description=item.label, amount=item.paid_price))
    if add_to_stock and item.food_id:
        grams = item.to_buy_base
        q = s.get(PriceQuote, item.quote_id) if item.quote_id else None
        if q is not None and item.purchased_qty:
            pkg_base, base = to_base(q.package_qty, q.unit)
            gpb = grams_per_base(q.product, base)
            if gpb:
                grams = pkg_base * gpb * item.purchased_qty
        s.add(InventoryItem(profile_id=pid, food_id=item.food_id, quantity=grams.quantize(Decimal("0.001")),
                            unit="g", notes=f"Comprado pela lista #{item.list_id}"))


def monthly_spending(s: Session, profile_id: int) -> list[tuple[str, Decimal]]:
    rows: dict[str, Decimal] = {}
    for p in s.scalars(select(Purchase).where(Purchase.profile_id == profile_id)):
        k = p.purchased_on.strftime("%Y-%m")
        rows[k] = rows.get(k, Decimal(0)) + p.amount
    return sorted(rows.items())
