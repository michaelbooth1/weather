import math

import pytest

from weather.market.market_making_live_pilot import (
    MARKET_HARVEST_QUOTE_TTL_SECONDS,
    build_market_harvest_policy_config,
    build_run_policy_config,
)
from weather.market.mm_policy import DEFAULT_POLICY_CONFIG


def test_live_pilot_requires_finite_bounded_budget_and_exactly_one_market():
    for budget in (0, -1, math.inf, math.nan, 100.01):
        with pytest.raises(ValueError, match="live-pilot budget"):
            build_run_policy_config("live-pilot", budget, 1)

    for market_count in (0, 2):
        with pytest.raises(ValueError, match="exactly one market"):
            build_run_policy_config("live-pilot", 100, market_count)


def test_live_pilot_clamps_every_operator_limit_without_raising_defaults():
    config = build_run_policy_config(
        "live-pilot",
        100,
        1,
        overrides={
            "max_daily_loss": 90,
            "max_event_notional": 90,
            "max_band_notional": 90,
            "quote_ttl_seconds": 900,
        },
    )

    assert config["max_daily_loss"] == DEFAULT_POLICY_CONFIG["max_daily_loss"]
    assert config["max_event_notional"] == DEFAULT_POLICY_CONFIG["max_event_notional"]
    assert config["max_band_notional"] == DEFAULT_POLICY_CONFIG["max_band_notional"]
    assert config["quote_ttl_seconds"] == 120.0


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("max_daily_loss", -1),
        ("max_event_notional", math.nan),
        ("max_band_notional", math.inf),
        ("quote_ttl_seconds", 0),
    ],
)
def test_live_pilot_rejects_invalid_policy_limits(key, value):
    with pytest.raises(ValueError, match=key):
        build_run_policy_config("live-pilot", 25, 1, overrides={key: value})


def test_non_live_policy_behavior_still_clamps_daily_loss_to_budget():
    config = build_run_policy_config(
        "shadow",
        7,
        3,
        overrides={"max_daily_loss": 9, "quote_ttl_seconds": 30},
    )

    assert config["max_daily_loss"] == 7
    assert config["quote_ttl_seconds"] == 30


def test_market_harvest_defaults_to_capture_ttl_and_allows_portable_ceiling():
    defaulted = build_market_harvest_policy_config(25, {})
    portable = build_market_harvest_policy_config(
        25,
        {"quote_ttl_seconds": MARKET_HARVEST_QUOTE_TTL_SECONDS},
    )
    clamped = build_market_harvest_policy_config(
        25,
        {"quote_ttl_seconds": MARKET_HARVEST_QUOTE_TTL_SECONDS + 1},
    )

    assert defaulted["quote_ttl_seconds"] == 120.0
    assert portable["quote_ttl_seconds"] == MARKET_HARVEST_QUOTE_TTL_SECONDS
    assert clamped["quote_ttl_seconds"] == MARKET_HARVEST_QUOTE_TTL_SECONDS
    with pytest.raises(ValueError, match="quote_ttl_seconds"):
        build_market_harvest_policy_config(25, {"quote_ttl_seconds": 0})
