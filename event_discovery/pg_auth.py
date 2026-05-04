"""PostgreSQL-backed auth when DATABASE_URL is set."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import bcrypt

log = logging.getLogger(__name__)

PG_AUTH_MIGRATIONS_DIR = Path(__file__).resolve().parent / "pg_auth_migrations"


def create_account(conn: Any, name: str) -> int:
    cur = conn.cursor()
    cur.execute("INSERT INTO accounts (name) VALUES (%s) RETURNING id", (name.strip(),))
    rid = int(cur.fetchone()["id"])
    conn.commit()
    return rid


def apply_auth_migrations_pg(dsn: str) -> None:
    """Apply versioned SQL in pg_auth_migrations/ once each (tracked in _pg_auth_migrations)."""
    import psycopg

    meta_sql = """
    CREATE TABLE IF NOT EXISTS _pg_auth_migrations (
        name TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    with psycopg.connect(dsn) as conn:
        conn.execute(meta_sql)
        conn.commit()
        rows = conn.execute("SELECT name FROM _pg_auth_migrations").fetchall()
        applied = {str(r[0]) for r in rows}

        for path in sorted(PG_AUTH_MIGRATIONS_DIR.glob("*.sql")):
            name = path.name
            if name in applied:
                continue
            log.info("Applying Postgres auth migration %s", name)
            script = path.read_text(encoding="utf-8").strip()
            with conn.transaction():
                conn.execute(script)
                conn.execute(
                    "INSERT INTO _pg_auth_migrations (name) VALUES (%s)",
                    (name,),
                )
            applied.add(name)

    log.info("Postgres auth migrations applied (ledger in _pg_auth_migrations)")


@contextmanager
def connect(dsn: str) -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(dsn, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def create_account_with_user(
    conn: Any,
    *,
    account_name: str,
    email: str,
    password: str,
) -> tuple[int, int]:
    name = account_name.strip()
    if not name:
        raise ValueError("account name is required")
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("email is required")
    if not password:
        raise ValueError("password is required")
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("INSERT INTO accounts (name) VALUES (%s) RETURNING id", (name,))
        account_id = int(cur.fetchone()["id"])
        cur.execute(
            """
            INSERT INTO users (account_id, email, password_hash)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (account_id, normalized, pw_hash),
        )
        user_id = int(cur.fetchone()["id"])
    return account_id, user_id


def create_user(
    conn: Any,
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
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (int(account_id), normalized, pw_hash),
    )
    uid = int(cur.fetchone()["id"])
    conn.commit()
    return uid


def verify_user_password(conn: Any, email: str, password: str) -> dict[str, Any] | None:
    normalized = email.strip().lower()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, account_id, email, password_hash
        FROM users WHERE lower(email) = %s
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


def fetch_user_by_id(conn: Any, user_id: int) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, account_id, email FROM users WHERE id = %s",
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
