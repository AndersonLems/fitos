import streamlit as st

from components import ui
from components.exercise_view import exercise_detail
from components.state import require_profile
from database.connection import session_scope
from database.models import Exercise
from services import exercise_service as es
from services import workout_service as ws

p = require_profile()
ui.page_header("Biblioteca de exercícios", "Catálogo local com demonstrações do ExerciseDB e do wger. As mídias são "
               "exibidas a partir das fontes originais, com atribuição; não há cópia local.")

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
    with left, st.container(key="library-grid"):
        # Linhas de dois cartões: cada linha estica os dois cartões até a mesma altura.
        for start in range(0, len(results), 2):
            row = st.columns(2)
            for col, exercise in zip(row, results[start:start + 2]):
                with col, ui.panel(f"lib-{exercise.id}"):
                    st.html(ui.media_html(exercise.gif_url, es.display_name(exercise)))
                    st.caption(es.BODY_PARTS_PT.get(exercise.body_part, exercise.body_part) or "Exercício")
                    if st.button(es.display_name(exercise), key=f"library_{exercise.id}", width="stretch",
                                 type="primary" if sel == exercise.id else "secondary"):
                        st.session_state["ex_sel"] = exercise.id
                        st.rerun()
    ex = next(e for e in results if e.id == sel)
    with session_scope() as s:
        last = ws.last_sets(s, p.id, ex.id)
    with right:
        exercise_detail(ex, last=last, profile_id=p.id)

with st.expander("Atualizar catálogo a partir das fontes"):
    st.write("ExerciseDB: ~1.500 exercícios com GIF (sem chave, com limite de requisições; leva ~1–2 min). "
             "wger: exercícios com imagens e vídeos sob licença CC-BY-SA (leva ~1 min). WorkoutDB: sem API pública "
             "acessível — integração não implementada.")
    c1, c2 = st.columns(2)
    if c1.button("Sincronizar ExerciseDB"):
        with ui.loading("Baixando…"), session_scope() as s:
            _, msg = es.sync_exercisedb(s)
        st.info(msg)
    if c2.button("Importar do wger"):
        with ui.loading("Baixando…"), session_scope() as s:
            _, msg = es.sync_wger(s)
        st.info(msg)
