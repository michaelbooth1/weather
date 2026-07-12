from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

from weather.calibration.residual_distribution_stress import (
    MAX_CASES,
    ResidualStressError,
    evaluate_residual_distribution_stress,
)
from weather.experiment_contract import verify_self_hash
from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.model.residual_distribution_v1 import ARTIFACT_SCHEMA_VERSION, PREDICTION_MODE


FEATURE_NAMES = [
    "forecast_high",
    "forecast_high_available",
    "forecast_high_missing",
    "high_so_far",
    "high_so_far_available",
    "high_so_far_missing",
    "minutes_since_cutoff",
    "minutes_since_cutoff_available",
    "minutes_since_cutoff_missing",
    "source_health_fresh_count",
    "source_health_stale_count",
    "source_health_failed_count",
    "source_health_unknown_count",
    "source_health_source_count",
    "source_health_all_fresh",
    "source_health_any_degraded",
    "source_open_meteo_present",
    "source_open_meteo_available",
    "source_open_meteo_fresh",
    "source_open_meteo_stale",
    "source_open_meteo_failed",
    "source_open_meteo_unknown",
    "source_open_meteo_age_ratio",
    "source_open_meteo_age_ratio_available",
]


def _artifact():
    rows = []
    for index in range(8):
        row = {name: 0.0 for name in FEATURE_NAMES}
        row.update({
            "forecast_high": 66.0 + index,
            "forecast_high_available": 1.0,
            "high_so_far": 64.0 + index,
            "high_so_far_available": 1.0,
            "minutes_since_cutoff_available": 1.0,
            "source_health_fresh_count": 1.0,
            "source_health_source_count": 1.0,
            "source_health_all_fresh": 1.0,
            "source_open_meteo_present": 1.0,
            "source_open_meteo_available": 1.0,
            "source_open_meteo_fresh": 1.0,
            "source_open_meteo_age_ratio": 0.1,
            "source_open_meteo_age_ratio_available": 1.0,
        })
        rows.append(row)
    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("ridge", Ridge(alpha=5.0)),
    ])
    pipeline.fit(pd.DataFrame(rows, columns=FEATURE_NAMES), [0.0] * len(rows))
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "prediction_mode": PREDICTION_MODE,
        "canonical_unit": "F",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": FEATURE_NAMES,
        "feature_contract": {
            "features": {
                "forecast_high": "absolute_temperature",
                "high_so_far": "absolute_temperature",
                "minutes_since_cutoff": "numeric",
            },
            "required": ["forecast_high"],
        },
        "source_health_policy": {
            "required_sources": ["open_meteo"],
            "allowed_states": ["fresh"],
        },
        "pipeline": pipeline,
        "residual_sigma_f": 2.0,
        "grid_low_f": -40.0,
        "grid_high_f": 130.0,
        "grid_step_f": 0.1,
        "calibration": {"method": "identity", "temperature": 1.0},
        "model_version": "stress-fixture-v1",
    }


def _bands():
    return [
        {"bin_kind": "lte", "bin_value_c": 19, "range_label": "19 C or lower"},
        {"bin_kind": "eq", "bin_value_c": 20, "range_label": "20 C"},
        {"bin_kind": "gte", "bin_value_c": 21, "range_label": "21 C or higher"},
    ]


def _cases(count=6):
    start = date(2026, 7, 1)
    rows = []
    for index in range(count):
        bucket = 20 if index % 2 == 0 else 21
        target = start + timedelta(days=index)
        captured = f"{target.isoformat()}T16:00:00+00:00"
        rows.append({
            "case_id": f"case-{index}",
            "target_date": target.isoformat(),
            "market_id": "toronto",
            "unit": "C",
            "cutoff_hour": 12,
            "captured_at": captured,
            "provider_timestamps": {
                "response_received_at": f"{target.isoformat()}T15:59:00+00:00",
                "provider_issue_time": f"{target.isoformat()}T15:00:00+00:00",
            },
            "feature_vector": {
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "forecast_high": float(bucket),
                "high_so_far": float(bucket) - 1.2,
                "minutes_since_cutoff": 0.0,
            },
            "source_diagnostics": [
                {
                    "source": "open_meteo",
                    "status": "fresh",
                    "age_minutes": 5.0,
                    "ttl_minutes": 60.0,
                }
            ],
            "band_rows": _bands(),
            "settlement_high": float(bucket) + 0.2,
            "settlement_bucket": bucket,
            "settlement_revision_buckets": [bucket, 21 if bucket == 20 else 20],
            "market_probabilities": {
                "lte_19c": 0.10,
                "eq_20c": 0.45,
                "gte_21c": 0.45,
            },
            "regime_tags": ["heat_spike"] if index < 3 else [],
        })
    return rows


