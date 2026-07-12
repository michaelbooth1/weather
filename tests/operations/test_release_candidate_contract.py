import json
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from weather.operations.release_candidate_contract import (
    CandidateContractError,
    SEMANTIC_PATHS,
    freeze_candidate_semantic_contract,
    verify_candidate_semantic_contract,
)
from weather.operations.release_manifest import ReleaseLifecycleError, create_release
from weather.operations.release_promotion import promote_release
from weather.release_artifacts import verify_release
from weather.release_contract import SEMANTIC_SERVING_ROLE_KINDS
from weather.release_contract import (
    PRODUCTION_POINT_IN_TIME_ROLE_KINDS,
    RESEARCH_ONLY_CANDIDATE_MODE,
)
from weather.reporting.validation.point_in_time_evaluation import (
    MATERIALIZER_SCHEMA_VERSION,
    POINT_IN_TIME_ARROW_SCHEMA,
    REQUIRED_FIT_STAGES,
    RollingOriginFold,
    build_fit_receipt,
    canonical_json,
    canonicalize_raw_row,
    evaluate_point_in_time_parquet,
    point_in_time_key,
    sha256_file as pit_sha256_file,
    sha256_text,
    validation_plan_payload,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_base_model_fixture(repo: Path, market_id: str = "nyc") -> dict[str, Path]:
    suffix = "" if market_id == "toronto" else f"_{market_id}"
    artifacts = repo / "artifacts"
    paths = {
        "feature_hgb": artifacts / "models" / "hgb" / f"feature_model_hgb{suffix}.pkl",
        "feature_lr_coefficients": (
            artifacts / "models" / "coefs" / f"feature_model_coefs{suffix}.json"
        ),
        "late_day_lr_coefficients": (
            artifacts / "models" / "coefs" / f"late_day_model_coefs{suffix}.json"
        ),
        "calibrated_weights": artifacts / "calibration" / f"calibrated_weights{suffix}.json",
        "probability_calibration": (
            artifacts / "calibration" / f"probability_calibration{suffix}.json"
        ),
        "forecast_error_model": (
            artifacts / "calibration" / f"forecast_error_model{suffix}.json"
        ),
        "settlement_lag_model": (
            artifacts / "calibration" / f"settlement_lag_model{suffix}.json"
        ),
        "afternoon_residual_centering": (
            artifacts / "misc" / "afternoon_residual_centering.json"
        ),
    }
    paths["feature_hgb"].parent.mkdir(parents=True, exist_ok=True)
    with paths["feature_hgb"].open("wb") as handle:
        pickle.dump(
            {
                "12": {
                    "feature_names": ["forecast_high", "high_so_far"],
                    "fixture_component": "feature_hgb",
                }
            },
            handle,
        )
    for component, path in paths.items():
        if component == "feature_hgb":
            continue
        _write_json(
            path,
            {
                "schema_version": f"{component}_fixture_v0.1",
                "fixture_component": component,
                "market_id": market_id if component != "afternoon_residual_centering" else "shared",
            },
        )
    return paths


def _fixture(tmp_path: Path, *, leaking_registry: bool = False) -> dict:
    repo = tmp_path / "repo"
    candidate = tmp_path / "artifacts" / "candidates" / "r1"
    config = repo / "config"
    feature_families = ["forecast_profile"]
    if leaking_registry:
        feature_families.append("settlement-distance-bucket")
    _write_json(
        config / "model_variant_registry.json",
        {
            "schema_version": "model_variant_registry_v0.1",
            "variants": [
                {
                    "variant_id": "candidate",
                    "feature_manifest": {"feature_families": feature_families},
                }
            ],
        },
    )
    _write_json(
        config / "locations.json",
        {
            "schema_version": "locations_v0.1",
            "locations": [
                {
                    "id": "nyc",
                    "market_unit": "F",
                    "polymarket": {"event_slug_prefix": "highest-temperature-in-nyc-on"},
                    "settlement": {
                        "unit": "F",
                        "precision": "whole_degree",
                        "source_type": "wunderground_history",
                        "station_id": "KLGA",
                        "resolution_source_url": "https://example.test/KLGA",
                    },
                }
            ],
        },
    )
    _write_json(config / "location_market_events.json", {"schema_version": "events_v0.1", "locations": []})
    _write_json(config / "markets.json", {"schema_version": "markets_v0.1", "markets": []})
    base_artifacts = _write_base_model_fixture(repo)
    bundle_path = candidate / "model" / "model.pkl"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "schema_version": "pooled_feature_band_hgb_v0.1",
        "feature_schema_version": "toronto_feature_store_v1.6",
        "family_unit": "F",
        "prediction_mode": "band_binary",
        "feature_subset": "all",
        "feature_subset_contract": {"feature_families": ["forecast_profile"]},
        "models": {
            "8": {
                "feature_schema_version": "toronto_feature_store_v1.6",
                "feature_names": ["forecast_high", "band_mid_minus_forecast"],
                "imputer": {"statistics": [80.0, 0.0]},
                "temperature": 1.0,
            }
        },
        "postprocess": {"market_bias_calibration": {"enabled": False}},
        "corpus_lineage": {
            "schema_version": "pooled_training_evaluation_corpus_v0.1",
            "selection_training": {
                "row_count": 20,
                "sha256": "1" * 64,
                "target_date_min": "2024-06-01",
                "target_date_max": "2024-07-01",
            },
            "evaluation": {
                "row_count": 10,
                "sha256": "2" * 64,
                "target_date_min": "2025-06-01",
                "target_date_max": "2025-07-01",
            },
            "final_refit": {
                "row_count": 30,
                "sha256": "3" * 64,
                "target_date_min": "2024-06-01",
                "target_date_max": "2025-07-01",
            },
            "model_input_fields": ["forecast_high", "band_mid_minus_forecast"],
            "evaluation_only_label_fields": ["outcome", "settlement_distance_bucket"],
        },
    }
    with bundle_path.open("wb") as handle:
        pickle.dump(bundle, handle)
    family = candidate / "calibration" / "family.json"
    registry = candidate / "config" / "artifact_registry.json"
    _write_json(family, {"schema_version": "family_calibration_v0.1"})
    _write_json(registry, {"schema_version": "artifact_registry_v0.1", "artifacts": []})
    return {
        "repo": repo,
        "candidate": candidate,
        "bundle": bundle_path,
        "family": family,
        "registry": registry,
        "base_artifacts": base_artifacts,
    }


