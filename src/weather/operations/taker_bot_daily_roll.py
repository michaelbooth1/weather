"""Daily launcher for paper taker-bot runs."""
from __future__ import annotations

from weather.operations.windows_silent import apply_windows_silent_subprocess_defaults

apply_windows_silent_subprocess_defaults()

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
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
from weather.market.taker_evidence_starvation import classify_taker_evidence_starvation
from weather.operations.bot_run_liveness import (
    DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    DEFAULT_MIN_FREE_BYTES,
    DEFAULT_STARTUP_GRACE_SECONDS,
    activity_liveness_preflight,
    age_seconds,
    disk_capacity_preflight,
    disk_full_status,
    failed_status,
    is_disk_full_error,
    parse_utc,
    terminal_status_for_inactive_process,
    utc_iso as liveness_utc_iso,
)
from weather.operations.bot_daily_roll_supervisor import ensure_daily_roll
from weather.operations.supervisor import (
    SupervisorSpec,
    acquire_file_lock,
    release_file_lock,
)
from weather.runtime_identity import get_runtime_identity
from weather.paths import REPO_ROOT
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("taker_bot_daily_roll")
DEFAULT_STATUS_PATH = DEFAULT_RUNS_ROOT / "daily_roll_status.json"
DEFAULT_CONSOLE_LOG_PATH = DEFAULT_RUNS_ROOT / "daily_roll_console.log"
DEFAULT_DIAGNOSTICS_PATH = DEFAULT_RUNS_ROOT / "daily_roll_diagnostics.jsonl"
DEFAULT_TASK_NAME = "WeatherTakerBotDailyRoll"
DEFAULT_SUPERVISOR_TASK_NAME = "WeatherTakerBotDailyRollSupervisor"
DEFAULT_TIMEZONE = "America/Toronto"
DEFAULT_START_AFTER_LOCAL_TIME = "00:05"
DEFAULT_BUDGET_USDC = 100.0
DEFAULT_MARKETS = "all"
DEFAULT_INTERVAL_SECONDS = 60.0
DEFAULT_STRATEGIES = DEFAULT_BAKEOFF_STRATEGIES
LAUNCH_LOCK_ATTEMPTS = 100
LAUNCH_LOCK_SLEEP_SECONDS = 0.1
LAUNCH_LOCK_STALE_AFTER_SECONDS = 600.0
COUNTERFACTUAL_RETENTION_FILENAMES = (
    "counterfactual_orders_long.csv",
    "settled_counterfactual_orders_long.csv",
)
COUNTERFACTUAL_RETENTION_PLAN_FILENAME = "counterfactual_retention_plan.json"
COUNTERFACTUAL_RETENTION_STATUS_FILENAME = "counterfactual_retention_status.json"
COUNTERFACTUAL_RETENTION_EVIDENCE_DIRNAME = "_counterfactual_retention"
PID_MATCH = "match"
PID_NO_MATCH = "no_match"
PID_MATCH_UNKNOWN = "unknown"
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
TAKER_DAILY_ROLL_SUPERVISOR = SupervisorSpec(
    name="taker_bot_daily_roll",
    module="weather.operations.taker_bot_daily_roll",
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
    """Return the process-safe lock that serializes taker lifecycle decisions."""
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
            "taker-bot daily-roll launch lock remained busy; refusing an "
            f"unserialized lifecycle decision ({lock_path})"
        )
    try:
        return callback()
    finally:
        release_file_lock(handle, lock_path)


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


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _self_hash(payload, field):
    body = dict(payload)
    body.pop(field, None)
    return hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def counterfactual_tape_retention_plan(
    runs_root=DEFAULT_RUNS_ROOT,
    *,
    retention_days=14,
    now=None,
    timezone_name=DEFAULT_TIMEZONE,
):
    """Plan exact old counterfactual tapes without depending on settlement."""

    root = Path(runs_root)
    try:
        retention_days = int(retention_days)
    except (TypeError, ValueError):
        retention_days = 0
    generated_at = parse_datetime(now) or utc_now()
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    generated_at = generated_at.astimezone(timezone.utc)
    local_today = generated_at.astimezone(ZoneInfo(timezone_name)).date()
    blockers = []
    if retention_days < 1:
        blockers.append(
            {
                "code": "INVALID_RETENTION_DAYS",
                "message": "counterfactual retention must be at least one day",
            }
        )
    if root.is_symlink():
        blockers.append(
            {
                "code": "RUNS_ROOT_SYMLINK",
                "message": "counterfactual retention refuses a symlinked runs root",
            }
        )
    candidates = []
    if root.is_dir() and not blockers:
        cutoff_date = local_today - timedelta(days=retention_days)
        cutoff_time = generated_at - timedelta(days=retention_days)
        for date_folder in sorted(root.iterdir()):
            if not date_folder.is_dir() or date_folder.is_symlink():
                continue
            try:
                target_date = date.fromisoformat(date_folder.name)
            except ValueError:
                continue
            if target_date > cutoff_date:
                continue
            for run_folder in sorted(date_folder.iterdir()):
                if not run_folder.is_dir() or run_folder.is_symlink():
                    continue
                for filename in COUNTERFACTUAL_RETENTION_FILENAMES:
                    path = run_folder / filename
                    if not path.is_file() or path.is_symlink():
                        continue
                    stat = path.stat()
                    modified_at = datetime.fromtimestamp(
                        stat.st_mtime,
                        tz=timezone.utc,
                    )
                    if modified_at > cutoff_time:
                        continue
                    candidates.append(
                        {
                            "path": str(path.resolve()),
                            "target_date": target_date.isoformat(),
                            "run_id": run_folder.name,
                            "filename": filename,
                            "byte_count": stat.st_size,
                            "sha256": _sha256_file(path),
                            "modified_at_utc": modified_at.isoformat(),
                            "retention_days": retention_days,
                            "settlement_summary_required": False,
                        }
                    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "counterfactual_tape_retention_plan",
        "status": "BLOCK" if blockers else "PASS",
        "generated_at_utc": generated_at.isoformat(),
        "runs_root": str(root.resolve()),
        "retention_days": retention_days,
        "cutoff_basis": "target_date_and_file_mtime",
        "settlement_summary_required": False,
        "allowlisted_filenames": list(COUNTERFACTUAL_RETENTION_FILENAMES),
        "candidate_count": len(candidates),
        "candidate_bytes": sum(row["byte_count"] for row in candidates),
        "candidates": candidates,
        "blockers": blockers,
    }
    payload["plan_sha256"] = _self_hash(payload, "plan_sha256")
    return payload


