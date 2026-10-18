"""Receipts — every call the site has made in public, and how each one is doing today.

A track record built from a backtest can always be tuned until it looks good. This one
can't: it only holds calls that were on the site before the outcome existed.

Three kinds of call
-------------------
* Follow-through (the one direction call with evidence behind it): a report gaps up by
  more than SIGNAL_K x its usual move, the site says "long at the reaction-day close,
  hold SIGNAL_HOLD sessions". Each is marked to the latest close every time the page is
  read — sessions elapsed, return so far, the S&P 500 over the same days, and what $10k
  in each call would be worth. After SIGNAL_HOLD sessions it closes at that close.
* Breakout flags: before each report the model gives P(moves more than usual). The value
  standing when the report came out is frozen in `call_log` (freeze_due), then graded
  against the move (grade_due). Flagged = the model's top decile at the time.
* The direction lean: frozen and graded the same way. It backtests as a coin flip and is
  shown here so that stays visible.

Nothing in `call_log` is ever rewritten once frozen; a retrain overwrites predictions,
not receipts.
"""
from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.services.headline_service import _breakout_metrics, move_tier
from backend.app.services.playbook_service import SIGNAL_HOLD, SIGNAL_K, signal_summary

# The follow-through rule and the leak-free models went live with the 2026-10-10 rebuild.
LIVE_SINCE = date(2026, 10, 12)
STAKE = 10_000.0
LEAN_DEADBAND = 0.015

