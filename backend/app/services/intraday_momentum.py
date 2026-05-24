"""Gao-Han-Li-Zhou intraday momentum (JFE 2018).

Finding: first half-hour return predicts last half-hour return on SPY and individual
liquid large-caps, R² ≈ 1.6% standalone, lifts to ~2.6% with 12th half-hour.

For 5-min bars:
  first_half = sum of returns for bars 1-6 (9:30-10:00 ET)
  last_half  = sum of returns for bars 73-78 (15:30-16:00 ET)

Use first_half_return as a SIGNAL for trades held INTO the close.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from datetime import time as _t


def first_half_hour_return(prices_today: pd.Series) -> float | None:
    """Compute first 30-min return from today's 5-min bars.
    Expects prices_today indexed by tz-aware timestamps in ET."""
    try:
        first6 = prices_today.iloc[:6]
        if len(first6) < 2:
            return None
        return float(first6.iloc[-1] / first6.iloc[0] - 1)
    except Exception:
        return None


def gao_signal(prices_today: pd.Series, current_idx: int) -> dict | None:
    """Returns signal strength for last-half-hour trade.

    Args:
        prices_today: today's 5-min closes, datetime-indexed in ET
        current_idx: position in today's bars (0-indexed)

    Returns: {'r1': first half-hour return, 'eligible': bool, 'side': LONG/SHORT}
    or None if not enough data / wrong time.
    """
    if current_idx < 66:  # Not yet at 15:00 ET
        return None
    if len(prices_today) < 7:
        return None

    r1 = first_half_hour_return(prices_today)
    if r1 is None or abs(r1) < 0.001:
        return None

    return {
        "r1": r1,
        "eligible": True,
        "side": "LONG" if r1 > 0 else "SHORT",
        "strength": min(1.0, abs(r1) / 0.015),  # cap at 1.5% move
    }
