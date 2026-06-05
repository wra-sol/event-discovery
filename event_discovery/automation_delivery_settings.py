from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlite3 import Connection

_SETTING_KEY = "automation_delivery"

_HTTPS_URL = re.compile(r"^https://", re.I)
_HTTP_URL = re.compile(r"^https?://", re.I)


@dataclass
class WebhookDestination:
    id: str
    url: str
    label: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "label": self.label,
            "enabled": self.enabled,
        }


@dataclass
class AutomationDeliverySettings:
    webhooks: list[WebhookDestination] = field(default_factory=list)
    skip_if_empty: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "webhooks": [w.to_dict() for w in self.webhooks],
            "skip_if_empty": self.skip_if_empty,
        }

    def enabled_webhook_urls(self) -> list[str]:
        return [w.url.strip() for w in self.webhooks if w.enabled and w.url.strip()]


def validate_webhook_url(url: str, *, allow_http: bool = False) -> str:
    text = url.strip()
    if not text:
        raise ValueError("Webhook URL is required")
    if len(text) > 2048:
        raise ValueError("Webhook URL is too long")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Webhook URL must be a valid http(s) URL")
    if not allow_http and parsed.scheme != "https":
        raise ValueError("Webhook URL must use https")
    return text


def _webhook_from_dict(raw: dict[str, Any]) -> WebhookDestination | None:
    url = str(raw.get("url") or "").strip()
    if not url:
        return None
    webhook_id = str(raw.get("id") or "").strip() or str(uuid.uuid4())
    return WebhookDestination(
        id=webhook_id,
        url=url,
        label=str(raw.get("label") or "").strip(),
        enabled=bool(raw.get("enabled", True)),
    )


def parse_automation_delivery_settings(raw: dict[str, Any] | None) -> AutomationDeliverySettings:
    if not isinstance(raw, dict):
        return AutomationDeliverySettings()
    webhooks: list[WebhookDestination] = []
    for item in raw.get("webhooks") or []:
        if isinstance(item, dict):
            wh = _webhook_from_dict(item)
            if wh is not None:
                webhooks.append(wh)
    return AutomationDeliverySettings(
        webhooks=webhooks,
        skip_if_empty=bool(raw.get("skip_if_empty", False)),
    )


def normalize_webhook_inputs(
    webhooks: list[dict[str, Any]],
    *,
    allow_http: bool = False,
) -> list[WebhookDestination]:
    out: list[WebhookDestination] = []
    seen: set[str] = set()
    for item in webhooks:
        if not isinstance(item, dict):
            continue
        url = validate_webhook_url(str(item.get("url") or ""), allow_http=allow_http)
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        webhook_id = str(item.get("id") or "").strip() or str(uuid.uuid4())
        out.append(
            WebhookDestination(
                id=webhook_id,
                url=url,
                label=str(item.get("label") or "").strip(),
                enabled=bool(item.get("enabled", True)),
            )
        )
    if len(out) > 10:
        raise ValueError("At most 10 webhook destinations are allowed")
    return out


def get_automation_delivery_settings(conn: Connection) -> AutomationDeliverySettings:
    cur = conn.cursor()
    cur.execute(
        "SELECT value_json FROM discovery_settings WHERE key = ?",
        (_SETTING_KEY,),
    )
    row = cur.fetchone()
    if row is None:
        return AutomationDeliverySettings()
    try:
        raw = json.loads(row["value_json"] or "{}")
    except json.JSONDecodeError:
        return AutomationDeliverySettings()
    return parse_automation_delivery_settings(raw if isinstance(raw, dict) else None)


def save_automation_delivery_settings(
    conn: Connection,
    settings: AutomationDeliverySettings,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO discovery_settings (key, value_json) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
        """,
        (_SETTING_KEY, json.dumps(settings.to_dict(), ensure_ascii=False)),
    )
    conn.commit()
