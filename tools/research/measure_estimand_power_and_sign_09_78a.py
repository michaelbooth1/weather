"""Outcome-blind estimand power and sign audit for mission -09-78a.

The only input is the checksum-pinned -09-77a arm-vector CSV.  The harness
never reads a realized band, settlement, label, market probability, or C row.
It simulates the band under each arm's calibration premise and combines every
simulation with crossed target-date x market pigeonhole weights.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SCRIPT_RELATIVE_PATH = "tools/research/measure_estimand_power_and_sign_09_78a.py"
SEED_RELATIVE_PATH = "tools/research/measure_estimand_power_and_sign_09_78a_seed.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    require(isinstance(payload, dict), f"expected JSON object: {path}")
    return payload


def prohibited_header(fieldnames: Iterable[str]) -> list[str]:
    prohibited_fragments = (
        "realized",
        "settlement",
        "settled_",
        "outcome",
        "winning_band",
        "market_price",
        "market_probability",
    )
    return sorted(
        field
        for field in fieldnames
        if any(fragment in field.lower() for fragment in prohibited_fragments)
    )


def load_rows(repo_root: Path, seed: dict[str, Any]) -> list[dict[str, Any]]:
    spec = seed["input"]
    csv_path = repo_root / spec["csv_relative_path"]
    actual_hash = sha256_file(csv_path)
    require(
        actual_hash == spec["csv_sha256"],
        f"STOP: input CSV checksum mismatch: expected {spec['csv_sha256']}, got {actual_hash}",
    )

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames is not None, "input CSV has no header")
        forbidden = prohibited_header(reader.fieldnames)
        require(not forbidden, f"STOP: outcome-bearing CSV fields are forbidden: {forbidden}")
        raw_rows = list(reader)

    rows: list[dict[str, Any]] = []
    mass_tolerance = float(seed["simulation"]["probability_mass_tolerance"])
    for index, raw in enumerate(raw_rows, start=2):
        require(raw["stratum"] == spec["required_stratum"], f"row {index}: non-B stratum")
        require(
            raw["target_date"] < spec["regime_boundary_exclusive"],
            f"row {index}: row crosses the 2026-07-31 regime boundary",
        )
        band_keys = json.loads(raw["band_keys"])
        q = np.asarray(json.loads(raw["incumbent_probs_q"]), dtype=np.float64)
        p = np.asarray(json.loads(raw["candidate_probs_p"]), dtype=np.float64)
        require(q.ndim == 1 and p.ndim == 1, f"row {index}: arm vector is not one-dimensional")
        require(len(q) == len(p) == len(band_keys), f"row {index}: arm/band length mismatch")
        require(np.all(np.isfinite(q)) and np.all(np.isfinite(p)), f"row {index}: non-finite probability")
        require(np.all(q >= 0.0) and np.all(p >= 0.0), f"row {index}: negative probability")
        require(abs(float(q.sum()) - 1.0) <= mass_tolerance, f"row {index}: q mass violation")
        require(abs(float(p.sum()) - 1.0) <= mass_tolerance, f"row {index}: p mass violation")
        q = q / q.sum()
        p = p / p.sum()
        squared_distance = float(np.square(p - q).sum())
        sharpness_delta = float(np.square(p).sum() - np.square(q).sum())
        rows.append(
            {
                "stratum": raw["stratum"],
                "market_id": raw["market_id"],
                "target_date": raw["target_date"],
                "snapshot_id": raw["snapshot_id"],
                "window": raw["window"],
                "q": q,
                "p": p,
                "base_delta": float(np.square(q).sum() - np.square(p).sum()),
                "squared_distance": squared_distance,
                "sharpness_delta": sharpness_delta,
                "argmax_changed": raw["argmax_changed"].strip().lower() == "true",
            }
        )

    support = {
        "rows": len(rows),
        "date_clusters": len({row["target_date"] for row in rows}),
        "market_clusters": len({row["market_id"] for row in rows}),
        "market_days": len({(row["target_date"], row["market_id"]) for row in rows}),
        "sharper_rows": sum(row["sharpness_delta"] > 0.0 for row in rows),
        "argmax_changes": sum(row["argmax_changed"] for row in rows),
    }
    for key, expected_key in (
        ("rows", "expected_rows"),
        ("date_clusters", "expected_date_clusters"),
        ("market_clusters", "expected_market_clusters"),
        ("market_days", "expected_market_days"),
        ("sharper_rows", "expected_sharper_rows"),
        ("argmax_changes", "expected_argmax_changes"),
    ):
        require(support[key] == int(spec[expected_key]), f"{key} receipt mismatch: {support[key]}")
    return rows


def decision(effect_magnitude: float, standard_error: float, q: float, z_power: float) -> str:
    mde = (q + z_power) * standard_error
    return "POWERED" if effect_magnitude > mde else "NO_GO_UNPOWERED"


def minimum_candidate_closer(rows: list[dict[str, Any]]) -> dict[str, Any]:
    distances = sorted((float(row["squared_distance"]) for row in rows), reverse=True)
    total = math.fsum(distances)
    require(total > 0.0, "arm distance is identically zero; a positive mean is impossible")
    cumulative = 0.0
    required = 0
    for value in distances:
        cumulative += value
        required += 1
        if cumulative > total / 2.0:
            break
    require(cumulative > total / 2.0, "failed to cross half of total squared distance")
    return {
        "rows": len(rows),
        "minimum_candidate_closer_rows": required,
        "minimum_candidate_closer_share": required / len(rows),
        "distance_share_at_threshold": cumulative / total,
        "rule": (
            "most favorable assignment: candidate is closer on rows in descending ||p-q||^2; "
            "strictly more than half of total squared distance is required"
        ),
    }


def summarize_group(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    sharp = [float(row["sharpness_delta"]) for row in rows]
    sharper_rows = sum(value > 0.0 for value in sharp)
    result = {
        "rows": len(rows),
        "mean_squared_arm_distance": math.fsum(float(row["squared_distance"]) for row in rows) / len(rows),
        "mean_sharpness_delta_p2_minus_q2": math.fsum(sharp) / len(rows),
        "sum_sharpness_delta_p2_minus_q2": math.fsum(sharp),
        "sharper_rows": sharper_rows,
        "sharper_share": sharper_rows / len(rows),
        "large_majority_sharpening_threshold": threshold,
        "large_majority_sharpening": sharper_rows / len(rows) >= threshold,
    }
    result.update(minimum_candidate_closer(rows))
    return result


def grouped_summaries(rows: list[dict[str, Any]], field: str, threshold: float) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {value: summarize_group(items, threshold) for value, items in sorted(groups.items())}


def simulate_nulls(rows: list[dict[str, Any]], seed: dict[str, Any]) -> dict[str, Any]:
    simulation = seed["simulation"]
    replicates = int(simulation["draws_per_null"])
    chunk_size = int(simulation["chunk_size"])
    require(replicates >= 10_000, "at least 10,000 draws per null are required")
    require(chunk_size > 0, "chunk size must be positive")

    dates = sorted({row["target_date"] for row in rows})
    markets = sorted({row["market_id"] for row in rows})
    date_index = {value: index for index, value in enumerate(dates)}
    market_index = {value: index for index, value in enumerate(markets)}
    row_dates = np.asarray([date_index[row["target_date"]] for row in rows], dtype=np.int64)
    row_markets = np.asarray([market_index[row["market_id"]] for row in rows], dtype=np.int64)
    base_delta = np.asarray([row["base_delta"] for row in rows], dtype=np.float64)
    q_vectors = [row["q"] for row in rows]
    p_vectors = [row["p"] for row in rows]
    q_cdf = [np.cumsum(vector, dtype=np.float64) for vector in q_vectors]
    p_cdf = [np.cumsum(vector, dtype=np.float64) for vector in p_vectors]
    for cdf in q_cdf + p_cdf:
        cdf[-1] = 1.0

    root_sequence = np.random.SeedSequence(int(simulation["seed"]))
    cluster_sequence, null_i_sequence, null_c_sequence = root_sequence.spawn(3)
    cluster_rng = np.random.Generator(np.random.PCG64(cluster_sequence))
    null_i_rng = np.random.Generator(np.random.PCG64(null_i_sequence))
    null_c_rng = np.random.Generator(np.random.PCG64(null_c_sequence))

    crossed_i = np.empty(replicates, dtype=np.float64)
    crossed_c = np.empty(replicates, dtype=np.float64)
    unweighted_i = np.empty(replicates, dtype=np.float64)
    unweighted_c = np.empty(replicates, dtype=np.float64)
    date_probability = np.full(len(dates), 1.0 / len(dates), dtype=np.float64)
    market_probability = np.full(len(markets), 1.0 / len(markets), dtype=np.float64)

    for start in range(0, replicates, chunk_size):
        stop = min(start + chunk_size, replicates)
        size = stop - start
        date_counts = cluster_rng.multinomial(len(dates), date_probability, size=size)
        market_counts = cluster_rng.multinomial(len(markets), market_probability, size=size)
        weights = date_counts[:, row_dates] * market_counts[:, row_markets]
        denominators = weights.sum(axis=1, dtype=np.float64)
        require(np.all(denominators > 0.0), "crossed bootstrap produced an empty product draw")

        delta_i = np.empty((size, len(rows)), dtype=np.float64)
        delta_c = np.empty((size, len(rows)), dtype=np.float64)
        for row_index, (q, p, q_bins, p_bins) in enumerate(zip(q_vectors, p_vectors, q_cdf, p_cdf)):
            band_i = np.searchsorted(q_bins, null_i_rng.random(size), side="right")
            band_c = np.searchsorted(p_bins, null_c_rng.random(size), side="right")
            delta_i[:, row_index] = base_delta[row_index] + 2.0 * (p[band_i] - q[band_i])
            delta_c[:, row_index] = base_delta[row_index] + 2.0 * (p[band_c] - q[band_c])

        unweighted_i[start:stop] = delta_i.mean(axis=1)
        unweighted_c[start:stop] = delta_c.mean(axis=1)
        crossed_i[start:stop] = np.einsum("ij,ij->i", weights, delta_i) / denominators
        crossed_c[start:stop] = np.einsum("ij,ij->i", weights, delta_c) / denominators

    analytic_magnitude = math.fsum(float(row["squared_distance"]) for row in rows) / len(rows)
    tolerance = float(simulation["mean_receipt_absolute_tolerance"])
    power = seed["power"]
    q_value = float(power["uniform_q"])
    z_power = float(power["z_80_percent_power"])

    def result_for(name: str, expected: float, unweighted: np.ndarray, crossed: np.ndarray) -> dict[str, Any]:
        unweighted_mean = float(unweighted.mean())
        crossed_mean = float(crossed.mean())
        standard_error = float(crossed.std(ddof=1))
        mde = (q_value + z_power) * standard_error
        receipt_pass = abs(unweighted_mean - expected) <= tolerance
        require(receipt_pass, f"{name} simulated mean misses analytic control")
        return {
            "band_draw_distribution": "q" if name == "null_i_incumbent_calibrated" else "p",
            "analytic_expected_mean": expected,
            "simulated_unweighted_mean": unweighted_mean,
            "simulated_crossed_draw_mean": crossed_mean,
            "simulated_mean_minus_analytic": unweighted_mean - expected,
            "mean_receipt_tolerance": tolerance,
            "mean_receipt_pass": receipt_pass,
            "crossed_standard_error_of_mean_estimand": standard_error,
            "mde": mde,
            "absolute_analytic_mean": abs(expected),
            "absolute_mean_clears_mde": abs(expected) > mde,
            "verdict": decision(abs(expected), standard_error, q_value, z_power),
            "draws": replicates,
        }

    return {
        "rng": simulation["rng"],
        "root_seed": int(simulation["seed"]),
        "draws_per_null": replicates,
        "chunk_size": chunk_size,
        "crossed_bootstrap": simulation["crossed_bootstrap"],
        "analytic_mean_magnitude": analytic_magnitude,
        "null_i_incumbent_calibrated": result_for(
            "null_i_incumbent_calibrated", -analytic_magnitude, unweighted_i, crossed_i
        ),
        "null_c_candidate_calibrated": result_for(
            "null_c_candidate_calibrated", analytic_magnitude, unweighted_c, crossed_c
        ),
    }


def write_breakdown(path: Path, overall: dict[str, Any], per_market: dict[str, Any], per_window: dict[str, Any]) -> None:
    fieldnames = [
        "scope_type",
        "scope_value",
        "rows",
        "mean_squared_arm_distance",
        "mean_sharpness_delta_p2_minus_q2",
        "sum_sharpness_delta_p2_minus_q2",
        "sharper_rows",
        "sharper_share",
        "large_majority_sharpening",
        "minimum_candidate_closer_rows",
        "minimum_candidate_closer_share",
        "distance_share_at_threshold",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for scope_type, values in (
            ("overall", {"ALL": overall}),
            ("market", per_market),
            ("window", per_window),
        ):
            for scope_value, summary in values.items():
                writer.writerow(
                    {
                        "scope_type": scope_type,
                        "scope_value": scope_value,
                        **{field: summary[field] for field in fieldnames[2:]},
                    }
                )


def write_checksums(repo_root: Path, output_path: Path, relative_paths: list[str]) -> None:
    lines = [f"{sha256_file(repo_root / relative)}  {relative}" for relative in relative_paths]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def run(repo_root: Path, seed_path: Path) -> dict[str, Any]:
    seed = load_json(seed_path)
    rows = load_rows(repo_root, seed)
    simulation = simulate_nulls(rows, seed)
    expected_magnitude = float(seed["simulation"]["expected_mean_magnitude"])
    require(
        abs(simulation["analytic_mean_magnitude"] - expected_magnitude) <= 5e-11,
        "analytic squared-distance receipt does not reproduce 0.1385161075",
    )

    threshold = float(seed["direction"]["large_majority_sharpening_threshold"])
    overall = summarize_group(rows, threshold)
    per_market = grouped_summaries(rows, "market_id", threshold)
    per_window = grouped_summaries(rows, "window", threshold)
    power = seed["power"]
    null_i = simulation["null_i_incumbent_calibrated"]
    null_c = simulation["null_c_candidate_calibrated"]
    floor = float(power["corrected_twelve_market_floor"])
    candidate_generous_powered = bool(null_c["absolute_mean_clears_mde"])
    verdict = (
        "POWERED_DRAFT_REMAINS_UNFROZEN_ALPHA_UNALLOCATED"
        if candidate_generous_powered
        else "NO_GO_UNPOWERED_UNDER_CANDIDATE_CALIBRATION_CLOSE_THREAD_KEEP_ALPHA"
    )

    result = {
        "schema_version": "estimand_power_and_sign_result_v1",
        "mission": seed["mission"],
        "verdict": verdict,
        "input": {
            "csv_relative_path": seed["input"]["csv_relative_path"],
            "csv_sha256_expected": seed["input"]["csv_sha256"],
            "csv_sha256_actual": sha256_file(repo_root / seed["input"]["csv_relative_path"]),
            "checksum_gate": "PASS",
        },
        "estimand": {
            "name": "paired multiclass Brier improvement",
            "formula": "sum(q_k^2)-sum(p_k^2)+2*(p_b-q_b)",
            "positive_means": "candidate p has lower Brier loss than incumbent q",
            "band_observation": "simulated only; no realized band read",
        },
        "support": {
            "rows": len(rows),
            "date_clusters": len({row["target_date"] for row in rows}),
            "market_clusters": len({row["market_id"] for row in rows}),
            "market_days": len({(row["target_date"], row["market_id"]) for row in rows}),
            "strata": sorted({row["stratum"] for row in rows}),
            "windows": sorted({row["window"] for row in rows}),
        },
        "simulation": simulation,
        "power": {
            "alpha": float(power["alpha"]),
            "power": float(power["power"]),
            "uniform_q": float(power["uniform_q"]),
            "z_80_percent_power": float(power["z_80_percent_power"]),
            "mde_formula": "(3.1098893 + 0.8416212336) * SE(delta)",
            "candidate_generous_null_c_powered": candidate_generous_powered,
            "candidate_generous_null_c_verdict": null_c["verdict"],
            "incumbent_null_i_verdict": null_i["verdict"],
            "corrected_twelve_market_floor": floor,
            "null_i_field_mde": null_i["mde"],
            "null_c_field_mde": null_c["mde"],
            "null_i_binding_limit": "field_mde" if null_i["mde"] >= floor else "twelve_market_floor",
            "null_c_binding_limit": "field_mde" if null_c["mde"] >= floor else "twelve_market_floor",
            "no_go_reachable_standard_error_threshold": (
                simulation["analytic_mean_magnitude"]
                / (float(power["uniform_q"]) + float(power["z_80_percent_power"]))
            ),
            "equality_is_no_go": bool(power["equality_is_no_go"]),
        },
        "direction": {
            "interpretation": (
                "Under the two calibrated-arm premises each row contributes +/-||p-q||^2; "
                "the sign depends on which arm is closer to the unknown truth."
            ),
            "overall": overall,
            "per_market": per_market,
            "per_window": per_window,
        },
        "proposed_sharpening_guard": {
            "fixed_subset": "rows with sum(p_k^2)-sum(q_k^2) > 0, computed before any outcome read",
            "row_indicator": "1 if realized paired delta > 0 (candidate closer), else 0; ties count 0",
            "rule": (
                "In addition to the primary mean-improvement rule, require the crossed-bootstrap "
                "lower bound for the candidate-closer share on the fixed sharper-row subset, using "
                "q=3.1098893 and shared target_date x market_id weights, to exceed 0.5."
            ),
            "intersection_union": True,
            "failure_disposition": "NO_GO",
        },
        "campaign": seed["campaign"],
        "receipts": {
            "self_test_passed_before_measurement": True,
            "design_can_return_no_go": True,
            "realized_band_read": False,
            "settlement_consulted": False,
            "outcome_scored": False,
            "market_compared": False,
            "C_endpoint": False,
            "replay_rerun": False,
            "snapshot_scan": False,
            "payload_read": False,
            "provider_or_exchange_call": False,
            "alpha_allocated_by_mission": 0,
        },
        "runtime": {
            "python": sys.version,
            "numpy": np.__version__,
        },
    }

    outputs = seed["outputs"]
    result_path = repo_root / outputs["result_json"]
    breakdown_path = repo_root / outputs["breakdown_csv"]
    checksums_path = repo_root / outputs["checksums"]
    result_path.parent.mkdir(parents=True, exist_ok=True)
    write_breakdown(breakdown_path, overall, per_market, per_window)
    result_path.write_bytes(canonical_json(result))
    write_checksums(
        repo_root,
        checksums_path,
        [
            seed["input"]["csv_relative_path"],
            SCRIPT_RELATIVE_PATH,
            SEED_RELATIVE_PATH,
            outputs["result_json"],
            outputs["breakdown_csv"],
            outputs["preregistration_draft"],
        ],
    )
    return result


def self_test() -> None:
    q = np.asarray([0.7, 0.2, 0.1], dtype=np.float64)
    p = np.asarray([0.4, 0.4, 0.2], dtype=np.float64)
    base = float(np.square(q).sum() - np.square(p).sum())
    deltas = base + 2.0 * (p - q)
    direct = []
    for band in range(3):
        truth = np.zeros(3, dtype=np.float64)
        truth[band] = 1.0
        direct.append(float(np.square(q - truth).sum() - np.square(p - truth).sum()))
    require(np.allclose(deltas, direct, rtol=0.0, atol=1e-15), "estimand orientation self-test failed")
    squared_distance = float(np.square(p - q).sum())
    require(abs(float(q @ deltas) + squared_distance) < 1e-15, "Null I sign self-test failed")
    require(abs(float(p @ deltas) - squared_distance) < 1e-15, "Null C sign self-test failed")

    q_value = 3.1098893
    z_power = 0.8416212336
    require(decision(0.1, 0.01, q_value, z_power) == "POWERED", "POWERED path unreachable")
    require(decision(0.1, 0.05, q_value, z_power) == "NO_GO_UNPOWERED", "NO-GO path unreachable")
    rows = [{"squared_distance": value} for value in (4.0, 3.0, 2.0, 1.0)]
    exposure = minimum_candidate_closer(rows)
    require(exposure["minimum_candidate_closer_rows"] == 2, "closer-share self-test failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    run_parser.add_argument(
        "--seed",
        type=Path,
        default=Path(SEED_RELATIVE_PATH),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    self_test()
    if args.command == "self-test":
        print("PASS: estimand orientation and NO-GO reachability")
        return 0
    repo_root = args.repo_root.resolve()
    seed_path = args.seed if args.seed.is_absolute() else repo_root / args.seed
    result = run(repo_root, seed_path)
    print(json.dumps({"verdict": result["verdict"], "power": result["power"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
