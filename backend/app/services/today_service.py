"""Today — the market and the earnings tape, on one sheet, rendered from data.

The Brief covers the week ahead. This covers one session: how the market closed (or is
trading), which reports are out before the open and after the close, which reports
reacted and how hard against their usual move, which of those triggered the
follow-through call, and how the open calls stand.

No language model writes any of it. The two-line summary at the top is assembled from
the same numbers shown below it, so it cannot say anything the table does not.
"""
from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.services.flat_band import load_flat_bands
from backend.app.services.headline_service import _breakout_metrics, move_tier
from backend.app.services.playbook_service import SIGNAL_K
from backend.app.services.receipts_service import closes, follow_through

INDICES = [("SPY", "SPY · S&P 500"), ("QQQ", "QQQ · Nasdaq 100"), ("IWM", "IWM · Russell 2000"), ("DIA", "DIA · Dow 30"),
           ("^VIX", "VIX"), ("^TNX", "10-yr yield")]
SECTORS = [("XLK", "Technology"), ("XLF", "Financials"), ("XLV", "Health care"), ("XLE", "Energy"),
           ("XLI", "Industrials"), ("XLC", "Communication"), ("XLY", "Discretionary"),
           ("XLP", "Staples"), ("XLU", "Utilities"), ("XLRE", "Real estate"), ("XLB", "Materials")]

_cache: dict[str, Any] = {"at": 0.0, "body": None}


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _session_days() -> tuple[date, date]:
    """(the session this page is about, the session after it)."""
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/New_York"))
    d = now.date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return d, n


def _market() -> dict[str, Any]:
    syms = [s for s, _ in INDICES + SECTORS]
    px = closes(syms, date.today() - timedelta(days=12), ttl=300)
    out: dict[str, list] = {"indices": [], "sectors": []}
    for group, items in (("indices", INDICES), ("sectors", SECTORS)):
        for sym, name in items:
            if sym not in px:
                continue
            s = px[sym].dropna()
            if len(s) < 2:
                continue
            last, prev = float(s.iloc[-1]), float(s.iloc[-2])
            out[group].append({"symbol": sym, "name": name, "last": last, "chg": last / prev - 1,
                               "as_of": str(s.index[-1].date()),
                               "spark": [round(float(x), 4) for x in s.tail(10)]})
    out["sectors"].sort(key=lambda x: x["chg"], reverse=True)
    return out


def _reporting(db: Session, day: date, nxt: date) -> list[dict[str, Any]]:
    """Reports out between this session's open and the next one's: today BMO/DMH/unknown,
    today AMC, and the next session's BMO."""
    rows = db.execute(text("""
        SELECT e.ticker, e.company_name, e.earnings_date, e.report_time, e.market_cap,
               p.prob_move, p.lean_up, f.expected_move_pct AS implied, u.tier AS cap_tier
        FROM earnings_events e
        LEFT JOIN predictions p ON p.ticker=e.ticker AND p.earnings_date=e.earnings_date
        LEFT JOIN price_features f ON f.ticker=e.ticker AND f.earnings_date=e.earnings_date
        LEFT JOIN universe u ON u.ticker=e.ticker
        WHERE e.earnings_date = :d OR (e.earnings_date = :n AND e.report_time = 'BMO')
        ORDER BY e.market_cap DESC NULLS LAST"""), {"d": day, "n": nxt}).mappings().all()
    metrics = _breakout_metrics() or {}
    bands = load_flat_bands(db, sorted({r["ticker"] for r in rows})) if rows else {}
    out = []
    for r in rows:
        when = ("next_bmo" if r["earnings_date"] == nxt else
                "amc" if r["report_time"] == "AMC" else "bmo" if r["report_time"] == "BMO" else "day")
        p = _num(r["prob_move"])
        out.append({"ticker": r["ticker"], "company": r["company_name"], "when": when,
                    "earnings_date": str(r["earnings_date"]), "cap_tier": r["cap_tier"] or "core",
                    "market_cap": _num(r["market_cap"]), "prob_move": p, "move_tier": move_tier(p, metrics),
                    "lean_up": _num(r["lean_up"]), "implied": _num(r["implied"]), "band": bands.get(r["ticker"])})
    return out


def _reacted(db: Session, day: date) -> list[dict[str, Any]]:
    rows = db.execute(text("""
        SELECT o.ticker, e.company_name, o.earnings_date, e.report_time, o.actual_t1_gap_pct AS gap,
               o.actual_t1_close_return AS t1, o.flat_band AS band, c.prob_move, c.move_tier, c.lean_up,
               u.tier AS cap_tier, e.market_cap
        FROM outcomes o
        JOIN earnings_events e ON e.ticker=o.ticker AND e.earnings_date=o.earnings_date
        LEFT JOIN call_log c ON c.ticker=o.ticker AND c.earnings_date=o.earnings_date
        LEFT JOIN universe u ON u.ticker=o.ticker
        WHERE COALESCE(o.reaction_date, o.earnings_date) = :d AND o.actual_t1_close_return IS NOT NULL
        ORDER BY abs(o.actual_t1_close_return / NULLIF(o.flat_band, 0)) DESC NULLS LAST"""), {"d": day}).mappings().all()
    latest = load_flat_bands(db, sorted({r["ticker"] for r in rows})) if rows else {}
    out = []
    for r in rows:
        t1, gap = _num(r["t1"]), _num(r["gap"])
        band = _num(r["band"]) or latest.get(r["ticker"])
        out.append({"ticker": r["ticker"], "company": r["company_name"], "earnings_date": str(r["earnings_date"]),
                    "report_time": r["report_time"], "cap_tier": r["cap_tier"] or "core",
                    "move": t1, "gap": gap, "band": band,
                    "x_band": None if t1 is None or not band else abs(t1) / band,
                    "moved": None if t1 is None or not band else abs(t1) > band,
                    "flagged": r["move_tier"] == "breakout", "prob_move": _num(r["prob_move"]),
                    "triggered": gap is not None and bool(band) and gap > SIGNAL_K * band})
    return out


