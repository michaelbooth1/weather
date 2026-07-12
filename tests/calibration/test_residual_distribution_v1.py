from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest

from weather.calibration.residual_distribution_v1 import (
    PREDECLARED_ABLATIONS,
    ResidualAblationSpec,
    ResidualTrainingError,
    build_oof_fit_receipt,
    feature_names_for_ablation,
    fleet_coverage_report,
    fit_final_candidate,
    hierarchical_checkpoint_weights,
    load_candidate_artifact,
    run_nested_evaluation,
    verify_artifact_training_receipts,
    verify_residual_oof_receipt,
    write_candidate_artifact,
)
from weather.experiment_contract import canonical_json, finalize_self_hash
from weather.model.continuous_density import f_to_native
from weather.model.residual_distribution_v1 import default_feature_contract, validate_artifact
from weather.reporting.validation.point_in_time_evaluation import RollingOriginFold
from weather.units import round_half_up


SCHEMA = "toronto_feature_store_v1.15"
TEST_ARMS = (
    PREDECLARED_ABLATIONS[0],
    PREDECLARED_ABLATIONS[3],
    PREDECLARED_ABLATIONS[4],
    PREDECLARED_ABLATIONS[5],
    PREDECLARED_ABLATIONS[6],
)


def _canonical_features(*, market_id: str, cutoff: int, anchor_f: float, residual_f: float):
    contract = default_feature_contract(SCHEMA)
    values = {
        "forecast_high": anchor_f,
        "high_so_far": anchor_f - 1.0,
        "current_temp": anchor_f - 1.5,
        "rise_from_7am": 2.0,
        "warming_rate_2h": 0.5,
        "hours_at_peak": 0.5,
        "forecast_gap": 1.0,
        "forecast_source_count": 3.0,
        "forecast_disagreement": 1.5,
        "minutes_since_cutoff": 2.0,
        "live_reading_temp": anchor_f - 1.0,
        "live_reading_minus_high": 0.0,
        "guidance_impossible_source_count": 0.0,
        "startup_feature_quarantined_flag": 0.0,
        "cutoff_hour": float(cutoff),
    }
    features = {"market_id": market_id, "unit": "F"}
    for name in contract["feature_contract"]["features"]:
        value = values.get(name)
        features[name] = value
        features[f"{name}_available"] = 0.0 if value is None else 1.0
        features[f"{name}_missing"] = 1.0 if value is None else 0.0
    features.update({
        "source_health_fresh_count": 1.0,
        "source_health_stale_count": 0.0,
        "source_health_failed_count": 0.0,
        "source_health_unknown_count": 0.0,
        "source_health_source_count": 1.0,
        "source_health_all_fresh": 1.0,
        "source_health_any_degraded": 0.0,
        "source_open_meteo_present": 1.0,
        "source_open_meteo_available": 1.0,
        "source_open_meteo_fresh": 1.0,
        "source_open_meteo_stale": 0.0,
        "source_open_meteo_failed": 0.0,
        "source_open_meteo_unknown": 0.0,
        "source_open_meteo_age_ratio": 0.1,
        "source_open_meteo_age_ratio_available": 1.0,
    })
    return features


