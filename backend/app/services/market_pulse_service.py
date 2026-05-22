"""Market Pulse — multi-factor intraday scanner.

Each ticker gets a composite conviction score from 5 independent factors:
  • RSI (mean reversion)
  • 20-MA distance (mean reversion)
  • 5-min momentum
  • Volume z-score (confirmation)
  • Opening gap behavior

Score in [-1, +1]. Trade only when |score| > 0.5. Position size scales
with conviction. High-conviction signals (|score| > 0.65) are pushed to
Telegram if configured.
"""
from __future__ import annotations

import os
import pickle
import time
from datetime import datetime, timedelta
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from backend.app.services.notification_service import send_signal as send_telegram


UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK-B",
    "JPM", "V", "JNJ", "WMT", "PG", "MA", "HD", "CVX", "ABBV", "LLY",
    "MRK", "KO", "PEP", "AVGO", "COST", "BAC", "ADBE", "TMO", "NFLX",
    "CSCO", "ORCL", "AMD",
]

SECTORS = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "GOOGL": "Communication", "AMZN": "Consumer", "META": "Communication",
    "TSLA": "Consumer", "BRK-B": "Financial", "JPM": "Financial", "V": "Financial",
    "JNJ": "Healthcare", "WMT": "Consumer", "PG": "Consumer", "MA": "Financial",
    "HD": "Consumer", "CVX": "Energy", "ABBV": "Healthcare", "LLY": "Healthcare",
    "MRK": "Healthcare", "KO": "Consumer", "PEP": "Consumer", "AVGO": "Technology",
    "COST": "Consumer", "BAC": "Financial", "ADBE": "Technology", "TMO": "Healthcare",
    "NFLX": "Communication", "CSCO": "Technology", "ORCL": "Technology", "AMD": "Technology",
}

CACHE_PATH = "/tmp/pulse_cache.pkl"
CACHE_TTL = 300

# Trading thresholds
SIGNAL_THRESHOLD = 0.50    # min |score| to enter a trade
NOTIFY_THRESHOLD = 0.65    # min |score| to send Telegram alert
BASE_POSITION = 50_000     # base $ size; actual = base * |score|


def _fetch_bars() -> pd.DataFrame:
    if os.path.exists(CACHE_PATH):
        age = time.time() - os.path.getmtime(CACHE_PATH)
        if age < CACHE_TTL:
            try:
                with open(CACHE_PATH, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass
    df = yf.download(
        tickers=" ".join(UNIVERSE),
        period="5d", interval="5m", group_by="ticker",
        progress=False, threads=True, auto_adjust=True,
    )
    try:
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(df, f)
    except Exception:
        pass
    return df


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).rolling(length).mean()
    down = (-delta.clip(upper=0)).rolling(length).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_indicators(df: pd.DataFrame, ticker: str) -> dict[str, Any] | None:
    try:
        if ticker not in df.columns.levels[0]:
            return None
        sub = df[ticker].dropna()
        if len(sub) < 30:
            return None
        close = sub["Close"]
        vol = sub["Volume"]

        rsi = _rsi(close, 14)
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        vol_ma = vol.rolling(60).mean()
        vol_std = vol.rolling(60).std()

        last_close = float(close.iloc[-1])
        last_vol = float(vol.iloc[-1])
        last_rsi = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0
        last_ma = float(ma20.iloc[-1]) if pd.notna(ma20.iloc[-1]) else last_close
        last_std = float(std20.iloc[-1]) if pd.notna(std20.iloc[-1]) else 0.01
        avg_vol = float(vol_ma.iloc[-1]) if pd.notna(vol_ma.iloc[-1]) else last_vol
        vstd = float(vol_std.iloc[-1]) if pd.notna(vol_std.iloc[-1]) else 1
        vol_z = (last_vol - avg_vol) / vstd if vstd > 0 else 0.0

        dist_ma = (last_close - last_ma) / last_std if last_std > 0 else 0.0

        today_start = sub.index[-1].normalize()
        today_bars = sub[sub.index >= today_start]
        intraday_ret = (last_close / float(today_bars["Open"].iloc[0]) - 1) if len(today_bars) > 0 else 0.0
        ret_5m = (last_close / float(close.iloc[-2]) - 1) if len(close) >= 2 else 0.0

        if len(today_bars) > 0 and len(sub) > len(today_bars):
            prev_close = float(close.iloc[-len(today_bars) - 1])
            today_open = float(today_bars["Open"].iloc[0])
            gap_pct = today_open / prev_close - 1
        else:
            gap_pct = 0.0

        spark = close.iloc[-78:].tolist() if len(close) >= 78 else close.tolist()

        return {
            "ticker": ticker, "sector": SECTORS.get(ticker, "—"),
            "price": round(last_close, 2),
            "rsi": round(last_rsi, 1), "vol_z": round(vol_z, 2),
            "dist_ma": round(dist_ma, 2), "intraday_ret": round(intraday_ret, 4),
            "ret_5m": round(ret_5m, 4), "gap_pct": round(gap_pct, 4),
            "spark": [round(s, 2) for s in spark],
            "last_ts": sub.index[-1].isoformat() if hasattr(sub.index[-1], "isoformat") else str(sub.index[-1]),
        }
    except Exception:
        return None


