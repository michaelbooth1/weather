"""Tune-only, cache-derived physical-bandwidth refinement for H1 smoothing.

This command has an intentionally narrow evidence boundary.  It accepts only
the finalized H1 *tune* W0 and W1 caches, proves that applying the production
ordinal smoother to W0 reproduces W1, and then evaluates a predeclared grid of
physically comparable bandwidths.  It has no holdout or fresh-panel arguments,
does not replay snapshots, and writes only compact research evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from weather.model.calibration_runtime import ordinal_smooth_distribution
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.research.current_replay_time_frontier import (
    ReaderStats,
    iter_cache_array,
    read_cache_metadata,
    sha256_stable_file,
)
from weather.reporting.research.ordinal_smoothing_sweep import (
    cluster_bootstrap_ci,
    sign_test,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("ordinal_smoothing_physical_refinement")
H1_SIGMA_NATIVE = 0.75
FIXED_BLEND_WEIGHT = 1.0
# Preregistered before any refinement score was read (2026-07-22).  These are
# physical Celsius-width anchors.  Fahrenheit markets use the exactly
# equivalent native width, sigma_F = 9/5 * sigma_C.
PHYSICAL_C_SIGMA_ANCHORS = (0.25, 0.50, 0.75, 1.00, 1.25)
F_PER_C_SCALE = 1.8
UNITS = ("C", "F")
MASS_TOLERANCE = 1e-9
PARITY_TOLERANCE = 1e-12
LOG_LOSS_EPSILON = 1e-15
BOOTSTRAP_REPLICATES = 10_000
MAX_DATE_FILE_BYTES = 1024 * 1024
MEASURED_TUNE_ARM_MINUTES = 25.0
MEASURED_TUNE_CACHE_BYTES = 2_219_652_377


class ExperimentConfigurationError(ValueError):
    """Raised when a provenance, alignment, or safety gate fails closed."""


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def read_tune_dates(path: str | Path) -> tuple[str, ...]:
    date_path = _resolved(path)
    if not date_path.is_file() or date_path.stat().st_size > MAX_DATE_FILE_BYTES:
        raise ExperimentConfigurationError(f"invalid tune-date manifest: {date_path}")
    values = tuple(
        line.strip()
        for line in date_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not values or len(values) != len(set(values)) or tuple(sorted(values)) != values:
        raise ExperimentConfigurationError(
            "tune-date manifest must be nonempty, unique, and sorted"
        )
    for value in values:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ExperimentConfigurationError(
                f"invalid tune date {value!r}: {date_path}"
            ) from exc
    return values


def validate_path_contract(
    *,
    read_only_data_root: str | Path,
    tune_w0_cache: str | Path,
    tune_w1_cache: str | Path,
    tune_dates_file: str | Path,
    output_root: str | Path,
    json_out: str | Path,
    report_out: str | Path,
    lock_path: str | Path,
) -> dict[str, Path]:
    paths = {
        "read_only_data_root": _resolved(read_only_data_root),
        "tune_w0_cache": _resolved(tune_w0_cache),
        "tune_w1_cache": _resolved(tune_w1_cache),
        "tune_dates_file": _resolved(tune_dates_file),
        "output_root": _resolved(output_root),
        "json_out": _resolved(json_out),
        "report_out": _resolved(report_out),
        "lock_path": _resolved(lock_path),
    }
    if not paths["read_only_data_root"].is_dir():
        raise ExperimentConfigurationError(
            f"read-only data root is not a directory: {paths['read_only_data_root']}"
        )
    for name in ("tune_w0_cache", "tune_w1_cache", "tune_dates_file"):
        if not paths[name].is_file():
            raise ExperimentConfigurationError(f"required input is missing: {paths[name]}")
    if paths["tune_w0_cache"] == paths["tune_w1_cache"]:
        raise ExperimentConfigurationError("W0 and W1 caches must be distinct")
    outputs = (paths["json_out"], paths["report_out"], paths["lock_path"])
    if len(set(outputs)) != len(outputs):
        raise ExperimentConfigurationError("JSON, report, and lock paths must be distinct")
    for path in outputs:
        if not _is_within(path, paths["output_root"]):
            raise ExperimentConfigurationError(
                f"output must remain below the explicit output root: {path}"
            )
        if path in (
            paths["tune_w0_cache"],
            paths["tune_w1_cache"],
            paths["tune_dates_file"],
        ):
            raise ExperimentConfigurationError(f"output aliases an input: {path}")
        if _is_within(path, paths["read_only_data_root"]):
            raise ExperimentConfigurationError(
                f"output resolves inside the read-only data root: {path}"
            )
    return paths


def native_sigma(physical_c_sigma: float, unit: str) -> float:
    unit = str(unit).upper()
    if physical_c_sigma not in PHYSICAL_C_SIGMA_ANCHORS:
        raise ExperimentConfigurationError(
            f"physical sigma is outside the preregistered grid: {physical_c_sigma}"
        )
    if unit == "C":
        return float(physical_c_sigma)
    if unit == "F":
        return float(physical_c_sigma) * F_PER_C_SCALE
    raise ExperimentConfigurationError(f"unsupported settlement unit: {unit!r}")


def distribution_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("market_id"),
        row.get("target_date"),
        row.get("snapshot_id"),
        row.get("captured_at_local"),
    )


def scoring_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return distribution_key(row) + (
        row.get("band"),
        row.get("bin_type"),
        row.get("bin_value_c"),
        row.get("bin_value_hi"),
    )


def scoring_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    fields = ("replayed_p", "outcome", "market_yes", "unit")
    return {name: row.get(name) for name in fields}


def grouped_scoring_rows(
    rows: Iterable[Mapping[str, Any]],
) -> Iterator[tuple[tuple[Any, ...], list[Mapping[str, Any]], int]]:
    """Yield contiguous, deduplicated scoring rows for each distribution key."""

    current_key: tuple[Any, ...] | None = None
    current: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    duplicate_extras = 0
    completed: set[tuple[Any, ...]] = set()
    for row in rows:
        group_key = distribution_key(row)
        if current_key is None:
            current_key = group_key
        elif group_key != current_key:
            completed.add(current_key)
            if group_key in completed:
                raise ExperimentConfigurationError(
                    f"scoring rows are not contiguous for distribution {group_key!r}"
                )
            yield current_key, list(current.values()), duplicate_extras
            current_key = group_key
            current = {}
            duplicate_extras = 0
        key = scoring_key(row)
        previous = current.get(key)
        if previous is not None:
            duplicate_extras += 1
            if scoring_projection(previous) != scoring_projection(row):
                raise ExperimentConfigurationError(
                    f"conflicting duplicate scoring key: {key!r}"
                )
            continue
        current[key] = row
    if current_key is not None:
        yield current_key, list(current.values()), duplicate_extras


def validate_distribution(
    row: Mapping[str, Any], *, tolerance: float = MASS_TOLERANCE
) -> tuple[dict[int, float], float]:
    raw = row.get("distribution") or {}
    if not isinstance(raw, Mapping) or not raw:
        raise ExperimentConfigurationError(
            f"distribution is empty or malformed: {distribution_key(row)!r}"
        )
    parsed: dict[int, float] = {}
    for raw_bucket, raw_probability in raw.items():
        try:
            bucket = int(raw_bucket)
            probability = float(raw_probability)
        except (TypeError, ValueError) as exc:
            raise ExperimentConfigurationError(
                f"invalid distribution value: {distribution_key(row)!r}"
            ) from exc
        if str(bucket) != str(raw_bucket) and raw_bucket != bucket:
            raise ExperimentConfigurationError(
                f"nonintegral distribution bucket {raw_bucket!r}: {distribution_key(row)!r}"
            )
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ExperimentConfigurationError(
                f"invalid distribution probability: {distribution_key(row)!r}"
            )
        if bucket in parsed:
            raise ExperimentConfigurationError(
                f"duplicate normalized distribution bucket {bucket}: {distribution_key(row)!r}"
            )
        parsed[bucket] = probability
    mass_error = abs(sum(parsed.values()) - 1.0)
    if mass_error > tolerance:
        raise ExperimentConfigurationError(
            f"distribution violates simplex tolerance: {distribution_key(row)!r}"
        )
    return dict(sorted(parsed.items())), mass_error


def project_band(distribution: Mapping[int, float], row: Mapping[str, Any]) -> float:
    try:
        threshold = float(row.get("bin_value_c"))
    except (TypeError, ValueError) as exc:
        raise ExperimentConfigurationError(
            f"invalid band threshold: {scoring_key(row)!r}"
        ) from exc
    if not math.isfinite(threshold):
        raise ExperimentConfigurationError(f"nonfinite band threshold: {scoring_key(row)!r}")
    bin_type = str(row.get("bin_type") or "")
    if bin_type == "eq":
        probability = sum(
            value for bucket, value in distribution.items() if float(bucket) == threshold
        )
    elif bin_type == "lte":
        probability = sum(
            value for bucket, value in distribution.items() if float(bucket) <= threshold
        )
    elif bin_type == "gte":
        probability = sum(
            value for bucket, value in distribution.items() if float(bucket) >= threshold
        )
    else:
        raise ExperimentConfigurationError(
            f"unsupported band type {bin_type!r}: {scoring_key(row)!r}"
        )
    if not math.isfinite(probability) or not -PARITY_TOLERANCE <= probability <= 1.0 + PARITY_TOLERANCE:
        raise ExperimentConfigurationError(
            f"projected probability is invalid: {scoring_key(row)!r}"
        )
    return min(1.0, max(0.0, probability))


def audit_transform_parity(
    w0_path: str | Path,
    w1_path: str | Path,
    tune_dates: Sequence[str],
) -> dict[str, Any]:
    """Test cache derivation without opening either cache's outcome rows."""

    w0_path = _resolved(w0_path)
    w1_path = _resolved(w1_path)
    w0_meta = read_cache_metadata(w0_path)
    w1_meta = read_cache_metadata(w1_path)
    blockers = []
    if w0_meta.split != "tune" or w1_meta.split != "tune":
        blockers.append("both cache metadata records must declare split='tune'")
    if w0_meta.weight != 0.0 or w1_meta.weight != 1.0:
        blockers.append("cache weights must be exactly W0=0.0 and W1=1.0")
    if w0_meta.sigma != H1_SIGMA_NATIVE or w1_meta.sigma != H1_SIGMA_NATIVE:
        blockers.append(f"both H1 caches must declare native sigma {H1_SIGMA_NATIVE}")
    if w0_meta.schema_version != w1_meta.schema_version:
        blockers.append("W0 and W1 cache schemas differ")
    if blockers:
        raise ExperimentConfigurationError("; ".join(blockers))

    w0_stats = ReaderStats("distribution_rows", 256 * 1024, 4 * 1024 * 1024)
    w1_stats = ReaderStats("distribution_rows", 256 * 1024, 4 * 1024 * 1024)
    tune_date_set = set(tune_dates)
    observed_dates: set[str] = set()
    distributions = 0
    exact_distribution_mismatches = 0
    distributions_outside_tolerance = 0
    probability_cells_outside_tolerance = 0
    maximum_probability_difference = 0.0
    maximum_l1_difference = 0.0
    l1_sum = 0.0
    maximum_w0_mass_error = 0.0
    maximum_w1_mass_error = 0.0
    maximum_recomputed_mass_error = 0.0
    examples = []
    by_unit = {
        unit: {
            "distributions": 0,
            "outside_tolerance": 0,
            "exact_mismatches": 0,
            "l1_sum": 0.0,
            "maximum_l1": 0.0,
            "maximum_probability_difference": 0.0,
        }
        for unit in UNITS
    }
    sentinel = object()
    for dist0, dist1 in zip_longest(
        iter_cache_array(w0_path, "distribution_rows", stats=w0_stats),
        iter_cache_array(w1_path, "distribution_rows", stats=w1_stats),
        fillvalue=sentinel,
    ):
        if dist0 is sentinel or dist1 is sentinel:
            raise ExperimentConfigurationError("W0/W1 distribution counts differ")
        key = distribution_key(dist0)
        if distribution_key(dist1) != key:
            raise ExperimentConfigurationError(
                f"W0/W1 distribution order or identity differs at {key!r}"
            )
        base, w0_mass_error = validate_distribution(dist0)
        w1, w1_mass_error = validate_distribution(dist1)
        if set(base) != set(w1):
            raise ExperimentConfigurationError(f"W0/W1 bucket grids differ: {key!r}")
        unit = str(dist0.get("unit") or "").upper()
        if unit not in UNITS or str(dist1.get("unit") or "").upper() != unit:
            raise ExperimentConfigurationError(f"invalid or misaligned unit: {key!r}")
        target_date = str(dist0.get("target_date"))
        if target_date not in tune_date_set:
            raise ExperimentConfigurationError(
                f"cache contains a date outside the explicit tune manifest: {target_date}"
            )
        observed_dates.add(target_date)
        recomputed = ordinal_smooth_distribution(
            base, sigma=H1_SIGMA_NATIVE, blend_weight=FIXED_BLEND_WEIGHT
        )
        if set(recomputed) != set(w1):
            raise ExperimentConfigurationError(f"recomputed W1 bucket grid differs: {key!r}")
        recomputed_mass_error = abs(sum(recomputed.values()) - 1.0)
        differences = [abs(float(recomputed[b]) - float(w1[b])) for b in w1]
        cell_mismatches = sum(value > PARITY_TOLERANCE for value in differences)
        exact_mismatch = any(float(recomputed[b]) != float(w1[b]) for b in w1)
        l1 = sum(differences)
        maximum = max(differences, default=0.0)
        outside = bool(cell_mismatches)
        distributions += 1
        exact_distribution_mismatches += int(exact_mismatch)
        distributions_outside_tolerance += int(outside)
        probability_cells_outside_tolerance += cell_mismatches
        maximum_probability_difference = max(maximum_probability_difference, maximum)
        maximum_l1_difference = max(maximum_l1_difference, l1)
        l1_sum += l1
        maximum_w0_mass_error = max(maximum_w0_mass_error, w0_mass_error)
        maximum_w1_mass_error = max(maximum_w1_mass_error, w1_mass_error)
        maximum_recomputed_mass_error = max(
            maximum_recomputed_mass_error, recomputed_mass_error
        )
        unit_row = by_unit[unit]
        unit_row["distributions"] += 1
        unit_row["outside_tolerance"] += int(outside)
        unit_row["exact_mismatches"] += int(exact_mismatch)
        unit_row["l1_sum"] += l1
        unit_row["maximum_l1"] = max(unit_row["maximum_l1"], l1)
        unit_row["maximum_probability_difference"] = max(
            unit_row["maximum_probability_difference"], maximum
        )
        if outside and len(examples) < 20:
            examples.append(
                {
                    "key": list(key),
                    "unit": unit,
                    "maximum_probability_difference": maximum,
                    "l1_difference": l1,
                    "probability_cells_outside_tolerance": cell_mismatches,
                }
            )
    if observed_dates != tune_date_set:
        raise ExperimentConfigurationError(
            "cache dates do not exactly cover the explicit tune manifest"
        )
    final_w0 = read_cache_metadata(w0_path)
    final_w1 = read_cache_metadata(w1_path)
    if final_w0 != w0_meta or final_w1 != w1_meta:
        raise ExperimentConfigurationError("an input cache changed during parity audit")
    for unit, row in by_unit.items():
        count = int(row["distributions"])
        row["mean_l1"] = row.pop("l1_sum") / count if count else None
    status = "PASS" if not distributions_outside_tolerance else "BLOCK"
    return {
        "status": status,
        "outcome_rows_opened": False,
        "tolerance": PARITY_TOLERANCE,
        "distributions": distributions,
        "dates": sorted(observed_dates),
        "exact_distribution_mismatches": exact_distribution_mismatches,
        "distributions_outside_tolerance": distributions_outside_tolerance,
        "probability_cells_outside_tolerance": probability_cells_outside_tolerance,
        "maximum_probability_difference": maximum_probability_difference,
        "mean_l1_difference": l1_sum / distributions if distributions else None,
        "maximum_l1_difference": maximum_l1_difference,
        "maximum_w0_mass_error": maximum_w0_mass_error,
        "maximum_w1_mass_error": maximum_w1_mass_error,
        "maximum_recomputed_mass_error": maximum_recomputed_mass_error,
        "by_unit": by_unit,
        "examples": examples,
        "reader_diagnostics": {
            "w0_distributions": w0_stats.as_dict(),
            "w1_distributions": w1_stats.as_dict(),
        },
        "blockers": (
            []
            if status == "PASS"
            else [
                "applying the production ordinal smoother to final W0 cached "
                "distributions does not reproduce final W1 cached distributions"
            ]
        ),
    }


