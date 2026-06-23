"""Daily launcher for paper taker-bot runs."""
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
from weather.market.taker_bot import (
    DEFAULT_BAKEOFF_STRATEGIES,
    DEFAULT_RUNS_ROOT,
    DEFAULT_CONFIG,
    current_high_trust_config_warnings,
    parse_config_overrides,
)
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
from weather.runtime_identity import get_runtime_identity
from weather.paths import REPO_ROOT
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("taker_bot_daily_roll")
DEFAULT_STATUS_PATH = DEFAULT_RUNS_ROOT / "daily_roll_status.json"
DEFAULT_CONSOLE_LOG_PATH = DEFAULT_RUNS_ROOT / "daily_roll_console.log"
DEFAULT_TASK_NAME = "WeatherTakerBotDailyRoll"
DEFAULT_TIMEZONE = "America/Toronto"
DEFAULT_BUDGET_USDC = 100.0
DEFAULT_MARKETS = "all"
DEFAULT_INTERVAL_SECONDS = 60.0
DEFAULT_STRATEGIES = DEFAULT_BAKEOFF_STRATEGIES
ACTIVITY_FILENAMES = (
    "orders_long.csv",
    "budget_ledger.jsonl",
    "daily_pnl.json",
    "run_summary.json",
    "strategy_summary.json",
)
REQUIRED_LATEST_RUN_ARTIFACTS = (
    "orders_long.csv",
    "run_summary.json",
    "strategy_summary.json",
)
QUARANTINE_DIR_NAME = "_quarantine"


def utc_now():
    return datetime.now(timezone.utc)


def parse_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def utc_iso(now=None):
    parsed = parse_datetime(now) or utc_now()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


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


def build_taker_bot_command(
    target_date,
    *,
    budget_usdc=DEFAULT_BUDGET_USDC,
    markets=DEFAULT_MARKETS,
    interval_seconds=DEFAULT_INTERVAL_SECONDS,
    python_executable=None,
    runs_root=None,
    once=False,
    config_overrides=None,
    strategies=DEFAULT_STRATEGIES,
    experiment_id=None,
):
    command = [
        str(python_executable or sys.executable),
        "-m",
        "weather.market.taker_bot",
        "--date",
        ensure_date(target_date),
        "--budget-usdc",
        format_number(budget_usdc),
        "--markets",
        str(markets),
        "--interval-seconds",
        format_number(interval_seconds),
    ]
    if not once:
        command.append("--loop")
    if runs_root:
        command.extend(["--runs-root", str(runs_root)])
    if strategies:
        command.extend(["--strategies", str(strategies)])
    if experiment_id:
        command.extend(["--experiment-id", str(experiment_id)])
    for override in config_overrides or []:
        command.extend(["--config", str(override)])
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


def pid_matches_taker_bot(pid, target_date=None):
    if not pid_is_python(pid):
        return False
    command_line = process_command_line(pid)
    if not command_line:
        return True
    text = command_line.lower()
    if "taker_bot" not in text:
        return False
    if target_date and str(target_date) not in command_line:
        return False
    return True


def launch_taker_bot_process(command, *, repo_root=REPO_ROOT, console_log_path=DEFAULT_CONSOLE_LOG_PATH):
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


def taker_activity_paths(runs_root, target_date, console_log_path=DEFAULT_CONSOLE_LOG_PATH):
    paths = []
    day_root = Path(runs_root) / ensure_date(target_date)
    if day_root.exists():
        for run_folder in sorted(day_root.glob("*")):
            if not run_folder.is_dir():
                continue
            if run_folder.name == QUARANTINE_DIR_NAME or run_folder.name.startswith("."):
                continue
            paths.extend(run_folder / name for name in ACTIVITY_FILENAMES)
    return paths


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


