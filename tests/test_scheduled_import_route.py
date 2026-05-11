"""Tests for /api/scheduled-import/run-now.

The Apps Script HTTP call is mocked so these tests don't hit the network
or depend on env config beyond what we explicitly set.
"""
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    """Default to a configured environment so the env-missing case is
    opt-in via test-level overrides rather than the default state."""
    monkeypatch.setenv('APPS_SCRIPT_WEEKLY_URL', 'https://script.google.com/macros/s/test/exec')
    monkeypatch.setenv('APPS_SCRIPT_WEEKLY_TOKEN', 'test-token-abc')
    yield


def _mock_response(status_code=200, text='', headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    resp.json = MagicMock(side_effect=lambda: __import__('json').loads(resp.text))
    return resp


def test_run_now_returns_zero_counts_on_empty_iif(client, monkeypatch):
    """Apps Script returned an empty IIF — no new transactions this week.
    Endpoint should still 200, with all counts at zero and a message
    flag the UI can use to show "no new receipts" rather than treating
    it as success-with-imports."""
    with patch('app.services.manual_import.requests.get') as mock_get:
        mock_get.return_value = _mock_response(text='')

        r = client.post('/api/scheduled-import/run-now')

    assert r.status_code == 200, r.text
    body = r.json()
    assert body['bills'] == 0
    assert body['deposits'] == 0
    assert body['duplicates_skipped'] == 0
    assert body['iif_bytes'] == 0
    assert body['archive_path'] is None
    assert 'empty' in body['message'].lower()


def test_run_now_imports_iif_and_returns_counts(client, monkeypatch, tmp_path):
    """Happy path: Apps Script returns IIF, importer writes bills."""
    iif_text = '!HDR\tFOO\n'

    monkeypatch.setattr(
        'app.services.manual_import.IIF_ARCHIVE_DIR', tmp_path,
    )

    with patch('app.services.manual_import.requests.get') as mock_get, \
         patch('app.services.manual_import.import_all') as mock_import:
        mock_get.return_value = _mock_response(text=iif_text)
        mock_import.return_value = {
            'bills': 4, 'deposits': 1, 'duplicates_skipped': 2, 'errors': [],
        }

        r = client.post('/api/scheduled-import/run-now')

    assert r.status_code == 200, r.text
    body = r.json()
    assert body['bills'] == 4
    assert body['deposits'] == 1
    assert body['duplicates_skipped'] == 2
    assert body['errors'] == []
    assert body['iif_bytes'] == len(iif_text)
    assert body['archive_path'].startswith(str(tmp_path))
    # Archive file actually written.
    archive_files = list(tmp_path.glob('manual-import-*.iif'))
    assert len(archive_files) == 1
    assert archive_files[0].read_text() == iif_text


def test_run_now_propagates_importer_errors_field(client, monkeypatch, tmp_path):
    """When import_all reports per-row errors, the route surfaces them
    so the UI can show the user there's something wrong with the IIF."""
    monkeypatch.setattr(
        'app.services.manual_import.IIF_ARCHIVE_DIR', tmp_path,
    )

    with patch('app.services.manual_import.requests.get') as mock_get, \
         patch('app.services.manual_import.import_all') as mock_import:
        mock_get.return_value = _mock_response(text='!HDR\tFOO\n')
        mock_import.return_value = {
            'bills': 2, 'deposits': 0, 'duplicates_skipped': 0,
            'errors': ['row 5: bad date', 'row 7: unknown account'],
        }

        r = client.post('/api/scheduled-import/run-now')

    assert r.status_code == 200, r.text
    body = r.json()
    assert body['bills'] == 2
    assert len(body['errors']) == 2
    assert 'bad date' in body['errors'][0]


def test_run_now_502_when_env_missing(client, monkeypatch):
    """No URL/token configured → 502 with a message that tells the user
    exactly which env vars to set."""
    monkeypatch.delenv('APPS_SCRIPT_WEEKLY_URL', raising=False)
    monkeypatch.delenv('APPS_SCRIPT_WEEKLY_TOKEN', raising=False)

    r = client.post('/api/scheduled-import/run-now')

    assert r.status_code == 502, r.text
    assert 'APPS_SCRIPT_WEEKLY_URL' in r.json()['detail']
    assert 'APPS_SCRIPT_WEEKLY_TOKEN' in r.json()['detail']


def test_run_now_502_on_apps_script_json_error(client, monkeypatch):
    """Apps Script can't return non-200 status codes, so its errors come
    back as a 200 with JSON body. The service has to detect that shape
    and surface it rather than treating the JSON string as IIF content."""
    json_body = '{"error": "invalid token", "status": 401}'

    with patch('app.services.manual_import.requests.get') as mock_get:
        mock_get.return_value = _mock_response(
            text=json_body, headers={'Content-Type': 'application/json'},
        )

        r = client.post('/api/scheduled-import/run-now')

    assert r.status_code == 502, r.text
    detail = r.json()['detail']
    assert 'invalid token' in detail
    assert '401' in detail


def test_run_now_502_on_http_failure(client, monkeypatch):
    """Network failure / DNS / Apps Script unreachable → 502 with the
    underlying RequestException message. We don't leak the URL or token."""
    import requests as _requests

    with patch('app.services.manual_import.requests.get') as mock_get:
        mock_get.side_effect = _requests.ConnectionError('DNS lookup failed')

        r = client.post('/api/scheduled-import/run-now')

    assert r.status_code == 502, r.text
    assert 'DNS lookup failed' in r.json()['detail']


def test_run_now_502_on_non_200_status(client, monkeypatch):
    """A genuine non-200 (e.g. 503 from Google) should bubble up as 502
    with the upstream status + body excerpt."""
    with patch('app.services.manual_import.requests.get') as mock_get:
        mock_get.return_value = _mock_response(
            status_code=503, text='Service Unavailable',
        )

        r = client.post('/api/scheduled-import/run-now')

    assert r.status_code == 502, r.text
    assert '503' in r.json()['detail']


def test_run_now_passes_token_in_querystring(client, monkeypatch):
    """The Apps Script web app expects ?token=... per its doGet; the
    service must send the token there (not in a header) for auth to
    pass. Regression guard against accidentally moving it to a header."""
    with patch('app.services.manual_import.requests.get') as mock_get:
        mock_get.return_value = _mock_response(text='')

        client.post('/api/scheduled-import/run-now')

    assert mock_get.called
    _, kwargs = mock_get.call_args
    assert kwargs.get('params') == {'token': 'test-token-abc'}
