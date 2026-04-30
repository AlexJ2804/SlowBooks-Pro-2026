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
    fenced = "```json\n" + json.dumps({"vendor_name": "Test"}) + "\n```"
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
        return _mock_response(_anthropic_envelope(json.dumps({"vendor_name": "x"})))

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
        return _mock_response(_anthropic_envelope(json.dumps({"vendor_name": "x"})))

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
    payload = json.dumps({"vendor_name": "X", "currency": "usd "})
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
    payload = json.dumps({"vendor_name": "X", "date": "April 15, 2026"})
    with mock.patch.object(
        receipt_parser.urllib.request, "urlopen",
        return_value=_mock_response(_anthropic_envelope(payload)),
    ):
        result = receipt_parser.parse_receipt(b"img", "image/jpeg", SETTINGS_OK)
    assert result["parsed"]["date"] is None
