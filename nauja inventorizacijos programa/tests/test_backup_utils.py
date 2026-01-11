import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import path_setup  # noqa: F401

import backup_utils


class TestBackupUtils(unittest.TestCase):
    def test_create_backup_rotates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "inventory.db"
            db_path.write_text("data1")
            backup_dir = tmp_path / "backups"

            with patch.object(backup_utils, "DB_PATH", db_path), patch.object(
                backup_utils, "BACKUP_DIR", backup_dir
            ):
                first = backup_utils.create_backup(label="t1")
                latest = backup_dir / "inventory-latest.bak"
                prev = backup_dir / "inventory-prev.bak"

                self.assertTrue(first.exists())
                self.assertTrue(latest.exists())
                self.assertFalse(prev.exists())

                db_path.write_text("data2")
                second = backup_utils.create_backup(label="t2")

                self.assertTrue(second.exists())
                self.assertTrue(latest.exists())
                self.assertTrue(prev.exists())
                self.assertEqual(latest.read_text(), "data2")
                self.assertEqual(prev.read_text(), "data1")
