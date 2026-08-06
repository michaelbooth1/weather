"""Mechanical maker-day countability checklist.

Every input is retained evidence. Missing tapes, incomplete WebSocket coverage,
missing settlement on a fill, or a heuristic reward denominator fails closed.
"""

from __future__ import annotations

import csv
import json
import hashlib
import io
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from weather.market.market_microstructure_capture import payload_sha1
from weather.market.mm_policy import parse_time
from weather.market.mm_paper_constants import (
    EXECUTION_BOOK_ALIGNMENT_SEQUENCE_STATUS,
    EXECUTION_CANONICAL_TAPE_FILENAME,
    EXECUTION_CONNECTION_SEQUENCE_SCOPE,
    EXECUTION_RAW_TAPE_FILENAME,
    EXECUTION_SESSION_FILENAME,
)
from weather.paths import docs_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_day_countability")
TAPE_INVENTORY_SCHEMA_VERSION = schema_version("mm_execution_tape_inventory")
BOUND_SESSION_SCHEMA_VERSION = schema_version("mm_execution_capture_bound_session")
EXECUTION_ROW_SCHEMA_VERSION = schema_version("mm_execution_capture_execution_row")
RAW_EXECUTION_SCHEMA_VERSION = schema_version("mm_execution_capture_raw_execution")
SESSION_FILENAME = EXECUTION_SESSION_FILENAME
CONNECTION_SEQUENCE_SCOPE = EXECUTION_CONNECTION_SEQUENCE_SCOPE
BOOK_ALIGNMENT_SEQUENCE_STATUS = EXECUTION_BOOK_ALIGNMENT_SEQUENCE_STATUS
RETENTION_MODE = "executions-only"
LOCK_SCOPE = "execution-tape"
HOST_POLICY_MODE = "pause-training-window"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
DEFAULT_RESERVATION_PATH = docs_path("operations", "reserved-confirmation-window.md")
_RESERVED_ROW = re.compile(
    r"^\|\s*\*\*Reserved dates\*\*\s*\|(?P<value>.*?)\|\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def confirmation_reservation_gate(target_date=None, *, path=DEFAULT_RESERVATION_PATH):
    """Fail closed on a declared confirmation date before MM evidence is read."""

    source = Path(path)
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "status": "BLOCK",
            "state": "SOURCE_UNREADABLE",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": None,
            "blockers": [f"reservation_source_unreadable:{type(exc).__name__}"],
        }
    binding = hashlib.sha256(raw).hexdigest()
    match = _RESERVED_ROW.search(text)
    if match is None:
        return {
            "status": "BLOCK",
            "state": "SOURCE_UNPARSEABLE",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": binding,
            "blockers": ["reserved_dates_row_missing"],
        }
    value = match.group("value").strip()
    if "NONE ARE CURRENTLY RESERVED" in value.upper():
        return {
            "status": "PASS",
            "state": "ARMED_UNDATED",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": binding,
            "reserved_start": None,
            "reserved_end": None,
            "blockers": [],
        }
    dates = _ISO_DATE.findall(value)
    if len(dates) not in {1, 2}:
        return {
            "status": "BLOCK",
            "state": "DECLARATION_UNPARSEABLE",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": binding,
            "blockers": ["reserved_dates_declaration_unparseable"],
        }
    try:
        reserved_start = date.fromisoformat(dates[0])
        reserved_end = date.fromisoformat(dates[-1])
    except ValueError:
        return {
            "status": "BLOCK",
            "state": "DECLARATION_UNPARSEABLE",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": binding,
            "blockers": ["reserved_dates_declaration_unparseable"],
        }
    if reserved_end < reserved_start:
        return {
            "status": "BLOCK",
            "state": "DECLARATION_UNPARSEABLE",
            "target_date": str(target_date) if target_date else None,
            "source_path": str(source),
            "source_sha256": binding,
            "blockers": ["reserved_dates_range_reversed"],
        }
    if not target_date:
        return {
            "status": "BLOCK",
            "state": "DECLARED_TARGET_REQUIRED",
            "target_date": None,
            "source_path": str(source),
            "source_sha256": binding,
            "reserved_start": reserved_start.isoformat(),
            "reserved_end": reserved_end.isoformat(),
            "blockers": ["explicit_target_required_while_confirmation_reserved"],
        }
    try:
        target = date.fromisoformat(str(target_date))
    except ValueError:
        return {
            "status": "BLOCK",
            "state": "TARGET_UNPARSEABLE",
            "target_date": str(target_date),
            "source_path": str(source),
            "source_sha256": binding,
            "reserved_start": reserved_start.isoformat(),
            "reserved_end": reserved_end.isoformat(),
            "blockers": ["reservation_target_date_unparseable"],
        }
    blocked = reserved_start <= target <= reserved_end
    return {
        "status": "BLOCK" if blocked else "PASS",
        "state": "DECLARED_RESERVED" if blocked else "DECLARED_OUTSIDE_TARGET",
        "target_date": target.isoformat(),
        "source_path": str(source),
        "source_sha256": binding,
        "reserved_start": reserved_start.isoformat(),
        "reserved_end": reserved_end.isoformat(),
        "blockers": ["target_date_reserved_for_confirmation"] if blocked else [],
    }


