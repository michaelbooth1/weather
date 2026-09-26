"""Fixture coverage for 110m's remaining signed capture consumers."""

from datetime import datetime, timezone

import pytest

from weather.market.market_microstructure_capture import label_bin_metadata, token_rows_from_event
from weather.operations.observation_trigger import band_key, band_outcome


@pytest.mark.parametrize("label,unit,expected", [
    ("-2°C or below", "C", ("lte", -2, -2)),
    ("-1°C", "C", ("eq", -1, -1)),
    ("-3 to -2", "C", ("eq", -3, -2)),
    ("-3--2°C", "C", ("eq", -3, -2)),
    ("0 C", "C", ("eq", 0, 0)),
    ("20 C or below", "C", ("lte", 20, 20)),
    ("20 C", "C", ("eq", 20, 20)),
    ("20-21 C", "C", ("eq", 20, 21)),
    ("20 to 21", "C", ("eq", 20, 21)),
    ("20 or higher", "C", ("gte", 20, 20)),
    ("20°C or above", "C", ("gte", 20, 20)),
    ("88-89°F", "F", ("eq", 88, 89)),
    ("80 F or below", "F", ("lte", 80, 80)),
    ("90°F or higher", "F", ("gte", 90, 90)),
])
def test_golden_native_band_rows(label, unit, expected):
    kind, low, high = expected
    assert label_bin_metadata(label, unit) == {
        "bin_kind": kind, "bin_value": low, "bin_value_hi": high, "unit": unit,
    }
    assert band_key({"range_label": label}) == expected
    assert band_key({"band_key": f"{kind}:{low}" if low == high else f"{kind}:{low}-{high}"}) == expected


@pytest.mark.parametrize("row,expected", [
    ({"bin_kind": "eq", "bin_value_c": 0, "bin_value": 20}, ("eq", 0, 0)),
    ({"bin_kind": "eq", "bin_value_c": -1, "bin_value_hi_c": 0,
      "bin_value_hi": 20}, ("eq", -1, 0)),
    ({"bin_value_c": "", "bin_value": 0, "range_label": "0 C"}, ("eq", 0, 0)),
    ({"bin_kind": "eq", "bin_value_c": "88", "range_label": "88-89°F"}, ("eq", 88, 89)),
    ({"band_key_text": "eq:88", "range_label": "88-89°F"}, ("eq", 88, 89)),
    ({"band_key": "eq:088-089"}, ("eq", 88, 89)),
    ({"band_key": "lte:-2"}, ("lte", -2, -2)),
    ({"band_key": "gte:0"}, ("gte", 0, 0)),
])
def test_persisted_fields_keep_precedence_and_zero(row, expected):
    assert band_key(row) == expected


@pytest.mark.parametrize("label", ["", None, "Will Toronto be -2 C on June 12?", "3 to -2", "2.5 C"])
def test_unparseable_text_does_not_invent_a_numeric_band(label):
    assert label_bin_metadata(label, "C") == {
        "bin_kind": None, "bin_value": None, "bin_value_hi": None, "unit": "C",
    }
    assert band_key({"range_label": label}) == (None, None, None)


def test_negative_token_rows_and_settlement_outcomes():
    event = {
        "slug": "highest-temperature-in-toronto-on-june-12-2026",
        "markets": [{
            "id": "fixture", "conditionId": "fixture-condition",
            "groupItemTitle": "-2°C or below", "outcomes": ["Yes", "No"],
            "clobTokenIds": ["fixture-yes", "fixture-no"], "outcomePrices": ["0.2", "0.8"],
        }],
    }
    rows = token_rows_from_event(event, captured_at=datetime(2026, 6, 12, tzinfo=timezone.utc))
    assert len(rows) == 2
    for row in rows:
        assert band_key(row) == ("lte", -2, -2)
        assert band_outcome(row, -3) == 1
        assert band_outcome(row, -1) == 0
        assert row["unit"] == "C"
