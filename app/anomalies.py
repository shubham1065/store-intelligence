# app/anomalies.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models   import AnomalyResponse

router = APIRouter()

@router.get("/stores/{store_id}/anomalies", response_model=AnomalyResponse)
def get_anomalies(store_id: str, db: Session = Depends(get_db)):
    return AnomalyResponse(store_id=store_id, anomalies=[])