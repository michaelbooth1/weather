from __future__ import annotations

import pickle
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

from weather.calibration.pooled_candidate_replay import (
    _captured_residual_source_diagnostics,
    _compute_pooled_candidate_day,
    attach_residual_distribution_v1_probabilities,
    residual_distribution_v1_replay_payload,
)
from weather.collection.live_variant_predictions import _residual_distribution_v1_payload
from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.model.residual_distribution_v1 import (
    ARTIFACT_SCHEMA_VERSION,
    PREDICTION_MODE,
    predict_residual_distribution_v1,
)


FEATURE_NAMES = [
    "forecast_high",
    "forecast_high_available",
    "forecast_high_missing",
    "high_so_far",
    "high_so_far_available",
    "high_so_far_missing",
    "source_health_fresh_count",
    "source_health_failed_count",
    "source_open_meteo_fresh",
]


def _pipeline():
    rows = []
    for index in range(5):
        row = {name: 0.0 for name in FEATURE_NAMES}
        row.update(
            {
                "forecast_high": 66.0 + index,
                "forecast_high_available": 1.0,
                "high_so_far": 63.0 + index,
                "high_so_far_available": 1.0,
                "source_health_fresh_count": 1.0,
                "source_open_meteo_fresh": 1.0,
            }
        )
        rows.append(row)
    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("ridge", Ridge(alpha=5.0)),
        ]
    )
    pipeline.fit(pd.DataFrame(rows, columns=FEATURE_NAMES), [0.0] * len(rows))
    return pipeline


def _artifact():
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "prediction_mode": PREDICTION_MODE,
        "canonical_unit": "F",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "feature_contract": {
            "features": {
                "forecast_high": "absolute_temperature",
                "high_so_far": "absolute_temperature",
            },
            "required": ["forecast_high"],
        },
        "source_health_policy": {
            "required_sources": ["open_meteo"],
            "allowed_states": ["fresh"],
        },
        "pipeline": _pipeline(),
        "residual_sigma_f": 2.0,
        "grid_low_f": -40.0,
        "grid_high_f": 130.0,
        "grid_step_f": 0.1,
        "calibration": {"method": "identity"},
    }


def _feature_vector():
    return {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "forecast_high": 20.0,
        "high_so_far": 18.2,
        "cutoff_hour": 12,
    }


def _source_diagnostics():
    return [
        {
            "source": "open_meteo",
            "status": "fresh",
            "age_minutes": 10.0,
            "ttl_minutes": 120.0,
        }
    ]


def _live_bands():
    return [
        {"bin_kind": "lte", "bin_value_c": 19, "range_label": "19 C or below"},
        {"bin_kind": "eq", "bin_value_c": 20, "range_label": "20 C"},
        {"bin_kind": "gte", "bin_value_c": 21, "range_label": "21 C or above"},
    ]


def _replay_results():
    return {
        "all_rows": [
            {
                "market_id": "toronto",
                "snapshot_id": "s1",
                "bin_type": band["bin_kind"],
                "bin_value_c": band["bin_value_c"],
                "range_label": band["range_label"],
                "outcome": 1 if band["bin_value_c"] == 20 else 0,
                "replayed_p": 0.2,
                "market_yes": 0.3,
            }
            for band in _live_bands()
        ]
    }


