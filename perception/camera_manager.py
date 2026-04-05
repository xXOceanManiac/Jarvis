
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator
import cv2

@dataclass
class CameraConfig:
    name: str
    source: str
    enabled: bool = True

class CameraManager:
    def __init__(self, configs: list[CameraConfig]) -> None:
        self.configs = [c for c in configs if c.enabled and c.source]

    def open(self, source: str):
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open camera source: {source}")
        return cap

    def snapshot(self, source: str):
        cap = self.open(source)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError(f"Could not read frame from camera source: {source}")
        return frame
