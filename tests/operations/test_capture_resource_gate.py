import json
import os
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from weather.operations.capture_resource_gate import (
    DAILY_REFRESH_WORKLOAD,
    EVIDENCE_CONTRACT,
    SCHEMA_VERSION,
    CaptureLoopSpec,
    build_capture_resource_gate,
    inspect_capture_loop,
    main,
    persist_pipeline_admission,
    render_report,
    write_outputs,
)


NOW = datetime(2026, 7, 12, 1, 0, tzinfo=timezone.utc)
DiskUsage = namedtuple("DiskUsage", "total used free")


def status_path(root: Path, name: str) -> Path:
    return root / f"{name}.json"


def write_loop(
    root: Path,
    name: str,
    *,
    pid: int,
    heartbeat: datetime = NOW,
    interval_seconds: float = 60.0,
    paused: bool = False,
    errors: int = 0,
    writer_lock: bool = True,
) -> CaptureLoopSpec:
    path = status_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "pid": pid,
            "last_heartbeat": heartbeat.isoformat(),
            "interval_seconds": interval_seconds,
            "paused": paused,
            "consecutive_errors": errors,
            "last_error": "boom" if errors else None,
            "runtime_identity": {"git_commit": "abc123", "source_fingerprint": "source"},
        }),
        encoding="utf-8",
    )
    if writer_lock:
        path.with_name(f".{path.name}.writer.lock").write_text(
            json.dumps({
                "pid": pid,
                "loop": name,
                "module": f"weather.{name}",
                "acquired_at_utc": heartbeat.isoformat(),
            }),
            encoding="utf-8",
        )
    return CaptureLoopSpec(name, path, interval_seconds)


def high_resources(**kwargs):
    return {
        "min_free_memory_bytes": 1_000,
        "min_free_disk_bytes": 1_000,
        "memory_available_fn": lambda: 10_000,
        "disk_usage_fn": lambda _path: DiskUsage(total=100_000, used=20_000, free=80_000),
        **kwargs,
    }


def test_live_capture_loops_block_heavy_work_with_exact_evidence(tmp_path):
    specs = tuple(write_loop(tmp_path, name, pid=index) for index, name in enumerate(
        ("snapshot", "clob", "observation_trigger"),
        start=101,
    ))

    payload = build_capture_resource_gate(
        workload="training",
        disk_path=tmp_path,
        loop_specs=specs,
        now=NOW,
        process_checker=lambda pid: pid in {101, 102, 103},
        **high_resources(),
    )

    assert payload["schema_version"] == SCHEMA_VERSION == "capture_resource_gate_v0.1"
    assert payload["status"] == "BLOCK"
    assert payload["admitted"] is False
    assert payload["decision"] == "DEFER"
    assert payload["evidence_contract"] == EVIDENCE_CONTRACT
    assert payload["summary"]["active_loop_count"] == 3
    assert {row["code"] for row in payload["blockers"]} == {"live_capture_loop_active"}
    assert {row["evidence"]["loop"] for row in payload["blockers"]} == {
        "snapshot",
        "clob",
        "observation_trigger",
    }
    assert payload["summary"]["suggested_defer_until_utc"]
    assert payload["safety_contract"]["stops_or_signals_processes"] is False


def test_fresh_heartbeat_and_writer_lock_are_active_without_pid_discovery(tmp_path):
    spec = write_loop(tmp_path, "snapshot", pid=999_999)

    evidence = inspect_capture_loop(
        spec,
        now=NOW,
        process_checker=lambda _pid: False,
    )

    assert evidence["process_diagnostics"]["status_pid_alive"] is False
    assert evidence["portable_active_evidence"] is True
    assert evidence["active"] is True
    assert evidence["state"] == "ACTIVE_HEALTHY"


def test_process_discovery_failure_does_not_override_portable_active_evidence(tmp_path):
    spec = write_loop(tmp_path, "snapshot", pid=123)

    def denied(_pid):
        raise PermissionError("process query denied")

    evidence = inspect_capture_loop(spec, now=NOW, process_checker=denied)

    assert evidence["active"] is True
    assert evidence["portable_active_evidence"] is True
    assert "PermissionError" in evidence["process_diagnostics"]["status_pid_error"]


