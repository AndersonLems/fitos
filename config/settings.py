"""Configuração central lida do ambiente (.env). Segredos nunca vão para o banco."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
BACKUP_DIR = ROOT / "backups"
LOG_DIR = ROOT / "logs"
ASSETS_DIR = ROOT / "assets"
PHOTO_DIR = DATA_DIR / "fotos"

for _d in (DATA_DIR, BACKUP_DIR, LOG_DIR, PHOTO_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _db_url() -> str:
    url = os.getenv("FITOS_DATABASE_URL", "sqlite:///data/fitos.db")
    # caminhos relativos são resolvidos a partir da raiz do projeto
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        url = f"sqlite:///{ROOT / url.removeprefix('sqlite:///')}"
    return url


DATABASE_URL = _db_url()
GEMINI_MODEL_DEFAULT = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
ACCESS_CODE = os.getenv("FITOS_ACCESS_CODE", "").strip()


def gemini_api_key() -> str | None:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return key or None


class _SecretFilter(logging.Filter):
    """Remove a chave da API de qualquer mensagem de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        key = gemini_api_key()
        if key:
            msg = record.getMessage()
            if key in msg:
                record.msg = msg.replace(key, "***")
                record.args = ()
        return True


def setup_logging() -> logging.Logger:
    log = logging.getLogger("fitos")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    h = RotatingFileHandler(LOG_DIR / "fitos.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    h.addFilter(_SecretFilter())
    log.addHandler(h)
    return log


logger = setup_logging()
