"""Linguagem visual do FitOS: editorial, sóbria, mesma família do Brasil em Dados."""
from __future__ import annotations

import html
from typing import Iterable

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# Paleta categórica validada (CVD/contraste) para a superfície escura #181b21
SERIES = ["#2fae64", "#3a8fd8", "#b9801c", "#9a7ce0", "#e0584f"]
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#eceae5", "#c3c7cf", "#9aa1ad", "#2a2e36", "#383d47", "#181b21"
ACCENT = "#3fbf74"
GOOD, WARN, BAD = "#3fbf74", "#d9a75f", "#e86370"

CSS = """
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@700;800&display=swap");
:root { --page:#0f1115; --surface:#181b21; --ink:#eceae5; --ink-2:#c3c7cf; --muted:#9aa1ad; --grid:#2a2e36;
        --axis:#383d47; --border:#343943; --chip:#20242c; --acento:#3fbf74; --bad:#e86370; --warn:#d9a75f; }
body { font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif; }
h1, h2, h3, .fx-val { font-family: "Playfair Display", Georgia, serif !important; letter-spacing: -.01em; }
h1 { font-weight: 800 !important; }
.block-container { padding-top: 2.2rem; max-width: 1320px; }
[data-testid="stSidebar"] { border-right: 1px solid var(--border); }
[data-testid="stSidebarNavSeparator"] { border-color: var(--border); }
.fx-head { border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 18px; }
.fx-head h1 { font-size: 34px; margin: 0 0 4px; padding: 0; line-height: 1.15; }
.fx-head p { color: var(--ink-2); margin: 0; max-width: 85ch; font-size: 14.5px; }
.fx-head .fx-kicker { text-transform: uppercase; letter-spacing: .08em; font-size: 11.5px; color: var(--acento); font-weight: 600; margin-bottom: 4px; }
.fx-tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; margin: 4px 0 18px; }
.fx-tile { background: var(--surface); border: 1px solid var(--border); border-top: 3px solid var(--ink); padding: 12px 14px 10px; min-width: 0; }
.fx-tile.acento { border-top-color: var(--acento); }
.fx-tile .fx-rot { font-size: 12.5px; color: var(--ink-2); }
.fx-tile .fx-val { font-size: 27px; font-weight: 800; line-height: 1.2; margin-top: 2px; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fx-tile .fx-det { font-size: 12px; color: var(--muted); margin-top: 2px; }
.fx-tile .fx-det b { color: var(--ink-2); font-weight: 600; }
.fx-prov { display: inline-block; font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em; color: var(--warn);
           border: 1px solid rgba(217,167,95,.45); padding: 0 5px; margin-left: 6px; vertical-align: 2px; }
.fx-card { background: var(--surface); border: 1px solid var(--border); border-top: 3px solid var(--ink); padding: 16px 18px; margin-bottom: 14px; }
.fx-card h3 { font-size: 17px; margin: 0 0 6px; padding: 0; }
.fx-card p { color: var(--ink-2); margin: 0 0 6px; }
.fx-note { font-size: 12.5px; color: var(--muted); margin: 6px 0 14px; max-width: 95ch; }
.fx-note a { color: var(--ink-2); }
.fx-list { margin: 0; padding-left: 18px; color: var(--ink-2); }
.fx-list li { margin-bottom: 5px; }
.fx-chip { display: inline-block; background: var(--chip); padding: 1px 8px; font-size: 11.5px; margin: 0 4px 4px 0; color: var(--ink-2); }
.fx-chip.ok { color: var(--acento); }
.fx-chip.warn { color: var(--warn); }
.fx-chip.bad { color: var(--bad); }
.fx-meal { border-left: 3px solid var(--acento); padding: 2px 0 2px 12px; margin: 8px 0 4px; }
.fx-meal b { font-size: 15px; }
.fx-meal span { color: var(--muted); font-size: 12.5px; }
.fx-day { font-family: "Playfair Display", Georgia, serif; font-size: 20px; font-weight: 800; margin: 12px 0 2px; }
.fx-ex { display:flex; gap:14px; align-items:flex-start; border-top: 1px solid var(--grid); padding: 10px 0; }
.fx-ex img { width: 96px; height: 96px; object-fit: cover; background: #fff; flex: none; }
.fx-ex .fx-ex-t { font-weight: 600; }
.fx-ex .fx-ex-d { color: var(--muted); font-size: 12.5px; }
.fx-media-off { width: 96px; height: 96px; display:flex; align-items:center; justify-content:center; text-align:center;
                font-size: 11px; color: var(--muted); border: 1px dashed var(--border); flex: none; }
div[data-testid="stMetric"] { background: var(--surface); border: 1px solid var(--border); border-top: 3px solid var(--ink); padding: 10px 14px; }
div[data-testid="stMetricValue"] { font-family: "Playfair Display", Georgia, serif; font-weight: 800; }
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--border); }
.stTabs [data-baseweb="tab"] { padding: 6px 12px; }
[data-testid="stExpander"] details { border-radius: 0; }
button[kind="primary"] { font-weight: 600; }
@media (max-width: 640px) {
  .block-container { padding: 3.8rem 1rem 3rem; }
  .fx-head h1 { font-size: 26px; }
  .fx-tiles { grid-template-columns: 1fr 1fr; gap: 8px; }
  .fx-tile .fx-val { font-size: 21px; }
}
</style>
"""


def inject_css() -> None:
    st.html(CSS)


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
        return '<div class="fx-media-off">sem mídia</div>'
    return (f'<img src="{esc(url)}" alt="mídia indisponível — {esc(alt)}" loading="lazy" '
            "onerror=\"this.outerHTML='<div class=&quot;fx-media-off&quot;>mídia indisponível</div>'\">")


# --------------------------------------------------------------------------- plotly

def _register_template() -> None:
    if "fitos" in pio.templates:
        return
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family="Inter, system-ui, sans-serif", color=INK2, size=12.5),
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
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "locale": "pt-BR"})


def fmt_num(v, digits: int = 0) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def fmt_date(d) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"
