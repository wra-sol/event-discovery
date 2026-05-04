from __future__ import annotations

import logging
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .dedupe import dedupe_events
from .enrich import enrich_discovered_events
from .http_util import ThrottledClient
from .models import DiscoveredEvent
from .paths import account_discovery_db_path
from .repository import (
    enabled_websites_count,
    ensure_discovery_seeded,
    fetch_website_source_for_crawl,
    iter_enabled_website_sources,
    load_all_website_preferences,
    merge_config_with_db,
    merge_site_preferences_into_cfg,
    open_connection,
    persist_discovery,
)
from .robots_check import allowed_fetch
from .schema_migrations import apply_migrations
from .scoring import load_scoring_config, score_event
from .sources.registry import (
    SOURCE_HANDLERS,
    iter_source_configs,
    resolve_event_source_label,
    source_robots_probe_url,
)

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent


def load_config(override_path: str | None) -> dict[str, Any]:
    default_path = PACKAGE_DIR / "config.default.yaml"
    with open(default_path, encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}
    if override_path and Path(override_path).is_file():
        with open(override_path, encoding="utf-8") as f:
            extra = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, extra)
    return cfg


def _deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _robots_ok(client: ThrottledClient, user_agent: str, url: str) -> bool:
    return allowed_fetch(lambda u: client.get(u), url, user_agent)


def resolve_db_path(cfg: dict[str, Any], output_dir: Path) -> Path:
    env = os.environ.get("DISCOVERY_DB_PATH")
    if env:
        return Path(env)
    railway_mount = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    base = Path(railway_mount) if railway_mount else output_dir
    db_cfg = cfg.get("database") or {}
    name = str(db_cfg.get("filename") or "discovery.db")
    flat = base / name
    migrated_default = account_discovery_db_path(base, 1, cfg=cfg)
    if migrated_default.is_file() and not flat.is_file():
        return migrated_default
    return flat


def collect_events(
    cfg: dict[str, Any],
    client: ThrottledClient,
    *,
    source_filter: set[str] | None,
    today_local: date,
    website_conn: sqlite3.Connection | None = None,
    only_website_id: int | None = None,
) -> list[DiscoveredEvent]:
    http_cfg = cfg.get("http") or {}
    default_ua = str(http_cfg.get("user_agent") or "")
    all_events: list[DiscoveredEvent] = []

    def want(name: str) -> bool:
        if source_filter is None:
            return True
        return name in source_filter

    use_website_table = website_conn is not None and (
        only_website_id is not None or enabled_websites_count(website_conn) > 0
    )
    if use_website_table:
        if only_website_id is not None:
            row = fetch_website_source_for_crawl(website_conn, only_website_id)
            if row is None:
                log.warning("crawl: website id %s not found", only_website_id)
                source_iter = iter(())
            else:
                source_iter = iter((row,))
        else:
            source_iter = iter_enabled_website_sources(website_conn)
    else:
        source_iter = ((None, sk, sc, {}) for sk, sc in iter_source_configs(cfg))

    for website_id, source_id, sc, prefs in source_iter:
        if not want(source_id):
            continue
        if not sc.get("enabled", True):
            continue
        st = str(sc.get("type") or "").strip()
        handler = SOURCE_HANDLERS.get(st)
        if handler is None:
            log.warning("unknown source type %r for %s", st, source_id)
            continue
        probe = source_robots_probe_url(st, sc)
        if not probe:
            log.warning("%s: missing URL for robots probe (type=%s)", source_id, st)
            continue
        use_db_site = website_id is not None
        merged_cfg = merge_site_preferences_into_cfg(cfg, prefs) if use_db_site else cfg
        http_m = merged_cfg.get("http") or {}
        ua = str(http_m.get("user_agent") or default_ua).strip() or default_ua
        delay_s = float(http_m.get("delay_seconds") or 0.75)
        timeout_s = float(http_m.get("timeout_seconds") or 45.0)
        if use_db_site:
            work_client = ThrottledClient(
                user_agent=ua, delay_s=delay_s, timeout_s=timeout_s
            )
            own_client = True
        else:
            work_client = client
            own_client = False
        try:
            if not _robots_ok(work_client, ua, probe):
                continue
            label = resolve_event_source_label(source_id, sc)
            batch = handler(work_client, sc, log, label, today_local)
            if website_id is not None:
                for ev in batch:
                    ev.website_id = website_id
            batch = enrich_discovered_events(
                work_client,
                batch,
                user_agent=ua,
                log=log,
                cfg=merged_cfg,
            )
            all_events.extend(batch)
        finally:
            if own_client:
                work_client.close()

    return dedupe_events(all_events)


