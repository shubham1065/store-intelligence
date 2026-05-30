# app/main.py

import time
import uuid
import logging
import csv
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.database import create_tables, engine, SessionLocal, POSTransactionORM
from app.ingestion import router as ingest_router
from app.health    import router as health_router
from app.metrics   import router as metrics_router
from app.funnel    import router as funnel_router
from app.heatmap   import router as heatmap_router
from app.anomalies import router as anomalies_router


# ─── Logging Setup ────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(message)s",
    level=logging.INFO,
)

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Store Intelligence API",
    description="Real-time retail analytics from CCTV event streams",
    version="1.0.0",
)


# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(ingest_router)
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(funnel_router)
app.include_router(heatmap_router)
app.include_router(anomalies_router)


# ─── Middleware ───────────────────────────────────────────────────────────────
@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "Store Intelligence API is online",
        "docs": "Navigate to /docs for interactive API documentation",
        "status": "operational"
    }
    
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    store_id = request.path_params.get("store_id", "N/A")
    start    = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error("unhandled_exception",
            trace_id=trace_id, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "An unexpected error occurred."},
        )

    latency_ms = int((time.perf_counter() - start) * 1000)

    # Read event_count from response header if ingest set it
    event_count = response.headers.get("X-Event-Count", "N/A")

    logger.info("request",
        trace_id=trace_id,
        store_id=store_id,
        endpoint=str(request.url.path),
        method=request.method,
        latency_ms=latency_ms,
        event_count=event_count,
        status_code=response.status_code,
    )

    response.headers["X-Trace-ID"] = trace_id
    return response


# ─── Exception Handlers ───────────────────────────────────────────────────────

@app.exception_handler(OperationalError)
async def db_error_handler(request: Request, exc: OperationalError):
    # Database is down → 503 with structured body (never a raw traceback)
    logger.error("database_unavailable", error=str(exc))
    return JSONResponse(
        status_code=503,
        content={
            "error":       "database_unavailable",
            "message":     "The database is temporarily unavailable. Please retry.",
            "retry_after": 30,
        },
    )

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), path=str(request.url))
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "An unexpected error occurred."},
    )


# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    # Create tables if they don't exist yet
    create_tables()
    logger.info("database_tables_ready")

    # Auto-load POS transactions CSV if present in /data
    pos_csv = Path("/data/pos_transactions.csv")
    if pos_csv.exists():
        _load_pos_csv(pos_csv)
    else:
        logger.info("pos_csv_not_found", path=str(pos_csv),
                    note="Place pos_transactions.csv in /data/ to load it")


def _load_pos_csv(path: Path):
    db = SessionLocal()
    loaded, skipped = 0, 0
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing = db.get(POSTransactionORM, row["transaction_id"])
                if existing:
                    skipped += 1
                    continue
                txn = POSTransactionORM(
                    transaction_id=row["transaction_id"],
                    store_id=row["store_id"],
                    timestamp=datetime.fromisoformat(
                        row["timestamp"].replace("Z", "+00:00")
                    ),
                    basket_value_inr=float(row["basket_value_inr"]),
                )
                db.add(txn)
            db.commit()
        logger.info("pos_transactions_loaded", loaded=loaded, skipped=skipped)
    except Exception as e:
        db.rollback()
        logger.error("pos_load_failed", error=str(e))
    finally:
        db.close()