"""Tests for /api/receipts/parse and /api/receipts/attach.

The Anthropic API call inside parse_receipt() is patched to return a
canned envelope — we never touch the network. Token-store state is
reset between cases so they don't see each other's leftovers.
"""

import io
import json
from unittest import mock

import pytest


def _anthropic_envelope(payload: dict) -> str:
    return json.dumps({
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "model": "claude-haiku-4-5-20251001",
        "role": "assistant",
        "stop_reason": "end_turn",
    })


def _mock_response(body: str, status: int = 200):
    resp = mock.MagicMock()
    resp.status = status
    resp.read.return_value = body.encode("utf-8")
    resp.__enter__ = mock.MagicMock(return_value=resp)
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


@pytest.fixture(autouse=True)
def _reset_token_store():
    from app.services import receipt_token_store
    receipt_token_store._reset_for_tests()
    yield
    receipt_token_store._reset_for_tests()


def _enable_parser(client, api_key="sk-ant-test-1234567890wxyz"):
    """Set the feature flag and API key. Returns the masked GET response."""
    r = client.put("/api/settings", json={
        "receipt_parser_enabled": "true",
        "anthropic_api_key": api_key,
    })
    assert r.status_code == 200
    return r.json()


# ---------- Feature-flag and config gating ----------------------------------

