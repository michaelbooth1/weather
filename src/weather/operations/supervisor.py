from __future__ import annotations

import os
import json
import logging
import signal
import shlex
import select
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from weather.io import (
    acquire_writer_lock,
    append_jsonl as io_append_jsonl,
    file_lock_is_stale,
    read_json as io_read_json,
    release_writer_lock,
    write_json_atomic,
    writer_lock_path,
)
from weather.schema_registry import schema_version
from weather.time import age_minutes as time_age_minutes
from weather.time import age_seconds as time_age_seconds
from weather.time import parse_datetime


SleepFn = Callable[[float], None]
LOOP_SUPERVISOR_STATUS_SCHEMA_VERSION = schema_version("loop_supervisor_status")


class JsonLineLogFormatter(logging.Formatter):
    """Format Python logging records as one valid JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, default=str)


def configure_json_console_logging(stream=None, level=logging.INFO) -> None:
    """Route library logging to JSONL for managed loop console logs."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonLineLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.captureWarnings(True)


@dataclass(frozen=True)
class SupervisorSpec:
    """Static wiring for a managed background loop.

    Loop-specific modules own policy and status payload shape. This spec only
    records the mechanical paths and module entrypoint used by the shared
    supervisor primitives.
    """

    name: str
    module: str
    status_path: Path
    diagnostics_path: Path
    console_log_path: Path
    cwd: Path | None = None
    pause_flag_path: Path | None = None
    lock_path: Path | None = None
    tolerated_states: tuple[str, ...] = ("RUNNING", "PAUSED", "ERRORING")
    status_schema_fields: tuple[str, ...] = field(default_factory=tuple)
    restart_budget: int = 12
    restart_budget_window_hours: float = 24.0
    restart_backoff_base_seconds: float = 120.0
    restart_backoff_max_seconds: float = 3600.0
    # Minimum interval between benign current-code re-adoptions (stale_code /
    # runtime_identity). Benign re-adoptions are excluded from the crash budget,
    # so without this floor a burst of commits relaunches the loop every ensure
    # cadence -- repeatedly killing it mid-iteration and starving the markets at
    # the tail of the capture order. 0 disables the debounce.
    readoption_debounce_seconds: float = 900.0

    def command(self, *args: object, python_executable: str | None = None) -> list[str]:
        return build_module_command(self.module, *args, python_executable=python_executable)

    def with_paths(
        self,
        *,
        status_path: str | Path | None = None,
        diagnostics_path: str | Path | None = None,
        console_log_path: str | Path | None = None,
        pause_flag_path: str | Path | None = None,
        lock_path: str | Path | None = None,
    ) -> "SupervisorSpec":
        return SupervisorSpec(
            name=self.name,
            module=self.module,
            status_path=Path(status_path) if status_path is not None else self.status_path,
            diagnostics_path=Path(diagnostics_path) if diagnostics_path is not None else self.diagnostics_path,
            console_log_path=Path(console_log_path) if console_log_path is not None else self.console_log_path,
            cwd=self.cwd,
            pause_flag_path=Path(pause_flag_path) if pause_flag_path is not None else self.pause_flag_path,
            lock_path=Path(lock_path) if lock_path is not None else self.lock_path,
            tolerated_states=self.tolerated_states,
            status_schema_fields=self.status_schema_fields,
            restart_budget=self.restart_budget,
            restart_budget_window_hours=self.restart_budget_window_hours,
            restart_backoff_base_seconds=self.restart_backoff_base_seconds,
            restart_backoff_max_seconds=self.restart_backoff_max_seconds,
            readoption_debounce_seconds=self.readoption_debounce_seconds,
        )


def build_module_command(
    module: str,
    *args: object,
    python_executable: str | None = None,
) -> list[str]:
    return [python_executable or sys.executable, "-m", module, *[str(arg) for arg in args]]


def read_json_file(path: str | Path) -> Any | None:
    return io_read_json(path)


def atomic_write_json(
    path: str | Path,
    payload: Any,
    *,
    retries: int = 20,
    retry_sleep_seconds: float = 0.05,
    sleep_fn: SleepFn = time.sleep,
    trailing_newline: bool = False,
) -> Path:
    return write_json_atomic(
        path,
        payload,
        retries=retries,
        retry_sleep_seconds=retry_sleep_seconds,
        sleep_fn=sleep_fn,
        trailing_newline=trailing_newline,
    )


def append_jsonl(path: str | Path, payload: Any) -> Path:
    return io_append_jsonl(path, payload)


def read_writer_lock(status_path: str | Path) -> dict[str, Any]:
    path = writer_lock_path(status_path)
    if not path.exists():
        return {"exists": False, "path": str(path)}
    payload = io_read_json(path, default=None)
    if not isinstance(payload, dict):
        payload = {"pid": path.read_text(encoding="utf-8", errors="replace")}
    payload["exists"] = True
    payload["path"] = str(path)
    try:
        payload["age_seconds"] = round(time.time() - path.stat().st_mtime, 3)
    except FileNotFoundError:
        payload["age_seconds"] = None
    return payload


