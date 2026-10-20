"""Replay the open-entry rules on the consolidated tape, at the price Autopilot actually gets.

The rule backtests (direction_service / strategy_lab) use Yahoo's daily open and close.
Two things could make them flatter what the bot earns:

1. A bad opening print in Yahoo's data invents a gap and a reversal from it — exactly the
   shape fade_spike and buy_flush profit from.
2. The bot cannot trade the opening auction: it learns the gap from the first print and
   sends a market order about a minute later, so it gets the 9:31 price, not the open.

For every report since 2016 whose Yahoo gap comes near a rule's threshold (relaxed by a
quarter, so triggers that only the consolidated tape would see are included too), this
pulls the SIP daily bars and the 9:30–9:45 minute bars from Alpaca and records:
  gap_x_sip  the gap on SIP prices          -> does the rule still fire?
  fill       VWAP of the first whole minute after the stock has printed (9:31 at the
             earliest) — the bot's market order
  exit       SIP close of the exit session (actual trading days)
  ret_yahoo / ret_open / ret_fill   the trade at Yahoo's open, the SIP open, the fill
All net of the same 10 bp round trip. Borrow availability is not modelled (the bot skips
names that are not easy to borrow; history of that list is not available).

    python -m data_pipeline.replay_open_fills          # writes $DATA_DIR/strategy_replay.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd

from backend.app.db.session import SessionLocal
from backend.app.services.direction_service import COST, RULES
from backend.app.services.playbook_service import _frame
from backend.app.services.strategy_lab import TRIGGER, data_headers, entry_days, from_alpaca, to_alpaca

NY = ZoneInfo("America/New_York")
SINCE = pd.Timestamp("2016-01-04")
OUT = Path(os.getenv("DATA_DIR", "/app/data")) / "strategy_replay.json"
OPEN_RULES = ["fade_spike", "buy_flush", "fade_miss"]
RELAXED = {"fade_spike": lambda gx, s: gx > 2.25, "buy_flush": lambda gx, s: gx < -1.5,
           "fade_miss": lambda gx, s: (gx > 0.75) & (s < 0)}
H: dict[str, str] = {}


def _get(params: dict) -> dict:
    for attempt in range(6):
        try:
            r = httpx.get("https://data.alpaca.markets/v2/stocks/bars", headers=H, params=params, timeout=30)
        except httpx.HTTPError:
            time.sleep(2 + attempt * 3)
            continue
        if r.status_code == 429:
            time.sleep(15)
            continue
        time.sleep(0.32)  # 200 requests a minute on the free data plan
        if r.status_code == 400 and "invalid symbol" in r.text and "symbols" in params:
            bad = r.text.split("invalid symbol:")[-1].strip().strip('"}').strip()
            rest = [x for x in params["symbols"].split(",") if x != bad]
            print("dropping", bad, flush=True)
            return _get({**params, "symbols": ",".join(rest)}) if rest else {}
        if r.status_code != 200:
            print("bars", r.status_code, r.text[:160], flush=True)
            return {}
        return r.json()
    return {}


def daily(symbols: list[str], end: date) -> dict[str, pd.DataFrame]:
    out: dict[str, list] = {}
    for i in range(0, len(symbols), 100):
        token = None
        while True:
            p = {"symbols": ",".join(to_alpaca(x) for x in symbols[i:i + 100]), "timeframe": "1Day", "feed": "sip", "adjustment": "raw",
                 "start": "2015-12-01", "end": end.isoformat(), "limit": 10000}  # free plan: no SIP from the last 15 min
            if token:
                p["page_token"] = token
            body = _get(p)
            for sym, rows in (body.get("bars") or {}).items():
                out.setdefault(from_alpaca(sym), []).extend(rows)
            token = body.get("next_page_token")
            if not token:
                break
        print(f"daily {min(i + 100, len(symbols))}/{len(symbols)}", flush=True)
    frames = {}
    for sym, rows in out.items():
        f = pd.DataFrame(rows)
        f.index = pd.to_datetime(f.t, utc=True).dt.tz_convert(NY).dt.tz_localize(None).dt.normalize()
        frames[sym] = f[~f.index.duplicated(keep="last")][["o", "c"]].astype(float)
    return frames


def minutes(day: pd.Timestamp, symbols: list[str]) -> dict[str, pd.DataFrame]:
    start = datetime(day.year, day.month, day.day, 9, 30, tzinfo=NY)
    body = _get({"symbols": ",".join(to_alpaca(x) for x in symbols), "timeframe": "1Min", "feed": "sip", "adjustment": "raw",
                 "start": start.isoformat(), "end": (start + timedelta(minutes=15)).isoformat(), "limit": 10000})
    frames = {}
    for sym, rows in (body.get("bars") or {}).items():
        f = pd.DataFrame(rows)
        f.index = pd.to_datetime(f.t, utc=True).dt.tz_convert(NY)
        frames[from_alpaca(sym)] = f
    return frames


def main() -> None:
    global H
    with SessionLocal() as db:
        H = data_headers(db) or {}
        if not H:
            sys.exit("no market-data credentials (ALPACA_DATA_KEY_ID/SECRET or a house connection)")
        df = _frame(db).copy()
    df["entry_day"] = entry_days(df)
    today = pd.Timestamp(datetime.now(NY).date())
    cands = []
    for key in OPEN_RULES:
        r = RULES[key]
        d = df[df.tier.isin(r["tiers"]) & (df.entry_day >= SINCE) & (df.entry_day < today - pd.Timedelta(days=10))]
        d = d[RELAXED[key](d.gap_x, d.surprise).fillna(False)].copy()
        d["rule"] = key
        cands.append(d)
    c = pd.concat(cands)
    syms = sorted(c.ticker.unique())
    print(f"{len(c)} candidate trades, {len(syms)} symbols, {c.entry_day.nunique()} sessions", flush=True)
    bars = daily(syms, (today - pd.Timedelta(days=1)).date())

    rows = []
    for x in c.itertuples():
        f = bars.get(x.ticker)
        if f is None or x.entry_day not in f.index:
            continue
        pos = f.index.get_loc(x.entry_day)
        if pos == 0:
            continue
        r = RULES[x.rule]
        if pos + r["hold"] >= len(f):
            continue
        prev_c, o = float(f.c.iloc[pos - 1]), float(f.o.iloc[pos])
        exit_px, exit_day = float(f.c.iloc[pos + r["hold"]]), f.index[pos + r["hold"]]
        gx_sip = (o / prev_c - 1) / x.band if x.band else np.nan
        rows.append({"rule": x.rule, "ticker": x.ticker, "entry_day": x.entry_day, "exit_day": exit_day,
                     "band": float(x.band), "surprise": None if pd.isna(x.surprise) else float(x.surprise),
                     "gap_x": float(x.gap_x), "gap_x_sip": float(gx_sip), "open": o, "exit": exit_px,
                     "yahoo_fires": bool(TRIGGER[x.rule](x.gap_x, x.surprise if not pd.isna(x.surprise) else np.nan)),
                     "sip_fires": bool(TRIGGER[x.rule](gx_sip, x.surprise if not pd.isna(x.surprise) else np.nan)),
                     "leg": float(getattr(x, r["leg"]))})
    t = pd.DataFrame(rows)
    need = t[t.yahoo_fires | t.sip_fires]
    print(f"{len(t)} with SIP bars; {len(need)} fire on either tape; fetching opening minutes", flush=True)

    fills: dict[tuple[str, pd.Timestamp], tuple[float, str]] = {}
    days = sorted(need.entry_day.unique())
    for i, day in enumerate(days):
        syms_day = sorted(need[need.entry_day == day].ticker.unique())
        for j in range(0, len(syms_day), 100):
            for sym, f in minutes(pd.Timestamp(day), syms_day[j:j + 100]).items():
                if f.empty:
                    continue
                first = f.index[0]
                earliest = max(first + pd.Timedelta(minutes=1), first.replace(hour=9, minute=31, second=0))
                after = f[f.index >= earliest]
                if len(after):
                    b = after.iloc[0]
                    fills[(sym, pd.Timestamp(day))] = (float(b["vw"] or b["c"]), after.index[0].strftime("%H:%M"))
        if i % 100 == 0:
            print(f"minutes {i}/{len(days)}", flush=True)

    out_rules = {}
    for key in OPEN_RULES:
        r = RULES[key]
        sign = 1.0 if r["side"] == "LONG" else -1.0
        d = t[t.rule == key].copy()
        d["fill"] = [fills.get((a, b), (np.nan, ""))[0] for a, b in zip(d.ticker, d.entry_day)]
        d["fill_at"] = [fills.get((a, b), (np.nan, ""))[1] for a, b in zip(d.ticker, d.entry_day)]
        d["ret_yahoo"] = sign * d.leg - COST
        d["ret_open"] = sign * (d.exit / d.open - 1) - COST
        d["ret_fill"] = sign * (d.exit / d.fill - 1) - COST
        y = d[d.yahoo_fires]
        s = d[d.sip_fires & d.fill.notna()]
        both = d[d.yahoo_fires & d.sip_fires & d.fill.notna()]

        def m(x):
            return {"n": int(len(x)), "mean": float(x.mean()) if len(x) else None,
                    "hit": float((x > 0).mean()) if len(x) else None,
                    "t": float(x.mean() / x.std() * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else None}
        out_rules[key] = {
            "summary": {"yahoo": m(y.ret_yahoo), "yahoo_on_sip_open": m(y.ret_open),
                        "agree": float(y.sip_fires.mean()) if len(y) else None,
                        "sip_only": int((d.sip_fires & ~d.yahoo_fires).sum()),
                        "realistic": m(s.ret_fill), "same_trades": {"yahoo": m(both.ret_yahoo), "open": m(both.ret_open),
                                                                    "fill": m(both.ret_fill)},
                        "fill_minute": s.fill_at.value_counts().head(5).to_dict()},
            "trades": [{"ticker": x.ticker, "entry_day": str(x.entry_day.date()), "exit_day": str(x.exit_day.date()),
                        "gap_x": round(x.gap_x, 3), "gap_x_sip": round(x.gap_x_sip, 3), "yahoo": bool(x.yahoo_fires),
                        "sip": bool(x.sip_fires), "ret_yahoo": round(x.ret_yahoo, 5), "ret_open": round(x.ret_open, 5),
                        "ret_fill": None if pd.isna(x.ret_fill) else round(x.ret_fill, 5), "fill_at": x.fill_at}
                       for x in d.itertuples()],
        }
        print(key, json.dumps(out_rules[key]["summary"]), flush=True)
    OUT.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "since": str(SINCE.date()),
                               "cost": COST, "rules": out_rules}))
    print("REPLAY_DONE", OUT, flush=True)


if __name__ == "__main__":
    main()
