from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import Settings, get_db, get_settings
from backend.app.schemas.prediction import PredictionResponse
from backend.app.services.prediction_service import PredictionService

router = APIRouter(prefix="/predict", tags=["predict"])


@router.get("/{ticker}", response_model=PredictionResponse)
def get_prediction(
    ticker: str,
    earnings_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PredictionResponse:
    service = PredictionService(settings)
    try:
        res = service.get_prediction(db, ticker=ticker, earnings_date=earnings_date)
        # Shown sector: the universe's (Yahoo-corrected) one. The event keeps the sector its
        # features were built with, which for some companies is NASDAQ's screener guess
        # (TSLA "Industrials", Visa "Consumer Cyclical").
        from sqlalchemy import text
        sec = db.execute(text("SELECT sector FROM universe WHERE ticker=:t"), {"t": ticker.upper()}).scalar()
        if sec and getattr(res, "sector", None) is not None and sec != res.sector:
            res.sector = sec
        return res
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Model artifacts are missing; run monthly retraining first.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{ticker}/schedule")
def get_schedule(ticker: str, db: Session = Depends(get_db)):
    """Last and next earnings, to the minute where knowable (SEC 8-K acceptance time), with the
    last report's sealed calls against what happened."""
    from backend.app.services.schedule_service import schedule

    return schedule(db, ticker)