def score_all(
    events: list[DiscoveredEvent],
    cfg: dict[str, Any],
    today_local: date,
    *,
    website_conn: sqlite3.Connection | None = None,
) -> list[DiscoveredEvent]:
    prefs_map = (
        load_all_website_preferences(website_conn)
        if website_conn is not None
        else {}
    )
    for ev in events:
        eff_cfg = cfg
        wid = ev.website_id
        if wid is not None:
            wp = prefs_map.get(int(wid))
            if wp:
                eff_cfg = merge_site_preferences_into_cfg(cfg, wp)
        sc = load_scoring_config(eff_cfg)
        score_event(
            ev,
            positive_keywords=sc["positive_keywords"],
            negative_keywords=sc["negative_keywords"],
            ward_keywords=sc["ward_keywords"],
            horizon_days=sc["horizon_days"],
            today=today_local,
        )
    return sorted(events, key=lambda e: (-e.relevance_score, e.title.lower()))


def migrate_database_only(
    *,
    config_path: str | None,
    output_dir: Path,
    database_path: Path | None = None,
) -> Path:
    """Apply pending SQL migrations; create empty DB if missing."""
    override = config_path or os.environ.get("EVENT_DISCOVERY_CONFIG")
    cfg = load_config(override if override else None)
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = database_path or resolve_db_path(cfg, output_dir)
    apply_migrations(db_path)
    conn = open_connection(db_path)
    try:
        ensure_discovery_seeded(conn, cfg)
    finally:
        conn.close()
    log.info("Migrations applied: %s", db_path)
    return db_path


def maybe_webhook(webhook_url: str | None, summary: dict[str, Any]) -> None:
    if not webhook_url:
        return
    try:
        import httpx

        r = httpx.post(webhook_url, json=summary, timeout=30.0)
        r.raise_for_status()
        log.info("webhook POST ok: %s", webhook_url[:48])
    except OSError as e:
        log.warning("webhook failed: %s", e)
    except Exception as e:
        # Do not fail the crawl after persistence; log non-OSError httpx failures too.
        log.warning("webhook failed: %s", e)


def run(
    *,
    config_path: str | None,
    output_dir: Path,
    source_filter: set[str] | None,
    dry_run: bool,
    database_path: Path | None = None,
    only_website_id: int | None = None,
) -> list[DiscoveredEvent]:
    override = config_path or os.environ.get("EVENT_DISCOVERY_CONFIG")
    cfg = load_config(override if override else None)

    http_cfg = cfg.get("http") or {}
    user_agent = str(http_cfg.get("user_agent") or "")
    delay = float(http_cfg.get("delay_seconds") or 0.75)
    timeout = float(http_cfg.get("timeout_seconds") or 45.0)

    tz = ZoneInfo("America/Toronto")
    today_local = datetime.now(tz).date()

    db_path = database_path or resolve_db_path(cfg, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    website_conn: sqlite3.Connection | None = None
    if dry_run and not db_path.is_file():
        log.info(
            "dry-run: no database at %s yet; using YAML sources only (no SQLite file created)",
            db_path,
        )
    else:
        apply_migrations(db_path)
        website_conn = open_connection(db_path)
        ensure_discovery_seeded(website_conn, cfg)
        cfg = merge_config_with_db(cfg, website_conn)
        http_cfg = cfg.get("http") or {}
        user_agent = str(http_cfg.get("user_agent") or "")
        delay = float(http_cfg.get("delay_seconds") or 0.75)
        timeout = float(http_cfg.get("timeout_seconds") or 45.0)

    client = ThrottledClient(user_agent=user_agent, delay_s=delay, timeout_s=timeout)
    try:
        events = collect_events(
            cfg,
            client,
            source_filter=source_filter,
            today_local=today_local,
            website_conn=website_conn,
            only_website_id=only_website_id,
        )
        events = score_all(events, cfg, today_local, website_conn=website_conn)
        if dry_run:
            log.info(
                "dry-run: skipping SQLite write; would persist %d events to %s",
                len(events),
                db_path,
            )
        else:
            assert website_conn is not None
            persist_discovery(website_conn, events)
            maybe_webhook(
                os.environ.get("WEBHOOK_URL"),
                {
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "event_count": len(events),
                    "top_titles": [e.title for e in events[:8]],
                },
            )
        return events
    finally:
        client.close()
        if website_conn is not None:
            website_conn.close()
