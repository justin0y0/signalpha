from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class CalendarEvent(BaseModel):
    ticker: str
    company_name: str | None = None
    earnings_date: date
    report_time: str | None = None
    sector: str | None = None
    market_cap: float | None = None
    confidence_score: float | None = None
    direction: str | None = None
    # The full calibrated distribution, not just its argmax. After walk-forward
    # calibration FLAT wins argmax on 97.5% of events, so `direction` alone conveys
    # almost nothing; the split behind it still does. The Calendar renders these.
    direction_prob_up: float | None = None
    direction_prob_flat: float | None = None
    direction_prob_down: float | None = None
    # The stock's own band — the median absolute reaction it produced on earlier
    # reports. What counts as a move for this name (JNJ ~0.5%, META ~6.8%).
    flat_band: float | None = None
    # P(this report moves the stock more than its own band), from the pooled breakout
    # model, and where that probability sits against the out-of-sample deciles:
    # "breakout" = top decile, "elevated" = top quintile, else "normal".
    prob_move: float | None = None
    move_tier: str | None = None
    # The regression model's size estimate. Out of sample it ranks actual moves worse
    # than the stock's own band does (Spearman 0.27 vs 0.37, MAE 24.7pp vs 2.1pp), so the
    # UI shows flat_band and the options-implied move instead and keeps this for the API.
    expected_move_pct: float | None = None
    # ATM straddle / spot from the latest options snapshot: what the market is pricing.
    implied_move_pct: float | None = None
    has_prediction: bool = False


class CalendarResponse(BaseModel):
    items: list[CalendarEvent]
    total: int
