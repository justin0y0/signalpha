"""What crawlers and link previews see: per-page titles and descriptions, and a sitemap.

The site is a single-page app, so every URL used to return the same <head> — 5,000 stock
pages with one title and one description, and a Reddit or X preview of /predict/NVDA
that said nothing about Nvidia. nginx now sends the stock pages and the desks through
`/seo/render`, which takes the built index.html (from the frontend container's internal
port) and rewrites its title, description, Open Graph tags and canonical link. If this
fails, nginx serves the plain index.html, so a broken backend never blanks the site.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db.session import get_db

router = APIRouter(prefix="/seo", tags=["seo"])
SITE = "https://signalpha.app"
ET = ZoneInfo("America/New_York")

PAGES: dict[str, tuple[str, str]] = {
    "/arena": ("Earnings Arena — AI models vs. the options market, sealed before the bell",
               "Before each earnings report, GPT-OSS, Qwen, our ML model, the options market and a base rate each give the "
               "chance of an unusually big move. Every call is hashed and anchored in Bitcoin, then scored against what happened."),
    "/strategy": ("Earnings direction rules, called at the open — with their live record",
                  "Four rules for trading a stock's first session after earnings, backtested on 21,881 trades since 2008 and "
                  "tracked live since October 2026, including the ones that are losing."),
    "/autopilot": ("Autopilot — earnings strategies that trade your paper account",
                   "Pick backtested earnings and market strategies and let them trade your Alpaca, moomoo, Tradier or "
                   "tastytrade paper account. Every fill is shown."),
    "/library": ("Strategy library — 496 trading rules backtested against buy-and-hold",
                 "Trend, mean reversion, seasonality, leveraged-ETF and earnings rules, graded after costs against simply "
                 "holding the same thing. Most lose; the page says which and by how much."),
    "/oracle": ("Who moves markets — Buffett, Pelosi, Musk, Cramer and 27 more, scored against SPY",
                "13F filings, congressional trade disclosures, ARK trades and the calls of 31 market movers, each priced when "
                "it became public and measured against the S&P 500."),
    "/model": ("Does it work? Every model claim checked out of sample",
               "Breakout flags, follow-through and direction calls, each beside the baseline it has to beat, with the live "
               "record since October 2026."),
    "/brief": ("Today's earnings brief — what reported, what moved, what is next",
               "One page per session: how the market traded, which earnings reports moved more than usual, and what reports "
               "before the next open."),
    "/markets": ("Markets at a glance — indices, breadth, sectors and movers",
                 "S&P 500, Nasdaq, Dow and Russell, breadth across 3,400 US companies, a sector heatmap, futures, rates, "
                 "commodities and crypto."),
    "/pro": ("SignAlpha Pro", "Research is free, and so is Autopilot on paper. Pro is for trading earnings season with real money."),
    "/about": ("About SignAlpha", "An earnings-season research site that publishes every result, including the failures."),
}


def _template() -> str:
    r = httpx.get("http://frontend:8080/index.html", timeout=3)
    r.raise_for_status()
    return r.text


def _fmt_day(d: date) -> str:
    return d.strftime("%a, %b %-d, %Y")


SESSION = {"BMO": "before the open", "AMC": "after the close", "DMH": "during market hours"}


def _stock_meta(db: Session, ticker: str) -> tuple[str, str] | None:
    from backend.app.services.flat_band import load_flat_bands

    t = ticker.upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,7}", t):
        return None
    name = db.execute(text("SELECT name FROM universe WHERE ticker=:t"), {"t": t}).scalar() \
        or db.execute(text("SELECT company_name FROM earnings_events WHERE ticker=:t ORDER BY earnings_date DESC LIMIT 1"), {"t": t}).scalar()
    if not name:
        return None
    name = re.sub(r"\s+(Common Stock|Class [A-Z] Common Stock|Ordinary Shares|American Depositary Shares.*)$", "", name).strip()
    today = datetime.now(ET).date()
    nxt = db.execute(text("""SELECT earnings_date, report_time FROM earnings_events WHERE ticker=:t AND earnings_date >= :d
                             ORDER BY earnings_date LIMIT 1"""), {"t": t, "d": today}).first()
    last = db.execute(text("""SELECT earnings_date FROM earnings_events WHERE ticker=:t AND earnings_date < :d
                              ORDER BY earnings_date DESC LIMIT 1"""), {"t": t, "d": today}).first()
    band = (load_flat_bands(db, [t]) or {}).get(t)
    implied = db.execute(text("""SELECT f.expected_move_pct FROM price_features f WHERE f.ticker=:t
                                 ORDER BY f.earnings_date DESC LIMIT 1"""), {"t": t}).scalar()
    parts = []
    if nxt:
        when = SESSION.get((nxt[1] or "").upper(), "")
        title = f"{t} earnings date: {_fmt_day(nxt[0])}" + (f", {when}" if when else "")
        parts.append(f"{name} reports next on {_fmt_day(nxt[0])}" + (f", {when}" if when else "") + ".")
    else:
        title = f"{t} earnings: last report, reaction and filings"
        if last:
            parts.append(f"{name} last reported on {_fmt_day(last[0])}.")
    if band:
        title += f" — usual move ±{band * 100:.1f}%"
        parts.append(f"It usually moves ±{band * 100:.1f}% on earnings"
                     + (f"; options price ±{float(implied) * 100:.1f}%." if implied and implied == implied else "."))
    parts.append("Breakout risk, the last report against the sealed forecast, reported numbers and SEC filings.")
    return f"{title} | SignAlpha", " ".join(parts)


def _inject(page: str, path: str, title: str, desc: str) -> str:
    t, d = html.escape(title, quote=True), html.escape(desc, quote=True)
    url = SITE + path
    page = re.sub(r"<title>.*?</title>", f"<title>{t}</title>", page, count=1, flags=re.S)
    page = re.sub(r'<meta name="description" content="[^"]*"\s*/?>', f'<meta name="description" content="{d}" />', page, count=1)
    page = re.sub(r'<meta property="og:title" content="[^"]*"\s*/?>', f'<meta property="og:title" content="{t}" />', page, count=1)
    page = re.sub(r'<meta property="og:description" content="[^"]*"\s*/?>', f'<meta property="og:description" content="{d}" />', page, count=1)
    page = re.sub(r'<meta property="og:url" content="[^"]*"\s*/?>', f'<meta property="og:url" content="{url}" />', page, count=1)
    page = re.sub(r'<meta name="twitter:title" content="[^"]*"\s*/?>', f'<meta name="twitter:title" content="{t}" />', page, count=1)
    page = re.sub(r'<meta name="twitter:description" content="[^"]*"\s*/?>', f'<meta name="twitter:description" content="{d}" />', page, count=1)
    return page.replace("</head>", f'<link rel="canonical" href="{url}" />\n</head>', 1)


@router.get("/render", response_class=HTMLResponse, include_in_schema=False)
def render(path: str = Query(..., max_length=80), db: Session = Depends(get_db)):
    path = "/" + path.strip("/")
    meta = None
    m = re.fullmatch(r"/predict/([A-Za-z0-9.\-]{1,8})", path)
    if m:
        from backend.app.services.ap_auth import _redis
        key = f"seo:meta:{m.group(1).upper()}"
        try:
            hit = _redis().get(key)
            meta = tuple(json.loads(hit)) if hit else None
        except Exception:  # noqa: BLE001
            meta = None
        if meta is None:
            meta = _stock_meta(db, m.group(1))
            if meta:
                try:
                    _redis().set(key, json.dumps(meta), ex=6 * 3600)
                except Exception:  # noqa: BLE001
                    pass
        path = f"/predict/{m.group(1).upper()}"
    elif path in PAGES:
        title, desc = PAGES[path]
        meta = (f"{title} | SignAlpha", desc)
    try:
        page = _template()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, "template unavailable") from exc
    if meta:
        page = _inject(page, path, *meta)
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(db: Session = Depends(get_db)):
    today = datetime.now(ET).date()
    tickers = [r[0] for r in db.execute(text("""SELECT DISTINCT ticker FROM earnings_events
        WHERE earnings_date BETWEEN :a AND :b ORDER BY ticker"""), {"a": today - timedelta(days=120), "b": today + timedelta(days=120)}).all()]
    urls = [("/", "daily", "1.0")] + [(p, "daily", "0.8") for p in PAGES] + \
        [(f"/predict/{t}", "weekly", "0.6") for t in tickers if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,7}", t)]
    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    body += [f"<url><loc>{SITE}{u}</loc><lastmod>{today}</lastmod><changefreq>{f}</changefreq><priority>{p}</priority></url>"
             for u, f, p in urls]
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml", headers={"Cache-Control": "public, max-age=3600"})