DDL = [
    """
    CREATE TABLE IF NOT EXISTS call_log (
        ticker        TEXT NOT NULL,
        earnings_date DATE NOT NULL,
        report_time   TEXT,
        prob_move     REAL,
        move_tier     TEXT,
        base_rate     REAL,
        band          REAL,
        implied_move  REAL,
        lean_up       REAL,
        frozen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        actual_move   REAL,
        moved         BOOLEAN,
        lean_hit      BOOLEAN,
        graded_at     TIMESTAMPTZ,
        PRIMARY KEY (ticker, earnings_date)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_call_log_date ON call_log (earnings_date)",
]


# ───────────────────────────── freezing and grading ─────────────────────────────

def freeze_due(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """Copy the standing call for every report whose bell has rung and is not frozen yet."""
    from backend.app.services.arena_service import ET, _cutoff
    from backend.app.services.flat_band import load_flat_bands

    now_et = (now or datetime.now(timezone.utc)).astimezone(ET)
    rows = db.execute(text("""
        SELECT e.ticker, e.earnings_date, e.report_time, p.prob_move, p.lean_up, f.expected_move_pct AS implied
        FROM earnings_events e
        JOIN predictions p ON p.ticker=e.ticker AND p.earnings_date=e.earnings_date
        LEFT JOIN price_features f ON f.ticker=e.ticker AND f.earnings_date=e.earnings_date
        WHERE e.earnings_date BETWEEN :a AND :b AND p.prob_move IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM call_log c WHERE c.ticker=e.ticker AND c.earnings_date=e.earnings_date)"""),
        {"a": max(LIVE_SINCE, now_et.date() - timedelta(days=4)), "b": now_et.date() + timedelta(days=1)}).mappings().all()
    due = [r for r in rows if now_et >= _cutoff(r["earnings_date"], r["report_time"])]
    if not due:
        return {"frozen": 0}
    metrics = _breakout_metrics() or {}
    bands = load_flat_bands(db, sorted({r["ticker"] for r in due}))
    for r in due:
        p = float(r["prob_move"])
        db.execute(text("""
            INSERT INTO call_log (ticker, earnings_date, report_time, prob_move, move_tier, base_rate, band,
                                  implied_move, lean_up)
            VALUES (:t, :d, :rt, :p, :tier, :base, :band, :im, :lu)
            ON CONFLICT (ticker, earnings_date) DO NOTHING"""),
            {"t": r["ticker"], "d": r["earnings_date"], "rt": r["report_time"], "p": p,
             "tier": move_tier(p, metrics), "base": metrics.get("base_rate"), "band": bands.get(r["ticker"]),
             "im": _num(r["implied"]), "lu": _num(r["lean_up"])})
    db.commit()
    return {"frozen": len(due)}


def grade_due(db: Session) -> dict[str, Any]:
    rows = db.execute(text("""
        SELECT c.ticker, c.earnings_date, c.band, c.lean_up, o.actual_t1_close_return AS r, o.flat_band
        FROM call_log c JOIN outcomes o ON o.ticker=c.ticker AND o.earnings_date=c.earnings_date
        WHERE c.graded_at IS NULL AND o.actual_t1_close_return IS NOT NULL""")).mappings().all()
    n = 0
    for r in rows:
        move = _num(r["r"])
        band = _num(r["band"]) or _num(r["flat_band"])
        if move is None or not band:
            continue
        lu = _num(r["lean_up"])
        hit = None if lu is None or abs(lu - 0.5) < LEAN_DEADBAND or move == 0 else ((move > 0) == (lu > 0.5))
        db.execute(text("""UPDATE call_log SET actual_move=:m, moved=:mv, lean_hit=:h, graded_at=NOW()
                           WHERE ticker=:t AND earnings_date=:d"""),
                   {"m": move, "mv": abs(move) > band, "h": hit, "t": r["ticker"], "d": r["earnings_date"]})
        n += 1
    db.commit()
    return {"graded": n}


# ───────────────────────────── prices ─────────────────────────────

_px: dict[tuple, tuple[float, dict]] = {}


def bars(tickers: list[str], start: date, ttl: int = 600) -> dict[str, pd.DataFrame]:
    """Daily opens and closes (unadjusted, like outcomes), one column per ticker."""
    key = (tuple(sorted(set(tickers))), start)
    hit = _px.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    import yfinance as yf

    raw = yf.download(list(key[0]), start=start.isoformat(), auto_adjust=False, progress=False,
                      threads=True, group_by="ticker")
    out = {"Open": pd.DataFrame(), "Close": pd.DataFrame()}
    if raw is not None and not raw.empty:
        for f in out:
            if isinstance(raw.columns, pd.MultiIndex):
                out[f] = pd.DataFrame({t: raw[t][f] for t in key[0] if t in raw.columns.get_level_values(0)})
            else:
                out[f] = pd.DataFrame({key[0][0]: raw[f]})
            out[f].index = pd.to_datetime(out[f].index).tz_localize(None).normalize()
    _px[key] = (time.time(), out)
    return out


def closes(tickers: list[str], start: date, ttl: int = 600) -> pd.DataFrame:
    return bars(tickers, start, ttl)["Close"]


# ───────────────────────────── read side ─────────────────────────────

def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _wilson(k: int, n: int, z: float = 1.645) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def follow_through(db: Session) -> dict[str, Any]:
    rows = db.execute(text("""
        SELECT o.ticker, e.company_name, e.sector, o.earnings_date, COALESCE(o.reaction_date, o.earnings_date) AS rd,
               o.actual_t1_gap_pct AS gap, o.flat_band AS band, u.tier
        FROM outcomes o
        JOIN earnings_events e ON e.ticker=o.ticker AND e.earnings_date=o.earnings_date
        LEFT JOIN universe u ON u.ticker=o.ticker
        WHERE COALESCE(o.reaction_date, o.earnings_date) >= :since
          AND o.actual_t1_gap_pct IS NOT NULL AND o.flat_band > 0
          AND o.actual_t1_gap_pct > :k * o.flat_band
        ORDER BY rd DESC, o.ticker"""), {"since": LIVE_SINCE, "k": SIGNAL_K}).mappings().all()
    calls: list[dict[str, Any]] = []
    if rows:
        px = closes([r["ticker"] for r in rows] + ["SPY"], LIVE_SINCE - timedelta(days=7))
        for r in rows:
            t, rd = r["ticker"], pd.Timestamp(r["rd"])
            if t not in px or "SPY" not in px:
                continue
            s, spy = px[t].dropna(), px["SPY"].dropna()
            if rd not in s.index:
                continue
            after = s[s.index > rd]
            held = after.iloc[:SIGNAL_HOLD]
            closed = len(after) >= SIGNAL_HOLD
            entry = float(s.loc[rd])
            mark_day = held.index[-1] if len(held) else rd
            mark = float(held.iloc[-1]) if len(held) else entry
            spy_entry = float(spy.loc[rd]) if rd in spy.index else None
            spy_mark = float(spy.loc[mark_day]) if mark_day in spy.index else None
            ret = mark / entry - 1
            spy_ret = None if not spy_entry or spy_mark is None else spy_mark / spy_entry - 1
            calls.append({
                "ticker": t, "company": r["company_name"], "sector": r["sector"], "tier": r["tier"] or "core",
                "earnings_date": str(r["earnings_date"]), "called_on": str(rd.date()),
                "gap": _num(r["gap"]), "band": _num(r["band"]), "gap_x": _num(r["gap"]) / float(r["band"]),
                "entry": entry, "mark": mark, "mark_on": str(mark_day.date()),
                "sessions": int(len(held)), "hold": SIGNAL_HOLD, "status": "closed" if closed else "open",
                "ret": ret, "spy_ret": spy_ret, "excess": None if spy_ret is None else ret - spy_ret,
                "pnl": STAKE * ret, "spy_pnl": None if spy_ret is None else STAKE * spy_ret,
            })
    rets = np.array([c["ret"] for c in calls])
    exc = np.array([c["excess"] for c in calls if c["excess"] is not None])
    k = int((rets > 0).sum())
    lo, hi = _wilson(k, len(rets))
    return {
        "calls": calls,
        "summary": {
            "n": len(calls), "open": sum(c["status"] == "open" for c in calls),
            "closed": sum(c["status"] == "closed" for c in calls),
            "right": k, "hit": k / len(rets) if len(rets) else None, "hit_lo": lo, "hit_hi": hi,
            "mean": float(rets.mean()) if len(rets) else None,
            "excess": float(exc.mean()) if len(exc) else None,
            "pnl": float(sum(c["pnl"] for c in calls)),
            "spy_pnl": float(sum(c["spy_pnl"] for c in calls if c["spy_pnl"] is not None)),
            "stake": STAKE,
        },
    }


def pre_report(db: Session) -> dict[str, Any]:
    rows = [dict(r) for r in db.execute(text("""
        SELECT c.*, e.company_name, u.tier AS cap_tier
        FROM call_log c
        JOIN earnings_events e ON e.ticker=c.ticker AND e.earnings_date=c.earnings_date
        LEFT JOIN universe u ON u.ticker=c.ticker
        ORDER BY c.earnings_date DESC, c.prob_move DESC""")).mappings().all()]
    for r in rows:
        for k in ("earnings_date",):
            r[k] = str(r[k])
        for k in ("frozen_at", "graded_at"):
            r[k] = r[k].isoformat() if r[k] else None
        lu = r.get("lean_up")
        r["lean"] = None if lu is None or abs(lu - 0.5) < LEAN_DEADBAND else ("UP" if lu > 0.5 else "DOWN")
    graded = [r for r in rows if r["graded_at"]]
    flagged = [r for r in graded if r["move_tier"] == "breakout"]
    fk = sum(1 for r in flagged if r["moved"])
    base_k = sum(1 for r in graded if r["moved"])
    leans = [r for r in graded if r["lean_hit"] is not None]
    lk = sum(1 for r in leans if r["lean_hit"])
    flo, fhi = _wilson(fk, len(flagged))
    llo, lhi = _wilson(lk, len(leans))
    return {
        "calls": rows[:300],
        "summary": {
            "frozen": len(rows), "graded": len(graded), "pending": len(rows) - len(graded),
            "flagged": len(flagged), "flagged_moved": fk,
            "flagged_rate": fk / len(flagged) if flagged else None, "flagged_lo": flo, "flagged_hi": fhi,
            "all_moved_rate": base_k / len(graded) if graded else None,
            "lean_n": len(leans), "lean_right": lk, "lean_hit": lk / len(leans) if leans else None,
            "lean_lo": llo, "lean_hi": lhi,
            # The freezing job started on 2026-10-15. Reports before that were copied from
            # predictions written before their bell, but the copy itself came later; the
            # page says how many.
            "late_frozen": sum(1 for r in rows if r["frozen_at"] and r["frozen_at"][:10] > r["earnings_date"]),
        },
    }


def receipts(db: Session) -> dict[str, Any]:
    m = _breakout_metrics() or {}
    return {
        "since": str(LIVE_SINCE),
        "as_of": datetime.now(timezone.utc).isoformat(),
        "follow": follow_through(db),
        "pre": pre_report(db),
        "expect": {
            "follow": signal_summary(db),
            "breakout_top": (m.get("top_decile") or {}).get("move_rate"),
            "breakout_base": m.get("base_rate"),
            "lean": 0.5,
        },
    }
