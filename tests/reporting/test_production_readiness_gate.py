from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.market.live_taker_canary import (
    CAPITAL_CEILING_USDC,
    RISK_CAPS,
    RISK_CAPS_SHA256,
    RISK_POLICY_ID,
    RISK_POLICY_SHA256,
)
from weather.operations.capture_resource_gate import (
    DAILY_REFRESH_WORKLOAD,
    EVIDENCE_CONTRACT as CAPTURE_RESOURCE_EVIDENCE_CONTRACT,
)
from weather.release_artifacts import ReleaseArtifactVerificationError, canonical_payload_sha256
from weather.release_contract import (
    PRODUCTION_CANDIDATE_MODE,
    PRODUCTION_RELEASE_KIND,
    RESEARCH_ONLY_CANDIDATE_MODE,
    SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
)
from weather.reporting.serving_gates.production_readiness_gate import (
    EVIDENCE_SPECS,
    STAGE_CAPITAL_CANARY,
    STAGE_NOT_READY,
    STAGE_PAPER,
    STAGE_SHADOW,
    build_production_readiness_gate,
    build_and_write_production_readiness_status,
    main,
    write_outputs,
)
from weather.schema_registry import schema_version


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
RELEASE_ID = "release-321"
MANIFEST_SHA = "a" * 64


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _base(schema_name: str, *, release_scoped: bool = False) -> dict:
    payload = {
        "schema_version": schema_version(schema_name),
        "generated_at_utc": NOW.isoformat(),
        "status": "PASS",
    }
    if release_scoped:
        payload.update({"release_id": RELEASE_ID, "manifest_sha256": MANIFEST_SHA})
    return payload


