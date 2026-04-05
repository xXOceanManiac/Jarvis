
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class WorldModel:
    active_project: str = ""
    active_workspace: str = ""
    active_window_title: str = ""
    active_window_class: str = ""
    room_mode: str = ""
    media_mode: str = ""
    screen_summary: str = ""
    camera_summary: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "active_project": self.active_project,
            "active_workspace": self.active_workspace,
            "active_window_title": self.active_window_title,
            "active_window_class": self.active_window_class,
            "room_mode": self.room_mode,
            "media_mode": self.media_mode,
            "screen_summary": self.screen_summary,
            "camera_summary": self.camera_summary,
            "extra": self.extra,
        }
