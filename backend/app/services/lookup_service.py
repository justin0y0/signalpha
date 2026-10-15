"""Search every US listing, and score any ticker on demand.

`search` reads the universe table (data_pipeline/universe.py). `lookup` is for a name the
site holds no history for — a micro cap below the training cut-off, or a listing the
nightly build has not reached. It does in a few seconds what the build does in bulk:
pull Yahoo's report dates and daily bars, measure each past reaction on the session
that traded it, take the median as the usual move, build point-in-time features for the
next report and score them with the live breakout model.

The answer says plainly when the ticker sits outside the range the model was trained
on. A score there is an extrapolation, not a measured skill.
"""
from __future__ import annotations

import math
import statistics
import time
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_PRIOR = 4
_cache: dict[str, tuple[float, dict]] = {}
_market: dict[str, Any] = {"at": 0.0, "bars": None, "macro": None}


def search(db: Session, q: str, limit: int = 12) -> list[dict[str, Any]]:
    q = (q or "").strip()
    if not q:
        return []
    sym = q.upper().replace(".", "-")
    rows = db.execute(text("""
        SELECT u.ticker, u.name, u.sector, u.tier, u.market_cap, u.history_at IS NOT NULL OR u.tier='core' AS has_history,
               (SELECT min(e.earnings_date) FROM earnings_events e
                 WHERE e.ticker=u.ticker AND e.earnings_date >= CURRENT_DATE) AS next_report,
               CASE WHEN u.ticker = :sym THEN 0 WHEN u.ticker LIKE :pre THEN 1 ELSE 2 END AS rank
        FROM universe u
        WHERE u.listed AND (u.ticker LIKE :pre OR lower(u.name) LIKE :name) AND u.tier <> 'dup'
        ORDER BY rank, u.market_cap DESC NULLS LAST
        LIMIT :lim"""), {"sym": sym, "pre": sym + "%", "name": f"%{q.lower()}%", "lim": limit}).mappings().all()
    return [{**dict(r), "next_report": str(r["next_report"]) if r["next_report"] else None} for r in rows]


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _bars_and_macro():
    """Market and sector bars plus the slow-macro table, shared across lookups for an hour."""
    from data_pipeline.collector import SECTOR_ETF_MAP
    from data_pipeline.rebuild_pit_features import MARKET, WINDOW_DAYS, Bars
    from data_pipeline.universe import SlowMacro

    if _market["bars"] is None or time.time() - _market["at"] > 3600:
        bars = Bars(date.today() - timedelta(days=4 * 365 + WINDOW_DAYS))
        for sym in (*MARKET, *SECTOR_ETF_MAP.values()):
            bars.get(sym)
        _market.update(at=time.time(), bars=bars, macro=SlowMacro())
    return _market["bars"], _market["macro"]


def lookup(db: Session, ticker: str) -> dict[str, Any]:
    t = ticker.upper().replace(".", "-")
    hit = _cache.get(t)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]

    from backend.app.services.headline_service import _breakout_metrics, move_tier
    from data_pipeline.earnings_timing import fetch as fetch_timing
    from data_pipeline.move_model import load_live, predict_live
    from data_pipeline.rebuild_pit_features import features_asof
    from data_pipeline.universe import YAHOO_SECTOR, _next_session, _yahoo_sector
    from models.dataset import expand_feature_payload
    from models.features import add_derived

    u = db.execute(text("SELECT * FROM universe WHERE ticker=:t"), {"t": t}).mappings().first()
    sector, qtype = _yahoo_sector(t)
    if u is None and qtype is None:
        raise LookupError(f"{t} is not a listing Yahoo or NASDAQ knows")
    sector = sector or (u["sector"] if u else None)
    sector = YAHOO_SECTOR.get(sector, sector)

    reports = sorted(fetch_timing(t), key=lambda r: r["report_date"])
    bars, macro = _bars_and_macro()
    hist = bars.get(t)
    today = date.today()
    reactions = []
    for r in reports:
        if r["report_date"] >= today or hist.empty:
            continue
        out = bars.yf.outcome_snapshot(hist, datetime.combine(r["report_date"], datetime.min.time()), r["report_time"])
        if out and out.get("actual_t1_close_return") is not None:
            reactions.append({"earnings_date": str(r["report_date"]), "reaction_pct": out["actual_t1_close_return"],
                              "report_time": r["report_time"], "surprise": r.get("surprise_pct")})
    band = (statistics.median(abs(x["reaction_pct"]) for x in reactions[-12:])
            if len(reactions) >= MIN_PRIOR else None)

    upcoming = next((r for r in reports if r["report_date"] >= today), None)
    prob = tier = None
    if upcoming is not None and band and not hist.empty:
        d, rt = upcoming["report_date"], upcoming["report_time"]
        cutoff = min(_next_session(d) if (rt or "").upper() == "AMC" else d, today + timedelta(days=1))
        fresh = features_asof(bars, t, sector, cutoff)
        bundle = load_live()
        if fresh and bundle:
            payload = {**macro.asof(cutoff), **fresh}
            row = expand_feature_payload(pd.DataFrame([{"feature_payload": payload}]))
            add_derived(row, band=pd.Series([band]))
            prob = predict_live(bundle, row)
            tier = move_tier(prob, _breakout_metrics() or {})
    bars.cache.pop(t, None)

    cap_tier = u["tier"] if u else "unlisted"
    body = {
        "ticker": t, "company_name": u["name"] if u else None, "sector": sector,
        "cap_tier": cap_tier, "market_cap": _num(u["market_cap"]) if u else None,
        "in_training": cap_tier in ("core", "large", "mid", "small"),
        "next_report": ({"date": str(upcoming["report_date"]), "report_time": upcoming["report_time"],
                         "eps_estimate": upcoming.get("eps_estimate")} if upcoming else None),
        "band": band, "n_reactions": len(reactions), "reactions": reactions[-12:],
        "prob_move": prob, "move_tier": tier,
        "base_rate": (_breakout_metrics() or {}).get("base_rate"),
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }
    _cache[t] = (time.time(), body)
    return body