def _rows(days: int = 18):
    output = []
    start = date(2026, 1, 1)
    for day_index in range(days):
        target_date = (start + timedelta(days=day_index)).isoformat()
        for market_id, unit, market_bias in (
            ("atlanta", "F", 1.25),
            ("toronto", "C", -0.75),
        ):
            for cutoff in (8, 12):
                anchor_f = 68.0 + (day_index % 5) + (0.5 if cutoff == 12 else 0.0)
                residual_f = market_bias + (0.4 if cutoff == 12 else 0.0)
                settled_f = anchor_f + residual_f
                settled_native = f_to_native(settled_f, unit)
                bucket = round_half_up(settled_native)
                features = _canonical_features(
                    market_id=market_id,
                    cutoff=cutoff,
                    anchor_f=anchor_f,
                    residual_f=residual_f,
                )
                output.append({
                    "target_date": target_date,
                    "market_id": market_id,
                    "snapshot_id": f"{target_date}-{market_id}-{cutoff}",
                    "cutoff_hour": cutoff,
                    "native_unit": unit,
                    "feature_schema_version": SCHEMA,
                    "forecast_anchor_f": anchor_f,
                    "residual_target_f": residual_f,
                    "features": features,
                    "source_health": [{"source": "open_meteo", "status": "fresh"}],
                    "market_bands": [
                        {"kind": "lte", "value": bucket - 1, "value_hi": bucket - 1},
                        {"kind": "eq", "value": bucket, "value_hi": bucket},
                        {"kind": "gte", "value": bucket + 1, "value_hi": bucket + 1},
                    ],
                    "winning_band": {"kind": "eq", "value": bucket, "value_hi": bucket},
                    "training_evidence_class": "research_only",
                    "promotion_training_countable": False,
                })
    return output


def test_hierarchical_weights_equalize_date_market_and_cutoff():
    rows = _rows(2)
    # Duplicate one checkpoint; it must divide that checkpoint's mass rather
    # than changing its date/market/cutoff total.
    duplicate = dict(rows[0])
    duplicate["snapshot_id"] = "duplicate"
    rows.append(duplicate)
    weights = hierarchical_checkpoint_weights(rows)
    by_date = {}
    by_market = {}
    by_cutoff = {}
    for row, weight in zip(rows, weights):
        by_date[row["target_date"]] = by_date.get(row["target_date"], 0.0) + weight
        key = (row["target_date"], row["market_id"])
        by_market[key] = by_market.get(key, 0.0) + weight
        cutoff_key = (*key, row["cutoff_hour"])
        by_cutoff[cutoff_key] = by_cutoff.get(cutoff_key, 0.0) + weight
    assert set(round(value, 12) for value in by_date.values()) == {0.5}
    assert set(round(value, 12) for value in by_market.values()) == {0.25}
    assert set(round(value, 12) for value in by_cutoff.values()) == {0.125}


def test_feature_ablations_are_small_and_market_effect_is_opt_in():
    contract = default_feature_contract(SCHEMA)
    anchor = feature_names_for_ablation(TEST_ARMS[0], contract)
    market = feature_names_for_ablation(TEST_ARMS[2], contract)
    assert "market_id" not in anchor
    assert "market_id" in market
    assert len(anchor) < len(market)


def test_oof_receipt_rejects_outer_validation_leakage():
    fold = RollingOriginFold(
        fold_id="outer",
        train_dates=("2026-01-01", "2026-01-02"),
        embargo_dates=("2026-01-03",),
        validation_dates=("2026-01-04",),
        embargo_days=3,
    )
    with pytest.raises(ResidualTrainingError, match="subset of outer training"):
        build_oof_fit_receipt(
            outer_fold=fold,
            oof_rows=[{
                "row": {"target_date": "2026-01-04", "market_id": "atlanta", "cutoff_hour": 8},
                "predicted_residual_f": 0.0,
                "residual_error_f": 1.0,
                "probabilities": {"a": 0.5, "b": 0.5},
            }],
            parent_receipt_sha256s=["a" * 64],
            stage_name="calibration",
        )


def _evaluation(rows):
    return run_nested_evaluation(
        rows,
        ablations=TEST_ARMS,
        alpha_grid=(1.0,),
        outer_min_train_dates=8,
        inner_min_train_dates=4,
        embargo_days=3,
    )


