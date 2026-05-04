from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from event_discovery.models import DiscoveredEvent
from event_discovery.paths import account_discovery_db_path
from event_discovery.pipeline import load_config
from event_discovery.repository import open_connection, persist_discovery
from event_discovery.web import app


class TestWebDeleteWebsite(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _env(self) -> dict[str, str]:
        return {
            "OUTPUT_DIR": str(self._dir),
            "EVENT_DISCOVERY_DISABLE_AUTH": "1",
        }

    def _account_db(self) -> Path:
        return account_discovery_db_path(self._dir, 1, cfg=load_config(None))

    def test_delete_unlinks_events_when_delete_events_false(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                client.get("/api/websites")
                db_path = self._account_db()
                conn = open_connection(db_path)
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO websites (source_key, enabled, type, config_json, display_order)
                        VALUES ('z', 1, 'tribe_rest', '{}', 0)
                        """
                    )
                    wid = int(cur.lastrowid)
                    conn.commit()
                    persist_discovery(
                        conn,
                        [
                            DiscoveredEvent(
                                title="T",
                                url="https://ex.test/e",
                                source="z",
                                website_id=wid,
                                start="2026-06-01",
                                relevance_score=1.0,
                            )
                        ],
                    )
                finally:
                    conn.close()

                r = client.delete(f"/api/websites/{wid}?delete_events=false")
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json(), {"deleted": True, "events_removed": 0})

                conn = open_connection(db_path)
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM websites")
                    self.assertEqual(cur.fetchone()[0], 0)
                    cur.execute("SELECT COUNT(*) FROM discovered_events")
                    self.assertEqual(cur.fetchone()[0], 1)
                    cur.execute("SELECT website_id FROM discovered_events LIMIT 1")
                    self.assertIsNone(cur.fetchone()[0])
                finally:
                    conn.close()

    def test_delete_removes_events_when_delete_events_true(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                client.get("/api/websites")
                db_path = self._account_db()
                conn = open_connection(db_path)
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO websites (source_key, enabled, type, config_json, display_order)
                        VALUES ('y', 1, 'tribe_rest', '{}', 0)
                        """
                    )
                    wid = int(cur.lastrowid)
                    conn.commit()
                    persist_discovery(
                        conn,
                        [
                            DiscoveredEvent(
                                title="E",
                                url="https://ex.test/y",
                                source="y",
                                website_id=wid,
                                start="2026-07-01",
                                relevance_score=2.0,
                            )
                        ],
                    )
                finally:
                    conn.close()

                r = client.delete(f"/api/websites/{wid}?delete_events=true")
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json(), {"deleted": True, "events_removed": 1})

                conn = open_connection(db_path)
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM websites")
                    self.assertEqual(cur.fetchone()[0], 0)
                    cur.execute("SELECT COUNT(*) FROM discovered_events")
                    self.assertEqual(cur.fetchone()[0], 0)
                finally:
                    conn.close()

    def test_delete_website_not_found(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                client.get("/api/websites")
                r = client.delete("/api/websites/99999?delete_events=false")
                self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
