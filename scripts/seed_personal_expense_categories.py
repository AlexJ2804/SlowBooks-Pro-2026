"""Seed personal / household expense categories alongside the QB business COA.

The default chart shipped with Slowbooks is QuickBooks' standard business
chart (Advertising & Marketing, Auto Expense, Bank Fees, etc. in the 6000
range). Once you start using the app for personal/household bookkeeping
too — pulling in Amex, Citi, HCU, Revolut imports — most of your real
spending doesn't fit into those buckets. This seed adds a personal chart
in the 7000 range so the categorize loop (/#/categorize) has somewhere
to put a Walmart grocery run or a Luas tram fare.

Idempotent: re-running skips any account whose name already exists.
Pure-Python, mirrors scripts/seed_personal_accounts.py style.

Numbering scheme:
  6000-6999  business expense (existing, untouched by this seed)
  7000-7799  personal expense categories (new — added by this seed)
  7800-7899  income categories (new)
  7900-7999  transfer / non-expense pseudo-categories (new)

Transfer pseudo-categories are still account_type=EXPENSE because that
is what the categorize UI surfaces; their distinguishing feature is the
account_number being in the 7900-7999 range and a "Transfer:" prefix
in the name. A follow-up spending-dashboard PR will teach the donut to
exclude this range from the "where did our money go" total.

Run:
    docker exec slowbooks-pro-2026-slowbooks-1 \\
        python -m scripts.seed_personal_expense_categories
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.accounts import Account, AccountType


# (account_number, name, account_type)
# Names chosen to match what people actually call these line items, not
# what an accountant calls them — "Coffee & Cafés" not "Beverages, Hot,
# Vendor Class 4". The categorize LLM matches better on natural names.
_PERSONAL_EXPENSES = [
    # 7000-7099 Food
    ("7000", "Groceries",                          AccountType.EXPENSE),
    ("7010", "Restaurants & Dining",               AccountType.EXPENSE),
    ("7020", "Coffee & Cafés",                     AccountType.EXPENSE),
    ("7030", "Takeout & Delivery",                 AccountType.EXPENSE),
    ("7040", "Alcohol",                            AccountType.EXPENSE),

    # 7100-7199 Home & utilities (personal)
    ("7100", "Utilities (Personal)",               AccountType.EXPENSE),
    ("7110", "Internet & Phone (Personal)",        AccountType.EXPENSE),
    ("7120", "Home Maintenance",                   AccountType.EXPENSE),
    ("7130", "Furniture & Furnishings",            AccountType.EXPENSE),
    ("7140", "Household Supplies",                 AccountType.EXPENSE),

    # 7200-7299 Health & wellness
    ("7200", "Healthcare & Medical",               AccountType.EXPENSE),
    ("7210", "Pharmacy",                           AccountType.EXPENSE),
    ("7220", "Dental & Vision",                    AccountType.EXPENSE),
    ("7230", "Gym & Fitness",                      AccountType.EXPENSE),

    # 7300-7399 Personal care & shopping
    ("7300", "Personal Care",                      AccountType.EXPENSE),
    ("7310", "Clothing & Apparel",                 AccountType.EXPENSE),
    ("7320", "Shopping (Misc)",                    AccountType.EXPENSE),

    # 7400-7499 Transportation
    ("7400", "Auto Fuel",                          AccountType.EXPENSE),
    ("7410", "Auto Maintenance",                   AccountType.EXPENSE),
    ("7420", "Parking & Tolls",                    AccountType.EXPENSE),
    ("7430", "Public Transit",                     AccountType.EXPENSE),
    ("7440", "Rideshare & Taxi",                   AccountType.EXPENSE),

    # 7500-7599 Travel
    ("7500", "Travel — Lodging",                   AccountType.EXPENSE),
    ("7510", "Travel — Air & Rail",                AccountType.EXPENSE),
    ("7520", "Travel — Other",                     AccountType.EXPENSE),

    # 7600-7699 Entertainment & lifestyle
    ("7600", "Entertainment",                      AccountType.EXPENSE),
    ("7610", "Streaming Subscriptions",            AccountType.EXPENSE),
    ("7620", "Software & Apps (Personal)",         AccountType.EXPENSE),
    ("7630", "Memberships & Dues",                 AccountType.EXPENSE),
    ("7640", "Books & Media",                      AccountType.EXPENSE),
    ("7650", "Hobbies",                            AccountType.EXPENSE),

    # 7700-7799 Kids, pets, gifts, donations
    ("7700", "Kids & Childcare",                   AccountType.EXPENSE),
    ("7710", "Education & School",                 AccountType.EXPENSE),
    ("7720", "Kids' Activities",                   AccountType.EXPENSE),
    ("7730", "Pet Care",                           AccountType.EXPENSE),
    ("7740", "Gifts",                              AccountType.EXPENSE),
    ("7750", "Charity & Donations",                AccountType.EXPENSE),

    # 7800-7899 Personal income lines (paychecks etc.)
    ("7800", "Salary & Wages",                     AccountType.INCOME),
    ("7810", "Bonus & Commission",                 AccountType.INCOME),
    ("7820", "Investment Income (Personal)",       AccountType.INCOME),
    ("7830", "Reimbursements & Refunds",           AccountType.INCOME),
    ("7840", "Other Personal Income",              AccountType.INCOME),

    # 7900-7999 Transfer / non-expense pseudo-categories.
    # Labelled with a "Transfer:" prefix so they read as obviously-not-
    # spending in the categorize dropdown and the merchant register.
    # The spending dashboard will eventually exclude account_number 7900+
    # from the "where did our money go" donut.
    ("7900", "Transfer: Between Household Accounts", AccountType.EXPENSE),
    ("7910", "Transfer: Credit Card Payment",      AccountType.EXPENSE),
    ("7920", "Transfer: Currency Exchange",        AccountType.EXPENSE),
    ("7930", "Transfer: Account Top-up / Funding", AccountType.EXPENSE),
]


def apply_seed(db) -> dict:
    """Insert any missing rows from _PERSONAL_EXPENSES.

    Idempotent on (name) — re-running skips rows whose name already
    exists, so this is safe to wire into a deploy hook.
    """
    counts = {"created": 0, "skipped": 0}
    for account_number, name, acct_type in _PERSONAL_EXPENSES:
        existing = db.query(Account).filter(Account.name == name).first()
        if existing:
            counts["skipped"] += 1
            continue
        db.add(Account(
            name=name,
            account_number=account_number,
            account_type=acct_type,
            account_kind=None,
            update_strategy=None,
            currency="USD",
            alex_pct=0,
            alexa_pct=0,
            kids_pct=0,
            is_active=True,
            is_system=False,
            balance=Decimal("0"),
        ))
        counts["created"] += 1
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

    print(f"Personal expense / income categories: created={counts['created']}, "
          f"skipped (already existed)={counts['skipped']}")
    total = len(_PERSONAL_EXPENSES)
    print(f"Targeted {total} categories; "
          f"final state has {counts['created'] + counts['skipped']} of them present.")
    print()
    print("Next: open /#/categorize and re-run 'Suggest categories with AI' —")
    print("Haiku now has personal categories to map merchants onto.")


if __name__ == "__main__":
    seed()
