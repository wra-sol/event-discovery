from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .brief_format import format_brief_markdown
from .brief_models import DailyBrief, LastCrawlSummary
from .daily_brief import build_daily_brief
from .pipeline import migrate_database_only
from .repository import insert_crawl_job, list_crawl_jobs, open_connection

log = logging.getLogger(__name__)


def last_crawl_summary(conn: Any) -> LastCrawlSummary | None:
    jobs = list_crawl_jobs(conn, limit=1)
    if not jobs:
        return None
    return LastCrawlSummary.from_job_row(jobs[0])


def build_daily_brief_response(
    conn: Any,
    *,
    config_path: str | None,
) -> DailyBrief:
    brief = build_daily_brief(conn, config_path=config_path)
    brief.last_crawl = last_crawl_summary(conn)
    return brief


def run_local_daily_automation(
    *,
    config_path: str | None,
    output_dir: Path,
    database_path: Path,
    skip_crawl: bool = False,
) -> DailyBrief:
    """
    Crawl all enabled sources into the account DB, then build the daily brief.
    For cron on the same volume as the web app (no HTTP round-trip).
    """
    import os

    from .crawl_runner import run_crawl_job_inline

    migrate_database_only(
        config_path=config_path,
        output_dir=output_dir,
        database_path=database_path,
    )

    last_crawl: LastCrawlSummary | None = None
    if not skip_crawl:
        conn = open_connection(database_path)
        try:
            job_id = insert_crawl_job(conn, kind="full", website_id=None)
        finally:
            conn.close()
        log.info("Running full crawl job_id=%s", job_id)
        summary = run_crawl_job_inline(
            db_path=database_path,
            data_root=output_dir,
            job_id=job_id,
            website_id=None,
        )
        last_crawl = LastCrawlSummary(
            job_id=job_id,
            status="succeeded",
            event_count=summary.get("event_count"),
        )
    else:
        conn = open_connection(database_path)
        try:
            last_crawl = last_crawl_summary(conn)
        finally:
            conn.close()

    conn = open_connection(database_path)
    try:
        brief = build_daily_brief(
            conn,
            config_path=config_path or os.environ.get("EVENT_DISCOVERY_CONFIG"),
        )
    finally:
        conn.close()

    brief.last_crawl = last_crawl
    if last_crawl is not None:
        brief.crawl_job = last_crawl
    return brief


def emit_brief(brief: DailyBrief, *, fmt: str) -> str:
    payload = brief.to_dict()
    if fmt == "markdown":
        return format_brief_markdown(payload)
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
