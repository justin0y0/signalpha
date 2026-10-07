"""Pick a Groq chat model that actually exists today.

Groq retires models without much notice, and every caller here used to hardcode one.
When `llama-3.3-70b-versatile` was pulled in 2026-09, the Oracle scanner kept running,
got HTTP 404 on every analysis, logged a one-line warning, and stored nothing for days.
The same thing happened earlier with `llama-4-scout`. A model name is configuration
that goes stale on someone else's schedule, so it has to be resolved, not assumed.

`resolve()` returns the first preferred model that Groq currently lists, caching the
listing for a few hours. `chat()` posts a completion and, on a 404, drops the cache,
re-resolves once and retries — so the next retirement degrades to one slow call
instead of a silent outage.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

API = "https://api.groq.com/openai/v1"

# Most capable first. gpt-oss models are reasoning models: they need a reasoning
# budget hint and more max_tokens, or the answer gets cut off by the reasoning.
PREFERENCE = (
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
)
_NOT_CHAT = ("whisper", "guard", "orpheus", "tts", "allam")

_cache: dict[str, Any] = {"models": None, "at": 0.0}
_lock = threading.Lock()
_TTL = 6 * 3600


def _key() -> str:
    return os.getenv("GROQ_API_KEY", "").strip()


def _available(force: bool = False) -> list[str]:
    with _lock:
        if not force and _cache["models"] is not None and time.time() - _cache["at"] < _TTL:
            return _cache["models"]
    try:
        r = httpx.get(f"{API}/models", headers={"Authorization": f"Bearer {_key()}"}, timeout=10)
        r.raise_for_status()
        models = sorted(m["id"] for m in r.json().get("data", []))
    except Exception as exc:  # noqa: BLE001
        log.warning("groq model listing failed: %s", exc)
        models = _cache["models"] or []
    with _lock:
        _cache.update(models=models, at=time.time())
    return models


def resolve(preferred_env: str | None = None, force: bool = False) -> str | None:
    """First usable model: the env override if Groq still lists it, then PREFERENCE."""
    available = _available(force=force)
    wanted = [os.getenv(preferred_env, "").strip()] if preferred_env else []
    for name in [*wanted, *PREFERENCE]:
        if name and (not available or name in available):
            return name
    chat = [m for m in available if not any(t in m for t in _NOT_CHAT)]
    return chat[0] if chat else None


def chat(messages: list[dict], *, preferred_env: str | None = None, json_mode: bool = False,
         temperature: float = 0.2, max_tokens: int = 600, timeout: float = 30,
         model: str | None = None, reasoning_effort: str = "low") -> str | None:
    """One completion with automatic recovery from a retired model. Returns text or None.

    `model` pins an exact model and disables the fallback: the Earnings Arena scores
    named forecasters, and quietly answering as a different model would corrupt their
    record. A pinned model that Groq has retired returns None instead.
    """
    if not _key():
        return None
    for attempt in (0, 1):
        chosen = model or resolve(preferred_env, force=attempt == 1)
        if not chosen:
            return None
        body: dict[str, Any] = {"model": chosen, "messages": messages, "temperature": temperature,
                                "max_tokens": max_tokens}
        if chosen.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = reasoning_effort
            body["max_tokens"] = max(max_tokens, 1200)
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = httpx.post(f"{API}/chat/completions", headers={"Authorization": f"Bearer {_key()}"},
                           json=body, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            log.warning("groq %s: %s", chosen, exc)
            return None
        if r.status_code == 404 and attempt == 0 and not model:
            log.warning("groq model %s is gone (404) — re-resolving", chosen)
            continue
        if r.status_code != 200:
            log.warning("groq %s HTTP %s: %s", chosen, r.status_code, r.text[:200])
            return None
        return r.json()["choices"][0]["message"]["content"]
    return None
