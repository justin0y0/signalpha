"""The one definition of what counts as a non-event.

A three-class accuracy figure is meaningless unless the answer key matches the one
the model was trained against. It did not. `models/dataset.py::label_direction_adaptive`
labels each event with that stock's *own* band — 0.5x its historical earnings-reaction
sigma, clamped to [2.5%, 10%] — while Track Record graded every stock at a flat +/-2%
and Performance at a flat 2.0%. A 2% move is a shrug for TSLA and a large move for KO,
so the two surfaces were marking correct answers wrong and wrong answers correct,
in opposite directions, depending on the ticker.

That is why the site reported 49.3% on one page and 59.9% on another for the same model
over the same events. Both were computed correctly; they were answering different
questions. This module makes them answer the same one.

Calendar already replicated the rule in raw SQL. It now imports from here instead, so
there is exactly one place where this threshold lives.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# Kept identical to models/dataset.py::label_direction_adaptive. If you change one,
# change both — or better, change this and have training import it.
SIGMA_MULTIPLE = 0.5
BAND_FLOOR = 0.025
BAND_CEILING = 0.10
# Below this many realised reactions a per-stock sigma is noise, so the stock falls
# back to the floor rather than inheriting a band fitted on two data points.
MIN_OBSERVATIONS = 4

_BAND_SQL = text(
    f"""SELECT ticker,
               greatest({BAND_FLOOR}, least({BAND_CEILING},
                        {SIGMA_MULTIPLE} * stddev_samp(actual_t1_close_return))) AS band
        FROM outcomes
        WHERE actual_t1_close_return IS NOT NULL
          AND (:all_tickers OR ticker = ANY(:tickers))
        GROUP BY ticker
        HAVING count(*) >= {MIN_OBSERVATIONS}"""
)


def load_flat_bands(db: Session, tickers: list[str] | None = None) -> dict[str, float]:
    """Per-ticker FLAT band, one query. Pass None for every ticker.

    Tickers with too few realised reactions are simply absent; callers fall back to
    BAND_FLOOR via `classify_actual`, which is the same thing training does when a
    stock's sigma is NaN.
    """
    rows = db.execute(
        _BAND_SQL,
        {"all_tickers": tickers is None, "tickers": tickers or []},
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def classify_actual(ret: float | None, band: float | None) -> str | None:
    """Bucket a realised T+1 close return using that stock's own band.

    Returns None for a missing return so the caller can skip the row rather than
    silently scoring it as FLAT — an unknown outcome is not a non-event.
    """
    if ret is None:
        return None
    threshold = BAND_FLOOR if band is None else band
    if ret > threshold:
        return "UP"
    if ret < -threshold:
        return "DOWN"
    return "FLAT"
