"""Direction lean — a pre-report up/down call, built in the open and scored honestly.

What it is
----------
A transparent scorecard, not a black box. Each factor votes up or down with a weight:

  backtestable (weights fitted on history, walk-forward accuracy published)
    reversion     daily Avellaneda-Lee s-score, contrarian
    run-up        stock-specific return over the last five sessions, contrarian
    past prints   the stock's average reaction on its last four reports, contrarian
    momentum      20-session return
    beat streak   share of the last four reports that beat EPS estimates

  live-only (no point-in-time history exists, so they CANNOT be backtested; small
  fixed weights with the sign the literature suggests, flagged unproven)
    revisions     analyst EPS up- vs down-revisions
    skew          put IV minus call IV
    put/call      option volume ratio

What it is not
--------------
Evidence of skill. On clean, leak-free data the backtestable part predicts the
direction of an earnings reaction about 51-52% of the time — coin-flip territory — and
every surface that shows a lean shows that number beside it. The live-only factors are
the only part that could change the picture, and the only way to find out is forward:
each lean is sealed in the Earnings Arena before the report and graded after.

    python -m data_pipeline.direction_lean            # fit, write metrics + model, score upcoming
    python -m data_pipeline.direction_lean --dry-run  # metrics only
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sqlalchemy import create_engine, text

from backend.app.core.config import get_settings
from backend.app.db.session import SessionLocal

log = logging.getLogger(__name__)
settings = get_settings()

# key, label, clip
FITTED = [
    ("reversion", "Mean-reversion score", 3.0),
    ("runup", "Run-up into the report", 3.0),
    ("past_prints", "Recent earnings reactions", 3.0),
    ("momentum", "20-session momentum", 3.0),
    ("beat_streak", "EPS beat streak", 1.0),
]
# key, label, weight per unit, scale — signs from Xing-Zhang-Zhao (skew) and the
# revision-drift literature; magnitudes deliberately small.
LIVE_ONLY = [
    ("revisions", "Analyst revisions", 0.12),
    ("skew", "Options skew", -0.10),
    ("put_call", "Put/call volume", -0.06),
]
FIRST_TEST_FRACTION = 0.40
N_FOLDS = 10


def artifacts() -> Path:
    return Path(settings.model_dir)


def _num(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return x if math.isfinite(x) else float("nan")


def raw_factors(payload: dict, past_reactions: list[float], band: float | None,
                beats: list[float]) -> dict[str, float]:
    """Unstandardised factor values from one event's point-in-time inputs."""
    vol = _num(payload.get("vol20"))
    f = {
        "reversion": -_num(payload.get("al_s")),
        "runup": -_num(payload.get("resid5")) / vol if vol and vol > 0 else float("nan"),
        "momentum": _num(payload.get("ret_20d_pre")) / (vol * math.sqrt(20)) if vol and vol > 0 else float("nan"),
        "past_prints": float("nan"), "beat_streak": float("nan"),
    }
    last4 = [r for r in past_reactions[-4:] if math.isfinite(r)]
    if len(last4) >= 2 and band and band > 0:
        f["past_prints"] = -float(np.mean(last4)) / band
    b4 = [b for b in beats[-4:] if math.isfinite(b)]
    if len(b4) >= 2:
        f["beat_streak"] = float(np.mean(b4)) - 0.5
    up, down = _num(payload.get("up_revisions")), _num(payload.get("down_revisions"))
    f["revisions"] = (up - down) / (up + down) if math.isfinite(up) and math.isfinite(down) and up + down > 0 else float("nan")
    skew = _num(payload.get("put_call_skew"))
    f["skew"] = skew / 0.05 if math.isfinite(skew) else float("nan")
    pcr = _num(payload.get("put_call_ratio"))
    f["put_call"] = math.log(pcr) if math.isfinite(pcr) and pcr > 0 else float("nan")
    return f


