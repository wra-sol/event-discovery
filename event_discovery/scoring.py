from __future__ import annotations

import re
from typing import Any

from .models import DiscoveredEvent, parse_iso_date


def score_event(
    ev: DiscoveredEvent,
    *,
    positive_keywords: list[str],
    negative_keywords: list[str],
    ward_keywords: list[str],
    horizon_days: int,
    today,
) -> DiscoveredEvent:
    """Mutate and return ev with relevance_score and relevance_reasons (handbook §14 triage)."""
    text = f"{ev.title} {ev.venue or ''} {ev.raw_snippet} {ev.url}".lower()
    score = 0.0
    reasons: list[str] = []

    for kw in positive_keywords:
        k = kw.lower()
        if k in text:
            score += 1.0
            reasons.append(f"keyword:{kw}")

    for kw in ward_keywords:
        k = kw.lower()
        if k in text:
            score += 2.0
            reasons.append(f"ward_local:{kw}")

    for kw in negative_keywords:
        k = kw.lower()
        if k in text:
            score -= 2.5
            reasons.append(f"negative:{kw}")

    ev_dt = parse_iso_date(ev.start)
    if ev_dt is not None and horizon_days > 0:
        delta = (ev_dt - today).days
        if delta < 0:
            score -= 1.0
            reasons.append("past_start")
        elif delta > horizon_days:
            score -= 0.5
            reasons.append("beyond_horizon")

    ev.relevance_score = round(score, 2)
    ev.relevance_reasons = reasons
    return ev


def load_scoring_config(cfg: dict[str, Any]) -> dict[str, Any]:
    s = cfg.get("scoring") or {}
    return {
        "positive_keywords": list(s.get("positive_keywords") or []),
        "negative_keywords": list(s.get("negative_keywords") or []),
        "ward_keywords": list(s.get("ward_keywords") or []),
        "horizon_days": int(s.get("horizon_days") or 120),
    }


def slug_title_from_eventbrite_url(url: str) -> str:
    m = re.search(r"/e/([^/?#]+)", url)
    if not m:
        return url
    slug = m.group(1).replace("-tickets-", " ").replace("-", " ")
    return slug.strip().title() if slug else url
