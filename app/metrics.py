from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from datetime import timedelta
from typing import Optional

from app.database import get_db, EventORM, POSTransactionORM
from app.models   import MetricsResponse, ZoneDwell

router = APIRouter()

def get_default_date(db: Session, store_id: str) -> str:
    "Use most recent event date — not today's date."

    latest = db.query(func.max(EventORM.timestamp))\
               .filter(EventORM.store_id == store_id)\
               .scalar()
    if latest:
        ts = str(latest)[:10]
        return ts
    from datetime import date
    return date.today().isoformat()

def get_unique_visitors(db: Session, store_id: str, target_date: str) -> int:
    # Primary source: ENTRY events from entry camera
    entry_count = db.query(func.count(distinct(EventORM.visitor_id)))\
                    .filter(
                        EventORM.store_id   == store_id,
                        EventORM.event_type == "ENTRY",
                        EventORM.is_staff   == False,
                        func.date(EventORM.timestamp) == target_date
                    ).scalar() or 0

    # Fallback: count from floor zone events when entry camera
    # over-detects staff (common with broad HSV range).
    # Return the max of both counts — if entry camera missed visitors
    # (yields a very low count like 1), floor cameras give a truer count.
    fallback_count = db.query(func.count(distinct(EventORM.visitor_id)))\
                       .filter(
                           EventORM.store_id   == store_id,
                           EventORM.event_type.in_(["ZONE_ENTER", "ZONE_DWELL"]),
                           EventORM.is_staff   == False,
                           func.date(EventORM.timestamp) == target_date
                       ).scalar() or 0

    return max(entry_count, fallback_count)

def get_converted_visitors(db: Session, store_id: str, target_date: str) -> set:
    """
    Visitor is converted if they were in BILLING zone
    within 30 minutes BEFORE any transaction.
    Wider window handles short clips that don't perfectly
    align with transaction timestamps.
    """
    
    transactions = db.query(POSTransactionORM)\
                     .filter(
                         POSTransactionORM.store_id == store_id,
                         func.date(POSTransactionORM.timestamp) == target_date
                     ).all()

    converted = set()
    for txn in transactions:
        window_start = txn.timestamp - timedelta(minutes=30)
        visitors = db.query(distinct(EventORM.visitor_id))\
                     .filter(
                         EventORM.store_id  == store_id,
                         EventORM.zone_id   == "BILLING",
                         EventORM.is_staff  == False,
                         EventORM.timestamp >= window_start,
                         EventORM.timestamp <= txn.timestamp
                     ).all()
        converted.update(v[0] for v in visitors)
    return converted


def get_avg_dwell_per_zone(db: Session, store_id: str, target_date: str) -> list:
    rows = db.query(
        EventORM.zone_id,
        func.avg(EventORM.dwell_ms).label("avg_dwell"),
        func.count(EventORM.event_id).label("visit_count")
    ).filter(
        EventORM.store_id   == store_id,
        EventORM.event_type.in_(["ZONE_EXIT", "ZONE_DWELL"]),
        EventORM.is_staff   == False,
        EventORM.zone_id    != None,
        func.date(EventORM.timestamp) == target_date
    ).group_by(EventORM.zone_id).all()

    return [
        ZoneDwell(
            zone_id      = r.zone_id,
            avg_dwell_ms = round(float(r.avg_dwell or 0), 2),
            visit_count  = r.visit_count
        ) for r in rows if r.zone_id
    ]


def get_queue_depth(db: Session, store_id: str) -> int:
    row = db.query(EventORM.queue_depth)\
            .filter(
                EventORM.store_id   == store_id,
                EventORM.event_type == "BILLING_QUEUE_JOIN",
                EventORM.queue_depth != None
            ).order_by(EventORM.timestamp.desc()).first()
    return int(row[0]) if row else 0


def get_abandonment_rate(db: Session, store_id: str, target_date: str) -> float:
    joins = db.query(func.count(EventORM.event_id))\
              .filter(
                  EventORM.store_id   == store_id,
                  EventORM.event_type == "BILLING_QUEUE_JOIN",
                  EventORM.is_staff   == False,
                  func.date(EventORM.timestamp) == target_date
              ).scalar() or 0
    if joins == 0:
        return 0.0
    abandons = db.query(func.count(EventORM.event_id))\
                 .filter(
                     EventORM.store_id   == store_id,
                     EventORM.event_type == "BILLING_QUEUE_ABANDON",
                     EventORM.is_staff   == False,
                     func.date(EventORM.timestamp) == target_date
                 ).scalar() or 0
    return round(abandons / joins, 4)


@router.get("/stores/{store_id}/metrics", response_model=MetricsResponse)
def get_metrics(
    store_id: str,
    date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    target_date     = date or get_default_date(db, store_id)
    unique_visitors = get_unique_visitors(db, store_id, target_date)
    converted       = get_converted_visitors(db, store_id, target_date)
    conversion_rate = round(len(converted) / unique_visitors, 4) \
                      if unique_visitors > 0 else 0.0

    return MetricsResponse(
        store_id           = store_id,
        date               = target_date,
        unique_visitors    = unique_visitors,
        conversion_rate    = conversion_rate,
        avg_dwell_per_zone = get_avg_dwell_per_zone(db, store_id, target_date),
        queue_depth        = get_queue_depth(db, store_id),
        abandonment_rate   = get_abandonment_rate(db, store_id, target_date),
    )