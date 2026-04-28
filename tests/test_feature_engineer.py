from __future__ import annotations

import math

import pandas as pd

from data_pipeline.feature_engineer import FeatureEngineer


def test_engineers_core_surprise_and_momentum_features() -> None:
    fe = FeatureEngineer()
    raw = {
        "actual_eps": 1.20,
        "est_eps": 1.00,
        "actual_rev": 110.0,
        "est_rev": 100.0,
        "price_t0": 120.0,
        "price_t5": 100.0,
        "price_t20": 80.0,
        "ret_20d_pre": 0.15,
        "spy_ret_20d": 0.05,
        "atm_iv": 0.50,
        "iv_52w_low": 0.20,
        "iv_52w_high": 0.80,
        "straddle_price": 6.0,
        "stock_price": 120.0,
        "vix": 22,
        "vix_history": [10, 12, 14, 20, 22, 30],
        "treasury_10y": 4.3,
        "treasury_2y": 4.0,
        "spy_price": 510,
        "spy_200ma": 500,
        "beats": 6,
        "total_quarters": 8,
        "last_8q_reactions": [0.08, -0.02, 0.03, 0.01],
        "sector_peer_median": 0.025,
        "up_revisions": 3,
        "down_revisions": 1,
        "short_shares": 5,
        "float_shares": 100,
    }
    features = fe.engineer_event(raw)

    assert math.isclose(features["eps_surprise_pct"], 0.20, rel_tol=1e-9)
    assert math.isclose(features["rev_surprise_pct"], 0.10, rel_tol=1e-9)
    assert math.isclose(features["pre_earn_momentum_5d"], 0.20, rel_tol=1e-9)
    assert math.isclose(features["pre_earn_momentum_20d"], 0.50, rel_tol=1e-9)
    assert math.isclose(features["relative_strength_vs_spy"], 0.10, rel_tol=1e-9)
    assert math.isclose(features["iv_rank"], 0.50, rel_tol=1e-9)
    assert math.isclose(features["expected_move_pct"], 0.05, rel_tol=1e-9)
    assert math.isclose(features["yield_curve_slope"], 0.30, rel_tol=1e-9)
    assert features["market_regime"] == 1
    assert math.isclose(features["hist_beat_rate"], 0.75, rel_tol=1e-9)
    assert math.isclose(features["analyst_revision_ratio"], 0.75, rel_tol=1e-9)
    assert math.isclose(features["short_interest_pct"], 0.05, rel_tol=1e-9)
    assert 0.0 < features["data_completeness"] <= 1.0


def test_imputation_uses_sector_medians_when_available() -> None:
    fe = FeatureEngineer()
    frame = pd.DataFrame(
        [
            {"sector": "Technology", "eps_surprise_pct": 0.15, "iv_rank": 0.40},
            {"sector": "Technology", "eps_surprise_pct": 0.25, "iv_rank": 0.60},
            {"sector": "Healthcare", "eps_surprise_pct": 0.05, "iv_rank": 0.30},
        ]
    )
    fe.fit_imputer(frame)
    result = fe.impute_row({"eps_surprise_pct": None, "iv_rank": None}, sector="Technology")

    assert math.isclose(result["eps_surprise_pct"], 0.20, rel_tol=1e-9)
    assert math.isclose(result["iv_rank"], 0.50, rel_tol=1e-9)


def test_technical_indicator_helpers_return_finite_values() -> None:
    fe = FeatureEngineer()
    prices = pd.Series([100 + i + (i % 3) for i in range(60)], dtype=float)

    rsi = fe.compute_rsi(prices)
    macd = fe.compute_macd(prices)
    bollinger = fe.compute_bollinger_position(prices)

    assert rsi.notna().all()
    assert macd["macd"].notna().sum() > 0
    assert macd["macd_signal"].notna().sum() > 0
    assert bollinger.notna().all()
