"""Canonical fail-closed parent gate for staged model production readiness.

The gate is deliberately read-only.  It never promotes a release, changes a
pointer, starts a worker, enables credentials, or submits an order.  It reads
predeclared child evidence, hash-links every input, requires one verified
served release identity, and reports the highest stage whose complete evidence
contract passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from weather.operations.capture_resource_gate import (
    EVIDENCE_CONTRACT as CAPTURE_RESOURCE_EVIDENCE_CONTRACT,
    INTEGRATED_WORKLOADS as CAPTURE_RESOURCE_WORKLOADS,
)
from weather.paths import data_path
from weather.release_artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_RELEASES_ROOT,
    ReleaseArtifactVerificationError,
    canonical_payload_sha256,
    resolve_verified_active_release,
    strict_json_loads,
    validate_release_id,
)
from weather.schema_registry import registry_payload, schema_version


SCHEMA_VERSION = schema_version("production_readiness_gate")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "production_readiness_gate.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "production_readiness_gate.md"

STAGE_NOT_READY = "NOT_READY"
STAGE_SHADOW = "SHADOW"
STAGE_PAPER = "PAPER"
STAGE_CAPITAL_CANARY = "CAPITAL_CANARY"
STAGES = (STAGE_SHADOW, STAGE_PAPER, STAGE_CAPITAL_CANARY)
STAGE_ORDER = {
    STAGE_NOT_READY: 0,
    STAGE_SHADOW: 1,
    STAGE_PAPER: 2,
    STAGE_CAPITAL_CANARY: 3,
}
REQUIRED_RELEASE_ARTIFACT_KINDS = frozenset(
    {
        "model",
        "calibration",
        "config",
        "imputer",
        "feature_schema",
        "postprocessor",
        "route",
        "registry",
        "settlement_rules",
    }
)

REGISTERED_SCHEMA_NAMES = {
    row["version"]: row["name"]
    for row in registry_payload().get("schemas") or []
}


def utc_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _parse_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _field(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _explicit_release_identity(payload: Mapping[str, Any]) -> tuple[str, str]:
    identity = payload.get("release_identity")
    identity = identity if isinstance(identity, Mapping) else {}
    release_id = str(payload.get("release_id") or identity.get("release_id") or "").strip()
    manifest_sha = str(
        payload.get("manifest_sha256")
        or payload.get("release_manifest_sha256")
        or identity.get("manifest_sha256")
        or ""
    ).strip()
    return release_id, manifest_sha


def _validator_issue(code: str, detail: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "detail": detail, **evidence}


def _expect(
    issues: list[dict[str, Any]],
    payload: Mapping[str, Any],
    path: Sequence[str],
    expected: Any,
    *,
    code: str,
) -> None:
    actual = _field(payload, path)
    if actual != expected:
        issues.append(
            _validator_issue(
                code,
                f"{'.'.join(path)} must be exactly {expected!r}",
                field=".".join(path),
                expected=expected,
                actual=actual,
            )
        )


def _expect_number(
    issues: list[dict[str, Any]],
    payload: Mapping[str, Any],
    path: Sequence[str],
    predicate: Callable[[float], bool],
    requirement: str,
    *,
    code: str,
) -> None:
    actual = _field(payload, path)
    parsed = _number(actual)
    if parsed is None or not predicate(parsed):
        issues.append(
            _validator_issue(
                code,
                f"{'.'.join(path)} must be {requirement}",
                field=".".join(path),
                actual=actual,
                requirement=requirement,
            )
        )


def _expect_nonempty(
    issues: list[dict[str, Any]],
    payload: Mapping[str, Any],
    path: Sequence[str],
    *,
    code: str,
) -> None:
    actual = _field(payload, path)
    if not str(actual or "").strip():
        issues.append(
            _validator_issue(
                code,
                f"{'.'.join(path)} must be non-empty",
                field=".".join(path),
            )
        )


def _validate_settlement(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(issues, payload, ("blocker_count",), 0, code="settlement_blockers_present")
    _expect(
        issues,
        payload,
        ("configuration", "require_explicit_release_id"),
        True,
        code="settlement_explicit_release_not_required",
    )
    _expect(
        issues,
        payload,
        ("configuration", "expected_variant_contract"),
        "explicit_manifest",
        code="settlement_expected_variant_manifest_missing",
    )
    expected_variants = _field(payload, ("configuration", "expected_variants"))
    if not isinstance(expected_variants, list) or not expected_variants:
        issues.append(
            _validator_issue(
                "settlement_expected_variants_empty",
                "configuration.expected_variants must contain the frozen active variant set",
                field="configuration.expected_variants",
                actual=expected_variants,
            )
        )
    _expect(
        issues,
        payload,
        ("configuration", "expected_partition_contract"),
        "sibling_snapshot_tape",
        code="settlement_expected_snapshot_contract_missing",
    )
    _expect(
        issues,
        payload,
        ("configuration", "aggregate_weighting"),
        "equal_market_day",
        code="settlement_snapshot_weighted_headline_forbidden",
    )
    _expect(
        issues,
        payload,
        ("configuration", "independent_evidence_unit"),
        "market_day_and_fleet_date",
        code="settlement_independent_evidence_unit_invalid",
    )
    _expect_number(
        issues,
        payload,
        ("coverage", "expected_snapshot_partition_count"),
        lambda value: value > 0,
        "greater than 0",
        code="settlement_expected_snapshot_partitions_empty",
    )
    _expect_number(
        issues,
        payload,
        ("coverage", "expected_snapshot_partition_coverage"),
        lambda value: abs(value - 1.0) <= 1e-12,
        "exactly 1.0",
        code="settlement_expected_snapshot_coverage_incomplete",
    )
    _expect_number(
        issues,
        payload,
        ("coverage", "eligible_prediction_coverage"),
        lambda value: abs(value - 1.0) <= 1e-12,
        "exactly 1.0",
        code="live_prediction_coverage_incomplete",
    )
    for field_name in (
        "unsupported_runtime_skip_band_count",
        "unresolved_settlement_partition_count",
        "missing_or_invalid_partition_count",
        "missing_expected_variant_partition_count",
        "missing_expected_snapshot_partition_count",
        "missing_expected_snapshot_band_count",
        "unexpected_variant_snapshot_partition_count",
    ):
        _expect_number(
            issues,
            payload,
            ("coverage", field_name),
            lambda value: value == 0,
            "exactly 0",
            code=f"settlement_{field_name}_nonzero",
        )
    _expect_number(
        issues,
        payload,
        ("coverage", "valid_prediction_partition_count"),
        lambda value: value > 0,
        "greater than 0",
        code="settlement_has_no_valid_partitions",
    )
    return issues


def _validate_parity(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("mode",),
        "captured_input_replay_vs_served_parity",
        code="unknown_replay_parity_mode",
    )
    _expect(
        issues,
        payload,
        ("inputs", "source_contract"),
        "explicit_captured_input_rows",
        code="replay_parity_source_contract_invalid",
    )
    _expect_number(
        issues,
        payload,
        ("summary", "mismatch_count"),
        lambda value: value == 0,
        "exactly 0",
        code="replay_parity_mismatch",
    )
    for field_name in ("compared_row_count", "compared_probability_count"):
        _expect_number(
            issues,
            payload,
            ("summary", field_name),
            lambda value: value > 0,
            "greater than 0",
            code=f"replay_parity_{field_name}_empty",
        )
    max_age = _number(_field(payload, ("inputs", "max_input_age_hours")))
    if max_age is None or max_age <= 0:
        issues.append(
            _validator_issue(
                "replay_parity_input_freshness_contract_missing",
                "inputs.max_input_age_hours must be positive",
            )
        )
    for side in ("served", "replay"):
        records = _field(payload, ("inputs", f"{side}_sources"))
        if not isinstance(records, list) or not records:
            issues.append(
                _validator_issue(
                    f"replay_parity_{side}_sources_missing",
                    f"inputs.{side}_sources must contain explicit hashed source files",
                )
            )
            continue
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                issues.append(
                    _validator_issue(
                        f"replay_parity_{side}_source_invalid",
                        f"inputs.{side}_sources[{index}] must be an object",
                    )
                )
                continue
            if record.get("status") != "PASS":
                issues.append(
                    _validator_issue(
                        f"replay_parity_{side}_source_not_pass",
                        f"inputs.{side}_sources[{index}] must be PASS",
                        source_status=record.get("status"),
                    )
                )
            if not str(record.get("sha256") or "").strip():
                issues.append(
                    _validator_issue(
                        f"replay_parity_{side}_source_hash_missing",
                        f"inputs.{side}_sources[{index}] requires SHA-256 provenance",
                    )
                )
            age = _number(record.get("age_hours"))
            if (
                age is None
                or age < -(5.0 / 60.0)
                or max_age is None
                or age > max_age
            ):
                issues.append(
                    _validator_issue(
                        f"replay_parity_{side}_source_stale",
                        f"inputs.{side}_sources[{index}] is outside the freshness window",
                        age_hours=record.get("age_hours"),
                        max_age_hours=max_age,
                    )
                )
    return issues


def _validate_promotion(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(issues, payload, ("decision",), "PROMOTE", code="promotion_decision_not_promote")
    _expect(issues, payload, ("candidate_only_build",), True, code="promotion_not_candidate_only")
    _expect(issues, payload, ("reviewed",), True, code="promotion_not_reviewed")
    _expect_nonempty(issues, payload, ("reviewed_by",), code="promotion_reviewer_missing")
    return issues


def _validate_rollback(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("evidence_contract",),
        "release_rollback_drill",
        code="unknown_rollback_evidence_contract",
    )
    for field_name in ("rollback_status", "post_rollback_identity_status", "health_status"):
        _expect(issues, payload, (field_name,), "PASS", code=f"rollback_{field_name}_failed")
    _expect_nonempty(
        issues,
        payload,
        ("rollback_target_release_id",),
        code="rollback_target_missing",
    )
    _expect_number(
        issues,
        payload,
        ("rollback_duration_seconds",),
        lambda value: value > 0,
        "greater than 0",
        code="rollback_duration_invalid",
    )
    if payload.get("restored_release_id") != payload.get("release_id"):
        issues.append(
            _validator_issue(
                "rollback_did_not_restore_release",
                "restored_release_id must exactly match release_id",
                release_id=payload.get("release_id"),
                restored_release_id=payload.get("restored_release_id"),
            )
        )
    if payload.get("rollback_target_release_id") == payload.get("release_id"):
        issues.append(
            _validator_issue(
                "rollback_target_equals_release",
                "rollback_target_release_id must differ from release_id",
            )
        )
    return issues


def _validate_fleet(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect_number(
        issues,
        payload,
        ("summary", "market_count"),
        lambda value: value == 12,
        "exactly 12",
        code="fleet_market_count_not_12",
    )
    _expect(
        issues,
        payload,
        ("summary", "critical_alerts"),
        0,
        code="fleet_critical_alerts_present",
    )
    _expect(
        issues,
        payload,
        ("summary", "live_forward_slo_status"),
        "PASS",
        code="fleet_live_forward_slo_failed",
    )
    _expect(
        issues,
        payload,
        ("clean_active_day_countability", "status"),
        "PASS",
        code="fleet_clean_day_failed",
    )
    _expect(
        issues,
        payload,
        ("clean_active_day_countability", "counts_toward_clean_active_day"),
        True,
        code="fleet_day_not_countable",
    )
    _expect_number(
        issues,
        payload,
        ("clean_active_day_countability", "operational_blocker_count"),
        lambda value: value == 0,
        "exactly 0",
        code="fleet_clean_day_blockers_present",
    )
    _expect(
        issues,
        payload,
        ("current_code_soak", "status"),
        "PASS",
        code="fleet_current_code_soak_failed",
    )
    _expect(
        issues,
        payload,
        ("runtime_identity_evidence", "status"),
        "PASS",
        code="fleet_runtime_identity_failed",
    )
    _expect_number(
        issues,
        payload,
        ("runtime_identity_evidence", "runtime_identity_count"),
        lambda value: value == 1,
        "exactly 1",
        code="fleet_runtime_identity_not_singular",
    )
    _expect(
        issues,
        payload,
        ("runtime_identity_evidence", "mixed_runtime_identity"),
        False,
        code="fleet_runtime_identity_mixed",
    )
    _expect(
        issues,
        payload,
        ("runtime_identity_evidence", "reconciliation_applied"),
        False,
        code="fleet_runtime_reconciliation_not_countable",
    )
    _expect_number(
        issues,
        payload,
        ("live_forward_slo", "clob_book_age_p99_seconds"),
        lambda value: value < 120,
        "less than 120",
        code="fleet_clob_p99_too_old",
    )
    _expect_number(
        issues,
        payload,
        ("live_forward_slo", "near_close_clob_book_age_p99_seconds"),
        lambda value: value < 30,
        "less than 30",
        code="fleet_near_close_clob_p99_too_old",
    )
    return issues


def _validate_clean_days(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("evidence_contract",),
        "append_only_clean_day_ledger",
        code="unknown_clean_day_evidence_contract",
    )
    _expect_number(
        issues,
        payload,
        ("summary", "consecutive_clean_active_days"),
        lambda value: value >= 3,
        "at least 3",
        code="insufficient_consecutive_clean_days",
    )
    _expect_number(
        issues,
        payload,
        ("summary", "market_count"),
        lambda value: value == 12,
        "exactly 12",
        code="clean_day_market_count_not_12",
    )
    for field_name in (
        "all_market_days_countable",
        "singular_release_identity",
        "capture_slos_pass",
        "append_only",
    ):
        _expect(
            issues,
            payload,
            ("summary", field_name),
            True,
            code=f"clean_day_{field_name}_failed",
        )
    _expect(
        issues,
        payload,
        ("summary", "ledger_integrity_status"),
        "PASS",
        code="clean_day_ledger_integrity_failed",
    )
    _expect_number(
        issues,
        payload,
        ("summary", "entry_count"),
        lambda value: value >= 3,
        "at least 3",
        code="clean_day_ledger_entries_insufficient",
    )
    _expect_nonempty(
        issues,
        payload,
        ("summary", "entry_chain_sha256"),
        code="clean_day_ledger_chain_missing",
    )
    return issues


def _validate_capture_resource(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("evidence_contract",),
        CAPTURE_RESOURCE_EVIDENCE_CONTRACT,
        code="capture_resource_evidence_contract_invalid",
    )
    _expect(
        issues,
        payload,
        ("safety_contract", "read_only"),
        True,
        code="capture_gate_not_read_only",
    )
    _expect(
        issues,
        payload,
        ("enforcement", "evaluated_before_heavy_work"),
        True,
        code="capture_admission_not_preflighted",
    )
    _expect(
        issues,
        payload,
        ("enforcement", "heavy_child_started_before_decision"),
        False,
        code="capture_heavy_child_started_before_decision",
    )
    _expect(
        issues,
        payload,
        ("enforcement", "proof_persisted"),
        True,
        code="capture_admission_proof_not_persisted",
    )
    workload = str(payload.get("workload") or "")
    if workload not in CAPTURE_RESOURCE_WORKLOADS:
        issues.append(
            _validator_issue(
                "capture_resource_workload_invalid",
                "workload must name an integrated daily or nightly heavy pipeline",
                workload=workload or None,
                expected_workloads=list(CAPTURE_RESOURCE_WORKLOADS),
            )
        )
    consumer = str(_field(payload, ("enforcement", "consumer")) or "")
    if consumer != workload:
        issues.append(
            _validator_issue(
                "capture_resource_consumer_mismatch",
                "enforcement.consumer must match the evaluated workload",
                workload=workload or None,
                consumer=consumer or None,
            )
        )

    capture_mode = str(_field(payload, ("configuration", "capture_mode")) or "")
    if capture_mode == "live":
        _expect(issues, payload, ("status",), "BLOCK", code="live_host_not_blocked")
        _expect(issues, payload, ("admitted",), False, code="live_host_heavy_work_admitted")
        _expect(issues, payload, ("decision",), "DEFER", code="live_host_decision_not_defer")
        _expect(
            issues,
            payload,
            ("enforcement", "outcome"),
            "DEFERRED_BEFORE_HEAVY_WORK",
            code="live_host_defer_not_enforced",
        )
        _expect_number(
            issues,
            payload,
            ("summary", "active_loop_count"),
            lambda value: value >= 1,
            "at least 1",
            code="live_host_active_capture_not_proven",
        )
        blocker_codes = {
            str(row.get("code") or "")
            for row in payload.get("blockers") or []
            if isinstance(row, Mapping)
        }
        if "live_capture_loop_active" not in blocker_codes:
            issues.append(
                _validator_issue(
                    "live_host_capture_denial_reason_missing",
                    "live-host proof must defer because an active capture loop was detected",
                    blocker_codes=sorted(blocker_codes),
                )
            )
    elif capture_mode in {"offline_host", "no_live_capture"}:
        _expect(issues, payload, ("status",), "PASS", code="offline_host_gate_not_passed")
        _expect(issues, payload, ("admitted",), True, code="offline_host_not_admitted")
        _expect(issues, payload, ("decision",), "ADMIT", code="offline_host_decision_not_admit")
        _expect(
            issues,
            payload,
            ("enforcement", "outcome"),
            "ADMITTED_BEFORE_HEAVY_WORK",
            code="offline_host_admission_not_enforced",
        )
        _expect(
            issues,
            payload,
            ("summary", "active_loop_count"),
            0,
            code="offline_host_live_loop_detected",
        )
        _expect(
            issues,
            payload,
            ("summary", "blocker_count"),
            0,
            code="offline_host_resource_blockers_present",
        )
        _expect(
            issues,
            payload,
            ("resources", "memory", "status"),
            "PASS",
            code="capture_memory_headroom_failed",
        )
        _expect(
            issues,
            payload,
            ("resources", "disk", "status"),
            "PASS",
            code="capture_disk_headroom_failed",
        )
    else:
        issues.append(
            _validator_issue(
                "capture_resource_mode_invalid",
                "configuration.capture_mode must explicitly identify a live or offline host",
                capture_mode=capture_mode or None,
            )
        )
    return issues


def _validate_unattended(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("evidence_contract",),
        "append_only_unattended_cycle_ledger",
        code="unknown_unattended_evidence_contract",
    )
    for field_name in (
        "consecutive_unattended_cycles",
        "daily_refresh_pass_count",
        "nightly_pass_count",
    ):
        _expect_number(
            issues,
            payload,
            ("summary", field_name),
            lambda value: value >= 7,
            "at least 7",
            code=f"unattended_{field_name}_insufficient",
        )
    for field_name in (
        "manual_repair_count",
        "stale_lock_count",
        "mixed_target_date_count",
        "unreviewed_promotion_count",
        "inconsistent_input_count",
    ):
        _expect_number(
            issues,
            payload,
            ("summary", field_name),
            lambda value: value == 0,
            "exactly 0",
            code=f"unattended_{field_name}_nonzero",
        )
    _expect_number(
        issues,
        payload,
        ("summary", "inside_sla_count"),
        lambda value: value >= 7,
        "at least 7",
        code="unattended_sla_count_insufficient",
    )
    _expect(
        issues,
        payload,
        ("summary", "ledger_integrity_status"),
        "PASS",
        code="unattended_ledger_integrity_failed",
    )
    _expect_number(
        issues,
        payload,
        ("summary", "entry_count"),
        lambda value: value >= 7,
        "at least 7",
        code="unattended_ledger_entries_insufficient",
    )
    _expect_nonempty(
        issues,
        payload,
        ("summary", "entry_chain_sha256"),
        code="unattended_ledger_chain_missing",
    )
    _expect(
        issues,
        payload,
        ("summary", "append_only"),
        True,
        code="unattended_ledger_not_append_only",
    )
    return issues


def _validate_storage_manifest(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("storage_gate", "status"),
        "PASS",
        code="storage_gate_failed",
    )
    _expect_number(
        issues,
        payload,
        ("summary", "folder_count"),
        lambda value: value > 0,
        "greater than 0",
        code="storage_manifest_inventory_empty",
    )
    folder_count = _number(_field(payload, ("summary", "folder_count")))
    current_count = _number(_field(payload, ("summary", "current_manifest_count")))
    if folder_count is None or current_count is None or current_count != folder_count:
        issues.append(
            _validator_issue(
                "storage_manifests_not_all_current",
                "current_manifest_count must exactly equal folder_count",
                folder_count=folder_count,
                current_manifest_count=current_count,
            )
        )
    for field_name in ("backup_pass_count", "restore_pass_count"):
        actual = _number(_field(payload, ("storage_gate", field_name)))
        if folder_count is None or actual is None or actual != folder_count:
            issues.append(
                _validator_issue(
                    f"storage_{field_name}_incomplete",
                    f"{field_name} must exactly equal folder_count",
                    folder_count=folder_count,
                    actual=actual,
                )
            )
    for field_name in (
        "block_count",
        "missing_manifest_count",
        "changed_manifest_count",
        "unreadable_manifest_count",
        "unclassified_file_count",
    ):
        _expect_number(
            issues,
            payload,
            ("summary", field_name),
            lambda value: value == 0,
            "exactly 0",
            code=f"storage_{field_name}_nonzero",
        )
    for field_name in (
        "backup_block_count",
        "backup_not_configured_count",
        "restore_block_count",
        "restore_not_configured_count",
    ):
        _expect_number(
            issues,
            payload,
            ("storage_gate", field_name),
            lambda value: value == 0,
            "exactly 0",
            code=f"storage_{field_name}_nonzero",
        )
    return issues


def _validate_backup(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("evidence_contract",),
        "off_machine_canonical_backup",
        code="unknown_backup_evidence_contract",
    )
    _expect(issues, payload, ("off_machine",), True, code="backup_not_off_machine")
    _expect(
        issues,
        payload,
        ("checksum_verification_status",),
        "PASS",
        code="backup_checksum_failed",
    )
    _expect(
        issues,
        payload,
        ("required_families_complete",),
        True,
        code="backup_required_families_incomplete",
    )
    _expect_number(
        issues,
        payload,
        ("backed_up_bytes",),
        lambda value: value > 0,
        "greater than 0",
        code="backup_has_no_bytes",
    )
    _expect_nonempty(issues, payload, ("rpo",), code="backup_rpo_missing")
    _expect_nonempty(issues, payload, ("rto",), code="backup_rto_missing")
    _expect_nonempty(issues, payload, ("owner",), code="backup_owner_missing")
    return issues


def _validate_restore(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("evidence_contract",),
        "off_machine_restore_drill",
        code="unknown_restore_evidence_contract",
    )
    for field_name in (
        "checksum_verification_status",
        "representative_market_day_score_status",
        "release_input_reproduction_status",
    ):
        _expect(issues, payload, (field_name,), "PASS", code=f"restore_{field_name}_failed")
    _expect_nonempty(
        issues,
        payload,
        ("representative_target_date",),
        code="restore_target_date_missing",
    )
    return issues


def _validate_headroom(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("mode",),
        "bounded_storage_headroom_probe",
        code="storage_headroom_probe_mode_invalid",
    )
    _expect(
        issues,
        payload,
        ("evidence_contract",),
        "prior_full_inventory_rate_plus_current_disk_free",
        code="storage_headroom_evidence_contract_invalid",
    )
    _expect(issues, payload, ("blocker_count",), 0, code="storage_headroom_probe_blocked")
    _expect(issues, payload, ("root_exists",), True, code="storage_root_missing")
    _expect(
        issues,
        payload,
        ("summary", "filesystem_walk_performed"),
        False,
        code="storage_headroom_unbounded_scan_claimed",
    )
    _expect(
        issues,
        payload,
        ("source_inventory", "trustworthy"),
        True,
        code="storage_headroom_source_untrusted",
    )
    _expect_nonempty(
        issues,
        payload,
        ("source_inventory", "sha256"),
        code="storage_headroom_source_hash_missing",
    )
    _expect_number(
        issues,
        payload,
        ("source_inventory", "age_hours"),
        lambda value: value >= 0,
        "non-negative",
        code="storage_headroom_source_age_invalid",
    )
    _expect_number(
        issues,
        payload,
        ("min_growth_headroom_days",),
        lambda value: value >= 30,
        "at least 30",
        code="headroom_policy_below_30_days",
    )
    _expect_number(
        issues,
        payload,
        ("disk", "daily_recent_bytes"),
        lambda value: value > 0,
        "greater than 0",
        code="storage_observed_write_rate_missing",
    )
    _expect_number(
        issues,
        payload,
        ("disk", "growth_headroom_days"),
        lambda value: value >= 30,
        "at least 30",
        code="storage_headroom_below_30_days",
    )
    return issues


def _validate_challenger(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("evidence_contract",),
        "frozen_challenger_forward_evidence",
        code="unknown_challenger_evidence_contract",
    )
    _expect_number(
        issues,
        payload,
        ("summary", "forward_day_count"),
        lambda value: value >= 7,
        "at least 7",
        code="challenger_forward_days_insufficient",
    )
    _expect_number(
        issues,
        payload,
        ("summary", "countable_market_day_count"),
        lambda value: value >= 84,
        "at least 84",
        code="challenger_market_days_insufficient",
    )
    for field_name in ("brier_delta_vs_current", "log_loss_delta_vs_current"):
        _expect_number(
            issues,
            payload,
            ("summary", field_name),
            lambda value: value < 0,
            "less than 0",
            code=f"challenger_{field_name}_not_better",
        )
    for field_name in (
        "no_material_location_regression",
        "probability_invariants_pass",
        "zero_unsupported_runtime_skips",
    ):
        _expect(
            issues,
            payload,
            ("summary", field_name),
            True,
            code=f"challenger_{field_name}_failed",
        )
    _expect_number(
        issues,
        payload,
        ("summary", "live_prediction_coverage"),
        lambda value: abs(value - 1.0) <= 1e-12,
        "exactly 1.0",
        code="challenger_live_coverage_incomplete",
    )
    _expect(
        issues,
        payload,
        ("summary", "clustered_uncertainty_status"),
        "PASS",
        code="challenger_clustered_uncertainty_failed",
    )
    _expect(
        issues,
        payload,
        ("summary", "replay_parity_status"),
        "PASS",
        code="challenger_replay_parity_failed",
    )
    _expect(
        issues,
        payload,
        ("summary", "hourly_gate_status"),
        "PASS",
        code="challenger_hourly_gate_failed",
    )
    _expect(
        issues,
        payload,
        ("summary", "ten_minute_gate_status"),
        "PASS",
        code="challenger_ten_minute_gate_failed",
    )
    _expect(
        issues,
        payload,
        ("summary", "frozen_release_through_window"),
        True,
        code="challenger_release_not_frozen",
    )
    _expect(
        issues,
        payload,
        ("summary", "route_or_config_change_count"),
        0,
        code="challenger_route_or_config_changed",
    )
    return issues


def _validate_paper(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("evidence_contract",),
        "countable_paper_execution",
        code="unknown_paper_evidence_contract",
    )
    _expect(issues, payload, ("countable",), True, code="paper_evidence_not_countable")
    for field_name in (
        "exchange_economics_status",
        "settlement_reconciliation_status",
        "stricter_child_gate_status",
        "fill_evidence_completeness_status",
    ):
        _expect(issues, payload, (field_name,), "PASS", code=f"paper_{field_name}_failed")
    for field_name in (
        "real_two_sided_depth_used",
        "after_fee_slippage_accounting",
        "current_release_evidence",
    ):
        _expect(issues, payload, (field_name,), True, code=f"paper_{field_name}_failed")
    return issues


def _validate_capital(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _expect(
        issues,
        payload,
        ("evidence_contract",),
        "reviewed_capital_canary_readiness",
        code="unknown_capital_evidence_contract",
    )
    _expect_number(
        issues,
        payload,
        ("second_independent_window", "settled_day_count"),
        lambda value: value >= 14,
        "at least 14",
        code="capital_second_window_insufficient",
    )
    _expect(
        issues,
        payload,
        ("second_independent_window", "independent"),
        True,
        code="capital_second_window_not_independent",
    )
    _expect(issues, payload, ("edge_proof_status",), "PASS", code="capital_edge_proof_failed")
    _expect_number(
        issues,
        payload,
        ("executable_paper_fill_count",),
        lambda value: value >= 100,
        "at least 100",
        code="capital_paper_fills_insufficient",
    )
    _expect_number(
        issues,
        payload,
        ("net_pnl_after_all_costs",),
        lambda value: value > 0,
        "greater than 0",
        code="capital_net_pnl_not_positive",
    )
    for field_name in (
        "clustered_uncertainty_status",
        "market_and_no_trade_benchmark_status",
        "risk_and_reconciliation_controls_status",
        "manual_authorization_status",
    ):
        _expect(issues, payload, (field_name,), "PASS", code=f"capital_{field_name}_failed")
    controls = payload.get("controls")
    controls = controls if isinstance(controls, Mapping) else {}
    for field_name in (
        "authenticated_secret_store",
        "read_only_account_preflight",
        "idempotent_order_keys",
        "place_cancel_replace",
        "private_stream_acknowledgement",
        "position_order_reconciliation",
        "cancel_all_dead_man",
        "tiny_hard_caps",
        "correlated_exposure_limits",
        "health_triggered_demotion",
    ):
        _expect(
            issues,
            controls,
            (field_name,),
            True,
            code=f"capital_control_{field_name}_failed",
        )
    authorization = payload.get("manual_authorization")
    authorization = authorization if isinstance(authorization, Mapping) else {}
    if authorization.get("release_id") != payload.get("release_id"):
        issues.append(
            _validator_issue(
                "capital_authorization_release_mismatch",
                "manual authorization must name the exact evidence release_id",
                authorization_release_id=authorization.get("release_id"),
                release_id=payload.get("release_id"),
            )
        )
    _expect_nonempty(
        issues,
        authorization,
        ("reviewed_by",),
        code="capital_authorization_reviewer_missing",
    )
    _expect_nonempty(
        issues,
        authorization,
        ("account_id",),
        code="capital_authorization_account_missing",
    )
    markets = authorization.get("markets")
    if not isinstance(markets, list) or not markets or any(not str(value).strip() for value in markets):
        issues.append(
            _validator_issue(
                "capital_authorization_markets_missing",
                "manual authorization must name at least one exact market",
            )
        )
    _expect_number(
        issues,
        authorization,
        ("budget",),
        lambda value: value > 0,
        "greater than 0",
        code="capital_authorization_budget_invalid",
    )
    caps = authorization.get("caps")
    if not isinstance(caps, Mapping) or not caps:
        issues.append(
            _validator_issue(
                "capital_authorization_caps_missing",
                "manual authorization must contain explicit non-empty caps",
            )
        )
    expires = _parse_utc(authorization.get("expires_at_utc"))
    if expires is None:
        issues.append(
            _validator_issue(
                "capital_authorization_expiry_invalid",
                "manual authorization requires a timezone-aware expires_at_utc",
            )
        )
    return issues


@dataclass(frozen=True)
class EvidenceSpec:
    name: str
    stage: str
    default_path: Path
    freshness_hours: float
    validator: Callable[[Mapping[str, Any]], list[dict[str, Any]]]
    status_path: tuple[str, ...] = ("status",)
    release_scoped: bool = False
    expected_schema_names: tuple[str, ...] = ()
    timestamp_path: tuple[str, ...] = ("generated_at_utc",)


EVIDENCE_SPECS = (
    EvidenceSpec(
        "live_settlement_scorecard",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "live_variant_settlement_scorecard.json",
        48.0,
        _validate_settlement,
        release_scoped=True,
        expected_schema_names=("live_variant_settlement_scorecard",),
    ),
    EvidenceSpec(
        "replay_parity",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "live_variant_replay_parity.json",
        48.0,
        _validate_parity,
        release_scoped=True,
        expected_schema_names=("live_variant_settlement_scorecard",),
    ),
    EvidenceSpec(
        "promotion_decision",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "release_promotion_decision.json",
        24.0 * 30,
        _validate_promotion,
        status_path=("gate_status",),
        release_scoped=True,
        expected_schema_names=("release_promotion_decision",),
        timestamp_path=("reviewed_at_utc",),
    ),
    EvidenceSpec(
        "rollback_drill",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "release_rollback_drill.json",
        24.0 * 30,
        _validate_rollback,
        release_scoped=True,
        expected_schema_names=("release_rollback_drill",),
    ),
    EvidenceSpec(
        "fleet_observability",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "fleet_observability.json",
        2.0,
        _validate_fleet,
        release_scoped=True,
        expected_schema_names=("fleet_observability",),
    ),
    EvidenceSpec(
        "clean_day_ledger",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "clean_day_ledger.json",
        48.0,
        _validate_clean_days,
        release_scoped=True,
        expected_schema_names=("clean_day_ledger",),
    ),
    EvidenceSpec(
        "capture_resource_gate",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "capture_resource_gate.json",
        2.0,
        _validate_capture_resource,
        status_path=("enforcement", "status"),
        expected_schema_names=("capture_resource_gate",),
    ),
    EvidenceSpec(
        "unattended_cycle_ledger",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "unattended_cycle_ledger.json",
        48.0,
        _validate_unattended,
        release_scoped=True,
        expected_schema_names=("unattended_cycle_ledger",),
    ),
    EvidenceSpec(
        "storage_manifest",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "event_day_manifest_backfill.json",
        48.0,
        _validate_storage_manifest,
        expected_schema_names=("event_day_manifest_backfill",),
    ),
    EvidenceSpec(
        "off_machine_backup",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "off_machine_backup_proof.json",
        24.0 * 30,
        _validate_backup,
        release_scoped=True,
        expected_schema_names=("off_machine_backup_proof",),
    ),
    EvidenceSpec(
        "restore_drill",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "storage_restore_drill.json",
        24.0 * 30,
        _validate_restore,
        release_scoped=True,
        expected_schema_names=("storage_restore_drill",),
    ),
    EvidenceSpec(
        "storage_headroom",
        STAGE_SHADOW,
        DEFAULT_BACKTEST_ROOT / "data_retention_headroom_probe.json",
        24.0,
        _validate_headroom,
        expected_schema_names=("data_retention_headroom_probe",),
    ),
    EvidenceSpec(
        "challenger_forward",
        STAGE_PAPER,
        DEFAULT_BACKTEST_ROOT / "challenger_forward_evidence.json",
        48.0,
        _validate_challenger,
        release_scoped=True,
        expected_schema_names=("challenger_forward_evidence",),
    ),
    EvidenceSpec(
        "paper_execution",
        STAGE_PAPER,
        DEFAULT_BACKTEST_ROOT / "paper_execution_evidence.json",
        48.0,
        _validate_paper,
        release_scoped=True,
        expected_schema_names=("paper_execution_evidence",),
    ),
    EvidenceSpec(
        "capital_canary",
        STAGE_CAPITAL_CANARY,
        DEFAULT_BACKTEST_ROOT / "capital_canary_evidence.json",
        24.0,
        _validate_capital,
        release_scoped=True,
        expected_schema_names=("capital_canary_evidence",),
    ),
)

SPECS_BY_NAME = {spec.name: spec for spec in EVIDENCE_SPECS}


def _input_blocker(
    spec: EvidenceSpec,
    code: str,
    detail: str,
    *,
    next_action: str | None = None,
    **evidence: Any,
) -> dict[str, Any]:
    return {
        "stage": spec.stage,
        "input": spec.name,
        "code": code,
        "detail": detail,
        "next_action": next_action or f"regenerate valid {spec.name} evidence",
        **evidence,
    }


def _read_json_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"), label=str(path))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return None, "evidence must be a JSON object"
    return payload, None


def _load_evidence(
    spec: EvidenceSpec,
    path: Path,
    *,
    now: datetime,
    freshness_hours: float,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    blockers: list[dict[str, Any]] = []
    record: dict[str, Any] = {
        "name": spec.name,
        "required_stage": spec.stage,
        "path": str(path),
        "exists": path.exists(),
        "read_status": "MISSING",
        "sha256": None,
        "schema_version": None,
        "schema_name": None,
        "generated_at_utc": None,
        "age_hours": None,
        "max_age_hours": float(freshness_hours),
        "freshness_status": "UNKNOWN",
        "child_status": None,
        "release_id": None,
        "manifest_sha256": None,
        "validation_status": "BLOCK",
        "blockers": blockers,
    }
    if not path.exists():
        blockers.append(
            _input_blocker(
                spec,
                "missing_evidence",
                f"required evidence file is missing: {path}",
                next_action=f"produce {spec.name} at {path}",
            )
        )
        return record, None
    if not path.is_file() or path.is_symlink():
        record["read_status"] = "REJECTED"
        blockers.append(
            _input_blocker(
                spec,
                "invalid_evidence_path",
                "evidence path must be a regular non-symlink file",
                path=str(path),
            )
        )
        return record, None
    try:
        record["sha256"] = _file_sha256(path)
    except OSError as exc:
        record["read_status"] = "UNREADABLE"
        blockers.append(
            _input_blocker(
                spec,
                "unreadable_evidence",
                f"evidence could not be hashed: {type(exc).__name__}: {exc}",
            )
        )
        return record, None
    payload, error = _read_json_file(path)
    if payload is None:
        record["read_status"] = "UNREADABLE"
        blockers.append(
            _input_blocker(
                spec,
                "unreadable_evidence",
                f"evidence JSON is invalid: {error}",
            )
        )
        return record, None
    record["read_status"] = "PRESENT"

    version = str(payload.get("schema_version") or "").strip()
    schema_name = REGISTERED_SCHEMA_NAMES.get(version)
    record["schema_version"] = version or None
    record["schema_name"] = schema_name
    if not version:
        blockers.append(_input_blocker(spec, "missing_schema_version", "schema_version is required"))
    elif schema_name is None:
        blockers.append(
            _input_blocker(
                spec,
                "unknown_schema_version",
                f"schema_version is not registered: {version}",
                schema_version=version,
            )
        )
    elif spec.expected_schema_names and schema_name not in spec.expected_schema_names:
        blockers.append(
            _input_blocker(
                spec,
                "wrong_evidence_schema",
                "registered schema does not match the required evidence contract",
                schema_name=schema_name,
                expected_schema_names=list(spec.expected_schema_names),
            )
        )

    timestamp_raw = _field(payload, spec.timestamp_path)
    timestamp = _parse_utc(timestamp_raw)
    record["generated_at_utc"] = str(timestamp_raw) if timestamp_raw is not None else None
    if timestamp is None:
        blockers.append(
            _input_blocker(
                spec,
                "missing_or_invalid_evidence_timestamp",
                f"{'.'.join(spec.timestamp_path)} must be a timezone-aware timestamp",
            )
        )
    else:
        age_hours = (now - timestamp).total_seconds() / 3600.0
        record["age_hours"] = age_hours
        if age_hours < -(5.0 / 60.0):
            record["freshness_status"] = "FUTURE"
            blockers.append(
                _input_blocker(
                    spec,
                    "future_evidence",
                    "evidence timestamp is more than five minutes in the future",
                    age_hours=age_hours,
                )
            )
        elif age_hours > float(freshness_hours):
            record["freshness_status"] = "STALE"
            blockers.append(
                _input_blocker(
                    spec,
                    "stale_evidence",
                    "evidence exceeds its declared freshness window",
                    age_hours=age_hours,
                    max_age_hours=float(freshness_hours),
                )
            )
        else:
            record["freshness_status"] = "PASS"

    child_status = _field(payload, spec.status_path)
    record["child_status"] = child_status
    if child_status != "PASS":
        blockers.append(
            _input_blocker(
                spec,
                "child_evidence_not_pass",
                f"{'.'.join(spec.status_path)} must be exactly 'PASS'",
                child_status=child_status,
            )
        )

    release_id, manifest_sha = _explicit_release_identity(payload)
    record["release_id"] = release_id or None
    record["manifest_sha256"] = manifest_sha or None
    if spec.release_scoped:
        if not release_id:
            blockers.append(
                _input_blocker(
                    spec,
                    "missing_release_identity",
                    "release-scoped evidence must explicitly name release_id",
                )
            )
        if not manifest_sha:
            blockers.append(
                _input_blocker(
                    spec,
                    "missing_manifest_identity",
                    "release-scoped evidence must explicitly name manifest_sha256",
                )
            )

    for issue in spec.validator(payload):
        blockers.append(
            _input_blocker(
                spec,
                issue.pop("code"),
                issue.pop("detail"),
                **issue,
            )
        )
    if spec.name == "capital_canary":
        authorization = payload.get("manual_authorization")
        authorization = authorization if isinstance(authorization, Mapping) else {}
        expires = _parse_utc(authorization.get("expires_at_utc"))
        if expires is not None and expires <= now:
            blockers.append(
                _input_blocker(
                    spec,
                    "capital_authorization_expired",
                    "manual capital authorization is expired",
                    expires_at_utc=expires.isoformat(),
                )
            )

    record["validation_status"] = "PASS" if not blockers else "BLOCK"
    return record, payload


def _release_file_record(
    name: str,
    path: Path | None,
    *,
    schema_names: tuple[str, ...] = (),
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    record = {
        "name": name,
        "required_stage": STAGE_SHADOW,
        "path": str(path) if path is not None else None,
        "exists": bool(path and path.exists()),
        "read_status": "MISSING",
        "sha256": None,
        "schema_version": None,
        "schema_name": None,
        "validation_status": "BLOCK",
        "blockers": blockers,
    }
    if path is None or not path.exists():
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": name,
                "code": "missing_release_input",
                "detail": f"required release input is missing: {path}",
                "next_action": f"supply and verify {name}",
            }
        )
        return record, None, blockers
    if not path.is_file() or path.is_symlink():
        record["read_status"] = "REJECTED"
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": name,
                "code": "invalid_release_input_path",
                "detail": "release input must be a regular non-symlink file",
                "next_action": f"replace invalid {name} path",
            }
        )
        return record, None, blockers
    try:
        record["sha256"] = _file_sha256(path)
    except OSError as exc:
        record["read_status"] = "UNREADABLE"
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": name,
                "code": "unreadable_release_input",
                "detail": f"release input could not be hashed: {type(exc).__name__}: {exc}",
                "next_action": f"repair {name}",
            }
        )
        return record, None, blockers
    payload, error = _read_json_file(path)
    if payload is None:
        record["read_status"] = "UNREADABLE"
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": name,
                "code": "unreadable_release_input",
                "detail": f"release input JSON is invalid: {error}",
                "next_action": f"repair {name}",
            }
        )
        return record, None, blockers
    record["read_status"] = "PRESENT"
    version = str(payload.get("schema_version") or "").strip()
    schema_name = REGISTERED_SCHEMA_NAMES.get(version)
    record["schema_version"] = version or None
    record["schema_name"] = schema_name
    if schema_name is None or (schema_names and schema_name not in schema_names):
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": name,
                "code": "unknown_release_input_schema",
                "detail": "release input schema is missing, unregistered, or wrong for this role",
                "next_action": f"regenerate {name} with its registered schema",
                "schema_version": version or None,
                "schema_name": schema_name,
            }
        )
    record["validation_status"] = "PASS" if not blockers else "BLOCK"
    return record, payload, blockers


def _binary_file_record(name: str, path: Path | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    record = {
        "name": name,
        "required_stage": STAGE_SHADOW,
        "path": str(path) if path is not None else None,
        "exists": bool(path and path.exists()),
        "read_status": "MISSING",
        "sha256": None,
        "validation_status": "BLOCK",
        "blockers": blockers,
    }
    if path is None or not path.exists():
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": name,
                "code": "missing_served_binding",
                "detail": f"served binding file is missing: {path}",
                "next_action": "bind every serving-semantic manifest role to its actual loaded file",
            }
        )
        return record, blockers
    if not path.is_file() or path.is_symlink():
        record["read_status"] = "REJECTED"
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": name,
                "code": "invalid_served_binding",
                "detail": "served binding must be a regular non-symlink file",
                "next_action": "repair the served artifact binding",
            }
        )
        return record, blockers
    try:
        record["sha256"] = _file_sha256(path)
    except OSError as exc:
        record["read_status"] = "UNREADABLE"
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": name,
                "code": "unreadable_served_binding",
                "detail": f"served binding could not be hashed: {type(exc).__name__}: {exc}",
                "next_action": "repair the served artifact binding",
            }
        )
        return record, blockers
    record["read_status"] = "PRESENT"
    record["validation_status"] = "PASS"
    return record, blockers


def _verify_active_release(
    *,
    pointer_path: Path,
    releases_root: Path,
    served_artifact_paths: Mapping[str, str | Path],
    served_route_path: Path | None,
    release_resolver: Callable[..., Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    pointer_record, pointer_payload, pointer_blockers = _release_file_record(
        "active_release_pointer",
        pointer_path,
        schema_names=("active_release_pointer",),
    )
    records.append(pointer_record)
    blockers.extend(pointer_blockers)

    route_record, route_payload, route_blockers = _release_file_record(
        "served_route",
        served_route_path,
    )
    # Serving route metadata is part of the release binding, not itself a
    # standalone evidence artifact, so it need not carry a schema version.
    if route_payload is not None:
        schema_only = [row for row in route_blockers if row.get("code") == "unknown_release_input_schema"]
        if schema_only:
            route_blockers[:] = [row for row in route_blockers if row not in schema_only]
            route_record["blockers"] = route_blockers
            route_record["validation_status"] = "PASS" if not route_blockers else "BLOCK"
    records.append(route_record)
    blockers.extend(route_blockers)

    if served_artifact_paths:
        for role, value in sorted(served_artifact_paths.items()):
            artifact_record, artifact_blockers = _binary_file_record(
                f"served_artifact:{role}",
                Path(value),
            )
            records.append(artifact_record)
            blockers.extend(artifact_blockers)
    else:
        missing_record, missing_blockers = _binary_file_record("served_artifact_bindings", None)
        records.append(missing_record)
        blockers.extend(missing_blockers)

    resolved: Mapping[str, Any] | None = None
    resolver_error = None
    try:
        resolved = release_resolver(
            pointer_path=pointer_path,
            releases_root=releases_root,
            served_artifact_paths=served_artifact_paths,
            served_route=route_payload,
            require_served_bindings=True,
        )
    except (ReleaseArtifactVerificationError, OSError, ValueError, TypeError) as exc:
        resolver_error = f"{type(exc).__name__}: {exc}"
    if resolved is None:
        if not pointer_path.exists():
            release_next_action = (
                "build and review a candidate-only immutable release, then atomically promote it "
                "to create the active pointer"
            )
        else:
            release_next_action = (
                "bind actual serving model/calibration/config/route/registry/postprocess files "
                "and re-run verified active-release resolution"
            )
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": "active_release",
                "code": "active_release_verification_failed",
                "detail": resolver_error or "active release resolver returned no verified identity",
                "next_action": release_next_action,
            }
        )
    elif (
        resolved.get("status") != "PASS"
        or resolved.get("served_bindings_verified") is not True
        or not resolved.get("release_id")
        or not resolved.get("manifest_sha256")
        or not isinstance(resolved.get("sequence"), int)
        or int(resolved.get("sequence")) < 1
    ):
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": "active_release",
                "code": "active_release_unknown_status",
                "detail": "resolver must return PASS with verified served bindings and immutable identity",
                "next_action": "repair active release and actual served bindings",
            }
        )
        resolved = None

    manifest_path: Path | None = None
    if resolved and resolved.get("manifest_path"):
        manifest_path = Path(str(resolved["manifest_path"]))
    elif isinstance(pointer_payload, Mapping):
        try:
            release_id = validate_release_id(str(pointer_payload.get("active_release_id") or ""))
            manifest_path = releases_root / release_id / "release_manifest.json"
        except ReleaseArtifactVerificationError:
            manifest_path = None
    manifest_record, manifest_payload, manifest_blockers = _release_file_record(
        "release_manifest",
        manifest_path,
        schema_names=("release_manifest",),
    )
    records.append(manifest_record)
    blockers.extend(manifest_blockers)

    release_identity = {
        "status": "PASS" if resolved and not blockers else "BLOCK",
        "release_id": str(resolved.get("release_id")) if resolved else None,
        "manifest_sha256": str(resolved.get("manifest_sha256")) if resolved else None,
        "pointer_sha256": str(resolved.get("pointer_sha256")) if resolved else None,
        "served_binding_sha256": str(resolved.get("served_binding_sha256")) if resolved else None,
        "pointer_sequence": resolved.get("sequence") if resolved else None,
        "release_kind": resolved.get("release_kind") if resolved else None,
        "candidate_mode": resolved.get("candidate_mode") if resolved else None,
        "production_capable": resolved.get("production_capable") if resolved else False,
        "served_artifact_roles": list(resolved.get("served_artifact_roles") or []) if resolved else [],
        "runtime_checked": resolved.get("runtime_checked") if resolved else None,
        "served_bindings_verified": resolved.get("served_bindings_verified") if resolved else False,
        "pointer_action": pointer_payload.get("action") if isinstance(pointer_payload, Mapping) else None,
        "promotion_decision_sha256": (
            pointer_payload.get("promotion_decision_sha256")
            if isinstance(pointer_payload, Mapping)
            else None
        ),
        "rollback_target_release_id": (
            manifest_payload.get("rollback_target")
            if isinstance(manifest_payload, Mapping)
            else None
        ),
    }
    if resolved and isinstance(pointer_payload, Mapping):
        if pointer_payload.get("active_release_id") != resolved.get("release_id"):
            blockers.append(
                {
                    "stage": STAGE_SHADOW,
                    "input": "active_release_pointer",
                    "code": "resolved_pointer_release_mismatch",
                    "detail": "verified resolver identity disagrees with pointer payload",
                    "next_action": "repair and atomically republish the active release pointer",
                }
            )
        if pointer_payload.get("active_manifest_sha256") != resolved.get("manifest_sha256"):
            blockers.append(
                {
                    "stage": STAGE_SHADOW,
                    "input": "active_release_pointer",
                    "code": "resolved_pointer_manifest_mismatch",
                    "detail": "verified resolver manifest hash disagrees with pointer payload",
                    "next_action": "repair and atomically republish the active release pointer",
                }
            )
    if resolved and isinstance(manifest_payload, Mapping):
        if manifest_payload.get("release_id") != resolved.get("release_id"):
            blockers.append(
                {
                    "stage": STAGE_SHADOW,
                    "input": "release_manifest",
                    "code": "resolved_manifest_release_mismatch",
                    "detail": "verified resolver identity disagrees with manifest payload",
                    "next_action": "rebuild the immutable release",
                }
            )
        if manifest_payload.get("manifest_sha256") != resolved.get("manifest_sha256"):
            blockers.append(
                {
                    "stage": STAGE_SHADOW,
                    "input": "release_manifest",
                    "code": "resolved_manifest_hash_mismatch",
                    "detail": "verified resolver hash disagrees with manifest payload",
                    "next_action": "rebuild the immutable release",
                }
            )
        inventory = _field(manifest_payload, ("artifacts", "inventory"))
        declared_kinds = {
            str(row.get("kind"))
            for row in inventory or []
            if isinstance(row, Mapping) and row.get("declared") is True
        }
        missing_kinds = sorted(REQUIRED_RELEASE_ARTIFACT_KINDS - declared_kinds)
        if missing_kinds:
            blockers.append(
                {
                    "stage": STAGE_SHADOW,
                    "input": "release_manifest",
                    "code": "release_manifest_serving_roles_incomplete",
                    "detail": "release manifest omits required serving-semantic artifact kinds",
                    "next_action": "rebuild the release with every serving-semantic artifact declared",
                    "missing_kinds": missing_kinds,
                }
            )
    if blockers:
        release_identity["status"] = "BLOCK"
    release_records_by_name = {record["name"]: record for record in records}
    for blocker in blockers:
        record = release_records_by_name.get(str(blocker.get("input") or ""))
        if record is not None and blocker not in record["blockers"]:
            record["blockers"].append(blocker)
            record["validation_status"] = "BLOCK"
    return release_identity, records, blockers


def build_production_readiness_gate(
    *,
    evidence_paths: Mapping[str, str | Path] | None = None,
    pointer_path: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    served_artifact_paths: Mapping[str, str | Path] | None = None,
    served_route_path: str | Path | None = None,
    freshness_hours: Mapping[str, float] | None = None,
    now: datetime | None = None,
    release_resolver: Callable[..., Mapping[str, Any]] = resolve_verified_active_release,
) -> dict[str, Any]:
    """Build the parent readiness decision from explicit child artifacts."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    configured_paths = {
        spec.name: Path((evidence_paths or {}).get(spec.name, spec.default_path))
        for spec in EVIDENCE_SPECS
    }
    configured_freshness = {
        spec.name: float((freshness_hours or {}).get(spec.name, spec.freshness_hours))
        for spec in EVIDENCE_SPECS
    }
    invalid_path_names = sorted(set(evidence_paths or {}) - set(SPECS_BY_NAME))
    invalid_freshness_names = sorted(set(freshness_hours or {}) - set(SPECS_BY_NAME))

    release_identity, release_records, release_blockers = _verify_active_release(
        pointer_path=Path(pointer_path),
        releases_root=Path(releases_root),
        served_artifact_paths=served_artifact_paths or {},
        served_route_path=Path(served_route_path) if served_route_path else None,
        release_resolver=release_resolver,
    )
    records = list(release_records)
    blockers = list(release_blockers)
    payloads: dict[str, dict[str, Any]] = {}
    for spec in EVIDENCE_SPECS:
        record, payload = _load_evidence(
            spec,
            configured_paths[spec.name],
            now=current,
            freshness_hours=configured_freshness[spec.name],
        )
        records.append(record)
        blockers.extend(record["blockers"])
        if payload is not None:
            payloads[spec.name] = payload

    scoped_records = {
        record["name"]: record
        for record in records
        if record.get("name") in SPECS_BY_NAME
        and SPECS_BY_NAME[record["name"]].release_scoped
    }
    for identity_field, code in (
        ("release_id", "mixed_release_identities"),
        ("manifest_sha256", "mixed_manifest_identities"),
    ):
        prior_values: set[str] = set()
        for stage in STAGES:
            stage_values = {
                str(record.get(identity_field))
                for name, record in scoped_records.items()
                if SPECS_BY_NAME[name].stage == stage and record.get(identity_field)
            }
            combined = prior_values | stage_values
            if len(combined) > 1 and len(prior_values) <= 1:
                blockers.append(
                    {
                        "stage": stage,
                        "input": "release_identity",
                        "code": code,
                        "detail": (
                            f"release-scoped evidence required through {stage} contains "
                            f"multiple explicit {identity_field} values"
                        ),
                        "next_action": "regenerate every stage input for one exact immutable served release",
                        "values": sorted(combined),
                    }
                )
            prior_values = combined

    if invalid_path_names:
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": "configuration",
                "code": "unknown_evidence_path_names",
                "detail": "evidence_paths contains unknown input names",
                "next_action": "remove unknown evidence path overrides",
                "names": invalid_path_names,
            }
        )
    if invalid_freshness_names:
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": "configuration",
                "code": "unknown_freshness_names",
                "detail": "freshness_hours contains unknown input names",
                "next_action": "remove unknown freshness overrides",
                "names": invalid_freshness_names,
            }
        )

    promotion_payload = payloads.get("promotion_decision")
    pointer_action = release_identity.get("pointer_action")
    if pointer_action == "PROMOTE" and promotion_payload is not None:
        expected_decision_sha = canonical_payload_sha256(promotion_payload)
        if release_identity.get("promotion_decision_sha256") != expected_decision_sha:
            spec = SPECS_BY_NAME["promotion_decision"]
            issue = _input_blocker(
                spec,
                "promotion_decision_pointer_hash_mismatch",
                "promotion decision is not the exact proof hash-linked by the active pointer",
                expected_sha256=release_identity.get("promotion_decision_sha256"),
                actual_sha256=expected_decision_sha,
            )
            blockers.append(issue)
            next(
                record for record in records if record["name"] == "promotion_decision"
            )["blockers"].append(issue)
    elif pointer_action == "ROLLBACK":
        spec = SPECS_BY_NAME["rollback_drill"]
        issue = _input_blocker(
            spec,
            "rollback_pointer_not_proof_linked",
            "the active rollback pointer does not hash-link a persistent rollback drill proof",
            next_action="extend rollback activation to hash-link the reviewed drill/restart/health proof",
        )
        blockers.append(issue)
        next(record for record in records if record["name"] == "rollback_drill")[
            "blockers"
        ].append(issue)
    rollback_payload = payloads.get("rollback_drill")
    if rollback_payload is not None and release_identity.get("status") == "PASS":
        expected_target = release_identity.get("rollback_target_release_id")
        actual_target = rollback_payload.get("rollback_target_release_id")
        if not expected_target or actual_target != expected_target:
            spec = SPECS_BY_NAME["rollback_drill"]
            issue = _input_blocker(
                spec,
                "rollback_target_manifest_mismatch",
                "rollback drill target must exactly match the immutable release manifest",
                expected_rollback_target=expected_target,
                actual_rollback_target=actual_target,
            )
            blockers.append(issue)
            next(record for record in records if record["name"] == "rollback_drill")[
                "blockers"
            ].append(issue)

    expected_release_id = release_identity.get("release_id")
    expected_manifest_sha = release_identity.get("manifest_sha256")
    if release_identity.get("status") == "PASS":
        by_name = {record["name"]: record for record in records}
        for spec in EVIDENCE_SPECS:
            if not spec.release_scoped:
                continue
            record = by_name[spec.name]
            if record.get("release_id") and record.get("release_id") != expected_release_id:
                issue = _input_blocker(
                    spec,
                    "release_identity_mismatch",
                    "evidence release_id does not match the verified active served release",
                    expected_release_id=expected_release_id,
                    actual_release_id=record.get("release_id"),
                )
                record["blockers"].append(issue)
                blockers.append(issue)
            if (
                record.get("manifest_sha256")
                and record.get("manifest_sha256") != expected_manifest_sha
            ):
                issue = _input_blocker(
                    spec,
                    "manifest_identity_mismatch",
                    "evidence manifest_sha256 does not match the verified active release",
                    expected_manifest_sha256=expected_manifest_sha,
                    actual_manifest_sha256=record.get("manifest_sha256"),
                )
                record["blockers"].append(issue)
                blockers.append(issue)
            if record["blockers"]:
                record["validation_status"] = "BLOCK"

    capital_payload = payloads.get("capital_canary") or {}
    if release_identity.get("status") == "PASS" and (
        release_identity.get("production_capable") is not True
    ):
        blockers.append(
            {
                "stage": STAGE_CAPITAL_CANARY,
                "input": "active_release",
                "code": "active_release_not_production_capable",
                "detail": (
                    "the verified active release is serving-identity/bootstrap evidence, "
                    "not a production-capable release"
                ),
                "next_action": (
                    "qualify and promote a production-capable immutable release before "
                    "requesting capital-canary authorization"
                ),
                "release_kind": release_identity.get("release_kind"),
                "candidate_mode": release_identity.get("candidate_mode"),
            }
        )
    capital_authorization = capital_payload.get("manual_authorization")
    capital_authorization = (
        capital_authorization if isinstance(capital_authorization, Mapping) else {}
    )
    if (
        expected_release_id
        and capital_authorization.get("release_id")
        and capital_authorization.get("release_id") != expected_release_id
    ):
        spec = SPECS_BY_NAME["capital_canary"]
        issue = _input_blocker(
            spec,
            "capital_authorization_active_release_mismatch",
            "manual authorization does not name the verified active served release",
            expected_release_id=expected_release_id,
            authorization_release_id=capital_authorization.get("release_id"),
        )
        blockers.append(issue)
        capital_record = next(
            record for record in records if record["name"] == "capital_canary"
        )
        capital_record["blockers"].append(issue)
        capital_record["validation_status"] = "BLOCK"

    blockers.sort(
        key=lambda row: (
            STAGE_ORDER.get(str(row.get("stage")), 99),
            str(row.get("input") or ""),
            str(row.get("code") or ""),
        )
    )
    stage_results: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        stage_rank = STAGE_ORDER[stage]
        stage_blockers = [
            row
            for row in blockers
            if STAGE_ORDER.get(str(row.get("stage")), 99) <= stage_rank
        ]
        stage_results[stage] = {
            "status": "PASS" if not stage_blockers else "BLOCK",
            "blocker_count": len(stage_blockers),
            "first_blocker": stage_blockers[0] if stage_blockers else None,
            "required_inputs": [
                spec.name
                for spec in EVIDENCE_SPECS
                if STAGE_ORDER[spec.stage] <= stage_rank
            ],
        }

    if stage_results[STAGE_CAPITAL_CANARY]["status"] == "PASS":
        stage = STAGE_CAPITAL_CANARY
        next_stage = None
    elif stage_results[STAGE_PAPER]["status"] == "PASS":
        stage = STAGE_PAPER
        next_stage = STAGE_CAPITAL_CANARY
    elif stage_results[STAGE_SHADOW]["status"] == "PASS":
        stage = STAGE_SHADOW
        next_stage = STAGE_PAPER
    else:
        stage = STAGE_NOT_READY
        next_stage = STAGE_SHADOW

    first_blocker = None
    if next_stage:
        next_rank = STAGE_ORDER[next_stage]
        prior_rank = STAGE_ORDER[stage]
        first_blocker = next(
            (
                row
                for row in blockers
                if prior_rank < STAGE_ORDER.get(str(row.get("stage")), 99) <= next_rank
            ),
            None,
        )
    if first_blocker is None and blockers:
        first_blocker = blockers[0]

    input_set_material = [
        {
            "name": record.get("name"),
            "path": record.get("path"),
            "sha256": record.get("sha256"),
            "schema_version": record.get("schema_version"),
            "validation_status": record.get("validation_status"),
            "release_id": record.get("release_id"),
            "manifest_sha256": record.get("manifest_sha256"),
        }
        for record in sorted(records, key=lambda row: str(row.get("name")))
    ]
    output = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(current),
        "status": "PASS" if stage != STAGE_NOT_READY else "BLOCK",
        "stage": stage,
        "highest_permitted_stage": stage,
        "next_stage": next_stage,
        "first_blocker": first_blocker,
        "next_action": (
            first_blocker.get("next_action")
            if first_blocker
            else "retain the exact release and continuously monitor every production gate"
        ),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "release_identity": release_identity,
        "stage_results": stage_results,
        "inputs": records,
        "input_set_sha256": canonical_payload_sha256({"inputs": input_set_material}),
        "configuration": {
            "freshness_hours": configured_freshness,
            "release_identity_contract": "one exact verified served release across every release-scoped input",
            "unknown_or_missing_evidence": "fail_closed",
            "stage_order": list(STAGES),
        },
        "capital_permissions": {
            "credential_access_permitted": False,
            "order_submission_permitted": False,
            "classification_only": True,
            "reason": (
                "this read-only gate never grants credentials or order authority; "
                "a separate exact-release reviewed activation remains required"
            ),
        },
    }
    output["gate_sha256"] = canonical_payload_sha256(output)
    return output


