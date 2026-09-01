import hashlib
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
from weather.operations.release_promotion import (
    MARKET_DAY_BOUNDARY_SCHEMA_VERSION,
    PROMOTION_DECISION_SCHEMA_VERSION,
    promote_release,
)
from weather.point_in_time_contract import (
    verify_embedded_point_in_time_training_evidence,
    verify_point_in_time_selection_binding,
    verify_production_point_in_time_artifacts,
)
from weather.paths import REPO_ROOT
from weather.release_artifacts import load_active_release_pointer, verify_release
from weather.release_contract import SEMANTIC_SERVING_ROLE_KINDS
from weather.release_contract import (
    PRODUCTION_POINT_IN_TIME_ROLE_KINDS,
    RESEARCH_ONLY_CANDIDATE_MODE,
    SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
)
from weather.reporting.validation.point_in_time_evaluation import (
    CANDIDATE_TRAINING_GRAPH_SCHEMA_VERSION,
    MATERIALIZER_SCHEMA_VERSION,
    POINT_IN_TIME_ARROW_SCHEMA,
    REQUIRED_FIT_STAGES,
    RollingOriginFold,
    build_fit_receipt,
    build_window_lock,
    canonical_json,
    canonicalize_raw_row,
    evaluate_point_in_time_parquet,
    point_in_time_key,
    selection_universe_contract,
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
                    "model": {
                        "n_features_in_": 2,
                        "feature_names_in_": ["forecast_high", "high_so_far"],
                    },
                    "fixture_component": "feature_hgb",
                }
            },
            handle,
        )
    for component, path in paths.items():
        if component == "feature_hgb":
            continue
        if component in {"feature_lr_coefficients", "late_day_lr_coefficients"}:
            _write_json(
                path,
                {
                    "fixture_component": component,
                    "12": {
                        "feature_names": ["forecast_high", "high_so_far"],
                        "coef": [1.0, 0.0],
                        "classes": [0, 1],
                        "fixture_component": component,
                    }
                },
            )
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
                "model": {
                    "n_features_in_": 2,
                    "feature_names_in_": [
                        "forecast_high",
                        "band_mid_minus_forecast",
                    ],
                },
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
    promotion = {
        "verdict": "promote_ready",
        "promote_markets": ["nyc"],
        "shadow_markets": [],
        "blocked_markets": [],
    }
    if paths.get("promotion") is not None:
        promotion["path"] = str(paths["promotion"])
    return freeze_candidate_semantic_contract(
        candidate_dir=paths["candidate"],
        model_bundle_path=paths["bundle"],
        family_secondary_path=paths["family"],
        artifact_registry_path=paths["registry"],
        repo_root=paths["repo"],
        candidate_id="r1",
        parent_release=None,
        promotion=promotion,
        family_unit="F",
        candidate_mode=candidate_mode,
        point_in_time_artifacts=point_in_time_artifacts,
        code_repo_root=REPO_ROOT,
    )


def _finalize_contract_hash(payload: dict, field: str) -> dict:
    finalized = dict(payload)
    finalized.pop(field, None)
    finalized[field] = sha256_text(canonical_json(finalized))
    return finalized


def _fixture_selection_binding(
    *,
    stage: str,
    preselection_hash: str,
    lock: dict,
    selection_dates: list[str],
    source_entries: list[dict] | None = None,
    output_inventory: dict | None = None,
    require_trust_cutoff: bool = False,
    selection_universe_sha256: str | None = None,
) -> dict:
    locked = set(lock["target_dates"])
    source_inventory = {
        "entries": source_entries
        if source_entries is not None
        else [
            {
                "folder": f"data/{stage}/{target_date}",
                "target_date": target_date,
                "market_id": "nyc",
            }
            for target_date in selection_dates
            if target_date not in locked
        ],
    }
    source_inventory["entry_count"] = len(source_inventory["entries"])
    if source_entries is not None:
        source_inventory["folder_count"] = sum(
            int(row.get("folder_count") or 0) for row in source_entries
        )
        source_inventory["row_count"] = sum(
            int(row.get("row_count") or 0) for row in source_entries
        )
    source_inventory = _finalize_contract_hash(source_inventory, "sha256")
    binding = {
        "preselection_hash": preselection_hash,
        "window_lock_id": lock["window_lock_id"],
        "locked_dates": list(lock["target_dates"]),
        "used_for_selection": False,
        "source_folder_date_inventory_sha256": source_inventory["sha256"],
        "source_inventory": source_inventory,
    }
    if require_trust_cutoff:
        training_dates = [
            value for value in selection_dates if value not in locked
        ]
        binding.update(
            {
                "selection_universe_sha256": selection_universe_sha256,
                "selection_universe_dates": list(selection_dates),
                "training_universe_dates": training_dates,
                "training_universe_sha256": sha256_text(
                    canonical_json(training_dates)
                ),
                "trust_date_scope": "exact_preselection_training_universe",
                "trust_included_target_dates_sha256": sha256_text(
                    canonical_json(training_dates)
                ),
            }
        )
        binding["trust_as_of_exclusive"] = lock["target_dates"][0]
    if output_inventory is not None:
        binding["output_artifact_inventory_sha256"] = output_inventory["sha256"]
        binding["output_artifacts"] = output_inventory
    return _finalize_contract_hash(binding, "binding_sha256")


