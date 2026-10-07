"""The public WU history client never lets the page access token escape into persisted text.

Guards: OD15 (owner decision 2026-10-06) -- fetch failures, error rows, raw day files and urllib3 DEBUG
logs from weather.sources.wu_history carry no WU page token; fetch values are unchanged.
"""

from __future__ import annotations

import json
import logging
import secrets
import traceback
from datetime import date
from zoneinfo import ZoneInfo

import pytest
import requests
import urllib3.exceptions

from weather.operations.wu_token_scan import scan
from weather.sources import wu_history
from weather.sources.wu_history import (
    PUBLIC_WU_HISTORY_SOURCE,
    PublicWundergroundHistoryClient,
    WundergroundHistoryStore,
    redact_api_key,
)

DAY = date(2026, 6, 19)
API_ROOT = "https://api.example.invalid"


@pytest.fixture
def token():
    return "FAKEKEY" + secrets.token_hex(16)


@pytest.fixture(autouse=True)
def restore_http_loggers():
    names = ("urllib3", "urllib3.connectionpool", "requests")
    saved = {name: logging.getLogger(name).level for name in names}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def _page(token):
    runtime = {"API_URL": API_ROOT, "API_KEY": token}
    return f"<html><script>const data = {json.dumps(runtime)};</script></html>"


def _prepared_url(url, params):
    return requests.Request("GET", url, params=params).prepare().url


class _PageResponse:
    status_code = 200
    url = "https://www.example.invalid/history/daily/KLGA/date/2026-6-19"

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class _Session:
    """Serves the page, then fails or answers the API call the way requests would."""

    def __init__(self, token, mode):
        self.token = token
        self.mode = mode
        self.api_params = None

    def get(self, url, params=None, **_kwargs):
        if params is None:
            return _PageResponse(_page(self.token))
        self.api_params = dict(params)
        full_url = _prepared_url(url, params)
        if self.mode == "connection":
            path = full_url.split("example.invalid", 1)[1]
            retry = urllib3.exceptions.MaxRetryError(None, path, reason=OSError("connect failed"))
            try:
                raise retry
            except urllib3.exceptions.MaxRetryError as exc:
                raise requests.ConnectionError(exc) from exc
        response = requests.Response()
        response.url = full_url
        if self.mode == "http404":
            response.status_code = 404
            response.reason = "Not Found"
            return response
        response.status_code = 200
        response._content = json.dumps({
            "observations": [{
                "valid_time_gmt": 1781870400,
                "temp": 77,
                "dewPt": 60,
                "obs_id": "KLGA",
            }],
        }).encode("utf-8")
        return response


def _client(token, mode):
    session = _Session(token, mode)
    client = PublicWundergroundHistoryClient(
        history_id="KLGA:9:US",
        station_icao="KLGA",
        units="e",
        session=session,
        page_base="https://www.example.invalid",
    )
    return client, session


def _store(tmp_path):
    return WundergroundHistoryStore(
        tmp_path / "wunderground" / "klga",
        station_icao="KLGA",
        history_id="KLGA:9:US",
        tz=ZoneInfo("America/New_York"),
        unit="F",
        wu_units="e",
    )


def _rendered(exc_info):
    return "".join(traceback.format_exception(exc_info.type, exc_info.value, exc_info.tb))


def _assert_tree_clean(root, token):
    result = scan([root], exact_token=token.encode("utf-8"))
    assert result.files_scanned > 0
    assert result.errors == []
    assert [row["path"] for row in result.findings] == []


@pytest.mark.parametrize("mode, error_type", [
    ("connection", requests.ConnectionError),
    ("http404", requests.HTTPError),
])
def test_fetch_failure_text_and_error_row_carry_no_token(tmp_path, token, mode, error_type):
    client, session = _client(token, mode)
    store = _store(tmp_path)

    with pytest.raises(error_type) as caught:
        client.fetch_range(DAY, DAY)

    assert session.api_params["apiKey"] == token  # the fetch itself is unchanged
    assert token not in str(caught.value)
    assert token not in _rendered(caught)
    row = store.write_fetch_error(DAY, DAY, caught.value, source=PUBLIC_WU_HISTORY_SOURCE)
    assert token not in json.dumps(row)
    if mode == "http404":
        assert row["status_code"] == 404
        assert row["failure_class"] == "transient"  # page-backed 404 stays retryable
        assert row["url"].endswith("apiKey=<redacted>&units=e&startDate=20260619&endDate=20260619")
    _assert_tree_clean(tmp_path, token)


def test_successful_fetch_persists_no_token_and_pins_debug_loggers(tmp_path, token):
    logging.getLogger("urllib3").setLevel(logging.DEBUG)
    client, session = _client(token, "ok")
    assert logging.getLogger("urllib3").level == logging.WARNING
    store = _store(tmp_path)

    payload = client.fetch_range(DAY, DAY)
    store.write_payload(DAY, DAY, payload)
    store.rebuild_normalized_files()

    assert session.api_params["apiKey"] == token
    assert payload["observations"][0]["temp"] == 77
    _assert_tree_clean(tmp_path, token)


def test_redact_api_key_delegates_to_the_shared_helper(token):
    text = f'url ?apiKey={token}&x=1 runtime {{"API_KEY":"{token}"}} js API_KEY = \'{token}\''
    redacted = redact_api_key(text)
    assert token not in redacted
    assert redacted.count("<redacted>") == 3


def test_mutant_client_without_sanitize_leaks_the_token(token, monkeypatch):
    monkeypatch.setattr(wu_history, "sanitize_exception", lambda exc: exc)
    client, _session = _client(token, "connection")

    with pytest.raises(requests.ConnectionError) as caught:
        client.fetch_range(DAY, DAY)

    assert token in _rendered(caught)
