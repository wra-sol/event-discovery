from __future__ import annotations

import unittest
from datetime import date

from event_discovery.dedupe import dedupe_events
from event_discovery.models import DiscoveredEvent
from event_discovery.scoring import score_event


class TestDedupe(unittest.TestCase):
    def test_dedupes_by_url_title_date(self) -> None:
        a = DiscoveredEvent(title="Foo", url="https://x.com/e/1", source="s")
        b = DiscoveredEvent(title="Foo", url="https://x.com/e/1?utm=1", source="s")
        out = dedupe_events([a, b])
        self.assertEqual(len(out), 1)

    def test_dedupes_recurring_tribe_style_slugs(self) -> None:
        a = DiscoveredEvent(
            title="Things I Can Fold",
            url="https://tourismburlington.ca/event/things-i-can-fold-80/",
            source="tourism_burlington",
            start="2026-04-06 10:00:00",
        )
        b = DiscoveredEvent(
            title="Things I Can Fold",
            url="https://tourismburlington.ca/event/things-i-can-fold-81/",
            source="tourism_burlington",
            start="2026-04-07 10:00:00",
        )
        out = dedupe_events([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].start, "2026-04-06 10:00:00")
        self.assertIn("Merged 2 date-specific listings", out[0].raw_snippet)

    def test_dedupe_key_keeps_year_like_slug_suffix(self) -> None:
        y = DiscoveredEvent(
            title="Gala",
            url="https://example.com/event/winter-gala-2026/",
            source="s",
        )
        self.assertIn("2026", y.dedupe_key())


class TestScoring(unittest.TestCase):
    def test_positive_and_negative(self) -> None:
        ev = DiscoveredEvent(
            title="Burlington community festival",
            url="https://example.com",
            source="t",
            start="2030-06-01 12:00:00",
            raw_snippet="Ward 6 neighbours welcome",
        )
        score_event(
            ev,
            positive_keywords=["community", "festival"],
            negative_keywords=["bootcamp"],
            ward_keywords=["Ward 6"],
            horizon_days=365,
            today=date(2030, 1, 1),
        )
        self.assertGreater(ev.relevance_score, 2.0)
        ev2 = DiscoveredEvent(
            title="CompTIA bootcamp Burlington",
            url="https://example.com/2",
            source="t",
            start="2030-06-01 12:00:00",
        )
        score_event(
            ev2,
            positive_keywords=["Burlington"],
            negative_keywords=["bootcamp", "CompTIA"],
            ward_keywords=["Ward 6"],
            horizon_days=365,
            today=date(2030, 1, 1),
        )
        self.assertLess(ev2.relevance_score, ev.relevance_score)


if __name__ == "__main__":
    unittest.main()
