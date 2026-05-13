from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from backend.app.api.deps import get_db
from backend.app.services.showdown_service import run_showdown, STRATEGIES

router = APIRouter(prefix="/showdown", tags=["showdown"])


@router.get("")
def showdown(
    start_date: date = Query(date(2022, 1, 1)),
    end_date: date = Query(date(2026, 5, 1)),
    initial_capital: float = Query(1_000_000, ge=10_000, le=100_000_000),
    db: Session = Depends(get_db),
):
    return run_showdown(db, start_date, end_date, initial_capital)


@router.get("/strategies")
def list_strategies():
    return [{
        "code": s.code, "name": s.name, "emoji": s.emoji,
        "tagline": s.tagline, "citation": s.citation,
        "color": s.color, "description": s.description,
    } for s in STRATEGIES]
