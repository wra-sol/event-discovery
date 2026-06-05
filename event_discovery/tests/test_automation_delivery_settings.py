from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from event_discovery.automation_delivery_settings import (
    AutomationDeliverySettings,
    WebhookDestination,
    get_automation_delivery_settings,
    normalize_webhook_inputs,
    save_automation_delivery_settings,
    validate_webhook_url,
)
from event_discovery.repository import open_connection
from event_discovery.schema_migrations import apply_migrations


class TestAutomationDeliverySettings(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp())
        self._db = self._dir / "discovery.db"
        apply_migrations(self._db)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._dir, ignore_errors=True)

    def test_validate_webhook_url_requires_https(self) -> None:
        self.assertEqual(
            validate_webhook_url("https://hooks.slack.com/x"),
            "https://hooks.slack.com/x",
        )
        with self.assertRaises(ValueError):
            validate_webhook_url("http://example.com/hook")

    def test_save_and_load_round_trip(self) -> None:
        conn = open_connection(self._db)
        try:
            settings = AutomationDeliverySettings(
                webhooks=[
                    WebhookDestination(
                        id="a",
                        label="Slack",
                        url="https://hooks.slack.com/services/T/B/x",
                        enabled=True,
                    )
                ],
                skip_if_empty=True,
            )
            save_automation_delivery_settings(conn, settings)
            loaded = get_automation_delivery_settings(conn)
            self.assertEqual(len(loaded.webhooks), 1)
            self.assertEqual(loaded.webhooks[0].label, "Slack")
            self.assertTrue(loaded.skip_if_empty)
            self.assertEqual(
                loaded.enabled_webhook_urls(),
                ["https://hooks.slack.com/services/T/B/x"],
            )
        finally:
            conn.close()

    def test_normalize_deduplicates_urls(self) -> None:
        webhooks = normalize_webhook_inputs(
            [
                {"url": "https://example.com/a"},
                {"url": "https://example.com/a"},
            ],
            allow_http=False,
        )
        self.assertEqual(len(webhooks), 1)