def _setups(db: Session, reporting: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trigger prices for the reports that trade next: where each direction rule fires.

    The gap is measured from the last close, so every rule turns into a price the
    stock has to open beyond. Rules only appear in the tiers where they hold."""
    from backend.app.services.direction_service import RULES

    names = [r for r in reporting if r["band"] and r["when"] in ("amc", "next_bmo")]
    if not names:
        return []
    last = dict(db.execute(text("SELECT ticker, price FROM market_snapshot WHERE ticker = ANY(:t)"),
                           {"t": [r["ticker"] for r in names]}).all())
    out = []
    for r in names:
        px = _num(last.get(r["ticker"]))
        if not px:
            continue
        tier = "large" if r["cap_tier"] in ("core", "large") else r["cap_tier"]
        b = r["band"]
        levels = []
        if tier in RULES["fade_spike"]["tiers"]:
            levels.append({"rule": "fade_spike", "side": "SHORT", "above": px * (1 + 3 * b)})
        if tier in RULES["follow_gap"]["tiers"]:
            levels.append({"rule": "follow_gap", "side": "LONG", "above": px * (1 + 2 * b)})
        if tier in RULES["buy_flush"]["tiers"]:
            levels.append({"rule": "buy_flush", "side": "LONG", "below": px * (1 - 2 * b)})
        if tier in RULES["fade_miss"]["tiers"]:
            levels.append({"rule": "fade_miss", "side": "SHORT", "above": px * (1 + b), "needs_miss": True})
        out.append({"ticker": r["ticker"], "company": r["company"], "when": r["when"], "last": px, "band": b,
                    "prob_move": r["prob_move"], "move_tier": r["move_tier"], "levels": levels})
    out.sort(key=lambda x: (x["move_tier"] != "breakout", -(x["prob_move"] or 0)))
    return out[:24]


def today(db: Session) -> dict[str, Any]:
    if _cache["body"] is not None and time.time() - _cache["at"] < 300:
        return _cache["body"]
    day, nxt = _session_days()
    # Reactions land in outcomes after the evening collection; before that, the latest
    # session with reactions is the useful one.
    last = db.execute(text("""SELECT max(COALESCE(reaction_date, earnings_date)) FROM outcomes
                              WHERE COALESCE(reaction_date, earnings_date) <= :d"""), {"d": day}).scalar()
    reacted = _reacted(db, last) if last else []
    reporting = _reporting(db, day, nxt)
    market = _market()
    ft = follow_through(db)
    open_calls = [c for c in ft["calls"] if c["status"] == "open"]

    spy = next((x for x in market["indices"] if x["symbol"] == "SPY"), None)
    moved = [r for r in reacted if r["moved"]]
    flagged = [r for r in reacted if r["flagged"]]
    summary = {
        "spy_chg": spy["chg"] if spy else None,
        "leader": market["sectors"][0] if market["sectors"] else None,
        "laggard": market["sectors"][-1] if market["sectors"] else None,
        "reacted": len(reacted), "moved": len(moved),
        "flagged": len(flagged), "flagged_moved": sum(1 for r in flagged if r["moved"]),
        "triggered": [r["ticker"] for r in reacted if r["triggered"]],
        "reporting": len(reporting),
        "reporting_flagged": [r["ticker"] for r in reporting if r["move_tier"] == "breakout"][:6],
        "open_calls": len(open_calls),
        "open_mean": (sum(c["ret"] for c in open_calls) / len(open_calls)) if open_calls else None,
    }
    from backend.app.services.direction_service import book, backtest

    bk = book(db)
    latest = max((c["session"] for c in bk["calls"]), default=None)
    rules = backtest(db)
    record = {"trades": sum(r["all"]["n"] for r in rules.values()), "pnl": sum(r["pnl"] for r in rules.values()),
              "market": sum(r["pnl_market"] for r in rules.values()),
              "best": max(({"rule": k, "years": f"{r['years_positive']}/{r['years_total']}", "hit": r["all"]["hit"]}
                           for k, r in rules.items()), key=lambda x: int(x["years"].split("/")[0]) / int(x["years"].split("/")[1]))}
    # Each reacted report with the calls the book made on it.
    by_ticker: dict[str, list] = {}
    for c in bk["calls"]:
        by_ticker.setdefault(c["ticker"], []).append({"rule": c["rule"], "side": c["side"], "ret": c.get("ret"), "status": c["status"]})
    for r in reacted:
        r["calls"] = by_ticker.get(r["ticker"], [])
    body = {
        "direction": {"latest_session": latest, "calls": [c for c in bk["calls"] if c["session"] == latest] if latest else [],
                      "live": bk["summary"], "record": record},
        "setups": _setups(db, reporting),
        "session": str(day), "next_session": str(nxt), "reactions_on": str(last) if last else None,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "summary": summary, "market": market, "reporting": reporting[:120],
        "reporting_total": len(reporting), "reacted": reacted[:80], "reacted_total": len(reacted),
        "open_calls": open_calls,
    }
    _cache.update(at=time.time(), body=body)
    return body
