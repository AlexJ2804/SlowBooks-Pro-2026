"""
Weekly automated IIF import.

Runs Monday 6am America/Chicago via APScheduler inside the FastAPI app
process. Pulls IIF from the Apps Script web app, archives it locally,
runs the existing IIF importer, writes structured log lines to
/app/logs/scheduled_import.log.

No email — failures only surface via the log file. Notification email
will be added in a later step (will be sent FROM Apps Script via a
callback POST to that endpoint, not from this service).

Reads from environment:
  APPS_SCRIPT_WEEKLY_URL      Full /exec URL of the Apps Script web app
  APPS_SCRIPT_WEEKLY_TOKEN    Shared secret, also set in Apps Script properties
  WEEKLY_IMPORT_ENABLED       'true' to enable; default off so dev doesn't fire it

Design notes:
  - Job runs in-process via APScheduler BackgroundScheduler. Lives and
    dies with the FastAPI app. No host cron, no separate container.
  - Calls the existing iif_import service directly rather than POSTing
    to /api/iif/import. Cuts out the HTTP roundtrip and keeps everything
    in one DB session.
  - On any exception the job catches and logs but does not re-raise —
    APScheduler would otherwise mark the job as broken and stop firing.
"""
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

from app.database import SessionLocal
from app.services.iif_import import import_all

LOG_DIR = Path('/app/logs')
LOG_FILE = LOG_DIR / 'scheduled_import.log'
IIF_ARCHIVE_DIR = Path('/app/backups/scheduled_iif')

# Dedicated logger that writes only to file. propagate=False keeps it
# out of uvicorn stdout, which is otherwise the default for any logger
# without an explicit handler.
_logger = logging.getLogger('scheduled_import')
_logger.setLevel(logging.INFO)
_logger.propagate = False


def _ensure_log_setup():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    IIF_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    if not _logger.handlers:
        handler = logging.FileHandler(LOG_FILE)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S %Z',
        ))
        _logger.addHandler(handler)


def run_weekly_import():
    """Entry point invoked by APScheduler. Wraps everything in a broad
    try/except so a bad week never breaks the schedule."""
    _ensure_log_setup()
    started = time.monotonic()
    _logger.info('=== weekly import starting ===')

    url = os.environ.get('APPS_SCRIPT_WEEKLY_URL')
    token = os.environ.get('APPS_SCRIPT_WEEKLY_TOKEN')
    if not url or not token:
        _logger.error('APPS_SCRIPT_WEEKLY_URL or APPS_SCRIPT_WEEKLY_TOKEN missing — aborting')
        return

    # Step 1: GET the IIF from Apps Script. Apps Script web apps have
    # a 6-min execution limit; 7-min timeout allows full scrape + network.
    try:
        resp = requests.get(url, params={'token': token}, timeout=420, allow_redirects=True)
    except requests.RequestException as exc:
        _logger.error('HTTP request to Apps Script failed: %s', exc)
        return

    if resp.status_code != 200:
        _logger.error('Apps Script returned HTTP %s: %s',
                      resp.status_code, resp.text[:500])
        return

    # Apps Script can't set non-200 status codes, so it encodes errors
    # in a JSON body. Detect by content type + presence of 'error' key.
    if resp.headers.get('Content-Type', '').startswith('application/json'):
        try:
            payload = resp.json()
            if isinstance(payload, dict) and 'error' in payload:
                _logger.error('Apps Script reported error (status %s): %s',
                              payload.get('status'), payload.get('error'))
                return
        except ValueError:
            pass  # Not JSON after all, fall through to treat as IIF

    iif_content = resp.text
    if not iif_content.strip():
        _logger.info('Apps Script returned empty IIF — no new transactions this week')
        elapsed = time.monotonic() - started
        _logger.info('=== weekly import finished in %.1fs (no-op) ===', elapsed)
        return

    _logger.info('IIF received: %s bytes', len(iif_content))

    # Step 2: archive locally.
    archive_path = IIF_ARCHIVE_DIR / (
        f'scheduled-import-{datetime.utcnow().strftime("%Y%m%d-%H%M%S")}.iif'
    )
    archive_path.write_text(iif_content)
    _logger.info('IIF archived to %s', archive_path)

    # Step 3: run the importer in a fresh DB session. The existing
    # import_all(db, content) returns a dict whose keys for our purposes
    # are: bills, deposits, duplicates_skipped, errors (list).
    db = SessionLocal()
    try:
        result = import_all(db, iif_content)

        bills = result.get('bills')
        deposits = result.get('deposits')
        dupes = result.get('duplicates_skipped')
        errors = result.get('errors') or []

        _logger.info(
            'import complete: bills=%s deposits=%s duplicates=%s errors=%s',
            bills, deposits, dupes, len(errors),
        )
        for err in errors:
            _logger.warning('  import error: %s', err)
    except Exception as exc:
        _logger.exception('IIF import threw: %s', exc)
        db.rollback()
    finally:
        db.close()

    elapsed = time.monotonic() - started
    _logger.info('=== weekly import finished in %.1fs ===', elapsed)


def start_scheduler():
    """Called once during FastAPI app startup."""
    if os.environ.get('WEEKLY_IMPORT_ENABLED', '').lower() != 'true':
        # Off by default so local dev doesn't fire scheduled imports.
        return

    _ensure_log_setup()
    scheduler = BackgroundScheduler(timezone=timezone('America/Chicago'))
    scheduler.add_job(
        run_weekly_import,
        CronTrigger(day_of_week='mon', hour=6, minute=0),
        id='weekly_iif_import',
        name='Weekly IIF import from Gmail scraper',
        max_instances=1,  # never overlap if a previous run is still going
        coalesce=True,    # if the app was down at trigger time, fire once on restart
    )
    scheduler.start()
    _logger.info(
        'scheduler started: next run = %s',
        scheduler.get_job('weekly_iif_import').next_run_time,
    )
