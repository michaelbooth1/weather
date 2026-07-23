"""Descriptive distribution-sharpness mechanics for the H1 holdout arms."""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import zip_longest
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from weather.reporting.research.current_replay_time_frontier import (
    BOOTSTRAP_REPLICATES,
    MAX_AGGREGATE_GROUPS,
    SCHEMA_VERSION,
    UNITS,
    ExperimentConfigurationError,
    ReaderStats,
    _capture_hour,
    _derived_seed,
    _scope_ids,
    cluster_bootstrap_ci,
    iter_cache_array,
    paired_sign_test,
)


MAX_SHARPNESS_KEYS = 100_000
SHARPNESS_METRICS = (
    "shannon_entropy_nats",
    "max_bucket_probability",
    "std_native",
    "std_c_equivalent",
)
SHARPNESS_MODELS = ("current", "selected")
SHARPNESS_FIELDS = tuple(
    f"{model}_{metric}"
    for model in SHARPNESS_MODELS
    for metric in SHARPNESS_METRICS
)


def _distribution_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("market_id"),
        row.get("target_date"),
        row.get("snapshot_id"),
        row.get("captured_at_local"),
    )


def _distribution_statistics(row: Mapping[str, Any]) -> tuple[dict[str, float], float]:
    distribution = row.get("distribution")
    if not isinstance(distribution, Mapping) or not distribution:
        raise ExperimentConfigurationError(
            f"sharpness distribution is empty for {_distribution_key(row)!r}"
        )
    values: list[tuple[float, float]] = []
    for raw_bucket, raw_probability in distribution.items():
        try:
            bucket = float(raw_bucket)
            probability = float(raw_probability)
        except (TypeError, ValueError) as exc:
            raise ExperimentConfigurationError(
                f"sharpness distribution has nonnumeric support for "
                f"{_distribution_key(row)!r}"
            ) from exc
        if (
            not math.isfinite(bucket)
            or not math.isfinite(probability)
            or probability < 0.0
            or probability > 1.0
        ):
            raise ExperimentConfigurationError(
                f"sharpness distribution has invalid support/probability for "
                f"{_distribution_key(row)!r}"
            )
        values.append((bucket, probability))
    total = sum(probability for _, probability in values)
    mass_error = abs(total - 1.0)
    if total <= 0.0 or mass_error > 1e-6:
        raise ExperimentConfigurationError(
            f"sharpness distribution mass {total} is not one for "
            f"{_distribution_key(row)!r}"
        )
    normalized = [(bucket, probability / total) for bucket, probability in values]
    entropy = -sum(
        probability * math.log(probability)
        for _, probability in normalized
        if probability > 0.0
    )
    maximum = max(probability for _, probability in normalized)
    mean = sum(bucket * probability for bucket, probability in normalized)
    variance = sum(
        probability * (bucket - mean) ** 2
        for bucket, probability in normalized
    )
    std_native = math.sqrt(max(0.0, variance))
    unit = str(row.get("unit") or "").upper()
    if unit not in UNITS:
        raise ExperimentConfigurationError(
            f"sharpness distribution has unsupported unit {unit!r}"
        )
    return (
        {
            "shannon_entropy_nats": entropy,
            "max_bucket_probability": maximum,
            "std_native": std_native,
            "std_c_equivalent": std_native if unit == "C" else std_native * 5.0 / 9.0,
        },
        mass_error,
    )


