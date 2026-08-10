"""Coverage calibration for the sealed -09-44a crossed-bootstrap panel.

This is a hash-bound, one-off research harness.  It reads only squared-error
columns from the retained pre-boundary paired field and writes only to a
declared scratch directory.  The design and seeds are frozen in the companion
09-62a predeclaration JSON before any coverage result is generated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd


NORMAL = NormalDist()
READ_COLUMNS = [
    "target_date",
    "stratum",
    "market_id",
    "market_squared_error",
    "control_squared_error",
    "repair_squared_error",
]


@dataclass(frozen=True)
class Endpoint:
    key: str
    dates: tuple[str, ...]
    markets: tuple[str, ...]
    counts: np.ndarray
    denominator: np.ndarray
    variance_components: dict[str, Any]

    @property
    def date_clusters(self) -> int:
        return len(self.dates)

    @property
    def market_clusters(self) -> int:
        return len(self.markets)

    @property
    def rows(self) -> int:
        return int(self.counts.sum())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def projection_sse(xtx: np.ndarray, xty: np.ndarray, yty: float) -> tuple[float, int]:
    rank = int(np.linalg.matrix_rank(xtx))
    fitted_ss = float(xty @ np.linalg.pinv(xtx, hermitian=True) @ xty)
    return max(0.0, float(yty - fitted_ss)), rank


def henderson_components(cells: pd.DataFrame, dates: tuple[str, ...], markets: tuple[str, ...]) -> dict[str, Any]:
    """Estimate unbalanced additive random-effect variances by Henderson method 3."""

    d_index = {value: index for index, value in enumerate(dates)}
    m_index = {value: index for index, value in enumerate(markets)}
    d_count = np.zeros(len(dates), dtype=float)
    m_count = np.zeros(len(markets), dtype=float)
    dm_count = np.zeros((len(dates), len(markets)), dtype=float)
    d_sum = np.zeros(len(dates), dtype=float)
    m_sum = np.zeros(len(markets), dtype=float)

    for row in cells.itertuples(index=False):
        d = d_index[row.target_date]
        m = m_index[row.market_id]
        n = float(row.row_count)
        value_sum = float(row.delta_sum)
        d_count[d] += n
        m_count[m] += n
        dm_count[d, m] += n
        d_sum[d] += value_sum
        m_sum[m] += value_sum

    total_rows = float(d_count.sum())
    total_sum = float(d_sum.sum())
    yty = float(cells["delta_sum_sq"].sum())

    full_xtx = np.block(
        [
            [np.diag(d_count), dm_count],
            [dm_count.T, np.diag(m_count)],
        ]
    )
    full_xty = np.concatenate([d_sum, m_sum])
    full_sse, full_rank = projection_sse(full_xtx, full_xty, yty)
    date_sse, date_rank = projection_sse(np.diag(d_count), d_sum, yty)
    market_sse, market_rank = projection_sse(np.diag(m_count), m_sum, yty)

    residual_df = int(total_rows) - full_rank
    if residual_df <= 0:
        raise RuntimeError("non-positive residual degrees of freedom")
    residual_variance = full_sse / residual_df

    # Date after market and market after date.  The coefficient of a random
    # effect is tr[Z'(P_full-P_reduced)Z].  P_full contains Z exactly, so its
    # contribution is N and only the reduced projection trace is needed.
    market_inv = np.diag(1.0 / m_count)
    date_inv = np.diag(1.0 / d_count)
    date_projection_trace = float(np.trace(dm_count.T @ dm_count @ market_inv))
    market_projection_trace = float(np.trace(dm_count @ dm_count.T @ date_inv))
    date_coefficient = total_rows - date_projection_trace
    market_coefficient = total_rows - market_projection_trace
    date_df = full_rank - market_rank
    market_df = full_rank - date_rank
    date_ss = market_sse - full_sse
    market_ss = date_sse - full_sse
    raw_date_variance = (date_ss - date_df * residual_variance) / date_coefficient
    raw_market_variance = (market_ss - market_df * residual_variance) / market_coefficient
    date_variance = max(0.0, raw_date_variance)
    market_variance = max(0.0, raw_market_variance)
    total_variance = date_variance + market_variance + residual_variance

    return {
        "observed_field_mean": total_sum / total_rows,
        "method": "Henderson method 3, unbalanced additive date + market model",
        "full_rank": full_rank,
        "residual_degrees_of_freedom": residual_df,
        "date_degrees_of_freedom": date_df,
        "market_degrees_of_freedom": market_df,
        "date_coefficient": date_coefficient,
        "market_coefficient": market_coefficient,
        "raw_variances": {
            "date": raw_date_variance,
            "market": raw_market_variance,
            "residual": residual_variance,
        },
        "simulation_variances": {
            "date": date_variance,
            "market": market_variance,
            "residual": residual_variance,
        },
        "simulation_standard_deviations": {
            "date": math.sqrt(date_variance),
            "market": math.sqrt(market_variance),
            "residual": math.sqrt(residual_variance),
        },
        "variance_shares": {
            "date": date_variance / total_variance,
            "market": market_variance / total_variance,
            "residual": residual_variance / total_variance,
        },
    }


def aggregate_endpoint(frame: pd.DataFrame, key: str, ratio: bool) -> Endpoint:
    work = frame.assign(
        _delta=frame["repair_squared_error"] - frame["control_squared_error"],
    )
    work = work.assign(_delta_sq=work["_delta"] ** 2)
    cells = (
        work.groupby(["target_date", "market_id"], sort=True, observed=True)
        .agg(
            row_count=("_delta", "size"),
            delta_sum=("_delta", "sum"),
            delta_sum_sq=("_delta_sq", "sum"),
            market_sse=("market_squared_error", "sum"),
        )
        .reset_index()
    )
    dates = tuple(sorted(work["target_date"].unique().tolist()))
    markets = tuple(sorted(work["market_id"].unique().tolist()))
    d_index = {value: index for index, value in enumerate(dates)}
    m_index = {value: index for index, value in enumerate(markets)}
    counts = np.zeros((len(dates), len(markets)), dtype=float)
    denominator = np.zeros_like(counts)
    for row in cells.itertuples(index=False):
        d = d_index[row.target_date]
        m = m_index[row.market_id]
        counts[d, m] = float(row.row_count)
        denominator[d, m] = float(row.market_sse if ratio else row.row_count)
    return Endpoint(
        key=key,
        dates=dates,
        markets=markets,
        counts=counts,
        denominator=denominator,
        variance_components=henderson_components(cells, dates, markets),
    )


def load_endpoints(input_path: Path, protocol: dict[str, Any]) -> dict[str, Endpoint]:
    input_spec = protocol["input"]
    actual_hash = sha256(input_path)
    if actual_hash != input_spec["sha256"]:
        raise RuntimeError(f"input hash mismatch: {actual_hash}")
    frame = pd.read_csv(
        input_path,
        usecols=READ_COLUMNS,
        dtype={"target_date": str, "stratum": str, "market_id": str},
    )
    if len(frame) != int(input_spec["rows"]):
        raise RuntimeError(f"unexpected input rows: {len(frame)}")
    if frame["target_date"].max() != input_spec["last_allowed_target_date"]:
        raise RuntimeError(f"unexpected final target date: {frame['target_date'].max()}")
    if frame["target_date"].ge("2026-07-31").any():
        raise RuntimeError("post-boundary row detected")

    # Binary Brier identity: sqrt((p-y)^2)=abs(p-y), and y is common to
    # repair and market.  Therefore this reproduces -09-57a's tail without
    # loading outcome or either probability column.
    repair_excess = frame["repair_squared_error"] > frame["market_squared_error"]
    probability_gap = (
        np.sqrt(frame["repair_squared_error"]) - np.sqrt(frame["market_squared_error"])
    ).abs()
    tail = frame.loc[repair_excess & probability_gap.ge(0.30)].copy()

    endpoints = {
        "out_of_season_c": aggregate_endpoint(
            frame.loc[frame["stratum"].eq("C")].copy(), "out_of_season_c", ratio=True
        ),
        "severity_tail": aggregate_endpoint(tail, "severity_tail", ratio=False),
        "in_season_b": aggregate_endpoint(
            frame.loc[frame["stratum"].eq("B")].copy(), "in_season_b", ratio=True
        ),
    }
    for key, endpoint in endpoints.items():
        expected = protocol["endpoints"][key]
        observed = (endpoint.date_clusters, endpoint.market_clusters, endpoint.rows)
        wanted = (
            int(expected["date_clusters"]),
            int(expected["market_clusters"]),
            int(expected["rows"]),
        )
        if observed != wanted:
            raise RuntimeError(f"{key} support mismatch: observed {observed}, expected {wanted}")
        if endpoint.denominator.sum() <= 0.0:
            raise RuntimeError(f"{key} has a non-positive endpoint denominator")
    return endpoints


def endpoint_metadata(endpoint: Endpoint) -> dict[str, Any]:
    occupied = endpoint.counts[endpoint.counts > 0]
    return {
        "date_clusters": endpoint.date_clusters,
        "market_clusters": endpoint.market_clusters,
        "rows": endpoint.rows,
        "occupied_cells": int((endpoint.counts > 0).sum()),
        "possible_cells": int(endpoint.counts.size),
        "cell_occupancy": {
            "minimum": float(occupied.min()),
            "median": float(np.median(occupied)),
            "maximum": float(occupied.max()),
        },
        "fixed_denominator_sum": float(endpoint.denominator.sum()),
        "variance_components": endpoint.variance_components,
    }


def generate_cell_sums(endpoint: Endpoint, rng: np.random.Generator, size: int) -> np.ndarray:
    variances = endpoint.variance_components["simulation_variances"]
    date_effect = rng.normal(0.0, math.sqrt(variances["date"]), size=(size, endpoint.date_clusters))
    market_effect = rng.normal(
        0.0, math.sqrt(variances["market"]), size=(size, endpoint.market_clusters)
    )
    residual = rng.normal(
        0.0,
        math.sqrt(variances["residual"]),
        size=(size, endpoint.date_clusters, endpoint.market_clusters),
    )
    return endpoint.counts[None, :, :] * (
        date_effect[:, :, None] + market_effect[:, None, :]
    ) + np.sqrt(endpoint.counts)[None, :, :] * residual


def crossed_statistics(
    cell_sums: np.ndarray,
    denominator: np.ndarray,
    draws: int,
    rng: np.random.Generator,
) -> np.ndarray:
    size, date_clusters, market_clusters = cell_sums.shape
    date_counts = rng.multinomial(
        date_clusters,
        np.full(date_clusters, 1.0 / date_clusters),
        size=(size, draws),
    )
    market_counts = rng.multinomial(
        market_clusters,
        np.full(market_clusters, 1.0 / market_clusters),
        size=(size, draws),
    )
    numerator = np.einsum(
        "rbd,rdm,rbm->rb", date_counts, cell_sums, market_counts, optimize=True
    )
    denominator_draws = np.einsum(
        "rbd,dm,rbm->rb", date_counts, denominator, market_counts, optimize=True
    )
    if np.any(denominator_draws <= 0.0):
        count = int(np.count_nonzero(denominator_draws <= 0.0))
        raise RuntimeError(f"crossed bootstrap produced {count} non-positive denominators")
    return numerator / denominator_draws


def pilot_endpoint(
    endpoint: Endpoint,
    replications: int,
    draw_grid: list[int],
    seed: int,
    batch_size: int,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    maximum = max(draw_grid)
    collected = {draws: [] for draws in draw_grid}
    completed = 0
    while completed < replications:
        size = min(batch_size, replications - completed)
        cell_sums = generate_cell_sums(endpoint, rng, size)
        statistics = crossed_statistics(cell_sums, endpoint.denominator, maximum, rng)
        for draws in draw_grid:
            collected[draws].append(statistics[:, :draws].std(axis=1, ddof=1))
        completed += size
    arrays = {draws: np.concatenate(parts) for draws, parts in collected.items()}
    reference = arrays[maximum]
    summary: dict[str, Any] = {}
    for draws in draw_grid:
        values = arrays[draws]
        paired_relative = np.abs(values - reference) / reference
        summary[str(draws)] = {
            "mean_bootstrap_sd": float(values.mean()),
            "mean_relative_to_reference": float(values.mean() / reference.mean()),
            "mean_relative_difference": float(abs(values.mean() / reference.mean() - 1.0)),
            "median_paired_absolute_relative_difference": float(np.median(paired_relative)),
            "p95_paired_absolute_relative_difference": float(np.quantile(paired_relative, 0.95)),
        }
    return {"replications": replications, "seed": seed, "draws": summary}


def run_pilot(
    endpoints: dict[str, Endpoint], protocol: dict[str, Any], output_dir: Path
) -> dict[str, Any]:
    bootstrap = protocol["bootstrap"]
    draw_grid = [int(value) for value in bootstrap["draw_grid"]]
    seed = int(protocol["random_seeds"]["pilot"])
    results: dict[str, Any] = {}
    for index, (key, endpoint) in enumerate(endpoints.items()):
        print(f"pilot {key}", flush=True)
        results[key] = pilot_endpoint(
            endpoint,
            int(bootstrap["pilot_replications"]),
            draw_grid,
            seed + index,
            int(bootstrap["coverage_batch_size"]),
        )
    reference = int(bootstrap["draw_reference"])
    selected = reference
    for candidate in sorted(draw_grid):
        if candidate == reference:
            continue
        passes = all(
            results[key]["draws"][str(candidate)]["mean_relative_difference"] <= 0.005
            and results[key]["draws"][str(candidate)][
                "median_paired_absolute_relative_difference"
            ]
            <= 0.03
            for key in results
        )
        if passes:
            selected = candidate
            break
    payload = {
        "protocol_sha256": json_hash(protocol),
        "selected_bootstrap_draws": selected,
        "selection_rule": protocol["bootstrap"]["draw_selection"],
        "endpoints": results,
    }
    write_json(output_dir / "pilot.json", payload)
    return payload


def wilson_interval(successes: int, trials: int, confidence: float = 0.95) -> list[float]:
    z = NORMAL.inv_cdf(0.5 + confidence / 2.0)
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    radius = z / denominator * math.sqrt(
        proportion * (1.0 - proportion) / trials + z * z / (4.0 * trials * trials)
    )
    return [max(0.0, center - radius), min(1.0, center + radius)]


def detectable_excess(nominal: float, replications: int) -> float:
    """Smallest positive rate excess with 80% power at two-sided 5% size."""

    z_size = NORMAL.inv_cdf(0.975)
    z_power = NORMAL.inv_cdf(0.80)
    threshold = nominal + z_size * math.sqrt(nominal * (1.0 - nominal) / replications)
    low, high = nominal, min(1.0, nominal + 0.25)
    for _ in range(100):
        candidate = (low + high) / 2.0
        standard_error = math.sqrt(candidate * (1.0 - candidate) / replications)
        power = NORMAL.cdf((candidate - threshold) / standard_error)
        if power >= 0.80:
            high = candidate
        else:
            low = candidate
    return high - nominal


def summarize_rejections(t_values: np.ndarray, alphas: list[float]) -> dict[str, Any]:
    replications = len(t_values)
    result: dict[str, Any] = {}
    for alpha in alphas:
        z = NORMAL.inv_cdf(1.0 - alpha / 2.0)
        rejected = int(np.count_nonzero(t_values > z))
        rate = rejected / replications
        interval = wilson_interval(rejected, replications)
        result[str(alpha)] = {
            "normal_quantile": z,
            "rejections": rejected,
            "replications": replications,
            "empirical_rejection_rate": rate,
            "monte_carlo_standard_error": math.sqrt(rate * (1.0 - rate) / replications),
            "wilson_95pct_interval": interval,
            "nominal_inside_wilson_interval": interval[0] <= alpha <= interval[1],
            "empirical_restoring_quantile": float(np.quantile(t_values, 1.0 - alpha)),
            "smallest_detectable_absolute_excess_80pct_power": detectable_excess(
                alpha, replications
            ),
        }
    return result


def positive_control(
    protocol: dict[str, Any], draws: int, alphas: list[float]
) -> dict[str, Any]:
    spec = protocol["positive_control"]
    d = int(spec["date_clusters"])
    m = int(spec["market_clusters"])
    replications = int(spec["replications"])
    batch_size = int(spec["batch_size"])
    rng = np.random.default_rng(int(protocol["random_seeds"]["positive_control"]))
    exact_sd = math.sqrt(1.0 / d + 1.0 / m)
    points: list[np.ndarray] = []
    bootstrap_sds: list[np.ndarray] = []
    completed = 0
    started = time.monotonic()
    while completed < replications:
        size = min(batch_size, replications - completed)
        date_effect = rng.normal(size=(size, d))
        market_effect = rng.normal(size=(size, m))
        point = date_effect.mean(axis=1) + market_effect.mean(axis=1)
        date_counts = rng.multinomial(d, np.full(d, 1.0 / d), size=(size, draws))
        market_counts = rng.multinomial(m, np.full(m, 1.0 / m), size=(size, draws))
        statistics = np.einsum("rbd,rd->rb", date_counts, date_effect, optimize=True) / d
        statistics += np.einsum("rbm,rm->rb", market_counts, market_effect, optimize=True) / m
        points.append(point)
        bootstrap_sds.append(statistics.std(axis=1, ddof=1))
        completed += size
        if completed % 2000 == 0 or completed == replications:
            elapsed = time.monotonic() - started
            print(f"positive control {completed}/{replications} ({elapsed:.1f}s)", flush=True)
    point_values = np.concatenate(points)
    sd_values = np.concatenate(bootstrap_sds)
    oracle = summarize_rejections(np.abs(point_values) / exact_sd, alphas)
    crossed = summarize_rejections(np.abs(point_values) / sd_values, alphas)
    checks: dict[str, Any] = {}
    passed = True
    for alpha in alphas:
        tolerance = 4.0 * math.sqrt(alpha * (1.0 - alpha) / replications)
        oracle_pass = abs(oracle[str(alpha)]["empirical_rejection_rate"] - alpha) <= tolerance
        crossed_pass = abs(crossed[str(alpha)]["empirical_rejection_rate"] - alpha) <= tolerance
        checks[str(alpha)] = {
            "four_null_mcse_tolerance": tolerance,
            "oracle_pass": oracle_pass,
            "crossed_bootstrap_pass": crossed_pass,
        }
        passed = passed and oracle_pass and crossed_pass
    scale_ratio = float(sd_values.mean() / exact_sd)
    scale_pass = abs(scale_ratio - 1.0) <= 0.025
    passed = passed and scale_pass
    return {
        "passed": passed,
        "fatal_rule": spec["fatal_rule"],
        "date_clusters": d,
        "market_clusters": m,
        "replications": replications,
        "bootstrap_draws": draws,
        "exact_standard_deviation": exact_sd,
        "mean_bootstrap_standard_deviation": float(sd_values.mean()),
        "mean_bootstrap_sd_to_exact_ratio": scale_ratio,
        "scale_check_pass": scale_pass,
        "oracle": oracle,
        "crossed_bootstrap": crossed,
        "coverage_checks": checks,
    }


def simulate_endpoint_coverage(
    endpoint: Endpoint,
    protocol: dict[str, Any],
    draws: int,
    alphas: list[float],
) -> dict[str, Any]:
    bootstrap = protocol["bootstrap"]
    replications = int(bootstrap["coverage_replications"])
    batch_size = int(bootstrap["coverage_batch_size"])
    rng = np.random.default_rng(int(protocol["random_seeds"][endpoint.key]))
    t_values: list[np.ndarray] = []
    standard_deviations: list[np.ndarray] = []
    points: list[np.ndarray] = []
    completed = 0
    started = time.monotonic()
    fixed_denominator = float(endpoint.denominator.sum())
    while completed < replications:
        size = min(batch_size, replications - completed)
        cell_sums = generate_cell_sums(endpoint, rng, size)
        point = cell_sums.sum(axis=(1, 2)) / fixed_denominator
        statistics = crossed_statistics(cell_sums, endpoint.denominator, draws, rng)
        sd = statistics.std(axis=1, ddof=1)
        if np.any(sd <= 0.0):
            raise RuntimeError(f"{endpoint.key} produced non-positive bootstrap SD")
        points.append(point)
        standard_deviations.append(sd)
        t_values.append(np.abs(point) / sd)
        completed += size
        if completed % 5000 == 0 or completed == replications:
            elapsed = time.monotonic() - started
            print(f"{endpoint.key} {completed}/{replications} ({elapsed:.1f}s)", flush=True)
    point_values = np.concatenate(points)
    sd_values = np.concatenate(standard_deviations)
    t_array = np.concatenate(t_values)
    return {
        "seed": int(protocol["random_seeds"][endpoint.key]),
        "replications": replications,
        "bootstrap_draws": draws,
        "point_mean": float(point_values.mean()),
        "point_standard_deviation": float(point_values.std(ddof=1)),
        "mean_bootstrap_standard_deviation": float(sd_values.mean()),
        "median_bootstrap_standard_deviation": float(np.median(sd_values)),
        "mean_bootstrap_sd_to_point_sd_ratio": float(sd_values.mean() / point_values.std(ddof=1)),
        "rejection": summarize_rejections(t_array, alphas),
    }


def validate_payload(
    protocol_path: Path,
    protocol: dict[str, Any],
    input_path: Path,
    endpoints: dict[str, Endpoint],
) -> dict[str, Any]:
    return {
        "python": sys.version,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "protocol_path": str(protocol_path),
        "protocol_file_sha256": sha256(protocol_path),
        "protocol_canonical_json_sha256": json_hash(protocol),
        "input_path": str(input_path),
        "input_sha256": sha256(input_path),
        "read_columns": READ_COLUMNS,
        "forbidden_columns_read": sorted(set(READ_COLUMNS) & set(protocol["input"]["forbidden_columns"])),
        "endpoints": {key: endpoint_metadata(value) for key, value in endpoints.items()},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("docs/roadmap/interval-coverage-predeclaration-2026-09-62a.json"),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("scratch/runs/gap-remeasure-repaired-2026-09-44a/paired-band-rows.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("scratch/runs/interval-coverage-2026-09-62a"),
    )
    parser.add_argument("phase", choices=("validate", "pilot", "full", "all"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    if args.output_dir.resolve() == args.input.parent.resolve():
        raise RuntimeError("output directory must not be the retained evidence directory")
    endpoints = load_endpoints(args.input, protocol)
    validation = validate_payload(args.protocol, protocol, args.input, endpoints)
    write_json(args.output_dir / "validation.json", validation)
    print(json.dumps(validation, indent=2, sort_keys=True), flush=True)
    if args.phase == "validate":
        return 0

    if args.phase in {"pilot", "all"}:
        pilot = run_pilot(endpoints, protocol, args.output_dir)
    else:
        pilot_path = args.output_dir / "pilot.json"
        if not pilot_path.exists():
            raise RuntimeError("pilot.json is required before full coverage simulation")
        pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
        if pilot["protocol_sha256"] != json_hash(protocol):
            raise RuntimeError("pilot protocol hash mismatch")
    print(json.dumps(pilot, indent=2, sort_keys=True), flush=True)
    if args.phase == "pilot":
        return 0

    draws = int(pilot["selected_bootstrap_draws"])
    alphas = [float(value) for value in protocol["bootstrap"]["alphas"]]
    print("running fatal positive control before panel", flush=True)
    control = positive_control(protocol, draws, alphas)
    write_json(args.output_dir / "positive-control.json", control)
    print(json.dumps(control, indent=2, sort_keys=True), flush=True)
    if not control["passed"]:
        print("FATAL: positive control failed; panel simulation not run", file=sys.stderr, flush=True)
        return 2

    coverage: dict[str, Any] = {}
    for key, endpoint in endpoints.items():
        print(f"full coverage {key}", flush=True)
        coverage[key] = simulate_endpoint_coverage(endpoint, protocol, draws, alphas)
        write_json(
            args.output_dir / "coverage-partial.json",
            {
                "protocol_sha256": json_hash(protocol),
                "selected_bootstrap_draws": draws,
                "endpoints": coverage,
            },
        )
    payload = {
        "protocol_sha256": json_hash(protocol),
        "selected_bootstrap_draws": draws,
        "positive_control_passed": True,
        "endpoints": coverage,
    }
    write_json(args.output_dir / "coverage.json", payload)
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
