"""SignAlpha platform accounts: email signup + verification, Telegram deep-link
binding, free-trial gating, and verified-user broadcast. Self-contained; uses
only stdlib (smtplib/ssl/secrets) + httpx + the existing SQLAlchemy session.
No external dependencies, no requirements.txt change."""
from __future__ import annotations
import os, re, ssl, smtplib, secrets, logging, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy import text
from backend.app.db.session import SessionLocal

log = logging.getLogger(__name__)

TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "30"))
PAID_TIERS = {"pro", "paid", "lifetime"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ready = False


def _base_url():
    return os.getenv("PUBLIC_BASE_URL", "https://signalpha.app").rstrip("/")

def _bot_username():
    return os.getenv("TELEGRAM_BOT_USERNAME", "").lstrip("@").strip()

def _tg_link(ttok):
    bu = _bot_username()
    return f"https://t.me/{bu}?start={ttok}" if bu and ttok else ""


def ensure_tables():
    ddl = """
    CREATE TABLE IF NOT EXISTS platform_users(
      id BIGSERIAL PRIMARY KEY,
      email TEXT UNIQUE NOT NULL,
      name TEXT,
      role TEXT,
      tier TEXT NOT NULL DEFAULT 'free_trial',
      verified BOOLEAN NOT NULL DEFAULT FALSE,
      verify_token TEXT,
      tg_token TEXT,
      tg_chat_id TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      verified_at TIMESTAMPTZ,
      trial_ends_at TIMESTAMPTZ,
      last_seen TIMESTAMPTZ
    );
    CREATE INDEX IF NOT EXISTS idx_pu_email ON platform_users(email);
    CREATE INDEX IF NOT EXISTS idx_pu_verify ON platform_users(verify_token);
    CREATE INDEX IF NOT EXISTS idx_pu_tg ON platform_users(tg_token);
    """
    db = SessionLocal()
    try:
        for stmt in ddl.split(";"):
            if stmt.strip():
                db.execute(text(stmt))
        db.commit()
        log.info("platform_users table ready")
    finally:
        db.close()

def _ensure():
    global _ready
    if _ready:
        return
    try:
        ensure_tables(); _ready = True
    except Exception as e:
        log.warning(f"ensure_tables: {e}")


def _active(m):
    if m.get("tier") in PAID_TIERS:
        return True
    if not m.get("verified"):
        return False
    te = m.get("trial_ends_at")
    if te is None:
        return True
    try:
        if te.tzinfo is None:
            te = te.replace(tzinfo=dt.timezone.utc)
        return dt.datetime.now(dt.timezone.utc) <= te
    except Exception:
        return True


def _send_email(to, subject, html, text=None):
    user = os.getenv("SMTP_USER", "").strip()
    pw = os.getenv("SMTP_PASS", "").strip()
    if not user or not pw:
        log.warning("SMTP not configured; verification email skipped")
        return False
    frm = os.getenv("SMTP_FROM", user).strip()
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    from email.utils import make_msgid, formatdate
    dom = frm.split("@")[-1] if "@" in frm else "signalpha.app"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"SignAlpha <{frm}>"
    msg["To"] = to
    msg["Reply-To"] = frm
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=dom)
    msg["List-Unsubscribe"] = f"<mailto:{frm}?subject=unsubscribe>"
    if text:
        msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.sendmail(frm, [to], msg.as_string())
        return True
    except Exception as e:
        log.warning(f"send_email to {to}: {e}")
        return False


def _verify_email_html(name, link):
    hi = f"Hi {name}," if name else "Hi,"
    return f"""<div style="background:#05070d;padding:40px 0;font-family:Inter,Arial,sans-serif">
<table align="center" width="460" style="background:#0d1322;border:1px solid rgba(148,163,184,.14);border-radius:16px;padding:34px">
<tr><td>
<div style="font-size:13px;letter-spacing:.28em;color:#38bdf8;text-transform:uppercase;margin-bottom:18px">SignAlpha</div>
<div style="font-size:21px;font-weight:700;color:#e8edf5;margin-bottom:10px">Confirm your email</div>
<p style="color:#8a99b0;font-size:14px;line-height:1.6;margin:0 0 24px">{hi} please confirm this email address to activate your SignAlpha account.</p>
<a href="{link}" style="display:inline-block;background:linear-gradient(120deg,#38bdf8,#7dd3fc);color:#06121c;font-weight:600;font-size:14px;text-decoration:none;padding:13px 26px;border-radius:11px">Confirm email</a>
<p style="color:#5b6678;font-size:12px;line-height:1.6;margin:26px 0 0">Or open this link:<br><span style="color:#38bdf8;word-break:break-all">{link}</span></p>
<p style="color:#5b6678;font-size:11px;margin:22px 0 0">If you didn't create this account, you can ignore this email.</p>
</td></tr></table></div>"""


def _verify_email_text(name, link):
    hi = f"Hi {name}," if name else "Hi,"
    return (f"{hi}\n\nPlease confirm this email address to activate your SignAlpha account:\n"
            f"{link}\n\nIf you didn't create this account, you can ignore this email.\n\nSignAlpha")


