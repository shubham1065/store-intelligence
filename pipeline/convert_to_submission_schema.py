# Converted pipeline sample_events.jsonl to the required submission schema

import json
import uuid
from pathlib import Path


EVENT_TYPE_MAP = {
    "ENTRY":                  "entry",
    "EXIT":                   "exit",
    "REENTRY":                "entry",
    "ZONE_ENTER":             "zone_entered",
    "ZONE_EXIT":              "zone_exited",
    "ZONE_DWELL":             "zone_dwell",
    "BILLING_QUEUE_JOIN":     "queue_completed",
    "BILLING_QUEUE_ABANDON":  "queue_abandoned",
}


def convert_event(event: dict) -> dict | None:
    raw_type    = event.get("event_type", "")
    mapped_type = EVENT_TYPE_MAP.get(raw_type)
    if not mapped_type:
        return None

    visitor_id  = event.get("visitor_id", "")
    store_id    = event.get("store_id", "")
    camera_id   = event.get("camera_id", "")
    timestamp   = event.get("timestamp", "")
    is_staff    = event.get("is_staff", False)
    zone_id     = event.get("zone_id")
    dwell_ms    = event.get("dwell_ms", 0)
    metadata    = event.get("metadata", {})
    queue_depth = metadata.get("queue_depth")

    if mapped_type in ("entry", "exit"):
        return {
            "event_type":    mapped_type,
            "id_token":      visitor_id,
            "store_code":    store_id,
            "camera_id":     camera_id.lower(),
            "event_timestamp": timestamp,
            "is_staff":      is_staff,
            "gender_pred":   None,
            "age_pred":      None,
            "age_bucket":    None,
            "is_face_hidden": False,
            "group_id":      None,
            "group_size":    None,
            "confidence":    event.get("confidence"),
        }

    if mapped_type in ("zone_entered", "zone_exited", "zone_dwell"):
        return {
            "event_type":     mapped_type,
            "track_id":       visitor_id,
            "store_id":       store_id,
            "camera_id":      camera_id,
            "zone_id":        zone_id,
            "zone_name":      metadata.get("sku_zone", zone_id),
            "zone_type":      "BILLING" if zone_id == "BILLING" else "SHELF",
            "is_revenue_zone": "Yes",
            "event_time":     timestamp,
            "dwell_ms":       dwell_ms,
            "zone_hotspot_x": None,
            "zone_hotspot_y": None,
            "gender":         None,
            "age":            None,
            "age_bucket":     None,
            "is_staff":       is_staff,
        }

    if mapped_type in ("queue_completed", "queue_abandoned"):
        abandoned = (mapped_type == "queue_abandoned")
        return {
            "queue_event_id":       str(uuid.uuid4()),
            "event_type":           mapped_type,
            "track_id":             visitor_id,
            "store_id":             store_id,
            "camera_id":            camera_id,
            "zone_id":              zone_id or "BILLING",
            "zone_name":            "Billing Counter Queue",
            "zone_type":            "BILLING",
            "is_revenue_zone":      "Yes",
            "queue_join_ts":        timestamp,
            "queue_served_ts":      None if abandoned else timestamp,
            "queue_exit_ts":        timestamp,
            "wait_seconds":         dwell_ms // 1000 if dwell_ms else None,
            "queue_position_at_join": queue_depth,
            "abandoned":            abandoned,
            "zone_hotspot_x":       None,
            "zone_hotspot_y":       None,
            "gender":               None,
            "age":                  None,
            "age_bucket":           None,
        }

    return None


def convert_file(input_path: str, output_path: str):
    converted = 0
    skipped   = 0

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(input_path) as fin, open(output_path, "w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            event  = json.loads(line)
            result = convert_event(event)
            if result:
                fout.write(json.dumps(result) + "\n")
                converted += 1
            else:
                skipped += 1

    print(f"Converted: {converted} events")
    print(f"Skipped:   {skipped} events")
    print(f"Output:    {output_path}")


if __name__ == "__main__":
    import sys
    input_path  = sys.argv[1] if len(sys.argv) > 1 else "data/sample_events.jsonl"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "submission/events_submission.jsonl"
    convert_file(input_path, output_path)