from weather.operations.windows_silent import apply_windows_silent_subprocess_defaults

apply_windows_silent_subprocess_defaults()

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

import requests

from weather.io import read_csv_rows as io_read_csv_rows
from weather.market.market_config import config_from_event, config_for_date
from weather.market.market_microstructure_features import write_clob_feature_rows
from weather.market.market_registry import all_specs, spec_for_id
from weather.market.polymarket_client import PolymarketClient
from weather.model.model_sources import request_with_retries
from weather.operations.power import keep_system_awake
from weather.runtime_identity import current_identity_for, get_runtime_identity, identities_match
from weather.operations.supervisor import (
    SupervisorSpec,
    acquire_file_lock,
    acquire_writer_lock,
    age_seconds as supervisor_age_seconds,
    append_jsonl,
    attach_status_writer,
    atomic_write_json,
    configure_json_console_logging,
    file_lock_is_stale,
    launch_detached,
    loop_file_offsets,
    pid_is_python,
    process_query_creationflags,
    quarantine_malformed_loop_lines,
    read_writer_lock,
    read_json_file,
    release_file_lock,
    release_writer_lock,
    should_emit_recovery_block_diagnostic,
    supervisor_recovery_guard,
    terminate_python_pid,
)
from weather.paths import REPO_ROOT

from weather.market.market_microstructure_constants import (  # noqa: E402
    BOOK_LEVEL_COLUMNS,
    BOOK_SUMMARY_COLUMNS,
    CLOB_BASE_URL,
    CLOB_DIAGNOSTICS_PATH,
    CLOB_LOOP_CONSOLE_LOG_PATH,
    CLOB_LOOP_STATUS_PATH,
    CLOB_PAUSE_FLAG_PATH,
    CLOB_SUPERVISOR_LOCK_PATH,
    CLOB_WS_URL,
    DEFAULT_BATCH_SIZE,
    DEFAULT_BOOK_INTERVAL_SECONDS,
    DEFAULT_CLOB_FEATURE_MAX_AGE_SECONDS,
    DEFAULT_FAST_INTERVAL_SECONDS,
    DEFAULT_INCLUDE_PRICE_HISTORY,
    DEFAULT_INCLUDE_WS_EVENTS,
    DEFAULT_LOOP_INCLUDE_PRICE_HISTORY,
    DEFAULT_LOOP_INCLUDE_WS_EVENTS,
    DEFAULT_WS_CONNECT_TIMEOUT,
    DEFAULT_WS_HEARTBEAT_SECONDS,
    DEFAULT_WS_MESSAGE_LIMIT,
    DEFAULT_WS_SECONDS,
    FIXED_EXECUTION_SIZES,
    PRICE_HISTORY_COLUMNS,
    SNAPSHOT_DATA_ROOT,
    TOKEN_COLUMNS,
    WS_EVENT_COLUMNS,
)
from weather.market.market_microstructure_capture import (  # noqa: E402
    ClobClient,
    MarketMicrostructureStore,
    capture_event_books,
    capture_fleet_books,
    capture_fleet_books_parallel,
    capture_id_for_book,
    capture_market_books,
    chunked,
    depth_within,
    filter_token_rows,
    imbalance,
    label_bin_metadata,
    normalize_levels,
    order_book_level_rows,
    parse_json_list,
    payload_sha1,
    price_for_outcome,
    price_history_rows,
    read_price_history_raw_response,
    record_market_websocket,
    repair_price_history_store,
    status_value,
    summarize_order_book,
    timestamp_to_iso,
    to_number,
    token_rows_from_event,
    token_sort_key,
    vwap_for_size,
    ws_summary_rows,
)


CLOB_SUPERVISOR = SupervisorSpec(
    name="clob_capture",
    module="weather.market.market_microstructure",
    status_path=CLOB_LOOP_STATUS_PATH,
    diagnostics_path=CLOB_DIAGNOSTICS_PATH,
    console_log_path=CLOB_LOOP_CONSOLE_LOG_PATH,
    cwd=REPO_ROOT,
    pause_flag_path=CLOB_PAUSE_FLAG_PATH,
    lock_path=CLOB_SUPERVISOR_LOCK_PATH,
    tolerated_states=("RUNNING", "PAUSED", "DEGRADED", "ERRORING"),
    status_schema_fields=(
        "pid",
        "started_at",
        "last_heartbeat",
        "market_id",
        "interval_seconds",
        "fast_interval_seconds",
        "consecutive_errors",
        "error_markets",
        "last_error",
        "paused",
    ),
    restart_budget=12,
    restart_budget_window_hours=24.0,
    restart_backoff_base_seconds=120.0,
    restart_backoff_max_seconds=3600.0,
)


def runtime_clob_supervisor_spec():
    return CLOB_SUPERVISOR.with_paths(
        status_path=CLOB_LOOP_STATUS_PATH,
        diagnostics_path=CLOB_DIAGNOSTICS_PATH,
        console_log_path=CLOB_LOOP_CONSOLE_LOG_PATH,
        pause_flag_path=CLOB_PAUSE_FLAG_PATH,
        lock_path=CLOB_SUPERVISOR_LOCK_PATH,
    )


def utc_now():
    return datetime.now(timezone.utc)


def read_clob_loop_status(path=None):
    return read_json_file(path or CLOB_LOOP_STATUS_PATH)


def write_clob_loop_status(status, path=None):
    return atomic_write_json(path or CLOB_LOOP_STATUS_PATH, status)


def append_clob_diagnostic(record, path=None):
    return append_jsonl(path or CLOB_DIAGNOSTICS_PATH, record)


def clob_supervisor_lock_is_stale(path=None, max_age_seconds=120):
    return file_lock_is_stale(path or CLOB_SUPERVISOR_LOCK_PATH, max_age_seconds=max_age_seconds)


def acquire_clob_supervisor_lock(path=None, attempts=30, sleep_fn=time.sleep):
    return acquire_file_lock(
        path or CLOB_SUPERVISOR_LOCK_PATH,
        attempts=attempts,
        stale_after_seconds=120,
        sleep_seconds=0.1,
        sleep_fn=sleep_fn,
    )


def release_clob_supervisor_lock(handle, path=None):
    release_file_lock(handle, path or CLOB_SUPERVISOR_LOCK_PATH)


def _age_seconds(now, iso_value):
    return supervisor_age_seconds(now, iso_value, default_tz=timezone.utc)


def clob_discovery_sanity_from_status(status):
    results = (status or {}).get("last_market_results") or {}
    if not results:
        return {"status": "UNKNOWN", "ok": True, "reason": "no loop market results recorded yet"}
    rows = [row for row in results.values() if isinstance(row, dict)]
    if not rows:
        return {"status": "UNKNOWN", "ok": True, "reason": "loop market results are not structured"}
    metadata_blocked = [
        row for row in rows
        if ((row.get("event_metadata_validation") or {}).get("ok") is False)
        or row.get("status") == "BLOCK"
    ]
    if metadata_blocked and len(metadata_blocked) == len(rows):
        first_gate = metadata_blocked[0].get("event_metadata_validation") or {}
        return {
            "status": "BLOCK",
            "ok": False,
            "root_cause": "event_metadata_validation_blocked",
            "reason": first_gate.get("reason") or "event metadata validation blocked the latest CLOB loop iteration",
            "market_count": len(rows),
            "remediation_command": first_gate.get("remediation_command")
            or "python -m weather.operations.event_metadata_validation --target-date <YYYY-MM-DD>",
        }
    all_zero_tokens = all((to_number(row.get("captured_tokens")) or 0) == 0 for row in rows)
    all_zero_books = all((to_number(row.get("books")) or 0) == 0 for row in rows)
    all_no_error = all(not row.get("error") for row in rows)
    if all_zero_tokens and all_zero_books and all_no_error:
        return {
            "status": "BLOCK",
            "ok": False,
            "root_cause": "blank_or_inactive_clob_discovery",
            "reason": "last CLOB loop iteration captured zero tokens and zero books for every market",
            "market_count": len(rows),
            "remediation_command": "python -m weather.market.market_microstructure capture --market all",
        }
    return {
        "status": "PASS",
        "ok": True,
        "reason": "latest CLOB loop results captured tokens or books, or produced explicit market errors",
        "market_count": len(rows),
    }


