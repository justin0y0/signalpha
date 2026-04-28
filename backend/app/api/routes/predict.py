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
        return service.get_prediction(db, ticker=ticker, earnings_date=earnings_date)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Model artifacts are missing; run monthly retraining first.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
