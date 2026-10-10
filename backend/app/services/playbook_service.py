"""Post-earnings playbook: what a stock tends to do AFTER it has reacted.

Why the direction call lives here and not before the report
----------------------------------------------------------
On correctly-labelled, leak-free data (2026-10-10 rebuild) a pre-report direction model
scores AUC 0.50: nothing. What does show up is what happens after the number is out and
the stock has gapped. The clearest pattern needs no model at all:

    a stock that opens up by more than twice its usual earnings move tends to keep
    rising over the following month; a big gap down does NOT keep falling.

So the product's direction call is long-only and post-report. This module is the
evidence for it — any rule of the form "gap of size k x usual move, enter at the open
or the close of the reaction session, hold N sessions" is tested on every report on
record against the same leg for all reports — and the live list of reports that just
triggered.

Honest limits, repeated in the API payload so no surface can drop them:
  * the universe is today's large caps, so history is tilted toward stocks that did
    well (survivorship); that flatters "buy strength";
  * entering at the open of a gap day costs more than a normal trade; the default
    cost is a round-trip 10 bps and can be raised.
"""
from __future__ import annotations

import math
import time
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

# The rule the product actually trades and alerts on: gap up beyond SIGNAL_K x the usual
# move, bought at the close of the reaction session, held SIGNAL_HOLD sessions.
#
# Picked on the full 2008-2026 history, not the flattering recent window: the 5-session
# version scores t = 2.4 against the all-reports baseline (t = 3.9 if you start in 2021),
# while 20 sessions clears t = 3.9 on everything. Entering at the close costs almost
# nothing in return and avoids buying the open of a gap day.
SIGNAL_K = 2.0
SIGNAL_HOLD = 20
SIGNAL_ENTRY = "close"

LEGS = {
    ("open", 0): "open_close", ("open", 5): "open_t5", ("open", 20): "open_t20",
    ("close", 5): "close_t5", ("close", 20): "close_t20",
}
CAVEATS = [
    "survivorship: the universe is today's large caps, which tilts history toward winners",
    "entering at the open of a gap day usually costs more than the modelled round trip",
    "trying many rules guarantees some look good by chance; t above 3 is the bar",
]

_cache: dict[str, Any] = {"at": 0.0, "frame": None}


def _frame(db: Session) -> pd.DataFrame:
    if _cache["frame"] is not None and time.time() - _cache["at"] < 600:
        return _cache["frame"]
    df = pd.read_sql(text("""
        SELECT o.ticker, o.earnings_date, o.reaction_date, e.report_time, e.sector, e.company_name,
               o.actual_t1_gap_pct AS gap, o.actual_t1_close_return AS t1,
               o.actual_t5_return AS t5, o.actual_t20_return AS t20, o.flat_band AS band,
               s.surprise_pct AS surprise
        FROM outcomes o
        JOIN earnings_events e ON e.ticker=o.ticker AND e.earnings_date=o.earnings_date
        LEFT JOIN LATERAL (
            SELECT surprise_pct FROM earnings_surprises s
            WHERE s.ticker=o.ticker AND s.report_date BETWEEN o.earnings_date - 3 AND o.earnings_date + 3
            ORDER BY abs(s.report_date - o.earnings_date) LIMIT 1) s ON TRUE
        WHERE o.actual_t1_gap_pct IS NOT NULL AND o.actual_t1_close_return IS NOT NULL
          AND o.flat_band IS NOT NULL AND o.flat_band > 0
        ORDER BY o.earnings_date"""), db.bind)
    for c in ("gap", "t1", "t5", "t20", "band", "surprise"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[np.isfinite(df.gap) & np.isfinite(df.t1) & (df.gap > -0.9) & (df.t1.abs() < 1)].copy()
    df["open_close"] = (1 + df.t1) / (1 + df.gap) - 1
    df["open_t5"] = (1 + df.t5) / (1 + df.gap) - 1
    df["open_t20"] = (1 + df.t20) / (1 + df.gap) - 1
    df["close_t5"] = (1 + df.t5) / (1 + df.t1) - 1
    df["close_t20"] = (1 + df.t20) / (1 + df.t1) - 1
    df["gap_x"] = df.gap / df.band
    df["year"] = pd.to_datetime(df.earnings_date).dt.year
    _cache.update(at=time.time(), frame=df)
    return df


def _stats(x: np.ndarray) -> dict[str, Any]:
    n = len(x)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "hit": None, "t": None}
    sd = float(x.std(ddof=1)) if n > 1 else 0.0
    return {"n": n, "mean": float(x.mean()), "median": float(np.median(x)), "hit": float((x > 0).mean()),
            "t": float(x.mean() / sd * math.sqrt(n)) if sd > 0 else None}


