"""Regenerate historical predictions walk-forward, so the backtest stops lying.

The problem this fixes
----------------------
Every historical row in `predictions` was written in a single batch on 2026-04-26 --
5,394 of 5,530 rows carry a `created_at` LATER than the `earnings_date` they forecast.
On top of that, `calibrate_predictions.py` fit isotonic calibrators on known
`actual_t5_return` values and wrote the result back over every row, so the older 70%
were fitted to their own outcomes.

Result: a 0.65-threshold backtest reported 155/159 correct (97.5% win rate, Sharpe
8.18) from a model whose honest walk-forward accuracy is 49.3%. Backtest, Showdown and
Track Record all read `predictions JOIN outcomes`, so all three were reporting
in-sample fit as if it were live performance.

What this script does
---------------------
Reuses the exact purged walk-forward splits that `models/train.py` already uses to
report the honest 49.3%, but instead of throwing the fold predictions away it writes
each one back to `predictions`. For every event the model that scores it has seen only
rows that come strictly earlier in time, so the stored probability is a genuine ex-ante
forecast.

Rows written here get `is_out_of_sample = TRUE`. Rows that cannot be regenerated (no
feature payload, sector too small to train) keep `is_out_of_sample = FALSE` and should
be excluded from every performance surface.

Sector routing mirrors production: `run_predictions` scores an event with
`registry.load_for_sector(event.sector or "general")`, which falls back to the general
model when a sector has no artifact. This script resolves each event the same way, so
the regenerated history matches how live predictions are actually produced.

Usage
-----
    # dry run -- reports coverage, writes nothing
    docker exec signalpha-backend-1 python -m data_pipeline.regenerate_predictions --dry-run

    # write
    docker exec signalpha-backend-1 python -m data_pipeline.regenerate_predictions
"""
from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Prediction
from backend.app.db.session import SessionLocal
from models.dataset import walk_forward_splits
from models.ensemble import ModelEnsemble
from models.train import MIN_ROWS_PER_SECTOR, _prepare_training_frame

logger = get_logger(__name__)
settings = get_settings()

NON_FEATURE_COLS = {
    "ticker", "earnings_date", "sector",
    "actual_t1_close_return", "actual_t5_return", "actual_t20_return",
    "convergence_low", "convergence_high",
    "direction_label", "magnitude_target",
}


def _feature_cols(frame: pd.DataFrame) -> list[str]:
    """Same selection rule as models/train.py: numeric, and <70% missing."""
    candidates = [
        c for c in frame.columns
        if c not in NON_FEATURE_COLS and pd.api.types.is_numeric_dtype(frame[c])
    ]
    return [c for c in candidates if frame[c].notna().mean() >= 0.30]


def _balance(train: pd.DataFrame) -> pd.DataFrame:
    """Upsample minority direction classes to 1:1:1 — mirrors models/train.py."""
    counts = train["direction_label"].value_counts()
    target = counts.max()
    parts = []
    for label, count in counts.items():
        subset = train[train["direction_label"] == label]
        parts.append(subset.sample(n=target, replace=True, random_state=42) if count < target else subset)
    return pd.concat(parts).sample(frac=1, random_state=42).reset_index(drop=True)