def test_nested_training_receipts_never_fit_outer_date():
    evaluation = _evaluation(_rows())
    assert evaluation["fold_contract"]["outer_fold_count"] > 0
    for outer in evaluation["outer_results"]:
        outer_dates = set(outer["validation_dates"])
        assert outer_dates.isdisjoint(outer["train_dates"])
        for arm in outer["arms"]:
            receipt = arm["oof_receipt"]
            assert set(receipt["oof_dates"]) <= set(outer["train_dates"])
            assert set(receipt["oof_dates"]).isdisjoint(outer_dates)
            for model_receipt in arm["fit_receipts"]:
                assert set(model_receipt["train_dates"]).isdisjoint(outer_dates)
                declared_output = model_receipt["stage_output_payload"][
                    "declared_stage_output"
                ]
                assert declared_output["model_payload_sha256"]
                assert declared_output["fit_predictions_sha256"]
                assert declared_output[
                    "validation_predictions_sha256"
                ]
            assert verify_residual_oof_receipt(
                receipt, arm["fit_receipts"]
            )["receipt_sha256"] == receipt["receipt_sha256"]
    sample = evaluation["outer_results"][0]["arms"][0]
    tampered_output = deepcopy(sample["oof_receipt"])
    tampered_output["stage_output_payload"][
        "calibrated_oof_payload_sha256"
    ] = "f" * 64
    tampered_output = finalize_self_hash(
        tampered_output, hash_field="receipt_sha256"
    )
    with pytest.raises(ResidualTrainingError, match="input/output payload hash mismatch"):
        verify_residual_oof_receipt(tampered_output, sample["fit_receipts"])

    broken_chain = deepcopy(sample["oof_receipt"])
    broken_chain["parent_stage_output_sha256s"][0] = "f" * 64
    broken_chain["stage_input_payload"]["parent_stage_output_sha256s"] = list(
        broken_chain["parent_stage_output_sha256s"]
    )
    broken_chain["stage_input_sha256"] = hashlib.sha256(
        canonical_json(broken_chain["stage_input_payload"]).encode("utf-8")
    ).hexdigest()
    broken_chain = finalize_self_hash(broken_chain, hash_field="receipt_sha256")
    with pytest.raises(ResidualTrainingError, match="exact parent model outputs"):
        verify_residual_oof_receipt(broken_chain, sample["fit_receipts"])
    assert "negative_whole_date_target_permutation" in evaluation["arm_outer_scores"]
    assert all(
        not arm["selected_arm"].startswith("negative_")
        for arm in evaluation["outer_results"]
    )


def test_final_artifact_uses_oof_scale_and_candidate_only_atomic_write(tmp_path):
    rows = _rows()
    evaluation = _evaluation(rows)
    artifact = fit_final_candidate(
        rows,
        evaluation,
        ablations=TEST_ARMS,
        alpha_grid=(1.0,),
        min_train_dates=4,
        embargo_days=3,
        locked_dates=(rows[-1]["target_date"],),
    )
    validated = validate_artifact(artifact)
    verify_artifact_training_receipts(validated)
    assert validated["training_lineage"]["oof_receipt"]["fit_role"] == "training_oof"
    assert validated["training_lineage"]["final_fit_receipt"]["fit_role"] == "prelock_final_refit"
    assert validated["training_lineage"]["research_only_rows"] == len(rows) - 4
    assert validated["training_lineage"]["locked_dates"] == [rows[-1]["target_date"]]
    assert rows[-1]["target_date"] not in validated["training_lineage"]["train_dates"]
    assert validated["calibration"]["fit_source"] == "rolling_origin_oof_complete_partitions"
    assert math.isfinite(validated["residual_sigma_f"])
    assert validated["qualification"]["status"] == "BLOCK"
    assert validated["qualification"]["criteria"]["has_release_bound_training_evidence"] is False
    assert validated["qualification"]["criteria"]["evidence_finalization_complete"] is False
    assert validated["source_health_policy"]["allowed_states"] == ["fresh"]
    assert validated["source_health_policy"]["degraded_state_action"] == "named_abstention"

    tampered = deepcopy(validated)
    tampered_receipt = tampered["training_lineage"]["final_fit_receipt"]
    tampered_receipt["stage_output_payload"]["fit_predictions_sha256"] = "f" * 64
    tampered["training_lineage"]["final_fit_receipt"] = finalize_self_hash(
        tampered_receipt, hash_field="receipt_sha256"
    )
    with pytest.raises(ResidualTrainingError, match="input/output payload hash mismatch"):
        verify_artifact_training_receipts(tampered)

    broken_final_chain = deepcopy(validated)
    final_receipt = broken_final_chain["training_lineage"]["final_fit_receipt"]
    final_receipt["parent_stage_output_sha256"] = "f" * 64
    final_receipt["stage_input_payload"]["parent_stage_output_sha256"] = "f" * 64
    final_receipt["stage_input_sha256"] = hashlib.sha256(
        canonical_json(final_receipt["stage_input_payload"]).encode("utf-8")
    ).hexdigest()
    broken_final_chain["training_lineage"]["final_fit_receipt"] = finalize_self_hash(
        final_receipt, hash_field="receipt_sha256"
    )
    with pytest.raises(ResidualTrainingError, match="not chained to the OOF output"):
        verify_artifact_training_receipts(broken_final_chain)

    candidates = tmp_path / "artifacts" / "candidates"
    releases = tmp_path / "artifacts" / "releases"
    path = candidates / "residual_distribution_v1" / "model.pkl"
    written = write_candidate_artifact(
        artifact,
        path,
        candidates_root=candidates,
        releases_root=releases,
    )
    assert written["status"] == "CANDIDATE_ONLY"
    assert written["candidate_release_eligible"] is False
    assert written["promotion_eligible"] is False
    assert written["sha256"]
    assert load_candidate_artifact(path)["prediction_mode"] == "residual_distribution_v1"