def _brier(probability: float, outcome: int) -> float:
    return (float(probability) - int(outcome)) ** 2


def _logloss(probability: float, outcome: int) -> float:
    p = max(LOG_LOSS_EPSILON, min(1.0 - LOG_LOSS_EPSILON, float(probability)))
    return -(int(outcome) * math.log(p) + (1 - int(outcome)) * math.log(1.0 - p))


@dataclass
class DailyAccumulator:
    rows: int = 0
    markets: set[str] = field(default_factory=set)
    baseline_brier: float = 0.0
    candidate_brier: float = 0.0
    w1_brier: float = 0.0
    market_brier: float = 0.0
    baseline_logloss: float = 0.0
    candidate_logloss: float = 0.0
    w1_logloss: float = 0.0
    market_logloss: float = 0.0

    def add(
        self,
        *,
        market_id: str,
        outcome: int,
        baseline_p: float,
        candidate_p: float,
        w1_p: float,
        market_p: float,
    ) -> None:
        self.rows += 1
        self.markets.add(market_id)
        self.baseline_brier += _brier(baseline_p, outcome)
        self.candidate_brier += _brier(candidate_p, outcome)
        self.w1_brier += _brier(w1_p, outcome)
        self.market_brier += _brier(market_p, outcome)
        self.baseline_logloss += _logloss(baseline_p, outcome)
        self.candidate_logloss += _logloss(candidate_p, outcome)
        self.w1_logloss += _logloss(w1_p, outcome)
        self.market_logloss += _logloss(market_p, outcome)

    def finalize(self, target_date: str) -> dict[str, Any]:
        if self.rows <= 0:
            raise ExperimentConfigurationError("cannot finalize an empty daily aggregate")
        n = self.rows
        baseline_brier = self.baseline_brier / n
        candidate_brier = self.candidate_brier / n
        w1_brier = self.w1_brier / n
        market_brier = self.market_brier / n
        baseline_logloss = self.baseline_logloss / n
        candidate_logloss = self.candidate_logloss / n
        w1_logloss = self.w1_logloss / n
        market_logloss = self.market_logloss / n
        return {
            "target_date": target_date,
            "rows": n,
            "markets": len(self.markets),
            "baseline_brier": baseline_brier,
            "candidate_brier": candidate_brier,
            "w1_brier": w1_brier,
            "market_brier": market_brier,
            "brier_delta_vs_w0": candidate_brier - baseline_brier,
            "brier_delta_vs_w1": candidate_brier - w1_brier,
            "candidate_brier_delta_vs_market": candidate_brier - market_brier,
            "baseline_logloss": baseline_logloss,
            "candidate_logloss": candidate_logloss,
            "w1_logloss": w1_logloss,
            "market_logloss": market_logloss,
            "logloss_delta_vs_w0": candidate_logloss - baseline_logloss,
            "logloss_delta_vs_w1": candidate_logloss - w1_logloss,
            "candidate_logloss_delta_vs_market": candidate_logloss - market_logloss,
        }


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def summarize_anchor(
    daily: Sequence[dict[str, Any]], *, unit: str, physical_c_sigma: float
) -> dict[str, Any]:
    brier_w0 = [row["brier_delta_vs_w0"] for row in daily]
    logloss_w0 = [row["logloss_delta_vs_w0"] for row in daily]
    brier_w1 = [row["brier_delta_vs_w1"] for row in daily]
    logloss_w1 = [row["logloss_delta_vs_w1"] for row in daily]
    seed_prefix = f"physical-refinement|{unit}|{physical_c_sigma:.8f}"

    def seed(metric: str) -> int:
        return 20260722 + int.from_bytes(
            hashlib.sha256(f"{seed_prefix}|{metric}".encode("utf-8")).digest()[:4],
            "big",
        )

    return {
        "unit": unit,
        "physical_c_sigma": physical_c_sigma,
        "native_sigma": native_sigma(physical_c_sigma, unit),
        "blend_weight": FIXED_BLEND_WEIGHT,
        "fleet_dates": len(daily),
        "scoring_rows": sum(row["rows"] for row in daily),
        "mean_brier_delta_vs_w0": _mean(brier_w0),
        "mean_logloss_delta_vs_w0": _mean(logloss_w0),
        "mean_brier_delta_vs_w1": _mean(brier_w1),
        "mean_logloss_delta_vs_w1": _mean(logloss_w1),
        "mean_candidate_brier_delta_vs_market": _mean(
            row["candidate_brier_delta_vs_market"] for row in daily
        ),
        "mean_candidate_logloss_delta_vs_market": _mean(
            row["candidate_logloss_delta_vs_market"] for row in daily
        ),
        "brier_vs_w0_cluster_bootstrap_95ci": cluster_bootstrap_ci(
            brier_w0, seed=seed("brier-w0"), replicates=BOOTSTRAP_REPLICATES
        ),
        "logloss_vs_w0_cluster_bootstrap_95ci": cluster_bootstrap_ci(
            logloss_w0, seed=seed("logloss-w0"), replicates=BOOTSTRAP_REPLICATES
        ),
        "brier_vs_w1_cluster_bootstrap_95ci": cluster_bootstrap_ci(
            brier_w1, seed=seed("brier-w1"), replicates=BOOTSTRAP_REPLICATES
        ),
        "logloss_vs_w1_cluster_bootstrap_95ci": cluster_bootstrap_ci(
            logloss_w1, seed=seed("logloss-w1"), replicates=BOOTSTRAP_REPLICATES
        ),
        "brier_vs_w0_sign_test": sign_test(brier_w0),
        "logloss_vs_w0_sign_test": sign_test(logloss_w0),
        "daily": list(daily),
    }


