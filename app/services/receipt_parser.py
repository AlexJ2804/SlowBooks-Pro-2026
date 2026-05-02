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
import logging
import re
import urllib.request
import urllib.error
from typing import Optional


logger = logging.getLogger(__name__)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
TIMEOUT_SECONDS = 30
MAX_TOKENS = 1024
ANTHROPIC_VERSION = "2023-06-01"

# Anthropic image limit (per API docs, late 2025): 5 MB per image. PDFs
# have a separate 32 MB / 100-page limit. The route layer also enforces
# the user-configured upload max — these constants exist as a defense in
# depth so this service never makes an obviously-doomed request.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# When a PDF/image parse with the user's configured model returns
# parsed!=null but total=null, we retry once with Sonnet 4.6. Sonnet has
# stronger spatial reasoning on dense column-heavy layouts (Gmail-rendered
# email receipts in particular). The retry is hardcoded — the Settings
# model selector is for the user's PRIMARY model preference; this is
# internal fallback only.
#
# Why claude-sonnet-4-6 (bare format) and not 4.5 / date-suffixed: 4.6 is
# the current Sonnet generation, and Anthropic ships Sonnet IDs as bare
# names in 4.x. Haiku 4.5 ships date-suffixed (claude-haiku-4-5-20251001)
# because that's its canonical alias — match each model's own format.
#
# Cost worst-case (Jan 2026 public pricing, ~3K input + ~300 output
# tokens for a single-page receipt + our system prompt):
#   Haiku call:  ~$0.013
#   Sonnet call: ~$0.014
# Worst-case Haiku-fail-then-Sonnet path: ~$0.027 per receipt. Most
# clean receipts succeed on Haiku and skip the retry entirely.
_RETRY_MODEL = "claude-sonnet-4-6"
_HAIKU_DEFAULT = "claude-haiku-4-5-20251001"


SYSTEM_PROMPT = """You are extracting structured data from a receipt or invoice image.

Return ONLY valid JSON matching this exact schema. No markdown fences, no
commentary, no preamble:

{
  "vendor_name": string or null,
  "date": "YYYY-MM-DD" or null,
  "currency": ISO-4217 3-letter code (e.g. "USD", "EUR", "CAD") or null,
  "order_number": string or null,
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
- "order_number": the primary identifier the vendor uses for this
  receipt — labeled with terms like "Order Number", "Order #",
  "Invoice Number", "Bill Number", "Account Number", or
  "Reference Number". Preserve the printed format including any
  prefix letters and punctuation (e.g. "W1591651266", "INV-2026-0042",
  "ACC/12345", "Bill #00123-A"). If multiple identifiers are present,
  pick the one most prominently displayed (largest type, near the top,
  or in a header bar). PREFER order/invoice/bill/account numbers over
  confirmation/booking numbers. If only a confirmation number is
  present, use that. If nothing is labeled as an identifier, return null.
- Numbers must be JSON numbers — no currency symbols, no thousands
  separators (1,234.56 -> 1234.56).
- When extracting totals: look for explicit labels like "Total",
  "Order Total", "Subtotal", "Amount Due", "Grand Total". These are
  usually at the END of the receipt or in a dedicated payment-summary
  section. Prices often appear in a right-aligned column visually
  separated from item descriptions — match each price to its nearest
  preceding item label by row position. If the receipt is rendered from
  an email (column-heavy HTML→PDF layout), totals may live in a
  "Billing and Payment" or "Order Summary" section with explicitly
  labeled rows. PREFER the most explicit labeled total (e.g. "Order
  Total: $X") over a sum you compute from line items.
- When extracting line items: each item's amount is usually
  right-aligned next to the item name or quantity. If you see
  "Qty 1   $499.00" in a layout, $499.00 is BOTH the rate and the
  amount for that single-quantity line. Empty middle columns
  (visually blank cells) are layout artifacts, not zeros.
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
    "vendor_name", "date", "currency", "order_number",
    "subtotal", "tax", "total",
    "line_items", "suggested_expense_account_keywords",
}
_EXPECTED_LINE_KEYS = {"description", "quantity", "rate", "amount"}

# Real-world order/bill/account numbers vary widely in length but rarely
# exceed ~30 characters. Cap at 64 so a runaway model can't dump a
# sentence into the field; below the cap we keep the printed format
# verbatim including slashes, dashes, dots, parentheses (utility bills
# in particular use these).
_ORDER_NUMBER_MAX_LEN = 64


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
        "order_number": _sanitize_order_number(raw.get("order_number")),
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
        "order_number": None,
        "subtotal": None,
        "tax": None,
        "total": None,
        "line_items": [],
        "suggested_expense_account_keywords": [],
    }


def _sanitize_order_number(v) -> Optional[str]:
    """Accept a string, strip whitespace, length-cap. No character filter:
    real utility bill numbers carry slashes, dashes, dots, parens.
    Anything not a string -> None."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    if len(s) > _ORDER_NUMBER_MAX_LEN:
        return s[:_ORDER_NUMBER_MAX_LEN]
    return s


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


