from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.services.simulation_service import (
    get_dashboard,
    reset_simulation,
    run_step,
)

router = APIRouter(prefix="/simulator", tags=["simulator"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return get_dashboard(db)


@router.post("/run-step")
def run_simulation_step(db: Session = Depends(get_db)):
    return run_step(db)


@router.post("/reset")
def reset(db: Session = Depends(get_db)):
    reset_simulation(db)
    return {"ok": True, "message": "Portfolio reset to initial capital"}
