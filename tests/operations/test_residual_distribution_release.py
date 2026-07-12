import json
import pickle
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

from weather.calibration.residual_distribution_corpus import MANIFEST_SCHEMA_VERSION
from weather.collection.live_variant_predictions import build_live_variant_prediction_rows
from weather.calibration.residual_distribution_lock import build_preselection_lock
from weather.calibration.residual_distribution_v1 import (
    FINAL_FIT_RECEIPT_SCHEMA_VERSION,
    FIT_RECEIPT_PAYLOAD_CANONICALIZATION,
    FIT_RECEIPT_PAYLOAD_HASH_ALGORITHM,
    _pipeline_payload_sha256,
    _payload_sha256,
    build_oof_fit_receipt,
)
from weather.experiment_contract import finalize_self_hash
from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.model.residual_distribution_v1 import ARTIFACT_SCHEMA_VERSION, PREDICTION_MODE
from weather.model_stage_retirement import (
    ABLATION_HASH_FIELD,
    ABLATION_SCHEMA_VERSION,
    INCUMBENT_STAGES,
    REQUIRED_CALIBRATION_ARMS,
    REQUIRED_EXPERIMENT_TYPES,
    REQUIRED_SAFETY_INVARIANTS,
    build_stage_retirement_register,
)
from weather.operations.release_manifest import sha256_file
from weather.paths import REPO_ROOT
from weather.reporting.scorecards.live_variant_settlement_scorecard import (
    compare_replay_to_served,
)
from weather.reporting.validation.point_in_time_evaluation import (
    RollingOriginFold,
    build_fit_receipt,
    build_window_lock,
    canonicalize_raw_row,
    evaluate_point_in_time_rows,
    point_in_time_key,
)
from weather.residual_distribution_release import (
    RELEASE_CONFIG_HASH_FIELD,
    REQUIRED_CORPUS_CRITERIA,
    REQUIRED_FORWARD_QUALIFICATION_CRITERIA,
    REQUIRED_QUALIFICATION_CRITERIA,
    build_residual_distribution_v1_candidate_release,
    build_residual_distribution_v1_forward_attestation,
    run_residual_distribution_v1_candidate_release,
    verify_residual_distribution_v1_forward_attestation,
    verify_residual_distribution_v1_release,
)
from weather.release_serving import (
    STATUS_BOUND,
    STATUS_SHADOW_BOUND,
    ReleaseServingBindingError,
    load_verified_residual_distribution_v1_shadow_bundle,
    materialize_verified_base_model_market,
    serving_bundle_lineage,
)


CANDIDATE_ID = "residual-distribution-v1-qualified"
RELEASE_ID = "residual-v1-release-20260712"
ROLLBACK_ID = "weather-release-previous"


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _pipeline(feature_names):
    rows = []
    for offset in range(4):
        row = {name: 0.0 for name in feature_names}
        row.update({
            "forecast_high": 70.0 + offset,
            "forecast_high_available": 1.0,
            "source_health_fresh_count": 1.0,
            "source_open_meteo_present": 1.0,
            "source_open_meteo_available": 1.0,
            "source_open_meteo_fresh": 1.0,
        })
        rows.append(row)
    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("ridge", Ridge(alpha=1.0)),
    ])
    pipeline.fit(pd.DataFrame(rows, columns=feature_names), [0.0] * len(rows))
    return pipeline


