
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class RightCameraObservation:
    summary: str
    confidence: float

class RightCameraObserver:
    """
    V5.1 single-camera observer scaffold. Later:
    - environment awareness
    - presence detection
    - whiteboard/paper fusion with more cameras
    - gesture attention zones
    """
    def summarize(self, frame) -> RightCameraObservation:
        return RightCameraObservation(summary="Camera frame captured.", confidence=0.2)
