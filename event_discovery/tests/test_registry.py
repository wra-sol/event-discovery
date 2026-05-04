from __future__ import annotations

import json
import logging
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from event_discovery.pipeline import collect_events
from event_discovery.sources.registry import (
    KNOWN_SOURCE_TYPES,
    iter_source_configs,
    resolve_event_source_label,
    source_robots_probe_url,
)


class _FakeResp:
    def __init__(self, payload: dict | None = None, text: str = "", status: int = 200) -> None:
        self.status_code = status
        self.text = text
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages
        self._n = 0

    def get(self, url: str, headers: dict | None = None) -> _FakeResp:
        if self._n >= len(self._pages):
            return _FakeResp({"events": []})
        p = self._pages[self._n]
        self._n += 1
        return _FakeResp(p)

    def close(self) -> None:
        pass


class TestRegistry(unittest.TestCase):
    def test_known_types_include_legacy(self) -> None:
        self.assertIn("tribe_rest", KNOWN_SOURCE_TYPES)
        self.assertIn("burlington_events_ldjson", KNOWN_SOURCE_TYPES)
        self.assertIn("json_ld_events", KNOWN_SOURCE_TYPES)

    def test_resolve_event_source_label_legacy(self) -> None:
        self.assertEqual(resolve_event_source_label("tourism", {}), "tourism_burlington")
        self.assertEqual(resolve_event_source_label("downtown", {}), "downtown_bdba")
        self.assertEqual(resolve_event_source_label("city_events", {}), "city_events")

    def test_resolve_event_source_label_override(self) -> None:
        self.assertEqual(
            resolve_event_source_label("tourism", {"source_label": "custom"}),
            "custom",
        )

    def test_source_robots_probe_url(self) -> None:
        self.assertEqual(
            source_robots_probe_url("tribe_rest", {"rest_url": "https://a.test/e"}),
            "https://a.test/e",
        )
        self.assertEqual(
            source_robots_probe_url("json_ld_events", {"page_url": "https://b.test/"}),
            "https://b.test/",
        )
        self.assertIsNone(source_robots_probe_url("eventbrite_listing", {"listing_urls": []}))

    def test_iter_source_configs_order(self) -> None:
        cfg = {
            "source_order": ["b", "a"],
            "sources": {
                "a": {"type": "x", "enabled": True},
                "b": {"type": "y", "enabled": True},
                "c": {"type": "z", "enabled": True},
            },
        }
        keys = [k for k, _ in iter_source_configs(cfg)]
        self.assertEqual(keys, ["b", "a", "c"])

    def test_collect_events_dispatches_tribe(self) -> None:
        fix = Path(__file__).resolve().parent / "fixtures" / "tribe_one_event.json"
        payload = json.loads(fix.read_text(encoding="utf-8"))
        client = _FakeClient([payload])
        cfg = {
            "sources": {
                "solo": {
                    "enabled": True,
                    "type": "tribe_rest",
                    "rest_url": "https://example.test/wp-json/tribe/events/v1/events",
                    "per_page": 10,
                    "max_pages": 1,
                }
            }
        }
        with patch("event_discovery.pipeline._robots_ok", return_value=True):
            out = collect_events(cfg, client, source_filter=None, today_local=date(2026, 4, 1))  # type: ignore[arg-type]
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "Sample Concert")
        self.assertEqual(out[0].source, "solo")

    def test_collect_events_legacy_tourism_label(self) -> None:
        fix = Path(__file__).resolve().parent / "fixtures" / "tribe_one_event.json"
        payload = json.loads(fix.read_text(encoding="utf-8"))
        client = _FakeClient([payload])
        cfg = {
            "sources": {
                "tourism": {
                    "enabled": True,
                    "type": "tribe_rest",
                    "rest_url": "https://example.test/wp-json/tribe/events/v1/events",
                    "per_page": 10,
                    "max_pages": 1,
                }
            }
        }
        with patch("event_discovery.pipeline._robots_ok", return_value=True):
            out = collect_events(cfg, client, source_filter=None, today_local=date(2026, 4, 1))  # type: ignore[arg-type]
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].source, "tourism_burlington")

    def test_collect_events_unknown_type_skipped(self) -> None:
        client = _FakeClient([])
        cfg = {
            "sources": {
                "bad": {"enabled": True, "type": "future_magic_scraper", "rest_url": "https://x.test/"},
            }
        }
        with patch("event_discovery.pipeline._robots_ok", return_value=True):
            out = collect_events(cfg, client, source_filter=None, today_local=date(2026, 4, 1))  # type: ignore[arg-type]
        self.assertEqual(out, [])

    def test_collect_events_source_filter(self) -> None:
        fix = Path(__file__).resolve().parent / "fixtures" / "tribe_one_event.json"
        payload = json.loads(fix.read_text(encoding="utf-8"))
        client = _FakeClient([payload, payload])
        cfg = {
            "sources": {
                "keep": {
                    "enabled": True,
                    "type": "tribe_rest",
                    "rest_url": "https://a.test/e",
                    "per_page": 10,
                    "max_pages": 1,
                },
                "skip": {
                    "enabled": True,
                    "type": "tribe_rest",
                    "rest_url": "https://b.test/e",
                    "per_page": 10,
                    "max_pages": 1,
                },
            }
        }
        with patch("event_discovery.pipeline._robots_ok", return_value=True):
            out = collect_events(
                cfg, client, source_filter={"keep"}, today_local=date(2026, 4, 1)
            )  # type: ignore[arg-type]
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
