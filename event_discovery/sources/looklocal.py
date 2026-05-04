from __future__ import annotations

import logging
from typing import Any

from ..http_util import ThrottledClient
from ..models import DiscoveredEvent


def fetch_looklocal(
    client: ThrottledClient,
    cfg: dict[str, Any],
    log: logging.Logger,
    source_label: str = "looklocal",
) -> list[DiscoveredEvent]:
    """
    Look Local embeds EventON; event rows are loaded client-side in many builds.
    Until an AJAX contract is pinned, return an empty list and log once.
    """
    page_url = (cfg.get("page_url") or "https://looklocal.ca/local-community-events/").strip()
    try:
        resp = client.get(page_url)
        if resp.status_code != 200:
            log.warning("%s: HTTP %s", source_label, resp.status_code)
            return []
    except OSError as e:
        log.warning("%s: fetch failed: %s", source_label, e)
        return []

    log.info(
        "%s: page fetched but calendar markup is not available server-side; "
        "open %s in a browser or extend adapter with EventON AJAX params.",
        source_label,
        page_url,
    )
    return []
