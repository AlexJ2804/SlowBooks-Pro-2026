# ============================================================================
# Decompiled from qbw32.exe!CPreferencesDialog  Offset: 0x0023F800
# Original: tabbed dialog (IDD_PREFERENCES) with 12 tabs. We condensed
# everything into a single key-value store because nobody needs 12 tabs.
# ============================================================================

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.settings import Settings, DEFAULT_SETTINGS


class SettingsUpdate(BaseModel):
    # Accept any subset of DEFAULT_SETTINGS keys. Unknown keys are silently
    # ignored by the handler (same as before). We keep this permissive because
    # DEFAULT_SETTINGS is the authoritative key list, not the schema.
    model_config = ConfigDict(extra="allow")

router = APIRouter(prefix="/api/settings", tags=["settings"])


# Phase 12: Anthropic API key gets a masked-on-GET treatment. The same
# hardening is NOT yet applied to the older sensitive keys (smtp_password,
# stripe_secret_key, qbo_client_secret, qbo_*_token) — they're still
# returned as plaintext. That inconsistency is filed as a separate
# follow-up; widening the mask in this PR was explicitly out of scope.
_MASKED_KEYS = {"anthropic_api_key"}
_MASK_PREFIX = "•" * 8


def _mask_value(value: str) -> str:
    """Return a display-safe mask of a sensitive value.

    Empty -> empty (so the UI knows the key isn't set yet).
    Else -> "••••••••<last 4>" so the user can verify they pasted the
    right key without revealing the full secret.
    """
    if not value:
        return ""
    last4 = value[-4:] if len(value) >= 4 else value
    return f"{_MASK_PREFIX}{last4}"


def _is_masked_sentinel(value) -> bool:
    """True if `value` looks like a masked key (came back unchanged from GET).

    Real API keys never contain bullet characters; the only way the
    bullet-prefixed string reaches PUT is if the frontend echoed back the
    masked GET value. In that case we must NOT overwrite the stored key.
    """
    return isinstance(value, str) and "•" in value


def _get_all(db: Session) -> dict:
    rows = db.query(Settings).all()
    result = dict(DEFAULT_SETTINGS)
    for row in rows:
        result[row.key] = row.value
    return result


def _set(db: Session, key: str, value: str):
    row = db.query(Settings).filter(Settings.key == key).first()
    if row:
        row.value = value
    else:
        row = Settings(key=key, value=value)
        db.add(row)


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    payload = _get_all(db)
    # Mask sensitive keys on the way out. The full value never leaves
    # the server via this endpoint.
    for k in _MASKED_KEYS:
        payload[k] = _mask_value(payload.get(k, ""))
    return payload


@router.put("")
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    # model_dump returns extras plus any declared fields. Still whitelisted
    # against DEFAULT_SETTINGS so unknown keys are silently dropped.
    submitted = data.model_dump()
    for key, value in submitted.items():
        if key not in DEFAULT_SETTINGS:
            continue
        # If a masked key field is submitted with the mask sentinel
        # (because the user didn't change it), preserve the stored
        # value instead of overwriting with bullets.
        if key in _MASKED_KEYS and _is_masked_sentinel(value):
            continue
        _set(db, key, str(value) if value is not None else "")
    db.commit()
    return get_settings(db)


@router.post("/test-receipt-parser")
def test_receipt_parser(db: Session = Depends(get_db)):
    """Send a tiny probe to the configured Anthropic model to confirm the
    API key + model are valid. Used by the Settings → Receipt Parsing
    "Test Connection" button. Returns {"ok": bool, "detail": str}.

    The probe is a one-token request with no image, so cost is < 1¢ on
    Haiku. The frontend rate-limits the click to once per second to
    prevent spam."""
    settings = _get_all(db)
    api_key = settings.get("anthropic_api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="Anthropic API key is not set")

    import json
    import urllib.request
    import urllib.error
    body = json.dumps({
        "model": settings.get("receipt_parser_model") or "claude-haiku-4-5-20251001",
        "max_tokens": 4,
        "messages": [{"role": "user", "content": "Reply with only the single word 'ok'."}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return {"ok": True, "detail": "Connection OK"}
            return {"ok": False, "detail": f"HTTP {resp.status} from Anthropic API"}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"ok": False, "detail": "API key was rejected (HTTP 401)"}
        if e.code == 404:
            return {"ok": False, "detail": "Model not found (HTTP 404) — check the model name"}
        return {"ok": False, "detail": f"HTTP {e.code} from Anthropic API"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        msg = "timed out" if "timed out" in str(e).lower() else "network error"
        return {"ok": False, "detail": f"Could not reach Anthropic API ({msg})"}


@router.post("/test-email")
def test_email(db: Session = Depends(get_db)):
    """Feature 8: Send a test email to verify SMTP settings."""
    settings = _get_all(db)
    if not settings.get("smtp_host"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="SMTP not configured")
    try:
        from app.services.email_service import send_email
        send_email(
            to_email=settings.get("smtp_from_email") or settings.get("smtp_user", ""),
            subject="Slowbooks Pro 2026 — Test Email",
            html_body="<p>This is a test email from Slowbooks Pro 2026. SMTP is configured correctly.</p>",
            settings=settings,
        )
        return {"status": "sent"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Email failed: {str(e)}")
