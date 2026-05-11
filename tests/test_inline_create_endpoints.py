"""Inline-create endpoint contracts.

Phase 3 hotfix: the InlineCreate JS module relies on each entity's POST
endpoint returning a body shaped { id, name, ... } so the parent form
can refresh its dropdown and select the new row.

These tests pin that contract for all four entity types the inline-create
modal can spawn (classes, vendors, customers, items) plus verify that GET
reflects the new row immediately — which is what the JS callback does
right after a successful POST.

We can't drive the actual <select> refresh from pytest (no JS runner in
this repo); these tests cover the seams instead.
"""


def _post(client, path, body):
    r = client.post(path, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ----- Class -----------------------------------------------------------------

def test_class_create_returns_id_and_name(client, seed_classes):
    body = _post(client, "/api/classes", {"name": "Inline-test Class"})
    assert isinstance(body.get("id"), int) and body["id"] > 0
    assert body["name"] == "Inline-test Class"
    assert body["is_archived"] is False
    assert body["is_system_default"] is False


def test_class_get_reflects_new_row(client, seed_classes):
    created = _post(client, "/api/classes", {"name": "Inline-test Class"})
    listed = client.get("/api/classes").json()
    ids = {c["id"] for c in listed}
    assert created["id"] in ids


# ----- Vendor ---------------------------------------------------------------

def test_vendor_create_returns_id_and_name(client, db_session):
    body = _post(client, "/api/vendors", {
        "name": "Inline-test Vendor",
        "email": "v@example.com",
        "phone": "555-0001",
    })
    assert isinstance(body.get("id"), int) and body["id"] > 0
    assert body["name"] == "Inline-test Vendor"


def test_vendor_create_minimal_fields_only(client, db_session):
    """The InlineCreate vendor config sends email/phone as null when blank.
    Endpoint must accept that — verifies the buildBody contract."""
    body = _post(client, "/api/vendors", {
        "name": "Minimal Vendor",
        "email": None,
        "phone": None,
    })
    assert body["name"] == "Minimal Vendor"


def test_vendor_get_reflects_new_row(client, db_session):
    created = _post(client, "/api/vendors", {"name": "Inline-test Vendor"})
    listed = client.get("/api/vendors?active_only=true").json()
    ids = {v["id"] for v in listed}
    assert created["id"] in ids


# ----- Customer -------------------------------------------------------------

def test_customer_create_returns_id_and_name(client, db_session):
    body = _post(client, "/api/customers", {
        "name": "Inline-test Customer",
        "email": "c@example.com",
        "phone": "555-0002",
    })
    assert isinstance(body.get("id"), int) and body["id"] > 0
    assert body["name"] == "Inline-test Customer"


def test_customer_create_minimal_fields_only(client, db_session):
    body = _post(client, "/api/customers", {
        "name": "Minimal Customer",
        "email": None,
        "phone": None,
    })
    assert body["name"] == "Minimal Customer"


def test_customer_get_reflects_new_row(client, db_session):
    created = _post(client, "/api/customers", {"name": "Inline-test Customer"})
    listed = client.get("/api/customers?active_only=true").json()
    ids = {c["id"] for c in listed}
    assert created["id"] in ids


# ----- Item ------------------------------------------------------------------

def test_item_create_returns_id_and_name(client, seed_accounts):
    income = seed_accounts["4000"]  # Service Income from the seeded chart
    body = _post(client, "/api/items", {
        "name": "Inline-test Item",
        "item_type": "service",
        "rate": "75.00",
        "income_account_id": income.id,
    })
    assert isinstance(body.get("id"), int) and body["id"] > 0
    assert body["name"] == "Inline-test Item"


def test_item_get_reflects_new_row(client, seed_accounts):
    income = seed_accounts["4000"]
    created = _post(client, "/api/items", {
        "name": "Inline-test Item",
        "item_type": "service",
        "rate": "75.00",
        "income_account_id": income.id,
    })
    listed = client.get("/api/items?active_only=true").json()
    ids = {i["id"] for i in listed}
    assert created["id"] in ids


# ----- The accounts filter the InlineCreate item modal depends on -----------

def test_accounts_filter_by_account_types_csv(client, seed_accounts):
    """The InlineCreate item modal populates its account dropdown from
    /accounts?account_types=income,expense — verify the filter actually
    returns both types and excludes others (assets, liabilities, equity)."""
    listed = client.get("/api/accounts?account_types=income,expense").json()
    types = {a["account_type"] for a in listed}
    assert types <= {"income", "expense"}, f"unexpected types: {types}"
    # Must include at least one of each (chart of accounts seeds 4000 income
    # and 6000 expense).
    assert "income" in types
    assert "expense" in types
