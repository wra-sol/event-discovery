from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .brief_models import CalendarEntry, DailyBrief, DailyBriefItem
from .campaign_config import CampaignProfile, load_campaign_profile
from .pipeline import load_config
from .repository import EventListFilters, list_discovered_events

TRIAGE_INSTRUCTIONS = (
    "For each item, ask the operator to: "
    "(1) **Share** — send the candidate_message_draft and add calendar_entry; "
    "(2) **Ignore** — mark rejected via PATCH /api/automation/events/{id}/review; "
    "(3) **Defer** — leave pending for a later run."
)


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _format_when(start_at: str | None, tz_name: str) -> str:
    dt = _parse_iso_dt(start_at)
    if dt is None:
        return "Date TBD"
    try:
        local = dt.astimezone(ZoneInfo(tz_name))
    except Exception:
        local = dt
    text = local.strftime("%A, %B %d %Y at %I:%M %p")
    return text.replace(" 0", " ").replace(" at 0", " at ")


def _format_date_only(start_at: str | None, tz_name: str) -> str:
    dt = _parse_iso_dt(start_at)
    if dt is None:
        return ""
    try:
        local = dt.astimezone(ZoneInfo(tz_name))
    except Exception:
        local = dt
    return local.strftime("%Y-%m-%d")


def _is_new_since(first_seen_at: str | None, *, hours: int | None) -> bool:
    if hours is None:
        return False
    seen = _parse_iso_dt(first_seen_at)
    if seen is None:
        return False
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return seen >= cutoff


def _candidate_message_draft(
    ev: dict[str, Any],
    *,
    profile: CampaignProfile,
) -> str:
    when = _format_when(ev.get("start_at"), profile.timezone)
    venue = (ev.get("venue") or "").strip()
    where = f" at {venue}" if venue else ""
    label = profile.outreach.candidate_contact_label
    lines = [
        f"Hi {label},",
        "",
        f"Community event in {profile.geography_label}: **{ev.get('title') or 'Untitled'}**",
        f"When: {when}{where}",
        f"Link: {ev.get('url') or ''}",
        "",
        "Worth considering for visibility/listening if your schedule allows.",
    ]
    if profile.outreach.briefing_notes:
        lines.extend(["", profile.outreach.briefing_notes])
    return "\n".join(lines)


def _calendar_entry(ev: dict[str, Any], *, profile: CampaignProfile) -> CalendarEntry:
    title = (ev.get("title") or "Community event").strip()
    venue = (ev.get("venue") or "").strip()
    url = (ev.get("url") or "").strip()
    desc_parts = [f"Source: {ev.get('source') or 'unknown'}"]
    if url:
        desc_parts.append(f"URL: {url}")
    desc_parts.append("Added from event discovery triage.")
    return CalendarEntry(
        calendar_name=profile.outreach.calendar_name,
        summary=title,
        location=venue,
        start_date=_format_date_only(ev.get("start_at"), profile.timezone),
        start_at=(ev.get("start_at") or "")[:19],
        description="\n".join(desc_parts),
    )


def build_daily_brief(
    conn: Any,
    *,
    config_path: str | None = None,
    profile: CampaignProfile | None = None,
) -> DailyBrief:
    """Return pending high-relevance events formatted for operator triage."""
    if profile is None:
        cfg = load_config(config_path if config_path else None)
        profile = load_campaign_profile(cfg)
    brief_cfg = profile.brief

    tz = ZoneInfo(profile.timezone)
    today = datetime.now(tz).date()
    start_to = today + timedelta(days=brief_cfg.days_ahead)

    first_seen_since: str | None = None
    if brief_cfg.only_new_since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=brief_cfg.only_new_since_hours)
        first_seen_since = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    filters = EventListFilters(
        min_score=brief_cfg.min_score,
        reviewed=False,
        rejected=False,
        include_past=brief_cfg.include_past,
        as_of_date=today.isoformat() if not brief_cfg.include_past else None,
        start_to=start_to.isoformat(),
        first_seen_since_utc=first_seen_since,
        sort="relevance",
        order="desc",
    )
    rows = list_discovered_events(conn, filters, limit=brief_cfg.max_items, offset=0)

    items: list[DailyBriefItem] = []
    for row in rows:
        ev = dict(row)
        items.append(
            DailyBriefItem(
                id=ev["id"],
                title=ev["title"],
                url=ev["url"],
                source=ev["source"],
                start_at=ev.get("start_at"),
                end_at=ev.get("end_at"),
                venue=ev.get("venue"),
                relevance_score=float(ev.get("relevance_score") or 0),
                relevance_reasons=ev.get("relevance_reasons") or [],
                first_seen_at=ev.get("first_seen_at"),
                is_new=_is_new_since(
                    ev.get("first_seen_at"),
                    hours=brief_cfg.only_new_since_hours or 168,
                ),
                candidate_message_draft=_candidate_message_draft(ev, profile=profile),
                calendar_entry=_calendar_entry(ev, profile=profile),
            )
        )

    return DailyBrief(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        geography_label=profile.geography_label,
        display_name=profile.display_name,
        filters={
            "min_score": brief_cfg.min_score,
            "days_ahead": brief_cfg.days_ahead,
            "include_past": brief_cfg.include_past,
            "only_new_since_hours": brief_cfg.only_new_since_hours,
            "max_items": brief_cfg.max_items,
        },
        pending_count=len(items),
        items=items,
        triage_instructions=TRIAGE_INSTRUCTIONS,
    )
