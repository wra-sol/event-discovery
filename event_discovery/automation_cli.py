from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .automation_run import emit_brief, run_local_daily_automation
from .pipeline import load_config, migrate_database_only
from .repository import open_connection

log = logging.getLogger(__name__)
DEFAULT_DATA_SUBDIR = "discovered-events"


def add_account_id_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--account-id",
        type=int,
        default=None,
        metavar="ID",
        help="Use accounts/<ID>/discovery.db under output-dir (or set DISCOVERY_ACCOUNT_ID).",
    )


def resolve_database_path_for_cli(
    data_dir: Path,
    cfg: dict,
    *,
    explicit_db: Path | None,
    account_id: int | None,
) -> Path | None:
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
        from .paths import account_discovery_db_path

        return account_discovery_db_path(data_dir, acc, cfg=cfg)
    return None


def default_data_dir() -> Path:
    from .paths import resolve_data_root

    return resolve_data_root()


def _prepare_cli_db(
    *,
    config_path: str | None,
    output_dir: Path,
    explicit_db: Path | None,
    account_id: int | None,
) -> Path:
    override = config_path or os.environ.get("EVENT_DISCOVERY_CONFIG")
    cfg = load_config(override if override else None)
    db_path = resolve_database_path_for_cli(
        output_dir, cfg, explicit_db=explicit_db, account_id=account_id
    )
    if db_path is None:
        return migrate_database_only(
            config_path=config_path,
            output_dir=output_dir,
            database_path=None,
        )
    migrate_database_only(
        config_path=config_path,
        output_dir=output_dir,
        database_path=db_path,
    )
    return db_path


def main_daily_brief(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Print the daily triage brief from the account discovery database (no crawl).",
    )
    parser.add_argument(
        "--config",
        help="Path to YAML config overlay (or set EVENT_DISCOVERY_CONFIG).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Data directory (default: OUTPUT_DIR or ./{DEFAULT_DATA_SUBDIR}).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite path (overrides DISCOVERY_DB_PATH).",
    )
    add_account_id_arg(parser)
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    from .automation_run import build_daily_brief_response

    data_dir = args.output_dir or default_data_dir()
    override = args.config or os.environ.get("EVENT_DISCOVERY_CONFIG")
    db_path = _prepare_cli_db(
        config_path=args.config,
        output_dir=data_dir,
        explicit_db=args.db,
        account_id=args.account_id,
    )

    conn = open_connection(db_path)
    try:
        brief = build_daily_brief_response(conn, config_path=override)
    finally:
        conn.close()

    sys.stdout.write(emit_brief(brief, fmt=args.format))
    return 0


def main_automation_run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run daily automation: full crawl then daily brief (local DB or remote API).",
    )
    parser.add_argument(
        "--config",
        help="Path to YAML config overlay (or set EVENT_DISCOVERY_CONFIG).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Data directory for local mode (default: OUTPUT_DIR or ./{DEFAULT_DATA_SUBDIR}).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite path for local mode.",
    )
    add_account_id_arg(parser)
    parser.add_argument(
        "--remote",
        metavar="BASE_URL",
        help="Call deployed API instead of local crawl (requires EVENTS_CRAWL_API_TOKEN).",
    )
    parser.add_argument(
        "--skip-crawl",
        action="store_true",
        help="Local mode only: build brief from existing DB without crawling.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=5.0,
        help="Remote mode: seconds between crawl job polls.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=900.0,
        help="Remote mode: max seconds to wait for crawl completion.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.remote:
        token = os.environ.get("EVENTS_CRAWL_API_TOKEN", "").strip()
        if not token:
            log.error("Remote mode requires EVENTS_CRAWL_API_TOKEN")
            return 2
        account_id = args.account_id
        if account_id is None:
            env_acc = os.environ.get("DISCOVERY_ACCOUNT_ID") or os.environ.get(
                "EVENT_DISCOVERY_ACCOUNT_ID"
            )
            if env_acc and env_acc.isdigit():
                account_id = int(env_acc)
        if account_id is None:
            log.error("Remote mode requires --account-id or DISCOVERY_ACCOUNT_ID")
            return 2
        from .automation_client import AutomationClientError, run_remote_daily_automation

        try:
            brief = run_remote_daily_automation(
                args.remote.rstrip("/"),
                token=token,
                account_id=account_id,
                poll_seconds=args.poll_seconds,
                timeout_seconds=args.timeout_seconds,
            )
        except AutomationClientError as e:
            log.error("%s", e)
            return 1
        sys.stdout.write(emit_brief(brief, fmt=args.format))
        return 0

    data_dir = args.output_dir or default_data_dir()
    override = args.config or os.environ.get("EVENT_DISCOVERY_CONFIG")
    db_path = _prepare_cli_db(
        config_path=args.config,
        output_dir=data_dir,
        explicit_db=args.db,
        account_id=args.account_id,
    )
    try:
        brief = run_local_daily_automation(
            config_path=override,
            output_dir=data_dir,
            database_path=db_path,
            skip_crawl=args.skip_crawl,
        )
    except Exception as e:
        log.error("automation-run failed: %s", e)
        if args.verbose:
            log.exception("detail")
        return 1
    sys.stdout.write(emit_brief(brief, fmt=args.format))
    return 0
