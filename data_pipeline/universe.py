"""Every US-listed stock, and the earnings history behind each one.

Until 2026-10 the site followed 180 hand-picked large caps. Justin asked for every US
stock to be searchable and trained on. This module owns that universe.

Where the list comes from
-------------------------
The NASDAQ screener download (one request, every NASDAQ / NYSE / AMEX listing with name,
market cap, sector, country). Preferreds, warrants, units and rights are dropped by
symbol shape; ADRs stay, because they report and trade like any other US listing.

Two tiers
---------
* trained — market cap of at least TRAIN_MIN_CAP when the list is refreshed. Each gets its
  full history: every report Yahoo lists since 2008, the outcome measured on the session
  that traded it (earnings_timing rules), and point-in-time features built from bars
  strictly before that session (rebuild_pit_features rules). These rows train the models.
* searchable — everything else. Nothing is stored ahead of time; /lookup scores one on
  demand and says it sits outside the range the model was trained on.

What this cannot fix
--------------------
The list is today's listings, so the history has survivorship bias: companies that were
delisted, acquired or went bankrupt are missing. The playbook numbers already say so for
the large caps; it matters more for small ones, and the per-tier evaluation reports it.

    python -m data_pipeline.universe refresh                # the listing -> universe table
    python -m data_pipeline.universe build [--limit N]      # history for untrained names
    python -m data_pipeline.universe status
"""
from __future__ import annotations

import argparse
import bisect
import json
import logging
import math
import re
import time
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
from sqlalchemy import text

from backend.app.db.schema_guard import UNIVERSE_DDL
from backend.app.db.session import SessionLocal
from data_pipeline.collector import SECTOR_ETF_MAP
from data_pipeline.earnings_timing import fetch as fetch_timing
from data_pipeline.rebuild_pit_features import MARKET, WINDOW_DAYS, Bars, features_asof

log = logging.getLogger(__name__)

SCREENER = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TRAIN_MIN_CAP = 300e6
HISTORY_FROM = date(2008, 1, 1)
SYMBOL = re.compile(r"^[A-Z]{1,5}([./][A-Z])?$")

# NASDAQ's sector names -> the Yahoo-style names the rest of the pipeline keys on. Yahoo's
# own sector is preferred when the info call answers; this is the fallback.
NASDAQ_SECTOR = {
    "Technology": "Technology", "Finance": "Financial Services", "Health Care": "Healthcare",
    "Consumer Discretionary": "Consumer Cyclical", "Consumer Staples": "Consumer Defensive",
    "Industrials": "Industrials", "Energy": "Energy", "Utilities": "Utilities",
    "Real Estate": "Real Estate", "Telecommunications": "Communication Services",
    "Basic Materials": "Materials",
}
YAHOO_SECTOR = {"Basic Materials": "Materials"}

# Slow macro series (FRED) are not in the bars; they are taken from the nearest earlier
# event that already carries them. They change monthly at most.
SLOW_MACRO = ("yield_10y", "yield_2y", "yield_curve_slope", "fed_funds_rate", "cpi_yoy", "pce_yoy")

PRICE_COLS = ("price_1d_pre", "price_5d_pre", "price_10d_pre", "price_20d_pre", "price_60d_pre",
              "ret_1d_pre", "ret_5d_pre", "ret_10d_pre", "ret_20d_pre", "ret_60d_pre",
              "volume_anomaly", "rsi_14", "macd", "macd_signal", "bollinger_position",
              "dist_52w_high", "dist_52w_low")

def tier_of(cap: float | None) -> str:
    if not cap:
        return "micro"
    return "large" if cap >= 10e9 else "mid" if cap >= 2e9 else "small" if cap >= TRAIN_MIN_CAP else "micro"


# ───────────────────────────── the listing ─────────────────────────────

