"""WU page access-token redaction helpers.

Guards: OD15 (owner decision 2026-10-06) -- the scraped WU page token is never persisted in logs,
error rows, status JSON or tracebacks; docs/operations/HISTORY_DATA_DESIGN.md "Page access token".
"""

from __future__ import annotations

import logging
import re
import secrets
import traceback

import pytest
import requests
import urllib3.exceptions

from weather.sources import wu_redaction
from weather.sources.wu_history import failure_class_for_exception
from weather.sources.wu_redaction import (
    REDACTED,
    pin_http_debug_loggers,
    redact_wu_secrets,
    sanitize_exception,
)


@pytest.fixture
def token():
    return "FAKEKEY" + secrets.token_hex(16)


def _forms(token):
    return [
        f"https://api.example.invalid/v1/x/historical.json?apiKey={token}&units=m",
        f"https://api.example.invalid/v1/x/historical.json?units=m&APIKEY={token}",
        f"GET /v1/x?apikey%3D{token}",
        f'{{"apiKey":"{token}"}}',
        f'{{"apiKey": "{token}", "units": "m"}}',
        f'{{"API_KEY":"{token}","API_URL":"https://api.example.invalid"}}',
        f'"{{\\"API_KEY\\":\\"{token}\\"}}"',
        f"&q;API_KEY&q;:&q;{token}&q;",
        f"&quot;API_KEY&quot;:&quot;{token}&quot;",
        f"API_KEY = '{token}';",
        f"api_key={token})",
    ]


def test_every_token_form_is_redacted(token):
    for text in _forms(token):
        redacted = redact_wu_secrets(text)
        assert token not in redacted, text.replace(token, "<fake>")
        assert REDACTED in redacted


def test_redaction_is_idempotent_and_keeps_other_text(token):
    text = f"https://api.example.invalid/x?apiKey={token}&units=m&startDate=20260619"
    once = redact_wu_secrets(text)
    assert once == "https://api.example.invalid/x?apiKey=<redacted>&units=m&startDate=20260619"
    assert redact_wu_secrets(once) == once
    assert redact_wu_secrets(None) is None
    assert redact_wu_secrets("no secrets here") == "no secrets here"


def _http_error(token, status_code):
    response = requests.Response()
    response.status_code = status_code
    response.url = f"https://api.example.invalid/v1/x/historical.json?apiKey={token}&units=m"
    error = requests.HTTPError(
        f"{status_code} Client Error: Not Found for url: {response.url}", response=response
    )
    return error


def _connection_error(token):
    url = f"/v1/x/historical.json?apiKey={token}&units=m"
    inner = urllib3.exceptions.NewConnectionError(None, "Failed to establish a new connection")
    retry = urllib3.exceptions.MaxRetryError(None, url, reason=inner)
    try:
        try:
            raise retry
        except urllib3.exceptions.MaxRetryError as exc:
            raise requests.ConnectionError(exc) from exc
    except requests.ConnectionError as outer:
        return outer


def _rendered(exc):
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def test_sanitize_exception_redacts_http_error_text_urls_and_keeps_classification(token):
    error = _http_error(token, 404)
    assert token in str(error)  # precondition: requests puts the URL in the message
    before = failure_class_for_exception(error, page_backed=True)

    assert sanitize_exception(error) is error

    assert token not in str(error)
    assert token not in repr(error)
    assert token not in error.response.url
    assert token not in _rendered(error)
    assert error.response.status_code == 404
    assert failure_class_for_exception(error, page_backed=True) == before


def test_sanitize_exception_redacts_the_whole_connection_error_chain(token):
    error = _connection_error(token)
    assert token in _rendered(error)  # precondition: urllib3 quotes the query string

    sanitize_exception(error)

    assert token not in str(error)
    assert token not in _rendered(error)
    assert token not in error.__cause__.url
    assert isinstance(error, requests.ConnectionError)


def test_sanitize_exception_survives_cycles_and_odd_args(token):
    first = ValueError(f"apiKey={token}", b"apiKey=" + token.encode(), [f"apiKey={token}"], 3)
    second = RuntimeError(first)
    first.__context__ = second
    sanitize_exception(second)
    assert token not in _rendered(second)
    assert first.args[3] == 3


def test_pin_http_debug_loggers_raises_permissive_levels_only():
    names = wu_redaction.HTTP_DEBUG_LOGGERS
    saved = {name: logging.getLogger(name).level for name in names}
    try:
        logging.getLogger("urllib3").setLevel(logging.DEBUG)
        logging.getLogger("urllib3.connectionpool").setLevel(logging.NOTSET)
        logging.getLogger("requests").setLevel(logging.ERROR)
        pin_http_debug_loggers()
        assert logging.getLogger("urllib3").level == logging.WARNING
        assert logging.getLogger("urllib3.connectionpool").level == logging.WARNING
        assert logging.getLogger("requests").level == logging.ERROR
        assert not logging.getLogger("urllib3.connectionpool").isEnabledFor(logging.DEBUG)
    finally:
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)


def test_mutant_without_redaction_is_detected(token, monkeypatch):
    """With the redaction regex disabled the same checks must fail."""
    monkeypatch.setattr(wu_redaction, "_SECRET_RE", re.compile(r"(?!x)x"))
    assert any(token in redact_wu_secrets(text) for text in _forms(token))
    error = _connection_error(token)
    sanitize_exception(error)
    assert token in _rendered(error)