def _nonempty(path):
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False


def _nonnegative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _asset_set_sha256(asset_ids):
    encoded = json.dumps(asset_ids, separators=(",", ":")).encode("utf-8")
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


def _verified_prefix(path, size, expected_sha256, label):
    if not _nonnegative_int(size):
        return None, f"{label}_prefix_size_invalid"
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256 or "")):
        return None, f"{label}_prefix_hash_invalid"
    if not path.exists():
        if size == 0 and expected_sha256 == EMPTY_SHA256:
            return b"", None
        return None, f"{label}_tape_missing"
    try:
        if path.stat().st_size < size:
            return None, f"{label}_prefix_truncated"
        with path.open("rb") as handle:
            prefix = handle.read(size)
    except OSError:
        return None, f"{label}_prefix_unreadable"
    if len(prefix) != size:
        return None, f"{label}_prefix_truncated"
    if hashlib.sha256(prefix).hexdigest() != expected_sha256:
        return None, f"{label}_prefix_hash_mismatch"
    if prefix and not prefix.endswith(b"\n"):
        return None, f"{label}_prefix_incomplete_record"
    return prefix, None


def _parse_raw_prefix(prefix):
    rows = []
    try:
        text = prefix.decode("utf-8")
    except UnicodeDecodeError:
        return None, "raw_prefix_malformed"
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return None, "raw_prefix_malformed"
        if not isinstance(row, dict):
            return None, "raw_prefix_malformed"
        rows.append(row)
    return rows, None


def _parse_canonical_prefix(prefix):
    if not prefix:
        return [], None
    try:
        text = prefix.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if not reader.fieldnames:
            return None, "canonical_prefix_malformed"
        return list(reader), None
    except (UnicodeDecodeError, csv.Error):
        return None, "canonical_prefix_malformed"


def _audit_key(row):
    session_id = str(row.get("session_id") or "")
    raw_sha1 = str(row.get("raw_sha1") or "")
    sequence = row.get("local_connection_message_sequence")
    try:
        sequence = int(sequence)
    except (TypeError, ValueError):
        return None
    if not session_id or sequence <= 0 or not re.fullmatch(r"[0-9a-f]{40}", raw_sha1):
        return None
    return session_id, sequence, raw_sha1


def _fill_audit_keys(row):
    try:
        bindings = json.loads(row.get("execution_audit_bindings_json") or "")
    except (TypeError, json.JSONDecodeError):
        return set()
    if not isinstance(bindings, list):
        return set()
    keys = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        key = _audit_key(binding)
        if (
            key is not None
            and binding.get("connection_sequence_scope") == CONNECTION_SEQUENCE_SCOPE
        ):
            keys.add(key)
    return keys


def _canonical_execution_projection(row):
    return {
        "clob_token_id": str(row.get("clob_token_id") or row.get("asset_id") or ""),
        "condition_id": str(row.get("condition_id") or row.get("market") or ""),
        "side": str(row.get("side") or "").strip().upper(),
        "price": str(row.get("price") or ""),
        "size": str(row.get("size") or ""),
        "transaction_hash": str(row.get("transaction_hash") or "").strip().lower(),
        "exchange_time_utc": str(row.get("exchange_time_utc") or ""),
        "raw_sha1": str(row.get("raw_sha1") or "").strip().lower(),
    }


def _decimal_equal(left, right):
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return False


def _fill_matches_execution_projection(fill, projection, audit_key):
    fill_time = parse_time(fill.get("execution_exchange_time_utc"))
    projection_time = parse_time(projection.get("exchange_time_utc"))
    raw_hashes = {
        value.strip().lower()
        for value in str(fill.get("execution_raw_sha1") or "").split(";")
        if value.strip()
    }
    return all((
        str(fill.get("clob_token_id") or "") == projection["clob_token_id"],
        str(fill.get("execution_condition_id") or "") == projection["condition_id"],
        str(fill.get("execution_side") or "").strip().upper() == projection["side"],
        _decimal_equal(fill.get("through_trade_price"), projection["price"]),
        _decimal_equal(fill.get("through_trade_size"), projection["size"]),
        str(fill.get("transaction_hash") or "").strip().lower()
        == projection["transaction_hash"],
        fill_time is not None and fill_time == projection_time,
        audit_key[2] == projection["raw_sha1"],
        audit_key[2] in raw_hashes,
    ))


def _normalized_exchange_timestamp(payload):
    value = payload.get("timestamp") if isinstance(payload, dict) else None
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        numeric = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not numeric.is_finite() or numeric != numeric.to_integral_value():
        return None
    milliseconds = int(numeric)
    seconds, remainder_ms = divmod(milliseconds, 1000)
    try:
        exchange_time = datetime.fromtimestamp(seconds, tz=timezone.utc).replace(
            microsecond=remainder_ms * 1000
        )
    except (OverflowError, OSError, ValueError):
        return None
    return milliseconds, exchange_time.isoformat(timespec="milliseconds")


