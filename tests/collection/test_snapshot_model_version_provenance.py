import csv

import pytest

from weather.collection.snapshot_store import MODEL_VERSION, SnapshotStore, snapshot_model_version
from weather.reporting.validation.point_in_time_evaluation import canonicalize_raw_row


@pytest.mark.parametrize(
    ("kind", "feature_version", "expected"),
    [
        ("lr", "v0.5.10 LogisticRegression feature-based ML model", "v0.5.10 LogisticRegression feature-based ML model"),
        ("lr", None, "LogisticRegression feature-based ML model (version unrecorded)"),
        ("empirical", None, "empirical lookup baseline (version unrecorded)"),
    ],
)
def test_backfilled_component_variant_uses_original_scorer(tmp_path, kind, feature_version, expected):
    store = object.__new__(SnapshotStore)
    store._set_paths(tmp_path, "synthetic-event")
    snapshot = {
        "snapshot_id": "example",
        "captured_at_local": "2025-08-01T12:00:00-04:00",
        "distribution_components": {"active_model_kind": kind, "components": {"final_model": {"70": 1.0}}},
        "bands": [{"range_label": "70", "bin_kind": "eq", "bin_value_c": 70, "bin_value_hi_c": 70}],
        "feature_vector": {"cutoff_hour": 12, "model_version": feature_version},
    }
    store.append_jsonl(store.jsonl_path, snapshot)
    assert store.backfill_feature_component_sidecars()["written_component_row_count"] == 1
    with store.components_long_path.open(encoding="utf-8", newline="") as handle:
        component, = csv.DictReader(handle)
    with store.features_long_path.open(encoding="utf-8", newline="") as handle:
        feature, = csv.DictReader(handle)
    assert feature["model_version"] == expected
    assert component["active_model_kind"] == kind
    analysis_row = canonicalize_raw_row(
        dict(component, release_id="synthetic-release", runtime_identity="synthetic-runtime"),
        provenance={"source_mode": "synthetic"},
        market_id="synthetic-market",
        target_date="2025-08-01",
        explicit_claim_lane="weather_only",
    )
    assert analysis_row["variant_id"] == expected
    assert store.backfill_feature_component_sidecars()["written_component_row_count"] == 0


def test_known_family_resolves_replay_display_and_preserves_explicit_version():
    model = {
        "active_model_kind": "lr",
        "feature_vector": {"model_version": "v0.5.10 LogisticRegression feature-based ML model"},
    }
    assert snapshot_model_version(model, replay_version=MODEL_VERSION) == model["feature_vector"]["model_version"]
    explicit = dict(model, model_version="recorded-explicit")
    assert snapshot_model_version(explicit, replay_version=MODEL_VERSION) == "recorded-explicit"
    result = {"distribution_result": {"active_model_kind": "empirical"}}
    assert snapshot_model_version(result) == "empirical lookup baseline (version unrecorded)"
    assert snapshot_model_version({**model, **result}) == "model version unrecorded (conflicting scorer families)"
    assert snapshot_model_version({}, replay_version="original-replay-version") == "original-replay-version"
    assert snapshot_model_version({}) == MODEL_VERSION
