"""Lopez de Prado triple-barrier labeling for trade outcomes.

For each entry, define three barriers:
  - Profit target: +pt_mult × σ_t
  - Stop loss:    -sl_mult × σ_t
  - Time:         max_bars from entry

σ_t = recent realized vol (EWMA of squared returns).
Returns whichever barrier is hit first, with timestamp and bars-held.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def realized_vol(returns: pd.Series, halflife: int = 20) -> pd.Series:
    """EWMA realized volatility."""
    return returns.ewm(halflife=halflife, min_periods=5).std()


def apply_barrier(prices: pd.Series, entry_idx: int, side: str,
                  sigma: float, pt_mult: float = 1.0, sl_mult: float = 1.0,
                  max_bars: int = 12) -> dict:
    """Walk forward from entry, return first barrier hit.

    Args:
        prices: full price series
        entry_idx: index position of entry bar (close)
        side: 'LONG' or 'SHORT'
        sigma: per-bar return volatility (e.g., 0.005 = 0.5%)
        pt_mult, sl_mult: barriers in units of σ × √horizon
        max_bars: time barrier (vertical)

    Returns dict: {exit_idx, exit_price, exit_reason, bars_held, return_pct}
    """
    entry_price = float(prices.iloc[entry_idx])
    horizon = max_bars
    pt_pct = pt_mult * sigma * np.sqrt(horizon)
    sl_pct = sl_mult * sigma * np.sqrt(horizon)

    end_idx = min(entry_idx + max_bars, len(prices) - 1)

    for i in range(entry_idx + 1, end_idx + 1):
        p = float(prices.iloc[i])
        if side == "LONG":
            ret = p / entry_price - 1
            if ret >= pt_pct:
                return {"exit_idx": i, "exit_price": p, "exit_reason": "PROFIT",
                        "bars_held": i - entry_idx, "return_pct": ret}
            if ret <= -sl_pct:
                return {"exit_idx": i, "exit_price": p, "exit_reason": "STOP",
                        "bars_held": i - entry_idx, "return_pct": ret}
        else:  # SHORT
            ret = 1 - p / entry_price
            if ret >= pt_pct:
                return {"exit_idx": i, "exit_price": p, "exit_reason": "PROFIT",
                        "bars_held": i - entry_idx, "return_pct": ret}
            if ret <= -sl_pct:
                return {"exit_idx": i, "exit_price": p, "exit_reason": "STOP",
                        "bars_held": i - entry_idx, "return_pct": ret}

    # Time barrier
    p = float(prices.iloc[end_idx])
    ret = (p / entry_price - 1) if side == "LONG" else (1 - p / entry_price)
    return {"exit_idx": end_idx, "exit_price": p, "exit_reason": "TIME",
            "bars_held": end_idx - entry_idx, "return_pct": ret}
