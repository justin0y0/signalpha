from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.services.headline_service import headline

router = APIRouter(prefix="/model", tags=["model"])


@router.get("/headline")
def get_headline(db: Session = Depends(get_db)) -> dict:
    """Live capability figures. Copy anywhere on the site should read these, not hardcode."""
    return headline(db)
