"""When each report came out, and by how much it beat or missed.

Why this exists
---------------
`earnings_events.report_time` was NULL for every one of 5,730 events, and the outcome
calculation always measured the reaction on the bar dated `earnings_date`. About 40% of
large-cap reports come out after the close, where that bar is the session BEFORE the
news. So the stored "T+1 reaction" for those events was an ordinary pre-report day, and
every label, band and model built on it carried the error.

yfinance's earnings calendar carries a timestamp per report (pre-market vs after-close
is unambiguous from the hour) along with the EPS estimate, the reported figure and the
surprise. This module stores those, stamps `report_time` onto our events, and can
recompute every outcome from the right session.

    python -m data_pipeline.earnings_timing sync                 # all tracked tickers
    python -m data_pipeline.earnings_timing sync --recent        # only names reporting soon/recently
    python -m data_pipeline.earnings_timing recompute-outcomes   # rewrite outcomes from the right session
"""
from __future__ import annotations

import argparse
import logging
import math
import time
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import select, text

from backend.app.db.models import EarningsEvent, Outcome
from backend.app.db.session import SessionLocal
from data_pipeline.sources.yfinance_client import YFinanceClient

log = logging.getLogger(__name__)
NY = "America/New_York"
MATCH_DAYS = 3


def classify(ts: pd.Timestamp) -> str:
    """BMO before the open, AMC from the close on, DMH (during market hours) between."""
    hm = ts.hour + ts.minute / 60
    return "BMO" if hm < 9.5 else "AMC" if hm >= 16 else "DMH"


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def fetch(ticker: str) -> list[dict]:
    import yfinance as yf

    frame = yf.Ticker(ticker).get_earnings_dates(limit=100)
    if frame is None or frame.empty:
        return []
    out = []
    for ts, row in frame.iterrows():
        ts = pd.Timestamp(ts)
        ts = ts.tz_convert(NY) if ts.tzinfo else ts.tz_localize(NY)
        out.append({
            "ticker": ticker, "report_date": ts.date(), "report_ts": ts.to_pydatetime(),
            "report_time": classify(ts),
            "eps_estimate": _num(row.get("EPS Estimate")), "eps_actual": _num(row.get("Reported EPS")),
            "surprise_pct": _num(row.get("Surprise(%)")),
        })
    return out


def _tickers(recent: bool) -> list[str]:
    with SessionLocal() as s:
        q = select(EarningsEvent.ticker).distinct()
        if recent:
            today = date.today()
            q = q.where(EarningsEvent.earnings_date >= today - timedelta(days=10),
                        EarningsEvent.earnings_date <= today + timedelta(days=21))
        return sorted(t for (t,) in s.execute(q).all())


def sync(recent: bool = False) -> dict:
    """Store timing + surprise rows, then stamp report_time on matching events."""
    tickers = _tickers(recent)
    stored = failed = 0
    for i, t in enumerate(tickers, 1):
        try:
            rows = fetch(t)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            log.warning("timing %s: %s", t, exc)
            continue
        with SessionLocal() as s:
            for r in rows:
                s.execute(text("""
                    INSERT INTO earnings_surprises (ticker, report_date, report_ts, report_time,
                        eps_estimate, eps_actual, surprise_pct, updated_at)
                    VALUES (:ticker, :report_date, :report_ts, :report_time, :eps_estimate, :eps_actual,
                            :surprise_pct, NOW())
                    ON CONFLICT (ticker, report_date) DO UPDATE SET
                        report_ts=EXCLUDED.report_ts, report_time=EXCLUDED.report_time,
                        eps_estimate=COALESCE(EXCLUDED.eps_estimate, earnings_surprises.eps_estimate),
                        eps_actual=COALESCE(EXCLUDED.eps_actual, earnings_surprises.eps_actual),
                        surprise_pct=COALESCE(EXCLUDED.surprise_pct, earnings_surprises.surprise_pct),
                        updated_at=NOW()"""), r)
            s.commit()
        stored += len(rows)
        time.sleep(0.35)
        if i % 30 == 0:
            log.info("timing [%s/%s] rows=%s failed=%s", i, len(tickers), stored, failed)
    stamped = stamp_events()
    return {"tickers": len(tickers), "rows": stored, "failed": failed, **stamped}


def stamp_events() -> dict:
    """Give each event the report_time of the nearest calendar row within a few days."""
    with SessionLocal() as s:
        res = s.execute(text(f"""
            UPDATE earnings_events e SET report_time = m.report_time
            FROM (
                SELECT DISTINCT ON (e2.id) e2.id, s.report_time
                FROM earnings_events e2
                JOIN earnings_surprises s ON s.ticker = e2.ticker
                 AND s.report_date BETWEEN e2.earnings_date - {MATCH_DAYS} AND e2.earnings_date + {MATCH_DAYS}
                ORDER BY e2.id, abs(s.report_date - e2.earnings_date)
            ) m
            WHERE m.id = e.id AND e.report_time IS DISTINCT FROM m.report_time"""))
        s.commit()
        counts = dict(s.execute(text(
            "SELECT coalesce(report_time,'unknown'), count(*) FROM earnings_events GROUP BY 1")).all())
        off = s.execute(text(f"""
            SELECT count(*) FROM earnings_events e WHERE EXISTS (
                SELECT 1 FROM earnings_surprises s WHERE s.ticker=e.ticker
                 AND s.report_date BETWEEN e.earnings_date - {MATCH_DAYS} AND e.earnings_date + {MATCH_DAYS})
              AND NOT EXISTS (SELECT 1 FROM earnings_surprises s WHERE s.ticker=e.ticker AND s.report_date=e.earnings_date)
        """)).scalar()
    return {"stamped": res.rowcount, "report_times": counts, "matched_on_a_different_day": off}


def _anchor(s, ticker: str, d: date) -> tuple[date, str | None]:
    """The calendar's own date for this report when ours is off by a day or two."""
    row = s.execute(text(f"""
        SELECT report_date, report_time FROM earnings_surprises
        WHERE ticker=:t AND report_date BETWEEN :a AND :b
        ORDER BY abs(report_date - :d) LIMIT 1"""),
        {"t": ticker, "d": d, "a": d - timedelta(days=MATCH_DAYS), "b": d + timedelta(days=MATCH_DAYS)}).first()
    return (row.report_date, row.report_time) if row else (d, None)


def recompute_outcomes() -> dict:
    """Rewrite every outcome from the session that actually traded the report."""
    yf = YFinanceClient()
    today = date.today()
    with SessionLocal() as s:
        events = s.execute(select(EarningsEvent.ticker, EarningsEvent.earnings_date)
                           .where(EarningsEvent.earnings_date < today)
                           .order_by(EarningsEvent.ticker, EarningsEvent.earnings_date)).all()
    by_ticker: dict[str, list[date]] = {}
    for t, d in events:
        by_ticker.setdefault(t, []).append(d)
    written = moved = skipped = 0
    for n, (ticker, dates) in enumerate(by_ticker.items(), 1):
        try:
            hist = yf.history(ticker, start=(min(dates) - timedelta(days=15)).isoformat(),
                              end=(today + timedelta(days=1)).isoformat())
        except Exception as exc:  # noqa: BLE001
            log.warning("history %s: %s", ticker, exc)
            skipped += len(dates)
            continue
        if hist is None or hist.empty:
            skipped += len(dates)
            continue
        with SessionLocal() as s:
            for d in dates:
                anchor, rt = _anchor(s, ticker, d)
                out = yf.outcome_snapshot(hist, datetime.combine(anchor, datetime.min.time()), rt)
                if not out or out.get("actual_t1_close_return") is None:
                    skipped += 1
                    continue
                row = s.execute(select(Outcome).where(Outcome.ticker == ticker, Outcome.earnings_date == d)).scalar_one_or_none()
                if row is None:
                    row = Outcome(ticker=ticker, earnings_date=d)
                    s.add(row)
                elif row.actual_t1_close_return is not None and abs(float(row.actual_t1_close_return) - out["actual_t1_close_return"]) > 1e-6:
                    moved += 1
                for k, v in out.items():
                    if v is not None and hasattr(row, k):
                        setattr(row, k, bool(v) if k == "gap_filled" else v)
                written += 1
            s.commit()
        time.sleep(0.25)
        if n % 25 == 0:
            log.info("outcomes [%s/%s] written=%s changed=%s skipped=%s", n, len(by_ticker), written, moved, skipped)
    return {"tickers": len(by_ticker), "written": written, "reaction_changed": moved, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sync", "stamp", "recompute-outcomes"])
    ap.add_argument("--recent", action="store_true")
    a = ap.parse_args()
    if a.cmd == "sync":
        print(sync(a.recent))
    elif a.cmd == "stamp":
        print(stamp_events())
    else:
        print(recompute_outcomes())
