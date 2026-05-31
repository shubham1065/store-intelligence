import hashlib
import numpy as np
from datetime import datetime, timezone
from typing import Optional


def make_visitor_id(seed: str) -> str:
    """Generates a short deterministic visitor ID from a seed string."""

    h = hashlib.md5(seed.encode()).hexdigest()[:8]
    return f"VIS_{h}"


class VisitorSession:
    """Tracks the full lifecycle of one visitor."""

    def __init__(self, visitor_id: str, entry_time: datetime, is_staff: bool = False):
        self.visitor_id   = visitor_id
        self.entry_time   = entry_time
        self.exit_time:   Optional[datetime] = None
        self.is_staff     = is_staff
        self.current_zone: Optional[str] = None
        self.zone_entry_time: Optional[datetime] = None
        self.last_dwell_emit: Optional[datetime] = None
        self.session_seq  = 0
        self.feature_vec: Optional[np.ndarray] = None  # for Re-ID

    def next_seq(self) -> int:
        self.session_seq += 1
        return self.session_seq

    def has_exited(self) -> bool:
        return self.exit_time is not None


class ReIDManager:
    "Simple Re-ID using colour histogram of the person crop."

    def __init__(self, similarity_threshold: float = 0.75,
                 reentry_window_seconds: int = 1800):
        self.threshold  = similarity_threshold
        self.window_sec = reentry_window_seconds
        # visitor_id -> (exit_time, feature_vector)
        self._exited: dict[str, tuple] = {}

    def register_exit(self, visitor_id: str, exit_time: datetime,
                      frame: np.ndarray, bbox):
        feature = self._extract_feature(frame, bbox)
        if feature is not None:
            self._exited[visitor_id] = (exit_time, feature)

    def find_reentry(self, frame: np.ndarray, bbox,
                     current_time: datetime) -> Optional[str]:
        "Returns matching visitor_id if this looks like a re-entry."
        new_feature = self._extract_feature(frame, bbox)
        if new_feature is None:
            return None

        best_sim    = 0.0
        best_vid    = None

        for visitor_id, (exit_time, saved_feature) in list(self._exited.items()):
            elapsed = (current_time - exit_time).total_seconds()
            if elapsed > self.window_sec:
                # Too old — clean up
                del self._exited[visitor_id]
                continue

            sim = self._cosine_similarity(new_feature, saved_feature)
            if sim > best_sim:
                best_sim = sim
                best_vid = visitor_id

        if best_sim >= self.threshold:
            return best_vid
        return None

    def _extract_feature(self, frame: np.ndarray, bbox) -> Optional[np.ndarray]:
        "Colour histogram of the person crop as a feature vector."

        import cv2
        x1, y1, x2, y2 = map(int, bbox)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
            return None
        hsv  = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [18, 16],
                            [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist.flatten()

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)


class SessionManager:
    "Manages all active visitor sessions for one camera."

    def __init__(self, camera_id: str, store_id: str):
        self.camera_id = camera_id
        self.store_id  = store_id
        # track_id (ByteTrack int) -> visitor_id
        self._track_to_visitor: dict[int, str] = {}
        # visitor_id -> VisitorSession
        self._sessions: dict[str, VisitorSession] = {}

    def get_or_create(self, track_id: int, entry_time: datetime,
                  is_staff: bool, reentry_visitor_id: Optional[str]) -> VisitorSession:
        if track_id in self._track_to_visitor:
            vid     = self._track_to_visitor[track_id]
            session = self._sessions.get(vid)   
            if session is not None:
                return session
            # Session was removed but mapping still exists — clean up stale entry
            del self._track_to_visitor[track_id]

        # Create new session
        if reentry_visitor_id:
            vid = reentry_visitor_id
        else:
            vid = make_visitor_id(
                f"{self.store_id}_{self.camera_id}_{track_id}_{entry_time.isoformat()}"
            )

        session = VisitorSession(vid, entry_time, is_staff)
        self._track_to_visitor[track_id] = vid
        self._sessions[vid]              = session
        return session

    def get(self, track_id: int) -> Optional[VisitorSession]:
        vid = self._track_to_visitor.get(track_id)
        if vid:
            return self._sessions.get(vid)
        return None

    def remove(self, track_id: int):
        vid = self._track_to_visitor.pop(track_id, None)
        if vid:
            self._sessions.pop(vid, None)

    def active_count(self, exclude_staff: bool = True) -> int:
        return sum(
            1 for s in self._sessions.values()
            if not s.has_exited() and (not exclude_staff or not s.is_staff)
        )