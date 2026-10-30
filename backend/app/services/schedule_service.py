"""When a company reports: its last and next earnings, to the minute where that is knowable.

Last report: the SEC's acceptance time of the 8-K with Item 2.02 ("Results of Operations")
filed around the report date — the release itself reaches EDGAR within minutes of the
press wire, and EDGAR stamps it to the second. Yahoo's calendar time is the fallback
(it rounds after-close reports to 16:00). The model's call on that report comes from the
Earnings Arena, sealed (hashed and timestamped) before the release, and the result from
the outcomes table.

Next report: Yahoo's calendar. Companies rarely publish the minute in advance, and
Yahoo fills unconfirmed times with a placeholder (15:00), so a placeholder is reported as
"time not confirmed" with the session the company has used in its last reports.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

ET = ZoneInfo("America/New_York")
UA = {"User-Agent": os.getenv("SEC_USER_AGENT", "SignAlpha research contact@signalpha.app")}
_tickers: dict[str, Any] = {"at": 0.0, "map": {}}


def _redis():
    from backend.app.services.ap_auth import _redis as r
    return r()


def _f(x: Any) -> float | None:
    """A float for JSON, or None (NaN is not valid JSON)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def session_of(ts: datetime) -> str:
    t = ts.astimezone(ET)
    if (t.hour, t.minute) < (9, 30):
        return "BMO"
    if t.hour >= 16:
        return "AMC"
    return "DMH"


def _cik(ticker: str) -> str | None:
    if time.time() - _tickers["at"] > 86400 or not _tickers["map"]:
        try:
            body = httpx.get("https://www.sec.gov/files/company_tickers.json", headers=UA, timeout=20).json()
            _tickers["map"] = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in body.values()}
            _tickers["title"] = {v["ticker"].upper(): v.get("title", "") for v in body.values()}
            _tickers["at"] = time.time()
        except Exception:  # noqa: BLE001
            pass
    return _tickers["map"].get(ticker.upper().replace(".", "-")) or _tickers["map"].get(ticker.upper().replace("-", "."))


def sec_title(ticker: str) -> str | None:
    """The company's name as registered with the SEC (None for a non-registrant)."""
    if _cik(ticker) is None:
        return None
    t = _tickers.get("title", {})
    return t.get(ticker.upper().replace(".", "-")) or t.get(ticker.upper().replace("-", "."))


def sec_release(ticker: str, around: date) -> dict | None:
    """The 8-K Item 2.02 filed within two days of `around`: acceptance time and link."""
    key = f"sched:8k:{ticker}:{around}"
    try:
        hit = _redis().get(key)
        if hit:
            return json.loads(hit) or None
    except Exception:  # noqa: BLE001
        pass
    cik = _cik(ticker)
    out = None
    if cik:
        try:
            r = httpx.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=UA, timeout=20).json()
            f = r.get("filings", {}).get("recent", {})
            for form, items, acc_dt, acc_no, doc in zip(f.get("form", []), f.get("items", []), f.get("acceptanceDateTime", []),
                                                        f.get("accessionNumber", []), f.get("primaryDocument", [])):
                if form not in ("8-K", "6-K") or (form == "8-K" and "2.02" not in (items or "")):
                    continue
                ts = datetime.fromisoformat(acc_dt.replace("Z", "+00:00")).astimezone(ET)
                if abs((ts.date() - around).days) <= 2:
                    out = {"ts": ts.isoformat(), "form": form,
                           "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_no.replace('-', '')}/{doc}"}
                    break
        except Exception:  # noqa: BLE001
            out = None
    try:
        _redis().set(key, json.dumps(out), ex=86400 * 7 if out else 3600 * 6)
    except Exception:  # noqa: BLE001
        pass
    return out


