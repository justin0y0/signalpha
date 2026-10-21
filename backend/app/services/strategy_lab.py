"""The strategies Autopilot can run, each with its backtest and its live record.

A strategy is one direction rule (direction_service.RULES) traded as a *sleeve*: the
money a holder gives it is split into `slots` equal positions, a new signal takes a free
slot (biggest gap first when several fire together) and is skipped when none is free.
That is exactly how autotrade_service sizes orders, so the backtest below is the
account the bot would have run, not a sum of independent $10k bets.

Backtest — every report on record since 2008 (outcomes + earnings_surprises, the same
frame direction_service.backtest uses). Entry and exit are the official open/close of
the sessions the rule names; 10 bp round trip; position size = sleeve equity / slots at
entry, compounding. The stored history holds the entry and the exit price of each trade
but not the path between them, so equity is booked on exit days: a 20-session hold
shows its result the day it closes, and drawdowns inside a hold are not visible. Also
reported: the same run at 30 bp (what a bad opening fill costs) and SPY over the span.

Live record — every call in direction_calls since the rule went live, run through the
same sleeve, marked on 30-minute bars from the broker's market-data feed between entry
and exit (entry and exit at the official prices direction_service.book reads). Candles
are one per session: first mark, highest, lowest, last.
"""
from __future__ import annotations

import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.services.direction_service import COST, RULES

NY = ZoneInfo("America/New_York")
ORDER = ["follow_gap", "fade_spike", "buy_flush", "fade_miss"]
SLOTS = {"follow_gap": 10, "fade_spike": 5, "buy_flush": 5, "fade_miss": 5}
ALLOC = {"follow_gap": 40.0, "fade_spike": 20.0, "buy_flush": 20.0, "fade_miss": 20.0}
STRESS_COST = 0.003

_cache: dict[Any, tuple[float, Any]] = {}


