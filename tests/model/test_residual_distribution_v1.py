from __future__ import annotations

import copy
import math
import pickle

import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from weather.model.residual_distribution_v1 import (
    ARTIFACT_SCHEMA_VERSION,
    PREDICTION_MODE,
    canonical_candidate_features,
    default_feature_contract,
    predict_residual_distribution_v1,
    simplex_temperature,
    validate_artifact,
)


FEATURE_SCHEMA = "toronto_feature_store_v1.15"


def _feature_names():
    return [
        "forecast_high",
        "forecast_high_available",
        "forecast_high_missing",
        "high_so_far",
        "high_so_far_available",
        "high_so_far_missing",
        "forecast_disagreement",
        "forecast_disagreement_available",
        "forecast_disagreement_missing",
        "forecast_source_count",
        "forecast_source_count_available",
        "source_health_fresh_count",
        "source_health_failed_count",
        "source_open_meteo_fresh",
        "source_open_meteo_age_ratio_available",
    ]


def _fitted_pipeline(feature_names=None):
    feature_names = feature_names or _feature_names()
    rows = []
    for index in range(8):
        row = {name: 0.0 for name in feature_names}
        row.update(
            {
                "forecast_high": 66.0 + index,
                "forecast_high_available": 1.0,
                "high_so_far": 63.0 + index,
                "high_so_far_available": 1.0,
                "forecast_disagreement": 1.0 + index / 10.0,
                "forecast_disagreement_available": 1.0,
                "forecast_source_count": 3.0,
                "forecast_source_count_available": 1.0,
                "source_health_fresh_count": 3.0,
                "source_open_meteo_fresh": 1.0,
                "source_open_meteo_age_ratio_available": 1.0,
            }
        )
        rows.append(row)
    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=10.0)),
        ]
    )
    pipeline.fit(pd.DataFrame(rows, columns=feature_names), [0.0] * len(rows))
    return pipeline


def _artifact():
    names = _feature_names()
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "prediction_mode": PREDICTION_MODE,
        "model_version": "residual-test-v1",
        "feature_schema_version": FEATURE_SCHEMA,
        "canonical_unit": "F",
        "feature_names": names,
        "feature_contract": {
            "features": {
                "forecast_high": "absolute_temperature",
                "high_so_far": "absolute_temperature",
                "forecast_disagreement": "temperature_delta",
                "forecast_source_count": "numeric",
            },
            "required": ["forecast_high"],
        },
        "source_health_policy": {
            "required_sources": ["open_meteo"],
            "allowed_states": ["fresh"],
        },
        "pipeline": _fitted_pipeline(names),
        "residual_sigma_f": 2.0,
        "grid_low_f": -40.0,
        "grid_high_f": 130.0,
        "grid_step_f": 0.1,
        "calibration": {
            "method": "simplex_temperature",
            "temperature": 1.0,
        },
    }


def _features(**updates):
    payload = {
        "feature_schema_version": FEATURE_SCHEMA,
        "forecast_high": 20.0,
        "high_so_far": 18.2,
        "forecast_disagreement": 2.0,
        "forecast_source_count": 3.0,
    }
    payload.update(updates)
    return payload


def _fresh_sources():
    return [
        {
            "source": "open_meteo",
            "status": "fresh",
            "age_minutes": 12.0,
            "ttl_minutes": 120.0,
        },
        {
            "source": "wu_history",
            "status": "fresh",
            "age_minutes": 4.0,
            "ttl_minutes": 30.0,
        },
    ]


def _c_bands(floor=19, exact=20, ceiling=21):
    return [
        {"bin_kind": "lte", "bin_value_c": floor},
        {"bin_kind": "eq", "bin_value_c": exact},
        {"bin_kind": "gte", "bin_value_c": ceiling},
    ]


def _f_bands(floor=67, exact=68, ceiling=69):
    return [
        {"bin_kind": "lte", "bin_value_c": floor},
        {"bin_kind": "eq", "bin_value_c": exact},
        {"bin_kind": "gte", "bin_value_c": ceiling},
    ]


def _predict(**overrides):
    kwargs = {
        "artifact": _artifact(),
        "feature_vector": _features(),
        "source_diagnostics": _fresh_sources(),
        "market_id": "toronto",
        "unit": "C",
        "band_rows": _c_bands(),
    }
    kwargs.update(overrides)
    return predict_residual_distribution_v1(**kwargs)


