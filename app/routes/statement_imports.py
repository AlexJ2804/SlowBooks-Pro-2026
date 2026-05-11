# ============================================================================
# Statement imports — upload PDF bank/CC statements, vision-parse them,
# preview the transactions, and post into bank_transactions.
# Phase 2: PDF statement ingestion pipeline (issue #1).
# ============================================================================
# Lifecycle:
#   POST  /upload/{bank_account_id}      -> creates row (status='pending')
#                                           hashes, dedups, saves PDF, parses,
#                                           returns {import, parsed} or 409
#   GET   /                              -> list (paginated by query param)
#   GET   /{id}                          -> import + parsed transactions
#   GET   /{id}/pdf                      -> serve the source PDF
#   POST  /{id}/post                     -> materialise into bank_transactions
#   DELETE /{id}                         -> remove row + PDF (file FK is
#                                           SET NULL on bank_transactions, so
#                                           drill-back disappears but rows stay)
#
# Why parse synchronously inside /upload: a Sonnet 4.6 statement parse is
# ~30-60s. That's well within FastAPI's response budget and matches the
# UX of /api/receipts/parse. If statements grow to >2 minutes routinely,
# move parsing to APScheduler with a "parsing" status that the frontend
# polls — for the 5-15-page statements we ingest today, sync is simpler.
# ============================================================================

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.accounts import Account
from app.models.balance_snapshots import BalanceSnapshot
from app.models.banking import BankAccount, BankTransaction
from app.models.statement_imports import StatementImport
from app.routes.settings import _get_all as get_settings
from app.services import statement_parser


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/statement-imports", tags=["statement_imports"])


STATIC_BASE = (Path(__file__).parent.parent / "static").resolve()
UPLOAD_BASE = (STATIC_BASE / "uploads" / "statements").resolve()

# Same character whitelist + cap as attachments. Statements come from
# users uploading their bank's exported PDFs, so filenames carry
# arbitrary punctuation; we sanitise hard.
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9 ._()\-]")
_MAX_PDF_BYTES = 32 * 1024 * 1024

# Cross-statement dedup key. Credit-card statements list transactions by
# the card-swipe date, and consecutive cycles often overlap by a few
# days at the boundary — a Feb 26 Wal-Mart charge can appear in both
# the February statement (transaction-date column) and the March
# statement (because it posted in March). Without this, posting two
# adjacent statements would duplicate the boundary rows. The key is
# (date, signed amount to 2dp, normalised description prefix). Same
# normalisation rule lives in the cleanup SQL so the two paths agree.
_DEDUP_DESC_LEN = 40
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def _normalize_description(desc: Optional[str]) -> str:
    if not desc:
        return ""
    return _NON_ALNUM_RE.sub("", desc.lower())[:_DEDUP_DESC_LEN]


def _dedup_key(tx_date, amount: float, description: Optional[str]) -> tuple:
    # Two-decimal string so float drift doesn't break equality.
    return (tx_date, f"{float(amount):.2f}", _normalize_description(description))


def _upsert_snapshot_from_statement(db: Session, si: StatementImport, parsed: dict) -> bool:
    """Write a balance_snapshot from a parsed statement, if possible.

    Conditions to write:
      * bank_account is linked to a COA account_id
      * parsed.statement.closing_balance is a number
      * statement period_end is known

    Sign convention: closing_balance is stored verbatim. The COA account's
    `account_kind` determines whether net_worth.py flips the sign at
    sum-time (credit_card / loan are flipped to negative contributions).
    So a Citi statement with closing_balance = $1,234.56 lands as a
    +1234.56 snapshot, and the net-worth dashboard renders it as
    -$1,234.56 owed automatically.

    Returns True if a snapshot was written/updated, False otherwise.
    Failure to write is non-fatal — the caller commits bank_transactions
    regardless. We surface success in the /post response so the user
    knows whether their Net Worth was just refreshed.
    """
    ba = db.query(BankAccount).filter(BankAccount.id == si.bank_account_id).first()
    if not ba or not ba.account_id:
        return False

    header = (parsed or {}).get("statement") or {}
    closing = header.get("closing_balance")
    if closing is None:
        return False
    if not si.period_end:
        return False

    coa = db.query(Account).filter(Account.id == ba.account_id).first()
    if not coa:
        return False
    currency = (coa.currency or "USD").upper()

    existing = (
        db.query(BalanceSnapshot)
        .filter(
            BalanceSnapshot.account_id == ba.account_id,
            BalanceSnapshot.as_of_date == si.period_end,
        )
        .first()
    )
    if existing:
        existing.balance = closing
        existing.currency = currency
    else:
        db.add(BalanceSnapshot(
            account_id=ba.account_id,
            as_of_date=si.period_end,
            balance=closing,
            currency=currency,
        ))
    return True