def test_core_live_and_replay_use_identical_pure_probabilities(tmp_path):
    artifact = _artifact()
    feature_vector = _feature_vector()
    diagnostics = _source_diagnostics()
    bands = _live_bands()
    core = predict_residual_distribution_v1(
        artifact=artifact,
        feature_vector=feature_vector,
        source_diagnostics=diagnostics,
        market_id="toronto",
        unit="C",
        band_rows=bands,
    )
    replay = residual_distribution_v1_replay_payload(
        artifact=artifact,
        feature_vector=feature_vector,
        source_diagnostics=diagnostics,
        market_id="toronto",
        unit="C",
        band_rows=bands,
    )
    artifact_path = tmp_path / "candidate.pkl"
    artifact_path.write_bytes(pickle.dumps(artifact))
    live = _residual_distribution_v1_payload(
        {
            "variant_id": "residual-v1",
            "artifact_path": str(artifact_path),
            "artifact_hash": "a" * 64,
            "live_runtime": PREDICTION_MODE,
        },
        {
            "market_id": "toronto",
            "model": {
                "feature_vector": feature_vector,
                "source_diagnostics": diagnostics,
            },
            "band_rows": bands,
        },
    )
    assert core["status"] == replay["status"] == live["status"] == "predicted"
    assert replay["probabilities"] == core["probabilities"]
    assert live["probabilities"] == core["probabilities"]


def test_replay_attaches_complete_partition_without_postprocess_or_blend():
    forbidden = {
        "weather.calibration.pooled_candidate_replay.apply_continuous_density_calibration":
            "legacy density calibration",
        "weather.calibration.pooled_candidate_replay.apply_density_band_postprocessing":
            "legacy density postprocess",
        "weather.calibration.pooled_candidate_replay.apply_current_blend_guardrail":
            "incumbent blend",
        "weather.calibration.pooled_candidate_replay.normalize_partition_probabilities":
            "legacy normalization",
        "weather.calibration.pooled_candidate_replay.predict_density_rows_for_bundle":
            "legacy density model",
    }
    patches = [
        patch(path, side_effect=AssertionError(label))
        for path, label in forbidden.items()
    ]
    for context in patches:
        context.start()
    try:
        rows, coverage = attach_residual_distribution_v1_probabilities(
            _replay_results(),
            {("toronto", "s1"): _feature_vector()},
            {("toronto", "s1"): _source_diagnostics()},
            _artifact(),
            family_unit="all",
        )
    finally:
        for context in reversed(patches):
            context.stop()

    assert coverage["predicted_snapshots"] == 1
    assert coverage["candidate_rows"] == 3
    assert coverage["failure_reason_counts"] == {}
    assert sum(row["candidate_p"] for row in rows) == pytest.approx(1.0, abs=1e-12)
    assert all(row["candidate_countable"] for row in rows)
    assert {row["candidate_prediction_status"] for row in rows} == {"predicted"}


def test_missing_captured_source_diagnostics_is_named_noncountable_abstention():
    rows, coverage = attach_residual_distribution_v1_probabilities(
        _replay_results(),
        {("toronto", "s1"): _feature_vector()},
        {},
        _artifact(),
        family_unit="all",
    )
    assert coverage["candidate_rows"] == 0
    assert coverage["abstained_snapshots"] == 1
    assert coverage["source_diagnostics_missing_snapshots"] == 1
    assert coverage["failure_reason_counts"] == {"abstain_source_state": 1}
    assert all(row["candidate_p"] is None for row in rows)
    assert all(not row["candidate_countable"] for row in rows)
    assert {row["candidate_failure_reason"] for row in rows} == {"abstain_source_state"}
    assert "disallowed state 'unknown'" in rows[0]["candidate_failure_detail"]


def test_live_and_replay_delegate_missing_source_diagnostics_to_same_core(tmp_path):
    artifact = _artifact()
    replay = residual_distribution_v1_replay_payload(
        artifact=artifact,
        feature_vector=_feature_vector(),
        source_diagnostics=None,
        market_id="toronto",
        unit="C",
        band_rows=_live_bands(),
    )
    artifact_path = tmp_path / "candidate.pkl"
    artifact_path.write_bytes(pickle.dumps(artifact))
    live = _residual_distribution_v1_payload(
        {
            "variant_id": "residual-v1",
            "artifact_path": str(artifact_path),
            "artifact_hash": "a" * 64,
            "live_runtime": PREDICTION_MODE,
        },
        {
            "market_id": "toronto",
            "model": {"feature_vector": _feature_vector()},
            "band_rows": _live_bands(),
        },
    )
    assert replay["status"] == live["status"] == "skipped"
    assert replay["failure_reason"] == live["failure_reason"] == "abstain_source_state"
    assert replay["failure_detail"] == live["failure_detail"]