def select_family_sigmas(
    summaries: Mapping[str, Sequence[Mapping[str, Any]]]
) -> tuple[dict[str, float], dict[str, Any]]:
    selected: dict[str, float] = {}
    details: dict[str, Any] = {}
    for unit in UNITS:
        candidates = list(summaries.get(unit) or [])
        eligible = [
            row
            for row in candidates
            if row.get("mean_brier_delta_vs_w0") is not None
            and row.get("mean_logloss_delta_vs_w0") is not None
            and float(row["mean_brier_delta_vs_w0"]) < 0.0
            and float(row["mean_logloss_delta_vs_w0"]) < 0.0
        ]
        eligible.sort(
            key=lambda row: (
                float(row["mean_brier_delta_vs_w0"]),
                float(row["mean_logloss_delta_vs_w0"]),
                float(row["physical_c_sigma"]),
            )
        )
        if not eligible:
            details[unit] = {
                "status": "NO_ELIGIBLE_ANCHOR",
                "eligible_physical_c_sigmas": [],
                "rule": "negative tune mean paired Brier and log-loss deltas vs W0",
            }
            continue
        winner = eligible[0]
        physical = float(winner["physical_c_sigma"])
        selected[unit] = physical
        details[unit] = {
            "status": "SELECTED",
            "selected_physical_c_sigma": physical,
            "selected_native_sigma": native_sigma(physical, unit),
            "eligible_physical_c_sigmas": [
                float(row["physical_c_sigma"]) for row in eligible
            ],
            "rule": (
                "require negative tune mean paired Brier and log-loss deltas vs W0; "
                "rank by Brier, log-loss, then smaller physical-C sigma"
            ),
        }
    return selected, details


