"""The direction book — four calls made at the open of a report's reaction session.

Before the report, direction is a coin flip (direction_lean.py, 86k reports). After it,
the open tells you two things the market has not finished pricing: how far the stock
gapped against its own usual move, and whether earnings beat or missed. Searched over
144k reports, fixed on 2008-2018 and confirmed on 2019-2026 (data the choice never saw),
four rules survive:

* follow_gap  gap up > 2x usual            long  from the reaction close to the T+20 close
* fade_spike  gap up > 3x usual            short at the open, cover at the close
* buy_flush   gap down > 2x usual          long  at the open, sell at the close
* fade_miss   gap up > 1x usual, EPS miss  short at the open, cover at the T+5 close

`hold` counts sessions after the entry session, matching the outcome legs (T+1 is the
reaction session, so T+5 is four sessions after it and T+20 nineteen).

Each applies only in the market-cap tiers where it held on its own (`TIERS`). A call is
written to `direction_calls` the morning it is made, with the time; the price it is
marked against is the official open or close of that session, read afterwards. Nothing
is back-dated: the three intraday/short-horizon rules start on LIVE_FROM, the first
session after they were published; follow_gap has been public since 2026-10-10.
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

STAKE = 10_000.0
COST = 0.001  # round trip, as in the backtest

RULES: dict[str, dict[str, Any]] = {
    "follow_gap": {"side": "LONG", "entry": "close", "hold": 19, "tiers": ("large", "mid", "small"),
                   "leg": "close_t20", "live_from": date(2026, 10, 12)},
    "fade_spike": {"side": "SHORT", "entry": "open", "hold": 0, "tiers": ("large", "mid", "small"),
                   "leg": "open_close", "live_from": date(2026, 10, 19)},
    "buy_flush": {"side": "LONG", "entry": "open", "hold": 0, "tiers": ("large", "mid"),
                  "leg": "open_close", "live_from": date(2026, 10, 19)},
    "fade_miss": {"side": "SHORT", "entry": "open", "hold": 4, "tiers": ("small",),
                  "leg": "open_t5", "live_from": date(2026, 10, 19)},
}
LIVE_FROM = min(r["live_from"] for r in RULES.values())


def matches(key: str, gap_x: float | None, surprise: float | None) -> bool:
    if gap_x is None:
        return False
    if key == "follow_gap":
        return gap_x > 2
    if key == "fade_spike":
        return gap_x > 3
    if key == "buy_flush":
        return gap_x < -2
    if key == "fade_miss":
        return gap_x > 1 and surprise is not None and surprise < 0
    return False


DDL = [
    """
    CREATE TABLE IF NOT EXISTS direction_calls (
        id            BIGSERIAL PRIMARY KEY,
        rule          TEXT NOT NULL,
        ticker        TEXT NOT NULL,
        earnings_date DATE NOT NULL,
        session       DATE NOT NULL,
        side          TEXT NOT NULL,
        entry         TEXT NOT NULL,
        hold          INTEGER NOT NULL,
        gap           REAL,
        band          REAL,
        gap_x         REAL,
        surprise      REAL,
        tier          TEXT,
        called_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        origin        TEXT NOT NULL DEFAULT 'open',
        UNIQUE (rule, ticker, earnings_date)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_direction_calls_session ON direction_calls (session)",
]


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


# ───────────────────────────── backtest ─────────────────────────────

_bt: dict[str, Any] = {"at": 0.0, "body": None}


def _stats(x: np.ndarray) -> dict[str, Any]:
    n = len(x)
    if n < 2:
        return {"n": n, "mean": None, "hit": None, "t": None}
    sd = float(x.std(ddof=1))
    return {"n": n, "mean": float(x.mean()), "hit": float((x > 0).mean()),
            "t": float(x.mean() / sd * math.sqrt(n)) if sd > 0 else None}


