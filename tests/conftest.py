import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.connection import run_migrations, session_scope  # noqa: E402
from services.seed import seed_foods, seed_products  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    url = f"sqlite:///{tmp_path / 't.db'}"
    run_migrations(url)
    with session_scope(url) as s:
        seed_foods(s)
        s.flush()
        seed_products(s)
    return url


@pytest.fixture()
def s(db):
    with session_scope(db) as sess:
        yield sess
        sess.rollback()
