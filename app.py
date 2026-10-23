"""FitOS — ponto de entrada. Execute: streamlit run app.py"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="FitOS", page_icon="assets/icone.svg", layout="wide",
                   initial_sidebar_state="auto")

from components import ui  # noqa: E402
from components.auth import gate  # noqa: E402
from components.state import current_profile_id, remember_profile_cookie, set_profile, show_flash  # noqa: E402
from config.settings import logger  # noqa: E402
from database.connection import run_migrations, session_scope  # noqa: E402
from services import profile_service as ps  # noqa: E402
from services.backup_service import auto_backup_if_due  # noqa: E402
from services.seed import seed_all  # noqa: E402


@st.cache_resource(show_spinner="Preparando o banco de dados…")
def bootstrap() -> dict:
    run_migrations()
    with session_scope() as s:
        out = seed_all(s)
    try:
        auto_backup_if_due()
    except Exception as exc:  # noqa: BLE001
        logger.warning("backup automático falhou: %s", exc)
    return out


ui.inject_css()
bootstrap()
gate()


def onboarding() -> None:
    ui.page_header("Comece pelo básico", "Idade, peso e altura bastam para criar o perfil. Os demais dados "
                   "(objetivo, atividade, dias de treino, restrições…) podem ser preenchidos depois em Meu Perfil; "
                   "até lá, as estimativas aparecem marcadas como provisórias.", kicker="Novo perfil")
    with st.form("onboarding"):
        name = st.text_input("Nome do perfil", placeholder="Ex.: Anderson")
        c1, c2, c3 = st.columns(3)
        age = c1.number_input("Idade (anos)", 12, 100, value=None, step=1)
        weight = c2.number_input("Peso atual (kg)", 30.0, 300.0, value=None, step=0.1, format="%.1f")
        height = c3.number_input("Altura (cm)", 120.0, 230.0, value=None, step=0.5, format="%.1f")
        ok = st.form_submit_button("Criar perfil", type="primary")
    if ok:
        if None in (age, weight, height) or not name.strip():
            st.error("Preencha nome, idade, peso e altura.")
            return
        try:
            with session_scope() as s:
                p = ps.create_profile(s, name, age, weight, height)
                pid = p.id
        except ValueError as exc:
            st.error(str(exc))
            return
        set_profile(pid)
        st.session_state.pop("_novo_perfil", None)
        st.rerun()


with session_scope() as _s:
    profiles = [(p.id, p.name) for p in ps.list_profiles(_s)]

pid = current_profile_id()
if pid not in {p[0] for p in profiles}:
    pid = profiles[0][0] if profiles else None
    set_profile(pid)

st.logo("assets/logo.svg", size="large", icon_image="assets/icone.svg")
with st.sidebar:
    if profiles:
        ids = [p[0] for p in profiles]
        names = dict(profiles)
        sel = st.selectbox("Perfil", ids, index=ids.index(pid), format_func=lambda i: names[i])
        if sel != pid:
            set_profile(sel)
            st.rerun()
        if st.button("Novo perfil", width="stretch"):
            st.session_state["_novo_perfil"] = True
            st.rerun()

if not profiles or st.session_state.get("_novo_perfil"):
    if profiles and st.button("Cancelar"):
        st.session_state.pop("_novo_perfil", None)
        st.rerun()
    onboarding()
    st.stop()

show_flash()
remember_profile_cookie()

pages = {
    "": [st.Page("views/dashboard.py", title="Painel", default=True)],
    "Treino": [st.Page("views/treinos.py", title="Meus treinos", url_path="treinos"),
               st.Page("views/biblioteca.py", title="Biblioteca de exercícios", url_path="biblioteca")],
    "Alimentação": [st.Page("views/plano_alimentar.py", title="Meu plano alimentar", url_path="plano-alimentar"),
                    st.Page("views/mercado.py", title="Mercado inteligente", url_path="mercado"),
                    st.Page("views/despensa.py", title="Minha despensa", url_path="despensa")],
    "Você": [st.Page("views/evolucao.py", title="Minha evolução", url_path="evolucao"),
             st.Page("views/personal_ia.py", title="Meu personal IA", url_path="personal-ia"),
             st.Page("views/perfil.py", title="Meu perfil", url_path="perfil"),
             st.Page("views/configuracoes.py", title="Configurações", url_path="configuracoes")],
}
st.navigation(pages, position="sidebar").run()

with st.sidebar:
    st.html('<p class="fx-note" style="margin-top:18px">Estimativas para planejamento pessoal. O FitOS e o Gemini '
            "não substituem médico, nutricionista ou profissional de educação física.</p>")