def _sanitize_filename(raw: str) -> str:
    base = Path(raw or "").name
    if not base or base.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip()
    if not cleaned or cleaned.startswith(".") or "/" in cleaned or "\\" in cleaned:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return cleaned


def _resolve_within(base: Path, *parts: str) -> Path:
    candidate = base.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    return candidate


def _serialise_import(si: StatementImport) -> dict:
    return {
        "id": si.id,
        "bank_account_id": si.bank_account_id,
        "period_start": si.period_start.isoformat() if si.period_start else None,
        "period_end": si.period_end.isoformat() if si.period_end else None,
        "source_pdf_path": si.source_pdf_path,
        "content_hash": si.content_hash,
        "file_size": si.file_size,
        "vision_model": si.vision_model,
        "vision_cost_cents": si.vision_cost_cents,
        "input_tokens": si.input_tokens,
        "output_tokens": si.output_tokens,
        "status": si.status,
        "error_message": si.error_message,
        "uploaded_at": si.uploaded_at.isoformat() if si.uploaded_at else None,
        "parsed_at": si.parsed_at.isoformat() if si.parsed_at else None,
        "posted_at": si.posted_at.isoformat() if si.posted_at else None,
    }


def _parsed_payload(si: StatementImport) -> Optional[dict]:
    """Decode raw_response_json into the {statement, transactions} payload
    the parser produced. Returns None if the row never finished parsing or
    the JSON is missing/malformed."""
    if not si.raw_response_json:
        return None
    try:
        return json.loads(si.raw_response_json)
    except json.JSONDecodeError:
        return None


