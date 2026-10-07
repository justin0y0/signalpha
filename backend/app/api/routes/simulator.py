from __future__ import annotations

import hmac
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.services.simulation_service import (
    get_dashboard,
    reset_simulation,
    run_step,
)

router = APIRouter(prefix="/simulator", tags=["simulator"])

# Both write endpoints used to be open to anyone. /reset wiped the public paper record
# with one unauthenticated POST, and every open tab's auto-step hit /run-step each
# minute — each call fans out to yfinance for every candidate. Reset now needs the
# admin token; steps are coalesced so any number of visitors cost one step a minute
# (the scheduler's 30-minute job is unaffected).
_STEP_MIN_INTERVAL = 55.0
_last_step: dict[str, Any] = {"at": 0.0, "result": None}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return get_dashboard(db)


@router.post("/run-step")
def run_simulation_step(db: Session = Depends(get_db)):
    if _last_step["result"] is not None and time.time() - _last_step["at"] < _STEP_MIN_INTERVAL:
        return {**_last_step["result"], "throttled": True}
    result = run_step(db)
    _last_step.update(at=time.time(), result=result)
    return result


@router.post("/reset")
def reset(db: Session = Depends(get_db), x_admin_token: str | None = Header(default=None)):
    want = os.getenv("ADMIN_TOKEN", "").strip()
    if not want or not x_admin_token or not hmac.compare_digest(x_admin_token.strip(), want):
        raise HTTPException(status_code=403, detail="Resetting the paper account needs the admin token.")
    reset_simulation(db)
    return {"ok": True, "message": "Portfolio reset to initial capital"}
