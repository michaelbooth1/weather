"""Supervise the read-only International public execution-tape producer.

This module owns process lifecycle only.  The managed worker imports the
public market websocket producer, which has no credential, wallet, order, or
exchange-mutation path.  Registration is a separate explicit host operation.
"""

from __future__ import annotations

from weather.operations.windows_silent import apply_windows_silent_subprocess_defaults

apply_windows_silent_subprocess_defaults()

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from weather.io import (
    ROTATE_BEFORE_APPEND,
    ROTATE_BEFORE_LAUNCH,
    append_rotating_jsonl,
    rotate_sidecar_policy,
)
from weather.market.execution_tape_capture import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_EVENT_METADATA,
    DEFAULT_EVENT_METADATA_MAX_AGE_HOURS,
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_INBOUND_SILENCE_TIMEOUT_SECONDS,
    DEFAULT_MAX_TOKENS_PER_CONNECTION,
    DEFAULT_SEED_CHECK_SECONDS,
    read_capture_status,
    run_live_capture,
)
from weather.market.execution_tape_store import DEFAULT_MAX_PART_BYTES, DEFAULT_SNAPSHOTS_ROOT
from weather.operations.supervisor import (
    SupervisorSpec,
    acquire_file_lock,
    age_seconds,
    atomic_write_json,
    authorize_managed_process_termination,
    authorize_writer_lock_removal,
    capture_managed_process_identity,
    configure_json_console_logging,
    launch_detached,
    loop_file_offsets,
    loop_writer_lock_health,
    managed_stop_allows_start,
    managed_stop_expected_command,
    persist_supervisor_status,
    pid_is_python,
    read_json_file,
    read_supervisor_status,
    read_writer_lock,
    readoption_debounce,
    release_file_lock,
    should_emit_recovery_block_diagnostic,
    supervisor_recovery_guard,
    terminate_managed_process,
)
from weather.paths import REPO_ROOT
from weather.runtime_identity import current_identity_for, get_runtime_identity, identities_match


TASK_NAME = "WeatherExecutionTapeSupervisor"
STATUS_PATH = DEFAULT_SNAPSHOTS_ROOT / "execution_tape_status.json"
DIAGNOSTICS_PATH = DEFAULT_SNAPSHOTS_ROOT / "execution_tape_supervisor_diagnostics.jsonl"
CONSOLE_LOG_PATH = DEFAULT_SNAPSHOTS_ROOT / "execution_tape_console.log"
SUPERVISOR_LOCK_PATH = DEFAULT_SNAPSHOTS_ROOT / "execution_tape_supervisor.lock"
DEFAULT_STALE_AFTER_SECONDS = 180.0
SIDECAR_ROTATE_BYTES = 64 * 1024 * 1024

EXECUTION_TAPE_SUPERVISOR = SupervisorSpec(
    name="execution_tape",
    module="weather.operations.execution_tape_supervisor",
    status_path=STATUS_PATH,
    diagnostics_path=DIAGNOSTICS_PATH,
    console_log_path=CONSOLE_LOG_PATH,
    cwd=REPO_ROOT,
    lock_path=SUPERVISOR_LOCK_PATH,
    tolerated_states=("RUNNING", "DEGRADED"),
    status_schema_fields=(
        "pid",
        "started_at",
        "last_heartbeat",
        "runtime_identity",
        "managed_process",
        "state",
        "evidence_integrity",
    ),
    restart_budget=12,
    restart_budget_window_hours=24.0,
    restart_backoff_base_seconds=120.0,
    restart_backoff_max_seconds=3600.0,
)


def runtime_supervisor_spec() -> SupervisorSpec:
    return EXECUTION_TAPE_SUPERVISOR.with_paths(
        status_path=STATUS_PATH,
        diagnostics_path=DIAGNOSTICS_PATH,
        console_log_path=CONSOLE_LOG_PATH,
        lock_path=SUPERVISOR_LOCK_PATH,
    )


def runtime_sidecar_rotation_policy() -> dict[Path, str]:
    return {
        DIAGNOSTICS_PATH: ROTATE_BEFORE_APPEND,
        CONSOLE_LOG_PATH: ROTATE_BEFORE_LAUNCH,
    }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def read_status(path: str | Path = STATUS_PATH) -> dict[str, Any] | None:
    payload = read_json_file(path)
    return payload if isinstance(payload, dict) else None