def test_artifact_contract_requires_exact_schema_mode_and_ridge_pipeline():
    normalized = validate_artifact(_artifact())
    assert normalized["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert normalized["prediction_mode"] == PREDICTION_MODE
    assert isinstance(normalized["pipeline"].steps[-1][1], Ridge)

    wrong_schema = _artifact()
    wrong_schema["schema_version"] = "residual_distribution_v1_v9"
    assert predict_residual_distribution_v1(
        artifact=wrong_schema,
        feature_vector=_features(),
        source_diagnostics=_fresh_sources(),
        market_id="toronto",
        unit="C",
        band_rows=_c_bands(),
    )["failure_reason"] == "invalid_artifact"


def test_feature_canonicalization_converts_absolute_and_delta_values_to_f():
    artifact = validate_artifact(_artifact())
    canonical = canonical_candidate_features(
        artifact=artifact,
        feature_vector=_features(high_so_far=None, forecast_disagreement=2.0),
        source_diagnostics=_fresh_sources(),
        market_id="toronto",
        unit="C",
    )
    assert canonical["forecast_high"] == pytest.approx(68.0)
    assert math.isnan(canonical["high_so_far"])
    assert canonical["high_so_far_available"] == 0.0
    assert canonical["high_so_far_missing"] == 1.0
    assert canonical["forecast_disagreement"] == pytest.approx(3.6)
    assert canonical["source_health_fresh_count"] == 2.0
    assert canonical["source_open_meteo_fresh"] == 1.0
    assert canonical["source_open_meteo_age_ratio_available"] == 1.0


def test_default_feature_contract_can_materialize_rows_before_fit():
    template = default_feature_contract(FEATURE_SCHEMA)
    canonical = canonical_candidate_features(
        artifact=template,
        feature_vector=_features(cutoff_hour=12),
        source_diagnostics=_fresh_sources(),
        market_id="toronto",
        unit="C",
    )
    assert template["feature_contract"]["required"] == ["forecast_high"]
    assert canonical["market_id"] == "toronto"
    assert canonical["forecast_high"] == pytest.approx(68.0)
    assert canonical["cutoff_hour"] == 12.0
    assert "source_health_any_degraded" in template["feature_names"]
    assert "source_open_meteo_age_ratio_available" in template["feature_names"]


@pytest.mark.parametrize(
    ("market_id", "unit", "features", "bands"),
    [
        ("toronto", "C", _features(), _c_bands()),
        (
            "atlanta",
            "F",
            _features(
                forecast_high=68.0,
                high_so_far=64.76,
                forecast_disagreement=3.6,
            ),
            _f_bands(),
        ),
    ],
)
def test_ridge_residual_inference_projects_exact_native_simplex(
    market_id, unit, features, bands
):
    payload = _predict(
        feature_vector=features,
        market_id=market_id,
        unit=unit,
        band_rows=bands,
    )
    assert payload["status"] == "predicted"
    assert payload["failure_reason"] is None
    assert payload["mean_f"] == pytest.approx(68.0, abs=1e-8)
    assert sum(payload["probabilities"].values()) == pytest.approx(1.0, abs=1e-12)
    assert all(0.0 <= value <= 1.0 for value in payload["probabilities"].values())


def test_range_band_projection_uses_native_half_open_boundaries():
    payload = _predict(
        market_id="atlanta",
        unit="F",
        feature_vector=_features(
            forecast_high=68.5,
            high_so_far=65.0,
            forecast_disagreement=2.0,
        ),
        band_rows=[
            {"bin_kind": "lte", "bin_value_c": 67},
            {"bin_kind": "eq", "bin_value_c": 68, "bin_value_hi_c": 69},
            {"bin_kind": "gte", "bin_value_c": 70},
        ],
    )
    assert payload["status"] == "predicted"
    assert set(payload["probabilities"]) == {"lte_67c", "eq_68_69c", "gte_70c"}
    assert sum(payload["probabilities"].values()) == pytest.approx(1.0, abs=1e-12)


def test_printed_high_is_the_only_hard_floor_signal():
    base_features = _features(forecast_high=22.0, high_so_far=20.6)
    base = _predict(
        feature_vector=base_features,
        band_rows=_c_bands(floor=20, exact=21, ceiling=22),
    )
    unrelated = _predict(
        feature_vector={
            **base_features,
            "trusted_current_max": 30.0,
            "current_temp": 30.0,
            "observed_support_bucket": 30.0,
        },
        band_rows=_c_bands(floor=20, exact=21, ceiling=22),
    )
    assert base["status"] == "predicted"
    assert base["printed_observed_floor_bucket"] == 21
    assert base["probabilities"]["lte_20c"] == 0.0
    assert unrelated["probabilities"] == pytest.approx(base["probabilities"])


def test_simplex_temperature_is_joint_and_preserves_zeroes():
    calibrated = simplex_temperature({"cold": 0.8, "warm": 0.2, "impossible": 0.0}, 2.0)
    assert calibrated["cold"] < 0.8
    assert calibrated["warm"] > 0.2
    assert calibrated["impossible"] == 0.0
    assert sum(calibrated.values()) == pytest.approx(1.0, abs=1e-12)


def test_identity_calibration_is_supported_as_temperature_one():
    artifact = _artifact()
    artifact["calibration"] = {"method": "identity"}
    identity = _predict(artifact=artifact)
    comparator = _predict()
    assert identity["status"] == "predicted"
    assert identity["calibration_temperature"] == 1.0
    assert identity["probabilities"] == pytest.approx(comparator["probabilities"])


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"market_id": "not-a-market"}, "abstain_unknown_market"),
        ({"unit": "F"}, "abstain_unit_mismatch"),
        (
            {"feature_vector": _features(feature_schema_version="unexpected")},
            "abstain_feature_schema",
        ),
        (
            {"feature_vector": _features(forecast_high=None)},
            "abstain_missing_forecast_anchor",
        ),
        (
            {
                "source_diagnostics": [
                    {"source": "open_meteo", "status": "failed"}
                ]
            },
            "abstain_source_state",
        ),
        ({"source_diagnostics": []}, "abstain_source_state"),
        ({"source_diagnostics": "fresh"}, "abstain_source_state"),
    ],
)
def test_input_incompatibilities_are_named_abstentions_without_fallback(overrides, reason):
    payload = _predict(**overrides)
    assert payload["status"] == "skipped"
    assert payload["failure_reason"] == reason
    assert "probabilities" not in payload


