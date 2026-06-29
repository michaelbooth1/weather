from weather.operations.windows_silent import apply_windows_silent_subprocess_defaults

apply_windows_silent_subprocess_defaults()

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.paths import REPO_ROOT, data_path
from weather.collection.collection_health import fleet_collection_health, serialize_summary, summarize_folder
from weather.collection.forecast_archive import (
    FORECAST_COLUMNS,
    append_rows as append_forecast_rows,
    build_forecast_rows,
)
from weather.market.market_config import config_for_date, config_from_event, default_target_date, ensure_date
from weather.market.market_registry import DEFAULT_MARKET_ID, all_specs, spec_for_id, spec_for_slug
from weather.model.feature_store import FEATURE_AUDIT_COLUMNS, audit_row
from weather.model.model_constants import LIVE_CACHE_MAX_AGE_MINUTES, SOURCE_CACHE_TTL_MINUTES
from weather.model.model_identity import model_replay_identity
from weather.model.toronto_model import MODEL_VERSION_HGB, TORONTO_TZ
from weather.operations.power import keep_system_awake
from weather.runtime_identity import (
    current_identity_for,
    format_runtime_identity,
    get_runtime_identity,
    identities_match,
)
from weather.operations.supervisor import (
    SupervisorSpec,
    age_minutes,
    append_jsonl,
    acquire_writer_lock,
    attach_status_writer,
    atomic_write_json,
    configure_json_console_logging,
    default_ensure_decision,
    launch_detached,
    loop_file_offsets,
    pid_is_python,
    quarantine_malformed_loop_lines,
    readoption_debounce,
    read_writer_lock,
    read_json_file,
    release_writer_lock,
    should_emit_recovery_block_diagnostic,
    supervisor_recovery_guard,
    terminate_python_pid,
)

from weather.collection.snapshot_store import (  # noqa: E402
    COMPONENT_COLUMNS,
    DEFAULT_MARKET_CONFIG,
    DEFAULT_SNAPSHOT_ROOT,
    FORECAST_PAYLOAD_COLUMNS,
    LONG_COLUMNS,
    MODEL_VERSION,
    PROCESS_RUNTIME_IDENTITY,
    REPLAY_SCHEMA_VERSION,
    RUNTIME_IDENTITY_COLUMNS,
    SNAPSHOT_INTERVAL,
    SNAPSHOT_PROBABILITY_TOLERANCE,
    SOURCE_STATUS_COLUMNS,
    SnapshotStore,
)


def capture_snapshot(
    force=False,
    market_id=DEFAULT_MARKET_ID,
    cadence="scheduled",
    trigger_context=None,
    target_date=None,
):
    from weather.market.polymarket_client import PolymarketClient
    from weather.model.toronto_model import TorontoHighTempModel
    from weather.operations import event_metadata_validation

    target_date = ensure_date(target_date) if target_date is not None else None
    market_client = PolymarketClient(market_id=market_id, target_date=target_date)
    event = market_client.get_event()
    event_config = config_from_event(event, fallback_date=market_client.config.target_date)
    # Pre-local-day guard. In auto mode (no explicit target_date) do not capture a
    # market's event for a date that is still in the future in that market's own
    # local timezone. At the day boundary the live gamma event can resolve to the
    # *next* day's market before that day has begun locally; persisting it writes
    # a stray snapshot hours ahead of the active window. Those strays were the
    # 2026-06-27 western-market "gaps" -- a UTC-measured artifact, not lost data.
    # An explicit target_date (backfill, --date) deliberately bypasses the guard.
    if target_date is None:
        local_today = default_target_date(spec_for_id(market_id).tz)
        if event_config.target_date > local_today:
            return {
                "written": False,
                "snapshot_id": None,
                "skipped": True,
                "skipped_reason": "event_date_ahead_of_local_date",
                "market_id": market_id,
                "event_slug": event_config.event_slug,
                "target_date": event_config.target_date.isoformat(),
                "local_date": local_today.isoformat(),
            }
    store = SnapshotStore(event_slug=event_config.event_slug)
    if (
        not force
        and cadence == "scheduled"
        and hasattr(store, "is_due")
        and not store.is_due(datetime.now(TORONTO_TZ), cadence=cadence)
    ):
        return {
            "written": False,
            "snapshot_id": None,
            "skipped": True,
            "skipped_reason": "not_due_preflight",
            "market_id": market_id,
            "event_slug": event_config.event_slug,
            "target_date": event_config.target_date.isoformat(),
            "path": str(store.long_path),
            "next_due_at": store.next_due_at(cadence=cadence),
        }
    validation = event_metadata_validation.build_validation_payload(
        target_date=event_config.target_date,
        markets=[market_id],
        live_events=[event],
        fetch_live=False,
    )
    validation_gate = event_metadata_validation.gate_for_market(validation, market_id)
    if not validation_gate.get("ok"):
        return {
            "status": "BLOCK",
            "blocked": True,
            "market_id": market_id,
            "event_slug": event_config.event_slug,
            "target_date": event_config.target_date.isoformat(),
            "event_metadata_validation": validation_gate,
            "validation_hash": validation.get("validation_hash"),
            "reason": validation_gate.get("reason"),
        }
    model_client = TorontoHighTempModel(target_date=event_config.target_date, market_id=market_id)
    historical_sources = model_client.fetch_historical_sources()
    live_sources = model_client.fetch_live_sources()
    model = model_client.build(
        event,
        historical_sources=historical_sources,
        live_sources=live_sources,
    )
    return store.maybe_write(
        event,
        model,
        model_client,
        force=force,
        cadence=cadence,
        trigger_context=trigger_context,
    )