def _evidence_payload(name: str) -> dict:
    if name == "live_settlement_scorecard":
        return {
            **_base("live_variant_settlement_scorecard", release_scoped=True),
            "blocker_count": 0,
            "configuration": {
                "require_explicit_release_id": True,
                "expected_variant_contract": "explicit_manifest",
                "expected_partition_contract": "sibling_snapshot_tape",
                "aggregate_weighting": "equal_market_day",
                "independent_evidence_unit": "market_day_and_fleet_date",
                "expected_variants": [
                    {
                        "variant_id": "candidate",
                        "evidence_lane": "weather_only",
                        "release_id": RELEASE_ID,
                    }
                ],
            },
            "coverage": {
                "eligible_prediction_coverage": 1.0,
                "unsupported_runtime_skip_band_count": 0,
                "unresolved_settlement_partition_count": 0,
                "missing_or_invalid_partition_count": 0,
                "missing_expected_variant_partition_count": 0,
                "expected_snapshot_partition_count": 84,
                "expected_snapshot_partition_coverage": 1.0,
                "missing_expected_snapshot_partition_count": 0,
                "missing_expected_snapshot_band_count": 0,
                "unexpected_variant_snapshot_partition_count": 0,
                "valid_prediction_partition_count": 84,
            },
        }
    if name == "replay_parity":
        return {
            **_base("live_variant_settlement_scorecard", release_scoped=True),
            "mode": "captured_input_replay_vs_served_parity",
            "inputs": {
                "source_contract": "explicit_captured_input_rows",
                "max_input_age_hours": 48.0,
                "served_sources": [
                    {"status": "PASS", "sha256": "1" * 64, "age_hours": 1.0}
                ],
                "replay_sources": [
                    {"status": "PASS", "sha256": "2" * 64, "age_hours": 1.0}
                ],
            },
            "summary": {
                "mismatch_count": 0,
                "compared_row_count": 100,
                "compared_probability_count": 100,
            },
        }
    if name == "promotion_decision":
        return {
            "schema_version": schema_version("release_promotion_decision"),
            "release_id": RELEASE_ID,
            "manifest_sha256": MANIFEST_SHA,
            "decision": "PROMOTE",
            "gate_status": "PASS",
            "candidate_only_build": True,
            "reviewed": True,
            "reviewed_by": "operator",
            "reviewed_at_utc": NOW.isoformat(),
        }
    if name == "rollback_drill":
        return {
            **_base("release_rollback_drill", release_scoped=True),
            "evidence_contract": "release_rollback_drill",
            "rollback_status": "PASS",
            "post_rollback_identity_status": "PASS",
            "health_status": "PASS",
            "rollback_target_release_id": "release-previous",
            "rollback_duration_seconds": 15.0,
            "restored_release_id": RELEASE_ID,
        }
    if name == "fleet_observability":
        return {
            **_base("fleet_observability", release_scoped=True),
            "summary": {
                "market_count": 12,
                "critical_alerts": 0,
                "live_forward_slo_status": "PASS",
            },
            "clean_active_day_countability": {
                "status": "PASS",
                "counts_toward_clean_active_day": True,
                "operational_blocker_count": 0,
            },
            "current_code_soak": {"status": "PASS"},
            "runtime_identity_evidence": {
                "status": "PASS",
                "runtime_identity_count": 1,
                "mixed_runtime_identity": False,
                "reconciliation_applied": False,
            },
            "live_forward_slo": {
                "clob_book_age_p99_seconds": 60.0,
                "near_close_clob_book_age_p99_seconds": 15.0,
            },
        }
    if name == "clean_day_ledger":
        return {
            **_base("clean_day_ledger", release_scoped=True),
            "evidence_contract": "append_only_clean_day_ledger",
            "summary": {
                "consecutive_clean_active_days": 3,
                "market_count": 12,
                "all_market_days_countable": True,
                "singular_release_identity": True,
                "capture_slos_pass": True,
                "append_only": True,
                "ledger_integrity_status": "PASS",
                "entry_count": 3,
                "entry_chain_sha256": "1" * 64,
            },
        }
    if name == "capture_resource_gate":
        return {
            **_base("capture_resource_gate"),
            "evidence_contract": CAPTURE_RESOURCE_EVIDENCE_CONTRACT,
            "status": "BLOCK",
            "decision": "DEFER",
            "workload": DAILY_REFRESH_WORKLOAD,
            "configuration": {"capture_mode": "live"},
            "safety_contract": {"read_only": True},
            "admitted": False,
            "summary": {"active_loop_count": 2, "blocker_count": 2},
            "blockers": [
                {
                    "code": "live_capture_loop_active",
                    "evidence": {"loop": "snapshot"},
                },
                {
                    "code": "live_capture_loop_active",
                    "evidence": {"loop": "observation_trigger"},
                },
            ],
            "enforcement": {
                "status": "PASS",
                "consumer": DAILY_REFRESH_WORKLOAD,
                "evaluated_before_heavy_work": True,
                "heavy_child_started_before_decision": False,
                "outcome": "DEFERRED_BEFORE_HEAVY_WORK",
                "proof_persisted": True,
            },
            "resources": {"memory": {"status": "PASS"}, "disk": {"status": "PASS"}},
        }
    if name == "unattended_cycle_ledger":
        return {
            **_base("unattended_cycle_ledger", release_scoped=True),
            "evidence_contract": "append_only_unattended_cycle_ledger",
            "summary": {
                "consecutive_unattended_cycles": 7,
                "daily_refresh_pass_count": 7,
                "nightly_pass_count": 7,
                "manual_repair_count": 0,
                "stale_lock_count": 0,
                "mixed_target_date_count": 0,
                "unreviewed_promotion_count": 0,
                "inconsistent_input_count": 0,
                "append_only": True,
                "inside_sla_count": 7,
                "ledger_integrity_status": "PASS",
                "entry_count": 7,
                "entry_chain_sha256": "2" * 64,
            },
        }
    if name == "storage_manifest":
        return {
            **_base("event_day_manifest_backfill"),
            "storage_gate": {
                "status": "PASS",
                "backup_pass_count": 36,
                "restore_pass_count": 36,
                "backup_block_count": 0,
                "backup_not_configured_count": 0,
                "restore_block_count": 0,
                "restore_not_configured_count": 0,
            },
            "summary": {
                "folder_count": 36,
                "current_manifest_count": 36,
                "block_count": 0,
                "missing_manifest_count": 0,
                "changed_manifest_count": 0,
                "unreadable_manifest_count": 0,
                "unclassified_file_count": 0,
            },
        }
    if name == "off_machine_backup":
        return {
            **_base("off_machine_backup_proof", release_scoped=True),
            "evidence_contract": "off_machine_canonical_backup",
            "off_machine": True,
            "checksum_verification_status": "PASS",
            "required_families_complete": True,
            "backed_up_bytes": 1000,
            "rpo": "24h",
            "rto": "4h",
            "owner": "ops",
        }
    if name == "restore_drill":
        return {
            **_base("storage_restore_drill", release_scoped=True),
            "evidence_contract": "off_machine_restore_drill",
            "checksum_verification_status": "PASS",
            "representative_market_day_score_status": "PASS",
            "release_input_reproduction_status": "PASS",
            "representative_target_date": "2026-07-10",
        }
    if name == "storage_headroom":
        return {
            **_base("data_retention_headroom_probe"),
            "mode": "bounded_storage_headroom_probe",
            "evidence_contract": "prior_full_inventory_rate_plus_current_disk_free",
            "blocker_count": 0,
            "root_exists": True,
            "min_growth_headroom_days": 30.0,
            "summary": {"filesystem_walk_performed": False},
            "source_inventory": {
                "trustworthy": True,
                "sha256": "a" * 64,
                "age_hours": 1.0,
            },
            "disk": {"daily_recent_bytes": 1000, "growth_headroom_days": 45.0},
        }
    if name == "challenger_forward":
        return {
            **_base("challenger_forward_evidence", release_scoped=True),
            "evidence_contract": "frozen_challenger_forward_evidence",
            "summary": {
                "forward_day_count": 7,
                "countable_market_day_count": 84,
                "brier_delta_vs_current": -0.01,
                "log_loss_delta_vs_current": -0.02,
                "no_material_location_regression": True,
                "probability_invariants_pass": True,
                "zero_unsupported_runtime_skips": True,
                "live_prediction_coverage": 1.0,
                "clustered_uncertainty_status": "PASS",
                "replay_parity_status": "PASS",
                "hourly_gate_status": "PASS",
                "ten_minute_gate_status": "PASS",
                "frozen_release_through_window": True,
                "route_or_config_change_count": 0,
            },
        }
    if name == "paper_execution":
        return {
            **_base("paper_execution_evidence", release_scoped=True),
            "evidence_contract": "countable_paper_execution",
            "countable": True,
            "exchange_economics_status": "PASS",
            "settlement_reconciliation_status": "PASS",
            "stricter_child_gate_status": "PASS",
            "fill_evidence_completeness_status": "PASS",
            "real_two_sided_depth_used": True,
            "after_fee_slippage_accounting": True,
            "current_release_evidence": True,
        }
    if name == "capital_canary":
        controls = {
            "authenticated_secret_store": True,
            "read_only_account_preflight": True,
            "idempotent_order_keys": True,
            "order_lifecycle_mode": "fok_one_shot_no_replace",
            "place_order": True,
            "cancel_order": True,
            "replace_order": False,
            "replace_disabled_for_fok": True,
            "private_stream_acknowledgement": True,
            "position_order_reconciliation": True,
            "cancel_all_dead_man": True,
            "tiny_hard_caps": True,
            "correlated_exposure_limits": True,
            "health_triggered_demotion": True,
        }
        return {
            **_base("capital_canary_evidence", release_scoped=True),
            "evidence_contract": "reviewed_capital_canary_readiness",
            "second_independent_window": {"settled_day_count": 14, "independent": True},
            "edge_proof_status": "PASS",
            "executable_paper_fill_count": 100,
            "net_pnl_after_all_costs": 1.0,
            "clustered_uncertainty_status": "PASS",
            "market_and_no_trade_benchmark_status": "PASS",
            "risk_and_reconciliation_controls_status": "PASS",
            "manual_authorization_status": "PASS",
            "controls": controls,
            "control_evidence": {
                field_name: {
                    "path": f"capital_controls/{field_name}.json",
                    "sha256": "c" * 64,
                }
                for field_name in controls
            },
            "manual_authorization": {
                "activation_id": "canary-2026-07",
                "platform": "polymarket_global",
                "release_id": RELEASE_ID,
                "manifest_sha256": MANIFEST_SHA,
                "reviewed_by": "risk-operator",
                "account_id_sha256": "b" * 64,
                "market_ids": ["toronto"],
                "capital_ceiling_usdc": CAPITAL_CEILING_USDC,
                "risk_policy_id": RISK_POLICY_ID,
                "risk_policy_sha256": RISK_POLICY_SHA256,
                "risk_caps": dict(RISK_CAPS),
                "risk_caps_sha256": RISK_CAPS_SHA256,
                "authorized_at_utc": (NOW - timedelta(hours=1)).isoformat(),
                "expires_at_utc": (NOW + timedelta(days=1)).isoformat(),
            },
        }
    raise AssertionError(name)


