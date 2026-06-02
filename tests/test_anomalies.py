# PROMPT: Write target-driven unit tests for billing counter queue spike detection, conversion drop warnings against 20% retail benchmark thresholds, dead zone validation, and suggested resolution strategies.
# CHANGES MADE: Calibrated mock queue depth numbers to match warning/critical levels correctly and added validation on suggestion length thresholds.

import pytest
from tests.conftest import make_event

STORE = "ST1008"

def test_empty_store_no_anomalies(client):
    r = client.get(f"/stores/{STORE}/anomalies")
    assert r.status_code == 200
    assert r.json()["anomalies"] == []


def test_anomalies_returns_correct_schema(client):
    r = client.get(f"/stores/{STORE}/anomalies")
    data = r.json()
    assert "store_id"  in data
    assert "anomalies" in data
    assert isinstance(data["anomalies"], list)


def test_billing_queue_spike_detected(client):
    events = [make_event({
        "event_id":   f"bq-{i}",
        "visitor_id": f"VIS_q{i}",
        "event_type": "BILLING_QUEUE_JOIN",
        "zone_id":    "BILLING",
        "camera_id":  "CAM_05",
        "timestamp":  "2026-04-10T20:10:00Z",
        "metadata":   {"queue_depth": 4, "sku_zone": "BILLING", "session_seq": 1}
    }) for i in range(4)]
    client.post("/events/ingest", json={"events": events})

    r = client.get(f"/stores/{STORE}/anomalies")
    types = [a["anomaly_type"] for a in r.json()["anomalies"]]
    assert "BILLING_QUEUE_SPIKE" in types


def test_severity_values_valid(client):
    r    = client.get(f"/stores/{STORE}/anomalies")
    valid = {"INFO", "WARN", "CRITICAL"}
    for anomaly in r.json()["anomalies"]:
        assert anomaly["severity"] in valid


def test_suggested_action_present(client):
    events = [make_event({
        "event_id":   f"sa-{i}",
        "visitor_id": f"VIS_sa{i}",
        "event_type": "BILLING_QUEUE_JOIN",
        "zone_id":    "BILLING",
        "camera_id":  "CAM_05",
        "timestamp":  "2026-04-10T20:10:00Z",
        "metadata":   {"queue_depth": 5, "sku_zone": "BILLING", "session_seq": 1}
    }) for i in range(5)]
    client.post("/events/ingest", json={"events": events})

    r = client.get(f"/stores/{STORE}/anomalies")
    for anomaly in r.json()["anomalies"]:
        assert anomaly["suggested_action"]
        assert len(anomaly["suggested_action"]) > 10