def clob_loop_health(status, now=None, interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS):
    """Heartbeat-based liveness for the fast market-book loop."""
    now = now or utc_now()
    if not status:
        return {"state": "UNKNOWN", "detail": "no CLOB loop status file"}
    interval = to_number(status.get("interval_seconds")) or float(interval_seconds)
    heartbeat_age = _age_seconds(now, status.get("last_heartbeat"))
    capture_age = _age_seconds(now, status.get("last_books_captured_at"))
    raw_capture_age = _age_seconds(now, status.get("last_raw_books_captured_at"))
    derived_capture_age = _age_seconds(now, status.get("last_derived_features_captured_at"))
    errors = int(status.get("consecutive_errors") or 0)
    error_markets = status.get("error_markets") or []
    discovery_sanity = clob_discovery_sanity_from_status(status)
    last_market_results = status.get("last_market_results") or {}
    last_target_dates_by_market = {
        market: value.get("target_date")
        for market, value in last_market_results.items()
        if isinstance(value, dict) and value.get("target_date")
    }
    last_event_slugs_by_market = {
        market: value.get("event_slug")
        for market, value in last_market_results.items()
        if isinstance(value, dict) and value.get("event_slug")
    }
    configured_target_date = status.get("target_date")
    target_date_mismatch_markets = sorted(
        market
        for market, target in last_target_dates_by_market.items()
        if configured_target_date and target != configured_target_date
    )
    dead_after = max(2 * interval + 30.0, 90.0)
    if status.get("paused"):
        state = "PAUSED"
    elif heartbeat_age is None or heartbeat_age > dead_after:
        state = "DEAD"
    elif errors >= 3:
        state = "ERRORING"
    elif error_markets or target_date_mismatch_markets or not discovery_sanity.get("ok", True):
        state = "DEGRADED"
    else:
        state = "RUNNING"
    return {
        "state": state,
        "pid": status.get("pid"),
        "heartbeat_age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        "last_books_age_seconds": round(capture_age, 1) if capture_age is not None else None,
        "last_raw_books_age_seconds": round(raw_capture_age, 1) if raw_capture_age is not None else None,
        "last_derived_features_age_seconds": (
            round(derived_capture_age, 1) if derived_capture_age is not None else None
        ),
        "consecutive_errors": errors,
        "error_markets": error_markets,
        "last_error": status.get("last_error"),
        "discovery_sanity": discovery_sanity,
        "started_at": status.get("started_at"),
        "market_id": status.get("market_id"),
        "target_date": configured_target_date,
        "date_selection": status.get("date_selection") or (
            "fixed_target_date" if configured_target_date else "market_local_date"
        ),
        "interval_seconds": interval,
        "fast_interval_seconds": status.get("fast_interval_seconds"),
        "include_price_history": status.get("include_price_history"),
        "include_ws_events": status.get("include_ws_events"),
        "websocket_message_limit": status.get("websocket_message_limit"),
        "last_mode": status.get("last_mode"),
        "last_sleep_seconds": status.get("last_sleep_seconds"),
        "last_market_results": last_market_results,
        "last_event_slugs_by_market": last_event_slugs_by_market,
        "last_target_dates_by_market": last_target_dates_by_market,
        "target_date_mismatch_markets": target_date_mismatch_markets,
        "last_raw_books_captured_at": status.get("last_raw_books_captured_at"),
        "last_raw_books_by_market": status.get("last_raw_books_by_market") or {},
        "raw_book_market_ages_seconds": {
            market: (round(age, 1) if age is not None else None)
            for market, age in (
                (market, _age_seconds(now, captured_at))
                for market, captured_at in (status.get("last_raw_books_by_market") or {}).items()
            )
        },
        "raw_book_useful_iterations": int(status.get("raw_book_useful_iterations") or 0),
        "last_derived_features_captured_at": status.get("last_derived_features_captured_at"),
        "last_derived_features_by_market": status.get("last_derived_features_by_market") or {},
        "derived_feature_market_ages_seconds": {
            market: (round(age, 1) if age is not None else None)
            for market, age in (
                (market, _age_seconds(now, captured_at))
                for market, captured_at in (status.get("last_derived_features_by_market") or {}).items()
            )
        },
        "derived_feature_error_markets": status.get("derived_feature_error_markets") or [],
        "last_iteration_elapsed_seconds": status.get("last_iteration_elapsed_seconds"),
        "max_iteration_elapsed_seconds": status.get("max_iteration_elapsed_seconds"),
        "max_recent_iteration_elapsed_seconds": status.get("max_recent_iteration_elapsed_seconds"),
    }


BOOK_AUDIT_MAX_GAP_SECONDS = 120.0
BOOK_AUDIT_STARTUP_GRACE_SECONDS = 180.0
BOOK_AUDIT_CYCLE_BUFFER_SECONDS = 60.0
BOOK_AUDIT_RECENT_CYCLE_COUNT = 12


def parse_utc_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def book_capture_times(folder):
    """Distinct book capture timestamps recorded in a folder's summary tape."""
    path = Path(folder) / "order_books_summary.csv"
    if not path.exists():
        return []
    try:
        rows = io_read_csv_rows(path, attach_diagnostics=True)
    except OSError:
        return []
    times = set()
    for row in rows:
        value = row.get("captured_at_utc")
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        times.add(parsed)
    return sorted(times)


def audit_book_tape(
    folder,
    now=None,
    max_gap_seconds=BOOK_AUDIT_MAX_GAP_SECONDS,
    ignore_gaps_before=None,
):
    """Cadence audit for one event folder's book tape.

    `ok` means the tape has captures, no internal gap above the threshold, and
    a fresh trailing capture. Trailing age only matters while the folder is the
    active market day, which is how the fleet audit calls this.
    """
    folder = Path(folder)
    now = now or utc_now()
    ignore_cutoff = parse_utc_datetime(ignore_gaps_before)
    times = book_capture_times(folder)
    result = {
        "folder": str(folder),
        "captures": len(times),
        "first_capture_utc": times[0].isoformat() if times else None,
        "last_capture_utc": times[-1].isoformat() if times else None,
        "median_gap_seconds": None,
        "max_gap_seconds": None,
        "gaps_over_threshold": 0,
        "startup_gaps_ignored": 0,
        "max_startup_gap_seconds": None,
        "max_counted_gap_seconds": None,
        "trailing_age_seconds": None,
        "max_gap_seconds_threshold": float(max_gap_seconds),
        "ignored_gap_cutoff_utc": ignore_cutoff.isoformat() if ignore_cutoff else None,
        "gap_policy": (
            f"ignore gaps ending before {ignore_cutoff.isoformat()}"
            if ignore_cutoff
            else "count all internal gaps"
        ),
        "ok": False,
        "reason": None,
    }
    if not times:
        result["reason"] = "no book captures"
        return result
    gap_rows = [
        {"earlier": earlier, "later": later, "seconds": (later - earlier).total_seconds()}
        for earlier, later in zip(times, times[1:])
    ]
    gaps = [row["seconds"] for row in gap_rows]
    if gaps:
        result["median_gap_seconds"] = round(statistics.median(gaps), 1)
        result["max_gap_seconds"] = round(max(gaps), 1)
        over_threshold = [row for row in gap_rows if row["seconds"] > float(max_gap_seconds)]
        ignored = [
            row
            for row in over_threshold
            if ignore_cutoff and row["later"].astimezone(timezone.utc) <= ignore_cutoff
        ]
        counted = [row for row in over_threshold if row not in ignored]
        result["gaps_over_threshold"] = len(counted)
        result["startup_gaps_ignored"] = len(ignored)
        if ignored:
            result["max_startup_gap_seconds"] = round(max(row["seconds"] for row in ignored), 1)
        if counted:
            result["max_counted_gap_seconds"] = round(max(row["seconds"] for row in counted), 1)
    trailing = max(0.0, (now - times[-1]).total_seconds())
    result["trailing_age_seconds"] = round(trailing, 1)
    if result["gaps_over_threshold"]:
        max_counted = result["max_counted_gap_seconds"] or result["max_gap_seconds"]
        result["reason"] = (
            f"{result['gaps_over_threshold']} gaps over {float(max_gap_seconds):.0f}s "
            f"(max {max_counted}s)"
        )
    elif trailing > float(max_gap_seconds):
        result["reason"] = f"last book capture is {trailing:.0f}s old"
    else:
        result["ok"] = True
        if result["startup_gaps_ignored"]:
            result["reason"] = (
                f"ok; ignored {result['startup_gaps_ignored']} startup gaps over "
                f"{float(max_gap_seconds):.0f}s (max {result['max_startup_gap_seconds']}s)"
            )
    return result


