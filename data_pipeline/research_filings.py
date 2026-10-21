"""Rules built on SEC filings — the same filings the Oracle desk watches.

  insider_cluster   Lakonishok & Lee (2001); Alldredge & Blank (2019): when three or more
                    different officers or directors of one company make open-market purchases
                    (Form 4, code P) within 30 days, buy at the next session's open after the
                    filing that completes the cluster; hold 21 sessions. One signal per company
                    per 60 days. Companies in the platform's universe (US, above $300M today).
  clone_<manager>   Copying 13F holdings, Martin & Puthenpurackal (2008) for Berkshire: on the
                    session after each 13F-HR is filed, hold the manager's ten largest reported
                    stock positions equally weighted until the next filing. Managers: the three
                    the Oracle desk follows through EDGAR — Berkshire Hathaway (Buffett), Pershing
                    Square (Ackman), Scion (Burry). 13F lags the quarter by up to 45 days; that
                    delay is in the test.

Data: SEC Insider Transactions Data Sets (quarterly, 2015 Q3 on) and EDGAR 13F-HR information
tables; CUSIPs to tickers through OpenFIGI; prices from Alpaca SIP daily (adjusted). Costs:
10 bp round trip.

    python -m data_pipeline.research_filings     # writes $DATA_DIR/research_filings.json
"""
from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from data_pipeline.research_common import alpaca_daily, curve, event_sleeve, ew_index, out_path, summary, tstat

UA = {"User-Agent": os.getenv("SEC_USER_AGENT") or "Signalpha-research contact@signalpha.app"}
CACHE = Path(os.getenv("DATA_DIR", "/app/data")) / "sec_cache"
MANAGERS = {"buffett": ("1067983", "Berkshire Hathaway"), "ackman": ("1336528", "Pershing Square"),
            "burry": ("1649339", "Scion Asset Management")}
COST = 0.001
START = "2015-06-01"


def sec_get(url: str) -> bytes:
    for attempt in range(5):
        try:
            r = httpx.get(url, headers=UA, timeout=60, follow_redirects=True)
        except httpx.HTTPError:
            time.sleep(2 + attempt * 2)
            continue
        time.sleep(0.15)  # SEC fair access: well under 10 requests a second
        if r.status_code == 200:
            return r.content
        if r.status_code in (403, 429):
            time.sleep(10)
            continue
        return b""
    return b""


# ───────────────────────── insiders ─────────────────────────

def insider_buys() -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    rows = []
    now = pd.Timestamp.now()
    q = [(y, k) for y in range(2015, now.year + 1) for k in range(1, 5) if (y, k) >= (2015, 3) and pd.Timestamp(year=y, month=3 * k, day=1) < now]
    for y, k in q:
        path = CACHE / f"{y}q{k}_form345.zip"
        if not path.exists():
            data = sec_get(f"https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{y}q{k}_form345.zip")
            if not data:
                print(f"insider {y}q{k}: not published", flush=True)
                continue
            path.write_bytes(data)
        z = zipfile.ZipFile(path)
        rd = lambda n, cols: pd.read_csv(z.open(n), sep="\t", usecols=cols, dtype=str, on_bad_lines="skip", quoting=3)  # noqa: E731
        sub = rd("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERTRADINGSYMBOL"])
        sub = sub[sub.DOCUMENT_TYPE == "4"]
        tr = rd("NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                                       "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"])
        tr = tr[(tr.TRANS_CODE == "P") & (tr.TRANS_ACQUIRED_DISP_CD == "A")]
        own = rd("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"])
        own = own[own.RPTOWNER_RELATIONSHIP.fillna("").str.contains("Director|Officer", regex=True)]
        m = tr.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER")
        m["value"] = pd.to_numeric(m.TRANS_SHARES, errors="coerce") * pd.to_numeric(m.TRANS_PRICEPERSHARE, errors="coerce")
        rows.append(m[["ISSUERTRADINGSYMBOL", "RPTOWNERCIK", "FILING_DATE", "TRANS_DATE", "value"]])
        print(f"insider {y}q{k}: {len(m)} open-market purchases by officers/directors", flush=True)
    d = pd.concat(rows, ignore_index=True)
    d["ticker"] = d.ISSUERTRADINGSYMBOL.fillna("").str.upper().str.strip().str.replace(".", "-", regex=False)
    d["filed"] = pd.to_datetime(d.FILING_DATE, format="%d-%b-%Y", errors="coerce")
    d["traded"] = pd.to_datetime(d.TRANS_DATE, format="%d-%b-%Y", errors="coerce")
    return d.dropna(subset=["filed", "traded"])


