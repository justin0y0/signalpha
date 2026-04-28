from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SectorPerformance(BaseModel):
    sector: str
    accuracy: float | None = None
    precision_weighted: float | None = None
    recall_weighted: float | None = None
    f1_weighted: float | None = None
    mae: float | None = None
    rmse: float | None = None
    sharpe_ratio: float | None = None
    recorded_at: datetime


class PerformanceResponse(BaseModel):
    model_version: str | None = None
    by_sector: list[SectorPerformance] = Field(default_factory=list)
    confusion_matrix: list[list[int]] = Field(default_factory=list)
    feature_importance: list[dict] = Field(default_factory=list)
