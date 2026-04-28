from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, mean_absolute_error, precision_recall_fscore_support, root_mean_squared_error
from sqlalchemy import create_engine

from models.backtest import sharpe_ratio
from models.dataset import expand_feature_payload, label_direction, label_direction_adaptive, walk_forward_splits
from models.ensemble import ModelEnsemble
from models.registry import ModelRegistry

MIN_ROWS_PER_SECTOR = 40


def _prepare_training_frame(database_url: str) -> pd.DataFrame:
    engine = create_engine(database_url)
    query = """
    SELECT
        e.ticker,
        e.earnings_date,
        e.sector,
        p.feature_payload,
        o.actual_t1_close_return,
        o.actual_t5_return,
        o.actual_t20_return,
        o.convergence_low,
        o.convergence_high
    FROM price_features p
    JOIN outcomes o
      ON p.ticker = o.ticker
     AND p.earnings_date = o.earnings_date
    JOIN earnings_events e
      ON p.ticker = e.ticker
     AND p.earnings_date = e.earnings_date
    WHERE p.feature_payload IS NOT NULL
      AND o.actual_t1_close_return IS NOT NULL
      AND o.convergence_low IS NOT NULL
      AND o.convergence_high IS NOT NULL
    ORDER BY e.earnings_date ASC
    """
    frame = pd.read_sql(query, engine)
    if frame.empty:
        return frame
    frame["earnings_date"] = pd.to_datetime(frame["earnings_date"])
    expanded = expand_feature_payload(frame, payload_col="feature_payload")
    expanded["direction_label"] = expanded["actual_t1_close_return"].astype(float).apply(label_direction)
    expanded["magnitude_target"] = expanded["actual_t1_close_return"].astype(float).abs()
    return expanded


