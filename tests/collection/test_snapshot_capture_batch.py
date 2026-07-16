import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import weather.collection.snapshot_tracker as tracker
from weather.collection.snapshot_capture_batch import (
    DEFAULT_CAPTURE_HOST_RESERVE_MB,
    DEFAULT_CAPTURE_WORKERS,
    DEFAULT_CHILD_WORKING_SET_MAX_MB,
    capture_command,
    capture_worker_admission,
    console_python_executable,
    run_bounded_capture_batch,
    run_isolated_capture,
)
from weather.collection.snapshot_tracker import capture_runtime_fingerprint_gate


NOW = datetime(2026, 7, 11, 18, 0, tzinfo=timezone.utc)


def request(market_id):
    return {"market_id": market_id, "force": False, "target_date": "2026-07-11"}


def successful_record(row, started_at=NOW, completed_at=None):
    return {
        "market_id": row["market_id"],
        "started_at": started_at,
        "completed_at": completed_at or (started_at + timedelta(seconds=1)),
        "result": {
            "written": True,
            "snapshot_id": f"{row['market_id']}-snapshot",
        },
        "execution": {"mode": "synthetic"},
    }


def test_bounded_batch_admits_due_order_and_proves_three_way_overlap():
    rows = [request(f"market-{index}") for index in range(6)]
    lock = threading.Lock()
    release = threading.Event()
    active = 0
    max_active = 0

    def runner(row, _timeout):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active == 3:
                release.set()
        assert release.wait(timeout=2), "three captures were not admitted concurrently"
        time.sleep(0.01)
        with lock:
            active -= 1
        return successful_record(row)

    result = run_bounded_capture_batch(
        rows,
        worker_count=3,
        fleet_budget_seconds=10,
        market_timeout_seconds=5,
        heartbeat_seconds=0.01,
        runner_fn=runner,
    )

    assert max_active == 3
    assert result["summary"]["max_active"] == 3
    assert result["summary"]["submission_order"] == [row["market_id"] for row in rows]
    assert [record["market_id"] for record in result["records"]] == [
        row["market_id"] for row in rows
    ]


def test_slow_market_does_not_block_other_worker_or_reorder_output():
    rows = [request("slow"), request("fast-a"), request("fast-b")]
    completion_order = []
    lock = threading.Lock()

    def runner(row, _timeout):
        time.sleep(0.08 if row["market_id"] == "slow" else 0.005)
        with lock:
            completion_order.append(row["market_id"])
        return successful_record(row)

    result = run_bounded_capture_batch(
        rows,
        worker_count=2,
        fleet_budget_seconds=10,
        market_timeout_seconds=5,
        heartbeat_seconds=0.01,
        runner_fn=runner,
    )

    assert completion_order[:2] == ["fast-a", "fast-b"]
    assert [record["market_id"] for record in result["records"]] == [
        "slow",
        "fast-a",
        "fast-b",
    ]


def test_one_runner_exception_is_a_market_result_not_a_batch_failure():
    rows = [request("a"), request("broken"), request("c")]

    def runner(row, _timeout):
        if row["market_id"] == "broken":
            raise RuntimeError("provider exploded")
        return successful_record(row)

    result = run_bounded_capture_batch(
        rows,
        worker_count=2,
        fleet_budget_seconds=10,
        market_timeout_seconds=5,
        runner_fn=runner,
    )

    broken = result["records"][1]["result"]
    assert broken["written"] is False
    assert broken["capture_status"] == "capture_runner_exception"
    assert result["records"][2]["result"]["written"] is True
    assert result["summary"]["error_count"] == 1


def test_market_timeout_is_tightened_to_fit_all_waves_inside_fleet_budget():
    rows = [request(f"market-{index}") for index in range(6)]
    timeouts = []

    def runner(row, timeout_seconds):
        timeouts.append(timeout_seconds)
        return successful_record(row)

    result = run_bounded_capture_batch(
        rows,
        worker_count=2,
        fleet_budget_seconds=8,
        market_timeout_seconds=120,
        runner_fn=runner,
    )

    assert result["summary"]["wave_count"] == 3
    assert result["summary"]["effective_market_timeout_seconds"] == 2.0
    assert timeouts and max(timeouts) <= 2.0