def loop_writer_lock_health(
    status_path: str | Path,
    *,
    status_pid: object,
    status_pid_alive: bool,
) -> dict[str, Any]:
    """Return whether the recorded worker owns a live single-writer lock.

    A generic live Python PID is not sufficient evidence that the recorded
    worker still exists: Windows can reuse a dead worker's PID for an unrelated
    Python process.  The long-running loop's writer lock is the second half of
    the identity check and must name the same PID.
    """

    lock = read_writer_lock(status_path)

    def _pid(value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    recorded_pid = _pid(status_pid)
    owner_pid = _pid(lock.get("pid"))
    owner_matches_status = bool(
        recorded_pid is not None
        and owner_pid is not None
        and recorded_pid == owner_pid
    )
    healthy = bool(lock.get("exists") and status_pid_alive and owner_matches_status)
    return {
        **lock,
        "status_pid": recorded_pid,
        "status_pid_alive": bool(status_pid_alive),
        "owner_pid": owner_pid,
        "owner_matches_status": owner_matches_status,
        "healthy": healthy,
        "reason": (
            "writer_lock_healthy"
            if healthy
            else "writer_lock_missing"
            if not lock.get("exists")
            else "recorded_pid_dead"
            if not status_pid_alive
            else "writer_lock_pid_missing"
            if owner_pid is None
            else "writer_lock_pid_mismatch"
        ),
    }


def attach_status_writer(status: dict[str, Any], lock: dict[str, Any] | None) -> dict[str, Any]:
    if lock and isinstance(status, dict):
        status["status_writer"] = {
            key: value
            for key, value in (lock.get("owner") or {}).items()
            if key != "handle"
        }
        status["status_writer"]["lock_path"] = lock.get("path")
    return status


def classify_malformed_jsonl_line(line: str, error: json.JSONDecodeError | None = None) -> str:
    text = str(line or "").strip()
    low = text.lower()
    if "\ufffd" in text:
        return "encoding_replacement"
    if text.startswith("{") or text.startswith("["):
        return "partial_json" if not (text.endswith("}") or text.endswith("]")) else "invalid_json"
    if (
        low.startswith(("traceback", "error", "warning", "info", "debug"))
        or ".py" in low
        or "exception" in low
    ):
        return "console_text"
    if error and "unterminated" in str(error).lower():
        return "partial_json"
    return "non_json_text"


def jsonl_integrity(path: str | Path, *, max_examples: int = 3) -> dict[str, Any]:
    path = Path(path)
    result = {
        "path": str(path),
        "exists": path.exists(),
        "line_count": 0,
        "valid_json_lines": 0,
        "malformed_lines": 0,
        "examples": [],
        "malformed_line_numbers": [],
        "classification_counts": {},
    }
    if not path.exists():
        return result
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            result["line_count"] += 1
            try:
                json.loads(line)
                result["valid_json_lines"] += 1
            except json.JSONDecodeError as exc:
                classification = classify_malformed_jsonl_line(line, exc)
                result["malformed_lines"] += 1
                result["malformed_line_numbers"].append(line_number)
                counts = result["classification_counts"]
                counts[classification] = int(counts.get(classification) or 0) + 1
                if len(result["examples"]) < max_examples:
                    result["examples"].append({
                        "line": line_number,
                        "error": str(exc),
                        "classification": classification,
                        "text": line[:200],
                    })
    result["ok"] = result["malformed_lines"] == 0
    return result


def quarantine_malformed_jsonl(path: str | Path, *, backup: bool = True) -> dict[str, Any]:
    """Rewrite a JSONL file with only valid lines and quarantine malformed ones."""
    path = Path(path)
    valid_lines: list[str] = []
    malformed: list[dict[str, Any]] = []
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "skipped": False,
            "valid_json_lines": 0,
            "malformed_lines": 0,
            "backup_path": None,
            "quarantine_path": None,
        }
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                json.loads(line)
                valid_lines.append(line)
            except json.JSONDecodeError as exc:
                malformed.append({
                    "line": line_number,
                    "classification": classify_malformed_jsonl_line(line, exc),
                    "error": str(exc),
                    "text": line,
                })
    backup_path = None
    quarantine_path = None
    if malformed:
        if backup:
            backup_path = path.with_suffix(path.suffix + ".malformed.bak")
            if not backup_path.exists():
                shutil.copy2(path, backup_path)
        quarantine_path = path.with_suffix(path.suffix + ".malformed.quarantine.jsonl")
        with quarantine_path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in malformed:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for line in valid_lines:
                handle.write(line + "\n")
    return {
        "path": str(path),
        "exists": True,
        "skipped": False,
        "valid_json_lines": len(valid_lines),
        "malformed_lines": len(malformed),
        "backup_path": str(backup_path) if backup_path else None,
        "quarantine_path": str(quarantine_path) if quarantine_path else None,
    }