SNAPSHOT_DATA_ROOT = data_path() / "snapshots"
PAUSE_FLAG_PATH = SNAPSHOT_DATA_ROOT / "loop_pause.flag"
LOOP_STATUS_PATH = SNAPSHOT_DATA_ROOT / "loop_status.json"
DIAGNOSTICS_PATH = SNAPSHOT_DATA_ROOT / "diagnostics.jsonl"
LOOP_CONSOLE_LOG_PATH = SNAPSHOT_DATA_ROOT / "loop_console.log"
RECENT_LOOP_CYCLE_COUNT = 12
SNAPSHOT_SUPERVISOR = SupervisorSpec(
    name="snapshot_capture",
    module="weather.collection.snapshot_tracker",
    status_path=LOOP_STATUS_PATH,
    diagnostics_path=DIAGNOSTICS_PATH,
    console_log_path=LOOP_CONSOLE_LOG_PATH,
    cwd=REPO_ROOT,
    pause_flag_path=PAUSE_FLAG_PATH,
    tolerated_states=("RUNNING", "PAUSED", "ERRORING"),
    status_schema_fields=(
        "pid",
        "started_at",
        "last_heartbeat",
        "interval_minutes",
        "iterations",
        "consecutive_errors",
        "last_error",
        "paused",
    ),
    restart_budget=6,
    restart_budget_window_hours=24.0,
    restart_backoff_base_seconds=120.0,
    restart_backoff_max_seconds=3600.0,
)


def runtime_supervisor_spec():
    return SNAPSHOT_SUPERVISOR.with_paths(
        status_path=LOOP_STATUS_PATH,
        diagnostics_path=DIAGNOSTICS_PATH,
        console_log_path=LOOP_CONSOLE_LOG_PATH,
        pause_flag_path=PAUSE_FLAG_PATH,
    )


class SourceStatusContext:
    def __init__(self, spec):
        self.spec = spec

    def source_cache_ttl_minutes(self, name):
        return SOURCE_CACHE_TTL_MINUTES.get(name, LIVE_CACHE_MAX_AGE_MINUTES)


FORECAST_PAYLOAD_RECONSTRUCTABLE_SOURCES = {
    "open_meteo",
    "weather_forecast",
    "eccc_citypage",
    "eccc_gem",
    "nws_hourly",
    "nws_grid",
    "nbm_probabilistic_tmax",
    "open_meteo_global_models",
    "open_meteo_multimodel",
    "global_ensemble",
}


def read_jsonl_records(path):
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def parse_capture_time(record, spec):
    value = record.get("captured_at_local") or record.get("captured_at_utc")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=spec.tz if spec else TORONTO_TZ)
    return parsed


def write_rows_csv(path, columns, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)


def replay_inputs_path_for_folder(folder):
    folder = Path(folder)
    replay_inputs_path = folder / "replay_inputs.jsonl"
    if replay_inputs_path.exists():
        return replay_inputs_path
    reconstructed_path = folder / "replay_inputs_reconstructed.jsonl"
    if reconstructed_path.exists():
        return reconstructed_path
    return replay_inputs_path