def test_artifact_failure_is_preserved_as_noncountable_failed_coverage():
    artifact = _artifact()
    artifact["schema_version"] = "corrupt"
    rows, coverage = attach_residual_distribution_v1_probabilities(
        _replay_results(),
        {("toronto", "s1"): _feature_vector()},
        {("toronto", "s1"): _source_diagnostics()},
        artifact,
        family_unit="all",
    )
    assert coverage["failed_snapshots"] == 1
    assert coverage["failure_reason_counts"] == {"invalid_artifact": 1}
    assert all(row["candidate_p"] is None for row in rows)
    assert {row["candidate_prediction_status"] for row in rows} == {"failed"}


def test_captured_source_diagnostics_accepts_explicit_status_envelopes_only():
    from_sources = _captured_residual_source_diagnostics(
        {
            "captured_at_local": "2026-07-12T12:00:00-04:00",
            "sources": {
                "open_meteo": {
                    "ok": True,
                    "stale": False,
                    "fetched_at": "2026-07-12T15:50:00+00:00",
                    "ttl_minutes": 120,
                }
            },
        }
    )
    assert from_sources == [
        {
            "source": "open_meteo",
            "source_family": "open_meteo",
            "status": "fresh",
            "age_minutes": 10.0,
            "ttl_minutes": 120.0,
            "degradation_state": None,
            "cache_status": None,
            "physical_validity_status": None,
        }
    ]
    assert _captured_residual_source_diagnostics(
        {
            "captured_at_local": "2026-07-12T12:00:00-04:00",
            "sources": {
                "open_meteo": {"fetched_at": "2026-07-12T15:50:00+00:00"}
            },
        }
    ) is None
    assert _captured_residual_source_diagnostics(
        {"source_diagnostics": _source_diagnostics()}
    ) == _source_diagnostics()
    assert _captured_residual_source_diagnostics(
        {"source_status": {"open_meteo": {"status": "fresh"}}}
    ) == [{"source": "open_meteo", "status": "fresh"}]


def test_compute_day_dispatches_residual_mode_to_isolated_adapter():
    replay_results = _replay_results()
    feature_rows = {("toronto", "s1"): _feature_vector()}
    diagnostic_rows = {("toronto", "s1"): _source_diagnostics()}
    args = SimpleNamespace(
        snapshots_root="unused",
        clob_max_age_seconds=180.0,
        long_job_guard_info=None,
    )
    with (
        patch(
            "weather.calibration.pooled_candidate_replay._single_entry_manifest",
            return_value={"include_reconstructed": False},
        ),
        patch(
            "weather.calibration.pooled_candidate_replay.run_replay_backtest",
            return_value=replay_results,
        ),
        patch(
            "weather.calibration.pooled_candidate_replay.build_candidate_features",
            return_value=(feature_rows, {"feature_rows": 1}),
        ),
        patch(
            "weather.calibration.pooled_candidate_replay.build_residual_source_diagnostics_index",
            return_value=(diagnostic_rows, {"residual_source_diagnostics_snapshots": 1}),
        ),
        patch(
            "weather.calibration.pooled_candidate_replay.attach_density_candidate_probabilities",
            side_effect=AssertionError("legacy density route must not run"),
        ),
    ):
        output = _compute_pooled_candidate_day(
            args,
            {},
            "unused-folder",
            _artifact(),
            family_unit="all",
            prediction_mode=PREDICTION_MODE,
        )
    assert output["coverage"]["predicted_snapshots"] == 1
    assert output["coverage"]["candidate_rows"] == 3
    assert output["diagnostics"]["residual_source_diagnostics_snapshots"] == 1
