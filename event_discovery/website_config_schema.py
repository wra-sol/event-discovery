from __future__ import annotations

import copy
from typing import Any, Literal

FieldKind = Literal["url", "int", "text", "url_list"]
FieldTier = Literal["simple", "advanced"]


def _field(
    id_: str,
    *,
    label: str,
    help_text: str,
    kind: FieldKind,
    tier: FieldTier,
    placeholder: str | None = None,
    default_hint: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": id_,
        "label": label,
        "help": help_text,
        "kind": kind,
        "tier": tier,
    }
    if placeholder is not None:
        out["placeholder"] = placeholder
    if default_hint is not None:
        out["default_hint"] = default_hint
    return out


# Human titles and per-type field metadata for the Sites UI (single source of truth).
WEBSITE_SOURCE_TYPES: list[dict[str, Any]] = [
    {
        "id": "tribe_rest",
        "title": "The Events Calendar (REST API)",
        "description": "WordPress sites using The Events Calendar’s JSON feed.",
        "fields": [
            _field(
                "rest_url",
                label="Events JSON URL",
                help_text="Usually ends with /wp-json/tribe/events/v1/events",
                kind="url",
                tier="simple",
                placeholder="https://example.org/wp-json/tribe/events/v1/events",
            ),
            _field(
                "per_page",
                label="Events per page",
                help_text="How many events to request per request.",
                kind="int",
                tier="advanced",
                default_hint="50",
            ),
            _field(
                "max_pages",
                label="Max pages",
                help_text="Safety cap on how many pages of results to fetch.",
                kind="int",
                tier="advanced",
                default_hint="4",
            ),
        ],
    },
    {
        "id": "json_ld_events",
        "title": "Single page (JSON-LD events)",
        "description": "A web page that embeds schema.org Event data (JSON-LD).",
        "fields": [
            _field(
                "page_url",
                label="Page URL",
                help_text="The page to load and scan for embedded events.",
                kind="url",
                tier="simple",
            ),
        ],
    },
    {
        "id": "burlington_events_ldjson",
        "title": "Single page (JSON-LD) — legacy id",
        "description": "Same as “Single page (JSON-LD events)”. Prefer json_ld_events for new sites.",
        "fields": [
            _field(
                "page_url",
                label="Page URL",
                help_text="The page to load and scan for embedded events.",
                kind="url",
                tier="simple",
            ),
        ],
    },
    {
        "id": "spaces_fragment",
        "title": "Spaces / community calendar fragment",
        "description": "Spaces-style sites that return HTML event cards from an endpoint.",
        "fields": [
            _field(
                "base_url",
                label="Site base URL",
                help_text="Origin of the calendar, e.g. https://burlington.spaces.ca",
                kind="url",
                tier="simple",
            ),
            _field(
                "endpoint",
                label="Events endpoint path",
                help_text="Path appended to the base URL (often /posts/eventsbysite).",
                kind="text",
                tier="advanced",
                default_hint="/posts/eventsbysite",
            ),
            _field(
                "max_pages",
                label="Max pages",
                help_text="Maximum listing pages to fetch.",
                kind="int",
                tier="advanced",
                default_hint="8",
            ),
        ],
    },
    {
        "id": "eventbrite_listing",
        "title": "Eventbrite search / listing pages",
        "description": "Public Eventbrite listing URLs; event links are collected from the HTML.",
        "fields": [
            _field(
                "listing_urls",
                label="Listing URLs",
                help_text="One URL per line. Usually Eventbrite search or “events this week” pages.",
                kind="url_list",
                tier="simple",
            ),
        ],
    },
    {
        "id": "looklocal_page",
        "title": "Looklocal-style events page",
        "description": "A single community events listing page.",
        "fields": [
            _field(
                "page_url",
                label="Page URL",
                help_text="The events listing page to scrape.",
                kind="url",
                tier="simple",
            ),
        ],
    },
]


def website_source_types_payload() -> list[dict[str, Any]]:
    """Return a JSON-serializable list for GET /api/website-source-types."""
    return copy.deepcopy(WEBSITE_SOURCE_TYPES)
