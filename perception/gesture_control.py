
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

try:
    import cv2
    import mediapipe as mp
except Exception:  # pragma: no cover
    cv2 = None
    mp = None

@dataclass
class GestureEvent:
    kind: str
    confidence: float
    data: dict[str, Any]

class GestureController:
    """
    V5.1 scaffold for cursor and HUD gesture control.
    This file is included now so the architecture has a dedicated place for:
    - open palm / wake
    - pinch / select
    - swipe / change panel
    - pointer motion / cursor mapping
    """
    def available(self) -> bool:
        return cv2 is not None and mp is not None

    def analyze(self, frame) -> list[GestureEvent]:
        return []
