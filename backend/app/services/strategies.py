"""Every strategy Autopilot can run, beyond the four direction rules — and where each comes from.

The catalog has three families, each tied to a desk of the site that produces its signal:

  earnings  (Calendar, Direction book, Brief)
      the four direction rules (direction_service; executed by autotrade_service as before)
      pre_run     buy five sessions before a scheduled report, hold through it, sell at the
                  reaction-session close (the earnings announcement premium; exiting before the
                  report did not beat an equal-weight pool of the same stocks)
      sue_gap     after a big EPS beat that also gapped up, buy at the reaction close, hold 60
  filings   (Oracle desk)
      insider_cluster  three or more officers/directors buying in the open market within 30
                       days: buy at the next open, hold 21 sessions
  market    (Markets desk)
      rsi2     SPY after a short, sharp dip in an uptrend (Connors RSI-2), back to T-bills on the rebound
      trend    SPY above its 10-month average, else T-bills (Faber)
      sectors  the three sector SPDRs with the best six months, monthly

Backtests live in data_pipeline/research_{equity,filings,etf}.py (json under $DATA_DIR); a rule
is offered only if it held up after publication / out of sample against the market and,
for single stocks, against an equal-weight portfolio of the same (survivor) universe.

Two kinds of execution:
  event   signals with an entry and exit session (strategy_signals); the account takes a
          free slot, sized equity x alloc / slots, exits on schedule — the same path as
          the direction calls (autotrade_service._place / run_closes / sweep_overdue).
  target  a set of weights decided at a rebalance (strategy_targets); the account's sleeve
          is moved to it at the close: tickers dropped are sold, tickers added are bought
          (sleeve x weight). Weights are not trimmed between rebalances.

Signal ids start at 1,000,000 so autotrade_orders.call_id can hold either a direction call
or a strategy signal.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

NY = ZoneInfo("America/New_York")
SEC_UA = {"User-Agent": os.getenv("SEC_USER_AGENT") or "Signalpha-research contact@signalpha.app"}

# key -> what the page and the executor need to know. `alloc` is the suggested share of the
# account; `on` is whether a new connection starts with it switched on.
SPECS: dict[str, dict[str, Any]] = {
    "fade_spike": {"family": "earnings", "kind": "direction", "side": "SHORT", "entry": "open", "slots": 5, "alloc": 25, "on": True,
                   "source": "SignAlpha", "desk": "/strategy"},
    "buy_flush": {"family": "earnings", "kind": "direction", "side": "LONG", "entry": "open", "slots": 5, "alloc": 25, "on": True,
                  "source": "SignAlpha", "desk": "/strategy"},
    "follow_gap": {"family": "earnings", "kind": "direction", "side": "LONG", "entry": "close", "slots": 10, "alloc": 15, "on": False,
                   "source": "Earnings-announcement-return drift — Brandt et al. (2008)", "desk": "/strategy"},
    "fade_miss": {"family": "earnings", "kind": "direction", "side": "SHORT", "entry": "open", "slots": 5, "alloc": 10, "on": False,
                  "source": "SignAlpha", "desk": "/strategy"},
    "pre_run": {"family": "earnings", "kind": "event", "side": "LONG", "entry": "close", "exit": "close", "slots": 30, "alloc": 20, "on": True,
                "hold": 6, "source": "Frazzini & Lamont (2007); Barber, De George, Lehavy & Trueman (2013)", "desk": "/",
                "research": ("research_equity.json", "pre_run_through")},
    "sue_gap": {"family": "earnings", "kind": "event", "side": "LONG", "entry": "close", "exit": "close", "slots": 20, "alloc": 15, "on": True,
                "hold": 60, "source": "Bernard & Thomas (1989); Chan, Jegadeesh & Lakonishok (1996)", "desk": "/brief",
                "research": ("research_equity.json", "sue_gap")},
    "insider_cluster": {"family": "filings", "kind": "event", "side": "LONG", "entry": "open", "exit": "close", "slots": 10, "alloc": 15,
                        "on": True, "hold": 21, "source": "Lakonishok & Lee (2001); Alldredge & Blank (2019)", "desk": "/oracle",
                        "research": ("research_filings.json", "insider_cluster")},
    "rsi2": {"family": "market", "kind": "target", "side": "LONG", "entry": "close", "slots": 2, "alloc": 20, "on": False,
             "source": "Connors & Alvarez (2008)", "desk": "/markets", "research": ("research_etf.json", "rsi2")},
    "trend": {"family": "market", "kind": "target", "side": "LONG", "entry": "close", "slots": 2, "alloc": 30, "on": False,
              "source": "Faber (2007)", "desk": "/markets", "research": ("research_etf.json", "trend")},
    "sectors": {"family": "market", "kind": "target", "side": "LONG", "entry": "close", "slots": 3, "alloc": 20, "on": False,
                "source": "Moskowitz & Grinblatt (1999); Faber (2010)", "desk": "/markets", "research": ("research_etf.json", "sectors")},
}
ORDER = list(SPECS)
SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
CASH = "BIL"

DDL = [
    "CREATE SEQUENCE IF NOT EXISTS strategy_signals_seq START 1000000",
    """CREATE TABLE IF NOT EXISTS strategy_signals (
        id BIGINT PRIMARY KEY DEFAULT nextval('strategy_signals_seq'), strategy TEXT NOT NULL, ticker TEXT NOT NULL,
        side TEXT NOT NULL, session DATE NOT NULL, entry_at TEXT NOT NULL, exit_session DATE, exit_at TEXT,
        rank REAL, ref TEXT UNIQUE NOT NULL, meta JSONB NOT NULL DEFAULT '{}'::jsonb,
        called_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    "CREATE INDEX IF NOT EXISTS idx_strategy_signals_session ON strategy_signals (session, strategy)",
    """CREATE TABLE IF NOT EXISTS strategy_targets (
        strategy TEXT NOT NULL, session DATE NOT NULL, weights JSONB NOT NULL, why TEXT,
        decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (strategy, session))""",
    """CREATE TABLE IF NOT EXISTS insider_trades (
        accession TEXT NOT NULL, owner_cik TEXT NOT NULL, ticker TEXT NOT NULL, filed DATE NOT NULL,
        traded DATE, shares REAL, price REAL, value REAL, relation TEXT,
        PRIMARY KEY (accession, owner_cik, traded, shares))""",
    "CREATE INDEX IF NOT EXISTS idx_insider_trades_ticker ON insider_trades (ticker, filed)",
]


