
import uuid
import json
from datetime import datetime, timezone
from typing import Optional


EVENT_TYPES = {
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT",
    "ZONE_DWELL", "BILLING_QUEUE_JOIN",
    "BILLING_QUEUE_ABANDON", "REENTRY"
}


def build_event(
    store_id:    str,
    camera_id:   str,
    visitor_id:  str,
    event_type:  str,
    timestamp:   datetime,
    zone_id:     Optional[str]  = None,
    dwell_ms:    int            = 0,
    is_staff:    bool           = False,
    confidence:  float          = 1.0,
    queue_depth: Optional[int]  = None,
    sku_zone:    Optional[str]  = None,
    session_seq: int            = 0,
) -> dict:
    assert event_type in EVENT_TYPES, f"Unknown event type: {event_type}"

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return {
        "event_id":   str(uuid.uuid4()),
        "store_id":   store_id,
        "camera_id":  camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp":  timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zone_id":    zone_id,
        "dwell_ms":   dwell_ms,
        "is_staff":   is_staff,
        "confidence": round(float(confidence), 4),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone":    sku_zone,
            "session_seq": session_seq,
        }
    }


class EventWriter:
    def __init__(self, output_path: str, api_url: Optional[str] = None):
        self.output_path = output_path
        self.api_url     = api_url
        self._buffer     = []
        self._file       = open(output_path, "a", encoding="utf-8")
        self._total      = 0

    def write(self, event: dict):
        self._file.write(json.dumps(event) + "\n")
        self._file.flush()
        self._buffer.append(event)
        self._total += 1

        # Batch POST to API every 50 events
        if self.api_url and len(self._buffer) >= 50:
            self._flush_to_api()

    def _flush_to_api(self):
        if not self._buffer:
            return
        try:
            import requests
            resp = requests.post(
                self.api_url,
                json={"events": self._buffer},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                print(f"  → API: ingested={data['ingested']} "
                      f"dupes={data['duplicates']} errors={len(data['errors'])}")
                for err in data.get("errors", []):
                    print(f"    ✗ Event {err.get('event_id')} failed: {err.get('reason')}")
            else:
                print(f"  → API error {resp.status_code}")
        except Exception as e:
            print(f"  → API unreachable: {e}")
        self._buffer.clear()

    def close(self):
        self._flush_to_api()
        self._file.close()
        print(f"  ✓ Total events written: {self._total}")