def backfill_source_status_for_folder(folder, overwrite=False):
    folder = Path(folder)
    status_path = folder / "source_status_long.csv"
    if status_path.exists() and not overwrite:
        return {"folder": str(folder), "rows": 0, "skipped": True, "reason": "source_status_long.csv exists"}
    replay_inputs_path = replay_inputs_path_for_folder(folder)
    records = read_jsonl_records(replay_inputs_path)
    if not records:
        return {
            "folder": str(folder),
            "rows": 0,
            "skipped": True,
            "reason": "no replay_inputs.jsonl or replay_inputs_reconstructed.jsonl",
        }

    spec = spec_for_slug(folder.name)
    context = SourceStatusContext(spec)
    store = SnapshotStore(root=folder, event_slug=folder.name)
    rows = []
    seen = set()
    for record in records:
        snapshot_id = record.get("snapshot_id")
        sources = record.get("sources") or {}
        captured_at = parse_capture_time(record, spec)
        if not snapshot_id or not sources or captured_at is None:
            continue
        for row in store.source_status_rows(
            sources,
            context,
            snapshot_id,
            captured_at,
            record.get("model_version"),
        ):
            key = (row.get("snapshot_id"), row.get("source"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)

    if not rows:
        return {"folder": str(folder), "rows": 0, "skipped": True, "reason": "no source rows"}

    write_rows_csv(status_path, SOURCE_STATUS_COLUMNS, rows)
    with (folder / "source_status.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return {"folder": str(folder), "rows": len(rows), "path": str(status_path)}


def backfill_forecast_payloads_for_folder(folder, overwrite=False):
    folder = Path(folder)
    payload_path = folder / "forecast_payloads_long.csv"
    if payload_path.exists() and not overwrite:
        return {"folder": str(folder), "rows": 0, "skipped": True, "reason": "forecast_payloads_long.csv exists"}
    replay_inputs_path = replay_inputs_path_for_folder(folder)
    records = read_jsonl_records(replay_inputs_path)
    if not records:
        return {
            "folder": str(folder),
            "rows": 0,
            "skipped": True,
            "reason": "no replay_inputs.jsonl or replay_inputs_reconstructed.jsonl",
        }

    spec = spec_for_slug(folder.name)
    store = SnapshotStore(root=folder, event_slug=folder.name)
    rows = []
    seen = set()
    for record in records:
        snapshot_id = record.get("snapshot_id")
        sources = record.get("sources") or {}
        captured_at = parse_capture_time(record, spec)
        if not snapshot_id or not sources or captured_at is None:
            continue
        captured_utc = captured_at.astimezone(timezone.utc).isoformat()
        captured_local = captured_at.isoformat()
        for source, item in sorted(sources.items()):
            if source not in FORECAST_PAYLOAD_RECONSTRUCTABLE_SOURCES:
                continue
            item = item or {}
            data = item.get("data") or {}
            if not isinstance(data, dict) or not data:
                continue
            key = (snapshot_id, source)
            if key in seen:
                continue
            seen.add(key)
            payload = data.get("raw_payload") if "raw_payload" in data else data
            raw_text = json.dumps(payload, sort_keys=True, default=str)
            payload_hash = hashlib.sha1(raw_text.encode("utf-8")).hexdigest()
            suffix = "raw" if "raw_payload" in data else "reconstructed"
            filename = f"{snapshot_id}_{store.safe_filename_part(source)}_{payload_hash[:12]}_{suffix}.json"
            raw_payload_path = folder / "forecast_payloads" / filename
            raw_payload_path.parent.mkdir(parents=True, exist_ok=True)
            raw_payload_path.write_text(raw_text + "\n", encoding="utf-8")
            age_minutes = item.get("cache_age_minutes")
            if age_minutes is None:
                age_minutes = store.source_age_minutes(item.get("fetched_at"), captured_at, None)
            ttl_minutes = item.get("ttl_minutes")
            if ttl_minutes is None:
                ttl_minutes = store.source_ttl_minutes(source)
            status = store.source_status(item)
            rows.append({
                "snapshot_id": snapshot_id,
                "captured_at_utc": captured_utc,
                "captured_at_local": captured_local,
                "event_slug": record.get("event_slug") or folder.name,
                "model_version": record.get("model_version"),
                "source": source,
                "status": status,
                "stale": bool(item.get("stale")),
                "source_family": store.source_family(source, item),
                "degradation_state": store.source_degradation_state(status, item),
                "cache_status": store.source_cache_status(status, item),
                "fetched_at": item.get("fetched_at"),
                "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
                "ttl_minutes": ttl_minutes,
                "provider_issue_time": data.get("provider_issue_time"),
                "provider_update_time": data.get("provider_update_time") or data.get("last_updated"),
                "payload_hash": payload_hash,
                "payload_bytes": len(raw_text.encode("utf-8")),
                "row_count": store.source_row_count(data),
                "source_url": data.get("url"),
                "raw_payload_path": str(raw_payload_path),
            })

    if not rows:
        return {"folder": str(folder), "rows": 0, "skipped": True, "reason": "no forecast payload rows"}

    write_rows_csv(payload_path, FORECAST_PAYLOAD_COLUMNS, rows)
    with (folder / "forecast_payloads.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return {"folder": str(folder), "rows": len(rows), "path": str(payload_path)}


def backfill_source_status(snapshots_root=SNAPSHOT_DATA_ROOT, overwrite=False):
    root = Path(snapshots_root)
    results = [
        backfill_source_status_for_folder(folder, overwrite=overwrite)
        for folder in sorted(path for path in root.iterdir() if path.is_dir())
    ]
    return {
        "snapshots_root": str(root),
        "folders": len(results),
        "written_folders": sum(1 for result in results if result.get("rows", 0) > 0),
        "rows": sum(result.get("rows", 0) for result in results),
        "results": results,
    }


def backfill_forecast_payloads(snapshots_root=SNAPSHOT_DATA_ROOT, overwrite=False):
    root = Path(snapshots_root)
    results = [
        backfill_forecast_payloads_for_folder(folder, overwrite=overwrite)
        for folder in sorted(path for path in root.iterdir() if path.is_dir())
    ]
    return {
        "snapshots_root": str(root),
        "folders": len(results),
        "written_folders": sum(1 for result in results if result.get("rows", 0) > 0),
        "rows": sum(result.get("rows", 0) for result in results),
        "results": results,
    }


def read_loop_status():
    return read_json_file(LOOP_STATUS_PATH)


def write_loop_status(status):
    return atomic_write_json(LOOP_STATUS_PATH, status)


def append_diagnostic(record):
    return append_jsonl(DIAGNOSTICS_PATH, record)


def _age_minutes(now, iso_value):
    return age_minutes(now, iso_value, default_tz=TORONTO_TZ)


def runtime_identity_status(process_identity, current_identity=None):
    if not process_identity:
        return {
            "runtime_code_state": "unknown",
            "runtime_identity_matches_current": None,
            "current_runtime_identity": current_identity,
            "detail": "no runtime identity recorded",
        }
    current_identity = current_identity or current_identity_for(process_identity)
    matches = identities_match(process_identity, current_identity)
    return {
        "runtime_code_state": "current" if matches else "stale_code",
        "runtime_identity_matches_current": matches,
        "current_runtime_identity": current_identity,
        "detail": None if matches else (
            "running process code identity differs from current source tree: "
            f"process={format_runtime_identity(process_identity)}; "
            f"current={format_runtime_identity(current_identity)}"
        ),
    }


def loop_health(status, now, interval_minutes=10.0, current_identity=None, pid_alive=None):
    """Judge collection liveness from the heartbeat. Liveness is decided by
    heartbeat freshness, not PID (a stale heartbeat means dead regardless, and
    PIDs get reused across reboots)."""
    if not status:
        return {"state": "UNKNOWN", "detail": "no status file (loop never ran or was cleaned)"}
    interval = status.get("interval_minutes", interval_minutes)
    hb_age = _age_minutes(now, status.get("last_heartbeat"))
    snap_age = _age_minutes(now, status.get("last_snapshot_written_at"))
    errors = status.get("consecutive_errors", 0)
    dead_after = 2 * interval + 2  # tolerate one full sleep cycle plus slack
    runtime = runtime_identity_status(status.get("runtime_identity"), current_identity)
    if pid_alive is None:
        pid_alive = pid_is_python(status.get("pid"))
    if not pid_alive:
        state = "DEAD"
    elif runtime.get("runtime_code_state") == "stale_code":
        state = "STALE_CODE"
    elif status.get("paused"):
        state = "PAUSED"
    elif hb_age is None or hb_age > dead_after:
        state = "DEAD"
    elif errors >= 3:
        state = "ERRORING"
    else:
        state = "RUNNING"
    return {
        "state": state,
        "pid": status.get("pid"),
        "pid_alive": bool(pid_alive),
        "heartbeat_age_min": round(hb_age, 1) if hb_age is not None else None,
        "last_snapshot_age_min": round(snap_age, 1) if snap_age is not None else None,
        "consecutive_errors": errors,
        "last_error": status.get("last_error"),
        "started_at": status.get("started_at"),
        "last_iteration_elapsed_minutes": status.get("last_iteration_elapsed_minutes"),
        "max_recent_iteration_elapsed_minutes": status.get("max_recent_iteration_elapsed_minutes"),
        "last_sleep_seconds": status.get("last_sleep_seconds"),
        **runtime,
    }


def current_collection_health(now=None, interval_minutes=10.0, tolerance=1.5, target_date=None):
    now = now or datetime.now(TORONTO_TZ)
    config = config_for_date(target_date or now.date())
    folder = SNAPSHOT_DATA_ROOT / config.event_slug
    summary = summarize_folder(
        folder,
        interval_minutes=interval_minutes,
        tolerance=tolerance,
        live=True,
        as_of=now,
    )
    return serialize_summary(summary)


def current_fleet_collection_health(now=None, interval_minutes=10.0, tolerance=1.5, target_date=None):
    now = now or datetime.now(TORONTO_TZ)
    return fleet_collection_health(
        snapshots_root=SNAPSHOT_DATA_ROOT,
        interval_minutes=interval_minutes,
        tolerance=tolerance,
        live=True,
        as_of=now,
        target_date=target_date,
    )


def _toronto_now(value):
    if value is None:
        return datetime.now(TORONTO_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=TORONTO_TZ)
    return value.astimezone(TORONTO_TZ)


def snapshot_due_state(market_id, target_date=None, now=None):
    spec = spec_for_id(market_id)
    effective_date = ensure_date(target_date) if target_date is not None else default_target_date(spec.tz)
    config = config_for_date(effective_date, market_id)
    store = SnapshotStore(event_slug=config.event_slug)
    due_now = _toronto_now(now)
    last_snapshot = store.last_snapshot_time(cadence="scheduled")
    return {
        "market_id": market_id,
        "event_slug": config.event_slug,
        "target_date": config.target_date.isoformat(),
        "due": store.is_due(due_now, cadence="scheduled"),
        "last_snapshot_at": last_snapshot.isoformat() if last_snapshot else None,
        "next_due_at": store.next_due_at(cadence="scheduled"),
    }


def ordered_snapshot_specs(specs, *, target_date=None, now=None):
    rows = [(spec, snapshot_due_state(spec.id, target_date=target_date, now=now)) for spec in specs]

    def sort_key(item):
        spec, state = item
        due_rank = 0 if state.get("due") else 1
        last_snapshot = state.get("last_snapshot_at") or ""
        next_due = state.get("next_due_at") or ""
        return (due_rank, last_snapshot, next_due, spec.id)

    return sorted(rows, key=sort_key)


def _normalized_pid(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cleanup_loop_writer_lock(expected_pid=None, attempts=1, sleep_seconds=0.1):
    """Remove this loop's writer lock when its owner has been stopped or died."""
    attempts = max(1, int(attempts))
    last_result = None
    for attempt in range(attempts):
        lock = read_writer_lock(LOOP_STATUS_PATH)
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


def stop_loop(now=None):
    """Terminate the managed loop recorded in the status file, if it is alive.
    Returns a result dict; never raises for an already-dead loop."""
    now = now or datetime.now(TORONTO_TZ)
    status = read_loop_status()
    pid = (status or {}).get("pid")
    if not pid_is_python(pid):
        return {"stopped": False, "reason": f"no live loop process (pid={pid})"}
    stop = terminate_python_pid(pid)
    if not stop.get("stopped"):
        return {"stopped": False, "pid": pid, "reason": stop.get("reason")}
    lock_cleanup = _cleanup_loop_writer_lock(expected_pid=pid, attempts=20, sleep_seconds=0.1)
    if status is not None:
        status["last_stop_requested_at"] = now.isoformat()
        write_loop_status(status)
    append_diagnostic({"time": now.isoformat(), "supervisor": "stop", "pid": pid, "writer_lock": lock_cleanup})
    return {"stopped": True, "pid": pid, "writer_lock": lock_cleanup}


def start_loop_detached(interval_minutes=10.0, now=None):
    """Spawn the loop as a detached process (survives this process exiting),
    console output appended to ``loop_console.log``. Writes a provisional
    status immediately so a racing --ensure does not double-start."""
    now = now or datetime.now(TORONTO_TZ)
    lock_cleanup = _cleanup_loop_writer_lock(attempts=3, sleep_seconds=0.1)
    if lock_cleanup.get("reason") == "writer lock owner is still live":
        append_diagnostic({
            "time": now.isoformat(),
            "supervisor": "start_blocked",
            "reason": "writer lock owner is still live",
            "writer_lock": lock_cleanup,
        })
        return {"started": False, "reason": "writer lock owner is still live", "writer_lock": lock_cleanup}
    child = launch_detached(
        SNAPSHOT_SUPERVISOR.command("--loop", "--interval-minutes", interval_minutes),
        cwd=SNAPSHOT_SUPERVISOR.cwd,
        console_log_path=LOOP_CONSOLE_LOG_PATH,
        popen_fn=subprocess.Popen,
    )
    write_loop_status({
        "pid": child.pid,
        "started_at": now.isoformat(),
        "last_heartbeat": now.isoformat(),
        "runtime_identity": get_runtime_identity(scope_files="loaded"),
        "interval_minutes": interval_minutes,
        "iterations": 0,
        "consecutive_errors": 0,
        "last_error": None,
        "last_snapshot_id": None,
        "last_snapshot_written_at": None,
        "paused": PAUSE_FLAG_PATH.exists(),
        "started_by": "supervisor",
    })
    append_diagnostic({"time": now.isoformat(), "supervisor": "start", "pid": child.pid, "writer_lock": lock_cleanup})
    return {"started": True, "pid": child.pid, "writer_lock": lock_cleanup}


def ensure_decision(health_state, pid_alive):
    """Pure supervisor decision: what --ensure should do given loop health.

    RUNNING/PAUSED are healthy (paused is operator intent); ERRORING is alive
    and already logging failures, so leave it visible rather than masking it
    with restarts. A stale heartbeat with a live PID is a HUNG process: kill
    and start fresh. Dead or never-started: start.
    """
    return default_ensure_decision(
        health_state,
        pid_alive,
        tolerated_states=SNAPSHOT_SUPERVISOR.tolerated_states,
    )


def ensure_loop(interval_minutes=10.0, now=None):
    """The supervisor verb Task Scheduler runs every few minutes: keep exactly
    one healthy loop alive across silent deaths, hangs, and reboots."""
    now = now or datetime.now(TORONTO_TZ)
    spec = runtime_supervisor_spec()
    status = read_loop_status()
    health = loop_health(status, now, interval_minutes)
    alive = pid_is_python((status or {}).get("pid"))
    action = ensure_decision(health["state"], alive)
    result = {
        "action": action,
        "state": health["state"],
        "pid": health.get("pid"),
        "restart_cause": health["state"] if action in {"start", "restart"} else None,
        "runtime_identity_before": (status or {}).get("runtime_identity"),
        "current_runtime_identity": health.get("current_runtime_identity"),
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
            append_diagnostic(event)
        else:
            result["diagnostic_suppressed"] = True
        return result
    if action == "restart" and health["state"] == "STALE_CODE":
        debounce = readoption_debounce(
            runtime_code_state=health.get("runtime_code_state"),
            process_started_at=(status or {}).get("started_at"),
            now=now,
            debounce_seconds=spec.readoption_debounce_seconds,
        )
        result["readoption_debounce"] = debounce
        if debounce.get("debounced"):
            # The running loop is on slightly-stale code but re-adopted very
            # recently. Let it finish at least one full capture cycle before
            # relaunching, so a burst of commits cannot starve the tail markets.
            result["intended_action"] = action
            result["action"] = "noop"
            result["reason"] = debounce.get("reason")
            append_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
            return result
    if action == "restart":
        result["stop"] = stop_loop(now=now)
        result["malformed_loop_line_quarantine"] = quarantine_malformed_loop_lines(spec)
        result["start"] = start_loop_detached(interval_minutes, now=now)
    elif action == "start":
        result["malformed_loop_line_quarantine"] = quarantine_malformed_loop_lines(spec)
        result["start"] = start_loop_detached(interval_minutes, now=now)
    if action != "noop":
        result["loop_offsets_after"] = loop_file_offsets(spec)
        append_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
    return result


def _numeric(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_recent_elapsed(status, elapsed_minutes):
    elapsed_rounded = round(float(elapsed_minutes), 3)
    recent = []
    for value in status.get("recent_iteration_elapsed_minutes") or []:
        numeric = _numeric(value)
        if numeric is not None:
            recent.append(float(numeric))
    recent.append(elapsed_rounded)
    recent = recent[-RECENT_LOOP_CYCLE_COUNT:]
    status["last_iteration_elapsed_minutes"] = elapsed_rounded
    status["recent_iteration_elapsed_minutes"] = recent
    status["max_recent_iteration_elapsed_minutes"] = round(max(recent), 3)


def run_loop(
    force=False,
    interval_minutes=10.0,
    max_iterations=None,
    capture_fn=None,
    sleep_fn=time.sleep,
    now_fn=None,
    target_date=None,
):
    """Crash-proof managed snapshot loop: a capture failure is logged and the
    loop continues, so collection never silently dies on a transient error. A
    heartbeat + diagnostics record is written every iteration."""
    now_fn = now_fn or (lambda: datetime.now(TORONTO_TZ))
    preflight_due_enabled = capture_fn is None
    capture_fn = capture_fn or capture_snapshot
    target_date = ensure_date(target_date) if target_date is not None else None
    writer_lock = acquire_writer_lock(
        LOOP_STATUS_PATH,
        owner={"loop": SNAPSHOT_SUPERVISOR.name, "module": SNAPSHOT_SUPERVISOR.module},
        stale_after_seconds=max(120.0, float(interval_minutes) * 60.0 * 3.0),
    )
    if writer_lock is None:
        existing = read_writer_lock(LOOP_STATUS_PATH)
        append_diagnostic({
            "time": now_fn().isoformat(),
            "status": "duplicate_writer_blocked",
            "existing_writer": existing,
            "pid": os.getpid(),
        })
        return {"status": "duplicate_writer_blocked", "existing_writer": existing, "pid": os.getpid()}
    sleep_inhibitor = keep_system_awake("weather snapshot capture loop")
    power_request = sleep_inhibitor.start()
    status = {
        "pid": os.getpid(),
        "started_at": now_fn().isoformat(),
        "runtime_identity": PROCESS_RUNTIME_IDENTITY,
        "power_request": power_request,
        "interval_minutes": interval_minutes,
        "iterations": 0,
        "consecutive_errors": 0,
        "last_error": None,
        "last_snapshot_id": None,
        "last_snapshot_written_at": None,
        "paused": False,
    }
    attach_status_writer(status, writer_lock)
    try:
        while True:
            now = now_fn()
            iteration_started = now
            status["iterations"] += 1
            status["last_heartbeat"] = now.isoformat()
            status["paused"] = PAUSE_FLAG_PATH.exists()
            runtime = runtime_identity_status(status.get("runtime_identity"))
            status["runtime_guard"] = runtime
            stale_code = runtime.get("runtime_code_state") == "stale_code"
            readopt = (
                readoption_debounce(
                    runtime_code_state=runtime.get("runtime_code_state"),
                    process_started_at=status.get("started_at"),
                    now=now,
                    debounce_seconds=SNAPSHOT_SUPERVISOR.readoption_debounce_seconds,
                )
                if stale_code
                else None
            )
            if stale_code and not (readopt or {}).get("debounced"):
                status["last_error"] = runtime.get("detail")
                status["consecutive_errors"] += 1
                status["stale_code_exit_requested_at"] = now.isoformat()
                write_loop_status(status)
                append_diagnostic({
                    "time": now.isoformat(),
                    "status": "stale_code",
                    "detail": runtime.get("detail"),
                    "action": "exit_cleanly",
                })
                print(json.dumps({
                    "status": "stale_code",
                    "time": now.isoformat(),
                    "detail": runtime.get("detail"),
                    "action": "exit_cleanly",
                }, sort_keys=True), flush=True)
                return status
            elif status["paused"]:
                write_loop_status(status)
                append_diagnostic({"time": now.isoformat(), "status": "paused"})
                print(json.dumps({"status": "paused", "time": now.isoformat()}), flush=True)
            else:
                if stale_code:
                    # Debounced benign re-adoption: keep collecting on
                    # slightly-stale code this cycle so a commit burst can't kill
                    # the loop mid-iteration and starve the tail markets. The loop
                    # re-adopts once the debounce window elapses.
                    status["runtime_guard"] = {**runtime, "readoption_debounce": readopt}
                    append_diagnostic({
                        "time": now.isoformat(),
                        "status": "stale_code_debounced",
                        "readoption_debounce": readopt,
                    })
                # Capture every registered market each tick; one market's failure is
                # isolated so it never kills the loop or the other markets.
                market_results = {}
                specs = list(all_specs())
                if preflight_due_enabled:
                    ordered_rows = ordered_snapshot_specs(specs, target_date=target_date, now=now)
                else:
                    ordered_rows = [(spec, None) for spec in specs]
                for spec, due_state in ordered_rows:
                    try:
                        status["last_market_in_progress"] = spec.id
                        status["last_heartbeat"] = now_fn().isoformat()
                        write_loop_status(status)
                        if (
                            preflight_due_enabled
                            and not force
                            and due_state is not None
                            and not due_state.get("due")
                        ):
                            result = {
                                "written": False,
                                "snapshot_id": None,
                                "skipped": True,
                                "skipped_reason": "not_due_preflight",
                                "market_id": spec.id,
                                "event_slug": due_state.get("event_slug"),
                                "target_date": due_state.get("target_date"),
                                "next_due_at": due_state.get("next_due_at"),
                            }
                        elif target_date is None:
                            result = capture_fn(force=force, market_id=spec.id)
                        else:
                            result = capture_fn(force=force, market_id=spec.id, target_date=target_date)
                        market_results[spec.id] = result
                        progress_now = now_fn()
                        status["last_heartbeat"] = progress_now.isoformat()
                        if result.get("written"):
                            status["last_snapshot_id"] = result.get("snapshot_id")
                            status["last_snapshot_written_at"] = progress_now.isoformat()
                    except Exception as exc:  # noqa: BLE001 - keep the loop alive
                        market_results[spec.id] = {"error": f"{type(exc).__name__}: {exc}"}
                        status["last_heartbeat"] = now_fn().isoformat()
                    status["last_market_results"] = {
                        mid: {
                            "written": bool(result.get("written")),
                            "snapshot_id": result.get("snapshot_id"),
                            "error": result.get("error"),
                            "skipped_reason": result.get("skipped_reason"),
                            "next_due_at": result.get("next_due_at"),
                        }
                        for mid, result in market_results.items()
                    }
                    write_loop_status(status)
                errors = {mid: r["error"] for mid, r in market_results.items() if r.get("error")}
                if errors:
                    status["consecutive_errors"] += 1
                    status["last_error"] = "; ".join(f"{mid}: {err}" for mid, err in errors.items())
                else:
                    status["consecutive_errors"] = 0
                    status["last_error"] = None
                status["last_market_in_progress"] = None
                elapsed_minutes = (now_fn() - iteration_started).total_seconds() / 60.0
                _record_recent_elapsed(status, elapsed_minutes)
                try:
                    fleet_health = current_fleet_collection_health(
                        now=now_fn(),
                        interval_minutes=interval_minutes,
                    )
                    status["fleet_collection"] = {
                        "schema_version": fleet_health.get("schema_version"),
                        "summary": fleet_health.get("summary"),
                        "attention_markets": [
                            row["market_id"]
                            for row in fleet_health.get("markets", [])
                            if row.get("action_required")
                        ],
                    }
                except Exception as exc:  # noqa: BLE001 - observability must not kill collection
                    status["fleet_collection"] = {
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                write_loop_status(status)
                append_diagnostic({
                    "time": now.isoformat(),
                    "markets": {
                        mid: {"written": bool(r.get("written")), "snapshot_id": r.get("snapshot_id"), "error": r.get("error")}
                        for mid, r in market_results.items()
                    },
                })
                print(json.dumps({
                    "time": now.isoformat(),
                    "markets": {mid: {"written": bool(r.get("written")), "snapshot_id": r.get("snapshot_id")} for mid, r in market_results.items()},
                }, sort_keys=True), flush=True)
            elapsed_seconds = (now_fn() - iteration_started).total_seconds()
            sleep_seconds = max(1.0, interval_minutes * 60.0 - elapsed_seconds)
            status["last_sleep_seconds"] = round(sleep_seconds, 1)
            write_loop_status(status)
            if max_iterations is not None and status["iterations"] >= max_iterations:
                return status
            sleep_fn(sleep_seconds)
    finally:
        sleep_inhibitor.stop()
        release_writer_lock(writer_lock)


def main():
    # Under pythonw.exe (the windowless interpreter the supervisor task uses so
    # no console flashes every 10 minutes) sys.stdout/stderr are None and any
    # print would crash. Route them to devnull; file/JSONL logging is unaffected.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Capture Toronto weather-market model/market odds snapshots."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Write even if the 10-minute interval has not elapsed.",
    )
    parser.add_argument(
        "--date",
        "--target-date",
        dest="target_date",
        default="",
        help="Explicit target market date, YYYY-MM-DD. Defaults to each market's current local date.",
    )
    parser.add_argument(
        "--market",
        default=DEFAULT_MARKET_ID,
        help="Market id for one-shot capture, or 'all' to capture every configured market.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously and check for due snapshots every interval.",
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=10.0,
        help="Loop interval in minutes.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the managed loop's health (from the heartbeat) and exit.",
    )
    parser.add_argument(
        "--status-tolerance",
        type=float,
        default=1.5,
        help="Collection gap tolerance multiplier used by --status.",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Terminate the managed loop process recorded in loop_status.json.",
    )
    parser.add_argument(
        "--start-detached",
        action="store_true",
        help="Start the loop as a detached background process (refuses if one is healthy).",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Stop the managed loop (if alive) and start a fresh detached one with current code.",
    )
    parser.add_argument(
        "--ensure",
        action="store_true",
        help="Supervisor check: start/restart the loop only if it is dead or hung. "
             "Run this from Task Scheduler every few minutes.",
    )
    parser.add_argument(
        "--backfill-source-status",
        action="store_true",
        help=(
            "Rebuild source_status_long.csv/jsonl from replay_inputs.jsonl "
            "or replay_inputs_reconstructed.jsonl under --snapshots-root."
        ),
    )
    parser.add_argument(
        "--backfill-forecast-payloads",
        action="store_true",
        help=(
            "Rebuild forecast_payloads_long.csv/jsonl and reconstructed payload JSON files "
            "from replay_inputs.jsonl or replay_inputs_reconstructed.jsonl under --snapshots-root."
        ),
    )
    parser.add_argument(
        "--snapshots-root",
        default=str(SNAPSHOT_DATA_ROOT),
        help="Snapshot root used by backfill commands.",
    )
    parser.add_argument(
        "--source-status-folder",
        default="",
        help="Optional single snapshot folder for --backfill-source-status.",
    )
    parser.add_argument(
        "--overwrite-source-status",
        action="store_true",
        help="Overwrite existing source_status_long.csv/jsonl during --backfill-source-status.",
    )
    parser.add_argument(
        "--overwrite-forecast-payloads",
        action="store_true",
        help="Overwrite existing forecast_payloads_long.csv/jsonl during --backfill-forecast-payloads.",
    )
    args = parser.parse_args()
    target_date = ensure_date(args.target_date) if args.target_date else None

    if args.status:
        health = loop_health(read_loop_status(), datetime.now(TORONTO_TZ), args.interval_minutes)
        health["collection"] = current_collection_health(
            interval_minutes=args.interval_minutes,
            tolerance=args.status_tolerance,
            target_date=target_date,
        )
        health["fleet_collection"] = current_fleet_collection_health(
            interval_minutes=args.interval_minutes,
            tolerance=args.status_tolerance,
            target_date=target_date,
        )
        print(json.dumps(health, indent=2, sort_keys=True, default=str))
        return
    if args.stop:
        print(json.dumps(stop_loop(), indent=2, sort_keys=True))
        return
    if args.restart:
        result = {"stop": stop_loop(), "start": start_loop_detached(args.interval_minutes)}
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if args.start_detached:
        health = loop_health(read_loop_status(), datetime.now(TORONTO_TZ), args.interval_minutes)
        if health["state"] in ("RUNNING", "PAUSED", "ERRORING") and pid_is_python(health.get("pid")):
            print(json.dumps({"started": False, "reason": f"loop already {health['state']}"}, indent=2))
            return
        print(json.dumps(start_loop_detached(args.interval_minutes), indent=2, sort_keys=True))
        return
    if args.ensure:
        print(json.dumps(ensure_loop(args.interval_minutes), indent=2, sort_keys=True, default=str))
        return
    if args.backfill_source_status:
        if args.source_status_folder:
            print(json.dumps(
                backfill_source_status_for_folder(Path(args.source_status_folder), overwrite=args.overwrite_source_status),
                indent=2,
                sort_keys=True,
                default=str,
            ))
            return
        print(json.dumps(
            backfill_source_status(args.snapshots_root, overwrite=args.overwrite_source_status),
            indent=2,
            sort_keys=True,
            default=str,
        ))
        return
    if args.backfill_forecast_payloads:
        print(json.dumps(
            backfill_forecast_payloads(args.snapshots_root, overwrite=args.overwrite_forecast_payloads),
            indent=2,
            sort_keys=True,
            default=str,
        ))
        return
    if not args.loop:
        if str(args.market).lower() == "all":
            results = {
                spec.id: capture_snapshot(
                    force=args.force,
                    market_id=spec.id,
                    target_date=target_date,
                )
                for spec in all_specs()
            }
            print(json.dumps({
                "market": "all",
                "target_date": target_date.isoformat() if target_date else None,
                "markets": results,
                "written_markets": sum(1 for result in results.values() if result.get("written")),
                "blocked_markets": [
                    market_id
                    for market_id, result in results.items()
                    if result.get("blocked") or result.get("status") == "BLOCK"
                ],
                "error_markets": [
                    market_id for market_id, result in results.items() if result.get("error")
                ],
            }, indent=2, sort_keys=True, default=str))
            return
        print(json.dumps(
            capture_snapshot(force=args.force, market_id=args.market, target_date=target_date),
            indent=2,
            sort_keys=True,
            default=str,
        ))
        return

    configure_json_console_logging()
    run_loop(force=args.force, interval_minutes=args.interval_minutes, target_date=target_date)


if __name__ == "__main__":
    main()
