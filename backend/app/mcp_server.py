"""SignAlpha as an MCP server — earnings risk for AI agents that trade.

Brokers now let Claude and ChatGPT place orders through MCP (Robinhood, Interactive
Brokers, Alpaca). What those agents lack is event awareness: an agent asked to "buy
some JNJ" will happily do it the afternoon before a report it has never heard of. This
server is the check it can call first. Every tool is read-only, returns the evidence
behind its numbers, and says what the numbers cannot do.

Mounted by main.py at /api/mcp (streamable HTTP, stateless, JSON responses).
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from backend.app.services.flat_band import load_flat_bands
from backend.app.services.headline_service import _breakout_metrics, move_tier

DISCLAIMER = (
    "Research data, not investment advice. Before a report, direction is a coin flip; the "
    "calls with measured skill are whether a report moves the stock more than usual, and "
    "post-report follow-through after a large gap up."
)

mcp = MCPServer(
    name="SignAlpha",
    title="SignAlpha earnings risk",
    description="Earnings-event risk for US large caps: breakout probability, usual move, "
                "options-implied move, and the walk-forward evidence behind them.",
    instructions=(
        "Call portfolio_earnings_risk before trading or rebalancing positions, and earnings_risk "
        "before opening a position in a single name. A 'breakout' tier means the report is in the "
        "model's top decile for moving the stock more than its usual earnings move; it says nothing "
        "about direction. Quote the evidence fields when you relay a number to a user."
    ),
    website_url="https://signalpha.app",
    version="1.0.0",
)


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _evidence() -> dict[str, Any]:
    m = _breakout_metrics() or {}
    top = m.get("top_decile") or {}
    return {
        "breakout_top_decile_hit_rate": top.get("move_rate"),
        "base_rate": m.get("base_rate"),
        "top_decile_reports": top.get("n"),
        "auc": m.get("auc"),
        "method": "pooled XGBoost, walk-forward, 61 point-in-time features",
        "details": "https://signalpha.app/model",
    }


def _rows(db, tickers: list[str] | None, start: date, end: date) -> list[dict[str, Any]]:
    q = """
        SELECT e.ticker, e.company_name, e.sector, e.earnings_date, e.report_time,
               p.prob_move, f.expected_move_pct AS implied
        FROM earnings_events e
        LEFT JOIN predictions p ON p.ticker=e.ticker AND p.earnings_date=e.earnings_date
        LEFT JOIN price_features f ON f.ticker=e.ticker AND f.earnings_date=e.earnings_date
        WHERE e.earnings_date BETWEEN :a AND :b
    """
    params: dict[str, Any] = {"a": start, "b": end}
    if tickers is not None:
        q += " AND e.ticker = ANY(:t)"
        params["t"] = tickers
    q += " ORDER BY e.earnings_date, e.ticker"
    rows = [dict(r) for r in db.execute(text(q), params).mappings().all()]
    bands = load_flat_bands(db, sorted({r["ticker"] for r in rows})) if rows else {}
    metrics = _breakout_metrics()
    out = []
    for r in rows:
        pm = _f(r["prob_move"])
        out.append({
            "ticker": r["ticker"],
            "company": r["company_name"],
            "sector": r["sector"],
            "earnings_date": str(r["earnings_date"]),
            "report_time": r["report_time"] or "unknown",
            "breakout_probability": pm,
            "breakout_tier": move_tier(pm, metrics),
            "usual_move": bands.get(r["ticker"]),
            "options_implied_move": _f(r["implied"]),
        })
    return out


def _clean(tickers: list[str]) -> list[str]:
    out = []
    for t in tickers[:200]:
        s = str(t).upper().strip()
        if s and len(s) <= 10 and s.replace(".", "").replace("-", "").isalnum():
            out.append(s)
    return sorted(set(out))


@mcp.tool(title="Upcoming earnings with breakout risk")
def upcoming_earnings(days: int = 7, only_flagged: bool = False) -> dict[str, Any]:
    """Earnings reports in the next `days` days (max 30) for the tracked universe, with each
    report's breakout probability and tier, the stock's usual earnings move, and the move the
    options market is pricing. Set only_flagged to return just 'breakout' and 'elevated' tiers."""
    days = max(1, min(int(days), 30))
    db = SessionLocal()
    try:
        today = date.today()
        rows = _rows(db, None, today, today + timedelta(days=days))
    finally:
        db.close()
    if only_flagged:
        rows = [r for r in rows if r["breakout_tier"] in ("breakout", "elevated")]
    return {"reports": rows, "count": len(rows), "evidence": _evidence(), "disclaimer": DISCLAIMER}


@mcp.tool(title="Earnings risk for one stock")
def earnings_risk(ticker: str) -> dict[str, Any]:
    """Next earnings report for `ticker`: date, breakout probability and tier, usual move,
    options-implied move, and a summary of every past earnings reaction on record (how often
    the stock moved more than the move options are pricing now)."""
    t = _clean([ticker])
    if not t:
        return {"error": "invalid ticker"}
    sym = t[0]
    db = SessionLocal()
    try:
        today = date.today()
        nxt = _rows(db, [sym], today, today + timedelta(days=120))
        hist = [abs(float(r[0])) for r in db.execute(text("""
            SELECT actual_t1_close_return FROM outcomes
            WHERE ticker=:t AND actual_t1_close_return IS NOT NULL AND earnings_date < :d"""),
            {"t": sym, "d": today}).all() if _f(r[0]) is not None and abs(float(r[0])) < 1]
    finally:
        db.close()
    report = nxt[0] if nxt else None
    implied = report["options_implied_move"] if report else None
    history = None
    if hist:
        history = {
            "reports": len(hist),
            "average_abs_move": sum(hist) / len(hist),
            "largest_abs_move": max(hist),
            "times_exceeding_current_implied": sum(1 for h in hist if implied and h > implied) if implied else None,
        }
    if not report and not history:
        return {"ticker": sym, "error": "not in the tracked universe"}
    return {"ticker": sym, "next_report": report, "past_reactions": history,
            "evidence": _evidence(), "disclaimer": DISCLAIMER}


@mcp.tool(title="Portfolio earnings-risk scan")
def portfolio_earnings_risk(tickers: list[str], days: int = 14) -> dict[str, Any]:
    """Which of these holdings report earnings in the next `days` days (max 45), and how
    likely each report is to move the stock more than usual. Call this before trading or
    rebalancing a portfolio. Holdings outside the tracked universe are listed as unknown."""
    syms = _clean(tickers)
    days = max(1, min(int(days), 45))
    db = SessionLocal()
    try:
        today = date.today()
        rows = _rows(db, syms, today, today + timedelta(days=days))
        known = {r[0] for r in db.execute(text(
            "SELECT DISTINCT ticker FROM earnings_events WHERE ticker = ANY(:t)"), {"t": syms}).all()}
    finally:
        db.close()
    reporting = {r["ticker"] for r in rows}
    return {
        "reporting": rows,
        "flagged": [r["ticker"] for r in rows if r["breakout_tier"] in ("breakout", "elevated")],
        "no_report_in_window": [s for s in syms if s in known and s not in reporting],
        "unknown": [s for s in syms if s not in known],
        "evidence": _evidence(),
        "disclaimer": DISCLAIMER,
    }


@mcp.tool(title="Post-earnings follow-through signals")
def post_earnings_signals(days: int = 10) -> dict[str, Any]:
    """Reports that reacted in the last `days` days, with the one direction call SignAlpha
    makes: 'long' when the stock opened up by more than twice its usual earnings move
    (historically these kept rising over the next five sessions more often than other
    reports). Long-only: big gap-downs have not kept falling, so they carry no call.
    Includes the rule's full historical record."""
    from backend.app.services.playbook_service import live

    db = SessionLocal()
    try:
        out = live(db, max(1, min(int(days), 30)))
    finally:
        db.close()
    out["disclaimer"] = DISCLAIMER
    return out