def fleet_effective_book_gap_seconds(max_gap_seconds, loop_status=None):
    """Active fleet tapes are captured serially; use the measured loop cycle.

    The per-market tape cadence can be longer than the nominal sleep interval
    when all 12 markets are captured in one process. A completed loop iteration
    records that elapsed capture time, so the active-day audit can distinguish a
    healthy serial cycle from a genuinely stale book tape.
    """
    threshold = float(max_gap_seconds)
    loop_status = loop_status or {}
    elapsed_values = []
    for key in (
        "last_iteration_elapsed_seconds",
        "max_iteration_elapsed_seconds",
        "max_recent_iteration_elapsed_seconds",
    ):
        value = to_number(loop_status.get(key))
        if value is not None:
            elapsed_values.append(value)
    recent_values = loop_status.get("recent_iteration_elapsed_seconds") or []
    if isinstance(recent_values, (list, tuple)):
        for item in recent_values:
            value = to_number(item)
            if value is not None:
                elapsed_values.append(value)
    if not elapsed_values:
        return threshold
    elapsed = max(elapsed_values)
    sleep_seconds = to_number(loop_status.get("last_sleep_seconds")) or 0.0
    cycle_threshold = elapsed + sleep_seconds + BOOK_AUDIT_CYCLE_BUFFER_SECONDS
    return max(threshold, float(cycle_threshold))


def fleet_book_audit(
    market_id="all",
    snapshots_root=None,
    now=None,
    target_date=None,
    max_gap_seconds=BOOK_AUDIT_MAX_GAP_SECONDS,
    ignore_gaps_before=None,
    startup_grace_seconds=BOOK_AUDIT_STARTUP_GRACE_SECONDS,
):
    """Audit every registered market's active-day book tape cadence."""
    now = now or utc_now()
    root = Path(snapshots_root) if snapshots_root is not None else SNAPSHOT_DATA_ROOT
    ignore_cutoff = parse_utc_datetime(ignore_gaps_before)
    try:
        uses_default_root = root.resolve() == SNAPSHOT_DATA_ROOT.resolve()
    except OSError:
        uses_default_root = snapshots_root is None
    loop_status = read_clob_loop_status() if uses_default_root else None
    max_gap_seconds = fleet_effective_book_gap_seconds(max_gap_seconds, loop_status)
    if ignore_cutoff is None and uses_default_root and startup_grace_seconds is not None:
        started_at = parse_utc_datetime((loop_status or {}).get("started_at"))
        if started_at is not None:
            ignore_cutoff = started_at + timedelta(seconds=float(startup_grace_seconds))
    market_ids = [spec.id for spec in all_specs()] if market_id == "all" else [market_id]
    rows = []
    for item in market_ids:
        spec = spec_for_id(item)
        config = config_for_date(target_date or now.astimezone(spec.tz).date(), item)
        audit = audit_book_tape(
            root / config.event_slug,
            now=now,
            max_gap_seconds=max_gap_seconds,
            ignore_gaps_before=ignore_cutoff,
        )
        rows.append({"market_id": item, "event_slug": config.event_slug, **audit})
    return {
        "generated_at_utc": now.isoformat(),
        "max_gap_seconds_threshold": float(max_gap_seconds),
        "startup_grace_seconds": float(startup_grace_seconds) if startup_grace_seconds is not None else None,
        "ignored_gap_cutoff_utc": ignore_cutoff.isoformat() if ignore_cutoff else None,
        "markets": rows,
        "ok": all(row["ok"] for row in rows) if rows else False,
    }


def _process_query_creationflags():
    return process_query_creationflags()


def python_process_rows():
    if os.name == "nt":
        from weather.operations.windows_processes import python_process_rows as windows_python_process_rows

        return windows_python_process_rows()
    else:
        command = ["ps", "-eo", "pid=,comm=,args="]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=_process_query_creationflags(),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0 or not (result.stdout or "").strip():
        return []
    if os.name == "nt":
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        if isinstance(payload, dict):
            payload = [payload]
        return [
            {
                "pid": row.get("ProcessId"),
                "name": row.get("Name"),
                "command_line": row.get("CommandLine") or "",
            }
            for row in payload
            if isinstance(row, dict)
        ]
    rows = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, name, command_line = parts
        if "python" not in name.lower():
            continue
        rows.append({"pid": pid, "name": name, "command_line": command_line})
    return rows


def clob_loop_command_matches(command_line):
    text = str(command_line or "").lower()
    return "market_microstructure" in text and " loop" in text


def running_clob_loop_processes(process_rows=None, current_pid=None):
    current_pid = int(current_pid or os.getpid())
    rows = process_rows if process_rows is not None else python_process_rows()
    matches = []
    for row in rows or []:
        try:
            pid = int(row.get("pid") if isinstance(row, dict) else row[0])
        except (TypeError, ValueError, IndexError):
            continue
        if pid == current_pid:
            continue
        command_line = row.get("command_line") if isinstance(row, dict) else ""
        if not clob_loop_command_matches(command_line):
            continue
        matches.append({
            "pid": pid,
            "name": row.get("name") if isinstance(row, dict) else None,
            "command_line": command_line,
        })
    return sorted(matches, key=lambda row: row["pid"])


def expected_clob_loop_process_count():
    # On Windows a venv pythonw launch commonly leaves both the venv launcher
    # and the base interpreter visible with the same command line.
    return 2 if os.name == "nt" else 1


def terminate_pid(pid):
    return terminate_python_pid(pid)


def stop_clob_loop_processes(process_rows=None, keep_pids=(), terminate_fn=terminate_pid):
    keep = {int(pid) for pid in keep_pids or [] if pid is not None}
    rows = running_clob_loop_processes(process_rows=process_rows)
    stopped = []
    for row in rows:
        if row["pid"] in keep:
            continue
        result = terminate_fn(row["pid"])
        result["command_line"] = row.get("command_line")
        stopped.append(result)
    return {
        "matched_process_count": len(rows),
        "stopped_count": sum(1 for row in stopped if row.get("stopped")),
        "kept_pids": sorted(keep),
        "stopped": stopped,
    }


def clob_runtime_matches_current(status, current_identity=None):
    if not status or not status.get("runtime_identity"):
        return True
    current_identity = current_identity or current_identity_for(status.get("runtime_identity"))
    return identities_match(status.get("runtime_identity"), current_identity)




def target_close_time(config):
    spec = spec_for_id(config.market_id)
    close_date = config.target_date + timedelta(days=1)
    return datetime.combine(close_date, dt_time.min, tzinfo=spec.tz)


