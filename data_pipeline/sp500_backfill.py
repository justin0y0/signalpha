"""
S&P 500 Historical Earnings Backfill
=====================================
Expands the platform from ~150 tickers to the full S&P 500.

Usage:
  docker compose exec backend python -m data_pipeline.sp500_backfill            # full run
  docker compose exec backend python -m data_pipeline.sp500_backfill calendar   # step 1 only
  docker compose exec backend python -m data_pipeline.sp500_backfill features   # step 2 only
  docker compose exec backend python -m data_pipeline.sp500_backfill train      # step 3 only

Checkpointed: safe to kill and restart — skips events already processed.
"""
from __future__ import annotations
import sys, time
from datetime import date, timedelta
import pandas as pd
from sqlalchemy import select
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import (
    EarningsEvent, FinancialMetric, PriceFeature, Prediction
)
from backend.app.db.session import SessionLocal
from data_pipeline.collector import DataCollector


def _json_safe(obj):
    """Recursively convert non-JSON-serializable types (Timestamp, date, etc)."""
    import pandas as pd
    import datetime
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
        return obj.isoformat() if hasattr(obj, 'isoformat') else str(obj)
    if hasattr(obj, 'item'):   # numpy scalars
        return obj.item()
    return obj

logger = get_logger(__name__)
settings = get_settings()
collector = DataCollector(settings)


def _session():
    return SessionLocal()

def _upsert(session, model_cls, identity, values):
    from sqlalchemy import select
    instance = session.execute(select(model_cls).filter_by(**identity)).scalar_one_or_none()
    if instance is None:
        instance = model_cls(**identity, **values)
        session.add(instance)
    else:
        for k, v in values.items():
            setattr(instance, k, v)
    return instance


# ── STEP 1: S&P 500 ticker list ───────────────────────────────────────────────
def get_sp500_tickers() -> set[str]:
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            header=0
        )
        tickers = set(tables[0]["Symbol"].str.replace(".", "-", regex=False).str.upper())
        print(f"✓ {len(tickers)} S&P 500 tickers from Wikipedia")
        return tickers
    except Exception as e:
        print(f"⚠ Wikipedia failed ({e}), using hardcoded top-100 S&P 500")
        return {
            "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","BRK-B","LLY","JPM",
            "UNH","V","XOM","TSLA","AVGO","PG","MA","JNJ","HD","COST","MRK","CVX",
            "ABBV","KO","PEP","BAC","WMT","NFLX","ORCL","CRM","ACN","AMD","LIN",
            "TMO","ABT","DHR","QCOM","TXN","MCD","PM","T","WFC","CSCO","GE","CAT",
            "NOW","INTU","IBM","AMGN","UPS","RTX","SPGI","BLK","GS","MS","HON","DE",
            "NEE","AMAT","ISRG","ELV","CI","MDLZ","ADP","REGN","C","MMC","ZTS","ETN",
            "BA","SYK","VRTX","PGR","GILD","CB","TJX","ADI","MO","SCHW","APD","SO",
            "DUK","SHW","ICE","CME","PLD","EQIX","PSA","AMT","CCI","AON","ITW","MMM",
            "EMR","NSC","CSX","UNP","FDX","GD","LMT","NOC","F","GM","INTC","SHOP",
        }


