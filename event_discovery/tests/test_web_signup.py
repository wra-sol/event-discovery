from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from event_discovery.web import app


class TestWebSignup(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _base_env(self) -> dict[str, str]:
        return {
            "OUTPUT_DIR": str(self._dir),
            "EVENTS_SESSION_SECRET": "x" * 32,
        }

    def test_signup_status_allowed_by_default(self) -> None:
        with patch.dict(os.environ, self._base_env(), clear=False):
            os.environ.pop("EVENT_DISCOVERY_ALLOW_SIGNUP", None)
            with TestClient(app) as client:
                r = client.get("/api/auth/signup-status")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json(), {"allowed": True})

    def test_signup_then_me(self) -> None:
        with patch.dict(os.environ, self._base_env(), clear=False):
            os.environ.pop("EVENT_DISCOVERY_ALLOW_SIGNUP", None)
            with TestClient(app) as client:
                r = client.post(
                    "/api/auth/signup",
                    json={"email": "New@Example.com", "password": "longenough"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                data = r.json()
                self.assertEqual(data["email"], "new@example.com")
                self.assertGreater(data["account_id"], 0)
                me = client.get("/api/auth/me")
                self.assertEqual(me.status_code, 200)
                self.assertEqual(me.json()["email"], "new@example.com")

    def test_signup_duplicate_email(self) -> None:
        with patch.dict(os.environ, self._base_env(), clear=False):
            os.environ.pop("EVENT_DISCOVERY_ALLOW_SIGNUP", None)
            with TestClient(app) as client:
                r1 = client.post(
                    "/api/auth/signup",
                    json={"email": "dup@example.com", "password": "longenough"},
                )
                self.assertEqual(r1.status_code, 200)
                r2 = client.post(
                    "/api/auth/signup",
                    json={"email": "dup@example.com", "password": "longenough2"},
                )
                self.assertEqual(r2.status_code, 409)

    def test_signup_disabled_returns_403(self) -> None:
        env = {**self._base_env(), "EVENT_DISCOVERY_ALLOW_SIGNUP": "0"}
        with patch.dict(os.environ, env, clear=False):
            with TestClient(app) as client:
                r = client.post(
                    "/api/auth/signup",
                    json={"email": "x@example.com", "password": "longenough"},
                )
                self.assertEqual(r.status_code, 403)

    def test_signup_short_password(self) -> None:
        with patch.dict(os.environ, self._base_env(), clear=False):
            os.environ.pop("EVENT_DISCOVERY_ALLOW_SIGNUP", None)
            with TestClient(app) as client:
                r = client.post(
                    "/api/auth/signup",
                    json={"email": "x@example.com", "password": "short"},
                )
                self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
