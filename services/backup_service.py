"""Backup do SQLite, exportação CSV/JSON e exclusão de dados."""
from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from config.settings import BACKUP_DIR, DATABASE_URL
from database.connection import get_engine
from database.models import Profile

# tabelas com profile_id direto
PROFILE_TABLES = ["measurements", "workout_plans", "workout_sessions", "day_overrides", "meal_plans", "recipes",
                  "inventory_items", "shopping_lists", "purchases", "ai_conversations", "ai_insights", "ai_usage",
                  "meal_logs", "monthly_budgets"]


def db_path() -> Path:
    return Path(DATABASE_URL.removeprefix("sqlite:///"))


def backup_now(keep: int = 20) -> Path:
    """Cópia consistente via API de backup do SQLite (funciona com o app aberto)."""
    dest = BACKUP_DIR / f"fitos-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(db_path())
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    olds = sorted(BACKUP_DIR.glob("fitos-*.db"))
    for old in olds[:-keep]:
        old.unlink()
    return dest


def list_backups() -> list[Path]:
    return sorted(BACKUP_DIR.glob("fitos-*.db"), reverse=True)


def auto_backup_if_due(hours: int = 24) -> Path | None:
    b = list_backups()
    if b and (datetime.now() - datetime.fromtimestamp(b[0].stat().st_mtime)).total_seconds() < hours * 3600:
        return None
    return backup_now()


def _tables() -> list[str]:
    return [t for t in inspect(get_engine()).get_table_names() if t != "alembic_version"]


def _profile_frames(profile_id: int | None) -> dict[str, pd.DataFrame]:
    eng = get_engine()
    out = {}
    with eng.connect() as c:
        for t in _tables():
            if profile_id is not None and t in PROFILE_TABLES:
                q = text(f'SELECT * FROM "{t}" WHERE profile_id = :p')
                out[t] = pd.read_sql(q, c, params={"p": profile_id})
            elif profile_id is not None and t == "profiles":
                out[t] = pd.read_sql(text('SELECT * FROM profiles WHERE id = :p'), c, params={"p": profile_id})
            elif profile_id is None or t in ("products", "price_quotes", "establishments"):
                out[t] = pd.read_sql(text(f'SELECT * FROM "{t}"'), c)
    return out


def export_zip(profile_id: int | None, fmt: str = "csv") -> bytes:
    """ZIP com uma planilha CSV (ou JSON) por tabela. Com profile_id, só os dados daquele perfil e os preços."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in _profile_frames(profile_id).items():
            if name in ("foods", "food_nutrients", "exercises") and profile_id is not None:
                continue
            if fmt == "json":
                z.writestr(f"{name}.json", df.to_json(orient="records", force_ascii=False, date_format="iso", indent=1))
            else:
                z.writestr(f"{name}.csv", df.to_csv(index=False))
        z.writestr("LEIA-ME.txt", "Exportação do FitOS. Valores monetários em reais; pesos em kg; porções em g.\n")
    return buf.getvalue()


def delete_profile(s: Session, profile_id: int) -> None:
    """Apaga o perfil e tudo que pertence a ele (cascata). Faz backup antes."""
    backup_now()
    p = s.get(Profile, profile_id)
    if p:
        s.delete(p)


def delete_profile_section(s: Session, profile_id: int, table: str) -> int:
    if table not in PROFILE_TABLES:
        raise ValueError("Tabela não permitida.")
    backup_now()
    res = s.execute(text(f'DELETE FROM "{table}" WHERE profile_id = :p'), {"p": profile_id})
    return res.rowcount or 0


def profile_count(s: Session) -> int:
    return len(list(s.scalars(select(Profile.id))))
