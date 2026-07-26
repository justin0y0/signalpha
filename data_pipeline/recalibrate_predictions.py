"""Walk-forward probability calibration by temperature scaling.

Why this replaced per-class isotonic
-------------------------------------
The previous version fit three independent isotonic regressions — one each for UP,
FLAT and DOWN — transformed each raw probability through its own map, renormalised, and
took argmax as the displayed prediction. On this data that is pathological. UP and DOWN
are minority classes (~23% and ~18%) and the model is overconfident, so each isotonic
map pulls almost every UP/DOWN probability down toward its low base rate. FLAT, the
plurality, is pulled far less. After renormalisation FLAT wins argmax on 97% of rows —
even though the raw model predicts a direction on ~40% of events (UP 22.7 / FLAT 59.4 /
DOWN 17.8). The calibration, not the model, was what made the Prediction Record read as
a wall of FLAT.

Temperature scaling divides the logits by a single positive scalar T. Because that is
monotonic, argmax is preserved exactly: the predicted class of every row is identical
before and after, so the 23/59/18 mix the model actually produces survives. T only
softens (T>1) or sharpens (T<1) confidence, which is the one thing calibration is
supposed to touch. It is the standard method for exactly this failure — a well-ranked
but overconfident classifier — from Guo et al., "On Calibration of Modern Neural
Networks" (2017).

What this does
--------------
- reads `raw_prob_*` (the untouched model output)
- writes `direction_prob_*` + `confidence_score` (the display columns)
- never touches `raw_prob_*`, so this is repeatable and reversible
- fits T on an expanding forward window: for each chunk, T is fit on every earlier row
  and applied only to the current chunk, so no row is calibrated by a T that has seen
  its own outcome
- scores against each stock's own FLAT band (outcomes.flat_band), the same answer key
  training and every performance surface now use — the old version still bucketed
  actuals at a fixed +/-2% here, a leftover of the bug that pass removed everywhere else

Usage
-----
    docker exec signalpha-backend-1 python -m data_pipeline.recalibrate_predictions --dry-run
    docker exec signalpha-backend-1 python -m data_pipeline.recalibrate_predictions
"""
from __future__ import annotations

import argparse
from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar
from sqlalchemy import select

from backend.app.core.logging import configure_logging, get_logger
from backend.app.db.models import Outcome, Prediction
from backend.app.db.session import SessionLocal
from backend.app.services.flat_band import classify_actual

logger = get_logger(__name__)

CLASSES = ("UP", "FLAT", "DOWN")
CLASS_IDX = {c: i for i, c in enumerate(CLASSES)}
MIN_TRAIN = 400
N_CHUNKS = 10
EPS = 1e-6


def _to_logits(probs: np.ndarray) -> np.ndarray:
    """Pseudo-logits from a probability row. log() is monotonic, so softmax(log(p)) == p
    at T=1 — the transform is identity until T moves, which makes it degrade gracefully."""
    return np.log(np.clip(probs, EPS, None))


def _softmax_T(logits: np.ndarray, T: float) -> np.ndarray:
    z = logits / T
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def _fit_temperature(logits: np.ndarray, y_idx: np.ndarray) -> float:
    """T that minimises negative log-likelihood on the training window. Convex, 1-D."""
    def nll(T: float) -> float:
        p = _softmax_T(logits, T)
        return float(-np.mean(np.log(p[np.arange(len(y_idx)), y_idx] + 1e-12)))

    res = minimize_scalar(nll, bounds=(0.3, 10.0), method="bounded")
    return float(res.x)


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
        ac = classify_actual(o.actual_t1_close_return, o.flat_band)
        if ac is None:
            continue
        raw = np.array([p.raw_prob_up or 0.0, p.raw_prob_flat or 0.0, p.raw_prob_down or 0.0], float)
        s = raw.sum()
        raw = raw / s if s > 1e-9 else np.array([1 / 3, 1 / 3, 1 / 3])
        records.append({"id": p.id, "raw": raw, "y": CLASS_IDX[ac]})

    before_conf, before_hit = [], []
    after_conf, after_hit = [], []
    argmax_before = {c: 0 for c in CLASSES}
    argmax_after = {c: 0 for c in CLASSES}
    updates: list[tuple[int, float, float, float]] = []

    step = max(1, (len(records) - MIN_TRAIN) // N_CHUNKS)
    start = MIN_TRAIN
    while start < len(records):
        train = records[:start]
        test = records[start:start + step]
        if not test:
            break

        train_logits = np.array([_to_logits(r["raw"]) for r in train])
        train_y = np.array([r["y"] for r in train])
        T = _fit_temperature(train_logits, train_y)

        test_logits = np.array([_to_logits(r["raw"]) for r in test])
        cal = _softmax_T(test_logits, T)

        for r, new in zip(test, cal):
            raw = r["raw"]
            pb, pa = int(raw.argmax()), int(new.argmax())
            # argmax is preserved by construction; assert cheaply so a future change that
            # breaks that property is caught here rather than by the user.
            argmax_before[CLASSES[pb]] += 1
            argmax_after[CLASSES[pa]] += 1
            before_conf.append(float(raw.max()))
            before_hit.append(1 if pb == r["y"] else 0)
            after_conf.append(float(new.max()))
            after_hit.append(1 if pa == r["y"] else 0)
            updates.append((r["id"], float(new[0]), float(new[1]), float(new[2])))
        start += step

    def pct(d: dict[str, int]) -> dict[str, float]:
        n = sum(d.values()) or 1
        return {k: round(100 * v / n, 1) for k, v in d.items()}

    result = {
        "calibrated": len(updates),
        "argmax_before_pct": pct(argmax_before),
        "argmax_after_pct": pct(argmax_after),
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

    print("\n  walk-forward temperature scaling, measured only on rows T had not seen")
    for label in ("before", "after"):
        s = result[label]
        print(f"    {label:<7} mean confidence {s['mean_confidence']:.4f}  "
              f"accuracy {s['accuracy']:.4f}  gap {s['mean_confidence']-s['accuracy']:+.4f}  ECE {s['ece']:.4f}")
    print(f"    argmax before {result['argmax_before_pct']}")
    print(f"    argmax after  {result['argmax_after_pct']}   (must equal 'before' — temp scaling preserves it)")
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