def _receipt_graph(pipeline):
    inner_fold = RollingOriginFold(
        fold_id="inner-1",
        train_dates=("2026-05-01",),
        embargo_dates=(),
        validation_dates=("2026-05-02",),
        embargo_days=3,
    )
    parent = build_fit_receipt(
        inner_fold,
        fold_scope="outer-1/inner-1",
        stage_name="residual_mean_model",
        implementation_identity="fixture.Ridge",
        fit_rows=({"target_date": "2026-05-01", "value": 1},),
        validation_rows=({"target_date": "2026-05-02", "value": 2},),
        fit_output_rows=({"target_date": "2026-05-01", "prediction": 0.0},),
        validation_output_rows=({"target_date": "2026-05-02", "prediction": 0.0},),
        stage_input_payload={"kind": "fixture_features"},
        stage_output_payload={"kind": "fixture_predictions"},
        generated_at_utc="2026-06-29T00:00:00+00:00",
    )
    oof_row = {
        "row": {"target_date": "2026-05-02", "market_id": "atlanta", "cutoff_hour": 8},
        "predicted_residual_f": 0.0,
        "residual_error_f": 0.0,
        "probabilities": {"low": 0.5, "high": 0.5},
    }
    outer = RollingOriginFold(
        fold_id="outer-1",
        train_dates=("2026-05-02",),
        embargo_dates=(),
        validation_dates=("2026-05-10",),
        embargo_days=3,
    )
    oof = build_oof_fit_receipt(
        outer_fold=outer,
        oof_rows=(oof_row,),
        calibrated_rows=(oof_row,),
        parent_receipt_sha256s=(parent["receipt_sha256"],),
        parent_stage_output_sha256s=(parent["stage_output_sha256"],),
        stage_name="scale_and_calibration",
        sigma_f=2.0,
        calibrator={"method": "identity", "temperature": 1.0},
        generated_at_utc="2026-06-29T00:01:00+00:00",
    )
    model_sha = _pipeline_payload_sha256(pipeline)
    fit_input_sha = "4" * 64
    prediction_sha = "5" * 64
    input_payload = {
        "fit_input_sha256": fit_input_sha,
        "fit_row_count": 1,
        "train_dates": ["2026-05-01"],
        "locked_dates": [],
        "parent_oof_receipt_sha256": oof["receipt_sha256"],
        "parent_stage_output_sha256": oof["stage_output_sha256"],
    }
    output_payload = {
        "model_payload_sha256": model_sha,
        "fit_predictions_sha256": prediction_sha,
        "fit_prediction_row_count": 1,
        "feature_names": [],
    }
    final_receipt = finalize_self_hash({
        "schema_version": FINAL_FIT_RECEIPT_SCHEMA_VERSION,
        "artifact_type": "residual_distribution_final_fit_receipt",
        "generated_at_utc": "2026-06-29T00:02:00+00:00",
        "fit_role": "prelock_final_refit",
        "train_dates": ["2026-05-01"],
        "locked_dates": [],
        "fit_row_count": 1,
        "fit_input_sha256": fit_input_sha,
        "fit_predictions_sha256": prediction_sha,
        "model_payload_sha256": model_sha,
        "parent_oof_receipt_sha256": oof["receipt_sha256"],
        "parent_stage_output_sha256": oof["stage_output_sha256"],
        "payload_hash_algorithm": FIT_RECEIPT_PAYLOAD_HASH_ALGORITHM,
        "payload_canonicalization": FIT_RECEIPT_PAYLOAD_CANONICALIZATION,
        "stage_input_payload": input_payload,
        "stage_input_sha256": _payload_sha256(input_payload),
        "stage_output_payload": output_payload,
        "stage_output_sha256": _payload_sha256(output_payload),
    }, hash_field="receipt_sha256")
    return parent, oof, final_receipt, model_sha


def _identity():
    return (
        {"git_commit": "a" * 40, "git_branch": "main", "git_dirty": False, "dirty_fingerprint": None},
        {
            "python": "3.13.0",
            "implementation": "CPython",
            "platform": "test",
            "direct_dependencies": {"scikit-learn": {"version": "1.7.0", "declared": "scikit-learn"}},
        },
        {"source_fingerprint": "fixture-source-fingerprint", "git_commit": "a" * 40},
    )


