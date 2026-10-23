from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components import ui
from components.state import require_profile
from database.connection import session_scope
from services import gemini_service as gs
from services import insights
from services import profile_service as ps
from services.ai_planner import ai_dashboard_recommendations
from utils.units import fmt_brl

p = require_profile()
with session_scope() as s:
    f = insights.collect(s, p)
    weekly = insights.weekly_sessions(s, p.id)
    last_ai = gs.last_insight(s, p.id, "dashboard")

e = f.energy
ui.page_header("Painel", f"{p.name} · {ps.WEEKDAYS[date.today().weekday()].lower()}, {date.today():%d/%m/%Y}",
               kicker="Resumo da semana")

w = f.weights
delta_txt = ""
if len(w) >= 2:
    ref = w[w["data"] <= w["data"].max() - pd.Timedelta(days=28)]
    base = float(ref["peso"].iloc[-1]) if not ref.empty else float(w["peso"].iloc[0])
    d = f.weight - base
    delta_txt = f"<b>{d:+.1f} kg</b> desde {('há 4 semanas' if not ref.empty else 'o primeiro registro')}".replace(".", ",")
bmi = ps.bmi(f.weight, p.height_cm)
target = p.target_weight_kg
cons = f.consumed

ui.tiles([
    {"label": "Peso atual", "value": f"{ui.fmt_num(f.weight, 1)} kg", "detail": delta_txt or "registre mais pesagens",
     "accent": True},
    {"label": "Meta de peso", "value": f"{ui.fmt_num(target, 1)} kg" if target else "não definida",
     "detail": f"faltam <b>{ui.fmt_num(abs(f.weight - target), 1)} kg</b>" if target else "defina em Meu Perfil"},
    {"label": "IMC", "value": ui.fmt_num(bmi, 1), "detail": ps.bmi_label(bmi)},
    {"label": "Calorias estimadas/dia", "value": f"{ui.fmt_num(e.target_kcal)} kcal",
     "detail": f"P {e.protein_g} g · C {e.carbs_g} g · G {e.fat_g} g", "provisional": e.is_provisional},
    {"label": "Consumido hoje", "value": f"{ui.fmt_num(cons.kcal)} kcal",
     "detail": f"P {cons.protein:.0f} g · C {cons.carbs:.0f} g · G {cons.fat:.0f} g"},
    {"label": "Treinos na semana", "value": f"{f.sessions_week} de {f.planned_week or '—'}",
     "detail": "hoje: " + ui.esc(f.today_title.split(" — ")[-1].title() if f.today_title else "descanso / sem ficha")},
    {"label": "Cardápio · custo por dia", "value": fmt_brl(f.plan_cost_daily) if f.plan_cost_daily is not None else "—",
     "detail": (f"{f.plan_unpriced} itens sem preço" if f.plan_unpriced else "todos os itens com preço")
     if f.plan_cost_daily is not None else "sem cardápio ativo"},
    {"label": "Gasto com alimentação no mês", "value": fmt_brl(f.month_spent),
     "detail": f"orçamento {fmt_brl(p.monthly_food_budget)}" if p.monthly_food_budget else "sem orçamento definido"},
])
if e.is_provisional:
    ui.note("Estimativa provisória — faltam: " + ", ".join(e.provisional) + ". " + ps.BMI_CAVEAT)
else:
    ui.note(ps.BMI_CAVEAT + " Calorias: Mifflin-St Jeor × fator de atividade, ajustadas ao objetivo.")

c1, c2 = st.columns([3, 2])
with c1:
    if len(w) >= 1:
        fig = go.Figure()
        fig.add_scatter(x=w["data"], y=w["peso"], mode="markers", name="Pesagens",
                        marker=dict(size=8, color=ui.SERIES[1], line=dict(width=2, color=ui.SURFACE)),
                        hovertemplate="%{y:.1f} kg<extra>pesagem</extra>")
        fig.add_scatter(x=w["data"], y=w["media7"], mode="lines", name="Média móvel 7 dias",
                        line=dict(width=2, color=ui.SERIES[0]), hovertemplate="%{y:.1f} kg<extra>média 7d</extra>")
        if target:
            fig.add_hline(y=target, line=dict(color=ui.MUTED, width=1, dash="dot"),
                          annotation_text=f"meta {ui.fmt_num(target, 1)} kg", annotation_font_color=ui.MUTED)
        fig.update_yaxes(ticksuffix=" kg")
        ui.plot(ui.date_axis(ui.fig_layout(fig, "Evolução do peso")))
    else:
        st.info("Sem pesagens registradas.")
with c2:
    fig = go.Figure()
    labels = ["Proteínas", "Carboidratos", "Gorduras"]
    fig.add_bar(y=labels, x=[e.protein_g, e.carbs_g, e.fat_g], orientation="h", name="Meta",
                marker=dict(color=ui.GRID, line=dict(width=0)), hovertemplate="%{x:.0f} g<extra>meta</extra>")
    fig.add_bar(y=labels, x=[cons.protein, cons.carbs, cons.fat], orientation="h", name="Consumido hoje",
                marker=dict(color=ui.SERIES[0], line=dict(width=0)), hovertemplate="%{x:.0f} g<extra>consumido</extra>")
    fig.update_layout(barmode="overlay", bargap=0.45, hovermode="y unified")
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(ticksuffix=" g", showgrid=True, gridcolor=ui.GRID)
    ui.plot(ui.fig_layout(fig, "Macronutrientes de hoje"))
    ui.note("Consumo vem das refeições marcadas como feitas em Meu Plano Alimentar.")

c3, c4 = st.columns([2, 3])
with c3:
    fig = go.Figure()
    fig.add_bar(x=weekly["semana"], y=weekly["treinos"], name="Treinos",
                marker=dict(color=ui.SERIES[0], line=dict(width=0)), hovertemplate="%{y} treino(s)<extra></extra>")
    if f.planned_week:
        fig.add_hline(y=f.planned_week, line=dict(color=ui.MUTED, width=1, dash="dot"),
                      annotation_text="previstos", annotation_font_color=ui.MUTED)
    ui.date_axis(fig)
    fig.update_yaxes(dtick=1)
    ui.plot(ui.fig_layout(fig, "Treinos concluídos por semana", height=280))
with c4:
    recs = insights.rule_recommendations(f)
    ui.card("Recomendações", ui.bullet_list(recs) +
            '<p class="fx-note">Regras fixas do FitOS sobre os seus registros — sem uso de IA.</p>')
    with st.container(border=True):
        st.markdown("**Leitura do Gemini**")
        if last_ai:
            st.markdown(last_ai.content)
            st.caption(f"Gerada em {last_ai.created_at:%d/%m/%Y %H:%M} · {last_ai.model}. Texto automático; "
                       "confira com os números acima.")
        else:
            st.caption("Nenhuma leitura gerada ainda. Cada clique faz uma chamada ao Gemini.")
        if st.button("Gerar nova leitura com Gemini", disabled=not gs.is_configured()):
            try:
                with st.spinner("Consultando o Gemini…"), session_scope() as s:
                    ai_dashboard_recommendations(s, s.get(type(p), p.id), f.as_dict())
                st.rerun()
            except gs.GeminiUnavailable as exc:
                st.error(str(exc))