def clusters(d: pd.DataFrame, tickers: set[str]) -> pd.DataFrame:
    """The filing that makes it three distinct insiders buying within 30 days; one per 60 days."""
    d = d[d.ticker.isin(tickers) & (d.value >= 10_000)].sort_values("filed")
    out = []
    for t, g in d.groupby("ticker"):
        last = None
        for f in sorted(g.filed.unique()):
            f = pd.Timestamp(f)
            if last is not None and (f - last).days < 60:
                continue
            w = g[(g.filed <= f) & (g.traded >= f - pd.Timedelta(days=30))]
            if w.RPTOWNERCIK.nunique() >= 3:
                out.append({"ticker": t, "filed": f, "insiders": int(w.RPTOWNERCIK.nunique()), "value": float(w.value.sum())})
                last = f
    return pd.DataFrame(out)


# ───────────────────────── 13F ─────────────────────────

def filings_13f(cik: str) -> list[dict]:
    body = json.loads(sec_get(f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json") or b"{}")
    out = []
    blocks = [body.get("filings", {}).get("recent", {})]
    for f in body.get("filings", {}).get("files", []):
        blocks.append(json.loads(sec_get("https://data.sec.gov/submissions/" + f["name"]) or b"{}"))
    for b in blocks:
        for form, acc, filed, rep in zip(b.get("form", []), b.get("accessionNumber", []), b.get("filingDate", []),
                                         b.get("reportDate", [])):
            if form == "13F-HR" and filed >= "2015-01-01":
                out.append({"acc": acc, "filed": filed, "period": rep})
    return sorted(out, key=lambda x: x["filed"])


def holdings(cik: str, acc: str) -> pd.DataFrame:
    path = CACHE / f"13f_{cik}_{acc}.json"
    if path.exists():
        return pd.DataFrame(json.loads(path.read_text()))
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}"
    idx = json.loads(sec_get(base + "/index.json") or b"{}")
    xmls = [i["name"] for i in idx.get("directory", {}).get("item", []) if i["name"].lower().endswith(".xml")
            and "primary_doc" not in i["name"].lower()]
    rows = []
    for x in xmls:
        raw = sec_get(f"{base}/{x}").decode("utf-8", "ignore")
        raw = re.sub(r"<(/?)[\w]+:", r"<\1", raw)  # drop namespaces
        for it in re.findall(r"<infoTable>(.*?)</infoTable>", raw, re.S):
            g = lambda tag: (re.search(f"<{tag}>(.*?)</{tag}>", it, re.S) or [None, ""])[1].strip()  # noqa: E731
            if g("putCall"):
                continue
            rows.append({"cusip": g("cusip").upper(), "name": g("nameOfIssuer"), "value": float(g("value") or 0)})
    path.write_text(json.dumps(rows))
    return pd.DataFrame(rows)


def figi(cusips: list[str]) -> dict[str, str]:
    path = CACHE / "figi.json"
    known = json.loads(path.read_text()) if path.exists() else {}
    todo = [c for c in sorted(set(cusips)) if c not in known]
    for i in range(0, len(todo), 10):
        chunk = todo[i:i + 10]
        try:
            r = httpx.post("https://api.openfigi.com/v3/mapping", timeout=30,
                           json=[{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in chunk])
            res = r.json() if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            res = []
        for c, item in zip(chunk, res):
            data = (item or {}).get("data") or []
            eq = [x for x in data if x.get("marketSector") == "Equity"] or data
            known[c] = (eq[0].get("ticker") or "").replace("/", "-").replace(" ", "-") if eq else ""
        time.sleep(2.6)  # 25 requests a minute without a key
    path.write_text(json.dumps(known))
    return known


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        uni = set(pd.read_sql(text("SELECT ticker FROM universe WHERE tier IN ('core','large','mid','small')"), db.bind).ticker)
    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "cost": COST, "rules": {}}

    ins = insider_buys()
    cl = clusters(ins, uni)
    print(f"insider clusters: {len(cl)}", flush=True)

    plans: dict[str, list[dict]] = {}
    tick_13f: set[str] = set()
    for key, (cik, name) in MANAGERS.items():
        fl = filings_13f(cik)
        h_all = []
        for f in fl:
            h = holdings(cik, f["acc"])
            if h.empty:
                continue
            h = h.groupby("cusip", as_index=False).agg(value=("value", "sum"), name=("name", "first"))
            h_all.append((f, h))
        mp = figi([c for _, h in h_all for c in h.cusip])
        plan = []
        for f, h in h_all:
            h["ticker"] = h.cusip.map(mp).fillna("")
            h = h[h.ticker != ""].sort_values("value", ascending=False)
            top = list(dict.fromkeys(h.ticker))[:10]
            plan.append({"filed": f["filed"], "period": f["period"], "top": top})
            tick_13f |= set(top)
        plans[key] = plan
        print(f"13F {key}: {len(plan)} filings, latest {plan[-1]['filed'] if plan else None} top {plan[-1]['top'] if plan else None}", flush=True)

    names = sorted(set(cl.ticker) | tick_13f | uni | {"SPY"})
    O, C = alpaca_daily(names, START)
    days = C.index
    spy = C.SPY.pct_change().fillna(0)
    ew = ew_index(C, sorted(uni))
    out["ew_universe"] = summary(ew.pct_change().fillna(0), spy)
    print(f"EW universe (large/mid/small) CAGR {out['ew_universe']['cagr']*100:+.1f}% vs SPY {out['ew_universe']['spy_cagr']*100:+.1f}%", flush=True)

    def nxt(d: pd.Timestamp) -> pd.Timestamp | None:
        k = days.searchsorted(d, side="right")
        return days[k] if k < len(days) else None

    def record(key: str, trades: pd.DataFrame, slots: int, extra: dict | None = None) -> None:
        r, taken = event_sleeve(trades, C, O, slots, COST)
        r = r[r.index >= r.ne(0).idxmax()]
        ex, ex_ew = [], []
        for t in taken.itertuples():
            try:
                ex.append(t.ret - (C.SPY.loc[t.exit] / O.SPY.loc[t.entry] - 1))
                k = days.get_loc(t.entry)
                ex_ew.append(t.ret - (ew.loc[t.exit] / ew.iloc[max(k - 1, 0)] - 1))
            except KeyError:
                pass
        body = {"all": summary(r, spy), "per_trade": tstat(taken.ret) if len(taken) else {}, "excess": tstat(ex),
                "excess_ew": tstat(ex_ew),
                "signals": int(len(trades)), "taken": int(len(taken)), "slots": slots, **curve(r, spy)}
        body.update(extra or {})
        out["rules"][key] = body
        a, e = body["all"], body["excess"]
        print(f"{key:16s} CAGR {a.get('cagr', 0)*100:+.1f}% vs SPY {a.get('spy_cagr', 0)*100:+.1f}% DD {a.get('max_dd', 0)*100:.0f}% "
              f"Sharpe {a.get('sharpe') or 0:.2f} vs {a.get('spy_sharpe') or 0:.2f} | excess {e.get('mean', 0)*100:+.2f}% t={e.get('t') or 0:+.1f} "
              f"| vs EW {body['excess_ew'].get('mean', 0)*100:+.2f}% t={body['excess_ew'].get('t') or 0:+.1f} n={e.get('n')}", flush=True)

    tr = []
    for c in cl.itertuples():
        e = nxt(c.filed)
        if e is None:
            continue
        k = days.get_loc(e)
        for hold, tag in ((21, "21"),):
            if k + hold < len(days):
                tr.append({"ticker": c.ticker, "entry": e, "entry_at": "open", "exit": days[k + hold], "exit_at": "close", "side": 1})
    record("insider_cluster", pd.DataFrame(tr), slots=10,
           extra={"recent": cl.sort_values("filed").tail(10).assign(filed=lambda x: x.filed.astype(str)).to_dict("records")})

    for key, plan in plans.items():
        tr = []
        for a, b in zip(plan, plan[1:] + [None]):
            e = nxt(pd.Timestamp(a["filed"]))
            x = nxt(pd.Timestamp(b["filed"])) if b else days[-1]
            if e is None or x is None or x <= e:
                continue
            for t in a["top"]:
                tr.append({"ticker": t, "entry": e, "entry_at": "open", "exit": x, "exit_at": "open" if b else "close", "side": 1})
        record(f"clone_{key}", pd.DataFrame(tr), slots=10, extra={"manager": MANAGERS[key][1],
                                                                  "latest": plan[-1] if plan else None})

    open(out_path("research_filings.json"), "w").write(json.dumps(out, default=str))
    print("FILINGS_DONE", flush=True)


if __name__ == "__main__":
    main()
