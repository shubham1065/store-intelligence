# app/funnel.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models   import FunnelResponse, FunnelStage

router = APIRouter()

@router.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
def get_funnel(store_id: str, date: str | None = None, db: Session = Depends(get_db)):
    target_date = date or datetime.utcnow().date().isoformat()
    return FunnelResponse(
        store_id = store_id,
        date     = target_date,
        stages   = [
            FunnelStage(stage="entry",         count=0, drop_off_pct=0.0),
            FunnelStage(stage="zone_visit",    count=0, drop_off_pct=0.0),
            FunnelStage(stage="billing_queue", count=0, drop_off_pct=0.0),
            FunnelStage(stage="purchase",      count=0, drop_off_pct=0.0),
        ],
    )