def should_use_fast_interval(
    configs,
    now,
    last_midpoints,
    current_midpoints,
    fast_hours_before_close,
    fast_after_local_hour,
    fast_on_mid_change_bps,
):
    for config in configs:
        spec = spec_for_id(config.market_id)
        local_now = now.astimezone(spec.tz)
        if fast_after_local_hour is not None and local_now.date() == config.target_date:
            if local_now.hour + local_now.minute / 60.0 >= fast_after_local_hour:
                return True
        if fast_hours_before_close is not None:
            hours_to_close = (target_close_time(config) - local_now).total_seconds() / 3600.0
            if 0 <= hours_to_close <= fast_hours_before_close:
                return True
    if fast_on_mid_change_bps is None or not last_midpoints:
        return False
    threshold = float(fast_on_mid_change_bps) / 10_000.0
    for token_id, midpoint in current_midpoints.items():
        previous = last_midpoints.get(token_id)
        if midpoint is None or previous is None:
            continue
        if abs(float(midpoint) - float(previous)) >= threshold:
            return True
    return False


def summarize_loop_results(results):
    summary = {}
    for market_id, value in (results or {}).items():
        if not isinstance(value, dict):
            summary[market_id] = {"error": f"unexpected result type {type(value).__name__}"}
            continue
        summary[market_id] = {
            "event_slug": value.get("event_slug"),
            "target_date": value.get("target_date"),
            "books": value.get("books"),
            "captured_at_utc": value.get("captured_at_utc"),
            "raw_books_captured_at_utc": value.get("raw_books_captured_at_utc"),
            "derived_features_captured_at_utc": value.get("derived_features_captured_at_utc"),
            "include_clob_features": value.get("include_clob_features"),
            "captured_tokens": value.get("captured_tokens"),
            "levels": value.get("levels"),
            "price_history_rows": value.get("price_history_rows"),
            "price_history_new_points": value.get("price_history_new_points"),
            "price_history_duplicate_points": value.get("price_history_duplicate_points"),
            "price_history_corrected_points": value.get("price_history_corrected_points"),
            "price_history_total_points": value.get("price_history_total_points"),
            "price_history_raw_response_hashes": value.get("price_history_raw_response_hashes"),
            "price_history_raw_response_bytes": value.get("price_history_raw_response_bytes"),
            "price_history_raw_response_stored_bytes": value.get("price_history_raw_response_stored_bytes"),
            "price_history_raw_response_reused_count": value.get("price_history_raw_response_reused_count"),
            "ws_messages": value.get("ws_messages"),
            "ws_event_rows": value.get("ws_event_rows"),
            "ws_error": value.get("ws_error"),
            "clob_feature_rows": value.get("clob_feature_rows"),
            "clob_features_error": value.get("clob_features_error"),
            "error": value.get("error"),
        }
    return summary


def latest_iso_timestamp(values):
    parsed = []
    for value in values or []:
        item = parse_utc_datetime(value)
        if item is not None:
            parsed.append(item)
    return max(parsed).isoformat() if parsed else None


def clob_ensure_decision(
    health_state,
    pid_alive,
    has_orphan_processes=False,
    runtime_matches_current=True,
):
    if has_orphan_processes:
        return "restart"
    if not runtime_matches_current and health_state in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING") and pid_alive:
        return "restart"
    if health_state in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING") and pid_alive:
        return "noop"
    if pid_alive:
        return "restart"
    if health_state in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING"):
        return "restart"
    return "start"


