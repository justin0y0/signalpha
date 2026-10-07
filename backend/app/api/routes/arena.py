from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.services import arena_service

router = APIRouter(prefix="/arena", tags=["arena"])

# The board re-scores every graded call with a bootstrap; a short cache keeps a burst of
# visitors from repeating that work. Sealing and resolution happen on the scheduler.
_cache: dict[str, Any] = {"at": 0.0, "body": None}
_TTL = 60


@router.get("")
def get_board(db: Session = Depends(get_db)):
    if _cache["body"] is not None and time.time() - _cache["at"] < _TTL:
        return _cache["body"]
    body = arena_service.board(db)
    _cache.update(at=time.time(), body=body)
    return body


@router.get("/anchors/{anchor_id}/manifest.txt")
def anchor_manifest(anchor_id: int, db: Session = Depends(get_db)):
    got = arena_service.anchor_file(db, anchor_id, "manifest")
    if not got:
        raise HTTPException(404, "no such anchor")
    data, ctype = got
    return Response(content=data, media_type=ctype,
                    headers={"Content-Disposition": f'attachment; filename="arena-{anchor_id}.txt"'})


@router.get("/anchors/{anchor_id}/manifest.txt.ots")
def anchor_proof(anchor_id: int, db: Session = Depends(get_db)):
    got = arena_service.anchor_file(db, anchor_id, "ots")
    if not got:
        raise HTTPException(404, "no such anchor")
    data, ctype = got
    return Response(content=data, media_type=ctype,
                    headers={"Content-Disposition": f'attachment; filename="arena-{anchor_id}.txt.ots"'})
