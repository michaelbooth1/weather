"""Continuous, execution-only WebSocket capture for maker-day evidence.

This producer is deliberately separate from the latency-critical raw-book loop.
It subscribes every active built-in token on one connection, retains only
individual ``last_trade_price`` payload members, and writes hash-bound per-event
session receipts. The paper scorer treats absent, incomplete, or unbound
receipts as non-countable.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import websocket

from weather.io import (
    acquire_writer_lock,
    release_writer_lock,
    sha256_file,
    write_json_atomic,
)
from weather.market.market_config import config_from_event
from weather.market.market_microstructure_capture import (
    MarketMicrostructureStore,
    RawTapeWriterBusy,
    filter_token_rows,
    payload_sha1,
    token_rows_from_event,
    utc_now,
)
from weather.market.market_microstructure_constants import CLOB_WS_URL
from weather.market.market_registry import all_specs
from weather.market.mm_paper_constants import (
    EXECUTION_BOOK_ALIGNMENT_SEQUENCE_STATUS,
    EXECUTION_CANONICAL_TAPE_FILENAME,
    EXECUTION_CONNECTION_SEQUENCE_SCOPE,
    EXECUTION_RAW_TAPE_FILENAME,
    EXECUTION_SESSION_FILENAME,
)
from weather.market.polymarket_client import PolymarketClient
from weather.paths import data_path
from weather.schema_registry import schema_version


BOUND_SESSION_SCHEMA_VERSION = schema_version("mm_execution_capture_bound_session")
EXECUTION_ROW_SCHEMA_VERSION = schema_version("mm_execution_capture_execution_row")
RAW_EXECUTION_SCHEMA_VERSION = schema_version("mm_execution_capture_raw_execution")
STATUS_SCHEMA_VERSION = schema_version("mm_execution_capture_status")
SESSION_FILENAME = EXECUTION_SESSION_FILENAME
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_STATUS_PATH = DEFAULT_SNAPSHOTS_ROOT / "market_execution_capture_status.json"

RETENTION_MODE = "executions-only"
LOCK_SCOPE = "execution-tape"
HOST_POLICY_MODE = "pause-training-window"
EXECUTION_EVENT_TYPE = "last_trade_price"
EXECUTION_TAPE_LOCK_ANCHOR = "mm_execution_tape"
CONNECTION_SEQUENCE_SCOPE = EXECUTION_CONNECTION_SEQUENCE_SCOPE
BOOK_ALIGNMENT_SEQUENCE_STATUS = EXECUTION_BOOK_ALIGNMENT_SEQUENCE_STATUS
HOST_POLICY_TIMEZONE = "America/Toronto"
TRAINING_WINDOW_TASK = "WeatherTrainingWindow"
TRAINING_WINDOW_START = datetime_time(1, 0)
TRAINING_WINDOW_RESTORE = datetime_time(4, 15)
DAILY_BINDING_ROLL = datetime_time(0, 55)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class PlannedHostPolicyPause(RuntimeError):
    """Internal control flow for a training-window boundary during connect."""

EXECUTION_TAPE_COLUMNS = [
    "schema_version",
    "received_at_utc",
    "exchange_time_utc",
    "trade_time_utc",
    "timestamp_utc",
    "exchange_timestamp_ms",
    "timestamp_precision_seconds",
    "event_slug",
    "market_id",
    "event_type",
    "asset_id",
    "clob_token_id",
    "market",
    "condition_id",
    "price",
    "size",
    "side",
    "transaction_hash",
    "session_id",
    "local_connection_message_sequence",
    "connection_sequence_scope",
    "book_alignment_sequence_status",
    "raw_sha1",
]


def _validate_contract(*, retention_mode, lock_scope, host_policy_mode):
    if retention_mode != RETENTION_MODE:
        raise ValueError(f"retention_mode must be {RETENTION_MODE!r}")
    if lock_scope != LOCK_SCOPE:
        raise ValueError(f"lock_scope must be {LOCK_SCOPE!r}")
    if host_policy_mode != HOST_POLICY_MODE:
        raise ValueError(f"host_policy_mode must be {HOST_POLICY_MODE!r}")


def _payload_items(payload):
    return payload if isinstance(payload, list) else [payload]


def _asset_id(item):
    if not isinstance(item, dict):
        return ""
    return str(
        item.get("asset_id")
        or item.get("clob_token_id")
        or item.get("token_id")
        or ""
    )


def _filter_payload_for_assets(payload, asset_ids):
    """Return individual execution members owned by one event."""

    return [
        item
        for item in _payload_items(payload)
        if isinstance(item, dict)
        and str(item.get("event_type") or "").strip().lower() == EXECUTION_EVENT_TYPE
        and _asset_id(item) in asset_ids
    ]


def _payload_subscribed_asset_ids(payload, asset_ids):
    observed = set()
    for item in _payload_items(payload):
        if not isinstance(item, dict) or not str(item.get("event_type") or "").strip():
            continue
        item_asset_id = _asset_id(item)
        if item_asset_id in asset_ids:
            observed.add(item_asset_id)
        changes = item.get("price_changes")
        if isinstance(changes, list):
            observed.update(
                change_asset_id
                for change in changes
                if isinstance(change, dict)
                for change_asset_id in [_asset_id(change)]
                if change_asset_id in asset_ids
            )
    return observed


def _normalize_exchange_timestamp_ms(value):
    """Return the exact epoch-millisecond value and normalized UTC time."""

    if value in (None, "") or isinstance(value, bool):
        raise ValueError("last_trade_price is missing its source millisecond timestamp")
    try:
        numeric = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("last_trade_price has an invalid source millisecond timestamp") from exc
    if not numeric.is_finite() or numeric != numeric.to_integral_value():
        raise ValueError("last_trade_price timestamp must be an integer epoch millisecond")
    milliseconds = int(numeric)
    seconds, remainder_ms = divmod(milliseconds, 1000)
    try:
        normalized = datetime.fromtimestamp(seconds, tz=timezone.utc).replace(
            microsecond=remainder_ms * 1000
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("last_trade_price timestamp is outside the supported UTC range") from exc
    return milliseconds, normalized.isoformat(timespec="milliseconds")


def _asset_set_sha256(asset_ids):
    encoded = json.dumps(
        sorted({str(value) for value in asset_ids if str(value)}),
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt_binding_sha256(row):
    unhashed = dict(row)
    unhashed.pop("receipt_binding_sha256", None)
    encoded = json.dumps(
        unhashed,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _execution_tape_paths(store):
    return (
        store.root / EXECUTION_RAW_TAPE_FILENAME,
        store.root / EXECUTION_CANONICAL_TAPE_FILENAME,
        store.root / EXECUTION_SESSION_FILENAME,
    )


@contextmanager
def execution_tape_guard(store, operation):
    """Serialize maker-only execution evidence without touching CLOB's lock."""

    anchor = store.root / EXECUTION_TAPE_LOCK_ANCHOR
    lock = acquire_writer_lock(
        anchor,
        owner={
            "resource": EXECUTION_TAPE_LOCK_ANCHOR,
            "event_slug": store.event_slug,
            "operation": str(operation),
        },
        attempts=3,
        stale_after_seconds=300.0,
        sleep_seconds=0.025,
    )
    if lock is None:
        raise RawTapeWriterBusy(
            f"execution tape guard busy for event={store.event_slug}, operation={operation}"
        )
    try:
        yield lock
    finally:
        release_writer_lock(lock)


