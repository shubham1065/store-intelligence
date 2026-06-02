import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.emit    import build_event, EventWriter
from pipeline.staff   import StaffDetector
from pipeline.zones   import ZoneClassifier, EntryLineDetector, frame_to_timestamp, parse_clip_start
from pipeline.tracker import ReIDManager, SessionManager

def load_layout(path: str) -> dict:
    with open(path) as f:
        return json.load(f)

def process_clip(
    clip_path:   str,
    camera_cfg:  dict,
    layout:      dict,
    writer:      EventWriter,
    reid_mgr:    ReIDManager,
    model,
):
    store_id  = layout["store_id"]
    camera_id = camera_cfg["camera_id"]
    cam_type  = camera_cfg.get("type", "floor")

    clip_start = parse_clip_start(
        camera_cfg.get("clip_start_time", "12:00:00"),
        layout.get("date", "2026-04-10")
    )

    zone_clf    = ZoneClassifier(camera_cfg, layout["zones"])
    staff_cfg   = layout.get("staff", {})
    staff_det   = StaffDetector(
        hsv_lower            = staff_cfg.get("uniform_hsv", {}).get("lower", [0, 0, 0]),
        hsv_upper            = staff_cfg.get("uniform_hsv", {}).get("upper", [180, 255, 60]),
        long_presence_frames = int(staff_cfg.get("long_presence_minutes", 8) * 60 * 15)
    )

    # Backroom camera — skipping entirely...
    if cam_type == "backroom":
        print(f"  ℹ {camera_id} is backroom — skipping")
        return

    entry_det   = None
    if cam_type == "entry":
        entry_det = EntryLineDetector(
            line_y_ratio = camera_cfg.get("entry_line_y_ratio", 0.55),
            direction    = camera_cfg.get("entry_direction", "top_to_bottom")
        )

    session_mgr = SessionManager(camera_id, store_id)

    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        print(f"  ✗ Cannot open: {clip_path}")
        return

    fps         = cap.get(cv2.CAP_PROP_FPS) or 15.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    cap.release()   

    print(f"  Processing {camera_id} | {clip_path}")
    print(f"  FPS={fps:.1f} | Frames={total_frames} | "
          f"Duration={total_frames/fps:.0f}s | Type={cam_type}")

    prev_track_ids: set = set()

    dwell_state: dict[str, tuple] = {}

    frame_idx = 0

    results = model.track(
        source    = clip_path,
        persist   = True,
        classes   = [0],
        conf      = 0.35,
        iou       = 0.30,
        tracker   = "bytetrack.yaml",
        stream    = True,
        verbose   = False,
    )

    for result in results:
        frame     = result.orig_img
        fh, fw    = frame.shape[:2]
        timestamp = frame_to_timestamp(clip_start, frame_idx, fps)
        frame_idx += 1

        if frame_idx % 2 != 0:
            continue

        current_track_ids: set = set()

        if result.boxes is None or result.boxes.id is None:
            _handle_disappeared_tracks(
                prev_track_ids, set(), session_mgr, reid_mgr,
                writer, store_id, camera_id, cam_type,
                timestamp, dwell_state
            )
            prev_track_ids = set()
            continue

        for box in result.boxes:
            track_id   = int(box.id.item())
            confidence = float(box.conf.item())
            bbox       = box.xyxy[0].tolist()

            current_track_ids.add(track_id)
            staff_det.update_track(track_id)

            is_staff, staff_conf = staff_det.classify(frame, bbox, track_id)
            detection_conf = confidence * (staff_conf if is_staff else 1.0)

            current_zone = zone_clf.get_zone(bbox, fh)
            sku_zone     = zone_clf.get_sku_zone(current_zone)

            if track_id not in prev_track_ids:
                reentry_vid = None
                if cam_type == "entry":
                    reentry_vid = reid_mgr.find_reentry(frame, bbox, timestamp)

                session = session_mgr.get_or_create(
                    track_id, timestamp, is_staff, reentry_vid
                )

                if cam_type == "entry":
                    direction = entry_det.update(track_id, bbox, fh)
                    if direction == "ENTRY":
                        evt_type = "REENTRY" if reentry_vid else "ENTRY"
                        writer.write(build_event(
                            store_id    = store_id,
                            camera_id   = camera_id,
                            visitor_id  = session.visitor_id,
                            event_type  = evt_type,
                            timestamp   = timestamp,
                            is_staff    = is_staff,
                            confidence  = round(detection_conf, 3),
                            session_seq = session.next_seq(),
                        ))

                elif current_zone and cam_type in ("floor", "billing"):
                    session.current_zone   = current_zone
                    session.zone_entry_time = timestamp

                    queue_depth = None
                    event_type  = "ZONE_ENTER"

                    if cam_type == "billing":
                        queue_depth = session_mgr.active_count(exclude_staff=True)
                        if queue_depth > 1:
                            event_type = "BILLING_QUEUE_JOIN"

                    writer.write(build_event(
                        store_id    = store_id,
                        camera_id   = camera_id,
                        visitor_id  = session.visitor_id,
                        event_type  = event_type,
                        timestamp   = timestamp,
                        zone_id     = current_zone,
                        is_staff    = is_staff,
                        confidence  = round(detection_conf, 3),
                        queue_depth = queue_depth,
                        sku_zone    = sku_zone,
                        session_seq = session.next_seq(),
                    ))

            else:
                session = session_mgr.get(track_id)
                if not session:
                    continue

                if cam_type == "entry" and entry_det:
                    direction = entry_det.update(track_id, bbox, fh)
                    if direction in ("ENTRY", "EXIT"):
                        evt_type = "REENTRY" if (
                            direction == "ENTRY" and
                            reid_mgr.find_reentry(frame, bbox, timestamp)
                        ) else direction
                        writer.write(build_event(
                            store_id   = store_id,
                            camera_id  = camera_id,
                            visitor_id = session.visitor_id,
                            event_type = evt_type,
                            timestamp  = timestamp,
                            is_staff   = is_staff,
                            confidence = round(detection_conf, 3),
                            session_seq = session.next_seq(),
                        ))
                        if direction == "EXIT":
                            reid_mgr.register_exit(
                                session.visitor_id, timestamp, frame, bbox
                            )

                elif cam_type in ("floor", "billing") and current_zone:
                    _handle_dwell(
                        session, current_zone, sku_zone,
                        timestamp, writer, store_id, camera_id, detection_conf
                    )

        disappeared = prev_track_ids - current_track_ids
        _handle_disappeared_tracks(
            disappeared, current_track_ids, session_mgr, reid_mgr,
            writer, store_id, camera_id, cam_type,
            timestamp, dwell_state
        )

        prev_track_ids = current_track_ids

    print(f"  ✓ {camera_id} done — {frame_idx} frames processed")


