from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


# ─── Enums ────────────────────────────────────────────────────────────────────

class EventType(str, Enum):
    ENTRY                 = "ENTRY"
    EXIT                  = "EXIT"
    ZONE_ENTER            = "ZONE_ENTER"
    ZONE_EXIT             = "ZONE_EXIT"
    ZONE_DWELL            = "ZONE_DWELL"
    BILLING_QUEUE_JOIN    = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY               = "REENTRY"

class AnomalySeverity(str, Enum):
    INFO     = "INFO"
    WARN     = "WARN"
    CRITICAL = "CRITICAL"


# ─── Ingest ───────────────────────────────────────────────────────────────────

class EventMetadata(BaseModel):
    queue_depth: Optional[int]  = None
    sku_zone:    Optional[str]  = None
    session_seq: Optional[int]  = None

class StoreEvent(BaseModel):
    event_id:   str        = Field(..., description="UUID v4 — globally unique")
    store_id:   str
    camera_id:  str
    visitor_id: str
    event_type: EventType
    timestamp:  datetime
    zone_id:    Optional[str]  = None
    dwell_ms:   int            = Field(default=0, ge=0)
    is_staff:   bool           = False
    confidence: float          = Field(..., ge=0.0, le=1.0)
    metadata:   EventMetadata  = Field(default_factory=EventMetadata)

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}

class EventBatch(BaseModel):
    events: List[StoreEvent]

    @field_validator("events")
    @classmethod
    def check_batch_size(cls, v):
        if len(v) > 500:
            raise ValueError("Batch cannot exceed 500 events")
        return v

class IngestResponse(BaseModel):
    total_received: int
    ingested:       int
    duplicates:     int
    errors:         List[Dict[str, Any]]


# ─── Metrics ──────────────────────────────────────────────────────────────────

class ZoneDwell(BaseModel):
    zone_id:      str
    avg_dwell_ms: float
    visit_count:  int

class MetricsResponse(BaseModel):
    store_id:          str
    date:              str
    unique_visitors:   int
    conversion_rate:   float
    avg_dwell_per_zone: List[ZoneDwell]
    queue_depth:       int
    abandonment_rate:  float


# ─── Funnel ───────────────────────────────────────────────────────────────────

class FunnelStage(BaseModel):
    stage:        str
    count:        int
    drop_off_pct: float

class FunnelResponse(BaseModel):
    store_id: str
    date:     str
    stages:   List[FunnelStage]


# ─── Heatmap ──────────────────────────────────────────────────────────────────

class HeatmapZone(BaseModel):
    zone_id:          str
    visit_count:      int
    avg_dwell_ms:     float
    normalized_score: float          # 0–100
    data_confidence:  bool           # False if < 20 sessions

class HeatmapResponse(BaseModel):
    store_id: str
    zones:    List[HeatmapZone]


# ─── Anomalies ────────────────────────────────────────────────────────────────

class Anomaly(BaseModel):
    anomaly_type:     str
    severity:         AnomalySeverity
    description:      str
    value:            Optional[float] = None
    zone_id:          Optional[str]   = None
    suggested_action: str
    detected_at:      str

class AnomalyResponse(BaseModel):
    store_id:  str
    anomalies: List[Anomaly]


# ─── Health ───────────────────────────────────────────────────────────────────

class StoreFeedStatus(BaseModel):
    last_event_timestamp: Optional[str]
    status:               str     # "OK" | "STALE_FEED" | "NO_DATA"

class HealthResponse(BaseModel):
    status:       str             # "healthy" | "degraded"
    database:     str             # "healthy" | "unhealthy"
    store_feeds:  Dict[str, StoreFeedStatus]
    stale_stores: List[str]
    checked_at:   str