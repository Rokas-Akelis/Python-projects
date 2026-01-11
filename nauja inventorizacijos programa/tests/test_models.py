import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

import path_setup  # noqa: F401

import models


class TestModels(unittest.TestCase):
    def test_get_session_creates_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "db.sqlite"
            session = models.get_session(db_path=f"sqlite:///{db_path}")
            try:
                session.execute(text("SELECT 1"))
            finally:
                session.close()
                bind = getattr(session, "bind", None)
                if bind is not None:
                    bind.dispose()
            self.assertTrue(db_path.exists())
