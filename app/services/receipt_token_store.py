"""Short-lived in-memory store for receipt bytes between parse and attach.

Flow: the user uploads a receipt, /api/receipts/parse stores the bytes
under a generated token and returns the token alongside the parsed data.
The frontend opens the bill confirm form pre-populated from the parse;
when the user saves the bill, /api/receipts/attach exchanges the token
for the bytes and persists them as an Attachment on the new bill row.
If the user abandons the form, the token expires (10 min default) and
the bytes are dropped — receipts only persist when the user actually
commits to saving the bill.

CONSTRAINT: this is an in-process dict, single-worker only. If you ever
run uvicorn with --workers > 1, a parse on worker A and an attach on
worker B will not share state and the attach will return 410. If we
ever need multi-worker, swap this for a small DB-backed table; the
public surface (put/get/invalidate) is intentionally narrow so that
swap is a one-file change.
"""

import secrets
import time
from typing import Optional, Tuple

# Bytes never persisted to disk by this module — only held in memory and
# evicted on TTL expiry, on explicit invalidation, or under the size cap.
_DEFAULT_TTL_SECONDS = 600
_MAX_ENTRIES = 50

# token -> (bytes, mime_type, expiry_epoch)
_store: dict[str, Tuple[bytes, str, float]] = {}


def _evict_expired(now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    expired = [t for t, (_, _, exp) in _store.items() if exp <= now]
    for t in expired:
        _store.pop(t, None)


def _evict_oldest_if_full() -> None:
    if len(_store) < _MAX_ENTRIES:
        return
    # Drop the entry closest to expiry (effectively oldest, since TTL is uniform).
    oldest = min(_store.items(), key=lambda kv: kv[1][2])[0]
    _store.pop(oldest, None)


def put(file_bytes: bytes, mime_type: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> str:
    """Store bytes under a freshly generated token. Returns the token."""
    now = time.time()
    _evict_expired(now)
    _evict_oldest_if_full()
    token = secrets.token_urlsafe(24)
    _store[token] = (file_bytes, mime_type, now + ttl_seconds)
    return token


def get(token: str) -> Optional[Tuple[bytes, str]]:
    """Return (bytes, mime_type) if the token is live, otherwise None.

    Distinguishing "expired" vs "never existed" is up to the caller — the
    route returns 410 on either, which is the right answer for both
    (the token is no longer usable).
    """
    _evict_expired()
    entry = _store.get(token)
    if entry is None:
        return None
    file_bytes, mime_type, _ = entry
    return file_bytes, mime_type


def invalidate(token: str) -> None:
    """Remove a token. Idempotent — no-op if the token is gone."""
    _store.pop(token, None)


def _reset_for_tests() -> None:
    """Drop all entries. Tests use this between cases to avoid cross-pollination."""
    _store.clear()
