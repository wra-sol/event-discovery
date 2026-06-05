from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .brief_format import format_brief_markdown


def is_slack_webhook(url: str) -> bool:
    return "hooks.slack.com" in url


def build_failure_payload(error: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "error": error,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_webhook_payload(brief: dict[str, Any], *, fmt: str = "markdown") -> dict[str, Any]:
    """Structured brief JSON plus a human-readable markdown field for chat/email."""
    payload: dict[str, Any] = {
        "status": "ok",
        "pending_count": int(brief.get("pending_count") or 0),
        "generated_at_utc": brief.get("generated_at_utc"),
        "geography_label": brief.get("geography_label"),
        "display_name": brief.get("display_name"),
        "brief": brief,
    }
    if fmt == "markdown":
        payload["markdown"] = format_brief_markdown(brief)
    return payload


def _request_body(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    if is_slack_webhook(url):
        text = payload.get("markdown") or payload.get("error") or str(payload)
        return {"text": text}
    return payload


def deliver_brief_webhook(url: str, payload: dict[str, Any], *, timeout: float = 30.0) -> None:
    """POST brief payload to webhook; raise on failure (cron should exit non-zero)."""
    body = _request_body(url.strip(), payload)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url.strip(), json=body)
        r.raise_for_status()
