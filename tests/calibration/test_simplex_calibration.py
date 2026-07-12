from __future__ import annotations

import math

import pytest

from weather.calibration.simplex_calibration import (
    SimplexCalibrationError,
    apply_simplex_calibrator,
    fit_global_simplex_temperature,
    simplex_power_transform,
    validate_complete_partition,
)


def test_identity_preserves_complete_partition_exactly():
    probabilities = {"low": 0.2, "mid": 0.5, "high": 0.3}
    assert simplex_power_transform(probabilities, 1.0) == probabilities


def test_temperature_is_joint_and_preserves_hard_zeroes():
    warmed = simplex_power_transform({"low": 0.0, "mid": 0.9, "high": 0.1}, 2.0)
    assert warmed["low"] == 0.0
    assert warmed["mid"] < 0.9
    assert warmed["high"] > 0.1
    assert math.isclose(sum(warmed.values()), 1.0, abs_tol=1e-12)


def test_incomplete_or_independently_invalid_partition_is_rejected():
    with pytest.raises(SimplexCalibrationError, match="sum to one"):
        validate_complete_partition({"a": 0.4, "b": 0.4})
    with pytest.raises(SimplexCalibrationError, match="nonnegative"):
        validate_complete_partition({"a": 1.1, "b": -0.1})


def test_global_fit_is_deterministic_and_uses_one_temperature():
    rows = [
        {"probabilities": {"a": 0.85, "b": 0.15}, "winner_key": "b", "sample_weight": 0.5},
        {"probabilities": {"a": 0.80, "b": 0.20}, "winner_key": "a", "sample_weight": 0.5},
    ]
    first = fit_global_simplex_temperature(rows, temperatures=(1.0, 1.5, 2.0))
    second = fit_global_simplex_temperature(rows, temperatures=(2.0, 1.0, 1.5))
    assert first == second
    assert first["temperature"] in {1.0, 1.5, 2.0}
    calibrated = apply_simplex_calibrator(rows[0]["probabilities"], first)
    assert math.isclose(sum(calibrated.values()), 1.0, abs_tol=1e-12)


def test_identity_is_retained_when_nonidentity_does_not_improve_both_scores():
    rows = [
        {"probabilities": {"a": 0.8, "b": 0.2}, "winner_key": "a"},
        {"probabilities": {"a": 0.2, "b": 0.8}, "winner_key": "b"},
    ]
    fitted = fit_global_simplex_temperature(rows, temperatures=(1.0, 2.0))
    assert fitted["temperature"] == 1.0
    assert fitted["selection"]["accepted_non_identity"] is False
