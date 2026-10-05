"""Remove duplicate earnings events — two dates for one report.

Two sources produce them:
  * yfinance's ``earnings_dates`` mixes reported dates with stale *estimates*. A
    backfill that takes every row stores the estimate as if it were a report, and its
    "outcome" is then an ordinary trading day's return labelled as an earnings reaction
    — a wrong training label, not just a cosmetic duplicate.
  * FMP revises upcoming dates; the calendar job upserts the new date but never removed
    the old one, so the calendar showed the same report twice.

A pair is two events for one ticker within ``WINDOW_DAYS``. The real one is decided by
evidence, never by guessing: for past dates, the date yfinance shows a Reported EPS
for; for future dates, the date FMP currently lists. When neither side can be proven
the pair is reported and left alone.

    python -m data_pipeline.dedupe_events --dry-run
    python -m data_pipeline.dedupe_events
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy import text

from backend.app.db.session import SessionLocal

log = logging.getLogger(__name__)
WINDOW_DAYS = 10
DEPENDENTS = ("predictions", "outcomes", "price_features", "financial_metrics", "earnings_events")


def find_pairs(session) -> list[tuple[str, date, date]]:
    rows = session.execute(text("""
        SELECT a.ticker, a.earnings_date, b.earnings_date
        FROM earnings_events a JOIN earnings_events b
          ON a.ticker = b.ticker AND a.earnings_date < b.earnings_date
         AND b.earnings_date - a.earnings_date <= :w
        ORDER BY a.earnings_date"""), {"w": WINDOW_DAYS}).all()
    return [(t, d1, d2) for t, d1, d2 in rows]


def reported_dates(ticker: str) -> set[date]:
    try:
        df = yf.Ticker(ticker).get_earnings_dates(limit=60)
    except Exception as exc:  # noqa: BLE001
        log.warning("yfinance %s: %s", ticker, exc)
        return set()
    if df is None or df.empty or "Reported EPS" not in df.columns:
        return set()
    df = df.reset_index()
    return {pd.to_datetime(r.iloc[0]).date() for _, r in df.iterrows() if pd.notna(r["Reported EPS"])}


def fmp_dates(ticker: str, cache: dict) -> set[date]:
    if "feed" not in cache:
        from data_pipeline.jobs import collector
        today = date.today()
        feed = collector.fmp.earnings_calendar((today - timedelta(days=7)).isoformat(),
                                               (today + timedelta(days=90)).isoformat())
        cache["feed"] = {}
        for e in feed or []:
            if e.get("symbol") and e.get("date"):
                cache["feed"].setdefault(e["symbol"].upper(), set()).add(date.fromisoformat(e["date"][:10]))
    return cache["feed"].get(ticker, set())


def decide(ticker: str, d1: date, d2: date, fmp_cache: dict) -> tuple[date | None, str]:
    """Return (stale_date, reason) or (None, why-undecided)."""
    today = date.today()
    if d2 < today:
        real = reported_dates(ticker) & {d1, d2}
        if len(real) == 1:
            keep = real.pop()
            return (d2 if keep == d1 else d1), f"yfinance reported EPS on {keep}"
        return None, f"yfinance reported {sorted(real) or 'neither'}"
    listed = fmp_dates(ticker, fmp_cache) & {d1, d2}
    if len(listed) == 1:
        keep = listed.pop()
        return (d2 if keep == d1 else d1), f"FMP calendar lists {keep}"
    return None, f"FMP lists {sorted(listed) or 'neither'}"


def run(dry_run: bool) -> None:
    fmp_cache: dict = {}
    with SessionLocal() as s:
        pairs = find_pairs(s)
        print(f"{len(pairs)} candidate pairs")
        removed = 0
        for ticker, d1, d2 in pairs:
            stale, why = decide(ticker, d1, d2, fmp_cache)
            if stale is None:
                print(f"  KEEP BOTH {ticker} {d1} / {d2}  ({why})")
                continue
            print(f"  drop {ticker} {stale}  ({why})")
            removed += 1
            if dry_run:
                continue
            for table in DEPENDENTS:
                s.execute(text(f"DELETE FROM {table} WHERE ticker = :t AND earnings_date = :d"),
                          {"t": ticker, "d": stale})
        if not dry_run:
            s.commit()
        print(f"{'would remove' if dry_run else 'removed'} {removed} events")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    run(ap.parse_args().dry_run)
