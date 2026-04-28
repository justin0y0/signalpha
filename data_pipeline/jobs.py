from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import EarningsEvent, FinancialMetric, MacroFeature, ModelPerformance, Outcome, Prediction, PriceFeature
from backend.app.db.session import SessionLocal
from data_pipeline.collector import DataCollector
from models.registry import ModelRegistry
from models.train import train_from_database

logger = get_logger(__name__)
settings = get_settings()
collector = DataCollector(settings)
registry = ModelRegistry(settings.model_dir)


def _session() -> Session:
    return SessionLocal()


def _upsert(session: Session, model_cls: type, identity_filters: dict[str, Any], values: dict[str, Any]) -> Any:
    instance = session.execute(select(model_cls).filter_by(**identity_filters)).scalar_one_or_none()
    if instance is None:
        instance = model_cls(**identity_filters, **values)
        session.add(instance)
    else:
        for key, value in values.items():
            setattr(instance, key, value)
    return instance


def collect_earnings_calendar() -> None:
    logger.info("Starting earnings calendar collection job")
    start = date.today()
    end = start + timedelta(days=settings.default_calendar_lookahead_days)
    items = collector.collect_earnings_calendar(start, end)
    with _session() as session:
        for item in items:
            identity = {"ticker": item["ticker"], "earnings_date": item["earnings_date"]}
            values = {k: v for k, v in item.items() if k not in identity}
            _upsert(session, EarningsEvent, identity, values)
        session.commit()
    logger.info("Finished earnings calendar collection with %s rows", len(items))


def collect_macro_data() -> None:
    logger.info("Starting macro data collection job")
    snapshot = collector.collect_macro_snapshot(date.today())
    with _session() as session:
        identity = {"feature_date": snapshot["feature_date"]}
        values = {k: v for k, v in snapshot.items() if k not in identity}
        _upsert(session, MacroFeature, identity, values)
        session.commit()
    logger.info("Finished macro data collection")


def collect_options_data() -> None:
    logger.info("Starting company feature collection job")
    with _session() as session:
        events = session.execute(
            select(EarningsEvent)
            .where(EarningsEvent.earnings_date >= date.today(), EarningsEvent.earnings_date <= date.today() + timedelta(days=21))
            .order_by(EarningsEvent.earnings_date.asc())
        ).scalars()
        event_list = list(events)
        for event in event_list:
            try:
                snapshot = collector.collect_event_snapshot(event.ticker, event.earnings_date, event.sector)
                raw = snapshot["raw"]
                engineered = snapshot["engineered"]
                _upsert(
                    session,
                    FinancialMetric,
                    {"ticker": event.ticker, "earnings_date": event.earnings_date},
                    {
                        "eps_actual": raw.get("actual_eps"),
                        "eps_estimate": raw.get("est_eps"),
                        "revenue_actual": raw.get("actual_rev"),
                        "revenue_estimate": raw.get("est_rev"),
                        "gross_margin": raw.get("gross_margin"),
                        "operating_margin": raw.get("operating_margin"),
                        "net_margin": raw.get("net_margin"),
                        "free_cash_flow": raw.get("free_cash_flow"),
                        "operating_cash_flow": raw.get("operating_cash_flow"),
                        "forward_revenue_guidance": raw.get("forward_revenue_guidance"),
                        "forward_eps_guidance": raw.get("forward_eps_guidance"),
                        "debt_to_equity": raw.get("debt_to_equity"),
                        "cash_and_equivalents": raw.get("cash_and_equivalents"),
                        "buyback_amount": raw.get("buyback_amount"),
                        "transcript_sentiment": raw.get("transcript_sentiment"),
                        "raw_payload": raw,
                    },
                )
                _upsert(
                    session,
                    PriceFeature,
                    {"ticker": event.ticker, "earnings_date": event.earnings_date},
                    {
                        "price_1d_pre": raw.get("price_1d_pre"),
                        "price_5d_pre": raw.get("price_5d_pre"),
                        "price_10d_pre": raw.get("price_10d_pre"),
                        "price_20d_pre": raw.get("price_20d_pre"),
                        "price_60d_pre": raw.get("price_60d_pre"),
                        "ret_1d_pre": raw.get("ret_1d_pre"),
                        "ret_5d_pre": raw.get("ret_5d_pre"),
                        "ret_10d_pre": raw.get("ret_10d_pre"),
                        "ret_20d_pre": raw.get("ret_20d_pre"),
                        "ret_60d_pre": raw.get("ret_60d_pre"),
                        "atm_iv": raw.get("atm_iv"),
                        "iv_rank": engineered.get("iv_rank"),
                        "iv_percentile": engineered.get("vix_percentile"),
                        "iv_crush_hist": raw.get("iv_crush_hist"),
                        "expected_move_pct": engineered.get("expected_move_pct"),
                        "volume_anomaly": engineered.get("volume_anomaly"),
                        "rsi_14": raw.get("rsi_14"),
                        "macd": raw.get("macd"),
                        "macd_signal": raw.get("macd_signal"),
                        "bollinger_position": raw.get("bollinger_position"),
                        "dist_52w_high": engineered.get("dist_52w_high"),
                        "dist_52w_low": engineered.get("dist_52w_low"),
                        "feature_payload": {**raw, **engineered},
                    },
                )
            except Exception as exc:  # noqa: BLE001 - keep pipeline running per ticker
                logger.exception("Feature collection failed for %s on %s: %s", event.ticker, event.earnings_date, exc)
        session.commit()
    logger.info("Finished company feature collection for %s events", len(event_list))


