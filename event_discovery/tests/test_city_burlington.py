from __future__ import annotations

import json
import unittest

from event_discovery.schema_event import sanitize_embedded_json_ld


class TestSanitizeLdJson(unittest.TestCase):
    def test_unescaped_newline_in_string(self) -> None:
        raw = '{"a": "line1\nline2", "b": 1}'
        clean = sanitize_embedded_json_ld(raw)
        data = json.loads(clean)
        self.assertEqual(data["a"], "line1 line2")

    def test_preserves_escaped_quote(self) -> None:
        raw = r'{"a": "say \"hi\""}'
        clean = sanitize_embedded_json_ld(raw)
        data = json.loads(clean)
        self.assertEqual(data["a"], 'say "hi"')


if __name__ == "__main__":
    unittest.main()
