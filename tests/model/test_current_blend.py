from unittest.mock import patch

import pytest

from weather.calibration.pooled_candidate_replay import (
    apply_current_blend_guardrail,
    attach_band_candidate_probabilities,
)
from weather.collection.live_variant_predictions import (
    _apply_current_blend,
    _band_binary_probabilities,
)
from weather.market.market_registry import REGISTRY
from weather.model.current_blend import (
    resolve_current_blend_alpha,
    source_freshness_state_from_diagnostics,
)


CANDIDATE = 0.80
INCUMBENT = 0.20


def _expected(alpha):
    return (alpha * CANDIDATE) + ((1.0 - alpha) * INCUMBENT)


def _live_and_replay(*, feature_vector, config, source_diagnostics=None):
    band = {
        "bin_kind": "eq",
        "bin_value_c": 22,
        "bin_value_hi_c": 22,
        "model_probability": INCUMBENT,
    }
    live = _apply_current_blend(
        {"eq_22c": CANDIDATE},
        [band],
        {"current_blend_enabled": True, **config},
        feature_vector.get("market_id"),
        feature_vector=feature_vector,
        source_diagnostics=source_diagnostics,
    )["eq_22c"]

    # This is the same band context retained by attach_band_candidate_probabilities
    # until the replay blend has run.
    replay_row = {
        **feature_vector,
        "candidate_p": CANDIDATE,
        "replayed_p": INCUMBENT,
        "_band_postprocess_row": {
            **feature_vector,
            "band_mid_minus_high_so_far": (
                22.0 - float(feature_vector["high_so_far"])
                if feature_vector.get("high_so_far") is not None
                else None
            ),
            "band_mid_minus_forecast": (
                22.0 - float(feature_vector["forecast_high"])
                if feature_vector.get("forecast_high") is not None
                else None
            ),
        },
    }
    if "source_freshness_state" not in replay_row:
        replay_row["source_freshness_state"] = source_freshness_state_from_diagnostics(
            source_diagnostics
        )
    apply_current_blend_guardrail([replay_row], config)
    return live, replay_row["candidate_p"]


@pytest.mark.parametrize(
    ("feature_vector", "source_diagnostics", "config", "expected_alpha"),
    [
        pytest.param(
            {"market_id": "chicago", "forecast_high": 22, "high_so_far": 22},
            [{"source": "open_meteo", "status": "fresh"}],
            {"current_blend_default_alpha": 0.75},
            0.75,
            id="default-alpha",
        ),
        pytest.param(
            {"market_id": "denver", "forecast_high": 22, "high_so_far": 22},
            [{"source": "open_meteo", "status": "fresh"}],
            {
                "current_blend_default_alpha": 0.75,
                "current_blend_market_alpha": {"denver": 0.25},
            },
            0.25,
            id="market-overrides-default",
        ),
        pytest.param(
            {"market_id": "denver", "forecast_high": 22, "high_so_far": 22},
            [{"source": "metar", "status": "stale_cache"}],
            {
                "current_blend_default_alpha": 1.0,
                "current_blend_market_alpha": {"denver": 0.80},
                "current_blend_source_freshness_default_alpha": 0.0,
                "current_blend_source_freshness_alpha": {"stale:metar": 0.50},
            },
            0.50,
            id="source-state-caps-market",
        ),
        pytest.param(
            {
                "market_id": "austin",
                "forecast_high": 20,
                "high_so_far": 22,
                "cutoff_hour": 12,
            },
            [{"source": "open_meteo", "status": "fresh"}],
            {
                "current_blend_default_alpha": 0.10,
                "current_blend_context_alpha": [
                    {"forecast_bucket_pressure": "warm_side", "alpha": 0.35},
                ],
            },
            0.35,
            id="derived-context-overrides-base",
        ),
        pytest.param(
            {
                "market_id": "austin",
                "forecast_high": 20,
                "high_so_far": 19,
                "cutoff_hour": 12,
            },
            [{"source": "open_meteo", "status": "fresh"}],
            {
                "current_blend_default_alpha": 0.90,
                "current_blend_context_alpha": [
                    {"forecast_bucket_pressure": "warm_side", "alpha": 0.10},
                    {"band_mid_minus_high_so_far_min": 2.0, "alpha": 0.65},
                ],
            },
            0.65,
            id="last-of-multiple-matches-wins",
        ),
        pytest.param(
            {
                "market_id": "austin",
                "forecast_high": None,
                "high_so_far": None,
            },
            None,
            {
                "current_blend_default_alpha": 0.60,
                "current_blend_source_freshness_default_alpha": 0.0,
                "current_blend_source_freshness_alpha": {"all_fresh": 1.0},
                "current_blend_context_alpha": [
                    {"forecast_bucket_pressure": "warm_side", "alpha": 1.0},
                    {"band_mid_minus_high_so_far_min": 2.0, "alpha": 1.0},
                ],
            },
            0.0,
            id="missing-fields-fail-closed-identically",
        ),
        pytest.param(
            {
                "market_id": "austin",
                "forecast_high": 22,
                "high_so_far": 22,
                "candidate_cutoff_regime": "late",
            },
            [{"source": "open_meteo", "status": "fresh"}],
            {
                "current_blend_default_alpha": 0.0,
                "current_blend_context_alpha": [
                    {"cutoff_regime": ["midday", "late"], "alpha": 1.0},
                ],
            },
            1.0,
            id="candidate-cutoff-regime-alias",
        ),
    ],
)
def test_live_and_replay_current_blend_policy_is_identical(
    feature_vector,
    source_diagnostics,
    config,
    expected_alpha,
):
    live, replay = _live_and_replay(
        feature_vector=feature_vector,
        source_diagnostics=source_diagnostics,
        config=config,
    )
    assert live == pytest.approx(_expected(expected_alpha))
    assert replay == pytest.approx(live)


