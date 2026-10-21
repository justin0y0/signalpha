"""Shared pieces of the strategy research scripts (research_etf / research_equity / research_filings).

Every candidate strategy is judged the same way, so the page can show them side by side:

* a daily return series of the sleeve (cash, when out of the market, earns T-bills only
  where the rule itself parks money in a T-bill ETF — event sleeves earn nothing idle);
* costs taken on every trade, stated per strategy;
* the whole sample and the part after the rule was published — a published anomaly that
  only worked before anyone wrote it down is not something to sell;
* against SPY with dividends over exactly the same days.

`summary()` turns a return series into the numbers the page shows; `event_sleeve()` runs
a list of trades through N equal slots and marks them to market every session.
"""
from __future__ import annotations

import math
import os
import time
from typing import Any, Iterable

import httpx
import numpy as np
import pandas as pd

NY = "America/New_York"


def summary(r: pd.Series, bench: pd.Series | None = None, since: str | None = None) -> dict[str, Any]:
    """Daily returns -> CAGR, vol, Sharpe, max drawdown, years up, and SPY over the same days."""
    r = r.dropna()
    if since:
        r = r[r.index >= pd.Timestamp(since)]
    if len(r) < 20:
        return {"n_days": int(len(r))}
    eq = (1 + r).cumprod()
    years = max((r.index[-1] - r.index[0]).days / 365.25, 1e-9)
    dd = float((eq / eq.cummax() - 1).min())
    vol = float(r.std() * math.sqrt(252))
    yr = (1 + r).groupby(r.index.year).prod() - 1
    out = {"start": str(r.index[0].date()), "end": str(r.index[-1].date()), "n_days": int(len(r)),
           "cagr": float(eq.iloc[-1] ** (1 / years) - 1), "vol": vol,
           "sharpe": float(r.mean() / r.std() * math.sqrt(252)) if r.std() > 0 else None,
           "max_dd": dd, "exposure": float((r != 0).mean()),
           "years_up": int((yr > 0).sum()), "years_total": int(len(yr)),
           "years": [{"y": int(y), "ret": float(v)} for y, v in yr.items()]}
    if bench is not None:
        b = bench.reindex(r.index).fillna(0)
        beq = (1 + b).cumprod()
        out["spy_cagr"] = float(beq.iloc[-1] ** (1 / years) - 1)
        out["spy_max_dd"] = float((beq / beq.cummax() - 1).min())
        out["spy_sharpe"] = float(b.mean() / b.std() * math.sqrt(252)) if b.std() > 0 else None
        yb = (1 + b).groupby(b.index.year).prod() - 1
        out["years_beat"] = int((yr > yb.reindex(yr.index)).sum())
    return out


def curve(r: pd.Series, bench: pd.Series | None = None, step: str = "ME") -> dict[str, list]:
    """Month-end cumulative return (%), for the page's equity line."""
    r = r.dropna()
    eq = (1 + r).cumprod().resample(step).last()
    out = {"series": [{"t": str(i.to_period("M")), "v": round((v - 1) * 100, 3)} for i, v in eq.items()]}
    if bench is not None:
        beq = (1 + bench.reindex(r.index).fillna(0)).cumprod().resample(step).last()
        out["bench"] = [{"t": str(i.to_period("M")), "v": round((v - 1) * 100, 3)} for i, v in beq.items()]
    return out


