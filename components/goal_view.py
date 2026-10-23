"""Seção “Prazo da meta” de Minha evolução: três cenários, escolha e acompanhamento."""
from __future__ import annotations

from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st

from components import ui
from components.state import flash
from database.connection import session_scope
from database.models import GoalPlan, Profile
from services import ai_planner
from services import gemini_service as gs
from services import goal_service as gls
from services import profile_service as ps


def _weight_now(w, p) -> float:
    return float(w["peso"].iloc[-1]) if not w.empty else float(p.weight_kg)


def _calculate(p, w, use_ai: bool) -> None:
    weight = _weight_now(w, p)
    try:
        with ui.loading("Analisando o prazo da meta…" if use_ai else "Calculando os prazos…"), session_scope() as s:
            prof = s.get(Profile, p.id)
            base = gls.compute(prof, weight)
            if use_ai:
                ai_planner.ai_goal_review(s, prof, weight, base, gls.weight_trend(w))
            else:
                gls.save(s, prof, weight, base)
        flash("Prazos da meta salvos. O cenário escolhido passa a valer para os próximos cardápios.")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
    except gs.GeminiInvalidOutput as exc:
        st.error(f"{exc} Problemas: {'; '.join(exc.errors[:5])}")
    except gs.GeminiUnavailable as exc:
        st.error(str(exc))


def _card(sc: gls.Scenario, chosen: bool) -> None:
    with ui.panel(f"goal-{sc.key}"):
        st.html(f'<div class="fx-rot">{ui.esc(sc.label)}'
                + (' <span class="fx-chip ok">escolhido</span>' if chosen else "") + "</div>"
                f'<div class="fx-val">{sc.date:%d/%m/%Y}</div>'
                f'<div class="fx-det">em {sc.weeks} semanas · {ui.fmt_num(sc.weekly_kg, 2)} kg/semana</div>'
                + ui.bullet_list([f"{ui.fmt_num(sc.kcal)} kcal por dia",
                                  f"Proteína {sc.protein_g} g · gordura {sc.fat_g} g · carboidratos {sc.carbs_g} g",
                                  f"{sc.meals_per_day} refeições por dia"]))
        if sc.tips:
            st.caption(sc.tips)
        for n in sc.notes:
            st.caption(n)
        st.caption(gls.CAVEATS[sc.key])


