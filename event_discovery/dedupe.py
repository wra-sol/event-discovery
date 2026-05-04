from __future__ import annotations

from .models import DiscoveredEvent

_MERGE_NOTE = "\n— [Merged {n} date-specific listings.]"


def merge_discovered_event_group(events: list[DiscoveredEvent]) -> DiscoveredEvent:
    """Pick the earliest-dated occurrence; carry max score and merged reasons (for DB compaction)."""
    if not events:
        raise ValueError("merge_discovered_event_group: empty list")
    if len(events) == 1:
        return events[0]

    def sort_key(e: DiscoveredEvent) -> tuple[str, str]:
        return (e.start or "9999-99-99", e.url)

    sorted_e = sorted(events, key=sort_key)
    base = sorted_e[0]
    n = len(sorted_e)
    note = _MERGE_NOTE.format(n=n)
    snippet = (base.raw_snippet or "").strip()
    if note.strip() not in snippet:
        snippet = (snippet + note).strip() if snippet else note.strip()

    max_score = max(e.relevance_score for e in sorted_e)
    seen_r: set[str] = set()
    merged_reasons: list[str] = []
    for e in sorted_e:
        for r in e.relevance_reasons:
            if r not in seen_r:
                seen_r.add(r)
                merged_reasons.append(r)

    return DiscoveredEvent(
        title=base.title,
        url=base.url,
        source=base.source,
        website_id=base.website_id,
        start=base.start,
        end=base.end,
        venue=base.venue,
        raw_snippet=snippet,
        relevance_score=max_score,
        relevance_reasons=merged_reasons,
    )


def dedupe_events(events: list[DiscoveredEvent]) -> list[DiscoveredEvent]:
    buckets: dict[str, list[DiscoveredEvent]] = {}
    for ev in events:
        buckets.setdefault(ev.dedupe_key(), []).append(ev)
    return [merge_discovered_event_group(g) for g in buckets.values()]
