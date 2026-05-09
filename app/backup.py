import os, zipfile, tempfile, shutil, json
from pathlib import Path
from datetime import datetime
from .config import APP_DIR, BACKUP_DIR

EXCLUDE_DIRS = {"venv", "__pycache__", ".git", "backups"}
EXCLUDE_EXTS = {".pyc", ".log"}

def create_backup_zip():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    name = f"delta-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    path = BACKUP_DIR / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(APP_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                fp = Path(root) / f
                if fp.suffix in EXCLUDE_EXTS:
                    continue
                arc = fp.relative_to(APP_DIR)
                z.write(fp, arc.as_posix())
    return path

def list_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(BACKUP_DIR.glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        items.append({"name": p.name, "size": p.stat().st_size, "mtime": int(p.stat().st_mtime)})
    return items

def restore_backup(fileobj):
    tmp = tempfile.mkdtemp()
    try:
        zpath = Path(tmp) / "restore.zip"
        with open(zpath, "wb") as f:
            shutil.copyfileobj(fileobj, f)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(APP_DIR)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