def fetch_listings() -> list[dict]:
    r = httpx.get(SCREENER, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    rows = (r.json().get("data") or {}).get("rows") or []
    out = []
    for row in rows:
        sym = (row.get("symbol") or "").strip().upper()
        if not SYMBOL.match(sym):
            continue
        name = (row.get("name") or "").strip()
        if re.search(r"\b(Warrants?|Rights?|Units?|Preferred|Notes due|Debentures)\b", name, re.I):
            continue
        try:
            cap = float(row.get("marketCap") or 0) or None
        except ValueError:
            cap = None
        out.append({
            "ticker": sym.replace("/", "-").replace(".", "-"),  # Yahoo's spelling: BRK-B
            "name": name, "market_cap": cap, "country": row.get("country") or None,
            "sector": NASDAQ_SECTOR.get(row.get("sector") or ""), "industry": row.get("industry") or None,
        })
    return out


def _company_key(name: str) -> str:
    n = re.sub(r"\b(class [a-z]|series [a-z]|common stock|capital stock|ordinary shares|"
               r"subordinate voting shares|common shares|american depositary shares?)\b", " ", name.lower())
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def ensure_table() -> None:
    with SessionLocal() as s:
        for stmt in UNIVERSE_DDL:
            s.execute(text(stmt))
        s.commit()


def refresh() -> dict:
    """Upsert today's listing. Names that already have events are tier 'core'."""
    ensure_table()
    rows = fetch_listings()
    if len(rows) < 3000:
        raise RuntimeError(f"screener returned {len(rows)} rows; refusing to shrink the universe")
    with SessionLocal() as s:
        core = {t for (t,) in s.execute(text(
            "SELECT DISTINCT ticker FROM earnings_events WHERE source IS DISTINCT FROM 'universe'")).all()}
        seen = set()
        # One company, one history: a second share class (GOOG beside GOOGL, BRK-A beside
        # BRK-B) reports the same numbers on the same day and would count every report
        # twice. Keep the class we already follow, else the shorter symbol.
        primary: dict[str, str] = {}
        for r in sorted(rows, key=lambda r: (r["ticker"] not in core, len(r["ticker"]), r["ticker"])):
            primary.setdefault(_company_key(r["name"]), r["ticker"])
        for r in rows:
            seen.add(r["ticker"])
            r["tier"] = ("core" if r["ticker"] in core
                         else "dup" if primary.get(_company_key(r["name"])) != r["ticker"]
                         else tier_of(r["market_cap"]))
            s.execute(text("""
                INSERT INTO universe (ticker, name, sector, industry, market_cap, country, tier, listed, updated_at)
                VALUES (:ticker, :name, :sector, :industry, :market_cap, :country, :tier, TRUE, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    name=EXCLUDED.name, industry=EXCLUDED.industry, market_cap=EXCLUDED.market_cap,
                    country=EXCLUDED.country, listed=TRUE, updated_at=NOW(),
                    sector=COALESCE(universe.sector, EXCLUDED.sector),
                    tier=CASE WHEN universe.tier='core' THEN 'core' ELSE EXCLUDED.tier END"""), r)
        s.execute(text("UPDATE universe SET listed=FALSE WHERE NOT (ticker = ANY(:seen))"), {"seen": list(seen)})
        # A name built before it was recognised as a second class: drop what was built.
        dups = [t for (t,) in s.execute(text("""
            SELECT DISTINCT u.ticker FROM universe u JOIN earnings_events e ON e.ticker=u.ticker
            WHERE u.tier='dup' AND e.source='universe'""")).all()]
        for t in dups:
            for table in ("price_features", "outcomes", "predictions"):
                s.execute(text(f"""DELETE FROM {table} x USING earnings_events e
                                   WHERE x.ticker=:t AND e.ticker=x.ticker AND e.earnings_date=x.earnings_date
                                     AND e.source='universe'"""), {"t": t})
            s.execute(text("DELETE FROM earnings_events WHERE ticker=:t AND source='universe'"), {"t": t})
            s.execute(text("UPDATE universe SET history_at=NULL, history_events=NULL, history_note='second share class' WHERE ticker=:t"), {"t": t})
        s.commit()
        counts = dict(s.execute(text("SELECT tier, count(*) FROM universe WHERE listed GROUP BY 1")).all())
    return {"listed": len(rows), "tiers": counts}


# ───────────────────────────── history ─────────────────────────────

class SlowMacro:
    """Nearest-earlier lookup of the FRED-derived fields, from events that carry them."""

    def __init__(self) -> None:
        with SessionLocal() as s:
            rows = s.execute(text(f"""
                SELECT earnings_date, {", ".join(f"feature_payload->>'{k}' AS {k}" for k in SLOW_MACRO)}
                FROM price_features WHERE feature_payload->>'yield_10y' IS NOT NULL
                ORDER BY earnings_date""")).mappings().all()
        self.dates = [r["earnings_date"] for r in rows]
        self.rows = [{k: _f(r[k]) for k in SLOW_MACRO} for r in rows]

    def asof(self, d: date) -> dict:
        i = bisect.bisect_left(self.dates, d) - 1
        return dict(self.rows[i]) if i >= 0 else {}


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _yahoo_sector(ticker: str) -> tuple[str | None, str | None]:
    """(sector, quoteType) from Yahoo, or (None, None) when it does not answer."""
    import yfinance as yf
    try:
        info = yf.Ticker(ticker).get_info() or {}
    except Exception:  # noqa: BLE001 - info is a nicety; the NASDAQ sector is the fallback
        return None, None
    sec = info.get("sector")
    return YAHOO_SECTOR.get(sec, sec), info.get("quoteType")


def _retry(fn, *a, tries: int = 3):
    for k in range(tries):
        try:
            return fn(*a)
        except Exception as exc:  # noqa: BLE001
            if "rate" in str(exc).lower() or "429" in str(exc) or "too many" in str(exc).lower():
                wait = 60 * (k + 1)
                log.warning("rate limited on %s; sleeping %ss", a, wait)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"still rate limited after {tries} tries: {a}")