def _normalized_pid(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cleanup_clob_writer_lock(expected_pid=None, attempts=1, sleep_seconds=0.1):
    attempts = max(1, int(attempts))
    last_result = None
    for attempt in range(attempts):
        lock = read_writer_lock(CLOB_LOOP_STATUS_PATH)
        if not lock.get("exists"):
            return {"removed": False, "reason": "no writer lock", "path": lock.get("path")}
        owner_pid = _normalized_pid(lock.get("pid"))
        expected = _normalized_pid(expected_pid)
        if expected is not None and owner_pid == expected:
            reason = "stopped writer pid"
        elif owner_pid is not None and not pid_is_python(owner_pid):
            reason = "dead writer pid"
        else:
            return {
                "removed": False,
                "reason": "writer lock owner is still live",
                "pid": owner_pid,
                "path": lock.get("path"),
            }
        try:
            Path(lock["path"]).unlink()
        except FileNotFoundError:
            return {"removed": False, "reason": "writer lock already gone", "pid": owner_pid, "path": lock.get("path")}
        except OSError as exc:
            last_result = {"removed": False, "reason": str(exc), "pid": owner_pid, "path": lock.get("path")}
            if attempt != attempts - 1:
                time.sleep(float(sleep_seconds))
                continue
            return last_result
        return {"removed": True, "reason": reason, "pid": owner_pid, "path": lock.get("path")}
    return last_result or {"removed": False, "reason": "writer lock cleanup exhausted attempts", "path": None}


def stop_clob_loop(now=None):
    now = now or utc_now()
    status = read_clob_loop_status()
    pid = (status or {}).get("pid")
    cleanup = stop_clob_loop_processes()
    pid_alive = pid_is_python(pid)
    lock_cleanup = _cleanup_clob_writer_lock(expected_pid=pid, attempts=20, sleep_seconds=0.1)
    if not cleanup["stopped_count"] and not pid_alive:
        return {
            "stopped": False,
            "reason": f"no live CLOB loop process (pid={pid})",
            "cleanup": cleanup,
            "writer_lock": lock_cleanup,
        }
    if not cleanup["stopped_count"] and pid_alive:
        cleanup["stopped"].append(terminate_pid(pid))
        cleanup["stopped_count"] = sum(1 for row in cleanup["stopped"] if row.get("stopped"))
    if status is not None:
        status["last_stop_requested_at"] = now.isoformat()
        write_clob_loop_status(status)
    append_clob_diagnostic({
        "time": now.isoformat(),
        "supervisor": "stop",
        "pid": pid,
        "cleanup": cleanup,
        "writer_lock": lock_cleanup,
    })
    return {"stopped": bool(cleanup["stopped_count"]), "pid": pid, "cleanup": cleanup, "writer_lock": lock_cleanup}


def _clob_loop_command(
    market_id="all",
    target_date=None,
    interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
    fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
    fast_hours_before_close=4.0,
    fast_after_local_hour=15.0,
    fast_on_mid_change_bps=500.0,
    outcomes="all",
    batch_size=DEFAULT_BATCH_SIZE,
    include_price_history=DEFAULT_LOOP_INCLUDE_PRICE_HISTORY,
    include_ws_events=DEFAULT_LOOP_INCLUDE_WS_EVENTS,
    ws_seconds=DEFAULT_WS_SECONDS,
    ws_message_limit=DEFAULT_WS_MESSAGE_LIMIT,
    ws_heartbeat_seconds=DEFAULT_WS_HEARTBEAT_SECONDS,
    ws_connect_timeout=DEFAULT_WS_CONNECT_TIMEOUT,
):
    command = [
        sys.executable,
        "-m",
        "weather.market.market_microstructure",
        "loop",
        "--market",
        str(market_id),
        "--outcomes",
        str(outcomes),
        "--interval-seconds",
        str(interval_seconds),
        "--fast-interval-seconds",
        str(fast_interval_seconds),
        "--fast-hours-before-close",
        str(fast_hours_before_close),
        "--fast-after-local-hour",
        str(fast_after_local_hour),
        "--fast-on-mid-change-bps",
        str(fast_on_mid_change_bps),
        "--batch-size",
        str(batch_size),
    ]
    if target_date:
        command.extend(["--date", str(target_date)])
    if not include_price_history:
        command.append("--no-price-history")
    if not include_ws_events:
        command.append("--no-websocket-events")
    command.extend([
        "--websocket-seconds",
        str(ws_seconds),
        "--websocket-message-limit",
        str(ws_message_limit),
        "--websocket-heartbeat-seconds",
        str(ws_heartbeat_seconds),
        "--websocket-connect-timeout",
        str(ws_connect_timeout),
    ])
    return command


def start_clob_loop_detached(
    market_id="all",
    target_date=None,
    interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
    fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
    fast_hours_before_close=4.0,
    fast_after_local_hour=15.0,
    fast_on_mid_change_bps=500.0,
    outcomes="all",
    batch_size=DEFAULT_BATCH_SIZE,
    include_price_history=DEFAULT_LOOP_INCLUDE_PRICE_HISTORY,
    include_ws_events=DEFAULT_LOOP_INCLUDE_WS_EVENTS,
    ws_seconds=DEFAULT_WS_SECONDS,
    ws_message_limit=DEFAULT_WS_MESSAGE_LIMIT,
    ws_heartbeat_seconds=DEFAULT_WS_HEARTBEAT_SECONDS,
    ws_connect_timeout=DEFAULT_WS_CONNECT_TIMEOUT,
    now=None,
):
    now = now or utc_now()
    lock_cleanup = _cleanup_clob_writer_lock(attempts=3, sleep_seconds=0.1)
    if lock_cleanup.get("reason") == "writer lock owner is still live":
        append_clob_diagnostic({
            "time": now.isoformat(),
            "supervisor": "start_blocked",
            "reason": "writer lock owner is still live",
            "writer_lock": lock_cleanup,
        })
        return {"started": False, "reason": "writer lock owner is still live", "writer_lock": lock_cleanup}
    child = launch_detached(
        _clob_loop_command(
            market_id=market_id,
            target_date=target_date,
            interval_seconds=interval_seconds,
            fast_interval_seconds=fast_interval_seconds,
            fast_hours_before_close=fast_hours_before_close,
            fast_after_local_hour=fast_after_local_hour,
            fast_on_mid_change_bps=fast_on_mid_change_bps,
            outcomes=outcomes,
            batch_size=batch_size,
            include_price_history=include_price_history,
            include_ws_events=include_ws_events,
            ws_seconds=ws_seconds,
            ws_message_limit=ws_message_limit,
            ws_heartbeat_seconds=ws_heartbeat_seconds,
            ws_connect_timeout=ws_connect_timeout,
        ),
        cwd=CLOB_SUPERVISOR.cwd,
        console_log_path=CLOB_LOOP_CONSOLE_LOG_PATH,
        popen_fn=subprocess.Popen,
    )
    write_clob_loop_status({
        "pid": child.pid,
        "started_at": now.isoformat(),
        "last_heartbeat": now.isoformat(),
        "runtime_identity": get_runtime_identity(scope_files="loaded"),
        "market_id": market_id,
        "target_date": target_date,
        "date_selection": "fixed_target_date" if target_date else "market_local_date",
        "outcomes": outcomes,
        "interval_seconds": interval_seconds,
        "fast_interval_seconds": fast_interval_seconds,
        "fast_hours_before_close": fast_hours_before_close,
        "fast_after_local_hour": fast_after_local_hour,
        "fast_on_mid_change_bps": fast_on_mid_change_bps,
        "batch_size": batch_size,
        "include_price_history": include_price_history,
        "include_ws_events": include_ws_events,
        "websocket_seconds": ws_seconds,
        "websocket_message_limit": ws_message_limit,
        "websocket_heartbeat_seconds": ws_heartbeat_seconds,
        "websocket_connect_timeout": ws_connect_timeout,
        "iterations": 0,
        "raw_book_useful_iterations": 0,
        "consecutive_errors": 0,
        "error_markets": [],
        "last_error": None,
        "paused": CLOB_PAUSE_FLAG_PATH.exists(),
        "started_by": "supervisor",
    })
    append_clob_diagnostic({
        "time": now.isoformat(),
        "supervisor": "start",
        "pid": child.pid,
        "market_id": market_id,
        "interval_seconds": interval_seconds,
        "writer_lock": lock_cleanup,
    })
    return {"started": True, "pid": child.pid, "writer_lock": lock_cleanup}


def ensure_clob_loop(
    market_id="all",
    target_date=None,
    interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
    fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
    fast_hours_before_close=4.0,
    fast_after_local_hour=15.0,
    fast_on_mid_change_bps=500.0,
    outcomes="all",
    batch_size=DEFAULT_BATCH_SIZE,
    include_price_history=DEFAULT_LOOP_INCLUDE_PRICE_HISTORY,
    include_ws_events=DEFAULT_LOOP_INCLUDE_WS_EVENTS,
    ws_seconds=DEFAULT_WS_SECONDS,
    ws_message_limit=DEFAULT_WS_MESSAGE_LIMIT,
    ws_heartbeat_seconds=DEFAULT_WS_HEARTBEAT_SECONDS,
    ws_connect_timeout=DEFAULT_WS_CONNECT_TIMEOUT,
    now=None,
):
    now = now or utc_now()
    spec = runtime_clob_supervisor_spec()
    lock_handle = acquire_clob_supervisor_lock()
    if lock_handle is None:
        return {"action": "locked", "state": "UNKNOWN", "reason": "another CLOB supervisor action is running"}
    try:
        status = read_clob_loop_status()
        preserved_target_date_from_status = False
        if target_date is None and (status or {}).get("target_date"):
            target_date = status.get("target_date")
            preserved_target_date_from_status = True
        health = clob_loop_health(status, now=now, interval_seconds=interval_seconds)
        alive = pid_is_python((status or {}).get("pid"))
        loop_processes = running_clob_loop_processes()
        has_orphans = len(loop_processes) > expected_clob_loop_process_count()
        runtime_matches_current = clob_runtime_matches_current(status)
        action = clob_ensure_decision(
            health["state"],
            alive,
            has_orphan_processes=has_orphans,
            runtime_matches_current=runtime_matches_current,
        )
        result = {
            "action": action,
            "state": health["state"],
            "pid": health.get("pid"),
            "restart_cause": (
                "orphan_processes"
                if has_orphans
                else "runtime_identity"
                if not runtime_matches_current
                else health["state"]
                if action in {"start", "restart"}
                else None
            ),
            "running_process_count": len(loop_processes),
            "running_pids": [row["pid"] for row in loop_processes],
            "orphan_processes_detected": has_orphans,
            "runtime_identity_matches_current": runtime_matches_current,
            "runtime_identity_before": (status or {}).get("runtime_identity"),
            "preserved_target_date_from_status": preserved_target_date_from_status,
        }
        guard = supervisor_recovery_guard(spec, action, now=now)
        result["recovery_guard"] = guard
        if action in {"start", "restart"}:
            result["loop_offsets_before"] = loop_file_offsets(spec)
        if action in {"start", "restart"} and not guard.get("allowed"):
            result["intended_action"] = action
            result["action"] = guard.get("action")
            result["reason"] = guard.get("reason")
            result["remediation"] = guard.get("remediation")
            event = {"time": now.isoformat(), "supervisor": "ensure", **result}
            if should_emit_recovery_block_diagnostic(spec, event):
                append_clob_diagnostic(event)
            else:
                result["diagnostic_suppressed"] = True
            return result
        if action == "restart":
            result["stop"] = stop_clob_loop(now=now)
            result["malformed_loop_line_quarantine"] = quarantine_malformed_loop_lines(spec)
            result["start"] = start_clob_loop_detached(
                market_id=market_id,
                target_date=target_date,
                interval_seconds=interval_seconds,
                fast_interval_seconds=fast_interval_seconds,
                fast_hours_before_close=fast_hours_before_close,
                fast_after_local_hour=fast_after_local_hour,
                fast_on_mid_change_bps=fast_on_mid_change_bps,
                outcomes=outcomes,
                batch_size=batch_size,
                include_price_history=include_price_history,
                include_ws_events=include_ws_events,
                ws_seconds=ws_seconds,
                ws_message_limit=ws_message_limit,
                ws_heartbeat_seconds=ws_heartbeat_seconds,
                ws_connect_timeout=ws_connect_timeout,
                now=now,
            )
        elif action == "start":
            result["malformed_loop_line_quarantine"] = quarantine_malformed_loop_lines(spec)
            result["start"] = start_clob_loop_detached(
                market_id=market_id,
                target_date=target_date,
                interval_seconds=interval_seconds,
                fast_interval_seconds=fast_interval_seconds,
                fast_hours_before_close=fast_hours_before_close,
                fast_after_local_hour=fast_after_local_hour,
                fast_on_mid_change_bps=fast_on_mid_change_bps,
                outcomes=outcomes,
                batch_size=batch_size,
                include_price_history=include_price_history,
                include_ws_events=include_ws_events,
                ws_seconds=ws_seconds,
                ws_message_limit=ws_message_limit,
                ws_heartbeat_seconds=ws_heartbeat_seconds,
                ws_connect_timeout=ws_connect_timeout,
                now=now,
            )
        if action != "noop":
            result["loop_offsets_after"] = loop_file_offsets(spec)
            append_clob_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
        return result
    finally:
        release_clob_supervisor_lock(lock_handle)


def run_book_loop(
    market_id="all",
    target_date=None,
    interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
    fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
    fast_hours_before_close=4.0,
    fast_after_local_hour=15.0,
    fast_on_mid_change_bps=500.0,
    outcomes="all",
    batch_size=DEFAULT_BATCH_SIZE,
    include_price_history=DEFAULT_LOOP_INCLUDE_PRICE_HISTORY,
    include_ws_events=DEFAULT_LOOP_INCLUDE_WS_EVENTS,
    ws_seconds=DEFAULT_WS_SECONDS,
    ws_message_limit=DEFAULT_WS_MESSAGE_LIMIT,
    ws_heartbeat_seconds=DEFAULT_WS_HEARTBEAT_SECONDS,
    ws_connect_timeout=DEFAULT_WS_CONNECT_TIMEOUT,
    max_iterations=None,
    capture_fn=None,
    sleep_fn=time.sleep,
    now_fn=utc_now,
):
    capture_fn = capture_fn or capture_fleet_books
    writer_lock = acquire_writer_lock(
        CLOB_LOOP_STATUS_PATH,
        owner={"loop": CLOB_SUPERVISOR.name, "module": CLOB_SUPERVISOR.module},
        stale_after_seconds=max(120.0, float(interval_seconds) * 3.0),
    )
    if writer_lock is None:
        existing = read_writer_lock(CLOB_LOOP_STATUS_PATH)
        append_clob_diagnostic({
            "time": now_fn().isoformat(),
            "status": "duplicate_writer_blocked",
            "existing_writer": existing,
            "pid": os.getpid(),
        })
        return {"status": "duplicate_writer_blocked", "existing_writer": existing, "pid": os.getpid()}
    sleep_inhibitor = keep_system_awake("weather CLOB book capture loop")
    power_request = sleep_inhibitor.start()
    last_midpoints = {}
    status = {
        "pid": os.getpid(),
        "started_at": now_fn().isoformat(),
        "runtime_identity": get_runtime_identity(scope_files="loaded"),
        "power_request": power_request,
        "market_id": market_id,
        "target_date": target_date,
        "date_selection": "fixed_target_date" if target_date else "market_local_date",
        "outcomes": outcomes,
        "interval_seconds": interval_seconds,
        "fast_interval_seconds": fast_interval_seconds,
        "fast_hours_before_close": fast_hours_before_close,
        "fast_after_local_hour": fast_after_local_hour,
        "fast_on_mid_change_bps": fast_on_mid_change_bps,
        "batch_size": batch_size,
        "include_price_history": include_price_history,
        "include_ws_events": include_ws_events,
        "websocket_seconds": ws_seconds,
        "websocket_message_limit": ws_message_limit,
        "websocket_heartbeat_seconds": ws_heartbeat_seconds,
        "websocket_connect_timeout": ws_connect_timeout,
        "iterations": 0,
        "consecutive_errors": 0,
        "error_markets": [],
        "last_error": None,
        "paused": False,
    }
    attach_status_writer(status, writer_lock)
    try:
        while True:
            loop_started = now_fn()
            status["iterations"] += 1
            status["last_heartbeat"] = loop_started.isoformat()
            status["paused"] = CLOB_PAUSE_FLAG_PATH.exists()
            market_ids = [spec.id for spec in all_specs()] if market_id == "all" else [market_id]
            configs = [
                config_for_date(target_date or loop_started.astimezone(spec_for_id(item).tz).date(), item)
                for item in market_ids
            ]
            if status["paused"]:
                sleep_seconds = interval_seconds
                status["last_mode"] = "paused"
                status["last_sleep_seconds"] = sleep_seconds
                write_clob_loop_status(status)
                append_clob_diagnostic({"time": loop_started.isoformat(), "status": "paused"})
                print(json.dumps({"status": "paused", "time": loop_started.isoformat()}), flush=True)
            else:
                try:
                    def progress_callback(item, result):
                        progress_now = now_fn()
                        status["last_heartbeat"] = progress_now.isoformat()
                        status["last_market_in_progress"] = item
                        if isinstance(result, dict) and (result.get("books") or 0) > 0:
                            status["last_books_captured_at"] = progress_now.isoformat()
                        write_clob_loop_status(status)

                    results = capture_fn(
                        market_id=market_id,
                        outcomes=outcomes,
                        include_price_history=include_price_history,
                        include_ws_events=include_ws_events,
                        ws_seconds=ws_seconds,
                        ws_message_limit=ws_message_limit,
                        ws_heartbeat_seconds=ws_heartbeat_seconds,
                        ws_connect_timeout=ws_connect_timeout,
                        batch_size=batch_size,
                        target_date=target_date,
                        progress_callback=progress_callback,
                    )
                    current_midpoints = {}
                    for result in results.values():
                        if isinstance(result, dict):
                            current_midpoints.update(result.get("midpoint_by_token") or {})
                    fast = should_use_fast_interval(
                        configs,
                        loop_started,
                        last_midpoints,
                        current_midpoints,
                        fast_hours_before_close,
                        fast_after_local_hour,
                        fast_on_mid_change_bps,
                    )
                    sleep_seconds = fast_interval_seconds if fast else interval_seconds
                    summary = summarize_loop_results(results)
                    errors = {
                        item: value.get("error")
                        for item, value in summary.items()
                        if value.get("error")
                    }
                    elapsed_seconds = (now_fn() - loop_started).total_seconds()
                    full_error = bool(summary) and len(errors) == len(summary)
                    status["consecutive_errors"] = status["consecutive_errors"] + 1 if full_error else 0
                    status["error_markets"] = sorted(errors)
                    status["last_error"] = "; ".join(f"{item}: {err}" for item, err in errors.items()) or None
                    status["last_market_results"] = summary
                    status["last_market_in_progress"] = None
                    raw_by_market = {
                        item: (
                            value.get("raw_books_captured_at_utc")
                            or (value.get("captured_at_utc") if (value.get("books") or 0) > 0 else None)
                        )
                        for item, value in summary.items()
                        if isinstance(value, dict)
                        and (
                            value.get("raw_books_captured_at_utc")
                            or ((value.get("books") or 0) > 0 and value.get("captured_at_utc"))
                        )
                    }
                    derived_by_market = {
                        item: value.get("derived_features_captured_at_utc")
                        for item, value in summary.items()
                        if isinstance(value, dict) and value.get("derived_features_captured_at_utc")
                    }
                    derived_errors = sorted(
                        item
                        for item, value in summary.items()
                        if isinstance(value, dict) and value.get("clob_features_error")
                    )
                    if raw_by_market:
                        status["last_raw_books_by_market"] = raw_by_market
                        status["last_raw_books_captured_at"] = latest_iso_timestamp(raw_by_market.values())
                        status["raw_book_useful_iterations"] = int(status.get("raw_book_useful_iterations") or 0) + 1
                    if derived_by_market:
                        status["last_derived_features_by_market"] = derived_by_market
                        status["last_derived_features_captured_at"] = latest_iso_timestamp(derived_by_market.values())
                    status["derived_feature_error_markets"] = derived_errors
                    status["last_mode"] = "fast" if fast else "baseline"
                    status["last_sleep_seconds"] = sleep_seconds
                    elapsed_rounded = round(elapsed_seconds, 1)
                    recent_elapsed = []
                    for value in status.get("recent_iteration_elapsed_seconds") or []:
                        numeric = to_number(value)
                        if numeric is not None:
                            recent_elapsed.append(float(numeric))
                    recent_elapsed.append(elapsed_rounded)
                    recent_elapsed = recent_elapsed[-BOOK_AUDIT_RECENT_CYCLE_COUNT:]
                    status["last_iteration_elapsed_seconds"] = elapsed_rounded
                    status["recent_iteration_elapsed_seconds"] = recent_elapsed
                    prior_max_elapsed = to_number(status.get("max_iteration_elapsed_seconds"))
                    if prior_max_elapsed is None:
                        prior_max_elapsed = 0.0
                    status["max_iteration_elapsed_seconds"] = round(
                        max(float(prior_max_elapsed), elapsed_rounded),
                        1,
                    )
                    status["max_recent_iteration_elapsed_seconds"] = round(max(recent_elapsed), 1)
                    if any((value.get("books") or 0) > 0 for value in summary.values()):
                        status["last_books_captured_at"] = loop_started.isoformat()
                    write_clob_loop_status(status)
                    append_clob_diagnostic({
                        "time": loop_started.isoformat(),
                        "mode": status["last_mode"],
                        "sleep_seconds": sleep_seconds,
                        "markets": summary,
                    })
                    print(json.dumps({
                        "time": loop_started.isoformat(),
                        "mode": status["last_mode"],
                        "sleep_seconds": sleep_seconds,
                        "results": summary,
                    }, sort_keys=True), flush=True)
                    last_midpoints = current_midpoints
                except Exception as exc:  # noqa: BLE001 - keep the collector alive
                    status["consecutive_errors"] += 1
                    status["error_markets"] = list(market_ids)
                    status["last_error"] = f"{type(exc).__name__}: {exc}"
                    status["last_mode"] = "error"
                    sleep_seconds = interval_seconds
                    status["last_sleep_seconds"] = sleep_seconds
                    write_clob_loop_status(status)
                    append_clob_diagnostic({
                        "time": loop_started.isoformat(),
                        "status": "error",
                        "error": status["last_error"],
                    })
                    print(json.dumps({
                        "time": loop_started.isoformat(),
                        "status": "error",
                        "error": status["last_error"],
                    }, sort_keys=True), flush=True)
            if max_iterations is not None and status["iterations"] >= max_iterations:
                return status
            elapsed = (now_fn() - loop_started).total_seconds()
            sleep_fn(max(1.0, sleep_seconds - elapsed))
    finally:
        sleep_inhibitor.stop()
        release_writer_lock(writer_lock)




def _market_choices():
    return ["all"] + [spec.id for spec in all_specs()]


def add_loop_options(parser):
    parser.add_argument("--market", choices=_market_choices(), default="all")
    parser.add_argument("--date", default=None, help="Fixed target event date YYYY-MM-DD. Defaults to each market's local date.")
    parser.add_argument("--outcomes", default="all")
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_BOOK_INTERVAL_SECONDS)
    parser.add_argument("--fast-interval-seconds", type=float, default=DEFAULT_FAST_INTERVAL_SECONDS)
    parser.add_argument("--fast-hours-before-close", type=float, default=4.0)
    parser.add_argument("--fast-after-local-hour", type=float, default=15.0)
    parser.add_argument("--fast-on-mid-change-bps", type=float, default=500.0)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    add_capture_enrichment_options(
        parser,
        default_price_history=DEFAULT_LOOP_INCLUDE_PRICE_HISTORY,
        default_websocket_events=DEFAULT_LOOP_INCLUDE_WS_EVENTS,
    )


