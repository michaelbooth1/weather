"""Fast observation-triggered recompute path.

This loop watches only settlement-relevant observation feeds. When a live source
changes enough to matter for a weather market, it forces a normal snapshot write
through ``snapshot_tracker.capture_snapshot`` and tags that evidence as
``snapshot_cadence=triggered`` with the source-change reason.
"""
from __future__ import annotations

from weather.operations.windows_silent import apply_windows_silent_subprocess_defaults

apply_windows_silent_subprocess_defaults()

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.collection.snapshot_tracker import capture_snapshot
from weather.io import read_jsonl as io_read_jsonl
from weather.market.market_config import config_for_date, date_from_event_slug
from weather.market.live_observation_normalization import update_monotonic_high_ledger
from weather.market.market_registry import DEFAULT_MARKET_ID, all_specs, spec_for_id, spec_for_slug
from weather.model.feature_store import (
    row_air_temp_native,
    row_max_native,
    row_max_since_7am_native,
    row_same_day_max_native,
    row_temp_native,
)
from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import REPO_ROOT, data_path
from weather.operations.power import keep_system_awake
from weather.operations.runtime_identity import get_runtime_identity
from weather.operations.supervisor import (
    SupervisorSpec,
    acquire_file_lock,
    acquire_writer_lock,
    age_seconds as supervisor_age_seconds,
    append_jsonl as supervisor_append_jsonl,
    attach_status_writer,
    atomic_write_json,
    launch_detached,
    pid_is_python,
    read_writer_lock,
    read_json_file,
    release_file_lock,
    release_writer_lock,
    terminate_python_pid,
)
from weather.schema_registry import schema_version
from weather.sources.asos_one_minute import (
    DEFAULT_ROOT as DEFAULT_ASOS_1MIN_ROOT,
    compare_daily_summary_to_wu_print,
    load_daily_summary,
)
from weather.time import parse_datetime, utc_now as shared_utc_now
from weather.units import round_half_up, to_float


SCHEMA_VERSION = schema_version("observation_trigger")
REPLAY_SCHEMA_VERSION = schema_version("observation_trigger_replay")
DEFAULT_INTERVAL_SECONDS = 60.0
DEFAULT_FAST_STALE_SECONDS = 180.0
DEFAULT_SUPPORT_MARGIN = 0.5
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
STATUS_PATH = DEFAULT_SNAPSHOTS_ROOT / "observation_trigger_status.json"
EVENTS_PATH = DEFAULT_SNAPSHOTS_ROOT / "observation_triggers.jsonl"
DIAGNOSTICS_PATH = DEFAULT_SNAPSHOTS_ROOT / "observation_trigger_diagnostics.jsonl"
CONSOLE_LOG_PATH = DEFAULT_SNAPSHOTS_ROOT / "observation_trigger_console.log"
PAUSE_FLAG_PATH = DEFAULT_SNAPSHOTS_ROOT / "observation_trigger_pause.flag"
SUPERVISOR_LOCK_PATH = DEFAULT_SNAPSHOTS_ROOT / "observation_trigger_supervisor.lock"
DEFAULT_REPLAY_JSON = DEFAULT_BACKTEST_ROOT / "observation_trigger_replay.json"
DEFAULT_REPLAY_REPORT = DEFAULT_BACKTEST_ROOT / "observation_trigger_replay_report.md"
DEFAULT_TRIGGER_POLICY_MIN_ROWS = 30
DEFAULT_TRIGGER_POLICY_MAX_DELTA = 0.0
TASK_NAME = "WeatherObservationTriggerSupervisor"
OBSERVATION_SUPERVISOR = SupervisorSpec(
    name="observation_trigger",
    module="weather.operations.observation_trigger",
    status_path=STATUS_PATH,
    diagnostics_path=DIAGNOSTICS_PATH,
    console_log_path=CONSOLE_LOG_PATH,
    cwd=REPO_ROOT,
    pause_flag_path=PAUSE_FLAG_PATH,
    lock_path=SUPERVISOR_LOCK_PATH,
    tolerated_states=("RUNNING", "PAUSED", "DEGRADED", "ERRORING"),
    status_schema_fields=(
        "schema_version",
        "runner",
        "pid",
        "market",
        "started_at",
        "last_heartbeat",
        "interval_seconds",
        "consecutive_errors",
        "last_error",
        "paused",
    ),
)

OBSERVATION_SOURCES = ("wu_history", "wu_current", "metar", "eccc_swob")


def utc_now():
    return shared_utc_now()


def write_json(path, payload):
    return atomic_write_json(path, payload, trailing_newline=True)


def read_json(path):
    return read_json_file(path)


def append_jsonl(path, payload):
    return supervisor_append_jsonl(path, payload)


def read_status(path=None):
    return read_json(path or STATUS_PATH)


def write_status(status, path=None):
    return write_json(path or STATUS_PATH, status)


def append_diagnostic(record, path=None):
    append_jsonl(path or DIAGNOSTICS_PATH, record)


def to_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_dt(value):
    return parse_datetime(value, default_tz=timezone.utc)


def age_seconds(now, iso_value):
    return supervisor_age_seconds(now, iso_value, default_tz=timezone.utc)


def market_ids(value):
    if value == "all":
        return [spec.id for spec in all_specs()]
    return [value or DEFAULT_MARKET_ID]


def source_item(sources, name):
    item = (sources or {}).get(name) or {}
    data = item.get("data") if isinstance(item, dict) else {}
    return item if isinstance(item, dict) else {}, data if isinstance(data, dict) else {}


def observation_fetchers(model_client):
    fetchers = {
        "wu_history": model_client.fetch_wu_history,
        "wu_current": model_client.fetch_wu_current,
        "metar": model_client.fetch_metar,
        "eccc_swob": model_client.fetch_eccc_swob,
    }
    return {
        name: fetchers[name]
        for name in model_client.spec.sources
        if name in fetchers
    }


def fetch_observation_sources(model_client):
    """Fetch only low-cost observation sources, not forecast ensembles."""
    return model_client.blend_with_last_good(
        model_client.fetch_source_group(observation_fetchers(model_client))
    )


def source_status(item):
    return {
        "ok": item.get("ok"),
        "status": item.get("status"),
        "stale": item.get("stale"),
        "fetched_at": item.get("fetched_at"),
        "cache_age_minutes": item.get("cache_age_minutes"),
        "ttl_minutes": item.get("ttl_minutes"),
        "error": item.get("error"),
    }