def _offline_safety_evidence(source: Path, report_path: Path, artifact_sha: str):
    paired_hash = "7" * 64
    calibration = {
        "literal_served_transform_executed": True,
        "comparator_arm": "literal_current_served_transform",
        "arms_evaluated": sorted(REQUIRED_CALIBRATION_ARMS),
        "selected_arm": "simplex_temperature",
        "paired_unit": "fleet_target_date",
        "paired_date_count": 14,
        "paired_dates_sha256": paired_hash,
        "embargo_days_evaluated": [3, 5, 7],
        "seed_count": 5,
        "evaluation_receipt_sha256": "8" * 64,
        "delta_brier": {"mean": -0.002, "ci95_upper": -0.0001},
        "delta_log_loss": {"mean": -0.006, "ci95_upper": -0.0001},
        "ece_delta": 0.002,
        "ece_delta_ci95_upper": 0.008,
        "max_market_brier_delta": 0.006,
        "simplex_invariants": {
            "partition_sum_one": "PASS",
            "probabilities_finite": "PASS",
            "probabilities_nonnegative": "PASS",
            "served_transform_parity": "PASS",
        },
        "parity_vectors": {"status": "PASS", "max_abs_delta": 0.0},
    }
    stages = [{
        "stage_id": descriptor["stage_id"],
        "category": descriptor["category"],
        "experiment_types": sorted(REQUIRED_EXPERIMENT_TYPES),
        "paired_unit": "fleet_target_date",
        "paired_date_count": 14,
        "paired_dates_sha256": paired_hash,
        "evaluation_receipt_sha256": f"{index + 1:064x}",
        "delta_brier": {"mean": 0.0002, "ci95_upper": 0.0008},
        "delta_log_loss": {"mean": 0.001, "ci95_upper": 0.004},
        "max_market_brier_delta": 0.008,
        "safety_invariants": {key: "PASS" for key in REQUIRED_SAFETY_INVARIANTS},
    } for index, descriptor in enumerate(INCUMBENT_STAGES)]
    ablation = finalize_self_hash({
        "schema_version": ABLATION_SCHEMA_VERSION,
        "artifact_type": "served_calibration_stage_ablation",
        "status": "PASS",
        "candidate_id": CANDIDATE_ID,
        "generated_at_utc": "2026-07-01T02:00:00+00:00",
        "requalification_report_sha256": sha256_file(report_path),
        "candidate_artifact_sha256": artifact_sha,
        "independent_unit": "fleet_target_date",
        "cluster_unit": "fleet_target_date",
        "paired_date_count": 14,
        "paired_dates_sha256": paired_hash,
        "frozen_full_stack_id": "incumbent-release-frozen",
        "candidate_graph_id": CANDIDATE_ID,
        "calibration": calibration,
        "stage_ablations": stages,
    }, hash_field=ABLATION_HASH_FIELD)
    ablation_path = _write_json(source / "served_ablation.json", ablation)
    register = build_stage_retirement_register(
        report_path,
        ablation_path,
        repo_root=REPO_ROOT,
        generated_at_utc="2026-07-01T03:00:00+00:00",
    )
    register_path = _write_json(source / "stage_retirement_register.json", register)
    required_controls = [
        "artifact_contract",
        "base_case_scoring",
        "e5_forbidden_future_label_sentinels",
        "e5_grouped_date_permutation",
        "e5_deterministic_noise",
        "e5_market_copy_placebo",
        "e6_provider_fault_matrix",
        "e6_cadence_time_unit_band_metamorphic",
    ]
    stress = finalize_self_hash({
        "schema_version": "residual_distribution_stress_evaluation_v1",
        "generated_at_utc": "2026-07-01T04:00:00+00:00",
        "status": "PASS",
        "candidate_id": CANDIDATE_ID,
        "candidate_artifact_sha256": artifact_sha,
        "requalification_report_sha256": sha256_file(report_path),
        "criteria": {"required_controls": required_controls},
        "control_statuses": {name: "PASS" for name in required_controls},
        "controls": {name: {"status": "PASS"} for name in required_controls},
    }, hash_field="report_sha256")
    stress_path = _write_json(source / "stress.json", stress)
    return ablation_path, register_path, stress_path


