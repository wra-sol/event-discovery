from __future__ import annotations

import unittest
from unittest.mock import patch

from event_discovery.source_discovery import (
    _heuristic_discover,
    discover_source_proposal,
    finalize_proposal,
)


class TestHeuristicDiscover(unittest.TestCase):
    def test_eventbrite_host(self) -> None:
        page = {
            "url": "https://www.eventbrite.ca/o/foo-org",
            "status_code": 200,
            "_full_body": "<html/>",
        }
        h = _heuristic_discover(page, timeout=1.0)
        self.assertIsNotNone(h)
        assert h is not None
        self.assertEqual(h["recommended_type"], "eventbrite_listing")
        self.assertEqual(h["suggested_config"]["listing_urls"], [page["url"]])

    def test_json_ld_events(self) -> None:
        html = (
            '<html><script type="application/ld+json">'
            '{"@type":"Event","name":"Party","startDate":"2026-05-01"}'
            "</script></html>"
        )
        page = {
            "url": "https://city.example/events",
            "status_code": 200,
            "_full_body": html,
        }
        with patch(
            "event_discovery.source_discovery._probe_tribe_rest",
            return_value=None,
        ):
            h = _heuristic_discover(page, timeout=1.0)
        self.assertIsNotNone(h)
        assert h is not None
        self.assertEqual(h["recommended_type"], "json_ld_events")
        self.assertEqual(h["suggested_config"]["page_url"], page["url"])

    def test_tribe_when_probe_succeeds(self) -> None:
        feed = "https://wp.test/wp-json/tribe/events/v1/events"
        with patch(
            "event_discovery.source_discovery._probe_tribe_rest",
            return_value=feed,
        ):
            page = {
                "url": "https://wp.test/events/",
                "status_code": 200,
                "_full_body": "<html/>",
            }
            h = _heuristic_discover(page, timeout=1.0)
        self.assertIsNotNone(h)
        assert h is not None
        self.assertEqual(h["recommended_type"], "tribe_rest")
        self.assertEqual(h["suggested_config"]["rest_url"], feed)

    def test_no_match_on_plain_html(self) -> None:
        page = {
            "url": "https://plain.example/",
            "status_code": 200,
            "_full_body": "<html><body>hello</body></html>",
        }
        with patch(
            "event_discovery.source_discovery._probe_tribe_rest",
            return_value=None,
        ):
            self.assertIsNone(_heuristic_discover(page, timeout=1.0))


class TestFinalizeProposal(unittest.TestCase):
    def test_save_ready_when_valid(self) -> None:
        out = finalize_proposal(
            {
                "recommended_type": "json_ld_events",
                "confidence": 0.9,
                "suggested_config": {"page_url": "https://ex.test/cal"},
                "evidence": ["ld+json"],
                "caveats": [],
            },
            discovered_url="https://ex.test/cal",
            html_for_title="<title>T</title>",
            method="heuristic",
        )
        self.assertTrue(out["save_ready"])
        self.assertIsNone(out["validation_error"])
        self.assertEqual(out["recommended_type"], "json_ld_events")

    def test_save_ready_false_when_invalid(self) -> None:
        out = finalize_proposal(
            {
                "recommended_type": "tribe_rest",
                "confidence": 1.0,
                "suggested_config": {"rest_url": "https://bad.example/no-json"},
                "evidence": [],
                "caveats": [],
            },
            discovered_url="https://bad.example/",
            html_for_title="",
            method="heuristic",
        )
        self.assertFalse(out["save_ready"])
        self.assertIsNotNone(out["validation_error"])

    def test_unknown_includes_fallback(self) -> None:
        out = finalize_proposal(
            {
                "recommended_type": "unknown",
                "confidence": 0.0,
                "suggested_config": {},
                "evidence": [],
                "caveats": [],
            },
            discovered_url="https://u.test/p",
            html_for_title="",
            method="unknown",
        )
        self.assertEqual(out["recommended_type"], "unknown")
        self.assertEqual(out["fallback_type"], "json_ld_events")
        self.assertEqual(out["fallback_config"]["page_url"], "https://u.test/p")


class TestDiscoverSourceProposal(unittest.TestCase):
    def test_end_to_end_heuristic_json_ld_no_llm(self) -> None:
        html = (
            '<html><head><title>Cal</title></head>'
            '<script type="application/ld+json">{"@type":"Event","name":"E"}</script></html>'
        )

        def fake_fetch(url: str, **kwargs: object) -> dict:
            return {
                "url": "https://z.example/cal",
                "status_code": 200,
                "headers": {},
                "body_excerpt": html,
                "_full_body": html,
            }

        with (
            patch(
                "event_discovery.source_discovery.fetch_page_brief",
                side_effect=fake_fetch,
            ),
            patch(
                "event_discovery.source_discovery._probe_tribe_rest",
                return_value=None,
            ),
        ):
            out = discover_source_proposal(
                "https://z.example/cal",
                use_llm=False,
            )
        self.assertEqual(out["method"], "heuristic")
        self.assertTrue(out["save_ready"])
        self.assertEqual(out["recommended_type"], "json_ld_events")

    def test_no_heuristic_no_llm_returns_unknown(self) -> None:
        html = "<html><body>no signals</body></html>"

        def fake_fetch(url: str, **kwargs: object) -> dict:
            return {
                "url": "https://plain.example/",
                "status_code": 200,
                "headers": {},
                "body_excerpt": html,
                "_full_body": html,
            }

        with (
            patch(
                "event_discovery.source_discovery.fetch_page_brief",
                side_effect=fake_fetch,
            ),
            patch(
                "event_discovery.source_discovery._probe_tribe_rest",
                return_value=None,
            ),
        ):
            out = discover_source_proposal("https://plain.example/", use_llm=False)
        self.assertEqual(out["recommended_type"], "unknown")
        self.assertEqual(out["method"], "unknown")


if __name__ == "__main__":
    unittest.main()