def _cached(key, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


# ───────────────────────────── candles ─────────────────────────────

def candles(points: list[tuple[str, float]], period: str = "D") -> list[dict[str, Any]]:
    """(timestamp-ish string, value) -> one candle per period: first, max, min, last.

    Each candle opens where the previous one closed, so gaps between periods show as
    bodies rather than disappearing."""
    if not points:
        return []
    def local(t):  # a bare date is already New York's; an instant is converted to it
        ts = pd.Timestamp(t)
        return ts if ts.tzinfo is None else ts.tz_convert(NY).tz_localize(None)
    s = pd.Series([v for _, v in points], index=pd.DatetimeIndex([local(t) for t, _ in points]))
    key = s.index.to_period("M" if period == "M" else "D")
    out, prev = [], None
    for k, g in s.groupby(key, sort=True):
        o = float(prev if prev is not None else g.iloc[0])
        c = float(g.iloc[-1])
        out.append({"t": str(k), "o": round(o, 4), "h": round(max(o, float(g.max())), 4),
                    "l": round(min(o, float(g.min())), 4), "c": round(c, 4)})
        prev = c
    return out


# ───────────────────────────── backtest ─────────────────────────────

TRIGGER = {"follow_gap": lambda gx, s: gx > 2, "fade_spike": lambda gx, s: gx > 3,
           "buy_flush": lambda gx, s: gx < -2, "fade_miss": lambda gx, s: (gx > 1) & (s < 0)}


def entry_days(d: pd.DataFrame) -> pd.Series:
    """The reaction session: the stored reaction date, else the report day (BMO/DMH) or the next."""
    ed = pd.to_datetime(d.earnings_date)
    react = pd.to_datetime(d.reaction_date) if "reaction_date" in d else pd.Series(pd.NaT, index=d.index)
    rt = d.report_time.fillna("AMC")
    amc = rt.ne("BMO") & rt.ne("DMH")
    fallback = pd.Series([e + pd.offsets.BDay(1) if a else e for e, a in zip(ed, amc)], index=d.index)
    return react.fillna(fallback).dt.normalize()


def _trades(db: Session, key: str) -> pd.DataFrame:
    from backend.app.services.playbook_service import _frame

    r = RULES[key]
    df = _frame(db)
    d = df[np.isfinite(df[r["leg"]]) & df.tier.isin(r["tiers"])].copy()
    d = d[TRIGGER[key](d.gap_x, d.surprise).fillna(False)].copy()
    d["entry_day"] = entry_days(d)
    d["exit_day"] = d.entry_day.apply(lambda x: x + pd.offsets.BDay(r["hold"])) if r["hold"] else d.entry_day
    sign = 1.0 if r["side"] == "LONG" else -1.0
    d["gross"] = sign * d[r["leg"]]
    return d.sort_values(["entry_day"])[["ticker", "entry_day", "exit_day", "gap_x", "gross"]]


def _simulate(t: pd.DataFrame, slots: int, entry: str, cost: float) -> tuple[pd.Series, pd.DataFrame]:
    """Sleeve equity (1.0 = start) on every entry/exit day, and the trades it took."""
    by_entry = {d: g.reindex(g.gap_x.abs().sort_values(ascending=False).index) for d, g in t.groupby("entry_day")}
    days = sorted(set(t.entry_day) | set(t.exit_day))
    eq, open_pos, taken, series = 1.0, [], [], {}

    def enter(day):
        g = by_entry.get(day)
        if g is None:
            return
        free = slots - len(open_pos)
        for row in g.head(max(free, 0)).itertuples():
            open_pos.append((row.exit_day, eq / slots, row.gross - cost))
            taken.append((row.ticker, row.entry_day, row.exit_day, row.gross - cost, row.gap_x))

    for day in days:
        if entry == "open":
            enter(day)
        keep = []
        for p in open_pos:
            if p[0] <= day:
                eq += p[1] * p[2]
            else:
                keep.append(p)
        open_pos[:] = keep
        if entry == "close":
            enter(day)
        series[day] = eq
    s = pd.Series(series).sort_index()
    tk = pd.DataFrame(taken, columns=["ticker", "entry_day", "exit_day", "ret", "gap_x"])
    return s, tk


def _spy_monthly() -> pd.Series:
    def load():
        import yfinance as yf

        raw = yf.download("SPY", start="2007-12-01", auto_adjust=True, progress=False)
        c = raw["Close"]
        if isinstance(c, pd.DataFrame):
            c = c.iloc[:, 0]
        c.index = pd.to_datetime(c.index).tz_localize(None)
        return c.resample("ME").last().dropna()
    try:
        return _cached("spy", 12 * 3600, load)
    except Exception:  # noqa: BLE001 - the benchmark is a nice-to-have
        return pd.Series(dtype=float)


def _stats(s: pd.Series, tk: pd.DataFrame) -> dict[str, Any]:
    if len(s) < 2:
        return {}
    years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
    peak = s.cummax()
    dd = float((s / peak - 1).min())
    m = s.resample("ME").last().ffill()
    mret = m.pct_change().dropna()
    yr = s.resample("YE").last().ffill()
    yret = yr.pct_change()
    yret.iloc[0] = yr.iloc[0] - 1
    hold = s[s.index >= "2019-01-01"]
    base_h = s[s.index < "2019-01-01"]
    h0 = float(base_h.iloc[-1]) if len(base_h) else 1.0
    h_years = max((hold.index[-1] - hold.index[0]).days / 365.25, 1e-9) if len(hold) > 1 else None
    return {
        "total": float(s.iloc[-1] - 1),
        "cagr": float(s.iloc[-1] ** (1 / years) - 1),
        "max_dd": dd,
        "sharpe": float(mret.mean() / mret.std() * math.sqrt(12)) if len(mret) > 2 and mret.std() > 0 else None,
        "months_up": float((mret > 0).mean()) if len(mret) else None,
        "years": [{"y": int(i.year), "ret": float(v)} for i, v in yret.items()],
        "years_up": int((yret > 0).sum()), "years_total": int(len(yret)),
        "holdout_cagr": float((hold.iloc[-1] / h0) ** (1 / h_years) - 1) if h_years else None,
        "trades": int(len(tk)), "hit": float((tk.ret > 0).mean()) if len(tk) else None,
        "avg": float(tk.ret.mean()) if len(tk) else None,
        "span": [str(s.index[0].date()), str(s.index[-1].date())],
    }


def backtest(db: Session, key: str, slots: int | None = None) -> dict[str, Any]:
    slots = int(min(max(slots or SLOTS[key], 1), 30))

    def run():
        r = RULES[key]
        t = _trades(db, key)
        s, tk = _simulate(t, slots, r["entry"], COST)
        s2, _ = _simulate(t, slots, r["entry"], STRESS_COST)
        st = _stats(s, tk)
        st["signals"] = int(len(t))
        st["stress_cagr"] = _stats(s2, tk).get("cagr")
        pts = [(str((s.index[0] - pd.Timedelta(days=1)).date()), 0.0)] + [(str(d.date()), round((v - 1) * 100, 3)) for d, v in s.items()]
        k = candles(pts, "M")
        spy = _spy_monthly()
        bench = []
        if len(spy) and len(s):
            sp = spy[(spy.index >= s.index[0] - pd.offsets.MonthEnd(1)) & (spy.index <= s.index[-1] + pd.offsets.MonthEnd(1))]
            if len(sp):
                base = float(sp.iloc[0])
                bench = [{"t": str(i.to_period("M")), "v": round((float(v) / base - 1) * 100, 3)} for i, v in sp.items()]
                st["spy_cagr"] = float((float(sp.iloc[-1]) / base) ** (1 / max((sp.index[-1] - sp.index[0]).days / 365.25, 1e-9)) - 1)
        recent = tk.sort_values("exit_day").tail(12)
        st["recent"] = [{"ticker": x.ticker, "in": str(x.entry_day.date()), "out": str(x.exit_day.date()),
                         "ret": float(x.ret), "gap_x": float(x.gap_x)} for x in recent.itertuples()][::-1]
        return {"slots": slots, "cost": COST, "stress_cost": STRESS_COST, "stats": st, "candles": k, "bench": bench,
                "replay": replay(key, slots)}

    return _cached(("bt", key, slots, _replay_mtime()), 6 * 3600, run)


def _replay_mtime() -> float:
    from pathlib import Path

    path = Path(os.getenv("DATA_DIR", "/app/data")) / "strategy_replay.json"
    return path.stat().st_mtime if path.exists() else 0.0


def _replay_file() -> dict[str, Any] | None:
    """data_pipeline/replay_open_fills.py output: the open-entry rules on SIP tape at the 9:31 fill."""
    import json
    from pathlib import Path

    path = Path(os.getenv("DATA_DIR", "/app/data")) / "strategy_replay.json"
    if not path.exists():
        return None
    return _cached(("replay-file", path.stat().st_mtime), 24 * 3600, lambda: json.loads(path.read_text()))


def replay(key: str, slots: int) -> dict[str, Any] | None:
    """The sleeve again, on the trades the SIP open triggers, entered at the 9:31 fill."""
    body = _replay_file()
    rule = (body or {}).get("rules", {}).get(key)
    if not rule:
        return None
    t = pd.DataFrame([x for x in rule["trades"] if x["sip"] and x["ret_fill"] is not None])
    out: dict[str, Any] = {"since": body["since"], "generated_at": body["generated_at"], "summary": rule["summary"],
                           "stats": None, "candles": []}
    if t.empty:
        return out
    t["entry_day"] = pd.to_datetime(t.entry_day)
    t["exit_day"] = pd.to_datetime(t.exit_day)
    t["gap_x"] = t.gap_x_sip
    t["gross"] = t.ret_fill + COST  # _simulate takes the cost off again
    s, tk = _simulate(t, slots, RULES[key]["entry"], COST)
    s2, _ = _simulate(t, slots, RULES[key]["entry"], STRESS_COST)
    out["stats"] = {**_stats(s, tk), "signals": int(len(t)), "stress_cagr": _stats(s2, tk).get("cagr")}
    out["candles"] = candles([(str((s.index[0] - pd.Timedelta(days=1)).date()), 0.0)]
                             + [(str(d.date()), round((v - 1) * 100, 3)) for d, v in s.items()], "M")
    spy = _spy_monthly()
    if len(spy):
        sp = spy[(spy.index >= s.index[0] - pd.offsets.MonthEnd(1)) & (spy.index <= s.index[-1] + pd.offsets.MonthEnd(1))]
        if len(sp) > 1:
            base = float(sp.iloc[0])
            out["bench"] = [{"t": str(i.to_period("M")), "v": round((float(v) / base - 1) * 100, 3)} for i, v in sp.items()]
            out["stats"]["spy_cagr"] = float((float(sp.iloc[-1]) / base) ** (1 / max((sp.index[-1] - sp.index[0]).days / 365.25, 1e-9)) - 1)
    return out


# ───────────────────────────── market data ─────────────────────────────

def to_alpaca(ticker: str) -> str:
    """Share classes: Yahoo writes BRK-B, Alpaca BRK.B."""
    return ticker.replace("-", ".")


def from_alpaca(symbol: str) -> str:
    return symbol.replace(".", "-")


def data_headers(db: Session | None = None) -> dict[str, str] | None:
    """Market-data credentials: ALPACA_DATA_KEY_ID/SECRET, else the house account's keys."""
    k, s = os.getenv("ALPACA_DATA_KEY_ID", "").strip(), os.getenv("ALPACA_DATA_SECRET", "").strip()
    if k and s:
        return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s}
    if db is not None:
        try:
            from backend.app.services.autotrade_service import _account_headers

            return _account_headers(db)
        except Exception:  # noqa: BLE001
            return None
    return None