def test_writer_rejects_release_path(tmp_path):
    # The path guard is exercised before any write. A tiny invalid artifact is
    # rejected even earlier, so use a trained artifact from the bounded fixture.
    rows = _rows(14)
    evaluation = run_nested_evaluation(
        rows,
        ablations=(TEST_ARMS[0], TEST_ARMS[2]),
        alpha_grid=(1.0,),
        outer_min_train_dates=8,
        inner_min_train_dates=4,
    )
    artifact = fit_final_candidate(
        rows,
        evaluation,
        ablations=(TEST_ARMS[0], TEST_ARMS[2]),
        alpha_grid=(1.0,),
        min_train_dates=4,
    )
    candidates = tmp_path / "artifacts" / "candidates"
    releases = tmp_path / "artifacts" / "releases"
    with pytest.raises(Exception, match="immutable|release|outside candidate"):
        write_candidate_artifact(
            artifact,
            releases / "r1" / "model.pkl",
            candidates_root=candidates,
            releases_root=releases,
        )


def test_fitted_release_bound_rows_never_bypass_evidence_finalization():
    rows = _rows(18)
    for row in rows:
        row["training_evidence_class"] = "release_bound"
        row["promotion_training_countable"] = True
        row["release_id"] = "r1"
        row["runtime_identity"] = {"source_fingerprint": "runtime-1"}
    evaluation = _evaluation(rows)
    artifact = fit_final_candidate(
        rows,
        evaluation,
        ablations=TEST_ARMS,
        alpha_grid=(1.0,),
        min_train_dates=4,
    )
    assert artifact["training_lineage"]["promotion_training_countable_rows"] == len(rows)
    assert artifact["qualification"]["status"] == "BLOCK"
    assert artifact["qualification"]["criteria"]["evidence_finalization_complete"] is False


def test_fleet_coverage_requires_every_market_cutoff_on_every_date():
    rows = _rows(2)
    complete = fleet_coverage_report(
        rows,
        target_dates=sorted({row["target_date"] for row in rows}),
        expected_market_ids=("atlanta", "toronto"),
        expected_cutoff_hours=(8, 12),
    )
    assert complete["status"] == "PASS"
    incomplete = fleet_coverage_report(
        rows[:-1],
        target_dates=complete["target_dates"],
        expected_market_ids=("atlanta", "toronto"),
        expected_cutoff_hours=(8, 12),
    )
    assert incomplete["status"] == "BLOCK"
    assert incomplete["missing_by_date"]
