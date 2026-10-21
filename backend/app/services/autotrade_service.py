"""Autopilot — runs the direction strategies in brokerage accounts connected to the site.

Each connection (`autotrade_accounts`) is one holder's Alpaca account in one mode, paper
or live: its own strategy picks, sizes, orders, marks and log. The owner signs in through
the site's Telegram, anyone else by email (services/ap_auth.py); a connection is made by
pasting API keys or, when ALPACA_OAUTH_CLIENT_ID/SECRET are set, by Alpaca's OAuth
consent screen. Jobs walk every connection, so a new user is a new row, not a new
deployment.

Strategies are sleeves (services/strategy_lab.py): a holder gives a strategy `alloc` per
cent of the account; it splits that into `slots` equal positions; a signal takes a free
slot, biggest gap first, and is skipped when none is free. The backtest on the page is
this exact sizing run over 2008–2026.

Broker: Alpaca Trading API v2 — plain HTTPS (no desktop gateway on an ARM server), free
paper accounts, market-on-close orders, and since FINRA retired the pattern-day-trader
rule (effective 2026-06-04) no $25,000 floor for the same-day rules. Shorts need margin,
$2,000 of equity and an easy-to-borrow name; otherwise the signal is skipped, not forced.

A session, New York time:
  09:31   run_open      opening prints from the broker feed -> direction calls -> orders
  09:32:30, 09:37, 09:51  run_entries again for opens that printed late (until 10:00)
  15:44   run_closes    market-on-close: exits due today, then follow_gap entries
  15:56   flatten_late  exits the closing auction refused go out at market
  */5     reconcile     fills from the broker; marks every strategy's P&L for the charts

Every order's client_order_id is `sa<account>-<call>-entry|exit`, so a job that runs
twice cannot double an order. Live trading needs live credentials, the holder's typed
acknowledgement, and stays inside LIVE_CAP_PER_TRADE / LIVE_CAP_GROSS. Live connections
are the owner's only unless AUTOPILOT_LIVE_PUBLIC=1: trading other people's money on our
signals is regulated activity (investment-adviser registration, in the US), and that
switch should move only after that is settled.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.services.strategies import ORDER, SPECS
from backend.app.services.strategy_lab import from_alpaca, to_alpaca

NY = ZoneInfo("America/New_York")
BASES = {"paper": "https://paper-api.alpaca.markets", "live": "https://api.alpaca.markets"}
DATA = "https://data.alpaca.markets"
LIVE_ACK = "I UNDERSTAND THIS TRADES REAL MONEY"
SHORT_MIN_EQUITY = 2000.0
ENTRY_DEADLINE = (10, 0)
CLOSE_CUTOFF = (15, 50)
DEAD = ("skipped", "failed", "rejected", "canceled", "expired", "done_for_day")
FINAL = sorted({"filled", "canceled", "expired", "rejected", "done_for_day", "replaced", "failed", "skipped"})


def live_caps() -> tuple[float, float]:
    return (float(os.getenv("LIVE_CAP_PER_TRADE", "1000")), float(os.getenv("LIVE_CAP_GROSS", "5000")))


# Which strategies a new connection starts with, their share of the account and their slots:
# services/strategies.py SPECS (on = the ones that held up after costs and out of sample).
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "strategies": {k: {"on": SPECS[k]["on"], "alloc": float(SPECS[k]["alloc"]), "slots": SPECS[k]["slots"]} for k in ORDER},
    "daily_loss_pct": 3.0, "max_gross_pct": 100.0, "min_price": 5.0,
    "allow_short": True, "notify": True, "live_ack_at": None,
}

DDL = [
    """CREATE TABLE IF NOT EXISTS autotrade_accounts (
        id BIGSERIAL PRIMARY KEY, holder TEXT NOT NULL, broker TEXT NOT NULL DEFAULT 'alpaca',
        mode TEXT NOT NULL, auth TEXT NOT NULL DEFAULT 'key', key_id TEXT NOT NULL, secret_enc TEXT NOT NULL,
        account_hint TEXT, settings JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (holder, broker, mode))""",
    "ALTER TABLE autotrade_accounts ADD COLUMN IF NOT EXISTS auth TEXT NOT NULL DEFAULT 'key'",
    """CREATE TABLE IF NOT EXISTS autotrade_orders (
        id BIGSERIAL PRIMARY KEY, account_id BIGINT NOT NULL, call_id BIGINT, rule TEXT, ticker TEXT NOT NULL,
        leg TEXT NOT NULL, side TEXT NOT NULL, qty NUMERIC NOT NULL, tif TEXT NOT NULL,
        client_order_id TEXT UNIQUE NOT NULL, broker_order_id TEXT, status TEXT NOT NULL,
        submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), filled_qty NUMERIC, filled_avg_price NUMERIC,
        filled_at TIMESTAMPTZ, exit_session DATE, error TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_autotrade_orders_acct ON autotrade_orders (account_id, call_id)",
    """CREATE TABLE IF NOT EXISTS autotrade_events (
        id BIGSERIAL PRIMARY KEY, account_id BIGINT, at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        level TEXT NOT NULL, message TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_autotrade_events_acct ON autotrade_events (account_id, at DESC)",
    """CREATE TABLE IF NOT EXISTS autotrade_marks (
        id BIGSERIAL PRIMARY KEY, account_id BIGINT NOT NULL, strategy TEXT NOT NULL,
        at TIMESTAMPTZ NOT NULL DEFAULT NOW(), pnl NUMERIC NOT NULL, capital NUMERIC NOT NULL, n_open INTEGER NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_autotrade_marks ON autotrade_marks (account_id, strategy, at)",
    """CREATE TABLE IF NOT EXISTS autotrade_vault (
        holder TEXT NOT NULL, kind TEXT NOT NULL, secret_enc TEXT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (holder, kind))""",
]


class BrokerError(Exception):
    pass


def live_allowed(role: str) -> bool:
    return role == "owner" or os.getenv("AUTOPILOT_LIVE_PUBLIC", "0") == "1"


# ───────────────────────────── broker ─────────────────────────────

class Alpaca:
    def __init__(self, mode: str, key_id: str, secret: str, auth: str = "key"):
        self.mode, self.base = mode, BASES[mode]
        self.h = ({"Authorization": f"Bearer {secret}"} if auth == "oauth"
                  else {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret})

    def _req(self, method: str, path: str, base: str | None = None, **kw) -> Any:
        r = httpx.request(method, (base or self.base) + path, headers=self.h, timeout=20, **kw)
        if r.status_code >= 400:
            try:
                msg = r.json().get("message") or r.text
            except Exception:  # noqa: BLE001
                msg = r.text
            raise BrokerError(f"{r.status_code}: {str(msg)[:240]}")
        return r.json() if r.content else None

    def account(self) -> dict: return self._req("GET", "/v2/account")
    def positions(self) -> list:
        """Open positions, symbols in our (Yahoo) spelling."""
        return [{**p, "symbol": from_alpaca(p["symbol"])} for p in self._req("GET", "/v2/positions")]
    def clock(self) -> dict: return self._req("GET", "/v2/clock")
    def asset(self, sym: str) -> dict: return self._req("GET", f"/v2/assets/{to_alpaca(sym)}")
    def cancel_all(self) -> Any: return self._req("DELETE", "/v2/orders")

    def order(self, cid: str) -> dict:
        return self._req("GET", "/v2/orders:by_client_order_id", params={"client_order_id": cid})

    def calendar(self, start: date, end: date) -> list[date]:
        rows = self._req("GET", "/v2/calendar", params={"start": start.isoformat(), "end": end.isoformat()})
        return [date.fromisoformat(r["date"]) for r in rows]

    def history(self, period: str, timeframe: str) -> dict:
        return self._req("GET", "/v2/account/portfolio/history",
                         params={"period": period, "timeframe": timeframe, "intraday_reporting": "market_hours"})

    def last_price(self, sym: str) -> float | None:
        try:
            d = self._req("GET", f"/v2/stocks/{to_alpaca(sym)}/trades/latest", base=DATA, params={"feed": "iex"})
            return float(d["trade"]["p"])
        except Exception:  # noqa: BLE001
            return None

    def submit(self, sym: str, qty: int, side: str, tif: str, cid: str) -> dict:
        return self._req("POST", "/v2/orders", json={"symbol": to_alpaca(sym), "qty": str(qty), "side": side, "type": "market",
                                                     "time_in_force": tif, "client_order_id": cid})


