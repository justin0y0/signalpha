"""The only features a model is allowed to see: ones knowable before the report.

Why a whitelist and not a blacklist
-----------------------------------
`collect_event_snapshot` builds a feature row from several sources, and some of them
take no date at all — they return *today's* value whenever they are called:

  * options (atm_iv, straddle, put/call, iv_rank, expected_move_pct) — the live chain
  * analyst targets, estimates, recommendation counts — today's consensus
  * fundamentals ratios, short interest, institutional ownership — today's `info`
  * news / 10-Q sentiment — the latest headlines and filing
  * `last_8q_reactions`, `beats` — the latest eight reports *as of collection*

For an event collected live (up to 21 days before the report) those are genuine
pre-report values. For every event collected afterwards — the 2014-2025 history was
backfilled in 2026, the April-September 2026 gap on 2026-10-02 — they describe a
different moment entirely. At best that is noise from years later; at worst it is the
event's own outcome: a September report backfilled in October has itself among its
"latest eight reports", so its own post-earnings move was sitting in its features.

Training on them taught the models nothing true and made every evaluation suspect, so
the rule is now positive: a column is a feature only if it is derived from data dated
strictly before the report. New columns stay out until someone checks where they come
from and adds them here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Price/volume history up to the day before the report, technicals computed from it,
# and market/macro series fetched with end=as_of_date.
POINT_IN_TIME = frozenset({
    "price_t0", "price_1d_pre", "price_5d_pre", "price_10d_pre", "price_20d_pre", "price_60d_pre",
    "ret_1d_pre", "ret_5d_pre", "ret_10d_pre", "ret_20d_pre", "ret_60d_pre",
    "high_52w", "low_52w", "dist_52w_high", "dist_52w_low",
    "volume_t1", "volume_20d_avg", "volume_anomaly",
    "rsi_14", "macd", "macd_signal", "bollinger_position",
    "pre_earn_momentum_5d", "pre_earn_momentum_20d", "relative_strength_vs_spy",
    "market_regime", "bull_bear_regime",
    "spy_price", "spy_200ma", "spy_ret_1d", "spy_ret_5d", "spy_ret_20d",
    "qqq_ret_1d", "qqq_ret_5d", "qqq_ret_20d",
    "vix", "vix9d", "vix3m", "vix_percentile",
    "yield_10y", "yield_2y", "yield_curve_slope", "fed_funds_rate", "cpi_yoy", "pce_yoy",
    "hyg_lqd_spread", "sector_peer_median", "sector_median_reaction",
})
POINT_IN_TIME_PREFIXES = ("sector_relative.",)

# Derived from outcomes.flat_band, which is itself point-in-time (median of the
# ticker's reactions strictly before this report). own_band is the single most useful
# input for "will this move more than usual": walk-forward AUC 0.538 -> 0.571, and the
# gain holds on tickers with 16+ prior reports, so it is not an artefact of short history.
DERIVED = ("own_band", "mom20_vs_band")

MIN_COVERAGE = 0.30


def is_point_in_time(col: str) -> bool:
    return col in POINT_IN_TIME or col.startswith(POINT_IN_TIME_PREFIXES) or col in DERIVED


def add_derived(frame: pd.DataFrame, band: pd.Series | None = None) -> pd.DataFrame:
    """Attach the band-relative features. `band` defaults to frame['flat_band']."""
    b = (band if band is not None else frame.get("flat_band", pd.Series(np.nan, index=frame.index))).astype(float)
    frame["own_band"] = b
    mom = frame["pre_earn_momentum_20d"].astype(float) if "pre_earn_momentum_20d" in frame else np.nan
    frame["mom20_vs_band"] = (pd.Series(mom, index=frame.index).abs() / b).replace([np.inf, -np.inf], np.nan)
    return frame


def feature_columns(frame: pd.DataFrame) -> list[str]:
    """Numeric point-in-time columns with enough coverage to be worth fitting."""
    return [
        c for c in frame.columns
        if is_point_in_time(c)
        and pd.api.types.is_numeric_dtype(frame[c])
        and frame[c].notna().mean() >= MIN_COVERAGE
    ]
