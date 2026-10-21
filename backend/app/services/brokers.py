"""The brokers Autopilot can trade in besides Alpaca and moomoo (moomoo_rest.py).

Every client here speaks the slice of the Alpaca client that autotrade_service uses —
account(), positions(), order(), submit(), cancel_all() — and borrows what its broker does
not offer (market clock, trading calendar, borrow flags, last price) from the house Alpaca
account, like moomoo_rest does. Statuses are mapped to Alpaca's words (accepted, filled,
canceled, expired, rejected, partially_filled).

  Tradier      paste a personal access token; paper = Tradier's sandbox (delayed quotes).
  tastytrade   paste a personal OAuth grant (client secret + refresh token); paper = the
               cert sandbox, which deletes every position each night — usable for same-day
               rules only, and the page says so.
  SnapTrade    one connection portal for brokers with no usable API of their own for us:
               E*TRADE, Webull, Public, tastytrade, moomoo, Wealthsimple, Trading 212. Needs
               SNAPTRADE_CLIENT_ID / SNAPTRADE_CONSUMER_KEY. Buy and sell only — SnapTrade's
               order API has no short sale, so short rules are skipped on these accounts.
  Robinhood    the official Trading MCP (agent.robinhood.com/mcp/trading): Robinhood's own
               route for third-party agents, OAuth with dynamic client registration, orders
               limited to the holder's dedicated agentic account. Long only. The order tool's
               arguments are read from its published schema at connect time; if they cannot be
               mapped with certainty the order is refused, never guessed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from backend.app.services.autotrade_service import Alpaca, BrokerError

OPEN_STATES = ("accepted", "new", "partially_filled", "pending_new")


def _opening(cid: str) -> bool:
    return cid.endswith("-entry")


class Borrowed:
    """Clock, calendar, asset flags and prices from the house Alpaca account."""

    _house: Alpaca | None = None

    @property
    def house(self) -> Alpaca:
        if Borrowed._house is None:
            Borrowed._house = Alpaca("paper", os.getenv("ALPACA_DATA_KEY_ID", ""), os.getenv("ALPACA_DATA_SECRET", ""))
        return Borrowed._house

    def clock(self) -> dict: return self.house.clock()
    def calendar(self, start: date, end: date) -> list[date]: return self.house.calendar(start, end)
    def asset(self, sym: str) -> dict: return self.house.asset(sym)
    def last_price(self, sym: str) -> float | None: return self.house.last_price(sym)

    def history(self, period: str, timeframe: str) -> dict:
        raise BrokerError("no equity history from this broker — Autopilot charts its own marks")

    def order_any(self, cid: str, boid: str | None) -> dict:
        return self.order(cid)


def _acct(equity, cash, power, shorts: bool, number: str, last=None) -> dict:
    return {"status": "ACTIVE", "account_number": number, "equity": str(float(equity or 0)),
            "last_equity": None if last is None else str(last), "cash": str(cash or 0), "buying_power": str(power or 0),
            "shorting_enabled": shorts, "multiplier": None, "trading_blocked": False, "account_blocked": False,
            "long_market_value": None, "short_market_value": None}


def _pos(sym: str, qty: float, avg, price, pl=None) -> dict:
    short = qty < 0
    mv = (price or 0) * qty if price else None
    plpc = ((price / float(avg) - 1) * (-1 if short else 1)) if price and avg and float(avg) else None
    return {"symbol": sym, "qty": str(qty), "side": "short" if short else "long", "avg_entry_price": avg,
            "current_price": price, "market_value": mv, "unrealized_pl": pl if pl is not None else
            ((price - float(avg)) * qty if price and avg else None), "unrealized_plpc": plpc, "change_today": None}


# ───────────────────────── Tradier ─────────────────────────

class Tradier(Borrowed):
    BASE = {"paper": "https://sandbox.tradier.com/v1", "live": "https://api.tradier.com/v1"}
    STATUS = {"open": "accepted", "pending": "accepted", "partially_filled": "partially_filled", "filled": "filled",
              "expired": "expired", "canceled": "canceled", "rejected": "rejected", "error": "rejected"}

    def __init__(self, mode: str, account: str, token: str):
        self.mode, self.acct, self.token = mode, account, token

    @classmethod
    def _call(cls, mode: str, token: str, method: str, path: str, **kw) -> Any:
        r = httpx.request(method, cls.BASE[mode] + path, timeout=20, **kw,
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if r.status_code >= 400:
            raise BrokerError(f"Tradier {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else {}

    def _req(self, method: str, path: str, **kw) -> Any:
        return self._call(self.mode, self.token, method, path, **kw)

    @classmethod
    def accounts(cls, mode: str, token: str) -> list[dict]:
        p = (cls._call(mode, token, "GET", "/user/profile").get("profile") or {}).get("account") or []
        return p if isinstance(p, list) else [p]

    @staticmethod
    def _list(x, key: str) -> list:
        v = (x or {}).get(key) if isinstance(x, dict) else None
        if not v or v == "null":
            return []
        return v if isinstance(v, list) else [v]

    def account(self) -> dict:
        b = self._req("GET", f"/accounts/{self.acct}/balances").get("balances") or {}
        margin = b.get("account_type") == "margin"
        power = (b.get("margin") or {}).get("stock_buying_power") if margin else (b.get("cash") or {}).get("cash_available")
        return _acct(b.get("total_equity"), b.get("total_cash"), power, margin, self.acct)

    def positions(self) -> list:
        from backend.app.services.strategy_lab import from_alpaca

        out = []
        for p in self._list(self._req("GET", f"/accounts/{self.acct}/positions").get("positions"), "position"):
            q = float(p.get("quantity") or 0)
            if not q:
                continue
            avg = float(p.get("cost_basis") or 0) / q if q else None
            sym = from_alpaca(p["symbol"])
            out.append(_pos(sym, q, abs(avg) if avg else None, self.last_price(sym)))
        return out

    def _orders(self) -> list[dict]:
        return self._list(self._req("GET", f"/accounts/{self.acct}/orders", params={"includeTags": "true"}).get("orders"), "order")

    def _norm(self, o: dict) -> dict:
        return {"id": str(o.get("id")), "status": self.STATUS.get(o.get("status"), "accepted"),
                "filled_qty": o.get("exec_quantity") or 0, "filled_avg_price": o.get("avg_fill_price") or None,
                "filled_at": o.get("transaction_date")}

    def order(self, cid: str) -> dict:
        for o in self._orders():
            if o.get("tag") == cid:
                return self._norm(o)
        raise BrokerError(f"order {cid} not found at Tradier")

    def submit(self, sym: str, qty: int, side: str, tif: str, cid: str) -> dict:
        from backend.app.services.strategy_lab import to_alpaca

        try:
            return self.order(cid)
        except BrokerError:
            pass
        op = _opening(cid)
        tside = {("buy", True): "buy", ("sell", True): "sell_short", ("sell", False): "sell", ("buy", False): "buy_to_cover"}[(side, op)]
        d = self._req("POST", f"/accounts/{self.acct}/orders", data={
            "class": "equity", "symbol": to_alpaca(sym), "side": tside, "quantity": str(qty), "type": "market",
            "duration": "day", "tag": cid})
        return {"id": str((d.get("order") or {}).get("id")), "status": "accepted"}

    def cancel_all(self) -> None:
        for o in self._orders():
            if self.STATUS.get(o.get("status")) in OPEN_STATES:
                try:
                    self._req("DELETE", f"/accounts/{self.acct}/orders/{o['id']}")
                except BrokerError:
                    pass


# ───────────────────────── tastytrade ─────────────────────────

class Tasty(Borrowed):
    BASE = {"paper": "https://api.cert.tastyworks.com", "live": "https://api.tastyworks.com"}
    UA = "signalpha-autopilot/1.0"
    STATUS = {"Received": "accepted", "Routed": "accepted", "In Flight": "accepted", "Live": "accepted",
              "Contingent": "accepted", "Cancel Requested": "accepted", "Filled": "filled", "Cancelled": "canceled",
              "Expired": "expired", "Rejected": "rejected", "Removed": "canceled", "Partially Removed": "canceled"}

    def __init__(self, mode: str, account: str, bundle: dict, saver: Callable[[dict], None] | None = None):
        self.mode, self.acct, self.b, self.saver = mode, account, dict(bundle), saver

    @classmethod
    def token(cls, mode: str, b: dict) -> dict:
        r = httpx.post(cls.BASE[mode] + "/oauth/token", timeout=20, headers={"User-Agent": cls.UA},
                       json={"grant_type": "refresh_token", "refresh_token": b["refresh_token"], "client_secret": b["client_secret"]})
        if r.status_code >= 400:
            raise BrokerError(f"tastytrade sign-in failed ({r.status_code}) — check the client secret and refresh token")
        t = r.json()
        return {**b, "access_token": t["access_token"], "expires_at": time.time() + float(t.get("expires_in") or 900) - 60}

    def _req(self, method: str, path: str, **kw) -> Any:
        if time.time() >= float(self.b.get("expires_at") or 0):
            self.b = self.token(self.mode, self.b)
            if self.saver:
                self.saver(self.b)
        r = httpx.request(method, self.BASE[self.mode] + path, timeout=20, **kw,
                          headers={"Authorization": f"Bearer {self.b['access_token']}", "User-Agent": self.UA,
                                   "Content-Type": "application/json"})
        if r.status_code >= 400:
            raise BrokerError(f"tastytrade {r.status_code}: {r.text[:200]}")
        return (r.json() if r.content else {}).get("data") or {}

    @classmethod
    def accounts(cls, mode: str, b: dict) -> tuple[list[dict], dict]:
        b = cls.token(mode, b)
        r = httpx.get(cls.BASE[mode] + "/customers/me/accounts", timeout=20,
                      headers={"Authorization": f"Bearer {b['access_token']}", "User-Agent": cls.UA})
        items = ((r.json() or {}).get("data") or {}).get("items") or []
        return [i.get("account") or {} for i in items], b

    def account(self) -> dict:
        d = self._req("GET", f"/accounts/{self.acct}/balances")
        margin = (self.b.get("margin_or_cash") or "Margin") == "Margin"
        return _acct(d.get("net-liquidating-value"), d.get("cash-balance"), d.get("equity-buying-power"), margin, self.acct)

    def positions(self) -> list:
        from backend.app.services.strategy_lab import from_alpaca

        out = []
        for p in (self._req("GET", f"/accounts/{self.acct}/positions").get("items") or []):
            if p.get("instrument-type") != "Equity":
                continue
            q = float(p.get("quantity") or 0) * (-1 if p.get("quantity-direction") == "Short" else 1)
            if q:
                sym = from_alpaca(p["symbol"])
                out.append(_pos(sym, q, p.get("average-open-price"), self.last_price(sym) or float(p.get("close-price") or 0) or None))
        return out

    def _norm(self, o: dict) -> dict:
        fills = [f for leg in o.get("legs") or [] for f in leg.get("fills") or []]
        q = sum(float(f.get("quantity") or 0) for f in fills)
        px = sum(float(f.get("fill-price") or 0) * float(f.get("quantity") or 0) for f in fills) / q if q else None
        return {"id": str(o.get("id")), "status": self.STATUS.get(o.get("status"), "accepted"), "filled_qty": q,
                "filled_avg_price": px, "filled_at": o.get("terminal-at") or o.get("updated-at")}

    def order(self, cid: str) -> dict:
        raise BrokerError("tastytrade orders are looked up by id")

    def order_any(self, cid: str, boid: str | None) -> dict:
        if not boid:
            raise BrokerError("no tastytrade order id recorded")
        return self._norm(self._req("GET", f"/accounts/{self.acct}/orders/{boid}"))

    def submit(self, sym: str, qty: int, side: str, tif: str, cid: str) -> dict:
        from backend.app.services.strategy_lab import to_alpaca

        op = _opening(cid)
        action = {("buy", True): "Buy to Open", ("sell", True): "Sell to Open", ("sell", False): "Sell to Close",
                  ("buy", False): "Buy to Close"}[(side, op)]
        d = self._req("POST", f"/accounts/{self.acct}/orders", json={
            "time-in-force": "Day", "order-type": "Market",
            "legs": [{"instrument-type": "Equity", "symbol": to_alpaca(sym).replace(".", "/"), "quantity": qty, "action": action}]})
        o = d.get("order") or {}
        return {"id": str(o.get("id")), "status": self.STATUS.get(o.get("status"), "accepted")}

    def cancel_all(self) -> None:
        for o in (self._req("GET", f"/accounts/{self.acct}/orders/live").get("items") or []):
            if self.STATUS.get(o.get("status")) in OPEN_STATES:
                try:
                    self._req("DELETE", f"/accounts/{self.acct}/orders/{o['id']}")
                except BrokerError:
                    pass


# ───────────────────────── SnapTrade ─────────────────────────

class SnapTrade(Borrowed):
    BASE = "https://api.snaptrade.com/api/v1"
    STATUS = {"EXECUTED": "filled", "PARTIAL": "partially_filled", "CANCELED": "canceled", "PARTIAL_CANCELED": "canceled",
              "EXPIRED": "expired", "REJECTED": "rejected", "FAILED": "rejected"}

    def __init__(self, mode: str, account: str, bundle: dict):
        self.mode, self.acct, self.b = mode, account, bundle

    @staticmethod
    def enabled() -> bool:
        return bool(os.getenv("SNAPTRADE_CLIENT_ID", "").strip() and os.getenv("SNAPTRADE_CONSUMER_KEY", "").strip())

    @classmethod
    def call(cls, method: str, path: str, query: dict | None = None, body: dict | None = None) -> Any:
        if not cls.enabled():
            raise BrokerError("SnapTrade is not set up on this server")
        q = {"clientId": os.environ["SNAPTRADE_CLIENT_ID"].strip(), "timestamp": str(int(time.time())), **(query or {})}
        qs = urlencode(q)
        sig_obj = {"content": None if not body else body, "path": "/api/v1" + path, "query": qs}
        msg = json.dumps(sig_obj, separators=(",", ":"), sort_keys=True)
        sig = base64.b64encode(hmac.new(os.environ["SNAPTRADE_CONSUMER_KEY"].strip().encode(), msg.encode(),
                                        hashlib.sha256).digest()).decode()
        r = httpx.request(method, f"{cls.BASE}{path}?{qs}", timeout=30, headers={"Signature": sig, "Content-Type": "application/json"},
                          content=json.dumps(body, separators=(",", ":"), sort_keys=True) if body else None)
        if r.status_code >= 400:
            raise BrokerError(f"SnapTrade {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else None

    @classmethod
    def register(cls, user_id: str) -> str:
        return cls.call("POST", "/snapTrade/registerUser", body={"userId": user_id})["userSecret"]

    @classmethod
    def portal(cls, user_id: str, secret: str, redirect: str, broker: str | None = None) -> str:
        body = {"connectionType": "trade", "customRedirect": redirect, "immediateRedirect": True}
        if broker:
            body["broker"] = broker
        return cls.call("POST", "/snapTrade/login", {"userId": user_id, "userSecret": secret}, body)["redirectURI"]

    @classmethod
    def list_accounts(cls, user_id: str, secret: str) -> list[dict]:
        return cls.call("GET", "/accounts", {"userId": user_id, "userSecret": secret}) or []

    def _u(self) -> dict:
        return {"userId": self.b["user_id"], "userSecret": self.b["user_secret"]}

    def account(self) -> dict:
        a = self.call("GET", f"/accounts/{self.acct}", self._u()) or {}
        total = ((a.get("balance") or {}).get("total") or {}).get("amount")
        bal = self.call("GET", f"/accounts/{self.acct}/balances", self._u()) or []
        usd = next((x for x in bal if ((x.get("currency") or {}).get("code") or "USD") == "USD"), bal[0] if bal else {})
        return _acct(total, usd.get("cash"), usd.get("buying_power"), False, str(a.get("number") or self.acct))

    def positions(self) -> list:
        from backend.app.services.strategy_lab import from_alpaca

        out = []
        for p in self.call("GET", f"/accounts/{self.acct}/positions", self._u()) or []:
            s = p.get("symbol") or {}
            s = s.get("symbol") if isinstance(s.get("symbol"), dict) else s
            sym = (s or {}).get("symbol") or (s or {}).get("raw_symbol")
            q = float(p.get("units") or 0)
            if sym and q:
                out.append(_pos(from_alpaca(sym), q, p.get("average_purchase_price"), p.get("price"), p.get("open_pnl")))
        return out

    def _norm(self, o: dict) -> dict:
        return {"id": str(o.get("brokerage_order_id")), "status": self.STATUS.get(o.get("status"), "accepted"),
                "filled_qty": o.get("filled_quantity") or 0, "filled_avg_price": o.get("execution_price"),
                "filled_at": o.get("time_executed") or o.get("time_updated")}

    def order(self, cid: str) -> dict:
        raise BrokerError("SnapTrade orders are looked up by id")

    def order_any(self, cid: str, boid: str | None) -> dict:
        for o in self.call("GET", f"/accounts/{self.acct}/orders", {**self._u(), "state": "all", "days": "30"}) or []:
            if str(o.get("brokerage_order_id")) == str(boid):
                return self._norm(o)
        raise BrokerError(f"order {boid} not found at SnapTrade")

    def submit(self, sym: str, qty: int, side: str, tif: str, cid: str) -> dict:
        from backend.app.services.strategy_lab import to_alpaca

        if side == "sell" and _opening(cid):
            raise BrokerError("short sales are not available through SnapTrade")
        o = self.call("POST", "/trade/place", self._u(), {
            "account_id": self.acct, "action": "BUY" if side == "buy" else "SELL", "order_type": "Market",
            "time_in_force": "Day", "symbol": to_alpaca(sym), "units": qty, "price": None, "stop": None,
            "universal_symbol_id": None, "client_order_id": str(uuid.uuid5(uuid.NAMESPACE_URL, cid))}) or {}
        return {"id": str(o.get("brokerage_order_id")), "status": self.STATUS.get(o.get("status"), "accepted")}

    def cancel_all(self) -> None:
        for o in self.call("GET", f"/accounts/{self.acct}/orders", {**self._u(), "state": "open"}) or []:
            try:
                self.call("POST", f"/accounts/{self.acct}/trading/cancel", self._u(),
                          {"brokerage_order_id": o.get("brokerage_order_id")})
            except BrokerError:
                pass


# ───────────────────────── Robinhood (Trading MCP) ─────────────────────────

class Robinhood(Borrowed):
    MCP = "https://agent.robinhood.com/mcp/trading"
    REGISTER = "https://agent.robinhood.com/oauth/trading/register"
    AUTHORIZE = "https://robinhood.com/oauth"
    TOKEN = "https://api.robinhood.com/oauth2/token/"

    def __init__(self, mode: str, account: str, bundle: dict, saver: Callable[[dict], None] | None = None):
        self.mode, self.acct, self.b, self.saver = mode, account, dict(bundle), saver
        self.session: str | None = None

    # OAuth (MCP authorization: dynamic client registration + PKCE)
    @classmethod
    def client_id(cls, redirect: str) -> str:
        from backend.app.services.ap_auth import _redis

        r = _redis()
        cid = r.get("ap:rh:client_id")
        if cid:
            return cid
        resp = httpx.post(cls.REGISTER, timeout=20, json={
            "redirect_uris": [redirect], "client_name": "SignAlpha Autopilot", "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]})
        if resp.status_code >= 400 or "client_id" not in resp.text:
            raise BrokerError(f"Robinhood client registration failed: {resp.status_code} {resp.text[:200]}")
        cid = resp.json()["client_id"]
        r.set("ap:rh:client_id", cid)
        return cid

    @classmethod
    def authorize_url(cls, client_id: str, redirect: str, state: str, verifier: str) -> str:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        return cls.AUTHORIZE + "?" + urlencode({
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect, "code_challenge": challenge,
            "code_challenge_method": "S256", "state": state, "scope": "internal", "resource": cls.MCP})

    @classmethod
    def exchange(cls, code: str, client_id: str, redirect: str, verifier: str) -> dict:
        r = httpx.post(cls.TOKEN, timeout=20, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "client_id": client_id,
            "code_verifier": verifier, "resource": cls.MCP})
        if r.status_code >= 400:
            raise BrokerError(f"Robinhood token exchange failed: {r.status_code} {r.text[:200]}")
        t = r.json()
        return {"client_id": client_id, "access_token": t["access_token"], "refresh_token": t.get("refresh_token"),
                "expires_at": time.time() + float(t.get("expires_in") or 3600) - 120}

    def _token(self) -> str:
        if time.time() >= float(self.b.get("expires_at") or 0):
            if not self.b.get("refresh_token"):
                raise BrokerError("Robinhood authorisation expired — reconnect")
            r = httpx.post(self.TOKEN, timeout=20, data={"grant_type": "refresh_token", "refresh_token": self.b["refresh_token"],
                                                         "client_id": self.b["client_id"], "resource": self.MCP})
            if r.status_code >= 400:
                raise BrokerError("Robinhood token refresh failed — reconnect the account")
            t = r.json()
            self.b.update(access_token=t["access_token"], refresh_token=t.get("refresh_token") or self.b["refresh_token"],
                          expires_at=time.time() + float(t.get("expires_in") or 3600) - 120)
            if self.saver:
                self.saver(self.b)
        return self.b["access_token"]

    # MCP over streamable HTTP
    def _post(self, msg: dict) -> dict | None:
        h = {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
        if self.session:
            h["Mcp-Session-Id"] = self.session
        r = httpx.post(self.MCP, json=msg, headers=h, timeout=30)
        if r.status_code >= 400:
            raise BrokerError(f"Robinhood MCP {r.status_code}: {r.text[:200]}")
        self.session = r.headers.get("mcp-session-id", self.session)
        if "id" not in msg:
            return None
        body = r.text
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            datas = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
            body = datas[-1] if datas else "{}"
        out = json.loads(body or "{}")
        if out.get("error"):
            raise BrokerError(f"Robinhood MCP: {out['error'].get('message')}")
        return out.get("result") or {}

    def _init(self) -> None:
        if self.session:
            return
        self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "signalpha-autopilot", "version": "1.0"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tools(self) -> list[dict]:
        self._init()
        return (self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) or {}).get("tools") or []

    def call(self, name: str, args: dict | None = None) -> Any:
        self._init()
        res = self._post({"jsonrpc": "2.0", "id": secrets.randbelow(10**9), "method": "tools/call",
                          "params": {"name": name, "arguments": args or {}}}) or {}
        if res.get("isError"):
            raise BrokerError(f"Robinhood {name}: {json.dumps(res.get('content'))[:200]}")
        if res.get("structuredContent") is not None:
            return res["structuredContent"]
        texts = [c.get("text") for c in res.get("content") or [] if c.get("type") == "text"]
        try:
            return json.loads(texts[0]) if texts else None
        except (ValueError, TypeError):
            return texts[0] if texts else None

    @staticmethod
    def _find(obj: Any, *keys: str) -> Any:
        """First value under any of `keys`, searching nested dicts and lists."""
        if isinstance(obj, dict):
            for k in keys:
                if k in obj and obj[k] not in (None, ""):
                    return obj[k]
            for v in obj.values():
                f = Robinhood._find(v, *keys)
                if f is not None:
                    return f
        elif isinstance(obj, list):
            for v in obj:
                f = Robinhood._find(v, *keys)
                if f is not None:
                    return f
        return None

    def account(self) -> dict:
        p = self.call("get_portfolio", {"account_number": self.acct} if self.acct else {})
        eq = self._find(p, "equity", "total_equity", "portfolio_value", "market_value")
        cash = self._find(p, "cash", "withdrawable_amount", "cash_balance")
        power = self._find(p, "buying_power")
        return _acct(eq, cash, power, False, self.acct)

    def positions(self) -> list:
        from backend.app.services.strategy_lab import from_alpaca

        raw = self.call("get_equity_positions", {"account_number": self.acct} if self.acct else {})
        items = raw if isinstance(raw, list) else self._find(raw, "results", "positions", "items") or []
        out = []
        for p in items if isinstance(items, list) else []:
            sym = self._find(p, "symbol", "ticker")
            q = float(self._find(p, "quantity", "shares") or 0)
            if sym and q:
                out.append(_pos(from_alpaca(sym), q, self._find(p, "average_buy_price", "average_price"), self.last_price(sym)))
        return out

    def _order_args(self, sym: str, qty: int, side: str) -> dict:
        tool = next((t for t in self.b.get("tools") or [] if t.get("name") == "place_equity_order"), None)
        props = ((tool or {}).get("inputSchema") or {}).get("properties") or {}
        req = set(((tool or {}).get("inputSchema") or {}).get("required") or [])
        if not props:
            raise BrokerError("Robinhood's order tool schema is unknown — reconnect to refresh it")
        pick = lambda *names: next((n for n in names if n in props), None)  # noqa: E731
        f_sym, f_qty, f_side = pick("symbol", "ticker"), pick("quantity", "qty", "shares"), pick("side", "action")
        f_type, f_tif, f_acct = pick("type", "order_type"), pick("time_in_force", "timeInForce"), pick("account_number", "account")
        if not (f_sym and f_qty and f_side):
            raise BrokerError("Robinhood's order tool changed — not mapped, order refused")
        args = {f_sym: sym, f_qty: qty, f_side: side}
        if f_type:
            args[f_type] = "market"
        if f_tif:
            args[f_tif] = "gfd"
        if f_acct and self.acct:
            args[f_acct] = self.acct
        missing = req - set(args)
        if missing:
            raise BrokerError(f"Robinhood's order tool needs {sorted(missing)} — not mapped, order refused")
        return args

    def submit(self, sym: str, qty: int, side: str, tif: str, cid: str) -> dict:
        if side == "sell" and _opening(cid):
            raise BrokerError("short sales are not available in a Robinhood agentic account")
        res = self.call("place_equity_order", self._order_args(sym, qty, side))
        oid = self._find(res, "id", "order_id")
        return {"id": str(oid), "status": "accepted"}

    def order(self, cid: str) -> dict:
        raise BrokerError("Robinhood orders are looked up by id")

    def order_any(self, cid: str, boid: str | None) -> dict:
        res = self.call("get_equity_orders", {"account_number": self.acct} if self.acct else {})
        items = res if isinstance(res, list) else self._find(res, "results", "orders", "items") or []
        for o in items if isinstance(items, list) else []:
            if str(self._find(o, "id", "order_id")) == str(boid):
                st = str(self._find(o, "state", "status") or "").lower()
                status = {"filled": "filled", "cancelled": "canceled", "canceled": "canceled", "rejected": "rejected",
                          "failed": "rejected", "partially_filled": "partially_filled"}.get(st, "accepted")
                return {"id": str(boid), "status": status, "filled_qty": self._find(o, "cumulative_quantity", "filled_quantity") or 0,
                        "filled_avg_price": self._find(o, "average_price", "filled_average_price"), "filled_at": self._find(o, "updated_at")}
        raise BrokerError(f"order {boid} not found at Robinhood")

    def cancel_all(self) -> None:
        res = self.call("get_equity_orders", {"account_number": self.acct} if self.acct else {})
        items = res if isinstance(res, list) else self._find(res, "results", "orders", "items") or []
        for o in items if isinstance(items, list) else []:
            if str(self._find(o, "state", "status") or "").lower() in ("queued", "confirmed", "unconfirmed", "partially_filled", "pending"):
                try:
                    self.call("cancel_equity_order", {"order_id": self._find(o, "id", "order_id")})
                except BrokerError:
                    pass


CATALOG = [
    # key, name, how it connects, paper?, shorts?, status
    {"key": "alpaca", "name": "Alpaca", "via": "keys", "paper": True, "shorts": True, "note": "ap.br.alpaca"},
    {"key": "moomoo", "name": "moomoo", "via": "oauth", "paper": True, "shorts": True, "note": "ap.br.moomoo"},
    {"key": "tradier", "name": "Tradier", "via": "token", "paper": True, "shorts": True, "note": "ap.br.tradier"},
    {"key": "tastytrade", "name": "tastytrade", "via": "grant", "paper": "same_day", "shorts": True, "note": "ap.br.tasty"},
    {"key": "robinhood", "name": "Robinhood", "via": "oauth", "paper": False, "shorts": False, "note": "ap.br.robinhood"},
    {"key": "snaptrade", "name": "E*TRADE · Webull · Public · Wealthsimple · Trading 212", "via": "snaptrade", "paper": "t212",
     "shorts": False, "note": "ap.br.snaptrade"},
    {"key": "ibkr", "name": "Interactive Brokers", "via": None, "paper": None, "shorts": None, "note": "ap.br.ibkr"},
    {"key": "schwab", "name": "Charles Schwab", "via": None, "paper": None, "shorts": None, "note": "ap.br.schwab"},
    {"key": "fidelity", "name": "Fidelity", "via": None, "paper": None, "shorts": None, "note": "ap.br.fidelity"},
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
