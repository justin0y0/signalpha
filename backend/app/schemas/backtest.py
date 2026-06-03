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
    drawdown: float


class DirectionStat(BaseModel):
    direction: str
    signals: int
    hits: int
    hit_rate: float
    avg_return_pct: float


class MonthlyReturn(BaseModel):
    month: str
    return_pct: float
    trades: int


class SectorAttribution(BaseModel):
    sector: str
    return_pct: float
    trades: int
    win_rate: float


class TradeRecord(BaseModel):
    date: date
    ticker: str
    sector: str
    signal: str
    actual: str
    confidence: float
    actual_return_pct: float
    pnl_dollars: float
    win: bool


class BacktestResponse(BaseModel):
    total_samples: int
    total_trades: int
    accuracy: float
    precision_weighted: float
    recall_weighted: float
    f1_weighted: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    total_return: float
    cagr: float = 0
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    mae: float | None = None
    rmse: float | None = None
    confusion_matrix: list[list[int]] = Field(default_factory=list)
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    direction_stats: list[DirectionStat] = Field(default_factory=list)
    benchmark_return: float = 0
    benchmark_curve: list[EquityPoint] = Field(default_factory=list)
    alpha: float = 0
    beta: float = 0
    time_underwater_pct: float = 0
    monthly_returns: list[MonthlyReturn] = Field(default_factory=list)
    sector_attribution: list[SectorAttribution] = Field(default_factory=list)
    trade_list: list[TradeRecord] = Field(default_factory=list)
