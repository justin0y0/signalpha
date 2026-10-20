"""Sign-in for Autopilot — a six-digit code, sent where only the account holder can read it.

Two kinds of holder:
* the owner — the code goes to TELEGRAM_CHAT_ID, the site's own Telegram chat. No email
  and no password involved; whoever reads that chat runs the house account.
* everyone else — the code goes to their email (and to their Telegram too, if they have
  linked it on the alerts sign-up). The address becomes, or reuses, a platform_users row,
  marked verified once a code is entered.

A correct code buys a signed session token (30 days): `<holder>.<expiry>.<hmac>`, where
holder is `owner` or `u<platform_user_id>`, keyed off ADMIN_TOKEN — rotating that signs
everyone out. Codes live in Redis for 10 minutes; one request a minute per holder, five
guesses per code.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException
from sqlalchemy import text

from backend.app.db.session import SessionLocal

TOKEN_DAYS = 30
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Holder:
    key: str            # 'owner' or 'u<id>'
    role: str           # 'owner' | 'user'
    email: str | None = None

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


def _redis():
    import redis

    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)


def _key() -> bytes:
    admin = os.getenv("ADMIN_TOKEN", "").strip()
    if not admin:
        raise HTTPException(503, "Sign-in is not configured on the server")
    return hashlib.sha256(b"signalpha-autopilot:" + admin.encode()).digest()


def _telegram(chat: str, message: str) -> bool:
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not tok or not chat:
        return False
    try:
        r = httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=10,
                       json={"chat_id": chat, "text": message})
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _holder_for_email(email: str) -> tuple[str, str | None]:
    """platform_users id for this address (created if new), and its Telegram chat if linked."""
    from backend.app.services.auth_service import _ensure

    _ensure()
    with SessionLocal() as s:
        row = s.execute(text("SELECT id, tg_chat_id FROM platform_users WHERE email=:e"), {"e": email}).first()
        if row is None:
            row = s.execute(text("""INSERT INTO platform_users (email, tier) VALUES (:e, 'free_trial')
                                    RETURNING id, tg_chat_id"""), {"e": email}).first()
            s.commit()
    return f"u{row.id}", row.tg_chat_id


def send_code(email: str | None) -> dict:
    """email=None asks for the owner code (Telegram); otherwise a user code (email)."""
    if email:
        email = email.strip().lower()
        if not EMAIL.match(email):
            raise HTTPException(400, "That is not an email address")
        holder, tg = _holder_for_email(email)
    else:
        holder, tg = "owner", os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not tg:
            raise HTTPException(503, "Owner sign-in needs Telegram configured on the server")
    r = _redis()
    if not r.set(f"ap:throttle:{holder}", "1", nx=True, ex=60):
        raise HTTPException(429, "A code was sent less than a minute ago")
    code = f"{secrets.randbelow(10**6):06d}"
    r.set(f"ap:code:{holder}", hashlib.sha256(code.encode()).hexdigest(), ex=600)
    r.delete(f"ap:tries:{holder}")
    msg = f"SignAlpha Autopilot sign-in code: {code}\nValid for 10 minutes. If you did not ask for it, ignore this."
    sent = []
    if tg and _telegram(tg, msg):
        sent.append("telegram")
    if email:
        from backend.app.services.auth_service import _send_email

        try:
            _send_email(email, "Your SignAlpha Autopilot code",
                        f"<p>Your sign-in code is</p><p style='font-size:28px;letter-spacing:6px'><b>{code}</b></p>"
                        "<p>It is valid for 10 minutes. If you did not ask for it, ignore this email.</p>", msg)
            sent.append("email")
        except Exception:  # noqa: BLE001 - reported below if nothing went out
            pass
    if not sent:
        r.delete(f"ap:code:{holder}", f"ap:throttle:{holder}")
        raise HTTPException(502, "The code could not be delivered")
    return {"sent": sent}


def login(email: str | None, code: str) -> dict:
    holder = "owner" if not email else _holder_for_email(email.strip().lower())[0]
    r = _redis()
    want = r.get(f"ap:code:{holder}")
    if not want:
        raise HTTPException(401, "No active code — request a new one")
    if r.incr(f"ap:tries:{holder}") > 5:
        r.delete(f"ap:code:{holder}")
        raise HTTPException(429, "Too many attempts — request a new code")
    if not hmac.compare_digest(want, hashlib.sha256((code or "").strip().encode()).hexdigest()):
        raise HTTPException(401, "Wrong code")
    r.delete(f"ap:code:{holder}", f"ap:tries:{holder}")
    if holder != "owner":
        with SessionLocal() as s:
            s.execute(text("""UPDATE platform_users SET verified=TRUE, verified_at=COALESCE(verified_at, now()),
                              last_seen=now() WHERE id=:i"""), {"i": int(holder[1:])})
            s.commit()
    exp = int(time.time()) + TOKEN_DAYS * 86400
    body = f"{holder}.{exp}"
    sig = base64.urlsafe_b64encode(hmac.new(_key(), body.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return {"token": f"{body}.{sig}", "expires": exp, "role": "owner" if holder == "owner" else "user"}


def holder_from(token: str) -> Holder | None:
    try:
        holder, exp_s, sig = token.split(".", 2)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return None
    if exp < time.time():
        return None
    want = base64.urlsafe_b64encode(hmac.new(_key(), f"{holder}.{exp_s}".encode(), hashlib.sha256).digest()).decode().rstrip("=")
    if not hmac.compare_digest(want, sig):
        return None
    if holder == "owner":
        return Holder("owner", "owner")
    with SessionLocal() as s:
        email = s.execute(text("SELECT email FROM platform_users WHERE id=:i"), {"i": int(holder[1:])}).scalar()
    return Holder(holder, "user", email) if email else None


def current(x_autopilot_token: str = Header(default="")) -> Holder:
    h = holder_from(x_autopilot_token.strip()) if x_autopilot_token else None
    if h is None:
        raise HTTPException(401, "Sign in to use Autopilot")
    return h
