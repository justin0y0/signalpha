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

def _classify_actual(t1: float | None, threshold: float = 0.015) -> str | None:
    """Classify realised T+1 close return into UP/FLAT/DOWN buckets.
    Threshold of 1.5% mirrors the labelling used at training time."""
    if t1 is None:
        return None
    if t1 > threshold:
        return "UP"
    if t1 < -threshold:
        return "DOWN"
    return "FLAT"


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
    ).all()

    if not rows:
        return {"total": 0, "hit_rate": 0, "avg_actual_move_pct": 0,
                "best_sector": None, "by_confidence": {}}

    total = len(rows)
    hits = 0
    moves = []
    by_conf = {"HIGH": [0, 0], "MEDIUM": [0, 0], "LOW": [0, 0]}
    by_sector: dict[str, list[int]] = {}
    for r in rows:
        pred = _classify_prediction(type("X", (), dict(
            direction_prob_up=r.direction_prob_up,
            direction_prob_flat=r.direction_prob_flat,
            direction_prob_down=r.direction_prob_down,
        ))())
        actual = _classify_actual(r.actual_t1_close_return)
        if actual is None:
            continue
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

    return {
        "total": total,
        "hit_rate": round(hits / total, 4),
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
            Prediction.direction_prob_up, Prediction.direction_prob_flat,
            Prediction.direction_prob_down, Outcome.actual_t1_close_return,
        )
        .join(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(Outcome.actual_t1_close_return.is_not(None))
    ).all()

    classes = ["UP", "FLAT", "DOWN"]
    matrix = {p: {a: 0 for a in classes} for p in classes}
    for r in rows:
        probs = {"UP": r.direction_prob_up or 0,
                 "FLAT": r.direction_prob_flat or 0,
                 "DOWN": r.direction_prob_down or 0}
        pred = max(probs, key=probs.get)
        actual = _classify_actual(r.actual_t1_close_return)
        if actual: matrix[pred][actual] += 1

    return {"classes": classes, "matrix": matrix, "total": len(rows)}


# ── 3. Calibration Curve (reliability diagram) ───────────────────────────────
@router.get("/calibration")
def calibration(db: Session = Depends(get_db)) -> dict:
    """Quant gold standard: when the model says 70% confidence, do 70% hit?
    Bin predictions by confidence into deciles, return predicted vs actual."""
    rows = db.execute(
        select(
            Prediction.direction_prob_up, Prediction.direction_prob_flat,
            Prediction.direction_prob_down, Prediction.confidence_score,
            Outcome.actual_t1_close_return,
        )
        .join(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(Outcome.actual_t1_close_return.is_not(None))
        .where(Prediction.confidence_score.is_not(None))
    ).all()

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
            actual = _classify_actual(r.actual_t1_close_return)
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
            Prediction.earnings_date,
            Prediction.direction_prob_up, Prediction.direction_prob_flat,
            Prediction.direction_prob_down, Outcome.actual_t1_close_return,
        )
        .join(Outcome, and_(
            Outcome.ticker == Prediction.ticker,
            Outcome.earnings_date == Prediction.earnings_date,
        ))
        .where(Outcome.actual_t1_close_return.is_not(None))
        .order_by(Prediction.earnings_date)
    ).all()

    if not rows: return {"points": []}

    items = []
    for r in rows:
        probs = {"UP": r.direction_prob_up or 0,
                 "FLAT": r.direction_prob_flat or 0,
                 "DOWN": r.direction_prob_down or 0}
        pred = max(probs, key=probs.get)
        actual = _classify_actual(r.actual_t1_close_return)
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
        .order_by(Prediction.earnings_date.desc())
    )
    if sector: q = q.where(Prediction.sector == sector)
    if min_confidence > 0: q = q.where(Prediction.confidence_score >= min_confidence)

    rows = db.execute(q).all()
    items = []
    for r in rows:
        probs = {"UP": r.direction_prob_up or 0,
                 "FLAT": r.direction_prob_flat or 0,
                 "DOWN": r.direction_prob_down or 0}
        pred = max(probs, key=probs.get)
        actual = _classify_actual(r.actual_t1_close_return)
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