def test_parse_returns_403_when_feature_disabled(client):
    # Default is disabled.
    r = client.post(
        "/api/receipts/parse",
        files={"file": ("r.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"].lower()


def test_parse_returns_400_when_api_key_missing(client):
    client.put("/api/settings", json={"receipt_parser_enabled": "true"})
    r = client.post(
        "/api/receipts/parse",
        files={"file": ("r.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    assert r.status_code == 400
    assert "API key" in r.json()["detail"]


def test_parse_returns_415_for_unsupported_mime(client):
    _enable_parser(client)
    r = client.post(
        "/api/receipts/parse",
        files={"file": ("r.svg", b"<svg/>", "image/svg+xml")},
    )
    assert r.status_code == 415


def test_parse_returns_413_for_oversized_file(client):
    _enable_parser(client)
    # Configure max=5 MB and upload 6 MB of zeros.
    client.put("/api/settings", json={"receipt_parser_max_file_size_mb": "5"})
    big = b"\x00" * (6 * 1024 * 1024)
    r = client.post(
        "/api/receipts/parse",
        files={"file": ("big.pdf", big, "application/pdf")},
    )
    assert r.status_code == 413
    assert "limit" in r.json()["detail"].lower()


# ---------- Successful parse + attach round-trip -----------------------------

def test_parse_success_returns_token_and_increments_counter(client):
    _enable_parser(client)
    parsed_payload = {
        "vendor_name": "Pret A Manger",
        "date": "2026-04-15",
        "currency": "GBP",
        "order_number": "ORD-2026-04-15-0042",
        "subtotal": 8.5, "tax": 0.42, "total": 8.92,
        "line_items": [{"description": "Sandwich", "quantity": 1, "rate": 5.5, "amount": 5.5}],
        "suggested_expense_account_keywords": ["meals"],
    }
    with mock.patch(
        "app.services.receipt_parser.urllib.request.urlopen",
        return_value=_mock_response(_anthropic_envelope(parsed_payload)),
    ):
        r = client.post(
            "/api/receipts/parse",
            files={"file": ("r.jpg", b"\xff\xd8\xff" + b"x" * 100, "image/jpeg")},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert body["parsed"]["vendor_name"] == "Pret A Manger"
    # order_number must pass through the route boundary verbatim — the
    # frontend reads this field and maps it to the bill_number form
    # input. If this assertion fails, the upload-receipt → bill flow
    # leaves Bill Number blank again (the bug that motivated phase-4-fix).
    assert body["parsed"]["order_number"] == "ORD-2026-04-15-0042"
    assert body["attachment_token"]
    assert body["filename"] == "r.jpg"

    # Counter incremented for the current month.
    from datetime import datetime
    key = f"receipts_parsed_count_{datetime.utcnow().strftime('%Y%m')}"
    settings = client.get("/api/settings").json()
    assert settings.get(key) == "1"


def test_parse_failure_does_not_increment_counter(client):
    _enable_parser(client)
    # API returns 401 → parser surfaces error, route returns 200 with error
    # field set. Counter must NOT bump on failed parses.
    import urllib.error
    err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"{}"))
    with mock.patch(
        "app.services.receipt_parser.urllib.request.urlopen",
        side_effect=err,
    ):
        r = client.post(
            "/api/receipts/parse",
            files={"file": ("r.jpg", b"\xff\xd8\xff", "image/jpeg")},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["parsed"] is None
    assert "401" in body["error"]
    # Token IS still issued so the user can attach the original file even
    # if parsing failed (we want to keep the receipt either way).
    assert body["attachment_token"]

    from datetime import datetime
    key = f"receipts_parsed_count_{datetime.utcnow().strftime('%Y%m')}"
    settings = client.get("/api/settings").json()
    assert key not in settings or settings.get(key) in ("0", None)


def test_attach_round_trip_creates_attachment_and_invalidates_token(
    client, db_session, seed_accounts, seed_classes
):
    """Full flow: parse, save a bill (manually via /bills), attach, verify
    the Attachment row exists and the token is single-use."""
    _enable_parser(client)
    # Stand up a vendor for the bill.
    from app.models.contacts import Vendor
    v = Vendor(name="V", is_active=True)
    db_session.add(v)
    db_session.commit()

    # Parse a fake receipt to mint a token.
    with mock.patch(
        "app.services.receipt_parser.urllib.request.urlopen",
        return_value=_mock_response(_anthropic_envelope({"vendor_name": "V"})),
    ):
        r = client.post(
            "/api/receipts/parse",
            files={"file": ("r.png", b"\x89PNG" + b"\x00" * 50, "image/png")},
        )
    assert r.status_code == 200, r.text
    token = r.json()["attachment_token"]

    # Save a bill (via the existing bills route).
    r = client.post("/api/bills", json={
        "vendor_id": v.id,
        "bill_number": "B-RECEIPT",
        "date": "2026-04-15",
        "tax_rate": 0,
        "class_id": seed_classes["Class A"].id,
        "lines": [{"description": "X", "quantity": 1, "rate": 10.0, "line_order": 0}],
    })
    assert r.status_code == 201, r.text
    bill_id = r.json()["id"]

    # Attach.
    r = client.post(
        "/api/receipts/attach",
        data={"bill_id": str(bill_id), "attachment_token": token},
    )
    assert r.status_code == 200, r.text
    assert r.json()["attachment_id"]

    # The Attachment row exists.
    from app.models.attachments import Attachment
    rows = (
        db_session.query(Attachment)
        .filter(Attachment.entity_type == "bill", Attachment.entity_id == bill_id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].mime_type == "image/png"

    # Token is single-use — second attach attempt should 410.
    r = client.post(
        "/api/receipts/attach",
        data={"bill_id": str(bill_id), "attachment_token": token},
    )
    assert r.status_code == 410


def test_attach_with_unknown_token_returns_410(client, db_session, seed_accounts, seed_classes):
    _enable_parser(client)
    from app.models.contacts import Vendor
    v = Vendor(name="V", is_active=True)
    db_session.add(v)
    db_session.commit()
    r = client.post("/api/bills", json={
        "vendor_id": v.id,
        "bill_number": "B-1",
        "date": "2026-04-15",
        "tax_rate": 0,
        "class_id": seed_classes["Class A"].id,
        "lines": [{"description": "X", "quantity": 1, "rate": 10.0, "line_order": 0}],
    })
    bill_id = r.json()["id"]
    r = client.post(
        "/api/receipts/attach",
        data={"bill_id": str(bill_id), "attachment_token": "bogus"},
    )
    assert r.status_code == 410


def test_attach_with_unknown_bill_returns_404(client):
    r = client.post(
        "/api/receipts/attach",
        data={"bill_id": "9999999", "attachment_token": "doesnt-matter"},
    )
    assert r.status_code == 404


# ---------- Settings masking + sentinel preservation ------------------------

def test_anthropic_api_key_masked_on_get(client):
    _enable_parser(client, api_key="sk-ant-1234567890ABCDEFwxyz")
    settings = client.get("/api/settings").json()
    masked = settings["anthropic_api_key"]
    assert "sk-ant-1234567890" not in masked, "full key must not be returned"
    assert masked.endswith("wxyz"), f"masked value should end in last 4: got {masked!r}"
    assert "•" in masked


def test_put_with_masked_sentinel_preserves_stored_key(client):
    """If the frontend echoes back the masked GET value (because the user
    didn't change the API key field), PUT must NOT overwrite the stored
    key with bullets."""
    _enable_parser(client, api_key="sk-ant-realreal-1234")
    masked = client.get("/api/settings").json()["anthropic_api_key"]
    # Submit it back unchanged along with another setting.
    r = client.put("/api/settings", json={
        "anthropic_api_key": masked,
        "receipt_parser_model": "claude-sonnet-4-6",
    })
    assert r.status_code == 200
    # GET still shows a real masked key (last 4 still "1234").
    re_get = client.get("/api/settings").json()
    assert re_get["anthropic_api_key"].endswith("1234")
    assert re_get["receipt_parser_model"] == "claude-sonnet-4-6"

    # Now actually change it.
    r = client.put("/api/settings", json={"anthropic_api_key": "sk-ant-new-9999"})
    assert client.get("/api/settings").json()["anthropic_api_key"].endswith("9999")


def test_pre_existing_secrets_stay_plaintext(client):
    """Documented inconsistency: phase 4 only masks anthropic_api_key.
    Pre-existing sensitive keys are still returned plaintext until the
    follow-up cleanup commit. This test pins the boundary so the
    follow-up doesn't surprise anyone."""
    client.put("/api/settings", json={
        "stripe_secret_key": "sk_test_pretend",
        "smtp_password": "pretend-pw",
    })
    settings = client.get("/api/settings").json()
    assert settings["stripe_secret_key"] == "sk_test_pretend"
    assert settings["smtp_password"] == "pretend-pw"
