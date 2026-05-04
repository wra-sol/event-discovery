from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = PACKAGE_DIR / "migrations"


def apply_migrations(db_path: Path) -> None:
    """
    Apply ordered *.sql files in migrations/ once each, tracked in _sql_migrations.
    Creates parent directories and an empty DB file if needed.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS _sql_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
        applied = {row[0] for row in cur.execute("SELECT name FROM _sql_migrations")}
        for sql_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            name = sql_path.name
            if name in applied:
                continue
            log.info("Applying SQL migration %s", name)
            script = sql_path.read_text(encoding="utf-8")
            conn.executescript(script)
            cur.execute("INSERT INTO _sql_migrations (name) VALUES (?)", (name,))
            conn.commit()
    finally:
        conn.close()
