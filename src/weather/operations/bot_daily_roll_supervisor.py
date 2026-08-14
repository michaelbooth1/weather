"""Shared ensure-style supervisor helpers for daily bot roll launchers."""

from __future__ import annotations

from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from weather.operations.bot_run_liveness import RUNNING_STATUSES, parse_utc, utc_iso
from weather.operations.supervisor import (
    SupervisorSpec,
    append_jsonl,
    loop_file_offsets,
    should_emit_recovery_block_diagnostic,
    supervisor_recovery_guard,
    terminate_python_pid,
)
from weather.runtime_identity import format_runtime_identity, get_runtime_identity, identities_match


STARTABLE_STATES = {"UNKNOWN", "DEAD", "IDLE", "STALE_CODE", "TARGET_MISMATCH"}


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_local_hhmm(value: str | None) -> dt_time | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.lower() in {"none", "always", "immediate"}:
        return None
    parsed = dt_time.fromisoformat(text)
    return parsed.replace(second=0, microsecond=0)


def local_time_gate(
    *,
    now: datetime,
    timezone_name: str,
    start_after_local_time: str | None,
    start_no_later_than_local_time: str | None = None,
) -> dict[str, Any]:
    start_threshold = parse_local_hhmm(start_after_local_time)
    end_threshold = parse_local_hhmm(start_no_later_than_local_time)
    if start_threshold is not None and end_threshold is not None and start_threshold >= end_threshold:
        raise ValueError(
            "start_after_local_time must be earlier than start_no_later_than_local_time"
        )
    local_now = now.astimezone(ZoneInfo(timezone_name))
    local_clock = local_now.time().replace(tzinfo=None)
    before_start = start_threshold is not None and local_clock < start_threshold
    after_end = end_threshold is not None and local_clock > end_threshold
    allowed = not before_start and not after_end
    if before_start:
        reason = "before_daily_start_time"
    elif after_end:
        reason = "after_daily_end_time"
    elif start_threshold is not None and end_threshold is not None:
        reason = "daily_start_window_open"
    elif start_threshold is not None:
        reason = "start_time_reached"
    elif end_threshold is not None:
        reason = "before_daily_end_time"
    else:
        reason = "no_start_time_gate"
    return {
        "allowed": allowed,
        "timezone": timezone_name,
        "local_now": local_now.isoformat(),
        "start_after_local_time": (
            start_threshold.isoformat(timespec="minutes") if start_threshold is not None else None
        ),
        "start_no_later_than_local_time": (
            end_threshold.isoformat(timespec="minutes") if end_threshold is not None else None
        ),
        "reason": reason,
    }


def runtime_identity_status(process_identity: dict[str, Any] | None, current_identity: dict[str, Any] | None = None):
    current_identity = current_identity or get_runtime_identity()
    if not process_identity:
        return {
            "runtime_code_state": "unknown",
            "runtime_identity_matches_current": None,
            "current_runtime_identity": current_identity,
            "detail": "no runtime identity recorded",
        }
    matches = identities_match(process_identity, current_identity)
    return {
        "runtime_code_state": "current" if matches else "stale_code",
        "runtime_identity_matches_current": matches,
        "current_runtime_identity": current_identity,
        "detail": None if matches else (
            "running process code identity differs from current source tree: "
            f"process={format_runtime_identity(process_identity)}; "
            f"current={format_runtime_identity(current_identity)}"
        ),
    }


def call_pid_alive(pid_alive: Callable[..., bool] | None, pid: Any, target_date: Any = None) -> bool:
    if not pid_alive or not pid:
        return False
    try:
        return bool(pid_alive(pid, target_date))
    except TypeError:
        return bool(pid_alive(pid))
    except (OSError, ValueError):
        return False


def latest_useful_write(status: dict[str, Any] | None) -> dict[str, Any]:
    status = status or {}
    artifact = status.get("artifact_liveness") or {}
    latest = artifact.get("latest_useful_artifact") or {}
    operator = status.get("operator_report") or {}
    return {
        "path": latest.get("path") or operator.get("latest_useful_write_path"),
        "at_utc": latest.get("modified_at_utc") or operator.get("latest_useful_write_at_utc"),
        "age_seconds": latest.get("age_seconds") or operator.get("latest_useful_write_age_seconds"),
        "artifact_liveness_status": artifact.get("status"),
        "artifact_liveness_root_cause": artifact.get("root_cause_class"),
    }


