from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from components import ui
from components.state import flash, require_profile
from database.connection import session_scope
from database.models import Meal, MealPlan, Profile
from services import ai_planner
from services import gemini_service as gs
from services import nutrition_service as ns
from services import profile_service as ps
from services.pricing_service import price_per_gram_map
from utils.units import fmt_brl

p = require_profile()
ui.page_header("Meu plano alimentar", "Cardápios de 1 a 31 dias. As refeições podem ser propostas pelo gerador local "
               "ou pelo Gemini; calorias, macronutrientes e custos são sempre calculados pelo FitOS com a TACO e os "
               "seus preços.", kicker=p.name)
e = ps.estimate_energy(p)


def generation_form(key: str) -> None:
    with st.form(f"gen{key}"):
        c1, c2, c3 = st.columns(3)
        days = c1.selectbox("Período", list(ns.PLAN_LENGTHS), index=1, format_func=ns.PLAN_LENGTHS.get)
        people = c2.number_input("Pessoas", 1, 12, p.people_count or 1)
        mode = c3.radio("Quem propõe as refeições", ["Gerador local (sem IA)", "Gemini"], horizontal=False,
                        disabled=False)
        c1, c2, c3 = st.columns(3)
        kcal = c1.number_input("Meta diária (kcal por pessoa)", 1000, 5000, int(e.target_kcal), 50)
        prot = c2.number_input("Proteína diária (g por pessoa)", 40, 300, int(e.protein_g), 5)
        budget = c3.number_input("Orçamento do período (R$, opcional)", 0.0, 100000.0, None, 10.0, format="%.2f")
        economic = st.checkbox("Priorizar os alimentos mais baratos cadastrados")
        extra = st.text_input("Pedido para o Gemini (opcional)", placeholder="Ex.: refeições rápidas, sem peixe no jantar")
        if e.is_provisional:
            ui.note("Metas pré-preenchidas com estimativa provisória (faltam: " + ", ".join(e.provisional) + ").")
        ok = st.form_submit_button("Gerar cardápio", type="primary")
    if ok:
        b = Decimal(str(round(budget, 2))) if budget else None
        try:
            with st.spinner("Montando o cardápio…"), session_scope() as s:
                prof = s.get(Profile, p.id)
                if mode == "Gemini":
                    plan = ai_planner.ai_meal_plan(s, prof, days, kcal, prot, people=people, economic=economic,
                                                   budget=b, extra=extra)
                else:
                    plan = ns.generate_local_plan(s, prof, days, kcal, prot, people=people, economic=economic, budget=b)
            flash(f"Cardápio “{plan.name}” criado.")
            st.rerun()
        except gs.GeminiInvalidOutput as exc:
            st.error(f"{exc} Problemas: {'; '.join(exc.errors[:5])}")
        except gs.GeminiUnavailable as exc:
            st.error(str(exc))


with session_scope() as s:
    plan = ns.active_plan(s, p.id)
    if plan:
        prices = price_per_gram_map(s)
        sm = ns.summarize(s, plan, prices)
        _, eaten = ns.consumed(s, p.id)

if not plan:
    st.info("Nenhum cardápio ativo.")
    generation_form("first")
    st.stop()

avg = sm.avg_macros
total = sm.total_cost
ui.tiles([
    {"label": "Energia média por dia", "value": f"{ui.fmt_num(avg.kcal)} kcal",
     "detail": f"meta {ui.fmt_num(plan.target_kcal)} kcal" if plan.target_kcal else "", "accent": True},
    {"label": "Proteína média por dia", "value": f"{avg.protein:.0f} g",
     "detail": f"meta {plan.target_protein_g:.0f} g" if plan.target_protein_g else ""},
    {"label": "Carboidratos / gorduras", "value": f"{avg.carbs:.0f} / {avg.fat:.0f} g"},
    {"label": f"Custo do período ({plan.days} dias, {plan.people} pessoa{'s' if plan.people > 1 else ''})",
     "value": fmt_brl(total), "detail": f"{fmt_brl(sm.avg_daily_cost())} por dia" + (
         f" · orçamento {fmt_brl(plan.budget)}" if plan.budget else "")},
    {"label": "Custo semanal / mensal estimado",
     "value": f"{fmt_brl(sm.avg_daily_cost() * 7) if sm.avg_daily_cost() else '—'}",
     "detail": f"{fmt_brl(sm.avg_daily_cost() * 30)} em 30 dias" if sm.avg_daily_cost() else ""},
])
if sm.unpriced:
    st.warning(f"{len(sm.unpriced)} alimento(s) sem preço cadastrado — o custo está incompleto: "
               + ", ".join(sorted(sm.unpriced)[:12]) + (" e outros" if len(sm.unpriced) > 12 else "")
               + ". Cadastre os preços em Mercado inteligente.")
