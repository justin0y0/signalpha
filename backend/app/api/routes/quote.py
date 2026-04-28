from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/quote", tags=["quote"])


@router.get("/{ticker}")
def get_quote(ticker: str):
    """Fetch latest price for a ticker using yfinance (15-min delayed, free)."""
    try:
        import yfinance as yf
    except ImportError:
        raise HTTPException(status_code=500, detail="yfinance not available")

    try:
        t = yf.Ticker(ticker.upper())
        info = t.fast_info
        price = float(info.get("last_price") or info.get("lastPrice") or 0.0)
        prev_close = float(info.get("previous_close") or info.get("previousClose") or 0.0)

        if not price or not prev_close:
            # fallback to history
            hist = t.history(period="5d", interval="1d")
            if hist.empty:
                raise HTTPException(status_code=404, detail=f"No price data for {ticker}")
            price = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price

        change = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0

        # Fetch sparkline (last 30 days of daily closes)
        hist = t.history(period="1mo", interval="1d")
        sparkline = [float(x) for x in hist["Close"].tolist()] if not hist.empty else []

        return {
            "ticker": ticker.upper(),
            "price": round(price, 2),
            "previous_close": round(prev_close, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "sparkline": sparkline,
            "as_of": datetime.utcnow().isoformat() + "Z",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quote error: {e}")