def append_diagnostic(record: Mapping[str, Any], path: str | Path = DIAGNOSTICS_PATH) -> Path:
    return append_rotating_jsonl(
        path,
        dict(record),
        max_bytes=SIDECAR_ROTATE_BYTES,
        now=utc_now(),
    )


def _normalized_pid(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _worker_command(
    *,
    market: str = "all",
    event_metadata: str | Path = DEFAULT_EVENT_METADATA,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
    max_tokens_per_connection: int = DEFAULT_MAX_TOKENS_PER_CONNECTION,
    seed_check_seconds: float = DEFAULT_SEED_CHECK_SECONDS,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    inbound_silence_timeout_seconds: float = DEFAULT_INBOUND_SILENCE_TIMEOUT_SECONDS,
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    event_metadata_max_age_hours: float = DEFAULT_EVENT_METADATA_MAX_AGE_HOURS,
) -> list[str]:
    return EXECUTION_TAPE_SUPERVISOR.command(
        "run",
        "--market",
        market,
        "--event-metadata",
        event_metadata,
        "--snapshots-root",
        snapshots_root,
        "--max-part-bytes",
        int(max_part_bytes),
        "--max-tokens-per-connection",
        int(max_tokens_per_connection),
        "--seed-check-seconds",
        float(seed_check_seconds),
        "--heartbeat-seconds",
        float(heartbeat_seconds),
        "--inbound-silence-timeout-seconds",
        float(inbound_silence_timeout_seconds),
        "--connect-timeout-seconds",
        float(connect_timeout_seconds),
        "--event-metadata-max-age-hours",
        float(event_metadata_max_age_hours),
    )


def _worker_command_from_status(status: Mapping[str, Any] | None) -> list[str]:
    row = status or {}
    return _worker_command(
        market=str(row.get("market") or "all"),
        event_metadata=str(row.get("event_metadata") or DEFAULT_EVENT_METADATA),
        snapshots_root=str(row.get("snapshots_root") or DEFAULT_SNAPSHOTS_ROOT),
        max_part_bytes=int(row.get("max_part_bytes") or DEFAULT_MAX_PART_BYTES),
        max_tokens_per_connection=int(
            row.get("max_tokens_per_connection") or DEFAULT_MAX_TOKENS_PER_CONNECTION
        ),
        seed_check_seconds=float(row.get("seed_check_seconds") or DEFAULT_SEED_CHECK_SECONDS),
        heartbeat_seconds=float(row.get("heartbeat_seconds") or DEFAULT_HEARTBEAT_SECONDS),
        inbound_silence_timeout_seconds=float(
            row.get("inbound_silence_timeout_seconds")
            or DEFAULT_INBOUND_SILENCE_TIMEOUT_SECONDS
        ),
        connect_timeout_seconds=float(
            row.get("connect_timeout_seconds") or DEFAULT_CONNECT_TIMEOUT_SECONDS
        ),
        event_metadata_max_age_hours=float(
            row.get("event_metadata_max_age_hours")
            or DEFAULT_EVENT_METADATA_MAX_AGE_HOURS
        ),
    )


def _validate_managed_scope(worker_options: Mapping[str, Any]) -> None:
    if str(worker_options.get("market") or "") != "all":
        raise ValueError("the managed execution-tape service requires --market all")
    configured_metadata = Path(str(worker_options.get("event_metadata") or "")).resolve()
    configured_root = Path(str(worker_options.get("snapshots_root") or "")).resolve()
    if configured_metadata != Path(DEFAULT_EVENT_METADATA).resolve():
        raise ValueError("the managed execution-tape service requires canonical event metadata")
    if configured_root != Path(DEFAULT_SNAPSHOTS_ROOT).resolve():
        raise ValueError("the managed execution-tape service requires the canonical snapshots root")


def _managed_identity_agrees(
    value: object,
    expected: Mapping[str, Any],
) -> bool:
    return bool(
        isinstance(value, dict)
        and _normalized_pid(value.get("pid")) == _normalized_pid(expected.get("pid"))
        and value.get("creation_time_token")
        and value.get("creation_time_token") == expected.get("creation_time_token")
        and value.get("expected_command") == expected.get("expected_command")
    )


def wait_for_worker_handshake(
    *,
    pid: int,
    managed_process: Mapping[str, Any],
    timeout_seconds: float = 15.0,
    status_reader=read_status,
    lock_reader=read_writer_lock,
    pid_check=pid_is_python,
    monotonic_fn=time.monotonic,
    sleep_fn=time.sleep,
) -> dict[str, Any]:
    """Require worker-owned status and lock provenance before launch succeeds."""

    deadline = monotonic_fn() + max(0.0, float(timeout_seconds))
    last_status: Mapping[str, Any] | None = None
    last_lock: Mapping[str, Any] | None = None
    while monotonic_fn() <= deadline:
        last_status = status_reader() or {}
        last_lock = lock_reader(STATUS_PATH) or {}
        ready = bool(
            _normalized_pid(last_status.get("pid")) == int(pid)
            and _normalized_pid(last_lock.get("pid")) == int(pid)
            and last_lock.get("exists")
            and last_status.get("last_heartbeat")
            and isinstance(last_status.get("runtime_identity"), dict)
            and last_status["runtime_identity"].get("source_fingerprint")
            and _managed_identity_agrees(last_status.get("managed_process"), managed_process)
            and _managed_identity_agrees(last_lock.get("managed_process"), managed_process)
        )
        if ready:
            return {
                "ready": True,
                "pid": pid,
                "status_state": last_status.get("state"),
                "runtime_source_fingerprint": last_status["runtime_identity"].get(
                    "source_fingerprint"
                ),
                "writer_lock": last_lock,
            }
        if not pid_check(pid):
            return {
                "ready": False,
                "pid": pid,
                "reason": "managed worker exited before status/lock handshake",
                "status": last_status,
                "writer_lock": last_lock,
            }
        sleep_fn(0.1)
    return {
        "ready": False,
        "pid": pid,
        "reason": "managed worker did not establish status/lock handshake before timeout",
        "status": last_status,
        "writer_lock": last_lock,
    }


def runtime_identity_matches(
    status: Mapping[str, Any] | None,
    current_identity: Mapping[str, Any] | None = None,
) -> tuple[bool, Mapping[str, Any] | None]:
    recorded = (status or {}).get("runtime_identity")
    if not isinstance(recorded, dict) or not recorded:
        return False, current_identity
    try:
        current = current_identity or current_identity_for(recorded)
    except (OSError, TypeError, ValueError):
        return False, current_identity
    return identities_match(recorded, current), current


def execution_tape_health(
    status: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    pid_alive: bool | None = None,
    current_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(timezone.utc)
    if not status:
        return {
            "state": "UNKNOWN",
            "pid": None,
            "pid_alive": False,
            "capture_state": None,
            "heartbeat_age_seconds": None,
            "runtime_identity_matches_current": False,
            "current_runtime_identity": current_identity,
            "detail": "execution-tape status is unavailable",
        }
    pid = _normalized_pid(status.get("pid"))
    if pid_alive is None:
        pid_alive = pid_is_python(pid)
    heartbeat = status.get("last_heartbeat") or status.get("updated_at_utc")
    heartbeat_age = age_seconds(current, heartbeat)
    identity_matches, current_runtime_identity = runtime_identity_matches(
        status,
        current_identity,
    )
    capture_state = str(status.get("state") or "UNKNOWN")
    if not pid_alive:
        state = "DEAD"
        detail = "recorded execution-tape process is not alive"
    elif not identity_matches:
        state = "STALE_CODE"
        detail = "managed execution-tape source identity differs from the current tree"
    elif heartbeat_age is None or heartbeat_age < 0 or heartbeat_age > float(stale_after_seconds):
        state = "HUNG"
        detail = "managed execution-tape heartbeat is stale or invalid"
    elif capture_state == "STOPPED":
        state = "DEAD"
        detail = "execution-tape status records a stopped producer"
    elif (
        capture_state == "CONNECTED"
        and status.get("evidence_integrity") == "PASS"
        and status.get("price_path_evidence_usable") is True
    ):
        state = "RUNNING"
        detail = None
    else:
        state = "DEGRADED"
        detail = (
            "producer is alive but public price-path evidence is not currently complete: "
            f"state={capture_state}; evidence_integrity={status.get('evidence_integrity')}"
        )
    return {
        "state": state,
        "pid": pid,
        "pid_alive": bool(pid_alive),
        "capture_state": capture_state,
        "heartbeat_age_seconds": round(heartbeat_age, 3) if heartbeat_age is not None else None,
        "stale_after_seconds": float(stale_after_seconds),
        "runtime_code_state": "current" if identity_matches else "stale_code",
        "runtime_identity_matches_current": identity_matches,
        "current_runtime_identity": current_runtime_identity,
        "evidence_integrity": status.get("evidence_integrity"),
        "price_path_evidence_usable": status.get("price_path_evidence_usable"),
        "active_market_day_count": status.get("active_market_day_count"),
        "last_seed_error": status.get("last_seed_error"),
        "detail": detail,
    }


def ensure_decision(
    health_state: str,
    pid_alive: bool,
    *,
    writer_lock_healthy: bool = True,
) -> str:
    if not writer_lock_healthy:
        return "restart" if pid_alive else "start"
    if health_state in EXECUTION_TAPE_SUPERVISOR.tolerated_states:
        return "noop"
    return "restart" if pid_alive else "start"


def _cleanup_writer_lock(
    *,
    expected_pid: object = None,
    confirmed_exit: Mapping[str, Any] | None = None,
    exited_identity: Mapping[str, Any] | None = None,
    attempts: int = 1,
) -> dict[str, Any]:
    for attempt in range(max(1, int(attempts))):
        lock = read_writer_lock(STATUS_PATH)
        if not lock.get("exists"):
            return {"removed": False, "reason": "no writer lock", "path": lock.get("path")}
        removal = authorize_writer_lock_removal(
            lock,
            expected_pid=_normalized_pid(expected_pid),
            confirmed_exit=confirmed_exit,
            exited_identity=exited_identity,
        )
        if not removal.get("authorized"):
            return {
                "removed": False,
                "blocked": True,
                "reason": removal.get("reason"),
                "path": lock.get("path"),
                "authorization": removal,
            }
        try:
            Path(lock["path"]).unlink()
        except FileNotFoundError:
            return {"removed": False, "reason": "writer lock already gone", "path": lock.get("path")}
        except OSError as exc:
            if attempt + 1 < max(1, int(attempts)):
                time.sleep(0.1)
                continue
            return {"removed": False, "reason": str(exc), "path": lock.get("path")}
        return {"removed": True, "reason": "confirmed dead writer", "path": lock.get("path")}
    return {"removed": False, "reason": "writer lock cleanup exhausted attempts"}


def stop_managed_capture(now: datetime | None = None) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(timezone.utc)
    status = read_status()
    pid = (status or {}).get("pid")
    writer_lock = read_writer_lock(STATUS_PATH)
    expected_command = managed_stop_expected_command(status, _worker_command_from_status(status))
    authorization = authorize_managed_process_termination(status, writer_lock, expected_command)
    if not authorization.get("authorized"):
        return {
            "stopped": False,
            "pid": pid,
            "reason": authorization.get("reason"),
            "authorization": authorization,
            "writer_lock": writer_lock,
        }
    managed_process = authorization["managed_process"]
    stop = terminate_managed_process(managed_process, expected_command)
    if not stop.get("stopped"):
        return {
            "stopped": False,
            "termination_requested": bool(stop.get("termination_requested")),
            "pid": pid,
            "reason": stop.get("reason"),
            "termination_scope": stop.get("termination_scope"),
            "authorization": authorization,
            "writer_lock": writer_lock,
        }
    confirmed_exit = {
        "exited": stop.get("exited") is True,
        "reason": stop.get("reason"),
        "pid": pid,
        "termination_scope": stop.get("termination_scope"),
    }
    lock_cleanup = _cleanup_writer_lock(
        expected_pid=pid,
        confirmed_exit=confirmed_exit,
        exited_identity=managed_process,
        attempts=20,
    )
    if not confirmed_exit.get("exited"):
        return {
            "stopped": False,
            "termination_requested": True,
            "pid": pid,
            "reason": confirmed_exit.get("reason"),
            "authorization": authorization,
            "post_termination_observation": confirmed_exit,
            "writer_lock": lock_cleanup,
        }
    if status:
        stopped_status = dict(status)
        stopped_status.update(
            {
                "state": "STOPPED",
                "capture_stopped_at_utc": current.isoformat(),
                "last_stop_requested_at": current.isoformat(),
                "last_heartbeat": current.isoformat(),
            }
        )
        atomic_write_json(STATUS_PATH, stopped_status, trailing_newline=True)
    append_diagnostic(
        {
            "time": current.isoformat(),
            "supervisor": "stop",
            "pid": pid,
            "writer_lock": lock_cleanup,
        }
    )
    return {
        "stopped": True,
        "pid": pid,
        "authorization": authorization,
        "post_termination_observation": confirmed_exit,
        "writer_lock": lock_cleanup,
    }


def start_managed_capture(now: datetime | None = None, **worker_options: Any) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(timezone.utc)
    _validate_managed_scope(worker_options)
    lock_cleanup = _cleanup_writer_lock(attempts=3)
    if lock_cleanup.get("blocked"):
        return {
            "started": False,
            "reason": lock_cleanup.get("reason"),
            "writer_lock": lock_cleanup,
        }
    rotations = rotate_sidecar_policy(runtime_sidecar_rotation_policy(), now=current)
    command = _worker_command(**worker_options)
    child = launch_detached(
        command,
        cwd=EXECUTION_TAPE_SUPERVISOR.cwd,
        console_log_path=CONSOLE_LOG_PATH,
        popen_fn=subprocess.Popen,
    )
    managed_process = capture_managed_process_identity(child.pid, command)
    handshake = wait_for_worker_handshake(
        pid=child.pid,
        managed_process=managed_process,
    )
    if not handshake.get("ready"):
        termination = terminate_managed_process(managed_process, command)
        confirmed_exit = {
            "exited": termination.get("exited") is True,
            "reason": termination.get("reason"),
            "pid": child.pid,
            "termination_scope": termination.get("termination_scope"),
        }
        failed_lock_cleanup = _cleanup_writer_lock(
            expected_pid=child.pid,
            confirmed_exit=confirmed_exit,
            exited_identity=managed_process,
            attempts=20,
        )
        result = {
            "started": False,
            "pid": child.pid,
            "reason": handshake.get("reason"),
            "managed_process": managed_process,
            "handshake": handshake,
            "termination": termination,
            "writer_lock": failed_lock_cleanup,
            "sidecar_rotations": rotations,
        }
        append_diagnostic(
            {"time": current.isoformat(), "supervisor": "start_failed", **result}
        )
        return result
    append_diagnostic(
        {
            "time": current.isoformat(),
            "supervisor": "start",
            "pid": child.pid,
            "managed_process": managed_process,
            "handshake": handshake,
            "writer_lock": lock_cleanup,
            "sidecar_rotations": rotations,
        }
    )
    return {
        "started": True,
        "pid": child.pid,
        "managed_process": managed_process,
        "handshake": handshake,
        "writer_lock": lock_cleanup,
        "sidecar_rotations": rotations,
    }


def acquire_supervisor_lock() -> int | None:
    return acquire_file_lock(SUPERVISOR_LOCK_PATH, attempts=2, stale_after_seconds=120)


def ensure_managed_capture(
    *,
    now: datetime | None = None,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    **worker_options: Any,
) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(timezone.utc)
    spec = runtime_supervisor_spec()
    handle = acquire_supervisor_lock()
    if handle is None:
        return persist_supervisor_status(
            spec,
            {
                "action": "locked",
                "state": "UNKNOWN",
                "reason": "another execution-tape supervisor action is running",
            },
            now=current,
        )
    try:
        status = read_status()
        alive = pid_is_python((status or {}).get("pid"))
        health = execution_tape_health(
            status,
            now=current,
            stale_after_seconds=stale_after_seconds,
            pid_alive=alive,
        )
        writer_lock = loop_writer_lock_health(
            spec.status_path,
            status_pid=(status or {}).get("pid"),
            status_pid_alive=alive,
        )
        action = ensure_decision(
            health["state"],
            alive,
            writer_lock_healthy=writer_lock["healthy"],
        )
        restart_cause = None
        if action in {"start", "restart"}:
            if status and not alive:
                restart_cause = health["state"]
            elif status and not writer_lock["healthy"]:
                restart_cause = writer_lock["reason"]
            else:
                restart_cause = health["state"]
        result: dict[str, Any] = {
            "action": action,
            "state": health["state"],
            "capture_state": health.get("capture_state"),
            "pid": health.get("pid"),
            "restart_cause": restart_cause,
            "writer_lock": writer_lock,
            "runtime_identity_matches_current": health.get(
                "runtime_identity_matches_current"
            ),
            "runtime_identity_before": (status or {}).get("runtime_identity"),
            "current_runtime_identity": health.get("current_runtime_identity"),
            "evidence_integrity": health.get("evidence_integrity"),
            "price_path_evidence_usable": health.get("price_path_evidence_usable"),
        }
        guard = supervisor_recovery_guard(spec, action, now=current)
        result["recovery_guard"] = guard
        if action in {"start", "restart"} and not guard.get("allowed"):
            result.update(
                {
                    "intended_action": action,
                    "action": guard.get("action"),
                    "reason": guard.get("reason"),
                    "remediation": guard.get("remediation"),
                }
            )
            event = {"time": current.isoformat(), "supervisor": "ensure", **result}
            if not should_emit_recovery_block_diagnostic(spec, event):
                result["diagnostic_suppressed"] = True
            result = persist_supervisor_status(spec, result, now=current)
            if not result.get("diagnostic_suppressed"):
                append_diagnostic(event)
            return result
        if action == "restart" and health["state"] == "STALE_CODE":
            debounce = readoption_debounce(
                runtime_code_state=health.get("runtime_code_state"),
                process_started_at=(status or {}).get("started_at"),
                now=current,
                debounce_seconds=spec.readoption_debounce_seconds,
            )
            result["readoption_debounce"] = debounce
            if debounce.get("debounced"):
                result.update(
                    {
                        "intended_action": "restart",
                        "action": "noop",
                        "reason": debounce.get("reason"),
                    }
                )
                return persist_supervisor_status(spec, result, now=current)
        if action in {"start", "restart"}:
            result["loop_offsets_before"] = loop_file_offsets(spec)
        if action == "restart":
            result["stop"] = stop_managed_capture(now=current)
            if not managed_stop_allows_start(result["stop"]):
                result.update(
                    {
                        "intended_action": "restart",
                        "action": "restart_blocked",
                        "reason": result["stop"].get("reason")
                        or "managed execution-tape stop was not confirmed",
                    }
                )
                result = persist_supervisor_status(spec, result, now=current)
                append_diagnostic({"time": current.isoformat(), "supervisor": "ensure", **result})
                return result
            result["start"] = start_managed_capture(now=current, **worker_options)
        elif action == "start":
            result["start"] = start_managed_capture(now=current, **worker_options)
        if action != "noop":
            result["loop_offsets_after"] = loop_file_offsets(spec)
        result = persist_supervisor_status(spec, result, now=current)
        if action != "noop":
            append_diagnostic({"time": current.isoformat(), "supervisor": "ensure", **result})
        return result
    finally:
        release_file_lock(handle, SUPERVISOR_LOCK_PATH)


def run_managed_capture(**worker_options: Any) -> None:
    _validate_managed_scope(worker_options)
    command = _worker_command(**worker_options)
    started = utc_now()
    managed_process = capture_managed_process_identity(os.getpid(), command)
    process_status = {
        "runner": "managed_execution_tape",
        "pid": os.getpid(),
        "started_at": started.isoformat(),
        "last_heartbeat": started.isoformat(),
        "runtime_identity": get_runtime_identity(scope_files="loaded"),
        "managed_process": managed_process,
        "started_by": "supervisor",
        **worker_options,
    }
    run_live_capture(
        event_metadata_path=worker_options["event_metadata"],
        markets=worker_options["market"],
        snapshots_root=worker_options["snapshots_root"],
        max_part_bytes=worker_options["max_part_bytes"],
        max_tokens_per_connection=worker_options["max_tokens_per_connection"],
        seed_check_seconds=worker_options["seed_check_seconds"],
        heartbeat_seconds=worker_options["heartbeat_seconds"],
        inbound_silence_timeout_seconds=worker_options[
            "inbound_silence_timeout_seconds"
        ],
        connect_timeout_seconds=worker_options["connect_timeout_seconds"],
        max_age_hours=worker_options["event_metadata_max_age_hours"],
        process_status=process_status,
    )


def _add_worker_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--market", default="all")
    parser.add_argument("--event-metadata", default=str(DEFAULT_EVENT_METADATA))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--max-part-bytes", type=int, default=DEFAULT_MAX_PART_BYTES)
    parser.add_argument(
        "--max-tokens-per-connection",
        type=int,
        default=DEFAULT_MAX_TOKENS_PER_CONNECTION,
    )
    parser.add_argument("--seed-check-seconds", type=float, default=DEFAULT_SEED_CHECK_SECONDS)
    parser.add_argument("--heartbeat-seconds", type=float, default=DEFAULT_HEARTBEAT_SECONDS)
    parser.add_argument(
        "--inbound-silence-timeout-seconds",
        type=float,
        default=DEFAULT_INBOUND_SILENCE_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--connect-timeout-seconds",
        type=float,
        default=DEFAULT_CONNECT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--event-metadata-max-age-hours",
        type=float,
        default=DEFAULT_EVENT_METADATA_MAX_AGE_HOURS,
    )


def _worker_options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "market": args.market,
        "event_metadata": args.event_metadata,
        "snapshots_root": args.snapshots_root,
        "max_part_bytes": args.max_part_bytes,
        "max_tokens_per_connection": args.max_tokens_per_connection,
        "seed_check_seconds": args.seed_check_seconds,
        "heartbeat_seconds": args.heartbeat_seconds,
        "inbound_silence_timeout_seconds": args.inbound_silence_timeout_seconds,
        "connect_timeout_seconds": args.connect_timeout_seconds,
        "event_metadata_max_age_hours": args.event_metadata_max_age_hours,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the managed read-only public producer.")
    _add_worker_options(run)
    start = sub.add_parser("start-detached", help="Start one detached managed producer.")
    _add_worker_options(start)
    ensure = sub.add_parser("ensure", help="Start or recover the producer if required.")
    _add_worker_options(ensure)
    ensure.add_argument("--stale-after-seconds", type=float, default=DEFAULT_STALE_AFTER_SECONDS)
    sub.add_parser("stop", help="Stop only the exactly identified managed producer.")
    restart = sub.add_parser("restart", help="Stop, then start, the managed producer.")
    _add_worker_options(restart)
    status = sub.add_parser("status", help="Print process, supervisor, and evidence health.")
    status.add_argument("--stale-after-seconds", type=float, default=DEFAULT_STALE_AFTER_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.command == "run":
        configure_json_console_logging()
        run_managed_capture(**_worker_options(args))
        return 0
    if args.command == "start-detached":
        result = start_managed_capture(**_worker_options(args))
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0 if result.get("started") else 1
    if args.command == "ensure":
        result = ensure_managed_capture(
            stale_after_seconds=args.stale_after_seconds,
            **_worker_options(args),
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return int(result.get("exit_code", 1))
    if args.command == "stop":
        result = stop_managed_capture()
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0 if result.get("stopped") else 1
    if args.command == "restart":
        stop = stop_managed_capture()
        result: dict[str, Any] = {"stop": stop}
        if managed_stop_allows_start(stop):
            result["start"] = start_managed_capture(**_worker_options(args))
        else:
            result["start"] = {
                "started": False,
                "reason": "managed stop was not confirmed",
            }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0 if result["start"].get("started") else 1
    if args.command == "status":
        status = read_status()
        payload = {
            "health": execution_tape_health(
                status,
                stale_after_seconds=args.stale_after_seconds,
            ),
            "supervisor": read_supervisor_status(runtime_supervisor_spec()),
            "status": status,
        }
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0 if payload["health"].get("state") in {"RUNNING", "DEGRADED"} else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
