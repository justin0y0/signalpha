"""Market Pulse v2 — Avellaneda-Lee + Gao-Han-Li-Zhou + Triple-Barrier + Meta-Score.

Architecture (per research synthesis):
  1. PRIMARY SIGNALS:
     • AL residual mean-reversion (s-score against SPY + sector ETF)
     • Gao-Han-Li-Zhou intraday momentum (last-hour trades use AM signal)
     • Connors RSI(2) with 200-bar regime filter (feature only)
  2. META-SCORE: combines primary signals + regime features into final conviction
  3. SIZING: fractional Kelly capped by ATR vol-targeting
  4. EXIT: triple barrier (PT, SL, time) — not fixed 1-hour
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
from backend.app.services.news_service import fetch_news
from backend.app.services.ai_explain_service import explain_signal as ai_explain
from backend.app.services.avellaneda_lee import compute_s_score, SECTOR_ETF
from backend.app.services.triple_barrier import apply_barrier, realized_vol
from backend.app.services.intraday_momentum import gao_signal

from datetime import time as _dt_time
try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None


# ════ Universe: S&P 100, expanded from 30 ════
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "BRK-B",
    "JPM", "V", "JNJ", "WMT", "PG", "MA", "HD", "CVX", "ABBV", "LLY",
    "MRK", "KO", "PEP", "AVGO", "COST", "BAC", "ADBE", "TMO", "NFLX",
    "CSCO", "ORCL", "AMD", "CRM", "ACN", "MCD", "ABT", "WFC", "DHR",
    "VZ", "TXN", "QCOM", "INTC", "INTU", "NKE", "PM", "DIS", "PFE",
    "RTX", "T", "LOW", "UPS", "AMGN", "HON", "GS", "IBM", "CAT",
    "SPGI", "AXP", "ELV", "DE", "BLK", "ISRG", "GE", "PLD", "SYK",
    "BKNG", "MDLZ", "AMAT", "GILD", "TJX", "ADI", "C", "VRTX", "ETN",
    "PANW", "REGN", "MMC", "SCHW", "ADP", "LMT", "MO", "CB", "CI",
    "ZTS", "BSX", "MU", "FI", "SO", "DUK", "BMY", "PYPL", "ICE",
    "AON", "CL", "EQIX", "WM", "SHW", "CME", "MCO", "ITW", "USB",
    "PNC",
]
FACTORS = ["SPY"]  # market factor

SECTORS = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "GOOGL": "Communication", "GOOG": "Communication", "AMZN": "Consumer",
    "META": "Communication", "TSLA": "Consumer", "BRK-B": "Financial",
    "JPM": "Financial", "V": "Financial", "JNJ": "Healthcare", "WMT": "Consumer",
    "PG": "Staples", "MA": "Financial", "HD": "Consumer", "CVX": "Energy",
    "ABBV": "Healthcare", "LLY": "Healthcare", "MRK": "Healthcare",
    "KO": "Staples", "PEP": "Staples", "AVGO": "Technology", "COST": "Staples",
    "BAC": "Financial", "ADBE": "Technology", "TMO": "Healthcare",
    "NFLX": "Communication", "CSCO": "Technology", "ORCL": "Technology",
    "AMD": "Technology", "CRM": "Technology", "ACN": "Technology",
    "MCD": "Consumer", "ABT": "Healthcare", "WFC": "Financial", "DHR": "Healthcare",
    "VZ": "Communication", "TXN": "Technology", "QCOM": "Technology",
    "INTC": "Technology", "INTU": "Technology", "NKE": "Consumer",
    "PM": "Staples", "DIS": "Communication", "PFE": "Healthcare",
    "RTX": "Industrials", "T": "Communication", "LOW": "Consumer",
    "UPS": "Industrials", "AMGN": "Healthcare", "HON": "Industrials",
    "GS": "Financial", "IBM": "Technology", "CAT": "Industrials",
    "SPGI": "Financial", "AXP": "Financial", "ELV": "Healthcare",
    "DE": "Industrials", "BLK": "Financial", "ISRG": "Healthcare",
    "GE": "Industrials", "PLD": "Real Estate", "SYK": "Healthcare",
    "BKNG": "Consumer", "MDLZ": "Staples", "AMAT": "Technology",
    "GILD": "Healthcare", "TJX": "Consumer", "ADI": "Technology",
    "C": "Financial", "VRTX": "Healthcare", "ETN": "Industrials",
    "PANW": "Technology", "REGN": "Healthcare", "MMC": "Financial",
    "SCHW": "Financial", "ADP": "Technology", "LMT": "Industrials",
    "MO": "Staples", "CB": "Financial", "CI": "Healthcare",
    "ZTS": "Healthcare", "BSX": "Healthcare", "MU": "Technology",
    "FI": "Financial", "SO": "Utilities", "DUK": "Utilities",
    "BMY": "Healthcare", "PYPL": "Financial", "ICE": "Financial",
    "AON": "Financial", "CL": "Staples", "EQIX": "Real Estate",
    "WM": "Industrials", "SHW": "Materials", "CME": "Financial",
    "MCO": "Financial", "ITW": "Industrials", "USB": "Financial",
    "PNC": "Financial",
}

CACHE_PATH = "/tmp/pulse_cache_v2.pkl"
CACHE_TTL = 300

# ════ AL thresholds (paper Eq. 16) ════
S_OPEN = 1.25      # open at |s| > 1.25
S_CLOSE_FAVOR = 0.50  # close when s crosses back through favorable side
S_CLOSE_OPP = 0.75    # close when s crosses to opposite side
KAPPA_MIN = 252 * 78 / 30  # half-life < ~30 bars (≈ 2.5 hours)

# ════ Triple-barrier params ════
PT_MULT = 1.0  # profit barrier = 1.0 × σ × √h
SL_MULT = 1.0  # stop barrier = 1.0 × σ × √h
MAX_BARS = 12  # 1-hour time barrier (12 × 5-min)

# ════ Sizing (Half-Kelly) ════
BASE_PORTFOLIO = 1_000_000
KELLY_FRACTION = 0.5  # half-Kelly per Thorp
MAX_POS_PCT = 0.05    # max 5% of book per name
MAX_GROSS = 2.0       # max 200% gross exposure
NOTIFY_THRESHOLD = 0.60  # meta-score threshold for Telegram


def _fetch_bars() -> pd.DataFrame | None:
    """Fetch 5-min bars for universe + factors. Cached for 5 min."""
    if os.path.exists(CACHE_PATH):
        age = time.time() - os.path.getmtime(CACHE_PATH)
        if age < CACHE_TTL:
            try:
                with open(CACHE_PATH, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass
    all_tickers = list(set(UNIVERSE + FACTORS + list(SECTOR_ETF.values())))
    try:
        df = yf.download(
            tickers=" ".join(all_tickers),
            period="5d", interval="5m", group_by="ticker",
            progress=False, threads=True, auto_adjust=True, prepost=True,
        )
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(df, f)
        return df
    except Exception:
        return None


def _session_of(ts) -> str:
    try:
        if _ET is None: return "market"
        if hasattr(ts, "tz_convert"):
            et = ts.tz_convert(_ET)
        elif hasattr(ts, "astimezone"):
            et = ts.astimezone(_ET) if ts.tzinfo else ts.tz_localize("UTC").tz_convert(_ET)
        else: return "market"
        if et.weekday() >= 5: return "closed"
        t = et.time()
        if t < _dt_time(4, 0) or t >= _dt_time(20, 0): return "closed"
        if t < _dt_time(9, 30): return "pre_market"
        if t < _dt_time(16, 0): return "market"
        return "after_hours"
    except Exception:
        return "market"


def _rsi(close: pd.Series, length: int = 2) -> pd.Series:
    """Connors-style short RSI."""
    delta = close.diff()
    up = delta.clip(lower=0).rolling(length).mean()
    down = (-delta.clip(upper=0)).rolling(length).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> pd.Series:
    """Average True Range."""
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _compute_signals_for_ticker(df: pd.DataFrame, ticker: str,
                                 spy_returns: pd.Series,
                                 sector_returns_lookup: dict[str, pd.Series]) -> dict | None:
    """Compute all signal components for one ticker. Returns full diagnostic dict."""
    try:
        if ticker not in df.columns.levels[0]:
            return None
        sub = df[ticker].dropna()
        if len(sub) < 80:
            return None
        close = sub["Close"]
        high = sub["High"]
        low = sub["Low"]
        vol = sub["Volume"]
        ret = close.pct_change()

        # Factor returns for residual model
        sector = SECTORS.get(ticker, "Technology")
        sector_etf = SECTOR_ETF.get(sector, "XLK")
        sector_ret = sector_returns_lookup.get(sector_etf)
        if sector_ret is None:
            return None
        # Align indices
        aligned = pd.concat([ret, spy_returns, sector_ret], axis=1, join="inner")
        aligned.columns = ["stock", "spy", "sec"]
        aligned = aligned.dropna()
        if len(aligned) < 70:
            return None

        # 1) AL s-score
        al = compute_s_score(
            aligned["stock"],
            aligned[["spy", "sec"]],
            lookback=60,
        )

        # 2) Connors RSI(2) with 200-bar regime
        rsi2 = _rsi(close, length=2)
        ma200 = close.rolling(200).mean()
        last_rsi2 = float(rsi2.iloc[-1]) if pd.notna(rsi2.iloc[-1]) else 50.0
        last_close = float(close.iloc[-1])
        regime_up = bool(pd.notna(ma200.iloc[-1]) and last_close > float(ma200.iloc[-1]))

        # 3) Gao-Han-Li-Zhou intraday momentum
        last_ts = sub.index[-1]
        today_mask = sub.index.normalize() == last_ts.normalize() if hasattr(last_ts, "normalize") else None
        gao = None
        if today_mask is not None:
            today_closes = close[today_mask]
            current_idx_today = len(today_closes) - 1
            gao = gao_signal(today_closes, current_idx_today)

        # 4) ATR for sizing + sigma for barriers
        atr20 = _atr(high, low, close, n=20)
        last_atr = float(atr20.iloc[-1]) if pd.notna(atr20.iloc[-1]) else last_close * 0.01
        sigma_bar = float(ret.tail(60).std()) if ret.tail(60).std() > 0 else 0.005

        # 5) Volume z-score (paper Eq. 20 spirit)
        vol_avg = vol.tail(60).mean()
        vol_std = vol.tail(60).std()
        vol_z = (float(vol.iloc[-1]) - vol_avg) / vol_std if vol_std > 0 else 0.0

        spark = close.iloc[-78:].tolist() if len(close) >= 78 else close.tolist()

        return {
            "ticker": ticker, "sector": sector, "sector_etf": sector_etf,
            "price": round(last_close, 2),
            "atr20": round(last_atr, 3),
            "sigma_bar": round(sigma_bar, 5),
            "rsi2": round(last_rsi2, 1),
            "regime_up": regime_up,
            "vol_z": round(vol_z, 2),
            "s_score": round(al["s_score"], 3) if al else None,
            "kappa_ann": round(al["kappa_ann"], 1) if al else None,
            "half_life_bars": round(al["half_life_bars"], 1) if al else None,
            "beta_market": round(al["beta_market"], 2) if al else None,
            "beta_sector": round(al["beta_sector"], 2) if al else None,
            "gao_r1": round(gao["r1"], 4) if gao else None,
            "gao_eligible": bool(gao["eligible"]) if gao else False,
            "gao_side": gao["side"] if gao else None,
            "session": _session_of(last_ts),
            "last_ts": last_ts.isoformat() if hasattr(last_ts, "isoformat") else str(last_ts),
            "spark": [round(s, 2) for s in spark],
        }
    except Exception:
        return None


def _meta_score(ind: dict) -> tuple[float, list[dict], str | None]:
    """Combine primary signals into a meta-conviction score in [-1, +1].

    Per research: meta-labeling lifts precision. Until we have enough live data
    to train a real meta-classifier, this is a rule-based proxy that mimics the
    same logic: a signal is high-conviction when MULTIPLE pillars agree.

    Returns (score, factors_breakdown, primary_engine).
    """
    factors = []
    score = 0.0
    primary = None

    # PILLAR 1: AL residual reversion (primary engine)
    if ind["s_score"] is not None and ind["kappa_ann"] is not None:
        s = ind["s_score"]
        kappa = ind["kappa_ann"]
        half_life = ind["half_life_bars"]

        # Only trade if reversion is fast enough (half-life < MAX_BARS * 2.5)
        fast_enough = half_life is not None and half_life < MAX_BARS * 2.5
        if fast_enough and abs(s) >= S_OPEN:
            # Sign convention: high s = overpriced = SHORT
            al_score = -np.sign(s) * min(1.0, (abs(s) - S_OPEN) / 1.5 + 0.4)
            score += al_score * 0.55
            factors.append({
                "label": f"AL s-score {s:+.2f} (HL {half_life:.0f} bars)",
                "value": round(al_score * 0.55, 3),
                "pillar": "AL_REVERSION",
            })
            primary = "AL_REVERSION"

    # PILLAR 2: Gao-Han-Li-Zhou intraday momentum (last hour only)
    if ind["gao_eligible"] and ind["gao_r1"] is not None:
        gao_dir = 1 if ind["gao_side"] == "LONG" else -1
        gao_score = gao_dir * min(1.0, abs(ind["gao_r1"]) / 0.012)
        score += gao_score * 0.25
        factors.append({
            "label": f"Intraday momentum r1 {ind['gao_r1']*100:+.2f}% (Gao 2018)",
            "value": round(gao_score * 0.25, 3),
            "pillar": "GAO_MOMENTUM",
        })
        if primary is None:
            primary = "GAO_MOMENTUM"

    # PILLAR 3: Connors RSI(2) + regime filter (feature)
    if ind["rsi2"] < 10 and ind["regime_up"]:
        connors_score = 0.30 * (10 - ind["rsi2"]) / 10
        score += connors_score * 0.15
        factors.append({
            "label": f"Connors RSI(2) {ind['rsi2']:.0f} oversold + uptrend regime",
            "value": round(connors_score * 0.15, 3),
            "pillar": "CONNORS",
        })
    elif ind["rsi2"] > 90 and not ind["regime_up"]:
        connors_score = -0.30 * (ind["rsi2"] - 90) / 10
        score += connors_score * 0.15
        factors.append({
            "label": f"Connors RSI(2) {ind['rsi2']:.0f} overbought + downtrend regime",
            "value": round(connors_score * 0.15, 3),
            "pillar": "CONNORS",
        })

    # PILLAR 4: Avellaneda-Lee volume-clock adjustment (Eq. 20)
    # On heavy-volume days, suppress mean-reversion (paper finding)
    if ind["vol_z"] > 2.5 and primary == "AL_REVERSION":
        damper = -np.sign(score) * 0.1
        score += damper
        factors.append({
            "label": f"Volume +{ind['vol_z']:.1f}σ damps reversion (AL Eq.20)",
            "value": round(damper, 3),
            "pillar": "VOLUME_FILTER",
        })

    return round(max(-1.0, min(1.0, score)), 3), factors, primary


def _kelly_size(prob: float, payoff: float, portfolio: float, atr_pct: float) -> int:
    """Half-Kelly position sizing capped by ATR vol-targeting and max pct."""
    if prob <= 0.5 or payoff <= 0:
        return 0
    full_kelly = (prob * payoff - (1 - prob)) / payoff
    kelly = max(0, KELLY_FRACTION * full_kelly)
    # Vol-target overlay: target 1% per-trade vol contribution
    if atr_pct > 0:
        vol_cap = 0.01 / atr_pct  # fraction of portfolio
        kelly = min(kelly, vol_cap)
    kelly = min(kelly, MAX_POS_PCT)
    return int(portfolio * kelly)


def _simulate_portfolio(df: pd.DataFrame, spy_ret: pd.Series,
                         sector_ret_lookup: dict[str, pd.Series]) -> dict:
    """Walk all bars, fire signals, apply triple-barrier exits. Honest trade log."""
    cash = BASE_PORTFOLIO
    closed = []
    equity_curve = []
    open_pos = []  # each: {ticker, side, score, entry_idx, entry_time, entry_price, sigma, size, primary}

    # Pre-compute for each ticker
    ticker_data = {}
    for ticker in UNIVERSE:
        try:
            if ticker not in df.columns.levels[0]:
                continue
            sub = df[ticker].dropna()
            if len(sub) < 80:
                continue
            close = sub["Close"]
            high = sub["High"]
            low = sub["Low"]
            ret = close.pct_change()
            sector = SECTORS.get(ticker, "Technology")
            sector_etf_name = SECTOR_ETF.get(sector, "XLK")
            sec_ret = sector_ret_lookup.get(sector_etf_name)
            if sec_ret is None:
                continue
            ticker_data[ticker] = {
                "close": close, "ret": ret, "high": high, "low": low,
                "sector": sector, "sec_ret": sec_ret,
                "atr": _atr(high, low, close, 20),
                "rsi2": _rsi(close, 2),
                "ma200": close.rolling(200).mean(),
                "vol_z": (sub["Volume"] - sub["Volume"].rolling(60).mean()) / sub["Volume"].rolling(60).std(),
            }
        except Exception:
            continue

    if not ticker_data:
        return {"final_equity": BASE_PORTFOLIO, "total_return": 0.0, "trades": 0,
                "wins": 0, "win_rate": 0.0, "sharpe": 0.0,
                "equity_curve": [], "trade_log": [], "by_engine": {}}

    all_times = sorted(set().union(*[td["close"].index for td in ticker_data.values()]))

    for t_idx, t in enumerate(all_times):
        # 1) Process exits (triple barrier already determined at entry; check if barrier hit)
        new_open = []
        for pos in open_pos:
            td = ticker_data.get(pos["ticker"])
            if td is None or t not in td["close"].index:
                new_open.append(pos)
                continue
            entry_idx = pos["entry_idx"]
            # Has barrier been hit yet?
            bars_since = td["close"].index.get_loc(t) - entry_idx
            if bars_since <= 0:
                new_open.append(pos)
                continue
            curr_price = float(td["close"].iloc[td["close"].index.get_loc(t)])
            entry_price = pos["entry_price"]
            if pos["side"] == "LONG":
                ret_pct = curr_price / entry_price - 1
            else:
                ret_pct = 1 - curr_price / entry_price
            pt_pct = PT_MULT * pos["sigma"] * np.sqrt(MAX_BARS)
            sl_pct = SL_MULT * pos["sigma"] * np.sqrt(MAX_BARS)
            exit_reason = None
            if ret_pct >= pt_pct:
                exit_reason = "PROFIT"
            elif ret_pct <= -sl_pct:
                exit_reason = "STOP"
            elif bars_since >= MAX_BARS:
                exit_reason = "TIME"
            if exit_reason:
                pnl = pos["size"] * ret_pct
                cash += pos["size"] + pnl
                closed.append({
                    "ticker": pos["ticker"], "side": pos["side"],
                    "score": pos["score"], "primary": pos["primary"],
                    "entry_time": pos["entry_time"].isoformat(),
                    "exit_time": t.isoformat(),
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(curr_price, 2),
                    "bars_held": bars_since,
                    "minutes_held": bars_since * 5,
                    "size": pos["size"],
                    "pnl": round(pnl, 2),
                    "return_pct": round(ret_pct, 4),
                    "exit_reason": exit_reason,
                    "win": pnl > 0,
                })
            else:
                new_open.append(pos)
        open_pos = new_open

        # 2) Look for new entries (only every 6 bars to save compute; spans full universe)
        if t_idx % 6 != 0:
            if t_idx % 30 == 0 or t_idx == len(all_times) - 1:
                pos_value = sum(p["size"] for p in open_pos)
                equity_curve.append({"ts": t.isoformat(),
                                     "equity": round(cash + pos_value, 2)})
            continue

        # Compute SPY return for this time
        try:
            spy_r_aligned = spy_ret.loc[:t].tail(70)
        except Exception:
            continue
        if len(spy_r_aligned) < 60:
            continue

        for ticker, td in ticker_data.items():
            if t not in td["close"].index:
                continue
            if any(p["ticker"] == ticker for p in open_pos):
                continue
            if cash < BASE_PORTFOLIO * 0.05:
                continue

            try:
                idx = td["close"].index.get_loc(t)
                if idx < 80:
                    continue
                # Build mini-indicator dict for this bar
                last_ret = td["ret"].iloc[max(0, idx-60):idx+1].dropna()
                last_sec = td["sec_ret"].loc[:t].tail(70)
                last_spy = spy_r_aligned

                aligned = pd.concat([last_ret, last_spy, last_sec], axis=1, join="inner")
                aligned.columns = ["stock", "spy", "sec"]
                aligned = aligned.dropna()
                if len(aligned) < 60:
                    continue
                al = compute_s_score(aligned["stock"], aligned[["spy", "sec"]], lookback=60)

                rsi2 = float(td["rsi2"].iloc[idx]) if pd.notna(td["rsi2"].iloc[idx]) else 50.0
                ma200_val = td["ma200"].iloc[idx]
                regime_up = bool(pd.notna(ma200_val) and float(td["close"].iloc[idx]) > float(ma200_val))
                atr_val = td["atr"].iloc[idx]
                if not pd.notna(atr_val):
                    continue
                atr_pct = float(atr_val) / float(td["close"].iloc[idx])
                sigma_bar = float(td["ret"].iloc[max(0, idx-60):idx+1].std())
                if sigma_bar <= 0 or sigma_bar > 0.05:
                    continue
                vz = float(td["vol_z"].iloc[idx]) if pd.notna(td["vol_z"].iloc[idx]) else 0.0

                ind = {
                    "ticker": ticker, "price": float(td["close"].iloc[idx]),
                    "atr20": float(atr_val), "sigma_bar": sigma_bar,
                    "rsi2": rsi2, "regime_up": regime_up, "vol_z": vz,
                    "s_score": al["s_score"] if al else None,
                    "kappa_ann": al["kappa_ann"] if al else None,
                    "half_life_bars": al["half_life_bars"] if al else None,
                    "gao_eligible": False, "gao_r1": None, "gao_side": None,
                }
                score, factors, primary = _meta_score(ind)
                if abs(score) < 0.50 or primary is None:
                    continue
                side = "LONG" if score > 0 else "SHORT"
                # Half-Kelly sizing
                prob = 0.50 + abs(score) * 0.15  # naive: |score|=0.5 → p=0.575, |score|=1 → p=0.65
                payoff = (PT_MULT / SL_MULT)
                size = _kelly_size(prob, payoff, BASE_PORTFOLIO, atr_pct)
                if size < 1000:
                    continue
                if size > cash:
                    continue
                # Gross exposure cap
                gross = sum(p["size"] for p in open_pos) + size
                if gross > BASE_PORTFOLIO * MAX_GROSS:
                    continue

                open_pos.append({
                    "ticker": ticker, "side": side, "score": round(score, 3),
                    "primary": primary, "entry_idx": idx,
                    "entry_time": t, "entry_price": float(td["close"].iloc[idx]),
                    "sigma": sigma_bar, "size": size,
                })
                cash -= size
            except Exception:
                continue

        if t_idx % 30 == 0 or t_idx == len(all_times) - 1:
            pos_value = sum(p["size"] for p in open_pos)
            equity_curve.append({"ts": t.isoformat(),
                                 "equity": round(cash + pos_value, 2)})

    # Close remaining
    for p in open_pos:
        cash += p["size"]

    n = len(closed)
    wins = sum(1 for c in closed if c["win"])
    win_rate = wins / n if n else 0.0
    rets = [c["return_pct"] for c in closed]
    sharpe = float(np.mean(rets) / np.std(rets) * sqrt(78 * 252 / 12)) if len(rets) > 1 and np.std(rets) > 0 else 0.0

    # Breakdown by engine
    by_engine = {}
    for c in closed:
        e = c.get("primary", "?")
        d = by_engine.setdefault(e, {"trades": 0, "wins": 0, "pnl": 0.0})
        d["trades"] += 1
        if c["win"]:
            d["wins"] += 1
        d["pnl"] += c["pnl"]
    for e, d in by_engine.items():
        d["win_rate"] = round(d["wins"] / d["trades"], 3) if d["trades"] else 0.0
        d["pnl"] = round(d["pnl"], 2)

    return {
        "final_equity": round(cash, 2),
        "total_return": round(cash / BASE_PORTFOLIO - 1, 4),
        "trades": n, "wins": wins,
        "win_rate": round(win_rate, 4), "sharpe": round(sharpe, 3),
        "equity_curve": equity_curve,
        "trade_log": sorted(closed, key=lambda x: x["exit_time"], reverse=True)[:30],
        "by_engine": by_engine,
    }


_portfolio_cache: dict = {}
_portfolio_cache_ts: float = 0.0
PORTFOLIO_CACHE_TTL = 1800  # 30 min — heavy computation, run infrequently


def _get_portfolio_cached(df, spy_ret, sector_ret_lookup) -> dict:
    """Return cached portfolio result; recompute in background if stale."""
    global _portfolio_cache, _portfolio_cache_ts
    import threading
    now = time.time()
    if _portfolio_cache and (now - _portfolio_cache_ts) < PORTFOLIO_CACHE_TTL:
        return _portfolio_cache

    def _run():
        global _portfolio_cache, _portfolio_cache_ts
        try:
            result = _simulate_portfolio(df, spy_ret, sector_ret_lookup)
            _portfolio_cache = result
            _portfolio_cache_ts = time.time()
        except Exception as e:
            pass  # keep old cache on error

    if not _portfolio_cache:
        # First call: return stub immediately, compute in background
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return {
            "final_equity": 1_000_000, "total_return": 0.0,
            "trades": 0, "wins": 0, "win_rate": 0.0, "sharpe": 0.0,
            "equity_curve": [], "trade_log": [], "by_engine": {},
            "status": "computing",
        }
    else:
        # Stale: return old data, refresh async
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        _portfolio_cache["status"] = "refreshing"
        return _portfolio_cache



def scan_market() -> dict[str, Any]:
    df = _fetch_bars()
    if df is None or df.empty:
        return {"error": "no_data", "tickers": [], "signals": [], "sectors": [],
                "market": {}, "portfolio": {}, "notifications": {"configured": False},
                "as_of": datetime.utcnow().isoformat()}

    # Pre-compute factor returns
    try:
        spy_close = df["SPY"]["Close"].dropna()
        spy_ret = spy_close.pct_change().dropna()
    except Exception:
        return {"error": "no_spy_data", "tickers": [], "signals": [], "sectors": [],
                "market": {}, "portfolio": {},
                "notifications": {"configured": False},
                "as_of": datetime.utcnow().isoformat()}

    sector_ret_lookup = {}
    for sector, etf in SECTOR_ETF.items():
        try:
            if etf in df.columns.levels[0]:
                r = df[etf]["Close"].dropna().pct_change().dropna()
                sector_ret_lookup[etf] = r
        except Exception:
            pass

    # Compute indicators + signals for each ticker
    indicators = []
    signals = []
    for ticker in UNIVERSE:
        ind = _compute_signals_for_ticker(df, ticker, spy_ret, sector_ret_lookup)
        if ind is None:
            continue
        score, factors, primary = _meta_score(ind)
        ind["score"] = score
        ind["factors"] = factors
        ind["primary"] = primary
        indicators.append(ind)

        if abs(score) >= 0.50 and primary is not None:
            side = "LONG" if score > 0 else "SHORT"
            prob = 0.50 + abs(score) * 0.15
            atr_pct = ind["atr20"] / ind["price"]
            size = _kelly_size(prob, 1.0, BASE_PORTFOLIO, atr_pct)
            sig = {
                "ticker": ticker, "sector": ind["sector"],
                "score": score, "side": side, "primary": primary,
                "factors": factors,
                "price": ind["price"], "rsi2": ind["rsi2"],
                "s_score": ind["s_score"], "half_life_bars": ind["half_life_bars"],
                "atr20": ind["atr20"],
                "intraday_ret": 0.0,  # legacy compat for UI
                "vol_z": ind["vol_z"],
                "suggested_size": size,
                "estimated_prob": round(prob, 3),
                "exit_clock": (datetime.utcnow() + timedelta(minutes=60)).strftime("%H:%M ET"),
                "timestamp": ind["last_ts"],
                "session": ind["session"],
                "high_conviction": abs(score) >= NOTIFY_THRESHOLD,
                "notified": False, "news": [], "ai": None,
            }
            if sig["high_conviction"]:
                sig["news"] = fetch_news(ticker, hours=24, limit=5)
                sig["ai"] = ai_explain(sig, sig["news"])
                sig["notified"] = send_telegram(sig)
            signals.append(sig)

    indicators.sort(key=lambda x: -abs(x.get("score", 0)))
    signals.sort(key=lambda x: -abs(x["score"]))

    # Sector aggregates (intraday return proxy)
    by_sec = {}
    for ind in indicators:
        sec = ind["sector"]
        by_sec.setdefault(sec, []).append(ind.get("score", 0))
    sectors = [{"sector": s, "avg_score": round(float(np.mean(scores)), 3),
                "count": len(scores)}
               for s, scores in by_sec.items()]
    sectors.sort(key=lambda x: x["avg_score"])

    if indicators:
        market_avg_s = float(np.mean([abs(i.get("s_score") or 0) for i in indicators]))
        avg_rsi2 = float(np.mean([i["rsi2"] for i in indicators]))
        n_uptrend = sum(1 for i in indicators if i["regime_up"])
    else:
        market_avg_s = avg_rsi2 = 0
        n_uptrend = 0

    from backend.app.services.notification_service import notification_status
    return {
        "tickers": indicators,
        "signals": signals,
        "sectors": sectors,
        "market": {
            "avg_abs_s_score": round(market_avg_s, 2),
            "avg_rsi2": round(avg_rsi2, 1),
            "n_uptrend": n_uptrend,
            "n_tickers": len(indicators),
            "spy_price": round(float(spy_close.iloc[-1]), 2) if len(spy_close) > 0 else 0,
        },
        "portfolio": _get_portfolio_cached(df, spy_ret, sector_ret_lookup),
        "notifications": notification_status(),
        "thresholds": {
            "signal": 0.50, "notify": NOTIFY_THRESHOLD,
            "s_open": S_OPEN, "kappa_min": KAPPA_MIN,
            "pt_mult": PT_MULT, "sl_mult": SL_MULT, "max_bars": MAX_BARS,
        },
        "as_of": datetime.utcnow().isoformat(),
    }
