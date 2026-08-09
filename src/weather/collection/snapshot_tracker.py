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
from weather.collection.forecast_payload_cas import (
    SHARED_FORECAST_PAYLOAD_CAS_ROOT,
)
from weather.forecast_payload_contracts import (
    ForecastPayloadExtractionIdentityError,
    deduplicate_fanout_coordinator_attributions,
    fanout_coordinator_attribution_totals,
)
from weather.io import (
    ROTATE_BEFORE_APPEND,
    ROTATE_BEFORE_LAUNCH,
    append_rotating_jsonl,
    rotate_sidecar_policy,
)
from weather.collection.forecast_payload_fetch_fanout import (
    fanout_from_environment,
)
from weather.market.market_config import config_for_date, config_from_event, default_target_date, ensure_date
from weather.market.market_registry import DEFAULT_MARKET_ID, all_specs, spec_for_id, spec_for_slug
from weather.model.feature_store import FEATURE_AUDIT_COLUMNS, audit_row
from weather.model.model_constants import LIVE_CACHE_MAX_AGE_MINUTES, SOURCE_CACHE_TTL_MINUTES
from weather.model.model_identity import model_replay_identity
from weather.model.toronto_model import MODEL_VERSION_HGB, TORONTO_TZ
from weather.operations.capture_resource_gate import available_memory_bytes
from weather.operations.power import keep_system_awake
from weather.runtime_identity import (
    current_identity_for,
    format_runtime_identity,
    get_runtime_identity,
    identities_match,
)
from weather.operations.supervisor import (
    SupervisorSpec,
    acquire_file_lock,
    authorize_managed_process_termination,
    managed_stop_expected_command,
    authorize_writer_lock_removal,
    age_minutes,
    acquire_writer_lock,
    attach_status_writer,
    atomic_write_json,
    configure_json_console_logging,
    capture_managed_process_identity,
    default_ensure_decision,
    launch_detached,
    loop_file_offsets,
    loop_writer_lock_health,
    managed_stop_allows_start,
    pid_is_python,
    persist_supervisor_status,
    quarantine_malformed_loop_lines,
    readoption_debounce,
    read_writer_lock,
    read_json_file,
    read_supervisor_status,
    release_file_lock,
    release_writer_lock,
    should_emit_recovery_block_diagnostic,
    supervisor_recovery_guard,
    terminate_managed_process,
)

