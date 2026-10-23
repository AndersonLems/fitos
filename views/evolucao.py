import uuid
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from components import ui
from components.state import flash, require_profile
from config.settings import PHOTO_DIR
from database.connection import session_scope
from database.models import Measurement, Profile
from services import gemini_service as gs
from services import insights
from services import workout_service as ws
from services.ai_planner import ai_trend_analysis

p = require_profile()
ui.page_header("Minha evolução", "Peso, medidas, frequência de treino e cargas ao longo do tempo. A média móvel "
               "suaviza a variação diária de água e conteúdo intestinal.")

def _avg_table(series: pd.Series, label: str, fmt: str) -> pd.DataFrame:
    diff = series.diff()
    return pd.DataFrame({label: series.index.strftime(fmt), "média (kg)": [ui.fmt_num(v, 1) for v in series],
                         "variação": ["—" if pd.isna(v) else f"{v:+.1f}".replace(".", ",") for v in diff]}).iloc[::-1]


FIELDS = [("weight_kg", "Peso (kg)"), ("abdomen_cm", "Abdômen (cm)"), ("waist_cm", "Cintura (cm)"),
          ("arm_cm", "Braço (cm)"), ("chest_cm", "Peito (cm)"), ("hip_cm", "Quadril (cm)"), ("thigh_cm", "Coxa (cm)")]

with st.expander("Registrar medidas", expanded=False):
    with st.form("medidas", clear_on_submit=True):
        d = st.date_input("Data", date.today(), format="DD/MM/YYYY", max_value=date.today())
        cols = st.columns(4)
        vals = {}
        for i, (k, label) in enumerate(FIELDS):
            lo, hi = (30.0, 300.0) if k == "weight_kg" else (10.0, 250.0)
            vals[k] = cols[i % 4].number_input(label, lo, hi, None, 0.1, format="%.1f")
        photo = st.file_uploader("Foto (opcional)", type=["jpg", "jpeg", "png", "webp"])
        notes = st.text_area("Observações pessoais")
        ok = st.form_submit_button("Salvar registro", type="primary")
    if ok:
        if all(v is None for v in vals.values()) and not photo and not notes:
            st.error("Informe ao menos uma medida, foto ou observação.")
        else:
            path = None
            if photo:
                ext = photo.name.rsplit(".", 1)[-1].lower()
                path = PHOTO_DIR / f"p{p.id}-{d:%Y%m%d}-{uuid.uuid4().hex[:6]}.{ext}"
                path.write_bytes(photo.getvalue())
            with session_scope() as s:
                s.add(Measurement(profile_id=p.id, measured_on=d, photo_path=str(path) if path else None,
                                  notes=notes or None, **vals))
                if vals["weight_kg"] and d >= date.today():
                    s.get(Profile, p.id).weight_kg = vals["weight_kg"]
            flash("Registro salvo.")
            st.rerun()

with session_scope() as s:
    w = insights.weights_df(s, p.id)
    ms = list(s.scalars(select(Measurement).where(Measurement.profile_id == p.id).order_by(Measurement.measured_on)))
    weekly = insights.weekly_sessions(s, p.id, 12)
    hist = ws.history_dataframe(s, p.id)
    last_ai = gs.last_insight(s, p.id, "evolucao")

if w.empty:
    st.info("Sem pesagens ainda.")
else:
    fig = go.Figure()
    fig.add_scatter(x=w["data"], y=w["peso"], mode="markers", name="Pesagens", marker=dict(color=ui.SERIES[1]),
                    hovertemplate="%{y:.1f} kg<extra>pesagem</extra>")
    fig.add_scatter(x=w["data"], y=w["media7"], mode="lines", name="Média móvel 7 dias", line=dict(color=ui.SERIES[0]),
                    hovertemplate="%{y:.1f} kg<extra>média 7d</extra>")
    if p.target_weight_kg:
        fig.add_hline(y=p.target_weight_kg, line=dict(color=ui.MUTED, width=1, dash="dot"), annotation_text="meta",
                      annotation_position="top left", annotation_font_color=ui.MUTED)
    fig.update_yaxes(ticksuffix=" kg")
    ui.plot(ui.date_axis(ui.fig_layout(fig, "Peso", 340)))

    ws_ = w.set_index("data")["peso"]
    wk = ws_.resample("W-MON", label="left", closed="left").mean().dropna()
    mo = ws_.resample("MS").mean().dropna()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Média semanal**")
        st.dataframe(_avg_table(wk, "semana de", "%d/%m/%Y"), hide_index=True, width="stretch", height=min(318, 35 * len(wk) + 38))
    with c2:
        st.markdown("**Média mensal**")
        st.dataframe(_avg_table(mo, "mês", "%m/%Y"), hide_index=True, width="stretch")