def _walk_forward_for_sector(frame: pd.DataFrame, sector: str) -> dict[tuple[str, Any], dict]:
    """Return {(ticker, earnings_date): prediction} for every row a fold could score."""
    feature_cols = _feature_cols(frame)
    if not feature_cols:
        return {}

    subset = frame[[*NON_FEATURE_COLS, *feature_cols]].copy()
    subset = subset.replace([np.inf, -np.inf], np.nan)
    subset = subset.sort_values("earnings_date").reset_index(drop=True)

    out: dict[tuple[str, Any], dict] = {}
    splits = walk_forward_splits(
        subset,
        min_train_size=min(MIN_ROWS_PER_SECTOR, max(20, len(subset) // 2)),
        test_window=max(5, len(subset) // 10),
        step=max(5, len(subset) // 10),
    )
    for fold, split in enumerate(splits, 1):
        train = subset.iloc[split.train_index].copy()
        test = subset.iloc[split.test_index]
        if train.empty or test.empty:
            continue
        balanced = _balance(train)
        # The fold's train window ends before its test window begins, so this model
        # has never seen any row it is about to score.
        model = ModelEnsemble(sector=sector, model_version=f"wf-{sector}-f{fold}")
        try:
            model.fit(
                balanced[feature_cols],
                balanced["direction_label"],
                balanced["magnitude_target"],
                balanced["convergence_low"],
                balanced["convergence_high"],
                balanced[["ticker", "earnings_date", "sector",
                          "actual_t1_close_return", "actual_t5_return", "actual_t20_return"]],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("sector=%s fold=%s fit failed: %s", sector, fold, exc)
            continue

        train_end = train["earnings_date"].max()
        for _, row in test.iterrows():
            try:
                x = pd.DataFrame([{c: row[c] for c in feature_cols}])
                pred = model.predict(x)
            except Exception as exc:  # noqa: BLE001
                logger.warning("predict failed for %s %s: %s", row["ticker"], row["earnings_date"], exc)
                continue
            key = (row["ticker"], pd.Timestamp(row["earnings_date"]).date())
            out[key] = {
                "pred": pred,
                "sector": sector,
                "fold": fold,
                "train_end": pd.Timestamp(train_end).date(),
            }
        logger.info("sector=%s fold=%s: trained on %s rows, scored %s", sector, fold, len(train), len(test))
    return out


def regenerate(dry_run: bool = False) -> dict[str, Any]:
    frame = _prepare_training_frame(settings.database_url)
    if frame.empty:
        logger.error("no training rows available — nothing to regenerate")
        return {"scored": 0, "written": 0}

    frame["sector"] = frame["sector"].fillna("Unknown")
    sectors_with_models = sorted(
        s for s, n in frame["sector"].value_counts().items() if n >= MIN_ROWS_PER_SECTOR
    )
    logger.info("%s rows; sectors with their own model: %s", len(frame), sectors_with_models)

    # General model first, then per-sector results overwrite it. This reproduces
    # registry.load_for_sector(), which prefers the sector artifact and falls back to
    # general — so an event is scored by the same model production would have used.
    scored: dict[tuple[str, Any], dict] = {}
    scored.update(_walk_forward_for_sector(frame, "general"))
    for sector in sectors_with_models:
        sector_frame = frame[frame["sector"] == sector]
        if len(sector_frame) < 20:
            continue
        scored.update(_walk_forward_for_sector(sector_frame, sector))

    logger.info("walk-forward produced %s ex-ante predictions", len(scored))
    if dry_run:
        _report_dry_run(scored)
        return {"scored": len(scored), "written": 0}

    written = 0
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    with SessionLocal() as session:
        for (ticker, edate), item in scored.items():
            try:
                row = session.execute(
                    select(Prediction).filter_by(ticker=ticker, earnings_date=edate)
                ).scalar_one_or_none()
                if row is None:
                    continue
                p = item["pred"]
                probs = p["direction_probabilities"]
                row.direction_prob_up = probs["up"]
                row.direction_prob_flat = probs["flat"]
                row.direction_prob_down = probs["down"]
                row.raw_prob_up = probs["up"]
                row.raw_prob_flat = probs["flat"]
                row.raw_prob_down = probs["down"]
                row.confidence_score = p["confidence_score"]
                row.expected_move_pct = p["expected_move_pct"]
                row.expected_move_low = p["expected_move_low"]
                row.expected_move_high = p["expected_move_high"]
                row.convergence_low = p["convergence_low"]
                row.convergence_high = p["convergence_high"]
                row.model_version = f"wf-{stamp}-{item['sector']}-f{item['fold']}"
                row.is_out_of_sample = True
                session.commit()
                written += 1
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                logger.warning("write failed for %s %s: %s", ticker, edate, exc)

    logger.info("regeneration complete: %s rows rewritten as out-of-sample", written)
    return {"scored": len(scored), "written": written}


def _report_dry_run(scored: dict) -> None:
    with SessionLocal() as session:
        total = session.execute(select(Prediction)).scalars().all()
        matched = sum(
            1 for p in total if (p.ticker, p.earnings_date) in scored
        )
    print(f"\n  walk-forward scored : {len(scored)}")
    print(f"  rows in predictions : {len(total)}")
    print(f"  would be rewritten  : {matched}")
    print(f"  left in-sample      : {len(total) - matched}  (excluded from performance surfaces)\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report coverage without writing")
    args = parser.parse_args()
    result = regenerate(dry_run=args.dry_run)
    print(result)