def test_stale_capture_blocks_active_window_even_when_process_is_dead(tmp_path):
    spec = write_loop(
        tmp_path,
        "snapshot",
        pid=404,
        heartbeat=NOW - timedelta(hours=2),
    )

    payload = build_capture_resource_gate(
        disk_path=tmp_path,
        loop_specs=(spec,),
        now=NOW,
        process_checker=lambda _pid: False,
        **high_resources(),
    )

    assert payload["status"] == "BLOCK"
    assert payload["summary"]["active_loop_count"] == 0
    assert payload["summary"]["degraded_loop_count"] == 1
    blocker = next(row for row in payload["blockers"] if row["code"] == "capture_freshness_degraded")
    assert "heartbeat_stale" in blocker["evidence"]["degraded_reasons"]


def test_missing_capture_status_fails_closed_in_live_window(tmp_path):
    spec = CaptureLoopSpec("snapshot", tmp_path / "missing.json", 600)

    payload = build_capture_resource_gate(
        disk_path=tmp_path,
        loop_specs=(spec,),
        now=NOW,
        process_checker=lambda _pid: False,
        **high_resources(),
    )

    assert payload["status"] == "BLOCK"
    assert payload["loops"][0]["status_artifact"] == "MISSING"
    assert payload["blockers"][0]["code"] == "capture_freshness_degraded"
    assert "status_missing" in payload["blockers"][0]["evidence"]["degraded_reasons"]


def test_outside_window_allows_inactive_stale_loop_as_warning(tmp_path):
    spec = write_loop(
        tmp_path,
        "snapshot",
        pid=404,
        heartbeat=NOW - timedelta(hours=2),
    )

    payload = build_capture_resource_gate(
        disk_path=tmp_path,
        loop_specs=(spec,),
        now=NOW,
        active_window=False,
        process_checker=lambda _pid: False,
        **high_resources(),
    )

    assert payload["status"] == "PASS"
    assert payload["admitted"] is True
    assert payload["blockers"] == []
    assert payload["warnings"][0]["code"] == "capture_freshness_degraded_outside_window"


def test_explicit_offline_host_allows_missing_live_artifacts(tmp_path):
    specs = (
        CaptureLoopSpec("snapshot", tmp_path / "snapshot.json", 600),
        CaptureLoopSpec("clob", tmp_path / "clob.json", 60),
    )

    payload = build_capture_resource_gate(
        capture_mode="offline_host",
        disk_path=tmp_path,
        loop_specs=specs,
        now=NOW,
        process_checker=lambda _pid: False,
        **high_resources(),
    )

    assert payload["status"] == "PASS"
    assert payload["decision"] == "ADMIT"
    assert payload["configuration"]["active_window"] is False
    assert payload["summary"]["degraded_loop_count"] == 2


def test_offline_configuration_blocks_if_live_loop_is_detected(tmp_path):
    spec = write_loop(tmp_path, "snapshot", pid=123)

    payload = build_capture_resource_gate(
        capture_mode="no_live_capture",
        disk_path=tmp_path,
        loop_specs=(spec,),
        now=NOW,
        process_checker=lambda pid: pid == 123,
        **high_resources(),
    )

    assert payload["status"] == "BLOCK"
    assert payload["blockers"][0]["code"] == "capture_mode_conflict_live_loop_detected"


def test_memory_disk_and_growth_reserves_each_fail_closed(tmp_path):
    payload = build_capture_resource_gate(
        capture_mode="offline_host",
        disk_path=tmp_path,
        loop_specs=(),
        now=NOW,
        min_free_memory_bytes=10_000,
        min_free_disk_bytes=20_000,
        daily_disk_growth_bytes=1_000,
        min_disk_headroom_days=30,
        memory_available_fn=lambda: 5_000,
        disk_usage_fn=lambda _path: DiskUsage(total=100_000, used=85_000, free=15_000),
    )

    codes = {row["code"] for row in payload["blockers"]}
    assert payload["status"] == "BLOCK"
    assert codes == {
        "insufficient_free_memory",
        "insufficient_free_disk",
        "insufficient_disk_growth_headroom",
    }
    assert payload["resources"]["disk"]["growth_headroom_days"] == 15.0


def test_unavailable_resource_measurements_fail_closed(tmp_path):
    def unavailable_disk(_path):
        raise OSError("volume unavailable")

    payload = build_capture_resource_gate(
        capture_mode="offline_host",
        disk_path=tmp_path,
        loop_specs=(),
        now=NOW,
        memory_available_fn=lambda: None,
        disk_usage_fn=unavailable_disk,
    )

    assert {row["code"] for row in payload["blockers"]} == {
        "free_memory_unavailable",
        "disk_headroom_unavailable",
    }


