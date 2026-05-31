# Two-method staff detection - 1. HSV uniform colour (primary)
# 2. Long presence heuristic (secondary)

import cv2
import numpy as np
from typing import Tuple


class StaffDetector:
    def __init__(self, hsv_lower, hsv_upper, long_presence_frames: int = 3600):
        
        self.lower = np.array(hsv_lower, dtype=np.uint8)
        self.upper = np.array(hsv_upper, dtype=np.uint8)
        self.long_presence = long_presence_frames

        self.track_frame_count: dict[int, int] = {}

    def update_track(self, track_id: int):
        self.track_frame_count[track_id] = \
            self.track_frame_count.get(track_id, 0) + 1

    def classify(self, frame: np.ndarray, bbox, track_id: int) -> Tuple[bool, float]:
        x1, y1, x2, y2 = map(int, bbox)
        h = y2 - y1

        if h < 30 or (x2 - x1) < 10:
            return self._heuristic_check(track_id, 0.0)

        # Torso = middle third of bounding box vertically
        torso_y1 = y1 + h // 3
        torso_y2 = y1 + 2 * h // 3
        torso = frame[torso_y1:torso_y2, x1:x2]

        if torso.size == 0:
            return self._heuristic_check(track_id, 0.0)

        hsv   = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
        mask  = cv2.inRange(hsv, self.lower, self.upper)
        ratio = float(np.sum(mask > 0)) / mask.size

        is_staff = ratio > 0.40  # >40% uniform colour = staff
        if is_staff:
            return True, round(ratio, 3)

        return self._heuristic_check(track_id, ratio)

    def _heuristic_check(self, track_id: int, colour_conf: float) -> Tuple[bool, float]:
        frames_seen = self.track_frame_count.get(track_id, 0)
        if frames_seen >= self.long_presence:

            heuristic_conf = min(0.95, 0.6 + (frames_seen / self.long_presence) * 0.35)
            return True, round(heuristic_conf, 3)
        return False, round(colour_conf, 3)