from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from event_discovery.models import DiscoveredEvent
from event_discovery.repository import (
    EventListFilters,
    count_discovered_events,
    delete_website,
    list_discovered_events,
    list_websites,
    open_connection,
    patch_website,
    persist_discovery,
    reorder_websites,
    update_event_review,
    update_website_enabled,
)
from event_discovery.schema_migrations import apply_migrations


class TestRepositoryWebFeatures(unittest.TestCase):
    def test_list_websites_includes_last_event_activity_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO websites (source_key, enabled, type, config_json, display_order)
                    VALUES ('a', 1, 'tribe_rest', '{}', 0)
                    """
                )
                wid = int(cur.lastrowid)
                conn.commit()
                ev = [
                    DiscoveredEvent(
                        title="E1",
                        url="https://ex.test/1",
                        source="a",
                        website_id=wid,
                        start="2026-06-01",
                        relevance_score=1.0,
                    )
                ]
                persist_discovery(conn, ev)
                sites = list_websites(conn)
                self.assertEqual(len(sites), 1)
                self.assertIsNotNone(sites[0]["last_event_activity_at"])
                cur.execute(
                    "SELECT MAX(last_seen_at) FROM discovered_events WHERE website_id = ?",
                    (wid,),
                )
                expected = cur.fetchone()[0]
                self.assertEqual(sites[0]["last_event_activity_at"], expected)
            finally:
                conn.close()

    def test_update_website_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO websites (source_key, enabled, type, config_json)
                    VALUES ('x', 1, 'html', '{}')
                    """
                )
                wid = int(cur.lastrowid)
                conn.commit()
                self.assertTrue(update_website_enabled(conn, wid, False))
                cur.execute("SELECT enabled FROM websites WHERE id = ?", (wid,))
                self.assertEqual(cur.fetchone()[0], 0)
                self.assertFalse(update_website_enabled(conn, 99999, True))
            finally:
                conn.close()

    def test_patch_website_preferences_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO websites (source_key, enabled, type, config_json)
                    VALUES ('key', 1, 'tribe_rest', '{"rest_url":"https://ex.test/e"}')
                    """
                )
                wid = int(cur.lastrowid)
                conn.commit()
                self.assertTrue(
                    patch_website(
                        conn,
                        wid,
                        preferences={
                            "scoring": {"horizon_days": 45},
                            "enrichment": {"max_urls": 12},
                        },
                    )
                )
                sites = list_websites(conn)
                self.assertEqual(sites[0]["preferences"]["scoring"]["horizon_days"], 45)
                self.assertEqual(sites[0]["preferences"]["enrichment"]["max_urls"], 12)
                self.assertTrue(patch_website(conn, wid, preferences={}))
                sites2 = list_websites(conn)
                self.assertEqual(sites2[0]["preferences"], {})
            finally:
                conn.close()

    def test_patch_website_config_type_and_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO websites (source_key, enabled, type, config_json, source_label)
                    VALUES ('key', 1, 'html', '{"url":"https://old.example"}', 'Old label')
                    """
                )
                wid = int(cur.lastrowid)
                conn.commit()
                self.assertTrue(
                    patch_website(
                        conn,
                        wid,
                        config={"url": "https://new.example", "type": "should_strip"},
                        site_type="tribe_rest",
                        source_label="  New  ",
                    )
                )
                sites = list_websites(conn)
                self.assertEqual(len(sites), 1)
                self.assertEqual(sites[0]["type"], "tribe_rest")
                self.assertEqual(sites[0]["source_label"], "New")
                self.assertEqual(
                    sites[0]["config"],
                    {"url": "https://new.example"},
                )
                self.assertTrue(patch_website(conn, wid, source_label=""))
                sites = list_websites(conn)
                self.assertIsNone(sites[0]["source_label"])
                self.assertFalse(patch_website(conn, 99999, enabled=True))
            finally:
                conn.close()

    def test_patch_website_rejects_empty_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO websites (source_key, enabled, type, config_json)
                    VALUES ('k', 1, 'html', '{}')
                    """
                )
                wid = int(cur.lastrowid)
                conn.commit()
                with self.assertRaises(ValueError):
                    patch_website(conn, wid, site_type="   ")
            finally:
                conn.close()

    def test_reorder_websites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO websites (source_key, enabled, type, config_json, display_order)
                    VALUES ('first', 1, 'html', '{}', 0),
                           ('second', 1, 'html', '{}', 1)
                    """
                )
                conn.commit()
                cur.execute("SELECT id FROM websites ORDER BY display_order")
                id_low = int(cur.fetchone()[0])
                id_high = int(cur.fetchone()[0])
                reorder_websites(conn, [id_high, id_low])
                cur.execute("SELECT source_key FROM websites ORDER BY display_order")
                keys = [r[0] for r in cur.fetchall()]
                self.assertEqual(keys, ["second", "first"])
                with self.assertRaises(ValueError):
                    reorder_websites(conn, [id_low])
                with self.assertRaises(ValueError):
                    reorder_websites(conn, [id_low, id_high, id_high])
            finally:
                conn.close()

    def test_event_filters_date_website_sort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO websites (source_key, enabled, type, config_json) VALUES ('s',1,'html','{}')"
                )
                wid = int(cur.lastrowid)
                cur.execute(
                    """
                    INSERT INTO discovery_runs (started_at) VALUES ('2026-01-01T00:00:00Z')
                    """
                )
                run_id = int(cur.lastrowid)
                rows = [
                    (
                        "k1",
                        "A",
                        "https://a.test/1",
                        "s",
                        wid,
                        "2026-04-15",
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:00:00Z",
                        run_id,
                    ),
                    (
                        "k2",
                        "B",
                        "https://a.test/2",
                        "s",
                        wid,
                        "2026-04-02",
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:00:00Z",
                        run_id,
                    ),
                    (
                        "k3",
                        "C",
                        "https://a.test/3",
                        "other",
                        None,
                        "2026-05-01",
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:00:00Z",
                        run_id,
                    ),
                ]
                for r in rows:
                    cur.execute(
                        """
                        INSERT INTO discovered_events (
                            dedupe_key, title, url, source, website_id, start_at, end_at, venue,
                            raw_snippet, relevance_score, relevance_reasons_json,
                            first_seen_at, last_seen_at, reviewed, notes, last_run_id
                        ) VALUES (?,?,?,?,?,?,NULL,NULL,'',1.0,'[]',?,?,0,'',?)
                        """,
                        (*r[:6], r[6], r[7], r[8]),
                    )
                conn.commit()

                f = EventListFilters(website_id=wid)
                self.assertEqual(count_discovered_events(conn, f), 2)

                f2 = EventListFilters(start_from="2026-04-01", start_to="2026-04-30")
                self.assertEqual(count_discovered_events(conn, f2), 2)

                f3 = EventListFilters(start_from="2026-04-01", start_to="2026-04-30", sort="start_at")
                listed = list_discovered_events(conn, f3, limit=50, offset=0)
                titles = [x["title"] for x in listed]
                self.assertEqual(titles, ["B", "A"])

                fp = EventListFilters(include_past=False, as_of_date="2026-04-10")
                self.assertEqual(count_discovered_events(conn, fp), 2)
                titles_p = [x["title"] for x in list_discovered_events(conn, fp, limit=20, offset=0)]
                self.assertCountEqual(titles_p, ["A", "C"])
            finally:
                conn.close()

    def test_update_event_review_accept_reject_and_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute("INSERT INTO discovery_runs (started_at) VALUES ('2026-01-01T00:00:00Z')")
                run_id = int(cur.lastrowid)
                cur.execute(
                    """
                    INSERT INTO discovered_events (
                        dedupe_key, title, url, source, website_id, start_at, end_at, venue,
                        raw_snippet, relevance_score, relevance_reasons_json,
                        first_seen_at, last_seen_at, reviewed, notes, last_run_id
                    ) VALUES (?,?,?,?,NULL,?,NULL,NULL,'',1.0,'[]',?,?,0,'',?)
                    """,
                    (
                        "k",
                        "One",
                        "https://ex.test/1",
                        "src",
                        "2026-04-10",
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:00:00Z",
                        run_id,
                    ),
                )
                eid = int(cur.lastrowid)
                conn.commit()

                row = list_discovered_events(conn, EventListFilters(), limit=10, offset=0)[0]
                self.assertFalse(row["reviewed"])
                self.assertFalse(row["rejected"])

                st = update_event_review(conn, eid, reviewed=True, rejected=False)
                self.assertTrue(st["reviewed"])
                self.assertFalse(st["rejected"])
                self.assertEqual(
                    count_discovered_events(
                        conn, EventListFilters(reviewed=True, rejected=False)
                    ),
                    1,
                )

                update_event_review(conn, eid, reviewed=False, rejected=True)
                self.assertEqual(
                    count_discovered_events(conn, EventListFilters(rejected=True)), 1
                )
                self.assertEqual(
                    count_discovered_events(
                        conn, EventListFilters(reviewed=False, rejected=False)
                    ),
                    0,
                )

                update_event_review(conn, eid, reviewed=False, rejected=False)
                self.assertEqual(
                    count_discovered_events(
                        conn, EventListFilters(reviewed=False, rejected=False)
                    ),
                    1,
                )
            finally:
                conn.close()

    def test_delete_website_unlinks_events_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO websites (source_key, enabled, type, config_json, display_order)
                    VALUES ('a', 1, 'tribe_rest', '{}', 0)
                    """
                )
                wid = int(cur.lastrowid)
                conn.commit()
                ev = [
                    DiscoveredEvent(
                        title="E1",
                        url="https://ex.test/1",
                        source="a",
                        website_id=wid,
                        start="2026-06-01",
                        relevance_score=1.0,
                    )
                ]
                persist_discovery(conn, ev)
                ok, n = delete_website(conn, wid, delete_events=False)
                self.assertTrue(ok)
                self.assertEqual(n, 0)
                cur.execute("SELECT COUNT(*) FROM websites WHERE id = ?", (wid,))
                self.assertEqual(cur.fetchone()[0], 0)
                cur.execute("SELECT website_id FROM discovered_events LIMIT 1")
                self.assertIsNone(cur.fetchone()[0])
                self.assertEqual(count_discovered_events(conn, EventListFilters()), 1)
            finally:
                conn.close()

    def test_delete_website_with_delete_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO websites (source_key, enabled, type, config_json, display_order)
                    VALUES ('b', 1, 'tribe_rest', '{}', 0)
                    """
                )
                wid = int(cur.lastrowid)
                conn.commit()
                ev = [
                    DiscoveredEvent(
                        title="E2",
                        url="https://ex.test/2",
                        source="b",
                        website_id=wid,
                        start="2026-06-02",
                        relevance_score=1.0,
                    )
                ]
                persist_discovery(conn, ev)
                ok, n = delete_website(conn, wid, delete_events=True)
                self.assertTrue(ok)
                self.assertEqual(n, 1)
                cur.execute("SELECT COUNT(*) FROM websites")
                self.assertEqual(cur.fetchone()[0], 0)
                self.assertEqual(count_discovered_events(conn, EventListFilters()), 0)
            finally:
                conn.close()

    def test_delete_website_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                ok, n = delete_website(conn, 999, delete_events=True)
                self.assertFalse(ok)
                self.assertEqual(n, 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
