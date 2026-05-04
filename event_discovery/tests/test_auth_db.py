from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import sqlite3

from event_discovery.auth_db import (
    apply_auth_migrations,
    create_account,
    create_account_with_user,
    create_user,
    fetch_user_by_id,
    open_auth_connection,
    verify_user_password,
)


class TestAuthDb(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp())
        self._auth = self._dir / "auth.db"

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_create_user_and_login(self) -> None:
        apply_auth_migrations(self._auth)
        conn = open_auth_connection(self._auth)
        try:
            aid = create_account(conn, "Acme")
            create_user(conn, account_id=aid, email="Pat@Example.com", password="secret-pass")
        finally:
            conn.close()
        conn = open_auth_connection(self._auth)
        try:
            u = verify_user_password(conn, "pat@example.com", "secret-pass")
            self.assertIsNotNone(u)
            assert u is not None
            self.assertEqual(u["account_id"], aid)
            row = fetch_user_by_id(conn, u["id"])
            self.assertEqual(row["email"], "pat@example.com")
            self.assertIsNone(verify_user_password(conn, "pat@example.com", "wrong"))
        finally:
            conn.close()

    def test_create_account_with_user_rolls_back_on_duplicate_email(self) -> None:
        apply_auth_migrations(self._auth)
        conn = open_auth_connection(self._auth)
        try:
            aid, uid = create_account_with_user(
                conn,
                account_name="First",
                email="same@example.com",
                password="secret-pass",
            )
            self.assertGreater(aid, 0)
            self.assertGreater(uid, 0)
        finally:
            conn.close()
        conn = open_auth_connection(self._auth)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                create_account_with_user(
                    conn,
                    account_name="Second",
                    email="same@example.com",
                    password="other-pass",
                )
            cur = conn.execute("SELECT COUNT(*) FROM accounts")
            self.assertEqual(int(cur.fetchone()[0]), 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
