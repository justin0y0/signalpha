"""Pro waitlist — a measured fake door.

There is no payment provider yet, so "Pro" cannot be sold. What can be measured now is
whether anyone wants it badly enough to leave an email against a stated price, and
which features they tick. That is the willingness-to-pay signal pricing decisions
should rest on, instead of a guess.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db.session import get_db

router = APIRouter(prefix="/waitlist", tags=["waitlist"])

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")
_WANTS = {"straddle_check", "alerts", "portfolio_risk", "arena_alerts", "api_mcp", "full_universe", "autopilot_live", "signal_alerts"}


class Join(BaseModel):
    email: str = Field(max_length=320)
    plan: str = Field(default="pro", max_length=32)
    wants: list[str] = Field(default_factory=list, max_length=10)
    source: str | None = Field(default=None, max_length=64)


@router.post("")
def join(body: Join, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(422, "That doesn't look like an email address.")
    wants = ",".join(sorted({w for w in body.wants if w in _WANTS}))
    db.execute(text("""
        INSERT INTO pro_waitlist (email, plan, wants, source) VALUES (:e, :p, :w, :s)
        ON CONFLICT (email) DO UPDATE SET plan=EXCLUDED.plan, wants=EXCLUDED.wants"""),
        {"e": email, "p": body.plan[:32], "w": wants, "s": (body.source or "")[:64]})
    db.commit()
    return {"ok": True}
