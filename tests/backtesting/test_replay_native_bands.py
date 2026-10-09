"""Native band interpretation agrees from serving through settlement and replay."""

import csv
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from weather.backtesting.replay import band_bin_data, band_model_probability, band_value_hi
from weather.backtesting.settlement_io import resolve_outcome, row_band_value_hi
from weather.model.continuous_density import continuous_density_payload
from weather.model.model_base import ModelUtilsMixin
from weather.model.model_presentation import PresentationMixin
from weather.units import native_to_f, temperature_band_key


class _BandModel(PresentationMixin, ModelUtilsMixin):
    """Real projection methods without source collection or artifact loading."""

    def __init__(self, unit):
        self.spec = SimpleNamespace(display_unit=unit)


def _persist(row, encoding):
    if encoding == "json":
        return json.loads(json.dumps(row))
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    stream.seek(0)
    return next(csv.DictReader(stream))


@pytest.mark.parametrize("unit", ["C", "F"])
@pytest.mark.parametrize(
    "labels, endpoints, distribution",
    [
        (
            ["-6 {unit} or below", "-5--4 {unit}", "-3 {unit} or higher"],
            [("lte", -6, -6), ("eq", -5, -4), ("gte", -3, -3)],
            {-7: 0.1, -6: 0.1, -5: 0.2, -4: 0.3, -3: 0.3},
        ),
        (
            ["-2 {unit} or below", "-1-0 {unit}", "1 {unit} or higher"],
            [("lte", -2, -2), ("eq", -1, 0), ("gte", 1, 1)],
            {-3: 0.1, -2: 0.1, -1: 0.2, 0: 0.3, 1: 0.3},
        ),
        (
            ["-1 {unit} or below", "0 {unit}", "1 {unit} or higher"],
            [("lte", -1, -1), ("eq", 0, 0), ("gte", 1, 1)],
            {-2: 0.1, -1: 0.1, 0: 0.5, 1: 0.3},
        ),
        (
            ["74 {unit} or below", "75-76 {unit}", "77 {unit} or higher"],
            [("lte", 74, 74), ("eq", 75, 76), ("gte", 77, 77)],
            {73: 0.1, 74: 0.1, 75: 0.2, 76: 0.3, 77: 0.3},
        ),
    ],
    ids=["negative", "crossing-zero", "exact-zero", "positive-control"],
)
@pytest.mark.parametrize("encoding", ["json", "csv"])
@pytest.mark.parametrize("explicit_upper", [False, True], ids=["legacy-upper", "typed-upper"])
@pytest.mark.parametrize("density", [False, True], ids=["native-buckets", "continuous-density"])
def test_native_bands_agree_across_serving_tape_settlement_and_replay(
    unit, labels, endpoints, distribution, encoding, explicit_upper, density
):
    model = _BandModel(unit)
    event = {
        "markets": [
            {
                "groupItemTitle": label.format(unit=unit),
                "outcomes": '["Yes","No"]',
                "outcomePrices": '["0.5","0.5"]',
            }
            for label in labels
        ]
    }
    bins = model.market_bins(event)
    assert [(band["kind"], band["value"], band["value_hi"]) for band in bins] == endpoints
    payload = (
        continuous_density_payload(
            {native_to_f(bucket, unit): probability for bucket, probability in distribution.items()}
        )
        if density
        else distribution
    )
    rows = []
    probabilities = []
    for band, expected_probability in zip(bins, (0.2, 0.5, 0.3)):
        row = {
            "bin_kind": band["kind"],
            "bin_value_c": band["value"],
            "range_label": band["label"],
            "market_yes": band["market_yes"],
            "market_no": band["market_no"],
        }
        if explicit_upper:
            row["bin_value_hi_c"] = band["value_hi"]
        row = _persist(row, encoding)
        rows.append(row)
        replay_bin = band_bin_data(row)
        assert (replay_bin["kind"], replay_bin["value"], replay_bin["value_hi"]) == (
            band["kind"], band["value"], band["value_hi"]
        )
        assert temperature_band_key(row) == (band["kind"], band["value"], band["value_hi"])
        assert row_band_value_hi(row) == band["value_hi"]
        assert model.bin_probability(payload, band) == pytest.approx(expected_probability)
        probability = band_model_probability(model, payload, row)
        assert probability == pytest.approx(expected_probability)
        probabilities.append(probability)
    assert sum(probabilities) == pytest.approx(1.0)

    # Every supported realized bucket has exactly one winner. Its probability
    # equals the mass of all native buckets assigned to that same band.
    for bucket in distribution:
        winners = [
            resolve_outcome(
                row["bin_kind"], row["bin_value_c"], bucket, value_hi=row_band_value_hi(row)
            )
            for row in rows
        ]
        assert sum(winners) == 1
        winner = winners.index(1)
        expected = sum(
            weight
            for value, weight in distribution.items()
            if resolve_outcome(
                rows[winner]["bin_kind"],
                rows[winner]["bin_value_c"],
                value,
                value_hi=row_band_value_hi(rows[winner]),
            )
        )
        assert probabilities[winner] == pytest.approx(expected)


