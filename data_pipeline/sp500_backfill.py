"""
S&P 500 Historical Earnings Backfill — yfinance edition
=========================================================
Uses yfinance (free, no API key) to get historical earnings dates for all S&P 500 stocks.

Usage:
  docker compose exec backend python -m data_pipeline.sp500_backfill            # full run
  docker compose exec backend python -m data_pipeline.sp500_backfill calendar   # step 1 only
  docker compose exec backend python -m data_pipeline.sp500_backfill features   # step 2 only
  docker compose exec backend python -m data_pipeline.sp500_backfill train      # step 3 only

Checkpointed: safe to kill and restart.
"""
from __future__ import annotations
import sys, time, datetime
import pandas as pd
import yfinance as yf
from sqlalchemy import select
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import EarningsEvent, FinancialMetric, PriceFeature
from backend.app.db.session import SessionLocal
from data_pipeline.collector import DataCollector

logger = get_logger(__name__)
settings = get_settings()
collector = DataCollector(settings)

# Valid columns for PriceFeature table (everything else → feature_payload)
PRICE_FEATURE_COLS = {
    'price_1d_pre','price_5d_pre','price_10d_pre','price_20d_pre','price_60d_pre',
    'ret_1d_pre','ret_5d_pre','ret_10d_pre','ret_20d_pre','ret_60d_pre',
    'atm_iv','iv_rank','iv_percentile','iv_crush_hist','expected_move_pct',
    'volume_anomaly','rsi_14','macd','macd_signal','bollinger_position',
    'dist_52w_high','dist_52w_low','feature_payload',
}

SECTOR_MAP = {
    "Technology": "Technology", "Financial Services": "Financial Services",
    "Healthcare": "Healthcare", "Consumer Cyclical": "Consumer Cyclical",
    "Consumer Defensive": "Consumer Defensive", "Industrials": "Industrials",
    "Energy": "Energy", "Communication Services": "Communication Services",
    "Basic Materials": "Basic Materials", "Real Estate": "Real Estate",
    "Utilities": "Utilities",
}


def _session():
    return SessionLocal()


def _upsert(session, model_cls, identity, values):
    instance = session.execute(
        select(model_cls).filter_by(**identity)
    ).scalar_one_or_none()
    if instance is None:
        instance = model_cls(**identity, **values)
        session.add(instance)
    else:
        for k, v in values.items():
            setattr(instance, k, v)
    return instance


def _json_safe(obj):
    """Recursively convert non-JSON-serializable types including NaN/inf/numpy."""
    import math
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
        return obj.isoformat() if hasattr(obj, "isoformat") else str(obj)
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, (int, str)):
        return obj
    # numpy scalars and anything with .item()
    try:
        v = obj.item()
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v
    except (AttributeError, ValueError):
        pass
    try:
        return str(obj)
    except Exception:
        return None


# ── STEP 1: Get S&P 500 tickers ───────────────────────────────────────────────
def get_sp500_tickers() -> list[str]:
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        )
        tickers = tables[0]["Symbol"].str.replace(".", "-", regex=False).str.upper().tolist()
        print(f"✓ Got {len(tickers)} S&P 500 tickers from Wikipedia")
        return tickers
    except Exception as e:
        print(f"⚠ Wikipedia failed ({e}), using top-100 fallback")
        return [
            "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","BRK-B","LLY","JPM",
            "UNH","V","XOM","TSLA","AVGO","PG","MA","JNJ","HD","COST","MRK","CVX",
            "ABBV","KO","PEP","BAC","WMT","NFLX","ORCL","CRM","ACN","AMD","LIN",
            "TMO","ABT","DHR","QCOM","TXN","MCD","PM","T","WFC","CSCO","GE","CAT",
            "NOW","INTU","IBM","AMGN","UPS","RTX","SPGI","BLK","GS","MS","HON","DE",
            "NEE","AMAT","ISRG","ELV","CI","MDLZ","ADP","REGN","C","MMC","ZTS","ETN",
            "BA","SYK","VRTX","PGR","GILD","CB","TJX","ADI","MO","SCHW","APD","SO",
            "DUK","SHW","ICE","CME","PLD","EQIX","PSA","AMT","CCI","AON","ITW","MMM",
            "EMR","NSC","CSX","UNP","FDX","GD","LMT","NOC","F","GM","INTC","SHOP",
        ]


