"""Shared disk and liveness helpers for daily bot roll launchers."""

from __future__ import annotations

import errno
import shutil
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_MIN_FREE_BYTES = 1_073_741_824
DEFAULT_MAX_ACTIVITY_AGE_SECONDS = 300
DEFAULT_STARTUP_GRACE_SECONDS = 180
RUNNING_STATUSES = {"started", "already_running"}
TERMINAL_STATUSES = {"exited", "failed", "disk_full", "pid_missing", "idle_process"}


def utc_iso(now=None):
    if now is None:
        parsed = datetime.now(timezone.utc)
    elif isinstance(now, datetime):
        parsed = now
    else:
        parsed = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def parse_utc(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_seconds(value, *, now=None):
    parsed = parse_utc(value)
    if parsed is None:
        return None
    current = parse_utc(now) or datetime.now(timezone.utc)
    return max(0.0, (current - parsed).total_seconds())


def nearest_existing_parent(path):
    path = Path(path)
    candidate = path if path.exists() and path.is_dir() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def disk_capacity_preflight(path, *, min_free_bytes=DEFAULT_MIN_FREE_BYTES, usage_fn=None):
    usage_fn = usage_fn or shutil.disk_usage
    root = nearest_existing_parent(path)
    usage = usage_fn(root)
    free = int(usage.free)
    required = int(min_free_bytes)
    status = "PASS" if free >= required else "LOW_SPACE"
    return {
        "status": status,
        "ok": status == "PASS",
        "disk_usage_path": str(root),
        "free_bytes": free,
        "required_free_bytes": required,
        "insufficient_bytes": max(0, required - free),
        "remediation_command": "free local disk space, move old run artifacts, then restart with --force",
    }


def is_disk_full_error(exc):
    if getattr(exc, "errno", None) == errno.ENOSPC:
        return True
    if getattr(exc, "winerror", None) in {112}:
        return True
    return "no space left on device" in str(exc).lower()


def terminal_status_for_dead_pid(payload, *, now=None, pid_alive=None):
    payload = dict(payload or {})
    if not payload:
        return payload
    if payload.get("status") not in RUNNING_STATUSES:
        return payload
    pid = payload.get("pid")
    target_date = payload.get("target_date")
    alive = bool(pid_alive(pid, target_date)) if pid_alive else False
    if alive:
        return payload
    payload.update({
        "status": "pid_missing",
        "action": "blocked_restart_required",
        "terminal": True,
        "pid_alive": False,
        "completed_at_utc": utc_iso(now),
        "first_failing_gate": "process_liveness",
        "root_cause_class": "pid_missing",
        "zero_trades_expected": False,
        "remediation_command": "inspect the console log, then restart the daily roll with --force",
    })
    return payload


def activity_liveness_preflight(
    paths,
    *,
    now=None,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    started_at_utc=None,
    stat_fn=None,
):
    current = parse_utc(now) or datetime.now(timezone.utc)
    stat_fn = stat_fn or (lambda path: Path(path).stat())
    checked = []
    latest_path = None
    latest_mtime = None
    for raw_path in paths or []:
        path = Path(raw_path)
        try:
            stat = stat_fn(path)
        except OSError:
            checked.append({"path": str(path), "exists": False})
            continue
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        age = max(0.0, (current - mtime).total_seconds())
        checked.append({
            "path": str(path),
            "exists": True,
            "modified_at_utc": mtime.isoformat(),
            "age_seconds": round(age, 3),
            "size_bytes": int(getattr(stat, "st_size", 0) or 0),
        })
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime = mtime
            latest_path = str(path)

    if latest_mtime is not None:
        latest_age = max(0.0, (current - latest_mtime).total_seconds())
        status = "PASS" if latest_age <= float(max_activity_age_seconds) else "STALE_ACTIVITY"
        return {
            "status": status,
            "ok": status == "PASS",
            "checked_path_count": len(checked),
            "existing_path_count": sum(1 for row in checked if row.get("exists")),
            "latest_activity_path": latest_path,
            "latest_activity_at_utc": latest_mtime.isoformat(),
            "latest_activity_age_seconds": round(latest_age, 3),
            "max_activity_age_seconds": float(max_activity_age_seconds),
            "startup_grace_seconds": float(startup_grace_seconds),
            "paths": checked,
        }

    startup_age = age_seconds(started_at_utc, now=current)
    if startup_age is not None and startup_age <= float(startup_grace_seconds):
        status = "STARTUP_GRACE"
        ok = True
    else:
        status = "NO_ACTIVITY"
        ok = False
    return {
        "status": status,
        "ok": ok,
        "checked_path_count": len(checked),
        "existing_path_count": 0,
        "latest_activity_path": None,
        "latest_activity_at_utc": None,
        "latest_activity_age_seconds": None,
        "max_activity_age_seconds": float(max_activity_age_seconds),
        "startup_grace_seconds": float(startup_grace_seconds),
        "startup_age_seconds": round(startup_age, 3) if startup_age is not None else None,
        "paths": checked,
    }


def terminal_status_for_inactive_process(
    payload,
    *,
    now=None,
    pid_alive=None,
    activity_paths=None,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    stat_fn=None,
):
    payload = terminal_status_for_dead_pid(payload, now=now, pid_alive=pid_alive)
    if not payload or payload.get("status") not in RUNNING_STATUSES:
        return payload
    activity = activity_liveness_preflight(
        activity_paths,
        now=now,
        max_activity_age_seconds=max_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
        started_at_utc=payload.get("started_at_utc") or payload.get("generated_at_utc"),
        stat_fn=stat_fn,
    )
    payload["activity_liveness"] = activity
    payload["pid_alive"] = True
    if activity.get("ok"):
        return payload
    payload.update({
        "status": "idle_process",
        "action": "blocked_restart_required",
        "terminal": True,
        "completed_at_utc": utc_iso(now),
        "first_failing_gate": "activity_liveness",
        "root_cause_class": "idle_process_no_recent_tape_or_log_activity",
        "zero_trades_expected": False,
        "remediation_command": "inspect the console log and run tape freshness, then restart the daily roll with --force",
    })
    return payload


def disk_full_status(base_payload, *, preflight=None, now=None, error=None):
    payload = dict(base_payload or {})
    payload.update({
        "status": "disk_full",
        "action": "blocked",
        "terminal": True,
        "completed_at_utc": utc_iso(now),
        "first_failing_gate": "disk_capacity",
        "root_cause_class": "blocked_by_disk",
        "zero_trades_expected": True,
        "disk_capacity_preflight": preflight or {},
        "remediation_command": (
            (preflight or {}).get("remediation_command")
            or "free local disk space, then restart the daily roll with --force"
        ),
    })
    if error is not None:
        payload["error"] = f"{type(error).__name__}: {error}"
    return payload


def failed_status(base_payload, *, now=None, error=None):
    payload = dict(base_payload or {})
    payload.update({
        "status": "failed",
        "action": "failed",
        "terminal": True,
        "completed_at_utc": utc_iso(now),
        "first_failing_gate": "launcher",
        "root_cause_class": "launcher_failed",
        "zero_trades_expected": False,
    })
    if error is not None:
        payload["error"] = f"{type(error).__name__}: {error}"
    return payload
