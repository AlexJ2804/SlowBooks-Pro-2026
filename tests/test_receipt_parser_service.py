"""Receipt parser service tests.

Mocks urllib.request.urlopen so no real Anthropic API call is ever made.
Covers the schema sanitisation, error paths, and the privacy guard that
strips fields outside the expected schema (e.g. if the model leaks
something like "card_number_last_4", we don't propagate it).
"""

import io
import json
from unittest import mock

import pytest


def _mock_response(body, status=200):
    """Build a mock object that quacks like the urlopen context-manager result."""
    mock_resp = mock.MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = body.encode("utf-8") if isinstance(body, str) else body
    mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = mock.MagicMock(return_value=False)
    return mock_resp


def _anthropic_envelope(text_payload):
    """Wrap a text payload in the shape Anthropic /v1/messages returns."""
    return json.dumps({
        "content": [{"type": "text", "text": text_payload}],
        "model": "claude-haiku-4-5-20251001",
        "role": "assistant",
        "stop_reason": "end_turn",
    })


SETTINGS_OK = {
    "anthropic_api_key": "sk-ant-test-1234567890abcdefwxyz",
    "receipt_parser_model": "claude-haiku-4-5-20251001",
}


def test_parse_clean_json_returns_correct_dict():
    from app.services import receipt_parser
    payload = {
        "vendor_name": "Pret A Manger",
        "date": "2026-04-15",
        "currency": "GBP",
        "subtotal": 8.50,
        "tax": 0.42,
        "total": 8.92,
        "line_items": [
            {"description": "Sandwich", "quantity": 1, "rate": 5.50, "amount": 5.50},
            {"description": "Coffee", "quantity": 1, "rate": 3.00, "amount": 3.00},
        ],
        "suggested_expense_account_keywords": ["meals", "office"],
    }
    with mock.patch.object(
        receipt_parser.urllib.request, "urlopen",
        return_value=_mock_response(_anthropic_envelope(json.dumps(payload))),
    ):
        result = receipt_parser.parse_receipt(b"fakeimg", "image/jpeg", SETTINGS_OK)
    assert result["error"] is None
    p = result["parsed"]
    assert p["vendor_name"] == "Pret A Manger"
    assert p["date"] == "2026-04-15"
    assert p["currency"] == "GBP"
    assert p["total"] == 8.92
    assert len(p["line_items"]) == 2
    assert p["suggested_expense_account_keywords"] == ["meals", "office"]


def test_parse_malformed_json_returns_error():
    from app.services import receipt_parser
    with mock.patch.object(
        receipt_parser.urllib.request, "urlopen",
        return_value=_mock_response(_anthropic_envelope("not json at all {{{")),
    ):
        result = receipt_parser.parse_receipt(b"fakeimg", "image/jpeg", SETTINGS_OK)
    assert result["parsed"] is None
    assert "malformed" in result["error"].lower()


def test_parse_strips_markdown_fences_around_json():
    """The system prompt forbids markdown fences but models occasionally add them anyway."""
    from app.services import receipt_parser
    # Include a total so we don't accidentally trip the Sonnet retry —
    # this test is about fence stripping, not retry behaviour.
    fenced = "```json\n" + json.dumps({"vendor_name": "Test", "total": 1.0, "date": "2026-04-15"}) + "\n```"
    with mock.patch.object(
        receipt_parser.urllib.request, "urlopen",
        return_value=_mock_response(_anthropic_envelope(fenced)),
    ):
        result = receipt_parser.parse_receipt(b"fakeimg", "image/jpeg", SETTINGS_OK)
    assert result["error"] is None
    assert result["parsed"]["vendor_name"] == "Test"


def test_parse_drops_unexpected_top_level_fields():
    """Privacy guard: even if the model sneaks in a card_number key, we drop it.
    Pins the spec rule that downstream callers only see the expected schema."""
    from app.services import receipt_parser
    leak = json.dumps({
        "vendor_name": "Shell",
        "total": 50.00,
        "card_number_last_4": "4242",       # must not be in result
        "customer_signature_present": True,  # must not be in result
    })
    with mock.patch.object(
        receipt_parser.urllib.request, "urlopen",
        return_value=_mock_response(_anthropic_envelope(leak)),
    ):
        result = receipt_parser.parse_receipt(b"fakeimg", "image/jpeg", SETTINGS_OK)
    p = result["parsed"]
    assert "card_number_last_4" not in p
    assert "customer_signature_present" not in p
    # Schema fields still come through.
    assert p["vendor_name"] == "Shell"
    assert p["total"] == 50.0


