"""Spending analytics — monthly trend + per-category breakdown.

Phase 3 — analytics layer that sits on top of the categorization loop
(/#/categorize). Pure SQL aggregations over bank_transactions; no
new tables, no migrations.

Multi-currency caveat:
  bank_transactions.amount is stored in the row's native currency
  (Revolut multi-currency rows are EUR/CZK/USD/GBP/etc). These
  endpoints sum amounts at face value without FX conversion, which
  is fine for an accounts-mostly-in-USD ledger. The frontend surfaces
  a footnote so the user knows the EUR/CZK rows aren't currency-
  converted. A future FX layer can plug in here without changing
  the JSON shape.
"""

from datetime import date
from calendar import monthrange

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.accounts import Account
from app.models.banking import BankAccount, BankTransaction


router = APIRouter(prefix="/api/spending", tags=["spending"])


def _month_bounds(yyyy_mm: str):
    """Return (start_date, end_date) for a 'YYYY-MM' string, or None."""
    try:
        y, m = yyyy_mm.split("-")
        y, m = int(y), int(m)
        if not (1 <= m <= 12) or not (1900 <= y <= 2100):
            return None
        _, last = monthrange(y, m)
        return date(y, m, 1), date(y, m, last)
    except (ValueError, AttributeError):
        return None


@router.get("/monthly")
def monthly(
    months: int = 12,
    bank_account_id: int = None,
    db: Session = Depends(get_db),
):
    """Last N months of income (positive) vs expense (negative) totals.

    Returned shape:
      {
        "months": [
          {"month": "2025-12", "income": 4523.10, "expense": -2891.45},
          ...
        ],
        "total_income": <float>,
        "total_expense": <float>,
        "bank_account_id": <int|None>,
      }
    """
    if months < 1 or months > 36:
        months = 12

    today = date.today()
    # Compute the first month in the window (months-1 calendar steps back).
    y, m = today.year, today.month
    for _ in range(months - 1):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    window_start = date(y, m, 1)

    month_label = func.to_char(BankTransaction.date, "YYYY-MM")
    q = (
        db.query(
            month_label.label("month"),
            func.sum(case((BankTransaction.amount > 0, BankTransaction.amount), else_=0)).label("income"),
            func.sum(case((BankTransaction.amount < 0, BankTransaction.amount), else_=0)).label("expense"),
        )
        .filter(BankTransaction.date >= window_start)
        .group_by(month_label)
        .order_by(month_label)
    )
    if bank_account_id:
        q = q.filter(BankTransaction.bank_account_id == bank_account_id)
    rows = q.all()

    by_month = {r.month: {"income": float(r.income or 0), "expense": float(r.expense or 0)} for r in rows}

    # Fill any missing months with zeros so the bar chart stays aligned.
    out = []
    yy, mm = window_start.year, window_start.month
    for _ in range(months):
        key = f"{yy:04d}-{mm:02d}"
        slot = by_month.get(key, {"income": 0.0, "expense": 0.0})
        out.append({"month": key, "income": slot["income"], "expense": slot["expense"]})
        mm += 1
        if mm > 12:
            mm = 1
            yy += 1

    return {
        "months": out,
        "total_income": sum(o["income"] for o in out),
        "total_expense": sum(o["expense"] for o in out),
        "bank_account_id": bank_account_id,
    }


@router.get("/by-category")
def by_category(
    month: str = None,
    bank_account_id: int = None,
    direction: str = "expense",  # "expense" | "income"
    db: Session = Depends(get_db),
):
    """Spend (or income) for one month, grouped by COA category.

    Uncategorized rows are bucketed under a single "Uncategorized" slice
    so the user can see how much of their spending hasn't been tagged
    yet — a visible nudge to keep using the categorize page.
    """
    if direction not in ("expense", "income"):
        direction = "expense"

    today = date.today()
    if not month or not _month_bounds(month):
        bounds = (date(today.year, today.month, 1),
                  date(today.year, today.month, monthrange(today.year, today.month)[1]))
        month = f"{today.year:04d}-{today.month:02d}"
    else:
        bounds = _month_bounds(month)
    start, end = bounds

    sign_filter = (BankTransaction.amount < 0) if direction == "expense" else (BankTransaction.amount > 0)

    q = (
        db.query(
            BankTransaction.category_account_id.label("cat_id"),
            Account.name.label("cat_name"),
            func.sum(BankTransaction.amount).label("total"),
            func.count(BankTransaction.id).label("count"),
        )
        .outerjoin(Account, Account.id == BankTransaction.category_account_id)
        .filter(BankTransaction.date >= start)
        .filter(BankTransaction.date <= end)
        .filter(sign_filter)
        .group_by(BankTransaction.category_account_id, Account.name)
        .order_by(func.sum(BankTransaction.amount).asc() if direction == "expense" else func.sum(BankTransaction.amount).desc())
    )
    if bank_account_id:
        q = q.filter(BankTransaction.bank_account_id == bank_account_id)
    rows = q.all()

    items = []
    for r in rows:
        items.append({
            "category_account_id": r.cat_id,
            "name": r.cat_name or "Uncategorized",
            "total": float(r.total or 0),
            "count": int(r.count or 0),
            "is_uncategorized": r.cat_id is None,
        })

    return {
        "month": month,
        "direction": direction,
        "bank_account_id": bank_account_id,
        "items": items,
        "grand_total": sum(i["total"] for i in items),
    }


@router.get("/top-merchants")
def top_merchants(
    month: str = None,
    bank_account_id: int = None,
    direction: str = "expense",
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """Top N merchants for one month by absolute spend (or income).

    Grouped case-insensitively on payee. Returns the most-common original
    casing of the payee per group along with count + total.
    """
    if limit < 1 or limit > 100:
        limit = 10
    if direction not in ("expense", "income"):
        direction = "expense"

    today = date.today()
    if not month or not _month_bounds(month):
        bounds = (date(today.year, today.month, 1),
                  date(today.year, today.month, monthrange(today.year, today.month)[1]))
        month = f"{today.year:04d}-{today.month:02d}"
    else:
        bounds = _month_bounds(month)
    start, end = bounds

    sign_filter = (BankTransaction.amount < 0) if direction == "expense" else (BankTransaction.amount > 0)
    norm = func.lower(func.coalesce(BankTransaction.payee, ""))
    order_col = func.sum(BankTransaction.amount).asc() if direction == "expense" else func.sum(BankTransaction.amount).desc()

    q = (
        db.query(
            norm.label("norm"),
            func.max(BankTransaction.payee).label("payee"),
            func.sum(BankTransaction.amount).label("total"),
            func.count(BankTransaction.id).label("count"),
        )
        .filter(BankTransaction.date >= start)
        .filter(BankTransaction.date <= end)
        .filter(sign_filter)
        .filter(func.coalesce(BankTransaction.payee, "") != "")
        .group_by(norm)
        .order_by(order_col)
        .limit(limit)
    )
    if bank_account_id:
        q = q.filter(BankTransaction.bank_account_id == bank_account_id)
    rows = q.all()

    return {
        "month": month,
        "direction": direction,
        "bank_account_id": bank_account_id,
        "items": [
            {
                "payee": r.payee,
                "total": float(r.total or 0),
                "count": int(r.count or 0),
            }
            for r in rows
        ],
    }


@router.get("/accounts")
def accounts_filter(db: Session = Depends(get_db)):
    """Lightweight bank_accounts list for the filter dropdown."""
    rows = (
        db.query(BankAccount)
        .order_by(BankAccount.name)
        .all()
    )
    return [{"id": ba.id, "name": ba.name, "is_active": ba.is_active} for ba in rows]
