from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

from .auth_db import (
    apply_auth_migrations,
    create_account,
    create_user,
    open_auth_connection,
)
from .paths import account_discovery_db_path, auth_db_path, resolve_data_root
from .pipeline import load_config, migrate_database_only, run
from .repository import (
    export_markdown,
    open_connection,
    sync_settings_from_config,
    sync_websites_from_config,
)

DEFAULT_DATA_SUBDIR = "discovered-events"

log = logging.getLogger(__name__)


def _add_account_id_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--account-id",
        type=int,
        default=None,
        metavar="ID",
        help="Use accounts/<ID>/discovery.db under output-dir (or set DISCOVERY_ACCOUNT_ID).",
    )


def _resolve_database_path_for_cli(
    data_dir: Path,
    cfg: dict,
    *,
    explicit_db: Path | None,
    account_id: int | None,
) -> Path | None:
    """
    Return explicit SQLite path for migrate/run, or None to use pipeline.resolve_db_path defaults.
    """
    if explicit_db is not None:
        return explicit_db
    env_db = os.environ.get("DISCOVERY_DB_PATH")
    if env_db:
        return Path(env_db)
    acc = account_id
    if acc is None:
        env_acc = os.environ.get("DISCOVERY_ACCOUNT_ID")
        if env_acc:
            acc = int(env_acc)
    if acc is not None:
        return account_discovery_db_path(data_dir, acc, cfg=cfg)
    return None


def _default_data_dir() -> Path:
    """Same layout as the web UI: RAILWAY_VOLUME_MOUNT_PATH, OUTPUT_DIR, or ./discovered-events."""
    return resolve_data_root()


