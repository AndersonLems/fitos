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

# --------------------------------------------------------------------------- temas
# Três temas escuros: os widgets nativos do Streamlit vêm do .streamlit/config.toml (base escura) e só
# o acento e as superfícies são trocados por CSS, então um tema claro deixaria tabelas e campos destoando.
# Cada série categórica foi escolhida para separar bem na superfície do próprio tema.
THEMES: dict[str, dict] = {
    "lima": {
        "label": "Lima", "page": "#0b0d10", "surface": "#14181e", "chip": "#1b2027", "ink": "#f3f5f7",
        "ink2": "#a4adb9", "muted": "#737d8a", "border": "#2a3039", "axis": "#383d47", "track": "#29313c",
        "accent": "#b5f24a", "on_accent": "#203019", "warn": "#e4b568", "bad": "#df7770",
        "series": ["#B5F24A", "#6eaddb", "#e4b568", "#9a7ce0", "#e0584f"],
    },
    "oceano": {
        "label": "Oceano", "page": "#080d14", "surface": "#0f1722", "chip": "#16202d", "ink": "#eef3f8",
        "ink2": "#9fb1c4", "muted": "#6c7f93", "border": "#22303f", "axis": "#2f3e50", "track": "#223040",
        "accent": "#5cc8ff", "on_accent": "#032435", "warn": "#e8b864", "bad": "#f0727a",
        "series": ["#5cc8ff", "#b9e769", "#e8b864", "#b392f0", "#f0727a"],
    },
    "brasa": {
        "label": "Brasa", "page": "#0f0b09", "surface": "#1a1411", "chip": "#231b17", "ink": "#f8f1ec",
        "ink2": "#c2b1a6", "muted": "#8c7a6e", "border": "#362a23", "axis": "#45362d", "track": "#3a2d26",
        "accent": "#ff8f4f", "on_accent": "#381402", "warn": "#f2c45a", "bad": "#ef6f8a",
        "series": ["#ff8f4f", "#6ab7e6", "#f2c45a", "#a98be6", "#5fcfa0"],
    },
}
DEFAULT_THEME = "lima"
THEME_KEY = "tema"

# Nomes antigos (ui.SERIES, ui.ACCENT…) resolvidos pelo tema da sessão: o módulo é compartilhado entre
# sessões, então as cores não podem ser globais mutáveis.
_TOKENS = {"SERIES": "series", "INK": "ink", "INK2": "ink2", "MUTED": "muted", "GRID": "border", "AXIS": "axis",
           "SURFACE": "surface", "ACCENT": "accent", "GOOD": "accent", "WARN": "warn", "BAD": "bad"}


def theme_key() -> str:
    try:
        key = st.session_state.get(THEME_KEY)
    except Exception:  # noqa: BLE001 — fora de uma execução do Streamlit (testes de serviço)
        key = None
    return key if key in THEMES else DEFAULT_THEME


def theme() -> dict:
    return THEMES[theme_key()]


def set_theme(key: str | None) -> None:
    st.session_state[THEME_KEY] = key if key in THEMES else DEFAULT_THEME


def __getattr__(name: str):
    if name in _TOKENS:
        return theme()[_TOKENS[name]]
    raise AttributeError(name)


def _theme_css(t: dict) -> str:
    return (":root{" + f"--page:{t['page']};--surface:{t['surface']};--chip:{t['chip']};--ink:{t['ink']};"
            f"--ink-2:{t['ink2']};--muted:{t['muted']};--border:{t['border']};--track:{t['track']};"
            f"--acento:{t['accent']};--on-acento:{t['on_accent']};--warn:{t['warn']};--bad:{t['bad']}" + "}")


def inject_css() -> None:
    css = (Path(__file__).resolve().parents[1] / "assets/theme.css").read_text()
    st.html("<style>" + css + _theme_css(theme()) + "</style>")


def theme_swatch_html(key: str) -> str:
    t = THEMES[key]
    dots = "".join(f'<i style="background:{c}"></i>' for c in t["series"][:4])
    return (f'<div class="fx-swatch" style="background:{t["surface"]};border-color:{t["border"]};color:{t["ink"]}">'
            f'<b style="background:{t["accent"]};color:{t["on_accent"]}">Aa</b><span>{esc(t["label"])}</span>'
            f'<div>{dots}</div></div>')


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

