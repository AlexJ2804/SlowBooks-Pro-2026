# ============================================================================
# Backup/Restore Service — pg_dump/pg_restore subprocess wrapper
# Feature 11: Database backup and restore accessible from settings
# ============================================================================

import re
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import DATABASE_URL
from app.models.backups import Backup

BACKUP_DIR = Path(__file__).parent.parent.parent / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Matches the exact format create_backup emits: slowbooks_YYYYMMDD_HHMMSS.sql.
# Used as the only allowlist for user-supplied filenames hitting the
# filesystem — anything else (path separators, '..', other extensions) is
# rejected outright before any Path construction.
_BACKUP_FILENAME_RE = re.compile(r"^slowbooks_(\d{8})_(\d{6})\.sql$")


def validate_backup_filename(filename: str) -> str:
    """Return a safe backup filename, or raise ValueError if it doesn't match the allowlist.

    The returned string is *reconstructed* from a constant template plus
    digit-only regex groups, not echoed from the input — so it cannot
    contain path separators, '..', or any other byte that wasn't an ASCII
    digit. CodeQL's py/path-injection dataflow treats this as full
    sanitization (it tracks the value as a new, untainted string).
    """
    if not isinstance(filename, str):
        raise ValueError("Invalid backup filename")
    m = _BACKUP_FILENAME_RE.fullmatch(filename)
    if not m:
        raise ValueError("Invalid backup filename")
    return f"slowbooks_{m.group(1)}_{m.group(2)}.sql"


def _parse_db_url(url: str) -> dict:
    """Parse PostgreSQL connection URL into components."""
    # postgresql://user:pass@host:port/dbname
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "bookkeeper",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/") or "bookkeeper",
    }


def create_backup(db: Session, notes: str = None, backup_type: str = "manual") -> dict:
    """Create a database backup using pg_dump."""
    params = _parse_db_url(DATABASE_URL)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"slowbooks_{timestamp}.sql"
    filepath = BACKUP_DIR / filename

    env = {"PGPASSWORD": params["password"]}

    try:
        result = subprocess.run(
            ["pg_dump", "-h", params["host"], "-p", params["port"],
             "-U", params["user"], "-F", "c", "-f", str(filepath), params["dbname"]],
            env={**dict(__import__("os").environ), **env},
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr}

        file_size = filepath.stat().st_size

        backup = Backup(
            filename=filename, file_size=file_size,
            backup_type=backup_type, notes=notes,
        )
        db.add(backup)
        db.commit()

        return {"success": True, "filename": filename, "file_size": file_size}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Backup timed out"}
    except FileNotFoundError:
        return {"success": False, "error": "pg_dump not found. Is PostgreSQL client installed?"}


def restore_backup(db: Session, filename: str) -> dict:
    """Restore a database from a backup file."""
    try:
        safe_name = validate_backup_filename(filename)
    except ValueError:
        return {"success": False, "error": "Invalid backup filename"}
    filepath = BACKUP_DIR / safe_name
    if not filepath.exists():
        return {"success": False, "error": f"Backup file not found: {safe_name}"}

    params = _parse_db_url(DATABASE_URL)
    env = {"PGPASSWORD": params["password"]}

    try:
        result = subprocess.run(
            ["pg_restore", "-h", params["host"], "-p", params["port"],
             "-U", params["user"], "-d", params["dbname"], "--clean", "--if-exists",
             str(filepath)],
            env={**dict(__import__("os").environ), **env},
            capture_output=True, text=True, timeout=300,
        )
        # pg_restore may return non-zero even on partial success
        if result.returncode != 0 and "error" in result.stderr.lower():
            return {"success": False, "error": result.stderr[:500]}

        return {"success": True, "message": f"Restored from {safe_name}"}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Restore timed out"}
    except FileNotFoundError:
        return {"success": False, "error": "pg_restore not found"}


def list_backup_files() -> list[dict]:
    """List all backup files in the backup directory."""
    files = []
    for f in sorted(BACKUP_DIR.glob("slowbooks_*.sql"), reverse=True):
        files.append({
            "filename": f.name,
            "file_size": f.stat().st_size,
            "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return files
