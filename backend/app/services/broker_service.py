"""Broker router — dispatches to moomoo or ibkr based on BROKER env var."""
import os
import logging
log = logging.getLogger(__name__)


def _broker():
    return os.getenv("BROKER","").lower().strip()


def place_signal_order(signal):
    b = _broker()
    if b == "moomoo":
        from backend.app.services import moomoo_service as svc
    elif b == "ibkr":
        from backend.app.services import ibkr_service as svc
    else:
        return {"placed": False, "reason": f"BROKER='{b}' (set to moomoo/ibkr to enable)"}
    return svc.place_signal_order(signal)


def place_exit_order(ticker, side, qty):
    b = _broker()
    if b == "moomoo":
        from backend.app.services import moomoo_service as svc
        return svc.place_exit_order(ticker, side, qty)
    elif b == "ibkr":
        # IBKR uses bracket orders (auto-exit), no manual exit needed
        return {"placed": False, "reason": "IBKR uses bracket (auto exit)"}
    return {"placed": False, "reason": f"BROKER='{b}'"}


def get_status():
    b = _broker()
    if b == "moomoo":
        from backend.app.services import moomoo_service as svc
    elif b == "ibkr":
        from backend.app.services import ibkr_service as svc
    else:
        return {"enabled": False, "broker": b, "reason": "BROKER env not set"}
    s = svc.get_status()
    s["broker"] = b
    return s
