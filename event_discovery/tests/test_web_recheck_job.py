from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from event_discovery.web import app


class TestWebRecheckJob(unittest.TestCase):
    def _env(self) -> dict[str, str]:
        return {
            "EVENT_DISCOVERY_DISABLE_AUTH": "1",
            "EVENTS_SESSION_SECRET": "x" * 32,
            "OUTPUT_DIR": self._dir,
        }

    def setUp(self) -> None:
        import tempfile

        self._dir = tempfile.mkdtemp(prefix="evrecheck-")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._dir, ignore_errors=True)

    def test_recheck_returns_202_and_job_row(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False):

            def _noop_start_crawl_job(**_kwargs: object) -> None:
                return None

            with patch(
                "event_discovery.web.start_crawl_job",
                side_effect=_noop_start_crawl_job,
            ):
                with TestClient(app) as client:
                    rows = client.get("/api/websites").json()
                    if not rows:
                        self.skipTest("no websites seeded in test DB")
                    wid = int(rows[0]["id"])
                    r = client.post(f"/api/websites/{wid}/recheck")
                    self.assertEqual(r.status_code, 202, r.text)
                    data = r.json()
                    self.assertIn("job_id", data)
                    jid = int(data["job_id"])
                    r2 = client.get(f"/api/crawl-jobs/{jid}")
                    self.assertEqual(r2.status_code, 200, r2.text)
                    self.assertEqual(r2.json()["status"], "queued")
