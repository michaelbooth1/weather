"""Guards: native market-band endpoints agree in scored artifact replay and serving."""

import csv
from types import SimpleNamespace

import pytest

from weather.calibration.probability_calibration import (
    artifact_market_predictions,
    prepare_training_row,
    read_scored_rows,
)
from weather.model.toronto_model import TorontoHighTempModel


def served_probability(label, unit, distribution, artifact, floor, support):
    # Use the actual venue parser and probability API with an in-memory artifact.
    model = TorontoHighTempModel.__new__(TorontoHighTempModel)
    model.spec = SimpleNamespace(display_unit=unit)
    model.probability_calibration = artifact
    band, = model.market_bins({"markets": [{"groupItemTitle": label}]})
    return model.bin_probability(distribution, band, {
        "observed_floor_bucket": floor, "observed_support_bucket": support,
    })


@pytest.mark.parametrize("hi_c,hi,tape_label", [
    (93, None, "92 F"),
    (None, 93, "92 F"),
    (None, None, "92–93°F"),
])
def test_scored_csv_replay_matches_serving_at_upper_endpoint(tmp_path, hi_c, hi, tape_label):
    folder = tmp_path / "highest-temperature-in-nyc-on-january-1-2001"
    folder.mkdir()
    snapshot = {
        "event_slug": folder.name, "captured_at_local": "2001-01-01T13:00:00-05:00",
        "bin_kind": "eq", "bin_value_c": 92, "bin_value_hi_c": hi_c, "bin_value_hi": hi,
        "range_label": tape_label, "model_probability": 0.88, "market_yes": 0.50,
        "wu_history_high_native": 93,
    }
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=snapshot)
        writer.writeheader()
        writer.writerow(snapshot)
    row, = read_scored_rows([folder], daily_summary_path=None, overrides={"2001-01-01": 93})
    assert (row["bin_value_hi"], row["outcome"], row["observed_floor_bucket"]) == (93, 1, 93)
    artifact = {"market_bin": {"enabled": True}}
    replay, = artifact_market_predictions([row], artifact)
    served = served_probability("92–93°F", "F", {93: 0.88, 94: 0.12}, artifact, 93, 93)
    assert replay == served == 0.88


@pytest.mark.parametrize("kind,lo,hi,label,floor,expected", [
    ("eq", -2, -1, "-2--1 C", -1, 0.88),
    ("eq", -1, 0, "-1-0 C", 0, 0.88),
    ("eq", -1, 0, "-1-0 C", 1, 0.0),
    ("eq", 0, 0, "0 C", 0, 0.88),
    ("eq", 0, 0, "0 C", 1, 0.0),
    ("lte", 0, 0, "0 C or below", 0, 0.88),
    ("lte", 0, 0, "0 C or below", 1, 0.0),
    ("gte", 0, 0, "0 C or above", -1, 0.88),
    ("gte", 0, 0, "0 C or above", 0, 1.0),
])
def test_legacy_scored_label_and_open_tail_boundaries(kind, lo, hi, label, floor, expected):
    row = prepare_training_row({
        "bin_kind": kind, "bin_value_c": lo, "band": label, "bin_value_hi": float("nan"),
        "wu_history_high_native": floor, "model_probability": 0.88,
    })
    assert row["bin_value_hi"] == hi
    outside = lo - 1 if kind == "gte" else hi + 1
    artifact = {"market_bin": {"enabled": True}}
    replay, = artifact_market_predictions([row], artifact)
    served = served_probability(label, "C", {hi: 0.88, outside: 0.12}, artifact, floor, floor)
    assert replay == served == expected


@pytest.mark.parametrize("floor,support,allow_lift,expected", [
    (-2, -1, True, 0.35), (-2, 0, True, 0.35), (0, 0, True, 0.35),
    (-2, 1, True, 0.02), (-2, 0, False, 0.02),
])
def test_observed_support_and_opt_in_lift_use_entire_band(floor, support, allow_lift, expected):
    artifact = {"market_bin": {
        "enabled": True, "preserve_distribution_coherence": False, "allow_exact_lift": allow_lift,
        "base_rate": 0.35, "weight": 1.0,
    }}
    row = prepare_training_row({
        "bin_kind": "eq", "bin_value_c": -1, "bin_value_hi": 0, "band": "-1 C",
        "wu_history_high_native": floor, "wu_current_native": support, "model_probability": 0.02,
    })
    replay, = artifact_market_predictions([row], artifact)
    served = served_probability("-1-0 C", "C", {0: 0.02, 1: 0.98}, artifact, floor, support)
    assert replay == served == expected


def test_older_prepared_rows_read_any_remaining_band_evidence():
    artifact = {"market_bin": {"enabled": True}}
    stripped = {"bin_kind": "eq", "bin_value_c": 92, "cutoff_hour": 13,
                "observed_floor_bucket": 93, "model_probability": 0.88}
    labelled = {**stripped, "band": "92-93 F", "bin_value_hi": "NaN"}
    assert artifact_market_predictions([stripped, labelled], artifact) == [0.0, 0.88]
