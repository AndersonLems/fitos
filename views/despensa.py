from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import select

from components import ui
from components.state import flash, require_profile
from database.connection import session_scope
from database.models import Food, Profile, Recipe, RecipeIngredient, ShoppingItem, ShoppingList
from services import ai_planner
from services import gemini_service as gs
from services import goal_service as gls
from services import inventory_service as inv
from services import nutrition_service as ns
from services import profile_service as ps
from services.pricing_service import price_per_gram_map
from services.shopping_service import available_stock
from utils.units import UNIT_LABELS, UnitError, fmt_brl, fmt_qty

p = require_profile()
ui.page_header("Minha despensa", "O que já existe em casa. A lista de compras desconta este estoque (itens vencidos "
               "não contam) e a cozinha sugere o que dá para preparar com ele.")
e = ps.estimate_energy(p)
with session_scope() as _s:
    tg = gls.daily_targets(_s, p)

tab_est, tab_coz = st.tabs(["Estoque", "O que posso preparar hoje?"])

with session_scope() as s:
    foods = list(s.scalars(select(Food).order_by(Food.is_core.desc(), Food.short_name, Food.name)))
fmap = {f.id: (f.short_name or f.name) for f in foods}

with tab_est:
    with st.expander("Adicionar item à despensa", icon=":material/add:"):
        with st.form("add_estoque", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns([3, 1, 1.2, 1.4])
            fid = c1.selectbox("Alimento", list(fmap), format_func=fmap.get, index=None, placeholder="Escolha")
            qty = c2.text_input("Quantidade", "1")
            unit = c3.selectbox("Unidade", list(UNIT_LABELS), format_func=UNIT_LABELS.get)
            gpu = c4.number_input("g por unidade", 0.0, 5000.0, None, 1.0, help="Obrigatório para unidade/dúzia")
            c1, c2 = st.columns([1, 3])
            exp = c1.date_input("Validade (opcional)", None, format="DD/MM/YYYY")
            notes = c2.text_input("Observações")
            ui.note("Cadastre no estado em que está em casa: arroz e feijão crus, frango cru etc. O cardápio converte "
                    "porções cozidas para o peso cru antes de descontar.")
            ok = st.form_submit_button("Adicionar à despensa", type="primary")
    if ok:
        try:
            if fid is None:
                raise UnitError("Escolha o alimento.")
            with session_scope() as s:
                inv.add_item(s, p.id, fid, qty, unit, expires_on=exp, grams_per_unit=gpu, notes=notes)
            flash("Item adicionado.")
            st.rerun()
        except UnitError as exc:
            st.error(str(exc))

    with session_scope() as s:
        items = inv.list_items(s, p.id)
    soon = inv.expiring(items)
    if soon:
        st.warning("Vencendo em até 3 dias ou vencido: " + ", ".join(
            f"{i.food.short_name or i.food.name} ({i.expires_on:%d/%m})" for i in soon))
    if items:
        rows = []
        for item in items:
            kind = "bad" if item.expires_on and item.expires_on < date.today() else "warn" if item in soon else ""
            rows.append('<div class="fx-inventory-row"><div><strong>' + ui.esc(item.food.short_name or item.food.name)
                        + '</strong><div class="fx-ex-d">' + ui.esc(item.notes or "") + '</div></div><span>'
                        + ui.esc(fmt_qty(item.quantity, item.unit)) + '</span><span>'
                        + ui.chip(ui.fmt_date(item.expires_on) if item.expires_on else "Sem validade", kind) + '</span></div>')
        st.html('<div class="fx-card"><div class="fx-inventory-row fx-eyebrow"><span>Item</span><span>Quantidade</span><span>Validade</span></div>' + ''.join(rows) + '</div>')
        df = pd.DataFrame([{"id": i.id, "alimento": i.food.short_name or i.food.name,
                            "quantidade": float(i.quantity), "unidade": i.unit, "validade": i.expires_on,
                            "situação": ("vencido" if i.expires_on and i.expires_on < date.today() else
                                         "vence logo" if i in soon else "ok"),
                            "observações": i.notes or "", "remover": False} for i in items])
        with st.expander("Editar quantidades, validade ou remover itens"):
            ed = st.data_editor(df, hide_index=True, width="stretch", key="estoque",
                                disabled=["id", "alimento", "unidade", "situação"],
                                column_config={"id": None,
                                               "quantidade": st.column_config.NumberColumn(min_value=0, step=0.1),
                                               "validade": st.column_config.DateColumn(format="DD/MM/YYYY")})
        to_remove = ed[ed["remover"]]
        c1, c2 = st.columns([1, 3])
        confirm = True
        if len(to_remove):
            confirm = c2.checkbox(f"Confirmo remover {len(to_remove)} item(ns)")
        if c1.button("Salvar despensa", type="primary", disabled=not confirm):
            try:
                with session_scope() as s:
                    for r in ed.to_dict("records"):
                        if r["remover"]:
                            inv.update_quantity(s, int(r["id"]), p.id, 0)
                            continue
                        inv.update_quantity(s, int(r["id"]), p.id, r["quantidade"])
                        it = s.get(type(items[0]), int(r["id"]))
                        if it:
                            it.expires_on = r["validade"] if not pd.isna(r["validade"]) else None
                            it.notes = r["observações"] or None
                flash("Despensa atualizada.")
                st.rerun()
            except UnitError as exc:
                st.error(str(exc))
    else:
        st.info("Despensa vazia.")

with tab_coz:
    with session_scope() as s:
        stock = available_stock(s, p.id)
        core = ns.core_foods(s)
        prices = price_per_gram_map(s)
        prof = s.get(Profile, p.id)
        excl = ns.excluded_food_ids(core, prof)
    usable = [f for f in core if f.id not in excl and (f.id in stock or (f.raw_food_id and f.raw_food_id in stock))]

    def missing_list(menu) -> list[tuple[Food, float]]:
        need: dict[int, tuple[Food, float]] = {}
        for m in menu:
            for it in m.items:
                pf, g = ns.purchase_requirement(it.food, it.grams)
                prev = need.get(pf.id, (pf, 0.0))[1]
                need[pf.id] = (pf, prev + g)
        return [(f, g - float(stock.get(f.id, 0))) for f, g in need.values() if g - float(stock.get(f.id, 0)) > 1]

    def show_menu(menu, title: str) -> None:
        st.html(f'<div class="fx-day">{ui.esc(title)}</div>')
        tot = ns.Macros()
        for m in menu:
            mac = sum((ns.food_macros(i.food, i.grams) for i in m.items), ns.Macros())
            tot = tot + mac
            st.html(f'<div class="fx-meal"><b>{ui.esc(m.meal_type)}</b> <span>· {mac.kcal:.0f} kcal · '
                    f'P {mac.protein:.0f} g</span></div>' + ui.bullet_list(
                        [f"{i.grams:g} g de {i.food.short_name or i.food.name}" for i in m.items]))
            if m.preparation:
                st.caption(m.preparation)
        st.caption(f"Total: {tot.kcal:.0f} kcal · P {tot.protein:.0f} g · C {tot.carbs:.0f} g · G {tot.fat:.0f} g "
                   "(calculado pelo FitOS com a TACO)")

    def offer_missing(miss, key: str) -> None:
        if not miss:
            st.success("Tudo disponível na despensa.")
            return
        rows = []
        for f, g in miss:
            q = prices.get(f.id)
            cost = (q.per_gram * Decimal(str(round(g, 1)))) if q else None
            rows.append({"item": f.short_name or f.name, "faltam": fmt_qty(Decimal(str(round(g))), "g"),
                         "custo estimado": fmt_brl(cost) if cost is not None else "sem preço"})
        st.markdown("**Lista complementar de compras**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if st.button("Criar lista com esses itens", key=f"ml{key}"):
            with session_scope() as s:
                sl = ShoppingList(profile_id=p.id, name=f"Complementar {date.today():%d/%m}")
                s.add(sl)
                s.flush()
                for f, g in miss:
                    q = prices.get(f.id)
                    gd = Decimal(str(round(g, 1)))
                    s.add(ShoppingItem(list_id=sl.id, food_id=f.id, label=f.short_name or f.name, needed_base=gd,
                                       stock_base=Decimal(0), to_buy_base=gd, base_unit="g",
                                       product_id=q.product.id if q else None, quote_id=q.quote.id if q else None,
                                       estimated_cost=(q.per_gram * gd).quantize(Decimal("0.01")) if q else None))
            flash("Lista complementar criada em Mercado inteligente → Lista de compras.")
            st.rerun()

    st.markdown("#### Refeições com o que tenho")
    st.caption(f"{len(stock)} alimento(s) utilizáveis na despensa.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Montar refeições de amanhã (sem IA)", disabled=not usable):
            menu = ns.local_menu(usable, 0, tg.kcal, tg.protein_g, meals=tg.meals_per_day)
            st.session_state["coz_local"] = [(m.meal_type, m.preparation, [(i.food.id, i.grams) for i in m.items])
                                             for m in menu]
        if not usable:
            st.caption("Cadastre alimentos na despensa para usar o montador local.")
    with c2:
        if st.button("Montar refeições de amanhã com Gemini", disabled=not (gs.is_configured() and stock)):
            try:
                with ui.loading("Consultando o Gemini…"), session_scope() as s:
                    menu, miss, nts = ai_planner.ai_tomorrow_from_stock(s, s.get(Profile, p.id), tg.kcal,
                                                                        tg.protein_g)
                st.session_state["coz_local"] = [(m.meal_type, m.preparation, [(i.food.id, i.grams) for i in m.items])
                                                 for m in menu]
                st.session_state["coz_notes"] = nts
            except (gs.GeminiInvalidOutput, gs.GeminiUnavailable) as exc:
                st.error(str(exc))
    if data := st.session_state.get("coz_local"):
        with session_scope() as s:
            loaded = {f.id: f for f in ns.core_foods(s)}
        menu = [ns.DraftMeal(mt, "", [ns.DraftItem(loaded[fid], g) for fid, g in items if fid in loaded], prep)
                for mt, prep, items in data]
        show_menu(menu, f"Amanhã, {(date.today() + timedelta(days=1)):%d/%m}")
        if st.session_state.get("coz_notes"):
            st.caption(st.session_state["coz_notes"])
        offer_missing(missing_list(menu), "amanha")

    st.divider()
    st.markdown("#### Receitas para hoje (Gemini)")
    with st.form("receitas"):
        ingredients = st.text_input("Ingredientes que você quer usar (opcional)", placeholder="Ex.: frango, batata-doce, brócolis")
        c1, c2 = st.columns(2)
        use_stock = c1.checkbox("Considerar a despensa", True)
        minutes = c2.number_input("Tempo máximo (min)", 5, 180, 30, 5)
        go_ = st.form_submit_button("Sugerir receitas", disabled=not gs.is_configured())
    if go_:
        try:
            with ui.loading("Consultando o Gemini…"), session_scope() as s:
                recs, _ = ai_planner.ai_recipes(s, s.get(Profile, p.id), ingredients, use_stock, max_minutes=minutes,
                                                target_kcal=tg.kcal, target_protein=tg.protein_g)
            st.session_state["receitas"] = [r.model_dump() for r in recs]
        except (gs.GeminiInvalidOutput, gs.GeminiUnavailable) as exc:
            st.error(str(exc))
    by = {f.id: f for f in core}
    for k, r in enumerate(st.session_state.get("receitas", [])):
        mac = sum((ns.food_macros(by[i["food_id"]], i["grams"]) for i in r["items"] if i["food_id"] in by), ns.Macros())
        with ui.panel(f"receita-{k}"):
            st.markdown(f"**{r['name']}** · {r['prep_minutes']} min · {mac.kcal:.0f} kcal · P {mac.protein:.0f} g")
            st.html(ui.bullet_list([f"{i['grams']:g} g de {by[i['food_id']].short_name}" for i in r["items"]
                                    if i["food_id"] in by]))
            st.markdown(r["instructions"])
            if r["missing"]:
                st.caption("Falta comprar: " + ", ".join(f"{m['name']} (~{m['grams']:.0f} g)" for m in r["missing"]))
            if st.button("Salvar receita", key=f"sr{k}"):
                with session_scope() as s:
                    rec = Recipe(profile_id=p.id, name=r["name"][:160], instructions=r["instructions"],
                                 prep_minutes=r["prep_minutes"], origin="gemini")
                    rec.ingredients = [RecipeIngredient(food_id=i["food_id"], grams=i["grams"]) for i in r["items"]
                                       if i["food_id"] in by]
                    s.add(rec)
                flash("Receita salva.")
                st.rerun()

    with session_scope() as s:
        saved = list(s.scalars(select(Recipe).where(Recipe.profile_id == p.id).order_by(Recipe.id.desc())))
        saved_data = [(r.id, r.name, r.prep_minutes, r.instructions, [(i.food_id, i.grams) for i in r.ingredients])
                      for r in saved]
    if saved_data:
        st.markdown("#### Minhas receitas")
        allf = {f.id: f for f in foods}
        for rid, name, mins, instr, ings in saved_data:
            have = all(fid in stock or (allf[fid].raw_food_id in stock) for fid, _ in ings)
            with st.expander(f"{name} · {mins or '?'} min" + (" · dá para fazer com a despensa" if have else "")):
                st.html(ui.bullet_list([f"{g:g} g de {allf[fid].short_name or allf[fid].name}" for fid, g in ings]))
                st.markdown(instr or "")
                if st.button("Apagar receita", key=f"dr{rid}"):
                    with session_scope() as s:
                        s.delete(s.get(Recipe, rid))
                    st.rerun()
