"""LLM-assisted bank transaction categorizer.

Phase 3 — spending analytics. Takes a list of unique payee strings
from unmatched bank_transactions and asks Claude to suggest the
best-fit COA account (income / expense / cogs). The route layer turns
accepted suggestions into BankRule rows; existing /api/bank-rules/apply
then propagates the categorization to every matching unmatched txn.

Same shape as receipt_parser / statement_parser:
  * stdlib urllib.request, no SDK dep
  * all failures caught, structured result returned
  * never raises

Pricing reference (Anthropic, Jan 2026, claude-haiku-4-5):
  Input:  $0.80 / million tokens
  Output: $4.00 / million tokens
Categorization is short text classification — Haiku is plenty. A batch
of 50 merchants + 50 categories is ~3,000 input + ~1,500 output tokens
= ~$0.01 per batch. Categorizing 500 distinct merchants in 10 batches
runs about a dime.

Privacy: payee strings are sent to Anthropic; the system prompt does
not log them and errors carry generic descriptions only.
"""

import json
import logging
import re
import urllib.request
import urllib.error
from typing import Optional


logger = logging.getLogger(__name__)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
TIMEOUT_SECONDS = 60
MAX_TOKENS = 4096

# Haiku 4.5 — cheap and plenty for short text classification.
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_PRICING_CENTS_PER_MTOK = {
    "claude-haiku-4-5-20251001":  {"input": 80,   "output": 400},
    "claude-sonnet-4-6":          {"input": 300,  "output": 1500},
    "claude-opus-4-7":            {"input": 1500, "output": 7500},
}

# Cap batch size so a single request stays well inside MAX_TOKENS even
# with verbose Amex foreign-spend payees. Large jobs split client-side.
MAX_BATCH = 50


SYSTEM_PROMPT = """You categorize bank/credit-card transactions into accounting categories (Chart of Accounts).

You will receive:
  - a list of CATEGORIES — each {id, name, type} where type is one of
    "income", "expense", "cogs"
  - a list of MERCHANTS — each {idx, payee} from real bank statements

Return ONLY valid JSON, no markdown fences, no commentary:
{
  "suggestions": [
    {
      "idx": <int matching MERCHANTS[idx]>,
      "account_id": <int from CATEGORIES, or null if unsure>,
      "confidence": <"high"|"medium"|"low"|"none">,
      "reason": <short string, max 100 chars>
    }
  ]
}

Rules:
- Output exactly one suggestion per merchant (never skip).
- account_id MUST be one of the IDs in CATEGORIES; pick the single
  best fit. If no fit, set account_id=null and confidence="none".
- For payments TO a credit card account (where the merchant string
  looks like "ONLINE PAYMENT - THANK YOU", "AUTOPAY PAYMENT",
  "MOBILE PAYMENT - THANK YOU"), set account_id=null and
  confidence="none" — those are account-to-account transfers, not
  expenses.
- For interest charges and fees, prefer an "Interest Expense" or
  "Bank Fees" category if one exists.
- Use confidence="high" only when the merchant brand is unambiguous
  (e.g. STARBUCKS, NETFLIX, SHELL OIL, AMAZON, SPOTIFY, UBER).
- Use confidence="low" for ambiguous strings or when picking between
  two plausible categories.

Output format — STRICT:
- First character `{`, last character `}`, no surrounding text or
  markdown fences. Stop after the closing `}`.
"""


