"""Capture admission for the exact, bounded replay-cache compression lane."""

from __future__ import annotations

from datetime import datetime, timezone
import ctypes
from ctypes import wintypes
import math
import json
import os
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

from weather.operations.capture_resource_gate import (
    available_memory_bytes, default_loop_specs, inspect_capture_loop,
)
from weather.operations.daily_refresh_resources import host_commit_percent
from weather.operations.ntfs_file_compression import MAX_FILE_BYTES
from weather.operations.windows_processes import describe_process, snapshot_processes
from weather.operations.process_lock_identity import observe_process_identity


GIB = 1024**3
MIN_FREE_MEMORY_BYTES = 4 * GIB
MAX_COMMIT_PERCENT = 70.0
MAX_HEARTBEAT_AGE_SECONDS = 180
MAX_SNAPSHOT_CLEAN_AGE_SECONDS = 900
# Twenty GiB remain reserved for capture. The lane permits at most 64 MiB per
# file and reserves two additional complete file images plus 1 MiB of receipts.
# This is a compression-only reservation, never a general heavy-work override.
MIN_FREE_DISK_BYTES = 20 * GIB + 2 * MAX_FILE_BYTES + 1024**2


def check_resources(*, now, available, commit, free_disk, loops):
    result = check_capture_health(now=now, available=available, commit=commit, loops=loops)
    result.update(free_disk_bytes=free_disk, minimum_free_disk_bytes=MIN_FREE_DISK_BYTES)
    if free_disk is None or free_disk < MIN_FREE_DISK_BYTES:
        result["reasons"].append("compression_disk_reservation_unmet")
        result["status"] = "BLOCK"
    return result


STORAGE_DAYTIME_EXCEPTION = "OWNER_APPROVED_STORAGE_RECOVERY_20260908"
STORAGE_DAYTIME_POLICY = "owner_approved_storage_recovery_20260908"
ARCHIVE_DAYTIME_EXCEPTION = "OWNER_APPROVED_ARCHIVE_RECOVERY_20260910"
ARCHIVE_DAYTIME_START = datetime(2026, 9, 10, 17, 10, 38, tzinfo=timezone.utc)
ARCHIVE_DAYTIME_END = datetime(2026, 9, 10, 22, tzinfo=timezone.utc)
STORAGE_DAYTIME_EXCEPTIONS = {
    ARCHIVE_DAYTIME_EXCEPTION: ("2026-09-10", ARCHIVE_DAYTIME_EXCEPTION.lower()),
    STORAGE_DAYTIME_EXCEPTION: ("2026-09-08", STORAGE_DAYTIME_POLICY),
    "OWNER_APPROVED_STORAGE_RECOVERY_20260909":
        ("2026-09-09", "owner_approved_storage_recovery_20260909"),
}


def storage_daytime_authorized(now, exception):
    if exception == ARCHIVE_DAYTIME_EXCEPTION:
        return ARCHIVE_DAYTIME_START <= now < ARCHIVE_DAYTIME_END
    local = now.astimezone(ZoneInfo("America/Toronto"))
    authorization = STORAGE_DAYTIME_EXCEPTIONS.get(exception)
    return (authorization is not None and local.date().isoformat() == authorization[0]
            and 540 <= local.hour * 60 + local.minute < 1080)


def verify_storage_exception(lease, exception, now):
    """Bind the dated owner instruction to the independently verified live lease."""
    if exception:
        if (not storage_daytime_authorized(now, exception)
                or lease.get("policy_window") != STORAGE_DAYTIME_EXCEPTIONS[exception][1]):
            raise ValueError("storage exception is invalid, expired or differs from the lease")
    elif lease.get("policy_window") in {row[1] for row in STORAGE_DAYTIME_EXCEPTIONS.values()}:
        raise ValueError("storage exception is missing from the wrapper environment")


def check_capture_health(*, now, available, commit, loops, owner_approved_exception=""):
    local = now.astimezone(ZoneInfo("America/Toronto"))
    minute = local.hour * 60 + local.minute
    reasons = []
    daytime = storage_daytime_authorized(now, owner_approved_exception)
    if owner_approved_exception and not daytime:
        reasons.append("invalid_or_expired_storage_exception")
    if not 30 <= minute < 9 * 60 and not daytime:
        reasons.append("outside_0030_0900_capture_window")
    if 285 <= minute < 405:
        reasons.append("reserved_0445_0645_scheduled_tiering_window")
    if available is None or available < MIN_FREE_MEMORY_BYTES:
        reasons.append("physical_memory_below_4_gib")
    if commit is None or not math.isfinite(commit) or not 0 <= commit < MAX_COMMIT_PERCENT:
        reasons.append("commit_not_below_70_percent")
    if len(loops) != 3 or {row.get("name") for row in loops} != {"snapshot", "clob", "observation_trigger"}:
        reasons.append("capture_loop_evidence_missing")
    for row in loops:
        if (not row.get("active") or row.get("degraded") or not row.get("heartbeat_fresh")
                or not row.get("pid_agreement")
                or not row.get("process_identity_matches_lock")
                or not _fresh_age(row.get("heartbeat_age_seconds"), MAX_HEARTBEAT_AGE_SECONDS)
                or not row.get("process_diagnostics", {}).get("status_pid_alive")
                or not row.get("process_diagnostics", {}).get("lock_pid_alive")):
            reasons.append("capture_unhealthy:" + str(row.get("name")))
        if row.get("name") == "snapshot" and not _fresh_age(
                row.get("last_clean_iteration_age_seconds"), MAX_SNAPSHOT_CLEAN_AGE_SECONDS):
            reasons.append("snapshot_clean_iteration_missing_or_stale")
    return {"status": "BLOCK" if reasons else "PASS", "reasons": reasons,
            "checked_at_utc": now.isoformat(), "available_memory_bytes": available,
            "host_commit_percent": commit,
            "capture_loops": [{key: row.get(key) for key in (
                "name", "status_pid", "lock_pid", "heartbeat_age_seconds",
                "last_clean_iteration_age_seconds", "process_identity_matches_lock",
            )} for row in loops]}


