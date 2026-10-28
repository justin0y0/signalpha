"""How fast does the edge of the open-entry rules decay after the bell?

Autopilot finds most opening gaps from the broker feed within seconds, but a stock whose
first print is slow (or that IEX does not quote early) is only found by the Yahoo passes at
9:36 and 9:50, and was then bought at 9:37 or 9:51. The replay (replay_open_fills.py) only
priced fills in the first minutes. This prices the same trades — fade_spike and buy_flush,
signals the SIP open confirms, 2023-07 onwards — entered at the VWAP of the minute starting
at 9:31, 9:35, 9:40, 9:45, 9:50 and 9:55, out at the SIP close, 10 bp round trip.

    python -m data_pipeline.research_entry_decay     # writes $DATA_DIR/research_entry_decay.json
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backend.app.services.direction_service import COST, RULES
from data_pipeline.research_common import alpaca_headers, out_path, tstat
from backend.app.services.strategy_lab import from_alpaca, to_alpaca

NY = ZoneInfo("America/New_York")
MINUTES = ["09:31", "09:35", "09:40", "09:45", "09:50", "09:55"]
SINCE = "2023-07-01"


def main() -> None:
    import httpx
    import time

    rp = json.loads((Path(os.getenv("DATA_DIR", "/app/data")) / "strategy_replay.json").read_text())
    rows = []
    for key in ("fade_spike", "buy_flush"):
        for t in rp["rules"][key]["trades"]:
            if t["sip"] and t["entry_day"] >= SINCE:
                rows.append({"rule": key, "ticker": t["ticker"], "day": t["entry_day"]})
    tr = pd.DataFrame(rows)
    print(f"{len(tr)} trades on {tr.day.nunique()} sessions", flush=True)
    h = alpaca_headers()
    out = []
    for n, (day, g) in enumerate(tr.groupby("day")):
        syms = sorted(set(g.ticker))
        start = datetime.fromisoformat(day).replace(hour=9, minute=30, tzinfo=NY)
        p = {"symbols": ",".join(to_alpaca(s) for s in syms), "timeframe": "1Min", "feed": "sip", "adjustment": "raw",
             "start": start.isoformat(), "end": (start + timedelta(minutes=27)).isoformat(), "limit": 10000}
        body = {}
        for attempt in range(5):
            r = httpx.get("https://data.alpaca.markets/v2/stocks/bars", headers=h, params=p, timeout=40)
            if r.status_code == 429:
                time.sleep(15)
                continue
            body = r.json() if r.status_code == 200 else {}
            break
        time.sleep(0.31)
        mins = {}
        for sym, bl in (body.get("bars") or {}).items():
            f = pd.DataFrame(bl)
            f.index = pd.to_datetime(f.t, utc=True).dt.tz_convert(NY).dt.strftime("%H:%M")
            mins[from_alpaca(sym)] = f
        d0 = datetime.fromisoformat(day).replace(tzinfo=NY)
        dp = {"symbols": ",".join(to_alpaca(s) for s in syms), "timeframe": "1Day", "feed": "sip", "adjustment": "raw",
              "start": d0.isoformat(), "end": (d0 + timedelta(hours=23)).isoformat(), "limit": 1000}
        closes = {}
        for attempt in range(5):
            r = httpx.get("https://data.alpaca.markets/v2/stocks/bars", headers=h, params=dp, timeout=40)
            if r.status_code == 429:
                time.sleep(15)
                continue
            for sym, bl in ((r.json() or {}).get("bars") or {}).items() if r.status_code == 200 else []:
                if bl:
                    closes[from_alpaca(sym)] = float(bl[0]["c"])
            break
        time.sleep(0.31)
        for x in g.itertuples():
            f = mins.get(x.ticker)
            if f is None or x.ticker not in closes:
                continue
            close = closes[x.ticker]
            sign = 1 if RULES[x.rule]["side"] == "LONG" else -1
            rec = {"rule": x.rule, "ticker": x.ticker, "day": day}
            for m in MINUTES:
                b = f[f.index >= m]
                if len(b):
                    px = float(b.iloc[0]["vw"] or b.iloc[0]["c"])
                    rec[m] = sign * (close / px - 1) - COST
            out.append(rec)
        if n % 50 == 0:
            print(f"{n}/{tr.day.nunique()} sessions", flush=True)
    d = pd.DataFrame(out)
    res = {"since": SINCE, "generated_at": datetime.now(timezone.utc).isoformat(), "rules": {}}
    for key, g in d.groupby("rule"):
        res["rules"][key] = {m: tstat(g[m].dropna()) for m in MINUTES if m in g}
        print(key, {m: (round(v.get("mean", 0) * 100, 3), round(v.get("t") or 0, 1), v.get("n")) for m, v in res["rules"][key].items()}, flush=True)
    Path(out_path("research_entry_decay.json")).write_text(json.dumps(res))
    print("DECAY_DONE", flush=True)


if __name__ == "__main__":
    main()
