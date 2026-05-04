from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)

ALLOWED_TYPES = (
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
    headers = {"User-Agent": os.environ.get("DISCOVER_SOURCE_UA", "FrankDomenicEventDiscovery/0.1 (+source-discovery)")}
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
    }


def build_prompt(page: dict[str, Any]) -> str:
    return f"""You help configure a conservative, robots-respecting event-discovery scraper.
The scraper already supports these adapter types only: {", ".join(ALLOWED_TYPES)}.

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
    if rt is not None and str(rt) not in ALLOWED_TYPES:
        raise ValueError(f"recommended_type must be one of {ALLOWED_TYPES}, got {rt!r}")
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
            "Set OPENAI_API_KEY or LLM_API_KEY for discover-source (or use a compatible API with LLM_API_BASE)."
        )
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You output only valid JSON for event source configuration. No markdown outside JSON unless asked.",
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


def run_discover_source(url: str, *, prompt_only: bool = False) -> dict[str, Any]:
    page = fetch_page_brief(url)
    prompt = build_prompt(page)
    if prompt_only:
        return {"page": page, "prompt": prompt}
    parsed = call_llm_json(prompt)
    return {"page": page, "result": parsed}


def format_yaml_suggestion(source_key: str, result: dict[str, Any]) -> str:
    """Human-readable YAML fragment for pasting under sources: (no PyYAML emit dependency)."""
    rt = result.get("recommended_type") or "unknown"
    sc = result.get("suggested_config") or {}
    lines = [f"  {source_key}:", "    enabled: true", f"    type: {rt}"]
    for k, v in sc.items():
        if isinstance(v, list):
            lines.append(f"    {k}:")
            for item in v:
                lines.append(f"      - {json.dumps(item)}")
        elif isinstance(v, bool):
            lines.append(f"    {k}: {'true' if v else 'false'}")
        elif v is None:
            continue
        elif isinstance(v, (int, float)):
            lines.append(f"    {k}: {v}")
        else:
            lines.append(f"    {k}: {json.dumps(str(v))}")
    return "\n".join(lines)