def snapshots(symbols: list[str], db: Session | None = None) -> dict[str, dict]:
    h = data_headers(db)
    if not h or not symbols:
        return {}
    out: dict[str, dict] = {}
    for i in range(0, len(symbols), 100):
        try:
            r = httpx.get("https://data.alpaca.markets/v2/stocks/snapshots", headers=h, timeout=15,
                          params={"symbols": ",".join(to_alpaca(x) for x in symbols[i:i + 100]), "feed": "iex"})
            if r.status_code == 200:
                out.update({from_alpaca(k): v for k, v in (r.json() or {}).items()})
        except Exception:  # noqa: BLE001
            pass
    return out


def opens_today(symbols: list[str], db: Session | None = None) -> dict[str, float]:
    """Today's first print per ticker from the IEX feed, only if it is from today's session."""
    today = datetime.now(timezone.utc).astimezone(NY).date()
    out = {}
    for sym, snap in snapshots(symbols, db).items():
        bar = (snap or {}).get("dailyBar") or {}
        try:
            when = datetime.fromisoformat(bar["t"].replace("Z", "+00:00")).astimezone(NY).date()
        except Exception:  # noqa: BLE001
            continue
        if when == today and bar.get("o"):
            out[sym] = float(bar["o"])
    return out


def intraday(symbols: list[str], start: date, db: Session | None = None) -> dict[str, pd.DataFrame]:
    """30-minute bars, regular session only, per ticker (IEX feed)."""
    h = data_headers(db)
    if not h or not symbols:
        return {}

    def load():
        out: dict[str, list] = {}
        token = None
        for _ in range(40):
            params = {"symbols": ",".join(to_alpaca(x) for x in sorted(symbols)), "timeframe": "30Min", "feed": "iex", "limit": 10000,
                      "start": datetime.combine(start, datetime.min.time(), tzinfo=NY).isoformat()}
            if token:
                params["page_token"] = token
            r = httpx.get("https://data.alpaca.markets/v2/stocks/bars", headers=h, params=params, timeout=20)
            if r.status_code != 200:
                break
            body = r.json()
            for sym, rows in (body.get("bars") or {}).items():
                out.setdefault(from_alpaca(sym), []).extend(rows)
            token = body.get("next_page_token")
            if not token:
                break
        frames = {}
        for sym, rows in out.items():
            f = pd.DataFrame(rows)
            f.index = pd.to_datetime(f.t, utc=True).dt.tz_convert(NY)
            mins = f.index.hour * 60 + f.index.minute
            frames[sym] = f[(mins >= 570) & (mins < 960)][["o", "c"]]
        return frames
    return _cached(("bars", tuple(sorted(symbols)), start), 300, load)


