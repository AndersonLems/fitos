"""wger (https://wger.de/api/v2).

Avaliação (out/2026):
- API REST aberta para leitura, sem chave; ~930 exercícios.
- Licença dos dados e mídias: Creative Commons BY-SA (3.0/4.0) com autor por item,
  o que permite cache local com atribuição. Ainda assim o FitOS só guarda as URLs.
- Vídeos são poucos (~80) e muitos estão em HEVC/.MOV, que nem todo navegador reproduz.
- Traduções em português (language=7) existem para parte dos exercícios.
"""
from __future__ import annotations

import html
import re
import time
from typing import Iterator

import httpx

from .base import USER_AGENT, get_json

BASE_URL = "https://wger.de/api/v2"
SOURCE = "wger"
LANG_PT, LANG_EN = 7, 2


def iter_exercises(pause: float = 0.6, only_with_media: bool = True) -> Iterator[dict]:
    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}) as c:
        url, params = f"{BASE_URL}/exerciseinfo/", {"limit": 100, "offset": 0}
        while url:
            data = get_json(c, url, params)
            for row in data.get("results", []):
                if only_with_media and not (row.get("images") or row.get("videos")):
                    continue
                yield row
            url, params = data.get("next"), None
            time.sleep(pause)


def _strip(text: str | None) -> str | None:
    if not text:
        return None
    text = re.sub(r"<li>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip() or None


def normalize(raw: dict) -> dict | None:
    tr = {t["language"]: t for t in raw.get("translations", [])}
    en, pt = tr.get(LANG_EN), tr.get(LANG_PT)
    if not (en or pt):
        return None
    main_img = next((i for i in raw.get("images", []) if i.get("is_main")), (raw.get("images") or [None])[0])
    video = (raw.get("videos") or [None])[0]
    lic = raw.get("license") or {}
    authors = ", ".join(raw.get("total_authors_history") or []) or raw.get("license_author") or "wger.de"
    muscles = raw.get("muscles") or []
    return {
        "source": SOURCE,
        "source_id": str(raw["id"]),
        "name_original": (en or pt)["name"],
        "name_pt": pt["name"] if pt else None,
        "body_part": (raw.get("category") or {}).get("name", "").lower() or None,
        "primary_muscle": (muscles[0].get("name_en") or muscles[0].get("name")) if muscles else None,
        "secondary_muscles": [m.get("name_en") or m.get("name") for m in raw.get("muscles_secondary", [])] or None,
        "equipment": ", ".join(e["name"].lower() for e in raw.get("equipment", [])) or "bodyweight",
        "instructions": _strip((pt or en).get("description")),
        "gif_url": main_img["image"] if main_img else None,
        "video_url": video["video"] if video else None,
        "media_source": "wger.de",
        "license": lic.get("short_name") or "CC-BY-SA",
        "attribution": f"wger.de — {authors[:200]}",
    }
