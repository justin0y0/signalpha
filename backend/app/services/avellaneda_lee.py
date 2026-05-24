"""Avellaneda-Lee residual mean-reversion engine (Quantitative Finance 2010).

Each stock's return is regressed against factor ETFs (SPY + sector ETF).
The residual is modeled as Ornstein-Uhlenbeck:
  dX = κ(m - X) dt + σ dW
We compute a standardized s-score:
  s = (X - m) / σ_eq    where σ_eq = σ / sqrt(2κ)

Entry/exit (paper Eq. 16):
  s > +1.25 → open SHORT      s < -1.25 → open LONG
  s < +0.75 → close SHORT     s > -0.50 → close LONG

Only trade if κ > κ_min (mean reversion fast enough to fit holding period).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

SECTOR_ETF = {
    "Technology": "XLK", "Communication": "XLC", "Consumer": "XLY",
    "Financial": "XLF", "Healthcare": "XLV", "Energy": "XLE",
    "Industrials": "XLI", "Materials": "XLB", "Utilities": "XLU",
    "Real Estate": "XLRE", "Staples": "XLP",
}


def _ols(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Plain OLS via normal equations. Returns betas."""
    Xb = np.column_stack([np.ones(len(X)), X])
    try:
        beta, *_ = np.linalg.lstsq(Xb, y, rcond=None)
        return beta
    except Exception:
        return np.zeros(X.shape[1] + 1)


def _fit_ou(residuals: np.ndarray) -> dict | None:
    """Fit AR(1) on cumulative residual, extract κ, m, σ_eq.
    Returns None if fit is bad (non-stationary or too slow)."""
    X = np.cumsum(residuals)
    if len(X) < 30:
        return None
    Y = X[1:]
    Z = X[:-1]
    if np.std(Z) < 1e-9:
        return None
    # Regress Y on Z
    n = len(Z)
    Zbar = Z.mean()
    Ybar = Y.mean()
    cov = np.sum((Z - Zbar) * (Y - Ybar)) / n
    var = np.sum((Z - Zbar) ** 2) / n
    if var < 1e-12:
        return None
    b = cov / var
    a = Ybar - b * Zbar
    if not (0 < b < 1):
        return None  # non-stationary, can't mean-revert
    kappa = -np.log(b) * 78 * 252 / 78  # convert to "per year" using 5-min bars
    # For 5-min bars: 78 bars/day × 252 days = 19656 bars/yr
    # so kappa_annual = -log(b) × 19656
    kappa = -np.log(b) * 19656
    if kappa <= 0:
        return None
    m = a / (1 - b)
    resid_var = np.var(Y - a - b * Z)
    if resid_var < 1e-12:
        return None
    sigma_eq = np.sqrt(resid_var / (1 - b ** 2))
    return {"kappa": float(kappa), "m": float(m), "sigma_eq": float(sigma_eq),
            "X_last": float(X[-1]), "half_life_bars": float(np.log(2) / -np.log(b))}


def compute_s_score(stock_returns: pd.Series, factor_returns: pd.DataFrame,
                    lookback: int = 60) -> dict | None:
    """Compute s-score for one stock against factor ETFs.

    Args:
        stock_returns: stock's 5-min returns
        factor_returns: DataFrame with columns SPY + sector ETF returns, same index
        lookback: bars to use for regression + OU fit

    Returns dict with s_score, kappa, half_life, beta_market, beta_sector — or None.
    """
    if len(stock_returns) < lookback + 5:
        return None
    y = stock_returns.iloc[-lookback:].values
    X = factor_returns.iloc[-lookback:].values
    if np.any(np.isnan(y)) or np.any(np.isnan(X)):
        return None
    betas = _ols(y, X)
    resid = y - betas[0] - X @ betas[1:]
    ou = _fit_ou(resid)
    if ou is None:
        return None
    s = (ou["X_last"] - ou["m"]) / ou["sigma_eq"] if ou["sigma_eq"] > 1e-9 else 0.0
    return {
        "s_score": float(s),
        "kappa_ann": ou["kappa"],
        "half_life_bars": ou["half_life_bars"],
        "beta_market": float(betas[1]) if len(betas) > 1 else 0.0,
        "beta_sector": float(betas[2]) if len(betas) > 2 else 0.0,
        "m": ou["m"],
        "sigma_eq": ou["sigma_eq"],
    }
