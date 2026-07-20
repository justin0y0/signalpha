from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import and_, desc, select
from sqlalchemy import inspect as sa_inspect
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


def _json_safe(o):
    """Coerce pandas Timestamp / datetime / numpy / NaN to JSON-serializable types."""
    if o is None or isinstance(o, (str, int, bool)):
        return o
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    if hasattr(o, "item"):
        try: return _json_safe(o.item())
        except Exception: pass
    if hasattr(o, "isoformat"):
        try: return o.isoformat()
        except Exception: return str(o)
    if isinstance(o, dict):
        return {str(k): _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_json_safe(v) for v in o]
    return o


_UNKNOWN_KEYS_SEEN: set[tuple[str, str]] = set()


def _coerce_for_model(model_cls: type, values: dict[str, Any]) -> dict[str, Any]:
    """Drop keys the model has no column for, and JSON-sanitize the JSON columns.

    Two production outages came from this gap:
      * a collector grew keys (`spy_price`, `spy_200ma`, `vix_history`) with no matching
        MacroFeature column -> `TypeError: invalid keyword argument` killed collect_macro_data
        daily for ~3 months;
      * a `datetime.date` rode into a JSONB column via `**market_snapshot` ->
        `Object of type date is not JSON serializable` killed collect_options_data for ~2 months.
    Both are now impossible: unknown keys are dropped (and logged once) and every JSON column
    goes through `_json_safe`.
    """
    mapper = sa_inspect(model_cls)
    columns = mapper.columns
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        column = columns.get(key)
        if column is None:
            marker = (model_cls.__name__, key)
            if marker not in _UNKNOWN_KEYS_SEEN:
                _UNKNOWN_KEYS_SEEN.add(marker)
                logger.warning("%s has no column %r — dropping it from the write", model_cls.__name__, key)
            continue
        if type(column.type).__name__ in {"JSON", "JSONB"}:
            value = _json_safe(value)
        cleaned[key] = value
    return cleaned


def _upsert(session: Session, model_cls: type, identity_filters: dict[str, Any], values: dict[str, Any]) -> Any:
    values = _coerce_for_model(model_cls, values)
    instance = session.execute(select(model_cls).filter_by(**identity_filters)).scalar_one_or_none()
    if instance is None:
        instance = model_cls(**identity_filters, **values)
        session.add(instance)
    else:
        for key, value in values.items():
            # Never let a sparser upstream feed blank out data we already have. FMP's /stable
            # earnings-calendar returns only symbol+date, so a plain overwrite would wipe the
            # sector column -- which is what picks the per-sector model in run_predictions.
            if value is None and getattr(instance, key, None) is not None:
                continue
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
        written = 0
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
                # Commit per event, inside the try. A commit after the loop means one bad row
                # aborts the whole transaction and the job silently writes nothing -- that is
                # how this job produced zero rows for ~2 months.
                session.commit()
                written += 1
            except Exception as exc:  # noqa: BLE001 - keep pipeline running per ticker
                session.rollback()
                logger.exception("Feature collection failed for %s on %s: %s", event.ticker, event.earnings_date, exc)
    logger.info("Finished company feature collection: %s/%s events written", written, len(event_list))


def run_predictions() -> None:
    logger.info("Starting prediction generation job")
    with _session() as session:
        events = session.execute(
            select(EarningsEvent, PriceFeature)
            .join(PriceFeature, and_(EarningsEvent.ticker == PriceFeature.ticker, EarningsEvent.earnings_date == PriceFeature.earnings_date))
            .where(EarningsEvent.earnings_date >= date.today())
            .order_by(EarningsEvent.earnings_date.asc())
        ).all()
        written = 0
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
                        "warning_flags": _json_safe(prediction.get("warnings", [])),
                        "key_drivers": _json_safe(key_drivers),
                        "similar_cases": _json_safe(similar_cases),
                        "feature_snapshot": _json_safe(price_feature.feature_payload),
                    },
                )
                session.commit()
                written += 1
            except Exception as exc:  # noqa: BLE001 - keep job moving across sectors
                session.rollback()
                logger.exception("Prediction generation failed for %s on %s: %s", event.ticker, event.earnings_date, exc)
    logger.info("Finished prediction generation: %s/%s events written", written, len(events))


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
        written = 0
        for event in event_list:
            try:
                outcome = collector.collect_post_earnings_outcome(event.ticker, event.earnings_date)
                if not outcome:
                    continue
                _upsert(session, Outcome, {"ticker": event.ticker, "earnings_date": event.earnings_date}, outcome)
                session.commit()
                written += 1
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                logger.exception("Outcome collection failed for %s on %s: %s", event.ticker, event.earnings_date, exc)
    logger.info("Finished post-earnings outcome collection: %s/%s events written", written, len(event_list))


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


def run_simulator_step() -> None:
    """Auto-step the simulator every 30 minutes during market hours."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from backend.app.db.session import SessionLocal
    from backend.app.services.simulation_service import run_step

    # Only run during US market hours-ish (4am-8pm ET, Mon-Fri)
    et = datetime.now(ZoneInfo("America/New_York"))
    if et.weekday() >= 5:
        return
    if et.hour < 4 or et.hour >= 20:
        return

    db = SessionLocal()
    try:
        result = run_step(db)
        logger.info("simulator auto-step: %s", result)
    except Exception as e:
        logger.error("simulator auto-step failed: %s", e)
    finally:
        db.close()


def run_pulse_scan() -> None:
    """Run market pulse scan every 5 min, fires Telegram alerts including
    pre-market and after-hours sessions. Skips deep night hours to save API calls."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        et = datetime.utcnow()
    # Run 4 AM ET (pre-market) through 8 PM ET (after-hours close), Mon-Fri
    if et.weekday() >= 5:
        return
    if et.hour < 4 or et.hour >= 20:
        return
    try:
        from backend.app.services.market_pulse_service import scan_market
        result = scan_market()
        logger.info("Pulse scan: %d signals, %d high-conviction",
                    len(result.get("signals", [])),
                    sum(1 for s in result.get("signals", []) if s.get("high_conviction")))
    except Exception as e:
        logger.error("Pulse scan failed: %s", e)
