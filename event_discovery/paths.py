from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def resolve_data_root() -> Path:
    """
    Root directory for auth.db, per-account folders, and legacy flat discovery.db.
    Uses RAILWAY_VOLUME_MOUNT_PATH, then OUTPUT_DIR, then ./discovered-events under cwd.
    """
    railway = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if railway:
        return Path(railway)
    env_out = os.environ.get("OUTPUT_DIR")
    if env_out:
        return Path(env_out)
    return Path.cwd() / "discovered-events"


def auth_db_path(data_root: Path | None = None) -> Path:
    root = data_root or resolve_data_root()
    return root / "auth.db"


def database_filename(cfg: dict[str, Any] | None) -> str:
    if not cfg:
        return "discovery.db"
    db_cfg = cfg.get("database") or {}
    return str(db_cfg.get("filename") or "discovery.db")


def account_discovery_db_path(
    data_root: Path,
    account_id: int,
    *,
    cfg: dict[str, Any] | None = None,
) -> Path:
    name = database_filename(cfg)
    return data_root / "accounts" / str(int(account_id)) / name


def maybe_migrate_legacy_flat_discovery_db(
    data_root: Path,
    cfg: dict[str, Any],
) -> None:
    """
    If a legacy flat discovery.db exists at data root and account 1 has no DB yet,
    move it to accounts/1/<filename>. Skips when DISCOVERY_DB_PATH is set (explicit layout).
    """
    if os.environ.get("DISCOVERY_DB_PATH"):
        return
    name = database_filename(cfg)
    legacy = data_root / name
    dest_dir = data_root / "accounts" / "1"
    dest = dest_dir / name
    if not legacy.is_file():
        return
    if dest.is_file():
        log.warning(
            "Legacy DB %s and %s both exist; leaving legacy in place. "
            "Set DISCOVERY_DB_PATH or remove the duplicate.",
            legacy,
            dest,
        )
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy), str(dest))
    log.info("Migrated legacy discovery DB to %s", dest)
