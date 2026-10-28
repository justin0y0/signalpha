"""The strategy library behind /library: the graded catalogue (written weekly by
data_pipeline/run_library.py), strategies people write themselves or brainstorm with the
LLM, and their backtests — scored exactly like the catalogue, with the deflation counting
every strategy that person has tried on top of the catalogue's own trials.

A user strategy is a spec in the library's own language (services/library.py: a template,
its parameters inside fixed bounds, up to two filters, instruments). The LLM only writes
that spec; it never writes code, so what is backtested is what Autopilot would run.
"""
from __future__ import annotations

import json
import logging
import os
import pickle
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.services import library as L

log = logging.getLogger(__name__)
DATA = Path(os.getenv("DATA_DIR", "/app/data"))
DAILY_BRAINSTORMS = 40

DDL = [
    """CREATE TABLE IF NOT EXISTS strategy_custom (
        id BIGSERIAL PRIMARY KEY, holder TEXT NOT NULL, name TEXT NOT NULL, spec JSONB NOT NULL,
        origin TEXT NOT NULL DEFAULT 'manual', prompt TEXT, thesis TEXT, result JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    "CREATE INDEX IF NOT EXISTS strategy_custom_holder ON strategy_custom (holder, created_at DESC)",
]


def ensure_schema(db: Session) -> None:
    for q in DDL:
        db.execute(text(q))
    db.commit()


# ───────────────────────── the catalogue ─────────────────────────

_cache: dict[str, Any] = {}
_lock = threading.Lock()


def _load(name: str) -> Any:
    p = DATA / name
    if not p.exists():
        return None
    m = p.stat().st_mtime
    with _lock:
        hit = _cache.get(name)
        if hit and hit[0] == m:
            return hit[1]
    v = json.loads(p.read_text())
    with _lock:
        _cache[name] = (m, v)
    return v


def _brief(r: dict) -> dict:
    o, ob, a = r.get("oos") or {}, r.get("bench_oos") or {}, r.get("alpha") or {}
    return {"id": r["id"], "family": r["family"], "template": r["template"], "params": r["params"], "assets": r["assets"],
            "filters": r.get("filters") or [], "bench": r["bench"], "source": r["source"], "published": r["published"],
            "executable": r["executable"], "note": r["note"], "grade": r["grade"], "dsr": r["dsr"],
            "oos": {k: o.get(k) for k in ("cagr", "sharpe", "max_dd", "start")},
            "bench_oos": {k: ob.get(k) for k in ("cagr", "sharpe", "max_dd")},
            "full": {k: (r.get("full") or {}).get(k) for k in ("cagr", "sharpe", "max_dd", "start")},
            "alpha_t": a.get("alpha_t"), "alpha_t_oos": (r.get("alpha_oos") or {}).get("alpha_t"),
            "exposure": (r.get("activity") or {}).get("exposure"), "entries_yr": (r.get("activity") or {}).get("entries_yr")}


def table() -> dict:
    d = _load("library.json")
    if not d:
        return {"rows": [], "count": 0, "templates": templates()}
    return {"generated_at": d["generated_at"], "split": d["split"], "trials": d["trials"], "count": d["count"],
            "grades": d["grades"], "rows": [_brief(r) for r in d["rows"]], "templates": templates()}


def templates() -> list[dict]:
    """The language a user strategy is written in, for the page's editor."""
    return [{"t": t, "kind": "multi" if t in L.MULTI else "earnings" if t in L.EARN else "single",
             "bounds": {k: [lo, hi] for k, (lo, hi) in b.items()}, "live": t not in L.NOT_LIVE,
             "fixed": L.FIXED_ASSETS.get(t)} for t, b in L.BOUNDS.items()]


def detail(spec_id: str) -> dict | None:
    d = _load("library.json")
    row = next((r for r in (d or {}).get("rows", []) if r["id"] == spec_id), None)
    if row is None:
        return None
    return {**row, "curve": (_load("library_curves.json") or {}).get(spec_id)}


def resolve(db: Session, sid: str, holder: str | None) -> L.Spec | None:
    """A catalogue spec, or one of the holder's own (`u<id>`)."""
    if sid.startswith("u") and sid[1:].isdigit():
        r = db.execute(text("SELECT spec FROM strategy_custom WHERE id=:i AND holder=:h"),
                       {"i": int(sid[1:]), "h": holder}).first()
        if r is None:
            return None
        spec = r[0] if isinstance(r[0], dict) else json.loads(r[0])
        return L.spec_from_dict(spec, sid)
    return L.find(sid)


# ───────────────────────── prices for backtests ─────────────────────────

_px: dict[str, Any] = {}


def _prices() -> dict:
    p = DATA / "library_prices.pkl"
    m = p.stat().st_mtime if p.exists() else 0
    with _lock:
        if _px.get("m") == m and "d" in _px:
            return _px["d"]
    if not m:
        raise RuntimeError("The library has not been built yet")
    with open(p, "rb") as fh:
        d = pickle.load(fh)
    with _lock:
        _px.update(m=m, d=d)
    return d


def _frame(t: str) -> pd.DataFrame | None:
    """Daily OHLC for any ticker: the library's own, else Yahoo (cached for a day)."""
    base = _prices()["O"]
    if t in base:
        return base[t]
    cache = DATA / "lib_px"
    cache.mkdir(exist_ok=True)
    f = cache / f"{t.replace('^', '_')}.pkl"
    if f.exists() and time.time() - f.stat().st_mtime < 86400:
        return pd.read_pickle(f)
    import yfinance as yf

    raw = yf.download(t, start="1993-01-01", auto_adjust=True, progress=False)
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    fr = raw[["Open", "High", "Low", "Close"]].dropna(subset=["Close"])
    fr.columns = ["o", "h", "l", "c"]
    fr.index = pd.to_datetime(fr.index).tz_localize(None)
    if len(fr) < 260:
        return None
    fr.to_pickle(f)
    return fr


def run(spec: L.Spec, trials_extra: int = 0) -> dict:
    """Backtest and grade one spec the way the catalogue was graded."""
    from data_pipeline.run_library import bench_returns, events_for, monthly, score, trim

    px = _prices()
    O = {}
    for a in set(spec.assets) | {spec.bench}:
        f = _frame(a)
        if f is None:
            raise ValueError(f"No price history for {a} (or under a year of it)")
        O[a] = f
    events = dict(px["events"])
    if spec.template in L.EARN and spec.assets[0] not in events:
        g = events_for(spec.assets[0], O[spec.assets[0]])
        if g is None:
            raise ValueError(f"No earnings history for {spec.assets[0]}")
        events[spec.assets[0]] = g
    extra = {"vix": px["vix"], "fomc": px["fomc"], "events": events}
    r, w = L.backtest(spec, O, px["cash"], extra)
    r = trim(spec, r, w, events)
    if r is None or len(r) < 250:
        raise ValueError("Under a year of history once the rule can act — nothing to grade")
    meta = _load("library.json") or {}
    trials = int(meta.get("trials") or 1) + trials_extra
    b = bench_returns(spec.bench, O, px["cash"])
    row = score(spec, r, w, b, px["cash"], trials, float(meta.get("sr_var_daily") or 1e-4))
    row["trials"] = trials
    row["curve"] = {"s": monthly(r), "b": monthly(b.reindex(r.index))}
    # what the rule holds after the last close; calendar rules need the coming sessions
    try:
        from backend.app.services.strategies import sessions

        last_day = max(f.index[-1] for f in O.values()).date()
        fut = [pd.Timestamp(x) for x in sessions(last_day, last_day + timedelta(days=12)) if x > last_day]
        wn = L.weights(spec, O, {**extra, "future": fut})
        last = wn.loc[pd.Timestamp(last_day)]
        row["now"] = {k: float(v) for k, v in last.items() if v > 0}
    except Exception:  # noqa: BLE001 - no calendar, no "now"
        row["now"] = None
    return json.loads(json.dumps(row, default=float))


# ───────────────────────── user strategies ─────────────────────────

def _tried(db: Session, holder: str) -> int:
    return int(db.execute(text("SELECT COUNT(*) FROM strategy_custom WHERE holder=:h"), {"h": holder}).scalar() or 0)


def save_run(db: Session, holder: str, spec_d: dict, name: str, origin: str = "manual", prompt: str | None = None,
             thesis: str | None = None) -> dict:
    spec = L.spec_from_dict(spec_d)
    res = run(spec, trials_extra=_tried(db, holder) + 1)
    rid = db.execute(text("""INSERT INTO strategy_custom (holder, name, spec, origin, prompt, thesis, result)
                             VALUES (:h, :n, CAST(:s AS jsonb), :o, :p, :t, CAST(:r AS jsonb)) RETURNING id"""),
                     {"h": holder, "n": (name or spec.template)[:120], "s": json.dumps(L.spec_to_dict(spec)), "o": origin,
                      "p": (prompt or "")[:2000] or None, "t": (thesis or "")[:3000] or None,
                      "r": json.dumps({k: v for k, v in res.items() if k != "curve"})}).scalar()
    db.commit()
    res["id"] = f"u{rid}"
    return {"id": f"u{rid}", "name": name, "spec": L.spec_to_dict(spec), "origin": origin, "thesis": thesis,
            "result": res, "tried": _tried(db, holder)}


def mine(db: Session, holder: str) -> list[dict]:
    rows = db.execute(text("""SELECT id, name, spec, origin, prompt, thesis, result, created_at FROM strategy_custom
                              WHERE holder=:h ORDER BY created_at DESC LIMIT 100"""), {"h": holder}).mappings().all()
    out = []
    for r in rows:
        res = r["result"] if isinstance(r["result"], dict) else json.loads(r["result"] or "{}")
        out.append({"id": f"u{r['id']}", "name": r["name"], "spec": r["spec"], "origin": r["origin"], "prompt": r["prompt"],
                    "thesis": r["thesis"], "created_at": r["created_at"].isoformat(), "grade": res.get("grade"),
                    "executable": res.get("executable"), "brief": _brief({**res, "id": f"u{r['id']}"}) if res else None})
    return out


def custom_detail(db: Session, holder: str, sid: str) -> dict | None:
    spec = resolve(db, sid, holder)
    if spec is None:
        return None
    r = db.execute(text("SELECT name, origin, prompt, thesis FROM strategy_custom WHERE id=:i"), {"i": int(sid[1:])}).mappings().first()
    res = run(spec, trials_extra=_tried(db, holder))
    return {"id": sid, **dict(r), "spec": L.spec_to_dict(spec), "result": res}


def delete(db: Session, holder: str, sid: str) -> None:
    db.execute(text("DELETE FROM strategy_custom WHERE id=:i AND holder=:h"), {"i": int(sid[1:]), "h": holder})
    db.commit()


# ───────────────────────── brainstorm with the LLM ─────────────────────────

def _menu() -> str:
    lines = []
    for t, b in L.BOUNDS.items():
        ps = ", ".join(f"{k} {lo}-{hi}" for k, (lo, hi) in b.items()) or "no parameters"
        kind = "portfolio (2+ tickers)" if t in L.MULTI else "earnings, one US stock" if t in L.EARN else "one ticker"
        doc = (L.SINGLE.get(t) or L.MULTI.get(t) or L.EARN.get(t)).__doc__ or ""
        lines.append(f"- {t} [{kind}; {ps}] {doc.strip().splitlines()[0] if doc.strip() else ''}")
    return "\n".join(lines)


SYSTEM = """You turn a trader's idea into ONE backtestable rule in a fixed strategy language, then explain it.
The language (template: what it does). Weights are decided at each close and held to the next close; long only;
cash earns T-bills; costs are charged.
{menu}
Extra notes: sma_trend holds while the close is above its n-day average. sma_monthly checks at month-end vs the
n-month average. donchian buys a close above the prior `entry`-day high and exits below the prior `exit`-day low.
high52 buys a new 52-week high and exits below the `exit`-day average. tsmom holds while the n-day return is positive.
rsi2 buys RSI(2) < lo while above the 200-day average, exits on a close above the 5-day average. ibs holds one day
after a close in the bottom `lo` of the day's range. down_streak buys after n down closes, exits on an up close.
vol_target scales exposure to target/realised 20-day volatility (max 100%). static holds fixed weights given as
params.w = {{ticker: weight}} (weights add up to 1 or less). top_momentum holds the k best of the tickers by n-day
return, monthly. gtaa holds each ticker 1/n while above its 10-month average. dual_momentum and adm use fixed
tickers. earn_* rules use the stock's own earnings reports (US stocks only): earn_runup buys 5 sessions before the
report and sells at the reaction close; earn_avoid holds the stock except across reports; earn_gap_follow buys
after a gap up larger than k x the stock's usual report move and holds `hold` sessions; earn_gap_down buys after a
gap down larger than k x usual; earn_double_beat buys an EPS beat that also gapped up beyond the usual move.
Single-ticker rules can take up to two "filters" (other single-ticker templates, combined with AND), e.g. rsi2 with
a filter sma_trend n=200.
Tickers: US-listed stocks and ETFs, as on Yahoo (BRK-B, not BRK.B).
If the idea cannot be expressed exactly, pick the closest rule and say plainly what differs. Never promise returns.
Reply with JSON only:
{{"name": short name, "thesis": 2-4 sentences in {lang} on why this might work and what would break it,
  "differs": one sentence in {lang} on what the rule does NOT capture from the idea ("" if nothing),
  "spec": {{"template": ..., "params": {{...}}, "assets": [...], "filters": [{{"template": ..., "params": {{...}}}}]}}}}"""


def brainstorm(db: Session, holder: str, prompt: str, lang: str = "en", base: dict | None = None) -> dict:
    from backend.app.services.ap_auth import _redis
    from backend.app.services.groq_models import chat

    prompt = (prompt or "").strip()
    if len(prompt) < 4:
        raise ValueError("Describe the idea in a sentence or two")
    k = f"lib:bs:{holder}:{date.today().isoformat()}"
    n = _redis().incr(k)
    _redis().expire(k, 90000)
    if n > DAILY_BRAINSTORMS:
        raise PermissionError(f"{DAILY_BRAINSTORMS} brainstorms a day — try again tomorrow")
    msgs = [{"role": "system", "content": SYSTEM.format(menu=_menu(), lang="Chinese" if lang == "zh" else "English")}]
    if base:
        msgs.append({"role": "user", "content": "Current rule: " + json.dumps(base)[:1500]})
    msgs.append({"role": "user", "content": prompt[:1500]})
    last_err = None
    for attempt in range(2):
        out = chat(msgs, json_mode=True, temperature=0.3, max_tokens=900, timeout=45, reasoning_effort="medium")
        if not out:
            raise RuntimeError("The model did not answer — try again in a minute")
        try:
            d = json.loads(out)
            spec = L.spec_from_dict(d.get("spec") or {})
            break
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            last_err = str(exc)
            msgs += [{"role": "assistant", "content": out[:2000]},
                     {"role": "user", "content": f"That spec is invalid: {last_err}. Fix it and reply with the JSON only."}]
    else:
        raise ValueError(f"Could not turn that into a rule ({last_err})")
    thesis = (d.get("thesis") or "").strip()
    if d.get("differs"):
        thesis += "\n" + str(d["differs"]).strip()
    return save_run(db, holder, L.spec_to_dict(spec), str(d.get("name") or spec.template), origin="llm",
                    prompt=prompt, thesis=thesis)


# ───────────────────────── live targets (15:35 ET) ─────────────────────────

def live_keys(db: Session) -> dict[str, set[str]]:
    """Library strategies to compute today: switched on in any account, or still holding."""
    keys: dict[str, set[str]] = {}
    for r in db.execute(text("SELECT holder, settings FROM autotrade_accounts")).mappings():
        s = r["settings"] if isinstance(r["settings"], dict) else json.loads(r["settings"] or "{}")
        for sid, v in (s.get("library") or {}).items():
            if isinstance(v, dict) and v.get("on"):
                keys.setdefault(sid, set()).add(r["holder"])
    for r in db.execute(text("""SELECT DISTINCT o.rule, a.holder FROM autotrade_orders o JOIN autotrade_accounts a ON a.id=o.account_id
                                WHERE o.rule LIKE 'lib:%' AND o.leg='entry' AND o.filled_qty > 0""")).mappings():
        keys.setdefault(r["rule"][4:], set()).add(r["holder"])
    return keys


def _ohlc(tickers: list[str], days: int = 800) -> dict[str, pd.DataFrame]:
    """Adjusted daily bars from the broker feed, with today so far (IEX snapshot) appended."""
    import httpx

    from backend.app.services.strategy_lab import NY, data_headers, from_alpaca, snapshots, to_alpaca

    h = data_headers()
    today = datetime.now(timezone.utc).astimezone(NY).date()
    start = datetime.combine(today - timedelta(days=days), datetime.min.time(), tzinfo=NY).isoformat()
    end = datetime.combine(today, datetime.min.time(), tzinfo=NY).isoformat()
    rows: dict[str, list] = {}
    token = None
    while True:
        p = {"symbols": ",".join(to_alpaca(t) for t in tickers), "timeframe": "1Day", "feed": "sip", "adjustment": "all",
             "start": start, "end": end, "limit": 10000}
        if token:
            p["page_token"] = token
        r = httpx.get("https://data.alpaca.markets/v2/stocks/bars", headers=h, params=p, timeout=60)
        r.raise_for_status()
        body = r.json()
        for sym, bl in (body.get("bars") or {}).items():
            rows.setdefault(from_alpaca(sym), []).extend(bl)
        token = body.get("next_page_token")
        if not token:
            break
    snap = snapshots(tickers)
    out = {}
    ts = pd.Timestamp(today)
    for t in tickers:
        bl = rows.get(t) or []
        if not bl:
            continue
        f = pd.DataFrame(bl)
        f.index = pd.to_datetime(f.t, utc=True).dt.tz_convert(NY).dt.tz_localize(None).dt.normalize()
        f = f[["o", "h", "l", "c"]].astype(float)
        f = f[f.index < ts]
        s = snap.get(t) or {}
        last = float((s.get("latestTrade") or {}).get("p") or 0)
        bar = s.get("dailyBar") or {}
        if last and bar and pd.Timestamp(bar.get("t", "1970")).tz_convert(NY).date() == today:
            f.loc[ts] = [float(bar["o"]), max(float(bar["h"]), last), min(float(bar["l"]), last), last]
        out[t] = f.sort_index()
    return out


def live_targets(db: Session, today: date, future: list[date]) -> dict[str, tuple[dict, dict]]:
    """Today's weights for every library strategy that needs them, from today's prices so far."""
    keys = live_keys(db)
    if not keys:
        return {}
    specs = {}
    for sid, holders in keys.items():
        sp = None
        for hld in holders:
            sp = resolve(db, sid, hld)
            if sp:
                break
        if sp is not None and sp.executable:
            specs[sid] = sp
    tick = sorted({a for sp in specs.values() for a in sp.assets})
    if not tick:
        return {}
    O = _ohlc(tick)
    try:
        px = _prices()
        fomc, vix = px["fomc"], px["vix"]
    except Exception:  # noqa: BLE001 - the calendar rules then hold nothing
        fomc, vix = [], None
    extra = {"fomc": fomc, "vix": vix, "future": [pd.Timestamp(d) for d in future]}
    ts = pd.Timestamp(today)
    out = {}
    for sid, sp in specs.items():
        if not all(a in O and ts in O[a].index for a in sp.assets):
            log.warning("library %s: no price for today on %s", sid, sp.assets)
            continue
        try:
            w = L.weights(sp, O, extra)
        except Exception as exc:  # noqa: BLE001
            log.warning("library %s failed: %s", sid, exc)
            continue
        if ts not in w.index:
            continue
        row = w.loc[ts]
        wt = {a: round(float(v), 4) for a, v in row.items() if v > 1e-6}
        out[f"lib:{sid}"] = (wt, {"code": "lib", "w": ", ".join(f"{a} {v*100:.0f}%" for a, v in wt.items()) or "cash"})
    return out