def add_capture_enrichment_options(
    parser,
    default_price_history=DEFAULT_INCLUDE_PRICE_HISTORY,
    default_websocket_events=DEFAULT_INCLUDE_WS_EVENTS,
    default_clob_features=True,
):
    parser.set_defaults(
        price_history=default_price_history,
        websocket_events=default_websocket_events,
        clob_features=default_clob_features,
    )
    parser.add_argument("--price-history", dest="price_history", action="store_true",
                        help="Capture /prices-history for each token (default).")
    parser.add_argument("--no-price-history", dest="price_history", action="store_false",
                        help="Disable /prices-history capture for this run.")
    parser.add_argument("--websocket-events", dest="websocket_events", action="store_true",
                        help="Record public CLOB market WebSocket events (default).")
    parser.add_argument("--no-websocket-events", dest="websocket_events", action="store_false",
                        help="Disable market WebSocket event capture for this run.")
    parser.add_argument("--clob-features", dest="clob_features", action="store_true",
                        help="Refresh derived clob_features_long.csv after raw CLOB capture (default).")
    parser.add_argument("--no-clob-features", dest="clob_features", action="store_false",
                        help="Skip derived CLOB feature refresh; useful for fast raw book freshness repairs.")
    parser.add_argument("--websocket-seconds", type=float, default=DEFAULT_WS_SECONDS)
    parser.add_argument("--websocket-message-limit", type=int, default=DEFAULT_WS_MESSAGE_LIMIT)
    parser.add_argument("--websocket-heartbeat-seconds", type=float, default=DEFAULT_WS_HEARTBEAT_SECONDS)
    parser.add_argument("--websocket-connect-timeout", type=float, default=DEFAULT_WS_CONNECT_TIMEOUT)


