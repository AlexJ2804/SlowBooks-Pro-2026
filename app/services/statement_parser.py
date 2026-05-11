"""Statement parser using the Anthropic Messages API (vision).

Phase 2 — issue #1. Same shape as receipt_parser: stdlib urllib.request,
no SDK dep, all failures caught and returned as a structured result.
The route layer translates that into a 200 response so the frontend can
display "couldn't read this statement" without exception handling.

Differences from receipt_parser:
  * Multi-page: full PDF goes to the API, not just page 1. Statements
    are 3-15 pages and every page contains transactions we need.
  * Output is an ARRAY of transactions, not a single record.
  * Returns token usage from the API envelope so the caller can record
    per-import cost in cents on statement_imports.

Pricing reference (Anthropic, Jan 2026, claude-sonnet-4-6):
  Input:  $3 / million tokens   = 0.0003 cents per token
  Output: $15 / million tokens  = 0.0015 cents per token

Typical bank statement (5-10 pages, 30-60 transactions):
  Input  ~ 8,000 tokens  -> 2.4 cents
  Output ~ 2,000 tokens  -> 3.0 cents
  Total                  ~ 5.4 cents per statement.

Privacy: same posture as receipt_parser — statement content is never
logged, errors carry generic descriptions only, the system prompt
instructs the model to ignore card numbers.
"""

import base64
import json
import logging
import re
import urllib.request
import urllib.error
from typing import Optional


logger = logging.getLogger(__name__)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
TIMEOUT_SECONDS = 120  # Statements take longer than receipts; multi-page reasoning.
# 32K output tokens covers the densest statements we've seen (Amex with
# foreign-spend rows runs ~30K input tokens / ~15K output tokens for
# 100+ transactions). The previous 8192 cap truncated mid-array on
# those — the model returned a partial JSON that re.search couldn't
# close, surfacing as "Model returned malformed JSON". Sonnet 4.6's
# hard cap is 64K so this still leaves headroom.
MAX_TOKENS = 32768
ANTHROPIC_VERSION = "2023-06-01"

# Anthropic PDF document limits (per API docs, late 2025): 32 MB and 100
# pages. Defense-in-depth caps so the service never makes an obviously-
# doomed request even if the route layer's check is misconfigured.
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PDF_PAGES = 100

# Sonnet 4.6 — bare ID, matches the format Anthropic ships for the
# current Sonnet generation. Statements have dense multi-page tables
# where Haiku misses rows; this is the right tier for the job.
_DEFAULT_MODEL = "claude-sonnet-4-6"

# Pricing in cents per million tokens. Held as ints so cost arithmetic
# stays in integer cents (no float drift). Keys are model IDs as sent
# in the API request — keep these in sync if the model changes.
_PRICING_CENTS_PER_MTOK = {
    "claude-sonnet-4-6":          {"input": 300,  "output": 1500},
    "claude-opus-4-7":            {"input": 1500, "output": 7500},
    "claude-haiku-4-5-20251001":  {"input": 80,   "output": 400},
}


SYSTEM_PROMPT = """You are extracting structured transaction data from a bank or credit-card statement PDF.

Return ONLY valid JSON matching this exact schema. No markdown fences, no
commentary, no preamble:

{
  "statement": {
    "bank_name": string or null,
    "account_last_four": string of exactly 4 digits or null,
    "period_start": "YYYY-MM-DD" or null,
    "period_end": "YYYY-MM-DD" or null,
    "opening_balance": number or null,
    "closing_balance": number or null
  },
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": string,
      "amount": number,
      "check_number": string or null
    }
  ]
}

Rules:
- Dates strictly ISO format YYYY-MM-DD. If the statement uses MM/DD,
  infer the year from period_start/period_end. Reject any date you
  cannot fully resolve to ISO format (omit the transaction).
- Amounts are JSON numbers. NO currency symbols, NO thousands separators
  ("1,234.56" -> 1234.56).
- Sign convention: deposits/credits/payments-into-the-account are
  POSITIVE. Withdrawals/debits/charges/fees are NEGATIVE. This applies
  to BOTH bank statements and credit-card statements:
    - Bank checking: a $100 ATM withdrawal -> -100. A $500 paycheck
      deposit -> +500.
    - Credit card: a $50 Starbucks charge -> -50. A $200 payment to
      the card -> +200.
  Do NOT use the absolute value of "amount due" or running-balance
  columns; extract each transaction's signed delta.
- If the statement displays separate "Withdrawals" and "Deposits"
  columns, apply the sign per column rather than guessing from the
  description.
- Include EVERY transaction visible on the statement. Do not skip
  recurring lines, fees, interest charges, or tiny adjustments.
- Do NOT include opening-balance, closing-balance, subtotal, or
  "Total Withdrawals" / "Total Deposits" summary rows. Only line-
  level transactions belong in the array.
- description: copy the merchant/payee text exactly as printed,
  including any reference codes the bank includes inline. Do not
  rewrite, summarise, or expand abbreviations.
- check_number: only fill this when the statement has a "Check #"
  column with a value. Otherwise null.
- IGNORE card numbers, partial card numbers (last-4 of the card
  printed in the statement header), CVV, expiration dates, addresses,
  customer names. Only the account_last_four field captures one piece
  of card-number data; everything else gets dropped.

Output format — STRICT:
- Output the JSON object as the very first character of your response.
- The first character must be `{` and the last character must be `}`.
- Do not include any text before or after the JSON object.
- Do not explain your reasoning, do not say "Here is the data".
- Do not wrap the JSON in markdown fences.
- Stop immediately after the closing `}`.
"""


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LAST_FOUR_RE = re.compile(r"^\d{4}$")