def tstat(x: Iterable[float]) -> dict[str, Any]:
    x = np.asarray(list(x), dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return {"n": n}
    sd = x.std(ddof=1)
    return {"n": n, "mean": float(x.mean()), "median": float(np.median(x)), "hit": float((x > 0).mean()),
            "t": float(x.mean() / sd * math.sqrt(n)) if sd > 0 else None}


def event_sleeve(trades: pd.DataFrame, close: pd.DataFrame, opn: pd.DataFrame, slots: int, cost: float,
                 rank: str | None = None) -> tuple[pd.Series, pd.DataFrame]:
    """Trades through N equal slots, marked to market at every close.

    trades: ticker, entry (Timestamp session), entry_at ('open'|'close'), exit (session), exit_at,
            side (+1/-1), and optionally a `rank` column (higher first when slots are short).
    A trade takes a free slot on its entry session (else it is skipped); its size is equity/N
    at entry. Returns daily sleeve returns and the trades actually taken (with their return)."""
    days = close.index
    pos = {d: i for i, d in enumerate(days)}
    t = trades[trades.entry.isin(pos) & trades.exit.isin(pos) & trades.ticker.isin(close.columns)].copy()
    t = t[(t.exit > t.entry) | ((t.exit == t.entry) & (t.entry_at == "open") & (t.exit_at == "close"))]
    if rank and rank in t:
        t = t.sort_values(["entry", rank], ascending=[True, False])
    else:
        t = t.sort_values("entry")
    by_day: dict[pd.Timestamp, list] = {}
    for row in t.itertuples():
        by_day.setdefault(row.entry, []).append(row)
    eq, cash, held, taken = 1.0, 1.0, [], []
    rets = np.zeros(len(days))
    C, O = close.to_numpy(dtype=float), opn.to_numpy(dtype=float)
    col = {c: j for j, c in enumerate(close.columns)}
    prev_eq = 1.0

    def enter(tr, i, when):
        nonlocal cash
        j = col[tr.ticker]
        px = O[i, j] if when == "open" else C[i, j]
        if not (px > 0) or len(held) >= slots:
            return
        notional = eq / slots
        held.append({"j": j, "side": tr.side, "q": notional / px, "entry_px": px, "exit_i": pos[tr.exit],
                     "exit_at": tr.exit_at, "tr": tr, "last": px})
        cash -= tr.side * notional + cost / 2 * notional

    def leave(h, px, d):
        nonlocal cash
        if not (px > 0):
            px = h["last"]
        cash += h["side"] * h["q"] * px - cost / 2 * h["q"] * px
        taken.append({"ticker": h["tr"].ticker, "entry": h["tr"].entry, "exit": d, "side": h["side"],
                      "ret": h["side"] * (px / h["entry_px"] - 1) - cost})

    for i, d in enumerate(days):
        todays = by_day.get(d, [])
        # the open: exits due at the open, then entries at the open
        for h in [h for h in held if h["exit_i"] == i and h["exit_at"] == "open"]:
            leave(h, O[i, h["j"]], d)
            held.remove(h)
        for tr in todays:
            if tr.entry_at == "open":
                enter(tr, i, "open")
        # the close: exits due at the close free their slots before close entries
        for h in [h for h in held if h["exit_i"] == i and h["exit_at"] == "close"]:
            leave(h, C[i, h["j"]], d)
            held.remove(h)
        value = 0.0
        for h in held:
            px_c = C[i, h["j"]]
            if px_c > 0:
                h["last"] = px_c
            value += h["side"] * h["q"] * h["last"]
        eq = cash + value
        for tr in todays:
            if tr.entry_at == "close":
                enter(tr, i, "close")
        eq = cash + sum(h["side"] * h["q"] * h["last"] for h in held)
        rets[i] = eq / prev_eq - 1 if prev_eq > 0 else 0.0
        prev_eq = eq
    return pd.Series(rets, index=days), pd.DataFrame(taken)


# ───────────────────────── market data ─────────────────────────

def alpaca_headers() -> dict[str, str]:
    from backend.app.db.session import SessionLocal
    from backend.app.services.strategy_lab import data_headers

    with SessionLocal() as db:
        return data_headers(db) or {}


def alpaca_daily(symbols: list[str], start: str, end: str | None = None, adjustment: str = "all") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily SIP opens and closes (split+dividend adjusted by default), one column per ticker.
    Cached for a day under $DATA_DIR/bars_cache, keyed by the request."""
    import hashlib

    key = hashlib.md5(json_key(sorted(set(symbols)), start, adjustment).encode()).hexdigest()[:16]
    cache = os.path.join(os.getenv("DATA_DIR", "/app/data"), "bars_cache")
    os.makedirs(cache, exist_ok=True)
    fo, fc = os.path.join(cache, f"{key}_o.pkl"), os.path.join(cache, f"{key}_c.pkl")
    if os.path.exists(fc) and time.time() - os.path.getmtime(fc) < 86400:
        return pd.read_pickle(fo), pd.read_pickle(fc)
    O, C = _alpaca_daily(symbols, start, end, adjustment)
    O.to_pickle(fo)
    C.to_pickle(fc)
    return O, C


def json_key(*parts) -> str:
    import json as _j

    return _j.dumps(parts, default=str)


def ew_index(C: pd.DataFrame, names: list[str]) -> pd.Series:
    """Equal-weight index of `names` (daily rebalanced, daily moves clipped at ±50%): the
    baseline that carries the same survivorship as any rule run on the same list."""
    r = C[[n for n in names if n in C]].pct_change().clip(-0.5, 0.5)
    return (1 + r.mean(axis=1).fillna(0)).cumprod()


def _alpaca_daily(symbols: list[str], start: str, end: str | None = None, adjustment: str = "all") -> tuple[pd.DataFrame, pd.DataFrame]:
    from backend.app.services.strategy_lab import from_alpaca, to_alpaca

    h = alpaca_headers()
    end = end or (pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=20)).isoformat()
    o: dict[str, dict] = {}
    c: dict[str, dict] = {}
    syms = [s for s in symbols if s and "^" not in s]
    for i in range(0, len(syms), 100):
        token = None
        while True:
            p = {"symbols": ",".join(to_alpaca(s) for s in syms[i:i + 100]), "timeframe": "1Day", "feed": "sip",
                 "adjustment": adjustment, "start": start, "end": end, "limit": 10000}
            if token:
                p["page_token"] = token
            body = {}
            for attempt in range(6):
                try:
                    r = httpx.get("https://data.alpaca.markets/v2/stocks/bars", headers=h, params=p, timeout=60)
                except httpx.HTTPError:
                    time.sleep(3 + 3 * attempt)
                    continue
                if r.status_code == 429:
                    time.sleep(15)
                    continue
                if r.status_code == 400 and "invalid symbol" in r.text:
                    bad = r.text.split("invalid symbol:")[-1].strip().strip('"}').strip().strip('\\"')
                    p["symbols"] = ",".join(x for x in p["symbols"].split(",") if x != bad)
                    if not p["symbols"]:
                        break
                    continue
                body = r.json() if r.status_code == 200 else {}
                time.sleep(0.31)
                break
            for sym, rows in (body.get("bars") or {}).items():
                s = from_alpaca(sym)
                for b in rows:
                    d = pd.Timestamp(b["t"]).tz_convert(NY).tz_localize(None).normalize()
                    o.setdefault(s, {})[d] = float(b["o"])
                    c.setdefault(s, {})[d] = float(b["c"])
            token = body.get("next_page_token")
            if not token:
                break
        if (i // 100) % 5 == 0:
            print(f"daily bars {min(i + 100, len(syms))}/{len(syms)}", flush=True)
    O = pd.DataFrame(o).sort_index()
    C = pd.DataFrame(c).sort_index()
    return O, C


def yf_daily(tickers: list[str], start: str = "1993-01-01") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Total-return-adjusted opens and closes from Yahoo (longer history than the broker feed)."""
    import yfinance as yf

    raw = yf.download(tickers, start=start, auto_adjust=True, progress=False, group_by="ticker", threads=True)
    O, C = {}, {}
    for t in tickers:
        try:
            f = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        O[t] = f["Open"]
        C[t] = f["Close"]
    O, C = pd.DataFrame(O), pd.DataFrame(C)
    O.index = pd.to_datetime(O.index).tz_localize(None)
    C.index = pd.to_datetime(C.index).tz_localize(None)
    return O, C


def out_path(name: str) -> str:
    return os.path.join(os.getenv("DATA_DIR", "/app/data"), name)
