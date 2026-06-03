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

import json as _json
from datetime import datetime as _dt, timezone as _tz
try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except: _ET = _tz.utc
try:
    import redis as _rl
    _rc = _rl.Redis(host='redis', port=6379, decode_responses=True)
    _rc.ping()
except: _rc = None

def _market_open():
    n = _dt.now(_ET)
    return n.weekday() < 5 and 4 <= n.hour < 20



def _market_regime():
    """SPY 5-day return regime: 'trending' / 'range_bound' / 'unknown'. Redis cached 10min."""
    if _rc is not None:
        try:
            c = _rc.get("regime:spy")
            if c: return c if isinstance(c, str) else c.decode()
        except Exception: pass
    try:
        import yfinance as yf
        h = yf.Ticker("SPY").history(period="7d", interval="1d")
        if len(h) < 5: r = "unknown"
        else:
            ret_5d = (float(h["Close"].iloc[-1]) / float(h["Close"].iloc[-5]) - 1) * 100
            thr = float(os.getenv("REGIME_THRESHOLD_PCT", "1.5"))
            r = "trending" if abs(ret_5d) > thr else "range_bound"
        if _rc:
            try: _rc.setex("regime:spy", 600, r)
            except Exception: pass
        return r
    except Exception:
        return "unknown"


def _regime_allows(strategy, side):
    """In trending market, suppress mean-reversion strategies (AL/Connors). Momentum stays."""
    if os.getenv("REGIME_FILTER","").lower() not in ("1","true","yes","on"):
        return True
    strat = (strategy or "").upper()
    is_mean_rev = any(k in strat for k in ("REVERSION", "AL_", "CONNORS"))
    if is_mean_rev and _market_regime() == "trending":
        return False
    return True


# ═══ Pulse risk/timing controls (env-tunable) ═══
def _flag_on(name, default="0"):
    return os.getenv(name, default).lower() in ("1","true","yes","on")

def _cooldown_active(ticker, side):
    """Hard cooldown: same ticker+side within PULSE_COOLDOWN_MIN. Redis-backed (survives restarts)."""
    mins = int(os.getenv("PULSE_COOLDOWN_MIN", "60"))
    if mins <= 0 or _rc is None:
        return False
    try:
        return _rc.exists(f"pulse:cd:{ticker}:{side}") == 1
    except Exception:
        return False

def _cooldown_set(ticker, side):
    mins = int(os.getenv("PULSE_COOLDOWN_MIN", "60"))
    if mins <= 0 or _rc is None:
        return
    try:
        _rc.setex(f"pulse:cd:{ticker}:{side}", mins*60, "1")
    except Exception:
        pass

def _session_allows_entry():
    """RTH-only entry + no Friday-late entry (avoid weekend holds)."""
    n = _dt.now(_ET)
    if n.weekday() >= 5:
        return False, "weekend"
    mins = n.hour*60 + n.minute
    if _flag_on("PULSE_RTH_ONLY", "1"):
        if mins < 9*60+30 or mins > 15*60+45:
            return False, "outside RTH"
    if _flag_on("PULSE_NO_WEEKEND_HOLD", "1") and n.weekday() == 4 and n.hour >= 14:
        return False, "friday-late weekend-hold"
    return True, "ok"


def _should_alert(ticker, side, score, min_delta=0.5, cooldown_h=4, hard_cd_min=60):
    if not _market_open(): return False, "market closed"
    if os.getenv("DISABLE_SHORTS","").lower() in ("1","true","yes","on") and side == "SHORT":
        return False, "shorts disabled by flag"
    if _rc is None: return True, "no-redis"
    try:
        last = _rc.get(f"tg:lastsig:{ticker}")
        if last:
            d = _json.loads(last)
            if d.get("side") == side:
                try:
                    last_ts = _dt.fromisoformat(d.get("ts","").replace("Z","+00:00"))
                    age_min = (_dt.now(_tz.utc) - last_ts).total_seconds() / 60
                    if age_min < hard_cd_min:
                        return False, f"hard cooldown ({age_min:.0f}min)"
                except Exception: pass
                if abs(d.get("score",0)-score) < min_delta:
                    return False, "soft cooldown"
        _rc.setex(f"tg:lastsig:{ticker}", cooldown_h*3600,
                  _json.dumps({"side":side,"score":float(score),"ts":_dt.now(_tz.utc).isoformat()}))
        return True, "ok"
    except Exception:
        return True, "err"


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



def _log_signal_db(signal):
    """Log signal to DB for exit tracking. Called after Telegram send succeeds."""
    try:
        from backend.app.db.session import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("""
            INSERT INTO pulse_signal_log
            (ticker, side, strategy, score, entry_price, expected_exit_time,
             tp_price, sl_price, suggested_size, status)
            VALUES (:t, :s, :st, :sc, :ep, :ex, :tp, :sl, :sz, 'open')
        """), {
            "t": signal["ticker"], "s": signal["side"],
            "st": signal.get("primary", "manual"),
            "sc": float(signal.get("score", 0)),
            "ep": float(signal.get("price", 0)),
            "ex": signal.get("_exit_dt"),
            "tp": float(signal.get("_tp_price", 0)),
            "sl": float(signal.get("_sl_price", 0)),
            "sz": float(signal.get("suggested_size", 50000)),
        })
        db.commit(); db.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"signal log fail: {e}")


