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
    expected_move_pct: float | None = None
    has_prediction: bool = False


class CalendarResponse(BaseModel):
    items: list[CalendarEvent]
    total: int
