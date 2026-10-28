"""Autopilot API — strategies, sign-in, broker connections, settings, state, kill switch.

The strategy catalog is public: anyone can read each strategy's backtest and live record.
Everything below sign-in acts on the signed-in holder's own connections only; a
connection id belonging to someone else is a 404.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
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
    log = logging.getLogger(__name__)
    try:
        st, bundle = moomoo_rest.oauth_finish(code, state)
        found = moomoo_rest.Moomoo.discover(bundle["access_token"])
        accts = found[st["mode"]]["accounts"]
        us = [a for a in accts if moomoo_rest.Moomoo.is_us(a)]
        if not us:
            # Keep the authorisation for an hour (encrypted) so the holder can pick the
            # account themselves (/moomoo/pending) instead of scanning again.
            from backend.app.services.ap_auth import _redis

            _redis().set(f"ap:mmpending:{st['holder']}", at._fernet().encrypt(json.dumps({**st, "bundle": bundle}).encode()).decode(), ex=3600)
            log.warning("moomoo connect: no US %s account for %s — moomoo answered %s", st["mode"], st["holder"],
                        json.dumps(moomoo_rest.Moomoo.summary(found), default=str))
            return RedirectResponse("/autopilot?oauth=noaccount", status_code=302)
        acc_id = str(us[0].get("account_id") or us[0].get("acc_id"))
        r = at.connect(db, st["holder"], st["role"], st["mode"], acc_id, json.dumps(bundle), auth="oauth", broker="moomoo")
        return RedirectResponse(f"/autopilot?connected={r['mode']}&broker=moomoo", status_code=302)
    except Exception as exc:  # noqa: BLE001 - the page explains; details go to the log
        log.warning("moomoo connect failed: %s", exc)
        return RedirectResponse("/autopilot?oauth=failed", status_code=302)


def _mm_pending(h: ap_auth.Holder) -> dict:
    import json

    from backend.app.services.ap_auth import _redis

    raw = _redis().get(f"ap:mmpending:{h.key}")
    if not raw:
        raise HTTPException(404, "No pending moomoo authorisation — connect again from the moomoo button")
    return json.loads(at._fernet().decrypt(raw.encode()).decode())


@router.get("/moomoo/pending")
def moomoo_pending(h: ap_auth.Holder = Depends(ap_auth.current)):
    """An authorisation that found no US account on its own: every account moomoo returned
    (both lists), masked, so the holder can pick one or see why there is none."""
    from backend.app.services import moomoo_rest

    st = _mm_pending(h)
    found = moomoo_rest.Moomoo.discover(st["bundle"]["access_token"])
    summ = moomoo_rest.Moomoo.summary(found)
    out = []
    for mode, v in found.items():
        for i, a in enumerate(v["accounts"]):
            acc = str(a.get("account_id") or a.get("acc_id") or "")
            out.append({"mode": mode, "index": i, "hint": acc[-4:], "us": moomoo_rest.Moomoo.is_us(a),
                        **summ[mode]["accounts"][i]})
    return {"mode": st["mode"], "accounts": out,
            "lists": {m: {"status": v["status"], "error": v["error"], "n": v["n"]} for m, v in summ.items()}}


@router.post("/moomoo/pending")
def moomoo_pending_connect(mode: str = Body(..., embed=True), index: int = Body(..., embed=True),
                           h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    """Connect the pending authorisation to one of the accounts it lists."""
    import json

    from backend.app.services import moomoo_rest
    from backend.app.services.ap_auth import _redis

    st = _mm_pending(h)
    if mode not in ("paper", "live"):
        raise HTTPException(400, "mode must be paper or live")
    if mode == "live" and not at.live_allowed(h.role):
        raise HTTPException(403, "Live trading is limited to the owner account for now")
    accts = moomoo_rest.Moomoo.discover(st["bundle"]["access_token"])[mode]["accounts"]
    if not 0 <= index < len(accts):
        raise HTTPException(400, "No such account")
    acc = str(accts[index].get("account_id") or accts[index].get("acc_id"))
    r = _guard(lambda: at.connect(db, st["holder"], st["role"], mode, acc, json.dumps(st["bundle"]),
                                  auth="oauth", broker="moomoo"))
    _redis().delete(f"ap:mmpending:{h.key}")
    return r


@router.post("/connect/tradier")
def connect_tradier(mode: str = Body(...), token: str = Body(...),
                    h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    return _guard(lambda: at.connect_tradier(db, h.key, h.role, mode, token))


@router.post("/connect/tastytrade")
def connect_tasty(mode: str = Body(...), client_secret: str = Body(...), refresh_token: str = Body(...),
                  h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    return _guard(lambda: at.connect_tasty(db, h.key, h.role, mode, client_secret, refresh_token))


@router.get("/robinhood/start")
def robinhood_start(h: ap_auth.Holder = Depends(ap_auth.current)):
    return {"url": _guard(lambda: at.robinhood_start(h.key, h.role))}


@router.get("/robinhood/callback")
def robinhood_callback(code: str = Query(""), state: str = Query(""), error: str = Query(""),
                       db: Session = Depends(get_db)):
    import logging

    if error or not code:
        return RedirectResponse("/autopilot?oauth=denied", status_code=302)
    try:
        at.robinhood_finish(db, code, state)
        return RedirectResponse("/autopilot?connected=live&broker=robinhood", status_code=302)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("robinhood connect failed: %s", exc)
        return RedirectResponse("/autopilot?oauth=failed", status_code=302)


@router.get("/snaptrade/start")
def snaptrade_start(broker: str | None = Query(None), h: ap_auth.Holder = Depends(ap_auth.current),
                    db: Session = Depends(get_db)):
    return {"url": _guard(lambda: at.snaptrade_start(db, h.key, h.role, broker))}


@router.get("/snaptrade/callback")
def snaptrade_callback(state: str = Query(""), db: Session = Depends(get_db)):
    import logging

    try:
        made = at.snaptrade_finish(db, state)
        if not made:
            return RedirectResponse("/autopilot?oauth=noaccount", status_code=302)
        return RedirectResponse(f"/autopilot?connected={made[-1]['mode']}&broker={made[-1]['broker']}", status_code=302)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("snaptrade connect failed: %s", exc)
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


# ───────────────────────── strategy library ─────────────────────────

@router.get("/library")
def library_table():
    """Every catalogue strategy, graded (public)."""
    from backend.app.services import library_service

    return library_service.table()


@router.get("/library/mine")
def library_mine(h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    from backend.app.services import library_service

    return {"rows": library_service.mine(db, h.key)}


@router.get("/library/{spec_id}")
def library_detail(spec_id: str, db: Session = Depends(get_db), x_autopilot_token: str = Header(default="")):
    """One strategy with its curve: a catalogue id, or `u<id>` for one of your own (signed in)."""
    from backend.app.services import library_service

    if spec_id.startswith("u") and spec_id[1:].isdigit():
        h = ap_auth.holder_from(x_autopilot_token) if x_autopilot_token else None
        if h is None:
            raise HTTPException(401, "Sign in to see your own strategies")
        d = _guard(lambda: library_service.custom_detail(db, h.key, spec_id))
    else:
        d = library_service.detail(spec_id)
    if d is None:
        raise HTTPException(404, "No such strategy")
    return d


@router.post("/library/backtest")
def library_backtest(spec: dict = Body(..., embed=True), name: str = Body("", embed=True),
                     h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    """Backtest a strategy you wrote yourself; it is saved to your list and counts as a trial."""
    from backend.app.services import library_service

    return _guard(lambda: library_service.save_run(db, h.key, spec, name or spec.get("template", "custom")))


@router.post("/library/brainstorm")
def library_brainstorm(prompt: str = Body(..., embed=True), lang: str = Body("en", embed=True),
                       base: dict | None = Body(None, embed=True),
                       h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    """Describe an idea; the model writes it as a library rule, which is then backtested."""
    from backend.app.services import library_service

    try:
        return _guard(lambda: library_service.brainstorm(db, h.key, prompt, lang, base))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.delete("/library/{spec_id}")
def library_delete(spec_id: str, h: ap_auth.Holder = Depends(ap_auth.current), db: Session = Depends(get_db)):
    from backend.app.services import library_service

    if not (spec_id.startswith("u") and spec_id[1:].isdigit()):
        raise HTTPException(400, "Only your own strategies can be deleted")
    library_service.delete(db, h.key, spec_id)
    return {"ok": True}
