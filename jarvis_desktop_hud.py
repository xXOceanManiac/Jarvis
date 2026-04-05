from __future__ import annotations

import json
import math
import sys
import time
from collections import deque
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
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
                out = deque(maxlen=90)
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
                        out.append(f"{ts}  {kind:<18} {json.dumps(rest)[:170]}")
                    except Exception:
                        out.append(raw[:220])
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

        self.cpu_hist = deque([0.0] * 120, maxlen=120)
        self.mem_hist = deque([0.0] * 120, maxlen=120)
        self.down_hist = deque([0.0] * 120, maxlen=120)
        self.up_hist = deque([0.0] * 120, maxlen=120)

        self._last_net = None
        self._last_t = time.time()

        if psutil:
            try:
                self._last_net = psutil.net_io_counters()
            except Exception:
                self._last_net = None

    def refresh(self) -> None:
        now = time.time()
        if psutil:
            try:
                self.cpu = float(psutil.cpu_percent(interval=None))
                self.mem = float(psutil.virtual_memory().percent)
            except Exception:
                self.cpu = self.mem = 0.0

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
                self._last_t = now
            except Exception:
                self.net_down_kbps = self.net_up_kbps = 0.0
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

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(Qt.WindowType.Window)
        self.setMouseTracking(True)

        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.setGeometry(
                geo.x() + 20,
                geo.y() + 20,
                max(980, geo.width() - 40),
                max(720, geo.height() - 40),
            )
        else:
            self.resize(1280, 900)

        self.setWindowTitle("JARVIS HUD")

        self.anim = QTimer(self)
        self.anim.timeout.connect(self.tick)
        self.anim.start(16)

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
            return 0.125 + self.store.drive * 0.100
        if self.store.state == "processing":
            return -0.100
        if self.store.state == "listening":
            return 0.075
        return 0.032

    def tick(self):
        target = self.target_orbit_speed()
        delta = target - self.orbit_vel

        changing_direction = (self.orbit_vel > 0 > target) or (
            self.orbit_vel < 0 < target
        )
        if changing_direction:
            accel = 0.34
        elif abs(delta) > 0.03:
            accel = 0.24
        else:
            accel = 0.050

        self.orbit_vel += delta * accel
        self.phase += self.orbit_vel
        self.update()

    def is_compact_mode(self) -> bool:
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return self.width() <= 640 or self.height() <= 500
        geo = screen.availableGeometry()
        return self.width() <= geo.width() * 0.5 and self.height() <= geo.height() * 0.5

    def _panel(self, p: QPainter, rect: QRectF, title: str):
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)

        grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        grad.setColorAt(0.0, QColor(6, 10, 16, 236))
        grad.setColorAt(1.0, QColor(4, 7, 12, 224))
        p.fillPath(path, grad)

        p.setPen(QPen(QColor(100, 200, 255, 95), 1.5))
        p.drawRoundedRect(rect, 16, 16)

        title_font = QFont()
        title_font.setPointSize(9)
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor(220, 240, 250, 180))
        p.drawText(rect.adjusted(14, 10, -14, 0), title)

    def _draw_graph(
        self, p: QPainter, rect: QRectF, values, title: str, value_text: str
    ):
        self._panel(p, rect, title)

        p.setPen(QColor(220, 240, 250, 180))
        p.drawText(
            rect.adjusted(14, 10, -14, 0), Qt.AlignmentFlag.AlignRight, value_text
        )

        plot = rect.adjusted(14, 30, -14, -12)
        plot_path = QPainterPath()
        plot_path.addRoundedRect(plot, 8, 8)
        p.fillPath(plot_path, QColor(3, 8, 14, 230))

        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        for i in range(1, 5):
            y = plot.top() + plot.height() * (i / 5.0)
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

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
        fg.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 120))
        fg.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 10))
        p.fillPath(fill, fg)

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 220), 2))
        p.drawPath(line)

    def _draw_corner_gauge(
        self, p: QPainter, rect: QRectF, label: str, value: float, value_text: str
    ):
        c = self.color()
        cx = rect.center().x()
        cy = rect.center().y()
        r = min(rect.width(), rect.height()) * 0.44

        path = QPainterPath()
        path.addEllipse(rect)
        g = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        g.setColorAt(0.0, QColor(8, 14, 24, 232))
        g.setColorAt(1.0, QColor(4, 8, 14, 220))
        p.fillPath(path, g)

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 70), 1.4))
        p.drawEllipse(rect)

        self._ring(p, cx, cy, r * 0.80, 70, 1)
        self._ring(p, cx, cy, r * 0.58, 55, 1)

        start_deg = 220
        full_span = 260
        span = full_span * max(0.0, min(1.0, value / 100.0))

        p.setPen(QPen(QColor(255, 255, 255, 20), 3))
        p.drawArc(
            QRectF(cx - r * 0.82, cy - r * 0.82, r * 1.64, r * 1.64),
            int(-start_deg * 16),
            int(-full_span * 16),
        )

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 230), 3))
        p.drawArc(
            QRectF(cx - r * 0.82, cy - r * 0.82, r * 1.64, r * 1.64),
            int(-start_deg * 16),
            int(-span * 16),
        )

        label_font = QFont()
        label_font.setPointSize(max(8, int(r * 0.13)))
        label_font.setBold(True)
        p.setFont(label_font)
        p.setPen(QColor(210, 232, 245, 185))
        p.drawText(
            QRectF(cx - r * 0.75, cy - r * 0.60, r * 1.5, 20),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )

        value_font = QFont()
        value_font.setPointSize(max(10, int(r * 0.21)))
        value_font.setBold(True)
        p.setFont(value_font)
        p.setPen(QColor(235, 246, 252, 230))
        p.drawText(
            QRectF(cx - r * 0.78, cy - 12, r * 1.56, 26),
            Qt.AlignmentFlag.AlignCenter,
            value_text,
        )

    def _ring(
        self, p: QPainter, cx: float, cy: float, r: float, alpha: int, width: int
    ):
        c = self.color()
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), alpha), width))
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
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), alpha), width))
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
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), alpha), width))
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
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), alpha), width))

        for i in range(tick_count):
            if i % 2 != 0:
                continue
            ang = (i / tick_count) * math.tau + self.phase * speed_mul
            x1 = cx + math.cos(ang) * (r - inner)
            y1 = cy + math.sin(ang) * (r - inner)
            x2 = cx + math.cos(ang) * (r + outer)
            y2 = cy + math.sin(ang) * (r + outer)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

    def _draw_core(self, p: QPainter, rect: QRectF):
        cx = rect.center().x()
        cy = rect.center().y() + 12
        s = min(rect.width(), rect.height()) * 0.94
        drive = self.store.drive
        c = self.color()
        a = self.accent_color()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 7))
        p.drawEllipse(QRectF(cx - s * 0.36, cy - s * 0.36, s * 0.72, s * 0.72))

        self._ring(p, cx, cy, s * 0.095, 170, 4)
        self._ring(p, cx, cy, s * 0.148, 122, 3)
        self._ring(p, cx, cy, s * 0.205, 86, 2)
        self._ring(p, cx, cy, s * 0.286, 52, 2)
        self._ring(p, cx, cy, s * 0.344, 28, 1)

        self._segmented_band(p, cx, cy, s * 0.118, 48, 2, 5.0, 118, 2, 0.0, 1.10)
        self._segmented_band(p, cx, cy, s * 0.172, 62, 3, 4.0, 98, 2, 18.0, -0.86)
        self._segmented_band(p, cx, cy, s * 0.226, 84, 4, 3.0, 82, 2, 54.0, 0.66)

        base = math.degrees(self.phase) * 1.35
        self._arc(p, cx, cy, s * 0.124, base + 12, 84, 250, 7, accent=True)
        self._arc(p, cx, cy, s * 0.182, -base * 0.78 + 34, 60, 210, 5)
        self._arc(p, cx, cy, s * 0.240, base * 0.56 + 210, 96, 178, 5)
        self._arc(p, cx, cy, s * 0.306, -base * 0.36 + 302, 68, 138, 5)

        self._tick_band(p, cx, cy, s * 0.152, 48, s * 0.005, s * 0.010, 74, 2, 0.22)

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 24), 1))
        p.drawLine(int(cx - s * 0.37), int(cy), int(cx + s * 0.37), int(cy))
        p.drawLine(int(cx), int(cy - s * 0.29), int(cx), int(cy + s * 0.29))

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 112), 3))
        bw = s * 0.11
        bh = s * 0.14
        for side in (-1, 1):
            bx = cx + side * s * 0.35
            by1 = cy - bh / 2
            by2 = cy + bh / 2
            p.drawLine(int(bx), int(by1), int(bx), int(by2))
            p.drawLine(int(bx), int(by1), int(bx - side * bw), int(by1))
            p.drawLine(int(bx), int(by2), int(bx - side * bw), int(by2))

        pulse = 1.0 + drive * 0.18 + (0.05 * math.sin(self.phase * 2.2))
        core_r = s * 0.050 * pulse

        inner_grad = QLinearGradient(cx, cy - core_r, cx, cy + core_r)
        inner_grad.setColorAt(0.0, QColor(235, 248, 255, 245))
        inner_grad.setColorAt(1.0, QColor(a.red(), a.green(), a.blue(), 180))
        core_path = QPainterPath()
        core_path.addEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))
        p.fillPath(core_path, inner_grad)

        p.setPen(QPen(QColor(210, 240, 255, 220), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - s * 0.052, cy - s * 0.052, s * 0.104, s * 0.104))

        box_w = s * 0.48
        box_h = s * 0.095
        text_box = QRectF(cx - box_w / 2, cy - box_h / 2, box_w, box_h)
        box_path = QPainterPath()
        box_path.addRoundedRect(text_box, box_h * 0.24, box_h * 0.24)

        glass_grad = QLinearGradient(
            text_box.left(), text_box.top(), text_box.left(), text_box.bottom()
        )
        glass_grad.setColorAt(0.0, QColor(9, 14, 22, 232))
        glass_grad.setColorAt(1.0, QColor(5, 9, 15, 224))
        p.fillPath(box_path, glass_grad)

        p.setPen(QPen(QColor(120, 210, 255, 62), 1.1))
        p.drawRoundedRect(text_box, box_h * 0.24, box_h * 0.24)

        center_font = QFont()
        center_font.setPointSize(max(12, int(s * 0.030)))
        center_font.setBold(True)
        center_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, max(1.0, s * 0.0021)
        )
        p.setFont(center_font)
        p.setPen(QColor(235, 246, 252, 238))
        p.drawText(
            text_box,
            Qt.AlignmentFlag.AlignCenter,
            "J.A.R.V.I.S",
        )

        tag_font = QFont()
        tag_font.setPointSize(max(7, int(s * 0.012)))
        tag_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        p.setFont(tag_font)
        p.setPen(QColor(170, 220, 245, 170))

        tag_w = s * 0.10
        tag_h = s * 0.030
        p.drawText(
            QRectF(cx - tag_w / 2, cy - s * 0.255, tag_w, tag_h),
            Qt.AlignmentFlag.AlignCenter,
            "SYS",
        )
        p.drawText(
            QRectF(cx + s * 0.245 - tag_w / 2, cy - tag_h / 2, tag_w, tag_h),
            Qt.AlignmentFlag.AlignCenter,
            "LINK",
        )
        p.drawText(
            QRectF(cx - tag_w / 2, cy + s * 0.225, tag_w, tag_h),
            Qt.AlignmentFlag.AlignCenter,
            "CORE",
        )
        p.drawText(
            QRectF(cx - s * 0.245 - tag_w / 2, cy - tag_h / 2, tag_w, tag_h),
            Qt.AlignmentFlag.AlignCenter,
            "AUX",
        )

    def _draw_logs(self, p: QPainter, rect: QRectF):
        self._panel(p, rect, "LIVE LOGS")
        body = rect.adjusted(14, 34, -14, -12)

        clip = QPainterPath()
        clip.addRoundedRect(body, 8, 8)
        p.setClipPath(clip)
        p.fillRect(body, QColor(3, 8, 14, 235))

        font = QFont("Monospace")
        font.setPointSize(9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        p.setFont(font)

        line_h = 16
        max_lines = max(1, int((body.height() - 8) / line_h))
        visible = self.store.lines[-max_lines:]

        y = body.top() + 16
        for line in visible:
            p.setPen(QColor(225, 240, 248, 165))
            p.drawText(
                QRectF(body.left() + 8, y - 11, body.width() - 16, line_h + 3),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                line[:260],
            )
            y += line_h

        p.setClipping(False)

    def paintEvent(self, _event):
        self.store.refresh()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(10, 10, self.width() - 20, self.height() - 20)

        bg = QPainterPath()
        bg.addRoundedRect(rect, 20, 20)
        p.fillPath(bg, QColor(2, 5, 9, 244))

        p.setPen(QPen(QColor(90, 190, 255, 90), 2))
        p.drawRoundedRect(rect, 20, 20)

        if self.is_compact_mode():
            core_size = min(rect.width(), rect.height()) * 0.88
            core_rect = QRectF(
                rect.center().x() - core_size / 2,
                rect.center().y() - core_size / 2,
                core_size,
                core_size,
            )
            self._draw_core(p, core_rect)

            gauge_size = min(rect.width(), rect.height()) * 0.22
            margin = 18
            tl = QRectF(
                rect.left() + margin, rect.top() + margin, gauge_size, gauge_size
            )
            tr = QRectF(
                rect.right() - margin - gauge_size,
                rect.top() + margin,
                gauge_size,
                gauge_size,
            )
            br = QRectF(
                rect.right() - margin - gauge_size,
                rect.bottom() - margin - gauge_size,
                gauge_size,
                gauge_size,
            )

            self._draw_corner_gauge(
                p, tl, "CPU", self.stats.cpu, f"{self.stats.cpu:.0f}%"
            )
            self._draw_corner_gauge(
                p, tr, "MEM", self.stats.mem, f"{self.stats.mem:.0f}%"
            )
            self._draw_corner_gauge(
                p,
                br,
                "NET",
                min(100.0, self.stats.net_down_kbps / 10.0),
                f"{min(100.0, self.stats.net_down_kbps / 10.0):.0f}%",
            )
            return

        top_h = max(300, rect.height() * 0.62)
        bottom_h = rect.height() - top_h - 30
        gap = 18
        left_w = rect.width() * 0.68
        right_w = rect.width() - left_w - gap - 30
        left = rect.left() + 16
        top = rect.top() + 18

        core_rect = QRectF(left, top, left_w, top_h - 10)
        right_x = core_rect.right() + gap
        graph_h = (top_h - gap * 3) / 4.0

        cpu_rect = QRectF(right_x, top, right_w, graph_h)
        mem_rect = QRectF(right_x, cpu_rect.bottom() + gap, right_w, graph_h)
        down_rect = QRectF(right_x, mem_rect.bottom() + gap, right_w, graph_h)
        up_rect = QRectF(right_x, down_rect.bottom() + gap, right_w, graph_h)
        logs_rect = QRectF(left, core_rect.bottom() + gap, rect.width() - 32, bottom_h)

        self._draw_core(p, core_rect)
        self._draw_graph(
            p, cpu_rect, self.stats.cpu_hist, "CPU LOAD", f"{self.stats.cpu:.0f}%"
        )
        self._draw_graph(
            p, mem_rect, self.stats.mem_hist, "MEMORY", f"{self.stats.mem:.0f}%"
        )
        self._draw_graph(
            p,
            down_rect,
            self.stats.down_hist,
            "NET DOWN",
            f"{self.stats.net_down_kbps:.0f} KB/s",
        )
        self._draw_graph(
            p,
            up_rect,
            self.stats.up_hist,
            "NET UP",
            f"{self.stats.net_up_kbps:.0f} KB/s",
        )
        self._draw_logs(p, logs_rect)


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
