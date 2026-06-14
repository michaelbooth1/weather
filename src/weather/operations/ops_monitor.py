"""Operational monitor helpers for the Streamlit dashboard."""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from market_microstructure import (
    CLOB_DIAGNOSTICS_PATH,
    CLOB_LOOP_CONSOLE_LOG_PATH,
    CLOB_LOOP_STATUS_PATH,
    CLOB_PAUSE_FLAG_PATH,
    DEFAULT_BOOK_INTERVAL_SECONDS,
    DEFAULT_FAST_INTERVAL_SECONDS,
    acquire_clob_supervisor_lock,
    clob_loop_health,
    ensure_clob_loop,
    read_clob_loop_status,
    release_clob_supervisor_lock,
    start_clob_loop_detached,
    stop_clob_loop,
    utc_now,
)
from observation_trigger import (
    CONSOLE_LOG_PATH as OBSERVATION_CONSOLE_LOG_PATH,
    DIAGNOSTICS_PATH as OBSERVATION_DIAGNOSTICS_PATH,
    STATUS_PATH as OBSERVATION_STATUS_PATH,
    TASK_NAME as OBSERVATION_TASK_NAME,
    ensure_watcher_loop,
    read_status as read_observation_status,
    start_watcher_detached,
    stop_watcher_loop,
    watcher_health,
)
from runtime_identity import format_runtime_identity, get_runtime_identity, identities_match
from snapshot_tracker import (
    DIAGNOSTICS_PATH,
    LOOP_CONSOLE_LOG_PATH,
    LOOP_STATUS_PATH,
    PAUSE_FLAG_PATH,
    TORONTO_TZ,
    ensure_loop,
    loop_health,
    read_loop_status,
    start_loop_detached,
    stop_loop,
)


SNAPSHOT_TASK_NAME = "WeatherSnapshotLoopSupervisor"
CLOB_TASK_NAME = "WeatherClobBookLoopSupervisor"
DAILY_REFRESH_TASK_NAME = "WeatherDailySettlementPromotionRefresh"


def _code_state(runtime_identity, current_identity):
    if not runtime_identity:
        return "unknown"
    if identities_match(runtime_identity, current_identity):
        return "current"
    return "different"


def _format_age(value, unit):
    if value is None:
        return "-"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if unit == "seconds":
        return f"{value:.0f}s"
    return f"{value:.1f}m"


def _latest_trigger_summary(status):
    latest = (status or {}).get("latest_triggered") or {}
    if not latest:
        return "-"
    parts = []
    for market_id, item in sorted(latest.items()):
        top_temp = item.get("top_temp")
        top_probability = item.get("top_probability")
        snapshot_id = item.get("snapshot_id")
        if top_temp is None:
            parts.append(f"{market_id}:{snapshot_id}")
        elif top_probability is None:
            parts.append(f"{market_id}:{top_temp}")
        else:
            parts.append(f"{market_id}:{top_temp}@{float(top_probability):.0%}")
    return "; ".join(parts[:4]) + ("; ..." if len(parts) > 4 else "")


def _trade_permission_summary(status):
    trade_permission = (status or {}).get("trade_permission") or {}
    if not trade_permission:
        return "-"
    return "yes" if trade_permission.get("trade_permissioned") else "no"


def _loop_row(
    name,
    health,
    status,
    current_identity,
    status_path,
    diagnostics_path,
    console_log_path,
):
    runtime_identity = (status or {}).get("runtime_identity")
    heartbeat = (
        _format_age(health.get("heartbeat_age_min"), "minutes")
        if "heartbeat_age_min" in health
        else _format_age(health.get("heartbeat_age_seconds"), "seconds")
    )
    capture = (
        _format_age(health.get("last_snapshot_age_min"), "minutes")
        if "last_snapshot_age_min" in health
        else _format_age(health.get("last_books_age_seconds"), "seconds")
    )
    return {
        "Loop": name,
        "State": health.get("state"),
        "PID": health.get("pid"),
        "Heartbeat": heartbeat,
        "Last Capture": capture,
        "Errors": health.get("consecutive_errors"),
        "Paused": bool((status or {}).get("paused")),
        "Mode": health.get("last_mode") or "-",
        "Running Code": format_runtime_identity(runtime_identity),
        "Code State": _code_state(runtime_identity, current_identity),
        "Started At": health.get("started_at"),
        "Last Error": health.get("last_error"),
        "Latest Trigger FV": _latest_trigger_summary(status),
        "Trade Permissioned": _trade_permission_summary(status),
        "Status File": str(status_path),
        "Diagnostics": str(diagnostics_path),
        "Console Log": str(console_log_path),
    }


