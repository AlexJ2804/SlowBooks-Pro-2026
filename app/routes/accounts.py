from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.accounts import Account
from app.models.balance_snapshots import BalanceSnapshot
from app.models.people import AccountOwnership, Person
from app.schemas.accounts import AccountCreate, AccountUpdate, AccountResponse
from app.schemas.people import OwnershipShareIn
from app.routes._helpers import get_or_404

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


# ---------------------------------------------------------------------------
# Phase 1.5 dual-write helpers.
#
# During the dual-write window (lasting ~1 week between migration
# j2a3b4c5d6e7 and the legacy-column drop), every ownership change
# touches both the new account_ownerships rows and the legacy
# alex_pct/alexa_pct/kids_pct columns. Reads come from the join only.
#
# The legacy columns map to fixed person_ids:
#     alex_pct  -> person_id 1 (Alex)
#     alexa_pct -> person_id 2 (Alexa)
#     kids_pct  -> person_id 3 (Theodore)
#
# Ownership rows referencing person_ids outside {1, 2, 3} (e.g. a
# future second child) are still written to the join table but do not
# round-trip into the legacy columns — those columns can't represent
# them. That's intentional: the legacy columns are deprecated and on
# their way out, so no work goes into making them more flexible.
# ---------------------------------------------------------------------------

_LEGACY_PCT_BY_PERSON_ID = {1: "alex_pct", 2: "alexa_pct", 3: "kids_pct"}


def _replace_ownerships(db: Session, account: Account,
                        rows: List[OwnershipShareIn]) -> None:
    """Replace all ownership rows for an account in one transaction.

    Pydantic has already validated the row set (positive shares,
    no duplicate person_ids, sum=100 or empty). The DB-level deferred
    trigger catches anything raw-SQL inserts smuggle in.

    Foreign-key existence is checked here rather than in Pydantic
    because the validator doesn't have a session: invalid person_ids
    surface as a clean 422 instead of a generic 500 from the FK
    constraint at flush time.
    """
    if rows:
        person_ids = [r.person_id for r in rows]
        existing = {
            p.id for p in db.query(Person.id).filter(Person.id.in_(person_ids)).all()
        }
        missing = [pid for pid in person_ids if pid not in existing]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"ownerships reference unknown person_id(s): {missing}",
            )

    # Wipe + re-insert. Cheaper than diffing for the typical 1-3 row
    # case, and the deferrable trigger covers us against transient
    # bad-sum states mid-transaction.
    db.query(AccountOwnership).filter(
        AccountOwnership.account_id == account.id
    ).delete(synchronize_session=False)

    for r in rows:
        db.add(AccountOwnership(
            account_id=account.id,
            person_id=r.person_id,
            share_pct=r.share_pct,
        ))

    # Dual-write: derive the legacy pct columns from the new rows.
    # Anything pointing at a person_id we can't represent (e.g. id 4)
    # silently falls off into the join table only.
    legacy = {"alex_pct": 0, "alexa_pct": 0, "kids_pct": 0}
    for r in rows:
        col = _LEGACY_PCT_BY_PERSON_ID.get(r.person_id)
        if col is not None:
            legacy[col] += r.share_pct
    account.alex_pct = legacy["alex_pct"]
    account.alexa_pct = legacy["alexa_pct"]
    account.kids_pct = legacy["kids_pct"]


def _legacy_pcts_to_rows(alex_pct: Optional[int], alexa_pct: Optional[int],
                         kids_pct: Optional[int]) -> List[OwnershipShareIn]:
    """Translate legacy three-column input into the new row shape.

    Used for backwards-compat callers (tests, older clients) that PUT
    alex_pct/alexa_pct/kids_pct directly without sending an
    `ownerships` array. Empty result = "all-zero, system account".
    """
    rows: List[OwnershipShareIn] = []
    pairs = (
        (alex_pct, 1),
        (alexa_pct, 2),
        (kids_pct, 3),
    )
    for pct, person_id in pairs:
        if pct and pct > 0:
            rows.append(OwnershipShareIn(person_id=person_id, share_pct=int(pct)))
    return rows


