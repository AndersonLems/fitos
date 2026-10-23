"""Perfil ativo e acesso ao banco a partir das páginas."""
from __future__ import annotations

import streamlit as st

from database.connection import session_scope
from database.models import Profile

KEY = "profile_id"  # gravado por components.auth após a entrada


def current_profile_id() -> int | None:
    return st.session_state.get(KEY)


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
