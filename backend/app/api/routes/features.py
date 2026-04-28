from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.services.feature_service import FeatureService

router = APIRouter(prefix="/features", tags=["features"])
service = FeatureService()


@router.get("/{ticker}")
def get_features(
    ticker: str,
    earnings_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return service.get_feature_snapshot(db, ticker, earnings_date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