def _next_session(d: date) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


def build_one(s, u: dict, bars: Bars, macro: SlowMacro) -> tuple[int, str]:
    """Events, outcomes and features for one ticker. Returns (events written, note)."""
    t = u["ticker"]
    today = date.today()
    sector, qtype = _yahoo_sector(t)
    if qtype and qtype not in ("EQUITY",):
        return 0, f"quoteType {qtype}"
    sector = sector or u["sector"]

    reports = [r for r in _retry(fetch_timing, t) if r["report_date"] >= HISTORY_FROM]
    if not reports:
        return 0, "no earnings dates"
    hist = bars.get(t)
    if hist.empty or len(hist) < 60:
        bars.cache.pop(t, None)
        return 0, "no price history"

    yfc = bars.yf
    written = 0
    for r in sorted(reports, key=lambda x: x["report_date"]):
        d, rt = r["report_date"], r["report_time"]
        s.execute(text("""
            INSERT INTO earnings_surprises (ticker, report_date, report_ts, report_time,
                eps_estimate, eps_actual, surprise_pct, updated_at)
            VALUES (:ticker, :report_date, :report_ts, :report_time, :eps_estimate, :eps_actual, :surprise_pct, NOW())
            ON CONFLICT (ticker, report_date) DO NOTHING"""), r)
        s.execute(text("""
            INSERT INTO earnings_events (ticker, company_name, earnings_date, report_time, sector, industry,
                                         market_cap, source, created_at, updated_at)
            VALUES (:t, :n, :d, :rt, :sec, :ind, :cap, 'universe', NOW(), NOW())
            ON CONFLICT (ticker, earnings_date) DO NOTHING"""),
            {"t": t, "n": u["name"], "d": d, "rt": rt, "sec": sector, "ind": u["industry"], "cap": u["market_cap"]})

        reaction = None
        if d < today:
            out = yfc.outcome_snapshot(hist, datetime.combine(d, datetime.min.time()), rt)
            if out and out.get("actual_t1_close_return") is not None:
                reaction = out.get("reaction_date")
                cols = {k: v for k, v in out.items() if k in OUTCOME_COLS and v is not None}
                cols = {k: (bool(v) if k == "gap_filled" else v) for k, v in cols.items()}
                names = ", ".join(cols)
                s.execute(text(f"""
                    INSERT INTO outcomes (ticker, earnings_date, {names})
                    VALUES (:ticker, :earnings_date, {", ".join(":" + k for k in cols)})
                    ON CONFLICT (ticker, earnings_date) DO NOTHING"""),
                    {"ticker": t, "earnings_date": d, **cols})
        if reaction is not None:
            cutoff = pd.Timestamp(reaction).date()
        else:
            cutoff = _next_session(d) if (rt or "").upper() == "AMC" else d
            cutoff = min(cutoff, today + timedelta(days=1))
        fresh = features_asof(bars, t, sector, cutoff)
        if not fresh:
            continue
        payload = {**macro.asof(cutoff), **fresh, "ticker": t, "earnings_date": d.isoformat(), "sector": sector}
        if payload.get("yield_10y") is not None and payload.get("yield_2y") is not None and payload.get("yield_curve_slope") is None:
            payload["yield_curve_slope"] = payload["yield_10y"] - payload["yield_2y"]
        s.execute(text(f"""
            INSERT INTO price_features (ticker, earnings_date, {", ".join(PRICE_COLS)}, feature_payload, created_at, updated_at)
            VALUES (:t, :d, {", ".join(":" + c for c in PRICE_COLS)}, CAST(:p AS jsonb), NOW(), NOW())
            ON CONFLICT (ticker, earnings_date) DO NOTHING"""),
            {"t": t, "d": d, **{c: fresh.get(c) for c in PRICE_COLS}, "p": json.dumps(payload, default=str)})
        written += 1
    bars.cache.pop(t, None)
    return written, "ok"


