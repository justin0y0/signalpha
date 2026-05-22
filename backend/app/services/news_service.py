"""Fetch recent news headlines via yfinance (free, real-time Yahoo Finance feed)."""
from __future__ import annotations
import time
from typing import Any
import yfinance as yf


def fetch_news(ticker: str, hours: int = 24, limit: int = 6) -> list[dict[str, Any]]:
    try:
        t = yf.Ticker(ticker)
        news = t.news or []
        cutoff = time.time() - hours * 3600
        out = []
        for item in news[:limit * 2]:
            # yfinance changed its news schema; handle both old and new
            content = item.get("content", item)
            title = content.get("title", "") or item.get("title", "")
            pub = content.get("provider", {}).get("displayName") or item.get("publisher", "") or "—"
            url = content.get("canonicalUrl", {}).get("url") or content.get("clickThroughUrl", {}).get("url") or item.get("link", "")
            ts = item.get("providerPublishTime") or 0
            if not ts and content.get("pubDate"):
                try:
                    from datetime import datetime as _dt
                    ts = int(_dt.fromisoformat(content["pubDate"].replace("Z", "+00:00")).timestamp())
                except Exception:
                    pass
            if not title or (ts and ts < cutoff):
                continue
            out.append({
                "title": title,
                "publisher": pub,
                "url": url,
                "timestamp": ts,
                "minutes_ago": int((time.time() - ts) / 60) if ts else None,
            })
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []
