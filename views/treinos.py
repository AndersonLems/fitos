from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from components import ui
from components.exercise_view import exercise_detail, exercise_list, prescription_text
from components.state import flash, require_profile
from components.timer import rest_timer
from database.connection import session_scope
from database.models import Exercise, Profile, WorkoutPlan, WorkoutSession
from services import gemini_service as gs
from services import workout_service as ws
from services.ai_planner import ai_workout_plan
from services.profile_service import WEEKDAYS

p = require_profile()
ui.page_header("Meus treinos", "Ficha semanal, treino do dia, registro de cargas e repetições e progressão. "
               "As sugestões de carga são conservadoras e nunca são aplicadas sozinhas.")


def ex_name(e: Exercise) -> str:
    return e.name_pt or e.name_original


def generate_controls(key: str) -> None:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Gerador local** — instantâneo, sem IA. Usa dias, tempo, experiência, equipamentos e "
                    "limitações do perfil.")
        if st.button("Gerar ficha local", key=f"gl{key}", type="primary"):
            with session_scope() as s:
                prof = s.get(Profile, p.id)
                days, warns = ws.local_plan_draft(s, prof)
                plan = ws.save_plan(s, p.id, "Ficha local", days, origin="local", change_note="Gerada localmente")
            flash(f"Ficha v{plan.version} criada." + (" " + " ".join(warns) if warns else ""), "info")
            st.rerun()
    with c2:
        st.markdown("**Gemini** — considera também o histórico de cargas e um pedido livre. Uma chamada por clique.")
        req = st.text_input("Pedido (opcional)", key=f"rq{key}", placeholder="Ex.: mais foco em costas, sem barra livre")
        if st.button("Gerar com Gemini", key=f"gg{key}", disabled=not gs.is_configured()):
            try:
                with ui.loading("Gerando e validando a ficha…"), session_scope() as s:
                    plan, why = ai_workout_plan(s, s.get(Profile, p.id), req)
                flash(f"Ficha v{plan.version} criada pelo Gemini. {why}", "info")
                st.rerun()
            except gs.GeminiInvalidOutput as exc:
                st.error(f"{exc} Problemas: {'; '.join(exc.errors[:5])}")
            except gs.GeminiUnavailable as exc:
                st.error(str(exc))


with session_scope() as s:
    plan = ws.active_plan(s, p.id)

if not plan:
    st.info("Nenhuma ficha ativa. Gere a primeira:")
    generate_controls("first")
    st.stop()

tab_hoje, tab_ficha, tab_hist, tab_ver = st.tabs(["Treino de hoje", "Ficha", "Histórico e progressão", "Versões"])

