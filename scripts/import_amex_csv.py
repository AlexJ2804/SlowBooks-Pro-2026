"""Import American Express activity CSVs into bank_transactions.

Amex's customer-facing CSV export uses these columns:
    Date, Description, Card Member, Account #, Amount, Extended Details,
    Appears On Your Statement As, Address, City/State, Zip Code, Country,
    Reference, Category

Sign convention (Amex):
    +amount  -> charge / interest / fee  (debt increases)
    -amount  -> payment received / refund (debt decreases)

This is exactly what credit_card storage in this app expects: the
positive number is "amount owed", and the credit-card-display flip on
the dashboard / banking page renders it as negative for the user.

Dedup uses the Reference column verbatim — Amex assigns a globally
unique transaction id, conveniently wrapped in single quotes (their
trick to defeat Excel's auto-format-as-number). When Reference is
missing for some reason, fall back to a content hash so the row can
still be inserted and re-imports stay idempotent.

Two cardholders (e.g. ALEXA + ALEXANDER) share one Amex account, so
all rows from both members land in the same bank_account. The card
member name is prefixed onto the description so the register shows
who charged what.

Usage:
    # one CSV
    docker exec slowbooks-pro-2026-slowbooks-1 \\
        python -m scripts.import_amex_csv \\
        --bank-account-id 8 --csv-path /tmp/amex/activity_2024-03.csv

    # whole directory of CSVs in one shot
    docker exec slowbooks-pro-2026-slowbooks-1 \\
        python -m scripts.import_amex_csv \\
        --bank-account-id 8 --csv-dir /tmp/amex

The CSV(s) need to be readable from inside the container — copy with
    docker cp ~/Downloads/AMEX slowbooks-pro-2026-slowbooks-1:/tmp/amex
"""

import argparse
import csv
import hashlib
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.banking import BankAccount, BankTransaction


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")
_DEDUP_DESC_LEN = 80


def _normalize_description(desc: str) -> str:
    if not desc:
        return ""
    return _NON_ALNUM_RE.sub("", desc.lower())[:_DEDUP_DESC_LEN]


def _strip_excel_quote(s: str) -> str:
    # Amex wraps Reference in a leading single quote so Excel doesn't
    # mangle it as a number. Strip both ends defensively.
    if not s:
        return ""
    s = s.strip()
    if s.startswith("'"):
        s = s[1:]
    if s.endswith("'"):
        s = s[:-1]
    return s


def _make_import_id(reference: str, date_iso: str, amount: float,
                    description: str, card_member: str) -> str:
    ref = _strip_excel_quote(reference)
    if ref:
        return f"amex:ref:{ref}"
    desc_hash = hashlib.sha1(
        _normalize_description(description).encode("utf-8")
    ).hexdigest()[:10]
    cm_hash = hashlib.sha1(
        (card_member or "").lower().encode("utf-8")
    ).hexdigest()[:6]
    return f"amex:hash:{date_iso}:{amount:+.2f}:{desc_hash}:{cm_hash}"


def _parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(s: str):
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("$", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _process_csv(db, ba_id: int, csv_path: Path, existing: set, totals: dict) -> None:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tx_date = _parse_date(row.get("Date"))
            amount = _parse_amount(row.get("Amount"))
            if tx_date is None or amount is None:
                totals["skipped_bad"] += 1
                continue

            description = (row.get("Description") or "").strip()
            card_member = (row.get("Card Member") or "").strip()
            extended = (row.get("Extended Details") or "").strip()
            category = (row.get("Category") or "").strip()
            reference = row.get("Reference") or ""

            # Compose a register-friendly payee: who charged + what
            # vendor + the high-level category. Extended details go in
            # the longer description field so the register stays readable.
            payee_bits = [description]
            if card_member:
                payee_bits.append(f"[{card_member}]")
            if category:
                payee_bits.append(f"({category})")
            payee = " ".join(payee_bits).strip()

            import_id = _make_import_id(reference, tx_date.isoformat(),
                                        amount, description, card_member)
            if import_id in existing:
                totals["dups"] += 1
                continue

            db.add(BankTransaction(
                bank_account_id=ba_id,
                date=tx_date,
                amount=amount,
                payee=payee[:200],
                description=(extended or payee)[:500],
                currency="USD",
                import_id=import_id,
                import_source="amex_csv",
                match_status="unmatched",
            ))
            existing.add(import_id)
            totals["created"] += 1
            totals["per_month"][tx_date.strftime("%Y-%m")] += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Amex activity CSV(s) into bank_transactions")
    parser.add_argument("--bank-account-id", type=int, required=True,
                        help="bank_accounts.id to attach every imported row to")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv-path", help="path to a single Amex activity CSV")
    src.add_argument("--csv-dir", help="directory; every *.csv inside is imported")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and report counts but don't commit")
    args = parser.parse_args()

    if args.csv_path:
        paths = [Path(args.csv_path)]
    else:
        d = Path(args.csv_dir)
        if not d.is_dir():
            print(f"ERROR: --csv-dir not a directory: {d}", file=sys.stderr)
            return 2
        paths = sorted(d.glob("*.csv"))
        if not paths:
            print(f"ERROR: no *.csv files under {d}", file=sys.stderr)
            return 2

    for p in paths:
        if not p.is_file():
            print(f"ERROR: CSV not found: {p}", file=sys.stderr)
            return 2

    db = SessionLocal()
    try:
        ba = db.query(BankAccount).filter(BankAccount.id == args.bank_account_id).first()
        if not ba:
            print(f"ERROR: bank_account id={args.bank_account_id} not found", file=sys.stderr)
            return 2
        print(f"Target: bank_account id={ba.id} '{ba.name}' "
              f"(linked to COA id={ba.account_id})")
        print(f"Files:  {len(paths)} CSV(s)")
        print()

        existing = {
            r[0] for r in (
                db.query(BankTransaction.import_id)
                .filter(BankTransaction.bank_account_id == ba.id)
                .filter(BankTransaction.import_source == "amex_csv")
                .filter(BankTransaction.import_id.isnot(None))
                .all()
            )
        }
        print(f"Loaded {len(existing)} existing amex_csv import_ids for dedup")
        print()

        totals = {
            "created": 0,
            "dups": 0,
            "skipped_bad": 0,
            "per_month": defaultdict(int),
        }

        for p in paths:
            before = totals["created"]
            _process_csv(db, ba.id, p, existing, totals)
            print(f"  {p.name:<50} +{totals['created'] - before:>5,} new rows")

        if args.dry_run:
            print()
            print("DRY RUN — no rows committed")
            db.rollback()
        else:
            db.commit()

        print()
        print(f"  Created:           {totals['created']:,}")
        print(f"  Dedupe-skipped:    {totals['dups']:,}")
        print(f"  Skipped malformed: {totals['skipped_bad']:,}")
        print()
        print("  Per month (months with zero rows in the imported range = candidate gaps):")
        if totals["per_month"]:
            months = sorted(totals["per_month"])
            start_y, start_m = (int(x) for x in months[0].split("-"))
            end_y, end_m = (int(x) for x in months[-1].split("-"))
            y, m = start_y, start_m
            while (y, m) <= (end_y, end_m):
                key = f"{y:04d}-{m:02d}"
                count = totals["per_month"].get(key, 0)
                marker = "  GAP <—" if count == 0 else ""
                print(f"    {key}  {count:>5,}{marker}")
                m += 1
                if m > 12:
                    m = 1
                    y += 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
