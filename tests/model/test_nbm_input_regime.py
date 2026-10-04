"""A v1-trained artifact never consumes parser-v2 NBM values (EF 10k/10l)."""
import json
import math
import pickle
from datetime import date, datetime, timezone

import numpy as np
import pytest

from weather.collection.live_variant_predictions import (
    build_live_variant_prediction_rows,
    trace_pooled_band_binary_probabilities,
)
from weather.model.nbm_input_regime import (
    artifact_nbm_parser_version,
    nbm_parser_label,
    quarantine_nbm_inputs,
    row_nbm_parser_version,
)
from weather.reporting.candidate_lifecycle.variant_registry import SCHEMA_VERSION as REGISTRY_SCHEMA_VERSION
from weather.sources.nbm_probabilistic_tmax import (
    NBM_NBP_PARSER_V1,
    NBM_NBP_PARSER_V2,
    NBM_PROB_TMAX_FEATURE_COLUMNS,
)

SEEN_ROWS = []
FEATURES = ["cutoff_hour", "nbm_prob_tmax_p50", "nbm_prob_tmax_stddev"]


class IdentityImputer:
    def transform(self, frame):
        return frame


class RecordingClassifier:
    classes_ = [0, 1]

    def predict_proba(self, rows):
        SEEN_ROWS.extend(np.asarray(rows, dtype=float).tolist())
        return [[0.4, 0.6] for _ in range(len(rows))]


def _artifact(**extra):
    return {
        "prediction_mode": "band_binary",
        "models": {"12": {
            "model": RecordingClassifier(), "imputer": IdentityImputer(),
            "feature_names": list(FEATURES), "classes": [0, 1],
        }},
        "postprocess": {"partition_normalization_enabled": False, "current_blend_enabled": False},
        **extra,
    }


def _vector(parser_version):
    vector = {
        "cutoff_hour": 12, "market_id": "miami", "high_so_far": 80.0,
        "nbm_prob_tmax_p50": 88.0, "nbm_prob_tmax_stddev": 2.0,
    }
    if parser_version is not None:
        vector["nbm_prob_tmax_parser_version"] = float(parser_version)
    return vector


def _band_rows():
    return [{
        "snapshot_id": "snap", "range_label": "88-89", "bin_kind": "range",
        "bin_value_c": 88, "bin_value_hi_c": 89, "model_probability": 0.3,
        "market_yes": 0.3, "market_no": 0.7, "condition_id": "c", "market_status": "active",
    }]


def test_artifact_regime_defaults_to_v1_only_when_it_selects_nbm():
    assert artifact_nbm_parser_version({"models": {"12": {"feature_names": ["cutoff_hour"]}}}) is None
    assert artifact_nbm_parser_version(None) is None
    assert artifact_nbm_parser_version(_artifact()) == 1
    assert artifact_nbm_parser_version(_artifact(nbm_prob_tmax_parser_version=NBM_NBP_PARSER_V2)) == 2
    assert artifact_nbm_parser_version({"feature_names": ["nbm_prob_tmax_p10"]}) == 1
    with pytest.raises(ValueError):
        artifact_nbm_parser_version(_artifact(nbm_prob_tmax_parser_version=3))
    assert nbm_parser_label(1) == NBM_NBP_PARSER_V1 and nbm_parser_label(None) is None


def test_row_without_recorded_version_is_v1():
    assert row_nbm_parser_version({}) == 1
    assert row_nbm_parser_version({"nbm_prob_tmax_parser_version": float("nan")}) == 1
    assert row_nbm_parser_version({"nbm_prob_tmax_parser_version": 2.0}) == 2
    with pytest.raises(ValueError):
        row_nbm_parser_version({"nbm_prob_tmax_parser_version": 2.5})


def test_mismatch_masks_every_nbm_input_and_match_is_untouched():
    v2_row = {column: 1.0 for column in NBM_PROB_TMAX_FEATURE_COLUMNS}
    v2_row["nbm_prob_tmax_parser_version"] = 2.0
    v2_row["forecast_high"] = 85.0
    decision = quarantine_nbm_inputs(v2_row, 1)
    assert decision == {"trained_parser_version": 1, "row_parser_version": 2, "masked": True, "masked_values": 15}
    assert all(v2_row[column] is None for column in NBM_PROB_TMAX_FEATURE_COLUMNS)
    assert v2_row["forecast_high"] == 85.0 and v2_row["nbm_prob_tmax_parser_version"] == 2.0

    v1_row = {"nbm_prob_tmax_p50": 88.0}
    assert quarantine_nbm_inputs(v1_row, 1)["masked"] is False
    assert v1_row["nbm_prob_tmax_p50"] == 88.0
    # A future v2-trained artifact refuses v1 values the same way.
    assert quarantine_nbm_inputs(v1_row, 2)["masked"] is True and v1_row["nbm_prob_tmax_p50"] is None
    assert quarantine_nbm_inputs({"nbm_prob_tmax_p50": 1.0}, None) is None


