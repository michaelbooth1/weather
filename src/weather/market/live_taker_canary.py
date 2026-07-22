"""Capital-locked controller and status producer for the $75 taker canary.

This module is intentionally incapable of resolving credentials or talking to
an exchange.  It materializes a truthful read-only preflight/status contract
while the repository's capital gate is closed.  A future authenticated adapter
must live behind a separate reviewed change and cannot treat this status as
order authority.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from weather.io import write_json_atomic
from weather.market.live_taker_risk import (
    CanaryRiskPolicy,
    activation_caps,
    policy_hash,
)
from weather.market.live_taker_state import (
    GENESIS_HASH,
    SecretMaterialError,
    assert_secret_safe,
    status_content_sha256,
)
from weather.paths import data_path, relative_to_repo
from weather.release_artifacts import canonical_payload_sha256, strict_json_loads
from weather.schema_registry import schema_version


STATUS_SCHEMA_VERSION = schema_version("capital_canary_status")
ACTIVATION_SCHEMA_VERSION = schema_version("capital_canary_activation")
READINESS_SCHEMA_VERSION = schema_version("production_readiness_gate")
DEFAULT_ROOT = data_path("live_taker_canary")
DEFAULT_STATUS_PATH = DEFAULT_ROOT / "status.json"
DEFAULT_ACTIVATION_PATH = DEFAULT_ROOT / "activation.json"
DEFAULT_READINESS_PATH = data_path("backtest", "production_readiness_gate.json")

_DEFAULT_RISK_POLICY = CanaryRiskPolicy()
CAPITAL_CEILING_USDC = format(
    _DEFAULT_RISK_POLICY.campaign_capital_ceiling_usdc,
    "f",
)
RISK_POLICY_ID = "capital-canary-75-policy-1"
RISK_POLICY_SHA256 = policy_hash(_DEFAULT_RISK_POLICY)
RISK_CAPS: dict[str, str | int] = {
    key: int(value) if isinstance(value, int) else format(value, "f")
    for key, value in activation_caps(_DEFAULT_RISK_POLICY).items()
}
RISK_CAPS_SHA256 = canonical_payload_sha256(RISK_CAPS)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_LOCAL_PATH_RE = re.compile(
    r"(?i)(?:[A-Z]:[\\/](?:[^\\/\s]+[\\/])*[^\\/\s,;]+)"
)
_CAPITAL_STAGE = "CAPITAL_CANARY"
_MAX_READINESS_AGE = timedelta(minutes=15)
_SECRET_KEY_MARKERS = (
    "api_key",
    "credential",
    "mnemonic",
    "passphrase",
    "private_key",
    "raw_request",
    "secret",
    "signature",
    "signed_order",
)
_ACTIVATION_FIELDS = frozenset(
    {
        "schema_version",
        "activation_id",
        "platform",
        "release_id",
        "manifest_sha256",
        "account_id_sha256",
        "market_ids",
        "capital_ceiling_usdc",
        "risk_policy_id",
        "risk_policy_sha256",
        "risk_caps",
        "risk_caps_sha256",
        "authorized_at_utc",
        "expires_at_utc",
        "reviewed_by",
        "activation_sha256",
    }
)
_ACTIVATION_SCOPE_FIELDS = (
    "activation_id",
    "platform",
    "release_id",
    "manifest_sha256",
    "account_id_sha256",
    "market_ids",
    "capital_ceiling_usdc",
    "risk_policy_id",
    "risk_policy_sha256",
    "risk_caps",
    "risk_caps_sha256",
    "authorized_at_utc",
    "expires_at_utc",
    "reviewed_by",
)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("capital-canary times must include a timezone")
    return current.astimezone(timezone.utc)


def _utc_iso(value: datetime | None = None) -> str:
    return _utc(value).isoformat()


def _parse_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _blocker(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "detail": detail, **extra}


def _public_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return _LOCAL_PATH_RE.sub("[LOCAL_PATH]", value)


def _public_artifact_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    display = relative_to_repo(value)
    return "[EXTERNAL_ARTIFACT]" if Path(display).is_absolute() else display


def _is_env_like_path(value: str | Path) -> bool:
    name = Path(value).name.lower()
    return name == ".env" or name.startswith(".env.")


def _exact_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _secret_paths(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).strip().lower()
            path = f"{prefix}.{key}" if prefix else str(key)
            if any(marker in key_text for marker in _SECRET_KEY_MARKERS):
                found.append(path)
            found.extend(_secret_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_secret_paths(child, f"{prefix}[{index}]"))
    return found


def _read_stable_mapping(
    path: str | Path,
    *,
    max_bytes: int = 2 * 1024 * 1024,
) -> tuple[dict[str, Any] | None, str | None]:
    """Read one small JSON artifact without accepting a moving/partial file."""

    source = Path(path)
    if _is_env_like_path(source):
        return None, "env_path_refused"
    if source.is_symlink():
        return None, "symlink_refused"
    try:
        before = source.stat()
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        return None, f"stat_error:{type(exc).__name__}"
    if before.st_size <= 0:
        return None, "empty"
    if before.st_size > max_bytes:
        return None, "oversized"
    try:
        raw = source.read_bytes()
        after = source.stat()
    except OSError as exc:
        return None, f"read_error:{type(exc).__name__}"
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        return None, "concurrent_modification"
    try:
        value = strict_json_loads(raw.decode("utf-8-sig"), label=str(source))
    except (UnicodeError, ValueError):
        return None, "malformed"
    if not isinstance(value, dict):
        return None, "not_object"
    return value, None


def activation_content_sha256(payload: Mapping[str, Any]) -> str:
    """Hash the secret-free activation envelope excluding its self-hash."""

    return canonical_payload_sha256(payload, omit=("activation_sha256",))


def _activation_authorization_scope(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field_name: payload.get(field_name)
        for field_name in _ACTIVATION_SCOPE_FIELDS
    }


def _valid_readiness_authorization_scope(
    readiness: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    binding = readiness.get("capital_authorization_binding")
    binding = binding if isinstance(binding, Mapping) else {}
    scope = binding.get("scope")
    scope = scope if isinstance(scope, Mapping) else {}
    scope_hash = str(binding.get("scope_sha256") or "")
    source_hash = str(binding.get("source_evidence_sha256") or "")
    input_rows = readiness.get("inputs")
    input_rows = input_rows if isinstance(input_rows, list) else []
    capital_rows = [
        row
        for row in input_rows
        if isinstance(row, Mapping) and row.get("name") == "capital_canary"
    ]
    capital_row = capital_rows[0] if len(capital_rows) == 1 else {}
    if not (
        binding.get("status") == "PASS"
        and scope
        and _SHA256_RE.fullmatch(source_hash)
        and _SHA256_RE.fullmatch(scope_hash)
        and scope_hash == canonical_payload_sha256(scope)
        and capital_row.get("validation_status") == "PASS"
        and capital_row.get("sha256") == source_hash
    ):
        return None
    return scope


def _readiness_capital_pass(
    readiness: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    if readiness.get("schema_version") != READINESS_SCHEMA_VERSION:
        return False
    actual_hash = str(readiness.get("gate_sha256") or "")
    if not _SHA256_RE.fullmatch(actual_hash) or actual_hash != canonical_payload_sha256(
        readiness,
        omit=("gate_sha256",),
    ):
        return False
    permissions = readiness.get("capital_permissions")
    permissions = permissions if isinstance(permissions, Mapping) else {}
    if not (
        permissions.get("classification_only") is True
        and permissions.get("credential_access_permitted") is False
        and permissions.get("order_submission_permitted") is False
    ):
        return False
    generated = _parse_utc(readiness.get("generated_at_utc"))
    if generated is None:
        return False
    age = _utc(now) - generated
    if age < -timedelta(seconds=5) or age > _MAX_READINESS_AGE:
        return False
    results = readiness.get("stage_results")
    results = results if isinstance(results, Mapping) else {}
    capital = results.get(_CAPITAL_STAGE)
    capital = capital if isinstance(capital, Mapping) else {}
    return (
        readiness.get("status") == "PASS"
        and readiness.get("highest_permitted_stage") == _CAPITAL_STAGE
        and capital.get("status") == "PASS"
        and _valid_readiness_authorization_scope(readiness) is not None
    )


def _readiness_contract_blockers(
    readiness: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(readiness, Mapping):
        return [
            _blocker(
                "production_readiness_missing",
                "The canonical production-readiness artifact is unavailable.",
            )
        ]
    blockers: list[dict[str, Any]] = []
    if readiness.get("schema_version") != READINESS_SCHEMA_VERSION:
        blockers.append(
            _blocker(
                "production_readiness_schema_mismatch",
                "The production-readiness schema is missing or unsupported.",
            )
        )
    actual_hash = str(readiness.get("gate_sha256") or "")
    expected_hash = canonical_payload_sha256(
        readiness,
        omit=("gate_sha256",),
    )
    if not _SHA256_RE.fullmatch(actual_hash) or actual_hash != expected_hash:
        blockers.append(
            _blocker(
                "production_readiness_hash_mismatch",
                "The production-readiness self-hash does not verify.",
            )
        )
    permissions = readiness.get("capital_permissions")
    permissions = permissions if isinstance(permissions, Mapping) else {}
    if not (
        permissions.get("classification_only") is True
        and permissions.get("credential_access_permitted") is False
        and permissions.get("order_submission_permitted") is False
    ):
        blockers.append(
            _blocker(
                "production_readiness_authority_contract_mismatch",
                "Readiness must remain classification-only and grant no credential or order authority.",
            )
        )
    generated = _parse_utc(readiness.get("generated_at_utc"))
    age = _utc(now) - generated if generated is not None else None
    if (
        generated is None
        or age is None
        or age < -timedelta(seconds=5)
        or age > _MAX_READINESS_AGE
    ):
        blockers.append(
            _blocker(
                "production_readiness_stale",
                "The production-readiness decision is missing a current generated time.",
            )
        )
    if readiness.get("status") != "PASS":
        blockers.append(
            _blocker(
                "production_readiness_status_not_passed",
                "The production-readiness decision has not passed.",
            )
        )
    if (
        readiness.get("highest_permitted_stage") == _CAPITAL_STAGE
        and _valid_readiness_authorization_scope(readiness) is None
    ):
        blockers.append(
            _blocker(
                "production_readiness_capital_binding_invalid",
                "The CAPITAL_CANARY readiness decision lacks a verified authorization binding.",
            )
        )
    return blockers


def validate_activation(
    activation: Mapping[str, Any] | None,
    readiness: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    expected_platform: str | None = None,
    expected_account_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Validate exact reviewed scope without granting credential/order authority."""

    current = _utc(now)
    issues: list[dict[str, Any]] = []
    if not isinstance(readiness, Mapping) or not _readiness_capital_pass(
        readiness,
        now=current,
    ):
        issues.append(
            _blocker(
                "capital_readiness_not_passed",
                "The canonical production-readiness gate has not cleared CAPITAL_CANARY.",
            )
        )
    if not isinstance(activation, Mapping):
        issues.append(
            _blocker(
                "activation_missing",
                "No exact, reviewed, expiring capital-canary activation is available.",
            )
        )
        return issues

    secret_paths = sorted(set(_secret_paths(activation)))
    try:
        assert_secret_safe(activation)
    except SecretMaterialError:
        issues.append(
            _blocker(
                "activation_contains_secret_material",
                "Activation contains forbidden secret-like material.",
            )
        )
    if secret_paths:
        issues.append(
            _blocker(
                "activation_contains_secret_fields",
                "Activation must contain references and hashes only, never secret material.",
                fields=secret_paths,
            )
        )
    unknown_fields = sorted(set(map(str, activation)) - _ACTIVATION_FIELDS)
    if unknown_fields:
        issues.append(
            _blocker(
                "activation_unknown_fields",
                "Activation contains fields outside the exact reviewed schema.",
                fields=unknown_fields,
            )
        )
    if activation.get("schema_version") != ACTIVATION_SCHEMA_VERSION:
        issues.append(
            _blocker(
                "activation_schema_mismatch",
                "Activation schema is missing or unsupported.",
            )
        )
    expected_hash = activation_content_sha256(activation)
    if activation.get("activation_sha256") != expected_hash:
        issues.append(
            _blocker("activation_hash_mismatch", "Activation self-hash does not verify.")
        )

    readiness_scope = (
        _valid_readiness_authorization_scope(readiness)
        if isinstance(readiness, Mapping)
        else None
    )
    if readiness_scope is None:
        issues.append(
            _blocker(
                "activation_readiness_binding_invalid",
                "Readiness does not contain a verified capital-authorization scope binding.",
            )
        )
    elif dict(readiness_scope) != _activation_authorization_scope(activation):
        issues.append(
            _blocker(
                "activation_readiness_scope_mismatch",
                "Activation does not exactly match the capital scope reviewed by readiness.",
            )
        )

    for field in ("activation_id", "platform", "release_id", "reviewed_by"):
        value = activation.get(field)
        if (
            not isinstance(value, str)
            or value != value.strip()
            or not _SAFE_SCOPE_ID_RE.fullmatch(value)
        ):
            issues.append(
                _blocker(
                    f"activation_{field}_invalid",
                    f"Activation requires a bounded exact {field} identifier.",
                )
            )
    for field in ("manifest_sha256", "account_id_sha256"):
        value = str(activation.get(field) or "")
        if not _SHA256_RE.fullmatch(value):
            issues.append(
                _blocker(
                    f"activation_{field}_invalid",
                    f"Activation {field} must be a lowercase SHA-256 digest.",
                )
            )

    if expected_platform is None:
        issues.append(
            _blocker(
                "activation_platform_identity_unverified",
                "No verified exchange adapter identity is available for this activation.",
            )
        )
    elif activation.get("platform") != expected_platform:
        issues.append(
            _blocker(
                "activation_platform_mismatch",
                "Activation platform does not match the verified account adapter.",
            )
        )
    if expected_account_sha256 is None:
        issues.append(
            _blocker(
                "activation_account_identity_unverified",
                "No reconciled account identity is available for this activation.",
            )
        )
    elif activation.get("account_id_sha256") != expected_account_sha256:
        issues.append(
            _blocker(
                "activation_account_mismatch",
                "Activation account identity does not match the reconciled account.",
            )
        )

    release = readiness.get("release_identity") if isinstance(readiness, Mapping) else {}
    release = release if isinstance(release, Mapping) else {}
    if release.get("status") != "PASS" or release.get("production_capable") is not True:
        issues.append(
            _blocker(
                "active_release_not_production_capable",
                "The verified active release is unavailable or not production-capable.",
            )
        )
    if activation.get("release_id") != release.get("release_id"):
        issues.append(
            _blocker(
                "activation_release_mismatch",
                "Activation does not name the verified active release.",
            )
        )
    if activation.get("manifest_sha256") != release.get("manifest_sha256"):
        issues.append(
            _blocker(
                "activation_manifest_mismatch",
                "Activation does not bind the verified active release manifest.",
            )
        )

    if _exact_decimal(activation.get("capital_ceiling_usdc")) != (
        _DEFAULT_RISK_POLICY.campaign_capital_ceiling_usdc
    ):
        issues.append(
            _blocker(
                "activation_capital_ceiling_mismatch",
                "Activation must bind the immutable $75 lifetime funding ceiling.",
            )
        )
    if activation.get("risk_policy_id") != RISK_POLICY_ID:
        issues.append(
            _blocker(
                "activation_risk_policy_mismatch",
                "Activation does not bind the reviewed $75 risk policy.",
            )
        )
    if activation.get("risk_policy_sha256") != RISK_POLICY_SHA256:
        issues.append(
            _blocker(
                "activation_risk_policy_hash_mismatch",
                "Activation does not hash-bind the reviewed risk policy.",
            )
        )
    caps = activation.get("risk_caps")
    if not isinstance(caps, Mapping) or dict(caps) != RISK_CAPS:
        issues.append(
            _blocker(
                "activation_risk_caps_mismatch",
                "Activation risk caps must exactly match the reviewed policy version.",
            )
        )
    if activation.get("risk_caps_sha256") != RISK_CAPS_SHA256:
        issues.append(
            _blocker(
                "activation_risk_caps_hash_mismatch",
                "Activation risk-cap hash does not verify.",
            )
        )

    markets = activation.get("market_ids")
    if (
        not isinstance(markets, list)
        or not markets
        or any(
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or len(value) > 256
            for value in markets
        )
        or len(set(markets)) != len(markets)
    ):
        issues.append(
            _blocker(
                "activation_market_scope_invalid",
                "Activation must contain a non-empty unique exact market allowlist.",
            )
        )

    authorized = _parse_utc(activation.get("authorized_at_utc"))
    expires = _parse_utc(activation.get("expires_at_utc"))
    if authorized is None or authorized > current:
        issues.append(
            _blocker(
                "activation_authorized_at_invalid",
                "Activation authorization time is missing or in the future.",
            )
        )
    if expires is None or expires <= current:
        issues.append(
            _blocker(
                "activation_expired",
                "Activation expiry is missing or has passed.",
            )
        )
    return issues


def _readiness_blockers(
    readiness: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    contract_blockers = _readiness_contract_blockers(readiness, now=now)
    if not isinstance(readiness, Mapping):
        return contract_blockers
    if any(
        row["code"]
        in {
            "production_readiness_schema_mismatch",
            "production_readiness_hash_mismatch",
            "production_readiness_authority_contract_mismatch",
        }
        for row in contract_blockers
    ):
        return contract_blockers
    rows = readiness.get("blockers")
    if not isinstance(rows, list):
        rows = []
    sanitized: list[dict[str, Any]] = []
    for row in rows[:20]:
        if not isinstance(row, Mapping):
            continue
        candidate = {
            key: _public_text(row.get(key))
            for key in ("code", "detail", "stage", "input", "next_action")
            if row.get(key) not in (None, "")
        }
        try:
            assert_secret_safe(candidate)
        except SecretMaterialError:
            candidate = {
                "code": "production_readiness_detail_redacted",
                "detail": "A source blocker contained secret-like text and was omitted.",
            }
        sanitized.append(candidate)
    sanitized = contract_blockers + sanitized
    if not _readiness_capital_pass(readiness, now=now):
        sanitized.insert(
            0,
            _blocker(
                "capital_readiness_not_passed",
                "The highest permitted production stage is not CAPITAL_CANARY.",
                highest_permitted_stage=readiness.get("highest_permitted_stage")
                or readiness.get("stage")
                or "NOT_READY",
            ),
        )
    return sanitized


def _dedupe_blockers(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (
            str(row.get("code") or ""),
            str(row.get("detail") or ""),
            str(row.get("input") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(row))
    return result


def build_capital_locked_status(
    readiness: Mapping[str, Any] | None,
    activation: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
    readiness_path: str | Path | None = None,
    activation_path: str | Path | None = None,
    input_errors: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the capital-locked producer contract.

    Even perfect inputs cannot set ``order_submission_enabled`` in this
    implementation.  That invariant prevents a future data-file copy from
    silently turning fixture/read-only code into a capital worker.
    """

    current = _utc(now)
    readiness = readiness if isinstance(readiness, Mapping) else None
    activation = activation if isinstance(activation, Mapping) else None
    blockers = _readiness_blockers(readiness, now=current)
    activation_issues = validate_activation(activation, readiness, now=current)
    blockers.extend(activation_issues)
    for error in input_errors:
        blockers.append(
            _blocker("artifact_read_error", "A required artifact failed stable validation.", error=error)
        )
    blockers.append(
        _blocker(
            "authenticated_adapter_not_implemented",
            "The capital-locked build has no credential resolver or order adapter.",
        )
    )
    blockers = _dedupe_blockers(blockers)

    release = readiness.get("release_identity") if readiness else {}
    release = release if isinstance(release, Mapping) else {}
    capital_pass = bool(
        readiness and _readiness_capital_pass(readiness, now=current)
    )
    activation_active = not activation_issues
    activation_status = (
        "ACTIVE"
        if activation_active
        else "MISSING"
        if activation is None
        else "EXPIRED"
        if any(row.get("code") == "activation_expired" for row in activation_issues)
        else "BLOCKED"
    )
    platform = str(activation.get("platform") or "") if activation_active else ""
    account_hash = (
        str(activation.get("account_id_sha256") or "") if activation_active else ""
    )
    account_redacted = f"sha256:{account_hash[:12]}..." if account_hash else None
    generated = _utc_iso(current)
    payload: dict[str, Any] = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "generated_at_utc": generated,
        "sequence": 0,
        "status": "BLOCKED",
        "substate": "SETUP_REQUIRED",
        "status_message": (
            "Capital remains locked. Readiness, exact activation, account reconciliation, "
            "and an authenticated adapter must all pass before any order can exist."
        ),
        "read_only": True,
        "actionable": False,
        "positions_state_known": False,
        "portfolio_state_known": False,
        "bot": {
            "campaign_id": activation.get("activation_id") if activation_active else None,
            "state": "LOCKED" if not (capital_pass and activation_active) else "PREFLIGHT",
            "heartbeat_at_utc": None,
            "heartbeat_sequence": 0,
            "last_evaluation_at_utc": None,
            "last_order_event_at_utc": None,
            "next_evaluation_at_utc": None,
            "kill_switch_state": "ENGAGED",
            "process_health_status": "CAPITAL_LOCKED",
            "restart_mode": "RECONCILE_ONLY",
        },
        "authority": {
            "production_readiness_stage": (
                readiness.get("highest_permitted_stage")
                if readiness
                else "NOT_READY"
            ),
            "capital_gate_status": "PASS" if capital_pass else "BLOCK",
            "activation_status": activation_status,
            "order_submission_enabled": False,
            "credential_access_enabled": False,
            "release_id": release.get("release_id"),
            "manifest_sha256": release.get("manifest_sha256"),
            "platform": platform or None,
            "account_id_redacted": account_redacted,
            "authorized_markets": list(activation.get("market_ids") or [])
            if activation_active
            else [],
            "authorized_budget_usdc": CAPITAL_CEILING_USDC,
            "authorized_caps": dict(RISK_CAPS),
            "expires_at_utc": activation.get("expires_at_utc")
            if activation_active
            else None,
            "credential_reference_status": "NOT_READ",
        },
        "fund": {
            "accounting_status": "UNKNOWN",
            "starting_capital_usdc": CAPITAL_CEILING_USDC,
            "external_flows_usdc": None,
            "cash_available_usdc": None,
            "cash_reserved_usdc": None,
            "open_position_cost_usdc": None,
            "open_position_mark_value_usdc": None,
            "pending_redemption_usdc": None,
            "net_liquidation_value_usdc": None,
            "realized_settlement_pnl_usdc": None,
            "unrealized_executable_pnl_usdc": None,
            "fees_usdc": None,
            "total_pnl_usdc": None,
            "return_fraction": None,
            "peak_net_liquidation_value_usdc": None,
            "drawdown_usdc": None,
            "drawdown_fraction": None,
            "reconciliation_difference_usdc": None,
        },
        "risk": {
            "policy_id": RISK_POLICY_ID,
            "risk_policy_sha256": RISK_POLICY_SHA256,
            "risk_caps_sha256": RISK_CAPS_SHA256,
            "open_max_loss_usdc": None,
            "daily_loss_usdc": None,
            "per_order_cap_usdc": RISK_CAPS["alpha_order_max_loss_usdc"],
            "per_event_cap_usdc": RISK_CAPS["alpha_order_max_loss_usdc"],
            "correlated_exposure_cap_usdc": RISK_CAPS[
                "correlated_open_max_loss_usdc"
            ],
            "total_open_cap_usdc": RISK_CAPS["total_open_max_loss_usdc"],
            "daily_loss_halt_usdc": RISK_CAPS["daily_realized_loss_halt_usdc"],
            "lifetime_drawdown_halt_usdc": RISK_CAPS[
                "permanent_drawdown_halt_usdc"
            ],
            "cap_utilization": {},
            "breaches": [],
        },
        "targets": [],
        "positions": [],
        "recent_activity": [],
        "equity_curve": [],
        "performance": {
            "filled_orders": 0,
            "settled_orders": 0,
            "unsettled_orders": 0,
            "wins": 0,
            "losses": 0,
            "turnover_usdc": "0.00",
            "settled_roi": None,
            "expected_pnl_at_entry_usdc": None,
            "realized_minus_expected_usdc": None,
            "market_benchmark_pnl_usdc": None,
            "no_trade_benchmark_pnl_usdc": "0.00",
            "sample_status": "INSUFFICIENT",
        },
        "ledger_high_water": {"sequence": 0, "record_hash": GENESIS_HASH},
        "blockers": blockers,
        "warnings": [
            "No credential resolver was invoked and no exchange request was made.",
            "Unknown account values are intentionally null, not zero.",
        ],
        "provenance": {
            "readiness_path": _public_artifact_path(readiness_path)
            if readiness_path
            else None,
            "readiness_gate_sha256": readiness.get("gate_sha256")
            if readiness
            else None,
            "activation_path": _public_artifact_path(activation_path)
            if activation_path and activation is not None
            else None,
            "activation_sha256": activation.get("activation_sha256")
            if activation is not None
            else None,
            "capital_lock_contract": "credentials_and_orders_absent_by_construction",
            "risk_policy_id": RISK_POLICY_ID,
            "risk_policy_sha256": RISK_POLICY_SHA256,
            "risk_caps_sha256": RISK_CAPS_SHA256,
        },
    }
    payload["status_sha256"] = status_content_sha256(payload)
    assert_secret_safe(payload)
    return payload


def load_and_build_capital_locked_status(
    *,
    readiness_path: str | Path = DEFAULT_READINESS_PATH,
    activation_path: str | Path = DEFAULT_ACTIVATION_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    readiness, readiness_error = _read_stable_mapping(readiness_path)
    activation, activation_error = _read_stable_mapping(activation_path)
    input_errors = []
    if readiness_error:
        input_errors.append(f"readiness:{readiness_error}")
    if activation_error not in (None, "missing"):
        input_errors.append(f"activation:{activation_error}")
    return build_capital_locked_status(
        readiness,
        activation,
        now=now,
        readiness_path=readiness_path,
        activation_path=activation_path,
        input_errors=input_errors,
    )


def write_capital_locked_status(
    *,
    status_path: str | Path = DEFAULT_STATUS_PATH,
    readiness_path: str | Path = DEFAULT_READINESS_PATH,
    activation_path: str | Path = DEFAULT_ACTIVATION_PATH,
    now: datetime | None = None,
) -> tuple[dict[str, Any], Path]:
    if _is_env_like_path(status_path):
        raise ValueError("refusing to write capital-canary status to an env file")
    if Path(status_path).is_symlink():
        raise ValueError("refusing to replace a symlink status path")
    payload = load_and_build_capital_locked_status(
        readiness_path=readiness_path,
        activation_path=activation_path,
        now=now,
    )
    path = write_json_atomic(status_path, payload, trailing_newline=True)
    return payload, path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or materialize the capital-locked $75 canary status. "
            "This command cannot resolve credentials or place orders."
        )
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("status", "initialize", "preflight"),
        default="status",
    )
    parser.add_argument("--readiness", default=str(DEFAULT_READINESS_PATH))
    parser.add_argument("--activation", default=str(DEFAULT_ACTIVATION_PATH))
    parser.add_argument("--status-out", default=str(DEFAULT_STATUS_PATH))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "initialize":
        payload, output = write_capital_locked_status(
            status_path=args.status_out,
            readiness_path=args.readiness,
            activation_path=args.activation,
        )
        response = {
            "status": payload["status"],
            "bot_state": payload["bot"]["state"],
            "order_submission_enabled": False,
            "status_path": str(output),
        }
    else:
        payload = load_and_build_capital_locked_status(
            readiness_path=args.readiness,
            activation_path=args.activation,
        )
        response = payload
    print(json.dumps(response, indent=2, sort_keys=True))
    if args.command == "preflight" and not payload["authority"][
        "order_submission_enabled"
    ]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACTIVATION_SCHEMA_VERSION",
    "CAPITAL_CEILING_USDC",
    "DEFAULT_ACTIVATION_PATH",
    "DEFAULT_READINESS_PATH",
    "DEFAULT_ROOT",
    "DEFAULT_STATUS_PATH",
    "RISK_CAPS",
    "RISK_CAPS_SHA256",
    "RISK_POLICY_ID",
    "RISK_POLICY_SHA256",
    "READINESS_SCHEMA_VERSION",
    "STATUS_SCHEMA_VERSION",
    "activation_content_sha256",
    "build_capital_locked_status",
    "load_and_build_capital_locked_status",
    "main",
    "validate_activation",
    "write_capital_locked_status",
]