def apply_counterfactual_tape_retention(plan, *, runs_root=DEFAULT_RUNS_ROOT):
    """Apply one self-hashed, allowlisted retention plan and receipt every path."""

    root = Path(runs_root).resolve()
    blockers = []
    if plan.get("plan_sha256") != _self_hash(plan, "plan_sha256"):
        blockers.append(
            {
                "code": "PLAN_IDENTITY_MISMATCH",
                "message": "counterfactual retention plan self-hash does not verify",
            }
        )
    if Path(str(plan.get("runs_root") or "")).resolve() != root:
        blockers.append(
            {
                "code": "RUNS_ROOT_MISMATCH",
                "message": "counterfactual retention plan names a different runs root",
            }
        )
    if plan.get("status") != "PASS":
        blockers.extend(plan.get("blockers") or [])
    deleted = []
    skipped = []
    if not blockers:
        for candidate in plan.get("candidates") or []:
            path = Path(str(candidate.get("path") or ""))
            try:
                resolved = path.resolve()
                relative = resolved.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                skipped.append({**candidate, "reason": "path_outside_runs_root"})
                continue
            if (
                len(relative.parts) != 3
                or relative.parts[-1] not in COUNTERFACTUAL_RETENTION_FILENAMES
                or relative.parts[-1] != candidate.get("filename")
                or path.is_symlink()
                or not path.is_file()
            ):
                skipped.append({**candidate, "reason": "path_contract_changed"})
                continue
            stat = path.stat()
            if (
                stat.st_size != int(candidate.get("byte_count") or -1)
                or _sha256_file(path) != candidate.get("sha256")
            ):
                skipped.append({**candidate, "reason": "file_identity_changed"})
                continue
            try:
                path.unlink()
            except OSError as exc:
                skipped.append(
                    {
                        **candidate,
                        "reason": "delete_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            deleted.append(candidate)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "counterfactual_tape_retention_receipt",
        "status": (
            "BLOCK" if blockers else "PARTIAL" if skipped else "PASS"
        ),
        "generated_at_utc": plan.get("generated_at_utc"),
        "runs_root": str(root),
        "plan_sha256": plan.get("plan_sha256"),
        "settlement_summary_required": False,
        "deleted_count": len(deleted),
        "deleted_bytes": sum(row["byte_count"] for row in deleted),
        "deleted": deleted,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "blockers": blockers,
    }
    receipt["receipt_sha256"] = _self_hash(receipt, "receipt_sha256")
    return receipt


def enforce_counterfactual_tape_retention(
    runs_root=DEFAULT_RUNS_ROOT,
    *,
    retention_days=14,
    now=None,
    timezone_name=DEFAULT_TIMEZONE,
):
    """Plan and apply the declared counterfactual retention on every daily roll."""

    root = Path(runs_root)
    plan = counterfactual_tape_retention_plan(
        root,
        retention_days=retention_days,
        now=now,
        timezone_name=timezone_name,
    )
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / COUNTERFACTUAL_RETENTION_PLAN_FILENAME, plan)
    evidence_root = root / COUNTERFACTUAL_RETENTION_EVIDENCE_DIRNAME
    evidence_root.mkdir(parents=True, exist_ok=True)
    plan_evidence_path = evidence_root / f"{plan['plan_sha256']}.plan.json"
    if not plan_evidence_path.exists():
        write_json(plan_evidence_path, plan)
    receipt = apply_counterfactual_tape_retention(plan, runs_root=root)
    receipt_evidence_path = evidence_root / f"{plan['plan_sha256']}.receipt.json"
    receipt = {
        **receipt,
        "plan_evidence_path": str(plan_evidence_path.resolve()),
        "receipt_evidence_path": str(receipt_evidence_path.resolve()),
    }
    receipt["receipt_sha256"] = _self_hash(receipt, "receipt_sha256")
    if not receipt_evidence_path.exists():
        write_json(receipt_evidence_path, receipt)
    write_json(root / COUNTERFACTUAL_RETENTION_STATUS_FILENAME, receipt)
    return receipt


