from __future__ import annotations

import unittest

from event_discovery.llm_source_discovery import (
    build_prompt,
    format_yaml_suggestion,
    parse_discovery_response,
)


class TestLlmDiscoveryParse(unittest.TestCase):
    def test_parse_raw_json(self) -> None:
        raw = """{
          "recommended_type": "tribe_rest",
          "confidence": 0.9,
          "suggested_config": {"rest_url": "https://x.test/wp-json/tribe/events/v1/events"},
          "evidence": ["wp-json in HTML"],
          "caveats": []
        }"""
        d = parse_discovery_response(raw)
        self.assertEqual(d["recommended_type"], "tribe_rest")
        self.assertEqual(d["confidence"], 0.9)

    def test_parse_fenced_json(self) -> None:
        raw = """Here you go:
```json
{"recommended_type": "unknown", "confidence": 0.1, "suggested_config": {}, "evidence": [], "caveats": ["x"]}
```
"""
        d = parse_discovery_response(raw)
        self.assertEqual(d["recommended_type"], "unknown")

    def test_parse_rejects_bad_type(self) -> None:
        with self.assertRaises(ValueError):
            parse_discovery_response('{"recommended_type": "not_a_real_type"}')

    def test_build_prompt_contains_url(self) -> None:
        p = build_prompt(
            {"url": "https://z.test/e", "status_code": 200, "headers": {}, "body_excerpt": "<html/>"}
        )
        self.assertIn("https://z.test/e", p)
        self.assertIn("<html/>", p)

    def test_format_yaml_suggestion(self) -> None:
        y = format_yaml_suggestion(
            "my_venue",
            {
                "recommended_type": "json_ld_events",
                "suggested_config": {"page_url": "https://cal.test/"},
            },
        )
        self.assertIn("my_venue:", y)
        self.assertIn("json_ld_events", y)
        self.assertIn("page_url", y)


if __name__ == "__main__":
    unittest.main()