def _full_fixture(tmp_path: Path) -> dict:
    evidence_paths = {}
    for spec in EVIDENCE_SPECS:
        evidence_payload = _evidence_payload(spec.name)
        if spec.name == "capital_canary":
            for control, evidence_ref in evidence_payload["control_evidence"].items():
                verification = {
                    "assertion_count": 1,
                    "failure_count": 0,
                    "producer": "synthetic-capital-control-verifier",
                }
                proof_path = _write_json(
                    tmp_path / evidence_ref["path"],
                    {
                        "evidence_contract": "reviewed_capital_control_v1",
                        "control": control,
                        "asserted_value": evidence_payload["controls"][control],
                        "status": "PASS",
                        "generated_at_utc": NOW.isoformat(),
                        "reviewed_by": "risk-operator",
                        "evidence": verification,
                        "evidence_sha256": canonical_payload_sha256(verification),
                    },
                )
                evidence_ref["sha256"] = hashlib.sha256(
                    proof_path.read_bytes()
                ).hexdigest()
        evidence_paths[spec.name] = _write_json(
            tmp_path / f"{spec.name}.json",
            evidence_payload,
        )
    releases_root = tmp_path / "releases"
    manifest_path = releases_root / RELEASE_ID / "release_manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": schema_version("release_manifest"),
            "release_id": RELEASE_ID,
            "manifest_sha256": MANIFEST_SHA,
            "rollback_target": "release-previous",
            "artifacts": {
                "inventory": [
                    {"declared": True, "kind": kind}
                    for kind in (
                        "model",
                        "calibration",
                        "config",
                        "imputer",
                        "feature_schema",
                        "postprocessor",
                        "route",
                        "registry",
                        "settlement_rules",
                    )
                ]
            },
        },
    )
    promotion_payload = json.loads(
        Path(evidence_paths["promotion_decision"]).read_text(encoding="utf-8")
    )
    pointer_path = _write_json(
        releases_root / "current_release.json",
        {
            "schema_version": schema_version("active_release_pointer"),
            "action": "PROMOTE",
            "active_release_id": RELEASE_ID,
            "active_manifest_sha256": MANIFEST_SHA,
            "promotion_decision_sha256": canonical_payload_sha256(promotion_payload),
        },
    )
    route_path = _write_json(tmp_path / "served_route.json", {"route_id": "route-1"})
    model_path = tmp_path / "served-model.bin"
    model_path.write_bytes(b"model")

    def resolver(**_kwargs):
        return {
            "status": "PASS",
            "release_id": RELEASE_ID,
            "manifest_path": str(manifest_path),
            "manifest_sha256": MANIFEST_SHA,
            "pointer_sha256": "b" * 64,
            "sequence": 1,
            "release_kind": PRODUCTION_RELEASE_KIND,
            "candidate_mode": PRODUCTION_CANDIDATE_MODE,
            "production_capable": True,
            "served_binding_sha256": "c" * 64,
            "served_bindings_verified": True,
            "served_artifact_roles": ["model"],
            "runtime_checked": True,
        }

    return {
        "evidence_paths": evidence_paths,
        "pointer_path": pointer_path,
        "releases_root": releases_root,
        "served_artifact_paths": {"model": model_path},
        "served_route_path": route_path,
        "release_resolver": resolver,
        "now": NOW,
    }


