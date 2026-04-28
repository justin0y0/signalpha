from __future__ import annotations

from math import sqrt

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.app.db.models import Outcome, Prediction
from backend.app.schemas.backtest import BacktestRequest, BacktestResponse, EquityPoint


class BacktestService:
    @staticmethod
    def _signal_from_probs(row: pd.Series, threshold: float) -> int:
        if row["direction_prob_up"] >= threshold:
            return 1
        if row["direction_prob_down"] >= threshold:
            return -1
        return 0

    @staticmethod
    def _label_from_return(value: float, stock_std: float | None = None) -> int:
        # Stock-aware adaptive threshold matching training labels
        if stock_std is None or stock_std != stock_std:
            threshold = 0.02
        else:
            threshold = max(0.025, min(0.10, abs(stock_std) * 1.0))
        if value > threshold:
            return 1
        if value < -threshold:
            return -1
        return 0

    def run(self, db: Session, request: BacktestRequest) -> BacktestResponse:
        stmt = (
            select(Prediction, Outcome)
            .join(
                Outcome,
                and_(Prediction.ticker == Outcome.ticker, Prediction.earnings_date == Outcome.earnings_date),
            )
            .where(Prediction.earnings_date >= request.start_date, Prediction.earnings_date <= request.end_date)
            .order_by(Prediction.earnings_date.asc())
        )
        if request.ticker:
            stmt = stmt.where(Prediction.ticker == request.ticker.upper())
        if request.sector:
            stmt = stmt.where(Prediction.sector == request.sector)

        rows = db.execute(stmt).all()
        if not rows:
            return BacktestResponse(
                total_samples=0,
                accuracy=0.0,
                precision_weighted=0.0,
                recall_weighted=0.0,
                f1_weighted=0.0,
                sharpe_ratio=0.0,
                confusion_matrix=[[0, 0, 0], [0, 0, 0], [0, 0, 0]],
                equity_curve=[],
            )

        frame = pd.DataFrame(
            [
                {
                    "date": prediction.earnings_date,
                    "direction_prob_up": prediction.direction_prob_up or 0.0,
                    "direction_prob_down": prediction.direction_prob_down or 0.0,
                    "actual_t1_close_return": outcome.actual_t1_close_return or 0.0,
                }
                for prediction, outcome in rows
            ]
        )
        frame["pred_label"] = frame.apply(lambda row: self._signal_from_probs(row, request.probability_threshold), axis=1)
        frame["actual_label"] = frame["actual_t1_close_return"].apply(self._label_from_return)
        frame["strategy_return"] = frame["pred_label"] * frame["actual_t1_close_return"]
        frame["equity"] = (1.0 + frame["strategy_return"]).cumprod()

        accuracy = accuracy_score(frame["actual_label"], frame["pred_label"])
        precision, recall, f1, _ = precision_recall_fscore_support(
            frame["actual_label"],
            frame["pred_label"],
            average="weighted",
            zero_division=0,
        )
        std = frame["strategy_return"].std(ddof=0)
        sharpe = float(frame["strategy_return"].mean() / std * sqrt(252)) if std and not np.isnan(std) else 0.0
        conf = confusion_matrix(frame["actual_label"], frame["pred_label"], labels=[-1, 0, 1]).tolist()
        equity_curve = [EquityPoint(date=row.date, equity=float(row.equity)) for row in frame.itertuples()]

        return BacktestResponse(
            total_samples=int(len(frame)),
            accuracy=float(accuracy),
            precision_weighted=float(precision),
            recall_weighted=float(recall),
            f1_weighted=float(f1),
            sharpe_ratio=sharpe,
            confusion_matrix=conf,
            equity_curve=equity_curve,
        )
