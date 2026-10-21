from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import and_, desc, func, select
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
    fresh: dict[str, set] = {}
    for item in items:
        fresh.setdefault(item["ticker"], set()).add(item["earnings_date"])
    with _session() as session:
        for item in items:
            identity = {"ticker": item["ticker"], "earnings_date": item["earnings_date"]}
            values = {k: v for k, v in item.items() if k not in identity}
            _upsert(session, EarningsEvent, identity, values)
        # FMP reschedules reports. Upserting the new date used to leave the old one in
        # place, so the calendar listed the same report twice and the stale copy got its
        # own prediction. Drop a future event only when the feed still lists that ticker
        # but on a nearby different date — a ticker missing from one fetch is left alone.
        stale = session.execute(
            select(EarningsEvent.ticker, EarningsEvent.earnings_date)
            .where(EarningsEvent.earnings_date >= start, EarningsEvent.earnings_date <= end,
                   EarningsEvent.ticker.in_(list(fresh)))
        ).all()
        removed = 0
        for ticker, d in stale:
            if d in fresh[ticker] or not any(abs((d - nd).days) <= 10 for nd in fresh[ticker]):
                continue
            for model in (Prediction, PriceFeature, FinancialMetric, EarningsEvent):
                session.query(model).filter(model.ticker == ticker, model.earnings_date == d).delete()
            removed += 1
            logger.info("calendar: %s moved off %s — stale event removed", ticker, d)
        session.commit()
    logger.info("Finished earnings calendar collection with %s rows (%s rescheduled removed)", len(items), removed)


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
                snapshot = collector.collect_event_snapshot(event.ticker, event.earnings_date, event.sector, event.report_time)
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


def sync_earnings_timing() -> None:
    """Report times (pre-market / after-close) and EPS surprises for names reporting
    around now. Outcomes, Arena cut-offs and the paper account all depend on knowing
    which session trades a report."""
    try:
        from data_pipeline.earnings_timing import sync
        logger.info("Earnings timing: %s", sync(recent=True))
    except Exception as exc:  # noqa: BLE001
        logger.error("Earnings timing sync failed: %s", exc)


