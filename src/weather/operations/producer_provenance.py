"""Fail-closed producer provenance for countable production evidence.

Labels such as ``mode=scheduled`` are not evidence.  This module verifies the
live Windows Task Scheduler definition and running state, correlates its last
run with this process start, and records exact lock/SLA/release-binding proofs.
Non-Windows, manual, dry, resumed, disabled, or unverifiable runs remain
explicitly non-countable.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.release_artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_RELEASES_ROOT,
)
from weather.release_serving import STATUS_BOUND, get_process_active_serving_bundle


TASK_RUNNING_RESULT = 0x00041301
DEFAULT_CORRELATION_SECONDS = 120.0


def _utc(value: datetime | str | None) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | str | None) -> str | None:
    parsed = _utc(value)
    return parsed.isoformat() if parsed else None


def _path_key(value: str | Path | None) -> str:
    if not value:
        return ""
    return os.path.normcase(str(Path(value).expanduser().resolve(strict=False)))


def _windows_argv(arguments: str) -> list[str]:
    """Parse a Task Scheduler action argument string with Windows semantics."""

    command = f"dummy.exe {arguments or ''}"
    argc = ctypes.c_int()
    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32
    shell32.CommandLineToArgvW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_int),
    )
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    parsed = shell32.CommandLineToArgvW(command, ctypes.byref(argc))
    if not parsed:
        raise OSError("CommandLineToArgvW failed")
    try:
        return [parsed[index] for index in range(1, argc.value)]
    finally:
        kernel32.LocalFree(parsed)


def query_windows_task(task_name: str, *, timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Read one exact scheduled task and its OS-maintained run information."""

    script = r"""
$ErrorActionPreference = 'Stop'
$matches = @(Get-ScheduledTask -TaskName $env:WEATHER_PRODUCER_TASK_NAME -ErrorAction Stop)
if ($matches.Count -ne 1) { throw "expected exactly one task, found $($matches.Count)" }
$task = $matches[0]
$info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction Stop
$xml = Export-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction Stop
$actions = @($task.Actions | ForEach-Object {
  [pscustomobject]@{
    execute = [string]$_.Execute
    arguments = [string]$_.Arguments
    working_directory = [string]$_.WorkingDirectory
  }
})
[pscustomobject]@{
  task_name = [string]$task.TaskName
  task_path = [string]$task.TaskPath
  state = [string]$task.State
  enabled = [bool]($task.State -ne 'Disabled' -and $task.Settings.Enabled)
  actions = $actions
  last_run_time_utc = if ($info.LastRunTime.Year -gt 1900) { $info.LastRunTime.ToUniversalTime().ToString('o') } else { $null }
  last_task_result = [int64]$info.LastTaskResult
  definition_xml = [string]$xml
} | ConvertTo-Json -Depth 8 -Compress
"""
    env = os.environ.copy()
    env["WEATHER_PRODUCER_TASK_NAME"] = str(task_name)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=float(timeout_seconds),
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "task query failed").strip())
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("scheduled-task query root must be an object")
    return payload


