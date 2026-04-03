from __future__ import annotations

import json
import math
import sys
import time
from collections import deque
from pathlib import Path

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import QApplication, QWidget

try:
    import psutil
except Exception:
    psutil = None


STATE_FILE = Path.home() / ".jarvis" / "visual_state.json"
AUDIO_FILE = Path.home() / ".jarvis" / "audio_levels.json"
LOG_DIR = Path.home() / ".jarvis" / "logs"


class Store:
    def __init__(self) -> None:
        self.state = "armed"
        self.mic = 0.0
        self.spk = 0.0
        self.lines: list[str] = []

    def refresh(self) -> None:
        try:
            self.state = json.loads(STATE_FILE.read_text(encoding="utf-8")).get(
                "state", "armed"
            )
        except Exception:
            self.state = "armed"

        try:
            data = json.loads(AUDIO_FILE.read_text(encoding="utf-8"))
            self.mic = float(data.get("mic_level", 0.0))
            self.spk = float(data.get("speaker_level", 0.0))
        except Exception:
            self.mic = self.spk = 0.0

        try:
            files = sorted(LOG_DIR.glob("*.jsonl"))
            if files:
                latest = files[-1]
                out = deque(maxlen=42)
                for raw in latest.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines():
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                        ts = rec.get("ts", "")
                        kind = rec.get("kind", "")
                        rest = {k: v for k, v in rec.items() if k not in {"ts", "kind"}}
                        out.append(f"{ts}  {kind:<18} {json.dumps(rest)[:100]}")
                    except Exception:
                        out.append(raw[:140])
                self.lines = list(out)
        except Exception:
            pass

    @property
    def drive(self) -> float:
        return max(self.mic, self.spk)


class SystemStats:
    def __init__(self) -> None:
        self.cpu = 0.0
        self.mem = 0.0
        self.net_down_kbps = 0.0
        self.net_up_kbps = 0.0
        self.hostname = "local"

        self.cpu_hist = deque([0.0] * 120, maxlen=120)
        self.mem_hist = deque([0.0] * 120, maxlen=120)
        self.down_hist = deque([0.0] * 120, maxlen=120)
        self.up_hist = deque([0.0] * 120, maxlen=120)

        self._last_net = None
        self._last_t = time.time()

        if psutil:
            try:
                import socket

                self.hostname = socket.gethostname()
            except Exception:
                pass
            try:
                self._last_net = psutil.net_io_counters()
            except Exception:
                self._last_net = None

    def refresh(self) -> None:
        now = time.time()

        if psutil:
            try:
                self.cpu = float(psutil.cpu_percent(interval=None))
            except Exception:
                self.cpu = 0.0

            try:
                self.mem = float(psutil.virtual_memory().percent)
            except Exception:
                self.mem = 0.0

            try:
                current = psutil.net_io_counters()
                if self._last_net is not None:
                    dt = max(0.001, now - self._last_t)
                    self.net_down_kbps = max(
                        0.0,
                        (current.bytes_recv - self._last_net.bytes_recv) / 1024.0 / dt,
                    )
                    self.net_up_kbps = max(
                        0.0,
                        (current.bytes_sent - self._last_net.bytes_sent) / 1024.0 / dt,
                    )
                self._last_net = current
            except Exception:
                self.net_down_kbps = 0.0
                self.net_up_kbps = 0.0

            self._last_t = now
        else:
            t = now
            self.cpu = 14 + abs(math.sin(t * 0.7)) * 32
            self.mem = 32 + abs(math.sin(t * 0.21 + 0.8)) * 18
            self.net_down_kbps = 25 + abs(math.sin(t * 1.18)) * 420
            self.net_up_kbps = 5 + abs(math.sin(t * 0.92 + 1.2)) * 120

        self.cpu_hist.append(self.cpu)
        self.mem_hist.append(self.mem)
        self.down_hist.append(min(100.0, self.net_down_kbps / 10.0))
        self.up_hist.append(min(100.0, self.net_up_kbps / 4.0))


