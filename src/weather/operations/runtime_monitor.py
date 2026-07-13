"""Bounded, read-only host and runtime soak monitor.

The monitor intentionally avoids importing collection/model/bot modules.  Those
imports are expensive on the dedicated capture host and the durable status JSON
files are the operational contract needed here.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from weather.io import append_jsonl, write_json_atomic
from weather.paths import REPO_ROOT, data_path, relative_to_repo


SCHEMA_VERSION = "runtime_monitor_v0.1"
TORONTO_TZ = ZoneInfo("America/Toronto")
DEFAULT_OUTPUT_ROOT = data_path("monitoring", "12h")
MAX_LOG_READ_BYTES = 1024 * 1024
OUTPUT_BUDGET_BYTES = 500 * 1024 * 1024
ERROR_RE = re.compile(
    r"(?i)(traceback|memoryerror|oserror|exception|critical|fatal|crash|failed|error)"
)
DISABLED_PAID_PROVIDER_ERROR = "Paid-provider weather endpoints are disabled by project policy"
SECRET_RE = re.compile(
    r"(?i)\b(token|secret|password|authorization|api[-_]?key)\b\s*[:=]\s*([^\s,;]+)"
)

STATUS_SPECS = {
    "snapshot": data_path("snapshots", "loop_status.json"),
    "clob": data_path("snapshots", "clob_loop_status.json"),
    "observation_trigger": data_path("snapshots", "observation_trigger_status.json"),
    "taker": data_path("taker_runs", "daily_roll_status.json"),
    "market_making": data_path("mm_runs", "daily_roll_status.json"),
    "nightly_retrain": data_path("backtest", "nightly_retrain_status.json"),
    "daily_refresh": data_path("backtest", "daily_refresh_status.json"),
    "memory_commit_guard": data_path("logs", "memory_commit_guard_status.json"),
}

LOG_SPECS = {
    "snapshot_diagnostics": data_path("snapshots", "diagnostics.jsonl"),
    "snapshot_console": data_path("snapshots", "loop_console.log"),
    "clob_diagnostics": data_path("snapshots", "clob_diagnostics.jsonl"),
    "clob_console": data_path("snapshots", "clob_loop_console.log"),
    "observation_diagnostics": data_path("snapshots", "observation_trigger_diagnostics.jsonl"),
    "observation_console": data_path("snapshots", "observation_trigger_console.log"),
    "taker_diagnostics": data_path("taker_runs", "daily_roll_diagnostics.jsonl"),
    "taker_console": data_path("taker_runs", "daily_roll_console.log"),
    "maker_diagnostics": data_path("mm_runs", "daily_roll_diagnostics.jsonl"),
    "maker_console": data_path("mm_runs", "daily_roll_console.log"),
    "memory_guard": data_path("logs", "memory_commit_guard.log"),
    "training_window": data_path("logs", "training_window.log"),
}

TASK_NAMES = (
    "WeatherSnapshotLoopSupervisor",
    "WeatherClobBookLoopSupervisor",
    "WeatherObservationTriggerSupervisor",
    "WeatherTakerBotDailyRoll",
    "WeatherTakerBotDailyRollSupervisor",
    "WeatherMarketMakingDailyRoll",
    "WeatherMarketMakingDailyRollSupervisor",
    "WeatherTrainingWindow",
    "WeatherTrainingWindowRestore",
    "WeatherMemoryCommitGuard",
    "WeatherDailySettlementPromotionRefresh",
    "WeatherNightlyRetrainValidatePromote",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any, now: datetime) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return round(max(0.0, (now - parsed).total_seconds()), 3)


def _elapsed_hour_index(started_at: datetime, now: datetime) -> int:
    """Return the zero-based elapsed hour on the run's immutable wall clock."""

    return max(0, int((now - started_at).total_seconds() // 3600))


def _load_recent_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    """Load a bounded tail of valid JSON objects for resume continuity."""

    rows: deque[dict[str, Any]] = deque(maxlen=max(1, int(limit)))
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return []
    return list(rows)


def _samples_for_elapsed_hour(
    samples: list[dict[str, Any]],
    started_at: datetime,
    hour_number: int,
) -> list[dict[str, Any]]:
    """Select samples inside one exact original-run elapsed-hour bucket."""

    bucket_start = started_at + timedelta(hours=max(0, hour_number - 1))
    bucket_end = bucket_start + timedelta(hours=1)
    selected = []
    for sample in samples:
        observed_at = _parse_time(sample.get("observed_at_utc"))
        if observed_at is not None and bucket_start <= observed_at < bucket_end:
            selected.append(sample)
    return selected


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return None, "not_an_object"
    return payload, None


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _sanitize(text: Any, limit: int = 800) -> str:
    value = SECRET_RE.sub(lambda match: f"{match.group(1)}=<redacted>", str(text or ""))
    value = value.replace("\x00", "")
    return value[:limit]


def _signature(text: Any) -> str | None:
    if not text:
        return None
    normalized = _sanitize(text, 2000).lower()
    normalized = re.sub(r"0x[0-9a-f]+", "<hex>", normalized)
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", normalized)
    normalized = re.sub(r"[a-z]:\\[^\s\"']+", "<path>", normalized)
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:20]


def _is_expected_policy_error(path: str, value: Any) -> bool:
    """Identify source-status sentinels that enforce the no-paid-provider contract."""

    low_path = path.lower()
    return (
        low_path.endswith(".error")
        and ".source_status.wu_" in low_path
        and isinstance(value, str)
        and value.startswith(DISABLED_PAID_PROVIDER_ERROR)
    )


def _json_error_evidence(value: Any, path: str = "") -> list[str]:
    """Return only populated error-bearing JSON fields.

    Runtime diagnostics deliberately include stable keys such as ``error`` and
    ``errors`` on successful rows.  Matching the serialized key name alone
    creates one false incident per healthy tick, so JSON lines are interpreted
    structurally before the plain-text fallback is used.
    """

    evidence: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            low = str(key).lower()
            populated = item not in (None, "", False, 0, [], {})
            error_field = (
                low in {"error", "errors", "last_error", "exception", "traceback"}
                or low.endswith("_error")
                or low.endswith("_errors")
                or low.endswith("_error_count")
            )
            if error_field and populated and not _is_expected_policy_error(child_path, item):
                evidence.append(f"{child_path}={_sanitize(item, 300)}")
            elif low in {"status", "state"} and str(item).lower() in {
                "error",
                "failed",
                "critical",
                "fatal",
            }:
                evidence.append(f"{child_path}={_sanitize(item, 100)}")
            elif isinstance(item, (dict, list)):
                evidence.extend(_json_error_evidence(item, child_path))
            if len(evidence) >= 20:
                break
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, (dict, list)):
                evidence.extend(_json_error_evidence(item, f"{path}[{index}]"))
            if len(evidence) >= 20:
                break
    return evidence


