from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

from ..http_util import ThrottledClient
from ..models import DiscoveredEvent
from .city_burlington import fetch_city_events_ldjson
from .eventbrite import fetch_eventbrite_listings
from .looklocal import fetch_looklocal
from .spaces import fetch_spaces
from .tribe import fetch_tribe_rest

SourceHandler = Callable[
    [ThrottledClient, dict[str, Any], logging.Logger, str, date],
    list[DiscoveredEvent],
]

# Config keys that historically used a different DiscoveredEvent.source than the YAML key.
_LEGACY_EVENT_SOURCE_BY_KEY: dict[str, str] = {
    "tourism": "tourism_burlington",
    "downtown": "downtown_bdba",
}


def resolve_event_source_label(source_id: str, cfg: dict[str, Any]) -> str:
    """Label stored on DiscoveredEvent.source (DB); optional source_label in cfg overrides."""
    sl = cfg.get("source_label")
    if sl is not None and str(sl).strip():
        return str(sl).strip()
    return _LEGACY_EVENT_SOURCE_BY_KEY.get(source_id, source_id)


def iter_source_configs(cfg: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (source_id, source_cfg) in stable order: source_order when set, else YAML order."""
    sources_cfg = cfg.get("sources") or {}
    if not isinstance(sources_cfg, dict):
        return
    order = cfg.get("source_order")
    seen: set[str] = set()
    if isinstance(order, list):
        for key in order:
            if not isinstance(key, str):
                continue
            if key in sources_cfg and key not in seen:
                raw = sources_cfg[key]
                if isinstance(raw, dict):
                    yield key, raw
                    seen.add(key)
        for key, raw in sources_cfg.items():
            if key in seen:
                continue
            if isinstance(raw, dict):
                yield key, raw
    else:
        for key, raw in sources_cfg.items():
            if isinstance(raw, dict):
                yield key, raw


def source_robots_probe_url(source_type: str, cfg: dict[str, Any]) -> str | None:
    """URL used for robots.txt allowance check before fetching this source."""
    st = (source_type or "").strip()
    if st == "tribe_rest":
        u = (cfg.get("rest_url") or "").strip()
        return u or None
    if st in ("burlington_events_ldjson", "json_ld_events"):
        u = (cfg.get("page_url") or "").strip()
        return u or None
    if st == "spaces_fragment":
        u = (cfg.get("base_url") or "").strip()
        return u or None
    if st == "eventbrite_listing":
        urls = cfg.get("listing_urls") or []
        if isinstance(urls, str):
            urls = [urls]
        for item in urls:
            u = str(item).strip()
            if u:
                return u
        return None
    if st == "looklocal_page":
        u = (cfg.get("page_url") or "").strip()
        return u or None
    return None


def _fetch_tribe_rest(
    client: ThrottledClient,
    cfg: dict[str, Any],
    log: logging.Logger,
    source_label: str,
    _today: date,
) -> list[DiscoveredEvent]:
    return fetch_tribe_rest(client, cfg, log, source_label)


def _fetch_json_ld(
    client: ThrottledClient,
    cfg: dict[str, Any],
    log: logging.Logger,
    source_label: str,
    _today: date,
) -> list[DiscoveredEvent]:
    return fetch_city_events_ldjson(client, cfg, log, source_label)


def _fetch_spaces(
    client: ThrottledClient,
    cfg: dict[str, Any],
    log: logging.Logger,
    source_label: str,
    today: date,
) -> list[DiscoveredEvent]:
    return fetch_spaces(client, cfg, log, source_label, today=today)


def _fetch_eventbrite(
    client: ThrottledClient,
    cfg: dict[str, Any],
    log: logging.Logger,
    source_label: str,
    today: date,
) -> list[DiscoveredEvent]:
    return fetch_eventbrite_listings(client, cfg, log, source_label, today=today)


def _fetch_looklocal(
    client: ThrottledClient,
    cfg: dict[str, Any],
    log: logging.Logger,
    source_label: str,
    _today: date,
) -> list[DiscoveredEvent]:
    return fetch_looklocal(client, cfg, log, source_label)


SOURCE_HANDLERS: dict[str, SourceHandler] = {
    "tribe_rest": _fetch_tribe_rest,
    "burlington_events_ldjson": _fetch_json_ld,
    "json_ld_events": _fetch_json_ld,
    "spaces_fragment": _fetch_spaces,
    "eventbrite_listing": _fetch_eventbrite,
    "looklocal_page": _fetch_looklocal,
}

KNOWN_SOURCE_TYPES: frozenset[str] = frozenset(SOURCE_HANDLERS.keys())
