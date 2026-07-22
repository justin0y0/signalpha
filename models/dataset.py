from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pandas as pd


DIRECTION_LABELS = {-1: "DOWN", 0: "FLAT", 1: "UP"}


def label_direction(value: float, threshold: float = 0.02) -> str:
    """Static threshold variant (kept for backward compat)."""
    if value > threshold:
        return "UP"
    if value < -threshold:
        return "DOWN"
    return "FLAT"


def label_direction_adaptive(value: float, band: float | None, fallback: float = 0.02) -> str:
    """Label one event against that stock's own FLAT band.

    `band` is the median absolute earnings reaction the ticker had produced before this
    event, read from `outcomes.flat_band` (see data_pipeline/compute_flat_bands.py).
    Half of a stock's prints are larger than its median and half are smaller, so this
    yields a roughly 25/50/25 target by construction — measured 26.8 / 50.8 / 22.5 over
    5,521 events.

    This replaces `clamp(0.5 * sigma, 2.5%, 10%)`, which was adaptive in name only: 113
    of 150 tickers had 0.5*sigma below the 2.5% floor, so the floor set the band for
    three quarters of the universe and FLAT swallowed 60.7% of events. A model whose
    most common correct answer is "nothing happens" has nothing to sell.

    Examples, from the real distribution:
      KO   band 1.2%  -> a 1.5% print is a real move for KO
      TSLA band 5.1%  -> a 4% print is a normal Tuesday and stays FLAT
    """
    threshold = fallback if band is None or band != band else band
    if value > threshold:
        return "UP"
    if value < -threshold:
        return "DOWN"
    return "FLAT"


@dataclass
class WalkForwardSplit:
    train_index: list[int]
    test_index: list[int]


def walk_forward_splits(
    frame: pd.DataFrame,
    date_col: str = "earnings_date",
    min_train_size: int = 60,
    test_window: int = 20,
    step: int = 20,
) -> Iterator[WalkForwardSplit]:
    ordered = frame.sort_values(date_col).reset_index(drop=True)
    total = len(ordered)
    start = min_train_size
    while start < total:
        train_idx = list(range(0, start))
        test_idx = list(range(start, min(start + test_window, total)))
        if test_idx:
            yield WalkForwardSplit(train_index=train_idx, test_index=test_idx)
        start += step


def expand_feature_payload(frame: pd.DataFrame, payload_col: str = "feature_payload") -> pd.DataFrame:
    payload_series = frame[payload_col].apply(lambda value: value if isinstance(value, dict) else {})
    payload = pd.json_normalize(payload_series)
    payload.index = frame.index
    # Drop columns from payload that already exist in meta to avoid duplicates
    meta = frame.drop(columns=[payload_col])
    overlap = [c for c in payload.columns if c in meta.columns]
    if overlap:
        payload = payload.drop(columns=overlap)
    return pd.concat([meta, payload], axis=1)