def runtime_taker_daily_roll_supervisor_spec(
    *,
    status_path=DEFAULT_STATUS_PATH,
    diagnostics_path=DEFAULT_DIAGNOSTICS_PATH,
    console_log_path=DEFAULT_CONSOLE_LOG_PATH,
):
    return TAKER_DAILY_ROLL_SUPERVISOR.with_paths(
        status_path=status_path,
        diagnostics_path=diagnostics_path,
        console_log_path=console_log_path,
    )


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
    disable_counterfactual_tape=False,
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
    if disable_counterfactual_tape:
        command.append("--disable-counterfactual-tape")
    return command


def _creationflags(detached=False):
    if os.name != "nt":
        return 0
    if detached:
        return subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.CREATE_NO_WINDOW


def process_command_line(
    pid,
    *,
    run_fn=subprocess.run,
    attempts=2,
    timeout_seconds=5.0,
    retry_delay_seconds=0.05,
    sleep_fn=time.sleep,
):
    """Return a process command line, ``""`` if absent, or ``None`` if unknown.

    Process lookup is advisory on a loaded host.  In particular, a PowerShell
    or CIM timeout does not prove that the process disappeared.  Preserve that
    distinction so callers can avoid converting a transient query failure into
    a false ``pid_missing`` recovery.
    """
    if not pid:
        return ""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return ""
    if os.name == "nt":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$process = Get-CimInstance Win32_Process "
                f"-Filter \"ProcessId = {pid}\" -ErrorAction Stop; "
                "if (-not $process) { exit 3 }; "
                "if ([string]::IsNullOrWhiteSpace([string]$process.CommandLine)) { exit 4 }; "
                "[Console]::Out.Write([string]$process.CommandLine)"
            ),
        ]
    else:
        command = ["ps", "-p", str(pid), "-o", "args="]
    attempt_count = max(1, int(attempts))
    for attempt in range(attempt_count):
        try:
            result = run_fn(
                command,
                capture_output=True,
                text=True,
                timeout=float(timeout_seconds),
                creationflags=_creationflags(),
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None:
            output = (result.stdout or "").strip()
            if result.returncode == 0 and output:
                return output
            # The PowerShell probe deliberately uses exit 3 only when CIM
            # successfully established that no such process exists.  POSIX ps
            # uses return code 1 for the same condition.
            if (os.name == "nt" and result.returncode == 3) or (
                os.name != "nt" and result.returncode == 1
            ):
                return ""
        if attempt + 1 < attempt_count and float(retry_delay_seconds) > 0:
            sleep_fn(float(retry_delay_seconds))
    return None


def taker_bot_pid_match_state(pid, target_date=None):
    """Return an exact-match tri-state for a recorded taker process PID."""
    command_line = process_command_line(pid)
    if command_line is None:
        return PID_MATCH_UNKNOWN
    if not command_line:
        return PID_NO_MATCH
    if not re.search(r"(?i)(?:^|\s)-m\s+weather\.market\.taker_bot(?:\s|$)", command_line):
        return PID_NO_MATCH
    if target_date and not re.search(
        rf"(?i)(?:^|\s)--date(?:=|\s+){re.escape(str(target_date))}(?:\s|$)",
        command_line,
    ):
        return PID_NO_MATCH
    # Command-line identity alone is not enough for a destructive match: the
    # PID may have exited between the CIM query and this live image check.
    if not pid_is_python(pid):
        return PID_MATCH_UNKNOWN
    return PID_MATCH


def pid_matches_taker_bot(pid, target_date=None):
    """Require an exact live module/date match for destructive operations."""
    return taker_bot_pid_match_state(pid, target_date) == PID_MATCH


def pid_is_live_taker_bot(pid, target_date=None):
    """Conservatively check liveness without weakening destructive matching.

    A failed command-line query is not evidence that the recorded process died.
    In that unknown case, the independent Win32 process-image lookup is enough
    to retain liveness.  Taker artifact-age checks remain responsible for
    detecting a live-but-idle or hung process.
    """
    match_state = taker_bot_pid_match_state(pid, target_date)
    if match_state == PID_MATCH:
        return True
    if match_state == PID_NO_MATCH:
        return False
    return bool(pid_is_python(pid))


def retire_taker_bot_process_tree(
    pid,
    target_date,
    *,
    run_fn=subprocess.run,
):
    """Terminate one command/date-verified taker process tree.

    Windows virtual-environment launchers retain the lightweight venv process
    as the recorded pid and run the memory-heavy interpreter as its child.
    Tree-aware retirement is therefore required at the date boundary; killing
    only the recorded launcher can orphan yesterday's worker.
    """
    if not pid_matches_taker_bot(pid, target_date):
        return {
            "pid": pid,
            "target_date": target_date,
            "stopped": False,
            "reason": "pid is not an exact live taker-bot command/date match",
        }
    try:
        normalized = int(pid)
    except (TypeError, ValueError):
        return {
            "pid": pid,
            "target_date": target_date,
            "stopped": False,
            "reason": "invalid pid",
        }
    if os.name == "nt":
        command = ["taskkill.exe", "/PID", str(normalized), "/T", "/F"]
        try:
            result = run_fn(
                command,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=_creationflags(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "pid": normalized,
                "target_date": target_date,
                "stopped": False,
                "reason": str(exc),
                "command": command,
            }
        return {
            "pid": normalized,
            "target_date": target_date,
            "stopped": result.returncode == 0,
            "returncode": result.returncode,
            "reason": None if result.returncode == 0 else (result.stderr or result.stdout or "taskkill failed").strip(),
            "command": command,
        }
    try:
        os.kill(normalized, 15)
    except OSError as exc:
        return {
            "pid": normalized,
            "target_date": target_date,
            "stopped": False,
            "reason": str(exc),
        }
    return {"pid": normalized, "target_date": target_date, "stopped": True}


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


def _summary_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _last_nonzero_scored_tick(summary):
    summary = summary or {}
    candidate = summary.get("last_nonzero_scored_tick")
    if isinstance(candidate, dict) and _summary_int(candidate.get("row_count")) > 0:
        return candidate
    cumulative_rows = _summary_int(summary.get("cumulative_order_rows"))
    latest_rows = _summary_int(summary.get("latest_tick_rows"))
    if cumulative_rows > 0 and latest_rows <= 0:
        return {
            "row_count": cumulative_rows,
            "filled_order_count": summary.get("cumulative_filled_orders"),
            "generated_at_utc": None,
            "captured_at_utc": None,
            "reason_counts": _top_reason_counts(summary),
            "basis": "cumulative_order_rows_fallback",
        }
    return {}


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
    evidence_starvation = classify_taker_evidence_starvation(summary)
    if evidence_starvation.get("status") == "BLOCK":
        return (
            str(evidence_starvation.get("classification") or "latest_tick_starvation").upper(),
            evidence_starvation.get("classification"),
        )
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
    summary = {}
    evidence_starvation = {}
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
            evidence_starvation = classify_taker_evidence_starvation(summary)
            summary_status, summary_root = _artifact_status_from_summary(summary)
            if summary_status != "PASS":
                status = summary_status
                root_cause = summary_root
                detail = evidence_starvation.get("detail") or f"latest run summary classified as {summary_root}"

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
        ok = status in {"PASS", "POLICY_NO_EDGE", "POLICY_GUARDRAIL_NO_TRADE"}

    summary = summary or (_read_run_summary(latest) if latest else {})
    evidence_starvation = evidence_starvation or classify_taker_evidence_starvation(summary)
    last_nonzero_scored_tick = (
        evidence_starvation.get("last_nonzero_scored_tick")
        or _last_nonzero_scored_tick(summary)
    )
    latest_tick_scoring_liveness = {
        "status": evidence_starvation.get("status"),
        "classification": evidence_starvation.get("classification"),
        "restart_recommended": evidence_starvation.get("restart_recommended"),
        "countability_status": evidence_starvation.get("countability_status"),
        "countability_blockers": evidence_starvation.get("countability_blockers") or [],
        "latest_tick_rows": evidence_starvation.get("latest_tick_rows"),
        "latest_tick_filled_orders": evidence_starvation.get("latest_tick_filled_orders"),
        "latest_tick_counterfactual_rows": evidence_starvation.get("latest_tick_counterfactual_rows"),
        "latest_tick_counterfactual_would_buy_count": evidence_starvation.get(
            "latest_tick_counterfactual_would_buy_count"
        ),
        "last_nonzero_scored_tick": last_nonzero_scored_tick,
        "first_failing_gate": evidence_starvation.get("first_failing_gate"),
        "first_failing_dependency": evidence_starvation.get("first_failing_dependency"),
        "remediation_command": evidence_starvation.get("remediation_command"),
        "detail": evidence_starvation.get("detail"),
    }
    upstream_dependency_status = evidence_starvation.get("upstream_dependency_status") or {}
    report = {
        "latest_run_folder": str(latest) if latest else None,
        "latest_useful_write_path": (latest_useful or {}).get("path"),
        "latest_useful_write_at_utc": (latest_useful or {}).get("modified_at_utc"),
        "latest_useful_write_age_seconds": (latest_useful or {}).get("age_seconds"),
        "latest_candidate_rows": summary.get("cumulative_order_rows") or summary.get("latest_tick_rows"),
        "latest_fill_count": summary.get("cumulative_filled_orders") or summary.get("latest_tick_filled_orders"),
        "latest_top_reason_counts": _top_reason_counts(summary),
        "latest_tick_rows": evidence_starvation.get("latest_tick_rows"),
        "last_nonzero_scored_tick_rows": last_nonzero_scored_tick.get("row_count"),
        "last_nonzero_scored_tick_filled_orders": last_nonzero_scored_tick.get("filled_order_count"),
        "last_nonzero_scored_tick_generated_at_utc": last_nonzero_scored_tick.get("generated_at_utc"),
        "last_nonzero_scored_tick_captured_at_utc": last_nonzero_scored_tick.get("captured_at_utc"),
        "last_nonzero_scored_tick": last_nonzero_scored_tick,
        "latest_tick_counterfactual_rows": evidence_starvation.get("latest_tick_counterfactual_rows"),
        "latest_tick_counterfactual_would_buy_count": evidence_starvation.get(
            "latest_tick_counterfactual_would_buy_count"
        ),
        "taker_day_classification": evidence_starvation.get("taker_day_classification"),
        "zero_would_buy_classification": evidence_starvation.get("zero_would_buy_classification"),
        "evidence_countability_status": evidence_starvation.get("countability_status"),
        "upstream_dependency_status": upstream_dependency_status.get("status"),
        "first_failing_dependency": upstream_dependency_status.get("first_failing_dependency"),
        "newest_snapshot_timestamp_utc": upstream_dependency_status.get("newest_snapshot_timestamp_utc"),
        "latest_source_status_utc": upstream_dependency_status.get("latest_source_status_utc"),
        "remediation_command": evidence_starvation.get("remediation_command"),
        "restart_recommended": not ok,
        "restart_reason": root_cause,
        "resource_diagnostics": summary.get("resource_diagnostics") or {},
        "incremental_persistence": summary.get("incremental_persistence") or {},
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
        "latest_tick_scoring_liveness": latest_tick_scoring_liveness,
        "upstream_dependency_status": upstream_dependency_status,
        "taker_evidence_starvation": evidence_starvation,
        "operator_report": report,
        "resource_diagnostics": summary.get("resource_diagnostics") or {},
        "incremental_persistence": summary.get("incremental_persistence") or {},
    }


def enrich_taker_liveness_status(
    payload,
    *,
    now=None,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    stat_fn=None,
    allow_pid_missing=False,
):
    eligible_statuses = {"started", "already_running", "idle_process"}
    if allow_pid_missing:
        eligible_statuses.add("pid_missing")
    if not payload or payload.get("status") not in eligible_statuses:
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
    payload["latest_tick_scoring_liveness"] = health.get("latest_tick_scoring_liveness") or {}
    payload["upstream_dependency_status"] = health.get("upstream_dependency_status") or {}
    payload["operator_report"] = health.get("operator_report") or {}
    payload["resource_diagnostics"] = health.get("resource_diagnostics") or {}
    payload["incremental_persistence"] = health.get("incremental_persistence") or {}
    if health.get("ok"):
        return payload
    scoring_liveness = health.get("latest_tick_scoring_liveness") or {}
    latest_tick_failure_statuses = {
        "LATEST_TICK_EMPTY",
        "SCORING_CRASH",
        "INFRA_STARVED_SNAPSHOT",
        "INFRA_STARVED_CLOB",
    }
    failing_gate = (
        "latest_tick_scoring_liveness"
        if (
            scoring_liveness.get("status") == "BLOCK"
            and health.get("status") in latest_tick_failure_statuses
        ) else
        "artifact_liveness"
    )
    payload.update({
        "status": "idle_process",
        "action": "blocked_restart_required",
        "terminal": True,
        "completed_at_utc": liveness_utc_iso(now),
        "first_failing_gate": failing_gate,
        "root_cause_class": health.get("root_cause_class") or "stale_pid_no_recent_useful_artifacts",
        "zero_trades_expected": False,
        "remediation_command": (
            scoring_liveness.get("remediation_command")
            or "quarantine stale or incomplete taker artifacts, then restart the daily roll with --force"
        ),
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
    original = dict(payload or {})
    original_status = original.get("status")
    original_action = original.get("action")
    alive = original.get("pid_alive")
    if pid_alive and original.get("pid"):
        try:
            alive = bool(pid_alive(original.get("pid"), target_date or original.get("target_date")))
        except (OSError, ValueError, TypeError):
            alive = False
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
    payload = enrich_taker_liveness_status(
        payload,
        now=now,
        max_activity_age_seconds=max_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
        stat_fn=stat_fn,
        allow_pid_missing=bool(alive),
    )
    # The shared activity preflight only runs for RUNNING_STATUSES, so a status
    # that is *already* persisted as idle_process or pid_missing arrives here
    # with no activity_liveness reading. Compute it for a live pid so a taker
    # that has since recovered -- including after a transient process-query
    # failure -- can be restored instead of staying stuck terminal across reads.
    if alive and not payload.get("activity_liveness"):
        payload["activity_liveness"] = activity_liveness_preflight(
            taker_activity_paths(root, target or target_date_for_roll(now=now)),
            now=now,
            max_activity_age_seconds=max_activity_age_seconds,
            startup_grace_seconds=startup_grace_seconds,
            started_at_utc=payload.get("started_at_utc") or payload.get("generated_at_utc"),
            stat_fn=stat_fn,
        )
    health = payload.get("artifact_liveness") or {}
    activity = payload.get("activity_liveness") or {}
    # `blocked_restart_required` should only be emitted when restarting the taker
    # is the appropriate remediation -- i.e. the process is dead (pid_missing) or
    # hung (alive but writing nothing: activity.ok False). A process that is alive
    # and still writing fresh run artifacts (the shared activity preflight PASSES)
    # is not idle/hung, so latest-tick *content/upstream* classifications must be
    # reported as a non-terminal advisory rather than a dead process needing a
    # bounce. Two such cases reach here for a live taker:
    #   (a) the shared activity gate tripped but the taker's own artifacts are
    #       healthy (first_failing_gate=activity_liveness, health.ok); and
    #   (b) the latest scoring tick is quiet or input-starved -- an empty tick
    #       (LATEST_TICK_EMPTY) or no fills attributed to snapshot/CLOB input
    #       (INFRA_STARVED_*). Restarting a live, active taker fixes none of
    #       these: an empty/no-edge tick has nothing to restart, and missing
    #       snapshot/CLOB input is an upstream-collection problem surfaced and
    #       repaired by the snapshot/CLOB monitors, not by bouncing the taker.
    # Genuine idle still latches terminal: a dead pid (pid_missing), no recent
    # writes at all (activity.ok False -> not live_and_active), a scoring crash
    # (SCORING_CRASH, where a restart can clear a wedged process), and stale or
    # missing taker artifacts (the taker's own output stopped, which also trips
    # the activity gate). These are deliberately left blocking.
    content_only_liveness_statuses = {
        "LATEST_TICK_EMPTY",
        "INFRA_STARVED_CLOB",
        "INFRA_STARVED_SNAPSHOT",
    }
    # live_and_active requires the shared activity preflight to PASS, which means
    # the process is writing fresh artifacts; that alone excludes the genuine
    # idle/hung case (stale activity -> activity.ok False). The health status
    # being a content classification is the discriminator; which gate enrich
    # attributed it to (latest_tick_scoring_liveness vs artifact_liveness, an
    # incidental of scoring_liveness) does not matter.
    live_and_active = bool(alive and activity.get("ok"))
    live_content_only = (
        live_and_active
        and str(health.get("status")) in content_only_liveness_statuses
    )
    activity_gate_false_idle = (
        alive
        and payload.get("first_failing_gate") == "activity_liveness"
        and health.get("ok")
    )
    false_dead_pid = (
        payload.get("status") == "pid_missing"
        and live_and_active
        and health.get("ok")
    )
    recoverable_idle = (
        payload.get("status") == "idle_process"
        and (live_content_only or activity_gate_false_idle)
    )
    if false_dead_pid or recoverable_idle:
        restored_status = original_status if original_status in {"started", "already_running"} else "already_running"
        # Restoring to a running status must clear any terminal action. A cached
        # `blocked_restart_required` from a prior persisted idle state must not be
        # inherited here (the bug this guards against), so derive the action from
        # the restored status rather than from the original action.
        non_terminal_action = "noop" if restored_status == "already_running" else "start"
        restored_action = (
            original_action
            if original_action in {"noop", "start", "already_running"}
            else non_terminal_action
        )
        payload.update({
            "status": restored_status,
            "action": restored_action,
            "terminal": False,
            "pid_alive": True,
            "zero_trades_expected": health.get("status") in {"POLICY_NO_EDGE", "LATEST_TICK_EMPTY"},
        })
        payload.pop("completed_at_utc", None)
        if false_dead_pid:
            payload.pop("first_failing_gate", None)
            if payload.get("root_cause_class") == "pid_missing":
                payload.pop("root_cause_class", None)
            if payload.get("remediation_command") == (
                "inspect the console log, then restart the daily roll with --force"
            ):
                payload.pop("remediation_command", None)
        # Preserve the artifact-content signal as a non-terminal advisory so a
        # quiet/empty or input-starved latest tick stays visible for operators
        # (and routes to the upstream collection monitors) without masquerading
        # as a dead process that needs a restart.
        if live_content_only:
            payload["artifact_health_status"] = health.get("status")
        # Keep the operator report consistent with the non-terminal decision: a
        # live, active taker is not a restart candidate.
        operator_report = payload.get("operator_report")
        if isinstance(operator_report, dict) and operator_report.get("restart_recommended"):
            operator_report = dict(operator_report)
            operator_report["restart_recommended"] = False
            payload["operator_report"] = operator_report
        if health.get("ok") and health.get("root_cause_class"):
            payload["root_cause_class"] = health.get("root_cause_class")
        else:
            payload.pop("root_cause_class", None)
        for key in ("completed_at_utc", "first_failing_gate", "remediation_command"):
            payload.pop(key, None)
    return payload


def quarantine_unhealthy_taker_run_folder(
    runs_root,
    target_date,
    *,
    artifact_health=None,
    now=None,
    force=False,
):
    health = artifact_health or taker_artifact_health(runs_root, target_date, now=now)
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
    markets,
    interval_seconds,
    timezone_name,
    status_path,
    console_log_path,
    runs_root,
    command,
    disk_preflight=None,
    config_warnings=None,
    counterfactual_retention=None,
    counterfactual_tape_enabled=True,
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
        "counterfactual_tape_enabled": bool(counterfactual_tape_enabled),
        "counterfactual_retention": counterfactual_retention or {},
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
    disable_counterfactual_tape=False,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    disk_usage_fn=None,
    activity_stat_fn=None,
    now=None,
    pid_alive=pid_is_live_taker_bot,
    launcher=launch_taker_bot_process,
    force_retire_latest_run=False,
    retire_process_tree=retire_taker_bot_process_tree,
    retire_superseded_process=True,
    _launch_lock_held=False,
):
    if not _launch_lock_held:
        return _run_with_daily_roll_launch_lock(
            lambda: start_for_date(
                target_date,
                budget_usdc=budget_usdc,
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
                strategies=strategies,
                experiment_id=experiment_id,
                disable_counterfactual_tape=disable_counterfactual_tape,
                min_free_bytes=min_free_bytes,
                max_activity_age_seconds=max_activity_age_seconds,
                startup_grace_seconds=startup_grace_seconds,
                disk_usage_fn=disk_usage_fn,
                activity_stat_fn=activity_stat_fn,
                now=now,
                pid_alive=pid_alive,
                launcher=launcher,
                force_retire_latest_run=force_retire_latest_run,
                retire_process_tree=retire_process_tree,
                retire_superseded_process=retire_superseded_process,
                _launch_lock_held=True,
            ),
            status_path=status_path,
        )
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
        disable_counterfactual_tape=disable_counterfactual_tape,
    )
    effective_config = {**DEFAULT_CONFIG, **parse_config_overrides(config_overrides or [])}
    if disable_counterfactual_tape:
        effective_config["counterfactual_tape_enabled"] = False
    retention = enforce_counterfactual_tape_retention(
        runs_root,
        retention_days=effective_config.get("counterfactual_retention_days") or 14,
        now=now,
        timezone_name=timezone_name,
    )
    config_warnings = current_high_trust_config_warnings(effective_config)
    existing = read_json(status_path) or {}
    existing_pid = existing.get("pid")
    existing_target_date = existing.get("target_date")
    superseded_process_retirement = None
    if (
        retire_superseded_process
        and existing_pid
        and existing_target_date
        and existing_target_date != target_date
        and pid_alive(existing_pid, existing_target_date)
    ):
        superseded_process_retirement = retire_process_tree(existing_pid, existing_target_date)
        if not superseded_process_retirement.get("stopped"):
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
                config_warnings=config_warnings,
                counterfactual_retention=retention,
                counterfactual_tape_enabled=effective_config.get(
                    "counterfactual_tape_enabled", True
                ),
                now=now,
            )
            payload.update({
                "status": "blocked_superseded_process",
                "action": "blocked_start",
                "terminal": True,
                "status_persisted": False,
                "superseded_target_date": existing_target_date,
                "superseded_pid": existing_pid,
                "superseded_process_retirement": superseded_process_retirement,
                "remediation_command": (
                    "verify and retire the exact prior-date taker process tree, then rerun the daily roll"
                ),
            })
            return payload
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
                counterfactual_retention=retention,
                counterfactual_tape_enabled=effective_config.get(
                    "counterfactual_tape_enabled", True
                ),
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
            counterfactual_retention=retention,
            counterfactual_tape_enabled=effective_config.get(
                "counterfactual_tape_enabled", True
            ),
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
            for key in (
                "activity_liveness",
                "artifact_liveness",
                "latest_tick_scoring_liveness",
                "upstream_dependency_status",
                "operator_report",
            ):
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
            force=force_retire_latest_run,
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
        counterfactual_retention=retention,
        counterfactual_tape_enabled=effective_config.get(
            "counterfactual_tape_enabled", True
        ),
        now=now,
    )
    if forced_run_retirement is not None:
        payload["forced_run_retirement"] = forced_run_retirement
    if superseded_process_retirement is not None:
        payload["superseded_process_retirement"] = superseded_process_retirement
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
    if superseded_process_retirement is not None:
        payload["superseded_process_retirement"] = superseded_process_retirement
    write_json(status_path, payload)
    return payload


