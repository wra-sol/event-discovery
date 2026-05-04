from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from event_discovery.models import DiscoveredEvent
from event_discovery.pipeline import score_all
from event_discovery.repository import open_connection, patch_website
from event_discovery.schema_migrations import apply_migrations


class TestPerSiteScoring(unittest.TestCase):
    def test_score_all_uses_website_preferences(self) -> None:
        cfg = {
            "scoring": {
                "horizon_days": 120,
                "positive_keywords": ["global"],
                "ward_keywords": [],
                "negative_keywords": [],
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO websites (source_key, enabled, type, config_json, display_order)
                    VALUES ('s1', 1, 'tribe_rest', '{}', 0)
                    """
                )
                wid = int(cur.lastrowid)
                conn.commit()
                patch_website(
                    conn,
                    wid,
                    preferences={
                        "scoring": {"positive_keywords": ["override"], "ward_keywords": []}
                    },
                )
                ev1 = DiscoveredEvent(
                    title="override",
                    url="https://ex.test/a",
                    source="s1",
                    website_id=wid,
                    start="2026-06-15",
                    relevance_score=0.0,
                )
                ev2 = DiscoveredEvent(
                    title="global",
                    url="https://ex.test/b",
                    source="yaml",
                    website_id=None,
                    start="2026-06-15",
                    relevance_score=0.0,
                )
                out = score_all([ev1, ev2], cfg, date(2026, 4, 1), website_conn=conn)
                by_url = {e.url: e for e in out}
                self.assertIn("keyword:override", " ".join(by_url["https://ex.test/a"].relevance_reasons))
                self.assertIn("keyword:global", " ".join(by_url["https://ex.test/b"].relevance_reasons))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