def test_configured_overnight_window_and_defer_time_use_window_end(tmp_path):
    spec = write_loop(tmp_path, "snapshot", pid=123)

    payload = build_capture_resource_gate(
        disk_path=tmp_path,
        loop_specs=(spec,),
        now=NOW,
        active_window_start_hour=20,
        active_window_end_hour=6,
        process_checker=lambda pid: pid == 123,
        **high_resources(),
    )

    assert payload["configuration"]["active_window"] is True
    defer = datetime.fromisoformat(payload["summary"]["suggested_defer_until_utc"])
    assert defer > NOW + timedelta(hours=4)


def test_report_and_outputs_are_atomic(tmp_path):
    payload = build_capture_resource_gate(
        capture_mode="offline_host",
        disk_path=tmp_path,
        loop_specs=(),
        now=NOW,
        **high_resources(),
    )
    out = tmp_path / "gate.json"
    report = tmp_path / "gate.md"

    with patch("weather.operations.capture_resource_gate.os.replace", wraps=os.replace) as replace:
        written = write_outputs(payload, out=out, report=report)

    assert written == (out, report)
    assert replace.call_count == 2
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "PASS"
    assert "Capture Resource Admission Gate" in report.read_text(encoding="utf-8")
    assert "never stops" in render_report(payload)


def test_pipeline_admission_persists_enforcement_receipt(tmp_path):
    out = tmp_path / "gate.json"
    report = tmp_path / "gate.md"

    payload, out_path, report_path = persist_pipeline_admission(
        workload=DAILY_REFRESH_WORKLOAD,
        out=out,
        report=report,
        capture_mode="offline_host",
        disk_path=tmp_path,
        loop_specs=(),
        now=NOW,
        **high_resources(),
    )

    assert payload["status"] == "PASS"
    assert payload["decision"] == "ADMIT"
    assert payload["enforcement"] == {
        "status": "PASS",
        "consumer": DAILY_REFRESH_WORKLOAD,
        "evaluated_before_heavy_work": True,
        "heavy_child_started_before_decision": False,
        "outcome": "ADMITTED_BEFORE_HEAVY_WORK",
        "proof_persisted": True,
        "json_path": str(out),
        "report_path": str(report),
    }
    assert (out_path, report_path) == (out, report)
    assert json.loads(out.read_text(encoding="utf-8"))["enforcement"]["status"] == "PASS"


def test_pipeline_admission_defers_if_proof_cannot_persist(tmp_path):
    def failed_writer(*_args, **_kwargs):
        raise OSError("read only evidence volume")

    payload, out_path, report_path = persist_pipeline_admission(
        workload=DAILY_REFRESH_WORKLOAD,
        out=tmp_path / "gate.json",
        report=tmp_path / "gate.md",
        capture_mode="offline_host",
        disk_path=tmp_path,
        loop_specs=(),
        now=NOW,
        output_writer=failed_writer,
        **high_resources(),
    )

    assert payload["status"] == "BLOCK"
    assert payload["admitted"] is False
    assert payload["decision"] == "DEFER"
    assert payload["enforcement"]["proof_persisted"] is False
    assert payload["enforcement"]["status"] == "BLOCK"
    assert payload["blockers"][-1]["code"] == "admission_proof_persistence_failed"
    assert out_path is report_path is None
    assert json.loads((tmp_path / "gate.json").read_text(encoding="utf-8"))[
        "enforcement"
    ]["status"] == "BLOCK"


def test_cli_no_write_is_a_true_read_only_audit(tmp_path):
    out = tmp_path / "gate.json"
    report = tmp_path / "gate.md"

    payload = main([
        "--capture-mode",
        "offline_host",
        "--snapshots-root",
        str(tmp_path / "missing-snapshots"),
        "--disk-path",
        str(tmp_path),
        "--min-free-memory-bytes",
        "0",
        "--min-free-disk-bytes",
        "0",
        "--out",
        str(out),
        "--report",
        str(report),
        "--no-write",
    ])

    assert payload["configuration"]["capture_mode"] == "offline_host"
    assert not out.exists()
    assert not report.exists()
