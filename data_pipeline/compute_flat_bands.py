"""Write each event's point-in-time FLAT band to `outcomes.flat_band`.

The band answers one question: for THIS stock, how big does an earnings move have to
be before it counts as a move at all? The answer is that stock's own median absolute
earnings reaction — half its prints are bigger, half are smaller — computed from the
events that had already happened when this one occurred.

Why the median and not sigma
----------------------------
The previous rule was `clamp(0.5 * sigma, 2.5%, 10%)`, which was meant to be adaptive
and was not: 113 of 150 tickers have 0.5*sigma below 2.5%, so for three quarters of
the universe the floor set the band and the stock's own volatility was ignored. The
result was FLAT on 60.7% of events — a model whose most common correct answer is
"nothing happens" is not worth running.

The median gives a 25/50/25-shaped target by construction, per stock, with no floor
needed and no parameter to tune. Measured over 5,521 events it produces 26.8 / 50.8 /
22.5, which is the split this project actually wants to predict.

Why persist it
--------------
Training labels and every scoring surface must agree on the answer key. They did not
before: training used per-stock sigma, Track Record used a flat 2%, Performance used a
flat 2% under a comment claiming otherwise. Storing one number per event and having
everything read it makes divergence impossible rather than merely discouraged.

Why point-in-time
-----------------
A band fitted on a stock's whole history knows how volatile that stock turned out to
be, which is information the walk-forward split is supposed to withhold. `.shift(1)`
means an event never contributes to its own band.

Usage:
    python -m data_pipeline.compute_flat_bands           # write
    python -m data_pipeline.compute_flat_bands --dry-run # report only
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter, defaultdict

from sqlalchemy import select, update

from backend.app.db.models import Outcome
from backend.app.db.session import SessionLocal

log = logging.getLogger(__name__)

# A ticker needs at least this many prior reactions before its own median means
# anything. Below it, the event falls back to GLOBAL_FALLBACK.
MIN_PRIOR = 4

# Applied only to a ticker's first few events, where there is no history to measure.
# 2% is the cross-sectional median of per-stock medians, so it is the least-wrong
# single number for a stock we know nothing about yet.
GLOBAL_FALLBACK = 0.02


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def compute(dry_run: bool = False) -> dict:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Outcome.id, Outcome.ticker, Outcome.earnings_date,
                   Outcome.actual_t1_close_return)
            .where(Outcome.actual_t1_close_return.is_not(None))
            .order_by(Outcome.ticker, Outcome.earnings_date)
        ).all()

        by_ticker: dict[str, list] = defaultdict(list)
        for r in rows:
            if abs(r.actual_t1_close_return) > 1e-9:
                by_ticker[r.ticker].append(r)

        updates: list[tuple[int, float]] = []
        used_fallback = 0
        for ticker, events in by_ticker.items():
            prior: list[float] = []
            for e in events:
                if len(prior) >= MIN_PRIOR:
                    band = _median(prior)
                else:
                    band = GLOBAL_FALLBACK
                    used_fallback += 1
                updates.append((e.id, band))
                # Only now does this event join the history, so it never sets its own band.
                prior.append(abs(e.actual_t1_close_return))

        # What the resulting labels look like — the reason this script exists.
        band_by_id = dict(updates)
        classes: Counter = Counter()
        for r in rows:
            b = band_by_id.get(r.id)
            if b is None:
                continue
            v = r.actual_t1_close_return
            classes["UP" if v > b else "DOWN" if v < -b else "FLAT"] += 1
        total = sum(classes.values()) or 1
        split = {k: round(classes[k] / total * 100, 1) for k in ("UP", "FLAT", "DOWN")}

        if not dry_run:
            for oid, band in updates:
                db.execute(update(Outcome).where(Outcome.id == oid).values(flat_band=band))
            db.commit()

        return {
            "tickers": len(by_ticker),
            "events": len(updates),
            "fallback_events": used_fallback,
            "class_split_pct": split,
            "written": 0 if dry_run else len(updates),
        }
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    result = compute(**vars(ap.parse_args()))
    for k, v in result.items():
        log.info("%-18s %s", k, v)
