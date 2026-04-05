from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from config import BASE_DIR

MEMORY_DIR = BASE_DIR / "memory_v2"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def norm_text(value: str) -> str:
    value = str(value or "").strip().lower()
    for ch in ["_", "-", "/", "."]:
        value = value.replace(ch, " ")
    return " ".join(value.split())
