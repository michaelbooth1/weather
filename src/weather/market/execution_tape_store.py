"""Durable, append-only storage for public market execution events.

The live transport is intentionally separate in ``execution_tape_capture``.
This module owns the evidence boundary: validation, transaction-hash dedupe,
bounded JSONL parts, gap accounting, and atomic status counters.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from weather.io import (
    acquire_writer_lock,
    read_json,
    release_writer_lock,
    write_json_atomic,
)
from weather.paths import data_path
from weather.schema_registry import schema_version


EXECUTION_TAPE_TRADE_SCHEMA_VERSION = schema_version("execution_tape_trade")
EXECUTION_TAPE_DEDUPE_SCHEMA_VERSION = schema_version("execution_tape_dedupe")
EXECUTION_TAPE_GAP_SCHEMA_VERSION = schema_version("execution_tape_gap")
EXECUTION_TAPE_SEED_SCHEMA_VERSION = schema_version("execution_tape_seed")
EXECUTION_TAPE_STATUS_SCHEMA_VERSION = schema_version("execution_tape_status")

DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_MAX_PART_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_JSONL_LINE_BYTES = 1024 * 1024

TRADE_IDENTITY_FIELDS = (
    "asset_id",
    "event_type",
    "fee_rate_bps",
    "market",
    "price",
    "side",
    "size",
    "timestamp",
    "transaction_hash",
)

_TX_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_CONDITION_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_TOKEN_ID_RE = re.compile(r"^[0-9]+$")


class ExecutionTapeError(RuntimeError):
    """Base error for fail-closed execution-tape operations."""


class ExecutionTapeWriterBusy(ExecutionTapeError):
    """Raised when another process owns the execution-tape writer lease."""


class ExecutionPayloadError(ExecutionTapeError):
    """Raised when a wire execution event is not safe to persist."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | str | None = None) -> datetime:
    if value is None:
        return utc_now()
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def stable_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ExecutionPayloadError(f"missing execution identity field: {field}")
    return result


def _decimal_text(value: Any, field: str, *, positive: bool = False) -> str:
    text = _text(value, field)
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ExecutionPayloadError(f"invalid decimal execution field {field}: {text}") from exc
    if not number.is_finite():
        raise ExecutionPayloadError(f"non-finite execution field {field}: {text}")
    if positive and number <= 0:
        raise ExecutionPayloadError(f"execution field {field} must be positive: {text}")
    if not positive and number < 0:
        raise ExecutionPayloadError(f"execution field {field} must be non-negative: {text}")
    return text


def _timestamp_text(value: Any) -> str:
    text = _text(value, "timestamp")
    if not text.isdigit():
        raise ExecutionPayloadError(f"execution timestamp is not integer epoch milliseconds: {text}")
    number = int(text)
    if number <= 0:
        raise ExecutionPayloadError("execution timestamp must be positive")
    return str(number)


def timestamp_ms_to_utc(value: str) -> str:
    return datetime.fromtimestamp(int(value) / 1000.0, timezone.utc).isoformat()


def normalize_execution_row(item: dict[str, Any]) -> dict[str, str]:
    event_type = _text(item.get("event_type"), "event_type")
    if event_type != "last_trade_price":
        raise ExecutionPayloadError(f"not an execution event: {event_type}")

    asset_id = _text(item.get("asset_id"), "asset_id")
    if not _TOKEN_ID_RE.fullmatch(asset_id):
        raise ExecutionPayloadError(f"invalid execution asset_id: {asset_id}")

    condition_id = _text(item.get("market"), "market").lower()
    if not _CONDITION_ID_RE.fullmatch(condition_id):
        raise ExecutionPayloadError(f"invalid execution market condition id: {condition_id}")

    transaction_hash = _text(item.get("transaction_hash"), "transaction_hash").lower()
    if not _TX_HASH_RE.fullmatch(transaction_hash):
        raise ExecutionPayloadError(f"invalid execution transaction_hash: {transaction_hash}")

    side = _text(item.get("side"), "side").upper()
    if side not in {"BUY", "SELL"}:
        raise ExecutionPayloadError(f"invalid execution side: {side}")

    price = _decimal_text(item.get("price"), "price")
    if Decimal(price) > 1:
        raise ExecutionPayloadError(f"execution price outside [0, 1]: {price}")

    return {
        "asset_id": asset_id,
        "event_type": event_type,
        "fee_rate_bps": _decimal_text(item.get("fee_rate_bps"), "fee_rate_bps"),
        "market": condition_id,
        "price": price,
        "side": side,
        "size": _decimal_text(item.get("size"), "size", positive=True),
        "timestamp": _timestamp_text(item.get("timestamp")),
        "transaction_hash": transaction_hash,
    }


@dataclass(frozen=True)
class ParsedExecutionBatch:
    trades: tuple[dict[str, Any], ...]
    non_trade_messages: int
    rejected: tuple[dict[str, Any], ...]
    raw_payload_sha256: str
    raw_payload_sha256_algorithm: str


def parse_execution_payload(raw: bytes | str | dict[str, Any] | list[Any]) -> ParsedExecutionBatch:
    """Parse one websocket frame while retaining an exact or canonical raw hash."""

    if isinstance(raw, bytes):
        raw_bytes = raw
        algorithm = "sha256-raw-bytes"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExecutionPayloadError(f"unparseable websocket payload: {type(exc).__name__}") from exc
    elif isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
        algorithm = "sha256-raw-utf8"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExecutionPayloadError("unparseable websocket JSON payload") from exc
    else:
        payload = raw
        raw_bytes = canonical_json_bytes(payload)
        algorithm = "sha256-canonical-json"

    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    items = payload if isinstance(payload, list) else [payload]
    trades: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    non_trade_messages = 0
    for index, value in enumerate(items):
        if not isinstance(value, dict):
            rejected.append({
                "message_index": index,
                "reason": "websocket message is not an object",
                "payload": value,
            })
            continue
        if value.get("event_type") != "last_trade_price":
            non_trade_messages += 1
            continue
        try:
            normalized = normalize_execution_row(value)
        except ExecutionPayloadError as exc:
            rejected.append({
                "message_index": index,
                "reason": str(exc),
                "payload": value,
            })
            continue
        normalized["raw_message_index"] = index
        trades.append(normalized)
    return ParsedExecutionBatch(
        trades=tuple(trades),
        non_trade_messages=non_trade_messages,
        rejected=tuple(rejected),
        raw_payload_sha256=raw_sha256,
        raw_payload_sha256_algorithm=algorithm,
    )


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


