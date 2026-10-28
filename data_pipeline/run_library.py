"""Backtest and grade every strategy in the library (services/library.py).

For each spec: daily returns after costs on total-return prices (Yahoo, 1993 on), cash at
the T-bill rate; the same numbers for buying and holding its benchmark; three windows —
the whole history, before 2015 and from 2015 on (out of sample for every rule published
before then, which is most of them). Then:

* alpha and its t-stat: the daily excess return regressed on the benchmark's, for the whole
  history, before 2015, from 2015, and from the year after the rule was published;
* the Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014): the probability that the
  strategy's true Sharpe ratio beats the best one you would expect by luck after trying
  this many — every spec in the library counts as a trial, so the bar rises with the
  catalogue;
* a grade (benchmark = holding the same instrument; SPY for portfolios):
    A  from 2015 a Sharpe 0.1+ above the benchmark's and alpha t >= 2, and over the whole
       history alpha t >= 3 (the multiple-testing hurdle of Harvey, Liu & Zhu 2016)
    B  from 2015 at least the benchmark's Sharpe, and alpha t >= 1 from 2015 or >= 2 overall
    C  defensive: from 2015 a Sharpe within 0.15 of the benchmark's with a max drawdown at
       least 20% smaller
    D  beat T-bills from 2015 but behind the benchmark
    F  did not beat T-bills from 2015

Writes $DATA_DIR/library.json (one row per strategy) and library_curves.json (monthly
equity, strategy and benchmark), and prints the grade counts.

    python -m data_pipeline.run_library
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from backend.app.services import library as L

SPLIT = pd.Timestamp("2015-01-01")
DATA = Path(os.getenv("DATA_DIR", "/app/data"))


def load_prices() -> tuple[dict[str, pd.DataFrame], pd.Series, pd.Series]:
    import yfinance as yf

    tick = sorted(set(L.INDEXES + L.STOCKS + L.SECTORS + L.CROSS))
    raw = yf.download(tick + ["^IRX", "^VIX"], start="1993-01-01", auto_adjust=True, progress=False,
                      group_by="ticker", threads=True)
    O = {}
    for t in tick:
        try:
            f = raw[t][["Open", "High", "Low", "Close"]].dropna(how="all")
        except KeyError:
            continue
        f.columns = ["o", "h", "l", "c"]
        f.index = pd.to_datetime(f.index).tz_localize(None)
        f = f.dropna(subset=["c"])
        if len(f) > 260:
            O[t] = f
    irx = raw["^IRX"]["Close"]
    irx.index = pd.to_datetime(irx.index).tz_localize(None)
    cash = (irx.ffill() / 100 / 252).fillna(0)
    vix = raw["^VIX"]["Close"]
    vix.index = pd.to_datetime(vix.index).tz_localize(None)
    return O, cash, vix


def events_for(t: str, f: pd.DataFrame) -> pd.DataFrame | None:
    """Every report since about 2002 from Yahoo's earnings calendar (the platform's own
    outcomes table only starts in 2020): the reaction session (the report day if it came
    before the open, else the next session), the opening gap, the stock's usual move (mean
    absolute gap of its previous eight reports, so known in advance) and the EPS surprise."""
    import yfinance as yf

    try:
        d = yf.Ticker(t).get_earnings_dates(limit=100)
    except Exception as exc:  # noqa: BLE001
        print("events fail", t, exc, flush=True)
        return None
    if d is None or d.empty:
        return None
    d = d[d["Reported EPS"].notna() | d["Surprise(%)"].notna()]
    rows = []
    for stamp, sur in zip(pd.to_datetime(d.index), d["Surprise(%)"]):
        day = pd.Timestamp(stamp.date())
        k = f.index.searchsorted(day, side="right" if stamp.hour >= 12 else "left")
        if k <= 0 or k >= len(f):
            continue
        rows.append({"reaction": f.index[k], "gap": float(f.o.iloc[k] / f.c.iloc[k - 1] - 1),
                     "surprise": float(sur) if pd.notna(sur) else np.nan})
    if not rows:
        return None
    g = pd.DataFrame(rows).drop_duplicates("reaction").sort_values("reaction").reset_index(drop=True)
    g["band"] = g.gap.abs().shift(1).rolling(8, min_periods=4).mean()
    return g


def load_events(O) -> dict[str, pd.DataFrame]:
    import time

    out = {}
    for t in L.STOCKS:
        if t in O:
            g = events_for(t, O[t])
            time.sleep(1)
            if g is not None:
                out[t] = g
                print(t, len(g), "reports from", g.reaction.iloc[0].date(), flush=True)
    return out


def stats(r: pd.Series, cash: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 250:
        return {"days": int(len(r))}
    ex = r - cash.reindex(r.index).fillna(0)
    eq = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((eq / eq.cummax() - 1).min())
    sd = ex.std()
    yr = (1 + r).groupby(r.index.year).prod() - 1
    return {"days": int(len(r)), "start": str(r.index[0].date()), "end": str(r.index[-1].date()),
            "cagr": float(eq.iloc[-1] ** (1 / yrs) - 1), "vol": float(r.std() * math.sqrt(252)),
            "sharpe": float(ex.mean() / sd * math.sqrt(252)) if sd > 0 else None, "max_dd": dd,
            "calmar": float((eq.iloc[-1] ** (1 / yrs) - 1) / abs(dd)) if dd < 0 else None,
            "cash_cagr": float((1 + cash.reindex(r.index).fillna(0)).prod() ** (1 / yrs) - 1),
            "years_up": int((yr > 0).sum()), "years_total": int(len(yr)),
            "skew": float(ex.skew()), "kurt": float(ex.kurt() + 3)}


def alpha(r: pd.Series, b: pd.Series, cash: pd.Series) -> dict:
    df = pd.concat([r, b], axis=1, join="inner").dropna()
    if len(df) < 250:
        return {}
    c = cash.reindex(df.index).fillna(0)
    y, x = df.iloc[:, 0] - c, df.iloc[:, 1] - c
    X = np.column_stack([np.ones(len(x)), x.values])
    beta, *_ = np.linalg.lstsq(X, y.values, rcond=None)
    res = y.values - X @ beta
    s2 = res.var(ddof=2)
    cov = s2 * np.linalg.inv(X.T @ X)
    return {"alpha": float(beta[0] * 252), "alpha_t": float(beta[0] / math.sqrt(cov[0, 0])), "beta": float(beta[1])}


def dsr(sr_d: float, n: int, skew: float, kurt: float, trials: int, sr_var: float) -> float:
    """Deflated Sharpe Ratio with daily Sharpe `sr_d` over n days, against `trials` attempts
    whose daily Sharpe ratios have variance `sr_var`."""
    g = 0.5772156649
    sr0 = math.sqrt(sr_var) * ((1 - g) * norm.ppf(1 - 1 / trials) + g * norm.ppf(1 - 1 / (trials * math.e)))
    den = math.sqrt(max(1 - skew * sr_d + (kurt - 1) / 4 * sr_d ** 2, 1e-9))
    return float(norm.cdf((sr_d - sr0) * math.sqrt(n - 1) / den))


def grade(o: dict, ob: dict, a_t: float | None, a_full_t: float | None) -> str:
    if not o.get("cagr") or o.get("sharpe") is None or ob.get("sharpe") is None:
        return "N"
    if o["cagr"] <= o.get("cash_cagr", 0):
        return "F"
    s, sb = o["sharpe"], ob["sharpe"]
    if s >= sb + 0.1 and (a_t or 0) >= 2 and (a_full_t or 0) >= 3:
        return "A"
    if s >= sb and ((a_t or 0) >= 1 or (a_full_t or 0) >= 2):
        return "B"
    if s >= sb - 0.15 and o["max_dd"] > ob["max_dd"] * 0.8:
        return "C"
    return "D"


def activity(w: pd.DataFrame, r: pd.Series) -> dict:
    w = w.reindex(r.index).fillna(0)
    yrs = max((r.index[-1] - r.index[0]).days / 365.25, 1e-9)
    on = (w.sum(axis=1) > 1e-9)
    entries = int((on & ~on.shift(1, fill_value=False)).sum())
    return {"exposure": float(w.sum(axis=1).clip(upper=1).mean()), "entries_yr": entries / yrs,
            "turnover_yr": float(w.diff().abs().sum(axis=1).sum() / yrs),
            "avg_hold": float(on.sum() / entries) if entries else None}


def monthly(r: pd.Series) -> list[dict]:
    eq = (1 + r.dropna()).cumprod().resample("ME").last()
    return [{"t": str(i.to_period("M")), "v": round((v - 1) * 100, 3)} for i, v in eq.items()]


def trim(s: L.Spec, r: pd.Series, w: pd.DataFrame, events: dict) -> pd.Series | None:
    """Start the record when the rule can first act: earnings rules once the stock's usual
    move is known, the others on their first day invested (not during the warm-up)."""
    if s.family == "earnings":
        ev = events.get(s.assets[0])
        if ev is None or len(ev) < 12:
            return None
        return r[r.index >= ev.reaction.iloc[4]]
    on = w.sum(axis=1)
    if s.template != "buy_hold" and (on > 0).any():
        return r[r.index >= on[on > 0].index.min()]
    return r


def score(s: L.Spec, r: pd.Series, w: pd.DataFrame, b: pd.Series, cash: pd.Series, trials: int, sr_var: float) -> dict:
    b = b.reindex(r.index)
    full, bfull = stats(r, cash), stats(b, cash)
    o, ob = stats(r[r.index >= SPLIT], cash), stats(b[b.index >= SPLIT], cash)
    i, ib = stats(r[r.index < SPLIT], cash), stats(b[b.index < SPLIT], cash)
    a_full, a_oos = alpha(r, b, cash), alpha(r[r.index >= SPLIT], b[b.index >= SPLIT], cash)
    a_is = alpha(r[r.index < SPLIT], b[b.index < SPLIT], cash)
    post = None
    if s.published:
        cut = pd.Timestamp(f"{s.published + 1}-01-01")
        if (r.index >= cut).sum() > 500:
            post = {"from": str(cut.date()), **stats(r[r.index >= cut], cash),
                    "bench": stats(b[b.index >= cut], cash), "alpha": alpha(r[r.index >= cut], b[b.index >= cut], cash)}
    ex = (r - cash.reindex(r.index).fillna(0)).dropna()
    d = dsr(ex.mean() / ex.std(), len(ex), float(ex.skew()), float(ex.kurt() + 3), trials, sr_var) \
        if len(ex) > 250 and ex.std() > 0 else None
    # a strategy with less than three years from 2015 is graded on what it has
    go, gob = (o, ob) if o.get("cagr") is not None else (full, bfull)
    ga = a_oos if o.get("cagr") is not None else a_full
    return {"id": s.id, "family": s.family, "template": s.template, "params": s.params, "assets": s.assets,
            "filters": s.extra.get("filters") or [], "bench": s.bench, "source": s.source, "published": s.published,
            "executable": s.executable, "note": s.note, "grade": grade(go, gob, ga.get("alpha_t"), a_full.get("alpha_t")),
            "dsr": d, "full": full, "bench_full": bfull, "oos": o, "bench_oos": ob, "is": i, "bench_is": ib,
            "alpha": a_full, "alpha_oos": a_oos, "alpha_is": a_is, "post": post, "activity": activity(w, r)}


def bench_returns(t: str, O: dict, cash: pd.Series) -> pd.Series:
    return L.returns(L.Spec("bh", "", "buy_hold", {}, [t], t, "", ""), O, cash)


def main() -> None:
    import pickle

    from data_pipeline.research_etf import fomc_dates

    O, cash, vix = load_prices()
    events = load_events(O)
    fomc = fomc_dates()
    extra = {"vix": vix, "fomc": fomc, "events": events}
    with open(DATA / "library_prices.pkl", "wb") as fh:
        pickle.dump({"O": O, "cash": cash, "vix": vix, "fomc": fomc, "events": events}, fh)
    specs = [s for s in L.build_specs() if all(a in O for a in s.assets)]
    print(f"{len(specs)} strategies over {len(O)} instruments", flush=True)
    bench_r: dict[str, pd.Series] = {}
    rets: dict[str, tuple[pd.Series, pd.DataFrame]] = {}
    for k, s in enumerate(specs):
        try:
            r, w = L.backtest(s, O, cash, extra)
        except Exception as exc:  # noqa: BLE001
            print("fail", s.id, exc, flush=True)
            continue
        r = trim(s, r, w, events)
        if r is None:
            continue
        if s.bench not in bench_r:
            bench_r[s.bench] = bench_returns(s.bench, O, cash)
        rets[s.id] = (r, w)
        if k % 50 == 0:
            print(f"{k}/{len(specs)}", flush=True)
    # deflation: every daily Sharpe in the library is a trial
    srs = []
    for r, _ in rets.values():
        ex = (r - cash.reindex(r.index).fillna(0)).dropna()
        if len(ex) > 250 and ex.std() > 0:
            srs.append(ex.mean() / ex.std())
    sr_var, trials = float(np.var(srs)), len(srs)
    rows, curves = [], {}
    for s in specs:
        if s.id not in rets:
            continue
        r, w = rets[s.id]
        rows.append(score(s, r, w, bench_r[s.bench], cash, trials, sr_var))
        curves[s.id] = {"s": monthly(r), "b": monthly(bench_r[s.bench].reindex(r.index))}
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "split": str(SPLIT.date()), "trials": trials,
           "sr_var_daily": sr_var, "count": len(rows),
           "grades": pd.Series([r["grade"] for r in rows]).value_counts().to_dict(), "rows": rows}
    (DATA / "library.json").write_text(json.dumps(out, default=float))
    (DATA / "library_curves.json").write_text(json.dumps(curves))
    print("grades", out["grades"], flush=True)
    for fam in sorted({r["family"] for r in rows}):
        fr = [r for r in rows if r["family"] == fam]
        print(fam, pd.Series([r["grade"] for r in fr]).value_counts().to_dict(), flush=True)
    top = sorted([r for r in rows if r["grade"] in ("A", "B")], key=lambda r: -(r["alpha"].get("alpha_t") or 0))[:30]
    for r in top:
        print(r["grade"], r["id"], "oos sharpe %.2f vs %.2f" % (r["oos"]["sharpe"], r["bench_oos"]["sharpe"]),
              "alpha_t %.1f / %.1f" % (r["alpha_oos"].get("alpha_t") or 0, r["alpha"].get("alpha_t") or 0),
              "dsr %.2f" % (r["dsr"] or 0), flush=True)
    print("LIBRARY_DONE", flush=True)


if __name__ == "__main__":
    main()
