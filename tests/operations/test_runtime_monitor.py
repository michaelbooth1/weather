import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
