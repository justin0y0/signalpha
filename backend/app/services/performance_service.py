from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.db.models import ModelPerformance, Outcome, Prediction
from backend.app.schemas.performance import ConfidenceTier, PerformanceResponse, SectorPerformance
from backend.app.services.prediction_filters import OUT_OF_SAMPLE_ONLY


FLAT_THRESHOLD = 0.02


def _actual_class(ret: float | None) -> str | None:
    """Bucket a realised return into the same 3 classes the model was trained on.

    Must be fed the T+1 close return. The model's direction label comes from
    `actual_t1_close_return` (models/train.py -> label_direction), and Backtest and
    Track Record both score against T+1. This function used to be handed
    `actual_t5_return`, so the confidence-tier block was grading a T+1 model against a
    T+5 outcome — an apples-to-oranges comparison that produced a flat ~33% (exactly
    3-class random) at every confidence threshold.
    """
    if ret is None:
        return None
    if ret > FLAT_THRESHOLD:
        return "UP"
    if ret < -FLAT_THRESHOLD:
        return "DOWN"
    return "FLAT"


def _predicted_class(p_up: float | None, p_flat: float | None, p_down: float | None) -> str:
    probs = {"UP": p_up or 0.0, "FLAT": p_flat or 0.0, "DOWN": p_down or 0.0}
    return max(probs, key=probs.get)


class PerformanceService:
    def latest(self, db: Session) -> PerformanceResponse:
        latest_row = db.execute(
            select(ModelPerformance).order_by(desc(ModelPerformance.recorded_at)).limit(1)
        ).scalar_one_or_none()
        if latest_row is None:
            return PerformanceResponse()

        rows = db.execute(
            select(ModelPerformance)
            .where(ModelPerformance.model_version == latest_row.model_version)
            .order_by(ModelPerformance.sector.asc())
        ).scalars()
        rows_list = list(rows)
        by_sector = [
            SectorPerformance(
                sector=row.sector,
                accuracy=row.accuracy,
                precision_weighted=row.precision_weighted,
                recall_weighted=row.recall_weighted,
                f1_weighted=row.f1_weighted,
                mae=row.mae,
                rmse=row.rmse,
                sharpe_ratio=row.sharpe_ratio,
                recorded_at=row.recorded_at,
            )
            for row in rows_list
        ]
        general = next((r for r in rows_list if r.sector == "general"), rows_list[0])

        return PerformanceResponse(
            model_version=latest_row.model_version,
            by_sector=by_sector,
            confusion_matrix=general.confusion_matrix or [],
            feature_importance=general.feature_importance or [],
            confidence_tiers=self._confidence_tiers(db),
        )

    def _confidence_tiers(self, db: Session) -> list[ConfidenceTier]:
        rows = db.execute(
            select(Prediction, Outcome)
            .join(
                Outcome,
                (Outcome.ticker == Prediction.ticker)
                & (Outcome.earnings_date == Prediction.earnings_date),
            )
            .where(Outcome.actual_t1_close_return.is_not(None))
            .where(OUT_OF_SAMPLE_ONLY)
        ).all()

        if not rows:
            return []

        records = []
        for p, o in rows:
            ac = _actual_class(o.actual_t1_close_return)
            if ac is None:
                continue
            pc = _predicted_class(p.direction_prob_up, p.direction_prob_flat, p.direction_prob_down)
            records.append({
                "conf": float(p.confidence_score or 0.0),
                "pred": pc,
                "actual": ac,
            })

        out: list[ConfidenceTier] = []
        for thresh in [0.0, 0.55, 0.65, 0.75, 0.85]:
            filt = [r for r in records if r["conf"] >= thresh]
            if not filt:
                continue
            correct = sum(1 for r in filt if r["pred"] == r["actual"])
            directional = [r for r in filt if r["pred"] in ("UP", "DOWN") and r["actual"] in ("UP", "DOWN")]
            dir_correct = sum(1 for r in directional if r["pred"] == r["actual"])
            out.append(ConfidenceTier(
                threshold=thresh,
                n_samples=len(filt),
                accuracy=correct / len(filt),
                n_directional=len(directional),
                directional_accuracy=(dir_correct / len(directional)) if directional else 0.0,
            ))
        return out
