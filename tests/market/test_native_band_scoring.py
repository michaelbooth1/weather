"""A native temperature band must mean the same thing in every scorer."""

import pandas as pd
import pytest

from weather.backtesting.settlement_io import band_value_hi
from weather.backtesting.settlement_ledger import parse_band_label, winning_band_from_frame
from weather.market.mm_paper_scoring import band_key, settlement_outcome_for_leg
from weather.market.taker_bot_scoring import band_key as taker_band_key, settlement_outcome_for_order
from weather.market.taker_bot_strategy_evaluation import band_key as evaluation_band_key


@pytest.mark.parametrize("label,bucket,expected", [
    ("-5 C or below", 0, 0.0),
    ("-5 C or below", -5, 1.0),
    ("80-81 F", 80, 1.0),
    ("80-81 F", 81, 1.0),
    ("80-81 F", 82, 0.0),
    ("−5–−4℃", -4, 1.0),
    ("-1-0 C", 0, 1.0),
])
def test_serving_ledger_and_paper_band_interpretation_agree(label, bucket, expected):
    row = {"range_label": label}
    settlement = {"settlement_bucket": bucket}
    parsed = parse_band_label(label)
    key = (parsed["kind"], parsed["value"], parsed["value_hi"])
    assert band_key(row) == taker_band_key(row) == evaluation_band_key(row) == key
    assert band_value_hi(label, parsed["value"]) == parsed["value_hi"]
    assert settlement_outcome_for_leg(row, settlement) == expected
    assert settlement_outcome_for_order(row, settlement) == expected
    assert settlement_outcome_for_order(dict(row, side="NO_BUY"), settlement) == 1.0 - expected
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
    settlement = {"settlement_bucket": 80}
    assert settlement_outcome_for_leg(row, settlement) is None
    assert settlement_outcome_for_order(row, settlement) is None
    assert winning_band_from_frame(pd.DataFrame([row]), 80) == {}
