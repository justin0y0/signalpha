"""Does the breakout model make money in options? Earnings straddles priced from real trades.

The breakout model (predictions.prob_move, walk-forward, out of sample) is the one ML
output with a proven edge: it ranks which reports will move beyond their usual range.
A move is only worth money if it beats what the options already price in, so this buys
the at-the-money straddle at the close before each report and sells it on the reaction
session, on Alpaca's historical option trades (OPRA, available from February 2024).

Per report (2024-02-20 onwards, large and mid caps — small-cap chains rarely trade):
  entry session E = the session before the reaction session R
  spot            = SIP close of the stock on E
  contracts       = call + put at the listed strike nearest spot, first expiry on or
                    after R that traded on E (weekly or monthly); OCC symbols are built
                    from candidate strikes rather than looked up one by one
  entry           = both legs' E close (last trade), only if each leg traded >= 20 times
  exits           = R open (first trade), R VWAP, R close
  implied move    = straddle / spot;  realised = |R close / E close - 1|
Returns are per dollar of premium, before costs; the summary also applies a round-trip
cost of 5% (and 10%) of the entry premium for the bid-ask on both legs.

    python -m data_pipeline.research_straddles     # writes $DATA_DIR/research_straddles.json
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from backend.app.services.strategy_lab import data_headers, from_alpaca, to_alpaca

NY = ZoneInfo("America/New_York")
SINCE = date(2024, 2, 20)
OUT = Path(os.getenv("DATA_DIR", "/app/data")) / "research_straddles.json"
H: dict[str, str] = {}


def _get(url: str, params: dict) -> dict:
    for attempt in range(6):
        try:
            r = httpx.get(url, headers=H, params=params, timeout=40)
        except httpx.HTTPError:
            time.sleep(3 + attempt * 3)
            continue
        if r.status_code == 429:
            time.sleep(15)
            continue
        time.sleep(0.31)
        if r.status_code != 200:
            print("http", r.status_code, r.text[:140], flush=True)
            return {}
        return r.json()
    return {}


def stock_daily(symbols: list[str], end: date) -> dict[str, pd.DataFrame]:
    out: dict[str, list] = {}
    for i in range(0, len(symbols), 100):
        token = None
        while True:
            p = {"symbols": ",".join(to_alpaca(s) for s in symbols[i:i + 100]), "timeframe": "1Day", "feed": "sip",
                 "adjustment": "raw", "start": "2024-01-15", "end": end.isoformat(), "limit": 10000}
            if token:
                p["page_token"] = token
            body = _get("https://data.alpaca.markets/v2/stocks/bars", p)
            for sym, rows in (body.get("bars") or {}).items():
                out.setdefault(from_alpaca(sym), []).extend(rows)
            token = body.get("next_page_token")
            if not token:
                break
        print(f"stock bars {min(i + 100, len(symbols))}/{len(symbols)}", flush=True)
    frames = {}
    for sym, rows in out.items():
        f = pd.DataFrame(rows)
        f.index = pd.to_datetime(f.t, utc=True).dt.tz_convert(NY).dt.tz_localize(None).dt.normalize()
        frames[sym] = f[~f.index.duplicated()][["o", "c"]].astype(float)
    return frames


def fridays(r: date) -> list[date]:
    """First weekly Friday on/after R, and the first monthly (third Friday) on/after R."""
    wk = r + timedelta(days=(4 - r.weekday()) % 7)
    out = [wk]
    for m in range(2):
        y, mo = (r.year, r.month + m) if r.month + m <= 12 else (r.year + 1, r.month + m - 12)
        first = date(y, mo, 1)
        third = first + timedelta(days=(4 - first.weekday()) % 7 + 14)
        if third >= r:
            out.append(third)
            break
    return sorted(set(out))


def strikes(spot: float) -> list[float]:
    """The strike nearest spot under each spacing a chain of this price is likely to use."""
    incs = [0.5, 1.0] if spot < 25 else [1.0, 2.5, 5.0] if spot < 200 else [2.5, 5.0, 10.0]
    return sorted({round(round(spot / inc) * inc, 2) for inc in incs if round(spot / inc) * inc > 0})


def occ(root: str, exp: date, kind: str, strike: float) -> str:
    return f"{root}{exp:%y%m%d}{kind}{int(round(strike * 1000)):08d}"


def main() -> None:
    global H
    with SessionLocal() as db:
        H = data_headers(db) or {}
        ev = pd.read_sql(text("""
            SELECT p.ticker, p.earnings_date, p.prob_move, o.reaction_date, o.actual_t1_close_return AS t1,
                   o.flat_band AS band, e.report_time,
                   CASE WHEN u.tier IS NULL OR u.tier IN ('core','large') THEN 'large' ELSE u.tier END AS tier
            FROM predictions p
            JOIN outcomes o ON o.ticker=p.ticker AND o.earnings_date=p.earnings_date
            JOIN earnings_events e ON e.ticker=p.ticker AND e.earnings_date=p.earnings_date
            LEFT JOIN universe u ON u.ticker=p.ticker
            WHERE p.is_out_of_sample AND p.prob_move IS NOT NULL AND p.earnings_date >= :s
              AND o.reaction_date IS NOT NULL AND o.reaction_date <= CURRENT_DATE - 3
              AND (u.tier IS NULL OR u.tier IN ('core', 'large', 'mid'))"""), db.bind, params={"s": SINCE})
    ev["reaction_date"] = pd.to_datetime(ev.reaction_date)
    syms = sorted(ev.ticker.unique())
    print(f"{len(ev)} reports, {len(syms)} stocks", flush=True)
    px = stock_daily(syms, date.today() - timedelta(days=1))

    rows = []
    for x in ev.itertuples():
        f = px.get(x.ticker)
        if f is None or x.reaction_date not in f.index:
            continue
        k = f.index.get_loc(x.reaction_date)
        if k == 0:
            continue
        e_day, r_day = f.index[k - 1], x.reaction_date
        spot = float(f.c.iloc[k - 1])
        if spot < 5:
            continue
        rows.append({"ticker": x.ticker, "earnings_date": str(x.earnings_date), "e": e_day.date(), "r": r_day.date(),
                     "spot": spot, "r_close": float(f.c.iloc[k]), "prob_move": float(x.prob_move),
                     "band": float(x.band) if x.band and not math.isnan(x.band) else None, "tier": x.tier})
    ev2 = pd.DataFrame(rows)
    print(f"{len(ev2)} with stock prices; building option symbols", flush=True)

    cand: dict[tuple, list[str]] = {}
    for x in ev2.itertuples():
        root = x.ticker.replace("-", "").replace(".", "")
        if len(root) > 5 or x.spot >= 99_000:
            continue
        cand[(x.ticker, x.e)] = [occ(root, ex, kd, st) for ex in fridays(x.r) for st in strikes(x.spot) for kd in "CP"]
    by_e: dict[date, list[str]] = {}
    for (t, e), lst in cand.items():
        by_e.setdefault(e, []).extend(lst)
    obar: dict[str, dict[date, dict]] = {}
    days = sorted(by_e)
    for n, e in enumerate(days):
        lst = sorted(set(by_e[e]))
        r_end = e + timedelta(days=6)
        for i in range(0, len(lst), 100):
            token = None
            while True:
                p = {"symbols": ",".join(lst[i:i + 100]), "timeframe": "1Day", "start": e.isoformat(),
                     "end": r_end.isoformat(), "limit": 10000}
                if token:
                    p["page_token"] = token
                body = _get("https://data.alpaca.markets/v1beta1/options/bars", p)
                for sym, bl in (body.get("bars") or {}).items():
                    d = obar.setdefault(sym, {})
                    for b in bl:
                        d[pd.Timestamp(b["t"]).tz_convert(NY).date()] = b
                token = body.get("next_page_token")
                if not token:
                    break
        if n % 25 == 0:
            print(f"option bars {n}/{len(days)} sessions, {len(obar)} contracts", flush=True)

    out_rows = []
    for x in ev2.itertuples():
        root = x.ticker.replace("-", "").replace(".", "")
        best = None
        for ex in fridays(x.r):
            for st in sorted(strikes(x.spot), key=lambda s: abs(s - x.spot)):
                c, p = obar.get(occ(root, ex, "C", st), {}), obar.get(occ(root, ex, "P", st), {})
                ce, pe, cr, pr = c.get(x.e), p.get(x.e), c.get(x.r), p.get(x.r)
                if not (ce and pe and cr and pr) or ce["n"] < 20 or pe["n"] < 20:
                    continue
                best = (ex, st, ce, pe, cr, pr)
                break
            if best:
                break
        if not best:
            continue
        ex, st, ce, pe, cr, pr = best
        entry = ce["c"] + pe["c"]
        if entry <= 0:
            continue
        out_rows.append({
            "ticker": x.ticker, "earnings_date": x.earnings_date, "e": str(x.e), "r": str(x.r), "tier": x.tier,
            "expiry": str(ex), "strike": st, "spot": x.spot, "prob_move": x.prob_move, "band": x.band,
            "implied": entry / x.spot, "realised": abs(x.r_close / x.spot - 1),
            "ret_open": (cr["o"] + pr["o"]) / entry - 1, "ret_vwap": (cr["vw"] + pr["vw"]) / entry - 1,
            "ret_close": (cr["c"] + pr["c"]) / entry - 1, "vol_e": int(ce["v"] + pe["v"]),
        })
    t = pd.DataFrame(out_rows)
    print(f"{len(t)} straddles priced", flush=True)

    def st_(r: pd.Series) -> dict:
        r = r.dropna()
        n = len(r)
        if n < 3:
            return {"n": n}
        return {"n": n, "mean": float(r.mean()), "median": float(r.median()), "hit": float((r > 0).mean()),
                "t": float(r.mean() / r.std() * math.sqrt(n))}
    t["dec"] = pd.qcut(t.prob_move.rank(method="first"), 10, labels=False) + 1
    t["cheap"] = t.implied / t.band
    summary = {"n": len(t), "by_decile": {}, "by_cheap": {}, "top_cheap": {}}
    for d, g in t.groupby("dec"):
        summary["by_decile"][int(d)] = {"prob_move": [float(g.prob_move.min()), float(g.prob_move.max())],
                                        "implied": float(g.implied.median()), "realised": float(g.realised.median()),
                                        "beat": float((g.realised > g.implied).mean()),
                                        "open": st_(g.ret_open), "vwap": st_(g.ret_vwap), "close": st_(g.ret_close)}
    t["cq"] = pd.qcut(t.cheap.rank(method="first"), 5, labels=False) + 1
    for q, g in t.groupby("cq"):
        summary["by_cheap"][int(q)] = {"ratio": [float(g.cheap.min()), float(g.cheap.max())], "open": st_(g.ret_open)}
    top = t[t.dec >= 9]
    for q, g in top.groupby("cq"):
        summary["top_cheap"][int(q)] = {"n": len(g), "open": st_(g.ret_open), "close": st_(g.ret_close)}
    OUT.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "since": str(SINCE),
                               "summary": summary, "rows": t.drop(columns=["dec", "cq"]).to_dict("records")}, default=str))
    print(json.dumps(summary, default=str), flush=True)
    print("STRADDLE_DONE", OUT, flush=True)


if __name__ == "__main__":
    main()
