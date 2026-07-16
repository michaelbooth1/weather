"""Fail-closed producer provenance for countable production evidence.

Labels such as ``mode=scheduled`` are not evidence.  This module verifies the
live Windows Task Scheduler definition and running state, correlates its last
run with this process start, and binds either a direct producer or a delegated
child to its exact scheduler action and process command. It also records exact
lock/SLA/release-binding proofs.
Non-Windows, manual, dry, resumed, disabled, or unverifiable runs remain
explicitly non-countable.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import json
import math
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
MAX_PROCESS_ANCESTORS = 2
PROCESS_START_CORRELATION_SECONDS = 120.0
PROCESS_START_EARLY_TOLERANCE_SECONDS = 5.0
TASK_ENGINE_START_CORRELATION_SECONDS = 30.0
VENV_REDIRECTOR_START_CORRELATION_SECONDS = 30.0
SCHEDULER_INVOCATION_TOPOLOGIES = frozenset({"direct", "delegated_child"})


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


def _int_or_default(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _windows_argv(arguments: str) -> list[str]:
    """Parse a Task Scheduler action argument string with Windows semantics."""

    return _windows_command_line_argv(f"dummy.exe {arguments or ''}")[1:]


def _windows_command_line_argv(command: str) -> list[str]:
    """Parse one complete Windows command line with native semantics."""

    if not command:
        raise ValueError("Windows command line is required")
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
        return [parsed[index] for index in range(argc.value)]
    finally:
        kernel32.LocalFree(parsed)


def decode_scheduler_action_arguments(value: str) -> list[str]:
    """Decode a bounded UTF-8/JSON task-action argument contract."""

    if not value:
        raise ValueError("scheduler task action argument contract is required")
    try:
        raw = base64.b64decode(str(value), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("scheduler task action argument contract is not valid base64") from exc
    if len(raw) > 64 * 1024:
        raise ValueError("scheduler task action argument contract exceeds 64 KiB")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("scheduler task action argument contract is not UTF-8 JSON") from exc
    if (
        not isinstance(payload, list)
        or not payload
        or len(payload) > 256
        or any(not isinstance(item, str) for item in payload)
    ):
        raise ValueError("scheduler task action argument contract must be 1..256 strings")
    return payload


def query_windows_task(task_name: str, *, timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Read one exact scheduled task and its OS-maintained run information."""

    script = r"""
$ErrorActionPreference = 'Stop'
$matches = @(Get-ScheduledTask -TaskName $env:WEATHER_PRODUCER_TASK_NAME -ErrorAction Stop)
if ($matches.Count -ne 1) { throw "expected exactly one task, found $($matches.Count)" }
$task = $matches[0]
$info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction Stop
$xml = Export-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction Stop
$scheduler = New-Object -ComObject 'Schedule.Service'
$scheduler.Connect()
$folderPath = [string]$task.TaskPath
if ($folderPath.Length -gt 1) { $folderPath = $folderPath.TrimEnd('\') }
$registeredTask = $scheduler.GetFolder($folderPath).GetTask([string]$task.TaskName)
$runningInstances = @($registeredTask.GetInstances(0) | ForEach-Object {
  [pscustomobject]@{
    engine_process_id = [int64]$_.EnginePID
    instance_guid = [string]$_.InstanceGuid
    state = [int]$_.State
    current_action = [string]$_.CurrentAction
  }
})
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
  running_instances = $runningInstances
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


def query_windows_process_lineage(
    process_id: int,
    *,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """Observe the current process and its bounded Windows ancestor chain."""

    script = r"""