def register(email, name="", role=""):
    _ensure()
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        return {"ok": False, "error": "Enter a valid email address."}
    name = (name or "").strip()[:120]
    role = (role or "").strip()[:60]
    vtok = secrets.token_urlsafe(24)
    ttok = secrets.token_urlsafe(16)
    db = SessionLocal()
    try:
        row = db.execute(text("SELECT id, verified, tg_token FROM platform_users WHERE email=:e"),
                         {"e": email}).fetchone()
        if row and row.verified:
            return {"ok": True, "verified": True, "tg_link": _tg_link(row.tg_token),
                    "message": "You're already verified."}
        if row:
            ttok = row.tg_token or ttok
            db.execute(text("UPDATE platform_users SET name=:n, role=:r, verify_token=:v, tg_token=:t WHERE email=:e"),
                       {"n": name, "r": role, "v": vtok, "t": ttok, "e": email})
        else:
            db.execute(text("""INSERT INTO platform_users(email,name,role,verify_token,tg_token,trial_ends_at)
                VALUES(:e,:n,:r,:v,:t, now() + (:days || ' days')::interval)"""),
                {"e": email, "n": name, "r": role, "v": vtok, "t": ttok, "days": str(TRIAL_DAYS)})
        db.commit()
    finally:
        db.close()
    link = f"{_base_url()}/api/v1/auth/verify?token={vtok}"
    _send_email(email, "Verify your SignAlpha account", _verify_email_html(name, link))
    return {"ok": True, "verified": False, "message": "Check your email to verify your account."}


def verify(token):
    _ensure()
    if not token:
        return None
    db = SessionLocal()
    try:
        row = db.execute(text("SELECT id, email, name, tg_token FROM platform_users WHERE verify_token=:v"),
                         {"v": token}).fetchone()
        if not row:
            return None
        db.execute(text("""UPDATE platform_users SET verified=TRUE, verified_at=now(),
            verify_token=NULL, last_seen=now() WHERE id=:i"""), {"i": row.id})
        db.commit()
        return {"email": row.email, "name": row.name, "tg_link": _tg_link(row.tg_token)}
    finally:
        db.close()


def bind_telegram(tg_token, chat_id):
    """Called by telegram_webhook on /start <token>. Returns user dict or None."""
    _ensure()
    if not tg_token or not chat_id:
        return None
    db = SessionLocal()
    try:
        row = db.execute(text("SELECT id, email, name, verified FROM platform_users WHERE tg_token=:t"),
                         {"t": tg_token}).fetchone()
        if not row:
            return None
        db.execute(text("UPDATE platform_users SET tg_chat_id=:c, last_seen=now() WHERE id=:i"),
                   {"c": str(chat_id), "i": row.id})
        db.commit()
        return {"email": row.email, "name": row.name, "verified": bool(row.verified)}
    finally:
        db.close()


def me(email):
    _ensure()
    email = (email or "").strip().lower()
    if not email:
        return None
    db = SessionLocal()
    try:
        row = db.execute(text("""SELECT email,name,role,tier,verified,tg_chat_id,trial_ends_at,tg_token
            FROM platform_users WHERE email=:e"""), {"e": email}).fetchone()
        if not row:
            return None
        m = dict(row._mapping)
        m["tg_link"] = _tg_link(m.pop("tg_token", None))
        m["tg_connected"] = bool(m.pop("tg_chat_id", None))
        m["active"] = _active(m)
        if m.get("trial_ends_at"):
            m["trial_ends_at"] = m["trial_ends_at"].isoformat()
        return m
    finally:
        db.close()


def list_users(limit=500):
    _ensure()
    db = SessionLocal()
    try:
        rows = db.execute(text("""SELECT email,name,role,tier,verified,
            (tg_chat_id IS NOT NULL) AS tg_connected, created_at, verified_at, trial_ends_at, last_seen
            FROM platform_users ORDER BY created_at DESC LIMIT :l"""), {"l": limit}).fetchall()
        users = []
        for r in rows:
            m = dict(r._mapping)
            for k in ("created_at", "verified_at", "trial_ends_at", "last_seen"):
                if m.get(k) is not None:
                    m[k] = m[k].isoformat()
            users.append(m)
        total = db.execute(text("SELECT count(*) FROM platform_users")).scalar()
        verified = db.execute(text("SELECT count(*) FROM platform_users WHERE verified")).scalar()
        tg = db.execute(text("SELECT count(*) FROM platform_users WHERE tg_chat_id IS NOT NULL")).scalar()
        roles = db.execute(text("""SELECT COALESCE(NULLIF(role,''),'(unspecified)') AS role, count(*) AS n
            FROM platform_users GROUP BY 1 ORDER BY n DESC""")).fetchall()
        return {"total": total, "verified": verified, "telegram_connected": tg,
                "by_role": [dict(r._mapping) for r in roles], "users": users}
    finally:
        db.close()


def verified_recipients():
    _ensure()
    db = SessionLocal()
    try:
        rows = db.execute(text("""SELECT tg_chat_id, tier, verified, trial_ends_at
            FROM platform_users WHERE verified=TRUE AND tg_chat_id IS NOT NULL""")).fetchall()
        return [dict(r._mapping)["tg_chat_id"] for r in rows if _active(dict(r._mapping))]
    finally:
        db.close()


def broadcast(message_md):
    """Send a Telegram message to every verified, in-trial, TG-connected user.
    Returns the number of users it reached."""
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not tok:
        return 0
    import httpx
    sent = 0
    for chat_id in verified_recipients():
        try:
            httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                json={"chat_id": chat_id, "text": message_md, "parse_mode": "Markdown",
                      "disable_web_page_preview": True}, timeout=8)
            sent += 1
        except Exception:
            pass
    return sent
