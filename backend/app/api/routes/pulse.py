from fastapi import APIRouter
from backend.app.services.market_pulse_service import scan_market

router = APIRouter(prefix="/pulse", tags=["pulse"])


@router.get("")
def get_pulse():
    return scan_market()
