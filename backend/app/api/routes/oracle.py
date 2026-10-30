"""Oracle API + background scan worker."""
import asyncio, logging, os, time
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from backend.app.services import oracle_service as O
from backend.app.services.oracle_figures import portrait

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/oracle", tags=["oracle"])

def _price_now(tk):
    """Current price, 10-min redis-cached to spare yfinance."""
    if not tk: return 0
    if O._rc is not None:
        try:
            c = O._rc.get(f"oracle:pxnow:{tk}")
            if c is not None: return float(c)
        except Exception: pass
    px, _ = O._quote(tk)
    if O._rc is not None and px and px > 0:
        try: O._rc.setex(f"oracle:pxnow:{tk}", 600, str(px))
        except Exception: pass
    return px or 0

def _prices_now(tickers):
    """Latest price for many tickers in one download (10-min cache): the leaderboard
    covers ~150 tickers and fetching them one by one took most of a minute."""
    out, need = {}, []
    for tk in set(t for t in tickers if t):
        hit = O._rc.get(f"oracle:pxnow:{tk}") if O._rc is not None else None
        if hit is not None: out[tk] = float(hit)
        else: need.append(tk)
    if need:
        try:
            import yfinance as yf
            h = yf.download(need, period="5d", progress=False, auto_adjust=False, threads=True)["Close"]
            if not hasattr(h, "columns"): h = h.to_frame(need[0])
            for tk in need:
                col = h[tk].dropna() if tk in h.columns else []
                if len(col):
                    out[tk] = float(col.iloc[-1])
                    if O._rc is not None: O._rc.setex(f"oracle:pxnow:{tk}", 600, str(out[tk]))
        except Exception as e:
            log.warning(f"oracle prices: {e}")
        for tk in need:
            if tk not in out: out[tk] = _price_now(tk)
    return out

_spy = {"at": 0.0, "s": None}
def _spy_on(ts):
    """SPY close on the session of `ts` (or the one before) — the benchmark a signal is held against."""
    import pandas as pd
    if _spy["s"] is None or time.time() - _spy["at"] > 3600:
        try:
            import yfinance as yf
            c = yf.Ticker("SPY").history(period="2y", auto_adjust=False)["Close"]
            c.index = c.index.tz_localize(None).normalize()
            _spy.update(s=c, at=time.time())
        except Exception as e:
            log.warning(f"oracle spy: {e}")
            return None
    s = _spy["s"]
    if s is None or s.empty: return None
    d = pd.Timestamp(ts).tz_convert("America/New_York").tz_localize(None).normalize()
    s = s[s.index <= d]
    return float(s.iloc[-1]) if len(s) else None

def _scored(rows):
    """Return since each signal, signed by direction, and the same against SPY."""
    px = _prices_now([r["ticker"] for r in rows] + ["SPY"])
    spy_now = px.get("SPY")
    for d in rows:
        entry, pn = d.get("price"), px.get(d.get("ticker"))
        sign = -1 if d.get("sentiment") == "bearish" else 1
        d["price_now"] = round(pn, 2) if pn else None
        d["return_since"] = d["excess_since"] = None
        if entry and pn and entry > 0:
            r = (pn - entry) / entry
            d["return_since"] = round(sign * r * 100, 2)
            s0 = _spy_on(d["detected_at"])
            if s0 and spy_now:
                d["excess_since"] = round(sign * (r - (spy_now - s0) / s0) * 100, 2)
    return rows

_LIVE = "status NOT IN ('duplicate','own_company','rejected') AND figure = ANY(:figs)"

def _admin(tok):
    want = os.getenv("ADMIN_TOKEN", "").strip()
    if not want or tok != want:
        raise HTTPException(status_code=401, detail="unauthorized")

class ToggleReq(BaseModel):
    keys: list[str]

