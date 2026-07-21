"""Alpha Brief + Watchlist endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.services import brief_service, entitlements, watchlist_service

router = APIRouter(prefix="/api/v1", tags=["brief"])


@router.get("/brief")
def get_brief(
    email: str | None = Query(None, description="personalises the brief with this user's watchlist"),
    horizon_days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
) -> dict:
    # The brief is the one daily-recurring surface, so it is where entitlement is
    # enforced. Public surfaces (calendar/model/strategy) stay open — gating the
    # evidence would defeat the transparency argument the site is built on.
    ent = entitlements.resolve(db, email)
    if not ent.allows("brief"):
        return {"gated": True, "entitlement": ent.as_dict(),
                "upgrade": entitlements.upgrade_hint(ent)}
    tickers = watchlist_service.get(db, email) if email else None
    payload = brief_service.build_brief(db, tickers=tickers or None, horizon_days=horizon_days)
    payload["entitlement"] = ent.as_dict()
    return payload


@router.get("/watchlist")
def list_watchlist(email: str, db: Session = Depends(get_db)) -> dict:
    return {"email": email, "tickers": watchlist_service.get(db, email)}


@router.post("/watchlist")
def add_watchlist(email: str, ticker: str, db: Session = Depends(get_db)) -> dict:
    return {"email": email, "tickers": watchlist_service.add(db, email, ticker)}


@router.delete("/watchlist")
def remove_watchlist(email: str, ticker: str, db: Session = Depends(get_db)) -> dict:
    return {"email": email, "tickers": watchlist_service.remove(db, email, ticker)}


@router.get("/entitlement")
def get_entitlement(email: str | None = None, db: Session = Depends(get_db)) -> dict:
    """What this email can currently see. Drives the UI's gating without guessing."""
    ent = entitlements.resolve(db, email)
    return {"entitlement": ent.as_dict(), "upgrade": entitlements.upgrade_hint(ent)}
