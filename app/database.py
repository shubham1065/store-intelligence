
from sqlalchemy import (
    create_engine, Column, String, Boolean,
    Float, Integer, DateTime, Index, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime
from typing import Generator
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/store.db")

# check_same_thread=False is required for SQLite with FastAPI
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,          # set True briefly if you want to see SQL queries
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─── ORM Models ───────────────────────────────────────────────────────────────

class EventORM(Base):
    __tablename__ = "events"

    event_id    = Column(String,  primary_key=True)           # idempotency key
    store_id    = Column(String,  nullable=False)
    camera_id   = Column(String,  nullable=False)
    visitor_id  = Column(String,  nullable=False)
    event_type  = Column(String,  nullable=False)
    timestamp   = Column(DateTime(timezone=True), nullable=False)
    zone_id     = Column(String,  nullable=True)
    dwell_ms    = Column(Integer, default=0)
    is_staff    = Column(Boolean, default=False)
    confidence  = Column(Float,   nullable=False)
    # metadata fields stored flat — simpler to query than JSON blob
    queue_depth = Column(Integer, nullable=True)
    sku_zone    = Column(String,  nullable=True)
    session_seq = Column(Integer, nullable=True)
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        # Critical: every metric query filters by (store_id, timestamp)
        Index("idx_store_ts",      "store_id", "timestamp"),
        # Re-entry and funnel queries filter by visitor
        Index("idx_visitor",       "visitor_id"),
        # Anomaly + metrics queries filter by event_type
        Index("idx_store_etype",   "store_id", "event_type"),
        # Zone heatmap queries
        Index("idx_store_zone",    "store_id", "zone_id"),
    )


class POSTransactionORM(Base):
    __tablename__ = "pos_transactions"

    transaction_id    = Column(String, primary_key=True)
    store_id          = Column(String, nullable=False)
    timestamp         = Column(DateTime(timezone=True), nullable=False)
    basket_value_inr  = Column(Float,  nullable=False)

    __table_args__ = (
        Index("idx_pos_store_ts", "store_id", "timestamp"),
    )


# ─── Session Dependency ───────────────────────────────────────────────────────

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    Base.metadata.create_all(bind=engine)


def check_db_connection() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False