def loop_status_rows(current_identity=None):
    current_identity = current_identity or get_runtime_identity()
    weather_status = read_loop_status()
    weather_health = loop_health(weather_status, datetime.now(TORONTO_TZ))
    clob_status = read_clob_loop_status()
    clob_health = clob_loop_health(clob_status, now=utc_now())
    observation_status = read_observation_status()
    observation_health = watcher_health(observation_status, now=utc_now())
    return [
        _loop_row(
            "Weather snapshots",
            weather_health,
            weather_status,
            current_identity,
            LOOP_STATUS_PATH,
            DIAGNOSTICS_PATH,
            LOOP_CONSOLE_LOG_PATH,
        ),
        _loop_row(
            "CLOB books",
            clob_health,
            clob_status,
            current_identity,
            CLOB_LOOP_STATUS_PATH,
            CLOB_DIAGNOSTICS_PATH,
            CLOB_LOOP_CONSOLE_LOG_PATH,
        ),
        _loop_row(
            "Observation triggers",
            observation_health,
            observation_status,
            current_identity,
            OBSERVATION_STATUS_PATH,
            OBSERVATION_DIAGNOSTICS_PATH,
            OBSERVATION_CONSOLE_LOG_PATH,
        ),
    ]


def set_pause_flag(path, paused):
    path = Path(path)
    if paused:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return {"paused": True, "path": str(path)}
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return {"paused": False, "path": str(path)}


def set_weather_paused(paused):
    return set_pause_flag(PAUSE_FLAG_PATH, paused)


def set_clob_paused(paused):
    return set_pause_flag(CLOB_PAUSE_FLAG_PATH, paused)


def start_all_loops():
    return {
        "weather": ensure_loop(),
        "clob": ensure_clob_loop(
            market_id="all",
            interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
            fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
        ),
        "observation_trigger": ensure_watcher_loop(),
    }


def ensure_weather_loop():
    return ensure_loop()


def ensure_clob_book_loop():
    return ensure_clob_loop(
        market_id="all",
        interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
        fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
    )


def ensure_observation_trigger_loop():
    return ensure_watcher_loop()


def restart_weather_loop():
    return {"stop": stop_loop(), "start": start_loop_detached()}


def restart_clob_loop():
    lock_handle = acquire_clob_supervisor_lock()
    if lock_handle is None:
        return {"restarted": False, "reason": "another CLOB supervisor action is running"}
    try:
        return {
            "stop": stop_clob_loop(),
            "start": start_clob_loop_detached(
                market_id="all",
                interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
                fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
            ),
        }
    finally:
        release_clob_supervisor_lock(lock_handle)


def restart_observation_trigger_loop():
    return {"stop": stop_watcher_loop(), "start": start_watcher_detached()}


def stop_all_loops():
    return {
        "weather": stop_loop(),
        "clob": stop_clob_loop(),
        "observation_trigger": stop_watcher_loop(),
    }


def stop_weather_loop():
    return stop_loop()


def stop_clob_book_loop():
    return stop_clob_loop()


def stop_observation_trigger_loop():
    return stop_watcher_loop()


def _creationflags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def scheduled_task_status(task_name):
    if os.name != "nt":
        return {
            "Task": task_name,
            "Registered": False,
            "State": "unsupported",
            "Last Run": None,
            "Next Run": None,
            "Result": None,
        }
    script = f"""
$task = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue
if ($null -eq $task) {{
    $row = [pscustomobject]@{{
        Task = '{task_name}'
        Registered = $false
        State = 'missing'
        LastRun = $null
        NextRun = $null
        Result = $null
    }}
}} else {{
    $info = Get-ScheduledTaskInfo -TaskName $task.TaskName
    $row = [pscustomobject]@{{
        Task = $task.TaskName
        Registered = $true
        State = [string]$task.State
        LastRun = [string]$info.LastRunTime
        NextRun = [string]$info.NextRunTime
        Result = $info.LastTaskResult
    }}
}}
$row | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_creationflags(),
        )
    except (OSError, subprocess.SubprocessError):
        return {
            "Task": task_name,
            "Registered": False,
            "State": "error",
            "Last Run": None,
            "Next Run": None,
            "Result": None,
        }
    if result.returncode != 0 or not result.stdout.strip():
        return {
            "Task": task_name,
            "Registered": False,
            "State": "error",
            "Last Run": None,
            "Next Run": None,
            "Result": result.stderr.strip() or result.returncode,
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}
    return {
        "Task": payload.get("Task", task_name),
        "Registered": bool(payload.get("Registered")),
        "State": payload.get("State"),
        "Last Run": payload.get("LastRun"),
        "Next Run": payload.get("NextRun"),
        "Result": payload.get("Result"),
    }


def scheduled_task_rows():
    return [
        scheduled_task_status(SNAPSHOT_TASK_NAME),
        scheduled_task_status(CLOB_TASK_NAME),
        scheduled_task_status(OBSERVATION_TASK_NAME),
        scheduled_task_status(DAILY_REFRESH_TASK_NAME),
    ]
