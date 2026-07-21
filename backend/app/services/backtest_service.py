"""Backtest service — fixed-fraction sizing + SPY benchmark."""
from __future__ import annotations
from math import sqrt
import logging
from datetime import date
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from backend.app.db.models import Outcome, Prediction
from backend.app.schemas.backtest import (
    BacktestRequest, BacktestResponse, DirectionStat, EquityPoint,
    MonthlyReturn, SectorAttribution, TradeRecord,
)
from backend.app.services.prediction_filters import OUT_OF_SAMPLE_ONLY

log = logging.getLogger(__name__)
INITIAL_EQUITY = 1_000_000.0
POSITION_FRAC = 0.05


class BacktestService:
    @staticmethod
    def _signal(up, down, th):
        if up >= th: return 1
        if down >= th: return -1
        return 0

    @staticmethod
    def _actual_label(ret, t=0.02):
        if ret > t: return 1
        if ret < -t: return -1
        return 0

    def _fetch_spy(self, start, end):
        try:
            import yfinance as yf
            df = yf.Ticker("SPY").history(start=start, end=end, auto_adjust=True)
            if df.empty: return None
            return (df["Close"] / df["Close"].iloc[0]) - 1.0
        except Exception as e:
            log.warning(f"SPY fail: {e}")
            return None

    @staticmethod
    def _beta_vs_benchmark(f: pd.DataFrame, spy_cum: pd.Series) -> float:
        """CAPM beta: OLS slope of strategy daily return on SPY daily return.

        The strategy is event-driven (one row per earnings event) while SPY is a daily
        series, so returns are first aggregated to a daily grid and joined on trading days
        the strategy was actually active. Fewer than 3 overlapping days is not enough to
        estimate a slope, so we report 0.0 rather than a spurious number.
        """
        try:
            strat_daily = f.groupby(pd.to_datetime(f["date"]))["ret_on_eq"].sum()
            spy_daily = (1.0 + spy_cum).pct_change().dropna()
            joined = pd.concat([strat_daily, spy_daily], axis=1, join="inner").dropna()
            joined.columns = ["strat", "bench"]
            if len(joined) < 3:
                return 0.0
            var_b = float(joined["bench"].var(ddof=0))
            if var_b < 1e-12:
                return 0.0
            cov = float(joined["strat"].cov(joined["bench"], ddof=0))
            return round(cov / var_b, 4)
        except Exception as e:  # noqa: BLE001 - beta is a nice-to-have, never fail the backtest
            log.warning(f"beta calc failed: {e}")
            return 0.0

    def _empty(self):
        return BacktestResponse(
            total_samples=0, total_trades=0, accuracy=0, precision_weighted=0,
            recall_weighted=0, f1_weighted=0, sharpe_ratio=0, sortino_ratio=0,
            max_drawdown=0, total_return=0, cagr=0, win_rate=0,
            avg_win_pct=0, avg_loss_pct=0, profit_factor=0,
            confusion_matrix=[[0]*3]*3, equity_curve=[], direction_stats=[],
            benchmark_return=0, benchmark_curve=[], alpha=0, beta=0,
            time_underwater_pct=0, monthly_returns=[],
            sector_attribution=[], trade_list=[],
        )

    def run(self, db, req):
        stmt = (
            select(Prediction, Outcome)
            .join(Outcome, and_(
                Prediction.ticker == Outcome.ticker,
                Prediction.earnings_date == Outcome.earnings_date,
            ))
            .where(
                Prediction.earnings_date >= req.start_date,
                Prediction.earnings_date <= req.end_date,
                # Only genuinely ex-ante rows. Without this the curve is in-sample fit.
                OUT_OF_SAMPLE_ONLY,
            )
            .order_by(Prediction.earnings_date.asc())
        )
        if req.ticker: stmt = stmt.where(Prediction.ticker == req.ticker.upper())
        if req.sector: stmt = stmt.where(Prediction.sector == req.sector)
        rows = db.execute(stmt).all()
        if not rows: return self._empty()
        f = pd.DataFrame([{
            "date": p.earnings_date, "ticker": p.ticker,
            "sector": p.sector or "Unknown",
            "prob_up": float(p.direction_prob_up or 0),
            "prob_down": float(p.direction_prob_down or 0),
            "conf": float(p.confidence_score or 0),
            "t1_return": float(o.actual_t1_close_return or 0),
        } for p, o in rows])
        f["signal"] = f.apply(lambda r: self._signal(r.prob_up, r.prob_down, req.probability_threshold), axis=1)
        f["actual_label"] = f["t1_return"].apply(self._actual_label)
        # FIX: fractional-Kelly (5% per trade, NOT 100% compound)
        f["ret_on_eq"] = f["signal"] * f["t1_return"] * POSITION_FRAC
        f["equity_d"] = INITIAL_EQUITY * (1.0 + f["ret_on_eq"]).cumprod()
        f["return_cum"] = (f["equity_d"] - INITIAL_EQUITY) / INITIAL_EQUITY
        f["pnl_d"] = f["equity_d"].diff().fillna(f["equity_d"].iloc[0] - INITIAL_EQUITY)
        rmax = f["equity_d"].cummax()
        f["drawdown"] = (f["equity_d"] - rmax) / rmax

        trades = f[f["signal"] != 0]
        n_trades = int(len(trades))
        wins = trades[trades["pnl_d"] > 0]["pnl_d"]
        losses = trades[trades["pnl_d"] < 0]["pnl_d"]
        win_rate = float(len(wins) / n_trades) if n_trades else 0
        avg_win_pct = float((trades.loc[trades["pnl_d"] > 0, "t1_return"]).mean() * 100) if len(wins) else 0
        avg_loss_pct = float((trades.loc[trades["pnl_d"] < 0, "t1_return"]).mean() * 100) if len(losses) else 0
        pf = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else 99.0

        roe = trades["ret_on_eq"]
        sd = float(roe.std(ddof=0))
        sd_dn = float(roe[roe < 0].std(ddof=0)) if (roe < 0).any() else 1e-9
        years = max(0.25, (req.end_date - req.start_date).days / 365.25)
        annual = sqrt(n_trades / years) if n_trades > 0 else 0
        sharpe = float(roe.mean() / sd * annual) if sd > 1e-9 else 0
        sortino = float(roe.mean() / sd_dn * annual) if sd_dn > 1e-9 else 0
        time_uw = float((f["drawdown"] < -0.01).sum() / len(f))

        total_ret = float(f["return_cum"].iloc[-1])
        cagr = float((1 + total_ret) ** (1/years) - 1) if years > 0 and total_ret > -1 else 0
        acc = accuracy_score(f["actual_label"], f["signal"])
        prec, rec, f1, _ = precision_recall_fscore_support(
            f["actual_label"], f["signal"], average="weighted", zero_division=0)
        cm = confusion_matrix(f["actual_label"], f["signal"], labels=[-1,0,1]).tolist()

        dir_stats = []
        for sig, lbl in [(1, "UP"), (-1, "DOWN")]:
            sub = f[f["signal"] == sig]
            if sub.empty: continue
            hits = int((sub["actual_label"] == sig).sum())
            dir_stats.append(DirectionStat(
                direction=lbl, signals=len(sub), hits=hits,
                hit_rate=round(hits/len(sub), 4),
                avg_return_pct=round(float(sub["t1_return"].mean()*100), 3),
            ))
        equity_curve = [EquityPoint(date=r.date, equity=float(1.0 + r.return_cum), drawdown=float(r.drawdown)) for r in f.itertuples()]

        spy = self._fetch_spy(req.start_date, req.end_date)
        bench_curve, bench_ret, alpha, beta = [], 0.0, 0.0, 0.0
        if spy is not None and not spy.empty:
            spy_idx = spy.tz_localize(None) if spy.index.tz else spy
            for d in f["date"]:
                d_pd = pd.Timestamp(d)
                prior = spy_idx.loc[:d_pd] if len(spy_idx.loc[:d_pd]) > 0 else None
                val = float(prior.iloc[-1]) if prior is not None and len(prior) > 0 else 0.0
                bench_curve.append(EquityPoint(date=d, equity=1.0 + val, drawdown=0.0))
            bench_ret = float(spy_idx.iloc[-1])
            beta = self._beta_vs_benchmark(f, spy_idx)
            # CAPM alpha with rf = 0. Previously beta was hardcoded to 0.0, which silently
            # reduced this to plain excess-return-vs-SPY while still being labelled "alpha".
            alpha = total_ret - beta * bench_ret

        f["month"] = pd.to_datetime(f["date"]).dt.to_period("M").astype(str)
        m_agg = f.groupby("month").agg(pnl=("pnl_d", "sum"), n=("signal", lambda x: (x != 0).sum()))
        m_agg["return_pct"] = m_agg["pnl"] / INITIAL_EQUITY
        monthly_returns = [MonthlyReturn(month=str(m), return_pct=float(r.return_pct), trades=int(r.n)) for m, r in m_agg.iterrows()]

        sec_attr = []
        for sec, g in trades.groupby("sector"):
            n = len(g); sw = int((g["pnl_d"] > 0).sum())
            sec_attr.append(SectorAttribution(
                sector=str(sec), return_pct=float(g["pnl_d"].sum() / INITIAL_EQUITY),
                trades=n, win_rate=float(sw / n) if n > 0 else 0))
        sec_attr.sort(key=lambda s: abs(s.return_pct), reverse=True)

        trade_list = []
        for r in trades.tail(100).itertuples():
            trade_list.append(TradeRecord(
                date=r.date, ticker=r.ticker, sector=r.sector,
                signal="UP" if r.signal == 1 else "DOWN",
                actual="UP" if r.actual_label == 1 else "DOWN" if r.actual_label == -1 else "FLAT",
                confidence=float(r.conf), actual_return_pct=float(r.t1_return),
                pnl_dollars=float(r.pnl_d), win=bool(r.pnl_d > 0)))

        return BacktestResponse(
            total_samples=int(len(f)), total_trades=n_trades,
            accuracy=float(acc), precision_weighted=float(prec),
            recall_weighted=float(rec), f1_weighted=float(f1),
            sharpe_ratio=round(sharpe, 3), sortino_ratio=round(sortino, 3),
            max_drawdown=round(float(f["drawdown"].min()), 4),
            total_return=round(total_ret, 4), cagr=round(cagr, 4),
            win_rate=round(win_rate, 4), avg_win_pct=round(avg_win_pct, 3),
            avg_loss_pct=round(avg_loss_pct, 3), profit_factor=round(min(pf, 99), 3),
            confusion_matrix=cm, equity_curve=equity_curve, direction_stats=dir_stats,
            benchmark_return=round(bench_ret, 4), benchmark_curve=bench_curve,
            alpha=round(alpha, 4), beta=beta, time_underwater_pct=round(time_uw, 4),
            monthly_returns=monthly_returns, sector_attribution=sec_attr,
            trade_list=trade_list,
        )
