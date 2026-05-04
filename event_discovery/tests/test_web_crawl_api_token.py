from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from event_discovery.web import app


class TestWebCrawlApiToken(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _base_env(self) -> dict[str, str]:
        return {
            "OUTPUT_DIR": str(self._dir),
            "EVENTS_SESSION_SECRET": "x" * 32,
            "EVENTS_CRAWL_API_TOKEN": "crawl-secret-token-exactly-32b",
        }

    def test_bearer_creates_full_crawl_job_without_session(self) -> None:
        env = self._base_env()
        with patch.dict(os.environ, env, clear=False):

            def _noop_start_crawl_job(**_kwargs: object) -> None:
                return None

            with patch(
                "event_discovery.web.start_crawl_job",
                side_effect=_noop_start_crawl_job,
            ):
                with TestClient(app) as anon:
                    r = anon.post(
                        "/api/crawl-jobs",
                        json={"kind": "full"},
                        headers={
                            "Authorization": "Bearer crawl-secret-token-exactly-32b",
                            "X-Crawl-Account-Id": "1",
                        },
                    )
                    self.assertEqual(r.status_code, 202, r.text)
                    self.assertIn("job_id", r.json())

    def test_bearer_wrong_token_401(self) -> None:
        env = self._base_env()
        with patch.dict(os.environ, env, clear=False):
            with TestClient(app) as anon:
                r = anon.post(
                    "/api/crawl-jobs",
                    json={"kind": "full"},
                    headers={
                        "Authorization": "Bearer wrong-token-not-matching-secret",
                        "X-Crawl-Account-Id": "1",
                    },
                )
                self.assertEqual(r.status_code, 401, r.text)

    def test_bearer_missing_account_header_400(self) -> None:
        env = self._base_env()
        with patch.dict(os.environ, env, clear=False):
            with TestClient(app) as anon:
                r = anon.post(
                    "/api/crawl-jobs",
                    json={"kind": "full"},
                    headers={"Authorization": "Bearer crawl-secret-token-exactly-32b"},
                )
                self.assertEqual(r.status_code, 400, r.text)

    def test_bearer_without_token_configured_503(self) -> None:
        env = {
            "OUTPUT_DIR": str(self._dir),
            "EVENTS_SESSION_SECRET": "x" * 32,
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("EVENTS_CRAWL_API_TOKEN", None)
            with TestClient(app) as anon:
                r = anon.post(
                    "/api/crawl-jobs",
                    json={"kind": "full"},
                    headers={
                        "Authorization": "Bearer any",
                        "X-Crawl-Account-Id": "1",
                    },
                )
                self.assertEqual(r.status_code, 503, r.text)


if __name__ == "__main__":
    unittest.main()