def _history() -> pd.DataFrame:
    eng = create_engine(settings.database_url)
    df = pd.read_sql(text("""
        SELECT o.ticker, o.earnings_date, o.actual_t1_close_return AS t1, o.flat_band AS band, p.feature_payload
        FROM outcomes o JOIN price_features p ON p.ticker=o.ticker AND p.earnings_date=o.earnings_date
        WHERE o.actual_t1_close_return IS NOT NULL AND o.flat_band IS NOT NULL
        ORDER BY o.ticker, o.earnings_date"""), eng)
    sp = pd.read_sql(text("SELECT ticker, report_date, surprise_pct FROM earnings_surprises WHERE eps_actual IS NOT NULL ORDER BY ticker, report_date"), eng)
    beats_by: dict[str, list[tuple[date, float]]] = {}
    for r in sp.itertuples():
        beats_by.setdefault(r.ticker, []).append((r.report_date, 1.0 if (r.surprise_pct or 0) > 0 else 0.0))
    rows = []
    for tk, g in df.groupby("ticker", sort=False):
        past: list[float] = []
        tb = beats_by.get(tk, [])
        for r in g.itertuples():
            pl = r.feature_payload if isinstance(r.feature_payload, dict) else json.loads(r.feature_payload or "{}")
            beats = [b for d, b in tb if d < r.earnings_date - pd.Timedelta(days=3).to_pytimedelta()]
            f = raw_factors(pl, past, float(r.band), beats)
            rows.append({"ticker": tk, "earnings_date": r.earnings_date, "t1": float(r.t1), **f})
            past.append(float(r.t1))
    out = pd.DataFrame(rows)
    return out[np.isfinite(out.t1) & (out.t1.abs() < 1)].sort_values("earnings_date").reset_index(drop=True)


def _design(df: pd.DataFrame, stats: dict | None = None) -> tuple[np.ndarray, dict]:
    stats = stats or {}
    cols = []
    for key, _label, clip in FITTED:
        x = df[key].astype(float)
        mu, sd = stats.get(key, (float(x.mean()), float(x.std()) or 1.0))
        stats[key] = (mu, sd)
        cols.append(((x - mu) / sd).clip(-clip, clip).fillna(0.0).to_numpy())
    return np.column_stack(cols), stats


