"""Continuous, fleet-wide market WebSocket capture for maker-day evidence.

This producer is deliberately separate from the latency-critical raw-book loop.
It subscribes every active built-in token on one connection, routes retained
messages to the owning event folder, and writes a per-event session receipt.
The paper scorer treats absent or incomplete receipts as non-countable.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import date
from pathlib import Path

import websocket

from weather.io import write_json_atomic
from weather.market.market_config import config_from_event
from weather.market.market_microstructure_capture import (
    MarketMicrostructureStore,
    filter_token_rows,
    payload_sha1,
    token_rows_from_event,
    utc_now,
    ws_summary_rows,
)
from weather.market.market_microstructure_constants import CLOB_WS_URL
from weather.market.market_registry import all_specs
from weather.market.mm_paper_constants import EXECUTION_SESSION_FILENAME
from weather.market.polymarket_client import PolymarketClient
from weather.paths import data_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_execution_capture_session")
STATUS_SCHEMA_VERSION = schema_version("mm_execution_capture_status")
SESSION_FILENAME = EXECUTION_SESSION_FILENAME
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_STATUS_PATH = DEFAULT_SNAPSHOTS_ROOT / "market_execution_capture_status.json"


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
    """Return only payload members owned by one event."""

    filtered = []
    for item in _payload_items(payload):
        if not isinstance(item, dict):
            continue
        changes = item.get("price_changes")
        if isinstance(changes, list):
            kept = [change for change in changes if _asset_id(change) in asset_ids]
            if kept:
                filtered.append({**item, "price_changes": kept})
            continue
        if _asset_id(item) in asset_ids:
            filtered.append(item)
    if not filtered:
        return None
    return filtered if isinstance(payload, list) else filtered[0]


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


def _append_session_receipts(bindings, receipt):
    for binding in bindings:
        row = {
            **receipt,
            "event_slug": binding["event_slug"],
            "market_id": binding["market_id"],
            "target_date": binding["target_date"],
            "subscribed_asset_count": len(binding["asset_ids"]),
        }
        store = binding["store"]
        with store.raw_tape_guard("continuous_execution_session_receipt"):
            store.append_jsonl(store.root / SESSION_FILENAME, row)


def record_fleet_session(
    bindings,
    *,
    seconds,
    websocket_factory=None,
    heartbeat_seconds=10.0,
    connect_timeout=30.0,
    message_limit=None,
    progress_callback=None,
    now_fn=utc_now,
    monotonic_fn=time.monotonic,
):
    """Record one bounded continuous fleet session and durable coverage proof."""

    asset_ids = sorted({asset for row in bindings for asset in row["asset_ids"]})
    if not asset_ids:
        raise ValueError("continuous execution capture has no active token ids")
    timeout_exceptions = (TimeoutError,)
    if websocket_factory is None:
        websocket_factory = websocket.create_connection
        timeout_exceptions = (TimeoutError, websocket.WebSocketTimeoutException)

    session_id = f"mmexec_{uuid.uuid4().hex}"
    started_at = now_fn()
    subscription = {"operation": "subscribe", "assets_ids": asset_ids}
    deadline = monotonic_fn() + float(seconds)
    next_heartbeat = monotonic_fn() + float(heartbeat_seconds)
    ws = websocket_factory(CLOB_WS_URL, timeout=connect_timeout)
    try:
        ws.settimeout(max(1.0, min(float(heartbeat_seconds), 10.0)))
    except AttributeError:
        pass
    ws.send(json.dumps(subscription))
    messages = 0
    event_rows = 0
    status = "COMPLETE"
    reason = "duration_complete"
    if progress_callback is not None:
        progress_callback({
            "session_id": session_id,
            "coverage_start_utc": started_at.isoformat(),
            "status": "RUNNING",
            "fleet_asset_count": len(asset_ids),
            "message_count": messages,
            "event_row_count": event_rows,
        })
    try:
        while monotonic_fn() < deadline:
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
                        "coverage_start_utc": started_at.isoformat(),
                        "heartbeat_at_utc": now_fn().isoformat(),
                        "status": "RUNNING",
                        "fleet_asset_count": len(asset_ids),
                        "message_count": messages,
                        "event_row_count": event_rows,
                    })
            try:
                raw = ws.recv()
            except timeout_exceptions:
                continue
            if raw in (None, "", b""):
                raise ConnectionError("WebSocket closed without a close exception")
            received_at = now_fn()
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                payload = raw
            for binding in bindings:
                event_payload = _filter_payload_for_assets(payload, binding["asset_ids"])
                if event_payload is None:
                    continue
                digest = payload_sha1(event_payload)
                rows = ws_summary_rows(
                    received_at,
                    binding["event_slug"],
                    binding["market_id"],
                    event_payload,
                    raw_sha1=digest,
                )
                store = binding["store"]
                with store.raw_tape_guard("continuous_execution_ws_append"):
                    store.write_ws_events(rows, {
                        "received_at_utc": received_at.isoformat(),
                        "event_slug": binding["event_slug"],
                        "market_id": binding["market_id"],
                        "session_id": session_id,
                        "subscription_asset_count": len(asset_ids),
                        "raw_sha1": digest,
                        "event_rows": len(rows),
                        "payload": event_payload,
                    })
                event_rows += len(rows)
            messages += 1
    except Exception as exc:  # noqa: BLE001 - receipt must survive a broken connection
        status = "INCOMPLETE"
        reason = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001 - retain the session receipt
            pass
    ended_at = now_fn()
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "coverage_start_utc": started_at.isoformat(),
        "coverage_end_utc": ended_at.isoformat(),
        "status": status,
        "reason": reason,
        "continuous_coverage": status == "COMPLETE",
        "requested_duration_seconds": float(seconds),
        "fleet_asset_count": len(asset_ids),
        "message_count": messages,
        "event_row_count": event_rows,
    }
    _append_session_receipts(bindings, receipt)
    return receipt


def run_loop(
    *,
    market_ids=None,
    target_date=None,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    status_path=DEFAULT_STATUS_PATH,
    session_seconds=86400.0,
    reconnect_seconds=1.0,
    once=False,
):
    while True:
        generated_at = utc_now()
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
                    "generated_at_utc": utc_now().isoformat(),
                    "status": "RUNNING",
                    "session": session,
                    "event_count": len(bindings),
                    "snapshots_root": str(snapshots_root),
                })

            receipt = record_fleet_session(
                bindings,
                seconds=session_seconds,
                progress_callback=write_progress,
            )
            payload = {
                "schema_version": STATUS_SCHEMA_VERSION,
                "generated_at_utc": utc_now().isoformat(),
                "status": receipt["status"],
                "session": receipt,
                "event_count": len(bindings),
                "snapshots_root": str(snapshots_root),
            }
        except Exception as exc:  # noqa: BLE001 - supervisor loop records and retries
            payload = {
                "schema_version": STATUS_SCHEMA_VERSION,
                "generated_at_utc": utc_now().isoformat(),
                "status": "BLOCK",
                "error": f"{type(exc).__name__}: {exc}",
                "snapshots_root": str(snapshots_root),
            }
        write_json_atomic(status_path, payload)
        if once:
            return payload
        time.sleep(max(0.0, float(reconnect_seconds)))


def build_parser():
    parser = argparse.ArgumentParser(description="Capture continuous maker execution evidence")
    parser.add_argument("--market", default="all", help="all or comma-separated built-in market ids")
    parser.add_argument("--target-date", type=date.fromisoformat)
    parser.add_argument("--session-seconds", type=float, default=86400.0)
    parser.add_argument("--reconnect-seconds", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    market_ids = None if args.market == "all" else [item.strip() for item in args.market.split(",") if item.strip()]
    payload = run_loop(
        market_ids=market_ids,
        target_date=args.target_date,
        session_seconds=args.session_seconds,
        reconnect_seconds=args.reconnect_seconds,
        once=args.once,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") != "BLOCK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
