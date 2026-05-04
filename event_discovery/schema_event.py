from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

_LD_JSON_SCRIPT = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def sanitize_embedded_json_ld(raw: str) -> str:
    """Strip raw control chars inside JSON strings (some sites embed multiline descriptions)."""
    out: list[str] = []
    i = 0
    in_str = False
    esc = False
    while i < len(raw):
        c = raw[i]
        if esc:
            out.append(c)
            esc = False
        elif c == "\\":
            out.append(c)
            esc = True
        elif c == '"':
            out.append(c)
            in_str = not in_str
        elif in_str and ord(c) < 32 and c not in "\t":
            out.append(" ")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def collect_schema_events(obj: Any, acc: list[dict[str, Any]]) -> None:
    if isinstance(obj, dict):
        types = obj.get("@type")
        if types == "Event" or (isinstance(types, list) and "Event" in types):
            acc.append(obj)
        for v in obj.values():
            collect_schema_events(v, acc)
    elif isinstance(obj, list):
        for item in obj:
            collect_schema_events(item, acc)


def venue_from_schema_location(loc: Any) -> str:
    venue = ""
    if isinstance(loc, list) and loc:
        loc = loc[0]
    if isinstance(loc, dict):
        venue = (loc.get("name") or "").strip()
        addr = loc.get("address")
        if isinstance(addr, dict):
            street = (addr.get("streetAddress") or "").strip()
            if street and venue:
                venue = f"{venue} — {street[:80]}"
            elif street:
                venue = street[:120]
        elif isinstance(addr, str) and addr.strip():
            a = addr.strip()
            if venue:
                venue = f"{venue} — {a[:80]}"
            else:
                venue = a[:120]
    elif isinstance(loc, str) and loc.strip():
        venue = loc.strip()[:200]
    return venue


def iter_ld_event_objects(html: str) -> list[dict[str, Any]]:
    """Parse all application/ld+json blocks and return schema.org Event objects."""
    found: list[dict[str, Any]] = []
    for m in _LD_JSON_SCRIPT.finditer(html):
        raw = sanitize_embedded_json_ld(m.group(1).strip())
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        acc: list[dict[str, Any]] = []
        collect_schema_events(data, acc)
        found.extend(acc)
    return found


def _meta_event_fields(html: str) -> dict[str, str]:
    """Open Graph / common meta tags when JSON-LD is missing fragments."""
    out: dict[str, str] = {}
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or "").strip()
        content = (meta.get("content") or "").strip()
        if not content:
            continue
        pl = prop.lower()
        if pl in ("event:start_time", "og:start_time"):
            out.setdefault("start", content)
        if pl in ("event:end_time", "og:end_time"):
            out.setdefault("end", content)
        if pl in ("event:location", "og:locality"):
            out.setdefault("venue", content[:200])
    for tag in soup.select("[itemprop=startDate]"):
        t = (tag.get("datetime") or tag.get_text(strip=True) or "").strip()
        if t:
            out.setdefault("start", t)
            break
    for tag in soup.select("[itemprop=endDate]"):
        t = (tag.get("datetime") or tag.get_text(strip=True) or "").strip()
        if t:
            out.setdefault("end", t)
            break
    for tag in soup.select("[itemtype*='Event'] [itemprop=location] [itemprop=name]"):
        v = tag.get_text(strip=True)
        if v:
            out.setdefault("venue", v[:200])
            break
    return out


def extract_event_fields_from_html(html: str) -> dict[str, str]:
    """
    Best-effort start, end, venue from JSON-LD Event blocks, then meta/microdata fallbacks.
    Values are raw strings as emitted by the page (often ISO 8601 for dates).
    """
    out: dict[str, str] = {}
    for ev in iter_ld_event_objects(html):
        s = (ev.get("startDate") or "").strip()
        if s:
            out.setdefault("start", s)
        e = (ev.get("endDate") or "").strip()
        if e:
            out.setdefault("end", e)
        v = venue_from_schema_location(ev.get("location"))
        if v:
            out.setdefault("venue", v[:500])
    if not out.get("start") or not out.get("venue"):
        extra = _meta_event_fields(html)
        for k, v in extra.items():
            out.setdefault(k, v)
    return out
