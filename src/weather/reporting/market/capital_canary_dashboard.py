"""Bounded, read-only projection for the capital-canary dashboard.

This module is intentionally separated from exchange and worker code.  It reads
only the canary's local projections, never resolves credentials, and never
turns a readiness classification into order authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.schema_registry import schema_version


DASHBOARD_SCHEMA_VERSION = schema_version("capital_canary_dashboard")
STATUS_SCHEMA_VERSION = schema_version("capital_canary_status")
DEFAULT_ROOT = data_path("live_taker_canary")
DEFAULT_STATUS_PATH = DEFAULT_ROOT / "status.json"
DEFAULT_MAX_AGE_SECONDS = 30.0
DEFAULT_MAX_STATUS_BYTES = 2 * 1024 * 1024
MAX_POSITIONS = 100
MAX_TARGETS = 50
MAX_ACTIVITY = 100
MAX_BLOCKERS = 50
MAX_TEXT_CHARS = 1_000

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_REDACTED_ACCOUNT_RE = re.compile(
    r"^(?:sha256:[0-9a-f]{12}(?:[0-9a-f]{52}|\.{3}|…)|acct_sha256:[0-9a-f]{64})$",
    re.IGNORECASE,
)
_KNOWN_DECLARED_STATUSES = frozenset(
    {"RUNNING", "BLOCKED", "LOCKED", "PAUSED", "HALTED", "STALE", "INVALID"}
)
_RISKY_KEY_RE = re.compile(
    r"(?:^|_)(?:api_?key|api_?secret|secret|private_?key|passphrase|password|"
    r"authorization|bearer|mnemonic|seed(?:_phrase)?|access_?token|refresh_?token|"
    r"credential(?:s)?|wallet_?address|account_?address)(?:$|_)",
    re.IGNORECASE,
)
_RISKY_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(api[-_ ]?key|api[-_ ]?secret|secret|private[-_ ]?key|passphrase|"
    r"password|authorization|bearer|mnemonic|seed(?:[-_ ]?phrase)?|"
    r"access[-_ ]?token|refresh[-_ ]?token)\b[\"']?\s*[:=]\s*"
    r"(?:[\"']?bearer\s+)?[\"']?([^\s,;}\"']+)[\"']?"
)
_BEARER_VALUE_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")

_BLOCKING_AUTHORITY_STATES = frozenset(
    {"LOCKED", "PREFLIGHT", "ARMED", "RECONCILE_ONLY", "PAUSED", "HALTED"}
)
_KNOWN_AUTHORITY_STATES = _BLOCKING_AUTHORITY_STATES | frozenset(
    {"SCANNING", "SUBMITTING", "EXPOSED"}
)

_POSITION_FIELDS = (
    "position_id",
    "event_id",
    "market_id",
    "event_slug",
    "target_date",
    "range_label",
    "side",
    "outcome",
    "quantity",
    "average_entry_price",
    "entry_notional_usdc",
    "fees_usdc",
    "worst_case_loss_usdc",
    "executable_bid",
    "unrealized_executable_bid_pnl_usdc",
    "settled",
    "settlement_state",
    "opened_at_utc",
    "updated_at_utc",
)
_TARGET_FIELDS = (
    "decision_id",
    "event_id",
    "market_id",
    "event_slug",
    "target_date",
    "range_label",
    "side",
    "executable_ask",
    "max_price",
    "spread",
    "quantity",
    "max_loss_usdc",
    "fair_value_lower_bound",
    "after_cost_edge_per_share",
    "expected_after_cost_roi",
    "decision",
    "hold_reason",
    "evaluated_at_utc",
)
_ACTIVITY_FIELDS = (
    "sequence",
    "event_type",
    "state",
    "code",
    "detail",
    "event_id",
    "market_id",
    "order_id",
    "occurred_at_utc",
)
_PROVENANCE_FIELDS = (
    "release_id",
    "release_manifest_sha256",
    "activation_sha256",
    "platform",
    "redacted_account_id",
    "policy_id",
    "policy_sha256",
    "risk_caps_sha256",
    "economics_snapshot_id",
    "economics_sha256",
    "permission_snapshot_id",
    "permission_sha256",
    "input_snapshot_id",
    "input_snapshot_sha256",
    "code_sha256",
    "schema_version",
    "status_sha256",
    "snapshot_hash",
    "sequence",
    "ledger_high_water_marks",
    "ledger_high_water",
    "positions_sha256",
    "portfolio_sha256",
)
_ACCOUNT_NUMBER_FIELDS = (
    "net_liquidation_value_usdc",
    "cash_usdc",
    "reserve_usdc",
    "unresolved_worst_case_loss_usdc",
    "capital_ceiling_usdc",
    "cap_utilization",
)
_PERFORMANCE_NUMBER_FIELDS = (
    "settled_realized_pnl_usdc",
    "unrealized_executable_bid_pnl_usdc",
    "fees_usdc",
    "drawdown_usdc",
    "market_following_pnl_usdc",
    "no_trade_pnl_usdc",
)


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return None


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "enabled", "engaged"}:
            return True
        if normalized in {"false", "no", "0", "disabled", "clear"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    return None


def _safe_text(value: Any, *, limit: int = MAX_TEXT_CHARS) -> str | None:
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return None
    text = " ".join(str(value).replace("\x00", " ").split()).strip()
    if not text:
        return None
    text = _RISKY_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _BEARER_VALUE_RE.sub("Bearer [REDACTED]", text)
    return text[: max(1, int(limit))]


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _finite_number(value)
    return _safe_text(value)


def _safe_redacted_account(value: Any) -> str | None:
    text = _safe_text(value, limit=160)
    return text if text and _REDACTED_ACCOUNT_RE.fullmatch(text) else None


def _parse_timestamp(value: Any) -> datetime | None:
    text = _safe_text(value, limit=128)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _canonical_sha256(payload: Mapping[str, Any], hash_field: str) -> str | None:
    try:
        encoded = json.dumps(
            {key: value for key, value in payload.items() if key != hash_field},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _self_hash_valid(payload: Mapping[str, Any], hash_field: str) -> bool:
    actual = str(payload.get(hash_field) or "").strip().lower()
    return bool(
        _HASH_RE.fullmatch(actual)
        and actual == _canonical_sha256(payload, hash_field)
    )


def _stable_bounded_json(
    path: Path,
    *,
    max_bytes: int,
) -> tuple[dict[str, Any] | None, str]:
    """Read one regular JSON object without accepting torn or unbounded bytes."""

    limit = max(1, int(max_bytes))
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                return None, "not_regular_file"
            if before.st_size <= 0:
                return None, "empty"
            if before.st_size > limit:
                return None, "oversized"
            raw = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "read_error"
    if len(raw) > limit:
        return None, "oversized"
    if len(raw) != before.st_size:
        return None, "short_read"
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
    ):
        return None, "changed_during_read"
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for key, value in pairs:
            if key in decoded:
                raise ValueError(f"duplicate JSON key: {key}")
            decoded[key] = value
        return decoded

    try:
        payload = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {value}")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return None, "malformed"
    if not isinstance(payload, dict):
        return None, "not_object"
    return payload, "ok"


def _snapshot(
    path: Path,
    *,
    max_bytes: int,
    expected_schema: str | None = None,
    hash_field: str,
) -> tuple[dict[str, Any] | None, str]:
    payload, status = _stable_bounded_json(path, max_bytes=max_bytes)
    if payload is None:
        return None, status
    if expected_schema is not None and payload.get("schema_version") != expected_schema:
        return None, "schema_mismatch"
    if not _self_hash_valid(payload, hash_field):
        return None, f"{hash_field}_invalid"
    sequence = payload.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        return None, "sequence_invalid"
    if _parse_timestamp(payload.get("generated_at_utc")) is None:
        return None, "generated_at_invalid"
    return payload, "ok"


def _safe_row(row: Any, fields: Sequence[str]) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    safe: dict[str, Any] = {}
    for field in fields:
        if _RISKY_KEY_RE.search(field) or field not in row:
            continue
        value = row.get(field)
        if field in {
            "quantity",
            "average_entry_price",
            "entry_notional_usdc",
            "fees_usdc",
            "worst_case_loss_usdc",
            "executable_bid",
            "unrealized_executable_bid_pnl_usdc",
            "executable_ask",
            "max_price",
            "spread",
            "max_loss_usdc",
            "fair_value_lower_bound",
            "after_cost_edge_per_share",
            "expected_after_cost_roi",
            "sequence",
        }:
            safe[field] = _finite_number(value)
        elif field == "settled":
            safe[field] = _optional_bool(value)
        else:
            safe[field] = _safe_scalar(value)
    return safe


def _safe_rows(
    value: Any,
    fields: Sequence[str],
    *,
    limit: int,
    keep_tail: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(value, list):
        return [], False
    rows = value[-limit:] if keep_tail else value[:limit]
    projected = [safe for row in rows if (safe := _safe_row(row, fields)) is not None]
    return projected, len(value) > limit


def _blockers(value: Any) -> tuple[list[dict[str, str | None]], bool, bool]:
    if value is None:
        return [], False, False
    if not isinstance(value, list):
        return [], False, True
    rows: list[dict[str, str | None]] = []
    malformed = False
    for item in value[:MAX_BLOCKERS]:
        if isinstance(item, Mapping):
            code = _safe_text(_first(item, "code", "category", "reason"), limit=160)
            detail = _safe_text(_first(item, "detail", "message", "next_action"))
        else:
            code = None
            detail = None
        if code:
            rows.append({"code": code, "detail": detail})
        else:
            malformed = True
    return rows, len(value) > MAX_BLOCKERS, malformed


def _warnings(value: Any) -> tuple[list[str], bool]:
    if not isinstance(value, list):
        return [], False
    rows = [text for item in value[:MAX_BLOCKERS] if (text := _safe_text(item))]
    return rows, len(value) > MAX_BLOCKERS


def _safe_high_water(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= 50:
            break
        safe_key = _safe_text(key, limit=100)
        if not safe_key or _RISKY_KEY_RE.search(safe_key):
            continue
        if isinstance(item, Mapping):
            result[safe_key] = {
                field: _safe_scalar(item[field])
                for field in ("sequence", "record_hash")
                if field in item
            }
        else:
            result[safe_key] = _safe_scalar(item)
    return result


def _provenance(status: Mapping[str, Any]) -> dict[str, Any]:
    nested = _mapping(status.get("provenance"))
    authority = _mapping(status.get("authority"))
    risk = _mapping(status.get("risk"))
    result: dict[str, Any] = {}
    for field in _PROVENANCE_FIELDS:
        if _RISKY_KEY_RE.search(field):
            continue
        value = _first(nested, field)
        if value is None:
            value = _first(status, field)
        if value is None and field == "release_id":
            value = authority.get("release_id")
        if value is None and field == "release_manifest_sha256":
            value = authority.get("manifest_sha256")
        if value is None and field == "platform":
            value = authority.get("platform")
        if value is None and field == "redacted_account_id":
            value = authority.get("account_id_redacted")
        if value is None and field == "policy_id":
            value = _first(risk, "policy_id") or nested.get("risk_policy_id")
        if value is None and field == "policy_sha256":
            value = _first(risk, "risk_policy_sha256") or nested.get(
                "risk_policy_sha256"
            )
        if value is None and field == "risk_caps_sha256":
            value = _first(risk, "risk_caps_sha256") or nested.get(
                "risk_caps_sha256"
            )
        if value is None:
            continue
        if field in {"ledger_high_water", "ledger_high_water_marks"}:
            safe = _safe_high_water(value)
        elif field == "redacted_account_id":
            safe = _safe_redacted_account(value)
        else:
            safe = _safe_scalar(value)
        if safe is not None:
            result[field] = safe
    result["source_schema_version"] = _safe_text(status.get("schema_version"), limit=128)
    result["status_sha256"] = _safe_text(status.get("status_sha256"), limit=64)
    return result


def _display_state(authority_state: str, campaign_stage: str | None) -> str:
    if authority_state == "LOCKED":
        return "LOCKED"
    if authority_state in {"PREFLIGHT", "ARMED", "RECONCILE_ONLY"}:
        return "PREFLIGHT" if authority_state == "PREFLIGHT" else "PROBE"
    if authority_state == "PAUSED":
        return "PAUSED"
    if authority_state == "HALTED":
        return "HALTED"
    if authority_state in {"SCANNING", "SUBMITTING", "EXPOSED"}:
        normalized = str(campaign_stage or "").strip().lower()
        return (
            "LIVE"
            if normalized in {"alpha", "alpha_canary", "live"}
            else "PROBE"
        )
    return "LOCKED"


def _empty_payload(now: datetime) -> dict[str, Any]:
    return {
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "generated_at_utc": _iso(now),
        "source_status": "NO_DATA",
        "display_state": "LOCKED",
        "status_message": "No capital-canary status is available.",
        "as_of_utc": None,
        "heartbeat": {"at_utc": None, "age_seconds": None, "freshness": "UNKNOWN"},
        "freshness": {
            "stale": True,
            "status_data_stale": True,
            "status_generated_at_utc": None,
            "status_age_seconds": None,
            "position_data_stale": True,
            "portfolio_data_stale": True,
            "position_state_known": False,
            "not_assumed_flat": True,
        },
        "safety": {
            "authority_state": "LOCKED",
            "campaign_stage": None,
            "capital_locked": True,
            "kill_switch_engaged": True,
            "reconciliation_state": "UNKNOWN",
            "activation_status": "UNKNOWN",
            "activation_expires_at_utc": None,
            "order_submission_enabled": False,
            "classification_only": True,
        },
        "readiness": {
            "classification": None,
            "classification_only": True,
            "grants_authority": False,
        },
        "account": {
            "platform": None,
            "redacted_account_id": None,
            **{field: None for field in _ACCOUNT_NUMBER_FIELDS},
        },
        "performance": {field: None for field in _PERFORMANCE_NUMBER_FIELDS},
        "positions": [],
        "targets": [],
        "activity": [],
        "blockers": [],
        "warnings": [],
        "provenance": {},
    }


def build_capital_canary_dashboard(
    status_payload: Mapping[str, Any] | None,
    *,
    positions_payload: Mapping[str, Any] | None = None,
    portfolio_payload: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    status_read_state: str = "ok",
    positions_read_state: str = "missing",
    portfolio_read_state: str = "missing",
) -> dict[str, Any]:
    """Project already verified snapshots into a display-only dashboard model."""

    now_utc = _utc_now(now)
    result = _empty_payload(now_utc)
    status = _mapping(status_payload)
    positions_snapshot = _mapping(positions_payload)
    portfolio_snapshot = _mapping(portfolio_payload)

    embedded_positions_present = isinstance(status.get("positions"), list)
    sidecar_positions_present = isinstance(positions_snapshot.get("positions"), list)
    raw_positions = (
        positions_snapshot.get("positions")
        if sidecar_positions_present
        else status.get("positions") if embedded_positions_present else []
    )
    positions, positions_truncated = _safe_rows(
        raw_positions, _POSITION_FIELDS, limit=MAX_POSITIONS
    )
    position_state_claim = _optional_bool(
        _first(positions_snapshot, "position_state_known", "positions_state_known")
        if sidecar_positions_present
        else _first(status, "position_state_known", "positions_state_known")
    )
    position_state_known = bool(
        (sidecar_positions_present or embedded_positions_present)
        and position_state_claim is True
    )
    result["positions"] = positions

    if not status:
        result["source_status"] = "NO_DATA" if status_read_state == "missing" else "INVALID"
        result["status_message"] = (
            "No capital-canary status is available."
            if status_read_state == "missing"
            else "The capital-canary status could not be verified."
        )
        if status_read_state != "missing":
            result["blockers"] = [
                {"code": f"status_{status_read_state}", "detail": None}
            ]
        result["freshness"].update(
            {
                "position_state_known": position_state_known and not positions_truncated,
                "not_assumed_flat": True,
            }
        )
        if positions_truncated:
            result["warnings"].append("positions_truncated")
        return result

    bot_source = _mapping(status.get("bot"))
    heartbeat_block = _mapping(status.get("heartbeat"))
    safety_source = _mapping(status.get("safety"))
    authority_source = _mapping(status.get("authority"))
    authority_state = str(
        _first(status, "authority_state", "state")
        or _first(safety_source, "authority_state", "state")
        or _first(bot_source, "state")
        or "LOCKED"
    ).strip().upper()
    if authority_state not in _KNOWN_AUTHORITY_STATES:
        authority_state = "LOCKED"

    generated_dt = _parse_timestamp(status.get("generated_at_utc"))
    generated_age = (
        (now_utc - generated_dt).total_seconds()
        if generated_dt is not None
        else None
    )
    status_fresh = bool(
        generated_age is not None
        and generated_age >= -5.0
        and generated_age <= max(0.0, float(max_age_seconds))
    )
    if "heartbeat_at_utc" in status:
        heartbeat_at = status.get("heartbeat_at_utc")
    elif any(key in heartbeat_block for key in ("at_utc", "heartbeat_at_utc")):
        heartbeat_at = _first(heartbeat_block, "at_utc", "heartbeat_at_utc")
    elif "heartbeat_at_utc" in bot_source:
        heartbeat_at = bot_source.get("heartbeat_at_utc")
    else:
        heartbeat_at = _first(status, "updated_at_utc", "generated_at_utc")
    heartbeat_dt = _parse_timestamp(heartbeat_at)
    heartbeat_age: float | None = None
    heartbeat_freshness = "UNKNOWN"
    if heartbeat_dt is not None:
        heartbeat_age = (now_utc - heartbeat_dt).total_seconds()
        if heartbeat_age < -5.0:
            heartbeat_freshness = "FUTURE"
        elif heartbeat_age > max(0.0, float(max_age_seconds)):
            heartbeat_freshness = "STALE"
        else:
            heartbeat_freshness = "FRESH"
    heartbeat_required = authority_state in {
        "ARMED",
        "RECONCILE_ONLY",
        "SCANNING",
        "SUBMITTING",
        "EXPOSED",
    }
    stale = bool(not status_fresh or (heartbeat_required and heartbeat_freshness != "FRESH"))
    result["as_of_utc"] = _iso(generated_dt) if generated_dt is not None else None
    result["heartbeat"] = {
        "at_utc": _iso(heartbeat_dt) if heartbeat_dt is not None else None,
        "age_seconds": heartbeat_age,
        "freshness": heartbeat_freshness,
    }

    campaign_stage = _safe_text(
        _first(status, "campaign_stage", "stage")
        or _first(safety_source, "campaign_stage", "stage"),
        limit=80,
    )
    activation = _mapping(status.get("activation"))
    reconciliation = _mapping(status.get("reconciliation"))
    activation_status = (
        _safe_text(
            _first(activation, "status", "state")
            or _first(authority_source, "activation_status"),
            limit=80,
        )
        or "UNKNOWN"
    ).upper()
    reconciliation_state = (
        _safe_text(
            _first(reconciliation, "status", "state")
            or _first(safety_source, "reconciliation_state"),
            limit=80,
        )
        or "UNKNOWN"
    ).upper()
    activation_expires = _safe_text(
        _first(activation, "expires_at_utc", "expiry_utc")
        or _first(safety_source, "activation_expires_at_utc"),
        limit=128,
    ) or _safe_text(
        _first(authority_source, "expires_at_utc"),
        limit=128,
    )

    blockers, blockers_truncated, blockers_malformed = _blockers(
        status.get("blockers")
    )
    if blockers_malformed:
        blockers.append(
            {
                "code": "status_blockers_malformed",
                "detail": "The source blocker contract is malformed.",
            }
        )
    warnings, warnings_truncated = _warnings(status.get("warnings"))
    explicit_order_enabled = _optional_bool(
        _first(status, "order_submission_enabled")
        if "order_submission_enabled" in status
        else _first(safety_source, "order_submission_enabled")
        if "order_submission_enabled" in safety_source
        else _first(authority_source, "order_submission_enabled")
    )
    source_capital_locked = _optional_bool(
        _first(status, "capital_locked")
        if "capital_locked" in status
        else _first(safety_source, "capital_locked")
    )
    source_kill_switch = _optional_bool(
        _first(status, "kill_switch_engaged", "kill_switch")
        if any(key in status for key in ("kill_switch_engaged", "kill_switch"))
        else _first(safety_source, "kill_switch_engaged", "kill_switch")
        if any(key in safety_source for key in ("kill_switch_engaged", "kill_switch"))
        else _first(bot_source, "kill_switch_state")
    )
    declared_status = str(status.get("status") or "").strip().upper()
    if declared_status not in _KNOWN_DECLARED_STATUSES:
        blockers.append(
            {
                "code": "status_declared_status_unknown",
                "detail": "The source status value is missing or unsupported.",
            }
        )
    activation_expiry_dt = _parse_timestamp(activation_expires)
    if activation_status in {"VALID", "ACTIVE", "PASS"} and (
        activation_expiry_dt is None or activation_expiry_dt <= now_utc
    ):
        blockers.append(
            {
                "code": "status_activation_expiry_invalid",
                "detail": "Active authority requires a current, valid activation expiry.",
            }
        )
    authority_account_claim = authority_source.get("account_id_redacted")
    safe_authority_account = _safe_redacted_account(authority_account_claim)
    if activation_status in {"VALID", "ACTIVE", "PASS"} and (
        authority_account_claim is not None and safe_authority_account is None
    ):
        blockers.append(
            {
                "code": "status_account_redaction_invalid",
                "detail": "The active account identity is not safely redacted.",
            }
        )
    source_actionable = _optional_bool(status.get("actionable"))
    source_read_only = _optional_bool(status.get("read_only"))
    safety_blocked = bool(
        stale
        or blockers
        or declared_status in {"BLOCKED", "LOCKED", "STALE", "INVALID"}
        or activation_status not in {"VALID", "ACTIVE", "PASS"}
        or reconciliation_state not in {"RECONCILED", "CLEAR", "PASS"}
        or source_capital_locked is not False
        or source_kill_switch is not False
        or source_actionable is not True
        or source_read_only is not False
    )
    placement_claim_blocked = bool(
        safety_blocked or authority_state != "SCANNING"
    )
    effective_order_enabled = bool(
        explicit_order_enabled is True and not placement_claim_blocked
    )

    readiness_source = _mapping(status.get("readiness"))
    readiness_classification = _safe_text(
        _first(readiness_source, "classification", "stage", "status")
        or _first(status, "readiness_classification", "readiness_status")
        or _first(authority_source, "production_readiness_stage"),
        limit=100,
    )
    result["readiness"] = {
        "classification": readiness_classification,
        "classification_only": True,
        "grants_authority": False,
    }
    result["display_state"] = _display_state(authority_state, campaign_stage)
    result["safety"] = {
        "authority_state": authority_state,
        "campaign_stage": campaign_stage,
        "capital_locked": True if safety_blocked else source_capital_locked is not False,
        "kill_switch_engaged": True if safety_blocked else source_kill_switch is not False,
        "reconciliation_state": reconciliation_state,
        "activation_status": activation_status,
        "activation_expires_at_utc": activation_expires,
        "order_submission_enabled": effective_order_enabled,
        "classification_only": True,
    }

    raw_targets = _first(status, "targets", "evaluated_targets", "candidate_targets")
    targets, targets_truncated = _safe_rows(raw_targets, _TARGET_FIELDS, limit=MAX_TARGETS)
    result["targets"] = [] if placement_claim_blocked else targets
    raw_activity = _first(status, "activity", "recent_activity", "events")
    activity, activity_truncated = _safe_rows(
        raw_activity, _ACTIVITY_FIELDS, limit=MAX_ACTIVITY, keep_tail=True
    )
    result["activity"] = activity

    raw_portfolio = _mapping(portfolio_snapshot.get("portfolio")) or portfolio_snapshot
    if not raw_portfolio:
        raw_portfolio = (
            _mapping(status.get("portfolio"))
            or _mapping(status.get("account"))
            or _mapping(status.get("fund"))
        )
    raw_account = _mapping(status.get("account"))
    account = {
        "platform": _safe_text(
            _first(raw_portfolio, "platform")
            or _first(raw_account, "platform")
            or _first(status, "platform")
            or _first(authority_source, "platform"),
            limit=100,
        ),
        "redacted_account_id": next(
            (
                safe
                for candidate in (
                    _first(raw_portfolio, "redacted_account_id", "account_redaction"),
                    _first(raw_account, "redacted_account_id", "account_redaction"),
                    _first(status, "redacted_account_id", "account_redaction"),
                    _first(authority_source, "account_id_redacted"),
                )
                if (safe := _safe_redacted_account(candidate)) is not None
            ),
            None,
        ),
    }
    for field in _ACCOUNT_NUMBER_FIELDS:
        aliases = {
            "cash_usdc": ("cash_usdc", "cash_available_usdc"),
            "reserve_usdc": ("reserve_usdc", "cash_reserved_usdc"),
            "unresolved_worst_case_loss_usdc": (
                "unresolved_worst_case_loss_usdc",
                "open_max_loss_usdc",
            ),
            "capital_ceiling_usdc": (
                "capital_ceiling_usdc",
                "starting_capital_usdc",
            ),
        }.get(field, (field,))
        value = _first(raw_portfolio, *aliases)
        if value is None:
            value = _first(raw_account, *aliases)
        if value is None and field == "unresolved_worst_case_loss_usdc":
            value = _first(_mapping(status.get("risk")), "open_max_loss_usdc")
        if value is None and field == "cap_utilization":
            utilization = _mapping(_mapping(status.get("risk")).get("cap_utilization"))
            value = _first(utilization, "total", "lifetime", "capital")
        if value is None and field == "capital_ceiling_usdc":
            value = _first(authority_source, "authorized_budget_usdc")
        account[field] = _finite_number(value)
    result["account"] = account

    performance_source = _mapping(raw_portfolio.get("performance"))
    if not performance_source:
        performance_source = _mapping(status.get("performance"))
    fund_source = _mapping(status.get("fund"))
    performance_aliases = {
        "settled_realized_pnl_usdc": ("settled_realized_pnl_usdc", "realized_settlement_pnl_usdc"),
        "unrealized_executable_bid_pnl_usdc": (
            "unrealized_executable_bid_pnl_usdc",
            "unrealized_executable_pnl_usdc",
        ),
        "market_following_pnl_usdc": ("market_following_pnl_usdc", "market_benchmark_pnl_usdc"),
        "no_trade_pnl_usdc": ("no_trade_pnl_usdc", "no_trade_benchmark_pnl_usdc"),
    }
    result["performance"] = {}
    for field in _PERFORMANCE_NUMBER_FIELDS:
        aliases = performance_aliases.get(field, (field,))
        value = _first(performance_source, *aliases)
        if value is None:
            value = _first(fund_source, *aliases)
        result["performance"][field] = _finite_number(value)
    result["provenance"] = _provenance(status)

    positions_stale = bool(
        stale
        or not position_state_known
        or positions_read_state not in {"ok", "embedded"}
    )
    if positions_read_state == "missing" and embedded_positions_present:
        positions_stale = stale
    portfolio_embedded = bool(
        status.get("portfolio") or status.get("account") or status.get("fund")
    )
    portfolio_state_claim = _optional_bool(
        _first(portfolio_snapshot, "portfolio_state_known")
        if portfolio_snapshot
        else _first(status, "portfolio_state_known")
    )
    portfolio_state_known = bool(
        (portfolio_snapshot or portfolio_embedded) and portfolio_state_claim is True
    )
    portfolio_stale = bool(
        stale
        or not portfolio_state_known
        or portfolio_read_state not in {"ok", "embedded"}
    )
    if portfolio_read_state == "missing" and portfolio_embedded:
        portfolio_stale = stale
    result["freshness"] = {
        "stale": stale,
        "status_data_stale": stale,
        "status_generated_at_utc": _iso(generated_dt) if generated_dt is not None else None,
        "status_age_seconds": generated_age,
        "position_data_stale": positions_stale,
        "portfolio_data_stale": portfolio_stale,
        "position_state_known": position_state_known and not positions_truncated,
        "not_assumed_flat": bool(stale or not position_state_known or positions_truncated),
    }

    if blockers_truncated:
        warnings.append("blockers_truncated")
    if warnings_truncated:
        warnings.append("warnings_truncated")
    if positions_truncated:
        warnings.append("positions_truncated")
    if targets_truncated:
        warnings.append("targets_truncated")
    if activity_truncated:
        warnings.append("activity_truncated")
    if positions_read_state not in {"ok", "missing", "embedded"}:
        warnings.append(f"positions_{positions_read_state}")
    if portfolio_read_state not in {"ok", "missing", "embedded"}:
        warnings.append(f"portfolio_{portfolio_read_state}")
    result["warnings"] = list(dict.fromkeys(warnings))
    result["blockers"] = blockers

    if stale:
        result["source_status"] = "STALE"
        result["status_message"] = (
            "Canary status is stale; targets and placement claims are hidden, "
            "and last-known positions are not assumed flat."
        )
    elif safety_blocked:
        result["source_status"] = "BLOCKED"
        result["status_message"] = "The capital canary is not permitted to place a new order."
    else:
        result["source_status"] = "FRESH"
        result["status_message"] = "Capital-canary status is current and read-only."
    return result


def load_capital_canary_dashboard(
    *,
    root: str | Path | None = None,
    status_path: str | Path | None = None,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    max_status_bytes: int = DEFAULT_MAX_STATUS_BYTES,
) -> dict[str, Any]:
    """Load the one registered status projection; ignore unregistered sidecars."""

    canary_root = Path(root) if root is not None else DEFAULT_ROOT
    path = Path(status_path) if status_path is not None else canary_root / "status.json"
    if status_path is not None and root is None:
        canary_root = path.parent
    status, status_state = _snapshot(
        path,
        max_bytes=max_status_bytes,
        expected_schema=STATUS_SCHEMA_VERSION,
        hash_field="status_sha256",
    )
    return build_capital_canary_dashboard(
        status,
        now=now,
        max_age_seconds=max_age_seconds,
        status_read_state=status_state,
        positions_read_state=(
            "embedded"
            if isinstance(_mapping(status).get("positions"), list)
            else "missing"
        ),
        portfolio_read_state=(
            "embedded"
            if any(key in _mapping(status) for key in ("portfolio", "account", "fund"))
            else "missing"
        ),
    )


__all__ = [
    "DASHBOARD_SCHEMA_VERSION",
    "DEFAULT_MAX_AGE_SECONDS",
    "DEFAULT_ROOT",
    "DEFAULT_STATUS_PATH",
    "STATUS_SCHEMA_VERSION",
    "build_capital_canary_dashboard",
    "load_capital_canary_dashboard",
]
