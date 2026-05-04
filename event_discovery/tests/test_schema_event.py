from __future__ import annotations

import json
import unittest
from datetime import date

from event_discovery.schema_event import extract_event_fields_from_html, sanitize_embedded_json_ld
from event_discovery.sources.spaces import _parse_spaces_date_text


class TestSchemaEventExtract(unittest.TestCase):
    def test_ld_json_event_start_venue(self) -> None:
        ev = {
            "@context": "https://schema.org",
            "@type": "Event",
            "name": "Concert",
            "startDate": "2026-08-01T19:00:00-04:00",
            "endDate": "2026-08-01T21:00:00-04:00",
            "location": {
                "@type": "Place",
                "name": "Town Hall",
                "address": {"streetAddress": "1 Main St"},
            },
        }
        raw = json.dumps(ev)
        html = f'<html><script type="application/ld+json">{raw}</script></html>'
        fields = extract_event_fields_from_html(html)
        self.assertEqual(fields["start"], "2026-08-01T19:00:00-04:00")
        self.assertEqual(fields["end"], "2026-08-01T21:00:00-04:00")
        self.assertIn("Town Hall", fields["venue"])


class TestSpacesDateParse(unittest.TestCase):
    def test_iso_date(self) -> None:
        ref = date(2026, 4, 1)
        self.assertEqual(_parse_spaces_date_text("2026-05-10", ref), "2026-05-10")

    def test_month_day_with_year(self) -> None:
        ref = date(2026, 4, 1)
        self.assertEqual(_parse_spaces_date_text("Apr 15, 2026", ref), "2026-04-15")

    def test_month_day_infer_year(self) -> None:
        ref = date(2026, 4, 1)
        self.assertEqual(_parse_spaces_date_text("Jun 10", ref), "2026-06-10")


class TestSanitizeReexport(unittest.TestCase):
    def test_newlines(self) -> None:
        raw = '{"a": "x\ny"}'
        clean = sanitize_embedded_json_ld(raw)
        data = json.loads(clean)
        self.assertEqual(data["a"], "x y")


if __name__ == "__main__":
    unittest.main()
