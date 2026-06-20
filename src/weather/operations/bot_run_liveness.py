"""Shared disk and liveness helpers for daily bot roll launchers."""

from __future__ import annotations

import errno
import shutil
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_MIN_FREE_BYTES = 1_073_741_824
RUNNING_STATUSES = {"started", "already_running"}
TERMINAL_STATUSES = {"exited", "failed", "disk_full", "pid_missing"}


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
