"""Engine, sessões e migrações do SQLite."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import DATABASE_URL, ROOT


def _make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        if ":memory:" not in url:
            cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


@lru_cache(maxsize=None)
def get_engine(url: str = DATABASE_URL) -> Engine:
    return _make_engine(url)


@lru_cache(maxsize=None)
def _factory(url: str) -> sessionmaker:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False, future=True)


@contextmanager
def session_scope(url: str = DATABASE_URL) -> Iterator[Session]:
    s: Session = _factory(url)()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def run_migrations(url: str = DATABASE_URL) -> None:
    """Aplica as migrações Alembic até a versão mais recente."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