OUTCOME_COLS: set[str] = set()


def _outcome_cols() -> set[str]:
    with SessionLocal() as s:
        return {c for (c,) in s.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='outcomes'")).all()} - {
            "id", "ticker", "earnings_date", "created_at", "updated_at"}


def build(limit: int | None = None, tickers: list[str] | None = None) -> dict:
    """History for every trained-tier name that does not have it yet. Resumable."""
    ensure_table()
    OUTCOME_COLS.update(_outcome_cols())
    with SessionLocal() as s:
        if tickers:
            todo = s.execute(text("SELECT * FROM universe WHERE ticker = ANY(:t)"), {"t": tickers}).mappings().all()
        else:
            todo = s.execute(text("""
                SELECT * FROM universe
                WHERE listed AND tier IN ('large','mid','small') AND history_at IS NULL
                ORDER BY market_cap DESC NULLS LAST"""
                + (f" LIMIT {int(limit)}" if limit else ""))).mappings().all()
    if not todo:
        return {"todo": 0}
    macro = SlowMacro()
    bars = Bars(HISTORY_FROM - timedelta(days=WINDOW_DAYS + 30))
    for sym in (*MARKET, *SECTOR_ETF_MAP.values()):
        bars.get(sym)
    events = done = failed = 0
    started = time.time()
    for n, u in enumerate(todo, 1):
        u = dict(u)
        try:
            with SessionLocal() as s:
                k, note = build_one(s, u, bars, macro)
                s.execute(text("""UPDATE universe SET history_at=NOW(), history_events=:k, history_note=:note
                                  WHERE ticker=:t"""), {"k": k, "note": note, "t": u["ticker"]})
                s.commit()
            events += k
            done += 1
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not stop three thousand
            failed += 1
            bars.cache.pop(u["ticker"], None)
            log.warning("universe %s failed: %s", u["ticker"], exc)
            with SessionLocal() as s:
                s.execute(text("UPDATE universe SET history_note=:n WHERE ticker=:t"),
                          {"n": f"failed: {str(exc)[:200]}", "t": u["ticker"]})
                s.commit()
        time.sleep(0.4)
        if n % 25 == 0:
            rate = n / max(1.0, time.time() - started)
            log.info("universe [%s/%s] events=%s failed=%s  ~%.0f min left",
                     n, len(todo), events, failed, (len(todo) - n) / rate / 60)
    return {"tickers": len(todo), "done": done, "failed": failed, "events": events}


# ───────────────────────────── upcoming reports ─────────────────────────────