def _err(message: str, *, raw_text: Optional[str] = None,
         input_tokens: Optional[int] = None,
         output_tokens: Optional[int] = None) -> dict:
    return {
        "parsed": None,
        "error": message,
        "raw_text": raw_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _coerce_number(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("$", "").strip())
        except ValueError:
            return None
    return None


def _looks_like_date(v) -> bool:
    return isinstance(v, str) and bool(_DATE_RE.match(v))


def _sanitize_statement_header(raw) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    last_four = raw.get("account_last_four")
    if not (isinstance(last_four, str) and _LAST_FOUR_RE.match(last_four)):
        last_four = None
    return {
        "bank_name": raw.get("bank_name") if isinstance(raw.get("bank_name"), str) else None,
        "account_last_four": last_four,
        "period_start": raw.get("period_start") if _looks_like_date(raw.get("period_start")) else None,
        "period_end": raw.get("period_end") if _looks_like_date(raw.get("period_end")) else None,
        "opening_balance": _coerce_number(raw.get("opening_balance")),
        "closing_balance": _coerce_number(raw.get("closing_balance")),
    }


def _sanitize_transactions(items) -> list:
    """Drop any row missing date or amount; keep everything else verbatim
    after type coercion. Description is length-capped at 500 chars to
    match BankTransaction.description's column width."""
    if not isinstance(items, list):
        return []
    cleaned = []
    for tx in items:
        if not isinstance(tx, dict):
            continue
        if not _looks_like_date(tx.get("date")):
            continue
        amount = _coerce_number(tx.get("amount"))
        if amount is None:
            continue
        description = tx.get("description")
        description = description.strip() if isinstance(description, str) else ""
        if len(description) > 500:
            description = description[:500]
        check_number = tx.get("check_number")
        if isinstance(check_number, str):
            check_number = check_number.strip()[:50] or None
        else:
            check_number = None
        cleaned.append({
            "date": tx["date"],
            "description": description,
            "amount": amount,
            "check_number": check_number,
        })
    return cleaned


def _compute_cost_cents(model: str,
                       input_tokens: Optional[int],
                       output_tokens: Optional[int]) -> Optional[int]:
    """Return integer cents for the call, or None if pricing is unknown.

    cents = round((input_tokens / 1_000_000) * input_rate_cents
                + (output_tokens / 1_000_000) * output_rate_cents)
    Tokens are unsigned integers from the API envelope; pricing is held
    as integer cents-per-million-tokens to avoid float drift.
    """
    pricing = _PRICING_CENTS_PER_MTOK.get(model)
    if pricing is None:
        return None
    if input_tokens is None or output_tokens is None:
        return None
    cents_x_mtok = (input_tokens * pricing["input"]) + (output_tokens * pricing["output"])
    # Round half up to the nearest cent. Statements rarely cost <1c so
    # rounding error is immaterial — we just need an integer.
    return (cents_x_mtok + 500_000) // 1_000_000


def _call_anthropic(pdf_bytes: bytes, api_key: str, model: str) -> dict:
    """Send the PDF to Anthropic and return the parsed envelope.

    Returns a dict shaped:
      {
        "parsed": dict | None,        # sanitised on success
        "error":  str | None,
        "raw_text": str | None,       # model's raw text response (for debugging)
        "input_tokens":  int | None,
        "output_tokens": int | None,
      }
    Never raises. parse_statement wraps this for the route layer.
    """
    encoded = base64.b64encode(pdf_bytes).decode("ascii")
    body = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": encoded,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract every transaction from this statement per the system prompt schema.",
                    },
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
        if e.code == 401:
            return _err("HTTP 401 from Anthropic API — check API key")
        if e.code == 429:
            return _err("HTTP 429 from Anthropic API — rate limited, try again shortly")
        if e.code == 413:
            return _err("HTTP 413 from Anthropic API — PDF too large (max 32 MB)")
        return _err(f"HTTP {e.code} from Anthropic API")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        msg = str(e)
        if "timed out" in msg.lower() or isinstance(e, TimeoutError):
            return _err(f"Anthropic API timed out ({TIMEOUT_SECONDS}s)")
        return _err("Network error contacting Anthropic API")

    if status != 200:
        return _err(f"HTTP {status} from Anthropic API")

    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _err("Anthropic API returned non-JSON response")

    usage = envelope.get("usage") or {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if not isinstance(input_tokens, int):
        input_tokens = None
    if not isinstance(output_tokens, int):
        output_tokens = None

    content = envelope.get("content") or []
    text_block = next(
        (b for b in content if isinstance(b, dict) and b.get("type") == "text"),
        None,
    )
    if text_block is None:
        return _err("Anthropic response missing text content",
                    input_tokens=input_tokens, output_tokens=output_tokens)
    text = text_block.get("text") or ""

    # Greedy DOTALL match grabs from the first `{` to the last `}` so
    # that any prose wrapper or markdown fence the model adds gets
    # stripped. Statements are a single JSON object, so this is safe.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        logger.warning(
            "statement_parser: model output contains no JSON object; "
            "first 500 chars: %r",
            (text or "")[:500],
        )
        return _err("Model returned malformed JSON",
                    raw_text=text,
                    input_tokens=input_tokens, output_tokens=output_tokens)

    try:
        parsed_raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning(
            "statement_parser: failed to parse JSON from model output; "
            "first 500 chars of raw text: %r",
            (text or "")[:500],
        )
        return _err("Model returned malformed JSON",
                    raw_text=text,
                    input_tokens=input_tokens, output_tokens=output_tokens)

    sanitised = {
        "statement": _sanitize_statement_header(parsed_raw.get("statement")),
        "transactions": _sanitize_transactions(parsed_raw.get("transactions")),
    }
    return {
        "parsed": sanitised,
        "error": None,
        "raw_text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def parse_statement(pdf_bytes: bytes, settings: dict) -> dict:
    """Parse a statement PDF via Anthropic Vision.

    Returns:
      {
        "parsed":  {"statement": {...}, "transactions": [...]} | None,
        "error":   str | None,
        "raw_text":      str | None,    # raw model output for debugging
        "model":         str,
        "input_tokens":  int | None,
        "output_tokens": int | None,
        "cost_cents":    int | None,
      }

    Never raises. The route layer surfaces this verbatim to the frontend
    after persisting tokens/cost on the statement_imports row.
    """
    api_key = (settings or {}).get("anthropic_api_key", "")
    if not api_key:
        return {**_err("Anthropic API key is not set"), "model": _DEFAULT_MODEL,
                "cost_cents": None}

    if len(pdf_bytes) > MAX_PDF_BYTES:
        size_mb = len(pdf_bytes) // 1024 // 1024
        return {**_err(f"PDF is {size_mb} MB; the Anthropic API limits PDFs to "
                      f"{MAX_PDF_BYTES // 1024 // 1024} MB"),
                "model": _DEFAULT_MODEL, "cost_cents": None}

    # Page-count check via pypdf — best effort, fall through if it fails
    # to read the PDF (let the API reject it with a clearer error).
    try:
        from pypdf import PdfReader
        import io as _io
        reader = PdfReader(_io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PAGES:
            return {**_err(f"PDF has {page_count} pages; the Anthropic API "
                          f"limits PDFs to {MAX_PDF_PAGES} pages"),
                    "model": _DEFAULT_MODEL, "cost_cents": None}
    except Exception:
        pass

    model = (settings or {}).get("statement_parser_model") or _DEFAULT_MODEL

    result = _call_anthropic(pdf_bytes, api_key, model)
    cost_cents = _compute_cost_cents(model,
                                     result.get("input_tokens"),
                                     result.get("output_tokens"))
    return {
        "parsed": result.get("parsed"),
        "error": result.get("error"),
        "raw_text": result.get("raw_text"),
        "model": model,
        "input_tokens": result.get("input_tokens"),
        "output_tokens": result.get("output_tokens"),
        "cost_cents": cost_cents,
    }
