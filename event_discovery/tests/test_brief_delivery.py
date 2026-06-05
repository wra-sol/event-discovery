from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from event_discovery.brief_delivery import (
    build_failure_payload,
    build_webhook_payload,
    deliver_brief_webhook,
    is_slack_webhook,
)
from event_discovery.brief_models import CalendarEntry, DailyBrief, DailyBriefItem, LastCrawlSummary


def _sample_brief_dict(*, pending_count: int = 1) -> dict:
    items = (
        [
            DailyBriefItem(
                id=1,
                title="Community Fair",
                url="https://example.com/fair",
                source="test",
                relevance_score=2.5,
                candidate_message_draft="Hi Frank — community fair this weekend.",
                calendar_entry=CalendarEntry(
                    calendar_name="Campaign events",
                    summary="Community Fair",
                    location="City Hall",
                    start_date="2026-06-15",
                    start_at="2026-06-15T18:00:00",
                    description="community festival",
                ),
            )
        ]
        if pending_count
        else []
    )
    brief = DailyBrief(
        generated_at_utc="2026-06-05T12:00:00+00:00",
        geography_label="Burlington, Ontario",
        display_name="Campaign team",
        filters={"min_score": 1.0},
        pending_count=pending_count,
        items=items,
        triage_instructions="Share, ignore, or defer each item.",
        crawl_job=LastCrawlSummary(job_id=99, status="succeeded", event_count=10),
    )
    return brief.to_dict()


class TestBriefDelivery(unittest.TestCase):
    def test_is_slack_webhook(self) -> None:
        self.assertTrue(is_slack_webhook("https://hooks.slack.com/services/T/B/x"))
        self.assertFalse(is_slack_webhook("https://example.com/webhook"))

    def test_build_webhook_payload_generic(self) -> None:
        brief = _sample_brief_dict()
        payload = build_webhook_payload(brief, fmt="markdown")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pending_count"], 1)
        self.assertIn("markdown", payload)
        self.assertIn("Community Fair", payload["markdown"])
        self.assertEqual(payload["brief"], brief)

    def test_build_webhook_payload_empty_brief(self) -> None:
        brief = _sample_brief_dict(pending_count=0)
        brief["items"] = []
        payload = build_webhook_payload(brief, fmt="markdown")
        self.assertEqual(payload["pending_count"], 0)
        self.assertIn("No pending events", payload["markdown"])

    def test_build_failure_payload(self) -> None:
        payload = build_failure_payload("crawl timed out")
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "crawl timed out")
        self.assertIn("generated_at_utc", payload)

    @patch("event_discovery.brief_delivery.httpx.Client")
    def test_deliver_brief_webhook_generic(self, client_cls: MagicMock) -> None:
        client = client_cls.return_value.__enter__.return_value
        response = MagicMock()
        response.raise_for_status.return_value = None
        client.post.return_value = response

        payload = build_webhook_payload(_sample_brief_dict(), fmt="markdown")
        deliver_brief_webhook("https://example.com/hook", payload)

        client.post.assert_called_once()
        args, kwargs = client.post.call_args
        self.assertEqual(args[0], "https://example.com/hook")
        self.assertEqual(kwargs["json"]["status"], "ok")
        self.assertIn("markdown", kwargs["json"])

    @patch("event_discovery.brief_delivery.httpx.Client")
    def test_deliver_brief_webhook_slack(self, client_cls: MagicMock) -> None:
        client = client_cls.return_value.__enter__.return_value
        response = MagicMock()
        response.raise_for_status.return_value = None
        client.post.return_value = response

        payload = build_webhook_payload(_sample_brief_dict(), fmt="markdown")
        deliver_brief_webhook("https://hooks.slack.com/services/T/B/x", payload)

        kwargs = client.post.call_args.kwargs
        self.assertIn("text", kwargs["json"])
        self.assertIn("Community Fair", kwargs["json"]["text"])
        self.assertNotIn("brief", kwargs["json"])
