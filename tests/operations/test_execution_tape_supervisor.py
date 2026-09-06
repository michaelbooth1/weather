from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from weather.operations.execution_tape_supervisor import (
    _handshake_worker_identity,
    _worker_command,
    _validate_managed_scope,
    ensure_decision,
    ensure_managed_capture,
    execution_tape_health,
    read_status,
    run_managed_capture,
    start_managed_capture,
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


def test_transient_status_access_failure_recovers_current_worker(tmp_path) -> None:
    path = tmp_path / "status.json"
    payload = _status()
    text = json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    with (
        patch("pathlib.Path.read_text", side_effect=[PermissionError("busy"), text]) as read,
        patch("weather.operations.execution_tape_supervisor.time.sleep") as sleep,
    ):
        recovered = read_status(path)
    health = execution_tape_health(
        recovered, now=NOW, pid_alive=True, current_identity=_identity(),
    )
    assert recovered == payload
    assert read.call_count == 2
    sleep.assert_called_once_with(0.05)
    assert ensure_decision(health["state"], True) == "noop"


def test_persistently_unreadable_status_exhausts_bounded_retry(tmp_path) -> None:
    path = tmp_path / "status.json"
    path.write_text("incomplete JSON", encoding="utf-8")
    with (
        patch("pathlib.Path.read_text", return_value="incomplete JSON") as read,
        patch("weather.operations.execution_tape_supervisor.time.sleep") as sleep,
    ):
        assert read_status(path) is None
    assert read.call_count == 3
    assert sleep.call_count == 2
    assert execution_tape_health(None, now=NOW)["state"] == "UNKNOWN"


def test_retry_does_not_make_stale_status_healthy() -> None:
    cases = (
        (_status(runtime_identity=_identity("old")), "STALE_CODE"),
        (_status(last_heartbeat=(NOW - timedelta(minutes=4)).isoformat()), "HUNG"),
    )
    for payload, expected in cases:
        with (
            patch("weather.operations.execution_tape_supervisor.read_json_file", side_effect=[None, payload]),
            patch("weather.operations.execution_tape_supervisor.time.sleep"),
        ):
            recovered = read_status("unused.json")
        health = execution_tape_health(
            recovered, now=NOW, pid_alive=True, current_identity=_identity(),
        )
        assert health["state"] == expected
        assert ensure_decision(health["state"], True) == "restart"


def test_ensure_samples_health_clock_after_recovered_status() -> None:
    module = "weather.operations.execution_tape_supervisor."
    payload = _status(last_heartbeat=(NOW + timedelta(milliseconds=25)).isoformat())
    with (
        patch(module + "utc_now", side_effect=[NOW, NOW + timedelta(milliseconds=50)]),
        patch(module + "acquire_supervisor_lock", return_value=1),
        patch(module + "release_file_lock"),
        patch(module + "read_json_file", side_effect=[None, payload]),
        patch(module + "time.sleep"),
        patch(module + "pid_is_python", return_value=True),
        patch(module + "runtime_identity_matches", return_value=(True, _identity())),
        patch(module + "loop_writer_lock_health", return_value={"healthy": True}),
        patch(module + "supervisor_recovery_guard", return_value={"allowed": True}),
        patch(module + "persist_supervisor_status", side_effect=lambda spec, result, **kw: result),
        patch(module + "start_managed_capture") as start,
        patch(module + "stop_managed_capture") as stop,
    ):
        result = ensure_managed_capture()
    assert result["action"] == "noop"
    assert result["state"] == "RUNNING"
    assert result["pid"] == payload["pid"]
    start.assert_not_called()
    stop.assert_not_called()


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
        "verified_at_capture": True,
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
        "verified_at_capture": True,
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


def test_worker_handshake_adopts_exact_direct_child_of_windows_venv_launcher() -> None:
    command = [r"C:\repo\venv\Scripts\pythonw.exe", "-m", "worker"]
    launched = {
        "pid": 4321,
        "creation_time_token": "launcher-token",
        "expected_command": command,
        "verified_at_capture": True,
    }
    worker = {
        "pid": 5432,
        "creation_time_token": "worker-token",
        "expected_command": command,
        "verified_at_capture": True,
    }
    status = {
        "pid": 5432,
        "last_heartbeat": NOW.isoformat(),
        "state": "CONNECTING",
        "runtime_identity": {"source_fingerprint": "source"},
        "managed_process": worker,
    }
    lock = {"exists": True, "pid": 5432, "managed_process": worker}
    observation = {
        "state": "running",
        "pid": 5432,
        "parent_pid": 4321,
        "inspectable": True,
        "creation_time_token": "worker-token",
        "argv": command,
    }

    result = wait_for_worker_handshake(
        pid=4321,
        managed_process=launched,
        status_reader=lambda: status,
        lock_reader=lambda _path: lock,
        pid_check=lambda _pid: True,
        observe_fn=lambda _pid: observation,
        monotonic_fn=lambda: 1.0,
        sleep_fn=lambda _seconds: None,
    )

    assert result["ready"] is True
    assert result["pid"] == 5432
    assert result["launched_pid"] == 4321
    assert result["managed_process"] == worker


def test_worker_handshake_rejects_matching_process_from_unrelated_parent() -> None:
    command = ["python", "-m", "worker"]
    launched = {
        "pid": 4321,
        "creation_time_token": "launcher-token",
        "expected_command": command,
        "verified_at_capture": True,
    }
    worker = {
        "pid": 5432,
        "creation_time_token": "worker-token",
        "expected_command": command,
        "verified_at_capture": True,
    }
    status = {"pid": 5432, "managed_process": worker}
    lock = {"exists": True, "pid": 5432, "managed_process": worker}

    candidate = _handshake_worker_identity(
        status,
        lock,
        launched_pid=4321,
        launched_process=launched,
        observe_fn=lambda _pid: {
            "state": "running",
            "pid": 5432,
            "parent_pid": 9999,
            "inspectable": True,
            "creation_time_token": "worker-token",
            "argv": command,
        },
    )

    assert candidate is None


def test_start_returns_the_worker_child_identity_not_the_venv_launcher() -> None:
    options = {
        "market": "all",
        "event_metadata": str(DEFAULT_EVENT_METADATA),
        "snapshots_root": str(DEFAULT_SNAPSHOTS_ROOT),
    }
    command = _worker_command(**options)
    launched = {
        "pid": 4321,
        "creation_time_token": "launcher-token",
        "expected_command": command,
        "verified_at_capture": True,
    }
    worker = {
        "pid": 5432,
        "creation_time_token": "worker-token",
        "expected_command": command,
        "verified_at_capture": True,
    }
    with (
        patch(
            "weather.operations.execution_tape_supervisor._cleanup_writer_lock",
            return_value={"removed": False},
        ),
        patch(
            "weather.operations.execution_tape_supervisor.rotate_sidecar_policy",
            return_value={},
        ),
        patch(
            "weather.operations.execution_tape_supervisor.launch_detached",
            return_value=SimpleNamespace(pid=4321),
        ),
        patch(
            "weather.operations.execution_tape_supervisor.capture_managed_process_identity",
            return_value=launched,
        ),
        patch(
            "weather.operations.execution_tape_supervisor.wait_for_worker_handshake",
            return_value={
                "ready": True,
                "pid": 5432,
                "managed_process": worker,
            },
        ),
        patch("weather.operations.execution_tape_supervisor.append_diagnostic"),
    ):
        result = start_managed_capture(**options)

    assert result["started"] is True
    assert result["pid"] == 5432
    assert result["launched_pid"] == 4321
    assert result["managed_process"] == worker
    assert result["launched_process"] == launched


def test_failed_handshake_terminates_exact_candidate_and_launcher() -> None:
    options = {
        "market": "all",
        "event_metadata": str(DEFAULT_EVENT_METADATA),
        "snapshots_root": str(DEFAULT_SNAPSHOTS_ROOT),
    }
    command = _worker_command(**options)
    launched = {
        "pid": 4321,
        "creation_time_token": "launcher-token",
        "expected_command": command,
        "verified_at_capture": True,
    }
    worker = {
        "pid": 5432,
        "creation_time_token": "worker-token",
        "expected_command": command,
        "verified_at_capture": True,
    }
    with (
        patch(
            "weather.operations.execution_tape_supervisor._cleanup_writer_lock",
            side_effect=[{"removed": False}, {"removed": True}],
        ),
        patch(
            "weather.operations.execution_tape_supervisor.rotate_sidecar_policy",
            return_value={},
        ),
        patch(
            "weather.operations.execution_tape_supervisor.launch_detached",
            return_value=SimpleNamespace(pid=4321),
        ),
        patch(
            "weather.operations.execution_tape_supervisor.capture_managed_process_identity",
            return_value=launched,
        ),
        patch(
            "weather.operations.execution_tape_supervisor.wait_for_worker_handshake",
            return_value={
                "ready": False,
                "reason": "handshake incomplete",
                "candidate_managed_process": worker,
            },
        ),
        patch(
            "weather.operations.execution_tape_supervisor.terminate_managed_process",
            side_effect=[
                {"stopped": True, "exited": True, "reason": "worker exited"},
                {"stopped": True, "exited": True, "reason": "launcher exited"},
            ],
        ) as terminate,
        patch("weather.operations.execution_tape_supervisor.append_diagnostic"),
    ):
        result = start_managed_capture(**options)

    assert result["started"] is False
    assert result["pid"] == 5432
    assert terminate.call_args_list[0].args == (worker, command)
    assert terminate.call_args_list[1].args == (launched, command)


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
        "verified_at_capture": True,
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
