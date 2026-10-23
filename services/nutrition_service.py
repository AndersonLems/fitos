"""Cálculos nutricionais, conversão cru/cozido e geração/ajuste de cardápios.

Regra central: quem propõe refeições pode ser o Gemini ou o gerador local, mas as quantidades
de nutrientes, somas e custos são sempre calculadas aqui, a partir da TACO e dos preços cadastrados.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from database.models import Food, Meal, MealItem, MealPlan, Profile
from services.pricing_service import QuoteView, price_per_gram_map
from utils.units import D, money

MEAL_TYPES = ["Café da manhã", "Almoço", "Lanche", "Jantar"]
PLAN_LENGTHS = {1: "1 dia", 7: "7 dias", 15: "15 dias", 30: "30 dias", 31: "31 dias"}


@dataclass
class Macros:
    kcal: float = 0.0
    protein: float = 0.0
    carbs: float = 0.0
    fat: float = 0.0
    incomplete: bool = False  # algum alimento sem valor na TACO

    def __add__(self, o: "Macros") -> "Macros":
        return Macros(self.kcal + o.kcal, self.protein + o.protein, self.carbs + o.carbs, self.fat + o.fat,
                      self.incomplete or o.incomplete)

    def scaled(self, k: float) -> "Macros":
        return Macros(self.kcal * k, self.protein * k, self.carbs * k, self.fat * k, self.incomplete)


def food_macros(food: Food, grams: float) -> Macros:
    n = food.nutrients
    vals = [n.kcal, n.protein_g, n.carbs_g, n.fat_g] if n else [None] * 4
    k = grams / 100.0
    return Macros(*(0.0 if v is None else v * k for v in vals), incomplete=any(v is None for v in vals))


# --------------------------------------------------------------------------- cru x cozido x comprado

def purchase_requirement(food: Food, grams: float) -> tuple[Food, float]:
    """Converte a porção consumida no alimento e peso a comprar.

    porção cozida --(÷ índice de cocção)--> peso cru comestível --(÷ fator comestível)--> peso comprado
    """
    if food.raw_food_id and food.yield_factor:
        raw = food.raw_food
        raw_g = grams / food.yield_factor
        return raw, raw_g / (raw.edible_factor or 1.0)
    return food, grams / (food.edible_factor or 1.0)


@dataclass
class ItemCost:
    purchase_food: Food
    purchase_grams: float
    cost: Decimal | None
    quote: QuoteView | None


def item_cost(food: Food, grams: float, prices: dict[int, QuoteView], people: int = 1) -> ItemCost:
    pf, pg = purchase_requirement(food, grams)
    pg *= people
    q = prices.get(pf.id)
    cost = money(q.per_gram * D(round(pg, 3))) if q else None
    return ItemCost(pf, pg, cost, q)


# --------------------------------------------------------------------------- resumo do plano

@dataclass
class MealSummary:
    meal: Meal
    macros: Macros
    cost: Decimal | None
    unpriced: list[str] = field(default_factory=list)


@dataclass
class PlanSummary:
    plan: MealPlan
    days: dict[int, list[MealSummary]]
    day_macros: dict[int, Macros]
    day_cost: dict[int, Decimal | None]
    unpriced: set[str]

    @property
    def avg_macros(self) -> Macros:
        n = max(1, len(self.day_macros))
        tot = Macros()
        for m in self.day_macros.values():
            tot = tot + m
        return tot.scaled(1 / n)

    @property
    def total_cost(self) -> Decimal | None:
        vals = [c for c in self.day_cost.values() if c is not None]
        return sum(vals, Decimal(0)) if vals else None

    def avg_daily_cost(self) -> Decimal | None:
        t = self.total_cost
        return money(t / len(self.day_cost)) if t is not None and self.day_cost else None


def load_plan(s: Session, plan_id: int) -> MealPlan | None:
    return s.scalar(select(MealPlan).where(MealPlan.id == plan_id).options(
        selectinload(MealPlan.meals).selectinload(Meal.items).joinedload(MealItem.food).joinedload(Food.nutrients),
        selectinload(MealPlan.meals).selectinload(Meal.items).joinedload(MealItem.food).joinedload(Food.raw_food)))


def active_plan(s: Session, profile_id: int) -> MealPlan | None:
    pid = s.scalar(select(MealPlan.id).where(MealPlan.profile_id == profile_id, MealPlan.is_active)
                   .order_by(MealPlan.id.desc()).limit(1))
    return load_plan(s, pid) if pid else None


def summarize(s: Session, plan: MealPlan, prices: dict[int, QuoteView] | None = None) -> PlanSummary:
    """Totais por refeição e por dia. Custos por pessoa × pessoas do plano."""
    prices = prices if prices is not None else price_per_gram_map(s)
    days: dict[int, list[MealSummary]] = {}
    unpriced: set[str] = set()
    for meal in plan.meals:
        mac, cost, miss = Macros(), Decimal(0), []
        for it in meal.items:
            mac = mac + food_macros(it.food, it.grams)
            ic = item_cost(it.food, it.grams, prices, plan.people)
            if ic.cost is None:
                miss.append(ic.purchase_food.short_name or ic.purchase_food.name)
            else:
                cost += ic.cost
        unpriced.update(miss)
        days.setdefault(meal.day_index, []).append(MealSummary(meal, mac, cost if meal.items else None, miss))
    day_macros = {d: sum((m.macros for m in ms), Macros()) for d, ms in days.items()}
    day_cost = {d: sum((m.cost or Decimal(0) for m in ms), Decimal(0)) for d, ms in days.items()}
    return PlanSummary(plan, dict(sorted(days.items())), day_macros, day_cost, unpriced)


# --------------------------------------------------------------------------- restrições

DIET_KEYWORDS = {
    "vegano": {"groups": {"proteina", "ovo", "laticinio"}, "names": {"mel", "manteiga"}},
    "vegetariano": {"groups": {"proteina"}, "keep": {"tofu"}},
    "lactose": {"groups": {"laticinio"}, "names": {"manteiga"}},
    "leite": {"groups": {"laticinio"}, "names": {"manteiga"}},
    "glúten": {"names": {"pão", "macarrão", "aveia"}},
    "gluten": {"names": {"pão", "macarrão", "aveia"}},
    "ovo": {"groups": {"ovo"}},
    "peixe": {"names": {"merluza", "sardinha", "atum"}},
    "frutos do mar": {"names": {"merluza", "sardinha", "atum"}},
    "amendoim": {"names": {"amendoim"}},
    "porco": {"names": {"lombo"}},
    "suíno": {"names": {"lombo"}},
    "carne vermelha": {"names": {"patinho", "acém", "músculo", "fígado", "lombo"}},
}


def excluded_food_ids(foods: list[Food], profile: Profile) -> set[int]:
    """Filtro determinístico por restrições, alergias e preferências do perfil (texto livre)."""
    text = " ".join(filter(None, [profile.restrictions, profile.allergies, profile.preferences])).lower()
    if not text:
        return set()
    out = set()
    for kw, rule in DIET_KEYWORDS.items():
        if kw not in text:
            continue
        for f in foods:
            nm = (f.short_name or f.name).lower()
            if any(k in nm for k in rule.get("keep", ())):
                continue
            if f.group in rule.get("groups", ()) or any(n in nm for n in rule.get("names", ())):
                out.add(f.id)
    # menções diretas ("não como beterraba", "alergia a morango")
    for f in foods:
        first = (f.short_name or f.name).split()[0].lower()
        if len(first) > 3 and first in text and f"gosto de {first}" not in text:
            out.add(f.id)
    return out


def core_foods(s: Session) -> list[Food]:
    return list(s.scalars(select(Food).where(Food.is_core).options(
        joinedload(Food.nutrients), joinedload(Food.raw_food)).order_by(Food.short_name)).unique())


# --------------------------------------------------------------------------- gerador local

# slots de cada refeição: (grupo, gramas iniciais, papel no ajuste)
TEMPLATES = {
    "Café da manhã": [("carbo_cafe", 50, "carb"), ("proteina_cafe", 100, "protein"), ("fruta", 100, "fixed")],
    "Almoço": [("cereal", 120, "carb"), ("leguminosa", 100, "fixed"), ("proteina", 120, "protein"),
               ("vegetal", 80, "fixed"), ("vegetal_cru", 60, "fixed"), ("gordura", 8, "fixed")],
    "Lanche": [("fruta", 120, "fixed"), ("laticinio", 170, "protein"), ("carbo_lanche", 30, "carb")],
    "Jantar": [("tuberculo", 150, "carb"), ("proteina", 120, "protein"), ("vegetal", 100, "fixed"),
               ("gordura", 5, "fixed")],
    "Lanche da manhã": [("fruta", 100, "fixed"), ("laticinio", 170, "protein")],
    "Ceia": [("laticinio", 170, "protein"), ("carbo_lanche", 20, "carb")],
}
# refeições do dia conforme a quantidade escolhida (o plano de meta sugere 3–6)
MEAL_SETS = {
    3: ["Café da manhã", "Almoço", "Jantar"],
    4: ["Café da manhã", "Almoço", "Lanche", "Jantar"],
    5: ["Café da manhã", "Lanche da manhã", "Almoço", "Lanche", "Jantar"],
    6: ["Café da manhã", "Lanche da manhã", "Almoço", "Lanche", "Jantar", "Ceia"],
}
SLOT_RULES = {
    "carbo_cafe": lambda f: f.group == "pao" or f.taco_id in (7, 533),
    "proteina_cafe": lambda f: f.state != "cru" and (f.group == "ovo" or f.taco_id in (461, 469, 448)),
    "fruta": lambda f: f.group == "fruta" and f.taco_id != 163,
    "cereal": lambda f: f.group == "cereal" and f.state == "cozido",
    "leguminosa": lambda f: f.group == "leguminosa" and f.state == "cozido",
    "proteina": lambda f: f.group == "proteina" and f.state in ("cozido", "pronto"),
    "vegetal": lambda f: f.group == "vegetal" and f.state == "cozido",
    "vegetal_cru": lambda f: f.group == "vegetal" and f.state == "pronto",
    "gordura": lambda f: f.taco_id == 260 or f.taco_id == 272,
    "laticinio": lambda f: f.group == "laticinio" and f.taco_id in (448, 449, 458, 457),
    "carbo_lanche": lambda f: f.taco_id in (7, 53, 52),
    "tuberculo": lambda f: f.state == "cozido" and f.group in ("tuberculo", "cereal"),
}
UNIT_PORTIONS = {488: 50, 53: 50}  # ovo, pão francês: múltiplos da unidade (g)
MAX_PORTION = {319: 125, 277: 120, 356: 120, 488: 150, 558: 30}  # conservas, fígado, ovos, amendoim
SLOT_BOUNDS = {"protein": (60, 220), "carb": (25, 300)}


def _portion_round(food: Food, g: float) -> float:
    g = min(g, MAX_PORTION.get(food.taco_id, g))
    unit = UNIT_PORTIONS.get(food.taco_id)
    if unit:
        return max(unit, round(g / unit) * unit)
    step = 5 if g >= 20 else 1
    return max(step, round(g / step) * step)


def _ranked_options(foods: list[Food], slot: str, economic: bool, prices: dict[int, QuoteView]) -> list[Food]:
    opts = [f for f in foods if SLOT_RULES[slot](f)]
    if economic:
        def unit_cost(f: Food) -> float:
            ic = item_cost(f, 100, prices)
            if ic.cost is None:
                return float("inf")
            m = food_macros(f, 100)
            ref = m.protein if slot.startswith("proteina") or slot in ("laticinio", "leguminosa") else m.kcal
            return float(ic.cost) / max(ref, 0.1)
        costs = {f.id: unit_cost(f) for f in opts}
        opts.sort(key=lambda f: costs[f.id])
        priced = [f for f in opts if costs[f.id] != float("inf")]
        if priced:  # só os mais baratos com preço conhecido, mantendo alguma variedade
            return priced[: max(2, (len(priced) + 1) // 2)]
    return opts


@dataclass
class DraftItem:
    food: Food
    grams: float
    role: str = "fixed"


@dataclass
class DraftMeal:
    meal_type: str
    title: str
    items: list[DraftItem]
    preparation: str = ""


def _max_grams(item: "DraftItem") -> float:
    hi = SLOT_BOUNDS.get(item.role, (0, 10_000))[1]
    return min(hi, MAX_PORTION.get(item.food.taco_id, hi))


def _scale_role(day: list["DraftMeal"], role: str, attr: str, target: float) -> None:
    """Escala os itens de um papel para aproximar o total do nutriente, respeitando os limites por item."""
    items = [i for m in day for i in m.items if i.role == role]
    lo = SLOT_BOUNDS[role][0]
    for _ in range(4):
        total = sum(getattr(food_macros(i.food, i.grams), attr) for m in day for i in m.items)
        free = [i for i in items if (i.grams < _max_grams(i) - 0.5 if total < target else i.grams > lo + 0.5)]
        free_amt = sum(getattr(food_macros(i.food, i.grams), attr) for i in free)
        if not free or free_amt <= 0 or abs(total - target) < target * 0.01:
            return
        k = max(0.4, min(2.5, (free_amt + target - total) / free_amt))
        for i in free:
            i.grams = min(_max_grams(i), max(lo, i.grams * k))


def fit_portions(day: list[DraftMeal], target_kcal: float, target_protein: float) -> None:
    """Ajusta as porções de proteína e de carboidrato para aproximar as metas do dia."""
    for _ in range(3):
        _scale_role(day, "protein", "protein", target_protein)
        _scale_role(day, "carb", "kcal", target_kcal)
    for m in day:
        for i in m.items:
            i.grams = _portion_round(i.food, i.grams)


PREP = {
    "Café da manhã": "Montar o prato; ovos cozidos por ~10 min ou mexidos sem óleo extra.",
    "Almoço": "Cozinhar arroz e feijão (podem ser feitos para a semana). Grelhar a proteína com sal e "
              "temperos naturais; legumes no vapor; finalizar a salada com o azeite.",
    "Lanche": "Misturar o iogurte/leite com a fruta picada e a aveia ou servir separado.",
    "Jantar": "Cozinhar o tubérculo em água ou no vapor; proteína grelhada ou assada; legumes no vapor.",
    "Lanche da manhã": "Fruta com o iogurte ou o leite.",
    "Ceia": "Iogurte ou leite com a aveia, cerca de 1 h antes de dormir.",
}


def local_menu(foods: list[Food], day_index: int, target_kcal: float, target_protein: float, *,
               economic: bool = False, prices: dict[int, QuoteView] | None = None,
               meals: int = 4) -> list[DraftMeal]:
    prices = prices or {}
    day: list[DraftMeal] = []
    for mi, meal_type in enumerate(MEAL_SETS[meals]):
        slots = TEMPLATES[meal_type]
        items = []
        used: set[int] = set()
        for si, (slot, grams, role) in enumerate(slots):
            opts = [f for f in _ranked_options(foods, slot, economic, prices) if f.id not in used]
            if not opts:
                continue
            f = opts[(day_index + mi * 3 + si) % len(opts)]
            used.add(f.id)
            items.append(DraftItem(f, grams, role))
        title = " + ".join((i.food.short_name or i.food.name).split(" (")[0] for i in items[:3])
        day.append(DraftMeal(meal_type, title, items, PREP[meal_type]))
    fit_portions(day, target_kcal, target_protein)
    return day


def save_plan(s: Session, profile_id: int, name: str, days_menus: list[list[DraftMeal]], total_days: int, *,
              people: int, start: date, origin: str, target_kcal: float | None, target_protein: float | None,
              budget: Decimal | None = None, parent_id: int | None = None, notes: str | None = None) -> MealPlan:
    """Grava o plano repetindo os cardápios distintos em ciclo até completar o período."""
    for old in s.scalars(select(MealPlan).where(MealPlan.profile_id == profile_id, MealPlan.is_active)):
        old.is_active = False
    plan = MealPlan(profile_id=profile_id, name=name[:120], start_date=start, days=total_days, people=max(1, people),
                    origin=origin, target_kcal=target_kcal, target_protein_g=target_protein, budget=budget,
                    parent_id=parent_id, notes=notes, is_active=True)
    s.add(plan)
    s.flush()
    for d in range(total_days):
        menu = days_menus[d % len(days_menus)]
        for pos, dm in enumerate(menu):
            meal = Meal(plan_id=plan.id, day_index=d, position=pos, meal_type=dm.meal_type, title=dm.title,
                        preparation=dm.preparation)
            meal.items = [MealItem(food_id=i.food.id, grams=float(i.grams)) for i in dm.items if i.grams > 0]
            s.add(meal)
    s.flush()
    return plan


def generate_local_plan(s: Session, profile: Profile, days: int, target_kcal: float, target_protein: float, *,
                        people: int = 1, economic: bool = False, start: date | None = None,
                        budget: Decimal | None = None, meals: int = 4) -> MealPlan:
    foods = core_foods(s)
    excl = excluded_food_ids(foods, profile)
    foods = [f for f in foods if f.id not in excl]
    prices = price_per_gram_map(s)
    distinct = min(days, 7)
    menus = [local_menu(foods, d, target_kcal, target_protein, economic=economic, prices=prices, meals=meals)
             for d in range(distinct)]
    label = "econômico" if economic else "padrão"
    return save_plan(s, profile.id, f"Cardápio {PLAN_LENGTHS.get(days, f'{days} dias')} ({label})", menus, days,
                     people=people, start=start or date.today(), origin="local", target_kcal=target_kcal,
                     target_protein=target_protein, budget=budget,
                     notes=f"{distinct} cardápios distintos repetidos em ciclo." if days > distinct else None)


# --------------------------------------------------------------------------- versão econômica

KEY_NUTRIENT = {"proteina": "protein", "ovo": "protein", "laticinio": "protein", "leguminosa": "protein"}


@dataclass
class Substitution:
    day_index: int
    meal_type: str
    old: str
    new: str
    old_grams: float
    new_grams: float
    saving: Decimal


def equivalent_grams(old: Food, old_g: float, new: Food) -> float:
    """Gramas do substituto que igualam o nutriente-chave do grupo (proteína ou energia)."""
    key = KEY_NUTRIENT.get(old.group or "", "kcal")
    a = getattr(food_macros(old, old_g), key)
    b = getattr(food_macros(new, 100), key)
    if not b:
        return old_g
    return _portion_round(new, min(old_g * 2.5, a / b * 100))


def economize_plan(s: Session, plan: MealPlan, budget: Decimal | None, profile: Profile) -> tuple[MealPlan, list[Substitution]]:
    """Cria uma nova versão do plano trocando itens por equivalentes mais baratos do mesmo grupo.

    Cada troca preserva o nutriente-chave do grupo; os totais do dia são recalculados ao final
    e apresentados ao usuário — não se presume equivalência nutricional completa.
    """
    prices = price_per_gram_map(s)
    foods = core_foods(s)
    excl = excluded_food_ids(foods, profile)
    candidates_by_group: dict[str, list[Food]] = {}
    for f in foods:
        if f.id in excl or f.group is None or f.state == "cru":
            continue
        # mesmo grupo e mesmo estado: evita trocar aveia (pronta) por arroz (cozido) no café
        candidates_by_group.setdefault(f"{f.group}:{f.state}", []).append(f)

    # monta o rascunho a partir dos cardápios distintos (ciclo) para manter o padrão do plano
    distinct = min(plan.days, 7)
    menus: list[list[DraftMeal]] = []
    for d in range(distinct):
        menus.append([DraftMeal(m.meal_type, m.title or m.meal_type,
                                [DraftItem(i.food, i.grams) for i in m.items], m.preparation or "")
                      for m in plan.meals if m.day_index == d])

    def menu_cost() -> Decimal:
        tot = Decimal(0)
        for menu in menus:
            for m in menu:
                for i in m.items:
                    c = item_cost(i.food, i.grams, prices, plan.people).cost
                    tot += c or Decimal(0)
        return tot

    cycle_factor = Decimal(plan.days) / Decimal(distinct)
    subs: list[Substitution] = []
    while True:
        best = None
        for d, menu in enumerate(menus):
            for m in menu:
                for idx, it in enumerate(m.items):
                    cur = item_cost(it.food, it.grams, prices, plan.people).cost
                    if cur is None:
                        continue
                    for alt in candidates_by_group.get(f"{it.food.group}:{it.food.state}", []):
                        if alt.id == it.food.id or any(x.food.id == alt.id for x in m.items):
                            continue
                        g = equivalent_grams(it.food, it.grams, alt)
                        c = item_cost(alt, g, prices, plan.people).cost
                        if c is None:
                            continue
                        saving = cur - c
                        if saving > Decimal("0.05") and (best is None or saving > best[0]):
                            best = (saving, d, m, idx, alt, g)
        if best is None:
            break
        saving, d, m, idx, alt, g = best
        old = m.items[idx]
        subs.append(Substitution(d, m.meal_type, old.food.short_name or old.food.name, alt.short_name or alt.name,
                                 old.grams, g, money(saving * cycle_factor)))
        m.items[idx] = DraftItem(alt, g, old.role)
        if budget is not None and menu_cost() * cycle_factor <= budget:
            break
        if len(subs) > 60:
            break
    new = save_plan(s, profile.id, f"{plan.name.split(' (')[0]} (econômico)", menus, plan.days, people=plan.people,
                    start=plan.start_date, origin="local", target_kcal=plan.target_kcal,
                    target_protein=plan.target_protein_g, budget=budget, parent_id=plan.id,
                    notes=f"Versão econômica de #{plan.id} com {len(subs)} substituições.")
    return new, subs


def replace_food_in_plan(s: Session, plan: MealPlan, old_food_id: int, new_food_id: int) -> int:
    """Substitui um alimento em todo o plano preservando o nutriente-chave. Devolve nº de itens."""
    new = s.get(Food, new_food_id)
    if not new:
        raise ValueError("Alimento substituto inexistente.")
    n = 0
    for m in plan.meals:
        for it in m.items:
            if it.food_id == old_food_id:
                it.grams = equivalent_grams(it.food, it.grams, new)
                it.food_id, it.food = new.id, new
                n += 1
    s.flush()
    return n


def daily_totals_dataframe(summary: PlanSummary):
    import pandas as pd
    rows = []
    for d, m in summary.day_macros.items():
        rows.append({"dia": d + 1, "kcal": round(m.kcal), "proteína (g)": round(m.protein),
                     "carboidratos (g)": round(m.carbs), "gorduras (g)": round(m.fat),
                     "custo": float(summary.day_cost.get(d) or 0)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- consumo registrado

def log_meal(s: Session, profile_id: int, meal: Meal, on: date | None = None) -> None:
    from database.models import MealLog
    mac = sum((food_macros(i.food, i.grams) for i in meal.items), Macros())
    s.add(MealLog(profile_id=profile_id, meal_id=meal.id, eaten_on=on or date.today(),
                  title=f"{meal.meal_type}: {meal.title or ''}"[:160], kcal=round(mac.kcal, 1),
                  protein_g=round(mac.protein, 1), carbs_g=round(mac.carbs, 1), fat_g=round(mac.fat, 1)))


def unlog_meal(s: Session, profile_id: int, meal_id: int, on: date | None = None) -> None:
    from database.models import MealLog
    for m in s.scalars(select(MealLog).where(MealLog.profile_id == profile_id, MealLog.meal_id == meal_id,
                                             MealLog.eaten_on == (on or date.today()))):
        s.delete(m)


def consumed(s: Session, profile_id: int, on: date | None = None) -> tuple[Macros, set[int]]:
    from database.models import MealLog
    rows = list(s.scalars(select(MealLog).where(MealLog.profile_id == profile_id,
                                                MealLog.eaten_on == (on or date.today()))))
    tot = Macros(sum(r.kcal for r in rows), sum(r.protein_g for r in rows), sum(r.carbs_g for r in rows),
                 sum(r.fat_g for r in rows))
    return tot, {r.meal_id for r in rows if r.meal_id}
