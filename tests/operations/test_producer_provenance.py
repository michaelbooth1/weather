import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from weather.operations.daily_refresh_locks import acquire_lock, release_lock
from weather.operations.long_job_guard import acquire_long_job_lock, release_long_job_lock
from weather.operations.producer_provenance import (
    STATUS_BOUND,
    _windows_argv,
    attest_scheduled_invocation,
    build_invocation_proof,
    build_lock_proof,
    build_stage_sla,
    verified_active_release_proof,
)


NOW = datetime(2026, 7, 12, 6, 30, tzinfo=timezone.utc)


def test_windows_task_arguments_use_native_command_line_parsing():
    if os.name != "nt":
        return
    assert _windows_argv(
        r'-m weather.operations.daily_refresh run --repo-root "C:\Program Files\weather"'
    ) == [
        "-m",
        "weather.operations.daily_refresh",
        "run",
        "--repo-root",
        r"C:\Program Files\weather",
    ]


def task_payload(executable, arguments, working_directory, **overrides):
    payload = {
        "task_name": "WeatherProducer",
        "task_path": "\\",
        "state": "Running",
        "enabled": True,
        "actions": [{
            "execute": str(executable),
            "arguments": "registered arguments",
            "working_directory": str(working_directory),
        }],
        "last_run_time_utc": (NOW - timedelta(seconds=4)).isoformat(),
        "last_task_result": 0x00041301,
        "definition_xml": "<Task><Actions /></Task>",
    }
    payload.update(overrides)
    return payload


def test_windows_scheduler_attestation_requires_exact_running_contract(tmp_path):
    executable = tmp_path / "venv" / "Scripts" / "pythonw.exe"
    workdir = tmp_path / "repo"
    expected_arguments = ["-m", "weather.operations.nightly_retrain", "run"]
    payload = task_payload(executable, expected_arguments, workdir)

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=executable,
        expected_arguments=expected_arguments,
        expected_working_directory=workdir,
        invocation_started_at_utc=NOW,
        process_executable=executable,
        process_working_directory=workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: expected_arguments,
    )

    assert proof["status"] == "PASS"
    assert proof["scheduler_attested"] is True
    assert proof["task_enabled"] is True
    assert proof["task_state"] == "Running"
    assert proof["contract"]["status"] == "PASS"
    assert len(proof["task_definition_sha256"]) == 64
    assert len(proof["contract"]["contract_sha256"]) == 64
    assert proof["task_run_correlation"]["status"] == "PASS"
    assert proof["task_run_correlation"]["process_start_delta_seconds"] == 4.0


def test_scheduler_attestation_blocks_disabled_stale_or_action_mismatch(tmp_path):
    expected_executable = tmp_path / "pythonw.exe"
    registered_executable = tmp_path / "wrong.exe"
    expected_workdir = tmp_path / "repo"
    payload = task_payload(
        registered_executable,
        [],
        tmp_path / "wrong-repo",
        state="Disabled",
        enabled=False,
        last_run_time_utc=(NOW - timedelta(hours=2)).isoformat(),
    )

    proof = attest_scheduled_invocation(
        task_name="WeatherProducer",
        expected_executable=expected_executable,
        expected_arguments=["-m", "weather.operations.daily_refresh", "run"],
        expected_working_directory=expected_workdir,
        invocation_started_at_utc=NOW,
        process_executable=expected_executable,
        process_working_directory=expected_workdir,
        os_name="nt",
        task_query=lambda _name: payload,
        argument_parser=lambda _arguments: ["-m", "wrong.module", "run"],
    )

    codes = {row["code"] for row in proof["blockers"]}
    assert proof["status"] == "BLOCK"
    assert proof["scheduler_attested"] is False
    assert {
        "scheduler_task_disabled",
        "scheduler_task_not_running",
        "scheduler_executable_mismatch",
        "scheduler_working_directory_mismatch",
        "scheduler_arguments_mismatch",
        "scheduler_run_correlation_stale",
    }.issubset(codes)


def test_manual_or_non_windows_label_cannot_spoof_scheduled_invocation():
    args = SimpleNamespace(
        scheduler_task_name="WeatherProducer",
        scheduler_task_executable="pythonw.exe",
        scheduler_task_working_directory="repo",
        scheduler_correlation_seconds=120,
        dry_run=False,
        resume_from_step="",
        force_lock=False,
        force_long_job_lock=False,
        disable_long_job_guard=False,
    )

    proof = build_invocation_proof(
        args,
        module_name="weather.operations.daily_refresh",
        invocation_started_at_utc=NOW,
        argv=["run"],
        os_name="posix",
    )

    assert proof["status"] == "BLOCK"
    assert proof["mode"] == "manual_or_unverified"
    assert proof["scheduler_attested"] is False
    assert proof["manual_intervention"] is True