def _call_anthropic(
    file_bytes: bytes,
    mime_type: str,
    api_key: str,
    model: str,
) -> tuple[Optional[dict], Optional[str]]:
    """Single round-trip to Anthropic /v1/messages with the receipt prompt.

    Returns (sanitised_parsed_dict, None) on success or (None, error_str)
    on any failure. Never raises — the parse_receipt wrapper surfaces
    failures to the route layer as {"parsed": None, "error": "..."}.
    """
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
            return None, "HTTP 401 from Anthropic API — check API key"
        if e.code == 429:
            return None, "HTTP 429 from Anthropic API — rate limited, try again shortly"
        return None, f"HTTP {e.code} from Anthropic API"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # urllib's URLError wraps timeouts on some platforms
        msg = str(e)
        if "timed out" in msg.lower() or isinstance(e, TimeoutError):
            return None, "Anthropic API timed out (30s)"
        return None, "Network error contacting Anthropic API"

    if status != 200:
        return None, f"HTTP {status} from Anthropic API"

    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "Anthropic API returned non-JSON response"

    # Messages API response: content is a list of blocks; we expect a single text block.
    content = envelope.get("content") or []
    text_block = next((b for b in content if isinstance(b, dict) and b.get("type") == "text"), None)
    if text_block is None:
        return None, "Anthropic response missing text content"
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
        return None, "Model returned malformed JSON"

    return _sanitize_parsed(parsed_raw), None


def parse_receipt(file_bytes: bytes, mime_type: str, settings: dict) -> dict:
    """Send a receipt to Anthropic and return parsed structured data.

    Always returns a dict shaped {"parsed": dict|None, "error": str|None}.
    Never raises. The route layer surfaces this verbatim to the frontend.

    Two-pass behaviour: if the configured (typically Haiku) model returns
    parsed-but-total-null on a PDF/image, retry once with Sonnet 4.6.
    Sonnet has stronger spatial reasoning on column-heavy layouts (Gmail-
    rendered HTML email receipts in particular). The retry's result is
    used unconditionally — even if Sonnet's output is "worse" on other
    fields than Haiku's. Pinned by test_haiku_partial_parse_sonnet_worse:
    deliberate "always use Sonnet" choice, revisit (with merging logic)
    only if real-world data shows Sonnet regressing fields meaningfully.
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

    primary_model = (settings or {}).get("receipt_parser_model") or _HAIKU_DEFAULT

    parsed, error = _call_anthropic(file_bytes, mime_type, api_key, primary_model)
    if error is not None:
        # Transport / auth / malformed-response failures don't trigger a
        # Sonnet retry — only successful-but-null-total parses do.
        return {"parsed": None, "error": error}

    # Retry gate: visual-input only (mime_type already constrained to
    # image/PDF earlier; gate written explicitly so a future text-input
    # path naturally excludes itself), and only when total is null but
    # the parse otherwise succeeded.
    is_visual_input = mime_type in ("image/jpeg", "image/png", "image/webp", "application/pdf")
    should_retry = (
        is_visual_input
        and parsed is not None
        and parsed.get("total") is None
        and primary_model != _RETRY_MODEL
    )

    # WARNING level (not INFO) because the app has no root-logger config
    # and uvicorn's default doesn't elevate non-uvicorn loggers to INFO.
    # Without this, retry diagnostics are invisible in production logs.
    # See diagnostic gap that motivated this change: retry fired/skipped
    # without anyone able to tell which from logs alone.
    logger.warning(
        "receipt_parser.retry_gate: mime_type=%r is_visual=%s parsed_not_none=%s "
        "total_is_none=%s primary_model=%r != retry_model=%r -> should_retry=%s",
        mime_type, is_visual_input, parsed is not None,
        (parsed is not None and parsed.get("total") is None),
        primary_model, _RETRY_MODEL, should_retry,
    )

    if should_retry:
        logger.warning(
            "receipt_parser: retrying with %s after %s returned null total",
            _RETRY_MODEL, primary_model,
        )
        retry_parsed, retry_error = _call_anthropic(
            file_bytes, mime_type, api_key, _RETRY_MODEL,
        )
        # Per spec: use Sonnet's result whether or not it improved totals.
        # Retry transport errors fall through to the original Haiku
        # result so a transient Sonnet failure doesn't lose Haiku's
        # partial parse.
        if retry_error is None and retry_parsed is not None:
            logger.warning(
                "receipt_parser: %s retry succeeded; has_total=%s",
                _RETRY_MODEL, retry_parsed.get("total") is not None,
            )
            parsed = retry_parsed
        else:
            logger.warning(
                "receipt_parser: %s retry failed (%s); keeping primary result",
                _RETRY_MODEL, retry_error or "no parsed data",
            )

    return {"parsed": parsed, "error": None}
