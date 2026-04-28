from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class EarningsEvent(Base):
    __tablename__ = "earnings_events"
    __table_args__ = (
        UniqueConstraint("ticker", "earnings_date", name="uq_earnings_event_ticker_date"),
        Index("idx_earnings_events_date", "earnings_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255))
    earnings_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_time: Mapped[str | None] = mapped_column(String(16))
    fiscal_quarter: Mapped[str | None] = mapped_column(String(16))
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    market_cap: Mapped[float | None] = mapped_column(Numeric(18, 2))
    exchange: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64), default="fmp")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FinancialMetric(Base):
    __tablename__ = "financial_metrics"
    __table_args__ = (UniqueConstraint("ticker", "earnings_date", name="uq_financial_metric_ticker_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    earnings_date: Mapped[date] = mapped_column(Date, nullable=False)
    eps_actual: Mapped[float | None] = mapped_column(Float)
    eps_estimate: Mapped[float | None] = mapped_column(Float)
    revenue_actual: Mapped[float | None] = mapped_column(Float)
    revenue_estimate: Mapped[float | None] = mapped_column(Float)
    gross_margin: Mapped[float | None] = mapped_column(Float)
    gross_margin_yoy: Mapped[float | None] = mapped_column(Float)
    operating_margin: Mapped[float | None] = mapped_column(Float)
    operating_margin_yoy: Mapped[float | None] = mapped_column(Float)
    net_margin: Mapped[float | None] = mapped_column(Float)
    net_margin_yoy: Mapped[float | None] = mapped_column(Float)
    free_cash_flow: Mapped[float | None] = mapped_column(Float)
    operating_cash_flow: Mapped[float | None] = mapped_column(Float)
    forward_revenue_guidance: Mapped[float | None] = mapped_column(Float)
    forward_eps_guidance: Mapped[float | None] = mapped_column(Float)
    debt_to_equity: Mapped[float | None] = mapped_column(Float)
    cash_and_equivalents: Mapped[float | None] = mapped_column(Float)
    buyback_amount: Mapped[float | None] = mapped_column(Float)
    transcript_sentiment: Mapped[float | None] = mapped_column(Float)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PriceFeature(Base):
    __tablename__ = "price_features"
    __table_args__ = (UniqueConstraint("ticker", "earnings_date", name="uq_price_feature_ticker_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    earnings_date: Mapped[date] = mapped_column(Date, nullable=False)
    price_1d_pre: Mapped[float | None] = mapped_column(Float)
    price_5d_pre: Mapped[float | None] = mapped_column(Float)
    price_10d_pre: Mapped[float | None] = mapped_column(Float)
    price_20d_pre: Mapped[float | None] = mapped_column(Float)
    price_60d_pre: Mapped[float | None] = mapped_column(Float)
    ret_1d_pre: Mapped[float | None] = mapped_column(Float)
    ret_5d_pre: Mapped[float | None] = mapped_column(Float)
    ret_10d_pre: Mapped[float | None] = mapped_column(Float)
    ret_20d_pre: Mapped[float | None] = mapped_column(Float)
    ret_60d_pre: Mapped[float | None] = mapped_column(Float)
    atm_iv: Mapped[float | None] = mapped_column(Float)
    iv_rank: Mapped[float | None] = mapped_column(Float)
    iv_percentile: Mapped[float | None] = mapped_column(Float)
    iv_crush_hist: Mapped[float | None] = mapped_column(Float)
    expected_move_pct: Mapped[float | None] = mapped_column(Float)
    volume_anomaly: Mapped[float | None] = mapped_column(Float)
    rsi_14: Mapped[float | None] = mapped_column(Float)
    macd: Mapped[float | None] = mapped_column(Float)
    macd_signal: Mapped[float | None] = mapped_column(Float)
    bollinger_position: Mapped[float | None] = mapped_column(Float)
    dist_52w_high: Mapped[float | None] = mapped_column(Float)
    dist_52w_low: Mapped[float | None] = mapped_column(Float)
    feature_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MacroFeature(Base):
    __tablename__ = "macro_features"
    __table_args__ = (UniqueConstraint("feature_date", name="uq_macro_feature_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_date: Mapped[date] = mapped_column(Date, nullable=False)
    vix: Mapped[float | None] = mapped_column(Float)
    vix9d: Mapped[float | None] = mapped_column(Float)
    vix3m: Mapped[float | None] = mapped_column(Float)
    spy_ret_1d: Mapped[float | None] = mapped_column(Float)
    spy_ret_5d: Mapped[float | None] = mapped_column(Float)
    spy_ret_20d: Mapped[float | None] = mapped_column(Float)
    qqq_ret_1d: Mapped[float | None] = mapped_column(Float)
    qqq_ret_5d: Mapped[float | None] = mapped_column(Float)
    qqq_ret_20d: Mapped[float | None] = mapped_column(Float)
    fed_funds_rate: Mapped[float | None] = mapped_column(Float)
    yield_10y: Mapped[float | None] = mapped_column(Float)
    yield_2y: Mapped[float | None] = mapped_column(Float)
    yield_curve_slope: Mapped[float | None] = mapped_column(Float)
    cpi_yoy: Mapped[float | None] = mapped_column(Float)
    pce_yoy: Mapped[float | None] = mapped_column(Float)
    bull_bear_regime: Mapped[int | None] = mapped_column(Integer)
    hyg_lqd_spread: Mapped[float | None] = mapped_column(Float)
    sector_relative: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("ticker", "earnings_date", name="uq_prediction_ticker_date"),
        Index("idx_predictions_date", "earnings_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    earnings_date: Mapped[date] = mapped_column(Date, nullable=False)
    sector: Mapped[str | None] = mapped_column(String(128))
    direction_prob_up: Mapped[float | None] = mapped_column(Float)
    direction_prob_flat: Mapped[float | None] = mapped_column(Float)
    direction_prob_down: Mapped[float | None] = mapped_column(Float)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    expected_move_pct: Mapped[float | None] = mapped_column(Float)
    expected_move_low: Mapped[float | None] = mapped_column(Float)
    expected_move_high: Mapped[float | None] = mapped_column(Float)
    convergence_low: Mapped[float | None] = mapped_column(Float)
    convergence_high: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(64))
    feature_completeness: Mapped[float | None] = mapped_column(Float)
    warning_flags: Mapped[list | dict | None] = mapped_column(JSON)
    key_drivers: Mapped[list | None] = mapped_column(JSON)
    similar_cases: Mapped[list | None] = mapped_column(JSON)
    feature_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Outcome(Base):
    __tablename__ = "outcomes"
    __table_args__ = (
        UniqueConstraint("ticker", "earnings_date", name="uq_outcome_ticker_date"),
        Index("idx_outcomes_date", "earnings_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    earnings_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_t1_gap_pct: Mapped[float | None] = mapped_column(Float)
    actual_t1_close_return: Mapped[float | None] = mapped_column(Float)
    actual_t5_return: Mapped[float | None] = mapped_column(Float)
    actual_t20_return: Mapped[float | None] = mapped_column(Float)
    max_intraday_move: Mapped[float | None] = mapped_column(Float)
    gap_direction: Mapped[str | None] = mapped_column(String(8))
    gap_filled: Mapped[bool | None] = mapped_column(Boolean)
    convergence_low: Mapped[float | None] = mapped_column(Float)
    convergence_high: Mapped[float | None] = mapped_column(Float)
    convergence_range: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ModelPerformance(Base):
    __tablename__ = "model_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    sector: Mapped[str] = mapped_column(String(128), nullable=False)
    accuracy: Mapped[float | None] = mapped_column(Float)
    precision_weighted: Mapped[float | None] = mapped_column(Float)
    recall_weighted: Mapped[float | None] = mapped_column(Float)
    f1_weighted: Mapped[float | None] = mapped_column(Float)
    mae: Mapped[float | None] = mapped_column(Float)
    rmse: Mapped[float | None] = mapped_column(Float)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float)
    confusion_matrix: Mapped[list | dict | None] = mapped_column(JSON)
    feature_importance: Mapped[list | dict | None] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
# =====================================================================
# Trading Simulator models — append to backend/app/db/models.py
# =====================================================================


class SimulationConfig(Base):
    """Single-row config table holding strategy params and last-run timestamp."""
    __tablename__ = "simulation_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    initial_capital: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=1_000_000)
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.55)
    base_position_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    max_position_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.15)
    portfolio_leverage_cap: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    stop_loss_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.08)
    take_profit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.15)
    holding_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    slippage_bps: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    last_step_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimulationState(Base):
    """Portfolio snapshot, one row per simulation step."""
    __tablename__ = "simulation_state"
    __table_args__ = (
        Index("idx_simulation_state_ts", "snapshot_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cash: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    positions_value: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    total_equity: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    total_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    leverage_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    num_open_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    num_trades_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sharpe: Mapped[float | None] = mapped_column(Float)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)


class SimulationPosition(Base):
    """An OPEN position currently held in the simulated portfolio."""
    __tablename__ = "simulation_position"
    __table_args__ = (
        Index("idx_simulation_position_ticker", "ticker"),
        Index("idx_simulation_position_exit", "target_exit_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(128))
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # 'LONG' | 'SHORT'
    shares: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    earnings_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_exit_date: Mapped[date] = mapped_column(Date, nullable=False)
    leverage: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    notional_value: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    margin_used: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    predicted_direction: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    expected_move_pct: Mapped[float | None] = mapped_column(Float)
    last_mark_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    last_mark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unrealized_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))
    unrealized_pnl_pct: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimulationTrade(Base):
    """A single executed trade event (open or close). Append-only history."""
    __tablename__ = "simulation_trade"
    __table_args__ = (
        Index("idx_simulation_trade_ts", "executed_at"),
        Index("idx_simulation_trade_ticker", "ticker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(128))
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # 'LONG' | 'SHORT'
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # 'OPEN' | 'CLOSE'
    shares: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    notional: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    leverage: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence: Mapped[float | None] = mapped_column(Float)
    predicted_direction: Mapped[str | None] = mapped_column(String(8))
    realized_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))  # only on CLOSE
    realized_pnl_pct: Mapped[float | None] = mapped_column(Float)
    holding_days: Mapped[int | None] = mapped_column(Integer)  # only on CLOSE
    exit_reason: Mapped[str | None] = mapped_column(String(32))  # 'TIME', 'STOP_LOSS', 'TAKE_PROFIT', 'MANUAL'
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
