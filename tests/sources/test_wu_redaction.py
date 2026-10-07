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


def _capture_handler():
    import io

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    return stream, handler


def _emit_urllib3_url_warnings(token):
    """Log the two urllib3 2.x WARNING lines that carry the full request URL, in urllib3's format."""
    url = f"https://api.example.invalid/v1/location/KXXX:9:US/observations/historical.json?apiKey={token}&units=e"
    logging.getLogger("urllib3.connection").warning(
        "Failed to parse headers (url=%s): %s", url, "HeaderParsingError", exc_info=False
    )
    logging.getLogger("urllib3.connectionpool").warning(
        "Retrying (%r) after connection broken by '%r': %s", "Retry(total=2)", "ProtocolError()", url
    )
    logging.getLogger("urllib3.util.retry").warning("Retry on %s", url)


@pytest.fixture
def clean_http_log_filters():
    names = wu_redaction.HTTP_LOG_REDACTION_LOGGERS
    root = logging.getLogger()
    saved = {name: list(logging.getLogger(name).filters) for name in names}
    saved_root_level = root.level
    yield
    root.setLevel(saved_root_level)
    for name, filters in saved.items():
        logging.getLogger(name).filters[:] = filters


def test_install_wu_log_redaction_redacts_urllib3_warning_urls(token, clean_http_log_filters):
    """Defender F1: urllib3 logs the full URL at WARNING; the WARNING pin cannot stop it."""
    stream, handler = _capture_handler()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        pin_http_debug_loggers()
        assert wu_redaction.install_wu_log_redaction() == len(wu_redaction.HTTP_LOG_REDACTION_LOGGERS)
        assert wu_redaction.install_wu_log_redaction() == 0  # idempotent
        _emit_urllib3_url_warnings(token)
    finally:
        root.removeHandler(handler)
    text = stream.getvalue()
    assert token not in text and token[7:] not in text
    assert text.count("apiKey=" + REDACTED) == 3
    assert "Failed to parse headers" in text and "Retrying" in text


def test_mutant_without_log_filter_leaks_the_url(token, clean_http_log_filters):
    stream, handler = _capture_handler()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        pin_http_debug_loggers()
        _emit_urllib3_url_warnings(token)
    finally:
        root.removeHandler(handler)
    assert token in stream.getvalue()


def test_log_filter_on_a_handler_covers_any_logger_and_exceptions(token):
    stream, handler = _capture_handler()
    assert wu_redaction.install_wu_log_redaction(logger_names=(), handlers=[handler]) == 1
    logger = logging.getLogger("weather.test.wu_redaction_handler_probe")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        try:
            raise _connection_error(token)
        except requests.ConnectionError:
            logger.warning("fetch failed for %s", {"apiKey": token}, exc_info=True)
        logger.warning("plain apiKey=%s", token, stack_info=True)
    finally:
        logger.removeHandler(handler)
        logger.propagate = True
    text = stream.getvalue()
    assert token not in text
    assert "Traceback" in text and "ConnectionError" in text


def test_log_redaction_logger_list_covers_installed_urllib3():
    """Every urllib3 module logger exists in the list (a logger filter misses child records)."""
    import importlib
    import pkgutil
    import warnings

    import urllib3

    emitting = {"urllib3"}
    for module_info in pkgutil.walk_packages(urllib3.__path__, "urllib3."):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # optional backends warn about missing extras
                module = importlib.import_module(module_info.name)
        except Exception:  # noqa: BLE001 - optional backends (socks, pyodide) may not import.
            continue
        for value in vars(module).values():
            if isinstance(value, logging.Logger) and value.name.startswith("urllib3"):
                emitting.add(value.name)
    assert emitting <= set(wu_redaction.HTTP_LOG_REDACTION_LOGGERS), sorted(
        emitting - set(wu_redaction.HTTP_LOG_REDACTION_LOGGERS)
    )


# --- N3: the redactor cleans every form the scanner flags (prior F4) -------------------


def _encoded_forms(token):
    return [
        f"%22apiKey%22%3A%22{token}%22",
        f"q=%22apikey%22%3a%22{token}%22&x=1",
        f"%27apiKey%27%3A%20%27{token}%27",
        f"apiKey%3A{token}",
        f"apikey%3a{token}",
        f"apiKey&#61;{token}",
        f"%2522apiKey%2522%253A%2522{token}%2522",
        f"apiKey%253D{token}",
        f"\\u0022apiKey\\u0022:\\u0022{token}\\u0022",
        f"\\u0022apiKey\\u0022\\u003a\\u0022{token}\\u0022",
        f"X-Api-Key: {token}",
        f"{{'X-Api-Key': '{token}'}}",
    ]


@pytest.mark.parametrize("index", range(len(_encoded_forms("t"))))
def test_encoded_forms_the_scanner_flags_are_redacted(index, tmp_path):
    from weather.operations.wu_token_scan import EXIT_CLEAN, EXIT_FOUND, exit_code_for, scan

    hex_token = secrets.token_hex(16)
    text = _encoded_forms(hex_token)[index]
    flagged = tmp_path / "before.log"
    flagged.write_text(text, encoding="utf-8")
    assert exit_code_for(scan([flagged])) == EXIT_FOUND  # precondition: the scanner flags it

    redacted = redact_wu_secrets(text)

    assert hex_token not in redacted.lower(), text.replace(hex_token, "<fake>")
    assert REDACTED in redacted
    assert redact_wu_secrets(redacted) == redacted  # idempotent
    cleaned = tmp_path / "after.log"
    cleaned.write_text(redacted, encoding="utf-8")
    assert exit_code_for(scan([cleaned])) == EXIT_CLEAN


# --- N3: exceptions whose args hold a dict or another object (prior F2) ----------------


class _Payload:
    def __init__(self, token):
        self.token = token

    def __repr__(self):
        return f"_Payload(apiKey={self.token!r})"


def test_sanitize_exception_redacts_dict_and_object_args(token):
    nested = RuntimeError({"params": {"apiKey": token, "units": "e"}, "tries": [f"apiKey={token}"]})
    obj = ValueError(_Payload(token), 7)
    keyed = KeyError({f"apiKey={token}": 1})
    for error in (nested, obj, keyed):
        assert token in _rendered(error)  # precondition: the token is in the rendered text
        sanitize_exception(error)
        assert token not in _rendered(error)
        assert token not in str(error) and token not in repr(error)
    # Non-secret structure survives: dicts stay dicts, plain values are untouched.
    assert nested.args[0]["params"]["units"] == "e"
    assert obj.args[1] == 7


def test_log_filter_redacts_a_dict_arg_exception(token):
    """Defender N3 (prior F2 through the filter): a dict-arg exception in exc_info."""
    stream, handler = _capture_handler()
    wu_redaction.install_wu_log_redaction(logger_names=(), handlers=[handler])
    logger = logging.getLogger("weather.test.wu_redaction_dict_arg_probe")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        try:
            raise RuntimeError({"params": {"apiKey": token}})
        except RuntimeError:
            logger.warning("boom", exc_info=True)
    finally:
        logger.removeHandler(handler)
        logger.propagate = True
    text = stream.getvalue()
    assert token not in text
    assert "Traceback" in text and "RuntimeError" in text