# ── STEP 2: Historical earnings calendar ──────────────────────────────────────
def backfill_calendar(sp500: set[str]) -> int:
    """Pull quarterly calendar back to 2015 from FMP, insert S&P 500 events."""

    with _session() as session:
        existing = set(session.execute(
            select(EarningsEvent.ticker, EarningsEvent.earnings_date)
        ).all())

    quarters: list[tuple[date, date]] = []
    y = 2015
    today = date.today()
    while y <= today.year + 1:
        for m in [1, 4, 7, 10]:
            qs = date(y, m, 1)
            qe = min((qs + timedelta(days=92)).replace(day=1) - timedelta(days=1), today)
            if qs > today:
                break
            quarters.append((qs, qe))
        y += 1

    print(f"\n── Step 1: Calendar backfill ({len(quarters)} quarters, 2015→today) ──")
    new_total = 0

    for i, (qs, qe) in enumerate(quarters):
        try:
            events = collector.collect_earnings_calendar(qs, qe)
            sp500_events = [e for e in events
                            if str(e.get("ticker","")).upper() in sp500]

            with _session() as session:
                for item in sp500_events:
                    ticker = str(item["ticker"]).upper()
                    key = (ticker, item["earnings_date"])
                    if key not in existing:
                        _upsert(session, EarningsEvent,
                                {"ticker": ticker, "earnings_date": item["earnings_date"]},
                                {k: v for k, v in item.items() if k not in ("ticker","earnings_date")})
                        existing.add(key)
                        new_total += 1
                session.commit()

            print(f"  [{(i+1)/len(quarters)*100:5.1f}%] {qs}→{qe}  "
                  f"got {len(sp500_events)} S&P500 events  |  {new_total} new total")
            time.sleep(0.3)

        except Exception as e:
            print(f"  ⚠ {qs}: {e}")
            time.sleep(3)

    print(f"✓ Calendar done — {new_total} new events inserted")
    return new_total


# ── STEP 3: Feature collection for events without features ────────────────────
def backfill_features(sp500: set[str]) -> None:
    """Collect ML features for S&P 500 events that don't have PriceFeature rows yet."""

    with _session() as session:
        has_features = set(session.execute(
            select(PriceFeature.ticker, PriceFeature.earnings_date)
        ).all())

        events = session.execute(
            select(EarningsEvent)
            .where(EarningsEvent.ticker.in_(list(sp500)))
            .order_by(EarningsEvent.earnings_date.asc())
        ).scalars().all()

    todo = [e for e in events if (e.ticker, e.earnings_date) not in has_features]
    total = len(todo)
    done_tickers = len({e.ticker for e in events} - {e.ticker for e in todo})

    print(f"\n── Step 2: Feature backfill ──")
    print(f"   Events total:    {len(events)}")
    print(f"   Already done:    {len(events) - total}")
    print(f"   Remaining:       {total}")
    print(f"   Unique tickers with all features: {done_tickers}")

    ok = fail = 0
    for i, event in enumerate(todo):
        try:
            snap = collector.collect_event_snapshot(
                event.ticker, event.earnings_date, event.sector
            )
            raw = snap.get("raw", {})
            eng  = snap.get("engineered", {})

            with _session() as session:
                _upsert(session, FinancialMetric,
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
                        "raw_payload": _json_safe(raw),
                    })
                if eng:
                    _upsert(session, PriceFeature,
                        {"ticker": event.ticker, "earnings_date": event.earnings_date},
                        eng)
                session.commit()
            ok += 1

        except Exception as e:
            fail += 1
            logger.warning("Feature fail: %s %s — %s", event.ticker, event.earnings_date, e)

        if (i + 1) % 20 == 0 or (i + 1) == total:
            pct = (i + 1) / total * 100
            eta_min = ((total - i - 1) * 2) // 60  # rough 2s/event
            print(f"  [{pct:5.1f}%] {i+1}/{total}  ok={ok} fail={fail}"
                  f"  ETA ~{eta_min}min  last={event.ticker}")

    print(f"✓ Feature backfill done — ok={ok} fail={fail}")


# ── STEP 4: Predictions + retrain ─────────────────────────────────────────────
def run_train() -> None:
    print("\n── Step 3: Run predictions on all new events ──")
    from data_pipeline.jobs import run_predictions, retrain_models
    run_predictions()
    print("\n── Step 4: Retrain models on expanded dataset ──")
    retrain_models()
    print("\n✓ Training complete! Check /performance and /track-record for updated metrics.")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    print("=" * 60)
    print("  Signalpha — S&P 500 Historical Backfill")
    print(f"  Step: {step}")
    print("=" * 60)

    sp500 = get_sp500_tickers()

    if step in ("all", "calendar"):
        backfill_calendar(sp500)

    if step in ("all", "features"):
        backfill_features(sp500)

    if step in ("all", "train"):
        run_train()

    print("\n✓ Backfill complete.")