def ensure(db: Session) -> None:
    for s in DDL:
        db.execute(text(s))
    db.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone(NY)


def sessions(start: date, end: date) -> list[date]:
    from backend.app.services.brokers import Borrowed

    return Borrowed().calendar(start, end)


def _emit(db: Session, strategy: str, ticker: str, side: str, session: date, entry_at: str, exit_session: date | None,
          exit_at: str | None, ref: str, rank: float | None = None, meta: dict | None = None) -> bool:
    n = db.execute(text("""
        INSERT INTO strategy_signals (strategy, ticker, side, session, entry_at, exit_session, exit_at, rank, ref, meta)
        VALUES (:s, :t, :side, :d, :ea, :x, :xa, :r, :ref, CAST(:m AS jsonb)) ON CONFLICT (ref) DO NOTHING"""),
        {"s": strategy, "t": ticker, "side": side, "d": session, "ea": entry_at, "x": exit_session, "xa": exit_at,
         "r": rank, "ref": ref, "m": json.dumps(meta or {})}).rowcount
    db.commit()
    return bool(n)


# ───────────────────────── generators: earnings ─────────────────────────

def gen_pre_run(db: Session, today: date | None = None) -> dict[str, Any]:
    """Reports whose last pre-announcement close is five sessions from today (large/mid caps):
    buy today's close, sell at the reaction session's close."""
    today = today or _now().date()
    cal = sessions(today - timedelta(days=5), today + timedelta(days=30))
    if today not in cal:
        return {"why": "not a session"}
    i = cal.index(today)
    if i + 6 >= len(cal):
        return {"why": "calendar too short"}
    d0 = cal[i + 5]
    react = cal[i + 6]
    # reaction session = d0's next session: BMO/DMH reports dated `react`, AMC reports dated d0
    rows = db.execute(text("""
        SELECT e.ticker, e.earnings_date, e.report_time, p.prob_move FROM earnings_events e
        JOIN universe u ON u.ticker=e.ticker AND u.tier IN ('core','large','mid')
        LEFT JOIN predictions p ON p.ticker=e.ticker AND p.earnings_date=e.earnings_date
        WHERE (e.earnings_date=:r AND e.report_time IN ('BMO','DMH')) OR (e.earnings_date=:d0 AND e.report_time='AMC')"""),
        {"r": react, "d0": d0}).mappings().all()
    n = 0
    for r in rows:
        n += _emit(db, "pre_run", r["ticker"], "LONG", today, "close", react, "close",
                   f"pre_run:{r['ticker']}:{r['earnings_date']}", rank=float(r["prob_move"] or 0),
                   meta={"earnings_date": str(r["earnings_date"]), "report_time": r["report_time"]})
    return {"reports": len(rows), "new": n, "exit": str(react)}