def _freeze(
    paths: dict,
    *,
    candidate_mode: str = RESEARCH_ONLY_CANDIDATE_MODE,
    point_in_time_artifacts: dict | None = None,
) -> dict:
    return freeze_candidate_semantic_contract(
        candidate_dir=paths["candidate"],
        model_bundle_path=paths["bundle"],
        family_secondary_path=paths["family"],
        artifact_registry_path=paths["registry"],
        repo_root=paths["repo"],
        candidate_id="r1",
        parent_release=None,
        promotion={"verdict": "promote_ready", "promote_markets": ["nyc"]},
        family_unit="F",
        candidate_mode=candidate_mode,
        point_in_time_artifacts=point_in_time_artifacts,
    )


def _production_evidence(paths: dict, *, age_days: int = 0) -> dict[str, Path]:
    evidence = paths["repo"].parent / "production-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc) - timedelta(days=age_days)
    end = now.date() - timedelta(days=1)
    fleet_dates = [
        (end - timedelta(days=16 - offset)).isoformat() for offset in range(17)
    ]
    provenance = {
        "artifact_family": "snapshots_long",
        "source_mode": "validated_parquet",
        "manifest_hash": "fixture-source-manifest",
        "source_file_hash": "fixture-source-file",
    }
    rows = []
    for target_date in fleet_dates:
        for band, probability, label in (("low", 0.8, 1), ("high", 0.2, 0)):
            rows.append(
                canonicalize_raw_row(
                    {
                        "target_date": target_date,
                        "market_id": "nyc",
                        "snapshot_id": "08:00",
                        "range_label": band,
                        "variant_id": "r1.pooled_band",
                        "release_id": "r1",
                        "feature_available_at_utc": f"{target_date}T11:55:00+00:00",
                        "captured_at_utc": f"{target_date}T12:00:00+00:00",
                        "label_quality": "complete",
                        "countable": True,
                        "claim_lane": "weather_only",
                        "replay_serve_parity": "pass",
                        "source_quality": "healthy",
                        "prediction_probability": probability,
                        "label": label,
                        "runtime_identity": "runtime-r1",
                    },
                    provenance=provenance,
                )
            )
    rows.sort(key=point_in_time_key)
    corpus = evidence / "corpus.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=POINT_IN_TIME_ARROW_SCHEMA), corpus)
    corpus_sha = pit_sha256_file(corpus)
    manifest = {
        "schema_version": MATERIALIZER_SCHEMA_VERSION,
        "artifact_type": "point_in_time_materialization_manifest",
        "generated_at_utc": (now - timedelta(minutes=3)).isoformat(),
        "candidate_id": "r1",
        "release_id": "r1",
        "status": "PASS",
        "derived_artifact": {
            "path": str(corpus),
            "sha256": corpus_sha,
            "row_count": len(rows),
            "bytes": corpus.stat().st_size,
            "compression": "zstd",
        },
        "counts": {"source_modes": {"validated_parquet": len(fleet_dates)}},
    }
    manifest["manifest_hash"] = sha256_text(canonical_json(manifest))
    manifest_path = evidence / "materialization_manifest.json"
    _write_json(manifest_path, manifest)

    plan_args = {
        "outer_min_train_dates": 7,
        "inner_min_train_dates": 2,
        "embargo_days": 3,
        "step_dates": 3,
        "generated_at_utc": (now - timedelta(minutes=2)).isoformat(),
        "candidate_id": "r1",
        "release_id": "r1",
        "corpus_sha256": corpus_sha,
        "materialization_manifest_hash": manifest["manifest_hash"],
    }
    seed_plan = validation_plan_payload(fleet_dates, **plan_args)
    receipts = []
    for fold_row in seed_plan["folds"]:
        outer = RollingOriginFold(**fold_row["outer"])
        scoped = [(f"outer/{outer.fold_id}", outer)]
        scoped.extend(
            (
                f"outer/{outer.fold_id}/inner/{inner_row['fold_id']}",
                RollingOriginFold(**inner_row),
            )
            for inner_row in fold_row["inner"]
        )
        for scope, fold in scoped:
            fit_rows = [{"target_date": value, "fold_scope": scope} for value in fold.train_dates]
            validation_rows = [
                {"target_date": value, "fold_scope": scope} for value in fold.validation_dates
            ]
            for stage in REQUIRED_FIT_STAGES:
                receipts.append(
                    build_fit_receipt(
                        fold,
                        fold_scope=scope,
                        stage_name=stage,
                        implementation_identity=f"fixture.{stage}",
                        fit_rows=fit_rows,
                        validation_rows=validation_rows,
                        generated_at_utc=(now - timedelta(minutes=2)).isoformat(),
                    )
                )
    plan = validation_plan_payload(fleet_dates, fit_receipts=receipts, **plan_args)
    plan_path = evidence / "validation_plan.json"
    _write_json(plan_path, plan)
    evaluation = evaluate_point_in_time_parquet(
        corpus,
        manifest_path=manifest_path,
        window_days=14,
        window_end=fleet_dates[-1],
        bootstrap_iterations=10,
        generated_at_utc=(now - timedelta(minutes=1)).isoformat(),
        evaluation_started_at_utc=(now - timedelta(minutes=1)).isoformat(),
        candidate_id="r1",
        release_id="r1",
        validation_plan_hash=plan["plan_hash"],
    )
    evaluation_path = evidence / "streaming_evaluation.json"
    _write_json(evaluation_path, evaluation)
    return {
        "point_in_time_corpus": corpus,
        "point_in_time_materialization_manifest": manifest_path,
        "point_in_time_validation_plan": plan_path,
        "point_in_time_streaming_evaluation": evaluation_path,
    }


