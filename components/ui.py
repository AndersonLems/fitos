"""Primitivos Streamlit adaptados do design React lime-powered-fit-club."""
from __future__ import annotations

import html
import base64
from pathlib import Path
from contextlib import contextmanager
from typing import Iterable

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# Paleta categórica validada (CVD/contraste) para a superfície escura #14181E
SERIES = ["#B5F24A", "#6eaddb", "#e4b568", "#9a7ce0", "#e0584f"]
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#F3F5F7", "#A4ADB9", "#737D8A", "#2A3039", "#383d47", "#14181E"
ACCENT = "#B5F24A"
GOOD, WARN, BAD = "#B5F24A", "#d9a75f", "#e86370"



def inject_css() -> None:
    st.html("<style>" + (Path(__file__).resolve().parents[1] / "assets/theme.css").read_text() + "</style>")


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def page_header(title: str, desc: str = "", kicker: str = "") -> None:
    k = f'<div class="fx-kicker">{esc(kicker)}</div>' if kicker else ""
    p = f"<p>{esc(desc)}</p>" if desc else ""
    st.html(f'<div class="fx-head">{k}<h1>{esc(title)}</h1>{p}</div>')


def tiles(items: Iterable[dict]) -> None:
    """items: {label, value, detail?, foot?, provisional?, accent?} — texto já formatado."""
    out = []
    for it in items:
        prov = '<span class="fx-prov">provisório</span>' if it.get("provisional") else ""
        det = f'<div class="fx-det">{it["detail"]}</div>' if it.get("detail") else ""
        foot = f'<div class="fx-det">{esc(it["foot"])}</div>' if it.get("foot") else ""
        cls = "fx-tile acento" if it.get("accent") else "fx-tile"
        out.append(f'<div class="{cls}"><div class="fx-rot">{esc(it["label"])}{prov}</div>'
                   f'<div class="fx-val" title="{esc(it["value"])}">{esc(it["value"])}</div>{det}{foot}</div>')
    st.html('<div class="fx-tiles">' + "".join(out) + "</div>")


def card(title: str, body_html: str) -> None:
    st.html(f'<div class="fx-card"><h3>{esc(title)}</h3>{body_html}</div>')


def note(text: str) -> None:
    st.html(f'<p class="fx-note">{text}</p>')


def chip(text: str, kind: str = "") -> str:
    return f'<span class="fx-chip {kind}">{esc(text)}</span>'


def bullet_list(items: list[str]) -> str:
    return '<ul class="fx-list">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def media_html(url: str | None, alt: str) -> str:
    if not url:
        return '<div class="fx-media-off" aria-label="Sem mídia">◇</div>'
    return (f'<img src="{esc(url)}" alt="mídia indisponível — {esc(alt)}" loading="lazy" '
            "onerror=\"this.outerHTML='<div class=&quot;fx-media-off&quot;>mídia indisponível</div>'\">")


# --------------------------------------------------------------------------- plotly

def _register_template() -> None:
    if "fitos" in pio.templates:
        return
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family="Geist, system-ui, sans-serif", color=INK2, size=12.5),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", colorway=SERIES,
        xaxis=dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickcolor=AXIS, showgrid=False),
        yaxis=dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickcolor=AXIS),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, font=dict(color=INK2),
                    bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=8, r=8, t=64, b=8), hoverlabel=dict(bgcolor=SURFACE, bordercolor=AXIS, font=dict(color=INK)),
        hovermode="x unified", separators=",.",
    )
    pio.templates["fitos"] = t


_register_template()


def fig_layout(fig: go.Figure, title: str | None = None, height: int = 320) -> go.Figure:
    fig.update_layout(template="fitos", height=height,
                      title=dict(text=title, font=dict(size=15, color=INK), x=0, xanchor="left", y=0.98, yanchor="top")
                      if title else None)
    return fig


def date_axis(fig: go.Figure, fmt: str = "%d/%m") -> go.Figure:
    """Datas no padrão brasileiro (o Plotly não traz o locale pt-BR embutido)."""
    fig.update_xaxes(tickformat=fmt, hoverformat="%d/%m/%Y")
    return fig


def plot(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False, "locale": "pt-BR"})


def fmt_num(v, digits: int = 0) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def fmt_date(d) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


@contextmanager
def loading(label: str, rows: int = 3):
    """Actual operation lifetime, with cleanup on success, failure or rerun."""
    placeholder = st.empty()
    placeholder.html('<div class="fx-loading" role="status" aria-live="polite" aria-busy="true">'
                     '<div class="fx-loading-line"></div><p>' + esc(label) + '</p>'
                     + '<div class="fx-skeleton" aria-hidden="true"></div>' * rows + '</div>')
    try:
        yield
    finally:
        placeholder.empty()


