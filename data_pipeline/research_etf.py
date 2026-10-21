"""Market-timing and ETF-rotation rules from the literature, on total-return ETF data.

Each rule is the one the paper published — no parameter was chosen here — and each is
shown over the whole sample and over the years after its publication.

  trend      Faber (2007), "A Quantitative Approach to Tactical Asset Allocation": at each
             month-end hold SPY if it closes above its 10-month average, else T-bills.
  gem        Antonacci (2014), Dual Momentum / Global Equities Momentum: at month-end, if
             SPY's 12-month return beats T-bills', hold the better of SPY and EFA over 12
             months; otherwise hold AGG.
  sectors    Moskowitz & Grinblatt (1999) industry momentum, as ETFs (Faber 2010): at month-
             end hold the three of the nine original sector SPDRs with the best 6 months.
  tom        Turn of the month, Lakonishok & Smidt (1988), McConnell & Xu (2008): hold SPY from
             the close two sessions before month-end to the close of the third session of the
             new month; T-bills otherwise.
  overnight  Cliff, Cooper & Gulen (2008): hold SPY from each close to the next open only.
  rsi2       Connors & Alvarez (2008): buy SPY at the close when RSI(2) < 10 and it is above its
             200-day average; sell at the close once it closes above its 5-day average.
  fomc       Lucca & Moench (2015), pre-FOMC drift: hold SPY from the close before each
             scheduled FOMC decision day to that day's close.

Costs: 1 bp a side for SPY and the bond/T-bill ETFs, 3 bp a side for sector and
international ETFs; overnight pays 1 bp per round trip (closing and opening auctions).
T-bill parking uses BIL (from its 2007 launch) and the 13-week bill rate before that.

    python -m data_pipeline.research_etf     # writes $DATA_DIR/research_etf.json
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import httpx
import numpy as np
import pandas as pd

from data_pipeline.research_common import curve, out_path, summary, yf_daily

SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
PUBLISHED = {"trend": "2007-01-01", "gem": "2015-01-01", "sectors": "2000-01-01", "tom": "2009-01-01",
             "overnight": "2009-01-01", "rsi2": "2009-01-01", "fomc": "2015-01-01"}


def rsi(c: pd.Series, n: int = 2) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def fomc_dates() -> list[pd.Timestamp]:
    """Scheduled FOMC decision days (the last day of each meeting) from the Fed's own pages."""
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
              "October", "November", "December"]
    mo = {m: i + 1 for i, m in enumerate(months)} | {m[:3]: i + 1 for i, m in enumerate(months)}
    out = set()

    def get(url: str) -> str:
        try:
            return httpx.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).text
        except Exception:  # noqa: BLE001
            return ""
    # 2000-2020: one page a year, headings like "July 31-August 1 Meeting"
    for y in range(2000, 2021):
        html = get(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm")
        rx = r"(" + "|".join(months) + r")\s+(\d{1,2})(?:\s*-\s*(?:(" + "|".join(months) + r")\s+)?(\d{1,2}))?\s+Meeting"
        for m1, d1, m2, d2 in re.findall(rx, html):
            m, d = (m2 or m1), int(d2 or d1)
            out.add(pd.Timestamp(year=y, month=mo[m], day=d))
    # 2021 onwards: the current calendar page, sections "2025 FOMC Meetings"
    html = get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
    parts = re.split(r"(\d{4}) FOMC Meetings", html)
    for k in range(1, len(parts) - 1, 2):
        y = int(parts[k])
        cells = re.findall(r"fomc-meeting__month[^>]*><strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<", parts[k + 1], re.S)
        for m, d in cells:
            names = [x.strip() for x in m.split("/")]
            nums = re.findall(r"\d{1,2}", d)
            if not nums or names[-1] not in mo:
                continue
            last = int(nums[-1])
            month = mo[names[-1]] if len(names) > 1 and len(nums) > 1 and int(nums[-1]) < int(nums[0]) else mo[names[0]] if names[0] in mo else mo[names[-1]]
            try:
                out.add(pd.Timestamp(year=y, month=month, day=last))
            except ValueError:
                pass
    return sorted(out)


def main() -> None:
    tick = ["SPY", "EFA", "AGG", "BIL", "^IRX"] + SECTORS
    O, C = yf_daily(tick, start="1993-01-01")
    C = C.dropna(how="all")
    spy_c, spy_o = C.SPY.dropna(), O.SPY.dropna()
    days = spy_c.index
    spy = spy_c.pct_change().fillna(0)
    irx = (C["^IRX"].reindex(days).ffill() / 100 / 252).shift(1).fillna(0)
    bil = C.BIL.reindex(days).pct_change()
    cash = bil.where(bil.notna(), irx).fillna(0)
    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "rules": {}}

    def record(key: str, r: pd.Series, extra: dict | None = None) -> None:
        r = r.reindex(days).fillna(0)
        start = r.ne(0).idxmax()
        r = r[r.index >= start]
        body = {"all": summary(r, spy), "post": summary(r, spy, since=PUBLISHED[key]), "published": PUBLISHED[key],
                **curve(r, spy)}
        body.update(extra or {})
        out["rules"][key] = body
        a, p = body["all"], body["post"]
        print(f"{key:9s} all {a['start']} CAGR {a['cagr']*100:+.1f}% vs SPY {a['spy_cagr']*100:+.1f}% | DD {a['max_dd']*100:.0f}% vs {a['spy_max_dd']*100:.0f}% "
              f"| Sharpe {a['sharpe']:.2f} vs {a['spy_sharpe']:.2f} | expo {a['exposure']*100:.0f}% || post CAGR {p['cagr']*100:+.1f}% vs {p['spy_cagr']*100:+.1f}% "
              f"Sharpe {p['sharpe']:.2f} vs {p['spy_sharpe']:.2f} DD {p['max_dd']*100:.0f}%", flush=True)

    month_end = spy_c.groupby([days.year, days.month]).tail(1).index
    is_me = pd.Series(days.isin(month_end), index=days)

    # ── trend: Faber 10-month SMA on month-end closes; decided at the month-end close
    me = spy_c.loc[month_end]
    sig_me = (me > me.rolling(10).mean()).astype(float)
    hold = sig_me.reindex(days).ffill().shift(1).fillna(0)  # position held during each day
    sw = hold.diff().abs().fillna(0)
    r = hold * spy + (1 - hold) * cash - sw * 0.0002
    record("trend", r, {"now": {"in_market": bool(sig_me.iloc[-1]), "sma10": float(me.rolling(10).mean().iloc[-1]),
                                "spy": float(spy_c.iloc[-1])}})

    # ── GEM
    efa, agg = C.EFA.reindex(days), C.AGG.reindex(days)
    ok = efa.notna() & agg.notna()
    lb = 252
    r12 = lambda s: s / s.shift(lb) - 1  # noqa: E731
    tb12 = (1 + cash).rolling(lb).apply(np.prod, raw=True) - 1
    choice = pd.Series(np.nan, index=days, dtype=object)
    for d in month_end:
        if not ok.get(d, False) or pd.isna(r12(efa).get(d)) or pd.isna(tb12.get(d)):
            continue
        s12, e12 = r12(spy_c).get(d), r12(efa).get(d)
        choice[d] = ("SPY" if s12 >= e12 else "EFA") if s12 > tb12[d] else "AGG"
    held = choice.ffill().shift(1)
    rets = {"SPY": spy, "EFA": efa.pct_change(), "AGG": agg.pct_change()}
    r = pd.Series(0.0, index=days)
    for k, v in rets.items():
        r += (held == k).astype(float) * v.fillna(0)
    sw = (held != held.shift(1)) & held.notna() & held.shift(1).notna()
    r -= sw.astype(float) * 0.0004
    record("gem", r[held.notna()], {"now": {"holding": choice.dropna().iloc[-1] if choice.notna().any() else None}})

    # ── sector momentum: top 3 of 9 by 6-month return, monthly
    sc = C[SECTORS].reindex(days)
    sr = sc.pct_change()
    w = pd.DataFrame(0.0, index=days, columns=SECTORS)
    picks = {}
    for d in month_end:
        m6 = sc.loc[d] / sc.shift(126).loc[d] - 1
        if m6.notna().sum() < 9:
            continue
        top = list(m6.sort_values(ascending=False).index[:3])
        picks[d] = top
        w.loc[d, top] = 1 / 3
    wd = w.loc[sorted(picks)].reindex(days).ffill().shift(1).fillna(0)
    turn = wd.diff().abs().sum(axis=1).fillna(0)
    r = (wd * sr.fillna(0)).sum(axis=1) - turn * 0.0003
    record("sectors", r[wd.sum(axis=1) > 0], {"now": {"holding": picks[max(picks)] if picks else []}})

    # ── turn of the month: in SPY over sessions -1 .. +3 (bought at the close of session -2)
    pos_in_month = days.to_series().groupby([days.year, days.month]).cumcount()
    from_end = days.to_series().groupby([days.year, days.month]).cumcount(ascending=False)
    window = (from_end == 0) | (pos_in_month <= 2)  # returns earned on these days
    hold = window.astype(float)
    sw = hold.diff().abs().fillna(0)
    r = hold * spy + (1 - hold) * cash - sw * 0.0002
    record("tom", r)

    # ── overnight: close -> next open, every session
    on = (spy_o / spy_c.shift(1) - 1).reindex(days).fillna(0)
    intraday = (spy_c / spy_o - 1).reindex(days).fillna(0)
    r = on - 0.0001
    record("overnight", r, {"intraday_all": summary(intraday, spy)})

    # ── RSI(2)
    rs, sma200, sma5 = rsi(spy_c), spy_c.rolling(200).mean(), spy_c.rolling(5).mean()
    pos_ = np.zeros(len(days))
    inpos = False
    for i in range(len(days)):
        if not inpos and rs.iloc[i] < 10 and spy_c.iloc[i] > sma200.iloc[i]:
            inpos = True
        elif inpos and spy_c.iloc[i] > sma5.iloc[i]:
            inpos = False
        pos_[i] = 1.0 if inpos else 0.0
    hold = pd.Series(pos_, index=days).shift(1).fillna(0)
    sw = hold.diff().abs().fillna(0)
    r = hold * spy + (1 - hold) * cash - sw * 0.0002
    trades = int((hold.diff() == 1).sum())
    record("rsi2", r, {"trades": trades, "now": {"rsi2": float(rs.iloc[-1]), "above_200": bool(spy_c.iloc[-1] > sma200.iloc[-1])}})

    # ── pre-FOMC: close before decision day -> decision-day close
    fd = [d for d in fomc_dates() if d in set(days)]
    print(f"fomc days found: {len(fd)} ({fd[0].date() if fd else None} .. {fd[-1].date() if fd else None})", flush=True)
    if len(fd) > 60:
        hold = pd.Series(days.isin(fd).astype(float), index=days)
        sw = hold.diff().abs().fillna(0)
        r = hold * spy + (1 - hold) * cash - sw * 0.0002
        record("fomc", r, {"events": len(fd),
                           "event_ret": {"all": float(spy[hold == 1].mean()),
                                         "post": float(spy[(hold == 1) & (days >= PUBLISHED['fomc'])].mean())}})
    open(out_path("research_etf.json"), "w").write(json.dumps(out))
    print("ETF_DONE", flush=True)


if __name__ == "__main__":
    main()