@dataclass(frozen=True)
class MarketDaySeed:
    market_id: str
    target_date: date
    event_slug: str
    asset_ids: tuple[str, ...]
    condition_ids: tuple[str, ...]
    source: str
    source_generated_at_utc: str | None = None

    def __post_init__(self) -> None:
        if not self.market_id or not self.event_slug:
            raise ValueError("execution-tape seed requires market_id and event_slug")
        if not self.asset_ids or not self.condition_ids:
            raise ValueError("execution-tape seed requires asset and condition ids")
        if any(not _TOKEN_ID_RE.fullmatch(value) for value in self.asset_ids):
            raise ValueError("execution-tape seed contains an invalid asset id")
        if any(not _CONDITION_ID_RE.fullmatch(value) for value in self.condition_ids):
            raise ValueError("execution-tape seed contains an invalid condition id")

    @property
    def key(self) -> str:
        return f"{self.market_id}:{self.target_date.isoformat()}:{self.event_slug}"

    def content_payload(self) -> dict[str, Any]:
        return {
            "market_id": self.market_id,
            "target_date": self.target_date.isoformat(),
            "event_slug": self.event_slug,
            "asset_ids": list(self.asset_ids),
            "condition_ids": list(self.condition_ids),
            "source": self.source,
            "source_generated_at_utc": self.source_generated_at_utc,
        }

    @property
    def sha256(self) -> str:
        return stable_sha256(self.content_payload())

    @classmethod
    def from_event(
        cls,
        event: dict[str, Any],
        *,
        market_id: str,
        target_date: date,
        source: str,
        source_generated_at_utc: str | None = None,
    ) -> "MarketDaySeed":
        event_slug = str(event.get("event_slug") or event.get("slug") or event.get("eventSlug") or "").strip()
        assets: set[str] = set()
        conditions: set[str] = set()
        for market in event.get("markets") or []:
            if not isinstance(market, dict):
                continue
            condition_id = str(market.get("condition_id") or market.get("conditionId") or "").strip().lower()
            if condition_id:
                conditions.add(condition_id)
            outcomes = market.get("outcomes")
            if isinstance(outcomes, list) and outcomes and all(isinstance(row, dict) for row in outcomes):
                for outcome in outcomes:
                    token_id = str(outcome.get("token_id") or outcome.get("clob_token_id") or "").strip()
                    if token_id:
                        assets.add(token_id)
            else:
                for token_id in _json_list(market.get("clobTokenIds") or market.get("clob_token_ids")):
                    token = str(token_id or "").strip()
                    if token:
                        assets.add(token)
        return cls(
            market_id=str(market_id),
            target_date=target_date,
            event_slug=event_slug,
            asset_ids=tuple(sorted(assets)),
            condition_ids=tuple(sorted(conditions)),
            source=str(source),
            source_generated_at_utc=source_generated_at_utc,
        )


@dataclass(frozen=True)
class JsonlWriteReceipt:
    path: str
    part_index: int
    line_count_after: int
    bytes_after: int
    row_sha256: str


