from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from backend.app.core.config import Settings
from backend.app.core.logging import get_logger
from data_pipeline.feature_engineer import FeatureEngineer
from data_pipeline.sources.alpaca_client import AlpacaClient
from data_pipeline.sources.fmp_client import FMPClient
from data_pipeline.sources.fred_client import FREDClient
from data_pipeline.sources.polygon_client import PolygonClient
from data_pipeline.sources.sec_client import SECClient
from data_pipeline.sources.yfinance_client import YFinanceClient

logger = get_logger(__name__)

SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Communication Services": "XLC",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}

POSITIVE_WORDS = {
    "strong",
    "accelerating",
    "improving",
    "beat",
    "beats",
    "growth",
    "profitable",
    "confidence",
    "expansion",
    "opportunity",
}
NEGATIVE_WORDS = {
    "weak",
    "soft",
    "pressure",
    "decline",
    "miss",
    "headwind",
    "uncertain",
    "challenging",
    "loss",
    "slowdown",
}


@dataclass
class DataCollector:
    settings: Settings

    def __post_init__(self) -> None:
        self.fe = FeatureEngineer()
        self.sec = SECClient(self.settings.sec_user_agent)
        self.fmp = FMPClient(self.settings.financial_modeling_prep_api_key or "")
        self.fred = FREDClient(self.settings.fred_api_key or "")
        self.polygon = PolygonClient(self.settings.polygon_api_key or "") if self.settings.polygon_api_key else None
        self.alpaca = (
            AlpacaClient(self.settings.alpaca_api_key or "", self.settings.alpaca_secret_key or "")
            if self.settings.alpaca_api_key and self.settings.alpaca_secret_key
            else None
        )
        self.yf = YFinanceClient()

    @staticmethod
    def _normalize_report_time(value: str | None) -> str | None:
        if not value:
            return None
        upper = str(value).upper()
        if upper in {"BEFORE MARKET OPEN", "BMO"}:
            return "BMO"
        if upper in {"AFTER MARKET CLOSE", "AMC"}:
            return "AMC"
        return upper

    @staticmethod
    def _first_record(records: list[dict[str, Any]]) -> dict[str, Any]:
        return records[0] if records else {}

    @staticmethod
    def _latest_numeric(observations: list[dict[str, Any]]) -> float | None:
        values = [float(item.get("value")) for item in observations if item.get("value") not in {None, "."}]
        return float(values[-1]) if values else None

    @staticmethod
    def _yoy_change(observations: list[dict[str, Any]]) -> float | None:
        values = [float(item.get("value")) for item in observations if item.get("value") not in {None, "."}]
        if len(values) < 13:
            return None
        latest = values[-1]
        base = values[-13]
        return None if base == 0 else float(latest / base - 1)

    def score_transcript_sentiment(self, transcript_text: str | None) -> float | None:
        if not transcript_text:
            return None
        tokens = [token.strip(".,:;!?()[]{}\"'").lower() for token in transcript_text.split()]
        if not tokens:
            return None
        positives = sum(1 for token in tokens if token in POSITIVE_WORDS)
        negatives = sum(1 for token in tokens if token in NEGATIVE_WORDS)
        return (positives - negatives) / max(len(tokens), 1)

    def collect_earnings_calendar(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        raw_events = self.fmp.earnings_calendar(start_date.isoformat(), end_date.isoformat())
        items: list[dict[str, Any]] = []
        for event in raw_events:
            event_date = event.get("date") or event.get("earningsDate")
            if not event_date:
                continue
            items.append(
                {
                    "ticker": str(event.get("symbol") or event.get("ticker")).upper(),
                    "company_name": event.get("name") or event.get("companyName"),
                    "earnings_date": pd.to_datetime(event_date).date(),
                    "report_time": self._normalize_report_time(event.get("time") or event.get("reportTime")),
                    "fiscal_quarter": event.get("fiscalQuarter") or event.get("quarter"),
                    "fiscal_year": event.get("fiscalYear") or event.get("year"),
                    "market_cap": event.get("marketCap"),
                    "sector": event.get("sector"),
                    "industry": event.get("industry"),
                    "exchange": event.get("exchangeShortName") or event.get("exchange"),
                    "source": "fmp",
                }
            )
        return items

    def collect_macro_snapshot(self, as_of_date: date) -> dict[str, Any]:
        start = (as_of_date - timedelta(days=400)).isoformat()
        end = as_of_date.isoformat()
        spy_hist = self.yf.history("SPY", start=start, end=end)
        qqq_hist = self.yf.history("QQQ", start=start, end=end)
        vix_hist = self.yf.history("^VIX", start=start, end=end)
        vix9d_hist = self.yf.history("^VIX9D", start=start, end=end)
        vix3m_hist = self.yf.history("^VIX3M", start=start, end=end)
        hyg_hist = self.yf.history("HYG", start=start, end=end)
        lqd_hist = self.yf.history("LQD", start=start, end=end)

        def trailing_return(frame: pd.DataFrame, window: int) -> float | None:
            if frame.empty or len(frame) <= window:
                return None
            close = frame["Close"].astype(float).reset_index(drop=True)
            return float(close.iloc[-1] / close.iloc[-(window + 1)] - 1)

        spy_close = spy_hist["Close"].astype(float) if not spy_hist.empty else pd.Series(dtype=float)
        spy_price = float(spy_close.iloc[-1]) if not spy_close.empty else None
        spy_200ma = float(spy_close.tail(200).mean()) if len(spy_close) >= 200 else None

        sector_relative: dict[str, float | None] = {}
        for sector, etf in SECTOR_ETF_MAP.items():
            hist = self.yf.history(etf, start=start, end=end)
            sector_ret = trailing_return(hist, 20)
            spy_ret = trailing_return(spy_hist, 20)
            sector_relative[sector] = None if sector_ret is None or spy_ret is None else sector_ret - spy_ret

        macro = {
            "feature_date": as_of_date,
            "vix": float(vix_hist["Close"].iloc[-1]) if not vix_hist.empty else None,
            "vix9d": float(vix9d_hist["Close"].iloc[-1]) if not vix9d_hist.empty else None,
            "vix3m": float(vix3m_hist["Close"].iloc[-1]) if not vix3m_hist.empty else None,
            "spy_ret_1d": trailing_return(spy_hist, 1),
            "spy_ret_5d": trailing_return(spy_hist, 5),
            "spy_ret_20d": trailing_return(spy_hist, 20),
            "qqq_ret_1d": trailing_return(qqq_hist, 1),
            "qqq_ret_5d": trailing_return(qqq_hist, 5),
            "qqq_ret_20d": trailing_return(qqq_hist, 20),
            "bull_bear_regime": 1 if spy_price is not None and spy_200ma is not None and spy_price > spy_200ma else -1,
            "hyg_lqd_spread": None
            if hyg_hist.empty or lqd_hist.empty
            else float(hyg_hist["Close"].iloc[-1] / max(lqd_hist["Close"].iloc[-1], 1e-9) - 1),
            "sector_relative": sector_relative,
            "spy_price": spy_price,
            "spy_200ma": spy_200ma,
            "vix_history": vix_hist["Close"].astype(float).tail(252).tolist() if not vix_hist.empty else [],
        }

        if self.settings.fred_api_key:
            fedfunds_obs = self.fred.series_observations("FEDFUNDS", observation_start=start, observation_end=end)
            y10_obs = self.fred.series_observations("DGS10", observation_start=start, observation_end=end)
            y2_obs = self.fred.series_observations("DGS2", observation_start=start, observation_end=end)
            cpi_obs = self.fred.series_observations("CPIAUCSL", observation_start=start, observation_end=end)
            pce_obs = self.fred.series_observations("PCEPI", observation_start=start, observation_end=end)
            macro.update(
                {
                    "fed_funds_rate": self._latest_numeric(fedfunds_obs),
                    "yield_10y": self._latest_numeric(y10_obs),
                    "yield_2y": self._latest_numeric(y2_obs),
                    "cpi_yoy": self._yoy_change(cpi_obs),
                    "pce_yoy": self._yoy_change(pce_obs),
                }
            )
            if macro.get("yield_10y") is not None and macro.get("yield_2y") is not None:
                macro["yield_curve_slope"] = macro["yield_10y"] - macro["yield_2y"]
        return macro

    def _extract_financial_snapshot(self, ticker: str) -> dict[str, Any]:
        def _safe(fn, *args, **kwargs):
            try:
                return self._first_record(fn(*args, **kwargs))
            except Exception:
                return {}
        earnings = _safe(self.fmp.earnings_report, ticker, limit=8)
        income = _safe(self.fmp.income_statement, ticker, limit=8)
        balance = _safe(self.fmp.balance_sheet_statement, ticker, limit=8)
        cash = _safe(self.fmp.cash_flow_statement, ticker, limit=8)
        estimates = _safe(self.fmp.financial_estimates, ticker)
        price_target = _safe(self.fmp.price_target_summary, ticker)
        transcript = _safe(self.fmp.search_transcripts, ticker)
        transcript_body = transcript.get("content") or transcript.get("text") or transcript.get("transcript")

        buy_count = price_target.get("buy") or price_target.get("strongBuy") or 0
        hold_count = price_target.get("hold") or 0
        sell_count = price_target.get("sell") or price_target.get("strongSell") or 0
        total_ratings = buy_count + hold_count + sell_count
        consensus_score = None
        if total_ratings:
            consensus_score = (buy_count - sell_count) / total_ratings

        return {
            "actual_eps": earnings.get("eps") or earnings.get("epsActual"),
            "est_eps": earnings.get("epsEstimated") or earnings.get("estimatedEps") or earnings.get("epsEstimate"),
            "actual_rev": earnings.get("revenue") or earnings.get("revenueActual"),
            "est_rev": earnings.get("revenueEstimated") or earnings.get("revenueEstimate"),
            "gross_margin": income.get("grossProfitRatio") or income.get("grossMargin"),
            "operating_margin": income.get("operatingIncomeRatio") or income.get("operatingMargin"),
            "net_margin": income.get("netIncomeRatio") or income.get("netMargin"),
            "free_cash_flow": cash.get("freeCashFlow"),
            "operating_cash_flow": cash.get("operatingCashFlow"),
            "forward_revenue_guidance": estimates.get("estimatedRevenueAvg") or estimates.get("revenueAvg"),
            "forward_eps_guidance": estimates.get("estimatedEpsAvg") or estimates.get("epsAvg"),
            "street_est": estimates.get("estimatedRevenueAvg") or estimates.get("estimatedEpsAvg"),
            "debt_to_equity": None
            if balance.get("totalStockholdersEquity") in (None, 0)
            else balance.get("totalDebt", 0) / balance.get("totalStockholdersEquity"),
            "cash_and_equivalents": balance.get("cashAndCashEquivalents"),
            "buyback_amount": cash.get("commonStockRepurchased") or cash.get("stockBasedCompensation"),
            "transcript_sentiment": self.score_transcript_sentiment(transcript_body),
            "analyst_consensus_score": consensus_score,
            "price_target_mean": price_target.get("priceTargetAverage") or price_target.get("targetMean"),
            "price_target_high": price_target.get("priceTargetHigh") or price_target.get("targetHigh"),
            "price_target_low": price_target.get("priceTargetLow") or price_target.get("targetLow"),
            "up_revisions": estimates.get("numberAnalystEstimations") or estimates.get("upRevisionCount"),
            "down_revisions": estimates.get("downRevisionCount"),
            "raw_financial_payload": {
                "earnings": earnings,
                "income": income,
                "balance": balance,
                "cash": cash,
                "estimates": estimates,
                "price_target": price_target,
                "transcript": transcript,
            },
        }

    def _historical_company_reactions(self, ticker: str, as_of_date: datetime) -> dict[str, Any]:
        try:
            reports = self.fmp.earnings_report(ticker, limit=8)
        except Exception:
            reports = []
        history = self.yf.history(ticker, start=(as_of_date - timedelta(days=800)).date().isoformat(), end=(as_of_date + timedelta(days=30)).date().isoformat())
        reactions: list[float] = []
        beats = 0
        total = 0
        for report in reports[:8]:
            report_date_raw = report.get("date") or report.get("earningsDate")
            if not report_date_raw:
                continue
            report_date = pd.to_datetime(report_date_raw).to_pydatetime()
            outcome = self.yf.outcome_snapshot(history, report_date)
            if outcome.get("actual_t1_close_return") is not None:
                reactions.append(float(outcome["actual_t1_close_return"]))
            actual = report.get("eps") or report.get("epsActual")
            estimate = report.get("epsEstimated") or report.get("epsEstimate") or report.get("estimatedEps")
            if actual is not None and estimate is not None:
                total += 1
                if actual > estimate:
                    beats += 1
        return {"last_8q_reactions": reactions, "beats": beats, "total_quarters": total}

    def collect_event_snapshot(self, ticker: str, earnings_date: date, sector: str | None = None) -> dict[str, Any]:
        earnings_dt = datetime.combine(earnings_date, datetime.min.time())
        try:
            history = self.yf.history(ticker, start=(earnings_dt - timedelta(days=420)).date().isoformat(), end=earnings_date.isoformat())
        except Exception:
            history = pd.DataFrame()
        try:
            market_snapshot = self.collect_macro_snapshot(earnings_date)
        except Exception:
            market_snapshot = {}
        try:
            price_snapshot = self.yf.price_window_snapshot(history, earnings_dt) if not history.empty else {}
        except Exception:
            price_snapshot = {}
        try:
            options_snapshot = self.yf.options_snapshot(ticker)
        except Exception:
            options_snapshot = {}
        try:
            technical_snapshot = self.yf.technical_snapshot(history) if not history.empty else {}
        except Exception:
            technical_snapshot = {}
        try:
            financial_snapshot = self._extract_financial_snapshot(ticker)
        except Exception:
            financial_snapshot = {}
        try:
            historical_snapshot = self._historical_company_reactions(ticker, earnings_dt)
        except Exception:
            historical_snapshot = {}
        sector_etf = SECTOR_ETF_MAP.get(sector or "", None)
        try:
            sector_hist = self.yf.history(sector_etf, start=(earnings_dt - timedelta(days=60)).date().isoformat(), end=earnings_date.isoformat()) if sector_etf else pd.DataFrame()
        except Exception:
            sector_hist = pd.DataFrame()
        sector_peer_median = None
        if not sector_hist.empty and market_snapshot.get("spy_ret_20d") is not None and len(sector_hist) > 20:
            sector_peer_median = float(sector_hist["Close"].iloc[-1] / sector_hist["Close"].iloc[-21] - 1)

        raw = {
            "ticker": ticker.upper(),
            "earnings_date": earnings_date.isoformat(),
            "sector": sector,
            **price_snapshot,
            **options_snapshot,
            **technical_snapshot,
            **financial_snapshot,
            **historical_snapshot,
            **market_snapshot,
            "sector_peer_median": sector_peer_median,
            "social_sentiment_score": None,
        }
        engineered = self.fe.engineer_event(raw)
        return {"raw": raw, "engineered": engineered}

    def collect_post_earnings_outcome(self, ticker: str, earnings_date: date) -> dict[str, Any]:
        earnings_dt = datetime.combine(earnings_date, datetime.min.time())
        history = self.yf.history(
            ticker,
            start=(earnings_dt - timedelta(days=10)).date().isoformat(),
            end=(earnings_dt + timedelta(days=40)).date().isoformat(),
        )
        return self.yf.outcome_snapshot(history, earnings_dt)
