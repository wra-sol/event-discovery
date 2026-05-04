from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from event_discovery.repository import insert_crawl_job, open_connection
from event_discovery.schema_migrations import apply_migrations


class TestCrawlJobsWebsiteIntegrity(unittest.TestCase):
    def test_insert_rejects_unknown_website_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    insert_crawl_job(conn, kind="recheck", website_id=99999)
            finally:
                conn.close()

    def test_insert_allows_full_with_null_website(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                jid = insert_crawl_job(conn, kind="full", website_id=None)
                self.assertGreater(jid, 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
