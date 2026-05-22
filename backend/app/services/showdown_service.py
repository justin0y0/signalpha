"""Strategy Showdown — LIVE TRADING FLOOR.

Five strategies running in parallel since launch (default 90 days ago).
Computes on-the-fly but presents as live: current open positions,
pending signals on upcoming earnings, recent closed trades.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import sqrt
from typing import Callable
import pandas as pd
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.app.db.models import EarningsEvent, Outcome, Prediction


@dataclass
class StrategyDef:
    code: str; name: str; emoji: str; tagline: str
    citation: str; color: str; description: str


STRATEGIES: list[StrategyDef] = [
    StrategyDef("QUANT", "The Quant", "🤖", "Trust the algorithm",
        "XGBoost + LightGBM ensemble · 102 features",
        "#38bdf8",
        "Pure ML signal. Trade direction whenever the model's confidence exceeds 55%."),
    StrategyDef("DRIFTER", "The Drifter", "🚀", "Ride the surprise",
        "Bernard & Thomas (JFE 1989) · Post-Earnings Drift",
        "#4ade80",
        "Stocks continue drifting in the direction of the earnings surprise. Long positive gaps, short negative ones."),
    StrategyDef("SNIPER", "The Sniper", "🎯", "Wait for the fat pitch",
        "Buffett-inspired selectivity",
        "#fbbf24",
        "Only trade when the model is highly confident (\u226575%) AND the expected move is large (\u22654%). Quality over quantity."),
    StrategyDef("TREND_LORD", "The Trend Lord", "🐢", "The trend is your friend",
        "Richard Dennis & The Turtle Traders (1983)",
        "#fb923c",
        "Pure mechanical trend-following. Trade every gap regardless of size."),
    StrategyDef("COMPOUNDER", "The Compounder", "🌱", "Long-only, never shorts",
        "Buffett \u2014 Rule #1: Don\u2019t lose money",
        "#2dd4bf",
        "Long-only quality. Never shorts, even when the algorithm screams DOWN."),
]


# Strategy entry rules
def _quant(r) -> int:
    if (r["confidence"] or 0) < 0.55: return 0
    if r["prob_up"] > r["prob_down"] and r["prob_up"] > r["prob_flat"]: return 1
    if r["prob_down"] > r["prob_up"] and r["prob_down"] > r["prob_flat"]: return -1
    return 0

def _drifter(r) -> int:
    if r["gap_pct"] > 0.03: return 1
    if r["gap_pct"] < -0.03: return -1
    return 0

def _sniper(r) -> int:
    if (r["confidence"] or 0) < 0.75: return 0
    if (r["expected_move"] or 0) < 0.04: return 0
    if r["prob_up"] > r["prob_down"] and r["prob_up"] > r["prob_flat"]: return 1
    if r["prob_down"] > r["prob_up"] and r["prob_down"] > r["prob_flat"]: return -1
    return 0

def _trendlord(r) -> int:
    if r["gap_pct"] > 0: return 1
    if r["gap_pct"] < 0: return -1
    return 0

def _compounder(r) -> int:
    if (r["confidence"] or 0) < 0.55: return 0
    if r["prob_up"] > r["prob_down"] and r["prob_up"] > r["prob_flat"]: return 1
    return 0


SIGNALS: dict[str, Callable] = {
    "QUANT": _quant, "DRIFTER": _drifter, "SNIPER": _sniper,
    "TREND_LORD": _trendlord, "COMPOUNDER": _compounder,
}

# Pre-earnings strategies (use ML predictions only, can signal in advance)
PRE_EARNINGS = {"QUANT", "SNIPER", "COMPOUNDER"}
# Post-earnings strategies (need gap_pct, signal at T+1)
POST_EARNINGS = {"DRIFTER", "TREND_LORD"}


def _to_dict(p, o):
    return {
        "date": p.earnings_date,
        "ticker": p.ticker,
        "sector": p.sector or "—",
        "prob_up": p.direction_prob_up or 0.0,
        "prob_down": p.direction_prob_down or 0.0,
        "prob_flat": p.direction_prob_flat or 0.0,
        "confidence": p.confidence_score or 0.0,
        "expected_move": p.expected_move_pct or 0.0,
        "gap_pct": (o.actual_t1_gap_pct if o else 0.0) or 0.0,
        "t5_return": (o.actual_t5_return if o else None),
        "outcome_known": (o is not None and o.actual_t5_return is not None),
    }


def run_showdown(
    db: Session,
    start_date: date,
    end_date: date,
    initial_capital: float = 1_000_000,
    position_size_pct: float = 0.05,
) -> dict:
    """Run the full showdown — both historical equity curve AND live state."""
    today = date.today()

    # Pull events from launch to today (need both with and without outcomes)
    rows = db.execute(
        select(Prediction, Outcome)
        .outerjoin(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(
            Prediction.earnings_date >= start_date,
            Prediction.earnings_date <= end_date,
        )
        .order_by(Prediction.earnings_date.asc())
    ).all()

    # Upcoming earnings for pending signals (next 14 days)
    upcoming_rows = db.execute(
        select(Prediction)
        .where(
            Prediction.earnings_date > today,
            Prediction.earnings_date <= today + timedelta(days=14),
        )
        .order_by(Prediction.earnings_date.asc())
    ).scalars().all()

    if not rows and not upcoming_rows:
        return {"strategies": [], "events": 0, "launch_date": start_date.isoformat(),
                "as_of": datetime.utcnow().isoformat(), "initial_capital": initial_capital}

    df_rows = [_to_dict(p, o) for p, o in rows]
    df = pd.DataFrame(df_rows) if df_rows else pd.DataFrame()

    results = []
    live_feed = []  # Cross-strategy ticker tape

    for strat in STRATEGIES:
        sig_fn = SIGNALS[strat.code]
        equity = initial_capital
        cash = initial_capital
        equity_curve = [{"date": start_date.isoformat(), "equity": equity}]
        closed_trades = []
        currently_open = []
        n_trades = wins = 0
        trade_returns = []

        for r in df_rows:
            s = sig_fn(r)
            if s == 0:
                continue
            # Decide if this trade is "currently open" or already "closed"
            # Pre-earnings strategies enter on earnings day, exit at T+5
            # Post-earnings enter at T+1, exit at T+6
            exit_offset = 5 if strat.code in PRE_EARNINGS else 6
            entry_offset = 0 if strat.code in PRE_EARNINGS else 1
            entry_date = r["date"] + timedelta(days=entry_offset)
            exit_date = r["date"] + timedelta(days=exit_offset)

            if r["outcome_known"]:
                # Trade closes — compute realized P&L
                ret = s * r["t5_return"]
                pnl = equity * position_size_pct * ret
                equity += pnl
                n_trades += 1
                if ret > 0: wins += 1
                trade_returns.append(ret)
                closed_trades.append({
                    "date": entry_date.isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "ticker": r["ticker"],
                    "sector": r["sector"],
                    "side": "LONG" if s == 1 else "SHORT",
                    "return_pct": round(ret * 100, 3),
                    "pnl": round(pnl, 2),
                    "win": ret > 0,
                })
                equity_curve.append({"date": exit_date.isoformat(), "equity": round(equity, 2)})
                # Add to live feed (recent closes only)
                if exit_date >= today - timedelta(days=14):
                    live_feed.append({
                        "type": "close",
                        "timestamp": exit_date.isoformat(),
                        "strategy": strat.code,
                        "ticker": r["ticker"],
                        "side": "LONG" if s == 1 else "SHORT",
                        "return_pct": round(ret * 100, 2),
                        "win": ret > 0,
                    })
            else:
                # Currently open — outcome not yet known
                if exit_date > today and r["date"] >= today - timedelta(days=exit_offset):
                    currently_open.append({
                        "entry_date": entry_date.isoformat(),
                        "exit_date": exit_date.isoformat(),
                        "ticker": r["ticker"],
                        "sector": r["sector"],
                        "side": "LONG" if s == 1 else "SHORT",
                        "confidence": round(r["confidence"] * 100, 1),
                        "expected_move": round(r["expected_move"] * 100, 1) if r["expected_move"] else None,
                        "notional": round(equity * position_size_pct, 2),
                        "days_held": (today - entry_date).days,
                    })
                    live_feed.append({
                        "type": "open",
                        "timestamp": entry_date.isoformat(),
                        "strategy": strat.code,
                        "ticker": r["ticker"],
                        "side": "LONG" if s == 1 else "SHORT",
                    })

        # Pending signals from upcoming earnings (ML strategies only)
        pending_signals = []
        if strat.code in PRE_EARNINGS:
            for p in upcoming_rows:
                row = {
                    "prob_up": p.direction_prob_up or 0,
                    "prob_down": p.direction_prob_down or 0,
                    "prob_flat": p.direction_prob_flat or 0,
                    "confidence": p.confidence_score or 0,
                    "expected_move": p.expected_move_pct or 0,
                    "gap_pct": 0.0,
                }
                s = sig_fn(row)
                if s != 0:
                    pending_signals.append({
                        "ticker": p.ticker,
                        "earnings_date": p.earnings_date.isoformat(),
                        "side": "LONG" if s == 1 else "SHORT",
                        "confidence": round((p.confidence_score or 0) * 100, 1),
                        "expected_move": round((p.expected_move_pct or 0) * 100, 1) if p.expected_move_pct else None,
                        "sector": p.sector or "—",
                        "days_until": (p.earnings_date - today).days,
                    })

        # Stats
        ret_pct = (equity / initial_capital) - 1
        win_rate = wins / n_trades if n_trades else 0
        # Downsample equity curve to ~150 points
        if len(equity_curve) > 150:
            step = max(1, len(equity_curve) // 150)
            ec = equity_curve[::step] + [equity_curve[-1]]
        else:
            ec = equity_curve

        # Sharpe
        sharpe = 0
        if len(trade_returns) > 1:
            tr = pd.Series(trade_returns)
            if tr.std() > 1e-9:
                sharpe = float(tr.mean() / tr.std() * sqrt(50))

        # Max drawdown
        eq_series = pd.Series([e["equity"] for e in equity_curve])
        running_max = eq_series.cummax()
        dd = ((eq_series - running_max) / running_max).min()

        results.append({
            "code": strat.code, "name": strat.name, "emoji": strat.emoji,
            "tagline": strat.tagline, "citation": strat.citation,
            "color": strat.color, "description": strat.description,
            "final_equity": round(equity, 2),
            "total_return": round(ret_pct, 4),
            "trades": n_trades, "wins": wins,
            "win_rate": round(win_rate, 4),
            "sharpe": round(sharpe, 3),
            "max_drawdown": round(float(dd) if pd.notna(dd) else 0.0, 4),
            "equity_curve": ec,
            "recent_closes": sorted(closed_trades, key=lambda x: x["exit_date"], reverse=True)[:8],
            "currently_open": currently_open,
            "pending_signals": pending_signals[:5],
        })

    results.sort(key=lambda x: -x["final_equity"])
    live_feed.sort(key=lambda x: x["timestamp"], reverse=True)

    return {
        "strategies": results,
        "events": len(df_rows),
        "initial_capital": initial_capital,
        "launch_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "as_of": datetime.utcnow().isoformat(),
        "live_feed": live_feed[:25],
        "days_since_launch": (today - start_date).days,
    }