class RotatingJsonlWriter:
    """Held-open JSONL writer with bounded, immutable numbered parts."""

    def __init__(
        self,
        root: str | Path,
        prefix: str,
        *,
        max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
        max_line_bytes: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.prefix = str(prefix)
        self.max_part_bytes = int(max_part_bytes)
        self.max_line_bytes = int(
            min(DEFAULT_MAX_JSONL_LINE_BYTES, self.max_part_bytes)
            if max_line_bytes is None
            else max_line_bytes
        )
        if self.max_part_bytes <= 0 or self.max_line_bytes <= 0:
            raise ValueError("JSONL rotation bounds must be positive")
        if self.max_line_bytes > self.max_part_bytes:
            raise ValueError("max_line_bytes cannot exceed max_part_bytes")
        self.root.mkdir(parents=True, exist_ok=True)
        self._pattern = re.compile(rf"^{re.escape(self.prefix)}-(\d{{5}})\.jsonl$")
        self.parts: list[dict[str, Any]] = []
        self.last_row: dict[str, Any] | None = None
        self._handle = None
        self._load_existing_parts()
        self._open_append_part()

    def _part_path(self, index: int) -> Path:
        return self.root / f"{self.prefix}-{index:05d}.jsonl"

    def _load_existing_parts(self) -> None:
        indexed: list[tuple[int, Path]] = []
        for path in self.root.glob(f"{self.prefix}-*.jsonl"):
            match = self._pattern.fullmatch(path.name)
            if match:
                indexed.append((int(match.group(1)), path))
        indexed.sort()
        if indexed and [index for index, _ in indexed] != list(range(indexed[-1][0] + 1)):
            raise ExecutionTapeError(f"non-contiguous {self.prefix} JSONL rotation parts")
        for index, path in indexed:
            rows = 0
            size = path.stat().st_size
            if size > self.max_part_bytes:
                raise ExecutionTapeError(
                    f"existing {self.prefix} part exceeds rotation bound: {path} ({size} bytes)"
                )
            with path.open("rb") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if len(line) > self.max_line_bytes:
                        raise ExecutionTapeError(f"oversized JSONL line in {path}:{line_number}")
                    if not line.endswith(b"\n"):
                        raise ExecutionTapeError(f"unterminated JSONL line in {path}:{line_number}")
                    try:
                        row = json.loads(line)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ExecutionTapeError(f"invalid JSONL row in {path}:{line_number}") from exc
                    if not isinstance(row, dict):
                        raise ExecutionTapeError(f"non-object JSONL row in {path}:{line_number}")
                    self.last_row = row
                    rows += 1
            self.parts.append({"index": index, "path": path, "rows": rows, "bytes": size})

    def _open_append_part(self) -> None:
        if self.parts and self.parts[-1]["bytes"] < self.max_part_bytes:
            current = self.parts[-1]
        else:
            index = self.parts[-1]["index"] + 1 if self.parts else 0
            current = {"index": index, "path": self._part_path(index), "rows": 0, "bytes": 0}
            self.parts.append(current)
        self._handle = Path(current["path"]).open("ab")

    def _rotate(self) -> None:
        self.close_handle()
        index = self.parts[-1]["index"] + 1
        self.parts.append({"index": index, "path": self._part_path(index), "rows": 0, "bytes": 0})
        self._handle = self._part_path(index).open("ab")

    def append(self, payload: dict[str, Any]) -> JsonlWriteReceipt:
        encoded = canonical_json_bytes(payload) + b"\n"
        if len(encoded) > self.max_line_bytes or len(encoded) > self.max_part_bytes:
            raise ExecutionTapeError(
                f"{self.prefix} row exceeds JSONL bound ({len(encoded)} bytes)"
            )
        current = self.parts[-1]
        if current["rows"] and current["bytes"] + len(encoded) > self.max_part_bytes:
            self._rotate()
            current = self.parts[-1]
        if self._handle is None:
            self._open_append_part()
            current = self.parts[-1]
        self._handle.write(encoded)
        self._handle.flush()
        os.fsync(self._handle.fileno())
        current["rows"] += 1
        current["bytes"] += len(encoded)
        self.last_row = payload
        return JsonlWriteReceipt(
            path=str(current["path"]),
            part_index=int(current["index"]),
            line_count_after=int(current["rows"]),
            bytes_after=int(current["bytes"]),
            row_sha256=hashlib.sha256(encoded[:-1]).hexdigest(),
        )

    def iter_rows(self) -> Iterable[dict[str, Any]]:
        if self._handle is not None:
            self._handle.flush()
        for part in self.parts:
            path = Path(part["path"])
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        yield json.loads(line)

    def stats(self) -> dict[str, Any]:
        current = self.parts[-1] if self.parts else None
        return {
            "part_count": len(self.parts),
            "row_count": sum(int(row["rows"]) for row in self.parts),
            "byte_count": sum(int(row["bytes"]) for row in self.parts),
            "last_part_path": str(current["path"]) if current else None,
            "last_part_index": int(current["index"]) if current else None,
            "last_part_rows": int(current["rows"]) if current else 0,
            "last_part_bytes": int(current["bytes"]) if current else 0,
            "max_part_bytes": self.max_part_bytes,
        }

    def close_handle(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def close(self) -> None:
        self.close_handle()


def trade_identity_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in TRADE_IDENTITY_FIELDS}


def trade_fingerprint(row: dict[str, Any]) -> str:
    return stable_sha256(trade_identity_payload(row))


class MarketDayTapeStore:
    def __init__(
        self,
        seed: MarketDaySeed,
        *,
        snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
        max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
        now: datetime | None = None,
    ) -> None:
        self.seed = seed
        self.root = Path(snapshots_root) / seed.event_slug / "execution_tape"
        self.status_path = self.root / "status.json"
        self.trades = RotatingJsonlWriter(self.root, "trades", max_part_bytes=max_part_bytes)
        self.dedupe = RotatingJsonlWriter(self.root, "dedupe", max_part_bytes=max_part_bytes)
        self.gaps = RotatingJsonlWriter(self.root, "gaps", max_part_bytes=max_part_bytes)
        self.seeds = RotatingJsonlWriter(self.root, "seeds", max_part_bytes=max_part_bytes)
        self._trade_by_hash: dict[str, tuple[str, dict[str, Any]]] = {}
        self._load_trade_index()
        previous = read_json(self.status_path, default={}) or {}
        if previous and previous.get("event_slug") != seed.event_slug:
            raise ExecutionTapeError(f"execution status route mismatch: {self.status_path}")
        self.state = self._initial_state(previous)
        self._load_durable_counters()
        opened_at = ensure_utc(now)
        self._recover_interrupted_connection(opened_at)
        self._append_seed_if_changed(now=opened_at)
        self.persist_status(now=opened_at)

    def _load_trade_index(self) -> None:
        for row in self.trades.iter_rows():
            transaction_hash = str(row.get("transaction_hash") or "").lower()
            if not transaction_hash:
                raise ExecutionTapeError("stored execution row is missing transaction_hash")
            fingerprint = trade_fingerprint(row)
            existing = self._trade_by_hash.get(transaction_hash)
            if existing and existing[0] != fingerprint:
                raise ExecutionTapeError(
                    f"stored execution tape has conflicting transaction hash: {transaction_hash}"
                )
            self._trade_by_hash[transaction_hash] = (fingerprint, trade_identity_payload(row))

    def _initial_state(self, previous: dict[str, Any]) -> dict[str, Any]:
        return {
            "capture_started_at_utc": previous.get("capture_started_at_utc"),
            "capture_ended_at_utc": previous.get("capture_ended_at_utc"),
            "connection_state": previous.get("connection_state") or "NOT_STARTED",
            "session_id": previous.get("session_id"),
            "connected_at_utc": previous.get("connected_at_utc"),
            "last_heartbeat_at_utc": previous.get("last_heartbeat_at_utc"),
            "last_message_at_utc": previous.get("last_message_at_utc"),
            "last_trade_received_at_utc": previous.get("last_trade_received_at_utc"),
            "last_trade_timestamp_ms_seen": previous.get("last_trade_timestamp_ms_seen"),
            "last_trade_timestamp_utc_seen": previous.get("last_trade_timestamp_utc_seen"),
            "last_written_transaction_hash": previous.get("last_written_transaction_hash"),
            "last_error": previous.get("last_error"),
            "open_gap": previous.get("open_gap"),
            "ever_connected": bool(previous.get("ever_connected")),
            "connection_count": int(previous.get("connection_count") or 0),
            "reconnect_count": int(previous.get("reconnect_count") or 0),
            "disconnect_count": int(previous.get("disconnect_count") or 0),
            "startup_gap_count": int(previous.get("startup_gap_count") or 0),
            "seconds_connected_completed": float(previous.get("seconds_connected_completed") or 0.0),
            "messages_seen": int(previous.get("messages_seen") or 0),
            "non_trade_messages_discarded": int(previous.get("non_trade_messages_discarded") or 0),
            "parse_rejections": int(previous.get("parse_rejections") or 0),
        }

    def _load_durable_counters(self) -> None:
        duplicate_rows = list(self.dedupe.iter_rows())
        gap_rows = list(self.gaps.iter_rows())
        opened: dict[str, dict[str, Any]] = {}
        closed: dict[str, dict[str, Any]] = {}
        for row in gap_rows:
            gap_id = str(row.get("gap_id") or "")
            if row.get("gap_state") == "OPEN" and gap_id:
                opened[gap_id] = row
            elif row.get("gap_state") == "CLOSED" and gap_id:
                closed[gap_id] = row
        completed_dark = sum(float(row.get("seconds_dark") or 0.0) for row in closed.values())
        open_gap = self.state.get("open_gap")
        durable_open = [row for gap_id, row in opened.items() if gap_id not in closed]
        if durable_open:
            durable_open.sort(key=lambda row: str(row.get("disconnected_at_utc") or ""))
            latest = durable_open[-1]
            open_gap = {
                "gap_id": latest.get("gap_id"),
                "disconnected_at_utc": latest.get("disconnected_at_utc"),
                "reason": latest.get("reason"),
                "session_id": latest.get("session_id"),
                "was_ever_connected": bool(latest.get("was_ever_connected")),
            }
        self.state.update({
            "trades_written": self.trades.stats()["row_count"],
            "duplicates_suppressed": len(duplicate_rows),
            "duplicate_conflicts": sum(1 for row in duplicate_rows if row.get("payload_conflict")),
            "gap_count": len(opened),
            "completed_gap_count": len(closed),
            "connection_count": sum(
                1 for row in closed.values() if row.get("close_reason") == "websocket_connected"
            ),
            "reconnect_count": sum(1 for row in closed.values() if row.get("reconnect")),
            "disconnect_count": sum(1 for row in opened.values() if row.get("was_ever_connected")),
            "startup_gap_count": sum(
                1 for row in opened.values() if not row.get("was_ever_connected")
            ),
            "seconds_dark_completed": completed_dark,
            "open_gap": open_gap,
        })
        if self.trades.last_row:
            last = self.trades.last_row
            self.state["last_written_transaction_hash"] = last.get("transaction_hash")
            self._observe_trade(last, last.get("received_at_utc"))

    def _append_seed_if_changed(self, *, now: datetime) -> None:
        if self.seeds.last_row and self.seeds.last_row.get("seed_sha256") == self.seed.sha256:
            return
        self.seeds.append({
            "schema_version": EXECUTION_TAPE_SEED_SCHEMA_VERSION,
            "recorded_at_utc": now.isoformat(),
            **self.seed.content_payload(),
            "seed_sha256": self.seed.sha256,
        })

    def _seconds_since(self, value: Any, now: datetime) -> float:
        if not value:
            return 0.0
        return max(0.0, (now - ensure_utc(value)).total_seconds())

    def _recover_interrupted_connection(self, opened_at: datetime) -> None:
        previous_state = self.state.get("connection_state")
        if previous_state not in {"CONNECTED", "CONNECTING"}:
            return
        last_heartbeat = ensure_utc(
            self.state.get("last_heartbeat_at_utc")
            or self.state.get("connected_at_utc")
            or opened_at
        )
        if previous_state == "CONNECTED":
            self._accumulate_connected(last_heartbeat)
        reason = f"unclean_process_restart_from_{str(previous_state).lower()}"
        self._open_gap(
            last_heartbeat,
            reason=reason,
            session_id=self.state.get("session_id"),
        )
        self.state.update({
            "connection_state": "DISCONNECTED",
            "last_error": reason,
        })

    def _open_gap(self, at: datetime, *, reason: str, session_id: str | None) -> None:
        if self.state.get("open_gap"):
            return
        was_ever_connected = bool(self.state.get("ever_connected"))
        gap = {
            "gap_id": uuid.uuid4().hex,
            "disconnected_at_utc": at.isoformat(),
            "reason": str(reason),
            "session_id": session_id,
            "was_ever_connected": was_ever_connected,
        }
        self.gaps.append({
            "schema_version": EXECUTION_TAPE_GAP_SCHEMA_VERSION,
            "gap_state": "OPEN",
            "market_id": self.seed.market_id,
            "target_date": self.seed.target_date.isoformat(),
            "event_slug": self.seed.event_slug,
            **gap,
        })
        self.state["open_gap"] = gap
        self.state["gap_count"] = int(self.state.get("gap_count") or 0) + 1
        if was_ever_connected:
            self.state["disconnect_count"] = int(self.state.get("disconnect_count") or 0) + 1
        else:
            self.state["startup_gap_count"] = int(self.state.get("startup_gap_count") or 0) + 1

    def _close_gap(self, at: datetime, *, session_id: str | None, close_reason: str) -> None:
        gap = self.state.get("open_gap")
        if not gap:
            return
        seconds_dark = self._seconds_since(gap.get("disconnected_at_utc"), at)
        reconnect = bool(gap.get("was_ever_connected"))
        self.gaps.append({
            "schema_version": EXECUTION_TAPE_GAP_SCHEMA_VERSION,
            "gap_state": "CLOSED",
            "gap_id": gap.get("gap_id"),
            "market_id": self.seed.market_id,
            "target_date": self.seed.target_date.isoformat(),
            "event_slug": self.seed.event_slug,
            "disconnected_at_utc": gap.get("disconnected_at_utc"),
            "reconnected_at_utc": at.isoformat(),
            "seconds_dark": round(seconds_dark, 6),
            "reason": gap.get("reason"),
            "close_reason": str(close_reason),
            "disconnected_session_id": gap.get("session_id"),
            "session_id": session_id,
            "reconnect": reconnect,
        })
        self.state["open_gap"] = None
        self.state["completed_gap_count"] = int(self.state.get("completed_gap_count") or 0) + 1
        self.state["seconds_dark_completed"] = float(self.state.get("seconds_dark_completed") or 0.0) + seconds_dark
        if reconnect:
            self.state["reconnect_count"] = int(self.state.get("reconnect_count") or 0) + 1

    def begin_connecting(self, at: datetime, *, session_id: str) -> None:
        at = ensure_utc(at)
        if not self.state.get("capture_started_at_utc"):
            self.state["capture_started_at_utc"] = at.isoformat()
        if self.state.get("connection_state") == "CONNECTED":
            self._accumulate_connected(at)
            self._open_gap(
                at,
                reason="new_session_replaced_connected_session",
                session_id=self.state.get("session_id"),
            )
        elif not self.state.get("open_gap"):
            self._open_gap(at, reason="startup_connecting", session_id=session_id)
        self.state.update({
            "connection_state": "CONNECTING",
            "session_id": session_id,
            "last_heartbeat_at_utc": at.isoformat(),
            "capture_ended_at_utc": None,
        })
        self.persist_status(now=at)

    def mark_connected(self, at: datetime, *, session_id: str) -> None:
        at = ensure_utc(at)
        self._close_gap(at, session_id=session_id, close_reason="websocket_connected")
        self.state.update({
            "connection_state": "CONNECTED",
            "session_id": session_id,
            "connected_at_utc": at.isoformat(),
            "last_heartbeat_at_utc": at.isoformat(),
            "last_error": None,
            "ever_connected": True,
            "connection_count": int(self.state.get("connection_count") or 0) + 1,
        })
        self.persist_status(now=at)

    def _accumulate_connected(self, at: datetime) -> None:
        connected_at = self.state.get("connected_at_utc")
        if connected_at:
            self.state["seconds_connected_completed"] = (
                float(self.state.get("seconds_connected_completed") or 0.0)
                + self._seconds_since(connected_at, at)
            )
        self.state["connected_at_utc"] = None

    def mark_disconnected(self, at: datetime, *, reason: str, session_id: str | None = None) -> None:
        at = ensure_utc(at)
        if self.state.get("connection_state") == "CONNECTED":
            self._accumulate_connected(at)
        self._open_gap(at, reason=reason, session_id=session_id or self.state.get("session_id"))
        self.state.update({
            "connection_state": "DISCONNECTED",
            "last_heartbeat_at_utc": at.isoformat(),
            "last_error": str(reason),
        })
        self.persist_status(now=at)

    def retire(self, at: datetime, *, reason: str) -> None:
        at = ensure_utc(at)
        if self.state.get("connection_state") == "CONNECTED":
            self._accumulate_connected(at)
        self._close_gap(at, session_id=None, close_reason="market_day_retired")
        self.state.update({
            "connection_state": "ENDED",
            "capture_ended_at_utc": at.isoformat(),
            "last_heartbeat_at_utc": at.isoformat(),
            "last_error": str(reason),
        })
        self.persist_status(now=at)

    def heartbeat(self, at: datetime, *, message_seen: bool = False) -> None:
        at = ensure_utc(at)
        self.state["last_heartbeat_at_utc"] = at.isoformat()
        if message_seen:
            self.state["last_message_at_utc"] = at.isoformat()
            self.state["messages_seen"] = int(self.state.get("messages_seen") or 0) + 1
        self.persist_status(now=at)

    def record_message_counts(self, *, non_trade: int = 0, rejected: int = 0) -> None:
        self.state["non_trade_messages_discarded"] = (
            int(self.state.get("non_trade_messages_discarded") or 0) + int(non_trade)
        )
        self.state["parse_rejections"] = int(self.state.get("parse_rejections") or 0) + int(rejected)

    def _observe_trade(self, row: dict[str, Any], received_at: Any) -> None:
        timestamp = str(row.get("timestamp") or "")
        prior = str(self.state.get("last_trade_timestamp_ms_seen") or "")
        if timestamp and (not prior or int(timestamp) >= int(prior)):
            self.state["last_trade_timestamp_ms_seen"] = timestamp
            self.state["last_trade_timestamp_utc_seen"] = timestamp_ms_to_utc(timestamp)
        if received_at:
            self.state["last_trade_received_at_utc"] = str(received_at)

    def ingest_trade(
        self,
        trade: dict[str, Any],
        *,
        received_at: datetime,
        session_id: str,
        raw_payload_sha256: str,
        raw_payload_sha256_algorithm: str,
    ) -> dict[str, Any]:
        received_at = ensure_utc(received_at)
        normalized = normalize_execution_row(trade)
        fingerprint = trade_fingerprint(normalized)
        transaction_hash = normalized["transaction_hash"]
        self._observe_trade(normalized, received_at.isoformat())
        existing = self._trade_by_hash.get(transaction_hash)
        if existing:
            existing_fingerprint, existing_identity = existing
            differing = [
                field
                for field in TRADE_IDENTITY_FIELDS
                if existing_identity.get(field) != normalized.get(field)
            ]
            conflict = bool(differing)
            receipt = self.dedupe.append({
                "schema_version": EXECUTION_TAPE_DEDUPE_SCHEMA_VERSION,
                "received_at_utc": received_at.isoformat(),
                "market_id": self.seed.market_id,
                "target_date": self.seed.target_date.isoformat(),
                "event_slug": self.seed.event_slug,
                "session_id": session_id,
                "transaction_hash": transaction_hash,
                "dedupe_key": "transaction_hash",
                "payload_conflict": conflict,
                "differing_fields": differing,
                "first_identity": existing_identity,
                "redelivered_identity": trade_identity_payload(normalized),
                "first_fingerprint_sha256": existing_fingerprint,
                "redelivered_fingerprint_sha256": fingerprint,
                "raw_payload_sha256": raw_payload_sha256,
                "raw_payload_sha256_algorithm": raw_payload_sha256_algorithm,
                "action": "suppressed_keep_first",
            })
            self.state["duplicates_suppressed"] = int(self.state.get("duplicates_suppressed") or 0) + 1
            if conflict:
                self.state["duplicate_conflicts"] = int(self.state.get("duplicate_conflicts") or 0) + 1
            self.persist_status(now=received_at)
            return {"written": False, "duplicate": True, "payload_conflict": conflict, "receipt": receipt}

        row = {
            "schema_version": EXECUTION_TAPE_TRADE_SCHEMA_VERSION,
            "received_at_utc": received_at.isoformat(),
            "trade_time_utc": timestamp_ms_to_utc(normalized["timestamp"]),
            "timestamp_unit": "unix_epoch_milliseconds",
            "market_id": self.seed.market_id,
            "target_date": self.seed.target_date.isoformat(),
            "event_slug": self.seed.event_slug,
            "session_id": session_id,
            "seed_sha256": self.seed.sha256,
            "raw_payload_sha256": raw_payload_sha256,
            "raw_payload_sha256_algorithm": raw_payload_sha256_algorithm,
            **normalized,
        }
        receipt = self.trades.append(row)
        self._trade_by_hash[transaction_hash] = (fingerprint, trade_identity_payload(normalized))
        self.state["trades_written"] = int(self.state.get("trades_written") or 0) + 1
        self.state["last_written_transaction_hash"] = transaction_hash
        self.persist_status(now=received_at)
        return {"written": True, "duplicate": False, "payload_conflict": False, "receipt": receipt}

    def evidence_interpretation(self, *, now: datetime) -> str:
        trades = int(self.state.get("trades_written") or 0)
        dark = self.seconds_dark(now=now)
        state = self.state.get("connection_state")
        if trades:
            return "TRADES_WITH_COVERAGE_GAPS" if dark > 0 else "TRADES_CONTINUOUSLY_CONNECTED"
        if state == "CONNECTED":
            return "NO_TRADES_WITH_COVERAGE_GAPS" if dark > 0 else "NO_TRADES_CONNECTED_QUIET"
        if state in {"CONNECTING", "DISCONNECTED"} or dark > 0:
            return "NO_TRADES_DISCONNECTED_NOT_QUIET"
        if state == "ENDED":
            return "NO_TRADES_CAPTURE_ENDED"
        return "NO_TRADES_NOT_YET_OBSERVED"

    def seconds_dark(self, *, now: datetime) -> float:
        completed = float(self.state.get("seconds_dark_completed") or 0.0)
        open_gap = self.state.get("open_gap") or {}
        return completed + self._seconds_since(open_gap.get("disconnected_at_utc"), now)

    def seconds_connected(self, *, now: datetime) -> float:
        completed = float(self.state.get("seconds_connected_completed") or 0.0)
        if self.state.get("connection_state") == "CONNECTED":
            completed += self._seconds_since(self.state.get("connected_at_utc"), now)
        return completed

    def status_payload(self, *, now: datetime) -> dict[str, Any]:
        now = ensure_utc(now)
        open_gap = self.state.get("open_gap")
        return {
            "schema_version": EXECUTION_TAPE_STATUS_SCHEMA_VERSION,
            "updated_at_utc": now.isoformat(),
            "last_counted_at_utc": now.isoformat(),
            "market_id": self.seed.market_id,
            "target_date": self.seed.target_date.isoformat(),
            "event_slug": self.seed.event_slug,
            "seed_sha256": self.seed.sha256,
            **self.state,
            "seconds_connected": round(self.seconds_connected(now=now), 6),
            "seconds_dark": round(self.seconds_dark(now=now), 6),
            "current_gap_seconds_dark": round(
                self._seconds_since((open_gap or {}).get("disconnected_at_utc"), now),
                6,
            ),
            "evidence_interpretation": self.evidence_interpretation(now=now),
            "last_counted": {
                "dedupe_key": "transaction_hash",
                "trade_tape": self.trades.stats(),
                "dedupe_tape": self.dedupe.stats(),
                "gap_tape": self.gaps.stats(),
                "seed_tape": self.seeds.stats(),
                "last_written_transaction_hash": self.state.get("last_written_transaction_hash"),
                "last_trade_timestamp_ms_seen": self.state.get("last_trade_timestamp_ms_seen"),
                "counter_basis": "physical JSONL scan at open plus fsynced append receipts",
            },
        }

    def persist_status(self, *, now: datetime) -> None:
        write_json_atomic(self.status_path, self.status_payload(now=now), trailing_newline=True)

    def close(self) -> None:
        self.trades.close()
        self.dedupe.close()
        self.gaps.close()
        self.seeds.close()


class ExecutionTapeCoordinator:
    """Single-writer coordinator for several independently connected market-days."""

    def __init__(
        self,
        seeds: Iterable[MarketDaySeed] = (),
        *,
        snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
        max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
        now: datetime | None = None,
    ) -> None:
        self.snapshots_root = Path(snapshots_root)
        self.max_part_bytes = int(max_part_bytes)
        self.status_path = self.snapshots_root / "execution_tape_status.json"
        self.reject_root = self.snapshots_root / "execution_tape_unrouted"
        self._mutex = threading.RLock()
        self.coordinator_session_id = uuid.uuid4().hex
        self._lock = acquire_writer_lock(
            self.status_path,
            owner={
                "resource": "execution_tape",
                "session_id": self.coordinator_session_id,
                "module": "weather.market.execution_tape_capture",
            },
            attempts=1,
            stale_after_seconds=300.0,
        )
        if self._lock is None:
            raise ExecutionTapeWriterBusy(f"execution-tape writer lock is busy: {self.status_path}")
        self.rejects = RotatingJsonlWriter(
            self.reject_root,
            "rejections",
            max_part_bytes=self.max_part_bytes,
        )
        prior = read_json(self.status_path, default={}) or {}
        self.state = {
            "capture_started_at_utc": prior.get("capture_started_at_utc") or ensure_utc(now).isoformat(),
            "capture_stopped_at_utc": None,
            "last_seed_check_at_utc": prior.get("last_seed_check_at_utc"),
            "last_seed_error": None,
            "seed_error_dark_since_utc": prior.get("seed_error_dark_since_utc"),
            "seconds_seed_error_dark_completed": float(prior.get("seconds_seed_error_dark_completed") or 0.0),
            "frames_seen": int(prior.get("frames_seen") or 0),
            "non_trade_messages_discarded": int(prior.get("non_trade_messages_discarded") or 0),
            "parse_rejections": int(prior.get("parse_rejections") or 0),
            "unrouted_trades": int(prior.get("unrouted_trades") or 0),
            "ambiguous_routes": int(prior.get("ambiguous_routes") or 0),
        }
        self.stores: dict[str, MarketDayTapeStore] = {}
        self.active_keys: set[str] = set()
        self.asset_routes: dict[str, str] = {}
        self.condition_routes: dict[str, str] = {}
        self.replace_seeds(tuple(seeds), now=ensure_utc(now))

    def _validate_routes(self, seeds: Iterable[MarketDaySeed]) -> None:
        asset_owner: dict[str, str] = {}
        condition_owner: dict[str, str] = {}
        for seed in seeds:
            for asset_id in seed.asset_ids:
                owner = asset_owner.setdefault(asset_id, seed.key)
                if owner != seed.key:
                    raise ExecutionTapeError(f"asset id maps to multiple market-days: {asset_id}")
            for condition_id in seed.condition_ids:
                owner = condition_owner.setdefault(condition_id, seed.key)
                if owner != seed.key:
                    raise ExecutionTapeError(f"condition id maps to multiple market-days: {condition_id}")

    def replace_seeds(self, seeds: Iterable[MarketDaySeed], *, now: datetime) -> None:
        now = ensure_utc(now)
        seeds = tuple(seeds)
        self._validate_routes(seeds)
        with self._mutex:
            by_key = {seed.key: seed for seed in seeds}
            for key in sorted(self.active_keys - set(by_key)):
                self.stores[key].retire(now, reason="seed no longer active")
                self.stores[key].close()
                self.stores.pop(key, None)
            for key, seed in by_key.items():
                existing = self.stores.get(key)
                if existing and existing.seed.sha256 != seed.sha256:
                    existing.close()
                    existing = None
                if existing is None:
                    self.stores[key] = MarketDayTapeStore(
                        seed,
                        snapshots_root=self.snapshots_root,
                        max_part_bytes=self.max_part_bytes,
                        now=now,
                    )
            self.active_keys = set(by_key)
            self.asset_routes = {
                asset_id: seed.key
                for seed in seeds
                for asset_id in seed.asset_ids
            }
            self.condition_routes = {
                condition_id: seed.key
                for seed in seeds
                for condition_id in seed.condition_ids
            }
            self.state["last_seed_check_at_utc"] = now.isoformat()
            self.clear_seed_error(now=now)
            self.persist_status(now=now)

    def set_seed_error(self, error: str, *, now: datetime) -> None:
        now = ensure_utc(now)
        with self._mutex:
            if not self.state.get("seed_error_dark_since_utc"):
                self.state["seed_error_dark_since_utc"] = now.isoformat()
            self.state["last_seed_error"] = str(error)
            self.state["last_seed_check_at_utc"] = now.isoformat()
            for key in self.active_keys:
                self.stores[key].mark_disconnected(now, reason=f"seed_error: {error}")
            self.persist_status(now=now)

    def clear_seed_error(self, *, now: datetime) -> None:
        now = ensure_utc(now)
        started = self.state.get("seed_error_dark_since_utc")
        if started:
            self.state["seconds_seed_error_dark_completed"] += max(
                0.0, (now - ensure_utc(started)).total_seconds()
            )
        self.state["seed_error_dark_since_utc"] = None
        self.state["last_seed_error"] = None

    def begin_connecting(self, route_keys: Iterable[str], *, session_id: str, at: datetime) -> None:
        with self._mutex:
            for key in route_keys:
                self.stores[key].begin_connecting(at, session_id=session_id)
            self.persist_status(now=at)

    def mark_connected(self, route_keys: Iterable[str], *, session_id: str, at: datetime) -> None:
        with self._mutex:
            for key in route_keys:
                self.stores[key].mark_connected(at, session_id=session_id)
            self.persist_status(now=at)

    def mark_disconnected(
        self,
        route_keys: Iterable[str],
        *,
        session_id: str,
        at: datetime,
        reason: str,
    ) -> None:
        with self._mutex:
            for key in route_keys:
                self.stores[key].mark_disconnected(at, reason=reason, session_id=session_id)
            self.persist_status(now=at)

    def heartbeat(self, route_keys: Iterable[str], *, at: datetime, message_seen: bool = False) -> None:
        with self._mutex:
            for key in route_keys:
                self.stores[key].heartbeat(at, message_seen=message_seen)
            self.persist_status(now=at)

    def _record_rejection(
        self,
        *,
        received_at: datetime,
        session_id: str,
        classification: str,
        detail: Any,
        raw_payload_sha256: str | None = None,
    ) -> None:
        self.rejects.append({
            "schema_version": EXECUTION_TAPE_DEDUPE_SCHEMA_VERSION,
            "received_at_utc": received_at.isoformat(),
            "session_id": session_id,
            "classification": classification,
            "detail": detail,
            "raw_payload_sha256": raw_payload_sha256,
            "action": "not_admitted_to_market_day_tape",
        })

    def ingest_frame(self, raw: Any, *, session_id: str, received_at: datetime | None = None) -> dict[str, Any]:
        received_at = ensure_utc(received_at)
        with self._mutex:
            self.state["frames_seen"] = int(self.state.get("frames_seen") or 0) + 1
            try:
                batch = parse_execution_payload(raw)
            except ExecutionPayloadError as exc:
                self.state["parse_rejections"] = int(self.state.get("parse_rejections") or 0) + 1
                self._record_rejection(
                    received_at=received_at,
                    session_id=session_id,
                    classification="unparseable_frame",
                    detail=str(exc),
                )
                self.persist_status(now=received_at)
                return {"trades": 0, "written": 0, "duplicates": 0, "rejected": 1}

            self.state["non_trade_messages_discarded"] += batch.non_trade_messages
            self.state["parse_rejections"] += len(batch.rejected)
            for rejection in batch.rejected:
                self._record_rejection(
                    received_at=received_at,
                    session_id=session_id,
                    classification="invalid_execution_message",
                    detail=rejection,
                    raw_payload_sha256=batch.raw_payload_sha256,
                )

            written = 0
            duplicates = 0
            conflicts = 0
            unrouted = 0
            for trade in batch.trades:
                asset_key = self.asset_routes.get(trade["asset_id"])
                condition_key = self.condition_routes.get(trade["market"])
                if not asset_key or not condition_key:
                    unrouted += 1
                    self.state["unrouted_trades"] += 1
                    self._record_rejection(
                        received_at=received_at,
                        session_id=session_id,
                        classification="incomplete_execution_route",
                        detail={
                            "trade": trade,
                            "asset_route": asset_key,
                            "condition_route": condition_key,
                        },
                        raw_payload_sha256=batch.raw_payload_sha256,
                    )
                    continue
                if asset_key != condition_key:
                    self.state["ambiguous_routes"] += 1
                    self._record_rejection(
                        received_at=received_at,
                        session_id=session_id,
                        classification="asset_condition_route_conflict",
                        detail={"trade": trade, "asset_route": asset_key, "condition_route": condition_key},
                        raw_payload_sha256=batch.raw_payload_sha256,
                    )
                    continue
                store = self.stores[asset_key]
                store.record_message_counts(
                    non_trade=0,
                    rejected=0,
                )
                result = store.ingest_trade(
                    trade,
                    received_at=received_at,
                    session_id=session_id,
                    raw_payload_sha256=batch.raw_payload_sha256,
                    raw_payload_sha256_algorithm=batch.raw_payload_sha256_algorithm,
                )
                written += int(bool(result["written"]))
                duplicates += int(bool(result["duplicate"]))
                conflicts += int(bool(result["payload_conflict"]))
            self.persist_status(now=received_at)
            return {
                "trades": len(batch.trades),
                "written": written,
                "duplicates": duplicates,
                "duplicate_conflicts": conflicts,
                "rejected": len(batch.rejected),
                "unrouted": unrouted,
                "non_trade_messages": batch.non_trade_messages,
            }

    def _global_state(self) -> str:
        if self.state.get("capture_stopped_at_utc"):
            return "STOPPED"
        if self.state.get("last_seed_error"):
            return "DISCONNECTED_SEED_ERROR"
        states = [self.stores[key].state.get("connection_state") for key in self.active_keys]
        connected = sum(1 for state in states if state == "CONNECTED")
        if states and connected == len(states):
            return "CONNECTED"
        if connected:
            return "DEGRADED_PARTIALLY_CONNECTED"
        if any(state == "CONNECTING" for state in states):
            return "CONNECTING"
        if states:
            return "DISCONNECTED"
        return "NO_ACTIVE_MARKET_DAYS"

    def status_payload(self, *, now: datetime) -> dict[str, Any]:
        now = ensure_utc(now)
        active_status = [self.stores[key].status_payload(now=now) for key in sorted(self.active_keys)]
        seed_dark = float(self.state.get("seconds_seed_error_dark_completed") or 0.0)
        if self.state.get("seed_error_dark_since_utc"):
            seed_dark += max(
                0.0,
                (now - ensure_utc(self.state["seed_error_dark_since_utc"])).total_seconds(),
            )
        return {
            "schema_version": EXECUTION_TAPE_STATUS_SCHEMA_VERSION,
            "updated_at_utc": now.isoformat(),
            "last_counted_at_utc": now.isoformat(),
            "state": self._global_state(),
            "coordinator_session_id": self.coordinator_session_id,
            **self.state,
            "seconds_seed_error_dark": round(seed_dark, 6),
            "active_market_day_count": len(active_status),
            "active_market_days": [
                {
                    "market_id": row["market_id"],
                    "target_date": row["target_date"],
                    "event_slug": row["event_slug"],
                    "connection_state": row["connection_state"],
                    "evidence_interpretation": row["evidence_interpretation"],
                    "trades_written": row["trades_written"],
                    "duplicates_suppressed": row["duplicates_suppressed"],
                    "last_trade_timestamp_ms_seen": row["last_trade_timestamp_ms_seen"],
                    "seconds_dark": row["seconds_dark"],
                    "status_path": str(self.stores[
                        f"{row['market_id']}:{row['target_date']}:{row['event_slug']}"
                    ].status_path),
                }
                for row in active_status
            ],
            "last_counted": {
                "dedupe_key": "transaction_hash",
                "trades_written": sum(int(row["trades_written"]) for row in active_status),
                "duplicates_suppressed": sum(int(row["duplicates_suppressed"]) for row in active_status),
                "duplicate_conflicts": sum(int(row["duplicate_conflicts"]) for row in active_status),
                "gap_count": sum(int(row["gap_count"]) for row in active_status),
                "seconds_dark": round(sum(float(row["seconds_dark"]) for row in active_status), 6),
                "last_trade_timestamp_ms_seen": max(
                    (str(row.get("last_trade_timestamp_ms_seen") or "") for row in active_status),
                    default="",
                ) or None,
                "rejection_tape": self.rejects.stats(),
                "counter_basis": "per-market-day physical JSONL scans plus fsynced append receipts",
            },
        }

    def persist_status(self, *, now: datetime) -> None:
        payload = self.status_payload(now=now)
        write_json_atomic(self.status_path, payload, trailing_newline=True)
        if self._lock:
            try:
                Path(self._lock["path"]).touch()
            except (KeyError, OSError):
                pass

    def stop(self, *, now: datetime | None = None, reason: str = "operator_stop") -> None:
        now = ensure_utc(now)
        with self._mutex:
            for key in tuple(self.active_keys):
                store = self.stores[key]
                if store.state.get("connection_state") not in {"DISCONNECTED", "ENDED"}:
                    store.mark_disconnected(
                        now,
                        reason=reason,
                        session_id=store.state.get("session_id"),
                    )
            self.state["capture_stopped_at_utc"] = now.isoformat()
            self.persist_status(now=now)

    def close(self) -> None:
        with self._mutex:
            for store in self.stores.values():
                store.close()
            self.rejects.close()
            release_writer_lock(self._lock)
            self._lock = None

    def __enter__(self) -> "ExecutionTapeCoordinator":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc is not None:
            try:
                self.stop(now=utc_now(), reason=f"unhandled_{exc_type.__name__ if exc_type else 'error'}")
            except Exception:
                pass
        self.close()


def fixture_seed(
    rows: Iterable[dict[str, Any]],
    *,
    market_id: str,
    target_date: date,
    event_slug: str,
    source: str,
) -> MarketDaySeed:
    """Build a deterministic one-market-day seed for offline fixture replay."""

    normalized = [normalize_execution_row(row) for row in rows]
    return MarketDaySeed(
        market_id=market_id,
        target_date=target_date,
        event_slug=event_slug,
        asset_ids=tuple(sorted({row["asset_id"] for row in normalized})),
        condition_ids=tuple(sorted({row["market"] for row in normalized})),
        source=source,
    )


def sizing_from_fixture(
    *,
    fixture_bytes: int,
    fixture_trades: int,
    trades_per_hour: float,
    pilot_market_count: int,
    projected_market_count: int,
) -> dict[str, Any]:
    """Return a storage projection while keeping its single-window basis explicit."""

    if min(fixture_bytes, fixture_trades, pilot_market_count, projected_market_count) <= 0:
        raise ValueError("sizing inputs must be positive")
    if not math.isfinite(float(trades_per_hour)) or float(trades_per_hour) < 0:
        raise ValueError("trades_per_hour must be finite and non-negative")
    bytes_per_trade = float(fixture_bytes) / float(fixture_trades)
    projected_trades_per_market_day = float(trades_per_hour) * 24.0 / float(pilot_market_count)
    bytes_per_market_day = bytes_per_trade * projected_trades_per_market_day
    bytes_per_day = bytes_per_market_day * int(projected_market_count)
    bytes_per_year = bytes_per_day * 365.0
    return {
        "basis": "one_30_minute_evening_window_not_a_stable_day_rate",
        "fixture_bytes": int(fixture_bytes),
        "fixture_trades": int(fixture_trades),
        "bytes_per_trade": bytes_per_trade,
        "trades_per_hour_observed": float(trades_per_hour),
        "pilot_market_count": int(pilot_market_count),
        "projected_market_count": int(projected_market_count),
        "projected_trades_per_market_day": projected_trades_per_market_day,
        "projected_bytes_per_market_day": bytes_per_market_day,
        "projected_bytes_per_day": bytes_per_day,
        "projected_bytes_per_year": bytes_per_year,
        "projected_gb_per_year_decimal": bytes_per_year / 1_000_000_000.0,
        "projected_gib_per_year_binary": bytes_per_year / float(1024**3),
    }
