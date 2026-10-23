"""ExerciseDB (versão open source, https://oss.exercisedb.dev).

Avaliação (out/2026):
- Sem autenticação; ~1.500 exercícios com GIF animado, músculos, equipamento e instruções.
- Paginação por cursor (`after`), máx. 100 itens por página; há limite de taxa (HTTP 429).
- Termos de uso das mídias não definem permissão de redistribuição: o FitOS NÃO faz cache
  local dos GIFs, apenas referencia a URL original com atribuição.
- A ExerciseDB comercial (RapidAPI) exige chave paga e não é usada.
"""
from __future__ import annotations

import time
from typing import Iterator

import httpx

from .base import USER_AGENT, get_json

BASE_URL = "https://oss.exercisedb.dev/api/v1"
SOURCE = "exercisedb"
ATTRIBUTION = "ExerciseDB (exercisedb.dev)"
LICENSE = "Termos de uso ExerciseDB — mídia referenciada, sem cópia local"


def iter_exercises(page_size: int = 100, pause: float = 1.2) -> Iterator[dict]:
    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}) as c:
        after = None
        while True:
            params = {"limit": page_size}
            if after:
                params["after"] = after
            data = get_json(c, f"{BASE_URL}/exercises", params)
            yield from data.get("data", [])
            meta = data.get("meta", {})
            if not meta.get("hasNextPage") or not meta.get("nextCursor"):
                return
            after = meta["nextCursor"]
            time.sleep(pause)


def normalize(raw: dict) -> dict:
    steps = [s.split(" ", 1)[1] if s.lower().startswith("step:") and " " in s else s
             for s in raw.get("instructions") or []]
    targets = raw.get("targetMuscles") or []
    return {
        "source": SOURCE,
        "source_id": raw["exerciseId"],
        "name_original": raw["name"],
        "body_part": (raw.get("bodyParts") or [None])[0],
        "primary_muscle": targets[0] if targets else None,
        "secondary_muscles": (targets[1:] + (raw.get("secondaryMuscles") or [])) or None,
        "equipment": (raw.get("equipments") or [None])[0],
        "instructions": "\n".join(steps) or None,
        "gif_url": raw.get("gifUrl"),
        "media_source": ATTRIBUTION,
        "license": LICENSE,
        "attribution": ATTRIBUTION,
    }
