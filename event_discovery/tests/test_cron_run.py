from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from event_discovery.automation_client import AutomationClientError
from event_discovery.automation_delivery_settings import AutomationDeliverySettings, WebhookDestination
from event_discovery.brief_models import DailyBrief, LastCrawlSummary
from event_discovery.cron_run import main_cron_run


def _sample_brief() -> DailyBrief:
    return DailyBrief(
        generated_at_utc="2026-06-05T12:00:00+00:00",
        geography_label="Burlington, Ontario",
        display_name="Campaign team",
        filters={},
        pending_count=1,
        items=[],
        triage_instructions="",
        crawl_job=LastCrawlSummary(job_id=42, status="succeeded", event_count=5),
    )


def _delivery_with_webhook() -> AutomationDeliverySettings:
    return AutomationDeliverySettings(
        webhooks=[
            WebhookDestination(
                id="1",
                url="https://hooks.slack.com/services/T/B/x",
                label="Slack",
                enabled=True,
            )
        ],
        skip_if_empty=False,
    )


class TestCronRun(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patch = patch.dict(os.environ, {}, clear=True)
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_missing_required_env_exits_2(self) -> None:
        self.assertEqual(main_cron_run(), 2)

    def _set_required_env(self) -> None:
        os.environ.update(
            {
                "EVENT_DISCOVERY_BASE_URL": "https://app.example",
                "EVENTS_CRAWL_API_TOKEN": "secret-token",
                "DISCOVERY_ACCOUNT_ID": "1",
            }
        )

    @patch("event_discovery.cron_run.deliver_brief_webhook")
    @patch("event_discovery.cron_run.run_remote_daily_automation")
    @patch("event_discovery.cron_run._resolve_delivery_settings")
    def test_success_delivers_webhook(
        self,
        resolve_delivery: MagicMock,
        run_remote: MagicMock,
        deliver: MagicMock,
    ) -> None:
        self._set_required_env()
        resolve_delivery.return_value = _delivery_with_webhook()
        run_remote.return_value = _sample_brief()

        self.assertEqual(main_cron_run(), 0)
        run_remote.assert_called_once()
        deliver.assert_called_once()
        payload = deliver.call_args.args[1]
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pending_count"], 1)

    @patch("event_discovery.cron_run.deliver_brief_webhook")
    @patch("event_discovery.cron_run.run_remote_daily_automation")
    @patch("event_discovery.cron_run._resolve_delivery_settings")
    def test_no_webhooks_configured_exits_0_after_crawl(
        self,
        resolve_delivery: MagicMock,
        run_remote: MagicMock,
        deliver: MagicMock,
    ) -> None:
        self._set_required_env()
        resolve_delivery.return_value = AutomationDeliverySettings()
        run_remote.return_value = _sample_brief()

        self.assertEqual(main_cron_run(), 0)
        deliver.assert_not_called()

    @patch("event_discovery.cron_run.deliver_brief_webhook")
    @patch("event_discovery.cron_run.run_remote_daily_automation")
    @patch("event_discovery.cron_run._resolve_delivery_settings")
    def test_skip_webhook_if_empty(
        self,
        resolve_delivery: MagicMock,
        run_remote: MagicMock,
        deliver: MagicMock,
    ) -> None:
        self._set_required_env()
        delivery = _delivery_with_webhook()
        delivery.skip_if_empty = True
        resolve_delivery.return_value = delivery
        brief = _sample_brief()
        brief.pending_count = 0
        run_remote.return_value = brief

        self.assertEqual(main_cron_run(), 0)
        deliver.assert_not_called()

    @patch("event_discovery.cron_run.deliver_brief_webhook")
    @patch("event_discovery.cron_run.run_remote_daily_automation")
    @patch("event_discovery.cron_run._resolve_delivery_settings")
    def test_crawl_failure_exits_1_and_posts_failure(
        self,
        resolve_delivery: MagicMock,
        run_remote: MagicMock,
        deliver: MagicMock,
    ) -> None:
        self._set_required_env()
        resolve_delivery.return_value = _delivery_with_webhook()
        run_remote.side_effect = AutomationClientError("crawl job 7 failed: timeout")

        self.assertEqual(main_cron_run(), 1)
        deliver.assert_called_once()
        payload = deliver.call_args.args[1]
        self.assertEqual(payload["status"], "failed")
        self.assertIn("timeout", payload["error"])

    @patch("event_discovery.cron_run.deliver_brief_webhook")
    @patch("event_discovery.cron_run.run_remote_daily_automation")
    @patch("event_discovery.cron_run._resolve_delivery_settings")
    def test_webhook_delivery_failure_exits_1(
        self,
        resolve_delivery: MagicMock,
        run_remote: MagicMock,
        deliver: MagicMock,
    ) -> None:
        self._set_required_env()
        resolve_delivery.return_value = _delivery_with_webhook()
        run_remote.return_value = _sample_brief()
        deliver.side_effect = RuntimeError("connection refused")

        self.assertEqual(main_cron_run(), 1)
