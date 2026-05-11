"""Import a Revolut account-statement CSV into bank_transactions.

Revolut exports a single CSV per account that covers every transaction
across every currency pocket — EUR purchases, CZK vault transfers, GBP
card payments, etc. They land in one bank_account (typically Revolut IE)
with the per-row currency stored on bank_transactions.currency.

CSV columns Revolut produces (Irish locale, May 2026):
    Type, Product, Started Date, Completed Date, Description, Amount,
    Fee, Currency, State, Balance

Mapping:
    bank_transactions.date         := Completed Date (YYYY-MM-DD)
    bank_transactions.amount       := Amount (already signed: + inflow,
                                       - outflow)
    bank_transactions.payee        := Description, truncated to 200 chars
    bank_transactions.description  := Description (full)
    bank_transactions.currency     := Currency (3-char code)
    bank_transactions.import_source:= 'revolut_csv'
    bank_transactions.import_id    := stable per-row fingerprint so a
                                       re-import dedups cleanly even if
                                       Revolut re-exports the same range

Rules:
  * Skip rows with State != 'COMPLETED' (pending / reverted / declined
    aren't real money movements yet)
  * Skip rows where Amount is missing or non-numeric
  * Include the fee as a separate negative row when Fee > 0, so the
    register matches what hit the account
  * Dedup on (date, signed amount, normalised description, currency) —
    same key the PDF importer uses, with currency added so a CZK 50 and
    a EUR 50 charge on the same day stay distinct

Usage:
    docker exec slowbooks-pro-2026-slowbooks-1 \\
        python -m scripts.import_revolut_csv \\
        --bank-account-id 12 \\
        --csv-path /tmp/revolut.csv

The CSV needs to be readable from inside the container. Copy with:
    docker cp ~/Downloads/Revolut/<file>.csv slowbooks-pro-2026-slowbooks-1:/tmp/revolut.csv
"""

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.banking import BankAccount, BankTransaction


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")
_DEDUP_DESC_LEN = 40


def _normalize_description(desc: str) -> str:
    if not desc:
        return ""
    return _NON_ALNUM_RE.sub("", desc.lower())[:_DEDUP_DESC_LEN]


def _dedup_key(tx_date, amount: float, description: str, currency: str) -> tuple:
    ccy = (currency or "").upper() or None
    return (tx_date, f"{float(amount):.2f}", _normalize_description(description), ccy)


def _parse_date(s: str):
    # Revolut's Completed Date is 'YYYY-MM-DD HH:MM:SS'. We only need the
    # date portion for the register. Reject anything that doesn't parse.
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_amount(s: str):
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a Revolut CSV into bank_transactions")
    parser.add_argument("--bank-account-id", type=int, required=True,
                        help="bank_accounts.id to attach every imported row to")
    parser.add_argument("--csv-path", required=True,
                        help="path to the Revolut CSV (must be readable inside the container)")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and report counts but don't commit")
    parser.add_argument("--include-fees", action="store_true", default=True,
                        help="emit a separate negative row for non-zero Fee (default: on)")
    parser.add_argument("--no-fees", dest="include_fees", action="store_false",
                        help="don't emit fee rows")
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.is_file():
        print(f"ERROR: CSV not found at {csv_path}", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        ba = db.query(BankAccount).filter(BankAccount.id == args.bank_account_id).first()
        if not ba:
            print(f"ERROR: bank_account id={args.bank_account_id} not found", file=sys.stderr)
            return 2
        print(f"Target: bank_account id={ba.id} '{ba.name}' "
              f"(linked to COA id={ba.account_id})")
        print()

        # Pre-load every existing row's dedup key for this account.
        existing = {
            _dedup_key(r.date, float(r.amount), r.description or r.payee, r.currency)
            for r in (
                db.query(
                    BankTransaction.date, BankTransaction.amount,
                    BankTransaction.description, BankTransaction.payee,
                    BankTransaction.currency,
                )
                .filter(BankTransaction.bank_account_id == ba.id)
                .all()
            )
        }
        print(f"Loaded {len(existing)} existing fingerprints for dedup")

        created = 0
        dups = 0
        skipped_state = 0
        skipped_bad = 0
        fee_rows = 0
        per_currency = {}

        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                state = (row.get("State") or "").strip().upper()
                if state != "COMPLETED":
                    skipped_state += 1
                    continue

                tx_date = _parse_date(row.get("Completed Date"))
                if tx_date is None:
                    skipped_bad += 1
                    continue

                amount = _parse_amount(row.get("Amount"))
                if amount is None:
                    skipped_bad += 1
                    continue

                currency = (row.get("Currency") or "").strip().upper() or None
                description = (row.get("Description") or "").strip()
                row_type = (row.get("Type") or "").strip()
                product = (row.get("Product") or "").strip()

                # Compose a richer description so the register shows the
                # Type + Product context (Revolut's Description alone
                # often loses information — many rows are bare "To CZK").
                full_desc = description
                if row_type and row_type.lower() not in description.lower():
                    full_desc = f"{row_type} • {description}".strip(" •")
                if product and product.lower() not in full_desc.lower():
                    full_desc = f"{full_desc} ({product})".strip()

                key = _dedup_key(tx_date, amount, full_desc, currency)
                if key in existing:
                    dups += 1
                    continue

                bt = BankTransaction(
                    bank_account_id=ba.id,
                    date=tx_date,
                    amount=amount,
                    payee=full_desc[:200],
                    description=full_desc,
                    currency=currency,
                    import_id=f"revolut:{idx}:{tx_date.isoformat()}:{amount:.2f}:{(currency or '')}",
                    import_source="revolut_csv",
                    match_status="unmatched",
                )
                db.add(bt)
                existing.add(key)
                created += 1
                per_currency[currency or "?"] = per_currency.get(currency or "?", 0) + 1

                # Fee row, if present and non-zero. Revolut's Fee column
                # is positive (the fee charged); we emit it as a negative
                # outflow so the running balance lines up. Fee is in the
                # same currency as the transaction.
                fee = _parse_amount(row.get("Fee"))
                if args.include_fees and fee is not None and fee != 0:
                    fee_desc = f"Fee for {full_desc[:120]}"
                    fee_key = _dedup_key(tx_date, -abs(fee), fee_desc, currency)
                    if fee_key not in existing:
                        db.add(BankTransaction(
                            bank_account_id=ba.id,
                            date=tx_date,
                            amount=-abs(fee),
                            payee=fee_desc[:200],
                            description=fee_desc,
                            currency=currency,
                            import_id=f"revolut:{idx}:fee:{tx_date.isoformat()}:{abs(fee):.2f}:{(currency or '')}",
                            import_source="revolut_csv",
                            match_status="unmatched",
                        ))
                        existing.add(fee_key)
                        fee_rows += 1
                        per_currency[currency or "?"] = per_currency.get(currency or "?", 0) + 1

        if args.dry_run:
            print("DRY RUN — no rows committed")
            db.rollback()
        else:
            db.commit()

        print()
        print(f"  Created:                {created:,}")
        print(f"  Fee rows (subset):      {fee_rows:,}")
        print(f"  Dedupe-skipped:         {dups:,}")
        print(f"  Skipped non-COMPLETED:  {skipped_state:,}")
        print(f"  Skipped malformed:      {skipped_bad:,}")
        print()
        print("  Per currency:")
        for ccy in sorted(per_currency):
            print(f"    {ccy:<6} {per_currency[ccy]:,}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
