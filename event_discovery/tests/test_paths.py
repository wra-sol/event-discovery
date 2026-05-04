from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from event_discovery.paths import account_discovery_db_path, maybe_migrate_legacy_flat_discovery_db
from event_discovery.pipeline import load_config


class TestPaths(unittest.TestCase):
    def test_account_discovery_db_path(self) -> None:
        root = Path("/data")
        cfg = load_config(None)
        p = account_discovery_db_path(root, 2, cfg=cfg)
        self.assertEqual(p, Path("/data/accounts/2/discovery.db"))

    def test_maybe_migrate_legacy_moves_flat_db(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        cfg = load_config(None)
        name = "discovery.db"
        legacy = root / name
        legacy.write_bytes(b"sqlite-fake")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCOVERY_DB_PATH", None)
            maybe_migrate_legacy_flat_discovery_db(root, cfg)
        dest = root / "accounts" / "1" / name
        self.assertTrue(dest.is_file())
        self.assertFalse(legacy.exists())
        self.assertEqual(dest.read_bytes(), b"sqlite-fake")


if __name__ == "__main__":
    unittest.main()
