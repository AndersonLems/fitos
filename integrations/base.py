"""Infra comum das integrações externas."""
from __future__ import annotations

import time

import httpx

from config.settings import logger

USER_AGENT = "FitOS/1.0 (uso pessoal)"


class IntegrationUnavailable(RuntimeError):
    """A fonte externa não respondeu ou não está acessível sem credenciais."""


def get_json(client: httpx.Client, url: str, params: dict | None = None, *, retries: int = 6) -> dict:
    last = None
    for attempt in range(retries):
        try:
            r = client.get(url, params=params)
        except httpx.HTTPError as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429:  # limite de requisições: espera crescente
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code >= 400:
            raise IntegrationUnavailable(f"{url} respondeu HTTP {r.status_code}")
        return r.json()
    logger.warning("integração indisponível: %s (%s)", url, last)
    raise IntegrationUnavailable(f"{url} indisponível após {retries} tentativas")
