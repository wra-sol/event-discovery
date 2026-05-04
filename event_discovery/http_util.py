from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_USER_AGENT = (
    "FrankDomenicEventDiscovery/0.1 (+https://github.com; campaign calendar triage bot; respectful crawl)"
)


class ThrottledClient:
    """Thin httpx wrapper with delay between requests."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout_s: float = 45.0,
        delay_s: float = 0.75,
    ) -> None:
        self._delay_s = delay_s
        self._last: float = 0.0
        headers = {"User-Agent": user_agent, "Accept": "*/*"}
        self._client = httpx.Client(timeout=timeout_s, headers=headers, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self._delay_s - (now - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self._throttle()
        return self._client.get(url, headers=headers)

    def post(
        self,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self._throttle()
        h = dict(headers or {})
        return self._client.post(url, data=data, headers=h)
