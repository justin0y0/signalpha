"""Strategy Showdown — multi-strategy backtest comparison.

Five distinct trading philosophies, $1M each, run on the same historical
earnings event set. Each strategy is academically documented with citations.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from math import sqrt
from typing import Callable
import pandas as pd
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from backend.app.db.models import Outcome, Prediction


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
        "Only trade when the model is highly confident (≥75%) AND the expected move is large (≥4%). Quality over quantity."),
    StrategyDef("FADER", "The Fader", "🔁", "Markets overreact",
        "De Bondt & Thaler (JF 1985) · Overreaction",
        "#a78bfa",
        "Fade large gaps. The crowd over-reacts to earnings; reversion follows. Short rallies, long panics."),
    StrategyDef("CONTRARIAN", "The Contrarian", "🐻", "Be greedy when others are fearful",
        "Templeton's maximum pessimism",
        "#f87171",
        "Fade the model's own high-conviction calls. When the algorithm screams DOWN, go LONG. Anti-consensus."),
]


# ── Strategy entry rules: return +1 (LONG), -1 (SHORT), 0 (skip) ─────────────
def _quant(row) -> int:
    if (row["confidence"] or 0) < 0.55: return 0
    if row["prob_up"] > row["prob_down"] and row["prob_up"] > row["prob_flat"]: return 1
    if row["prob_down"] > row["prob_up"] and row["prob_down"] > row["prob_flat"]: return -1
    return 0

def _drifter(row) -> int:
    if row["gap_pct"] > 0.03: return 1
    if row["gap_pct"] < -0.03: return -1
    return 0

def _sniper(row) -> int:
    if (row["confidence"] or 0) < 0.75: return 0
    if (row["expected_move"] or 0) < 0.04: return 0
    if row["prob_up"] > row["prob_down"] and row["prob_up"] > row["prob_flat"]: return 1
    if row["prob_down"] > row["prob_up"] and row["prob_down"] > row["prob_flat"]: return -1
    return 0

def _fader(row) -> int:
    if row["gap_pct"] > 0.05: return -1
    if row["gap_pct"] < -0.05: return 1
    return 0

def _contrarian(row) -> int:
    if row["prob_up"] > 0.65: return -1
    if row["prob_down"] > 0.65: return 1
    return 0


SIGNALS: dict[str, Callable] = {
    "QUANT": _quant, "DRIFTER": _drifter, "SNIPER": _sniper,
    "FADER": _fader, "CONTRARIAN": _contrarian,
}


def run_showdown(
    db: Session,
    start_date: date,
    end_date: date,
    initial_capital: float = 1_000_000,
    position_size_pct: float = 0.05,
) -> dict:
    """Run all five strategies on the same historical window."""
    rows = db.execute(
        select(Prediction, Outcome)
        .join(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(
            Prediction.earnings_date >= start_date,
            Prediction.earnings_date <= end_date,
            Outcome.actual_t5_return.is_not(None),
        )
        .order_by(Prediction.earnings_date.asc())
    ).all()

    if not rows:
        return {"strategies": [], "events": 0, "initial_capital": initial_capital,
                "start_date": start_date.isoformat(), "end_date": end_date.isoformat()}

    df = pd.DataFrame([{
        "date": p.earnings_date, "ticker": p.ticker, "sector": p.sector or "—",
        "prob_up": p.direction_prob_up or 0.0,
        "prob_down": p.direction_prob_down or 0.0,
        "prob_flat": p.direction_prob_flat or 0.0,
        "confidence": p.confidence_score or 0.0,
        "expected_move": p.expected_move_pct or 0.0,
        "gap_pct": o.actual_t1_gap_pct or 0.0,
        "t5_return": o.actual_t5_return or 0.0,
    } for p, o in rows])

    results = []
    for strat in STRATEGIES:
        sig = df.apply(SIGNALS[strat.code], axis=1)
        # SHORT (-1) profits when t5_return is negative → multiply
        trade_ret = sig * df["t5_return"]
        equity = (1.0 + position_size_pct * trade_ret).cumprod() * initial_capital
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max

        taken_mask = sig != 0
        n_trades = int(taken_mask.sum())
        wins = int((taken_mask & (trade_ret > 0)).sum())
        win_rate = wins / n_trades if n_trades else 0
        tr = trade_ret[taken_mask]
        # ~50 events/year on this dataset (5400 events / ~10 years)
        ann = sqrt(50)
        sharpe = float(tr.mean() / tr.std() * ann) if (n_trades > 1 and tr.std() > 1e-9) else 0
        # Sortino (downside only)
        downside = tr[tr < 0]
        sortino = float(tr.mean() / downside.std() * ann) if (len(downside) > 1 and downside.std() > 1e-9) else 0

        # Downsample equity curve to ~200 points
        n = len(df)
        step = max(1, n // 200)
        idxs = list(range(0, n, step))
        if idxs[-1] != n - 1: idxs.append(n - 1)
        curve = [{
            "date": df["date"].iloc[i].isoformat(),
            "equity": float(equity.iloc[i]),
            "drawdown": float(drawdown.iloc[i]),
        } for i in idxs]

        # Most recent 20 trades for attribution
        trades = []
        for i in reversed(df.index):
            if sig.iloc[i] == 0: continue
            trades.append({
                "date": df["date"].iloc[i].isoformat(),
                "ticker": df["ticker"].iloc[i],
                "sector": df["sector"].iloc[i],
                "side": "LONG" if sig.iloc[i] == 1 else "SHORT",
                "return_pct": round(float(trade_ret.iloc[i]) * 100, 3),
                "win": bool(trade_ret.iloc[i] > 0),
            })
            if len(trades) >= 20: break

        results.append({
            "code": strat.code, "name": strat.name, "emoji": strat.emoji,
            "tagline": strat.tagline, "citation": strat.citation,
            "color": strat.color, "description": strat.description,
            "final_equity": round(float(equity.iloc[-1]), 2),
            "total_return": round(float(equity.iloc[-1] / initial_capital - 1), 4),
            "trades": n_trades, "wins": wins,
            "win_rate": round(win_rate, 4),
            "sharpe": round(sharpe, 3), "sortino": round(sortino, 3),
            "max_drawdown": round(float(drawdown.min()), 4),
            "equity_curve": curve, "recent_trades": trades,
        })

    results.sort(key=lambda x: -x["final_equity"])
    return {
        "strategies": results,
        "events": int(len(df)),
        "initial_capital": initial_capital,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