def test_isolated_capture_uses_atomic_child_result_and_process_tree_limits():
    observed = {}

    def subprocess_runner(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        result_path = Path(command[command.index("--result-json") + 1])
        result_path.write_text(
            json.dumps({"written": True, "snapshot_id": "synthetic"}),
            encoding="utf-8",
        )
        return {
            "returncode": 0,
            "timed_out": False,
            "duration_seconds": 0.25,
            "working_set_limit": {"applied": True},
            "resource_peaks": {
                "working_set_peak_bytes": 128 * 1024 * 1024,
                "private_memory_peak_bytes": 384 * 1024 * 1024,
            },
            "resource_io": {"read_bytes": 1024, "write_bytes": 512},
            "resource_limit_exceeded": None,
            "containment": {"status": "PASS", "process_tree_contained": True},
            "termination": {"triggered": False},
            "stderr": "",
            "runner_error": None,
        }

    result = run_isolated_capture(
        request("toronto"),
        12,
        expected_runtime_fingerprint="fingerprint",
        python_executable="python.exe",
        cwd="repo",
        working_set_max_mb=512,
        shared_source_cooldown_path="shared-cooldown.json",
        shared_forecast_payload_cas_root="shared-cas",
        market_invariant_fetch_scope="fleet-pass-1",
        subprocess_runner=subprocess_runner,
        now_fn=lambda: NOW,
    )

    assert result["result"] == {"written": True, "snapshot_id": "synthetic"}
    assert observed["kwargs"]["timeout_seconds"] == 12.0
    assert observed["kwargs"]["working_set_max_bytes"] == 512 * 1024 * 1024
    assert observed["kwargs"]["env"]["WEATHER_SOURCE_FAMILY_COOLDOWN_PATH"] == "shared-cooldown.json"
    assert observed["kwargs"]["env"]["WEATHER_FORECAST_FANOUT_CAS_ROOT"] == "shared-cas"
    assert observed["kwargs"]["env"]["WEATHER_FORECAST_FANOUT_SCOPE"] == "fleet-pass-1"
    assert "--expected-runtime-fingerprint" in observed["command"]
    assert result["execution"]["containment"]["process_tree_contained"] is True
    assert result["execution"]["resource_peaks"]["private_memory_peak_bytes"] == (
        384 * 1024 * 1024
    )
    assert result["execution"]["resource_io"]["read_bytes"] == 1024
    assert result["execution"]["resource_limit_exceeded"] is None


def test_production_defaults_bound_aggregate_commit_with_headroom():
    assert DEFAULT_CAPTURE_WORKERS == 2
    assert DEFAULT_CHILD_WORKING_SET_MAX_MB == 1792
    assert DEFAULT_CAPTURE_WORKERS * DEFAULT_CHILD_WORKING_SET_MAX_MB < 3 * 1536
    assert DEFAULT_CAPTURE_HOST_RESERVE_MB == 1536


def test_worker_admission_preserves_full_child_ceilings_and_host_reserve():
    mib = 1024 * 1024
    two_workers = capture_worker_admission(
        2,
        child_memory_max_mb=1792,
        host_reserve_mb=1536,
        available_memory_bytes=(1536 + 2 * 1792) * mib,
    )
    one_worker = capture_worker_admission(
        2,
        child_memory_max_mb=1792,
        host_reserve_mb=1536,
        available_memory_bytes=(1536 + 1792) * mib,
    )
    blocked = capture_worker_admission(
        2,
        child_memory_max_mb=1792,
        host_reserve_mb=1536,
        available_memory_bytes=(1536 + 1792) * mib - 1,
    )
    unknown = capture_worker_admission(2, available_memory_bytes=None)

    assert two_workers["admitted_worker_count"] == 2
    assert two_workers["reason"] == "requested_workers_admitted"
    assert one_worker["admitted_worker_count"] == 1
    assert one_worker["reason"] == "worker_count_reduced_for_physical_memory"
    assert blocked["status"] == "BLOCK"
    assert blocked["admitted_worker_count"] == 0
    assert unknown["status"] == "BLOCK"
    assert unknown["reason"] == "measurement_unavailable"


def test_isolated_capture_classifies_and_persists_resource_limit_evidence():
    limit = 1792 * 1024 * 1024
    observed = limit + 4096

    def subprocess_runner(_command, **_kwargs):
        return {
            "returncode": 137,
            "timed_out": False,
            "duration_seconds": 2.5,
            "working_set_limit": {
                "applied": True,
                "private_memory_max_bytes": limit,
            },
            "resource_peaks": {
                "working_set_peak_bytes": 320 * 1024 * 1024,
                "private_memory_peak_bytes": observed,
            },
            "resource_io": {"read_bytes": 42, "write_bytes": 7},
            "resource_limit_exceeded": {
                "resource": "private_memory_bytes",
                "observed_bytes": observed,
                "limit_bytes": limit,
            },
            "containment": {"status": "PASS", "process_tree_contained": True},
            "termination": {
                "triggered": True,
                "reason": "resource_budget_exceeded",
            },
            "stderr": "",
            "runner_error": None,
        }

    record = run_isolated_capture(
        request("atlanta"),
        12,
        python_executable="python.exe",
        cwd="repo",
        working_set_max_mb=1792,
        subprocess_runner=subprocess_runner,
        now_fn=lambda: NOW,
    )

    assert record["result"]["capture_status"] == "capture_resource_budget"
    assert "observed_bytes=" in record["result"]["error"]
    assert record["execution"]["resource_limit_exceeded"] == {
        "resource": "private_memory_bytes",
        "observed_bytes": observed,
        "limit_bytes": limit,
    }
    assert record["execution"]["resource_peaks"]["private_memory_peak_bytes"] == observed


def test_command_preserves_force_date_market_and_parent_runtime_identity(tmp_path):
    command = capture_command(
        {"market_id": "seattle", "force": True, "target_date": "2026-07-11"},
        result_path=tmp_path / "result.json",
        expected_runtime_fingerprint="abc123",
        python_executable="python.exe",
    )

    assert command[:3] == ["python.exe", "-m", "weather.collection.snapshot_tracker"]
    assert command[command.index("--market") + 1] == "seattle"
    assert command[command.index("--target-date") + 1] == "2026-07-11"
    assert command[command.index("--expected-runtime-fingerprint") + 1] == "abc123"
    assert "--force" in command


def test_pythonw_children_use_console_sibling_when_present(tmp_path):
    pythonw = tmp_path / "pythonw.exe"
    python = tmp_path / "python.exe"
    pythonw.touch()
    python.touch()

    assert console_python_executable(pythonw) == str(python)


def test_isolated_child_runtime_identity_gate_fails_closed():
    identity = {"source_fingerprint": "child"}

    assert capture_runtime_fingerprint_gate("child", identity)["ok"] is True
    mismatch = capture_runtime_fingerprint_gate("parent", identity)
    assert mismatch["ok"] is False
    assert mismatch["actual"] == "child"
    assert mismatch["expected"] == "parent"
    assert capture_runtime_fingerprint_gate("parent", {})["ok"] is False


def test_child_cli_writes_atomic_block_result_before_capture_on_runtime_mismatch(
    tmp_path,
    monkeypatch,
):
    result_path = tmp_path / "capture-result.json"

    def forbidden_capture(**_kwargs):
        raise AssertionError("runtime-mismatched child must not fetch or write a snapshot")

    monkeypatch.setattr(tracker, "capture_snapshot", forbidden_capture)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "snapshot_tracker",
            "--market",
            "toronto",
            "--expected-runtime-fingerprint",
            "definitely-not-this-runtime",
            "--result-json",
            str(result_path),
        ],
    )

    tracker.main()
    payload = json.loads(result_path.read_text(encoding="utf-8"))

    assert payload["status"] == "BLOCK"
    assert payload["written"] is False
    assert payload["runtime_fingerprint_gate"]["ok"] is False