def taker_run_folders(runs_root, target_date):
    day_root = Path(runs_root) / ensure_date(target_date)
    if not day_root.exists():
        return []
    folders = []
    for folder in day_root.iterdir():
        if not folder.is_dir():
            continue
        if folder.name == QUARANTINE_DIR_NAME or folder.name.startswith("."):
            continue
        folders.append(folder)
    return sorted(folders)


def latest_taker_run_folder(runs_root, target_date, *, stat_fn=None):
    folders = taker_run_folders(runs_root, target_date)
    if not folders:
        return None
    return max(
        folders,
        key=lambda folder: (
            _run_folder_latest_mtime(folder, stat_fn=stat_fn) or datetime.min.replace(tzinfo=timezone.utc),
            folder.name,
        ),
    )


def _read_run_summary(run_folder):
    payload = read_json(Path(run_folder) / "run_summary.json") or {}
    return payload.get("summary") or {}


def _top_reason_counts(summary, limit=8):
    counts = summary.get("reason_counts") or {}
    if not isinstance(counts, dict):
        return {}
    return dict(sorted(counts.items(), key=lambda item: (-int(item[1] or 0), item[0]))[:limit])


def _reason_count(summary, code):
    try:
        return int((summary.get("reason_counts") or {}).get(code) or 0)
    except (TypeError, ValueError):
        return 0


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


def _artifact_status_from_summary(summary):
    latest_rows = int(summary.get("latest_tick_rows") or 0)
    latest_fills = int(summary.get("latest_tick_filled_orders") or 0)
    stale_model = _reason_count(summary, "NO_TRADE_STALE_MODEL")
    stale_book = _reason_count(summary, "NO_TRADE_STALE_BOOK")
    total_reasons = sum(
        int(value or 0)
        for value in (summary.get("reason_counts") or {}).values()
        if isinstance(value, (int, float)) or str(value).isdigit()
    )
    if latest_fills <= 0 and stale_model > 0:
        return "STALE_MODEL_INPUT", "stale_model_input"
    if latest_fills <= 0 and stale_book > 0 and (total_reasons == 0 or stale_book / total_reasons >= 0.5):
        return "STALE_BOOK_INPUT", "stale_book_input"
    if latest_fills <= 0 and (summary.get("root_cause_class") == "policy_no_edge" or latest_rows > 0):
        return "POLICY_NO_EDGE", "policy_no_edge"
    return "PASS", None


