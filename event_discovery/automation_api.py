from __future__ import annotations

import os
import time
from typing import Any

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlite3 import Connection

from .automation_run import build_daily_brief_response
from .repository import get_crawl_job, insert_crawl_job, update_event_review


class DailyBriefItemResponse(BaseModel):
    id: int
    title: str
    url: str
    source: str
    start_at: str | None = None
    end_at: str | None = None
    venue: str | None = None
    relevance_score: float
    relevance_reasons: list[str] = Field(default_factory=list)
    first_seen_at: str | None = None
    is_new: bool = False
    candidate_message_draft: str
    calendar_entry: dict[str, str]


class DailyBriefResponse(BaseModel):
    generated_at_utc: str
    geography_label: str
    display_name: str
    filters: dict[str, Any]
    pending_count: int
    items: list[DailyBriefItemResponse]
    triage_instructions: str
    last_crawl: dict[str, Any] | None = None


class AutomationRunRequest(BaseModel):
    kind: str = "full"
    wait: bool = True
    poll_seconds: float = Field(default=5.0, ge=0.5, le=60.0)
    timeout_seconds: float = Field(default=300.0, ge=1.0, le=1800.0)


class CrawlJobResponse(BaseModel):
    id: int
    kind: str
    website_id: int | None = None
    status: str
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    event_count: int | None = None
    error_message: str | None = None


class AutomationRunResponse(BaseModel):
    job: CrawlJobResponse
    brief: DailyBriefResponse | None = None
    timed_out: bool = False
    next_poll_url: str | None = None
    brief_url: str = "/api/daily-brief"


class AutomationReviewPatch(BaseModel):
    reviewed: bool | None = None
    rejected: bool | None = None
    notes: str | None = None


class AutomationReviewState(BaseModel):
    id: int
    reviewed: bool
    rejected: bool
    notes: str


class WebhookDestinationResponse(BaseModel):
    id: str
    label: str
    url: str
    enabled: bool


class AutomationDeliveryResponse(BaseModel):
    webhooks: list[WebhookDestinationResponse]
    skip_if_empty: bool


class WebhookDestinationInput(BaseModel):
    id: str | None = None
    label: str = ""
    url: str
    enabled: bool = True


class AutomationDeliveryUpdate(BaseModel):
    webhooks: list[WebhookDestinationInput] = Field(default_factory=list)
    skip_if_empty: bool = False


def _delivery_response(settings: Any) -> AutomationDeliveryResponse:
    return AutomationDeliveryResponse(
        webhooks=[
            WebhookDestinationResponse(
                id=w.id,
                label=w.label,
                url=w.url,
                enabled=w.enabled,
            )
            for w in settings.webhooks
        ],
        skip_if_empty=settings.skip_if_empty,
    )


def _job_response(row: dict[str, Any]) -> CrawlJobResponse:
    return CrawlJobResponse(
        id=int(row["id"]),
        kind=str(row["kind"]),
        website_id=row.get("website_id"),
        status=str(row["status"]),
        created_at=row.get("created_at"),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        event_count=row.get("event_count"),
        error_message=row.get("error_message"),
    )


def _wait_for_job(conn: Connection, job_id: int, *, poll_seconds: float, timeout_seconds: float) -> tuple[dict[str, Any], bool]:
    deadline = time.monotonic() + timeout_seconds
    last = get_crawl_job(conn, job_id)
    if last is None:
        raise HTTPException(status_code=404, detail="Job not found")
    while str(last.get("status")) not in ("succeeded", "failed"):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return last, True
        time.sleep(min(poll_seconds, remaining))
        next_row = get_crawl_job(conn, job_id)
        if next_row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        last = next_row
    return last, False


