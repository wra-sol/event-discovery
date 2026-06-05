from __future__ import annotations

from typing import Any


def format_brief_markdown(brief: dict[str, Any]) -> str:
    """Human-readable daily brief for terminal, email, or chat."""
    lines = [
        f"# Event discovery brief — {brief.get('geography_label', '')}",
        "",
        f"_Generated: {brief.get('generated_at_utc', '')}_",
        f"Pending items: **{brief.get('pending_count', 0)}**",
        "",
    ]
    last = brief.get("last_crawl")
    if isinstance(last, dict) and last.get("status"):
        lines.extend(
            [
                f"Last crawl: job #{last.get('job_id')} — {last.get('status')}"
                + (f" ({last.get('event_count')} events)" if last.get("event_count") is not None else ""),
                "",
            ]
        )

    items = brief.get("items") or []
    if not items:
        lines.append("No pending events match your brief filters.")
        return "\n".join(lines) + "\n"

    for i, item in enumerate(items, start=1):
        title = item.get("title") or "Untitled"
        score = item.get("relevance_score")
        start_at = item.get("start_at") or "TBD"
        venue = item.get("venue") or ""
        url = item.get("url") or ""
        new_tag = " *(new)*" if item.get("is_new") else ""
        lines.extend(
            [
                f"## {i}. {title}{new_tag}",
                "",
                f"- **Score:** {score}",
                f"- **When:** {start_at}",
            ]
        )
        if venue:
            lines.append(f"- **Where:** {venue}")
        if url:
            lines.append(f"- **Link:** {url}")
        lines.extend(
            [
                "",
                "### Candidate message",
                "",
                item.get("candidate_message_draft") or "",
                "",
                "### Calendar",
                "",
            ]
        )
        cal = item.get("calendar_entry") or {}
        if isinstance(cal, dict):
            for key in ("calendar_name", "summary", "location", "start_at", "description"):
                val = cal.get(key)
                if val:
                    lines.append(f"- **{key}:** {val}")
        lines.extend(
            [
                "",
                "**Actions:** Share (send message + calendar) · Ignore · Defer",
                "",
                "---",
                "",
            ]
        )

    instructions = brief.get("triage_instructions")
    if instructions:
        lines.extend(["", f"_{instructions}_", ""])

    return "\n".join(lines)
