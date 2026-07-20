"""Account signup / email verification / lightweight 'me' / admin user list."""
import os, html, logging
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from backend.app.services import auth_service as A

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegReq(BaseModel):
    email: str
    name: str = ""
    role: str = ""


@router.post("/register")
def register(req: RegReq):
    return A.register(req.email, req.name, req.role)


@router.get("/me")
def me(email: str = ""):
    u = A.me(email)
    if not u:
        return JSONResponse({"found": False}, status_code=404)
    return {"found": True, **u}


@router.get("/verify", response_class=HTMLResponse)
def verify(token: str = ""):
    base = os.getenv("PUBLIC_BASE_URL", "https://signalpha.app").rstrip("/")
    res = A.verify(token)
    if not res:
        return HTMLResponse(_page(base, "Link expired", "This verification link is no longer valid. Head back and sign up again.", None), status_code=400)
    name = res.get("name") or ""
    return HTMLResponse(_page(base, "You're in" + (f", {html.escape(name)}" if name else ""),
        "Your email is verified and your free trial is live. Connect Telegram to start receiving signals the moment they fire.",
        res.get("tg_link")))


def _check_admin(tok):
    want = os.getenv("ADMIN_TOKEN", "").strip()
    if not want or tok != want:
        raise HTTPException(status_code=401, detail="unauthorized")


@router.get("/admin/users")
def admin_users(x_admin_token: str = Header(default=""), limit: int = 500):
    _check_admin(x_admin_token)
    return A.list_users(limit)


def _page(base, title, body, tg_link):
    tg_btn = (f'<a class="btn tg" href="{html.escape(tg_link)}">Connect Telegram &rarr;</a>'
              if tg_link else "")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SignAlpha</title><style>
*{{margin:0;box-sizing:border-box}}
body{{background:#05070d;color:#e8edf5;font-family:Inter,system-ui,sans-serif;min-height:100vh;
display:grid;place-items:center;padding:24px;
background-image:radial-gradient(800px 400px at 70% -10%,rgba(56,189,248,.12),transparent 60%),radial-gradient(700px 380px at 10% 0%,rgba(167,139,250,.10),transparent 60%)}}
.card{{max-width:440px;text-align:center;background:rgba(17,24,39,.6);border:1px solid rgba(148,163,184,.14);
border-radius:18px;padding:42px 34px;backdrop-filter:blur(14px)}}
.eyebrow{{font-size:12px;letter-spacing:.3em;color:#38bdf8;text-transform:uppercase;margin-bottom:18px}}
h1{{font-size:27px;font-weight:760;letter-spacing:-.02em;margin-bottom:12px}}
p{{color:#8a99b0;font-size:15px;line-height:1.6;margin-bottom:26px}}
.btn{{display:inline-block;text-decoration:none;font-weight:600;font-size:14px;padding:13px 24px;border-radius:12px;margin:5px}}
.tg{{background:linear-gradient(120deg,#38bdf8,#7dd3fc);color:#06121c}}
.ghost{{border:1px solid rgba(148,163,184,.22);color:#e8edf5}}
</style></head><body><div class="card">
<div class="eyebrow">SignAlpha</div>
<h1>{title}</h1>
<p>{body}</p>
{tg_btn}
<a class="btn ghost" href="{base}/oracle">Open SignAlpha</a>
</div></body></html>"""