def _compute_conviction(ind: dict, sector_ret: float = 0.0) -> tuple[float, list[dict]]:
    """Compute composite conviction score from 5 factors. Returns (score, factors_list)."""
    factors = []

    # 1) RSI (mean reversion): low RSI = bullish bias
    if ind["rsi"] < 30:
        v = round(0.30 * (30 - ind["rsi"]) / 30, 3)
        factors.append({"label": f"RSI oversold ({ind['rsi']:.0f})", "value": v})
    elif ind["rsi"] > 70:
        v = round(-0.30 * (ind["rsi"] - 70) / 30, 3)
        factors.append({"label": f"RSI overbought ({ind['rsi']:.0f})", "value": v})

    # 2) Distance from 20-MA (mean reversion): far above = bearish bias
    if abs(ind["dist_ma"]) > 1.2:
        sign = -1 if ind["dist_ma"] > 0 else 1
        v = round(sign * 0.25 * min(1.0, abs(ind["dist_ma"]) / 3.0), 3)
        side = "above" if ind["dist_ma"] > 0 else "below"
        factors.append({"label": f"{abs(ind['dist_ma']):.1f}σ {side} 20-MA", "value": v})

    # 3) 5-min momentum (trend): vote with direction
    if abs(ind["ret_5m"]) > 0.003:
        sign = 1 if ind["ret_5m"] > 0 else -1
        v = round(sign * 0.20 * min(1.0, abs(ind["ret_5m"]) / 0.01), 3)
        factors.append({"label": f"5m momentum {ind['ret_5m']*100:+.2f}%", "value": v})

    # 4) Volume confirmation: amplifies the dominant direction
    if ind["vol_z"] > 1.8:
        # Volume confirms whatever direction the 5-min move shows
        if ind["ret_5m"] > 0:
            v = round(0.20 * min(1.0, ind["vol_z"] / 5.0), 3)
            factors.append({"label": f"Volume surge +{ind['vol_z']:.1f}σ", "value": v})
        elif ind["ret_5m"] < 0:
            v = round(-0.20 * min(1.0, ind["vol_z"] / 5.0), 3)
            factors.append({"label": f"Volume surge +{ind['vol_z']:.1f}σ", "value": v})

    # 5) Gap behavior
    if ind["gap_pct"] > 0.015:
        if ind["intraday_ret"] < ind["gap_pct"] * 0.5:
            # Gap up that's already fading — bearish
            factors.append({"label": f"Fading gap-up ({ind['gap_pct']*100:+.1f}%)", "value": -0.25})
    elif ind["gap_pct"] < -0.015:
        if ind["intraday_ret"] > ind["gap_pct"] * 0.5:
            factors.append({"label": f"Reversing gap-down ({ind['gap_pct']*100:+.1f}%)", "value": 0.25})

    # 6) Sector tailwind/headwind
    if abs(sector_ret) > 0.005:
        sign = 1 if sector_ret > 0 else -1
        v = round(sign * 0.10, 3)
        factors.append({"label": f"Sector {sector_ret*100:+.2f}%", "value": v})

    score = round(sum(f["value"] for f in factors), 3)
    return score, factors


