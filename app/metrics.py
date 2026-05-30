# app/metrics.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models   import MetricsResponse

router = APIRouter()

@router.get("/stores/{store_id}/metrics", response_model=MetricsResponse)
def get_metrics(store_id: str, date: str | None = None, db: Session = Depends(get_db)):
    target_date = date or datetime.utcnow().date().isoformat()
    # ── STUB: real logic added in Phase 3 ─────────────────────────────────────
    return MetricsResponse(
        store_id           = store_id,
        date               = target_date,
        unique_visitors    = 0,
        conversion_rate    = 0.0,
        avg_dwell_per_zone = [],
        queue_depth        = 0,
        abandonment_rate   = 0.0,
    )