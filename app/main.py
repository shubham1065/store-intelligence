
import time
import uuid
import logging
import csv
from datetime import datetime, timezone
from pathlib import Path
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError
from app.database import create_tables, engine, SessionLocal, POSTransactionORM
from app.ingestion import router as ingest_router
from app.health    import router as health_router
from app.metrics   import router as metrics_router
from app.funnel    import router as funnel_router
from app.heatmap   import router as heatmap_router
from app.anomalies import router as anomalies_router
from app.pos import router as pos_router

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


app = FastAPI(
    title="Store Intelligence API",
    description="Real-time retail analytics from CCTV event streams",
    version="1.0.0",
)

# CORS — allow dashboard to call API from any origin (file://, localhost, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(funnel_router)
app.include_router(heatmap_router)
app.include_router(anomalies_router)
app.include_router(pos_router)  

@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "Store Intelligence API is online",
        "docs": "Navigate to /docs for interactive API documentation",
        "dashboard": "Navigate to /dashboard for the live analytics dashboard",
        "status": "operational"
    }

@app.get("/dashboard", tags=["Dashboard"], response_class=HTMLResponse)
async def dashboard():
    """Serve the live analytics dashboard."""
    dashboard_path = Path(__file__).parent.parent / "dashboard" / "index.html"
    if dashboard_path.exists():
        return HTMLResponse(content=dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Dashboard not found</h1><p>Place index.html in dashboard/</p>", status_code=404)
    
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

@app.exception_handler(OperationalError)
async def db_error_handler(request: Request, exc: OperationalError):
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

@app.on_event("startup")
def on_startup():
    create_tables()
    logger.info("database_tables_ready")

    # Copy sample_events files to submission directory
    try:
        import shutil
        src_dir = Path(__file__).parent.parent / "data"
        dest_dir = Path(__file__).parent.parent / "submission"
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        for name in ["sample_events.jsonl", "sample_events_store2.jsonl"]:
            src_file = src_dir / name
            dest_file = dest_dir / name
            if src_file.exists():
                shutil.copy2(src_file, dest_file)
                logger.info("deliverable_copied", src=str(src_file), dest=str(dest_file))
    except Exception as e:
        logger.error("deliverable_copy_failed", error=str(e))

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
                loaded += 1
            db.commit()
        logger.info("pos_transactions_loaded", loaded=loaded, skipped=skipped)
    except Exception as e:
        db.rollback()
        logger.error("pos_load_failed", error=str(e))
    finally:
        db.close()