def render_report(payload: Mapping[str, Any]) -> str:
    release = payload.get("release_identity") or {}
    lines = [
        "# Production Readiness Gate",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: `{payload.get('status')}`",
        f"Highest permitted stage: `{payload.get('highest_permitted_stage')}`",
        f"Next stage: `{payload.get('next_stage') or '-'}`",
        f"Release: `{release.get('release_id') or '-'}`",
        f"Manifest: `{release.get('manifest_sha256') or '-'}`",
        f"Input set SHA-256: `{payload.get('input_set_sha256')}`",
        f"Gate SHA-256: `{payload.get('gate_sha256')}`",
        "",
        "## Decision",
        "",
        f"First blocker: `{((payload.get('first_blocker') or {}).get('code') or '-')}`",
        f"Next action: {payload.get('next_action') or '-'}",
        "",
        "## Stage Gates",
        "",
        "| Stage | Status | Blockers | First blocker |",
        "| --- | --- | ---: | --- |",
    ]
    for stage in STAGES:
        row = (payload.get("stage_results") or {}).get(stage) or {}
        lines.append(
            "| {stage} | {status} | {count} | {first} |".format(
                stage=stage,
                status=row.get("status") or "-",
                count=row.get("blocker_count") or 0,
                first=((row.get("first_blocker") or {}).get("code") or "-"),
            )
        )
    lines.extend(
        [
            "",
            "## Evidence Inputs",
            "",
            "| Input | Required stage | Read | Freshness | Validation | Release | SHA-256 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in payload.get("inputs") or []:
        lines.append(
            "| {name} | {stage} | {read} | {freshness} | {validation} | {release} | {sha} |".format(
                name=row.get("name") or "-",
                stage=row.get("required_stage") or "-",
                read=row.get("read_status") or "-",
                freshness=row.get("freshness_status") or "-",
                validation=row.get("validation_status") or "-",
                release=row.get("release_id") or "-",
                sha=row.get("sha256") or "-",
            )
        )
    lines.extend(
        [
            "",
            "## Blockers",
            "",
            "| Stage | Input | Code | Detail | Next action |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in payload.get("blockers") or []:
        lines.append(
            "| {stage} | {input_name} | {code} | {detail} | {action} |".format(
                stage=row.get("stage") or "-",
                input_name=row.get("input") or "-",
                code=row.get("code") or "-",
                detail=str(row.get("detail") or "-").replace("|", "\\|"),
                action=str(row.get("next_action") or "-").replace("|", "\\|"),
            )
        )
    permissions = payload.get("capital_permissions") or {}
    lines.extend(
        [
            "",
            "## Capital Authority",
            "",
            f"Credential access permitted: `{permissions.get('credential_access_permitted')}`",
            f"Order submission permitted: `{permissions.get('order_submission_permitted')}`",
            "",
            str(permissions.get("reason") or ""),
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write_text(path: str | Path, text: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        try:
            directory_fd = os.open(output.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_outputs(
    payload: Mapping[str, Any],
    *,
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> None:
    _atomic_write_text(
        json_out,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
    )
    _atomic_write_text(report_out, render_report(payload))


def _resolved_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _assert_safe_readiness_outputs(
    *,
    json_out: str | Path,
    report_out: str | Path,
    pointer_path: str | Path,
    releases_root: str | Path,
    evidence_paths: Mapping[str, str | Path],
    served_artifact_paths: Mapping[str, str | Path],
    served_route_path: str | Path | None,
) -> tuple[Path, Path]:
    """Reject any status output capable of overwriting production inputs."""

    json_path = _resolved_path(json_out)
    report_path = _resolved_path(report_out)
    if json_path == report_path:
        raise ValueError("production readiness JSON and report outputs must be distinct")
    release_root = _resolved_path(releases_root)
    protected = {
        _resolved_path(pointer_path): "active release pointer",
        **{
            _resolved_path(path): f"evidence input {name}"
            for name, path in evidence_paths.items()
        },
        **{
            _resolved_path(path): f"served artifact {role}"
            for role, path in served_artifact_paths.items()
        },
    }
    if served_route_path:
        protected[_resolved_path(served_route_path)] = "served route"
    for output_name, output_path in (("json_out", json_path), ("report_out", report_path)):
        if output_path == release_root or output_path.is_relative_to(release_root):
            raise ValueError(
                f"unsafe production readiness {output_name}: output is inside the immutable release tree"
            )
        if output_path in protected:
            raise ValueError(
                f"unsafe production readiness {output_name}: output collides with {protected[output_path]}"
            )
    return json_path, report_path


def _pointer_snapshot(path: str | Path) -> dict[str, Any]:
    pointer = Path(path)
    snapshot = {
        "path": str(pointer),
        "exists": pointer.exists(),
        "is_file": pointer.is_file(),
        "is_symlink": pointer.is_symlink(),
        "sha256": None,
        "bytes": None,
        "error": None,
    }
    if pointer.exists() and pointer.is_file() and not pointer.is_symlink():
        try:
            snapshot["sha256"] = _file_sha256(pointer)
            snapshot["bytes"] = pointer.stat().st_size
        except OSError as exc:
            snapshot["error"] = f"{type(exc).__name__}: {exc}"
    return snapshot


def _pointer_snapshots_equal(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    fields = ("exists", "is_file", "is_symlink", "sha256", "bytes", "error")
    return all(before.get(field) == after.get(field) for field in fields)


def _attest_pointer_unchanged(
    payload: dict[str, Any],
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    checked_after_persistence: bool,
) -> dict[str, Any]:
    """Attach truthful pointer evidence and force NOT_READY on any mutation."""

    unchanged = _pointer_snapshots_equal(before, after)
    mutation_code = "readiness_pointer_mutated_during_evaluation"
    blockers = [
        dict(row)
        for row in payload.get("blockers") or []
        if row.get("code") != mutation_code
    ]
    if not unchanged:
        blockers.append(
            {
                "stage": STAGE_SHADOW,
                "input": "active_release_pointer",
                "code": mutation_code,
                "detail": "the active release pointer changed while the read-only gate was running",
                "next_action": "stop concurrent pointer writers, verify the active release, and rerun readiness",
                "before_sha256": before.get("sha256"),
                "after_sha256": after.get("sha256"),
            }
        )
    blockers.sort(
        key=lambda row: (
            STAGE_ORDER.get(str(row.get("stage")), 99),
            str(row.get("input") or ""),
            str(row.get("code") or ""),
        )
    )
    payload["blockers"] = blockers
    payload["blocker_count"] = len(blockers)
    payload["read_only_attestation"] = {
        "status": "PASS" if unchanged else "BLOCK",
        "pointer_path": before.get("path"),
        "pointer_before": dict(before),
        "pointer_after": dict(after),
        "pointer_unchanged": unchanged,
        "pointer_mutated": not unchanged,
        "checked_after_persistence": bool(checked_after_persistence),
    }
    if not unchanged:
        payload["status"] = "BLOCK"
        payload["stage"] = STAGE_NOT_READY
        payload["highest_permitted_stage"] = STAGE_NOT_READY
        payload["next_stage"] = STAGE_SHADOW
        payload["first_blocker"] = next(
            row for row in blockers if row.get("code") == mutation_code
        )
        payload["next_action"] = payload["first_blocker"]["next_action"]
        if isinstance(payload.get("release_identity"), dict):
            payload["release_identity"]["status"] = "BLOCK"
        for stage in STAGES:
            prior = (payload.get("stage_results") or {}).get(stage) or {}
            stage_rank = STAGE_ORDER[stage]
            stage_blockers = [
                row
                for row in blockers
                if STAGE_ORDER.get(str(row.get("stage")), 99) <= stage_rank
            ]
            payload.setdefault("stage_results", {})[stage] = {
                **prior,
                "status": "BLOCK",
                "blocker_count": len(stage_blockers),
                "first_blocker": stage_blockers[0] if stage_blockers else None,
            }
    payload["gate_sha256"] = canonical_payload_sha256(
        payload,
        omit=("gate_sha256",),
    )
    return payload


def evidence_paths_for_root(
    backtest_root: str | Path,
    overrides: Mapping[str, str | Path] | None = None,
) -> dict[str, Path]:
    """Map every canonical child evidence name into one pipeline data root."""

    root = Path(backtest_root)
    configured = overrides or {}
    mapped = {
        spec.name: Path(configured.get(spec.name, root / spec.default_path.name))
        for spec in EVIDENCE_SPECS
    }
    mapped.update(
        {
            str(name): Path(path)
            for name, path in configured.items()
            if name not in mapped
        }
    )
    return mapped


def build_and_write_production_readiness_status(
    *,
    backtest_root: str | Path = DEFAULT_BACKTEST_ROOT,
    evidence_paths: Mapping[str, str | Path] | None = None,
    json_out: str | Path | None = None,
    report_out: str | Path | None = None,
    **gate_kwargs: Any,
) -> tuple[dict[str, Any], Path, Path]:
    """Persist the canonical parent gate as a read-only pipeline status step."""

    root = Path(backtest_root)
    mapped_evidence = evidence_paths_for_root(root, evidence_paths)
    pointer_path = gate_kwargs.get("pointer_path", DEFAULT_ACTIVE_RELEASE_POINTER)
    releases_root = gate_kwargs.get("releases_root", DEFAULT_RELEASES_ROOT)
    served_artifacts = gate_kwargs.get("served_artifact_paths") or {}
    served_route = gate_kwargs.get("served_route_path")
    json_path, report_path = _assert_safe_readiness_outputs(
        json_out=json_out or root / DEFAULT_JSON_OUT.name,
        report_out=report_out or root / DEFAULT_REPORT_OUT.name,
        pointer_path=pointer_path,
        releases_root=releases_root,
        evidence_paths=mapped_evidence,
        served_artifact_paths=served_artifacts,
        served_route_path=served_route,
    )
    pointer_before = _pointer_snapshot(pointer_path)
    payload = build_production_readiness_gate(
        evidence_paths=mapped_evidence,
        **gate_kwargs,
    )
    payload = _attest_pointer_unchanged(
        payload,
        before=pointer_before,
        after=_pointer_snapshot(pointer_path),
        checked_after_persistence=False,
    )
    write_outputs(payload, json_out=json_path, report_out=report_path)
    payload = _attest_pointer_unchanged(
        payload,
        before=pointer_before,
        after=_pointer_snapshot(pointer_path),
        checked_after_persistence=True,
    )
    write_outputs(payload, json_out=json_path, report_out=report_path)
    return payload, json_path, report_path


def _parse_name_values(
    values: Sequence[str],
    *,
    value_parser: Callable[[str], Any] = str,
) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected NAME=VALUE, found {value!r}")
        name, raw = value.split("=", 1)
        name = name.strip()
        if not name or name in parsed:
            raise ValueError(f"invalid or duplicate name in {value!r}")
        parsed[name] = value_parser(raw)
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the hash-linked fail-closed Item 321 production readiness parent gate."
    )
    for spec in EVIDENCE_SPECS:
        parser.add_argument(
            f"--{spec.name.replace('_', '-')}",
            default=str(spec.default_path),
            help=f"Path to {spec.name} evidence.",
        )
    parser.add_argument("--active-pointer", default=str(DEFAULT_ACTIVE_RELEASE_POINTER))
    parser.add_argument("--releases-root", default=str(DEFAULT_RELEASES_ROOT))
    parser.add_argument(
        "--served-artifact",
        action="append",
        default=[],
        metavar="ROLE=PATH",
        help="Actual serving artifact binding; repeat for every manifest serving role.",
    )
    parser.add_argument(
        "--served-route",
        default="",
        help="JSON file containing the actual route metadata used by serving.",
    )
    parser.add_argument(
        "--freshness-hours",
        action="append",
        default=[],
        metavar="INPUT=HOURS",
        help="Override one predeclared evidence freshness window.",
    )
    parser.add_argument("--now", default="", help="Timezone-aware evaluation time (tests/replay).")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--fail-on-block", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        served_artifacts = _parse_name_values(args.served_artifact, value_parser=Path)
        freshness = _parse_name_values(args.freshness_hours, value_parser=float)
    except ValueError as exc:
        parser.error(str(exc))
    now = _parse_utc(args.now) if args.now else None
    if args.now and now is None:
        parser.error("--now must be a timezone-aware ISO-8601 timestamp")
    evidence_paths = {
        spec.name: Path(getattr(args, spec.name))
        for spec in EVIDENCE_SPECS
    }
    payload, _json_path, _report_path = build_and_write_production_readiness_status(
        backtest_root=Path(args.json_out).parent,
        evidence_paths=evidence_paths,
        pointer_path=args.active_pointer,
        releases_root=args.releases_root,
        served_artifact_paths=served_artifacts,
        served_route_path=args.served_route or None,
        freshness_hours=freshness,
        now=now,
        json_out=args.json_out,
        report_out=args.report_out,
    )
    print(
        "Production readiness: status={status} stage={stage} blockers={blockers} next={next_action}".format(
            status=payload["status"],
            stage=payload["stage"],
            blockers=payload["blocker_count"],
            next_action=payload["next_action"],
        )
    )
    if args.fail_on_block and payload["status"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
