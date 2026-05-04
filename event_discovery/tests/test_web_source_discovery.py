from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from event_discovery.web import app


class TestWebSourceDiscovery(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix="ev-srcdisc-")

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _env(self) -> dict[str, str]:
        return {
            "EVENT_DISCOVERY_DISABLE_AUTH": "1",
            "EVENTS_SESSION_SECRET": "x" * 32,
            "OUTPUT_DIR": self._dir,
        }

    def test_source_discovery_returns_proposal(self) -> None:
        fake = {
            "recommended_type": "json_ld_events",
            "confidence": 0.9,
            "suggested_config": {"page_url": "https://x.example/y"},
            "source_key": "x-example-y",
            "source_label": "Events",
            "evidence": ["JSON-LD Event"],
            "caveats": [],
            "method": "heuristic",
            "save_ready": True,
            "validation_error": None,
            "discovered_url": "https://x.example/y",
            "fallback_type": None,
            "fallback_config": None,
        }
        with patch.dict(os.environ, self._env(), clear=False):
            with patch(
                "event_discovery.web.discover_source_proposal",
                return_value=fake,
            ):
                with TestClient(app) as client:
                    r = client.post(
                        "/api/source-discovery",
                        json={"url": "https://x.example/y", "use_llm": False},
                    )
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["recommended_type"], "json_ld_events")
        self.assertTrue(data["save_ready"])
        self.assertEqual(data["source_key"], "x-example-y")

    def test_source_discovery_read_only_403(self) -> None:
        fake = {
            "recommended_type": "unknown",
            "confidence": 0.0,
            "suggested_config": {},
            "source_key": "k",
            "source_label": "l",
            "evidence": [],
            "caveats": [],
            "method": "unknown",
            "save_ready": False,
            "validation_error": None,
            "discovered_url": "https://x/",
            "fallback_type": "json_ld_events",
            "fallback_config": {"page_url": "https://x/"},
        }
        env = {**self._env(), "EVENTS_WEB_READ_ONLY": "1"}
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "event_discovery.web.discover_source_proposal",
                return_value=fake,
            ):
                with TestClient(app) as client:
                    r = client.post(
                        "/api/source-discovery",
                        json={"url": "https://x/"},
                    )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
