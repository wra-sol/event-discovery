from __future__ import annotations

import logging
from typing import Any

from .http_util import ThrottledClient
from .models import DiscoveredEvent
from .robots_check import allowed_fetch
from .schema_event import extract_event_fields_from_html


def _blank(s: str | None) -> bool:
    return not (s or "").strip()


def enrich_discovered_events(
    client: ThrottledClient,
    events: list[DiscoveredEvent],
    *,
    user_agent: str,
    log: logging.Logger,
    cfg: dict[str, Any],
) -> list[DiscoveredEvent]:
    """
    Fetch event detail pages (robots-allowed) to fill missing start/end/venue from JSON-LD and meta tags.
    """
    block = cfg.get("enrichment")
    if isinstance(block, dict) and block.get("enabled") is False:
        return events
    max_urls = 100
    if isinstance(block, dict) and block.get("max_urls") is not None:
        try:
            max_urls = max(0, int(block["max_urls"]))
        except (TypeError, ValueError):
            max_urls = 100

    def robots_ok(url: str) -> bool:
        return allowed_fetch(lambda u: client.get(u), url, user_agent)

    cache: dict[str, dict[str, str]] = {}
    fetches = 0

    for ev in events:
        need_start = _blank(ev.start)
        need_end = _blank(ev.end)
        need_venue = _blank(ev.venue)
        if not (need_start or need_end or need_venue):
            continue
        u = (ev.url or "").strip()
        if not u:
            continue
        if u not in cache:
            if fetches >= max_urls:
                cache[u] = {}
                continue
            if not robots_ok(u):
                log.debug("enrich: robots skip %s", u[:80])
                cache[u] = {}
                continue
            try:
                resp = client.get(u)
                fetches += 1
                if resp.status_code != 200:
                    cache[u] = {}
                else:
                    cache[u] = extract_event_fields_from_html(resp.text)
            except OSError as e:
                log.debug("enrich: fetch failed %s: %s", u[:80], e)
                cache[u] = {}
                fetches += 1
        fields = cache[u]
        if need_start and fields.get("start"):
            ev.start = fields["start"]
        if need_end and fields.get("end"):
            ev.end = fields["end"]
        if need_venue and fields.get("venue"):
            ev.venue = fields["venue"]

    return events
