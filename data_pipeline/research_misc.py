"""Two of the strategy-lab checks that need no new market data beyond daily bars.

1. Oracle (celebrity / fund-manager signals, services/oracle_service.py): every signal
   since the desk went live, entered at the first close after it was detected (one
   placed after the bell waits for the next session), held 1 and 5 sessions, signed by
   its stated direction, against SPY over the same days.
2. The breakout model as a filter on follow_gap: the post-earnings rule's T+20 return in
   each tercile of the walk-forward prob_move — raw, and against every report in the
   same year and tercile (stocks the model expects to move a lot also drift up more
   after earnings, so the raw split flatters the filter). Tercile cut points come only
   from earlier years.

    python -m data_pipeline.research_misc     # writes $DATA_DIR/research_misc.json
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from backend.app.services.direction_service import COST
from backend.app.services.playbook_service import _frame
from backend.app.services.strategy_lab import data_headers, from_alpaca, to_alpaca

OUT = Path(os.getenv("DATA_DIR", "/app/data")) / "research_misc.json"


def stats(v) -> dict:
    v = np.asarray(v, dtype=float)
    n = len(v)
    if n < 3:
        return {"n": n}
    return {"n": n, "mean": float(v.mean()), "hit": float((v > 0).mean()), "t": float(v.mean() / v.std(ddof=1) * math.sqrt(n))}


def oracle(db) -> dict:
    sig = pd.read_sql(text("SELECT figure, sentiment, ticker, detected_at FROM oracle_signals ORDER BY detected_at"), db.bind)
    if sig.empty:
        return {}
    h = data_headers(db)
    syms = sorted(set(sig.ticker) | {"SPY"})
    closes: dict[str, pd.Series] = {}
    start = (pd.Timestamp(sig.detected_at.min()) - pd.Timedelta(days=7)).date().isoformat()
    end = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=20)).isoformat()
    for i in range(0, len(syms), 100):
        r = httpx.get("https://data.alpaca.markets/v2/stocks/bars", headers=h, timeout=30, params={
            "symbols": ",".join(to_alpaca(s) for s in syms[i:i + 100]), "timeframe": "1Day", "feed": "sip",
            "adjustment": "all", "start": start, "end": end, "limit": 10000})
        for s, rows in ((r.json() or {}).get("bars") or {}).items():
            f = pd.DataFrame(rows)
            f.index = pd.to_datetime(f.t, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
            closes[from_alpaca(s)] = f.c.astype(float)
    spy = closes["SPY"]
    rows = []
    for x in sig.itertuples():
        c = closes.get(x.ticker)
        if c is None:
            continue
        t = pd.Timestamp(x.detected_at).tz_convert("America/New_York")
        d0 = t.tz_localize(None).normalize() + (pd.Timedelta(0) if t.hour < 16 else pd.Timedelta(days=1))
        after = c[c.index >= d0]
        if len(after) < 2 or after.index[0] not in spy.index:
            continue
        sgn = 1 if x.sentiment == "bullish" else -1
        for hold in (1, 5):
            if len(after) > hold and after.index[hold] in spy.index:
                r = after.iloc[hold] / after.iloc[0] - 1
                m = spy.loc[after.index[hold]] / spy.loc[after.index[0]] - 1
                rows.append({"figure": x.figure, "hold": hold, "ret": sgn * r, "excess": sgn * (r - m)})
    t = pd.DataFrame(rows)
    return {"since": str(pd.Timestamp(sig.detected_at.min()).date()), "signals": int(len(sig)),
            "h1": stats(t[t.hold == 1].excess), "h5": stats(t[t.hold == 5].excess),
            "by_figure": {f: stats(g[g.hold == 1].excess) for f, g in t.groupby("figure") if (g.hold == 1).sum() >= 5}}


def ml_filter(db) -> dict:
    pm = pd.read_sql(text("SELECT ticker, earnings_date, prob_move FROM predictions WHERE is_out_of_sample AND prob_move IS NOT NULL"), db.bind)
    pm["earnings_date"] = pd.to_datetime(pm.earnings_date)
    df = _frame(db).copy()
    df["earnings_date"] = pd.to_datetime(df.earnings_date)
    df = df.merge(pm, on=["ticker", "earnings_date"], how="inner")
    df["yr"] = df.earnings_date.dt.year
    cuts = {}
    for y in sorted(df.yr.unique()):
        past = df[df.yr < y].prob_move
        ref = past if len(past) > 2000 else df[df.yr == y].prob_move
        cuts[y] = (ref.quantile(1 / 3), ref.quantile(2 / 3))
    df["pq"] = [("low" if p < cuts[y][0] else "mid" if p < cuts[y][1] else "high") for p, y in zip(df.prob_move, df.yr)]
    base = df[np.isfinite(df.close_t20)].groupby(["yr", "pq"]).close_t20.mean()
    d = df[np.isfinite(df.close_t20) & (df.gap_x > 2)].copy()
    d["excess"] = d.close_t20 - base.reindex(list(zip(d.yr, d.pq))).values - COST
    out = {"since": str(df.earnings_date.min().date())}
    for q in ("low", "mid", "high"):
        g = d[d.pq == q]
        out[q] = {"raw": stats(g.close_t20 - COST), "excess": stats(g.excess),
                  "base": float(base.xs(q, level="pq").mean())}
    return out


def main() -> None:
    with SessionLocal() as db:
        body = {"generated_at": datetime.now(timezone.utc).isoformat(), "oracle": oracle(db), "ml_filter": ml_filter(db)}
    OUT.write_text(json.dumps(body))
    print(json.dumps(body, indent=1)[:3000])
    print("MISC_DONE", OUT)


if __name__ == "__main__":
    main()