def _main_discover_source(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch a URL and use an LLM to suggest a sources: YAML block (onboarding only; not used during daily crawl)."
    )
    parser.add_argument("--url", required=True, help="Events or calendar page to analyze.")
    parser.add_argument(
        "--source-key",
        default="new_source",
        metavar="KEY",
        help="YAML key name for the printed suggestion (default: new_source).",
    )
    parser.add_argument(
        "--prompt-only",
        action="store_true",
        help="Fetch the page and print the LLM prompt only; no API call (no key required).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.DEBUG if args.verbose else logging.WARNING)

    from .llm_source_discovery import format_yaml_suggestion, run_discover_source

    try:
        out = run_discover_source(args.url, prompt_only=args.prompt_only)
    except OSError as e:
        log.error("fetch failed: %s", e)
        return 1
    except RuntimeError as e:
        log.error("%s", e)
        return 1
    except Exception as e:
        log.error("discover-source failed: %s", e)
        if args.verbose:
            log.exception("detail")
        return 1

    if args.prompt_only:
        print(out["prompt"])
        return 0

    result = out["result"]
    print(json.dumps(result, indent=2))
    print("\n# Suggested YAML (paste under sources: in your config overlay):\n")
    print(format_yaml_suggestion(args.source_key, result))
    return 0


def _main_sync_websites(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Upsert discovery_settings (http, scoring) and websites from merged YAML. "
        "Runs use the database as the source of truth after the first migrate/run."
    )
    parser.add_argument(
        "--config",
        help="Path to YAML config overlay (or set EVENT_DISCOVERY_CONFIG).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Data directory for discovery.db (default: OUTPUT_DIR or ./{DEFAULT_DATA_SUBDIR}).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite path (overrides DISCOVERY_DB_PATH).",
    )
    _add_account_id_arg(parser)
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    data_dir = args.output_dir or _default_data_dir()
    override = args.config or os.environ.get("EVENT_DISCOVERY_CONFIG")
    cfg = load_config(override if override else None)
    db_explicit = _resolve_database_path_for_cli(
        data_dir, cfg, explicit_db=args.db, account_id=args.account_id
    )
    db_path = migrate_database_only(
        config_path=args.config,
        output_dir=data_dir,
        database_path=db_explicit,
    )
    conn = open_connection(db_path)
    try:
        sync_settings_from_config(conn, cfg)
        n = sync_websites_from_config(conn, cfg)
    finally:
        conn.close()
    log.info("Synced settings and %d website row(s) into %s", n, db_path)
    return 0


def _main_run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Discover public Burlington-area events for campaign triage (review-only).",
        epilog="Other commands: discover-source, sync-websites, create-account, create-user, "
        "daily-brief, automation-run, cron-run (see --help on each).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        help="Path to YAML config overlay (or set EVENT_DISCOVERY_CONFIG).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Data directory for discovery.db when path is relative (default: OUTPUT_DIR or ./{DEFAULT_DATA_SUBDIR}).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite database path (overrides DISCOVERY_DB_PATH and database.filename under output-dir).",
    )
    _add_account_id_arg(parser)
    parser.add_argument(
        "--migrate-only",
        action="store_true",
        help="Apply SQL migrations and exit (no crawl).",
    )
    parser.add_argument(
        "--export-markdown",
        metavar="PATH",
        help="Export current DB to a markdown table (use '-' for stdout), then exit (no crawl).",
    )
    parser.add_argument(
        "--sources",
        help="Comma-separated source keys (YAML keys, or websites.source_key when DB drives sources).",
    )
    parser.add_argument(
        "--website-id",
        type=int,
        default=None,
        metavar="ID",
        help="Crawl only this websites.id row (SQLite must contain the site; ignores enabled toggle).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and score only; no persist/webhook. Uses websites table if DB already exists.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    data_dir = args.output_dir or _default_data_dir()
    override = args.config or os.environ.get("EVENT_DISCOVERY_CONFIG")
    cfg = load_config(override if override else None)
    db_explicit = _resolve_database_path_for_cli(
        data_dir, cfg, explicit_db=args.db, account_id=args.account_id
    )

    if args.migrate_only:
        migrate_database_only(
            config_path=args.config,
            output_dir=data_dir,
            database_path=db_explicit,
        )
        return 0

    if args.export_markdown:
        db_path = migrate_database_only(
            config_path=args.config,
            output_dir=data_dir,
            database_path=db_explicit,
        )
        export_markdown(db_path, args.export_markdown)
        return 0

    source_filter: set[str] | None = None
    if args.sources:
        source_filter = {s.strip() for s in args.sources.split(",") if s.strip()}
    if args.website_id is not None and source_filter is not None:
        log.error("Use either --website-id or --sources, not both")
        return 2

    run(
        config_path=args.config,
        output_dir=data_dir,
        source_filter=source_filter,
        dry_run=args.dry_run,
        database_path=db_explicit,
        only_website_id=args.website_id,
    )
    return 0


def _main_create_account(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Create a tenant account (per-account discovery database directory).",
    )
    parser.add_argument("--name", required=True, help="Display name for the account.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help=f"Data root (auth.db + accounts/). Default: OUTPUT_DIR or ./{DEFAULT_DATA_SUBDIR}.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    data_root = args.data_dir or _default_data_dir()
    from .settings_env import database_url

    dsn = database_url()
    if dsn:
        from . import pg_auth

        pg_auth.apply_auth_migrations_pg(dsn)
        with pg_auth.connect(dsn) as conn:
            aid = pg_auth.create_account(conn, args.name)
        print(aid)
        return 0
    a_path = auth_db_path(data_root)
    apply_auth_migrations(a_path)
    conn = open_auth_connection(a_path)
    try:
        aid = create_account(conn, args.name)
    finally:
        conn.close()
    print(aid)
    return 0


def _main_create_user(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Create a login user linked to an account (use create-account first).",
    )
    parser.add_argument("--account-id", type=int, required=True, dest="account_id")
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--password",
        help="If omitted, password is read securely (not echoed).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help=f"Data root where auth.db lives. Default: OUTPUT_DIR or ./{DEFAULT_DATA_SUBDIR}.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    pw = args.password or getpass.getpass("Password: ")
    data_root = args.data_dir or _default_data_dir()
    from .settings_env import database_url

    dsn = database_url()
    if dsn:
        from . import pg_auth

        pg_auth.apply_auth_migrations_pg(dsn)
        try:
            with pg_auth.connect(dsn) as conn:
                pg_auth.create_user(
                    conn,
                    account_id=args.account_id,
                    email=args.email,
                    password=pw,
                )
        except Exception as e:
            from psycopg.errors import UniqueViolation

            if isinstance(e, UniqueViolation):
                log.error("A user with that email already exists.")
                return 1
            if isinstance(e, ValueError):
                log.error("%s", e)
                return 1
            raise
    else:
        a_path = auth_db_path(data_root)
        apply_auth_migrations(a_path)
        conn = open_auth_connection(a_path)
        try:
            create_user(conn, account_id=args.account_id, email=args.email, password=pw)
        except sqlite3.IntegrityError:
            log.error("A user with that email already exists.")
            return 1
        except ValueError as e:
            log.error("%s", e)
            return 1
        finally:
            conn.close()
    log.info("Created user %s for account %s", args.email.strip().lower(), args.account_id)
    return 0


def _main_daily_brief(argv: list[str]) -> int:
    from .automation_cli import main_daily_brief

    return main_daily_brief(argv)


def _main_automation_run(argv: list[str]) -> int:
    from .automation_cli import main_automation_run

    return main_automation_run(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "discover-source":
        return _main_discover_source(argv[1:])
    if argv and argv[0] == "sync-websites":
        return _main_sync_websites(argv[1:])
    if argv and argv[0] == "create-account":
        return _main_create_account(argv[1:])
    if argv and argv[0] == "create-user":
        return _main_create_user(argv[1:])
    if argv and argv[0] == "daily-brief":
        return _main_daily_brief(argv[1:])
    if argv and argv[0] == "automation-run":
        return _main_automation_run(argv[1:])
    if argv and argv[0] == "cron-run":
        from .cron_run import main as cron_main

        return cron_main(argv[1:])
    return _main_run(argv)
