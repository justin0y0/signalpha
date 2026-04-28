from __future__ import annotations

from datetime import date

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from backend.app.db.models import EarningsEvent, FinancialMetric, MacroFeature, PriceFeature


class FeatureService:
    def get_feature_snapshot(self, db: Session, ticker: str, earnings_date: date | None = None) -> dict:
        event_stmt = select(EarningsEvent).where(EarningsEvent.ticker == ticker.upper())
        if earnings_date:
            event_stmt = event_stmt.where(EarningsEvent.earnings_date == earnings_date)
        event_stmt = event_stmt.order_by(EarningsEvent.earnings_date.desc()).limit(1)
        event = db.execute(event_stmt).scalar_one_or_none()
        if event is None:
            raise ValueError(f"No earnings event found for {ticker}")

        financial = db.execute(
            select(FinancialMetric).where(
                and_(FinancialMetric.ticker == event.ticker, FinancialMetric.earnings_date == event.earnings_date)
            )
        ).scalar_one_or_none()
        price = db.execute(
            select(PriceFeature).where(
                and_(PriceFeature.ticker == event.ticker, PriceFeature.earnings_date == event.earnings_date)
            )
        ).scalar_one_or_none()
        macro = db.execute(
            select(MacroFeature)
            .where(MacroFeature.feature_date <= event.earnings_date)
            .order_by(desc(MacroFeature.feature_date))
            .limit(1)
        ).scalar_one_or_none()

        payload: dict = {
            "ticker": event.ticker,
            "earnings_date": event.earnings_date.isoformat(),
            "company_name": event.company_name,
            "sector": event.sector,
            "report_time": event.report_time,
            "market_cap": float(event.market_cap) if event.market_cap is not None else None,
        }
        if financial and financial.raw_payload:
            payload.update(financial.raw_payload)
        if price and price.feature_payload:
            payload.update(price.feature_payload)
        if macro:
            payload.update(
                {
                    "macro_feature_date": macro.feature_date.isoformat(),
                    "vix": macro.vix,
                    "spy_ret_20d": macro.spy_ret_20d,
                    "yield_curve_slope": macro.yield_curve_slope,
                    "bull_bear_regime": macro.bull_bear_regime,
                    "sector_relative": macro.sector_relative,
                }
            )
        return payload
