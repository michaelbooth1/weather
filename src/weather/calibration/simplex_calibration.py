"""Deterministic, global temperature calibration for probability simplexes.

The calibrator in this module deliberately has one degree of freedom.  It is
fit from out-of-fold categorical probability partitions and is accepted only
when it improves both proper scores relative to the identity transform.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any


CALIBRATOR_SCHEMA_VERSION = "simplex_temperature_v1"
DEFAULT_TEMPERATURES: tuple[float, ...] = (
    0.50,
    0.67,
    0.80,
    0.90,
    1.00,
    1.10,
    1.25,
    1.50,
    2.00,
)
_SUM_TOLERANCE = 1e-9
_IMPROVEMENT_EPSILON = 1e-12


class SimplexCalibrationError(ValueError):
    """Raised when a probability row is not a complete categorical partition."""


def _ordered_items(
    probabilities: Mapping[str, float] | Sequence[float],
) -> tuple[list[str], list[float], bool]:
    if isinstance(probabilities, Mapping):
        keys = [str(key) for key in probabilities]
        if len(set(keys)) != len(keys):
            raise SimplexCalibrationError("probability keys must be unique strings")
        values = [float(value) for value in probabilities.values()]
        return keys, values, True
    if isinstance(probabilities, (str, bytes)):
        raise SimplexCalibrationError("probabilities must be a mapping or numeric sequence")
    values = [float(value) for value in probabilities]
    return [str(index) for index in range(len(values))], values, False


def validate_complete_partition(
    probabilities: Mapping[str, float] | Sequence[float],
    *,
    outcomes: Mapping[str, float] | Sequence[float] | None = None,
    tolerance: float = _SUM_TOLERANCE,
) -> None:
    """Validate a nonnegative, finite simplex and an optional one-hot outcome."""

    keys, values, is_mapping = _ordered_items(probabilities)
    if not values:
        raise SimplexCalibrationError("probability partition must not be empty")
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise SimplexCalibrationError("probabilities must be finite and nonnegative")
    if not math.isclose(math.fsum(values), 1.0, abs_tol=tolerance, rel_tol=0.0):
        raise SimplexCalibrationError("probabilities must sum to one")

    if outcomes is None:
        return
    outcome_keys, outcome_values, outcome_is_mapping = _ordered_items(outcomes)
    if is_mapping != outcome_is_mapping or outcome_keys != keys:
        raise SimplexCalibrationError("outcomes must have the same ordered partition as probabilities")
    if any(value not in (0.0, 1.0) for value in outcome_values):
        raise SimplexCalibrationError("outcomes must be one-hot")
    if math.fsum(outcome_values) != 1.0:
        raise SimplexCalibrationError("outcomes must contain exactly one winning category")


def simplex_power_transform(
    probabilities: Mapping[str, float] | Sequence[float],
    temperature: float,
) -> dict[str, float] | list[float]:
    """Apply ``p ** (1 / T)`` and renormalize, preserving every hard zero."""

    validate_complete_partition(probabilities)
    temperature = float(temperature)
    if not math.isfinite(temperature) or temperature <= 0.0:
        raise SimplexCalibrationError("temperature must be finite and positive")
    keys, values, is_mapping = _ordered_items(probabilities)
    if temperature == 1.0:
        transformed = list(values)
    else:
        inverse_temperature = 1.0 / temperature
        powered = [0.0 if value == 0.0 else value**inverse_temperature for value in values]
        denominator = math.fsum(powered)
        if not math.isfinite(denominator) or denominator <= 0.0:
            raise SimplexCalibrationError("temperature transform produced no finite mass")
        transformed = [value / denominator for value in powered]
    if is_mapping:
        return dict(zip(keys, transformed, strict=True))
    return transformed


def _outcome_vector(
    probabilities: Mapping[str, float] | Sequence[float],
    *,
    outcomes: Mapping[str, float] | Sequence[float] | None,
    winner_key: str | int | None,
) -> tuple[list[float], list[float]]:
    keys, values, is_mapping = _ordered_items(probabilities)
    if outcomes is not None and winner_key is not None:
        raise SimplexCalibrationError("provide outcomes or winner_key, not both")
    if outcomes is not None:
        validate_complete_partition(probabilities, outcomes=outcomes)
        _, outcome_values, _ = _ordered_items(outcomes)
        return values, outcome_values
    if winner_key is None:
        raise SimplexCalibrationError("a one-hot outcome or winner_key is required")
    winner = str(winner_key)
    if not is_mapping and isinstance(winner_key, int):
        winner = str(winner_key)
    if winner not in keys:
        raise SimplexCalibrationError(f"winner_key {winner!r} is not in the probability partition")
    return values, [1.0 if key == winner else 0.0 for key in keys]


def categorical_partition_scores(
    probabilities: Mapping[str, float] | Sequence[float],
    *,
    outcomes: Mapping[str, float] | Sequence[float] | None = None,
    winner_key: str | int | None = None,
) -> dict[str, float]:
    """Return proper, ordinal, calibration-support, and rank metrics.

    The partition order is meaningful for temperature bands, so the ranked
    probability score (RPS) is reported in addition to the unordered
    categorical Brier score.  Entropy and quadratic concentration are emitted
    as sharpness diagnostics; neither is used as a stand-alone selection
    objective.
    """

    validate_complete_partition(probabilities)
    values, outcome_values = _outcome_vector(
        probabilities,
        outcomes=outcomes,
        winner_key=winner_key,
    )
    brier = math.fsum((probability - outcome) ** 2 for probability, outcome in zip(values, outcome_values))
    winning_probability = math.fsum(
        probability * outcome for probability, outcome in zip(values, outcome_values)
    )
    cumulative_probability = 0.0
    cumulative_outcome = 0.0
    rps = 0.0
    for probability, outcome in zip(values[:-1], outcome_values[:-1]):
        cumulative_probability += probability
        cumulative_outcome += outcome
        rps += (cumulative_probability - cumulative_outcome) ** 2
    entropy = -math.fsum(
        probability * math.log(probability)
        for probability in values
        if probability > 0.0
    )
    predicted_index = min(
        range(len(values)),
        key=lambda index: (-values[index], index),
    )
    winner_index = outcome_values.index(1.0)
    sorted_indexes = sorted(
        range(len(values)),
        key=lambda index: (-values[index], index),
    )
    log_loss = math.inf if winning_probability <= 0.0 else -math.log(winning_probability)
    return {
        "brier": brier,
        "log_loss": log_loss,
        "rps": rps,
        "entropy": entropy,
        "quadratic_concentration": math.fsum(value * value for value in values),
        "winning_probability": winning_probability,
        "top_band_hit": 1.0 if predicted_index == winner_index else 0.0,
        "winner_rank": float(sorted_indexes.index(winner_index) + 1),
        "top_confidence": values[predicted_index],
        "top_correct": 1.0 if predicted_index == winner_index else 0.0,
    }


def score_probability_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    temperature: float = 1.0,
) -> dict[str, float]:
    """Score weighted rows containing probabilities and a categorical outcome."""

    if not rows:
        raise SimplexCalibrationError("at least one probability row is required")
    total_weight = 0.0
    weighted_brier = 0.0
    weighted_log_loss = 0.0
    weighted_rps = 0.0
    weighted_entropy = 0.0
    weighted_concentration = 0.0
    weighted_winning_probability = 0.0
    weighted_top_band_hit = 0.0
    weighted_winner_rank = 0.0
    calibration_rows: list[tuple[float, float, float]] = []
    for row in rows:
        probabilities = row.get("probabilities")
        if probabilities is None:
            raise SimplexCalibrationError("each row must contain probabilities")
        calibrated = simplex_power_transform(probabilities, temperature)
        score = categorical_partition_scores(
            calibrated,
            outcomes=row.get("outcomes"),
            winner_key=row.get("winner_key"),
        )
        weight = float(row.get("sample_weight", row.get("weight", 1.0)))
        if not math.isfinite(weight) or weight <= 0.0:
            raise SimplexCalibrationError("sample weights must be finite and positive")
        total_weight += weight
        weighted_brier += weight * score["brier"]
        weighted_log_loss += weight * score["log_loss"]
        weighted_rps += weight * score["rps"]
        weighted_entropy += weight * score["entropy"]
        weighted_concentration += weight * score["quadratic_concentration"]
        weighted_winning_probability += weight * score["winning_probability"]
        weighted_top_band_hit += weight * score["top_band_hit"]
        weighted_winner_rank += weight * score["winner_rank"]
        calibration_rows.append((score["top_confidence"], score["top_correct"], weight))
    # Weighted top-label ECE.  Fixed bins are diagnostic only; proper scores
    # remain the candidate-selection objectives.
    ece = 0.0
    for bin_index in range(10):
        low = bin_index / 10.0
        high = (bin_index + 1) / 10.0
        bucket = [
            row for row in calibration_rows
            if row[0] >= low and (row[0] < high or (bin_index == 9 and row[0] <= high))
        ]
        bucket_weight = math.fsum(row[2] for row in bucket)
        if bucket_weight <= 0.0:
            continue
        confidence = math.fsum(row[0] * row[2] for row in bucket) / bucket_weight
        accuracy = math.fsum(row[1] * row[2] for row in bucket) / bucket_weight
        ece += (bucket_weight / total_weight) * abs(confidence - accuracy)
    return {
        "brier": weighted_brier / total_weight,
        "log_loss": weighted_log_loss / total_weight,
        "rps": weighted_rps / total_weight,
        "ece": ece,
        "entropy": weighted_entropy / total_weight,
        "quadratic_concentration": weighted_concentration / total_weight,
        "winning_probability": weighted_winning_probability / total_weight,
        "top_band_hit": weighted_top_band_hit / total_weight,
        "winner_rank": weighted_winner_rank / total_weight,
        "weight_sum": total_weight,
        "row_count": len(rows),
    }


def fit_global_simplex_temperature(
    rows: Sequence[Mapping[str, Any]],
    *,
    temperatures: Sequence[float] = DEFAULT_TEMPERATURES,
    improvement_epsilon: float = _IMPROVEMENT_EPSILON,
) -> dict[str, Any]:
    """Fit one global temperature, accepting it only if both proper scores improve."""

    candidate_temperatures = sorted({float(value) for value in temperatures} | {1.0})
    if any(not math.isfinite(value) or value <= 0.0 for value in candidate_temperatures):
        raise SimplexCalibrationError("candidate temperatures must be finite and positive")
    baseline = score_probability_rows(rows, temperature=1.0)
    scored = [
        {"temperature": value, **score_probability_rows(rows, temperature=value)}
        for value in candidate_temperatures
    ]
    best = min(
        scored,
        key=lambda result: (
            result["log_loss"],
            result["brier"],
            abs(result["temperature"] - 1.0),
            result["temperature"],
        ),
    )
    improves_both = (
        best["brier"] < baseline["brier"] - improvement_epsilon
        and best["log_loss"] < baseline["log_loss"] - improvement_epsilon
    )
    selected = best if improves_both else next(
        result for result in scored if result["temperature"] == 1.0
    )
    return {
        "schema_version": CALIBRATOR_SCHEMA_VERSION,
        "method": "simplex_temperature",
        "temperature": selected["temperature"],
        "selection": {
            "accepted_non_identity": improves_both,
            "baseline": baseline,
            "selected": {
                key: selected[key]
                for key in ("temperature", "brier", "log_loss", "weight_sum", "row_count")
            },
            "candidate_scores": scored,
            "acceptance_rule": "strict_improvement_in_brier_and_log_loss",
        },
    }


def apply_simplex_calibrator(
    probabilities: Mapping[str, float] | Sequence[float],
    calibrator: Mapping[str, Any],
) -> dict[str, float] | list[float]:
    """Validate and apply a serialized simplex-temperature calibrator."""

    if calibrator.get("schema_version") != CALIBRATOR_SCHEMA_VERSION:
        raise SimplexCalibrationError("unsupported calibrator schema_version")
    if calibrator.get("method") != "simplex_temperature":
        raise SimplexCalibrationError("unsupported calibration method")
    return simplex_power_transform(probabilities, float(calibrator.get("temperature", math.nan)))


__all__ = [
    "CALIBRATOR_SCHEMA_VERSION",
    "DEFAULT_TEMPERATURES",
    "SimplexCalibrationError",
    "apply_simplex_calibrator",
    "categorical_partition_scores",
    "fit_global_simplex_temperature",
    "score_probability_rows",
    "simplex_power_transform",
    "validate_complete_partition",
]