def _file_artifact(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"path": relative_to_repo(path), "exists": False}
    return {
        "path": relative_to_repo(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _runtime_identity(payload: dict[str, Any]) -> dict[str, Any]:
    identity = payload.get("runtime_identity") or {}
    return {
        key: identity.get(key)
        for key in ("git_branch", "git_commit", "git_dirty", "source_fingerprint", "python_version")
        if identity.get(key) is not None
    }


def _market_counts(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("last_market_results") or {}
    if isinstance(results, list):
        rows = [row for row in results if isinstance(row, dict)]
    elif isinstance(results, dict):
        rows = [row for row in results.values() if isinstance(row, dict)]
    else:
        rows = []
    error_count = sum(
        1
        for row in rows
        if row.get("error") or str(row.get("status") or "").lower() in {"error", "failed", "timeout"}
    )
    return {
        "markets": len(rows) or None,
        "success_markets": (len(rows) - error_count) if rows else None,
        "error_markets": error_count if rows else None,
    }


FORECAST_PAYLOAD_STORAGE_SCHEMA_VERSION = "forecast_payload_storage_observability_v0.1"
FORECAST_PAYLOAD_STORAGE_COUNT_FIELDS = (
    "manifest_row_count",
    "created_blob_count",
    "reused_blob_count",
    "logical_referenced_bytes",
    "physical_bytes_written",
    "avoided_bytes",
)


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    parsed = _safe_int(value)
    return parsed if parsed is not None and parsed >= 0 else None


def _compact_forecast_payload_storage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if value.get("schema_version") != FORECAST_PAYLOAD_STORAGE_SCHEMA_VERSION:
        return None
    projected = {"schema_version": FORECAST_PAYLOAD_STORAGE_SCHEMA_VERSION}
    for field in FORECAST_PAYLOAD_STORAGE_COUNT_FIELDS:
        projected[field] = _nonnegative_int(value.get(field)) or 0
    projected["physical_write_budget_bytes"] = _nonnegative_int(
        value.get("physical_write_budget_bytes")
    )
    budget_status = str(value.get("physical_write_budget_status") or "").upper()
    projected["physical_write_budget_status"] = (
        budget_status
        if budget_status in {"PASS", "BLOCK", "NOT_CONFIGURED"}
        else "NOT_CONFIGURED"
    )
    return projected


def _forecast_payload_storage(payload: dict[str, Any]) -> dict[str, Any] | None:
    direct = _compact_forecast_payload_storage(payload.get("forecast_payload_storage"))
    if direct is not None:
        return direct

    results = payload.get("last_market_results") or {}
    if isinstance(results, list):
        candidates = results
    elif isinstance(results, dict):
        candidates = results.values()
    else:
        candidates = []
    rows = []
    for result in candidates:
        if not isinstance(result, dict):
            continue
        row = _compact_forecast_payload_storage(result.get("forecast_payload_storage"))
        if row is not None:
            rows.append(row)
    if not rows:
        return None

    summary = {
        "schema_version": FORECAST_PAYLOAD_STORAGE_SCHEMA_VERSION,
        **{
            field: sum(row[field] for row in rows)
            for field in FORECAST_PAYLOAD_STORAGE_COUNT_FIELDS
        },
    }
    budgets = [row["physical_write_budget_bytes"] for row in rows]
    all_budgets_configured = all(value is not None for value in budgets)
    summary["physical_write_budget_bytes"] = (
        sum(budgets) if all_budgets_configured else None
    )
    if any(row["physical_write_budget_status"] == "BLOCK" for row in rows):
        budget_status = "BLOCK"
    elif all_budgets_configured:
        budget_status = (
            "PASS"
            if summary["physical_bytes_written"] <= summary["physical_write_budget_bytes"]
            else "BLOCK"
        )
    else:
        budget_status = "NOT_CONFIGURED"
    summary["physical_write_budget_status"] = budget_status
    return summary


def _planned_window(now: datetime) -> str:
    local = now.astimezone(TORONTO_TZ)
    minutes = local.hour * 60 + local.minute
    if minutes >= 18 * 60 or minutes < 30:
        return "protected"
    if 60 <= minutes < 4 * 60 + 15:
        return "training_window"
    if 30 <= minutes < 9 * 60:
        return "quiet"
    if 9 * 60 + 30 <= minutes < 12 * 60 + 30:
        return "scheduled_heavy"
    return "moderate"


def project_component(name: str, path: Path, payload: dict[str, Any] | None, error: str | None, now: datetime) -> dict[str, Any]:
    payload = payload or {}
    result: dict[str, Any] = {
        "schema_version": "runtime_monitor_component_v0.1",
        "observed_at_utc": utc_iso(now),
        "component": name,
        "state": "UNKNOWN",
        "reason": error,
        "pid": _safe_int(payload.get("pid")),
        "pid_alive": payload.get("pid_alive"),
        "heartbeat_age_seconds": None,
        "capture_age_seconds": None,
        "useful_write_age_seconds": None,
        "consecutive_errors": _safe_int(payload.get("consecutive_errors")) or 0,
        "last_error_signature": _signature(payload.get("last_error")),
        "runtime_identity": _runtime_identity(payload),
        "counts": {},
        "policy": {},
        "supervisor": {},
        "local_load_window": _planned_window(now),
        "status_artifact": _file_artifact(path),
    }
    if error:
        return result

    if name == "snapshot":
        interval = max(60.0, 60.0 * (_safe_float(payload.get("interval_minutes")) or 10.0))
        dead_after = 2.0 * interval + 120.0
        heartbeat_age = _age_seconds(payload.get("last_heartbeat"), now)
        capture_age = _age_seconds(payload.get("last_snapshot_written_at"), now)
        errors = result["consecutive_errors"]
        result.update(
            heartbeat_age_seconds=heartbeat_age,
            capture_age_seconds=capture_age,
            interval_seconds=interval,
            dead_after_seconds=dead_after,
            iteration_elapsed_seconds=round(60.0 * (_safe_float(payload.get("last_iteration_elapsed_minutes")) or 0.0), 3),
            counts={"iterations": _safe_int(payload.get("iterations")), **_market_counts(payload)},
            forecast_payload_storage=_forecast_payload_storage(payload),
        )
        if payload.get("paused"):
            result.update(state="PAUSED", reason="pause_flag")
        elif heartbeat_age is None or heartbeat_age > dead_after:
            result.update(state="UNHEALTHY", reason="heartbeat_stale")
        elif errors > 0:
            result.update(state="UNHEALTHY", reason="consecutive_errors")
        elif capture_age is None or capture_age > dead_after:
            result.update(state="DEGRADED", reason="capture_stale")
        else:
            result.update(state="HEALTHY", reason="fresh")
        return result

    if name == "clob":
        interval = max(1.0, _safe_float(payload.get("interval_seconds")) or 60.0)
        elapsed = _safe_float(payload.get("last_iteration_elapsed_seconds")) or 0.0
        sleep_seconds = _safe_float(payload.get("last_sleep_seconds")) or interval
        dead_after = max(90.0, 2.0 * interval + 30.0, elapsed + sleep_seconds + 30.0)
        heartbeat_age = _age_seconds(payload.get("last_heartbeat"), now)
        capture_age = _age_seconds(payload.get("last_books_captured_at"), now)
        errors = result["consecutive_errors"]
        result.update(
            heartbeat_age_seconds=heartbeat_age,
            capture_age_seconds=capture_age,
            interval_seconds=interval,
            dead_after_seconds=dead_after,
            iteration_elapsed_seconds=elapsed,
            counts={
                "iterations": _safe_int(payload.get("iterations")),
                "error_markets": len(payload.get("error_markets") or []),
            },
        )
        if payload.get("paused"):
            result.update(state="PAUSED", reason="pause_flag")
        elif heartbeat_age is None or heartbeat_age > dead_after:
            result.update(state="UNHEALTHY", reason="heartbeat_stale")
        elif errors > 0 or (result["counts"].get("error_markets") or 0) > 0:
            result.update(state="UNHEALTHY", reason="capture_errors")
        elif capture_age is None or capture_age > dead_after:
            result.update(state="DEGRADED", reason="books_stale")
        else:
            result.update(state="HEALTHY", reason="fresh")
        return result

    if name == "observation_trigger":
        interval = max(1.0, _safe_float(payload.get("interval_seconds")) or 60.0)
        dead_after = max(90.0, 2.0 * interval + 30.0)
        heartbeat_age = _age_seconds(payload.get("last_heartbeat"), now)
        capture_age = _age_seconds(payload.get("last_poll_at_utc"), now)
        result.update(
            heartbeat_age_seconds=heartbeat_age,
            capture_age_seconds=capture_age,
            interval_seconds=interval,
            dead_after_seconds=dead_after,
            counts={
                "iterations": _safe_int(payload.get("iterations")),
                "trigger_count": _safe_int(payload.get("last_trigger_count")),
            },
            policy={"trade_permissioned": (payload.get("trade_permission") or {}).get("trade_permissioned")},
        )
        if payload.get("paused"):
            result.update(state="PAUSED", reason="pause_flag")
        elif heartbeat_age is None or heartbeat_age > dead_after:
            result.update(state="UNHEALTHY", reason="heartbeat_stale")
        elif result["consecutive_errors"] > 0:
            result.update(state="UNHEALTHY", reason="consecutive_errors")
        else:
            result.update(state="HEALTHY", reason="fresh")
        return result

    if name in {"taker", "market_making"}:
        artifact = payload.get("artifact_liveness") or {}
        activity = payload.get("activity_liveness") or {}
        operator = payload.get("operator_report") or {}
        supervisor = payload.get("daily_roll_supervisor") or {}
        useful = payload.get("supervisor_latest_useful_write") or {}
        useful_age = _safe_float(useful.get("age_seconds"))
        native = str(payload.get("status") or "unknown")
        classification = (
            operator.get("taker_day_classification")
            or operator.get("useful_work_liveness_reason")
            or artifact.get("root_cause_class")
            or payload.get("root_cause_class")
        )
        expected = any(
            marker in str(classification or "").lower()
            for marker in ("policy", "after active", "post_settlement", "not all-market")
        ) or str(artifact.get("status") or "").upper() in {"PASS", "POLICY_NO_EDGE", "STARTUP_GRACE"}
        result.update(
            native_state=native,
            useful_write_age_seconds=useful_age,
            pid_alive=payload.get("pid_alive"),
            policy={
                "classification": classification,
                "countability_status": operator.get("evidence_countability_status"),
                "counts_toward_live_forward": payload.get("current_counts_toward_live_forward_gate"),
                "zero_trades_expected": payload.get("zero_trades_expected"),
            },
            supervisor={
                "state": supervisor.get("state") or payload.get("supervisor_state"),
                "action": supervisor.get("action") or payload.get("supervisor_action"),
                "restart_cause": supervisor.get("restart_cause") or payload.get("supervisor_restart_cause"),
                "retry_after_seconds": (supervisor.get("recovery_guard") or {}).get("retry_after_seconds")
                or payload.get("supervisor_retry_after_seconds"),
            },
            counts={
                "latest_rows": operator.get("latest_tick_rows") or operator.get("latest_quote_rows"),
                "fills": operator.get("latest_fill_count") or operator.get("latest_tick_filled_orders"),
            },
        )
        startup = str(artifact.get("status") or activity.get("status") or "").upper() == "STARTUP_GRACE"
        artifact_ok = artifact.get("ok") is True or str(artifact.get("status") or "").upper() == "PASS"
        if startup:
            result.update(state="DEGRADED", reason="startup_grace")
        elif expected:
            result.update(state="HEALTHY" if artifact_ok else "DEGRADED", reason="expected_policy_state")
        elif payload.get("pid_alive") is False:
            result.update(state="UNHEALTHY", reason="process_dead")
        elif artifact_ok:
            result.update(state="HEALTHY", reason="useful_artifact_fresh")
        else:
            result.update(state="UNHEALTHY", reason=str(artifact.get("status") or activity.get("status") or native))
        return result

    if name == "memory_commit_guard":
        commit = _safe_float(payload.get("commit_percent"))
        action = str(payload.get("action") or "none")
        result.update(
            native_state=action,
            counts={"commit_percent": commit, "free_ram_mb": _safe_float(payload.get("free_ram_mb"))},
        )
        if commit is None:
            result.update(state="UNKNOWN", reason="commit_missing")
        elif commit >= 92:
            result.update(state="UNHEALTHY", reason="commit_action_threshold")
        elif commit >= 85:
            result.update(state="DEGRADED", reason="commit_warning_threshold")
        else:
            result.update(state="HEALTHY", reason="below_warning_threshold")
        return result

    native = str(payload.get("status") or (payload.get("summary") or {}).get("status") or "unknown")
    generated_age = _age_seconds(payload.get("generated_at_utc") or payload.get("finished_at_utc"), now)
    result.update(native_state=native, useful_write_age_seconds=generated_age)
    if native.lower() in {"ok", "pass", "passed", "complete", "completed", "success"}:
        result.update(state="HEALTHY", reason="native_success")
    elif native.lower() in {"blocked", "critical", "failed", "error"}:
        result.update(state="UNHEALTHY", reason=f"native_{native.lower()}")
    else:
        result.update(state="DEGRADED", reason=f"native_{native.lower()}")
    return result


class HostSampler:
    """Small standard-library collector for CPU, physical memory, commit, and disk."""

    def __init__(self) -> None:
        self.previous_times: tuple[int, int, int] | None = None
        self.previous_at: float | None = None

    @staticmethod
    def _filetime_value(value: Any) -> int:
        return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)

    def _memory(self) -> dict[str, Any]:
        if os.name != "nt":
            return {"available": False}

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
            return {"available": False, "error": "GlobalMemoryStatusEx_failed"}
        commit_used = int(status.ullTotalPageFile - status.ullAvailPageFile)
        commit_limit = int(status.ullTotalPageFile)
        return {
            "available": True,
            "physical_total_bytes": int(status.ullTotalPhys),
            "physical_available_bytes": int(status.ullAvailPhys),
            "memory_load_percent": float(status.dwMemoryLoad),
            "commit_used_bytes": commit_used,
            "commit_limit_bytes": commit_limit,
            "commit_percent": round(100.0 * commit_used / commit_limit, 3) if commit_limit else None,
        }

    def _cpu(self) -> float | None:
        if os.name != "nt":
            return None
        from ctypes import wintypes

        idle = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None
        current = tuple(self._filetime_value(item) for item in (idle, kernel, user))
        previous = self.previous_times
        self.previous_times = current
        if previous is None:
            return None
        idle_delta = current[0] - previous[0]
        total_delta = (current[1] - previous[1]) + (current[2] - previous[2])
        if total_delta <= 0 or idle_delta < 0:
            return None
        return round(max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta)), 3)

    @staticmethod
    def _self_memory() -> dict[str, Any]:
        if os.name != "nt":
            return {}
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        if not ok:
            return {}
        return {
            "working_set_bytes": int(counters.WorkingSetSize),
            "private_bytes": int(counters.PrivateUsage),
        }

    def sample(self, run_dir: Path) -> dict[str, Any]:
        started = time.monotonic()
        usage = shutil.disk_usage(REPO_ROOT)
        record = {
            "schema_version": "runtime_monitor_host_v0.1",
            "observed_at_utc": utc_iso(),
            "system_cpu_percent": self._cpu(),
            "memory": self._memory(),
            "disk": {
                "path": str(REPO_ROOT.anchor or REPO_ROOT),
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "free_percent": round(100.0 * usage.free / usage.total, 3) if usage.total else None,
            },
            "monitor_process": {"pid": os.getpid(), **self._self_memory()},
            "output_bytes": output_size_bytes(run_dir),
        }
        record["sampler_elapsed_seconds"] = round(time.monotonic() - started, 6)
        return record


