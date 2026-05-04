from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from event_discovery.paths import account_discovery_db_path
from event_discovery.pipeline import load_config
from event_discovery.repository import open_connection
from event_discovery.web import app


class TestWebDiscoverySettings(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _env(self) -> dict[str, str]:
        return {
            "OUTPUT_DIR": str(self._dir),
            "EVENT_DISCOVERY_DISABLE_AUTH": "1",
        }

    def test_get_discovery_settings(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                r = client.get("/api/discovery-settings")
                self.assertEqual(r.status_code, 200, r.text)
                data = r.json()
                self.assertIn("http", data)
                self.assertIn("scoring", data)
                self.assertIn("enrichment", data)
                self.assertIn("user_agent", data["http"])
                self.assertIn("horizon_days", data["scoring"])
                self.assertIn("enabled", data["enrichment"])

    def test_patch_discovery_settings_persists(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                client.get("/api/websites")
                r = client.patch(
                    "/api/discovery-settings",
                    json={
                        "scoring": {"horizon_days": 42},
                        "enrichment": {"enabled": False, "max_urls": 10},
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["scoring"]["horizon_days"], 42)
                self.assertFalse(r.json()["enrichment"]["enabled"])
                self.assertEqual(r.json()["enrichment"]["max_urls"], 10)

                db_path = account_discovery_db_path(self._dir, 1, cfg=load_config(None))
                conn = open_connection(db_path)
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT value_json FROM discovery_settings WHERE key = ?",
                        ("scoring",),
                    )
                    row = cur.fetchone()
                    self.assertIsNotNone(row)
                    sj = json.loads(row[0])
                    self.assertEqual(sj["horizon_days"], 42)
                finally:
                    conn.close()

    def test_bulk_enabled(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                client.get("/api/websites")
                db_path = account_discovery_db_path(self._dir, 1, cfg=load_config(None))
                conn = open_connection(db_path)
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO websites (source_key, enabled, type, config_json, display_order)
                        VALUES ('a', 0, 'tribe_rest', '{}', 0)
                        """
                    )
                    cur.execute(
                        """
                        INSERT INTO websites (source_key, enabled, type, config_json, display_order)
                        VALUES ('b', 0, 'tribe_rest', '{}', 1)
                        """
                    )
                    conn.commit()
                finally:
                    conn.close()

                r = client.patch("/api/websites/bulk-enabled", json={"enabled": True})
                self.assertEqual(r.status_code, 200, r.text)
                rows = r.json()
                self.assertTrue(all(x["enabled"] for x in rows))

                r2 = client.patch("/api/websites/bulk-enabled", json={"enabled": False})
                self.assertEqual(r2.status_code, 200)
                self.assertFalse(any(x["enabled"] for x in r2.json()))

    def test_read_only_blocks_patch(self) -> None:
        env = {**self._env(), "EVENTS_WEB_READ_ONLY": "1"}
        with patch.dict(os.environ, env, clear=False):
            with TestClient(app) as client:
                client.get("/api/websites")
                r = client.patch(
                    "/api/discovery-settings",
                    json={"scoring": {"horizon_days": 1}},
                )
                self.assertEqual(r.status_code, 403)
                r2 = client.patch("/api/websites/bulk-enabled", json={"enabled": True})
                self.assertEqual(r2.status_code, 403)


if __name__ == "__main__":
    unittest.main()