def start_for_current_day(*, now=None, timezone_name=DEFAULT_TIMEZONE, **kwargs):
    return start_for_date(
        target_date_for_roll(now=now, timezone_name=timezone_name),
        now=now,
        timezone_name=timezone_name,
        **kwargs,
    )


def ensure_for_date(
    target_date,
    *,
    budget_usdc=DEFAULT_BUDGET_USDC,
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
    strategies=None,
    experiment_id=None,
    disable_counterfactual_tape=False,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    max_activity_age_seconds=DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
    disk_usage_fn=None,
    activity_stat_fn=None,
    now=None,
    pid_alive=pid_is_live_taker_bot,
    pid_stop_check=None,
    launcher=launch_taker_bot_process,
    start_after_local_time=DEFAULT_START_AFTER_LOCAL_TIME,
    current_identity=None,
    _launch_lock_held=False,
):
    if not _launch_lock_held:
        return _run_with_daily_roll_launch_lock(
            lambda: ensure_for_date(
                target_date,
                budget_usdc=budget_usdc,
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
                strategies=strategies,
                experiment_id=experiment_id,
                disable_counterfactual_tape=disable_counterfactual_tape,
                min_free_bytes=min_free_bytes,
                max_activity_age_seconds=max_activity_age_seconds,
                startup_grace_seconds=startup_grace_seconds,
                disk_usage_fn=disk_usage_fn,
                activity_stat_fn=activity_stat_fn,
                now=now,
                pid_alive=pid_alive,
                pid_stop_check=pid_stop_check,
                launcher=launcher,
                start_after_local_time=start_after_local_time,
                current_identity=current_identity,
                _launch_lock_held=True,
            ),
            status_path=status_path,
        )
    target_date = ensure_date(target_date)
    spec = runtime_taker_daily_roll_supervisor_spec(
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
            strategies=strategies,
            experiment_id=experiment_id,
            disable_counterfactual_tape=disable_counterfactual_tape,
            min_free_bytes=min_free_bytes,
            max_activity_age_seconds=max_activity_age_seconds,
            startup_grace_seconds=startup_grace_seconds,
            disk_usage_fn=disk_usage_fn,
            activity_stat_fn=activity_stat_fn,
            now=now,
            pid_alive=pid_alive,
            launcher=launcher,
            force_retire_latest_run=force_retire_latest_run,
            retire_superseded_process=False,
            _launch_lock_held=True,
        )

    return ensure_daily_roll(
        spec=spec,
        target_date=target_date,
        load_status_fn=load_current_status,
        start_fn=start_recovery,
        pid_alive=pid_alive,
        pid_stop_check=pid_stop_check or (
            pid_matches_taker_bot if pid_alive is pid_is_live_taker_bot else pid_alive
        ),
        write_status_fn=write_json,
        now=now,
        current_identity=current_identity,
        timezone_name=timezone_name,
        start_after_local_time=start_after_local_time,
    )