def _powershell_enrichment(include_tasks: bool) -> dict[str, Any]:
    if os.name != "nt":
        return {"available": False, "reason": "non_windows"}
    task_names = ",".join(f"'{name}'" for name in TASK_NAMES)
    task_block = "@()"
    if include_tasks:
        task_block = f"""
@({task_names}) | ForEach-Object {{
  $name = $_
  try {{
    $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $name -ErrorAction Stop
    [pscustomobject]@{{name=$name;state=[string]$task.State;enabled=($task.Settings.Enabled -ne $false);last_result=$info.LastTaskResult;last_run=if($info.LastRunTime){{$info.LastRunTime.ToString('o')}}else{{$null}};next_run=if($info.NextRunTime){{$info.NextRunTime.ToString('o')}}else{{$null}}}}
  }} catch {{ [pscustomobject]@{{name=$name;state='missing';enabled=$false;error=$_.Exception.GetType().Name}} }}
}}
"""
    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$processes = @(Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -match '(?i)(-m\\s+weather\\.|streamlit.*weather)' }} | ForEach-Object {{
  $commandHash = $null
  if ($_.CommandLine) {{
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{
      $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$_.CommandLine))
      $commandHash = ([BitConverter]::ToString($digest)).Replace('-', '').Substring(0,16).ToLowerInvariant()
    }} finally {{ $sha.Dispose() }}
  }}
  [pscustomobject]@{{pid=$_.ProcessId;parent_pid=$_.ParentProcessId;name=$_.Name;threads=$_.ThreadCount;handles=$_.HandleCount;working_set_bytes=[long]$_.WorkingSetSize;private_bytes=[long]$_.PrivatePageCount;read_bytes=[long]$_.ReadTransferCount;write_bytes=[long]$_.WriteTransferCount;cpu_100ns=([long]$_.KernelModeTime+[long]$_.UserModeTime);command_hash=$commandHash}}
}})
$disk = Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'"
$net = @(Get-CimInstance Win32_PerfFormattedData_Tcpip_NetworkInterface)
$tasks = {task_block}
[pscustomobject]@{{processes=$processes;disk=if($disk){{[pscustomobject]@{{busy_percent=$disk.PercentDiskTime;queue_length=$disk.CurrentDiskQueueLength;read_bytes_per_sec=$disk.DiskReadBytesPersec;write_bytes_per_sec=$disk.DiskWriteBytesPersec}}}}else{{$null}};network=[pscustomobject]@{{receive_bytes_per_sec=($net|Measure-Object BytesReceivedPersec -Sum).Sum;send_bytes_per_sec=($net|Measure-Object BytesSentPersec -Sum).Sum}};tasks=$tasks}} | ConvertTo-Json -Compress -Depth 6
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    if result.returncode != 0:
        return {"available": False, "error": _sanitize(result.stderr or result.stdout)}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"available": False, "error": f"JSONDecodeError: {exc}"}
    payload["available"] = True
    payload["observed_at_utc"] = utc_iso()
    return payload


