"""Oracle API + background scan worker."""
import asyncio, logging
from fastapi import APIRouter
from pydantic import BaseModel
from backend.app.services import oracle_service as O

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

class ToggleReq(BaseModel):
    keys: list[str]

@router.get("/figures")
def figures():
    en = O._enabled()
    return {"figures":[{"key":k,**v,"enabled":k in en} for k,v in O.FIGURES.items()]}

@router.post("/figures")
def toggle(req: ToggleReq):
    O.set_enabled(req.keys)
    return {"enabled": sorted(O._enabled())}

@router.get("/signals")
def signals(limit: int = 50):
    from backend.app.db.session import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(text("""SELECT figure,figure_name,source_url,headline,ticker,
            sentiment,confidence,rationale,price,market_cap,suggested_size,pulse_score,detected_at
            FROM oracle_signals ORDER BY detected_at DESC LIMIT :l"""), {"l": limit}).fetchall()
        out = []; pxc = {}
        for r in rows:
            d = dict(r._mapping); tk = d.get("ticker"); entry = d.get("price")
            if tk and tk not in pxc: pxc[tk] = _price_now(tk)
            pn = pxc.get(tk, 0)
            d["price_now"] = round(pn, 2) if pn else None
            if entry and pn and entry > 0:
                rs = (pn - entry) / entry * 100.0
                if d.get("sentiment") == "bearish": rs = -rs
                d["return_since"] = round(rs, 2)
            else:
                d["return_since"] = None
            out.append(d)
        return {"signals": out}
    finally:
        db.close()

@router.get("/leaderboard")
def leaderboard():
    from backend.app.db.session import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(text("""SELECT figure,figure_name,ticker,sentiment,price
            FROM oracle_signals ORDER BY detected_at DESC LIMIT 400""")).fetchall()
    finally:
        db.close()
    pxc = {}; agg = {}
    for r in rows:
        m = r._mapping; tk = m["ticker"]; entry = m["price"]
        if not tk or not entry or entry <= 0: continue
        if tk not in pxc: pxc[tk] = _price_now(tk)
        pn = pxc[tk]
        if not pn: continue
        rs = (pn - entry) / entry * 100.0
        if m["sentiment"] == "bearish": rs = -rs
        fig = O.FIGURES.get(m["figure"], {})
        a = agg.setdefault(m["figure"], {"figure_name": m["figure_name"],
            "emoji": fig.get("emoji", "\U0001F52E"), "type": fig.get("type", ""), "rets": []})
        a["rets"].append(rs)
    board = []
    for k, a in agg.items():
        rets = a["rets"]; nn = len(rets)
        if not nn: continue
        wins = sum(1 for x in rets if x > 0)
        board.append({"figure": k, "figure_name": a["figure_name"], "emoji": a["emoji"],
            "type": a["type"], "calls": nn, "hit_rate": round(wins / nn * 100),
            "avg_return": round(sum(rets) / nn, 2), "best": round(max(rets), 2), "worst": round(min(rets), 2)})
    board.sort(key=lambda x: x["avg_return"], reverse=True)
    return {"leaderboard": board}

@router.post("/scan-now")
def scan_now():
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
