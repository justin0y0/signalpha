"""Track Record API — predictions vs realised outcomes.

Designed for the Citadel/Two Sigma audience: confusion matrix, calibration curve,
rolling accuracy, and a paginated, filterable list of every prediction the model
has ever made — joined with the actual T+1 outcome.
"""
from __future__ import annotations
from typing import Literal
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.db.models import Prediction, Outcome, EarningsEvent
from backend.app.services.prediction_filters import OUT_OF_SAMPLE_ONLY
from backend.app.services.flat_band import classify_actual, load_flat_bands

router = APIRouter(prefix="/track-record", tags=["track-record"])

# ── helpers ──────────────────────────────────────────────────────────────────
def _classify_prediction(p: Prediction) -> str:
    """Pick the highest-probability class as the model's call."""
    probs = {
        "UP": p.direction_prob_up or 0,
        "FLAT": p.direction_prob_flat or 0,
        "DOWN": p.direction_prob_down or 0,
    }
    return max(probs, key=probs.get)

def _classify_actual(t1: float | None, ticker: str, bands: dict[str, float]) -> str | None:
    """Classify a realised T+1 close return against *this stock's* FLAT band.

    Previously a flat +/-2% for every ticker, with a docstring that claimed 1.5% —
    neither of which was the rule the model was trained on. See services/flat_band.py
    for why that made every accuracy number on this page wrong.
    """
    if t1 is None or abs(t1) < 1e-9:
        return None
    return classify_actual(t1, bands.get(ticker))


# ── 1. Summary KPIs ──────────────────────────────────────────────────────────
@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(
            Prediction.ticker, Prediction.earnings_date, Prediction.sector,
            Prediction.direction_prob_up, Prediction.direction_prob_flat,
            Prediction.direction_prob_down, Prediction.confidence_score,
            Prediction.expected_move_pct,
            Outcome.actual_t1_close_return, Outcome.actual_t5_return,
        )
        .join(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(Outcome.actual_t1_close_return.is_not(None))
        .where(OUT_OF_SAMPLE_ONLY)
    ).all()
    bands = load_flat_bands(db)

    if not rows:
        return {"total": 0, "hit_rate": 0, "avg_actual_move_pct": 0,
                "best_sector": None, "by_confidence": {}}

    # Denominator must be rows we actually scored, not rows we fetched. Rows whose
    # outcome is unusable are `continue`d below, but `total` used to be len(rows),
    # so every unscored row silently counted as a miss and depressed the hit rate.
    scored = 0
    hits = 0
    moves = []
    actual_counts = {"UP": 0, "FLAT": 0, "DOWN": 0}
    by_conf = {"HIGH": [0, 0], "MEDIUM": [0, 0], "LOW": [0, 0]}
    by_sector: dict[str, list[int]] = {}
    for r in rows:
        pred = _classify_prediction(type("X", (), dict(
            direction_prob_up=r.direction_prob_up,
            direction_prob_flat=r.direction_prob_flat,
            direction_prob_down=r.direction_prob_down,
        ))())
        actual = _classify_actual(r.actual_t1_close_return, r.ticker, bands)
        if actual is None:
            continue
        scored += 1
        actual_counts[actual] += 1
        hit = pred == actual
        if hit: hits += 1
        moves.append(abs(r.actual_t1_close_return) * 100)
        conf = r.confidence_score or 0
        bucket = "HIGH" if conf >= 0.75 else "MEDIUM" if conf >= 0.6 else "LOW"
        by_conf[bucket][0] += 1
        if hit: by_conf[bucket][1] += 1
        sec = r.sector or "Unknown"
        by_sector.setdefault(sec, [0, 0])
        by_sector[sec][0] += 1
        if hit: by_sector[sec][1] += 1

    best_sector = None
    best_rate = 0
    for sec, (n, h) in by_sector.items():
        if n >= 50 and h / n > best_rate:
            best_rate = h / n
            best_sector = {"name": sec, "hit_rate": round(h/n, 4), "n": n}

    if not scored:
        return {"total": 0, "hit_rate": 0, "avg_actual_move_pct": 0,
                "best_sector": None, "by_confidence": {}}

    # The number that actually matters. A 3-class accuracy means nothing without the
    # majority-class rule it has to beat — "always predict FLAT" is free, and if the
    # model can't clear it, the model is not adding anything. Computed here rather
    # than hardcoded in the frontend, which had it as a stale 33.3%/50%.
    baseline_class = max(actual_counts, key=actual_counts.get)
    baseline = actual_counts[baseline_class] / scored

    return {
        "total": scored,
        "hit_rate": round(hits / scored, 4),
        "baseline": round(baseline, 4),
        "baseline_class": baseline_class,
        "actual_distribution": {k: round(v / scored, 4) for k, v in actual_counts.items()},
        "avg_actual_move_pct": round(sum(moves) / len(moves), 2) if moves else 0,
        "best_sector": best_sector,
        "by_confidence": {
            k: {"n": v[0], "hits": v[1],
                "hit_rate": round(v[1]/v[0], 4) if v[0] else 0}
            for k, v in by_conf.items()
        },
        "by_sector": [
            {"name": s, "n": n, "hits": h,
             "hit_rate": round(h/n, 4) if n else 0}
            for s, (n, h) in sorted(by_sector.items(), key=lambda x: -x[1][0])
        ],
    }