# ============================================================================ HOJE
with tab_hoje:
    with session_scope() as s:
        plan = ws.active_plan(s, p.id)
        today = ws.todays_workout(s, p.id, plan)
        sess = ws.open_session(s, p.id)
        done_today = s.scalars(select(WorkoutSession).where(
            WorkoutSession.profile_id == p.id, WorkoutSession.performed_on == date.today(),
            WorkoutSession.finished_at.is_not(None))).all()
    day_ids = [d.id for d in plan.days]
    titles = {d.id: d.title for d in plan.days}

    head = ui.day_title(today.day.title) if today.day else "Descanso"
    st.html(f'<div class="fx-day">{ui.esc(head)}</div>' +
            (ui.chip("trocado para hoje", "warn") if today.overridden else ui.chip(f"ficha v{plan.version}")))

    with st.expander("Mudar o treino de hoje"):
        opts = [*day_ids, None]
        cur = today.day.id if today.day else None
        choice = st.selectbox("Fazer hoje", opts, index=opts.index(cur) if cur in opts else len(opts) - 1,
                              format_func=lambda i: titles.get(i, "Descanso"), key=f"hoje{plan.id}")
        c1, c2 = st.columns(2)
        if c1.button("Aplicar só para hoje"):
            with session_scope() as s:
                ws.set_override(s, p.id, date.today(), choice)
            st.rerun()
        if today.overridden and c2.button("Voltar ao previsto"):
            with session_scope() as s:
                ws.clear_override(s, p.id, date.today())
            st.rerun()
        ui.note("Para mudar de forma permanente qual treino cai em cada dia, use “Trocar dias da semana” na aba Ficha.")

    if done_today and not sess:
        st.success(f"Treino de hoje concluído ({len(done_today)} sessão registrada).")

    if today.day and not sess:
        exercise_list(today.day.exercises, "treino", profile_id=p.id)
        if st.button("Iniciar outra sessão" if done_today else "Iniciar treino", type="primary"):
            with session_scope() as s:
                pl = ws.active_plan(s, p.id)
                ws.start_session(s, p.id, pl, next(d for d in pl.days if d.id == today.day.id))
            st.rerun()

    if sess:
        rest_timer(90, "hoje")
        with session_scope() as s:
            sets = ws.session_sets(s, sess.id)
            pl = ws.load_plan(s, sess.plan_id) if sess.plan_id else None
            planned = {pe.id: pe for d in (pl.days if pl else []) for pe in d.exercises}
            exs = {e.id: e for e in s.scalars(select(Exercise).where(Exercise.id.in_({x.exercise_id for x in sets})))}
            prev = {eid: ws.last_sets(s, p.id, eid) for eid in exs}
        groups: dict[int, list] = {}
        for x in sets:
            groups.setdefault(x.planned_exercise_id or -x.exercise_id, []).append(x)
        edited = {}
        with st.form("series"):
            for gid, rows in groups.items():
                pe = planned.get(gid)
                ex = exs[rows[0].exercise_id]
                last = prev.get(ex.id) or []
                last_txt = ", ".join(f"{(r.load_kg or 0):g}×{r.reps}" for r in last if r.reps) or "sem registro anterior"
                c1, c2 = st.columns([1, 5])
                with c1:
                    st.html(ui.media_html(ex.gif_url, ex_name(ex)))
                    with st.popover("Execução", icon=":material/play_circle:", width="stretch"):
                        exercise_detail(ex, pe)
                with c2:
                    presc = prescription_text(pe) if pe else "avulso"
                    st.markdown(f"**{ex_name(ex)}** — {presc}  \nÚltima vez: {last_txt}")
                    df = pd.DataFrame([{"id": r.id, "série": r.set_number, "carga (kg)": r.load_kg, "reps": r.reps,
                                        "feita": r.completed, "dificuldade": r.difficulty} for r in rows])
                    # tipos explícitos: colunas vazias viram célula em branco, não o texto "None"
                    df = df.astype({"carga (kg)": "float64", "reps": "Int64", "dificuldade": "string"})
                    edited[gid] = st.data_editor(
                        df, key=f"ed{gid}", hide_index=True, width="stretch", disabled=["id", "série"],
                        column_config={"id": None,
                                       "carga (kg)": st.column_config.NumberColumn(min_value=0, max_value=600, step=0.5),
                                       "reps": st.column_config.NumberColumn(min_value=0, max_value=100, step=1),
                                       "dificuldade": st.column_config.SelectboxColumn(
                                           options=["facil", "ok", "dificil", "falha"])})
            save = st.form_submit_button("Salvar séries", type="primary")
        if save:
            try:
                with session_scope() as s:
                    for df in edited.values():
                        for r in df.to_dict("records"):
                            ws.save_set(s, int(r["id"]), p.id,
                                        load_kg=None if pd.isna(r["carga (kg)"]) else float(r["carga (kg)"]),
                                        reps=None if pd.isna(r["reps"]) else int(r["reps"]),
                                        completed=bool(r["feita"]),
                                        difficulty=None if pd.isna(r["dificuldade"]) else r["dificuldade"] or None)
                flash("Séries salvas.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        with st.form("finalizar"):
            st.markdown("**Finalizar treino**")
            c1, c2 = st.columns(2)
            fatigue = c1.slider("Esforço percebido da sessão (1 = muito leve, 10 = máximo)", 1, 10, 7)
            recovery = c2.selectbox("Como estava a recuperação?", ["boa", "regular", "ruim"])
            pain = st.checkbox("Senti dor (não confundir com cansaço muscular)")
            pain_notes = st.text_input("Onde e quando doeu?")
            notes = st.text_input("Observações")
            fin = st.form_submit_button("Finalizar e salvar")
        if fin:
            with session_scope() as s:
                ws.finish_session(s, sess.id, p.id, fatigue=fatigue, pain=pain, pain_notes=pain_notes or None,
                                  recovery=recovery, notes=notes or None)
            flash("Treino finalizado." + (" Com dor registrada, as sugestões não vão aumentar carga." if pain else ""))
            st.rerun()
        if st.button("Descartar sessão em andamento"):
            with session_scope() as s:
                s.delete(s.get(WorkoutSession, sess.id))
            st.rerun()

# ============================================================================ FICHA
with tab_ficha:
    with session_scope() as s:
        plan = ws.active_plan(s, p.id)
        core = ws.core_exercises(s)
        last_sess = {}
        for d in plan.days:
            for pe in d.exercises:
                ls = ws.last_sets(s, p.id, pe.exercise_id)
                sess_obj = s.get(WorkoutSession, ls[0].session_id) if ls else None
                last_sess[pe.id] = ws.suggest_progression(pe, ls, sess_obj)
    st.caption(f"{plan.name} · versão {plan.version} · origem {plan.origin} · criada em {plan.created_at:%d/%m/%Y}")
    if plan.rationale:
        ui.note(ui.esc(plan.rationale))

    for d in plan.days:
        st.html(f'<div class="fx-day">{ui.esc(ui.day_title(d.title))}</div>')
        extra = {}
        for pe in d.exercises:
            sug = last_sess[pe.id]
            kind = {"aumentar": "ok", "reduzir": "bad", "manter": ""}.get(sug.action, "")
            if sug.action != "sem_dados":
                extra[pe.id] = f'<div class="fx-ex-d">{ui.chip(sug.text, kind)}</div>'
        if d.exercises:
            exercise_list(d.exercises, f"ficha-{d.id}", extra=extra, profile_id=p.id)
        else:
            ui.note("Dia sem exercícios.")

        with st.expander(f"Editar {d.title.split(' — ')[0].title()}"):
            names = {ex_name(e): e.id for e in core}
            for pe in d.exercises:
                names.setdefault(ex_name(pe.exercise), pe.exercise_id)
            df = pd.DataFrame([{"exercício": ex_name(pe.exercise), "séries": pe.sets, "reps mín": pe.reps_min,
                                "reps máx": pe.reps_max, "descanso (s)": pe.rest_seconds, "observação": pe.notes or ""}
                               for pe in d.exercises])
            new_df = st.data_editor(df, key=f"edit{d.id}", num_rows="dynamic", hide_index=True,
                                    width="stretch", column_config={
                                        "exercício": st.column_config.SelectboxColumn(options=sorted(names), required=True),
                                        "séries": st.column_config.NumberColumn(min_value=1, max_value=8, step=1),
                                        "reps mín": st.column_config.NumberColumn(min_value=1, max_value=50, step=1),
                                        "reps máx": st.column_config.NumberColumn(min_value=1, max_value=50, step=1),
                                        "descanso (s)": st.column_config.NumberColumn(min_value=0, max_value=600, step=15)})
            title = st.text_input("Título do dia", d.title, key=f"tt{d.id}")
            if st.button("Salvar como nova versão", key=f"sv{d.id}"):
                try:
                    with session_scope() as s:
                        pl = ws.active_plan(s, p.id)
                        drafts = ws.draft_from_plan(pl)
                        idx = [x.id for x in pl.days].index(d.id)
                        exmap = {e.id: e for e in s.scalars(select(Exercise).where(Exercise.id.in_(names.values())))}
                        items = []
                        for r in new_df.dropna(subset=["exercício"]).to_dict("records"):
                            items.append(ws.DraftExercise(exmap[names[r["exercício"]]], int(r["séries"] or 3),
                                                          int(r["reps mín"] or 8), int(r["reps máx"] or 12),
                                                          int(r["descanso (s)"] or 90), r["observação"] or None))
                        drafts[idx].exercises, drafts[idx].title = items, title.strip() or d.title
                        newp = ws.new_version(s, pl, drafts, f"Edição de {drafts[idx].title}")
                    flash(f"Versão {newp.version} salva.")
                    st.rerun()
                except (ValueError, KeyError) as exc:
                    st.error(f"Não foi possível salvar: {exc}")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Substituir exercício**")
        all_pe = {pe.id: f"{d.title.split(' — ')[0]} · {ex_name(pe.exercise)}" for d in plan.days for pe in d.exercises}
        if all_pe:
            pe_id = st.selectbox("Exercício da ficha", list(all_pe), format_func=all_pe.get, key=f"pe{plan.id}")
            pe_obj = next(pe for d in plan.days for pe in d.exercises if pe.id == pe_id)
            with session_scope() as s:
                alts = ws.similar_exercises(s, pe_obj.exercise)
            if alts:
                alt = st.selectbox("Substituir por", [a.id for a in alts], key=f"alt{pe_id}",
                                   format_func=lambda i: next(ex_name(a) + (f" ({a.equipment})" if a.equipment else "")
                                                              for a in alts if a.id == i))
                if st.button("Substituir (nova versão)"):
                    with session_scope() as s:
                        newp = ws.replace_exercise(s, ws.active_plan(s, p.id), pe_id, alt)
                    flash(f"Exercício substituído. Ficha v{newp.version}.")
                    st.rerun()
    with c2:
        st.markdown("**Ajustar volume e intensidade**")
        st.caption("Altera o número de séries de todos os exercícios. Para intensidade, edite as faixas de "
                   "repetições do dia.")
        b1, b2 = st.columns(2)
        if b1.button("−1 série em tudo"):
            with session_scope() as s:
                ws.adjust_volume(s, ws.active_plan(s, p.id), -1)
            st.rerun()
        if b2.button("+1 série em tudo"):
            with session_scope() as s:
                ws.adjust_volume(s, ws.active_plan(s, p.id), +1)
            st.rerun()
        st.markdown("**Trocar dias da semana**")
        if len(plan.days) >= 2:
            dmap = {d.id: d.title for d in plan.days}
            a = st.selectbox("Treino", list(dmap), format_func=dmap.get, key=f"swa{plan.id}")
            b = st.selectbox("troca de dia com", [i for i in dmap if i != a], format_func=dmap.get, key=f"swb{plan.id}{a}")
            if st.button("Trocar dias (nova versão)"):
                with session_scope() as s:
                    ws.swap_weekdays(s, ws.active_plan(s, p.id), a, b)
                st.rerun()

    with st.expander("Gerar uma nova ficha"):
        st.caption("A ficha atual continua no histórico de versões e pode ser reativada.")
        generate_controls("new")

# ============================================================================ HISTÓRICO
with tab_hist:
    with session_scope() as s:
        hist = ws.history_dataframe(s, p.id)
        sessions = s.execute(select(WorkoutSession.performed_on, WorkoutSession.fatigue, WorkoutSession.pain,
                                    WorkoutSession.recovery, WorkoutSession.notes, WorkoutSession.day_id)
                             .where(WorkoutSession.profile_id == p.id, WorkoutSession.finished_at.is_not(None))
                             .order_by(WorkoutSession.performed_on.desc())).all()
    if hist.empty:
        st.info("Nenhuma série registrada ainda.")
    else:
        done = hist[hist["concluida"]]
        exercises = sorted(done["exercicio"].unique())
        sel = st.selectbox("Exercício", exercises)
        g = done[done["exercicio"] == sel].groupby("data").agg(carga=("carga", "max"), e1rm=("e1rm", "max"),
                                                               volume=("volume", "sum")).reset_index()
        c1, c2 = st.columns(2)
        with c1:
            fig = go.Figure()
            fig.add_scatter(x=g["data"], y=g["carga"], name="Carga máxima", mode="lines+markers",
                            line=dict(width=2, color=ui.SERIES[0]), marker=dict(size=8))
            fig.add_scatter(x=g["data"], y=g["e1rm"], name="1RM estimado (Epley)", mode="lines+markers",
                            line=dict(width=2, color=ui.SERIES[1], dash="dot"), marker=dict(size=8))
            fig.update_yaxes(ticksuffix=" kg")
            ui.plot(ui.date_axis(ui.fig_layout(fig, f"Progressão de carga — {sel}")))
        with c2:
            fig = go.Figure()
            fig.add_bar(x=g["data"], y=g["volume"], name="Volume", marker=dict(color=ui.SERIES[0], line=dict(width=0)),
                        hovertemplate="%{y:.0f} kg·rep<extra></extra>")
            ui.plot(ui.date_axis(ui.fig_layout(fig, "Volume por sessão (carga × repetições)")))
        ui.note("1RM estimado pela fórmula de Epley: indicador de tendência, não um teste de carga máxima.")
    if sessions:
        st.markdown("**Sessões concluídas**")
        st.dataframe(pd.DataFrame([{"data": ui.fmt_date(r[0]), "esforço": r[1], "dor": "sim" if r[2] else "não",
                                    "recuperação": r[3] or "—", "observações": r[4] or "—"} for r in sessions]),
                     hide_index=True, width="stretch")

# ============================================================================ VERSÕES
with tab_ver:
    with session_scope() as s:
        versions = ws.plan_versions(s, p.id)
    for v in versions:
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**v{v.version}** · {v.name} · {v.origin} · {v.created_at:%d/%m/%Y %H:%M}"
                    + (" · **ativa**" if v.is_active else "") + (f"  \n{v.change_note}" if v.change_note else ""))
        if not v.is_active and c2.button("Reativar", key=f"re{v.id}"):
            with session_scope() as s:
                for o in s.scalars(select(WorkoutPlan).where(WorkoutPlan.profile_id == p.id)):
                    o.is_active = o.id == v.id
            st.rerun()