def test_parse_401_returns_auth_error():
    from app.services import receipt_parser
    import urllib.error
    err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"{}"))
    with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=err):
        result = receipt_parser.parse_receipt(b"fakeimg", "image/jpeg", SETTINGS_OK)
    assert result["parsed"] is None
    assert "401" in result["error"]
    # Must not echo the body of the error response (could contain prompt fragments).
    assert "Unauthorized" not in result["error"]


def test_parse_timeout_returns_timeout_error():
    from app.services import receipt_parser
    with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=TimeoutError("timed out")):
        result = receipt_parser.parse_receipt(b"fakeimg", "image/jpeg", SETTINGS_OK)
    assert result["parsed"] is None
    assert "timed out" in result["error"].lower()


def test_parse_missing_api_key():
    from app.services import receipt_parser
    result = receipt_parser.parse_receipt(b"fakeimg", "image/jpeg", {"anthropic_api_key": ""})
    assert result["parsed"] is None
    assert "key" in result["error"].lower()


def test_parse_unsupported_mime_rejected_locally():
    """Defensive — the route also enforces this, but the service refuses
    to send anything outside the allowlist so a future caller can't bypass."""
    from app.services import receipt_parser
    result = receipt_parser.parse_receipt(b"fakebytes", "image/svg+xml", SETTINGS_OK)
    assert result["parsed"] is None
    assert "MIME" in result["error"] or "type" in result["error"].lower()


def test_parse_oversized_image_rejected_before_api_call():
    from app.services import receipt_parser
    big = b"\x00" * (6 * 1024 * 1024)  # 6 MB > 5 MB API cap
    with mock.patch.object(receipt_parser.urllib.request, "urlopen") as urlopen:
        result = receipt_parser.parse_receipt(big, "image/jpeg", SETTINGS_OK)
        # We rejected before reaching the network.
        urlopen.assert_not_called()
    assert result["parsed"] is None


def test_parse_request_body_shape():
    """Pin the request shape: model, system prompt, vision content block,
    max_tokens, headers. Anyone refactoring the call must keep this stable."""
    from app.services import receipt_parser
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["timeout"] = timeout
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data.decode("utf-8"))
        # Include a total — this test pins the FIRST call's shape, and
        # we don't want a Sonnet retry overwriting `captured` from the
        # second call's body.
        return _mock_response(_anthropic_envelope(
            json.dumps({"vendor_name": "x", "total": 1.0, "date": "2026-04-15"})
        ))

    with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=fake_urlopen):
        receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["timeout"] == 30
    # Headers (urllib lowercases them in the dict)
    headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers_lower.get("x-api-key") == SETTINGS_OK["anthropic_api_key"]
    assert headers_lower.get("anthropic-version") == "2023-06-01"
    body = captured["body"]
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["max_tokens"] >= 256
    assert "system" in body
    # Content has an image block + a text block.
    msg = body["messages"][0]
    types = [b["type"] for b in msg["content"]]
    assert "image" in types
    assert "text" in types


def test_parse_pdf_first_page_extraction():
    """Multi-page PDFs are reduced to page 1 before sending — cost guard."""
    from app.services import receipt_parser
    # Build a tiny 2-page PDF with pypdf.
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    w.write(buf)
    two_page_bytes = buf.getvalue()

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        # total set so we don't trigger a Sonnet retry — this test
        # pins page-1 extraction on the FIRST call.
        return _mock_response(_anthropic_envelope(
            json.dumps({"vendor_name": "x", "total": 1.0, "date": "2026-04-15"})
        ))

    with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=fake_urlopen):
        receipt_parser.parse_receipt(two_page_bytes, "application/pdf", SETTINGS_OK)

    # Decode the PDF that was sent and confirm it has exactly 1 page.
    import base64
    from pypdf import PdfReader
    sent_b64 = captured["body"]["messages"][0]["content"][0]["source"]["data"]
    sent_pdf = base64.b64decode(sent_b64)
    reader = PdfReader(io.BytesIO(sent_pdf))
    assert len(reader.pages) == 1, "multi-page PDF should be trimmed to page 1 before sending"


def test_parse_normalises_currency_strings():
    """If the model returns 'usd' lowercase or extra whitespace, normalise."""
    from app.services import receipt_parser
    # total included so this stays a single-call test.
    payload = json.dumps({"vendor_name": "X", "currency": "usd ", "total": 1.0, "date": "2026-04-15"})
    with mock.patch.object(
        receipt_parser.urllib.request, "urlopen",
        return_value=_mock_response(_anthropic_envelope(payload)),
    ):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)
    assert result["parsed"]["currency"] == "USD"


