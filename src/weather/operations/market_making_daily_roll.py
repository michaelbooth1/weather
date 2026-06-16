"""Daily launcher for paper-live-forward market-making runs."""
from __future__ import annotations

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
from weather.market.market_making_run_constants import DEFAULT_RUNS_ROOT, RUN_MODES
from weather.operations.runtime_identity import get_runtime_identity
from weather.paths import REPO_ROOT
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("market_making_daily_roll")
DEFAULT_STATUS_PATH = DEFAULT_RUNS_ROOT / "daily_roll_status.json"
DEFAULT_CONSOLE_LOG_PATH = DEFAULT_RUNS_ROOT / "daily_roll_console.log"
DEFAULT_TASK_NAME = "WeatherMarketMakingDailyRoll"
DEFAULT_TIMEZONE = "America/Toronto"
DEFAULT_BUDGET_USDC = 500.0
DEFAULT_MODE = "paper-live-forward"
DEFAULT_MARKETS = "all"
DEFAULT_INTERVAL_SECONDS = 60.0


def utc_now():
    return datetime.now(timezone.utc)


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
):
    mode = str(mode)
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
        script = (
            f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\" "
            "-ErrorAction SilentlyContinue; if ($null -ne $p) { $p.CommandLine }"
        )
        command = ["powershell", "-NoProfile", "-Command", script]
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
    now=None,
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
        "runtime_identity": get_runtime_identity(),
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
    now=None,
    pid_alive=pid_matches_market_making_run,
    launcher=launch_market_making_process,
):
    target_date = ensure_date(target_date)
    status_path = Path(status_path)
    console_log_path = Path(console_log_path)
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
    )
    existing = read_json(status_path) or {}
    existing_pid = existing.get("pid")
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

    pid = launcher(command, repo_root=repo_root, console_log_path=console_log_path)
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
        now=now,
    )
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


def load_status(path=DEFAULT_STATUS_PATH):
    status = read_json(path)
    if not status:
        return {"exists": False, "path": str(path)}
    status["exists"] = True
    status["path"] = str(path)
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
        now=parse_datetime(args.now),
    )
    print(
        "Market-making daily roll: "
        f"{payload['status']} date={payload['target_date']} pid={payload.get('pid')}"
    )
    print(f"Status written to {payload['status_path']}")
    print(f"Console log: {payload['console_log_path']}")
    return 0


def cmd_status(args):
    status = load_status(args.status_out)
    print(json.dumps(status, indent=2, sort_keys=True, default=str))
    return 0 if status.get("exists") else 1


def build_parser():
    parser = argparse.ArgumentParser(description="Start the next daily paper market-making run.")
    sub = parser.add_subparsers(dest="command", required=True)
    start = build_start_parser(sub.add_parser("start"))
    start.set_defaults(func=cmd_start)
    status = sub.add_parser("status")
    status.add_argument("--status-out", default=str(DEFAULT_STATUS_PATH))
    status.set_defaults(func=cmd_status)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
