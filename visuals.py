from __future__ import annotations

import json
import threading

from config import VISUAL_STATE_PATH
from utils import log_event


class VisualStateController:
    VALID_STATES = {"idle", "armed", "listening", "processing", "speaking"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "idle"
        self._write_state("armed")

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def set_state(self, state: str) -> None:
        state = state.strip().lower()
        if state not in self.VALID_STATES:
            return

        with self._lock:
            if state == self._state:
                return
            self._state = state

        self._write_state(state)
        log_event("visual_state", {"state": state})

    def _write_state(self, state: str) -> None:
        try:
            VISUAL_STATE_PATH.write_text(
                json.dumps({"state": state}),
                encoding="utf-8",
            )
        except Exception as e:
            log_event("visual_state_write_error", {"error": str(e)})
