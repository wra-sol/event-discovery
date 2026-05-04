"""Run crawl jobs in a background thread (per-process)."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pipeline import run
from .repository import open_connection, update_crawl_job

log = logging.getLogger(__name__)

_job_lock = threading.Lock()
_active: dict[tuple[int, str, int | None], bool] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def start_crawl_job(
    *,
    account_id: int,
    db_path: Path,
    data_root: Path,
    job_id: int,
    kind: str,
    website_id: int | None,
) -> None:
    """
    Spawn a daemon thread to execute the crawl and update crawl_jobs rows.
    Prevents duplicate concurrent jobs per (account, kind, website_id).
    """
    key = (int(account_id), str(kind), website_id)
    with _job_lock:
        if _active.get(key):
            log.info("Skip duplicate crawl job %s for key %s", job_id, key)
            return
        _active[key] = True

    def worker() -> None:
        conn: Any = None
        try:
            conn = open_connection(db_path)
            update_crawl_job(
                conn,
                job_id,
                status="running",
                started_at=_utc_now(),
                error_message=None,
            )
            log.info(
                "Crawl job started job_id=%s account_id=%s kind=%s website_id=%s",
                job_id,
                account_id,
                kind,
                website_id,
            )
            cfg_path = os.environ.get("EVENT_DISCOVERY_CONFIG")
            events = run(
                config_path=cfg_path,
                output_dir=data_root,
                source_filter=None,
                dry_run=False,
                database_path=db_path,
                only_website_id=website_id,
            )
            summary = {
                "event_count": len(events),
                "top_titles": [e.title for e in events[:8]],
            }
            update_crawl_job(
                conn,
                job_id,
                status="succeeded",
                finished_at=_utc_now(),
                event_count=len(events),
                summary_json=json.dumps(summary, ensure_ascii=False),
            )
        except Exception as e:
            log.exception("crawl job %s failed", job_id)
            try:
                conn2 = open_connection(db_path)
                try:
                    update_crawl_job(
                        conn2,
                        job_id,
                        status="failed",
                        finished_at=_utc_now(),
                        error_message=str(e),
                    )
                finally:
                    conn2.close()
            except Exception:
                log.exception("could not persist crawl job failure for job %s", job_id)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            with _job_lock:
                _active.pop(key, None)

    threading.Thread(target=worker, name=f"crawl-job-{job_id}", daemon=True).start()


def run_crawl_job_inline(
    *,
    db_path: Path,
    data_root: Path,
    job_id: int,
    website_id: int | None,
) -> dict[str, Any]:
    """Execute a job synchronously (tests / CLI). Returns summary dict."""
    conn = open_connection(db_path)
    try:
        update_crawl_job(
            conn,
            job_id,
            status="running",
            started_at=_utc_now(),
        )
        cfg_path = os.environ.get("EVENT_DISCOVERY_CONFIG")
        events = run(
            config_path=cfg_path,
            output_dir=data_root,
            source_filter=None,
            dry_run=False,
            database_path=db_path,
            only_website_id=website_id,
        )
        summary = {
            "event_count": len(events),
            "top_titles": [e.title for e in events[:8]],
        }
        update_crawl_job(
            conn,
            job_id,
            status="succeeded",
            finished_at=_utc_now(),
            event_count=len(events),
            summary_json=json.dumps(summary, ensure_ascii=False),
        )
        return summary
    except Exception as e:
        update_crawl_job(
            conn,
            job_id,
            status="failed",
            finished_at=_utc_now(),
            error_message=str(e),
        )
        raise
    finally:
        conn.close()
