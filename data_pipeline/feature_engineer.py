from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import percentileofscore


@dataclass
class FeatureEngineer:
    default_fill_value: float = 0.0
    global_medians_: dict[str, float] = field(default_factory=dict)
    sector_medians_: dict[str, dict[str, float]] = field(default_factory=dict)

    @staticmethod
    def _first(raw: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in raw and raw[key] is not None:
                return raw[key]
        return None

    @staticmethod
    def safe_divide(numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator in (None, 0):
            return None
        return float(numerator) / float(denominator)

    @classmethod
    def pct_surprise(cls, actual: float | None, estimate: float | None) -> float | None:
        if actual is None or estimate in (None, 0):
            return None
        return (float(actual) - float(estimate)) / abs(float(estimate))

    @staticmethod
    def pct_return(current: float | None, prior: float | None) -> float | None:
        if current is None or prior in (None, 0):
            return None
        return float(current) / float(prior) - 1.0

    @staticmethod
    def list_mean(values: list[float] | None) -> float | None:
        cleaned = [float(v) for v in (values or []) if v is not None and not pd.isna(v)]
        return mean(cleaned) if cleaned else None

    @staticmethod
    def list_std(values: list[float] | None) -> float | None:
        cleaned = [float(v) for v in (values or []) if v is not None and not pd.isna(v)]
        if len(cleaned) < 2:
            return 0.0 if cleaned else None
        return pstdev(cleaned)

    def engineer_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        price_t0 = self._first(raw, "price_t0", "price_0d_pre", "price_1d_pre")
        price_t5 = self._first(raw, "price_t5", "price_5d_pre")
        price_t20 = self._first(raw, "price_t20", "price_20d_pre")
        stock_20d_return = self._first(raw, "ret_20d_pre", "stock_20d_return")
        spy_20d_return = self._first(raw, "spy_ret_20d")
        current_iv = self._first(raw, "atm_iv", "current_iv")
        iv_low = self._first(raw, "iv_52w_low")
        iv_high = self._first(raw, "iv_52w_high")
        vix_history = self._first(raw, "vix_history") or []
        current_vix = self._first(raw, "vix", "current_vix")
        beats = self._first(raw, "beats")
        total_quarters = self._first(raw, "total_quarters")
        up_revisions = self._first(raw, "up_revisions") or 0
        down_revisions = self._first(raw, "down_revisions") or 0
        short_shares = self._first(raw, "short_shares")
        float_shares = self._first(raw, "float_shares")
        expected_move_pct = self.safe_divide(self._first(raw, "straddle_price"), self._first(raw, "stock_price", "price_t0"))

        features: dict[str, Any] = {
            "eps_surprise_pct": self.pct_surprise(self._first(raw, "actual_eps", "eps_actual"), self._first(raw, "est_eps", "eps_estimate")),
            "rev_surprise_pct": self.pct_surprise(
                self._first(raw, "actual_rev", "rev_actual", "revenue_actual"),
                self._first(raw, "est_rev", "rev_estimate", "revenue_estimate"),
            ),
            "guidance_delta": self.pct_surprise(
                self._first(raw, "fwd_guidance", "forward_revenue_guidance", "forward_eps_guidance"),
                self._first(raw, "street_est", "street_estimate"),
            ),
            "pre_earn_momentum_20d": self.pct_return(price_t0, price_t20),
            "pre_earn_momentum_5d": self.pct_return(price_t0, price_t5),
            "relative_strength_vs_spy": None if stock_20d_return is None or spy_20d_return is None else stock_20d_return - spy_20d_return,
            "iv_rank": None if current_iv is None or iv_low is None or iv_high in (None, iv_low) else (current_iv - iv_low) / (iv_high - iv_low),
            "expected_move_pct": expected_move_pct,
            "put_call_skew": None
            if self._first(raw, "iv_25d_put") is None or self._first(raw, "iv_25d_call") is None
            else self._first(raw, "iv_25d_put") - self._first(raw, "iv_25d_call"),
            "vix_percentile": None
            if current_vix is None or not vix_history
            else percentileofscore(vix_history, current_vix, kind="weak") / 100.0,
            "yield_curve_slope": None
            if self._first(raw, "treasury_10y", "yield_10y") is None or self._first(raw, "treasury_2y", "yield_2y") is None
            else self._first(raw, "treasury_10y", "yield_10y") - self._first(raw, "treasury_2y", "yield_2y"),
            "market_regime": 1
            if self._first(raw, "spy_price") is not None and self._first(raw, "spy_200ma") is not None and self._first(raw, "spy_price") > self._first(raw, "spy_200ma")
            else -1
            if self._first(raw, "spy_price") is not None and self._first(raw, "spy_200ma") is not None
            else None,
            "hist_beat_rate": self.safe_divide(beats, total_quarters),
            "hist_avg_reaction": self.list_mean(self._first(raw, "last_8q_reactions") or []),
            "hist_reaction_std": self.list_std(self._first(raw, "last_8q_reactions") or []),
            "sector_median_reaction": self._first(raw, "sector_peer_median", "sector_median_reaction"),
            "analyst_revision_ratio": self.safe_divide(up_revisions, up_revisions + down_revisions),
            "short_interest_pct": self.safe_divide(short_shares, float_shares),
            "volume_anomaly": self.safe_divide(self._first(raw, "volume_t1"), self._first(raw, "volume_20d_avg")),
            "dist_52w_high": self.pct_return(self._first(raw, "price_t0", "stock_price"), self._first(raw, "high_52w")),
            "dist_52w_low": self.pct_return(self._first(raw, "price_t0", "stock_price"), self._first(raw, "low_52w")),
            "rsi_14": self._first(raw, "rsi_14"),
            "macd": self._first(raw, "macd"),
            "macd_signal": self._first(raw, "macd_signal"),
            "bollinger_position": self._first(raw, "bollinger_position"),
            "transcript_sentiment": self._first(raw, "transcript_sentiment"),
            "analyst_consensus_score": self._first(raw, "analyst_consensus_score"),
            "put_call_ratio": self._first(raw, "put_call_ratio"),
            "social_sentiment_score": self._first(raw, "social_sentiment_score"),
            "price_t0": price_t0,
        }
        features["data_completeness"] = self.calculate_data_completeness(features)
        return features

    @staticmethod
    def calculate_data_completeness(features: dict[str, Any]) -> float:
        keys = [key for key in features.keys() if key != "data_completeness"]
        if not keys:
            return 0.0
        populated = sum(1 for key in keys if features[key] is not None and not pd.isna(features[key]))
        return populated / len(keys)

    @staticmethod
    def compute_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        delta = prices.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def compute_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return pd.DataFrame({"macd": macd_line, "macd_signal": signal_line})

    @staticmethod
    def compute_bollinger_position(prices: pd.Series, window: int = 20, n_std: int = 2) -> pd.Series:
        mean_ = prices.rolling(window).mean()
        std_ = prices.rolling(window).std(ddof=0)
        lower = mean_ - n_std * std_
        upper = mean_ + n_std * std_
        denom = (upper - lower).replace(0, np.nan)
        pos = (prices - lower) / denom
        return pos.clip(0, 1).fillna(0.5)

    def fit_imputer(self, frame: pd.DataFrame, sector_col: str = "sector") -> None:
        numeric_cols = frame.select_dtypes(include=[np.number]).columns.tolist()
        self.global_medians_ = frame[numeric_cols].median(numeric_only=True).fillna(self.default_fill_value).to_dict()
        self.sector_medians_ = {}
        if sector_col in frame.columns:
            for sector, group in frame.groupby(sector_col):
                self.sector_medians_[str(sector)] = (
                    group[numeric_cols].median(numeric_only=True).fillna(self.default_fill_value).to_dict()
                )

    def impute_row(self, row: dict[str, Any], sector: str | None = None) -> dict[str, Any]:
        sector_defaults = self.sector_medians_.get(sector or "", {})
        result = dict(row)
        for key, value in row.items():
            if value is None or (isinstance(value, float) and np.isnan(value)):
                result[key] = sector_defaults.get(key, self.global_medians_.get(key, self.default_fill_value))
        result["data_completeness"] = row.get("data_completeness", self.calculate_data_completeness(row))
        return result

    def build_feature_frame(self, raw_events: list[dict[str, Any]], sector_col: str = "sector") -> pd.DataFrame:
        rows = []
        for raw in raw_events:
            engineered = self.engineer_event(raw)
            engineered[sector_col] = raw.get(sector_col)
            engineered["ticker"] = raw.get("ticker")
            engineered["earnings_date"] = raw.get("earnings_date")
            rows.append(engineered)
        frame = pd.DataFrame(rows)
        if not frame.empty:
            self.fit_imputer(frame, sector_col=sector_col)
            frame = pd.DataFrame([
                self.impute_row(record, sector=record.get(sector_col)) for record in frame.to_dict(orient="records")
            ])
        return frame