class HUDWindow(QWidget):
    def __init__(self, store: Store, stats: SystemStats):
        super().__init__()
        self.store = store
        self.stats = stats

        self.phase = 0.0
        self.orbit_vel = 0.0

        self.drag_active = False
        self.drag_offset = QPoint()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMouseTracking(True)

        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            w = min(1280, geo.width() - 28)
            h = min(900, geo.height() - 28)
            x = geo.center().x() - w // 2
            y = geo.center().y() - h // 2
            self.setGeometry(x, y, w, h)
        else:
            self.resize(1280, 900)

        self.anim = QTimer(self)
        self.anim.timeout.connect(self.tick)
        self.anim.start(16)

    def is_expanded(self) -> bool:
        return self.width() >= 930 and self.height() >= 620

    def color(self) -> QColor:
        if self.store.state == "processing":
            return QColor(150, 110, 255, 255)
        return QColor(34, 224, 255, 255)

    def accent_color(self) -> QColor:
        if self.store.state == "speaking":
            return QColor(255, 188, 110, 255)
        if self.store.state == "processing":
            return QColor(150, 110, 255, 255)
        return QColor(34, 224, 255, 255)

    def target_orbit_speed(self) -> float:
        if self.store.state == "speaking":
            return 0.070 + self.store.drive * 0.085
        if self.store.state == "processing":
            return -0.062
        if self.store.state == "listening":
            return 0.042
        return 0.014

    def tick(self):
        target = self.target_orbit_speed()
        delta = target - self.orbit_vel
        accel = 0.22 if abs(delta) > 0.03 else 0.045
        self.orbit_vel += delta * accel
        self.phase += self.orbit_vel
        self.update()

    def top_tab_rect(self) -> QRectF:
        if self.is_expanded():
            return QRectF(28, 16, 188, 36)
        return QRectF(16, 12, 124, 28)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.top_tab_rect().contains(
            e.position()
        ):
            self.drag_active = True
            self.drag_offset = (
                e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.drag_active:
            self.move(e.globalPosition().toPoint() - self.drag_offset)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self.drag_active = False
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            return
        if e.key() == Qt.Key.Key_F11:
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
            return
        super().keyPressEvent(e)

    def _ring(
        self, p: QPainter, cx: float, cy: float, r: float, alpha: int, width: int
    ):
        c = self.color()
        pen = QPen(QColor(c.red(), c.green(), c.blue(), alpha), width)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

    def _arc(
        self,
        p: QPainter,
        cx: float,
        cy: float,
        r: float,
        start_deg: float,
        span_deg: float,
        alpha: int,
        width: int,
        accent: bool = False,
    ):
        c = self.accent_color() if accent else self.color()
        pen = QPen(QColor(c.red(), c.green(), c.blue(), alpha), width)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(
            QRectF(cx - r, cy - r, r * 2, r * 2),
            int(-start_deg * 16),
            int(-span_deg * 16),
        )

    def _segmented_band(
        self,
        p: QPainter,
        cx: float,
        cy: float,
        r: float,
        segments: int,
        draw_every: int,
        span_deg: float,
        alpha: int,
        width: int,
        offset_deg: float = 0.0,
        speed_mul: float = 1.0,
    ):
        c = self.color()
        pen = QPen(QColor(c.red(), c.green(), c.blue(), alpha), width)
        p.setPen(pen)

        base = math.degrees(self.phase * speed_mul) + offset_deg
        step = 360 / segments

        for i in range(segments):
            if i % draw_every != 0:
                continue
            start = base + i * step
            p.drawArc(
                QRectF(cx - r, cy - r, r * 2, r * 2),
                int(-start * 16),
                int(-span_deg * 16),
            )

    def _tick_band(
        self,
        p: QPainter,
        cx: float,
        cy: float,
        r: float,
        tick_count: int,
        inner: float,
        outer: float,
        alpha: int,
        width: int,
        speed_mul: float = 0.0,
    ):
        c = self.color()
        pen = QPen(QColor(c.red(), c.green(), c.blue(), alpha), width)
        p.setPen(pen)

        for i in range(tick_count):
            if i % 2 != 0:
                continue
            ang = (i / tick_count) * math.tau + self.phase * speed_mul
            x1 = cx + math.cos(ang) * (r - inner)
            y1 = cy + math.sin(ang) * (r - inner)
            x2 = cx + math.cos(ang) * (r + outer)
            y2 = cy + math.sin(ang) * (r + outer)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

    def draw_tab(self, p: QPainter):
        r = self.top_tab_rect()
        c = self.color()

        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)
        p.fillPath(path, QColor(8, 16, 28, 235))

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 170), 2))
        p.drawRoundedRect(r, 9, 9)

        f = QFont()
        f.setBold(True)
        f.setPointSize(9 if self.is_expanded() else 8)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        p.setFont(f)
        p.setPen(QColor(225, 245, 250, 230))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "JARVIS HUD")

    def draw_background(self, p: QPainter, rect: QRectF):
        bg = QPainterPath()
        bg.addRoundedRect(rect.adjusted(3, 3, -3, -3), 20, 20)

        g = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        g.setColorAt(0.0, QColor(3, 7, 12, 252))
        g.setColorAt(0.45, QColor(4, 9, 15, 252))
        g.setColorAt(1.0, QColor(2, 5, 10, 252))
        p.fillPath(bg, g)

        # hard technical grid
        p.setPen(QPen(QColor(90, 150, 190, 12), 1))
        step = 28
        for x in range(int(rect.left()) + 18, int(rect.right()), step):
            p.drawLine(x, int(rect.top()) + 12, x, int(rect.bottom()) - 12)
        for y in range(int(rect.top()) + 12, int(rect.bottom()), step):
            p.drawLine(int(rect.left()) + 12, y, int(rect.right()) - 12, y)

        # scan lines
        p.setPen(QPen(QColor(255, 255, 255, 5), 1))
        for y in range(int(rect.top()) + 12, int(rect.bottom()), 5):
            p.drawLine(int(rect.left()) + 12, y, int(rect.right()) - 12, y)

        # central energy plane
        center_band = QLinearGradient(
            rect.center().x() - 260, rect.top(), rect.center().x() + 260, rect.bottom()
        )
        center_band.setColorAt(0.0, QColor(0, 0, 0, 0))
        center_band.setColorAt(0.5, QColor(45, 120, 180, 24))
        center_band.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(rect, center_band)

    def draw_frame(self, p: QPainter, rect: QRectF):
        outer = rect.adjusted(2, 2, -2, -2)
        inner = rect.adjusted(8, 8, -8, -8)

        p.setPen(QPen(QColor(90, 190, 255, 120), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(outer, 18, 18)

        p.setPen(QPen(QColor(130, 220, 255, 70), 1))
        p.drawRoundedRect(inner, 14, 14)

        # angular corner cuts
        p.setPen(QPen(QColor(130, 220, 255, 210), 2))
        l, t, r, b = outer.left(), outer.top(), outer.right(), outer.bottom()
        s = 22

        p.drawLine(int(l + 10), int(t), int(l + 10 + s), int(t))
        p.drawLine(int(l), int(t + 10), int(l), int(t + 10 + s))
        p.drawLine(int(r - 10), int(t), int(r - 10 - s), int(t))
        p.drawLine(int(r), int(t + 10), int(r), int(t + 10 + s))
        p.drawLine(int(l + 10), int(b), int(l + 10 + s), int(b))
        p.drawLine(int(l), int(b - 10), int(l), int(b - 10 - s))
        p.drawLine(int(r - 10), int(b), int(r - 10 - s), int(b))
        p.drawLine(int(r), int(b - 10), int(r), int(b - 10 - s))

        # top instrument ticks
        p.setPen(QPen(QColor(130, 220, 255, 110), 1))
        for i in range(10):
            x = rect.left() + 250 + i * 26
            p.drawLine(int(x), int(t + 2), int(x + 10), int(t + 2))

    def panel_box(self, p: QPainter, rect: QRectF):
        # solid technical panel
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        p.fillPath(path, QColor(6, 12, 20, 236))

        # subtle inner gradient so panels are never "white"
        inner = QRectF(
            rect.left() + 1, rect.top() + 1, rect.width() - 2, rect.height() - 2
        )
        grad = QLinearGradient(inner.left(), inner.top(), inner.left(), inner.bottom())
        grad.setColorAt(0.0, QColor(14, 22, 34, 110))
        grad.setColorAt(1.0, QColor(4, 8, 14, 40))
        p.fillRect(inner, grad)

        p.setPen(QPen(QColor(100, 200, 255, 90), 1))
        p.drawRoundedRect(rect, 8, 8)

        # clipped top-left accent
        p.setPen(QPen(QColor(120, 220, 255, 190), 2))
        p.drawLine(
            int(rect.left() + 10),
            int(rect.top() + 1),
            int(rect.left() + 46),
            int(rect.top() + 1),
        )
        p.drawLine(
            int(rect.left() + 1),
            int(rect.top() + 10),
            int(rect.left() + 1),
            int(rect.top() + 30),
        )

    def draw_terminal_panel(self, p: QPainter, rect: QRectF):
        self.panel_box(p, rect)

        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.8)
        p.setFont(title_font)
        p.setPen(QColor(220, 240, 250, 165))
        p.drawText(rect.adjusted(12, 10, -12, 0), "LIVE TERMINAL")

        body_font = QFont("Monospace")
        body_font.setStyleHint(QFont.StyleHint.Monospace)
        body_font.setPointSize(7)
        p.setFont(body_font)

        fade = QLinearGradient(
            rect.left(), rect.top() + 34, rect.left(), rect.bottom() - 12
        )
        fade.setColorAt(0.0, QColor(255, 255, 255, 0))
        fade.setColorAt(0.42, QColor(255, 255, 255, 52))
        fade.setColorAt(1.0, QColor(255, 255, 255, 172))

        lines_top = rect.top() + 40
        lines_bottom = rect.bottom() - 10
        line_h = 14
        max_lines = max(14, int((lines_bottom - lines_top) / line_h))
        visible = self.store.lines[-max_lines:]

        y = lines_bottom - (len(visible) - 1) * line_h
        for line in visible:
            path = QPainterPath()
            path.addText(rect.left() + 12, y, body_font, line[:58])
            p.fillPath(path, fade)
            y += line_h

    def draw_graph(
        self, p: QPainter, rect: QRectF, values, title: str, value_text: str
    ):
        self.panel_box(p, rect)

        title_font = QFont()
        title_font.setPointSize(8)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        p.setFont(title_font)
        p.setPen(QColor(220, 240, 250, 185))
        p.drawText(rect.adjusted(10, 8, -10, 0), title)
        p.drawText(
            rect.adjusted(10, 8, -10, 0), Qt.AlignmentFlag.AlignRight, value_text
        )

        plot = rect.adjusted(10, 26, -10, -10)

        # strong opaque plot background so every chart reads clearly
        plot_path = QPainterPath()
        plot_path.addRoundedRect(plot, 5, 5)
        p.fillPath(plot_path, QColor(3, 8, 14, 230))

        # faint vertical glow for depth
        plot_grad = QLinearGradient(plot.left(), plot.top(), plot.left(), plot.bottom())
        plot_grad.setColorAt(0.0, QColor(20, 40, 60, 32))
        plot_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(plot, plot_grad)

        # grid
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        for i in range(1, 5):
            y = plot.top() + plot.height() * (i / 5.0)
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
        for i in range(1, 6):
            x = plot.left() + plot.width() * (i / 6.0)
            p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

        vals = list(values)
        if len(vals) < 2:
            return

        line = QPainterPath()
        fill = QPainterPath()
        for i, v in enumerate(vals):
            x = plot.left() + (i / (len(vals) - 1)) * plot.width()
            y = plot.bottom() - (max(0.0, min(100.0, v)) / 100.0) * plot.height()
            if i == 0:
                line.moveTo(x, y)
                fill.moveTo(x, plot.bottom())
                fill.lineTo(x, y)
            else:
                line.lineTo(x, y)
                fill.lineTo(x, y)

        fill.lineTo(plot.right(), plot.bottom())
        fill.closeSubpath()

        c = self.color()
        fg = QLinearGradient(plot.left(), plot.top(), plot.left(), plot.bottom())
        fg.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 58))
        fg.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 6))
        p.fillPath(fill, fg)

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 220), 2))
        p.drawPath(line)

        lx = plot.right()
        ly = plot.bottom() - (max(0.0, min(100.0, vals[-1])) / 100.0) * plot.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(230, 248, 255, 225))
        p.drawEllipse(QRectF(lx - 3, ly - 3, 6, 6))

    def draw_metrics_block(self, p: QPainter, rect: QRectF):
        self.panel_box(p, rect)

        font = QFont()
        font.setPointSize(8)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        p.setFont(font)
        p.setPen(QColor(220, 240, 250, 160))
        p.drawText(rect.adjusted(10, 8, -10, 0), "SYSTEM STATUS")

        small = QFont("Monospace")
        small.setStyleHint(QFont.StyleHint.Monospace)
        small.setPointSize(8)
        p.setFont(small)
        p.setPen(QColor(205, 230, 240, 165))

        y = rect.top() + 30
        step = 18
        rows = [
            ("HOST", self.stats.hostname),
            ("STATE", self.store.state.upper()),
            ("CPU", f"{self.stats.cpu:.0f}%"),
            ("MEM", f"{self.stats.mem:.0f}%"),
            ("DOWN", f"{self.stats.net_down_kbps:.0f} KB/s"),
            ("UP", f"{self.stats.net_up_kbps:.0f} KB/s"),
        ]
        for k, v in rows:
            p.drawText(
                QRectF(rect.left() + 10, y, rect.width() - 20, 14),
                Qt.AlignmentFlag.AlignLeft,
                f"{k:<5} {v}",
            )
            y += step

    def draw_diag_panel(self, p: QPainter, rect: QRectF):
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        p.setFont(title_font)
        p.setPen(QColor(220, 240, 250, 165))
        p.drawText(rect.adjusted(0, 0, 0, 0), "DIAGNOSTICS")

        gap = 10
        y = rect.top() + 24

        h1 = rect.height() * 0.27
        h2 = rect.height() * 0.23
        h3 = rect.height() * 0.23
        h4 = rect.height() - 24 - gap * 3 - h1 - h2 - h3

        r1 = QRectF(rect.left(), y, rect.width(), h1)
        y += h1 + gap
        r2 = QRectF(rect.left(), y, rect.width(), h2)
        y += h2 + gap
        r3 = QRectF(rect.left(), y, rect.width(), h3)
        y += h3 + gap
        r4 = QRectF(rect.left(), y, rect.width(), h4)

        self.draw_graph(
            p, r1, self.stats.cpu_hist, "CPU LOAD", f"{self.stats.cpu:.0f}%"
        )
        self.draw_graph(p, r2, self.stats.mem_hist, "MEMORY", f"{self.stats.mem:.0f}%")
        self.draw_graph(
            p,
            r3,
            self.stats.down_hist,
            "NET DOWN",
            f"{self.stats.net_down_kbps:.0f} KB/s",
        )
        self.draw_metrics_block(p, r4)

    def draw_core(self, p: QPainter, rect: QRectF, with_panel: bool):
        cx, cy = rect.center().x(), rect.center().y()
        s = min(rect.width(), rect.height())
        drive = self.store.drive
        c = self.color()

        if with_panel:
            path = QPainterPath()
            path.addRoundedRect(rect.adjusted(1, 1, -1, -1), 12, 12)
            p.fillPath(path, QColor(6, 12, 22, 205))
            p.setPen(QPen(QColor(100, 200, 255, 70), 1))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 12, 12)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 8))
        p.drawEllipse(QRectF(cx - s * 0.35, cy - s * 0.35, s * 0.70, s * 0.70))

        self._ring(p, cx, cy, s * 0.100, 165, 4)
        self._ring(p, cx, cy, s * 0.152, 120, 3)
        self._ring(p, cx, cy, s * 0.208, 86, 2)
        self._ring(p, cx, cy, s * 0.286, 58, 2)

        self._segmented_band(p, cx, cy, s * 0.120, 46, 2, 5.0, 112, 2, 0.0, 0.88)
        self._segmented_band(p, cx, cy, s * 0.172, 62, 3, 4.0, 96, 2, 20.0, -0.62)
        self._segmented_band(p, cx, cy, s * 0.228, 84, 4, 3.0, 80, 2, 54.0, 0.45)

        base = math.degrees(self.phase) * 0.95
        self._arc(p, cx, cy, s * 0.126, base + 14, 84, 250, 7, accent=True)
        self._arc(p, cx, cy, s * 0.185, -base * 0.74 + 36, 60, 205, 5)
        self._arc(p, cx, cy, s * 0.242, base * 0.44 + 210, 96, 175, 5)
        self._arc(p, cx, cy, s * 0.308, -base * 0.28 + 300, 68, 138, 5)

        self._tick_band(p, cx, cy, s * 0.154, 48, s * 0.005, s * 0.010, 68, 2, 0.18)

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 34), 1))
        p.drawLine(int(cx - s * 0.36), int(cy), int(cx + s * 0.36), int(cy))
        p.drawLine(int(cx), int(cy - s * 0.28), int(cx), int(cy + s * 0.28))

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 108), 3))
        bw = s * 0.11
        bh = s * 0.14
        for side in (-1, 1):
            bx = cx + side * s * 0.35
            by1 = cy - bh / 2
            by2 = cy + bh / 2
            p.drawLine(int(bx), int(by1), int(bx), int(by2))
            p.drawLine(int(bx), int(by1), int(bx - side * bw), int(by1))
            p.drawLine(int(bx), int(by2), int(bx - side * bw), int(by2))

        pulse = s * (
            0.016 + drive * (0.018 if self.store.state == "speaking" else 0.010)
        )
        for i in range(2, 0, -1):
            rr = pulse + i * (s * 0.010)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 26 + i * 28))
            p.drawEllipse(QRectF(cx - rr, cy - rr, rr * 2, rr * 2))

        p.setBrush(QColor(242, 250, 255, 255))
        p.drawEllipse(QRectF(cx - pulse, cy - pulse, pulse * 2, pulse * 2))

        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSizeF(max(7.0, s * 0.011))
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        p.setFont(font)
        p.setPen(QColor(208, 244, 248, 112))
        p.drawText(
            QRectF(cx - s * 0.06, cy - s * 0.150, s * 0.12, s * 0.03),
            Qt.AlignmentFlag.AlignCenter,
            "SYS",
        )
        p.drawText(
            QRectF(cx - s * 0.06, cy + s * 0.118, s * 0.12, s * 0.03),
            Qt.AlignmentFlag.AlignCenter,
            "LINK",
        )

        rect_w = s * 0.42
        rect_h = s * 0.076
        label_rect = QRectF(cx - rect_w / 2, cy - rect_h / 2, rect_w, rect_h)

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 170), 2))
        p.setBrush(QColor(7, 16, 26, 242))
        p.drawRoundedRect(label_rect, 4, 4)

        f = QFont()
        f.setBold(True)
        f.setPointSizeF(max(14.0, s * 0.031))
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, max(2.0, s * 0.009))
        p.setFont(f)
        p.setPen(QColor(235, 250, 255, 248))
        p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, "J.A.R.V.I.S")

    def draw_wave(self, p: QPainter, rect: QRectF):
        c = self.accent_color()
        total, bar_w, gap = 36, 4, 4
        full_w = total * bar_w + (total - 1) * gap
        start_x = rect.center().x() - full_w / 2
        cy = rect.bottom() - 28
        d = self.store.drive

        for i in range(total):
            off = abs(i - total // 2)
            speed = (
                2.4
                if self.store.state == "speaking"
                else 1.5 if self.store.state == "listening" else 0.9
            )
            wave = math.sin(self.phase * speed + i * 0.28)
            base = 5 if self.store.state == "armed" else 7
            amp = 6 + d * (34 if self.store.state == "speaking" else 18)
            height = max(2, base + abs(wave) * amp - off * 0.34)

            x = start_x + i * (bar_w + gap)
            y = cy - height / 2
            path = QPainterPath()
            path.addRoundedRect(x, y, bar_w, height, 2, 2)
            alpha = 42 + int(min(155, height * 4))
            p.fillPath(path, QColor(c.red(), c.green(), c.blue(), alpha))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect())

        if self.is_expanded():
            self.draw_background(p, rect)
            self.draw_frame(p, rect)
            self.draw_tab(p)

            left_w = min(238, rect.width() * 0.18)
            right_w = min(310, rect.width() * 0.24)
            gap = 30

            terminal_rect = QRectF(26, 72, left_w, rect.height() - 116)
            diag_rect = QRectF(
                rect.width() - right_w - 26, 84, right_w, rect.height() - 142
            )

            center_left = terminal_rect.right() + gap
            center_right = diag_rect.left() - gap
            center_w = center_right - center_left

            jarvis_size = min(rect.height() * 0.80, center_w * 0.95)
            center_x = center_left + center_w / 2 + center_w * 0.08
            center_y = rect.center().y() + 2

            jarvis_rect = QRectF(
                center_x - jarvis_size / 2,
                center_y - jarvis_size / 2,
                jarvis_size,
                jarvis_size,
            )

            self.draw_terminal_panel(p, terminal_rect)
            self.draw_diag_panel(p, diag_rect)
            self.draw_core(p, jarvis_rect, with_panel=False)

            if self.store.state in {"listening", "speaking"}:
                wave_rect = QRectF(
                    jarvis_rect.left(),
                    jarvis_rect.bottom() - 24,
                    jarvis_rect.width(),
                    76,
                )
                self.draw_wave(p, wave_rect)
            return

        compact_panel = QPainterPath()
        compact_panel.addRoundedRect(rect.adjusted(2, 2, -2, -2), 14, 14)
        p.fillPath(compact_panel, QColor(5, 12, 20, 210))

        p.setPen(QPen(QColor(120, 220, 255, 85), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 14, 14)

        self.draw_frame(p, rect)
        self.draw_tab(p)

        pad = 22
        jarvis_rect = QRectF(
            pad,
            42,
            rect.width() - pad * 2,
            rect.height() - 74,
        )
        self.draw_core(p, jarvis_rect, with_panel=True)

        if self.store.state in {"listening", "speaking"}:
            self.draw_wave(p, rect)


class App:
    def __init__(self):
        print("Desktop HUD launched")

        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(True)

        self.store = Store()
        self.stats = SystemStats()
        self.win = HUDWindow(self.store, self.stats)

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(120)

        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.stats.refresh)
        self.stats_timer.start(1000)

    def refresh(self):
        self.store.refresh()
        self.win.update()

    def run(self):
        self.win.show()
        self.win.activateWindow()
        return self.app.exec()


if __name__ == "__main__":
    raise SystemExit(App().run())
