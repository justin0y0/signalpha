"""Single-stock rules from the literature, on the platform's own universe and earnings data.

  pre_run     Earnings announcement premium — Frazzini & Lamont (2007), Barber, De George,
              Lehavy & Trueman (2013): stocks rise into a scheduled report. Buy at the close
              five sessions before the last pre-announcement close, sell at that close (the
              report itself is never held). Report dates come from the platform's calendar.
  pre_run_ml  The same, only for reports in the top third of the breakout model's
              prob_move (cut points from earlier years only). Frazzini & Lamont find the
              premium is largest where the announcement draws the most attention; the model's
              expected-move score is the platform's measure of that.
  sue         Post-earnings-announcement drift — Bernard & Thomas (1989): after the report,
              buy the top tenth by EPS surprise (cut point from the previous 90 days of
              reports) at the reaction-session close, hold 60 sessions.
  sue_gap     The same, only when the price also gapped up beyond its usual range
              (gap_x > 1): the market and the numbers agree (Chan, Jegadeesh & Lakonishok 1996).
  momentum    Jegadeesh & Titman (1993): each month-end, hold the 50 stocks of the large/mid
              universe with the best 12-month return skipping the last month.
  rsi2_mega   Connors & Alvarez (2008) on single stocks: the ~100 mega-caps the Pulse desk
              watches; buy at the close when RSI(2) < 5 above the 200-day average, sell at the
              close above the 5-day average or after 10 sessions; ten slots, most oversold first.

Universe: today's US stocks above $300M (large and mid tiers) — firms that later delisted are
missing, which flatters long-only rules; stated on the page. Daily bars: Alpaca SIP, adjusted
for splits and dividends, from 2015-06. Costs: 10 bp round trip on single stocks.

    python -m data_pipeline.research_equity     # writes $DATA_DIR/research_equity.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from backend.app.services.market_pulse_service import SECTORS as MEGA
from data_pipeline.research_common import alpaca_daily, curve, event_sleeve, out_path, summary, tstat
from data_pipeline.research_etf import rsi

COST = 0.001
START = "2015-06-01"


def excess(trades: pd.DataFrame, C: pd.DataFrame) -> pd.Series:
    spy = C.SPY
    out = []
    for t in trades.itertuples():
        try:
            m = spy.loc[t.exit] / spy.loc[t.entry] - 1
        except KeyError:
            m = np.nan
        out.append(t.ret - t.side * m)
    return pd.Series(out, index=trades.index)


def main() -> None:
    with SessionLocal() as db:
        uni = pd.read_sql(text("SELECT ticker, tier FROM universe WHERE tier IN ('core','large','mid')"), db.bind)
        ev = pd.read_sql(text("""
            SELECT o.ticker, o.earnings_date, o.reaction_date, e.report_time, o.actual_t1_gap_pct AS gap, o.flat_band AS band,
                   p.prob_move, s.surprise_pct AS surprise
            FROM outcomes o JOIN earnings_events e ON e.ticker=o.ticker AND e.earnings_date=o.earnings_date
            LEFT JOIN predictions p ON p.ticker=o.ticker AND p.earnings_date=o.earnings_date AND p.is_out_of_sample
            LEFT JOIN LATERAL (SELECT surprise_pct FROM earnings_surprises s WHERE s.ticker=o.ticker
                               AND s.report_date BETWEEN o.earnings_date - 3 AND o.earnings_date + 3
                               ORDER BY abs(s.report_date - o.earnings_date) LIMIT 1) s ON TRUE
            WHERE o.earnings_date >= :s"""), db.bind, params={"s": START})
    names = sorted(set(uni.ticker) | set(MEGA) | {"SPY"})
    O, C = alpaca_daily(names, START)
    C, O = C.sort_index(), O.reindex(C.index)
    days = C.index
    spy = C.SPY.pct_change().fillna(0)
    pos = {d: i for i, d in enumerate(days)}
    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "start": START, "cost": COST,
                 "universe": int(len(uni)), "rules": {}}

    def record(key: str, trades: pd.DataFrame, slots: int, rank: str | None = None, extra: dict | None = None):
        r, taken = event_sleeve(trades, C, O, slots, COST, rank=rank)
        first = r.ne(0).idxmax()
        r = r[r.index >= first]
        ex = excess(taken, C) if len(taken) else pd.Series(dtype=float)
        body = {"all": summary(r, spy), "per_trade": tstat(taken.ret) if len(taken) else {},
                "excess": tstat(ex), "signals": int(len(trades)), "taken": int(len(taken)), "slots": slots,
                **curve(r, spy)}
        if len(taken):
            taken = taken.assign(excess=ex.values, yr=pd.to_datetime(taken.entry).dt.year)
            body["by_year"] = {int(y): tstat(g.excess) for y, g in taken.groupby("yr")}
        body.update(extra or {})
        out["rules"][key] = body
        a, e = body["all"], body["excess"]
        print(f"{key:10s} CAGR {a.get('cagr', 0)*100:+.1f}% vs SPY {a.get('spy_cagr', 0)*100:+.1f}% DD {a.get('max_dd', 0)*100:.0f}% "
              f"Sharpe {a.get('sharpe') or 0:.2f} vs {a.get('spy_sharpe') or 0:.2f} | per trade {body['per_trade'].get('mean', 0)*100:+.2f}% "
              f"| excess vs SPY {e.get('mean', 0)*100:+.2f}% t={e.get('t') or 0:+.1f} n={e.get('n')} (signals {len(trades)})", flush=True)

    # ── earnings windows
    ev["reaction_date"] = pd.to_datetime(ev.reaction_date)
    ev["earnings_date"] = pd.to_datetime(ev.earnings_date)
    rt = ev.report_time.fillna("AMC")
    ev["reaction"] = ev.reaction_date.where(ev.reaction_date.notna(),
                                            ev.earnings_date + pd.to_timedelta(rt.isin(["AMC"]).astype(int), unit="D"))
    ev = ev[ev.ticker.isin(set(uni.ticker)) & ev.reaction.isin(pos)].copy()
    ev["ri"] = ev.reaction.map(pos)
    ev = ev[ev.ri >= 6]
    ev["d0"] = [days[i - 1] for i in ev.ri]
    ev["d_5"] = [days[i - 6] for i in ev.ri]
    ev["yr"] = ev.earnings_date.dt.year
    cuts = {}
    for y in sorted(ev.yr.unique()):
        past = ev[(ev.yr < y) & ev.prob_move.notna()].prob_move
        cuts[y] = past.quantile(2 / 3) if len(past) > 2000 else np.nan
    ev["ml_top"] = [bool(p >= cuts[y]) if pd.notna(p) and pd.notna(cuts[y]) else False for p, y in zip(ev.prob_move, ev.yr)]

    pre = pd.DataFrame({"ticker": ev.ticker, "entry": ev.d_5, "entry_at": "close", "exit": ev.d0, "exit_at": "close",
                        "side": 1, "pm": ev.prob_move.fillna(0)})
    record("pre_run", pre, slots=30)
    record("pre_run_ml", pre[ev.ml_top.values], slots=20, rank="pm",
           extra={"ml_cut_from": int(min(y for y, c in cuts.items() if pd.notna(c))) if any(pd.notna(c) for c in cuts.values()) else None})
    through = pre.assign(exit=ev.reaction.values)
    record("pre_run_through", through, slots=30)

    # ── post-earnings drift by surprise
    ev = ev.sort_values("reaction")
    s = ev.surprise
    thr = []
    hist = ev[["reaction", "surprise"]].dropna()
    for d in ev.reaction:
        w = hist[(hist.reaction < d) & (hist.reaction >= d - pd.Timedelta(days=90))].surprise
        thr.append(w.quantile(0.9) if len(w) >= 200 else np.nan)
    ev["sue_top"] = (s >= np.array(thr)) & s.notna()
    ev["exit60"] = [days[min(i + 60, len(days) - 1)] for i in ev.ri]
    ok = ev.ri + 60 < len(days)
    gx = ev.gap / ev.band
    sue = pd.DataFrame({"ticker": ev.ticker, "entry": ev.reaction, "entry_at": "close", "exit": ev.exit60, "exit_at": "close",
                        "side": 1, "s": s.fillna(0)})
    record("sue", sue[(ev.sue_top & ok).values], slots=20, rank="s")
    record("sue_gap", sue[(ev.sue_top & ok & (gx > 1)).values], slots=20, rank="s")
    base60 = tstat([(C[t].iloc[i + 60] / C[t].iloc[i] - 1) - (C.SPY.iloc[i + 60] / C.SPY.iloc[i] - 1)
                    for t, i in zip(ev.ticker[ok], ev.ri[ok]) if t in C])
    out["base_60d_excess_all_reports"] = base60

    # ── momentum 12-1, top 50, monthly
    big = [t for t in uni.ticker if t in C]
    month_end = days.to_series().groupby([days.year, days.month]).tail(1)
    trades = []
    me = list(month_end)
    for k in range(12, len(me) - 1):
        d, d12, d1 = me[k], me[k - 12], me[k - 1]
        r = C.loc[d1, big] / C.loc[d12, big] - 1
        r = r[C.loc[d, big].notna()].dropna()
        for t in r.sort_values(ascending=False).index[:50]:
            trades.append({"ticker": t, "entry": d, "entry_at": "close", "exit": me[k + 1], "exit_at": "close", "side": 1})
    record("momentum", pd.DataFrame(trades), slots=50)

    # ── RSI(2) on the Pulse mega-caps
    mega = [t for t in MEGA if t in C]
    trades = []
    for t in mega:
        c = C[t].dropna()
        if len(c) < 250:
            continue
        rs, s200, s5 = rsi(c), c.rolling(200).mean(), c.rolling(5).mean()
        i = 200
        idx = c.index
        while i < len(c) - 1:
            if rs.iloc[i] < 5 and c.iloc[i] > s200.iloc[i]:
                j = i + 1
                while j < len(c) - 1 and j - i < 10 and not (c.iloc[j] > s5.iloc[j]):
                    j += 1
                trades.append({"ticker": t, "entry": idx[i], "entry_at": "close", "exit": idx[j], "exit_at": "close",
                               "side": 1, "rsi": -float(rs.iloc[i])})
                i = j + 1
            else:
                i += 1
    record("rsi2_mega", pd.DataFrame(trades), slots=10, rank="rsi")

    open(out_path("research_equity.json"), "w").write(json.dumps(out, default=str))
    print("EQUITY_DONE", flush=True)


if __name__ == "__main__":
    main()
