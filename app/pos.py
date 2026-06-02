from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import List
from pydantic import BaseModel
from app.database import get_db, POSTransactionORM

router = APIRouter()

class POSTransaction(BaseModel):
    transaction_id:   str
    store_id:         str
    timestamp:        datetime
    basket_value_inr: float

class POSLoadRequest(BaseModel):
    transactions: List[POSTransaction]

class POSLoadResponse(BaseModel):
    loaded:     int
    duplicates: int


@router.post("/pos/load", response_model=POSLoadResponse)
def load_pos_transactions(payload: POSLoadRequest, db: Session = Depends(get_db)):
    loaded, duplicates = 0, 0

    for txn in payload.transactions:
        if db.get(POSTransactionORM, txn.transaction_id):
            duplicates += 1
            continue

        ts = txn.timestamp
        db.add(POSTransactionORM(
            transaction_id   = txn.transaction_id,
            store_id         = txn.store_id,
            timestamp        = ts,
            basket_value_inr = txn.basket_value_inr,
        ))
        loaded += 1

    db.commit()
    return POSLoadResponse(loaded=loaded, duplicates=duplicates)