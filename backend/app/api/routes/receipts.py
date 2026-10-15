from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.services import lookup_service, receipts_service, today_service

router = APIRouter(tags=["receipts"])

# Receipts mark every open call to the latest close; a short cache keeps a burst of
# visitors from re-downloading the same bars.
_cache: dict[str, Any] = {"at": 0.0, "body": None}


@router.get("/receipts")
def get_receipts(db: Session = Depends(get_db)):
    if _cache["body"] is not None and time.time() - _cache["at"] < 300:
        return _cache["body"]
    body = receipts_service.receipts(db)
    _cache.update(at=time.time(), body=body)
    return body


@router.get("/today")
def get_today(db: Session = Depends(get_db)):
    return today_service.today(db)


@router.get("/search")
def search(q: str = Query("", max_length=40), limit: int = Query(12, ge=1, le=30), db: Session = Depends(get_db)):
    return {"results": lookup_service.search(db, q, limit)}


@router.get("/lookup/{ticker}")
def lookup(ticker: str, db: Session = Depends(get_db)):
    if not ticker.replace("-", "").replace(".", "").isalpha() or len(ticker) > 8:
        raise HTTPException(400, "not a ticker")
    try:
        return lookup_service.lookup(db, ticker)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
