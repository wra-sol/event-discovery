"""Simple in-memory rate limiting for auth endpoints (per-process)."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Deque

_lock = threading.Lock()
_state: dict[str, Deque[float]] = {}


def _now() -> float:
    return time.monotonic()


def check_rate_limit(
    key: str,
    *,
    max_events: int,
    window_seconds: float,
) -> tuple[bool, float | None]:
    """
    Return (allowed, retry_after_seconds).
    If not allowed, retry_after is a coarse hint until the oldest event expires.
    """
    t = _now()
    cutoff = t - window_seconds
    with _lock:
        q = _state.setdefault(key, deque())
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= max_events:
            oldest = q[0]
            retry_after = max(0.1, window_seconds - (t - oldest))
            return False, retry_after
        q.append(t)
        return True, None


def client_key(request_headers: Callable[[str], str], fallback_ip: str) -> str:
    """Prefer X-Forwarded-For first hop when present (behind Railway/proxy)."""
    xff = request_headers("x-forwarded-for") or ""
    if xff.strip():
        return xff.split(",")[0].strip()
    return fallback_ip or "unknown"
