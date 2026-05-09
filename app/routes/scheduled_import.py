"""Manual trigger for the Gmail-receipts → IIF → import pipeline.

The same pipeline runs every Monday 6am America/Chicago via APScheduler
(app/services/scheduled_import.py); this route exposes an on-demand
button for the UI so the user can pull the latest receipts whenever
they want without waiting for the cron.

Endpoint:
  POST /api/scheduled-import/run-now    runs synchronously and returns
                                        bills/deposits/duplicates counts
                                        + archive path + elapsed seconds

Synchronous because the underlying flow is short for a typical week
(seconds), and the Apps Script web app's 6-min hard limit caps the
worst case. Front-end disables the button + shows "Scanning…" while
the request is in flight.
"""
from fastapi import APIRouter, HTTPException

from app.services.manual_import import ManualImportError, run_import_now


router = APIRouter(prefix='/api/scheduled-import', tags=['scheduled-import'])


@router.post('/run-now')
def run_now():
    """Pull the latest IIF from Apps Script and import it immediately."""
    try:
        return run_import_now()
    except ManualImportError as exc:
        # 502 because Apps Script (the upstream) is the failure source in
        # the realistic cases (env missing, HTTP timeout, Apps Script JSON
        # error). Use plain str(exc) for the detail since ManualImportError
        # already crafts a user-readable message.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