from weather.collection.snapshot_capture_batch import (  # noqa: E402
    DEFAULT_CAPTURE_HOST_RESERVE_MB,
    DEFAULT_CAPTURE_WORKERS,
    DEFAULT_CHILD_WORKING_SET_MAX_MB,
    DEFAULT_FLEET_BUDGET_SECONDS,
    DEFAULT_MARKET_TIMEOUT_SECONDS,
    capture_worker_admission,
    run_bounded_capture_batch,
    run_isolated_capture,
)
from weather.collection.triggered_snapshot_queue import (  # noqa: E402
    DEFAULT_TRIGGER_QUEUE_ROOT,
    claim_triggered_snapshot_jobs,
    complete_triggered_snapshot_job,
    has_pending_triggered_snapshot_jobs,
    recover_inflight_jobs,
    retry_triggered_snapshot_job,
    triggered_snapshot_queue_status,
)
from weather.collection.snapshot_store import (  # noqa: E402
    COMPONENT_COLUMNS,
    DEFAULT_MARKET_CONFIG,
    DEFAULT_SNAPSHOT_ROOT,
    FORECAST_PAYLOAD_COLUMNS,
    FORECAST_RAW_PAYLOAD_RETENTION_ENV,
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
    cross_process_fanout, fanout_scope = fanout_from_environment()
    store = SnapshotStore(
        event_slug=event_config.event_slug,
        shared_forecast_payload_cas_root=(
            cross_process_fanout.cas.root if cross_process_fanout is not None else None
        ),
    )
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
    model_kwargs = {
        "target_date": event_config.target_date,
        "market_id": market_id,
    }
    verified_bundle_loader = getattr(store, "verified_serving_bundle", None)
    if callable(verified_bundle_loader):
        model_kwargs["serving_bundle"] = verified_bundle_loader()
    model_client = TorontoHighTempModel(**model_kwargs)
    if cross_process_fanout is not None and store.retain_raw_forecast_payloads:
        model_client.market_invariant_fetch_fanout = cross_process_fanout
        model_client.market_invariant_fetch_scope = fanout_scope
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
SOURCE_FAMILY_COOLDOWN_PATH = data_path() / "ops" / "live_source_family_cooldown.json"
PAUSE_FLAG_PATH = SNAPSHOT_DATA_ROOT / "loop_pause.flag"
LOOP_STATUS_PATH = SNAPSHOT_DATA_ROOT / "loop_status.json"
DIAGNOSTICS_PATH = SNAPSHOT_DATA_ROOT / "diagnostics.jsonl"
LOOP_CONSOLE_LOG_PATH = SNAPSHOT_DATA_ROOT / "loop_console.log"
SUPERVISOR_LOCK_PATH = SNAPSHOT_DATA_ROOT / "loop_supervisor.lock"
RECENT_LOOP_CYCLE_COUNT = 12
DEFAULT_TRIGGER_QUEUE_SLEEP_CHECK_SECONDS = 5.0
SNAPSHOT_SUPERVISOR = SupervisorSpec(
    name="snapshot_capture",
    module="weather.collection.snapshot_tracker",
    status_path=LOOP_STATUS_PATH,
    diagnostics_path=DIAGNOSTICS_PATH,
    console_log_path=LOOP_CONSOLE_LOG_PATH,
    cwd=REPO_ROOT,
    pause_flag_path=PAUSE_FLAG_PATH,
    lock_path=SUPERVISOR_LOCK_PATH,
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
        lock_path=SUPERVISOR_LOCK_PATH,
    )


def runtime_snapshot_sidecar_rotation_policy():
    return {
        DIAGNOSTICS_PATH: ROTATE_BEFORE_APPEND,
        LOOP_CONSOLE_LOG_PATH: ROTATE_BEFORE_LAUNCH,
    }


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


def retain_raw_forecast_payloads_enabled():
    value = os.environ.get(FORECAST_RAW_PAYLOAD_RETENTION_ENV, "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def backfill_forecast_payloads_for_folder(folder, overwrite=False, retain_raw_payloads=False):
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
            raw_payload_path = ""
            if retain_raw_payloads:
                suffix = "raw" if "raw_payload" in data else "reconstructed"
                filename = f"{snapshot_id}_{store.safe_filename_part(source)}_{payload_hash[:12]}_{suffix}.json"
                raw_path = folder / "forecast_payloads" / filename
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(raw_text + "\n", encoding="utf-8")
                raw_payload_path = str(raw_path)
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
                "raw_payload_path": raw_payload_path,
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


def backfill_forecast_payloads(
    snapshots_root=SNAPSHOT_DATA_ROOT,
    overwrite=False,
    retain_raw_payloads=None,
):
    root = Path(snapshots_root)
    retain_raw_payloads = (
        retain_raw_forecast_payloads_enabled()
        if retain_raw_payloads is None
        else bool(retain_raw_payloads)
    )
    results = [
        backfill_forecast_payloads_for_folder(
            folder,
            overwrite=overwrite,
            retain_raw_payloads=retain_raw_payloads,
        )
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
    return append_rotating_jsonl(DIAGNOSTICS_PATH, record)


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
    # The heartbeat updates per market inside a sweep, so a loop thrashing
    # under host memory pressure reads RUNNING while per-market captures gap
    # for an hour-plus (2026-07-03 stall). Restarting doesn't relieve external
    # pressure, so this stays out of `state`; it is a visibility flag for
    # status/fleet consumers.
    capture_degraded = (
        state == "RUNNING"
        and snap_age is not None
        and snap_age > dead_after
    )
    return {
        "state": state,
        "capture_degraded": capture_degraded,
        "capture_degraded_reason": (
            f"heartbeat fresh but last snapshot {round(snap_age, 1)} min old"
            f" (> {round(dead_after, 1)} min)"
            if capture_degraded
            else None
        ),
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


def _snapshot_loop_command(interval_minutes=10.0):
    return SNAPSHOT_SUPERVISOR.command(
        "--loop",
        "--interval-minutes",
        interval_minutes,
    )


def _cleanup_loop_writer_lock(
    expected_pid=None,
    attempts=1,
    sleep_seconds=0.1,
    confirmed_exit=None,
    exited_identity=None,
):
    """Remove this loop's writer lock when its owner has been stopped or died."""
    attempts = max(1, int(attempts))
    last_result = None
    for attempt in range(attempts):
        lock = read_writer_lock(LOOP_STATUS_PATH)
        if not lock.get("exists"):
            return {"removed": False, "reason": "no writer lock", "path": lock.get("path")}
        owner_pid = _normalized_pid(lock.get("pid"))
        expected = _normalized_pid(expected_pid)
        removal = authorize_writer_lock_removal(
            lock,
            expected_pid=expected,
            confirmed_exit=confirmed_exit,
            exited_identity=exited_identity,
        )
        if not removal.get("authorized"):
            return {
                "removed": False,
                "blocked": True,
                "reason": removal.get("reason"),
                "pid": owner_pid,
                "path": lock.get("path"),
                "authorization": removal,
            }
        reason = "stopped writer pid" if expected is not None and owner_pid == expected else "dead writer pid"
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
    writer_lock = read_writer_lock(LOOP_STATUS_PATH)
    expected_command = managed_stop_expected_command(
        status,
        _snapshot_loop_command((status or {}).get("interval_minutes", 10.0)),
    )
    authorization = authorize_managed_process_termination(
        status,
        writer_lock,
        expected_command,
    )
    if not authorization.get("authorized"):
        return {
            "stopped": False,
            "pid": pid,
            "reason": authorization.get("reason"),
            "authorization": authorization,
            "writer_lock": writer_lock,
        }
    managed_process = authorization["managed_process"]
    stop = terminate_managed_process(managed_process, expected_command)
    if not stop.get("stopped"):
        return {
            "stopped": False,
            "termination_requested": bool(stop.get("termination_requested")),
            "pid": pid,
            "reason": stop.get("reason"),
            "termination_scope": stop.get("termination_scope"),
            "authorization": authorization,
            "writer_lock": writer_lock,
        }
    confirmed_exit = {
        "exited": stop.get("exited") is True,
        "reason": stop.get("reason"),
        "pid": pid,
        "termination_scope": stop.get("termination_scope"),
    }
    lock_cleanup = _cleanup_loop_writer_lock(
        expected_pid=pid,
        attempts=20,
        sleep_seconds=0.1,
        confirmed_exit=confirmed_exit,
        exited_identity=managed_process,
    )
    if not confirmed_exit.get("exited"):
        return {
            "stopped": False,
            "termination_requested": True,
            "pid": pid,
            "reason": confirmed_exit.get("reason"),
            "authorization": authorization,
            "post_termination_observation": confirmed_exit,
            "writer_lock": lock_cleanup,
        }
    if status is not None:
        status["last_stop_requested_at"] = now.isoformat()
        write_loop_status(status)
    append_diagnostic({"time": now.isoformat(), "supervisor": "stop", "pid": pid, "writer_lock": lock_cleanup})
    return {
        "stopped": True,
        "pid": pid,
        "authorization": authorization,
        "post_termination_observation": confirmed_exit,
        "writer_lock": lock_cleanup,
    }


def start_loop_detached(interval_minutes=10.0, now=None):
    """Spawn the loop as a detached process (survives this process exiting),
    console output appended to ``loop_console.log``. Writes a provisional
    status immediately so a racing --ensure does not double-start."""
    now = now or datetime.now(TORONTO_TZ)
    lock_cleanup = _cleanup_loop_writer_lock(attempts=3, sleep_seconds=0.1)
    if lock_cleanup.get("blocked"):
        append_diagnostic({
            "time": now.isoformat(),
            "supervisor": "start_blocked",
            "reason": lock_cleanup.get("reason"),
            "writer_lock": lock_cleanup,
        })
        return {"started": False, "reason": lock_cleanup.get("reason"), "writer_lock": lock_cleanup}
    sidecar_rotations = rotate_sidecar_policy(
        runtime_snapshot_sidecar_rotation_policy(),
        now=now,
    )
    command = _snapshot_loop_command(interval_minutes)
    child = launch_detached(
        command,
        cwd=SNAPSHOT_SUPERVISOR.cwd,
        console_log_path=LOOP_CONSOLE_LOG_PATH,
        popen_fn=subprocess.Popen,
    )
    managed_process = capture_managed_process_identity(child.pid, command)
    write_loop_status({
        "pid": child.pid,
        "started_at": now.isoformat(),
        "last_heartbeat": now.isoformat(),
        "runtime_identity": get_runtime_identity(scope_files="loaded"),
        "managed_process": managed_process,
        "interval_minutes": interval_minutes,
        "iterations": 0,
        "consecutive_errors": 0,
        "last_error": None,
        "last_snapshot_id": None,
        "last_snapshot_written_at": None,
        "paused": PAUSE_FLAG_PATH.exists(),
        "started_by": "supervisor",
    })
    append_diagnostic({
        "time": now.isoformat(),
        "supervisor": "start",
        "pid": child.pid,
        "writer_lock": lock_cleanup,
        "sidecar_rotations": sidecar_rotations,
    })
    return {
        "started": True,
        "pid": child.pid,
        "writer_lock": lock_cleanup,
        "sidecar_rotations": sidecar_rotations,
    }


def acquire_supervisor_lock(path=None):
    return acquire_file_lock(
        path or SUPERVISOR_LOCK_PATH,
        attempts=2,
        stale_after_seconds=120,
    )


def release_supervisor_lock(handle, path=None):
    release_file_lock(handle, path or SUPERVISOR_LOCK_PATH)


def ensure_decision(health_state, pid_alive, *, writer_lock_healthy=True):
    """Pure supervisor decision: what --ensure should do given loop health.

    RUNNING/PAUSED are healthy (paused is operator intent); ERRORING is alive
    and already logging failures, so leave it visible rather than masking it
    with restarts. A stale heartbeat with a live PID is a HUNG process: kill
    and start fresh. Dead or never-started: start.
    """
    if not writer_lock_healthy:
        return "restart" if pid_alive else "start"
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
    handle = acquire_supervisor_lock()
    if handle is None:
        return persist_supervisor_status(
            spec,
            {
                "action": "locked",
                "state": "UNKNOWN",
                "reason": "another snapshot supervisor action is running",
            },
            now=now,
        )
    try:
        status = read_loop_status()
        alive = pid_is_python((status or {}).get("pid"))
        health = loop_health(
            status,
            now,
            interval_minutes,
            pid_alive=alive,
        )
        writer_lock = loop_writer_lock_health(
            spec.status_path,
            status_pid=(status or {}).get("pid"),
            status_pid_alive=alive,
        )
        action = ensure_decision(
            health["state"],
            alive,
            writer_lock_healthy=writer_lock["healthy"],
        )
        if action in {"start", "restart"}:
            if status and not alive:
                restart_cause = health["state"]
            elif status and not writer_lock["healthy"]:
                restart_cause = writer_lock["reason"]
            else:
                restart_cause = health["state"]
        else:
            restart_cause = None
        result = {
            "action": action,
            "state": health["state"],
            "pid": health.get("pid"),
            "restart_cause": restart_cause,
            "writer_lock": writer_lock,
            "runtime_identity_before": (status or {}).get("runtime_identity"),
            "current_runtime_identity": health.get("current_runtime_identity"),
        }
        guard = supervisor_recovery_guard(spec, action, now=now)
        result["recovery_guard"] = guard
        if action in {"start", "restart"} and not guard.get("allowed"):
            result["intended_action"] = action
            result["action"] = guard.get("action")
            result["reason"] = guard.get("reason")
            result["remediation"] = guard.get("remediation")
            event = {"time": now.isoformat(), "supervisor": "ensure", **result}
            if not should_emit_recovery_block_diagnostic(spec, event):
                result["diagnostic_suppressed"] = True
            result = persist_supervisor_status(spec, result, now=now)
            if not result.get("diagnostic_suppressed"):
                append_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
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
                result = persist_supervisor_status(spec, result, now=now)
                append_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
                return result
        if action in {"start", "restart"}:
            result["loop_offsets_before"] = loop_file_offsets(spec)
        if action == "restart":
            result["stop"] = stop_loop(now=now)
            if not managed_stop_allows_start(result["stop"]):
                result["intended_action"] = "restart"
                result["action"] = "restart_blocked"
                result["reason"] = result["stop"].get("reason") or "managed loop stop was not confirmed"
                result = persist_supervisor_status(spec, result, now=now)
                append_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
                return result
            result["malformed_loop_line_quarantine"] = quarantine_malformed_loop_lines(spec)
            result["start"] = start_loop_detached(interval_minutes, now=now)
        elif action == "start":
            result["malformed_loop_line_quarantine"] = quarantine_malformed_loop_lines(spec)
            result["start"] = start_loop_detached(interval_minutes, now=now)
        if action != "noop":
            result["loop_offsets_after"] = loop_file_offsets(spec)
        result = persist_supervisor_status(spec, result, now=now)
        if action != "noop":
            append_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
        return result
    finally:
        release_supervisor_lock(handle)


def _numeric(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


FORECAST_PAYLOAD_STORAGE_SCHEMA_VERSION = "forecast_payload_storage_observability_v0.1"
FORECAST_PAYLOAD_STORAGE_COUNT_FIELDS = (
    "manifest_row_count",
    "created_blob_count",
    "reused_blob_count",
    "logical_referenced_bytes",
    "physical_bytes_written",
    "avoided_bytes",
    "network_fetch_count",
    "network_reuse_count",
    "cross_process_reuse_count",
    "network_wait_timeout_fail_open_count",
)


def _nonnegative_int(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def compact_forecast_payload_storage(value):
    """Project one capture to bounded scalars plus receipt attributions."""
    if not isinstance(value, dict):
        return None
    if value.get("schema_version") != FORECAST_PAYLOAD_STORAGE_SCHEMA_VERSION:
        return None
    result = {"schema_version": FORECAST_PAYLOAD_STORAGE_SCHEMA_VERSION}
    for field in FORECAST_PAYLOAD_STORAGE_COUNT_FIELDS:
        result[field] = _nonnegative_int(value.get(field)) or 0
    raw_attributions = value.get("coordinator_attributions") or []
    if not isinstance(raw_attributions, list):
        raise ValueError("forecast coordinator attributions must be a list")
    try:
        attributions = deduplicate_fanout_coordinator_attributions(
            raw_attributions
        )
        coordinator_totals = fanout_coordinator_attribution_totals(
            attributions
        )
    except ForecastPayloadExtractionIdentityError as exc:
        raise ValueError(str(exc)) from exc
    declared_count = _nonnegative_int(value.get("coordinator_evidence_count"))
    if declared_count not in (None, coordinator_totals["coordinator_evidence_count"]):
        raise ValueError("forecast coordinator evidence count mismatch")
    for field, total_field in (
        ("coordinator_network_fetch_count", "network_fetch_count"),
        ("coordinator_physical_bytes_written", "physical_bytes_written"),
    ):
        declared = _nonnegative_int(value.get(field))
        if declared not in (None, coordinator_totals[total_field]):
            raise ValueError(f"forecast {field} mismatch")
    result["coordinator_attributions"] = attributions
    result["coordinator_evidence_count"] = coordinator_totals[
        "coordinator_evidence_count"
    ]
    result["coordinator_network_fetch_count"] = coordinator_totals[
        "network_fetch_count"
    ]
    result["coordinator_physical_bytes_written"] = coordinator_totals[
        "physical_bytes_written"
    ]
    result["coordinator_attribution_unavailable_count"] = (
        _nonnegative_int(
            value.get("coordinator_attribution_unavailable_count")
        )
        or 0
    )
    result["physical_write_budget_bytes"] = _nonnegative_int(
        value.get("physical_write_budget_bytes")
    )
    budget_status = str(value.get("physical_write_budget_status") or "").upper()
    result["physical_write_budget_status"] = (
        budget_status
        if budget_status in {"PASS", "BLOCK", "NOT_CONFIGURED"}
        else "NOT_CONFIGURED"
    )
    return result


def summarize_forecast_payload_storage(market_results):
    """Aggregate one fleet pass with exact-id coordinator deduplication."""
    rows = []
    for result in (market_results or {}).values():
        if not isinstance(result, dict):
            continue
        row = compact_forecast_payload_storage(result.get("forecast_payload_storage"))
        if row is not None:
            rows.append(row)

    raw_attributions = [
        attribution
        for row in rows
        for attribution in row["coordinator_attributions"]
    ]
    try:
        attributions = deduplicate_fanout_coordinator_attributions(
            raw_attributions
        )
        coordinator_totals = fanout_coordinator_attribution_totals(
            attributions
        )
    except ForecastPayloadExtractionIdentityError as exc:
        raise ValueError(str(exc)) from exc
    summary = {
        "schema_version": FORECAST_PAYLOAD_STORAGE_SCHEMA_VERSION,
        **{
            field: sum(row[field] for row in rows)
            for field in FORECAST_PAYLOAD_STORAGE_COUNT_FIELDS
            if field not in {
                "physical_bytes_written",
                "avoided_bytes",
                "network_fetch_count",
            }
        },
    }
    uncoordinated = {
        "physical_bytes_written": 0,
        "avoided_bytes": 0,
        "network_fetch_count": 0,
    }
    for row in rows:
        child_totals = fanout_coordinator_attribution_totals(
            row["coordinator_attributions"]
        )
        for field in uncoordinated:
            child_value = row[field]
            coordinator_value = child_totals[field]
            if child_value < coordinator_value:
                raise ValueError(
                    f"forecast coordinator {field} exceeds child total"
                )
            uncoordinated[field] += child_value - coordinator_value
    summary["physical_bytes_written"] = (
        uncoordinated["physical_bytes_written"]
        + coordinator_totals["physical_bytes_written"]
    )
    summary["avoided_bytes"] = (
        uncoordinated["avoided_bytes"] + coordinator_totals["avoided_bytes"]
    )
    summary["network_fetch_count"] = (
        uncoordinated["network_fetch_count"]
        + coordinator_totals["network_fetch_count"]
    )
    summary["coordinator_attributions"] = attributions
    summary["coordinator_evidence_count"] = coordinator_totals[
        "coordinator_evidence_count"
    ]
    summary["coordinator_network_fetch_count"] = coordinator_totals[
        "network_fetch_count"
    ]
    summary["coordinator_physical_bytes_written"] = coordinator_totals[
        "physical_bytes_written"
    ]
    summary["coordinator_attribution_unavailable_count"] = sum(
        row["coordinator_attribution_unavailable_count"] for row in rows
    )
    budgets = [row["physical_write_budget_bytes"] for row in rows]
    all_budgets_configured = bool(rows) and all(value is not None for value in budgets)
    summary["physical_write_budget_bytes"] = (
        sum(budgets) if all_budgets_configured else None
    )
    if any(row["physical_write_budget_status"] == "BLOCK" for row in rows):
        budget_status = "BLOCK"
    elif all_budgets_configured:
        budget_status = (
            "PASS"
            if summary["physical_bytes_written"] <= summary["physical_write_budget_bytes"]
            else "BLOCK"
        )
    else:
        budget_status = "NOT_CONFIGURED"
    summary["physical_write_budget_status"] = budget_status
    return summary


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


def _parse_next_due_at(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds_until(target, now):
    if target.tzinfo is not None and now.tzinfo is not None:
        now = now.astimezone(target.tzinfo)
    elif target.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=target.tzinfo)
    elif target.tzinfo is None and now.tzinfo is not None:
        target = target.replace(tzinfo=now.tzinfo)
    return (target - now).total_seconds()


def adaptive_loop_sleep_seconds(market_results, *, now, default_sleep_seconds):
    """Cap loop sleep at the earliest market next_due_at.

    A long iteration can leave tail markets just shy of due at the next loop
    start. If those markets are skipped by due-preflight and we then sleep the
    full nominal interval, their actual capture gap becomes nearly two
    intervals. Sleeping only until the earliest next due keeps per-market
    cadence from drifting after long passes.
    """
    default_sleep_seconds = max(1.0, float(default_sleep_seconds))
    candidates = []
    for result in (market_results or {}).values():
        if not isinstance(result, dict):
            continue
        raw_due_at = result.get("next_due_at")
        parsed = _parse_next_due_at(raw_due_at)
        if parsed is not None:
            candidates.append((parsed, raw_due_at))
    if not candidates:
        return {
            "sleep_seconds": default_sleep_seconds,
            "reason": "interval_elapsed",
            "next_due_at": None,
        }
    next_due, raw_next_due = min(candidates, key=lambda item: item[0])
    due_sleep = max(1.0, _seconds_until(next_due, now))
    if due_sleep < default_sleep_seconds:
        return {
            "sleep_seconds": due_sleep,
            "reason": "next_due_at",
            "next_due_at": raw_next_due,
        }
    return {
        "sleep_seconds": default_sleep_seconds,
        "reason": "interval_elapsed",
        "next_due_at": raw_next_due,
    }


def sleep_until_due_or_triggered_work(
    sleep_seconds,
    *,
    queue_root,
    sleep_fn=time.sleep,
    check_seconds=DEFAULT_TRIGGER_QUEUE_SLEEP_CHECK_SECONDS,
):
    """Keep the normal schedule while making idle sleep interruptible by work."""

    remaining = max(0.0, float(sleep_seconds))
    check = max(0.1, float(check_seconds))
    while remaining > 0.0:
        if has_pending_triggered_snapshot_jobs(queue_root):
            return {"interrupted": True, "remaining_seconds": round(remaining, 3)}
        chunk = min(check, remaining)
        sleep_fn(chunk)
        remaining -= chunk
    return {"interrupted": False, "remaining_seconds": 0.0}


def _isoformat(value):
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def market_cadence_attribution(market_id, result, due_state, *, started_at, completed_at):
    result = result or {}
    due_state = due_state or {}
    raw_next_due_at = due_state.get("next_due_at") or result.get("next_due_at")
    parsed_next_due_at = _parse_next_due_at(raw_next_due_at)
    due_lag_seconds = None
    became_due_during_iteration = False
    if parsed_next_due_at is not None and completed_at is not None:
        lag = -_seconds_until(parsed_next_due_at, completed_at)
        due_lag_seconds = round(max(0.0, lag), 3)
        became_due_during_iteration = bool(
            not due_state.get("due")
            and due_lag_seconds > 0.0
        )
    elapsed_seconds = None
    if started_at is not None and completed_at is not None:
        elapsed_seconds = round(max(0.0, (completed_at - started_at).total_seconds()), 3)
    skipped_reason = result.get("skipped_reason")
    skipped_not_due = skipped_reason == "not_due_preflight"
    return {
        "market_id": market_id,
        "event_slug": result.get("event_slug") or due_state.get("event_slug"),
        "target_date": result.get("target_date") or due_state.get("target_date"),
        "started_at": _isoformat(started_at),
        "completed_at": _isoformat(completed_at),
        "elapsed_seconds": elapsed_seconds,
        "written": bool(result.get("written")),
        "snapshot_id": result.get("snapshot_id"),
        "error": result.get("error"),
        "skipped_reason": skipped_reason,
        "skipped_not_due": skipped_not_due,
        "due_at_loop_start": bool(due_state.get("due")),
        "last_snapshot_at_loop_start": due_state.get("last_snapshot_at"),
        "next_due_at_loop_start": raw_next_due_at,
        "became_due_during_iteration": became_due_during_iteration,
        "skipped_after_due_at_completion": bool(skipped_not_due and became_due_during_iteration),
        "due_lag_seconds_at_completion": due_lag_seconds,
    }


def summarize_market_cadence_attribution(market_attribution, *, iteration_elapsed_minutes=None):
    rows = dict(market_attribution or {})
    skipped_after_due = [
        market_id for market_id, row in rows.items()
        if row.get("skipped_after_due_at_completion")
    ]
    skipped_not_due = [
        market_id for market_id, row in rows.items()
        if row.get("skipped_not_due")
    ]
    due_lags = [
        float(row.get("due_lag_seconds_at_completion") or 0.0)
        for row in rows.values()
        if row.get("due_lag_seconds_at_completion") is not None
    ]
    return {
        "schema_version": "snapshot_cadence_attribution_v0.1",
        "iteration_elapsed_minutes": (
            round(float(iteration_elapsed_minutes), 3)
            if iteration_elapsed_minutes is not None else None
        ),
        "market_count": len(rows),
        "written_count": sum(1 for row in rows.values() if row.get("written")),
        "error_count": sum(1 for row in rows.values() if row.get("error")),
        "skipped_not_due_count": len(skipped_not_due),
        "became_due_during_iteration_count": sum(
            1 for row in rows.values()
            if row.get("became_due_during_iteration")
        ),
        "skipped_after_due_count": len(skipped_after_due),
        "skipped_after_due_markets": skipped_after_due,
        "max_due_lag_seconds_at_completion": round(max(due_lags), 3) if due_lags else None,
        "markets": rows,
    }


def finalize_iteration_error_state(
    status,
    market_results,
    *,
    expected_market_ids,
    completed_at,
):
    """Latch only the latest fully completed capture iteration's errors.

    Progress heartbeats intentionally retain the prior completed iteration's
    error state.  Once every registered market has a result, an error-free
    iteration clears the current latch; historical recovery remains visible
    through the completed/clean iteration markers.
    """

    expected = [str(market_id) for market_id in expected_market_ids]
    errors = {
        str(market_id): result.get("error")
        for market_id, result in market_results.items()
        if result.get("error")
    }
    for market_id in expected:
        if market_id not in market_results:
            errors[market_id] = "capture_result_missing: no market result"

    completed_iso = completed_at.isoformat()
    iteration = int(status.get("iterations") or 0)
    status["last_completed_iteration"] = iteration
    status["last_completed_iteration_at"] = completed_iso
    status["last_iteration_error_count"] = len(errors)
    if errors:
        status["last_iteration_outcome"] = "error"
        status["consecutive_errors"] = int(status.get("consecutive_errors") or 0) + 1
        status["last_error"] = "; ".join(
            f"{market_id}: {detail}" for market_id, detail in errors.items()
        )
    else:
        status["last_iteration_outcome"] = "clean"
        status["last_clean_iteration"] = iteration
        status["last_clean_iteration_at"] = completed_iso
        status["consecutive_errors"] = 0
        status["last_error"] = None
    return errors


def run_loop(
    force=False,
    interval_minutes=10.0,
    max_iterations=None,
    capture_fn=None,
    sleep_fn=time.sleep,
    now_fn=None,
    target_date=None,
    capture_workers=DEFAULT_CAPTURE_WORKERS,
    capture_fleet_budget_seconds=DEFAULT_FLEET_BUDGET_SECONDS,
    capture_timeout_seconds=DEFAULT_MARKET_TIMEOUT_SECONDS,
    capture_child_working_set_max_mb=DEFAULT_CHILD_WORKING_SET_MAX_MB,
    capture_host_reserve_mb=DEFAULT_CAPTURE_HOST_RESERVE_MB,
    available_memory_fn=available_memory_bytes,
    trigger_queue_root=None,
    trigger_queue_sleep_check_seconds=DEFAULT_TRIGGER_QUEUE_SLEEP_CHECK_SECONDS,
):
    """Crash-proof managed snapshot loop: a capture failure is logged and the
    loop continues, so collection never silently dies on a transient error. A
    heartbeat + diagnostics record is written every iteration."""
    now_fn = now_fn or (lambda: datetime.now(TORONTO_TZ))
    production_capture = capture_fn is None
    preflight_due_enabled = production_capture
    capture_fn = capture_fn or capture_snapshot
    target_date = ensure_date(target_date) if target_date is not None else None
    managed_command = _snapshot_loop_command(interval_minutes)
    managed_process = capture_managed_process_identity(os.getpid(), managed_command)
    writer_lock = acquire_writer_lock(
        LOOP_STATUS_PATH,
        owner={
            "loop": SNAPSHOT_SUPERVISOR.name,
            "module": SNAPSHOT_SUPERVISOR.module,
            "managed_process": managed_process,
        },
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
    trigger_queue_root = Path(trigger_queue_root or LOOP_STATUS_PATH.parent / "triggered_snapshot_queue")
    trigger_queue_recovery = recover_inflight_jobs(trigger_queue_root)
    sleep_inhibitor = keep_system_awake("weather snapshot capture loop")
    power_request = sleep_inhibitor.start()
    status = {
        "pid": os.getpid(),
        "started_at": now_fn().isoformat(),
        "runtime_identity": PROCESS_RUNTIME_IDENTITY,
        "managed_process": managed_process,
        "power_request": power_request,
        "interval_minutes": interval_minutes,
        "iterations": 0,
        "consecutive_errors": 0,
        "last_error": None,
        "last_completed_iteration": None,
        "last_completed_iteration_at": None,
        "last_iteration_error_count": None,
        "last_iteration_outcome": None,
        "last_clean_iteration": None,
        "last_clean_iteration_at": None,
        "last_snapshot_id": None,
        "last_snapshot_written_at": None,
        "paused": False,
        "capture_execution": {
            "mode": (
                "isolated_subprocess_batch"
                if production_capture
                else "inline_test_or_override"
            ),
            "worker_count": max(1, int(capture_workers)),
            "fleet_budget_seconds": float(capture_fleet_budget_seconds),
            "market_timeout_seconds": float(capture_timeout_seconds),
            "child_working_set_max_mb": int(capture_child_working_set_max_mb),
            "host_reserve_mb": int(capture_host_reserve_mb),
        },
        "trigger_queue": {
            **triggered_snapshot_queue_status(trigger_queue_root),
            "sleep_check_seconds": float(trigger_queue_sleep_check_seconds),
            "startup_recovery": trigger_queue_recovery,
        },
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
                # isolated so it never kills the loop or the other markets. Normal
                # production passes use bounded child processes. If this parent is
                # temporarily serving its already-loaded code during the re-adoption
                # debounce, stay inline: a newly imported child would have a different
                # runtime fingerprint and must not write into the old-runtime segment.
                market_results = {}
                specs = list(all_specs())
                if preflight_due_enabled:
                    ordered_rows = ordered_snapshot_specs(specs, target_date=target_date, now=now)
                else:
                    ordered_rows = [(spec, None) for spec in specs]
                market_cadence = {}
                market_execution = {}
                parent_runtime_fingerprint = str(
                    (status.get("runtime_identity") or {}).get("source_fingerprint") or ""
                )
                use_isolated_batch = bool(
                    production_capture
                    and not stale_code
                    and parent_runtime_fingerprint
                )
                status["capture_execution"]["active_mode"] = (
                    "isolated_subprocess_batch" if use_isolated_batch else "inline"
                )
                status["capture_execution"]["inline_reason"] = (
                    "runtime_re_adoption_debounce"
                    if production_capture and stale_code
                    else (
                        "runtime_fingerprint_missing"
                        if production_capture and not parent_runtime_fingerprint
                        else ("capture_override" if not production_capture else None)
                    )
                )
                if use_isolated_batch:
                    market_invariant_fetch_scope = (
                        f"snapshot-fleet:{os.getpid()}:{status['started_at']}:"
                        f"{status['iterations']}"
                    )
                    due_requests = []
                    skipped_records = {}
                    claimed_trigger_jobs = claim_triggered_snapshot_jobs(
                        trigger_queue_root,
                        market_ids=[spec.id for spec in specs],
                        limit=len(specs),
                    )
                    trigger_jobs_by_market = {
                        job["market_id"]: job for job in claimed_trigger_jobs
                    }
                    for spec, due_state in ordered_rows:
                        trigger_job = trigger_jobs_by_market.get(spec.id)
                        if trigger_job is not None:
                            due_requests.append({
                                "market_id": spec.id,
                                "force": True,
                                "target_date": trigger_job.get("target_date"),
                                "cadence": "triggered",
                                "trigger_context": trigger_job.get("trigger_context") or {},
                                "trigger_work_id": trigger_job.get("work_id"),
                            })
                            continue
                        if not force and due_state is not None and not due_state.get("due"):
                            skipped_records[spec.id] = {
                                "market_id": spec.id,
                                "started_at": now,
                                "result": {
                                    "written": False,
                                    "snapshot_id": None,
                                    "skipped": True,
                                    "skipped_reason": "not_due_preflight",
                                    "market_id": spec.id,
                                    "event_slug": due_state.get("event_slug"),
                                    "target_date": due_state.get("target_date"),
                                    "next_due_at": due_state.get("next_due_at"),
                                },
                                "execution": {
                                    "mode": "preflight",
                                    "not_started": True,
                                    "reason": "not_due_preflight",
                                },
                            }
                            continue
                        due_requests.append({
                            "market_id": spec.id,
                            "force": bool(force),
                            "target_date": target_date.isoformat() if target_date else None,
                            "cadence": "scheduled",
                        })

                    def capture_progress(progress):
                        progress_now = now_fn()
                        active_markets = list(progress.get("active_markets") or [])
                        status["last_heartbeat"] = progress_now.isoformat()
                        status["markets_in_progress"] = active_markets
                        status["last_market_in_progress"] = (
                            active_markets[0] if active_markets else None
                        )
                        status["last_capture_batch_progress"] = {
                            **progress,
                            "updated_at": progress_now.isoformat(),
                        }
                        write_loop_status(status)

                    def isolated_runner(request, timeout_seconds):
                        return run_isolated_capture(
                            request,
                            timeout_seconds,
                            expected_runtime_fingerprint=parent_runtime_fingerprint,
                            cwd=REPO_ROOT,
                            working_set_max_mb=capture_child_working_set_max_mb,
                            shared_source_cooldown_path=SOURCE_FAMILY_COOLDOWN_PATH,
                            shared_forecast_payload_cas_root=(
                                SHARED_FORECAST_PAYLOAD_CAS_ROOT
                            ),
                            market_invariant_fetch_scope=(
                                market_invariant_fetch_scope
                            ),
                            now_fn=now_fn,
                        )

                    try:
                        if due_requests:
                            try:
                                available_memory = available_memory_fn()
                            except Exception:  # noqa: BLE001 - fail closed below
                                available_memory = None
                            worker_admission = capture_worker_admission(
                                capture_workers,
                                child_memory_max_mb=capture_child_working_set_max_mb,
                                host_reserve_mb=capture_host_reserve_mb,
                                available_memory_bytes=available_memory,
                            )
                        else:
                            worker_admission = {
                                "status": "NOT_REQUIRED",
                                "requested_worker_count": max(
                                    1, int(capture_workers)
                                ),
                                "admitted_worker_count": 0,
                                "reason": "no_due_markets",
                            }
                        status["capture_execution"]["worker_admission"] = (
                            worker_admission
                        )
                        admitted_workers = int(
                            worker_admission["admitted_worker_count"]
                        )
                        if due_requests and not admitted_workers:
                            detail = (
                                f"{worker_admission['reason']}: "
                                f"available_bytes={worker_admission['available_memory_bytes']}, "
                                "required_for_one_worker_bytes="
                                f"{worker_admission['required_for_one_worker_bytes']}"
                            )
                            blocked_at = now_fn()
                            capture_batch = {
                                "records": [
                                    {
                                        "market_id": request["market_id"],
                                        "started_at": blocked_at,
                                        "completed_at": blocked_at,
                                        "result": {
                                            "written": False,
                                            "error": (
                                                "capture_host_memory_admission: "
                                                f"{detail}"
                                            ),
                                            "capture_status": (
                                                "capture_host_memory_admission"
                                            ),
                                            "retryable": True,
                                        },
                                        "execution": {
                                            "mode": "host_memory_admission",
                                            "worker_admission": worker_admission,
                                        },
                                    }
                                    for request in due_requests
                                ],
                                "summary": {
                                    "mode": "isolated_subprocess_batch",
                                    "request_count": len(due_requests),
                                    "worker_count": 0,
                                    "worker_admission": worker_admission,
                                },
                            }
                        else:
                            capture_batch = run_bounded_capture_batch(
                                due_requests,
                                worker_count=max(1, admitted_workers),
                                fleet_budget_seconds=capture_fleet_budget_seconds,
                                market_timeout_seconds=capture_timeout_seconds,
                                runner_fn=isolated_runner,
                                progress_fn=capture_progress,
                                now_fn=now_fn,
                            )
                            capture_batch.setdefault("summary", {})[
                                "worker_admission"
                            ] = worker_admission
                    except Exception as exc:  # noqa: BLE001 - preserve loop liveness
                        failed_at = now_fn()
                        detail = f"{type(exc).__name__}: {exc}"
                        capture_batch = {
                            "records": [
                                {
                                    "market_id": request["market_id"],
                                    "started_at": failed_at,
                                    "completed_at": failed_at,
                                    "result": {
                                        "written": False,
                                        "error": f"capture_batch_error: {detail}",
                                        "capture_status": "capture_batch_error",
                                        "retryable": True,
                                    },
                                    "execution": {
                                        "mode": "isolated_subprocess_batch",
                                        "batch_error": detail,
                                    },
                                }
                                for request in due_requests
                            ],
                            "summary": {
                                "mode": "isolated_subprocess_batch",
                                "request_count": len(due_requests),
                                "error": detail,
                            },
                        }
                    batch_records_by_market = {
                        record.get("market_id"): record
                        for record in capture_batch.get("records") or []
                    }
                    trigger_queue_results = {}
                    for job in claimed_trigger_jobs:
                        record = batch_records_by_market.get(job.get("market_id")) or {}
                        result = record.get("result") or {
                            "written": False,
                            "error": "triggered_capture_result_missing",
                            "capture_status": "triggered_capture_result_missing",
                            "retryable": True,
                        }
                        result["trigger_work_id"] = job.get("work_id")
                        if result.get("retryable") is True:
                            receipt = retry_triggered_snapshot_job(
                                job,
                                result,
                                queue_root=trigger_queue_root,
                                now=now_fn(),
                            )
                        else:
                            receipt = complete_triggered_snapshot_job(
                                job,
                                result,
                                record.get("execution") or {},
                                queue_root=trigger_queue_root,
                                now=now_fn(),
                            )
                        trigger_queue_results[job["work_id"]] = receipt
                    status["last_capture_batch"] = capture_batch.get("summary")
                    status["last_trigger_queue_results"] = trigger_queue_results
                    status["trigger_queue"] = {
                        **triggered_snapshot_queue_status(trigger_queue_root),
                        "sleep_check_seconds": float(trigger_queue_sleep_check_seconds),
                        "claimed_count": len(claimed_trigger_jobs),
                    }
                    completed_records = {
                        record["market_id"]: record
                        for record in capture_batch.get("records") or []
                    }
                    pass_completed_at = now_fn()
                    latest_written = None
                    for spec, due_state in ordered_rows:
                        record = completed_records.get(spec.id) or skipped_records.get(spec.id)
                        if record is None:
                            missing_at = now_fn()
                            record = {
                                "market_id": spec.id,
                                "started_at": missing_at,
                                "completed_at": missing_at,
                                "result": {
                                    "written": False,
                                    "error": "capture_batch_result_missing: no market result",
                                    "capture_status": "capture_batch_result_missing",
                                    "retryable": True,
                                },
                                "execution": {
                                    "mode": "isolated_subprocess_batch",
                                    "result_missing": True,
                                },
                            }
                        if "completed_at" not in record:
                            # Match the old serial attribution: a market that was
                            # not due at loop start can become due while other
                            # captures run, and must be visible as skipped drift.
                            record["completed_at"] = pass_completed_at
                        result = record.get("result") or {}
                        market_results[spec.id] = result
                        market_execution[spec.id] = record.get("execution") or {}
                        market_cadence[spec.id] = market_cadence_attribution(
                            spec.id,
                            result,
                            due_state,
                            started_at=record.get("started_at"),
                            completed_at=record.get("completed_at"),
                        )
                        if result.get("written") and (
                            latest_written is None
                            or record.get("completed_at") > latest_written.get("completed_at")
                        ):
                            latest_written = record
                    if latest_written is not None:
                        status["last_snapshot_id"] = (
                            latest_written.get("result") or {}
                        ).get("snapshot_id")
                        status["last_snapshot_written_at"] = latest_written[
                            "completed_at"
                        ].isoformat()
                    status["markets_in_progress"] = []
                else:
                    for spec, due_state in ordered_rows:
                        market_started = now_fn()
                        try:
                            status["last_market_in_progress"] = spec.id
                            status["markets_in_progress"] = [spec.id]
                            status["last_heartbeat"] = market_started.isoformat()
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
                                result = capture_fn(
                                    force=force,
                                    market_id=spec.id,
                                    target_date=target_date,
                                )
                            market_results[spec.id] = result
                            progress_now = now_fn()
                            status["last_heartbeat"] = progress_now.isoformat()
                            if result.get("written"):
                                status["last_snapshot_id"] = result.get("snapshot_id")
                                status["last_snapshot_written_at"] = progress_now.isoformat()
                        except Exception as exc:  # noqa: BLE001 - keep the loop alive
                            market_results[spec.id] = {
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                            progress_now = now_fn()
                            status["last_heartbeat"] = progress_now.isoformat()
                        market_execution[spec.id] = {
                            "mode": "inline",
                            "runtime_re_adoption_debounce": bool(stale_code),
                        }
                        market_cadence[spec.id] = market_cadence_attribution(
                            spec.id,
                            market_results.get(spec.id) or {},
                            due_state,
                            started_at=market_started,
                            completed_at=progress_now,
                        )
                        status["last_market_results"] = {
                            mid: {
                                "written": bool(result.get("written")),
                                "snapshot_id": result.get("snapshot_id"),
                                "error": result.get("error"),
                                "skipped_reason": result.get("skipped_reason"),
                                "next_due_at": result.get("next_due_at"),
                                "execution": market_execution.get(mid),
                                "cadence": market_cadence.get(mid),
                                "forecast_payload_storage": compact_forecast_payload_storage(
                                    result.get("forecast_payload_storage")
                                ),
                            }
                            for mid, result in market_results.items()
                        }
                        status["forecast_payload_storage"] = summarize_forecast_payload_storage(
                            market_results
                        )
                        write_loop_status(status)
                    status["markets_in_progress"] = []

                status["last_market_results"] = {
                    mid: {
                        "written": bool(result.get("written")),
                        "snapshot_id": result.get("snapshot_id"),
                        "error": result.get("error"),
                        "skipped_reason": result.get("skipped_reason"),
                        "next_due_at": result.get("next_due_at"),
                        "execution": market_execution.get(mid),
                        "cadence": market_cadence.get(mid),
                        "forecast_payload_storage": compact_forecast_payload_storage(
                            result.get("forecast_payload_storage")
                        ),
                    }
                    for mid, result in market_results.items()
                }
                status["forecast_payload_storage"] = summarize_forecast_payload_storage(
                    market_results
                )
                iteration_completed_at = now_fn()
                finalize_iteration_error_state(
                    status,
                    market_results,
                    expected_market_ids=(spec.id for spec in specs),
                    completed_at=iteration_completed_at,
                )
                status["last_market_in_progress"] = None
                elapsed_minutes = (
                    iteration_completed_at - iteration_started
                ).total_seconds() / 60.0
                _record_recent_elapsed(status, elapsed_minutes)
                cadence_attribution = summarize_market_cadence_attribution(
                    market_cadence,
                    iteration_elapsed_minutes=elapsed_minutes,
                )
                status["last_cadence_attribution"] = cadence_attribution
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
                    "cadence_attribution": cadence_attribution,
                    "forecast_payload_storage": status["forecast_payload_storage"],
                })
                print(json.dumps({
                    "time": now.isoformat(),
                    "markets": {mid: {"written": bool(r.get("written")), "snapshot_id": r.get("snapshot_id")} for mid, r in market_results.items()},
                }, sort_keys=True), flush=True)
            sleep_now = now_fn()
            elapsed_seconds = (sleep_now - iteration_started).total_seconds()
            default_sleep_seconds = max(1.0, interval_minutes * 60.0 - elapsed_seconds)
            sleep_plan = adaptive_loop_sleep_seconds(
                market_results if not status["paused"] else {},
                now=sleep_now,
                default_sleep_seconds=default_sleep_seconds,
            )
            sleep_seconds = sleep_plan["sleep_seconds"]
            status["last_sleep_seconds"] = round(sleep_seconds, 1)
            status["last_sleep_reason"] = sleep_plan["reason"]
            status["next_due_at"] = sleep_plan["next_due_at"]
            write_loop_status(status)
            if max_iterations is not None and status["iterations"] >= max_iterations:
                return status
            if production_capture and trigger_queue_sleep_check_seconds is not None:
                status["last_trigger_queue_sleep"] = sleep_until_due_or_triggered_work(
                    sleep_seconds,
                    queue_root=trigger_queue_root,
                    sleep_fn=sleep_fn,
                    check_seconds=trigger_queue_sleep_check_seconds,
                )
            else:
                sleep_fn(sleep_seconds)
    finally:
        sleep_inhibitor.stop()
        release_writer_lock(writer_lock)


def capture_runtime_fingerprint_gate(expected_fingerprint, identity=None):
    """Fail closed when an isolated child is not the parent's code identity."""

    identity = PROCESS_RUNTIME_IDENTITY if identity is None else identity
    actual = str((identity or {}).get("source_fingerprint") or "")
    expected = str(expected_fingerprint or "")
    if not expected:
        return {"ok": True, "expected": None, "actual": actual or None}
    return {
        "ok": bool(actual and actual == expected),
        "expected": expected,
        "actual": actual or None,
        "reason": (
            None
            if actual and actual == expected
            else "isolated capture runtime fingerprint differs from parent loop"
        ),
    }


def emit_capture_result(result, result_json=None):
    if result_json:
        atomic_write_json(Path(result_json), result)
        return
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


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
        "--trigger-queue-root",
        default=str(DEFAULT_TRIGGER_QUEUE_ROOT),
        help="Durable observation-trigger work spool consumed by the managed loop.",
    )
    parser.add_argument(
        "--trigger-queue-sleep-check-seconds",
        type=float,
        default=DEFAULT_TRIGGER_QUEUE_SLEEP_CHECK_SECONDS,
        help="Idle-sleep check interval for newly queued triggered snapshots.",
    )
    parser.add_argument(
        "--capture-workers",
        type=int,
        default=DEFAULT_CAPTURE_WORKERS,
        help=(
            "Maximum concurrent isolated market captures in the managed loop "
            f"(default: {DEFAULT_CAPTURE_WORKERS})."
        ),
    )
    parser.add_argument(
        "--capture-fleet-budget-seconds",
        type=float,
        default=DEFAULT_FLEET_BUDGET_SECONDS,
        help="Hard admission/timeout budget for one due-market fleet pass.",
    )
    parser.add_argument(
        "--capture-timeout-seconds",
        type=float,
        default=DEFAULT_MARKET_TIMEOUT_SECONDS,
        help="Maximum runtime for one isolated market capture (may tighten to fit fleet budget).",
    )
    parser.add_argument(
        "--capture-child-working-set-max-mb",
        type=int,
        default=DEFAULT_CHILD_WORKING_SET_MAX_MB,
        help=(
            "Per-child process-tree working-set and private-commit ceiling for "
            "an isolated market capture "
            f"(default: {DEFAULT_CHILD_WORKING_SET_MAX_MB} MiB)."
        ),
    )
    parser.add_argument(
        "--capture-host-reserve-mb",
        type=int,
        default=DEFAULT_CAPTURE_HOST_RESERVE_MB,
        help=(
            "Physical memory that must remain available after admitting full "
            "child ceilings "
            f"(default: {DEFAULT_CAPTURE_HOST_RESERVE_MB} MiB)."
        ),
    )
    parser.add_argument("--result-json", default="", help=argparse.SUPPRESS)
    parser.add_argument(
        "--cadence",
        choices=("scheduled", "triggered"),
        default="scheduled",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--trigger-context-file", default="", help=argparse.SUPPRESS)
    parser.add_argument(
        "--expected-runtime-fingerprint",
        default="",
        help=argparse.SUPPRESS,
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
            "Rebuild forecast_payloads_long.csv/jsonl "
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
    parser.add_argument(
        "--retain-raw-forecast-payloads",
        action="store_true",
        help=(
            "Opt in to writing raw forecast payload JSON files during forecast-payload backfill. "
            f"By default they are omitted; {FORECAST_RAW_PAYLOAD_RETENTION_ENV}=1 also enables this."
        ),
    )
    args = parser.parse_args()
    target_date = ensure_date(args.target_date) if args.target_date else None
    trigger_context = None
    if args.trigger_context_file:
        trigger_context = json.loads(Path(args.trigger_context_file).read_text(encoding="utf-8"))

    if args.status:
        health = loop_health(read_loop_status(), datetime.now(TORONTO_TZ), args.interval_minutes)
        health["supervisor"] = read_supervisor_status(runtime_supervisor_spec())
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
        stop = stop_loop()
        result = {"stop": stop}
        if managed_stop_allows_start(stop):
            result["start"] = start_loop_detached(args.interval_minutes)
        else:
            result["start"] = {"started": False, "reason": "managed stop was not confirmed"}
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
        result = ensure_loop(args.interval_minutes)
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return int(result.get("exit_code", 1))
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
            backfill_forecast_payloads(
                args.snapshots_root,
                overwrite=args.overwrite_forecast_payloads,
                retain_raw_payloads=args.retain_raw_forecast_payloads or None,
            ),
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
        runtime_gate = capture_runtime_fingerprint_gate(args.expected_runtime_fingerprint)
        if runtime_gate.get("ok"):
            result = capture_snapshot(
                force=args.force,
                market_id=args.market,
                cadence=args.cadence,
                trigger_context=trigger_context,
                target_date=target_date,
            )
        else:
            result = {
                "written": False,
                "blocked": True,
                "status": "BLOCK",
                "error": runtime_gate.get("reason"),
                "runtime_fingerprint_gate": runtime_gate,
                "market_id": args.market,
                "target_date": target_date.isoformat() if target_date else None,
            }
        emit_capture_result(result, args.result_json)
        return

    configure_json_console_logging()
    run_loop(
        force=args.force,
        interval_minutes=args.interval_minutes,
        target_date=target_date,
        capture_workers=args.capture_workers,
        capture_fleet_budget_seconds=args.capture_fleet_budget_seconds,
        capture_timeout_seconds=args.capture_timeout_seconds,
        capture_child_working_set_max_mb=args.capture_child_working_set_max_mb,
        capture_host_reserve_mb=args.capture_host_reserve_mb,
        trigger_queue_root=args.trigger_queue_root,
        trigger_queue_sleep_check_seconds=args.trigger_queue_sleep_check_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
