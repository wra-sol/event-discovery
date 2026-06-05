from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from event_discovery.web import app


class TestWebAgentApiToken(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _env(self) -> dict[str, str]:
        return {
            "OUTPUT_DIR": str(self._dir),
            "EVENTS_SESSION_SECRET": "x" * 32,
            "EVENTS_AGENT_API_TOKEN": "agent-secret-token-exactly-32-bytes",
            "EVENTS_CRAWL_API_TOKEN": "crawl-secret-token-exactly-32b",
        }

    def _agent_headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer agent-secret-token-exactly-32-bytes",
            "X-Agent-Account-Id": "1",
        }

    def test_agent_token_can_manage_websites(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                created = client.post(
                    "/api/websites",
                    json={
                        "source_key": "city_events",
                        "type": "json_ld_events",
                        "config": {"page_url": "https://example.test/events"},
                        "source_label": "City events",
                        "enabled": False,
                    },
                    headers=self._agent_headers(),
                )
                self.assertEqual(created.status_code, 200, created.text)
                wid = created.json()["id"]

                patched = client.patch(
                    f"/api/websites/{wid}",
                    json={"enabled": True, "source_label": "Updated city events"},
                    headers=self._agent_headers(),
                )
                self.assertEqual(patched.status_code, 200, patched.text)
                self.assertTrue(patched.json()["enabled"])

                listed = client.get("/api/websites", headers=self._agent_headers())
                self.assertEqual(listed.status_code, 200, listed.text)
                self.assertEqual(len(listed.json()), 1)

    def test_agent_token_can_patch_discovery_settings(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                r = client.patch(
                    "/api/discovery-settings",
                    json={"scoring": {"horizon_days": 21}},
                    headers=self._agent_headers(),
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["scoring"]["horizon_days"], 21)

    def test_agent_token_can_manage_automation_delivery(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                updated = client.put(
                    "/api/automation/delivery",
                    json={
                        "webhooks": [
                            {
                                "id": "brief",
                                "label": "Daily brief",
                                "url": "https://hooks.example.test/brief",
                                "enabled": True,
                            }
                        ],
                        "skip_if_empty": True,
                    },
                    headers=self._agent_headers(),
                )
                self.assertEqual(updated.status_code, 200, updated.text)
                self.assertTrue(updated.json()["skip_if_empty"])
                self.assertEqual(updated.json()["webhooks"][0]["id"], "brief")

                fetched = client.get(
                    "/api/automation/delivery",
                    headers=self._agent_headers(),
                )
                self.assertEqual(fetched.status_code, 200, fetched.text)
                self.assertEqual(fetched.json()["webhooks"][0]["label"], "Daily brief")

    def test_agent_token_can_run_automation_without_waiting(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):

            def _noop_start_crawl_job(**_kwargs: object) -> None:
                return None

            with patch(
                "event_discovery.web.start_crawl_job",
                side_effect=_noop_start_crawl_job,
            ):
                with TestClient(app) as client:
                    r = client.post(
                        "/api/automation/run",
                        json={"wait": False},
                        headers=self._agent_headers(),
                    )
                self.assertEqual(r.status_code, 202, r.text)
                self.assertEqual(r.json()["job"]["status"], "queued")

    def test_crawl_token_cannot_manage_sources(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                r = client.get(
                    "/api/websites",
                    headers={
                        "Authorization": "Bearer crawl-secret-token-exactly-32b",
                        "X-Crawl-Account-Id": "1",
                    },
                )
                self.assertEqual(r.status_code, 401, r.text)

    def test_agent_token_requires_account_header(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):
            with TestClient(app) as client:
                r = client.get(
                    "/api/websites",
                    headers={"Authorization": "Bearer agent-secret-token-exactly-32-bytes"},
                )
                self.assertEqual(r.status_code, 400, r.text)


if __name__ == "__main__":
    unittest.main()