def _fixture(tmp_path: Path) -> dict:
    source = tmp_path / "source"
    releases = tmp_path / "releases"
    pointer = releases / "current_release.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text('{"sentinel":"unchanged"}\n', encoding="utf-8")
    corpus_sha = "1" * 64
    corpus_manifest = finalize_self_hash({
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_type": "residual_distribution_training_corpus_manifest",
        "generated_at_utc": "2026-07-01T00:00:00+00:00",
        "corpus_schema_version": "residual_distribution_training_corpus_v2",
        "corpus_sha256": corpus_sha,
        "qualification_input_contract": {
            "status": "PASS",
            "criteria": {key: True for key in REQUIRED_CORPUS_CRITERIA},
            "release_ids": ["weather-release-source"],
            "runtime_identity_sha256s": ["2" * 64],
        },
        "counts": {"accepted_rows": 336, "fleet_dates": 28, "market_days": 336},
        "inputs": [{"status": "PASS", "manifest_sha256": "3" * 64}],
        "exclusions": [],
    }, hash_field="manifest_sha256")
    corpus_path = _write_json(source / "corpus_manifest.json", corpus_manifest)
    locked_dates = [f"2026-06-{day:02d}" for day in range(1, 15)]
    lock = build_preselection_lock(
        candidate_id=CANDIDATE_ID,
        corpus_sha256=corpus_sha,
        corpus_manifest_sha256=corpus_manifest["manifest_sha256"],
        locked_dates=locked_dates,
        expected_market_ids=["atlanta"],
        expected_cutoff_hours=[8],
        created_at_utc="2026-06-30T00:00:00+00:00",
    )
    lock_path = _write_json(source / "preselection_lock.json", lock)
    criteria = {key: True for key in REQUIRED_QUALIFICATION_CRITERIA}
    for key in REQUIRED_FORWARD_QUALIFICATION_CRITERIA:
        criteria[key] = False
    feature_names = [
        "forecast_high", "forecast_high_available", "forecast_high_missing",
        "source_health_fresh_count", "source_health_stale_count",
        "source_health_failed_count", "source_health_unknown_count",
        "source_health_source_count", "source_health_all_fresh",
        "source_health_any_degraded", "source_open_meteo_present",
        "source_open_meteo_available", "source_open_meteo_fresh",
        "source_open_meteo_stale", "source_open_meteo_failed",
        "source_open_meteo_unknown", "source_open_meteo_age_ratio",
        "source_open_meteo_age_ratio_available",
    ]
    pipeline = _pipeline(feature_names)
    parent, oof, final_receipt, model_sha = _receipt_graph(pipeline)
    qualification = {
        "status": "OFFLINE_PASS",
        "offline_status": "PASS",
        "forward_status": "BLOCK",
        "criteria": criteria,
        "offline_criteria": {key: value for key, value in criteria.items() if key not in REQUIRED_FORWARD_QUALIFICATION_CRITERIA},
        "forward_criteria": {key: False for key in REQUIRED_FORWARD_QUALIFICATION_CRITERIA},
        "parity_evidence": {},
        "streaming_evidence": {},
    }
    artifact = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "prediction_mode": PREDICTION_MODE,
        "candidate_id": CANDIDATE_ID,
        "canonical_unit": "F",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": feature_names,
        "feature_contract": {"features": {"forecast_high": "absolute_temperature"}, "required": ["forecast_high"]},
        "source_health_policy": {"required_sources": ["open_meteo"], "allowed_states": ["fresh"]},
        "pipeline": pipeline,
        "residual_sigma_f": 2.0,
        "grid_low_f": -40.0,
        "grid_high_f": 130.0,
        "grid_step_f": 0.1,
        "calibration": {
            "method": "identity",
            "temperature": 1.0,
            "oof_receipt_sha256": oof["receipt_sha256"],
            "model_payload_sha256": model_sha,
        },
        "training_lineage": {
            "full_corpus_sha256": corpus_sha,
            "corpus_manifest_sha256": corpus_manifest["manifest_sha256"],
            "preselection_lock": lock,
            "locked_dates": locked_dates,
            "fit_receipts": [parent],
            "oof_receipt": oof,
            "final_fit_receipt": final_receipt,
        },
        "qualification": qualification,
    }
    artifact_path = source / "model.pkl"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(pickle.dumps(artifact, protocol=pickle.HIGHEST_PROTOCOL))
    artifact_sha = sha256_file(artifact_path)
    report = {
        "status": "OFFLINE_PASS",
        "candidate_id": CANDIDATE_ID,
        "generated_at_utc": "2026-07-01T01:00:00+00:00",
        "corpus_sha256": corpus_sha,
        "locked_dates": locked_dates,
        "qualification": {
            **qualification,
            "preselection_lock": lock,
            "corpus_manifest_sha256": corpus_manifest["manifest_sha256"],
        },
        "candidate_artifact": {
            "path": str(artifact_path),
            "sha256": artifact_sha,
            "qualification_status": "OFFLINE_PASS",
            "offline_qualification_status": "PASS",
            "forward_qualification_status": "BLOCK",
            "candidate_release_eligible": True,
            "promotion_eligible": False,
        },
    }
    report_path = _write_json(source / "requalification.json", report)
    ablation_path, register_path, stress_path = _offline_safety_evidence(
        source, report_path, artifact_sha
    )
    registry_path = _write_json(source / "model_variant_registry.json", {
        "schema_version": "model_variant_registry_v0.1",
        "variants": [{
            "variant_id": CANDIDATE_ID,
            "variant_family": "residual_distribution",
            "lifecycle": "shadow",
            "prediction_mode": PREDICTION_MODE,
            "live_runtime": PREDICTION_MODE,
            "active_for_headline": False,
            "live_capture_enabled": False,
            "counts_toward_weather_model_promotion": False,
            "artifact_required": True,
        }],
    })
    code, runtime_versions, runtime_identity = _identity()
    return {
        "release_id": RELEASE_ID,
        "candidate_bundle_dir": tmp_path / "candidates" / RELEASE_ID,
        "artifact_path": artifact_path,
        "requalification_report_path": report_path,
        "corpus_manifest_path": corpus_path,
        "preselection_lock_path": lock_path,
        "served_calibration_stage_ablation_path": ablation_path,
        "stage_retirement_register_path": register_path,
        "stress_report_path": stress_path,
        "model_registry_path": registry_path,
        "rollback_target": ROLLBACK_ID,
        "code_identity": code,
        "runtime_versions": runtime_versions,
        "runtime_identity": runtime_identity,
        "releases_root": releases,
        "active_pointer_path": pointer,
        "repo_root": REPO_ROOT,
        "created_at_utc": "2026-07-12T12:00:00+00:00",
    }


