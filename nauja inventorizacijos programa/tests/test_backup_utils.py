import backup_utils


def test_create_backup_rotates(tmp_path, monkeypatch):
    db_path = tmp_path / "inventory.db"
    db_path.write_text("data1")
    backup_dir = tmp_path / "backups"

    monkeypatch.setattr(backup_utils, "DB_PATH", db_path)
    monkeypatch.setattr(backup_utils, "BACKUP_DIR", backup_dir)

    first = backup_utils.create_backup(label="t1")
    latest = backup_dir / "inventory-latest.bak"
    prev = backup_dir / "inventory-prev.bak"

    assert first.exists()
    assert latest.exists()
    assert not prev.exists()

    db_path.write_text("data2")
    second = backup_utils.create_backup(label="t2")

    assert second.exists()
    assert latest.exists()
    assert prev.exists()
    assert latest.read_text() == "data2"
    assert prev.read_text() == "data1"
