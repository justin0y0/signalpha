"""The one definition of what counts as a non-event.

A three-class accuracy figure is meaningless unless the answer key matches the one the
model was trained against. It did not. Training labelled each event against that
stock's own band while Track Record graded every stock at a flat +/-2% and Performance
at a flat 2.0% under a comment claiming it was per-stock. A 2% move is a shrug for TSLA
and a large move for KO, so the two flat-band surfaces marked correct answers wrong and
wrong answers correct, in opposite directions, depending on the ticker. That is why the
site reported 49.3% on one page and 59.9% on another for the same model over the same
events.

The band now lives in one place — `outcomes.flat_band`, one number per event, written
by data_pipeline/compute_flat_bands.py — and training and every scoring surface read
it. Nothing recomputes it, so nothing can drift.

The band is each ticker's median absolute earnings reaction *prior to* that event. Half
its prints are bigger, half smaller, which makes the target roughly 25/50/25 by
construction (measured 26.8 / 50.8 / 22.5). The rule it replaced,
`clamp(0.5 * sigma, 2.5%, 10%)`, was adaptive in name only: 113 of 150 tickers had
0.5*sigma below the floor, so the floor set the band for three quarters of the universe
and FLAT swallowed 60.7% of events.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# Applied only where an event has no stored band — a ticker's first few prints, before
# it has enough history to measure. Matches compute_flat_bands.GLOBAL_FALLBACK.
BAND_FALLBACK = 0.02

_EVENT_BANDS_SQL = text(
    """SELECT ticker, earnings_date, flat_band
       FROM outcomes
       WHERE flat_band IS NOT NULL
         AND (:all_tickers OR ticker = ANY(:tickers))"""
)

# For events that have not happened yet there is no row to read, so an upcoming print
# is shown against the most recent band the ticker has — the best available estimate of
# what a normal move looks like for it.
_LATEST_BANDS_SQL = text(
    """SELECT DISTINCT ON (ticker) ticker, flat_band
       FROM outcomes
       WHERE flat_band IS NOT NULL
         AND (:all_tickers OR ticker = ANY(:tickers))
       ORDER BY ticker, earnings_date DESC"""
)


def load_event_bands(db: Session, tickers: list[str] | None = None) -> dict[tuple[str, object], float]:
    """Per-event bands keyed by (ticker, earnings_date). Pass None for every ticker."""
    rows = db.execute(
        _EVENT_BANDS_SQL, {"all_tickers": tickers is None, "tickers": tickers or []}
    ).fetchall()
    return {(r[0], r[1]): float(r[2]) for r in rows if r[2] is not None}


def load_flat_bands(db: Session, tickers: list[str] | None = None) -> dict[str, float]:
    """Latest band per ticker — for upcoming events with no outcome row yet."""
    rows = db.execute(
        _LATEST_BANDS_SQL, {"all_tickers": tickers is None, "tickers": tickers or []}
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def classify_actual(ret: float | None, band: float | None) -> str | None:
    """Bucket a realised T+1 close return using that event's own band.

    Returns None for a missing return so the caller can skip the row rather than
    silently scoring it as FLAT — an unknown outcome is not a non-event.
    """
    if ret is None:
        return None
    threshold = BAND_FALLBACK if band is None else band
    if ret > threshold:
        return "UP"
    if ret < -threshold:
        return "DOWN"
    return "FLAT"
