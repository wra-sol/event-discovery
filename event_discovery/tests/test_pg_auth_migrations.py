from __future__ import annotations

import os
import unittest

from event_discovery import pg_auth


class TestPgAuthMigrations(unittest.TestCase):
    def test_migration_files_exist(self) -> None:
        d = pg_auth.PG_AUTH_MIGRATIONS_DIR
        self.assertTrue(d.is_dir(), f"missing {d}")
        names = sorted(p.name for p in d.glob("*.sql"))
        self.assertEqual(
            names,
            [
                "001_accounts.sql",
                "002_users.sql",
                "003_idx_users_account.sql",
            ],
        )

    @unittest.skipUnless(
        os.environ.get("PYTEST_PG_DSN"),
        "Set PYTEST_PG_DSN to run Postgres auth migration smoke test",
    )
    def test_apply_auth_migrations_pg_idempotent(self) -> None:
        dsn = os.environ["PYTEST_PG_DSN"]
        pg_auth.apply_auth_migrations_pg(dsn)
        pg_auth.apply_auth_migrations_pg(dsn)


if __name__ == "__main__":
    unittest.main()