def _forward_evidence(tmp_path: Path, result: dict, *, branches=("fresh",)):
    manifest_sha = result["manifest_sha256"]
    artifact_path = Path(result["release_dir"]) / "model/model.pkl"
    artifact_sha = sha256_file(artifact_path)
    rows = []
    for branch_index, branch in enumerate(branches):
        for kind, value, probability in (("lte", 70, 0.4), ("gte", 71, 0.6)):
            rows.append({
                "target_date": "2026-07-12",
                "market_id": "atlanta",
                "snapshot_id": f"s-{branch_index}",
                "variant_id": CANDIDATE_ID,
                "release_id": RELEASE_ID,
                "evidence_lane": "weather_only",
                "bin_kind": kind,
                "bin_value_c": value,
                "prediction_status": "predicted",
                "variant_probability": probability,
                "captured_input_hash": f"input-{branch}",
                "live_runtime": PREDICTION_MODE,
                "route_id": "residual-v1",
                "model_version": CANDIDATE_ID,
                "artifact_hash": artifact_sha,
                "postprocess_config_hash": "identity",
                "release_manifest_sha256": manifest_sha,
                "parity_branch_scenario": branch,
            })
    parity = compare_replay_to_served(
        rows,
        deepcopy(rows),
        generated_at_utc="2026-07-12T12:02:00+00:00",
        coverage_contract={
            "candidate_id": CANDIDATE_ID,
            "expected_market_ids": ["atlanta"],
            "expected_branch_scenarios": list(branches),
            "expected_band_count_by_market": {"atlanta": 2},
        },
    )
    parity_path = _write_json(tmp_path / "external" / "parity.json", parity)
    dates = [f"2026-06-{day:02d}" for day in range(1, 15)]
    provenance = {
        "artifact_family": "snapshots_long",
        "source_mode": "validated_parquet",
        "manifest_hash": "manifest-hash",
        "source_file_hash": "source-hash",
    }
    streaming_rows = []
    for target_date in dates:
        for band, probability, label in (("low", 0.7, 1), ("high", 0.3, 0)):
            streaming_rows.append(canonicalize_raw_row({
                "target_date": target_date,
                "market_id": "atlanta",
                "snapshot_id": "08:00",
                "range_label": band,
                "variant_id": CANDIDATE_ID,
                "release_id": RELEASE_ID,
                "feature_available_at_utc": f"{target_date}T11:55:00+00:00",
                "captured_at_utc": f"{target_date}T12:00:00+00:00",
                "label_quality": "complete",
                "countable": True,
                "claim_lane": "weather_only",
                "replay_serve_parity": "pass",
                "source_quality": "healthy",
                "prediction_probability": probability,
                "label": label,
                "runtime_identity": "runtime-1",
            }, provenance=provenance))
    lock = build_window_lock(
        dates,
        input_sha256="6" * 64,
        generated_at_utc="2026-07-12T12:00:30+00:00",
    )
    streaming = evaluate_point_in_time_rows(
        sorted(streaming_rows, key=point_in_time_key),
        locked_dates=dates,
        bootstrap_iterations=25,
        generated_at_utc="2026-07-12T12:05:00+00:00",
        evaluation_started_at_utc="2026-07-12T12:01:00+00:00",
        window_lock=lock,
        candidate_id=CANDIDATE_ID,
        release_id=RELEASE_ID,
        manifest_sha256=manifest_sha,
        candidate_artifact_sha256=artifact_sha,
    )
    streaming_path = _write_json(tmp_path / "external" / "streaming.json", streaming)
    return parity_path, streaming_path