# ── 2. Confusion Matrix (3×3) ────────────────────────────────────────────────
@router.get("/confusion")
def confusion(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(
            Prediction.ticker, Prediction.direction_prob_up, Prediction.direction_prob_flat,
            Prediction.direction_prob_down, Outcome.actual_t1_close_return,
        )
        .join(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(Outcome.actual_t1_close_return.is_not(None))
        .where(OUT_OF_SAMPLE_ONLY)
    ).all()
    bands = load_flat_bands(db)

    classes = ["UP", "FLAT", "DOWN"]
    matrix = {p: {a: 0 for a in classes} for p in classes}
    scored = 0
    for r in rows:
        probs = {"UP": r.direction_prob_up or 0,
                 "FLAT": r.direction_prob_flat or 0,
                 "DOWN": r.direction_prob_down or 0}
        pred = max(probs, key=probs.get)
        actual = _classify_actual(r.actual_t1_close_return, r.ticker, bands)
        if actual:
            matrix[pred][actual] += 1
            scored += 1

    # `total` drives every percentage in the matrix cells, so it has to be the number
    # of events that landed in a cell — not the number of rows fetched.
    return {"classes": classes, "matrix": matrix, "total": scored}


# ── 3. Calibration Curve (reliability diagram) ───────────────────────────────
@router.get("/calibration")
def calibration(db: Session = Depends(get_db)) -> dict:
    """Quant gold standard: when the model says 70% confidence, do 70% hit?
    Bin predictions by confidence into deciles, return predicted vs actual."""
    rows = db.execute(
        select(
            Prediction.ticker, Prediction.direction_prob_up, Prediction.direction_prob_flat,
            Prediction.direction_prob_down, Prediction.confidence_score,
            Outcome.actual_t1_close_return,
        )
        .join(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(Outcome.actual_t1_close_return.is_not(None))
        .where(OUT_OF_SAMPLE_ONLY)
        .where(Prediction.confidence_score.is_not(None))
    ).all()
    bands = load_flat_bands(db)

    bins = [(i/10, (i+1)/10) for i in range(3, 10)]
    out = []
    for lo, hi in bins:
        in_bin = []
        for r in rows:
            if r.confidence_score is None: continue
            if not (lo <= r.confidence_score < hi): continue
            probs = {"UP": r.direction_prob_up or 0,
                     "FLAT": r.direction_prob_flat or 0,
                     "DOWN": r.direction_prob_down or 0}
            pred = max(probs, key=probs.get)
            actual = _classify_actual(r.actual_t1_close_return, r.ticker, bands)
            if actual: in_bin.append(pred == actual)
        if not in_bin: continue
        out.append({
            "confidence_bin": round((lo + hi) / 2, 2),
            "n": len(in_bin),
            "predicted_rate": round((lo + hi) / 2, 4),
            "actual_rate": round(sum(in_bin) / len(in_bin), 4),
        })
    return {"points": out}


# ── 4. Rolling 90-day accuracy ───────────────────────────────────────────────
@router.get("/rolling")
def rolling(window: int = Query(90, ge=14, le=365), db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(
            Prediction.ticker, Prediction.earnings_date,
            Prediction.direction_prob_up, Prediction.direction_prob_flat,
            Prediction.direction_prob_down, Outcome.actual_t1_close_return,
        )
        .join(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(Outcome.actual_t1_close_return.is_not(None))
        .where(OUT_OF_SAMPLE_ONLY)
        .order_by(Prediction.earnings_date)
    ).all()
    bands = load_flat_bands(db)

    if not rows: return {"points": []}

    items = []
    for r in rows:
        probs = {"UP": r.direction_prob_up or 0,
                 "FLAT": r.direction_prob_flat or 0,
                 "DOWN": r.direction_prob_down or 0}
        pred = max(probs, key=probs.get)
        actual = _classify_actual(r.actual_t1_close_return, r.ticker, bands)
        if actual: items.append((r.earnings_date, pred == actual))

    if not items: return {"points": []}

    start = items[0][0]
    end = items[-1][0]
    out = []
    cur = start + timedelta(days=window)
    while cur <= end:
        win_start = cur - timedelta(days=window)
        win = [hit for d, hit in items if win_start <= d <= cur]
        if len(win) >= 30:
            out.append({"date": cur.isoformat(),
                        "accuracy": round(sum(win) / len(win), 4),
                        "n": len(win)})
        cur += timedelta(days=7)
    return {"points": out}


# ── 5. Recent predictions list (paginated, filterable) ───────────────────────
@router.get("/recent")
def recent(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    verdict: Literal["all", "hit", "miss"] = "all",
    sector: str | None = None,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> dict:
    q = (
        select(
            Prediction.ticker, Prediction.earnings_date, Prediction.sector,
            Prediction.direction_prob_up, Prediction.direction_prob_flat,
            Prediction.direction_prob_down, Prediction.confidence_score,
            Prediction.expected_move_pct,
            Outcome.actual_t1_close_return, Outcome.actual_t5_return,
            Outcome.actual_t1_gap_pct,
        )
        .join(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(Outcome.actual_t1_close_return.is_not(None))
        .where(OUT_OF_SAMPLE_ONLY)
        .order_by(Prediction.earnings_date.desc())
    )
    if sector: q = q.where(Prediction.sector == sector)
    if min_confidence > 0: q = q.where(Prediction.confidence_score >= min_confidence)

    rows = db.execute(q).all()
    bands = load_flat_bands(db)
    items = []
    for r in rows:
        probs = {"UP": r.direction_prob_up or 0,
                 "FLAT": r.direction_prob_flat or 0,
                 "DOWN": r.direction_prob_down or 0}
        pred = max(probs, key=probs.get)
        actual = _classify_actual(r.actual_t1_close_return, r.ticker, bands)
        hit = pred == actual if actual else None
        if verdict == "hit" and hit is not True: continue
        if verdict == "miss" and hit is not False: continue
        items.append({
            "ticker": r.ticker,
            "earnings_date": r.earnings_date.isoformat(),
            "sector": r.sector,
            "predicted": pred,
            "predicted_prob": round(probs[pred], 4),
            "confidence": round(r.confidence_score or 0, 4),
            "expected_move_pct": round(r.expected_move_pct or 0, 4),
            "actual_class": actual,
            "actual_t1_return": round(r.actual_t1_close_return, 4),
            "actual_t5_return": round(r.actual_t5_return, 4) if r.actual_t5_return is not None else None,
            "actual_gap": round(r.actual_t1_gap_pct, 4) if r.actual_t1_gap_pct is not None else None,
            "hit": hit,
        })
    return {"total_filtered": len(items),
            "items": items[offset:offset + limit]}


# ── 6. Confidence breakdown table ────────────────────────────────────────────
@router.get("/confidence-breakdown")
def confidence_breakdown(db: Session = Depends(get_db)) -> dict:
    """Show accuracy at each confidence threshold — key for investor credibility."""
    rows = db.execute(
        select(
            Prediction.ticker, Prediction.direction_prob_up, Prediction.direction_prob_flat,
            Prediction.direction_prob_down, Prediction.confidence_score,
            Outcome.actual_t1_close_return,
        )
        .join(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(Outcome.actual_t1_close_return.is_not(None))
        .where(OUT_OF_SAMPLE_ONLY)
        .where(Prediction.confidence_score.is_not(None))
    ).all()
    bands = load_flat_bands(db)

    thresholds = [0.0, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]
    result = []
    for t in thresholds:
        subset = []
        for r in rows:
            if (r.confidence_score or 0) < t:
                continue
            probs = {"UP": r.direction_prob_up or 0,
                     "FLAT": r.direction_prob_flat or 0,
                     "DOWN": r.direction_prob_down or 0}
            pred = max(probs, key=probs.get)
            actual = _classify_actual(r.actual_t1_close_return, r.ticker, bands)
            if actual:
                subset.append(pred == actual)
        if not subset:
            continue
        result.append({
            "min_confidence": t,
            "label": "All" if t == 0 else f"≥{int(t*100)}%",
            "n": len(subset),
            "hit_rate": round(sum(subset) / len(subset), 4),
        })
    return {"rows": result}