def taker_artifact_health(
    runs_root,
    target_date,
    *,
    now=None,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    started_at_utc=None,
    stat_fn=None,
):
    current = parse_utc(now) or datetime.now(timezone.utc)
    folders = taker_run_folders(runs_root, target_date)
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

    latest = latest_taker_run_folder(runs_root, target_date, stat_fn=stat_fn)
    try:
        files = [path for path in latest.iterdir() if path.is_file()]
    except OSError:
        files = []
    useful_paths = [latest / name for name in ACTIVITY_FILENAMES]
    latest_useful = _latest_useful_artifact_row(useful_paths, now=current, stat_fn=stat_fn)
    missing_required = [name for name in REQUIRED_LATEST_RUN_ARTIFACTS if _path_stat(latest / name, stat_fn=stat_fn) is None]
    status = "PASS"
    root_cause = None
    detail = "latest taker run artifacts are current"
    if not files:
        status = "EMPTY_RUN_FOLDER"
        root_cause = "empty_run_artifact_folder"
        detail = "latest taker run folder has no files"
    elif "orders_long.csv" in missing_required:
        status = "MISSING_ORDERS_TAPE"
        root_cause = "missing_orders_tape"
        detail = "latest taker run folder is missing orders_long.csv"
    elif "run_summary.json" in missing_required:
        status = "MISSING_HEARTBEAT_METADATA"
        root_cause = "missing_heartbeat_metadata"
        detail = "latest taker run folder is missing run_summary.json"
    elif "strategy_summary.json" in missing_required:
        status = "MISSING_STRATEGY_SUMMARY"
        root_cause = "missing_strategy_summary"
        detail = "latest taker run folder is missing strategy_summary.json"
    else:
        run_summary_mtime = _path_mtime_utc(latest / "run_summary.json", stat_fn=stat_fn)
        strategy_mtime = _path_mtime_utc(latest / "strategy_summary.json", stat_fn=stat_fn)
        if run_summary_mtime is not None:
            run_summary_age = max(0.0, (current - run_summary_mtime).total_seconds())
        else:
            run_summary_age = None
        if strategy_mtime is not None:
            strategy_age = max(0.0, (current - strategy_mtime).total_seconds())
        else:
            strategy_age = None
        if run_summary_age is not None and run_summary_age > float(max_activity_age_seconds):
            status = "STALE_HEARTBEAT_METADATA"
            root_cause = "stale_heartbeat_metadata"
            detail = "run_summary.json is stale"
        elif strategy_age is not None and strategy_age > float(max_activity_age_seconds):
            status = "STALE_STRATEGY_SUMMARY"
            root_cause = "stale_strategy_summary"
            detail = "strategy_summary.json is stale"
        else:
            summary = _read_run_summary(latest)
            summary_status, summary_root = _artifact_status_from_summary(summary)
            if summary_status != "PASS":
                status = summary_status
                root_cause = summary_root
                detail = f"latest run summary classified as {summary_root}"

    if status != "PASS" and in_startup_grace and status in {
        "EMPTY_RUN_FOLDER",
        "MISSING_ORDERS_TAPE",
        "MISSING_HEARTBEAT_METADATA",
        "MISSING_STRATEGY_SUMMARY",
    }:
        ok = True
        root_cause = None
        detail = f"{detail}; still inside startup grace"
        status = "STARTUP_GRACE"
    else:
        ok = status in {"PASS", "POLICY_NO_EDGE"}

    summary = _read_run_summary(latest) if latest else {}
    report = {
        "latest_run_folder": str(latest) if latest else None,
        "latest_useful_write_path": (latest_useful or {}).get("path"),
        "latest_useful_write_at_utc": (latest_useful or {}).get("modified_at_utc"),
        "latest_useful_write_age_seconds": (latest_useful or {}).get("age_seconds"),
        "latest_candidate_rows": summary.get("cumulative_order_rows") or summary.get("latest_tick_rows"),
        "latest_fill_count": summary.get("cumulative_filled_orders") or summary.get("latest_tick_filled_orders"),
        "latest_top_reason_counts": _top_reason_counts(summary),
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
        "operator_report": report,
    }


def enrich_taker_liveness_status(
    payload,
    *,
    now=None,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    stat_fn=None,
):
    if not payload or payload.get("status") not in {"started", "already_running", "idle_process"}:
        return payload
    health = taker_artifact_health(
        payload.get("runs_root") or DEFAULT_RUNS_ROOT,
        payload.get("target_date") or target_date_for_roll(now=now),
        now=now,
        max_activity_age_seconds=max_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
        started_at_utc=payload.get("started_at_utc") or payload.get("generated_at_utc"),
        stat_fn=stat_fn,
    )
    payload["artifact_liveness"] = health
    payload["operator_report"] = health.get("operator_report") or {}
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
        "remediation_command": "quarantine stale or incomplete taker artifacts, then restart the daily roll with --force",
    })
    return payload


def taker_terminal_status_for_inactive_process(
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
    target = target_date or (payload or {}).get("target_date")
    root = runs_root or (payload or {}).get("runs_root") or DEFAULT_RUNS_ROOT
    payload = terminal_status_for_inactive_process(
        payload,
        now=now,
        pid_alive=pid_alive,
        activity_paths=taker_activity_paths(root, target or target_date_for_roll(now=now)),
        max_activity_age_seconds=max_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
        stat_fn=stat_fn,
    )
    return enrich_taker_liveness_status(
        payload,
        now=now,
        max_activity_age_seconds=max_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
        stat_fn=stat_fn,
    )


def quarantine_unhealthy_taker_run_folder(
    runs_root,
    target_date,
    *,
    artifact_health=None,
    now=None,
):
    health = artifact_health or taker_artifact_health(runs_root, target_date, now=now)
    if health.get("ok"):
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
    }