def _fixture_family_secondary_manifest(
    paths: dict,
    *,
    preselection_hash: str,
    lock: dict,
    selection_dates: list[str],
    selection_universe_sha256: str,
) -> dict:
    artifact_root = (
        paths["candidate"] / "calibration" / "family_secondary_components"
    ).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    family_artifacts = {}
    market_artifacts = {}
    output_entries = []
    kinds = ("probability_calibration", "forecast_error", "settlement_lag")
    for fit_scope, market_id, destination in (
        ("family:F", "", family_artifacts),
        ("market", "nyc", market_artifacts),
    ):
        scope_name = "family_f" if fit_scope == "family:F" else "market_nyc"
        for artifact_kind in kinds:
            artifact_path = artifact_root / f"{scope_name}_{artifact_kind}.json"
            _write_json(
                artifact_path,
                {
                    "schema_version": f"{artifact_kind}_fixture_v0.1",
                    "artifact_kind": artifact_kind,
                    "fit_scope": fit_scope,
                    "market_id": market_id,
                },
            )
            digest = pit_sha256_file(artifact_path)
            byte_count = artifact_path.stat().st_size
            destination[artifact_kind] = {
                "status": "ok",
                "artifact": artifact_path.as_posix(),
                "artifact_sha256": digest,
                "artifact_bytes": byte_count,
            }
            output_entries.append(
                {
                    "artifact_kind": artifact_kind,
                    "fit_scope": fit_scope,
                    "market_id": market_id,
                    "path": artifact_path.as_posix(),
                    "sha256": digest,
                    "bytes": byte_count,
                }
            )
    output_entries.sort(
        key=lambda row: (
            row["artifact_kind"],
            row["fit_scope"],
            row["market_id"],
        )
    )
    output_inventory = _finalize_contract_hash(
        {
            "entries": output_entries,
            "entry_count": len(output_entries),
        },
        "sha256",
    )
    selected_date = next(
        value for value in selection_dates if value not in set(lock["target_dates"])
    )
    source_entries = [
        {
            "artifact_kind": artifact_kind,
            "fit_scope": fit_scope,
            "market_id": "nyc",
            "row_count": 1,
            "row_target_dates": [
                {"target_date": selected_date, "row_count": 1}
            ],
            "folder_count": 1,
            "folders": [
                {
                    "folder": f"data/calibration/{fit_scope}/{artifact_kind}",
                    "target_date": selected_date,
                }
            ],
        }
        for artifact_kind in kinds
        for fit_scope in ("family:F", "market")
    ]
    binding = _fixture_selection_binding(
        stage="calibration",
        preselection_hash=preselection_hash,
        lock=lock,
        selection_dates=selection_dates,
        source_entries=source_entries,
        output_inventory=output_inventory,
        require_trust_cutoff=True,
        selection_universe_sha256=selection_universe_sha256,
    )
    return {
        "schema_version": "family_secondary_artifacts_v0.1",
        "family_unit": "F",
        "artifact_root": str(artifact_root),
        "family_artifacts": family_artifacts,
        "markets": {"nyc": {"artifacts": market_artifacts}},
        "output_artifact_inventory": output_inventory,
        "point_in_time_selection_binding": binding,
    }


def _fixture_pooled_serving_contract(bundle: dict) -> dict:
    fit_contract = bundle.get("postprocess_fit_contract") or {}
    static_context = bundle.get("production_static_context") or {}
    return {
        "schema_version": bundle.get("schema_version"),
        "feature_schema_version": bundle.get("feature_schema_version"),
        "family_unit": bundle.get("family_unit"),
        "prediction_mode": bundle.get("prediction_mode"),
        "objective": bundle.get("objective"),
        "feature_subset": bundle.get("feature_subset"),
        "feature_subset_contract": bundle.get("feature_subset_contract"),
        "dynamic_source_state_enabled": bundle.get("dynamic_source_state_enabled"),
        "postprocess": bundle.get("postprocess"),
        "production_static_context_sha256": static_context.get("context_sha256"),
        "production_external_sidecar_policy": static_context.get(
            "external_sidecar_policy"
        ),
        "postprocess_fit_contract": {
            key: fit_contract.get(key)
            for key in (
                "schema_version",
                "status",
                "policy",
                "served_parameters",
                "preselection_hash",
                "window_lock_id",
                "locked_dates",
                "promotion_permission",
            )
            if key in fit_contract
        },
    }


