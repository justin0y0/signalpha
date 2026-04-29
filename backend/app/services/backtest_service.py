from __future__ import annotations
from math import sqrt
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from backend.app.db.models import Outcome, Prediction
from backend.app.schemas.backtest import BacktestRequest, BacktestResponse, DirectionStat, EquityPoint


class BacktestService:
    @staticmethod
    def _signal(row: pd.Series, threshold: float) -> int:
        if row["direction_prob_up"] >= threshold:   return 1
        if row["direction_prob_down"] >= threshold: return -1
        return 0

    @staticmethod
    def _actual_label(value: float, stock_std: float | None = None) -> int:
        if stock_std is None or stock_std != stock_std:
            t = 0.02
        else:
            t = max(0.025, min(0.10, abs(stock_std) * 1.0))
        if value > t:  return 1
        if value < -t: return -1
        return 0

    def run(self, db: Session, request: BacktestRequest) -> BacktestResponse:
        stmt = (
            select(Prediction, Outcome)
            .join(Outcome, and_(
                Prediction.ticker == Outcome.ticker,
                Prediction.earnings_date == Outcome.earnings_date,
            ))
            .where(
                Prediction.earnings_date >= request.start_date,
                Prediction.earnings_date <= request.end_date,
            )
            .order_by(Prediction.earnings_date.asc())
        )
        if request.ticker:  stmt = stmt.where(Prediction.ticker == request.ticker.upper())
        if request.sector:  stmt = stmt.where(Prediction.sector == request.sector)

        rows = db.execute(stmt).all()
        _empty = BacktestResponse(
            total_samples=0, total_trades=0, accuracy=0, precision_weighted=0,
            recall_weighted=0, f1_weighted=0, sharpe_ratio=0, sortino_ratio=0,
            max_drawdown=0, total_return=0, win_rate=0, avg_win_pct=0,
            avg_loss_pct=0, profit_factor=0,
            confusion_matrix=[[0,0,0],[0,0,0],[0,0,0]], equity_curve=[],
        )
        if not rows: return _empty

        frame = pd.DataFrame([{
            "date":      p.earnings_date,
            "ticker":    p.ticker,
            "prob_up":   p.direction_prob_up   or 0.0,
            "prob_down": p.direction_prob_down  or 0.0,
            "t1_return": o.actual_t1_close_return or 0.0,
        } for p, o in rows])

        frame["signal"]       = frame.apply(lambda r: self._signal(
            {"direction_prob_up": r.prob_up, "direction_prob_down": r.prob_down},
            request.probability_threshold), axis=1)
        frame["actual_label"] = frame["t1_return"].apply(self._actual_label)
        frame["trade_return"] = frame["signal"] * frame["t1_return"]
        frame["equity"]       = (1.0 + frame["trade_return"]).cumprod()

        running_max     = frame["equity"].cummax()
        frame["drawdown"] = (frame["equity"] - running_max) / running_max

        accuracy = accuracy_score(frame["actual_label"], frame["signal"])
        prec, rec, f1, _ = precision_recall_fscore_support(
            frame["actual_label"], frame["signal"],
            average="weighted", zero_division=0)
        conf = confusion_matrix(frame["actual_label"], frame["signal"],
                                labels=[-1, 0, 1]).tolist()

        trades = frame[frame["signal"] != 0]
        total_trades  = int(len(trades))
        wins   = trades[trades["trade_return"] > 0]["trade_return"]
        losses = trades[trades["trade_return"] <= 0]["trade_return"]
        win_rate      = float(len(wins) / total_trades) if total_trades else 0
        avg_win       = float(wins.mean()   * 100) if len(wins)   else 0
        avg_loss      = float(losses.mean() * 100) if len(losses) else 0
        profit_factor = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else 99.0

        tr       = frame["trade_return"]
        std_all  = float(tr.std(ddof=0))
        std_down = float(tr[tr < 0].std(ddof=0)) if (tr < 0).any() else 1e-9
        freq     = 4
        sharpe   = float(tr.mean() / std_all  * sqrt(freq)) if std_all  > 1e-9 else 0
        sortino  = float(tr.mean() / std_down * sqrt(freq)) if std_down > 1e-9 else 0

        dir_stats = []
        for sig, label in [(1, "UP"), (-1, "DOWN")]:
            sub = frame[frame["signal"] == sig]
            if sub.empty: continue
            hits = int((sub["actual_label"] == sig).sum())
            dir_stats.append(DirectionStat(
                direction=label, signals=len(sub), hits=hits,
                hit_rate=round(hits / len(sub), 4),
                avg_return_pct=round(float(sub["trade_return"].mean() * 100), 3),
            ))

        equity_curve = [
            EquityPoint(date=row.date, equity=float(row.equity), drawdown=float(row.drawdown))
            for row in frame.itertuples()
        ]

        return BacktestResponse(
            total_samples=int(len(frame)), total_trades=total_trades,
            accuracy=float(accuracy), precision_weighted=float(prec),
            recall_weighted=float(rec), f1_weighted=float(f1),
            sharpe_ratio=round(sharpe, 3), sortino_ratio=round(sortino, 3),
            max_drawdown=round(float(frame["drawdown"].min()), 4),
            total_return=round(float(frame["equity"].iloc[-1] - 1), 4),
            win_rate=round(win_rate, 4), avg_win_pct=round(avg_win, 3),
            avg_loss_pct=round(avg_loss, 3), profit_factor=round(min(profit_factor, 99), 3),
            confusion_matrix=conf, equity_curve=equity_curve, direction_stats=dir_stats,
        )
