import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main     import app
from app.database import Base, get_db

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture
def client():
    
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def make_event(overrides: dict = {}) -> dict:
    
    base = {
        "event_id":   "550e8400-e29b-41d4-a716-446655440000",
        "store_id":   "ST1008",
        "camera_id":  "CAM_01",
        "visitor_id": "VIS_test001",
        "event_type": "ENTRY",
        "timestamp":  "2026-04-10T20:00:00Z",
        "dwell_ms":   0,
        "is_staff":   False,
        "confidence": 0.91,
        "metadata":   {"queue_depth": None, "sku_zone": None, "session_seq": 1}
    }
    base.update(overrides)
    return base