def _chart(gp: GoalPlan, scenarios: list[gls.Scenario], w) -> None:
    fig = go.Figure()
    if not w.empty:
        fig.add_scatter(x=w["data"], y=w["media7"], mode="lines", name="Média móvel 7 dias",
                        line=dict(color=ui.INK2, width=2), hovertemplate="%{y:.1f} kg<extra>registrado</extra>")
    start = gp.created_at.date()
    for i, sc in enumerate(scenarios):
        xs = [start + timedelta(weeks=k) for k in range(0, sc.weeks + 1, max(1, sc.weeks // 40))] + [sc.date]
        ys = [gls.expected_weight(gp, sc, d) for d in xs]
        fig.add_scatter(x=xs, y=ys, mode="lines", name=sc.label,
                        line=dict(color=ui.SERIES[i], width=2.5 if sc.key == gp.chosen else 1.5,
                                  dash=None if sc.key == gp.chosen else "dot"),
                        hovertemplate="%{y:.1f} kg<extra>" + sc.label + "</extra>")
    fig.add_hline(y=gp.target_weight_kg, line=dict(color=ui.MUTED, width=1, dash="dot"),
                  annotation_text=f"meta {ui.fmt_num(gp.target_weight_kg, 1)} kg", annotation_position="top left",
                  annotation_font_color=ui.MUTED)
    fig.update_yaxes(ticksuffix=" kg")
    ui.plot(ui.date_axis(ui.fig_layout(fig, "Projeção até a meta", 300,
                                       caption="Projeção dos três cenários a partir do dia do cálculo"), "%d/%m/%y"))


def goal_section(p, w) -> None:
    st.subheader("Prazo da meta")
    if not p.target_weight_kg:
        st.info("Defina a meta de peso em Meu perfil para calcular em quanto tempo dá para chegar lá.")
        st.page_link("views/perfil.py", label="Abrir Meu perfil", icon=":material/person:")
        return
    weight = _weight_now(w, p)
    with session_scope() as s:
        gp = gls.active(s, p.id)
    ai_ok = gs.is_configured()

    if gp is None:
        st.caption(f"De {ui.fmt_num(weight, 1)} kg para {ui.fmt_num(p.target_weight_kg, 1)} kg. O FitOS calcula três "
                   "cenários pelo balanço energético; a IA pode revisar e explicar qual combina mais com você.")
        c1, c2, _ = st.columns([1.2, 1.2, 3])
        if c1.button("Calcular prazos", type="primary", width="stretch"):
            _calculate(p, w, use_ai=False)
        if c2.button("Analisar com IA", icon=":material/auto_awesome:", disabled=not ai_ok, width="stretch"):
            _calculate(p, w, use_ai=True)
        return

    scenarios = gls.scenarios_of(gp)
    stale = gls.is_stale(gp, p, weight)
    if stale:
        st.warning(f"Recalcule os prazos: {stale}.")
    cols = st.columns(3)
    for col, sc in zip(cols, scenarios):
        with col:
            _card(sc, sc.key == gp.chosen)

    chosen = gls.chosen_scenario(gp)
    keys = [x.key for x in scenarios]
    pick = st.radio("Cenário que vale para os cardápios", keys, index=keys.index(gp.chosen), horizontal=True,
                    format_func=gls.LABELS.get, key=f"goal_pick{gp.id}")
    if pick != gp.chosen:
        with session_scope() as s:
            s.get(GoalPlan, gp.id).chosen = pick
        flash(f"Cenário “{gls.LABELS[pick]}” escolhido: gere um novo cardápio para aplicar as novas metas.")
        st.rerun()

    if chosen and (date.today() - gp.created_at.date()).days >= 7 and not w.empty:
        exp = gls.expected_weight(gp, chosen)
        diff = weight - exp
        losing = gp.target_weight_kg < gp.start_weight_kg
        ahead = diff < 0 if losing else diff > 0
        msg = (f"Pelo cenário {chosen.label.lower()}, hoje o esperado era {ui.fmt_num(exp, 1)} kg; a última pesagem "
               f"é {ui.fmt_num(weight, 1)} kg")
        if abs(diff) < 0.5:
            st.success(msg + ": no ritmo.")
        elif ahead:
            st.info(msg + f": {ui.fmt_num(abs(diff), 1)} kg adiantado. Ritmo acima do planejado não é meta; "
                          "confira fome, sono e cargas do treino.")
        else:
            st.warning(msg + f": {ui.fmt_num(abs(diff), 1)} kg atrás. Revise a adesão ao cardápio antes de "
                             "mudar as calorias.")

    _chart(gp, scenarios, w)
    if gp.analysis:
        with ui.panel("goal-analysis"):
            st.markdown("**Análise da IA**")
            st.markdown(gp.analysis)
            st.caption(f"Gerada em {gp.created_at:%d/%m/%Y %H:%M} ({gp.origin}). Texto automático, não substitui "
                       "avaliação profissional.")
    e = ps.estimate_energy(p, weight)
    ui.note(f"Calculado em {gp.created_at:%d/%m/%Y} com gasto diário estimado de {ui.fmt_num(gp.tdee_kcal)} kcal "
            f"(hoje: {ui.fmt_num(e.tdee)} kcal). Perda em % do peso por semana com as calorias reajustadas a cada "
            "4 semanas; ≈7.700 kcal por kg. É uma estimativa: o corpo se adapta e a balança oscila.")
    c1, c2, c3 = st.columns([1.2, 1.2, 3])
    if c1.button("Recalcular", width="stretch"):
        _calculate(p, w, use_ai=False)
    if c2.button("Analisar com IA", icon=":material/auto_awesome:", disabled=not ai_ok, width="stretch",
                 key="goal_ai_again"):
        _calculate(p, w, use_ai=True)
    c3.page_link("views/plano_alimentar.py", label="Gerar cardápio com estas metas", icon=":material/restaurant:")
