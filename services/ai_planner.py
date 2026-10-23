"""Gerações com Gemini: prompts compactos + validação contra o catálogo local.

O Gemini escolhe exercícios e alimentos pelos IDs enviados; o Python valida, recalcula e salva.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import Exercise, Food, Profile
from services import gemini_service as gs
from services import nutrition_service as ns
from services import workout_service as ws
from services.inventory_service import list_items
from services.pricing_service import price_per_gram_map
from services.profile_service import ACTIVITY, EXPERIENCE, GOALS, WEEKDAYS


def profile_brief(p: Profile) -> dict:
    return {
        "idade": p.age, "peso_kg": p.weight_kg, "altura_cm": p.height_cm,
        "sexo": {"M": "masculino", "F": "feminino"}.get(p.sex, "não informado"),
        "objetivo": GOALS.get(p.goal, "não informado"),
        "atividade": ACTIVITY[p.activity_level][1] if p.activity_level in ACTIVITY else "não informado",
        "experiencia": EXPERIENCE.get(p.experience, "não informada"),
        "dias_treino": [WEEKDAYS[d] for d in (p.training_weekdays or [])] or "não informado",
        "minutos_por_treino": p.session_minutes or "não informado",
        "equipamentos": p.equipment or "não informado",
        "limitacoes": p.injuries or "nenhuma informada",
        "restricoes": p.restrictions or "nenhuma", "alergias": p.allergies or "nenhuma",
        "preferencias": p.preferences or "nenhuma",
    }


# --------------------------------------------------------------------------- treino

def ai_workout_plan(s: Session, profile: Profile, extra_request: str = "") -> tuple[object, str]:
    equipment = ws.allowed_equipment(profile)
    exs = [e for e in ws.core_exercises(s) if equipment is None or (e.equipment or "") in equipment]
    catalog = [[e.id, e.name_pt, e.slot, e.equipment, e.difficulty] for e in exs]
    valid_ids = {e.id for e in exs}
    history = ws.history_dataframe(s, profile.id)
    hist_txt = "sem histórico"
    if not history.empty:
        recent = history[history["concluida"]].groupby("exercicio").agg(carga=("carga", "max"), reps=("reps", "max"))
        hist_txt = gs.compact(recent.tail(15).reset_index().values.tolist())
    prompt = (
        "Monte uma ficha de musculação semanal para este perfil.\n"
        f"PERFIL: {gs.compact(profile_brief(profile))}\n"
        f"HISTÓRICO RECENTE (exercício, carga máx, reps máx): {hist_txt}\n"
        f"CATÁLOGO PERMITIDO [id, nome, padrão, equipamento, dificuldade]: {gs.compact(catalog)}\n"
        "Regras: use SOMENTE exercise_id do catálogo; um dia por dia disponível (weekday 0=segunda); "
        "respeite o tempo por treino; evite movimentos que agravem as limitações informadas; volume moderado "
        "para a experiência; reps_min ≤ reps_max; títulos no formato 'SEGUNDA — PEITO, OMBROS E TRÍCEPS'.\n"
        + (f"Pedido adicional do usuário: {extra_request[:400]}\n" if extra_request else "")
    )

    def validate(plan: gs.GWPlan) -> list[str]:
        errs = []
        if not plan.days:
            errs.append("nenhum dia gerado")
        for d in plan.days:
            if d.weekday is not None and not 0 <= d.weekday <= 6:
                errs.append(f"weekday inválido em {d.title}")
            if not d.exercises:
                errs.append(f"dia sem exercícios: {d.title}")
            for e in d.exercises:
                if e.exercise_id not in valid_ids:
                    errs.append(f"exercise_id {e.exercise_id} não existe no catálogo enviado")
                if e.reps_min > e.reps_max:
                    errs.append(f"reps_min > reps_max no exercício {e.exercise_id}")
        return errs

    plan = gs.generate_structured(s, prompt, gs.GWPlan, purpose="treino", profile_id=profile.id, validator=validate)
    by_id = {e.id: e for e in exs}
    days = [ws.DraftDay(d.title, d.weekday, [ws.DraftExercise(by_id[e.exercise_id], e.sets, e.reps_min, e.reps_max,
                                                              e.rest_seconds, e.notes) for e in d.exercises])
            for d in plan.days]
    saved = ws.save_plan(s, profile.id, plan.name or "Ficha Gemini", days, origin="gemini", rationale=plan.rationale)
    return saved, plan.rationale


# --------------------------------------------------------------------------- cardápio

def _food_catalog(s: Session, profile: Profile, only_ids: set[int] | None = None) -> tuple[list[Food], list]:
    foods = [f for f in ns.core_foods(s) if f.state != "cru" or f.taco_id == 40]
    excl = ns.excluded_food_ids(foods, profile)
    foods = [f for f in foods if f.id not in excl and (only_ids is None or f.id in only_ids)]
    prices = price_per_gram_map(s)
    rows = []
    for f in foods:
        m = ns.food_macros(f, 100)
        ic = ns.item_cost(f, 100, prices)
        rows.append([f.id, f.short_name, f.group, round(m.kcal), round(m.protein, 1),
                     float(ic.cost) if ic.cost is not None else None])
    return foods, rows


ROLE_BY_GROUP = {"proteina": "protein", "ovo": "protein", "cereal": "carb", "tuberculo": "carb", "pao": "carb"}


def _menu_validator(valid: set[int], days_expected: int, target_kcal: float, target_protein: float):
    def validate(plan: gs.GMPlan) -> list[str]:
        errs = []
        if len(plan.days) != days_expected:
            errs.append(f"esperados {days_expected} dias, vieram {len(plan.days)}")
        return errs + _check_days(plan.days, valid, target_kcal, target_protein)
    return validate


_FOODS_CACHE: dict[int, Food] = {}


def _check_days(days: list, valid: set[int], target_kcal: float, target_protein: float) -> list[str]:
    errs = []
    for i, d in enumerate(days):
        tot = ns.Macros()
        for m in d.meals:
            for it in m.items:
                if it.food_id not in valid:
                    errs.append(f"dia {i + 1}: food_id {it.food_id} fora do catálogo")
                    continue
                if not 3 <= it.grams <= 700:
                    errs.append(f"dia {i + 1}: porção de {it.grams} g fora do razoável (food_id {it.food_id})")
                tot = tot + ns.food_macros(_FOODS_CACHE[it.food_id], it.grams)
        if target_kcal and abs(tot.kcal - target_kcal) / target_kcal > 0.25:
            errs.append(f"dia {i + 1}: {tot.kcal:.0f} kcal calculadas, meta {target_kcal:.0f} (tolerância 25%)")
        if target_protein and tot.protein < 0.75 * target_protein:
            errs.append(f"dia {i + 1}: {tot.protein:.0f} g de proteína calculados, meta {target_protein:.0f} g")
    return errs


def _to_drafts(days: list, by_id: dict[int, Food]) -> list[list[ns.DraftMeal]]:
    out = []
    for d in days:
        out.append([ns.DraftMeal(m.meal_type, m.title, [ns.DraftItem(by_id[i.food_id], float(i.grams),
                                                                     ROLE_BY_GROUP.get(by_id[i.food_id].group, "fixed"))
                                                        for i in m.items], m.preparation) for m in d.meals])
    return out


def ai_meal_plan(s: Session, profile: Profile, days: int, target_kcal: float, target_protein: float, *,
                 people: int = 1, economic: bool = False, budget: Decimal | None = None, extra: str = ""):
    foods, rows = _food_catalog(s, profile)
    by_id = {f.id: f for f in foods}
    _FOODS_CACHE.update(by_id)
    distinct = min(days, 7)
    budget_txt = ""
    if budget is not None:
        budget_txt = f"Orçamento para o período de {days} dias e {people} pessoa(s): R$ {budget}. "
    prompt = (
        f"Crie {distinct} cardápios diários distintos (serão repetidos em ciclo até {days} dias).\n"
        f"PERFIL: {gs.compact(profile_brief(profile))}\n"
        f"METAS DIÁRIAS POR PESSOA: {target_kcal:.0f} kcal, {target_protein:.0f} g de proteína.\n"
        f"CATÁLOGO [food_id, nome, grupo, kcal/100g, proteína/100g, custo R$/100g ou null se sem preço]: "
        f"{gs.compact(rows)}\n"
        "Regras: use SOMENTE food_id do catálogo; gramas no estado indicado no nome (cozido/cru/pronto); "
        "4 refeições (Café da manhã, Almoço, Lanche, Jantar); preparo simples em 1–2 frases; comida brasileira "
        "do dia a dia; respeite restrições e alergias. "
        + ("Priorize os alimentos de menor custo com preço conhecido, mantendo as metas. " if economic else "")
        + budget_txt + (f"Pedido do usuário: {extra[:300]}" if extra else "")
    )
    plan = gs.generate_structured(s, prompt, gs.GMPlan, purpose="cardapio", profile_id=profile.id,
                                  validator=_menu_validator(set(by_id), distinct, target_kcal, target_protein))
    menus = _to_drafts(plan.days, by_id)
    for day in menus:  # ajuste fino determinístico das porções às metas (o Python fecha a conta)
        ns.fit_portions(day, target_kcal, target_protein)
    label = "econômico" if economic else "Gemini"
    return ns.save_plan(s, profile.id, f"Cardápio {ns.PLAN_LENGTHS.get(days, f'{days} dias')} ({label})", menus, days,
                        people=people, start=date.today(), origin="gemini", target_kcal=target_kcal,
                        target_protein=target_protein, budget=budget,
                        notes=plan.notes or (f"{distinct} cardápios distintos repetidos em ciclo." if days > distinct else None))


def ai_economic_version(s: Session, profile: Profile, plan, budget: Decimal | None):
    summary = ns.summarize(s, plan)
    current = []
    for d, meals in list(summary.days.items())[:7]:
        current.append([[m.meal.meal_type, [[i.food_id, i.grams] for i in m.meal.items]] for m in meals])
    cost = summary.total_cost
    extra = (f"Esta é uma versão mais econômica do cardápio atual (custo calculado R$ {cost} para {plan.days} dias). "
             f"Cardápio atual [refeição, [[food_id, gramas]]]: {gs.compact(current)}. Troque os itens caros por "
             "equivalentes mais baratos com preço conhecido, sem presumir que o mais barato tem o mesmo valor "
             "nutricional: ajuste as gramas para manter proteína e energia.")
    new = ai_meal_plan(s, profile, plan.days, plan.target_kcal or 2000, plan.target_protein_g or 100,
                       people=plan.people, economic=True, budget=budget, extra=extra)
    new.parent_id = plan.id
    return new


# --------------------------------------------------------------------------- cozinha

def ai_recipes(s: Session, profile: Profile, ingredients_text: str, use_stock: bool, *, max_minutes: int | None,
               target_kcal: float | None, target_protein: float | None) -> tuple[list[gs.GRecipe], dict[int, Food]]:
    only = None
    stock_txt = ""
    if use_stock:
        items = list_items(s, profile.id)
        only = {i.food_id for i in items}
        stock_txt = "; ".join(f"{i.food.short_name or i.food.name} [id {i.food_id}] {i.quantity:g} {i.unit}" for i in items)
    foods, rows = _food_catalog(s, profile)
    by_id = {f.id: f for f in foods}
    prompt = (
        "Sugira até 3 receitas simples para hoje.\n"
        f"PERFIL: {gs.compact(profile_brief(profile))}\n"
        + (f"ESTOQUE EM CASA: {stock_txt or 'vazio'}\n" if use_stock else "")
        + (f"INGREDIENTES INFORMADOS: {ingredients_text[:400]}\n" if ingredients_text else "")
        + f"CATÁLOGO [food_id, nome, grupo, kcal/100g, prot/100g, custo]: {gs.compact(rows)}\n"
        + (f"Tempo máximo de preparo: {max_minutes} min. " if max_minutes else "")
        + (f"Referência por refeição: ~{target_kcal / 4:.0f} kcal e ~{target_protein / 4:.0f} g de proteína. "
           if target_kcal and target_protein else "")
        + "Use SOMENTE food_id do catálogo nos itens; o que faltar em casa vai em 'missing' (nome e gramas)."
    )

    def validate(r: gs.GRecipes) -> list[str]:
        errs = []
        for rec in r.recipes:
            for it in rec.items:
                if it.food_id not in by_id:
                    errs.append(f"{rec.name}: food_id {it.food_id} fora do catálogo")
                elif not 3 <= it.grams <= 700:
                    errs.append(f"{rec.name}: porção de {it.grams} g fora do razoável")
        return errs

    out = gs.generate_structured(s, prompt, gs.GRecipes, purpose="receitas", profile_id=profile.id, validator=validate)
    return out.recipes, by_id


def ai_tomorrow_from_stock(s: Session, profile: Profile, target_kcal: float, target_protein: float):
    items = list_items(s, profile.id)
    stock_ids = {i.food_id for i in items}
    foods, rows = _food_catalog(s, profile)
    by_id = {f.id: f for f in foods}
    _FOODS_CACHE.update(by_id)
    stock_txt = "; ".join(f"{i.food.short_name or i.food.name} [id {i.food_id}] {i.quantity:g} {i.unit}" for i in items)
    prompt = (
        "Monte as 4 refeições de amanhã usando APENAS o que há no estoque, respeitando as quantidades.\n"
        f"PERFIL: {gs.compact(profile_brief(profile))}\nMETAS: {target_kcal:.0f} kcal, {target_protein:.0f} g proteína.\n"
        f"ESTOQUE: {stock_txt or 'vazio'}\nCATÁLOGO: {gs.compact(rows)}\n"
        "Se faltar algo essencial, use o alimento do catálogo mesmo assim e cite-o em notes como compra complementar."
    )

    def validate(plan: gs.GMPlan) -> list[str]:
        errs = [] if len(plan.days) == 1 else ["envie exatamente 1 dia"]
        for d in plan.days:
            for m in d.meals:
                for it in m.items:
                    if it.food_id not in by_id:
                        errs.append(f"food_id {it.food_id} fora do catálogo")
        return errs

    plan = gs.generate_structured(s, prompt, gs.GMPlan, purpose="amanha_estoque", profile_id=profile.id,
                                  validator=validate)
    menus = _to_drafts(plan.days, by_id)
    missing = sorted({(i.food.short_name or i.food.name) for m in menus[0] for i in m.items
                      if i.food.id not in stock_ids and (i.food.raw_food_id not in stock_ids)})
    return menus[0], missing, plan.notes


# --------------------------------------------------------------------------- textos

def ai_dashboard_recommendations(s: Session, profile: Profile, facts: dict) -> str:
    prompt = ("Com base nos dados abaixo, escreva até 4 recomendações curtas e práticas (uma linha cada, sem "
              "introdução), conservadoras, sobre treino, alimentação e gastos. Se faltar dado, diga qual "
              f"registrar.\nPERFIL: {gs.compact(profile_brief(profile))}\nDADOS: {gs.compact(facts)}")
    text = gs.generate_text(s, prompt, purpose="recomendacoes", profile_id=profile.id, max_tokens=400)
    gs.save_insight(s, profile.id, "dashboard", text)
    return text


def ai_trend_analysis(s: Session, profile: Profile, facts: dict) -> str:
    prompt = ("Analise as tendências abaixo (peso, medidas, frequência e cargas). Aponte o que os números mostram, "
              "o que não dá para concluir e até 3 revisões conservadoras. Não interprete fotos nem estime "
              f"percentual de gordura.\nPERFIL: {gs.compact(profile_brief(profile))}\nDADOS: {gs.compact(facts)}")
    text = gs.generate_text(s, prompt, purpose="tendencias", profile_id=profile.id, max_tokens=600)
    gs.save_insight(s, profile.id, "evolucao", text)
    return text


def tomorrow() -> date:
    return date.today() + timedelta(days=1)


def exercise_name(e: Exercise) -> str:
    return e.name_pt or e.name_original