def _live_rows(tmp_path, artifact_payload, vector):
    artifact = tmp_path / f"pooled-{len(list(tmp_path.iterdir()))}.pkl"
    artifact.write_bytes(pickle.dumps(artifact_payload))
    registry = tmp_path / f"registry-{artifact.stem}.json"
    registry.write_text(json.dumps({"schema_version": REGISTRY_SCHEMA_VERSION, "variants": [{
        "variant_id": "pooled_f_candidate_miami_current_fallback_v0_1", "variant_family": "pooled_f_candidate",
        "lifecycle": "active", "track": "no_market", "active_for_headline": False, "live_capture_enabled": True,
        "artifact_path": str(artifact), "live_runtime": "pooled_candidate_replay",
    }]}), encoding="utf-8")

    class Client:
        target_date = date(2026, 10, 5)

        def source_data(self, *_):
            return {}

    return build_live_variant_prediction_rows(
        snapshot_id="snap", captured_at=datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc),
        event={"slug": "highest-temperature-in-miami-on-october-5-2026"},
        model={"distribution": {88: 1.0}, "feature_vector": vector}, model_client=Client(),
        band_rows=_band_rows(), event_slug="highest-temperature-in-miami-on-october-5-2026",
        market_id="miami", target_date=date(2026, 10, 5), serving_model_version="serving",
        release_lineage={}, captured_input_hash="c" * 64, runtime_fields={},
        snapshot_cadence="triggered", cadence_quality=None, trigger_summary={}, registry_path=registry,
    )


def test_live_writer_feeds_v1_artifact_no_v2_values(tmp_path):
    SEEN_ROWS.clear()
    rows = _live_rows(tmp_path, _artifact(), _vector(parser_version=2))
    assert rows[0]["prediction_status"] == "predicted"
    p50 = SEEN_ROWS[-1][FEATURES.index("nbm_prob_tmax_p50")]
    assert math.isnan(p50)

    SEEN_ROWS.clear()
    rows = _live_rows(tmp_path, _artifact(), _vector(parser_version=None))
    assert rows[0]["prediction_status"] == "predicted"
    assert SEEN_ROWS[-1][FEATURES.index("nbm_prob_tmax_p50")] == 88.0

    SEEN_ROWS.clear()
    rows = _live_rows(tmp_path, _artifact(nbm_prob_tmax_parser_version=2), _vector(parser_version=2))
    assert SEEN_ROWS[-1][FEATURES.index("nbm_prob_tmax_p50")] == 88.0


def test_live_writer_fails_closed_on_unknown_row_version(tmp_path):
    rows = _live_rows(tmp_path, _artifact(), _vector(parser_version=7))
    assert rows[0]["prediction_status"] == "failed"
    assert rows[0]["failure_reason"] == "nbm_input_regime_unsupported"


def test_trace_reports_the_regime_without_mutating_the_caller_vector():
    vector = _vector(parser_version=2)
    trace = trace_pooled_band_binary_probabilities(_artifact(), vector, _band_rows(), {})
    assert trace["nbm_input_regime"]["masked"] is True
    assert vector["nbm_prob_tmax_p50"] == 88.0


def test_replay_feature_build_masks_v2_rows_for_v1_artifact_and_counts_them():
    from pathlib import Path
    from unittest.mock import patch

    from weather.calibration.pooled_candidate_replay import build_candidate_features

    def record_feature(_model, _spec, _climate, record, **_kwargs):
        row = {"cutoff_hour": 12, "nbm_prob_tmax_p50": 88.0, "nbm_prob_tmax_stddev": 2.0}
        if record["snapshot_id"] == "after-adoption":
            row["nbm_prob_tmax_parser_version"] = 2.0
        return row

    target = "weather.calibration.pooled_candidate_replay."
    with (
        patch(target + "folders_from_manifest", return_value=[Path("miami-high-2026-10-05")]),
        patch(target + "folder_market_id", return_value="miami"),
        patch(target + "entry_for_folder", return_value={"snapshot_ids": ["before-adoption", "after-adoption"]}),
        patch(target + "_model_for_market", return_value=object()),
        patch(target + "_climate_for_market", return_value={}),
        patch(target + "_source_reliability_for_market", return_value={}),
        patch(target + "load_replay_records", return_value=[
            {"snapshot_id": "before-adoption"}, {"snapshot_id": "after-adoption"},
        ]),
        patch(target + "record_target_date", return_value=date(2026, 10, 5)),
        patch(target + "_record_feature_row", side_effect=record_feature),
    ):
        features, diagnostics = build_candidate_features(
            {"include_reconstructed": False}, "snapshots", "F", artifact=_artifact(),
        )

    assert features[("miami", "before-adoption")]["nbm_prob_tmax_p50"] == 88.0
    assert features[("miami", "after-adoption")]["nbm_prob_tmax_p50"] is None
    assert diagnostics["nbm_input_regime"] == {
        "trained_parser": NBM_NBP_PARSER_V1, "masked_rows": 1, "masked_values": 2,
    }