def test_parse_invalid_date_becomes_null():
    """Defensive: if the model emits a date in some other format, drop it
    rather than passing garbage to the bill form."""
    from app.services import receipt_parser
    # total included so this stays a single-call test (Sonnet retry only
    # fires on null total, not null date).
    payload = json.dumps({"vendor_name": "X", "date": "April 15, 2026", "total": 1.0})
    with mock.patch.object(
        receipt_parser.urllib.request, "urlopen",
        return_value=_mock_response(_anthropic_envelope(payload)),
    ):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)
    assert result["parsed"]["date"] is None


# ----- order_number ---------------------------------------------------------

def test_parse_extracts_order_number():
    """The schema now includes order_number — make sure it survives sanitisation."""
    from app.services import receipt_parser
    payload = {
        "vendor_name": "Apple",
        "date": "2026-04-15",
        "currency": "USD",
        "order_number": "W1591651266",
        "total": 544.93,
        "subtotal": 499.00,
        "tax": 45.93,
        "line_items": [],
        "suggested_expense_account_keywords": ["software"],
    }
    with mock.patch.object(
        receipt_parser.urllib.request, "urlopen",
        return_value=_mock_response(_anthropic_envelope(json.dumps(payload))),
    ):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)
    assert result["parsed"]["order_number"] == "W1591651266"


def test_parse_preserves_real_world_punctuation_in_order_number():
    """Utility bills routinely use slashes / dashes / dots / parens. The
    sanitiser must not strip those — only enforce the length cap."""
    from app.services import receipt_parser
    samples = [
        "INV-2026-0042",
        "ACC/12345",
        "Bill #00123-A",
        "(KS-44.78)",
        "REF.2026.04.15",
    ]
    for raw in samples:
        payload = json.dumps({
            "vendor_name": "X", "total": 1.0, "date": "2026-04-15",
            "order_number": raw,
        })
        with mock.patch.object(
            receipt_parser.urllib.request, "urlopen",
            return_value=_mock_response(_anthropic_envelope(payload)),
        ):
            result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)
        assert result["parsed"]["order_number"] == raw, f"sanitiser mangled {raw!r}"


def test_parse_drops_order_number_if_not_string():
    """Defense in depth: if the model returns a non-string for
    order_number (number, list, object), we drop it to None rather
    than coercing."""
    from app.services import receipt_parser
    for bad in (12345, ["a", "b"], {"x": 1}, True):
        payload = json.dumps({
            "vendor_name": "X", "total": 1.0, "date": "2026-04-15",
            "order_number": bad,
        })
        with mock.patch.object(
            receipt_parser.urllib.request, "urlopen",
            return_value=_mock_response(_anthropic_envelope(payload)),
        ):
            result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)
        assert result["parsed"]["order_number"] is None, f"got {result['parsed']['order_number']!r} for input {bad!r}"


def test_parse_truncates_overly_long_order_number():
    """Length cap: a runaway model dumping a paragraph into the field
    is cut off at 64 chars rather than passed through."""
    from app.services import receipt_parser
    long_value = "X" * 200
    payload = json.dumps({
        "vendor_name": "Y", "total": 1.0, "date": "2026-04-15",
        "order_number": long_value,
    })
    with mock.patch.object(
        receipt_parser.urllib.request, "urlopen",
        return_value=_mock_response(_anthropic_envelope(payload)),
    ):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)
    assert len(result["parsed"]["order_number"]) == 64
    assert result["parsed"]["order_number"] == "X" * 64


# ----- Sonnet retry on null total -------------------------------------------

def _haiku_envelope(parsed_payload):
    """Convenience: wrap a parser-output dict in the API response envelope."""
    return _mock_response(_anthropic_envelope(json.dumps(parsed_payload)))