def _value_text(value):
    return "" if value is None else str(value)


def _strict_execution_payload_valid(payload, raw_row):
    if not isinstance(payload, dict):
        return False
    asset_id = str(
        payload.get("asset_id")
        or payload.get("clob_token_id")
        or payload.get("token_id")
        or ""
    )
    condition_id = str(payload.get("condition_id") or payload.get("market") or "")
    transaction_hash = str(
        payload.get("transaction_hash") or payload.get("transactionHash") or ""
    ).strip()
    size = payload.get("size")
    if size in (None, ""):
        size = payload.get("trade_size")
    try:
        price_decimal = Decimal(str(payload.get("price")).strip())
        size_decimal = Decimal(str(size).strip())
    except (InvalidOperation, ValueError):
        return False
    normalized = _normalized_exchange_timestamp(payload)
    received_at = parse_time(raw_row.get("received_at_utc"))
    exchange_time = parse_time(normalized[1]) if normalized is not None else None
    return bool(
        asset_id
        and condition_id
        and transaction_hash
        and price_decimal.is_finite()
        and Decimal("0") <= price_decimal <= Decimal("1")
        and size_decimal.is_finite()
        and size_decimal > 0
        and str(payload.get("side") or "").strip().upper() in {"BUY", "SELL"}
        and received_at is not None
        and exchange_time is not None
        and received_at >= exchange_time - timedelta(seconds=1)
    )


def _execution_projection_matches(raw_row, canonical_row):
    payload = raw_row.get("payload")
    if not isinstance(payload, dict):
        return False
    normalized = _normalized_exchange_timestamp(payload)
    if normalized is None:
        return False
    milliseconds, exchange_time_utc = normalized
    raw_asset = str(
        payload.get("asset_id")
        or payload.get("clob_token_id")
        or payload.get("token_id")
        or ""
    )
    raw_condition = str(payload.get("condition_id") or payload.get("market") or "")
    raw_size = payload.get("size") or payload.get("trade_size")
    raw_transaction = payload.get("transaction_hash") or payload.get("transactionHash")
    return _strict_execution_payload_valid(payload, raw_row) and all((
        _value_text(canonical_row.get("received_at_utc"))
        == _value_text(raw_row.get("received_at_utc")),
        _value_text(canonical_row.get("market_id"))
        == _value_text(raw_row.get("market_id")),
        str(canonical_row.get("asset_id") or canonical_row.get("clob_token_id") or "")
        == raw_asset,
        str(canonical_row.get("condition_id") or canonical_row.get("market") or "")
        == raw_condition,
        _value_text(canonical_row.get("price")) == _value_text(payload.get("price")),
        _value_text(canonical_row.get("size")) == _value_text(raw_size),
        _value_text(canonical_row.get("side")) == _value_text(payload.get("side")),
        _value_text(canonical_row.get("transaction_hash"))
        == _value_text(raw_transaction),
        str(canonical_row.get("exchange_timestamp_ms") or "") == str(milliseconds),
        str(canonical_row.get("exchange_time_utc") or "") == exchange_time_utc,
        str(canonical_row.get("trade_time_utc") or "") == exchange_time_utc,
        str(canonical_row.get("timestamp_utc") or "") == exchange_time_utc,
        str(canonical_row.get("timestamp_precision_seconds") or "")
        in {"0.001", "0.0010"},
    ))


