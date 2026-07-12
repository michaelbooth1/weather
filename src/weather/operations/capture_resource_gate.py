"""Read-only admission gate for heavyweight work on capture hosts.

The gate never starts, stops, pauses, or signals a process.  It combines the
portable loop contract (status heartbeat plus single-writer lock) with optional
PID liveness diagnostics and host resource headroom.  Live capture evidence is
therefore not trusted from process discovery alone.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from weather.operations.long_job_guard import process_is_running
from weather.operations.supervisor import age_seconds, read_writer_lock
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("capture_resource_gate")
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_DISK_PATH = data_path()
DEFAULT_OUT = data_path("backtest", "capture_resource_gate.json")
DEFAULT_REPORT = data_path("backtest", "capture_resource_gate.md")
DEFAULT_MIN_FREE_MEMORY_BYTES = 4 * 1024**3
DEFAULT_MIN_FREE_DISK_BYTES = 30 * 1024**3
DEFAULT_MIN_DISK_HEADROOM_DAYS = 30.0
CAPTURE_MODES = ("live", "offline_host", "no_live_capture")
EVIDENCE_CONTRACT = "capture_resource_admission_enforcement_v0.1"
DAILY_REFRESH_WORKLOAD = "daily_refresh_heavy_steps"
NIGHTLY_RETRAIN_WORKLOAD = "nightly_retrain_heavy_pipeline"
INTEGRATED_WORKLOADS = (DAILY_REFRESH_WORKLOAD, NIGHTLY_RETRAIN_WORKLOAD)


@dataclass(frozen=True)
class CaptureLoopSpec:
    name: str
    status_path: Path
    default_interval_seconds: float
    required: bool = True


def default_loop_specs(snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT) -> tuple[CaptureLoopSpec, ...]:
    root = Path(snapshots_root)
    return (
        CaptureLoopSpec("snapshot", root / "loop_status.json", 600.0),
        CaptureLoopSpec("clob", root / "clob_loop_status.json", 60.0),
        CaptureLoopSpec("observation_trigger", root / "observation_trigger_status.json", 60.0),
    )


def utc_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _read_json_with_status(path: Path) -> tuple[dict[str, Any] | None, str, str | None]:
    if not path.exists():
        return None, "MISSING", None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, "UNREADABLE", f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return None, "UNREADABLE", "status payload is not a JSON object"
    return payload, "PRESENT", None


def _positive_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return parsed if parsed > 0 else float(fallback)


def _loop_interval_seconds(status: dict[str, Any] | None, spec: CaptureLoopSpec) -> float:
    status = status or {}
    if status.get("interval_seconds") not in (None, ""):
        return _positive_float(status.get("interval_seconds"), spec.default_interval_seconds)
    if status.get("interval_minutes") not in (None, ""):
        return 60.0 * _positive_float(status.get("interval_minutes"), spec.default_interval_seconds / 60.0)
    return float(spec.default_interval_seconds)


def _safe_pid(value: Any) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _process_diagnostic(pid: int | None, process_checker: Callable[[Any], bool]) -> tuple[bool, str | None]:
    if not pid:
        return False, None
    try:
        return bool(process_checker(pid)), None
    except Exception as exc:  # noqa: BLE001 - portable artifacts remain authoritative
        return False, f"{type(exc).__name__}: {exc}"


def inspect_capture_loop(
    spec: CaptureLoopSpec,
    *,
    now: datetime,
    process_checker: Callable[[Any], bool] = process_is_running,
    heartbeat_interval_multiplier: float = 3.0,
    minimum_heartbeat_max_age_seconds: float = 180.0,
    error_threshold: int = 1,
) -> dict[str, Any]:
    """Read one loop's status/lock contract without changing either artifact."""

    status, artifact_status, read_error = _read_json_with_status(spec.status_path)
    try:
        writer_lock = read_writer_lock(spec.status_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        writer_lock = {
            "exists": False,
            "path": str(spec.status_path.with_name(f".{spec.status_path.name}.writer.lock")),
            "error": f"{type(exc).__name__}: {exc}",
        }
    interval_seconds = _loop_interval_seconds(status, spec)
    configured_stale = (status or {}).get("stale_after_seconds")
    heartbeat_max_age = max(
        float(minimum_heartbeat_max_age_seconds),
        _positive_float(
            configured_stale,
            interval_seconds * float(heartbeat_interval_multiplier),
        ),
    )
    heartbeat = (status or {}).get("last_heartbeat")
    heartbeat_age = age_seconds(now, heartbeat) if heartbeat else None
    heartbeat_fresh = heartbeat_age is not None and heartbeat_age <= heartbeat_max_age
    status_pid = _safe_pid((status or {}).get("pid"))
    lock_pid = _safe_pid(writer_lock.get("pid"))
    status_pid_alive, status_pid_error = _process_diagnostic(status_pid, process_checker)
    lock_pid_alive, lock_pid_error = _process_diagnostic(lock_pid, process_checker)
    pid_agreement = not (status_pid and lock_pid) or status_pid == lock_pid
    portable_active_evidence = bool(heartbeat_fresh and writer_lock.get("exists") and pid_agreement)
    active = bool(status_pid_alive or lock_pid_alive or portable_active_evidence)
    errors = _safe_nonnegative_int((status or {}).get("consecutive_errors"))
    degraded_reasons: list[str] = []
    if artifact_status != "PRESENT":
        degraded_reasons.append(f"status_{artifact_status.lower()}")
    if artifact_status == "PRESENT" and heartbeat_age is None:
        degraded_reasons.append("heartbeat_missing_or_invalid")
    elif artifact_status == "PRESENT" and not heartbeat_fresh:
        degraded_reasons.append("heartbeat_stale")
    if (status or {}).get("paused"):
        degraded_reasons.append("loop_paused")
    if errors >= int(error_threshold):
        degraded_reasons.append("consecutive_errors")
    if (status or {}).get("last_error") and errors:
        degraded_reasons.append("last_error_present")
    if artifact_status == "PRESENT" and not writer_lock.get("exists"):
        degraded_reasons.append("writer_lock_missing")
    if writer_lock.get("exists") and not lock_pid:
        degraded_reasons.append("writer_lock_pid_missing")
    if status_pid and lock_pid and not pid_agreement:
        degraded_reasons.append("status_lock_pid_mismatch")
    if writer_lock.get("error"):
        degraded_reasons.append("writer_lock_unreadable")
    degraded_reasons = sorted(set(degraded_reasons))
    if active and degraded_reasons:
        state = "ACTIVE_DEGRADED"
    elif active:
        state = "ACTIVE_HEALTHY"
    elif degraded_reasons:
        state = "INACTIVE_DEGRADED"
    else:
        state = "INACTIVE"
    return {
        "name": spec.name,
        "required": spec.required,
        "status_path": str(spec.status_path),
        "status_artifact": artifact_status,
        "status_read_error": read_error,
        "writer_lock": {
            key: writer_lock.get(key)
            for key in ("exists", "path", "pid", "age_seconds", "acquired_at_utc", "loop", "module", "error")
            if key in writer_lock
        },
        "state": state,
        "active": active,
        "degraded": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
        "heartbeat": heartbeat,
        "heartbeat_age_seconds": heartbeat_age,
        "heartbeat_max_age_seconds": heartbeat_max_age,
        "heartbeat_fresh": heartbeat_fresh,
        "interval_seconds": interval_seconds,
        "consecutive_errors": errors,
        "paused": bool((status or {}).get("paused")),
        "status_pid": status_pid,
        "lock_pid": lock_pid,
        "pid_agreement": pid_agreement,
        "process_diagnostics": {
            "status_pid_alive": status_pid_alive,
            "lock_pid_alive": lock_pid_alive,
            "status_pid_error": status_pid_error,
            "lock_pid_error": lock_pid_error,
            "diagnostic_only": True,
        },
        "portable_active_evidence": portable_active_evidence,
        "runtime_identity": (status or {}).get("runtime_identity"),
    }


def available_memory_bytes() -> int | None:
    """Return currently available physical memory without optional packages."""

    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return int(status.ullAvailPhys)
        except (AttributeError, OSError, ValueError):
            return None
    try:
        pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return pages * page_size
    except (AttributeError, OSError, ValueError):
        return None


def _hour_in_window(hour: float, start_hour: float, end_hour: float) -> bool:
    start = float(start_hour) % 24.0
    end = float(end_hour) % 24.0
    current = float(hour) % 24.0
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _configured_active_window(
    now: datetime,
    *,
    capture_mode: str,
    active_window: bool | None,
    active_window_start_hour: float | None,
    active_window_end_hour: float | None,
) -> tuple[bool, str]:
    if capture_mode != "live":
        return False, "capture_mode_disables_live_window"
    if active_window is not None:
        return bool(active_window), "explicit_override"
    if active_window_start_hour is not None and active_window_end_hour is not None:
        local_now = now.astimezone()
        local_hour = local_now.hour + local_now.minute / 60.0 + local_now.second / 3600.0
        return (
            _hour_in_window(local_hour, active_window_start_hour, active_window_end_hour),
            "configured_local_hour_window",
        )
    return True, "fail_closed_live_default"


def _next_window_end(
    now: datetime,
    start_hour: float | None,
    end_hour: float | None,
) -> datetime | None:
    if start_hour is None or end_hour is None:
        return None
    local_now = now.astimezone()
    end = float(end_hour) % 24.0
    hour = int(end)
    minute = int(round((end - hour) * 60.0))
    if minute >= 60:
        hour = (hour + 1) % 24
        minute = 0
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    start = float(start_hour) % 24.0
    local_value = local_now.hour + local_now.minute / 60.0
    if start < end:
        if candidate <= local_now:
            candidate += timedelta(days=1)
    elif start > end:
        if local_value >= start:
            candidate += timedelta(days=1)
    elif candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _blocker(code: str, detail: str, *, defer_seconds: float, **evidence: Any) -> dict[str, Any]:
    return {
        "code": code,
        "detail": detail,
        "defer_seconds": float(defer_seconds),
        "evidence": evidence,
    }


def build_capture_resource_gate(
    *,
    workload: str = "heavyweight_work",
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    disk_path: str | Path = DEFAULT_DISK_PATH,
    capture_mode: str = "live",
    active_window: bool | None = None,
    active_window_start_hour: float | None = None,
    active_window_end_hour: float | None = None,
    min_free_memory_bytes: int = DEFAULT_MIN_FREE_MEMORY_BYTES,
    min_free_disk_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES,
    daily_disk_growth_bytes: int | None = None,
    min_disk_headroom_days: float = DEFAULT_MIN_DISK_HEADROOM_DAYS,
    loop_specs: tuple[CaptureLoopSpec, ...] | list[CaptureLoopSpec] | None = None,
    now: datetime | None = None,
    process_checker: Callable[[Any], bool] = process_is_running,
    memory_available_fn: Callable[[], int | None] = available_memory_bytes,
    disk_usage_fn: Callable[[str | Path], Any] = shutil.disk_usage,
) -> dict[str, Any]:
    """Return whether heavy work may start; no mutations are performed."""

    if capture_mode not in CAPTURE_MODES:
        raise ValueError(f"capture_mode must be one of {', '.join(CAPTURE_MODES)}")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    in_active_window, active_window_source = _configured_active_window(
        current,
        capture_mode=capture_mode,
        active_window=active_window,
        active_window_start_hour=active_window_start_hour,
        active_window_end_hour=active_window_end_hour,
    )
    specs = tuple(default_loop_specs(snapshots_root) if loop_specs is None else loop_specs)
    loops = [
        inspect_capture_loop(
            spec,
            now=current,
            process_checker=process_checker,
        )
        for spec in specs
    ]
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    window_end = _next_window_end(
        current,
        active_window_start_hour,
        active_window_end_hour,
    ) if in_active_window else None
    for loop in loops:
        loop_defer = max(300.0, 2.0 * float(loop.get("interval_seconds") or 0.0))
        if window_end:
            loop_defer = max(loop_defer, (window_end - current).total_seconds())
        if capture_mode != "live":
            if loop.get("active"):
                blockers.append(_blocker(
                    "capture_mode_conflict_live_loop_detected",
                    f"{loop['name']} is active although capture_mode={capture_mode}",
                    defer_seconds=loop_defer,
                    loop=loop["name"],
                    state=loop["state"],
                    status_path=loop["status_path"],
                ))
            continue
        if loop.get("active"):
            blockers.append(_blocker(
                "live_capture_loop_active",
                f"{loop['name']} is active; isolate heavy work from this capture host",
                defer_seconds=loop_defer,
                loop=loop["name"],
                state=loop["state"],
                status_path=loop["status_path"],
                heartbeat_age_seconds=loop.get("heartbeat_age_seconds"),
            ))
        if in_active_window and loop.get("required") and loop.get("degraded"):
            blockers.append(_blocker(
                "capture_freshness_degraded",
                f"{loop['name']} capture evidence is degraded during the active window",
                defer_seconds=loop_defer,
                loop=loop["name"],
                state=loop["state"],
                degraded_reasons=loop["degraded_reasons"],
                status_path=loop["status_path"],
            ))
        elif not in_active_window and loop.get("degraded"):
            warnings.append({
                "code": "capture_freshness_degraded_outside_window",
                "loop": loop["name"],
                "degraded_reasons": loop["degraded_reasons"],
            })

    memory_available = memory_available_fn()
    memory_status = "PASS"
    if memory_available is None:
        memory_status = "BLOCK"
        blockers.append(_blocker(
            "free_memory_unavailable",
            "available physical memory could not be measured",
            defer_seconds=900,
            required_bytes=int(min_free_memory_bytes),
        ))
    elif int(memory_available) < int(min_free_memory_bytes):
        memory_status = "BLOCK"
        blockers.append(_blocker(
            "insufficient_free_memory",
            "available physical memory is below the configured admission reserve",
            defer_seconds=900,
            available_bytes=int(memory_available),
            required_bytes=int(min_free_memory_bytes),
            shortfall_bytes=int(min_free_memory_bytes) - int(memory_available),
        ))
    disk_error = None
    disk_total = disk_used = disk_free = None
    try:
        usage_path = Path(disk_path)
        usage = disk_usage_fn(usage_path if usage_path.exists() else usage_path.parent)
        disk_total = int(usage.total)
        disk_used = int(usage.used)
        disk_free = int(usage.free)
    except (OSError, ValueError, AttributeError) as exc:
        disk_error = f"{type(exc).__name__}: {exc}"
    disk_status = "PASS"
    if disk_free is None:
        disk_status = "BLOCK"
        blockers.append(_blocker(
            "disk_headroom_unavailable",
            "disk free space could not be measured",
            defer_seconds=1800,
            path=str(disk_path),
            error=disk_error,
        ))
    elif disk_free < int(min_free_disk_bytes):
        disk_status = "BLOCK"
        blockers.append(_blocker(
            "insufficient_free_disk",
            "disk free space is below the configured admission reserve",
            defer_seconds=1800,
            path=str(disk_path),
            available_bytes=disk_free,
            required_bytes=int(min_free_disk_bytes),
            shortfall_bytes=int(min_free_disk_bytes) - disk_free,
        ))
    daily_growth = int(daily_disk_growth_bytes) if daily_disk_growth_bytes not in (None, "") else None
    growth_headroom_days = (
        float(disk_free) / daily_growth
        if disk_free is not None and daily_growth and daily_growth > 0
        else None
    )
    growth_status = "NOT_EVALUATED"
    if growth_headroom_days is not None:
        growth_status = "PASS" if growth_headroom_days >= float(min_disk_headroom_days) else "BLOCK"
        if growth_status == "BLOCK":
            disk_status = "BLOCK"
            blockers.append(_blocker(
                "insufficient_disk_growth_headroom",
                "projected disk headroom is below the configured day reserve",
                defer_seconds=1800,
                growth_headroom_days=growth_headroom_days,
                required_days=float(min_disk_headroom_days),
                daily_growth_bytes=daily_growth,
            ))
    defer_seconds = max((row["defer_seconds"] for row in blockers), default=0.0)
    suggested_defer = current + timedelta(seconds=defer_seconds) if blockers else None
    status = "PASS" if not blockers else "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(current),
        "evidence_contract": EVIDENCE_CONTRACT,
        "status": status,
        "admitted": status == "PASS",
        "decision": "ADMIT" if status == "PASS" else "DEFER",
        "workload": str(workload),
        "configuration": {
            "capture_mode": capture_mode,
            "active_window": in_active_window,
            "active_window_source": active_window_source,
            "active_window_start_hour": active_window_start_hour,
            "active_window_end_hour": active_window_end_hour,
            "min_free_memory_bytes": int(min_free_memory_bytes),
            "min_free_disk_bytes": int(min_free_disk_bytes),
            "daily_disk_growth_bytes": daily_growth,
            "min_disk_headroom_days": float(min_disk_headroom_days),
        },
        "summary": {
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "active_loop_count": sum(1 for row in loops if row.get("active")),
            "degraded_loop_count": sum(1 for row in loops if row.get("degraded")),
            "suggested_defer_seconds": defer_seconds if blockers else None,
            "suggested_defer_until_utc": utc_iso(suggested_defer) if suggested_defer else None,
            "recommended_action": (
                "defer heavyweight work and preserve capture resources"
                if blockers
                else "heavyweight work may start under its normal process-tree guard"
            ),
        },
        "blockers": blockers,
        "warnings": warnings,
        "loops": loops,
        "resources": {
            "memory": {
                "status": memory_status,
                "available_bytes": int(memory_available) if memory_available is not None else None,
                "required_bytes": int(min_free_memory_bytes),
            },
            "disk": {
                "status": disk_status,
                "path": str(disk_path),
                "error": disk_error,
                "total_bytes": disk_total,
                "used_bytes": disk_used,
                "free_bytes": disk_free,
                "required_free_bytes": int(min_free_disk_bytes),
                "daily_growth_bytes": daily_growth,
                "growth_headroom_days": growth_headroom_days,
                "growth_headroom_status": growth_status,
                "required_growth_headroom_days": float(min_disk_headroom_days),
            },
        },
        "safety_contract": {
            "read_only": True,
            "process_discovery_is_diagnostic_only": True,
            "stops_or_signals_processes": False,
            "live_evidence_contract": "status heartbeat plus single-writer lock, corroborated by PID diagnostics",
        },
    }


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    resources = payload.get("resources") or {}
    lines = [
        "# Capture Resource Admission Gate",
        "",
            f"Generated: `{payload.get('generated_at_utc')}`",
            f"Status: `{payload.get('status')}`",
            f"Decision: `{payload.get('decision')}`",
            f"Workload: `{payload.get('workload')}`",
        "",
        "## Decision",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [[key, value] for key, value in summary.items()],
        ),
        "",
        "## Blockers",
        "",
        *markdown_table(
            ["Code", "Detail", "Evidence"],
            [
                [row.get("code"), row.get("detail"), json.dumps(row.get("evidence") or {}, sort_keys=True)]
                for row in payload.get("blockers") or []
            ],
        ),
        "",
        "## Capture Loops",
        "",
        *markdown_table(
            ["Loop", "State", "Active", "Heartbeat Age", "Degraded Reasons", "Status Path"],
            [
                [
                    row.get("name"),
                    row.get("state"),
                    row.get("active"),
                    row.get("heartbeat_age_seconds"),
                    ", ".join(row.get("degraded_reasons") or []),
                    row.get("status_path"),
                ]
                for row in payload.get("loops") or []
            ],
        ),
        "",
        "## Host Resources",
        "",
        *markdown_table(
            ["Resource", "Status", "Evidence"],
            [
                [name, row.get("status"), json.dumps(row, sort_keys=True)]
                for name, row in resources.items()
            ],
        ),
        "",
        "The gate is read-only and never stops, pauses, restarts, or signals collection processes.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write_text(path: str | Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