def observation_state_from_sources(model_client, sources, captured_at=None, event_slug=None):
    captured_at = captured_at or datetime.now(model_client.spec.tz)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=model_client.spec.tz)
    config = config_for_date(model_client.target_date, model_client.market_id)
    event_slug = event_slug or config.event_slug

    history_item, history = source_item(sources, "wu_history")
    current_item, current = source_item(sources, "wu_current")
    metar_item, metar = source_item(sources, "metar")
    swob_item, swob = source_item(sources, "eccc_swob")
    latest_history = history.get("latest") or {}
    latest_swob = swob.get("latest") or {}

    values = {
        "wu_history_high": row_max_native(history),
        "wu_history_latest_value": row_temp_native(latest_history),
        "wu_history_latest_time": latest_history.get("datetime") or latest_history.get("time"),
        "wu_history_row_count": len(history.get("rows") or []),
        "wu_current_temp": row_temp_native(current),
        "wu_current_max_since_7am": row_max_since_7am_native(current),
        "wu_current_time": current.get("time"),
        "metar_temp": row_temp_native(metar),
        "metar_report_time": metar.get("report_time"),
        "eccc_swob_max": row_same_day_max_native(swob),
        "eccc_swob_latest_temp": row_air_temp_native(latest_swob),
        "eccc_swob_latest_time": latest_swob.get("local_time") or latest_swob.get("time"),
    }
    values["max_live_observation"] = max(
        [
            value for value in (
                values.get("wu_current_temp"),
                values.get("wu_current_max_since_7am"),
                values.get("metar_temp"),
                values.get("eccc_swob_max"),
                values.get("eccc_swob_latest_temp"),
            )
            if value is not None
        ],
        default=None,
    )
    state = {
        "schema_version": SCHEMA_VERSION,
        "market_id": model_client.market_id,
        "event_slug": event_slug,
        "target_date": model_client.target_date.isoformat(),
        "unit": model_client.spec.unit,
        "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
        "captured_at_local": captured_at.astimezone(model_client.spec.tz).isoformat(),
        "values": values,
        "source_status": {
            name: source_status(item)
            for name, item in sorted((sources or {}).items())
            if name in OBSERVATION_SOURCES
        },
    }
    ledger = update_monotonic_high_ledger(current_observation=state)
    state["settlement_normalization"] = ledger
    values.update({
        "raw_current_high": ledger.get("raw_current_high"),
        "raw_current_high_bucket": ledger.get("raw_current_high_bucket"),
        "settlement_current_high": ledger.get("settlement_current_high"),
        "high_source": ledger.get("high_source"),
        "revision_state": ledger.get("revision_state"),
        "settlement_bin_key": ledger.get("settlement_bin_key"),
    })
    return state


def fetch_market_observation_state(market_id, now=None):
    spec = spec_for_id(market_id)
    local_now = (now or datetime.now(spec.tz)).astimezone(spec.tz)
    config = config_for_date(local_now.date(), market_id)
    model_client = TorontoHighTempModel(target_date=config.target_date, market_id=market_id)
    sources = fetch_observation_sources(model_client)
    return observation_state_from_sources(
        model_client,
        sources,
        captured_at=local_now,
        event_slug=config.event_slug,
    )


def fresh_source_status(state, source):
    item = ((state or {}).get("source_status") or {}).get(source) or {}
    return bool(item.get("ok")) and not bool(item.get("stale")) and item.get("status") != "failed"


def source_became_fresh(previous, current, source):
    prev = ((previous or {}).get("source_status") or {}).get(source) or {}
    curr = ((current or {}).get("source_status") or {}).get(source) or {}
    prev_fresh = bool(prev.get("ok")) and not bool(prev.get("stale")) and prev.get("status") != "failed"
    curr_fresh = bool(curr.get("ok")) and not bool(curr.get("stale")) and curr.get("status") != "failed"
    return (not prev_fresh) and curr_fresh


def trigger_record(reason, source, previous_value, current_value, current, previous=None, observed_at=None, detail=None):
    return {
        "reason": reason,
        "source": source,
        "previous_value": previous_value,
        "current_value": current_value,
        "previous_bucket": round_half_up(previous_value),
        "current_bucket": round_half_up(current_value),
        "observed_at": observed_at,
        "detail": detail,
        "market_id": current.get("market_id"),
        "event_slug": current.get("event_slug"),
        "target_date": current.get("target_date"),
        "unit": current.get("unit"),
        "current_captured_at_utc": current.get("captured_at_utc"),
        "previous_captured_at_utc": (previous or {}).get("captured_at_utc"),
    }


