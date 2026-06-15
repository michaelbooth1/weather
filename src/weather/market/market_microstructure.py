import argparse
import csv
import hashlib
import json
import os
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

import requests

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_config import config_from_event, config_for_date  # noqa: E402
from market_microstructure_features import write_clob_feature_rows  # noqa: E402
from market_registry import all_specs, spec_for_id  # noqa: E402
from model_sources import request_with_retries  # noqa: E402
from polymarket_client import PolymarketClient  # noqa: E402
from runtime_identity import get_runtime_identity  # noqa: E402
from weather.paths import REPO_ROOT  # noqa: E402



try:
    from .market_microstructure_constants import (  # noqa: E402
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
    from .market_microstructure_capture import (  # noqa: E402
        ClobClient,
        MarketMicrostructureStore,
        capture_event_books,
        capture_fleet_books,
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
        record_market_websocket,
        status_value,
        summarize_order_book,
        timestamp_to_iso,
        to_number,
        token_rows_from_event,
        token_sort_key,
        vwap_for_size,
        ws_summary_rows,
    )
except ImportError:  # pragma: no cover - direct src compatibility
    from market_microstructure_constants import (  # noqa: E402
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
    from market_microstructure_capture import (  # noqa: E402
        ClobClient,
        MarketMicrostructureStore,
        capture_event_books,
        capture_fleet_books,
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
        record_market_websocket,
        status_value,
        summarize_order_book,
        timestamp_to_iso,
        to_number,
        token_rows_from_event,
        token_sort_key,
        vwap_for_size,
        ws_summary_rows,
    )


def utc_now():
    return datetime.now(timezone.utc)


def read_clob_loop_status(path=None):
    path = Path(path or CLOB_LOOP_STATUS_PATH)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def write_clob_loop_status(status, path=None):
    path = Path(path or CLOB_LOOP_STATUS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2, sort_keys=True, default=str)
    tmp.replace(path)


def append_clob_diagnostic(record, path=None):
    path = Path(path or CLOB_DIAGNOSTICS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def clob_supervisor_lock_is_stale(path=None, max_age_seconds=120):
    path = Path(path or CLOB_SUPERVISOR_LOCK_PATH)
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age > max_age_seconds


def acquire_clob_supervisor_lock(path=None, attempts=30, sleep_fn=time.sleep):
    path = Path(path or CLOB_SUPERVISOR_LOCK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(attempts):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, str(os.getpid()).encode("ascii"))
            return handle
        except FileExistsError:
            if clob_supervisor_lock_is_stale(path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            sleep_fn(0.1)
    return None


def release_clob_supervisor_lock(handle, path=None):
    os.close(handle)
    try:
        Path(path or CLOB_SUPERVISOR_LOCK_PATH).unlink()
    except FileNotFoundError:
        pass


def _age_seconds(now, iso_value):
    if not iso_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(iso_value))
    except ValueError:
        return None
    if parsed.tzinfo is None and now.tzinfo is not None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed).total_seconds()


def clob_loop_health(status, now=None, interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS):
    """Heartbeat-based liveness for the fast market-book loop."""
    now = now or utc_now()
    if not status:
        return {"state": "UNKNOWN", "detail": "no CLOB loop status file"}
    interval = to_number(status.get("interval_seconds")) or float(interval_seconds)
    heartbeat_age = _age_seconds(now, status.get("last_heartbeat"))
    capture_age = _age_seconds(now, status.get("last_books_captured_at"))
    errors = int(status.get("consecutive_errors") or 0)
    error_markets = status.get("error_markets") or []
    dead_after = max(2 * interval + 30.0, 90.0)
    if status.get("paused"):
        state = "PAUSED"
    elif heartbeat_age is None or heartbeat_age > dead_after:
        state = "DEAD"
    elif errors >= 3:
        state = "ERRORING"
    elif error_markets:
        state = "DEGRADED"
    else:
        state = "RUNNING"
    return {
        "state": state,
        "pid": status.get("pid"),
        "heartbeat_age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        "last_books_age_seconds": round(capture_age, 1) if capture_age is not None else None,
        "consecutive_errors": errors,
        "error_markets": error_markets,
        "last_error": status.get("last_error"),
        "started_at": status.get("started_at"),
        "market_id": status.get("market_id"),
        "interval_seconds": interval,
        "fast_interval_seconds": status.get("fast_interval_seconds"),
        "last_mode": status.get("last_mode"),
        "last_sleep_seconds": status.get("last_sleep_seconds"),
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
    times = set()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
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
    except (OSError, csv.Error):
        return []
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
        config = config_for_date(now.astimezone(spec.tz).date(), item)
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


def pid_is_python(pid):
    """True when pid exists and belongs to a Python process."""
    if not pid:
        return False
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
        ).stdout
        return "python" in out.lower()
    except (OSError, ValueError, subprocess.SubprocessError):
        return False




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
            "books": value.get("books"),
            "captured_tokens": value.get("captured_tokens"),
            "levels": value.get("levels"),
            "price_history_rows": value.get("price_history_rows"),
            "ws_messages": value.get("ws_messages"),
            "ws_event_rows": value.get("ws_event_rows"),
            "ws_error": value.get("ws_error"),
            "clob_feature_rows": value.get("clob_feature_rows"),
            "clob_features_error": value.get("clob_features_error"),
            "error": value.get("error"),
        }
    return summary


def clob_ensure_decision(health_state, pid_alive):
    if health_state in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING") and pid_alive:
        return "noop"
    if pid_alive:
        return "restart"
    if health_state in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING"):
        return "restart"
    return "start"


def stop_clob_loop(now=None):
    now = now or utc_now()
    status = read_clob_loop_status()
    pid = (status or {}).get("pid")
    if not pid_is_python(pid):
        return {"stopped": False, "reason": f"no live CLOB loop process (pid={pid})"}
    os.kill(int(pid), signal.SIGTERM)
    if status is not None:
        status["last_stop_requested_at"] = now.isoformat()
        write_clob_loop_status(status)
    append_clob_diagnostic({"time": now.isoformat(), "supervisor": "stop", "pid": pid})
    return {"stopped": True, "pid": pid}


def _clob_loop_command(
    market_id="all",
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
        "src.market_microstructure",
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
    CLOB_LOOP_CONSOLE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_handle = CLOB_LOOP_CONSOLE_LOG_PATH.open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    child = subprocess.Popen(
        _clob_loop_command(
            market_id=market_id,
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
        cwd=str(REPO_ROOT),
        stdout=log_handle,
        stderr=log_handle,
        creationflags=creationflags,
    )
    log_handle.close()
    write_clob_loop_status({
        "pid": child.pid,
        "started_at": now.isoformat(),
        "last_heartbeat": now.isoformat(),
        "runtime_identity": get_runtime_identity(),
        "market_id": market_id,
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
        "paused": CLOB_PAUSE_FLAG_PATH.exists(),
        "started_by": "supervisor",
    })
    append_clob_diagnostic({
        "time": now.isoformat(),
        "supervisor": "start",
        "pid": child.pid,
        "market_id": market_id,
        "interval_seconds": interval_seconds,
    })
    return {"started": True, "pid": child.pid}


def ensure_clob_loop(
    market_id="all",
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
    lock_handle = acquire_clob_supervisor_lock()
    if lock_handle is None:
        return {"action": "locked", "state": "UNKNOWN", "reason": "another CLOB supervisor action is running"}
    try:
        status = read_clob_loop_status()
        health = clob_loop_health(status, now=now, interval_seconds=interval_seconds)
        alive = pid_is_python((status or {}).get("pid"))
        action = clob_ensure_decision(health["state"], alive)
        result = {"action": action, "state": health["state"], "pid": health.get("pid")}
        if action == "restart":
            result["stop"] = stop_clob_loop(now=now)
            result["start"] = start_clob_loop_detached(
                market_id=market_id,
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
            result["start"] = start_clob_loop_detached(
                market_id=market_id,
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
            append_clob_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
        return result
    finally:
        release_clob_supervisor_lock(lock_handle)


def run_book_loop(
    market_id="all",
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
    last_midpoints = {}
    status = {
        "pid": os.getpid(),
        "started_at": now_fn().isoformat(),
        "runtime_identity": get_runtime_identity(),
        "market_id": market_id,
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
    while True:
        loop_started = now_fn()
        status["iterations"] += 1
        status["last_heartbeat"] = loop_started.isoformat()
        status["paused"] = CLOB_PAUSE_FLAG_PATH.exists()
        market_ids = [spec.id for spec in all_specs()] if market_id == "all" else [market_id]
        configs = [config_for_date(loop_started.astimezone(spec_for_id(item).tz).date(), item) for item in market_ids]
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




def _market_choices():
    return ["all"] + [spec.id for spec in all_specs()]


def add_loop_options(parser):
    parser.add_argument("--market", choices=_market_choices(), default="all")
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
):
    parser.set_defaults(price_history=default_price_history, websocket_events=default_websocket_events)
    parser.add_argument("--price-history", dest="price_history", action="store_true",
                        help="Capture /prices-history for each token (default).")
    parser.add_argument("--no-price-history", dest="price_history", action="store_false",
                        help="Disable /prices-history capture for this run.")
    parser.add_argument("--websocket-events", dest="websocket_events", action="store_true",
                        help="Record public CLOB market WebSocket events (default).")
    parser.add_argument("--no-websocket-events", dest="websocket_events", action="store_false",
                        help="Disable market WebSocket event capture for this run.")
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
    add_capture_enrichment_options(capture)

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
    audit.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when any market has a gap over the threshold or a stale/missing tape.",
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
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    if command == "loop":
        run_book_loop(
            market_id=args.market,
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
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        if args.strict and not result["ok"]:
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
