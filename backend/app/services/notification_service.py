"""Telegram bot notifications for high-conviction trade signals.

Setup:
1. Open Telegram, message @BotFather, send /newbot, follow prompts, save token
2. Search for your bot in Telegram, send it /start
3. Visit https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates — find chat.id
4. Add to server .env:
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
5. Restart backend
"""
from __future__ import annotations
import os
import time
from datetime import datetime
import httpx

_sent: dict[str, float] = {}  # key -> unix_ts, for dedup
DEDUP_WINDOW = 3600  # 1 hour - don't re-send same signal within this window


def _key(ticker: str, side: str) -> str:
    """Dedup at the hourly level — re-fire if signal persists into next hour."""
    return f"{ticker}-{side}-{datetime.utcnow().strftime('%Y%m%d-%H')}"


def _cleanup() -> None:
    """Drop entries older than dedup window."""
    cutoff = time.time() - DEDUP_WINDOW
    stale = [k for k, t in _sent.items() if t < cutoff]
    for k in stale:
        del _sent[k]


def send_signal(signal: dict) -> bool:
    """Send a single high-conviction signal to Telegram. Returns True if sent."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False

    _cleanup()
    key = _key(signal["ticker"], signal["side"])
    if key in _sent:
        return False

    arrow = "🟢↑" if signal["side"] == "LONG" else "🔴↓"
    session = signal.get("session", "market").upper().replace("_", "-")
    factors_text = "\n".join(f"  • {f['label']:<28} {f['value']:+.2f}" for f in signal.get("factors", []))

    # News block
    news = signal.get("news") or []
    if news:
        news_text = "\n*📰 RECENT NEWS:*\n" + "\n".join(
            f"  • _{n['title'][:90]}_" for n in news[:3]
        ) + "\n"
    else:
        news_text = ""

    # AI block
    ai = signal.get("ai") or {}
    if ai and "why" in ai:
        ai_text = (f"\n*🧠 AI ANALYSIS:*\n"
                   f"  *Why:* {ai.get('why', '—')}\n"
                   f"  *Action:* `{ai.get('action', '—')}` — {ai.get('rationale', '—')}\n"
                   f"  *Risk:* {ai.get('risk', '—')}\n")
    elif ai and "error" in ai:
        ai_text = f"\n_AI: {ai.get('error', 'unavailable')}_\n"
    else:
        ai_text = ""

    msg = f"""🚨 *SIGNALPHA · {session} SIGNAL*

{arrow} *{signal['side']}* `{signal['ticker']}`  @ ${signal['price']:.2f}

Conviction: *{signal['score']:+.2f}*   ({'★' * min(5, int(abs(signal['score']) * 5 + 1))})
Suggested size: *${signal['suggested_size']:,}*
Hold: ~1h · Exit ~{signal['exit_clock']}

*Factors:*
{factors_text}

Intraday: {signal['intraday_ret']*100:+.2f}%  |  RSI {signal.get('rsi2', signal.get('rsi', 50)):.0f}  |  Vol {signal['vol_z']:+.1f}σ
{news_text}{ai_text}
[https://signalpha.app/pulse]"""

    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown",
                  "disable_web_page_preview": True},
            timeout=8,
        )
        if r.status_code == 200:
            _sent[key] = time.time()
            return True
    except Exception:
        pass
    return False


def notification_status() -> dict:
    """Report Telegram config status (for UI display, no secrets leaked)."""
    token = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    chat = bool(os.getenv("TELEGRAM_CHAT_ID"))
    return {
        "configured": token and chat,
        "has_token": token,
        "has_chat_id": chat,
        "sent_last_hour": len(_sent),
    }
