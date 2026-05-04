"""Shared URL-based crawl strategy discovery (heuristics + optional LLM)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .schema_event import iter_ld_event_objects
from .source_validation import slugify_source_key, validate_website_type_and_config

log = logging.getLogger(__name__)

# Includes "unknown" for LLM / API responses; handlers use KNOWN_SOURCE_TYPES without unknown.
DISCOVERY_ALLOWED_TYPES = (
    "tribe_rest",
    "json_ld_events",
    "burlington_events_ldjson",
    "eventbrite_listing",
    "spaces_fragment",
    "looklocal_page",
    "unknown",
)

DISCOVERY_JSON_SCHEMA_HINT = """
Return a single JSON object with exactly these keys:
- recommended_type: one of: tribe_rest, json_ld_events, burlington_events_ldjson, eventbrite_listing, spaces_fragment, looklocal_page, unknown
- confidence: number from 0 to 1
- suggested_config: object with keys that match our YAML source block for that type (omit enabled). Examples:
  tribe_rest: rest_url, per_page, max_pages
  json_ld_events or burlington_events_ldjson: page_url
  eventbrite_listing: listing_urls (array of strings)
  spaces_fragment: base_url, endpoint, max_pages
  looklocal_page: page_url
- evidence: array of short strings (what you observed)
- caveats: array of short strings (JS-only calendars, logins, ambiguity, etc.)
"""


def _truncate(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n… [truncated]"


def fetch_page_brief(url: str, *, timeout: float = 45.0, max_chars: int = 60000) -> dict[str, Any]:
    """Fetch URL; return status, selected headers, and truncated body for LLM context."""
    headers = {
        "User-Agent": os.environ.get(
            "DISCOVER_SOURCE_UA",
            "FrankDomenicEventDiscovery/0.1 (+source-discovery)",
        )
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
    interesting = {}
    for k in ("content-type", "server", "link"):
        if k in resp.headers:
            interesting[k] = resp.headers[k]
    text = resp.text or ""
    return {
        "url": str(resp.url),
        "status_code": resp.status_code,
        "headers": interesting,
        "body_excerpt": _truncate(text, max_chars),
        "_full_body": text,
    }


def build_prompt(page: dict[str, Any]) -> str:
    return f"""You help configure a conservative, robots-respecting event-discovery scraper.
The scraper already supports these adapter types only: {", ".join(DISCOVERY_ALLOWED_TYPES)}.

Analyze the HTTP response below and guess which adapter fits best, or "unknown" if none apply.

{DISCOVERY_JSON_SCHEMA_HINT}

