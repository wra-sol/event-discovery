from __future__ import annotations

import json
import logging
from typing import Any

from bs4 import BeautifulSoup

from ..http_util import ThrottledClient
from ..models import DiscoveredEvent


def _strip_html(html: str, limit: int = 400) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    return text[:limit] + ("…" if len(text) > limit else "")


def fetch_tribe_rest(
    client: ThrottledClient,
    cfg: dict[str, Any],
    log: logging.Logger,
    source_label: str,
) -> list[DiscoveredEvent]:
    base = (cfg.get("rest_url") or "").rstrip("/")
    if not base:
        log.warning("%s: missing rest_url", source_label)
        return []
    per_page = int(cfg.get("per_page") or 50)
    max_pages = int(cfg.get("max_pages") or 4)
    out: list[DiscoveredEvent] = []
    headers = {"Accept": "application/json"}
    for page in range(1, max_pages + 1):
        url = f"{base}?per_page={per_page}&page={page}"
        try:
            resp = client.get(url, headers=headers)
            if resp.status_code != 200:
                log.warning("%s: HTTP %s for %s", source_label, resp.status_code, url)
                break
            payload = resp.json()
        except (json.JSONDecodeError, OSError) as e:
            log.warning("%s: failed page %s: %s", source_label, page, e)
            break
        events = payload.get("events") or []
        if not events:
            break
        for ev in events:
            title = (ev.get("title") or "").strip()
            link = (ev.get("url") or "").strip()
            if not title or not link:
                continue
            start = (ev.get("start_date") or "").strip() or None
            end = (ev.get("end_date") or "").strip() or None
            venue = ev.get("venue") or {}
            venue_name = ""
            if isinstance(venue, dict):
                name = (venue.get("venue") or "").strip()
                addr = (venue.get("address") or "").strip()
                city = (venue.get("city") or "").strip()
                zipc = (
                    (venue.get("zip") or venue.get("postal") or venue.get("postal_code") or "")
                    .strip()
                )
                rest = ", ".join(x for x in [addr, city, zipc] if x)
                if name and rest:
                    venue_name = f"{name} — {rest}"
                elif name:
                    venue_name = name
                elif rest:
                    venue_name = rest
            desc = _strip_html(ev.get("description") or "")
            out.append(
                DiscoveredEvent(
                    title=title,
                    url=link,
                    source=source_label,
                    start=start,
                    end=end,
                    venue=venue_name or None,
                    raw_snippet=desc,
                )
            )
        if len(events) < per_page:
            break
    log.info("%s: fetched %d events", source_label, len(out))
    return out