def _production_evidence(
    paths: dict,
    *,
    age_days: int = 0,
    target_age_days: int = 1,
) -> dict[str, Path]:
    evidence = paths["repo"].parent / "production-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc) - timedelta(days=age_days)
    end = now.date() - timedelta(days=target_age_days)
    fleet_dates = [
        (end - timedelta(days=29 - offset)).isoformat() for offset in range(30)
    ]
    source_replay_manifest_sha = "b" * 64
    source_replay_corpus_hash = "a" * 64
    preselection_hash = "c" * 64
    route_selection = {
        "verdict": "promote_ready",
        "promote_markets": ["nyc"],
        "shadow_markets": [],
        "blocked_markets": [],
    }
    def candidate_rows(candidate_artifact_sha256: str) -> list[dict]:
        provenance = {
            "artifact_family": "bounded_pooled_band_candidate_replay",
            "source_mode": "promotion_manifest_pinned_candidate_replay",
            "manifest_hash": source_replay_corpus_hash,
            "source_replay_manifest_sha256": source_replay_manifest_sha,
            "candidate_artifact_sha256": candidate_artifact_sha256,
        }
        output = []
        for target_date in fleet_dates:
            for band, probability, label in (("low", 0.8, 1), ("high", 0.2, 0)):
                output.append(
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
        output.sort(key=point_in_time_key)
        return output

    rows = candidate_rows("0" * 64)
    corpus = evidence / "corpus.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=POINT_IN_TIME_ARROW_SCHEMA), corpus)
    corpus_sha = pit_sha256_file(corpus)
    selection_universe = selection_universe_contract(corpus)
    lock = build_window_lock(
        fleet_dates,
        input_sha256=selection_universe["sha256"],
        input_kind="selection_universe_sha256",
        window_days=14,
        window_end=fleet_dates[-1],
        generated_at_utc=(now - timedelta(minutes=4)).isoformat(),
    )
    resources = {
        "host_physical_memory_bytes": int(15.7 * 1024**3),
        "private_memory_budget_bytes": 4 * 1024**3,
        "corpus_read_mode": "market_day_streaming",
        "raw_market_days_retained_at_once": 1,
        "max_market_days": 60,
        "max_rows_per_market_day": 250_000,
        "parquet_batch_rows": 65_536,
        "max_fold_scopes": 128,
    }
    seed_args = {
        "outer_min_train_dates": 7,
        "inner_min_train_dates": 2,
        "embargo_days": 3,
        "step_dates": 3,
        "generated_at_utc": (now - timedelta(minutes=2)).isoformat(),
        "candidate_id": "r1",
        "release_id": "r1",
        "corpus_sha256": corpus_sha,
        "materialization_manifest_hash": "0" * 64,
        "selection_excluded_dates": lock["target_dates"],
        "selection_window_lock": lock,
        "resource_contract": resources,
    }
    seed_plan = validation_plan_payload(fleet_dates, **seed_args)
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
            upstream_stage_output_sha256 = None
            for stage in REQUIRED_FIT_STAGES:
                fit_output_rows = [
                    {
                        **row,
                        "completed_stages": [
                            *(row.get("completed_stages") or []),
                            stage,
                        ],
                    }
                    for row in fit_rows
                ]
                validation_output_rows = [
                    {
                        **row,
                        "completed_stages": [
                            *(row.get("completed_stages") or []),
                            stage,
                        ],
                    }
                    for row in validation_rows
                ]
                receipt = build_fit_receipt(
                    fold,
                    fold_scope=scope,
                    stage_name=stage,
                    implementation_identity=f"fixture.{stage}",
                    fit_rows=fit_rows,
                    validation_rows=validation_rows,
                    fit_output_rows=fit_output_rows,
                    validation_output_rows=validation_output_rows,
                    stage_input_payload={"scope": scope, "stage": stage},
                    stage_output_payload={
                        "implementation_identity": f"fixture.{stage}",
                        "stage": stage,
                    },
                    upstream_stage_output_sha256=upstream_stage_output_sha256,
                    generated_at_utc=(now - timedelta(minutes=2)).isoformat(),
                )
                receipts.append(receipt)
                upstream_stage_output_sha256 = receipt["stage_output_sha256"]
                fit_rows = fit_output_rows
                validation_rows = validation_output_rows
    scope_count = sum(1 + len(row["inner"]) for row in seed_plan["folds"])
    resources.update(
        {
            "observed_fold_scopes": scope_count,
            "observed_market_days": len(fleet_dates),
            "observed_peak_rows_per_market_day": 2,
            "replay_artifact_loads_retained_at_once": 1,
        }
    )
    training_generated_at = (now - timedelta(minutes=3)).isoformat()
    training_dates = sorted(set(fleet_dates) - set(lock["target_dates"]))
    with paths["bundle"].open("rb") as handle:
        bundle = pickle.load(handle)
    bundle["postprocess_fit_contract"] = {
        "schema_version": "pooled_nested_postprocess_fit_contract_v1",
        "status": "PASS",
        "policy": "nested_training_only",
        "served_parameters": "identity",
        "preselection_hash": preselection_hash,
        "window_lock_id": lock["window_lock_id"],
        "locked_dates": list(lock["target_dates"]),
        "promotion_permission": "requires_locked_evaluation",
    }
    model_hashes = {
        str(hour): sha256_text(canonical_json(model))
        for hour, model in bundle["models"].items()
    }
    serving_contract = _fixture_pooled_serving_contract(bundle)
    serving_contract_sha = sha256_text(canonical_json(serving_contract))
    model_payload_sha = sha256_text(
        canonical_json(
            {
                "model_sha256_by_hour": model_hashes,
                "artifact_serving_contract_sha256": serving_contract_sha,
            }
        )
    )
    parent_receipts_sha = sha256_text(
        canonical_json(sorted(row["receipt_sha256"] for row in receipts))
    )
    final_stage_input = {
        "fit_input_sha256": "4" * 64,
        "fit_row_count": len(training_dates) * 2,
        "train_dates": training_dates,
        "locked_dates": list(lock["target_dates"]),
        "preselection_hash": preselection_hash,
        "window_lock_id": lock["window_lock_id"],
        "parent_fit_receipts_sha256": parent_receipts_sha,
    }
    final_stage_output = {
        "model_payload_sha256": model_payload_sha,
        "model_sha256_by_hour": model_hashes,
        "artifact_serving_contract": serving_contract,
        "artifact_serving_contract_sha256": serving_contract_sha,
        "model_count": len(model_hashes),
        "feature_schema_version": bundle["feature_schema_version"],
        "support_sha256": sha256_text(canonical_json(bundle.get("support"))),
    }
    final_receipt = _finalize_contract_hash(
        {
            "schema_version": "pooled_band_final_refit_receipt_v1",
            "artifact_type": "pooled_band_final_refit_receipt",
            "generated_at_utc": (now - timedelta(minutes=2, seconds=45)).isoformat(),
            "fit_role": "prelock_excluded_final_refit",
            "fit_scope": "all_unlocked_training_rows",
            "fit_input_sha256": final_stage_input["fit_input_sha256"],
            "fit_row_count": final_stage_input["fit_row_count"],
            "train_dates": training_dates,
            "locked_dates": list(lock["target_dates"]),
            "preselection_hash": preselection_hash,
            "window_lock_id": lock["window_lock_id"],
            "selection_universe_sha256": selection_universe["sha256"],
            "parent_fit_receipts_sha256": parent_receipts_sha,
            "model_payload_sha256": model_payload_sha,
            "model_sha256_by_hour": model_hashes,
            "artifact_serving_contract_sha256": serving_contract_sha,
            "payload_hash_algorithm": "sha256",
            "payload_canonicalization": "canonical_json",
            "stage_input_payload": final_stage_input,
            "stage_input_sha256": sha256_text(canonical_json(final_stage_input)),
            "stage_output_payload": final_stage_output,
            "stage_output_sha256": sha256_text(canonical_json(final_stage_output)),
        },
        "receipt_sha256",
    )
    training_evidence = _finalize_contract_hash(
        {
            "schema_version": "pooled_band_point_in_time_training_v1",
            "status": "PASS",
            "generated_at_utc": training_generated_at,
            "preselection_lock": {
                "preselection_hash": preselection_hash,
                "window_lock_id": lock["window_lock_id"],
                "locked_at_utc": lock["generated_at_utc"],
                "locked_dates": list(lock["target_dates"]),
                "selection_universe_sha256": selection_universe["sha256"],
                "selection_universe_dates": fleet_dates,
                "selection_universe_row_count": selection_universe["row_count"],
                "training_universe_dates": training_dates,
                "training_universe_sha256": sha256_text(
                    canonical_json(training_dates)
                ),
                "locked_dates_used_for_selection": False,
                "candidate_selection_permission": "forbidden",
            },
            "fold_config": {
                "outer_min_train_dates": 7,
                "inner_min_train_dates": 2,
                "outer_validation_dates": 1,
                "inner_validation_dates": 1,
                "embargo_days": 3,
                "step_dates": 3,
            },
            "folds": seed_plan["folds"],
            "fit_receipt_contract": {
                "fit_scope": "training_only",
                "required_stages": list(REQUIRED_FIT_STAGES),
                "stage_order": list(REQUIRED_FIT_STAGES),
                "scope_count": scope_count,
                "max_fold_scopes": 128,
                "payload_binding_required": True,
                "payload_hash_algorithm": "sha256",
                "payload_canonicalization": "canonical_json",
            },
            "fit_receipts": receipts,
            "resource_contract": resources,
            "final_fit_receipt": final_receipt,
        },
        "evidence_sha256",
    )
    bundle["point_in_time_training"] = training_evidence
    bundle["postprocess_fit_contract"].update(
        {
            "evidence_sha256": training_evidence["evidence_sha256"],
            "final_fit_receipt_sha256": final_receipt["receipt_sha256"],
            "model_payload_sha256": model_payload_sha,
        }
    )
    with paths["bundle"].open("wb") as handle:
        pickle.dump(bundle, handle)
    embedded_training_evidence = verify_embedded_point_in_time_training_evidence(
        bundle
    )
    model_sha = pit_sha256_file(paths["bundle"])

    rows = candidate_rows(model_sha)
    pq.write_table(pa.Table.from_pylist(rows, schema=POINT_IN_TIME_ARROW_SCHEMA), corpus)
    corpus_sha = pit_sha256_file(corpus)
    rebuilt_selection_universe = selection_universe_contract(corpus)
    assert rebuilt_selection_universe == selection_universe
    seed_args["corpus_sha256"] = corpus_sha
    final_seed_plan = validation_plan_payload(fleet_dates, **seed_args)
    assert final_seed_plan["folds"] == seed_plan["folds"]
    seed_plan = final_seed_plan

    family_payload = _fixture_family_secondary_manifest(
        paths,
        preselection_hash=preselection_hash,
        lock=lock,
        selection_dates=fleet_dates,
        selection_universe_sha256=selection_universe["sha256"],
    )
    _write_json(paths["family"], family_payload)
    calibration_sha = pit_sha256_file(paths["family"])

    receipt_paths = {
        "base_model.nyc.feature_hgb": paths["base_artifacts"]["feature_hgb"],
        "base_model.nyc.feature_lr_coefficients": paths["base_artifacts"][
            "feature_lr_coefficients"
        ],
        "base_model.nyc.late_day_lr_coefficients": paths["base_artifacts"][
            "late_day_lr_coefficients"
        ],
        "base_model.nyc.calibrated_weights": paths["base_artifacts"][
            "calibrated_weights"
        ],
        "base_model.nyc.probability_calibration": paths["base_artifacts"][
            "probability_calibration"
        ],
        "base_model.nyc.forecast_error_model": paths["base_artifacts"][
            "forecast_error_model"
        ],
        "base_model.nyc.settlement_lag_model": paths["base_artifacts"][
            "settlement_lag_model"
        ],
        "base_model.shared.afternoon_residual_centering": paths[
            "base_artifacts"
        ]["afternoon_residual_centering"],
        "family_secondary_calibration": paths["family"],
    }
    training_receipts = {}
    for role, artifact_path in sorted(receipt_paths.items()):
        if artifact_path.suffix.casefold() == ".json" and role != "family_secondary_calibration":
            canonical_candidate_bytes = (
                json.dumps(
                    json.loads(artifact_path.read_text(encoding="utf-8")),
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            output_sha256 = hashlib.sha256(canonical_candidate_bytes).hexdigest()
        else:
            output_sha256 = pit_sha256_file(artifact_path)
        receipt = {
            "schema_version": "model_artifact_fit_receipt_v0.1",
            "artifact_role": role,
            "output_content_sha256": output_sha256,
            "partition_sha256": "3" * 64,
            "row_count": 30,
            "evidence_sha256": embedded_training_evidence["evidence_sha256"],
        }
        receipt["receipt_sha256"] = sha256_text(canonical_json(receipt))
        training_receipts[role] = receipt
    _write_json(
        paths["registry"],
        {
            "schema_version": "artifact_registry_v0.1",
            "artifacts": [],
            "model_bom_training_receipts": training_receipts,
        },
    )

    routing_binding = _fixture_selection_binding(
        stage="routing",
        preselection_hash=preselection_hash,
        lock=lock,
        selection_dates=fleet_dates,
    )
    routing_artifact = evidence / "promotion.json"
    routing_payload = {
        "schema_version": "promotion_refresh_fixture_v0.1",
        "decisions": {
            "promote_markets": ["nyc"],
            "shadow_markets": [],
            "blocked_markets": [],
        },
        "point_in_time_selection_binding": routing_binding,
    }
    _write_json(routing_artifact, routing_payload)
    paths["promotion"] = routing_artifact
    routing_sha = pit_sha256_file(routing_artifact)
    selection_stage_bindings = {
        "calibration": verify_point_in_time_selection_binding(
            family_payload,
            stage="calibration",
        ),
        "routing": verify_point_in_time_selection_binding(
            routing_payload,
            stage="routing",
        ),
    }
    graph = {
        "schema_version": CANDIDATE_TRAINING_GRAPH_SCHEMA_VERSION,
        "artifact_type": "point_in_time_candidate_training_graph",
        "status": "PASS",
        "candidate_id": "r1",
        "release_id": "r1",
        "preselection_hash": preselection_hash,
        "window_lock_id": lock["window_lock_id"],
        "selection_universe_sha256": selection_universe["sha256"],
        "training_evidence_sha256": embedded_training_evidence[
            "evidence_sha256"
        ],
        "training_evidence_generated_at_utc": embedded_training_evidence[
            "generated_at_utc"
        ],
        "folds_sha256": sha256_text(
            canonical_json(embedded_training_evidence["folds"])
        ),
        "fit_receipts_sha256": sha256_text(
            canonical_json(
                sorted(
                    row["receipt_sha256"]
                    for row in embedded_training_evidence["fit_receipts"]
                )
            )
        ),
        "final_fit_receipt_sha256": embedded_training_evidence[
            "final_fit_receipt"
        ]["receipt_sha256"],
        "candidate_artifacts": {
            "model_sha256": model_sha,
            "calibration_sha256": calibration_sha,
            "routing_sha256": routing_sha,
        },
        "route_selection": route_selection,
        "route_selection_sha256": sha256_text(canonical_json(route_selection)),
        "selection_stage_bindings": selection_stage_bindings,
        "selection_stage_bindings_sha256": sha256_text(
            canonical_json(selection_stage_bindings)
        ),
        "source_replay_manifest_sha256": source_replay_manifest_sha,
        "source_replay_corpus_hash": source_replay_corpus_hash,
        "locked_dates_used_for_selection": False,
    }
    graph["graph_hash"] = sha256_text(canonical_json(graph))
    manifest = {
        "schema_version": MATERIALIZER_SCHEMA_VERSION,
        "artifact_type": "point_in_time_materialization_manifest",
        "generated_at_utc": (now - timedelta(minutes=2, seconds=30)).isoformat(),
        "candidate_id": "r1",
        "release_id": "r1",
        "status": "PASS",
        "preselection_hash": preselection_hash,
        "derived_artifact": {
            "path": str(corpus),
            "sha256": corpus_sha,
            "row_count": len(rows),
            "bytes": corpus.stat().st_size,
            "compression": "zstd",
        },
        "streaming_bounds": {
            "max_market_days": 60,
            "max_rows_per_market_day": 250_000,
            "raw_market_days_retained_at_once": 1,
            "observed_market_days": len(fleet_dates),
            "observed_peak_rows_per_market_day": 2,
        },
        "counts": {
            "source_modes": {
                "promotion_manifest_pinned_candidate_replay": len(rows)
            }
        },
        "candidate_training_graph": graph,
        "candidate_training_graph_hash": graph["graph_hash"],
        "inputs": [
            {
                "folder": f"data/snapshots/fleet-{target_date}",
                "target_date": target_date,
                "market_id": "nyc",
                "artifact_family": "bounded_pooled_band_candidate_replay",
                "source_mode": "promotion_manifest_pinned_candidate_replay",
                "source_row_count": 2,
                "source_file_hash": hashlib.sha256(
                    f"source:{target_date}".encode("utf-8")
                ).hexdigest(),
                "parquet_file_hash": hashlib.sha256(
                    f"parquet:{target_date}".encode("utf-8")
                ).hexdigest(),
                "manifest_hash": source_replay_corpus_hash,
                "event_manifest_hash": hashlib.sha256(
                    f"event-manifest:{target_date}".encode("utf-8")
                ).hexdigest(),
                "release_id": "r1",
                "runtime_identity_key": "runtime-r1",
                "fallback_reason": None,
                "candidate_artifact_sha256": model_sha,
                "source_replay_manifest_sha256": source_replay_manifest_sha,
                "replay_record_set_sha256": hashlib.sha256(
                    f"replay:{target_date}".encode("utf-8")
                ).hexdigest(),
                "tape_row_set_sha256": hashlib.sha256(
                    f"tape:{target_date}".encode("utf-8")
                ).hexdigest(),
            }
            for target_date in fleet_dates
        ],
    }
    manifest["manifest_hash"] = sha256_text(canonical_json(manifest))
    manifest_path = evidence / "materialization_manifest.json"
    _write_json(manifest_path, manifest)
    plan_args = {
        **seed_args,
        "materialization_manifest_hash": manifest["manifest_hash"],
        "resource_contract": resources,
    }
    plan = validation_plan_payload(
        fleet_dates,
        fit_receipts=receipts,
        require_output_bound_receipts=True,
        **plan_args,
    )
    plan.pop("plan_hash")
    plan["candidate_training_graph"] = graph
    plan["candidate_training_graph_hash"] = graph["graph_hash"]
    plan["plan_hash"] = sha256_text(canonical_json(plan))
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
        candidate_artifact_sha256=model_sha,
        validation_plan_hash=plan["plan_hash"],
        window_lock=lock,
    )
    evaluation.pop("evaluation_hash")
    evaluation["contract_binding"].update(
        {
            "candidate_training_graph_hash": graph["graph_hash"],
            "selection_universe_sha256": selection_universe["sha256"],
        }
    )
    evaluation["evaluation_hash"] = sha256_text(canonical_json(evaluation))
    evaluation_path = evidence / "streaming_evaluation.json"
    _write_json(evaluation_path, evaluation)
    return {
        "point_in_time_corpus": corpus,
        "point_in_time_materialization_manifest": manifest_path,
        "point_in_time_validation_plan": plan_path,
        "point_in_time_streaming_evaluation": evaluation_path,
    }


def _rehash_plan_and_evaluation(
    evidence: dict[str, Path],
    *,
    mutate_plan,
) -> None:
    plan_path = evidence["point_in_time_validation_plan"]
    evaluation_path = evidence["point_in_time_streaming_evaluation"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    mutate_plan(plan)
    plan.pop("plan_hash", None)
    plan["plan_hash"] = sha256_text(canonical_json(plan))
    _write_json(plan_path, plan)
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    evaluation["contract_binding"]["validation_plan_hash"] = plan["plan_hash"]
    evaluation.pop("evaluation_hash", None)
    evaluation["evaluation_hash"] = sha256_text(canonical_json(evaluation))
    _write_json(evaluation_path, evaluation)


def _rehash_graph_across_packet(
    evidence: dict[str, Path],
    *,
    mutate_graph,
) -> None:
    manifest_path = evidence["point_in_time_materialization_manifest"]
    plan_path = evidence["point_in_time_validation_plan"]
    evaluation_path = evidence["point_in_time_streaming_evaluation"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    graph = dict(manifest["candidate_training_graph"])
    mutate_graph(graph)
    graph.pop("graph_hash", None)
    graph["graph_hash"] = sha256_text(canonical_json(graph))
    manifest["candidate_training_graph"] = graph
    manifest["candidate_training_graph_hash"] = graph["graph_hash"]
    manifest.pop("manifest_hash", None)
    manifest["manifest_hash"] = sha256_text(canonical_json(manifest))
    _write_json(manifest_path, manifest)
    plan["candidate_training_graph"] = graph
    plan["candidate_training_graph_hash"] = graph["graph_hash"]
    plan["corpus_binding"]["materialization_manifest_hash"] = manifest["manifest_hash"]
    plan.pop("plan_hash", None)
    plan["plan_hash"] = sha256_text(canonical_json(plan))
    _write_json(plan_path, plan)
    evaluation["contract_binding"].update(
        {
            "candidate_training_graph_hash": graph["graph_hash"],
            "materialization_manifest_hash": manifest["manifest_hash"],
            "validation_plan_hash": plan["plan_hash"],
        }
    )
    evaluation["input"]["materialization_manifest_hash"] = manifest["manifest_hash"]
    evaluation.pop("evaluation_hash", None)
    evaluation["evaluation_hash"] = sha256_text(canonical_json(evaluation))
    _write_json(evaluation_path, evaluation)


def test_candidate_contract_freezes_all_roles_and_release_reverifies_internal_hashes(tmp_path: Path):
    paths = _fixture(tmp_path)
    frozen = _freeze(paths)

    assert frozen["status"] == "PASS"
    assert frozen["audit"]["status"] == "PASS"
    model_bom = json.loads(
        (
            paths["candidate"] / SEMANTIC_PATHS["model_bill_of_materials"]
        ).read_text(encoding="utf-8")
    )
    assert model_bom["status"] == "INCOMPLETE"
    assert model_bom["authoritative_identity_sha256"] is None
    assert any(
        entry.startswith("training_lineage.base_model.nyc.feature_hgb")
        for entry in model_bom["missing_entries"]
    )
    assert model_bom["model_nodes"]["base_model.nyc.feature_hgb"]["models"][
        "12"
    ]["feature_names"] == ["forecast_high", "high_so_far"]
    declared_roles = {row["role"] for row in frozen["declarations"]}
    assert set(SEMANTIC_SERVING_ROLE_KINDS) <= declared_roles
    assert declared_roles - set(SEMANTIC_SERVING_ROLE_KINDS) == {
        "model_bill_of_materials",
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
        repo_root=REPO_ROOT,
        code_identity={
            "git_commit": "a" * 40,
            "git_branch": "main",
            "git_dirty": False,
            "dirty_fingerprint": None,
        },
        runtime_versions=model_bom["evidence"]["runtime_dependencies"]["binding"][
            "release_runtime_versions"
        ],
        runtime_identity=model_bom["evidence"]["runtime_dependencies"]["binding"][
            "release_runtime_identity"
        ],
    )
    verified = verify_release(result["release_dir"], check_runtime=False)

    assert verified["semantic_contract_verified"] is True
    assert verified["semantic_contract"]["status"] == "PASS"
    assert verified["semantic_contract"]["candidate_mode"] == "research_only"
    assert verified["semantic_contract"]["production_capable"] is False
    assert verified["semantic_contract"]["model_bill_of_materials_verified"] is True
    assert verified["semantic_contract"]["role_count"] == len(frozen["declarations"])
    with pytest.raises(ReleaseLifecycleError, match="research-only release"):
        promote_release(
            "r1",
            decision={},
            market_day_boundary={},
            releases_root=tmp_path / "releases",
            pointer_path=tmp_path / "releases" / "current_release.json",
            repo_root=REPO_ROOT,
            current_runtime_versions=model_bom["evidence"]["runtime_dependencies"][
                "binding"
            ]["release_runtime_versions"],
            current_runtime_identity=model_bom["evidence"]["runtime_dependencies"][
                "binding"
            ]["release_runtime_identity"],
            current_code_identity={
                "git_commit": "a" * 40,
                "git_branch": "main",
                "git_dirty": False,
                "dirty_fingerprint": None,
            },
        )

    promotion_now = datetime(2026, 7, 14, 14, 0, tzinfo=timezone.utc)
    decision = {
        "schema_version": PROMOTION_DECISION_SCHEMA_VERSION,
        "decision": "PROMOTE",
        "gate_status": "PASS",
        "release_id": "r1",
        "manifest_sha256": result["manifest_sha256"],
        "candidate_only_build": True,
        "reviewed": True,
        "reviewed_by": "release-reviewer",
        "reviewed_at_utc": promotion_now.isoformat(),
        "release_kind": SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
    }
    market_day_boundary = {
        "schema_version": MARKET_DAY_BOUNDARY_SCHEMA_VERSION,
        "status": "PASS",
        "release_id": "r1",
        "manifest_sha256": result["manifest_sha256"],
        "at_market_day_boundary": True,
        "processes_quiesced": True,
        "open_market_days": [],
        "mixed_release_market_days": [],
        "effective_target_date": promotion_now.date().isoformat(),
        "observed_at_utc": promotion_now.isoformat(),
    }
    promoted = promote_release(
        "r1",
        decision=decision,
        market_day_boundary=market_day_boundary,
        releases_root=tmp_path / "releases",
        pointer_path=tmp_path / "releases" / "current_release.json",
        repo_root=REPO_ROOT,
        now=promotion_now,
        current_runtime_versions=model_bom["evidence"]["runtime_dependencies"][
            "binding"
        ]["release_runtime_versions"],
        current_runtime_identity=model_bom["evidence"]["runtime_dependencies"][
            "binding"
        ]["release_runtime_identity"],
        current_code_identity={
            "git_commit": "a" * 40,
            "git_branch": "main",
            "git_dirty": False,
            "dirty_fingerprint": None,
        },
        bootstrap_first_release=True,
    )
    pointer = load_active_release_pointer(
        tmp_path / "releases" / "current_release.json"
    )

    assert promoted["status"] == "PROMOTED"
    assert promoted["release_kind"] == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND
    assert pointer["sequence"] == 1
    assert pointer["previous_release_id"] is None
    assert pointer["release_kind"] == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND
    assert pointer["release_kind_provenance"]["origin_release_id"] == "r1"
    assert pointer["release_kind_provenance"]["origin_manifest_sha256"] == (
        result["manifest_sha256"]
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
    assert frozen["point_in_time_qualification"][
        "fit_receipt_output_binding_verified"
    ] is True
    assert frozen["point_in_time_qualification"][
        "candidate_training_graph_hash"
    ]
    assert frozen["point_in_time_qualification"][
        "selection_universe_sha256"
    ]
    assert frozen["point_in_time_qualification"]["training_evidence_identity"][
        "final_fit_receipt_sha256"
    ]
    assert set(
        frozen["point_in_time_qualification"]["selection_stage_bindings"]
    ) == {"calibration", "routing"}
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
        repo_root=REPO_ROOT,
        code_identity={
            "git_commit": "a" * 40,
            "git_branch": "main",
            "git_dirty": False,
            "dirty_fingerprint": None,
        },
        runtime_versions=json.loads(
            (
                paths["candidate"] / SEMANTIC_PATHS["model_bill_of_materials"]
            ).read_text(encoding="utf-8")
        )["evidence"]["runtime_dependencies"]["binding"][
            "release_runtime_versions"
        ],
        runtime_identity=json.loads(
            (
                paths["candidate"] / SEMANTIC_PATHS["model_bill_of_materials"]
            ).read_text(encoding="utf-8")
        )["evidence"]["runtime_dependencies"]["binding"][
            "release_runtime_identity"
        ],
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


def test_production_candidate_rejects_graph_not_shared_by_all_four_roles(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)

    def mutate(plan: dict) -> None:
        plan["candidate_training_graph"]["route_selection"][
            "promote_markets"
        ] = []

    _rehash_plan_and_evaluation(evidence, mutate_plan=mutate)

    with pytest.raises(CandidateContractError, match="do not share one training graph"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


@pytest.mark.parametrize(
    "artifact_field",
    ["model_sha256", "calibration_sha256", "routing_sha256"],
)
def test_dependency_safe_verifier_rejects_self_consistent_wrong_candidate_artifact_hash(
    tmp_path: Path,
    artifact_field: str,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    _rehash_graph_across_packet(
        evidence,
        mutate_graph=lambda graph: graph["candidate_artifacts"].update(
            {artifact_field: "9" * 64}
        ),
    )

    with pytest.raises(ValueError, match="different fitted artifact"):
        verify_production_point_in_time_artifacts(
            corpus_path=evidence["point_in_time_corpus"],
            materialization_manifest_path=evidence[
                "point_in_time_materialization_manifest"
            ],
            validation_plan_path=evidence["point_in_time_validation_plan"],
            streaming_evaluation_path=evidence[
                "point_in_time_streaming_evaluation"
            ],
            expected_candidate_id="r1",
            expected_release_id="r1",
            expected_candidate_artifact_sha256=pit_sha256_file(paths["bundle"]),
            expected_calibration_artifact_sha256=pit_sha256_file(paths["family"]),
            expected_routing_artifact_sha256=pit_sha256_file(paths["promotion"]),
            expected_route_selection={
                "verdict": "promote_ready",
                "promote_markets": ["nyc"],
                "shadow_markets": [],
                "blocked_markets": [],
            },
        )


def test_production_candidate_rejects_observed_resource_use_above_declaration(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)

    def mutate(plan: dict) -> None:
        plan["resource_contract"]["observed_market_days"] = 61

    _rehash_plan_and_evaluation(evidence, mutate_plan=mutate)

    with pytest.raises(CandidateContractError, match="observed production replay"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_requires_selection_universe_bound_window(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    evaluation_path = evidence["point_in_time_streaming_evaluation"]
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    evaluation["window_lock"]["input_kind"] = "corpus_sha256"
    evaluation["window_lock"]["input_sha256"] = evaluation["input"]["sha256"]
    evaluation.pop("evaluation_hash")
    evaluation["evaluation_hash"] = sha256_text(canonical_json(evaluation))
    _write_json(evaluation_path, evaluation)

    with pytest.raises(CandidateContractError, match="preselected evaluation lock"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_rejects_graph_that_reuses_locked_dates_for_selection(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    _rehash_graph_across_packet(
        evidence,
        mutate_graph=lambda graph: graph.update(
            {"locked_dates_used_for_selection": True}
        ),
    )

    with pytest.raises(CandidateContractError, match="selection contract is invalid"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_rejects_stage_selection_binding_reuse(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)

    def mutate(graph: dict) -> None:
        graph["selection_stage_bindings"]["routing"]["used_for_selection"] = True
        graph["selection_stage_bindings_sha256"] = sha256_text(
            canonical_json(graph["selection_stage_bindings"])
        )

    _rehash_graph_across_packet(evidence, mutate_graph=mutate)

    with pytest.raises(CandidateContractError, match="routing selection"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_rejects_graph_binding_not_named_by_routing_artifact(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)

    def mutate(graph: dict) -> None:
        graph["selection_stage_bindings"]["routing"]["binding_sha256"] = "9" * 64
        graph["selection_stage_bindings_sha256"] = sha256_text(
            canonical_json(graph["selection_stage_bindings"])
        )

    _rehash_graph_across_packet(evidence, mutate_graph=mutate)

    with pytest.raises(CandidateContractError, match="exact fitted artifacts"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_rejects_model_bundle_evidence_not_named_by_graph(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    with paths["bundle"].open("rb") as handle:
        bundle = pickle.load(handle)
    embedded = dict(bundle["point_in_time_training"])
    final_receipt = dict(embedded["final_fit_receipt"])
    final_receipt["generated_at_utc"] = (
        datetime.fromisoformat(final_receipt["generated_at_utc"])
        + timedelta(seconds=1)
    ).isoformat()
    final_receipt = _finalize_contract_hash(final_receipt, "receipt_sha256")
    embedded["final_fit_receipt"] = final_receipt
    embedded = _finalize_contract_hash(embedded, "evidence_sha256")
    bundle["point_in_time_training"] = embedded
    bundle["postprocess_fit_contract"].update(
        {
            "evidence_sha256": embedded["evidence_sha256"],
            "final_fit_receipt_sha256": final_receipt["receipt_sha256"],
        }
    )
    with paths["bundle"].open("wb") as handle:
        pickle.dump(bundle, handle)

    with pytest.raises(CandidateContractError, match="exact model bundle evidence"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_rejects_missing_calibration_selection_proof(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    family = json.loads(paths["family"].read_text(encoding="utf-8"))
    family.pop("point_in_time_selection_binding")
    _write_json(paths["family"], family)

    with pytest.raises(CandidateContractError, match="selection binding is missing"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_rejects_locked_date_in_routing_source_inventory(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    routing = json.loads(paths["promotion"].read_text(encoding="utf-8"))
    binding = dict(routing["point_in_time_selection_binding"])
    inventory = dict(binding["source_inventory"])
    inventory["entries"] = [
        *inventory["entries"],
        {
            "folder": "data/routing/locked",
            "target_date": binding["locked_dates"][0],
            "market_id": "nyc",
        },
    ]
    inventory["entry_count"] = len(inventory["entries"])
    inventory = _finalize_contract_hash(inventory, "sha256")
    binding["source_inventory"] = inventory
    binding["source_folder_date_inventory_sha256"] = inventory["sha256"]
    binding = _finalize_contract_hash(binding, "binding_sha256")
    routing["point_in_time_selection_binding"] = binding
    _write_json(paths["promotion"], routing)

    with pytest.raises(CandidateContractError, match="includes locked dates"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


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


def test_production_candidate_recomputes_fit_receipt_output_payload_hash(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    plan_path = evidence["point_in_time_validation_plan"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    receipt = plan["fit_receipts"][0]
    receipt["stage_output_payload"]["declared_stage_output"]["stage"] = "tampered"
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = sha256_text(canonical_json(receipt))
    plan.pop("plan_hash")
    plan["plan_hash"] = sha256_text(canonical_json(plan))
    _write_json(plan_path, plan)

    with pytest.raises(CandidateContractError, match="output payload hash does not recompute"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_recomputes_fit_receipt_input_payload_hash(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    plan_path = evidence["point_in_time_validation_plan"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    receipt = plan["fit_receipts"][0]
    receipt["stage_input_payload"]["declared_stage_input"]["scope"] = "tampered"
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = sha256_text(canonical_json(receipt))
    plan.pop("plan_hash")
    plan["plan_hash"] = sha256_text(canonical_json(plan))
    _write_json(plan_path, plan)

    with pytest.raises(CandidateContractError, match="input payload hash does not recompute"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )


def test_production_candidate_requires_fit_stage_output_to_input_chain(tmp_path: Path):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths)
    plan_path = evidence["point_in_time_validation_plan"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    receipt = plan["fit_receipts"][1]
    receipt["stage_input_payload"]["upstream_stage_output_sha256"] = "f" * 64
    receipt["stage_input_sha256"] = sha256_text(
        canonical_json(receipt["stage_input_payload"])
    )
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = sha256_text(canonical_json(receipt))
    plan.pop("plan_hash")
    plan["plan_hash"] = sha256_text(canonical_json(plan))
    _write_json(plan_path, plan)

    with pytest.raises(CandidateContractError, match="not bound to the prior output"):
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


def test_production_candidate_rejects_fresh_evaluation_over_stale_targets(
    tmp_path: Path,
):
    paths = _fixture(tmp_path)
    evidence = _production_evidence(paths, target_age_days=8)

    with pytest.raises(CandidateContractError, match="target window is stale"):
        _freeze(
            paths,
            candidate_mode="production",
            point_in_time_artifacts=evidence,
        )
