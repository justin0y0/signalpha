"""Process-wide settings for third-party libraries, applied once at startup by both the
API and the scheduler."""
from __future__ import annotations


def tame_yfinance() -> None:
    """Run yfinance without its on-disk SQLite caches.

    yfinance keeps its timezone/cookie/ISIN caches in SQLite through peewee, which opens
    one connection per thread. Every `yf.download(threads=True)` starts fresh threads, so
    connections piled up: fd_watch counted 188 open handles on tkr-tz.db (2026-11-01),
    the source of the 1,024-file limit hit on 2026-10-27. Pointing the cache at a folder
    that cannot be created makes yfinance fall back to its in-memory dummy caches, at the
    cost of an extra timezone lookup per new ticker.
    """
    try:
        import yfinance as yf

        yf.set_tz_cache_location("/proc/yfinance-cache-off")
    except Exception:  # noqa: BLE001 - yfinance missing or API changed: keep the default
        pass
