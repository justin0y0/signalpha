"""Rebuild every price/market feature from bars strictly before the reaction session.

Why this exists
---------------
The feature history was assembled in two batches with opposite conventions:

  * one cut features off the day BEFORE `earnings_date` and labelled the reaction on
    `earnings_date` — right for pre-market reports, wrong label for after-close ones;
  * the other cut features off ON `earnings_date` and labelled the next session — right
    for after-close reports, but for a pre-market report the features contained the
    reaction itself (`ret_1d_pre` == the label for ~40% of pre-market events since 2020).

While the labels were wrong the two errors hid each other. Once the labels were moved
to the correct session (earnings_timing.recompute_outcomes) the second batch showed up
as a "pre-report" direction model with 81% top-decile accuracy — a leak, not a signal.

A third problem rode along: events collected live were snapshotted once, sometimes
months ahead, and never refreshed, so their "pre-report" prices were stale.

One rule replaces all of it: a feature may use bars dated strictly before the session
that traded the report (`outcomes.reaction_date`). For a report still to come, that is
every bar available today. Slow macro series (yields, fed funds, CPI, PCE) are left as
stored: a day's shift in them carries no information about one stock's reaction.

    python -m data_pipeline.rebuild_pit_features            # every event
    python -m data_pipeline.rebuild_pit_features --upcoming # only reports still to come
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from scipy.stats import percentileofscore
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from data_pipeline.collector import SECTOR_ETF_MAP
from data_pipeline.sources.yfinance_client import YFinanceClient

log = logging.getLogger(__name__)
MARKET = ("SPY", "QQQ", "^VIX", "^VIX9D", "^VIX3M", "HYG", "LQD")
WINDOW_DAYS = 420


class Bars:
    """Daily bars for many symbols, each downloaded once."""

    def __init__(self, start: date):
        self.yf = YFinanceClient()
        self.start = start
        self.cache: dict[str, pd.DataFrame] = {}

    def get(self, symbol: str) -> pd.DataFrame:
        if symbol not in self.cache:
            try:
                frame = self.yf.history(symbol, start=self.start.isoformat(),
                                        end=(date.today() + timedelta(days=1)).isoformat())
            except Exception as exc:  # noqa: BLE001
                log.warning("bars %s: %s", symbol, exc)
                frame = pd.DataFrame()
            if frame is not None and not frame.empty:
                frame = frame.sort_values("date").reset_index(drop=True)
            self.cache[symbol] = frame if frame is not None else pd.DataFrame()
            time.sleep(0.2)
        return self.cache[symbol]

    def before(self, symbol: str, cutoff: date, days: int = WINDOW_DAYS) -> pd.DataFrame:
        frame = self.get(symbol)
        if frame.empty:
            return frame
        hi = int(np.searchsorted(frame["date"].values, np.datetime64(pd.Timestamp(cutoff)), side="left"))
        lo = int(np.searchsorted(frame["date"].values, np.datetime64(pd.Timestamp(cutoff) - pd.Timedelta(days=days)), side="left"))
        return frame.iloc[lo:hi]


def _trailing(frame: pd.DataFrame, window: int) -> float | None:
    if frame.empty or len(frame) <= window:
        return None
    close = frame["Close"].astype(float).to_numpy()
    return float(close[-1] / close[-(window + 1)] - 1) if close[-(window + 1)] else None


def _last(frame: pd.DataFrame) -> float | None:
    return None if frame.empty else float(frame["Close"].iloc[-1])


def _ratio(a, b) -> float | None:
    if a is None or b in (None, 0):
        return None
    return float(a) / float(b)


def features_asof(bars: Bars, ticker: str, sector: str | None, cutoff: date) -> dict:
    """Every rebuilt key, from bars dated strictly before `cutoff`."""
    yf = bars.yf
    hist = bars.before(ticker, cutoff)
    if hist.empty or len(hist) < 25:
        return {}
    out: dict = {}
    out.update(yf.price_window_snapshot(hist, datetime.combine(cutoff, datetime.min.time())))
    out.update(yf.technical_snapshot(hist))

    spy, qqq = bars.before("SPY", cutoff, 400), bars.before("QQQ", cutoff, 400)
    vix = bars.before("^VIX", cutoff, 400)
    spy_close = spy["Close"].astype(float) if not spy.empty else pd.Series(dtype=float)
    spy_price = float(spy_close.iloc[-1]) if len(spy_close) else None
    spy_200ma = float(spy_close.tail(200).mean()) if len(spy_close) >= 200 else None
    spy_20 = _trailing(spy, 20)
    hyg, lqd = _last(bars.before("HYG", cutoff, 400)), _last(bars.before("LQD", cutoff, 400))
    out.update({
        "spy_price": spy_price, "spy_200ma": spy_200ma,
        "spy_ret_1d": _trailing(spy, 1), "spy_ret_5d": _trailing(spy, 5), "spy_ret_20d": spy_20,
        "qqq_ret_1d": _trailing(qqq, 1), "qqq_ret_5d": _trailing(qqq, 5), "qqq_ret_20d": _trailing(qqq, 20),
        "vix": _last(vix), "vix9d": _last(bars.before("^VIX9D", cutoff, 400)),
        "vix3m": _last(bars.before("^VIX3M", cutoff, 400)),
        "hyg_lqd_spread": None if hyg is None or not lqd else hyg / max(lqd, 1e-9) - 1,
    })
    if spy_price is not None and spy_200ma is not None:
        out["bull_bear_regime"] = out["market_regime"] = 1 if spy_price > spy_200ma else -1
    vix_hist = vix["Close"].astype(float).tail(252).tolist() if not vix.empty else []
    if out["vix"] is not None and vix_hist:
        out["vix_percentile"] = percentileofscore(vix_hist, out["vix"], kind="weak") / 100.0

    rel = {}
    for name, etf in SECTOR_ETF_MAP.items():
        r = _trailing(bars.before(etf, cutoff, 400), 20)
        rel[name] = None if r is None or spy_20 is None else r - spy_20
    out["sector_relative"] = rel
    etf = SECTOR_ETF_MAP.get(sector or "")
    if etf:
        sh = bars.before(etf, cutoff, 60)
        peer = float(sh["Close"].iloc[-1] / sh["Close"].iloc[-21] - 1) if len(sh) > 20 else None
        out["sector_peer_median"] = out["sector_median_reaction"] = peer

    p0 = out.get("price_t0")
    out["pre_earn_momentum_20d"] = None if not _ratio(p0, out.get("price_20d_pre")) else _ratio(p0, out["price_20d_pre"]) - 1
    out["pre_earn_momentum_5d"] = None if not _ratio(p0, out.get("price_5d_pre")) else _ratio(p0, out["price_5d_pre"]) - 1
    out["relative_strength_vs_spy"] = (None if out.get("ret_20d_pre") is None or spy_20 is None
                                       else out["ret_20d_pre"] - spy_20)
    out["volume_anomaly"] = _ratio(out.get("volume_t1"), out.get("volume_20d_avg"))
    out["dist_52w_high"] = None if not _ratio(p0, out.get("high_52w")) else _ratio(p0, out["high_52w"]) - 1
    out["dist_52w_low"] = None if not _ratio(p0, out.get("low_52w")) else _ratio(p0, out["low_52w"]) - 1
    out.update(_reversion(bars, hist, sector, cutoff))
    out["features_asof"] = (hist["date"].iloc[-1]).date().isoformat()
    return {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in out.items()}


def _reversion(bars: Bars, hist: pd.DataFrame, sector: str | None, cutoff: date) -> dict:
    """Daily Avellaneda-Lee s-score and the stock-specific run-up into the report.

    The same residual mean-reversion model Pulse runs on 5-minute bars, on daily ones:
    regress 60 sessions of the stock's returns on SPY and its sector ETF, treat the
    cumulative residual as an Ornstein-Uhlenbeck process, and report how many
    equilibrium standard deviations it sits from its mean (`al_s`). `resid5` is the
    last five sessions of residual return — the part of the pre-report move that the
    market and the sector do not explain.
    """
    empty = {"al_s": None, "al_half": None, "resid5": None, "vol20": None}
    sr = hist.set_index("date")["Close"].astype(float).pct_change().dropna().tail(60)
    cols = [bars.before("SPY", cutoff, 130).set_index("date")["Close"].astype(float).pct_change()]
    etf = SECTOR_ETF_MAP.get(sector or "")
    if etf:
        eh = bars.before(etf, cutoff, 130)
        if len(eh) > 61:
            cols.append(eh.set_index("date")["Close"].astype(float).pct_change())
    m = pd.concat([sr, *cols], axis=1, join="inner").dropna()
    if len(m) < 45:
        return empty
    y = m.iloc[:, 0].to_numpy()
    a = np.column_stack([np.ones(len(m)), m.iloc[:, 1:].to_numpy()])
    resid = y - a @ np.linalg.lstsq(a, y, rcond=None)[0]
    out = {**empty, "resid5": float(resid[-5:].sum()), "vol20": float(sr.tail(20).std())}
    x = np.cumsum(resid)
    z, nxt = x[:-1], x[1:]
    if z.std() < 1e-9:
        return out
    b = float(np.cov(z, nxt, bias=True)[0, 1] / z.var())
    if not 0 < b < 1:
        return out  # not mean-reverting over this window: no score, rather than a made-up one
    c = float(nxt.mean() - b * z.mean())
    rv = float(np.var(nxt - c - b * z))
    if rv < 1e-12:
        return out
    out["al_s"] = float((x[-1] - c / (1 - b)) / math.sqrt(rv / (1 - b * b)))
    out["al_half"] = float(math.log(2) / -math.log(b))
    return out


def next_session(d: date) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


def run(upcoming_only: bool = False) -> dict:
    today = date.today()
    where = "e.earnings_date >= :today" if upcoming_only else "TRUE"
    with SessionLocal() as s:
        events = s.execute(text(f"""
            SELECT p.id, e.ticker, e.earnings_date, e.sector, e.report_time, o.reaction_date
            FROM price_features p
            JOIN earnings_events e ON e.ticker=p.ticker AND e.earnings_date=p.earnings_date
            LEFT JOIN outcomes o ON o.ticker=p.ticker AND o.earnings_date=p.earnings_date
            WHERE {where} ORDER BY e.ticker, e.earnings_date"""), {"today": today}).all()
    if not events:
        return {"events": 0}
    bars = Bars(min(e.earnings_date for e in events) - timedelta(days=WINDOW_DAYS + 30))
    for sym in (*MARKET, *SECTOR_ETF_MAP.values()):
        bars.get(sym)
    done = skipped = 0
    with SessionLocal() as s:
        for n, e in enumerate(events, 1):
            if e.reaction_date is not None:
                cutoff = e.reaction_date
            else:
                # Not reacted yet: the report trades on its own date (pre-market) or the
                # session after (after-close). Bars only exist up to today either way.
                cutoff = next_session(e.earnings_date) if (e.report_time or "").upper() == "AMC" else e.earnings_date
                cutoff = min(cutoff, today + timedelta(days=1))
            fresh = features_asof(bars, e.ticker, e.sector, cutoff)
            if not fresh:
                skipped += 1
                continue
            payload = s.execute(text("SELECT feature_payload FROM price_features WHERE id=:i"), {"i": e.id}).scalar() or {}
            if isinstance(payload, str):
                payload = json.loads(payload)
            payload.update(fresh)
            s.execute(text("UPDATE price_features SET feature_payload = CAST(:p AS jsonb) WHERE id=:i"),
                      {"p": json.dumps(payload, default=str), "i": e.id})
            done += 1
            if n % 500 == 0:
                s.commit()
                log.info("rebuild [%s/%s] done=%s skipped=%s", n, len(events), done, skipped)
        s.commit()
    return {"events": len(events), "rebuilt": done, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--upcoming", action="store_true")
    print(run(ap.parse_args().upcoming))
