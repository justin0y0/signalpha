from __future__ import annotations

from datetime import date

from sqlalchemy import text, Select, and_, select
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

        # Each ticker's own FLAT band, from its realised earnings reactions — the same
        # 0.5-sigma rule models/dataset.py labels against, clamped to [2.5%, 10%].
        # Computed once per request rather than per row.
        flat_bands: dict[str, float] = {}
        tickers = {event.ticker for event, _ in rows}
        if tickers:
            band_rows = db.execute(
                text("""SELECT ticker,
                               greatest(0.025, least(0.10, 0.5 * stddev_samp(actual_t1_close_return))) AS band
                        FROM outcomes
                        WHERE ticker = ANY(:tickers) AND actual_t1_close_return IS NOT NULL
                        GROUP BY ticker
                        HAVING count(*) >= 4"""),
                {"tickers": list(tickers)},
            ).fetchall()
            flat_bands = {r[0]: float(r[1]) for r in band_rows if r[1] is not None}

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
                    direction_prob_up=prediction.direction_prob_up if prediction else None,
                    direction_prob_flat=prediction.direction_prob_flat if prediction else None,
                    direction_prob_down=prediction.direction_prob_down if prediction else None,
                    flat_band=flat_bands.get(event.ticker),
                    expected_move_pct=prediction.expected_move_pct if prediction else None,
                    has_prediction=prediction is not None,
                )
            )
        return CalendarResponse(items=items, total=len(items))