def _file_offset(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    result = {"path": str(path), "exists": path.exists(), "size_bytes": 0, "line_count": 0}
    if not path.exists():
        return result
    try:
        result["size_bytes"] = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            result["line_count"] = sum(1 for _line in handle)
    except OSError as exc:
        result["error"] = str(exc)
    return result


def loop_file_offsets(spec: SupervisorSpec) -> dict[str, Any]:
    return {
        "status": _file_offset(spec.status_path),
        "diagnostics": _file_offset(spec.diagnostics_path),
        "console": _file_offset(spec.console_log_path),
    }


def quarantine_malformed_loop_lines(
    spec: SupervisorSpec,
    *,
    backup: bool = True,
    allow_active: bool = False,
) -> dict[str, Any]:
    lock = read_writer_lock(spec.status_path)
    pid = lock.get("pid")
    active_writer = bool(lock.get("exists") and pid_is_python(pid))
    if active_writer and not allow_active:
        return {
            "skipped": True,
            "reason": "active_writer_lock",
            "active_writer": {
                "pid": pid,
                "lock_path": lock.get("path"),
                "status_path": str(spec.status_path),
            },
            "files": [],
        }
    files = []
    for path in (spec.diagnostics_path, spec.console_log_path):
        integrity = jsonl_integrity(path)
        if int(integrity.get("malformed_lines") or 0):
            repaired = quarantine_malformed_jsonl(path, backup=backup)
            repaired["before"] = integrity
            files.append(repaired)
    return {
        "skipped": False,
        "reason": None,
        "active_writer": {"pid": pid, "lock_path": lock.get("path"), "status_path": str(spec.status_path)},
        "files": files,
        "malformed_lines": sum(int(row.get("malformed_lines") or 0) for row in files),
    }


def _event_time(event: dict[str, Any]) -> datetime | None:
    for key in ("time", "timestamp", "created_at_utc", "captured_at_utc"):
        parsed = parse_iso_datetime(event.get(key))
        if parsed is not None:
            return parsed.astimezone(timezone.utc)
    return None


# Restart causes that are benign current-code re-adoption rather than crash
# recovery. These must not consume the crash circuit-breaker budget. When code is
# committed, every running collection loop detects that its process identity
# differs from the source tree, exits cleanly, and is relaunched on current code.
# Counting those clean re-adoptions as crash restarts means a normal burst of
# commits exhausts the small restart budget, trips the breaker, and leaves
# collection dark for the whole 24h window -- the root cause of the 2026-06-24/25
# snapshot outages (capture ratio 0.51, 8.5h gap). The supervisor's own ensure
# cadence still bounds how often a stale-code relaunch can occur.
#
# Different loops label this same benign re-adoption differently: the snapshot
# loop uses health state "stale_code", while the CLOB/microstructure loop uses
# "runtime_identity" (set when runtime_matches_current is False). Both mean the
# loop is being relaunched on current code, not crash-looping, so both are benign.
# "superseded_code" is the daily-roll supervisor's name for the same condition.
# "policy_no_edge" and "infra_starved_*" recycle a worker that is alive and
# correctly idle (no tradable edge, or upstream snapshot/CLOB inputs stale) —
# restarting cannot manufacture edge or repair upstream inputs, so those
# recycles must not burn the crash budget: on 2026-07-03/04/05 they exhausted
# the 12-restart budget by midday and opened the taker circuit every day.
_BENIGN_RESTART_CAUSES = {
    "stale_code",
    "runtime_identity",
    "superseded_code",
    "policy_no_edge",
}
_BENIGN_RESTART_CAUSE_PREFIXES = ("infra_starved",)


def _recovery_event(event: dict[str, Any]) -> bool:
    if str(event.get("supervisor") or "").lower() != "ensure":
        return False
    if str(event.get("action") or "").lower() not in {"start", "restart"}:
        return False
    cause = str(event.get("restart_cause") or "").lower()
    if cause in _BENIGN_RESTART_CAUSES:
        return False
    if cause.startswith(_BENIGN_RESTART_CAUSE_PREFIXES):
        return False
    return True


def readoption_debounce(
    *,
    runtime_code_state: object,
    process_started_at: object,
    now: datetime,
    debounce_seconds: float,
) -> dict[str, Any]:
    """Rate-limit benign current-code re-adoption.

    Benign re-adoptions (relaunching a healthy loop onto current code after a
    commit) are excluded from the crash budget by :func:`_recovery_event`, so
    they carry no backoff. Without a floor, a burst of commits relaunches the
    loop every ensure cadence (1-2 min) -- each relaunch hard-kills the loop
    mid-iteration and restarts the capture cycle from the top, so the markets at
    the tail of the order never get reached and silently starve.

    A re-adoption is held when the running process itself re-adopted (started)
    more recently than ``debounce_seconds`` ago, so the loop re-adopts at most
    once per window and always runs at least one capture cycle to completion
    before being relaunched. Genuine crash/hang restarts (non-benign causes) are
    never debounced -- they fall through immediately.
    """
    state = str(runtime_code_state or "").lower()
    if state not in _BENIGN_RESTART_CAUSES:
        return {"debounced": False, "reason": "not_benign_readoption"}
    if not debounce_seconds or float(debounce_seconds) <= 0:
        return {"debounced": False, "reason": "debounce_disabled"}
    age = age_seconds(now, process_started_at)
    if age is None:
        return {"debounced": False, "reason": "no_process_start_time"}
    debounce_seconds = float(debounce_seconds)
    if age >= debounce_seconds:
        return {
            "debounced": False,
            "reason": "debounce_window_elapsed",
            "process_age_seconds": round(age, 1),
            "debounce_seconds": debounce_seconds,
        }
    return {
        "debounced": True,
        "reason": "readoption_debounced",
        "process_age_seconds": round(age, 1),
        "debounce_seconds": debounce_seconds,
        "retry_after_seconds": round(debounce_seconds - age, 1),
    }


def _looks_like_recovery_event_line(line: str) -> bool:
    text = str(line or "").lower()
    return (
        '"supervisor"' in text
        and '"ensure"' in text
        and '"action"' in text
        and ('"start"' in text or '"restart"' in text)
    )


def recent_recovery_events(
    diagnostics_path: str | Path,
    *,
    now: datetime,
    window_hours: float,
) -> list[dict[str, Any]]:
    diagnostics_path = Path(diagnostics_path)
    if not diagnostics_path.exists():
        return []
    now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    window_start = now_utc - timedelta(hours=float(window_hours))
    events: list[dict[str, Any]] = []
    with diagnostics_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            if not _looks_like_recovery_event_line(line):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or not _recovery_event(event):
                continue
            event_time = _event_time(event)
            if event_time is None or event_time < window_start:
                continue
            events.append({"line": line_number, "time": event_time, "event": event})
    return events


def supervisor_recovery_guard(
    spec: SupervisorSpec,
    action: str,
    *,
    now: datetime,
) -> dict[str, Any]:
    action = str(action or "").lower()
    if action not in {"start", "restart"}:
        return {"allowed": True, "action": action, "reason": "not_recovery_action"}
    now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    events = recent_recovery_events(
        spec.diagnostics_path,
        now=now_utc,
        window_hours=spec.restart_budget_window_hours,
    )
    count = len(events)
    budget = int(spec.restart_budget)
    event_times = [row["time"] for row in events if row.get("time")]
    last = max(event_times) if event_times else None
    backoff_seconds = 0.0
    retry_at = None
    retry_after = 0.0
    if count > 0:
        backoff_seconds = min(
            float(spec.restart_backoff_max_seconds),
            float(spec.restart_backoff_base_seconds) * (2 ** max(0, count - 1)),
        )
    if last is not None and backoff_seconds > 0:
        retry_at = last + timedelta(seconds=backoff_seconds)
        retry_after = max(0.0, (retry_at - now_utc).total_seconds())
    base = {
        "loop": spec.name,
        "requested_action": action,
        "recent_recovery_count": count,
        "restart_budget": budget,
        "restart_budget_window_hours": float(spec.restart_budget_window_hours),
        "backoff_seconds": round(backoff_seconds, 3),
        "last_recovery_at_utc": last.isoformat() if last else None,
        "retry_at_utc": retry_at.isoformat() if retry_at else None,
        "retry_after_seconds": round(retry_after, 3),
    }
    if count >= budget:
        return {
            **base,
            "allowed": False,
            "action": "circuit_open",
            "reason": f"restart_budget_exceeded={count}>={budget}",
            "remediation": "inspect the loop diagnostics and console log, fix the root cause, then run an explicit restart",
        }
    if retry_after > 0:
        return {
            **base,
            "allowed": False,
            "action": "backoff",
            "reason": f"restart_backoff_active={round(retry_after, 1)}s",
            "remediation": "wait for the supervisor backoff window or inspect the loop diagnostics before manual restart",
        }
    return {**base, "allowed": True, "action": action, "reason": "within_restart_budget"}


def supervisor_status_path(spec: SupervisorSpec) -> Path:
    """Return the sidecar that owns the latest short-lived ensure decision."""

    status_path = Path(spec.status_path)
    stem = status_path.stem
    owner_stem = stem[: -len("_status")] if stem.endswith("_status") else stem
    return status_path.with_name(f"{owner_stem}_supervisor_status.json")


def read_supervisor_status(spec: SupervisorSpec) -> dict[str, Any]:
    payload = read_json_file(supervisor_status_path(spec))
    return payload if isinstance(payload, dict) else {}


def ensure_exit_code(result: dict[str, Any] | None) -> int:
    """Map an ensure result to the scheduled task's fail-closed exit code."""

    result = result if isinstance(result, dict) else {}
    action = str(result.get("action") or "").lower()
    if action == "noop":
        writer = result.get("writer_lock")
        if isinstance(writer, dict) and writer.get("healthy") is False:
            return 1
        return 0
    if action in {"start", "restart"}:
        start = result.get("start")
        return 0 if isinstance(start, dict) and start.get("started") is True else 1
    return 1


def managed_stop_allows_start(result: object) -> bool:
    """Return whether a stop proved replacement launch cannot duplicate a loop."""

    if not isinstance(result, dict):
        return False
    if result.get("stopped") is True:
        return True
    authorization = result.get("authorization")
    return bool(isinstance(authorization, dict) and authorization.get("process_gone") is True)


def persist_supervisor_status(
    spec: SupervisorSpec,
    result: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Persist and return one inspectable ensure decision.

    The loop status remains single-writer-owned by the long-running worker.
    Supervisors therefore publish their circuit/backoff decision to a separate
    atomic sidecar that status and fleet observability can read without racing
    capture heartbeats.
    """

    exit_code = ensure_exit_code(result)
    action = str(result.get("action") or "").lower()
    if exit_code == 0:
        ensure_status = "OK"
    elif action in {"locked", "backoff", "circuit_open", "restart_blocked"}:
        ensure_status = "BLOCKED"
    else:
        ensure_status = "FAILED"
    path = supervisor_status_path(spec)
    payload = {
        **result,
        "schema_version": LOOP_SUPERVISOR_STATUS_SCHEMA_VERSION,
        "loop": spec.name,
        "updated_at_utc": now.astimezone(timezone.utc).isoformat() if now.tzinfo else now.replace(tzinfo=timezone.utc).isoformat(),
        "ensure_status": ensure_status,
        "exit_code": exit_code,
        "supervisor_status_path": str(path),
    }
    atomic_write_json(path, payload)
    return payload


def _tail_text_lines(path: str | Path, *, max_bytes: int = 1_000_000) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            start = max(0, size - int(max_bytes))
            handle.seek(start)
            if start:
                handle.readline()
            return handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def recovery_block_diagnostic_key(event: dict[str, Any]) -> tuple[Any, ...] | None:
    guard = event.get("recovery_guard") or {}
    action = str(event.get("action") or guard.get("action") or "").lower()
    if action != "circuit_open":
        return None
    return (
        action,
        guard.get("loop"),
        event.get("intended_action") or guard.get("requested_action"),
        guard.get("last_recovery_at_utc"),
        guard.get("restart_budget"),
        guard.get("restart_budget_window_hours"),
        event.get("remediation") or guard.get("remediation"),
    )


def should_emit_recovery_block_diagnostic(
    spec: SupervisorSpec,
    event: dict[str, Any],
    *,
    max_scan_bytes: int = 1_000_000,
) -> bool:
    """Coalesce repeated circuit-open ensure diagnostics for one breaker trip."""
    key = recovery_block_diagnostic_key(event)
    if key is None:
        return True
    for line in reversed(_tail_text_lines(spec.diagnostics_path, max_bytes=max_scan_bytes)):
        if '"circuit_open"' not in line or '"action"' not in line:
            continue
        try:
            previous = json.loads(line)
        except json.JSONDecodeError:
            continue
        if recovery_block_diagnostic_key(previous) == key:
            return False
    return True


def parse_iso_datetime(value: object, *, default_tz=timezone.utc) -> datetime | None:
    return parse_datetime(value, default_tz=default_tz)


def age_seconds(now: datetime, iso_value: object, *, default_tz=timezone.utc) -> float | None:
    return time_age_seconds(now, iso_value, default_tz=default_tz)


def age_minutes(now: datetime, iso_value: object, *, default_tz=timezone.utc) -> float | None:
    return time_age_minutes(now, iso_value, default_tz=default_tz)


def heartbeat_state(
    status: dict[str, Any] | None,
    now: datetime,
    *,
    interval_seconds: float,
    dead_after_seconds: float,
    heartbeat_field: str = "last_heartbeat",
    paused_field: str = "paused",
    error_field: str = "consecutive_errors",
    error_threshold: int = 3,
    default_tz=timezone.utc,
) -> dict[str, Any]:
    if not status:
        return {"state": "UNKNOWN", "heartbeat_age_seconds": None, "consecutive_errors": 0}
    heartbeat_age = age_seconds(now, status.get(heartbeat_field), default_tz=default_tz)
    errors = int(status.get(error_field) or 0)
    if status.get(paused_field):
        state = "PAUSED"
    elif heartbeat_age is None or heartbeat_age > dead_after_seconds:
        state = "DEAD"
    elif errors >= error_threshold:
        state = "ERRORING"
    else:
        state = "RUNNING"
    return {
        "state": state,
        "heartbeat_age_seconds": heartbeat_age,
        "consecutive_errors": errors,
        "interval_seconds": float(interval_seconds),
        "dead_after_seconds": float(dead_after_seconds),
    }


def default_ensure_decision(
    health_state: str,
    pid_alive: bool,
    *,
    tolerated_states: Iterable[str] = ("RUNNING", "PAUSED", "ERRORING"),
) -> str:
    if health_state in set(tolerated_states):
        return "noop"
    if pid_alive:
        return "restart"
    return "start"


def process_query_creationflags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def detached_creationflags() -> int:
    if os.name != "nt":
        return 0
    return subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP


def windows_process_image_path(pid: int) -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        query_image_name = kernel32.QueryFullProcessImageNameW
        query_image_name.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        query_image_name.restype = wintypes.BOOL
        handle = open_process(0x1000, False, int(pid))
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not query_image_name(handle, 0, buffer, ctypes.byref(size)):
                return ""
            return buffer.value
        finally:
            close_handle(handle)
    except (OSError, TypeError, ValueError):
        return ""


def pid_is_python(pid: object, *, run_fn: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool:
    if not pid:
        return False
    try:
        normalized = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt" and run_fn is subprocess.run:
        return "python" in Path(windows_process_image_path(normalized)).name.lower()
    if os.name == "nt":
        command = ["tasklist", "/FI", f"PID eq {normalized}", "/FO", "CSV", "/NH"]
    else:
        command = ["ps", "-p", str(normalized), "-o", "comm="]
    try:
        result = run_fn(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=process_query_creationflags(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "python" in (result.stdout or "").lower()


def _normalized_pid(value: object) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _windows_command_argv(command_line: str) -> list[str] | None:
    try:
        import ctypes
        from ctypes import wintypes

        argc = ctypes.c_int()
        command_line_to_argv = ctypes.windll.shell32.CommandLineToArgvW
        command_line_to_argv.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        command_line_to_argv.restype = ctypes.POINTER(wintypes.LPWSTR)
        argv = command_line_to_argv(str(command_line), ctypes.byref(argc))
        if not argv:
            return None
        try:
            return [argv[index] for index in range(argc.value)]
        finally:
            ctypes.windll.kernel32.LocalFree(argv)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def command_line_argv(command_line: object) -> list[str] | None:
    text = str(command_line or "").strip()
    if not text:
        return None
    if os.name == "nt":
        return _windows_command_argv(text)
    try:
        return shlex.split(text)
    except ValueError:
        return None


def _normalized_executable(value: object) -> str:
    text = os.path.expandvars(str(value or "").strip().strip('"'))
    if not text:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(text)))


def _trusted_windows_venv_base_resolution(
    observed_executable: object,
    expected_executable: object,
) -> bool:
    """Accept only this runtime's exact venv-launcher to base-exe redirect.

    Windows venv ``python.exe``/``pythonw.exe`` files are redirector launchers.
    The child PEB can therefore report the matching base interpreter as
    ``argv[0]`` even though ``Popen`` received the venv path.  ``sys.prefix``
    and ``sys.base_prefix`` are interpreter-owned evidence for that one pair;
    unrelated venvs, Python installs, or executable flavors remain mismatches.
    """

    if os.name != "nt" or sys.prefix == sys.base_prefix:
        return False
    expected_name = Path(str(expected_executable or "").strip().strip('"')).name.lower()
    observed_name = Path(str(observed_executable or "").strip().strip('"')).name.lower()
    if expected_name not in {"python.exe", "pythonw.exe"}:
        return False
    if observed_name != expected_name:
        return False
    expected_launcher = Path(sys.prefix) / "Scripts" / expected_name
    resolved_base = Path(sys.base_prefix) / expected_name
    if not expected_launcher.is_file() or not resolved_base.is_file():
        return False
    return bool(
        _normalized_executable(expected_executable)
        == _normalized_executable(expected_launcher)
        and _normalized_executable(observed_executable)
        == _normalized_executable(resolved_base)
    )


def commands_match_exact(observed: Sequence[object] | None, expected: Sequence[object] | None) -> bool:
    """Compare complete managed argv, including the interpreter and every flag."""

    observed_values = [str(value) for value in observed or []]
    expected_values = [str(value) for value in expected or []]
    if not observed_values or len(observed_values) != len(expected_values):
        return False
    executable_matches = (
        _normalized_executable(observed_values[0])
        == _normalized_executable(expected_values[0])
    )
    if not executable_matches and not _trusted_windows_venv_base_resolution(
        observed_values[0],
        expected_values[0],
    ):
        return False
    return observed_values[1:] == expected_values[1:]


def observe_process(pid: object) -> dict[str, Any]:
    """Return tri-state command and OS creation-token evidence for one PID.

    ``not_found`` is affirmative absence. ``unknown`` is deliberately distinct:
    an access or inspection failure must never authorize destructive recovery.
    """

    normalized = _normalized_pid(pid)
    if normalized is None:
        return {"state": "unknown", "pid": pid, "reason": "invalid_pid"}
    if os.name == "nt":
        try:
            from weather.operations.windows_processes import describe_process, snapshot_processes

            table = snapshot_processes()
            if table is None:
                return {
                    "state": "unknown",
                    "pid": normalized,
                    "reason": "Windows process snapshot unavailable",
                }
            if normalized not in table:
                return {"state": "not_found", "pid": normalized}
            detail = describe_process(normalized, table)
        except (OSError, TypeError, ValueError) as exc:
            return {"state": "unknown", "pid": normalized, "reason": str(exc)}
        command_line = detail.get("command_line")
        creation_token = detail.get("creation_time_token")
        return {
            "state": "running",
            "pid": normalized,
            "parent_pid": detail.get("parent_pid"),
            "image_path": detail.get("image_path"),
            "command_line": command_line,
            "argv": command_line_argv(command_line),
            "creation_time_token": creation_token,
            "inspectable": bool(command_line and creation_token),
        }

    proc_root = Path("/proc") / str(normalized)
    if Path("/proc").is_dir():
        try:
            raw_stat = (proc_root / "stat").read_text(encoding="utf-8")
            command_bytes = (proc_root / "cmdline").read_bytes()
        except FileNotFoundError:
            return {"state": "not_found", "pid": normalized}
        except OSError as exc:
            return {"state": "unknown", "pid": normalized, "reason": str(exc)}
        closing_paren = raw_stat.rfind(")")
        fields = raw_stat[closing_paren + 2 :].split() if closing_paren >= 0 else []
        start_ticks = fields[19] if len(fields) > 19 else None
        argv = [
            value.decode("utf-8", errors="replace")
            for value in command_bytes.split(b"\0")
            if value
        ]
        return {
            "state": "running",
            "pid": normalized,
            "command_line": shlex.join(argv) if argv else None,
            "argv": argv or None,
            "creation_time_token": f"proc-start-ticks:{start_ticks}" if start_ticks else None,
            "inspectable": bool(argv and start_ticks),
        }
    return {
        "state": "unknown",
        "pid": normalized,
        "reason": "OS process creation token is unavailable",
    }


def capture_managed_process_identity(
    pid: object,
    expected_command: Sequence[object],
    *,
    observe_fn: Callable[[object], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Capture PID-reuse-resistant provenance to persist in status and lock."""

    normalized = _normalized_pid(pid)
    expected = [str(value) for value in expected_command]
    observe_fn = observe_fn or observe_process
    observation = observe_fn(normalized)
    identity = {
        "pid": normalized,
        "expected_command": expected,
        "creation_time_token": observation.get("creation_time_token"),
        "command_line": observation.get("command_line"),
        "observed_executable": (
            str(observation["argv"][0])
            if observation.get("argv")
            else None
        ),
        "observed_image_path": observation.get("image_path"),
        "captured_state": observation.get("state"),
    }
    identity["verified_at_capture"] = bool(
        observation.get("state") == "running"
        and observation.get("creation_time_token")
        and commands_match_exact(observation.get("argv"), expected)
    )
    return identity


def managed_stop_expected_command(
    status: object,
    canonical_command: Sequence[object],
) -> list[str]:
    """Expected argv for stop/restart authorization of a managed worker.

    Scheduled supervisors launch workers with the venv ``pythonw.exe``, while
    operator stop verbs usually run under the console ``python.exe``;
    ``sys.executable``-built expectations therefore carry an argv[0] the exact
    matcher rightly refuses (2026-07-17 training window: all three loops
    survived their stop verbs and retrain never started). Adopt the recorded
    ``managed_process.expected_command`` only when it differs from the
    canonical command by a same-directory python/pythonw sibling interpreter
    and matches every other argument exactly; any other difference falls back
    to the canonical command, which fails closed downstream.
    """

    canonical = [str(value) for value in canonical_command]
    identity = (status or {}).get("managed_process") if isinstance(status, dict) else None
    recorded = identity.get("expected_command") if isinstance(identity, dict) else None
    if not recorded:
        return canonical
    recorded = [str(value) for value in recorded]
    if len(recorded) != len(canonical) or recorded[1:] != canonical[1:]:
        return canonical
    siblings = {"python.exe", "pythonw.exe"}
    recorded_path = Path(recorded[0].strip().strip('"'))
    canonical_path = Path(canonical[0].strip().strip('"'))
    if (
        recorded_path.name.lower() in siblings
        and canonical_path.name.lower() in siblings
        and _normalized_executable(recorded_path.parent)
        == _normalized_executable(canonical_path.parent)
    ):
        return recorded
    return canonical


def _managed_identity_matches_expected(
    identity: object,
    *,
    pid: int,
    expected_command: Sequence[object],
) -> bool:
    return bool(
        isinstance(identity, dict)
        and _normalized_pid(identity.get("pid")) == pid
        and identity.get("creation_time_token")
        and commands_match_exact(identity.get("expected_command"), expected_command)
    )


def managed_process_matches(
    identity: object,
    expected_command: Sequence[object],
    *,
    observe_fn: Callable[[object], dict[str, Any]] | None = None,
) -> bool:
    """Re-observe and exactly match the recorded process immediately pre-kill."""

    if not isinstance(identity, dict):
        return False
    observe_fn = observe_fn or observe_process
    pid = _normalized_pid(identity.get("pid"))
    if pid is None or not _managed_identity_matches_expected(
        identity,
        pid=pid,
        expected_command=expected_command,
    ):
        return False
    observation = observe_fn(pid)
    return bool(
        observation.get("state") == "running"
        and observation.get("creation_time_token") == identity.get("creation_time_token")
        and commands_match_exact(observation.get("argv"), expected_command)
    )


def authorize_managed_process_termination(
    status: object,
    writer_lock: object,
    expected_command: Sequence[object],
    *,
    observe_fn: Callable[[object], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Authorize a kill only for the exact status/lock/OS process instance."""

    status = status if isinstance(status, dict) else {}
    writer_lock = writer_lock if isinstance(writer_lock, dict) else {}
    observe_fn = observe_fn or observe_process
    pid = _normalized_pid(status.get("pid"))
    if pid is None:
        return {"authorized": False, "process_gone": False, "reason": "status_pid_unknown", "pid": status.get("pid")}

    if writer_lock.get("exists"):
        owner_pid = _normalized_pid(writer_lock.get("pid"))
        if owner_pid is None:
            return {"authorized": False, "process_gone": False, "reason": "writer_lock_owner_unknown", "pid": pid}
        if owner_pid != pid:
            owner_observation = observe_fn(owner_pid)
            if owner_observation.get("state") != "not_found":
                return {
                    "authorized": False,
                    "process_gone": False,
                    "reason": "mismatched_writer_lock_owner_is_authoritative",
                    "pid": pid,
                    "writer_lock_owner_pid": owner_pid,
                    "writer_lock_owner_observation": owner_observation,
                }

    identity = status.get("managed_process")
    if not _managed_identity_matches_expected(identity, pid=pid, expected_command=expected_command):
        return {"authorized": False, "process_gone": False, "reason": "managed_process_provenance_missing_or_mismatched", "pid": pid}

    if writer_lock.get("exists") and _normalized_pid(writer_lock.get("pid")) == pid:
        lock_identity = writer_lock.get("managed_process")
        if not _managed_identity_matches_expected(lock_identity, pid=pid, expected_command=expected_command):
            return {"authorized": False, "process_gone": False, "reason": "writer_lock_process_provenance_missing_or_mismatched", "pid": pid}
        if lock_identity.get("creation_time_token") != identity.get("creation_time_token"):
            return {"authorized": False, "process_gone": False, "reason": "writer_lock_process_instance_mismatch", "pid": pid}

    observation = observe_fn(pid)
    if observation.get("state") == "not_found":
        return {
            "authorized": False,
            "process_gone": True,
            "reason": "recorded_process_not_found",
            "pid": pid,
            "managed_process": identity,
            "observation": observation,
        }
    if observation.get("state") != "running" or not observation.get("inspectable"):
        return {
            "authorized": False,
            "process_gone": False,
            "reason": "live_process_identity_uninspectable",
            "pid": pid,
            "managed_process": identity,
            "observation": observation,
        }
    if observation.get("creation_time_token") != identity.get("creation_time_token"):
        return {
            "authorized": False,
            "process_gone": False,
            "reason": "reused_pid_process_instance_mismatch",
            "pid": pid,
            "managed_process": identity,
            "observation": observation,
        }
    if not commands_match_exact(observation.get("argv"), expected_command):
        return {
            "authorized": False,
            "process_gone": False,
            "reason": "managed_process_command_mismatch",
            "pid": pid,
            "managed_process": identity,
            "observation": observation,
        }
    return {
        "authorized": True,
        "process_gone": False,
        "reason": "exact_managed_process_confirmed",
        "pid": pid,
        "managed_process": identity,
        "observation": observation,
    }


def authorize_writer_lock_removal(
    writer_lock: object,
    *,
    expected_pid: object = None,
    confirmed_exit: object = None,
    exited_identity: object = None,
    observe_fn: Callable[[object], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Authorize unlink only after owner absence or exact-instance exit proof."""

    writer_lock = writer_lock if isinstance(writer_lock, dict) else {}
    owner_pid = _normalized_pid(writer_lock.get("pid"))
    expected = _normalized_pid(expected_pid)
    if owner_pid is None:
        return {"authorized": False, "reason": "writer_lock_owner_unknown", "pid": writer_lock.get("pid")}

    if expected is not None and owner_pid == expected:
        if not (
            isinstance(confirmed_exit, dict)
            and confirmed_exit.get("exited") is True
            and isinstance(exited_identity, dict)
        ):
            return {"authorized": False, "reason": "writer_lock_owner_exit_not_proven", "pid": owner_pid}
        exited_token = exited_identity.get("creation_time_token")
        lock_identity = writer_lock.get("managed_process")
        lock_token = lock_identity.get("creation_time_token") if isinstance(lock_identity, dict) else None
        if not exited_token or lock_token != exited_token:
            return {
                "authorized": False,
                "reason": "writer_lock_process_instance_mismatch",
                "pid": owner_pid,
                "exited_creation_time_token": exited_token,
                "lock_creation_time_token": lock_token,
            }
        return {"authorized": True, "reason": "exact_managed_writer_exited", "pid": owner_pid}

    observe_fn = observe_fn or observe_process
    observation = observe_fn(owner_pid)
    if observation.get("state") == "not_found":
        return {
            "authorized": True,
            "reason": "writer_lock_owner_absence_proven",
            "pid": owner_pid,
            "observation": observation,
        }
    return {
        "authorized": False,
        "reason": "writer_lock_owner_not_proven_dead",
        "pid": owner_pid,
        "observation": observation,
    }


def wait_for_managed_process_exit(
    identity: object,
    *,
    observe_fn: Callable[[object], dict[str, Any]] | None = None,
    attempts: int = 20,
    sleep_seconds: float = 0.1,
    sleep_fn: SleepFn = time.sleep,
) -> dict[str, Any]:
    """Prove the recorded OS process instance is gone before lock cleanup."""

    if not isinstance(identity, dict) or _normalized_pid(identity.get("pid")) is None:
        return {"exited": False, "reason": "managed_process_provenance_missing"}
    observe_fn = observe_fn or observe_process
    pid = int(identity["pid"])
    token = identity.get("creation_time_token")
    if not token:
        return {"exited": False, "reason": "process_creation_token_missing", "pid": pid}
    last_observation = None
    for attempt in range(max(1, int(attempts))):
        last_observation = observe_fn(pid)
        if last_observation.get("state") == "not_found":
            return {"exited": True, "reason": "process_not_found", "pid": pid, "observation": last_observation}
        observed_token = last_observation.get("creation_time_token")
        if last_observation.get("state") == "running" and observed_token and observed_token != token:
            return {"exited": True, "reason": "pid_reused_after_managed_exit", "pid": pid, "observation": last_observation}
        if attempt + 1 < max(1, int(attempts)):
            sleep_fn(float(sleep_seconds))
    return {
        "exited": False,
        "reason": "managed_process_exit_not_observed",
        "pid": pid,
        "observation": last_observation,
    }


def terminate_managed_process(
    identity: object,
    expected_command: Sequence[object],
    *,
    observe_fn: Callable[[object], dict[str, Any]] | None = None,
    windows_terminate_fn: Callable[..., dict[str, Any]] | None = None,
    signal_number: int = signal.SIGTERM,
) -> dict[str, Any]:
    """Terminate the verified instance through a PID-reuse-safe OS handle."""

    if not isinstance(identity, dict):
        return {"stopped": False, "reason": "managed_process_provenance_missing"}
    pid = _normalized_pid(identity.get("pid"))
    token = identity.get("creation_time_token")
    if pid is None or not token or not _managed_identity_matches_expected(
        identity,
        pid=pid,
        expected_command=expected_command,
    ):
        return {"pid": pid, "stopped": False, "reason": "managed_process_provenance_missing_or_mismatched"}

    if os.name == "nt":
        if windows_terminate_fn is None:
            from weather.operations.windows_processes import terminate_verified_process

            windows_terminate_fn = terminate_verified_process
        return windows_terminate_fn(
            pid,
            expected_creation_time_token=str(token),
            command_line_check=lambda command_line: commands_match_exact(
                command_line_argv(command_line),
                expected_command,
            ),
            exit_code=int(signal_number),
        )

    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return {
            "pid": pid,
            "stopped": False,
            "reason": "handle-scoped process termination is unavailable",
        }
    observe_fn = observe_fn or observe_process
    try:
        pidfd = os.pidfd_open(pid)
    except OSError as exc:
        return {"pid": pid, "stopped": False, "reason": str(exc)}
    try:
        observation = observe_fn(pid)
        if not (
            observation.get("state") == "running"
            and observation.get("creation_time_token") == token
            and commands_match_exact(observation.get("argv"), expected_command)
        ):
            return {"pid": pid, "stopped": False, "reason": "process changed before handle-scoped termination"}
        signal.pidfd_send_signal(pidfd, signal_number)
        poller = select.poll()
        poller.register(pidfd, select.POLLIN)
        exited = bool(poller.poll(2000))
    except OSError as exc:
        return {"pid": pid, "stopped": False, "reason": str(exc)}
    finally:
        os.close(pidfd)
    return {
        "pid": pid,
        "stopped": exited,
        "termination_requested": True,
        "termination_scope": "verified_pidfd",
        "creation_time_token": token,
        "exited": exited,
        "reason": "verified_process_exited" if exited else "verified_process_exit_not_observed",
    }


def terminate_python_pid(
    pid: object,
    *,
    pid_check: Callable[[object], bool] = pid_is_python,
    kill_fn: Callable[[int, int], None] = os.kill,
    signal_number: int = signal.SIGTERM,
) -> dict[str, Any]:
    if not pid_check(pid):
        return {"pid": pid, "stopped": False, "reason": "pid is not a live python process"}
    try:
        normalized = int(pid)
        kill_fn(normalized, signal_number)
    except (OSError, ValueError) as exc:
        return {"pid": pid, "stopped": False, "reason": str(exc)}
    return {"pid": normalized, "stopped": True}


def launch_detached(
    command: Sequence[object],
    *,
    cwd: str | Path | None,
    console_log_path: str | Path,
    popen_fn: Callable[..., Any] = subprocess.Popen,
    creationflags: int | None = None,
) -> Any:
    log_path = Path(console_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("a", encoding="utf-8")
    try:
        return popen_fn(
            [str(item) for item in command],
            cwd=str(cwd) if cwd is not None else None,
            stdout=log_handle,
            stderr=log_handle,
            creationflags=detached_creationflags() if creationflags is None else creationflags,
        )
    finally:
        log_handle.close()


def _file_lock_owner_pid(path: str | Path) -> int | None:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except FileNotFoundError:
        return None
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return int(payload.get("pid"))
    except (TypeError, ValueError):
        return None


def file_lock_owner_is_dead(
    path: str | Path,
    *,
    pid_check: Callable[[object], bool] = pid_is_python,
) -> bool:
    pid = _file_lock_owner_pid(path)
    return pid is not None and not pid_check(pid)


def _create_file_lock(path: Path) -> int:
    handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(handle, str(os.getpid()).encode("ascii"))
    return handle


def acquire_file_lock(
    path: str | Path,
    *,
    attempts: int = 1,
    stale_after_seconds: float = 120.0,
    sleep_seconds: float = 0.1,
    sleep_fn: SleepFn = time.sleep,
    pid_check: Callable[[object], bool] = pid_is_python,
) -> int | None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        try:
            return _create_file_lock(path)
        except FileExistsError:
            if file_lock_owner_is_dead(path, pid_check=pid_check) or file_lock_is_stale(
                path,
                max_age_seconds=stale_after_seconds,
            ):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                try:
                    return _create_file_lock(path)
                except FileExistsError:
                    pass
                continue
            if attempt != attempts - 1:
                sleep_fn(sleep_seconds)
    return None


def release_file_lock(
    handle: int | None,
    path: str | Path,
    *,
    attempts: int = 6,
    sleep_seconds: float = 0.1,
    sleep_fn: SleepFn = time.sleep,
) -> None:
    """Close and remove a process lock, retrying transient Windows denials.

    Antivirus and indexing can briefly retain the directory entry after the
    owning handle closes. Leaving that entry behind is not cosmetic: if the
    owning Python process remains alive, the next lifecycle decision correctly
    treats the lock as live and can remain blocked until its stale threshold.
    Persistent denial still raises so callers never report an unproven release.
    """

    if handle is None:
        return
    attempts = max(1, int(attempts))
    sleep_seconds = max(0.0, float(sleep_seconds))
    try:
        os.close(handle)
    finally:
        for attempt in range(attempts):
            try:
                Path(path).unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:
                if attempt + 1 >= attempts:
                    raise
                sleep_fn(sleep_seconds)
