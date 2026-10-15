from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.performance import PerformanceResponse
from backend.app.services.performance_service import PerformanceService

router = APIRouter(prefix="/performance", tags=["performance"])
service = PerformanceService()


_cache: dict = {"at": 0.0, "body": None}


@router.get("", response_model=PerformanceResponse)
def get_performance(db: Session = Depends(get_db)) -> PerformanceResponse:
    # Recomputed from every graded prediction; it only changes after a retrain.
    if _cache["body"] is None or time.time() - _cache["at"] > 600:
        _cache.update(at=time.time(), body=service.latest(db))
    return _cache["body"]