# ───────────────────────────── live record ─────────────────────────────

def live_record(db: Session, key: str, slots: int | None = None) -> dict[str, Any]:
    """The rule's calls since it went live, run through the sleeve and marked on 30-min bars."""
    from backend.app.services.direction_service import direction

    slots = int(min(max(slots or SLOTS[key], 1), 30))
    r = RULES[key]
    calls = [c for c in direction(db)["book"]["calls"] if c["rule"] == key and c["status"] != "pending"
             and c.get("entry_price")]
    body: dict[str, Any] = {"live_from": str(r["live_from"]), "slots": slots, "calls": [], "candles": [],
                            "stats": {"n": 0, "closed": 0, "open": 0}}
    if not calls:
        return body

    def run():
        sign = 1 if r["side"] == "LONG" else -1
        calls.sort(key=lambda c: (c["session"], -abs(c.get("gap_x") or 0)))
        start = date.fromisoformat(calls[0]["session"])
        bars = intraday(sorted({c["ticker"] for c in calls}), start - timedelta(days=1), db)
        # Each call: when it starts counting, when it stops, entry/exit price.
        legs = []
        for c in calls:
            s = pd.Timestamp(c["session"]).tz_localize(NY)
            t_in = s + (pd.Timedelta(hours=9, minutes=30) if r["entry"] == "open" else pd.Timedelta(hours=16))
            t_out = None
            if c["status"] == "closed":
                t_out = pd.Timestamp(c["mark_on"]).tz_localize(NY) + pd.Timedelta(hours=16)
            legs.append({**c, "t_in": t_in, "t_out": t_out})
        # Bars are labelled by their start; a mark belongs to the moment the bar closes.
        ends = {sym: f.set_axis(f.index + pd.Timedelta(minutes=30)) for sym, f in bars.items()}
        grid = sorted({ts for f in ends.values() for ts in f.index} | {l["t_in"] for l in legs}
                      | {l["t_out"] for l in legs if l["t_out"] is not None})
        first_in = min(l["t_in"] for l in legs)
        grid = [g for g in grid if g >= first_in]
        eq, held, waiting, marks, taken = 1.0, [], list(legs), [], []
        for ts in grid:
            while waiting and waiting[0]["t_in"] <= ts:  # entries, in call order (biggest gap first)
                l = waiting.pop(0)
                if len(held) < slots:
                    held.append({"leg": l, "notional": eq / slots})
                    taken.append(l)
            for h in list(held):  # exits, at the official close
                l = h["leg"]
                if l["t_out"] is not None and l["t_out"] <= ts:
                    eq += h["notional"] * (sign * (l["mark"] / l["entry_price"] - 1) - COST)
                    held.remove(h)
            val = eq
            for h in held:
                l = h["leg"]
                px = l["entry_price"]
                f = ends.get(l["ticker"])
                if f is not None:
                    upto = f[(f.index <= ts) & (f.index > l["t_in"])]
                    if len(upto):
                        px = float(upto.c.iloc[-1])
                    elif ts >= grid[-1] and l["status"] == "open":
                        px = l["mark"]
                val += h["notional"] * sign * (px / l["entry_price"] - 1)
            marks.append((ts.isoformat(), round((val - 1) * 100, 4)))
        body["candles"] = candles(marks, "D")
        body["calls"] = [{k: c.get(k) for k in ("ticker", "session", "status", "entry_price", "mark", "mark_on", "ret",
                                                "gap_x", "tier", "called_at")} for c in reversed(taken)]
        closed = [c for c in taken if c["status"] == "closed"]
        body["stats"] = {"n": len(taken), "closed": len(closed), "open": len(taken) - len(closed),
                         "right": sum(1 for c in closed if (c.get("ret") or 0) > 0),
                         "ret": marks[-1][1] / 100 if marks else 0.0, "skipped": len(calls) - len(taken)}
        return body
    return _cached(("live", key, slots, len(calls), calls[-1]["session"]), 300, run)


