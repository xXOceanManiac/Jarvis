from __future__ import annotations

from dataclasses import dataclass
from typing import List

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


@dataclass
class HandPoint:
    x: float
    y: float
    z: float


@dataclass
class TrackedHand:
    handedness: str
    score: float
    landmarks: List[HandPoint]


class HandTracker:
    def __init__(self, model_path: str, num_hands: int = 1):
        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=num_hands,
        )
        self.landmarker = vision.HandLandmarker.create_from_options(options)

    def process_bgr(self, frame_bgr) -> List[TrackedHand]:
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        result = self.landmarker.detect(mp_image)

        hands: List[TrackedHand] = []
        if not result.hand_landmarks:
            return hands

        for i, hand_landmarks in enumerate(result.hand_landmarks):
            handedness = "Unknown"
            score = 0.0
            if result.handedness and i < len(result.handedness) and result.handedness[i]:
                handedness = result.handedness[i][0].category_name
                score = float(result.handedness[i][0].score)

            pts = [HandPoint(x=lm.x, y=lm.y, z=lm.z) for lm in hand_landmarks]
            hands.append(TrackedHand(handedness=handedness, score=score, landmarks=pts))

        return hands
