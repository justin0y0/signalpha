"""Reported financials and original filings for any SEC registrant."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.services import filings_service

router = APIRouter(prefix="/company", tags=["company"])


@router.get("/{ticker}/financials")
def company_financials(ticker: str, db: Session = Depends(get_db)):
    if not ticker.replace("-", "").replace(".", "").isalpha() or len(ticker) > 8:
        raise HTTPException(400, "not a ticker")
    body = filings_service.company(db, ticker)
    if not body.get("cik"):
        raise HTTPException(404, "not an SEC registrant")
    return body
