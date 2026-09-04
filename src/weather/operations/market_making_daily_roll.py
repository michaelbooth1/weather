"""Daily launcher for paper-live-forward market-making runs."""
from __future__ import annotations

from weather.operations.windows_silent import apply_windows_silent_subprocess_defaults

apply_windows_silent_subprocess_defaults()

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.collection.snapshot_tracker import pid_is_python
from weather.market.market_making_evidence import (
    DEFAULT_ACTIVE_WINDOW_END,
    EVIDENCE_MODE_AUTO,
    EVIDENCE_MODE_CHOICES,
    classify_market_making_evidence,
)
from weather.market.market_making_run_constants import DEFAULT_RUNS_ROOT, RUN_MODES
from weather.market.mm_scoring_projection import backfill_run_scoring_projections
from weather.operations.bot_run_liveness import (
    DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    DEFAULT_MIN_FREE_BYTES,
    DEFAULT_STARTUP_GRACE_SECONDS,
    age_seconds,
    disk_capacity_preflight,
    disk_full_status,
    failed_status,
    is_disk_full_error,
    parse_utc,
    terminal_status_for_inactive_process,
    utc_iso as liveness_utc_iso,
)
from weather.operations.bot_daily_roll_supervisor import (
    call_pid_alive,
    ensure_daily_roll,
    stop_daily_roll_process,
)
from weather.operations.supervisor import (
    SupervisorSpec,
    acquire_file_lock,
    release_file_lock,
)
from weather.runtime_identity import get_runtime_identity
from weather.paths import REPO_ROOT
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("market_making_daily_roll")
DEFAULT_STATUS_PATH = DEFAULT_RUNS_ROOT / "daily_roll_status.json"
DEFAULT_CONSOLE_LOG_PATH = DEFAULT_RUNS_ROOT / "daily_roll_console.log"
DEFAULT_DIAGNOSTICS_PATH = DEFAULT_RUNS_ROOT / "daily_roll_diagnostics.jsonl"
DEFAULT_TASK_NAME = "WeatherMarketMakingDailyRoll"
DEFAULT_SUPERVISOR_TASK_NAME = "WeatherMarketMakingDailyRollSupervisor"
DEFAULT_TIMEZONE = "America/Toronto"
DEFAULT_START_AFTER_LOCAL_TIME = "19:30"
DEFAULT_START_NO_LATER_THAN_LOCAL_TIME = DEFAULT_ACTIVE_WINDOW_END
DEFAULT_BUDGET_USDC = 500.0
DEFAULT_MODE = "paper-live-forward"
DEFAULT_MARKETS = "all"
DEFAULT_INTERVAL_SECONDS = 60.0
SUPERSEDED_EXIT_WAIT_ATTEMPTS = 20
SUPERSEDED_EXIT_WAIT_SECONDS = 0.1
LAUNCH_LOCK_ATTEMPTS = 100
LAUNCH_LOCK_SLEEP_SECONDS = 0.1
LAUNCH_LOCK_STALE_AFTER_SECONDS = 600.0
ACTIVITY_FILENAMES = (
    "quote_intents_long.csv",
    "order_lifecycle.jsonl",
    "budget_ledger.jsonl",
    "run_summary.json",
    "live_forward_gate.json",
    "preflight.json",
)
REQUIRED_LATEST_RUN_ARTIFACTS = (
    "quote_intents_long.csv",
    "run_summary.json",
)
QUARANTINE_DIR_NAME = "_quarantine"
MARKET_MAKING_DAILY_ROLL_SUPERVISOR = SupervisorSpec(
    name="market_making_daily_roll",
    module="weather.operations.market_making_daily_roll",
    status_path=DEFAULT_STATUS_PATH,
    diagnostics_path=DEFAULT_DIAGNOSTICS_PATH,
    console_log_path=DEFAULT_CONSOLE_LOG_PATH,
    cwd=REPO_ROOT,
    restart_budget=12,
    restart_budget_window_hours=24.0,
    restart_backoff_base_seconds=120.0,
    restart_backoff_max_seconds=3600.0,
)


def utc_now():
    return datetime.now(timezone.utc)


def daily_roll_launch_lock_path(status_path=DEFAULT_STATUS_PATH):
    """Return the process-safe lock that serializes maker lifecycle decisions."""
    status_path = Path(status_path)
    return status_path.with_name(f"{status_path.name}.launch.lock")


def _run_with_daily_roll_launch_lock(callback, *, status_path):
    lock_path = daily_roll_launch_lock_path(status_path)
    handle = acquire_file_lock(
        lock_path,
        attempts=LAUNCH_LOCK_ATTEMPTS,
        stale_after_seconds=LAUNCH_LOCK_STALE_AFTER_SECONDS,
        sleep_seconds=LAUNCH_LOCK_SLEEP_SECONDS,
        pid_check=pid_is_python,
    )
    if handle is None:
        raise RuntimeError(
            "market-making daily-roll launch lock remained busy; refusing an "
            f"unserialized lifecycle decision ({lock_path})"
        )
    try:
        return callback()
    finally:
        release_file_lock(handle, lock_path)


def utc_iso(now=None):
    now = parse_datetime(now) or utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).isoformat()


def parse_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def local_datetime(now=None, timezone_name=DEFAULT_TIMEZONE):
    tz = ZoneInfo(timezone_name)
    parsed = parse_datetime(now)
    if parsed is None:
        return datetime.now(tz)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def target_date_for_roll(now=None, timezone_name=DEFAULT_TIMEZONE):
    return local_datetime(now=now, timezone_name=timezone_name).date().isoformat()


def ensure_date(value):
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)).isoformat()


def format_number(value):
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def read_json(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    for attempt in range(20):
        try:
            tmp.replace(path)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)
    return path


def runtime_market_making_daily_roll_supervisor_spec(
    *,
    status_path=DEFAULT_STATUS_PATH,
    diagnostics_path=DEFAULT_DIAGNOSTICS_PATH,
    console_log_path=DEFAULT_CONSOLE_LOG_PATH,
):
    return MARKET_MAKING_DAILY_ROLL_SUPERVISOR.with_paths(
        status_path=status_path,
        diagnostics_path=diagnostics_path,
        console_log_path=console_log_path,
    )


