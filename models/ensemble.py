from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import shap
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestRegressor, VotingClassifier, VotingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
from xgboost import XGBClassifier, XGBRegressor


class ApproxQuantileForest:
    def __init__(self, n_estimators: int = 250, random_state: int = 42):
        self.model = RandomForestRegressor(
            n_estimators=n_estimators,
            random_state=random_state,
            min_samples_leaf=3,
            n_jobs=-1,
        )

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "ApproxQuantileForest":
        self.model.fit(X, y)
        return self

    def predict_quantiles(self, X: pd.DataFrame, quantiles: tuple[float, ...]) -> dict[float, np.ndarray]:
        tree_predictions = np.column_stack([tree.predict(X) for tree in self.model.estimators_])
        return {q: np.quantile(tree_predictions, q, axis=1) for q in quantiles}


class ConvergenceZonePredictor:
    def __init__(self):
        self.lower_model = ApproxQuantileForest()
        self.upper_model = ApproxQuantileForest()

    def fit(self, X: pd.DataFrame, y_low: pd.Series, y_high: pd.Series) -> "ConvergenceZonePredictor":
        self.lower_model.fit(X, y_low)
        self.upper_model.fit(X, y_high)
        return self

    def predict(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        low = self.lower_model.predict_quantiles(X, (0.25,))[0.25]
        high = self.upper_model.predict_quantiles(X, (0.75,))[0.75]
        return low, high


class PatternSimilarityEngine:
    def __init__(self):
        self.scaler = StandardScaler()
        self.matrix_: np.ndarray | None = None
        self.metadata_: pd.DataFrame | None = None
        self.feature_names_: list[str] = []

    def fit(self, X: pd.DataFrame, metadata: pd.DataFrame) -> "PatternSimilarityEngine":
        self.feature_names_ = X.columns.tolist()
        self.matrix_ = self.scaler.fit_transform(X.fillna(0.0))
        self.metadata_ = metadata.reset_index(drop=True)
        return self

    def query(self, X: pd.DataFrame, top_k: int = 5) -> list[dict[str, Any]]:
        if self.matrix_ is None or self.metadata_ is None:
            return []
        vector = self.scaler.transform(X[self.feature_names_].fillna(0.0))
        sims = cosine_similarity(vector, self.matrix_)[0]
        top_indices = np.argsort(sims)[::-1][:top_k]
        results: list[dict[str, Any]] = []
        for idx in top_indices:
            row = self.metadata_.iloc[int(idx)].to_dict()
            row["similarity"] = float(sims[int(idx)])
            results.append(row)
        return results


@dataclass
class ModelEnsemble:
    sector: str
    model_version: str = "v1"
    feature_columns: list[str] = field(default_factory=list)
    residual_std_: float = 0.02

    def __post_init__(self) -> None:
        self.label_encoder = LabelEncoder()
        self.label_encoder.fit(["DOWN", "FLAT", "UP"])
        self.direction_model = VotingClassifier(
            estimators=[
                (
                    "xgb",
                    Pipeline(
                        steps=[
                            ("imputer", SimpleImputer(strategy="median")),
                            (
                                "model",
                                XGBClassifier(
                                    objective="multi:softprob",
                                    num_class=3,
                                    eval_metric="mlogloss",
                                    max_depth=4,
                                    n_estimators=250,
                                    learning_rate=0.05,
                                    subsample=0.9,
                                    colsample_bytree=0.8,
                                    random_state=42,
                                ),
                            ),
                        ]
                    ),
                ),
                (
                    "lgbm",
                    Pipeline(
                        steps=[
                            ("imputer", SimpleImputer(strategy="median")),
                            (
                                "model",
                                LGBMClassifier(
                                    objective="multiclass",
                                    num_class=3,
                                    n_estimators=300,
                                    learning_rate=0.05,
                                    random_state=42,
                                    class_weight="balanced",
                                ),
                            ),
                        ]
                    ),
                ),
                (
                    "logreg",
                    Pipeline(
                        steps=[
                            ("imputer", SimpleImputer(strategy="median")),
                            ("scaler", StandardScaler()),
                            ("model", LogisticRegression(max_iter=2000, class_weight="balanced")),
                        ]
                    ),
                ),
            ],
            voting="soft",
        )
        self.magnitude_model = VotingRegressor(
            estimators=[
                (
                    "xgb",
                    Pipeline(
                        steps=[
                            ("imputer", SimpleImputer(strategy="median")),
                            (
                                "model",
                                XGBRegressor(
                                    objective="reg:squarederror",
                                    max_depth=4,
                                    n_estimators=250,
                                    learning_rate=0.05,
                                    subsample=0.9,
                                    colsample_bytree=0.8,
                                    random_state=42,
                                ),
                            ),
                        ]
                    ),
                ),
                (
                    "ridge",
                    Pipeline(
                        steps=[
                            ("imputer", SimpleImputer(strategy="median")),
                            ("scaler", StandardScaler()),
                            ("model", Ridge(alpha=1.0)),
                        ]
                    ),
                ),
            ]
        )
        self.convergence_model = ConvergenceZonePredictor()
        self.similarity_engine = PatternSimilarityEngine()

    def _align_features(self, X: pd.DataFrame) -> pd.DataFrame:
        frame = X.copy()
        if not self.feature_columns:
            self.feature_columns = frame.columns.tolist()
        for feature in self.feature_columns:
            if feature not in frame.columns:
                frame[feature] = np.nan
        return frame[self.feature_columns]

    def fit(
        self,
        X: pd.DataFrame,
        y_direction: pd.Series,
        y_magnitude: pd.Series,
        y_convergence_low: pd.Series,
        y_convergence_high: pd.Series,
        metadata: pd.DataFrame,
    ) -> "ModelEnsemble":
        self.feature_columns = X.columns.tolist()
        X_aligned = self._align_features(X)
        y_encoded = self.label_encoder.transform(y_direction)
        self.direction_model.fit(X_aligned, y_encoded)
        self.magnitude_model.fit(X_aligned, y_magnitude)
        self.convergence_model.fit(X_aligned.fillna(X_aligned.median(numeric_only=True)), y_convergence_low, y_convergence_high)
        self.similarity_engine.fit(X_aligned, metadata)

        residuals = np.abs(self.magnitude_model.predict(X_aligned) - y_magnitude.to_numpy())
        self.residual_std_ = float(np.nanstd(residuals)) if len(residuals) else 0.02
        return self

    def _data_completeness(self, X: pd.DataFrame) -> float:
        total = X.shape[1]
        if total == 0:
            return 0.0
        populated = X.notna().sum(axis=1).iloc[0]
        return float(populated / total)

    def predict(self, X: pd.DataFrame, current_price: float | None = None) -> dict[str, Any]:
        X_aligned = self._align_features(X)
        probs = self.direction_model.named_estimators_["xgb"].predict_proba(X_aligned)[0]
        class_names = self.label_encoder.inverse_transform(np.arange(len(probs)))
        mapping = {label: float(prob) for label, prob in zip(class_names, probs)}
        magnitude = float(self.magnitude_model.predict(X_aligned)[0])
        low_move = max(0.0, magnitude - self.residual_std_)
        high_move = magnitude + self.residual_std_
        conv_low, conv_high = self.convergence_model.predict(X_aligned.fillna(X_aligned.median(numeric_only=True)))
        predicted_direction = max(mapping, key=mapping.get)
        warnings = []
        if self._data_completeness(X_aligned) < 0.8:
            warnings.append(
                {
                    "field": "feature_completeness",
                    "message": "Feature payload is incomplete; review missing inputs before acting on the forecast.",
                    "severity": "warning",
                }
            )
        return {
            "direction_probabilities": {
                "up": mapping.get("UP", 0.0),
                "flat": mapping.get("FLAT", 0.0),
                "down": mapping.get("DOWN", 0.0),
            },
            "predicted_direction": predicted_direction,
            "confidence_score": float(max(probs)),
            "expected_move_pct": magnitude,
            "expected_move_low": low_move,
            "expected_move_high": high_move,
            "convergence_low": float(conv_low[0]),
            "convergence_high": float(conv_high[0]),
            "current_price": current_price,
            "data_completeness": self._data_completeness(X_aligned),
            "warnings": warnings,
        }

    def explain_top_features(self, X: pd.DataFrame, top_n: int = 5) -> list[dict[str, Any]]:
        X_aligned = self._align_features(X)
        pipeline: Pipeline = self.direction_model.named_estimators_["xgb"]
        imputer: SimpleImputer = pipeline.named_steps["imputer"]
        model: XGBClassifier = pipeline.named_steps["model"]
        transformed = imputer.transform(X_aligned)
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(transformed)
        probs = self.direction_model.named_estimators_["xgb"].predict_proba(X_aligned)[0]
        class_idx = int(np.argmax(probs))

        if isinstance(shap_values, list):
            values = shap_values[class_idx][0]
        else:
            array = np.asarray(shap_values)
            if array.ndim == 3:
                values = array[0, :, class_idx]
            else:
                values = array[0]
        ranked = sorted(zip(self.feature_columns, values, X_aligned.iloc[0].tolist()), key=lambda item: abs(float(item[1])), reverse=True)
        output = []
        for feature, contribution, value in ranked[:top_n]:
            output.append(
                {
                    "feature": str(feature),
                    "value": None if pd.isna(value) else float(value),
                    "contribution": float(contribution),
                    "direction": "positive" if contribution >= 0 else "negative",
                }
            )
        return output

    def feature_importance(self, X: pd.DataFrame, top_n: int = 20) -> list[dict[str, Any]]:
        X_aligned = self._align_features(X)
        pipeline: Pipeline = self.direction_model.named_estimators_["xgb"]
        imputer: SimpleImputer = pipeline.named_steps["imputer"]
        model: XGBClassifier = pipeline.named_steps["model"]
        transformed = imputer.transform(X_aligned)
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(transformed)
        if isinstance(shap_values, list):
            arr = np.mean(np.abs(np.stack(shap_values, axis=0)), axis=(0, 1))
        else:
            arr = np.abs(np.asarray(shap_values))
            if arr.ndim == 3:
                arr = arr.mean(axis=(0, 2))
            else:
                arr = arr.mean(axis=0)
        ranked = sorted(zip(self.feature_columns, arr), key=lambda item: float(item[1]), reverse=True)
        return [{"feature": feature, "importance": float(importance)} for feature, importance in ranked[:top_n]]

    def find_similar_cases(self, X: pd.DataFrame, top_k: int = 5) -> list[dict[str, Any]]:
        X_aligned = self._align_features(X)
        return self.similarity_engine.query(X_aligned, top_k=top_k)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: str | Path) -> "ModelEnsemble":
        return joblib.load(path)