def _evaluate_sector(frame: pd.DataFrame, sector: str) -> dict[str, Any]:
    candidate_cols = [
        col
        for col in frame.columns
        if col
        not in {
            "ticker",
            "earnings_date",
            "sector",
            "actual_t1_close_return",
            "actual_t5_return",
            "actual_t20_return",
            "convergence_low",
            "convergence_high",
            "direction_label",
            "magnitude_target",
        }
        and pd.api.types.is_numeric_dtype(frame[col])
    ]
    # Drop features that are >=70% missing (mostly empty FMP fields adding noise)
    feature_cols = [c for c in candidate_cols if frame[c].notna().mean() >= 0.30]
    subset = frame[["ticker", "earnings_date", "sector", "actual_t1_close_return", "actual_t5_return", "actual_t20_return", "convergence_low", "convergence_high", "direction_label", "magnitude_target", *feature_cols]].copy()
    subset = subset.replace([np.inf, -np.inf], np.nan)
    subset = subset.sort_values("earnings_date").reset_index(drop=True)

    y_true_dir: list[str] = []
    y_pred_dir: list[str] = []
    y_true_mag: list[float] = []
    y_pred_mag: list[float] = []
    strategy_returns: list[float] = []

    for split in walk_forward_splits(subset, min_train_size=min(MIN_ROWS_PER_SECTOR, max(20, len(subset) // 2)), test_window=max(5, len(subset) // 10), step=max(5, len(subset) // 10)):
        train = subset.iloc[split.train_index].copy()
        test = subset.iloc[split.test_index]
        
        # Moderate upsampling: bring minority classes up to 70% of majority class size.
        # Full balancing (100%) over-amplifies UP/DOWN; 70% is a good compromise between
        # making the model see them often enough vs preserving FLAT's natural statistical edge.
        class_counts = train["direction_label"].value_counts()
        max_class_size = class_counts.max()
        target_size = max_class_size  # full balance to 1:1:1
        balanced_parts = []
        for label, count in class_counts.items():
            class_subset = train[train["direction_label"] == label]
            if count < target_size:
                upsampled = class_subset.sample(n=target_size, replace=True, random_state=42)
                balanced_parts.append(upsampled)
            else:
                balanced_parts.append(class_subset)
        train_balanced = pd.concat(balanced_parts).sample(frac=1, random_state=42).reset_index(drop=True)
        
        model = ModelEnsemble(sector=sector, model_version=datetime.utcnow().strftime("%Y%m%d%H%M%S"))
        model.fit(
            train_balanced[feature_cols],
            train_balanced["direction_label"],
            train_balanced["magnitude_target"],
            train_balanced["convergence_low"],
            train_balanced["convergence_high"],
            train_balanced[["ticker", "earnings_date", "sector", "actual_t1_close_return", "actual_t5_return", "actual_t20_return"]],
        )
        for _, row in test.iterrows():
            x = pd.DataFrame([{col: row[col] for col in feature_cols}])
            pred = model.predict(x)
            y_true_dir.append(row["direction_label"])
            y_pred_dir.append(pred["predicted_direction"])
            y_true_mag.append(float(row["magnitude_target"]))
            y_pred_mag.append(float(pred["expected_move_pct"]))
            signal = 1 if pred["direction_probabilities"]["up"] >= 0.55 else -1 if pred["direction_probabilities"]["down"] >= 0.55 else 0
            strategy_returns.append(signal * float(row["actual_t1_close_return"]))

    if not y_true_dir:
        return {
            "accuracy": 0.0,
            "precision_weighted": 0.0,
            "recall_weighted": 0.0,
            "f1_weighted": 0.0,
            "mae": 0.0,
            "rmse": 0.0,
            "sharpe_ratio": 0.0,
            "confusion_matrix": [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
        }

    precision, recall, f1, _ = precision_recall_fscore_support(y_true_dir, y_pred_dir, average="weighted", zero_division=0)
    return {
        "accuracy": float(accuracy_score(y_true_dir, y_pred_dir)),
        "precision_weighted": float(precision),
        "recall_weighted": float(recall),
        "f1_weighted": float(f1),
        "mae": float(mean_absolute_error(y_true_mag, y_pred_mag)),
        "rmse": float(root_mean_squared_error(y_true_mag, y_pred_mag)),
        "sharpe_ratio": float(sharpe_ratio(pd.Series(strategy_returns))),
        "confusion_matrix": confusion_matrix(y_true_dir, y_pred_dir, labels=["DOWN", "FLAT", "UP"]).tolist(),
    }


def _fit_final_model(frame: pd.DataFrame, sector: str, model_version: str) -> tuple[ModelEnsemble, list[dict]]:
    candidate_cols = [
        col
        for col in frame.columns
        if col
        not in {
            "ticker",
            "earnings_date",
            "sector",
            "actual_t1_close_return",
            "actual_t5_return",
            "actual_t20_return",
            "convergence_low",
            "convergence_high",
            "direction_label",
            "magnitude_target",
        }
        and pd.api.types.is_numeric_dtype(frame[col])
    ]
    # Drop features that are >=70% missing (mostly empty FMP fields adding noise)
    feature_cols = [c for c in candidate_cols if frame[c].notna().mean() >= 0.30]
    final_model = ModelEnsemble(sector=sector, model_version=model_version)
    final_model.fit(
        frame[feature_cols],
        frame["direction_label"],
        frame["magnitude_target"],
        frame["convergence_low"],
        frame["convergence_high"],
        frame[["ticker", "earnings_date", "sector", "actual_t1_close_return", "actual_t5_return", "actual_t20_return"]],
    )
    feature_importance = final_model.feature_importance(frame[feature_cols], top_n=20)
    return final_model, feature_importance


def train_from_database(database_url: str, model_dir: str | Path) -> dict[str, Any]:
    frame = _prepare_training_frame(database_url)
    model_version = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    registry = ModelRegistry(model_dir)
    performance_rows: list[dict[str, Any]] = []

    if frame.empty:
        return {"model_version": model_version, "performance": []}

    candidate_sectors = ["general"]
    candidate_sectors.extend(
        sorted(sector for sector, count in frame["sector"].fillna("Unknown").value_counts().items() if count >= MIN_ROWS_PER_SECTOR)
    )

    for sector in candidate_sectors:
        sector_frame = frame if sector == "general" else frame[frame["sector"] == sector]
        if len(sector_frame) < 20:
            continue
        metrics = _evaluate_sector(sector_frame, sector)
        final_model, feature_importance = _fit_final_model(sector_frame, sector, model_version)
        registry.save_for_sector(sector, final_model)
        performance_rows.append(
            {
                "model_version": model_version,
                "sector": sector,
                **metrics,
                "feature_importance": feature_importance,
            }
        )
    return {"model_version": model_version, "performance": performance_rows}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train sector-specific earnings models from the PostgreSQL database.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--model-dir", required=True)
    args = parser.parse_args()
    report = train_from_database(args.database_url, args.model_dir)
    print(report)
