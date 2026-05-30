# app/ingestion.py

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.database import get_db, EventORM
from app.models   import EventBatch, IngestResponse, StoreEvent

router = APIRouter()


def _event_to_orm(event: StoreEvent) -> EventORM:
    """Convert a validated Pydantic StoreEvent into an ORM row."""
    ts = event.timestamp
    # Normalise to UTC-aware datetime regardless of how the pipeline emits it
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    return EventORM(
        event_id    = event.event_id,
        store_id    = event.store_id,
        camera_id   = event.camera_id,
        visitor_id  = event.visitor_id,
        event_type  = event.event_type.value,
        timestamp   = ts,
        zone_id     = event.zone_id,
        dwell_ms    = event.dwell_ms,
        is_staff    = event.is_staff,
        confidence  = event.confidence,
        queue_depth = event.metadata.queue_depth,
        sku_zone    = event.metadata.sku_zone,
        session_seq = event.metadata.session_seq,
        ingested_at = datetime.now(tz=timezone.utc),
    )


@router.post("/events/ingest", response_model=IngestResponse)
def ingest_events(
    payload:  EventBatch,
    response: Response,
    db:       Session = Depends(get_db),
):
    ingested   = 0
    duplicates = 0
    errors     = []

    for event in payload.events:
        try:
            # ── Idempotency check (event_id is PRIMARY KEY) ──────────────────
            if db.get(EventORM, event.event_id):
                duplicates += 1
                continue

            db.add(_event_to_orm(event))
            db.flush()   # write to transaction buffer; catch errors per-row
            ingested += 1

        except Exception as exc:
            db.rollback()   # roll back only the failed row's flush
            errors.append({
                "event_id": event.event_id,
                "reason":   str(exc),
            })

    # Commit everything that succeeded
    db.commit()

    # Expose event count for the logging middleware
    response.headers["X-Event-Count"] = str(ingested)

    return IngestResponse(
        total_received = len(payload.events),
        ingested       = ingested,
        duplicates     = duplicates,
        errors         = errors,
    )