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


def test_parse_route_triggers_sonnet_retry_when_total_is_null(client):
    """Integration pin for the production failure case (May 2026):
    a Gmail-rendered Apple Store PDF where Haiku returns parsed-but-
    null-total. The route must drive the retry through to Sonnet 4.6
    and surface Sonnet's total in the response.

    This catches an entire class of regressions where the unit test
    passes but route-level integration breaks (settings plumbing,
    mime_type munging by FastAPI's UploadFile, etc.).
    """
    _enable_parser(client)
    haiku_response = {
        "vendor_name": "Apple Store",
        "date": "2026-04-30",
        "currency": None,
        "order_number": "W1591651266",
        "subtotal": None, "tax": None, "total": None,
        "line_items": [],
        "suggested_expense_account_keywords": ["equipment"],
    }
    sonnet_response = {
        "vendor_name": "Apple Store",
        "date": "2026-04-30",
        "currency": "USD",
        "order_number": "W1591651266",
        "subtotal": 499.00, "tax": 45.93, "total": 544.93,
        "line_items": [{"description": "iPad", "quantity": 1, "rate": 499.00, "amount": 499.00}],
        "suggested_expense_account_keywords": ["equipment"],
    }

    captured_models = []

    def fake_urlopen(req, timeout=None):
        captured_models.append(json.loads(req.data.decode("utf-8"))["model"])
        if len(captured_models) == 1:
            return _mock_response(_anthropic_envelope(haiku_response))
        return _mock_response(_anthropic_envelope(sonnet_response))

    with mock.patch(
        "app.services.receipt_parser.urllib.request.urlopen",
        side_effect=fake_urlopen,
    ):
        r = client.post(
            "/api/receipts/parse",
            files={"file": ("apple.pdf", b"%PDF-1.4\n" + b"x" * 200, "application/pdf")},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    # Both calls fired — this is the predicate-evaluates-True path.
    assert len(captured_models) == 2, (
        f"expected 2 Anthropic calls (Haiku then Sonnet retry), got {len(captured_models)}: "
        f"{captured_models}. If this is 1, the retry predicate evaluated False on the route path "
        f"despite evaluating True at the unit-test level."
    )
    assert captured_models[0] == "claude-haiku-4-5-20251001"
    assert captured_models[1] == "claude-sonnet-4-6"
    # Sonnet's total surfaced through the route boundary.
    assert body["parsed"]["total"] == 544.93
    assert body["parsed"]["currency"] == "USD"


def test_parse_route_handles_sonnet_response_with_prose_commentary(client):
    """Production failure case (May 2026): Sonnet 4.6 retry succeeded
    at the API level but returned its JSON wrapped in prose ("Looking at
    this receipt, ... {JSON} ... Let me know if you need anything!").
    The original parser rejected that as malformed JSON, silently fell
    back to Haiku's null-total result, and the user saw total=null in
    the UI despite a perfectly successful Sonnet call.

    Pin the fix at the route layer so a future regression in the JSON
    extractor surfaces immediately rather than via a customer report."""
    _enable_parser(client)

    haiku_response_text = json.dumps({
        "vendor_name": "Apple Store",
        "date": "2026-04-30",
        "currency": None,
        "order_number": "W1591651266",
        "subtotal": None, "tax": None, "total": None,
        "line_items": [],
        "suggested_expense_account_keywords": ["equipment"],
    })
    sonnet_inner_payload = {
        "vendor_name": "Apple Store",
        "date": "2026-04-30",
        "currency": "USD",
        "order_number": "W1591651266",
        "subtotal": 499.00, "tax": 45.93, "total": 544.93,
        "line_items": [{"description": "iPad", "quantity": 1, "rate": 499.00, "amount": 499.00}],
        "suggested_expense_account_keywords": ["equipment"],
    }
    sonnet_response_text = (
        "Looking at this Apple Store receipt, here's what I extracted:\n\n"
        + json.dumps(sonnet_inner_payload)
        + "\n\nThe order total is $544.93 USD. Let me know if you need any clarification."
    )

    def _envelope(text: str) -> str:
        return json.dumps({
            "content": [{"type": "text", "text": text}],
            "model": "claude-sonnet-4-6",
            "role": "assistant",
            "stop_reason": "end_turn",
        })

    call_idx = [0]

    def fake_urlopen(req, timeout=None):
        call_idx[0] += 1
        if call_idx[0] == 1:
            return _mock_response(_envelope(haiku_response_text))
        return _mock_response(_envelope(sonnet_response_text))

    with mock.patch(
        "app.services.receipt_parser.urllib.request.urlopen",
        side_effect=fake_urlopen,
    ):
        r = client.post(
            "/api/receipts/parse",
            files={"file": ("apple.pdf", b"%PDF-1.4\n" + b"x" * 200, "application/pdf")},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert call_idx[0] == 2, "expected Haiku then Sonnet retry"
    # Sonnet's prose-wrapped JSON was successfully extracted and
    # surfaced through the route boundary — the bug we're pinning.
    assert body["parsed"]["total"] == 544.93
    assert body["parsed"]["currency"] == "USD"
    assert body["parsed"]["vendor_name"] == "Apple Store"


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