def _validate_bound_session(row, folder):
    errors = []
    session_id = str(row.get("session_id") or "")
    event_slug = str(row.get("event_slug") or "")
    if row.get("schema_version") != BOUND_SESSION_SCHEMA_VERSION:
        errors.append("bound_schema_missing")
    if not session_id:
        errors.append("session_id_missing")
    if not event_slug or event_slug != folder.name:
        errors.append("event_slug_mismatch")
    if row.get("receipt_binding_sha256") != _receipt_binding_sha256(row):
        errors.append("receipt_binding_hash_mismatch")
    if row.get("retention_mode") != RETENTION_MODE:
        errors.append("retention_mode_invalid")
    if row.get("lock_scope") != LOCK_SCOPE:
        errors.append("lock_scope_invalid")
    if row.get("host_policy_mode") != HOST_POLICY_MODE:
        errors.append("host_policy_mode_invalid")
    if not isinstance(row.get("continuous_coverage"), bool):
        errors.append("continuous_coverage_invalid")
    if row.get("status") == "COMPLETE" and row.get("continuous_coverage") is not True:
        errors.append("complete_session_without_continuous_coverage")

    start = parse_time(row.get("coverage_start_utc"))
    end = parse_time(row.get("coverage_end_utc"))
    if start is None or end is None or end < start:
        errors.append("coverage_interval_invalid")

    asset_ids = row.get("subscribed_asset_ids")
    if not isinstance(asset_ids, list):
        asset_ids = []
        errors.append("subscribed_asset_set_invalid")
    else:
        normalized_assets = [str(value) for value in asset_ids if str(value)]
        if normalized_assets != sorted(set(normalized_assets)):
            errors.append("subscribed_asset_set_invalid")
        asset_ids = normalized_assets
    if (
        not _nonnegative_int(row.get("subscribed_asset_count"))
        or row.get("subscribed_asset_count") != len(asset_ids)
        or row.get("subscribed_asset_set_sha256") != _asset_set_sha256(asset_ids)
    ):
        errors.append("subscribed_asset_binding_invalid")

    observed_asset_ids = row.get("observed_subscribed_asset_ids")
    if not isinstance(observed_asset_ids, list):
        observed_asset_ids = []
        errors.append("observed_subscribed_asset_set_invalid")
    else:
        normalized_observed_assets = [
            str(value) for value in observed_asset_ids if str(value)
        ]
        if normalized_observed_assets != sorted(set(normalized_observed_assets)):
            errors.append("observed_subscribed_asset_set_invalid")
        observed_asset_ids = normalized_observed_assets
    if (
        not _nonnegative_int(row.get("observed_subscribed_asset_count"))
        or row.get("observed_subscribed_asset_count") != len(observed_asset_ids)
        or row.get("observed_subscribed_asset_set_sha256")
        != _asset_set_sha256(observed_asset_ids)
        or any(value not in asset_ids for value in observed_asset_ids)
        or (
            row.get("status") == "COMPLETE"
            and observed_asset_ids != asset_ids
        )
    ):
        errors.append("observed_subscribed_asset_binding_invalid")

    message_count = row.get("message_count")
    market_data_message_count = row.get("market_data_message_count")
    sequence_start = row.get("local_connection_message_sequence_start")
    sequence_end = row.get("local_connection_message_sequence_end")
    if row.get("connection_sequence_scope") != CONNECTION_SEQUENCE_SCOPE:
        errors.append("connection_sequence_scope_invalid")
    if not _nonnegative_int(message_count):
        errors.append("message_count_invalid")
    elif message_count == 0:
        if row.get("status") == "COMPLETE":
            errors.append("complete_session_without_inbound_liveness")
        if sequence_start != 0 or sequence_end != 0:
            errors.append("local_connection_sequence_interval_invalid")
    elif (
        sequence_start != 1
        or sequence_end != message_count
    ):
        errors.append("local_connection_sequence_interval_invalid")
    if (
        not _nonnegative_int(market_data_message_count)
        or (
            _nonnegative_int(message_count)
            and market_data_message_count > message_count
        )
        or (
            row.get("status") == "COMPLETE"
            and market_data_message_count == 0
        )
    ):
        errors.append("market_data_liveness_invalid")
    inbound_liveness_timeout = row.get("inbound_liveness_timeout_seconds")
    if (
        isinstance(inbound_liveness_timeout, bool)
        or not isinstance(inbound_liveness_timeout, (int, float))
        or inbound_liveness_timeout <= 0
    ):
        errors.append("inbound_liveness_contract_invalid")

    execution_count = row.get("execution_count")
    if not _nonnegative_int(execution_count):
        execution_count = -1
        errors.append("execution_count_invalid")
    if row.get("raw_tape_filename") != EXECUTION_RAW_TAPE_FILENAME:
        errors.append("raw_tape_filename_invalid")
    if row.get("canonical_tape_filename") != EXECUTION_CANONICAL_TAPE_FILENAME:
        errors.append("canonical_tape_filename_invalid")

    raw_path = folder / EXECUTION_RAW_TAPE_FILENAME
    canonical_path = folder / EXECUTION_CANONICAL_TAPE_FILENAME
    raw_prefix, error = _verified_prefix(
        raw_path,
        row.get("raw_tape_prefix_size_bytes"),
        row.get("raw_tape_prefix_sha256"),
        "raw",
    )
    if error:
        errors.append(error)
    canonical_prefix, error = _verified_prefix(
        canonical_path,
        row.get("canonical_tape_prefix_size_bytes"),
        row.get("canonical_tape_prefix_sha256"),
        "canonical",
    )
    if error:
        errors.append(error)

    raw_rows = canonical_rows = None
    bound_execution_audit_keys = set()
    bound_execution_projections = {}
    if raw_prefix is not None:
        raw_rows, error = _parse_raw_prefix(raw_prefix)
        if error:
            errors.append(error)
    if canonical_prefix is not None:
        canonical_rows, error = _parse_canonical_prefix(canonical_prefix)
        if error:
            errors.append(error)

    if raw_rows is not None and canonical_rows is not None and session_id:
        raw_session_rows = [
            value for value in raw_rows
            if str(value.get("session_id") or "") == session_id
        ]
        canonical_session_rows = [
            value for value in canonical_rows
            if str(value.get("session_id") or "") == session_id
        ]
        if execution_count > 0 and (
            not raw_path.exists()
            or not canonical_path.exists()
            or not raw_prefix
            or not canonical_prefix
        ):
            errors.append("positive_execution_tape_missing")
        if (
            len(raw_session_rows) != execution_count
            or len(canonical_session_rows) != execution_count
        ):
            errors.append(
                "execution_receipt_count_mismatch"
                f"_{execution_count}_{len(raw_session_rows)}_{len(canonical_session_rows)}"
            )
        raw_keys = Counter()
        canonical_keys = Counter()
        raw_by_key = defaultdict(list)
        canonical_by_key = defaultdict(list)
        for value in raw_session_rows:
            payload = value.get("payload")
            key = _audit_key(value)
            if (
                value.get("schema_version") != RAW_EXECUTION_SCHEMA_VERSION
                or str(value.get("event_slug") or "") != event_slug
                or not isinstance(payload, dict)
                or str(payload.get("event_type") or "").strip().lower()
                != "last_trade_price"
                or str(payload.get("asset_id") or payload.get("clob_token_id") or "")
                not in asset_ids
                or key is None
                or value.get("connection_sequence_scope") != CONNECTION_SEQUENCE_SCOPE
                or value.get("book_alignment_sequence_status")
                != BOOK_ALIGNMENT_SEQUENCE_STATUS
                or not (
                    _nonnegative_int(sequence_start)
                    and _nonnegative_int(sequence_end)
                    and sequence_start <= key[1] <= sequence_end
                )
                or payload_sha1(payload) != key[2]
            ):
                errors.append("raw_execution_row_invalid")
                continue
            raw_keys[key] += 1
            raw_by_key[key].append(value)
        for value in canonical_session_rows:
            key = _audit_key(value)
            if (
                value.get("schema_version") != EXECUTION_ROW_SCHEMA_VERSION
                or str(value.get("event_slug") or "") != event_slug
                or str(value.get("event_type") or "").strip().lower()
                != "last_trade_price"
                or str(value.get("asset_id") or value.get("clob_token_id") or "")
                not in asset_ids
                or key is None
                or value.get("connection_sequence_scope") != CONNECTION_SEQUENCE_SCOPE
                or value.get("book_alignment_sequence_status")
                != BOOK_ALIGNMENT_SEQUENCE_STATUS
                or not (
                    _nonnegative_int(sequence_start)
                    and _nonnegative_int(sequence_end)
                    and sequence_start <= key[1] <= sequence_end
                )
            ):
                errors.append("canonical_execution_row_invalid")
                continue
            canonical_keys[key] += 1
            canonical_by_key[key].append(value)
        if raw_keys != canonical_keys:
            errors.append("execution_representation_key_mismatch")
        else:
            for key in raw_keys:
                raw_values = raw_by_key[key]
                canonical_values = canonical_by_key[key]
                if any(
                    not _execution_projection_matches(raw_value, canonical_value)
                    for raw_value, canonical_value in zip(raw_values, canonical_values)
                ):
                    errors.append("execution_representation_semantic_mismatch")
                else:
                    bound_execution_projections[key] = (
                        _canonical_execution_projection(canonical_values[0])
                    )
            bound_execution_audit_keys.update(raw_keys)

    return {
        **row,
        "_start": start,
        "_end": end,
        "_subscribed_asset_ids": set(asset_ids),
        "_bound_execution_audit_keys": bound_execution_audit_keys,
        "_bound_execution_projections": bound_execution_projections,
        "_binding_errors": sorted(set(errors)),
        "_binding_valid": not errors,
    }


