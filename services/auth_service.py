"""Códigos de acesso por perfil e sessão assinada no navegador.

- O código de cada perfil é guardado como PBKDF2-SHA256 com sal; nunca em texto.
- O cookie de sessão é "<id>.<assinatura>". A assinatura inclui o hash do código do perfil:
  trocar o código derruba as sessões antigas daquele perfil.
- Perfis antigos sem código entram com o código da instalação (FITOS_ACCESS_CODE).
- Erros seguidos bloqueiam o perfil por alguns minutos (memória do processo).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

ITERATIONS = 200_000
MIN_LEN, MAX_LEN = 4, 32
MAX_FAILURES, LOCK_SECONDS = 5, 300


def validate_new_code(code: str) -> str:
    code = (code or "").strip()
    if not MIN_LEN <= len(code) <= MAX_LEN:
        raise ValueError(f"O código precisa ter de {MIN_LEN} a {MAX_LEN} caracteres.")
    return code


def hash_code(code: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2${ITERATIONS}${salt}${digest}"


def verify_code(stored: str | None, code: str) -> bool:
    try:
        _, iterations, salt, digest = (stored or "").split("$")
        calc = hashlib.pbkdf2_hmac("sha256", (code or "").strip().encode(), bytes.fromhex(salt), int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(calc.hex(), digest)


def can_enter(access_hash: str | None, code: str, install_code: str) -> bool:
    """Perfil com código: só o código dele. Perfil antigo: o código da instalação (ou livre, se não houver)."""
    if access_hash:
        return verify_code(access_hash, code)
    if install_code:
        return hmac.compare_digest((code or "").strip(), install_code)
    return True


def session_token(profile_id: int, access_hash: str | None, secret: str) -> str:
    sig = hmac.new(secret.encode(), f"{profile_id}:{access_hash or ''}".encode(), hashlib.sha256).hexdigest()
    return f"{profile_id}.{sig}"


def profile_from_token(token: str | None, hashes: dict[int, str | None], secret: str) -> int | None:
    pid_txt, _, _ = (token or "").partition(".")
    if not pid_txt.isdigit() or int(pid_txt) not in hashes:
        return None
    pid = int(pid_txt)
    return pid if hmac.compare_digest(token, session_token(pid, hashes[pid], secret)) else None


class Attempts:
    """Contagem de erros por perfil; bloqueia após MAX_FAILURES erros seguidos."""

    def __init__(self, clock=time.monotonic):
        self._clock, self._data = clock, {}

    def locked_for(self, profile_id: int) -> int:
        failures, until = self._data.get(profile_id, (0, 0.0))
        return max(0, int(until - self._clock())) if failures >= MAX_FAILURES else 0

    def fail(self, profile_id: int) -> None:
        failures, _ = self._data.get(profile_id, (0, 0.0))
        failures += 1
        self._data[profile_id] = (failures, self._clock() + LOCK_SECONDS if failures >= MAX_FAILURES else 0.0)

    def reset(self, profile_id: int) -> None:
        self._data.pop(profile_id, None)