def gen_sue_gap(db: Session, today: date | None = None, opens: dict[str, float] | None = None) -> dict[str, Any]:
    """Today's reaction-session reports with an EPS surprise in the top tenth of the last 90 days
    of reports and an opening gap beyond the stock's usual move."""
    from backend.app.services.direction_service import candidates
    from backend.app.services.flat_band import load_flat_bands
    from backend.app.services.receipts_service import bars
    from backend.app.services.strategy_lab import opens_today

    today = today or _now().date()
    cands = candidates(db, today)
    if not cands:
        return {"candidates": 0}
    thr = db.execute(text("""SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY surprise_pct) FROM earnings_surprises
                             WHERE report_date BETWEEN :a AND :b AND surprise_pct IS NOT NULL AND eps_actual IS NOT NULL"""),
                     {"a": today - timedelta(days=90), "b": today - timedelta(days=1)}).scalar()
    if thr is None:
        return {"why": "no surprise history"}
    tick = [c["ticker"] for c in cands if c["tier"] in ("core", "large", "mid")]
    sur = {r["ticker"]: float(r["surprise_pct"]) for r in db.execute(text("""
        SELECT DISTINCT ON (ticker) ticker, surprise_pct FROM earnings_surprises
        WHERE ticker = ANY(:t) AND report_date BETWEEN :a AND :b AND eps_actual IS NOT NULL AND surprise_pct IS NOT NULL
        ORDER BY ticker, report_date DESC"""), {"t": tick, "a": today - timedelta(days=4), "b": today}).mappings()}
    big = [t for t in tick if sur.get(t, -1e9) >= float(thr)]
    if not big:
        return {"candidates": len(tick), "beats": 0, "threshold": float(thr)}
    opens = opens or opens_today(big, db)
    px = bars(big, today - timedelta(days=10))
    bands = load_flat_bands(db, big)
    cal = sessions(today, today + timedelta(days=120))
    exit_s = cal[60] if len(cal) > 60 else None
    n = 0
    for t in big:
        c = px["Close"].get(t)
        prev = c[c.index < pd.Timestamp(today)].dropna() if c is not None else None
        if prev is None or prev.empty or not opens.get(t) or not bands.get(t) or exit_s is None:
            continue
        gx = (opens[t] / float(prev.iloc[-1]) - 1) / bands[t]
        if gx > 1:
            n += _emit(db, "sue_gap", t, "LONG", today, "close", exit_s, "close", f"sue_gap:{t}:{today}",
                       rank=sur[t], meta={"surprise": sur[t], "gap_x": gx, "threshold": float(thr)})
    return {"candidates": len(tick), "beats": len(big), "new": n, "threshold": float(thr)}


# ───────────────────────── generators: filings ─────────────────────────

def _sec(url: str) -> str:
    for attempt in range(4):
        try:
            r = httpx.get(url, headers=SEC_UA, timeout=30)
        except httpx.HTTPError:
            time.sleep(2 + attempt * 2)
            continue
        time.sleep(0.13)
        if r.status_code == 200:
            return r.text
        if r.status_code in (403, 429):
            time.sleep(10)
            continue
        return ""
    return ""


