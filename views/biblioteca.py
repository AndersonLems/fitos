import streamlit as st

from components import ui
from database.connection import session_scope
from database.models import Exercise
from services import exercise_service as es
from services.catalog_data import SLOT_LABELS

ui.page_header("Biblioteca de exercícios", "Catálogo local com demonstrações do ExerciseDB e do wger. As mídias são "
               "exibidas a partir das fontes originais, com atribuição; não há cópia local.", kicker="Treino")

with session_scope() as s:
    body_parts = es.distinct_values(s, Exercise.body_part)
    equipments = es.distinct_values(s, Exercise.equipment)
    total = s.query(Exercise).count()

c1, c2, c3, c4 = st.columns([3, 2, 2, 1.4])
text = c1.text_input("Buscar", placeholder="supino, remada, glúteo…")
bp = c2.selectbox("Região", [None, *body_parts], format_func=lambda v: es.BODY_PARTS_PT.get(v, v) if v else "Todas")
eq = c3.selectbox("Equipamento", [None, *equipments], format_func=lambda v: es.EQUIPMENT_PT.get(v, v) if v else "Todos")
only_core = c4.toggle("Só principais", value=not text, help="Exercícios com nome em português usados nas fichas")

with session_scope() as s:
    results = es.search(s, text, bp, eq, only_core, limit=48)
st.caption(f"{len(results)} exibidos de {total} no catálogo")

if not results:
    st.info("Nada encontrado com esses filtros.")
else:
    ids = [e.id for e in results]
    sel = st.session_state.get("ex_sel")
    if sel not in ids:
        sel = ids[0]
    left, right = st.columns([2, 3])
    with left:
        sel = st.radio("Exercícios", ids, index=ids.index(sel), label_visibility="collapsed",
                       format_func=lambda i: next(es.display_name(e) for e in results if e.id == i))
        st.session_state["ex_sel"] = sel
    ex = next(e for e in results if e.id == sel)
    with right:
        st.html(f'<div class="fx-day">{ui.esc(es.display_name(ex))}</div>'
                + (f'<p class="fx-note">{ui.esc(ex.name_original)}</p>' if ex.name_pt else ""))
        chips = [es.BODY_PARTS_PT.get(ex.body_part, ex.body_part), ex.primary_muscle,
                 es.EQUIPMENT_PT.get(ex.equipment, ex.equipment), ex.difficulty, SLOT_LABELS.get(ex.slot)]
        st.html("".join(ui.chip(c) for c in chips if c))
        if ex.video_url:
            st.video(ex.video_url)
            ui.note("Vídeos do wger podem estar em HEVC (.MOV), que alguns navegadores não reproduzem.")
        if ex.gif_url:
            st.html(f'<img src="{ui.esc(ex.gif_url)}" alt="Demonstração de {ui.esc(es.display_name(ex))} — '
                    f'mídia indisponível" style="max-width:360px;width:100%;background:#fff">')
        if not ex.gif_url and not ex.video_url:
            st.warning("Sem mídia de demonstração para este exercício.")
        if ex.secondary_muscles:
            st.caption("Músculos secundários: " + ", ".join(ex.secondary_muscles))
        if ex.instructions:
            st.markdown("**Execução**")
            steps = [x for x in ex.instructions.split("\n") if x.strip()]
            st.markdown("\n".join(f"{i}. {x.strip()}" for i, x in enumerate(steps, 1)))
            if not ex.name_pt or ex.source == "exercisedb":
                ui.note("Instruções no idioma original da fonte.")
        if ex.common_errors:
            st.markdown("**Erros comuns**")
            st.markdown(ex.common_errors)
            ui.note("Orientação geral do FitOS por padrão de movimento.")
        ui.note(f"Fonte: {ui.esc(ex.attribution or ex.media_source or ex.source)} · Licença: {ui.esc(ex.license or '—')}")

with st.expander("Atualizar catálogo a partir das fontes"):
    st.write("ExerciseDB: ~1.500 exercícios com GIF (sem chave, com limite de requisições; leva ~1–2 min). "
             "wger: exercícios com imagens e vídeos sob licença CC-BY-SA (leva ~1 min). WorkoutDB: sem API pública "
             "acessível — integração não implementada.")
    c1, c2 = st.columns(2)
    if c1.button("Sincronizar ExerciseDB"):
        with st.spinner("Baixando…"), session_scope() as s:
            _, msg = es.sync_exercisedb(s)
        st.info(msg)
    if c2.button("Importar do wger"):
        with st.spinner("Baixando…"), session_scope() as s:
            _, msg = es.sync_wger(s)
        st.info(msg)
