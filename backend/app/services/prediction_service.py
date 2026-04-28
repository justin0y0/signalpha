from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models import EarningsEvent, Outcome, Prediction, PriceFeature
from backend.app.schemas.common import DataCompletenessWarning
from backend.app.schemas.prediction import (
    ConvergenceBand,
    DirectionProbabilities,
    DriverContribution,
    ExpectedMove,
    HistoricalReaction,
    PredictionResponse,
    SimilarCase,
)
from backend.app.services.feature_service import FeatureService
from models.registry import ModelRegistry


class PredictionService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.feature_service = FeatureService()
        self.registry = ModelRegistry(settings.model_dir)

    def _build_warning_objects(self, feature_completeness: float | None, existing: list | dict | None) -> list[DataCompletenessWarning]:
        warnings: list[DataCompletenessWarning] = []
        if feature_completeness is not None and feature_completeness < self.settings.feature_completeness_warning_threshold:
            warnings.append(
                DataCompletenessWarning(
                    field="feature_completeness",
                    message=(
                        f"Only {feature_completeness:.0%} of expected features are populated; prediction confidence may be degraded."
                    ),
                )
            )
        if isinstance(existing, list):
            for item in existing:
                if isinstance(item, dict) and item.get("field") and item.get("message"):
                    warnings.append(DataCompletenessWarning(**item))
        return warnings

    def _fetch_historical_reactions(self, db: Session, ticker: str) -> list[HistoricalReaction]:
        rows = db.execute(
            select(Outcome)
            .where(Outcome.ticker == ticker.upper())
            .order_by(desc(Outcome.earnings_date))
            .limit(8)
        ).scalars()
        items: list[HistoricalReaction] = []
        for row in rows:
            beat_miss = None
            if row.actual_t1_close_return is not None:
                if row.actual_t1_close_return > 0.02:
                    beat_miss = "positive"
                elif row.actual_t1_close_return < -0.02:
                    beat_miss = "negative"
                else:
                    beat_miss = "mixed"
            items.append(
                HistoricalReaction(
                    earnings_date=row.earnings_date,
                    reaction_pct=row.actual_t1_close_return,
                    beat_miss=beat_miss,
                )
            )
        return items

    def _map_prediction(self, event: EarningsEvent, prediction: Prediction) -> PredictionResponse:
        direction_probabilities = DirectionProbabilities(
            up=prediction.direction_prob_up or 0.0,
            flat=prediction.direction_prob_flat or 0.0,
            down=prediction.direction_prob_down or 0.0,
        )
        predicted_direction = max(
            {"UP": direction_probabilities.up, "FLAT": direction_probabilities.flat, "DOWN": direction_probabilities.down},
            key=lambda k: {"UP": direction_probabilities.up, "FLAT": direction_probabilities.flat, "DOWN": direction_probabilities.down}[k],
        )
        key_drivers = [DriverContribution(**item) for item in (prediction.key_drivers or [])]
        similar_cases = [SimilarCase(**item) for item in (prediction.similar_cases or [])]
        warnings = self._build_warning_objects(prediction.feature_completeness, prediction.warning_flags)
        historical_avg = None
        if prediction.similar_cases:
            rets = [abs(case.get("actual_t1_return", 0.0) or 0.0) for case in prediction.similar_cases]
            if rets:
                historical_avg = float(sum(rets) / len(rets))
        return PredictionResponse(
            ticker=event.ticker,
            company_name=event.company_name,
            earnings_date=event.earnings_date,
            report_time=event.report_time,
            sector=event.sector,
            model_version=prediction.model_version,
            direction_probabilities=direction_probabilities,
            predicted_direction=predicted_direction,
            confidence_score=prediction.confidence_score or 0.0,
            expected_move=ExpectedMove(
                point_estimate_pct=prediction.expected_move_pct,
                low_pct=prediction.expected_move_low,
                high_pct=prediction.expected_move_high,
                historical_avg_pct=historical_avg,
            ),
            convergence_band=ConvergenceBand(
                lower=prediction.convergence_low,
                upper=prediction.convergence_high,
                current_price=(prediction.feature_snapshot or {}).get("price_t0") if prediction.feature_snapshot else None,
                horizon_days=20,
            ),
            data_completeness=prediction.feature_completeness or 0.0,
            warnings=warnings,
            key_drivers=key_drivers,
            similar_cases=similar_cases,
            historical_reactions=[],
            feature_snapshot=prediction.feature_snapshot or {},
        )

    def _predict_on_demand(self, db: Session, event: EarningsEvent) -> PredictionResponse:
        feature_snapshot = self.feature_service.get_feature_snapshot(db, event.ticker, event.earnings_date)
        price_row = db.execute(
            select(PriceFeature).where(
                and_(PriceFeature.ticker == event.ticker, PriceFeature.earnings_date == event.earnings_date)
            )
        ).scalar_one_or_none()
        if not price_row or not price_row.feature_payload:
            raise ValueError("Feature payload is missing; scheduled feature collection may not have completed yet.")

        model = self.registry.load_for_sector(event.sector or "general")
        input_frame = pd.DataFrame([price_row.feature_payload])
        pred = model.predict(input_frame, current_price=price_row.feature_payload.get("price_t0"))
        key_drivers = model.explain_top_features(input_frame, top_n=5)
        similar_cases = model.find_similar_cases(input_frame, top_k=3)
        warnings = self._build_warning_objects(pred.get("data_completeness"), pred.get("warnings"))

        return PredictionResponse(
            ticker=event.ticker,
            company_name=event.company_name,
            earnings_date=event.earnings_date,
            report_time=event.report_time,
            sector=event.sector,
            model_version=model.model_version,
            direction_probabilities=DirectionProbabilities(**pred["direction_probabilities"]),
            predicted_direction=pred["predicted_direction"],
            confidence_score=pred["confidence_score"],
            expected_move=ExpectedMove(
                point_estimate_pct=pred["expected_move_pct"],
                low_pct=pred["expected_move_low"],
                high_pct=pred["expected_move_high"],
                historical_avg_pct=pred.get("historical_avg_pct"),
            ),
            convergence_band=ConvergenceBand(
                lower=pred["convergence_low"],
                upper=pred["convergence_high"],
                current_price=feature_snapshot.get("price_t0"),
                horizon_days=20,
            ),
            data_completeness=pred["data_completeness"],
            warnings=warnings,
            key_drivers=[DriverContribution(**item) for item in key_drivers],
            similar_cases=[SimilarCase(**item) for item in similar_cases],
            historical_reactions=self._fetch_historical_reactions(db, event.ticker),
            feature_snapshot=feature_snapshot,
        )

    def get_prediction(self, db: Session, ticker: str, earnings_date: date | None = None) -> PredictionResponse:
        event_stmt = select(EarningsEvent).where(EarningsEvent.ticker == ticker.upper())
        if earnings_date:
            event_stmt = event_stmt.where(EarningsEvent.earnings_date == earnings_date)
        event_stmt = event_stmt.order_by(EarningsEvent.earnings_date.desc()).limit(1)
        event = db.execute(event_stmt).scalar_one_or_none()
        if event is None:
            raise ValueError(f"No earnings event found for {ticker}")

        prediction = db.execute(
            select(Prediction).where(
                and_(Prediction.ticker == event.ticker, Prediction.earnings_date == event.earnings_date)
            )
        ).scalar_one_or_none()

        if prediction is not None:
            response = self._map_prediction(event, prediction)
            response.historical_reactions = self._fetch_historical_reactions(db, event.ticker)
            return response
        return self._predict_on_demand(db, event)
