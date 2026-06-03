"""Moomoo / broker status endpoint."""
from fastapi import APIRouter
from backend.app.services.broker_service import get_status

router = APIRouter(prefix="/api/v1/broker", tags=["broker"])

@router.get("/status")
def status():
    return get_status()
