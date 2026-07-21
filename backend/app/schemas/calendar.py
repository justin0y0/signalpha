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
    # The stock's own FLAT band — 0.5x its historical earnings-reaction sigma, clamped
    # to [2.5%, 10%]. This is what the model labels against, and it differs enormously
    # by name (MMM 2.5%, TSLA 4.4%). The frontend was reverse-engineering an
    # approximation from expected_move; now it gets the real number.
    flat_band: float | None = None
    expected_move_pct: float | None = None
    has_prediction: bool = False


class CalendarResponse(BaseModel):
    items: list[CalendarEvent]
    total: int
