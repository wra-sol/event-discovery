from __future__ import annotations

import time
from typing import Any

import httpx

from .automation_run import build_daily_brief_response
from .automation_delivery_settings import (
    AutomationDeliverySettings,
    get_automation_delivery_settings,
    normalize_webhook_inputs,
    save_automation_delivery_settings,
)
from .brief_models import DailyBrief, LastCrawlSummary


class AutomationClientError(RuntimeError):
    pass


def _headers(token: str, account_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token.strip()}",
        "X-Crawl-Account-Id": str(int(account_id)),
        "Content-Type": "application/json",
    }


def create_full_crawl(
    base_url: str,
    *,
    token: str,
    account_id: int,
    timeout: float = 30.0,
) -> int:
    url = f"{base_url.rstrip('/')}/api/crawl-jobs"
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json={"kind": "full"}, headers=_headers(token, account_id))
    if r.status_code != 202:
        raise AutomationClientError(f"crawl create failed ({r.status_code}): {r.text}")
    body = r.json()
    job_id = body.get("job_id")
    if not isinstance(job_id, int):
        raise AutomationClientError(f"unexpected crawl response: {body}")
    return job_id


def get_crawl_job(
    base_url: str,
    *,
    token: str,
    account_id: int,
    job_id: int,
    timeout: float = 30.0,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/crawl-jobs/{int(job_id)}"
    with httpx.Client(timeout=timeout) as client:
        r = client.get(url, headers=_headers(token, account_id))
    if r.status_code != 200:
        raise AutomationClientError(f"crawl poll failed ({r.status_code}): {r.text}")
    body = r.json()
    if not isinstance(body, dict):
        raise AutomationClientError(f"unexpected crawl job response: {body}")
    return body


def wait_for_crawl_job(
    base_url: str,
    *,
    token: str,
    account_id: int,
    job_id: int,
    poll_seconds: float = 5.0,
    timeout_seconds: float = 900.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = get_crawl_job(
            base_url,
            token=token,
            account_id=account_id,
            job_id=job_id,
        )
        status = str(job.get("status") or "")
        if status in ("succeeded", "failed"):
            return job
        time.sleep(poll_seconds)
    raise AutomationClientError(f"crawl job {job_id} timed out after {timeout_seconds}s")


def fetch_daily_brief(
    base_url: str,
    *,
    token: str,
    account_id: int,
    timeout: float = 60.0,
) -> DailyBrief:
    url = f"{base_url.rstrip('/')}/api/daily-brief"
    with httpx.Client(timeout=timeout) as client:
        r = client.get(url, headers=_headers(token, account_id))
    if r.status_code != 200:
        raise AutomationClientError(f"daily brief failed ({r.status_code}): {r.text}")
    body = r.json()
    if not isinstance(body, dict):
        raise AutomationClientError(f"unexpected daily brief response: {body}")
    return _brief_from_api(body)


def _brief_from_api(body: dict[str, Any]) -> DailyBrief:
    from .brief_models import CalendarEntry, DailyBriefItem

    items = [
        DailyBriefItem(
            id=int(item["id"]),
            title=str(item["title"]),
            url=str(item["url"]),
            source=str(item["source"]),
            relevance_score=float(item["relevance_score"]),
            candidate_message_draft=str(item["candidate_message_draft"]),
            calendar_entry=CalendarEntry(**item["calendar_entry"]),
            start_at=item.get("start_at"),
            end_at=item.get("end_at"),
            venue=item.get("venue"),
            relevance_reasons=list(item.get("relevance_reasons") or []),
            first_seen_at=item.get("first_seen_at"),
            is_new=bool(item.get("is_new")),
        )
        for item in body.get("items") or []
    ]
    last_crawl = body.get("last_crawl")
    crawl_job = body.get("crawl_job")
    return DailyBrief(
        generated_at_utc=str(body["generated_at_utc"]),
        geography_label=str(body["geography_label"]),
        display_name=str(body["display_name"]),
        filters=dict(body.get("filters") or {}),
        pending_count=int(body.get("pending_count", 0)),
        items=items,
        triage_instructions=str(body.get("triage_instructions") or ""),
        last_crawl=LastCrawlSummary(**last_crawl) if isinstance(last_crawl, dict) else None,
        crawl_job=LastCrawlSummary(**crawl_job) if isinstance(crawl_job, dict) else None,
    )


def run_remote_daily_automation(
    base_url: str,
    *,
    token: str,
    account_id: int,
    poll_seconds: float = 5.0,
    timeout_seconds: float = 900.0,
) -> DailyBrief:
    """Trigger full crawl, wait for completion, return daily brief."""
    job_id = create_full_crawl(base_url, token=token, account_id=account_id)
    job = wait_for_crawl_job(
        base_url,
        token=token,
        account_id=account_id,
        job_id=job_id,
        poll_seconds=poll_seconds,
        timeout_seconds=timeout_seconds,
    )
    if str(job.get("status")) != "succeeded":
        err = job.get("error_message") or "crawl failed"
        raise AutomationClientError(f"crawl job {job_id} failed: {err}")
    brief = fetch_daily_brief(base_url, token=token, account_id=account_id)
    brief.crawl_job = LastCrawlSummary(
        job_id=int(job["id"]),
        status=str(job["status"]),
        finished_at=job.get("finished_at"),
        event_count=job.get("event_count"),
        error_message=job.get("error_message"),
    )
    return brief


def fetch_automation_delivery(
    base_url: str,
    *,
    token: str,
    account_id: int,
    timeout: float = 30.0,
) -> AutomationDeliverySettings:
    url = f"{base_url.rstrip('/')}/api/automation/delivery"
    with httpx.Client(timeout=timeout) as client:
        r = client.get(url, headers=_headers(token, account_id))
    if r.status_code != 200:
        raise AutomationClientError(f"automation delivery settings failed ({r.status_code}): {r.text}")
    body = r.json()
    if not isinstance(body, dict):
        raise AutomationClientError(f"unexpected automation delivery response: {body}")
    from .automation_delivery_settings import parse_automation_delivery_settings

    return parse_automation_delivery_settings(body)
