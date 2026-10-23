"""Entrada por perfil: cada pessoa escolhe o próprio perfil e digita o código dele.

O navegador guarda um cookie assinado por 30 dias (fitos_sessao). Perfis antigos, criados antes dos
códigos por perfil, entram com o código da instalação (FITOS_ACCESS_CODE) até definirem o seu em
Meu perfil. Criar um perfil novo também pede o código da instalação.
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from config.settings import ACCESS_CODE, SESSION_SECRET
from database.connection import session_scope
from database.models import Profile
from services import auth_service as auth
from services import profile_service as ps

COOKIE = "fitos_sessao"
KEY = "profile_id"


@st.cache_resource
def _attempts() -> auth.Attempts:
    return auth.Attempts()


def _write_cookie(value: str, max_age: int) -> None:
    components.html(
        "<script>const s=parent.location.protocol==='https:'?';Secure':'';"
        f"parent.document.cookie='{COOKIE}={value};path=/;max-age={max_age};SameSite=Lax'+s;</script>", height=0)


def login(profile_id: int, access_hash: str | None) -> None:
    st.session_state[KEY] = profile_id
    st.session_state["_cookie_set"] = auth.session_token(profile_id, access_hash, SESSION_SECRET)
    st.session_state.pop("_logged_out", None)


def logout() -> None:
    for k in (KEY, "_cookie_set", "_flash"):
        st.session_state.pop(k, None)
    # os cookies lidos na abertura da conexão continuam em st.context até recarregar a página
    st.session_state["_logged_out"] = True
    st.session_state["_cookie_clear"] = True


def refresh_cookie(profile_id: int, access_hash: str | None) -> None:
    """Depois de trocar o código, reemite o cookie (a assinatura antiga deixa de valer)."""
    st.session_state["_cookie_set"] = auth.session_token(profile_id, access_hash, SESSION_SECRET)


def authenticated_profile(profiles: list[Profile]) -> int | None:
    hashes = {p.id: p.access_hash for p in profiles}
    pid = st.session_state.get(KEY)
    if pid in hashes:
        token = st.session_state.pop("_cookie_set", None)
        if token:
            _write_cookie(token, 2592000)
        return pid
    st.session_state.pop(KEY, None)
    if not st.session_state.get("_logged_out"):
        try:
            pid = auth.profile_from_token(st.context.cookies.get(COOKIE), hashes, SESSION_SECRET)
        except Exception:  # noqa: BLE001
            pid = None
        if pid is None and not ACCESS_CODE and len(profiles) == 1 and not profiles[0].access_hash:
            pid = profiles[0].id  # uso local, sem códigos configurados
        if pid is not None:
            st.session_state[KEY] = pid
            return pid
    return None


def login_screen(profiles: list[Profile]) -> None:
    if st.session_state.pop("_cookie_clear", False):
        _write_cookie("", 0)
    with st.container(key="login"):
        st.html('<div class="fx-head"><h1>FitOS</h1><p>Cada pessoa entra no próprio perfil com o código dele. '
                "O navegador lembra a entrada por 30 dias.</p></div>")
        if profiles:
            _enter_form(profiles)
        with st.expander("Criar um perfil novo", expanded=not profiles):
            _create_form(first=not profiles)


def _enter_form(profiles: list[Profile]) -> None:
    by = {p.id: p for p in profiles}
    with st.form("entrar"):
        pid = st.selectbox("Perfil", list(by), format_func=lambda i: by[i].name)
        code = st.text_input("Código de acesso", type="password")
        ok = st.form_submit_button("Entrar", type="primary", width="stretch")
    if ACCESS_CODE and any(p.access_hash is None for p in profiles):
        st.caption("Perfil criado antes dos códigos por perfil? Entre com o código da instalação e defina o seu em "
                   "Meu perfil.")
    if not ok:
        return
    wait = _attempts().locked_for(pid)
    if wait:
        st.error(f"Muitas tentativas erradas. Tente de novo em {wait // 60 + 1} min.")
    elif auth.can_enter(by[pid].access_hash, code, ACCESS_CODE):
        _attempts().reset(pid)
        login(pid, by[pid].access_hash)
        st.rerun()
    else:
        _attempts().fail(pid)
        st.error("Código incorreto.")


def _create_form(first: bool) -> None:
    with st.form("novo_perfil"):
        name = st.text_input("Nome", placeholder="Ex.: Anderson")
        c1, c2, c3 = st.columns(3)
        age = c1.number_input("Idade (anos)", 12, 100, value=None, step=1)
        weight = c2.number_input("Peso atual (kg)", 30.0, 300.0, value=None, step=0.1, format="%.1f")
        height = c3.number_input("Altura (cm)", 120.0, 230.0, value=None, step=0.5, format="%.1f")
        c1, c2 = st.columns(2)
        code = c1.text_input("Código de acesso do perfil", type="password",
                             help=f"De {auth.MIN_LEN} a {auth.MAX_LEN} caracteres. É o que essa pessoa vai digitar para entrar.")
        code2 = c2.text_input("Repita o código", type="password")
        install = st.text_input("Código da instalação", type="password",
                                help="FITOS_ACCESS_CODE do arquivo .env; só quem administra o FitOS tem.") \
            if ACCESS_CODE else ""
        st.caption("Os demais dados (objetivo, atividade, dias de treino, restrições…) ficam em Meu perfil; até lá, "
                   "as estimativas aparecem marcadas como provisórias.")
        ok = st.form_submit_button("Criar perfil", type="primary", width="stretch")
    if not ok:
        return
    try:
        if ACCESS_CODE and not auth.can_enter(None, install, ACCESS_CODE):
            raise ValueError("Código da instalação incorreto.")
        if None in (age, weight, height) or not name.strip():
            raise ValueError("Preencha nome, idade, peso e altura.")
        code = auth.validate_new_code(code)
        if code != code2.strip():
            raise ValueError("Os dois códigos não são iguais.")
        with session_scope() as s:
            p = ps.create_profile(s, name, age, weight, height)
            p.access_hash = auth.hash_code(code)
            pid, h = p.id, p.access_hash
    except ValueError as exc:
        st.error(str(exc))
        return
    login(pid, h)
    st.rerun()