def _sessions(folder):
    path = Path(folder) / SESSION_FILENAME
    rows = []
    parse_errors = []
    if not path.exists():
        return rows, parse_errors
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                parse_errors.append(f"line_{line_number}_malformed_json")
                continue
            if not isinstance(row, dict):
                parse_errors.append(f"line_{line_number}_not_an_object")
                continue
            rows.append(_validate_bound_session(row, Path(folder)))
    return rows, parse_errors


def build_execution_tape_inventory(quote_rows, legs, snapshots_root, fill_rows=None):
    by_event = defaultdict(lambda: {
        "target_dates": set(),
        "expected_asset_ids": set(),
        "decision_row_count": 0,
        "uncovered_decision_count": 0,
        "uncovered_decision_examples": [],
        "quote_leg_count": 0,
        "uncovered_count": 0,
        "uncovered_examples": [],
    })
    session_cache = {}
    fills_by_event = defaultdict(list)
    for row in fill_rows or []:
        event_slug = str(row.get("event_slug") or "")
        if event_slug:
            fills_by_event[event_slug].append(row)
    for row in quote_rows or []:
        event_slug = str(row.get("event_slug") or "")
        if event_slug:
            by_event[event_slug]["target_dates"].add(str(row.get("target_date") or ""))
            decision_asset_id = str(
                row.get("clob_token_id") or row.get("asset_id") or ""
            )
            if decision_asset_id:
                by_event[event_slug]["expected_asset_ids"].add(decision_asset_id)
            by_event[event_slug]["decision_row_count"] += 1
            if event_slug not in session_cache:
                session_cache[event_slug] = _sessions(Path(snapshots_root) / event_slug)
            sessions = session_cache[event_slug][0]
            decision_time = parse_time(
                row.get("generated_at_utc") or row.get("captured_at_utc")
            )
            covered = bool(
                decision_time is not None and any(
                    session.get("status") == "COMPLETE"
                    and bool(session.get("continuous_coverage"))
                    and session.get("_binding_valid")
                    and (
                        not decision_asset_id
                        or decision_asset_id in session.get("_subscribed_asset_ids", set())
                    )
                    and session["_start"] <= decision_time <= session["_end"]
                    for session in sessions
                )
            )
            if not covered:
                by_event[event_slug]["uncovered_decision_count"] += 1
                if len(by_event[event_slug]["uncovered_decision_examples"]) < 100:
                    by_event[event_slug]["uncovered_decision_examples"].append(
                        str(row.get("_quote_id") or row.get("quote_id") or "unknown")
                    )
    for leg in legs or []:
        event_slug = str(leg.get("event_slug") or "")
        if event_slug:
            by_event[event_slug]["target_dates"].add(str(leg.get("target_date") or ""))
            leg_asset_id = str(leg.get("clob_token_id") or leg.get("asset_id") or "")
            if leg_asset_id:
                by_event[event_slug]["expected_asset_ids"].add(leg_asset_id)
            by_event[event_slug]["quote_leg_count"] += 1
            if event_slug not in session_cache:
                session_cache[event_slug] = _sessions(Path(snapshots_root) / event_slug)
            sessions = session_cache[event_slug][0]
            complete_sessions = [
                row for row in sessions
                if row.get("status") == "COMPLETE" and bool(row.get("continuous_coverage"))
                and row.get("_binding_valid")
                and (
                    not leg_asset_id
                    or leg_asset_id in row.get("_subscribed_asset_ids", set())
                )
            ]
            start = leg.get("quote_time")
            end = leg.get("quote_expires_at")
            covered = bool(
                start is not None and end is not None and any(
                    session["_start"] <= start and session["_end"] >= end
                    for session in complete_sessions
                )
            )
            if not covered:
                by_event[event_slug]["uncovered_count"] += 1
                if len(by_event[event_slug]["uncovered_examples"]) < 100:
                    by_event[event_slug]["uncovered_examples"].append(
                        str(leg.get("leg_id") or "unknown")
                    )

    event_rows = []
    blockers = []
    for event_slug, expected in sorted(by_event.items()):
        folder = Path(snapshots_root) / event_slug
        book_path = folder / "order_books.jsonl"
        raw_path = folder / EXECUTION_RAW_TAPE_FILENAME
        csv_path = folder / EXECUTION_CANONICAL_TAPE_FILENAME
        session_path = folder / SESSION_FILENAME
        cached_sessions = session_cache.get(event_slug)
        if cached_sessions is None:
            cached_sessions = _sessions(folder)
        sessions, session_parse_errors = cached_sessions
        complete_sessions = [
            row for row in sessions
            if row.get("status") == "COMPLETE" and bool(row.get("continuous_coverage"))
            and row.get("_binding_valid")
        ]
        bound_execution_audit_keys = set()
        bound_execution_projections = {}
        for session in complete_sessions:
            bound_execution_audit_keys.update(
                session.get("_bound_execution_audit_keys") or ()
            )
            bound_execution_projections.update(
                session.get("_bound_execution_projections") or {}
            )
        unbound_fill_ids = []
        for fill in fills_by_event.get(event_slug, ()):
            representations = set(
                str(fill.get("execution_source_representations") or "").split(";")
            )
            fill_keys = _fill_audit_keys(fill)
            matching_key = any(
                key in bound_execution_projections
                and _fill_matches_execution_projection(
                    fill,
                    bound_execution_projections[key],
                    key,
                )
                for key in fill_keys
            )
            if (
                EXECUTION_RAW_TAPE_FILENAME not in representations
                or EXECUTION_CANONICAL_TAPE_FILENAME not in representations
                or not matching_key
            ):
                fill_id = str(fill.get("fill_id") or "unknown")
                unbound_fill_ids.append(fill_id)
                blockers.append(
                    f"execution_fill_not_bound:{event_slug}:{fill_id}"
                )
        tape_present = _nonempty(raw_path) and _nonempty(csv_path)
        zero_execution_proven = any(
            row.get("execution_count") == 0 for row in complete_sessions
        )
        execution_evidence_complete = bool(complete_sessions) and (
            tape_present or zero_execution_proven
        )
        full_depth_book_tape_present = _nonempty(book_path)
        if not full_depth_book_tape_present:
            blockers.append(f"full_depth_book_tape_missing:{event_slug}")
        if not execution_evidence_complete:
            blockers.append(f"execution_tape_missing:{event_slug}")
        if not complete_sessions:
            blockers.append(f"execution_bound_receipt_missing:{event_slug}")
        for parse_error in session_parse_errors:
            blockers.append(f"execution_receipt_invalid:{event_slug}:{parse_error}")
        invalid_sessions = [row for row in sessions if not row.get("_binding_valid")]
        for session in invalid_sessions:
            if session.get("status") != "COMPLETE" and not session.get("execution_count"):
                continue
            session_id = str(session.get("session_id") or "unknown")
            for error in session.get("_binding_errors") or ["unknown"]:
                blockers.append(
                    f"execution_receipt_invalid:{event_slug}:{session_id}:{error}"
                )
        for asset_id in sorted(expected["expected_asset_ids"]):
            if not any(
                asset_id in session.get("_subscribed_asset_ids", set())
                for session in complete_sessions
            ):
                blockers.append(
                    f"execution_expected_asset_unsubscribed:{event_slug}:{asset_id}"
                )
        uncovered_decision_count = expected["uncovered_decision_count"]
        if uncovered_decision_count:
            blockers.append(
                f"decision_time_not_covered:{event_slug}={uncovered_decision_count}"
            )
        uncovered_count = expected["uncovered_count"]
        if uncovered_count:
            blockers.append(
                f"quote_lifetime_not_covered:{event_slug}={uncovered_count}"
            )
        event_rows.append({
            "event_slug": event_slug,
            "target_dates": sorted(value for value in expected["target_dates"] if value),
            "order_books_jsonl_path": str(book_path),
            "full_depth_book_tape_present": full_depth_book_tape_present,
            "execution_raw_tape_path": str(raw_path),
            "execution_canonical_tape_path": str(csv_path),
            "session_receipt_path": str(session_path),
            "execution_tape_present": tape_present,
            "execution_zero_proven": zero_execution_proven,
            "execution_evidence_complete": execution_evidence_complete,
            "session_receipt_count": len(sessions),
            "complete_session_count": len(complete_sessions),
            "invalid_session_receipt_count": len(invalid_sessions) + len(session_parse_errors),
            "bound_execution_audit_key_count": len(bound_execution_audit_keys),
            "fill_count": len(fills_by_event.get(event_slug, ())),
            "unbound_execution_fill_count": len(unbound_fill_ids),
            "unbound_execution_fill_ids": unbound_fill_ids[:100],
            "decision_row_count": expected["decision_row_count"],
            "uncovered_decision_count": uncovered_decision_count,
            "uncovered_decision_ids": expected["uncovered_decision_examples"],
            "quote_leg_count": expected["quote_leg_count"],
            "uncovered_quote_leg_count": uncovered_count,
            "uncovered_quote_leg_ids": expected["uncovered_examples"],
        })
    return {
        "schema_version": TAPE_INVENTORY_SCHEMA_VERSION,
        "status": "PASS" if event_rows and not blockers else "BLOCK",
        "expected_event_count": len(event_rows),
        "blockers": sorted(set(blockers or (["no_expected_events"] if not event_rows else []))),
        "events": event_rows,
    }


