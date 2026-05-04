"""Environment flags shared across web, CLI, and workers."""

from __future__ import annotations

import os


def is_production() -> bool:
    env = (os.environ.get("EVENT_DISCOVERY_ENV") or "").strip().lower()
    if env == "production":
        return True
    return os.environ.get("EVENT_DISCOVERY_PRODUCTION", "").lower() in ("1", "true", "yes")


def database_url() -> str | None:
    u = (os.environ.get("DATABASE_URL") or "").strip()
    return u or None


def cors_allow_origins() -> list[str]:
    raw = (os.environ.get("EVENTS_CORS_ORIGINS") or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def allow_ephemeral_session_secret() -> bool:
    """Dev-only: allow missing EVENTS_SESSION_SECRET when explicitly opted in."""
    return os.environ.get("EVENT_DISCOVERY_ALLOW_EPHEMERAL_SESSION", "").lower() in (
        "1",
        "true",
        "yes",
    )


def crawl_api_token() -> str | None:
    """Shared secret for machine-to-machine crawl API (Bearer); None if unset."""
    t = (os.environ.get("EVENTS_CRAWL_API_TOKEN") or "").strip()
    return t or None
