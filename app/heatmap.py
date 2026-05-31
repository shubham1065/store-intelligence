
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from typing import Optional

from app.database import get_db, EventORM
from app.metrics  import get_default_date
from app.models   import HeatmapResponse, HeatmapZone

router = APIRouter()


@router.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
def get_heatmap(
    store_id: str,
    date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    target_date = date or get_default_date(db, store_id)

    rows = db.query(
        EventORM.zone_id,
        func.count(distinct(EventORM.visitor_id)).label("visit_count"),
        func.avg(EventORM.dwell_ms).label("avg_dwell")
    ).filter(
        EventORM.store_id   == store_id,
        EventORM.event_type.in_(["ZONE_ENTER", "ZONE_DWELL", "ZONE_EXIT"]),
        EventORM.is_staff   == False,
        EventORM.zone_id    != None,
        func.date(EventORM.timestamp) == target_date
    ).group_by(EventORM.zone_id).all()

    if not rows:
        return HeatmapResponse(store_id=store_id, zones=[])

    max_visits = max(r.visit_count for r in rows) or 1

    total_sessions = db.query(func.count(distinct(EventORM.visitor_id)))\
                       .filter(
                           EventORM.store_id  == store_id,
                           EventORM.is_staff  == False,
                           func.date(EventORM.timestamp) == target_date
                       ).scalar() or 0

    zones = [
        HeatmapZone(
            zone_id          = r.zone_id,
            visit_count      = r.visit_count,
            avg_dwell_ms     = round(float(r.avg_dwell or 0), 2),
            normalized_score = round((r.visit_count / max_visits) * 100, 1),
            data_confidence  = total_sessions >= 20
        )
        for r in rows if r.zone_id
    ]
    zones.sort(key=lambda z: z.normalized_score, reverse=True)
    return HeatmapResponse(store_id=store_id, zones=zones)