def _fresh_age(value, maximum):
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= maximum


def _age(now, stamp):
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return (now - parsed).total_seconds() if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def _bounded_status(path, limit):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("capture status/lock exceeds its admission read bound")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("capture status/lock must be a JSON object")
    return value


def capture_admission(production_root: Path):
    return observe_capture_admission(production_root, check_resources)


def observe_capture_admission(production_root: Path, resource_checker):
    now = datetime.now(timezone.utc)
    observed, loops, statuses = {}, [], []
    def process(pid):
        if pid not in observed:
            observed[pid] = observe_process_identity(pid)
        return observed[pid]
    for spec in default_loop_specs(production_root / "data" / "snapshots"):
        status = _bounded_status(spec.status_path, 1024 * 1024)
        lock = _bounded_status(spec.status_path.with_name(f".{spec.status_path.name}.writer.lock"), 16384)
        row = inspect_capture_loop(spec, now=now,
                                   process_checker=lambda pid: process(pid).get("state") == "running")
        if (type(status.get("consecutive_errors")) is not int or status["consecutive_errors"] != 0
                or status.get("paused") is not False):
            row["degraded"] = True
        identity = lock.get("managed_process") or {}
        row["process_identity_matches_lock"] = bool(
            status.get("pid") == row.get("status_pid") == lock.get("pid") == identity.get("pid")
            and identity.get("creation_time_token")
            and identity["creation_time_token"] == process(row["status_pid"]).get("creation_time_token")
        )
        loops.append(row)
        statuses.append(status)
    # Producers can publish while status/identity reads are in progress. Age all
    # captured timestamps after those reads; a start-time clock can falsely
    # classify a newly written heartbeat as future-dated.
    now = datetime.now(timezone.utc)
    for row, status in zip(loops, statuses):
        row["heartbeat_age_seconds"] = _age(now, status.get("last_heartbeat"))
        row["last_clean_iteration_age_seconds"] = _age(now, status.get("last_clean_iteration_at"))
    result = resource_checker(now=now, available=available_memory_bytes(),
                             commit=host_commit_percent(),
                             free_disk=shutil.disk_usage(production_root).free, loops=loops)
    memory = process_memory_bytes()
    result["child_memory"] = memory
    if memory is None or max(memory.values()) > 384 * 1024**2:
        result["reasons"].append("child_memory_unavailable_or_over_384_mib")
        result["status"] = "BLOCK"
    result["worker_priority_class"] = current_process_priority()
    if result["worker_priority_class"] != 0x4000:
        result["reasons"].append("worker_not_below_normal_priority")
        result["status"] = "BLOCK"
    return result


def current_process_priority():
    api = ctypes.WinDLL("kernel32", use_last_error=True).GetPriorityClass
    api.argtypes, api.restype = [wintypes.HANDLE], wintypes.DWORD
    return int(api(ctypes.c_void_p(-1)))


def set_current_process_below_normal():
    api = ctypes.WinDLL("kernel32", use_last_error=True).SetPriorityClass
    api.argtypes, api.restype = [wintypes.HANDLE, wintypes.DWORD], wintypes.BOOL
    if not api(ctypes.c_void_p(-1), 0x4000) or current_process_priority() != 0x4000:
        raise OSError("cannot establish BelowNormal priority for the actual Python worker")


def process_memory_bytes():
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "peak_working", "working", "peak_paged", "paged", "peak_nonpaged",
                "nonpaged", "pagefile", "peak_pagefile", "private")]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    api = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    api.restype = wintypes.BOOL
    if not api(ctypes.c_void_p(-1), ctypes.byref(counters), counters.cb):
        return None
    return {"working_set_bytes": int(counters.working), "private_bytes": int(counters.private)}


def verify_lease_owner(record, *, owner_pid, table, describe,
                       workload="replay_cache_compression"):
    """Require a live wrapper ancestor, including the Windows venv redirector."""
    if (record.get("workload") != workload
            or record.get("execution_host_profile") != "capture_colocated_v1"
            or record.get("pid") != owner_pid or not table):
        raise ValueError("compression wrapper lease identity is missing")
    process = describe(owner_pid, table)
    if (not record.get("owner_process_creation_time_token")
            or process.get("creation_time_token") != record["owner_process_creation_time_token"]):
        raise ValueError("compression wrapper process identity changed")
    current = os.getpid()
    for _ in range(3):
        current = (table.get(current) or {}).get("parent_pid")
        if current == owner_pid:
            return
        if current is None:
            break
    raise ValueError("the lease owner is not this process's wrapper ancestor")


def verify_current_lease(record, owner_pid, path, *, workload="replay_cache_compression"):
    verify_lease_owner(record, owner_pid=owner_pid, table=snapshot_processes(),
                       describe=describe_process, workload=workload)
    verify_lease_file_locked(path)


def verify_lease_file_locked(path):
    """A stale owner JSON is insufficient: the live lease must exclude writers."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x40000000, 7, None, 3, 0x00200000, None)
    if handle != ctypes.c_void_p(-1).value:
        kernel.CloseHandle(handle)
        raise ValueError("compression lease file is not held against another writer")
    if ctypes.get_last_error() != 32:
        raise ValueError("compression lease ownership cannot be proved by the sharing lock")
