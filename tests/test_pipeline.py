import uuid
import pytest
from datetime import datetime, timezone
import sys
from pathlib import Path
from pipeline.emit import build_event
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_event_id_is_unique():
    ts  = datetime.now(tz=timezone.utc)
    e1  = build_event("ST1008", "CAM_01", "VIS_001", "ENTRY", ts, confidence=0.9)
    e2  = build_event("ST1008", "CAM_01", "VIS_001", "ENTRY", ts, confidence=0.9)
    assert e1["event_id"] != e2["event_id"]


def test_event_id_is_valid_uuid():
    ts = datetime.now(tz=timezone.utc)
    e  = build_event("ST1008", "CAM_01", "VIS_001", "ENTRY", ts, confidence=0.9)
    uuid.UUID(e["event_id"])   # raises if invalid


def test_timestamp_is_utc_iso8601():
    ts = datetime.now(tz=timezone.utc)
    e  = build_event("ST1008", "CAM_01", "VIS_001", "ENTRY", ts, confidence=0.9)
    assert e["timestamp"].endswith("Z")
    datetime.strptime(e["timestamp"], "%Y-%m-%dT%H:%M:%SZ")  # raises if wrong format


def test_confidence_bounds():
    ts = datetime.now(tz=timezone.utc)
    e  = build_event("ST1008", "CAM_01", "VIS_001", "ENTRY", ts, confidence=0.75)
    assert 0.0 <= e["confidence"] <= 1.0


def test_invalid_event_type_raises():
    ts = datetime.now(tz=timezone.utc)
    with pytest.raises(AssertionError):
        build_event("ST1008", "CAM_01", "VIS_001", "INVALID_TYPE", ts, confidence=0.9)


def test_metadata_structure():
    ts = datetime.now(tz=timezone.utc)
    e  = build_event("ST1008", "CAM_05", "VIS_001", "BILLING_QUEUE_JOIN",
                     ts, zone_id="BILLING", confidence=0.88,
                     queue_depth=3, sku_zone="BILLING", session_seq=2)
    assert e["metadata"]["queue_depth"] == 3
    assert e["metadata"]["sku_zone"]    == "BILLING"
    assert e["metadata"]["session_seq"] == 2


def test_zone_dwell_has_dwell_ms():
    ts = datetime.now(tz=timezone.utc)
    e  = build_event("ST1008", "CAM_02", "VIS_001", "ZONE_DWELL",
                     ts, zone_id="MAKEUP", dwell_ms=30000, confidence=0.82)
    assert e["dwell_ms"] == 30000
    assert e["zone_id"]  == "MAKEUP"


def test_is_staff_is_boolean():
    ts = datetime.now(tz=timezone.utc)
    e  = build_event("ST1008", "CAM_01", "VIS_s01", "ENTRY",
                     ts, is_staff=True, confidence=0.91)
    assert e["is_staff"] is True
    assert isinstance(e["is_staff"], bool)