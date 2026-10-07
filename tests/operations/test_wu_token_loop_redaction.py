"""WU page-token redaction at the capture-loop error builders (source fetch payloads, trigger status).

Guards: OD15 (owner decision 2026-10-06) and gate Defender MF-5 -- once WU history is enabled, a fetch
error quoting its request URL must not write the page token into source payloads, snapshot inputs,
observation-trigger status, diagnostics or trigger rows.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests
import urllib3.exceptions

from weather.model import source_adapters
from weather.model.source_adapters import fetch_source
from weather.operations import observation_trigger
from weather.operations.observation_trigger import run_once


@pytest.fixture
def token():
    return "FAKEKEY" + secrets.token_hex(16)


def _token_error(token):
    url = f"/v1/location/KLGA:9:US/observations/historical.json?apiKey={token}&units=e"
    retry = urllib3.exceptions.MaxRetryError(None, url, reason=OSError("connect failed"))
    try:
        try:
            raise retry
        except urllib3.exceptions.MaxRetryError as exc:
            raise requests.ConnectionError(exc) from exc
    except requests.ConnectionError as outer:
        return outer


def _raising(token):
    def fetcher():
        raise _token_error(token)
    return fetcher


def test_fetch_source_error_payload_carries_no_token(token):
    name, payload = fetch_source("wu_history", _raising(token))

    assert name == "wu_history"
    assert payload["ok"] is False
    assert "apiKey=<redacted>" in payload["error"]
    assert token not in json.dumps(payload, default=str)


def test_mutant_fetch_source_without_redaction_leaks(token, monkeypatch):
    monkeypatch.setattr(source_adapters, "sanitize_exception", lambda exc: exc)
    monkeypatch.setattr(source_adapters, "redact_wu_secrets", lambda value: value)

    _name, payload = fetch_source("wu_history", _raising(token))

    assert token in payload["error"]


def _trigger_args(tmp_path):
    return SimpleNamespace(
        market="toronto",
        status_out=str(tmp_path / "observation_trigger_status.json"),
        events_out=str(tmp_path / "observation_trigger_events.jsonl"),
        diagnostics_out=str(tmp_path / "observation_trigger_diagnostics.jsonl"),
        trigger_queue_root=str(tmp_path / "triggered_snapshot_queue"),
        support_margin=0.5,
        dry_run=True,
        trigger_on_first=False,
        stale_after_seconds=180.0,
        interval_seconds=60.0,
    )


def _run_trigger(tmp_path, token):
    def fake_fetch(_market_id, now=None, **_kwargs):
        raise _token_error(token)

    def fake_capture(**_kwargs):
        raise AssertionError("no snapshot is captured on a fetch failure")

    return run_once(
        _trigger_args(tmp_path),
        capture_func=fake_capture,
        fetch_state_func=fake_fetch,
        now=datetime(2026, 6, 13, 16, 1, tzinfo=timezone.utc),
    )


def _written(tmp_path):
    return "".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in tmp_path.rglob("*")
        if path.is_file()
    )


def test_observation_trigger_status_and_diagnostics_carry_no_token(tmp_path, token):
    result = _run_trigger(tmp_path, token)

    assert result["status"] == "error"
    status = json.loads((tmp_path / "observation_trigger_status.json").read_text(encoding="utf-8"))
    assert "apiKey=<redacted>" in status["last_error"]
    assert token not in json.dumps(result, default=str)
    assert token not in _written(tmp_path)


def test_mutant_observation_trigger_without_redaction_leaks(tmp_path, token, monkeypatch):
    monkeypatch.setattr(observation_trigger, "redact_wu_secrets", lambda value: value)

    _run_trigger(tmp_path, token)

    assert token in _written(tmp_path)
