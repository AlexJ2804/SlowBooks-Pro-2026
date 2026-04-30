# ============================================================================
# Receipt parsing route — upload a receipt image/PDF, run vision parsing,
# return structured fields + a short-lived token so the frontend can attach
# the original bytes to the resulting bill if the user actually saves it.
#
# All Anthropic-side errors (timeout, 401, malformed JSON) come back as
# {"parsed": null, "error": "..."} with HTTP 200 from /parse — the
# frontend can show "we couldn't read this receipt" without exception
# handling. HTTP 4xx is reserved for user-correctable problems (feature
# disabled, missing key, oversized, wrong MIME).
#
# Privacy:
# - Receipt bytes are held in a process-local in-memory store with a
#   10-minute TTL (see app.services.receipt_token_store). They never
#   touch disk via this route. They only persist if /attach is called
#   for a real bill, which routes them through the existing Attachments
#   storage path (app.routes.attachments).
# - File contents and API key are never logged.
# ============================================================================

import os
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.bills import Bill
from app.models.attachments import Attachment
from app.routes.settings import _get_all as get_settings, _set as set_setting
from app.services import receipt_parser, receipt_token_store


router = APIRouter(prefix="/api/receipts", tags=["receipts"])


_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


def _current_month_key() -> str:
    """e.g. receipts_parsed_count_202604"""
    return f"receipts_parsed_count_{datetime.utcnow().strftime('%Y%m')}"


def _increment_parse_counter(db: Session) -> None:
    """Bump the current-month parse counter. Best-effort — a failure here
    must not turn a successful parse into an error response."""
    try:
        from app.models.settings import Settings
        key = _current_month_key()
        row = db.query(Settings).filter(Settings.key == key).first()
        if row:
            try:
                row.value = str(int(row.value) + 1)
            except (TypeError, ValueError):
                row.value = "1"
        else:
            db.add(Settings(key=key, value="1"))
        db.commit()
    except Exception:
        db.rollback()


@router.post("/parse")
async def parse_receipt(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    settings = get_settings(db)

    if str(settings.get("receipt_parser_enabled", "false")).lower() != "true":
        raise HTTPException(status_code=403, detail="Receipt parsing is disabled in settings")

    if not settings.get("anthropic_api_key"):
        raise HTTPException(
            status_code=400,
            detail="Anthropic API key is not configured. Add it in Settings → Receipt Parsing.",
        )

    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type {file.content_type}. Use JPEG, PNG, WebP, or PDF.",
        )

    try:
        max_mb = int(settings.get("receipt_parser_max_file_size_mb") or 10)
    except (TypeError, ValueError):
        max_mb = 10
    max_bytes = max_mb * 1024 * 1024

    # Read into a NamedTemporaryFile so we never keep large bytes in
    # memory longer than necessary. Always cleaned up via try/finally.
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "").suffix)
    try:
        size = 0
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {max_mb} MB limit configured in Settings.",
                )
            tmp.write(chunk)
        tmp.flush()
        tmp.close()
        file_bytes = Path(tmp.name).read_bytes()
    except HTTPException:
        raise
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass

    result = receipt_parser.parse_receipt(file_bytes, file.content_type, settings)

    # Stash bytes for a possible later /attach. We do this regardless of
    # parse success — even if parsing failed, the user might choose to
    # fall back to manual entry while still attaching the original image.
    token = receipt_token_store.put(file_bytes, file.content_type)

    if result.get("parsed") is not None:
        _increment_parse_counter(db)

    return {
        "parsed": result.get("parsed"),
        "error": result.get("error"),
        "attachment_token": token,
        "filename": file.filename or "receipt",
    }


@router.post("/attach")
def attach_receipt_to_bill(
    bill_id: int = Form(...),
    attachment_token: str = Form(...),
    db: Session = Depends(get_db),
):
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    entry = receipt_token_store.get(attachment_token)
    if entry is None:
        # Token never existed, expired, or was already used. Treat as gone.
        raise HTTPException(
            status_code=410,
            detail="Receipt upload token has expired or already been used. "
                   "Re-upload the receipt as an attachment from the bill's view page.",
        )

    file_bytes, mime_type = entry

    # Reuse the existing Attachments storage layout. We mirror the
    # path/filename sanitisation from app/routes/attachments.py so the
    # file lands in the same place as a manual upload would.
    from app.routes.attachments import (
        _ENTITY_TYPE_DIRS, _resolve_within, UPLOAD_BASE, STATIC_BASE
    )

    type_dir = _ENTITY_TYPE_DIRS["bill"]  # known-safe constant
    upload_dir = _resolve_within(UPLOAD_BASE, type_dir, str(bill.id))
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(mime_type, "")
    safe_filename = f"receipt-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}{ext}"
    file_path = _resolve_within(upload_dir, safe_filename)
    file_path.write_bytes(file_bytes)

    attachment = Attachment(
        entity_type="bill",
        entity_id=bill.id,
        filename=safe_filename,
        file_path=str(file_path.relative_to(STATIC_BASE)),
        mime_type=mime_type,
        file_size=len(file_bytes),
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    receipt_token_store.invalidate(attachment_token)

    return {
        "attachment_id": attachment.id,
        "filename": attachment.filename,
    }
