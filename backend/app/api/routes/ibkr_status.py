"""IBKR status endpoint for monitoring."""
from fastapi import APIRouter
from backend.app.services.ibkr_service import get_status

router = APIRouter(prefix="/api/v1/ibkr", tags=["ibkr"])

@router.get("/status")
def ibkr_status():
    return get_status()
