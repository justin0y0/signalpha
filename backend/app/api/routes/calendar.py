from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import Settings, get_db, get_settings
from backend.app.schemas.calendar import CalendarResponse
from backend.app.services.calendar_service import CalendarService

router = APIRouter(prefix="/calendar", tags=["calendar"])
service = CalendarService()


@router.get("", response_model=CalendarResponse)
def get_calendar(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    sector: str | None = Query(default=None),
    report_time: str | None = Query(default=None),
    days_forward: int | None = Query(default=None, ge=0, le=180),
    days_back: int | None = Query(default=None, ge=0, le=180),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CalendarResponse:
    # Every caller in the frontend asks with days_forward/days_back; these were ignored
    # until 2026-10-27, so the calendar's "past" tab was always empty and the tape on every
    # page downloaded 90 days of reports to show the next three weeks.
    today = date.today()
    start_date = start or (today - timedelta(days=days_back or 0))
    end_date = end or (today + timedelta(days=days_forward if days_forward is not None else settings.default_calendar_lookahead_days))
    return service.list_events(db=db, start=start_date, end=end_date, sector=sector, report_time=report_time)
