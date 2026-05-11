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
import logging

from fastapi import APIRouter, HTTPException

from app.services.manual_import import ManualImportError, run_import_now


logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/scheduled-import', tags=['scheduled-import'])


@router.post('/run-now')
def run_now():
    """Pull the latest IIF from Apps Script and import it immediately."""
    try:
        return run_import_now()
    except ManualImportError:
        # ManualImportError messages can transitively include upstream
        # response bodies (Apps Script JSON, requests-RequestException
        # text) or DB constraint detail from the importer. Don't echo
        # them in the HTTP response (CodeQL py/stack-trace-exposure) —
        # log the full exception with traceback server-side and return
        # a generic 502 so the admin can grep the container logs for
        # the actual cause.
        logger.warning(
            "Manual IIF import failed via /api/scheduled-import/run-now",
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail="Manual import failed; check server logs for details.",
        )
