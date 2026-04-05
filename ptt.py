from __future__ import annotations

import threading
import time
from typing import Callable

from pynput import keyboard

from config import CONFIG
from utils import log_event


class PushToTalkController:
    def __init__(
        self,
        on_activated: Callable[[], None],
        on_released: Callable[[], None],
    ) -> None:
        self.on_activated = on_activated
        self.on_released = on_released

        self.hold_seconds = float(CONFIG.get("ptt_hold_seconds", 0.25))
        self.key_name = str(CONFIG.get("ptt_key", "space")).strip().lower()

        self._listener: keyboard.Listener | None = None
        self._monitor_thread: threading.Thread | None = None
        self._running = False

        self._lock = threading.Lock()
        self._pressed = False
        self._press_started_at = 0.0
        self._activated = False

    def start(self) -> None:
        if self._running:
            return

        self._running = True

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        log_event(
            "ptt_started", {"key": self.key_name, "hold_seconds": self.hold_seconds}
        )

    def stop(self) -> None:
        self._running = False
        if self._listener:
            self._listener.stop()
            self._listener = None
        log_event("ptt_stopped", {})

    def is_pressed(self) -> bool:
        with self._lock:
            return self._pressed

    def is_activated(self) -> bool:
        with self._lock:
            return self._activated

    def _matches_ptt_key(self, key) -> bool:
        if self.key_name == "esc":
            return key == keyboard.Key.esc

        if self.key_name == "space":
            return key == keyboard.Key.space

        if self.key_name == "meta":
            return key in {
                keyboard.Key.cmd,
                getattr(keyboard.Key, "cmd_l", None),
                getattr(keyboard.Key, "cmd_r", None),
            }

        if self.key_name == "ctrl":
            return key in {
                keyboard.Key.ctrl,
                getattr(keyboard.Key, "ctrl_l", None),
                getattr(keyboard.Key, "ctrl_r", None),
            }

        if self.key_name == "alt":
            return key in {
                keyboard.Key.alt,
                getattr(keyboard.Key, "alt_l", None),
                getattr(keyboard.Key, "alt_r", None),
            }

        return False

    def _on_press(self, key) -> None:
        if not self._matches_ptt_key(key):
            return

        with self._lock:
            if self._pressed:
                return
            self._pressed = True
            self._press_started_at = time.time()
            self._activated = False

    def _on_release(self, key) -> None:
        if not self._matches_ptt_key(key):
            return

        should_fire_release = False

        with self._lock:
            if self._pressed and self._activated:
                should_fire_release = True

            self._pressed = False
            self._press_started_at = 0.0
            self._activated = False

        if should_fire_release:
            log_event("ptt_released", {})
            self.on_released()

    def _monitor_loop(self) -> None:
        while self._running:
            should_activate = False

            with self._lock:
                if (
                    self._pressed
                    and not self._activated
                    and self._press_started_at > 0
                    and (time.time() - self._press_started_at) >= self.hold_seconds
                ):
                    self._activated = True
                    should_activate = True

            if should_activate:
                log_event("ptt_activated", {})
                self.on_activated()

            time.sleep(0.01)