def run_predictions() -> None:
    logger.info("Starting prediction generation job")
    # A snapshot taken weeks ahead and never refreshed gave live predictions stale
    # prices; rebuild the price/market features of every upcoming report first.
    try:
        from data_pipeline.rebuild_pit_features import run as _rebuild
        logger.info("Upcoming features refreshed: %s", _rebuild(upcoming_only=True))
    except Exception as exc:  # noqa: BLE001
        logger.error("Upcoming feature refresh failed: %s", exc)
    from data_pipeline.recalibrate_predictions import calibrate_live, load_temperature
    temperature = load_temperature()
    if temperature is None:
        logger.warning("no calibration.json — live probabilities will be written uncalibrated")
    from backend.app.services.flat_band import load_flat_bands
    from data_pipeline.move_model import load_live, predict_live
    from models.dataset import expand_feature_payload
    from models.features import add_derived
    move_bundle = load_live()
    if move_bundle is None:
        logger.warning("no move_model.joblib — prob_move falls back to the ensemble head")
    with _session() as session:
        events = session.execute(
            select(EarningsEvent, PriceFeature)
            .join(PriceFeature, and_(EarningsEvent.ticker == PriceFeature.ticker, EarningsEvent.earnings_date == PriceFeature.earnings_date))
            .where(EarningsEvent.earnings_date >= date.today())
            .order_by(EarningsEvent.earnings_date.asc())
        ).all()
        bands = load_flat_bands(session, list({e.ticker for e, _ in events})) if events else {}
        written = 0
        for event, price_feature in events:
            try:
                model = registry.load_for_sector(event.sector or "general")
                # Flatten exactly as training does. Building the frame straight from the
                # nested payload left every `sector_relative.*` column NaN at serving time
                # while the model had been trained with them populated.
                feature_df = expand_feature_payload(
                    pd.DataFrame([{"feature_payload": price_feature.feature_payload or {}}]))
                add_derived(feature_df, band=pd.Series([bands.get(event.ticker, np.nan)]))
                prediction = model.predict(feature_df, current_price=(price_feature.feature_payload or {}).get("price_t0"))
                raw = prediction["direction_probabilities"]
                # Same scale as the history beside it: raw output kept, display columns
                # temperature-scaled (argmax unchanged). See recalibrate_predictions.py.
                shown = (calibrate_live(raw["up"], raw["flat"], raw["down"], temperature)
                         if temperature else (raw["up"], raw["flat"], raw["down"]))
                key_drivers = model.explain_top_features(feature_df, top_n=5)
                similar_cases = model.find_similar_cases(feature_df, top_k=3)
                _upsert(
                    session,
                    Prediction,
                    {"ticker": event.ticker, "earnings_date": event.earnings_date},
                    {
                        "sector": event.sector,
                        "direction_prob_up": shown[0],
                        "direction_prob_flat": shown[1],
                        "direction_prob_down": shown[2],
                        "raw_prob_up": raw["up"],
                        "raw_prob_flat": raw["flat"],
                        "raw_prob_down": raw["down"],
                        "confidence_score": max(shown),
                        "prob_move": (predict_live(move_bundle, feature_df) if move_bundle
                                      else prediction.get("prob_move")),
                        # Made before the report by a model trained only on earlier
                        # events — genuinely ex-ante, so it belongs in the record.
                        "is_out_of_sample": True,
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
    # Direction lean for every upcoming report (experimental; see direction_lean.py).
    try:
        from data_pipeline.direction_lean import score_upcoming
        logger.info("Direction leans written: %s", score_upcoming())
    except Exception as exc:  # noqa: BLE001
        logger.error("Direction lean failed: %s", exc)


def collect_post_earnings_results() -> None:
    logger.info("Starting post-earnings outcome collection job")
    lower = date.today() - timedelta(days=30)
    upper = date.today() - timedelta(days=1)
    with _session() as session:
        # With the whole US list a 30-day window holds well over a thousand reports. A
        # report needs collecting when it has no outcome yet, or once a day while its
        # T+20 leg is still filling in -- not every hour.
        events = session.execute(
            select(EarningsEvent)
            .outerjoin(Outcome, and_(Outcome.ticker == EarningsEvent.ticker, Outcome.earnings_date == EarningsEvent.earnings_date))
            .where(EarningsEvent.earnings_date >= lower, EarningsEvent.earnings_date <= upper)
            .where((Outcome.id.is_(None)) | (Outcome.actual_t1_close_return.is_(None))
                   | ((Outcome.actual_t20_return.is_(None)) & (func.date(Outcome.updated_at) < date.today())))
            .order_by(EarningsEvent.earnings_date.desc())
        ).scalars()
        event_list = list(events)
        written = 0
        for event in event_list:
            try:
                outcome = collector.collect_post_earnings_outcome(event.ticker, event.earnings_date, event.report_time)
                if not outcome:
                    continue
                _upsert(session, Outcome, {"ticker": event.ticker, "earnings_date": event.earnings_date}, outcome)
                session.commit()
                written += 1
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                logger.exception("Outcome collection failed for %s on %s: %s", event.ticker, event.earnings_date, exc)
    logger.info("Finished post-earnings outcome collection: %s/%s events written", written, len(event_list))
    if written:
        from data_pipeline.compute_flat_bands import compute as compute_bands
        logger.info("Bands for new outcomes: %s", compute_bands(missing_only=True))


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


def retrain_full() -> None:
    """Monthly: the whole chain, not just the models.

    The schedule used to call retrain_models alone, which replaced the served models
    while the stored history, prob_move and the calibration temperature stayed fitted to
    the previous ones — the calendar and the record drifted apart until someone reran
    the rest by hand. Same four steps as scripts/retrain_pipeline.sh.
    """
    from data_pipeline.move_model import run as run_move_model
    from data_pipeline.recalibrate_predictions import recalibrate
    from data_pipeline.regenerate_predictions import regenerate

    retrain_models()
    logger.info("retrain_full: regenerate %s", regenerate())
    logger.info("retrain_full: move model AUC %s", run_move_model().get("auc"))
    logger.info("retrain_full: recalibrate %s", recalibrate().get("after"))
    run_predictions()


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


def seal_arena_forecasts() -> None:
    """Earnings Arena: seal every forecaster's call for reports in the next few days."""
    from backend.app.services.arena_service import seal_due
    db = SessionLocal()
    try:
        logger.info("Arena seal: %s", seal_due(db))
    except Exception as exc:  # noqa: BLE001
        logger.error("Arena seal failed: %s", exc)
    finally:
        db.close()


def resolve_arena_forecasts() -> None:
    """Earnings Arena: grade sealed calls whose T+1 outcome has landed."""
    from backend.app.services.arena_service import resolve_due
    db = SessionLocal()
    try:
        logger.info("Arena resolve: %s", resolve_due(db))
    except Exception as exc:  # noqa: BLE001
        logger.error("Arena resolve failed: %s", exc)
    finally:
        db.close()


def freeze_and_grade_receipts() -> None:
    """Receipts: freeze the standing call of every report whose bell has rung, grade the rest."""
    from backend.app.services.receipts_service import freeze_due, grade_due
    db = SessionLocal()
    try:
        logger.info("Receipts: %s %s", freeze_due(db), grade_due(db))
    except Exception as exc:  # noqa: BLE001
        logger.error("Receipts failed: %s", exc)
    finally:
        db.close()


def issue_direction_calls() -> None:
    """Direction book: after the open, write the calls for every report trading today."""
    from backend.app.services.direction_service import backfill_follow_gap, issue_due
    db = SessionLocal()
    try:
        logger.info("Direction calls: %s (follow_gap from reactions: %s)", issue_due(db), backfill_follow_gap(db))
    except Exception as exc:  # noqa: BLE001
        logger.error("Direction calls failed: %s", exc)
    finally:
        db.close()


def strategy_job(step: str) -> None:
    """Signals for the strategies beyond the direction rules (services/strategies.py)."""
    from backend.app.services import strategies as st
    db = SessionLocal()
    try:
        fn = {"pre_run": st.gen_pre_run, "sue_gap": st.gen_sue_gap, "insider": st.gen_insider, "targets": st.gen_targets}[step]
        logger.info("Strategy %s: %s", step, fn(db))
    except Exception as exc:  # noqa: BLE001
        logger.error("Strategy %s failed: %s", step, exc)
    finally:
        db.close()


def autopilot_job(step: str) -> None:
    """Autopilot (services/autotrade_service.py): the open, entries, on-close orders, the late fallback, fills and marks."""
    from backend.app.services import autotrade_service as at
    db = SessionLocal()
    try:
        fn = {"open": at.run_open, "entries": at.run_entries, "closes": at.run_closes, "flatten": at.flatten_late,
              "reconcile": at.reconcile, "closes_late": lambda d: at.run_closes(d, phase="late")}[step]
        result = fn(db)
        if step != "reconcile" or result.get("updated"):
            logger.info("Autopilot %s: %s", step, result)
    except Exception as exc:  # noqa: BLE001
        logger.error("Autopilot %s failed: %s", step, exc)
    finally:
        db.close()


def refresh_market_snapshot() -> None:
    """Markets page: last price and change for every trained-tier name."""
    from backend.app.services.markets_service import refresh_snapshot
    try:
        logger.info("Market snapshot: %s", refresh_snapshot())
    except Exception as exc:  # noqa: BLE001
        logger.error("Market snapshot failed: %s", exc)


def sync_universe_calendar() -> None:
    """Upcoming reports for every trained-tier name, from the NASDAQ earnings calendar."""
    from data_pipeline.universe import sync_calendar
    try:
        logger.info("Universe calendar: %s", sync_calendar())
    except Exception as exc:  # noqa: BLE001
        logger.error("Universe calendar failed: %s", exc)


def alert_follow_through() -> None:
    """Telegram ping when a report gaps up beyond the Playbook threshold.

    The one direction call the product makes is only useful near the open of the
    reaction day, so it is pushed rather than left for someone to find on the site.
    One alert per ticker per day (redis); without redis nothing is sent, because an
    un-deduplicated job on a 15-minute schedule would spam every subscriber.
    """
    from backend.app.services import oracle_service
    from backend.app.services.flat_band import load_flat_bands
    from backend.app.services.playbook_service import SIGNAL_K, signal_summary
    from backend.app.services.simulation_service import _market_status, _reaction_gap

    if _market_status().get("status") != "OPEN" or oracle_service._rc is None:
        return
    today = date.today()
    sent = 0
    with _session() as session:
        events = session.execute(
            select(EarningsEvent).where(EarningsEvent.earnings_date >= today - timedelta(days=4),
                                        EarningsEvent.earnings_date <= today)
        ).scalars().all()
        if not events:
            return
        bands = load_flat_bands(session, sorted({e.ticker for e in events}))
        summary = signal_summary(session)
        for e in events:
            band = bands.get(e.ticker)
            key = f"ft:alert:{e.ticker}:{today.isoformat()}"
            if not band or oracle_service._rc.exists(key):
                continue
            try:
                reaction = _reaction_gap(e.ticker, e.earnings_date, e.report_time)
            except Exception:  # noqa: BLE001
                reaction = None
            if not reaction or reaction[0] != today or reaction[1] <= SIGNAL_K * band:
                continue
            gap = reaction[1]
            oracle_service._rc.setex(key, 3 * 86400, "1")
            oracle_service._push(
                f"📈 *FOLLOW-THROUGH · {e.ticker}*\n\n"
                f"Opened *{gap:+.1%}* on earnings — {gap / band:.1f}× its usual ±{band:.1%} move.\n"
                f"History: bought at that day's close, {summary['hit']:.0%} of gaps this size were "
                f"higher {summary['hold']} sessions later (avg {summary['mean']:+.1%}, n={summary['n']}; "
                f"all reports {summary['baseline_hit']:.0%}).\n\n"
                f"_Research, not advice. Long-only signal; big gap-downs do not keep falling._\n"
                f"[Playbook](https://signalpha.app/strategy)"
            )
            sent += 1
    logger.info("Follow-through alerts: %s sent", sent)
