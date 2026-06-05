from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from event_discovery.campaign_config import load_campaign_profile
from event_discovery.daily_brief import build_daily_brief
from event_discovery.pipeline import load_config
from event_discovery.repository import open_connection
from event_discovery.schema_migrations import apply_migrations
from event_discovery.web import app


def _seed_event(
    conn: sqlite3.Connection,
    *,
    title: str,
    score: float,
    reviewed: int = 0,
    rejected: int = 0,
    first_seen_at: str = "2026-06-01T12:00:00Z",
    start_at: str = "2026-06-15T18:00:00Z",
) -> None:
    conn.execute(
        """
        INSERT INTO discovered_events (
            dedupe_key, title, url, source, start_at, venue, raw_snippet,
            relevance_score, relevance_reasons_json, first_seen_at, last_seen_at,
            reviewed, rejected, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"key-{title}",
            title,
            f"https://example.com/{title.replace(' ', '-')}",
            "test",
            start_at,
            "City Hall",
            "community festival",
            score,
            '["keyword:Burlington"]',
            first_seen_at,
            first_seen_at,
            reviewed,
            rejected,
            "",
        ),
    )
    conn.commit()


class TestCampaignConfig(unittest.TestCase):
    def test_load_campaign_profile_defaults(self) -> None:
        cfg = load_config(None)
        profile = load_campaign_profile(cfg)
        self.assertEqual(profile.geography_label, "Burlington, Ontario")
        self.assertEqual(profile.brief.min_score, 1.0)


class TestDailyBrief(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp())
        self._db = self._dir / "discovery.db"
        apply_migrations(self._db)

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_build_daily_brief_filters_pending(self) -> None:
        conn = open_connection(self._db)
        try:
            _seed_event(conn, title="High score pending", score=3.0)
            _seed_event(conn, title="Low score pending", score=0.0)
            _seed_event(
                conn,
                title="Already rejected",
                score=4.0,
                rejected=1,
            )
            cfg = {
                "campaign": {
                    "geography_label": "Hamilton, Ontario",
                    "brief": {"min_score": 1.0, "include_past": True},
                }
            }
            profile = load_campaign_profile(cfg)
            brief = build_daily_brief(conn, config_path=None, profile=profile)
        finally:
            conn.close()
        titles = [i.title for i in brief.items]
        self.assertIn("High score pending", titles)
        self.assertNotIn("Low score pending", titles)
        self.assertNotIn("Already rejected", titles)
        self.assertEqual(brief.geography_label, "Hamilton, Ontario")
        self.assertTrue(brief.items[0].candidate_message_draft.startswith("Hi "))


class TestWebDailyBriefApi(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_daily_brief_with_bearer_token(self) -> None:
        env = {
            "OUTPUT_DIR": str(self._dir),
            "EVENTS_SESSION_SECRET": "x" * 32,
            "EVENTS_CRAWL_API_TOKEN": "crawl-secret-token-exactly-32b",
        }
        with patch.dict(os.environ, env, clear=False):
            with TestClient(app) as client:
                r = client.get(
                    "/api/daily-brief",
                    headers={
                        "Authorization": "Bearer crawl-secret-token-exactly-32b",
                        "X-Crawl-Account-Id": "1",
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertIn("items", body)
                self.assertIn("triage_instructions", body)

    def test_patch_review_with_bearer_token(self) -> None:
        env = {
            "OUTPUT_DIR": str(self._dir),
            "EVENTS_SESSION_SECRET": "x" * 32,
            "EVENTS_CRAWL_API_TOKEN": "crawl-secret-token-exactly-32b",
        }
        db_path = self._dir / "accounts" / "1" / "discovery.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        apply_migrations(db_path)
        conn = open_connection(db_path)
        try:
            _seed_event(conn, title="Reject me", score=2.0)
            eid = conn.execute("SELECT id FROM discovered_events LIMIT 1").fetchone()[0]
        finally:
            conn.close()

        with patch.dict(os.environ, env, clear=False):
            with TestClient(app) as client:
                r = client.patch(
                    f"/api/automation/events/{eid}/review",
                    json={"rejected": True},
                    headers={
                        "Authorization": "Bearer crawl-secret-token-exactly-32b",
                        "X-Crawl-Account-Id": "1",
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.json()["rejected"])

    def test_automation_delivery_get_and_put(self) -> None:
        env = {
            "OUTPUT_DIR": str(self._dir),
            "EVENTS_SESSION_SECRET": "x" * 32,
            "EVENTS_AGENT_API_TOKEN": "agent-secret-token-exactly-32-bytes",
        }
        db_path = self._dir / "accounts" / "1" / "discovery.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        apply_migrations(db_path)

        with patch.dict(os.environ, env, clear=False):
            with TestClient(app) as client:
                headers = {
                    "Authorization": "Bearer agent-secret-token-exactly-32-bytes",
                    "X-Agent-Account-Id": "1",
                }
                r0 = client.get("/api/automation/delivery", headers=headers)
                self.assertEqual(r0.status_code, 200, r0.text)
                self.assertEqual(r0.json()["webhooks"], [])

                r1 = client.put(
                    "/api/automation/delivery",
                    json={
                        "webhooks": [
                            {
                                "label": "Slack",
                                "url": "https://hooks.slack.com/services/T/B/x",
                                "enabled": True,
                            }
                        ],
                        "skip_if_empty": True,
                    },
                    headers=headers,
                )
                self.assertEqual(r1.status_code, 200, r1.text)
                body = r1.json()
                self.assertEqual(len(body["webhooks"]), 1)
                self.assertEqual(body["webhooks"][0]["label"], "Slack")
                self.assertTrue(body["skip_if_empty"])

    def test_automation_run_with_bearer_token_no_wait(self) -> None:
        env = {
            "OUTPUT_DIR": str(self._dir),
            "EVENTS_SESSION_SECRET": "x" * 32,
            "EVENTS_CRAWL_API_TOKEN": "crawl-secret-token-exactly-32b",
        }
        with patch.dict(os.environ, env, clear=False):

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
                        headers={
                            "Authorization": "Bearer crawl-secret-token-exactly-32b",
                            "X-Crawl-Account-Id": "1",
                        },
                    )
                self.assertEqual(r.status_code, 202, r.text)
                body = r.json()
                self.assertEqual(body["job"]["status"], "queued")
                self.assertIsNone(body["brief"])
                self.assertTrue(body["next_poll_url"].startswith("/api/crawl-jobs/"))

    def test_list_events_requires_session_not_bearer(self) -> None:
        env = {
            "OUTPUT_DIR": str(self._dir),
            "EVENTS_SESSION_SECRET": "x" * 32,
            "EVENTS_CRAWL_API_TOKEN": "crawl-secret-token-exactly-32b",
        }
        with patch.dict(os.environ, env, clear=False):
            with TestClient(app) as client:
                r = client.get(
                    "/api/events",
                    headers={
                        "Authorization": "Bearer crawl-secret-token-exactly-32b",
                        "X-Crawl-Account-Id": "1",
                    },
                )
                self.assertEqual(r.status_code, 401, r.text)


class TestBriefFormat(unittest.TestCase):
    def test_markdown_empty(self) -> None:
        from event_discovery.brief_format import format_brief_markdown

        text = format_brief_markdown({"geography_label": "Test", "pending_count": 0, "items": []})
        self.assertIn("No pending events", text)


if __name__ == "__main__":
    unittest.main()
