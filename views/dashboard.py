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
ui.page_header(f"Bom dia, {p.name.split()[0]}.", f"{p.name} · {ps.WEEKDAYS[date.today().weekday()].lower()}, {date.today():%d/%m/%Y}",
               kicker="")

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

# The React hero uses actual session/meal records here, never preview phases.
from datetime import timedelta
from sqlalchemy import select
from database.models import Meal, WorkoutSession
from services import workout_service as ws, nutrition_service as ns

with session_scope() as s:
    plan = ws.active_plan(s, p.id)
    today = ws.todays_workout(s, p.id, plan) if plan else None
    active = ws.open_session(s, p.id)
    finished = list(s.scalars(select(WorkoutSession).where(
        WorkoutSession.profile_id == p.id, WorkoutSession.finished_at.is_not(None),
        WorkoutSession.performed_on >= date.today() - timedelta(days=7))))
    last_finished = max((x for x in finished if x.performed_on == date.today()), key=lambda x: x.id, default=None)
    displayed_session = active or last_finished
    logs = ws.session_sets(s, displayed_session.id) if displayed_session else []
    meal_plan = ns.active_plan(s, p.id)
    meal_summary = ns.summarize(s, meal_plan) if meal_plan else None
    _, eaten = ns.consumed(s, p.id)
    # A running session can refer to an older plan or a different day.
    running_plan = ws.load_plan(s, displayed_session.plan_id) if displayed_session and displayed_session.plan_id else None
    day = next((d for d in running_plan.days if d.id == displayed_session.day_id), None) if running_plan else today.day if today else None

left, right = st.columns([2.2, 1], gap="medium")
with left:
    with st.container(key="workout-hero"):
        done_today = any(x.performed_on == date.today() for x in finished)
        status = "Sem ficha" if not plan else "Em andamento" if active else "Concluído" if done_today else "Ainda não iniciado" if day else "Descanso"
        st.html('<div class="fx-eyebrow">Treino de hoje</div>' + ui.chip(status, 'warn' if active else 'ok' if done_today else ''))
        st.html(f'<h2 style="font-size:32px;padding:0">{ui.esc(day.title.split(" — ")[-1].capitalize()) if day else "Hoje é dia de recuperação." if plan else "Seu próximo passo começa aqui."}</h2>')
        if day:
            completed = {}
            for row in logs:
                if row.completed:
                    completed[row.planned_exercise_id] = completed.get(row.planned_exercise_id, 0) + 1
            total_sets = sum(x.sets for x in day.exercises)
            st.html(f'<div class="fx-statline"><p><small>Exercícios</small>{len(day.exercises)}</p>'
                    f'<p><small>Séries</small>{sum(completed.values())}/{total_sets}</p>'
                    f'<p><small>Tempo disponível</small>{p.session_minutes or "—"} min</p></div>')
            if active:
                st.html(ui.progress_html(sum(completed.values()), total_sets))
                if st.button("Continuar treino", type="primary", icon=":material/play_arrow:"):
                    st.switch_page("views/treinos.py")
            elif not done_today:
                if st.button("Começar treino", type="primary", icon=":material/play_arrow:"):
                    with session_scope() as s:
                        pl = ws.active_plan(s, p.id)
                        current = ws.todays_workout(s, p.id, pl)
                        if current.day:
                            ws.start_session(s, p.id, pl, current.day)
                    st.switch_page("views/treinos.py")
            st.page_link("views/treinos.py", label="Ver resumo" if done_today else "Ver ficha completa", icon=":material/arrow_forward:")
            ui.exercise_rows(day.exercises, completed)
        else:
            st.caption("Mantenha a alimentação e a hidratação em dia." if plan else "Crie sua ficha de treino a partir do seu perfil.")
            st.page_link("views/treinos.py", label="Ver ficha" if plan else "Criar ficha de treino", icon=":material/fitness_center:")