def run_predictions() -> None:
    logger.info("Starting prediction generation job")
    with _session() as session:
        events = session.execute(
            select(EarningsEvent, PriceFeature)
            .join(PriceFeature, and_(EarningsEvent.ticker == PriceFeature.ticker, EarningsEvent.earnings_date == PriceFeature.earnings_date))
            .where(EarningsEvent.earnings_date >= date.today())
            .order_by(EarningsEvent.earnings_date.asc())
        ).all()
        for event, price_feature in events:
            try:
                model = registry.load_for_sector(event.sector or "general")
                feature_df = pd.DataFrame([price_feature.feature_payload or {}])
                prediction = model.predict(feature_df, current_price=(price_feature.feature_payload or {}).get("price_t0"))
                key_drivers = model.explain_top_features(feature_df, top_n=5)
                similar_cases = model.find_similar_cases(feature_df, top_k=3)
                _upsert(
                    session,
                    Prediction,
                    {"ticker": event.ticker, "earnings_date": event.earnings_date},
                    {
                        "sector": event.sector,
                        "direction_prob_up": prediction["direction_probabilities"]["up"],
                        "direction_prob_flat": prediction["direction_probabilities"]["flat"],
                        "direction_prob_down": prediction["direction_probabilities"]["down"],
                        "confidence_score": prediction["confidence_score"],
                        "expected_move_pct": prediction["expected_move_pct"],
                        "expected_move_low": prediction["expected_move_low"],
                        "expected_move_high": prediction["expected_move_high"],
                        "convergence_low": prediction["convergence_low"],
                        "convergence_high": prediction["convergence_high"],
                        "model_version": model.model_version,
                        "feature_completeness": prediction["data_completeness"],
                        "warning_flags": prediction.get("warnings", []),
                        "key_drivers": key_drivers,
                        "similar_cases": similar_cases,
                        "feature_snapshot": price_feature.feature_payload,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - keep job moving across sectors
                logger.exception("Prediction generation failed for %s on %s: %s", event.ticker, event.earnings_date, exc)
        session.commit()
    logger.info("Finished prediction generation")


def collect_post_earnings_results() -> None:
    logger.info("Starting post-earnings outcome collection job")
    lower = date.today() - timedelta(days=30)
    upper = date.today() - timedelta(days=1)
    with _session() as session:
        events = session.execute(
            select(EarningsEvent)
            .where(EarningsEvent.earnings_date >= lower, EarningsEvent.earnings_date <= upper)
            .order_by(EarningsEvent.earnings_date.desc())
        ).scalars()
        event_list = list(events)
        for event in event_list:
            try:
                outcome = collector.collect_post_earnings_outcome(event.ticker, event.earnings_date)
                if not outcome:
                    continue
                _upsert(session, Outcome, {"ticker": event.ticker, "earnings_date": event.earnings_date}, outcome)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Outcome collection failed for %s on %s: %s", event.ticker, event.earnings_date, exc)
        session.commit()
    logger.info("Finished post-earnings outcome collection for %s events", len(event_list))


def retrain_models() -> None:
    logger.info("Starting model retraining job")
    report = train_from_database(settings.database_url, settings.model_dir)
    with _session() as session:
        for row in report.get("performance", []):
            session.add(
                ModelPerformance(
                    model_version=row["model_version"],
                    sector=row["sector"],
                    accuracy=row.get("accuracy"),
                    precision_weighted=row.get("precision_weighted"),
                    recall_weighted=row.get("recall_weighted"),
                    f1_weighted=row.get("f1_weighted"),
                    mae=row.get("mae"),
                    rmse=row.get("rmse"),
                    sharpe_ratio=row.get("sharpe_ratio"),
                    confusion_matrix=row.get("confusion_matrix"),
                    feature_importance=row.get("feature_importance"),
                )
            )
        session.commit()
    logger.info("Finished model retraining")