def test_managed_loop_integrates_batch_heartbeats_and_isolates_market_error(
    tmp_path,
    monkeypatch,
):
    specs = [SimpleNamespace(id="a"), SimpleNamespace(id="broken"), SimpleNamespace(id="c")]
    due_rows = [
        (
            spec,
            {
                "market_id": spec.id,
                "event_slug": f"event-{spec.id}",
                "target_date": "2026-07-11",
                "due": True,
                "last_snapshot_at": (NOW - timedelta(minutes=20)).isoformat(),
                "next_due_at": (NOW - timedelta(minutes=11)).isoformat(),
            },
        )
        for spec in specs
    ]

    def fake_batch(requests, **kwargs):
        kwargs["progress_fn"]({
            "active_markets": ["a", "broken", "c"],
            "queued_markets": [],
            "completed_markets": [],
            "worker_count": 3,
        })
        records = []
        for index, row in enumerate(requests, start=1):
            result = (
                {"written": False, "error": "capture_timeout: synthetic"}
                if row["market_id"] == "broken"
                else {
                    "written": True,
                    "snapshot_id": f"{row['market_id']}-snapshot",
                    "next_due_at": (NOW + timedelta(minutes=9)).isoformat(),
                    "forecast_payload_storage": {
                        "schema_version": "forecast_payload_storage_observability_v0.1",
                        "manifest_row_count": 1,
                        "created_blob_count": int(row["market_id"] == "a"),
                        "reused_blob_count": int(row["market_id"] == "c"),
                        "logical_referenced_bytes": 100,
                        "physical_bytes_written": 100 if row["market_id"] == "a" else 0,
                        "avoided_bytes": 100 if row["market_id"] == "c" else 0,
                        "physical_write_budget_bytes": 200,
                        "physical_write_budget_status": "PASS",
                        "unbounded_detail": ["must not reach loop status"] * 100,
                    },
                }
            )
            records.append({
                "market_id": row["market_id"],
                "started_at": NOW,
                "completed_at": NOW + timedelta(seconds=index),
                "result": result,
                "execution": {"mode": "synthetic_isolated"},
            })
        return {
            "records": records,
            "summary": {
                "mode": "isolated_subprocess_batch",
                "worker_count": 3,
                "request_count": 3,
            },
        }

    class NoopPower:
        def start(self):
            return {"status": "synthetic"}

        def stop(self):
            return None

    monkeypatch.setattr(tracker, "LOOP_STATUS_PATH", tmp_path / "loop_status.json")
    monkeypatch.setattr(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl")
    monkeypatch.setattr(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag")
    monkeypatch.setattr(tracker, "all_specs", lambda: specs)
    monkeypatch.setattr(tracker, "ordered_snapshot_specs", lambda *_args, **_kwargs: due_rows)
    monkeypatch.setattr(tracker, "run_bounded_capture_batch", fake_batch)
    monkeypatch.setattr(
        tracker,
        "runtime_identity_status",
        lambda *_args, **_kwargs: {"runtime_code_state": "current_code"},
    )
    monkeypatch.setattr(
        tracker,
        "current_fleet_collection_health",
        lambda **_kwargs: {"summary": {}, "markets": []},
    )
    monkeypatch.setattr(tracker, "keep_system_awake", lambda _reason: NoopPower())

    status = tracker.run_loop(
        interval_minutes=10,
        max_iterations=1,
        sleep_fn=lambda _seconds: None,
        now_fn=lambda: NOW,
        capture_workers=3,
        available_memory_fn=lambda: 16 * 1024**3,
    )

    persisted = json.loads((tmp_path / "loop_status.json").read_text(encoding="utf-8"))
    assert status["last_capture_batch"]["mode"] == "isolated_subprocess_batch"
    assert status["last_snapshot_id"] == "c-snapshot"
    assert status["consecutive_errors"] == 1
    assert "broken: capture_timeout" in status["last_error"]
    assert status["markets_in_progress"] == []
    assert persisted["last_market_in_progress"] is None
    assert persisted["last_market_results"]["broken"]["error"]
    assert persisted["last_market_results"]["a"]["execution"]["mode"] == "synthetic_isolated"
    assert "unbounded_detail" not in persisted["last_market_results"]["a"]["forecast_payload_storage"]
    assert persisted["forecast_payload_storage"] == {
        "schema_version": "forecast_payload_storage_observability_v0.1",
        "manifest_row_count": 2,
        "created_blob_count": 1,
        "reused_blob_count": 1,
        "logical_referenced_bytes": 200,
        "physical_bytes_written": 100,
        "avoided_bytes": 100,
        "network_fetch_count": 0,
        "network_reuse_count": 0,
        "cross_process_reuse_count": 0,
        "network_wait_timeout_fail_open_count": 0,
        "coordinator_attributions": [],
        "coordinator_evidence_count": 0,
        "coordinator_network_fetch_count": 0,
        "coordinator_physical_bytes_written": 0,
        "coordinator_attribution_unavailable_count": 0,
        "physical_write_budget_bytes": 400,
        "physical_write_budget_status": "PASS",
    }


def test_managed_loop_fails_closed_before_spawning_when_memory_cannot_admit_one(
    tmp_path,
    monkeypatch,
):
    spec = SimpleNamespace(id="atlanta")
    due_state = {
        "market_id": spec.id,
        "event_slug": "event-atlanta",
        "target_date": "2026-07-11",
        "due": True,
        "last_snapshot_at": (NOW - timedelta(minutes=20)).isoformat(),
        "next_due_at": (NOW - timedelta(minutes=11)).isoformat(),
    }

    class NoopPower:
        def start(self):
            return {"status": "synthetic"}

        def stop(self):
            return None

    monkeypatch.setattr(tracker, "LOOP_STATUS_PATH", tmp_path / "loop_status.json")
    monkeypatch.setattr(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl")
    monkeypatch.setattr(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag")
    monkeypatch.setattr(tracker, "all_specs", lambda: [spec])
    monkeypatch.setattr(
        tracker,
        "ordered_snapshot_specs",
        lambda *_args, **_kwargs: [(spec, due_state)],
    )
    monkeypatch.setattr(
        tracker,
        "run_bounded_capture_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("memory-blocked pass must not start a child batch")
        ),
    )
    monkeypatch.setattr(
        tracker,
        "runtime_identity_status",
        lambda *_args, **_kwargs: {"runtime_code_state": "current_code"},
    )
    monkeypatch.setattr(
        tracker,
        "current_fleet_collection_health",
        lambda **_kwargs: {"summary": {}, "markets": []},
    )
    monkeypatch.setattr(tracker, "keep_system_awake", lambda _reason: NoopPower())

    status = tracker.run_loop(
        interval_minutes=10,
        max_iterations=1,
        sleep_fn=lambda _seconds: None,
        now_fn=lambda: NOW,
        available_memory_fn=lambda: 0,
    )

    persisted = json.loads((tmp_path / "loop_status.json").read_text(encoding="utf-8"))
    assert status["last_iteration_outcome"] == "error"
    assert "capture_host_memory_admission" in status["last_error"]
    assert persisted["capture_execution"]["worker_admission"]["status"] == "BLOCK"
    execution = persisted["last_market_results"]["atlanta"]["execution"]
    assert execution["mode"] == "host_memory_admission"
    assert execution["worker_admission"]["admitted_worker_count"] == 0