def main():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Capture Polymarket CLOB books, price history, and market WebSocket events."
    )
    subparsers = parser.add_subparsers(dest="command")

    capture = subparsers.add_parser("capture", help="Capture one REST book batch.")
    capture.add_argument("--market", choices=_market_choices(), default="all")
    capture.add_argument("--outcomes", default="all", help="'all', 'yes', 'no', or comma-separated outcomes.")
    capture.add_argument("--history-minutes", type=int, default=240)
    capture.add_argument("--history-interval", default=None)
    capture.add_argument("--fidelity-minutes", type=int, default=1)
    capture.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    capture.add_argument("--date", default=None, help="Target event date YYYY-MM-DD. Defaults to each market's local date.")
    add_capture_enrichment_options(capture)

    raw_refresh = subparsers.add_parser(
        "raw-refresh",
        help="Refresh raw CLOB books across markets in parallel without derived feature work.",
    )
    raw_refresh.add_argument("--market", choices=_market_choices(), default="all")
    raw_refresh.add_argument("--outcomes", default="all", help="'all', 'yes', 'no', or comma-separated outcomes.")
    raw_refresh.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    raw_refresh.add_argument("--date", default=None, help="Target event date YYYY-MM-DD. Defaults to each market's local date.")
    raw_refresh.add_argument("--max-workers", type=int, default=None)
    raw_refresh.add_argument("--per-market-timeout-seconds", type=float, default=30.0)
    raw_refresh.add_argument("--freshness-sla-seconds", type=float, default=120.0)
    raw_refresh.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when any market fails, times out, or exceeds the raw-refresh SLA.",
    )

    loop = subparsers.add_parser("loop", help="Run a fast CLOB book capture loop.")
    add_loop_options(loop)

    status = subparsers.add_parser("status", help="Print the managed CLOB loop health and exit.")
    status.add_argument("--interval-seconds", type=float, default=DEFAULT_BOOK_INTERVAL_SECONDS)

    stop = subparsers.add_parser("stop", help="Terminate the managed CLOB loop process.")
    stop.set_defaults(_stop=True)

    start = subparsers.add_parser("start-detached", help="Start the CLOB loop as a detached process.")
    add_loop_options(start)

    restart = subparsers.add_parser("restart", help="Stop the managed CLOB loop and start a fresh detached one.")
    add_loop_options(restart)

    ensure = subparsers.add_parser(
        "ensure",
        help="Supervisor check: start/restart the CLOB loop only if it is dead or hung.",
    )
    add_loop_options(ensure)

    audit = subparsers.add_parser(
        "audit",
        help="Audit the active market day's book-tape cadence per market.",
    )
    audit.add_argument("--market", choices=_market_choices(), default="all")
    audit.add_argument("--max-gap-seconds", type=float, default=BOOK_AUDIT_MAX_GAP_SECONDS)
    audit.add_argument("--date", default=None, help="Target event date YYYY-MM-DD. Defaults to each market's local date.")
    audit.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when any market has a gap over the threshold or a stale/missing tape.",
    )

    repair_history = subparsers.add_parser(
        "repair-price-history",
        help="Deduplicate a snapshot folder's CLOB price-history point table.",
    )
    repair_history.add_argument("--folder", required=True, help="Snapshot event folder containing price_history.csv.")
    repair_history.add_argument(
        "--out",
        default="",
        help="Output CSV path. Defaults to price_history_deduped.csv, or price_history.csv with --apply.",
    )
    repair_history.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite price_history.csv in place instead of writing a sidecar deduped table.",
    )

    ws = subparsers.add_parser("websocket", help="Record the public CLOB market WebSocket.")
    ws.add_argument("--market", choices=[spec.id for spec in all_specs()], default="toronto")
    ws.add_argument("--outcomes", default="all")
    ws.add_argument("--seconds", type=int, default=300)
    ws.add_argument("--message-limit", type=int, default=None)
    ws.add_argument("--heartbeat-seconds", type=int, default=10)
    ws.add_argument("--connect-timeout", type=float, default=30)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    command = args.command
    if command == "capture":
        result = capture_fleet_books(
            market_id=args.market,
            outcomes=args.outcomes,
            target_date=args.date,
            include_price_history=args.price_history,
            history_minutes=args.history_minutes,
            history_interval=args.history_interval,
            fidelity_minutes=args.fidelity_minutes,
            include_ws_events=args.websocket_events,
            ws_seconds=args.websocket_seconds,
            ws_message_limit=args.websocket_message_limit,
            ws_heartbeat_seconds=args.websocket_heartbeat_seconds,
            ws_connect_timeout=args.websocket_connect_timeout,
            batch_size=args.batch_size,
            include_clob_features=args.clob_features,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    if command == "raw-refresh":
        result = capture_fleet_books_parallel(
            market_id=args.market,
            outcomes=args.outcomes,
            target_date=args.date,
            batch_size=args.batch_size,
            max_workers=args.max_workers,
            per_market_timeout_seconds=args.per_market_timeout_seconds,
            freshness_sla_seconds=args.freshness_sla_seconds,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        if args.strict and (
            not result.get("ok")
            or (result.get("summary") or {}).get("slow_market_count")
        ):
            sys.exit(2)
        return
    if command == "loop":
        configure_json_console_logging()
        run_book_loop(
            market_id=args.market,
            target_date=args.date,
            interval_seconds=args.interval_seconds,
            fast_interval_seconds=args.fast_interval_seconds,
            fast_hours_before_close=args.fast_hours_before_close,
            fast_after_local_hour=args.fast_after_local_hour,
            fast_on_mid_change_bps=args.fast_on_mid_change_bps,
            outcomes=args.outcomes,
            batch_size=args.batch_size,
            include_price_history=args.price_history,
            include_ws_events=args.websocket_events,
            ws_seconds=args.websocket_seconds,
            ws_message_limit=args.websocket_message_limit,
            ws_heartbeat_seconds=args.websocket_heartbeat_seconds,
            ws_connect_timeout=args.websocket_connect_timeout,
        )
        return
    if command == "status":
        health = clob_loop_health(
            read_clob_loop_status(),
            now=utc_now(),
            interval_seconds=args.interval_seconds,
        )
        print(json.dumps(health, indent=2, sort_keys=True, default=str))
        return
    if command == "audit":
        result = fleet_book_audit(
            market_id=args.market,
            max_gap_seconds=args.max_gap_seconds,
            target_date=args.date,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        if args.strict and not result["ok"]:
            sys.exit(2)
        return
    if command == "repair-price-history":
        result = repair_price_history_store(
            args.folder,
            output_path=args.out or None,
            apply=args.apply,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        if result.get("validation", {}).get("status") != "PASS":
            sys.exit(2)
        return
    if command == "stop":
        print(json.dumps(stop_clob_loop(), indent=2, sort_keys=True, default=str))
        return
    if command == "start-detached":
        lock_handle = acquire_clob_supervisor_lock()
        if lock_handle is None:
            print(json.dumps({"started": False, "reason": "another CLOB supervisor action is running"}, indent=2))
            return
        try:
            health = clob_loop_health(
                read_clob_loop_status(),
                now=utc_now(),
                interval_seconds=args.interval_seconds,
            )
            if health["state"] in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING") and pid_is_python(health.get("pid")):
                print(json.dumps({"started": False, "reason": f"CLOB loop already {health['state']}"}, indent=2))
                return
            print(json.dumps(start_clob_loop_detached(
                market_id=args.market,
                target_date=args.date,
                interval_seconds=args.interval_seconds,
                fast_interval_seconds=args.fast_interval_seconds,
                fast_hours_before_close=args.fast_hours_before_close,
                fast_after_local_hour=args.fast_after_local_hour,
                fast_on_mid_change_bps=args.fast_on_mid_change_bps,
                outcomes=args.outcomes,
                batch_size=args.batch_size,
                include_price_history=args.price_history,
                include_ws_events=args.websocket_events,
                ws_seconds=args.websocket_seconds,
                ws_message_limit=args.websocket_message_limit,
                ws_heartbeat_seconds=args.websocket_heartbeat_seconds,
                ws_connect_timeout=args.websocket_connect_timeout,
            ), indent=2, sort_keys=True, default=str))
        finally:
            release_clob_supervisor_lock(lock_handle)
        return
    if command == "restart":
        lock_handle = acquire_clob_supervisor_lock()
        if lock_handle is None:
            print(json.dumps({"restarted": False, "reason": "another CLOB supervisor action is running"}, indent=2))
            return
        try:
            result = {
                "stop": stop_clob_loop(),
                "start": start_clob_loop_detached(
                    market_id=args.market,
                    target_date=args.date,
                    interval_seconds=args.interval_seconds,
                    fast_interval_seconds=args.fast_interval_seconds,
                    fast_hours_before_close=args.fast_hours_before_close,
                    fast_after_local_hour=args.fast_after_local_hour,
                    fast_on_mid_change_bps=args.fast_on_mid_change_bps,
                    outcomes=args.outcomes,
                    batch_size=args.batch_size,
                    include_price_history=args.price_history,
                    include_ws_events=args.websocket_events,
                    ws_seconds=args.websocket_seconds,
                    ws_message_limit=args.websocket_message_limit,
                    ws_heartbeat_seconds=args.websocket_heartbeat_seconds,
                    ws_connect_timeout=args.websocket_connect_timeout,
                ),
            }
            print(json.dumps(result, indent=2, sort_keys=True, default=str))
        finally:
            release_clob_supervisor_lock(lock_handle)
        return
    if command == "ensure":
        print(json.dumps(ensure_clob_loop(
            market_id=args.market,
            target_date=args.date,
            interval_seconds=args.interval_seconds,
            fast_interval_seconds=args.fast_interval_seconds,
            fast_hours_before_close=args.fast_hours_before_close,
            fast_after_local_hour=args.fast_after_local_hour,
            fast_on_mid_change_bps=args.fast_on_mid_change_bps,
            outcomes=args.outcomes,
            batch_size=args.batch_size,
            include_price_history=args.price_history,
            include_ws_events=args.websocket_events,
            ws_seconds=args.websocket_seconds,
            ws_message_limit=args.websocket_message_limit,
            ws_heartbeat_seconds=args.websocket_heartbeat_seconds,
            ws_connect_timeout=args.websocket_connect_timeout,
        ), indent=2, sort_keys=True, default=str))
        return
    if command == "websocket":
        event = PolymarketClient(market_id=args.market).get_event()
        result = record_market_websocket(
            event,
            market_id=args.market,
            outcomes=args.outcomes,
            seconds=args.seconds,
            message_limit=args.message_limit,
            heartbeat_seconds=args.heartbeat_seconds,
            connect_timeout=args.connect_timeout,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return


if __name__ == "__main__":
    main()
