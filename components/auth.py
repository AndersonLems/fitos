"""Portão de acesso por código (FITOS_ACCESS_CODE), necessário quando o app passa pelo túnel.

Não é um sistema de contas: um único código para a instalação. O navegador guarda um cookie
assinado por 30 dias para não pedir o código a cada recarga.
"""
from __future__ import annotations

import hashlib
import hmac

import streamlit as st
import streamlit.components.v1 as components

from config.settings import ACCESS_CODE

COOKIE = "fitos_acesso"


def _token() -> str:
    return hmac.new(ACCESS_CODE.encode(), b"fitos-acesso-v1", hashlib.sha256).hexdigest()


def gate() -> None:
    if not ACCESS_CODE:
        return
    if st.session_state.get("_acesso_ok"):
        if st.session_state.pop("_gravar_cookie", False):
            components.html(
                "<script>const s=parent.location.protocol==='https:'?';Secure':'';"
                f"parent.document.cookie='{COOKIE}={_token()};path=/;max-age=2592000;SameSite=Lax'+s;</script>",
                height=0)
        return
    try:
        cookie = st.context.cookies.get(COOKIE)
    except Exception:  # noqa: BLE001
        cookie = None
    if cookie and hmac.compare_digest(cookie, _token()):
        st.session_state["_acesso_ok"] = True
        return
    st.html('<div class="fx-head"><div class="fx-kicker">Acesso</div><h1>FitOS</h1>'
            "<p>Esta instalação é pessoal. Informe o código de acesso definido no arquivo .env.</p></div>")
    with st.form("acesso", border=False):
        code = st.text_input("Código de acesso", type="password")
        ok = st.form_submit_button("Entrar", type="primary")
    if ok:
        if hmac.compare_digest(code.strip(), ACCESS_CODE):
            st.session_state["_acesso_ok"] = True
            st.session_state["_gravar_cookie"] = True
            st.rerun()
        else:
            st.error("Código incorreto.")
    st.stop()
