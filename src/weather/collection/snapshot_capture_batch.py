"""Bounded, isolated execution for one snapshot fleet pass.

The managed snapshot loop owns scheduling and status.  This module owns only
the mechanical part of a pass: start due markets in their existing priority
order, cap concurrent child processes, and give every child a killable timeout.
Each child writes to one market/event folder, whose ``SnapshotStore`` lock
continues to provide the file-level single-writer guarantee.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

from weather.operations.long_job_guard import run_isolated_subprocess
from weather.collection.forecast_payload_fetch_fanout import (
    FANOUT_CAS_ROOT_ENV,
    FANOUT_SCOPE_ENV,
)


# Two workers keep the worst-case aggregate child commit below the previous
# three-worker envelope while still fitting six waves inside the fleet budget.
DEFAULT_CAPTURE_WORKERS = 2
DEFAULT_FLEET_BUDGET_SECONDS = 540.0
DEFAULT_MARKET_TIMEOUT_SECONDS = 120.0
# ``run_isolated_subprocess`` preserves this legacy argument as both a real
# working-set ceiling and a Windows Job Object private-commit ceiling.  Normal
# production captures can approach 1.51 GiB of private commit, so 1.5 GiB left
# no allocation headroom and caused intermittent kernel-enforced exit 137s.
DEFAULT_CHILD_WORKING_SET_MAX_MB = 1792
DEFAULT_CAPTURE_HOST_RESERVE_MB = 1536
DEFAULT_HEARTBEAT_SECONDS = 5.0


def console_python_executable(executable=None):
    """Return a Python interpreter whose stdout/result channel is usable.

    The production supervisor runs under ``pythonw.exe``.  A child launched
    with that executable has no standard streams, so use its sibling
    ``python.exe`` for isolated one-shot captures.
    """

    path = Path(executable or sys.executable)
    if path.name.lower() == "pythonw.exe":
        console_path = path.with_name("python.exe")
        if console_path.exists():
            return str(console_path)
    return str(path)


def capture_command(
    request,
    *,
    result_path,
    expected_runtime_fingerprint=None,
    python_executable=None,
):
    command = [
        console_python_executable(python_executable),
        "-m",
        "weather.collection.snapshot_tracker",
        "--market",
        str(request["market_id"]),
        "--result-json",
        str(result_path),
    ]
    if request.get("force"):
        command.append("--force")
    if request.get("target_date"):
        command.extend(["--target-date", str(request["target_date"])])
    if expected_runtime_fingerprint:
        command.extend([
            "--expected-runtime-fingerprint",
            str(expected_runtime_fingerprint),
        ])
    return command


def _error_result(kind, detail, *, retryable=True):
    return {
        "written": False,
        "error": f"{kind}: {detail}",
        "capture_status": kind,
        "retryable": bool(retryable),
    }


def capture_worker_admission(
    requested_workers,
    *,
    child_memory_max_mb=DEFAULT_CHILD_WORKING_SET_MAX_MB,
    host_reserve_mb=DEFAULT_CAPTURE_HOST_RESERVE_MB,
    available_memory_bytes=None,
):
    """Admit only workers whose full ceilings leave the host reserve intact."""

    requested = max(1, int(requested_workers))
    child_bytes = max(1, int(child_memory_max_mb)) * 1024 * 1024
    reserve_bytes = max(0, int(host_reserve_mb)) * 1024 * 1024
    available = (
        int(available_memory_bytes)
        if available_memory_bytes is not None and int(available_memory_bytes) >= 0
        else None
    )
    admitted = 0
    if available is not None and available >= reserve_bytes + child_bytes:
        admitted = min(
            requested,
            max(0, (available - reserve_bytes) // child_bytes),
        )
    return {
        "status": "PASS" if admitted else "BLOCK",
        "requested_worker_count": requested,
        "admitted_worker_count": int(admitted),
        "available_memory_bytes": available,
        "child_memory_ceiling_bytes": child_bytes,
        "host_reserve_bytes": reserve_bytes,
        "required_for_one_worker_bytes": reserve_bytes + child_bytes,
        "required_for_requested_workers_bytes": (
            reserve_bytes + requested * child_bytes
        ),
        "reason": (
            "measurement_unavailable"
            if available is None
            else "insufficient_physical_memory"
            if not admitted
            else "requested_workers_admitted"
            if admitted == requested
            else "worker_count_reduced_for_physical_memory"
        ),
    }


def run_isolated_capture(
    request,
    timeout_seconds,
    *,
    expected_runtime_fingerprint=None,
    python_executable=None,
    cwd=None,
    working_set_max_mb=DEFAULT_CHILD_WORKING_SET_MAX_MB,
    shared_source_cooldown_path=None,
    shared_forecast_payload_cas_root=None,
    market_invariant_fetch_scope=None,
    subprocess_runner=run_isolated_subprocess,
    now_fn=None,
):
    """Run one market capture in a bounded process tree and read its result."""

    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    started_at = now_fn()
    with tempfile.TemporaryDirectory(prefix="weather_snapshot_capture_") as tmp:
        result_path = Path(tmp) / "result.json"
        command = capture_command(
            request,
            result_path=result_path,
            expected_runtime_fingerprint=expected_runtime_fingerprint,
            python_executable=python_executable,
        )
        child_env = os.environ.copy()
        if shared_source_cooldown_path:
            child_env["WEATHER_SOURCE_FAMILY_COOLDOWN_PATH"] = str(
                shared_source_cooldown_path
            )
        if bool(shared_forecast_payload_cas_root) != bool(
            market_invariant_fetch_scope
        ):
            raise ValueError(
                "isolated forecast fan-out requires both CAS root and scope"
            )
        if shared_forecast_payload_cas_root:
            child_env[FANOUT_CAS_ROOT_ENV] = str(
                shared_forecast_payload_cas_root
            )
            child_env[FANOUT_SCOPE_ENV] = str(market_invariant_fetch_scope)
        execution = subprocess_runner(
            command,
            timeout_seconds=max(1.0, float(timeout_seconds)),
            working_set_max_bytes=(
                max(1, int(working_set_max_mb)) * 1024 * 1024
                if working_set_max_mb
                else None
            ),
            cwd=cwd,
            env=child_env,
            output_tail_chars=16_384,
        )
        completed_at = now_fn()
        if execution.get("timed_out"):
            result = _error_result(
                "capture_timeout",
                f"market process exceeded {float(timeout_seconds):.1f}s",
            )
        elif execution.get("runner_error"):
            result = _error_result(
                "capture_runner_error",
                execution["runner_error"],
            )
        elif execution.get("resource_limit_exceeded"):
            resource_limit = execution["resource_limit_exceeded"]
            resource = str(resource_limit.get("resource") or "unknown")
            observed = resource_limit.get("observed_bytes")
            limit = resource_limit.get("limit_bytes")
            detail = f"{resource} exceeded"
            if observed is not None and limit is not None:
                detail = f"{detail}: observed_bytes={observed}, limit_bytes={limit}"
            result = _error_result("capture_resource_budget", detail)
        elif execution.get("returncode") not in (0, None):
            stderr = str(execution.get("stderr") or "").strip()
            result = _error_result(
                "capture_process_error",
                stderr[-2000:] or f"returncode={execution.get('returncode')}",
            )
        elif not result_path.exists():
            result = _error_result(
                "capture_result_missing",
                "child exited without an atomic result artifact",
            )
        else:
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("capture result root must be an object")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                result = _error_result(
                    "capture_result_invalid",
                    f"{type(exc).__name__}: {exc}",
                    retryable=False,
                )

    return {
        "market_id": request["market_id"],
        "started_at": started_at,
        "completed_at": completed_at,
        "result": result,
        "execution": {
            "mode": "isolated_subprocess",
            "timeout_seconds": round(float(timeout_seconds), 3),
            "duration_seconds": execution.get("duration_seconds"),
            "timed_out": bool(execution.get("timed_out")),
            "returncode": execution.get("returncode"),
            "working_set_limit": execution.get("working_set_limit"),
            "resource_peaks": execution.get("resource_peaks"),
            "resource_io": execution.get("resource_io"),
            "resource_limit_exceeded": execution.get("resource_limit_exceeded"),
            "containment": execution.get("containment"),
            "termination": execution.get("termination"),
            "runner_error": execution.get("runner_error"),
        },
    }


def _deadline_result(request, *, started_at, completed_at, detail):
    return {
        "market_id": request["market_id"],
        "started_at": started_at,
        "completed_at": completed_at,
        "result": _error_result("fleet_deadline", detail),
        "execution": {
            "mode": "isolated_subprocess",
            "not_started": True,
            "reason": "fleet_deadline",
        },
    }


def run_bounded_capture_batch(
    requests,
    *,
    worker_count=DEFAULT_CAPTURE_WORKERS,
    fleet_budget_seconds=DEFAULT_FLEET_BUDGET_SECONDS,
    market_timeout_seconds=DEFAULT_MARKET_TIMEOUT_SECONDS,
    heartbeat_seconds=DEFAULT_HEARTBEAT_SECONDS,
    runner_fn,
    progress_fn=None,
    monotonic_fn=time.monotonic,
    now_fn=None,
):
    """Execute requests with FIFO admission, bounded concurrency and deadline.

    A per-market timeout is tightened, when necessary, so the maximum number of
    waves fits inside the fleet budget.  The caller receives records in the
    original due order even though completions are harvested out of order.
    """

    requests = [dict(request) for request in requests]
    workers = max(1, int(worker_count))
    budget = max(1.0, float(fleet_budget_seconds))
    heartbeat = max(0.01, float(heartbeat_seconds))
    waves = max(1, math.ceil(len(requests) / workers))
    # Leave a small fixed allowance for process startup and tree cleanup.
    timeout = max(
        1.0,
        min(float(market_timeout_seconds), max(1.0, budget - 2.0) / waves),
    )
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    batch_started_at = now_fn()
    deadline = monotonic_fn() + budget
    next_index = 0
    active = {}
    results = {}
    submission_order = []
    max_active = 0

    def emit_progress():
        if progress_fn is None:
            return
        progress_fn({
            "active_markets": [row["request"]["market_id"] for row in active.values()],
            "queued_markets": [request["market_id"] for request in requests[next_index:]],
            "completed_markets": [
                request["market_id"]
                for request in requests
                if request["market_id"] in results
            ],
            "worker_count": workers,
            "effective_market_timeout_seconds": round(timeout, 3),
            "fleet_budget_seconds": round(budget, 3),
        })

    def submit_available(executor):
        nonlocal next_index, max_active
        while next_index < len(requests) and len(active) < workers:
            remaining = deadline - monotonic_fn()
            if remaining <= 1.0:
                break
            request = requests[next_index]
            next_index += 1
            request_timeout = max(1.0, min(timeout, remaining - 0.5))
            future = executor.submit(runner_fn, request, request_timeout)
            active[future] = {
                "request": request,
                "timeout_seconds": request_timeout,
            }
            submission_order.append(request["market_id"])
            max_active = max(max_active, len(active))

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="snapshot-capture") as executor:
        submit_available(executor)
        emit_progress()
        while active or next_index < len(requests):
            if not active:
                break
            remaining = deadline - monotonic_fn()
            wait_seconds = heartbeat if remaining <= 0 else min(heartbeat, remaining)
            done, _ = wait(
                tuple(active),
                timeout=max(0.01, wait_seconds),
                return_when=FIRST_COMPLETED,
            )
            for future in done:
                row = active.pop(future)
                request = row["request"]
                try:
                    record = future.result()
                except Exception as exc:  # noqa: BLE001 - isolate one market
                    moment = now_fn()
                    record = {
                        "market_id": request["market_id"],
                        "started_at": moment,
                        "completed_at": moment,
                        "result": _error_result(
                            "capture_runner_exception",
                            f"{type(exc).__name__}: {exc}",
                        ),
                        "execution": {
                            "mode": "isolated_subprocess",
                            "runner_exception": True,
                        },
                    }
                results[request["market_id"]] = record
            submit_available(executor)
            emit_progress()

        # Requests that could not be admitted before the fleet deadline are
        # explicit failures, never silent skips. Running children already have
        # a timeout no later than the remaining deadline at submission.
        while next_index < len(requests):
            request = requests[next_index]
            next_index += 1
            moment = now_fn()
            results[request["market_id"]] = _deadline_result(
                request,
                started_at=moment,
                completed_at=moment,
                detail=f"market was not admitted within {budget:.1f}s fleet budget",
            )

    batch_completed_at = now_fn()
    ordered_records = [results[request["market_id"]] for request in requests]
    return {
        "records": ordered_records,
        "summary": {
            "mode": "isolated_subprocess_batch",
            "request_count": len(requests),
            "worker_count": workers,
            "max_active": max_active,
            "wave_count": waves,
            "fleet_budget_seconds": round(budget, 3),
            "effective_market_timeout_seconds": round(timeout, 3),
            "submission_order": submission_order,
            "timeout_count": sum(
                1
                for record in ordered_records
                if record.get("result", {}).get("capture_status") == "capture_timeout"
            ),
            "error_count": sum(
                1 for record in ordered_records if record.get("result", {}).get("error")
            ),
            "started_at": batch_started_at.isoformat(),
            "completed_at": batch_completed_at.isoformat(),
        },
    }
