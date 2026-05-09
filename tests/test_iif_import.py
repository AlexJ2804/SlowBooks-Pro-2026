"""IIF import tests — common case coverage.

The handler only understands INVOICE, PAYMENT, and ESTIMATE blocks. For the
common-case QB export convention (SPL amounts stored with opposite sign from
the AR debit), the abs()-based parse is correct. Edge cases like mixed-sign
SPL lines (e.g. discount lines) are a known limitation — separate work item.
"""
from decimal import Decimal


INVOICE_IIF = (
    "!TRNS\tTRNSID\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tTERMS\n"
    "!SPL\tSPLID\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tINVITEM\tQNTY\tPRICE\n"
    "!ENDTRNS\n"
    "TRNS\t1\tINVOICE\t2026-04-01\tAccounts Receivable\tAcme Co\t108.75\tINV-001\tNet 30\n"
    "SPL\t2\tINVOICE\t2026-04-01\tService Income\tAcme Co\t-100.00\t\t1\t100.00\n"
    "SPL\t3\tINVOICE\t2026-04-01\tSales Tax Payable\tAcme Co\t-8.75\t\t\t\n"
    "ENDTRNS\n"
)


def test_iif_import_invoice_common_case(db_session, seed_accounts, seed_classes):
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.invoices import Invoice
    from app.models.contacts import Customer

    # Ensure a customer exists to avoid the auto-create path complicating the test
    db_session.add(Customer(name="Acme Co", is_active=True))
    db_session.commit()

    parsed = parse_iif(INVOICE_IIF)
    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    assert result["imported"]["invoices"] == 1, result
    invoice = db_session.query(Invoice).filter_by(invoice_number="INV-001").first()
    assert invoice is not None
    assert invoice.total == Decimal("108.75")
    # Subtotal = sum of non-tax SPL amounts (absolute value convention)
    assert invoice.subtotal == Decimal("100.00")
    assert invoice.tax_amount == Decimal("8.75")

    # Journal entry should exist and be balanced
    assert invoice.transaction_id is not None
    from app.models.transactions import TransactionLine
    lines = db_session.query(TransactionLine).filter_by(
        transaction_id=invoice.transaction_id,
    ).all()
    total_dr = sum((Decimal(str(l.debit)) for l in lines), Decimal("0"))
    total_cr = sum((Decimal(str(l.credit)) for l in lines), Decimal("0"))
    assert total_dr == total_cr == Decimal("108.75")


def test_iif_import_dedupes_on_doc_number(db_session, seed_accounts, seed_classes):
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.invoices import Invoice
    from app.models.contacts import Customer

    db_session.add(Customer(name="Acme Co", is_active=True))
    db_session.commit()

    parsed = parse_iif(INVOICE_IIF)
    import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    # Re-import same IIF — should be a no-op (existing doc number detected)
    import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    assert db_session.query(Invoice).filter_by(invoice_number="INV-001").count() == 1


# ============================================================================
# BILL import tests
#
# Sign convention (standard QB IIF for BILL): TRNS line carries the
# AP-account amount as NEGATIVE; SPL line(s) carry expense-account amounts
# as POSITIVE. They must sum to zero. The IIF below mirrors the May 2026
# bulk-import test file: two simple Apple Store bills with $1 and $2 totals.
# ============================================================================

BILL_IIF = (
    "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tDUEDATE\tTERMS\tMEMO\n"
    "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tMEMO\n"
    "!ENDTRNS\n"
    "TRNS\tBILL\t05/01/2026\tAccounts Payable\tApple Store\t-1.00\tTEST-001\t05/31/2026\tNet 30\tIIF import test #1\n"
    "SPL\tBILL\t05/01/2026\tOffice Supplies\tApple Store\t1.00\tTEST-001\ttest expense line\n"
    "ENDTRNS\n"
    "TRNS\tBILL\t05/01/2026\tAccounts Payable\tApple Store\t-2.00\tTEST-002\t05/31/2026\tNet 30\tIIF import test #2\n"
    "SPL\tBILL\t05/01/2026\tOffice Supplies\tApple Store\t2.00\tTEST-002\ttest expense line 2\n"
    "ENDTRNS\n"
)


