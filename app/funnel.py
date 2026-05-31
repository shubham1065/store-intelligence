
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from typing import Optional
from app.database import get_db, EventORM
from app.models   import FunnelResponse, FunnelStage
from app.metrics import get_converted_visitors, get_default_date, get_unique_visitors
router = APIRouter()

@router.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
def get_funnel(store_id: str, date: Optional[str] = None, db: Session = Depends(get_db)):
    target_date = date or get_default_date(db, store_id)

    # Stage 1 — reuse same logic as /metrics (includes fallback)
    total = get_unique_visitors(db, store_id, target_date)

    # Stage 2 — visited at least one zone
    zone_visitors = db.query(func.count(distinct(EventORM.visitor_id)))\
                      .filter(
                          EventORM.store_id   == store_id,
                          EventORM.event_type == "ZONE_ENTER",
                          EventORM.is_staff   == False,
                          func.date(EventORM.timestamp) == target_date
                      ).scalar() or 0

    # Stage 3 — reached billing
    billing_visitors = db.query(func.count(distinct(EventORM.visitor_id)))\
                         .filter(
                             EventORM.store_id  == store_id,
                             EventORM.zone_id   == "BILLING",
                             EventORM.is_staff  == False,
                             func.date(EventORM.timestamp) == target_date
                         ).scalar() or 0

    # Stage 4 — purchased
    converted = len(get_converted_visitors(db, store_id, target_date))

    def drop(current, previous):
        if previous == 0:
            return 0.0
        return round((previous - current) / previous * 100, 1)

    return FunnelResponse(
        store_id = store_id,
        date     = target_date,
        stages   = [
            FunnelStage(stage="entry",         count=total,            drop_off_pct=0.0),
            FunnelStage(stage="zone_visit",    count=zone_visitors,    drop_off_pct=drop(zone_visitors, total)),
            FunnelStage(stage="billing_queue", count=billing_visitors, drop_off_pct=drop(billing_visitors, billing_visitors)),
            FunnelStage(stage="purchase",      count=converted,        drop_off_pct=drop(converted, billing_visitors)),
        ]
    )