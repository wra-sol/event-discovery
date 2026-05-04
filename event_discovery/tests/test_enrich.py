from __future__ import annotations

import logging
import unittest

from event_discovery.enrich import enrich_discovered_events
from event_discovery.models import DiscoveredEvent


class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text


class _Client:
    def __init__(self, pages: dict[str, _Resp]) -> None:
        self.pages = pages
        self.get_calls: list[str] = []

    def get(self, url: str, headers: dict | None = None) -> _Resp:
        self.get_calls.append(url)
        return self.pages.get(url, _Resp(404, ""))


class TestEnrichDiscoveredEvents(unittest.TestCase):
    def test_fills_start_from_ld_json(self) -> None:
        ld = (
            '{"@type":"Event","name":"X","startDate":"2026-09-01T18:00:00",'
            '"location":{"name":"Hall"}}'
        )
        html = f'<html><script type="application/ld+json">{ld}</script></html>'
        u = "https://example.test/event/1"
        client = _Client(
            {
                "https://example.test/robots.txt": _Resp(404, ""),
                u: _Resp(200, html),
            }
        )
        ev = DiscoveredEvent(title="X", url=u, source="t")
        log = logging.getLogger("t")
        cfg: dict = {"enrichment": {"max_urls": 5}}
        out = enrich_discovered_events(
            client,  # type: ignore[arg-type]
            [ev],
            user_agent="TestBot/1",
            log=log,
            cfg=cfg,
        )
        self.assertEqual(out[0].start, "2026-09-01T18:00:00")
        self.assertIn("Hall", out[0].venue or "")

    def test_skips_when_disabled(self) -> None:
        u = "https://example.test/e"
        client = _Client({u: _Resp(200, "<html></html>")})
        ev = DiscoveredEvent(title="Y", url=u, source="t", start=None)
        log = logging.getLogger("t2")
        cfg = {"enrichment": {"enabled": False}}
        enrich_discovered_events(
            client,  # type: ignore[arg-type]
            [ev],
            user_agent="TestBot/1",
            log=log,
            cfg=cfg,
        )
        self.assertEqual(client.get_calls, [])


if __name__ == "__main__":
    unittest.main()