def _handle_dwell(session, current_zone, sku_zone, timestamp,
                  writer, store_id, camera_id, confidence):
                  
    if session.current_zone != current_zone:
        if session.current_zone and session.zone_entry_time:
            dwell_ms = int((timestamp - session.zone_entry_time).total_seconds() * 1000)
            writer.write(build_event(
                store_id   = store_id,
                camera_id  = camera_id,
                visitor_id = session.visitor_id,
                event_type = "ZONE_EXIT",
                timestamp  = timestamp,
                zone_id    = session.current_zone,
                dwell_ms   = dwell_ms,
                is_staff   = session.is_staff,
                confidence = round(confidence, 3),
                session_seq = session.next_seq(),
            ))
        session.current_zone    = current_zone
        session.zone_entry_time = timestamp
        session.last_dwell_emit = None

        writer.write(build_event(
            store_id   = store_id,
            camera_id  = camera_id,
            visitor_id = session.visitor_id,
            event_type = "ZONE_ENTER",
            timestamp  = timestamp,
            zone_id    = current_zone,
            is_staff   = session.is_staff,
            confidence = round(confidence, 3),
            sku_zone   = sku_zone,
            session_seq = session.next_seq(),
        ))

    elif session.zone_entry_time:
        last = session.last_dwell_emit or session.zone_entry_time
        if (timestamp - last).total_seconds() >= 30:
            dwell_ms = int((timestamp - session.zone_entry_time).total_seconds() * 1000)
            writer.write(build_event(
                store_id   = store_id,
                camera_id  = camera_id,
                visitor_id = session.visitor_id,
                event_type = "ZONE_DWELL",
                timestamp  = timestamp,
                zone_id    = current_zone,
                dwell_ms   = dwell_ms,
                is_staff   = session.is_staff,
                confidence = round(confidence, 3),
                sku_zone   = sku_zone,
                session_seq = session.next_seq(),
            ))
            session.last_dwell_emit = timestamp


