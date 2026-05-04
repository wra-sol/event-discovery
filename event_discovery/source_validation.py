"""Validate website type + config for API and UI (shared with crawler expectations)."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from .sources.registry import KNOWN_SOURCE_TYPES
from .website_config_schema import WEBSITE_SOURCE_TYPES

_TYPE_FIELDS: dict[str, list[dict[str, Any]]] = {
    str(t["id"]): list(t.get("fields") or []) for t in WEBSITE_SOURCE_TYPES
}


def _is_http_url(s: str) -> bool:
    u = urlparse(s.strip())
    return u.scheme in ("http", "https") and bool(u.netloc)


def validate_website_type_and_config(site_type: str, config: dict[str, Any]) -> None:
    st = (site_type or "").strip()
    if not st:
        raise ValueError("Source type is required.")
    if st not in KNOWN_SOURCE_TYPES:
        raise ValueError(
            "That source type is not supported. Pick one of the listed types, or ask an admin."
        )
    fields = _TYPE_FIELDS.get(st, [])
    for f in fields:
        fid = str(f.get("id") or "")
        kind = str(f.get("kind") or "text")
        tier = str(f.get("tier") or "simple")
        if tier != "simple":
            continue
        val = config.get(fid)
        if kind in ("url", "text"):
            if not (isinstance(val, str) and val.strip()):
                raise ValueError(f"Please fill in {f.get('label', fid)}.")
            if kind == "url" and not _is_http_url(val):
                raise ValueError(f"{f.get('label', fid)} must be a valid http(s) URL.")
        elif kind == "int":
            try:
                int(val)
            except (TypeError, ValueError):
                raise ValueError(f"{f.get('label', fid)} must be a whole number.") from None
        elif kind == "url_list":
            if isinstance(val, str):
                lines = [ln.strip() for ln in val.splitlines() if ln.strip()]
            elif isinstance(val, list):
                lines = [str(x).strip() for x in val if str(x).strip()]
            else:
                lines = []
            if not lines:
                raise ValueError(f"Add at least one URL for {f.get('label', fid)}.")
            for ln in lines:
                if not _is_http_url(ln):
                    raise ValueError(f"Each line in {f.get('label', fid)} must be a valid http(s) URL.")

    if st == "tribe_rest":
        url = str(config.get("rest_url") or "")
        if "wp-json" not in url:
            raise ValueError(
                "The WordPress REST feed URL should include wp-json (often …/wp-json/tribe/events/v1/events)."
            )
    if st in ("eventbrite_listing",):
        urls = config.get("listing_urls")
        if isinstance(urls, str):
            urls = [urls]
        if not isinstance(urls, list) or not urls:
            raise ValueError("Add at least one Eventbrite listing URL.")


def merge_config_with_expert(
    site_type: str,
    *,
    structured: dict[str, Any],
    expert: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge structured fields with optional expert JSON (advanced)."""
    base = dict(structured)
    if not expert:
        return base
    merged = {**base, **expert}
    merged.pop("type", None)
    merged.pop("enabled", None)
    merged.pop("source_label", None)
    merged.pop("preferences", None)
    return merged


def slugify_source_key(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "source"