def _artifact_restart_required(status: dict[str, Any]) -> bool:
    artifact = status.get("artifact_liveness") or {}
    operator = status.get("operator_report") or {}
    non_restartable_content_statuses = {
        "LATEST_TICK_EMPTY",
        "INFRA_STARVED_CLOB",
        "INFRA_STARVED_SNAPSHOT",
    }
    if (
        artifact
        and artifact.get("ok") is False
        and artifact.get("status") not in non_restartable_content_statuses
    ):
        return True
    if operator.get("restart_recommended") is True:
        return True
    for key in ("latest_tick_scoring_liveness", "scoring_liveness", "latest_tick_liveness"):
        liveness = status.get(key) or {}
        if liveness.get("restart_recommended") is True:
            return True
    return False


def _artifact_restart_cause(status: dict[str, Any]) -> str:
    artifact = status.get("artifact_liveness") or {}
    operator = status.get("operator_report") or {}
    for key in ("latest_tick_scoring_liveness", "scoring_liveness", "latest_tick_liveness"):
        liveness = status.get(key) or {}
        if liveness.get("restart_recommended") is True:
            return liveness.get("root_cause_class") or key
    return (
        artifact.get("root_cause_class")
        or operator.get("restart_reason")
        or status.get("root_cause_class")
        or "artifact_liveness"
    )


def daily_roll_health(
    status: dict[str, Any] | None,
    *,
    target_date: str | None = None,
    current_identity: dict[str, Any] | None = None,
    now: datetime | str | None = None,
    pid_alive: Callable[..., bool] | None = None,
) -> dict[str, Any]:
    current = parse_datetime(now) or utc_now()
    status = dict(status or {})
    exists = bool(status and status.get("exists", True))
    if not exists:
        return {
            "state": "UNKNOWN",
            "action": "start",
            "restart_cause": "missing_status",
            "detail": "daily-roll status file is missing",
            "pid": status.get("pid"),
            "pid_alive": False,
            "target_date": status.get("target_date"),
            "expected_target_date": target_date,
            "latest_useful_write": latest_useful_write(status),
        }
    status_target = status.get("target_date")
    expected_target = target_date or status_target
    pid = status.get("pid")
    alive = call_pid_alive(pid_alive, pid, status_target) if pid_alive else bool(status.get("pid_alive", True))
    runtime = runtime_identity_status(status.get("runtime_identity"), current_identity)
    started_at = status.get("started_at_utc") or status.get("started_at") or status.get("generated_at_utc")
    started = parse_utc(started_at)
    status_value = status.get("status")
    base = {
        "pid": pid,
        "pid_alive": alive,
        "status": status_value,
        "target_date": status_target,
        "expected_target_date": expected_target,
        "started_at_utc": started.isoformat() if started else started_at,
        "started_age_seconds": round(max(0.0, (current.astimezone(timezone.utc) - started).total_seconds()), 3)
        if started
        else None,
        "latest_useful_write": latest_useful_write(status),
        "runtime_identity": status.get("runtime_identity") or {},
        "resource_diagnostics": (
            status.get("resource_diagnostics")
            or (status.get("operator_report") or {}).get("resource_diagnostics")
            or {}
        ),
        "incremental_persistence": (
            status.get("incremental_persistence")
            or (status.get("operator_report") or {}).get("incremental_persistence")
            or {}
        ),
        **runtime,
    }
    if expected_target and status_target != expected_target:
        return {
            **base,
            "state": "TARGET_MISMATCH",
            "action": "start",
            "restart_cause": "target_date_mismatch",
            "detail": f"status target_date={status_target or 'unknown'} expected={expected_target}",
        }
    if status_value == "pid_missing":
        return {
            **base,
            "state": "DEAD",
            "action": "start",
            "restart_cause": status.get("root_cause_class") or "pid_missing",
            "detail": "daily-roll process is not alive",
        }
    if status_value == "idle_process" or _artifact_restart_required(status):
        return {
            **base,
            "state": "IDLE",
            "action": "restart" if alive else "start",
            "restart_cause": _artifact_restart_cause(status),
            "detail": status.get("remediation_command") or "daily-roll useful-write liveness is stale",
        }
    if runtime.get("runtime_code_state") == "stale_code" and status_value in RUNNING_STATUSES and alive:
        return {
            **base,
            "state": "STALE_CODE",
            "action": "restart",
            "restart_cause": "superseded_code",
            "detail": runtime.get("detail"),
        }
    if status_value not in RUNNING_STATUSES:
        return {
            **base,
            "state": "DEAD",
            "action": "start",
            "restart_cause": status.get("root_cause_class") or status_value or "not_running",
            "detail": f"daily-roll status is {status_value or 'missing'}",
        }
    if not alive:
        return {
            **base,
            "state": "DEAD",
            "action": "start",
            "restart_cause": "pid_missing",
            "detail": "daily-roll process is not alive",
        }
    return {
        **base,
        "state": "RUNNING",
        "action": "noop",
        "restart_cause": None,
        "detail": "daily-roll process is current and useful-write liveness is passing",
    }