def test_phase_one_builds_offline_release_without_forward_evidence_or_pointer_mutation(tmp_path):
    kwargs = _fixture(tmp_path)
    pointer_before = kwargs["active_pointer_path"].read_bytes()
    result = build_residual_distribution_v1_candidate_release(**kwargs)
    verified = verify_residual_distribution_v1_release(result["release_dir"], check_runtime=False)
    assert result["qualification_status"] == "OFFLINE_PASS"
    assert verified["qualification_status"] == "OFFLINE_PASS"
    assert kwargs["active_pointer_path"].read_bytes() == pointer_before
    assert verified["manifest"]["artifacts"]["file_count"] == 9
    config = json.loads((Path(result["release_dir"]) / "config/residual_distribution_v1_release_config.json").read_text())
    assert config["qualification_status"] == "OFFLINE_PASS"
    assert config[RELEASE_CONFIG_HASH_FIELD]


def test_verified_inactive_shadow_bundle_stamps_exact_forward_capture_identity(tmp_path):
    kwargs = _fixture(tmp_path)
    pointer_before = kwargs["active_pointer_path"].read_bytes()
    result = build_residual_distribution_v1_candidate_release(**kwargs)
    release_dir = Path(result["release_dir"])
    model_path = release_dir / "model/model.pkl"
    registry_path = release_dir / "config/model_variant_registry.json"

    bundle = load_verified_residual_distribution_v1_shadow_bundle(
        release_dir,
        repo_root=REPO_ROOT,
        expected_manifest_sha256=result["manifest_sha256"],
        check_runtime=False,
    )
    assert bundle.status == STATUS_SHADOW_BOUND
    assert bundle.status != STATUS_BOUND
    assert bundle.base_model_bound is True
    assert bundle.release_id == RELEASE_ID
    assert bundle.manifest_sha256 == result["manifest_sha256"]
    assert bundle.artifact_paths["residual_distribution_v1_model"] == str(model_path)
    assert bundle.artifact_hashes["residual_distribution_v1_model"] == sha256_file(model_path)
    assert bundle.artifact_hashes["model_variant_registry"] == sha256_file(registry_path)
    assert serving_bundle_lineage(bundle)["release_identity_status"] == (
        "verified_inactive_shadow_bundle"
    )
    with pytest.raises(ReleaseServingBindingError, match="active-release graph"):
        materialize_verified_base_model_market(bundle, "atlanta")

    band_rows = [{
        "snapshot_id": "shadow-snapshot",
        "range_label": "20 C or lower",
        "bin_kind": "lte",
        "bin_value_c": 20,
        "bin_value_hi_c": 20,
        "model_probability": 0.41,
        "market_yes": 0.40,
        "market_no": 0.60,
        "condition_id": "shadow-condition",
        "market_status": "active",
    }]
    with patch(
        "weather.model.residual_distribution_v1.predict_residual_distribution_v1",
        return_value={
            "status": "predicted",
            "probabilities": {"lte_20c": 0.23},
            "model_version": CANDIDATE_ID,
        },
    ):
        rows = build_live_variant_prediction_rows(
            snapshot_id="shadow-snapshot",
            captured_at=datetime(2026, 7, 12, 16, 0, tzinfo=timezone.utc),
            event={"updatedAt": "2026-07-12T15:59:00+00:00"},
            model={
                "feature_vector": {"forecast_high": 72.0},
                "source_diagnostics": [{"source": "open_meteo", "status": "fresh"}],
            },
            model_client=object(),
            band_rows=band_rows,
            event_slug="atlanta-high-2026-07-12",
            market_id="atlanta",
            target_date=date(2026, 7, 12),
            serving_model_version="incumbent",
            captured_input_hash="c" * 64,
            serving_bundle=bundle,
        )

    assert len(rows) == 1
    row = rows[0]
    assert row["prediction_status"] == "predicted"
    assert row["variant_id"] == CANDIDATE_ID
    assert row["release_id"] == RELEASE_ID
    assert row["release_manifest_sha256"] == result["manifest_sha256"]
    assert row["release_pointer_sha256"] == ""
    assert row["release_identity_status"] == "verified_inactive_shadow_bundle"
    assert row["artifact_hash"] == sha256_file(model_path)
    assert row["artifact_path"] == str(model_path)
    assert row["live_runtime"] == PREDICTION_MODE
    assert row["active_for_headline"] is False
    assert row["serving_model_binding_status"] == "verified_release_base_model"
    assert kwargs["active_pointer_path"].read_bytes() == pointer_before


