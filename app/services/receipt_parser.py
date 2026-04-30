"""Receipt parser using the Anthropic Messages API (vision).

Same shape as fx_service: stdlib urllib.request, no new dependency on the
Anthropic SDK, all failures caught and surfaced as a structured result.
The route layer translates that into a 200 response with a JSON body so
the frontend can show "couldn't read this receipt" without exception
handling.

Privacy:
- Receipt content is never logged. Errors from this module include only
  generic descriptions ("HTTP 401 from Anthropic API"), not the request
  body or the model's response.
- The system prompt explicitly instructs the model to ignore card numbers
  and signatures. We additionally strip any field that isn't in the
  expected schema before returning, so even if the model leaks something
  in a stray key, we don't propagate it.
"""

import base64
import io
import json
import re
import urllib.request
import urllib.error
from typing import Optional


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
TIMEOUT_SECONDS = 30
MAX_TOKENS = 1024
ANTHROPIC_VERSION = "2023-06-01"

# Anthropic image limit (per API docs, late 2025): 5 MB per image. PDFs
# have a separate 32 MB / 100-page limit. The route layer also enforces
# the user-configured upload max — these constants exist as a defense in
# depth so this service never makes an obviously-doomed request.
MAX_IMAGE_BYTES = 5 * 1024 * 1024


SYSTEM_PROMPT = """You are extracting structured data from a receipt or invoice image.

Return ONLY valid JSON matching this exact schema. No markdown fences, no
commentary, no preamble:

{
  "vendor_name": string or null,
  "date": "YYYY-MM-DD" or null,
  "currency": ISO-4217 3-letter code (e.g. "USD", "EUR", "CAD") or null,
  "subtotal": number or null,
  "tax": number or null,
  "total": number or null,
  "line_items": [{"description": string, "quantity": number, "rate": number, "amount": number}],
  "suggested_expense_account_keywords": array of short strings
}

Rules:
- If a field isn't visible or you're not confident, set it to null. Do not
  guess.
- "vendor_name": the merchant/business name as printed (e.g. "Pret A
  Manger", "Shell"). Strip trailing location text.
- "date": the receipt date. If only a partial date is visible, use null.
- "currency": infer from the printed currency symbol or code. If only a
  bare "$" is shown with no country indicator, use null rather than
  guessing USD vs CAD.
- Numbers must be JSON numbers — no currency symbols, no thousands
  separators (1,234.56 -> 1234.56).
- "line_items" is the items list as printed. If quantity or rate isn't
  shown but amount is, set quantity=1, rate=amount.
- "suggested_expense_account_keywords": 1-3 short keywords matching
  common expense categories. Examples: "meals", "travel", "office",
  "software", "fuel", "utilities", "rent", "insurance".
- IGNORE card numbers, partial card numbers (the last-4 digits often
  printed on receipts), CVV, expiration dates, or any other payment
  instrument data. Do NOT include these in any field.
- IGNORE customer names and signatures if present.
- If the image is not a receipt or invoice, return all fields as null
  and an empty line_items array.

Return only the JSON object, nothing else.
"""


# Expected top-level keys. Anything else the model returns is dropped.
_EXPECTED_KEYS = {
    "vendor_name", "date", "currency", "subtotal", "tax", "total",
    "line_items", "suggested_expense_account_keywords",
}
_EXPECTED_LINE_KEYS = {"description", "quantity", "rate", "amount"}


def _err(message: str) -> dict:
    return {"parsed": None, "error": message}