def _seed_apple_vendor(db_session):
    from app.models.contacts import Vendor
    v = Vendor(name="Apple Store", is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def test_iif_import_bill_happy_path(db_session, seed_accounts, seed_classes):
    """The acceptance criterion from the bulk-import spec: drop the test
    IIF in, get 2 bills with bill_numbers TEST-001/TEST-002, status UNPAID,
    totals $1 and $2, vendor=Apple Store."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.bills import Bill, BillStatus

    _seed_apple_vendor(db_session)

    parsed = parse_iif(BILL_IIF)
    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    assert result["imported"]["bills"] == 2, result
    assert result["errors"] == [], result["errors"]

    bills = db_session.query(Bill).order_by(Bill.bill_number).all()
    assert [b.bill_number for b in bills] == ["TEST-001", "TEST-002"]
    assert all(b.status == BillStatus.UNPAID for b in bills)
    assert [b.total for b in bills] == [Decimal("1.00"), Decimal("2.00")]
    assert all(b.vendor.name == "Apple Store" for b in bills)
    # Each bill has one BillLine pointed at the Office Supplies account.
    for b in bills:
        assert len(b.lines) == 1
        assert b.lines[0].account.name == "Office Supplies"
    # Each bill has a balanced journal entry (DR Expense, CR AP).
    from app.models.transactions import TransactionLine
    for b in bills:
        assert b.transaction_id is not None
        lines = db_session.query(TransactionLine).filter_by(transaction_id=b.transaction_id).all()
        total_dr = sum((Decimal(str(l.debit)) for l in lines), Decimal("0"))
        total_cr = sum((Decimal(str(l.credit)) for l in lines), Decimal("0"))
        assert total_dr == total_cr == b.total


def test_iif_import_bill_missing_vendor_returns_error_no_partial(db_session, seed_accounts, seed_classes):
    """Spec: don't auto-create vendors. Surface the missing name so the
    user can fix Vendors first."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.bills import Bill

    # Note: NO _seed_apple_vendor call — vendor doesn't exist.
    parsed = parse_iif(BILL_IIF)
    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    assert result["imported"]["bills"] == 0
    assert len(result["errors"]) == 2
    msgs = [e["message"] for e in result["errors"]]
    assert all("Apple Store" in m for m in msgs), msgs
    assert all("vendor" in m.lower() and "not found" in m.lower() for m in msgs), msgs
    # No partial Bill rows were left behind by the savepoint rollback.
    assert db_session.query(Bill).count() == 0


def test_iif_import_bill_missing_account_returns_error_no_partial(db_session, seed_accounts, seed_classes):
    """Same defensive posture for the SPL expense account: error out,
    don't silently fall back to a default expense category."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.bills import Bill

    _seed_apple_vendor(db_session)

    bad_iif = (
        "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\n"
        "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\n"
        "!ENDTRNS\n"
        "TRNS\tBILL\t05/01/2026\tAccounts Payable\tApple Store\t-1.00\tTEST-A\n"
        # This account doesn't exist in the seeded chart.
        "SPL\tBILL\t05/01/2026\tHovercraft Repairs\tApple Store\t1.00\n"
        "ENDTRNS\n"
    )
    parsed = parse_iif(bad_iif)
    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    assert result["imported"]["bills"] == 0
    assert len(result["errors"]) == 1
    assert "Hovercraft Repairs" in result["errors"][0]["message"]
    assert "not found" in result["errors"][0]["message"].lower()
    assert db_session.query(Bill).count() == 0


def test_iif_import_bill_unbalanced_block_rejected(db_session, seed_accounts, seed_classes):
    """TRNS + SPL must sum to zero. If they don't, refuse rather than
    posting an unbalanced bill — an unbalanced source block usually
    means a hand-edited IIF where a line got dropped."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.bills import Bill

    _seed_apple_vendor(db_session)

    # TRNS=-1, SPL=2 -> residual=1, rejected.
    unbalanced = (
        "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\n"
        "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\n"
        "!ENDTRNS\n"
        "TRNS\tBILL\t05/01/2026\tAccounts Payable\tApple Store\t-1.00\tTEST-UNB\n"
        "SPL\tBILL\t05/01/2026\tOffice Supplies\tApple Store\t2.00\n"
        "ENDTRNS\n"
    )
    parsed = parse_iif(unbalanced)
    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    assert result["imported"]["bills"] == 0
    assert len(result["errors"]) == 1
    assert "sum to zero" in result["errors"][0]["message"].lower()
    assert db_session.query(Bill).count() == 0


def test_iif_import_bill_dedupes_on_docnum(db_session, seed_accounts, seed_classes):
    """Same (vendor, bill_number) twice must result in one bill row.
    Idempotent re-runs are required so the user can re-import after
    fixing earlier failures without double-counting. The duplicates
    bumped during the second pass surface in counts['duplicates_skipped']
    so the UI can show 'Skipped 2 duplicates' instead of a confusing
    silent zero."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.bills import Bill

    _seed_apple_vendor(db_session)

    parsed = parse_iif(BILL_IIF)
    first = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()
    assert first["imported"]["bills"] == 2
    assert first["imported"]["duplicates_skipped"] == 0
    assert db_session.query(Bill).count() == 2

    # Re-import the same IIF — no new rows, no errors, both blocks
    # logged as duplicates.
    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()
    assert result["imported"]["bills"] == 0
    assert result["imported"]["duplicates_skipped"] == 2
    assert result["errors"] == []
    assert db_session.query(Bill).count() == 2


# ---- CLASS handling on SPL lines -------------------------------------------

# Schema constraint pinned by the BILL CLASS tests below: BillLine has no
# class_id column, so SPL.CLASS collapses to Bill.class_id at the entity
# level. If multiple SPLs in a BILL block disagree on CLASS we refuse —
# silently picking one would be a worse failure mode for financial data.

BILL_WITH_CLASS_IIF = (
    "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\n"
    "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tCLASS\n"
    "!ENDTRNS\n"
    "TRNS\tBILL\t05/01/2026\tAccounts Payable\tApple Store\t-7.50\tTEST-CLS\n"
    "SPL\tBILL\t05/01/2026\tOffice Supplies\tApple Store\t7.50\tClass A\n"
    "ENDTRNS\n"
)


def test_iif_import_bill_with_valid_class_lands_on_bill_class_id(
    db_session, seed_accounts, seed_classes
):
    """SPL.CLASS resolves by name and lands on Bill.class_id (the
    schema's only place to put it). Same value flows into the journal
    entry's Transaction.class_id via create_journal_entry."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.bills import Bill
    from app.models.transactions import Transaction

    _seed_apple_vendor(db_session)
    parsed = parse_iif(BILL_WITH_CLASS_IIF)
    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    assert result["imported"]["bills"] == 1, result
    assert result["errors"] == [], result["errors"]
    bill = db_session.query(Bill).filter_by(bill_number="TEST-CLS").first()
    assert bill is not None
    assert bill.class_id == seed_classes["Class A"].id, (
        f"expected Class A id={seed_classes['Class A'].id}, got {bill.class_id}"
    )
    # The bill's journal entry inherits the same class.
    txn = db_session.query(Transaction).filter_by(id=bill.transaction_id).first()
    assert txn.class_id == seed_classes["Class A"].id


def test_iif_import_bill_with_unknown_class_returns_error(
    db_session, seed_accounts, seed_classes
):
    """Strict CLASS lookup — same posture as missing vendor or account.
    Don't auto-create classes; surface the bad name so the user can
    decide whether to add it or fix the IIF."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.bills import Bill

    _seed_apple_vendor(db_session)
    bad_iif = BILL_WITH_CLASS_IIF.replace("Class A", "Phantom Class")
    parsed = parse_iif(bad_iif)
    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    assert result["imported"]["bills"] == 0
    assert len(result["errors"]) == 1
    msg = result["errors"][0]["message"]
    assert "Phantom Class" in msg
    assert "class" in msg.lower() and "not found" in msg.lower(), msg
    assert db_session.query(Bill).count() == 0


def test_iif_import_bill_falls_back_to_uncategorized_when_no_class(
    db_session, seed_accounts, seed_classes
):
    """No CLASS column / empty CLASS values keep the existing
    Uncategorized behaviour — the BILL_IIF used elsewhere in this file
    has no CLASS column at all and lands on Uncategorized."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.bills import Bill

    _seed_apple_vendor(db_session)
    parsed = parse_iif(BILL_IIF)
    import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    bills = db_session.query(Bill).all()
    assert len(bills) == 2
    for b in bills:
        assert b.class_id == seed_classes["Uncategorized"].id


def test_iif_import_bill_uses_vendor_default_class_when_iif_has_no_class(
    db_session, seed_accounts, seed_classes
):
    """When the IIF has no CLASS column but the vendor has a
    default_class_id set, the bill auto-tags to the vendor's default
    instead of falling through to Uncategorized. This is the per-vendor
    auto-tagging path used to send TJX/Menards/Home Depot bills to the
    Airbnb class without modifying the Apps Script IIF generator."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.bills import Bill
    from app.models.contacts import Vendor

    v = _seed_apple_vendor(db_session)
    v.default_class_id = seed_classes["Class A"].id
    db_session.commit()

    parsed = parse_iif(BILL_IIF)
    import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    bills = db_session.query(Bill).all()
    assert len(bills) == 2
    for b in bills:
        assert b.class_id == seed_classes["Class A"].id


def test_iif_import_bill_iif_class_wins_over_vendor_default(
    db_session, seed_accounts, seed_classes
):
    """An explicit CLASS in the IIF SPL row beats the vendor's default —
    the IIF is the more specific instruction. Without this guard, every
    bill from a default-class vendor would silently ignore class
    overrides the user typed into the source spreadsheet."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.bills import Bill

    v = _seed_apple_vendor(db_session)
    # Vendor default is Class A, but the IIF below explicitly sets Class B.
    v.default_class_id = seed_classes["Class A"].id
    db_session.commit()

    iif_with_class = (
        "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tDUEDATE\tTERMS\tMEMO\n"
        "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tCLASS\tMEMO\n"
        "!ENDTRNS\n"
        "TRNS\tBILL\t05/01/2026\tAccounts Payable\tApple Store\t-1.00\tCLS-001\t05/31/2026\tNet 30\toverride test\n"
        "SPL\tBILL\t05/01/2026\tOffice Supplies\tApple Store\t1.00\tCLS-001\tClass B\toverride line\n"
        "ENDTRNS\n"
    )
    parsed = parse_iif(iif_with_class)
    import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    bills = db_session.query(Bill).all()
    assert len(bills) == 1
    assert bills[0].class_id == seed_classes["Class B"].id, (
        "explicit IIF CLASS must override vendor default_class_id"
    )


# ============================================================================
# DEPOSIT import tests
# ============================================================================

DEPOSIT_IIF = (
    "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tMEMO\n"
    "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO\n"
    "!ENDTRNS\n"
    # TRNS positive on bank, SPL negative on income — the inverse of BILL.
    "TRNS\tDEPOSIT\t05/02/2026\tChecking\t\t150.00\tDEP-001\tConsulting income deposit\n"
    "SPL\tDEPOSIT\t05/02/2026\tService Income\t\t-150.00\tConsulting fees\n"
    "ENDTRNS\n"
)


def test_iif_import_deposit_happy_path(db_session, seed_accounts, seed_classes):
    """Deposit creates a journal-only Transaction with source_type='deposit',
    DR bank, CR income — same shape as the manual Make Deposits route."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.transactions import Transaction, TransactionLine

    parsed = parse_iif(DEPOSIT_IIF)
    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    assert result["imported"]["deposits"] == 1, result
    assert result["errors"] == [], result["errors"]

    txn = db_session.query(Transaction).filter_by(source_type="deposit", reference="DEP-001").first()
    assert txn is not None
    lines = db_session.query(TransactionLine).filter_by(transaction_id=txn.id).all()
    assert len(lines) == 2

    bank_line = next(l for l in lines if l.account.name == "Checking")
    income_line = next(l for l in lines if l.account.name == "Service Income")
    assert bank_line.debit == Decimal("150.00") and bank_line.credit == 0
    assert income_line.credit == Decimal("150.00") and income_line.debit == 0


def test_iif_import_deposit_missing_account_rejected(db_session, seed_accounts, seed_classes):
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.transactions import Transaction

    bad_iif = (
        "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\n"
        "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\n"
        "!ENDTRNS\n"
        "TRNS\tDEPOSIT\t05/02/2026\tNonexistent Bank\t\t100.00\tDEP-X\n"
        "SPL\tDEPOSIT\t05/02/2026\tService Income\t\t-100.00\n"
        "ENDTRNS\n"
    )
    parsed = parse_iif(bad_iif)
    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()

    assert result["imported"]["deposits"] == 0
    assert len(result["errors"]) == 1
    assert "Nonexistent Bank" in result["errors"][0]["message"]
    # No partial Transaction row was committed.
    assert db_session.query(Transaction).filter_by(source_type="deposit").count() == 0


def test_iif_import_deposit_dedupes_on_docnum_date_and_amount(
    db_session, seed_accounts, seed_classes
):
    """Same (DOCNUM, date, amount) tuple → second import dedups and
    bumps duplicates_skipped. Re-imports of unchanged IIF must remain
    idempotent so the Gmail scraper can safely re-run."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.transactions import Transaction

    parsed = parse_iif(DEPOSIT_IIF)
    import_transactions(db_session, parsed["TRNS"])
    db_session.commit()
    assert db_session.query(Transaction).filter_by(source_type="deposit").count() == 1

    result = import_transactions(db_session, parsed["TRNS"])
    db_session.commit()
    assert result["imported"]["deposits"] == 0
    assert result["imported"]["duplicates_skipped"] == 1
    assert db_session.query(Transaction).filter_by(source_type="deposit").count() == 1


def test_iif_import_deposit_does_not_dedupe_when_amount_differs(
    db_session, seed_accounts, seed_classes
):
    """Same DOCNUM + same date but a DIFFERENT amount = not the same
    deposit. The dedup tuple now includes amount so a corrected re-import
    (e.g. user fixed a typo and re-ran the scraper) lands as a new row
    instead of being silently swallowed by the previous wrong-amount
    record."""
    from app.services.iif_import import parse_iif, import_transactions
    from app.models.transactions import Transaction

    parsed = parse_iif(DEPOSIT_IIF)
    import_transactions(db_session, parsed["TRNS"])
    db_session.commit()
    assert db_session.query(Transaction).filter_by(source_type="deposit").count() == 1

    different_amount_iif = (
        "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tDOCNUM\tMEMO\n"
        "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO\n"
        "!ENDTRNS\n"
        # Same DOCNUM + date as DEPOSIT_IIF, different amount.
        "TRNS\tDEPOSIT\t05/02/2026\tChecking\t\t99.99\tDEP-001\tCorrected amount\n"
        "SPL\tDEPOSIT\t05/02/2026\tService Income\t\t-99.99\tCorrected amount\n"
        "ENDTRNS\n"
    )
    parsed2 = parse_iif(different_amount_iif)
    result = import_transactions(db_session, parsed2["TRNS"])
    db_session.commit()

    assert result["imported"]["deposits"] == 1, result
    assert result["imported"]["duplicates_skipped"] == 0
    assert db_session.query(Transaction).filter_by(source_type="deposit").count() == 2


# ============================================================================
# import_all integration: counts roll up correctly into the result schema
# ============================================================================

def test_import_all_reports_bills_and_deposits_in_result(db_session, seed_accounts, seed_classes):
    """The route returns the result dict directly to the UI; the UI
    enumerates Bills/Deposits rows. Pin that the orchestrator
    populates both keys so the UI never sees Imported 0 again."""
    from app.services.iif_import import import_all

    # Seed Apple Store so the BILL portion succeeds.
    from app.models.contacts import Vendor
    db_session.add(Vendor(name="Apple Store", is_active=True))
    db_session.commit()

    # Combined IIF: 2 bills + 1 deposit.
    combined = BILL_IIF + DEPOSIT_IIF
    result = import_all(db_session, combined)

    assert result["bills"] == 2, result
    assert result["deposits"] == 1, result
    assert result["errors"] == [], result["errors"]