@router.get("/figures")
def figures():
    from backend.app.db.session import SessionLocal
    from sqlalchemy import text
    en = O._enabled()
    with SessionLocal() as db:
        st = {r.figure: r for r in db.execute(text(f"""SELECT figure, count(*) FILTER (WHERE detected_at > now() - interval '30 days') n30,
                count(*) n, max(detected_at) last FROM oracle_signals WHERE {_LIVE} GROUP BY figure"""),
                {"figs": list(O.FIGURES)}).fetchall()}
    out = []
    for k, v in O.FIGURES.items():
        r = st.get(k)
        out.append({"key": k, **{f: v.get(f) for f in ("name", "zh", "group", "type", "emoji", "why", "why_zh", "cadence")},
                    "sources": sorted({s["type"] for s in v["sources"]}), "portrait": portrait(k),
                    "enabled": k in en, "health": O.figure_health(k),
                    "signals_30d": r.n30 if r else 0, "signals": r.n if r else 0,
                    "last_signal": r.last.isoformat() if r and r.last else None})
    return {"figures": out}

@router.post("/figures")
def toggle(req: ToggleReq, x_admin_token: str = Header(default="")):
    # Was open to anyone: one visitor could switch a figure off for the whole site.
    _admin(x_admin_token)
    O.set_enabled(req.keys)
    return {"enabled": sorted(O._enabled())}

@router.get("/signals")
def signals(limit: int = 50, figure: str = ""):
    from backend.app.db.session import SessionLocal
    from sqlalchemy import text
    with SessionLocal() as db:
        rows = db.execute(text(f"""SELECT figure,figure_name,source_url,headline,ticker,
            sentiment,confidence,rationale,price,market_cap,suggested_size,pulse_score,detected_at,kind
            FROM oracle_signals WHERE {_LIVE} AND (:fig = '' OR figure = :fig)
            ORDER BY detected_at DESC LIMIT :l"""), {"l": min(limit, 200), "figs": list(O.FIGURES), "fig": figure}).fetchall()
    return {"signals": _scored([dict(r._mapping) for r in rows])}

@router.get("/leaderboard")
def leaderboard():
    """Per figure: calls in the last 120 days, hit rate and average return since each call,
    and the same against SPY over the same days — the column that says whether following
    them beat just holding the index."""
    from backend.app.db.session import SessionLocal
    from sqlalchemy import text
    hit = O._rc.get("oracle:lb") if O._rc is not None else None
    if hit:
        import json
        return json.loads(hit)
    with SessionLocal() as db:
        rows = [dict(r._mapping) for r in db.execute(text(f"""SELECT figure,figure_name,ticker,sentiment,price,detected_at
            FROM oracle_signals WHERE {_LIVE} AND detected_at > now() - interval '120 days'
            ORDER BY detected_at DESC LIMIT 1500"""), {"figs": list(O.FIGURES)}).fetchall()]
    agg = {}
    for d in _scored(rows):
        if d["return_since"] is None: continue
        a = agg.setdefault(d["figure"], {"figure_name": d["figure_name"], "rets": [], "ex": []})
        a["rets"].append(d["return_since"])
        if d["excess_since"] is not None: a["ex"].append(d["excess_since"])
    board = []
    for k, a in agg.items():
        rets, ex = a["rets"], a["ex"]; nn = len(rets)
        fig = O.FIGURES.get(k, {})
        board.append({"figure": k, "figure_name": a["figure_name"], "emoji": fig.get("emoji", "\U0001F52E"),
            "type": fig.get("type", ""), "portrait": portrait(k), "calls": nn,
            "hit_rate": round(sum(1 for x in rets if x > 0) / nn * 100),
            "avg_return": round(sum(rets) / nn, 2), "best": round(max(rets), 2), "worst": round(min(rets), 2),
            "avg_excess": round(sum(ex) / len(ex), 2) if ex else None,
            "beat_spy": round(sum(1 for x in ex if x > 0) / len(ex) * 100) if ex else None})
    board.sort(key=lambda x: (x["avg_excess"] if x["avg_excess"] is not None else -999), reverse=True)
    body = {"leaderboard": board}
    if O._rc is not None:
        import json
        O._rc.setex("oracle:lb", 600, json.dumps(body))
    return body

@router.post("/scan-now")
def scan_now(x_admin_token: str = Header(default="")):
    # The worker scans every 90 s; a public button only let anyone spend the LLM quota.
    _admin(x_admin_token)
    n = O.scan_once()
    return {"new_signals": n}

