from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from event_discovery.web import app


class TestWebQuickAdd(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix="ev-quickadd-")

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _env(self) -> dict[str, str]:
        return {
            "EVENT_DISCOVERY_DISABLE_AUTH": "1",
            "EVENTS_SESSION_SECRET": "x" * 32,
            "OUTPUT_DIR": self._dir,
        }

    def test_quick_add_creates_website(self) -> None:
        proposal = {
            "recommended_type": "json_ld_events",
            "confidence": 0.9,
            "suggested_config": {"page_url": "https://x.example/y"},
            "source_key": "ignored",
            "source_label": "My label",
            "evidence": ["JSON-LD"],
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
                return_value=proposal,
            ):
                with TestClient(app) as client:
                    r = client.post(
                        "/api/websites/quick-add",
                        json={
                            "url": "https://x.example/y",
                            "name": "City events",
                            "use_llm": False,
                        },
                    )
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertIn("website", data)
        self.assertIn("discovery", data)
        self.assertEqual(data["website"]["type"], "json_ld_events")
        self.assertEqual(data["website"]["source_label"], "City events")
        self.assertFalse(data["website"]["enabled"])
        self.assertEqual(data["discovery"]["method"], "heuristic")

    def test_quick_add_read_only_403(self) -> None:
        proposal = {
            "recommended_type": "json_ld_events",
            "confidence": 0.9,
            "suggested_config": {"page_url": "https://x/y"},
            "source_key": "k",
            "source_label": "L",
            "evidence": [],
            "caveats": [],
            "method": "heuristic",
            "save_ready": True,
            "validation_error": None,
            "discovered_url": "https://x/y",
            "fallback_type": None,
            "fallback_config": None,
        }
        env = {**self._env(), "EVENTS_WEB_READ_ONLY": "1"}
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "event_discovery.web.discover_source_proposal",
                return_value=proposal,
            ):
                with TestClient(app) as client:
                    r = client.post(
                        "/api/websites/quick-add",
                        json={"url": "https://x/y", "name": "N"},
                    )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
