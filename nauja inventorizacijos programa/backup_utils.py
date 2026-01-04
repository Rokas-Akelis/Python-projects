from pathlib import Path
import shutil
import time

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "inventory.db"
BACKUP_DIR = BASE_DIR / "backups"


def ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    return BACKUP_DIR


def create_backup(label: str = "") -> Path:
    """
    Sukuria DB kopiją backups/ kataloge.
    Grąžina sukurtos kopijos kelią.
    """
    ensure_backup_dir()
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