def write_outputs(
    payload: dict[str, Any],
    *,
    out: str | Path = DEFAULT_OUT,
    report: str | Path = DEFAULT_REPORT,
) -> tuple[Path, Path]:
    out_path = _atomic_write_text(out, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    report_path = _atomic_write_text(report, render_report(payload))
    return out_path, report_path


def persist_pipeline_admission(
    *,
    workload: str,
    out: str | Path = DEFAULT_OUT,
    report: str | Path = DEFAULT_REPORT,
    gate_builder: Callable[..., dict[str, Any]] | None = None,
    output_writer: Callable[..., tuple[Path, Path]] | None = None,
    **gate_kwargs: Any,
) -> tuple[dict[str, Any], Path | None, Path | None]:
    """Evaluate and atomically persist a pre-heavy-work admission decision.

    The enforcement receipt records ordering, not topology: the caller invokes
    this function before starting a heavy child and must honor ``decision``.
    A persistence failure converts even an otherwise admissible result to a
    fail-closed DEFER decision.
    """

    builder = gate_builder or build_capture_resource_gate
    writer = output_writer or write_outputs
    try:
        payload = builder(workload=workload, **gate_kwargs)
    except Exception as exc:  # noqa: BLE001 - evaluation failure must deny heavy work
        generated = utc_iso()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": generated,
            "evidence_contract": EVIDENCE_CONTRACT,
            "status": "BLOCK",
            "admitted": False,
            "decision": "DEFER",
            "workload": str(workload),
            "configuration": {
                "capture_mode": gate_kwargs.get("capture_mode"),
            },
            "summary": {
                "blocker_count": 1,
                "warning_count": 0,
                "active_loop_count": None,
                "degraded_loop_count": None,
                "suggested_defer_seconds": 900.0,
                "suggested_defer_until_utc": utc_iso(
                    datetime.now(timezone.utc) + timedelta(seconds=900)
                ),
                "recommended_action": (
                    "defer heavyweight work until admission can be evaluated"
                ),
            },
            "blockers": [
                _blocker(
                    "admission_evaluation_failed",
                    "capture-resource admission could not be evaluated",
                    defer_seconds=900,
                    error=f"{type(exc).__name__}: {exc}",
                )
            ],
            "warnings": [],
            "loops": [],
            "resources": {
                "memory": {"status": "BLOCK"},
                "disk": {"status": "BLOCK"},
            },
            "safety_contract": {
                "read_only": True,
                "process_discovery_is_diagnostic_only": True,
                "stops_or_signals_processes": False,
            },
        }
    decision = "ADMIT" if payload.get("admitted") is True else "DEFER"
    payload["decision"] = decision
    payload["evidence_contract"] = EVIDENCE_CONTRACT
    payload["enforcement"] = {
        "status": "PASS",
        "consumer": str(workload),
        "evaluated_before_heavy_work": True,
        "heavy_child_started_before_decision": False,
        "outcome": (
            "ADMITTED_BEFORE_HEAVY_WORK"
            if decision == "ADMIT"
            else "DEFERRED_BEFORE_HEAVY_WORK"
        ),
        "proof_persisted": True,
        "json_path": str(out),
        "report_path": str(report),
    }
    try:
        out_path, report_path = writer(payload, out=out, report=report)
    except Exception as exc:  # noqa: BLE001 - proof failure must deny heavy work
        failure = _blocker(
            "admission_proof_persistence_failed",
            "capture-resource admission proof could not be persisted",
            defer_seconds=900,
            out=str(out),
            report=str(report),
            error=f"{type(exc).__name__}: {exc}",
        )
        payload.setdefault("blockers", []).append(failure)
        payload["status"] = "BLOCK"
        payload["admitted"] = False
        payload["decision"] = "DEFER"
        summary = payload.setdefault("summary", {})
        summary["blocker_count"] = len(payload["blockers"])
        summary["suggested_defer_seconds"] = max(
            float(summary.get("suggested_defer_seconds") or 0.0),
            900.0,
        )
        summary["recommended_action"] = (
            "defer heavyweight work until the admission proof persists"
        )
        payload["enforcement"].update(
            {
                "status": "BLOCK",
                "outcome": "DEFERRED_BEFORE_HEAVY_WORK",
                "proof_persisted": False,
                "persistence_error": f"{type(exc).__name__}: {exc}",
            }
        )
        try:
            _atomic_write_text(
                out,
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
            )
        except Exception:  # noqa: BLE001 - absence is also fail-closed to consumers
            pass
        return payload, None, None
    return payload, out_path, report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only admission gate for heavy work on capture hosts.")
    parser.add_argument("--workload", default="heavyweight_work")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--disk-path", default=str(DEFAULT_DISK_PATH))
    parser.add_argument("--capture-mode", choices=CAPTURE_MODES, default="live")
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--active-window", dest="active_window", action="store_true")
    window.add_argument("--outside-active-window", dest="active_window", action="store_false")
    parser.set_defaults(active_window=None)
    parser.add_argument("--active-window-start-hour", type=float, default=None)
    parser.add_argument("--active-window-end-hour", type=float, default=None)
    parser.add_argument("--min-free-memory-bytes", type=int, default=DEFAULT_MIN_FREE_MEMORY_BYTES)
    parser.add_argument("--min-free-disk-bytes", type=int, default=DEFAULT_MIN_FREE_DISK_BYTES)
    parser.add_argument("--daily-disk-growth-bytes", type=int, default=None)
    parser.add_argument("--min-disk-headroom-days", type=float, default=DEFAULT_MIN_DISK_HEADROOM_DAYS)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    payload = build_capture_resource_gate(
        workload=args.workload,
        snapshots_root=args.snapshots_root,
        disk_path=args.disk_path,
        capture_mode=args.capture_mode,
        active_window=args.active_window,
        active_window_start_hour=args.active_window_start_hour,
        active_window_end_hour=args.active_window_end_hour,
        min_free_memory_bytes=args.min_free_memory_bytes,
        min_free_disk_bytes=args.min_free_disk_bytes,
        daily_disk_growth_bytes=args.daily_disk_growth_bytes,
        min_disk_headroom_days=args.min_disk_headroom_days,
    )
    if not args.no_write:
        out, report = write_outputs(payload, out=args.out, report=args.report)
        print(f"JSON written to {out}")
        print(f"Report written to {report}")
    print(
        "Capture resource gate: "
        f"{payload['status']} blockers={payload['summary']['blocker_count']} "
        f"active_loops={payload['summary']['active_loop_count']}"
    )
    if args.fail_on_block and payload["status"] == "BLOCK":
        raise SystemExit(2)
    return payload


if __name__ == "__main__":
    main()
