"""Per-market feature selection policy for model training only."""

from __future__ import annotations

from collections.abc import Sequence

from weather.market.market_registry import MarketSpec


TRAINING_FEATURE_POLICY_ID = "native_station_pressure_train_serve_v1"
F_MARKET_UNSERVABLE_TRAINING_FEATURES = (
    "pressure",
    "pressure_trend_3h",
)


def training_feature_exclusions(market_spec: MarketSpec) -> tuple[str, ...]:
    """Return features that the registry market cannot know at serve time."""

    unit = str(getattr(market_spec, "unit", "") or "").upper()
    if unit == "F":
        return F_MARKET_UNSERVABLE_TRAINING_FEATURES
    if unit == "C":
        return ()
    raise ValueError(
        f"unsupported registry market unit for training policy: {unit!r}"
    )


def training_feature_names(
    feature_names: Sequence[str],
    *,
    market_spec: MarketSpec,
) -> list[str]:
    """Preserve feature order while applying the registry-unit policy."""

    excluded = set(training_feature_exclusions(market_spec))
    return [str(name) for name in feature_names if str(name) not in excluded]


__all__ = [
    "F_MARKET_UNSERVABLE_TRAINING_FEATURES",
    "TRAINING_FEATURE_POLICY_ID",
    "training_feature_exclusions",
    "training_feature_names",
]