# ───────────────────────────── connections ─────────────────────────────

def _fernet():
    from cryptography.fernet import Fernet

    key = os.getenv("AUTOTRADE_KEY", "").strip()
    if not key:
        path = Path(os.getenv("DATA_DIR", "/app/data")) / "autotrade.key"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(Fernet.generate_key().decode())
            path.chmod(0o600)
        key = path.read_text().strip()
    return Fernet(key.encode())


def _settings(row) -> dict[str, Any]:
    body = row["settings"] if isinstance(row["settings"], dict) else json.loads(row["settings"] or "{}")
    out = {**DEFAULTS, **{k: v for k, v in body.items() if k in DEFAULTS}}
    strat = body.get("strategies") or {}
    out["strategies"] = {k: {**DEFAULTS["strategies"][k], **(strat.get(k) or {})} for k in ORDER}
    return out


def _account(db: Session, account_id: int, holder: str | None = None):
    q = "SELECT * FROM autotrade_accounts WHERE id=:i" + (" AND holder=:h" if holder else "")
    row = db.execute(text(q), {"i": account_id, "h": holder}).mappings().first()
    if row is None:
        raise LookupError("No such connection")
    return row


def _client(row):
    """The broker client for a connection (see services/brokers.py for all but Alpaca)."""
    account_id = row["id"]

    def save(bundle: dict) -> None:  # refreshed tokens, last close's equity
        from backend.app.db.session import SessionLocal

        with SessionLocal() as s:
            s.execute(text("UPDATE autotrade_accounts SET secret_enc=:e, updated_at=NOW() WHERE id=:i"),
                      {"e": _fernet().encrypt(json.dumps(bundle).encode()).decode(), "i": account_id})
            s.commit()
    secret = _fernet().decrypt(row["secret_enc"].encode()).decode()
    return make_client(row.get("broker") or "alpaca", row["mode"], row["key_id"], secret, row.get("auth") or "key", save)


BROKER_NAMES = {"alpaca": "Alpaca", "moomoo": "moomoo", "tradier": "Tradier", "tastytrade": "tastytrade",
                "robinhood": "Robinhood"}


def broker_name(broker: str) -> str:
    if broker.startswith("snaptrade:"):
        return broker.split(":", 1)[1] + " (SnapTrade)"
    return BROKER_NAMES.get(broker, broker)


def make_client(broker: str, mode: str, key_id: str, secret: str, auth: str, save=None):
    if broker == "moomoo":
        from backend.app.services.moomoo_rest import Moomoo

        return Moomoo(mode, key_id, json.loads(secret), saver=save)
    if broker == "tradier":
        from backend.app.services.brokers import Tradier

        return Tradier(mode, key_id, secret)
    if broker == "tastytrade":
        from backend.app.services.brokers import Tasty

        return Tasty(mode, key_id, json.loads(secret), saver=save)
    if broker == "robinhood":
        from backend.app.services.brokers import Robinhood

        return Robinhood(mode, key_id, json.loads(secret), saver=save)
    if broker.startswith("snaptrade:"):
        from backend.app.services.brokers import SnapTrade

        return SnapTrade(mode, key_id, json.loads(secret))
    return Alpaca(mode, key_id, secret, auth)


def _account_headers(db: Session) -> dict[str, str] | None:
    """The house paper account's credentials, for market data when no data key is set."""
    row = db.execute(text("""SELECT * FROM autotrade_accounts WHERE holder='owner' AND auth='key' AND broker='alpaca'
                             ORDER BY (mode='paper') DESC LIMIT 1""")).mappings().first()
    return _client(row).h if row else None


def connect(db: Session, holder: str, role: str, mode: str, key_id: str, secret: str, auth: str = "key",
            broker: str = "alpaca") -> dict[str, Any]:
    if mode not in BASES:
        raise ValueError("mode must be paper or live")
    if broker not in BROKER_NAMES and not broker.startswith("snaptrade:"):
        raise ValueError("unknown broker")
    if mode == "live" and not live_allowed(role):
        raise PermissionError("Live trading is limited to the owner account for now")
    key_id, secret = key_id.strip(), secret.strip()
    if broker == "alpaca" and auth == "key" and mode == "paper" and not key_id.startswith("PK"):
        raise ValueError("These look like live keys — paper keys start with PK")
    if broker == "alpaca" and auth == "key" and mode == "live" and key_id.startswith("PK"):
        raise ValueError("These are paper keys — live keys come from the Live account's dashboard")
    acct = make_client(broker, mode, key_id, secret, auth).account()  # the credentials prove themselves first
    hint = str(acct.get("account_number") or "")[-4:]
    row = db.execute(text("""
        INSERT INTO autotrade_accounts (holder, broker, mode, auth, key_id, secret_enc, account_hint, settings)
        VALUES (:h, :b, :m, :au, :k, :s, :a, CAST(:st AS jsonb))
        ON CONFLICT (holder, broker, mode) DO UPDATE SET key_id=EXCLUDED.key_id, secret_enc=EXCLUDED.secret_enc,
            auth=EXCLUDED.auth, account_hint=EXCLUDED.account_hint, updated_at=NOW()
        RETURNING id"""),
        {"h": holder, "b": broker, "m": mode, "au": auth, "k": key_id, "s": _fernet().encrypt(secret.encode()).decode(),
         "a": hint, "st": json.dumps(DEFAULTS)}).first()
    db.commit()
    event(db, row.id, "info", f"Connected {broker_name(broker)} {mode} account …{hint}" + (" (OAuth)" if auth == "oauth" else ""))
    return {"id": row.id, "broker": broker, "mode": mode, "account_hint": hint, "status": acct.get("status")}


# ── brokers that connect by pasted credentials or their own OAuth (services/brokers.py)

def _vault_get(db: Session, holder: str, kind: str) -> dict | None:
    v = db.execute(text("SELECT secret_enc FROM autotrade_vault WHERE holder=:h AND kind=:k"), {"h": holder, "k": kind}).scalar()
    return json.loads(_fernet().decrypt(v.encode()).decode()) if v else None


def _vault_put(db: Session, holder: str, kind: str, body: dict) -> None:
    db.execute(text("""INSERT INTO autotrade_vault (holder, kind, secret_enc) VALUES (:h, :k, :e)
                       ON CONFLICT (holder, kind) DO UPDATE SET secret_enc=EXCLUDED.secret_enc, updated_at=NOW()"""),
               {"h": holder, "k": kind, "e": _fernet().encrypt(json.dumps(body).encode()).decode()})
    db.commit()


def connect_tradier(db: Session, holder: str, role: str, mode: str, token: str) -> dict[str, Any]:
    from backend.app.services.brokers import Tradier

    accts = Tradier.accounts(mode, token.strip())
    if not accts:
        raise ValueError("This Tradier token has no brokerage account" + (" — paper tokens come from the sandbox dashboard" if mode == "paper" else ""))
    a = next((x for x in accts if x.get("type") == "margin"), accts[0])
    return connect(db, holder, role, mode, str(a["account_number"]), token, broker="tradier")