CALENDAR = "https://api.nasdaq.com/api/calendar/earnings?date={d}"
NASDAQ_TIME = {"time-pre-market": "BMO", "time-after-hours": "AMC"}


def sync_calendar(days: int = 45) -> dict:
    """Upsert the next `days` of report dates for trained-tier names.

    New events get no features here; run_predictions rebuilds features for every upcoming
    event that has a price_features row, so a stub row is written for each new one.
    A date that moved is handled like the FMP job does: the stale future event goes.
    """
    ensure_table()
    with SessionLocal() as s:
        names = {r["ticker"]: dict(r) for r in s.execute(text(
            "SELECT * FROM universe WHERE listed AND tier IN ('core','large','mid','small')")).mappings()}
    today = date.today()
    found: dict[str, tuple[date, str | None]] = {}
    for i in range(days):
        d = today + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            r = httpx.get(CALENDAR.format(d=d.isoformat()), headers={"User-Agent": UA, "Accept": "application/json"},
                          timeout=30)
            rows = ((r.json().get("data") or {}).get("rows")) or []
        except Exception as exc:  # noqa: BLE001
            log.warning("nasdaq calendar %s: %s", d, exc)
            continue
        for row in rows:
            t = (row.get("symbol") or "").upper().replace(".", "-").replace("/", "-")
            if t in names and t not in found:
                found[t] = (d, NASDAQ_TIME.get(row.get("time") or ""))
        time.sleep(0.3)
    added = moved = 0
    with SessionLocal() as s:
        for t, (d, rt) in found.items():
            u = names[t]
            stale = s.execute(text("""SELECT earnings_date FROM earnings_events
                                      WHERE ticker=:t AND earnings_date >= :today AND earnings_date <> :d
                                        AND abs(earnings_date - :d) <= 20"""),
                              {"t": t, "today": today, "d": d}).scalars().all()
            for old in stale:
                for table in ("predictions", "price_features", "financial_metrics"):
                    s.execute(text(f"DELETE FROM {table} WHERE ticker=:t AND earnings_date=:d"), {"t": t, "d": old})
                s.execute(text("DELETE FROM earnings_events WHERE ticker=:t AND earnings_date=:d"), {"t": t, "d": old})
                moved += 1
            res = s.execute(text("""
                INSERT INTO earnings_events (ticker, company_name, earnings_date, report_time, sector, industry,
                                             market_cap, source, created_at, updated_at)
                VALUES (:t, :n, :d, :rt, :sec, :ind, :cap, 'universe', NOW(), NOW())
                ON CONFLICT (ticker, earnings_date) DO UPDATE SET
                    report_time=COALESCE(EXCLUDED.report_time, earnings_events.report_time), updated_at=NOW()"""),
                {"t": t, "n": u["name"], "d": d, "rt": rt, "sec": u["sector"], "ind": u["industry"], "cap": u["market_cap"]})
            s.execute(text("""INSERT INTO price_features (ticker, earnings_date, feature_payload, created_at, updated_at)
                              VALUES (:t, :d, CAST('{}' AS jsonb), NOW(), NOW())
                              ON CONFLICT (ticker, earnings_date) DO NOTHING"""), {"t": t, "d": d})
            added += res.rowcount
        s.commit()
    return {"names": len(names), "found": len(found), "upserted": added, "moved": moved}


def status() -> dict:
    with SessionLocal() as s:
        return {
            "tiers": dict(s.execute(text("SELECT tier, count(*) FROM universe WHERE listed GROUP BY 1")).all()),
            "built": dict(s.execute(text("""SELECT tier, count(*) FROM universe
                                            WHERE history_at IS NOT NULL GROUP BY 1""")).all()),
            "events": s.execute(text("SELECT count(*) FROM earnings_events WHERE source='universe'")).scalar(),
            "failed": s.execute(text("SELECT count(*) FROM universe WHERE history_note LIKE 'failed%'")).scalar(),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["refresh", "build", "status"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--tickers", nargs="*")
    a = ap.parse_args()
    if a.cmd == "refresh":
        print(refresh())
    elif a.cmd == "build":
        print(build(a.limit, a.tickers))
    else:
        print(status())