def build_market_making_command(
    target_date,
    *,
    budget_usdc=DEFAULT_BUDGET_USDC,
    mode=DEFAULT_MODE,
    markets=DEFAULT_MARKETS,
    interval_seconds=DEFAULT_INTERVAL_SECONDS,
    python_executable=None,
    runs_root=None,
    once=False,
    config_overrides=None,
    evidence_mode=None,
    market_harvest_companion=False,
):
    mode = str(mode)
    if market_harvest_companion and mode == "live-pilot":
        raise ValueError("market-harvest companion is paper-only")
    if mode not in RUN_MODES:
        raise ValueError(f"unsupported market-making mode: {mode}")
    command = [
        str(python_executable or sys.executable),
        "-m",
        "weather.market.market_making_run",
        "--date",
        ensure_date(target_date),
        "--budget-usdc",
        format_number(budget_usdc),
        "--mode",
        mode,
        "--markets",
        str(markets),
        "--interval-seconds",
        format_number(interval_seconds),
    ]
    if runs_root:
        command.extend(["--runs-root", str(runs_root)])
    if evidence_mode:
        command.extend(["--evidence-mode", str(evidence_mode)])
    if market_harvest_companion:
        command.append("--enable-market-harvest-companion")
    for override in config_overrides or []:
        command.extend(["--config", str(override)])
    if once:
        command.append("--once")
    return command


def _creationflags(detached=False):
    if os.name != "nt":
        return 0
    if detached:
        return subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.CREATE_NO_WINDOW


def process_command_line(pid):
    if not pid:
        return ""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return ""
    if os.name == "nt":
        return ""
    else:
        command = ["ps", "-p", str(pid), "-o", "args="]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_creationflags(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def pid_matches_market_making_run(pid, target_date=None):
    if not pid_is_python(pid):
        return False
    command_line = process_command_line(pid)
    if not command_line:
        return True
    text = command_line.lower()
    if "market_making_run" not in text:
        return False
    if target_date and str(target_date) not in command_line:
        return False
    return True


def launch_market_making_process(command, *, repo_root=REPO_ROOT, console_log_path=DEFAULT_CONSOLE_LOG_PATH):
    console_log_path = Path(console_log_path)
    console_log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = console_log_path.open("a", encoding="utf-8")
    try:
        child = subprocess.Popen(
            list(command),
            cwd=str(repo_root),
            stdout=log_handle,
            stderr=log_handle,
            creationflags=_creationflags(detached=True),
        )
    finally:
        log_handle.close()
    return child.pid


def _run_folder_metadata(run_folder):
    run_folder = Path(run_folder)
    return read_json(run_folder / "run_summary.json") or read_json(run_folder / "run_config.json") or {}


def _run_folder_matches_expected(run_folder, *, expected_mode=None, expected_evidence_mode=None):
    if not expected_mode and not expected_evidence_mode:
        return True
    metadata = _run_folder_metadata(run_folder)
    if not metadata:
        return False
    metadata_mode = str(metadata.get("mode") or "")
    metadata_evidence_mode = str(metadata.get("evidence_mode") or "")
    if expected_mode and metadata_mode and metadata_mode != str(expected_mode):
        return False
    if expected_evidence_mode and metadata_evidence_mode and metadata_evidence_mode != str(expected_evidence_mode):
        return False
    return True


def market_making_run_folders(runs_root, target_date, *, expected_mode=None, expected_evidence_mode=None):
    day_root = Path(runs_root) / ensure_date(target_date)
    if not day_root.exists():
        return []
    folders = []
    for folder in day_root.iterdir():
        if not folder.is_dir():
            continue
        if folder.name == QUARANTINE_DIR_NAME or folder.name.startswith("."):
            continue
        if not _run_folder_matches_expected(
            folder,
            expected_mode=expected_mode,
            expected_evidence_mode=expected_evidence_mode,
        ):
            continue
        folders.append(folder)
    return sorted(folders)


def _path_stat(path, stat_fn=None):
    stat_fn = stat_fn or (lambda value: Path(value).stat())
    try:
        return stat_fn(Path(path))
    except OSError:
        return None


def _path_mtime_utc(path, stat_fn=None):
    stat = _path_stat(path, stat_fn=stat_fn)
    if stat is None:
        return None
    return datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)


def _path_size(path, stat_fn=None):
    stat = _path_stat(path, stat_fn=stat_fn)
    if stat is None:
        return None
    return int(getattr(stat, "st_size", 0) or 0)


def _run_folder_latest_mtime(run_folder, stat_fn=None):
    latest = _path_mtime_utc(run_folder, stat_fn=stat_fn)
    try:
        children = list(Path(run_folder).iterdir())
    except OSError:
        children = []
    for path in children:
        if path.is_file():
            mtime = _path_mtime_utc(path, stat_fn=stat_fn)
            if mtime is not None and (latest is None or mtime > latest):
                latest = mtime
    return latest


def latest_market_making_run_folder(
    runs_root,
    target_date,
    *,
    stat_fn=None,
    expected_mode=None,
    expected_evidence_mode=None,
):
    folders = market_making_run_folders(
        runs_root,
        target_date,
        expected_mode=expected_mode,
        expected_evidence_mode=expected_evidence_mode,
    )
    if not folders:
        return None
    return max(
        folders,
        key=lambda folder: (
            _run_folder_latest_mtime(folder, stat_fn=stat_fn) or datetime.min.replace(tzinfo=timezone.utc),
            folder.name,
        ),
    )


def market_making_activity_paths(runs_root, target_date, *, expected_mode=None, expected_evidence_mode=None):
    paths = []
    day_root = Path(runs_root) / ensure_date(target_date)
    if day_root.exists():
        for run_folder in sorted(day_root.glob("*")):
            if not run_folder.is_dir():
                continue
            if run_folder.name == QUARANTINE_DIR_NAME or run_folder.name.startswith("."):
                continue
            if not _run_folder_matches_expected(
                run_folder,
                expected_mode=expected_mode,
                expected_evidence_mode=expected_evidence_mode,
            ):
                continue
            paths.extend(run_folder / name for name in ACTIVITY_FILENAMES)
    return paths


def _latest_useful_artifact_row(paths, *, now=None, stat_fn=None):
    current = parse_utc(now) or datetime.now(timezone.utc)
    best = None
    for path in paths:
        mtime = _path_mtime_utc(path, stat_fn=stat_fn)
        if mtime is None:
            continue
        row = {
            "path": str(path),
            "modified_at_utc": mtime.isoformat(),
            "age_seconds": round(max(0.0, (current - mtime).total_seconds()), 3),
            "size_bytes": _path_size(path, stat_fn=stat_fn),
        }
        if best is None or mtime > parse_utc(best["modified_at_utc"]):
            best = row
    return best


