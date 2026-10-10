"""Small persistent UI state; the photo catalog and identities live separately."""
from __future__ import annotations

import json
from pathlib import Path

from core import app_data

DEFAULTS = {"last_folder": "", "faces_analyzed": False, "last_tab": 2,
            "last_person_id": "", "count_filter": "Todos"}


def load_settings():
    path = app_data() / "preferencias.json"
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            return DEFAULTS.copy()
    except (OSError, ValueError):
        return DEFAULTS.copy()
    result = DEFAULTS.copy()
    for key, default in DEFAULTS.items():
        value = stored.get(key)
        if isinstance(value, type(default)):
            result[key] = value
    if not 0 <= result["last_tab"] <= 5:
        result["last_tab"] = 2
    if result["count_filter"] not in ("Todos", "0 rostros", "1 rostro", "2 rostros", "3 o más"):
        result["count_filter"] = "Todos"
    return result


def save_settings(settings):
    path = app_data() / "preferencias.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