$ErrorActionPreference = 'Stop'
$targetId = [int64]$env:WEATHER_PRODUCER_PROCESS_ID
$processRows = @(Get-CimInstance Win32_Process -Filter "ProcessId = $targetId" -ErrorAction Stop)
if ($processRows.Count -ne 1) { throw "expected one producer process, found $($processRows.Count)" }
$process = $processRows[0]
$ancestors = @()
$nextId = [int64]$process.ParentProcessId
for ($depth = 0; $depth -lt 2 -and $nextId -gt 0; $depth++) {
  $rows = @(Get-CimInstance Win32_Process -Filter "ProcessId = $nextId" -ErrorAction Stop)
  if ($rows.Count -ne 1) {
    if ($depth -eq 0) { throw "expected one parent process $nextId, found $($rows.Count)" }
    break
  }
  $row = $rows[0]
  $ancestors += [pscustomobject]@{
    process_id = [int64]$row.ProcessId
    parent_process_id = [int64]$row.ParentProcessId
    executable = [string]$row.ExecutablePath
    command_line = [string]$row.CommandLine
    created_at_utc = if ($row.CreationDate) { $row.CreationDate.ToUniversalTime().ToString('o') } else { $null }
  }
  $nextId = [int64]$row.ParentProcessId
}
[pscustomobject]@{
  process = [pscustomobject]@{
    process_id = [int64]$process.ProcessId
    parent_process_id = [int64]$process.ParentProcessId
    executable = [string]$process.ExecutablePath
    command_line = [string]$process.CommandLine
    created_at_utc = if ($process.CreationDate) { $process.CreationDate.ToUniversalTime().ToString('o') } else { $null }
  }
  ancestors = $ancestors
} | ConvertTo-Json -Depth 6 -Compress
"""
    env = os.environ.copy()
    env["WEATHER_PRODUCER_PROCESS_ID"] = str(int(process_id))
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=float(timeout_seconds),
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout or "process-lineage query failed").strip()
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("process-lineage query root must be an object")
    return payload


def attest_scheduled_invocation(
    *,
    task_name: str,
    expected_executable: str | Path,
    expected_arguments: Sequence[str],
    expected_working_directory: str | Path,
    invocation_started_at_utc: datetime | str,
    invocation_topology: str = "direct",
    expected_process_executable: str | Path | None = None,
    expected_process_arguments: Sequence[str] | None = None,
    process_executable: str | Path | None = None,
    process_working_directory: str | Path | None = None,
    correlation_seconds: float = DEFAULT_CORRELATION_SECONDS,
    os_name: str | None = None,
    task_query=None,
    argument_parser=None,
    process_query=None,
    process_argument_parser=None,
    process_id: int | None = None,
    process_image_executable: str | Path | None = None,
) -> dict[str, Any]:
    """Verify definition + current running task + fresh run/start correlation."""

    platform_name = os.name if os_name is None else os_name
    topology = str(invocation_topology or "").strip()
    observed_at = datetime.now(timezone.utc)
    started_at = _utc(invocation_started_at_utc)
    blockers: list[dict[str, Any]] = []
    try:
        correlation_limit = float(correlation_seconds)
    except (TypeError, ValueError):
        correlation_limit = DEFAULT_CORRELATION_SECONDS
        blockers.append({
            "code": "scheduler_correlation_contract_invalid",
            "actual": repr(correlation_seconds),
        })
    else:
        if not math.isfinite(correlation_limit) or correlation_limit <= 0:
            blockers.append({
                "code": "scheduler_correlation_contract_invalid",
                "actual": repr(correlation_seconds),
            })
            correlation_limit = DEFAULT_CORRELATION_SECONDS
    if topology not in SCHEDULER_INVOCATION_TOPOLOGIES:
        blockers.append({
            "code": "scheduler_invocation_topology_invalid",
            "actual": topology,
            "expected": sorted(SCHEDULER_INVOCATION_TOPOLOGIES),
        })
    if topology == "delegated_child" and not expected_process_executable:
        blockers.append({
            "code": "scheduler_process_contract_missing",
            "detail": "delegated_child requires the expected child executable",
        })
    if topology == "delegated_child" and expected_process_arguments is None:
        blockers.append({
            "code": "scheduler_process_contract_missing",
            "detail": "delegated_child requires the expected child arguments",
        })
    if (
        topology == "direct"
        and expected_process_executable
        and _path_key(expected_process_executable) != _path_key(expected_executable)
    ):
        blockers.append({
            "code": "scheduler_direct_process_executable_mismatch",
            "actual": _path_key(expected_process_executable),
            "expected": _path_key(expected_executable),
        })
    if platform_name != "nt":
        blockers.append({
            "code": "scheduler_attestation_non_windows",
            "detail": "Windows Task Scheduler attestation is unavailable",
        })
        return {
            "status": "BLOCK",
            "scheduler_attested": False,
            "invocation_topology": topology,
            "task_name": str(task_name or ""),
            "observed_at_utc": observed_at.isoformat(),
            "process_lineage": {"status": "BLOCK"},
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
            "invocation_topology": topology,
            "task_name": str(task_name or ""),
            "observed_at_utc": observed_at.isoformat(),
            "process_lineage": {"status": "BLOCK"},
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
            "invocation_topology": topology,
            "task_name": str(task_name),
            "observed_at_utc": observed_at.isoformat(),
            "process_lineage": {"status": "BLOCK"},
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
    process_arguments = [
        str(value)
        for value in (
            expected_arguments
            if expected_process_arguments is None
            else expected_process_arguments
        )
    ]
    if topology == "direct" and process_arguments != expected_arguments:
        blockers.append({
            "code": "scheduler_direct_process_arguments_mismatch",
            "actual": process_arguments,
            "expected": expected_arguments,
        })

    current_process_id = int(os.getpid() if process_id is None else process_id)
    lineage_query = process_query or query_windows_process_lineage
    try:
        lineage = lineage_query(current_process_id)
    except Exception as exc:  # noqa: BLE001 - provenance must fail closed
        lineage = {}
        blockers.append({
            "code": "scheduler_process_lineage_query_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        })
    observed_process = (
        lineage.get("process") if isinstance(lineage, Mapping) else None
    )
    raw_observed_ancestors = (
        lineage.get("ancestors") if isinstance(lineage, Mapping) else None
    )
    if lineage and (
        not isinstance(observed_process, Mapping)
        or not isinstance(raw_observed_ancestors, list)
        or any(not isinstance(row, Mapping) for row in raw_observed_ancestors)
    ):
        blockers.append({
            "code": "scheduler_process_lineage_invalid",
            "detail": "process lineage must contain one process and an ancestor list",
        })
    observed_process = (
        observed_process if isinstance(observed_process, Mapping) else {}
    )
    observed_ancestors = (
        [row for row in raw_observed_ancestors if isinstance(row, Mapping)]
        if isinstance(raw_observed_ancestors, list) else []
    )
    if len(observed_ancestors) > MAX_PROCESS_ANCESTORS:
        blockers.append({
            "code": "scheduler_process_lineage_too_deep",
            "actual": len(observed_ancestors),
            "expected_maximum": MAX_PROCESS_ANCESTORS,
        })
        observed_ancestors = observed_ancestors[:MAX_PROCESS_ANCESTORS]

    observed_process_id = _int_or_default(observed_process.get("process_id"))
    observed_process_parent_id = _int_or_default(
        observed_process.get("parent_process_id")
    )
    if not lineage or observed_process_id != current_process_id:
        blockers.append({
            "code": "scheduler_process_pid_mismatch",
            "actual": observed_process_id,
            "expected": current_process_id,
        })

    command_parser = process_argument_parser or _windows_command_line_argv

    def parse_observed_command(
        observed: Mapping[str, Any], ancestor_depth: int
    ) -> list[str]:
        try:
            parsed = command_parser(str(observed.get("command_line") or ""))
            return [str(value) for value in parsed]
        except Exception as exc:  # noqa: BLE001 - evidence must fail closed
            blockers.append({
                "code": "scheduler_process_command_unparseable",
                "ancestor_depth": ancestor_depth,
                "detail": f"{type(exc).__name__}: {exc}",
            })
            return []

    observed_nodes = [observed_process, *observed_ancestors]
    observed_argv = [
        parse_observed_command(node, depth)
        for depth, node in enumerate(observed_nodes)
    ]

    previous_parent_id = observed_process_parent_id
    for depth, ancestor in enumerate(observed_ancestors, start=1):
        ancestor_id = _int_or_default(ancestor.get("process_id"))
        if previous_parent_id != ancestor_id or ancestor_id <= 0:
            blockers.append({
                "code": "scheduler_process_lineage_pid_mismatch",
                "ancestor_depth": depth,
                "actual": {
                    "expected_parent_process_id": previous_parent_id,
                    "observed_process_id": ancestor_id,
                },
            })
        previous_parent_id = _int_or_default(ancestor.get("parent_process_id"))

    observed_process_executable = _path_key(observed_process.get("executable"))
    observed_process_command_executable = (
        _path_key(observed_argv[0][0]) if observed_argv and observed_argv[0] else ""
    )
    expected_process_image_key = _path_key(
        process_image_executable
        or getattr(sys, "_base_executable", None)
        or sys.executable
    )
    expected_process_executable_key = _path_key(
        expected_process_executable or expected_executable
    )
    if (
        observed_process_executable != expected_process_image_key
        or observed_process_command_executable != expected_process_image_key
    ):
        blockers.append({
            "code": "scheduler_process_image_mismatch",
            "actual": {
                "image": observed_process_executable,
                "command": observed_process_command_executable,
            },
            "expected": expected_process_image_key,
        })
    observed_process_arguments = (
        observed_argv[0][1:] if observed_argv and observed_argv[0] else []
    )
    if observed_process_arguments != process_arguments:
        blockers.append({
            "code": "scheduler_process_arguments_mismatch",
            "actual": observed_process_arguments,
            "expected": process_arguments,
        })

    observed_process_started = _utc(observed_process.get("created_at_utc"))
    process_start_delta_seconds = None
    if observed_process_started is None or started_at is None:
        blockers.append({
            "code": "scheduler_process_start_correlation_missing",
            "actual": observed_process.get("created_at_utc"),
        })
    else:
        process_start_delta_seconds = (
            started_at - observed_process_started
        ).total_seconds()
        if (
            process_start_delta_seconds < -PROCESS_START_EARLY_TOLERANCE_SECONDS
            or process_start_delta_seconds > PROCESS_START_CORRELATION_SECONDS
        ):
            blockers.append({
                "code": "scheduler_process_start_correlation_stale",
                "actual_seconds": round(process_start_delta_seconds, 3),
                "expected": (
                    f"-{PROCESS_START_EARLY_TOLERANCE_SECONDS:.1f}.."
                    f"{PROCESS_START_CORRELATION_SECONDS:.1f}"
                ),
            })

    redirector_required = (
        expected_process_image_key != expected_process_executable_key
    )
    launcher_depth = 1 if redirector_required else 0
    launcher_node = (
        observed_ancestors[0]
        if redirector_required and observed_ancestors else observed_process
    )
    launcher_argv = (
        observed_argv[1]
        if redirector_required and len(observed_argv) > 1 else observed_argv[0]
    )
    if redirector_required and not observed_ancestors:
        blockers.append({
            "code": "scheduler_process_launcher_missing",
            "detail": "expected Windows venv redirector is not the immediate parent",
        })
    launcher_executable = _path_key(launcher_node.get("executable"))
    launcher_command_executable = (
        _path_key(launcher_argv[0]) if launcher_argv else ""
    )
    launcher_arguments = launcher_argv[1:] if launcher_argv else []
    if redirector_required and (
        launcher_executable != expected_process_executable_key
        or launcher_command_executable != expected_process_executable_key
        or launcher_arguments != process_arguments
    ):
        blockers.append({
            "code": "scheduler_process_launcher_mismatch",
            "actual": {
                "image": launcher_executable,
                "command": launcher_command_executable,
                "arguments": launcher_arguments,
            },
            "expected": {
                "executable": expected_process_executable_key,
                "arguments": process_arguments,
            },
        })
    launcher_started = _utc(launcher_node.get("created_at_utc"))
    redirector_child_start_delta_seconds = None
    if redirector_required:
        if observed_process_started is None or launcher_started is None:
            blockers.append({
                "code": "scheduler_process_launcher_start_correlation_missing",
                "actual": launcher_node.get("created_at_utc"),
            })
        else:
            redirector_child_start_delta_seconds = (
                observed_process_started - launcher_started
            ).total_seconds()
            if (
                redirector_child_start_delta_seconds
                < -PROCESS_START_EARLY_TOLERANCE_SECONDS
                or redirector_child_start_delta_seconds
                > VENV_REDIRECTOR_START_CORRELATION_SECONDS
            ):
                blockers.append({
                    "code": "scheduler_process_launcher_start_correlation_stale",
                    "actual_seconds": round(
                        redirector_child_start_delta_seconds, 3
                    ),
                    "expected": (
                        f"-{PROCESS_START_EARLY_TOLERANCE_SECONDS:.1f}.."
                        f"{VENV_REDIRECTOR_START_CORRELATION_SECONDS:.1f}"
                    ),
                })

    if topology == "direct":
        scheduler_node = launcher_node
        scheduler_argv = launcher_argv
        scheduler_depth = launcher_depth
    else:
        scheduler_index = launcher_depth
        scheduler_depth = scheduler_index + 1
        scheduler_node = (
            observed_ancestors[scheduler_index]
            if len(observed_ancestors) > scheduler_index else {}
        )
        scheduler_argv = (
            observed_argv[scheduler_depth]
            if len(observed_argv) > scheduler_depth else []
        )
        if not scheduler_node:
            blockers.append({
                "code": "scheduler_parent_lineage_missing",
                "ancestor_depth": scheduler_depth,
            })

    observed_scheduler_executable = _path_key(scheduler_node.get("executable"))
    observed_scheduler_command_executable = (
        _path_key(scheduler_argv[0]) if scheduler_argv else ""
    )
    expected_scheduler_executable = _path_key(expected_executable)
    if (
        observed_scheduler_executable != expected_scheduler_executable
        or observed_scheduler_command_executable != expected_scheduler_executable
    ):
        blockers.append({
            "code": "scheduler_parent_executable_mismatch",
            "actual": {
                "image": observed_scheduler_executable,
                "command": observed_scheduler_command_executable,
                "ancestor_depth": scheduler_depth,
            },
            "expected": expected_scheduler_executable,
        })
    scheduler_arguments = scheduler_argv[1:] if scheduler_argv else []
    if scheduler_arguments != expected_arguments:
        blockers.append({
            "code": "scheduler_parent_arguments_mismatch",
            "actual": scheduler_arguments,
            "expected": expected_arguments,
        })

    scheduler_process_id = _int_or_default(scheduler_node.get("process_id"))
    if scheduler_process_id <= 0:
        blockers.append({
            "code": "scheduler_parent_pid_missing",
            "actual": scheduler_node.get("process_id"),
        })
    running_instances = task.get("running_instances")
    if isinstance(running_instances, Mapping):
        running_instances = [running_instances]
    running_instances = (
        [row for row in running_instances if isinstance(row, Mapping)]
        if isinstance(running_instances, list) else []
    )
    if len(running_instances) != 1:
        blockers.append({
            "code": "scheduler_running_instance_count_mismatch",
            "actual": len(running_instances),
            "expected": 1,
        })
    running_instance = running_instances[0] if len(running_instances) == 1 else {}
    scheduler_engine_process_id = _int_or_default(
        running_instance.get("engine_process_id")
    )
    if scheduler_engine_process_id != scheduler_process_id:
        blockers.append({
            "code": "scheduler_parent_engine_pid_mismatch",
            "actual": scheduler_process_id,
            "expected": scheduler_engine_process_id,
        })
    scheduler_instance_guid = str(running_instance.get("instance_guid") or "")
    if not scheduler_instance_guid:
        blockers.append({"code": "scheduler_running_instance_identity_missing"})
    scheduler_instance_state = _int_or_default(running_instance.get("state"))
    if scheduler_instance_state != 4:
        blockers.append({
            "code": "scheduler_running_instance_state_mismatch",
            "actual": scheduler_instance_state,
            "expected": 4,
        })

    scheduler_started = _utc(scheduler_node.get("created_at_utc"))
    child_parent_start_delta_seconds = None
    if topology == "delegated_child":
        if observed_process_started is None or scheduler_started is None:
            blockers.append({
                "code": "scheduler_child_parent_start_correlation_missing",
                "actual": {
                    "child": observed_process.get("created_at_utc"),
                    "parent": scheduler_node.get("created_at_utc"),
                },
            })
        else:
            child_parent_start_delta_seconds = (
                observed_process_started - scheduler_started
            ).total_seconds()
            if (
                child_parent_start_delta_seconds
                < -PROCESS_START_EARLY_TOLERANCE_SECONDS
                or child_parent_start_delta_seconds > correlation_limit
            ):
                blockers.append({
                    "code": "scheduler_child_parent_start_correlation_stale",
                    "actual_seconds": round(child_parent_start_delta_seconds, 3),
                    "expected": (
                        f"-{PROCESS_START_EARLY_TOLERANCE_SECONDS:.1f}.."
                        f"{correlation_limit:.1f}"
                    ),
                })

    launcher_process_id = _int_or_default(launcher_node.get("process_id"))
    lineage_evidence: dict[str, Any] = {
        "status": "PASS",
        "process_id": observed_process_id if observed_process_id > 0 else None,
        "process_parent_id": (
            observed_process_parent_id if observed_process_parent_id > 0 else None
        ),
        "process_executable": observed_process_executable,
        "process_arguments": observed_process_arguments,
        "process_working_directory": _path_key(
            process_working_directory or Path.cwd()
        ),
        "process_started_at_utc": _iso(observed_process_started),
        "process_start_delta_seconds": (
            round(process_start_delta_seconds, 3)
            if process_start_delta_seconds is not None else None
        ),
        "logical_launcher_process_id": (
            launcher_process_id if launcher_process_id > 0 else None
        ),
        "logical_launcher_executable": launcher_executable,
        "logical_launcher_started_at_utc": _iso(launcher_started),
        "venv_redirector_observed": redirector_required,
        "redirector_child_start_delta_seconds": (
            round(redirector_child_start_delta_seconds, 3)
            if redirector_child_start_delta_seconds is not None else None
        ),
        "scheduler_process_id": (
            scheduler_process_id if scheduler_process_id > 0 else None
        ),
        "scheduler_engine_process_id": (
            scheduler_engine_process_id
            if scheduler_engine_process_id > 0 else None
        ),
        "scheduler_instance_guid": scheduler_instance_guid,
        "scheduler_instance_state": scheduler_instance_state,
        "scheduler_current_action": str(
            running_instance.get("current_action") or ""
        ),
        "scheduler_ancestor_depth": scheduler_depth,
        "scheduler_executable": observed_scheduler_executable,
        "scheduler_arguments": scheduler_arguments,
        "scheduler_started_at_utc": _iso(scheduler_started),
        "child_parent_start_delta_seconds": (
            round(child_parent_start_delta_seconds, 3)
            if child_parent_start_delta_seconds is not None else None
        ),
        "observed_ancestor_count": len(observed_ancestors),
        "maximum_ancestor_count": MAX_PROCESS_ANCESTORS,
    }
    if registered_arguments != expected_arguments:
        blockers.append({
            "code": "scheduler_arguments_mismatch",
            "actual": registered_arguments,
            "expected": expected_arguments,
        })
    registered_executable = _path_key(action.get("execute"))
    expected_executable_key = _path_key(expected_executable)
    actual_process_executable = _path_key(process_executable or sys.executable)
    expected_process_executable_key = _path_key(
        expected_process_executable or expected_executable
    )
    if registered_executable != expected_executable_key:
        blockers.append({
            "code": "scheduler_executable_mismatch",
            "actual": registered_executable,
            "expected": expected_executable_key,
        })
    if actual_process_executable != expected_process_executable_key:
        blockers.append({
            "code": "running_executable_mismatch",
            "actual": actual_process_executable,
            "expected": expected_process_executable_key,
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
        if delta_seconds < -5.0 or delta_seconds > correlation_limit:
            blockers.append({
                "code": "scheduler_run_correlation_stale",
                "actual_seconds": round(delta_seconds, 3),
                "expected": f"-5..{correlation_limit:.1f}",
            })
    parent_started = _utc(lineage_evidence.get("scheduler_started_at_utc"))
    parent_delta_seconds = None
    if parent_started is None or last_run is None:
        blockers.append({
            "code": "scheduler_parent_run_correlation_missing",
            "actual": lineage_evidence.get("scheduler_started_at_utc"),
        })
    else:
        parent_delta_seconds = (parent_started - last_run).total_seconds()
        if (
            parent_delta_seconds < -PROCESS_START_EARLY_TOLERANCE_SECONDS
            or parent_delta_seconds > TASK_ENGINE_START_CORRELATION_SECONDS
        ):
            blockers.append({
                "code": "scheduler_parent_run_correlation_stale",
                "actual_seconds": round(parent_delta_seconds, 3),
                "expected": (
                    f"-{PROCESS_START_EARLY_TOLERANCE_SECONDS:.1f}.."
                    f"{TASK_ENGINE_START_CORRELATION_SECONDS:.1f}"
                ),
            })
    lineage_evidence["parent_task_start_delta_seconds"] = (
        round(parent_delta_seconds, 3)
        if parent_delta_seconds is not None else None
    )
    lineage_blocked = any(
        row["code"].startswith("scheduler_process_")
        or row["code"].startswith("scheduler_parent_")
        or row["code"].startswith("scheduler_child_")
        or row["code"].startswith("scheduler_running_instance_")
        or row["code"] in {
            "running_executable_mismatch",
            "running_working_directory_mismatch",
            "scheduler_correlation_contract_invalid",
            "scheduler_direct_process_executable_mismatch",
            "scheduler_direct_process_arguments_mismatch",
        }
        for row in blockers
    )
    lineage_evidence["status"] = "BLOCK" if lineage_blocked else "PASS"

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
        or row["code"].startswith("scheduler_parent_run_correlation")
        or row["code"].startswith("scheduler_child_parent_start_correlation")
        or row["code"].startswith("scheduler_process_start_correlation")
        or row["code"].startswith(
            "scheduler_process_launcher_start_correlation"
        )
        or row["code"] in {
            "scheduler_correlation_contract_invalid",
            "scheduler_task_not_running",
        }
        for row in blockers
    ) else "BLOCK"
    contract = {
        "invocation_topology": topology,
        "task_name": str(task_name),
        # Flat scheduler-action aliases are retained for existing evidence
        # readers; both topologies add the explicit OS process sub-contract.
        "executable": expected_executable_key,
        "arguments": expected_arguments,
        "working_directory": expected_workdir,
        "scheduler_action": {
            "executable": expected_executable_key,
            "arguments": expected_arguments,
            "working_directory": expected_workdir,
        },
        "producer_process": {
            "executable": expected_process_executable_key,
            "arguments": process_arguments,
            "working_directory": expected_workdir,
        },
        "task_definition_sha256": definition_sha256,
    }
    contract["contract_sha256"] = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    status = "PASS" if not blockers else "BLOCK"
    return {
        "status": status,
        "scheduler_attested": status == "PASS",
        "invocation_topology": topology,
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
                "scheduler_invocation_topology_invalid",
                "scheduler_correlation_contract_invalid",
                "scheduler_process_contract_missing",
                "scheduler_direct_process_executable_mismatch",
                "scheduler_direct_process_arguments_mismatch",
                "scheduler_process_lineage_query_failed",
                "scheduler_process_lineage_invalid",
                "scheduler_process_lineage_missing",
                "scheduler_process_lineage_too_deep",
                "scheduler_process_lineage_pid_mismatch",
                "scheduler_process_pid_mismatch",
                "scheduler_process_command_unparseable",
                "scheduler_process_image_mismatch",
                "scheduler_process_arguments_mismatch",
                "scheduler_process_start_correlation_missing",
                "scheduler_process_start_correlation_stale",
                "scheduler_process_launcher_missing",
                "scheduler_process_launcher_mismatch",
                "scheduler_process_launcher_start_correlation_missing",
                "scheduler_process_launcher_start_correlation_stale",
                "scheduler_parent_lineage_missing",
                "scheduler_parent_executable_mismatch",
                "scheduler_parent_arguments_mismatch",
                "scheduler_parent_pid_missing",
                "scheduler_running_instance_count_mismatch",
                "scheduler_running_instance_identity_missing",
                "scheduler_running_instance_state_mismatch",
                "scheduler_parent_engine_pid_mismatch",
                "scheduler_parent_run_correlation_missing",
                "scheduler_parent_run_correlation_stale",
                "scheduler_child_parent_start_correlation_missing",
                "scheduler_child_parent_start_correlation_stale",
            }
            for row in blockers
        ) else "BLOCK"},
        "task_run_correlation": {
            "status": correlation_status,
            "last_run_time_utc": _iso(last_run),
            "process_start_delta_seconds": (
                round(delta_seconds, 3) if delta_seconds is not None else None
            ),
            "max_delta_seconds": correlation_limit,
            "task_running_result_code": TASK_RUNNING_RESULT,
        },
        "process_lineage": lineage_evidence,
        "blockers": blockers,
    }


def build_invocation_proof(
    args,
    *,
    module_name: str,
    invocation_started_at_utc: datetime | str,
    argv: Sequence[str] | None = None,
    task_query=None,
    argument_parser=None,
    process_query=None,
    process_argument_parser=None,
    process_id: int | None = None,
    process_image_executable: str | Path | None = None,
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
    topology = str(
        getattr(args, "scheduler_invocation_topology", "direct") or "direct"
    ).strip()
    action_arguments_b64 = str(
        getattr(args, "scheduler_task_action_arguments_b64", "") or ""
    )
    expected_process_executable = str(
        getattr(args, "scheduler_process_executable", "") or ""
    )
    raw_correlation_seconds = getattr(
        args, "scheduler_correlation_seconds", DEFAULT_CORRELATION_SECONDS
    )
    try:
        correlation_seconds = float(raw_correlation_seconds)
    except (TypeError, ValueError):
        correlation_seconds = DEFAULT_CORRELATION_SECONDS
        correlation_contract_invalid = True
    else:
        correlation_contract_invalid = (
            not math.isfinite(correlation_seconds) or correlation_seconds <= 0
        )
        if correlation_contract_invalid:
            correlation_seconds = DEFAULT_CORRELATION_SECONDS
    running_argv = list(argv if argv is not None else sys.argv[1:])
    process_arguments = ["-m", module_name, *running_argv]
    contract_blockers = []
    if correlation_contract_invalid:
        contract_blockers.append({
            "code": "scheduler_correlation_contract_invalid",
            "actual": repr(raw_correlation_seconds),
        })
    expected_arguments: list[str] = []
    if not task_name or not expected_executable or not expected_workdir:
        contract_blockers.append({
            "code": "scheduler_contract_missing",
            "detail": "registration must pass task name/executable/working directory",
        })
    if topology not in SCHEDULER_INVOCATION_TOPOLOGIES:
        contract_blockers.append({
            "code": "scheduler_invocation_topology_invalid",
            "actual": topology,
            "expected": sorted(SCHEDULER_INVOCATION_TOPOLOGIES),
        })
    elif topology == "direct":
        expected_arguments = process_arguments
        if action_arguments_b64 or expected_process_executable:
            contract_blockers.append({
                "code": "scheduler_direct_contract_ambiguous",
                "detail": "direct topology derives action/process identity from the running command",
            })
        expected_process_executable = expected_executable
    elif topology == "delegated_child":
        if not expected_process_executable:
            contract_blockers.append({
                "code": "scheduler_process_contract_missing",
                "detail": "delegated_child requires --scheduler-process-executable",
            })
        try:
            expected_arguments = decode_scheduler_action_arguments(action_arguments_b64)
        except ValueError as exc:
            contract_blockers.append({
                "code": "scheduler_task_action_contract_invalid",
                "detail": str(exc),
            })

    if not contract_blockers:
        attestation = attest_scheduled_invocation(
            task_name=task_name,
            expected_executable=expected_executable,
            expected_arguments=expected_arguments,
            expected_working_directory=expected_workdir,
            invocation_started_at_utc=invocation_started_at_utc,
            invocation_topology=topology,
            expected_process_executable=expected_process_executable,
            expected_process_arguments=process_arguments,
            correlation_seconds=correlation_seconds,
            task_query=task_query,
            argument_parser=argument_parser,
            process_query=process_query,
            process_argument_parser=process_argument_parser,
            process_id=process_id,
            process_image_executable=process_image_executable,
            os_name=os_name,
        )
    else:
        attestation = {
            "status": "BLOCK",
            "scheduler_attested": False,
            "invocation_topology": topology,
            "task_name": task_name,
            "task_definition_sha256": "",
            "contract": {"status": "BLOCK"},
            "task_run_correlation": {"status": "BLOCK"},
            "process_lineage": {"status": "BLOCK"},
            "blockers": contract_blockers,
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
            "release_kind": "",
            "candidate_mode": "",
            "production_capable": False,
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
            "release_kind": bundle.release_kind,
            "candidate_mode": bundle.candidate_mode,
            "production_capable": bundle.production_capable,
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
        "release_kind": bundle.release_kind,
        "candidate_mode": bundle.candidate_mode,
        "production_capable": bundle.production_capable,
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
