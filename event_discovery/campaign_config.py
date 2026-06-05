from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BriefConfig:
    min_score: float = 1.0
    max_items: int = 15
    include_past: bool = False
    days_ahead: int = 45
    only_new_since_hours: int | None = None


@dataclass(frozen=True)
class OutreachConfig:
    candidate_contact_label: str = "the candidate"
    calendar_name: str = "Campaign events"
    briefing_notes: str = ""


@dataclass(frozen=True)
class CampaignProfile:
    display_name: str = "Campaign team"
    geography_label: str = "Burlington, Ontario"
    timezone: str = "America/Toronto"
    brief: BriefConfig = BriefConfig()
    outreach: OutreachConfig = OutreachConfig()


def _brief_from_dict(raw: dict[str, Any]) -> BriefConfig:
    return BriefConfig(
        min_score=float(raw.get("min_score", 1.0)),
        max_items=max(1, min(int(raw.get("max_items", 15)), 50)),
        include_past=bool(raw.get("include_past", False)),
        days_ahead=max(1, int(raw.get("days_ahead", 45))),
        only_new_since_hours=(
            int(raw["only_new_since_hours"])
            if raw.get("only_new_since_hours") is not None
            else None
        ),
    )


def _outreach_from_dict(raw: dict[str, Any]) -> OutreachConfig:
    return OutreachConfig(
        candidate_contact_label=str(
            raw.get("candidate_contact_label") or "the candidate"
        ),
        calendar_name=str(raw.get("calendar_name") or "Campaign events"),
        briefing_notes=str(raw.get("briefing_notes") or "").strip(),
    )


def load_campaign_profile(cfg: dict[str, Any]) -> CampaignProfile:
    """Load optional `campaign:` block from merged YAML config."""
    raw = cfg.get("campaign") or {}
    if not isinstance(raw, dict):
        raw = {}
    brief_raw = raw.get("brief") or {}
    outreach_raw = raw.get("outreach") or {}
    if not isinstance(brief_raw, dict):
        brief_raw = {}
    if not isinstance(outreach_raw, dict):
        outreach_raw = {}
    return CampaignProfile(
        display_name=str(raw.get("display_name") or "Campaign team"),
        geography_label=str(raw.get("geography_label") or "Burlington, Ontario"),
        timezone=str(raw.get("timezone") or "America/Toronto"),
        brief=_brief_from_dict(brief_raw),
        outreach=_outreach_from_dict(outreach_raw),
    )