def stop_daily_roll_process(
    status: dict[str, Any] | None,
    *,
    target_date: str | None,
    pid_alive: Callable[..., bool] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    status = status or {}
    pid = status.get("pid")
    if not call_pid_alive(pid_alive, pid, target_date or status.get("target_date")):
        return {"stopped": False, "pid": pid, "reason": "no live matching daily-roll python process"}
    return terminate_python_pid(
        pid,
        pid_check=lambda candidate: call_pid_alive(pid_alive, candidate, target_date or status.get("target_date")),
    )


def _supervisor_status(result: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    keys = (
        "action",
        "intended_action",
        "state",
        "pid",
        "restart_cause",
        "detail",
        "reason",
        "target_date",
        "expected_target_date",
        "status_target_date",
        "start_time_gate",
        "runtime_identity_before",
        "current_runtime_identity",
        "runtime_identity_matches_current",
        "latest_useful_write",
        "recovery_guard",
        "stop",
        "loop_offsets_before",
        "loop_offsets_after",
    )
    payload = {key: result.get(key) for key in keys if key in result}
    payload["last_ensure_at_utc"] = utc_iso(now)
    return payload


def annotate_status_with_supervisor(
    status: dict[str, Any] | None,
    result: dict[str, Any],
    *,
    now: datetime,
    write_status_fn: Callable[[Path, dict[str, Any]], Any] | None,
    status_path: str | Path,
) -> dict[str, Any]:
    payload = dict(status or {})
    if not payload:
        return payload
    if payload.get("exists") is False and not payload.get("status"):
        return payload
    payload["daily_roll_supervisor"] = _supervisor_status(result, now=now)
    if result.get("restart_cause"):
        payload["supervisor_restart_cause"] = result.get("restart_cause")
        payload["supervisor_restart_at_utc"] = utc_iso(now)
        payload["supervisor_restart_action"] = result.get("action")
        payload["supervisor_latest_useful_write"] = result.get("latest_useful_write")
    if write_status_fn:
        write_status_fn(Path(status_path), payload)
    return payload


def append_daily_roll_diagnostic(path: str | Path, event: dict[str, Any]) -> Path:
    return append_jsonl(path, event)


def ensure_daily_roll(
    *,
    spec: SupervisorSpec,
    target_date: str,
    load_status_fn: Callable[[], dict[str, Any]],
    start_fn: Callable[..., dict[str, Any]],
    pid_alive: Callable[..., bool] | None,
    write_status_fn: Callable[[Path, dict[str, Any]], Any] | None,
    pid_stop_check: Callable[..., bool] | None = None,
    now: datetime | str | None = None,
    current_identity: dict[str, Any] | None = None,
    timezone_name: str = "America/Toronto",
    start_after_local_time: str | None = None,
    start_no_later_than_local_time: str | None = None,
    diagnostic_append_fn: Callable[[Path, dict[str, Any]], Any] = append_daily_roll_diagnostic,
) -> dict[str, Any]:
    current = parse_datetime(now) or utc_now()
    current_identity = current_identity or get_runtime_identity()
    pid_stop_check = pid_stop_check or pid_alive
    status = load_status_fn() or {}
    same_target = bool(status.get("target_date") == target_date)
    start_gate = local_time_gate(
        now=current,
        timezone_name=timezone_name,
        start_after_local_time=start_after_local_time,
        start_no_later_than_local_time=start_no_later_than_local_time,
    )
    if not same_target and not start_gate.get("allowed"):
        result = {
            "action": "scheduled_wait",
            "state": "SCHEDULED_WAIT",
            "pid": status.get("pid"),
            "target_date": status.get("target_date"),
            "expected_target_date": target_date,
            "restart_cause": None,
            "detail": "daily roll is outside its configured local launch window",
            "start_time_gate": start_gate,
            "runtime_identity_before": status.get("runtime_identity"),
            "current_runtime_identity": current_identity,
            "latest_useful_write": latest_useful_write(status),
        }
        annotate_status_with_supervisor(
            status,
            result,
            now=current,
            write_status_fn=write_status_fn,
            status_path=spec.status_path,
        )
        return result

    health = daily_roll_health(
        status,
        target_date=target_date,
        current_identity=current_identity,
        now=current,
        pid_alive=pid_alive,
    )
    action = health.get("action") or "noop"
    result = {
        "action": action,
        "state": health.get("state"),
        "pid": health.get("pid"),
        "restart_cause": health.get("restart_cause") if action in {"start", "restart"} else None,
        "detail": health.get("detail"),
        "target_date": target_date,
        "status_target_date": status.get("target_date"),
        "runtime_identity_before": status.get("runtime_identity"),
        "current_runtime_identity": current_identity,
        "runtime_identity_matches_current": health.get("runtime_identity_matches_current"),
        "latest_useful_write": health.get("latest_useful_write"),
        "start_time_gate": start_gate,
    }
    if action in {"start", "restart"} and not start_gate.get("allowed"):
        result["intended_action"] = action
        result["action"] = "scheduled_wait"
        result["state"] = "SCHEDULED_WAIT"
        result["reason"] = start_gate.get("reason")
        result["detail"] = "daily roll recovery is outside its configured local launch window"
        annotate_status_with_supervisor(
            status,
            result,
            now=current,
            write_status_fn=write_status_fn,
            status_path=spec.status_path,
        )
        return result
    guard = supervisor_recovery_guard(spec, action, now=current)
    result["recovery_guard"] = guard
    if action in {"start", "restart"}:
        result["loop_offsets_before"] = loop_file_offsets(spec)
    if action in {"start", "restart"} and not guard.get("allowed"):
        result["intended_action"] = action
        result["action"] = guard.get("action")
        result["reason"] = guard.get("reason")
        result["remediation"] = guard.get("remediation")
        event = {"time": current.isoformat(), "supervisor": "ensure", **result}
        if should_emit_recovery_block_diagnostic(spec, event):
            diagnostic_append_fn(spec.diagnostics_path, event)
        else:
            result["diagnostic_suppressed"] = True
        annotate_status_with_supervisor(
            status,
            result,
            now=current,
            write_status_fn=write_status_fn,
            status_path=spec.status_path,
        )
        return result

    if action == "restart":
        result["stop"] = stop_daily_roll_process(
            status,
            target_date=target_date,
            pid_alive=pid_stop_check,
            now=current,
        )
        result["start"] = start_fn(
            force=True,
            force_retire_latest_run=result.get("restart_cause") == "superseded_code",
        )
    elif action == "start":
        # A day-roll "start" (e.g. TARGET_MISMATCH at 00:05) previously left
        # yesterday's worker running: it leaked ~3GB/2h alongside the fresh
        # worker and recurred nightly (2026-06-30, 2026-07-04). Stop the
        # superseded worker, matched against ITS OWN target date, before
        # starting the new one; stop is a no-op when the pid is already dead.
        result["stop_superseded"] = stop_daily_roll_process(
            status,
            target_date=status.get("target_date"),
            pid_alive=pid_stop_check,
            now=current,
        )
        result["start"] = start_fn(force=True, force_retire_latest_run=False)

    final_status = None
    if action in {"start", "restart"}:
        result["loop_offsets_after"] = loop_file_offsets(spec)
        final_status = dict(result.get("start") or {})
        annotate_status_with_supervisor(
            final_status,
            result,
            now=current,
            write_status_fn=write_status_fn,
            status_path=spec.status_path,
        )
        diagnostic_append_fn(spec.diagnostics_path, {"time": current.isoformat(), "supervisor": "ensure", **result})
    elif action == "noop":
        annotate_status_with_supervisor(
            status,
            result,
            now=current,
            write_status_fn=write_status_fn,
            status_path=spec.status_path,
        )
    return result