def _cursor_for(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"path": str(path), "offset": 0, "exists": False, "identity": None}
    return {
        "path": str(path),
        "offset": stat.st_size,
        "exists": True,
        "identity": [stat.st_dev, stat.st_ino],
        "modified_ns": stat.st_mtime_ns,
    }


def scan_log(cursor: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = Path(cursor["path"])
    events: list[dict[str, Any]] = []
    try:
        stat = path.stat()
    except FileNotFoundError:
        cursor.update(exists=False)
        return cursor, events
    identity = [stat.st_dev, stat.st_ino]
    offset = int(cursor.get("offset") or 0)
    if cursor.get("identity") not in (None, identity) or stat.st_size < offset:
        events.append({"event_type": "log_rotated_or_truncated", "severity": "INFO", "summary": relative_to_repo(path)})
        offset = 0
    if stat.st_size <= offset:
        cursor.update(exists=True, identity=identity, modified_ns=stat.st_mtime_ns)
        return cursor, events
    with path.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read(MAX_LOG_READ_BYTES)
    last_newline = chunk.rfind(b"\n")
    if last_newline < 0:
        return cursor, events
    consumed = chunk[: last_newline + 1]
    cursor.update(
        offset=offset + len(consumed),
        exists=True,
        identity=identity,
        modified_ns=stat.st_mtime_ns,
    )
    seen: set[str] = set()
    for raw_line in consumed.splitlines():
        line = raw_line.decode("utf-8", errors="replace")
        parsed: Any = None
        if line.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                parsed = None
        if parsed is not None:
            populated_errors = _json_error_evidence(parsed)
            if not populated_errors:
                continue
            summary = "; ".join(populated_errors)
        else:
            if not ERROR_RE.search(line):
                continue
            summary = line
        signature = _signature(summary)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        events.append(
            {
                "event_type": "new_log_error_signature",
                "severity": "ERROR",
                "incident_signature": signature,
                "summary": _sanitize(summary),
                "evidence_path": relative_to_repo(path),
            }
        )
        if len(events) >= 20:
            break
    return cursor, events


def _git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, text=True, capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def output_size_bytes(run_dir: Path) -> int:
    total = 0
    try:
        paths = run_dir.rglob("*")
        for path in paths:
            if path.is_file():
                try:
                    total += path.stat().st_size
                except FileNotFoundError:
                    continue
    except FileNotFoundError:
        return 0
    return total


def create_run(
    output_root: Path,
    duration_hours: float,
    host_interval_seconds: float,
    component_interval_seconds: float,
    task_interval_seconds: float,
    *,
    now: datetime | None = None,
) -> Path:
    now = now or utc_now()
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "incidents").mkdir()
    log_cursors = {name: _cursor_for(path) for name, path in LOG_SPECS.items()}
    planned_end = now + timedelta(hours=duration_hours)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "repo_root": str(REPO_ROOT),
        "started_at_utc": utc_iso(now),
        "started_at_local": now.astimezone(TORONTO_TZ).isoformat(),
        "planned_end_at_utc": utc_iso(planned_end),
        "planned_end_at_local": planned_end.astimezone(TORONTO_TZ).isoformat(),
        "duration_hours": duration_hours,
        "host_interval_seconds": host_interval_seconds,
        "component_interval_seconds": component_interval_seconds,
        "task_interval_seconds": task_interval_seconds,
        "git": {
            "branch": _git_value("branch", "--show-current"),
            "commit": _git_value("rev-parse", "HEAD"),
            "status_porcelain": _git_value("status", "--porcelain"),
        },
        "python_version": sys.version,
        "pid": os.getpid(),
        "initial_log_cursors": log_cursors,
        "initial_status_artifacts": {name: _file_artifact(path) for name, path in STATUS_SPECS.items()},
    }
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    state = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "lifecycle": "starting",
        "pid": os.getpid(),
        "started_at_utc": manifest["started_at_utc"],
        "planned_end_at_utc": manifest["planned_end_at_utc"],
        "last_heartbeat_at_utc": utc_iso(now),
        "host_sequence": 0,
        "component_sequence": 0,
        "log_cursors": log_cursors,
        "last_component_states": {},
    }
    write_json_atomic(run_dir / "run_state.json", state)
    write_json_atomic(output_root / "latest_run.json", {"run_id": run_id, "run_dir": str(run_dir)})
    for name in ("host_samples.jsonl", "host_minutes.jsonl", "component_health.jsonl", "events.jsonl", "hourly_summaries.jsonl"):
        (run_dir / name).touch()
    return run_dir


