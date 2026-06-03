"""Ticker detail endpoint for the Pulse side panel.

Returns: current pulse data + active signal + earnings history (predictions vs actuals).
"""
from __future__ import annotations
from datetime import date
from typing import Any, Dict, List

from fastapi import APIRouter
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from backend.app.services.market_pulse_service import scan_market

router = APIRouter(prefix="/api/v1/pulse", tags=["pulse_detail"])

# Aliases: tickers that need a different lookup in earnings_events
TICKER_ALIASES = {"GOOG": "GOOGL", "BRK-B": "BRK.B"}


def _predicted_label(up, down):
    """Pick UP/DOWN/FLAT based on direction probabilities."""
    if up is None or down is None:
        return None
    up_f, down_f = float(up), float(down)
    flat_f = max(0.0, 1.0 - up_f - down_f)
    return max({"UP": up_f, "DOWN": down_f, "FLAT": flat_f}.items(), key=lambda x: x[1])[0]


def _actual_label(ret):
    """Classify actual T+1 return as UP/DOWN/FLAT (±1.5% threshold)."""
    if ret is None:
        return None
    r = float(ret)
    if r > 0.015:
        return "UP"
    if r < -0.015:
        return "DOWN"
    return "FLAT"


def _get_earnings_history(ticker: str, limit: int = 6) -> List[Dict[str, Any]]:
    """Pull last N earnings with predictions + actual outcomes from real DB schema."""
    db = SessionLocal()
    try:
        lookup = TICKER_ALIASES.get(ticker, ticker)
        sql = text("""
            SELECT
                e.ticker,
                e.earnings_date,
                p.direction_prob_up,
                p.direction_prob_down,
                p.expected_move_pct,
                p.confidence_score,
                o.actual_t1_close_return,
                o.actual_t1_gap_pct,
                o.actual_t5_return,
                o.max_intraday_move,
                o.gap_direction
            FROM earnings_events e
            LEFT JOIN predictions p
                ON p.ticker = e.ticker AND p.earnings_date = e.earnings_date
            LEFT JOIN outcomes o
                ON o.ticker = e.ticker AND o.earnings_date = e.earnings_date
            WHERE e.ticker = :ticker
            ORDER BY e.earnings_date DESC
            LIMIT :limit
        """)
        rows = db.execute(sql, {"ticker": lookup, "limit": limit}).fetchall()
        today = date.today()
        history: List[Dict[str, Any]] = []
        for r in rows:
            ed = r.earnings_date
            q = (ed.month - 1) // 3 + 1
            period = f"Q{q} {ed.year}"

            predicted = _predicted_label(r.direction_prob_up, r.direction_prob_down)
            actual_ret = (
                float(r.actual_t1_close_return)
                if r.actual_t1_close_return is not None else None
            )
            actual = _actual_label(actual_ret)
            is_past = ed < today
            win = (
                (predicted == actual)
                if (predicted and actual and is_past)
                else None
            )

            history.append({
                "period": period,
                "earnings_date": ed.isoformat(),
                "predicted_label": predicted,
                "actual_label": actual,
                "actual_move_pct": actual_ret,
                "expected_move_pct": (
                    float(r.expected_move_pct)
                    if r.expected_move_pct is not None else None
                ),
                "confidence_score": (
                    float(r.confidence_score)
                    if r.confidence_score is not None else None
                ),
                "is_past": is_past,
                "win": win,
            })
        return history
    finally:
        db.close()


@router.get("/ticker/{ticker}")
def get_ticker_detail(ticker: str):
    t = ticker.upper().strip()
    scan = scan_market()
    tickers_list = scan.get("tickers", []) or []
    signals_list = scan.get("signals", []) or []
    ticker_data = next((x for x in tickers_list if x.get("ticker") == t), None)
    active_signal = next((x for x in signals_list if x.get("ticker") == t), None)
    earnings_history = _get_earnings_history(t, limit=6)
    price_series = (ticker_data or {}).get("spark", []) if ticker_data else []
    return {
        "ticker": t,
        "in_universe": ticker_data is not None,
        "pulse": ticker_data,
        "active_signal": active_signal,
        "earnings_history": earnings_history,
        "price_series": price_series,
    }
