from __future__ import annotations

import hashlib
from datetime import date, timedelta

import pytest

from weather.calibration.served_stage_ablation import (
    CONCRETE_COHERENT_CALIBRATION_ARMS,
    StageAblationExecutionError,
    execute_served_calibration_stage_ablation,
    experiment_matrix,
    probability_vector_sha256,
)
from weather.experiment_contract import canonical_json, finalize_self_hash
from weather.model_stage_retirement import (
    INCUMBENT_STAGES,
    REQUIRED_CALIBRATION_ARMS,
    REQUIRED_EXPERIMENT_TYPES,
    REQUIRED_REQUALIFICATION_CRITERIA,
    build_stage_retirement_register,
)


CANDIDATE_ID = "residual_distribution_v1"
ARTIFACT_SHA256 = "a" * 64


def _sha256_payload(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _report() -> dict:
    criteria = {key: True for key in REQUIRED_REQUALIFICATION_CRITERIA}
    return {
        "status": "OFFLINE_PASS",
        "candidate_id": CANDIDATE_ID,
        "qualification": {
            "status": "OFFLINE_PASS",
            "offline_status": "PASS",
            "forward_status": "BLOCK",
            "criteria": criteria,
        },
        "candidate_artifact": {
            "sha256": ARTIFACT_SHA256,
            "qualification_status": "OFFLINE_PASS",
            "offline_qualification_status": "PASS",
            "forward_qualification_status": "BLOCK",
            "promotion_eligible": False,
        },
    }


def _cases(count: int = 14) -> list[dict]:
    first = date(2026, 6, 1)
    rows = []
    for index in range(count):
        captured_input = {
            "forecast_anchor": 80.0 + (index % 3),
            "source_health": {"required_source_status": "fresh"},
            "feature_vector": {"forecast_gap": float(index % 4)},
        }
        rows.append({
            "target_date": (first + timedelta(days=index)).isoformat(),
            "market_id": "nyc",
            "cutoff_hour": 12,
            "captured_input": captured_input,
            "captured_input_sha256": _sha256_payload(captured_input),
            "allowed_band_keys": ["win", "lose"],
            "impossible_band_keys": ["impossible"],
            "winner_key": "win",
            "outcome": 1,
            "settlement_label": {"winner_key": "win"},
            "audit": {"final_bucket": "win", "label_value": 1},
        })
    return rows


def _assert_label_sanitized(value) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            assert key != "winner_key"
            assert "outcome" not in normalized
            assert "settlement" not in normalized
            assert "label" not in normalized
            assert "final_bucket" not in normalized
            _assert_label_sanitized(item)
    elif isinstance(value, list):
        for item in value:
            _assert_label_sanitized(item)


def _execution_proof(case: dict, config: dict, result: dict) -> dict:
    experiment = config["experiment"]
    adapter = config["predictor_adapter"]
    binding = config["call_binding"]
    return {
        "experiment_config_sha256": config["experiment_config_sha256"],
        "experiment_id": experiment["experiment_id"],
        "executed_disabled_stages": list(experiment.get("disabled_stages") or []),
        "executed_order_override": list(experiment.get("order_override") or []),
        "executed_calibration_arm": experiment.get("calibration_arm"),
        "executed_stage_execution": dict(config["expected_stage_execution"]),
        "embargo_days": config["embargo_days"],
        "evaluation_seed": config["evaluation_seed"],
        "probe_type": config["probe_type"],
        "predictor_adapter_identity": adapter["identity"],
        "predictor_adapter_source_sha256": adapter["source_sha256"],
        "captured_input_sha256": binding["captured_input_sha256"],
        "predictor_input_sha256": binding["predictor_input_sha256"],
        "probability_vector_sha256": probability_vector_sha256(
            result.get("probabilities")
        ),
        "prediction_status": result["prediction_status"],
        "failure_reason": str(result.get("failure_reason") or ""),
    }


def _predictor(case: dict, config: dict) -> dict:
    _assert_label_sanitized(case)
    probe_type = config["probe_type"]
    if probe_type != "none":
        failure_reason = {
            "source_failure": "required_source_failure",
            "unknown_market": "unknown_market",
        }[probe_type]
        result = {
            "prediction_status": "abstained",
            "failure_reason": failure_reason,
            "model_family": CANDIDATE_ID,
        }
        result["execution_proof"] = _execution_proof(case, config, result)
        return result

    experiment = config["experiment"]
    probability = 0.60
    if experiment["kind"] == "calibration_arm":
        arm = experiment["calibration_arm"]
        probability = {
            "literal_current_served_transform": 0.55,
            "simplex_temperature": 0.70,
            "coherent_ordinal_simplex_shrinkage": 0.68,
            "coherent_simplex_temperature_or_shrinkage": 0.66,
        }.get(arm, 0.60)
    probabilities = {
        "win": probability,
        "lose": 1.0 - probability,
        "impossible": 0.0,
    }
    result = {
        "prediction_status": "predicted",
        "failure_reason": "",
        "model_family": CANDIDATE_ID,
        "probabilities": probabilities,
    }
    if (
        experiment.get("calibration_arm")
        == "literal_current_served_transform"
    ):
        result["served_reference_probabilities"] = dict(probabilities)
    result["execution_proof"] = _execution_proof(case, config, result)
    return result


def _execute(cases=None, predictor=_predictor):
    return execute_served_calibration_stage_ablation(
        cases or _cases(),
        predictor,
        _report(),
        candidate_id=CANDIDATE_ID,
        candidate_artifact_sha256=ARTIFACT_SHA256,
        frozen_full_stack_id="immutable-incumbent-release",
        selected_calibrator="simplex_temperature",
        evaluation_seeds=(101, 211, 307),
        bootstrap_seeds=(17, 31, 47),
        bootstrap_iterations=1,
        generated_at_utc="2026-07-12T17:00:00+00:00",
    )


def test_matrix_is_complete_predeclared_and_keeps_coherent_arms_distinct():
    matrix = experiment_matrix()
    stage_rows = [row for row in matrix if row["kind"] == "stage_ablation"]
    calibration_rows = [row for row in matrix if row["kind"] == "calibration_arm"]
    calibration_arms = {row["calibration_arm"] for row in calibration_rows}

    assert len(stage_rows) == len(INCUMBENT_STAGES) * len(REQUIRED_EXPERIMENT_TYPES)
    assert {row["stage_id"] for row in stage_rows} == {
        row["stage_id"] for row in INCUMBENT_STAGES
    }
    assert {row["experiment_type"] for row in stage_rows} == set(
        REQUIRED_EXPERIMENT_TYPES
    )
    assert set(REQUIRED_CALIBRATION_ARMS) <= calibration_arms
    assert set(CONCRETE_COHERENT_CALIBRATION_ARMS) <= calibration_arms
    assert "simplex_temperature" in calibration_arms
    assert "coherent_ordinal_simplex_shrinkage" in calibration_arms


def test_executed_predictions_produce_receipt_bound_e3_e4_and_retirement_register():
    evidence = _execute()
    register = build_stage_retirement_register(
        _report(),
        evidence,
        generated_at_utc="2026-07-12T18:00:00+00:00",
    )

    matrix_count = len(experiment_matrix())
    expected_normal_calls = len(_cases()) * matrix_count * 3 * 3
    expected_probe_calls = matrix_count * 2
    contract = evidence["execution_contract"]
    assert evidence["status"] == "PASS"
    assert contract["selection_from_scored_rows"] is False
    assert contract["normal_prediction_count"] == expected_normal_calls
    assert contract["probe_prediction_count"] == expected_probe_calls
    assert contract["prediction_count"] == expected_normal_calls + expected_probe_calls
    assert contract["predictor_adapter"]["identity"].endswith(":_predictor")
    assert len(contract["predictor_adapter"]["source_sha256"]) == 64
    assert contract["embargo_days_evaluated"] == [3, 5, 7]
    assert contract["evaluation_seeds"] == [101, 211, 307]
    assert len(contract["execution_receipts"]) == contract["prediction_count"]
    for receipt in contract["execution_receipts"][:10]:
        recomputed = finalize_self_hash(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"},
            hash_field="receipt_sha256",
        )
        assert receipt["receipt_sha256"] == recomputed["receipt_sha256"]
    assert evidence["calibration"]["selected_arm"] == "simplex_temperature"
    assert evidence["calibration"]["seed_count"] == 3
    assert evidence["calibration"]["parity_vectors"]["status"] == "PASS"
    assert evidence["calibration"]["parity_vectors"]["compared_vector_count"] > 0
    assert set(evidence["calibration"]["sensitivity"]["embargo_days"]) == {
        "3",
        "5",
        "7",
    }
    assert set(evidence["calibration"]["sensitivity"]["evaluation_seeds"]) == {
        "101",
        "211",
        "307",
    }
    assert len(evidence["stage_ablations"]) == len(INCUMBENT_STAGES)
    assert register["status"] == "PASS"
    assert register["summary"]["retire_count"] == len(INCUMBENT_STAGES)


def test_winner_and_nested_label_fields_are_absent_from_predictor_input():
    seen = {"calls": 0}

    def inspecting_predictor(case, config):
        seen["calls"] += 1
        _assert_label_sanitized(case)
        assert "winner_key" not in case
        return _predictor(case, config)

    evidence = _execute(predictor=inspecting_predictor)

    assert evidence["status"] == "PASS"
    assert seen["calls"] == evidence["execution_contract"]["prediction_count"]


def test_predictor_ignoring_config_cannot_emit_retirement_evidence():
    def ignores_config(_case, _config):
        return {
            "prediction_status": "predicted",
            "failure_reason": "",
            "model_family": CANDIDATE_ID,
            "probabilities": {"win": 0.6, "lose": 0.4, "impossible": 0.0},
        }

    with pytest.raises(StageAblationExecutionError, match="omitted execution_proof"):
        _execute(predictor=ignores_config)


def test_predictor_lying_about_disabled_stage_cannot_retire_it():
    def lying_predictor(case, config):
        result = _predictor(case, config)
        if config["experiment"].get("disabled_stages"):
            result["execution_proof"]["executed_disabled_stages"] = []
        return result

    with pytest.raises(StageAblationExecutionError, match="does not match"):
        _execute(predictor=lying_predictor)


def test_parity_is_derived_from_vectors_even_when_predictor_self_asserts_pass():
    def mismatched_parity_predictor(case, config):
        result = _predictor(case, config)
        if (
            config["probe_type"] == "none"
            and config["experiment"].get("calibration_arm")
            == "literal_current_served_transform"
        ):
            result["served_reference_probabilities"] = {
                "win": 0.50,
                "lose": 0.50,
                "impossible": 0.0,
            }
            result["served_transform_parity"] = True
        return result

    evidence = _execute(predictor=mismatched_parity_predictor)

    assert evidence["status"] == "BLOCK"
    assert evidence["calibration"]["parity_vectors"]["status"] == "BLOCK"
    assert evidence["calibration"]["parity_vectors"]["max_abs_delta"] == pytest.approx(
        0.05
    )


def test_source_failure_probe_must_execute_named_abstention_not_fallback():
    def fallback_predictor(case, config):
        if config["probe_type"] == "source_failure":
            result = {
                "prediction_status": "predicted",
                "failure_reason": "",
                "model_family": CANDIDATE_ID,
                "probabilities": {"win": 0.5, "lose": 0.5, "impossible": 0.0},
            }
            result["execution_proof"] = _execution_proof(case, config, result)
            return result
        return _predictor(case, config)

    with pytest.raises(StageAblationExecutionError, match="named abstention"):
        _execute(predictor=fallback_predictor)


def test_captured_input_hash_mismatch_fails_before_predictor_execution():
    rows = _cases()
    rows[0]["captured_input_sha256"] = "f" * 64

    with pytest.raises(StageAblationExecutionError, match="does not bind"):
        _execute(cases=rows)


def test_insufficient_fleet_dates_cannot_emit_pass_evidence():
    evidence = _execute(cases=_cases(13))

    assert evidence["status"] == "BLOCK"
    assert evidence["paired_date_count"] == 13