def test_full_synthetic_contract_classifies_capital_but_never_grants_permissions(tmp_path):
    payload = build_production_readiness_gate(**_full_fixture(tmp_path))

    assert payload["status"] == "PASS"
    assert payload["stage"] == STAGE_CAPITAL_CANARY
    assert payload["blocker_count"] == 0
    assert payload["release_identity"]["release_id"] == RELEASE_ID
    assert payload["capital_permissions"]["credential_access_permitted"] is False
    assert payload["capital_permissions"]["order_submission_permitted"] is False
    binding = payload["capital_authorization_binding"]
    assert binding["status"] == "PASS"
    assert binding["scope"]["account_id_sha256"] == "b" * 64
    assert binding["scope"]["capital_ceiling_usdc"] == CAPITAL_CEILING_USDC
    assert binding["scope_sha256"] == canonical_payload_sha256(binding["scope"])
    assert all(row["sha256"] for row in payload["inputs"])
    assert payload["gate_sha256"] == canonical_payload_sha256(
        payload,
        omit=("gate_sha256",),
    )


def test_capital_order_lifecycle_requires_fok_without_replace_and_hashed_proof(tmp_path):
    fixture = _full_fixture(tmp_path)
    path = Path(fixture["evidence_paths"]["capital_canary"])
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["controls"]["order_lifecycle_mode"] = "place_cancel_replace"
    evidence["controls"]["replace_order"] = True
    evidence["controls"]["replace_disabled_for_fok"] = False
    evidence["control_evidence"].pop("cancel_all_dead_man")
    _write_json(path, evidence)

    payload = build_production_readiness_gate(**fixture)
    codes = {row["code"] for row in payload["blockers"]}

    assert payload["stage"] == STAGE_PAPER
    assert "capital_control_order_lifecycle_mode_failed" in codes
    assert "capital_control_replace_order_must_be_disabled" in codes
    assert "capital_control_replace_disabled_for_fok_failed" in codes
    assert "capital_control_evidence_reference_invalid" in codes
    assert "capital_control_evidence_artifact_unverified" in codes
    assert payload["capital_authorization_binding"]["status"] == "BLOCK"
    assert payload["capital_authorization_binding"]["scope"] is None


