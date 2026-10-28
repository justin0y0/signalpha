"""The strategy library: hundreds of rules, one definition each, used for both the backtest
and the live signal — so what is graded is exactly what Autopilot would trade.

A strategy here is a *spec*: a template (a function of price history), its parameters and
the instrument(s). Every template returns, for each session, the weights to hold from
that session's close to the next (decided on information up to and including the close),
so the backtest is close-to-close and the live run decides at 15:35 New York time on the
day's price so far and trades into the close — the same as the market rules in
strategies.py. Cash earns the 13-week T-bill rate. Costs: 2 bp a side on ETFs, 5 bp on
single stocks, charged on every change of weight.

Families
  trend         moving-average filters and crosses, Donchian/Turtle breakouts, 52-week
                highs, MACD, time-series momentum (Moskowitz, Ooi & Pedersen 2012)
  reversion     RSI(2) (Connors), RSI(14), Bollinger bands, internal bar strength, down
                streaks
  seasonal      turn of the month, Halloween / sell in May, pre-holiday, FOMC days
  volatility    volatility targeting, VIX regime
  allocation    60/40, permanent portfolio, all weather, golden butterfly, GTAA (Faber),
                dual momentum (Antonacci), risk parity, sector momentum
  earnings      single stocks around their own reports, from the platform's outcomes data:
                run-up held through the report, report avoidance, gap follow-through

Specs are generated, not hand-listed: templates x instruments, each with the parameters
its source published (no parameter was tuned here). The grading in
data_pipeline/run_library.py corrects for how many were tried.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

INDEXES = ["SPY", "QQQ", "IWM", "DIA"]
STOCKS = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX", "AVGO",
          "JPM", "XOM", "COST", "WMT", "UNH", "LLY", "BRK-B", "MU", "PLTR", "COIN"]
SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
CROSS = ["EFA", "EEM", "AGG", "TLT", "IEF", "SHY", "GLD", "DBC", "VNQ", "IJS", "VTI", "BIL", "SCZ"]


@dataclass
class Spec:
    id: str
    family: str
    template: str
    params: dict[str, Any]
    assets: list[str]
    bench: str
    name_key: str
    source: str
    published: int | None = None
    executable: bool = True
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ───────────────────────── indicators ─────────────────────────

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(c: pd.Series, n: int) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def hold_until(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """1 from an entry day until (and including) the day an exit condition is first true."""
    pos = np.zeros(len(entry))
    on = False
    e, x = entry.fillna(False).to_numpy(), exit_.fillna(False).to_numpy()
    for i in range(len(pos)):
        if not on and e[i]:
            on = True
        elif on and x[i]:
            on = False
        pos[i] = 1.0 if on else 0.0
    return pd.Series(pos, index=entry.index)


# ───────────────────────── single-asset templates ─────────────────────────
# Each takes the asset's OHLC frame (columns o, h, l, c) and params; returns weight in [0, 1].

def t_buy_hold(f, p):
    return pd.Series(1.0, index=f.index)


def t_sma_trend(f, p):
    return (f.c > sma(f.c, p["n"])).astype(float).where(sma(f.c, p["n"]).notna(), 0.0)


def t_sma_monthly(f, p):
    """Faber: month-end close above its n-month average; held all of the next month."""
    is_me = f.c.index.isin(f.c.groupby([f.index.year, f.index.month]).tail(1).index)
    monthly = f.c[is_me]
    sig = (monthly > monthly.rolling(p["n"]).mean()).astype(float)
    return sig.reindex(f.index).ffill().fillna(0.0)


def t_sma_cross(f, p):
    a, b = sma(f.c, p["fast"]), sma(f.c, p["slow"])
    return (a > b).astype(float).where(b.notna(), 0.0)


def t_donchian(f, p):
    hi = f.h.rolling(p["entry"]).max().shift(1)
    lo = f.l.rolling(p["exit"]).min().shift(1)
    return hold_until(f.c > hi, f.c < lo)


def t_high52(f, p):
    hi = f.c.rolling(252).max()
    return hold_until(f.c >= hi * 0.999, f.c < sma(f.c, p["exit"]))


def t_macd(f, p):
    m = f.c.ewm(span=12, adjust=False).mean() - f.c.ewm(span=26, adjust=False).mean()
    return (m > m.ewm(span=9, adjust=False).mean()).astype(float)


def t_tsmom(f, p):
    r = f.c / f.c.shift(p["n"]) - 1
    return (r > 0).astype(float).where(r.notna(), 0.0)


def t_rsi2(f, p):
    """Connors: RSI(2) below `lo` above the 200-day average; out on a close above the 5-day average."""
    r, s200, s5 = rsi(f.c, 2), sma(f.c, 200), sma(f.c, 5)
    return hold_until((r < p["lo"]) & (f.c > s200), f.c > s5)


def t_rsi14(f, p):
    r = rsi(f.c, 14)
    return hold_until(r < 30, r > 70)


def t_boll_revert(f, p):
    m, sd = sma(f.c, 20), f.c.rolling(20).std()
    return hold_until(f.c < m - 2 * sd, f.c > m)


def t_boll_break(f, p):
    m, sd = sma(f.c, 20), f.c.rolling(20).std()
    return hold_until(f.c > m + 2 * sd, f.c < m)


def t_ibs(f, p):
    """Internal bar strength: (close - low) / (high - low) under 0.2 -> hold one session."""
    ibs = (f.c - f.l) / (f.h - f.l).replace(0, np.nan)
    return (ibs < p["lo"]).astype(float)


def t_down_streak(f, p):
    down = (f.c < f.c.shift(1)).astype(int)
    streak = down.groupby((down == 0).cumsum()).cumsum()
    return hold_until(streak >= p["n"], f.c > f.c.shift(1))


def t_vol_target(f, p):
    vol = f.c.pct_change().rolling(20).std() * math.sqrt(252)
    return (p["target"] / vol).clip(upper=1.0).fillna(0.0)


def t_turn_of_month(f, p):
    idx = f.index.to_series()
    pos_in = idx.groupby([idx.dt.year, idx.dt.month]).cumcount()
    from_end = idx.groupby([idx.dt.year, idx.dt.month]).cumcount(ascending=False)
    # weight decided at a close applies to the next session: hold from the close two
    # sessions before month-end through the third session of the new month
    return ((from_end == 1) | (from_end == 0) | (pos_in <= 1)).astype(float)


def t_halloween(f, p):
    m = f.index.month
    return pd.Series(((m >= 11) | (m <= 4)).astype(float), index=f.index)


def t_fomc(f, p):
    days = set(p.get("dates") or [])
    nxt = pd.Series(f.index, index=f.index).shift(-1)
    return pd.Series([1.0 if (n in days) else 0.0 for n in nxt], index=f.index)


def t_pre_holiday(f, p):
    """Hold into the session before a market holiday (the gap to the next session is > 1
    weekday): position taken at the close two sessions before the holiday."""
    idx = pd.Series(f.index, index=f.index)
    nxt = idx.shift(-1)
    gap = (nxt - idx).dt.days
    wk = idx.dt.weekday
    pre_holiday = (gap > 1) & ~((wk == 4) & (gap == 3))
    return pre_holiday.shift(-1, fill_value=False).astype(float)


def t_vix_regime(f, p, vix: pd.Series | None = None):
    if vix is None:
        return pd.Series(0.0, index=f.index)
    v = vix.reindex(f.index).ffill()
    return (v < sma(v, 50)).astype(float).where(sma(v, 50).notna(), 0.0)


SINGLE: dict[str, Callable] = {
    "buy_hold": t_buy_hold, "sma_trend": t_sma_trend, "sma_monthly": t_sma_monthly, "sma_cross": t_sma_cross,
    "donchian": t_donchian, "high52": t_high52, "macd": t_macd, "tsmom": t_tsmom, "rsi2": t_rsi2, "rsi14": t_rsi14,
    "boll_revert": t_boll_revert, "boll_break": t_boll_break, "ibs": t_ibs, "down_streak": t_down_streak,
    "vol_target": t_vol_target, "turn_of_month": t_turn_of_month, "halloween": t_halloween, "fomc": t_fomc,
    "pre_holiday": t_pre_holiday, "vix_regime": t_vix_regime,
}


# ───────────────────────── multi-asset templates ─────────────────────────
# Each takes {ticker: OHLC frame} and params; returns a weights DataFrame (columns = assets).

def _month_ends(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(idx, index=idx)
    return pd.DatetimeIndex(s.groupby([idx.year, idx.month]).tail(1).values)


def m_static(C: pd.DataFrame, p):
    """Fixed weights, rebalanced at each month-end (weights drift in between are ignored)."""
    w = pd.DataFrame(0.0, index=C.index, columns=C.columns)
    for k, v in p["w"].items():
        w[k] = v
    return w.where(C.notna(), 0.0)


def m_gtaa(C: pd.DataFrame, p):
    """Faber GTAA: each asset 1/n, held only while above its 10-month average."""
    me = _month_ends(C.index)
    w = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
    m = C.loc[me]
    ok = m > m.rolling(10).mean()
    w.loc[me] = ok.astype(float) / len(C.columns)
    return w.ffill().fillna(0.0)


def m_dual_momentum(C: pd.DataFrame, p):
    """Antonacci GEM: SPY vs EFA by 12-month return, if SPY beats T-bills (BIL); else AGG."""
    me = _month_ends(C.index)
    w = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
    for d in me:
        i = C.index.get_loc(d)
        if i < 252:
            continue
        r = C.iloc[i] / C.iloc[i - 252] - 1
        if pd.isna(r.get("SPY")) or pd.isna(r.get("EFA")) or pd.isna(r.get("BIL")):
            continue
        row = pd.Series(0.0, index=C.columns)
        if r["SPY"] > r["BIL"]:
            row["SPY" if r["SPY"] >= r["EFA"] else "EFA"] = 1.0
        else:
            row["AGG"] = 1.0
        w.loc[d] = row
    return w.ffill().fillna(0.0)


def m_risk_parity(C: pd.DataFrame, p):
    """Inverse 60-day volatility weights, monthly."""
    me = _month_ends(C.index)
    vol = C.pct_change().rolling(60).std()
    w = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
    inv = (1 / vol.loc[me]).replace([np.inf], np.nan)
    w.loc[me] = inv.div(inv.sum(axis=1), axis=0)
    return w.ffill().fillna(0.0)


def m_top_momentum(C: pd.DataFrame, p):
    """Top k of the assets by n-day return, equal weight, monthly."""
    me = _month_ends(C.index)
    w = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
    for d in me:
        i = C.index.get_loc(d)
        if i < p["n"]:
            continue
        r = (C.iloc[i] / C.iloc[i - p["n"]] - 1).dropna()
        if len(r) < p["k"]:
            continue
        row = pd.Series(0.0, index=C.columns)
        row[r.sort_values(ascending=False).index[:p["k"]]] = 1 / p["k"]
        w.loc[d] = row
    return w.ffill().fillna(0.0)


def m_adm(C: pd.DataFrame, p):
    """Accelerating dual momentum: SPY vs SCZ by the sum of 1/3/6-month returns; TLT if both negative."""
    me = _month_ends(C.index)
    w = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
    for d in me:
        i = C.index.get_loc(d)
        if i < 126:
            continue
        sc = {}
        for a in ("SPY", "SCZ"):
            s = C[a]
            sc[a] = sum(s.iloc[i] / s.iloc[i - n] - 1 for n in (21, 63, 126))
        if any(pd.isna(v) for v in sc.values()):
            continue
        row = pd.Series(0.0, index=C.columns)
        best = max(sc, key=sc.get)
        row[best if sc[best] > 0 else "TLT"] = 1.0
        w.loc[d] = row
    return w.ffill().fillna(0.0)


MULTI: dict[str, Callable] = {"static": m_static, "gtaa": m_gtaa, "dual_momentum": m_dual_momentum,
                              "risk_parity": m_risk_parity, "top_momentum": m_top_momentum, "adm": m_adm}


# ───────────────────────── earnings templates (single stock) ─────────────────────────
# Take the OHLC frame and the stock's reports (reaction session, gap, usual move).

def e_runup(f, ev, p):
    """Buy at the close five sessions before the last pre-report close, sell at the reaction close."""
    w = pd.Series(0.0, index=f.index)
    pos = {d: i for i, d in enumerate(f.index)}
    for r in ev.itertuples():
        i = pos.get(r.reaction)
        if i is None or i < 6:
            continue
        w.iloc[i - 6:i] = 1.0  # held from the close of i-6 through the close of i
    return w


def e_avoid(f, ev, p):
    """Hold the stock, except across its reports: out at the last pre-report close, back in at the reaction close."""
    w = pd.Series(1.0, index=f.index)
    pos = {d: i for i, d in enumerate(f.index)}
    for r in ev.itertuples():
        i = pos.get(r.reaction)
        if i is not None and i >= 1:
            w.iloc[i - 1] = 0.0
    return w


def e_gap_follow(f, ev, p):
    """Gapped up more than k x its usual move on the report: buy the reaction close, hold n sessions."""
    w = pd.Series(0.0, index=f.index)
    pos = {d: i for i, d in enumerate(f.index)}
    for r in ev.itertuples():
        i = pos.get(r.reaction)
        if i is None or not (r.band and r.gap / r.band > p["k"]):
            continue
        w.iloc[i:i + p["hold"]] = 1.0
    return w


def e_gap_fade_down(f, ev, p):
    """Gapped down more than k x its usual move: buy the reaction close, hold n sessions (overreaction)."""
    w = pd.Series(0.0, index=f.index)
    pos = {d: i for i, d in enumerate(f.index)}
    for r in ev.itertuples():
        i = pos.get(r.reaction)
        if i is None or not (r.band and r.gap / r.band < -p["k"]):
            continue
        w.iloc[i:i + p["hold"]] = 1.0
    return w


def e_double_beat(f, ev, p):
    """Beat the EPS estimate and gapped up beyond its usual move: buy the reaction close, hold n sessions."""
    w = pd.Series(0.0, index=f.index)
    pos = {d: i for i, d in enumerate(f.index)}
    for r in ev.itertuples():
        i = pos.get(r.reaction)
        if i is None or not (r.band and r.surprise > 0 and r.gap > r.band):
            continue
        w.iloc[i:i + p["hold"]] = 1.0
    return w


EARN: dict[str, Callable] = {"earn_runup": e_runup, "earn_avoid": e_avoid, "earn_gap_follow": e_gap_follow,
                             "earn_gap_down": e_gap_fade_down, "earn_double_beat": e_double_beat}


# ───────────────────────── the catalog ─────────────────────────

SINGLE_SPECS = [
    # template, params, family, source, year published
    ("sma_trend", {"n": 200}, "trend", "200-day moving average filter (Siegel 1994; Faber 2007)", 1994),
    ("sma_monthly", {"n": 10}, "trend", "Faber (2007), A Quantitative Approach to Tactical Asset Allocation", 2007),
    ("sma_cross", {"fast": 50, "slow": 200}, "trend", "Golden cross (50/200-day)", None),
    ("donchian", {"entry": 20, "exit": 10}, "trend", "Donchian channel / Turtle System 1 (Dennis 1983; Faith 2003)", 2003),
    ("donchian", {"entry": 55, "exit": 20}, "trend", "Turtle System 2 (Faith 2003)", 2003),
    ("high52", {"exit": 50}, "trend", "52-week high (George & Hwang 2004)", 2004),
    ("macd", {}, "trend", "MACD 12/26/9 (Appel 1979)", 1979),
    ("tsmom", {"n": 252}, "trend", "Time-series momentum (Moskowitz, Ooi & Pedersen 2012)", 2012),
    ("rsi2", {"lo": 10}, "reversion", "Connors & Alvarez (2008), RSI(2)", 2008),
    ("rsi14", {}, "reversion", "RSI(14) 30/70 (Wilder 1978)", 1978),
    ("boll_revert", {}, "reversion", "Bollinger band reversion 20/2 (Bollinger 2001)", 2001),
    ("boll_break", {}, "trend", "Bollinger band breakout 20/2 (Bollinger 2001)", 2001),
    ("ibs", {"lo": 0.2}, "reversion", "Internal bar strength (Pagonidis 2013)", 2013),
    ("down_streak", {"n": 3}, "reversion", "Three down closes", None),
    ("vol_target", {"target": 0.15}, "volatility", "Volatility targeting (Moreira & Muir 2017)", 2017),
]
INDEX_ONLY = [
    ("turn_of_month", {}, "seasonal", "Turn of the month (Lakonishok & Smidt 1988; McConnell & Xu 2008)", 1988),
    ("halloween", {}, "seasonal", "Halloween / sell in May (Bouman & Jacobsen 2002)", 2002),
    ("pre_holiday", {}, "seasonal", "Pre-holiday effect (Ariel 1990)", 1990),
    ("fomc", {}, "seasonal", "Pre-FOMC drift (Lucca & Moench 2015)", 2015),
    ("vix_regime", {}, "volatility", "VIX below its 50-day average", None),
]
EARN_SPECS = [
    ("earn_runup", {}, "Earnings announcement premium (Barber et al. 2013)", 2013),
    ("earn_avoid", {}, "Skip the report: hold the stock but step aside across earnings", None),
    ("earn_gap_follow", {"k": 1, "hold": 20}, "Post-earnings gap drift (Brandt et al. 2008)", 2008),
    ("earn_gap_down", {"k": 2, "hold": 5}, "Buy the post-earnings flush, hold a week", None),
    ("earn_double_beat", {"hold": 60}, "Double surprise: EPS beat + gap (Bernard & Thomas 1989; Chan et al. 1996)", 1989),
]
ALLOC_SPECS = [
    ("alloc_6040", "static", {"w": {"SPY": 0.6, "AGG": 0.4}}, ["SPY", "AGG"], "60/40 stocks/bonds", None),
    ("alloc_permanent", "static", {"w": {"VTI": 0.25, "TLT": 0.25, "SHY": 0.25, "GLD": 0.25}}, ["VTI", "TLT", "SHY", "GLD"],
     "Permanent portfolio (Browne 1987)", 1987),
    ("alloc_allweather", "static", {"w": {"VTI": 0.30, "TLT": 0.40, "IEF": 0.15, "GLD": 0.075, "DBC": 0.075}},
     ["VTI", "TLT", "IEF", "GLD", "DBC"], "All Weather (Dalio, via Robbins 2014)", 2014),
    ("alloc_butterfly", "static", {"w": {"VTI": 0.2, "IJS": 0.2, "TLT": 0.2, "SHY": 0.2, "GLD": 0.2}},
     ["VTI", "IJS", "TLT", "SHY", "GLD"], "Golden butterfly (Tyler 2016)", 2016),
    ("alloc_gtaa5", "gtaa", {}, ["VTI", "EFA", "IEF", "DBC", "VNQ"], "GTAA 5 (Faber 2007)", 2007),
    ("alloc_gem", "dual_momentum", {}, ["SPY", "EFA", "AGG", "BIL"], "Dual momentum / GEM (Antonacci 2014)", 2014),
    ("alloc_adm", "adm", {}, ["SPY", "SCZ", "TLT"], "Accelerating dual momentum (EngineeredPortfolio 2018)", 2018),
    ("alloc_riskparity", "risk_parity", {}, ["SPY", "TLT"], "Risk parity, stocks/bonds (inverse volatility)", None),
    ("alloc_sectors", "top_momentum", {"n": 126, "k": 3}, SECTORS, "Sector momentum (Moskowitz & Grinblatt 1999)", 1999),
    ("alloc_cross_mom", "top_momentum", {"n": 252, "k": 3}, ["SPY", "EFA", "EEM", "TLT", "GLD", "DBC", "VNQ"],
     "Cross-asset momentum top 3 (Faber 2010)", 2010),
]


# Templates Autopilot does not run yet: fractional weights that need re-sizing every day
# (it sizes a position once, on entry), the VIX (no broker feed) and the earnings rules
# (they need each stock's next report date in advance).
NOT_LIVE = {"vol_target": "lib.note.rebalance", "risk_parity": "lib.note.rebalance", "static": "lib.note.rebalance",
            "vix_regime": "lib.note.vix", **{k: "lib.note.earnings" for k in EARN}}


def build_specs() -> list[Spec]:
    specs: list[Spec] = []
    for a in INDEXES + STOCKS:
        cost_bench = a
        for tpl, params, fam, src, yr in SINGLE_SPECS:
            pid = "_".join(f"{k}{v}" for k, v in params.items())
            specs.append(Spec(f"{tpl}{'_' + pid if pid else ''}:{a}", fam, tpl, params, [a], cost_bench,
                              f"lib.t.{tpl}", src, yr))
    for a in INDEXES:
        for tpl, params, fam, src, yr in INDEX_ONLY:
            specs.append(Spec(f"{tpl}:{a}", fam, tpl, params, [a], a, f"lib.t.{tpl}", src, yr))
    for a in STOCKS:
        for tpl, params, src, yr in EARN_SPECS:
            pid = "_".join(f"{k}{v}" for k, v in params.items())
            specs.append(Spec(f"{tpl}{'_' + pid if pid else ''}:{a}", "earnings", tpl, params, [a], a,
                              f"lib.t.{tpl}", src, yr, executable=False,
                              note="lib.note.earnings"))
    for sid, tpl, params, assets, src, yr in ALLOC_SPECS:
        specs.append(Spec(sid, "allocation", tpl, params, assets, "SPY", f"lib.t.{sid}", src, yr))
    for sp in specs:
        sp.executable = sp.template not in NOT_LIVE
        sp.note = NOT_LIVE.get(sp.template, "")
    return specs


_BY_ID: dict[str, Spec] = {}


def find(spec_id: str) -> Spec | None:
    if not _BY_ID:
        _BY_ID.update({s.id: s for s in build_specs()})
    return _BY_ID.get(spec_id)


def _extend(f: pd.DataFrame, future: list) -> pd.DataFrame:
    """Append the coming sessions (no prices) so calendar rules know what comes next."""
    if not future:
        return f
    return f.reindex(f.index.union(pd.DatetimeIndex(future)))


def _single(tpl: str, f: pd.DataFrame, params: dict, extra: dict) -> pd.Series:
    p = dict(params)
    if tpl == "fomc":
        p["dates"] = extra.get("fomc", [])
    if tpl == "vix_regime":
        return t_vix_regime(f, p, extra.get("vix"))
    return SINGLE[tpl](f, p)


def weights(spec: Spec, O: dict[str, pd.DataFrame], extra: dict[str, Any] | None = None) -> pd.DataFrame:
    """Weights to hold from each close to the next, one column per asset.

    extra: "fomc" (decision days), "vix" (series), "events" ({ticker: reports}) and, for the
    live run, "future" (the next sessions, so month-ends, holidays and FOMC days are known)."""
    extra = extra or {}
    fut = extra.get("future") or []
    if spec.template in SINGLE:
        a = spec.assets[0]
        f = _extend(O[a], fut)
        w = _single(spec.template, f, spec.params, extra)
        # optional filters (AND): e.g. RSI(2) only while above the 200-day average
        for flt in spec.extra.get("filters") or []:
            w = w * _single(flt["template"], f, flt.get("params") or {}, extra).clip(0, 1)
        return w.rename(a).to_frame()
    if spec.template in EARN:
        a = spec.assets[0]
        ev = (extra.get("events") or {}).get(a)
        if ev is None or ev.empty:
            return pd.DataFrame(0.0, index=O[a].index, columns=[a])
        return EARN[spec.template](O[a], ev, spec.params).rename(a).to_frame()
    # a portfolio starts once every one of its assets trades
    C = pd.DataFrame({a: O[a].c for a in spec.assets if a in O}).dropna()
    C = C.reindex(C.index.union(pd.DatetimeIndex(fut))) if fut else C
    return MULTI[spec.template](C, spec.params)


# ───────────────────────── user strategies ─────────────────────────
# What a person (or the LLM on their behalf) may ask for: a template from above, its
# parameters inside these bounds, up to two filters, and instruments Yahoo has history for.

BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "buy_hold": {}, "sma_trend": {"n": (5, 400)}, "sma_monthly": {"n": (2, 24)},
    "sma_cross": {"fast": (2, 200), "slow": (10, 400)}, "donchian": {"entry": (5, 250), "exit": (2, 120)},
    "high52": {"exit": (5, 200)}, "macd": {}, "tsmom": {"n": (20, 504)}, "rsi2": {"lo": (1, 40)}, "rsi14": {},
    "boll_revert": {}, "boll_break": {}, "ibs": {"lo": (0.05, 0.5)}, "down_streak": {"n": (2, 7)},
    "vol_target": {"target": (0.05, 0.4)}, "turn_of_month": {}, "halloween": {}, "fomc": {}, "pre_holiday": {},
    "vix_regime": {}, "earn_runup": {}, "earn_avoid": {}, "earn_gap_follow": {"k": (0.3, 5), "hold": (1, 120)},
    "earn_gap_down": {"k": (0.3, 5), "hold": (1, 60)}, "earn_double_beat": {"hold": (1, 120)},
    "gtaa": {}, "dual_momentum": {}, "risk_parity": {}, "top_momentum": {"n": (21, 504), "k": (1, 10)}, "adm": {},
    "static": {},
}
INTS = {"n", "fast", "slow", "entry", "exit", "hold", "k_assets"}
FIXED_ASSETS = {"dual_momentum": ["SPY", "EFA", "AGG", "BIL"], "adm": ["SPY", "SCZ", "TLT"]}
TICKER_OK = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^"


def spec_from_dict(d: dict, sid: str = "custom") -> Spec:
    """Validate a user strategy; raises ValueError with a reason a person can act on."""
    tpl = str(d.get("template") or "")
    if tpl not in BOUNDS:
        raise ValueError(f"Unknown template {tpl!r}")
    assets = [str(a).upper().strip() for a in (d.get("assets") or [])][:12]
    assets = list(dict.fromkeys(a for a in assets if a and all(ch in TICKER_OK for ch in a) and len(a) <= 10))
    if tpl in FIXED_ASSETS:
        assets = FIXED_ASSETS[tpl]
    multi = tpl in MULTI
    if not assets or (not multi and len(assets) != 1) or (multi and len(assets) < 2 and tpl != "static"):
        raise ValueError("Single-instrument templates take one ticker; portfolio templates take two or more")

    def clean(t: str, raw: dict) -> dict:
        out = {}
        for k, (lo, hi) in BOUNDS[t].items():
            v = (raw or {}).get(k, None)
            if v is None:
                raise ValueError(f"{t} needs parameter {k} ({lo}–{hi})")
            v = float(v)
            if not lo <= v <= hi:
                raise ValueError(f"{t}.{k} must be between {lo} and {hi}")
            out[k] = int(round(v)) if k in INTS or (k == "k" and t == "top_momentum") else round(v, 4)
        return out
    params = clean(tpl, d.get("params") or {})
    if tpl == "sma_cross" and params["fast"] >= params["slow"]:
        raise ValueError("sma_cross: fast must be shorter than slow")
    if tpl == "top_momentum" and params["k"] >= len(assets):
        raise ValueError("top_momentum: k must be smaller than the number of assets")
    if tpl == "static":
        w = {str(k).upper(): float(v) for k, v in ((d.get("params") or {}).get("w") or {}).items()}
        if not w or any(v < 0 for v in w.values()) or sum(w.values()) > 1.0001:
            raise ValueError("static: weights must be positive and add up to 1 or less")
        assets = list(w)
        params = {"w": w}
    filters = []
    for flt in (d.get("filters") or [])[:2]:
        ft = str(flt.get("template") or "")
        if multi or ft not in SINGLE or ft in ("buy_hold",):
            raise ValueError("Filters work on single-instrument rules only, with a single-instrument template")
        filters.append({"template": ft, "params": clean(ft, flt.get("params") or {})})
    fam = ("earnings" if tpl in EARN else "allocation" if multi else
           next((f for t, _, f, *_ in SINGLE_SPECS + INDEX_ONLY if t == tpl), "trend"))
    sp = Spec(sid, fam, tpl, params, assets, assets[0] if not multi else "SPY", f"lib.t.{tpl}", "custom",
              extra={"filters": filters} if filters else {})
    sp.executable = tpl not in NOT_LIVE and not any(f["template"] in NOT_LIVE for f in filters)
    sp.note = NOT_LIVE.get(tpl, "")
    return sp


def spec_to_dict(sp: Spec) -> dict:
    return {"template": sp.template, "params": sp.params, "assets": sp.assets,
            "filters": sp.extra.get("filters") or []}


def returns(spec: Spec, O: dict[str, pd.DataFrame], cash: pd.Series, extra: dict[str, Any] | None = None) -> pd.Series:
    return backtest(spec, O, cash, extra)[0]


def backtest(spec: Spec, O: dict[str, pd.DataFrame], cash: pd.Series,
             extra: dict[str, Any] | None = None) -> tuple[pd.Series, pd.DataFrame]:
    """Daily strategy returns after costs (weights decided at close t earn close t -> t+1,
    booked on t+1) and the weights themselves."""
    w = weights(spec, O, extra)
    C = pd.DataFrame({a: O[a].c for a in w.columns}).reindex(w.index)
    r = C.pct_change().shift(-1)  # return earned by holding from this close to the next
    w = w.reindex(r.index).fillna(0.0).clip(lower=0)
    gross = (w * r.fillna(0)).sum(axis=1)
    invested = w.sum(axis=1).clip(upper=1.0)
    cash_r = cash.reindex(r.index).ffill().fillna(0.0)
    cost_bp = 0.0002 if all(a in INDEXES + SECTORS + CROSS for a in w.columns) else 0.0005
    turnover = w.diff().abs().sum(axis=1).fillna(w.abs().sum(axis=1))
    net = gross + (1 - invested) * cash_r - turnover * cost_bp
    # shift so each return is booked on the day it is earned
    return net.shift(1).dropna(), w
