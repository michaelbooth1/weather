"""Sidecar reconstruction preserves the recorded native band contract."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from weather.backtesting.replay import band_bin_data
from weather.collection.snapshot_store import SnapshotStore


@pytest.fixture
def store():
    # Only pure decoding/projection methods are used; do not initialize paths.
    result = object.__new__(SnapshotStore)
    result.event_slug = "fixture-event"
    return result


@pytest.mark.parametrize("unit", ["C", "F"])
@pytest.mark.parametrize("legacy_upper", [False, True])
@pytest.mark.parametrize(
    "labels, values, highs, distribution",
    [
        (["-6 {u} or below", "-5--4 {u}", "-3 {u} or higher"],
         [-6, -5, -3], [-6, -4, -3], {-6: 0.2, -5: 0.1, -4: 0.4, -3: 0.3}),
        (["-2 {u} or below", "-1-0 {u}", "1 {u} or higher"],
         [-2, -1, 1], [-2, 0, 1], {-2: 0.2, -1: 0.1, 0: 0.4, 1: 0.3}),
        (["-1 {u} or below", "0 {u}", "1 {u} or higher"],
         [-1, 0, 1], [-1, 0, 1], {-1: 0.2, 0: 0.5, 1: 0.3}),
        (["74 {u} or below", "75-76 {u}", "77 {u} or higher"],
         [74, 75, 77], [74, 76, 77], {74: 0.2, 75: 0.1, 76: 0.4, 77: 0.3}),
    ],
)
def test_snapshot_sidecar_bands_match_replay_and_preserve_mass(
    store, unit, legacy_upper, labels, values, highs, distribution
):
    bands = []
    for label, kind, value, high in zip(labels, ("lte", "eq", "gte"), values, highs):
        row = {
            "range_label": label.format(u=unit),
            "bin_kind": kind,
            "bin_value_c": value,
            "market_yes": 0.5,
        }
        if not legacy_upper:
            row["bin_value_hi_c"] = high
        bands.append(row)
    snapshot = {"bands": bands}
    original = deepcopy(snapshot)
    decoded = store.snapshot_band_bins(snapshot)
    for band, row, high in zip(decoded, bands, highs):
        replay = band_bin_data(row)
        assert band == {
            "label": row["range_label"],
            "kind": replay["kind"],
            "value": replay["value"],
            "value_hi": high,
            "market_yes": 0.5,
        }
        assert replay["value_hi"] == high
    components = store.component_rows(
        {"components": {"final_model": distribution}},
        decoded,
        "snapshot-1",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "fixture-model",
    )
    assert [row["bin_value_c"] for row in components] == values
    assert [row["bin_value_hi_c"] for row in components] == highs
    probabilities = [row["component_probability"] for row in components]
    assert probabilities == pytest.approx([0.2, 0.5, 0.3])
    assert sum(probabilities) == pytest.approx(1.0)
    assert snapshot == original


def test_snapshot_legacy_kind_and_native_aliases_keep_zero_upper_endpoint(store):
    snapshot = {"bands": [{
        "kind": "eq",
        "bin_value": -1,
        "bin_value_hi": 0,
        "range_label": "-1 C",
    }]}
    assert store.snapshot_band_bins(snapshot) == [{
        "label": "-1 C", "kind": "eq", "value": -1, "value_hi": 0, "market_yes": None,
    }]


@pytest.mark.parametrize(
    "band",
    [
        {"bin_value_c": 0, "range_label": "unknown 0"},
        {"bin_value_c": -5, "range_label": "-5--6 C"},
        {"bin_kind": "gte", "bin_value_c": -5, "range_label": "-5 C or below"},
        {"bin_value_c": -5, "bin_value_hi_c": -3, "range_label": "-5--4 C"},
        {"bin_value_c": 0, "bin_value_hi_c": "bad", "range_label": "0 C"},
        {"bin_value_c": "nan", "range_label": "0 C"},
        {"bin_value_c": True, "range_label": "1 C"},
        {"bin_value_c": 0.5},
    ],
)
def test_invalid_snapshot_band_explicitly_blocks_sidecar_reconstruction(store, band):
    snapshot = {"bands": [band]}
    original = deepcopy(snapshot)
    with pytest.raises(ValueError, match="cannot backfill an invalid native temperature band"):
        store.snapshot_band_bins(snapshot)
    assert snapshot == original