def test_instrumented_daily_and_long_job_locks_report_stale_and_force_exactly(tmp_path):
    daily_path = tmp_path / "daily.lock"
    daily_path.write_text(json.dumps({"pid": -999}), encoding="utf-8")
    daily_audit = {}
    daily_lock = acquire_lock(daily_path, audit=daily_audit)
    release_lock(daily_lock)

    long_path = tmp_path / "long.lock"
    long_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")
    forced_audit = {}
    long_lock = acquire_long_job_lock(long_path, "test", force=True, audit=forced_audit)
    release_long_job_lock(long_lock)

    proof = build_lock_proof(daily_audit, forced_audit)
    assert daily_audit["stale_lock_detected_count"] == 1
    assert daily_audit["stale_lock_repair_count"] == 1
    assert forced_audit["forced_lock_acquisition_count"] == 1
    assert forced_audit["forced_lock_repair_count"] == 1
    assert proof["status"] == "BLOCK"
    assert proof["stale_lock_count"] == 1
    assert proof["forced_lock_acquisition_count"] == 1


def test_predeclared_stage_sla_is_exact_and_breaches_fail_closed():
    passed = build_stage_sla(duration_seconds=59, limit_seconds=60)
    breached = build_stage_sla(duration_seconds=61, limit_seconds=60)
    missing = build_stage_sla(duration_seconds=1, limit_seconds=0)

    assert passed["status"] == "PASS"
    assert breached["status"] == "BLOCK"
    assert breached["breach_seconds"] == 1.0
    assert missing["status"] == "BLOCK"
    assert missing["predeclared"] is False


def test_release_identity_only_emits_after_verified_serving_binding(tmp_path):
    bound = SimpleNamespace(
        status=STATUS_BOUND,
        reason="verified",
        release_id="release-1",
        manifest_sha256="a" * 64,
        pointer_sha256="b" * 64,
        sequence=3,
        artifact_paths={"pooled_band_model": str(tmp_path / "model.pkl")},
    )
    unbound = SimpleNamespace(
        status="RESEARCH_UNBOUND",
        reason="missing pointer",
        release_id="legacy-should-not-leak",
        manifest_sha256="c" * 64,
        pointer_sha256="",
        sequence=None,
        artifact_paths={},
    )

    passed = verified_active_release_proof(
        pointer_path=tmp_path / "pointer.json",
        releases_root=tmp_path,
        bundle_provider=lambda **_kwargs: bound,
    )
    blocked = verified_active_release_proof(
        pointer_path=tmp_path / "missing.json",
        releases_root=tmp_path,
        bundle_provider=lambda **_kwargs: unbound,
    )

    assert passed["status"] == "PASS"
    assert passed["served_bindings_verified"] is True
    assert passed["release_id"] == "release-1"
    assert blocked["status"] == "BLOCK"
    assert blocked["release_id"] == ""
    assert blocked["release_manifest_sha256"] == ""


def test_scheduler_registration_scripts_declare_producer_contracts():
    repo_root = Path(__file__).resolve().parents[2]
    scripts = {
        "daily": (repo_root / "scripts" / "ops" / "register_daily_refresh.ps1").read_text(
            encoding="utf-8"
        ),
        "nightly": (repo_root / "scripts" / "ops" / "register_nightly_retrain.ps1").read_text(
            encoding="utf-8"
        ),
    }
    required_flags = (
        "--scheduler-task-name",
        "--scheduler-task-executable",
        "--scheduler-task-working-directory",
        "--producer-sla-seconds",
        "--releases-root",
        "--repo-root",
        "--captured-input-parity-served",
        "--captured-input-parity-replay",
        "--production-readiness-served-artifact",
        "--production-readiness-served-route",
        "--fail-on-production-readiness-block",
    )
    for script in scripts.values():
        for flag in required_flags:
            assert flag in script
    assert "--active-release-pointer" in scripts["daily"]
    assert "--release-pointer" in scripts["nightly"]
    for script in scripts.values():
        assert "Parameter(Mandatory = $true)" in script
        assert "Resolve-RequiredFile" in script
