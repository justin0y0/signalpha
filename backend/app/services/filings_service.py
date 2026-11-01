"""A company's reported numbers and its original documents, straight from the SEC.

Numbers: XBRL "company facts" (data.sec.gov/api/xbrl/companyfacts). Each concept is a
list of reported values with a period; this turns them into quarters:
  * a value whose period is about three months is a quarter as filed;
  * cash-flow items are filed year-to-date (6M, 9M), so consecutive YTD values from the
    same fiscal-year start are differenced into quarters;
  * Q4 is rarely filed on its own — it is the fiscal year minus the first three quarters
    (marked `derived`; for EPS that is approximate, since the share count moves).
A concept can change name over the years (Apple's revenue moved from `Revenues` to
`RevenueFromContractWithCustomerExcludingAssessedTax`), so every alias is merged, the
most recently filed value winning. Foreign private issuers file only annual XBRL (20-F,
IFRS); their quarters come as 6-K documents without tagged numbers, so only annual rows.

Documents: the filing list (data.sec.gov/submissions). For earnings releases (8-K Item
2.02, and 6-K for foreign filers) the filing index is read for its exhibits — the press
release (EX-99.1), slides or supplements (EX-99.2…), PDFs flagged — and cached for good,
since a filed document never changes. Everything links to the SEC's own copy.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.services.schedule_service import UA, _cik, _redis

SEC = "https://www.sec.gov"

# output field -> XBRL concepts (us-gaap first, then IFRS), merged in this order
CONCEPTS: dict[str, list[str]] = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense",
                "InterestAndDividendIncomeOperating", "InterestIncomeOperating", "InterestAndFeeIncomeLoansAndLeases",
                "Revenue"],
    "gross_profit": ["GrossProfit"],
    "op_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "eps_diluted": ["EarningsPerShareDiluted", "DilutedEarningsLossPerShare", "EarningsPerShareBasicAndDiluted"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets", "PaymentsForCapitalImprovements",
              "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
}
EARNINGS_FORMS = {"8-K", "6-K"}
PERIODIC_FORMS = {"10-Q", "10-K", "20-F", "40-F", "10-K/A", "10-Q/A"}


def _get(url: str, timeout: float = 25) -> httpx.Response:
    return httpx.get(url, headers=UA, timeout=timeout, follow_redirects=True)


def _cached(key: str, ttl: int, fn):
    try:
        hit = _redis().get(key)
        if hit:
            return json.loads(hit)
    except Exception:  # noqa: BLE001
        pass
    val = fn()
    try:
        _redis().set(key, json.dumps(val), ex=ttl)
    except Exception:  # noqa: BLE001
        pass
    return val


# ───────────────────────────── numbers ─────────────────────────────

def _d(s: str) -> date:
    return date.fromisoformat(s)


def _series(facts: dict, names: list[str], currency: str | None) -> tuple[dict, str | None]:
    """{(start, end): value} for duration facts (instants are skipped), aliases merged."""
    out: dict[tuple[str, str], tuple[str, float]] = {}
    unit_used = None
    for ns in ("us-gaap", "ifrs-full"):
        for name in names:
            units = (facts.get(ns, {}).get(name) or {}).get("units") or {}
            if not units:
                continue
            # prefer the reporting currency (or USD for per-share), else the first unit
            keys = sorted(units, key=lambda u: (0 if currency and u.startswith(currency) else 1, u))
            unit = keys[0]
            unit_used = unit_used or unit
            for f in units[unit]:
                if "start" not in f or f.get("form") not in PERIODIC_FORMS | {"8-K", "6-K"}:
                    continue
                k = (f["start"], f["end"])
                if k not in out or f.get("filed", "") > out[k][0]:
                    out[k] = (f.get("filed", ""), float(f["val"]))
    return {k: v for k, (_, v) in out.items()}, unit_used


def _quarters(series: dict[tuple[str, str], float]) -> dict[str, dict[str, Any]]:
    """{quarter end: {"start", "val", "derived"}} from filed quarters, YTD differences and FY − Q1..Q3."""
    q: dict[str, dict[str, Any]] = {}
    ytd: dict[str, list[tuple[str, float]]] = {}
    for (s, e), v in series.items():
        days = (_d(e) - _d(s)).days
        if 80 <= days <= 100:
            q[e] = {"start": s, "val": v, "derived": False}
        if days >= 80:
            ytd.setdefault(s, []).append((e, v))
    for s, rows in ytd.items():
        rows.sort()
        for (e1, v1), (e2, v2) in zip(rows, rows[1:]):
            gap = (_d(e2) - _d(e1)).days
            if 80 <= gap <= 100 and e2 not in q:
                q[e2] = {"start": (_d(e1) + timedelta(days=1)).isoformat(), "val": v2 - v1, "derived": True}
    for (s, e), v in series.items():
        if 350 <= (_d(e) - _d(s)).days <= 380 and e not in q:
            inside = [x for k, x in q.items() if s <= x["start"] and k < e]
            if len(inside) == 3:
                q[e] = {"start": (_d(max(k for k, x in q.items() if s <= x["start"] and k < e)) + timedelta(days=1)).isoformat(),
                        "val": v - sum(x["val"] for x in inside), "derived": True}
    return q


def _annual(series: dict[tuple[str, str], float]) -> dict[str, float]:
    return {e: v for (s, e), v in series.items() if 350 <= (_d(e) - _d(s)).days <= 380}


def financials(ticker: str) -> dict[str, Any] | None:
    cik = _cik(ticker)
    if not cik:
        return None

    def build():
        r = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        if r.status_code != 200:
            return {"cik": cik, "quarters": [], "annual": [], "currency": None}
        body = r.json()
        facts = body.get("facts", {})
        # reporting currency: the unit most revenue facts use
        cur = None
        for ns in ("us-gaap", "ifrs-full"):
            for name in CONCEPTS["revenue"]:
                units = (facts.get(ns, {}).get(name) or {}).get("units") or {}
                if units:
                    cur = max(units, key=lambda u: len(units[u]))
                    break
            if cur:
                break
        cols: dict[str, dict] = {}
        ann: dict[str, dict] = {}
        for field, names in CONCEPTS.items():
            ser, _ = _series(facts, names, cur if field != "eps_diluted" else (cur or "USD"))
            cols[field] = _quarters(ser)
            ann[field] = _annual(ser)
        ends = sorted({e for c in cols.values() for e in c}, reverse=True)[:12]
        quarters = []
        for e in ends:
            row: dict[str, Any] = {"end": e, "derived": []}
            for f, c in cols.items():
                x = c.get(e)
                row[f] = (round(x["val"], 4) if f == "eps_diluted" else x["val"]) if x else None
                if x and x["derived"]:
                    row["derived"].append(f)
            if row["revenue"] is None and row["net_income"] is None:
                continue
            quarters.append(row)
        # year-over-year revenue: the quarter ending ~a year earlier
        by_end = {q["end"]: q for q in quarters}
        for q in quarters:
            prev = next((p for e, p in by_end.items() if 350 <= (_d(q["end"]) - _d(e)).days <= 380), None)
            if prev is None:
                prev_v = next((x["val"] for e, x in cols["revenue"].items() if 350 <= (_d(q["end"]) - _d(e)).days <= 380), None)
            else:
                prev_v = prev["revenue"]
            q["revenue_yoy"] = (q["revenue"] / prev_v - 1) if q["revenue"] and prev_v else None
            q["gross_margin"] = (q["gross_profit"] / q["revenue"]) if q["gross_profit"] is not None and q["revenue"] else None
            q["fcf"] = (q["ocf"] - q["capex"]) if q["ocf"] is not None and q["capex"] is not None else None
        aends = sorted({e for c in ann.values() for e in c}, reverse=True)[:5]
        annual = [{"end": e, **{f: ann[f].get(e) for f in CONCEPTS}} for e in aends]
        return {"cik": cik, "name": body.get("entityName"), "currency": cur, "quarters": quarters, "annual": annual}

    return _cached(f"fin:facts:{cik}", 6 * 3600, build)


# ───────────────────────────── documents ─────────────────────────────

def _exhibits(cik: str, acc: str) -> list[dict[str, Any]]:
    """The documents inside one filing (type, description, link), from its index page."""
    def build():
        nodash = acc.replace("-", "")
        r = _get(f"{SEC}/Archives/edgar/data/{int(cik)}/{nodash}/{acc}-index.htm")
        if r.status_code != 200:
            return []
        out = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            link = re.search(r'href="(/Archives/edgar/data/[^"]+)"', row)
            if len(cells) < 4 or not link:
                continue
            desc = re.sub("<[^>]+>", "", cells[1]).strip()
            typ = re.sub("<[^>]+>", "", cells[3]).strip()
            href = link.group(1).replace("/ix?doc=", "")
            if not typ.upper().startswith("EX-") or typ.upper().startswith("EX-101") \
                    or href.endswith((".jpg", ".png", ".gif", ".xml", ".xsd")):
                continue
            out.append({"type": typ, "desc": desc[:120], "url": SEC + href, "pdf": href.lower().endswith(".pdf")})
        return out[:12]
    return _cached(f"fin:ex:{acc}", 86400 * 365, build)


def documents(ticker: str, limit: int = 24, report_dates: list[date] | None = None) -> dict[str, Any] | None:
    cik = _cik(ticker)
    if not cik:
        return None

    def build():
        r = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
        if r.status_code != 200:
            return {"cik": cik, "filings": []}
        f = r.json().get("filings", {}).get("recent", {})
        rows = []
        for i, form in enumerate(f.get("form", [])):
            items = (f.get("items") or [""] * len(f["form"]))[i] or ""
            earnings = (form == "8-K" and "2.02" in items) or form == "6-K"
            if not (earnings or form in PERIODIC_FORMS):
                continue
            acc, doc = f["accessionNumber"][i], f["primaryDocument"][i]
            nodash = acc.replace("-", "")
            rows.append({"form": form, "kind": "earnings" if earnings else "annual" if form in ("10-K", "20-F", "40-F", "10-K/A") else "quarterly",
                         "filed": f["filingDate"][i], "accepted": f["acceptanceDateTime"][i], "period": f["reportDate"][i] or None,
                         "accession": acc, "desc": (f.get("primaryDocDescription") or [""] * len(f["form"]))[i],
                         "url": f"{SEC}/Archives/edgar/data/{int(cik)}/{nodash}/{doc}",
                         "index": f"{SEC}/Archives/edgar/data/{int(cik)}/{nodash}/{acc}-index.htm"})
        # foreign filers send many 6-Ks (notices, votes); keep the ones near a reported period
        return {"cik": cik, "filings": rows[:80]}

    body = _cached(f"fin:docs:{cik}", 3 * 3600, build)
    rows = body.get("filings", [])
    sixk = [r for r in rows if r["form"] == "6-K"]
    if sixk:   # a foreign filer sends 6-Ks for everything; keep those filed 0-4 days after a report
        near = lambda d: any(0 <= (_d(d) - rd).days <= 4 for rd in (report_dates or []))  # noqa: E731
        rows = [r for r in rows if r["form"] != "6-K" or near(r["filed"])
                or re.search(r"result|earning|quarter", r["desc"] or "", re.I)]
    rows = rows[:limit]
    for r in rows:
        if r["kind"] == "earnings":
            r["exhibits"] = _exhibits(cik, r["accession"])
    return {"cik": cik, "filings": rows,
            "browse": f"{SEC}/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&dateb=&owner=include&count=40"}


def company(db: Session, ticker: str) -> dict[str, Any]:
    t = ticker.upper()
    fin = financials(t) or {"quarters": [], "annual": [], "currency": None}
    est = [dict(r) for r in db.execute(text("""SELECT report_date, eps_estimate, eps_actual, surprise_pct, report_time
                                              FROM earnings_surprises WHERE ticker=:t AND eps_actual IS NOT NULL
                                              ORDER BY report_date DESC LIMIT 12"""), {"t": t}).mappings()]
    dates = [r["report_date"] for r in est] + [r[0] for r in db.execute(text(
        "SELECT earnings_date FROM earnings_events WHERE ticker=:t AND earnings_date <= CURRENT_DATE"), {"t": t}).all()]
    docs = documents(t, report_dates=dates) or {"filings": []}
    for r in est:
        r["report_date"] = str(r["report_date"])
        for k in ("eps_estimate", "eps_actual", "surprise_pct"):
            r[k] = float(r[k]) if r[k] is not None and r[k] == r[k] else None
    return {"ticker": t, "cik": fin.get("cik") or docs.get("cik"), "name": fin.get("name"), "currency": fin.get("currency"),
            "quarters": fin.get("quarters", []), "annual": fin.get("annual", []), "estimates": est,
            "filings": docs.get("filings", []), "browse": docs.get("browse"),
            "source": "SEC EDGAR — XBRL company facts and filing indexes"}
