"""Seed the 18 personal accounts for the net-worth dashboard.

Idempotent — safe to re-run. Skips any account that already exists
(matched by name). For the mortgage account, also inserts the
corresponding `loans` row with placeholder amortization parameters
that the user will edit through the UI before clicking "Generate
schedule" — phase-1 spec is to leave loan_amortization_schedule
empty initially.

Initial balance snapshots are created for the property and loan
accounts (US House: 299000 USD, US Mortgage: 232000 USD) dated today
so the dashboard has something to render. Other balance_only accounts
(brokerage, retirement) get no initial snapshot — the user enters
those through the UI.

Mirrors scripts/seed_database.py style: import path setup, SessionLocal,
print summary on completion.
"""
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.accounts import Account, AccountType
from app.models.balance_snapshots import BalanceSnapshot
from app.models.loans import Loan


# Each row: (name, currency, alex_pct, alexa_pct, kids_pct, account_kind,
#            update_strategy, account_type)
# account_type is the QB-coarse dimension: assets are everything except
# the credit cards and the mortgage (those are liabilities).
_PERSONAL_ACCOUNTS = [
    # Banks (7) — all transactional, all asset
    ("Heartland Joint Checking",    "USD", 50, 50,   0, "bank",        "transactional", AccountType.ASSET),
    ("Heartland Joint Savings",     "USD", 50, 50,   0, "bank",        "transactional", AccountType.ASSET),
    ("Heartland Savings (son)",     "USD",  0,  0, 100, "bank",        "transactional", AccountType.ASSET),
    ("Revolut IE",                  "EUR", 100, 0,   0, "bank",        "transactional", AccountType.ASSET),
    ("Revolut US",                  "USD",  0, 100,  0, "bank",        "transactional", AccountType.ASSET),
    ("Bank of Ireland",             "EUR", 100, 0,   0, "bank",        "transactional", AccountType.ASSET),
    ("Capital Credit Union",        "EUR", 100, 0,   0, "bank",        "transactional", AccountType.ASSET),
    # Credit cards (4) — all liability
    ("Chase United Explorer",       "USD", 50, 50,   0, "credit_card", "transactional", AccountType.LIABILITY),
    ("Citi Aadvantage",             "USD", 50, 50,   0, "credit_card", "transactional", AccountType.LIABILITY),
    ("Heartland CC",                "USD",  0, 100,  0, "credit_card", "transactional", AccountType.LIABILITY),
    ("Bank of Ireland CC",          "EUR", 100, 0,   0, "credit_card", "transactional", AccountType.LIABILITY),
    # Brokerage (2) — balance_only, asset
    ("Vanguard (Alexa)",            "USD",  0, 100,  0, "brokerage",   "balance_only",  AccountType.ASSET),
    ("Vanguard (kids)",             "USD",  0,  0, 100, "brokerage",   "balance_only",  AccountType.ASSET),
    # Retirement (3) — balance_only, asset
    ("Irish Life PRSA",             "EUR", 100, 0,   0, "retirement",  "balance_only",  AccountType.ASSET),
    ("Zurich Pension",              "EUR", 100, 0,   0, "retirement",  "balance_only",  AccountType.ASSET),
    ("Vestwell 401k",               "USD", 100, 0,   0, "retirement",  "balance_only",  AccountType.ASSET),
    # Property (1) — balance_only, asset
    ("US House",                    "USD", 50, 50,   0, "property",    "balance_only",  AccountType.ASSET),
    # Loan (1) — balance_only, liability. Linked into the loans table below.
    ("US Mortgage (PennyMac)",      "USD", 50, 50,   0, "loan",        "balance_only",  AccountType.LIABILITY),
]


# Initial balance snapshots dated today. Only property + loan get one
# in the seed — other balance_only accounts wait for user input via UI.
_INITIAL_SNAPSHOTS = {
    "US House":               (Decimal("299000.00"), "USD"),
    "US Mortgage (PennyMac)": (Decimal("232000.00"), "USD"),
}


# Mortgage placeholder amortization parameters. ALL VALUES ARE GUESSES
# the user will replace via the UI; the loan_amortization_schedule table
# stays empty until they click "Generate schedule" with real values.
_MORTGAGE_PLACEHOLDER = {
    "loan_account_name":  "US Mortgage (PennyMac)",
    "asset_account_name": "US House",
    "original_amount":    Decimal("240000.00"),
    "interest_rate":      Decimal("6.5000"),     # 6.5% APR
    "term_months":        360,
    "start_date":         date(2022, 1, 1),
    "monthly_payment":    Decimal("2100.00"),
    "escrow_amount":      Decimal("400.00"),
    "currency":           "USD",
}


