"""FitOS — ponto de entrada. Execute: streamlit run app.py"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="FitOS", page_icon="assets/icone.svg", layout="wide",
                   initial_sidebar_state="auto")

from components import ui  # noqa: E402
from components import auth  # noqa: E402
from components.state import show_flash  # noqa: E402
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

pages = {
    "": [st.Page("views/dashboard.py", title="Hoje", icon=":material/dashboard:", default=True)],
    "Treino": [st.Page("views/treinos.py", title="Meus treinos", icon=":material/fitness_center:", url_path="treinos"),
               st.Page("views/biblioteca.py", title="Biblioteca", icon=":material/exercise:", url_path="biblioteca")],
    "Nutrição": [st.Page("views/plano_alimentar.py", title="Plano alimentar", icon=":material/restaurant:", url_path="plano-alimentar"),
                    st.Page("views/mercado.py", title="Mercado inteligente", icon=":material/shopping_cart:", url_path="mercado"),
                    st.Page("views/despensa.py", title="Minha despensa", icon=":material/inventory_2:", url_path="despensa")],
    "Acompanhamento": [st.Page("views/evolucao.py", title="Minha evolução", icon=":material/show_chart:", url_path="evolucao"),
             st.Page("views/personal_ia.py", title="Personal IA", icon=":material/auto_awesome:", url_path="personal-ia")],

    "Conta": [st.Page("views/perfil.py", title="Meu perfil", icon=":material/person:", url_path="perfil"),
             st.Page("views/configuracoes.py", title="Configurações", icon=":material/settings:", url_path="configuracoes")],
}

with session_scope() as _s:
    profiles = ps.list_profiles(_s)

pid = auth.authenticated_profile(profiles)
if pid is None:
    # A navegação é registrada (oculta) para o endereço pedido continuar válido depois da entrada.
    st.navigation(pages, position="hidden")
    auth.login_screen(profiles)
    st.stop()
me = next(p for p in profiles if p.id == pid)

st.logo("assets/logo.svg", size="large", icon_image="assets/icone.svg")
with st.sidebar:
    st.html(f'<div class="fx-me"><span>Perfil</span><strong>{ui.esc(me.name)}</strong></div>')
    if me.access_hash is None:
        st.caption("Sem código próprio ainda. Defina um em Meu perfil.")
    if st.button("Sair", key="sair", width="stretch", icon=":material/logout:", help="Voltar à tela de entrada para trocar de perfil"):
        auth.logout()
        st.rerun()

show_flash()

page = st.navigation(pages, position="sidebar")
ui.app_chrome(page.title, me.name, page.url_path)
page.run()

with st.sidebar:
    st.html('<p class="fx-note" style="margin-top:18px">Estimativas para planejamento pessoal. O FitOS e o Gemini '
            "não substituem médico, nutricionista ou profissional de educação física.</p>")