def catalog(db: Session) -> dict[str, Any]:
    """The whole /autopilot/strategies body, cached for two minutes (a cold build is ~30 s:
    ten backtests, live records, research files); the backend warms it at start."""
    return _cached(("catalog",), 120, lambda: _catalog(db))


def _catalog(db: Session) -> dict[str, Any]:
    from backend.app.services.direction_service import backtest as rule_stats

    stats = rule_stats(db)
    out = []
    for key in ORDER:
        r, s = RULES[key], stats.get(key, {})
        out.append({"key": key, "side": r["side"], "entry": r["entry"], "hold": r["hold"], "tiers": list(r["tiers"]),
                    "live_from": str(r["live_from"]), "slots": SLOTS[key], "alloc": ALLOC[key],
                    "signal": {k: s.get(k) for k in ("all", "excess", "discovery", "holdout", "years_positive",
                                                     "years_total", "per_year", "span")},
                    "backtest": backtest(db, key), "live": live_record(db, key)})
    from backend.app.services import strategies as st

    cards = [direction_card(c) for c in out] + st.catalog()
    order = {k: i for i, k in enumerate(st.ORDER)}
    cards.sort(key=lambda c: order.get(c["key"], 99))
    return {"as_of": datetime.now(timezone.utc).isoformat(), "strategies": out, "cards": cards, "research": research()}


