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

SOURCES = [
    lambda t: f"https://financialmodelingprep.com/image-stock/{t}.png",
    lambda t: f"https://assets.parqet.com/logos/symbol/{t}",
    lambda t: f"https://eodhd.com/img/logos/US/{t}.png",
]

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
    for src in SOURCES:
        try:
            r = httpx.get(src(t), timeout=8, follow_redirects=True, headers=headers)
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
