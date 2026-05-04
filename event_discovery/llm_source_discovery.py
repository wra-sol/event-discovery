"""CLI helpers for LLM-only source discovery (onboarding). Shared parsing lives in source_discovery."""

from __future__ import annotations

import json
from typing import Any

from .source_discovery import (
    ALLOWED_TYPES,
    DISCOVERY_JSON_SCHEMA_HINT,
    build_prompt,
    call_llm_json,
    fetch_page_brief,
    parse_discovery_response,
)

__all__ = [
    "ALLOWED_TYPES",
    "DISCOVERY_JSON_SCHEMA_HINT",
    "build_prompt",
    "call_llm_json",
    "fetch_page_brief",
    "format_yaml_suggestion",
    "parse_discovery_response",
    "run_discover_source",
]


def run_discover_source(url: str, *, prompt_only: bool = False) -> dict[str, Any]:
    """
    Fetch a URL and use an LLM to suggest a sources: YAML block (CLI onboarding).
    Does not run heuristic probes; use discover_source_proposal() for the full pipeline.
    """
    page = fetch_page_brief(url)
    # Prompt uses excerpt only; drop full body from snapshot if present
    prompt_page = {k: v for k, v in page.items() if k != "_full_body"}
    prompt = build_prompt(prompt_page)
    if prompt_only:
        return {"page": prompt_page, "prompt": prompt}
    parsed = call_llm_json(prompt)
    return {"page": prompt_page, "result": parsed}


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
