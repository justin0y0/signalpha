from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from backend.app.schemas.common import DataCompletenessWarning


class DirectionProbabilities(BaseModel):
    up: float = 0.0
    flat: float = 0.0
    down: float = 0.0


class ExpectedMove(BaseModel):
    point_estimate_pct: float | None = None
    low_pct: float | None = None
    high_pct: float | None = None
    historical_avg_pct: float | None = None


class ConvergenceBand(BaseModel):
    lower: float | None = None
    upper: float | None = None
    current_price: float | None = None
    horizon_days: int = 20


class DriverContribution(BaseModel):
    feature: str
    value: float | None = None
    contribution: float
    direction: str


class SimilarCase(BaseModel):
    ticker: str
    earnings_date: date
    sector: str | None = None
    similarity: float
    actual_t1_return: float | None = None
    actual_t5_return: float | None = None
    actual_t20_return: float | None = None


class HistoricalReaction(BaseModel):
    earnings_date: date
    reaction_pct: float | None = None
    beat_miss: str | None = None


class PredictionResponse(BaseModel):
    ticker: str
    company_name: str | None = None
    earnings_date: date
    report_time: str | None = None
    sector: str | None = None
    model_version: str | None = None
    direction_probabilities: DirectionProbabilities
    predicted_direction: str
    confidence_score: float
    expected_move: ExpectedMove
    convergence_band: ConvergenceBand
    data_completeness: float
    warnings: list[DataCompletenessWarning] = Field(default_factory=list)
    key_drivers: list[DriverContribution] = Field(default_factory=list)
    historical_reactions: list[HistoricalReaction] = Field(default_factory=list)
    similar_cases: list[SimilarCase] = Field(default_factory=list)
    feature_snapshot: dict[str, float | str | int | list | dict | None] = Field(default_factory=dict)