def _evaluate(cases=None, **kwargs):
    return evaluate_residual_distribution_stress(
        artifact=_artifact(),
        cases=cases or _cases(),
        generated_at_utc="2026-07-12T20:00:00+00:00",
        negative_control_improvement_tolerance=10.0,
        rare_regime_max_excess_logloss=10.0,
        **kwargs,
    )


def test_evaluator_covers_e5_e6_e7_is_self_hashed_and_does_not_write_by_default(tmp_path):
    report = _evaluate()

    verify_self_hash(report, hash_field="report_sha256")
    assert report["schema_version"] == "residual_distribution_stress_evaluation_v1"
    assert report["input"]["case_count"] == 6
    assert not list(tmp_path.iterdir())
    assert set(report["controls"]) == {
        "artifact_contract",
        "base_case_scoring",
        "e5_forbidden_future_label_sentinels",
        "e5_grouped_date_permutation",
        "e5_deterministic_noise",
        "e5_market_copy_placebo",
        "e6_provider_fault_matrix",
        "e6_cadence_time_unit_band_metamorphic",
        "e7_settlement_rounding",
        "e7_settlement_revision_monte_carlo",
        "e7_rare_regime_slices",
    }
    assert report["controls"]["e5_grouped_date_permutation"]["status"] == "PASS"
    assert len(report["controls"]["e5_grouped_date_permutation"]["seeds"]) == 5
    assert report["controls"]["e6_cadence_time_unit_band_metamorphic"]["status"] == "PASS"
    assert report["controls"]["e7_settlement_rounding"]["status"] == "PASS"
    assert report["controls"]["e7_settlement_revision_monte_carlo"]["status"] == "PASS"
    assert report["controls"]["e7_rare_regime_slices"]["status"] == "PASS"
    provider = report["controls"]["e6_provider_fault_matrix"]
    assert provider["status"] == "PASS"
    delayed = next(row for row in provider["checks"] if row["case"] == "delayed_fresh_beyond_ttl")
    assert delayed["status"] == "PASS"
    assert delayed["terminal"] == "skipped"
    assert delayed["reason"] == "abstain_source_state"
    assert report["status"] == "PASS"


def test_future_provider_timestamp_and_real_label_proxy_block_sentinel_control():
    cases = _cases()
    cases[0]["provider_timestamps"]["provider_issue_time"] = "2026-07-01T17:00:00+00:00"
    cases[1]["feature_vector"]["hashed_label_proxy"] = "leak"

    report = _evaluate(cases)
    control = report["controls"]["e5_forbidden_future_label_sentinels"]

    assert control["status"] == "BLOCK"
    assert control["future_provider_timestamps"][0]["case_id"] == "case-0"
    assert control["observed_forbidden_features"][0]["field"] == "hashed_label_proxy"


def test_optional_settlement_controls_are_explicitly_inconclusive_without_inputs():
    cases = _cases()
    for case in cases:
        case.pop("settlement_high")
        case.pop("settlement_revision_buckets")
        case["regime_tags"] = []

    report = _evaluate(cases, rare_regime_min_cases=20)

    assert report["controls"]["e7_settlement_rounding"]["status"] == "INCONCLUSIVE"
    assert report["controls"]["e7_settlement_revision_monte_carlo"]["status"] == "INCONCLUSIVE"
    assert report["controls"]["e7_rare_regime_slices"]["status"] == "INCONCLUSIVE"


def test_explicit_output_is_self_hashed_and_bounded_inputs_fail_closed(tmp_path):
    output = tmp_path / "stress.json"
    report = evaluate_residual_distribution_stress(
        artifact=_artifact(),
        cases=_cases(),
        generated_at_utc="2026-07-12T20:00:00+00:00",
        negative_control_improvement_tolerance=10.0,
        rare_regime_max_excess_logloss=10.0,
        output_path=output,
    )
    assert json.loads(output.read_text(encoding="utf-8")) == report

    with pytest.raises(ResidualStressError, match="five unique seeds"):
        evaluate_residual_distribution_stress(
            artifact=_artifact(),
            cases=_cases(),
            seeds=(1, 2),
        )
    with pytest.raises(ResidualStressError, match=str(MAX_CASES)):
        evaluate_residual_distribution_stress(
            artifact=_artifact(),
            cases=[{"case_id": str(index)} for index in range(MAX_CASES + 1)],
        )


def test_invalid_artifact_returns_self_hashed_block_instead_of_crashing():
    report = evaluate_residual_distribution_stress(
        artifact={"schema_version": "bad"},
        cases=_cases(),
        generated_at_utc="2026-07-12T20:00:00+00:00",
        negative_control_improvement_tolerance=10.0,
    )

    verify_self_hash(report, hash_field="report_sha256")
    assert report["status"] == "BLOCK"
    assert report["controls"]["artifact_contract"]["status"] == "BLOCK"