def collect_form4(db: Session, day: date) -> dict[str, Any]:
    """Every Form 4 filed on `day` (EDGAR daily index): open-market purchases by officers and
    directors go into insider_trades."""
    q = (day.month - 1) // 3 + 1
    idx = _sec(f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/form.{day:%Y%m%d}.idx")
    files = [ln.split()[-1] for ln in idx.splitlines() if ln.startswith("4 ")]
    added = 0
    for path in files:
        raw = _sec("https://www.sec.gov/Archives/" + path)
        m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", raw, re.S)
        if not m:
            continue
        doc = m.group(0)
        g = lambda tag, s=doc: (re.search(f"<{tag}>\\s*(?:<value>)?\\s*([^<]*)", s) or [None, ""])[1].strip()  # noqa: E731
        ticker = g("issuerTradingSymbol").upper().replace(".", "-")
        rel = []
        if g("isDirector") in ("1", "true"):
            rel.append("Director")
        if g("isOfficer") in ("1", "true"):
            rel.append("Officer")
        if not ticker or not rel:
            continue
        owner = g("rptOwnerCik")
        acc = path.rsplit("/", 1)[-1].replace(".txt", "")
        for tx in re.findall(r"<nonDerivativeTransaction>.*?</nonDerivativeTransaction>", doc, re.S):
            if g("transactionCode", tx) != "P" or g("transactionAcquiredDisposedCode", tx) != "A":
                continue
            try:
                sh, pr = float(g("transactionShares", tx) or 0), float(g("transactionPricePerShare", tx) or 0)
                traded = date.fromisoformat(g("transactionDate", tx)[:10])
            except ValueError:
                continue
            added += db.execute(text("""
                INSERT INTO insider_trades (accession, owner_cik, ticker, filed, traded, shares, price, value, relation)
                VALUES (:a, :o, :t, :f, :d, :s, :p, :v, :r) ON CONFLICT DO NOTHING"""),
                {"a": acc, "o": owner, "t": ticker, "f": day, "d": traded, "s": sh, "p": pr, "v": sh * pr,
                 "r": "/".join(rel)}).rowcount
    db.commit()
    return {"form4": len(files), "purchases": added}


def gen_insider(db: Session, today: date | None = None) -> dict[str, Any]:
    """Yesterday's filings (EDGAR dates them by session); a third distinct insider buying within 30
    days makes a signal for today's open. One per company per 60 days."""
    today = today or _now().date()
    cal = sessions(today - timedelta(days=10), today + timedelta(days=45))
    if today not in cal:
        return {"why": "not a session"}
    i = cal.index(today)
    filed = cal[i - 1]
    got = collect_form4(db, filed)
    exit_s = cal[i + 20] if i + 20 < len(cal) else None
    rows = db.execute(text("""
        SELECT t.ticker, count(DISTINCT t.owner_cik) n, sum(t.value) v FROM insider_trades t
        JOIN universe u ON u.ticker=t.ticker AND u.tier IN ('core','large','mid','small')
        WHERE t.filed <= :f AND t.traded >= :f - 30 AND t.value >= 10000
          AND t.ticker IN (SELECT ticker FROM insider_trades WHERE filed=:f)
        GROUP BY t.ticker HAVING count(DISTINCT t.owner_cik) >= 3"""), {"f": filed}).mappings().all()
    n = 0
    for r in rows:
        recent = db.execute(text("""SELECT 1 FROM strategy_signals WHERE strategy='insider_cluster' AND ticker=:t
                                    AND session > :d - 60"""), {"t": r["ticker"], "d": today}).first()
        if recent or exit_s is None:
            continue
        n += _emit(db, "insider_cluster", r["ticker"], "LONG", today, "open", exit_s, "close",
                   f"insider:{r['ticker']}:{filed}", rank=float(r["v"] or 0),
                   meta={"insiders": int(r["n"]), "value": float(r["v"] or 0), "filed": str(filed)})
    return {**got, "clusters": len(rows), "new": n}


# ───────────────────────── generators: market targets ─────────────────────────

def _closes(tickers: list[str], days: int = 420) -> pd.DataFrame:
    """Adjusted daily closes, with today's latest trade appended as today's close."""
    from data_pipeline.research_common import alpaca_daily
    from backend.app.services.strategy_lab import snapshots

    today = _now().date()
    _, C = alpaca_daily(tickers, (today - timedelta(days=days)).isoformat())
    snap = snapshots(tickers)
    last = {t: float((snap.get(t) or {}).get("latestTrade", {}).get("p") or 0) for t in tickers}
    ts = pd.Timestamp(today)
    if all(last.values()):
        C.loc[ts, list(last)] = list(last.values())
    return C.sort_index()


def gen_targets(db: Session, today: date | None = None) -> dict[str, Any]:
    """At 15:35 ET: today's weights for rsi2 (daily), trend and sectors (last session of the month)."""
    from data_pipeline.research_etf import rsi

    today = today or _now().date()
    cal = sessions(today - timedelta(days=5), today + timedelta(days=10))
    if today not in cal:
        return {"why": "not a session"}
    nxt = cal[cal.index(today) + 1]
    month_end = nxt.month != today.month
    C = _closes(["SPY", CASH] + SECTORS)
    spy = C.SPY.dropna()
    out = {}
    held = db.execute(text("""SELECT weights FROM strategy_targets WHERE strategy='rsi2' AND session < :d
                              ORDER BY session DESC LIMIT 1"""), {"d": today}).scalar()
    in_spy = bool(held and (held if isinstance(held, dict) else json.loads(held)).get("SPY"))
    r2, s200, s5 = rsi(spy).iloc[-1], spy.rolling(200).mean().iloc[-1], spy.rolling(5).mean().iloc[-1]
    # `why` is stored as {"code", ...values} so the page can say it in either language.
    if not in_spy and r2 < 10 and spy.iloc[-1] > s200:
        w, why = {"SPY": 1.0}, {"code": "rsi2_buy", "r": round(float(r2), 1)}
    elif in_spy and spy.iloc[-1] > s5:
        w, why = {CASH: 1.0}, {"code": "rsi2_exit", "r": round(float(r2), 1)}
    else:
        w, why = ({"SPY": 1.0} if in_spy else {CASH: 1.0}), {"code": "rsi2_hold_in" if in_spy else "rsi2_hold_out", "r": round(float(r2), 1)}
    out["rsi2"] = (w, why)
    if month_end:
        me = spy.groupby([spy.index.year, spy.index.month]).tail(1)
        sma = me.rolling(10).mean().iloc[-1]
        up = spy.iloc[-1] > sma
        out["trend"] = ({"SPY": 1.0} if up else {CASH: 1.0},
                        {"code": "trend_in" if up else "trend_out", "spy": round(float(spy.iloc[-1]), 2), "sma": round(float(sma), 2)})
        m6 = (C[SECTORS].iloc[-1] / C[SECTORS].iloc[-127] - 1).dropna().sort_values(ascending=False)
        out["sectors"] = ({t: 1 / 3 for t in m6.index[:3]},
                          {"code": "sectors", "top": ", ".join(f"{t} {v*100:+.1f}%" for t, v in m6.head(3).items())})
    for k, (w, why) in out.items():
        db.execute(text("""INSERT INTO strategy_targets (strategy, session, weights, why) VALUES (:s, :d, CAST(:w AS jsonb), :y)
                           ON CONFLICT (strategy, session) DO UPDATE SET weights=EXCLUDED.weights, why=EXCLUDED.why, decided_at=NOW()"""),
                   {"s": k, "d": today, "w": json.dumps(w), "y": json.dumps(why)})
    db.commit()
    return {k: v[1] for k, v in out.items()}


# ───────────────────────── execution hooks (called from autotrade_service) ─────────────────────────

def signals_for(db: Session, today: date, entry_at: str) -> list:
    return list(db.execute(text("""SELECT id, strategy AS rule, ticker, side, session, exit_session, rank, meta
                                   FROM strategy_signals WHERE session=:d AND entry_at=:e
                                   ORDER BY strategy, rank DESC NULLS LAST, id"""), {"d": today, "e": entry_at}).mappings())


def targets_for(db: Session, today: date) -> dict[str, dict[str, float]]:
    out = {}
    for r in db.execute(text("SELECT strategy, weights FROM strategy_targets WHERE session=:d"), {"d": today}).mappings():
        out[r["strategy"]] = r["weights"] if isinstance(r["weights"], dict) else json.loads(r["weights"])
    return out


def target_signal(db: Session, strategy: str, ticker: str, today: date) -> dict:
    ref = f"{strategy}:{ticker}:{today}"
    _emit(db, strategy, ticker, "LONG", today, "close", None, None, ref)
    r = db.execute(text("SELECT id, strategy AS rule, ticker, side, session, exit_session FROM strategy_signals WHERE ref=:r"),
                   {"r": ref}).mappings().first()
    return dict(r)


# ───────────────────────── catalog (page) ─────────────────────────

def _research(name: str) -> dict | None:
    from pathlib import Path

    p = Path(os.getenv("DATA_DIR", "/app/data")) / name
    return json.loads(p.read_text()) if p.exists() else None


def card(key: str) -> dict[str, Any] | None:
    """The page's card for a non-direction strategy, in the same shape as strategy_lab.catalog."""
    spec = SPECS[key]
    f, k = spec["research"]
    full = _research(f) or {}
    body = full.get("rules", {}).get(k)
    if not body:
        return None
    ew_all = full.get("ew_universe") or {}
    a = body.get("all") or {}
    post = body.get("post") or {}
    ex = body.get("excess") or {}
    ew = body.get("excess_ew") or {}
    stats = {"cagr": a.get("cagr"), "spy_cagr": a.get("spy_cagr"), "max_dd": a.get("max_dd"), "spy_max_dd": a.get("spy_max_dd"),
             "sharpe": a.get("sharpe"), "spy_sharpe": a.get("spy_sharpe"), "years_up": a.get("years_up"),
             "years_total": a.get("years_total"), "years": a.get("years") or [], "span": [a.get("start"), a.get("end")],
             "trades": body.get("taken") or body.get("trades"), "signals": body.get("signals"),
             "hit": (body.get("per_trade") or {}).get("hit"), "avg": (body.get("per_trade") or {}).get("mean"),
             "excess": ex.get("mean"), "excess_t": ex.get("t"), "excess_ew": ew.get("mean"), "excess_ew_t": ew.get("t"),
             "post_cagr": post.get("cagr"), "post_spy_cagr": post.get("spy_cagr"), "published": body.get("published"),
             "ew_cagr": ew_all.get("cagr")}
    return {"key": key, "family": spec["family"], "kind": spec["kind"], "side": spec["side"], "entry": spec["entry"],
            "hold": spec.get("hold"), "slots": spec["slots"], "alloc": spec["alloc"], "on": spec["on"],
            "source": spec["source"], "desk": spec["desk"],
            "backtest": {"stats": stats, "series": body.get("series") or [], "bench": body.get("bench") or [],
                         "now": body.get("now")},
            "live": live(key)}


def live(key: str) -> dict[str, Any]:
    """Signals since the strategy went live, entered and exited at official prices (latest bar for open ones)."""
    from backend.app.db.session import SessionLocal

    with SessionLocal() as db:
        rows = [dict(r) for r in db.execute(text("""SELECT id, ticker, side, session, entry_at, exit_session, exit_at, meta
                                                    FROM strategy_signals WHERE strategy=:s AND exit_session IS NOT NULL
                                                    ORDER BY session DESC LIMIT 60"""), {"s": key}).mappings()]
        tgt = [dict(r) for r in db.execute(text("""SELECT session, weights, why FROM strategy_targets WHERE strategy=:s
                                                   ORDER BY session DESC LIMIT 1"""), {"s": key}).mappings()]
    out: dict[str, Any] = {"n": len(rows), "calls": [], "target": None}
    if tgt:
        t = tgt[0]
        out["target"] = {"session": str(t["session"]), "weights": t["weights"] if isinstance(t["weights"], dict) else json.loads(t["weights"]),
                         "why": t["why"]}
    if rows:
        from backend.app.services.receipts_service import bars

        px = bars(sorted({r["ticker"] for r in rows}), min(r["session"] for r in rows) - timedelta(days=5))
        today = _now().date()
        for r in rows:
            o, c = px["Open"].get(r["ticker"]), px["Close"].get(r["ticker"])
            if c is None:
                continue
            ts = pd.Timestamp(r["session"])
            entry = None
            if r["entry_at"] == "open" and o is not None and ts in o.index:
                entry = float(o.loc[ts])
            elif ts in c.index:
                entry = float(c.loc[ts])
            if not entry or not math.isfinite(entry):
                out["calls"].append({"ticker": r["ticker"], "session": str(r["session"]), "status": "pending"})
                continue
            closed = r["exit_session"] <= today and pd.Timestamp(r["exit_session"]) in c.index
            mark = float(c.loc[pd.Timestamp(r["exit_session"])]) if closed else float(c.dropna().iloc[-1])
            sign = 1 if r["side"] == "LONG" else -1
            out["calls"].append({"ticker": r["ticker"], "session": str(r["session"]), "exit_session": str(r["exit_session"]),
                                 "status": "closed" if closed else "open", "entry_price": entry, "mark": mark,
                                 "ret": sign * (mark / entry - 1), "meta": r["meta"]})
    done = [c for c in out["calls"] if c.get("status") == "closed"]
    out["closed"], out["right"] = len(done), sum(1 for c in done if c["ret"] > 0)
    out["mean"] = float(np.mean([c["ret"] for c in done])) if done else None
    return out


def catalog() -> list[dict[str, Any]]:
    return [c for c in (card(k) for k in ORDER if SPECS[k]["kind"] != "direction") if c]