def backtest(db: Session) -> dict[str, Any]:
    """Each rule over the full record, in its own tiers, against the same trade on every report."""
    if _bt["body"] is not None and time.time() - _bt["at"] < 3600:
        return _bt["body"]
    from backend.app.services.playbook_service import _frame

    df = _frame(db).copy()
    df["yr"] = pd.to_datetime(df.earnings_date).dt.year
    out = {}
    for key, r in RULES.items():
        d = df[np.isfinite(df[r["leg"]]) & df.tier.isin(r["tiers"])].copy()
        sign = 1.0 if r["side"] == "LONG" else -1.0
        base = d.groupby("yr")[r["leg"]].transform("mean")
        sel = np.array([matches(key, g, s) for g, s in zip(d.gap_x, d.surprise.where(d.surprise.notna(), None))])
        s = d[sel].copy()
        s["ret"] = sign * s[r["leg"]] - COST
        s["excess"] = sign * (s[r["leg"]] - base[sel]) - COST
        s["mkt"] = base[sel]
        years = s.groupby("yr").agg(n=("ret", "size"), ret=("ret", "mean"), excess=("excess", "mean"))
        curve, total, mkt = [], 0.0, 0.0
        s = s.sort_values("earnings_date")
        for dt, x, m in zip(s.earnings_date, s.ret, s.mkt):
            total += STAKE * float(x)
            mkt += STAKE * sign * float(m)
            curve.append({"d": str(dt), "v": round(total), "m": round(mkt)})
        if len(curve) > 260:
            step = len(curve) // 260 + 1
            curve = curve[::step] + [curve[-1]]
        out[key] = {
            "side": r["side"], "entry": r["entry"], "hold": r["hold"], "tiers": list(r["tiers"]),
            "live_from": str(r["live_from"]),
            "all": _stats(s.ret.to_numpy()), "excess": _stats(s.excess.to_numpy()),
            "discovery": _stats(s[s.yr <= 2018].excess.to_numpy()),
            "holdout": _stats(s[s.yr >= 2019].excess.to_numpy()),
            "years_positive": int((years.excess > 0).sum()), "years_total": int(len(years)),
            "per_year": round(len(s) / max(1, d.yr.nunique())),
            "pnl": round(float(s.ret.sum() * STAKE)), "pnl_market": round(float((sign * s.mkt).sum() * STAKE)),
            "curve": curve,
            "span": [str(d.earnings_date.min()), str(d.earnings_date.max())],
        }
    _bt.update(at=time.time(), body=out)
    return out


# ───────────────────────────── issuing ─────────────────────────────

def _sessions_back(d: date) -> date:
    p = d - timedelta(days=1)
    while p.weekday() >= 5:
        p -= timedelta(days=1)
    return p


def candidates(db: Session, today: date) -> list[dict[str, Any]]:
    """Reports whose reaction session is `today`: BMO/DMH today, or AMC the session before."""
    return [dict(r) for r in db.execute(text("""
        SELECT e.ticker, e.earnings_date, e.report_time, u.tier
        FROM earnings_events e LEFT JOIN universe u ON u.ticker=e.ticker
        WHERE (e.earnings_date = :today AND e.report_time IN ('BMO', 'DMH'))
           OR (e.earnings_date = :prev AND e.report_time = 'AMC')"""),
        {"today": today, "prev": _sessions_back(today)}).mappings().all()]