def test_capital_control_artifacts_are_loaded_stably_and_hash_verified(tmp_path):
    fixture = _full_fixture(tmp_path)
    path = Path(fixture["evidence_paths"]["capital_canary"])
    evidence = json.loads(path.read_text(encoding="utf-8"))
    control_ref = evidence["control_evidence"]["tiny_hard_caps"]
    proof_path = path.parent / control_ref["path"]
    proof_path.write_text('{"status":"TAMPERED"}\n', encoding="utf-8")
    evidence["control_evidence"]["authenticated_secret_store"]["path"] = ".env"
    empty_ref = evidence["control_evidence"]["idempotent_order_keys"]
    empty_path = path.parent / empty_ref["path"]
    empty_path.write_text("{}\n", encoding="utf-8")
    empty_ref["sha256"] = hashlib.sha256(empty_path.read_bytes()).hexdigest()
    _write_json(path, evidence)

    payload = build_production_readiness_gate(**fixture)
    failures = {
        (row.get("control"), row.get("verification_failure"))
        for row in payload["blockers"]
        if row["code"] == "capital_control_evidence_artifact_unverified"
    }

    assert payload["stage"] == STAGE_PAPER
    assert ("tiny_hard_caps", "hash_mismatch") in failures
    assert ("authenticated_secret_store", "path_invalid") in failures
    assert ("idempotent_order_keys", "contract_invalid") in failures
    assert payload["capital_authorization_binding"]["status"] == "BLOCK"


def test_capital_control_artifact_binds_the_exact_asserted_value(tmp_path):
    fixture = _full_fixture(tmp_path)
    path = Path(fixture["evidence_paths"]["capital_canary"])
    evidence = json.loads(path.read_text(encoding="utf-8"))
    control_ref = evidence["control_evidence"]["replace_order"]
    proof_path = path.parent / control_ref["path"]
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["asserted_value"] = True
    _write_json(proof_path, proof)
    control_ref["sha256"] = hashlib.sha256(proof_path.read_bytes()).hexdigest()
    _write_json(path, evidence)

    payload = build_production_readiness_gate(**fixture)
    failures = {
        (row.get("control"), row.get("verification_failure"))
        for row in payload["blockers"]
        if row["code"] == "capital_control_evidence_artifact_unverified"
    }

    assert payload["stage"] == STAGE_PAPER
    assert ("replace_order", "contract_invalid") in failures
    assert payload["capital_authorization_binding"]["status"] == "BLOCK"


def test_capital_evidence_rejects_secret_material_and_unknown_top_level_fields(tmp_path):
    fixture = _full_fixture(tmp_path)
    path = Path(fixture["evidence_paths"]["capital_canary"])
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["private_key"] = "must-not-appear-in-readiness-evidence"
    evidence["unreviewed_extension"] = True
    _write_json(path, evidence)

    payload = build_production_readiness_gate(**fixture)
    codes = {row["code"] for row in payload["blockers"]}

    assert payload["stage"] == STAGE_PAPER
    assert "capital_evidence_contains_secret_material" in codes
    assert "capital_evidence_unknown_fields" in codes
    assert payload["capital_authorization_binding"]["status"] == "BLOCK"


def test_capital_authorization_rejects_raw_identity_float_money_and_scope_drift(tmp_path):
    fixture = _full_fixture(tmp_path)
    path = Path(fixture["evidence_paths"]["capital_canary"])
    evidence = json.loads(path.read_text(encoding="utf-8"))
    authorization = evidence["manual_authorization"]
    authorization["account_id"] = "raw-account"
    authorization["account_id_sha256"] = "not-a-hash"
    authorization["platform"] = "unknown-platform"
    authorization["reviewed_by"] = "private_key=must-not-leak"
    authorization["capital_ceiling_usdc"] = 75.0
    authorization["risk_caps"]["alpha_order_max_loss_usdc"] = "7.50"
    authorization["market_ids"] = ["toronto", "toronto"]
    _write_json(path, evidence)

    payload = build_production_readiness_gate(**fixture)
    codes = {row["code"] for row in payload["blockers"]}

    assert payload["stage"] == STAGE_PAPER
    assert "capital_authorization_raw_account_forbidden" in codes
    assert "capital_authorization_unknown_fields" in codes
    assert "capital_authorization_account_hash_invalid" in codes
    assert "capital_authorization_platform_invalid" in codes
    assert "capital_authorization_contains_secret_material" in codes
    assert "capital_authorization_budget_not_exact" in codes
    assert "capital_authorization_caps_mismatch" in codes
    assert "capital_authorization_markets_missing" in codes


def test_bootstrap_release_permits_evidence_stages_but_blocks_capital(tmp_path):
    fixture = _full_fixture(tmp_path)
    production_resolver = fixture["release_resolver"]

    def bootstrap_resolver(**kwargs):
        resolved = dict(production_resolver(**kwargs))
        resolved.update(
            {
                "release_kind": SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
                "candidate_mode": RESEARCH_ONLY_CANDIDATE_MODE,
                "production_capable": False,
            }
        )
        return resolved

    fixture["release_resolver"] = bootstrap_resolver

    payload = build_production_readiness_gate(**fixture)
    capital_blockers = {
        row["code"]
        for row in payload["blockers"]
        if row["stage"] == STAGE_CAPITAL_CANARY
    }

    assert payload["status"] == "PASS"
    assert payload["stage"] == STAGE_PAPER
    assert payload["stage_results"][STAGE_SHADOW]["status"] == "PASS"
    assert payload["stage_results"][STAGE_PAPER]["status"] == "PASS"
    assert payload["stage_results"][STAGE_CAPITAL_CANARY]["status"] == "BLOCK"
    assert "active_release_not_production_capable" in capital_blockers
    assert (
        payload["release_identity"]["release_kind"]
        == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND
    )
    assert (
        payload["release_identity"]["candidate_mode"]
        == RESEARCH_ONLY_CANDIDATE_MODE
    )
    assert payload["release_identity"]["production_capable"] is False


