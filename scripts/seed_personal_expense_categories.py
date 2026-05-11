"""Seed personal / household expense categories alongside the QB business COA.

The default chart shipped with Slowbooks is QuickBooks' standard
business chart (Advertising & Marketing, Auto Expense, Bank Fees, etc.
in the 6000 range). Once you start pulling Amex / Citi / HCU / Revolut
imports through the categorize loop, most personal spending —
groceries, restaurants, gym, kids — doesn't fit into those buckets.
This seed adds a parallel personal chart in the 7000 range plus a
"Transfer:" prefixed pseudo-category set for non-expense movements.

Each row carries the `account_kind` tag that became legal in alembic
q9h0i1j2k3l4. The categorize page groups its dropdown by kind so
personal vs business vs transfer reads at a glance, and the spending
dashboard uses `account_kind != 'transfer'` to keep transfers out of
the "where did our money go" donut total.

Idempotent: re-running upserts on (name). If a row already exists
(e.g. created by the earlier kind-less version of this seed), this
re-run patches its account_number and account_kind so existing data
ends up tagged correctly without having to drop and re-insert.

Numbering scheme:
  6000-6999  business expense (existing QB defaults, untouched by this
             seed but backfilled with account_kind='business_expense'
             by alembic q9h0i1j2k3l4)
  7000-7099  food
  7100-7199  home & utilities (personal)
  7200-7299  health & wellness
  7300-7399  personal care & shopping
  7400-7499  transportation
  7500-7599  travel
  7600-7699  entertainment & lifestyle
  7700-7799  kids, pets, gifts, donations
  7800-7899  personal income (paychecks etc.)
  7900-7999  transfer pseudo-categories (kind='transfer')

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


# (account_number, name, account_type, account_kind)
# Names chosen to match what people actually call these line items, not
# what an accountant calls them — "Coffee & Cafés" not "Beverages, Hot,
# Vendor Class 4". The categorize LLM matches better on natural names.
_PERSONAL_CATEGORIES = [
    # 7000-7099 Food
    ("7000", "Groceries",                          AccountType.EXPENSE, "personal_expense"),
    ("7010", "Restaurants & Dining",               AccountType.EXPENSE, "personal_expense"),
    ("7020", "Coffee & Cafés",                     AccountType.EXPENSE, "personal_expense"),
    ("7030", "Takeout & Delivery",                 AccountType.EXPENSE, "personal_expense"),
    ("7040", "Alcohol",                            AccountType.EXPENSE, "personal_expense"),

    # 7100-7199 Home & utilities (personal)
    ("7100", "Utilities (Personal)",               AccountType.EXPENSE, "personal_expense"),
    ("7110", "Internet & Phone (Personal)",        AccountType.EXPENSE, "personal_expense"),
    ("7120", "Home Maintenance",                   AccountType.EXPENSE, "personal_expense"),
    ("7130", "Furniture & Furnishings",            AccountType.EXPENSE, "personal_expense"),
    ("7140", "Household Supplies",                 AccountType.EXPENSE, "personal_expense"),

    # 7200-7299 Health & wellness
    ("7200", "Healthcare & Medical",               AccountType.EXPENSE, "personal_expense"),
    ("7210", "Pharmacy",                           AccountType.EXPENSE, "personal_expense"),
    ("7220", "Dental & Vision",                    AccountType.EXPENSE, "personal_expense"),
    ("7230", "Gym & Fitness",                      AccountType.EXPENSE, "personal_expense"),

    # 7300-7399 Personal care & shopping
    ("7300", "Personal Care",                      AccountType.EXPENSE, "personal_expense"),
    ("7310", "Clothing & Apparel",                 AccountType.EXPENSE, "personal_expense"),
    ("7320", "Shopping (Misc)",                    AccountType.EXPENSE, "personal_expense"),

    # 7400-7499 Transportation
    ("7400", "Auto Fuel",                          AccountType.EXPENSE, "personal_expense"),
    ("7410", "Auto Maintenance",                   AccountType.EXPENSE, "personal_expense"),
    ("7420", "Parking & Tolls",                    AccountType.EXPENSE, "personal_expense"),
    ("7430", "Public Transit",                     AccountType.EXPENSE, "personal_expense"),
    ("7440", "Rideshare & Taxi",                   AccountType.EXPENSE, "personal_expense"),

    # 7500-7599 Travel
    ("7500", "Travel — Lodging",                   AccountType.EXPENSE, "personal_expense"),
    ("7510", "Travel — Air & Rail",                AccountType.EXPENSE, "personal_expense"),
    ("7520", "Travel — Other",                     AccountType.EXPENSE, "personal_expense"),

    # 7600-7699 Entertainment & lifestyle
    ("7600", "Entertainment",                      AccountType.EXPENSE, "personal_expense"),
    ("7610", "Streaming Subscriptions",            AccountType.EXPENSE, "personal_expense"),
    ("7620", "Software & Apps (Personal)",         AccountType.EXPENSE, "personal_expense"),
    ("7630", "Memberships & Dues",                 AccountType.EXPENSE, "personal_expense"),
    ("7640", "Books & Media",                      AccountType.EXPENSE, "personal_expense"),
    ("7650", "Hobbies",                            AccountType.EXPENSE, "personal_expense"),

    # 7700-7799 Kids, pets, gifts, donations
    ("7700", "Kids & Childcare",                   AccountType.EXPENSE, "personal_expense"),
    ("7710", "Education & School",                 AccountType.EXPENSE, "personal_expense"),
    ("7720", "Kids' Activities",                   AccountType.EXPENSE, "personal_expense"),
    ("7730", "Pet Care",                           AccountType.EXPENSE, "personal_expense"),
    ("7740", "Gifts",                              AccountType.EXPENSE, "personal_expense"),
    ("7750", "Charity & Donations",                AccountType.EXPENSE, "personal_expense"),

    # 7800-7899 Personal income
    ("7800", "Salary & Wages",                     AccountType.INCOME,  "personal_income"),
    ("7810", "Bonus & Commission",                 AccountType.INCOME,  "personal_income"),
    ("7820", "Investment Income (Personal)",       AccountType.INCOME,  "personal_income"),
    ("7830", "Reimbursements & Refunds",           AccountType.INCOME,  "personal_income"),
    ("7840", "Other Personal Income",              AccountType.INCOME,  "personal_income"),

    # 7900-7999 Transfer / non-expense pseudo-categories.
    # account_type stays EXPENSE because that's what the categorize UI
    # filters to surface. account_kind='transfer' is the marker the
    # spending dashboard reads to exclude these from spend totals.
    ("7900", "Transfer: Between Household Accounts", AccountType.EXPENSE, "transfer"),
    ("7910", "Transfer: Credit Card Payment",        AccountType.EXPENSE, "transfer"),
    ("7920", "Transfer: Currency Exchange",          AccountType.EXPENSE, "transfer"),
    ("7930", "Transfer: Account Top-up / Funding",   AccountType.EXPENSE, "transfer"),
]


def apply_seed(db) -> dict:
    """Upsert any missing rows from _PERSONAL_CATEGORIES.

    Idempotent on (name) — re-running:
      * creates rows that don't exist
      * patches account_number / account_kind on rows that already
        exist but came in untagged (e.g. seeded by an earlier
        kind-less version of this script)
      * leaves rows alone if they're already in the desired shape
    """
    counts = {"created": 0, "updated": 0, "skipped": 0}
    for account_number, name, acct_type, kind in _PERSONAL_CATEGORIES:
        existing = db.query(Account).filter(Account.name == name).first()
        if existing:
            changed = False
            if not existing.account_number:
                existing.account_number = account_number
                changed = True
            if existing.account_kind != kind:
                existing.account_kind = kind
                changed = True
            if existing.account_type != acct_type:
                existing.account_type = acct_type
                changed = True
            counts["updated" if changed else "skipped"] += 1
            continue
        db.add(Account(
            name=name,
            account_number=account_number,
            account_type=acct_type,
            account_kind=kind,
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

    print(f"Personal categories: created={counts['created']}, "
          f"updated (tagged with kind/number)={counts['updated']}, "
          f"unchanged={counts['skipped']}")
    total = len(_PERSONAL_CATEGORIES)
    print(f"Targeted {total} categories; "
          f"final state has {counts['created'] + counts['updated'] + counts['skipped']} of them present.")
    print()
    print("Next: open /#/categorize — the dropdown is grouped by kind so")
    print("personal vs business vs transfer reads at a glance.")


if __name__ == "__main__":
    seed()
