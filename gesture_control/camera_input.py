from __future__ import annotations

from dataclasses import dataclass
import cv2


@dataclass
class CameraFrame:
    ok: bool
    frame: any
    timestamp_ms: int


class CameraInput:
    def __init__(self, device_index: int = 0, width: int = 960, height: int = 540):
        self.device_index = device_index
        self.width = width
        self.height = height
        self.cap = None

    def start(self) -> None:
        self.cap = cv2.VideoCapture(self.device_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera index {self.device_index}")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def read(self) -> CameraFrame:
        if self.cap is None:
            raise RuntimeError("Camera not started")

        ok, frame = self.cap.read()
        ts = cv2.getTickCount() / cv2.getTickFrequency()
        return CameraFrame(ok=ok, frame=frame, timestamp_ms=int(ts * 1000))

    def stop(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None