def _aligned_distribution_pairs(
    current_rows: Iterable[Mapping[str, Any]],
    candidate_rows_by_weight: Mapping[float, Iterable[Mapping[str, Any]]],
    selected_weights: Mapping[str, float],
    *,
    diagnostics: dict[str, Any],
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    weights = sorted(float(weight) for weight in candidate_rows_by_weight)
    streams = [iter(current_rows)] + [
        iter(candidate_rows_by_weight[weight]) for weight in weights
    ]
    sentinel = object()
    seen: set[tuple[Any, ...]] = set()
    raw_rows = 0
    for values in zip_longest(*streams, fillvalue=sentinel):
        raw_rows += 1
        if any(value is sentinel for value in values):
            raise ExperimentConfigurationError(
                "selected/current distribution row counts differ"
            )
        current = dict(values[0])
        key = _distribution_key(current)
        if key in seen:
            raise ExperimentConfigurationError(
                f"duplicate sharpness distribution identity: {key!r}"
            )
        if len(seen) >= MAX_SHARPNESS_KEYS:
            raise ExperimentConfigurationError(
                f"sharpness identity count exceeds bound {MAX_SHARPNESS_KEYS}"
            )
        seen.add(key)
        candidates: dict[float, dict[str, Any]] = {}
        for weight, source in zip(weights, values[1:]):
            candidate = dict(source)
            if _distribution_key(candidate) != key:
                raise ExperimentConfigurationError(
                    f"sharpness alignment mismatch for weight {weight}: "
                    f"{key!r} != {_distribution_key(candidate)!r}"
                )
            for field in ("capture_minute", "cutoff_hour", "unit"):
                if current.get(field) != candidate.get(field):
                    raise ExperimentConfigurationError(
                        f"sharpness immutable field {field!r} differs at {key!r}"
                    )
            candidates[weight] = candidate
        unit = str(current.get("unit") or "").upper()
        if unit not in selected_weights:
            raise ExperimentConfigurationError(
                f"sharpness row has unsupported native unit {unit!r}"
            )
        selected_weight = float(selected_weights[unit])
        selected = current if selected_weight == 0.0 else candidates.get(selected_weight)
        if selected is None:
            raise ExperimentConfigurationError(
                f"sharpness selected weight {selected_weight} was not opened for {unit}"
            )
        yield current, selected
    diagnostics.update(
        {
            "raw_rows": raw_rows,
            "unique_rows": len(seen),
            "duplicates": 0,
            "key_bound": MAX_SHARPNESS_KEYS,
            "key_fields": [
                "market_id",
                "target_date",
                "snapshot_id",
                "captured_at_local",
            ],
        }
    )


def _market_date_rows(
    pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    split: str,
    selected_weights: Mapping[str, float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    observed_dates: set[str] = set()
    unit_snapshots = {unit: 0 for unit in UNITS}
    maximum_mass_error = 0.0
    for current, selected in pairs:
        unit = str(current.get("unit") or "").upper()
        market_id = str(current.get("market_id") or "")
        target_date = str(current.get("target_date") or "")
        observed_dates.add(target_date)
        unit_snapshots[unit] += 1
        current_statistics, current_mass_error = _distribution_statistics(current)
        selected_statistics, selected_mass_error = _distribution_statistics(selected)
        maximum_mass_error = max(
            maximum_mass_error, current_mass_error, selected_mass_error
        )
        for scope in _scope_ids(_capture_hour(current)):
            key = (unit, market_id, target_date, scope)
            group = groups.get(key)
            if group is None:
                if len(groups) >= MAX_AGGREGATE_GROUPS:
                    raise ExperimentConfigurationError(
                        "sharpness market-date aggregation exceeds "
                        f"{MAX_AGGREGATE_GROUPS} groups"
                    )
                group = {
                    "schema_version": SCHEMA_VERSION,
                    "split": split,
                    "evidence_role": "UNTOUCHED_HOLDOUT_DESCRIPTIVE_POST_SELECTION",
                    "unit": unit,
                    "market_id": market_id,
                    "target_date": target_date,
                    "scope": scope,
                    "selected_weight": float(selected_weights[unit]),
                    "snapshots": 0,
                }
                for field in SHARPNESS_FIELDS:
                    group[field] = 0.0
                groups[key] = group
            group["snapshots"] += 1
            for model, statistics in (
                ("current", current_statistics),
                ("selected", selected_statistics),
            ):
                for metric in SHARPNESS_METRICS:
                    group[f"{model}_{metric}"] += statistics[metric]
    rows = []
    for key in sorted(groups):
        row = groups[key]
        count = int(row["snapshots"])
        for field in SHARPNESS_FIELDS:
            row[field] /= count
        rows.append(row)
    return rows, {
        "observed_dates": sorted(observed_dates),
        "unit_snapshots": unit_snapshots,
        "maximum_probability_mass_error": maximum_mass_error,
        "market_date_scope_rows": len(rows),
    }


def _fleet_date_rows(
    market_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in market_rows:
        key = (
            str(row["split"]),
            str(row["unit"]),
            str(row["target_date"]),
            str(row["scope"]),
        )
        groups[key].append(row)
    output = []
    for key in sorted(groups):
        split, unit, target_date, scope = key
        rows = groups[key]
        result = {
            "schema_version": SCHEMA_VERSION,
            "split": split,
            "evidence_role": "UNTOUCHED_HOLDOUT_DESCRIPTIVE_POST_SELECTION",
            "unit": unit,
            "market_id": "__fleet__",
            "target_date": target_date,
            "scope": scope,
            "selected_weight": rows[0]["selected_weight"],
            "markets": len(rows),
            "snapshots": sum(int(row["snapshots"]) for row in rows),
        }
        for field in SHARPNESS_FIELDS:
            result[field] = sum(float(row[field]) for row in rows) / len(rows)
        output.append(result)
    return output


def _summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    split: str,
    unit: str,
    market_id: str,
    scope: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "split": split,
        "evidence_role": "UNTOUCHED_HOLDOUT_DESCRIPTIVE_POST_SELECTION",
        "unit": unit,
        "market_id": market_id,
        "scope": scope,
        "selected_weight": float(rows[0]["selected_weight"]),
        "fleet_dates": len(rows),
        "markets_per_fleet_date": {
            "minimum": min(int(row.get("markets", 1)) for row in rows),
            "maximum": max(int(row.get("markets", 1)) for row in rows),
        },
        "metrics": {},
        "selected_vs_current": {},
    }
    for model in SHARPNESS_MODELS:
        result["metrics"][model] = {
            metric: sum(float(row[f"{model}_{metric}"]) for row in rows) / len(rows)
            for metric in SHARPNESS_METRICS
        }
    for metric in SHARPNESS_METRICS:
        deltas = [
            float(row[f"selected_{metric}"]) - float(row[f"current_{metric}"])
            for row in rows
        ]
        lower_is_sharper = metric != "max_bucket_probability"
        seed_metric = "std_native" if metric == "std_c_equivalent" else metric
        result["selected_vs_current"][metric] = {
            "mean_delta": sum(deltas) / len(deltas),
            "paired_fleet_date_bootstrap_95ci": cluster_bootstrap_ci(
                deltas,
                seed=_derived_seed(
                    "sharpness", split, unit, market_id, scope, seed_metric
                ),
                replicates=BOOTSTRAP_REPLICATES,
            ),
            "paired_fleet_date_sign_test": paired_sign_test(
                deltas,
                lower_is_better=lower_is_sharper,
            ),
            "sharper_direction": "negative" if lower_is_sharper else "positive",
        }
    entropy_delta = result["selected_vs_current"]["shannon_entropy_nats"][
        "mean_delta"
    ]
    maximum_delta = result["selected_vs_current"]["max_bucket_probability"][
        "mean_delta"
    ]
    std_delta = result["selected_vs_current"]["std_native"]["mean_delta"]
    if entropy_delta > 0.0 and maximum_delta < 0.0 and std_delta > 0.0:
        result["descriptive_shape_direction"] = "DIFFUSER_ALL_THREE"
    elif entropy_delta < 0.0 and maximum_delta > 0.0 and std_delta < 0.0:
        result["descriptive_shape_direction"] = "SHARPER_ALL_THREE"
    else:
        result["descriptive_shape_direction"] = "MIXED"
    return result


def _summaries(
    market_rows: Sequence[Mapping[str, Any]],
    fleet_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    market_groups: dict[
        tuple[str, str, str, str], list[Mapping[str, Any]]
    ] = defaultdict(list)
    for row in market_rows:
        market_groups[
            (
                str(row["split"]),
                str(row["unit"]),
                str(row["market_id"]),
                str(row["scope"]),
            )
        ].append(row)
    for (split, unit, market_id, scope), rows in sorted(market_groups.items()):
        output.append(
            _summary(
                rows,
                split=split,
                unit=unit,
                market_id=market_id,
                scope=scope,
            )
        )
    fleet_groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in fleet_rows:
        fleet_groups[
            (str(row["split"]), str(row["unit"]), str(row["scope"]))
        ].append(row)
    for (split, unit, scope), rows in sorted(fleet_groups.items()):
        output.append(
            _summary(
                rows,
                split=split,
                unit=unit,
                market_id="__fleet__",
                scope=scope,
            )
        )
    return output


def analyze_holdout_sharpness(
    *,
    current_cache: Path,
    selected_caches_by_weight: Mapping[float, Path],
    selected_weights: Mapping[str, float],
    expected_dates: Sequence[str],
) -> dict[str, Any]:
    """Stream exact bucket distributions and summarize shape without gating H1."""

    current_stats = ReaderStats("distribution_rows", 256 * 1024, 4 * 1024 * 1024)
    current_rows = iter_cache_array(
        current_cache,
        "distribution_rows",
        stats=current_stats,
    )
    candidate_stats: dict[float, ReaderStats] = {}
    candidates: dict[float, Iterable[Mapping[str, Any]]] = {}
    for weight, path in sorted(selected_caches_by_weight.items()):
        stats = ReaderStats("distribution_rows", 256 * 1024, 4 * 1024 * 1024)
        candidate_stats[float(weight)] = stats
        candidates[float(weight)] = iter_cache_array(
            path,
            "distribution_rows",
            stats=stats,
        )
    alignment: dict[str, Any] = {}
    pairs = _aligned_distribution_pairs(
        current_rows,
        candidates,
        selected_weights,
        diagnostics=alignment,
    )
    market_rows, aggregation = _market_date_rows(
        pairs,
        split="holdout",
        selected_weights=selected_weights,
    )
    if tuple(aggregation["observed_dates"]) != tuple(expected_dates):
        raise ExperimentConfigurationError(
            "sharpness holdout dates do not exactly match manifest: "
            f"expected={list(expected_dates)}, "
            f"observed={aggregation['observed_dates']}"
        )
    if any(aggregation["unit_snapshots"][unit] <= 0 for unit in UNITS):
        raise ExperimentConfigurationError(
            f"sharpness holdout is missing a native unit: {aggregation['unit_snapshots']}"
        )
    fleet_rows = _fleet_date_rows(market_rows)
    summaries = _summaries(market_rows, fleet_rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_DESCRIPTIVE",
        "evidence_role": "UNTOUCHED_HOLDOUT_DESCRIPTIVE_POST_SELECTION",
        "selection_or_gate_use": False,
        "method": {
            "distribution": "exact replayed integer bucket probability map",
            "shannon_entropy_units": "natural-log nats",
            "max_bucket_probability": "maximum exact replay bucket probability",
            "std_native": "probability-weighted integer bucket-key standard deviation",
            "std_c_equivalent": "C unchanged; F multiplied by 5/9",
            "weighting": (
                "snapshot -> market-date mean -> fleet-date equal-market mean -> "
                "equal fleet-date mean"
            ),
            "comparability": (
                "selected-current comparisons are within native unit; absolute entropy "
                "is not compared across C/F because physical bucket widths differ"
            ),
            "bootstrap_unit": "paired fleet date",
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        },
        "selected_weights": {unit: float(selected_weights[unit]) for unit in UNITS},
        "diagnostics": {
            **aggregation,
            "alignment": alignment,
            "current_reader": current_stats.as_dict(),
            "selected_readers": {
                str(weight): candidate_stats[weight].as_dict()
                for weight in sorted(candidate_stats)
            },
            "full_cache_loaded": False,
        },
        "market_date_rows": market_rows,
        "fleet_date_rows": fleet_rows,
        "summaries": summaries,
    }


__all__ = [
    "MAX_SHARPNESS_KEYS",
    "SHARPNESS_METRICS",
    "analyze_holdout_sharpness",
]
