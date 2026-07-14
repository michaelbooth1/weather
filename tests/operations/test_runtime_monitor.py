import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

from weather.operations import runtime_monitor


def test_snapshot_projection_keeps_large_payload_bounded(tmp_path):
    now = datetime(2026, 7, 13, 1, 30, tzinfo=timezone.utc)
    status = {
        "pid": 42,
        "interval_minutes": 10,
        "last_heartbeat": (now - timedelta(seconds=20)).isoformat(),
        "last_snapshot_written_at": (now - timedelta(seconds=20)).isoformat(),
        "consecutive_errors": 1,
        "last_error": "MemoryError: payload 12345",
        "fleet_collection": {"huge": ["x" * 1000] * 100},
        "last_market_results": {"toronto": {"status": "ok"}, "nyc": {"error": "MemoryError"}},
        "forecast_payload_storage": {
            "schema_version": "forecast_payload_storage_observability_v0.1",
            "manifest_row_count": 2,
            "created_blob_count": 1,
            "reused_blob_count": 1,
            "logical_referenced_bytes": 200,
            "physical_bytes_written": 100,
            "avoided_bytes": 100,
            "physical_write_budget_bytes": 250,
            "physical_write_budget_status": "PASS",
            "payload_detail": ["x" * 1000] * 100,
        },
    }
    path = tmp_path / "status.json"
    path.write_text(json.dumps(status), encoding="utf-8")
    projected = runtime_monitor.project_component("snapshot", path, status, None, now)
    assert projected["state"] == "UNHEALTHY"
    assert projected["reason"] == "consecutive_errors"
    assert projected["counts"]["error_markets"] == 1
    assert "fleet_collection" not in projected
    assert projected["forecast_payload_storage"]["physical_bytes_written"] == 100
    assert projected["forecast_payload_storage"]["avoided_bytes"] == 100
    assert projected["forecast_payload_storage"]["network_fetch_count"] == 0
    assert projected["forecast_payload_storage"]["network_reuse_count"] == 0
    assert projected["forecast_payload_storage"]["cross_process_reuse_count"] == 0
    assert (
        projected["forecast_payload_storage"][
            "network_wait_timeout_fail_open_count"
        ]
        == 0
    )
    assert "payload_detail" not in projected["forecast_payload_storage"]
    assert len(json.dumps(projected)) < 5000


def test_snapshot_payload_storage_projection_falls_back_to_compact_market_rows():
    def row(*, created, reused, physical, avoided, budget, status):
        return {
            "forecast_payload_storage": {
                "schema_version": "forecast_payload_storage_observability_v0.1",
                "manifest_row_count": 1,
                "created_blob_count": created,
                "reused_blob_count": reused,
                "logical_referenced_bytes": 100,
                "physical_bytes_written": physical,
                "avoided_bytes": avoided,
                "physical_write_budget_bytes": budget,
                "physical_write_budget_status": status,
            }
        }

    projected = runtime_monitor._forecast_payload_storage({
        "last_market_results": {
            "toronto": row(created=1, reused=0, physical=100, avoided=0, budget=75, status="BLOCK"),
            "nyc": row(created=0, reused=1, physical=0, avoided=100, budget=75, status="PASS"),
        }
    })

    assert projected == {
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
        "physical_write_budget_bytes": 150,
        "physical_write_budget_status": "BLOCK",
    }


def test_bot_policy_state_is_not_misclassified_as_crash(tmp_path):
    now = datetime(2026, 7, 13, 1, 30, tzinfo=timezone.utc)
    status = {
        "pid": 43,
        "pid_alive": True,
        "status": "idle_process",
        "artifact_liveness": {"ok": True, "status": "POLICY_NO_EDGE"},
        "operator_report": {"taker_day_classification": "policy_guardrail_no_trade"},
    }
    projected = runtime_monitor.project_component("taker", tmp_path / "status.json", status, None, now)
    assert projected["state"] == "HEALTHY"
    assert projected["reason"] == "expected_policy_state"


def test_log_cursor_starts_at_eof_and_processes_new_complete_lines_once(tmp_path):
    path = tmp_path / "loop.log"
    path.write_text("historical MemoryError\n", encoding="utf-8")
    cursor = runtime_monitor._cursor_for(path)
    cursor, events = runtime_monitor.scan_log(cursor)
    assert events == []
    with path.open("ab") as handle:
        handle.write(b"new RuntimeError: failed 123\npartial MemoryError")
    cursor, events = runtime_monitor.scan_log(cursor)
    assert [event["event_type"] for event in events] == ["new_log_error_signature"]
    first_offset = cursor["offset"]
    cursor, events = runtime_monitor.scan_log(cursor)
    assert events == []
    assert cursor["offset"] == first_offset
    with path.open("ab") as handle:
        handle.write(b" continued\n")
    cursor, events = runtime_monitor.scan_log(cursor)
    assert len(events) == 1


