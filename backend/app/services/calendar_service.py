from __future__ import annotations

from datetime import date

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session

from backend.app.db.models import EarningsEvent, Prediction
from backend.app.schemas.calendar import CalendarEvent, CalendarResponse


class CalendarService:
    def list_events(
        self,
        db: Session,
        start: date,
        end: date,
        sector: str | None = None,
        report_time: str | None = None,
    ) -> CalendarResponse:
        stmt: Select = (
            select(EarningsEvent, Prediction)
            .outerjoin(
                Prediction,
                and_(
                    Prediction.ticker == EarningsEvent.ticker,
                    Prediction.earnings_date == EarningsEvent.earnings_date,
                ),
            )
            .where(EarningsEvent.earnings_date >= start, EarningsEvent.earnings_date <= end)
            .order_by(EarningsEvent.earnings_date.asc(), EarningsEvent.ticker.asc())
        )
        if sector:
            stmt = stmt.where(EarningsEvent.sector == sector)
        if report_time:
            stmt = stmt.where(EarningsEvent.report_time == report_time)

        rows = db.execute(stmt).all()
        items: list[CalendarEvent] = []
        for event, prediction in rows:
            direction = None
            if prediction:
                probs = {
                    "UP": prediction.direction_prob_up or 0.0,
                    "FLAT": prediction.direction_prob_flat or 0.0,
                    "DOWN": prediction.direction_prob_down or 0.0,
                }
                direction = max(probs, key=probs.get)
            items.append(
                CalendarEvent(
                    ticker=event.ticker,
                    company_name=event.company_name,
                    earnings_date=event.earnings_date,
                    report_time=event.report_time,
                    sector=event.sector,
                    market_cap=float(event.market_cap) if event.market_cap is not None else None,
                    confidence_score=prediction.confidence_score if prediction else None,
                    direction=direction,
                    expected_move_pct=prediction.expected_move_pct if prediction else None,
                    has_prediction=prediction is not None,
                )
            )
        return CalendarResponse(items=items, total=len(items))