def issue_due(db: Session, now: datetime | None = None, opens: dict[str, float] | None = None) -> dict[str, Any]:
    """Run after the open: every report trading today, its gap from the open, its calls.

    `opens` (ticker -> today's opening print, from the broker feed a minute after the bell)
    lets the calls go out at 9:31 instead of waiting ~15 minutes for Yahoo's daily bar.
    Tickers missing from it fall back to Yahoo as before."""
    from zoneinfo import ZoneInfo

    from backend.app.services.flat_band import load_flat_bands
    from backend.app.services.receipts_service import bars

    now_et = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    today = now_et.date()
    if today.weekday() >= 5 or (now_et.hour, now_et.minute) < ((9, 30) if opens else (9, 33)):
        return {"issued": 0, "why": "market not open"}
    rows = candidates(db, today)
    if not rows:
        return {"issued": 0, "candidates": 0}
    tickers = sorted({r["ticker"] for r in rows})
    px = bars(tickers, today - timedelta(days=10), ttl=60)
    bands = load_flat_bands(db, tickers)
    issued = 0
    for r in rows:
        t = r["ticker"]
        o, c = px["Open"].get(t), px["Close"].get(t)
        if c is None:
            continue
        c = c.dropna()
        ts = pd.Timestamp(today)
        if opens and opens.get(t):
            first = float(opens[t])
        elif o is not None and ts in o.dropna().index:
            first = float(o.dropna().loc[ts])
        else:
            continue  # no print yet today
        before = c[c.index < ts]
        if before.empty:
            continue
        gap = first / float(before.iloc[-1]) - 1
        band = bands.get(t)
        if not band:
            continue
        sur = db.execute(text("""SELECT surprise_pct FROM earnings_surprises
                                 WHERE ticker=:t AND report_date BETWEEN :a AND :b
                                 ORDER BY abs(report_date - :d) LIMIT 1"""),
                         {"t": t, "d": r["earnings_date"], "a": r["earnings_date"] - timedelta(days=3),
                          "b": r["earnings_date"] + timedelta(days=3)}).scalar()
        tier = "large" if (r["tier"] or "core") in ("core", "large") else r["tier"]
        for key, rule in RULES.items():
            if today < rule["live_from"] or tier not in rule["tiers"] or not matches(key, gap / band, _num(sur)):
                continue
            res = db.execute(text("""
                INSERT INTO direction_calls (rule, ticker, earnings_date, session, side, entry, hold, gap, band,
                                             gap_x, surprise, tier, origin)
                VALUES (:rule, :t, :d, :s, :side, :entry, :hold, :gap, :band, :gx, :sur, :tier, 'open')
                ON CONFLICT (rule, ticker, earnings_date) DO NOTHING"""),
                {"rule": key, "t": t, "d": r["earnings_date"], "s": today, "side": rule["side"],
                 "entry": rule["entry"], "hold": rule["hold"], "gap": gap, "band": band, "gx": gap / band,
                 "sur": _num(sur), "tier": tier})
            issued += res.rowcount
    db.commit()
    return {"issued": issued, "candidates": len(rows)}


def backfill_follow_gap(db: Session) -> int:
    """follow_gap was published on 2026-10-10; its triggers since then are mechanical
    and recorded with origin='rule' (derived from the reaction, not issued at the open)."""
    rows = db.execute(text("""
        SELECT o.ticker, o.earnings_date, COALESCE(o.reaction_date, o.earnings_date) AS s,
               o.actual_t1_gap_pct AS gap, o.flat_band AS band, u.tier
        FROM outcomes o LEFT JOIN universe u ON u.ticker=o.ticker
        WHERE COALESCE(o.reaction_date, o.earnings_date) >= :since
          AND o.flat_band > 0 AND o.actual_t1_gap_pct > 2 * o.flat_band"""),
        {"since": RULES["follow_gap"]["live_from"]}).mappings().all()
    n = 0
    for r in rows:
        tier = "large" if (r["tier"] or "core") in ("core", "large") else r["tier"]
        n += db.execute(text("""
            INSERT INTO direction_calls (rule, ticker, earnings_date, session, side, entry, hold, gap, band, gap_x, tier, origin)
            VALUES ('follow_gap', :t, :d, :s, 'LONG', 'close', 19, :g, :b, :gx, :tier, 'rule')
            ON CONFLICT (rule, ticker, earnings_date) DO NOTHING"""),
            {"t": r["ticker"], "d": r["earnings_date"], "s": r["s"], "g": float(r["gap"]), "b": float(r["band"]),
             "gx": float(r["gap"]) / float(r["band"]), "tier": tier}).rowcount
    db.commit()
    return n


# ───────────────────────────── marking ─────────────────────────────