def connect_tasty(db: Session, holder: str, role: str, mode: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    from backend.app.services.brokers import Tasty

    accts, b = Tasty.accounts(mode, {"client_secret": client_secret.strip(), "refresh_token": refresh_token.strip()})
    if not accts:
        raise ValueError("No tastytrade account under this grant" + (" — sandbox grants come from the cert environment" if mode == "paper" else ""))
    a = accts[0]
    b["margin_or_cash"] = a.get("margin-or-cash")
    return connect(db, holder, role, mode, str(a.get("account-number")), json.dumps(b), auth="oauth", broker="tastytrade")


def _redirect(path: str) -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://signalpha.app").rstrip("/") + path


def robinhood_start(holder: str, role: str) -> str:
    from backend.app.services.ap_auth import _redis
    from backend.app.services.brokers import Robinhood

    if not live_allowed(role):
        raise PermissionError("Robinhood agentic accounts trade real money — live trading is limited to the owner account for now")
    cb = _redirect("/api/v1/autopilot/robinhood/callback")
    cid = Robinhood.client_id(cb)
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(64)[:96]
    _redis().set(f"ap:rhoauth:{state}", json.dumps({"holder": holder, "role": role, "verifier": verifier, "client_id": cid}), ex=600)
    return Robinhood.authorize_url(cid, cb, state, verifier)


def robinhood_finish(db: Session, code: str, state: str) -> dict[str, Any]:
    from backend.app.services.ap_auth import _redis
    from backend.app.services.brokers import Robinhood

    raw = _redis().getdel(f"ap:rhoauth:{state}") if state else None
    if not raw:
        raise ValueError("This authorisation link has expired — start again from the Autopilot page")
    st = json.loads(raw)
    b = Robinhood.exchange(code, st["client_id"], _redirect("/api/v1/autopilot/robinhood/callback"), st["verifier"])
    rh = Robinhood("live", "", b)
    b["tools"] = rh.tools()
    accts = rh.call("get_accounts")
    items = accts if isinstance(accts, list) else Robinhood._find(accts, "results", "accounts", "items") or []
    agentic = [a for a in items if isinstance(a, dict) and "agent" in json.dumps(a).lower()] or (items if isinstance(items, list) else [])
    number = str(Robinhood._find(agentic[0], "account_number", "number", "id")) if agentic else ""
    return connect(db, st["holder"], st["role"], "live", number, json.dumps(b), auth="oauth", broker="robinhood")


def snaptrade_start(db: Session, holder: str, role: str, broker: str | None) -> str:
    from backend.app.services.ap_auth import _redis
    from backend.app.services.brokers import SnapTrade

    if not live_allowed(role):
        raise PermissionError("Brokers connected through SnapTrade trade real money — live trading is limited to the owner account for now")
    u = _vault_get(db, holder, "snaptrade")
    if not u:
        uid = f"sa-{holder}-{secrets.token_hex(4)}"
        u = {"user_id": uid, "user_secret": SnapTrade.register(uid)}
        _vault_put(db, holder, "snaptrade", u)
    state = secrets.token_urlsafe(24)
    _redis().set(f"ap:snapstate:{state}", json.dumps({"holder": holder, "role": role}), ex=1800)
    return SnapTrade.portal(u["user_id"], u["user_secret"], _redirect(f"/api/v1/autopilot/snaptrade/callback?state={state}"), broker)


def snaptrade_finish(db: Session, state: str) -> list[dict[str, Any]]:
    from backend.app.services.ap_auth import _redis
    from backend.app.services.brokers import SnapTrade

    raw = _redis().getdel(f"ap:snapstate:{state}") if state else None
    if not raw:
        raise ValueError("This connection link has expired — start again from the Autopilot page")
    st = json.loads(raw)
    u = _vault_get(db, st["holder"], "snaptrade")
    out = []
    for a in SnapTrade.list_accounts(u["user_id"], u["user_secret"]):
        inst = (a.get("institution_name") or "broker").strip()
        mode = "paper" if "practice" in inst.lower() or "paper" in inst.lower() else "live"
        out.append(connect(db, st["holder"], st["role"], mode, str(a["id"]), json.dumps(u), auth="oauth",
                           broker=f"snaptrade:{inst}"))
    return out


def disconnect(db: Session, holder: str, account_id: int) -> None:
    row = _account(db, account_id, holder)
    try:
        _client(row).cancel_all()
    except Exception:  # noqa: BLE001 - disconnecting must work even if the keys were revoked
        pass
    db.execute(text("DELETE FROM autotrade_accounts WHERE id=:i"), {"i": account_id})
    db.commit()
    event(db, account_id, "warn", "Connection removed; open orders canceled, positions left as they are")


# ── OAuth ("Connect with Alpaca") — only when the site is registered as an Alpaca OAuth app.

def oauth_enabled() -> bool:
    return bool(os.getenv("ALPACA_OAUTH_CLIENT_ID", "").strip() and os.getenv("ALPACA_OAUTH_CLIENT_SECRET", "").strip())


def _redirect_uri() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://signalpha.app").rstrip("/") + "/api/v1/autopilot/oauth/callback"


def oauth_start(holder: str, role: str, mode: str) -> str:
    from backend.app.services.ap_auth import _redis

    if not oauth_enabled():
        raise ValueError("Connect-with-Alpaca is not set up on this server; paste API keys instead")
    if mode == "live" and not live_allowed(role):
        raise PermissionError("Live trading is limited to the owner account for now")
    state = secrets.token_urlsafe(24)
    _redis().set(f"ap:oauth:{state}", json.dumps({"holder": holder, "role": role, "mode": mode}), ex=600)
    return "https://app.alpaca.markets/oauth/authorize?" + urlencode({
        "response_type": "code", "client_id": os.getenv("ALPACA_OAUTH_CLIENT_ID"), "redirect_uri": _redirect_uri(),
        "state": state, "scope": "account:write trading data", "env": mode})


def oauth_finish(db: Session, code: str, state: str) -> dict[str, Any]:
    from backend.app.services.ap_auth import _redis

    raw = _redis().getdel(f"ap:oauth:{state}") if state else None
    if not raw:
        raise ValueError("This authorisation link has expired — start again from the Autopilot page")
    st = json.loads(raw)
    r = httpx.post("https://api.alpaca.markets/oauth/token", timeout=20, data={
        "grant_type": "authorization_code", "code": code, "client_id": os.getenv("ALPACA_OAUTH_CLIENT_ID"),
        "client_secret": os.getenv("ALPACA_OAUTH_CLIENT_SECRET"), "redirect_uri": _redirect_uri()})
    if r.status_code != 200:
        raise BrokerError(f"token exchange failed: {r.status_code} {r.text[:200]}")
    return connect(db, st["holder"], st["role"], st["mode"], "oauth", r.json()["access_token"], auth="oauth")


# ── settings

def save_settings(db: Session, holder: str, account_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    row = _account(db, account_id, holder)
    cur = _settings(row)
    for k, v in patch.items():
        if k not in DEFAULTS or k == "live_ack_at":
            continue
        if k == "strategies":
            for sk, sv in (v or {}).items():
                if sk not in cur["strategies"] or not isinstance(sv, dict):
                    continue
                s = cur["strategies"][sk]
                if "on" in sv:
                    s["on"] = bool(sv["on"])
                if "alloc" in sv:
                    s["alloc"] = round(min(max(float(sv["alloc"]), 0.0), 100.0), 1)
                if "slots" in sv:
                    s["slots"] = int(min(max(int(sv["slots"]), 1), 30))
        elif k in ("enabled", "allow_short", "notify"):
            cur[k] = bool(v)
        else:
            cur[k] = max(0.0, float(v))
    used = sum(s["alloc"] for s in cur["strategies"].values() if s["on"])
    if used > 100.0001:
        raise ValueError(f"Strategies add up to {used:.0f}% of the account — keep it at 100% or less")
    cur["max_gross_pct"] = min(cur["max_gross_pct"], 200.0)
    if row["mode"] == "live" and cur["enabled"] and not cur.get("live_ack_at"):
        raise PermissionError("Acknowledge live trading before switching it on")
    _write(db, account_id, cur)
    on = [k for k, s in cur["strategies"].items() if s["on"]]
    event(db, account_id, "info", "Autopilot " + ("ON" if cur["enabled"] else "off") + " · running: " + (", ".join(on) or "none"))
    return cur


def acknowledge_live(db: Session, holder: str, account_id: int, ack: str) -> dict[str, Any]:
    row = _account(db, account_id, holder)
    if row["mode"] != "live":
        raise ValueError("This is not a live connection")
    if ack.strip() != LIVE_ACK:
        raise ValueError("Type the acknowledgement exactly")
    cur = _settings(row)
    cur["live_ack_at"] = datetime.now(timezone.utc).isoformat()
    _write(db, account_id, cur)
    event(db, account_id, "warn", "Live trading acknowledged")
    return cur


def _write(db: Session, account_id: int, body: dict[str, Any]) -> None:
    db.execute(text("UPDATE autotrade_accounts SET settings=CAST(:b AS jsonb), updated_at=NOW() WHERE id=:i"),
               {"b": json.dumps(body), "i": account_id})
    db.commit()


def event(db: Session, account_id: int | None, level: str, message: str) -> None:
    db.execute(text("INSERT INTO autotrade_events (account_id, level, message) VALUES (:a, :l, :m)"),
               {"a": account_id, "l": level, "m": message[:500]})
    db.commit()


def _notify(row, message: str) -> None:
    """Pings go to the site's Telegram chat, for the owner's connections only."""
    if row["holder"] != "owner" or not _settings(row).get("notify"):
        return
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if tok and chat:
        try:
            httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=8,
                       json={"chat_id": chat, "text": f"Autopilot ({row['mode']}) · {message}"})
        except Exception:  # noqa: BLE001
            pass


# ───────────────────────────── the session ─────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone(NY)


def _session_after(alp: Alpaca, d: date, n: int) -> date:
    if n <= 0:
        return d
    days = [x for x in alp.calendar(d, d + timedelta(days=n * 2 + 10)) if x > d]
    return days[n - 1] if len(days) >= n else d + timedelta(days=n)


def _record(db: Session, **o) -> None:
    db.execute(text("""
        INSERT INTO autotrade_orders (account_id, call_id, rule, ticker, leg, side, qty, tif, client_order_id,
                                      broker_order_id, status, exit_session, error)
        VALUES (:account_id, :call_id, :rule, :ticker, :leg, :side, :qty, :tif, :cid, :boid, :status, :exit_session, :error)
        ON CONFLICT (client_order_id) DO NOTHING"""),
        {"account_id": o["account_id"], "call_id": o.get("call_id"), "rule": o.get("rule"), "ticker": o["ticker"],
         "leg": o["leg"], "side": o["side"], "qty": o.get("qty", 0), "tif": o.get("tif", "day"), "cid": o["cid"],
         "boid": o.get("boid"), "status": o["status"], "exit_session": o.get("exit_session"), "error": o.get("error")})
    db.commit()


def _open_trades(db: Session, account_id: int) -> list[dict[str, Any]]:
    """Entries that are live (filled or working) and have no exit order working or done."""
    return [dict(r) for r in db.execute(text("""
        SELECT e.* FROM autotrade_orders e
        WHERE e.account_id=:a AND e.leg='entry' AND (e.filled_qty > 0 OR e.status <> ALL(:dead))
          AND NOT EXISTS (SELECT 1 FROM autotrade_orders x WHERE x.account_id=e.account_id AND x.call_id=e.call_id
                          AND x.leg LIKE 'exit%' AND (x.filled_qty > 0 OR x.status <> ALL(:dead)))"""),
        {"a": account_id, "dead": list(DEAD)}).mappings().all()]


def _last_equity(db: Session | None, account_id: int | None) -> float | None:
    """Yesterday's last equity mark, for brokers that do not report a previous close."""
    if db is None or account_id is None:
        return None
    v = db.execute(text("""SELECT pnl FROM autotrade_marks WHERE account_id=:a AND strategy='_equity'
                           AND (at AT TIME ZONE 'America/New_York')::date < :d ORDER BY at DESC LIMIT 1"""),
                   {"a": account_id, "d": _now().date()}).scalar()
    return float(v) if v is not None else None


def _guard(s: dict, alp: Alpaca, mode: str, db: Session | None = None, account_id: int | None = None) -> tuple[bool, str, dict]:
    if not s["enabled"]:
        return False, "Autopilot is off", {}
    if mode == "live" and not s.get("live_ack_at"):
        return False, "Live trading not acknowledged", {}
    acct = alp.account()
    if acct.get("trading_blocked") or acct.get("account_blocked"):
        return False, "The broker has blocked trading on this account", acct
    eq = float(acct.get("equity", 0))
    last = acct.get("last_equity")
    last = float(last) if last not in (None, "") else _last_equity(db, account_id)
    day_pl = eq - last if last else 0.0
    if day_pl <= -abs(s["daily_loss_pct"]) / 100 * eq:
        return False, f"Daily loss limit reached ({day_pl:+.2f})", acct
    return True, "", acct


class _Book:
    """What one account holds right now: gross exposure for the limits, each ticker's direction
    (a long and a short in the same name cannot live in one account), slots per strategy."""

    def __init__(self, db: Session, row, alp: Alpaca):
        self.positions = alp.positions()
        self.gross = sum(abs(float(p["market_value"] or 0)) for p in self.positions)
        self.sides: dict[str, set[str]] = {}
        for p in self.positions:
            self.sides.setdefault(p["symbol"], set()).add("short" if float(p["qty"]) < 0 else "long")
        self.trades = _open_trades(db, row["id"])
        for t in self.trades:
            self.sides.setdefault(t["ticker"], set()).add("short" if t["side"] == "sell" else "long")
        self.slots_used: dict[str, int] = {}
        for t in self.trades:
            self.slots_used[t["rule"]] = self.slots_used.get(t["rule"], 0) + 1

    def same_strategy(self, rule: str, ticker: str) -> bool:
        return any(t["rule"] == rule and t["ticker"] == ticker for t in self.trades)


def _place(db: Session, row, s: dict, alp: Alpaca, c, *, tif: str, book: _Book, acct: dict,
           notional: float | None = None) -> bool:
    """One entry for one signal (a direction call, a strategy signal, or a target), inside every limit."""
    from backend.app.services.direction_service import RULES

    st = s["strategies"][c["rule"]]
    equity = float(acct.get("equity", 0))
    short = c["side"] == "SHORT"
    side = "sell" if short else "buy"
    cid = f"sa{row['id']}-{c['id']}-entry"
    per = notional if notional is not None else equity * st["alloc"] / 100 / max(st["slots"], 1)
    max_gross = equity * s["max_gross_pct"] / 100
    if row["mode"] == "live":
        cap_trade, cap_gross = live_caps()
        per, max_gross = min(per, cap_trade), min(max_gross, cap_gross)
    skip = None
    if not st["on"]:
        skip = "strategy switched off"
    elif book.slots_used.get(c["rule"], 0) >= st["slots"]:
        skip = f"all {st['slots']} slots in use"
    elif ("long" if short else "short") in book.sides.get(c["ticker"], set()):
        skip = "the account holds this ticker the other way"
    elif book.same_strategy(c["rule"], c["ticker"]):
        skip = "this strategy already holds this ticker"
    elif short and (not s["allow_short"] or not acct.get("shorting_enabled") or equity < SHORT_MIN_EQUITY):
        skip = "shorting unavailable on this account (needs a margin account with $2,000; SnapTrade and Robinhood agentic accounts cannot short)"
    asset = None
    if not skip:
        try:
            asset = alp.asset(c["ticker"])
        except BrokerError as exc:
            skip = f"asset lookup failed: {exc}"
    if not skip and not asset.get("tradable"):
        skip = "not tradable at this broker"
    if not skip and short and not (asset.get("shortable") and asset.get("easy_to_borrow")):
        skip = "not easy to borrow"
    px = None if skip else alp.last_price(c["ticker"])
    if not skip and (px is None or px < s["min_price"]):
        skip = "no live price" if px is None else f"price ${px:.2f} below the ${s['min_price']:.0f} minimum"
    qty = 0 if skip else int(per // px)
    if not skip and qty < 1:
        skip = f"${per:,.0f} buys no whole share at ${px:.2f}"
    if not skip and book.gross + qty * px > max_gross:
        skip = "account exposure limit reached"
    base = dict(account_id=row["id"], call_id=c["id"], rule=c["rule"], ticker=c["ticker"], leg="entry", side=side, tif=tif, cid=cid)
    if skip:
        _record(db, **base, qty=0, status="skipped", error=skip)
        event(db, row["id"], "skip", f"{c['ticker']} {c['rule']} skipped — {skip}")
        return False
    try:
        o = alp.submit(c["ticker"], qty, side, tif, cid)
    except BrokerError as exc:
        _record(db, **base, qty=qty, status="failed", error=str(exc))
        event(db, row["id"], "error", f"{c['ticker']} entry failed: {exc}")
        return False
    exit_session = c["exit_session"] if "exit_session" in c else _session_after(alp, c["session"], RULES[c["rule"]]["hold"])
    _record(db, **base, qty=qty, boid=o["id"], status=o["status"], exit_session=exit_session)
    book.gross += qty * px
    book.sides.setdefault(c["ticker"], set()).add("short" if short else "long")
    book.trades.append({"rule": c["rule"], "ticker": c["ticker"], "side": side})
    book.slots_used[c["rule"]] = book.slots_used.get(c["rule"], 0) + 1
    how = "on the close" if tif == "cls" else "at market"
    detail = f"gap {c['gap_x']:+.1f}×" if c.get("gap_x") is not None else ""
    until = f"exit {exit_session}" if exit_session else "held until the rule changes"
    event(db, row["id"], "trade", " · ".join(x for x in (f"{side.upper()} {qty} {c['ticker']} {how}", c["rule"], detail, until) if x))
    _notify(row, f"{side.upper()} {qty} {c['ticker']} {how} ({c['rule']})")
    return True


def _accounts(db: Session, enabled_only: bool) -> list:
    q = "SELECT * FROM autotrade_accounts" + (" WHERE (settings->>'enabled')::boolean" if enabled_only else "")
    return list(db.execute(text(q)).mappings())


def uses_moc(row) -> bool:
    """Market-on-close orders only where they fill: Alpaca live. Alpaca's paper simulator
    accepts them and lets every one expire at 16:00 (seen 2026-10-20); moomoo's simulator
    has no such order. Everyone else closes with a market order at 15:58:20."""
    return (row.get("broker") or "alpaca") == "alpaca" and row["mode"] == "live"


def sweep_overdue(db: Session, row, alp, now: datetime) -> int:
    """Close at market every position the bot opened whose exit session has passed and whose
    exit never filled — so one missed closing order cannot turn into an open-ended hold."""
    n = 0
    for o in _open_trades(db, row["id"]):
        if not o["exit_session"] or o["exit_session"] >= now.date() or not (o["filled_qty"] or 0) > 0:
            continue
        side = "buy" if o["side"] == "sell" else "sell"
        q = int(o["filled_qty"])
        cid = f"sa{row['id']}-{o['call_id']}-exit-{now:%m%d}"
        base = dict(account_id=row["id"], call_id=o["call_id"], rule=o["rule"], ticker=o["ticker"], leg="exit-late",
                    side=side, qty=q, tif="day", cid=cid)
        try:
            r = alp.submit(o["ticker"], q, side, "day", cid)
            _record(db, **base, boid=r["id"], status=r["status"])
            event(db, row["id"], "warn", f"{side.upper()} {q} {o['ticker']} at market — overdue exit "
                                         f"(due {o['exit_session']}, its closing order did not fill)")
            n += 1
        except BrokerError as exc:
            _record(db, **base, status="failed", error=str(exc))
            event(db, row["id"], "error", f"{o['ticker']} overdue exit failed: {exc}")
            _notify(row, f"⚠ could not close overdue {o['ticker']}: {exc}")
    return n


def run_open(db: Session) -> dict[str, Any]:
    """Seconds after the bell: overdue exits first, then the opening prints from the broker
    feed, the day's calls and their orders."""
    from backend.app.services import direction_service as ds
    from backend.app.services.strategy_lab import opens_today

    now = _now()
    if now.weekday() >= 5 or (now.hour, now.minute) < (9, 30) or (now.hour, now.minute) >= ENTRY_DEADLINE:
        return {"why": "outside the entry window"}
    swept = {}
    for row in _accounts(db, False):
        try:
            k = sweep_overdue(db, row, _client(row), now)
            if k:
                swept[row["id"]] = k
        except Exception as exc:  # noqa: BLE001
            event(db, row["id"], "error", f"overdue sweep: {exc}")
    cands = ds.candidates(db, now.date())
    opens = opens_today(sorted({c["ticker"] for c in cands}), db) if cands else {}
    issued = ds.issue_due(db, opens=opens) if cands else {"issued": 0}
    return {"swept": swept, "candidates": len(cands), "opened": len(opens), "issued": issued, "entries": run_entries(db)}


def run_entries(db: Session) -> dict[str, Any]:
    """Market orders for today's open-entry calls, in every enabled connection."""
    now = _now()
    if now.weekday() >= 5 or (now.hour, now.minute) < (9, 30) or (now.hour, now.minute) >= ENTRY_DEADLINE:
        return {"why": "outside the entry window"}
    from backend.app.services.strategies import signals_for

    calls = list(db.execute(text("""SELECT * FROM direction_calls WHERE session=:d AND entry='open' AND origin='open'
                                    ORDER BY abs(gap_x) DESC"""), {"d": now.date()}).mappings())
    calls += signals_for(db, now.date(), "open")
    out = {}
    for row in _accounts(db, True):
        s = _settings(row)
        try:
            done = {r[0] for r in db.execute(text("SELECT call_id FROM autotrade_orders WHERE account_id=:a AND leg='entry'"),
                                             {"a": row["id"]}).all()}
            todo = [c for c in calls if c["id"] not in done]
            if not todo:
                out[row["id"]] = 0
                continue
            alp = _client(row)
            ok, why, acct = _guard(s, alp, row["mode"], db, row["id"])
            if not ok:
                out[row["id"]] = why
                continue
            book = _Book(db, row, alp)
            out[row["id"]] = sum(_place(db, row, s, alp, c, tif="day", book=book, acct=acct) for c in todo)
        except Exception as exc:  # noqa: BLE001 - one broken connection must not stop the others
            event(db, row["id"], "error", f"entries: {exc}")
            out[row["id"]] = f"error: {exc}"
    return {"calls": len(calls), "accounts": out}


def run_closes(db: Session, phase: str = "moc") -> dict[str, Any]:
    """Closing orders: exits due today (every connection), then follow_gap entries (enabled ones).

    phase "moc" (15:44): connections that take market-on-close orders (uses_moc), before
    Alpaca's 15:50 cutoff. phase "late" (15:58:20): everyone else, at market."""
    now = _now()
    cutoff = CLOSE_CUTOFF if phase == "moc" else (16, 0)
    if now.weekday() >= 5 or (now.hour, now.minute) >= cutoff:
        return {"why": "after the closing-order cutoff"}
    tif = "cls" if phase == "moc" else "day"
    out = {}
    for row in _accounts(db, False):
        if uses_moc(row) != (phase == "moc"):
            continue
        s = _settings(row)
        try:
            alp = _client(row)
            placed = sweep_overdue(db, row, alp, now) if phase == "late" else 0
            # Exits run even if Autopilot was switched off after the entry: a position the
            # bot opened is a position the bot closes.
            for o in _open_trades(db, row["id"]):
                if not o["exit_session"] or o["exit_session"] > now.date() or not (o["filled_qty"] or 0) > 0:
                    continue
                side = "buy" if o["side"] == "sell" else "sell"
                cid = f"sa{row['id']}-{o['call_id']}-exit"
                q = int(o["filled_qty"])
                base = dict(account_id=row["id"], call_id=o["call_id"], rule=o["rule"], ticker=o["ticker"], leg="exit",
                            side=side, qty=q, tif=tif, cid=cid)
                try:
                    r = alp.submit(o["ticker"], q, side, tif, cid)
                    _record(db, **base, boid=r["id"], status=r["status"])
                    placed += 1
                    how = "on the close" if tif == "cls" else "at market before the close"
                    event(db, row["id"], "trade", f"{side.upper()} {q} {o['ticker']} {how} · exit · {o['rule']}")
                except BrokerError as exc:
                    _record(db, **base, status="failed", error=str(exc))
                    event(db, row["id"], "error", f"{o['ticker']} closing exit failed: {exc}" + (" — market order at 15:56" if tif == "cls" else ""))
            placed += _close_targets(db, row, s, alp, tif, now)
            ok, why, acct = _guard(s, alp, row["mode"], db, row["id"])
            if ok:
                from backend.app.services.strategies import signals_for

                done = {r[0] for r in db.execute(text("SELECT call_id FROM autotrade_orders WHERE account_id=:a AND leg='entry'"),
                                                 {"a": row["id"]}).all()}
                calls = [c for c in db.execute(text("""SELECT * FROM direction_calls WHERE session=:d AND rule='follow_gap'
                                                       ORDER BY abs(gap_x) DESC"""), {"d": now.date()}).mappings()]
                calls += signals_for(db, now.date(), "close")
                calls = [c for c in calls if c["id"] not in done and s["strategies"].get(c["rule"], {}).get("on")]
                book = _Book(db, row, alp) if calls or _targets_today(db, now) else None
                if calls:
                    placed += sum(_place(db, row, s, alp, c, tif=tif, book=book, acct=acct) for c in calls)
                if book is not None:
                    placed += _open_targets(db, row, s, alp, tif, now, book, acct)
            out[row["id"]] = placed
        except Exception as exc:  # noqa: BLE001
            event(db, row["id"], "error", f"closes: {exc}")
            out[row["id"]] = f"error: {exc}"
    return {"accounts": out}


def _targets_today(db: Session, now: datetime) -> dict:
    from backend.app.services.strategies import targets_for

    return targets_for(db, now.date())


def _target_trades(db: Session, account_id: int, key: str) -> list[dict]:
    return [t for t in _open_trades(db, account_id) if t["rule"] == key]


def _close_targets(db: Session, row, s: dict, alp, tif: str, now: datetime) -> int:
    """Target strategies: sell what today's weights dropped (or everything, if the strategy is off)."""
    n = 0
    for key, w in _targets_today(db, now).items():
        on = s["strategies"].get(key, {}).get("on") and s["enabled"]
        for t in _target_trades(db, row["id"], key):
            if on and t["ticker"] in w:
                continue
            if not (t["filled_qty"] or 0) > 0:
                continue
            side = "buy" if t["side"] == "sell" else "sell"
            q = int(t["filled_qty"])
            cid = f"sa{row['id']}-{t['call_id']}-exit"
            base = dict(account_id=row["id"], call_id=t["call_id"], rule=key, ticker=t["ticker"], leg="exit", side=side,
                        qty=q, tif=tif, cid=cid)
            try:
                r = alp.submit(t["ticker"], q, side, tif, cid)
                _record(db, **base, boid=r["id"], status=r["status"])
                event(db, row["id"], "trade", f"{side.upper()} {q} {t['ticker']} · {key} rebalance")
                n += 1
            except BrokerError as exc:
                _record(db, **base, status="failed", error=str(exc))
                event(db, row["id"], "error", f"{t['ticker']} {key} rebalance exit failed: {exc}")
    return n


def _open_targets(db: Session, row, s: dict, alp, tif: str, now: datetime, book: _Book, acct: dict) -> int:
    """Target strategies: buy what today's weights added, sized sleeve x weight."""
    from backend.app.services.strategies import target_signal

    n = 0
    equity = float(acct.get("equity", 0))
    for key, w in _targets_today(db, now).items():
        st = s["strategies"].get(key)
        if not st or not st["on"]:
            continue
        held = {t["ticker"] for t in _target_trades(db, row["id"], key)}
        for ticker, weight in w.items():
            if ticker in held or weight <= 0:
                continue
            c = target_signal(db, key, ticker, now.date())
            done = db.execute(text("SELECT 1 FROM autotrade_orders WHERE account_id=:a AND call_id=:c AND leg='entry'"),
                              {"a": row["id"], "c": c["id"]}).first()
            if done:
                continue
            n += _place(db, row, s, alp, c, tif=tif, book=book, acct=acct, notional=equity * st["alloc"] / 100 * float(weight))
    return n


def flatten_late(db: Session) -> dict[str, Any]:
    """Exits the closing auction refused go out as plain market orders before the bell."""
    now = _now()
    if now.weekday() >= 5:
        return {}
    out = {}
    rows = db.execute(text("""
        SELECT o.*, a.mode, a.auth, a.key_id, a.secret_enc, a.holder, a.settings FROM autotrade_orders o
        JOIN autotrade_accounts a ON a.id = o.account_id
        WHERE o.leg='exit' AND o.tif='cls' AND o.status IN ('failed','rejected','canceled','expired')
          AND (o.submitted_at AT TIME ZONE 'America/New_York')::date = :d"""), {"d": now.date()}).mappings().all()
    for o in rows:
        cid = f"{o['client_order_id']}-mkt"
        try:
            r = _client(o).submit(o["ticker"], int(o["qty"]), o["side"], "day", cid)
            _record(db, account_id=o["account_id"], call_id=o["call_id"], rule=o["rule"], ticker=o["ticker"],
                    leg="exit-fallback", side=o["side"], qty=int(o["qty"]), cid=cid, boid=r["id"], status=r["status"])
            event(db, o["account_id"], "warn", f"{o['ticker']} exit sent at market after the closing auction missed")
            out[o["ticker"]] = "sent"
        except Exception as exc:  # noqa: BLE001
            event(db, o["account_id"], "error", f"{o['ticker']} market exit failed: {exc} — needs a manual close")
            _notify(o, f"⚠ could not close {o['ticker']}: {exc}")
            out[o["ticker"]] = str(exc)
    return out


def reconcile(db: Session) -> dict[str, Any]:
    """Fills from the broker, then a P&L mark for every strategy in every connection."""
    changed = 0
    for row in _accounts(db, False):
        open_orders = db.execute(text("""SELECT * FROM autotrade_orders WHERE account_id=:a AND broker_order_id IS NOT NULL
                                         AND status <> ALL(:final)"""), {"a": row["id"], "final": FINAL}).mappings().all()
        try:
            alp = _client(row)
        except Exception:  # noqa: BLE001
            continue
        for o in open_orders:
            try:
                r = (alp.order_any(o["client_order_id"], o["broker_order_id"]) if hasattr(alp, "order_any")
                     else alp.order(o["client_order_id"]))
            except BrokerError:
                continue
            fq = float(r.get("filled_qty") or 0)
            price = float(r["filled_avg_price"]) if r.get("filled_avg_price") else None
            if r["status"] == o["status"] and fq == float(o["filled_qty"] or 0):
                continue
            db.execute(text("""UPDATE autotrade_orders SET status=:s, filled_qty=:q, filled_avg_price=:p,
                               filled_at=CAST(:t AS timestamptz) WHERE id=:i"""),
                       {"s": r["status"], "q": fq, "p": price, "t": r.get("filled_at"), "i": o["id"]})
            db.commit()
            changed += 1
            if r["status"] == "filled" and price:
                event(db, row["id"], "fill", f"{o['side'].upper()} {int(fq)} {o['ticker']} filled at ${price:.2f} · {o['leg']}")
                _notify(row, f"filled {o['side'].upper()} {int(fq)} {o['ticker']} @ ${price:.2f} ({o['leg']}, {o['rule']})")
        try:
            mark(db, row, alp)
        except Exception as exc:  # noqa: BLE001
            event(db, row["id"], "error", f"marks: {exc}")
    return {"updated": changed}


# ───────────────────────────── marks and P&L ─────────────────────────────

def _ledger(db: Session, account_id: int) -> list[dict[str, Any]]:
    """Every filled entry with its exit fill if there is one."""
    rows = db.execute(text("""
        SELECT e.call_id, e.rule, e.ticker, e.side, e.filled_qty AS qty, e.filled_avg_price AS entry, e.filled_at AS opened,
               e.exit_session, x.filled_avg_price AS exit, x.filled_at AS closed
        FROM autotrade_orders e
        LEFT JOIN LATERAL (SELECT * FROM autotrade_orders x WHERE x.account_id=e.account_id AND x.call_id=e.call_id
                           AND x.leg LIKE 'exit%' AND x.filled_qty > 0 ORDER BY x.filled_at DESC LIMIT 1) x ON TRUE
        WHERE e.account_id=:a AND e.leg='entry' AND e.filled_qty > 0
        ORDER BY e.filled_at DESC"""), {"a": account_id}).mappings().all()
    return [dict(r) for r in rows]


def _pnl(t: dict, px: float | None) -> float | None:
    sign = 1 if t["side"] == "buy" else -1
    q, en = float(t["qty"]), float(t["entry"])
    out = t["exit"] if t["exit"] is not None else px
    return None if out is None else sign * (float(out) - en) * q


def mark(db: Session, row, alp: Alpaca | None = None) -> None:
    """One P&L mark per running strategy: realised + open at the broker's current prices."""
    now = _now()
    if now.weekday() >= 5 or not ((9, 30) <= (now.hour, now.minute) <= (16, 10)):
        return
    alp = alp or _client(row)
    s = _settings(row)
    acct = alp.account()
    equity = float(acct.get("equity", 0))
    db.execute(text("INSERT INTO autotrade_marks (account_id, strategy, pnl, capital, n_open) VALUES (:a, '_equity', :e, :e, 0)"),
               {"a": row["id"], "e": round(equity, 2)})
    if (row.get("broker") or "alpaca") == "moomoo" and (now.hour, now.minute) >= (16, 0) and getattr(alp, "saver", None):
        alp.b["last_equity"] = equity  # moomoo reports no previous close; the daily-loss guard needs one
        alp.saver(alp.b)
    prices = {p["symbol"]: float(p["current_price"]) for p in alp.positions() if p.get("current_price")}
    ledger = _ledger(db, row["id"])
    for k in ORDER:
        st = s["strategies"][k]
        mine = [t for t in ledger if t["rule"] == k]
        if not st["on"] and not mine:
            continue
        pnl, n_open = 0.0, 0
        for t in mine:
            px = prices.get(t["ticker"]) if t["exit"] is None else None
            if t["exit"] is None:
                n_open += 1
                if px is None:
                    px = alp.last_price(t["ticker"]) or float(t["entry"])
            pnl += _pnl(t, px) or 0.0
        db.execute(text("INSERT INTO autotrade_marks (account_id, strategy, pnl, capital, n_open) VALUES (:a, :s, :p, :c, :n)"),
                   {"a": row["id"], "s": k, "p": round(pnl, 2), "c": round(equity * st["alloc"] / 100, 2), "n": n_open})
    db.commit()


def strategy_candles(db: Session, account_id: int, key: str) -> list[dict[str, Any]]:
    """Daily candles of a strategy's time-weighted return in this account, from the marks.

    Each session's return is that session's P&L change over the money the strategy had
    that morning; sessions chain, so changing the allocation does not bend the line."""
    from backend.app.services.strategy_lab import candles

    rows = db.execute(text("""SELECT at, pnl, capital FROM autotrade_marks WHERE account_id=:a AND strategy=:s
                              ORDER BY at"""), {"a": account_id, "s": key}).mappings().all()
    if not rows:
        return []
    pts, idx, day, base_pnl, cap = [], 1.0, None, 0.0, 0.0
    prev_pnl = 0.0
    for r in rows:
        d = r["at"].astimezone(NY).date()
        if d != day:
            if day is not None:
                idx = idx * (1 + (prev_pnl - base_pnl) / cap) if cap > 0 else idx
            day, base_pnl, cap = d, prev_pnl, float(r["capital"])
        prev_pnl = float(r["pnl"])
        v = idx * (1 + (prev_pnl - base_pnl) / cap) if cap > 0 else idx
        pts.append((r["at"].isoformat(), round((v - 1) * 100, 4)))
    return candles(pts, "D")


def equity_candles(db: Session, account_id: int) -> list[dict[str, Any]]:
    """Daily candles of the account's return from Autopilot's own five-minute equity marks."""
    from backend.app.services.strategy_lab import candles

    rows = db.execute(text("""SELECT at, pnl FROM autotrade_marks WHERE account_id=:a AND strategy='_equity' ORDER BY at"""),
                      {"a": account_id}).all()
    if not rows:
        return []
    base = float(rows[0].pnl) or 1.0
    return candles([(r.at.isoformat(), round((float(r.pnl) / base - 1) * 100, 4)) for r in rows], "D")


def account_candles(alp) -> list[dict[str, Any]]:
    """Daily candles of the whole account's return, from the broker's own equity history."""
    from backend.app.services.strategy_lab import candles

    pts: list[tuple[str, float]] = []
    try:
        long = alp.history("1A", "1D")
        intr = alp.history("1M", "15Min")
    except BrokerError:
        return []
    first_intraday = min(intr.get("timestamp") or [10**12])
    for ts, eq in zip(long.get("timestamp") or [], long.get("equity") or []):
        if eq and ts < first_intraday:
            pts.append((datetime.fromtimestamp(ts, timezone.utc).isoformat(), float(eq)))
    for ts, eq in zip(intr.get("timestamp") or [], intr.get("equity") or []):
        if eq:
            pts.append((datetime.fromtimestamp(ts, timezone.utc).isoformat(), float(eq)))
    if not pts:
        return []
    base = pts[0][1]
    return candles([(t, round((v / base - 1) * 100, 4)) for t, v in pts], "D")


def kill(db: Session, holder: str, account_id: int, flatten: bool) -> dict[str, Any]:
    """Autopilot off, working orders canceled; with flatten, every position the bot opened closed at market."""
    row = _account(db, account_id, holder)
    cur = _settings(row)
    cur["enabled"] = False
    _write(db, account_id, cur)
    out: dict[str, Any] = {"enabled": False, "closed": []}
    try:
        alp = _client(row)
        alp.cancel_all()
        out["orders_canceled"] = True
        if flatten:
            for t in _open_trades(db, account_id):
                if not (t["filled_qty"] or 0) > 0:
                    continue
                side = "buy" if t["side"] == "sell" else "sell"
                cid = f"sa{account_id}-{t['call_id']}-exit-kill"
                try:
                    r = alp.submit(t["ticker"], int(t["filled_qty"]), side, "day", cid)
                    _record(db, account_id=account_id, call_id=t["call_id"], rule=t["rule"], ticker=t["ticker"],
                            leg="exit-kill", side=side, qty=int(t["filled_qty"]), cid=cid, boid=r["id"], status=r["status"])
                    out["closed"].append(t["ticker"])
                except BrokerError as exc:
                    out.setdefault("errors", []).append(f"{t['ticker']}: {exc}")
    except BrokerError as exc:
        out["error"] = str(exc)
    event(db, account_id, "warn", "KILL SWITCH — Autopilot off, orders canceled"
          + (f", closed {', '.join(out['closed']) or 'nothing'}" if flatten else ""))
    _notify(row, "kill switch" + (" — closing the bot's positions" if flatten else ""))
    return out


# ───────────────────────────── read side ─────────────────────────────

def accounts_of(db: Session, holder: str) -> list[dict[str, Any]]:
    rows = db.execute(text("SELECT * FROM autotrade_accounts WHERE holder=:h ORDER BY broker, mode DESC"), {"h": holder}).mappings().all()
    return [{"id": r["id"], "mode": r["mode"], "broker": r["broker"], "auth": r["auth"], "account_hint": r["account_hint"],
             "key_hint": "OAuth" if r["auth"] == "oauth" else r["key_id"][:4] + "…" + r["key_id"][-2:],
             "label": broker_name(r["broker"]) + " · " + r["mode"],
             "name": broker_name(r["broker"]),
             "settings": _settings(r), "created_at": r["created_at"].isoformat()} for r in rows]


def broker_catalog() -> list[dict[str, Any]]:
    from backend.app.services.brokers import CATALOG, SnapTrade

    out = []
    for b in CATALOG:
        b = dict(b)
        if b["key"] == "snaptrade":
            b["ready"] = SnapTrade.enabled()
        elif b["key"] == "alpaca":
            b["ready"], b["oauth"] = True, oauth_enabled()
        else:
            b["ready"] = b["via"] is not None
        out.append(b)
    return out


def overview(db: Session, holder: str, role: str) -> dict[str, Any]:
    cap_trade, cap_gross = live_caps()
    return {"holder": holder, "role": role, "live_allowed": live_allowed(role), "live_ack_phrase": LIVE_ACK,
            "oauth": oauth_enabled(), "moomoo": True, "defaults": DEFAULTS, "brokers": broker_catalog(),
            "caps": {"live_per_trade": cap_trade, "live_gross": cap_gross, "short_min_equity": SHORT_MIN_EQUITY},
            "accounts": accounts_of(db, holder), "now_et": _now().isoformat()}


def state(db: Session, holder: str, account_id: int) -> dict[str, Any]:
    row = _account(db, account_id, holder)
    s = _settings(row)
    body: dict[str, Any] = {"id": row["id"], "broker": row["broker"], "mode": row["mode"], "auth": row["auth"], "settings": s,
                            "account_hint": row["account_hint"]}
    prices: dict[str, float] = {}
    try:
        alp = _client(row)
        a = alp.account()
        body["account"] = {k: a.get(k) for k in ("status", "equity", "last_equity", "cash", "buying_power", "long_market_value",
                                                  "short_market_value", "shorting_enabled", "multiplier",
                                                  "trading_blocked", "account_blocked")}
        pos = alp.positions()
        prices = {p["symbol"]: float(p["current_price"]) for p in pos if p.get("current_price")}
        body["positions"] = [{k: p.get(k) for k in ("symbol", "qty", "side", "avg_entry_price", "current_price", "market_value",
                                                     "unrealized_pl", "unrealized_plpc", "change_today")} for p in pos]
        body["clock"] = alp.clock()
        body["candles"] = account_candles(alp) or equity_candles(db, account_id)
    except Exception as exc:  # noqa: BLE001 - the page still shows the bot's own records
        body["broker_error"] = str(exc)
    ledger = _ledger(db, account_id)
    by_ticker_rule = {}
    trades = []
    for t in ledger:
        p = _pnl(t, prices.get(t["ticker"]))
        sign = 1 if t["side"] == "buy" else -1
        ref = t["exit"] if t["exit"] is not None else prices.get(t["ticker"])
        trades.append({"call_id": t["call_id"], "rule": t["rule"], "ticker": t["ticker"], "side": "LONG" if sign > 0 else "SHORT",
                       "qty": float(t["qty"]), "entry": float(t["entry"]),
                       "exit": float(t["exit"]) if t["exit"] is not None else None,
                       "mark": float(ref) if ref is not None else None, "status": "closed" if t["exit"] is not None else "open",
                       "exit_session": str(t["exit_session"]) if t["exit_session"] else None,
                       "opened": t["opened"].isoformat() if t["opened"] else None,
                       "closed": t["closed"].isoformat() if t["closed"] else None, "pnl": p,
                       "ret": None if ref is None else sign * (float(ref) / float(t["entry"]) - 1)})
        by_ticker_rule[t["ticker"]] = t["rule"]
    for p in body.get("positions", []):
        p["strategy"] = by_ticker_rule.get(p["symbol"])
    body["trades"] = trades[:150]
    body["strategies"] = {}
    for k in ORDER:
        mine = [t for t in trades if t["rule"] == k]
        closed = [t for t in mine if t["status"] == "closed"]
        body["strategies"][k] = {
            "candles": strategy_candles(db, account_id, k),
            "open": sum(1 for t in mine if t["status"] == "open"), "closed": len(closed),
            "wins": sum(1 for t in closed if (t["pnl"] or 0) > 0),
            "realized": sum(t["pnl"] or 0 for t in closed), "unrealized": sum(t["pnl"] or 0 for t in mine if t["status"] == "open")}
    body["orders"] = [{**dict(r), "submitted_at": r["submitted_at"].isoformat(),
                       "filled_at": r["filled_at"].isoformat() if r["filled_at"] else None,
                       "exit_session": str(r["exit_session"]) if r["exit_session"] else None, "qty": float(r["qty"]),
                       "filled_qty": float(r["filled_qty"]) if r["filled_qty"] is not None else None,
                       "filled_avg_price": float(r["filled_avg_price"]) if r["filled_avg_price"] is not None else None}
                      for r in db.execute(text("""SELECT * FROM autotrade_orders WHERE account_id=:a
                                                  ORDER BY submitted_at DESC LIMIT 80"""), {"a": account_id}).mappings()]
    body["events"] = [{"at": r["at"].isoformat(), "level": r["level"], "message": r["message"]}
                      for r in db.execute(text("""SELECT * FROM autotrade_events WHERE account_id=:a
                                                  ORDER BY at DESC LIMIT 60"""), {"a": account_id}).mappings()]
    body["today"] = [{**dict(r), "session": str(r["session"]), "earnings_date": str(r["earnings_date"]),
                      "called_at": r["called_at"].isoformat()}
                     for r in db.execute(text("""SELECT id, rule, ticker, side, entry, hold, gap_x, tier, session, earnings_date,
                                                        called_at FROM direction_calls WHERE session=:d ORDER BY called_at"""),
                                         {"d": _now().date()}).mappings()]
    return body
