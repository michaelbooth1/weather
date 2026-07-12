from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from weather.calibration.residual_distribution_v1 import (
    PREDECLARED_ABLATIONS,
    ResidualAblationSpec,
    ResidualTrainingError,
    build_oof_fit_receipt,
    feature_names_for_ablation,
    fit_final_candidate,
    hierarchical_checkpoint_weights,
    load_candidate_artifact,
    run_nested_evaluation,
    write_candidate_artifact,
)
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
    assert validated["training_lineage"]["oof_receipt"]["fit_role"] == "training_oof"
    assert validated["training_lineage"]["final_fit_receipt"]["fit_role"] == "prelock_final_refit"
    assert validated["training_lineage"]["research_only_rows"] == len(rows) - 4
    assert validated["training_lineage"]["locked_dates"] == [rows[-1]["target_date"]]
    assert rows[-1]["target_date"] not in validated["training_lineage"]["train_dates"]
    assert validated["calibration"]["fit_source"] == "rolling_origin_oof_complete_partitions"
    assert math.isfinite(validated["residual_sigma_f"])
    assert validated["qualification"]["status"] == "BLOCK"
    assert validated["qualification"]["criteria"]["has_release_bound_training_evidence"] is False

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
