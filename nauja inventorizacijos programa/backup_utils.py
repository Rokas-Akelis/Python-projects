from pathlib import Path
import os
import shutil
import tempfile
import time

from models import get_default_db_path

BASE_DIR = Path(__file__).parent
DB_PATH = get_default_db_path()
BACKUP_ROOT = BASE_DIR / "backup"
LEGACY_BACKUP_ROOT = BASE_DIR / "backups"


def get_db_path() -> Path:
    env_path = os.getenv("INVENTORY_DB_PATH")
    if env_path:
        return Path(env_path)
    return get_default_db_path()


def _resolve_backup_dir(db_path: Path | None = None) -> Path:
    env_dir = os.getenv("INVENTORY_BACKUP_DIR")
    if env_dir:
        return Path(env_dir)
    base_dir = BACKUP_ROOT
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if not os.access(base_dir, os.W_OK):
        db_path = db_path or get_db_path()
        base_dir = db_path.parent
        if not os.access(base_dir, os.W_OK):
            base_dir = Path(tempfile.gettempdir())
    return base_dir


def get_backup_dir(db_path: Path | None = None) -> Path:
    return _resolve_backup_dir(db_path)


BACKUP_DIR = get_backup_dir()


def _migrate_legacy_backups(target_dir: Path) -> None:
    if LEGACY_BACKUP_ROOT == target_dir:
        return
    if not LEGACY_BACKUP_ROOT.exists():
        return
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    for item in LEGACY_BACKUP_ROOT.glob("inventory*.bak"):
        try:
            dest = target_dir / item.name
            if dest.exists():
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                dest = target_dir / f"{item.stem}-migrated-{timestamp}{item.suffix}"
            shutil.move(str(item), str(dest))
        except Exception:
            continue


def ensure_backup_dir(db_path: Path | None = None) -> Path:
    backup_dir = get_backup_dir(db_path)
    _migrate_legacy_backups(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_backup(label: str = "", db_path: Path | None = None, backup_dir: Path | None = None) -> Path | None:
    """
    Sukuria DB kopija backup/ kataloge.
    Grazina sukurtos kopijos kelia, arba None jei DB dar nesukurta.
    """
    db_path = db_path or get_db_path()
    backup_dir = backup_dir or ensure_backup_dir(db_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        return None
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    target = backup_dir / f"inventory{suffix}-{timestamp}.bak"
    shutil.copy2(db_path, target)

    # rotuojame "latest" -> "prev", kad turėtume dvi naujausias
    latest = backup_dir / "inventory-latest.bak"
    prev = backup_dir / "inventory-prev.bak"
    if latest.exists():
        latest.replace(prev)
    shutil.copy2(db_path, latest)

    return target


def list_backups(db_path: Path | None = None) -> list[Path]:
    backup_dir = get_backup_dir(db_path)
    _migrate_legacy_backups(backup_dir)
    if not backup_dir.exists():
        return []
    return sorted(
        backup_dir.glob("inventory*.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def restore_backup(backup_path: Path | str, db_path: Path | None = None) -> Path:
    db_path = db_path or get_db_path()
    backup_path = Path(backup_path)
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup failas nerastas: {backup_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, db_path)
    return db_path