def _load_run(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, manifest_error = _read_json(run_dir / "run_manifest.json")
    state, state_error = _read_json(run_dir / "run_state.json")
    if manifest_error or state_error or manifest is None or state is None:
        raise RuntimeError(f"unreadable run: manifest={manifest_error}; state={state_error}")
    return manifest, state


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def summarize_host_samples(samples: list[dict[str, Any]], *, bucket: str) -> dict[str, Any]:
    paths = {
        "system_cpu_percent": lambda row: row.get("system_cpu_percent"),
        "commit_percent": lambda row: (row.get("memory") or {}).get("commit_percent"),
        "physical_available_mb": lambda row: ((_safe_float((row.get("memory") or {}).get("physical_available_bytes")) or 0.0) / 1024**2),
        "disk_free_gb": lambda row: ((_safe_float((row.get("disk") or {}).get("free_bytes")) or 0.0) / 1024**3),
        "monitor_private_mb": lambda row: ((_safe_float((row.get("monitor_process") or {}).get("private_bytes")) or 0.0) / 1024**2),
        "sampler_elapsed_seconds": lambda row: row.get("sampler_elapsed_seconds"),
    }
    metrics: dict[str, Any] = {}
    for name, getter in paths.items():
        values = [value for row in samples if (value := _safe_float(getter(row))) is not None]
        metrics[name] = {
            "count": len(values),
            "median": round(statistics.median(values), 4) if values else None,
            "p95": round(_percentile(values, 0.95), 4) if values else None,
            "max": round(max(values), 4) if values else None,
            "first": round(values[0], 4) if values else None,
            "last": round(values[-1], 4) if values else None,
        }
    return {
        "schema_version": "runtime_monitor_summary_v0.1",
        "bucket": bucket,
        "generated_at_utc": utc_iso(),
        "sample_count": len(samples),
        "metrics": metrics,
    }


def _component_tick(run_dir: Path, state: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    records = []
    for name, path in STATUS_SPECS.items():
        payload, error = _read_json(path)
        record = project_component(name, path, payload, error, now)
        record["run_id"] = state["run_id"]
        append_jsonl(run_dir / "component_health.jsonl", record)
        records.append(record)
        previous = (state.get("last_component_states") or {}).get(name)
        current = record.get("state")
        if previous != current:
            append_jsonl(
                run_dir / "events.jsonl",
                {
                    "schema_version": "runtime_monitor_event_v0.1",
                    "run_id": state["run_id"],
                    "observed_at_utc": utc_iso(now),
                    "component": name,
                    "event_type": "component_state_transition",
                    "severity": "ERROR" if current == "UNHEALTHY" else "INFO",
                    "transition_from": previous,
                    "transition_to": current,
                    "summary": record.get("reason"),
                },
            )
        state.setdefault("last_component_states", {})[name] = current

    for name, cursor in list((state.get("log_cursors") or {}).items()):
        updated, events = scan_log(cursor)
        state["log_cursors"][name] = updated
        for event in events:
            event.update(
                schema_version="runtime_monitor_event_v0.1",
                run_id=state["run_id"],
                observed_at_utc=utc_iso(now),
                component=name,
            )
            append_jsonl(run_dir / "events.jsonl", event)
    state["component_sequence"] = int(state.get("component_sequence") or 0) + 1
    return records


def finalize_run(run_dir: Path, *, lifecycle: str = "completed") -> dict[str, Any]:
    manifest, state = _load_run(run_dir)
    finished = utc_now()
    state.update(
        lifecycle=lifecycle,
        finished_at_utc=utc_iso(finished),
        last_heartbeat_at_utc=utc_iso(finished),
        output_bytes=output_size_bytes(run_dir),
    )
    write_json_atomic(run_dir / "run_state.json", state)
    summary = {
        "schema_version": "runtime_monitor_final_v0.1",
        "run_id": manifest["run_id"],
        "started_at_utc": manifest["started_at_utc"],
        "planned_end_at_utc": manifest["planned_end_at_utc"],
        "finished_at_utc": state["finished_at_utc"],
        "lifecycle": lifecycle,
        "host_samples": state.get("host_sequence", 0),
        "component_ticks": state.get("component_sequence", 0),
        "last_component_states": state.get("last_component_states", {}),
        "output_bytes": state["output_bytes"],
        "artifacts": {
            name: str(run_dir / name)
            for name in (
                "run_manifest.json",
                "run_state.json",
                "host_samples.jsonl",
                "host_minutes.jsonl",
                "component_health.jsonl",
                "events.jsonl",
                "hourly_summaries.jsonl",
            )
        },
    }
    write_json_atomic(run_dir / "summary.json", summary)
    report = [
        f"# 12-Hour Runtime Monitor - {manifest['run_id']}",
        "",
        f"- Lifecycle: `{lifecycle}`",
        f"- Started UTC: `{manifest['started_at_utc']}`",
        f"- Planned end UTC: `{manifest['planned_end_at_utc']}`",
        f"- Finished UTC: `{state['finished_at_utc']}`",
        f"- Host samples: `{summary['host_samples']}`",
        f"- Component ticks: `{summary['component_ticks']}`",
        f"- Output bytes: `{summary['output_bytes']}`",
        "",
        "This generated report is a monitor lifecycle summary. Incident diagnosis,",
        "pre/post-fix comparison, and optimization conclusions require operator review",
        "of the structured artifacts listed in `summary.json`.",
        "",
    ]
    (run_dir / "final_report.md").write_text("\n".join(report), encoding="utf-8")
    return summary


def run_monitor(run_dir: Path, *, sleep_fn=time.sleep, monotonic_fn=time.monotonic) -> dict[str, Any]:
    manifest, state = _load_run(run_dir)
    started_at = _parse_time(manifest["started_at_utc"])
    end_at = _parse_time(manifest["planned_end_at_utc"])
    if started_at is None or end_at is None:
        raise RuntimeError("manifest start or planned end timestamp is invalid")
    host_interval = max(10.0, min(30.0, float(manifest["host_interval_seconds"])))
    component_interval = max(30.0, float(manifest["component_interval_seconds"]))
    task_interval = max(60.0, float(manifest["task_interval_seconds"]))
    state.update(lifecycle="running", pid=os.getpid(), last_heartbeat_at_utc=utc_iso())
    write_json_atomic(run_dir / "run_state.json", state)
    sampler = HostSampler()
    recent_limit = max(10, int(3900 / host_interval))
    recent_samples: deque[dict[str, Any]] = deque(
        _load_recent_jsonl(run_dir / "host_samples.jsonl", recent_limit),
        maxlen=recent_limit,
    )
    baseline_minutes: list[dict[str, Any]] = []
    next_component = 0.0
    next_tasks = 0.0
    last_minute: str | None = None
    last_hour_index = _elapsed_hour_index(started_at, utc_now())
    stop_requested = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_handlers: dict[int, Any] = {}
    for signum in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if signum is not None:
            previous_handlers[signum] = signal.signal(signum, request_stop)
    try:
        while utc_now() < end_at and not stop_requested:
            loop_started = monotonic_fn()
            now = utc_now()
            due_component = loop_started >= next_component
            due_tasks = loop_started >= next_tasks
            if due_component:
                _component_tick(run_dir, state, now)
                next_component = loop_started + component_interval
            sample = sampler.sample(run_dir)
            if due_component:
                sample["enrichment"] = _powershell_enrichment(include_tasks=due_tasks)
                if due_tasks:
                    next_tasks = loop_started + task_interval
            append_jsonl(run_dir / "host_samples.jsonl", sample)
            recent_samples.append(sample)
            state["host_sequence"] = int(state.get("host_sequence") or 0) + 1
            state["last_heartbeat_at_utc"] = utc_iso(now)
            state["output_bytes"] = output_size_bytes(run_dir)
            if state["output_bytes"] > OUTPUT_BUDGET_BYTES:
                state["lifecycle"] = "output_budget_exceeded"
                write_json_atomic(run_dir / "run_state.json", state)
                return finalize_run(run_dir, lifecycle="output_budget_exceeded")

            minute = now.strftime("%Y-%m-%dT%H:%MZ")
            if last_minute is None:
                last_minute = minute
            elif minute != last_minute:
                minute_samples = [row for row in recent_samples if str(row.get("observed_at_utc", "")).startswith(last_minute[:16])]
                minute_summary = summarize_host_samples(minute_samples, bucket=last_minute)
                append_jsonl(run_dir / "host_minutes.jsonl", minute_summary)
                baseline_minutes.append(minute_summary)
                if len(baseline_minutes) == 10 and not (run_dir / "baseline.json").exists():
                    write_json_atomic(
                        run_dir / "baseline.json",
                        {
                            "schema_version": "runtime_monitor_baseline_v0.1",
                            "generated_at_utc": utc_iso(),
                            "minute_count": 10,
                            "minutes": baseline_minutes,
                        },
                    )
                last_minute = minute

            hour_index = _elapsed_hour_index(started_at, now)
            if hour_index > last_hour_index:
                if last_hour_index >= 0:
                    hour_number = last_hour_index + 1
                    hour_samples = _samples_for_elapsed_hour(list(recent_samples), started_at, hour_number)
                    summary = summarize_host_samples(hour_samples, bucket=f"elapsed_hour_{hour_number}")
                    summary["component_states"] = dict(state.get("last_component_states") or {})
                    append_jsonl(run_dir / "hourly_summaries.jsonl", summary)
                    print(json.dumps(summary, sort_keys=True), flush=True)
                last_hour_index = hour_index

            write_json_atomic(run_dir / "run_state.json", state)
            remaining = max(0.0, host_interval - (monotonic_fn() - loop_started))
            if remaining:
                sleep_fn(remaining)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return finalize_run(run_dir, lifecycle="interrupted" if stop_requested else "completed")


def latest_run_dir(output_root: Path) -> Path | None:
    pointer, error = _read_json(output_root / "latest_run.json")
    if error or pointer is None or not pointer.get("run_dir"):
        return None
    return Path(pointer["run_dir"])


def status_payload(run_dir: Path) -> dict[str, Any]:
    manifest, state = _load_run(run_dir)
    heartbeat = _parse_time(state.get("last_heartbeat_at_utc"))
    return {
        "run_dir": str(run_dir),
        "run_id": manifest["run_id"],
        "lifecycle": state.get("lifecycle"),
        "pid": state.get("pid"),
        "started_at_utc": manifest.get("started_at_utc"),
        "planned_end_at_utc": manifest.get("planned_end_at_utc"),
        "last_heartbeat_at_utc": state.get("last_heartbeat_at_utc"),
        "heartbeat_age_seconds": round((utc_now() - heartbeat).total_seconds(), 3) if heartbeat else None,
        "host_samples": state.get("host_sequence", 0),
        "component_ticks": state.get("component_sequence", 0),
        "last_component_states": state.get("last_component_states", {}),
        "output_bytes": output_size_bytes(run_dir),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded host and weather-runtime soak monitor.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--duration-hours", type=float, default=12.0)
    run.add_argument("--host-interval-seconds", type=float, default=15.0)
    run.add_argument("--component-interval-seconds", type=float, default=60.0)
    run.add_argument("--task-interval-seconds", type=float, default=300.0)
    run.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    run.add_argument("--resume-run-dir")

    status = subparsers.add_parser("status")
    status.add_argument("--run-dir")
    status.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--run-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        if args.resume_run_dir:
            run_dir = Path(args.resume_run_dir).resolve()
        else:
            host_interval = max(10.0, min(30.0, float(args.host_interval_seconds)))
            run_dir = create_run(
                Path(args.output_root).resolve(),
                float(args.duration_hours),
                host_interval,
                float(args.component_interval_seconds),
                float(args.task_interval_seconds),
            )
        print(json.dumps({"run_dir": str(run_dir), "status": "starting"}), flush=True)
        run_monitor(run_dir)
        return 0
    if args.command == "status":
        run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir(Path(args.output_root).resolve())
        if run_dir is None:
            print(json.dumps({"status": "missing", "reason": "no monitor run found"}, indent=2))
            return 2
        print(json.dumps(status_payload(run_dir), indent=2, sort_keys=True))
        return 0
    if args.command == "finalize":
        print(json.dumps(finalize_run(Path(args.run_dir).resolve()), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
