"""Backtest the Pulse desk's two intraday engines on the consolidated tape.

Pulse (services/market_pulse_service.py) has signalled live since 2026-10-05 on ~100
mega-caps from 5-minute bars:

* AL_REVERSION — Avellaneda-Lee: each stock's 5-min returns regressed on SPY + its sector
  ETF over the last 60 bars, residual fitted as an OU process; |s| >= 1.25 with a
  half-life under 30 bars opens against the residual. Exit by triple barrier: take
  profit / stop at 1.0 x sigma_bar x sqrt(12), or after 12 bars (one hour).
* GAO_MOMENTUM — Gao-Han-Li-Zhou (2018): the first half-hour's return (>= 0.1% in size)
  sets the side of a trade held into the close; entered at 15:00 (as Pulse allows) and,
  as in the paper, at 15:30.

Here the same rules run on Alpaca SIP 5-minute bars from 2025-01-02, one position per
stock at a time, entered at the NEXT bar's open (a signal is known only at a bar's
close), 2 bp a side. Output: $DATA_DIR/research_pulse.json.

    python -m data_pipeline.research_pulse
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd

from backend.app.db.session import SessionLocal
from backend.app.services.avellaneda_lee import SECTOR_ETF, compute_s_score
from backend.app.services.market_pulse_service import MAX_BARS, SECTORS, S_OPEN
from backend.app.services.strategy_lab import data_headers, from_alpaca, to_alpaca

NY = ZoneInfo("America/New_York")
START = "2025-01-02"
COST = 0.0002  # a side
OUT = Path(os.getenv("DATA_DIR", "/app/data")) / "research_pulse.json"
H: dict[str, str] = {}


def _get(params: dict) -> dict:
    for attempt in range(6):
        try:
            r = httpx.get("https://data.alpaca.markets/v2/stocks/bars", headers=H, params=params, timeout=40)
        except httpx.HTTPError:
            time.sleep(3 + attempt * 3)
            continue
        if r.status_code == 429:
            time.sleep(15)
            continue
        time.sleep(0.32)
        return r.json() if r.status_code == 200 else {}
    return {}


def bars(symbols: list[str], end: str) -> dict[str, pd.DataFrame]:
    out: dict[str, list] = {}
    for i in range(0, len(symbols), 20):
        token = None
        while True:
            p = {"symbols": ",".join(to_alpaca(s) for s in symbols[i:i + 20]), "timeframe": "5Min", "feed": "sip",
                 "adjustment": "split", "start": START, "end": end, "limit": 10000}
            if token:
                p["page_token"] = token
            body = _get(p)
            for sym, rows in (body.get("bars") or {}).items():
                out.setdefault(from_alpaca(sym), []).extend(rows)
            token = body.get("next_page_token")
            if not token:
                break
        print(f"bars {min(i + 20, len(symbols))}/{len(symbols)}", flush=True)
    frames = {}
    for sym, rows in out.items():
        f = pd.DataFrame(rows)
        f.index = pd.to_datetime(f.t, utc=True).dt.tz_convert(NY)
        mins = f.index.hour * 60 + f.index.minute
        f = f[(mins >= 570) & (mins < 960)][["o", "h", "l", "c"]].astype(float)
        frames[sym] = f[~f.index.duplicated()]
    return frames


def stats(r: pd.Series) -> dict:
    r = r.dropna()
    n = len(r)
    if n < 3:
        return {"n": n}
    return {"n": n, "mean": float(r.mean()), "hit": float((r > 0).mean()), "t": float(r.mean() / r.std() * np.sqrt(n)),
            "median": float(r.median())}


def al_trades(sym: str, f: pd.DataFrame, fac: pd.DataFrame) -> list[dict]:
    ret = f.c.pct_change()
    al = pd.concat([ret, fac], axis=1, join="inner").dropna()
    al.columns = ["stock", "spy", "sec"]
    idx = f.index
    pos_of = {ts: k for k, ts in enumerate(idx)}
    trades, busy_until = [], None
    sig = ret.rolling(60).std()
    for j in range(60, len(al) - 1):
        ts = al.index[j]
        if busy_until is not None and ts <= busy_until:
            continue
        m = ts.hour * 60 + ts.minute
        if m < 600 or m > 900:  # 10:00-15:00 as Pulse's live window
            continue
        s = compute_s_score(al.stock.iloc[j - 64:j + 1], al[["spy", "sec"]].iloc[j - 64:j + 1], lookback=60)
        if not s or abs(s["s_score"]) < S_OPEN or s["half_life_bars"] >= MAX_BARS * 2.5:
            continue
        k = pos_of.get(ts)
        if k is None or k + 1 >= len(idx) or idx[k + 1].date() != ts.date():
            continue
        side = -1 if s["s_score"] > 0 else 1
        p0 = f.o.iloc[k + 1]
        b = 1.0 * float(sig.loc[ts]) * np.sqrt(MAX_BARS)
        exit_px, exit_ts, why = None, None, "time"
        for q in range(k + 1, min(k + 1 + MAX_BARS, len(idx))):
            if idx[q].date() != ts.date():
                break
            hi, lo = f.h.iloc[q], f.l.iloc[q]
            stop = p0 * (1 - side * b)
            take = p0 * (1 + side * b)
            hit_stop = lo <= stop if side > 0 else hi >= stop
            hit_take = hi >= take if side > 0 else lo <= take
            if hit_stop:  # both in one bar: assume the stop came first
                exit_px, exit_ts, why = stop, idx[q], "stop"
                break
            if hit_take:
                exit_px, exit_ts, why = take, idx[q], "take"
                break
            exit_px, exit_ts = f.c.iloc[q], idx[q]
        if exit_px is None:
            continue
        trades.append({"sym": sym, "t": ts.isoformat(), "day": str(ts.date()), "side": side, "s": s["s_score"],
                       "ret": side * (exit_px / p0 - 1) - 2 * COST, "why": why})
        busy_until = exit_ts
    return trades


def gao_trades(sym: str, f: pd.DataFrame, entry_min: int) -> list[dict]:
    out = []
    for day, g in f.groupby(f.index.date):
        mins = g.index.hour * 60 + g.index.minute
        first = g[mins < 600]
        if len(first) < 6:
            continue
        r1 = first.c.iloc[-1] / first.o.iloc[0] - 1
        if abs(r1) < 0.001:
            continue
        leg = g[mins >= entry_min]
        if len(leg) < 2:
            continue
        side = 1 if r1 > 0 else -1
        out.append({"sym": sym, "day": str(day), "side": side, "r1": float(r1),
                    "ret": side * (leg.c.iloc[-1] / leg.o.iloc[0] - 1) - 2 * COST})
    return out


def daily_curve(trades: pd.DataFrame, slots: int) -> list[tuple[str, float]]:
    """Equal slices of capital per trade (1/slots), P&L summed per day, compounded."""
    if trades.empty:
        return []
    d = trades.groupby("day").ret.sum() / slots
    eq = (1 + d).cumprod()
    return [(k, round((v - 1) * 100, 4)) for k, v in eq.items()]


def main() -> None:
    global H
    with SessionLocal() as db:
        H = data_headers(db) or {}
    names = sorted(SECTORS)
    etfs = sorted(set(SECTOR_ETF.values()) | {"SPY"})
    end = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=20)).isoformat()
    f = bars(names + etfs, end)
    spy = f["SPY"].c.pct_change()
    al_all, g15, g1530 = [], [], []
    for n, sym in enumerate(names):
        if sym not in f:
            continue
        etf = SECTOR_ETF.get(SECTORS.get(sym, "Technology"), "XLK")
        if etf not in f:
            continue
        fac = pd.concat([spy, f[etf].c.pct_change()], axis=1)
        fac.columns = ["spy", "sec"]
        al_all += al_trades(sym, f[sym], fac)
        g15 += gao_trades(sym, f[sym], 900)
        g1530 += gao_trades(sym, f[sym], 930)
        if n % 10 == 0:
            print(f"signals {n}/{len(names)} al={len(al_all)}", flush=True)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "start": START, "cost_side": COST, "symbols": len(names)}
    for key, rows, slots in (("al_reversion", al_all, 10), ("gao_1500", g15, 20), ("gao_1530", g1530, 20)):
        t = pd.DataFrame(rows)
        if t.empty:
            out[key] = {"all": {"n": 0}}
            continue
        t["yr"] = t.day.str[:4]
        body = {"all": stats(t.ret), "gross": stats(t.ret + 2 * COST),
                "by_year": {y: stats(g.ret) for y, g in t.groupby("yr")},
                "by_side": {str(s): stats(g.ret) for s, g in t.groupby("side")},
                "curve": daily_curve(t, slots), "slots": slots}
        if "why" in t:
            body["exits"] = t.why.value_counts().to_dict()
        out[key] = body
        print(key, json.dumps({k: v for k, v in body.items() if k not in ("curve",)}), flush=True)
    OUT.write_text(json.dumps(out))
    print("PULSE_DONE", OUT, flush=True)


if __name__ == "__main__":
    main()