def apply_seed(db, today=None):
    """Apply the seed against a given SQLAlchemy session.

    Returns a counts dict so the CLI wrapper can print a summary and the
    test suite can assert idempotency. Caller is responsible for
    db.commit() / db.close() — keeps this function pure for testing.

    `today` overrides the as_of_date used for initial snapshots; mainly
    a test hook so assertions don't depend on the wall clock.
    """
    if today is None:
        today = date.today()

    counts = {
        "accounts_created": 0, "accounts_skipped": 0,
        "snapshots_created": 0, "snapshots_skipped": 0,
        "loans_created": 0, "loans_skipped": 0,
    }
    accounts_by_name: dict = {}

    for (name, currency, alex_pct, alexa_pct, kids_pct,
         kind, strategy, acct_type) in _PERSONAL_ACCOUNTS:
        existing = db.query(Account).filter(Account.name == name).first()
        if existing:
            accounts_by_name[name] = existing
            counts["accounts_skipped"] += 1
            continue
        acct = Account(
            name=name,
            account_type=acct_type,
            account_kind=kind,
            update_strategy=strategy,
            currency=currency,
            alex_pct=alex_pct,
            alexa_pct=alexa_pct,
            kids_pct=kids_pct,
            is_active=True,
            is_system=False,
            balance=Decimal("0"),
        )
        db.add(acct)
        db.flush()
        accounts_by_name[name] = acct
        counts["accounts_created"] += 1

    # Initial balance snapshots — only for property + loan per spec.
    for acct_name, (balance, currency) in _INITIAL_SNAPSHOTS.items():
        acct = accounts_by_name.get(acct_name)
        if acct is None:
            continue  # defensive; every snapshot key is in _PERSONAL_ACCOUNTS
        existing_snap = db.query(BalanceSnapshot).filter(
            BalanceSnapshot.account_id == acct.id,
            BalanceSnapshot.as_of_date == today,
        ).first()
        if existing_snap:
            counts["snapshots_skipped"] += 1
            continue
        db.add(BalanceSnapshot(
            account_id=acct.id,
            as_of_date=today,
            balance=balance,
            currency=currency,
        ))
        counts["snapshots_created"] += 1

    # Mortgage loan row — placeholder values, no schedule generated.
    mortgage = accounts_by_name.get(_MORTGAGE_PLACEHOLDER["loan_account_name"])
    house = accounts_by_name.get(_MORTGAGE_PLACEHOLDER["asset_account_name"])
    if mortgage is not None:
        existing_loan = db.query(Loan).filter(Loan.account_id == mortgage.id).first()
        if existing_loan:
            counts["loans_skipped"] += 1
        else:
            db.add(Loan(
                account_id=mortgage.id,
                asset_account_id=(house.id if house is not None else None),
                original_amount=_MORTGAGE_PLACEHOLDER["original_amount"],
                interest_rate=_MORTGAGE_PLACEHOLDER["interest_rate"],
                term_months=_MORTGAGE_PLACEHOLDER["term_months"],
                start_date=_MORTGAGE_PLACEHOLDER["start_date"],
                monthly_payment=_MORTGAGE_PLACEHOLDER["monthly_payment"],
                escrow_amount=_MORTGAGE_PLACEHOLDER["escrow_amount"],
                currency=_MORTGAGE_PLACEHOLDER["currency"],
            ))
            counts["loans_created"] += 1

    db.flush()
    return counts


def seed():
    db = SessionLocal()
    try:
        counts = apply_seed(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"Personal accounts: created={counts['accounts_created']}, "
          f"skipped (already existed)={counts['accounts_skipped']}")
    print(f"Initial balance snapshots: created={counts['snapshots_created']}, "
          f"skipped={counts['snapshots_skipped']}")
    print(f"Mortgage loan row: created={counts['loans_created']}, "
          f"skipped={counts['loans_skipped']}")
    print()
    print("Note: loan_amortization_schedule is intentionally empty.")
    print("Edit the mortgage's real values via /#/accounts and click 'Generate schedule'.")


if __name__ == "__main__":
    seed()