def ensure_for_current_day(*, now=None, timezone_name=DEFAULT_TIMEZONE, **kwargs):
    return ensure_for_date(
        target_date_for_roll(now=now, timezone_name=timezone_name),
        now=now,
        timezone_name=timezone_name,
        **kwargs,
    )


def load_status(
    path=DEFAULT_STATUS_PATH,
    *,
    now=None,
    pid_alive=pid_is_live_taker_bot,
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
    parser.add_argument(
        "--disable-counterfactual-tape",
        action="store_true",
        help="Disable counterfactual strategy-replay tape generation for the launched run.",
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
        disable_counterfactual_tape=args.disable_counterfactual_tape,
        min_free_bytes=args.min_free_bytes,
        max_activity_age_seconds=args.max_activity_age_seconds,
        startup_grace_seconds=args.startup_grace_seconds,
        now=parse_datetime(args.now),
    )
    print(
        "Taker-bot daily roll: "
        f"{payload['status']} date={payload['target_date']} pid={payload.get('pid')}"
    )
    if payload.get("status_persisted", True):
        print(f"Status written to {payload['status_path']}")
    else:
        print(f"Existing status preserved at {payload['status_path']}")
    print(f"Console log: {payload['console_log_path']}")
    return 1 if payload.get("status") == "blocked_superseded_process" else 0


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
        markets=args.markets,
        interval_seconds=args.interval_seconds,
        timezone_name=args.timezone,
        status_path=args.status_out,
        diagnostics_path=args.diagnostics_out,
        console_log_path=args.console_log,
        runs_root=Path(args.runs_root),
        once=args.once,
        config_overrides=args.config,
        strategies=args.strategies,
        experiment_id=args.experiment_id,
        disable_counterfactual_tape=args.disable_counterfactual_tape,
        min_free_bytes=args.min_free_bytes,
        max_activity_age_seconds=args.max_activity_age_seconds,
        startup_grace_seconds=args.startup_grace_seconds,
        now=parse_datetime(args.now),
        start_after_local_time=args.start_after_local_time,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


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
    ensure_parser = build_start_parser(sub.add_parser("ensure", help="Supervisor check: restart dead, idle, or stale-code taker rolls."))
    ensure_parser.add_argument("--diagnostics-out", default=str(DEFAULT_DIAGNOSTICS_PATH))
    ensure_parser.add_argument("--start-after-local-time", default=DEFAULT_START_AFTER_LOCAL_TIME)
    ensure_parser.set_defaults(func=cmd_ensure)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