def _handle_disappeared_tracks(disappeared, current_ids, session_mgr,
                                reid_mgr, writer, store_id, camera_id,
                                cam_type, timestamp, dwell_state):
    for track_id in disappeared:
        session = session_mgr.get(track_id)
        if not session:
            continue

        if cam_type in ("floor", "billing") and session.current_zone:
            dwell_ms = int(
                (timestamp - (session.zone_entry_time or timestamp)).total_seconds() * 1000
            )
            writer.write(build_event(
                store_id   = store_id,
                camera_id  = camera_id,
                visitor_id = session.visitor_id,
                event_type = "ZONE_EXIT",
                timestamp  = timestamp,
                zone_id    = session.current_zone,
                dwell_ms   = dwell_ms,
                is_staff   = session.is_staff,
                confidence = 0.5,
                session_seq = session.next_seq(),
            ))

        session_mgr.remove(track_id)


def main():
    parser = argparse.ArgumentParser(description="Store Intelligence Detection Pipeline")
    parser.add_argument("--clips",  default="data/clips",
                        help="Folder containing video clips")
    parser.add_argument("--output", default="data/events.jsonl",
                        help="Output JSONL file path")
    parser.add_argument("--layout", default="pipeline/config/store_layout.json",
                        help="Store layout JSON config")
    parser.add_argument("--api",    default=None,
                        help="API base URL (optional, e.g. http://localhost:8000)")
    parser.add_argument("--model",  default="yolov8m.pt",
                        help="YOLOv8 model weights (downloaded automatically)")
    args = parser.parse_args()

    print("=" * 60)
    print("Store Intelligence Detection Pipeline")
    print("=" * 60)

    layout = load_layout(args.layout)
    print(f"Store:  {layout['store_id']} / {layout['store_name']}")
    print(f"Date:   {layout.get('date', 'unknown')}")
    print(f"Clips:  {args.clips}")
    print(f"Output: {args.output}")
    print()

    from ultralytics import YOLO
    print("Loading YOLOv8m model...")
    model = YOLO(args.model)
    print("Model ready.")
    print()

    api_ingest_url = f"{args.api}/events/ingest" if args.api else None
    writer  = EventWriter(args.output, api_ingest_url)
    reid_mgr = ReIDManager(similarity_threshold=0.72, reentry_window_seconds=1800)

    clips_dir = Path(args.clips)

    for cam_cfg in layout["cameras"]:
        clip_file = clips_dir / cam_cfg["clip_filename"]

        if not clip_file.exists():
            print(f"  ⚠ Clip not found: {clip_file} — skipping {cam_cfg['camera_id']}")
            continue

        print(f"\n[{cam_cfg['camera_id']}] {cam_cfg.get('type','floor').upper()} CAMERA")
        process_clip(
            clip_path  = str(clip_file),
            camera_cfg = cam_cfg,
            layout     = layout,
            writer     = writer,
            reid_mgr   = reid_mgr,
            model      = model,
        )

    writer.close()
    print()
    print("=" * 60)
    print(f"Pipeline complete. Events written to: {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()