from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from weather.operations.execution_tape_supervisor import (
    _worker_command,
    _validate_managed_scope,
    ensure_decision,
    execution_tape_health,
    run_managed_capture,
    wait_for_worker_handshake,
)
from weather.market.execution_tape_capture import DEFAULT_EVENT_METADATA
from weather.market.execution_tape_store import DEFAULT_SNAPSHOTS_ROOT


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def _identity(fingerprint: str = "current") -> dict:
    return {
        "schema_version": "runtime_identity_v0.1",
        "source_fingerprint": fingerprint,
        "source_scope_files": ["src/weather/market/execution_tape_capture.py"],
    }


def _status(**updates) -> dict:
    payload = {
        "pid": 1234,
        "started_at": (NOW - timedelta(hours=1)).isoformat(),
        "last_heartbeat": (NOW - timedelta(seconds=5)).isoformat(),
        "state": "CONNECTED",
        "evidence_integrity": "PASS",
        "price_path_evidence_usable": True,
        "active_market_day_count": 12,
        "runtime_identity": _identity(),
    }
    payload.update(updates)
    return payload


def test_health_separates_process_liveness_from_public_evidence_quality() -> None:
    running = execution_tape_health(
        _status(),
        now=NOW,
        pid_alive=True,
        current_identity=_identity(),
    )
    degraded = execution_tape_health(
        _status(state="DISCONNECTED", price_path_evidence_usable=False),
        now=NOW,
        pid_alive=True,
        current_identity=_identity(),
    )

    assert running["state"] == "RUNNING"
    assert running["runtime_identity_matches_current"] is True
    assert degraded["state"] == "DEGRADED"
    assert ensure_decision(degraded["state"], True) == "noop"


def test_health_restarts_stale_code_hung_and_dead_workers() -> None:
    stale = execution_tape_health(
        _status(),
        now=NOW,
        pid_alive=True,
        current_identity=_identity("changed"),
    )
    hung = execution_tape_health(
        _status(last_heartbeat=(NOW - timedelta(minutes=4)).isoformat()),
        now=NOW,
        pid_alive=True,
        current_identity=_identity(),
    )
    dead = execution_tape_health(
        _status(),
        now=NOW,
        pid_alive=False,
        current_identity=_identity(),
    )

    assert stale["state"] == "STALE_CODE"
    assert hung["state"] == "HUNG"
    assert dead["state"] == "DEAD"
    assert ensure_decision(stale["state"], True) == "restart"
    assert ensure_decision(hung["state"], True) == "restart"
    assert ensure_decision(dead["state"], False) == "start"


def test_missing_writer_lock_never_noops() -> None:
    assert ensure_decision("RUNNING", True, writer_lock_healthy=False) == "restart"
    assert ensure_decision("DEAD", False, writer_lock_healthy=False) == "start"


def test_managed_command_is_public_capture_only() -> None:
    command = _worker_command()
    text = " ".join(command).lower()

    assert command[1:4] == ["-m", "weather.operations.execution_tape_supervisor", "run"]
    assert "--market all" in text
    for forbidden in (
        "credential",
        "private-key",
        "api-key",
        "wallet",
        "live-order",
        "cancel-order",
        "polymarket_us",
    ):
        assert forbidden not in text


def test_managed_scope_requires_all_markets_and_canonical_paths() -> None:
    valid = {
        "market": "all",
        "event_metadata": str(DEFAULT_EVENT_METADATA),
        "snapshots_root": str(DEFAULT_SNAPSHOTS_ROOT),
    }
    _validate_managed_scope(valid)

    for invalid in (
        {**valid, "market": "toronto"},
        {**valid, "event_metadata": "other.json"},
        {**valid, "snapshots_root": "other-root"},
    ):
        try:
            _validate_managed_scope(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("noncanonical managed scope was accepted")


def test_worker_handshake_requires_matching_status_lock_and_process_instance() -> None:
    managed = {
        "pid": 4321,
        "creation_time_token": "token",
        "expected_command": ["python", "-m", "worker"],
    }
    status = {
        "pid": 4321,
        "last_heartbeat": NOW.isoformat(),
        "state": "CONNECTING",
        "runtime_identity": {"source_fingerprint": "source"},
        "managed_process": managed,
    }
    lock = {"exists": True, "pid": 4321, "managed_process": managed}

    result = wait_for_worker_handshake(
        pid=4321,
        managed_process=managed,
        status_reader=lambda: status,
        lock_reader=lambda _path: lock,
        pid_check=lambda _pid: True,
        monotonic_fn=lambda: 1.0,
        sleep_fn=lambda _seconds: None,
    )

    assert result["ready"] is True
    assert result["status_state"] == "CONNECTING"


def test_worker_handshake_fails_immediately_when_child_exits() -> None:
    managed = {
        "pid": 4321,
        "creation_time_token": "token",
        "expected_command": ["python", "-m", "worker"],
    }
    result = wait_for_worker_handshake(
        pid=4321,
        managed_process=managed,
        status_reader=lambda: {},
        lock_reader=lambda _path: {"exists": False},
        pid_check=lambda _pid: False,
        monotonic_fn=lambda: 1.0,
        sleep_fn=lambda _seconds: None,
    )

    assert result["ready"] is False
    assert "exited" in result["reason"]


def test_managed_worker_binds_process_identity_into_capture_status() -> None:
    options = {
        "market": "all",
        "event_metadata": str(DEFAULT_EVENT_METADATA),
        "snapshots_root": str(DEFAULT_SNAPSHOTS_ROOT),
        "max_part_bytes": 1024,
        "max_tokens_per_connection": 50,
        "seed_check_seconds": 60.0,
        "heartbeat_seconds": 10.0,
        "inbound_silence_timeout_seconds": 30.0,
        "connect_timeout_seconds": 30.0,
        "event_metadata_max_age_hours": 36.0,
    }
    managed = {
        "pid": 4321,
        "creation_time_token": "test-token",
        "expected_command": _worker_command(**options),
    }
    identity = {"source_fingerprint": "source", "source_scope_files": ["capture.py"]}
    with (
        patch(
            "weather.operations.execution_tape_supervisor.capture_managed_process_identity",
            return_value=managed,
        ),
        patch(
            "weather.operations.execution_tape_supervisor.get_runtime_identity",
            return_value=identity,
        ),
        patch("weather.operations.execution_tape_supervisor.os.getpid", return_value=4321),
        patch("weather.operations.execution_tape_supervisor.run_live_capture") as capture,
    ):
        run_managed_capture(**options)

    kwargs = capture.call_args.kwargs
    assert kwargs["markets"] == "all"
    assert kwargs["process_status"]["pid"] == 4321
    assert kwargs["process_status"]["managed_process"] == managed
    assert kwargs["process_status"]["runtime_identity"] == identity
    assert kwargs["process_status"]["started_by"] == "supervisor"