def test_missing_noncritical_feature_is_explicit_not_neutral():
    artifact = validate_artifact(_artifact())
    canonical = canonical_candidate_features(
        artifact=artifact,
        feature_vector=_features(forecast_disagreement=None),
        source_diagnostics=_fresh_sources(),
        market_id="toronto",
        unit="C",
    )
    assert math.isnan(canonical["forecast_disagreement"])
    assert canonical["forecast_disagreement_available"] == 0.0
    assert canonical["forecast_disagreement_missing"] == 1.0


def test_duplicate_source_rows_retain_worst_state_and_abstain():
    payload = _predict(
        source_diagnostics=[
            {"source": "open_meteo", "status": "fresh"},
            {"source": "open_meteo", "status": "failed"},
        ]
    )
    assert payload["status"] == "skipped"
    assert payload["failure_reason"] == "abstain_source_state"


def test_malformed_band_partition_is_failed_not_abstained():
    payload = _predict(
        band_rows=[
            {"bin_kind": "lte", "bin_value_c": 18},
            {"bin_kind": "gte", "bin_value_c": 21},
        ]
    )
    assert payload["status"] == "failed"
    assert payload["failure_reason"] == "invalid_band_partition"
    assert "probabilities" not in payload


def test_unfitted_ridge_pipeline_is_failed_without_model_substitution():
    artifact = _artifact()
    artifact["pipeline"] = Pipeline(
        [("imputer", SimpleImputer()), ("ridge", Ridge(alpha=1.0))]
    )
    payload = _predict(artifact=artifact)
    assert payload["status"] == "failed"
    assert payload["failure_reason"] == "inference_failed"
    assert "probabilities" not in payload


def test_artifact_is_pickle_safe_and_roundtrip_predictions_match():
    artifact = _artifact()
    restored = pickle.loads(pickle.dumps(artifact))
    left = _predict(artifact=artifact)
    right = _predict(artifact=restored)
    assert left["status"] == right["status"] == "predicted"
    assert right["probabilities"] == pytest.approx(left["probabilities"])
    assert right["mean_f"] == pytest.approx(left["mean_f"])


def test_temperature_change_is_applied_after_floor_and_band_projection():
    artifact = _artifact()
    artifact["calibration"]["temperature"] = 2.0
    features = _features(forecast_high=22.0, high_so_far=20.6)
    bands = _c_bands(floor=20, exact=21, ceiling=22)
    softened = _predict(artifact=artifact, feature_vector=features, band_rows=bands)
    identity = _predict(feature_vector=features, band_rows=bands)
    assert softened["status"] == "predicted"
    assert softened["probabilities"]["lte_20c"] == identity["probabilities"]["lte_20c"] == 0.0
    assert max(softened["probabilities"].values()) < max(identity["probabilities"].values())