def test_retries_with_sonnet_when_total_is_null():
    """First call (Haiku) returns parsed but null total; service retries
    with Sonnet 4.6 and uses the Sonnet result."""
    from app.services import receipt_parser
    haiku_response = {
        "vendor_name": "Apple", "date": "2026-04-15", "currency": "USD",
        "total": None, "subtotal": None, "tax": None,
        "line_items": [], "suggested_expense_account_keywords": [],
    }
    sonnet_response = {
        "vendor_name": "Apple", "date": "2026-04-15", "currency": "USD",
        "total": 544.93, "subtotal": 499.00, "tax": 45.93,
        "line_items": [{"description": "iPad", "quantity": 1, "rate": 499.00, "amount": 499.00}],
        "suggested_expense_account_keywords": ["software"],
    }

    captured_models = []

    def fake_urlopen(req, timeout=None):
        captured_models.append(json.loads(req.data.decode("utf-8"))["model"])
        if len(captured_models) == 1:
            return _haiku_envelope(haiku_response)
        return _haiku_envelope(sonnet_response)

    with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=fake_urlopen):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)

    assert len(captured_models) == 2, "expected exactly two HTTP calls"
    assert captured_models[0] == "claude-haiku-4-5-20251001"
    assert captured_models[1] == receipt_parser._RETRY_MODEL == "claude-sonnet-4-6"
    assert result["error"] is None
    # Sonnet result wins.
    assert result["parsed"]["total"] == 544.93
    assert result["parsed"]["subtotal"] == 499.00


def test_no_retry_when_first_call_returns_total():
    """Common path: Haiku extracts the total cleanly, no retry, single API call."""
    from app.services import receipt_parser
    payload = {
        "vendor_name": "Home Depot", "date": "2026-04-15", "currency": "USD",
        "total": 47.93, "subtotal": 47.93, "tax": 0.0,
        "line_items": [], "suggested_expense_account_keywords": ["repairs"],
    }
    call_count = [0]

    def fake_urlopen(req, timeout=None):
        call_count[0] += 1
        return _haiku_envelope(payload)

    with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=fake_urlopen):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)

    assert call_count[0] == 1, "Haiku-only path must not call Anthropic twice"
    assert result["parsed"]["total"] == 47.93


def test_uses_sonnet_result_even_when_sonnet_total_also_null():
    """Per spec: 'If Sonnet also returns null, use Sonnet's result anyway.'
    Sonnet may have improved line items or other fields even without a total."""
    from app.services import receipt_parser
    haiku_response = {
        "vendor_name": "X", "date": "2026-04-15", "currency": None,
        "total": None, "line_items": [], "suggested_expense_account_keywords": [],
    }
    sonnet_response = {
        "vendor_name": "X", "date": "2026-04-15", "currency": "USD",  # currency improved
        "total": None,                                                 # still null
        "line_items": [{"description": "Item A", "quantity": 1, "rate": 0.0, "amount": 0.0}],
        "suggested_expense_account_keywords": ["meals"],
    }
    responses = [_haiku_envelope(haiku_response), _haiku_envelope(sonnet_response)]
    with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=responses):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)

    # Sonnet result wins unconditionally — even though its total is also null.
    assert result["parsed"]["currency"] == "USD"
    assert result["parsed"]["suggested_expense_account_keywords"] == ["meals"]


def test_no_retry_when_first_call_errors():
    """Sonnet retry fires only on parsed-but-null-total. Transport/auth
    errors fall straight through — retrying Sonnet on a 401 would just
    fail again with the same auth problem."""
    from app.services import receipt_parser
    import urllib.error
    err = io.BytesIO(b"{}")
    http_err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, err)

    call_count = [0]

    def fake_urlopen(req, timeout=None):
        call_count[0] += 1
        raise http_err

    with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=fake_urlopen):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)

    assert call_count[0] == 1, "401 must not trigger a Sonnet retry"
    assert result["parsed"] is None
    assert "401" in result["error"]


def test_retry_falls_back_to_primary_when_sonnet_errors():
    """If the Sonnet retry transport-fails (timeout, network, 429),
    keep the primary's partial parse rather than losing all data."""
    from app.services import receipt_parser

    haiku_response = {
        "vendor_name": "X", "date": "2026-04-15", "currency": "USD",
        "total": None,
        "line_items": [{"description": "A", "quantity": 1, "rate": 10.0, "amount": 10.0}],
        "suggested_expense_account_keywords": [],
    }
    call_count = [0]

    def fake_urlopen(req, timeout=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return _haiku_envelope(haiku_response)
        # Second call (Sonnet) explodes.
        raise TimeoutError("simulated retry timeout")

    with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=fake_urlopen):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)

    assert call_count[0] == 2
    assert result["error"] is None
    # Haiku's partial parse survived — line items are still there.
    assert result["parsed"]["vendor_name"] == "X"
    assert len(result["parsed"]["line_items"]) == 1


