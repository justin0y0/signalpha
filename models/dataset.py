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


def label_direction_adaptive(value: float, stock_std: float | None, floor: float = 0.025, ceiling: float = 0.10) -> str:
    """Stock-aware label. Uses 0.5x stock's historical earnings reaction std as FLAT boundary.
    Bounded between [floor, ceiling] so we don't get crazy thresholds.
    
    Examples:
    - KO with std=0.015 -> FLAT zone is ±0.75% (capped to floor 1.5%)
    - TSLA with std=0.08 -> FLAT zone is ±4%
    - SMCI with std=0.15 -> FLAT zone is ±7.5% (capped to ceiling 10%)
    """
    if stock_std is None or stock_std != stock_std:  # NaN check
        threshold = floor
    else:
        threshold = max(floor, min(ceiling, abs(stock_std) * 1.0))
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
