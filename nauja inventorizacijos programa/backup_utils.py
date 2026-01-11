from pathlib import Path
import os
import shutil
import tempfile
import time

from models import get_default_db_path

BASE_DIR = Path(__file__).parent
DB_PATH = get_default_db_path()


def _resolve_backup_dir() -> Path:
    env_dir = os.getenv("INVENTORY_BACKUP_DIR")
    if env_dir:
        return Path(env_dir)
    base_dir = DB_PATH.parent
    if not os.access(base_dir, os.W_OK):
        base_dir = Path(tempfile.gettempdir())
    return base_dir / "backups"


BACKUP_DIR = _resolve_backup_dir()


def ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    return BACKUP_DIR


def create_backup(label: str = "") -> Path | None:
    """
    Sukuria DB kopiją backups/ kataloge.
    Grąžina sukurtos kopijos kelią, arba None jei DB dar nesukurta.
    """
    ensure_backup_dir()
    if not DB_PATH.exists():
        return None
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    target = BACKUP_DIR / f"inventory{suffix}-{timestamp}.bak"
    shutil.copy2(DB_PATH, target)

    # rotuojame "latest" -> "prev", kad turėtume dvi naujausias
    latest = BACKUP_DIR / "inventory-latest.bak"
    prev = BACKUP_DIR / "inventory-prev.bak"
    if latest.exists():
        latest.replace(prev)
    shutil.copy2(DB_PATH, latest)

    return target