def _simulate_portfolio(df: pd.DataFrame, hold_bars: int = 12, sector_lookup: dict = None) -> dict:
    """Walk through bars; trade when |conviction| > threshold; hold 1 hr."""
    initial = 1_000_000
    cash = initial
    closed = []
    equity_curve = []

    ticker_bars = {}
    for ticker in UNIVERSE:
        try:
            if ticker not in df.columns.levels[0]:
                continue
            sub = df[ticker].dropna()
            if len(sub) < 30:
                continue
            close = sub["Close"]
            ticker_bars[ticker] = {
                "close": close, "vol": sub["Volume"],
                "rsi": _rsi(close, 14),
                "ma20": close.rolling(20).mean(),
                "std20": close.rolling(20).std(),
                "vol_ma": sub["Volume"].rolling(60).mean(),
                "vol_std": sub["Volume"].rolling(60).std(),
                "open": sub["Open"],
                "sector": SECTORS.get(ticker, "—"),
            }
        except Exception:
            continue

    if not ticker_bars:
        return {"final_equity": initial, "total_return": 0.0, "trades": 0, "wins": 0,
                "win_rate": 0.0, "sharpe": 0.0, "equity_curve": [], "trade_log": []}

    all_times = sorted(set().union(*[v["close"].index for v in ticker_bars.values()]))
    open_pos = []

    for t_idx, t in enumerate(all_times):
        # Close expiring
        keep = []
        for pos in open_pos:
            if t >= pos["exit_time"]:
                tb = ticker_bars.get(pos["ticker"])
                if tb is not None and t in tb["close"].index:
                    exit_p = float(tb["close"].loc[t])
                    pnl = pos["size"] * (exit_p / pos["entry"] - 1) * (1 if pos["side"] == "LONG" else -1)
                    cash += pos["size"] + pnl
                    closed.append({
                        "ticker": pos["ticker"], "side": pos["side"], "score": pos["score"],
                        "entry_time": pos["entry_time"].isoformat(),
                        "exit_time": t.isoformat(),
                        "entry_price": round(pos["entry"], 2),
                        "exit_price": round(exit_p, 2),
                        "pnl": round(pnl, 2),
                        "return_pct": round(pnl / pos["size"], 4),
                        "win": pnl > 0,
                    })
                else:
                    cash += pos["size"]
            else:
                keep.append(pos)
        open_pos = keep

        # Compute sector returns at this bar
        sector_rets = {}
        if t_idx % 4 == 0:  # update every 20 min to save compute
            by_sec = {}
            for ticker, tb in ticker_bars.items():
                try:
                    if t in tb["close"].index:
                        opn = tb["open"].loc[tb["open"].index >= t.normalize()]
                        if len(opn) > 0:
                            ret = float(tb["close"].loc[t]) / float(opn.iloc[0]) - 1
                            by_sec.setdefault(tb["sector"], []).append(ret)
                except Exception:
                    pass
            sector_rets = {s: float(np.mean(r)) for s, r in by_sec.items()}

        # Check signals
        for ticker, tb in ticker_bars.items():
            if t not in tb["close"].index:
                continue
            if any(p["ticker"] == ticker for p in open_pos):
                continue
            try:
                close = float(tb["close"].loc[t])
                rsi = tb["rsi"].loc[t]
                ma = tb["ma20"].loc[t]
                std = tb["std20"].loc[t]
                vol_ma = tb["vol_ma"].loc[t]
                vol_std = tb["vol_std"].loc[t]
                if pd.isna(rsi) or pd.isna(ma) or pd.isna(std) or std == 0:
                    continue
                vol = float(tb["vol"].loc[t])
                avgv = float(vol_ma) if pd.notna(vol_ma) else vol
                vstd = float(vol_std) if pd.notna(vol_std) and vol_std > 0 else 1
                opn = tb["open"].loc[tb["open"].index >= t.normalize()]
                intraday = (close / float(opn.iloc[0]) - 1) if len(opn) > 0 else 0.0
                prev_close_idx = tb["close"].index.get_loc(t) - 1
                ret_5m = (close / float(tb["close"].iloc[prev_close_idx]) - 1) if prev_close_idx >= 0 else 0.0
                if len(opn) > 0:
                    bars_today = (tb["open"].index >= t.normalize()).sum()
                    if bars_today < len(tb["close"]):
                        prev_close_day = float(tb["close"].iloc[-bars_today - 1]) if bars_today < len(tb["close"]) else float(opn.iloc[0])
                        gap = float(opn.iloc[0]) / prev_close_day - 1
                    else:
                        gap = 0
                else:
                    gap = 0

                ind = {
                    "ticker": ticker, "rsi": float(rsi),
                    "dist_ma": (close - float(ma)) / float(std),
                    "ret_5m": ret_5m, "vol_z": (vol - avgv) / vstd if vstd > 0 else 0,
                    "intraday_ret": intraday, "gap_pct": gap,
                }
                sect_ret = sector_rets.get(tb["sector"], 0.0)
                score, _ = _compute_conviction(ind, sect_ret)

                if abs(score) >= SIGNAL_THRESHOLD and cash >= BASE_POSITION * abs(score):
                    side = "LONG" if score > 0 else "SHORT"
                    size = BASE_POSITION * abs(score)
                    exit_idx = min(t_idx + hold_bars, len(all_times) - 1)
                    open_pos.append({
                        "ticker": ticker, "side": side, "score": round(score, 3),
                        "entry_time": t, "entry": close,
                        "exit_time": all_times[exit_idx], "size": size,
                    })
                    cash -= size
            except Exception:
                continue

        if t_idx % 20 == 0 or t_idx == len(all_times) - 1:
            pos_value = sum(p["size"] for p in open_pos)
            equity_curve.append({
                "ts": t.isoformat(),
                "equity": round(cash + pos_value, 2),
            })

    for p in open_pos:
        cash += p["size"]

    final = cash
    n = len(closed)
    wins = sum(1 for t in closed if t["win"])
    win_rate = wins / n if n else 0.0
    rets = [t["return_pct"] for t in closed]
    sharpe = float(np.mean(rets) / np.std(rets) * sqrt(78 * 5 / hold_bars)) if len(rets) > 1 and np.std(rets) > 0 else 0.0

    return {
        "final_equity": round(final, 2),
        "total_return": round(final / initial - 1, 4),
        "trades": n, "wins": wins,
        "win_rate": round(win_rate, 4),
        "sharpe": round(sharpe, 3),
        "equity_curve": equity_curve,
        "trade_log": sorted(closed, key=lambda x: x["exit_time"], reverse=True)[:20],
    }


