from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.accounts import Account
from app.models.balance_snapshots import BalanceSnapshot
from app.schemas.accounts import AccountCreate, AccountUpdate, AccountResponse
from app.routes._helpers import get_or_404

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _latest_snapshots_by_account(db: Session) -> dict:
    """Return {account_id: BalanceSnapshot} for the most recent snapshot
    per account. One round-trip via a max-date subquery — used by the
    list and single-account endpoints to attach `latest_balance*` fields
    without N+1 queries.
    """
    latest_dates = (
        db.query(
            BalanceSnapshot.account_id.label("aid"),
            func.max(BalanceSnapshot.as_of_date).label("max_date"),
        )
        .group_by(BalanceSnapshot.account_id)
        .subquery()
    )
    rows = (
        db.query(BalanceSnapshot)
        .join(latest_dates, and_(
            BalanceSnapshot.account_id == latest_dates.c.aid,
            BalanceSnapshot.as_of_date == latest_dates.c.max_date,
        ))
        .all()
    )
    return {r.account_id: r for r in rows}


def _to_response(account: Account, latest: BalanceSnapshot = None) -> AccountResponse:
    """Build an AccountResponse, attaching latest snapshot fields when present."""
    resp = AccountResponse.model_validate(account)
    if latest is not None:
        resp.latest_balance = latest.balance
        resp.latest_balance_as_of = latest.as_of_date
        resp.latest_balance_currency = latest.currency
    return resp


@router.get("", response_model=list[AccountResponse])
def list_accounts(
    active_only: bool = False,
    account_type: str = None,
    account_types: str = None,
    account_kind: str = None,
    db: Session = Depends(get_db),
):
    """List accounts.

    `account_type` filters to one QB-coarse type (legacy); `account_types`
    accepts a comma-separated list. `account_kind` filters by the
    finer-grained net-worth dimension (bank/credit_card/etc).

    Each row in the response carries `latest_balance` / `latest_balance_as_of`
    / `latest_balance_currency` from the most recent snapshot, or null when
    the account has no snapshots yet.
    """
    q = db.query(Account)
    if active_only:
        q = q.filter(Account.is_active == True)
    if account_type:
        q = q.filter(Account.account_type == account_type)
    if account_types:
        types = [t.strip() for t in account_types.split(",") if t.strip()]
        if types:
            q = q.filter(Account.account_type.in_(types))
    if account_kind:
        q = q.filter(Account.account_kind == account_kind)
    accounts = q.order_by(Account.account_number).all()
    latest_by_id = _latest_snapshots_by_account(db)
    return [_to_response(a, latest_by_id.get(a.id)) for a in accounts]


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(account_id: int, db: Session = Depends(get_db)):
    account = get_or_404(db, Account, account_id)
    latest = (
        db.query(BalanceSnapshot)
        .filter(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.as_of_date.desc())
        .first()
    )
    return _to_response(account, latest)


@router.post("", response_model=AccountResponse, status_code=201)
def create_account(data: AccountCreate, db: Session = Depends(get_db)):
    account = Account(**data.model_dump(exclude_unset=True))
    db.add(account)
    db.commit()
    db.refresh(account)
    return _to_response(account, None)


@router.put("/{account_id}", response_model=AccountResponse)
def update_account(account_id: int, data: AccountUpdate, db: Session = Depends(get_db)):
    account = get_or_404(db, Account, account_id)
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(account, key, val)
    db.commit()
    db.refresh(account)
    latest = (
        db.query(BalanceSnapshot)
        .filter(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.as_of_date.desc())
        .first()
    )
    return _to_response(account, latest)


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    account = get_or_404(db, Account, account_id)
    if account.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete system account")
    db.delete(account)
    db.commit()
    return {"message": "Account deleted"}