def test(db: Session, side: str = "up", k: float = SIGNAL_K, action: str = "follow",
         entry: str = SIGNAL_ENTRY, hold: int = SIGNAL_HOLD, surprise: str = "any",
         cost_bps: float = 10.0) -> dict[str, Any]:
    """Every report that matched the rule, traded the same way, against the baseline."""
    leg = LEGS.get((entry, hold))
    if leg is None:
        return {"error": "unsupported entry/hold combination", "supported": [list(k_) for k_ in LEGS]}
    k = max(0.0, min(float(k), 6.0))
    df = _frame(db)
    df = df[np.isfinite(df[leg])]
    base_long = float(df[leg].mean())
    base_hit = float((df[leg] > 0).mean())

    if side == "up":
        m = df.gap_x > k
    elif side == "down":
        m = df.gap_x < -k
    else:
        m = df.gap_x.abs() > k
    if surprise == "beat":
        m &= df.surprise > 0
    elif surprise == "miss":
        m &= df.surprise < 0
    d = df[m].copy()
    sign = np.sign(d.gap_x.to_numpy()) * (1 if action == "follow" else -1)
    cost = cost_bps / 10_000.0
    d["ret"] = sign * d[leg].to_numpy() - cost
    d["excess"] = sign * (d[leg].to_numpy() - base_long) - cost
    d["side"] = np.where(sign > 0, "LONG", "SHORT")

    raw, exc = _stats(d.ret.to_numpy()), _stats(d.excess.to_numpy())
    n, t = raw["n"], exc["t"]
    if n < 50:
        verdict = "thin"
    elif t is not None and t >= 3 and exc["mean"] > 0:
        verdict = "edge"
    elif t is not None and t >= 2 and exc["mean"] > 0:
        verdict = "weak"
    elif t is not None and t <= -2:
        verdict = "negative"
    else:
        verdict = "none"

    years = []
    for y, g in d.groupby("year"):
        years.append({"year": int(y), "n": int(len(g)), "mean": float(g.ret.mean()),
                      "excess": float(g.excess.mean()), "hit": float((g.ret > 0).mean())})
    curve, total = [], 0.0
    for dt, r in zip(d.earnings_date, d.ret):
        total += float(r)
        curve.append({"d": str(dt), "v": round(total, 4)})
    if len(curve) > 240:
        step = len(curve) // 240 + 1
        curve = curve[::step] + [curve[-1]]
    recent = [{
        "ticker": r.ticker, "date": str(r.reaction_date or r.earnings_date), "side": r.side,
        "gap": float(r.gap), "band": float(r.band), "gap_x": float(r.gap_x),
        "surprise": None if pd.isna(r.surprise) else float(r.surprise), "ret": float(r.ret),
    } for r in d.sort_values("earnings_date", ascending=False).head(14).itertuples()]
    return {
        "rule": {"side": side, "k": k, "action": action, "entry": entry, "hold": hold,
                 "surprise": surprise, "cost_bps": cost_bps},
        "stats": raw, "excess": exc, "verdict": verdict,
        "baseline": {"n": int(len(df)), "mean_long": base_long, "hit_long": base_hit},
        "years": years, "curve": curve, "recent": recent,
        "span": {"from": str(df.earnings_date.min()), "to": str(df.earnings_date.max())},
        "caveats": CAVEATS,
    }


def grid(db: Session, entry: str = SIGNAL_ENTRY, hold: int = SIGNAL_HOLD) -> dict[str, Any]:
    """Excess return of 'follow the gap' for each direction and size — where the edge is."""
    cells = []
    for side in ("up", "down"):
        for k in (0.5, 1.0, 1.5, 2.0, 3.0):
            r = test(db, side=side, k=k, entry=entry, hold=hold)
            if "error" in r:
                return r
            cells.append({"side": side, "k": k, "n": r["stats"]["n"], "mean": r["stats"]["mean"],
                          "hit": r["stats"]["hit"], "excess": r["excess"]["mean"], "t": r["excess"]["t"],
                          "verdict": r["verdict"]})
    return {"entry": entry, "hold": hold, "cells": cells}