@router.post("/upload/{bank_account_id}", status_code=201)
async def upload_statement(
    bank_account_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a PDF statement, dedup, parse, and return the preview.

    Re-uploading a PDF whose SHA-256 matches an existing import returns
    409 with a pointer to the original import — same idempotency idea as
    the OFX importer's FITID-based dedup, scoped to the whole PDF since
    a statement is one atomic blob.
    """
    ba = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
    if not ba:
        raise HTTPException(status_code=404, detail="Bank account not found")

    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type {file.content_type}. Use application/pdf.",
        )

    content = await file.read()
    if len(content) > _MAX_PDF_BYTES:
        size_mb = len(content) // 1024 // 1024
        raise HTTPException(
            status_code=413,
            detail=f"PDF is {size_mb} MB; max is {_MAX_PDF_BYTES // 1024 // 1024} MB",
        )

    content_hash = hashlib.sha256(content).hexdigest()

    existing = (
        db.query(StatementImport)
        .filter(StatementImport.content_hash == content_hash)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This PDF was already imported.",
                "existing_import_id": existing.id,
                "existing_uploaded_at": existing.uploaded_at.isoformat() if existing.uploaded_at else None,
                "existing_status": existing.status,
            },
        )

    settings = get_settings(db)
    if not settings.get("anthropic_api_key"):
        raise HTTPException(
            status_code=400,
            detail="Anthropic API key is not configured. Add it in Settings → Receipt Parsing.",
        )

    safe_filename = _sanitize_filename(file.filename or "statement.pdf")
    if not safe_filename.lower().endswith(".pdf"):
        safe_filename = f"{safe_filename}.pdf"

    # Lay PDFs out as uploads/statements/<bank_account_id>/<timestamp>-<file>.
    # Timestamp prefix avoids collisions when two statements share a name
    # within the same bank_account folder.
    upload_dir = _resolve_within(UPLOAD_BASE, str(bank_account_id))
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamped = f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{safe_filename}"
    file_path = _resolve_within(upload_dir, stamped)
    file_path.write_bytes(content)

    # Persist the row in pending state BEFORE calling the API so that a
    # crash mid-parse leaves a recoverable trail (status='pending' rows
    # can be retried via a future /reparse endpoint).
    si = StatementImport(
        bank_account_id=bank_account_id,
        source_pdf_path=str(file_path.relative_to(STATIC_BASE)),
        content_hash=content_hash,
        file_size=len(content),
        status="parsing",
    )
    db.add(si)
    db.commit()
    db.refresh(si)

    result = statement_parser.parse_statement(content, settings)

    si.vision_model = result.get("model")
    si.input_tokens = result.get("input_tokens")
    si.output_tokens = result.get("output_tokens")
    si.vision_cost_cents = result.get("cost_cents")

    parsed = result.get("parsed")
    if parsed is None:
        si.status = "failed"
        si.error_message = result.get("error") or "Unknown parse failure"
        # Stash raw model text for debugging when the JSON shape was bad.
        si.raw_response_json = result.get("raw_text")
        db.commit()
        return {"import": _serialise_import(si), "parsed": None}

    # Hydrate period dates from the parsed header so the list view can
    # show "Statement period: Apr 1 – Apr 30" without re-parsing.
    header = parsed.get("statement") or {}
    period_start_str = header.get("period_start")
    period_end_str = header.get("period_end")
    try:
        si.period_start = datetime.strptime(period_start_str, "%Y-%m-%d").date() if period_start_str else None
    except ValueError:
        si.period_start = None
    try:
        si.period_end = datetime.strptime(period_end_str, "%Y-%m-%d").date() if period_end_str else None
    except ValueError:
        si.period_end = None

    si.raw_response_json = json.dumps(parsed)
    si.status = "parsed"
    si.parsed_at = datetime.utcnow()
    si.error_message = None
    db.commit()
    db.refresh(si)

    return {"import": _serialise_import(si), "parsed": parsed}


@router.get("/")
def list_imports(
    bank_account_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(StatementImport)
    if bank_account_id is not None:
        q = q.filter(StatementImport.bank_account_id == bank_account_id)
    if status is not None:
        q = q.filter(StatementImport.status == status)
    rows = q.order_by(StatementImport.uploaded_at.desc()).limit(min(limit, 200)).all()
    return [_serialise_import(r) for r in rows]


@router.get("/{import_id}")
def get_import(import_id: int, db: Session = Depends(get_db)):
    si = db.query(StatementImport).filter(StatementImport.id == import_id).first()
    if not si:
        raise HTTPException(status_code=404, detail="Statement import not found")
    return {"import": _serialise_import(si), "parsed": _parsed_payload(si)}


@router.get("/{import_id}/pdf")
def download_pdf(import_id: int, db: Session = Depends(get_db)):
    si = db.query(StatementImport).filter(StatementImport.id == import_id).first()
    if not si:
        raise HTTPException(status_code=404, detail="Statement import not found")
    file_path = _resolve_within(STATIC_BASE, si.source_pdf_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Source PDF missing on disk")
    return FileResponse(
        str(file_path),
        filename=Path(si.source_pdf_path).name,
        media_type="application/pdf",
    )


@router.post("/{import_id}/post")
def post_import(import_id: int, db: Session = Depends(get_db)):
    """Materialise parsed transactions into bank_transactions.

    Cross-statement dedup: each candidate row is fingerprinted as
    (date, signed amount, normalised description) and skipped if a row
    with the same fingerprint already exists on this bank_account.
    This handles the Citi/Chase pattern where consecutive monthly
    statements overlap by a few transaction-date days at the cycle
    boundary, so the same Wal-Mart charge appearing in both PDFs only
    lands once in the register. See _dedup_key for the matching rule.

    Posting an already-posted import is a no-op (returns the existing
    count rather than duplicating rows).
    """
    si = db.query(StatementImport).filter(StatementImport.id == import_id).first()
    if not si:
        raise HTTPException(status_code=404, detail="Statement import not found")
    if si.status not in ("parsed", "posted"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot post import with status '{si.status}'. Must be 'parsed'.",
        )
    if si.status == "posted":
        existing_count = (
            db.query(BankTransaction)
            .filter(BankTransaction.statement_import_id == si.id)
            .count()
        )
        return {
            "import": _serialise_import(si),
            "created_count": 0,
            "existing_count": existing_count,
            "message": "Already posted",
        }

    parsed = _parsed_payload(si)
    if parsed is None:
        raise HTTPException(
            status_code=400,
            detail="Parsed payload missing or malformed; cannot post.",
        )

    # Pre-load every existing row on this bank_account into a fingerprint
    # set. One query instead of N inside the loop. For an account with
    # tens of thousands of rows this is still cheap; revisit with a
    # composite index on (bank_account_id, date, amount) if it stops
    # being.
    existing_keys = {
        _dedup_key(row.date, float(row.amount), row.description or row.payee)
        for row in (
            db.query(
                BankTransaction.date,
                BankTransaction.amount,
                BankTransaction.description,
                BankTransaction.payee,
            )
            .filter(BankTransaction.bank_account_id == si.bank_account_id)
            .all()
        )
    }

    transactions = parsed.get("transactions") or []
    created = 0
    duplicates = 0
    for idx, tx in enumerate(transactions):
        try:
            tx_date = datetime.strptime(tx["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        amount = tx.get("amount")
        if amount is None:
            continue
        key = _dedup_key(tx_date, amount, tx.get("description"))
        if key in existing_keys:
            duplicates += 1
            continue
        bt = BankTransaction(
            bank_account_id=si.bank_account_id,
            date=tx_date,
            amount=amount,
            payee=(tx.get("description") or "")[:200],
            description=tx.get("description"),
            check_number=tx.get("check_number"),
            import_id=f"{si.id}:{idx}",
            import_source="pdf",
            match_status="unmatched",
            statement_import_id=si.id,
        )
        db.add(bt)
        # Also dedup within this batch — guards against a PDF that lists
        # the same transaction twice in its own pages (rare but seen on
        # corrected statements).
        existing_keys.add(key)
        created += 1

    si.status = "posted"
    si.posted_at = datetime.utcnow()

    # Auto-write a balance_snapshot from the parsed statement's
    # closing_balance, if the bank_account is linked to a COA row.
    # Lets the Net Worth dashboard reflect this statement's ending
    # balance with no manual /#/balances entry. Atomic with the
    # bank_transactions write since both go through the same commit.
    snapshot_written = _upsert_snapshot_from_statement(db, si, parsed)

    db.commit()
    db.refresh(si)

    return {
        "import": _serialise_import(si),
        "created_count": created,
        "duplicate_count": duplicates,
        "invalid_count": len(transactions) - created - duplicates,
        "snapshot_written": snapshot_written,
    }


@router.delete("/{import_id}")
def delete_import(import_id: int, db: Session = Depends(get_db)):
    """Remove the import row and the source PDF.

    Posted bank_transactions stay (FK is ON DELETE SET NULL); the
    drill-back link just goes away. This matches user expectation:
    once you've reconciled the rows, deleting the source PDF
    shouldn't blow up your register.
    """
    si = db.query(StatementImport).filter(StatementImport.id == import_id).first()
    if not si:
        raise HTTPException(status_code=404, detail="Statement import not found")

    file_path = _resolve_within(STATIC_BASE, si.source_pdf_path)
    try:
        file_path.unlink()
    except FileNotFoundError:
        pass

    db.delete(si)
    db.commit()
    return {"status": "deleted"}
