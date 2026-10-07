"""Every earnings reaction a stock has had, plus what options price for the next one.

Feeds the Straddle Check on the deep-dive page: the descriptive comparison options
traders actually make before a print — how big this name's reactions have been versus
the move the straddle is pricing now. Nothing here is a forecast; the breakout model's
call is attached so the page can show both side by side.
"""
from __future__ import annotations

import math
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.services.flat_band import load_flat_bands
from backend.app.services.headline_service import _breakout_metrics, move_tier

router = APIRouter(prefix="/moves", tags=["moves"])


@router.get("/{ticker}")
def moves(ticker: str, db: Session = Depends(get_db)):
    t = ticker.upper().strip()
    if not t.replace(".", "").replace("-", "").isalnum() or len(t) > 10:
        raise HTTPException(400, "bad ticker")
    today = date.today()
    hist = db.execute(text("""
        SELECT earnings_date, actual_t1_close_return AS r FROM outcomes
        WHERE ticker=:t AND actual_t1_close_return IS NOT NULL AND earnings_date < :d
        ORDER BY earnings_date"""), {"t": t, "d": today}).all()
    history = [{"date": str(h.earnings_date), "move": float(h.r)}
               for h in hist if h.r is not None and math.isfinite(float(h.r)) and abs(float(h.r)) < 1]
    nxt = db.execute(text("""
        SELECT e.earnings_date, e.report_time, f.expected_move_pct AS implied, p.prob_move
        FROM earnings_events e
        LEFT JOIN price_features f ON f.ticker=e.ticker AND f.earnings_date=e.earnings_date
        LEFT JOIN predictions p ON p.ticker=e.ticker AND p.earnings_date=e.earnings_date
        WHERE e.ticker=:t AND e.earnings_date >= :d
        ORDER BY e.earnings_date LIMIT 1"""), {"t": t, "d": today}).first()
    if not history and not nxt:
        raise HTTPException(404, "no earnings history")
    metrics = _breakout_metrics()
    return {
        "ticker": t,
        "band": load_flat_bands(db, [t]).get(t),
        "history": history,
        "next": None if not nxt else {
            "earnings_date": str(nxt.earnings_date),
            "report_time": nxt.report_time,
            "implied_move_pct": float(nxt.implied) if nxt.implied is not None else None,
            "prob_move": float(nxt.prob_move) if nxt.prob_move is not None else None,
            "move_tier": move_tier(nxt.prob_move, metrics),
        },
    }
