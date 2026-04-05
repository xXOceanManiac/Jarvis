from __future__ import annotations

import time
import pyautogui


class MouseRouter:
    def __init__(self, smoothing: float = 0.22):
        self.screen_w, self.screen_h = pyautogui.size()
        self.smoothing = smoothing
        self.last_x = self.screen_w / 2
        self.last_y = self.screen_h / 2
        self.last_click_ts = 0.0
        self.drag_down = False
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0

    def move_normalized(self, nx: float, ny: float) -> tuple[int, int]:
        target_x = int((1.0 - nx) * self.screen_w)
        target_y = int(ny * self.screen_h)
        sx = self.last_x + (target_x - self.last_x) * self.smoothing
        sy = self.last_y + (target_y - self.last_y) * self.smoothing
        pyautogui.moveTo(int(sx), int(sy), duration=0)
        self.last_x = sx
        self.last_y = sy
        return int(sx), int(sy)

    def left_click(self, cooldown: float = 0.40) -> bool:
        now = time.time()
        if now - self.last_click_ts < cooldown:
            return False
        pyautogui.click()
        self.last_click_ts = now
        return True

    def drag_start(self) -> bool:
        if self.drag_down:
            return False
        pyautogui.mouseDown(button='left')
        self.drag_down = True
        return True

    def drag_end(self) -> bool:
        if not self.drag_down:
            return False
        pyautogui.mouseUp(button='left')
        self.drag_down = False
        return True

    def scroll(self, amount: int) -> None:
        if amount:
            pyautogui.scroll(amount)