def send_signal(signal: dict) -> bool:
    """Send a single high-conviction signal to Telegram. Returns True if sent."""
    if not _regime_allows(signal.get("primary",""), signal.get("side","")):
        return False
    if os.getenv("DISABLE_SHORTS","").lower() in ("1","true","yes","on") and signal.get("side") == "SHORT":
        return False
    # ═══ Pulse entry gates: session + hard cooldown + min score ═══
    _se_ok, _se_why = _session_allows_entry()
    if not _se_ok:
        return False
    if _cooldown_active(signal["ticker"], signal["side"]):
        return False
    _min_score = float(os.getenv("PULSE_MIN_SCORE", "0") or 0)
    if _min_score > 0 and abs(float(signal.get("score", 0) or 0)) < _min_score:
        return False
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False

    _cleanup()
    key = _key(signal["ticker"], signal["side"])
    if key in _sent:
        return False


    # ═══ Session-aware exit time + triple-barrier TP/SL ═══
    from datetime import timedelta as _td
    _now_et = _dt.now(_ET)
    _session = signal.get("session", "market")
    def _next_open(d):
        nd = d + _td(days=1)
        while nd.weekday() >= 5: nd += _td(days=1)
        return nd.replace(hour=9, minute=30, second=0, microsecond=0)
    if _session == "market":
        _strat = (signal.get("primary","") or "").upper()
        if any(k in _strat for k in ("REVERSION","AL_")): _hold_h = 4
        elif "GAO" in _strat: _hold_h = 1
        elif "CONNORS" in _strat: _hold_h = 2
        else: _hold_h = 1
        _exit_dt = _now_et + _td(hours=_hold_h)
        if _exit_dt.hour >= 16:
            _exit_dt = _now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    elif _session == "pre_market":
        _exit_dt = _now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if _exit_dt <= _now_et: _exit_dt = _next_open(_now_et)
    elif _session == "after_hours" or _now_et.hour >= 20 or _now_et.hour < 4:
        _exit_dt = _next_open(_now_et)
    else:
        _exit_dt = _now_et + _td(hours=1)
    if _exit_dt.date() == _now_et.date():
        exit_clock_str = _exit_dt.strftime("%H:%M ET today")
    elif _exit_dt.date() == (_now_et + _td(days=1)).date():
        exit_clock_str = _exit_dt.strftime("%H:%M ET tomorrow")
    else:
        exit_clock_str = _exit_dt.strftime("%H:%M ET %a %m/%d")
    hold_label = "~1h" if _session == "market" else "until next open"
    _px = float(signal.get("price", 0) or 0)
    _atr = float(signal.get("atr20", 0) or signal.get("atr", 0) or _px * 0.02)
    _ap = (_atr / _px) if _px > 0 else 0.02
    _il = signal["side"] == "LONG"
    # Mean reversion: TP near (take the revert), SL wide (room to revert), with min SL floor
    _tp_mult = float(os.getenv("PULSE_TP_ATR_MULT", "1.0"))
    _sl_mult = float(os.getenv("PULSE_SL_ATR_MULT", "2.2"))
    _sl_min = float(os.getenv("PULSE_SL_MIN_PCT", "0.6")) / 100.0
    _tp_dist = _tp_mult * _ap
    _sl_dist = max(_sl_mult * _ap, _sl_min)
    _tp_pct = (_tp_dist if _il else -_tp_dist)
    _sl_pct = (-_sl_dist if _il else _sl_dist)
    tp_price = _px * (1 + _tp_pct)
    sl_price = _px * (1 + _sl_pct)
    risk_block = (f"\n*Triple-barrier exit:*\n"
                  f"  🎯 PT  ${tp_price:.2f}  ({_tp_pct*100:+.2f}%)\n"
                  f"  🛡 SL  ${sl_price:.2f}  ({_sl_pct*100:+.2f}%)\n"
                  f"  ⏰ Time {exit_clock_str}\n")
    # Store for DB log later
    signal["_exit_dt"] = _exit_dt.isoformat()
    signal["_tp_price"] = tp_price
    signal["_sl_price"] = sl_price

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
Hold: {hold_label} · Exit ~{exit_clock_str}
{risk_block}
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
            _cooldown_set(signal["ticker"], signal["side"])
            _log_signal_db(signal)
            try:
                from backend.app.services.broker_service import place_signal_order
                _ibkr_res = place_signal_order(signal)
                if _ibkr_res.get("placed"):
                    import logging; logging.getLogger(__name__).info(f"IBKR order: {_ibkr_res}")
            except Exception:
                import logging; logging.getLogger(__name__).exception("broker hook fail")
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