def test_json_log_scanner_ignores_empty_error_contract_fields(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    path.write_text("", encoding="utf-8")
    cursor = runtime_monitor._cursor_for(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"errors": {}, "error_count": 0, "markets": {"x": {"error": None}}}) + "\n")
        handle.write(json.dumps({"markets": {"x": {"error": "MemoryError"}}}) + "\n")
    cursor, events = runtime_monitor.scan_log(cursor)
    assert len(events) == 1
    assert "MemoryError" in events[0]["summary"]


def test_json_log_scanner_ignores_disabled_paid_provider_policy_sentinels(tmp_path):
    path = tmp_path / "observation.jsonl"
    path.write_text("", encoding="utf-8")
    cursor = runtime_monitor._cursor_for(path)
    disabled = "Paid-provider weather endpoints are disabled by project policy; use free/local sources."
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "markets": {
                        "chicago": {
                            "trigger_context": {
                                "current_observation": {
                                    "source_status": {
                                        "wu_current": {"error": disabled},
                                        "wu_history": {"error": disabled},
                                        "metar": {"error": None},
                                    }
                                }
                            }
                        }
                    }
                }
            )
            + "\n"
        )
        handle.write(json.dumps({"markets": {"chicago": {"error": "MemoryError"}}}) + "\n")
    cursor, events = runtime_monitor.scan_log(cursor)
    assert len(events) == 1
    assert "MemoryError" in events[0]["summary"]


def test_resume_preserves_original_deadline_and_offsets(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_monitor, "REPO_ROOT", tmp_path)
    now = datetime(2026, 7, 13, 1, 30, tzinfo=timezone.utc)
    run_dir = runtime_monitor.create_run(tmp_path / "runs", 12, 15, 60, 300, now=now)
    manifest, state = runtime_monitor._load_run(run_dir)
    original_end = manifest["planned_end_at_utc"]
    state["log_cursors"]["snapshot_console"]["offset"] = 999
    runtime_monitor.write_json_atomic(run_dir / "run_state.json", state)
    manifest_after, state_after = runtime_monitor._load_run(run_dir)
    assert manifest_after["planned_end_at_utc"] == original_end
    assert state_after["log_cursors"]["snapshot_console"]["offset"] == 999


def test_host_summary_reports_percentiles():
    rows = [
        {
            "system_cpu_percent": value,
            "memory": {"commit_percent": 40 + value, "physical_available_bytes": 4 * 1024**3},
            "disk": {"free_bytes": 300 * 1024**3},
            "monitor_process": {"private_bytes": 20 * 1024**2},
            "sampler_elapsed_seconds": 0.01,
        }
        for value in range(1, 11)
    ]
    summary = runtime_monitor.summarize_host_samples(rows, bucket="test")
    cpu = summary["metrics"]["system_cpu_percent"]
    assert cpu["median"] == 5.5
    assert cpu["p95"] == 9.55
    assert cpu["max"] == 10.0


def test_elapsed_hour_index_uses_original_run_start():
    started_at = datetime(2026, 7, 13, 1, 48, 23, tzinfo=timezone.utc)
    assert runtime_monitor._elapsed_hour_index(started_at, started_at + timedelta(minutes=59)) == 0
    assert runtime_monitor._elapsed_hour_index(started_at, started_at + timedelta(hours=2, minutes=3)) == 2


def test_resume_seed_and_hour_filter_preserve_pre_restart_samples(tmp_path):
    started_at = datetime(2026, 7, 13, 1, 48, 23, tzinfo=timezone.utc)
    rows = [
        {"observed_at_utc": (started_at + timedelta(hours=1, minutes=59)).isoformat(), "value": 1},
        {"observed_at_utc": (started_at + timedelta(hours=2, minutes=1)).isoformat(), "value": 2},
        {"observed_at_utc": (started_at + timedelta(hours=2, minutes=30)).isoformat(), "value": 3},
    ]
    path = tmp_path / "host_samples.jsonl"
    path.write_text("\n".join([json.dumps(row) for row in rows] + ["not-json"]) + "\n", encoding="utf-8")

    seeded = runtime_monitor._load_recent_jsonl(path, 3)
    selected = runtime_monitor._samples_for_elapsed_hour(seeded, started_at, 3)

    assert [row["value"] for row in seeded] == [1, 2, 3]
    assert [row["value"] for row in selected] == [2, 3]


