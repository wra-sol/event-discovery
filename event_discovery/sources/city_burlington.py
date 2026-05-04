from __future__ import annotations

import logging
import re
from typing import Any

from ..http_util import ThrottledClient
from ..models import DiscoveredEvent
from ..schema_event import iter_ld_event_objects, venue_from_schema_location


def _https_url(url: str) -> str:
    return re.sub(r"^http://", "https://", url, flags=re.I)


def fetch_city_events_ldjson(
    client: ThrottledClient,
    cfg: dict[str, Any],
    log: logging.Logger,
    source_label: str = "city_events",
) -> list[DiscoveredEvent]:
    page_url = (cfg.get("page_url") or "https://events.burlington.ca/").strip()
    try:
        resp = client.get(page_url)
        if resp.status_code != 200:
            log.warning("%s: HTTP %s", source_label, resp.status_code)
            return []
        html = resp.text
    except OSError as e:
        log.warning("%s: fetch failed: %s", source_label, e)
        return []

    out: list[DiscoveredEvent] = []
    for ev in iter_ld_event_objects(html):
        name = (ev.get("name") or "").strip()
        if not name:
            continue
        url = (ev.get("url") or "").strip()
        if not url:
            url = page_url
        start = (ev.get("startDate") or "").strip() or None
        end = (ev.get("endDate") or "").strip() or None
        desc = (ev.get("description") or "").strip()
        if len(desc) > 400:
            desc = desc[:400] + "…"
        venue = venue_from_schema_location(ev.get("location"))
        out.append(
            DiscoveredEvent(
                title=name,
                url=_https_url(url),
                source=source_label,
                start=start,
                end=end,
                venue=venue or None,
                raw_snippet=desc,
            )
        )

    log.info("%s: parsed %d events from JSON-LD", source_label, len(out))
    return out