with right:
    with st.container(key="nutrition-panel"):
        st.markdown("**Alimentação de hoje**")
        st.html(f'<div class="fx-val">{ui.fmt_num(cons.kcal)} <span style="font-size:14px;color:var(--muted)">/ {ui.fmt_num(e.target_kcal)} kcal</span></div>'
                + ui.progress_html(cons.kcal, e.target_kcal, ui.INK))
        for label, value, goal, color in [("Proteína",cons.protein,e.protein_g,ui.ACCENT),
                                         ("Carboidratos",cons.carbs,e.carbs_g,ui.SERIES[1]),
                                         ("Gorduras",cons.fat,e.fat_g,ui.SERIES[2])]:
            st.html(f'<div class="fx-macro"><span>{label}</span>{ui.progress_html(value, goal, color)}<span>{value:.0f}/{goal:.0f} g</span></div>')
        st.html('<div class="fx-eyebrow" style="margin-top:20px">Refeições</div>')
        day_index = (date.today() - meal_plan.start_date).days if meal_plan else -1
        meals = meal_summary.days.get(day_index, []) if meal_summary else []
        for ms in meals:
            meal = ms.meal
            was_eaten = meal.id in eaten
            with st.container(key=f"meal-row-{meal.id}"):
                marked = st.checkbox(f"{meal.meal_type} · {ms.macros.kcal:.0f} kcal", value=was_eaten,
                                     key=f"dashboard_meal_{meal.id}")
                st.caption(meal.title or ", ".join(i.food.short_name or i.food.name for i in meal.items))
            if marked != was_eaten:
                with session_scope() as s:
                    if marked:
                        ns.log_meal(s, p.id, s.get(Meal, meal.id))
                    else:
                        ns.unlog_meal(s, p.id, meal.id)
                st.rerun()
        if not meals:
            st.caption("Nenhuma refeição planejada para esta data.")
        st.page_link("views/plano_alimentar.py", label="Ver cardápio", icon=":material/restaurant:")

lower1, lower2, lower3 = st.columns([1.4, 1, 1])
with lower1:
    ui.tiles([{"label":"Peso corporal", "value":f"{ui.fmt_num(f.weight,1)} kg", "detail":delta_txt,
               "foot":f"Meta {ui.fmt_num(target,1)} kg" if target else "Meta não definida"}])
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
        ui.plot(ui.date_axis(ui.fig_layout(fig, "Evolução do peso", height=220)))
    else:
        st.info("Sem pesagens registradas.")
with lower2:
    with st.container(border=True):
        st.markdown("**Consistência semanal**")
        st.caption(f"{f.sessions_week} de {f.planned_week or '—'} treinos")
        ui.week_strip(plan, {x.performed_on for x in finished})
with lower3:
    ui.card("Orçamento alimentar", f'<div class="fx-val">{fmt_brl(p.monthly_food_budget - f.month_spent) if p.monthly_food_budget else "—"}</div>'
            + '<p class="fx-note">restantes no mês</p>'
            + ui.progress_html(float(f.month_spent), float(p.monthly_food_budget or 0), ui.INK2)
            + f'<p>{fmt_brl(f.month_spent)} gastos · de {fmt_brl(p.monthly_food_budget) if p.monthly_food_budget else "orçamento não definido"}</p>')

with st.expander("Indicadores e estimativas"):
    ui.tiles([
        {"label":"IMC", "value":ui.fmt_num(bmi,1), "detail":ps.bmi_label(bmi)},
        {"label":"Calorias estimadas/dia", "value":f"{ui.fmt_num(e.target_kcal)} kcal", "provisional":e.is_provisional},
        {"label":"Cardápio · custo por dia", "value":fmt_brl(f.plan_cost_daily) if f.plan_cost_daily is not None else "—",
         "detail":f"{f.plan_unpriced} itens sem preço" if f.plan_unpriced else ""},
    ])
    ui.note(ps.BMI_CAVEAT + " Calorias: Mifflin-St Jeor × fator de atividade, ajustadas ao objetivo.")
    if e.is_provisional:
        ui.note("Estimativa provisória — faltam: " + ", ".join(e.provisional))

with st.expander("Macronutrientes em detalhe"):
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
                with ui.loading("Consultando o Gemini…"), session_scope() as s:
                    ai_dashboard_recommendations(s, s.get(type(p), p.id), f.as_dict())
                st.rerun()
            except gs.GeminiUnavailable as exc:
                st.error(str(exc))