def test_candidate_contract_freezes_all_roles_and_release_reverifies_internal_hashes(tmp_path: Path):
    paths = _fixture(tmp_path)
    frozen = _freeze(paths)

    assert frozen["status"] == "PASS"
    assert frozen["audit"]["status"] == "PASS"
    declared_roles = {row["role"] for row in frozen["declarations"]}
    assert set(SEMANTIC_SERVING_ROLE_KINDS) <= declared_roles
    assert declared_roles - set(SEMANTIC_SERVING_ROLE_KINDS) == {
        "base_model.nyc.feature_hgb",
        "base_model.nyc.feature_lr_coefficients",
        "base_model.nyc.late_day_lr_coefficients",
        "base_model.nyc.calibrated_weights",
        "base_model.nyc.probability_calibration",
        "base_model.nyc.forecast_error_model",
        "base_model.nyc.settlement_lag_model",
        "base_model.shared.afternoon_residual_centering",
    }
    result = create_release(
        release_id="r1",
        candidate_dir=paths["candidate"],
        declarations=frozen["declarations"],
        route=frozen["route"],
        expected_live_runtimes=["snapshot_loop"],
        releases_root=tmp_path / "releases",
        repo_root=paths["repo"],
        code_identity={
            "git_commit": "a" * 40,
            "git_branch": "main",
            "git_dirty": False,
            "dirty_fingerprint": None,
        },
        runtime_versions={
            "python": "3.13.0",
            "implementation": "CPython",
            "platform": "test",
            "direct_dependencies": {
                "scikit-learn": {"version": "1.7.0", "declared": "scikit-learn"}
            },
        },
        runtime_identity={"source_fingerprint": "source", "git_commit": "a" * 40},
    )
    verified = verify_release(result["release_dir"], check_runtime=False)

    assert verified["semantic_contract_verified"] is True
    assert verified["semantic_contract"]["status"] == "PASS"
    assert verified["semantic_contract"]["candidate_mode"] == "research_only"
    assert verified["semantic_contract"]["production_capable"] is False
    assert verified["semantic_contract"]["role_count"] == len(frozen["declarations"])
    with pytest.raises(ReleaseLifecycleError, match="research-only release"):
        promote_release(
            "r1",
            decision={},
            market_day_boundary={},
            releases_root=tmp_path / "releases",
            pointer_path=tmp_path / "releases" / "current_release.json",
            repo_root=paths["repo"],
            current_runtime_versions={
                "python": "3.13.0",
                "implementation": "CPython",
                "platform": "test",
                "direct_dependencies": {
                    "scikit-learn": {"version": "1.7.0", "declared": "scikit-learn"}
                },
            },
            current_runtime_identity={
                "source_fingerprint": "source",
                "git_commit": "a" * 40,
            },
            current_code_identity={
                "git_commit": "a" * 40,
                "git_branch": "main",
                "git_dirty": False,
                "dirty_fingerprint": None,
            },
        )


