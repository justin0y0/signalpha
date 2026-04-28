from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.backtest import BacktestRequest, BacktestResponse
from backend.app.services.backtest_service import BacktestService

router = APIRouter(prefix="/backtest", tags=["backtest"])
service = BacktestService()


@router.post("", response_model=BacktestResponse)
def run_backtest(request: BacktestRequest, db: Session = Depends(get_db)) -> BacktestResponse:
    return service.run(db, request)