# ── STEP 2: Calendar via yfinance ─────────────────────────────────────────────
def backfill_calendar(tickers: list[str]) -> int:
    """Get historical earnings dates from yfinance for each ticker."""
    print(f"\n── Step 1: Calendar backfill via yfinance ({len(tickers)} tickers) ──")

    with _session() as session:
        existing = set(session.execute(
            select(EarningsEvent.ticker, EarningsEvent.earnings_date)
        ).all())

    new_total = 0
    cutoff = datetime.date(2014, 1, 1)

    for i, ticker in enumerate(tickers):
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            sector = SECTOR_MAP.get(info.get("sector", ""), info.get("sector"))
            company = info.get("longName") or info.get("shortName") or ticker

            # yfinance earnings_dates goes back ~4 years
            dates_df = t.earnings_dates
            if dates_df is None or len(dates_df) == 0:
                continue

            dates_df = dates_df.reset_index()
            date_col = dates_df.columns[0]

            with _session() as session:
                for _, row in dates_df.iterrows():
                    try:
                        ed = pd.to_datetime(row[date_col]).date()
                        if ed < cutoff or ed > datetime.date.today():
                            continue
                        key = (ticker.upper(), ed)
                        if key in existing:
                            continue
                        _upsert(session, EarningsEvent,
                            {"ticker": ticker.upper(), "earnings_date": ed},
                            {
                                "company_name": company,
                                "sector": sector,
                                "source": "yfinance",
                                "exchange": info.get("exchange"),
                                "market_cap": info.get("marketCap"),
                            })
                        existing.add(key)
                        new_total += 1
                    except Exception:
                        continue
                session.commit()

            pct = (i + 1) / len(tickers) * 100
            if (i + 1) % 10 == 0 or (i + 1) == len(tickers):
                print(f"  [{pct:5.1f}%] {i+1}/{len(tickers)}  new={new_total}  last={ticker}")

            time.sleep(0.3)

        except Exception as e:
            print(f"  ⚠ {ticker}: {e}")
            time.sleep(1)

    print(f"✓ Calendar done — {new_total} new events added")
    return new_total


# ── STEP 3: Features for events without them ──────────────────────────────────
def backfill_features(tickers: list[str]) -> None:
    ticker_set = set(t.upper() for t in tickers)

    with _session() as session:
        has_features = set(session.execute(
            select(PriceFeature.ticker, PriceFeature.earnings_date)
        ).all())
        events = session.execute(
            select(EarningsEvent)
            .where(EarningsEvent.ticker.in_(list(ticker_set)))
            .order_by(EarningsEvent.earnings_date.asc())
        ).scalars().all()

    todo = [e for e in events if (e.ticker, e.earnings_date) not in has_features]
    total = len(todo)
    print(f"\n── Step 2: Feature backfill — {total} events need features ──")

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
                    safe_eng = _json_safe(eng)
                    # Only pass columns that exist in PriceFeature
                    pf_vals = {k: v for k, v in safe_eng.items() if k in PRICE_FEATURE_COLS}
                    # Overflow unknown keys into feature_payload JSON column
                    overflow = {k: v for k, v in safe_eng.items() if k not in PRICE_FEATURE_COLS}
                    if overflow:
                        pf_vals['feature_payload'] = overflow
                    _upsert(session, PriceFeature,
                        {"ticker": event.ticker, "earnings_date": event.earnings_date},
                        pf_vals)
                session.commit()
            ok += 1

        except Exception as e:
            fail += 1
            if fail % 20 == 0:
                logger.warning("Feature fail count=%d last: %s %s — %s",
                               fail, event.ticker, event.earnings_date, e)

        if (i + 1) % 25 == 0 or (i + 1) == total:
            pct = (i + 1) / total * 100
            eta = int((total - i - 1) * 2 / 60)
            print(f"  [{pct:5.1f}%] {i+1}/{total}  ok={ok} fail={fail}  "
                  f"ETA~{eta}min  {event.ticker} {event.earnings_date}")

    print(f"✓ Feature backfill done — ok={ok} fail={fail}")


# ── STEP 4: Predictions + retrain ─────────────────────────────────────────────
def run_train() -> None:
    print("\n── Step 3: Predictions + retrain ──")
    from data_pipeline.jobs import run_predictions, retrain_models
    run_predictions()
    print("  ✓ Predictions done")
    retrain_models()
    print("  ✓ Model retrained — check /performance for new metrics")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    print("=" * 60)
    print("  Signalpha — S&P 500 Backfill (yfinance edition)")
    print(f"  Step: {step}")
    print("=" * 60)

    tickers = get_sp500_tickers()

    if step in ("all", "calendar"):
        backfill_calendar(tickers)
    if step in ("all", "features"):
        backfill_features(tickers)
    if step in ("all", "train"):
        run_train()

    print("\n✓ All done.")
