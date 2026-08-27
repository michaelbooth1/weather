"""Mode-specific budget and policy limits for market-making runs."""

from __future__ import annotations

import math

from weather.market.market_making_run_constants import (
    DEFAULT_QUOTE_TTL_SECONDS,
    MAX_OPERATOR_PILOT_BUDGET_USDC,
)
from weather.market.mm_policy import DEFAULT_POLICY_CONFIG


MARKET_HARVEST_QUOTE_TTL_SECONDS = 600.0


def build_run_policy_config(mode, budget_usdc, selected_market_count, overrides=None):
    """Build run policy without allowing live-pilot callers to raise risk ceilings."""
    budget = float(budget_usdc)
    if mode == "live-pilot" and (
        not math.isfinite(budget)
        or not 0 < budget <= MAX_OPERATOR_PILOT_BUDGET_USDC
    ):
        raise ValueError(
            "live-pilot budget must be finite, greater than zero, and no more than "
            f"{MAX_OPERATOR_PILOT_BUDGET_USDC:.2f} USDC"
        )
    if mode == "live-pilot" and selected_market_count != 1:
        raise ValueError("live-pilot is restricted to exactly one market")

    config = {**DEFAULT_POLICY_CONFIG, **(overrides or {})}
    if mode != "live-pilot":
        config["max_daily_loss"] = min(
            float(config.get("max_daily_loss", budget)),
            budget,
        )
        config.setdefault("quote_ttl_seconds", DEFAULT_QUOTE_TTL_SECONDS)
        return config

    live_limits = {
        "max_daily_loss": (
            config.get("max_daily_loss", budget),
            min(budget, float(DEFAULT_POLICY_CONFIG["max_daily_loss"])),
            True,
        ),
        "max_event_notional": (
            config["max_event_notional"],
            float(DEFAULT_POLICY_CONFIG["max_event_notional"]),
            True,
        ),
        "max_band_notional": (
            config["max_band_notional"],
            float(DEFAULT_POLICY_CONFIG["max_band_notional"]),
            True,
        ),
        "quote_ttl_seconds": (
            config.get("quote_ttl_seconds", DEFAULT_QUOTE_TTL_SECONDS),
            float(DEFAULT_QUOTE_TTL_SECONDS),
            False,
        ),
    }
    for key, (requested_value, ceiling, allow_zero) in live_limits.items():
        requested = float(requested_value)
        if not math.isfinite(requested) or requested < 0 or (not allow_zero and requested == 0):
            qualifier = "non-negative" if allow_zero else "greater than zero"
            raise ValueError(f"live-pilot {key} must be finite and {qualifier}")
        config[key] = min(requested, ceiling)
    return config


def build_market_harvest_policy_config(budget_usdc, config):
    """Clamp the paper harvest profile to the existing conservative ceilings."""
    budget = float(budget_usdc)
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("market_harvest budget must be finite and greater than zero")
    config = dict(config or {})
    ceilings = {
        "quote_size": float(DEFAULT_POLICY_CONFIG["quote_size"]),
        "max_event_notional": float(DEFAULT_POLICY_CONFIG["max_event_notional"]),
        "max_band_notional": 10.0,
        "max_daily_loss": min(budget, float(DEFAULT_POLICY_CONFIG["max_daily_loss"])),
        "quote_ttl_seconds": MARKET_HARVEST_QUOTE_TTL_SECONDS,
    }
    for key, ceiling in ceilings.items():
        default = (
            DEFAULT_QUOTE_TTL_SECONDS
            if key == "quote_ttl_seconds"
            else ceiling
        )
        requested = float(config.get(key, default))
        allow_zero = key != "quote_ttl_seconds"
        if (
            not math.isfinite(requested)
            or requested < 0
            or (not allow_zero and requested == 0)
        ):
            qualifier = "non-negative" if allow_zero else "greater than zero"
            raise ValueError(f"market_harvest {key} must be finite and {qualifier}")
        config[key] = min(requested, ceiling)
    config["harvest_half_spread"] = 0.01
    config["max_harvest_spread"] = 0.08
    return config
