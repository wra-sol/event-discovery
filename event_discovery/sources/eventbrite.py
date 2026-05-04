from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

from ..http_util import ThrottledClient
from ..models import DiscoveredEvent
from ..scoring import slug_title_from_eventbrite_url


def _normalize_eventbrite_url(href: str) -> str | None:
    if "/e/" not in href:
        return None
    if "eventbrite.com" not in href and "eventbrite.ca" not in href:
        return None
    parsed = urlparse(href)
    if not parsed.scheme:
        href = "https:" + href if href.startswith("//") else "https://" + href.lstrip("/")
        parsed = urlparse(href)
    clean = urlunparse(
        (parsed.scheme or "https", parsed.netloc, parsed.path, "", "", "")
    )
    return clean


def _listing_implies_date(listing_url: str, today: date) -> str | None:
    u = listing_url.lower()
    if "today" in u:
        return today.isoformat()
    if "this-week" in u or "this_week" in u:
        return today.isoformat()
    if "tomorrow" in u:
        from datetime import timedelta

        return (today + timedelta(days=1)).isoformat()
    return None


def fetch_eventbrite_listings(
    client: ThrottledClient,
    cfg: dict[str, Any],
    log: logging.Logger,
    source_label: str = "eventbrite",
    today: date | None = None,
) -> list[DiscoveredEvent]:
    """Scrape listing pages for /e/ links; real dates and venues come from pipeline enrichment."""
    from datetime import date as date_cls

    today = today or date_cls.today()
    urls = cfg.get("listing_urls") or []
    if isinstance(urls, str):
        urls = [urls]
    out: list[DiscoveredEvent] = []
    seen: set[str] = set()

    for listing_url in urls:
        listing_url = str(listing_url).strip()
        if not listing_url:
            continue
        implied = _listing_implies_date(listing_url, today)
        try:
            resp = client.get(listing_url)
            if resp.status_code != 200:
                log.warning("%s: HTTP %s for %s", source_label, resp.status_code, listing_url)
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
        except OSError as e:
            log.warning("%s: fetch %s failed: %s", source_label, listing_url, e)
            continue

        for a in soup.find_all("a", href=True):
            norm = _normalize_eventbrite_url(a["href"])
            if not norm or norm in seen:
                continue
            seen.add(norm)
            title = a.get_text(separator=" ", strip=True)
            if not title or len(title) < 3:
                title = slug_title_from_eventbrite_url(norm)
            parent = a.find_parent()
            snippet = ""
            if parent:
                snippet = parent.get_text(separator=" ", strip=True)
                if len(snippet) > 350:
                    snippet = snippet[:350] + "…"
            loc_hint = ""
            if re.search(r"\bBurlington\b", snippet, re.I):
                loc_hint = "Mentioned in listing context: Burlington."
            raw = " ".join(
                x
                for x in [
                    f"Listing: {listing_url}",
                    f"Approx. date hint: {implied}" if implied else "",
                    loc_hint,
                    snippet,
                ]
                if x
            )
            out.append(
                DiscoveredEvent(
                    title=title,
                    url=norm,
                    source=source_label,
                    start=implied,
                    venue=None,
                    raw_snippet=raw[:600],
                )
            )

    log.info("%s: extracted %d unique event links", source_label, len(out))
    return out
