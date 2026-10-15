from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.services import playbook_service

router = APIRouter(prefix="/playbook", tags=["playbook"])


@router.get("/test")
def test_rule(
    side: str = Query("up", pattern="^(up|down|either)$"),
    k: float = Query(2.0, ge=0, le=6),
    action: str = Query("follow", pattern="^(follow|fade)$"),
    entry: str = Query("close", pattern="^(open|close)$"),
    hold: int = Query(20),
    surprise: str = Query("any", pattern="^(any|beat|miss)$"),
    cost_bps: float = Query(10.0, ge=0, le=200),
    tier: str = Query("all", pattern="^(all|large|mid|small)$"),
    db: Session = Depends(get_db),
):
    return playbook_service.test(db, side, k, action, entry, hold, surprise, cost_bps, tier)


@router.get("/grid")
def grid(entry: str = Query("close", pattern="^(open|close)$"), hold: int = Query(20), db: Session = Depends(get_db)):
    return playbook_service.grid(db, entry, hold)


@router.get("/live")
def live(days: int = Query(10, ge=1, le=30), db: Session = Depends(get_db)):
    return playbook_service.live(db, days)
