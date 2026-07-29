"""Cache-hit payload parity checks for replay retention."""

from __future__ import annotations

import math
from typing import Any


FULL_KEY_FIELDS = (
    "event_slug",
    "consumer",
    "inputs_fp",
    "model_fp",
    "config_fp",
    "schema_version",
)


def _full_key(metadata: dict[str, Any]) -> dict[str, str]:
    return {field: str(metadata.get(field) or "") for field in FULL_KEY_FIELDS}


def _compare_values(
    left: Any,
    right: Any,
    path: str = "$",
) -> dict[str, Any]:
    left_numeric = isinstance(left, (int, float)) and not isinstance(left, bool)
    right_numeric = isinstance(right, (int, float)) and not isinstance(right, bool)
    if left_numeric and right_numeric:
        left_value = float(left)
        right_value = float(right)
        if math.isnan(left_value) or math.isnan(right_value):
            if math.isnan(left_value) and math.isnan(right_value):
                return {
                    "structural": False,
                    "max_numeric_diff": 0.0,
                    "reason": None,
                }
            return {
                "structural": True,
                "max_numeric_diff": math.inf,
                "reason": f"{path}:nan",
            }
        return {
            "structural": False,
            "max_numeric_diff": abs(left_value - right_value),
            "reason": None,
        }
    if type(left) is not type(right):
        return {
            "structural": True,
            "max_numeric_diff": math.inf,
            "reason": f"{path}:type",
        }
    if isinstance(left, dict):
        if set(left) != set(right):
            return {
                "structural": True,
                "max_numeric_diff": math.inf,
                "reason": f"{path}:keys",
            }
        results = [
            _compare_values(left[key], right[key], f"{path}.{key}")
            for key in sorted(left)
        ]
    elif isinstance(left, list):
        if len(left) != len(right):
            return {
                "structural": True,
                "max_numeric_diff": math.inf,
                "reason": f"{path}:length",
            }
        results = [
            _compare_values(a, b, f"{path}[{index}]")
            for index, (a, b) in enumerate(zip(left, right))
        ]
    else:
        return {
            "structural": left != right,
            "max_numeric_diff": math.inf if left != right else 0.0,
            "reason": f"{path}:value" if left != right else None,
        }
    first_structural = next(
        (result for result in results if result["structural"]),
        None,
    )
    if first_structural:
        return first_structural
    return {
        "structural": False,
        "max_numeric_diff": max(
            (float(result["max_numeric_diff"]) for result in results),
            default=0.0,
        ),
        "reason": None,
    }


def cache_payload_parity_checks(
    cached: dict[str, Any],
    rebuilt: dict[str, Any],
    *,
    abs_tolerance: float,
) -> list[dict[str, Any]]:
    """Compare every field consumed by a replay-cache hit."""

    checks = []
    for field in ("rows", "replay_results", "coverage", "diagnostics"):
        comparison = _compare_values(
            cached.get(field),
            rebuilt.get(field),
            f"$.{field}",
        )
        passed = (
            not comparison["structural"]
            and comparison["max_numeric_diff"] <= float(abs_tolerance)
        )
        checks.append(
            {
                "field": field,
                "status": "PASS" if passed else "BLOCK",
                **comparison,
            }
        )
    cached_key = _full_key(cached.get("key") or {})
    rebuilt_key = _full_key(rebuilt.get("key") or {})
    key_matches = (
        isinstance(rebuilt.get("key"), dict)
        and all(cached_key.values())
        and cached_key == rebuilt_key
    )
    checks.append(
        {
            "field": "key",
            "status": "PASS" if key_matches else "BLOCK",
            "structural": not key_matches,
            "max_numeric_diff": 0.0 if key_matches else math.inf,
            "reason": None if key_matches else "$.key:value",
        }
    )
    return checks
