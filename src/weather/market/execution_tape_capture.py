"""Read-only public websocket producer for the execution tape.

Nothing in this module registers, schedules, or starts a background task.  The
``capture`` command is an explicit operator action.  Offline fixture replay and
sizing are separate commands and never open a network connection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from weather.io import read_json
from weather.market.execution_tape_store import (
    DEFAULT_MAX_PART_BYTES,
    DEFAULT_SNAPSHOTS_ROOT,
    ExecutionTapeCoordinator,
    ExecutionTapeError,
    MarketDaySeed,
    ensure_utc,
    fixture_seed,
    sizing_from_fixture,
)
from weather.market.market_config import config_for_date, ensure_date
from weather.market.market_microstructure_constants import CLOB_WS_URL
from weather.market.market_registry import all_specs, spec_for_id
from weather.paths import config_path
from weather.schema_registry import schema_version


DEFAULT_EVENT_METADATA = config_path("location_market_events.json")
DEFAULT_EVENT_METADATA_MAX_AGE_HOURS = 36.0
DEFAULT_HEARTBEAT_SECONDS = 10.0
DEFAULT_INBOUND_SILENCE_TIMEOUT_SECONDS = 30.0
DEFAULT_SEED_CHECK_SECONDS = 60.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 30.0
DEFAULT_RECONNECT_BASE_SECONDS = 1.0
DEFAULT_RECONNECT_MAX_SECONDS = 30.0
DEFAULT_MAX_TOKENS_PER_CONNECTION = 100


class ExecutionTapeSeedError(ExecutionTapeError):
    """Raised when an auditable current market-day subscription cannot be built."""


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionTapeSeedError(f"cannot read execution-tape seed metadata {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExecutionTapeSeedError(f"execution-tape seed metadata is not an object: {path}")
    return payload


def _parse_generated_at(payload: dict[str, Any], *, now: datetime, max_age_hours: float) -> str:
    value = payload.get("generated_at_utc")
    if not value:
        raise ExecutionTapeSeedError("location_market_events metadata has no generated_at_utc")
    try:
        generated_at = ensure_utc(str(value))
    except (TypeError, ValueError) as exc:
        raise ExecutionTapeSeedError("location_market_events generated_at_utc is invalid") from exc
    age_hours = (now - generated_at).total_seconds() / 3600.0
    if age_hours < -0.25:
        raise ExecutionTapeSeedError(
            f"location_market_events metadata is from the future ({age_hours:.2f}h)"
        )
    if age_hours > float(max_age_hours):
        raise ExecutionTapeSeedError(
            f"location_market_events metadata is stale ({age_hours:.2f}h > {max_age_hours:.2f}h)"
        )
    return generated_at.isoformat()


def selected_market_ids(value: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",") if item.strip()]
    else:
        values = [str(item).strip() for item in value if str(item).strip()]
    if not values or values == ["all"]:
        return tuple(spec.id for spec in all_specs())
    valid = {spec.id for spec in all_specs()}
    unknown = sorted(set(values) - valid)
    if unknown:
        raise ExecutionTapeSeedError(f"unknown market ids: {', '.join(unknown)}")
    return tuple(dict.fromkeys(values))


def load_market_day_seeds(
    event_metadata_path: str | Path = DEFAULT_EVENT_METADATA,
    *,
    markets: str | Iterable[str] = "all",
    target_date: str | date | None = None,
    now: datetime | str | None = None,
    max_age_hours: float = DEFAULT_EVENT_METADATA_MAX_AGE_HOURS,
) -> tuple[MarketDaySeed, ...]:
    """Load fail-closed subscription seeds from retained generated metadata."""

    now_utc = ensure_utc(now)
    path = Path(event_metadata_path)
    payload = _read_json(path)
    expected_schema = schema_version("location_market_events")
    if payload.get("schema_version") != expected_schema:
        raise ExecutionTapeSeedError(
            f"location_market_events schema mismatch: {payload.get('schema_version')} != {expected_schema}"
        )
    generated_at = _parse_generated_at(payload, now=now_utc, max_age_hours=max_age_hours)
    locations = {
        str(row.get("location_id") or ""): row
        for row in payload.get("locations") or []
        if isinstance(row, dict) and row.get("location_id")
    }
    seeds: list[MarketDaySeed] = []
    for market_id in selected_market_ids(markets):
        spec = spec_for_id(market_id)
        target = ensure_date(target_date) if target_date is not None else now_utc.astimezone(spec.tz).date()
        expected_slug = config_for_date(target, market_id).event_slug
        location = locations.get(market_id)
        if not location:
            raise ExecutionTapeSeedError(f"location_market_events is missing market {market_id}")
        candidates = [
            event
            for event in location.get("active_events") or []
            if isinstance(event, dict)
            and (
                str(event.get("event_date") or "") == target.isoformat()
                or str(event.get("event_slug") or "") == expected_slug
            )
        ]
        if len(candidates) != 1:
            raise ExecutionTapeSeedError(
                f"expected one active event for {market_id} {target.isoformat()}, found {len(candidates)}"
            )
        event = candidates[0]
        if str(event.get("event_slug") or "") != expected_slug:
            raise ExecutionTapeSeedError(
                f"event slug mismatch for {market_id}: {event.get('event_slug')} != {expected_slug}"
            )
        markets_payload = [row for row in event.get("markets") or [] if isinstance(row, dict)]
        if not markets_payload:
            raise ExecutionTapeSeedError(f"event {expected_slug} has no condition markets")
        for condition in markets_payload:
            if condition.get("active") is False or condition.get("closed") is True:
                raise ExecutionTapeSeedError(f"event {expected_slug} includes an inactive condition market")
            outcomes = condition.get("outcomes") or []
            token_ids = [
                str(row.get("token_id") or "").strip()
                for row in outcomes
                if isinstance(row, dict)
            ]
            if len(token_ids) != 2 or any(not token_id for token_id in token_ids):
                raise ExecutionTapeSeedError(
                    f"event {expected_slug} condition {condition.get('condition_id')} lacks two CLOB tokens"
                )
        seed = MarketDaySeed.from_event(
            event,
            market_id=market_id,
            target_date=target,
            source=str(path),
            source_generated_at_utc=generated_at,
        )
        if len(seed.condition_ids) != len(markets_payload):
            raise ExecutionTapeSeedError(f"event {expected_slug} has blank or duplicate condition ids")
        if len(seed.asset_ids) != len(markets_payload) * 2:
            raise ExecutionTapeSeedError(f"event {expected_slug} has blank or duplicate asset ids")
        seeds.append(seed)
    return tuple(seeds)


def seed_set_sha256(seeds: Iterable[MarketDaySeed]) -> str:
    payload = [seed.content_payload() for seed in sorted(seeds, key=lambda row: row.key)]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def partition_market_days(
    seeds: Iterable[MarketDaySeed],
    *,
    max_tokens_per_connection: int = DEFAULT_MAX_TOKENS_PER_CONNECTION,
) -> tuple[tuple[MarketDaySeed, ...], ...]:
    """Partition without splitting one market-day across connections."""

    limit = int(max_tokens_per_connection)
    if limit <= 0:
        raise ValueError("max_tokens_per_connection must be positive")
    groups: list[list[MarketDaySeed]] = []
    current: list[MarketDaySeed] = []
    current_tokens = 0
    for seed in sorted(seeds, key=lambda row: row.key):
        token_count = len(seed.asset_ids)
        if token_count > limit:
            raise ExecutionTapeSeedError(
                f"market-day {seed.key} has {token_count} tokens, above connection limit {limit}"
            )
        if current and current_tokens + token_count > limit:
            groups.append(current)
            current = []
            current_tokens = 0
        current.append(seed)
        current_tokens += token_count
    if current:
        groups.append(current)
    return tuple(tuple(group) for group in groups)


def subscription_payload(seeds: Iterable[MarketDaySeed]) -> dict[str, Any]:
    asset_ids = sorted({asset_id for seed in seeds for asset_id in seed.asset_ids})
    if not asset_ids:
        raise ExecutionTapeSeedError("cannot subscribe without asset ids")
    return {"assets_ids": asset_ids, "type": "market"}


def confirmed_subscription_assets(
    raw: bytes | str | dict[str, Any] | list[Any],
    seeds: Iterable[MarketDaySeed],
) -> dict[str, tuple[str, ...]]:
    """Return exact requested assets evidenced by one inbound market frame."""

    if raw == "PONG" or raw == b"PONG":
        return {}
    try:
        if isinstance(raw, bytes):
            payload = json.loads(raw.decode("utf-8"))
        elif isinstance(raw, str):
            payload = json.loads(raw)
        else:
            payload = raw
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}

    seed_rows = tuple(seeds)
    confirmed: dict[str, set[str]] = {}
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if not isinstance(item, dict):
            continue
        event_type = item.get("event_type")
        if event_type not in {
            "book",
            "price_change",
            "last_trade_price",
            "tick_size_change",
            "best_bid_ask",
            "new_market",
            "market_resolved",
        }:
            continue
        condition_id = str(item.get("market") or "").strip().lower()
        assets = {str(item.get("asset_id") or "").strip()}
        price_changes = item.get("price_changes")
        assets.update(
            str(row.get("asset_id") or "").strip()
            for row in (price_changes if isinstance(price_changes, list) else [])
            if isinstance(row, dict)
        )
        asset_ids = item.get("assets_ids")
        assets.update(
            str(value).strip()
            for value in (asset_ids if isinstance(asset_ids, list) else [])
        )
        for seed in seed_rows:
            matched = {
                asset_id
                for asset_id in set(seed.asset_ids).intersection(assets)
                if seed.condition_for_asset(asset_id) == condition_id
            }
            if matched:
                confirmed.setdefault(seed.key, set()).update(matched)
    return {
        key: tuple(sorted(values))
        for key, values in sorted(confirmed.items())
    }


def confirmed_subscription_routes(
    raw: bytes | str | dict[str, Any] | list[Any],
    seeds: Iterable[MarketDaySeed],
) -> tuple[str, ...]:
    """Return routes whose every requested asset is proven by this frame."""

    seed_rows = tuple(seeds)
    confirmed_assets = confirmed_subscription_assets(raw, seed_rows)
    return tuple(sorted(
        seed.key
        for seed in seed_rows
        if set(seed.asset_ids).issubset(confirmed_assets.get(seed.key, ()))
    ))


def frame_proves_subscription(
    raw: bytes | str | dict[str, Any] | list[Any],
    seeds: Iterable[MarketDaySeed],
) -> bool:
    """Return whether a frame proves at least one requested market-day route."""

    return bool(confirmed_subscription_routes(raw, seeds))


def _default_websocket_factory(url: str, *, timeout: float):
    try:
        import websocket  # type: ignore
    except ImportError as exc:
        raise RuntimeError("websocket-client is required for execution-tape capture") from exc
    return websocket.create_connection(url, timeout=timeout)


def _timeout_exceptions() -> tuple[type[BaseException], ...]:
    try:
        import websocket  # type: ignore
    except ImportError:
        return (TimeoutError,)
    return (TimeoutError, websocket.WebSocketTimeoutException)


def run_connection_once(
    coordinator: ExecutionTapeCoordinator,
    seeds: tuple[MarketDaySeed, ...],
    *,
    stop_event: threading.Event,
    websocket_factory: Callable[..., Any] | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    inbound_silence_timeout_seconds: float = DEFAULT_INBOUND_SILENCE_TIMEOUT_SECONDS,
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic_fn: Callable[[], float] = time.monotonic,
    max_messages: int | None = None,
) -> dict[str, Any]:
    """Run one documented websocket session; reconnect policy is owned above."""

    if float(heartbeat_seconds) <= 0:
        raise ValueError("heartbeat_seconds must be positive")
    if float(connect_timeout_seconds) <= 0:
        raise ValueError("connect_timeout_seconds must be positive")
    if float(inbound_silence_timeout_seconds) <= float(heartbeat_seconds):
        raise ValueError("inbound silence timeout must exceed the heartbeat interval")
    websocket_factory = websocket_factory or _default_websocket_factory
    route_keys = tuple(seed.key for seed in seeds)
    session_id = uuid.uuid4().hex
    coordinator.begin_connecting(route_keys, session_id=session_id, at=now_fn())
    websocket = None
    messages = 0
    reason = "session_ended"
    try:
        websocket = websocket_factory(CLOB_WS_URL, timeout=float(connect_timeout_seconds))
        recv_timeout = max(0.1, min(float(heartbeat_seconds), 1.0))
        try:
            websocket.settimeout(recv_timeout)
        except AttributeError:
            pass
        frame = subscription_payload(seeds)
        websocket.send(json.dumps(frame, sort_keys=True))
        required_assets_by_route = {
            seed.key: set(seed.asset_ids)
            for seed in seeds
        }
        confirmed_assets_by_route = {
            seed.key: set()
            for seed in seeds
        }
        unconfirmed_route_keys = set(route_keys)
        confirmation_deadline = monotonic_fn() + float(connect_timeout_seconds)
        last_inbound_monotonic = monotonic_fn()
        next_ping = monotonic_fn() + float(heartbeat_seconds)
        while not stop_event.is_set():
            if unconfirmed_route_keys and monotonic_fn() >= confirmation_deadline:
                raise TimeoutError("subscription was not confirmed by a routed market frame")
            if (
                not unconfirmed_route_keys
                and monotonic_fn() - last_inbound_monotonic
                >= float(inbound_silence_timeout_seconds)
            ):
                raise TimeoutError("no inbound server heartbeat or market frame before silence deadline")
            if max_messages is not None and messages >= int(max_messages):
                reason = "message_limit_reached"
                break
            if monotonic_fn() >= next_ping:
                websocket.send("PING")
                next_ping = monotonic_fn() + float(heartbeat_seconds)
                coordinator.heartbeat(route_keys, at=now_fn())
            try:
                raw = websocket.recv()
            except _timeout_exceptions():
                continue
            if raw in (None, "", b""):
                raise ConnectionError("websocket returned an empty frame")
            last_inbound_monotonic = monotonic_fn()
            if raw in ("PONG", b"PONG"):
                coordinator.heartbeat(route_keys, at=now_fn())
                continue
            received_at = now_fn()
            for route_key, asset_ids in confirmed_subscription_assets(raw, seeds).items():
                confirmed_assets_by_route[route_key].update(asset_ids)
            newly_confirmed = {
                route_key
                for route_key in unconfirmed_route_keys
                if required_assets_by_route[route_key].issubset(
                    confirmed_assets_by_route[route_key]
                )
            }
            if newly_confirmed:
                coordinator.mark_connected(
                    tuple(sorted(newly_confirmed)),
                    session_id=session_id,
                    at=received_at,
                )
                unconfirmed_route_keys.difference_update(newly_confirmed)
            coordinator.heartbeat(route_keys, at=received_at, message_seen=True)
            coordinator.ingest_frame(raw, session_id=session_id, received_at=received_at)
            messages += 1
        if stop_event.is_set():
            reason = "stop_requested"
        return {
            "session_id": session_id,
            "messages": messages,
            "subscription": frame,
            "reason": reason,
        }
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        disconnected_at = now_fn()
        try:
            coordinator.mark_disconnected(
                route_keys,
                session_id=session_id,
                at=disconnected_at,
                reason=reason,
            )
        finally:
            if websocket is not None:
                try:
                    websocket.close()
                except Exception:
                    pass


def connection_worker(
    coordinator: ExecutionTapeCoordinator,
    seeds: tuple[MarketDaySeed, ...],
    *,
    stop_event: threading.Event,
    websocket_factory: Callable[..., Any] | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    inbound_silence_timeout_seconds: float = DEFAULT_INBOUND_SILENCE_TIMEOUT_SECONDS,
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    reconnect_base_seconds: float = DEFAULT_RECONNECT_BASE_SECONDS,
    reconnect_max_seconds: float = DEFAULT_RECONNECT_MAX_SECONDS,
) -> None:
    route_keys = tuple(seed.key for seed in seeds)
    delay = max(0.1, float(reconnect_base_seconds))
    while not stop_event.is_set():
        try:
            run_connection_once(
                coordinator,
                seeds,
                stop_event=stop_event,
                websocket_factory=websocket_factory,
                heartbeat_seconds=heartbeat_seconds,
                inbound_silence_timeout_seconds=inbound_silence_timeout_seconds,
                connect_timeout_seconds=connect_timeout_seconds,
            )
            delay = max(0.1, float(reconnect_base_seconds))
        except Exception:
            if stop_event.is_set():
                break
            waited = 0.0
            while waited < delay and not stop_event.is_set():
                step = min(1.0, delay - waited)
                stop_event.wait(step)
                waited += step
                coordinator.heartbeat(route_keys, at=datetime.now(timezone.utc))
            delay = min(float(reconnect_max_seconds), max(delay * 2.0, delay))


class ConnectionFleet:
    def __init__(
        self,
        coordinator: ExecutionTapeCoordinator,
        groups: Iterable[tuple[MarketDaySeed, ...]],
        *,
        websocket_factory: Callable[..., Any] | None = None,
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
        inbound_silence_timeout_seconds: float = DEFAULT_INBOUND_SILENCE_TIMEOUT_SECONDS,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        reconnect_base_seconds: float = DEFAULT_RECONNECT_BASE_SECONDS,
        reconnect_max_seconds: float = DEFAULT_RECONNECT_MAX_SECONDS,
    ) -> None:
        self.stop_event = threading.Event()
        self.threads = [
            threading.Thread(
                target=connection_worker,
                kwargs={
                    "coordinator": coordinator,
                    "seeds": group,
                    "stop_event": self.stop_event,
                    "websocket_factory": websocket_factory,
                    "heartbeat_seconds": heartbeat_seconds,
                    "inbound_silence_timeout_seconds": inbound_silence_timeout_seconds,
                    "connect_timeout_seconds": connect_timeout_seconds,
                    "reconnect_base_seconds": reconnect_base_seconds,
                    "reconnect_max_seconds": reconnect_max_seconds,
                },
                name=f"execution-tape-{index + 1}",
                daemon=True,
            )
            for index, group in enumerate(groups)
        ]

    def start(self) -> None:
        for thread in self.threads:
            thread.start()

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        self.stop_event.set()
        deadline = time.monotonic() + float(timeout_seconds)
        for thread in self.threads:
            thread.join(max(0.0, deadline - time.monotonic()))


def run_live_capture(
    *,
    event_metadata_path: str | Path = DEFAULT_EVENT_METADATA,
    markets: str | Iterable[str] = "all",
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
    max_tokens_per_connection: int = DEFAULT_MAX_TOKENS_PER_CONNECTION,
    seed_check_seconds: float = DEFAULT_SEED_CHECK_SECONDS,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    inbound_silence_timeout_seconds: float = DEFAULT_INBOUND_SILENCE_TIMEOUT_SECONDS,
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    max_age_hours: float = DEFAULT_EVENT_METADATA_MAX_AGE_HOURS,
    shutdown_event: threading.Event | None = None,
    websocket_factory: Callable[..., Any] | None = None,
) -> None:
    """Run until interrupted, reloading only auditable retained event metadata."""

    shutdown = shutdown_event or threading.Event()
    coordinator = ExecutionTapeCoordinator(
        (),
        snapshots_root=snapshots_root,
        max_part_bytes=max_part_bytes,
    )
    fleet: ConnectionFleet | None = None
    active_signature: str | None = None
    try:
        while not shutdown.is_set():
            now = datetime.now(timezone.utc)
            try:
                seeds = load_market_day_seeds(
                    event_metadata_path,
                    markets=markets,
                    now=now,
                    max_age_hours=max_age_hours,
                )
                signature = seed_set_sha256(seeds)
            except Exception as exc:
                if fleet is not None:
                    fleet.stop()
                    fleet = None
                    active_signature = None
                coordinator.set_seed_error(f"{type(exc).__name__}: {exc}", now=now)
            else:
                if signature != active_signature:
                    if fleet is not None:
                        fleet.stop()
                    coordinator.replace_seeds(seeds, now=now)
                    groups = partition_market_days(
                        seeds,
                        max_tokens_per_connection=max_tokens_per_connection,
                    )
                    fleet = ConnectionFleet(
                        coordinator,
                        groups,
                        websocket_factory=websocket_factory,
                        heartbeat_seconds=heartbeat_seconds,
                        inbound_silence_timeout_seconds=inbound_silence_timeout_seconds,
                        connect_timeout_seconds=connect_timeout_seconds,
                    )
                    fleet.start()
                    active_signature = signature
            shutdown.wait(float(seed_check_seconds))
    except KeyboardInterrupt:
        shutdown.set()
    finally:
        if fleet is not None:
            fleet.stop()
        coordinator.stop(now=datetime.now(timezone.utc), reason="capture_service_stopped")
        coordinator.close()


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ExecutionTapeError(f"invalid fixture JSON at line {line_number}") from exc
            if not isinstance(row, dict):
                raise ExecutionTapeError(f"fixture row {line_number} is not an object")
            rows.append(row)
    return rows


def replay_fixture(
    fixture_path: str | Path,
    *,
    snapshots_root: str | Path,
    market_id: str = "fixture_market",
    target_date: str | date = "2026-08-10",
    event_slug: str = "execution-tape-fixture-2026-08-10",
    max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
) -> dict[str, Any]:
    """Offline harness used by tests and operator reproduction."""

    fixture_path = Path(fixture_path)
    rows = _load_jsonl(fixture_path)
    seed = fixture_seed(
        rows,
        market_id=market_id,
        target_date=ensure_date(target_date),
        event_slug=event_slug,
        source=str(fixture_path),
    )
    first_time = ensure_utc(datetime.fromtimestamp(int(rows[0]["timestamp"]) / 1000.0, timezone.utc))
    session_id = "fixture-replay"
    coordinator = ExecutionTapeCoordinator(
        (seed,),
        snapshots_root=snapshots_root,
        max_part_bytes=max_part_bytes,
        now=first_time,
    )
    try:
        coordinator.begin_connecting((seed.key,), session_id=session_id, at=first_time)
        coordinator.mark_connected((seed.key,), session_id=session_id, at=first_time)
        for row in rows:
            received_at = datetime.fromtimestamp(int(row["timestamp"]) / 1000.0, timezone.utc)
            coordinator.ingest_frame(row, session_id=session_id, received_at=received_at)
        final_time = datetime.fromtimestamp(int(rows[-1]["timestamp"]) / 1000.0, timezone.utc)
        payload = coordinator.status_payload(now=final_time)
        return payload
    finally:
        coordinator.close()


def fixture_sizing(
    fixture_path: str | Path,
    pilot_report_path: str | Path,
    *,
    pilot_market_count: int = 3,
    projected_market_count: int = 12,
) -> dict[str, Any]:
    fixture_path = Path(fixture_path)
    report_path = Path(pilot_report_path)
    rows = _load_jsonl(fixture_path)
    report = _read_json(report_path)
    documented = ((report.get("results") or {}).get("documented") or {})
    result = sizing_from_fixture(
        fixture_bytes=fixture_path.stat().st_size,
        fixture_trades=len(rows),
        trades_per_hour=float(documented["trades_per_hour"]),
        pilot_market_count=int(pilot_market_count),
        projected_market_count=int(projected_market_count),
    )
    as_captured_bytes = int(documented.get("execution_only_bytes") or 0)
    if as_captured_bytes:
        as_captured = sizing_from_fixture(
            fixture_bytes=as_captured_bytes,
            fixture_trades=len(rows),
            trades_per_hour=float(documented["trades_per_hour"]),
            pilot_market_count=int(pilot_market_count),
            projected_market_count=int(projected_market_count),
        )
    else:
        as_captured = None
    result.update({
        "fixture_path": str(fixture_path),
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "pilot_report_path": str(report_path),
        "pilot_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "as_captured_crlf_projection": as_captured,
        "rate_caveat": (
            "79.98/hour is one 30-minute evening window, not a day; overnight and "
            "pre-settlement rates are unmeasured and this projection is not a stable annual run rate"
        ),
    })
    return result


def read_capture_status(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
) -> dict[str, Any]:
    """Read the atomic last-counted status without starting capture."""

    path = Path(snapshots_root) / "execution_tape_status.json"
    payload = read_json(path, default=None)
    if not isinstance(payload, dict):
        raise ExecutionTapeError(f"execution-tape status is unavailable: {path}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser(
        "capture",
        help="Explicitly run the read-only public execution websocket producer.",
    )
    capture.add_argument("--event-metadata", default=str(DEFAULT_EVENT_METADATA))
    capture.add_argument("--market", default="all", help="all or comma-separated built-in market ids")
    capture.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    capture.add_argument("--max-part-bytes", type=int, default=DEFAULT_MAX_PART_BYTES)
    capture.add_argument("--max-tokens-per-connection", type=int, default=DEFAULT_MAX_TOKENS_PER_CONNECTION)
    capture.add_argument("--seed-check-seconds", type=float, default=DEFAULT_SEED_CHECK_SECONDS)
    capture.add_argument("--heartbeat-seconds", type=float, default=DEFAULT_HEARTBEAT_SECONDS)
    capture.add_argument(
        "--inbound-silence-timeout-seconds",
        type=float,
        default=DEFAULT_INBOUND_SILENCE_TIMEOUT_SECONDS,
    )
    capture.add_argument("--connect-timeout-seconds", type=float, default=DEFAULT_CONNECT_TIMEOUT_SECONDS)
    capture.add_argument("--event-metadata-max-age-hours", type=float, default=DEFAULT_EVENT_METADATA_MAX_AGE_HOURS)

    replay = subparsers.add_parser(
        "replay-fixture",
        help="Offline fixture-only persistence harness; never opens a network connection.",
    )
    replay.add_argument("--fixture", required=True)
    replay.add_argument("--snapshots-root", required=True)
    replay.add_argument("--market-id", default="fixture_market")
    replay.add_argument("--target-date", default="2026-08-10")
    replay.add_argument("--event-slug", default="execution-tape-fixture-2026-08-10")
    replay.add_argument("--max-part-bytes", type=int, default=DEFAULT_MAX_PART_BYTES)

    sizing = subparsers.add_parser(
        "sizing",
        help="Read-only storage sizing from the committed fixture and pilot report.",
    )
    sizing.add_argument("--fixture", required=True)
    sizing.add_argument("--pilot-report", required=True)
    sizing.add_argument("--pilot-market-count", type=int, default=3)
    sizing.add_argument("--projected-market-count", type=int, default=12)

    status = subparsers.add_parser(
        "status",
        help="Print the atomic last-counted status; never starts capture or opens a connection.",
    )
    status.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "capture":
        run_live_capture(
            event_metadata_path=args.event_metadata,
            markets=args.market,
            snapshots_root=args.snapshots_root,
            max_part_bytes=args.max_part_bytes,
            max_tokens_per_connection=args.max_tokens_per_connection,
            seed_check_seconds=args.seed_check_seconds,
            heartbeat_seconds=args.heartbeat_seconds,
            inbound_silence_timeout_seconds=args.inbound_silence_timeout_seconds,
            connect_timeout_seconds=args.connect_timeout_seconds,
            max_age_hours=args.event_metadata_max_age_hours,
        )
        return 0
    if args.command == "replay-fixture":
        result = replay_fixture(
            args.fixture,
            snapshots_root=args.snapshots_root,
            market_id=args.market_id,
            target_date=args.target_date,
            event_slug=args.event_slug,
            max_part_bytes=args.max_part_bytes,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "sizing":
        result = fixture_sizing(
            args.fixture,
            args.pilot_report,
            pilot_market_count=args.pilot_market_count,
            projected_market_count=args.projected_market_count,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "status":
        print(json.dumps(read_capture_status(args.snapshots_root), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
