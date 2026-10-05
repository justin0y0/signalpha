"""Every capability figure the site states, computed from the data rather than typed.

The site's copy hardcoded its own accuracy claims — "76.3% vs a 60.7% base rate",
"59.9% three-class", "49.3% (5,393 events, 47 folds)" — and each one went stale the
next time labels, calibration or features changed, so different pages contradicted
each other and the numbers on screen described models that no longer existed. Copy now
takes its numbers from here; when the model changes, the page changes with it.

  three_class — out-of-sample accuracy against each stock's own band, and the
                always-FLAT baseline it must beat
  direction   — precision of each predicted class against that class's base rate
  breakout    — the pooled move model's walk-forward metrics (artifacts/move_metrics.json)
  universe    — tickers, events and features actually in use
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.models import EarningsEvent, Outcome, Prediction
from backend.app.services.flat_band import classify_actual
from backend.app.services.prediction_filters import OUT_OF_SAMPLE_ONLY

_TTL = 600
_cache: dict[str, Any] = {"at": 0.0, "value": None}
_lock = threading.Lock()


def _breakout_metrics() -> dict | None:
    path = Path(get_settings().model_dir) / "move_metrics.json"
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return None


def move_tier(prob_move: float | None, metrics: dict | None) -> str | None:
    """Place a live P(move) in the same decile scheme the evaluation measured."""
    if prob_move is None or not metrics:
        return None
    if prob_move >= metrics.get("threshold_top_decile", 2):
        return "breakout"
    if prob_move >= metrics.get("threshold_top_quintile", 2):
        return "elevated"
    return "normal"


def _compute(db: Session) -> dict:
    rows = db.execute(
        select(Prediction.direction_prob_up, Prediction.direction_prob_flat, Prediction.direction_prob_down,
               Outcome.actual_t1_close_return, Outcome.flat_band)
        .join(Outcome, and_(Outcome.ticker == Prediction.ticker, Outcome.earnings_date == Prediction.earnings_date))
        .where(Outcome.actual_t1_close_return.is_not(None))
        .where(OUT_OF_SAMPLE_ONLY)
    ).all()
    pairs = []
    for up, flat, down, ret, band in rows:
        actual = classify_actual(ret, band) if ret is not None and abs(ret) > 1e-9 else None
        if actual is None or up is None:
            continue
        probs = {"UP": up, "FLAT": flat or 0, "DOWN": down or 0}
        pairs.append((max(probs, key=probs.get), actual))

    n = len(pairs)
    actual_counts = Counter(a for _, a in pairs)
    direction = {}
    for cls in ("UP", "FLAT", "DOWN"):
        picked = [a for p, a in pairs if p == cls]
        direction[cls] = {
            "n": len(picked),
            "precision": round(sum(a == cls for a in picked) / len(picked), 4) if picked else None,
            "base_rate": round(actual_counts[cls] / n, 4) if n else None,
        }

    universe = {
        "tickers": db.execute(select(func.count(func.distinct(EarningsEvent.ticker)))).scalar() or 0,
        "events": db.execute(select(func.count()).select_from(EarningsEvent)).scalar() or 0,
        "scored_events": n,
    }
    breakout = _breakout_metrics()
    if breakout:
        universe["features"] = breakout.get("features")

    return {
        "three_class": {
            "n": n,
            "accuracy": round(sum(p == a for p, a in pairs) / n, 4) if n else None,
            "flat_baseline": round(actual_counts["FLAT"] / n, 4) if n else None,
            "distribution": {k: round(v / n, 4) for k, v in actual_counts.items()} if n else {},
        },
        "direction": direction,
        "breakout": breakout,
        "universe": universe,
    }


def headline(db: Session) -> dict:
    with _lock:
        if _cache["value"] is not None and time.time() - _cache["at"] < _TTL:
            return _cache["value"]
    value = _compute(db)
    with _lock:
        _cache.update(at=time.time(), value=value)
    return value
