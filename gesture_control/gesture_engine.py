from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Optional, List


WRIST = 0
THUMB_TIP = 4
INDEX_PIP = 6
INDEX_TIP = 8
MIDDLE_PIP = 10
MIDDLE_TIP = 12
RING_PIP = 14
RING_TIP = 16
PINKY_PIP = 18
PINKY_TIP = 20


HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(17,18),(18,19),(19,20),
    (0,17)
]


def dist(a, b) -> float:
    return sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)


@dataclass
class GestureState:
    name: str = "idle"
    cursor_x: Optional[float] = None
    cursor_y: Optional[float] = None
    confidence: float = 0.0
    pinch_ratio: float = 999.0
    scroll_delta: int = 0
    drag_active: bool = False
    screenshot_triggered: bool = False
    hand_points: List[tuple[float, float]] = field(default_factory=list)
    stable: bool = False
    visible: bool = False


class GestureEngine:
    def __init__(self, stable_frames_required: int = 3):
        self.stable_frames_required = stable_frames_required
        self.last_name = None
        self.same_count = 0
        self.drag_active = False
        self.screenshot_armed = True
        self.prev_scroll_y = None

    def _finger_extended(self, pts, tip_idx: int, pip_idx: int) -> bool:
        return pts[tip_idx].y < pts[pip_idx].y

    def interpret(self, hand) -> GestureState:
        pts = hand.landmarks
        thumb_tip = pts[THUMB_TIP]
        index_tip = pts[INDEX_TIP]
        middle_tip = pts[MIDDLE_TIP]
        wrist = pts[WRIST]

        hand_scale = max(dist(wrist, middle_tip), 1e-6)
        pinch_ratio = dist(thumb_tip, index_tip) / hand_scale

        index_extended = self._finger_extended(pts, INDEX_TIP, INDEX_PIP)
        middle_extended = self._finger_extended(pts, MIDDLE_TIP, MIDDLE_PIP)
        ring_extended = self._finger_extended(pts, RING_TIP, RING_PIP)
        pinky_extended = self._finger_extended(pts, PINKY_TIP, PINKY_PIP)

        cursor_x = index_tip.x
        cursor_y = index_tip.y
        scroll_delta = 0
        screenshot_triggered = False

        screenshot_pose = index_extended and middle_extended and ring_extended and not pinky_extended and pinch_ratio > 0.45
        if screenshot_pose and self.screenshot_armed:
            screenshot_triggered = True
            self.screenshot_armed = False
        elif not screenshot_pose:
            self.screenshot_armed = True

        scroll_mode = index_extended and middle_extended and not ring_extended and not pinky_extended and pinch_ratio > 0.45

        if scroll_mode:
            center_y = (index_tip.y + middle_tip.y) / 2.0
            if self.prev_scroll_y is not None:
                delta = self.prev_scroll_y - center_y
                if abs(delta) > 0.0035:
                    scroll_delta = int(delta * 2500)
            self.prev_scroll_y = center_y
            name = "scroll"
            confidence = 0.85
        else:
            self.prev_scroll_y = None
            if pinch_ratio < 0.28:
                name = "drag_hold" if self.drag_active else "pinch"
                confidence = max(0.0, 1.0 - pinch_ratio)
            elif self.drag_active and pinch_ratio < 0.42:
                name = "drag_hold"
                confidence = 0.85
            elif self.drag_active and pinch_ratio >= 0.42:
                name = "drag_release"
                confidence = 0.95
            else:
                name = "point"
                confidence = 0.8

        if name == self.last_name:
            self.same_count += 1
        else:
            self.last_name = name
            self.same_count = 1

        stable = self.same_count >= self.stable_frames_required

        if name in ("pinch", "drag_hold") and stable and self.same_count >= 8:
            self.drag_active = True
            name = "drag_hold"
        elif name == "drag_release" and stable:
            self.drag_active = False
            self.same_count = 0
            self.last_name = "point"

        return GestureState(
            name=name,
            cursor_x=cursor_x,
            cursor_y=cursor_y,
            confidence=confidence,
            pinch_ratio=pinch_ratio,
            scroll_delta=scroll_delta,
            drag_active=self.drag_active,
            screenshot_triggered=screenshot_triggered,
            hand_points=[(p.x, p.y) for p in pts],
            stable=stable,
            visible=True,
        )
