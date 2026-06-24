from __future__ import annotations

import os
import json
import logging
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from weather.io import append_jsonl as io_append_jsonl
from weather.io import read_json as io_read_json
from weather.io import write_json_atomic
from weather.time import age_minutes as time_age_minutes
from weather.time import age_seconds as time_age_seconds
from weather.time import parse_datetime


SleepFn = Callable[[float], None]


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


def writer_lock_path(path: str | Path) -> Path:
    path = Path(path)
    return path.with_name(f".{path.name}.writer.lock")


def _writer_owner_payload(status_path: str | Path, owner: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "pid": os.getpid(),
        "status_path": str(Path(status_path)),
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(owner or {})
    return payload


def acquire_writer_lock(
    status_path: str | Path,
    *,
    owner: dict[str, Any] | None = None,
    attempts: int = 1,
    stale_after_seconds: float = 120.0,
    sleep_seconds: float = 0.1,
    sleep_fn: SleepFn = time.sleep,
) -> dict[str, Any] | None:
    lock_path = writer_lock_path(status_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        try:
            handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = _writer_owner_payload(status_path, owner)
            os.write(handle, json.dumps(payload, sort_keys=True).encode("utf-8"))
            return {"handle": handle, "path": str(lock_path), "owner": payload}
        except FileExistsError:
            if file_lock_is_stale(lock_path, max_age_seconds=stale_after_seconds):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if attempt != attempts - 1:
                sleep_fn(sleep_seconds)
    return None


def release_writer_lock(lock: dict[str, Any] | None) -> None:
    if not lock:
        return
    handle = lock.get("handle")
    if handle is not None:
        try:
            os.close(handle)
        except OSError:
            pass
    try:
        Path(lock["path"]).unlink()
    except (FileNotFoundError, KeyError):
        pass


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


def _recovery_event(event: dict[str, Any]) -> bool:
    return (
        str(event.get("supervisor") or "").lower() == "ensure"
        and str(event.get("action") or "").lower() in {"start", "restart"}
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


def file_lock_is_stale(path: str | Path, *, max_age_seconds: float = 120.0) -> bool:
    path = Path(path)
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age > max_age_seconds


def acquire_file_lock(
    path: str | Path,
    *,
    attempts: int = 1,
    stale_after_seconds: float = 120.0,
    sleep_seconds: float = 0.1,
    sleep_fn: SleepFn = time.sleep,
) -> int | None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, str(os.getpid()).encode("ascii"))
            return handle
        except FileExistsError:
            if file_lock_is_stale(path, max_age_seconds=stale_after_seconds):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if attempt != attempts - 1:
                sleep_fn(sleep_seconds)
    return None


def release_file_lock(handle: int | None, path: str | Path) -> None:
    if handle is None:
        return
    try:
        os.close(handle)
    finally:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