def register_automation_routes(app: Any) -> None:
    """Attach automation-only routes; call after web deps are defined."""
    from .web import (
        _require_writes_allowed,
        ensure_account_db_ready,
        get_db_crawl,
        get_db_agent,
        open_connection,
        require_user_or_agent_api,
        require_user_or_agent_or_crawl_api,
        require_user_or_crawl_api,
        start_crawl_job,
    )

    @app.get("/api/daily-brief", response_model=DailyBriefResponse, tags=["automation"])
    def api_daily_brief(
        conn: Connection = Depends(get_db_crawl),
        user: dict[str, Any] = Depends(require_user_or_crawl_api),
    ) -> DailyBriefResponse:
        _ = user
        brief = build_daily_brief_response(
            conn,
            config_path=os.environ.get("EVENT_DISCOVERY_CONFIG"),
        )
        return DailyBriefResponse.model_validate(brief.to_dict())

    @app.post(
        "/api/automation/run",
        status_code=202,
        response_model=AutomationRunResponse,
        tags=["automation"],
    )
    def api_automation_run(
        request: Request,
        body: AutomationRunRequest,
        user: dict[str, Any] = Depends(require_user_or_agent_or_crawl_api),
    ) -> AutomationRunResponse:
        _require_writes_allowed(request)
        if body.kind.strip().lower() != "full":
            raise HTTPException(status_code=422, detail='Only kind "full" is supported here')

        account_id = int(user["account_id"])
        db_path = ensure_account_db_ready(request, account_id)
        conn = open_connection(db_path)
        try:
            job_id = insert_crawl_job(conn, kind="full", website_id=None)
            start_crawl_job(
                account_id=account_id,
                db_path=db_path,
                data_root=request.app.state.data_root,
                job_id=job_id,
                kind="full",
                website_id=None,
            )

            row = get_crawl_job(conn, job_id)
            if row is None:
                raise HTTPException(status_code=500, detail="Could not load queued crawl job")

            timed_out = False
            if body.wait:
                row, timed_out = _wait_for_job(
                    conn,
                    job_id,
                    poll_seconds=body.poll_seconds,
                    timeout_seconds=body.timeout_seconds,
                )

            brief: DailyBriefResponse | None = None
            if str(row.get("status")) == "succeeded":
                daily = build_daily_brief_response(
                    conn,
                    config_path=os.environ.get("EVENT_DISCOVERY_CONFIG"),
                )
                brief = DailyBriefResponse.model_validate(daily.to_dict())

            return AutomationRunResponse(
                job=_job_response(row),
                brief=brief,
                timed_out=timed_out,
                next_poll_url=f"/api/crawl-jobs/{job_id}"
                if timed_out or str(row.get("status")) not in ("succeeded", "failed")
                else None,
            )
        finally:
            conn.close()

    @app.get(
        "/api/automation/delivery",
        response_model=AutomationDeliveryResponse,
        tags=["automation"],
    )
    def api_automation_delivery_get(
        conn: Connection = Depends(get_db_agent),
        user: dict[str, Any] = Depends(require_user_or_agent_api),
    ) -> AutomationDeliveryResponse:
        _ = user
        from .automation_delivery_settings import get_automation_delivery_settings

        settings = get_automation_delivery_settings(conn)
        return _delivery_response(settings)

    @app.put(
        "/api/automation/delivery",
        response_model=AutomationDeliveryResponse,
        tags=["automation"],
    )
    def api_automation_delivery_put(
        request: Request,
        body: AutomationDeliveryUpdate,
        conn: Connection = Depends(get_db_agent),
        user: dict[str, Any] = Depends(require_user_or_agent_api),
    ) -> AutomationDeliveryResponse:
        _ = user
        _require_writes_allowed(request)
        from .automation_delivery_settings import (
            AutomationDeliverySettings,
            normalize_webhook_inputs,
            save_automation_delivery_settings,
        )
        from .settings_env import is_production

        allow_http = not is_production()
        try:
            webhooks = normalize_webhook_inputs(
                [w.model_dump() for w in body.webhooks],
                allow_http=allow_http,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        settings = AutomationDeliverySettings(
            webhooks=webhooks,
            skip_if_empty=body.skip_if_empty,
        )
        save_automation_delivery_settings(conn, settings)
        return _delivery_response(settings)

    @app.patch(
        "/api/automation/events/{event_id}/review",
        response_model=AutomationReviewState,
        tags=["automation"],
    )
    def api_automation_patch_review(
        request: Request,
        event_id: int,
        body: AutomationReviewPatch,
        conn: Connection = Depends(get_db_crawl),
        user: dict[str, Any] = Depends(require_user_or_crawl_api),
    ) -> AutomationReviewState:
        _ = user
        _require_writes_allowed(request)
        result = update_event_review(
            conn,
            event_id,
            reviewed=body.reviewed,
            rejected=body.rejected,
            notes=body.notes,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return AutomationReviewState.model_validate(result)
