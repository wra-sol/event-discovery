from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from event_discovery.models import DiscoveredEvent
from event_discovery.repository import compact_series_duplicates, open_connection, persist_discovery
from event_discovery.schema_migrations import apply_migrations


class TestMigrationsAndRepository(unittest.TestCase):
    def test_migrations_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute("SELECT name FROM _sql_migrations ORDER BY name")
                names = [r[0] for r in cur.fetchall()]
                self.assertEqual(
                    names,
                    [
                        "001_initial.sql",
                        "002_review_columns.sql",
                        "003_websites.sql",
                        "004_discovery_settings.sql",
                        "005_event_rejected.sql",
                        "006_website_preferences.sql",
                        "007_crawl_jobs.sql",
                        "008_crawl_jobs_website_integrity.sql",
                    ],
                )
            finally:
                conn.close()

    def test_persist_sets_website_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO websites (source_key, enabled, type, config_json)
                    VALUES ('w', 1, 'tribe_rest', '{"rest_url": "https://x.test/e"}')
                    """
                )
                wid = cur.lastrowid
                conn.commit()
                ev = [
                    DiscoveredEvent(
                        title="A",
                        url="https://example.com/e/1",
                        source="w",
                        website_id=int(wid),
                        start="2026-06-01",
                        relevance_score=1.0,
                    )
                ]
                persist_discovery(conn, ev)
                cur.execute("SELECT website_id FROM discovered_events WHERE dedupe_key = ?", (ev[0].dedupe_key(),))
                self.assertEqual(cur.fetchone()[0], int(wid))
            finally:
                conn.close()

    def test_upsert_preserves_start_end_venue_when_incoming_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            dk = "https://example.com/e/1|town hall"
            ev_full = [
                DiscoveredEvent(
                    title="Town Hall",
                    url="https://example.com/e/1",
                    source="test",
                    start="2026-06-01T18:00:00",
                    end="2026-06-01T20:00:00",
                    venue="Main St",
                    relevance_score=1.0,
                )
            ]
            conn = open_connection(db)
            try:
                persist_discovery(conn, ev_full)
                ev_sparse = [
                    DiscoveredEvent(
                        title="Town Hall",
                        url="https://example.com/e/1",
                        source="test",
                        start=None,
                        end="",
                        venue=None,
                        relevance_score=2.0,
                    )
                ]
                persist_discovery(conn, ev_sparse)
                cur = conn.cursor()
                cur.execute(
                    "SELECT start_at, end_at, venue, relevance_score FROM discovered_events WHERE dedupe_key = ?",
                    (dk,),
                )
                row = cur.fetchone()
                self.assertEqual(row[0], "2026-06-01T18:00:00")
                self.assertEqual(row[1], "2026-06-01T20:00:00")
                self.assertEqual(row[2], "Main St")
                self.assertEqual(row[3], 2.0)
            finally:
                conn.close()

    def test_upsert_overwrites_start_when_incoming_has_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            dk = "https://example.com/e/2|gig"
            conn = open_connection(db)
            try:
                persist_discovery(
                    conn,
                    [
                        DiscoveredEvent(
                            title="Gig",
                            url="https://example.com/e/2",
                            source="test",
                            start="2026-06-01",
                            relevance_score=1.0,
                        )
                    ],
                )
                persist_discovery(
                    conn,
                    [
                        DiscoveredEvent(
                            title="Gig",
                            url="https://example.com/e/2",
                            source="test",
                            start="2026-07-15",
                            relevance_score=1.0,
                        )
                    ],
                )
                cur = conn.cursor()
                cur.execute("SELECT start_at FROM discovered_events WHERE dedupe_key = ?", (dk,))
                self.assertEqual(cur.fetchone()[0], "2026-07-15")
            finally:
                conn.close()

    def test_upsert_preserves_first_seen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            ev = [
                DiscoveredEvent(
                    title="Town Hall",
                    url="https://example.com/e/1",
                    source="test",
                    start="2026-06-01",
                    relevance_score=1.0,
                    relevance_reasons=["keyword:x"],
                )
            ]
            conn = open_connection(db)
            try:
                persist_discovery(conn, ev)
                cur = conn.cursor()
                cur.execute("SELECT first_seen_at FROM discovered_events WHERE dedupe_key = ?", (ev[0].dedupe_key(),))
                first = cur.fetchone()[0]
                ev[0].relevance_score = 5.0
                persist_discovery(conn, ev)
                cur.execute("SELECT first_seen_at, last_seen_at, relevance_score FROM discovered_events WHERE dedupe_key = ?", (ev[0].dedupe_key(),))
                row = cur.fetchone()
                self.assertEqual(row[0], first)
                self.assertLessEqual(row[0], row[1])
                self.assertEqual(row[2], 5.0)
            finally:
                conn.close()

    def test_compact_merges_tribe_style_duplicate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO discovery_runs (started_at, finished_at, event_count) VALUES (?,?,?)",
                    ("2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z", 2),
                )
                run_id = cur.lastrowid
                row_common = (
                    "Show Title",
                    "src",
                    "snippet",
                    1.0,
                    "[]",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                    0,
                    "",
                    run_id,
                )
                cur.execute(
                    """
                    INSERT INTO discovered_events (
                        dedupe_key, title, url, source, start_at, end_at, venue, raw_snippet,
                        relevance_score, relevance_reasons_json, first_seen_at, last_seen_at,
                        reviewed, notes, last_run_id
                    ) VALUES (?,?,?,?,?,NULL,NULL,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "old-key-1|show title|2026-04-01",
                        row_common[0],
                        "https://ex.test/event/show-title-10/",
                        row_common[1],
                        "2026-04-01",
                        row_common[2],
                        row_common[3],
                        row_common[4],
                        row_common[5],
                        row_common[6],
                        row_common[7],
                        row_common[8],
                        row_common[9],
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO discovered_events (
                        dedupe_key, title, url, source, start_at, end_at, venue, raw_snippet,
                        relevance_score, relevance_reasons_json, first_seen_at, last_seen_at,
                        reviewed, notes, last_run_id
                    ) VALUES (?,?,?,?,?,NULL,NULL,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "old-key-2|show title|2026-04-02",
                        row_common[0],
                        "https://ex.test/event/show-title-11/",
                        row_common[1],
                        "2026-04-02",
                        row_common[2],
                        row_common[3],
                        row_common[4],
                        row_common[5],
                        row_common[6],
                        row_common[7],
                        row_common[8],
                        row_common[9],
                    ),
                )
                conn.commit()
                removed, _ = compact_series_duplicates(conn)
                self.assertEqual(removed, 1)
                cur.execute("SELECT COUNT(*) FROM discovered_events")
                self.assertEqual(cur.fetchone()[0], 1)
                cur.execute("SELECT start_at, reviewed FROM discovered_events LIMIT 1")
                start_at, reviewed = cur.fetchone()
                self.assertEqual(start_at, "2026-04-01")
                self.assertEqual(reviewed, 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
