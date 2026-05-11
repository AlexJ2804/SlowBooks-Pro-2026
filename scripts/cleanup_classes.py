"""One-shot cleanup of duplicate / leftover classes after the seed landed.

The seed (scripts/seed_business_classes.py) added the household's
canonical class taxonomy, but pre-existing rows from earlier
experiments left a handful of duplicates and stray test entries in
the classes table. This script reconciles them:

  Renames   — adjust a canonical name in-place (no row movement)
  Merges    — rewrite bank_rules.class_id + bank_transactions.class_id
              to the canonical class, then archive the source so it
              vanishes from the categorize dropdown but its history
              stays auditable
  Deletes   — for entries with zero references (test inputs), drop
              the row entirely. If references exist, archives instead
              so we never silently NULL-out tagged transactions.

Idempotent on every operation: re-running is a no-op once the desired
state is reached. Safe to run again after a future cleanup pass.

Apply:
    docker exec slowbooks-pro-2026-slowbooks-1 \\
        python -m scripts.cleanup_classes
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func

from app.database import SessionLocal
from app.models.bank_rules import BankRule
from app.models.banking import BankTransaction
from app.models.classes import Class


# Rename: rewrite the canonical class name in place. Used to clarify
# the seeded "Alex Music (1099)" as US-specific (the household also
# has a separate Canadian music class).
_RENAMES = [
    ("Alex Music (1099)", "Alex Music US (1099)"),
]


# Merge: each entry rewrites every bank_rules + bank_transactions
# reference from `source` → `target`, then archives `source`. Lookups
# are case-insensitive on name so capitalization variants (e.g.
# "Airbnb income from US Home" vs "AirBnB") match cleanly.
_MERGES = [
    ("Airbnb income from US Home",   "AirBnB"),
    ("PEJR LLC",                     "Alex PEJR LLC (1099)"),
    ("Wife 1099 (US)",               "Alexa VIPKid (1099)"),
    ("Alex 1099 (US)",               "Alex Consulting"),
    ("Income: Sandhills Brewing W2", "Alex W-2 (US)"),
]


# Delete (or archive if still referenced): leftover test entries and
# any other class names the user explicitly wants gone. If a delete
# target has bank_rules / bank_transactions referencing it, the script
# archives instead — guarantees no silent data loss.
_DELETES = [
    "TestInline",
    "TestRefresh",
]


def _find_class(db, name: str):
    return (
        db.query(Class)
        .filter(func.lower(Class.name) == name.lower())
        .first()
    )


def apply(db) -> dict:
    counts = {
        "renamed": 0, "rename_skipped": 0,
        "merged_rules": 0, "merged_txns": 0, "merge_archived": 0, "merge_skipped": 0,
        "deleted": 0, "delete_archived": 0, "delete_skipped": 0,
    }

    # 1) Renames
    for old, new in _RENAMES:
        row = _find_class(db, old)
        if row is None:
            # Maybe already renamed?
            already = _find_class(db, new)
            if already:
                counts["rename_skipped"] += 1
                print(f"  rename: '{old}' not found (target '{new}' already exists)")
            else:
                print(f"  rename: '{old}' not found, '{new}' not present either — nothing to do")
                counts["rename_skipped"] += 1
            continue
        # If target name already taken by a different row, fall through
        # to merge instead so we don't get a unique-constraint blowup.
        clash = _find_class(db, new)
        if clash and clash.id != row.id:
            print(f"  rename: target name '{new}' already taken by id={clash.id}; "
                  f"merging id={row.id} into it instead")
            _merge_into(db, row, clash, counts)
            continue
        row.name = new
        counts["renamed"] += 1
        print(f"  renamed id={row.id}: '{old}' → '{new}'")

    db.flush()

    # 2) Merges
    for source_name, target_name in _MERGES:
        source = _find_class(db, source_name)
        target = _find_class(db, target_name)
        if target is None:
            print(f"  merge: target class '{target_name}' missing; skipping merge of '{source_name}'")
            counts["merge_skipped"] += 1
            continue
        if source is None:
            counts["merge_skipped"] += 1
            print(f"  merge: source class '{source_name}' not present — already merged or never existed")
            continue
        if source.id == target.id:
            counts["merge_skipped"] += 1
            print(f"  merge: '{source_name}' and '{target_name}' are the same row; skipping")
            continue
        _merge_into(db, source, target, counts)

    db.flush()

    # 3) Deletes (or archive if still referenced after merges)
    for name in _DELETES:
        row = _find_class(db, name)
        if row is None:
            counts["delete_skipped"] += 1
            print(f"  delete: '{name}' not present — already removed")
            continue
        rule_refs = db.query(BankRule).filter(BankRule.class_id == row.id).count()
        txn_refs = db.query(BankTransaction).filter(BankTransaction.class_id == row.id).count()
        if rule_refs == 0 and txn_refs == 0:
            db.delete(row)
            counts["deleted"] += 1
            print(f"  deleted id={row.id} '{name}' (no references)")
        else:
            row.is_archived = True
            counts["delete_archived"] += 1
            print(f"  archived id={row.id} '{name}' "
                  f"(still referenced by {rule_refs} rule(s), {txn_refs} txn(s) — refusing delete)")

    db.flush()
    return counts


def _merge_into(db, source: Class, target: Class, counts: dict):
    """Move every bank_rules + bank_transactions reference from
    `source.id` → `target.id`, then archive the source. Counts are
    aggregated into the shared counts dict so the CLI summary stays
    honest across both rename-collisions and explicit merges."""
    rules = (
        db.query(BankRule)
        .filter(BankRule.class_id == source.id)
        .all()
    )
    for r in rules:
        r.class_id = target.id
    counts["merged_rules"] += len(rules)

    txns = (
        db.query(BankTransaction)
        .filter(BankTransaction.class_id == source.id)
        .all()
    )
    for t in txns:
        t.class_id = target.id
    counts["merged_txns"] += len(txns)

    if not source.is_archived:
        source.is_archived = True
    counts["merge_archived"] += 1
    print(f"  merged id={source.id} '{source.name}' → id={target.id} '{target.name}' "
          f"({len(rules)} rule(s), {len(txns)} txn(s))")


def main():
    db = SessionLocal()
    try:
        print("Class cleanup — applying renames, merges, deletes")
        print("-" * 60)
        counts = apply(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print("-" * 60)
    print(f"Renamed:           {counts['renamed']:>4}   (skipped {counts['rename_skipped']})")
    print(f"Merged classes:    {counts['merge_archived']:>4}   "
          f"({counts['merged_rules']} rules + {counts['merged_txns']} txns rewritten; "
          f"skipped {counts['merge_skipped']})")
    print(f"Deleted:           {counts['deleted']:>4}   "
          f"(archived {counts['delete_archived']}, skipped {counts['delete_skipped']})")
    print()
    print("Done. Refresh /#/categorize to see the cleaned-up Class dropdown.")


if __name__ == "__main__":
    main()
