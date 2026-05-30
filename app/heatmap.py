# app/heatmap.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models   import HeatmapResponse

router = APIRouter()

@router.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
def get_heatmap(store_id: str, db: Session = Depends(get_db)):
    return HeatmapResponse(store_id=store_id, zones=[])