def direction_card(c: dict[str, Any]) -> dict[str, Any]:
    """A direction rule in the page's common card shape (services/strategies.card).

    For rules that enter at the open the headline is the replay at the bot's real fill —
    the open itself is out of reach — and the open-price backtest is kept as `alt`."""
    from backend.app.services.strategies import SPECS

    spec = SPECS[c["key"]]
    bt = c["backtest"]
    rp = bt.get("replay") or {}
    real = bool(rp.get("stats") and c["entry"] == "open")
    src = rp["stats"] if real else bt["stats"]
    line = lambda cs: [{"t": x["t"], "v": x["c"]} for x in cs or []]  # noqa: E731
    stats = {"cagr": src.get("cagr"), "spy_cagr": src.get("spy_cagr"), "max_dd": src.get("max_dd"),
             "sharpe": src.get("sharpe"), "years_up": src.get("years_up"), "years_total": src.get("years_total"),
             "years": src.get("years") or [], "span": src.get("span"), "trades": src.get("trades"),
             "signals": src.get("signals"), "hit": src.get("hit"), "avg": src.get("avg"),
             "stress_cagr": src.get("stress_cagr"), "holdout_cagr": bt["stats"].get("holdout_cagr"),
             "excess": (c["signal"].get("excess") or {}).get("mean"), "excess_t": (c["signal"].get("holdout") or {}).get("t"),
             "basis": "replay" if real else "backtest"}
    out = {"key": c["key"], "family": spec["family"], "kind": "direction", "side": c["side"], "entry": c["entry"],
           "hold": c["hold"], "slots": spec["slots"], "alloc": spec["alloc"], "on": spec["on"], "source": spec["source"],
           "desk": spec["desk"], "live_from": c["live_from"], "tiers": c["tiers"],
           "backtest": {"stats": stats, "series": line(rp.get("candles") if real else bt.get("candles")),
                        "bench": (rp.get("bench") if real else bt.get("bench")) or [],
                        "replay_summary": rp.get("summary") if real else None},
           "live": {"n": c["live"]["stats"].get("n"), "closed": c["live"]["stats"].get("closed"),
                    "right": c["live"]["stats"].get("right"), "ret": c["live"]["stats"].get("ret"),
                    "calls": c["live"].get("calls") or [], "candles": c["live"].get("candles") or []}}
    if real:
        out["alt"] = {"basis": "open", "series": line(bt.get("candles")), "bench": bt.get("bench") or [],
                      "cagr": bt["stats"].get("cagr")}
    return out


# ───────────────────────────── the rest of the lab ─────────────────────────────

def _json(name: str) -> dict[str, Any] | None:
    import json
    from pathlib import Path

    path = Path(os.getenv("DATA_DIR", "/app/data")) / name
    if not path.exists():
        return None
    return _cached(("file", name, path.stat().st_mtime), 24 * 3600, lambda: json.loads(path.read_text()))


