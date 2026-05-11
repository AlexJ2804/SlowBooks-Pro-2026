"""Retroactively write balance_snapshots from already-posted statement imports.

Run after wiring bank_accounts.account_id to the matching COA rows. Walks
every statement_imports row with status='posted' (or 'parsed'), reads the
parsed payload's closing_balance, and upserts a balance_snapshot for
(account_id, period_end). Idempotent — re-running just overwrites the
same (account_id, as_of_date) rows.

Skips imports whose bank_account isn't linked yet (account_id NULL), or
whose parsed payload doesn't carry a closing_balance.

Usage:
    docker exec slowbooks-pro-2026-slowbooks-1 python -m scripts.backfill_statement_snapshots
"""

import json
import sys
from pathlib import Path

# Allow running as `python scripts/backfill_statement_snapshots.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.accounts import Account
from app.models.balance_snapshots import BalanceSnapshot
from app.models.banking import BankAccount
from app.models.statement_imports import StatementImport


def main() -> int:
    db = SessionLocal()
    try:
        imports = (
            db.query(StatementImport)
            .filter(StatementImport.status.in_(("posted", "parsed")))
            .order_by(StatementImport.bank_account_id, StatementImport.period_end)
            .all()
        )
        written = 0
        skipped_no_link = 0
        skipped_no_closing = 0
        skipped_no_period = 0
        for si in imports:
            ba = db.query(BankAccount).filter(BankAccount.id == si.bank_account_id).first()
            if not ba or not ba.account_id:
                skipped_no_link += 1
                continue
            if not si.period_end:
                skipped_no_period += 1
                continue
            try:
                parsed = json.loads(si.raw_response_json or "")
            except (TypeError, ValueError, json.JSONDecodeError):
                skipped_no_closing += 1
                continue
            closing = ((parsed or {}).get("statement") or {}).get("closing_balance")
            if closing is None:
                skipped_no_closing += 1
                continue

            coa = db.query(Account).filter(Account.id == ba.account_id).first()
            currency = (coa.currency if coa and coa.currency else "USD").upper()

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
            written += 1
            print(
                f"  acct={ba.account_id:<4} ({ba.name[:30]:<30}) "
                f"date={si.period_end} bal={closing:>12,.2f} {currency}"
            )

        db.commit()
        print()
        print(f"Snapshots written/updated: {written}")
        print(f"Skipped (no COA link):     {skipped_no_link}")
        print(f"Skipped (no closing_bal):  {skipped_no_closing}")
        print(f"Skipped (no period_end):   {skipped_no_period}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