def test_offline_host_admission_also_satisfies_capture_resource_contract(tmp_path):
    fixture = _full_fixture(tmp_path)
    capture_path = Path(fixture["evidence_paths"]["capture_resource_gate"])
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    capture.update(
        {
            "status": "PASS",
            "admitted": True,
            "decision": "ADMIT",
            "configuration": {"capture_mode": "offline_host"},
            "summary": {"active_loop_count": 0, "blocker_count": 0},
            "blockers": [],
        }
    )
    capture["enforcement"]["outcome"] = "ADMITTED_BEFORE_HEAVY_WORK"
    _write_json(capture_path, capture)

    payload = build_production_readiness_gate(**fixture)

    assert payload["status"] == "PASS"
    assert payload["stage"] == STAGE_CAPITAL_CANARY
    assert not any(
        row["input"] == "capture_resource_gate" for row in payload["blockers"]
    )


def test_capture_proof_missing_stale_or_consumer_mismatched_cannot_pass_shadow(tmp_path):
    cases = {}
    for case in ("missing", "stale", "mismatch"):
        fixture = _full_fixture(tmp_path / case)
        capture_path = Path(fixture["evidence_paths"]["capture_resource_gate"])
        if case == "missing":
            capture_path.unlink()
        else:
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            if case == "stale":
                capture["generated_at_utc"] = (NOW - timedelta(hours=3)).isoformat()
            else:
                capture["enforcement"]["consumer"] = "nightly_retrain_heavy_pipeline"
            _write_json(capture_path, capture)
        cases[case] = build_production_readiness_gate(**fixture)

    assert all(payload["stage"] == STAGE_NOT_READY for payload in cases.values())
    assert "missing_evidence" in {row["code"] for row in cases["missing"]["blockers"]}
    assert "stale_evidence" in {row["code"] for row in cases["stale"]["blockers"]}
    assert "capture_resource_consumer_mismatch" in {
        row["code"] for row in cases["mismatch"]["blockers"]
    }


def test_missing_later_stage_evidence_stops_at_shadow(tmp_path):
    fixture = _full_fixture(tmp_path)
    for name in ("challenger_forward", "paper_execution", "capital_canary"):
        Path(fixture["evidence_paths"][name]).unlink()

    payload = build_production_readiness_gate(**fixture)

    assert payload["status"] == "PASS"
    assert payload["stage"] == STAGE_SHADOW
    assert payload["stage_results"]["SHADOW"]["status"] == "PASS"
    assert payload["stage_results"]["PAPER"]["status"] == "BLOCK"
    assert payload["first_blocker"]["stage"] == "PAPER"


def test_missing_capital_evidence_stops_at_paper(tmp_path):
    fixture = _full_fixture(tmp_path)
    Path(fixture["evidence_paths"]["capital_canary"]).unlink()

    payload = build_production_readiness_gate(**fixture)

    assert payload["status"] == "PASS"
    assert payload["stage"] == STAGE_PAPER
    assert payload["stage_results"]["PAPER"]["status"] == "PASS"
    assert payload["stage_results"]["CAPITAL_CANARY"]["status"] == "BLOCK"
    assert payload["capital_permissions"]["order_submission_permitted"] is False


def test_release_mismatch_stale_and_unknown_evidence_fail_closed(tmp_path):
    fixture = _full_fixture(tmp_path)
    settlement_path = Path(fixture["evidence_paths"]["live_settlement_scorecard"])
    settlement = json.loads(settlement_path.read_text(encoding="utf-8"))
    settlement["release_id"] = "other-release"
    _write_json(settlement_path, settlement)
    capture_path = Path(fixture["evidence_paths"]["capture_resource_gate"])
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    capture["generated_at_utc"] = (NOW - timedelta(days=2)).isoformat()
    capture["schema_version"] = "unknown_contract_v99"
    _write_json(capture_path, capture)

    payload = build_production_readiness_gate(**fixture)
    codes = {row["code"] for row in payload["blockers"]}

    assert payload["status"] == "BLOCK"
    assert payload["stage"] == STAGE_NOT_READY
    assert "release_identity_mismatch" in codes
    assert "mixed_release_identities" in codes
    assert "stale_evidence" in codes
    assert "unknown_schema_version" in codes


