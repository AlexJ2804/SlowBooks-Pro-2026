"""Categorize unmatched bank transactions with LLM-suggested rules.

Phase 3 — spending analytics. The flow:

  1. Frontend calls GET /unmatched-merchants to list distinct payees
     from currently-unmatched bank_transactions, sorted by frequency.
  2. Frontend ships a batch (<=50) to POST /suggest, which calls
     Claude Haiku and returns per-merchant {account_id, confidence}
     suggestions.
  3. User reviews suggestions, possibly tweaks the matching pattern,
     and POSTs to /accept. /accept creates a BankRule and immediately
     applies it to every unmatched txn whose payee matches, so the
     register reflects the categorization in one round-trip.

The existing /api/bank-rules CRUD + /apply endpoints handle ongoing
rule maintenance and bulk re-application; this module just wires the
LLM-assisted onboarding step on top.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.accounts import Account, AccountType
from app.models.bank_rules import BankRule
from app.models.banking import BankTransaction
from app.models.classes import Class
from app.routes.settings import _get_all as get_settings
from app.services import categorizer


router = APIRouter(prefix="/api/categorize", tags=["categorize"])


# Categories eligible to be the target of a rule. Liability/asset/equity
# accounts aren't categories you'd attribute spending to — they're the
# bank account itself or transfers between accounts.
_RULE_TARGET_TYPES = (AccountType.INCOME, AccountType.EXPENSE, AccountType.COGS)


class MerchantBatchItem(BaseModel):
    idx: int
    payee: str = Field(..., max_length=500)


class SuggestRequest(BaseModel):
    merchants: List[MerchantBatchItem] = Field(..., max_length=categorizer.MAX_BATCH)


class AcceptRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    pattern: str = Field(..., min_length=1, max_length=200)
    account_id: int
    # Phase 3: optional class attribution. NULL = "no business" (the
    # implicit personal/household default). When set, the created
    # BankRule carries the class_id and rule-apply stamps it onto every
    # matching unmatched txn alongside the category.
    class_id: Optional[int] = None
    rule_type: str = Field("contains", pattern="^(contains|starts_with|exact)$")
    priority: int = 0


class ClassCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


@router.get("/categories")
def list_target_categories(db: Session = Depends(get_db)):
    """Categories eligible to be a rule target — income / expense / cogs.

    Returned shape matches what categorizer.suggest_categories expects
    so the frontend can pass the array straight through to /suggest.
    """
    rows = (
        db.query(Account)
        .filter(Account.account_type.in_(_RULE_TARGET_TYPES))
        .filter(Account.is_active == True)
        .order_by(Account.account_type, Account.account_number, Account.name)
        .all()
    )
    return [
        {
            "id": a.id,
            "name": a.name,
            "type": a.account_type.value,
            "account_number": a.account_number,
            # Phase 3: surface account_kind so the frontend dropdown can
            # group by Personal / Business / Transfer / etc.
            "account_kind": a.account_kind,
        }
        for a in rows
    ]


@router.get("/classes")
def list_classes(db: Session = Depends(get_db)):
    """Active classes for the per-business-attribution dropdown.

    Skips archived rows. The "Uncategorized" system default is included
    because users may legitimately want to tag a row with it explicitly
    (vs leaving class_id NULL which means "no attribution"); the
    frontend can decide how to display it.
    """
    rows = (
        db.query(Class)
        .filter(Class.is_archived == False)
        .order_by(Class.is_system_default.desc(), Class.name)
        .all()
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "is_system_default": c.is_system_default,
        }
        for c in rows
    ]


@router.post("/classes")
def create_class(payload: ClassCreateRequest, db: Session = Depends(get_db)):
    """Inline create — used by the categorize page's "+ New class" option.

    Idempotent on name (case-insensitive): if a class already exists
    with that name we return it instead of erroring. The same UI flow
    can therefore fire repeatedly without needing to disable the input.
    """
    name = payload.name.strip()
    existing = (
        db.query(Class)
        .filter(func.lower(Class.name) == name.lower())
        .first()
    )
    if existing:
        return {
            "id": existing.id,
            "name": existing.name,
            "is_system_default": existing.is_system_default,
            "created": False,
        }
    c = Class(name=name, is_archived=False, is_system_default=False)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {
        "id": c.id,
        "name": c.name,
        "is_system_default": c.is_system_default,
        "created": True,
    }


@router.get("/unmatched-merchants")
def list_unmatched_merchants(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Distinct payees from unmatched / uncategorized bank transactions.

    Grouped case-insensitively; the most-common original casing of the
    payee is returned so the merchant string the user sees matches what
    Claude saw. Sorted by transaction count desc — categorizing the
    big-frequency rows first knocks out the most data per click.
    """
    if limit < 1 or limit > 1000:
        limit = 100
    if offset < 0:
        offset = 0

    norm = func.lower(func.coalesce(BankTransaction.payee, ""))

    base_filter = (
        # Treat NULL match_status as unmatched; treat any tx without a
        # category as a candidate even if match_status is "auto" but the
        # rule didn't assign a category (vendor-only rules in legacy data).
        or_(
            BankTransaction.match_status == "unmatched",
            BankTransaction.match_status.is_(None),
            BankTransaction.category_account_id.is_(None),
        ),
    )

    total = (
        db.query(func.count(func.distinct(norm)))
        .filter(*base_filter)
        .filter(func.coalesce(BankTransaction.payee, "") != "")
        .filter(BankTransaction.category_account_id.is_(None))
        .scalar()
    ) or 0

    # Pick a representative original payee per group: just MAX(payee).
    # Stats: count, sum of negative amounts (spend), sum of positive
    # amounts (income), date range.
    group_q = (
        db.query(
            norm.label("norm"),
            func.max(BankTransaction.payee).label("payee"),
            func.count(BankTransaction.id).label("tx_count"),
            func.sum(
                case((BankTransaction.amount < 0, BankTransaction.amount), else_=0)
            ).label("spend_total"),
            func.sum(
                case((BankTransaction.amount > 0, BankTransaction.amount), else_=0)
            ).label("income_total"),
            func.min(BankTransaction.date).label("first_date"),
            func.max(BankTransaction.date).label("last_date"),
        )
        .filter(*base_filter)
        .filter(BankTransaction.category_account_id.is_(None))
        .filter(func.coalesce(BankTransaction.payee, "") != "")
        .group_by(norm)
        .order_by(func.count(BankTransaction.id).desc())
        .limit(limit)
        .offset(offset)
    )

    items = []
    for row in group_q.all():
        items.append({
            "normalized": row.norm,
            "payee": row.payee,
            "tx_count": int(row.tx_count or 0),
            "spend_total": float(row.spend_total or 0),
            "income_total": float(row.income_total or 0),
            "first_date": row.first_date.isoformat() if row.first_date else None,
            "last_date": row.last_date.isoformat() if row.last_date else None,
        })

    return {"total": int(total), "limit": limit, "offset": offset, "items": items}


