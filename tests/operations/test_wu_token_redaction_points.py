"""WU page access-token redaction at the daily-refresh restore step and the backfill runner.

Guards: OD15 (owner decision 2026-10-06) -- the scraped WU page token never reaches step status JSON,
backfill_errors.jsonl, tracebacks, runner ledgers or urllib3 DEBUG logs.
"""

from __future__ import annotations

import logging
import secrets
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
import urllib3.exceptions

from weather.collection import historical_backfill_runner
from weather.collection.historical_backfill_runner import tail_text
from weather.operations import daily_refresh_source_steps
from weather.operations.daily_refresh_source_steps import run_public_wu_settlement_restore_step

TARGET = "2026-06-19"


@pytest.fixture
def token():
    return "FAKEKEY" + secrets.token_hex(16)


@pytest.fixture
def http_loggers():
    names = ("urllib3", "urllib3.connectionpool", "requests")
    saved = {name: logging.getLogger(name).level for name in names}
    yield names
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def _token_connection_error(token):
    """An unsanitized failure as the client raised it before OD15."""
    url = f"/v1/location/KLGA:9:US/observations/historical.json?apiKey={token}&units=e"
    retry = urllib3.exceptions.MaxRetryError(None, url, reason=OSError("connect failed"))
    try:
        try:
            raise retry
        except urllib3.exceptions.MaxRetryError as exc:
            raise requests.ConnectionError(exc) from exc
    except requests.ConnectionError as outer:
        return outer


def _spec(root):
    return SimpleNamespace(
        id="nyc",
        icao="KLGA",
        city_label="NYC",
        wu_history_id="KLGA:9:US",
        tz="America/New_York",
        display_unit="F",
        wu_units="e",
        data_root=Path(root) / "wunderground" / "klga",
    )


def _args(root, continue_on_error):
    return SimpleNamespace(
        backtest_root=str(Path(root) / "backtest"),
        settled_analysis_target_date=TARGET,
        wu_settlement_restore_markets="nyc",
        wu_settlement_restore_retries=0,
        wu_settlement_restore_retry_backoff=0.0,
        wu_settlement_restore_sleep=0,
        wu_settlement_restore_continue_on_error=continue_on_error,
    )


def _failing_client(token):
    class FailingClient:
        def __init__(self, **_kwargs):
            pass

        def fetch_range(self, *_args, **_kwargs):
            raise _token_connection_error(token)

    return FailingClient


def _all_text_under(root):
    return "".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in Path(root).rglob("*")
        if path.is_file()
    )


def _run(monkeypatch, tmp_path, token, continue_on_error):
    monkeypatch.setattr(daily_refresh_source_steps, "all_specs", lambda: [_spec(tmp_path)])
    monkeypatch.setattr(
        daily_refresh_source_steps, "PublicWundergroundHistoryClient", _failing_client(token)
    )
    return run_public_wu_settlement_restore_step(_args(tmp_path, continue_on_error))


def test_restore_step_error_rows_and_status_json_carry_no_token(monkeypatch, tmp_path, token, http_loggers):
    logging.getLogger("urllib3").setLevel(logging.DEBUG)

    result = _run(monkeypatch, tmp_path, token, continue_on_error=True)

    assert result["status"] == "BLOCK"
    assert result["error_count"] == 1
    written = _all_text_under(tmp_path)
    assert (tmp_path / "wunderground" / "klga" / "backfill_errors.jsonl").is_file()
    assert "<redacted>" in written
    assert token not in written
    assert logging.getLogger("urllib3").level == logging.WARNING


def test_restore_step_reraise_is_sanitized_for_status_tracebacks(monkeypatch, tmp_path, token):
    with pytest.raises(requests.ConnectionError) as caught:
        _run(monkeypatch, tmp_path, token, continue_on_error=False)

    rendered = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert token not in str(caught.value)
    assert token not in rendered
    assert token not in _all_text_under(tmp_path)


def test_mutant_restore_step_without_sanitize_leaks_into_traceback(monkeypatch, tmp_path, token):
    monkeypatch.setattr(daily_refresh_source_steps, "sanitize_exception", lambda exc: exc)

    with pytest.raises(requests.ConnectionError) as caught:
        _run(monkeypatch, tmp_path, token, continue_on_error=False)

    rendered = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert token in rendered


def test_backfill_runner_tails_redact_every_token_form(token):
    text = "\n".join([
        f"failed url https://api.example.invalid/v1/x?APIKEY={token}&units=e",
        f'runtime {{"API_KEY":"{token}"}}',
        f'payload {{"apiKey": "{token}"}}',
    ])

    redacted = tail_text(text)

    assert token not in redacted
    assert redacted.count("<redacted>") == 3


def test_mutant_backfill_runner_without_shared_helper_leaks(monkeypatch, token):
    monkeypatch.setattr(historical_backfill_runner, "redact_wu_secrets", lambda value: value)

    assert token in tail_text(f'runtime {{"API_KEY":"{token}"}}')