def signal_summary(db: Session) -> dict[str, Any]:
    """The headline rule's numbers, for every surface that quotes it."""
    r = test(db, side="up", k=SIGNAL_K, entry=SIGNAL_ENTRY, hold=SIGNAL_HOLD)
    short = test(db, side="up", k=SIGNAL_K, entry=SIGNAL_ENTRY, hold=5)
    years = [y for y in r["years"] if y["n"] >= 20]
    return {
        "k": SIGNAL_K, "hold": SIGNAL_HOLD, "entry": SIGNAL_ENTRY,
        "n": r["stats"]["n"], "mean": r["stats"]["mean"], "hit": r["stats"]["hit"],
        "excess": r["excess"]["mean"], "t": r["excess"]["t"], "verdict": r["verdict"],
        "baseline_mean": r["baseline"]["mean_long"], "baseline_hit": r["baseline"]["hit_long"],
        "years_positive": sum(1 for y in years if y["excess"] > 0), "years_total": len(years),
        # The shorter hold, shown so nobody has to take the 20-session choice on trust.
        "mean_5d": short["stats"]["mean"], "hit_5d": short["stats"]["hit"], "t_5d": short["excess"]["t"],
        "span": r["span"],
    }


def live(db: Session, days: int = 10) -> dict[str, Any]:
    """Reports that have just reacted, and which of them triggered the signal."""
    since = date.today() - timedelta(days=days)
    rows = db.execute(text("""
        SELECT o.ticker, e.company_name, e.sector, o.earnings_date, o.reaction_date, e.report_time,
               o.actual_t1_gap_pct AS gap, o.actual_t1_close_return AS t1, o.actual_t5_return AS t5,
               o.flat_band AS band, s.surprise_pct AS surprise, p.prob_move
        FROM outcomes o
        JOIN earnings_events e ON e.ticker=o.ticker AND e.earnings_date=o.earnings_date
        LEFT JOIN predictions p ON p.ticker=o.ticker AND p.earnings_date=o.earnings_date
        LEFT JOIN LATERAL (
            SELECT surprise_pct FROM earnings_surprises s
            WHERE s.ticker=o.ticker AND s.report_date BETWEEN o.earnings_date - 3 AND o.earnings_date + 3
            ORDER BY abs(s.report_date - o.earnings_date) LIMIT 1) s ON TRUE
        WHERE COALESCE(o.reaction_date, o.earnings_date) >= :since AND o.actual_t1_gap_pct IS NOT NULL
        ORDER BY COALESCE(o.reaction_date, o.earnings_date) DESC, o.ticker"""), {"since": since}).mappings().all()
    out = []
    for r in rows:
        gap = float(r["gap"]) if r["gap"] is not None else None
        band = float(r["band"]) if r["band"] else None
        gx = gap / band if gap is not None and band else None
        t1 = float(r["t1"]) if r["t1"] is not None else None
        t5 = float(r["t5"]) if r["t5"] is not None else None
        signal = "none"
        if gx is not None:
            signal = "long" if gx > SIGNAL_K else "watch" if gx > 1 else "gap_down" if gx < -1 else "none"
        out.append({
            "ticker": r["ticker"], "company": r["company_name"], "sector": r["sector"],
            "earnings_date": str(r["earnings_date"]),
            "reaction_date": str(r["reaction_date"] or r["earnings_date"]), "report_time": r["report_time"],
            "gap": gap, "band": band, "gap_x": gx,
            "surprise": float(r["surprise"]) if r["surprise"] is not None else None,
            "day1_from_open": None if gap is None or t1 is None else (1 + t1) / (1 + gap) - 1,
            "since_open_5d": None if gap is None or t5 is None else (1 + t5) / (1 + gap) - 1,
            "signal": signal,
        })
    return {"signal": signal_summary(db), "reports": out,
            "triggered": [r["ticker"] for r in out if r["signal"] == "long"], "caveats": CAVEATS}