async def oracle_worker():
    import os
    log.info("Oracle worker started")
    while True:
        try:
            await asyncio.sleep(int(os.getenv("ORACLE_SCAN_SEC","90")))
            if os.getenv("ORACLE_ENABLED","1").lower() in ("1","true","yes"):
                n = await asyncio.to_thread(O.scan_once)
                if n: log.info(f"oracle scan: {n} new signals")
        except Exception:
            log.exception("oracle worker err")


@router.get("/ohlc")
def ohlc(ticker: str, since: str = ""):
    import yfinance as yf, datetime as _dt
    try:
        start = _dt.date.fromisoformat(since) if since and len(since) == 10 else _dt.date.today() - _dt.timedelta(days=120)
    except Exception:
        start = _dt.date.today() - _dt.timedelta(days=120)
    start = start - _dt.timedelta(days=3)
    try:
        h = yf.download(ticker, start=start.isoformat(), progress=False, auto_adjust=True)
        if h is None or h.empty:
            return {"ticker": ticker, "candles": []}
        idx = list(h.index)
        o = h["Open"].values.flatten(); hi = h["High"].values.flatten()
        lo = h["Low"].values.flatten(); cl = h["Close"].values.flatten()
        candles = [{"t": str(idx[i].date()), "o": round(float(o[i]), 2), "h": round(float(hi[i]), 2),
                    "l": round(float(lo[i]), 2), "c": round(float(cl[i]), 2)} for i in range(len(idx))]
        return {"ticker": ticker, "candles": candles}
    except Exception as e:
        return {"ticker": ticker, "candles": [], "error": str(e)[:120]}


@router.get("/insiders")
def insiders():
    """Officers and directors buying their own stock (Form 4, code P), last 30 days, grouped by
    company; clusters of three or more insiders are what the insider_cluster strategy trades.
    Alongside: what following the desk's other sources has been worth (strategy lab files)."""
    import json
    from pathlib import Path
    import os
    from sqlalchemy import text
    from backend.app.db.session import SessionLocal

    with SessionLocal() as db:
        rows = [dict(r) for r in db.execute(text("""
            SELECT t.ticker, count(DISTINCT t.owner_cik) insiders, sum(t.value) value, max(t.filed) last_filed,
                   min(t.traded) first_trade, u.tier
            FROM insider_trades t LEFT JOIN universe u ON u.ticker=t.ticker
            WHERE t.filed >= CURRENT_DATE - 30 AND t.value >= 10000
            GROUP BY t.ticker, u.tier ORDER BY count(DISTINCT t.owner_cik) DESC, sum(t.value) DESC LIMIT 40""")).mappings()]
        sig = [dict(r) for r in db.execute(text("""SELECT ticker, session, exit_session, meta FROM strategy_signals
                                                   WHERE strategy='insider_cluster' ORDER BY session DESC LIMIT 20""")).mappings()]
        since = db.execute(text("SELECT min(filed) FROM insider_trades")).scalar()
    for r in rows:
        r["value"] = float(r["value"] or 0)
        r["last_filed"], r["first_trade"] = str(r["last_filed"]), str(r["first_trade"])
    for r in sig:
        r["session"], r["exit_session"] = str(r["session"]), str(r["exit_session"])
    base = Path(os.getenv("DATA_DIR", "/app/data"))
    load = lambda n: json.loads((base / n).read_text()) if (base / n).exists() else {}  # noqa: E731
    fl, misc = load("research_filings.json").get("rules", {}), load("research_misc.json")
    pick = lambda b: {"excess": (b.get("excess") or {}).get("mean"), "t": (b.get("excess") or {}).get("t"),  # noqa: E731
                      "n": (b.get("excess") or {}).get("n"), "cagr": (b.get("all") or {}).get("cagr"),
                      "spy": (b.get("all") or {}).get("spy_cagr")} if b else None
    return {"since": str(since) if since else None, "companies": rows, "signals": sig,
            "verdicts": {"calls": {"h5": ((misc.get("oracle") or {}).get("h5") or {}),
                                   "h1": ((misc.get("oracle") or {}).get("h1") or {})},
                         "insider_cluster": pick(fl.get("insider_cluster")),
                         "clone_buffett": pick(fl.get("clone_buffett")), "clone_ackman": pick(fl.get("clone_ackman"))}}
