from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import bcrypt

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
AUTH_MIGRATIONS_DIR = PACKAGE_DIR / "auth_migrations"


def apply_auth_migrations(auth_db_path: Path) -> None:
    auth_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(auth_db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS _auth_sql_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
        applied = {row[0] for row in cur.execute("SELECT name FROM _auth_sql_migrations")}
        for sql_path in sorted(AUTH_MIGRATIONS_DIR.glob("*.sql")):
            name = sql_path.name
            if name in applied:
                continue
            log.info("Applying auth SQL migration %s", name)
            script = sql_path.read_text(encoding="utf-8")
            conn.executescript(script)
            cur.execute("INSERT INTO _auth_sql_migrations (name) VALUES (?)", (name,))
            conn.commit()
    finally:
        conn.close()


def open_auth_connection(auth_db_path: Path) -> sqlite3.Connection:
    auth_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(auth_db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_account(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.cursor()
    cur.execute("INSERT INTO accounts (name) VALUES (?)", (name.strip(),))
    conn.commit()
    return int(cur.lastrowid)


def create_account_with_user(
    conn: sqlite3.Connection,
    *,
    account_name: str,
    email: str,
    password: str,
) -> tuple[int, int]:
    """
    Create a new account and its first user in one transaction.
    Returns (account_id, user_id). Rolls back and raises IntegrityError on duplicate email.
    """
    name = account_name.strip()
    if not name:
        raise ValueError("account name is required")
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("email is required")
    if not password:
        raise ValueError("password is required")
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")
    try:
        cur.execute("INSERT INTO accounts (name) VALUES (?)", (name,))
        account_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO users (account_id, email, password_hash)
            VALUES (?, ?, ?)
            """,
            (account_id, normalized, pw_hash),
        )
        user_id = int(cur.lastrowid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return account_id, user_id


def create_user(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    email: str,
    password: str,
) -> int:
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("email is required")
    if not password:
        raise ValueError("password is required")
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (account_id, email, password_hash)
        VALUES (?, ?, ?)
        """,
        (int(account_id), normalized, pw_hash),
    )
    conn.commit()
    return int(cur.lastrowid)


def verify_user_password(conn: sqlite3.Connection, email: str, password: str) -> dict[str, Any] | None:
    normalized = email.strip().lower()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, account_id, email, password_hash
        FROM users WHERE email = ?
        """,
        (normalized,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    stored = str(row["password_hash"])
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), stored.encode("ascii"))
    except ValueError:
        return None
    if not ok:
        return None
    return {
        "id": int(row["id"]),
        "account_id": int(row["account_id"]),
        "email": str(row["email"]),
    }


def fetch_user_by_id(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, account_id, email FROM users WHERE id = ?",
        (int(user_id),),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "account_id": int(row["account_id"]),
        "email": str(row["email"]),
    }
