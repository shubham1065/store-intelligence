import pytest
from tests.conftest import make_event

STORE = "ST1008"

def seed_zone_event(client, visitor_id, zone, event_id):
    client.post("/events/ingest", json={"events": [
        make_event({
            "event_id":   event_id,
            "visitor_id": visitor_id,
            "event_type": "ZONE_ENTER",
            "zone_id":    zone,
            "camera_id":  "CAM_02",
            "timestamp":  "2026-04-10T20:05:00Z",
            "metadata":   {"queue_depth": None, "sku_zone": zone, "session_seq": 1}
        })
    ]})


def test_empty_store_returns_zeros(client):
    r = client.get(f"/stores/{STORE}/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["unique_visitors"]  == 0
    assert data["conversion_rate"]  == 0.0
    assert data["queue_depth"]      == 0
    assert data["abandonment_rate"] == 0.0


def test_unique_visitors_excludes_staff(client):
    customer = make_event({"event_id": "c-001", "visitor_id": "VIS_cust",
                           "is_staff": False})
    staff    = make_event({"event_id": "s-001", "visitor_id": "VIS_staff",
                           "is_staff": True})
    client.post("/events/ingest", json={"events": [customer, staff]})

    r = client.get(f"/stores/{STORE}/metrics")
    assert r.json()["unique_visitors"] == 1   # staff not counted


def test_zone_dwell_populated(client):
    seed_zone_event(client, "VIS_001", "MAKEUP", "z-001")
    seed_zone_event(client, "VIS_002", "MAKEUP", "z-002")

    dwell_event = make_event({
        "event_id":   "z-003",
        "visitor_id": "VIS_001",
        "event_type": "ZONE_EXIT",
        "zone_id":    "MAKEUP",
        "camera_id":  "CAM_02",
        "dwell_ms":   8000,
        "timestamp":  "2026-04-10T20:06:00Z",
        "metadata":   {"queue_depth": None, "sku_zone": "MAKEUP", "session_seq": 2}
    })
    client.post("/events/ingest", json={"events": [dwell_event]})

    r    = client.get(f"/stores/{STORE}/metrics")
    data = r.json()
    zone = next((z for z in data["avg_dwell_per_zone"]
                 if z["zone_id"] == "MAKEUP"), None)
    assert zone is not None
    assert zone["avg_dwell_ms"] == 8000.0


def test_zero_purchase_store(client):
    billing_event = make_event({
        "event_id":   "b-001",
        "visitor_id": "VIS_biller",
        "event_type": "BILLING_QUEUE_JOIN",
        "zone_id":    "BILLING",
        "camera_id":  "CAM_05",
        "timestamp":  "2026-04-10T20:09:00Z",
        "metadata":   {"queue_depth": 1, "sku_zone": "BILLING", "session_seq": 1}
    })
    client.post("/events/ingest", json={"events": [billing_event]})

    r = client.get(f"/stores/{STORE}/metrics")
    assert r.status_code  == 200
    assert r.json()["conversion_rate"] == 0.0


def test_metrics_with_date_param(client):
    client.post("/events/ingest", json={"events": [
        make_event({"event_id": "d-001", "timestamp": "2026-04-10T20:00:00Z"})
    ]})

    r1 = client.get(f"/stores/{STORE}/metrics?date=2026-04-10")
    assert r1.status_code == 200

    r2 = client.get(f"/stores/{STORE}/metrics?date=2025-01-01")
    assert r2.json()["unique_visitors"] == 0