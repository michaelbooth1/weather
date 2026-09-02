from __future__ import annotations

from unittest.mock import patch

import pytest

from weather.calibration import seasonal_challenger as subject


def test_range_upper_bound_is_recovered_without_reinterpreting_single_bands():
    assert subject._band_value_hi("eq", 82.0, "", "82-83°F") == 83.0
    assert subject._band_value_hi("eq", -2.0, "", "-2--1°C") == -1.0
    assert subject._band_value_hi("eq", 25.0, "", "25°C") == 25.0
    assert subject._band_value_hi("gte", 90.0, "", "90°F or higher") == 90.0


def test_feature_contract_excludes_market_outcome_and_settlement_inputs():
    names = subject._feature_names(subject.EXPECTED_FIELDS)
    forbidden = ("price", "outcome", "settlement", "market_yes", "market_no", "market_probability")
    assert not any(token in name for name in names for token in forbidden)
    assert names[: len(subject.EXPECTED_FIELDS)] == [
        subject.FIELD_TO_COLUMN[field] for field in subject.EXPECTED_FIELDS
    ]


def test_crossed_bootstrap_is_deterministic_and_reports_both_cluster_axes():
    records = [
        (target_date, market, value, 1.0)
        for target_date, value in (("2026-01-01", 1.0), ("2026-01-02", 3.0))
        for market in ("a", "b")
    ]
    first = subject._crossed_draws(records, draws=2000, seed=123)
    second = subject._crossed_draws(records, draws=2000, seed=123)
    assert first == second
    assert first["point"] == 2.0
    assert first["date_clusters"] == 2
    assert first["market_clusters"] == 2
    assert first["effective_cluster_cells"] == 4


def test_probability_pipeline_preserves_incumbent_zero_support_and_simplex():
    rows = [
        {"incumbent_probability": 0.0, "market_id": "a", "target_date": "2026-01-01", "cutoff_hour": 7},
        {"incumbent_probability": 0.4, "market_id": "a", "target_date": "2026-01-01", "cutoff_hour": 7},
        {"incumbent_probability": 0.6, "market_id": "a", "target_date": "2026-01-01", "cutoff_hour": 7},
    ]
    with (
        patch.object(subject, "predict_band_probabilities", return_value=[0.8, 0.1, 0.1]),
        patch.object(subject, "apply_band_postprocessing", side_effect=lambda probability, _row, config: probability),
    ):
        probabilities = subject._predict_group((object(), object(), []), rows)
    assert probabilities[0] == 0.0
    assert sum(probabilities) == pytest.approx(1.0, abs=1e-12)


def test_severe_tail_membership_is_frozen_from_recorded_incumbent_not_refit():
    group = {
        "snapshot_id": "s",
        "settlement_bucket": 2,
        "rows": [
            {"band_mid": 1.0, "outcome": 0, "incumbent_probability": 0.8, "market_probability": 0.1},
            {"band_mid": 2.0, "outcome": 1, "incumbent_probability": 0.2, "market_probability": 0.9},
        ],
    }
    predictions = {
        "primary_baseline": {"s": [0.1, 0.9]},
        "primary_challenger": {"s": [0.2, 0.8]},
        "sensitivity_baseline": {"s": [0.1, 0.9]},
        "sensitivity_challenger": {"s": [0.2, 0.8]},
    }
    values = subject._snapshot_values(group, predictions)
    assert values["severe_indexes"] == [0, 1]


def test_decision_rule_returns_inconclusive_when_centre_interval_crosses_zero():
    c_pre = {
        "paired_endpoints": {
            "primary_centre_sse_improvement": {"point": -1.0, "lower_95": -4.0, "upper_95": 1.0},
            "primary_brier_challenger_minus_baseline": {"point": -0.001, "lower_95": -0.003, "upper_95": 0.001},
            "sensitivity_centre_sse_improvement": {"point": -0.5},
        },
        "maximum_one_market_contribution": None,
        "probability_mass_valid": True,
        "captured_input_parity": True,
    }
    assert subject._decision(c_pre)["verdict"] == "INCONCLUSIVE_UNDERPOWERED"
