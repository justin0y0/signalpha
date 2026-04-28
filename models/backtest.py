from __future__ import annotations

from math import sqrt

import numpy as np
import pandas as pd


def sharpe_ratio(returns: pd.Series, annualization: int = 252) -> float:
    returns = returns.astype(float)
    std = returns.std(ddof=0)
    if std == 0 or np.isnan(std):
        return 0.0
    return float(returns.mean() / std * sqrt(annualization))
