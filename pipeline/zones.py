from datetime import datetime, timedelta
from typing import Optional

class ZoneClassifier:
    def __init__(self, camera_config: dict, zone_list: list):
        self.cam    = camera_config
        self.sku_map = {z["zone_id"]: z["sku_zone"] for z in zone_list}

    def get_zone(self, bbox, frame_height: int) -> Optional[str]:
        cam_type = self.cam.get("type", "floor")

        if cam_type == "entry":
            return None  

        if cam_type == "billing":
            return "BILLING"

        if cam_type == "floor":
            zones = self.cam.get("primary_zones", [])
            if not zones:
                return None
            if len(zones) == 1:
                return zones[0]

            _, y1, _, y2 = bbox
            centroid_y = (y1 + y2) / 2

            if centroid_y < frame_height / 2:
                return zones[0]
            return zones[1]

        return None

    def get_sku_zone(self, zone_id: Optional[str]) -> Optional[str]:
        if zone_id is None:
            return None
        return self.sku_map.get(zone_id)


class EntryLineDetector:
    """Detects entry/exit by virtual tripwire on the entry camera."""

    def __init__(self, line_y_ratio: float, direction: str = "top_to_bottom"):
        self.line_y_ratio = line_y_ratio
        self.direction    = direction
        self._prev_y: dict[int, float] = {}

    def update(self, track_id: int, bbox, frame_height: int) -> Optional[str]:
        _, y1, _, y2 = bbox
        centroid_y  = (y1 + y2) / 2
        line_y      = self.line_y_ratio * frame_height

        prev_y = self._prev_y.get(track_id)
        self._prev_y[track_id] = centroid_y

        if prev_y is None:
            return None  

        crossed = (prev_y < line_y <= centroid_y) or (prev_y > line_y >= centroid_y)
        if not crossed:
            return None

        # Determine direction
        moving_down = centroid_y > prev_y
        if self.direction == "top_to_bottom":
            return "ENTRY" if moving_down else "EXIT"
        else:
            return "EXIT" if moving_down else "ENTRY"

    def remove(self, track_id: int):
        self._prev_y.pop(track_id, None)


def parse_clip_start(time_str: str, date_str: str) -> datetime:
    """Converts 'HH:MM:SS' + 'YYYY-MM-DD' to datetime."""
    
    from datetime import timezone
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc)


def frame_to_timestamp(clip_start: datetime, frame_idx: int, fps: float) -> datetime:
    offset_seconds = frame_idx / fps
    return clip_start + timedelta(seconds=offset_seconds)