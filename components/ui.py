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
    st.html('<div class="fx-tiles">' + "".join(tile_html(it) for it in items) + "</div>")


def tile_html(it: dict, extra: str = "") -> str:
    prov = '<span class="fx-prov">provisório</span>' if it.get("provisional") else ""
    det = f'<div class="fx-det">{it["detail"]}</div>' if it.get("detail") else ""
    foot = f'<div class="fx-det fx-foot">{esc(it["foot"])}</div>' if it.get("foot") else ""
    cls = "fx-tile acento" if it.get("accent") else "fx-tile"
    return (f'<div class="{cls}"><div class="fx-rot">{esc(it["label"])}{prov}</div>'
            f'<div class="fx-val" title="{esc(it["value"])}">{esc(it["value"])}</div>{det}{extra}{foot}</div>')


def panel(name: str):
    """Contêiner com borda no estilo de cartão do FitOS (o nome vira a classe st-key-card-<nome>)."""
    return st.container(border=True, key=f"card-{name}")


def card(title: str, body_html: str) -> None:
    st.html(f'<div class="fx-card"><h3>{esc(title)}</h3>{body_html}</div>')


def note(text: str) -> None:
    st.html(f'<p class="fx-note">{text}</p>')


def chip(text: str, kind: str = "") -> str:
    return f'<span class="fx-chip {kind}">{esc(text)}</span>'


def bullet_list(items: list[str]) -> str:
    return '<ul class="fx-list">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def media_html(url: str | None, alt: str, cls: str = "fx-thumb") -> str:
    """Quadro de tamanho fixo; se a fonte externa falhar, o fundo mostra “sem demonstração”."""
    img = f'<img src="{esc(url)}" alt="{esc(alt)}" loading="lazy">' if url else ""
    return f'<div class="{cls}" data-vazio="sem demonstração">{img}</div>'



# --------------------------------------------------------------------------- plotly

def _register_template() -> None:
    if "fitos" in pio.templates:
        return
    axis = dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickcolor=AXIS, automargin=True,
                tickfont=dict(color=MUTED, size=11), title=dict(font=dict(color=MUTED, size=11)))
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family="Geist, system-ui, sans-serif", color=INK2, size=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", colorway=SERIES,
        xaxis=dict(axis, showgrid=False, showline=True, ticks="outside", ticklen=4),
        yaxis=dict(axis, showgrid=True, showline=False, nticks=6, tickformat=",~f"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(color=INK2, size=12),
                    bgcolor="rgba(0,0,0,0)", itemsizing="constant", itemwidth=30, title=None),
        margin=dict(l=4, r=12, t=8, b=4), hoverlabel=dict(bgcolor=SURFACE, bordercolor=AXIS, font=dict(color=INK)),
        hovermode="x unified", separators=",.", bargap=0.42, barcornerradius=4, showlegend=True,
    )
    t.data.scatter = [go.Scatter(line=dict(width=2), marker=dict(size=8, line=dict(width=1.5, color=SURFACE)))]
    t.data.bar = [go.Bar(marker=dict(line=dict(width=0)))]
    pio.templates["fitos"] = t


_register_template()


def fig_layout(fig: go.Figure, title: str | None = None, height: int = 300, caption: str | None = None) -> go.Figure:
    """O título e a legenda ficam fora da área do gráfico; o título é desenhado pelo cartão em plot()."""
    legend = sum(1 for tr in fig.data if tr.showlegend is not False) >= 2
    fig.update_layout(template="fitos", height=height, title=None, showlegend=legend,
                      paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
                      margin=dict(t=36 if legend else 8),
                      meta={"title": title, "caption": caption})
    return fig


def date_axis(fig: go.Figure, fmt: str = "%d/%m") -> go.Figure:
    """Datas no padrão brasileiro (o Plotly não traz o locale pt-BR embutido)."""
    fig.update_xaxes(tickformat=fmt, hoverformat="%d/%m/%Y")
    return fig


def plot(fig: go.Figure) -> None:
    if not isinstance(fig.layout.meta, dict):  # gráfico montado sem fig_layout
        fig_layout(fig)
    meta = fig.layout.meta
    # O cabeçalho é sempre emitido: o CSS reconhece o cartão do gráfico por ele.
    with st.container(border=True):
        st.html('<div class="fx-chart-head">'
                + (f'<h3>{esc(meta["title"])}</h3>' if meta.get("title") else "")
                + (f'<p>{esc(meta["caption"])}</p>' if meta.get("caption") else "") + "</div>")
        st.plotly_chart(fig, width="stretch", theme=None,
                        config={"displayModeBar": False, "locale": "pt-BR", "responsive": True})


def day_title(title: str) -> str:
    """“SEXTA — SUPERIORES B — COSTAS, PEITO E BRAÇOS” → “Sexta — Superiores B — Costas, peito e braços”."""
    parts = []
    for p in title.split(" — "):
        words = p.lower().split()
        if len(words) > 1 and len(words[-1]) == 1:  # letra do treino (A, B, C)
            words[-1] = words[-1].upper()
        text = " ".join(words)
        parts.append(text[:1].upper() + text[1:])
    return " — ".join(parts)


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
    st.html(week_strip_html(plan, finished_dates))


def week_strip_html(plan, finished_dates) -> str:
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
    return '<div class="fx-week" aria-label="Semana de treinos">' + ''.join(out) + '</div>'


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