def attest_scheduled_invocation(
    *,
    task_name: str,
    expected_executable: str | Path,
    expected_arguments: Sequence[str],
    expected_working_directory: str | Path,
    invocation_started_at_utc: datetime | str,
    process_executable: str | Path | None = None,
    process_working_directory: str | Path | None = None,
    correlation_seconds: float = DEFAULT_CORRELATION_SECONDS,
    os_name: str | None = None,
    task_query=None,
    argument_parser=None,
) -> dict[str, Any]:
    """Verify definition + current running task + fresh run/start correlation."""

    platform_name = os.name if os_name is None else os_name
    observed_at = datetime.now(timezone.utc)
    started_at = _utc(invocation_started_at_utc)
    blockers: list[dict[str, Any]] = []
    if platform_name != "nt":
        blockers.append({
            "code": "scheduler_attestation_non_windows",
            "detail": "Windows Task Scheduler attestation is unavailable",
        })
        return {
            "status": "BLOCK",
            "scheduler_attested": False,
            "task_name": str(task_name or ""),
            "observed_at_utc": observed_at.isoformat(),
            "blockers": blockers,
        }
    if not task_name or not expected_executable or not expected_working_directory:
        blockers.append({
            "code": "scheduler_contract_missing",
            "detail": "task name, executable, and working directory are required",
        })
        return {
            "status": "BLOCK",
            "scheduler_attested": False,
            "task_name": str(task_name or ""),
            "observed_at_utc": observed_at.isoformat(),
            "blockers": blockers,
        }
    query = task_query or query_windows_task
    try:
        task = query(str(task_name))
    except Exception as exc:  # noqa: BLE001 - evidence must fail closed
        blockers.append({
            "code": "scheduler_query_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        })
        return {
            "status": "BLOCK",
            "scheduler_attested": False,
            "task_name": str(task_name),
            "observed_at_utc": observed_at.isoformat(),
            "blockers": blockers,
        }

    actions = task.get("actions")
    if isinstance(actions, Mapping):
        actions = [actions]
    actions = actions if isinstance(actions, list) else []
    action = actions[0] if len(actions) == 1 and isinstance(actions[0], Mapping) else {}
    if len(actions) != 1:
        blockers.append({"code": "scheduler_action_count_mismatch", "actual": len(actions), "expected": 1})

    parser = argument_parser or _windows_argv
    try:
        registered_arguments = parser(str(action.get("arguments") or ""))
    except Exception as exc:  # noqa: BLE001
        registered_arguments = []
        blockers.append({
            "code": "scheduler_arguments_unparseable",
            "detail": f"{type(exc).__name__}: {exc}",
        })
    expected_arguments = [str(value) for value in expected_arguments]
    if registered_arguments != expected_arguments:
        blockers.append({
            "code": "scheduler_arguments_mismatch",
            "actual": registered_arguments,
            "expected": expected_arguments,
        })
    registered_executable = _path_key(action.get("execute"))
    expected_executable_key = _path_key(expected_executable)
    actual_process_executable = _path_key(process_executable or sys.executable)
    if registered_executable != expected_executable_key:
        blockers.append({
            "code": "scheduler_executable_mismatch",
            "actual": registered_executable,
            "expected": expected_executable_key,
        })
    if actual_process_executable != expected_executable_key:
        blockers.append({
            "code": "running_executable_mismatch",
            "actual": actual_process_executable,
            "expected": expected_executable_key,
        })
    registered_workdir = _path_key(action.get("working_directory"))
    expected_workdir = _path_key(expected_working_directory)
    actual_workdir = _path_key(process_working_directory or Path.cwd())
    if registered_workdir != expected_workdir:
        blockers.append({
            "code": "scheduler_working_directory_mismatch",
            "actual": registered_workdir,
            "expected": expected_workdir,
        })
    if actual_workdir != expected_workdir:
        blockers.append({
            "code": "running_working_directory_mismatch",
            "actual": actual_workdir,
            "expected": expected_workdir,
        })
    if str(task.get("task_name") or "").casefold() != str(task_name).casefold():
        blockers.append({
            "code": "scheduler_task_name_mismatch",
            "actual": task.get("task_name"),
            "expected": task_name,
        })
    if task.get("enabled") is not True or str(task.get("state") or "").casefold() == "disabled":
        blockers.append({"code": "scheduler_task_disabled", "actual": task.get("state")})
    if str(task.get("state") or "").casefold() != "running":
        blockers.append({"code": "scheduler_task_not_running", "actual": task.get("state")})

    last_run = _utc(task.get("last_run_time_utc"))
    delta_seconds = None
    if started_at is None or last_run is None:
        blockers.append({
            "code": "scheduler_run_correlation_missing",
            "actual": task.get("last_run_time_utc"),
        })
    else:
        delta_seconds = (started_at - last_run).total_seconds()
        if delta_seconds < -5.0 or delta_seconds > float(correlation_seconds):
            blockers.append({
                "code": "scheduler_run_correlation_stale",
                "actual_seconds": round(delta_seconds, 3),
                "expected": f"-5..{float(correlation_seconds):.1f}",
            })

    definition_xml = str(task.get("definition_xml") or "")
    definition_sha256 = (
        hashlib.sha256(definition_xml.encode("utf-8")).hexdigest()
        if definition_xml
        else ""
    )
    if not definition_sha256:
        blockers.append({"code": "scheduler_definition_missing"})
    correlation_status = "PASS" if not any(
        row["code"].startswith("scheduler_run_correlation")
        or row["code"] == "scheduler_task_not_running"
        for row in blockers
    ) else "BLOCK"
    contract = {
        "task_name": str(task_name),
        "executable": expected_executable_key,
        "arguments": expected_arguments,
        "working_directory": expected_workdir,
        "task_definition_sha256": definition_sha256,
    }
    contract["contract_sha256"] = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    status = "PASS" if not blockers else "BLOCK"
    return {
        "status": status,
        "scheduler_attested": status == "PASS",
        "task_name": str(task_name),
        "task_path": task.get("task_path"),
        "task_state": task.get("state"),
        "task_enabled": task.get("enabled") is True,
        "last_task_result": task.get("last_task_result"),
        "observed_at_utc": observed_at.isoformat(),
        "invocation_started_at_utc": _iso(started_at),
        "task_definition_sha256": definition_sha256,
        "contract": {**contract, "status": "PASS" if not any(
            row["code"] in {
                "scheduler_action_count_mismatch",
                "scheduler_arguments_unparseable",
                "scheduler_arguments_mismatch",
                "scheduler_executable_mismatch",
                "running_executable_mismatch",
                "scheduler_working_directory_mismatch",
                "running_working_directory_mismatch",
                "scheduler_task_name_mismatch",
                "scheduler_task_disabled",
                "scheduler_definition_missing",
            }
            for row in blockers
        ) else "BLOCK"},
        "task_run_correlation": {
            "status": correlation_status,
            "last_run_time_utc": _iso(last_run),
            "process_start_delta_seconds": (
                round(delta_seconds, 3) if delta_seconds is not None else None
            ),
            "max_delta_seconds": float(correlation_seconds),
            "task_running_result_code": TASK_RUNNING_RESULT,
        },
        "blockers": blockers,
    }


def build_invocation_proof(
    args,
    *,
    module_name: str,
    invocation_started_at_utc: datetime | str,
    argv: Sequence[str] | None = None,
    task_query=None,
    os_name: str | None = None,
) -> dict[str, Any]:
    injected = getattr(args, "_producer_invocation", None)
    if isinstance(injected, Mapping):
        return dict(injected)
    task_name = str(getattr(args, "scheduler_task_name", "") or "")
    expected_executable = str(getattr(args, "scheduler_task_executable", "") or "")
    expected_workdir = str(
        getattr(args, "scheduler_task_working_directory", "") or ""
    )
    correlation_seconds = float(
        getattr(args, "scheduler_correlation_seconds", DEFAULT_CORRELATION_SECONDS)
    )
    if task_name and expected_executable and expected_workdir:
        running_argv = list(argv if argv is not None else sys.argv[1:])
        attestation = attest_scheduled_invocation(
            task_name=task_name,
            expected_executable=expected_executable,
            expected_arguments=["-m", module_name, *running_argv],
            expected_working_directory=expected_workdir,
            invocation_started_at_utc=invocation_started_at_utc,
            correlation_seconds=correlation_seconds,
            task_query=task_query,
            os_name=os_name,
        )
    else:
        attestation = {
            "status": "BLOCK",
            "scheduler_attested": False,
            "task_name": task_name,
            "task_definition_sha256": "",
            "contract": {"status": "BLOCK"},
            "task_run_correlation": {"status": "BLOCK"},
            "blockers": [{
                "code": "scheduler_contract_missing",
                "detail": "registration must pass task name/executable/working directory",
            }],
        }
    resume_from = str(getattr(args, "resume_from_step", "") or "")
    prior_repair = getattr(args, "_prior_lock_repair_outcomes", None)
    reasons = []
    if attestation.get("status") != "PASS":
        reasons.append("scheduler_not_attested")
    if getattr(args, "dry_run", False):
        reasons.append("dry_run")
    if resume_from:
        reasons.append("resumed")
    if getattr(args, "force_lock", False) or getattr(args, "force_long_job_lock", False):
        reasons.append("forced_lock")
    if prior_repair:
        reasons.append("lock_repair_command")
    if getattr(args, "disable_long_job_guard", False):
        reasons.append("long_job_guard_disabled")
    return {
        **attestation,
        "mode": "scheduled" if attestation.get("status") == "PASS" else "manual_or_unverified",
        "manual_intervention": bool(reasons),
        "manual_intervention_reasons": reasons,
        "resume_from_step": resume_from,
        "resumed": bool(resume_from),
        "dry_run": bool(getattr(args, "dry_run", False)),
    }


def build_stage_sla(*, duration_seconds: Any, limit_seconds: Any) -> dict[str, Any]:
    try:
        duration = float(duration_seconds)
        limit = float(limit_seconds)
    except (TypeError, ValueError):
        duration = limit = -1.0
    predeclared = limit > 0
    status = "PASS" if predeclared and duration >= 0 and duration <= limit else "BLOCK"
    return {
        "status": status,
        "predeclared": predeclared,
        "duration_seconds": round(duration, 3) if duration >= 0 else None,
        "limit_seconds": round(limit, 3) if predeclared else None,
        "breach_seconds": (
            round(max(0.0, duration - limit), 3)
            if duration >= 0 and predeclared
            else None
        ),
    }


def build_lock_proof(
    *outcomes: Mapping[str, Any] | None,
    prior_repair: Mapping[str, Any] | None = None,
    required_kinds: Sequence[str] = (),
) -> dict[str, Any]:
    rows = [dict(row) for row in outcomes if isinstance(row, Mapping)]
    observed_kinds = {str(row.get("kind") or "") for row in rows}
    missing_kinds = sorted(set(required_kinds) - observed_kinds)
    instrumented = bool(rows) and not missing_kinds and all(
        row.get("instrumented") is True for row in rows
    )
    stale_detected = sum(int(row.get("stale_lock_detected_count") or 0) for row in rows)
    stale_repaired = sum(int(row.get("stale_lock_repair_count") or 0) for row in rows)
    forced_acquisitions = sum(int(row.get("forced_lock_acquisition_count") or 0) for row in rows)
    forced_repairs = sum(int(row.get("forced_lock_repair_count") or 0) for row in rows)
    guard_disabled = any(row.get("guard_enabled") is False for row in rows)
    nested = any(row.get("nested") is True for row in rows)
    if isinstance(prior_repair, Mapping):
        stale_detected += int(prior_repair.get("verified_stale_lock_count") or 0)
        stale_repaired += int(prior_repair.get("removed_lock_count") or 0)
    status = "PASS" if (
        instrumented
        and not guard_disabled
        and not nested
        and stale_detected == 0
        and stale_repaired == 0
        and forced_acquisitions == 0
        and forced_repairs == 0
    ) else "BLOCK"
    return {
        "status": status,
        "instrumented": instrumented,
        "guard_disabled": guard_disabled,
        "nested_guard": nested,
        "required_kinds": list(required_kinds),
        "observed_kinds": sorted(observed_kinds),
        "missing_kinds": missing_kinds,
        "stale_lock_count": stale_detected,
        "stale_lock_repair_count": stale_repaired,
        "forced_lock_acquisition_count": forced_acquisitions,
        "forced_lock_repair_count": forced_repairs,
        "outcomes": rows,
        "prior_repair": dict(prior_repair) if isinstance(prior_repair, Mapping) else None,
    }


def verified_active_release_proof(
    *,
    pointer_path: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    repo_root: str | Path | None = None,
    bundle_provider=get_process_active_serving_bundle,
) -> dict[str, Any]:
    try:
        kwargs = {
            "pointer_path": pointer_path,
            "releases_root": releases_root,
        }
        if repo_root is not None:
            kwargs["repo_root"] = repo_root
        bundle = bundle_provider(**kwargs)
    except Exception as exc:  # noqa: BLE001 - provenance must fail closed
        return {
            "status": "BLOCK",
            "served_bindings_verified": False,
            "release_id": "",
            "release_manifest_sha256": "",
            "reason": f"{type(exc).__name__}: {exc}",
        }
    if bundle.status != STATUS_BOUND or not bundle.release_id or not bundle.manifest_sha256:
        return {
            "status": "BLOCK",
            "served_bindings_verified": False,
            "release_id": "",
            "release_manifest_sha256": "",
            "release_pointer_sha256": "",
            "release_sequence": None,
            "reason": bundle.reason,
            "binding_status": bundle.status,
        }
    return {
        "status": "PASS",
        "served_bindings_verified": True,
        "release_id": bundle.release_id,
        "release_manifest_sha256": bundle.manifest_sha256,
        "release_pointer_sha256": bundle.pointer_sha256,
        "release_sequence": bundle.sequence,
        "served_artifact_roles": sorted(bundle.artifact_paths),
        "reason": bundle.reason,
        "binding_status": bundle.status,
    }


def producer_release_proof(args) -> dict[str, Any]:
    injected = getattr(args, "_producer_release_identity", None)
    if isinstance(injected, Mapping):
        return dict(injected)
    pointer = (
        getattr(args, "active_release_pointer", None)
        or getattr(args, "release_pointer", None)
        or DEFAULT_ACTIVE_RELEASE_POINTER
    )
    releases_root = getattr(args, "releases_root", None) or DEFAULT_RELEASES_ROOT
    repo_root = getattr(args, "repo_root", None)
    return verified_active_release_proof(
        pointer_path=pointer,
        releases_root=releases_root,
        repo_root=repo_root,
    )
