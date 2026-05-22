"""
Post-hoc probability calibration using isotonic regression.

Trains 3 calibrators (one per class) on the older 70% of predictions
where outcomes are known, then applies to ALL predictions in the DB.

Usage:
  docker compose exec backend python -m data_pipeline.calibrate_predictions
"""
from __future__ import annotations
import joblib
import numpy as np
from pathlib import Path
from sklearn.isotonic import IsotonicRegression
from sqlalchemy import select
from backend.app.db.models import Outcome, Prediction
from backend.app.db.session import SessionLocal

FLAT_THRESHOLD = 0.02


def actual_class(t5: float | None) -> str | None:
    if t5 is None:
        return None
    if t5 > FLAT_THRESHOLD:
        return "UP"
    if t5 < -FLAT_THRESHOLD:
        return "DOWN"
    return "FLAT"


def main() -> None:
    print("Loading predictions with outcomes...")
    with SessionLocal() as s:
        rows = s.execute(
            select(Prediction, Outcome)
            .join(
                Outcome,
                (Outcome.ticker == Prediction.ticker)
                & (Outcome.earnings_date == Prediction.earnings_date),
            )
            .where(Outcome.actual_t5_return.is_not(None))
            .order_by(Prediction.earnings_date.asc())
        ).all()
    print(f"  Got {len(rows)} predictions with outcomes")

    # Train calibrators on first 70% (chronological)
    split = int(len(rows) * 0.7)
    train_rows = rows[:split]
    print(f"  Training on first {len(train_rows)} (older), holding out last {len(rows)-split}")

    train_up_p, train_up_y = [], []
    train_flat_p, train_flat_y = [], []
    train_down_p, train_down_y = [], []

    for p, o in train_rows:
        ac = actual_class(o.actual_t5_return)
        if ac is None:
            continue
        train_up_p.append(p.direction_prob_up or 0.0)
        train_up_y.append(1 if ac == "UP" else 0)
        train_flat_p.append(p.direction_prob_flat or 0.0)
        train_flat_y.append(1 if ac == "FLAT" else 0)
        train_down_p.append(p.direction_prob_down or 0.0)
        train_down_y.append(1 if ac == "DOWN" else 0)

    cal_up = IsotonicRegression(out_of_bounds="clip").fit(train_up_p, train_up_y)
    cal_flat = IsotonicRegression(out_of_bounds="clip").fit(train_flat_p, train_flat_y)
    cal_down = IsotonicRegression(out_of_bounds="clip").fit(train_down_p, train_down_y)

    art_dir = Path("/app/artifacts/calibrators")
    art_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(cal_up, art_dir / "cal_up.joblib")
    joblib.dump(cal_flat, art_dir / "cal_flat.joblib")
    joblib.dump(cal_down, art_dir / "cal_down.joblib")
    print(f"  Saved calibrators to {art_dir}")

    # Apply to ALL predictions
    print("Applying calibrators to all predictions...")
    with SessionLocal() as s:
        all_preds = s.execute(select(Prediction)).scalars().all()
        n = len(all_preds)
        for i, p in enumerate(all_preds):
            if p.direction_prob_up is None:
                continue
            up = float(cal_up.transform([p.direction_prob_up])[0])
            fl = float(cal_flat.transform([p.direction_prob_flat or 0])[0])
            dn = float(cal_down.transform([p.direction_prob_down or 0])[0])
            total = up + fl + dn
            if total > 1e-9:
                up, fl, dn = up / total, fl / total, dn / total
            p.direction_prob_up = up
            p.direction_prob_flat = fl
            p.direction_prob_down = dn
            p.confidence_score = max(up, fl, dn)
            if (i + 1) % 500 == 0:
                s.commit()
                print(f"  {i+1}/{n}")
        s.commit()

    # Eval on holdout
    print("\nEvaluation on holdout (last 30%):")
    holdout = rows[split:]
    if holdout:
        correct_old = correct_new = 0
        for p, o in holdout:
            ac = actual_class(o.actual_t5_return)
            if ac is None:
                continue
            # We already overwrote the DB, so use new values
            probs = {"UP": p.direction_prob_up, "FLAT": p.direction_prob_flat, "DOWN": p.direction_prob_down}
            pred = max(probs, key=probs.get)
            if pred == ac:
                correct_new += 1
        print(f"  Calibrated accuracy on holdout: {correct_new}/{len(holdout)} = {correct_new/len(holdout)*100:.1f}%")

    print("\n\u2713 Done. Calibrated probabilities are now in the database.")


if __name__ == "__main__":
    main()
