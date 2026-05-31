
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.database import get_db, EventORM
from app.metrics  import get_converted_visitors, get_default_date, get_unique_visitors
from app.models   import AnomalyResponse, Anomaly, AnomalySeverity

router = APIRouter()

ALL_ZONES = ["MAKEUP", "SKIN", "BATH_AND_BODY", "HAIR",
             "PERSONAL_CARE", "FRAGRANCE", "BILLING"]


@router.get("/stores/{store_id}/anomalies", response_model=AnomalyResponse)
def get_anomalies(store_id: str, db: Session = Depends(get_db)):
    anomalies  = []
    last_event = db.query(func.max(EventORM.timestamp))\
                   .filter(EventORM.store_id == store_id)\
                   .scalar()

    if last_event is None:
        return AnomalyResponse(store_id=store_id, anomalies=[])

    if hasattr(last_event, 'tzinfo') and last_event.tzinfo is None:
        last_event = last_event.replace(tzinfo=timezone.utc)

    now        = last_event          
    thirty_ago = now - timedelta(minutes=30)
    target_date = get_default_date(db, store_id)

    # ── 1. Billing queue spike ─────────────────────────────────────────────
    recent_max = db.query(func.max(EventORM.queue_depth))\
                   .filter(
                       EventORM.store_id   == store_id,
                       EventORM.event_type == "BILLING_QUEUE_JOIN",
                       EventORM.timestamp  >= now - timedelta(minutes=10)
                   ).scalar() or 0

    if recent_max >= 3:
        sev = AnomalySeverity.CRITICAL if recent_max >= 6 else AnomalySeverity.WARN
        anomalies.append(Anomaly(
            anomaly_type     = "BILLING_QUEUE_SPIKE",
            severity         = sev,
            description      = f"Queue reached {recent_max} customers in last 10 min",
            value            = float(recent_max),
            suggested_action = "Open an additional billing counter immediately",
            detected_at      = now.isoformat()
        ))

    # ── 2. Conversion rate drop vs 20% retail benchmark ───────────────────
    total     = get_unique_visitors(db, store_id, target_date)
    converted = len(get_converted_visitors(db, store_id, target_date))
    rate      = converted / total if total > 0 else 0.0

    if total >= 5 and rate < 0.12:   # below 12% = flag
        anomalies.append(Anomaly(
            anomaly_type     = "CONVERSION_DROP",
            severity         = AnomalySeverity.WARN,
            description      = f"Conversion {rate:.1%} is below 20% retail benchmark",
            value            = round(rate, 4),
            suggested_action = "Review promotions and staff placement near billing zone",
            detected_at      = now.isoformat()
        ))

    # ── 3. Dead zone — no visits in last 30 min ───────────────────────────
    thirty_ago   = now - timedelta(minutes=30)
    active_zones = {
        z[0] for z in
        db.query(distinct(EventORM.zone_id))\
          .filter(
              EventORM.store_id   == store_id,
              EventORM.event_type == "ZONE_ENTER",
              EventORM.is_staff   == False,
              EventORM.timestamp  >= thirty_ago
          ).all()
        if z[0]
    }

    for zone in ALL_ZONES:
        if zone in active_zones:
            continue
        ever = db.query(func.count(EventORM.event_id))\
                 .filter(
                     EventORM.store_id  == store_id,
                     EventORM.zone_id   == zone,
                     EventORM.is_staff  == False,
                     func.date(EventORM.timestamp) == target_date
                 ).scalar() or 0
        if ever > 0:
            anomalies.append(Anomaly(
                anomaly_type     = "DEAD_ZONE",
                severity         = AnomalySeverity.INFO,
                description      = f"{zone} had no visits in 30+ minutes",
                zone_id          = zone,
                suggested_action = f"Move a promotional display to {zone} to drive traffic",
                detected_at      = now.isoformat()
            ))

    return AnomalyResponse(store_id=store_id, anomalies=anomalies)