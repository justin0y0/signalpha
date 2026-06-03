"""Logo proxy with bulletproof SVG monogram fallback.
Always returns a valid image — never 404, never empty."""
from __future__ import annotations
import os
from pathlib import Path
import httpx
from fastapi import APIRouter
from fastapi.responses import Response, FileResponse

router = APIRouter(prefix="/api/v1/logos", tags=["logos"])

CACHE_DIR = Path(os.getenv("LOGO_CACHE_DIR", "/tmp/signalpha_logos"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

TICKER_DOMAINS = {
    "AAPL":"apple.com","MSFT":"microsoft.com","GOOGL":"abc.xyz","GOOG":"abc.xyz",
    "NVDA":"nvidia.com","AMZN":"amazon.com","META":"meta.com","TSLA":"tesla.com",
    "AVGO":"broadcom.com","ORCL":"oracle.com","CRM":"salesforce.com","ADBE":"adobe.com",
    "AMD":"amd.com","IBM":"ibm.com","CSCO":"cisco.com","INTC":"intel.com",
    "QCOM":"qualcomm.com","TXN":"ti.com","AMAT":"appliedmaterials.com","MU":"micron.com",
    "PANW":"paloaltonetworks.com","ADI":"analog.com","INTU":"intuit.com",
    "ACN":"accenture.com","ADP":"adp.com","NFLX":"netflix.com","DIS":"disney.com",
    "T":"att.com","VZ":"verizon.com",
    "JPM":"jpmorganchase.com","BAC":"bankofamerica.com","WFC":"wellsfargo.com",
    "GS":"goldmansachs.com","MS":"morganstanley.com","C":"citigroup.com",
    "USB":"usbank.com","PNC":"pnc.com","AXP":"americanexpress.com",
    "V":"visa.com","MA":"mastercard.com","PYPL":"paypal.com",
    "BLK":"blackrock.com","SCHW":"schwab.com","CB":"chubb.com","MCO":"moodys.com",
    "ICE":"ice.com","CME":"cmegroup.com","SPGI":"spglobal.com","AON":"aon.com",
    "BRK-B":"berkshirehathaway.com","BRK.B":"berkshirehathaway.com",
    "JNJ":"jnj.com","LLY":"lilly.com","MRK":"merck.com","ABBV":"abbvie.com",
    "ABT":"abbott.com","TMO":"thermofisher.com","PFE":"pfizer.com","AMGN":"amgen.com",
    "ISRG":"intuitive.com","SYK":"stryker.com","BMY":"bms.com","DHR":"danaher.com",
    "GILD":"gilead.com","REGN":"regeneron.com","VRTX":"vrtx.com",
    "ELV":"elevancehealth.com","CI":"cigna.com","BSX":"bostonscientific.com","ZTS":"zoetis.com",
    "WMT":"walmart.com","HD":"homedepot.com","MCD":"mcdonalds.com",
    "NKE":"nike.com","LOW":"lowes.com","BKNG":"booking.com","TJX":"tjx.com",
    "COST":"costco.com","PG":"pg.com","KO":"coca-cola.com","PEP":"pepsico.com",
    "PM":"pmi.com","MO":"altria.com","MDLZ":"mondelezinternational.com","CL":"colgatepalmolive.com",
    "CVX":"chevron.com","XOM":"exxonmobil.com","SO":"southerncompany.com","DUK":"duke-energy.com",
    "GE":"ge.com","RTX":"rtx.com","CAT":"caterpillar.com","DE":"deere.com",
    "ETN":"eaton.com","HON":"honeywell.com","UPS":"ups.com","WM":"wm.com",
    "LMT":"lockheedmartin.com","ITW":"itw.com",
    "PLD":"prologis.com","EQIX":"equinix.com","SHW":"sherwin-williams.com",
}

def _sources_for(t):
    urls = []
    if t in TICKER_DOMAINS:
        urls.append(f"https://logo.clearbit.com/{TICKER_DOMAINS[t]}")
    urls.append(f"https://financialmodelingprep.com/image-stock/{t}.png")
    urls.append(f"https://assets.parqet.com/logos/symbol/{t}")
    urls.append(f"https://eodhd.com/img/logos/US/{t}.png")
    return urls

PALETTE = ['#38bdf8', '#a78bfa', '#4ade80', '#fbbf24', '#f87171', '#ec4899', '#06b6d4', '#fb923c', '#22d3ee', '#84cc16']


def gen_monogram_svg(ticker: str) -> bytes:
    """Always-valid SVG monogram. Deterministic color from ticker hash."""
    clean = ticker.replace("-", "").replace(".", "")[:4]
    h = sum(ord(c) * (i + 1) for i, c in enumerate(clean))
    bg = PALETTE[h % len(PALETTE)]
    fs = 90 if len(clean) <= 3 else 64
    y = 124 if len(clean) <= 3 else 122
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">'
        f'<rect width="200" height="200" rx="28" fill="{bg}"/>'
        f'<text x="100" y="{y}" font-family="-apple-system,system-ui,sans-serif" '
        f'font-size="{fs}" font-weight="800" fill="white" text-anchor="middle" '
        f'letter-spacing="-2">{clean}</text>'
        f'</svg>'
    )
    return svg.encode('utf-8')


@router.get("/{ticker}.png")
def get_logo(ticker: str):
    t = ticker.upper().strip().replace("/", "")
    png_path = CACHE_DIR / f"{t}.png"
    svg_path = CACHE_DIR / f"{t}.svg"
    cache_h = {"Cache-Control": "public, max-age=604800, immutable"}

    # 1) Real PNG cached?
    if png_path.exists() and png_path.stat().st_size > 500:
        return FileResponse(png_path, media_type="image/png", headers=cache_h)
    # 2) SVG monogram cached?
    if svg_path.exists() and svg_path.stat().st_size > 100:
        return FileResponse(svg_path, media_type="image/svg+xml", headers=cache_h)

    # 3) Try external sources
    headers = {"User-Agent": UA, "Accept": "image/png,image/webp,image/*,*/*"}
    for src_url in _sources_for(t):
        try:
            r = httpx.get(src_url, timeout=8, follow_redirects=True, headers=headers)
            ct = r.headers.get("content-type", "").lower()
            if r.status_code == 200 and len(r.content) > 500 and "image" in ct and "html" not in ct:
                png_path.write_bytes(r.content)
                return Response(content=r.content,
                                media_type=ct.split(";")[0].strip(),
                                headers=cache_h)
        except Exception:
            continue

    # 4) All external failed → generate SVG monogram (ALWAYS succeeds)
    svg = gen_monogram_svg(t)
    svg_path.write_bytes(svg)
    return Response(content=svg, media_type="image/svg+xml", headers=cache_h)


@router.post("/preload")
def preload_universe():
    from backend.app.services.market_pulse_service import UNIVERSE
    results = {"png": 0, "svg_fallback": 0, "tickers": []}
    for t in UNIVERSE:
        try:
            get_logo(t)
            png = CACHE_DIR / f"{t.replace('/', '')}.png"
            if png.exists() and png.stat().st_size > 500:
                results["png"] += 1
            else:
                results["svg_fallback"] += 1
            results["tickers"].append(t)
        except Exception:
            pass
    return results
