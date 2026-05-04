from __future__ import annotations

import json
import logging
import unittest
from pathlib import Path

from event_discovery.http_util import ThrottledClient
from event_discovery.sources.tribe import fetch_tribe_rest


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload

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


class TestTribeFromFixture(unittest.TestCase):
    def test_maps_event_fields(self) -> None:
        fix = Path(__file__).resolve().parent / "fixtures" / "tribe_one_event.json"
        payload = json.loads(fix.read_text(encoding="utf-8"))
        client = _FakeClient([payload])
        log = logging.getLogger("test")
        cfg = {"rest_url": "https://example.test/events", "per_page": 10, "max_pages": 1}
        out = fetch_tribe_rest(client, cfg, log, "test_source")  # type: ignore[arg-type]
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "Sample Concert")
        self.assertIn("sample-concert", out[0].url)
        self.assertEqual(out[0].venue, "Town Hall — 1 Main St, Burlington")


if __name__ == "__main__":
    unittest.main()