@pytest.mark.parametrize(
    "failure",
    [
        "missing_receipts",
        "report_status",
        "artifact_hash",
        "corpus_hash",
        "missing_ablation",
        "tampered_register",
        "tampered_stress",
        "registry_activated",
    ],
)
def test_phase_one_fails_closed_on_offline_evidence_mismatch(tmp_path, failure):
    kwargs = _fixture(tmp_path)
    if failure == "missing_receipts":
        artifact = pickle.loads(kwargs["artifact_path"].read_bytes())
        artifact["training_lineage"].pop("final_fit_receipt")
        kwargs["artifact_path"].write_bytes(pickle.dumps(artifact))
    elif failure == "report_status":
        report = json.loads(kwargs["requalification_report_path"].read_text())
        report["status"] = "PASS"
        _write_json(kwargs["requalification_report_path"], report)
    elif failure == "artifact_hash":
        report = json.loads(kwargs["requalification_report_path"].read_text())
        report["candidate_artifact"]["sha256"] = "f" * 64
        _write_json(kwargs["requalification_report_path"], report)
    elif failure == "corpus_hash":
        corpus = json.loads(kwargs["corpus_manifest_path"].read_text())
        corpus["counts"]["accepted_rows"] += 1
        _write_json(kwargs["corpus_manifest_path"], corpus)
    elif failure == "missing_ablation":
        kwargs["served_calibration_stage_ablation_path"].unlink()
    elif failure == "tampered_register":
        register = json.loads(kwargs["stage_retirement_register_path"].read_text())
        register["status"] = "BLOCK"
        _write_json(kwargs["stage_retirement_register_path"], register)
    elif failure == "tampered_stress":
        stress = json.loads(kwargs["stress_report_path"].read_text())
        stress["control_statuses"]["artifact_contract"] = "BLOCK"
        _write_json(kwargs["stress_report_path"], stress)
    else:
        registry = json.loads(kwargs["model_registry_path"].read_text())
        registry["variants"][0]["live_capture_enabled"] = True
        _write_json(kwargs["model_registry_path"], registry)
    result = run_residual_distribution_v1_candidate_release(**kwargs)
    assert result["status"] == "BLOCK"
    assert result["active_pointer_unchanged"] is True
    assert not (kwargs["releases_root"] / RELEASE_ID).exists()


