from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.performance import PerformanceResponse
from backend.app.services.performance_service import PerformanceService

router = APIRouter(prefix="/performance", tags=["performance"])
service = PerformanceService()


@router.get("", response_model=PerformanceResponse)
def get_performance(db: Session = Depends(get_db)) -> PerformanceResponse:
    return service.latest(db)