def evaluate(df: pd.DataFrame) -> dict:
    y = (df.t1 > 0).astype(int).to_numpy()
    n = len(df)
    start = int(n * FIRST_TEST_FRACTION)
    step = max(1, (n - start) // N_FOLDS)
    p = np.full(n, np.nan)
    i = start
    while i < n:
        X, st = _design(df.iloc[:i])
        m = LogisticRegression(C=0.05, max_iter=500).fit(X, y[:i])
        Xt, _ = _design(df.iloc[i:i + step], dict(st))
        p[i:i + step] = m.predict_proba(Xt)[:, 1]
        i += step
    k = ~np.isnan(p)
    yy, pp, r = y[k], p[k], df.t1.to_numpy()[k]
    hit = float(((pp > 0.5) == (yy == 1)).mean())
    se = math.sqrt(0.25 / k.sum())
    q = np.quantile(pp, [0.2, 0.8])
    hi, lo = pp >= q[1], pp <= q[0]
    ls = np.concatenate([r[hi], -r[lo]])
    ls_t = float(ls.mean() / ls.std() * math.sqrt(len(ls)))
    # The bar is not 50%: always calling the more common side scores max(base, 1-base),
    # and on 86k reports a 51.4% hit rate is "significant" against 50% while losing to
    # "always up" at 51.5%. A lean only counts if it beats that and its long-short
    # spread is real.
    majority = max(float(yy.mean()), 1 - float(yy.mean()))
    z_maj = (hit - majority) / se
    verdict = ("edge" if z_maj >= 3 and ls_t >= 3 else "weak" if z_maj >= 2 and ls_t >= 2 else "coin_flip")
    return {
        "n": int(k.sum()), "accuracy": round(hit, 4), "z": round((hit - 0.5) / se, 2),
        "auc": round(float(roc_auc_score(yy, pp)), 4), "base_up": round(float(yy.mean()), 4),
        "top_quintile_up": round(float(yy[hi].mean()), 4), "bottom_quintile_up": round(float(yy[lo].mean()), 4),
        "long_short_mean": round(float(ls.mean()), 5),
        "long_short_t": round(ls_t, 2), "majority": round(majority, 4), "z_vs_majority": round(z_maj, 2),
        "first_oos_date": str(df.earnings_date.iloc[start]),
        "verdict": verdict,
    }


def fit(dry_run: bool = False) -> dict:
    df = _history()
    metrics = evaluate(df)
    X, stats = _design(df)
    model = LogisticRegression(C=0.05, max_iter=500).fit(X, (df.t1 > 0).astype(int).to_numpy())
    bundle = {
        "intercept": float(model.intercept_[0]),
        "fitted": [{"key": k, "label": lab, "clip": clip, "mean": stats[k][0], "std": stats[k][1], "coef": float(c)}
                   for (k, lab, clip), c in zip(FITTED, model.coef_[0])],
        "live_only": [{"key": k, "label": lab, "coef": w} for k, lab, w in LIVE_ONLY],
        "metrics": {**metrics, "rows": int(len(df)), "fitted_at": datetime.now(timezone.utc).isoformat()},
    }
    print(json.dumps({"metrics": metrics, "coefs": {f["key"]: round(f["coef"], 4) for f in bundle["fitted"]}}, indent=1))
    if not dry_run:
        artifacts().mkdir(parents=True, exist_ok=True)
        (artifacts() / "lean_model.json").write_text(json.dumps(bundle))
    return bundle


def load() -> dict | None:
    path = artifacts() / "lean_model.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def lean(bundle: dict, factors: dict[str, float]) -> dict:
    """P(up) and each factor's signed contribution, in log-odds."""
    z = bundle["intercept"]
    parts = []
    for f in bundle["fitted"]:
        v = factors.get(f["key"], float("nan"))
        if not math.isfinite(v):
            parts.append({"key": f["key"], "label": f["label"], "value": None, "contrib": 0.0, "proven": True})
            continue
        zs = max(-f["clip"], min(f["clip"], (v - f["mean"]) / (f["std"] or 1.0)))
        parts.append({"key": f["key"], "label": f["label"], "value": round(v, 4), "contrib": round(f["coef"] * zs, 4), "proven": True})
        z += f["coef"] * zs
    for f in bundle["live_only"]:
        v = factors.get(f["key"], float("nan"))
        if not math.isfinite(v):
            parts.append({"key": f["key"], "label": f["label"], "value": None, "contrib": 0.0, "proven": False})
            continue
        c = f["coef"] * max(-2.0, min(2.0, v))
        parts.append({"key": f["key"], "label": f["label"], "value": round(v, 4), "contrib": round(c, 4), "proven": False})
        z += c
    p = 1.0 / (1.0 + math.exp(-z))
    return {"p_up": round(p, 4), "lean": "UP" if p >= 0.5 else "DOWN", "factors": parts}


def score_upcoming() -> int:
    """Write a lean for every report still to come."""
    bundle = load()
    if not bundle:
        return 0
    today = date.today()
    n = 0
    with SessionLocal() as s:
        rows = s.execute(text("""
            SELECT pr.id, e.ticker, e.earnings_date, p.feature_payload
            FROM predictions pr
            JOIN earnings_events e ON e.ticker=pr.ticker AND e.earnings_date=pr.earnings_date
            JOIN price_features p ON p.ticker=pr.ticker AND p.earnings_date=pr.earnings_date
            WHERE e.earnings_date >= :d"""), {"d": today}).all()
        for r in rows:
            pl = r.feature_payload if isinstance(r.feature_payload, dict) else json.loads(r.feature_payload or "{}")
            past = [float(x[0]) for x in s.execute(text("""
                SELECT actual_t1_close_return FROM outcomes WHERE ticker=:t AND earnings_date < :d
                  AND actual_t1_close_return IS NOT NULL ORDER BY earnings_date"""), {"t": r.ticker, "d": r.earnings_date}).all()]
            band = s.execute(text("""
                SELECT flat_band FROM outcomes WHERE ticker=:t AND flat_band IS NOT NULL
                ORDER BY earnings_date DESC LIMIT 1"""), {"t": r.ticker}).scalar()
            beats = [1.0 if (x[0] or 0) > 0 else 0.0 for x in s.execute(text("""
                SELECT surprise_pct FROM earnings_surprises WHERE ticker=:t AND report_date < :d
                  AND eps_actual IS NOT NULL ORDER BY report_date"""), {"t": r.ticker, "d": r.earnings_date}).all()]
            out = lean(bundle, raw_factors(pl, past, float(band) if band else None, beats))
            s.execute(text("UPDATE predictions SET lean_up=:p, lean_factors=CAST(:f AS jsonb) WHERE id=:i"),
                      {"p": out["p_up"], "f": json.dumps(out["factors"]), "i": r.id})
            n += 1
        s.commit()
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    fit(a.dry_run)
    if not a.dry_run:
        print("upcoming scored:", score_upcoming())