def build_day_countability(
    quote_rows,
    legs,
    fill_rows,
    *,
    snapshots_root,
    fill_evidence,
    reward_q_share,
    target_date=None,
    reservation_gate=None,
):
    selected_target = str(target_date) if target_date else None

    def selected(rows):
        return (
            row for row in rows or []
            if selected_target is None
            or str(row.get("target_date") or "") == selected_target
        )

    if selected_target is not None:
        target_dates = [selected_target]
    else:
        target_dates = set()
        for rows in (quote_rows or [], legs or [], fill_rows or []):
            for row in rows:
                if row.get("target_date"):
                    target_dates.add(str(row["target_date"]))
        target_dates = sorted(target_dates)
    tape = build_execution_tape_inventory(
        selected(quote_rows),
        selected(legs),
        snapshots_root,
        fill_rows=selected(fill_rows),
    )
    blockers = list(tape.get("blockers") or [])
    reservation_gate = reservation_gate or {
        "status": "BLOCK",
        "blockers": ["reservation_gate_missing"],
    }
    if reservation_gate.get("status") != "PASS":
        blockers.extend(
            f"reservation:{blocker}"
            for blocker in reservation_gate.get("blockers") or ["blocked"]
        )
    if len(target_dates) != 1:
        blockers.append("expected_exactly_one_target_date")
    settlement_missing_count = 0
    settlement_missing_ids = []
    non_strict_fill_count = 0
    incomplete_execution_fill_count = 0
    missing_markout_fill_count = 0
    missing_markout_ids = []
    fill_count = 0
    for row in selected(fill_rows):
        fill_count += 1
        if row.get("conservative_fill_rule") != "strict_trade_through_price_and_recorded_size":
            non_strict_fill_count += 1
        required_execution_values = (
            row.get("execution_exchange_time_utc"),
            row.get("execution_time_precision_seconds"),
            row.get("clob_token_id"),
            row.get("execution_condition_id"),
            row.get("execution_side"),
            row.get("through_trade_price"),
            row.get("through_trade_size"),
            row.get("execution_raw_sha1"),
            row.get("canonical_execution_id") or row.get("execution_id"),
        )
        if any(value is None or value == "" for value in required_execution_values):
            incomplete_execution_fill_count += 1
        if any(
            row.get(field) is None or row.get(field) == ""
            for field in (
                "markout_30s_per_share",
                "markout_1m_per_share",
                "markout_5m_per_share",
                "markout_30m_per_share",
            )
        ):
            missing_markout_fill_count += 1
            if len(missing_markout_ids) < 100:
                missing_markout_ids.append(str(row.get("fill_id") or "unknown"))
        if row.get("acceptance_pnl_status") != "COUNTABLE_SETTLEMENT":
            settlement_missing_count += 1
            if len(settlement_missing_ids) < 100:
                settlement_missing_ids.append(str(row.get("fill_id") or "unknown"))
    if settlement_missing_count:
        blockers.append(f"settlement_horizon_missing={settlement_missing_count}")
    if non_strict_fill_count:
        blockers.append(f"non_strict_through_fills={non_strict_fill_count}")
    if incomplete_execution_fill_count:
        blockers.append(
            f"execution_provenance_incomplete_fills={incomplete_execution_fill_count}"
        )
    if missing_markout_fill_count:
        blockers.append(f"required_markout_horizons_missing={missing_markout_fill_count}")
    target_fill_evidence = fill_evidence or {}
    if selected_target is not None:
        target_fill_evidence = (
            (fill_evidence or {}).get("by_target_date") or {}
        ).get(selected_target) or fill_evidence or {}
    fill_blockers = [
        blocker for blocker in target_fill_evidence.get("blockers") or []
        if blocker != "no_quote_legs"
    ]
    blockers.extend(f"fill_evidence:{blocker}" for blocker in fill_blockers)
    selected_leg_count = sum(1 for _row in selected(legs))
    target_reward_q_share = reward_q_share or {}
    if selected_target is not None:
        target_reward_q_share = (
            (reward_q_share or {}).get("by_target_date") or {}
        ).get(selected_target) or {
            "status": "NOT_APPLICABLE" if selected_leg_count == 0 else "BLOCK",
            "exact_sampled": selected_leg_count == 0,
            "quoted_legs": selected_leg_count,
            "sampled_legs": 0,
            "blockers": [] if selected_leg_count == 0 else ["target_date_samples_missing"],
        }
    reward_status = target_reward_q_share.get("status")
    if selected_leg_count and (
        reward_status != "PASS"
        or not bool(target_reward_q_share.get("exact_sampled"))
    ):
        blockers.append("reward_q_share_not_exact")
    blockers = sorted(set(blockers))
    status = "COUNTABLE" if not blockers else "NOT_COUNTABLE"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "counts_toward_maker_day_target": status == "COUNTABLE",
        "target_dates": target_dates,
        "checklist": {
            "exactly_one_target_date": len(target_dates) == 1,
            "confirmation_reservation_clear": reservation_gate.get("status") == "PASS",
            "execution_tape_present": tape.get("status") == "PASS",
            "full_depth_book_tape_present": not any(
                blocker.startswith("full_depth_book_tape_missing:") for blocker in blockers
            ),
            "decision_times_continuously_covered": not any(
                blocker.startswith("decision_time_not_covered:") for blocker in blockers
            ),
            "quote_lifetimes_continuously_covered": not any(
                blocker.startswith("quote_lifetime_not_covered:") for blocker in blockers
            ),
            "strict_through_only": non_strict_fill_count == 0,
            "execution_provenance_complete": (
                incomplete_execution_fill_count == 0
                and not any(
                    blocker.startswith("execution_fill_not_bound:")
                    for blocker in blockers
                )
            ),
            "all_required_markouts_complete": missing_markout_fill_count == 0,
            "settlement_horizon_complete": settlement_missing_count == 0,
            "fill_evidence_complete": not fill_blockers,
            "reward_q_share_exact_when_quoted": not selected_leg_count or reward_status == "PASS",
        },
        "blockers": blockers,
        "first_blocker": blockers[0] if blockers else None,
        "quote_rows": sum(1 for _row in selected(quote_rows)),
        "quote_legs": selected_leg_count,
        "strict_through_fills": fill_count,
        "non_strict_through_fill_count": non_strict_fill_count,
        "execution_provenance_incomplete_fill_count": incomplete_execution_fill_count,
        "required_markout_missing_fill_count": missing_markout_fill_count,
        "required_markout_missing_fill_ids": missing_markout_ids,
        "settlement_missing_fill_count": settlement_missing_count,
        "settlement_missing_fill_ids": settlement_missing_ids,
        "execution_tape_inventory": tape,
        "reward_q_share_status": reward_status,
        "reward_q_share": target_reward_q_share,
        "fill_evidence": target_fill_evidence,
        "confirmation_reservation_gate": reservation_gate,
    }
