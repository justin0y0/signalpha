"""moomoo through its gateway-free REST API — the second broker behind Autopilot.

The old integration (services/moomoo_service.py) drove the OpenD desktop gateway over a
tunnel; OpenD ships no ARM build, so on this server it never ran. moomoo now also serves
plain HTTPS at https://webapi.moomoo.com with OAuth 2.1 + PKCE, which suits Autopilot
better: each holder authorises their own moomoo account on moomoo's site, and nothing of
theirs but the tokens reaches us.

    paper  /api/v1.0/sim-trade/accounts | /{acc}/cash-info | /{acc}/positions | /{acc}/orders
           POST /{acc}/orders {market, symbol, order_type 3=market, order_side 1 buy 2 sell
           3 short 4 buy back, qty, text}; POST /{acc}/orders/{id}/cancel
    live   /api/v1.0/accounts/authorized_trd_accs | /{acc}/funds | /{acc}/positions |
           GET/POST /{acc}/orders {code US.X, side BUY|SELL|SELL_SHORT|BUY_BACK, order_type
           MARKET, time_in_force DAY, session RTH, remark}

`Moomoo` mirrors the slice of the Alpaca client that autotrade_service uses. What moomoo
does not offer is borrowed from the house Alpaca account: the market clock and calendar,
asset flags (tradable / shortable / easy to borrow — a proxy, moomoo's own list may differ)
and the last trade price. There is no market-on-close order in moomoo's simulator, so
Autopilot sends moomoo's closing orders at market at 15:58 instead (scheduler).

Orders carry our client order id in `text` / `remark`; before sending, today's orders are
searched for it, so a job that runs twice cannot double an order here either.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from datetime import date, datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from backend.app.services.autotrade_service import Alpaca, BrokerError

BASE = "https://webapi.moomoo.com"
US_SIM_MARKET = 2
SIM_STATUS = {2: "accepted", 3: "partially_filled", 4: "filled", 5: "canceled", 6: "rejected"}


class MoomooError(BrokerError):
    pass


def redirect_uri() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://signalpha.app").rstrip("/") + "/api/v1/autopilot/moomoo/callback"


def client_id() -> str:
    """The site's OAuth client at moomoo: MOOMOO_OAUTH_CLIENT_ID, else registered once and kept in redis."""
    cid = os.getenv("MOOMOO_OAUTH_CLIENT_ID", "").strip()
    if cid:
        return cid
    from backend.app.services.ap_auth import _redis

    r = _redis()
    cid = r.get("ap:moomoo:client_id")
    if cid:
        return cid
    resp = httpx.post(f"{BASE}/oauth2/register", timeout=20, json={
        "redirect_uris": [redirect_uri()], "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "client_name": "SignAlpha Autopilot"})
    if resp.status_code >= 400 or "client_id" not in resp.text:
        raise MoomooError(f"client registration failed: {resp.status_code} {resp.text[:200]}")
    cid = resp.json()["client_id"]
    r.set("ap:moomoo:client_id", cid)
    return cid


def oauth_start(holder: str, role: str, mode: str) -> str:
    from backend.app.services.ap_auth import _redis

    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(24)
    cid = client_id()
    _redis().set(f"ap:mmoauth:{state}", json.dumps({"holder": holder, "role": role, "mode": mode, "verifier": verifier,
                                                    "client_id": cid}), ex=600)
    return f"{BASE}/oauth2/authorize/confirm?" + urlencode({
        "client_id": cid, "code_challenge": challenge, "code_challenge_method": "S256",
        "redirect_uri": redirect_uri(), "response_type": "code", "state": state})


def oauth_finish(code: str, state: str) -> tuple[dict, dict]:
    """-> (the holder's pending request, the token bundle to store)."""
    from backend.app.services.ap_auth import _redis

    raw = _redis().getdel(f"ap:mmoauth:{state}") if state else None
    if not raw:
        raise MoomooError("This authorisation link has expired — start again from the Autopilot page")
    st = json.loads(raw)
    r = httpx.post(f"{BASE}/oauth2/token", timeout=20, data={
        "grant_type": "authorization_code", "code": code, "client_id": st["client_id"],
        "redirect_uri": redirect_uri(), "code_verifier": st["verifier"]})
    if r.status_code != 200:
        raise MoomooError(f"token exchange failed: {r.status_code} {r.text[:200]}")
    t = r.json()
    return st, {"access_token": t["access_token"], "refresh_token": t.get("refresh_token"), "client_id": st["client_id"],
                "expires_at": time.time() + float(t.get("expires_in") or 7200) - 120, "scope": t.get("scope")}


def _house():
    """The house Alpaca account (paper keys in .env) for clock, calendar, asset flags and prices."""
    return Alpaca("paper", os.getenv("ALPACA_DATA_KEY_ID", ""), os.getenv("ALPACA_DATA_SECRET", ""))


class Moomoo:
    def __init__(self, mode: str, acc_id: str, bundle: dict, saver: Callable[[dict], None] | None = None):
        self.mode, self.acc, self.b, self.saver = mode, str(acc_id), dict(bundle), saver
        self.house = _house()

    # ── transport
    def _token(self) -> str:
        if time.time() >= float(self.b.get("expires_at") or 0):
            self._refresh()
        return self.b["access_token"]

    def _refresh(self) -> None:
        if not self.b.get("refresh_token"):
            raise MoomooError("moomoo authorisation expired — reconnect the account")
        r = httpx.post(f"{BASE}/oauth2/token", timeout=20, data={
            "grant_type": "refresh_token", "refresh_token": self.b["refresh_token"], "client_id": self.b["client_id"]})
        if r.status_code != 200:
            raise MoomooError(f"token refresh failed ({r.status_code}) — reconnect the account")
        t = r.json()
        self.b["access_token"] = t["access_token"]
        self.b["expires_at"] = time.time() + float(t.get("expires_in") or 7200) - 120
        if self.saver:
            self.saver(self.b)

    def _req(self, method: str, path: str, **kw) -> Any:
        for attempt in (0, 1):
            r = httpx.request(method, BASE + path, timeout=20,
                              headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}, **kw)
            if r.status_code == 401 and attempt == 0:
                self._refresh()
                continue
            break
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            raise MoomooError(f"{r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            raise MoomooError(f"{r.status_code}: {str(body)[:240]}")
        if "ret_code" in body:  # simulated-trading wrapper
            if body["ret_code"] != 0:
                raise MoomooError(f"{body['ret_code']}: {body.get('ret_msg')}")
            return body.get("data")
        if body.get("s") == "error":  # trading wrapper
            raise MoomooError(f"{body.get('errcode')}: {body.get('errmsg')}")
        return body.get("d", body)

    @property
    def _sim(self) -> bool:
        return self.mode == "paper"

    # ── account
    @staticmethod
    def accounts(token: str, mode: str) -> list[dict]:
        path = "/api/v1.0/sim-trade/accounts" if mode == "paper" else "/api/v1.0/accounts/authorized_trd_accs"
        r = httpx.get(BASE + path, timeout=20, headers={"Authorization": f"Bearer {token}"})
        body = r.json()
        data = body.get("data") if "ret_code" in body else body.get("d", body)
        return (data or {}).get("accounts") or []

    def account(self) -> dict:
        if self._sim:
            d = self._req("GET", f"/api/v1.0/sim-trade/{self.acc}/cash-info")
            eq, cash, power = d.get("total_asset"), d.get("balance"), d.get("max_power_long")
        else:
            d = self._req("GET", f"/api/v1.0/accounts/{self.acc}/funds", params={"currency": "USD"})
            eq, cash, power = d.get("total_assets"), d.get("cash"), d.get("power")
        eq = float(eq or 0)
        return {"status": "ACTIVE", "account_number": self.acc, "equity": str(eq), "last_equity": str(self.b.get("last_equity") or eq),
                "cash": str(cash or 0), "buying_power": str(power or 0), "shorting_enabled": True, "multiplier": None,
                "trading_blocked": False, "account_blocked": False, "long_market_value": None, "short_market_value": None}

    def positions(self) -> list:
        from backend.app.services.strategy_lab import from_alpaca

        out = []
        if self._sim:
            rows = (self._req("GET", f"/api/v1.0/sim-trade/{self.acc}/positions", params={"market": US_SIM_MARKET}) or {}).get("positions") or []
            for p in rows:
                qty = float(p.get("qty") or 0)
                if not qty:
                    continue
                short = str(p.get("pstn_type")) == "1"
                out.append({"symbol": from_alpaca(p["symbol"]), "qty": str(-qty if short else qty), "side": "short" if short else "long",
                            "avg_entry_price": p.get("cost_price"), "current_price": p.get("cur_price"),
                            "market_value": str(-abs(float(p.get("mv") or 0)) if short else abs(float(p.get("mv") or 0))),
                            "unrealized_pl": p.get("profit"), "unrealized_plpc": p.get("profit_ratio"), "change_today": None})
        else:
            rows = self._req("GET", f"/api/v1.0/accounts/{self.acc}/positions") or []
            for p in rows:
                if not str(p.get("code", "")).startswith("US.") or not float(p.get("qty") or 0):
                    continue
                short = p.get("position_side") == "SHORT"
                qty = abs(float(p["qty"]))
                out.append({"symbol": from_alpaca(p["code"][3:]), "qty": str(-qty if short else qty), "side": "short" if short else "long",
                            "avg_entry_price": p.get("cost_price"), "current_price": p.get("nominal_price"),
                            "market_value": str(-abs(float(p.get("market_val") or 0)) if short else abs(float(p.get("market_val") or 0))),
                            "unrealized_pl": p.get("pl_val"), "unrealized_plpc": p.get("pl_ratio"), "change_today": None})
        return out

    # ── borrowed from the house Alpaca account
    def clock(self) -> dict: return self.house.clock()
    def calendar(self, start: date, end: date) -> list[date]: return self.house.calendar(start, end)
    def asset(self, sym: str) -> dict: return self.house.asset(sym)
    def last_price(self, sym: str) -> float | None: return self.house.last_price(sym)

    def history(self, period: str, timeframe: str) -> dict:
        raise MoomooError("no equity history at moomoo — Autopilot charts its own marks")

    # ── orders
    def _orders(self) -> list[dict]:
        if self._sim:
            return (self._req("GET", f"/api/v1.0/sim-trade/{self.acc}/orders") or {}).get("orders") or []
        return (self._req("GET", f"/api/v1.0/accounts/{self.acc}/orders", params={"trd_market": "US", "page_flag": "",
                                                                                   "page_size": 100}) or {}).get("orders") or []

    def _norm(self, o: dict) -> dict:
        if self._sim:
            status = SIM_STATUS.get(int(o.get("status") or 0), "accepted")
            fq, px = o.get("cum_qty"), o.get("avg_fill_price")
            ts = o.get("update_time")
            when = datetime.fromtimestamp(int(ts) / 1e6, timezone.utc).isoformat() if ts else None
        else:
            s = str(o.get("order_status") or "")
            status = ("filled" if s == "FILLED_ALL" else "partially_filled" if s.startswith("FILLED_PART")
                      else "canceled" if "CANCEL" in s else "rejected" if "FAIL" in s or "REJECT" in s else "accepted")
            fq, px, when = o.get("dealt_qty"), o.get("dealt_avg_price"), o.get("updated_time")
        return {"id": str(o.get("order_id")), "status": status, "filled_qty": fq or "0",
                "filled_avg_price": px if px not in (None, "", "0", 0) else None, "filled_at": when}

    def order(self, cid: str) -> dict:
        key = "text" if self._sim else "remark"
        for o in self._orders():
            if (o.get(key) or "") == cid[:64]:
                return self._norm(o)
        raise MoomooError(f"order {cid} not found at moomoo")

    def cancel_all(self) -> None:
        for o in self._orders():
            n = self._norm(o)
            if n["status"] in ("accepted", "partially_filled"):
                path = (f"/api/v1.0/sim-trade/{self.acc}/orders/{n['id']}/cancel" if self._sim
                        else f"/api/v1.0/accounts/{self.acc}/orders/{n['id']}/cancel")
                try:
                    self._req("POST", path, json={})
                except MoomooError:
                    pass

    def submit(self, sym: str, qty: int, side: str, tif: str, cid: str) -> dict:
        from backend.app.services.strategy_lab import to_alpaca

        try:
            return self.order(cid)  # already sent by an earlier pass
        except MoomooError:
            pass
        opening = cid.endswith("-entry")
        if self._sim:
            code = {("buy", True): 1, ("sell", True): 3, ("sell", False): 2, ("buy", False): 4}[(side, opening)]
            d = self._req("POST", f"/api/v1.0/sim-trade/{self.acc}/orders", json={
                "market": US_SIM_MARKET, "symbol": to_alpaca(sym), "order_type": 3, "order_side": code,
                "qty": str(qty), "text": cid[:64]})
        else:
            code = {("buy", True): "BUY", ("sell", True): "SELL_SHORT", ("sell", False): "SELL", ("buy", False): "BUY_BACK"}[(side, opening)]
            d = self._req("POST", f"/api/v1.0/accounts/{self.acc}/orders", json={
                "code": f"US.{to_alpaca(sym)}", "qty": str(qty), "side": code, "order_type": "MARKET",
                "time_in_force": "DAY", "session": "RTH", "remark": cid[:64]})
        return {"id": str((d or {}).get("order_id")), "status": "accepted"}
