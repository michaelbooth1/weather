"""Guardrails for long replay/refresh jobs that share the active-day host."""

from __future__ import annotations

import contextlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path

from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("long_job_guard")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_STATE_PATH = DEFAULT_BACKTEST_ROOT / "long_job_guard_status.json"
DEFAULT_LOCK_PATH = DEFAULT_BACKTEST_ROOT / "long_job_guard.lock"
ACTIVE_ENV_VAR = "WEATHER_LONG_JOB_GUARD_ACTIVE"


class LongJobBusy(RuntimeError):
    """Raised when another guarded long job is already active."""


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _parse_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def touch_long_job_guard(state_path=DEFAULT_STATE_PATH, *, progress=None):
    """Refresh a running long-job guard heartbeat without taking the lock."""
    state_path = Path(state_path)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"updated": False, "reason": "state_unavailable"}
    if state.get("status") != "running" or not state.get("active"):
        return {"updated": False, "reason": "not_running"}
    now = utc_iso()
    state["updated_at_utc"] = now
    started = _parse_utc(state.get("started_at_utc"))
    current = _parse_utc(now)
    if started and current:
        state["duration_seconds"] = round((current - started).total_seconds(), 3)
    if progress is not None:
        state["progress"] = progress
        state["last_progress_at_utc"] = now
    write_json(state_path, state)
    return {"updated": True, "state_path": str(state_path)}


def _lock_payload(job_name):
    return {
        "schema_version": SCHEMA_VERSION,
        "job_name": job_name,
        "pid": os.getpid(),
        "started_at_utc": utc_iso(),
    }


def process_is_running(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information | synchronize,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_is_running(pid):
    return process_is_running(pid)


def _read_lock_detail(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(path)}


def _lock_owner_is_active(detail):
    if isinstance(detail, dict) and "pid" in detail:
        return _process_is_running(detail.get("pid"))
    return True


def acquire_long_job_lock(path, job_name, force=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if force:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        detail = _read_lock_detail(path)
        if not _lock_owner_is_active(detail):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                detail = _read_lock_detail(path)
                raise LongJobBusy(f"long job already active: {detail}") from exc
        else:
            raise LongJobBusy(f"long job already active: {detail}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(_lock_payload(job_name), handle, sort_keys=True)
    return path


def release_long_job_lock(path):
    if not path:
        return
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def lower_process_priority(priority="below_normal"):
    """Best-effort process throttling for local long jobs.

    This deliberately avoids external dependencies. On Windows it uses
    SetPriorityClass; on POSIX it increases nice value. Failure is reported in
    the guard status and does not abort the job.
    """
    priority = (priority or "normal").lower()
    if priority in {"normal", "none", "off"}:
        return {"requested": priority, "applied": False, "reason": "normal_priority"}
    try:
        if os.name == "nt":
            import ctypes

            classes = {
                "idle": 0x00000040,
                "below_normal": 0x00004000,
            }
            priority_class = classes.get(priority, classes["below_normal"])
            kernel32 = ctypes.windll.kernel32
            # Without these declarations ctypes truncates the pseudo-handle to
            # a 32-bit int on 64-bit Windows and SetPriorityClass rejects it.
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            kernel32.SetPriorityClass.restype = ctypes.c_int
            handle = kernel32.GetCurrentProcess()
            ok = kernel32.SetPriorityClass(handle, priority_class)
            if not ok:
                raise OSError("SetPriorityClass returned 0")
            return {
                "requested": priority,
                "applied": True,
                "method": "SetPriorityClass",
            }
        increment = 10 if priority == "idle" else 5
        new_nice = os.nice(increment)
        return {
            "requested": priority,
            "applied": True,
            "method": "os.nice",
            "nice": new_nice,
        }
    except Exception as exc:  # noqa: BLE001 - throttling is best-effort
        return {
            "requested": priority,
            "applied": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


@contextlib.contextmanager
def long_job_guard(
    job_name,
    *,
    state_path=DEFAULT_STATE_PATH,
    lock_path=DEFAULT_LOCK_PATH,
    priority="below_normal",
    enabled=True,
    force_lock=False,
):
    """Serialize and throttle expensive replay/refresh jobs.

    Nested calls in the same process tree are treated as already guarded. This
    lets `daily_refresh` guard the whole pipeline while `promotion_refresh`
    remains guarded when invoked directly.
    """
    if not enabled:
        yield {
            "enabled": False,
            "state_path": str(state_path),
            "lock_path": str(lock_path),
        }
        return
    if os.environ.get(ACTIVE_ENV_VAR):
        yield {
            "enabled": True,
            "nested": True,
            "state_path": str(state_path),
            "lock_path": str(lock_path),
        }
        return

    lock = acquire_long_job_lock(lock_path, job_name, force=force_lock)
    previous_env = os.environ.get(ACTIVE_ENV_VAR)
    os.environ[ACTIVE_ENV_VAR] = str(os.getpid())
    start_monotonic = time.time()
    started_wall = utc_iso()
    priority_result = lower_process_priority(priority)
    write_json(state_path, {
        "schema_version": SCHEMA_VERSION,
        "status": "running",
        "active": True,
        "job_name": job_name,
        "pid": os.getpid(),
        "started_at_utc": started_wall,
        "updated_at_utc": started_wall,
        "duration_seconds": 0.0,
        "priority": priority_result,
    })
    try:
        yield {
            "enabled": True,
            "nested": False,
            "state_path": str(state_path),
            "lock_path": str(lock_path),
            "priority": priority_result,
        }
    except Exception as exc:
        write_json(state_path, {
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "active": False,
            "job_name": job_name,
            "pid": os.getpid(),
            "started_at_utc": started_wall,
            "updated_at_utc": utc_iso(),
            "duration_seconds": round(time.time() - start_monotonic, 3),
            "priority": priority_result,
            "error": f"{type(exc).__name__}: {exc}",
        })
        raise
    finally:
        if previous_env is None:
            os.environ.pop(ACTIVE_ENV_VAR, None)
        else:
            os.environ[ACTIVE_ENV_VAR] = previous_env
        release_long_job_lock(lock)
        if Path(state_path).exists():
            try:
                state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
            if state.get("status") == "running":
                state.update({
                    "status": "complete",
                    "active": False,
                    "updated_at_utc": utc_iso(),
                    "duration_seconds": round(time.time() - start_monotonic, 3),
                })
                write_json(state_path, state)
