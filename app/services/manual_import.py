"""On-demand version of the weekly IIF import.

Mirrors run_weekly_import() in scheduled_import.py but returns a
structured result instead of logging-only, so a UI button can show the
user exactly what landed.

Lives in its own module so the production cron path
(scheduled_import.py + APScheduler + WEEKLY_IMPORT_ENABLED gate) stays
untouched. Both paths share the same env contract:

  APPS_SCRIPT_WEEKLY_URL     /exec URL of the deployed Apps Script web app
  APPS_SCRIPT_WEEKLY_TOKEN   shared secret matching WEEKLY_IMPORT_TOKEN in
                             Apps Script Properties

The Apps Script doGet(e) returns the IIF as plain text, or a JSON
{error, status} body with HTTP 200 on failure (Apps Script web apps
can't set non-200 status codes). We detect that JSON error shape by
content type + 'error' key and surface it as a ManualImportError so
the route layer can return a meaningful 5xx.
"""
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from app.database import SessionLocal
from app.services.iif_import import import_all


IIF_ARCHIVE_DIR = Path('/app/backups/scheduled_iif')


class ManualImportError(Exception):
    """Raised when the import can't proceed (missing env, HTTP failure,
    Apps Script JSON error, importer exception)."""


def run_import_now() -> dict:
    """Fetch the IIF from Apps Script and run the importer right now.

    Returns a dict with: bills, deposits, duplicates_skipped, errors,
    iif_bytes, archive_path, elapsed_seconds, message.

    Raises ManualImportError on any failure (missing env, HTTP failure,
    Apps Script error, importer exception).
    """
    started = time.monotonic()

    url = os.environ.get('APPS_SCRIPT_WEEKLY_URL')
    token = os.environ.get('APPS_SCRIPT_WEEKLY_TOKEN')
    if not url or not token:
        raise ManualImportError(
            'APPS_SCRIPT_WEEKLY_URL or APPS_SCRIPT_WEEKLY_TOKEN is not set in '
            'the environment. Set both in .env: the URL is the Apps Script '
            'web-app /exec URL; the token must match WEEKLY_IMPORT_TOKEN in '
            'Apps Script Project Settings → Script Properties.'
        )

    # Apps Script web apps have a 6-min execution limit; 7-min HTTP
    # timeout allows full scrape + transit.
    try:
        resp = requests.get(
            url, params={'token': token}, timeout=420, allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise ManualImportError(f'Could not reach Apps Script: {exc}') from exc

    if resp.status_code != 200:
        raise ManualImportError(
            f'Apps Script returned HTTP {resp.status_code}: {resp.text[:500]}'
        )

    # Apps Script encodes errors as JSON in the response body since it
    # can't return non-200 status codes. Detect by content type +
    # presence of an 'error' key; fall through to IIF treatment if the
    # body isn't actually JSON.
    if resp.headers.get('Content-Type', '').startswith('application/json'):
        try:
            payload = resp.json()
            if isinstance(payload, dict) and 'error' in payload:
                raise ManualImportError(
                    f"Apps Script error (status {payload.get('status')}): "
                    f"{payload.get('error')}"
                )
        except ValueError:
            pass  # not JSON after all

    iif_content = resp.text
    iif_bytes = len(iif_content)

    if not iif_content.strip():
        return {
            'bills': 0,
            'deposits': 0,
            'duplicates_skipped': 0,
            'errors': [],
            'iif_bytes': 0,
            'archive_path': None,
            'elapsed_seconds': round(time.monotonic() - started, 2),
            'message': 'Apps Script returned an empty IIF — no new transactions.',
        }

    # Archive locally — same convention and folder as the scheduled job
    # so a single directory holds the full audit trail of imports
    # regardless of trigger.
    archive_path = _archive(iif_content)

    db = SessionLocal()
    try:
        result = import_all(db, iif_content)
        return {
            'bills': result.get('bills') or 0,
            'deposits': result.get('deposits') or 0,
            'duplicates_skipped': result.get('duplicates_skipped') or 0,
            'errors': list(result.get('errors') or []),
            'iif_bytes': iif_bytes,
            'archive_path': str(archive_path),
            'elapsed_seconds': round(time.monotonic() - started, 2),
            'message': None,
        }
    except Exception as exc:
        db.rollback()
        raise ManualImportError(f'IIF import failed: {exc}') from exc
    finally:
        db.close()


def _archive(iif_content: str) -> Path:
    IIF_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = IIF_ARCHIVE_DIR / (
        f'manual-import-{datetime.utcnow().strftime("%Y%m%d-%H%M%S")}.iif'
    )
    path.write_text(iif_content)
    return path
