"""Lightweight proven-healthy ensure path; recovery stays with loop owners."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import math
import os
import subprocess

from weather.paths import REPO_ROOT, data_path
from weather.runtime_identity import current_identity_for, identities_match
from weather.operations import supervisor as supervision


def supervisor_spec(loop, root=None):
    root = root or data_path() / "snapshots"
    snapshot = loop == "snapshot"
    return supervision.SupervisorSpec(
        name="snapshot_capture" if snapshot else "clob_capture",
        module="weather.collection.snapshot_tracker" if snapshot else "weather.market.market_microstructure",
        status_path=root / ("loop_status.json" if snapshot else "clob_loop_status.json"),
        diagnostics_path=root / ("diagnostics.jsonl" if snapshot else "clob_diagnostics.jsonl"),
        console_log_path=root / ("loop_console.log" if snapshot else "clob_loop_console.log"),
        cwd=REPO_ROOT,
        pause_flag_path=root / ("loop_pause.flag" if snapshot else "clob_loop_pause.flag"),
        lock_path=root / ("loop_supervisor.lock" if snapshot else ".clob_supervisor.lock"),
        restart_budget=6 if snapshot else 12,
    )


def process_rows():
    if os.name == "nt":
        from weather.operations.windows_processes import python_process_rows
        return python_process_rows()
    result = subprocess.run(["ps", "-eo", "pid=,comm=,args="], capture_output=True,
                            text=True, timeout=15)
    if result.returncode:
        raise OSError("process inventory failed")
    rows = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3:
            rows.append({"pid": int(parts[0]), "name": parts[1], "command_line": parts[2]})
    return rows


def _healthy_result(loop, spec, status, now):
    """Only a strict subset of canonical RUNNING states may skip heavy imports."""
    if not isinstance(status, dict) or not status:
        return None
    try:
        if status.get("paused") or int(status.get("consecutive_errors") or 0):
            return None
        identity = status.get("runtime_identity")
        if not isinstance(identity, dict) or not identity.get("source_scope_files"):
            return None
        current = current_identity_for(identity)
        if not identities_match(identity, current):
            return None
        alive = supervision.pid_is_python(status.get("pid"))
        if not alive:
            return None
        writer = supervision.loop_writer_lock_health(
            spec.status_path, status_pid=status["pid"], status_pid_alive=alive)
        if not writer.get("healthy"):
            return None
        heartbeat = supervision.age_seconds(now, status.get("last_heartbeat"), default_tz=timezone.utc)
        if loop == "snapshot":
            interval = float(status.get("interval_minutes", 10))
            limit = (2 * interval + 2) * 60
        else:
            interval = float(status.get("interval_seconds") or 60)
            # Stricter than the owner's expanded long-iteration tolerance.
            limit = max(2 * interval + 30, 90)
        if not math.isfinite(interval) or interval <= 0 or heartbeat is None or not 0 <= heartbeat <= limit:
            return None
        result = {"action": "noop", "state": "RUNNING", "pid": status["pid"],
                  "restart_cause": None, "writer_lock": writer,
                  "runtime_identity_before": identity, "current_runtime_identity": current}
        if loop == "clob":
            if (status.get("target_date") or status.get("error_markets")
                    or status.get("include_price_history") or status.get("include_ws_events")
                    or status.get("raw_freshness_sla_breach")):
                return None
            markets = status.get("last_market_results") or {}
            if not markets or not all(
                isinstance(row, dict) and not row.get("error") and row.get("status") != "BLOCK"
                and (row.get("event_metadata_validation") or {}).get("ok") is not False
                and (float(row.get("books") or 0) > 0 or float(row.get("captured_tokens") or 0) > 0)
                for row in markets.values()
            ):
                return None
            matches = [row for row in process_rows()
                       if "market_microstructure" in str(row.get("command_line", "")).lower()
                       and " loop" in str(row.get("command_line", "")).lower()
                       and int(row["pid"]) != os.getpid()]
            if not matches or len(matches) > (2 if os.name == "nt" else 1):
                return None
            if int(status["pid"]) not in {int(row["pid"]) for row in matches}:
                return None
            result.update(running_process_count=len(matches), running_pids=[row["pid"] for row in matches],
                          orphan_processes_detected=False, runtime_identity_matches_current=True,
                          preserved_target_date_from_status=False, target_mode_mismatch=False,
                          status_target_date=None, requested_target_date=None)
        result["recovery_guard"] = supervision.supervisor_recovery_guard(spec, "noop", now=now)
        return result
    except (OSError, TypeError, ValueError, KeyError, subprocess.SubprocessError):
        return None


def ensure(loop, *, interval_minutes=10.0, market="all", interval_seconds=60,
           fast_interval_seconds=15, now=None, root=None):
    now = now or datetime.now(timezone.utc)
    spec = supervisor_spec(loop, root)
    handle = supervision.acquire_file_lock(spec.lock_path, attempts=2 if loop == "snapshot" else 30)
    if handle is None:
        return supervision.persist_supervisor_status(spec, {
            "action": "locked", "state": "UNKNOWN",
            "reason": "another supervisor action is running"}, now=now)
    try:
        status = supervision.read_json_file(spec.status_path)
        result = _healthy_result(loop, spec, status, now)
        if result is not None:
            return supervision.persist_supervisor_status(spec, result, now=now)
    finally:
        supervision.release_file_lock(handle, spec.lock_path)
    # Release the same lock before the canonical ensure routine acquires it.
    # It re-observes all state; this probe grants no start/stop authority.
    module = importlib.import_module(spec.module)
    if loop == "snapshot":
        return module.ensure_loop(interval_minutes=interval_minutes, now=now)
    return module.ensure_clob_loop(market_id=market, interval_seconds=interval_seconds,
                                   fast_interval_seconds=fast_interval_seconds, now=now)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ensure", action="store_true", required=True)
    parser.add_argument("--loop", choices=("snapshot", "clob"), required=True)
    parser.add_argument("--interval-minutes", type=float, default=10)
    parser.add_argument("--market", default="all")
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--fast-interval-seconds", type=float, default=15)
    args = parser.parse_args(argv)
    result = ensure(args.loop, interval_minutes=args.interval_minutes, market=args.market,
                    interval_seconds=args.interval_seconds, fast_interval_seconds=args.fast_interval_seconds)
    print(json.dumps(result, sort_keys=True, default=str))
    return supervision.ensure_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
