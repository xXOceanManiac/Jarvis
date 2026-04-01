from __future__ import annotations

import json
import math
from pathlib import Path

from PyQt6.QtCore import QPointF, QTimer, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

STATE_FILE = Path.home() / ".jarvis" / "visual_state.json"


class Overlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.state = "idle"
        self.phase = 0.0

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )

        # Wider, cleaner footprint that feels closer to a cinematic HUD.
        self.resize(440, 210)
        self.reposition()

        self.anim = QTimer(self)
        self.anim.timeout.connect(self._tick)
        self.anim.start(16)

        self.state_timer = QTimer(self)
        self.state_timer.timeout.connect(self._read_state)
        self.state_timer.start(50)

    def reposition(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + geo.height() - self.height() - 26
        self.move(x, y)

    def _tick(self) -> None:
        self.phase += 0.07
        self.update()

    def _read_state(self) -> None:
        try:
            raw = STATE_FILE.read_text(encoding="utf-8")
            state = json.loads(raw).get("state", "idle")
        except Exception:
            state = "idle"

        if state != self.state:
            self.state = state
            if state == "idle":
                self.hide()
            else:
                self.show()
                self.raise_()
                self.reposition()

    def _state_color(self) -> QColor:
        if self.state == "armed":
            return QColor(70, 205, 255, 220)
        if self.state == "listening":
            return QColor(120, 230, 255, 245)
        if self.state == "processing":
            return QColor(140, 170, 255, 240)
        if self.state == "speaking":
            return QColor(255, 180, 110, 240)
        return QColor(100, 220, 255, 225)

    def _draw_glow_ring(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        radius: float,
        color: QColor,
        alpha: int,
        width: int,
    ) -> None:
        pen = QPen(QColor(color.red(), color.green(), color.blue(), alpha))
        pen.setWidth(width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

    def _draw_arc_ring(
        self, painter: QPainter, cx: float, cy: float, radius: float, color: QColor
    ) -> None:
        rect_x = cx - radius
        rect_y = cy - radius
        rect_w = radius * 2
        rect_h = radius * 2

        painter.setBrush(Qt.BrushStyle.NoBrush)

        for idx, span_deg in enumerate((44, 28, 18)):
            start_deg = (self.phase * 52 + idx * 110) % 360
            pen = QPen(QColor(color.red(), color.green(), color.blue(), 175 - idx * 28))
            pen.setWidth(3 if idx == 0 else 2)
            painter.setPen(pen)
            painter.drawArc(
                int(rect_x),
                int(rect_y),
                int(rect_w),
                int(rect_h),
                int(-start_deg * 16),
                int(-span_deg * 16),
            )

    def _draw_center_core(
        self, painter: QPainter, cx: float, cy: float, color: QColor
    ) -> None:
        painter.setPen(Qt.PenStyle.NoPen)

        # Outer glow
        for i in range(7, 0, -1):
            glow_r = 8 + i * 5
            glow_alpha = 10 + i * 10
            painter.setBrush(
                QColor(color.red(), color.green(), color.blue(), glow_alpha)
            )
            painter.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        # White hot center
        painter.setBrush(QColor(245, 252, 255, 235))
        painter.drawEllipse(QPointF(cx, cy), 8.5, 8.5)

    def _draw_side_brackets(
        self, painter: QPainter, cx: float, cy: float, color: QColor
    ) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(color.red(), color.green(), color.blue(), 120))
        pen.setWidth(2)
        painter.setPen(pen)

        left_x = cx - 122
        right_x = cx + 122
        top_y = cy - 18
        bot_y = cy + 18
        depth = 22

        # Left
        painter.drawLine(int(left_x), int(top_y), int(left_x + depth), int(top_y))
        painter.drawLine(int(left_x), int(bot_y), int(left_x + depth), int(bot_y))
        painter.drawLine(int(left_x), int(top_y), int(left_x), int(bot_y))

        # Right
        painter.drawLine(int(right_x - depth), int(top_y), int(right_x), int(top_y))
        painter.drawLine(int(right_x - depth), int(bot_y), int(right_x), int(bot_y))
        painter.drawLine(int(right_x), int(top_y), int(right_x), int(bot_y))

    def _draw_waveform(
        self, painter: QPainter, cx: float, cy: float, color: QColor
    ) -> None:
        bar_y = cy + 56
        total_bars = 31
        bar_w = 5
        gap = 5
        full_w = total_bars * bar_w + (total_bars - 1) * gap
        start_x = cx - full_w / 2

        for i in range(total_bars):
            offset = abs(i - total_bars // 2)

            if self.state == "armed":
                wave = math.sin(self.phase * 1.3 + i * 0.22)
                base = 4
                amp = 4
            elif self.state == "listening":
                wave = math.sin(self.phase * 2.2 + i * 0.38)
                base = 8
                amp = 14
            elif self.state == "processing":
                wave = math.sin(self.phase * 3.1 + i * 0.5)
                base = 10
                amp = 10
            else:  # speaking
                wave = math.sin(self.phase * 4.0 + i * 0.48)
                base = 8
                amp = 18

            height = max(3, base + abs(wave) * amp - offset * 0.22)

            x = start_x + i * (bar_w + gap)
            y = bar_y - height / 2

            path = QPainterPath()
            path.addRoundedRect(x, y, bar_w, height, 2.2, 2.2)
            alpha = 72 + int(min(145, height * 5))
            painter.fillPath(
                path, QColor(color.red(), color.green(), color.blue(), alpha)
            )

        baseline = QPainterPath()
        baseline.addRoundedRect(cx - 118, bar_y + 22, 236, 2.5, 1.2, 1.2)
        painter.fillPath(baseline, QColor(color.red(), color.green(), color.blue(), 62))

    def paintEvent(self, event) -> None:
        if self.state == "idle":
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        color = self._state_color()
        cx = self.width() / 2
        cy = self.height() / 2 - 8

        # Soft background aura
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(6, 0, -1):
            r = 78 + i * 18 + math.sin(self.phase + i * 0.3) * 2
            alpha = 6 + i * 5
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), alpha))
            painter.drawEllipse(QPointF(cx, cy), r, r * 0.62)

        # Main ring system
        self._draw_glow_ring(painter, cx, cy, 32, color, 150, 2)
        self._draw_glow_ring(painter, cx, cy, 52, color, 105, 2)
        self._draw_glow_ring(painter, cx, cy, 76, color, 70, 1)
        self._draw_arc_ring(painter, cx, cy, 44, color)
        self._draw_arc_ring(painter, cx, cy, 64, color)

        # Crosshair
        cross_pen = QPen(QColor(color.red(), color.green(), color.blue(), 55))
        cross_pen.setWidth(1)
        painter.setPen(cross_pen)
        painter.drawLine(int(cx - 95), int(cy), int(cx - 24), int(cy))
        painter.drawLine(int(cx + 24), int(cy), int(cx + 95), int(cy))
        painter.drawLine(int(cx), int(cy - 42), int(cx), int(cy - 18))
        painter.drawLine(int(cx), int(cy + 18), int(cx), int(cy + 42))

        self._draw_side_brackets(painter, cx, cy, color)
        self._draw_center_core(painter, cx, cy, color)
        self._draw_waveform(painter, cx, cy, color)


def main() -> None:
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    overlay = Overlay()
    overlay.show()
    app.exec()


if __name__ == "__main__":
    main()
