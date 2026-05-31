
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from datetime import datetime, timezone, timedelta

from app.database import get_db, EventORM
from app.models   import HealthResponse, StoreFeedStatus

router = APIRouter()

STALE_THRESHOLD_MINUTES = 10


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    # ── 1. Database liveness ──────────────────────────────────────────────────
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    # ── 2. Per-store feed freshness ───────────────────────────────────────────
    now      = datetime.now(tz=timezone.utc)
    cutoff   = now - timedelta(minutes=STALE_THRESHOLD_MINUTES)

    store_rows = (
        db.query(EventORM.store_id, func.max(EventORM.timestamp).label("last_ts"))
        .group_by(EventORM.store_id)
        .all()
    )

    store_feeds: dict[str, StoreFeedStatus] = {}
    stale_stores: list[str] = []

    for store_id, last_ts in store_rows:
        # SQLite returns naive datetimes — normalise
        if last_ts and last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)

        is_stale = (last_ts is None) or (last_ts < cutoff)
        status   = "STALE_FEED" if is_stale else "OK"

        store_feeds[store_id] = StoreFeedStatus(
            last_event_timestamp = last_ts.isoformat() if last_ts else None,
            status               = status,
        )
        if is_stale:
            stale_stores.append(store_id)

    overall = "healthy" if db_status == "healthy" else "degraded"

    return HealthResponse(
        status       = overall,
        database     = db_status,
        store_feeds  = store_feeds,
        stale_stores = stale_stores,
        checked_at   = now.isoformat(),
    )