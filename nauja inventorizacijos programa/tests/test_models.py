import models
from sqlalchemy import text


def test_get_session_creates_db(tmp_path):
    db_path = tmp_path / "db.sqlite"
    session = models.get_session(db_path=f"sqlite:///{db_path}")
    session.execute(text("SELECT 1"))
    session.close()
    assert db_path.exists()