def _read_run_summary(run_folder):
    return read_json(Path(run_folder) / "run_summary.json") or {}


def _read_live_forward_gate(run_folder):
    return read_json(Path(run_folder) / "live_forward_gate.json") or {}


def _bool_or_none(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _current_live_forward_count(gate, useful_work):
    explicit = _bool_or_none((gate or {}).get("counts_toward_live_forward_gate"))
    if explicit is not None:
        return explicit
    status = str((gate or {}).get("status") or "").upper()
    if status == "PASS":
        return True
    if status in {"BLOCK", "FAIL", "ERROR"}:
        return False
    useful_work_status = str((useful_work or {}).get("status") or "").upper()
    if useful_work_status in {"BLOCK", "FAIL", "ERROR"}:
        return False
    return None


def market_making_artifact_health(
    runs_root,
    target_date,
    *,
    now=None,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    started_at_utc=None,
    stat_fn=None,
    expected_mode=None,
    expected_evidence_mode=None,
):
    current = parse_utc(now) or datetime.now(timezone.utc)
    folders = market_making_run_folders(
        runs_root,
        target_date,
        expected_mode=expected_mode,
        expected_evidence_mode=expected_evidence_mode,
    )
    startup_age = age_seconds(started_at_utc, now=current)
    in_startup_grace = startup_age is not None and startup_age <= float(startup_grace_seconds)
    if not folders:
        status = "STARTUP_GRACE" if in_startup_grace else "NO_RUN_FOLDER"
        return {
            "status": status,
            "ok": in_startup_grace,
            "root_cause_class": None if in_startup_grace else "stale_pid_no_recent_useful_artifacts",
            "run_folder_count": 0,
            "latest_run_folder": None,
            "startup_age_seconds": round(startup_age, 3) if startup_age is not None else None,
        }

    latest = latest_market_making_run_folder(
        runs_root,
        target_date,
        stat_fn=stat_fn,
        expected_mode=expected_mode,
        expected_evidence_mode=expected_evidence_mode,
    )
    try:
        files = [path for path in latest.iterdir() if path.is_file()]
    except OSError:
        files = []
    useful_paths = [latest / name for name in ACTIVITY_FILENAMES]
    latest_useful = _latest_useful_artifact_row(useful_paths, now=current, stat_fn=stat_fn)
    missing_required = [name for name in REQUIRED_LATEST_RUN_ARTIFACTS if _path_stat(latest / name, stat_fn=stat_fn) is None]
    status = "PASS"
    root_cause = None
    detail = "latest market-making run artifacts are current"
    if not files:
        status = "EMPTY_RUN_FOLDER"
        root_cause = "empty_run_artifact_folder"
        detail = "latest market-making run folder has no files"
    elif "quote_intents_long.csv" in missing_required:
        status = "MISSING_QUOTE_TAPE"
        root_cause = "missing_quote_tape"
        detail = "latest market-making run folder is missing quote_intents_long.csv"
    elif "run_summary.json" in missing_required:
        status = "MISSING_HEARTBEAT_METADATA"
        root_cause = "missing_heartbeat_metadata"
        detail = "latest market-making run folder is missing run_summary.json"
    else:
        run_summary_mtime = _path_mtime_utc(latest / "run_summary.json", stat_fn=stat_fn)
        quote_mtime = _path_mtime_utc(latest / "quote_intents_long.csv", stat_fn=stat_fn)
        run_summary_age = max(0.0, (current - run_summary_mtime).total_seconds()) if run_summary_mtime else None
        quote_age = max(0.0, (current - quote_mtime).total_seconds()) if quote_mtime else None
        if run_summary_age is not None and run_summary_age > float(max_activity_age_seconds):
            status = "STALE_HEARTBEAT_METADATA"
            root_cause = "stale_heartbeat_metadata"
            detail = "run_summary.json is stale"
        elif quote_age is not None and quote_age > float(max_activity_age_seconds):
            status = "STALE_QUOTE_TAPE"
            root_cause = "stale_quote_tape"
            detail = "quote_intents_long.csv is stale"

    if status != "PASS" and in_startup_grace and status in {
        "EMPTY_RUN_FOLDER",
        "MISSING_QUOTE_TAPE",
        "MISSING_HEARTBEAT_METADATA",
    }:
        ok = True
        root_cause = None
        detail = f"{detail}; still inside startup grace"
        status = "STARTUP_GRACE"
    else:
        ok = status == "PASS"

    summary = _read_run_summary(latest) if latest else {}
    live_forward_gate = _read_live_forward_gate(latest) if latest else {}
    if not isinstance(live_forward_gate, dict):
        live_forward_gate = {}
    embedded_gate = summary.get("live_forward_gate") or {}
    if not isinstance(embedded_gate, dict):
        embedded_gate = {}
    if not live_forward_gate and isinstance(embedded_gate, dict):
        live_forward_gate = embedded_gate
    useful_work = (
        summary.get("useful_work_liveness")
        or (live_forward_gate or {}).get("useful_work_liveness")
        or (embedded_gate or {}).get("useful_work_liveness")
        or {}
    )
    current_counts_toward_live_forward = _current_live_forward_count(live_forward_gate, useful_work)
    report = {
        "latest_run_folder": str(latest) if latest else None,
        "latest_useful_write_path": (latest_useful or {}).get("path"),
        "latest_useful_write_at_utc": (latest_useful or {}).get("modified_at_utc"),
        "latest_useful_write_age_seconds": (latest_useful or {}).get("age_seconds"),
        "latest_quote_rows": summary.get("row_count") or (summary.get("latest_tick") or {}).get("row_count"),
        "latest_quote_permission_rows": summary.get("quote_permission_rows")
        or (summary.get("latest_tick") or {}).get("quote_permission_rows"),
        "useful_work_liveness_status": useful_work.get("status"),
        "useful_work_liveness_reason": useful_work.get("reason"),
        "live_forward_gate_status": live_forward_gate.get("status"),
        "live_forward_gate_counts_toward_live_forward_gate": _bool_or_none(
            live_forward_gate.get("counts_toward_live_forward_gate")
        ),
        "current_counts_toward_live_forward_gate": current_counts_toward_live_forward,
        "restart_recommended": not ok,
        "restart_reason": root_cause,
    }
    return {
        "status": status,
        "ok": ok,
        "root_cause_class": root_cause,
        "detail": detail,
        "run_folder_count": len(folders),
        "latest_run_folder": str(latest) if latest else None,
        "missing_required_artifacts": missing_required,
        "startup_age_seconds": round(startup_age, 3) if startup_age is not None else None,
        "max_activity_age_seconds": float(max_activity_age_seconds),
        "latest_useful_artifact": latest_useful,
        "live_forward_gate_status": live_forward_gate.get("status"),
        "current_counts_toward_live_forward_gate": current_counts_toward_live_forward,
        "operator_report": report,
    }


def enrich_market_making_liveness_status(
    payload,
    *,
    now=None,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    stat_fn=None,
):
    if not payload or payload.get("status") not in {"started", "already_running", "idle_process"}:
        return payload
    health = market_making_artifact_health(
        payload.get("runs_root") or DEFAULT_RUNS_ROOT,
        payload.get("target_date") or target_date_for_roll(now=now),
        now=now,
        max_activity_age_seconds=max_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
        started_at_utc=payload.get("started_at_utc") or payload.get("generated_at_utc"),
        stat_fn=stat_fn,
        expected_mode=payload.get("mode"),
        expected_evidence_mode=payload.get("evidence_mode"),
    )
    payload["artifact_liveness"] = health
    payload["operator_report"] = health.get("operator_report") or {}
    supervisor = payload.get("daily_roll_supervisor") or {}
    recovery_guard = supervisor.get("recovery_guard") or {}
    if supervisor:
        operator = dict(payload.get("operator_report") or {})
        supervisor_remediation = supervisor.get("remediation") or recovery_guard.get("remediation")
        start_time_gate = supervisor.get("start_time_gate") or {}
        flattened_supervisor = {
            "supervisor_state": supervisor.get("state"),
            "supervisor_action": supervisor.get("action"),
            "supervisor_intended_action": supervisor.get("intended_action"),
            "supervisor_restart_cause": supervisor.get("restart_cause"),
            "supervisor_reason": supervisor.get("reason"),
            "supervisor_remediation": supervisor_remediation,
            "supervisor_runtime_identity_matches_current": supervisor.get("runtime_identity_matches_current"),
            "supervisor_retry_after_seconds": recovery_guard.get("retry_after_seconds"),
            "supervisor_retry_at_utc": recovery_guard.get("retry_at_utc"),
            "expected_target_date": supervisor.get("expected_target_date"),
            "supervisor_target_date": supervisor.get("target_date"),
            "start_time_gate_allowed": start_time_gate.get("allowed"),
            "start_reason": start_time_gate.get("reason"),
            "start_after_local_time": start_time_gate.get("start_after_local_time"),
            "start_no_later_than_local_time": start_time_gate.get(
                "start_no_later_than_local_time"
            ),
            "start_time_gate_timezone": start_time_gate.get("timezone"),
        }
        operator.update({
            key: value
            for key, value in flattened_supervisor.items()
            if value is not None
        })
        payload.update({
            key: value
            for key, value in flattened_supervisor.items()
            if value is not None
        })
        payload["operator_report"] = operator
    if health.get("live_forward_gate_status") is not None:
        payload["live_forward_gate_status"] = health.get("live_forward_gate_status")
    current_counts_toward_live_forward = health.get("current_counts_toward_live_forward_gate")
    if current_counts_toward_live_forward is not None:
        payload["current_counts_toward_live_forward_gate"] = current_counts_toward_live_forward
        payload["counts_toward_live_forward_gate"] = current_counts_toward_live_forward
    if health.get("ok"):
        return payload
    payload.update({
        "status": "idle_process",
        "action": "blocked_restart_required",
        "terminal": True,
        "completed_at_utc": liveness_utc_iso(now),
        "first_failing_gate": "artifact_liveness",
        "root_cause_class": health.get("root_cause_class") or "stale_pid_no_recent_useful_artifacts",
        "zero_trades_expected": False,
        "remediation_command": "quarantine stale or incomplete market-making artifacts, then restart the daily roll with --force",
    })
    return payload


def market_making_terminal_status_for_inactive_process(
    payload,
    *,
    now=None,
    pid_alive=None,
    runs_root=None,
    target_date=None,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    stat_fn=None,
):
    original = dict(payload or {})
    original_status = original.get("status")
    original_action = original.get("action")
    alive = original.get("pid_alive")
    if pid_alive and original.get("pid"):
        try:
            alive = bool(pid_alive(original.get("pid"), target_date or original.get("target_date")))
        except (OSError, ValueError, TypeError):
            alive = False
    root = runs_root or (payload or {}).get("runs_root") or DEFAULT_RUNS_ROOT
    target = target_date or (payload or {}).get("target_date")
    expected_mode = (payload or {}).get("mode")
    expected_evidence_mode = (payload or {}).get("evidence_mode")
    payload = terminal_status_for_inactive_process(
        payload,
        now=now,
        pid_alive=pid_alive,
        activity_paths=market_making_activity_paths(
            root,
            target or target_date_for_roll(now=now),
            expected_mode=expected_mode,
            expected_evidence_mode=expected_evidence_mode,
        ),
        max_activity_age_seconds=max_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
        stat_fn=stat_fn,
    )
    payload = enrich_market_making_liveness_status(
        payload,
        now=now,
        max_activity_age_seconds=max_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
        stat_fn=stat_fn,
    )
    health = payload.get("artifact_liveness") or {}
    if (
        payload.get("status") == "idle_process"
        and payload.get("first_failing_gate") == "activity_liveness"
        and health.get("ok")
        and alive
    ):
        restored_status = original_status if original_status in {"started", "already_running"} else "already_running"
        restored_action = (
            original_action
            if original_status in {"started", "already_running"} and original_action
            else ("noop" if restored_status == "already_running" else "start")
        )
        payload.update({
            "status": restored_status,
            "action": restored_action,
            "terminal": False,
            "pid_alive": True,
            "zero_trades_expected": False,
        })
        if health.get("root_cause_class"):
            payload["root_cause_class"] = health.get("root_cause_class")
        else:
            payload.pop("root_cause_class", None)
        for key in ("completed_at_utc", "first_failing_gate", "remediation_command"):
            payload.pop(key, None)
    return payload


def quarantine_unhealthy_market_making_run_folder(
    runs_root,
    target_date,
    *,
    artifact_health=None,
    now=None,
    force=False,
):
    health = artifact_health or market_making_artifact_health(runs_root, target_date, now=now)
    if health.get("ok") and not force:
        return {"status": "SKIPPED_HEALTHY", "action": "none", "reason": "latest run artifacts are healthy"}
    source = health.get("latest_run_folder")
    if not source:
        return {"status": "SKIPPED_NO_RUN_FOLDER", "action": "none", "reason": "no run folder to quarantine"}
    source = Path(source)
    if not source.exists() or not source.is_dir():
        return {"status": "SKIPPED_MISSING_SOURCE", "action": "none", "source_path": str(source)}
    timestamp = (parse_utc(now) or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    quarantine_root = source.parent / QUARANTINE_DIR_NAME
    quarantine_root.mkdir(parents=True, exist_ok=True)
    destination = quarantine_root / f"{source.name}__{timestamp}"
    if destination.exists():
        destination = quarantine_root / f"{source.name}__{timestamp}__{os.getpid()}_{time.time_ns()}"
    try:
        source.rename(destination)
    except OSError as exc:
        return {
            "status": "FAILED",
            "action": "quarantine_failed",
            "source_path": str(source),
            "quarantine_path": str(destination),
            "reason": f"{type(exc).__name__}: {exc}",
            "artifact_liveness_status": health.get("status"),
        }
    return {
        "status": "QUARANTINED",
        "action": "quarantine",
        "source_path": str(source),
        "quarantine_path": str(destination),
        "artifact_liveness_status": health.get("status"),
        "root_cause_class": health.get("root_cause_class"),
        "forced": bool(force),
    }


def _base_payload(
    *,
    target_date,
    budget_usdc,
    mode,
    markets,
    interval_seconds,
    timezone_name,
    status_path,
    console_log_path,
    runs_root,
    command,
    evidence_classification,
    disk_preflight=None,
    now=None,
    market_harvest_companion=False,
):
    generated_at = utc_iso(now)
    return {
        "schema_version": SCHEMA_VERSION,
        "runner": "market_making_daily_roll",
        "generated_at_utc": generated_at,
        "target_date": ensure_date(target_date),
        "timezone": timezone_name,
        "budget_usdc": float(budget_usdc),
        "mode": mode,
        "markets": markets,
        "interval_seconds": float(interval_seconds),
        "runs_root": str(runs_root),
        "status_path": str(status_path),
        "console_log_path": str(console_log_path),
        "command": list(command),
        "evidence_mode": evidence_classification.get("evidence_mode"),
        "evidence_classification": evidence_classification,
        "counts_toward_live_forward_gate": evidence_classification.get("counts_toward_live_forward_gate"),
        "runtime_identity": get_runtime_identity(),
        "disk_capacity_preflight": disk_preflight or {},
        "market_harvest_companion_enabled": bool(market_harvest_companion),
    }


def start_for_date(
    target_date,
    *,
    budget_usdc=DEFAULT_BUDGET_USDC,
    mode=DEFAULT_MODE,
    markets=DEFAULT_MARKETS,
    interval_seconds=DEFAULT_INTERVAL_SECONDS,
    timezone_name=DEFAULT_TIMEZONE,
    status_path=DEFAULT_STATUS_PATH,
    console_log_path=DEFAULT_CONSOLE_LOG_PATH,
    runs_root=DEFAULT_RUNS_ROOT,
    repo_root=REPO_ROOT,
    python_executable=None,
    force=False,
    once=False,
    config_overrides=None,
    evidence_mode=EVIDENCE_MODE_AUTO,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    disk_usage_fn=None,
    activity_stat_fn=None,
    now=None,
    pid_alive=pid_matches_market_making_run,
    launcher=launch_market_making_process,
    force_retire_latest_run=False,
    market_harvest_companion=False,
    _launch_lock_held=False,
):
    if market_harvest_companion and str(mode) == "live-pilot":
        raise ValueError("market-harvest companion is paper-only")
    if not _launch_lock_held:
        return _run_with_daily_roll_launch_lock(
            lambda: start_for_date(
                target_date,
                budget_usdc=budget_usdc,
                mode=mode,
                markets=markets,
                interval_seconds=interval_seconds,
                timezone_name=timezone_name,
                status_path=status_path,
                console_log_path=console_log_path,
                runs_root=runs_root,
                repo_root=repo_root,
                python_executable=python_executable,
                force=force,
                once=once,
                config_overrides=config_overrides,
                evidence_mode=evidence_mode,
                min_free_bytes=min_free_bytes,
                max_activity_age_seconds=max_activity_age_seconds,
                startup_grace_seconds=startup_grace_seconds,
                disk_usage_fn=disk_usage_fn,
                activity_stat_fn=activity_stat_fn,
                now=now,
                pid_alive=pid_alive,
                launcher=launcher,
                force_retire_latest_run=force_retire_latest_run,
                market_harvest_companion=market_harvest_companion,
                _launch_lock_held=True,
            ),
            status_path=status_path,
        )
    target_date = ensure_date(target_date)
    status_path = Path(status_path)
    console_log_path = Path(console_log_path)
    evidence_classification = classify_market_making_evidence(
        target_date,
        now=now,
        timezone_name=timezone_name,
        requested_mode=evidence_mode,
        run_mode=mode,
    )
    command = build_market_making_command(
        target_date,
        budget_usdc=budget_usdc,
        mode=mode,
        markets=markets,
        interval_seconds=interval_seconds,
        python_executable=python_executable,
        runs_root=runs_root,
        once=once,
        config_overrides=config_overrides,
        evidence_mode=evidence_classification.get("evidence_mode"),
        market_harvest_companion=market_harvest_companion,
    )
    existing = read_json(status_path) or {}
    existing_pid = existing.get("pid")
    existing_liveness = None
    if existing.get("target_date") == target_date and existing.get("status") in {"started", "already_running"}:
        refreshed = market_making_terminal_status_for_inactive_process(
            existing,
            now=now,
            pid_alive=pid_alive,
            runs_root=existing.get("runs_root") or runs_root,
            target_date=target_date,
            max_activity_age_seconds=max_activity_age_seconds,
            startup_grace_seconds=startup_grace_seconds,
            stat_fn=activity_stat_fn,
        )
        existing_liveness = refreshed
        if refreshed.get("status") in {"pid_missing", "idle_process"} and not force:
            payload = _base_payload(
                target_date=target_date,
                budget_usdc=budget_usdc,
                mode=mode,
                markets=markets,
                interval_seconds=interval_seconds,
                timezone_name=timezone_name,
                status_path=status_path,
                console_log_path=console_log_path,
                runs_root=runs_root,
                command=existing.get("command") or command,
                evidence_classification=evidence_classification,
                disk_preflight=existing.get("disk_capacity_preflight") or {},
                now=now,
                market_harvest_companion=market_harvest_companion,
            )
            payload.update(refreshed)
            payload["previous_status_generated_at_utc"] = existing.get("generated_at_utc")
            write_json(status_path, payload)
            return payload
    if (
        not force
        and existing.get("target_date") == target_date
        and pid_alive(existing_pid, target_date)
    ):
        payload = _base_payload(
            target_date=target_date,
            budget_usdc=budget_usdc,
            mode=mode,
            markets=markets,
            interval_seconds=interval_seconds,
            timezone_name=timezone_name,
            status_path=status_path,
            console_log_path=console_log_path,
            runs_root=runs_root,
            command=existing.get("command") or command,
            evidence_classification=evidence_classification,
            disk_preflight=existing.get("disk_capacity_preflight") or {},
            now=now,
            market_harvest_companion=market_harvest_companion,
        )
        payload.update({
            "status": "already_running",
            "action": "noop",
            "pid": existing_pid,
            "started_at_utc": existing.get("started_at_utc"),
            "previous_status_generated_at_utc": existing.get("generated_at_utc"),
        })
        if existing_liveness:
            for key in ("activity_liveness", "artifact_liveness", "operator_report"):
                if key in existing_liveness:
                    payload[key] = existing_liveness[key]
        write_json(status_path, payload)
        return payload

    disk_preflight = disk_capacity_preflight(
        runs_root,
        min_free_bytes=min_free_bytes,
        usage_fn=disk_usage_fn,
    )
    forced_run_retirement = None
    if force and existing.get("target_date") == target_date:
        health = market_making_artifact_health(
            existing.get("runs_root") or runs_root,
            target_date,
            now=now,
            max_activity_age_seconds=max_activity_age_seconds,
            startup_grace_seconds=startup_grace_seconds,
            started_at_utc=existing.get("started_at_utc") or existing.get("generated_at_utc"),
            stat_fn=activity_stat_fn,
            expected_mode=mode,
            expected_evidence_mode=evidence_classification.get("evidence_mode"),
        )
        forced_run_retirement = quarantine_unhealthy_market_making_run_folder(
            existing.get("runs_root") or runs_root,
            target_date,
            artifact_health=health,
            now=now,
            force=force_retire_latest_run,
        )
    payload = _base_payload(
        target_date=target_date,
        budget_usdc=budget_usdc,
        mode=mode,
        markets=markets,
        interval_seconds=interval_seconds,
        timezone_name=timezone_name,
        status_path=status_path,
        console_log_path=console_log_path,
        runs_root=runs_root,
        command=command,
        evidence_classification=evidence_classification,
        disk_preflight=disk_preflight,
        now=now,
        market_harvest_companion=market_harvest_companion,
    )
    if forced_run_retirement is not None:
        payload["forced_run_retirement"] = forced_run_retirement
    if not disk_preflight.get("ok"):
        payload = disk_full_status(payload, preflight=disk_preflight, now=now)
        if forced_run_retirement is not None:
            payload["forced_run_retirement"] = forced_run_retirement
        write_json(status_path, payload)
        return payload
    try:
        pid = launcher(command, repo_root=repo_root, console_log_path=console_log_path)
    except OSError as exc:
        if is_disk_full_error(exc):
            payload = disk_full_status(payload, preflight=disk_preflight, now=now, error=exc)
        else:
            payload = failed_status(payload, now=now, error=exc)
        write_json(status_path, payload)
        return payload
    payload.update({
        "status": "started",
        "action": "start",
        "pid": pid,
        "started_at_utc": payload["generated_at_utc"],
        "forced": bool(force),
        "once": bool(once),
    })
    if forced_run_retirement is not None:
        payload["forced_run_retirement"] = forced_run_retirement
    write_json(status_path, payload)
    return payload


def start_for_current_day(
    *,
    now=None,
    timezone_name=DEFAULT_TIMEZONE,
    **kwargs,
):
    return start_for_date(
        target_date_for_roll(now=now, timezone_name=timezone_name),
        now=now,
        timezone_name=timezone_name,
        **kwargs,
    )


def wait_for_superseded_process_exit(
    pid,
    target_date,
    *,
    pid_alive,
    attempts=SUPERSEDED_EXIT_WAIT_ATTEMPTS,
    sleep_seconds=SUPERSEDED_EXIT_WAIT_SECONDS,
    sleep_fn=None,
):
    """Boundedly prove the old target-matched worker no longer exists."""

    sleep_fn = sleep_fn or time.sleep
    bounded_attempts = max(1, int(attempts))
    for attempt in range(bounded_attempts):
        if not call_pid_alive(pid_alive, pid, target_date):
            return {
                "exited": True,
                "reason": "superseded_process_not_alive",
                "pid": pid,
                "target_date": str(target_date),
                "attempts": attempt + 1,
            }
        if attempt + 1 < bounded_attempts:
            sleep_fn(float(sleep_seconds))
    return {
        "exited": False,
        "reason": "superseded_process_exit_not_observed",
        "pid": pid,
        "target_date": str(target_date),
        "attempts": bounded_attempts,
    }


def finalize_scoring_projections_for_date(runs_root, target_date):
    target = ensure_date(target_date)
    folders = market_making_run_folders(runs_root, target)
    payload = backfill_run_scoring_projections(folders, skip_existing=True)
    return {
        "status": "PASS" if not payload.get("error_run_count") else "WARN",
        "target_date": target,
        **payload,
    }


def ensure_for_date(
    target_date,
    *,
    budget_usdc=DEFAULT_BUDGET_USDC,
    mode=DEFAULT_MODE,
    markets=DEFAULT_MARKETS,
    interval_seconds=DEFAULT_INTERVAL_SECONDS,
    timezone_name=DEFAULT_TIMEZONE,
    status_path=DEFAULT_STATUS_PATH,
    diagnostics_path=DEFAULT_DIAGNOSTICS_PATH,
    console_log_path=DEFAULT_CONSOLE_LOG_PATH,
    runs_root=DEFAULT_RUNS_ROOT,
    repo_root=REPO_ROOT,
    python_executable=None,
    once=False,
    config_overrides=None,
    evidence_mode=EVIDENCE_MODE_AUTO,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    disk_usage_fn=None,
    activity_stat_fn=None,
    now=None,
    pid_alive=pid_matches_market_making_run,
    launcher=launch_market_making_process,
    start_after_local_time=DEFAULT_START_AFTER_LOCAL_TIME,
    start_no_later_than_local_time=DEFAULT_START_NO_LATER_THAN_LOCAL_TIME,
    current_identity=None,
    market_harvest_companion=False,
    _launch_lock_held=False,
):
    if market_harvest_companion and str(mode) == "live-pilot":
        raise ValueError("market-harvest companion is paper-only")
    if not _launch_lock_held:
        return _run_with_daily_roll_launch_lock(
            lambda: ensure_for_date(
                target_date,
                budget_usdc=budget_usdc,
                mode=mode,
                markets=markets,
                interval_seconds=interval_seconds,
                timezone_name=timezone_name,
                status_path=status_path,
                diagnostics_path=diagnostics_path,
                console_log_path=console_log_path,
                runs_root=runs_root,
                repo_root=repo_root,
                python_executable=python_executable,
                once=once,
                config_overrides=config_overrides,
                evidence_mode=evidence_mode,
                min_free_bytes=min_free_bytes,
                max_activity_age_seconds=max_activity_age_seconds,
                startup_grace_seconds=startup_grace_seconds,
                disk_usage_fn=disk_usage_fn,
                activity_stat_fn=activity_stat_fn,
                now=now,
                pid_alive=pid_alive,
                launcher=launcher,
                start_after_local_time=start_after_local_time,
                start_no_later_than_local_time=start_no_later_than_local_time,
                current_identity=current_identity,
                market_harvest_companion=market_harvest_companion,
                _launch_lock_held=True,
            ),
            status_path=status_path,
        )
    target_date = ensure_date(target_date)
    spec = runtime_market_making_daily_roll_supervisor_spec(
        status_path=status_path,
        diagnostics_path=diagnostics_path,
        console_log_path=console_log_path,
    )

    def load_current_status():
        return load_status(
            status_path,
            now=now,
            pid_alive=pid_alive,
            write_back=True,
            max_activity_age_seconds=max_activity_age_seconds,
            startup_grace_seconds=startup_grace_seconds,
            activity_stat_fn=activity_stat_fn,
        )

    def start_recovery(*, force, force_retire_latest_run=False):
        return start_for_date(
            target_date,
            budget_usdc=budget_usdc,
            mode=mode,
            markets=markets,
            interval_seconds=interval_seconds,
            timezone_name=timezone_name,
            status_path=status_path,
            console_log_path=console_log_path,
            runs_root=runs_root,
            repo_root=repo_root,
            python_executable=python_executable,
            force=force,
            once=once,
            config_overrides=config_overrides,
            evidence_mode=evidence_mode,
            min_free_bytes=min_free_bytes,
            max_activity_age_seconds=max_activity_age_seconds,
            startup_grace_seconds=startup_grace_seconds,
            disk_usage_fn=disk_usage_fn,
            activity_stat_fn=activity_stat_fn,
            now=now,
            pid_alive=pid_alive,
            launcher=launcher,
            force_retire_latest_run=force_retire_latest_run,
            market_harvest_companion=market_harvest_companion,
            _launch_lock_held=True,
        )

    result = ensure_daily_roll(
        spec=spec,
        target_date=target_date,
        load_status_fn=load_current_status,
        start_fn=start_recovery,
        pid_alive=pid_alive,
        write_status_fn=write_json,
        now=now,
        current_identity=current_identity,
        timezone_name=timezone_name,
        start_after_local_time=start_after_local_time,
        start_no_later_than_local_time=start_no_later_than_local_time,
    )
    previous_target = result.get("status_target_date")
    if (
        result.get("action") == "start"
        and previous_target
        and str(previous_target) != target_date
    ):
        stop_result = result.get("stop_superseded") or {}
        no_matching_process = (
            stop_result.get("reason")
            == "no live matching daily-roll python process"
        )
        exit_wait = None
        if stop_result.get("stopped"):
            if stop_result.get("exited") is True:
                exit_wait = {
                    "exited": True,
                    "reason": "stop_receipt_confirmed_exit",
                    "pid": stop_result.get("pid"),
                    "target_date": str(previous_target),
                    "attempts": 0,
                }
            else:
                exit_wait = wait_for_superseded_process_exit(
                    stop_result.get("pid"),
                    previous_target,
                    pid_alive=pid_alive,
                )
            result["superseded_process_exit_wait"] = exit_wait
        safe_to_finalize = bool(no_matching_process or (exit_wait or {}).get("exited"))
        try:
            if not safe_to_finalize:
                raise RuntimeError(
                    "superseded maker worker did not stop cleanly or its exit was not "
                    "confirmed; canonical fallback required"
                )
            finalization = finalize_scoring_projections_for_date(runs_root, previous_target)
        except Exception as exc:
            finalization = {
                "status": "ERROR",
                "target_date": str(previous_target),
                "error": f"{type(exc).__name__}: {exc}",
            }
        result["superseded_run_scoring_projection_finalization"] = finalization
        latest_status = read_json(status_path)
        if isinstance(latest_status, dict):
            latest_status["superseded_run_scoring_projection_finalization"] = finalization
            if exit_wait is not None:
                latest_status["superseded_process_exit_wait"] = exit_wait
            try:
                write_json(status_path, latest_status)
            except Exception as exc:
                result["scoring_projection_status_persistence_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
    return result


def ensure_for_current_day(*, now=None, timezone_name=DEFAULT_TIMEZONE, **kwargs):
    return ensure_for_date(
        target_date_for_roll(now=now, timezone_name=timezone_name),
        now=now,
        timezone_name=timezone_name,
        **kwargs,
    )


def stop_status_file(
    path=DEFAULT_STATUS_PATH,
    *,
    target_date=None,
    now=None,
    pid_alive=pid_matches_market_making_run,
    write_back=True,
):
    status = read_json(path) or {"exists": False, "path": str(path)}
    target = target_date or status.get("target_date")
    stop_result = stop_daily_roll_process(
        status,
        target_date=target,
        pid_alive=pid_alive,
        now=parse_datetime(now),
    )
    payload = dict(status)
    payload["exists"] = bool(status.get("exists", True))
    payload["path"] = str(path)
    payload["action"] = "stop"
    payload["stop_result"] = stop_result
    payload["stop_target_date"] = target
    payload["stopped_at_utc"] = utc_iso(now) if stop_result.get("stopped") else None
    if stop_result.get("stopped"):
        payload["status"] = "stopped"
        payload["pid_alive"] = False
    if write_back:
        write_json(path, payload)
    return payload


def load_status(
    path=DEFAULT_STATUS_PATH,
    *,
    now=None,
    pid_alive=pid_matches_market_making_run,
    write_back=False,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    activity_stat_fn=None,
):
    status = read_json(path)
    if not status:
        return {"exists": False, "path": str(path)}
    status = market_making_terminal_status_for_inactive_process(
        status,
        now=now,
        pid_alive=pid_alive,
        runs_root=status.get("runs_root") or DEFAULT_RUNS_ROOT,
        target_date=status.get("target_date") or target_date_for_roll(now=now),
        max_activity_age_seconds=max_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
        stat_fn=activity_stat_fn,
    )
    status["exists"] = True
    status["path"] = str(path)
    if write_back and status.get("status") in {"pid_missing", "idle_process"}:
        write_json(path, status)
    return status


def build_start_parser(parser):
    parser.add_argument("--date", default=None, help="Target market date. Defaults to the local date at launch.")
    parser.add_argument("--now", default=None, help="Testing timestamp used to compute the default date.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--budget-usdc", type=float, default=DEFAULT_BUDGET_USDC)
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=sorted(RUN_MODES))
    parser.add_argument("--markets", default=DEFAULT_MARKETS)
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--status-out", default=str(DEFAULT_STATUS_PATH))
    parser.add_argument("--console-log", default=str(DEFAULT_CONSOLE_LOG_PATH))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--once", action="store_true", help="Debug mode: start a one-tick run.")
    parser.add_argument("--config", action="append", default=[], help="Policy config override passed to market_making_run.")
    parser.add_argument("--evidence-mode", default=EVIDENCE_MODE_AUTO, choices=sorted(EVIDENCE_MODE_CHOICES))
    parser.add_argument(
        "--enable-market-harvest-companion",
        action="store_true",
        help="Opt in to the separate International market-harvest paper companion.",
    )
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--max-activity-age-seconds", type=float, default=DEFAULT_MAX_ACTIVITY_AGE_SECONDS)
    parser.add_argument("--startup-grace-seconds", type=float, default=DEFAULT_STARTUP_GRACE_SECONDS)
    return parser


def cmd_start(args):
    target = args.date or target_date_for_roll(now=args.now, timezone_name=args.timezone)
    payload = start_for_date(
        target,
        budget_usdc=args.budget_usdc,
        mode=args.mode,
        markets=args.markets,
        interval_seconds=args.interval_seconds,
        timezone_name=args.timezone,
        status_path=args.status_out,
        console_log_path=args.console_log,
        runs_root=Path(args.runs_root),
        force=args.force,
        once=args.once,
        config_overrides=args.config,
        evidence_mode=args.evidence_mode,
        market_harvest_companion=args.enable_market_harvest_companion,
        min_free_bytes=args.min_free_bytes,
        max_activity_age_seconds=args.max_activity_age_seconds,
        startup_grace_seconds=args.startup_grace_seconds,
        now=parse_datetime(args.now),
    )
    print(
        "Market-making daily roll: "
        f"{payload['status']} date={payload['target_date']} pid={payload.get('pid')}"
    )
    print(f"Status written to {payload['status_path']}")
    print(f"Console log: {payload['console_log_path']}")
    print(f"Evidence mode: {payload.get('evidence_mode')} ({(payload.get('evidence_classification') or {}).get('reason')})")
    return 0


def cmd_status(args):
    status = load_status(
        args.status_out,
        write_back=True,
        max_activity_age_seconds=args.max_activity_age_seconds,
        startup_grace_seconds=args.startup_grace_seconds,
    )
    print(json.dumps(status, indent=2, sort_keys=True, default=str))
    return 0 if status.get("exists") else 1


def cmd_ensure(args):
    target = args.date or target_date_for_roll(now=args.now, timezone_name=args.timezone)
    payload = ensure_for_date(
        target,
        budget_usdc=args.budget_usdc,
        mode=args.mode,
        markets=args.markets,
        interval_seconds=args.interval_seconds,
        timezone_name=args.timezone,
        status_path=args.status_out,
        diagnostics_path=args.diagnostics_out,
        console_log_path=args.console_log,
        runs_root=Path(args.runs_root),
        once=args.once,
        config_overrides=args.config,
        evidence_mode=args.evidence_mode,
        market_harvest_companion=args.enable_market_harvest_companion,
        min_free_bytes=args.min_free_bytes,
        max_activity_age_seconds=args.max_activity_age_seconds,
        startup_grace_seconds=args.startup_grace_seconds,
        now=parse_datetime(args.now),
        start_after_local_time=args.start_after_local_time,
        start_no_later_than_local_time=args.start_no_later_than_local_time,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def cmd_stop(args):
    payload = stop_status_file(
        args.status_out,
        target_date=args.date,
        now=args.now,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if (payload.get("stop_result") or {}).get("stopped") else 1


def build_parser():
    parser = argparse.ArgumentParser(description="Start the next daily paper market-making run.")
    sub = parser.add_subparsers(dest="command", required=True)
    start = build_start_parser(sub.add_parser("start"))
    start.set_defaults(func=cmd_start)
    status = sub.add_parser("status")
    status.add_argument("--status-out", default=str(DEFAULT_STATUS_PATH))
    status.add_argument("--max-activity-age-seconds", type=float, default=DEFAULT_MAX_ACTIVITY_AGE_SECONDS)
    status.add_argument("--startup-grace-seconds", type=float, default=DEFAULT_STARTUP_GRACE_SECONDS)
    status.set_defaults(func=cmd_status)
    ensure_parser = build_start_parser(sub.add_parser("ensure", help="Supervisor check: restart dead, idle, or stale-code maker rolls."))
    ensure_parser.add_argument("--diagnostics-out", default=str(DEFAULT_DIAGNOSTICS_PATH))
    ensure_parser.add_argument("--start-after-local-time", default=DEFAULT_START_AFTER_LOCAL_TIME)
    ensure_parser.add_argument(
        "--start-no-later-than-local-time",
        default=DEFAULT_START_NO_LATER_THAN_LOCAL_TIME,
    )
    ensure_parser.set_defaults(func=cmd_ensure)
    stop = sub.add_parser("stop", help="Stop the current paper market-making daily-roll process.")
    stop.add_argument("--date", default=None, help="Expected target date for the process. Defaults to status target_date.")
    stop.add_argument("--now", default=None, help="Testing timestamp for stopped_at_utc.")
    stop.add_argument("--status-out", default=str(DEFAULT_STATUS_PATH))
    stop.set_defaults(func=cmd_stop)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
