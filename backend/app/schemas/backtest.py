from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    ticker: str | None = None
    sector: str | None = None
    start_date: date
    end_date: date
    probability_threshold: float = 0.55


class EquityPoint(BaseModel):
    date: date
    equity: float


class BacktestResponse(BaseModel):
    total_samples: int
    accuracy: float
    precision_weighted: float
    recall_weighted: float
    f1_weighted: float
    sharpe_ratio: float
    mae: float | None = None
    rmse: float | None = None
    confusion_matrix: list[list[int]] = Field(default_factory=list)
    equity_curve: list[EquityPoint] = Field(default_factory=list)