@pytest.mark.parametrize("value_field", ["bin_value", "bin_value_c"])
@pytest.mark.parametrize("upper_field", ["bin_value_hi", "bin_value_hi_c"])
def test_explicit_zero_upper_endpoint_survives_legacy_single_value_label(value_field, upper_field):
    band = {"bin_kind": "eq", value_field: -1, upper_field: 0, "range_label": "-1 C"}
    assert band_value_hi(band) == 0
    assert band_model_probability(_BandModel("C"), {-1: 0.4, 0: 0.6}, band) == pytest.approx(1.0)


@pytest.mark.parametrize("value_field", ["bin_value", "bin_value_c"])
def test_numeric_zero_lower_endpoint_is_not_missing(value_field):
    band = {"bin_kind": "eq", value_field: 0, "range_label": "0 C"}
    assert band_bin_data(band)["value"] == 0
    assert band_value_hi(band) == 0
    assert band_model_probability(_BandModel("C"), {0: 0.7, 1: 0.3}, band) == pytest.approx(0.7)


@pytest.mark.parametrize("missing_upper", [None, "", float("nan"), "nan"])
def test_legacy_missing_upper_recovers_signed_endpoint_without_mutating_tape(missing_upper):
    band = {
        "bin_kind": "eq",
        "bin_value_c": -5,
        "bin_value_hi_c": missing_upper,
        "range_label": "-5--4 F",
    }
    assert band_value_hi(band) == -4
    assert band_model_probability(_BandModel("F"), {-5: 0.2, -4: 0.8}, band) == pytest.approx(1.0)
    assert band["bin_value_hi_c"] is missing_upper


@pytest.mark.parametrize(
    "label, expected",
    [
        ("-5 C or below", ("lte", -5, -5)),
        ("0 F or higher", ("gte", 0, 0)),
        ("\u22125\u2013\u22124\u00b0C", ("eq", -5, -4)),
    ],
)
def test_label_only_legacy_band_recovers_kind_and_signed_endpoints(label, expected):
    band = band_bin_data({"range_label": label})
    assert (band["kind"], band["value"], band["value_hi"]) == expected


@pytest.mark.parametrize(
    "band",
    [
        {"bin_kind": "eq", "bin_value_c": 0, "range_label": "unknown 0"},
        {"bin_kind": "eq", "bin_value_c": -5, "range_label": "-5--6 C"},
        {"bin_kind": "gte", "bin_value_c": -5, "range_label": "-5 C or below"},
        {"bin_kind": "eq", "bin_value_c": -5, "bin_value_hi_c": -3, "range_label": "-5--4 C"},
        {"bin_kind": "eq", "bin_value_c": 0, "bin_value_hi_c": "bad", "range_label": "0 C"},
        {"bin_kind": "eq", "bin_value_c": "nan", "range_label": "0 C"},
        {"bin_kind": "eq", "bin_value_c": True, "range_label": "1 C"},
        {"bin_kind": "eq", "bin_value_c": 0.5},
    ],
)
def test_invalid_band_evidence_cannot_reach_probability_projection(band):
    model = Mock()
    assert band_bin_data(band)["value"] is None
    assert band_value_hi(band) is None
    assert band_model_probability(model, {0: 1.0}, band) is None
    model.bin_probability.assert_not_called()
