"""Probability calibration helpers for feature-model class distributions."""

from __future__ import annotations

import math


DEFAULT_TEMPERATURE_GRID = (0.70, 0.85, 1.00, 1.20, 1.50, 2.00)
DEFAULT_BLEND_WEIGHT_GRID = (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.97)


def normalize_distribution(probabilities):
    cleaned = {
        int(bucket): max(0.0, float(probability))
        for bucket, probability in (probabilities or {}).items()
        if probability is not None
    }
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {bucket: probability / total for bucket, probability in sorted(cleaned.items())}


def temperature_scale_distribution(probabilities, temperature=1.0):
    """Apply multiclass temperature scaling to a probability dictionary."""
    distribution = normalize_distribution(probabilities)
    if not distribution:
        return {}
    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = 1.0
    temperature = max(0.05, temperature)
    if abs(temperature - 1.0) <= 1e-12:
        return distribution
    scaled = {
        bucket: (probability ** (1.0 / temperature)) if probability > 0 else 0.0
        for bucket, probability in distribution.items()
    }
    return normalize_distribution(scaled)


def blend_distribution(base, model, weight):
    base = normalize_distribution(base)
    model = normalize_distribution(model)
    if not base:
        return model
    if not model:
        return base
    weight = max(0.0, min(1.0, float(weight)))
    keys = set(base) | set(model)
    return normalize_distribution({
        bucket: (1.0 - weight) * base.get(bucket, 0.0) + weight * model.get(bucket, 0.0)
        for bucket in keys
    })


def log_loss(probabilities, actual_bucket):
    probability = normalize_distribution(probabilities).get(int(actual_bucket), 0.0)
    probability = max(1e-15, min(1.0 - 1e-15, probability))
    return -math.log(probability)


def fit_temperature_blend_grid(
    folds,
    temperatures=DEFAULT_TEMPERATURE_GRID,
    blend_weights=DEFAULT_BLEND_WEIGHT_GRID,
):
    """Tune HGB temperature and climatology blend weight by validation log loss.

    ``folds`` is an iterable of ``(climatology_distribution,
    raw_model_distribution, actual_bucket)`` tuples. The grid contains the
    legacy serving behavior (temperature=1, blend=0.80), so the selected pair is
    never worse than that baseline on the validation rows used for tuning.
    """
    rows = list(folds or [])
    if not rows:
        return {"temperature": 1.0, "blend_weight": 0.80, "logloss": None}
    best = {"temperature": 1.0, "blend_weight": 0.80, "logloss": float("inf")}
    for temperature in temperatures:
        scaled_rows = [
            (base, temperature_scale_distribution(raw, temperature), actual)
            for base, raw, actual in rows
        ]
        for weight in blend_weights:
            loss = sum(
                log_loss(blend_distribution(base, scaled, weight), actual)
                for base, scaled, actual in scaled_rows
            ) / len(scaled_rows)
            if loss < best["logloss"] - 1e-12:
                best = {
                    "temperature": float(temperature),
                    "blend_weight": float(weight),
                    "logloss": float(loss),
                }
    return best
