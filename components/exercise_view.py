"""Linhas de exercício com miniatura e a janela de detalhe (GIF grande, prescrição, execução)."""
from __future__ import annotations

import streamlit as st

from components import ui
from database.connection import session_scope
from database.models import Exercise, PlannedExercise
from services import exercise_service as es
from services import workout_service as ws
from services.catalog_data import SLOT_LABELS


def prescription_text(pe: PlannedExercise) -> str:
    if pe.exercise.slot == "cardio":  # na prescrição local, repetições de cardio são minutos
        return f"{pe.reps_min}–{pe.reps_max} min"
    return f"{pe.sets} × {pe.reps_min}–{pe.reps_max} · descanso {pe.rest_seconds}s"


def exercise_list(exercises: list[PlannedExercise], key: str, *, completed: dict | None = None,
                  extra: dict | None = None, profile_id: int | None = None) -> None:
    """Uma linha por exercício; “Ver execução” abre o detalhe. `extra[pe.id]` é HTML sob a prescrição."""
    completed, extra = completed or {}, extra or {}
    for i, pe in enumerate(exercises, 1):
        name = es.display_name(pe.exercise)
        count = completed.get(pe.id, 0)
        marks = "".join(f'<i class="{"done" if n < count else ""}"></i>' for n in range(pe.sets))
        with st.container(key=f"exrow-{key}-{pe.id}"):
            c1, c2 = st.columns([5, 1], vertical_alignment="center", gap="small")
            c1.html(f'<div class="fx-ex"><span class="fx-ex-number">{i}</span>'
                    f'{ui.media_html(pe.exercise.gif_url, name, "fx-thumb fx-thumb-sm")}'
                    f'<div class="fx-ex-body"><div class="fx-ex-t">{ui.esc(name)}</div>'
                    f'<div class="fx-ex-d">{ui.esc(prescription_text(pe))}'
                    f'{" · " + ui.esc(pe.notes) if pe.notes else ""}</div>{extra.get(pe.id, "")}</div>'
                    f'<div class="fx-sets" aria-label="{count} de {pe.sets} séries">{marks}</div></div>')
            if c2.button("Ver execução", key=f"ver-{key}-{pe.id}", type="tertiary", icon=":material/play_circle:"):
                show_exercise(pe.exercise_id, pe.id, profile_id)


@st.dialog("Execução do exercício", width="large")
def show_exercise(exercise_id: int, planned_id: int | None = None, profile_id: int | None = None) -> None:
    with session_scope() as s:
        ex = s.get(Exercise, exercise_id)
        pe = s.get(PlannedExercise, planned_id) if planned_id else None
        if pe:
            pe.exercise  # noqa: B018 — carrega antes de fechar a sessão
        last = ws.last_sets(s, profile_id, exercise_id) if profile_id else []
    exercise_detail(ex, pe, last)


def exercise_detail(ex: Exercise, pe: PlannedExercise | None = None, last: list | None = None) -> None:
    name = es.display_name(ex)
    st.html(f'<div class="fx-day">{ui.esc(name)}</div>'
            + (f'<p class="fx-note">{ui.esc(ex.name_original)}</p>' if ex.name_pt else ""))
    media, info = st.columns([1.1, 1], gap="large")
    with media:
        if ex.video_url:
            st.video(ex.video_url)
            ui.note("Vídeos do wger podem estar em HEVC (.MOV), que alguns navegadores não reproduzem.")
        if ex.gif_url or not ex.video_url:
            st.html(ui.media_html(ex.gif_url, f"Demonstração de {name}", "fx-thumb fx-demo"))
    with info:
        chips = [es.BODY_PARTS_PT.get(ex.body_part, ex.body_part), ex.primary_muscle,
                 es.EQUIPMENT_PT.get(ex.equipment, ex.equipment), ex.difficulty, SLOT_LABELS.get(ex.slot)]
        st.html("".join(ui.chip(c) for c in chips if c))
        rows = []
        if pe:
            rows.append(("Na sua ficha", prescription_text(pe)))
            if pe.notes:
                rows.append(("Observação", pe.notes))
        if last:
            rows.append(("Última vez", ", ".join(f"{(r.load_kg or 0):g} kg × {r.reps}" for r in last if r.reps)
                         or "sem carga registrada"))
        if ex.secondary_muscles:
            rows.append(("Músculos secundários", ", ".join(ex.secondary_muscles)))
        if rows:
            st.html('<dl class="fx-facts">' + "".join(f"<dt>{ui.esc(k)}</dt><dd>{ui.esc(v)}</dd>" for k, v in rows)
                    + "</dl>")
        if ex.common_errors:
            st.html(f'<div class="fx-facts-t">Erros comuns</div><p class="fx-body">{ui.esc(ex.common_errors)}</p>')
            ui.note("Orientação geral do FitOS por padrão de movimento.")
    if ex.instructions:
        steps = [x.strip() for x in ex.instructions.split("\n") if x.strip()]
        st.html('<div class="fx-facts-t">Como executar</div><ol class="fx-steps">'
                + "".join(f"<li>{ui.esc(x)}</li>" for x in steps) + "</ol>")
        if not ex.name_pt or ex.source == "exercisedb":
            ui.note("Instruções no idioma original da fonte.")
    ui.note(f"Fonte: {ui.esc(ex.attribution or ex.media_source or ex.source)} · Licença: {ui.esc(ex.license or '—')}")
