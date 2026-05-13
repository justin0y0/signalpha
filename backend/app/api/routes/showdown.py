from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from backend.app.api.deps import get_db
from backend.app.services.showdown_service import run_showdown, STRATEGIES

router = APIRouter(prefix="/showdown", tags=["showdown"])


@router.get("")
def showdown(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    initial_capital: float = Query(1_000_000, ge=10_000, le=100_000_000),
    db: Session = Depends(get_db),
):
    """Live forward test — strategies trade forward from launch date (60 days ago by default)."""
    if start_date is None:
        start_date = date.today() - timedelta(days=60)
    if end_date is None:
        end_date = date.today()
    return run_showdown(db, start_date, end_date, initial_capital)


@router.get("/strategies")
def list_strategies():
    return [{
        "code": s.code, "name": s.name, "emoji": s.emoji,
        "tagline": s.tagline, "citation": s.citation,
        "color": s.color, "description": s.description,
    } for s in STRATEGIES]