--- HTTP snapshot ---
Final URL: {page.get("url")}
Status: {page.get("status_code")}
Headers: {json.dumps(page.get("headers") or {}, indent=2)}
Body (possibly truncated HTML or JSON):
{page.get("body_excerpt", "")}
"""


def parse_discovery_response(content: str) -> dict[str, Any]:
    """
    Parse model output into a dict. Accepts raw JSON or a fenced ```json block.
    Raises ValueError on invalid shape.
    """
    s = content.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.I)
    if fence:
        s = fence.group(1).strip()
    data = json.loads(s)
    if not isinstance(data, dict):
        raise ValueError("root must be a JSON object")
    rt = data.get("recommended_type")
    if rt is not None and str(rt) not in DISCOVERY_ALLOWED_TYPES:
        raise ValueError(
            f"recommended_type must be one of {DISCOVERY_ALLOWED_TYPES}, got {rt!r}"
        )
    conf = data.get("confidence")
    if conf is not None and not isinstance(conf, (int, float)):
        raise ValueError("confidence must be a number")
    sc = data.get("suggested_config")
    if sc is not None and not isinstance(sc, dict):
        raise ValueError("suggested_config must be an object")
    for key in ("evidence", "caveats"):
        v = data.get(key)
        if v is not None:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ValueError(f"{key} must be an array of strings")
    return data


def _chat_completions_url() -> str:
    base = (os.environ.get("LLM_API_BASE") or "https://api.openai.com/v1").rstrip("/")
    return f"{base}/chat/completions"


def call_llm_json(prompt: str, *, timeout: float = 120.0) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set OPENAI_API_KEY or LLM_API_KEY for discover-source "
            "(or use a compatible API with LLM_API_BASE)."
        )
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You output only valid JSON for event source configuration. "
                    "No markdown outside JSON unless asked."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    if "openai.com" in _chat_completions_url():
        body["response_format"] = {"type": "json_object"}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(_chat_completions_url(), headers=headers, json=body)
        r.raise_for_status()
        payload = r.json()
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("LLM response missing choices")
    msg = choices[0].get("message") or {}
    raw = (msg.get("content") or "").strip()
    if not raw:
        raise RuntimeError("LLM returned empty content")
    return parse_discovery_response(raw)


def _discovery_headers() -> dict[str, str]:
    return {
        "User-Agent": os.environ.get(
            "DISCOVER_SOURCE_UA",
            "FrankDomenicEventDiscovery/0.1 (+source-discovery)",
        ),
        "Accept": "*/*",
    }


def _origin_from_url(url: str) -> str:
    p = urlparse(url)
    scheme = p.scheme or "https"
    if not p.netloc:
        return url.rstrip("/")
    return f"{scheme}://{p.netloc}".rstrip("/")


def _extract_title(html: str) -> str:
    if not html.strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    t = soup.find("title")
    if t:
        return (t.get_text() or "").strip()[:200]
    return ""


def _default_source_key(final_url: str) -> str:
    p = urlparse(final_url)
    raw = f"{p.netloc}{p.path}".strip("/")
    return slugify_source_key(raw.replace("/", "-"))


def _default_source_label(final_url: str, html: str) -> str:
    t = _extract_title(html)
    if t:
        return t
    p = urlparse(final_url)
    return p.netloc if p.netloc else "event source"


def _probe_tribe_rest(origin: str, *, timeout: float) -> str | None:
    feed = f"{origin.rstrip('/')}/wp-json/tribe/events/v1/events"
    url = f"{feed}?per_page=1"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            r = client.get(url, headers=_discovery_headers())
    except OSError as e:
        log.debug("tribe probe failed: %s", e)
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except json.JSONDecodeError:
        return None
    ev = data.get("events")
    if isinstance(ev, list):
        return feed
    return None


def _probe_spaces_fragment(origin: str, *, timeout: float) -> dict[str, Any] | None:
    base = origin.rstrip("/")
    endpoint = "/posts/eventsbysite"
    frag_url = f"{base}{endpoint}?page=1"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            r = client.get(frag_url, headers=_discovery_headers())
    except OSError as e:
        log.debug("spaces probe failed: %s", e)
        return None
    if r.status_code != 200:
        return None
    text = r.text or ""
    if "card-body" in text and "data-id" in text:
        return {"base_url": base, "endpoint": endpoint}
    return None


def _is_eventbrite_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "eventbrite.com" in host or "eventbrite.ca" in host


def _heuristic_discover(
    page: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any] | None:
    """
    Return a candidate dict with keys recommended_type, confidence, suggested_config,
    evidence, caveats, or None if no strong heuristic match.
    """
    final_url = str(page.get("url") or "")
    body = str(page.get("_full_body") or page.get("body_excerpt") or "")
    status = int(page.get("status_code") or 0)
    evidence: list[str] = []
    caveats: list[str] = []

    if _is_eventbrite_url(final_url):
        evidence.append("URL host matches Eventbrite (eventbrite.com / .ca).")
        return {
            "recommended_type": "eventbrite_listing",
            "confidence": 0.9,
            "suggested_config": {"listing_urls": [final_url]},
            "evidence": evidence,
            "caveats": caveats,
        }

    origin = _origin_from_url(final_url)

    rest_url = _probe_tribe_rest(origin, timeout=timeout)
    if rest_url:
        evidence.append(
            "WordPress Tribe REST endpoint responded with JSON containing an events array."
        )
        return {
            "recommended_type": "tribe_rest",
            "confidence": 0.92,
            "suggested_config": {"rest_url": rest_url},
            "evidence": evidence,
            "caveats": caveats,
        }

    if status == 200 and body:
        ld_events = iter_ld_event_objects(body)
        if ld_events:
            evidence.append(
                f"Found {len(ld_events)} schema.org Event object(s) in JSON-LD on the page."
            )
            return {
                "recommended_type": "json_ld_events",
                "confidence": 0.85,
                "suggested_config": {"page_url": final_url},
                "evidence": evidence,
                "caveats": caveats,
            }

    host = urlparse(final_url).netloc.lower()
    if ".spaces.ca" in host or host.endswith("spaces.ca"):
        frag = _probe_spaces_fragment(origin, timeout=timeout)
        if frag:
            evidence.append(
                "Spaces.ca host and calendar fragment endpoint returned event card markup."
            )
            return {
                "recommended_type": "spaces_fragment",
                "confidence": 0.82,
                "suggested_config": frag,
                "evidence": evidence,
                "caveats": caveats,
            }

    if status == 200 and body:
        if "/posts/eventsbysite" in body or "eventsbysite" in body:
            frag = _probe_spaces_fragment(origin, timeout=timeout)
            if frag:
                evidence.append("Page references Spaces eventsbysite fragment; probe succeeded.")
                return {
                    "recommended_type": "spaces_fragment",
                    "confidence": 0.78,
                    "suggested_config": frag,
                    "evidence": evidence,
                    "caveats": caveats,
                }

    return None


def _merge_evidence(a: list[str], b: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in a + b:
        t = (x or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def finalize_proposal(
    raw: dict[str, Any],
    *,
    discovered_url: str,
    html_for_title: str,
    method: str,
) -> dict[str, Any]:
    """Attach metadata, validate config, set save_ready."""
    rt = str(raw.get("recommended_type") or "unknown").strip()
    conf = raw.get("confidence")
    if conf is None:
        confidence = 0.0
    else:
        try:
            confidence = float(conf)
        except (TypeError, ValueError):
            confidence = 0.0
    suggested = dict(raw.get("suggested_config") or {})
    evidence = list(raw.get("evidence") or [])
    caveats = list(raw.get("caveats") or [])
    if not isinstance(evidence, list):
        evidence = []
    if not isinstance(caveats, list):
        caveats = []
    evidence = [str(x) for x in evidence if str(x).strip()]
    caveats = [str(x) for x in caveats if str(x).strip()]

    source_key = raw.get("source_key")
    if not isinstance(source_key, str) or not source_key.strip():
        source_key = _default_source_key(discovered_url)
    else:
        source_key = slugify_source_key(source_key)

    source_label = raw.get("source_label")
    if not isinstance(source_label, str) or not source_label.strip():
        source_label = _default_source_label(discovered_url, html_for_title)
    else:
        source_label = source_label.strip()[:200]

    save_ready = False
    validation_error: str | None = None

    if rt == "unknown":
        caveats = _merge_evidence(
            caveats,
            ["Could not determine a supported adapter automatically."],
        )
        return {
            "recommended_type": "unknown",
            "confidence": confidence,
            "suggested_config": suggested,
            "source_key": source_key,
            "source_label": source_label,
            "evidence": evidence,
            "caveats": caveats,
            "method": method,
            "save_ready": False,
            "validation_error": None,
            "discovered_url": discovered_url,
            "fallback_type": "json_ld_events",
            "fallback_config": {"page_url": discovered_url},
        }

    try:
        validate_website_type_and_config(rt, suggested)
        save_ready = True
    except ValueError as e:
        validation_error = str(e)
        caveats = _merge_evidence(caveats, [f"Validation: {validation_error}"])

    return {
        "recommended_type": rt,
        "confidence": confidence,
        "suggested_config": suggested,
        "source_key": source_key,
        "source_label": source_label,
        "evidence": evidence,
        "caveats": caveats,
        "method": method,
        "save_ready": save_ready,
        "validation_error": validation_error,
        "discovered_url": discovered_url,
        "fallback_type": None,
        "fallback_config": None,
    }


def discover_source_proposal(
    url: str,
    *,
    use_llm: bool = True,
    source_key: str | None = None,
    source_label: str | None = None,
    timeout: float = 45.0,
    max_chars: int = 60000,
) -> dict[str, Any]:
    """
    Fetch url, run deterministic probes, optionally call LLM, return a UI-ready proposal dict.

    The returned dict includes save_ready when suggested_config passes validate_website_type_and_config.
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("URL is required.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    page = fetch_page_brief(url, timeout=timeout, max_chars=max_chars)
    body_full = page.pop("_full_body", "")
    # Keep excerpt for any prompt rebuild
    page_for_prompt = {**page, "body_excerpt": page.get("body_excerpt", "")}
    page_internal = {**page_for_prompt, "_full_body": body_full}

    discovered_url = str(page.get("url") or url)
    html_for_title = body_full if body_full else str(page.get("body_excerpt") or "")

    heuristic = _heuristic_discover(page_internal, timeout=timeout)
    method = "unknown"
    candidate: dict[str, Any] | None = None

    if heuristic:
        candidate = heuristic
        method = "heuristic"
    elif use_llm:
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
        if api_key:
            try:
                prompt = build_prompt(page_for_prompt)
                candidate = call_llm_json(prompt, timeout=min(120.0, timeout + 60.0))
                method = "llm"
            except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as e:
                log.info("LLM discovery failed: %s", e)
                candidate = {
                    "recommended_type": "unknown",
                    "confidence": 0.0,
                    "suggested_config": {},
                    "evidence": [],
                    "caveats": [f"AI suggestion failed: {e}"],
                }
                method = "unknown"
        else:
            candidate = {
                "recommended_type": "unknown",
                "confidence": 0.0,
                "suggested_config": {},
                "evidence": [],
                "caveats": [
                    "Heuristics did not match a known adapter. "
                    "Set OPENAI_API_KEY or LLM_API_KEY to enable AI-assisted detection."
                ],
            }
            method = "unknown"
    else:
        candidate = {
            "recommended_type": "unknown",
            "confidence": 0.0,
            "suggested_config": {},
            "evidence": [],
            "caveats": [
                "Heuristics did not match a known adapter and AI assist was turned off."
            ],
        }
        method = "unknown"

    if source_key:
        candidate = {**candidate, "source_key": source_key}
    if source_label:
        candidate = {**candidate, "source_label": source_label}

    return finalize_proposal(
        candidate,
        discovered_url=discovered_url,
        html_for_title=html_for_title,
        method=method,
    )


def pick_type_and_config_for_website(proposal: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Choose (site_type, config) for persisting a website after discovery.

    Prefers a validated primary suggestion, then fallback (e.g. json_ld_events + page_url),
    then a re-validation of the primary type with its suggested_config.

    Raises ValueError with a human-readable message if nothing validates.
    """
    if proposal.get("save_ready") and proposal.get("recommended_type") not in (
        None,
        "",
        "unknown",
    ):
        return str(proposal["recommended_type"]), dict(proposal.get("suggested_config") or {})

    fb_t = proposal.get("fallback_type")
    fb_c = proposal.get("fallback_config")
    if isinstance(fb_t, str) and fb_t.strip() and isinstance(fb_c, dict):
        try:
            validate_website_type_and_config(fb_t.strip(), dict(fb_c))
            return fb_t.strip(), dict(fb_c)
        except ValueError:
            pass

    rt = proposal.get("recommended_type")
    sc = proposal.get("suggested_config")
    if isinstance(rt, str) and rt.strip() and rt != "unknown" and isinstance(sc, dict):
        try:
            validate_website_type_and_config(rt.strip(), dict(sc))
            return rt.strip(), dict(sc)
        except ValueError:
            pass

    caveats = proposal.get("caveats") or []
    msg = " ".join(str(c) for c in caveats if str(c).strip()) or (
        "Could not determine a supported crawl strategy for this URL."
    )
    raise ValueError(msg)


# Backwards compatibility for tests importing ALLOWED_TYPES
ALLOWED_TYPES = DISCOVERY_ALLOWED_TYPES
