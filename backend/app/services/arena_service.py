"""Earnings Arena — sealed, forward-only forecasts, scored after the print.

Every forecaster answers the same question before each report:

    P( |T+1 close-to-close return| > this stock's usual move )

where the usual move is the stock's band (median absolute reaction on its earlier
reports, services/flat_band.py) frozen at sealing time. It is the one question the
SignAlpha model answers better than chance, and it has a clean, unarguable outcome.

Why sealed and forward-only
---------------------------
"Claude beat human traders 76% of the time" style results come from replaying history,
and a language model has read that history: any backtest of an LLM on events before its
training cutoff is contaminated by construction. The only fair test is a forecast made
before the event and frozen. So each call is serialised canonically, hashed (SHA-256),
and every sealing batch's hashes are written into a manifest whose own hash is
submitted to OpenTimestamps calendars, which anchor it in Bitcoin. Nobody — including
us — can add, drop or edit a call after the fact without the anchor failing to verify.

Scoring is Brier score, and every forecaster is compared with the base rate on the same
events, with a bootstrap interval, so a two-week lucky streak reads as "can't tell yet"
instead of a leaderboard win. That is the difference from LLM trading arenas that rank
six accounts on a few weeks of P&L.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.services.flat_band import load_flat_bands
from backend.app.services.headline_service import _breakout_metrics

logger = get_logger(__name__)

ET = ZoneInfo("America/New_York")

SEASON = {"id": "2026Q3", "name": "Season 1 · Q3 2026 earnings", "opened": "2026-10-06"}
QUESTION = "P(|T+1 close-to-close return| > band)"

# Sealing opens this many days before a report and closes shortly before the bell.
SEAL_DAYS_AHEAD = 3
SEAL_MARGIN = timedelta(minutes=20)

OTS_CALENDARS = (
    "https://alice.btc.calendar.opentimestamps.org",
    "https://bob.btc.calendar.opentimestamps.org",
)
OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"

FORECASTERS: dict[str, dict[str, Any]] = {
    "signalpha_ml": {
        "name": "SignAlpha ML", "kind": "model", "provider": "Pooled XGBoost · 61 point-in-time features",
        "blurb": "The breakout model. Walk-forward history says its top decile moves more than usual "
                 "about two times in three.",
    },
    "options_market": {
        "name": "Options market", "kind": "market", "provider": "ATM straddle, normal approximation",
        "blurb": "What the straddle is pricing, turned into a probability. The benchmark every "
                 "options trader is actually up against.",
    },
    "base_rate": {
        "name": "Base rate", "kind": "benchmark", "provider": "Historical frequency",
        "blurb": "Says the same number every time: how often a report beats its stock's usual move. "
                 "Anything that can't beat this has no skill.",
    },
    "gpt_oss_120b": {
        "name": "GPT-OSS 120B", "kind": "llm", "provider": "OpenAI open-weight · via Groq",
        "model": "openai/gpt-oss-120b", "backend": "groq",
        "blurb": "Reads the same facts sheet as every other model and answers in one sealed call.",
    },
    "qwen3": {
        "name": "Qwen3.8 27B", "kind": "llm", "provider": "Alibaba · via Groq",
        "model": "qwen/qwen3.8-27b", "backend": "groq",
        "blurb": "Same facts sheet, same question, different model family.",
    },
    "claude": {
        "name": "Claude Opus 5.5", "kind": "llm", "provider": "Anthropic",
        "model": "claude-opus-5-5", "backend": "anthropic", "needs": "ANTHROPIC_API_KEY",
        "blurb": "Same facts sheet, same question.",
    },
}


def active_forecasters() -> list[str]:
    out = []
    for code, f in FORECASTERS.items():
        need = f.get("needs")
        if need and not os.getenv(need, "").strip():
            continue
        if f.get("backend") == "groq" and not os.getenv("GROQ_API_KEY", "").strip():
            continue
        out.append(code)
    return out


# ───────────────────────────── schema ─────────────────────────────

DDL = [
    """
    CREATE TABLE IF NOT EXISTS arena_forecasts (
        id            BIGSERIAL PRIMARY KEY,
        season        TEXT NOT NULL,
        forecaster    TEXT NOT NULL,
        ticker        TEXT NOT NULL,
        earnings_date DATE NOT NULL,
        report_time   TEXT,
        band          REAL NOT NULL,
        implied_move  REAL,
        p_breakout    REAL NOT NULL,
        lean          TEXT,
        rationale     TEXT,
        payload       TEXT NOT NULL,
        digest        TEXT NOT NULL,
        sealed_at     TIMESTAMPTZ NOT NULL,
        anchor_id     BIGINT,
        actual_move   REAL,
        broke_out     BOOLEAN,
        brier         REAL,
        resolved_at   TIMESTAMPTZ,
        UNIQUE (forecaster, ticker, earnings_date)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_arena_event ON arena_forecasts (earnings_date, ticker)",
    # Calls withdrawn before grading because the question itself was built from bad inputs.
    # They are moved here, never deleted: the digests stay in their anchored manifests, and
    # the board lists every one with the reason.
    """
    CREATE TABLE IF NOT EXISTS arena_voided (
        id            BIGINT PRIMARY KEY,
        season        TEXT NOT NULL,
        forecaster    TEXT NOT NULL,
        ticker        TEXT NOT NULL,
        earnings_date DATE NOT NULL,
        report_time   TEXT,
        band          REAL NOT NULL,
        implied_move  REAL,
        p_breakout    REAL NOT NULL,
        lean          TEXT,
        rationale     TEXT,
        payload       TEXT NOT NULL,
        digest        TEXT NOT NULL,
        sealed_at     TIMESTAMPTZ NOT NULL,
        anchor_id     BIGINT,
        voided_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        reason        TEXT NOT NULL
    )
    """,
    "ALTER TABLE arena_voided ADD COLUMN IF NOT EXISTS actual_move REAL",
    "ALTER TABLE arena_voided ADD COLUMN IF NOT EXISTS broke_out BOOLEAN",
    "ALTER TABLE arena_voided ADD COLUMN IF NOT EXISTS brier REAL",
    "ALTER TABLE arena_voided ADD COLUMN IF NOT EXISTS lean_hit BOOLEAN",
    "ALTER TABLE arena_voided ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ",
    """
    CREATE TABLE IF NOT EXISTS arena_anchors (
        id          BIGSERIAL PRIMARY KEY,
        manifest    TEXT NOT NULL,
        root        TEXT NOT NULL,
        ots         BYTEA,
        calendars   TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
]


# ───────────────────────────── helpers ─────────────────────────────

def _cutoff(earnings_date: date, report_time: str | None) -> datetime:
    """Last moment a call may be sealed. Unknown timing is treated as pre-market."""
    rt = (report_time or "").upper()
    local = datetime.combine(earnings_date, datetime.min.time(), ET)
    bell = local.replace(hour=16) if rt == "AMC" else local.replace(hour=9, minute=30)
    return bell - SEAL_MARGIN


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def options_probability(implied: float | None, band: float) -> float | None:
    """P(|move| > band) implied by an ATM straddle priced at `implied` of spot.

    For a normal move with standard deviation s, E|move| = s * sqrt(2/pi), and an ATM
    straddle is worth roughly that expectation. So s = implied / sqrt(2/pi). The straddle
    also carries a few ordinary days of vol, which makes this slightly generous to the
    move — the market forecaster is, if anything, biased toward "it breaks out".
    """
    if implied is None or not implied > 0 or not band > 0:
        return None
    s = implied / math.sqrt(2.0 / math.pi)
    return float(min(0.99, max(0.01, 2.0 * (1.0 - _norm_cdf(band / s)))))


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _clamp(p: Any) -> float | None:
    try:
        v = float(p)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return min(0.99, max(0.01, v))


# ───────────────────────────── facts sheet ─────────────────────────────

_FACT_KEYS = (
    ("ret_5d_pre", "5-day return into the report", "pct"),
    ("ret_20d_pre", "20-day return into the report", "pct"),
    ("ret_60d_pre", "60-day return into the report", "pct"),
    ("dist_52w_high", "distance from 52-week high", "pct"),
    ("dist_52w_low", "distance from 52-week low", "pct"),
    ("relative_strength_vs_spy", "20-day relative strength vs SPY", "pct"),
    ("volume_anomaly", "volume vs 20-day average (z)", "num"),
    ("atm_iv", "at-the-money implied volatility", "pct"),
    ("iv_rank", "IV rank (0-1)", "num"),
    ("vix", "VIX", "num"),
    ("up_revisions", "analyst EPS up-revisions (90d)", "num"),
    ("down_revisions", "analyst EPS down-revisions (90d)", "num"),
)


def _facts(db: Session, ticker: str, earnings_date: date, band: float, implied: float | None) -> dict[str, Any]:
    ev = db.execute(text("""
        SELECT company_name, sector, report_time FROM earnings_events
        WHERE ticker=:t AND earnings_date=:d"""), {"t": ticker, "d": earnings_date}).mappings().first() or {}
    past = db.execute(text("""
        SELECT earnings_date, actual_t1_close_return AS r FROM outcomes
        WHERE ticker=:t AND earnings_date < :d AND actual_t1_close_return IS NOT NULL
        ORDER BY earnings_date DESC LIMIT 8"""), {"t": ticker, "d": earnings_date}).mappings().all()
    payload = db.execute(text("""
        SELECT feature_payload FROM price_features WHERE ticker=:t AND earnings_date=:d"""),
        {"t": ticker, "d": earnings_date}).scalar() or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    context = {}
    for key, label, kind in _FACT_KEYS:
        v = payload.get(key) if isinstance(payload, dict) else None
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(v):
            continue
        context[label] = f"{v * 100:+.1f}%" if kind == "pct" else round(v, 2)
    return {
        "ticker": ticker,
        "company": ev.get("company_name"),
        "sector": ev.get("sector"),
        "report_date": earnings_date.isoformat(),
        "report_time": ev.get("report_time") or "unknown",
        "usual_move": f"±{band * 100:.2f}%",
        "options_implied_move": f"±{implied * 100:.2f}%" if implied else "no options snapshot",
        "last_reactions_t1": [f"{r['earnings_date']}: {float(r['r']) * 100:+.2f}%" for r in past],
        "context": context,
    }


_SYSTEM = (
    "You are a forecaster in a scored, sealed earnings-forecasting competition. You will see a "
    "facts sheet for one upcoming earnings report. Estimate the probability that the stock's "
    "close-to-close return on the first trading day after the report is larger in absolute value "
    "than its usual move (the median absolute reaction on its earlier reports). By construction "
    "roughly half of all reports clear their usual move, so stay near 0.5 unless the facts give "
    "you a real reason not to. You are scored with the Brier score: overconfidence is punished. "
    "Also give the direction you lean if it does move (UP, DOWN, or NONE), and one sentence of "
    "reasoning that cites the facts. Reply with JSON only: "
    '{"p_breakout": <0..1>, "lean": "UP"|"DOWN"|"NONE", "rationale": "<one sentence>"}'
)


def _ask_groq(model: str, facts: dict[str, Any]) -> dict[str, Any] | None:
    from backend.app.services.groq_models import chat
    out = chat(
        [{"role": "system", "content": _SYSTEM},
         {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
        model=model, json_mode=True, temperature=0.2, max_tokens=500, timeout=60,
        reasoning_effort="medium",
    )
    if not out:
        return None
    try:
        return json.loads(out)
    except ValueError:
        logger.warning("arena: %s returned non-JSON", model)
        return None


_CLAUDE_SCHEMA = {
    "type": "object",
    "properties": {
        "p_breakout": {"type": "number"},
        "lean": {"type": "string", "enum": ["UP", "DOWN", "NONE"]},
        "rationale": {"type": "string"},
    },
    "required": ["p_breakout", "lean", "rationale"],
    "additionalProperties": False,
}


def _ask_claude(model: str, facts: dict[str, Any]) -> dict[str, Any] | None:
    """Only runs when ANTHROPIC_API_KEY is set (see active_forecasters)."""
    try:
        import anthropic
    except ImportError:
        logger.warning("arena: anthropic SDK not installed")
        return None
    client = anthropic.Anthropic()
    try:
        resp = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=_SYSTEM,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _CLAUDE_SCHEMA}},
            messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
        )
    except anthropic.RateLimitError:
        logger.warning("arena: claude rate limited")
        return None
    except anthropic.APIStatusError as exc:
        logger.warning("arena: claude HTTP %s: %s", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError as exc:
        logger.warning("arena: claude connection error: %s", exc)
        return None
    if resp.stop_reason == "refusal":
        logger.warning("arena: claude refused %s", facts.get("ticker"))
        return None
    text_out = next((b.text for b in resp.content if b.type == "text"), None)
    if not text_out:
        return None
    try:
        return json.loads(text_out)
    except ValueError:
        return None


# ───────────────────────────── sealing ─────────────────────────────

def _upcoming(db: Session, now_et: datetime) -> list[dict[str, Any]]:
    today = now_et.date()
    rows = db.execute(text("""
        SELECT e.ticker, e.earnings_date, e.report_time, p.prob_move, p.lean_up,
               f.expected_move_pct AS implied
        FROM earnings_events e
        LEFT JOIN predictions p ON p.ticker=e.ticker AND p.earnings_date=e.earnings_date
        LEFT JOIN price_features f ON f.ticker=e.ticker AND f.earnings_date=e.earnings_date
        LEFT JOIN universe u ON u.ticker=e.ticker
        WHERE e.earnings_date BETWEEN :a AND :b
          -- The Arena covers the large caps: the original names plus everything over $10B.
          -- Every call costs two LLM requests, and a few thousand small caps a season
          -- would exhaust the free tiers inside a week.
          AND (u.tier IS NULL OR u.tier IN ('core', 'large'))
        ORDER BY e.earnings_date, e.ticker"""),
        {"a": today, "b": today + timedelta(days=SEAL_DAYS_AHEAD)}).mappings().all()
    out = []
    for r in rows:
        if now_et >= _cutoff(r["earnings_date"], r["report_time"]):
            continue
        d = dict(r)
        # NUMERIC columns come back as Decimal; everything downstream is float math.
        for k in ("prob_move", "implied", "lean_up"):
            d[k] = float(d[k]) if d[k] is not None else None
        out.append(d)
    return out


def _existing(db: Session, ticker: str, d: date) -> set[str]:
    return {r[0] for r in db.execute(text(
        "SELECT forecaster FROM arena_forecasts WHERE ticker=:t AND earnings_date=:d"),
        {"t": ticker, "d": d}).all()}


def _forecast(code: str, ev: dict[str, Any], band: float, facts_fn) -> dict[str, Any] | None:
    f = FORECASTERS[code]
    if code == "signalpha_ml":
        p = _clamp(ev.get("prob_move"))
        if not p:
            return None
        lu = ev.get("lean_up")
        # The model's own direction call is the experimental lean; a lean within a point
        # and a half of even is not a call and is sealed as none.
        lean = None if lu is None or abs(lu - 0.5) < 0.015 else ("UP" if lu > 0.5 else "DOWN")
        return {"p": p, "lean": lean,
                "why": "Pooled breakout model on point-in-time features; direction from the experimental lean scorecard."}
    if code == "options_market":
        p = options_probability(ev.get("implied"), band)
        if p is None:
            return None
        return {"p": p, "lean": None,
                "why": f"Straddle prices ±{ev['implied'] * 100:.1f}% against a usual ±{band * 100:.1f}%."}
    if code == "base_rate":
        m = _breakout_metrics() or {}
        p = _clamp(m.get("base_rate", 0.54))
        return {"p": p, "lean": None, "why": "Share of all out-of-sample reports that beat their usual move."}
    facts = facts_fn()
    ans = _ask_groq(f["model"], facts) if f.get("backend") == "groq" else _ask_claude(f["model"], facts)
    if not ans:
        return None
    p = _clamp(ans.get("p_breakout"))
    if p is None:
        return None
    lean = str(ans.get("lean") or "NONE").upper()
    lean = lean if lean in ("UP", "DOWN") else None
    return {"p": p, "lean": lean, "why": str(ans.get("rationale") or "")[:400]}


def seal_due(db: Session, now: datetime | None = None, limit: int | None = None) -> dict[str, Any]:
    """Seal every missing call for reports inside the window. Idempotent."""
    now_et = (now or datetime.now(timezone.utc)).astimezone(ET)
    events = _upcoming(db, now_et)
    bands = load_flat_bands(db, sorted({e["ticker"] for e in events})) if events else {}
    sealed: list[str] = []
    skipped = 0
    for ev in events:
        band = bands.get(ev["ticker"])
        if not band or not band > 0:
            skipped += 1
            continue
        have = _existing(db, ev["ticker"], ev["earnings_date"])
        facts_cache: dict[str, Any] = {}

        def facts_fn(ev=ev, band=band):
            if "v" not in facts_cache:
                facts_cache["v"] = _facts(db, ev["ticker"], ev["earnings_date"], band, ev.get("implied"))
            return facts_cache["v"]

        for code in active_forecasters():
            if code in have:
                continue
            if limit is not None and len(sealed) >= limit:
                break
            try:
                fc = _forecast(code, ev, band, facts_fn)
            except Exception as exc:  # noqa: BLE001 - one bad call must not stop the batch
                logger.warning("arena: %s on %s failed: %s", code, ev["ticker"], exc)
                fc = None
            if not fc:
                continue
            sealed_at = datetime.now(timezone.utc).replace(microsecond=0)
            if sealed_at.astimezone(ET) >= _cutoff(ev["earnings_date"], ev["report_time"]):
                continue  # an LLM call ran past the bell — a late call is not a forecast
            record = {
                "season": SEASON["id"], "forecaster": code, "ticker": ev["ticker"],
                "earnings_date": ev["earnings_date"].isoformat(), "report_time": ev["report_time"],
                "question": QUESTION, "band": round(float(band), 6),
                "p_breakout": round(fc["p"], 4), "lean": fc["lean"], "rationale": fc["why"],
                "sealed_at": sealed_at.isoformat(),
            }
            payload = _canonical(record)
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            db.execute(text("""
                INSERT INTO arena_forecasts (season, forecaster, ticker, earnings_date, report_time, band,
                    implied_move, p_breakout, lean, rationale, payload, digest, sealed_at)
                VALUES (:s,:f,:t,:d,:rt,:b,:im,:p,:l,:r,:pl,:dg,:sa)
                ON CONFLICT (forecaster, ticker, earnings_date) DO NOTHING"""),
                {"s": SEASON["id"], "f": code, "t": ev["ticker"], "d": ev["earnings_date"],
                 "rt": ev["report_time"], "b": float(band), "im": ev.get("implied"),
                 "p": record["p_breakout"], "l": fc["lean"], "r": fc["why"], "pl": payload,
                 "dg": digest, "sa": sealed_at})
            db.commit()
            sealed.append(f"{code}:{ev['ticker']}")
            if FORECASTERS[code].get("backend"):
                time.sleep(1.5)  # stay well inside free-tier rate limits
    anchor = anchor_pending(db) if sealed else None
    return {"events": len(events), "sealed": len(sealed), "skipped_no_band": skipped, "anchor": anchor}


# ───────────────────────────── voiding ─────────────────────────────

_VOID_COLS = ("id, season, forecaster, ticker, earnings_date, report_time, band, implied_move, "
              "p_breakout, lean, rationale, payload, digest, sealed_at, anchor_id")
_GRADE_COLS = "actual_move, broke_out, brier, lean_hit, resolved_at"

# Every call sealed before this moment was built on the mislabelled reaction days fixed
# on 2026-10-10 (wrong usual-move bands) and, for options, on an expiry that could lapse
# before the report. The rule was written down on 2026-10-11, before the affected
# reports were graded, and it applies to every such call whatever its score.
PRE_FIX_CUTOFF = datetime(2026, 10, 10, 19, 15, tzinfo=timezone.utc)


def void_calls(db: Session, sealed_before: datetime, reason: str, include_graded: bool = False) -> int:
    """Withdraw calls sealed before `sealed_before` into arena_voided, with the reason.

    By default only ungraded calls move. `include_graded` is for a rule that was fixed
    before the outcomes were known; graded calls then keep their scores in arena_voided,
    so the board can show exactly what was withdrawn and how it would have scored.
    """
    where = "sealed_at < :b" + ("" if include_graded else " AND resolved_at IS NULL")
    args = {"b": sealed_before, "r": reason}
    n = db.execute(text(f"""
        INSERT INTO arena_voided ({_VOID_COLS}, {_GRADE_COLS}, reason)
        SELECT {_VOID_COLS}, {_GRADE_COLS}, :r FROM arena_forecasts WHERE {where}
        ON CONFLICT (id) DO NOTHING"""), args).rowcount
    db.execute(text(f"DELETE FROM arena_forecasts WHERE {where}"), args)
    db.commit()
    return n


# ───────────────────────────── anchoring ─────────────────────────────

def anchor_pending(db: Session) -> dict[str, Any] | None:
    """Write every unanchored digest into a manifest and timestamp its hash in Bitcoin."""
    rows = db.execute(text(
        "SELECT id, digest FROM arena_forecasts WHERE anchor_id IS NULL ORDER BY digest")).all()
    if not rows:
        return None
    manifest = "".join(f"{r.digest}\n" for r in rows)
    root = hashlib.sha256(manifest.encode("ascii")).digest()
    bodies, used = [], []
    for cal in OTS_CALENDARS:
        try:
            r = httpx.post(f"{cal}/digest", content=root, timeout=20,
                           headers={"Accept": "application/vnd.opentimestamps.v1",
                                    "User-Agent": "signalpha-arena"})
            if r.status_code == 200 and r.content:
                bodies.append(r.content)
                used.append(cal)
        except Exception as exc:  # noqa: BLE001
            logger.warning("arena: OTS calendar %s failed: %s", cal, exc)
    if not bodies:
        return None  # stays unanchored; the next run retries the whole set
    # A detached .ots proof: magic, version 1, sha256 file-hash op, the digest, then the
    # timestamp tree — one branch per calendar, forks marked with 0xff.
    tree = b"".join(b"\xff" + b for b in bodies[:-1]) + bodies[-1]
    ots = OTS_MAGIC + b"\x01" + b"\x08" + root + tree
    anchor_id = db.execute(text("""
        INSERT INTO arena_anchors (manifest, root, ots, calendars) VALUES (:m, :r, :o, :c)
        RETURNING id"""), {"m": manifest, "r": root.hex(), "o": ots, "c": ",".join(used)}).scalar()
    db.execute(text("UPDATE arena_forecasts SET anchor_id=:a WHERE id = ANY(:ids)"),
               {"a": anchor_id, "ids": [r.id for r in rows]})
    db.commit()
    return {"id": anchor_id, "root": root.hex(), "calls": len(rows), "calendars": used}


def anchor_file(db: Session, anchor_id: int, kind: str) -> tuple[bytes, str] | None:
    row = db.execute(text("SELECT manifest, ots FROM arena_anchors WHERE id=:i"), {"i": anchor_id}).first()
    if not row:
        return None
    if kind == "manifest":
        return row.manifest.encode("ascii"), "text/plain; charset=us-ascii"
    return bytes(row.ots), "application/octet-stream"


# ───────────────────────────── resolution ─────────────────────────────

def resolve_due(db: Session) -> dict[str, Any]:
    rows = db.execute(text("""
        SELECT a.id, a.band, a.p_breakout, a.lean, o.actual_t1_close_return AS r
        FROM arena_forecasts a
        JOIN outcomes o ON o.ticker=a.ticker AND o.earnings_date=a.earnings_date
        WHERE a.resolved_at IS NULL AND o.actual_t1_close_return IS NOT NULL""")).all()
    n = 0
    for r in rows:
        move = float(r.r)
        if not math.isfinite(move):
            continue
        y = 1.0 if abs(move) > float(r.band) else 0.0
        hit = None if r.lean not in ("UP", "DOWN") or move == 0 else ((move > 0) == (r.lean == "UP"))
        db.execute(text("""
            UPDATE arena_forecasts SET actual_move=:m, broke_out=:y, brier=:b, lean_hit=:h, resolved_at=NOW()
            WHERE id=:i"""), {"m": move, "y": bool(y), "b": (float(r.p_breakout) - y) ** 2, "h": hit, "i": r.id})
        n += 1
    db.commit()
    return {"resolved": n}


# ───────────────────────────── read side ─────────────────────────────

def _leaderboard(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Paired comparison with the base rate: same events, bootstrap 90% interval."""
    by_event: dict[tuple[str, str], dict[str, float]] = {}
    for r in rows:
        by_event.setdefault((r["ticker"], str(r["earnings_date"])), {})[r["forecaster"]] = float(r["brier"])
    import numpy as np

    out = []
    rng = np.random.default_rng(7)
    for code in FORECASTERS:
        mine = [(k, v[code]) for k, v in by_event.items() if code in v]
        if not mine:
            continue
        briers = [b for _, b in mine]
        paired = [v["base_rate"] - v[code] for k, v in by_event.items() if code in v and "base_rate" in v]
        entry: dict[str, Any] = {"code": code, "n": len(briers), "brier": sum(briers) / len(briers)}
        hits = [r["lean_hit"] for r in rows if r["forecaster"] == code and r.get("lean_hit") is not None]
        if hits:
            k, m = sum(1 for h in hits if h), len(hits)
            # Wilson 90% interval: a direction record is only news once it excludes 50%.
            z = 1.645
            c = (k / m + z * z / (2 * m)) / (1 + z * z / m)
            hw = z * math.sqrt((k / m) * (1 - k / m) / m + z * z / (4 * m * m)) / (1 + z * z / m)
            entry.update(dir_n=m, dir_hit=k / m, dir_lo=c - hw, dir_hi=c + hw)
        if code != "base_rate" and len(paired) >= 2:
            arr = np.asarray(paired)
            mean = float(arr.mean())
            boots = arr[rng.integers(0, len(arr), size=(1000, len(arr)))].mean(axis=1)
            lo, hi = (float(x) for x in np.quantile(boots, [0.05, 0.95]))
            base_b = [v["base_rate"] for v in by_event.values() if code in v and "base_rate" in v]
            entry.update(skill=mean, skill_lo=lo, skill_hi=hi,
                         bss=1.0 - (sum(briers) / len(briers)) / max(1e-9, sum(base_b) / len(base_b)))
            if len(paired) < 20:
                entry["verdict"] = "warming_up"
            elif lo > 0:
                entry["verdict"] = "beating_base"
            elif hi < 0:
                entry["verdict"] = "worse_than_base"
            else:
                entry["verdict"] = "indistinguishable"
        else:
            entry["verdict"] = "benchmark" if code == "base_rate" else "warming_up"
        out.append(entry)
    out.sort(key=lambda e: e["brier"])
    return out


def board(db: Session) -> dict[str, Any]:
    now_et = datetime.now(timezone.utc).astimezone(ET)
    today = now_et.date()
    calls = [dict(r) for r in db.execute(text("""
        SELECT a.forecaster, a.ticker, a.earnings_date, a.report_time, a.band, a.implied_move,
               a.p_breakout, a.lean, a.rationale, a.payload, a.digest, a.sealed_at, a.anchor_id,
               a.actual_move, a.broke_out, a.brier, a.lean_hit, a.resolved_at, e.company_name, e.sector
        FROM arena_forecasts a
        LEFT JOIN earnings_events e ON e.ticker=a.ticker AND e.earnings_date=a.earnings_date
        WHERE a.season=:s ORDER BY a.earnings_date, a.ticker"""), {"s": SEASON["id"]}).mappings().all()]

    events: dict[tuple[str, str], dict[str, Any]] = {}
    for c in calls:
        key = (c["ticker"], str(c["earnings_date"]))
        ev = events.setdefault(key, {
            "ticker": c["ticker"], "company": c["company_name"], "sector": c["sector"],
            "earnings_date": str(c["earnings_date"]), "report_time": c["report_time"],
            "band": c["band"], "implied_move": c["implied_move"],
            "cutoff": _cutoff(c["earnings_date"], c["report_time"]).isoformat(),
            "actual_move": c["actual_move"], "broke_out": c["broke_out"], "calls": [],
        })
        ev["calls"].append({
            "forecaster": c["forecaster"], "p": c["p_breakout"], "lean": c["lean"],
            "rationale": c["rationale"], "digest": c["digest"], "payload": c["payload"],
            "sealed_at": c["sealed_at"].isoformat() if c["sealed_at"] else None,
            "anchor_id": c["anchor_id"], "brier": c["brier"], "lean_hit": c["lean_hit"],
        })

    resolved = [e for e in events.values() if e["broke_out"] is not None]
    pending = [e for e in events.values() if e["broke_out"] is None]
    resolved.sort(key=lambda e: e["earnings_date"], reverse=True)

    # Reports that are close but not yet inside the sealing window, so the page can say
    # when they open instead of showing nothing.
    queued = [dict(r) for r in db.execute(text("""
        SELECT e.ticker, e.company_name AS company, e.earnings_date, e.report_time
        FROM earnings_events e
        LEFT JOIN universe u ON u.ticker=e.ticker
        WHERE e.earnings_date > :a AND e.earnings_date <= :b
          AND (u.tier IS NULL OR u.tier IN ('core', 'large'))
          AND NOT EXISTS (SELECT 1 FROM arena_forecasts a
                          WHERE a.ticker=e.ticker AND a.earnings_date=e.earnings_date)
        ORDER BY e.earnings_date, e.ticker LIMIT 40"""),
        {"a": today, "b": today + timedelta(days=14)}).mappings().all()]
    # A stock with no reaction history has no band, so it can never be sealed; listing it
    # as "opening soon" would be a promise the scheduler never keeps.
    eligible = load_flat_bands(db, sorted({q["ticker"] for q in queued})) if queued else {}
    queued = [q for q in queued if eligible.get(q["ticker"])]
    for q in queued:
        q["opens"] = (datetime.combine(q["earnings_date"], datetime.min.time(), ET)
                      - timedelta(days=SEAL_DAYS_AHEAD)).isoformat()
        q["earnings_date"] = str(q["earnings_date"])

    anchors = [dict(r) for r in db.execute(text("""
        SELECT id, root, calendars, created_at,
               (SELECT count(*) FROM arena_forecasts f WHERE f.anchor_id=a.id)
               + (SELECT count(*) FROM arena_voided v WHERE v.anchor_id=a.id) AS calls
        FROM arena_anchors a ORDER BY id DESC LIMIT 20""")).mappings().all()]
    for a in anchors:
        a["created_at"] = a["created_at"].isoformat()

    voided = [dict(r) for r in db.execute(text("""
        SELECT ticker, earnings_date, count(*) AS calls, min(sealed_at) AS sealed_at,
               max(voided_at) AS voided_at, max(band) AS band, max(implied_move) AS implied_move,
               max(anchor_id) AS anchor_id, max(reason) AS reason,
               max(actual_move) AS actual_move, bool_or(broke_out) AS broke_out,
               avg(brier) FILTER (WHERE forecaster='signalpha_ml') AS ml_brier,
               avg(brier) FILTER (WHERE forecaster='base_rate') AS base_brier
        FROM arena_voided WHERE season=:s GROUP BY ticker, earnings_date
        ORDER BY earnings_date, ticker"""), {"s": SEASON["id"]}).mappings().all()]
    for v in voided:
        v["earnings_date"] = str(v["earnings_date"])
        v["sealed_at"] = v["sealed_at"].isoformat()
        v["voided_at"] = v["voided_at"].isoformat()

    graded = [c for c in calls if c["brier"] is not None]
    active = set(active_forecasters())
    return {
        "season": SEASON,
        "question": QUESTION,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "forecasters": [
            {"code": k, **{x: v.get(x) for x in ("name", "kind", "provider", "blurb")},
             "active": k in active, "calls": sum(1 for c in calls if c["forecaster"] == k)}
            for k, v in FORECASTERS.items() if k in active or any(c["forecaster"] == k for c in calls)
        ],
        "leaderboard": _leaderboard(graded),
        "pending": pending,
        "resolved": resolved[:40],
        "queued": queued,
        "anchors": anchors,
        "voided": voided,
        "totals": {"calls": len(calls), "graded": len(graded), "events": len(events),
                   "voided": sum(v["calls"] for v in voided)},
    }