def test_resolver_clamps_and_uses_last_matching_rule_deterministically():
    row = {"market_id": "nyc", "cutoff_hour": 12}
    config = {
        "current_blend_default_alpha": -10,
        "current_blend_context_alpha": [
            {"cutoff_regime": "midday", "alpha": 0.25},
            {"cutoff_hour_min": 10, "alpha": 4.0},
        ],
    }
    assert resolve_current_blend_alpha(row, config) == 1.0


def test_source_diagnostic_group_matches_replay_taxonomy_and_missingness():
    assert source_freshness_state_from_diagnostics(None) == "missing_source_status"
    assert source_freshness_state_from_diagnostics([]) == "missing_source_status"
    assert source_freshness_state_from_diagnostics({"mystery": {}}) == "unknown:mystery"
    assert source_freshness_state_from_diagnostics(
        [
            {"source": "wu", "status": "failed"},
            {"source": "metar", "status": "stale_cache"},
            {"source": "open_meteo", "status": "fresh"},
        ]
    ) == "failed:wu;stale:metar"


@pytest.mark.parametrize("market_id", sorted(REGISTRY))
def test_all_registered_markets_have_live_replay_market_alpha_parity(market_id):
    markets = sorted(REGISTRY)
    alpha = (markets.index(market_id) + 1) / (len(markets) + 1)
    live, replay = _live_and_replay(
        feature_vector={
            "market_id": market_id,
            "forecast_high": 22,
            "high_so_far": 22,
        },
        source_diagnostics=[{"source": "open_meteo", "status": "fresh"}],
        config={
            "current_blend_default_alpha": 0.99,
            "current_blend_market_alpha": {market_id: alpha},
        },
    )
    assert live == pytest.approx(_expected(alpha))
    assert replay == pytest.approx(live)


