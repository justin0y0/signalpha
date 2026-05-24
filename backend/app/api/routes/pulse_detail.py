"""Per-ticker detail endpoint: combines current pulse signal + earnings history."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.services.market_pulse_service import scan_market

router = APIRouter(prefix="/api/v1/pulse", tags=["pulse"])


@router.get("/ticker/{ticker}")
def get_ticker_detail(ticker: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    # Alias: GOOG (Class C, non-voting) has no separate earnings, use GOOGL
    earnings_ticker = "GOOGL" if ticker == "GOOG" else ticker

    # 1) Current pulse signal for this ticker (use cached scan)
    pulse = scan_market()
    ticker_data = next((t for t in pulse.get("tickers", []) if t["ticker"] == ticker), None)
    active_signal = next((s for s in pulse.get("signals", []) if s["ticker"] == ticker), None)

    # 2) Earnings history with predictions vs actuals
    earnings_history: list[dict] = []
    try:
        from backend.app.models.earnings import EarningsEvent
        events = (
            db.query(EarningsEvent)
            .filter(EarningsEvent.ticker == earnings_ticker)
            .order_by(EarningsEvent.scheduled_time.desc())
            .limit(6)
            .all()
        )
        for ev in events:
            row = {
                "scheduled_time": ev.scheduled_time.isoformat() if ev.scheduled_time else None,
                "period": _quarter_label(ev.scheduled_time) if ev.scheduled_time else None,
                "eps_estimate": _safe_float(getattr(ev, "eps_estimate", None)),
                "eps_actual": _safe_float(getattr(ev, "eps_actual", None)),
                "predicted_label": None, "predicted_prob": None,
                "actual_move_pct": None, "win": None,
                "is_past": False,
            }
            # Past or future?
            if ev.scheduled_time:
                is_past = ev.scheduled_time.replace(tzinfo=None) < datetime.utcnow()
                row["is_past"] = is_past

            # Pull prediction if available
            try:
                from backend.app.models.predictions import Prediction
                pred = (
                    db.query(Prediction)
                    .filter(Prediction.event_id == ev.id)
                    .order_by(Prediction.created_at.desc())
                    .first()
                )
                if pred:
                    row["predicted_label"] = getattr(pred, "label", None) or getattr(pred, "predicted_label", None)
                    row["predicted_prob"] = _safe_float(getattr(pred, "confidence", None) or getattr(pred, "probability", None))
            except Exception:
                pass

            # Pull actual move from PriceFeature payload if any
            try:
                from backend.app.models.features import PriceFeature
                pf = (
                    db.query(PriceFeature)
                    .filter(PriceFeature.event_id == ev.id)
                    .order_by(PriceFeature.snapshot_at.desc())
                    .first()
                )
                if pf:
                    payload = getattr(pf, "feature_payload", {}) or {}
                    move = (payload.get("event_return_pct")
                            or payload.get("realized_move_pct")
                            or payload.get("actual_move_pct"))
                    row["actual_move_pct"] = _safe_float(move)
            except Exception:
                pass

            # Compute win/loss if we have both
            if row["predicted_label"] and row["actual_move_pct"] is not None:
                actual_dir = "UP" if row["actual_move_pct"] > 0.005 else "DOWN" if row["actual_move_pct"] < -0.005 else "FLAT"
                row["actual_label"] = actual_dir
                row["win"] = row["predicted_label"].upper() == actual_dir
            earnings_history.append(row)
    except Exception as e:
        earnings_history = []

    # 3) Quick price series for chart (uses pulse spark data we already have)
    price_series = ticker_data.get("spark", []) if ticker_data else []

    if ticker_data is None and active_signal is None:
        # Ticker not in pulse universe — return minimal
        return {
            "ticker": ticker, "in_universe": False,
            "pulse": None, "active_signal": None,
            "earnings_history": earnings_history,
            "price_series": [],
        }

    return {
        "ticker": ticker,
        "in_universe": True,
        "pulse": ticker_data,
        "active_signal": active_signal,
        "earnings_history": earnings_history,
        "price_series": price_series,
    }


def _safe_float(v) -> float | None:
    try:
        if v is None: return None
        f = float(v)
        if f != f or f == float("inf") or f == -float("inf"): return None
        return round(f, 4)
    except Exception:
        return None


def _quarter_label(dt: datetime) -> str:
    if dt is None: return "—"
    q = (dt.month - 1) // 3 + 1
    return f"Q{q}'{str(dt.year)[2:]}"
