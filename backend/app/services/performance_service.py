from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.db.models import ModelPerformance
from backend.app.schemas.performance import PerformanceResponse, SectorPerformance


class PerformanceService:
    def latest(self, db: Session) -> PerformanceResponse:
        latest_row = db.execute(select(ModelPerformance).order_by(desc(ModelPerformance.recorded_at)).limit(1)).scalar_one_or_none()
        if latest_row is None:
            return PerformanceResponse(model_version=None, by_sector=[], confusion_matrix=[], feature_importance=[])

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
        best_general = next((row for row in rows_list if row.sector == "general"), rows_list[0])
        return PerformanceResponse(
            model_version=latest_row.model_version,
            by_sector=by_sector,
            confusion_matrix=best_general.confusion_matrix or [],
            feature_importance=best_general.feature_importance or [],
        )