def book(db: Session) -> dict[str, Any]:
    """Every call, marked to the latest bar; closed once its exit bar exists."""
    from backend.app.services.receipts_service import bars

    rows = [dict(r) for r in db.execute(text("""
        SELECT c.*, e.company_name FROM direction_calls c
        LEFT JOIN earnings_events e ON e.ticker=c.ticker AND e.earnings_date=c.earnings_date
        ORDER BY c.session DESC, c.rule, c.ticker""")).mappings().all()]
    calls: list[dict[str, Any]] = []
    if rows:
        start = min(r["session"] for r in rows) - timedelta(days=7)
        px = bars(sorted({r["ticker"] for r in rows} | {"SPY"}), start, ttl=300)
        O, C = px["Open"], px["Close"]
        for r in rows:
            t, s = r["ticker"], pd.Timestamp(r["session"])
            if t not in C or "SPY" not in C:
                continue
            o, c, so, sc = O[t].dropna(), C[t].dropna(), O["SPY"].dropna(), C["SPY"].dropna()
            if s not in c.index:
                calls.append({**_base(r), "status": "pending"})
                continue
            entry = float(o.loc[s]) if r["entry"] == "open" else float(c.loc[s])
            spy_entry = float(so.loc[s]) if r["entry"] == "open" and s in so.index else float(sc.loc[s]) if s in sc.index else None
            path = c[c.index >= s] if r["entry"] == "open" else c[c.index > s]
            need = r["hold"] + (1 if r["entry"] == "open" else 0)  # an open entry's own close counts
            held = path.iloc[:need]
            closed = len(path) >= need
            mark_day = held.index[-1] if len(held) else s
            mark = float(held.iloc[-1]) if len(held) else entry
            sign = 1 if r["side"] == "LONG" else -1
            ret = sign * (mark / entry - 1) - (COST if closed else 0)
            spy_mark = float(sc.loc[mark_day]) if mark_day in sc.index else None
            spy_ret = None if not spy_entry or spy_mark is None else sign * (spy_mark / spy_entry - 1)
            calls.append({**_base(r), "status": "closed" if closed else "open", "entry_price": entry,
                          "mark": mark, "mark_on": str(mark_day.date()), "sessions": int(len(held)),
                          "ret": ret, "spy_ret": spy_ret, "excess": None if spy_ret is None else ret - spy_ret,
                          "pnl": STAKE * ret})
    # Only closed calls count as right or wrong; open ones are reported as running P&L.
    done = [c for c in calls if c["status"] == "closed"]
    running = [c for c in calls if c["status"] == "open"]
    rets = np.array([c["ret"] for c in done])
    k = int((rets > 0).sum())
    by_rule = {}
    for key in RULES:
        x = np.array([c["ret"] for c in done if c["rule"] == key])
        by_rule[key] = {"n": len(x), "right": int((x > 0).sum()), "mean": float(x.mean()) if len(x) else None,
                        "pnl": float(STAKE * x.sum()) if len(x) else 0.0}
    return {
        "calls": calls,
        "summary": {"n": len(done), "right": k, "hit": k / len(done) if done else None,
                    "pnl": float(STAKE * rets.sum()) if len(rets) else 0.0,
                    "spy_pnl": float(STAKE * sum(c["spy_ret"] for c in done if c["spy_ret"] is not None)),
                    "open": sum(1 for c in calls if c["status"] in ("open", "pending")),
                    "open_pnl": float(sum(c["pnl"] for c in running)),
                    "open_right": sum(1 for c in running if c["ret"] > 0),
                    "by_rule": by_rule},
    }


def _base(r: dict) -> dict:
    return {"rule": r["rule"], "ticker": r["ticker"], "company": r.get("company_name"), "side": r["side"],
            "entry": r["entry"], "hold": r["hold"], "session": str(r["session"]),
            "earnings_date": str(r["earnings_date"]), "gap": _num(r["gap"]), "gap_x": _num(r["gap_x"]),
            "band": _num(r["band"]), "surprise": _num(r["surprise"]), "tier": r["tier"], "origin": r["origin"],
            "called_at": r["called_at"].isoformat() if r.get("called_at") else None}


_book: dict[str, Any] = {"at": 0.0, "body": None}


def direction(db: Session) -> dict[str, Any]:
    if _book["body"] is None or time.time() - _book["at"] > 120:
        _book.update(at=time.time(), body={"as_of": datetime.now(timezone.utc).isoformat(),
                                           "stake": STAKE, "rules": backtest(db), "book": book(db)})
    return _book["body"]