def _extract_first_pdf_page(pdf_bytes: bytes) -> bytes:
    """Return a single-page PDF containing only page 1 of the input.

    Multi-page receipts are rare; the API charges per page processed.
    Capping at page 1 controls cost on accidentally-large uploads (e.g.
    a 20-page invoice scan). If pypdf can't parse the input, fall back
    to sending the original bytes — better to spend an extra few cents
    than to hard-fail an otherwise-valid receipt.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if len(reader.pages) <= 1:
            return pdf_bytes
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:
        return pdf_bytes


def _build_content_block(file_bytes: bytes, mime_type: str) -> dict:
    """Build the content block for either an image or a PDF document."""
    encoded = base64.b64encode(file_bytes).decode("ascii")
    if mime_type == "application/pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": encoded},
        }
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": mime_type, "data": encoded},
    }


def _coerce_number(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _sanitize_parsed(raw: dict) -> dict:
    """Return a dict containing ONLY the expected schema keys.

    Drops any unexpected top-level keys (defense in depth: even if the
    model invents a `card_number` field, we don't pass it to the
    frontend). Coerces number fields, normalises types.
    """
    if not isinstance(raw, dict):
        return _empty_schema()

    out = {
        "vendor_name": raw.get("vendor_name") if isinstance(raw.get("vendor_name"), str) else None,
        "date": raw.get("date") if _looks_like_date(raw.get("date")) else None,
        "currency": _normalise_currency(raw.get("currency")),
        "subtotal": _coerce_number(raw.get("subtotal")),
        "tax": _coerce_number(raw.get("tax")),
        "total": _coerce_number(raw.get("total")),
        "line_items": _sanitize_line_items(raw.get("line_items")),
        "suggested_expense_account_keywords": _sanitize_keywords(
            raw.get("suggested_expense_account_keywords")
        ),
    }
    return out


def _empty_schema() -> dict:
    return {
        "vendor_name": None,
        "date": None,
        "currency": None,
        "subtotal": None,
        "tax": None,
        "total": None,
        "line_items": [],
        "suggested_expense_account_keywords": [],
    }


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _looks_like_date(v) -> bool:
    return isinstance(v, str) and bool(_DATE_RE.match(v))


def _normalise_currency(v) -> Optional[str]:
    if not isinstance(v, str):
        return None
    s = v.strip().upper()
    if len(s) == 3 and s.isalpha():
        return s
    return None


def _sanitize_line_items(items) -> list:
    if not isinstance(items, list):
        return []
    cleaned = []
    for li in items:
        if not isinstance(li, dict):
            continue
        cleaned.append({
            "description": li.get("description") if isinstance(li.get("description"), str) else "",
            "quantity": _coerce_number(li.get("quantity")) or 1.0,
            "rate": _coerce_number(li.get("rate")) or 0.0,
            "amount": _coerce_number(li.get("amount")) or 0.0,
        })
    return cleaned


def _sanitize_keywords(kws) -> list:
    if not isinstance(kws, list):
        return []
    return [k.strip() for k in kws if isinstance(k, str) and k.strip()][:5]


def parse_receipt(file_bytes: bytes, mime_type: str, settings: dict) -> dict:
    """Send a receipt to Anthropic and return parsed structured data.

    Always returns a dict shaped {"parsed": dict|None, "error": str|None}.
    Never raises. The route layer surfaces this verbatim to the frontend.
    """
    api_key = (settings or {}).get("anthropic_api_key", "")
    if not api_key:
        return _err("Anthropic API key is not set")

    if mime_type not in ("image/jpeg", "image/png", "image/webp", "application/pdf"):
        return _err(f"Unsupported MIME type: {mime_type}")

    if mime_type != "application/pdf" and len(file_bytes) > MAX_IMAGE_BYTES:
        return _err(
            f"Image is {len(file_bytes) // 1024 // 1024} MB; the Anthropic API "
            f"limits images to {MAX_IMAGE_BYTES // 1024 // 1024} MB"
        )

    if mime_type == "application/pdf":
        file_bytes = _extract_first_pdf_page(file_bytes)

    model = (settings or {}).get("receipt_parser_model") or "claude-haiku-4-5-20251001"

    body = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": [
                    _build_content_block(file_bytes, mime_type),
                    {"type": "text", "text": "Extract the receipt fields per the system prompt."},
                ],
            }
        ],
    }

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=payload,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as e:
        # Anthropic error responses are JSON, but we don't surface their
        # body (it can echo small parts of the request). Just describe
        # the status.
        if e.code == 401:
            return _err("HTTP 401 from Anthropic API — check API key")
        if e.code == 429:
            return _err("HTTP 429 from Anthropic API — rate limited, try again shortly")
        return _err(f"HTTP {e.code} from Anthropic API")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # urllib's URLError wraps timeouts on some platforms
        msg = str(e)
        if "timed out" in msg.lower() or isinstance(e, TimeoutError):
            return _err("Anthropic API timed out (30s)")
        return _err("Network error contacting Anthropic API")

    if status != 200:
        return _err(f"HTTP {status} from Anthropic API")

    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _err("Anthropic API returned non-JSON response")

    # Messages API response: content is a list of blocks; we expect a single text block.
    content = envelope.get("content") or []
    text_block = next((b for b in content if isinstance(b, dict) and b.get("type") == "text"), None)
    if text_block is None:
        return _err("Anthropic response missing text content")
    text = text_block.get("text") or ""

    # Strip any stray markdown fences in case the model added them despite
    # being told not to.
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed_raw = json.loads(text)
    except json.JSONDecodeError:
        return _err("Model returned malformed JSON")

    parsed = _sanitize_parsed(parsed_raw)
    return {"parsed": parsed, "error": None}
