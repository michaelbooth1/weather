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
from weather.market.taker_bot import DEFAULT_BAKEOFF_STRATEGIES, DEFAULT_RUNS_ROOT, DEFAULT_CONFIG
from weather.operations.bot_run_liveness import (
    DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    DEFAULT_MIN_FREE_BYTES,
    DEFAULT_STARTUP_GRACE_SECONDS,
    disk_capacity_preflight,
    disk_full_status,
    failed_status,
    is_disk_full_error,
    terminal_status_for_inactive_process,
)
from weather.operations.runtime_identity import get_runtime_identity
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
)


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
    paths = [Path(console_log_path)]
    day_root = Path(runs_root) / ensure_date(target_date)
    if day_root.exists():
        for run_folder in sorted(day_root.glob("*")):
            if not run_folder.is_dir():
                continue
            paths.extend(run_folder / name for name in ACTIVITY_FILENAMES)
    return paths


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
    now=None,
):
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
    existing = read_json(status_path) or {}
    existing_pid = existing.get("pid")
    if existing.get("target_date") == target_date and existing.get("status") in {"started", "already_running"}:
        refreshed = terminal_status_for_inactive_process(
            existing,
            now=now,
            pid_alive=pid_alive,
            activity_paths=taker_activity_paths(
                existing.get("runs_root") or runs_root,
                target_date,
                existing.get("console_log_path") or console_log_path,
            ),
            max_activity_age_seconds=max_activity_age_seconds,
            startup_grace_seconds=startup_grace_seconds,
            stat_fn=activity_stat_fn,
        )
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
            now=now,
        )
        payload.update({
            "status": "already_running",
            "action": "noop",
            "pid": existing_pid,
            "started_at_utc": existing.get("started_at_utc"),
            "previous_status_generated_at_utc": existing.get("generated_at_utc"),
        })
        write_json(status_path, payload)
        return payload

    disk_preflight = disk_capacity_preflight(
        runs_root,
        min_free_bytes=min_free_bytes,
        usage_fn=disk_usage_fn,
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
        now=now,
    )
    if not disk_preflight.get("ok"):
        payload = disk_full_status(payload, preflight=disk_preflight, now=now)
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
    status = terminal_status_for_inactive_process(
        status,
        now=now,
        pid_alive=pid_alive,
        activity_paths=taker_activity_paths(
            status.get("runs_root") or DEFAULT_RUNS_ROOT,
            status.get("target_date") or target_date_for_roll(now=now),
            status.get("console_log_path") or DEFAULT_CONSOLE_LOG_PATH,
        ),
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
