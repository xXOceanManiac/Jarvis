from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path

import mss

from camera_input import CameraInput
from hand_tracker import HandTracker
from gesture_engine import GestureEngine
from mouse_router import MouseRouter
from overlay_hud import OverlayState, run_overlay


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / 'models' / 'hand_landmarker.task'
SCREENSHOT_DIR = PROJECT_ROOT / 'screenshots'


class GestureService:
    def __init__(self):
        self.camera = CameraInput(device_index=0, width=960, height=540)
        self.tracker = HandTracker(model_path=str(MODEL_PATH), num_hands=1)
        self.engine = GestureEngine(stable_frames_required=3)
        self.mouse = MouseRouter(smoothing=0.22)
        self.overlay_state = OverlayState()
        self.active = True
        self.running = True
        self.last_visible_ts = 0.0
        self.last_screenshot_ts = 0.0

    def _save_screenshot(self) -> str:
        from PIL import Image
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = SCREENSHOT_DIR / f'shot_{ts}.png'
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            img = sct.grab(monitor)
            shot = Image.frombytes('RGB', img.size, img.rgb)
            shot.save(path)
        return str(path)

    def _update_overlay(self, **kwargs):
        with self.overlay_state.lock:
            for k, v in kwargs.items():
                setattr(self.overlay_state, k, v)

    def _loop(self):
        self.camera.start()
        self._update_overlay(status='active')
        try:
            while self.running:
                packet = self.camera.read()
                if not packet.ok:
                    self._update_overlay(status='frame_error', visible=False)
                    continue

                hands = self.tracker.process_bgr(packet.frame)
                if not hands:
                    if self.mouse.drag_down:
                        self.mouse.drag_end()
                    if time.time() - self.last_visible_ts > 0.25:
                        self._update_overlay(visible=False, hand_points=[], gesture_name='idle', scroll_delta=0, drag_active=False)
                    time.sleep(0.003)
                    continue

                self.last_visible_ts = time.time()
                hand = hands[0]
                gesture = self.engine.interpret(hand)

                cursor_px = None
                if self.active and gesture.cursor_x is not None and gesture.cursor_y is not None:
                    cursor_px = self.mouse.move_normalized(gesture.cursor_x, gesture.cursor_y)

                if self.active:
                    if gesture.name == 'pinch' and gesture.stable and not self.mouse.drag_down:
                        self.mouse.left_click()

                    if gesture.name == 'drag_hold':
                        self.mouse.drag_start()

                    if gesture.name == 'drag_release':
                        self.mouse.drag_end()

                    if gesture.name == 'scroll' and gesture.scroll_delta:
                        self.mouse.scroll(gesture.scroll_delta)

                    if gesture.screenshot_triggered and time.time() - self.last_screenshot_ts > 1.2:
                        path = self._save_screenshot()
                        self.last_screenshot_ts = time.time()
                        self._update_overlay(screenshot_flash_until=time.time() + 0.15, status=f"saved {os.path.basename(path)}")

                if gesture.name not in ('drag_hold', 'drag_release') and self.mouse.drag_down and gesture.pinch_ratio > 0.42:
                    self.mouse.drag_end()

                self._update_overlay(
                    gesture_name=gesture.name,
                    pinch_ratio=gesture.pinch_ratio,
                    scroll_delta=gesture.scroll_delta,
                    drag_active=self.mouse.drag_down,
                    hand_points=gesture.hand_points,
                    cursor_px=cursor_px,
                    visible=True,
                    status='active',
                )
                time.sleep(0.001)
        finally:
            try:
                self.mouse.drag_end()
            except Exception:
                pass
            self.camera.stop()

    def run(self):
        worker = threading.Thread(target=self._loop, daemon=True)
        worker.start()
        run_overlay(self.overlay_state)
        self.running = False
        worker.join(timeout=1.0)


if __name__ == '__main__':
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f'Missing model file: {MODEL_PATH}')
    GestureService().run()
