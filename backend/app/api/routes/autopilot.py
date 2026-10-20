"""Autopilot API — strategies, sign-in, broker connections, settings, state, kill switch.

The strategy catalog is public: anyone can read each strategy's backtest and live record.
Everything below sign-in acts on the signed-in holder's own connections only; a
connection id belonging to someone else is a 404.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.services import ap_auth
from backend.app.services import autotrade_service as at
from backend.app.services import strategy_lab as lab

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


def _guard(fn):
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except at.BrokerError as exc:
        raise HTTPException(400, f"Alpaca said: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/strategies")
def strategies(db: Session = Depends(get_db)):
    return lab.catalog(db)


@router.get("/strategies/{key}")
def strategy(key: str, slots: int | None = Query(None), db: Session = Depends(get_db)):
    if key not in lab.ORDER:
        raise HTTPException(404, "No such strategy")
    return {"key": key, "backtest": lab.backtest(db, key, slots), "live": lab.live_record(db, key, slots)}


@router.post("/code")
def send_code(email: str | None = Body(None, embed=True)):
    return ap_auth.send_code(email)


@router.post("/login")
def login(code: str = Body(...), email: str | None = Body(None)):
    return ap_auth.login(email, code)


@router.get("/me")
def me(h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    return at.overview(db, h.key, h.role) | {"email": h.email}


@router.post("/accounts")
def connect(mode: str = Body(...), key_id: str = Body(...), secret: str = Body(...),
            h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    return _guard(lambda: at.connect(db, h.key, h.role, mode, key_id, secret))


@router.get("/oauth/start")
def oauth_start(mode: str = Query("paper"), h: ap_auth.Holder = Depends(ap_auth.current)):
    return {"url": _guard(lambda: at.oauth_start(h.key, h.role, mode))}


@router.get("/oauth/callback")
def oauth_callback(code: str = Query(""), state: str = Query(""), error: str = Query(""),
                   db: Session = Depends(get_db)):
    if error or not code:
        return RedirectResponse("/autopilot?oauth=denied", status_code=302)
    try:
        r = at.oauth_finish(db, code, state)
        return RedirectResponse(f"/autopilot?connected={r['mode']}", status_code=302)
    except Exception:  # noqa: BLE001 - the page explains; details are in the server log
        return RedirectResponse("/autopilot?oauth=failed", status_code=302)


@router.get("/moomoo/start")
def moomoo_start(mode: str = Query("paper"), h: ap_auth.Holder = Depends(ap_auth.current)):
    from backend.app.services import moomoo_rest

    if mode not in ("paper", "live"):
        raise HTTPException(400, "mode must be paper or live")
    if mode == "live" and not at.live_allowed(h.role):
        raise HTTPException(403, "Live trading is limited to the owner account for now")
    return {"url": _guard(lambda: moomoo_rest.oauth_start(h.key, h.role, mode))}


@router.get("/moomoo/callback")
def moomoo_callback(code: str = Query(""), state: str = Query(""), error: str = Query(""),
                    db: Session = Depends(get_db)):
    """moomoo sends the holder back here after they approve; pick their US account and connect it."""
    import json
    import logging

    from backend.app.services import moomoo_rest

    if error or not code:
        return RedirectResponse("/autopilot?oauth=denied", status_code=302)
    try:
        st, bundle = moomoo_rest.oauth_finish(code, state)
        accts = moomoo_rest.Moomoo.accounts(bundle["access_token"], st["mode"])
        if st["mode"] == "paper":
            us = [a for a in accts if int(a.get("market_id") or 0) == moomoo_rest.US_SIM_MARKET]
        else:
            us = [a for a in accts if 2 in [int(m) for m in (a.get("enable_market") or [])]] or accts
        if not us:
            return RedirectResponse("/autopilot?oauth=noaccount", status_code=302)
        acc_id = str(us[0].get("account_id"))
        r = at.connect(db, st["holder"], st["role"], st["mode"], acc_id, json.dumps(bundle), auth="oauth", broker="moomoo")
        return RedirectResponse(f"/autopilot?connected={r['mode']}&broker=moomoo", status_code=302)
    except Exception as exc:  # noqa: BLE001 - the page explains; details go to the log
        logging.getLogger(__name__).warning("moomoo connect failed: %s", exc)
        return RedirectResponse("/autopilot?oauth=failed", status_code=302)


@router.delete("/accounts/{account_id}")
def disconnect(account_id: int, h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    _guard(lambda: at.disconnect(db, h.key, account_id))
    return {"deleted": account_id}


@router.get("/accounts/{account_id}")
def state(account_id: int, h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    return _guard(lambda: at.state(db, h.key, account_id))


@router.put("/accounts/{account_id}/settings")
def settings(account_id: int, patch: dict[str, Any] = Body(...),
             h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    return _guard(lambda: at.save_settings(db, h.key, account_id, patch))


@router.post("/accounts/{account_id}/live")
def acknowledge_live(account_id: int, ack: str = Body(..., embed=True),
                     h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    if not at.live_allowed(h.role):
        raise HTTPException(403, "Live trading is limited to the owner account for now")
    return _guard(lambda: at.acknowledge_live(db, h.key, account_id, ack))


@router.post("/accounts/{account_id}/kill")
def kill(account_id: int, flatten: bool = Body(False, embed=True),
         h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    return _guard(lambda: at.kill(db, h.key, account_id, flatten))
