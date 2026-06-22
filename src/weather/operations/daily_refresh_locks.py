"""Lock, stale-state repair, and disk preflight helpers for daily refresh."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from weather.io import write_json_atomic
from weather.paths import data_path
from weather.reporting import promotion_refresh
from weather.reporting.artifact_disk_budget import DEFAULT_ROW_EXPORT_BYTES_PER_ROW
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    process_is_running,
)
from weather.time import utc_now as shared_utc_now


DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_LOCK_PATH = DEFAULT_BACKTEST_ROOT / "daily_refresh.lock"


class DiskPreflightError(RuntimeError):
    def __init__(self, message, payload):
        super().__init__(message)
        self.payload = payload


def utc_now():
    return shared_utc_now()


def utc_iso():
    return utc_now().isoformat()


def as_path(value):
    return str(Path(value)) if value is not None else None


def backtest_path(args, name):
    return str(Path(args.backtest_root) / name)


def cleanup_command(args, target_bytes):
    root = Path(args.backtest_root)
    manifest = root / "backtest_artifact_cleanup_manifest.json"
    return (
        "python -m weather.reporting.backtest_artifact_retention "
        f"--root {root} "
        f"--cleanup-manifest {manifest} "
        f"--cleanup-target-bytes {int(max(0, target_bytes))}"
    )


def resume_command(args, step_name):
    return (
        "python -m weather.operations.daily_refresh run "
        f"--backtest-root {Path(args.backtest_root)} "
        f"--snapshots-root {Path(args.snapshots_root)} "
        f"--resume-from-step {step_name}"
    )


def _read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def promotion_export_row_estimate(args):
    payload = _read_json(backtest_path(args, "pooled_candidate_replay_latest.json"))
    aggregate = payload.get("aggregate") or {}
    rows = aggregate.get("n") or aggregate.get("rows") or 0
    try:
        return int(float(rows))
    except (TypeError, ValueError):
        return 0


def promotion_disk_preflight(args, disk_usage_fn=None):
    disk_usage_fn = disk_usage_fn or shutil.disk_usage
    out_path = Path(backtest_path(args, "f_family_promotion_refresh.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    usage = disk_usage_fn(out_path.parent)
    min_free_bytes = int(getattr(
        args,
        "promotion_min_artifact_free_bytes",
        promotion_refresh.DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES,
    ) or 0)
    rows = promotion_export_row_estimate(args)
    projected_export_bytes = rows * int(max(1, DEFAULT_ROW_EXPORT_BYTES_PER_ROW))
    required_free_bytes = min_free_bytes + projected_export_bytes
    free_bytes = int(getattr(usage, "free"))
    insufficient_bytes = max(0, required_free_bytes - free_bytes)
    status = "PASS" if insufficient_bytes == 0 else "BLOCK"
    return {
        "schema_version": "daily_refresh_disk_preflight_v0.1",
        "step": "promotion_refresh",
        "status": status,
        "path": str(out_path),
        "free_bytes": free_bytes,
        "total_bytes": int(getattr(usage, "total", 0)),
        "required_free_bytes": int(required_free_bytes),
        "min_free_bytes": int(min_free_bytes),
        "projected_export_bytes": int(projected_export_bytes),
        "estimated_export_rows": rows,
        "bytes_per_row": int(DEFAULT_ROW_EXPORT_BYTES_PER_ROW),
        "insufficient_bytes": int(insufficient_bytes),
        "cleanup_command": cleanup_command(args, insufficient_bytes),
        "resume_command": resume_command(args, "promotion_refresh"),
    }


def write_json(path, payload):
    return write_json_atomic(path, payload, trailing_newline=True)


def _read_lock_payload(path):
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "missing"
    except json.JSONDecodeError as exc:
        return {"path": str(path), "error": str(exc)}, "unreadable"
    except OSError as exc:
        return {"path": str(path), "error": str(exc)}, "unreadable"
    if not isinstance(payload, dict):
        return {"path": str(path), "raw_type": type(payload).__name__}, "unreadable"
    return payload, "ok"


def lock_diagnostic(path, *, kind):
    path = Path(path)
    payload, read_status = _read_lock_payload(path)
    exists = path.exists()
    pid = payload.get("pid") if isinstance(payload, dict) else None
    owner_running = None
    stale = False
    stale_reason = ""
    if exists and read_status == "ok" and pid not in (None, ""):
        owner_running = process_is_running(pid)
        if owner_running is False:
            stale = True
            stale_reason = "dead_pid"
    elif exists and read_status != "ok":
        stale_reason = "owner_unknown"
    return {
        "kind": kind,
        "path": str(path),
        "exists": exists,
        "read_status": read_status,
        "pid": pid,
        "owner_running": owner_running,
        "stale": stale,
        "stale_reason": stale_reason,
        "payload": payload if exists else {},
    }


def _remove_lock_if_verified_stale(path, *, kind):
    diagnostic = lock_diagnostic(path, kind=kind)
    if not diagnostic.get("stale"):
        diagnostic["removed"] = False
        return diagnostic
    try:
        Path(path).unlink()
        diagnostic["removed"] = True
    except FileNotFoundError:
        diagnostic["removed"] = False
        diagnostic["missing_before_remove"] = True
    return diagnostic


def long_job_state_diagnostic(path):
    path = Path(path)
    payload, read_status = _read_lock_payload(path)
    exists = path.exists()
    active = bool(payload.get("active")) or payload.get("status") == "running"
    pid = payload.get("pid") if isinstance(payload, dict) else None
    owner_running = None
    stale = False
    if exists and read_status == "ok" and active and pid not in (None, ""):
        owner_running = process_is_running(pid)
        stale = owner_running is False
    return {
        "kind": "long_job_guard_status",
        "path": str(path),
        "exists": exists,
        "read_status": read_status,
        "active": active,
        "status": payload.get("status") if isinstance(payload, dict) else None,
        "pid": pid,
        "owner_running": owner_running,
        "stale": stale,
        "stale_reason": "dead_pid" if stale else "",
        "payload": payload if exists else {},
    }


def clear_stale_long_job_state(path):
    diagnostic = long_job_state_diagnostic(path)
    if not diagnostic.get("stale"):
        diagnostic["cleared"] = False
        return diagnostic
    payload = dict(diagnostic.get("payload") or {})
    payload.update({
        "status": "stale_cleared",
        "active": False,
        "updated_at_utc": utc_iso(),
        "stale_cleared_at_utc": utc_iso(),
        "stale_reason": "dead_pid",
    })
    write_json(path, payload)
    diagnostic["cleared"] = True
    return diagnostic


def stale_lock_repair_command(args, *, resume_from_step="daily_learning", run_after_repair=True):
    lock_path = getattr(args, "lock_path", DEFAULT_LOCK_PATH)
    command = (
        "python -m weather.operations.daily_refresh repair-stale-locks "
        f"--backtest-root {Path(args.backtest_root)} "
        f"--snapshots-root {Path(args.snapshots_root)} "
        f"--lock-path {Path(lock_path)} "
        f"--long-job-lock {Path(getattr(args, 'long_job_lock', DEFAULT_LONG_JOB_LOCK_PATH))} "
        f"--long-job-state {Path(getattr(args, 'long_job_state', DEFAULT_LONG_JOB_STATE_PATH))} "
        f"--resume-from-step {resume_from_step}"
    )
    if run_after_repair:
        command += " --run-after-repair"
    return command


def lock_preflight(args):
    lock_path = getattr(args, "lock_path", DEFAULT_LOCK_PATH)
    return {
        "daily_refresh_lock": lock_diagnostic(lock_path, kind="daily_refresh_lock"),
        "long_job_lock": lock_diagnostic(
            getattr(args, "long_job_lock", DEFAULT_LONG_JOB_LOCK_PATH),
            kind="long_job_guard_lock",
        ),
        "long_job_state": long_job_state_diagnostic(
            getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
        ),
        "repair_command": stale_lock_repair_command(args),
    }


def acquire_lock(path, force=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if force:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(path), flags)
    except FileExistsError:
        stale = _remove_lock_if_verified_stale(path, kind="daily_refresh_lock")
        if not stale.get("removed"):
            return None
        try:
            fd = os.open(str(path), flags)
        except FileExistsError:
            return None
    payload = {
        "pid": os.getpid(),
        "created_at_utc": utc_iso(),
    }
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
    return path


def release_lock(path):
    if not path:
        return
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