def schedule(db: Session, ticker: str) -> dict[str, Any]:
    t = ticker.upper()
    today = datetime.now(ET).date()
    rows = db.execute(text("""SELECT report_date, report_ts, report_time, eps_estimate, eps_actual
                              FROM earnings_surprises WHERE ticker=:t ORDER BY report_date DESC LIMIT 12"""),
                      {"t": t}).mappings().all()
    past = [r for r in rows if r["report_date"] <= today and r["eps_actual"] is not None]
    future = [r for r in rows if r["report_date"] >= today and r["eps_actual"] is None]
    # the session the company has used lately, for unconfirmed future times
    habit = None
    sess = [session_of(r["report_ts"]) for r in past[:4] if r["report_ts"] is not None
            and r["report_ts"].astimezone(ET).strftime("%H:%M") != "15:00"]
    if sess:
        habit = max(set(sess), key=sess.count)
    if not future:  # fall back to the site's own calendar
        ev = db.execute(text("""SELECT earnings_date, report_time FROM earnings_events WHERE ticker=:t AND earnings_date >= :d
                                ORDER BY earnings_date LIMIT 1"""), {"t": t, "d": today}).mappings().first()
        nxt = {"date": str(ev["earnings_date"]), "ts": None, "session": ev["report_time"] or habit, "confirmed": False,
               "source": "calendar"} if ev else None
    else:
        r = future[-1]
        ts = r["report_ts"].astimezone(ET) if r["report_ts"] is not None else None
        placeholder = ts is None or ts.strftime("%H:%M") in ("15:00", "00:00")
        nxt = {"date": str(r["report_date"]), "ts": None if placeholder else ts.isoformat(),
               "session": habit if placeholder else session_of(ts), "confirmed": not placeholder, "source": "yahoo",
               "eps_estimate": float(r["eps_estimate"]) if r["eps_estimate"] is not None else None}
    last = None
    if past:
        r = past[0]
        sec = sec_release(t, r["report_date"])
        ts = datetime.fromisoformat(sec["ts"]) if sec else (r["report_ts"].astimezone(ET) if r["report_ts"] is not None else None)
        est, act = r["eps_estimate"], r["eps_actual"]
        last = {"date": str(r["report_date"]), "ts": ts.isoformat() if ts else None, "session": session_of(ts) if ts else r["report_time"],
                "source": "sec" if sec else "yahoo", "sec_url": sec["url"] if sec else None,
                "eps_estimate": float(est) if est is not None else None, "eps_actual": float(act) if act is not None else None,
                "surprise": float(act / est - 1) if est not in (None, 0) and act is not None else None}
        # the reaction session's outcome, and the model's sealed call on it
        o = db.execute(text("""SELECT earnings_date, reaction_date, actual_t1_gap_pct, actual_t1_close_return, flat_band
                               FROM outcomes WHERE ticker=:t AND earnings_date BETWEEN :a AND :b
                               ORDER BY earnings_date DESC LIMIT 1"""),
                       {"t": t, "a": r["report_date"] - timedelta(days=3), "b": r["report_date"] + timedelta(days=3)}).mappings().first()
        if o:
            band, mv = _f(o["flat_band"]), _f(o["actual_t1_close_return"])
            last["event_date"] = str(o["earnings_date"])
            last["actual"] = {"reaction_date": str(o["reaction_date"]) if o["reaction_date"] else None,
                              "gap": _f(o["actual_t1_gap_pct"]),
                              "move": mv, "band": band, "broke_out": (abs(mv) > band) if mv is not None and band else None}
        calls = db.execute(text("""SELECT forecaster, p_breakout, lean, sealed_at, broke_out, brier FROM arena_forecasts
                                   WHERE ticker=:t AND earnings_date BETWEEN :a AND :b ORDER BY sealed_at"""),
                           {"t": t, "a": r["report_date"] - timedelta(days=3), "b": r["report_date"] + timedelta(days=3)}).mappings().all()
        last["calls"] = [{"forecaster": c["forecaster"], "p": _f(c["p_breakout"]), "lean": c["lean"],
                          "sealed_at": c["sealed_at"].isoformat() if c["sealed_at"] else None, "brier": _f(c["brier"])}
                         for c in calls]
        if not last["calls"]:
            p = db.execute(text("""SELECT prob_move, lean_up, created_at FROM predictions WHERE ticker=:t
                                   AND earnings_date BETWEEN :a AND :b ORDER BY created_at LIMIT 1"""),
                           {"t": t, "a": r["report_date"] - timedelta(days=3), "b": r["report_date"] + timedelta(days=3)}).mappings().first()
            if p and p["prob_move"] is not None:
                last["model"] = {"p": float(p["prob_move"]), "lean_up": float(p["lean_up"]) if p["lean_up"] is not None else None,
                                 "made_at": p["created_at"].isoformat()}
    return {"ticker": t, "last": last, "next": nxt}
