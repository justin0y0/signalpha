from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RateLimiter:
    min_interval_seconds: float
    _lock: threading.Lock = threading.Lock()
    _last_call: float = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self.min_interval_seconds - (now - self._last_call)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_call = time.monotonic()


class BaseAPIClient:
    def __init__(
        self,
        base_url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        min_interval_seconds: float = 0.25,
        max_retries: int = 4,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limiter = RateLimiter(min_interval_seconds=min_interval_seconds)
        self.client = httpx.Client(timeout=timeout, headers=self.headers)
        self._consecutive_failures = 0
        self._circuit_open = False

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if self._circuit_open:
            raise httpx.HTTPStatusError("Circuit breaker open — upstream repeatedly failing", request=httpx.Request(method, url), response=httpx.Response(503))
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.rate_limiter.wait()
                response = self.client.request(method, url, params=params)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        f"Transient upstream status {response.status_code}", request=response.request, response=response
                    )
                # 4xx client errors: fail fast, no retry
                if 400 <= response.status_code < 500:
                    response.raise_for_status()
                response.raise_for_status()
                self._consecutive_failures = 0
                return response
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                # fail fast on 4xx (except 429 rate-limit)
                if 400 <= status < 500 and status != 429:
                    raise
                last_error = exc
                backoff = min(2 ** (attempt - 1), 8) + random.random()
                logger.debug("API retry %s for %s: %s", attempt, url, exc)
                time.sleep(backoff)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                backoff = min(2 ** (attempt - 1), 8) + random.random()
                logger.debug("API retry %s for %s: %s", attempt, url, exc)
                time.sleep(backoff)
        assert last_error is not None
        self._consecutive_failures += 1
        if self._consecutive_failures >= 10:
            self._circuit_open = True
            logger.warning("Circuit breaker opened for %s after 10 consecutive failures", self.base_url)
        raise last_error

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._request("GET", path, params=params)
        return response.json()

    def get_text(self, path: str, params: dict[str, Any] | None = None) -> str:
        response = self._request("GET", path, params=params)
        return response.text

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def encode_cache_key(prefix: str, payload: dict[str, Any] | None = None) -> str:
        if not payload:
            return prefix
        return f"{prefix}:{json.dumps(payload, sort_keys=True, default=str)}"