def research() -> list[dict[str, Any]]:
    """Every other strategy the platform could trade, with the test it was put through and
    the verdict. Only rules that survive reach the catalog above; the rest are shown so a
    paying user can see what was tried and why it is not on offer.

    verdict: 'edge' (tradable), 'weak' (positive but not significant or not beating the
    market), 'none' (no edge or negative), 'pending' (test still running)."""
    import json
    from pathlib import Path

    out: list[dict[str, Any]] = []
    lean = Path(os.getenv("MODEL_DIR", "/app/artifacts")) / "lean_model.json"
    if lean.exists():
        m = json.loads(lean.read_text()).get("metrics", {})
        out.append({"key": "ml_direction", "verdict": "none", "n": m.get("n"), "since": m.get("first_oos_date"),
                    "nums": {"hit": m.get("accuracy"), "majority": m.get("majority"), "ls_mean": m.get("long_short_mean"),
                             "ls_t": m.get("long_short_t")}})
    misc = _json("research_misc.json") or {}
    mf = misc.get("ml_filter") or {}
    if mf:
        hi = mf.get("high", {})
        out.append({"key": "ml_filter", "verdict": "none" if abs((hi.get("excess") or {}).get("t") or 0) < 2 else "edge",
                    "n": (hi.get("raw") or {}).get("n"), "since": mf.get("since"),
                    "nums": {"raw": (hi.get("raw") or {}).get("mean"), "base": hi.get("base"),
                             "excess": (hi.get("excess") or {}).get("mean"), "t": (hi.get("excess") or {}).get("t")}})
    st = _json("research_straddles.json")
    if st:
        s = st["summary"]
        top = {int(k): v for k, v in s["by_decile"].items()}
        best = top.get(10, {})
        t = (best.get("open") or {}).get("t") or 0
        mean = (best.get("open") or {}).get("mean") or 0
        out.append({"key": "ml_straddle", "verdict": "edge" if t >= 2 and mean > 0.05 else "weak" if mean > 0 else "none",
                    "n": s.get("n"), "since": st.get("since"),
                    "nums": {"top_open": mean, "top_t": t, "top_beat": best.get("beat"),
                             "top_implied": best.get("implied"), "top_realised": best.get("realised"),
                             "mid_implied": float(np.median([top[k]["implied"] for k in (4, 5, 6, 7) if k in top])) if top else None,
                             "bottom_open": ((top.get(1) or {}).get("open") or {}).get("mean"),
                             "deciles": {k: (v.get("open") or {}).get("mean") for k, v in sorted(top.items())}}})
    else:
        out.append({"key": "ml_straddle", "verdict": "pending"})
    pl = _json("research_pulse.json")
    for key in ("al_reversion", "gao_1530"):
        if pl and key in pl:
            a = pl[key]["all"]
            out.append({"key": key, "verdict": "edge" if (a.get("t") or 0) >= 2 and (a.get("mean") or 0) > 0 else "none",
                        "n": a.get("n"), "since": pl.get("start"),
                        "nums": {"mean": a.get("mean"), "t": a.get("t"), "hit": a.get("hit"),
                                 "gross": (pl[key].get("gross") or {}).get("mean")},
                        "curve": candles(pl[key].get("curve") or [], "M")})
        else:
            out.append({"key": key, "verdict": "pending"})
    # Published rules that did not survive their own publication (research_etf.py): numbers after it.
    etf = (_json("research_etf.json") or {}).get("rules", {})
    for key, verdict in (("gem", "none"), ("tom", "none"), ("overnight", "none"), ("fomc", "weak")):
        b = etf.get(key)
        if not b:
            continue
        post = b.get("post") or {}
        out.append({"key": f"etf_{key}", "verdict": verdict, "since": b.get("published"), "n": post.get("n_days"),
                    "nums": {"cagr": post.get("cagr"), "spy": post.get("spy_cagr"), "sharpe": post.get("sharpe"),
                             "spy_sharpe": post.get("spy_sharpe"), "dd": post.get("max_dd"),
                             "ev": (b.get("event_ret") or {}).get("post")}})
    # Single-stock and filing rules that did not hold up (research_equity.py, research_filings.py).
    eq = (_json("research_equity.json") or {}).get("rules", {})
    fl = (_json("research_filings.json") or {}).get("rules", {})
    for src, key in ((eq, "rsi2_mega"), (eq, "pre_run_ml"), (eq, "momentum"), (fl, "clone_buffett"),
                     (fl, "clone_ackman"), (fl, "clone_burry")):
        b = src.get(key)
        if not b:
            continue
        ex, ew = b.get("excess") or {}, b.get("excess_ew") or {}
        good = (ew.get("t") or ex.get("t") or 0) >= 2 and (ew.get("mean") if ew else ex.get("mean") or 0) > 0
        out.append({"key": key, "verdict": "weak" if good else "none", "n": ex.get("n"),
                    "since": ((b.get("all") or {}).get("start") or "")[:4],
                    "nums": {"ex": ex.get("mean"), "ex_t": ex.get("t"), "ew": ew.get("mean"), "ew_t": ew.get("t"),
                             "cagr": (b.get("all") or {}).get("cagr"), "spy": (b.get("all") or {}).get("spy_cagr")}})
    orc = misc.get("oracle") or {}
    if orc:
        out.append({"key": "oracle", "verdict": "none", "n": (orc.get("h1") or {}).get("n"), "since": orc.get("since"),
                    "nums": {"h1": (orc.get("h1") or {}).get("mean"), "h1_t": (orc.get("h1") or {}).get("t"),
                             "h5": (orc.get("h5") or {}).get("mean"), "h5_t": (orc.get("h5") or {}).get("t")}})
    return out