def _template_name() -> str:
    key = theme_key()
    name = f"fitos-{key}"
    if name in pio.templates:
        return name
    th = THEMES[key]
    axis = dict(gridcolor=th["border"], linecolor=th["axis"], zeroline=False, tickcolor=th["axis"], automargin=True,
                tickfont=dict(color=th["muted"], size=11), title=dict(font=dict(color=th["muted"], size=11)))
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family="Geist, system-ui, sans-serif", color=th["ink2"], size=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", colorway=th["series"],
        xaxis=dict(axis, showgrid=False, showline=True, ticks="outside", ticklen=4),
        yaxis=dict(axis, showgrid=True, showline=False, nticks=6, tickformat=",~f"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(color=th["ink2"], size=12), bgcolor="rgba(0,0,0,0)", itemsizing="constant",
                    itemwidth=30, title=None),
        margin=dict(l=4, r=12, t=8, b=4),
        hoverlabel=dict(bgcolor=th["surface"], bordercolor=th["axis"], font=dict(color=th["ink"])),
        hovermode="x unified", separators=",.", bargap=0.42, barcornerradius=4, showlegend=True,
    )
    t.data.scatter = [go.Scatter(line=dict(width=2), marker=dict(size=8, line=dict(width=1.5, color=th["surface"])))]
    t.data.bar = [go.Bar(marker=dict(line=dict(width=0)))]
    pio.templates[name] = t
    return name


def fig_layout(fig: go.Figure, title: str | None = None, height: int = 300, caption: str | None = None) -> go.Figure:
    """O título e a legenda ficam fora da área do gráfico; o título é desenhado pelo cartão em plot()."""
    legend = sum(1 for tr in fig.data if tr.showlegend is not False) >= 2
    surface = theme()["surface"]
    fig.update_layout(template=_template_name(), height=height, title=None, showlegend=legend,
                      paper_bgcolor=surface, plot_bgcolor=surface,
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


def progress_html(value: float, maximum: float, color: str | None = None) -> str:
    color = color or theme()["accent"]
    pct = max(0, min(100, float(value) / float(maximum) * 100)) if maximum else 0
    return (f'<div class="fx-track" role="progressbar" aria-label="Progresso" aria-valuenow="{pct:.0f}" '
            f'aria-valuemin="0" aria-valuemax="100"><span style="width:{pct}%;background:{color}"></span></div>')


def svg_image(svg: str) -> str:
    # st.html intentionally strips inline SVG; an image keeps the vector intact.
    data = base64.b64encode(svg.encode()).decode()
    return f'<img src="data:image/svg+xml;base64,{data}" alt="" aria-hidden="true" class="fx-icon">'


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


def app_chrome(title: str, name: str, path: str) -> None:
    from datetime import date
    st.html(f'<div class="fx-topbar"><span>FitOS &nbsp; / &nbsp; <strong>{esc(title)}</strong></span>'
            f'<span class="fx-top-date">{date.today():%d/%m/%Y}</span>'
            f'<a href="evolucao" target="_self">＋ Registrar peso</a><strong>{esc(name)}</strong></div>')
    links = [('','Hoje'),('treinos','Treinos'),('plano-alimentar','Alimentar'),('despensa','Despensa'),('personal-ia','Personal IA')]
    icons = ['<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
             '<path d="m6 6 12 12M3 7l4-4M17 21l4-4M2 10l8-8M14 22l8-8"/>',
             '<path d="M5 3v7m4-7v7m-6 0h8M7 10v11M18 3v18m0-18c-5 4-5 10 0 10"/>',
             '<rect x="3" y="7" width="18" height="14"/><path d="M2 3h20v4H2zm7 9h6"/>',
             '<path d="m12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3z"/>']
    st.html('<nav class="fx-mobile-nav" aria-label="Navegação principal">' + ''.join(
        f'<a href="/{route}" target="_self"'+(' aria-current="page"' if route == path else '')
        + '>' + svg_image(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{theme()["ink2"]}" stroke-width="1.6">{icon}</svg>') + f'{label}</a>'
        for (route,label),icon in zip(links,icons)) + '</nav>')
