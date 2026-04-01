from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from config import BASE_DIR, VISUAL_STATE_PATH
from utils import log_event


class VisualStateController:
    VALID_STATES = {"idle", "armed", "listening", "processing", "speaking"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "idle"
        self._overlay_proc: subprocess.Popen | None = None
        self._overlay_script = Path(__file__).resolve().parent / "visual_overlay.py"

        self._ensure_overlay()

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

        self._ensure_overlay()
        self._write_state(state)
        log_event("visual_state", {"state": state})

    def _ensure_overlay(self) -> None:
        if self._overlay_proc and self._overlay_proc.poll() is None:
            return

        if not self._overlay_script.exists():
            log_event("visual_overlay_missing", {"path": str(self._overlay_script)})
            return

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        try:
            self._overlay_proc = subprocess.Popen(
                [sys.executable, str(self._overlay_script)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        except Exception as e:
            log_event("visual_overlay_launch_error", {"error": str(e)})

    def _write_state(self, state: str) -> None:
        try:
            VISUAL_STATE_PATH.write_text(json.dumps({"state": state}), encoding="utf-8")
        except Exception as e:
            log_event("visual_state_write_error", {"error": str(e)})