def test_retry_logs_event(caplog):
    """When the retry fires, an INFO-level log line is emitted. No
    receipt content in the log message."""
    import logging
    from app.services import receipt_parser

    haiku_response = {"vendor_name": "X", "date": "2026-04-15", "total": None,
                      "line_items": [], "suggested_expense_account_keywords": []}
    sonnet_response = {"vendor_name": "X", "date": "2026-04-15", "total": 1.0,
                       "line_items": [], "suggested_expense_account_keywords": []}

    responses = [_haiku_envelope(haiku_response), _haiku_envelope(sonnet_response)]

    with caplog.at_level(logging.INFO, logger="app.services.receipt_parser"):
        with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=responses):
            receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)

    msgs = [r.getMessage() for r in caplog.records if r.name == "app.services.receipt_parser"]
    assert any("retrying" in m.lower() for m in msgs), msgs
    # No receipt content in any log message.
    for m in msgs:
        assert "vendor_name" not in m
        assert "X" not in m or "Sonnet" in m or "Haiku" in m or "claude" in m.lower()


def test_haiku_partial_parse_sonnet_worse():
    """Pin the deliberate "always use Sonnet" choice.

    Scenario: Haiku extracts useful partial data (line items present,
    total null). Sonnet retry returns LESS data (line items empty, total
    still null). Per spec, we use the Sonnet result anyway — the rule is
    "use Sonnet's result whether or not it improved totals."

    Why pin this: it's a deliberate simplicity choice. Merging Haiku +
    Sonnet outputs (e.g. take Sonnet's total but keep Haiku's line items
    if Sonnet drops them) would be more useful in this exact scenario,
    but adds branchy logic for an unusual case. If real-world data shows
    Sonnet regressing fields meaningfully, revisit by introducing a
    merge step here. Until then this test pins the simple behaviour so
    the choice is explicit and reviewable.
    """
    from app.services import receipt_parser
    haiku_response = {
        "vendor_name": "Pret A Manger", "date": "2026-04-15", "currency": "GBP",
        "total": None, "subtotal": None, "tax": None,
        "line_items": [
            {"description": "Sandwich", "quantity": 1, "rate": 5.50, "amount": 5.50},
            {"description": "Coffee", "quantity": 1, "rate": 3.00, "amount": 3.00},
        ],
        "suggested_expense_account_keywords": ["meals"],
    }
    sonnet_response = {
        "vendor_name": "Pret A Manger", "date": "2026-04-15", "currency": "GBP",
        "total": None, "subtotal": None, "tax": None,
        "line_items": [],            # WORSE than Haiku
        "suggested_expense_account_keywords": [],   # WORSE than Haiku
    }
    responses = [_haiku_envelope(haiku_response), _haiku_envelope(sonnet_response)]
    with mock.patch.object(receipt_parser.urllib.request, "urlopen", side_effect=responses):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)

    # Sonnet's (worse) output wins unconditionally.
    assert result["parsed"]["line_items"] == []
    assert result["parsed"]["suggested_expense_account_keywords"] == []
    # Haiku's line items are GONE — this is the deliberate behaviour.
    # If you're reading this test because you're tempted to merge
    # Haiku+Sonnet results, review the `parse_receipt` docstring first.


# ----- Regression pin -------------------------------------------------------

def test_simple_clean_receipt_still_returns_full_fields():
    """A clean single-line receipt with every schema field populated
    must round-trip through _sanitize_parsed unchanged. Catches structural
    regressions in the sanitiser when the schema is extended."""
    from app.services import receipt_parser
    payload = {
        "vendor_name": "Pret A Manger",
        "date": "2026-04-15",
        "currency": "GBP",
        "order_number": "ORD-2026-04-15-0042",
        "subtotal": 8.50,
        "tax": 0.42,
        "total": 8.92,
        "line_items": [
            {"description": "Sandwich", "quantity": 1, "rate": 5.50, "amount": 5.50},
            {"description": "Coffee", "quantity": 1, "rate": 3.00, "amount": 3.00},
        ],
        "suggested_expense_account_keywords": ["meals"],
    }
    with mock.patch.object(
        receipt_parser.urllib.request, "urlopen",
        return_value=_mock_response(_anthropic_envelope(json.dumps(payload))),
    ):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)

    p = result["parsed"]
    # Every field present on output, matching input.
    assert p["vendor_name"] == "Pret A Manger"
    assert p["date"] == "2026-04-15"
    assert p["currency"] == "GBP"
    assert p["order_number"] == "ORD-2026-04-15-0042"
    assert p["subtotal"] == 8.50
    assert p["tax"] == 0.42
    assert p["total"] == 8.92
    assert len(p["line_items"]) == 2
    assert p["suggested_expense_account_keywords"] == ["meals"]
    # Schema-key shape: every expected key present, no extras.
    assert set(p.keys()) == receipt_parser._EXPECTED_KEYS
