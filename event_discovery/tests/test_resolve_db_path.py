from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from event_discovery.pipeline import load_config, resolve_db_path


class TestResolveDbPath(unittest.TestCase):
    def test_discovery_db_path_env_wins_over_railway_mount(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DISCOVERY_DB_PATH": "/tmp/explicit.db",
                "RAILWAY_VOLUME_MOUNT_PATH": "/railway/vol",
            },
            clear=False,
        ):
            cfg = load_config(None)
            p = resolve_db_path(cfg, Path("/out"))
            self.assertEqual(p, Path("/tmp/explicit.db"))

    def test_railway_volume_mount_fallback(self) -> None:
        clean = dict(os.environ)
        clean.pop("DISCOVERY_DB_PATH", None)
        clean["RAILWAY_VOLUME_MOUNT_PATH"] = "/app/data"
        with patch.dict(os.environ, clean, clear=True):
            cfg = load_config(None)
            p = resolve_db_path(cfg, Path("/out"))
            self.assertEqual(p, Path("/app/data/discovery.db"))

    def test_output_dir_when_no_env(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCOVERY_DB_PATH", None)
            os.environ.pop("RAILWAY_VOLUME_MOUNT_PATH", None)
            cfg = load_config(None)
            p = resolve_db_path(cfg, Path("/var/data"))
            self.assertEqual(p, Path("/var/data/discovery.db"))

    def test_prefers_accounts_1_when_flat_missing(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        acc1_dir = root / "accounts" / "1"
        acc1_dir.mkdir(parents=True)
        (acc1_dir / "discovery.db").write_text("x")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCOVERY_DB_PATH", None)
            os.environ.pop("RAILWAY_VOLUME_MOUNT_PATH", None)
            cfg = load_config(None)
            p = resolve_db_path(cfg, root)
            self.assertEqual(p, acc1_dir / "discovery.db")


if __name__ == "__main__":
    unittest.main()
