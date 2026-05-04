from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

# The Events Calendar / WordPress often emits one permalink per occurrence
# (slug ends with -{post_id}). Strip that suffix for dedupe unless it looks like a year.
_SLUG_TRAILING_NUM = re.compile(r"^(.+)-(\d+)$")


def _canonical_slug_segment(segment: str) -> str:
    segment = segment.strip().lower()
    if not segment:
        return segment
    m = _SLUG_TRAILING_NUM.match(segment)
    if not m:
        return segment
    num = int(m.group(2))
    if 1900 <= num <= 2100:
        return segment
    return m.group(1)


def normalize_url_for_dedupe(url: str) -> str:
    """Strip query/fragment, normalize host, collapse Tribe/WordPress per-occurrence slug suffixes."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "http").lower()
    netloc = (parsed.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = (parsed.path or "").replace("\\", "/").rstrip("/")
    parts = [p for p in path.split("/") if p]
    if parts:
        parts[-1] = _canonical_slug_segment(parts[-1])
        new_path = "/" + "/".join(parts)
    else:
        new_path = ""
    rebuilt = urlunparse((scheme, netloc, new_path, "", "", ""))
    return rebuilt.rstrip("/")


def dedupe_key_from_url_title(url: str, title: str) -> str:
    u = normalize_url_for_dedupe(url)
    t = " ".join((title or "").lower().split())
    return f"{u}|{t}"


@dataclass
class DiscoveredEvent:
    """Normalized event row from any source adapter."""

    title: str
    url: str
    source: str
    website_id: int | None = None
    """FK to websites.id when the row was produced from DB-configured source."""
    start: str | None = None
    """ISO 8601 date (YYYY-MM-DD) or datetime when known."""
    end: str | None = None
    venue: str | None = None
    raw_snippet: str = ""
    relevance_score: float = 0.0
    relevance_reasons: list[str] = field(default_factory=list)

    def dedupe_key(self) -> str:
        return dedupe_key_from_url_title(self.url, self.title)

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def parse_iso_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    s = value.strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.date()
    except ValueError:
        return None
