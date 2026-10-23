"""Baixa o catálogo ExerciseDB para data/exercisedb.json (metadados apenas)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DATA_DIR  # noqa: E402
from integrations.exercisedb import iter_exercises  # noqa: E402

rows = list(iter_exercises())
(DATA_DIR / "exercisedb.json").write_text(json.dumps(rows, ensure_ascii=False))
print(len(rows))