def _prefix_metadata(path):
    path = Path(path)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return 0, EMPTY_SHA256
    return int(size), sha256_file(path)


def _canonical_execution_row(
    *,
    item,
    binding,
    received_at,
    session_id,
    connection_sequence,
    raw_sha1,
):
    timestamp_ms, exchange_time_utc = _normalize_exchange_timestamp_ms(
        item.get("timestamp")
    )
    asset_id = _asset_id(item)
    condition_id = str(item.get("condition_id") or item.get("market") or "")
    transaction_hash = str(
        item.get("transaction_hash") or item.get("transactionHash") or ""
    ).strip()
    side = str(item.get("side") or "").strip()
    size = item.get("size")
    if size in (None, ""):
        size = item.get("trade_size")
    try:
        price_decimal = Decimal(str(item.get("price")).strip())
        size_decimal = Decimal(str(size).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("last_trade_price has invalid price or size") from exc
    if (
        not asset_id
        or not condition_id
        or not transaction_hash
        or not price_decimal.is_finite()
        or not Decimal("0") <= price_decimal <= Decimal("1")
        or not size_decimal.is_finite()
        or size_decimal <= 0
        or side.upper() not in {"BUY", "SELL"}
    ):
        raise ValueError("last_trade_price is missing valid strict-through evidence")
    return {
        "schema_version": EXECUTION_ROW_SCHEMA_VERSION,
        "received_at_utc": received_at.isoformat(),
        "exchange_time_utc": exchange_time_utc,
        "trade_time_utc": exchange_time_utc,
        "timestamp_utc": exchange_time_utc,
        "exchange_timestamp_ms": timestamp_ms,
        "timestamp_precision_seconds": 0.001,
        "event_slug": binding["event_slug"],
        "market_id": binding["market_id"],
        "event_type": EXECUTION_EVENT_TYPE,
        "asset_id": asset_id,
        "clob_token_id": asset_id,
        "market": condition_id,
        "condition_id": condition_id,
        "price": item.get("price"),
        "size": size,
        "side": side,
        "transaction_hash": transaction_hash,
        "session_id": session_id,
        "local_connection_message_sequence": int(connection_sequence),
        "connection_sequence_scope": CONNECTION_SEQUENCE_SCOPE,
        "book_alignment_sequence_status": BOOK_ALIGNMENT_SEQUENCE_STATUS,
        "raw_sha1": raw_sha1,
    }


def _append_execution_member(
    *,
    binding,
    item,
    received_at,
    session_id,
    connection_sequence,
):
    store = binding["store"]
    raw_path, canonical_path, _session_path = _execution_tape_paths(store)
    digest = payload_sha1(item)
    row = _canonical_execution_row(
        item=item,
        binding=binding,
        received_at=received_at,
        session_id=session_id,
        connection_sequence=connection_sequence,
        raw_sha1=digest,
    )
    raw_record = {
        "schema_version": RAW_EXECUTION_SCHEMA_VERSION,
        "received_at_utc": received_at.isoformat(),
        "event_slug": binding["event_slug"],
        "market_id": binding["market_id"],
        "session_id": session_id,
        "local_connection_message_sequence": int(connection_sequence),
        "connection_sequence_scope": CONNECTION_SEQUENCE_SCOPE,
        "book_alignment_sequence_status": BOOK_ALIGNMENT_SEQUENCE_STATUS,
        "raw_sha1": digest,
        "payload": item,
    }
    with execution_tape_guard(store, "execution_raw_and_canonical_append"):
        if canonical_path.exists():
            with canonical_path.open("r", encoding="utf-8", newline="") as handle:
                existing_header = next(csv.reader(handle), None)
            if existing_header != EXECUTION_TAPE_COLUMNS:
                raise ValueError(
                    f"incompatible execution tape header at {canonical_path}"
                )
        store.append_jsonl(raw_path, raw_record)
        store.append_csv(canonical_path, EXECUTION_TAPE_COLUMNS, [row])
    return row


def fleet_bindings(
    *,
    target_date=None,
    market_ids=None,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    client_factory=PolymarketClient,
    now=None,
):
    """Fetch event metadata and bind each token to one retained event store."""

    selected = set(market_ids or [])
    specs = [spec for spec in all_specs() if not selected or spec.id in selected]
    captured_at = now or utc_now()
    bindings = []
    for spec in specs:
        client = client_factory(target_date=target_date, market_id=spec.id)
        event = client.get_event()
        config = config_from_event(event, fallback_date=client.config.target_date)
        rows = filter_token_rows(
            token_rows_from_event(event, market_id=spec.id, captured_at=captured_at),
            outcomes="all",
        )
        asset_ids = {str(row.get("clob_token_id") or "") for row in rows}
        asset_ids.discard("")
        if not asset_ids:
            continue
        store = MarketMicrostructureStore(
            root=Path(snapshots_root) / config.event_slug,
            event_slug=config.event_slug,
        )
        bindings.append({
            "market_id": spec.id,
            "event_slug": config.event_slug,
            "target_date": config.target_date.isoformat(),
            "asset_ids": asset_ids,
            "store": store,
        })
    return bindings


def _append_session_receipts(
    bindings,
    receipt,
    execution_counts,
    event_market_data_counts,
    event_observed_asset_ids,
):
    for binding in bindings:
        store = binding["store"]
        raw_path, canonical_path, session_path = _execution_tape_paths(store)
        asset_ids = sorted(binding["asset_ids"])
        observed_asset_ids = sorted(
            event_observed_asset_ids.get(binding["event_slug"], set())
        )
        with execution_tape_guard(store, "execution_session_receipt_binding"):
            raw_size, raw_sha256 = _prefix_metadata(raw_path)
            canonical_size, canonical_sha256 = _prefix_metadata(canonical_path)
            row = {
                **receipt,
                "schema_version": BOUND_SESSION_SCHEMA_VERSION,
                "event_slug": binding["event_slug"],
                "market_id": binding["market_id"],
                "target_date": binding["target_date"],
                "subscribed_asset_ids": asset_ids,
                "subscribed_asset_count": len(asset_ids),
                "subscribed_asset_set_sha256": _asset_set_sha256(asset_ids),
                "market_data_message_count": int(
                    event_market_data_counts.get(binding["event_slug"], 0)
                ),
                "observed_subscribed_asset_ids": observed_asset_ids,
                "observed_subscribed_asset_count": len(observed_asset_ids),
                "observed_subscribed_asset_set_sha256": _asset_set_sha256(
                    observed_asset_ids
                ),
                "execution_count": int(execution_counts.get(binding["event_slug"], 0)),
                "raw_tape_filename": EXECUTION_RAW_TAPE_FILENAME,
                "raw_tape_prefix_size_bytes": raw_size,
                "raw_tape_prefix_sha256": raw_sha256,
                "canonical_tape_filename": EXECUTION_CANONICAL_TAPE_FILENAME,
                "canonical_tape_prefix_size_bytes": canonical_size,
                "canonical_tape_prefix_sha256": canonical_sha256,
            }
            row["receipt_binding_sha256"] = _receipt_binding_sha256(row)
            store.append_jsonl(session_path, row)


def _training_window_pause(now):
    if now.tzinfo is None:
        raise ValueError("host-policy clock must be timezone-aware")
    zone = ZoneInfo(HOST_POLICY_TIMEZONE)
    local = now.astimezone(zone)
    start = datetime.combine(local.date(), TRAINING_WINDOW_START, tzinfo=zone)
    restore = datetime.combine(local.date(), TRAINING_WINDOW_RESTORE, tzinfo=zone)
    if not start <= local < restore:
        return None
    return {
        "policy": TRAINING_WINDOW_TASK,
        "reason": "planned_host_policy_pause",
        "timezone": HOST_POLICY_TIMEZONE,
        "start_utc": start.astimezone(timezone.utc).isoformat(),
        "restore_utc": restore.astimezone(timezone.utc).isoformat(),
        "seconds_until_restore": max(
            0.0,
            (restore.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds(),
        ),
    }


def _seconds_until_training_window(now):
    if now.tzinfo is None:
        raise ValueError("host-policy clock must be timezone-aware")
    zone = ZoneInfo(HOST_POLICY_TIMEZONE)
    local = now.astimezone(zone)
    start = datetime.combine(local.date(), TRAINING_WINDOW_START, tzinfo=zone)
    if local >= start:
        start = datetime.combine(
            date.fromordinal(local.date().toordinal() + 1),
            TRAINING_WINDOW_START,
            tzinfo=zone,
        )
    return max(
        0.0,
        (start.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds(),
    )


def _seconds_until_daily_binding_roll(now):
    if now.tzinfo is None:
        raise ValueError("binding-roll clock must be timezone-aware")
    zone = ZoneInfo(HOST_POLICY_TIMEZONE)
    local = now.astimezone(zone)
    roll = datetime.combine(local.date(), DAILY_BINDING_ROLL, tzinfo=zone)
    if local >= roll:
        roll = datetime.combine(
            date.fromordinal(local.date().toordinal() + 1),
            DAILY_BINDING_ROLL,
            tzinfo=zone,
        )
    return max(
        0.0,
        (roll.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds(),
    )


def record_fleet_session(
    bindings,
    *,
    seconds,
    retention_mode,
    lock_scope,
    host_policy_mode,
    websocket_factory=None,
    heartbeat_seconds=10.0,
    connect_timeout=30.0,
    inbound_liveness_seconds=None,
    message_limit=None,
    progress_callback=None,
    preceding_planned_coverage_break=None,
    now_fn=utc_now,
    monotonic_fn=time.monotonic,
):
    """Record one bounded continuous fleet session and durable coverage proof."""

    _validate_contract(
        retention_mode=retention_mode,
        lock_scope=lock_scope,
        host_policy_mode=host_policy_mode,
    )
    if _training_window_pause(now_fn()) is not None:
        raise RuntimeError("host policy forbids connecting during WeatherTrainingWindow")
    asset_ids = sorted({asset for row in bindings for asset in row["asset_ids"]})
    if not asset_ids:
        raise ValueError("continuous execution capture has no active token ids")
    timeout_exceptions = (TimeoutError,)
    if websocket_factory is None:
        websocket_factory = websocket.create_connection
        timeout_exceptions = (TimeoutError, websocket.WebSocketTimeoutException)

    session_id = f"mmexec_{uuid.uuid4().hex}"
    attempt_started_at = now_fn()
    coverage_started_at = None
    coverage_ended_at = None
    subscription = {"operation": "subscribe", "assets_ids": asset_ids}
    base_receive_timeout = max(0.05, min(float(heartbeat_seconds), 10.0))
    inbound_liveness_seconds = max(
        1.0,
        float(
            inbound_liveness_seconds
            if inbound_liveness_seconds is not None
            else max(30.0, float(heartbeat_seconds) * 3.0)
        ),
    )
    ws = None
    messages = 0
    market_data_messages = 0
    execution_counts = {binding["event_slug"]: 0 for binding in bindings}
    event_market_data_counts = {binding["event_slug"]: 0 for binding in bindings}
    event_observed_asset_ids = {
        binding["event_slug"]: set() for binding in bindings
    }
    status = "INCOMPLETE"
    reason = "connection_not_established"
    planned_break = None
    try:
        ws = websocket_factory(CLOB_WS_URL, timeout=connect_timeout)
        planned_break = _training_window_pause(now_fn())
        if planned_break is not None:
            raise PlannedHostPolicyPause("training window began while connecting")
        try:
            ws.settimeout(base_receive_timeout)
        except AttributeError:
            pass
        ws.send(json.dumps(subscription))
        subscription_completed_at = now_fn()
        planned_break = _training_window_pause(subscription_completed_at)
        if planned_break is not None:
            raise PlannedHostPolicyPause("training window began while subscribing")
        deadline = monotonic_fn() + float(seconds)
        next_heartbeat = monotonic_fn() + float(heartbeat_seconds)
        last_inbound_at = monotonic_fn()
        last_market_data_at = last_inbound_at
        status = "COMPLETE"
        reason = "duration_complete"
        if progress_callback is not None:
            progress_callback({
                "session_id": session_id,
                "coverage_start_utc": None,
                "subscription_completed_at_utc": subscription_completed_at.isoformat(),
                "status": "RUNNING",
                "fleet_asset_count": len(asset_ids),
                "message_count": messages,
                "execution_count": 0,
            })
        while monotonic_fn() < deadline:
            if monotonic_fn() - last_market_data_at > inbound_liveness_seconds:
                raise TimeoutError("WebSocket market-data liveness deadline exceeded")
            policy_now = now_fn()
            planned_break = _training_window_pause(policy_now)
            if planned_break is not None:
                reason = "planned_host_policy_pause"
                break
            if message_limit is not None and messages >= int(message_limit):
                status = "INCOMPLETE"
                reason = "message_limit_reached"
                break
            if monotonic_fn() >= next_heartbeat:
                ws.send("PING")
                next_heartbeat = monotonic_fn() + float(heartbeat_seconds)
                if progress_callback is not None:
                    progress_callback({
                        "session_id": session_id,
                        "coverage_start_utc": (
                            coverage_started_at.isoformat()
                            if coverage_started_at is not None
                            else None
                        ),
                        "heartbeat_at_utc": policy_now.isoformat(),
                        "status": "RUNNING",
                        "fleet_asset_count": len(asset_ids),
                        "message_count": messages,
                        "execution_count": sum(execution_counts.values()),
                    })
            receive_timeout = min(
                base_receive_timeout,
                max(0.05, deadline - monotonic_fn()),
                max(0.05, _seconds_until_training_window(policy_now)),
            )
            try:
                ws.settimeout(receive_timeout)
            except AttributeError:
                pass
            try:
                raw = ws.recv()
            except timeout_exceptions:
                if monotonic_fn() - last_inbound_at > inbound_liveness_seconds:
                    raise TimeoutError("WebSocket inbound liveness deadline exceeded")
                continue
            if raw in (None, "", b""):
                raise ConnectionError("WebSocket closed without a close exception")
            received_at = now_fn()
            last_inbound_at = monotonic_fn()
            planned_break = _training_window_pause(received_at)
            if planned_break is not None:
                reason = "planned_host_policy_pause"
                break
            messages += 1
            connection_sequence = messages
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                heartbeat = (
                    raw.decode("utf-8", errors="strict")
                    if isinstance(raw, bytes)
                    else str(raw)
                ).strip().upper()
                if heartbeat in {"PING", "PONG"}:
                    continue
                raise ValueError("unrecognized non-JSON WebSocket frame") from exc
            if isinstance(payload, str) and payload.strip().upper() in {"PING", "PONG"}:
                continue
            if not isinstance(payload, (dict, list)) or (
                isinstance(payload, list)
                and any(not isinstance(item, dict) for item in payload)
            ):
                raise ValueError("unrecognized WebSocket payload shape")
            observed_fleet_assets = _payload_subscribed_asset_ids(
                payload,
                set(asset_ids),
            )
            if observed_fleet_assets:
                market_data_messages += 1
                last_market_data_at = monotonic_fn()
            for binding in bindings:
                observed_event_assets = observed_fleet_assets.intersection(
                    binding["asset_ids"]
                )
                if observed_event_assets:
                    event_market_data_counts[binding["event_slug"]] += 1
                    event_observed_asset_ids[binding["event_slug"]].update(
                        observed_event_assets
                    )
                if coverage_started_at is None and all(
                    event_observed_asset_ids[value["event_slug"]]
                    == set(value["asset_ids"])
                    for value in bindings
                ):
                    coverage_started_at = received_at
                for item in _filter_payload_for_assets(payload, binding["asset_ids"]):
                    _append_execution_member(
                        binding=binding,
                        item=item,
                        received_at=received_at,
                        session_id=session_id,
                        connection_sequence=connection_sequence,
                    )
                    execution_counts[binding["event_slug"]] += 1
        coverage_ended_at = now_fn()
        unobserved_events = [
            binding["event_slug"]
            for binding in bindings
            if event_observed_asset_ids[binding["event_slug"]]
            != set(binding["asset_ids"])
        ]
        if status == "COMPLETE" and unobserved_events:
            status = "INCOMPLETE"
            reason = (
                "planned_host_policy_pause_without_complete_event_readiness"
                if planned_break is not None
                else "event_subscriptions_not_fully_observed:"
                + ",".join(unobserved_events)
            )
    except PlannedHostPolicyPause:
        status = "INCOMPLETE"
        reason = "planned_host_policy_pause_before_subscription"
        coverage_ended_at = None
    except Exception as exc:  # noqa: BLE001 - receipt must survive a broken connection
        status = "INCOMPLETE"
        reason = f"{type(exc).__name__}: {exc}"
        planned_break = None
        coverage_ended_at = now_fn() if coverage_started_at is not None else None
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001 - retain the session receipt
                pass
    attempt_ended_at = now_fn()
    fleet_observed_asset_ids = sorted(
        {asset for values in event_observed_asset_ids.values() for asset in values}
    )
    receipt = {
        "schema_version": BOUND_SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "attempt_start_utc": attempt_started_at.isoformat(),
        "attempt_end_utc": attempt_ended_at.isoformat(),
        "coverage_start_utc": (
            coverage_started_at.isoformat() if coverage_started_at is not None else None
        ),
        "coverage_end_utc": (
            coverage_ended_at.isoformat() if coverage_ended_at is not None else None
        ),
        "status": status,
        "reason": reason,
        "continuous_coverage": (
            status == "COMPLETE"
            and coverage_started_at is not None
            and coverage_ended_at is not None
        ),
        "requested_duration_seconds": float(seconds),
        "fleet_asset_count": len(asset_ids),
        "message_count": messages,
        "market_data_message_count": market_data_messages,
        "fleet_observed_subscribed_asset_count": len(fleet_observed_asset_ids),
        "fleet_observed_subscribed_asset_set_sha256": _asset_set_sha256(
            fleet_observed_asset_ids
        ),
        "inbound_liveness_timeout_seconds": inbound_liveness_seconds,
        "local_connection_message_sequence_start": 1 if messages else 0,
        "local_connection_message_sequence_end": messages,
        "connection_sequence_scope": CONNECTION_SEQUENCE_SCOPE,
        "event_row_count": sum(execution_counts.values()),
        "retention_mode": retention_mode,
        "lock_scope": lock_scope,
        "host_policy_mode": host_policy_mode,
        "protected_window_behavior": "append_only_execution_evidence_exception",
        "planned_coverage_break": planned_break,
        "preceding_planned_coverage_break": preceding_planned_coverage_break,
    }
    _append_session_receipts(
        bindings,
        receipt,
        execution_counts,
        event_market_data_counts,
        event_observed_asset_ids,
    )
    return receipt


def run_loop(
    *,
    retention_mode,
    lock_scope,
    host_policy_mode,
    market_ids=None,
    target_date=None,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    status_path=DEFAULT_STATUS_PATH,
    session_seconds=86400.0,
    reconnect_seconds=1.0,
    once=False,
    now_fn=utc_now,
    sleep_fn=time.sleep,
):
    _validate_contract(
        retention_mode=retention_mode,
        lock_scope=lock_scope,
        host_policy_mode=host_policy_mode,
    )
    connection_attempts = 0
    unplanned_reconnects = 0
    pending_planned_break = None
    while True:
        generated_at = now_fn()
        planned_break = _training_window_pause(generated_at)
        if planned_break is not None:
            pending_planned_break = planned_break
            payload = {
                "schema_version": STATUS_SCHEMA_VERSION,
                "generated_at_utc": generated_at.isoformat(),
                "status": "PAUSED",
                "reason": "planned_host_policy_pause",
                "planned_coverage_break": planned_break,
                "host_policy_mode": host_policy_mode,
                "connection_attempt_count": connection_attempts,
                "unplanned_reconnect_count": unplanned_reconnects,
                "snapshots_root": str(snapshots_root),
            }
            write_json_atomic(status_path, payload)
            if once:
                return payload
            sleep_fn(min(60.0, max(0.05, planned_break["seconds_until_restore"])))
            continue
        try:
            bindings = fleet_bindings(
                target_date=target_date,
                market_ids=market_ids,
                snapshots_root=snapshots_root,
                now=generated_at,
            )

            def write_progress(session):
                write_json_atomic(status_path, {
                    "schema_version": STATUS_SCHEMA_VERSION,
                    "generated_at_utc": now_fn().isoformat(),
                    "status": "RUNNING",
                    "session": session,
                    "event_count": len(bindings),
                    "connection_attempt_count": connection_attempts,
                    "unplanned_reconnect_count": unplanned_reconnects,
                    "snapshots_root": str(snapshots_root),
                })

            connection_attempts += 1
            bounded_session_seconds = min(
                float(session_seconds),
                max(0.05, _seconds_until_daily_binding_roll(now_fn())),
            )
            receipt = record_fleet_session(
                bindings,
                seconds=bounded_session_seconds,
                retention_mode=retention_mode,
                lock_scope=lock_scope,
                host_policy_mode=host_policy_mode,
                progress_callback=write_progress,
                preceding_planned_coverage_break=pending_planned_break,
                now_fn=now_fn,
            )
            pending_planned_break = None
            paused = str(receipt.get("reason") or "").startswith(
                "planned_host_policy_pause"
            )
            if receipt.get("status") != "COMPLETE" and not paused:
                unplanned_reconnects += 1
            payload = {
                "schema_version": STATUS_SCHEMA_VERSION,
                "generated_at_utc": now_fn().isoformat(),
                "status": "PAUSED" if paused else receipt["status"],
                "session": receipt,
                "event_count": len(bindings),
                "connection_attempt_count": connection_attempts,
                "unplanned_reconnect_count": unplanned_reconnects,
                "snapshots_root": str(snapshots_root),
            }
        except Exception as exc:  # noqa: BLE001 - supervisor loop records and retries
            unplanned_reconnects += 1
            payload = {
                "schema_version": STATUS_SCHEMA_VERSION,
                "generated_at_utc": now_fn().isoformat(),
                "status": "BLOCK",
                "error": f"{type(exc).__name__}: {exc}",
                "connection_attempt_count": connection_attempts,
                "unplanned_reconnect_count": unplanned_reconnects,
                "snapshots_root": str(snapshots_root),
            }
        write_json_atomic(status_path, payload)
        if once:
            return payload
        if payload.get("status") != "PAUSED":
            sleep_fn(max(0.0, float(reconnect_seconds)))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Capture continuous, execution-only maker evidence"
    )
    parser.add_argument("--market", default="all", help="all or comma-separated built-in market ids")
    parser.add_argument("--target-date", type=date.fromisoformat)
    parser.add_argument("--session-seconds", type=float, default=86400.0)
    parser.add_argument("--reconnect-seconds", type=float, default=1.0)
    parser.add_argument(
        "--retention-mode",
        required=True,
        choices=[RETENTION_MODE],
        help="retain individual last_trade_price members only",
    )
    parser.add_argument(
        "--lock-scope",
        required=True,
        choices=[LOCK_SCOPE],
        help="use the maker-only mm_execution_tape writer lock",
    )
    parser.add_argument(
        "--host-policy-mode",
        required=True,
        choices=[HOST_POLICY_MODE],
        help="disconnect for WeatherTrainingWindow and resume after 04:15 local",
    )
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    market_ids = (
        None
        if args.market == "all"
        else [item.strip() for item in args.market.split(",") if item.strip()]
    )
    payload = run_loop(
        market_ids=market_ids,
        target_date=args.target_date,
        session_seconds=args.session_seconds,
        reconnect_seconds=args.reconnect_seconds,
        retention_mode=args.retention_mode,
        lock_scope=args.lock_scope,
        host_policy_mode=args.host_policy_mode,
        once=args.once,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") != "BLOCK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
