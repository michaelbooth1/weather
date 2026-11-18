import csv
import json
from types import SimpleNamespace

import pytest

import weather.collection.snapshot_store as snapshot_store
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


OLD_HGB = "v0.4 HGBC feature-based ML model"
NEW_HGB = "v0.5 HGBC feature-based ML model"
UNVERSIONED_HGB = "HGBC feature-based ML model (version unrecorded)"


@pytest.mark.parametrize(
    ("kind", "replay_file", "source", "feature_version", "recorded_version", "top_version", "expected"),
    [
        ("hgb", "reconstructed", None, OLD_HGB, NEW_HGB, None, OLD_HGB),
        ("hgb", "normal", "reconstructed", OLD_HGB, NEW_HGB, None, OLD_HGB),
        ("hgb", "normal", None, OLD_HGB, NEW_HGB, None, "model version unrecorded (conflicting original versions)"),
        ("hgb", "normal", None, OLD_HGB, OLD_HGB, None, OLD_HGB),
        ("hgb", "normal", None, OLD_HGB, NEW_HGB, "explicit", "explicit"),
        ("hgb", "reconstructed", None, None, NEW_HGB, None, UNVERSIONED_HGB),
        ("hgb", "normal", None, None, OLD_HGB, None, OLD_HGB),
        ("hgb", "normal", None, UNVERSIONED_HGB, OLD_HGB, None, OLD_HGB),
        (None, "normal", None, None, "opaque-original", None, "opaque-original"),
        (None, "reconstructed", None, None, "later-reconstruction", None, MODEL_VERSION),
    ],
)
def test_explanation_backfill_distinguishes_original_versions_from_reconstruction(
    tmp_path, monkeypatch, kind, replay_file, source, feature_version, recorded_version, top_version, expected
):
    store = object.__new__(SnapshotStore)
    store._set_paths(tmp_path, "synthetic-event")
    event = SimpleNamespace(target_date="2025-08-01", market_id="synthetic")
    monkeypatch.setattr(snapshot_store, "config_from_event", lambda *args, **kwargs: event)
    snapshot = {
        "snapshot_id": "example",
        "captured_at_utc": "2025-08-01T12:00:00+00:00",
        "model_version": top_version,
        "feature_vector": {"model_version": feature_version},
        "distribution_components": {"active_model_kind": kind},
        "model_explanation": {"summary": "synthetic"},
    }
    store.append_jsonl(store.jsonl_path, snapshot)
    reconstructed = store.root / snapshot_store.REPLAY_RECONSTRUCTED_FILENAME
    if replay_file == "normal":
        # A reconstructed duplicate in a separate file cannot demote the original.
        store.append_jsonl(reconstructed, {"snapshot_id": "example", "model_version": "ignored duplicate"})
    path = store.replay_inputs_path if replay_file == "normal" else reconstructed
    store.append_jsonl(path, {"snapshot_id": "example", "model_version": recorded_version, "source": source})

    assert store.backfill_snapshot_explanations()["written_snapshot_count"] == 1
    payload = json.loads(store.snapshot_explanations_jsonl_path.read_text(encoding="utf-8"))
    assert payload["model_version"] == expected
    with store.snapshot_explanations_long_path.open(encoding="utf-8", newline="") as handle:
        assert {row["model_version"] for row in csv.DictReader(handle)} == {expected}
