"""Perfil ativo e acesso ao banco a partir das páginas."""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from database.connection import session_scope
from database.models import Profile

KEY = "profile_id"


def current_profile_id() -> int | None:
    pid = st.session_state.get(KEY)
    if pid is None:
        qp = st.query_params.get("perfil")
        if not (qp and qp.isdigit()):
            try:
                qp = st.context.cookies.get("fitos_perfil")
            except Exception:  # noqa: BLE001
                qp = None
        if qp and qp.isdigit():
            pid = int(qp)
            st.session_state[KEY] = pid
    return pid


def set_profile(pid: int | None) -> None:
    st.session_state[KEY] = pid
    if pid is None:
        st.query_params.pop("perfil", None)
    else:
        st.query_params["perfil"] = str(pid)
        st.session_state["_cookie_perfil"] = pid


def remember_profile_cookie() -> None:
    """Grava no navegador o último perfil escolhido (cada aparelho lembra o seu)."""
    pid = st.session_state.pop("_cookie_perfil", None)
    if pid is not None:
        components.html(f"<script>parent.document.cookie='fitos_perfil={int(pid)};path=/;max-age=31536000;"
                        "SameSite=Lax';</script>", height=0)


def load_profile() -> Profile | None:
    pid = current_profile_id()
    if pid is None:
        return None
    with session_scope() as s:
        return s.get(Profile, pid)


def require_profile() -> Profile:
    p = load_profile()
    if p is None:
        st.info("Crie ou selecione um perfil na barra lateral.")
        st.stop()
    return p


def flash(msg: str, kind: str = "success") -> None:
    st.session_state.setdefault("_flash", []).append((kind, msg))


def show_flash() -> None:
    for kind, msg in st.session_state.pop("_flash", []):
        getattr(st, kind)(msg)