def evaluate_cache_pair(
    w0_path: str | Path,
    w1_path: str | Path,
    tune_dates: Sequence[str],
) -> dict[str, Any]:
    """Stream, align, validate, and score the two immutable tune caches."""

    w0_path = _resolved(w0_path)
    w1_path = _resolved(w1_path)
    w0_meta = read_cache_metadata(w0_path)
    w1_meta = read_cache_metadata(w1_path)
    blockers = []
    if w0_meta.split != "tune" or w1_meta.split != "tune":
        blockers.append("both cache metadata records must declare split='tune'")
    if w0_meta.weight != 0.0 or w1_meta.weight != 1.0:
        blockers.append("cache weights must be exactly W0=0.0 and W1=1.0")
    if w0_meta.sigma != H1_SIGMA_NATIVE or w1_meta.sigma != H1_SIGMA_NATIVE:
        blockers.append(f"both H1 caches must declare native sigma {H1_SIGMA_NATIVE}")
    if w0_meta.schema_version != w1_meta.schema_version:
        blockers.append("W0 and W1 cache schemas differ")
    if blockers:
        raise ExperimentConfigurationError("; ".join(blockers))

    dist0_stats = ReaderStats("distribution_rows", 256 * 1024, 4 * 1024 * 1024)
    dist1_stats = ReaderStats("distribution_rows", 256 * 1024, 4 * 1024 * 1024)
    rows0_stats = ReaderStats("rows", 256 * 1024, 4 * 1024 * 1024)
    rows1_stats = ReaderStats("rows", 256 * 1024, 4 * 1024 * 1024)
    dist0_iter = iter_cache_array(w0_path, "distribution_rows", stats=dist0_stats)
    dist1_iter = iter_cache_array(w1_path, "distribution_rows", stats=dist1_stats)
    rows0_iter = grouped_scoring_rows(iter_cache_array(w0_path, "rows", stats=rows0_stats))
    rows1_iter = grouped_scoring_rows(iter_cache_array(w1_path, "rows", stats=rows1_stats))

    aggregates: dict[float, dict[str, dict[str, DailyAccumulator]]] = {
        anchor: {unit: defaultdict(DailyAccumulator) for unit in UNITS}
        for anchor in PHYSICAL_C_SIGMA_ANCHORS
    }
    tune_date_set = set(tune_dates)
    observed_dates: set[str] = set()
    distributions = 0
    unique_scoring_rows = 0
    raw_scoring_rows = 0
    duplicate_extras = 0
    maximum_base_mass_error = 0.0
    maximum_w1_mass_error = 0.0
    maximum_candidate_mass_error = 0.0
    maximum_w1_probability_difference = 0.0
    w1_probability_mismatches = 0
    w1_exact_distribution_mismatches = 0
    maximum_w0_projection_difference = 0.0
    maximum_w1_projection_difference = 0.0
    maximum_recomputed_w1_projection_difference = 0.0
    projection_mismatches = 0
    effect_l1_sum = {anchor: {unit: 0.0 for unit in UNITS} for anchor in PHYSICAL_C_SIGMA_ANCHORS}
    effect_count = {anchor: {unit: 0 for unit in UNITS} for anchor in PHYSICAL_C_SIGMA_ANCHORS}

    sentinel = object()
    streams = zip_longest(
        dist0_iter, dist1_iter, rows0_iter, rows1_iter, fillvalue=sentinel
    )
    for dist0, dist1, group0, group1 in streams:
        if sentinel in (dist0, dist1, group0, group1):
            raise ExperimentConfigurationError("W0/W1 distribution or row-group counts differ")
        key0 = distribution_key(dist0)
        if distribution_key(dist1) != key0 or group0[0] != key0 or group1[0] != key0:
            raise ExperimentConfigurationError(
                f"W0/W1 distribution and scoring-group order differs at {key0!r}"
            )
        base, base_mass_error = validate_distribution(dist0)
        w1, w1_mass_error = validate_distribution(dist1)
        recomputed_w1 = ordinal_smooth_distribution(
            base, sigma=H1_SIGMA_NATIVE, blend_weight=FIXED_BLEND_WEIGHT
        )
        if set(base) != set(w1) or set(recomputed_w1) != set(w1):
            raise ExperimentConfigurationError(f"W1 distribution bucket grid differs: {key0!r}")
        distribution_exact = True
        for bucket in w1:
            difference = abs(float(recomputed_w1[bucket]) - float(w1[bucket]))
            maximum_w1_probability_difference = max(
                maximum_w1_probability_difference, difference
            )
            if difference > PARITY_TOLERANCE:
                w1_probability_mismatches += 1
            if float(recomputed_w1[bucket]) != float(w1[bucket]):
                distribution_exact = False
        if not distribution_exact:
            w1_exact_distribution_mismatches += 1
        if w1_probability_mismatches:
            raise ExperimentConfigurationError(
                "production smoother does not reproduce the W1 cache within tolerance"
            )

        unit = str(dist0.get("unit") or "").upper()
        if unit not in UNITS or str(dist1.get("unit") or "").upper() != unit:
            raise ExperimentConfigurationError(f"invalid or misaligned unit: {key0!r}")
        target_date = str(dist0.get("target_date"))
        if target_date not in tune_date_set:
            raise ExperimentConfigurationError(
                f"cache contains a date outside the explicit tune manifest: {target_date}"
            )
        observed_dates.add(target_date)
        candidates = {}
        for anchor in PHYSICAL_C_SIGMA_ANCHORS:
            candidate = ordinal_smooth_distribution(
                base,
                sigma=native_sigma(anchor, unit),
                blend_weight=FIXED_BLEND_WEIGHT,
            )
            candidate_mass_error = abs(sum(candidate.values()) - 1.0)
            maximum_candidate_mass_error = max(
                maximum_candidate_mass_error, candidate_mass_error
            )
            if candidate_mass_error > MASS_TOLERANCE or set(candidate) != set(base):
                raise ExperimentConfigurationError(
                    f"candidate distribution gate failed: {key0!r}, anchor={anchor}"
                )
            candidates[anchor] = candidate
            effect_l1_sum[anchor][unit] += sum(
                abs(candidate[bucket] - base[bucket]) for bucket in base
            )
            effect_count[anchor][unit] += 1

        rows0 = {scoring_key(row): row for row in group0[1]}
        rows1 = {scoring_key(row): row for row in group1[1]}
        if set(rows0) != set(rows1):
            raise ExperimentConfigurationError(f"W0/W1 scoring keys differ: {key0!r}")
        duplicate_extras += int(group0[2])
        raw_scoring_rows += len(group0[1]) + int(group0[2])
        if int(group0[2]) != int(group1[2]):
            raise ExperimentConfigurationError(f"W0/W1 duplicate counts differ: {key0!r}")
        for row_key in rows0:
            row0 = rows0[row_key]
            row1 = rows1[row_key]
            if any(
                row0.get(name) != row1.get(name)
                for name in ("outcome", "market_yes", "unit")
            ):
                raise ExperimentConfigurationError(f"W0/W1 scoring labels differ: {row_key!r}")
            try:
                outcome = int(row0["outcome"])
                baseline_p = float(row0["replayed_p"])
                w1_p = float(row1["replayed_p"])
                market_p = float(row0["market_yes"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ExperimentConfigurationError(
                    f"invalid scoring value: {row_key!r}"
                ) from exc
            if outcome not in (0, 1):
                raise ExperimentConfigurationError(f"invalid outcome: {row_key!r}")
            projected_w0 = project_band(base, row0)
            projected_w1 = project_band(w1, row1)
            projected_recomputed_w1 = project_band(recomputed_w1, row0)
            w0_difference = abs(projected_w0 - baseline_p)
            w1_difference = abs(projected_w1 - w1_p)
            recomputed_difference = abs(projected_recomputed_w1 - w1_p)
            maximum_w0_projection_difference = max(
                maximum_w0_projection_difference, w0_difference
            )
            maximum_w1_projection_difference = max(
                maximum_w1_projection_difference, w1_difference
            )
            maximum_recomputed_w1_projection_difference = max(
                maximum_recomputed_w1_projection_difference, recomputed_difference
            )
            if max(w0_difference, w1_difference, recomputed_difference) > PARITY_TOLERANCE:
                projection_mismatches += 1
                raise ExperimentConfigurationError(
                    f"distribution-to-band projection does not reproduce cache rows: {row_key!r}"
                )
            for anchor, candidate in candidates.items():
                aggregates[anchor][unit][target_date].add(
                    market_id=str(row0.get("market_id")),
                    outcome=outcome,
                    baseline_p=baseline_p,
                    candidate_p=project_band(candidate, row0),
                    w1_p=w1_p,
                    market_p=market_p,
                )
            unique_scoring_rows += 1

        distributions += 1
        maximum_base_mass_error = max(maximum_base_mass_error, base_mass_error)
        maximum_w1_mass_error = max(maximum_w1_mass_error, w1_mass_error)

    if observed_dates != tune_date_set:
        raise ExperimentConfigurationError(
            "cache dates do not exactly cover the explicit tune manifest"
        )
    summaries: dict[str, list[dict[str, Any]]] = {unit: [] for unit in UNITS}
    for unit in UNITS:
        for anchor in PHYSICAL_C_SIGMA_ANCHORS:
            daily = [
                accumulator.finalize(target_date)
                for target_date, accumulator in sorted(aggregates[anchor][unit].items())
            ]
            summaries[unit].append(
                summarize_anchor(daily, unit=unit, physical_c_sigma=anchor)
            )
    selected, selection_details = select_family_sigmas(summaries)
    if set(selected) != set(UNITS):
        raise ExperimentConfigurationError(
            "at least one family has no tune-eligible physical-bandwidth anchor"
        )
    final_w0_meta = read_cache_metadata(w0_path)
    final_w1_meta = read_cache_metadata(w1_path)
    if final_w0_meta != w0_meta or final_w1_meta != w1_meta:
        raise ExperimentConfigurationError("an input cache changed during evaluation")
    return {
        "status": "PASS",
        "blockers": [],
        "cache_metadata": {"w0": w0_meta.as_dict(), "w1": w1_meta.as_dict()},
        "reader_diagnostics": {
            "w0_distributions": dist0_stats.as_dict(),
            "w1_distributions": dist1_stats.as_dict(),
            "w0_rows": rows0_stats.as_dict(),
            "w1_rows": rows1_stats.as_dict(),
        },
        "alignment_and_parity": {
            "distributions": distributions,
            "raw_scoring_rows": raw_scoring_rows,
            "unique_scoring_rows": unique_scoring_rows,
            "equivalent_duplicate_extras": duplicate_extras,
            "dates": sorted(observed_dates),
            "maximum_w0_mass_error": maximum_base_mass_error,
            "maximum_w1_mass_error": maximum_w1_mass_error,
            "maximum_candidate_mass_error": maximum_candidate_mass_error,
            "parity_tolerance": PARITY_TOLERANCE,
            "w1_probability_mismatches": w1_probability_mismatches,
            "w1_exact_distribution_mismatches": w1_exact_distribution_mismatches,
            "maximum_w1_probability_difference": maximum_w1_probability_difference,
            "projection_mismatches": projection_mismatches,
            "maximum_w0_projection_difference": maximum_w0_projection_difference,
            "maximum_w1_projection_difference": maximum_w1_projection_difference,
            "maximum_recomputed_w1_projection_difference": (
                maximum_recomputed_w1_projection_difference
            ),
        },
        "scope_effect": {
            str(anchor): {
                unit: {
                    "distributions": effect_count[anchor][unit],
                    "mean_l1_vs_w0": (
                        effect_l1_sum[anchor][unit] / effect_count[anchor][unit]
                        if effect_count[anchor][unit]
                        else None
                    ),
                }
                for unit in UNITS
            }
            for anchor in PHYSICAL_C_SIGMA_ANCHORS
        },
        "summaries": summaries,
        "selection": selection_details,
        "selected_physical_c_sigmas": selected,
    }


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ExperimentConfigurationError(f"research lock already exists: {path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "pid": os.getpid(),
                    "started_at_utc": datetime.now(timezone.utc).isoformat(),
                    "schema_version": SCHEMA_VERSION,
                },
                handle,
                sort_keys=True,
            )
            handle.write("\n")
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def render_report(payload: Mapping[str, Any]) -> str:
    transform = payload.get("cache_transform_parity") or {}
    parity = payload.get("alignment_and_parity") or {}
    frozen = payload.get("frozen_candidate") or {}
    blocked = payload.get("status") == "BLOCK"
    lines = [
        "# H1 Physical-Bandwidth Refinement (Tune Only)",
        "",
        "This bounded follow-up reuses only the original H1 tune W0/W1 caches. "
        "It does not open or score an H1 holdout or later fresh panel, does not replay "
        "snapshots, and does not alter serving.",
        "",
        "## Result",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Status", payload.get("status")],
                ["Disposition", payload.get("disposition")],
                ["Tune dates", len((payload.get("experiment") or {}).get("tune_dates") or [])],
                ["Distributions", transform.get("distributions", parity.get("distributions"))],
                ["Outcome rows opened", transform.get("outcome_rows_opened")],
                ["Unique scoring rows", parity.get("unique_scoring_rows")],
                ["W0->W1 max probability difference", fmt_num(transform.get("maximum_probability_difference", parity.get("maximum_w1_probability_difference")))],
                ["Distributions outside 1e-12", transform.get("distributions_outside_tolerance")],
                ["Projection mismatches", parity.get("projection_mismatches")],
                ["Frozen C native sigma", (frozen.get("native_sigma_by_family") or {}).get("C")],
                ["Frozen F native sigma", (frozen.get("native_sigma_by_family") or {}).get("F")],
                ["Blend weight", frozen.get("blend_weight")],
            ],
        ),
        "",
        "## Preregistered Contract",
        "",
        f"Physical-C anchors were fixed before scoring: {', '.join(map(str, PHYSICAL_C_SIGMA_ANCHORS))}. "
        "For each anchor x, C markets use sigma=x and F markets use sigma=1.8*x; "
        "blend weight is fixed at 1.0. Families are selected independently on tune "
        "only, requiring negative mean paired Brier and log-loss deltas versus W0, "
        "then ranking by Brier, log-loss, and smaller physical sigma.",
        "",
    ]
    if blocked:
        cost = payload.get("replay_cost") or {}
        lines.extend(
            [
                "## Exact Blocker",
                "",
                "The cache shortcut is invalid. Applying the exact production ordinal "
                "smoother to each final W0 cached distribution does not reproduce the "
                "corresponding final W1 cached distribution. The audit completed across "
                "all tune distributions before any outcome-row array was opened.",
                "",
                *markdown_table(
                    ["Unit", "Distributions", "Outside tolerance", "Exact mismatch", "Mean L1", "Max L1", "Max cell difference"],
                    [
                        [
                            unit,
                            ((transform.get("by_unit") or {}).get(unit) or {}).get("distributions"),
                            ((transform.get("by_unit") or {}).get(unit) or {}).get("outside_tolerance"),
                            ((transform.get("by_unit") or {}).get(unit) or {}).get("exact_mismatches"),
                            fmt_num(((transform.get("by_unit") or {}).get(unit) or {}).get("mean_l1")),
                            fmt_num(((transform.get("by_unit") or {}).get(unit) or {}).get("maximum_l1")),
                            fmt_num(((transform.get("by_unit") or {}).get(unit) or {}).get("maximum_probability_difference")),
                        ]
                        for unit in UNITS
                    ],
                ),
                "",
                "The reason is pipeline order: ordinal smoothing is applied to the "
                "feature-model distribution before feature blending and later live-signal, "
                "hard-floor, tail, and plausible-cap stages. The cache records the final "
                "distribution, so smoothing that final W0 object is not algebraically "
                "equivalent to rerunning the pipeline with smoothing enabled.",
                "",
                "## Exact Replay Cost",
                "",
                *markdown_table(
                    ["Field", "Value"],
                    [
                        ["Preregistered candidate arms", cost.get("candidate_arms")],
                        ["Measured minutes per tune arm", cost.get("measured_minutes_per_arm")],
                        ["Estimated replay minutes", cost.get("estimated_minutes")],
                        ["Measured bytes per tune cache", cost.get("measured_bytes_per_arm")],
                        ["Estimated cache bytes", cost.get("estimated_cache_bytes")],
                        ["Estimated cache GiB", fmt_num(cost.get("estimated_cache_gib"))],
                        ["Replay status", cost.get("status")],
                    ],
                ),
                "",
                "No sigma score was computed and no candidate was frozen. A valid follow-up "
                "requires five new family-aware tune replays at the preregistered anchors, "
                "then one future confirmation of the tune-selected pair. That replay was "
                "not authorized or started in this bounded follow-up.",
                "",
                "## Safety and Interpretation",
                "",
                "The original H1 holdout and all fresh-panel caches remained unopened. "
                "No outcome rows were opened by the completed parity audit, no snapshot "
                "replay ran, and no data, release, promotion, trading, or serving state was "
                "changed.",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(["## Tune Results", ""])
    result_rows = []
    for unit in UNITS:
        selected = (payload.get("selected_physical_c_sigmas") or {}).get(unit)
        for row in (payload.get("summaries") or {}).get(unit) or []:
            result_rows.append(
                [
                    unit,
                    row.get("physical_c_sigma"),
                    row.get("native_sigma"),
                    row.get("fleet_dates"),
                    fmt_signed(row.get("mean_brier_delta_vs_w0")),
                    fmt_signed(row.get("mean_logloss_delta_vs_w0")),
                    fmt_signed(row.get("mean_brier_delta_vs_w1")),
                    fmt_signed(row.get("mean_logloss_delta_vs_w1")),
                    fmt_signed(row.get("mean_candidate_brier_delta_vs_market")),
                    "yes" if row.get("physical_c_sigma") == selected else "",
                ]
            )
    lines.extend(
        markdown_table(
            [
                "Unit",
                "Physical C sigma",
                "Native sigma",
                "Dates",
                "Brier vs W0",
                "Log-loss vs W0",
                "Brier vs W1",
                "Log-loss vs W1",
                "Brier vs market",
                "Frozen",
            ],
            result_rows,
        )
    )
    lines.extend(
        [
            "",
            "## Safety and Interpretation",
            "",
            "The selected family-aware pair is frozen only for a future, separately "
            "authorized confirmation. Tune evidence is not holdout support, is not a "
            "promotion decision, and is not evidence of market edge. No release or "
            "serving artifact was written.",
            "",
            "All per-date paired metrics and cluster-bootstrap intervals are retained "
            "in the adjacent JSON evidence file.",
            "",
        ]
    )
    return "\n".join(lines)


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    paths = validate_path_contract(
        read_only_data_root=args.read_only_data_root,
        tune_w0_cache=args.tune_w0_cache,
        tune_w1_cache=args.tune_w1_cache,
        tune_dates_file=args.tune_dates_file,
        output_root=args.output_root,
        json_out=args.json_out,
        report_out=args.report_out,
        lock_path=args.lock_path,
    )
    for path in (paths["json_out"], paths["report_out"]):
        if path.exists():
            raise ExperimentConfigurationError(f"refusing to overwrite output: {path}")
    tune_dates = read_tune_dates(paths["tune_dates_file"])
    date_stat = paths["tune_dates_file"].stat()
    date_hash = sha256_stable_file(
        paths["tune_dates_file"],
        expected_size_bytes=date_stat.st_size,
        expected_mtime_ns=date_stat.st_mtime_ns,
    )
    with exclusive_lock(paths["lock_path"]):
        transform_parity = audit_transform_parity(
            paths["tune_w0_cache"], paths["tune_w1_cache"], tune_dates
        )
        cache_metadata = {
            "w0": read_cache_metadata(paths["tune_w0_cache"]).as_dict(),
            "w1": read_cache_metadata(paths["tune_w1_cache"]).as_dict(),
        }
        for label, path in (
            ("w0", paths["tune_w0_cache"]),
            ("w1", paths["tune_w1_cache"]),
        ):
            metadata = cache_metadata[label]
            metadata["sha256"] = sha256_stable_file(
                path,
                expected_size_bytes=int(metadata["size_bytes"]),
                expected_mtime_ns=int(metadata["mtime_ns"]),
            )
        experiment = {
            "hypothesis": "H1 bandwidth should be physically comparable across unit families",
            "swept_variable": "physical_c_ordinal_smoothing_sigma",
            "physical_c_sigma_anchors": list(PHYSICAL_C_SIGMA_ANCHORS),
            "native_mapping": {"C": "x", "F": "1.8*x"},
            "blend_weight": FIXED_BLEND_WEIGHT,
            "selection_uses_tune_only": True,
            "selection_rule": (
                "negative mean paired Brier and log-loss deltas vs W0; rank by "
                "Brier, log-loss, then smaller physical-C sigma"
            ),
            "tune_dates": list(tune_dates),
            "tune_dates_path": str(paths["tune_dates_file"]),
            "tune_dates_sha256": date_hash,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        }
        if transform_parity["status"] != "PASS":
            candidate_arms = len(PHYSICAL_C_SIGMA_ANCHORS)
            replay_bytes = candidate_arms * MEASURED_TUNE_CACHE_BYTES
            payload = {
                "schema_version": SCHEMA_VERSION,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "status": "BLOCK",
                "disposition": "REPLAY_REQUIRED_CACHE_TRANSFORM_INVALID",
                "research_only": True,
                "promotion_authorized": False,
                "holdout_opened": False,
                "fresh_panel_opened": False,
                "outcome_rows_opened": False,
                "replay_run": False,
                "serving_changed": False,
                "technical_blockers": list(transform_parity.get("blockers") or []),
                "experiment": experiment,
                "inputs": {"cache_metadata": cache_metadata},
                "cache_transform_parity": transform_parity,
                "replay_cost": {
                    "status": "NOT_RUN_NOT_AUTHORIZED",
                    "candidate_arms": candidate_arms,
                    "measured_minutes_per_arm": MEASURED_TUNE_ARM_MINUTES,
                    "estimated_minutes": candidate_arms * MEASURED_TUNE_ARM_MINUTES,
                    "measured_bytes_per_arm": MEASURED_TUNE_CACHE_BYTES,
                    "estimated_cache_bytes": replay_bytes,
                    "estimated_cache_gib": replay_bytes / (1024**3),
                    "basis": (
                        "measured H1 tune-arm runtime/cache size from the outcome-blind "
                        "fresh-confirmation feasibility audit"
                    ),
                    "implementation_required": (
                        "family-aware feature-stage sigma injection and five new tune replays"
                    ),
                },
                "summaries": {"C": [], "F": []},
                "selection": {"status": "NOT_RUN"},
                "selected_physical_c_sigmas": {},
                "frozen_candidate": {
                    "status": "NOT_FROZEN",
                    "reason": "cache-transform parity failed before outcome scoring",
                    "confirmation_run": False,
                    "promotion_authorized": False,
                },
            }
            _atomic_write(
                paths["json_out"], json.dumps(payload, indent=2, sort_keys=True) + "\n"
            )
            _atomic_write(paths["report_out"], render_report(payload))
            return payload

        evaluation = evaluate_cache_pair(
            paths["tune_w0_cache"], paths["tune_w1_cache"], tune_dates
        )
        evaluation["cache_metadata"] = cache_metadata
        selected = evaluation["selected_physical_c_sigmas"]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "COMPLETE",
            "disposition": "FROZEN_TUNE_ONLY_FOR_FUTURE_CONFIRMATION",
            "research_only": True,
            "promotion_authorized": False,
            "holdout_opened": False,
            "fresh_panel_opened": False,
            "replay_run": False,
            "serving_changed": False,
            "experiment": experiment,
            **evaluation,
            "cache_transform_parity": transform_parity,
            "frozen_candidate": {
                "status": "FROZEN_FOR_FUTURE_CONFIRMATION",
                "physical_c_sigma_by_family": selected,
                "native_sigma_by_family": {
                    unit: native_sigma(selected[unit], unit) for unit in UNITS
                },
                "blend_weight": FIXED_BLEND_WEIGHT,
                "selection_uses_tune_only": True,
                "confirmation_run": False,
                "promotion_authorized": False,
            },
        }
        # Preserve the top-level completion status after expanding evaluation.
        payload["status"] = "COMPLETE"
        payload["blockers"] = []
        _atomic_write(
            paths["json_out"], json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
        _atomic_write(paths["report_out"], render_report(payload))
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Tune-only cache-derived physical-unit refinement for H1 ordinal smoothing."
        )
    )
    parser.add_argument("--tune-w0-cache", required=True)
    parser.add_argument("--tune-w1-cache", required=True)
    parser.add_argument("--tune-dates-file", required=True)
    parser.add_argument("--read-only-data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--lock-path", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        payload = run_experiment(build_parser().parse_args(argv))
    except ExperimentConfigurationError as exc:
        print(f"physical smoothing refinement blocked: {exc}", file=sys.stderr)
        return 2
    if payload.get("status") == "BLOCK":
        parity = payload.get("cache_transform_parity") or {}
        print(
            "physical smoothing refinement blocked: cache transform invalid; "
            f"outside_tolerance={parity.get('distributions_outside_tolerance')}",
            file=sys.stderr,
        )
        return 2
    frozen = payload.get("frozen_candidate") or {}
    print(
        "physical smoothing refinement complete: "
        f"C={((frozen.get('native_sigma_by_family') or {}).get('C'))} "
        f"F={((frozen.get('native_sigma_by_family') or {}).get('F'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
