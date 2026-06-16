"""Canonical continuous-density helpers for unified temperature models.

Item 35 moves the model target away from city-native integer buckets. These
helpers keep the serving contract explicit: learn on a fine canonical
Fahrenheit grid, then integrate that density over each market's native rounded
bucket/band interval only at serve time.
"""
from __future__ import annotations

import math
from collections.abc import Mapping


DEFAULT_GRID_LOW_F = -40.0
DEFAULT_GRID_HIGH_F = 130.0
DEFAULT_GRID_STEP_F = 0.1
CANONICAL_DENSITY_KIND = "continuous_density_f"


def c_to_f(value):
    return float(value) * 9.0 / 5.0 + 32.0


def f_to_c(value):
    return (float(value) - 32.0) * 5.0 / 9.0


def native_to_f(value, unit):
    return c_to_f(value) if str(unit).upper() == "C" else float(value)


def f_to_native(value, unit):
    return f_to_c(value) if str(unit).upper() == "C" else float(value)


def canonical_grid_f(
    low_f=DEFAULT_GRID_LOW_F,
    high_f=DEFAULT_GRID_HIGH_F,
    step_f=DEFAULT_GRID_STEP_F,
):
    if step_f <= 0:
        raise ValueError("step_f must be positive")
    count = int(math.floor((float(high_f) - float(low_f)) / float(step_f) + 1e-9)) + 1
    return [round(float(low_f) + index * float(step_f), 6) for index in range(count)]


def normalize_density(density):
    cleaned = {}
    for key, value in (density or {}).items():
        if value is None:
            continue
        probability = float(value)
        if probability < 0:
            raise ValueError("density probabilities must be non-negative")
        cleaned[float(key)] = probability
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {grid_value: probability / total for grid_value, probability in cleaned.items()}


def continuous_density_payload(density_f, **metadata):
    """Return the explicit serving/replay payload for canonical-F densities."""
    payload = {
        "kind": CANONICAL_DENSITY_KIND,
        "density_f": normalize_density(density_f),
    }
    payload.update(metadata)
    return payload


def density_f_from_payload(distribution):
    """Extract canonical-F density weights from an explicit density payload.

    Native integer distributions are also mappings, so this intentionally only
    recognizes named payload keys. That keeps legacy ``{bucket: probability}``
    callers on the existing native bucket path.
    """
    if not isinstance(distribution, Mapping):
        return None
    for key in ("density_f", "canonical_density_f"):
        if key in distribution:
            return distribution.get(key) or {}
    if distribution.get("kind") == CANONICAL_DENSITY_KIND and "density" in distribution:
        return distribution.get("density") or {}
    return None


def is_continuous_density_payload(distribution):
    return density_f_from_payload(distribution) is not None


def bucket_interval_native(kind, value, value_hi=None):
    """Return the half-open native-unit interval for a rounded settlement band.

    A settlement bucket ``X`` represents continuous temperatures in
    ``[X - 0.5, X + 0.5)`` under round-half-up semantics. ``lte`` and ``gte``
    expand that interval to the relevant tail.
    """
    if value is None:
        return None, None
    kind = str(kind or "eq").lower()
    low = float(value) - 0.5
    high = float(value if value_hi is None else value_hi) + 0.5
    if kind == "lte":
        return None, high
    if kind == "gte":
        return low, None
    return low, high


def native_interval_to_f(low_native, high_native, unit):
    low_f = None if low_native is None else native_to_f(low_native, unit)
    high_f = None if high_native is None else native_to_f(high_native, unit)
    return low_f, high_f


def point_in_half_open_interval(value, low=None, high=None):
    value = float(value)
    if low is not None and value < float(low):
        return False
    if high is not None and value >= float(high):
        return False
    return True


def band_probability_from_density(density_f, unit, kind, value, value_hi=None):
    """Integrate canonical-F density over a native market band.

    ``density_f`` is a discrete approximation to a continuous density on a fine
    Fahrenheit grid. The function normalizes the incoming density before
    summing, so callers can pass raw weights or probabilities.
    """
    low_native, high_native = bucket_interval_native(kind, value, value_hi)
    low_f, high_f = native_interval_to_f(low_native, high_native, unit)
    density = normalize_density(density_f)
    return sum(
        probability
        for grid_value, probability in density.items()
        if point_in_half_open_interval(grid_value, low_f, high_f)
    )


def band_probability_from_distribution(distribution, spec, bin_data):
    density_f = density_f_from_payload(distribution)
    if density_f is None:
        return None
    unit = (
        (bin_data or {}).get("unit")
        or getattr(spec, "display_unit", getattr(spec, "unit", "F"))
    )
    return band_probability_from_density(
        density_f,
        unit,
        (bin_data or {}).get("kind") or (bin_data or {}).get("bin_kind") or "eq",
        (bin_data or {}).get("value", (bin_data or {}).get("bin_value")),
        value_hi=(bin_data or {}).get("value_hi", (bin_data or {}).get("bin_value_hi")),
    )


def discretize_density_to_market_bands(density_f, spec, bands):
    payload_density = density_f_from_payload(density_f)
    if payload_density is not None:
        density_f = payload_density
    rows = []
    unit = getattr(spec, "display_unit", getattr(spec, "unit", "F"))
    for band in bands or []:
        value = band.get("value")
        value_hi = band.get("value_hi", value)
        rows.append({
            "market_id": getattr(spec, "id", None),
            "unit": unit,
            "label": band.get("label"),
            "kind": band.get("kind") or "eq",
            "value": value,
            "value_hi": value_hi,
            "probability": band_probability_from_density(
                density_f,
                unit,
                band.get("kind") or "eq",
                value,
                value_hi=value_hi,
            ),
        })
    return rows
