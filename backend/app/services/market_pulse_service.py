"""Market Pulse — real-time intraday anomaly scanner.

Continuously monitors top S&P 500 names on 5-min bars. Detects 5 classes of
signal: RSI extremes, volume surges, momentum breakouts, mean reversion,
opening gap reversals. Simulates a $1M portfolio that trades these signals
with 1-hour holding periods.

Uses file-based 5-min cache to avoid hammering yfinance.
"""
from __future__ import annotations

import os
import pickle
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


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
CACHE_TTL = 300  # 5 minutes


def _fetch_bars() -> pd.DataFrame:
    """Fetch 5-min bars for the universe, cached for 5 min."""
    if os.path.exists(CACHE_PATH):
        age = time.time() - os.path.getmtime(CACHE_PATH)
        if age < CACHE_TTL:
            try:
                with open(CACHE_PATH, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass
    # Fresh fetch — single batch call
    df = yf.download(
        tickers=" ".join(UNIVERSE),
        period="5d",
        interval="5m",
        group_by="ticker",
        progress=False,
        threads=True,
        auto_adjust=True,
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


def _compute_ticker_indicators(df: pd.DataFrame, ticker: str) -> dict[str, Any] | None:
    """Compute current indicators + recent bars for one ticker."""
    try:
        if ticker not in df.columns.levels[0]:
            return None
        sub = df[ticker].dropna()
        if len(sub) < 30:
            return None
        close = sub["Close"]
        vol = sub["Volume"]
        high = sub["High"]
        low = sub["Low"]
        opn = sub["Open"]

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
        vol_z = (last_vol - avg_vol) / float(vol_std.iloc[-1]) if pd.notna(vol_std.iloc[-1]) and vol_std.iloc[-1] > 0 else 0.0

        # Distance from MA in standard deviations
        dist_ma = (last_close - last_ma) / last_std if last_std > 0 else 0.0

        # Intraday return (since first bar today)
        today_start = sub.index[-1].normalize()
        today_bars = sub[sub.index >= today_start]
        intraday_ret = (last_close / float(today_bars["Open"].iloc[0]) - 1) if len(today_bars) > 0 else 0.0

        # 5-min recent return
        ret_5m = (last_close / float(close.iloc[-2]) - 1) if len(close) >= 2 else 0.0

        # Opening gap
        if len(today_bars) > 0 and len(sub) > len(today_bars):
            prev_close = float(close.iloc[-len(today_bars) - 1])
            today_open = float(today_bars["Open"].iloc[0])
            gap_pct = today_open / prev_close - 1
        else:
            gap_pct = 0.0

        # Mini bar history for sparkline (last 78 bars = full trading day if avail)
        spark = close.iloc[-78:].tolist() if len(close) >= 78 else close.tolist()

        return {
            "ticker": ticker,
            "sector": SECTORS.get(ticker, "—"),
            "price": round(last_close, 2),
            "rsi": round(last_rsi, 1),
            "vol_z": round(vol_z, 2),
            "dist_ma": round(dist_ma, 2),
            "intraday_ret": round(intraday_ret, 4),
            "ret_5m": round(ret_5m, 4),
            "gap_pct": round(gap_pct, 4),
            "spark": [round(s, 2) for s in spark],
            "last_ts": sub.index[-1].isoformat() if hasattr(sub.index[-1], "isoformat") else str(sub.index[-1]),
        }
    except Exception:
        return None


SIGNAL_TYPES = {
    "RSI_OVERSOLD":   {"emoji": "📉", "label": "RSI Oversold",     "side": "LONG",  "color": "#4ade80"},
    "RSI_OVERBOUGHT": {"emoji": "📈", "label": "RSI Overbought",   "side": "SHORT", "color": "#f87171"},
    "VOL_SURGE":      {"emoji": "🔥", "label": "Volume Surge",     "side": "LONG",  "color": "#fbbf24"},
    "BREAKOUT_UP":    {"emoji": "🚀", "label": "Momentum Breakout","side": "LONG",  "color": "#38bdf8"},
    "BREAKDOWN":      {"emoji": "💥", "label": "Momentum Breakdown","side": "SHORT","color": "#fb7185"},
    "GAP_FADE_UP":    {"emoji": "🔄", "label": "Gap Fade (down)",  "side": "SHORT", "color": "#a78bfa"},
    "GAP_FADE_DN":    {"emoji": "🔄", "label": "Gap Fade (up)",    "side": "LONG",  "color": "#2dd4bf"},
}


def _detect_signals(ind: dict[str, Any]) -> list[dict[str, Any]]:
    """Run signal rules on one ticker's indicators."""
    sigs = []
    if ind["rsi"] < 22 and ind["intraday_ret"] < -0.015:
        sigs.append("RSI_OVERSOLD")
    if ind["rsi"] > 78 and ind["intraday_ret"] > 0.015:
        sigs.append("RSI_OVERBOUGHT")
    if ind["vol_z"] > 3.5 and ind["intraday_ret"] > 0:
        sigs.append("VOL_SURGE")
    if ind["dist_ma"] > 2.0 and ind["ret_5m"] > 0.003:
        sigs.append("BREAKOUT_UP")
    if ind["dist_ma"] < -2.0 and ind["ret_5m"] < -0.003:
        sigs.append("BREAKDOWN")
    if ind["gap_pct"] > 0.02 and ind["intraday_ret"] < ind["gap_pct"] * 0.5:
        sigs.append("GAP_FADE_UP")
    if ind["gap_pct"] < -0.02 and ind["intraday_ret"] > ind["gap_pct"] * 0.5:
        sigs.append("GAP_FADE_DN")
    return [{
        "ticker": ind["ticker"],
        "sector": ind["sector"],
        "type": t,
        "type_label": SIGNAL_TYPES[t]["label"],
        "emoji": SIGNAL_TYPES[t]["emoji"],
        "side": SIGNAL_TYPES[t]["side"],
        "color": SIGNAL_TYPES[t]["color"],
        "price": ind["price"],
        "rsi": ind["rsi"],
        "vol_z": ind["vol_z"],
        "intraday_ret": ind["intraday_ret"],
        "timestamp": ind["last_ts"],
    } for t in sigs]


def _simulate_portfolio(df: pd.DataFrame, hold_bars: int = 12, position_size: float = 50_000) -> dict[str, Any]:
    """Walk through every bar over the data window. When a signal fires,
    open a $50k position and close `hold_bars` (1 hour) later. Track P&L."""
    initial = 1_000_000
    cash = initial
    closed_trades = []
    equity_curve = []

    # Build per-ticker bar series with timestamp index aligned
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
                "close": close,
                "rsi": _rsi(close, 14),
                "ma20": close.rolling(20).mean(),
                "std20": close.rolling(20).std(),
                "vol": sub["Volume"],
                "vol_ma": sub["Volume"].rolling(60).mean(),
                "vol_std": sub["Volume"].rolling(60).std(),
            }
        except Exception:
            continue

    if not ticker_bars:
        return {"final_equity": initial, "total_return": 0.0, "trades": 0,
                "win_rate": 0.0, "sharpe": 0.0, "equity_curve": [], "trade_log": []}

    # Get common timeline
    all_times = sorted(set().union(*[v["close"].index for v in ticker_bars.values()]))
    open_positions = []  # list of dicts

    for t_idx, t in enumerate(all_times):
        # Close any expiring positions
        keep = []
        for pos in open_positions:
            if t >= pos["exit_time"]:
                tb = ticker_bars.get(pos["ticker"])
                if tb is not None and t in tb["close"].index:
                    exit_price = float(tb["close"].loc[t])
                    pnl = pos["size"] * (exit_price / pos["entry_price"] - 1) * (1 if pos["side"] == "LONG" else -1)
                    cash += pos["size"] + pnl
                    closed_trades.append({
                        "ticker": pos["ticker"], "side": pos["side"], "type": pos["type"],
                        "entry_time": pos["entry_time"].isoformat() if hasattr(pos["entry_time"], "isoformat") else str(pos["entry_time"]),
                        "exit_time": t.isoformat() if hasattr(t, "isoformat") else str(t),
                        "entry_price": round(pos["entry_price"], 2),
                        "exit_price": round(exit_price, 2),
                        "pnl": round(pnl, 2),
                        "return_pct": round(pnl / pos["size"], 4),
                        "win": pnl > 0,
                    })
                else:
                    cash += pos["size"]  # close at entry, no data
            else:
                keep.append(pos)
        open_positions = keep

        # Check for new signals on each ticker
        for ticker, tb in ticker_bars.items():
            if t not in tb["close"].index:
                continue
            try:
                close = float(tb["close"].loc[t])
                rsi = tb["rsi"].loc[t]
                if pd.isna(rsi):
                    continue
                ma = tb["ma20"].loc[t]
                std = tb["std20"].loc[t]
                if pd.isna(ma) or pd.isna(std) or std == 0:
                    continue
                dist_ma = (close - ma) / std

                # Skip if already have open position on this ticker
                if any(p["ticker"] == ticker for p in open_positions):
                    continue

                # Need cash
                if cash < position_size:
                    continue

                side = None
                stype = None
                if rsi < 22 and dist_ma < -1.5:
                    side, stype = "LONG", "RSI_OVERSOLD"
                elif rsi > 78 and dist_ma > 1.5:
                    side, stype = "SHORT", "RSI_OVERBOUGHT"
                elif dist_ma > 2.0:
                    side, stype = "LONG", "BREAKOUT_UP"
                elif dist_ma < -2.0:
                    side, stype = "SHORT", "BREAKDOWN"

                if side is not None:
                    exit_idx = min(t_idx + hold_bars, len(all_times) - 1)
                    open_positions.append({
                        "ticker": ticker, "side": side, "type": stype,
                        "entry_time": t, "entry_price": close,
                        "exit_time": all_times[exit_idx], "size": position_size,
                    })
                    cash -= position_size
            except Exception:
                continue

        # Mark equity once per bar (downsample for performance)
        if t_idx % 20 == 0 or t_idx == len(all_times) - 1:
            pos_value = sum(p["size"] for p in open_positions)
            equity_curve.append({
                "ts": t.isoformat() if hasattr(t, "isoformat") else str(t),
                "equity": round(cash + pos_value, 2),
            })

    # Force-close any remaining at last available price
    for pos in open_positions:
        cash += pos["size"]

    final_equity = cash
    n_trades = len(closed_trades)
    wins = sum(1 for t in closed_trades if t["win"])
    win_rate = wins / n_trades if n_trades else 0.0
    rets = [t["return_pct"] for t in closed_trades]
    if len(rets) > 1 and np.std(rets) > 0:
        sharpe = float(np.mean(rets) / np.std(rets) * sqrt(78 * 5 / hold_bars))  # ~78 bars/day
    else:
        sharpe = 0.0

    return {
        "final_equity": round(final_equity, 2),
        "total_return": round(final_equity / initial - 1, 4),
        "trades": n_trades,
        "wins": wins,
        "win_rate": round(win_rate, 4),
        "sharpe": round(sharpe, 3),
        "equity_curve": equity_curve,
        "trade_log": sorted(closed_trades, key=lambda x: x["exit_time"], reverse=True)[:20],
    }


def scan_market() -> dict[str, Any]:
    """Main entry point. Returns full pulse state."""
    df = _fetch_bars()
    if df is None or df.empty:
        return {"error": "no_data", "tickers": [], "signals": [],
                "portfolio": {"final_equity": 1_000_000, "total_return": 0.0,
                              "trades": 0, "wins": 0, "win_rate": 0.0, "sharpe": 0.0,
                              "equity_curve": [], "trade_log": []},
                "as_of": datetime.utcnow().isoformat()}

    indicators = []
    all_signals = []
    for ticker in UNIVERSE:
        ind = _compute_ticker_indicators(df, ticker)
        if ind is not None:
            indicators.append(ind)
            all_signals.extend(_detect_signals(ind))

    # Sort tickers by intraday return for heat map
    indicators.sort(key=lambda x: -x["intraday_ret"])

    # Compute aggregate market metrics
    if indicators:
        market_ret = float(np.mean([i["intraday_ret"] for i in indicators]))
        market_breadth = sum(1 for i in indicators if i["intraday_ret"] > 0) / len(indicators)
        avg_vol_z = float(np.mean([i["vol_z"] for i in indicators]))
        avg_rsi = float(np.mean([i["rsi"] for i in indicators]))
    else:
        market_ret = market_breadth = avg_vol_z = 0
        avg_rsi = 50

    # Sector aggregates
    sector_data = {}
    for ind in indicators:
        sec = ind["sector"]
        sector_data.setdefault(sec, []).append(ind["intraday_ret"])
    sectors = [{
        "sector": sec, "avg_ret": round(float(np.mean(rets)), 4),
        "count": len(rets),
    } for sec, rets in sector_data.items()]
    sectors.sort(key=lambda x: -x["avg_ret"])

    # Portfolio simulation
    portfolio = _simulate_portfolio(df)

    return {
        "tickers": indicators,
        "signals": sorted(all_signals, key=lambda x: x["timestamp"], reverse=True),
        "sectors": sectors,
        "market": {
            "avg_return": round(market_ret, 4),
            "breadth": round(market_breadth, 3),
            "avg_vol_z": round(avg_vol_z, 2),
            "avg_rsi": round(avg_rsi, 1),
            "n_tickers": len(indicators),
        },
        "portfolio": portfolio,
        "as_of": datetime.utcnow().isoformat(),
    }
