"""Markets — the whole tape on one page.

Two sources, both read live and cached for a few minutes:

* `market_snapshot`: last price, previous close and volume for every name in the
  trained universe (~3,400 US companies over $300M), downloaded in bulk from Yahoo by
  `refresh_snapshot` every fifteen minutes in market hours. Movers, breadth and the heatmap
  come from it, joined with the universe table for name, sector and market cap. (The
  NASDAQ screener has the same fields in one request, but its prices lag a session.)
* Yahoo quotes for everything that is not a single stock: the major indices with an
  intraday line, index futures, Treasury yields, commodities, currencies, crypto and the
  main overseas indices, plus a market news feed.

News comes from public RSS feeds (CNBC, Yahoo Finance): headline, source, time, link.
"""
from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd
from sqlalchemy import text

from backend.app.db.session import SessionLocal

MOVER_MIN_CAP = 300e6

MAJORS = [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq Composite"), ("^DJI", "Dow Jones"), ("^RUT", "Russell 2000")]
GROUPS: dict[str, list[tuple[str, str]]] = {
    "futures": [("ES=F", "S&P 500 futures"), ("NQ=F", "Nasdaq 100 futures"), ("YM=F", "Dow futures"), ("RTY=F", "Russell futures")],
    "rates": [("^IRX", "3-month T-bill"), ("^FVX", "5-year Treasury"), ("^TNX", "10-year Treasury"), ("^TYX", "30-year Treasury")],
    "commodities": [("GC=F", "Gold"), ("SI=F", "Silver"), ("CL=F", "WTI crude"), ("NG=F", "Natural gas"), ("HG=F", "Copper")],
    "fx": [("DX-Y.NYB", "US dollar index"), ("EURUSD=X", "EUR / USD"), ("USDJPY=X", "USD / JPY"), ("GBPUSD=X", "GBP / USD"), ("USDCNY=X", "USD / CNY")],
    "crypto": [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ether"), ("SOL-USD", "Solana")],
    "world": [("^N225", "Nikkei 225"), ("^HSI", "Hang Seng"), ("000001.SS", "Shanghai Composite"), ("^KS11", "KOSPI"),
              ("^FTSE", "FTSE 100"), ("^GDAXI", "DAX"), ("^FCHI", "CAC 40"), ("^STOXX50E", "Euro Stoxx 50")],
    "volatility": [("^VIX", "VIX"), ("^VIX9D", "VIX 9-day"), ("^VIX3M", "VIX 3-month")],
}

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: int, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _f(v) -> float | None:
    if v is None:
        return None
    s = re.sub(r"[$,%\s]", "", str(v))
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


DDL = [
    """
    CREATE TABLE IF NOT EXISTS market_snapshot (
        ticker      TEXT PRIMARY KEY,
        price       DOUBLE PRECISION,
        prev_close  DOUBLE PRECISION,
        chg         DOUBLE PRECISION,
        volume      DOUBLE PRECISION,
        as_of       DATE,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
]

# ───────────────────────────── single stocks ─────────────────────────────

def refresh_snapshot(chunk: int = 400) -> dict[str, Any]:
    """Last bar and the one before it for every trained-tier name, in bulk."""
    import yfinance as yf

    with SessionLocal() as s:
        tickers = [t for (t,) in s.execute(text(
            "SELECT ticker FROM universe WHERE listed AND tier IN ('core','large','mid','small')")).all()]
    rows = []
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        try:
            raw = yf.download(part, period="5d", interval="1d", auto_adjust=False, progress=False,
                              threads=True, group_by="ticker")
        except Exception:  # noqa: BLE001 - one bad chunk; the next refresh retries it
            continue
        for t in part:
            try:
                f = raw[t].dropna(subset=["Close"])
            except Exception:  # noqa: BLE001
                continue
            if len(f) < 2:
                continue
            last, prev = float(f["Close"].iloc[-1]), float(f["Close"].iloc[-2])
            if prev <= 0:
                continue
            rows.append({"t": t, "p": last, "pc": prev, "c": last / prev - 1,
                         "v": float(f["Volume"].iloc[-1] or 0), "d": pd.Timestamp(f.index[-1]).date()})
    with SessionLocal() as s:
        for stmt in DDL:
            s.execute(text(stmt))
        s.execute(text("""
            INSERT INTO market_snapshot (ticker, price, prev_close, chg, volume, as_of, updated_at)
            VALUES (:t, :p, :pc, :c, :v, :d, NOW())
            ON CONFLICT (ticker) DO UPDATE SET price=EXCLUDED.price, prev_close=EXCLUDED.prev_close,
                chg=EXCLUDED.chg, volume=EXCLUDED.volume, as_of=EXCLUDED.as_of, updated_at=NOW()"""), rows)
        s.commit()
    return {"tickers": len(tickers), "written": len(rows)}


def _snapshot() -> list[dict[str, Any]]:
    with SessionLocal() as s:
        rows = s.execute(text("""
            SELECT m.ticker, u.name, m.price, m.chg, m.volume, m.as_of, m.updated_at,
                   COALESCE(u.market_cap, 0) AS cap, COALESCE(u.sector, 'Other') AS sector
            FROM market_snapshot m JOIN universe u ON u.ticker=m.ticker
            WHERE m.as_of = (SELECT max(as_of) FROM market_snapshot)""")).mappings().all()
    return [{**dict(r), "name": re.sub(r"\s+(Common Stock|Class [A-Z].*|Ordinary Shares.*|American Depositary.*)$", "", r["name"] or ""),
             "as_of": str(r["as_of"]), "updated_at": r["updated_at"].isoformat()} for r in rows]


def stocks() -> dict[str, Any]:
    rows = _cached("snapshot", 120, _snapshot)
    if not rows:
        return {}
    up = sum(1 for r in rows if r["chg"] > 0)
    down = sum(1 for r in rows if r["chg"] < 0)
    for r in rows:
        r["dollar_volume"] = (r["volume"] or 0) * r["price"]
    pick = lambda xs: [{k: r[k] for k in ("ticker", "name", "price", "chg", "volume", "cap", "sector")} for r in xs]

    sectors: dict[str, dict[str, Any]] = {}
    for r in rows:
        sec = sectors.setdefault(r["sector"], {"name": r["sector"], "cap": 0.0, "w": 0.0, "up": 0, "down": 0, "stocks": []})
        sec["cap"] += r["cap"]
        sec["w"] += r["cap"] * r["chg"]
        if r["chg"]:
            sec["up" if r["chg"] > 0 else "down"] += 1
        sec["stocks"].append(r)
    heat = []
    for sec in sectors.values():
        sec["stocks"].sort(key=lambda x: -x["cap"])
        heat.append({"name": sec["name"], "cap": sec["cap"], "chg": sec["w"] / sec["cap"] if sec["cap"] else 0.0,
                     "up": sec["up"], "down": sec["down"],
                     "stocks": [{"ticker": x["ticker"], "cap": x["cap"], "chg": x["chg"]} for x in sec["stocks"][:24]]})
    heat.sort(key=lambda x: -x["cap"])
    total_cap = sum(r["cap"] for r in rows) or 1
    return {
        "snapshot": {"as_of": rows[0]["as_of"], "updated_at": max(r["updated_at"] for r in rows), "n": len(rows)},
        "breadth": {"up": up, "down": down, "flat": len(rows) - up - down, "total": len(rows),
                    "cap_weighted": sum(r["cap"] * r["chg"] for r in rows) / total_cap,
                    "big_up": sum(1 for r in rows if r["chg"] >= 0.05), "big_down": sum(1 for r in rows if r["chg"] <= -0.05)},
        "gainers": pick(sorted(rows, key=lambda r: -r["chg"])[:25]),
        "losers": pick(sorted(rows, key=lambda r: r["chg"])[:25]),
        "active": pick(sorted(rows, key=lambda r: -r["dollar_volume"])[:25]),
        "megacaps": pick(sorted(rows, key=lambda r: -r["cap"])[:12]),
        "heatmap": heat,
    }


# ───────────────────────────── everything else ─────────────────────────────

def _quotes() -> dict[str, Any]:
    import yfinance as yf

    syms = [s for s, _ in MAJORS] + [s for g in GROUPS.values() for s, _ in g]
    daily = yf.download(syms, period="1mo", interval="1d", auto_adjust=False, progress=False, threads=True, group_by="ticker")
    intra = yf.download([s for s, _ in MAJORS], period="1d", interval="5m", auto_adjust=False, progress=False,
                        threads=True, group_by="ticker")

    def series(frame, sym):
        try:
            s = frame[sym]["Close"].dropna()
        except Exception:  # noqa: BLE001 - a symbol Yahoo did not answer is just skipped
            return pd.Series(dtype=float)
        return s

    def quote(sym, name):
        s = series(daily, sym)
        if len(s) < 2:
            return None
        last, prev = float(s.iloc[-1]), float(s.iloc[-2])
        return {"symbol": sym, "name": name, "last": last, "chg": last / prev - 1, "abs": last - prev,
                "as_of": str(pd.Timestamp(s.index[-1]).date()), "spark": [round(float(x), 4) for x in s.tail(22)]}

    majors = []
    for sym, name in MAJORS:
        q = quote(sym, name)
        if not q:
            continue
        line = series(intra, sym)
        if len(line) > 2:
            q["intraday"] = [round(float(x), 2) for x in line]
            q["intraday_from"] = str(pd.Timestamp(line.index[0]))
            q["last"] = float(line.iloc[-1])
            q["chg"] = q["last"] / float(series(daily, sym).iloc[-2]) - 1 if str(pd.Timestamp(line.index[-1]).date()) == q["as_of"] else q["chg"]
        majors.append(q)
    groups = {g: [q for q in (quote(s, n) for s, n in items) if q] for g, items in GROUPS.items()}
    return {"majors": majors, "groups": groups}


FEEDS = [("https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC"),
         ("https://www.cnbc.com/id/15839135/device/rss/rss.html", "CNBC Earnings"),
         ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US", "Yahoo Finance")]


def _news() -> list[dict[str, Any]]:
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    out, seen = [], set()
    for url, source in FEEDS:
        try:
            r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            items = ET.fromstring(r.content).iter("item")
        except Exception:  # noqa: BLE001
            continue
        for it in list(items)[:10]:
            title = (it.findtext("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            try:
                when = parsedate_to_datetime(it.findtext("pubDate") or "").isoformat()
            except Exception:  # noqa: BLE001
                when = None
            out.append({"title": title, "publisher": source, "link": it.findtext("link"), "time": when})
    out.sort(key=lambda x: x["time"] or "", reverse=True)
    return out[:18]


def markets() -> dict[str, Any]:
    body: dict[str, Any] = {"as_of": datetime.now(timezone.utc).isoformat()}
    parts = (("stocks", lambda: stocks()),
             ("quotes", lambda: _cached("quotes", 180, _quotes)),
             ("news", lambda: {"news": _cached("news", 600, _news)}))
    for key, fn in parts:
        try:
            body.update(fn())
        except Exception as exc:  # noqa: BLE001 - one dead source must not blank the page
            body.setdefault("errors", []).append(f"{key}: {exc}"[:200])
    return body
