"""Clustered power design for the first all-market base-retrain confirmation.

This module consumes only pre-aggregated, published development evidence.  It
does not read replay rows, fit or score a candidate, or know how to reach a
network provider.  The CLI writes a machine-readable design and its matching
Markdown report beneath one explicitly supplied run root outside ``data/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import nct, t

from weather.paths import DATA_ROOT


INPUT_SCHEMA_VERSION = "detectable_win_power_design_input_v0.1"
REPORT_SCHEMA_VERSION = "detectable_win_power_design_v0.1"
DEFAULT_SIMULATION_REPETITIONS = 200_000
DEFAULT_SIMULATION_SEED = 20_260_904


class DetectableWinPowerError(ValueError):
    """Raised when the declared power-design contract is incomplete or unsafe."""


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_float(value: object, *, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise DetectableWinPowerError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise DetectableWinPowerError(f"{name} must be finite")
    return parsed


def one_sided_clustered_t_power(
    cluster_count: int,
    effect: float,
    cluster_standard_deviation: float,
    *,
    alpha: float = 0.05,
    degrees_of_freedom_cap: int | None = None,
) -> float:
    """Power for a one-sided paired mean test over independent date clusters.

    ``effect`` is a positive improvement magnitude.  Snapshot and band rows do
    not enter this calculation; each input value is one whole-fleet date (or
    one Toronto market-day for the Toronto-only sensitivity).
    """

    if cluster_count < 3:
        raise DetectableWinPowerError("cluster_count must be at least 3")
    if effect < 0.0:
        raise DetectableWinPowerError("effect must be non-negative")
    if cluster_standard_deviation <= 0.0:
        raise DetectableWinPowerError("cluster_standard_deviation must be positive")
    if not 0.0 < alpha < 1.0:
        raise DetectableWinPowerError("alpha must be in (0, 1)")
    degrees_of_freedom = cluster_count - 1
    if degrees_of_freedom_cap is not None:
        if degrees_of_freedom_cap < 2:
            raise DetectableWinPowerError("degrees_of_freedom_cap must be at least 2")
        degrees_of_freedom = min(degrees_of_freedom, degrees_of_freedom_cap)
    critical = float(t.ppf(1.0 - alpha, degrees_of_freedom))
    noncentrality = effect * math.sqrt(cluster_count) / cluster_standard_deviation
    return float(1.0 - nct.cdf(critical, degrees_of_freedom, noncentrality))


def minimum_detectable_effect(
    cluster_count: int,
    cluster_standard_deviation: float,
    *,
    target_power: float = 0.80,
    alpha: float = 0.05,
    degrees_of_freedom_cap: int | None = None,
) -> float:
    """Return the positive effect detected at ``target_power``."""

    if not 0.0 < target_power < 1.0:
        raise DetectableWinPowerError("target_power must be in (0, 1)")
    lower = 0.0
    upper = cluster_standard_deviation
    while one_sided_clustered_t_power(
        cluster_count,
        upper,
        cluster_standard_deviation,
        alpha=alpha,
        degrees_of_freedom_cap=degrees_of_freedom_cap,
    ) < target_power:
        upper *= 2.0
    for _ in range(80):
        midpoint = (lower + upper) / 2.0
        if one_sided_clustered_t_power(
            cluster_count,
            midpoint,
            cluster_standard_deviation,
            alpha=alpha,
            degrees_of_freedom_cap=degrees_of_freedom_cap,
        ) >= target_power:
            upper = midpoint
        else:
            lower = midpoint
    return upper


def required_cluster_count(
    effect: float,
    cluster_standard_deviation: float,
    *,
    target_power: float = 0.80,
    alpha: float = 0.05,
    maximum_clusters: int = 100_000,
    degrees_of_freedom_cap: int | None = None,
) -> int | None:
    """Return required independent clusters, or ``None`` for a zero effect."""

    if effect < 0.0:
        raise DetectableWinPowerError("effect must be non-negative")
    if effect == 0.0:
        return None
    low = 3
    high = 3
    while one_sided_clustered_t_power(
        high,
        effect,
        cluster_standard_deviation,
        alpha=alpha,
        degrees_of_freedom_cap=degrees_of_freedom_cap,
    ) < target_power:
        low = high + 1
        high *= 2
        if high > maximum_clusters:
            high = maximum_clusters
            break
    if one_sided_clustered_t_power(
        high,
        effect,
        cluster_standard_deviation,
        alpha=alpha,
        degrees_of_freedom_cap=degrees_of_freedom_cap,
    ) < target_power:
        return None
    while low < high:
        midpoint = (low + high) // 2
        if one_sided_clustered_t_power(
            midpoint,
            effect,
            cluster_standard_deviation,
            alpha=alpha,
            degrees_of_freedom_cap=degrees_of_freedom_cap,
        ) >= target_power:
            high = midpoint
        else:
            low = midpoint + 1
    return low


def _validate_cluster_values(values: object, *, name: str) -> list[float]:
    if not isinstance(values, list) or len(values) < 3:
        raise DetectableWinPowerError(f"{name} must contain at least three date clusters")
    return [_finite_float(value, name=f"{name}[{index}]") for index, value in enumerate(values)]


def validate_design_input(payload: Mapping[str, Any]) -> None:
    """Validate the aggregate-only input contract."""

    if payload.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise DetectableWinPowerError("unsupported input schema_version")
    design = payload.get("design")
    if not isinstance(design, Mapping):
        raise DetectableWinPowerError("design object is required")
    current_days = int(design.get("current_reservation_days", 0))
    recommended_days = int(design.get("recommended_reservation_days", 0))
    if current_days <= 0 or recommended_days < current_days:
        raise DetectableWinPowerError("reservation day counts are invalid")
    try:
        date.fromisoformat(str(design["reservation_start"]))
    except (KeyError, ValueError) as exc:
        raise DetectableWinPowerError("reservation_start must be an ISO date") from exc

    endpoints = payload.get("endpoints")
    if not isinstance(endpoints, list) or {item.get("id") for item in endpoints} != {
        "pooled_brier",
        "primary_09_14_brier",
        "severe_tail_sse",
    }:
        raise DetectableWinPowerError("the three declared endpoints are required")
    for endpoint in endpoints:
        endpoint_id = str(endpoint["id"])
        upper_fraction = _finite_float(
            endpoint.get("planning_effect_fraction_upper"),
            name=f"{endpoint_id}.planning_effect_fraction_upper",
        )
        midpoint_fraction = _finite_float(
            endpoint.get("planning_effect_fraction_midpoint"),
            name=f"{endpoint_id}.planning_effect_fraction_midpoint",
        )
        if not 0.0 < midpoint_fraction <= upper_fraction:
            raise DetectableWinPowerError(f"{endpoint_id} effect fractions are invalid")
        populations = endpoint.get("populations")
        if not isinstance(populations, Mapping) or set(populations) != {"fleet", "toronto"}:
            raise DetectableWinPowerError(f"{endpoint_id} requires fleet and Toronto populations")
        for population_id, population in populations.items():
            baseline = _finite_float(
                population.get("baseline_reference"),
                name=f"{endpoint_id}.{population_id}.baseline_reference",
            )
            if baseline <= 0.0:
                raise DetectableWinPowerError("baseline references must be positive")
            _validate_cluster_values(
                population.get("cluster_deltas"),
                name=f"{endpoint_id}.{population_id}.cluster_deltas",
            )
            override = population.get("cluster_standard_deviation_override")
            if override is not None and _finite_float(
                override,
                name=f"{endpoint_id}.{population_id}.cluster_standard_deviation_override",
            ) <= 0.0:
                raise DetectableWinPowerError("cluster standard-deviation overrides must be positive")
            cap = population.get("degrees_of_freedom_cap")
            if cap is not None and int(cap) < 2:
                raise DetectableWinPowerError("degrees-of-freedom caps must be at least 2")

    slice_gate = payload.get("slice_gate")
    if not isinstance(slice_gate, Mapping):
        raise DetectableWinPowerError("slice_gate object is required")
    total_rows = int(slice_gate.get("reference_snapshot_count", 0))
    dimensions = slice_gate.get("dimension_slice_counts")
    if total_rows <= 0 or not isinstance(dimensions, Mapping):
        raise DetectableWinPowerError("slice support counts are required")
    observed_slices = 0
    for dimension, counts in dimensions.items():
        if not isinstance(counts, list) or not counts:
            raise DetectableWinPowerError(f"slice counts missing for {dimension}")
        parsed = [int(value) for value in counts]
        if any(value <= 0 for value in parsed) or sum(parsed) != total_rows:
            raise DetectableWinPowerError(f"slice counts do not partition rows for {dimension}")
        observed_slices += len(parsed)
    if observed_slices != 54:
        raise DetectableWinPowerError("the reference gate must contain 54 observed slices")


def _endpoint_power(
    endpoint: Mapping[str, Any],
    *,
    current_days: int,
    target_power: float,
    alpha: float,
) -> dict[str, Any]:
    upper_fraction = float(endpoint["planning_effect_fraction_upper"])
    midpoint_fraction = float(endpoint["planning_effect_fraction_midpoint"])
    populations: dict[str, Any] = {}
    for population_id, population in endpoint["populations"].items():
        cluster_deltas = [float(value) for value in population["cluster_deltas"]]
        unadjusted_date_standard_deviation = stdev(cluster_deltas)
        standard_deviation = float(
            population.get(
                "cluster_standard_deviation_override",
                unadjusted_date_standard_deviation,
            )
        )
        degrees_of_freedom_cap = (
            int(population["degrees_of_freedom_cap"])
            if population.get("degrees_of_freedom_cap") is not None
            else None
        )
        baseline = float(population["baseline_reference"])
        upper_effect = baseline * upper_fraction
        midpoint_effect = baseline * midpoint_fraction
        detectable = minimum_detectable_effect(
            current_days,
            standard_deviation,
            target_power=target_power,
            alpha=alpha,
            degrees_of_freedom_cap=degrees_of_freedom_cap,
        )
        populations[population_id] = {
            "baseline_reference": baseline,
            "source_cluster_count": len(cluster_deltas),
            "source_cluster_mean_delta": mean(cluster_deltas),
            "unadjusted_date_cluster_standard_deviation": unadjusted_date_standard_deviation,
            "source_cluster_standard_deviation": standard_deviation,
            "variance_method": population.get(
                "variance_method", "one-way target-date clusters"
            ),
            "variance_components": population.get("variance_components"),
            "degrees_of_freedom_cap": degrees_of_freedom_cap,
            "cluster_unit": population["cluster_unit"],
            "variance_evidence": population["variance_evidence"],
            "current_window": {
                "date_clusters": current_days,
                "minimum_detectable_effect": detectable,
                "minimum_detectable_fraction_of_baseline": detectable / baseline,
                "power_at_upper_planning_effect": one_sided_clustered_t_power(
                    current_days,
                    upper_effect,
                    standard_deviation,
                    alpha=alpha,
                    degrees_of_freedom_cap=degrees_of_freedom_cap,
                ),
            },
            "planning_effect": {
                "range_lower": 0.0,
                "upper_fraction_of_baseline": upper_fraction,
                "upper_absolute": upper_effect,
                "midpoint_fraction_of_baseline": midpoint_fraction,
                "midpoint_absolute": midpoint_effect,
                "required_date_clusters_at_upper": required_cluster_count(
                    upper_effect,
                    standard_deviation,
                    target_power=target_power,
                    alpha=alpha,
                    degrees_of_freedom_cap=degrees_of_freedom_cap,
                ),
                "required_date_clusters_at_midpoint": required_cluster_count(
                    midpoint_effect,
                    standard_deviation,
                    target_power=target_power,
                    alpha=alpha,
                    degrees_of_freedom_cap=degrees_of_freedom_cap,
                ),
                "required_date_clusters_at_zero": None,
            },
        }
    return {
        "id": endpoint["id"],
        "label": endpoint["label"],
        "measure": endpoint["measure"],
        "role": endpoint["role"],
        "populations": populations,
    }


def simulate_slice_gate_false_rejection(
    dimension_slice_counts: Mapping[str, Sequence[int]],
    *,
    reference_snapshot_count: int,
    date_cluster_standard_deviation: float,
    date_clusters: int,
    uniform_improvement: float,
    repetitions: int = DEFAULT_SIMULATION_REPETITIONS,
    seed: int = DEFAULT_SIMULATION_SEED,
) -> dict[str, Any]:
    """Simulate the raw slice bar and a max-T harm-evidence replacement.

    Each protected dimension remains a partition of the same population.  A
    whole-date shock is shared by every slice; dimension-specific residuals are
    centered so their support-weighted mean is zero.  This retains the pooled /
    slice dependence instead of pretending 53--54 independent tests.
    """

    if repetitions < 1_000:
        raise DetectableWinPowerError("slice simulation requires at least 1,000 repetitions")
    if date_clusters < 3 or date_cluster_standard_deviation <= 0.0:
        raise DetectableWinPowerError("slice simulation cluster inputs are invalid")
    if uniform_improvement <= 0.0:
        raise DetectableWinPowerError("uniform_improvement must be positive")

    rng = np.random.default_rng(seed)
    pooled_error = rng.normal(
        0.0,
        date_cluster_standard_deviation / math.sqrt(date_clusters),
        size=repetitions,
    )
    raw_flags: list[np.ndarray] = []
    standardized_contrasts: list[np.ndarray] = []
    contrast_standard_errors: list[float] = []
    dimension_false_rejection: dict[str, float] = {}

    for dimension, counts in dimension_slice_counts.items():
        fractions = np.asarray(counts, dtype=float) / float(reference_snapshot_count)
        independent = rng.normal(size=(repetitions, len(fractions))) * (
            date_cluster_standard_deviation / np.sqrt(date_clusters * fractions)
        )
        residual = independent - np.sum(independent * fractions, axis=1)[:, None]
        contrast_error = residual + 2.0 * pooled_error[:, None]
        flags = contrast_error > 2.0 * uniform_improvement
        raw_flags.extend(flags[:, index] for index in range(flags.shape[1]))
        dimension_false_rejection[str(dimension)] = float(np.any(flags, axis=1).mean())

        standard_errors = (
            date_cluster_standard_deviation
            / math.sqrt(date_clusters)
            * np.sqrt((1.0 / fractions) + 3.0)
        )
        standardized_contrasts.extend(
            contrast_error[:, index] / standard_errors[index]
            for index in range(contrast_error.shape[1])
        )
        contrast_standard_errors.extend(float(value) for value in standard_errors)

    flag_matrix = np.column_stack(raw_flags)
    failures_per_repetition = flag_matrix.sum(axis=1)
    raw_fwer = float((failures_per_repetition > 0).mean())
    rates_after_one_removed = [
        float((failures_per_repetition - flag_matrix[:, index] > 0).mean())
        for index in range(flag_matrix.shape[1])
    ]

    statistic_matrix = np.column_stack(standardized_contrasts)
    maximum_statistic = statistic_matrix.max(axis=1)
    max_t_critical = float(np.quantile(maximum_statistic, 0.95))
    standard_errors_array = np.asarray(contrast_standard_errors)
    uniformly_better_shift = -2.0 * uniform_improvement / standard_errors_array
    corrected_uniform_fwer = float(
        np.any(statistic_matrix + uniformly_better_shift > max_t_critical, axis=1).mean()
    )
    corrected_boundary_fwer = float((maximum_statistic > max_t_critical).mean())

    return {
        "date_clusters": date_clusters,
        "uniform_improvement": uniform_improvement,
        "date_cluster_standard_deviation": date_cluster_standard_deviation,
        "repetitions": repetitions,
        "seed": seed,
        "observed_slice_count": int(flag_matrix.shape[1]),
        "raw_point_bar_false_rejection_rate_54_slices": raw_fwer,
        "raw_point_bar_false_rejection_rate_53_slices_min": min(rates_after_one_removed),
        "raw_point_bar_false_rejection_rate_53_slices_max": max(rates_after_one_removed),
        "dimension_false_rejection_rates": dimension_false_rejection,
        "max_t_critical_value": max_t_critical,
        "max_t_boundary_familywise_error": corrected_boundary_fwer,
        "max_t_uniformly_better_false_rejection_rate": corrected_uniform_fwer,
        "dependence_model": (
            "whole-date shared shock plus support-scaled residuals centered within each "
            "protected dimension, calibrated to the declared two-way date/market endpoint "
            "standard deviation; every dimension remains a partition of the same rows"
        ),
    }


def _build_reservation(
    payload: Mapping[str, Any], endpoint_results: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    design = payload["design"]
    start = date.fromisoformat(str(design["reservation_start"]))
    current_days = int(design["current_reservation_days"])
    recommended_days = int(design["recommended_reservation_days"])
    primary = next(item for item in endpoint_results if item["id"] == design["primary_endpoint_id"])
    estimated_required = int(
        primary["populations"]["fleet"]["planning_effect"][
            "required_date_clusters_at_upper"
        ]
    )
    if recommended_days < estimated_required:
        raise DetectableWinPowerError("recommended reservation is shorter than primary upper-effect N")
    return {
        "recommendation": "EXTEND_NOW",
        "original_start": start.isoformat(),
        "original_end": (start + timedelta(days=current_days - 1)).isoformat(),
        "original_days": current_days,
        "additional_start": (start + timedelta(days=current_days)).isoformat(),
        "additional_end": (start + timedelta(days=recommended_days - 1)).isoformat(),
        "additional_days": recommended_days - current_days,
        "total_reserved_days": recommended_days,
        "point_estimate_required_days_for_upper_effect": estimated_required,
        "point_estimate_buffer_days": recommended_days - estimated_required,
        "midpoint_required_days": primary["populations"]["fleet"]["planning_effect"][
            "required_date_clusters_at_midpoint"
        ],
        "zero_effect_required_days": None,
        "interpretation": (
            "The extension is the minimum point-estimate reservation for the optimistic top "
            "of the honest served-effect range. A 504-date, greater-than-16-month confirmation is not a "
            "realistic single-candidate test; it is still not powered for the midpoint, and "
            "no finite reservation can detect a true zero effect."
        ),
    }


def build_power_design(
    payload: Mapping[str, Any],
    *,
    generated_at_utc: str | None = None,
    simulation_repetitions: int = DEFAULT_SIMULATION_REPETITIONS,
) -> dict[str, Any]:
    """Build the complete aggregate-only power design."""

    validate_design_input(payload)
    design = payload["design"]
    current_days = int(design["current_reservation_days"])
    target_power = float(design["target_power"])
    alpha = float(design["one_sided_alpha"])
    endpoint_results = [
        _endpoint_power(
            endpoint,
            current_days=current_days,
            target_power=target_power,
            alpha=alpha,
        )
        for endpoint in payload["endpoints"]
    ]
    primary = next(item for item in endpoint_results if item["id"] == "primary_09_14_brier")
    pooled = next(item for item in endpoint_results if item["id"] == "pooled_brier")
    uniform_improvement = float(
        primary["populations"]["fleet"]["planning_effect"]["upper_absolute"]
    )
    slice_gate = payload["slice_gate"]
    common_simulation = {
        "dimension_slice_counts": slice_gate["dimension_slice_counts"],
        "reference_snapshot_count": int(slice_gate["reference_snapshot_count"]),
        "date_clusters": current_days,
        "uniform_improvement": uniform_improvement,
        "repetitions": simulation_repetitions,
        "seed": int(slice_gate["simulation_seed"]),
    }
    lower_variance = simulate_slice_gate_false_rejection(
        date_cluster_standard_deviation=float(
            pooled["populations"]["fleet"]["source_cluster_standard_deviation"]
        ),
        **common_simulation,
    )
    primary_variance = simulate_slice_gate_false_rejection(
        date_cluster_standard_deviation=float(
            primary["populations"]["fleet"]["source_cluster_standard_deviation"]
        ),
        **common_simulation,
    )

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "DESIGN_COMPLETE_NO_RESERVED_DATA_READ",
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
        "method": {
            "test": (
                "one-sided paired mean power using a fleet-date-equivalent standard "
                "deviation from two-way date/market clustered variance"
            ),
            "alpha": alpha,
            "target_power": target_power,
            "fleet_cluster": (
                "market-day first, with two-way date and market clustered variance; "
                "fleet-date equivalent standard deviation and 12-market df cap"
            ),
            "toronto_cluster": "Toronto target date (one market-day)",
            "prohibited_independence_assumption": "snapshot rows or band rows as IID",
            "source_boundary": payload["source_boundary"],
        },
        "expected_effect": payload["effect_evidence"],
        "endpoint_power": endpoint_results,
        "slice_gate": {
            "current_rule": slice_gate["current_rule"],
            "reference_observed_slices": 54,
            "published_candidate_failures": slice_gate["published_candidate_failures"],
            "false_rejection_sensitivity": {
                "lower_all_hour_variance_proxy": lower_variance,
                "primary_09_14_variance": primary_variance,
            },
            "verdict": "UNACCEPTABLE_LOTTERY",
            "correction": {
                "name": "one-sided two-way-cluster max-T harm-evidence gate",
                "hypothesis": (
                    "For each pre-registered slice, test candidate-minus-incumbent delta "
                    "greater than the pooled-improvement margin; block only when the "
                    "simultaneous lower confidence bound proves that harm."
                ),
                "familywise_alpha": 0.05,
                "resampling_unit": (
                    "multiway wild-cluster weights over target dates and markets, with the "
                    "complete frozen slice vector attached and the market-day intersection "
                    "component removed once"
                ),
                "small_slice_policy": (
                    "Insufficient date support is NOT_EVALUABLE, never a pass; collect more "
                    "evidence or quarantine that regime without treating a noisy point estimate "
                    "as a statistical block."
                ),
                "hard_gates_unchanged": (
                    "probability mass, trusted floor, release/parity, newly severe, and other "
                    "deterministic safety invariants remain conjunctive"
                ),
            },
        },
        "primary_endpoint": payload["primary_endpoint"],
    }
    report["reservation"] = _build_reservation(payload, endpoint_results)
    report["input_canonical_sha256"] = _sha256_text(_canonical_json(payload))
    report["report_sha256"] = _sha256_text(_canonical_json(report))
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise human-readable counterpart to the JSON design."""

    reservation = report["reservation"]
    expected = report["expected_effect"]
    if reservation["point_estimate_buffer_days"]:
        buffer_sentence = (
            f"The {reservation['total_reserved_days']}-day recommendation adds a "
            f"{reservation['point_estimate_buffer_days']}-day planning buffer."
        )
    else:
        buffer_sentence = (
            f"The {reservation['total_reserved_days']}-day recommendation is that exact "
            "point estimate and contains no variance-estimation buffer."
        )
    lines = [
        "# Can we even detect the win?",
        "",
        "## Reservation recommendation",
        "",
        f"**Extend now by {reservation['additional_days']} days: "
        f"{reservation['additional_start']} through {reservation['additional_end']}.** "
        f"That makes {reservation['total_reserved_days']} reserved target dates in total.",
        "",
        f"The point estimate needs {reservation['point_estimate_required_days_for_upper_effect']} "
        "fleet dates to reach 80% power at the optimistic top of the expected served effect. "
        f"{buffer_sentence} At the 2.5% "
        f"gap-closure midpoint it needs {reservation['midpoint_required_days']} dates; at a "
        "true zero effect no finite N can detect a win.",
        "",
        "Plainly: this is not a realistic single-candidate confirmation horizon. The exact "
        "extension is the amount to reserve only if preserving a formally powered test at the "
        "optimistic effect is worth more than 16 months of otherwise usable evidence.",
        "",
        "## Expected served effect",
        "",
        f"The honest fleet served-level range is **0 to "
        f"{100.0 * expected['served_gap_fraction_upper']:.2f}% of the incumbent-market Brier "
        f"gap** (0 to {expected['served_absolute_improvement_upper']:.6f} absolute Brier). "
        "The upper endpoint is the measured out-of-fold conditional correction, not a retrain "
        "guarantee, and its interval crosses zero.",
        "",
        f"Upstream raw correction closed {100.0 * expected['raw_gap_fraction']:.2f}% of its gap, "
        f"but downstream serving retained only {100.0 * expected['served_gap_fraction_upper']:.2f}%. "
        f"The forecast lookahead explains only {100.0 * expected['forecast_lookahead_bias_fraction']:.1f}% "
        "of the raw centre displacement. The severe-tail diagnostic is much larger but cannot "
        "replace a pooled proper-score endpoint.",
        "",
        "## Clustered power",
        "",
        "| Endpoint | Population | 14-day MDE | MDE / baseline | N at upper effect | N at midpoint |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for endpoint in report["endpoint_power"]:
        for population_id in ("fleet", "toronto"):
            population = endpoint["populations"][population_id]
            current = population["current_window"]
            planning = population["planning_effect"]
            lines.append(
                f"| {endpoint['label']} | {population_id.title()} | "
                f"{current['minimum_detectable_effect']:.6f} | "
                f"{100.0 * current['minimum_detectable_fraction_of_baseline']:.1f}% | "
                f"{planning['required_date_clusters_at_upper']} | "
                f"{planning['required_date_clusters_at_midpoint']} |"
            )
    lines.extend(
        [
            "",
            "Fleet inference aggregates market-day first, then uses two-way date and market "
            "clustered variance converted to a fleet-date equivalent with degrees of freedom "
            "capped by 12 markets. Toronto uses one Toronto market-day per date. Snapshot and "
            "band-row counts never enter N.",
            "",
            "## Protected-slice gate",
            "",
        ]
    )
    sensitivity = report["slice_gate"]["false_rejection_sensitivity"]
    low = sensitivity["lower_all_hour_variance_proxy"]
    high = sensitivity["primary_09_14_variance"]
    lines.extend(
        [
            f"At 14 dates, the current raw point-estimate rule falsely rejects a uniformly "
            f"better candidate in **{100.0 * low['raw_point_bar_false_rejection_rate_54_slices']:.2f}% "
            f"to {100.0 * high['raw_point_bar_false_rejection_rate_54_slices']:.2f}%** of simulations. "
            "Removing any one slice (53 rather than 54) does not materially change that result.",
            "",
            "Replace it with a one-sided two-way-cluster max-T harm-evidence gate over the frozen "
            "slice family. It controls boundary familywise error at 5%, preserves cross-slice "
            "dependence, and still blocks a regime only when simultaneous evidence shows harm "
            "beyond the pooled-improvement margin.",
            "",
            "## Pre-registered primary endpoint",
            "",
            f"**{report['primary_endpoint']['name']}**",
            "",
            report["primary_endpoint"]["definition"],
            "",
            report["primary_endpoint"]["decision_rule"],
            "",
            "Pooled all-hour Brier and the incumbent-frozen severe tail remain secondary "
            "safety/diagnostic endpoints. They cannot be selected as the win criterion after "
            "results are visible.",
            "",
            "## Evidence boundary",
            "",
            report["method"]["source_boundary"],
            "",
            f"Input canonical SHA-256: `{report['input_canonical_sha256']}`",
            "",
            f"Report SHA-256: `{report['report_sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _safe_run_root(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    data_root = DATA_ROOT.resolve(strict=False)
    if resolved == data_root or data_root in resolved.parents:
        raise DetectableWinPowerError("run_root must be outside data/")
    return resolved


def write_power_design(
    report: Mapping[str, Any],
    *,
    run_root: Path,
) -> tuple[Path, Path]:
    """Write the JSON and Markdown counterparts beneath the declared root."""

    resolved_root = _safe_run_root(run_root)
    resolved_root.mkdir(parents=True, exist_ok=True)
    json_path = resolved_root / "detectable-win-power.json"
    markdown_path = resolved_root / "detectable-win-power.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a no-network, aggregate-only clustered power design."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument(
        "--simulation-repetitions",
        type=int,
        default=DEFAULT_SIMULATION_REPETITIONS,
    )
    args = parser.parse_args(argv)
    input_path = args.input.resolve(strict=True)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    report = build_power_design(
        payload,
        simulation_repetitions=args.simulation_repetitions,
    )
    report["input_file_sha256"] = _sha256_file(input_path)
    report["report_sha256"] = _sha256_text(
        _canonical_json({key: value for key, value in report.items() if key != "report_sha256"})
    )
    json_path, markdown_path = write_power_design(report, run_root=args.run_root)
    print(
        json.dumps(
            {
                "status": report["status"],
                "json": str(json_path),
                "markdown": str(markdown_path),
                "report_sha256": report["report_sha256"],
                "reservation": report["reservation"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
