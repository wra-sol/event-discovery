from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CalendarEntry:
    calendar_name: str
    summary: str
    location: str
    start_date: str
    start_at: str
    description: str


@dataclass(frozen=True)
class DailyBriefItem:
    id: int
    title: str
    url: str
    source: str
    relevance_score: float
    candidate_message_draft: str
    calendar_entry: CalendarEntry
    start_at: str | None = None
    end_at: str | None = None
    venue: str | None = None
    relevance_reasons: list[str] = field(default_factory=list)
    first_seen_at: str | None = None
    is_new: bool = False


@dataclass(frozen=True)
class LastCrawlSummary:
    job_id: int
    status: str
    finished_at: str | None = None
    event_count: int | None = None
    error_message: str | None = None

    @classmethod
    def from_job_row(cls, row: dict[str, Any]) -> LastCrawlSummary:
        return cls(
            job_id=int(row["id"]),
            status=str(row["status"]),
            finished_at=row.get("finished_at"),
            event_count=row.get("event_count"),
            error_message=row.get("error_message"),
        )


@dataclass
class DailyBrief:
    generated_at_utc: str
    geography_label: str
    display_name: str
    filters: dict[str, Any]
    pending_count: int
    items: list[DailyBriefItem]
    triage_instructions: str
    last_crawl: LastCrawlSummary | None = None
    crawl_job: LastCrawlSummary | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.last_crawl is None:
            data["last_crawl"] = None
        if self.crawl_job is None:
            data.pop("crawl_job", None)
        return data