@mcp.tool(title="Model track record")
def model_track_record() -> dict[str, Any]:
    """The model's out-of-sample record, including where it fails: three-class direction
    accuracy against the always-FLAT baseline, and breakout detection by decile."""
    from backend.app.services.headline_service import headline

    db = SessionLocal()
    try:
        h = headline(db)
    finally:
        db.close()
    return {"headline": h, "disclaimer": DISCLAIMER}


@mcp.tool(title="Earnings Arena standings")
def arena_standings() -> dict[str, Any]:
    """The Earnings Arena: AI models, SignAlpha's model, the options market and a base rate
    each seal a breakout forecast before every report (hashed and anchored in Bitcoin), then
    get Brier-scored. Returns the leaderboard and the calls on reports still to come."""
    from backend.app.services.arena_service import board

    db = SessionLocal()
    try:
        b = board(db)
    finally:
        db.close()
    pending = [{
        "ticker": e["ticker"], "earnings_date": e["earnings_date"], "usual_move": e["band"],
        "options_implied_move": e["implied_move"],
        "calls": {c["forecaster"]: c["p"] for c in e["calls"]},
    } for e in b["pending"]]
    return {"season": b["season"], "question": b["question"], "leaderboard": b["leaderboard"],
            "upcoming": pending, "page": "https://signalpha.app/arena", "disclaimer": DISCLAIMER}


# Behind nginx the Host header is signalpha.app; the SDK's default rebinding protection
# only admits localhost, which would reject every real request.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["signalpha.app", "www.signalpha.app", "localhost:*", "127.0.0.1:*", "backend:*"],
        allowed_origins=["https://signalpha.app", "https://www.signalpha.app",
                         "http://localhost:*", "http://127.0.0.1:*"],
    ),
)
