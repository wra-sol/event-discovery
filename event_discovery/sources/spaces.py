from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from ..http_util import ThrottledClient
from ..models import DiscoveredEvent


def _parse_spaces_date_text(date_text: str, ref: date) -> str | None:
    """Return ISO date (YYYY-MM-DD) or None."""
    t = (date_text or "").strip()
    if not t:
        return None
    iso = re.match(r"^(\d{4}-\d{2}-\d{2})$", t)
    if iso:
        return iso.group(1)
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    for fmt in ("%b %d", "%B %d"):
        try:
            d = datetime.strptime(f"{t} {ref.year}", f"{fmt} %Y").date()
        except ValueError:
            continue
        if (ref - d).days > 120:
            try:
                d = d.replace(year=ref.year + 1)
            except ValueError:
                d = datetime.strptime(f"{t} {ref.year + 1}", f"{fmt} %Y").date()
        elif (d - ref).days > 370:
            try:
                d = d.replace(year=ref.year - 1)
            except ValueError:
                pass
        return d.isoformat()
    return None


def fetch_spaces(
    client: ThrottledClient,
    cfg: dict[str, Any],
    log: logging.Logger,
    source_label: str = "spaces",
    today: date | None = None,
) -> list[DiscoveredEvent]:
    from datetime import date as date_cls

    ref = today or date_cls.today()
    base = (cfg.get("base_url") or "https://burlington.spaces.ca").rstrip("/")
    endpoint = (cfg.get("endpoint") or "/posts/eventsbysite").strip()
    max_pages = int(cfg.get("max_pages") or 8)
    out: list[DiscoveredEvent] = []
    seen_ids: set[str] = set()

    for page in range(1, max_pages + 1):
        url = f"{base}{endpoint}?page={page}"
        try:
            resp = client.get(url)
            if resp.status_code != 200:
                log.warning("%s: HTTP %s page %s", source_label, resp.status_code, page)
                break
            fragment = resp.text
        except OSError as e:
            log.warning("%s: page %s failed: %s", source_label, page, e)
            break

        soup = BeautifulSoup(fragment, "html.parser")
        cards = soup.select("div.card.card-body[data-id]")
        if not cards:
            break
        new_count = 0
        for card in cards:
            eid = card.get("data-id")
            if not eid or eid in seen_ids:
                continue
            seen_ids.add(eid)
            link_el = card.select_one("a.event-details, a.post-modal-trigger[href]")
            if not link_el or not link_el.get("href"):
                continue
            href = link_el["href"].strip()
            if href.startswith("/"):
                href = base + href
            title_el = link_el.select_one(".short-post")
            title = title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)
            if not title:
                continue
            date_text = ""
            snippet = card.select_one(".event-body")
            if snippet:
                date_div = snippet.find_next_sibling()
                if date_div:
                    date_text = date_div.get_text(" ", strip=True)
            if not date_text:
                for div in card.find_all("div"):
                    t = div.get_text(strip=True)
                    if re.match(r"^[A-Za-z]{3,9}\s+\d{1,2}$", t) or re.match(
                        r"^\d{4}-\d{2}-\d{2}$", t
                    ):
                        date_text = t
                        break
            space_link = card.select_one('a[href^="/"][class*="space"]')
            space_name = space_link.get_text(strip=True) if space_link else ""
            start_iso = _parse_spaces_date_text(date_text, ref)
            venue = space_name.strip() or None
            raw = " ".join(x for x in [date_text, space_name] if x)
            out.append(
                DiscoveredEvent(
                    title=title,
                    url=href,
                    source=source_label,
                    start=start_iso,
                    venue=venue,
                    raw_snippet=raw[:500],
                )
            )
            new_count += 1
        if new_count == 0:
            break

    log.info("%s: fetched %d events", source_label, len(out))
    return out
