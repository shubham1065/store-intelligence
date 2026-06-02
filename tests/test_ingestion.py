# PROMPT: Generate complete Pytest endpoint tests for event batch ingestion, covering idempotency checks on primary keys, payload batch size constraints of 500 records, schema validation on partial failures, and visitor reentry edge cases.
# CHANGES MADE: Standardized mock event factory values and adapted assertions to use custom response models.

import pytest
from tests.conftest import make_event

def test_ingest_happy_path(client):
    event = make_event()
    r = client.post("/events/ingest", json={"events": [event]})
    assert r.status_code == 200
    data = r.json()
    assert data["ingested"]       == 1
    assert data["duplicates"]     == 0
    assert data["total_received"] == 1
    assert data["errors"]         == []

def test_ingest_idempotency(client):
    event = make_event()
    client.post("/events/ingest", json={"events": [event]})
    r = client.post("/events/ingest", json={"events": [event]})
    assert r.status_code == 200
    data = r.json()
    assert data["ingested"]   == 0
    assert data["duplicates"] == 1
    assert data["errors"]     == []


def test_ingest_batch_limit(client):
    events = [make_event({"event_id": f"id-{i}"}) for i in range(501)]
    r = client.post("/events/ingest", json={"events": events})
    assert r.status_code == 422


def test_ingest_empty_batch(client):
    r = client.post("/events/ingest", json={"events": []})
    assert r.status_code == 200
    data = r.json()
    assert data["ingested"]       == 0
    assert data["total_received"] == 0


def test_ingest_partial_success(client):
    good = make_event({"event_id": "good-001"})
    bad  = make_event({"event_id": "bad-001", "confidence": 99.9})  # out of range
    r = client.post("/events/ingest", json={"events": [good, bad]})
    assert r.status_code == 422  # Pydantic rejects at schema level


def test_ingest_all_staff_batch(client):
    events = [
        make_event({"event_id": f"staff-{i}", "visitor_id": f"VIS_staff{i}",
                    "is_staff": True})
        for i in range(5)
    ]
    r = client.post("/events/ingest", json={"events": events})
    assert r.status_code == 200
    assert r.json()["ingested"] == 5

    m = client.get("/stores/ST1008/metrics").json()
    assert m["unique_visitors"] == 0


def test_ingest_reentry_same_visitor(client):
    entry   = make_event({"event_id": "e-001", "event_type": "ENTRY",
                          "visitor_id": "VIS_returning"})
    reentry = make_event({"event_id": "e-002", "event_type": "REENTRY",
                          "visitor_id": "VIS_returning",
                          "timestamp": "2026-04-10T20:30:00Z"})
    client.post("/events/ingest", json={"events": [entry, reentry]})

    f = client.get("/stores/ST1008/funnel").json()
    entry_stage = next(s for s in f["stages"] if s["stage"] == "entry")
    assert entry_stage["count"] == 1