ui.note(f"{ui.esc(plan.name)} · origem {plan.origin} · início {ui.fmt_date(plan.start_date)}"
        + (f" · {ui.esc(plan.notes)}" if plan.notes else "")
        + ". Custos por refeição/dia são proporcionais ao consumido (sem arredondar embalagens); a lista de compras "
          "mostra o valor das embalagens inteiras.")

tab_dia, tab_resumo, tab_acoes, tab_hist = st.tabs(["Cardápio do dia", "Resumo do período", "Ajustes", "Histórico"])

with tab_dia:
    day = st.selectbox("Dia", list(sm.days), format_func=lambda d: f"Dia {d + 1} — "
                       f"{(plan.start_date + pd.Timedelta(days=d)):%d/%m}")
    dm = sm.day_macros[day]
    st.html(ui.chip(f"{dm.kcal:.0f} kcal") + ui.chip(f"P {dm.protein:.0f} g") + ui.chip(f"C {dm.carbs:.0f} g")
            + ui.chip(f"G {dm.fat:.0f} g") + ui.chip(f"custo {fmt_brl(sm.day_cost[day])}"))
    for ms in sm.days[day]:
        meal = ms.meal
        st.html(f'<div class="fx-meal"><b>{ui.esc(meal.meal_type)}</b> <span>· {ui.esc(meal.title or "")} · '
                f'{ms.macros.kcal:.0f} kcal · P {ms.macros.protein:.0f} g · {fmt_brl(ms.cost)}'
                f'{" (parcial)" if ms.unpriced else ""}</span></div>')
        rows = []
        for it in meal.items:
            m = ns.food_macros(it.food, it.grams)
            ic = ns.item_cost(it.food, it.grams, prices, plan.people)
            rows.append({"alimento": it.food.short_name or it.food.name, "quantidade": f"{it.grams:g} g",
                         "estado": it.food.state, "kcal": round(m.kcal), "proteína": round(m.protein, 1),
                         "carbo": round(m.carbs, 1), "gordura": round(m.fat, 1),
                         "comprar (cru)": f"{ic.purchase_grams:.0f} g" + (" ×pessoas" if plan.people > 1 else ""),
                         "custo": fmt_brl(ic.cost) if ic.cost is not None else "sem preço"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        c1, c2 = st.columns([4, 1])
        if meal.preparation:
            c1.caption("Preparo: " + meal.preparation)
        if meal.id in eaten:
            if c2.button("Desmarcar", key=f"un{meal.id}"):
                with session_scope() as s:
                    ns.unlog_meal(s, p.id, meal.id)
                st.rerun()
        elif c2.button("Comi hoje", key=f"eat{meal.id}"):
            with session_scope() as s:
                ns.log_meal(s, p.id, s.get(Meal, meal.id))
            st.rerun()
    ui.note("Valores nutricionais: TACO 4ª ed. (NEPA/UNICAMP). Conversão cru/cozido por índice de cocção de referência "
            "e perdas por fator de correção — estimativas editáveis. Planejamento pessoal, não prescrição clínica.")

with tab_resumo:
    df = ns.daily_totals_dataframe(sm)
    fig = go.Figure()
    fig.add_bar(x=df["dia"], y=df["kcal"], name="Energia", marker=dict(color=ui.SERIES[0], line=dict(width=0)),
                hovertemplate="%{y} kcal<extra></extra>")
    if plan.target_kcal:
        fig.add_hline(y=plan.target_kcal, line=dict(color=ui.MUTED, width=1, dash="dot"), annotation_text="meta",
                      annotation_font_color=ui.MUTED)
    fig.update_xaxes(title="dia", dtick=1 if len(df) <= 15 else 5)
    ui.plot(ui.fig_layout(fig, "Energia por dia (kcal por pessoa)", 280))
    out = df.copy()
    out["custo"] = out["custo"].map(lambda v: fmt_brl(v))
    st.dataframe(out, hide_index=True, width="stretch")

with tab_acoes:
    st.markdown("**Versão mais econômica**")
    st.caption("Troca itens por equivalentes mais baratos do mesmo grupo, ajustando as gramas para manter proteína "
               "(fontes proteicas) ou energia (demais). Gera uma nova versão; os totais são recalculados.")
    c1, c2 = st.columns(2)
    budget = c1.number_input("Orçamento alvo para o período (R$)", 0.0, 100000.0,
                             float(plan.budget) if plan.budget else None, 10.0, format="%.2f")
    via = c2.radio("Como", ["Local (sem IA)", "Gemini"], horizontal=True)
    if st.button("Gerar versão econômica", type="primary"):
        b = Decimal(str(round(budget, 2))) if budget else None
        try:
            with st.spinner("Recalculando…"), session_scope() as s:
                prof = s.get(Profile, p.id)
                cur = ns.load_plan(s, plan.id)
                if via == "Gemini":
                    new = ai_planner.ai_economic_version(s, prof, cur, b)
                    subs = []
                else:
                    new, subs = ns.economize_plan(s, cur, b, prof)
                new_sm = ns.summarize(s, ns.load_plan(s, new.id))
            st.session_state["eco_result"] = (new.id, str(sm.total_cost), str(new_sm.total_cost),
                                              [(x.day_index + 1, x.meal_type, x.old, x.new, x.old_grams, x.new_grams,
                                                str(x.saving)) for x in subs],
                                              round(new_sm.avg_macros.kcal), round(new_sm.avg_macros.protein))
            st.rerun()
        except gs.GeminiInvalidOutput as exc:
            st.error(f"{exc} Problemas: {'; '.join(exc.errors[:5])}")
        except gs.GeminiUnavailable as exc:
            st.error(str(exc))
    res = st.session_state.get("eco_result")
    if res and res[0] == plan.id:
        _, old_c, new_c, subs, kcal, prot = res
        st.success(f"Custo: {fmt_brl(Decimal(old_c)) if old_c != 'None' else '—'} → "
                   f"{fmt_brl(Decimal(new_c)) if new_c != 'None' else '—'}. Nova média: {kcal} kcal, {prot} g de proteína.")
        if subs:
            st.dataframe(pd.DataFrame(subs, columns=["dia", "refeição", "antes", "depois", "g antes", "g depois",
                                                     "economia no período (R$)"]),
                         hide_index=True, width="stretch")
        elif not subs:
            st.caption("Sem substituições listadas (versão gerada pelo Gemini ou nenhuma troca mais barata disponível).")

    st.divider()
    st.markdown("**Substituir um alimento em todo o cardápio**")
    with session_scope() as s:
        in_plan = {}
        for m in plan.meals:
            for it in m.items:
                in_plan[it.food_id] = it.food
        foods = ns.core_foods(s)
    old_id = st.selectbox("Alimento", list(in_plan), format_func=lambda i: in_plan[i].short_name or in_plan[i].name)
    old = in_plan[old_id]
    same = [f for f in foods if f.group == old.group and f.id != old.id and f.state == old.state]
    if same:
        new_id = st.selectbox("Trocar por", [f.id for f in same],
                              format_func=lambda i: next(f.short_name for f in same if f.id == i))
        if st.button("Substituir e recalcular"):
            with session_scope() as s:
                n = ns.replace_food_in_plan(s, ns.load_plan(s, plan.id), old_id, new_id)
            flash(f"{n} item(ns) substituídos.")
            st.rerun()
    else:
        st.caption("Sem alternativas do mesmo grupo no catálogo.")

    with st.expander("Gerar novo cardápio"):
        generation_form("new")

with tab_hist:
    with session_scope() as s:
        plans = list(s.scalars(select(MealPlan).where(MealPlan.profile_id == p.id).order_by(MealPlan.id.desc())))
    for mp in plans:
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**{mp.name}** · {mp.days} dias · {mp.origin} · {mp.created_at:%d/%m/%Y %H:%M}"
                    + (" · **ativo**" if mp.is_active else "") + (f"  \n{mp.notes}" if mp.notes else ""))
        if not mp.is_active and c2.button("Reativar", key=f"ra{mp.id}"):
            with session_scope() as s:
                for o in s.scalars(select(MealPlan).where(MealPlan.profile_id == p.id)):
                    o.is_active = o.id == mp.id
            st.rerun()
