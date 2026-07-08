"""Guardrails for long replay/refresh jobs that share the active-day host."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
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
DEFAULT_CHILD_OUTPUT_TAIL_CHARS = 4000


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


def _lower_memory_priority(priority):
    """Bias Windows page replacement against this process (best effort).

    CPU priority alone did not protect the collection loops on 2026-07-03: a
    7 GB replay at below-normal CPU still forced the trackers' pages out and a
    10-minute capture sweep thrashed to ~85 minutes. Memory priority tells the
    memory manager to evict THIS process's pages before normal-priority ones.
    """
    import ctypes

    MEMORY_PRIORITY_LOW = 2
    MEMORY_PRIORITY_BELOW_NORMAL = 4
    memory_priority = (
        MEMORY_PRIORITY_LOW if priority == "idle" else MEMORY_PRIORITY_BELOW_NORMAL
    )

    class MEMORY_PRIORITY_INFORMATION(ctypes.Structure):
        _fields_ = [("MemoryPriority", ctypes.c_ulong)]

    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetProcessInformation.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    kernel32.SetProcessInformation.restype = ctypes.c_int
    ProcessMemoryPriority = 0
    info = MEMORY_PRIORITY_INFORMATION(memory_priority)
    ok = kernel32.SetProcessInformation(
        kernel32.GetCurrentProcess(),
        ProcessMemoryPriority,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        raise OSError("SetProcessInformation(ProcessMemoryPriority) returned 0")
    return {"applied": True, "memory_priority": memory_priority}


def set_process_working_set_limit(pid, *, max_bytes=None, min_bytes=None):
    """Best-effort Windows working-set cap for an already spawned child.

    The process still owns its virtual memory; this limits resident working set
    pressure so a replay child can be paged without pinning the daily-refresh
    parent or collection loops.
    """
    if not max_bytes or int(max_bytes) <= 0:
        return {"requested": False, "applied": False, "reason": "no_limit"}
    if os.name != "nt":
        return {"requested": True, "applied": False, "reason": "non_windows"}
    try:
        import ctypes

        PROCESS_SET_QUOTA = 0x0100
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        QUOTA_LIMITS_HARDWS_MAX_ENABLE = 0x00000004
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.SetProcessWorkingSetSizeEx.argtypes = (
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_uint32,
        )
        kernel32.SetProcessWorkingSetSizeEx.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            int(pid),
        )
        if not handle:
            raise OSError("OpenProcess returned 0")
        try:
            max_value = int(max_bytes)
            min_value = int(min_bytes) if min_bytes and int(min_bytes) > 0 else min(64 * 1024 * 1024, max_value)
            ok = kernel32.SetProcessWorkingSetSizeEx(
                handle,
                ctypes.c_size_t(min_value),
                ctypes.c_size_t(max_value),
                QUOTA_LIMITS_HARDWS_MAX_ENABLE,
            )
            if not ok:
                raise OSError("SetProcessWorkingSetSizeEx returned 0")
        finally:
            kernel32.CloseHandle(handle)
        return {
            "requested": True,
            "applied": True,
            "pid": int(pid),
            "min_bytes": min_value,
            "max_bytes": max_value,
            "method": "SetProcessWorkingSetSizeEx",
        }
    except Exception as exc:  # noqa: BLE001 - cap is best-effort
        return {
            "requested": True,
            "applied": False,
            "pid": int(pid),
            "max_bytes": int(max_bytes),
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_isolated_subprocess(
    command,
    *,
    timeout_seconds=None,
    working_set_max_bytes=None,
    cwd=None,
    env=None,
    output_tail_chars=DEFAULT_CHILD_OUTPUT_TAIL_CHARS,
):
    """Run a heavy child process and apply a best-effort working-set cap."""
    started = time.time()
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    working_set = set_process_working_set_limit(
        process.pid,
        max_bytes=working_set_max_bytes,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate()
    tail = max(0, int(output_tail_chars or 0))
    return {
        "command": [str(item) for item in command],
        "pid": process.pid,
        "returncode": process.returncode,
        "timed_out": timed_out,
        "stdout": (stdout or "")[-tail:] if tail else "",
        "stderr": (stderr or "")[-tail:] if tail else "",
        "duration_seconds": round(time.time() - started, 3),
        "working_set_limit": working_set,
    }


def lower_process_priority(priority="below_normal"):
    """Best-effort process throttling for local long jobs.

    This deliberately avoids external dependencies. On Windows it uses
    SetPriorityClass plus a lowered memory priority; on POSIX it increases the
    nice value. Failure is reported in the guard status and does not abort the
    job.
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
            try:
                memory_result = _lower_memory_priority(priority)
            except Exception as exc:  # noqa: BLE001 - memory bias is best-effort
                memory_result = {
                    "applied": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            return {
                "requested": priority,
                "applied": True,
                "method": "SetPriorityClass",
                "memory_priority": memory_result,
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