mdf = pd.DataFrame([{"data": m.measured_on, **{label: getattr(m, k) for k, label in FIELDS[1:]}} for m in ms])
present = [label for _, label in FIELDS[1:] if not mdf.empty and mdf[label].notna().any()]
if present:
    st.markdown("**Medidas**")
    sel = st.multiselect("Mostrar", present, present[:3], max_selections=len(ui.SERIES))
    # Medidas de escalas diferentes (cintura × braço) ficam comparáveis pela variação desde a primeira.
    fig = go.Figure()
    for label in sel:
        g = mdf[["data", label]].dropna()
        color = ui.SERIES[present.index(label) % len(ui.SERIES)]
        fig.add_scatter(x=g["data"], y=g[label] - g[label].iloc[0], name=label.replace(" (cm)", ""),
                        mode="lines+markers", line=dict(color=color), marker=dict(color=color),
                        customdata=g[label], hovertemplate="%{customdata:.1f} cm (%{y:+.1f})<extra>" + label + "</extra>")
    fig.add_hline(y=0, line=dict(color=ui.AXIS, width=1))
    fig.update_yaxes(ticksuffix=" cm", tickformat="+.1f")
    ui.plot(ui.date_axis(ui.fig_layout(fig, "Medidas corporais", 300, caption="Variação em relação à primeira medição")))
    rows = []
    for label in present:
        g = mdf[["data", label]].dropna()
        rows.append({"medida": label, "primeira": ui.fmt_num(g[label].iloc[0], 1),
                     "última": ui.fmt_num(g[label].iloc[-1], 1),
                     "mudança": f"{g[label].iloc[-1] - g[label].iloc[0]:+.1f}".replace(".", ","),
                     "período": f"{ui.fmt_date(g['data'].iloc[0])} → {ui.fmt_date(g['data'].iloc[-1])}"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

c1, c2 = st.columns(2)
with c1:
    fig = go.Figure()
    fig.add_bar(x=weekly["semana"], y=weekly["treinos"], name="Treinos", marker=dict(color=ui.SERIES[0]),
                hovertemplate="%{y} treino(s)<extra>semana de %{x|%d/%m}</extra>")
    ui.date_axis(fig)
    fig.update_yaxes(dtick=1, rangemode="tozero")
    ui.plot(ui.fig_layout(fig, "Frequência de treinos (12 semanas)", 280))
with c2:
    if hist.empty:
        st.info("Sem cargas registradas.")
    else:
        done = hist[hist["concluida"] & hist["carga"].notna()]
        top = done.groupby("exercicio")["sessao"].nunique().sort_values(ascending=False).head(4).index.tolist()
        fig = go.Figure()
        for i, ex in enumerate(top):
            g = done[done["exercicio"] == ex].groupby("data")["carga"].max().reset_index()
            fig.add_scatter(x=g["data"], y=g["carga"], name=ex, mode="lines+markers",
                            line=dict(color=ui.SERIES[i]), marker=dict(color=ui.SERIES[i]))
        fig.update_yaxes(ticksuffix=" kg")
        fig.update_layout(legend=dict(entrywidth=0.5, entrywidthmode="fraction"))
        ui.plot(ui.date_axis(ui.fig_layout(fig, "Carga máxima", 280, caption="Os 4 exercícios mais registrados")))

photos = [m for m in ms if m.photo_path]
if photos:
    st.markdown("**Fotos**")
    ui.note("Fotos servem como registro pessoal. Iluminação, postura e ângulo mudam muito a aparência; não são "
            "medida confiável de composição corporal nem são analisadas pelo FitOS ou pelo Gemini.")
    cols = st.columns(4)
    for i, m in enumerate(reversed(photos[-8:])):
        try:
            cols[i % 4].image(m.photo_path, caption=ui.fmt_date(m.measured_on), width="stretch")
        except Exception:  # noqa: BLE001
            cols[i % 4].caption(f"{ui.fmt_date(m.measured_on)}: foto indisponível")

notes = [m for m in ms if m.notes]
if notes:
    with st.expander("Observações registradas"):
        for m in reversed(notes):
            st.markdown(f"**{ui.fmt_date(m.measured_on)}** — {m.notes}")

st.divider()
st.markdown("**Análise de tendências (Gemini)**")
if last_ai:
    st.markdown(last_ai.content)
    st.caption(f"Gerada em {last_ai.created_at:%d/%m/%Y %H:%M}. Texto automático, não substitui avaliação profissional.")
if st.button("Gerar nova análise", disabled=not gs.is_configured() or w.empty):
    facts = {"pesos_semana": [[str(k.date()), round(v, 1)] for k, v in wk.tail(12).items()] if not w.empty else [],
             "medidas": mdf.tail(6).astype(str).values.tolist() if not mdf.empty else [],
             "treinos_por_semana": weekly["treinos"].tolist(),
             "cargas": (hist[hist["concluida"]].groupby("exercicio")["carga"].agg(["first", "last"]).reset_index()
                        .head(10).values.tolist() if not hist.empty else [])}
    try:
        with ui.loading("Consultando o Gemini…"), session_scope() as s:
            ai_trend_analysis(s, s.get(Profile, p.id), facts)
        st.rerun()
    except gs.GeminiUnavailable as exc:
        st.error(str(exc))
