"""Manual balance snapshots — net worth phase 1.

Endpoints:
- GET  /api/balances                       list recent snapshots (most recent first)
- GET  /api/balances?account_id=N          filter to one account
- POST /api/balances                       upsert by (account_id, as_of_date)
- DELETE /api/balances/{id}                remove a snapshot

POST is upsert-on-conflict: if (account_id, as_of_date) already exists,
the existing row is updated rather than the request being rejected.
This matches the actual user workflow — entering Friday's balance
Saturday morning and realising the number was wrong should let the
user just re-submit, not force a delete-then-insert dance.

The currency field on the snapshot is denormalised from the parent
account at insert time when the request omits it. Storing per-snapshot
currency means historical reads stay correct even if the user later
flips an account's native currency on edit.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.accounts import Account
from app.models.balance_snapshots import BalanceSnapshot
from app.schemas.balance_snapshots import (
    BalanceSnapshotCreate, BalanceSnapshotResponse,
)


router = APIRouter(prefix="/api/balances", tags=["balances"])


def _to_response(snap: BalanceSnapshot) -> BalanceSnapshotResponse:
    resp = BalanceSnapshotResponse.model_validate(snap)
    if snap.account is not None:
        resp.account_name = snap.account.name
        resp.account_kind = snap.account.account_kind
    return resp


@router.get("", response_model=list[BalanceSnapshotResponse])
def list_balances(
    account_id: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(BalanceSnapshot)
    if account_id is not None:
        q = q.filter(BalanceSnapshot.account_id == account_id)
    rows = (
        q.order_by(
            BalanceSnapshot.as_of_date.desc(),
            BalanceSnapshot.created_at.desc(),
        )
        .limit(limit)
        .all()
    )
    return [_to_response(r) for r in rows]


@router.post("", response_model=BalanceSnapshotResponse, status_code=201)
def create_or_update_balance(
    data: BalanceSnapshotCreate, db: Session = Depends(get_db),
):
    account = db.query(Account).filter(Account.id == data.account_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    # Currency falls back to the account's native currency. Stored on
    # the snapshot regardless so it stays correct if the account
    # currency changes later.
    currency = (data.currency or account.currency or "USD").upper()

    existing = (
        db.query(BalanceSnapshot)
        .filter(
            BalanceSnapshot.account_id == data.account_id,
            BalanceSnapshot.as_of_date == data.as_of_date,
        )
        .first()
    )
    if existing is not None:
        existing.balance = data.balance
        existing.currency = currency
        db.commit()
        db.refresh(existing)
        return _to_response(existing)

    snap = BalanceSnapshot(
        account_id=data.account_id,
        as_of_date=data.as_of_date,
        balance=data.balance,
        currency=currency,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return _to_response(snap)


@router.delete("/{snapshot_id}")
def delete_balance(snapshot_id: int, db: Session = Depends(get_db)):
    snap = db.query(BalanceSnapshot).filter(BalanceSnapshot.id == snapshot_id).first()
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    db.delete(snap)
    db.commit()
    return {"message": "Snapshot deleted"}
