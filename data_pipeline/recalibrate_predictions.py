"""Walk-forward probability calibration.

Why the old script had to be replaced
-------------------------------------
`calibrate_predictions.py` fit isotonic calibrators on the older 70% of predictions
using their known outcomes, then applied them to ALL rows — including the 70% it had
just trained on — and overwrote `direction_prob_*` in place, destroying the model's
raw output with no way back. That is one of the two things that made the backtest
claim a 97.5% win rate.

What this does instead
----------------------
Calibration is fit the same way the predictions themselves now are: expanding window,
strictly forward. For each chunk of events in date order, the isotonic calibrators are
fit on every row that comes EARLIER and applied only to the current chunk. No row is
ever calibrated by a mapping that has seen its own outcome.

- reads `raw_prob_*` (the untouched model output)
- writes `direction_prob_*` + `confidence_score` (the display columns)
- never touches `raw_prob_*`, so this is repeatable and reversible

Why calibration matters here: the regenerated model averages 0.71 confidence while
being right 46.4% of the time. Showing a user "85% confident" for a coin flip is
misleading regardless of whether the underlying model has edge.

Usage
-----
    docker exec signalpha-backend-1 python -m data_pipeline.recalibrate_predictions --dry-run
    docker exec signalpha-backend-1 python -m data_pipeline.recalibrate_predictions
"""
from __future__ import annotations

import argparse
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sqlalchemy import select

from backend.app.core.logging import configure_logging, get_logger
from backend.app.db.models import Outcome, Prediction
from backend.app.db.session import SessionLocal

logger = get_logger(__name__)

FLAT_THRESHOLD = 0.02
# Must match models/train.py's label (label_direction on actual_t1_close_return) and the
# horizon every performance surface scores against.
MIN_TRAIN = 400
N_CHUNKS = 10


def _actual_class(t1: float | None) -> str | None:
    if t1 is None:
        return None
    if t1 > FLAT_THRESHOLD:
        return "UP"
    if t1 < -FLAT_THRESHOLD:
        return "DOWN"
    return "FLAT"


def _fit(pairs: list[tuple[float, int]]) -> IsotonicRegression | None:
    if len(pairs) < 30 or len({y for _, y in pairs}) < 2:
        return None
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    return IsotonicRegression(out_of_bounds="clip").fit(xs, ys)


def _ece(probs: list[float], hits: list[int], bins: int = 10) -> float:
    """Expected calibration error: mean |confidence - accuracy| across probability bins."""
    if not probs:
        return 0.0
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(probs) if (lo <= p < hi or (b == bins - 1 and p == 1.0))]
        if not idx:
            continue
        conf = float(np.mean([probs[i] for i in idx]))
        acc = float(np.mean([hits[i] for i in idx]))
        total += len(idx) / len(probs) * abs(conf - acc)
    return total


def recalibrate(dry_run: bool = False) -> dict[str, Any]:
    with SessionLocal() as session:
        rows = session.execute(
            select(Prediction, Outcome)
            .join(
                Outcome,
                (Outcome.ticker == Prediction.ticker)
                & (Outcome.earnings_date == Prediction.earnings_date),
            )
            .where(Prediction.is_out_of_sample.is_(True))
            .where(Prediction.raw_prob_up.is_not(None))
            .where(Outcome.actual_t1_close_return.is_not(None))
            .order_by(Prediction.earnings_date.asc())
        ).all()

    logger.info("%s out-of-sample rows with raw probabilities and outcomes", len(rows))
    if len(rows) < MIN_TRAIN * 2:
        logger.error("not enough rows to calibrate walk-forward")
        return {"calibrated": 0}

    records = []
    for p, o in rows:
        ac = _actual_class(o.actual_t1_close_return)
        if ac is None:
            continue
        records.append({
            "id": p.id,
            "up": float(p.raw_prob_up or 0.0),
            "flat": float(p.raw_prob_flat or 0.0),
            "down": float(p.raw_prob_down or 0.0),
            "actual": ac,
        })

    before_conf, before_hit = [], []
    after_conf, after_hit = [], []
    updates: list[tuple[int, float, float, float]] = []

    step = max(1, (len(records) - MIN_TRAIN) // N_CHUNKS)
    start = MIN_TRAIN
    while start < len(records):
        train = records[:start]
        test = records[start:start + step]
        if not test:
            break
        cal = {
            cls: _fit([(r[cls.lower()], 1 if r["actual"] == cls else 0) for r in train])
            for cls in ("UP", "FLAT", "DOWN")
        }
        for r in test:
            raw = {"UP": r["up"], "FLAT": r["flat"], "DOWN": r["down"]}
            new = {}
            for cls, value in raw.items():
                model = cal[cls]
                new[cls] = float(model.transform([value])[0]) if model is not None else value
            total = sum(new.values())
            if total > 1e-9:
                new = {k: v / total for k, v in new.items()}
            else:
                new = raw

            pred_before = max(raw, key=raw.get)
            pred_after = max(new, key=new.get)
            before_conf.append(max(raw.values()))
            before_hit.append(1 if pred_before == r["actual"] else 0)
            after_conf.append(max(new.values()))
            after_hit.append(1 if pred_after == r["actual"] else 0)
            updates.append((r["id"], new["UP"], new["FLAT"], new["DOWN"]))
        start += step

    result = {
        "calibrated": len(updates),
        "before": {
            "mean_confidence": round(float(np.mean(before_conf)), 4),
            "accuracy": round(float(np.mean(before_hit)), 4),
            "ece": round(_ece(before_conf, before_hit), 4),
        },
        "after": {
            "mean_confidence": round(float(np.mean(after_conf)), 4),
            "accuracy": round(float(np.mean(after_hit)), 4),
            "ece": round(_ece(after_conf, after_hit), 4),
        },
    }

    print("\n  walk-forward calibration, measured only on rows a calibrator had not seen")
    for label in ("before", "after"):
        s = result[label]
        print(f"    {label:<7} mean confidence {s['mean_confidence']:.4f}  "
              f"accuracy {s['accuracy']:.4f}  gap {s['mean_confidence']-s['accuracy']:+.4f}  ECE {s['ece']:.4f}")
    print(f"    rows: {len(updates)}\n")

    if dry_run:
        return result

    written = 0
    with SessionLocal() as session:
        for pid, up, flat, down in updates:
            try:
                row = session.get(Prediction, pid)
                if row is None:
                    continue
                row.direction_prob_up = up
                row.direction_prob_flat = flat
                row.direction_prob_down = down
                row.confidence_score = max(up, flat, down)
                session.commit()
                written += 1
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                logger.warning("calibration write failed for id=%s: %s", pid, exc)
    result["written"] = written
    logger.info("wrote %s calibrated rows", written)
    return result


if __name__ == "__main__":
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(recalibrate(dry_run=args.dry_run))
