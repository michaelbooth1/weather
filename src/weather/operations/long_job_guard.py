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


def _lock_payload(job_name):
    return {
        "schema_version": SCHEMA_VERSION,
        "job_name": job_name,
        "pid": os.getpid(),
        "started_at_utc": utc_iso(),
    }


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
        detail = None
        try:
            detail = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            detail = {"path": str(path)}
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
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.kernel32.SetPriorityClass(handle, priority_class)
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
        if not Path(state_path).exists():
            return
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