# ---------------------------------------------------------------------------
# Latest-snapshot lookup (unchanged from phase 1)
# ---------------------------------------------------------------------------

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
    """Build an AccountResponse, attaching latest snapshot fields when present.

    The `ownerships` field on the response auto-populates from the
    account.ownerships relationship via from_attributes=True. Callers
    that want efficient list rendering should joinedload(ownerships)
    upstream to avoid N+1.
    """
    resp = AccountResponse.model_validate(account)
    if latest is not None:
        resp.latest_balance = latest.balance
        resp.latest_balance_as_of = latest.as_of_date
        resp.latest_balance_currency = latest.currency
    return resp


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

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
    the account has no snapshots yet. `ownerships` carries the join-table
    rows; the legacy alex_pct/alexa_pct/kids_pct fields stay populated
    via dual-write for now.
    """
    q = db.query(Account).options(joinedload(Account.ownerships))
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
    account = (
        db.query(Account)
        .options(joinedload(Account.ownerships))
        .filter(Account.id == account_id)
        .first()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    latest = (
        db.query(BalanceSnapshot)
        .filter(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.as_of_date.desc())
        .first()
    )
    return _to_response(account, latest)


@router.post("", response_model=AccountResponse, status_code=201)
def create_account(data: AccountCreate, db: Session = Depends(get_db)):
    payload = data.model_dump(exclude_unset=True)
    # Pull ownership inputs out so they don't land on the Account
    # constructor as plain keyword args.
    ownerships_in: Optional[List[OwnershipShareIn]] = data.ownerships
    payload.pop("ownerships", None)
    legacy_alex  = payload.pop("alex_pct", None)
    legacy_alexa = payload.pop("alexa_pct", None)
    legacy_kids  = payload.pop("kids_pct", None)

    account = Account(**payload)
    db.add(account)
    db.flush()  # need account.id before inserting ownership rows

    if ownerships_in is not None:
        _replace_ownerships(db, account, ownerships_in)
    elif (legacy_alex is not None or legacy_alexa is not None
            or legacy_kids is not None):
        # Translate the legacy three-column input into rows so the join
        # table stays in sync from the moment the account is created.
        rows = _legacy_pcts_to_rows(legacy_alex, legacy_alexa, legacy_kids)
        _replace_ownerships(db, account, rows)
    # If neither was sent, account starts with no ownership rows.

    db.commit()
    db.refresh(account)
    return _to_response(account, None)


@router.put("/{account_id}", response_model=AccountResponse)
def update_account(account_id: int, data: AccountUpdate, db: Session = Depends(get_db)):
    account = get_or_404(db, Account, account_id)
    payload = data.model_dump(exclude_unset=True)

    # exclude_unset means absent fields don't show up here at all.
    # Treat ownerships specially:
    #   - field absent  -> leave ownership rows untouched
    #   - field present -> replace rows wholesale (incl. empty list = clear)
    #
    # IMPORTANT: read `data.ownerships` for the actual Pydantic objects,
    # not from the dumped `payload` dict. `model_dump()` recursively
    # serializes nested BaseModels to plain dicts, so popping from
    # `payload` would hand `_replace_ownerships` a list[dict] and
    # AttributeError (`r.person_id` on a dict) bubbles to a 500. The
    # `payload.pop` is still done — but only to keep the key out of
    # the column-setattr loop below.
    ownership_present = "ownerships" in payload
    ownerships_in: Optional[List[OwnershipShareIn]] = data.ownerships
    payload.pop("ownerships", None)

    # Same dance for the legacy pct fields.
    legacy_keys = ("alex_pct", "alexa_pct", "kids_pct")
    legacy_present = all(k in payload for k in legacy_keys)
    legacy_partial = any(k in payload for k in legacy_keys) and not legacy_present
    legacy_alex = payload.pop("alex_pct", None)
    legacy_alexa = payload.pop("alexa_pct", None)
    legacy_kids = payload.pop("kids_pct", None)

    for key, val in payload.items():
        setattr(account, key, val)

    if ownership_present:
        _replace_ownerships(db, account, ownerships_in or [])
    elif legacy_present:
        rows = _legacy_pcts_to_rows(legacy_alex, legacy_alexa, legacy_kids)
        _replace_ownerships(db, account, rows)
    elif legacy_partial:
        # Partial legacy update (e.g. only alex_pct sent). Keep the v1
        # behavior: write the column directly without touching the
        # join table. Pydantic validation already declined to enforce
        # sum-to-100 on partial updates, so this preserves shipping
        # behavior for the existing test_partial_update_only_one_pct_is_allowed
        # case.
        if legacy_alex is not None:
            account.alex_pct = legacy_alex
        if legacy_alexa is not None:
            account.alexa_pct = legacy_alexa
        if legacy_kids is not None:
            account.kids_pct = legacy_kids

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
