"""Legacy CSV upper cells preserve native settlement-band evidence."""

import csv
import io

import pandas as pd
import pytest

from weather.backtesting.settlement_ledger import winning_band_from_frame


@pytest.mark.parametrize("unit", ["C", "F"])
@pytest.mark.parametrize("lower, upper", [(90, 91), (-5, -4), (-1, 0)])
@pytest.mark.parametrize("upper_field", ["bin_value_hi", "bin_value_hi_c"])
@pytest.mark.parametrize("missing_cell", ["", "NaN"])
def test_csv_missing_upper_recovers_native_winner_without_mutating_frame(
    unit, lower, upper, upper_field, missing_cell
):
    label = f"{lower}-{upper} {unit}"
    row = {
        "bin_kind": "eq",
        "bin_value_c": lower,
        upper_field: missing_cell,
        "range_label": label,
    }
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    stream.seek(0)
    frame = pd.read_csv(stream)
    original = frame.copy(deep=True)

    assert winning_band_from_frame(frame, upper) == {
        "label": label, "kind": "eq", "value": lower, "value_hi": upper,
    }
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("unit", ["C", "F"])
@pytest.mark.parametrize("lower, upper", [(90, 91), (-5, -4), (-1, 0)])
def test_legacy_tape_without_upper_column_keeps_label_fallback(unit, lower, upper):
    label = f"{lower}-{upper} {unit}"
    stream = io.StringIO(
        f"bin_kind,bin_value_c,range_label\neq,{lower},{label}\n"
    )
    assert winning_band_from_frame(pd.read_csv(stream), upper) == {
        "label": label, "kind": "eq", "value": lower, "value_hi": upper,
    }


@pytest.mark.parametrize("unit", ["C", "F"])
@pytest.mark.parametrize("upper_field", ["bin_value_hi", "bin_value_hi_c"])
def test_explicit_zero_upper_keeps_legacy_single_value_display_label(unit, upper_field):
    frame = pd.DataFrame([{
        "bin_kind": "eq",
        "bin_value_c": -1,
        upper_field: 0,
        "range_label": f"-1 {unit}",
    }])
    assert winning_band_from_frame(frame, 0) == {
        "label": f"-1 {unit}", "kind": "eq", "value": -1, "value_hi": 0,
    }
    assert winning_band_from_frame(frame, 1) == {}


def test_missing_native_upper_can_use_explicit_legacy_zero_before_label():
    frame = pd.DataFrame([{
        "bin_kind": "eq",
        "bin_value_c": -1,
        "bin_value_hi": float("nan"),
        "bin_value_hi_c": 0,
        "range_label": "-1 C",
    }])
    original = frame.copy(deep=True)
    assert winning_band_from_frame(frame, 0) == {
        "label": "-1 C", "kind": "eq", "value": -1, "value_hi": 0,
    }
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("override", [
    {"bin_value_hi_c": float("inf")},
    {"bin_value_hi_c": -float("inf")},
    {"bin_value_hi_c": True},
    {"bin_value_hi_c": -4.5},
    {"bin_value_hi_c": "bad"},
    {"bin_value_hi_c": "nan"},
    {"bin_value_hi_c": -3},
    {"bin_value_hi_c": -6},
    {"bin_value_c": float("nan"), "bin_value_hi_c": float("nan")},
    {"bin_value_c": True},
    {"bin_value_c": -5.5},
    {"bin_kind": "gte", "bin_value_hi_c": float("nan")},
    {"range_label": "-5--6 C", "bin_value_hi_c": float("nan")},
    {"range_label": "unknown -5", "bin_value_hi_c": float("nan")},
])
def test_missing_upper_repair_does_not_rescue_invalid_typed_evidence(override):
    frame = pd.DataFrame([{
        "bin_kind": "eq",
        "bin_value_c": -5,
        "bin_value_hi_c": -4,
        "range_label": "-5--4 C",
        **override,
    }])
    original = frame.copy(deep=True)
    assert winning_band_from_frame(frame, -4) == {}
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("reverse", [False, True])
def test_existing_first_matching_row_selection_is_preserved(reverse):
    rows = [
        {"bin_kind": "eq", "bin_value_c": -1, "bin_value_hi_c": float("nan"),
         "range_label": "-1-0 C"},
        {"bin_kind": "eq", "bin_value_c": 0, "bin_value_hi_c": 0,
         "range_label": "0 C"},
    ]
    if reverse:
        rows.reverse()
    winner = winning_band_from_frame(pd.DataFrame(rows), 0)
    assert winner["label"] == rows[0]["range_label"]
    assert winner["value"] == rows[0]["bin_value_c"]
    assert winner["value_hi"] == 0