def _err(message: str, *, raw_text: Optional[str] = None,
         input_tokens: Optional[int] = None,
         output_tokens: Optional[int] = None) -> dict:
    return {
        "suggestions": None,
        "error": message,
        "raw_text": raw_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _compute_cost_cents(model: str,
                        input_tokens: Optional[int],
                        output_tokens: Optional[int]) -> Optional[int]:
    pricing = _PRICING_CENTS_PER_MTOK.get(model)
    if pricing is None or input_tokens is None or output_tokens is None:
        return None
    cents_x_mtok = input_tokens * pricing["input"] + output_tokens * pricing["output"]
    return (cents_x_mtok + 500_000) // 1_000_000


def _call_anthropic(merchants: list, categories: list,
                    api_key: str, model: str) -> dict:
    user_payload = {"categories": categories, "merchants": merchants}
    body = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        }],
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
    input_tokens = usage.get("input_tokens") if isinstance(usage.get("input_tokens"), int) else None
    output_tokens = usage.get("output_tokens") if isinstance(usage.get("output_tokens"), int) else None

    content = envelope.get("content") or []
    text_block = next(
        (b for b in content if isinstance(b, dict) and b.get("type") == "text"),
        None,
    )
    if text_block is None:
        return _err("Anthropic response missing text content",
                    input_tokens=input_tokens, output_tokens=output_tokens)
    text = text_block.get("text") or ""

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        logger.warning("categorizer: model output contains no JSON object; "
                       "first 500 chars: %r", (text or "")[:500])
        return _err("Model returned malformed JSON",
                    raw_text=text, input_tokens=input_tokens,
                    output_tokens=output_tokens)
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("categorizer: failed to parse JSON; first 500 chars: %r",
                       (text or "")[:500])
        return _err("Model returned malformed JSON",
                    raw_text=text, input_tokens=input_tokens,
                    output_tokens=output_tokens)

    raw_suggestions = parsed.get("suggestions") if isinstance(parsed, dict) else None
    if not isinstance(raw_suggestions, list):
        return _err("Model response missing suggestions array",
                    raw_text=text, input_tokens=input_tokens,
                    output_tokens=output_tokens)

    valid_account_ids = {c["id"] for c in categories if isinstance(c.get("id"), int)}
    cleaned = []
    for s in raw_suggestions:
        if not isinstance(s, dict):
            continue
        idx = s.get("idx")
        if not isinstance(idx, int):
            continue
        account_id = s.get("account_id")
        if account_id is not None and account_id not in valid_account_ids:
            account_id = None
        confidence = s.get("confidence")
        if confidence not in ("high", "medium", "low", "none"):
            confidence = "none"
        reason = s.get("reason")
        if not isinstance(reason, str):
            reason = ""
        cleaned.append({
            "idx": idx,
            "account_id": account_id,
            "confidence": confidence,
            "reason": reason[:200],
        })

    return {
        "suggestions": cleaned,
        "error": None,
        "raw_text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def suggest_categories(merchants: list, categories: list, settings: dict) -> dict:
    """Categorize a batch of merchant strings via Anthropic.

    Args:
      merchants:  [{"idx": int, "payee": str}, ...] up to MAX_BATCH
      categories: [{"id": int, "name": str, "type": str}, ...] eligible
                  COA accounts (income / expense / cogs)
      settings:   dict containing "anthropic_api_key" and optional
                  "categorizer_model"

    Returns:
      {
        "suggestions": [{"idx", "account_id"|None, "confidence", "reason"}, ...] | None,
        "error":   str | None,
        "model":   str,
        "input_tokens":  int | None,
        "output_tokens": int | None,
        "cost_cents":    int | None,
      }
    Never raises.
    """
    api_key = (settings or {}).get("anthropic_api_key", "")
    if not api_key:
        return {**_err("Anthropic API key is not set"),
                "model": _DEFAULT_MODEL, "cost_cents": None}

    if not merchants:
        return {"suggestions": [], "error": None, "model": _DEFAULT_MODEL,
                "input_tokens": 0, "output_tokens": 0, "cost_cents": 0}

    if len(merchants) > MAX_BATCH:
        return {**_err(f"Batch too large: {len(merchants)} > {MAX_BATCH}"),
                "model": _DEFAULT_MODEL, "cost_cents": None}

    if not categories:
        return {**_err("No categories provided"),
                "model": _DEFAULT_MODEL, "cost_cents": None}

    model = (settings or {}).get("categorizer_model") or _DEFAULT_MODEL
    result = _call_anthropic(merchants, categories, api_key, model)
    cost_cents = _compute_cost_cents(model, result.get("input_tokens"),
                                     result.get("output_tokens"))
    return {
        "suggestions": result.get("suggestions"),
        "error": result.get("error"),
        "model": model,
        "input_tokens": result.get("input_tokens"),
        "output_tokens": result.get("output_tokens"),
        "cost_cents": cost_cents,
    }
