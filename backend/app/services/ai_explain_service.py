"""Groq-powered signal explanation. Free tier: 30 req/min on llama-3.1-70b.

Setup:
1. Go to https://console.groq.com/keys (sign up free)
2. Create API key
3. Add to server .env:  GROQ_API_KEY=gsk_...
4. Restart backend
"""
from __future__ import annotations
import json
import os
import time
import httpx

_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 1800  # 30 min — same ticker won't be re-analyzed
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def _cleanup() -> None:
    cutoff = time.time() - CACHE_TTL
    stale = [k for k, (t, _) in _cache.items() if t < cutoff]
    for k in stale:
        del _cache[k]


def explain_signal(signal: dict, news: list[dict]) -> dict | None:
    """Returns dict with keys: why, action, rationale, risk. Or None on failure."""
    _cleanup()
    cache_key = f"{signal['ticker']}-{signal['side']}-{int(time.time() // CACHE_TTL)}"
    if cache_key in _cache:
        return _cache[cache_key][1]

    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None

    news_text = "\n".join(
        f"- [{n.get('minutes_ago','?')}min ago] {n['title']} ({n['publisher']})"
        for n in news[:5]
    ) or "(No recent news headlines found.)"

    factors_text = ", ".join(
        f"{f['label']} {f['value']:+.2f}" for f in signal.get("factors", [])
    ) or "—"

    session_text = signal.get("session", "market")
    prompt = f"""You are a quantitative trading assistant analyzing a real-time technical signal.

Ticker: {signal['ticker']}
Current price: ${signal['price']:.2f}
Intraday move: {signal['intraday_ret']*100:+.2f}%
Session: {session_text}
Conviction score: {signal['score']:+.2f} ({signal['side']})
Technical factors driving signal: {factors_text}

Recent news (last 24h):
{news_text}

Output ONLY valid minified JSON, no other text:
{{"why":"1 sentence root cause - cite specific news if relevant","action":"LONG or SHORT or WAIT or FADE","rationale":"1 sentence why this action makes sense","risk":"1 sentence main downside scenario"}}"""

    try:
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 350,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=12,
        )
        if r.status_code != 200:
            return {"error": f"Groq {r.status_code}", "raw": r.text[:200]}
        content = r.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        _cache[cache_key] = (time.time(), result)
        return result
    except Exception as e:
        return {"error": str(e)[:120]}