def test_resume_emits_missing_hours_once_and_final_boundary_emits_last_hour(tmp_path):
    started_at = datetime(2026, 7, 13, 1, 48, 23, tzinfo=timezone.utc)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rows = [
        {
            "observed_at_utc": (started_at + timedelta(minutes=30)).isoformat(),
            "system_cpu_percent": 1,
        },
        {
            "observed_at_utc": (started_at + timedelta(hours=1, minutes=30)).isoformat(),
            "system_cpu_percent": 2,
        },
        {
            "observed_at_utc": (started_at + timedelta(hours=2, minutes=30)).isoformat(),
            "system_cpu_percent": 3,
        },
    ]
    (run_dir / "host_samples.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    (run_dir / "hourly_summaries.jsonl").write_text(
        json.dumps({"bucket": "elapsed_hour_1", "sample_count": 1}) + "\n",
        encoding="utf-8",
    )
    component_rows = [
        {
            "observed_at_utc": (started_at + timedelta(minutes=30)).isoformat(),
            "component": "snapshot",
            "state": "HEALTHY",
        },
        {
            "observed_at_utc": (started_at + timedelta(hours=1, minutes=30)).isoformat(),
            "component": "snapshot",
            "state": "UNHEALTHY",
        },
        {
            "observed_at_utc": (started_at + timedelta(hours=2, minutes=30)).isoformat(),
            "component": "snapshot",
            "state": "HEALTHY",
        },
    ]
    (run_dir / "component_health.jsonl").write_text(
        "\n".join(json.dumps(row) for row in component_rows) + "\n",
        encoding="utf-8",
    )
    state = {"last_component_states": {"snapshot": "HEALTHY"}}
    planned_end = started_at + timedelta(hours=3)

    first = runtime_monitor._emit_completed_elapsed_hours(
        run_dir,
        state,
        started_at,
        started_at + timedelta(hours=2, minutes=5),
        planned_end_at=planned_end,
    )
    duplicate = runtime_monitor._emit_completed_elapsed_hours(
        run_dir,
        state,
        started_at,
        started_at + timedelta(hours=2, minutes=5),
        planned_end_at=planned_end,
    )
    final = runtime_monitor._emit_completed_elapsed_hours(
        run_dir,
        state,
        started_at,
        planned_end,
        planned_end_at=planned_end,
    )
    summaries = [
        json.loads(line)
        for line in (run_dir / "hourly_summaries.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert first == [2]
    assert duplicate == []
    assert final == [3]
    assert [row["bucket"] for row in summaries] == [
        "elapsed_hour_1",
        "elapsed_hour_2",
        "elapsed_hour_3",
    ]
    assert [row["sample_count"] for row in summaries] == [1, 1, 1]
    assert summaries[1]["component_states"] == {"snapshot": "UNHEALTHY"}
    assert summaries[2]["component_states"] == {"snapshot": "HEALTHY"}
    assert summaries[1]["component_states_source"] == "component_health_tape"


def test_hourly_summary_emitter_waits_for_writer_lock_and_rechecks(tmp_path, monkeypatch):
    started_at = datetime(2026, 7, 13, 1, 48, 23, tzinfo=timezone.utc)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    summary_path = run_dir / "hourly_summaries.jsonl"
    summary_path.touch()
    (run_dir / "host_samples.jsonl").write_text(
        json.dumps(
            {
                "observed_at_utc": (started_at + timedelta(minutes=30)).isoformat(),
                "system_cpu_percent": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "component_health.jsonl").touch()
    held_lock = runtime_monitor.acquire_writer_lock(summary_path, attempts=1)
    assert held_lock is not None
    entered = Event()
    original_acquire = runtime_monitor.acquire_writer_lock

    def tracked_acquire(*args, **kwargs):
        entered.set()
        return original_acquire(*args, **kwargs)

    monkeypatch.setattr(runtime_monitor, "acquire_writer_lock", tracked_acquire)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            runtime_monitor._emit_completed_elapsed_hours,
            run_dir,
            {"run_id": "test"},
            started_at,
            started_at + timedelta(hours=1),
            planned_end_at=started_at + timedelta(hours=1),
        )
        assert entered.wait(timeout=2)
        runtime_monitor.append_jsonl(summary_path, {"bucket": "elapsed_hour_1"})
        runtime_monitor.release_writer_lock(held_lock)
        assert future.result(timeout=5) == []

    rows = [json.loads(line) for line in summary_path.read_text(encoding="utf-8").splitlines()]
    assert [row["bucket"] for row in rows] == ["elapsed_hour_1"]


def _seed_terminal_run(tmp_path, monkeypatch, *, duration_hours=1):
    started_at = datetime(2026, 7, 13, 1, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(runtime_monitor, "_git_value", lambda *_args: None)
    run_dir = runtime_monitor.create_run(
        tmp_path / "runs",
        duration_hours,
        10,
        60,
        300,
        now=started_at,
    )
    runtime_monitor.append_jsonl(
        run_dir / "host_samples.jsonl",
        {
            "observed_at_utc": (started_at + timedelta(minutes=30)).isoformat(),
            "system_cpu_percent": 2,
        },
    )
    return run_dir, started_at


def _patch_monitor_sampling(monkeypatch, observed_at):
    class FakeSampler:
        def sample(self, _run_dir):
            return {
                "observed_at_utc": observed_at.isoformat(),
                "system_cpu_percent": 3,
            }

    monkeypatch.setattr(runtime_monitor, "HostSampler", FakeSampler)
    monkeypatch.setattr(runtime_monitor, "_component_tick", lambda *_args: [])
    monkeypatch.setattr(runtime_monitor, "_powershell_enrichment", lambda **_kwargs: {})


def test_normal_terminal_path_reconciles_final_completed_hour(tmp_path, monkeypatch):
    run_dir, started_at = _seed_terminal_run(tmp_path, monkeypatch)
    before_boundary = started_at + timedelta(minutes=59, seconds=50)
    planned_end = started_at + timedelta(hours=1)
    _patch_monitor_sampling(monkeypatch, before_boundary)
    clock_values = iter([before_boundary] * 5 + [planned_end] * 10)
    monkeypatch.setattr(runtime_monitor, "utc_now", lambda: next(clock_values))

    result = runtime_monitor.run_monitor(
        run_dir,
        sleep_fn=lambda _seconds: None,
        monotonic_fn=lambda: 0.0,
    )

    summaries = runtime_monitor._load_recent_jsonl(run_dir / "hourly_summaries.jsonl", 10)
    assert result["lifecycle"] == "completed"
    assert [row["bucket"] for row in summaries] == ["elapsed_hour_1"]


def test_output_budget_terminal_path_reconciles_completed_hours(tmp_path, monkeypatch):
    run_dir, started_at = _seed_terminal_run(tmp_path, monkeypatch, duration_hours=2)
    before_boundary = started_at + timedelta(minutes=59, seconds=50)
    after_boundary = started_at + timedelta(hours=1, minutes=5)
    _patch_monitor_sampling(monkeypatch, after_boundary)
    clock_values = iter([before_boundary] * 4 + [after_boundary] * 10)
    monkeypatch.setattr(runtime_monitor, "utc_now", lambda: next(clock_values))
    monkeypatch.setattr(runtime_monitor, "OUTPUT_BUDGET_BYTES", -1)

    result = runtime_monitor.run_monitor(
        run_dir,
        sleep_fn=lambda _seconds: None,
        monotonic_fn=lambda: 0.0,
    )

    summaries = runtime_monitor._load_recent_jsonl(run_dir / "hourly_summaries.jsonl", 10)
    assert result["lifecycle"] == "output_budget_exceeded"
    assert [row["bucket"] for row in summaries] == ["elapsed_hour_1"]


def test_finalize_cli_reconciles_completed_hours(tmp_path, monkeypatch, capsys):
    run_dir, started_at = _seed_terminal_run(tmp_path, monkeypatch)
    planned_end = started_at + timedelta(hours=1)
    monkeypatch.setattr(runtime_monitor, "utc_now", lambda: planned_end)

    assert runtime_monitor.main(["finalize", "--run-dir", str(run_dir)]) == 0

    output = json.loads(capsys.readouterr().out)
    summaries = runtime_monitor._load_recent_jsonl(run_dir / "hourly_summaries.jsonl", 10)
    assert output["lifecycle"] == "completed"
    assert [row["bucket"] for row in summaries] == ["elapsed_hour_1"]
