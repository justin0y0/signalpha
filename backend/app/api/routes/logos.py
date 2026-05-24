"""Logo cache proxy. First hit fetches from FMP and caches to disk; subsequent
hits serve from local file with long cache-control. Eliminates CORS issues
and gives instant subsequent loads."""
from __future__ import annotations
import os
from pathlib import Path

import httpx
from fastapi import APIRouter
from fastapi.responses import Response, FileResponse

router = APIRouter(prefix="/api/v1/logos", tags=["logos"])

CACHE_DIR = Path(os.getenv("LOGO_CACHE_DIR", "/tmp/signalpha_logos"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SOURCES = [
    lambda t: f"https://financialmodelingprep.com/image-stock/{t}.png",
    lambda t: f"https://assets.parqet.com/logos/symbol/{t}",
    lambda t: f"https://eodhd.com/img/logos/US/{t}.png",
]

# 1x1 transparent PNG fallback
EMPTY_PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0005fe02fea735812d0000000049454e44ae426082")


@router.get("/{ticker}.png")
def get_logo(ticker: str):
    t = ticker.upper().strip().replace("/", "")
    cache_path = CACHE_DIR / f"{t}.png"
    if cache_path.exists() and cache_path.stat().st_size > 200:
        return FileResponse(
            cache_path,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=604800, immutable"},
        )

    for src in SOURCES:
        try:
            r = httpx.get(src(t), timeout=6, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 200:
                cache_path.write_bytes(r.content)
                return Response(
                    content=r.content, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800, immutable"},
                )
        except Exception:
            continue

    # Mark as missing so we don't re-fetch repeatedly
    cache_path.write_bytes(EMPTY_PNG)
    return Response(
        content=EMPTY_PNG, media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.post("/preload")
def preload_universe():
    """Pre-fetch all S&P 100 logos. Run once after deploy."""
    from backend.app.services.market_pulse_service import UNIVERSE
    fetched = []
    for t in UNIVERSE:
        try:
            get_logo(t)
            fetched.append(t)
        except Exception:
            pass
    return {"cached": len(fetched), "tickers": fetched}
