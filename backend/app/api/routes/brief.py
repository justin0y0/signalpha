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
    # The brief itself is public — it is the best demo of the one thing the model
    # measurably does, and hiding it pre-launch means nobody sees the reason to sign
    # up. What is gated is personalisation: only an entitled user gets their watchlist
    # applied, which is also the honest thing to charge for since it is per-user work
    # rather than shared research.
    ent = entitlements.resolve(db, email)
    tickers = watchlist_service.get(db, email) if (email and ent.allows("watchlist")) else None
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
