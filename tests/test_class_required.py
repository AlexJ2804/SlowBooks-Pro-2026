"""Every transaction-creating route must reject a missing class with HTTP 400.

Pins the exact error message so a future refactor can't silently relax this.
"""
import pytest


SPEC_MESSAGE = "Class is required. Pick a class before saving."


def test_invoice_create_rejects_missing_class(client, seed_accounts, seed_customer, seed_classes):
    r = client.post("/api/invoices", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-01",
        "terms": "Net 30",
        "tax_rate": "0",
        "lines": [{"description": "X", "quantity": "1", "rate": "100", "line_order": 0}],
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


def test_bill_create_rejects_missing_class(client, db_session, seed_accounts, seed_classes):
    from app.models.contacts import Vendor
    v = Vendor(name="V", is_active=True)
    db_session.add(v)
    db_session.commit()

    r = client.post("/api/bills", json={
        "vendor_id": v.id,
        "bill_number": "B-X",
        "date": "2026-04-01",
        "tax_rate": 0,
        "lines": [{"description": "X", "quantity": 1, "rate": 50.00, "line_order": 0}],
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


def test_payment_create_rejects_missing_class(client, seed_accounts, seed_customer, seed_classes):
    r = client.post("/api/payments", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-15",
        "amount": "100",
        "allocations": [],
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


def test_bill_payment_create_rejects_missing_class(client, db_session, seed_accounts, seed_classes):
    from app.models.contacts import Vendor
    v = Vendor(name="V", is_active=True)
    db_session.add(v)
    db_session.commit()

    r = client.post("/api/bill-payments", json={
        "vendor_id": v.id,
        "date": "2026-04-15",
        "amount": 100.00,
        "allocations": [],
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


def test_estimate_create_rejects_missing_class(client, seed_accounts, seed_customer, seed_classes):
    r = client.post("/api/estimates", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-01",
        "tax_rate": "0",
        "lines": [{"description": "X", "quantity": "1", "rate": "100", "line_order": 0}],
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


def test_credit_memo_create_rejects_missing_class(client, seed_accounts, seed_customer, seed_classes):
    r = client.post("/api/credit-memos", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-01",
        "tax_rate": 0,
        "lines": [{"description": "X", "quantity": 1, "rate": 50.0, "line_order": 0}],
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


def test_cc_charge_create_rejects_missing_class(client, db_session, seed_accounts, seed_classes):
    from app.models.accounts import Account, AccountType
    # Make sure CC account exists
    cc = db_session.query(Account).filter(Account.account_number == "2100").first()
    if not cc:
        cc = Account(account_number="2100", name="Credit Card",
                     account_type=AccountType.LIABILITY, is_system=True)
        db_session.add(cc)
    expense = db_session.query(Account).filter(Account.account_number == "6000").first()
    db_session.commit()

    r = client.post("/api/cc-charges", json={
        "date": "2026-04-15",
        "account_id": expense.id,
        "amount": "75.00",
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


def test_journal_create_rejects_missing_class(client, db_session, seed_accounts, seed_classes):
    from app.models.accounts import Account
    cash = db_session.query(Account).filter(Account.account_number == "1000").first()
    other = db_session.query(Account).filter(Account.account_number == "4000").first()
    r = client.post("/api/journal", json={
        "date": "2026-04-15",
        "description": "test",
        "lines": [
            {"account_id": cash.id, "debit": "10", "credit": "0"},
            {"account_id": other.id, "debit": "0", "credit": "10"},
        ],
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


def test_deposit_create_rejects_missing_class(client, db_session, seed_accounts, seed_classes):
    from app.models.accounts import Account
    bank = db_session.query(Account).filter(Account.account_number == "1000").first()
    r = client.post("/api/deposits", json={
        "deposit_to_account_id": bank.id,
        "date": "2026-04-15",
        "total": "100.00",
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


def test_recurring_create_rejects_missing_class(client, seed_accounts, seed_customer, seed_classes):
    r = client.post("/api/recurring", json={
        "customer_id": seed_customer.id,
        "frequency": "monthly",
        "start_date": "2026-04-01",
        "lines": [{"description": "X", "quantity": 1, "rate": 100.0, "line_order": 0}],
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


def test_batch_payment_create_rejects_missing_class(
    client, db_session, seed_accounts, seed_customer, seed_classes
):
    from app.models.invoices import Invoice
    from datetime import date
    inv = Invoice(
        invoice_number="INV-X", customer_id=seed_customer.id,
        date=date(2026, 4, 1), total=100, balance_due=100,
        class_id=seed_classes["Class A"].id,
    )
    db_session.add(inv)
    db_session.commit()
    r = client.post("/api/batch-payments", json={
        "date": "2026-04-15",
        "allocations": [{"customer_id": seed_customer.id, "invoice_id": inv.id, "amount": 100.0}],
    })
    assert r.status_code == 400
    assert r.json()["detail"] == SPEC_MESSAGE


# -------- Sanity check: providing a real class works for at least one route --------

def test_invoice_create_with_class_succeeds(client, seed_accounts, seed_customer, seed_classes):
    r = client.post("/api/invoices", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-01",
        "terms": "Net 30",
        "tax_rate": "0",
        "class_id": seed_classes["Class A"].id,
        "lines": [{"description": "X", "quantity": "1", "rate": "100", "line_order": 0}],
    })
    assert r.status_code == 201
    assert r.json()["class_id"] == seed_classes["Class A"].id


def test_archived_class_still_accepted_on_create(
    client, seed_accounts, seed_customer, seed_classes
):
    """Archive only hides from new-form dropdowns; existing references must
    still work, including new transactions if the user explicitly picks one."""
    cls_id = seed_classes["Class A"].id
    client.patch(f"/api/classes/{cls_id}", json={"is_archived": True})

    r = client.post("/api/invoices", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-01",
        "terms": "Net 30",
        "tax_rate": "0",
        "class_id": cls_id,
        "lines": [{"description": "X", "quantity": "1", "rate": "100", "line_order": 0}],
    })
    assert r.status_code == 201, r.text
