"""Alpha Brief — the daily recurring surface.

What it leads with, and why
---------------------------
The brief is built around one question: which reports this week are likely to move
their stock more than that stock usually moves on earnings. That is the only skill the
data supports out of sample — the breakout model's top decile clears its own band far
more often than the base rate, while "which will be quiet" and "which way" are near
chance. The brief therefore ranks by breakout risk and shows direction only as context.

No figure is typed here. List membership comes from the model's own out-of-sample
decile cut-offs and the skill statement from artifacts/move_metrics.json, so when the
model is retrained the brief changes with it instead of quoting a model that is gone.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.services.headline_service import _breakout_metrics, move_tier

logger = get_logger(__name__)

# Which list a report lands in comes from the breakout model's own out-of-sample decile
# cut-offs (artifacts/move_metrics.json), not hand-picked probabilities. The previous
# P(FLAT) thresholds were tuned to one calibration and silently changed meaning — or
# stopped selecting anything — each time the calibration moved.


def _rows_for_window(db: Session, start: date, end: date, tickers: list[str] | None) -> list[dict[str, Any]]:
    sql = """
        SELECT e.ticker, e.company_name, e.sector, e.earnings_date, e.report_time,
               p.direction_prob_up, p.direction_prob_flat, p.direction_prob_down,
               p.expected_move_pct, p.confidence_score, p.prob_move,
               f.atm_iv, f.iv_rank, f.iv_crush_hist,
               f.expected_move_pct AS implied_move_pct,
               (SELECT o.flat_band FROM outcomes o WHERE o.ticker = e.ticker AND o.flat_band IS NOT NULL
                ORDER BY o.earnings_date DESC LIMIT 1) AS own_band
        FROM earnings_events e
        LEFT JOIN predictions p
               ON p.ticker = e.ticker AND p.earnings_date = e.earnings_date
        LEFT JOIN price_features f
               ON f.ticker = e.ticker AND f.earnings_date = e.earnings_date
        WHERE e.earnings_date >= :start AND e.earnings_date <= :end
    """
    params: dict[str, Any] = {"start": start, "end": end}
    if tickers:
        sql += " AND e.ticker = ANY(:tickers)"
        params["tickers"] = tickers
    sql += " ORDER BY e.earnings_date ASC, e.ticker ASC"
    return [dict(r._mapping) for r in db.execute(text(sql), params).fetchall()]


def build_brief(db: Session, for_date: date | None = None, tickers: list[str] | None = None,
                horizon_days: int = 7) -> dict[str, Any]:
    """Assemble the brief. Pure data — no LLM, so it cannot hallucinate a number."""
    today = for_date or date.today()
    rows = _rows_for_window(db, today, today + timedelta(days=horizon_days), tickers)

    metrics = _breakout_metrics()
    breakout, elevated, normal, unscored = [], [], [], []
    for r in rows:
        tier = move_tier(float(r["prob_move"]) if r.get("prob_move") is not None else None, metrics)
        r["move_tier"] = tier
        {"breakout": breakout, "elevated": elevated, "normal": normal}.get(tier, unscored).append(r)
    for bucket in (breakout, elevated, normal):
        bucket.sort(key=lambda r: -float(r["prob_move"]))

    def fmt(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticker": r["ticker"],
            "company_name": r["company_name"],
            "sector": r["sector"],
            "earnings_date": r["earnings_date"].isoformat() if r["earnings_date"] else None,
            "report_time": r["report_time"],
            "prob_move": float(r["prob_move"]) if r.get("prob_move") is not None else None,
            "move_tier": r.get("move_tier"),
            "own_band": float(r["own_band"]) if r.get("own_band") is not None else None,
            "implied_move_pct": float(r["implied_move_pct"]) if r.get("implied_move_pct") is not None else None,
            "p_flat": float(r["direction_prob_flat"]) if r["direction_prob_flat"] is not None else None,
            "p_up": float(r["direction_prob_up"]) if r["direction_prob_up"] is not None else None,
            "p_down": float(r["direction_prob_down"]) if r["direction_prob_down"] is not None else None,
            "expected_move_pct": float(r["expected_move_pct"]) if r["expected_move_pct"] is not None else None,
            "atm_iv": float(r["atm_iv"]) if r.get("atm_iv") is not None else None,
            "iv_rank": float(r["iv_rank"]) if r.get("iv_rank") is not None else None,
            "iv_crush_hist": float(r["iv_crush_hist"]) if r.get("iv_crush_hist") is not None else None,
        }

    return {
        "as_of": today.isoformat(),
        "horizon_days": horizon_days,
        "personalised": bool(tickers),
        "watchlist_size": len(tickers) if tickers else 0,
        "counts": {"total": len(rows), "breakout": len(breakout), "elevated": len(elevated),
                   "normal": len(normal), "unscored": len(unscored)},
        "breakout": [fmt(r) for r in breakout[:12]],
        "elevated": [fmt(r) for r in elevated[:12]],
        "normal": [fmt(r) for r in normal[:20]],
        # Live evaluation numbers, so the page states the measured skill, not a stale one.
        "metrics": {k: metrics.get(k) for k in ("auc", "base_rate", "top_decile", "bottom_decile", "n",
                                                  "threshold_top_decile", "threshold_top_quintile")}
                   if metrics else None,
        "methodology": {
            "no_directional_edge": "The model has no measurable directional skill. Direction is shown for completeness only.",
            "disclaimer": "Research and education only. Not investment advice.",
        },
    }


def render_telegram(brief: dict[str, Any]) -> str:
    """Plain-text rendering for Telegram. Kept deterministic — no model in the loop."""
    c = brief["counts"]
    lines = [
        f"*SignAlpha Brief* · {brief['as_of']}",
        f"_{c['total']} earnings in the next {brief['horizon_days']}d_"
        + (f" · watchlist of {brief['watchlist_size']}" if brief["personalised"] else ""),
        "",
    ]
    def line(r: dict[str, Any]) -> str:
        pm = f"P(move) {r['prob_move']*100:.0f}%" if r.get("prob_move") is not None else ""
        band = f" · usual ±{r['own_band']*100:.1f}%" if r.get("own_band") else ""
        return f"  `{r['ticker']:<6}` {r['earnings_date']}  {pm}{band}"

    if brief["breakout"]:
        lines.append(f"*Breakout watch* ({c['breakout']})")
        lines += [line(r) for r in brief["breakout"][:8]]
        lines.append("")
    if brief["elevated"]:
        lines.append(f"*Elevated* ({c['elevated']})")
        lines += [line(r) for r in brief["elevated"][:6]]
        lines.append("")
    m = brief.get("metrics") or {}
    top = (m.get("top_decile") or {}).get("move_rate")
    if top is not None and m.get("base_rate") is not None:
        lines.append(f"_Out of sample, top-decile calls moved more than usual {top*100:.0f}% of the time "
                     f"vs a {m['base_rate']*100:.0f}% base rate (n={m.get('n')})._")
    lines.append("_No directional edge. Not investment advice._")
    return "\n".join(lines)
