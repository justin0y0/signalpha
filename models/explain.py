from __future__ import annotations

import numpy as np
import pandas as pd


def top_feature_importance_from_values(feature_names: list[str], values: np.ndarray, top_n: int = 20) -> list[dict]:
    ranking = sorted(zip(feature_names, values), key=lambda item: abs(float(item[1])), reverse=True)
    return [{"feature": feature, "importance": float(value)} for feature, value in ranking[:top_n]]


def mean_abs_frame(frame: pd.DataFrame, top_n: int = 20) -> list[dict]:
    scores = frame.abs().mean().sort_values(ascending=False).head(top_n)
    return [{"feature": str(index), "importance": float(value)} for index, value in scores.items()]
