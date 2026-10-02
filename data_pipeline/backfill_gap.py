"""Fill the hole between a restored database dump and today.

The production database was lost with the Google Cloud VM. The newest surviving dump
is from 2026-04-28, so every earnings event, feature snapshot and realised outcome
after that date has to be collected again. This does exactly that, for the tickers the
dump already tracks — unlike sp500_backfill.py, it does not widen the universe.

Steps, each idempotent (existing rows are skipped, so it is safe to re-run):
  1. events   — yfinance earnings dates after --since for every tracked ticker
  2. features — collect_event_snapshot for events that have no price_features row
  3. outcomes — collect_post_earnings_outcome for past events that have no outcome

Usage:
    docker compose run --rm backend python -m data_pipeline.backfill_gap
    docker compose run --rm backend python -m data_pipeline.backfill_gap --since 2026-04-01
"""
from __future__ import annotations

import argparse
import time
from datetime import date, datetime

import pandas as pd
import yfinance as yf
from sqlalchemy import select

from backend.app.db.models import EarningsEvent, Outcome
from backend.app.db.session import SessionLocal
from data_pipeline.jobs import _upsert, collector
from data_pipeline.sp500_backfill import backfill_features


def tracked_tickers() -> dict[str, tuple[str | None, str | None]]:
    """ticker -> (company_name, sector), taken from the most recent event we hold."""
    with SessionLocal() as s:
        rows = s.execute(
            select(EarningsEvent.ticker, EarningsEvent.company_name, EarningsEvent.sector)
            .order_by(EarningsEvent.earnings_date.asc())
        ).all()
    return {t: (c, sec) for t, c, sec in rows}


def backfill_events(tickers: dict, since: date) -> int:
    today = date.today()
    with SessionLocal() as s:
        existing = set(s.execute(select(EarningsEvent.ticker, EarningsEvent.earnings_date)).all())
    added = 0
    for i, (ticker, (company, sector)) in enumerate(sorted(tickers.items()), 1):
        try:
            df = yf.Ticker(ticker).earnings_dates
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {ticker}: {exc}")
            time.sleep(1)
            continue
        if df is None or len(df) == 0:
            continue
        with SessionLocal() as s:
            for raw in df.index:
                d = pd.to_datetime(raw).date()
                if d <= since or d > today or (ticker, d) in existing:
                    continue
                _upsert(s, EarningsEvent, {"ticker": ticker, "earnings_date": d},
                        {"company_name": company, "sector": sector, "source": "yfinance"})
                existing.add((ticker, d))
                added += 1
            s.commit()
        if i % 20 == 0:
            print(f"  events [{i}/{len(tickers)}] added={added}")
        time.sleep(0.3)
    print(f"events: {added} added")
    return added


def backfill_outcomes(since: date) -> int:
    today = date.today()
    with SessionLocal() as s:
        have = set(s.execute(select(Outcome.ticker, Outcome.earnings_date)).all())
        events = s.execute(
            select(EarningsEvent)
            .where(EarningsEvent.earnings_date > since, EarningsEvent.earnings_date < today)
            .order_by(EarningsEvent.earnings_date.asc())
        ).scalars().all()
        todo = [(e.ticker, e.earnings_date) for e in events if (e.ticker, e.earnings_date) not in have]
    print(f"outcomes: {len(todo)} to collect")
    written = 0
    for i, (ticker, d) in enumerate(todo, 1):
        try:
            outcome = collector.collect_post_earnings_outcome(ticker, d)
            if outcome:
                with SessionLocal() as s:
                    _upsert(s, Outcome, {"ticker": ticker, "earnings_date": d}, outcome)
                    s.commit()
                written += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ! outcome {ticker} {d}: {exc}")
        if i % 25 == 0:
            print(f"  outcomes [{i}/{len(todo)}] written={written}")
    print(f"outcomes: {written} written")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-04-01", help="collect events strictly after this date")
    since = datetime.strptime(ap.parse_args().since, "%Y-%m-%d").date()

    tickers = tracked_tickers()
    print(f"{len(tickers)} tracked tickers, backfilling after {since}")
    backfill_events(tickers, since)
    backfill_features(list(tickers))
    backfill_outcomes(since)
    print("BACKFILL COMPLETE")
