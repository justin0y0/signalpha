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
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CalendarResponse:
    start_date = start or date.today()
    end_date = end or (start_date + timedelta(days=settings.default_calendar_lookahead_days))
    return service.list_events(db=db, start=start_date, end=end_date, sector=sector, report_time=report_time)