def detect_observation_triggers(previous, current, support_margin=DEFAULT_SUPPORT_MARGIN):
    """Return material source-change triggers between two observation states."""
    if not previous:
        return []
    prev_values = previous.get("values") or {}
    cur_values = current.get("values") or {}
    triggers = []

    prev_history = to_float(prev_values.get("wu_history_high"))
    cur_history = to_float(cur_values.get("wu_history_high"))
    if cur_history is not None and (prev_history is None or cur_history > prev_history):
        triggers.append(trigger_record(
            "wu_history_high_increased",
            "wu_history",
            prev_history,
            cur_history,
            current,
            previous,
            observed_at=cur_values.get("wu_history_latest_time"),
            detail="WU/Weather.com printed high increased.",
        ))

    boundary_sources = (
        ("wu_current_temp", "wu_current", cur_values.get("wu_current_time")),
        ("wu_current_max_since_7am", "wu_current", cur_values.get("wu_current_time")),
        ("metar_temp", "metar", cur_values.get("metar_report_time")),
        ("eccc_swob_latest_temp", "eccc_swob", cur_values.get("eccc_swob_latest_time")),
    )
    for key, source, observed_at in boundary_sources:
        prev_value = to_float(prev_values.get(key))
        cur_value = to_float(cur_values.get(key))
        if prev_value is None or cur_value is None:
            continue
        prev_bucket = round_half_up(prev_value)
        cur_bucket = round_half_up(cur_value)
        if prev_bucket is not None and cur_bucket is not None and prev_bucket != cur_bucket:
            if key == "wu_current_max_since_7am" and cur_bucket < prev_bucket:
                triggers.append(trigger_record(
                    f"{key}_source_revision_down",
                    source,
                    prev_value,
                    cur_value,
                    current,
                    previous,
                    observed_at=observed_at,
                    detail=(
                        f"{key} decreased from bucket {prev_bucket} to {cur_bucket}; "
                        "classified as a source revision, not a lower day high."
                    ),
                ))
                continue
            triggers.append(trigger_record(
                f"{key}_bucket_crossed",
                source,
                prev_value,
                cur_value,
                current,
                previous,
                observed_at=observed_at,
                detail=f"{key} crossed from bucket {prev_bucket} to {cur_bucket}.",
            ))

    history_floor = cur_history
    prev_history_floor = prev_history
    support_sources = (
        ("metar_temp", "metar", cur_values.get("metar_report_time")),
        ("eccc_swob_max", "eccc_swob", cur_values.get("eccc_swob_latest_time")),
        ("eccc_swob_latest_temp", "eccc_swob", cur_values.get("eccc_swob_latest_time")),
    )
    for key, source, observed_at in support_sources:
        cur_value = to_float(cur_values.get(key))
        prev_value = to_float(prev_values.get(key))
        if cur_value is None or history_floor is None:
            continue
        cur_margin = cur_value - history_floor
        prev_margin = None
        if prev_value is not None and prev_history_floor is not None:
            prev_margin = prev_value - prev_history_floor
        if cur_margin >= support_margin and (prev_margin is None or prev_margin < support_margin):
            triggers.append(trigger_record(
                f"{key}_above_wu_floor",
                source,
                prev_value,
                cur_value,
                current,
                previous,
                observed_at=observed_at,
                detail=f"{key} is {cur_margin:.2f} {current.get('unit')} above the WU printed high.",
            ))

    for source in OBSERVATION_SOURCES:
        if source_became_fresh(previous, current, source):
            triggers.append(trigger_record(
                f"{source}_became_fresh",
                source,
                None,
                None,
                current,
                previous,
                observed_at=((current.get("source_status") or {}).get(source) or {}).get("fetched_at"),
                detail=f"{source} recovered from stale/failed to fresh.",
            ))

    seen = set()
    deduped = []
    for trigger in triggers:
        key = (trigger.get("reason"), trigger.get("source"), trigger.get("current_value"), trigger.get("observed_at"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(trigger)
    return deduped


def build_trigger_context(market_id, previous, current, triggers):
    reasons = sorted({trigger["reason"] for trigger in triggers})
    primary = triggers[0] if triggers else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "observation_trigger",
        "market_id": market_id,
        "event_slug": current.get("event_slug"),
        "target_date": current.get("target_date"),
        "unit": current.get("unit"),
        "reason": reasons[0] if len(reasons) == 1 else "multiple_observation_changes",
        "reasons": reasons,
        "primary_trigger": primary,
        "triggers": triggers,
        "previous_observation": previous,
        "current_observation": current,
        "created_at_utc": utc_now().isoformat(),
    }


def trigger_is_live_fresh(trigger_context, now=None, stale_seconds=DEFAULT_FAST_STALE_SECONDS):
    now = now or utc_now()
    created = trigger_context.get("created_at_utc") if trigger_context else None
    age = age_seconds(now, created)
    return age is not None and age <= stale_seconds


def trigger_direction(previous_value, current_value):
    previous_value = to_float(previous_value)
    current_value = to_float(current_value)
    if previous_value is None or current_value is None:
        return "unknown"
    if current_value > previous_value:
        return "up"
    if current_value < previous_value:
        return "down"
    return "same"


def trigger_context_direction(trigger_context):
    primary = (trigger_context or {}).get("primary_trigger") or {}
    return trigger_direction(primary.get("previous_value"), primary.get("current_value"))


def trigger_policy_key(reason, direction):
    return f"{reason or 'unknown'}|{direction or 'unknown'}"


def load_trigger_permission_policy(path=DEFAULT_REPLAY_JSON):
    payload = read_json(path)
    if not payload:
        return None
    summary = payload.get("summary") or {}
    return summary.get("trigger_permission_policy")


def trigger_context_allowed_by_policy(trigger_context, policy):
    if not policy:
        return False, "missing_trigger_permission_policy"
    allowed = set(policy.get("allowed_reason_directions") or [])
    reason = (trigger_context or {}).get("reason") or "unknown"
    direction = trigger_context_direction(trigger_context)
    key = trigger_policy_key(reason, direction)
    if key in allowed:
        return True, key
    return False, key


def latest_trade_permission(status, now=None, stale_seconds=DEFAULT_FAST_STALE_SECONDS, policy_path=DEFAULT_REPLAY_JSON):
    now = now or utc_now()
    health = watcher_health(status, now=now)
    latest = (status or {}).get("latest_triggered") or {}
    policy = load_trigger_permission_policy(policy_path)
    fresh_markets = {
        market_id: trigger_is_live_fresh((item or {}).get("trigger_context") or {}, now, stale_seconds)
        for market_id, item in latest.items()
    }
    permissioned_markets = {}
    blocked_reasons = {}
    for market_id, item in latest.items():
        context = (item or {}).get("trigger_context") or {}
        allowed, reason = trigger_context_allowed_by_policy(context, policy)
        permissioned_markets[market_id] = bool(fresh_markets.get(market_id)) and allowed
        if fresh_markets.get(market_id) and not allowed:
            blocked_reasons[market_id] = reason
    return {
        "watcher_state": health.get("state"),
        "watcher_fresh": health.get("state") in {"RUNNING", "DEGRADED"},
        "fresh_markets": fresh_markets,
        "permissioned_markets": permissioned_markets,
        "blocked_reasons": blocked_reasons,
        "policy_path": str(policy_path) if policy_path else None,
        "policy_status": (policy or {}).get("acceptance_status") or "missing",
        "trade_permissioned": health.get("state") in {"RUNNING", "DEGRADED"} and any(permissioned_markets.values()),
        "stale_after_seconds": stale_seconds,
    }


def run_once(args, capture_func=capture_snapshot, fetch_state_func=fetch_market_observation_state, now=None):
    now = now or utc_now()
    status_path = Path(args.status_out)
    events_path = Path(args.events_out)
    status = read_status(status_path) or {
        "schema_version": SCHEMA_VERSION,
        "runner": "observation_trigger",
        "markets": {},
        "latest_triggered": {},
        "consecutive_errors": 0,
    }
    status.setdefault("markets", {})
    status.setdefault("latest_triggered", {})
    poll_results = {}
    trigger_count = 0
    errors = {}

    for market_id in market_ids(args.market):
        try:
            current = fetch_state_func(market_id, now=now)
            market_state = status["markets"].get(market_id) or {}
            previous = market_state.get("last_observation")
            current["settlement_normalization"] = update_monotonic_high_ledger(
                previous_ledger=market_state.get("monotonic_high_ledger"),
                previous_observation=previous,
                current_observation=current,
            )
            current_values = current.setdefault("values", {})
            current_values.update({
                "raw_current_high": current["settlement_normalization"].get("raw_current_high"),
                "raw_current_high_bucket": current["settlement_normalization"].get("raw_current_high_bucket"),
                "settlement_current_high": current["settlement_normalization"].get("settlement_current_high"),
                "high_source": current["settlement_normalization"].get("high_source"),
                "revision_state": current["settlement_normalization"].get("revision_state"),
                "settlement_bin_key": current["settlement_normalization"].get("settlement_bin_key"),
            })
            triggers = detect_observation_triggers(previous, current, support_margin=args.support_margin)
            if args.trigger_on_first and not previous:
                triggers = [trigger_record(
                    "initial_state_forced",
                    "observation_trigger",
                    None,
                    current.get("values", {}).get("settlement_current_high"),
                    current,
                    previous,
                    observed_at=current.get("captured_at_utc"),
                    detail="Initial watcher state was configured to force a recompute.",
                )]
            result = {
                "market_id": market_id,
                "event_slug": current.get("event_slug"),
                "triggered": bool(triggers),
                "trigger_count": len(triggers),
                "triggers": triggers,
                "dry_run": bool(args.dry_run),
            }
            if triggers:
                trigger_context = build_trigger_context(market_id, previous, current, triggers)
                result["trigger_context"] = trigger_context
                if not args.dry_run:
                    snapshot_result = capture_func(
                        force=True,
                        market_id=market_id,
                        cadence="triggered",
                        trigger_context=trigger_context,
                    )
                    result["snapshot"] = snapshot_result
                    event = {
                        "schema_version": SCHEMA_VERSION,
                        "record_type": "observation_trigger_event",
                        "triggered_at_utc": utc_now().isoformat(),
                        "market_id": market_id,
                        "event_slug": current.get("event_slug"),
                        "trigger_context": trigger_context,
                        "snapshot": snapshot_result,
                    }
                    append_jsonl(events_path, event)
                    status["latest_triggered"][market_id] = {
                        "triggered_at_utc": event["triggered_at_utc"],
                        "event_slug": current.get("event_slug"),
                        "snapshot_id": snapshot_result.get("snapshot_id"),
                        "snapshot_path": snapshot_result.get("path"),
                        "top_temp": snapshot_result.get("top_temp_c"),
                        "top_probability": snapshot_result.get("top_probability"),
                        "distribution": snapshot_result.get("distribution"),
                        "trigger_context": trigger_context,
                    }
                trigger_count += len(triggers)
            market_state.update({
                "last_poll_at_utc": now.astimezone(timezone.utc).isoformat(),
                "last_observation": current,
                "monotonic_high_ledger": current.get("settlement_normalization") or {},
                "last_result": result,
            })
            status["markets"][market_id] = market_state
            poll_results[market_id] = result
        except Exception as exc:  # noqa: BLE001 - one market cannot kill the watcher
            errors[market_id] = f"{type(exc).__name__}: {exc}"
            poll_results[market_id] = {"market_id": market_id, "error": errors[market_id]}

    if errors:
        status["consecutive_errors"] = int(status.get("consecutive_errors") or 0) + 1
        status["last_error"] = "; ".join(f"{market}: {error}" for market, error in sorted(errors.items()))
    else:
        status["consecutive_errors"] = 0
        status["last_error"] = None

    status.update({
        "schema_version": SCHEMA_VERSION,
        "runner": "observation_trigger",
        "pid": os.getpid(),
        "last_heartbeat": now.astimezone(timezone.utc).isoformat(),
        "last_poll_at_utc": now.astimezone(timezone.utc).isoformat(),
        "interval_seconds": getattr(args, "interval_seconds", DEFAULT_INTERVAL_SECONDS),
        "stale_after_seconds": getattr(args, "stale_after_seconds", DEFAULT_FAST_STALE_SECONDS),
        "runtime_identity": get_runtime_identity(),
        "last_poll_results": poll_results,
        "last_trigger_count": trigger_count,
        "paused": PAUSE_FLAG_PATH.exists(),
    })
    status["trade_permission"] = latest_trade_permission(
        status,
        now=now,
        stale_seconds=getattr(args, "stale_after_seconds", DEFAULT_FAST_STALE_SECONDS),
        policy_path=getattr(args, "trigger_policy", DEFAULT_REPLAY_JSON),
    )
    write_status(status, status_path)
    append_diagnostic({
        "time": now.astimezone(timezone.utc).isoformat(),
        "market_count": len(poll_results),
        "trigger_count": trigger_count,
        "errors": errors,
    }, path=getattr(args, "diagnostics_out", DIAGNOSTICS_PATH))
    return {
        "status": "error" if errors else "ok",
        "trigger_count": trigger_count,
        "markets": poll_results,
        "status_path": str(status_path),
        "events_path": str(events_path),
    }


def watcher_health(status, now=None, interval_seconds=DEFAULT_INTERVAL_SECONDS, pid_alive=None):
    now = now or utc_now()
    if not status:
        return {"state": "UNKNOWN", "detail": "no observation trigger status file"}
    interval = to_float(status.get("interval_seconds")) or float(interval_seconds)
    hb_age = age_seconds(now, status.get("last_heartbeat"))
    errors = int(status.get("consecutive_errors") or 0)
    dead_after = 2 * interval + 30.0
    if pid_alive is None:
        pid_alive = pid_is_python(status.get("pid"))
    if not pid_alive:
        state = "DEAD"
    elif status.get("paused"):
        state = "PAUSED"
    elif hb_age is None or hb_age > dead_after:
        state = "DEAD"
    elif errors >= 3:
        state = "ERRORING"
    elif errors:
        state = "DEGRADED"
    else:
        state = "RUNNING"
    return {
        "state": state,
        "pid": status.get("pid"),
        "pid_alive": bool(pid_alive),
        "heartbeat_age_seconds": round(hb_age, 1) if hb_age is not None else None,
        "consecutive_errors": errors,
        "last_error": status.get("last_error"),
        "started_at": status.get("started_at"),
        "market_id": status.get("market"),
        "interval_seconds": status.get("interval_seconds"),
        "last_trigger_count": status.get("last_trigger_count"),
    }


def _normalized_pid(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cleanup_watcher_writer_lock(expected_pid=None, attempts=1, sleep_seconds=0.1, status_path=None):
    attempts = max(1, int(attempts))
    status_path = status_path or STATUS_PATH
    last_result = None
    for attempt in range(attempts):
        lock = read_writer_lock(status_path)
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


def stop_watcher_loop(now=None, status_path=None):
    now = now or utc_now()
    status_path = status_path or STATUS_PATH
    status = read_status(status_path)
    pid = (status or {}).get("pid")
    lock_cleanup = _cleanup_watcher_writer_lock(
        expected_pid=pid,
        attempts=20,
        sleep_seconds=0.1,
        status_path=status_path,
    )
    if not pid_is_python(pid):
        return {
            "stopped": False,
            "reason": f"no live observation trigger process (pid={pid})",
            "writer_lock": lock_cleanup,
        }
    stop = terminate_python_pid(pid)
    if not stop.get("stopped"):
        return {"stopped": False, "pid": pid, "reason": stop.get("reason"), "writer_lock": lock_cleanup}
    if status is not None:
        status["last_stop_requested_at"] = now.isoformat()
        write_status(status, status_path)
    append_diagnostic({"time": now.isoformat(), "supervisor": "stop", "pid": pid, "writer_lock": lock_cleanup})
    return {"stopped": True, "pid": pid, "writer_lock": lock_cleanup}


def start_watcher_detached(
    market="all",
    interval_seconds=DEFAULT_INTERVAL_SECONDS,
    stale_after_seconds=DEFAULT_FAST_STALE_SECONDS,
    now=None,
):
    now = now or utc_now()
    lock_cleanup = _cleanup_watcher_writer_lock(attempts=3, sleep_seconds=0.1)
    if lock_cleanup.get("reason") == "writer lock owner is still live":
        append_diagnostic({
            "time": now.isoformat(),
            "supervisor": "start_blocked",
            "reason": "writer lock owner is still live",
            "writer_lock": lock_cleanup,
        })
        return {"started": False, "reason": "writer lock owner is still live", "writer_lock": lock_cleanup}
    child = launch_detached(
        OBSERVATION_SUPERVISOR.command(
            "loop",
            "--market",
            market,
            "--interval-seconds",
            interval_seconds,
            "--stale-after-seconds",
            stale_after_seconds,
        ),
        cwd=OBSERVATION_SUPERVISOR.cwd,
        console_log_path=CONSOLE_LOG_PATH,
        popen_fn=subprocess.Popen,
    )
    write_status({
        "schema_version": SCHEMA_VERSION,
        "runner": "observation_trigger",
        "pid": child.pid,
        "market": market,
        "started_at": now.isoformat(),
        "last_heartbeat": now.isoformat(),
        "interval_seconds": interval_seconds,
        "stale_after_seconds": stale_after_seconds,
        "iterations": 0,
        "consecutive_errors": 0,
        "last_error": None,
        "markets": {},
        "latest_triggered": {},
        "runtime_identity": get_runtime_identity(),
        "started_by": "supervisor",
        "paused": PAUSE_FLAG_PATH.exists(),
    })
    append_diagnostic({"time": now.isoformat(), "supervisor": "start", "pid": child.pid, "writer_lock": lock_cleanup})
    return {"started": True, "pid": child.pid, "writer_lock": lock_cleanup}


def acquire_supervisor_lock(path=None):
    return acquire_file_lock(path or SUPERVISOR_LOCK_PATH, attempts=2, stale_after_seconds=120)


def release_supervisor_lock(handle, path=None):
    release_file_lock(handle, path or SUPERVISOR_LOCK_PATH)


def source_identity_error(value):
    text = str(value or "").lower()
    return "code identity differs" in text or "source tree" in text


def ensure_decision(health_state, pid_alive, last_error=None):
    if health_state in {"DEGRADED", "ERRORING"} and source_identity_error(last_error):
        return "restart" if pid_alive else "start"
    if health_state in {"RUNNING", "PAUSED", "DEGRADED", "ERRORING"}:
        return "noop"
    if pid_alive:
        return "restart"
    return "start"


def ensure_watcher_loop(
    market="all",
    interval_seconds=DEFAULT_INTERVAL_SECONDS,
    stale_after_seconds=DEFAULT_FAST_STALE_SECONDS,
    now=None,
):
    now = now or utc_now()
    handle = acquire_supervisor_lock()
    if handle is None:
        return {"action": "locked", "reason": "another observation trigger supervisor action is running"}
    try:
        status = read_status()
        alive = pid_is_python((status or {}).get("pid"))
        health = watcher_health(status, now=now, interval_seconds=interval_seconds, pid_alive=alive)
        action = ensure_decision(health["state"], alive, health.get("last_error"))
        result = {"action": action, "state": health["state"], "pid": health.get("pid")}
        if action == "restart":
            result["stop"] = stop_watcher_loop(now=now)
            result["start"] = start_watcher_detached(market, interval_seconds, stale_after_seconds, now=now)
        elif action == "start":
            result["start"] = start_watcher_detached(market, interval_seconds, stale_after_seconds, now=now)
        if action != "noop":
            append_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
        return result
    finally:
        release_supervisor_lock(handle)


def run_loop(args, capture_func=capture_snapshot, fetch_state_func=fetch_market_observation_state):
    writer_lock = acquire_writer_lock(
        args.status_out,
        owner={"loop": OBSERVATION_SUPERVISOR.name, "module": OBSERVATION_SUPERVISOR.module},
        stale_after_seconds=max(120.0, float(args.interval_seconds) * 3.0),
    )
    if writer_lock is None:
        existing = read_writer_lock(args.status_out)
        append_diagnostic({
            "time": utc_now().isoformat(),
            "status": "duplicate_writer_blocked",
            "existing_writer": existing,
            "pid": os.getpid(),
        }, path=args.diagnostics_out)
        return {"status": "duplicate_writer_blocked", "existing_writer": existing, "pid": os.getpid()}
    sleep_inhibitor = keep_system_awake("weather observation trigger loop")
    power_request = sleep_inhibitor.start()
    status = read_status(args.status_out) or {"markets": {}, "latest_triggered": {}}
    status.update({
        "schema_version": SCHEMA_VERSION,
        "runner": "observation_trigger",
        "pid": os.getpid(),
        "power_request": power_request,
        "market": args.market,
        "started_at": utc_now().isoformat(),
        "last_heartbeat": utc_now().isoformat(),
        "interval_seconds": args.interval_seconds,
        "stale_after_seconds": args.stale_after_seconds,
        "iterations": 0,
        "consecutive_errors": 0,
        "last_error": None,
        "runtime_identity": get_runtime_identity(),
    })
    attach_status_writer(status, writer_lock)
    write_status(status, args.status_out)
    try:
        while True:
            loop_started = utc_now()
            status = read_status(args.status_out) or status
            attach_status_writer(status, writer_lock)
            status["iterations"] = int(status.get("iterations") or 0) + 1
            status["last_heartbeat"] = loop_started.isoformat()
            status["paused"] = PAUSE_FLAG_PATH.exists()
            write_status(status, args.status_out)
            if status["paused"]:
                append_diagnostic({"time": loop_started.isoformat(), "status": "paused"}, path=args.diagnostics_out)
                result = {"status": "paused", "time": loop_started.isoformat()}
            else:
                result = run_once(
                    args,
                    capture_func=capture_func,
                    fetch_state_func=fetch_state_func,
                    now=loop_started,
                )
            print(json.dumps(result, sort_keys=True, default=str), flush=True)
            if args.max_iterations is not None and int(status.get("iterations") or 0) >= args.max_iterations:
                return status
            elapsed = (utc_now() - loop_started).total_seconds()
            time.sleep(max(1.0, float(args.interval_seconds) - elapsed))
    finally:
        sleep_inhibitor.stop()
        release_writer_lock(writer_lock)


def read_jsonl(path):
    return io_read_jsonl(path)


def band_key(row):
    kind = row.get("bin_kind")
    value = to_int(row.get("bin_value_c") or row.get("bin_value"))
    value_hi = to_int(row.get("bin_value_hi_c") or row.get("bin_value_hi"))
    encoded = row.get("band_key") or row.get("band_key_text")
    if encoded and (not kind or value is None):
        match = re.match(r"^(eq|lte|gte):(\d+)(?:-(\d+))?$", str(encoded))
        if match:
            kind = kind or match.group(1)
            value = value if value is not None else to_int(match.group(2))
            value_hi = value_hi if value_hi is not None else to_int(match.group(3))
    label = row.get("range_label") or ""
    numbers = [to_int(item) for item in re.findall(r"\d+", str(label))]
    numbers = [item for item in numbers if item is not None]
    if not kind and numbers:
        label_lower = str(label).lower()
        if "below" in label_lower or "under" in label_lower:
            kind = "lte"
        elif "higher" in label_lower or "above" in label_lower:
            kind = "gte"
        else:
            kind = "eq"
    if value is None and numbers:
        value = numbers[0]
    if value_hi is None:
        value_hi = numbers[-1] if len(numbers) >= 2 else value
    return kind, value, value_hi


def same_band(left, right):
    left_key = band_key(left)
    right_key = band_key(right)
    if left_key[0] is not None and left_key[1] is not None and right_key[0] is not None and right_key[1] is not None:
        return left_key == right_key
    return (left.get("range_label") or "") == (right.get("range_label") or "")


def band_outcome(row, settlement_bucket):
    if settlement_bucket is None:
        return None
    kind, value, value_hi = band_key(row)
    if kind is None or value is None:
        return None
    if kind == "lte":
        return int(settlement_bucket <= value)
    if kind == "gte":
        return int(settlement_bucket >= value)
    value_hi = value if value_hi is None else value_hi
    return int(value <= settlement_bucket <= value_hi)


def brier(probability, outcome):
    probability = to_float(probability)
    if probability is None or outcome is None:
        return None
    return (probability - int(outcome)) ** 2


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def load_labels(path):
    labels = {}
    path = Path(path)
    if not path.exists():
        return labels
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            labels[row.get("event_slug")] = row
    return labels


def load_snapshot_rows(folder):
    path = Path(folder) / "snapshots_long.csv"
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row["_captured_dt"] = parse_dt(row.get("captured_at_utc") or row.get("captured_at_local"))
            rows.append(row)
    replay_index = {
        str(record.get("snapshot_id")): record
        for record in read_jsonl(Path(folder) / "replay_inputs.jsonl")
    }
    for row in rows:
        record = replay_index.get(str(row.get("snapshot_id"))) or {}
        trigger_context = record.get("trigger_context") or {}
        primary_trigger = trigger_context.get("primary_trigger") or {}
        if not row.get("snapshot_cadence"):
            row["snapshot_cadence"] = record.get("snapshot_cadence") or "scheduled"
        if not row.get("trigger_reason") and trigger_context:
            row["trigger_reason"] = trigger_context.get("reason")
        if not row.get("trigger_source"):
            row["trigger_source"] = primary_trigger.get("source")
        if not row.get("trigger_previous_value"):
            row["trigger_previous_value"] = primary_trigger.get("previous_value")
        if not row.get("trigger_current_value"):
            row["trigger_current_value"] = primary_trigger.get("current_value")
        if not row.get("trigger_observed_at"):
            row["trigger_observed_at"] = primary_trigger.get("observed_at")
    return rows


def load_casebook_wu_lag(casebook_path):
    payload = read_json(casebook_path) or {}
    cases = payload.get("cases") or []
    return [
        case for case in cases
        if case.get("taxonomy") == "wu_lag_catchup_miss"
        and case.get("model_result") == "model_loss"
    ]


def case_window(case):
    start = parse_dt(case.get("start_time_utc") or case.get("start_time_local"))
    end = parse_dt(case.get("end_time_utc") or case.get("end_time_local"))
    return start, end


def matches_case(row, case):
    if row.get("event_slug") != case.get("event_slug"):
        return False
    if not same_band(row, case):
        return False
    captured = row.get("_captured_dt")
    start, end = case_window(case)
    if captured is None or start is None or end is None:
        return True
    return start <= captured <= end


def nearest_rows(rows, trigger_row):
    captured = trigger_row.get("_captured_dt")
    if captured is None:
        return None, None
    same_band_rows = [
        row for row in rows
        if same_band(row, trigger_row)
        and row.get("snapshot_cadence") != "triggered"
        and row.get("_captured_dt") is not None
    ]
    before = [row for row in same_band_rows if row["_captured_dt"] < captured]
    after = [row for row in same_band_rows if row["_captured_dt"] > captured]
    return (
        max(before, key=lambda row: row["_captured_dt"]) if before else None,
        min(after, key=lambda row: row["_captured_dt"]) if after else None,
    )


def score_row(row, settlement_bucket):
    outcome = band_outcome(row, settlement_bucket)
    return {
        "model_brier": brier(row.get("model_probability"), outcome),
        "market_brier": brier(row.get("market_yes"), outcome),
        "outcome": outcome,
    }


def replay_metric_summary(rows):
    triggered_brier = mean(row.get("triggered_model_brier") for row in rows)
    pre_brier = mean(row.get("pre_model_brier") for row in rows)
    next_brier = mean(row.get("next_model_brier") for row in rows)
    market_brier = mean(row.get("triggered_market_brier") for row in rows)
    delta = triggered_brier - pre_brier if triggered_brier is not None and pre_brier is not None else None
    return {
        "rows": len(rows),
        "triggered_model_brier": triggered_brier,
        "pre_model_brier": pre_brier,
        "next_model_brier": next_brier,
        "triggered_market_brier": market_brier,
        "delta_triggered_vs_pre": delta,
    }


def build_trigger_permission_policy(
    scored_rows,
    min_rows=DEFAULT_TRIGGER_POLICY_MIN_ROWS,
    max_delta=DEFAULT_TRIGGER_POLICY_MAX_DELTA,
):
    reason_direction_rows = defaultdict(list)
    reason_rows = defaultdict(list)
    for row in scored_rows:
        reason = row.get("trigger_reason") or "unknown"
        direction = row.get("trigger_direction") or "unknown"
        reason_direction_rows[trigger_policy_key(reason, direction)].append(row)
        reason_rows[reason].append(row)

    def summarize_groups(groups):
        output = {}
        for key, rows in sorted(groups.items()):
            metrics = replay_metric_summary(rows)
            delta = metrics.get("delta_triggered_vs_pre")
            metrics["passes_policy"] = (
                metrics.get("rows", 0) >= min_rows
                and delta is not None
                and delta <= max_delta
            )
            output[key] = metrics
        return output

    reason_direction_metrics = summarize_groups(reason_direction_rows)
    reason_metrics = summarize_groups(reason_rows)
    allowed = [
        key for key, metrics in reason_direction_metrics.items()
        if metrics.get("passes_policy")
    ]
    blocked = [
        key for key, metrics in reason_direction_metrics.items()
        if not metrics.get("passes_policy")
    ]
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "minimum_rows": min_rows,
        "maximum_delta_triggered_vs_pre": max_delta,
        "allowed_reason_directions": allowed,
        "blocked_reason_directions": blocked,
        "reason_direction_cohorts": reason_direction_metrics,
        "reason_cohorts": reason_metrics,
    }


def build_triggered_replay_report(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    casebook_path=None,
    asos_1min_root=None,
):
    snapshots_root = Path(snapshots_root)
    backtest_root = Path(backtest_root)
    asos_1min_root = Path(asos_1min_root) if asos_1min_root else DEFAULT_ASOS_1MIN_ROOT
    labels = load_labels(backtest_root / "market_day_labels.csv")
    casebook_path = Path(casebook_path) if casebook_path else backtest_root / "disagreement_casebook.json"
    cases = load_casebook_wu_lag(casebook_path)
    cases_by_event = defaultdict(list)
    for case in cases:
        cases_by_event[case.get("event_slug")].append(case)

    scored = []
    trigger_rows = 0
    matched_trigger_rows = 0
    for folder in sorted(snapshots_root.glob("*")):
        if not folder.is_dir():
            continue
        rows = load_snapshot_rows(folder)
        if not rows:
            continue
        event_slug = rows[0].get("event_slug")
        label = labels.get(event_slug) or {}
        settlement_bucket = to_int(label.get("settlement_bucket"))
        if settlement_bucket is None:
            continue
        folder_cases = cases_by_event.get(event_slug) or []
        if not folder_cases:
            continue
        for row in rows:
            if row.get("snapshot_cadence") != "triggered":
                continue
            trigger_rows += 1
            matching_cases = [case for case in folder_cases if matches_case(row, case)]
            if not matching_cases:
                continue
            matched_trigger_rows += 1
            before, after = nearest_rows(rows, row)
            trigger_score = score_row(row, settlement_bucket)
            before_score = score_row(before, settlement_bucket) if before else {}
            after_score = score_row(after, settlement_bucket) if after else {}
            spec = spec_for_slug(event_slug)
            target_date = date_from_event_slug(event_slug) if event_slug else None
            asos_daily = load_daily_summary(asos_1min_root, spec, target_date) if spec and target_date else None
            asos_comparison = compare_daily_summary_to_wu_print(
                asos_daily,
                settlement_bucket=settlement_bucket,
                wu_print_time=row.get("_captured_dt"),
                spec=spec,
            ) if spec else {}
            scored.append({
                "event_slug": event_slug,
                "market_id": spec.id if spec else None,
                "snapshot_id": row.get("snapshot_id"),
                "captured_at_utc": row.get("captured_at_utc"),
                "range_label": row.get("range_label"),
                "trigger_reason": row.get("trigger_reason"),
                "trigger_source": row.get("trigger_source"),
                "trigger_previous_value": to_float(row.get("trigger_previous_value")),
                "trigger_current_value": to_float(row.get("trigger_current_value")),
                "trigger_direction": trigger_direction(row.get("trigger_previous_value"), row.get("trigger_current_value")),
                "case_ids": [case.get("case_id") for case in matching_cases],
                "settlement_bucket": settlement_bucket,
                "triggered_model_probability": to_float(row.get("model_probability")),
                "pre_model_probability": to_float((before or {}).get("model_probability")),
                "next_model_probability": to_float((after or {}).get("model_probability")),
                "triggered_model_brier": trigger_score.get("model_brier"),
                "pre_model_brier": before_score.get("model_brier"),
                "next_model_brier": after_score.get("model_brier"),
                "triggered_market_brier": trigger_score.get("market_brier"),
                **asos_comparison,
            })

    policy = build_trigger_permission_policy(scored)
    allowed_reason_directions = set(policy.get("allowed_reason_directions") or [])
    for row in scored:
        permission_key = trigger_policy_key(row.get("trigger_reason"), row.get("trigger_direction"))
        row["trigger_permission_key"] = permission_key
        row["trigger_permissioned"] = permission_key in allowed_reason_directions

    all_metrics = replay_metric_summary(scored)
    permissioned = [row for row in scored if row.get("trigger_permissioned")]
    permissioned_metrics = replay_metric_summary(permissioned)
    all_delta = all_metrics.get("delta_triggered_vs_pre")
    permissioned_delta = permissioned_metrics.get("delta_triggered_vs_pre")
    if len(scored) == 0:
        acceptance_status = "WAITING_FOR_SETTLED_TRIGGER_ROWS"
    elif all_delta is not None and all_delta <= DEFAULT_TRIGGER_POLICY_MAX_DELTA:
        acceptance_status = "PASS_ALL_TRIGGERED"
    elif (
        permissioned_metrics.get("rows", 0) >= DEFAULT_TRIGGER_POLICY_MIN_ROWS
        and permissioned_delta is not None
        and permissioned_delta <= DEFAULT_TRIGGER_POLICY_MAX_DELTA
    ):
        acceptance_status = "PASS_WITH_PERMISSION_POLICY"
    else:
        acceptance_status = "BLOCKED_BY_TRIGGER_REPLAY_REGRESSION"
    policy["acceptance_status"] = acceptance_status

    summary = {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "casebook_path": str(casebook_path),
        "wu_lag_loss_cases": len(cases),
        "triggered_rows_on_settled_wu_lag_events": trigger_rows,
        "matched_triggered_rows": matched_trigger_rows,
        "scored_rows": len(scored),
        "trigger_acceptance_status": acceptance_status,
        "triggered_model_brier": all_metrics.get("triggered_model_brier"),
        "pre_model_brier": all_metrics.get("pre_model_brier"),
        "next_model_brier": all_metrics.get("next_model_brier"),
        "triggered_market_brier": all_metrics.get("triggered_market_brier"),
        "trigger_permissioned_rows": permissioned_metrics.get("rows"),
        "trigger_permissioned_model_brier": permissioned_metrics.get("triggered_model_brier"),
        "trigger_permissioned_pre_brier": permissioned_metrics.get("pre_model_brier"),
        "trigger_permissioned_next_brier": permissioned_metrics.get("next_model_brier"),
        "trigger_permissioned_market_brier": permissioned_metrics.get("triggered_market_brier"),
        "trigger_permissioned_delta_triggered_vs_pre": permissioned_metrics.get("delta_triggered_vs_pre"),
        "trigger_permission_policy": policy,
        "asos_1min_rows_with_evidence": sum(1 for row in scored if row.get("asos_1min_available")),
        "asos_1min_mean_minus_settlement": mean(row.get("asos_1min_minus_settlement_bucket") for row in scored),
        "asos_1min_mean_minutes_from_first_high_to_wu_print": mean(
            row.get("asos_1min_minutes_from_first_high_to_wu_print") for row in scored
        ),
    }
    summary["delta_triggered_vs_pre"] = all_metrics.get("delta_triggered_vs_pre")
    return {"summary": summary, "rows": scored}


def fmt_num(value, digits=4):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def write_replay_outputs(payload, json_out=DEFAULT_REPLAY_JSON, report_out=DEFAULT_REPLAY_REPORT):
    json_path = write_json(json_out, payload)
    summary = payload.get("summary") or {}
    lines = [
        "# Observation-Triggered Replay Slice",
        "",
        f"Generated: {utc_now().isoformat()}",
        "",
        "## Summary",
        "",
        markdown_table(
            ["Metric", "Value"],
            [
                ["WU lag/catch-up model-loss cases", summary.get("wu_lag_loss_cases")],
                ["Triggered rows on settled WU-lag events", summary.get("triggered_rows_on_settled_wu_lag_events")],
                ["Matched triggered rows", summary.get("matched_triggered_rows")],
                ["Scored rows", summary.get("scored_rows")],
                ["Acceptance status", summary.get("trigger_acceptance_status")],
                ["Triggered model Brier", fmt_num(summary.get("triggered_model_brier"))],
                ["Pre-trigger model Brier", fmt_num(summary.get("pre_model_brier"))],
                ["Next scheduled model Brier", fmt_num(summary.get("next_model_brier"))],
                ["Triggered market Brier", fmt_num(summary.get("triggered_market_brier"))],
                ["Delta triggered vs pre", fmt_num(summary.get("delta_triggered_vs_pre"))],
                ["Permissioned triggered rows", summary.get("trigger_permissioned_rows")],
                ["Permissioned triggered Brier", fmt_num(summary.get("trigger_permissioned_model_brier"))],
                ["Permissioned pre-trigger Brier", fmt_num(summary.get("trigger_permissioned_pre_brier"))],
                ["Permissioned delta vs pre", fmt_num(summary.get("trigger_permissioned_delta_triggered_vs_pre"))],
                ["Rows with ASOS 1-min evidence", summary.get("asos_1min_rows_with_evidence")],
                ["ASOS 1-min mean minus settlement", fmt_num(summary.get("asos_1min_mean_minus_settlement"))],
                ["ASOS 1-min mean minutes high before WU print", fmt_num(summary.get("asos_1min_mean_minutes_from_first_high_to_wu_print"))],
            ],
        ),
        "",
    ]
    if not payload.get("rows"):
        lines.extend([
            "No settled triggered rows matched WU lag/catch-up cases yet. The watcher is now able",
            "to create those rows; this report becomes the acceptance slice as triggered evidence accumulates.",
            "",
        ])
    else:
        lines.extend([
            "## Rows",
            "",
            markdown_table(
                [
                    "Event", "Band", "Snapshot", "Reason", "Triggered Brier",
                    "Direction", "Permissioned", "Pre Brier", "Next Brier",
                    "ASOS Max", "ASOS-Settle", "ASOS->WU min", "Cases",
                ],
                [
                    [
                        row.get("event_slug"),
                        row.get("range_label"),
                        row.get("snapshot_id"),
                        row.get("trigger_reason"),
                        fmt_num(row.get("triggered_model_brier")),
                        row.get("trigger_direction"),
                        row.get("trigger_permissioned"),
                        fmt_num(row.get("pre_model_brier")),
                        fmt_num(row.get("next_model_brier")),
                        fmt_num(row.get("asos_1min_max_so_far")),
                        fmt_num(row.get("asos_1min_minus_settlement_bucket")),
                        fmt_num(row.get("asos_1min_minutes_from_first_high_to_wu_print")),
                        ", ".join(row.get("case_ids") or []),
                    ]
                    for row in payload.get("rows", [])[:200]
                ],
            ),
            "",
        ])
        policy = summary.get("trigger_permission_policy") or {}
        cohorts = policy.get("reason_direction_cohorts") or {}
        if cohorts:
            lines.extend([
                "## Trigger Permission Cohorts",
                "",
                markdown_table(
                    [
                        "Reason|Direction", "Rows", "Delta", "Triggered Brier",
                        "Pre Brier", "Allowed",
                    ],
                    [
                        [
                            key,
                            metrics.get("rows"),
                            fmt_num(metrics.get("delta_triggered_vs_pre")),
                            fmt_num(metrics.get("triggered_model_brier")),
                            fmt_num(metrics.get("pre_model_brier")),
                            metrics.get("passes_policy"),
                        ]
                        for key, metrics in sorted(cohorts.items())
                    ],
                ),
                "",
            ])
    report_path = Path(report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, report_path


def build_parser():
    parser = argparse.ArgumentParser(description="Watch live observations and force material weather-market recomputes.")
    sub = parser.add_subparsers(dest="command")

    def add_common(p):
        p.add_argument("--market", default="all", help="Market id or 'all'.")
        p.add_argument("--status-out", default=str(STATUS_PATH))
        p.add_argument("--events-out", default=str(EVENTS_PATH))
        p.add_argument("--diagnostics-out", default=str(DIAGNOSTICS_PATH))
        p.add_argument("--support-margin", type=float, default=DEFAULT_SUPPORT_MARGIN)
        p.add_argument("--stale-after-seconds", type=float, default=DEFAULT_FAST_STALE_SECONDS)
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--trigger-on-first", action="store_true")
        p.add_argument("--trigger-policy", default=str(DEFAULT_REPLAY_JSON))

    once = sub.add_parser("once", help="Poll observations once and trigger recomputes if needed.")
    add_common(once)

    loop = sub.add_parser("loop", help="Run the observation watcher continuously.")
    add_common(loop)
    loop.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    loop.add_argument("--max-iterations", type=int)

    status = sub.add_parser("status", help="Print watcher health and latest triggered fair values.")
    status.add_argument("--status-out", default=str(STATUS_PATH))
    status.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    status.add_argument("--stale-after-seconds", type=float, default=DEFAULT_FAST_STALE_SECONDS)
    status.add_argument("--trigger-policy", default=str(DEFAULT_REPLAY_JSON))

    start = sub.add_parser("start-detached", help="Start the watcher as a detached background process.")
    start.add_argument("--market", default="all")
    start.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    start.add_argument("--stale-after-seconds", type=float, default=DEFAULT_FAST_STALE_SECONDS)

    ensure = sub.add_parser("ensure", help="Supervisor check: start/restart the watcher if dead or hung.")
    ensure.add_argument("--market", default="all")
    ensure.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    ensure.add_argument("--stale-after-seconds", type=float, default=DEFAULT_FAST_STALE_SECONDS)

    sub.add_parser("stop", help="Stop the watcher process recorded in the status file.")

    restart = sub.add_parser("restart", help="Stop then start the watcher.")
    restart.add_argument("--market", default="all")
    restart.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    restart.add_argument("--stale-after-seconds", type=float, default=DEFAULT_FAST_STALE_SECONDS)

    replay = sub.add_parser("replay", help="Score triggered rows against WU lag/catch-up casebook losses.")
    replay.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    replay.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    replay.add_argument("--casebook", default=None)
    replay.add_argument("--asos-1min-root", default=str(DEFAULT_ASOS_1MIN_ROOT))
    replay.add_argument("--json-out", default=str(DEFAULT_REPLAY_JSON))
    replay.add_argument("--report-out", default=str(DEFAULT_REPLAY_REPORT))
    return parser


def main(argv=None):
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "once"
    if command == "once":
        print(json.dumps(run_once(args), indent=2, sort_keys=True, default=str))
        return
    if command == "loop":
        run_loop(args)
        return
    if command == "status":
        status = read_status(args.status_out)
        payload = {
            "health": watcher_health(status, interval_seconds=args.interval_seconds),
            "trade_permission": latest_trade_permission(
                status,
                stale_seconds=args.stale_after_seconds,
                policy_path=args.trigger_policy,
            ),
            "status": status,
        }
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    if command == "start-detached":
        print(json.dumps(
            start_watcher_detached(args.market, args.interval_seconds, args.stale_after_seconds),
            indent=2,
            sort_keys=True,
            default=str,
        ))
        return
    if command == "ensure":
        print(json.dumps(
            ensure_watcher_loop(args.market, args.interval_seconds, args.stale_after_seconds),
            indent=2,
            sort_keys=True,
            default=str,
        ))
        return
    if command == "stop":
        print(json.dumps(stop_watcher_loop(), indent=2, sort_keys=True, default=str))
        return
    if command == "restart":
        result = {
            "stop": stop_watcher_loop(),
            "start": start_watcher_detached(args.market, args.interval_seconds, args.stale_after_seconds),
        }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    if command == "replay":
        payload = build_triggered_replay_report(
            snapshots_root=args.snapshots_root,
            backtest_root=args.backtest_root,
            casebook_path=args.casebook,
            asos_1min_root=args.asos_1min_root,
        )
        json_out, report_out = write_replay_outputs(payload, args.json_out, args.report_out)
        print(f"Observation-triggered replay rows: {payload['summary']['scored_rows']}")
        print(f"JSON written to {json_out}")
        print(f"Report written to {report_out}")
        return
    parser.error(f"unknown command {command}")


if __name__ == "__main__":
    main()