def scan_market() -> dict[str, Any]:
    df = _fetch_bars()
    if df is None or df.empty:
        return {"error": "no_data", "tickers": [], "signals": [], "sectors": [],
                "market": {}, "portfolio": {}, "notifications": {"configured": False},
                "as_of": datetime.utcnow().isoformat()}

    # Pass 1: indicators
    indicators = []
    for ticker in UNIVERSE:
        ind = _compute_indicators(df, ticker)
        if ind is not None:
            indicators.append(ind)

    # Pass 2: sector aggregates
    by_sec = {}
    for i in indicators:
        by_sec.setdefault(i["sector"], []).append(i["intraday_ret"])
    sector_rets = {s: float(np.mean(r)) for s, r in by_sec.items()}

    # Pass 3: conviction scores
    enriched = []
    signals = []
    for ind in indicators:
        score, factors = _compute_conviction(ind, sector_rets.get(ind["sector"], 0))
        ind["score"] = score
        ind["factors"] = factors
        enriched.append(ind)

        if abs(score) >= SIGNAL_THRESHOLD:
            side = "LONG" if score > 0 else "SHORT"
            size = int(BASE_POSITION * abs(score))
            sig = {
                "ticker": ind["ticker"], "sector": ind["sector"],
                "score": score, "side": side, "factors": factors,
                "price": ind["price"], "rsi": ind["rsi"], "vol_z": ind["vol_z"],
                "intraday_ret": ind["intraday_ret"],
                "suggested_size": size,
                "exit_clock": (datetime.utcnow() + timedelta(hours=1)).strftime("%H:%M ET"),
                "timestamp": ind["last_ts"],
                "high_conviction": abs(score) >= NOTIFY_THRESHOLD,
                "notified": False,
            }
            # Push high-conviction to Telegram
            if sig["high_conviction"]:
                sig["notified"] = send_telegram(sig)
            signals.append(sig)

    enriched.sort(key=lambda x: -x["intraday_ret"])
    signals.sort(key=lambda x: -abs(x["score"]))

    sectors = [{"sector": s, "avg_ret": round(r, 4), "count": len(by_sec[s])}
               for s, r in sector_rets.items()]
    sectors.sort(key=lambda x: -x["avg_ret"])

    if indicators:
        market_ret = float(np.mean([i["intraday_ret"] for i in indicators]))
        breadth = sum(1 for i in indicators if i["intraday_ret"] > 0) / len(indicators)
        avg_vol_z = float(np.mean([i["vol_z"] for i in indicators]))
        avg_rsi = float(np.mean([i["rsi"] for i in indicators]))
    else:
        market_ret = breadth = avg_vol_z = 0
        avg_rsi = 50

    from backend.app.services.notification_service import notification_status
    return {
        "tickers": enriched,
        "signals": signals,
        "sectors": sectors,
        "market": {
            "avg_return": round(market_ret, 4),
            "breadth": round(breadth, 3),
            "avg_vol_z": round(avg_vol_z, 2),
            "avg_rsi": round(avg_rsi, 1),
            "n_tickers": len(indicators),
        },
        "portfolio": _simulate_portfolio(df, sector_lookup=sector_rets),
        "notifications": notification_status(),
        "thresholds": {
            "signal": SIGNAL_THRESHOLD,
            "notify": NOTIFY_THRESHOLD,
        },
        "as_of": datetime.utcnow().isoformat(),
    }
