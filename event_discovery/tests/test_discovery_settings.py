from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from event_discovery.repository import (
    discovery_settings_populated,
    ensure_discovery_seeded,
    get_discovery_settings_bundle,
    merge_config_with_db,
    merge_site_preferences_into_cfg,
    open_connection,
    parse_website_preferences,
    patch_discovery_settings,
    sync_settings_from_config,
)
from event_discovery.schema_migrations import apply_migrations


class TestDiscoverySettings(unittest.TestCase):
    def test_merge_config_prefers_db_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO discovery_settings (key, value_json) VALUES (?, ?)
                    """,
                    (
                        "http",
                        json.dumps(
                            {
                                "user_agent": "DB-Agent/1",
                                "delay_seconds": 9.0,
                                "timeout_seconds": 99.0,
                            }
                        ),
                    ),
                )
                conn.commit()
                cfg = {
                    "http": {
                        "user_agent": "YAML-Agent",
                        "delay_seconds": 0.1,
                        "timeout_seconds": 1.0,
                    },
                    "scoring": {"horizon_days": 5},
                }
                out = merge_config_with_db(cfg, conn)
                self.assertEqual(out["http"]["user_agent"], "DB-Agent/1")
                self.assertEqual(out["http"]["delay_seconds"], 9.0)
                self.assertEqual(out["scoring"]["horizon_days"], 5)
            finally:
                conn.close()

    def test_ensure_seeded_fills_settings_and_websites(self) -> None:
        cfg = {
            "http": {"user_agent": "x", "delay_seconds": 1, "timeout_seconds": 2},
            "scoring": {"horizon_days": 3, "positive_keywords": ["a"]},
            "sources": {
                "one": {
                    "enabled": True,
                    "type": "tribe_rest",
                    "rest_url": "https://example.test/e",
                    "per_page": 1,
                    "max_pages": 1,
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                self.assertFalse(discovery_settings_populated(conn))
                ensure_discovery_seeded(conn, cfg)
                self.assertTrue(discovery_settings_populated(conn))
                out = merge_config_with_db(
                    {"http": {}, "scoring": {}, "sources": {}}, conn
                )
                self.assertEqual(out["http"]["user_agent"], "x")
                self.assertEqual(out["scoring"]["horizon_days"], 3)
            finally:
                conn.close()

    def test_sync_settings_from_config_upserts(self) -> None:
        cfg = {
            "http": {"user_agent": "u2", "delay_seconds": 2, "timeout_seconds": 20},
            "scoring": {"horizon_days": 7},
        }
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                n = sync_settings_from_config(conn, cfg)
                self.assertEqual(n, 2)
                n2 = sync_settings_from_config(
                    conn,
                    {
                        **cfg,
                        "http": {
                            **cfg["http"],
                            "user_agent": "u3",
                        },
                    },
                )
                self.assertEqual(n2, 2)
                merged = merge_config_with_db({}, conn)
                self.assertEqual(merged["http"]["user_agent"], "u3")
            finally:
                conn.close()

    def test_merge_config_prefers_db_enrichment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO discovery_settings (key, value_json) VALUES (?, ?)
                    """,
                    ("enrichment", json.dumps({"enabled": False, "max_urls": 5})),
                )
                conn.commit()
                cfg = {"enrichment": {"enabled": True, "max_urls": 100}}
                out = merge_config_with_db(cfg, conn)
                self.assertFalse(out["enrichment"]["enabled"])
                self.assertEqual(out["enrichment"]["max_urls"], 5)
            finally:
                conn.close()

    def test_get_discovery_settings_bundle_and_patch(self) -> None:
        defaults = {
            "http": {"user_agent": "A", "delay_seconds": 1.0, "timeout_seconds": 45.0},
            "scoring": {"horizon_days": 120, "positive_keywords": ["x"]},
            "enrichment": {"enabled": True, "max_urls": 100},
        }
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "d.db"
            apply_migrations(db)
            conn = open_connection(db)
            try:
                bundle = get_discovery_settings_bundle(conn, defaults)
                self.assertEqual(bundle["http"]["user_agent"], "A")
                self.assertEqual(bundle["scoring"]["horizon_days"], 120)
                patch_discovery_settings(
                    conn,
                    scoring={"horizon_days": 7, "ward_keywords": ["Ward 1"]},
                    enrichment={"enabled": False},
                    defaults_cfg=defaults,
                )
                b2 = get_discovery_settings_bundle(conn, defaults)
                self.assertEqual(b2["scoring"]["horizon_days"], 7)
                self.assertEqual(b2["scoring"]["positive_keywords"], ["x"])
                self.assertEqual(b2["scoring"]["ward_keywords"], ["Ward 1"])
                self.assertFalse(b2["enrichment"]["enabled"])
                self.assertEqual(b2["enrichment"]["max_urls"], 100)
            finally:
                conn.close()

    def test_merge_site_preferences_into_cfg(self) -> None:
        base = {
            "http": {"user_agent": "A", "delay_seconds": 1.0, "timeout_seconds": 45.0},
            "scoring": {
                "horizon_days": 120,
                "positive_keywords": ["p1"],
                "ward_keywords": [],
                "negative_keywords": [],
            },
            "enrichment": {"enabled": True, "max_urls": 100},
        }
        prefs = {"scoring": {"positive_keywords": ["only"]}, "http": {"delay_seconds": 2.5}}
        out = merge_site_preferences_into_cfg(base, prefs)
        self.assertEqual(out["scoring"]["positive_keywords"], ["only"])
        self.assertEqual(out["scoring"]["horizon_days"], 120)
        self.assertEqual(out["http"]["user_agent"], "A")
        self.assertEqual(out["http"]["delay_seconds"], 2.5)

    def test_parse_website_preferences_filters_keys(self) -> None:
        raw = '{"scoring": {"horizon_days": 7}, "other": 1}'
        self.assertEqual(parse_website_preferences(raw)["scoring"]["horizon_days"], 7)
        self.assertNotIn("other", parse_website_preferences(raw))


if __name__ == "__main__":
    unittest.main()
