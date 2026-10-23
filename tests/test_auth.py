"""Códigos por perfil, sessão assinada e bloqueio por tentativas."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from services import auth_service as auth


def test_hash_and_verify():
    h = auth.hash_code("1234")
    assert h.startswith("pbkdf2$") and "1234" not in h
    assert auth.verify_code(h, "1234") and auth.verify_code(h, " 1234 ")
    assert not auth.verify_code(h, "1235") and not auth.verify_code(None, "1234")
    assert auth.hash_code("1234") != h  # sal diferente a cada vez


def test_validate_new_code():
    assert auth.validate_new_code(" abcd ") == "abcd"
    for bad in ("", "123", "x" * 33):
        with pytest.raises(ValueError):
            auth.validate_new_code(bad)


def test_can_enter_rules():
    h = auth.hash_code("perfil1")
    assert auth.can_enter(h, "perfil1", "instalacao")
    assert not auth.can_enter(h, "instalacao", "instalacao")  # com código próprio, o da instalação não abre
    assert auth.can_enter(None, "instalacao", "instalacao")  # perfil antigo usa o da instalação
    assert not auth.can_enter(None, "errado", "instalacao")
    assert auth.can_enter(None, "", "")  # uso local sem códigos


def test_session_token_roundtrip_and_invalidation():
    h1 = auth.hash_code("aaaa")
    token = auth.session_token(7, h1, "segredo")
    assert auth.profile_from_token(token, {7: h1}, "segredo") == 7
    assert auth.profile_from_token(token, {7: auth.hash_code("bbbb")}, "segredo") is None  # código trocado
    assert auth.profile_from_token(token, {7: h1}, "outro") is None
    assert auth.profile_from_token(token.replace("7.", "8.", 1), {7: h1, 8: h1}, "segredo") is None
    assert auth.profile_from_token(token, {}, "segredo") is None
    assert auth.profile_from_token(None, {7: h1}, "segredo") is None


def test_attempts_lock_and_release():
    now = [0.0]
    a = auth.Attempts(clock=lambda: now[0])
    for _ in range(auth.MAX_FAILURES - 1):
        a.fail(1)
    assert a.locked_for(1) == 0
    a.fail(1)
    assert a.locked_for(1) > 0 and a.locked_for(2) == 0
    now[0] += auth.LOCK_SECONDS + 1
    assert a.locked_for(1) == 0
    a.reset(1)
    a.fail(1)
    assert a.locked_for(1) == 0


def test_login_screen_flow(tmp_path):
    env = dict(os.environ, FITOS_DATABASE_URL=f"sqlite:///{tmp_path / 'auth.db'}", FITOS_ACCESS_CODE="instalacao",
               FITOS_SECRET="teste", GEMINI_API_KEY="", FITOS_UI_TEST_DIR=str(tmp_path))
    result = subprocess.run([sys.executable, str(Path(__file__).parent / "auth_flow_runner.py")],
                            env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
