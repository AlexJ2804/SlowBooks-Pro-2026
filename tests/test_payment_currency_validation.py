"""Cross-currency payment / bill-payment validation.

Phase 2 multi-currency rule: a payment cannot be allocated to an invoice
(or bill) in a different currency. Cross-currency reconciliation is not
supported — the create endpoints must reject with HTTP 400 *before* any
DB write, regardless of what the frontend does.

These tests pin that behaviour so a future refactor can't silently break it.
"""
from decimal import Decimal


def _create_invoice_with_currency(client, customer_id, currency, amount="500.00"):
    """Create a sent invoice in the given currency and return the row dict."""
    body = {
        "customer_id": customer_id,
        "date": "2026-04-01",
        "terms": "Net 30",
        "tax_rate": "0",
        "currency": currency,
        "exchange_rate": "1.0820" if currency == "EUR" else "1",
        "lines": [
            {"description": "Line", "quantity": "1", "rate": amount, "line_order": 0}
        ],
    }
    r = client.post("/api/invoices", json=body)
    assert r.status_code == 201, r.text
    inv = r.json()
    # Move it out of draft so the payment form's invoice picker would show it.
    r = client.post(f"/api/invoices/{inv['id']}/send")
    assert r.status_code == 200, r.text
    return r.json()


def test_payment_against_same_currency_invoice_succeeds_usd(
    client, db_session, seed_accounts, seed_customer
):
    inv = _create_invoice_with_currency(client, seed_customer.id, "USD")
    r = client.post("/api/payments", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-15",
        "amount": "500.00",
        "currency": "USD",
        "exchange_rate": "1",
        "allocations": [{"invoice_id": inv["id"], "amount": "500.00"}],
    })
    assert r.status_code == 201, r.text
    assert r.json()["currency"] == "USD"


def test_payment_against_same_currency_invoice_succeeds_eur(
    client, db_session, seed_accounts, seed_customer
):
    inv = _create_invoice_with_currency(client, seed_customer.id, "EUR")
    r = client.post("/api/payments", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-15",
        "amount": "500.00",
        "currency": "EUR",
        "exchange_rate": "1.0820",
        "allocations": [{"invoice_id": inv["id"], "amount": "500.00"}],
    })
    assert r.status_code == 201, r.text
    assert r.json()["currency"] == "EUR"


def test_usd_payment_against_eur_invoice_is_rejected(
    client, db_session, seed_accounts, seed_customer
):
    inv = _create_invoice_with_currency(client, seed_customer.id, "EUR")
    r = client.post("/api/payments", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-15",
        "amount": "500.00",
        "currency": "USD",
        "exchange_rate": "1",
        "allocations": [{"invoice_id": inv["id"], "amount": "500.00"}],
    })
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    # Error must name both currencies and the invoice number so the user can
    # actually fix the request.
    assert "USD" in detail
    assert "EUR" in detail
    assert inv["invoice_number"] in detail

    # Most importantly: nothing was persisted.
    from app.models.payments import Payment
    assert db_session.query(Payment).count() == 0


def test_eur_payment_against_usd_invoice_is_rejected(
    client, db_session, seed_accounts, seed_customer
):
    inv = _create_invoice_with_currency(client, seed_customer.id, "USD")
    r = client.post("/api/payments", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-15",
        "amount": "500.00",
        "currency": "EUR",
        "exchange_rate": "1.0820",
        "allocations": [{"invoice_id": inv["id"], "amount": "500.00"}],
    })
    assert r.status_code == 400, r.text
    from app.models.payments import Payment
    assert db_session.query(Payment).count() == 0


def test_payment_with_no_allocations_saves_regardless_of_currency(
    client, db_session, seed_accounts, seed_customer
):
    """Unallocated payments are 'on account' credits — no invoice to mismatch."""
    r = client.post("/api/payments", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-15",
        "amount": "500.00",
        "currency": "EUR",
        "exchange_rate": "1.0820",
        "allocations": [],
    })
    assert r.status_code == 201, r.text


def test_payment_mismatch_on_one_of_many_allocations_rejects_all(
    client, db_session, seed_accounts, seed_customer
):
    """If even one of the allocations is in a mismatched currency, the entire
    request must reject — partial saves would corrupt the ledger."""
    inv_usd = _create_invoice_with_currency(client, seed_customer.id, "USD")
    inv_eur = _create_invoice_with_currency(client, seed_customer.id, "EUR")
    r = client.post("/api/payments", json={
        "customer_id": seed_customer.id,
        "date": "2026-04-15",
        "amount": "1000.00",
        "currency": "USD",
        "exchange_rate": "1",
        "allocations": [
            {"invoice_id": inv_usd["id"], "amount": "500.00"},
            {"invoice_id": inv_eur["id"], "amount": "500.00"},  # mismatch
        ],
    })
    assert r.status_code == 400, r.text
    from app.models.payments import Payment
    assert db_session.query(Payment).count() == 0


# -------- Bill-payment side: mirror the same rule for AP -------- #

def _create_vendor(db_session):
    from app.models.contacts import Vendor
    v = Vendor(name="Test Vendor", is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def _create_bill_with_currency(client, vendor_id, currency, amount="500.00"):
    r = client.post("/api/bills", json={
        "vendor_id": vendor_id,
        "bill_number": f"B-{currency}-{vendor_id}",
        "date": "2026-04-01",
        "terms": "Net 30",
        "tax_rate": 0,
        "currency": currency,
        "exchange_rate": 1.0820 if currency == "EUR" else 1,
        "lines": [
            {"description": "Line", "quantity": 1, "rate": float(amount), "line_order": 0}
        ],
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_bill_payment_currency_mismatch_is_rejected(
    client, db_session, seed_accounts
):
    vendor = _create_vendor(db_session)
    bill = _create_bill_with_currency(client, vendor.id, "EUR")
    r = client.post("/api/bill-payments", json={
        "vendor_id": vendor.id,
        "date": "2026-04-15",
        "amount": 500.00,
        "method": "check",
        "currency": "USD",
        "exchange_rate": 1,
        "allocations": [{"bill_id": bill["id"], "amount": 500.00}],
    })
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "USD" in detail and "EUR" in detail
    assert bill["bill_number"] in detail
    from app.models.bills import BillPayment
    assert db_session.query(BillPayment).count() == 0


def test_bill_payment_same_currency_succeeds(
    client, db_session, seed_accounts
):
    vendor = _create_vendor(db_session)
    bill = _create_bill_with_currency(client, vendor.id, "EUR")
    r = client.post("/api/bill-payments", json={
        "vendor_id": vendor.id,
        "date": "2026-04-15",
        "amount": 500.00,
        "method": "check",
        "currency": "EUR",
        "exchange_rate": 1.0820,
        "allocations": [{"bill_id": bill["id"], "amount": 500.00}],
    })
    assert r.status_code == 201, r.text
