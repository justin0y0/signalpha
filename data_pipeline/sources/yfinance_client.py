from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from data_pipeline.feature_engineer import FeatureEngineer


class YFinanceClient:
    def __init__(self):
        import yfinance as yf  # imported lazily so tests do not require the dependency

        self.yf = yf
        self.fe = FeatureEngineer()

    def history(self, ticker: str, start: str | None = None, end: str | None = None, period: str = "2y") -> pd.DataFrame:
        if start or end:
            data = self.yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
        else:
            data = self.yf.Ticker(ticker).history(period=period, auto_adjust=False)
        if data.empty:
            return data
        data = data.rename_axis("date").reset_index()
        data["date"] = pd.to_datetime(data["date"]).dt.tz_localize(None)
        return data

    def technical_snapshot(self, history: pd.DataFrame) -> dict[str, Any]:
        if history.empty:
            return {"rsi_14": None, "macd": None, "macd_signal": None, "bollinger_position": None}
        close = history["Close"].astype(float)
        macd = self.fe.compute_macd(close)
        return {
            "rsi_14": float(self.fe.compute_rsi(close).iloc[-1]),
            "macd": float(macd["macd"].iloc[-1]),
            "macd_signal": float(macd["macd_signal"].iloc[-1]),
            "bollinger_position": float(self.fe.compute_bollinger_position(close).iloc[-1]),
        }

    def price_window_snapshot(self, history: pd.DataFrame, earnings_date: datetime) -> dict[str, Any]:
        if history.empty:
            return {}
        frame = history.copy()
        frame = frame[frame["date"] < pd.Timestamp(earnings_date)].sort_values("date")
        if frame.empty:
            return {}
        close = frame["Close"].astype(float).reset_index(drop=True)
        price_t0 = float(close.iloc[-1])
        def get_price(days_back: int) -> float | None:
            return float(close.iloc[-days_back]) if len(close) >= days_back else None
        def get_return(days_back: int) -> float | None:
            if len(close) <= days_back:
                return None
            base = float(close.iloc[-(days_back + 1)])
            return None if base == 0 else float(close.iloc[-1] / base - 1)
        price_1d_pre = get_price(1)
        price_5d_pre = get_price(5)
        price_10d_pre = get_price(10)
        price_20d_pre = get_price(20)
        price_60d_pre = get_price(60)
        high_52w = float(close.tail(252).max()) if len(close) else None
        low_52w = float(close.tail(252).min()) if len(close) else None
        volume = frame["Volume"].astype(float).reset_index(drop=True)
        return {
            "price_t0": price_t0,
            "price_1d_pre": price_1d_pre,
            "price_5d_pre": price_5d_pre,
            "price_10d_pre": price_10d_pre,
            "price_20d_pre": price_20d_pre,
            "price_60d_pre": price_60d_pre,
            "ret_1d_pre": get_return(1),
            "ret_5d_pre": get_return(5),
            "ret_10d_pre": get_return(10),
            "ret_20d_pre": get_return(20),
            "ret_60d_pre": get_return(60),
            "volume_t1": float(volume.iloc[-1]) if not volume.empty else None,
            "volume_20d_avg": float(volume.tail(20).mean()) if len(volume) >= 20 else None,
            "high_52w": high_52w,
            "low_52w": low_52w,
        }

    def options_snapshot(self, ticker: str) -> dict[str, Any]:
        stock = self.yf.Ticker(ticker)
        expiries = getattr(stock, "options", [])
        if not expiries:
            return {
                "atm_iv": None,
                "put_call_ratio": None,
                "straddle_price": None,
                "iv_25d_put": None,
                "iv_25d_call": None,
                "iv_52w_low": None,
                "iv_52w_high": None,
            }
        expiry = expiries[0]
        chain = stock.option_chain(expiry)
        calls = chain.calls.copy()
        puts = chain.puts.copy()
        info = stock.fast_info or {}
        spot = info.get("lastPrice") or info.get("last_price") or None
        if spot is None:
            hist = stock.history(period="5d")
            if not hist.empty:
                spot = float(hist["Close"].iloc[-1])
        if spot is None or calls.empty or puts.empty:
            return {
                "atm_iv": None,
                "put_call_ratio": None,
                "straddle_price": None,
                "iv_25d_put": None,
                "iv_25d_call": None,
                "iv_52w_low": None,
                "iv_52w_high": None,
            }
        calls["distance"] = (calls["strike"] - spot).abs()
        puts["distance"] = (puts["strike"] - spot).abs()
        atm_call = calls.sort_values("distance").iloc[0]
        atm_put = puts.sort_values("distance").iloc[0]
        all_iv = pd.concat([calls["impliedVolatility"], puts["impliedVolatility"]]).replace([np.inf, -np.inf], np.nan).dropna()
        return {
            "stock_price": float(spot),
            "atm_iv": float(np.nanmean([atm_call.get("impliedVolatility"), atm_put.get("impliedVolatility")])),
            "put_call_ratio": float(len(puts) / max(len(calls), 1)),
            "straddle_price": float((atm_call.get("lastPrice") or 0.0) + (atm_put.get("lastPrice") or 0.0)),
            "iv_25d_put": float(atm_put.get("impliedVolatility")) if pd.notna(atm_put.get("impliedVolatility")) else None,
            "iv_25d_call": float(atm_call.get("impliedVolatility")) if pd.notna(atm_call.get("impliedVolatility")) else None,
            "iv_52w_low": float(all_iv.min()) if not all_iv.empty else None,
            "iv_52w_high": float(all_iv.max()) if not all_iv.empty else None,
        }

    def outcome_snapshot(self, history: pd.DataFrame, earnings_date: datetime) -> dict[str, Any]:
        if history.empty:
            return {}
        frame = history.copy().sort_values("date")
        frame = frame[frame["date"] >= pd.Timestamp(earnings_date)].reset_index(drop=True)
        if frame.empty:
            return {}
        open_t1 = float(frame.iloc[0]["Open"])
        close_t1 = float(frame.iloc[0]["Close"])
        prev = history[history["date"] < pd.Timestamp(earnings_date)].sort_values("date")
        prev_close = float(prev.iloc[-1]["Close"]) if not prev.empty else None

        def safe_future(idx: int) -> float | None:
            if len(frame) > idx:
                return float(frame.iloc[idx]["Close"])
            return None

        t5 = safe_future(4)
        t20 = safe_future(19)
        high = frame.head(20)["High"].max() if len(frame) else None
        low = frame.head(20)["Low"].min() if len(frame) else None
        gap_pct = None if prev_close in (None, 0) else open_t1 / prev_close - 1
        t1_close_return = None if prev_close in (None, 0) else close_t1 / prev_close - 1
        t5_return = None if prev_close in (None, 0) or t5 is None else t5 / prev_close - 1
        t20_return = None if prev_close in (None, 0) or t20 is None else t20 / prev_close - 1
        intraday = None if open_t1 in (None, 0) else max(abs(frame.iloc[0]["High"] / open_t1 - 1), abs(frame.iloc[0]["Low"] / open_t1 - 1))
        gap_direction = "up" if gap_pct and gap_pct > 0 else "down" if gap_pct and gap_pct < 0 else "flat"
        gap_filled = None
        if prev_close is not None and len(frame):
            gap_filled = bool(frame.head(20)["Low"].min() <= prev_close <= frame.head(20)["High"].max())
        return {
            "actual_t1_gap_pct": gap_pct,
            "actual_t1_close_return": t1_close_return,
            "actual_t5_return": t5_return,
            "actual_t20_return": t20_return,
            "max_intraday_move": float(intraday) if intraday is not None else None,
            "gap_direction": gap_direction,
            "gap_filled": gap_filled,
            "convergence_low": float(low) if low is not None else None,
            "convergence_high": float(high) if high is not None else None,
            "convergence_range": None if high is None or low is None else float(high - low),
        }