def test_registered_but_wrong_schema_is_rejected_for_every_distinct_later_stage_contract(tmp_path):
    for name in (
        "rollback_drill",
        "off_machine_backup",
        "restore_drill",
        "storage_headroom",
        "challenger_forward",
        "paper_execution",
        "capital_canary",
    ):
        fixture = _full_fixture(tmp_path / name)
        path = Path(fixture["evidence_paths"][name])
        evidence = json.loads(path.read_text(encoding="utf-8"))
        evidence["schema_version"] = schema_version("capture_resource_gate")
        _write_json(path, evidence)

        payload = build_production_readiness_gate(**fixture)

        assert any(
            row["code"] == "wrong_evidence_schema" and row["input"] == name
            for row in payload["blockers"]
        )


def test_storage_headroom_requires_a_hashed_trustworthy_bounded_probe(tmp_path):
    fixture = _full_fixture(tmp_path)
    path = Path(fixture["evidence_paths"]["storage_headroom"])
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["mode"] = "full_inventory"
    evidence["source_inventory"]["trustworthy"] = False
    evidence["source_inventory"]["sha256"] = ""
    evidence["summary"]["filesystem_walk_performed"] = True
    _write_json(path, evidence)

    payload = build_production_readiness_gate(**fixture)
    codes = {row["code"] for row in payload["blockers"]}

    assert payload["stage"] == STAGE_NOT_READY
    assert "storage_headroom_probe_mode_invalid" in codes
    assert "storage_headroom_source_untrusted" in codes
    assert "storage_headroom_source_hash_missing" in codes
    assert "storage_headroom_unbounded_scan_claimed" in codes


def test_incomplete_release_manifest_and_unlinked_promotion_proof_block_shadow(tmp_path):
    fixture = _full_fixture(tmp_path)
    manifest_path = Path(fixture["releases_root"]) / RELEASE_ID / "release_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["inventory"] = [
        row for row in manifest["artifacts"]["inventory"] if row["kind"] != "settlement_rules"
    ]
    _write_json(manifest_path, manifest)
    pointer_path = Path(fixture["pointer_path"])
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["promotion_decision_sha256"] = "f" * 64
    _write_json(pointer_path, pointer)

    payload = build_production_readiness_gate(**fixture)
    codes = {row["code"] for row in payload["blockers"]}

    assert payload["stage"] == STAGE_NOT_READY
    assert "release_manifest_serving_roles_incomplete" in codes
    assert "promotion_decision_pointer_hash_mismatch" in codes