def test_replay_attachment_retains_band_context_until_shared_blend_runs():
    replay_results = {
        "all_rows": [
            {
                "market_id": "austin",
                "snapshot_id": "s1",
                "range_label": "22 F",
                "bin_type": "eq",
                "bin_value_c": 22,
                "replayed_p": INCUMBENT,
                "outcome": 1,
            }
        ]
    }
    feature_rows = {
        ("austin", "s1"): {
            "market_id": "austin",
            "cutoff_hour": 12,
            "forecast_high": 20.0,
            "high_so_far": 19.0,
        }
    }
    artifact = {
        "models": {"12": {"feature_names": ["placeholder"]}},
        "postprocess": {
            "partition_normalization_enabled": False,
            "current_blend_enabled": True,
            "current_blend_default_alpha": 1.0,
            "current_blend_context_alpha": [
                {"band_mid_minus_high_so_far_min": 2.0, "alpha": 0.35},
            ],
        },
    }
    with patch(
        "weather.calibration.pooled_candidate_replay.predict_band_rows_for_bundle",
        return_value=[CANDIDATE],
    ):
        rows, coverage = attach_band_candidate_probabilities(
            replay_results,
            feature_rows,
            artifact,
            "F",
            source_freshness={("austin", "s1"): "all_fresh"},
        )
    assert coverage["candidate_rows"] == 1
    assert rows[0]["candidate_p"] == pytest.approx(_expected(0.35))
    assert "_band_postprocess_row" not in rows[0]


def test_contextual_band_blend_restores_simplex_with_live_replay_parity():
    band_rows = [
        {
            "snapshot_id": "s1",
            "range_label": "19 F or below",
            "bin_kind": "lte",
            "bin_type": "lte",
            "bin_value_c": 19,
            "bin_value_hi_c": 19,
            "model_probability": 0.20,
        },
        {
            "snapshot_id": "s1",
            "range_label": "20-21 F",
            "bin_kind": "eq",
            "bin_type": "eq",
            "bin_value_c": 20,
            "bin_value_hi_c": 21,
            "model_probability": 0.30,
        },
        {
            "snapshot_id": "s1",
            "range_label": "22 F or higher",
            "bin_kind": "gte",
            "bin_type": "gte",
            "bin_value_c": 22,
            "bin_value_hi_c": 22,
            "model_probability": 0.50,
        },
    ]
    feature_vector = {
        "market_id": "austin",
        "cutoff_hour": 12,
        "forecast_high": 20.0,
        "high_so_far": 19.0,
    }
    artifact = {
        "models": {"12": {"feature_names": ["placeholder"]}},
        "postprocess": {
            "partition_normalization_enabled": True,
            "partition_normalization_gamma": 1.0,
            "current_blend_enabled": True,
            "current_blend_default_alpha": 1.0,
            "current_blend_context_alpha": [
                {"forecast_bucket_pressure": "warm_side", "alpha": 0.35},
            ],
        },
    }
    raw_candidate = [0.60, 0.30, 0.10]
    replay_results = {
        "all_rows": [
            {
                **band,
                "market_id": "austin",
                "replayed_p": band["model_probability"],
                "outcome": int(index == 1),
            }
            for index, band in enumerate(band_rows)
        ]
    }

    with (
        patch(
            "weather.calibration.pooled_candidate_replay.predict_band_rows_for_bundle",
            return_value=raw_candidate,
        ),
        patch(
            "weather.model.variant_prediction_runtime.predict_band_rows_for_bundle",
            return_value=raw_candidate,
        ),
    ):
        replay_rows, coverage = attach_band_candidate_probabilities(
            replay_results,
            {("austin", "s1"): feature_vector},
            artifact,
            "F",
            source_freshness={("austin", "s1"): "all_fresh"},
        )
        live = _band_binary_probabilities(
            artifact,
            feature_vector,
            band_rows,
            {"market_id": "austin", "model": {}},
        )

    replay = [row["candidate_p"] for row in replay_rows]
    raw_blended = [0.60, 0.30, (0.35 * 0.10) + (0.65 * 0.50)]
    expected = [value / sum(raw_blended) for value in raw_blended]
    assert coverage["candidate_rows"] == 3
    assert sum(replay) == pytest.approx(1.0, abs=1e-12)
    assert sum(live.values()) == pytest.approx(1.0, abs=1e-12)
    assert replay == pytest.approx(expected)
    assert list(live.values()) == pytest.approx(replay)