def _base_payload(
    *,
    target_date,
    budget_usdc,
    markets,
    interval_seconds,
    timezone_name,
    status_path,
    console_log_path,
    runs_root,
    command,
    disk_preflight=None,
    config_warnings=None,
    now=None,
):
    config_warnings = list(config_warnings or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "runner": "taker_bot_daily_roll",
        "generated_at_utc": utc_iso(now),
        "target_date": ensure_date(target_date),
        "timezone": timezone_name,
        "budget_usdc": float(budget_usdc),
        "markets": markets,
        "interval_seconds": float(interval_seconds),
        "runs_root": str(runs_root),
        "status_path": str(status_path),
        "console_log_path": str(console_log_path),
        "command": list(command),
        "policy_defaults": dict(DEFAULT_CONFIG),
        "config_warning_count": len(config_warnings),
        "config_warnings": config_warnings,
        "runtime_identity": get_runtime_identity(),
        "disk_capacity_preflight": disk_preflight or {},
    }


def start_for_date(
    target_date,
    *,
    budget_usdc=DEFAULT_BUDGET_USDC,
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
    strategies=None,
    experiment_id=None,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    disk_usage_fn=None,
    activity_stat_fn=None,
    now=None,
    pid_alive=pid_matches_taker_bot,
    launcher=launch_taker_bot_process,
):
    target_date = ensure_date(target_date)
    status_path = Path(status_path)
    console_log_path = Path(console_log_path)
    command = build_taker_bot_command(
        target_date,
        budget_usdc=budget_usdc,
        markets=markets,
        interval_seconds=interval_seconds,
        python_executable=python_executable,
        runs_root=runs_root,
        once=once,
        config_overrides=config_overrides,
        strategies=strategies,
        experiment_id=experiment_id,
    )
    effective_config = {**DEFAULT_CONFIG, **parse_config_overrides(config_overrides or [])}
    config_warnings = current_high_trust_config_warnings(effective_config)
    existing = read_json(status_path) or {}
    existing_pid = existing.get("pid")
    existing_liveness = None
    if existing.get("target_date") == target_date and existing.get("status") in {"started", "already_running"}:
        refreshed = taker_terminal_status_for_inactive_process(
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
                markets=markets,
                interval_seconds=interval_seconds,
                timezone_name=timezone_name,
                status_path=status_path,
                console_log_path=console_log_path,
                runs_root=runs_root,
                command=existing.get("command") or command,
                disk_preflight=existing.get("disk_capacity_preflight") or {},
                config_warnings=config_warnings,
                now=now,
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
            markets=markets,
            interval_seconds=interval_seconds,
            timezone_name=timezone_name,
            status_path=status_path,
            console_log_path=console_log_path,
            runs_root=runs_root,
            command=existing.get("command") or command,
            disk_preflight=existing.get("disk_capacity_preflight") or {},
            config_warnings=config_warnings,
            now=now,
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
            artifact_status = (payload.get("artifact_liveness") or {}).get("status")
            artifact_root = (payload.get("artifact_liveness") or {}).get("root_cause_class")
            if artifact_status == "POLICY_NO_EDGE":
                payload["root_cause_class"] = artifact_root
                payload["zero_trades_expected"] = True
        write_json(status_path, payload)
        return payload

    disk_preflight = disk_capacity_preflight(
        runs_root,
        min_free_bytes=min_free_bytes,
        usage_fn=disk_usage_fn,
    )
    forced_run_retirement = None
    if force and existing.get("target_date") == target_date:
        health = taker_artifact_health(
            existing.get("runs_root") or runs_root,
            target_date,
            now=now,
            max_activity_age_seconds=max_activity_age_seconds,
            startup_grace_seconds=startup_grace_seconds,
            started_at_utc=existing.get("started_at_utc") or existing.get("generated_at_utc"),
            stat_fn=activity_stat_fn,
        )
        forced_run_retirement = quarantine_unhealthy_taker_run_folder(
            existing.get("runs_root") or runs_root,
            target_date,
            artifact_health=health,
            now=now,
        )
    payload = _base_payload(
        target_date=target_date,
        budget_usdc=budget_usdc,
        markets=markets,
        interval_seconds=interval_seconds,
        timezone_name=timezone_name,
        status_path=status_path,
        console_log_path=console_log_path,
        runs_root=runs_root,
        command=command,
        disk_preflight=disk_preflight,
        config_warnings=config_warnings,
        now=now,
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


def start_for_current_day(*, now=None, timezone_name=DEFAULT_TIMEZONE, **kwargs):
    return start_for_date(
        target_date_for_roll(now=now, timezone_name=timezone_name),
        now=now,
        timezone_name=timezone_name,
        **kwargs,
    )


def load_status(
    path=DEFAULT_STATUS_PATH,
    *,
    now=None,
    pid_alive=pid_matches_taker_bot,
    write_back=False,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    activity_stat_fn=None,
):
    status = read_json(path)
    if not status:
        return {"exists": False, "path": str(path)}
    status = taker_terminal_status_for_inactive_process(
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
    parser.add_argument("--markets", default=DEFAULT_MARKETS)
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--status-out", default=str(DEFAULT_STATUS_PATH))
    parser.add_argument("--console-log", default=str(DEFAULT_CONSOLE_LOG_PATH))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--once", action="store_true", help="Debug mode: start a one-tick run.")
    parser.add_argument("--config", action="append", default=[], help="Config override passed to taker_bot.")
    parser.add_argument("--strategies", default=None, help="Comma-separated taker strategy IDs to run.")
    parser.add_argument("--experiment-id", default=None, help="Stable taker strategy experiment ID.")
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--max-activity-age-seconds", type=float, default=DEFAULT_MAX_ACTIVITY_AGE_SECONDS)
    parser.add_argument("--startup-grace-seconds", type=float, default=DEFAULT_STARTUP_GRACE_SECONDS)
    return parser


def cmd_start(args):
    target = args.date or target_date_for_roll(now=args.now, timezone_name=args.timezone)
    payload = start_for_date(
        target,
        budget_usdc=args.budget_usdc,
        markets=args.markets,
        interval_seconds=args.interval_seconds,
        timezone_name=args.timezone,
        status_path=args.status_out,
        console_log_path=args.console_log,
        runs_root=Path(args.runs_root),
        force=args.force,
        once=args.once,
        config_overrides=args.config,
        strategies=args.strategies,
        experiment_id=args.experiment_id,
        min_free_bytes=args.min_free_bytes,
        max_activity_age_seconds=args.max_activity_age_seconds,
        startup_grace_seconds=args.startup_grace_seconds,
        now=parse_datetime(args.now),
    )
    print(
        "Taker-bot daily roll: "
        f"{payload['status']} date={payload['target_date']} pid={payload.get('pid')}"
    )
    print(f"Status written to {payload['status_path']}")
    print(f"Console log: {payload['console_log_path']}")
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


def build_parser():
    parser = argparse.ArgumentParser(description="Start the daily paper taker-bot run.")
    sub = parser.add_subparsers(dest="command", required=True)
    start = build_start_parser(sub.add_parser("start"))
    start.set_defaults(func=cmd_start)
    status = sub.add_parser("status")
    status.add_argument("--status-out", default=str(DEFAULT_STATUS_PATH))
    status.add_argument("--max-activity-age-seconds", type=float, default=DEFAULT_MAX_ACTIVITY_AGE_SECONDS)
    status.add_argument("--startup-grace-seconds", type=float, default=DEFAULT_STARTUP_GRACE_SECONDS)
    status.set_defaults(func=cmd_status)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