def test_unattended_inconsistent_inputs_block_shadow(tmp_path):
    fixture = _full_fixture(tmp_path)
    path = Path(fixture["evidence_paths"]["unattended_cycle_ledger"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["summary"]["inconsistent_input_count"] = 1
    _write_json(path, payload)

    gate = build_production_readiness_gate(**fixture)
    codes = {row["code"] for row in gate["blockers"]}

    assert gate["stage"] == STAGE_NOT_READY
    assert "unattended_inconsistent_input_count_nonzero" in codes


def test_observed_only_settlement_tape_cannot_satisfy_shadow_coverage(tmp_path):
    fixture = _full_fixture(tmp_path)
    path = Path(fixture["evidence_paths"]["live_settlement_scorecard"])
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["configuration"]["expected_variant_contract"] = "observed_tape_rows"
    evidence["configuration"]["expected_variants"] = []
    _write_json(path, evidence)

    payload = build_production_readiness_gate(**fixture)
    codes = {row["code"] for row in payload["blockers"]}

    assert payload["stage"] == STAGE_NOT_READY
    assert "settlement_expected_variant_manifest_missing" in codes
    assert "settlement_expected_variants_empty" in codes


def test_settlement_requires_complete_sibling_snapshot_contract_and_market_day_weighting(tmp_path):
    fixture = _full_fixture(tmp_path)
    path = Path(fixture["evidence_paths"]["live_settlement_scorecard"])
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["configuration"]["expected_partition_contract"] = "observed_tape_rows"
    evidence["configuration"]["aggregate_weighting"] = "equal_partition"
    evidence["coverage"]["expected_snapshot_partition_count"] = 0
    evidence["coverage"]["expected_snapshot_partition_coverage"] = 0.0
    evidence["coverage"]["missing_expected_snapshot_partition_count"] = 1
    evidence["coverage"]["missing_expected_snapshot_band_count"] = 1
    evidence["coverage"]["unexpected_variant_snapshot_partition_count"] = 1
    _write_json(path, evidence)

    payload = build_production_readiness_gate(**fixture)
    codes = {row["code"] for row in payload["blockers"]}

    assert payload["stage"] == STAGE_NOT_READY
    assert "settlement_expected_snapshot_contract_missing" in codes
    assert "settlement_snapshot_weighted_headline_forbidden" in codes
    assert "settlement_expected_snapshot_partitions_empty" in codes
    assert "settlement_expected_snapshot_coverage_incomplete" in codes
    assert "settlement_missing_expected_snapshot_partition_count_nonzero" in codes
    assert "settlement_missing_expected_snapshot_band_count_nonzero" in codes
    assert "settlement_unexpected_variant_snapshot_partition_count_nonzero" in codes


def test_missing_or_unverified_active_release_is_not_ready(tmp_path):
    def failed_resolver(**_kwargs):
        raise ReleaseArtifactVerificationError("served bindings missing")

    payload = build_production_readiness_gate(
        evidence_paths={spec.name: tmp_path / f"missing-{spec.name}.json" for spec in EVIDENCE_SPECS},
        pointer_path=tmp_path / "missing-pointer.json",
        releases_root=tmp_path / "releases",
        release_resolver=failed_resolver,
        now=NOW,
    )

    assert payload["status"] == "BLOCK"
    assert payload["stage"] == STAGE_NOT_READY
    assert payload["release_identity"]["release_id"] is None
    assert any(row["code"] == "active_release_verification_failed" for row in payload["blockers"])
    assert "candidate-only immutable release" in payload["first_blocker"]["next_action"]


def test_atomic_outputs_and_cli_fail_on_currently_missing_evidence(tmp_path):
    fixture = _full_fixture(tmp_path)
    payload = build_production_readiness_gate(**fixture)
    json_out = tmp_path / "gate.json"
    report_out = tmp_path / "gate.md"
    write_outputs(payload, json_out=json_out, report_out=report_out)

    assert json.loads(json_out.read_text(encoding="utf-8"))["input_set_sha256"] == payload["input_set_sha256"]
    assert "Production Readiness Gate" in report_out.read_text(encoding="utf-8")
    assert not list(tmp_path.glob(".*.tmp"))

    missing_args = []
    for spec in EVIDENCE_SPECS:
        missing_args.extend([f"--{spec.name.replace('_', '-')}", str(tmp_path / f"cli-{spec.name}.json")])
    exit_code = main(
        [
            *missing_args,
            "--active-pointer",
            str(tmp_path / "cli-pointer.json"),
            "--releases-root",
            str(tmp_path / "cli-releases"),
            "--json-out",
            str(tmp_path / "cli-gate.json"),
            "--report-out",
            str(tmp_path / "cli-gate.md"),
            "--now",
            NOW.isoformat(),
            "--fail-on-block",
        ]
    )
    assert exit_code == 1
    assert json.loads((tmp_path / "cli-gate.json").read_text(encoding="utf-8"))["stage"] == STAGE_NOT_READY


def test_status_writer_rejects_pointer_release_and_input_output_aliases(tmp_path):
    fixture = _full_fixture(tmp_path)
    pointer = Path(fixture["pointer_path"])
    before = pointer.read_bytes()
    protected_outputs = [
        pointer,
        Path(fixture["releases_root"]) / "gate.json",
        Path(next(iter(fixture["evidence_paths"].values()))),
        Path(next(iter(fixture["served_artifact_paths"].values()))),
        Path(fixture["served_route_path"]),
    ]
    for index, output in enumerate(protected_outputs):
        with pytest.raises(ValueError, match="unsafe production readiness"):
            build_and_write_production_readiness_status(
                backtest_root=tmp_path,
                evidence_paths=fixture["evidence_paths"],
                json_out=output,
                report_out=tmp_path / f"safe-{index}.md",
                pointer_path=pointer,
                releases_root=fixture["releases_root"],
                served_artifact_paths=fixture["served_artifact_paths"],
                served_route_path=fixture["served_route_path"],
                release_resolver=fixture["release_resolver"],
                now=NOW,
            )
        assert pointer.read_bytes() == before


def test_status_writer_detects_pointer_mutation_by_resolver(tmp_path):
    fixture = _full_fixture(tmp_path)
    pointer = Path(fixture["pointer_path"])
    resolver = fixture["release_resolver"]

    def mutating_resolver(**kwargs):
        result = resolver(**kwargs)
        pointer.write_text(pointer.read_text(encoding="utf-8") + " ", encoding="utf-8")
        return result

    payload, _json, _report = build_and_write_production_readiness_status(
        backtest_root=tmp_path,
        evidence_paths=fixture["evidence_paths"],
        json_out=tmp_path / "gate.json",
        report_out=tmp_path / "gate.md",
        pointer_path=pointer,
        releases_root=fixture["releases_root"],
        served_artifact_paths=fixture["served_artifact_paths"],
        served_route_path=fixture["served_route_path"],
        release_resolver=mutating_resolver,
        now=NOW,
    )

    assert payload["status"] == "BLOCK"
    assert payload["stage"] == STAGE_NOT_READY
    assert payload["read_only_attestation"]["pointer_mutated"] is True
    assert any(
        row["code"] == "readiness_pointer_mutated_during_evaluation"
        for row in payload["blockers"]
    )
