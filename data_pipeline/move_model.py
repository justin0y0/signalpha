"""Breakout model: will this report move the stock more than it usually moves?

What it predicts
----------------
`move = |T+1 close return| > own band`, where the band is the median absolute reaction
the ticker produced on its earlier reports (outcomes.flat_band). Half of all reports
clear their own band by construction, so the base rate sits near 50% and a skill claim
is easy to check.

Why one pooled model, not the per-sector ensembles' move head
-------------------------------------------------------------
The first production version hung a binary head off each sector ensemble. Each sector
has a few hundred events, and the ensembles upsample rows to balance *direction*
classes, which is the wrong balancing for this target. Measured walk-forward it scored
AUC 0.516 — and was anti-predictive at the "loud" end. The same features pooled into
one gradient-boosted model score 0.54, and adding the band-relative inputs 0.57.

What the evidence supports (point-in-time features only, see models/features.py)
-------------------------------------------------------------------------------
The skill is one-sided. The top decile of predicted movers moves more than usual about
70% of the time against a ~54% base rate, and that holds on tickers with 16+ prior
reports (69% vs 55%). The bottom decile — "will be quiet" — is barely better than the
base rate. So this is a breakout detector, not a non-event detector, and every surface
that reads `artifacts/move_metrics.json` says so with the live numbers.

    python -m data_pipeline.move_model            # walk-forward, write prob_move, fit final model
    python -m data_pipeline.move_model --dry-run  # metrics only
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sqlalchemy import select, text
from xgboost import XGBClassifier

from backend.app.core.config import get_settings
from backend.app.db.models import Prediction
from backend.app.db.session import SessionLocal
from models.features import feature_columns
from models.train import _prepare_training_frame

log = logging.getLogger(__name__)
settings = get_settings()

FIRST_TEST_FRACTION = 0.40   # the earliest 40% of history only ever trains
N_FOLDS = 10
PARAMS = dict(n_estimators=250, max_depth=3, learning_rate=0.05, subsample=0.8,
              colsample_bytree=0.8, min_child_weight=5, eval_metric="logloss", n_jobs=2,
              random_state=42)


def artifacts_dir() -> Path:
    return Path(settings.model_dir)


def _model() -> XGBClassifier:
    return XGBClassifier(**PARAMS)


def walk_forward(frame: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """Out-of-sample P(move) for every row after the first training window, NaN before."""
    X = frame[cols].replace([np.inf, -np.inf], np.nan).to_numpy(dtype=float)
    y = frame["move_target"].to_numpy()
    n = len(frame)
    start = int(n * FIRST_TEST_FRACTION)
    step = max(1, (n - start) // N_FOLDS)
    out = np.full(n, np.nan)
    i = start
    while i < n:
        m = _model()
        m.fit(X[:i], y[:i])
        out[i:i + step] = m.predict_proba(X[i:i + step])[:, 1]
        log.info("move fold ending %s: trained on %s rows", frame["earnings_date"].iloc[min(i + step, n) - 1].date(), i)
        i += step
    return out


def evaluate(y: np.ndarray, p: np.ndarray) -> dict:
    k = ~np.isnan(p)
    y, p = y[k], p[k]
    base = float(y.mean())
    edges = np.quantile(p, np.linspace(0, 1, 11))
    deciles = []
    for d in range(10):
        lo, hi = edges[d], edges[d + 1]
        m = (p >= lo) & (p <= hi) if d == 9 else (p >= lo) & (p < hi)
        if m.sum():
            deciles.append({"decile": d + 1, "n": int(m.sum()), "mean_p": round(float(p[m].mean()), 4),
                            "move_rate": round(float(y[m].mean()), 4)})
    top = p >= np.quantile(p, 0.9)
    bottom = p <= np.quantile(p, 0.1)
    se = np.sqrt(base * (1 - base) / max(1, top.sum()))
    return {
        "n": int(len(y)),
        "auc": round(float(roc_auc_score(y, p)), 4),
        "base_rate": round(base, 4),
        "top_decile": {"n": int(top.sum()), "move_rate": round(float(y[top].mean()), 4),
                       "z": round(float((y[top].mean() - base) / se), 2)},
        "bottom_decile": {"n": int(bottom.sum()), "quiet_rate": round(float(1 - y[bottom].mean()), 4),
                          "quiet_base": round(1 - base, 4)},
        # Cut-offs on the out-of-sample distribution, so a live prediction can be placed in
        # the same decile the evaluation used.
        "threshold_top_decile": round(float(np.quantile(p, 0.9)), 4),
        "threshold_top_quintile": round(float(np.quantile(p, 0.8)), 4),
        "deciles": deciles,
    }


def run(dry_run: bool = False) -> dict:
    frame = _prepare_training_frame(settings.database_url)
    frame = frame[frame["flat_band"].notna()].sort_values("earnings_date").reset_index(drop=True)
    cols = feature_columns(frame)
    log.info("%s rows, %s point-in-time features", len(frame), len(cols))

    oos = walk_forward(frame, cols)
    metrics = evaluate(frame["move_target"].to_numpy(), oos)
    # The universe grew from 180 large caps to every US listing over $300M (2026-10-14).
    # One pooled model serves all of them, so the skill is reported per market-cap tier,
    # with the top decile cut at the pooled threshold -- the one live scores are read by.
    with SessionLocal() as s:
        tiers = dict(s.execute(text("SELECT ticker, tier FROM universe")).all()) if _has_universe(s) else {}
    tier = frame["ticker"].map(lambda t: "large" if tiers.get(t, "core") in ("core", "large") else tiers.get(t)).to_numpy()
    y_all = frame["move_target"].to_numpy()
    cut = metrics["threshold_top_decile"]
    by_tier = {}
    for name in ("large", "mid", "small"):
        m = (tier == name) & ~np.isnan(oos)
        if m.sum() < 200:
            continue
        y, p = y_all[m], oos[m]
        top = p >= cut
        base = float(y.mean())
        se = np.sqrt(base * (1 - base) / max(1, top.sum()))
        by_tier[name] = {"n": int(m.sum()), "auc": round(float(roc_auc_score(y, p)), 4), "base_rate": round(base, 4),
                         "top_n": int(top.sum()),
                         "top_move_rate": round(float(y[top].mean()), 4) if top.any() else None,
                         "top_z": round(float((y[top].mean() - base) / se), 2) if top.any() else None}
    metrics["by_tier"] = by_tier
    metrics.update(features=len(cols), fitted_at=datetime.now(timezone.utc).isoformat(),
                   first_oos_date=str(frame["earnings_date"].iloc[int(len(frame) * FIRST_TEST_FRACTION)].date()))
    print(json.dumps({k: v for k, v in metrics.items() if k != "deciles"}, indent=1))
    if dry_run:
        return metrics

    # Persist the out-of-sample probabilities; rows inside the first training window get
    # NULL rather than an in-sample number that would flatter any evaluation.
    written = 0
    with SessionLocal() as s:
        preds = {(p.ticker, p.earnings_date): p for p in s.execute(select(Prediction)).scalars()}
        today = datetime.now(timezone.utc).date()
        for (tk, d, sec), prob in zip(zip(frame["ticker"], frame["earnings_date"].dt.date, frame["sector"]), oos):
            if d >= today:
                continue
            row = preds.get((tk, d))
            if row is None:
                # A report added with the universe has no three-class prediction; the
                # breakout score still belongs in the record.
                if np.isnan(prob):
                    continue
                row = Prediction(ticker=tk, earnings_date=d, sector=sec if isinstance(sec, str) else None, model_version="move-pooled",
                                 is_out_of_sample=True)
                s.add(row)
            row.prob_move = None if np.isnan(prob) else float(prob)
            written += 1
        s.commit()
    metrics["written"] = written

    final = _model()
    final.fit(frame[cols].replace([np.inf, -np.inf], np.nan).to_numpy(dtype=float), frame["move_target"].to_numpy())
    d = artifacts_dir()
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": final, "features": cols}, d / "move_model.joblib")
    (d / "move_metrics.json").write_text(json.dumps(metrics))
    log.info("move model saved: AUC %.4f, %s OOS rows written", metrics["auc"], written)
    return metrics


def _has_universe(s) -> bool:
    return bool(s.execute(text("SELECT to_regclass('public.universe') IS NOT NULL")).scalar())


def load_live() -> dict | None:
    """The final model + its feature list, for run_predictions. None if never trained."""
    path = artifacts_dir() / "move_model.joblib"
    return joblib.load(path) if path.exists() else None


def predict_live(bundle: dict, feature_row: pd.DataFrame) -> float | None:
    try:
        X = feature_row.reindex(columns=bundle["features"]).astype(float).replace([np.inf, -np.inf], np.nan)
        return float(bundle["model"].predict_proba(X.to_numpy())[0][1])
    except Exception as exc:  # noqa: BLE001
        log.warning("live move prediction failed: %s", exc)
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    run(ap.parse_args().dry_run)
