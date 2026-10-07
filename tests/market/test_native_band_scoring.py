"""A native temperature band must mean the same thing in every scorer.

The retired paper-maker and taker scorers were deleted on 2026-09-29; the
retained settlement-ledger and settlement-IO interpretations stay pinned here.
"""

import pandas as pd
import pytest

from weather.backtesting.settlement_io import band_value_hi
from weather.backtesting.settlement_ledger import parse_band_label, winning_band_from_frame


@pytest.mark.parametrize("label,bucket,expected", [
    ("-3 to -2 °C", -2, 1.0),
    ("-1 to 0 °C", 0, 1.0),
    ("-5 °C or below", -6, 1.0),
    ("-5 °C or below", -4, 0.0),
    ("-5 C or below", 0, 0.0),
    ("-5 C or below", -5, 1.0),
    ("80-81 F", 80, 1.0),
    ("80-81 F", 81, 1.0),
    ("80-81 F", 82, 0.0),
    ("−5–−4℃", -4, 1.0),
    ("-1-0 C", 0, 1.0),
])
def test_serving_ledger_band_interpretation_agrees(label, bucket, expected):
    row = {"range_label": label}
    parsed = parse_band_label(label)
    assert band_value_hi(label, parsed["value"]) == parsed["value_hi"]
    winner = winning_band_from_frame(pd.DataFrame([row]), bucket)
    assert bool(winner) == bool(expected)


@pytest.mark.parametrize("row", [
    {"range_label": "81-80 F"},
    {"range_label": "-5 C or below", "bin_value": 5},
    {"range_label": "80-81 F", "bin_value_hi": 79},
    {"range_label": "80 C-81 F", "bin_value": 80, "bin_value_hi": 81},
    {"range_label": "81-80 F", "bin_value": 80, "bin_value_hi": 81},
])
def test_invalid_or_contradictory_bands_remain_unscored(row):
    assert winning_band_from_frame(pd.DataFrame([row]), 80) == {}
