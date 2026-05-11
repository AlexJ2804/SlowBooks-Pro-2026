from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, field_validator, model_validator

from app.models.accounts import AccountType
from app.schemas.people import OwnershipShareIn, OwnershipShareOut


# Net worth phase 1 — accepted account_kind values, mirrored from the
# DB CHECK constraint in alembic h0e1f2a3b4c5. Kept here so the API
# layer can reject bad input before it hits the DB and produces a
# generic constraint-violation 500.
_VALID_ACCOUNT_KINDS = {"bank", "credit_card", "brokerage", "retirement", "property", "loan"}
_VALID_UPDATE_STRATEGIES = {"transactional", "balance_only"}


def _empty_str_to_none(v):
    """Coerce blank strings to None for fields that are nullable + UNIQUE.

    Forms send blank inputs as "" rather than omitting them. account_number
    has a UNIQUE constraint, so two accounts both posting "" collide and
    return a generic 500. Mapping "" → NULL lets multiple accounts coexist
    without a number, since Postgres treats NULLs as distinct under UNIQUE.
    """
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


class AccountCreate(BaseModel):
    name: str
    account_number: Optional[str] = None
    account_type: AccountType
    parent_id: Optional[int] = None
    description: Optional[str] = None
    account_kind: Optional[str] = None
    update_strategy: Optional[str] = None
    currency: Optional[str] = None

    _coerce_account_number = field_validator(
        "account_number", mode="before"
    )(_empty_str_to_none)
    # Phase 1.5: new authoritative ownership shape. When provided, the
    # route handler replaces the account's ownership rows wholesale and
    # back-fills the legacy alex_pct/alexa_pct/kids_pct columns. When
    # omitted, the legacy pct fields below are used for backwards-compat
    # callers that haven't migrated yet.
    ownerships: Optional[List[OwnershipShareIn]] = None
    # DEPRECATED phase 1.5 — superseded by `ownerships`. Still accepted
    # so existing tests and callers keep working through the dual-write
    # window. Will be removed once the legacy columns are dropped.
    alex_pct: Optional[int] = None
    alexa_pct: Optional[int] = None
    kids_pct: Optional[int] = None

    @model_validator(mode="after")
    def _check_kind_and_pct(self):
        if self.account_kind is not None and self.account_kind not in _VALID_ACCOUNT_KINDS:
            raise ValueError(f"account_kind must be one of {sorted(_VALID_ACCOUNT_KINDS)}")
        if self.update_strategy is not None and self.update_strategy not in _VALID_UPDATE_STRATEGIES:
            raise ValueError(f"update_strategy must be one of {sorted(_VALID_UPDATE_STRATEGIES)}")
        if self.ownerships is not None:
            _validate_ownership_rows(self.ownerships)
        else:
            _validate_ownership_total(self.alex_pct, self.alexa_pct, self.kids_pct)
        return self


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_number: Optional[str] = None
    account_type: Optional[AccountType] = None
    parent_id: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    account_kind: Optional[str] = None
    update_strategy: Optional[str] = None
    currency: Optional[str] = None

    _coerce_account_number = field_validator(
        "account_number", mode="before"
    )(_empty_str_to_none)
    # See AccountCreate for the ownership rules. On update, omitting
    # `ownerships` means "don't touch the ownership rows" (partial PUT
    # semantics). Sending an empty list explicitly means "clear all
    # ownership rows" (i.e. mark this account as system / not personally
    # owned).
    ownerships: Optional[List[OwnershipShareIn]] = None
    alex_pct: Optional[int] = None
    alexa_pct: Optional[int] = None
    kids_pct: Optional[int] = None

    @model_validator(mode="after")
    def _check_kind_and_pct(self):
        if self.account_kind is not None and self.account_kind not in _VALID_ACCOUNT_KINDS:
            raise ValueError(f"account_kind must be one of {sorted(_VALID_ACCOUNT_KINDS)}")
        if self.update_strategy is not None and self.update_strategy not in _VALID_UPDATE_STRATEGIES:
            raise ValueError(f"update_strategy must be one of {sorted(_VALID_UPDATE_STRATEGIES)}")
        if self.ownerships is not None:
            _validate_ownership_rows(self.ownerships)
        elif (self.alex_pct is not None and self.alexa_pct is not None
                and self.kids_pct is not None):
            # PUT uses exclude_unset so partial updates are normal — only
            # validate the legacy total when ALL three pcts were sent.
            _validate_ownership_total(self.alex_pct, self.alexa_pct, self.kids_pct)
        return self


def _validate_ownership_total(alex_pct, alexa_pct, kids_pct):
    """Legacy three-column ownership validation.

    Mirror of the DB CHECK from alembic h0e1f2a3b4c5: all-zero (system
    COA, not personally owned) OR sum-to-100. Returns early if every
    value is None (means caller sent no ownership info on a partial PUT).
    """
    if alex_pct is None and alexa_pct is None and kids_pct is None:
        return
    a, b, c = (alex_pct or 0), (alexa_pct or 0), (kids_pct or 0)
    if a < 0 or b < 0 or c < 0:
        raise ValueError("ownership pcts must be non-negative")
    total = a + b + c
    if total != 0 and total != 100:
        raise ValueError(
            f"ownership pcts must be all-zero (system account) or sum to 100; "
            f"got {a}/{b}/{c} = {total}"
        )


def _validate_ownership_rows(rows: List[OwnershipShareIn]):
    """Phase 1.5 join-table ownership validation.

    Rules:
      - Zero rows = "system account, not personally owned" (allowed).
      - One or more rows: each share_pct in 1..100 (Pydantic field
        constraint already covers this), no duplicate person_id, sum
        across rows == 100.

    Mirrors the DB-level deferred trigger from alembic j2a3b4c5d6e7
    so SQLite tests get the same behavior without the trigger.
    """
    if not rows:
        return
    seen_person_ids = set()
    total = 0
    for r in rows:
        if r.person_id in seen_person_ids:
            raise ValueError(
                f"duplicate person_id={r.person_id} in ownerships; "
                f"merge into a single row"
            )
        seen_person_ids.add(r.person_id)
        total += r.share_pct
    if total != 100:
        raise ValueError(
            f"ownership shares must sum to 100; got "
            f"{'/'.join(str(r.share_pct) for r in rows)} = {total}"
        )


class AccountResponse(BaseModel):
    id: int
    name: str
    account_number: Optional[str]
    account_type: AccountType
    parent_id: Optional[int]
    description: Optional[str]
    is_active: bool
    is_system: bool
    balance: Decimal
    created_at: datetime
    updated_at: datetime
    # Net worth phase 1 fields. All defaults nullable / 0 so existing
    # callers that don't care about them keep working.
    account_kind: Optional[str] = None
    update_strategy: Optional[str] = None
    currency: str = "USD"
    # DEPRECATED phase 1.5 — kept in the response so existing UI / tests
    # that read these fields keep working through the dual-write window.
    alex_pct: int = 0
    alexa_pct: int = 0
    kids_pct: int = 0
    # Phase 1.5: authoritative ownership rows. Empty list for system
    # accounts. Populated from the account_ownerships join table by the
    # route handler.
    ownerships: List[OwnershipShareOut] = []
    # Latest balance snapshot — computed by the route handler, not on
    # the ORM model. Optional so accounts with zero snapshots return
    # cleanly as null rather than 0 (which would be misleading).
    latest_balance: Optional[Decimal] = None
    latest_balance_as_of: Optional[date] = None
    latest_balance_currency: Optional[str] = None

    model_config = {"from_attributes": True}
