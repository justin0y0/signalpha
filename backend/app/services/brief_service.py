"""Alpha Brief — the daily recurring surface.

Positioning note (this drives what the brief actually says)
----------------------------------------------------------
The brief leads with the quiet/loud split and the options context around it, not with
"we think NVDA goes up", because the measured skill is in the first question and not
the second. See CLAUDE.md for the current accuracy figures — they are deliberately not
duplicated here, since a docstring is the last place anyone remembers to update and
this one spent two label revisions quoting numbers that no longer existed.

Thresholds are expressed relative to BASE_RATE rather than as absolute probabilities.
A P(FLAT) of 0.60 means something different when non-events are 47.7% of the universe
than when they were 60.7%, and hardcoding the absolute number silently changed what
this surface promised every time the labelling moved.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Share of events that are genuine non-events under the current per-stock median
# labelling. Measured over 5,553 events; see data_pipeline/compute_flat_bands.py.
BASE_RATE = 0.477

# A row earns the quiet list by being meaningfully more certain than the base rate,
# not merely above 50%.
QUIET_THRESHOLD = BASE_RATE + 0.13   # 0.607
LOUD_THRESHOLD = BASE_RATE - 0.08    # 0.397


def _rows_for_window(db: Session, start: date, end: date, tickers: list[str] | None) -> list[dict[str, Any]]:
    sql = """
        SELECT e.ticker, e.company_name, e.sector, e.earnings_date, e.report_time,
               p.direction_prob_up, p.direction_prob_flat, p.direction_prob_down,
               p.expected_move_pct, p.confidence_score,
               f.atm_iv, f.iv_rank, f.iv_crush_hist
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

    quiet, loud, unscored = [], [], []
    for r in rows:
        flat = r.get("direction_prob_flat")
        if flat is None:
            unscored.append(r)
        elif float(flat) >= QUIET_THRESHOLD:
            quiet.append(r)
        elif float(flat) <= LOUD_THRESHOLD:
            loud.append(r)

    quiet.sort(key=lambda r: -float(r["direction_prob_flat"]))
    loud.sort(key=lambda r: float(r["direction_prob_flat"]))

    def fmt(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticker": r["ticker"],
            "company_name": r["company_name"],
            "sector": r["sector"],
            "earnings_date": r["earnings_date"].isoformat() if r["earnings_date"] else None,
            "report_time": r["report_time"],
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
        "counts": {"total": len(rows), "quiet": len(quiet), "loud": len(loud), "unscored": len(unscored)},
        "quiet": [fmt(r) for r in quiet[:12]],
        "loud": [fmt(r) for r in loud[:12]],
        "methodology": {
            "quiet_threshold": QUIET_THRESHOLD,
            "loud_threshold": LOUD_THRESHOLD,
            "validated_skill": "At P(FLAT) >= 0.60 the model is correct 66.6% of the time vs a 49.8% base rate (n=862).",
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
    if brief["quiet"]:
        lines.append(f"*Likely quiet* ({c['quiet']})")
        for r in brief["quiet"][:6]:
            iv = f" · IV {r['atm_iv']*100:.0f}%" if r.get("atm_iv") else ""
            lines.append(f"  `{r['ticker']:<6}` {r['earnings_date']}  P(flat) {r['p_flat']*100:.0f}%{iv}")
        lines.append("")
    if brief["loud"]:
        lines.append(f"*Move expected* ({c['loud']})")
        for r in brief["loud"][:6]:
            em = f" · ±{r['expected_move_pct']*100:.1f}%" if r.get("expected_move_pct") else ""
            lines.append(f"  `{r['ticker']:<6}` {r['earnings_date']}  P(flat) {r['p_flat']*100:.0f}%{em}")
        lines.append("")
    lines.append("_Quiet calls are the model's one validated skill (66.6% vs 49.8% base rate)._")
    lines.append("_It has no directional edge. Not investment advice._")
    return "\n".join(lines)