def test_candidate_contract_persists_rejections_and_refuses_release_on_hidden_alias(tmp_path: Path):
    paths = _fixture(tmp_path, leaking_registry=True)

    with pytest.raises(CandidateContractError, match="leakage audit BLOCK"):
        _freeze(paths)

    audit_path = paths["candidate"] / SEMANTIC_PATHS["candidate_input_leakage_audit"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["status"] == "BLOCK"
    assert audit["rejection_count"] == 1
    assert audit["rejections"][0]["value"] == "settlement-distance-bucket"
    assert not (paths["candidate"] / SEMANTIC_PATHS["semantic_serving_contract"]).exists()


@pytest.mark.parametrize("role", ["family", "registry"])
def test_candidate_contract_recursively_scans_calibration_and_artifact_registry_inputs(
    tmp_path: Path,
    role: str,
):
    paths = _fixture(tmp_path)
    path = paths[role]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["guardrail"] = {
        "feature_hash_inputs": {
            "feature_families": ["forecast_profile", "post-event-winner"]
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CandidateContractError, match="leakage audit BLOCK"):
        _freeze(paths)

    audit = json.loads(
        (
            paths["candidate"]
            / SEMANTIC_PATHS["candidate_input_leakage_audit"]
        ).read_text(encoding="utf-8")
    )
    assert audit["rejection_count"] == 1
    assert audit["rejections"][0]["source"] in {
        "family_secondary_calibration",
        "artifact_registry",
    }
    assert audit["rejections"][0]["value"] == "post-event-winner"


def test_candidate_verifier_rejects_sidecar_tampering(tmp_path: Path):
    paths = _fixture(tmp_path)
    _freeze(paths)
    feature_path = paths["candidate"] / SEMANTIC_PATHS["pooled_feature_schema"]
    feature = json.loads(feature_path.read_text(encoding="utf-8"))
    feature["family_unit"] = "C"
    feature_path.write_text(json.dumps(feature), encoding="utf-8")

    with pytest.raises(CandidateContractError, match="hash verification failed"):
        verify_candidate_semantic_contract(paths["candidate"])


@pytest.mark.parametrize(
    "component",
    [
        "feature_hgb",
        "feature_lr_coefficients",
        "late_day_lr_coefficients",
        "calibrated_weights",
        "probability_calibration",
        "forecast_error_model",
        "settlement_lag_model",
        "afternoon_residual_centering",
    ],
)
def test_candidate_contract_refuses_an_omitted_base_serving_component(
    tmp_path: Path,
    component: str,
):
    paths = _fixture(tmp_path)
    paths["base_artifacts"][component].unlink()

    with pytest.raises(CandidateContractError, match="missing or invalid"):
        _freeze(paths)


def test_production_candidate_freezes_and_release_reverifies_point_in_time_graph(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)

    frozen = _freeze(
        paths,
        candidate_mode="production",
        point_in_time_artifacts=evidence,
    )

    assert frozen["production_capable"] is True
    assert frozen["point_in_time_qualification"]["locked_window_days"] == 14
    assert frozen["point_in_time_qualification"]["corpus_structure_reverified"] is True
    assert set(PRODUCTION_POINT_IN_TIME_ROLE_KINDS) <= {
        row["role"] for row in frozen["declarations"]
    }
    result = create_release(
        release_id="r1",
        candidate_dir=paths["candidate"],
        declarations=frozen["declarations"],
        route=frozen["route"],
        expected_live_runtimes=["snapshot_loop"],
        releases_root=tmp_path / "releases",
        repo_root=paths["repo"],
        code_identity={
            "git_commit": "a" * 40,
            "git_branch": "main",
            "git_dirty": False,
            "dirty_fingerprint": None,
        },
        runtime_versions={
            "python": "3.13.0",
            "implementation": "CPython",
            "platform": "test",
            "direct_dependencies": {
                "scikit-learn": {"version": "1.7.0", "declared": "scikit-learn"}
            },
        },
        runtime_identity={"source_fingerprint": "source", "git_commit": "a" * 40},
    )

    verified = verify_release(result["release_dir"], check_runtime=False)
    assert verified["semantic_contract"]["production_capable"] is True
    assert verified["semantic_contract"]["point_in_time_qualification"][
        "corpus_structure_reverified"
    ] is False
    assert verified["semantic_contract"]["point_in_time_qualification"][
        "verification_mode"
    ] == "immutable_release_hash_graph_reverification"
    assert verified["semantic_contract"]["point_in_time_qualification"][
        "validation_plan_hash"
    ] == frozen["point_in_time_qualification"]["validation_plan_hash"]


@pytest.mark.parametrize("missing_role", sorted(PRODUCTION_POINT_IN_TIME_ROLE_KINDS))
def test_production_candidate_fails_closed_when_a_required_evidence_role_is_missing(
    tmp_path: Path,
    missing_role: str,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    evidence.pop(missing_role)

    with pytest.raises(CandidateContractError, match="exact point-in-time artifact role set"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_rejects_tampered_evaluation(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    evaluation_path = evidence["point_in_time_streaming_evaluation"]
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    evaluation["counts"]["window_rows"] += 1
    _write_json(evaluation_path, evaluation)

    with pytest.raises(CandidateContractError, match="evaluation_hash"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_rejects_wrong_corpus_binding(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    plan_path = evidence["point_in_time_validation_plan"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["corpus_binding"]["corpus_sha256"] = "f" * 64
    plan.pop("plan_hash")
    plan["plan_hash"] = sha256_text(canonical_json(plan))
    _write_json(plan_path, plan)

    with pytest.raises(CandidateContractError, match="corpus hash mismatch"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_rejects_window_selected_after_evaluation(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    evaluation_path = evidence["point_in_time_streaming_evaluation"]
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    started = datetime.fromisoformat(evaluation["evaluation_started_at_utc"])
    evaluation["window_lock"]["generated_at_utc"] = (
        started + timedelta(seconds=1)
    ).isoformat()
    evaluation.pop("evaluation_hash")
    evaluation["evaluation_hash"] = sha256_text(canonical_json(evaluation))
    _write_json(evaluation_path, evaluation)

    with pytest.raises(CandidateContractError, match="selected after scoring began"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_rejects_stale_evaluation(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths, age_days=8)

    with pytest.raises(CandidateContractError, match="evaluation is stale"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )
