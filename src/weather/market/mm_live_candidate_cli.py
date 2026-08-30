"""Select a fresh public market for the bounded International lifecycle probe.

This command performs no authentication and cannot place or cancel orders. It
binds a current validated economics snapshot and a still-current successful
paper-only market-harvest quote to current public CLOB books, then chooses the
exact built-in weather token whose one-tick minimum-size BUY is nonmarketable
and within the adapter's single-order cap.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from weather.market.exchange_economics import (
    CURRENT_EVIDENCE_BASIS,
    DRIFT_SCHEMA_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    build_drift_report,
    load_exchange_economics_gate,
    snapshot_hash,
    snapshot_id,
)
from weather.market.market_config import ensure_date
from weather.market.market_microstructure_capture import ClobClient
from weather.market.market_registry import BUILTIN_SPECS
from weather.market.mm_policy import utc_now
from weather.operations.live_path_security import (
    assert_no_ambient_market_registry_override,
    validate_nonreparse_directory,
    validate_regular_nonreparse_file,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_live_market_candidate_plan")
RUN_SCHEMA_VERSION = schema_version("mm_run")
QUOTE_SCHEMA_VERSION = schema_version("mm_quote_intent")
PLATFORM = "polymarket_global"
SETTLEMENT_UNIT = "pUSD"
MAX_SINGLE_ORDER_NOTIONAL = Decimal("10")
MIN_MIDPOINT = Decimal("0.20")
MAX_MIDPOINT = Decimal("0.80")
MAX_BOOK_SPREAD = Decimal("0.05")
MAX_ALTERNATES = 5
MAX_PLAN_AGE_SECONDS = 300
MAX_PAPER_QUOTE_TTL_SECONDS = 600
MAX_SUBSTRATE_PREFLIGHT_AGE_SECONDS = 600
MAX_OPERATOR_PILOT_BUDGET_PUSD = Decimal("100")
MAX_DAILY_LOSS_PUSD = Decimal("25")
MAX_EVENT_NOTIONAL_PUSD = Decimal("25")
MAX_BAND_NOTIONAL_PUSD = Decimal("10")
MAX_PAPER_QUOTE_SIZE = Decimal("5")
PAPER_PROFILE = "market_harvest"
SUBSTRATE_PREFLIGHT_SCHEMA_VERSION = schema_version(
    "portable_live_candidate_substrate_preflight"
)
ECONOMICS_ACCEPTANCE_ACKNOWLEDGMENT_PREFIX = (
    "I_ACCEPT_REVIEWED_INTERNATIONAL_ECONOMICS_BASELINE"
)
ECONOMICS_ACCEPTANCE_KEYS = {
    "accepted_at_utc",
    "accepted_snapshot_file_sha256",
    "accepted_snapshot_id",
    "accepted_snapshot_sha256",
    "drift_generated_at_utc",
    "drift_report_file_sha256",
    "drift_status",
    "operator_acknowledgment",
    "operator_acknowledgment_matches_candidate",
    "required_operator_acknowledgment",
    "rescore_required",
}
ACCEPTED_GATE_KEYS = {
    "status",
    "evidence_basis",
    "snapshot_id",
    "snapshot_hash",
    "source_hash",
    "verified_at_utc",
    "verified_for_target_date",
    "payout_asset_conflict_acknowledged",
}
DRIFT_REPORT_KEYS = {
    "schema_version",
    "generated_at_utc",
    "status",
    "target_date",
    "platform",
    "snapshot_path",
    "accepted_snapshot_path",
    "current_gate",
    "current_snapshot_id",
    "current_snapshot_hash",
    "accepted_snapshot_id",
    "accepted_snapshot_hash",
    "accepted_snapshot_present",
    "material_change_count",
    "material_changes",
    "rescore_required",
    "blockers",
}
SUBSTRATE_PREFLIGHT_ARTIFACT_KEYS = {
    "event_metadata",
    "event_metadata_validation",
    "observation_status",
    "economics_snapshot",
    "accepted_economics_snapshot",
    "economics_drift_report",
    "paper_run_config",
    "paper_preflight",
    "paper_quote_intents",
    "clob_tokens",
    "order_books_summary",
    "source_status_long",
}
SUBSTRATE_PREFLIGHT_KEYS = {
    "schema_version",
    "status",
    "checked_at_utc",
    "market_id",
    "target_date",
    "event_slug",
    "snapshots_root",
    "event_folder",
    "checks",
    "blockers",
    "missing_paths",
    "artifact_paths",
    "artifact_sha256",
    "validation_hash",
    "economics_snapshot_id",
    "economics_snapshot_sha256",
    "accepted_snapshot_file_sha256",
    "economics_drift_report_file_sha256",
    "paper_quote_intents_sha256",
    "paper_quote_intents_row_count",
    "credential_access",
    "exchange_contact",
    "exchange_mutation",
    "network_access",
}
SUBSTRATE_BINDING_KEYS = {
    "schema_version",
    "receipt_sha256",
    "checked_at_utc",
    "expires_at_utc",
    "market_id",
    "target_date",
    "event_slug",
    "validation_hash",
    "event_metadata_file_sha256",
    "event_metadata_validation_file_sha256",
    "observation_status_file_sha256",
    "economics_snapshot_file_sha256",
    "accepted_snapshot_file_sha256",
    "economics_drift_report_file_sha256",
    "paper_run_config_file_sha256",
    "paper_preflight_file_sha256",
    "paper_quote_intents_file_sha256",
    "clob_tokens_file_sha256",
    "order_books_summary_file_sha256",
    "source_status_long_file_sha256",
    "network_access",
    "credential_access",
    "exchange_contact",
    "exchange_mutation",
}


def _canonical_sha256(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_plan_sha256(payload):
    return _canonical_sha256({
        key: value for key, value in dict(payload or {}).items()
        if key != "plan_sha256"
    })


def _decimal(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _bool_value(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _parse_utc(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("paper quote evidence has an invalid UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("paper quote evidence timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_json_object(path, *, label):
    source = validate_regular_nonreparse_file(path)
    try:
        raw = source.read_bytes()
        payload = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not readable JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return source, payload, raw


def _reject_duplicate_pairs(pairs):
    payload = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def _write_new_json(path: Path, payload: dict) -> None:
    """Create one immutable plan without an absence-check/replace race."""

    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def validate_candidate_substrate_binding(
    value,
    *,
    target_date,
    market_id,
    created_at,
    now=None,
):
    """Validate the immutable public-substrate receipt summary in a candidate."""

    binding = dict(value) if isinstance(value, dict) else {}
    current = utc_now(now)
    try:
        checked = _parse_utc(binding.get("checked_at_utc"))
        expires = _parse_utc(binding.get("expires_at_utc"))
        created = _parse_utc(created_at)
    except RuntimeError as exc:
        raise RuntimeError("candidate substrate binding has invalid timestamps") from exc
    hash_fields = {
        "receipt_sha256",
        "validation_hash",
        "event_metadata_file_sha256",
        "event_metadata_validation_file_sha256",
        "observation_status_file_sha256",
        "economics_snapshot_file_sha256",
        "accepted_snapshot_file_sha256",
        "economics_drift_report_file_sha256",
        "paper_run_config_file_sha256",
        "paper_preflight_file_sha256",
        "paper_quote_intents_file_sha256",
        "clob_tokens_file_sha256",
        "order_books_summary_file_sha256",
        "source_status_long_file_sha256",
    }
    checks = {
        "shape": set(binding) == SUBSTRATE_BINDING_KEYS,
        "schema": (
            binding.get("schema_version") == SUBSTRATE_PREFLIGHT_SCHEMA_VERSION
        ),
        "scope": (
            binding.get("target_date") == ensure_date(target_date).isoformat()
            and binding.get("market_id") == market_id
            and isinstance(binding.get("event_slug"), str)
            and bool(binding.get("event_slug", "").strip())
        ),
        "hashes": all(_is_sha256(binding.get(field)) for field in hash_fields),
        "timing": (
            checked <= created <= current < expires
            and expires
            == checked + timedelta(seconds=MAX_SUBSTRATE_PREFLIGHT_AGE_SECONDS)
        ),
        "non_authorizing": all(
            binding.get(field) is False
            for field in (
                "network_access",
                "credential_access",
                "exchange_contact",
                "exchange_mutation",
            )
        ),
    }
    missing = sorted(name for name, passed in checks.items() if not passed)
    if missing:
        raise RuntimeError(
            "candidate substrate binding gate failed: " + ", ".join(missing)
        )
    return {
        **binding,
        "checked_at_utc": checked.isoformat(),
        "expires_at_utc": expires.isoformat(),
    }


def _load_substrate_preflight_receipt(
    path,
    *,
    target_date,
    economics_snapshot,
    accepted_economics_snapshot,
    economics_drift_report,
    paper_run_config,
    paper_quote_intents,
    now,
):
    """Validate and summarize the exact no-network public-substrate receipt."""

    source, payload, raw = _read_json_object(
        path,
        label="candidate substrate preflight",
    )
    artifacts_value = payload.get("artifact_sha256")
    artifacts = dict(artifacts_value) if isinstance(artifacts_value, dict) else {}
    artifact_paths_value = payload.get("artifact_paths")
    artifact_paths = (
        dict(artifact_paths_value)
        if isinstance(artifact_paths_value, dict)
        else {}
    )
    checks_value = payload.get("checks")
    preflight_checks = dict(checks_value) if isinstance(checks_value, dict) else {}
    checked = _parse_utc(payload.get("checked_at_utc"))
    current = utc_now(now)
    target = ensure_date(target_date).isoformat()
    market_id = str(payload.get("market_id") or "")
    expected_files = {
        "economics_snapshot": validate_regular_nonreparse_file(economics_snapshot),
        "accepted_economics_snapshot": validate_regular_nonreparse_file(
            accepted_economics_snapshot
        ),
        "economics_drift_report": validate_regular_nonreparse_file(
            economics_drift_report
        ),
        "paper_run_config": validate_regular_nonreparse_file(paper_run_config),
        "paper_quote_intents": validate_regular_nonreparse_file(
            paper_quote_intents
        ),
    }
    try:
        if set(artifact_paths) != SUBSTRATE_PREFLIGHT_ARTIFACT_KEYS:
            raise RuntimeError("artifact path shape changed")
        validated_artifact_paths = {
            name: validate_regular_nonreparse_file(artifact_path)
            for name, artifact_path in artifact_paths.items()
        }
        snapshots_root = validate_nonreparse_directory(payload.get("snapshots_root"))
        event_folder = validate_nonreparse_directory(payload.get("event_folder"))
    except Exception as exc:
        raise RuntimeError(
            "candidate substrate preflight artifact paths are invalid"
        ) from exc
    distinct_evidence_paths = {os.path.normcase(str(source))}
    distinct_evidence_paths.update(
        os.path.normcase(str(artifact_path))
        for artifact_path in validated_artifact_paths.values()
    )
    receipt_checks = {
        "shape": set(payload) == SUBSTRATE_PREFLIGHT_KEYS,
        "schema": payload.get("schema_version") == SUBSTRATE_PREFLIGHT_SCHEMA_VERSION,
        "status": payload.get("status") == "PASS",
        "scope": (
            payload.get("target_date") == target
            and market_id in {spec.id for spec in BUILTIN_SPECS}
            and isinstance(payload.get("event_slug"), str)
            and bool(payload.get("event_slug", "").strip())
        ),
        "fresh": (
            checked <= current
            and (current - checked).total_seconds()
            <= MAX_SUBSTRATE_PREFLIGHT_AGE_SECONDS
        ),
        "checks": bool(preflight_checks)
        and all(value is True for value in preflight_checks.values()),
        "clear": payload.get("blockers") == [] and payload.get("missing_paths") == [],
        "artifact_shape": set(artifacts) == SUBSTRATE_PREFLIGHT_ARTIFACT_KEYS
        and all(_is_sha256(value) for value in artifacts.values()),
        "artifact_paths": (
            len(distinct_evidence_paths)
            == len(SUBSTRATE_PREFLIGHT_ARTIFACT_KEYS) + 1
            and event_folder.parent == snapshots_root
            and event_folder.name == payload.get("event_slug")
            and validated_artifact_paths.get("clob_tokens")
            == event_folder / "clob_tokens.csv"
            and validated_artifact_paths.get("order_books_summary")
            == event_folder / "order_books_summary.csv"
            and validated_artifact_paths.get("source_status_long")
            == event_folder / "source_status_long.csv"
            and all(
                validated_artifact_paths.get(name) == file_path
                for name, file_path in expected_files.items()
            )
        ),
        "input_hashes": all(
            artifacts.get(name) == hashlib.sha256(file_path.read_bytes()).hexdigest()
            for name, file_path in validated_artifact_paths.items()
        ),
        "reported_hashes": (
            payload.get("accepted_snapshot_file_sha256")
            == artifacts.get("accepted_economics_snapshot")
            and payload.get("economics_drift_report_file_sha256")
            == artifacts.get("economics_drift_report")
            and payload.get("paper_quote_intents_sha256")
            == artifacts.get("paper_quote_intents")
            and _is_sha256(payload.get("validation_hash"))
        ),
        "non_authorizing": all(
            payload.get(field) is False
            for field in (
                "network_access",
                "credential_access",
                "exchange_contact",
                "exchange_mutation",
            )
        ),
        "stable": source.read_bytes() == raw,
    }
    missing = sorted(name for name, passed in receipt_checks.items() if not passed)
    if missing:
        raise RuntimeError(
            "candidate substrate preflight gate failed: " + ", ".join(missing)
        )
    binding = {
        "schema_version": SUBSTRATE_PREFLIGHT_SCHEMA_VERSION,
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "checked_at_utc": checked.isoformat(),
        "expires_at_utc": (
            checked + timedelta(seconds=MAX_SUBSTRATE_PREFLIGHT_AGE_SECONDS)
        ).isoformat(),
        "market_id": market_id,
        "target_date": target,
        "event_slug": payload["event_slug"],
        "validation_hash": payload["validation_hash"],
        "event_metadata_file_sha256": artifacts["event_metadata"],
        "event_metadata_validation_file_sha256": artifacts[
            "event_metadata_validation"
        ],
        "observation_status_file_sha256": artifacts["observation_status"],
        "economics_snapshot_file_sha256": artifacts["economics_snapshot"],
        "accepted_snapshot_file_sha256": artifacts[
            "accepted_economics_snapshot"
        ],
        "economics_drift_report_file_sha256": artifacts[
            "economics_drift_report"
        ],
        "paper_run_config_file_sha256": artifacts["paper_run_config"],
        "paper_preflight_file_sha256": artifacts["paper_preflight"],
        "paper_quote_intents_file_sha256": artifacts["paper_quote_intents"],
        "clob_tokens_file_sha256": artifacts["clob_tokens"],
        "order_books_summary_file_sha256": artifacts["order_books_summary"],
        "source_status_long_file_sha256": artifacts["source_status_long"],
        "network_access": False,
        "credential_access": False,
        "exchange_contact": False,
        "exchange_mutation": False,
    }
    return validate_candidate_substrate_binding(
        binding,
        target_date=target,
        market_id=market_id,
        created_at=current.isoformat(),
        now=current,
    )


def economics_acceptance_acknowledgment(
    target_date,
    condition_id,
    token_id,
    *,
    accepted_snapshot_file_sha256,
    drift_report_file_sha256,
):
    """Return the exact informed-acceptance literal for one candidate and date."""

    target = ensure_date(target_date).isoformat()
    condition = str(condition_id or "").lower()
    token = str(token_id or "")
    if not (
        len(condition) == 66
        and condition.startswith("0x")
        and all(character in "0123456789abcdef" for character in condition[2:])
        and token
        and token[0] in "123456789"
        and all(character in "0123456789" for character in token)
        and _is_sha256(accepted_snapshot_file_sha256)
        and _is_sha256(drift_report_file_sha256)
    ):
        raise RuntimeError("economics acceptance scope or evidence hash is invalid")
    return "|".join(
        (
            ECONOMICS_ACCEPTANCE_ACKNOWLEDGMENT_PREFIX,
            target,
            condition,
            token,
            str(accepted_snapshot_file_sha256),
            str(drift_report_file_sha256),
        )
    )


def load_economics_acceptance_evidence(
    economics_snapshot,
    accepted_economics_snapshot,
    economics_drift_report,
    target_date,
    *,
    now=None,
):
    """Validate an exact human-accepted baseline and its current no-drift proof."""

    target = ensure_date(target_date).isoformat()
    current_path, current, current_raw = _read_json_object(
        economics_snapshot,
        label="current economics snapshot",
    )
    accepted_path, accepted, accepted_raw = _read_json_object(
        accepted_economics_snapshot,
        label="accepted economics snapshot",
    )
    drift_path, drift, drift_raw = _read_json_object(
        economics_drift_report,
        label="economics drift report",
    )
    current_gate = load_exchange_economics_gate(
        current_path,
        target,
        platform=PLATFORM,
        now=now,
        max_age_hours=2,
    )
    accepted_gate = load_exchange_economics_gate(
        accepted_path,
        target,
        platform=PLATFORM,
        now=now,
        max_age_hours=2,
    )
    acceptance_gate = accepted.get("accepted_gate")
    if not isinstance(acceptance_gate, dict):
        raise RuntimeError("accepted economics snapshot has no acceptance gate")
    try:
        accepted_at = _parse_utc(accepted.get("accepted_at_utc"))
        drift_generated = _parse_utc(drift.get("generated_at_utc"))
    except RuntimeError as exc:
        raise RuntimeError("economics acceptance timestamps are invalid") from exc
    current_time = utc_now(now)
    accepted_hash = snapshot_hash(accepted)
    accepted_identifier = snapshot_id(accepted)
    current_hash = snapshot_hash(current)
    current_identifier = snapshot_id(current)
    recomputed = build_drift_report(
        current_path,
        accepted_path,
        target_date=target,
        platform=PLATFORM,
        now=now,
        max_age_hours=2,
    )
    try:
        report_snapshot_path_matches = (
            Path(str(drift.get("snapshot_path") or "")).resolve() == current_path
        )
        report_accepted_path_matches = (
            Path(str(drift.get("accepted_snapshot_path") or "")).resolve()
            == accepted_path
        )
    except (OSError, RuntimeError, ValueError):
        report_snapshot_path_matches = report_accepted_path_matches = False
    checks = {
        "current_gate": current_gate.get("ok") is True,
        "accepted_current_gate": accepted_gate.get("ok") is True,
        "accepted_schema": accepted.get("schema_version") == SNAPSHOT_SCHEMA_VERSION,
        "accepted_gate_shape": set(acceptance_gate) == ACCEPTED_GATE_KEYS,
        "accepted_gate_pass": (
            acceptance_gate.get("status") == "PASS"
            and acceptance_gate.get("evidence_basis") == CURRENT_EVIDENCE_BASIS
        ),
        "accepted_gate_identity": (
            acceptance_gate.get("snapshot_id") == accepted_identifier
            and acceptance_gate.get("snapshot_hash") == accepted_hash
            and acceptance_gate.get("source_hash") == accepted.get("source_hash")
            and acceptance_gate.get("verified_at_utc")
            == accepted.get("verified_at_utc")
            and acceptance_gate.get("verified_for_target_date")
            == accepted.get("verified_for_target_date")
        ),
        "accepted_conflict_acknowledgment": (
            isinstance(
                acceptance_gate.get("payout_asset_conflict_acknowledged"), bool
            )
            and (
                (accepted.get("maker_rebate") or {}).get(
                    "documentation_asset_terms_conflict"
                )
                is not True
                or acceptance_gate.get("payout_asset_conflict_acknowledged") is True
            )
        ),
        "accepted_timestamp": accepted_at <= current_time,
        "drift_timestamp": accepted_at <= drift_generated <= current_time,
        "drift_shape": set(drift) == DRIFT_REPORT_KEYS,
        "drift_schema": drift.get("schema_version") == DRIFT_SCHEMA_VERSION,
        "drift_scope": (
            drift.get("target_date") == target
            and drift.get("platform") == PLATFORM
            and report_snapshot_path_matches
            and report_accepted_path_matches
        ),
        "drift_pass": (
            drift.get("status") == "PASS"
            and drift.get("rescore_required") is False
            and drift.get("accepted_snapshot_present") is True
            and type(drift.get("material_change_count")) is int
            and drift.get("material_change_count") == 0
            and drift.get("material_changes") == []
            and drift.get("blockers") == []
        ),
        "drift_identity": (
            drift.get("current_snapshot_id") == current_identifier
            and drift.get("current_snapshot_hash") == current_hash
            and drift.get("accepted_snapshot_id") == accepted_identifier
            and drift.get("accepted_snapshot_hash") == accepted_hash
            and current_identifier == accepted_identifier
            and current_hash == accepted_hash
        ),
        "drift_current_gate": (
            isinstance(drift.get("current_gate"), dict)
            and drift["current_gate"].get("ok") is True
            and drift["current_gate"].get("status") == "PASS"
            and drift["current_gate"].get("missing") == []
            and drift["current_gate"].get("snapshot_id") == current_identifier
            and drift["current_gate"].get("snapshot_hash") == current_hash
        ),
        "recomputed_drift": (
            recomputed.get("status") == "PASS"
            and recomputed.get("rescore_required") is False
            and recomputed.get("material_change_count") == 0
            and recomputed.get("material_changes") == []
            and recomputed.get("blockers") == []
            and recomputed.get("current_snapshot_id") == current_identifier
            and recomputed.get("accepted_snapshot_id") == accepted_identifier
            and recomputed.get("current_snapshot_hash") == current_hash
            and recomputed.get("accepted_snapshot_hash") == accepted_hash
        ),
        "current_stable": current_path.read_bytes() == current_raw,
        "accepted_stable": accepted_path.read_bytes() == accepted_raw,
        "drift_stable": drift_path.read_bytes() == drift_raw,
    }
    missing = sorted(name for name, passed in checks.items() if not passed)
    if missing:
        raise RuntimeError(
            "economics baseline acceptance gate failed: " + ", ".join(missing)
        )
    return {
        "accepted_at_utc": accepted_at.isoformat(),
        "accepted_snapshot_file_sha256": hashlib.sha256(accepted_raw).hexdigest(),
        "accepted_snapshot_id": accepted_identifier,
        "accepted_snapshot_sha256": accepted_hash,
        "drift_generated_at_utc": drift_generated.isoformat(),
        "drift_report_file_sha256": hashlib.sha256(drift_raw).hexdigest(),
        "drift_status": "PASS",
        "rescore_required": False,
    }


def validate_bound_economics_acceptance_files(
    accepted_economics_snapshot,
    economics_drift_report,
    binding,
    *,
    target_date,
    current_snapshot_id,
    current_snapshot_sha256,
):
    """Revalidate staged acceptance files against one candidate-plan binding."""

    accepted_path, accepted, accepted_raw = _read_json_object(
        accepted_economics_snapshot,
        label="bound accepted economics snapshot",
    )
    drift_path, drift, drift_raw = _read_json_object(
        economics_drift_report,
        label="bound economics drift report",
    )
    acceptance_gate = accepted.get("accepted_gate")
    candidate_binding = dict(binding) if isinstance(binding, dict) else {}
    target = ensure_date(target_date).isoformat()
    accepted_hash = snapshot_hash(accepted)
    accepted_identifier = snapshot_id(accepted)
    checks = {
        "binding_shape": set(candidate_binding) == ECONOMICS_ACCEPTANCE_KEYS,
        "accepted_schema": accepted.get("schema_version") == SNAPSHOT_SCHEMA_VERSION,
        "accepted_gate_shape": (
            isinstance(acceptance_gate, dict)
            and set(acceptance_gate) == ACCEPTED_GATE_KEYS
        ),
        "accepted_gate": (
            isinstance(acceptance_gate, dict)
            and acceptance_gate.get("status") == "PASS"
            and acceptance_gate.get("evidence_basis") == CURRENT_EVIDENCE_BASIS
            and acceptance_gate.get("snapshot_id") == accepted_identifier
            and acceptance_gate.get("snapshot_hash") == accepted_hash
            and acceptance_gate.get("source_hash") == accepted.get("source_hash")
        ),
        "accepted_conflict_acknowledgment": (
            isinstance(acceptance_gate, dict)
            and isinstance(
                acceptance_gate.get("payout_asset_conflict_acknowledged"), bool
            )
            and (
                (accepted.get("maker_rebate") or {}).get(
                    "documentation_asset_terms_conflict"
                )
                is not True
                or acceptance_gate.get("payout_asset_conflict_acknowledged") is True
            )
        ),
        "accepted_file": (
            candidate_binding.get("accepted_snapshot_file_sha256")
            == hashlib.sha256(accepted_raw).hexdigest()
            and candidate_binding.get("accepted_snapshot_id")
            == accepted_identifier
            == current_snapshot_id
            and candidate_binding.get("accepted_snapshot_sha256")
            == accepted_hash
            == current_snapshot_sha256
            and candidate_binding.get("accepted_at_utc")
            == str(accepted.get("accepted_at_utc"))
        ),
        "drift_file": (
            candidate_binding.get("drift_report_file_sha256")
            == hashlib.sha256(drift_raw).hexdigest()
            and candidate_binding.get("drift_generated_at_utc")
            == str(drift.get("generated_at_utc"))
        ),
        "drift_shape": set(drift) == DRIFT_REPORT_KEYS,
        "drift_pass": (
            drift.get("schema_version") == DRIFT_SCHEMA_VERSION
            and drift.get("status") == candidate_binding.get("drift_status") == "PASS"
            and drift.get("target_date") == target
            and drift.get("platform") == PLATFORM
            and drift.get("rescore_required")
            is candidate_binding.get("rescore_required")
            is False
            and drift.get("accepted_snapshot_present") is True
            and drift.get("material_change_count") == 0
            and drift.get("material_changes") == []
            and drift.get("blockers") == []
        ),
        "drift_identity": (
            drift.get("current_snapshot_id") == current_snapshot_id
            and drift.get("current_snapshot_hash") == current_snapshot_sha256
            and drift.get("accepted_snapshot_id") == accepted_identifier
            and drift.get("accepted_snapshot_hash") == accepted_hash
        ),
        "accepted_stable": accepted_path.read_bytes() == accepted_raw,
        "drift_stable": drift_path.read_bytes() == drift_raw,
    }
    missing = sorted(name for name, passed in checks.items() if not passed)
    if missing:
        raise RuntimeError(
            "bound economics acceptance files failed: " + ", ".join(missing)
        )
    return dict(candidate_binding)


def _scan_hashed_csv(path, visitor):
    digest = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    row_count = 0
    with Path(path).open("rb") as handle:
        def decoded_lines():
            for raw_line in handle:
                digest.update(raw_line)
                yield decoder.decode(raw_line)
            tail = decoder.decode(b"", final=True)
            if tail:
                yield tail

        for row in csv.DictReader(decoded_lines()):
            row_count += 1
            visitor(row)
    return row_count, digest.hexdigest()


def _load_paper_quote_evidence(
    run_config_path,
    quote_intents_path,
    *,
    target_date,
    economics_snapshot_id,
    economics_hash,
    now,
):
    config_raw = Path(run_config_path).read_bytes()
    try:
        config = json.loads(config_raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("paper run config is invalid JSON") from exc
    if not isinstance(config, dict):
        raise RuntimeError("paper run config must be a JSON object")
    policy = dict(config.get("policy_config") or {})
    shadow = dict(config.get("shadow_safety") or {})
    markets = list(config.get("markets") or [])
    budget = _decimal(config.get("budget_usdc"))
    policy_limits = {
        "quote_size": MAX_PAPER_QUOTE_SIZE,
        "quote_ttl_seconds": MAX_PAPER_QUOTE_TTL_SECONDS,
        "max_daily_loss": MAX_DAILY_LOSS_PUSD,
        "max_event_notional": MAX_EVENT_NOTIONAL_PUSD,
        "max_band_notional": MAX_BAND_NOTIONAL_PUSD,
    }
    config_checks = {
        "schema": config.get("schema_version") == RUN_SCHEMA_VERSION,
        "profile": config.get("permission_profile") == PAPER_PROFILE,
        "paper_mode": config.get("mode") == "paper-live-forward",
        "target_date": config.get("target_date") == target_date,
        "one_market": len(markets) == 1 and markets[0] in {spec.id for spec in BUILTIN_SPECS},
        "budget": budget is not None and Decimal("0") < budget <= MAX_OPERATOR_PILOT_BUDGET_PUSD,
        "live_mutation_disabled": shadow.get("live_trade_permission_allowed") is False,
        "private_keys_disabled": shadow.get("loads_private_keys") is False,
        "order_posting_disabled": shadow.get("posts_orders") is False,
        "economics_snapshot": config.get("exchange_economics_snapshot_id") == economics_snapshot_id,
        "economics_hash": config.get("exchange_economics_hash") == economics_hash,
    }
    for name, ceiling in policy_limits.items():
        value = _decimal(policy.get(name))
        config_checks[f"policy_{name}"] = (
            value is not None and Decimal("0") < value <= Decimal(str(ceiling))
        )
    missing_config = [name for name, valid in config_checks.items() if not valid]
    if missing_config:
        raise RuntimeError(
            "paper run config does not satisfy the live-pilot proof contract: "
            + ", ".join(missing_config)
        )

    current = utc_now(now)
    qualifying = {}

    def consider(row):
        generated = None
        try:
            generated = _parse_utc(row.get("generated_at_utc"))
        except RuntimeError:
            pass
        ttl = _decimal(row.get("quote_ttl_seconds"))
        bid = _decimal(row.get("bid_price"))
        ask = _decimal(row.get("ask_price"))
        bid_size = _decimal(row.get("bid_size"))
        ask_size = _decimal(row.get("ask_size"))
        quote_risk = _decimal(row.get("quote_risk_usdc"))
        row_budget = _decimal(row.get("run_budget_usdc"))
        expected_quote_risk = (
            (
                bid * bid_size + (Decimal("1") - ask) * ask_size
            ).quantize(Decimal("0.000001"))
            if all(value is not None for value in (bid, bid_size, ask, ask_size))
            else None
        )
        token = str(row.get("clob_token_id") or "")
        condition = str(row.get("condition_id") or "").lower()
        row_checks = all((
            generated is not None,
            row.get("schema_version") == QUOTE_SCHEMA_VERSION,
            ttl is not None and Decimal("0") < ttl <= MAX_PAPER_QUOTE_TTL_SECONDS,
            generated is not None and generated <= current <= generated + timedelta(seconds=float(ttl or 0)),
            row.get("run_id") == config.get("run_id"),
            row.get("target_date") == target_date,
            row.get("run_mode") == "paper-live-forward",
            row.get("preflight_status") == "PASS",
            row.get("market_id") == markets[0],
            row.get("known_edge_permission") == PAPER_PROFILE,
            row.get("model_variant_probability_source") == "market_mid_no_model",
            _bool_value(row.get("shadow_mode")),
            _bool_value(row.get("quote_permission")),
            not _bool_value(row.get("live_trade_permission")),
            row.get("action") == "QUOTE",
            str(row.get("side") or "").upper() == "TWO_SIDED",
            row.get("budget_action") == "reserved",
            row.get("exchange_economics_snapshot_id") == economics_snapshot_id,
            row.get("exchange_economics_hash") == economics_hash,
            row.get("policy_hash") == config.get("policy_hash"),
            token.isdigit() and int(token) > 0,
            len(condition) == 66 and condition.startswith("0x")
            and all(character in "0123456789abcdef" for character in condition[2:]),
            bid is not None and ask is not None and Decimal("0") < bid < ask < Decimal("1"),
            bid_size is not None and Decimal("0") < bid_size <= MAX_PAPER_QUOTE_SIZE,
            ask_size is not None and Decimal("0") < ask_size <= MAX_PAPER_QUOTE_SIZE,
            quote_risk is not None and Decimal("0") < quote_risk <= MAX_BAND_NOTIONAL_PUSD,
            quote_risk == expected_quote_risk,
            row_budget is not None and row_budget == budget,
            quote_risk is not None and budget is not None and quote_risk <= budget,
            row.get("expected_reward_score") in {"0", "0.0", "0.00"},
            row.get("expected_rebate_value") in {"0", "0.0", "0.00"},
        ))
        if not row_checks:
            return
        row_binding = {
            "run_id": row["run_id"],
            "market_id": row["market_id"],
            "target_date": row["target_date"],
            "condition_id": condition,
            "token_id": token,
            "range_label": row.get("range_label"),
            "exchange_economics_snapshot_id": economics_snapshot_id,
            "exchange_economics_hash": economics_hash,
            "policy_hash": row.get("policy_hash"),
            "generated_at_utc": generated.isoformat(),
            "expires_at_utc": (generated + timedelta(seconds=float(ttl))).isoformat(),
            "quote_ttl_seconds": float(ttl),
            "bid_price": float(bid),
            "bid_size": float(bid_size),
            "ask_price": float(ask),
            "ask_size": float(ask_size),
            "quote_risk_pusd": float(quote_risk),
            "quote_permission": True,
            "live_trade_permission": False,
            "two_sided_post_only_intent": True,
            "reward_and_rebate_assumed_zero": True,
        }
        row_binding["quote_row_sha256"] = _canonical_sha256(row)
        qualifying[(condition, token)] = row_binding

    row_count, quote_intents_sha256 = _scan_hashed_csv(
        quote_intents_path,
        consider,
    )
    if not qualifying:
        raise RuntimeError("paper quote evidence contains no current qualifying quote-permission row")
    return {
        "run_config_sha256": hashlib.sha256(config_raw).hexdigest(),
        "quote_intents_sha256": quote_intents_sha256,
        "quote_intents_row_count": row_count,
        "market_id": markets[0],
        "run_id": config.get("run_id"),
        "qualifying": qualifying,
    }


def _book_levels(book, side):
    levels = []
    for row in book.get(side) or []:
        price = _decimal(row.get("price")) if isinstance(row, dict) else None
        size = _decimal(row.get("size")) if isinstance(row, dict) else None
        if price is not None and size is not None and 0 < price < 1 and size > 0:
            levels.append((price, size))
    return levels


def _candidate_for_book(market, token_id, outcome_index, book):
    if str(book.get("asset_id") or "") != str(token_id):
        return None
    condition_id = str(market.get("condition_id") or "").lower()
    observed_condition = str(book.get("market") or "").lower()
    if observed_condition != condition_id:
        return None
    bids = _book_levels(book, "bids")
    asks = _book_levels(book, "asks")
    if not bids or not asks:
        return None
    best_bid = max(price for price, _size in bids)
    best_ask = min(price for price, _size in asks)
    if best_bid >= best_ask:
        return None
    spread = best_ask - best_bid
    midpoint = (best_bid + best_ask) / 2
    min_size = _decimal(market.get("order_min_size"))
    tick_size = _decimal(market.get("order_price_min_tick_size"))
    book_min_size = _decimal(book.get("min_order_size"))
    book_tick_size = _decimal(book.get("tick_size"))
    book_neg_risk = book.get("neg_risk")
    fee = dict(market.get("fee_schedule") or {})
    fee_rate = _decimal(fee.get("rate"))
    rebate_rate = _decimal(fee.get("rebate_rate"))
    if not all((
        market.get("fees_enabled") is True,
        min_size is not None and min_size > 0,
        tick_size is not None and 0 < tick_size < 1,
        book_min_size == min_size,
        book_tick_size == tick_size,
        isinstance(book_neg_risk, bool),
        fee_rate is not None and fee_rate > 0,
        rebate_rate is not None and rebate_rate > 0,
        best_ask > tick_size,
        MIN_MIDPOINT <= midpoint <= MAX_MIDPOINT,
        spread <= MAX_BOOK_SPREAD,
        min_size * tick_size <= MAX_SINGLE_ORDER_NOTIONAL,
    )):
        return None
    best_bid_depth = sum(size for price, size in bids if price == best_bid)
    best_ask_depth = sum(size for price, size in asks if price == best_ask)
    rewards = dict(market.get("liquidity_rewards") or {})
    reward_max_spread = _decimal(rewards.get("rewards_max_spread_cents"))
    reward_min_size = _decimal(rewards.get("rewards_min_size"))
    result = {
        "location_id": market.get("location_id"),
        "event_date": market.get("event_date"),
        "event_slug": market.get("event_slug"),
        "question": market.get("question"),
        "condition_id": condition_id,
        "token_id": str(token_id),
        "outcome_index": int(outcome_index),
        "best_bid": float(best_bid),
        "best_ask": float(best_ask),
        "midpoint": float(midpoint),
        "spread": float(spread),
        "best_bid_depth": float(best_bid_depth),
        "best_ask_depth": float(best_ask_depth),
        "order_min_size": float(min_size),
        "tick_size": float(tick_size),
        "neg_risk": book_neg_risk,
        "fee_rate": float(fee_rate),
        "maker_rebate_rate": float(rebate_rate),
        "reward_min_size": float(reward_min_size)
        if reward_min_size is not None else None,
        "reward_max_spread_cents": float(reward_max_spread)
        if reward_max_spread is not None else None,
        "current_book_within_reward_spread": (
            reward_max_spread is not None
            and spread * 100 <= reward_max_spread
        ),
        "lifecycle_probe_reward_min_size_met": (
            reward_min_size is not None and min_size >= reward_min_size
        ),
        "book_sha256": _canonical_sha256(book),
    }
    result["stage1_intent"] = {
        "side": "BUY",
        "price": float(tick_size),
        "size": float(min_size),
        "notional_pusd": float(tick_size * min_size),
        "post_only": True,
    }
    return result


def select_live_pilot_candidate(
    economics_snapshot,
    target_date,
    plan_out,
    *,
    accepted_economics_snapshot,
    economics_drift_report,
    paper_run_config,
    paper_quote_intents,
    substrate_preflight,
    economics_baseline_acknowledgment=None,
    expected_condition_id=None,
    expected_token_id=None,
    now=None,
    book_reader=None,
):
    assert_no_ambient_market_registry_override()
    target_text = ensure_date(target_date).isoformat()
    output_input = Path(plan_out)
    if not output_input.is_absolute():
        raise RuntimeError("candidate-plan output path must be absolute")
    output_parent = validate_nonreparse_directory(output_input.parent)
    output = output_parent / output_input.name
    if output.exists() or output.is_symlink():
        raise RuntimeError("candidate-plan output path must be new")
    gate = load_exchange_economics_gate(
        economics_snapshot,
        target_text,
        platform=PLATFORM,
        now=now,
        max_age_hours=2,
    )
    created_at = utc_now(now)
    expected_condition = str(expected_condition_id or "").lower()
    expected_token = str(expected_token_id or "")
    if bool(expected_condition) != bool(expected_token):
        raise RuntimeError("expected condition and token constraints must be supplied together")
    substrate_binding = _load_substrate_preflight_receipt(
        substrate_preflight,
        target_date=target_text,
        economics_snapshot=economics_snapshot,
        accepted_economics_snapshot=accepted_economics_snapshot,
        economics_drift_report=economics_drift_report,
        paper_run_config=paper_run_config,
        paper_quote_intents=paper_quote_intents,
        now=created_at,
    )
    base = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCK",
        "created_at_utc": created_at.isoformat(),
        "expires_at_utc": (
            created_at + timedelta(seconds=MAX_PLAN_AGE_SECONDS)
        ).isoformat(),
        "target_date": target_text,
        "platform": PLATFORM,
        "settlement_unit": SETTLEMENT_UNIT,
        "exchange_economics_snapshot_id": gate.get("snapshot_id"),
        "exchange_economics_sha256": gate.get("exchange_economics_hash"),
        "economics_gate_ok": gate.get("ok") is True,
        "economics_gate_missing": list(gate.get("missing") or []),
        "economics_acceptance": None,
        "substrate_preflight": substrate_binding,
        "selection_is_trading_authorization": False,
        "secret_values_retained": False,
        "selection_policy": {
            "built_in_locations_only": True,
            "positive_fee_and_rebate_required": True,
            "midpoint_interval": [float(MIN_MIDPOINT), float(MAX_MIDPOINT)],
            "max_spread": float(MAX_BOOK_SPREAD),
            "minimum_tick_buy_must_be_nonmarketable": True,
            "book_tick_min_size_and_neg_risk_must_be_current": True,
            "plan_max_age_seconds": MAX_PLAN_AGE_SECONDS,
            "max_single_order_notional_pusd": float(MAX_SINGLE_ORDER_NOTIONAL),
            "successful_current_market_harvest_quote_required": True,
            "expected_bootstrap_scope": {
                "condition_id": expected_condition or None,
                "token_id": expected_token or None,
            },
            "ranking": "spread_asc_then_best_level_depth_desc_then_midpoint_distance",
        },
        "paper_quote_evidence": None,
        "candidate_count": 0,
        "selected": None,
        "alternates": [],
        "missing": [],
    }
    if not gate.get("ok"):
        base["missing"] = ["current_exchange_economics_gate"]
        base["plan_sha256"] = candidate_plan_sha256(base)
        _write_new_json(output, base)
        return base
    snapshot = json.loads(Path(economics_snapshot).read_text(encoding="utf-8-sig"))
    if snapshot_hash(snapshot) != gate.get("exchange_economics_hash"):
        raise RuntimeError("economics snapshot changed after validation")
    acceptance = load_economics_acceptance_evidence(
        economics_snapshot,
        accepted_economics_snapshot,
        economics_drift_report,
        target_text,
        now=now,
    )
    base["economics_acceptance"] = {
        **acceptance,
        "operator_acknowledgment": None,
        "operator_acknowledgment_matches_candidate": False,
        "required_operator_acknowledgment": None,
    }
    paper_evidence = _load_paper_quote_evidence(
        paper_run_config,
        paper_quote_intents,
        target_date=target_text,
        economics_snapshot_id=gate.get("snapshot_id"),
        economics_hash=gate.get("exchange_economics_hash"),
        now=now,
    )
    if not all(
        (
            substrate_binding["market_id"] == paper_evidence["market_id"],
            substrate_binding["economics_snapshot_file_sha256"]
            == hashlib.sha256(Path(economics_snapshot).read_bytes()).hexdigest(),
            substrate_binding["accepted_snapshot_file_sha256"]
            == acceptance["accepted_snapshot_file_sha256"],
            substrate_binding["economics_drift_report_file_sha256"]
            == acceptance["drift_report_file_sha256"],
            substrate_binding["paper_run_config_file_sha256"]
            == paper_evidence["run_config_sha256"],
            substrate_binding["paper_quote_intents_file_sha256"]
            == paper_evidence["quote_intents_sha256"],
        )
    ):
        raise RuntimeError("candidate inputs changed after substrate preflight")
    base["paper_quote_evidence"] = {
        key: value for key, value in paper_evidence.items() if key != "qualifying"
    }
    built_in_locations = {spec.id for spec in BUILTIN_SPECS}
    markets = [
        row for row in snapshot.get("markets") or []
        if row.get("location_id") in built_in_locations
        and row.get("location_id") == paper_evidence["market_id"]
        and row.get("event_date") == target_text
    ]
    token_map = {}
    for market in markets:
        for outcome_index, token_id in enumerate(market.get("token_ids") or []):
            token_map[str(token_id)] = (market, outcome_index)
    reader = book_reader or ClobClient(timeout=15).get_order_books
    books = reader(list(token_map))
    candidates = []
    for book in books or []:
        if not isinstance(book, dict):
            continue
        token_id = str(book.get("asset_id") or "")
        bound = token_map.get(token_id)
        if bound is None:
            continue
        condition_id = str(bound[0].get("condition_id") or "").lower()
        if expected_condition and (
            condition_id != expected_condition or token_id != expected_token
        ):
            continue
        paper_quote = paper_evidence["qualifying"].get((condition_id, token_id))
        if paper_quote is None:
            continue
        candidate = _candidate_for_book(bound[0], token_id, bound[1], book)
        if candidate is not None:
            candidate["paper_quote_proof"] = paper_quote
            candidates.append(candidate)
    candidates.sort(key=lambda row: (
        row["spread"],
        -(row["best_bid_depth"] + row["best_ask_depth"]),
        abs(row["midpoint"] - 0.5),
        row["location_id"],
        row["token_id"],
    ))
    base["candidate_count"] = len(candidates)
    if candidates:
        base["selected"] = candidates[0]
        base["alternates"] = candidates[1:1 + MAX_ALTERNATES]
        paper_expiry = _parse_utc(candidates[0]["paper_quote_proof"]["expires_at_utc"])
        ordinary_expiry = created_at + timedelta(seconds=MAX_PLAN_AGE_SECONDS)
        substrate_expiry = _parse_utc(substrate_binding["expires_at_utc"])
        base["expires_at_utc"] = min(
            ordinary_expiry,
            paper_expiry,
            substrate_expiry,
        ).isoformat()
        required_acknowledgment = economics_acceptance_acknowledgment(
            target_text,
            candidates[0]["condition_id"],
            candidates[0]["token_id"],
            accepted_snapshot_file_sha256=acceptance[
                "accepted_snapshot_file_sha256"
            ],
            drift_report_file_sha256=acceptance["drift_report_file_sha256"],
        )
        matched = economics_baseline_acknowledgment == required_acknowledgment
        base["economics_acceptance"].update(
            {
                "operator_acknowledgment": (
                    required_acknowledgment if matched else None
                ),
                "operator_acknowledgment_matches_candidate": matched,
                "required_operator_acknowledgment": required_acknowledgment,
            }
        )
        if matched:
            base["status"] = "PASS"
        else:
            base["missing"] = [
                "explicit_candidate_economics_baseline_acknowledgment"
            ]
    else:
        base["missing"] = ["current_paper_proved_safe_fee_eligible_book_candidate"]
    base["plan_sha256"] = candidate_plan_sha256(base)
    _write_new_json(output, base)
    return base


def _load_candidate_plan_gate(
    plan_path,
    *,
    target_date=None,
    expected_condition_id=None,
    expected_token_id=None,
    require_unconstrained=False,
    now=None,
):
    assert_no_ambient_market_registry_override()
    raw = Path(plan_path).read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("candidate plan is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("candidate plan must be a JSON object")
    from weather.market.mm_credentials import contains_secret_material

    selected_value = payload.get("selected")
    selected = dict(selected_value) if isinstance(selected_value, dict) else {}
    paper_value = selected.get("paper_quote_proof")
    paper = dict(paper_value) if isinstance(paper_value, dict) else {}
    intent_value = selected.get("stage1_intent")
    intent = dict(intent_value) if isinstance(intent_value, dict) else {}
    evidence_value = payload.get("paper_quote_evidence")
    evidence = dict(evidence_value) if isinstance(evidence_value, dict) else {}
    policy_value = payload.get("selection_policy")
    policy = dict(policy_value) if isinstance(policy_value, dict) else {}
    acceptance_value = payload.get("economics_acceptance")
    acceptance = (
        dict(acceptance_value) if isinstance(acceptance_value, dict) else {}
    )
    substrate_value = payload.get("substrate_preflight")
    substrate = dict(substrate_value) if isinstance(substrate_value, dict) else {}
    expected_scope_value = policy.get("expected_bootstrap_scope")
    expected_scope = (
        dict(expected_scope_value) if isinstance(expected_scope_value, dict) else {}
    )
    selected_condition = str(selected.get("condition_id") or "").lower()
    selected_token = str(selected.get("token_id") or "")
    condition = (
        selected_condition
        if require_unconstrained
        else str(expected_condition_id or "").lower()
    )
    token = selected_token if require_unconstrained else str(expected_token_id or "")
    current = utc_now(now)
    try:
        created = _parse_utc(payload.get("created_at_utc"))
        expires = _parse_utc(payload.get("expires_at_utc"))
        paper_generated = _parse_utc(paper.get("generated_at_utc"))
        paper_expires = _parse_utc(paper.get("expires_at_utc"))
        accepted_at = _parse_utc(acceptance.get("accepted_at_utc"))
        drift_generated = _parse_utc(
            acceptance.get("drift_generated_at_utc")
        )
        substrate_expires = _parse_utc(substrate.get("expires_at_utc"))
    except RuntimeError:
        invalid_time = datetime.min.replace(tzinfo=timezone.utc)
        created = expires = paper_generated = paper_expires = invalid_time
        accepted_at = drift_generated = invalid_time
        substrate_expires = invalid_time
    paper_ttl = _decimal(paper.get("quote_ttl_seconds"))
    notional = _decimal(intent.get("notional_pusd"))
    price = _decimal(intent.get("price"))
    size = _decimal(intent.get("size"))
    best_bid = _decimal(selected.get("best_bid"))
    best_ask = _decimal(selected.get("best_ask"))
    spread = _decimal(selected.get("spread"))
    tick_size = _decimal(selected.get("tick_size"))
    min_size = _decimal(selected.get("order_min_size"))
    paper_bid = _decimal(paper.get("bid_price"))
    paper_ask = _decimal(paper.get("ask_price"))
    paper_bid_size = _decimal(paper.get("bid_size"))
    paper_ask_size = _decimal(paper.get("ask_size"))
    paper_risk = _decimal(paper.get("quote_risk_pusd"))
    midpoint = _decimal(selected.get("midpoint"))
    best_bid_depth = _decimal(selected.get("best_bid_depth"))
    best_ask_depth = _decimal(selected.get("best_ask_depth"))
    fee_rate = _decimal(selected.get("fee_rate"))
    rebate_rate = _decimal(selected.get("maker_rebate_rate"))
    reward_min_size = _decimal(selected.get("reward_min_size"))
    reward_max_spread = _decimal(selected.get("reward_max_spread_cents"))
    economics_hash_value = payload.get("exchange_economics_sha256")
    economics_hash = (
        economics_hash_value if isinstance(economics_hash_value, str) else ""
    )
    economics_id = str(payload.get("exchange_economics_snapshot_id") or "")
    try:
        canonical_target = ensure_date(payload.get("target_date")).isoformat()
    except (TypeError, ValueError):
        canonical_target = ""
    expected_target = (
        ensure_date(target_date).isoformat() if target_date is not None else canonical_target
    )
    invalid_timestamp = datetime.min.replace(tzinfo=timezone.utc)
    try:
        expected_effective_expiry = min(
            created + timedelta(seconds=MAX_PLAN_AGE_SECONDS),
            paper_expires,
            substrate_expires,
        )
    except OverflowError:
        expected_effective_expiry = invalid_timestamp
    try:
        expected_paper_expiry = (
            paper_generated + timedelta(seconds=float(paper_ttl))
            if paper_ttl is not None
            and Decimal("0") < paper_ttl <= MAX_PAPER_QUOTE_TTL_SECONDS
            else invalid_timestamp
        )
    except OverflowError:
        expected_paper_expiry = invalid_timestamp
    top_level_keys = {
        "schema_version", "status", "created_at_utc", "expires_at_utc",
        "target_date", "platform", "settlement_unit",
        "exchange_economics_snapshot_id", "exchange_economics_sha256",
        "economics_gate_ok", "economics_gate_missing", "economics_acceptance",
        "substrate_preflight",
        "selection_is_trading_authorization", "secret_values_retained",
        "selection_policy", "paper_quote_evidence", "candidate_count",
        "selected", "alternates", "missing", "plan_sha256",
    }
    selected_keys = {
        "location_id", "event_date", "event_slug", "question", "condition_id",
        "token_id", "outcome_index", "best_bid", "best_ask", "midpoint",
        "spread", "best_bid_depth", "best_ask_depth", "order_min_size",
        "tick_size", "neg_risk", "fee_rate", "maker_rebate_rate",
        "reward_min_size", "reward_max_spread_cents",
        "current_book_within_reward_spread",
        "lifecycle_probe_reward_min_size_met", "book_sha256", "stage1_intent",
        "paper_quote_proof",
    }
    paper_keys = {
        "run_id", "market_id", "target_date", "condition_id", "token_id",
        "range_label", "exchange_economics_snapshot_id",
        "exchange_economics_hash", "policy_hash", "generated_at_utc",
        "expires_at_utc", "quote_ttl_seconds", "bid_price", "bid_size",
        "ask_price", "ask_size", "quote_risk_pusd", "quote_permission",
        "live_trade_permission", "two_sided_post_only_intent",
        "reward_and_rebate_assumed_zero", "quote_row_sha256",
    }
    policy_keys = {
        "built_in_locations_only", "positive_fee_and_rebate_required",
        "midpoint_interval", "max_spread",
        "minimum_tick_buy_must_be_nonmarketable",
        "book_tick_min_size_and_neg_risk_must_be_current",
        "plan_max_age_seconds", "max_single_order_notional_pusd",
        "successful_current_market_harvest_quote_required",
        "expected_bootstrap_scope", "ranking",
    }
    evidence_keys = {
        "run_config_sha256", "quote_intents_sha256", "quote_intents_row_count",
        "market_id", "run_id",
    }
    intent_keys = {"side", "price", "size", "notional_pusd", "post_only"}
    try:
        substrate_gate = validate_candidate_substrate_binding(
            substrate,
            target_date=expected_target,
            market_id=str(paper.get("market_id") or ""),
            created_at=payload.get("created_at_utc"),
            now=current,
        )
        substrate_ok = True
    except (RuntimeError, TypeError, ValueError):
        substrate_gate = {}
        substrate_ok = False
    midpoint_interval = policy.get("midpoint_interval")
    alternates = payload.get("alternates")
    candidate_count = payload.get("candidate_count")
    row_count = evidence.get("quote_intents_row_count")
    outcome_index = selected.get("outcome_index")
    reward_spread_met = (
        reward_max_spread is not None
        and spread is not None
        and spread * 100 <= reward_max_spread
    )
    reward_size_met = (
        reward_min_size is not None
        and min_size is not None
        and min_size >= reward_min_size
    )
    scope_contract = (
        expected_scope_value is not None
        and isinstance(expected_scope_value, dict)
        and set(expected_scope_value) == {"condition_id", "token_id"}
    )
    if require_unconstrained:
        scope_contract = scope_contract and all(
            expected_scope.get(field) is None for field in ("condition_id", "token_id")
        )
        scope_check_name = "unconstrained_scope"
    else:
        scope_contract = scope_contract and (
            str(expected_scope.get("condition_id") or "").lower() == condition
            and str(expected_scope.get("token_id") or "") == token
        )
        scope_check_name = "constrained_scope"
    try:
        required_acceptance = economics_acceptance_acknowledgment(
            expected_target,
            condition,
            token,
            accepted_snapshot_file_sha256=acceptance.get(
                "accepted_snapshot_file_sha256"
            ),
            drift_report_file_sha256=acceptance.get(
                "drift_report_file_sha256"
            ),
        )
    except (RuntimeError, TypeError, ValueError):
        required_acceptance = ""
    paper_quote_shape = (
        paper_bid is not None
        and paper_ask is not None
        and Decimal("0") < paper_bid < paper_ask < Decimal("1")
        and paper_bid_size is not None
        and Decimal("0") < paper_bid_size <= MAX_PAPER_QUOTE_SIZE
        and paper_ask_size is not None
        and Decimal("0") < paper_ask_size <= MAX_PAPER_QUOTE_SIZE
        and paper_risk is not None
        and Decimal("0") < paper_risk <= MAX_BAND_NOTIONAL_PUSD
        and paper_risk
        == (
            paper_bid * paper_bid_size
            + (Decimal("1") - paper_ask) * paper_ask_size
        ).quantize(Decimal("0.000001"))
        and min_size is not None
        and paper_bid_size >= min_size
        and paper_ask_size >= min_size
        and tick_size is not None
        and tick_size > 0
        and paper_bid % tick_size == 0
        and paper_ask % tick_size == 0
        and best_ask is not None
        and paper_bid < best_ask
        and best_bid is not None
        and paper_ask > best_bid
    )
    current_book = (
        best_bid is not None
        and best_ask is not None
        and Decimal("0") < best_bid < best_ask < Decimal("1")
        and spread is not None
        and Decimal("0") < spread <= MAX_BOOK_SPREAD
        and midpoint is not None
        and midpoint == (best_bid + best_ask) / 2
        and spread == best_ask - best_bid
        and MIN_MIDPOINT <= midpoint <= MAX_MIDPOINT
        and best_bid_depth is not None
        and best_bid_depth > 0
        and best_ask_depth is not None
        and best_ask_depth > 0
    )
    current_book_rules = (
        tick_size is not None
        and Decimal("0") < tick_size < Decimal("1")
        and min_size is not None
        and min_size > 0
        and isinstance(selected.get("neg_risk"), bool)
        and fee_rate is not None
        and fee_rate > 0
        and rebate_rate is not None
        and rebate_rate > 0
        and tick_size * min_size <= MAX_SINGLE_ORDER_NOTIONAL
        and _is_sha256(selected.get("book_sha256"))
        and (reward_min_size is None or reward_min_size > 0)
        and (reward_max_spread is None or reward_max_spread > 0)
        and selected.get("current_book_within_reward_spread") is reward_spread_met
        and selected.get("lifecycle_probe_reward_min_size_met") is reward_size_met
    )
    intent_ok = (
        intent.get("side") == "BUY"
        and intent.get("post_only") is True
        and price is not None
        and price == tick_size
        and size is not None
        and size == min_size
        and best_ask is not None
        and price < best_ask
        and notional is not None
        and Decimal("0") < notional <= MAX_SINGLE_ORDER_NOTIONAL
        and notional == price * size
    )
    checks = {
        "exact_schema_shape": (
            isinstance(selected_value, dict)
            and isinstance(paper_value, dict)
            and isinstance(intent_value, dict)
            and isinstance(evidence_value, dict)
            and isinstance(policy_value, dict)
            and isinstance(acceptance_value, dict)
            and isinstance(substrate_value, dict)
            and set(payload) == top_level_keys
            and set(selected) == selected_keys
            and set(paper) == paper_keys
            and set(policy) == policy_keys
            and set(evidence) == evidence_keys
            and set(intent) == intent_keys
            and set(acceptance) == ECONOMICS_ACCEPTANCE_KEYS
            and set(substrate) == SUBSTRATE_BINDING_KEYS
        ),
        "schema": payload.get("schema_version") == SCHEMA_VERSION,
        "status": payload.get("status") == "PASS",
        "plan_hash": payload.get("plan_sha256") == candidate_plan_sha256(payload),
        "platform": payload.get("platform") == PLATFORM,
        "settlement_unit": payload.get("settlement_unit") == SETTLEMENT_UNIT,
        "target_date": (
            payload.get("target_date") == canonical_target == expected_target
            and paper.get("target_date") == expected_target
            and selected.get("event_date") == expected_target
        ),
        "non_authorizing": payload.get("selection_is_trading_authorization") is False,
        "secret_free": (
            payload.get("secret_values_retained") is False
            and not contains_secret_material(payload)
        ),
        "economics": (
            payload.get("economics_gate_ok") is True
            and payload.get("economics_gate_missing") == []
            and len(economics_hash) == 32
            and all(character in "0123456789abcdef" for character in economics_hash)
            and economics_id == f"xecon-{economics_hash[:16]}"
        ),
        "economics_acceptance": (
            acceptance.get("accepted_snapshot_id") == economics_id
            and acceptance.get("accepted_snapshot_sha256") == economics_hash
            and _is_sha256(acceptance.get("accepted_snapshot_file_sha256"))
            and _is_sha256(acceptance.get("drift_report_file_sha256"))
            and acceptance.get("drift_status") == "PASS"
            and acceptance.get("rescore_required") is False
            and acceptance.get("operator_acknowledgment_matches_candidate") is True
            and bool(required_acceptance)
            and acceptance.get("required_operator_acknowledgment")
            == required_acceptance
            and acceptance.get("operator_acknowledgment") == required_acceptance
            and accepted_at <= drift_generated <= created
        ),
        "substrate_preflight": (
            substrate_ok
            and substrate_gate.get("accepted_snapshot_file_sha256")
            == acceptance.get("accepted_snapshot_file_sha256")
            and substrate_gate.get("economics_drift_report_file_sha256")
            == acceptance.get("drift_report_file_sha256")
            and substrate_gate.get("paper_run_config_file_sha256")
            == evidence.get("run_config_sha256")
            and substrate_gate.get("paper_quote_intents_file_sha256")
            == evidence.get("quote_intents_sha256")
        ),
        "created": created <= current,
        "current": current < expires and current < paper_expires,
        "expiry_contract": expires == expected_effective_expiry,
        "paper_expiry_contract": paper_expires == expected_paper_expiry,
        "paper_generated_before_plan": paper_generated <= created,
        "paper_ttl": paper_ttl is not None
        and Decimal("0") < paper_ttl <= MAX_PAPER_QUOTE_TTL_SECONDS,
        "condition": selected_condition == condition,
        "token": selected_token == token,
        "scope_format": (
            len(condition) == 66
            and condition.startswith("0x")
            and all(character in "0123456789abcdef" for character in condition[2:])
            and bool(token)
            and token[0] in "123456789"
            and all(character in "0123456789" for character in token)
        ),
        scope_check_name: scope_contract,
        "selection_policy": (
            policy.get("built_in_locations_only") is True
            and policy.get("positive_fee_and_rebate_required") is True
            and isinstance(midpoint_interval, list)
            and len(midpoint_interval) == 2
            and [_decimal(value) for value in midpoint_interval]
            == [MIN_MIDPOINT, MAX_MIDPOINT]
            and _decimal(policy.get("max_spread")) == MAX_BOOK_SPREAD
            and policy.get("minimum_tick_buy_must_be_nonmarketable") is True
            and policy.get("book_tick_min_size_and_neg_risk_must_be_current") is True
            and policy.get("plan_max_age_seconds") == MAX_PLAN_AGE_SECONDS
            and _decimal(policy.get("max_single_order_notional_pusd"))
            == MAX_SINGLE_ORDER_NOTIONAL
            and policy.get("successful_current_market_harvest_quote_required") is True
            and policy.get("ranking")
            == "spread_asc_then_best_level_depth_desc_then_midpoint_distance"
        ),
        "selected_scope": (
            selected.get("condition_id") == condition
            and selected.get("token_id") == token
            and selected.get("location_id") in {spec.id for spec in BUILTIN_SPECS}
            and isinstance(selected.get("event_slug"), str)
            and bool(selected.get("event_slug").strip())
            and isinstance(selected.get("question"), str)
            and bool(selected.get("question").strip())
            and isinstance(outcome_index, int)
            and not isinstance(outcome_index, bool)
            and outcome_index >= 0
        ),
        "candidate_set": (
            isinstance(candidate_count, int)
            and not isinstance(candidate_count, bool)
            and candidate_count >= 1
            and isinstance(alternates, list)
            and len(alternates) <= MAX_ALTERNATES
            and candidate_count >= 1 + len(alternates)
            and payload.get("missing") == []
        ),
        "paper_condition": paper.get("condition_id") == condition,
        "paper_token": paper.get("token_id") == token,
        "paper_run": (
            isinstance(paper.get("run_id"), str)
            and bool(paper.get("run_id").strip())
            and isinstance(evidence.get("run_id"), str)
            and paper.get("run_id") == evidence.get("run_id")
        ),
        "paper_market": str(paper.get("market_id") or "")
        == str(evidence.get("market_id") or "")
        == str(selected.get("location_id") or ""),
        "paper_economics": (
            paper.get("exchange_economics_snapshot_id")
            == economics_id
            and paper.get("exchange_economics_hash")
            == economics_hash
        ),
        "paper_policy": (
            isinstance(paper.get("policy_hash"), str)
            and bool(paper.get("policy_hash").strip())
        ),
        "paper_permission": paper.get("quote_permission") is True,
        "paper_mutation_disabled": paper.get("live_trade_permission") is False,
        "paper_two_sided": paper.get("two_sided_post_only_intent") is True,
        "paper_zero_reward_assumption": paper.get("reward_and_rebate_assumed_zero") is True,
        "paper_quote_shape": paper_quote_shape,
        "paper_hashes": all(
            _is_sha256(evidence.get(field))
            for field in ("run_config_sha256", "quote_intents_sha256")
        ) and _is_sha256(paper.get("quote_row_sha256"))
        and isinstance(row_count, int)
        and not isinstance(row_count, bool)
        and row_count > 0,
        "current_book": current_book,
        "current_book_rules": current_book_rules,
        "intent": intent_ok,
    }
    missing = [name for name, valid in checks.items() if not valid]
    if missing:
        label = "candidate discovery" if require_unconstrained else "Stage 1 candidate"
        raise RuntimeError(f"{label} gate failed: " + ", ".join(missing))
    return {
        "ok": True,
        "plan_sha256": hashlib.sha256(raw).hexdigest(),
        "semantic_plan_sha256": payload["plan_sha256"],
        "target_date": expected_target,
        "market_id": paper["market_id"],
        "condition_id": condition,
        "token_id": token,
        "created_at_utc": created.isoformat(),
        "expires_at_utc": expires.isoformat(),
        "paper_quote_expires_at_utc": paper_expires.isoformat(),
        "paper_run_config_sha256": evidence["run_config_sha256"],
        "paper_quote_intents_sha256": evidence["quote_intents_sha256"],
        "paper_quote_row_sha256": paper["quote_row_sha256"],
        "substrate_preflight_receipt_sha256": substrate["receipt_sha256"],
        "economics_acceptance": dict(acceptance),
        "stage1_intent": dict(intent),
        "tick_size": float(tick_size),
        "order_min_size": float(min_size),
        "fee_rate": float(fee_rate),
        "neg_risk": selected["neg_risk"],
    }


def load_candidate_discovery_gate(plan_path, *, now=None):
    """Load one complete, current, unconstrained public discovery plan."""

    return _load_candidate_plan_gate(
        plan_path,
        require_unconstrained=True,
        now=now,
    )


def load_stage1_candidate_gate(
    plan_path,
    target_date,
    *,
    expected_condition_id,
    expected_token_id,
    now=None,
):
    return _load_candidate_plan_gate(
        plan_path,
        target_date=target_date,
        expected_condition_id=expected_condition_id,
        expected_token_id=expected_token_id,
        now=now,
    )


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--economics-snapshot", required=True)
    parser.add_argument("--accepted-economics-snapshot", required=True)
    parser.add_argument("--economics-drift-report", required=True)
    parser.add_argument(
        "--economics-baseline-acknowledgment",
        help=(
            "exact candidate/date/evidence-bound literal emitted by a prior "
            "review-only selector plan after informed operator review"
        ),
    )
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--paper-run-config", required=True)
    parser.add_argument("--paper-quote-intents", required=True)
    parser.add_argument("--substrate-preflight", required=True)
    parser.add_argument("--expected-condition-id")
    parser.add_argument("--expected-token-id")
    parser.add_argument("--plan-out", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = select_live_pilot_candidate(
            args.economics_snapshot,
            args.target_date,
            args.plan_out,
            accepted_economics_snapshot=args.accepted_economics_snapshot,
            economics_drift_report=args.economics_drift_report,
            paper_run_config=args.paper_run_config,
            paper_quote_intents=args.paper_quote_intents,
            substrate_preflight=args.substrate_preflight,
            economics_baseline_acknowledgment=(
                args.economics_baseline_acknowledgment
            ),
            expected_condition_id=args.expected_condition_id,
            expected_token_id=args.expected_token_id,
        )
    except Exception as exc:
        print(f"candidate selection failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if result["status"] != "PASS":
        print("candidate selection BLOCK", file=sys.stderr)
        return 1
    print("candidate selection PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