def test_phase_two_attests_exact_release_bound_forward_evidence_without_pointer_mutation(tmp_path):
    kwargs = _fixture(tmp_path)
    result = build_residual_distribution_v1_candidate_release(**kwargs)
    parity_path, streaming_path = _forward_evidence(tmp_path, result)
    pointer_before = kwargs["active_pointer_path"].read_bytes()
    attestation_path = tmp_path / "external" / "forward-attestation.json"
    attestation = build_residual_distribution_v1_forward_attestation(
        release_dir=result["release_dir"],
        live_replay_parity_path=parity_path,
        point_in_time_streaming_path=streaming_path,
        attestation_path=attestation_path,
        active_pointer_path=kwargs["active_pointer_path"],
        repo_root=REPO_ROOT,
        generated_at_utc="2026-07-12T12:06:00+00:00",
    )
    verified = verify_residual_distribution_v1_forward_attestation(
        attestation_path,
        release_dir=result["release_dir"],
        live_replay_parity_path=parity_path,
        point_in_time_streaming_path=streaming_path,
        repo_root=REPO_ROOT,
    )
    assert attestation["status"] == verified["status"] == "PASS"
    assert attestation["release_manifest_sha256"] == result["manifest_sha256"]
    assert kwargs["active_pointer_path"].read_bytes() == pointer_before


@pytest.mark.parametrize(
    ("evidence", "field"),
    [
        ("parity", "candidate_id"),
        ("parity", "release_id"),
        ("parity", "manifest_sha256"),
        ("parity", "candidate_artifact_sha256"),
        ("streaming", "candidate_id"),
        ("streaming", "release_id"),
        ("streaming", "manifest_sha256"),
        ("streaming", "candidate_artifact_sha256"),
    ],
)
def test_phase_two_blocks_any_missing_exact_identity_binding(tmp_path, evidence, field):
    kwargs = _fixture(tmp_path)
    result = build_residual_distribution_v1_candidate_release(**kwargs)
    parity_path, streaming_path = _forward_evidence(tmp_path, result)
    path = parity_path if evidence == "parity" else streaming_path
    payload = json.loads(path.read_text())
    payload.pop(field)
    hash_field = "parity_sha256" if evidence == "parity" else "evaluation_hash"
    payload = finalize_self_hash(
        {key: value for key, value in payload.items() if key != hash_field},
        hash_field=hash_field,
    )
    _write_json(path, payload)
    with pytest.raises(Exception):
        build_residual_distribution_v1_forward_attestation(
            release_dir=result["release_dir"],
            live_replay_parity_path=parity_path,
            point_in_time_streaming_path=streaming_path,
            attestation_path=tmp_path / "external" / "blocked.json",
            active_pointer_path=kwargs["active_pointer_path"],
            repo_root=REPO_ROOT,
        )


def test_phase_two_blocks_subset_or_missing_branch_coverage(tmp_path):
    kwargs = _fixture(tmp_path)
    result = build_residual_distribution_v1_candidate_release(**kwargs)
    parity_path, streaming_path = _forward_evidence(tmp_path, result, branches=("fresh",))
    parity = json.loads(parity_path.read_text())
    coverage = parity["coverage_contract"]
    coverage["expected_branch_scenarios"].append("stale")
    coverage["status"] = "BLOCK"
    coverage["checks"]["expected_market_branch_cross_product_complete"] = False
    coverage["missing_market_branch_pairs"] = [{"market_id": "atlanta", "branch_scenario": "stale"}]
    parity["status"] = "BLOCK"
    parity = finalize_self_hash(
        {key: value for key, value in parity.items() if key != "parity_sha256"},
        hash_field="parity_sha256",
    )
    _write_json(parity_path, parity)
    with pytest.raises(Exception, match="parity"):
        build_residual_distribution_v1_forward_attestation(
            release_dir=result["release_dir"],
            live_replay_parity_path=parity_path,
            point_in_time_streaming_path=streaming_path,
            attestation_path=tmp_path / "external" / "blocked.json",
            active_pointer_path=kwargs["active_pointer_path"],
            repo_root=REPO_ROOT,
        )