@router.post("/suggest")
def suggest(payload: SuggestRequest, db: Session = Depends(get_db)):
    """Run a single LLM batch and return per-merchant suggestions.

    No DB writes happen here. The frontend collects accepts and POSTs
    each one to /accept, which is where rules and txns are mutated.
    """
    settings = get_settings(db)
    categories = list_target_categories(db)
    merchants = [{"idx": m.idx, "payee": m.payee} for m in payload.merchants]
    result = categorizer.suggest_categories(merchants, categories, settings)
    if result.get("error"):
        # 200 with an error field, mirroring statement_imports — the UI
        # shows the message inline rather than dropping out of the flow.
        return {
            "ok": False,
            "error": result["error"],
            "model": result.get("model"),
            "cost_cents": result.get("cost_cents"),
        }
    return {
        "ok": True,
        "suggestions": result["suggestions"],
        "model": result["model"],
        "input_tokens": result.get("input_tokens"),
        "output_tokens": result.get("output_tokens"),
        "cost_cents": result.get("cost_cents"),
    }


@router.post("/accept")
def accept(payload: AcceptRequest, db: Session = Depends(get_db)):
    """Create a BankRule and immediately apply it to existing unmatched txns.

    Atomic: rule + categorization are committed together, so the user
    never sees a half-applied rule on the register. Returns the rule
    plus the count of transactions it touched.
    """
    target = (
        db.query(Account)
        .filter(Account.id == payload.account_id)
        .filter(Account.account_type.in_(_RULE_TARGET_TYPES))
        .filter(Account.is_active == True)
        .first()
    )
    if not target:
        raise HTTPException(
            status_code=400,
            detail="account_id must be an active income / expense / cogs account",
        )

    # Validate class_id if provided. NULL is the implicit "no business
    # attribution" default and is always allowed.
    class_row: Optional[Class] = None
    if payload.class_id is not None:
        class_row = (
            db.query(Class)
            .filter(Class.id == payload.class_id)
            .filter(Class.is_archived == False)
            .first()
        )
        if not class_row:
            raise HTTPException(
                status_code=400,
                detail="class_id must reference an active class",
            )

    rule = BankRule(
        name=payload.name.strip(),
        pattern=payload.pattern.strip(),
        account_id=payload.account_id,
        class_id=payload.class_id,
        rule_type=payload.rule_type,
        priority=payload.priority,
        is_active=True,
    )
    db.add(rule)
    db.flush()  # need rule.id and rule visible to apply step below

    # Apply this single rule to currently-unmatched transactions. Mirror
    # bank_rules.apply_rules's matching semantics so behavior is the same
    # whether you re-apply via the bulk endpoint or via this acceptance.
    pattern = rule.pattern.lower()
    rule_type = rule.rule_type
    unmatched = (
        db.query(BankTransaction)
        .filter(
            or_(
                BankTransaction.match_status == "unmatched",
                BankTransaction.match_status.is_(None),
            )
        )
        .filter(BankTransaction.category_account_id.is_(None))
        .all()
    )

    matched = 0
    for txn in unmatched:
        payee_lc = (txn.payee or "").lower()
        hit = (
            (rule_type == "contains" and pattern in payee_lc)
            or (rule_type == "starts_with" and payee_lc.startswith(pattern))
            or (rule_type == "exact" and payee_lc == pattern)
        )
        if hit:
            txn.category_account_id = rule.account_id
            if rule.class_id is not None:
                txn.class_id = rule.class_id
            txn.match_status = "auto"
            matched += 1

    db.commit()
    db.refresh(rule)
    return {
        "rule": {
            "id": rule.id,
            "name": rule.name,
            "pattern": rule.pattern,
            "rule_type": rule.rule_type,
            "account_id": rule.account_id,
            "account_name": target.name,
            "class_id": rule.class_id,
            "class_name": class_row.name if class_row else None,
            "priority": rule.priority,
        },
        "matched": matched,
    }