def progress_html(value: float, maximum: float, color: str = ACCENT) -> str:
    pct = max(0, min(100, float(value) / float(maximum) * 100)) if maximum else 0
    return (f'<div class="fx-track" role="progressbar" aria-label="Progresso" aria-valuenow="{pct:.0f}" '
            f'aria-valuemin="0" aria-valuemax="100"><span style="width:{pct}%;background:{color}"></span></div>')


def svg_image(svg: str) -> str:
    # st.html intentionally strips inline SVG; an image keeps the vector intact.
    data = base64.b64encode(svg.encode()).decode()
    return f'<img src="data:image/svg+xml;base64,{data}" alt="" aria-hidden="true" class="fx-icon">'


def exercise_rows(exercises, completed: dict | None = None) -> None:
    completed = completed or {}
    rows = []
    for i, pe in enumerate(exercises, 1):
        name = pe.exercise.name_pt or pe.exercise.name_original
        count = completed.get(pe.id, 0)
        marks = ''.join(f'<i class="{"done" if n < count else ""}"></i>' for n in range(pe.sets))
        icon = svg_image('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
                         'fill="none" stroke="#A4ADB9" stroke-width="1.6">'
                         '<path d="m6 6 12 12M3 7l4-4M17 21l4-4M2 10l8-8M14 22l8-8"/></svg>')
        thumb = f'<div class="fx-media-off" aria-hidden="true">{icon}</div>'
        rows.append(f'<div class="fx-ex"><span class="fx-ex-number">{i}</span>'
                    f'{thumb}<div class="fx-ex-body">'
                    f'<div class="fx-ex-t">{esc(name)}</div><div class="fx-ex-d">'
                    f'{pe.sets} × {pe.reps_min}–{pe.reps_max} · descanso {pe.rest_seconds}s</div></div>'
                    f'<div class="fx-sets" aria-label="{count} de {pe.sets} séries">{marks}</div>'
                    f'<span class="fx-ex-d">{"✓" if count >= pe.sets else "›"}</span></div>')
    st.html(''.join(rows))


def week_strip(plan, finished_dates) -> None:
    from datetime import date, timedelta
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    scheduled = {d.weekday for d in plan.days} if plan else set()
    out = []
    for n, name in enumerate(['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']):
        day = monday + timedelta(days=n)
        cls = 'done' if day in finished_dates else 'today' if day == today else 'planned' if n in scheduled else ''
        label = 'Concluído' if cls == 'done' else 'Hoje' if cls == 'today' else 'Programado' if cls else 'Descanso'
        out.append(f'<div title="{day:%d/%m}: {label}">{name}<b class="{cls}">{day.day}</b></div>')
    st.html('<div class="fx-week" aria-label="Semana de treinos">' + ''.join(out) + '</div>')


def app_chrome(title: str, name: str, profile_id: int, path: str) -> None:
    from datetime import date
    st.html(f'<div class="fx-topbar"><span>FitOS &nbsp; / &nbsp; <strong>{esc(title)}</strong></span>'
            f'<span class="fx-top-date">{date.today():%d/%m/%Y}</span>'
            f'<a href="evolucao?perfil={profile_id}" target="_self">＋ Registrar peso</a><strong>{esc(name)}</strong></div>')
    links = [('','Hoje'),('treinos','Treinos'),('plano-alimentar','Alimentar'),('despensa','Despensa'),('personal-ia','Personal IA')]
    icons = ['<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
             '<path d="m6 6 12 12M3 7l4-4M17 21l4-4M2 10l8-8M14 22l8-8"/>',
             '<path d="M5 3v7m4-7v7m-6 0h8M7 10v11M18 3v18m0-18c-5 4-5 10 0 10"/>',
             '<rect x="3" y="7" width="18" height="14"/><path d="M2 3h20v4H2zm7 9h6"/>',
             '<path d="m12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3z"/>']
    st.html('<nav class="fx-mobile-nav" aria-label="Navegação principal">' + ''.join(
        f'<a href="/{route}?perfil={profile_id}" target="_self"'+(' aria-current="page"' if route == path else '')
        + '>' + svg_image(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#A4ADB9" stroke-width="1.6">{icon}</svg>') + f'{label}</a>'
        for (route,label),icon in zip(links,icons)) + '</nav>')
