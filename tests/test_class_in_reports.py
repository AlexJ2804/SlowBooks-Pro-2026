"""P&L behaves correctly under class filtering and column-per-class breakdown."""


def _mk_invoice(client, customer_id, class_id, amount, date_="2026-04-01"):
    r = client.post("/api/invoices", json={
        "customer_id": customer_id,
        "date": date_,
        "terms": "Net 30",
        "tax_rate": "0",
        "class_id": class_id,
        "lines": [{"description": "S", "quantity": "1", "rate": amount, "line_order": 0}],
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_pl_filter_by_class_returns_only_that_class(
    client, seed_accounts, seed_customer, seed_classes
):
    a_id = seed_classes["Class A"].id
    b_id = seed_classes["Class B"].id
    _mk_invoice(client, seed_customer.id, a_id, "100.00")
    _mk_invoice(client, seed_customer.id, b_id, "300.00")

    r = client.get(f"/api/reports/profit-loss?class_id={a_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["class_id"] == a_id
    assert body["total_income"] == 100.00
    # Filtered response should not include the breakdown (only emitted when
    # no class filter is applied).
    assert "by_class_income" not in body


def test_pl_no_filter_includes_column_per_class_breakdown(
    client, seed_accounts, seed_customer, seed_classes
):
    a_id = seed_classes["Class A"].id
    b_id = seed_classes["Class B"].id
    _mk_invoice(client, seed_customer.id, a_id, "100.00")
    _mk_invoice(client, seed_customer.id, b_id, "300.00")

    r = client.get("/api/reports/profit-loss?start_date=2026-01-01&end_date=2026-12-31")
    assert r.status_code == 200
    body = r.json()
    assert body["class_id"] is None
    assert body["total_income"] == 400.00
    assert "classes" in body and len(body["classes"]) >= 3  # A, B, Uncategorized
    assert "by_class_income" in body

    # Each row's by_class values must sum to its `total`. Pins the user's
    # spec requirement: column-per-class breakdown sums equal grand total.
    for row in body["by_class_income"]:
        assert sum(row["by_class"].values()) == row["total"], row


def test_pl_grand_total_equals_sum_of_class_columns(
    client, seed_accounts, seed_customer, seed_classes
):
    a_id = seed_classes["Class A"].id
    b_id = seed_classes["Class B"].id
    _mk_invoice(client, seed_customer.id, a_id, "100.00")
    _mk_invoice(client, seed_customer.id, b_id, "250.00")

    r = client.get("/api/reports/profit-loss?start_date=2026-01-01&end_date=2026-12-31")
    body = r.json()

    # Sum of column totals (per class) across all income rows == grand
    # total_income. This is the second leg of the user's spec.
    column_totals = {}
    for row in body["by_class_income"]:
        for cid, amt in row["by_class"].items():
            column_totals[cid] = column_totals.get(cid, 0) + amt
    assert sum(column_totals.values()) == body["total_income"]


def test_pl_by_uncategorized_returns_only_uncategorized(
    client, seed_accounts, seed_customer, seed_classes
):
    """The system Uncategorized class is a normal filter target."""
    a_id = seed_classes["Class A"].id
    uncat_id = seed_classes["Uncategorized"].id
    _mk_invoice(client, seed_customer.id, a_id, "100.00")
    _mk_invoice(client, seed_customer.id, uncat_id, "50.00")

    r = client.get(f"/api/reports/profit-loss?class_id={uncat_id}")
    body = r.json()
    assert body["total_income"] == 50.00
