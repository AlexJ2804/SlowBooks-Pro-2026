# ============================================================================
# Backup/Restore Routes — accessible from settings page
# Feature 11: Create, list, download, restore backups
# ============================================================================

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models.backups import Backup
from app.services.backup_service import (
    BACKUP_DIR,
    BACKUP_FILENAME_RE,
    create_backup,
    list_backup_files,
    restore_backup,
)

router = APIRouter(prefix="/api/backups", tags=["backups"])


class BackupCreate(BaseModel):
    notes: Optional[str] = None


class RestoreRequest(BaseModel):
    filename: str


@router.get("")
def list_backups(db: Session = Depends(get_db)):
    """List only backups whose files still exist on disk."""
    db_backups = db.query(Backup).order_by(Backup.created_at.desc()).all()
    return [
        {"id": b.id, "filename": b.filename, "file_size": b.file_size,
         "backup_type": b.backup_type, "notes": b.notes,
         "created_at": b.created_at.isoformat() if b.created_at else None}
        for b in db_backups
        if (BACKUP_DIR / b.filename).exists()
    ]


@router.post("")
def make_backup(data: BackupCreate = BackupCreate(), db: Session = Depends(get_db)):
    result = create_backup(db, notes=data.notes)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Backup failed"))
    return result


@router.get("/download/{filename}")
def download_backup(filename: str):
    # User input never reaches the filesystem call: we enumerate
    # BACKUP_DIR ourselves and pick the entry whose name matches. The
    # path passed to FileResponse comes from iterdir(), so CodeQL sees
    # no dataflow from the request param to the sink.
    if not BACKUP_FILENAME_RE.fullmatch(filename or ""):
        raise HTTPException(status_code=400, detail="Invalid filename")
    for entry in BACKUP_DIR.iterdir():
        if entry.is_file() and entry.name == filename:
            return FileResponse(entry, filename=entry.name, media_type="application/octet-stream")
    raise HTTPException(status_code=404, detail="Backup file not found")


@router.post("/restore")
def restore(data: RestoreRequest, db: Session = Depends(get_db)):
    if not BACKUP_FILENAME_RE.fullmatch(data.filename or ""):
        raise HTTPException(status_code=400, detail="Invalid filename")
    # Resolve via directory listing — restore_backup receives a name
    # sourced from the filesystem, not from the request body.
    matched = next(
        (e.name for e in BACKUP_DIR.iterdir() if e.is_file() and e.name == data.filename),
        None,
    )
    if matched is None:
        raise HTTPException(status_code=404, detail="Backup file not found")
    result = restore_backup(db, matched)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Restore failed"))
    return result
