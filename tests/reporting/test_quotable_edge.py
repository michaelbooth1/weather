from __future__ import annotations

import pandas as pd

from weather.reporting.research.quotable_edge import (
    HYPOTHESES,
    Hypothesis,
    break_even_grid,
    crossed_edge_draws,
    holm_adjust,
    membership,
)
from weather.schema_registry import schema_version


def _thresholds():
    return {
        "cutpoints": {
            "model_entropy": [0.25, 0.5, 0.75],
            "market_entropy": [0.25, 0.5, 0.75],
            "entropy_gap": [-0.1, 0.0, 0.1],
        }
    }


def test_preregistered_family_is_fixed_at_117_unique_cells():
    assert len(HYPOTHESES) == 117
    assert len({item.key for item in HYPOTHESES}) == 117
    assert sum(item.axis == "hour" for item in HYPOTHESES) == 14
    assert sum(item.axis == "market" for item in HYPOTHESES) == 12
    assert sum(item.axis == "book_spread" for item in HYPOTHESES) == 5


def test_receipt_schemas_are_registered():
    assert schema_version("quotable_edge_predictor_thresholds") == "quotable_edge_predictor_thresholds_v1"
    assert schema_version("quotable_edge_predictor_manifest") == "quotable_edge_predictor_manifest_v1"
    assert schema_version("quotable_edge_analysis") == "quotable_edge_analysis_v1"


def test_membership_uses_declared_boundaries():
    frame = pd.DataFrame(
        {
            "effective_cutoff_hour": [9, 18, 18],
            "market_id": ["toronto", "atlanta", "atlanta"],
            "stratum": ["B", "C", "C"],
            "forecast_distance_bands": [0.5, 3.0, None],
            "model_entropy": [0.25, 0.6, 0.9],
            "market_entropy": [0.2, 0.6, 0.9],
            "entropy_gap": [0.05, 0.0, 0.2],
            "forecast_disagreement_c_eq": [0.5, 1.5, None],
            "forecast_source_count": [1, 3, 0],
            "market_probability": [0.02, 0.50, 0.98],
            "repair_probability": [0.01, 0.65, 0.70],
            "book_spread": [0.002, 0.045, None],
            "liquidity": [24.0, 100.0, None],
            "volume": [9_999.0, 65_000.0, None],
        }
    )
    assert membership(frame, _thresholds(), Hypothesis("forecast_distance", "-0.5_to_0.5")).tolist() == [True, False, False]
    assert membership(frame, _thresholds(), Hypothesis("market_probability", "0.02_to_0.10")).tolist() == [True, False, False]
    assert membership(frame, _thresholds(), Hypothesis("hour_x_probability_gap", "lock_in_18_20|model_higher_10pp")).tolist() == [False, True, False]
    assert membership(frame, _thresholds(), Hypothesis("book_spread", "missing_or_invalid")).tolist() == [False, False, True]
    assert membership(frame, _thresholds(), Hypothesis("volume", "ge_65000")).tolist() == [False, True, False]


def test_crossed_draws_preserve_constant_positive_edge():
    rows = []
    for target_date in ("2026-06-01", "2026-06-02", "2026-06-03"):
        for market_id in ("a", "b"):
            rows.append(
                {
                    "target_date": target_date,
                    "market_id": market_id,
                    "edge_row": 0.02,
                }
            )
    draws = crossed_edge_draws(pd.DataFrame(rows), replicates=100, seed=7)
    assert len(draws) == 100
    assert set(draws.round(12)) == {0.02}


def test_crossed_draws_redraw_empty_sparse_product_samples():
    frame = pd.DataFrame(
        [
            {"target_date": "2026-06-01", "market_id": "a", "edge_row": 0.02},
            {"target_date": "2026-06-02", "market_id": "b", "edge_row": 0.02},
        ]
    )
    draws = crossed_edge_draws(frame, replicates=250, seed=11)
    assert len(draws) == 250
    assert set(draws.round(12)) == {0.02}


def test_holm_adjustment_is_monotone_in_rank():
    raw = [0.01, 0.03, 0.02, 0.50]
    adjusted = holm_adjust(raw)
    ordered = sorted(zip(raw, adjusted))
    assert [value for _, value in ordered] == sorted(value for _, value in ordered)
    assert adjusted[0] == 0.04
    assert adjusted[3] == 0.50


def test_break_even_grid_has_declared_size_and_fill_rate_cancels_without_reward():
    grid = break_even_grid()
    assert len(grid) == 21_000
    scoped = grid[
        (grid["adverse_move"] == 0.045)
        & (grid["informed_fraction"] == 0.50)
        & (grid["spread_capture"] == 0.005)
        & (grid["price"] == 0.50)
        & (grid["liquidity_reward_per_band_day"] == 0.0)
        & (grid["quote_size_per_side"] == 20)
    ]
    assert scoped["required_probability_edge"].nunique() == 1
    subsidized = grid[
        (grid["adverse_move"] == 0.045)
        & (grid["informed_fraction"] == 0.50)
        & (grid["spread_capture"] == 0.005)
        & (grid["price"] == 0.50)
        & (grid["fill_rate"] == 0.25)
        & (grid["quote_size_per_side"] == 20)
    ].sort_values("liquidity_reward_per_band_day")
    assert subsidized.iloc[-1]["required_probability_edge"] <= subsidized.iloc[0]["required_probability_edge"]
