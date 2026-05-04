from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from datetime import date

from event_discovery.pipeline import collect_events
from event_discovery.repository import (
    enabled_websites_count,
    fetch_website_source_for_crawl,
    iter_enabled_website_sources,
    list_websites,
    open_connection,
    sync_websites_from_config,
)
from event_discovery.schema_migrations import apply_migrations


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages
        self._n = 0

    def get(self, url: str, headers: dict | None = None) -> _FakeResp:
        if self._n >= len(self._pages):
            return _FakeResp({"events": []})
        p = self._pages[self._n]
        self._n += 1
        return _FakeResp(p)

    def close(self) -> None:
        pass


class TestWebsites(unittest.TestCase):
    def test_empty_table_uses_yaml_path_in_collect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                self.assertEqual(enabled_websites_count(conn), 0)
                self.assertEqual(list(iter_enabled_website_sources(conn)), [])
            finally:
                conn.close()

    def test_sync_and_collect_sets_website_id(self) -> None:
        fix = Path(__file__).resolve().parent / "fixtures" / "tribe_one_event.json"
        payload = json.loads(fix.read_text(encoding="utf-8"))
        cfg = {
            "sources": {
                "solo": {
                    "enabled": True,
                    "type": "tribe_rest",
                    "rest_url": "https://example.test/wp-json/tribe/events/v1/events",
                    "per_page": 10,
                    "max_pages": 1,
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                sync_websites_from_config(conn, cfg)
                self.assertEqual(enabled_websites_count(conn), 1)
                with (
                    patch("event_discovery.pipeline._robots_ok", return_value=True),
                    patch(
                        "event_discovery.pipeline.ThrottledClient",
                        side_effect=lambda **_: _FakeClient([payload]),
                    ),
                ):
                    out = collect_events(
                        cfg,
                        _FakeClient([payload]),
                        source_filter=None,
                        today_local=date(2026, 4, 1),
                        website_conn=conn,
                    )
                self.assertEqual(len(out), 1)
                self.assertIsNotNone(out[0].website_id)
            finally:
                conn.close()

    def test_fetch_website_source_for_crawl(self) -> None:
        cfg = {
            "sources": {
                "solo": {
                    "enabled": True,
                    "type": "tribe_rest",
                    "rest_url": "https://example.test/wp-json/tribe/events/v1/events",
                    "per_page": 10,
                    "max_pages": 1,
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                sync_websites_from_config(conn, cfg)
                cur = conn.cursor()
                cur.execute("SELECT id FROM websites WHERE source_key = ?", ("solo",))
                wid = int(cur.fetchone()[0])
                self.assertIsNone(fetch_website_source_for_crawl(conn, 99999))
                row = fetch_website_source_for_crawl(conn, wid)
                assert row is not None
                self.assertEqual(row[0], wid)
                self.assertEqual(row[1], "solo")
                self.assertTrue(row[2]["enabled"])
                self.assertEqual(row[3], {})
                cur.execute("UPDATE websites SET enabled = 0")
                conn.commit()
                row2 = fetch_website_source_for_crawl(conn, wid)
                assert row2 is not None
                self.assertTrue(row2[2]["enabled"])
                self.assertEqual(row2[3], {})
            finally:
                conn.close()

    def test_only_website_id_crawls_when_all_sites_disabled(self) -> None:
        fix = Path(__file__).resolve().parent / "fixtures" / "tribe_one_event.json"
        payload = json.loads(fix.read_text(encoding="utf-8"))
        cfg = {
            "sources": {
                "solo": {
                    "enabled": True,
                    "type": "tribe_rest",
                    "rest_url": "https://example.test/wp-json/tribe/events/v1/events",
                    "per_page": 10,
                    "max_pages": 1,
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                sync_websites_from_config(conn, cfg)
                cur = conn.cursor()
                cur.execute("SELECT id FROM websites WHERE source_key = ?", ("solo",))
                wid = int(cur.fetchone()[0])
                cur.execute("UPDATE websites SET enabled = 0")
                conn.commit()
                self.assertEqual(enabled_websites_count(conn), 0)
                with (
                    patch("event_discovery.pipeline._robots_ok", return_value=True),
                    patch(
                        "event_discovery.pipeline.ThrottledClient",
                        side_effect=lambda **_: _FakeClient([payload]),
                    ),
                ):
                    out = collect_events(
                        cfg,
                        _FakeClient([payload]),
                        source_filter=None,
                        today_local=date(2026, 4, 1),
                        website_conn=conn,
                        only_website_id=wid,
                    )
                self.assertEqual(len(out), 1)
                self.assertEqual(out[0].website_id, wid)
            finally:
                conn.close()

    def test_sync_websites_from_config_preferences_yaml(self) -> None:
        cfg = {
            "sources": {
                "solo": {
                    "enabled": True,
                    "type": "tribe_rest",
                    "rest_url": "https://example.test/wp-json/tribe/events/v1/events",
                    "preferences": {
                        "scoring": {"horizon_days": 30},
                        "http": {"delay_seconds": 1.25},
                    },
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                sync_websites_from_config(conn, cfg)
                sites = list_websites(conn)
                self.assertEqual(len(sites), 1)
                self.assertEqual(sites[0]["preferences"]["scoring"]["horizon_days"], 30)
                self.assertEqual(sites[0]["preferences"]["http"]["delay_seconds"], 1.25)
                self.assertNotIn("preferences", sites[0]["config"])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
