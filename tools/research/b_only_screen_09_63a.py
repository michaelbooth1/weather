"""Execute the frozen -09-61a decision-10 B-only screen without opening C.

This is deliberately a one-shot research harness, not a production workflow.  Its
most important property is the input boundary: the paired panel is filtered on the
raw fourth CSV token before a row is parsed.  C outcome and probability fields are
therefore never materialized.  Feature rows are likewise parsed only after their
date is known to belong to stratum B.

Run from the repository root with the bundled Codex Python 3.12 runtime::

    python tools/research/b_only_screen_09_63a.py

The optimizer is deterministic and invokes no RNG.  ``DETERMINISTIC_SEED`` is
retained as the mission's committed seed/audit identifier; every fit starts once
from the frozen all-zero vector.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
PAIRED_PATH = REPO_ROOT / "scratch/runs/gap-remeasure-repaired-2026-09-44a/paired-band-rows.csv"
FEATURE_PATH = REPO_ROOT / "docs/roadmap/pit-lead1-daily-features-2026-09-61a.csv"
FEATURE_MANIFEST_PATH = (
    REPO_ROOT / "docs/roadmap/pit-lead1-daily-features-2026-09-61a-manifest.json"
)
PROTOCOL_PATH = REPO_ROOT / "docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.json"
OUTPUT_PATH = REPO_ROOT / "scratch/runs/b-only-screen-2026-09-63a/result.json"

FEATURE_SHA256 = "60b450f1dd1ee575acde86607d179ae0cae68ddee541feef664923bd62b71ac8"
PROTOCOL_SHA256 = "336150be1a62e88c2fe40ccd7b77916576d08981617ebbff1e01195007cfc146"
PAIRED_SHA256 = "4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88"
DETERMINISTIC_SEED = 20260963  # Audit identifier only: this harness invokes no RNG.
LAMBDA = 0.01
GRADIENT_TOLERANCE = 1e-8
OBJECTIVE_RELATIVE_TOLERANCE = 1e-12
MASS_TOLERANCE = 1e-12
MAX_OPTIMIZER_ITERATIONS = 200

FEATURES = (
    "temperature_2m",
    "cloud_cover",
    "shortwave_radiation",
    "wind_speed_10m",
    "cape",
    "direct_radiation",
    "diffuse_radiation",
    "wind_gusts_10m",
    "precipitation_probability",
    "precipitation",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
)
EXPECTED_MARKETS = (
    "atlanta",
    "austin",
    "chicago",
    "dallas",
    "denver",
    "houston",
    "los-angeles",
    "miami",
    "nyc",
    "san-francisco",
    "seattle",
    "toronto",
)
EXPECTED_PAIRED_HEADER = (
    "snapshot_id",
    "record_hash",
    "target_date",
    "stratum",
    "market_id",
    "capture_hour",
    "effective_cutoff_hour",
    "band_index",
    "outcome",
    "market_probability",
    "market_squared_error",
    "control_probability",
    "repair_probability",
    "control_squared_error",
    "repair_squared_error",
    "probability_delta",
    "squared_error_delta",
)
EXPECTED_FEATURE_HEADER = ("market", "target_date", *FEATURES)


class GateFailure(RuntimeError):
    """A frozen integrity or model gate failed and execution must stop."""

    def __init__(self, gate: str, message: str) -> None:
        super().__init__(message)
        self.gate = gate


@dataclass(frozen=True)
class Snapshot:
    key: tuple[str, str, str, str]
    target_date: str
    market: str
    market_day: tuple[str, str]
    band_index: np.ndarray
    outcome: np.ndarray
    incumbent: np.ndarray
    ordered_coordinate: np.ndarray
    winner: int


@dataclass(frozen=True)
class FitResult:
    beta: np.ndarray
    objective: float
    unpenalized_nll: float
    penalty: float
    gradient_inf_norm: float
    iterations: int
    relative_objective_change: float
    converged: bool
    line_search_halvings: int


@dataclass
class SafetyAccumulator:
    applications: int = 0
    probability_rows: int = 0
    zero_support_rows: int = 0
    zero_support_violations: int = 0
    max_mass_error: float = 0.0
    floor_contract_violations: int = 0

    def update(self, snapshot: Snapshot, candidate: np.ndarray) -> None:
        self.applications += 1
        self.probability_rows += len(candidate)
        zero = snapshot.incumbent == 0.0
        self.zero_support_rows += int(np.count_nonzero(zero))
        self.zero_support_violations += int(np.count_nonzero(candidate[zero] != 0.0))
        self.max_mass_error = max(self.max_mass_error, abs(float(candidate.sum()) - 1.0))
        # The multiplicative map cannot create support below the serving floor.  Record the
        # structural check separately so the report does not mistake mass alone for floor safety.
        self.floor_contract_violations += int(np.count_nonzero(candidate[zero] != 0.0))

    def assert_pass(self) -> None:
        if self.zero_support_violations:
            raise GateFailure("GATE_3_ZERO_SUPPORT", "candidate populated incumbent-zero bands")
        if self.floor_contract_violations:
            raise GateFailure("GATE_3_SERVING_FLOOR", "candidate changed excluded-band support")
        if self.max_mass_error > MASS_TOLERANCE:
            raise GateFailure(
                "GATE_3_MASS",
                f"candidate mass error {self.max_mass_error:.17g} exceeds {MASS_TOLERANCE}",
            )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def raw_csv_field(line: bytes, index: int) -> bytes:
    """Return one unquoted CSV field without splitting or decoding the remaining line.

    The retained panel's first four fields are identifiers with no quoting.  This small scanner
    lets us inspect only ``stratum`` on C rows.  Full CSV parsing happens only after it equals B.
    """

    start = 0
    current = 0
    for position, value in enumerate(line):
        if value == 44:  # comma
            if current == index:
                return line[start:position]
            current += 1
            start = position + 1
    if current == index:
        return line[start:].rstrip(b"\r\n")
    raise GateFailure("GATE_3_PANEL_SCHEMA", f"CSV line has no field {index}")


def parse_one_csv_line(line: bytes) -> list[str]:
    return next(csv.reader([line.decode("utf-8")]))


def read_b_panel() -> tuple[list[Snapshot], dict[str, object]]:
    if not PAIRED_PATH.exists():
        raise GateFailure("GATE_3_PANEL_INPUT", f"missing retained panel: {PAIRED_PATH}")
    paired_digest = sha256(PAIRED_PATH)
    if paired_digest != PAIRED_SHA256:
        raise GateFailure(
            "GATE_3_PANEL_INPUT",
            f"retained panel hash {paired_digest} != frozen {PAIRED_SHA256}",
        )

    grouped: dict[tuple[str, str, str, str], list[tuple[int, int, float]]] = defaultdict(list)
    raw_b_lines = 0
    raw_c_lines_rejected_before_parse = 0
    other_strata = Counter()
    with PAIRED_PATH.open("rb") as handle:
        header = tuple(next(csv.reader([handle.readline().decode("utf-8")])))
        if header != EXPECTED_PAIRED_HEADER:
            raise GateFailure("GATE_3_PANEL_SCHEMA", f"unexpected paired header: {header}")
        column = {name: index for index, name in enumerate(header)}
        if column["stratum"] != 3:
            raise GateFailure("GATE_3_PANEL_SCHEMA", "stratum is not the raw fourth CSV token")

        for raw_line in handle:
            if not raw_line.strip():
                continue
            raw_stratum = raw_csv_field(raw_line, column["stratum"])
            if raw_stratum != b"B":
                if raw_stratum == b"C":
                    raw_c_lines_rejected_before_parse += 1
                else:
                    other_strata[raw_stratum.decode("ascii", errors="replace")] += 1
                continue

            raw_b_lines += 1
            row = parse_one_csv_line(raw_line)
            if len(row) != len(header) or row[column["stratum"]] != "B":
                raise GateFailure("GATE_3_PANEL_SCHEMA", "B row failed full CSV parsing")
            target_date = row[column["target_date"]]
            market = row[column["market_id"]]
            if target_date > "2026-07-30":
                raise GateFailure("GATE_3_BOUNDARY", f"B row crosses boundary: {target_date}")
            key = (
                target_date,
                market,
                row[column["snapshot_id"]],
                row[column["record_hash"]],
            )
            grouped[key].append(
                (
                    int(row[column["band_index"]]),
                    int(row[column["outcome"]]),
                    float(row[column["repair_probability"]]),
                )
            )

    if other_strata:
        raise GateFailure("GATE_3_PANEL_SCHEMA", f"unexpected strata: {dict(other_strata)}")

    snapshots: list[Snapshot] = []
    max_incumbent_mass_error = 0.0
    incumbent_zero_rows = 0
    for key, entries in grouped.items():
        entries.sort(key=lambda value: value[0])
        band_index = np.asarray([value[0] for value in entries], dtype=np.int64)
        if not np.array_equal(band_index, np.arange(len(entries), dtype=np.int64)):
            raise GateFailure("GATE_3_PANEL_SCHEMA", f"non-contiguous bands for {key}")
        outcome = np.asarray([value[1] for value in entries], dtype=np.float64)
        incumbent = np.asarray([value[2] for value in entries], dtype=np.float64)
        if not np.all(np.isfinite(incumbent)) or np.any(incumbent < 0.0) or np.any(incumbent > 1.0):
            raise GateFailure("GATE_3_PANEL_SCHEMA", f"invalid incumbent probability for {key}")
        if int(outcome.sum()) != 1 or not np.all((outcome == 0.0) | (outcome == 1.0)):
            raise GateFailure("GATE_3_PANEL_SCHEMA", f"outcome is not one-hot for {key}")
        winner = int(np.argmax(outcome))
        if incumbent[winner] == 0.0:
            raise GateFailure("GATE_3_WINNING_BAND_ZERO", f"incumbent winner is zero for {key}")
        max_incumbent_mass_error = max(
            max_incumbent_mass_error, abs(float(incumbent.sum()) - 1.0)
        )
        incumbent_zero_rows += int(np.count_nonzero(incumbent == 0.0))
        k = len(entries)
        ordered_coordinate = -1.0 + 2.0 * band_index.astype(np.float64) / (k - 1)
        snapshots.append(
            Snapshot(
                key=key,
                target_date=key[0],
                market=key[1],
                market_day=(key[0], key[1]),
                band_index=band_index,
                outcome=outcome,
                incumbent=incumbent,
                ordered_coordinate=ordered_coordinate,
                winner=winner,
            )
        )

    snapshots.sort(key=lambda value: value.key)
    dates = sorted({snapshot.target_date for snapshot in snapshots})
    markets = sorted({snapshot.market for snapshot in snapshots})
    market_days = {snapshot.market_day for snapshot in snapshots}
    support = {
        "paired_sha256": paired_digest,
        "raw_b_rows_parsed": raw_b_lines,
        "raw_c_rows_rejected_before_csv_parse": raw_c_lines_rejected_before_parse,
        "c_rows_parsed": 0,
        "date_clusters": len(dates),
        "dates": dates,
        "market_clusters": len(markets),
        "markets": markets,
        "market_days": len(market_days),
        "snapshots": len(snapshots),
        "band_rows": sum(len(snapshot.incumbent) for snapshot in snapshots),
        "incumbent_zero_rows": incumbent_zero_rows,
        "max_incumbent_mass_error": max_incumbent_mass_error,
        "candidate_probability_column_read": False,
        "market_probability_column_read": False,
        "control_probability_column_read": False,
        "incumbent_probability_column_read": "repair_probability (B rows only)",
        "outcome_column_read": "outcome (B rows only)",
    }
    expected = {
        "date_clusters": 23,
        "market_clusters": 12,
        "market_days": 204,
        "snapshots": 4636,
        "band_rows": 50996,
    }
    for name, value in expected.items():
        if support[name] != value:
            raise GateFailure(
                "GATE_3_PANEL_SUPPORT", f"B {name}={support[name]} != frozen {value}"
            )
    if tuple(markets) != EXPECTED_MARKETS:
        raise GateFailure("GATE_3_PANEL_SUPPORT", f"unexpected B markets: {markets}")
    return snapshots, support


def read_b_features(
    b_dates: Iterable[str],
) -> tuple[dict[tuple[str, str], np.ndarray], dict[str, object]]:
    feature_digest = sha256(FEATURE_PATH)
    if feature_digest != FEATURE_SHA256:
        raise GateFailure(
            "GATE_3_FEATURE_HASH",
            f"feature hash {feature_digest} != frozen {FEATURE_SHA256}",
        )
    protocol_digest = sha256(PROTOCOL_PATH)
    if protocol_digest != PROTOCOL_SHA256:
        raise GateFailure(
            "GATE_3_PROTOCOL_HASH",
            f"protocol hash {protocol_digest} != frozen {PROTOCOL_SHA256}",
        )

    manifest = json.loads(FEATURE_MANIFEST_PATH.read_text(encoding="utf-8"))
    required_manifest = {
        "extract_sha256": FEATURE_SHA256,
        "protocol_sha256": PROTOCOL_SHA256,
        "issue_time_basis": "fixed_lead_day_offset",
        "source": "open_meteo_previous_runs",
        "lead_days": 1,
        "standardized": False,
        "contains_outcomes_or_market_prices": False,
        "date_max": "2026-07-30",
        "hourly_values_consumed": 116928,
        "extract_rows": 696,
    }
    for name, expected in required_manifest.items():
        if manifest.get(name) != expected:
            raise GateFailure(
                "GATE_3_FEATURE_PROVENANCE",
                f"manifest {name}={manifest.get(name)!r} != {expected!r}",
            )
    if tuple(manifest.get("fields", [])) != FEATURES:
        raise GateFailure("GATE_3_FEATURE_PROVENANCE", "manifest feature order changed")
    if tuple(manifest.get("markets", [])) != EXPECTED_MARKETS:
        raise GateFailure("GATE_3_FEATURE_PROVENANCE", "manifest market roster changed")

    date_set = set(b_dates)
    date_bytes = {date.encode("ascii") for date in date_set}
    feature_rows: dict[tuple[str, str], np.ndarray] = {}
    non_b_feature_rows_rejected_before_parse = 0
    with FEATURE_PATH.open("rb") as handle:
        header = tuple(next(csv.reader([handle.readline().decode("utf-8")])))
        if header != EXPECTED_FEATURE_HEADER:
            raise GateFailure("GATE_3_FEATURE_SCHEMA", f"unexpected feature header: {header}")
        for raw_line in handle:
            if not raw_line.strip():
                continue
            if raw_csv_field(raw_line, 1) not in date_bytes:
                non_b_feature_rows_rejected_before_parse += 1
                continue
            row = parse_one_csv_line(raw_line)
            if len(row) != len(header):
                raise GateFailure("GATE_3_FEATURE_SCHEMA", "malformed B feature row")
            market, target_date = row[0], row[1]
            key = (market, target_date)
            if key in feature_rows:
                raise GateFailure("GATE_3_FEATURE_COVERAGE", f"duplicate B feature row {key}")
            values = np.asarray([float(value) for value in row[2:]], dtype=np.float64)
            if not np.all(np.isfinite(values)):
                raise GateFailure("GATE_3_FEATURE_COVERAGE", f"non-finite B feature row {key}")
            # The extract is native-unit by design.  Convert the one mixed-unit field before the
            # within-market scaling required by the protocol.
            unit = manifest["temperature_unit_by_market"].get(market)
            if unit == "fahrenheit":
                values[0] = (values[0] - 32.0) * 5.0 / 9.0
            elif unit != "celsius":
                raise GateFailure(
                    "GATE_3_FEATURE_PROVENANCE",
                    f"unexpected temperature unit for {market}: {unit}",
                )
            feature_rows[key] = values

    expected_keys = {(market, date) for market in EXPECTED_MARKETS for date in date_set}
    missing = sorted(expected_keys - set(feature_rows))
    extra = sorted(set(feature_rows) - expected_keys)
    if missing or extra:
        raise GateFailure(
            "GATE_3_FEATURE_COVERAGE",
            f"B feature key mismatch: missing={missing[:3]} extra={extra[:3]}",
        )
    feature_support = {
        "feature_sha256": feature_digest,
        "protocol_sha256": protocol_digest,
        "manifest_sha256": sha256(FEATURE_MANIFEST_PATH),
        "source": manifest["source"],
        "issue_time_basis": manifest["issue_time_basis"],
        "lead_days": manifest["lead_days"],
        "valid_local_hours_inclusive": manifest["valid_local_hours_inclusive"],
        "manifest_hourly_values_consumed": manifest["hourly_values_consumed"],
        "B_feature_rows_parsed": len(feature_rows),
        "B_feature_values_materialized": len(feature_rows) * len(FEATURES),
        "non_B_feature_rows_rejected_before_csv_parse": non_b_feature_rows_rejected_before_parse,
        "C_feature_rows_parsed": 0,
        "missing_B_market_date_rows": len(missing),
        "duplicate_B_market_date_rows": 0,
        "nonfinite_B_feature_values": 0,
        "temperature_converted_to_celsius_before_scaling": True,
        "standardized_in_extract": manifest["standardized"],
    }
    return feature_rows, feature_support


def scaled_features(
    raw_features: dict[tuple[str, str], np.ndarray], train_dates: list[str]
) -> tuple[dict[tuple[str, str], np.ndarray], dict[str, dict[str, list[float]]]]:
    scaled: dict[tuple[str, str], np.ndarray] = {}
    diagnostics: dict[str, dict[str, list[float]]] = {}
    for market in EXPECTED_MARKETS:
        matrix = np.stack([raw_features[(market, date)] for date in train_dates])
        means = matrix.mean(axis=0)
        stds = matrix.std(axis=0, ddof=0)
        zero = np.flatnonzero(stds == 0.0)
        if len(zero):
            names = [FEATURES[index] for index in zero]
            raise GateFailure(
                "GATE_3_ZERO_SCALING_SD",
                f"zero B-only population SD for {market} on {len(train_dates)} dates: {names}",
            )
        for date in train_dates:
            scaled[(market, date)] = (raw_features[(market, date)] - means) / stds
        diagnostics[market] = {
            "mean": means.tolist(),
            "population_sd": stds.tolist(),
        }
    return scaled, diagnostics


def snapshot_weights(snapshots: list[Snapshot]) -> np.ndarray:
    counts = Counter(snapshot.market_day for snapshot in snapshots)
    return np.asarray([1.0 / counts[snapshot.market_day] for snapshot in snapshots], dtype=float)


def candidate_probability(snapshot: Snapshot, eta: float) -> np.ndarray:
    positive = snapshot.incumbent > 0.0
    log_terms = np.log(snapshot.incumbent[positive]) + snapshot.ordered_coordinate[positive] * eta
    maximum = float(log_terms.max())
    exp_terms = np.exp(log_terms - maximum)
    candidate = np.zeros_like(snapshot.incumbent)
    candidate[positive] = exp_terms / exp_terms.sum()
    return candidate


def objective_gradient_hessian(
    beta: np.ndarray,
    snapshots: list[Snapshot],
    x_by_market_day: dict[tuple[str, str], np.ndarray],
    weights: np.ndarray,
) -> tuple[float, np.ndarray, np.ndarray, float]:
    objective = 0.5 * LAMBDA * float(beta @ beta)
    unpenalized = 0.0
    gradient = LAMBDA * beta.copy()
    hessian = LAMBDA * np.eye(len(beta), dtype=float)
    for weight, snapshot in zip(weights, snapshots, strict=True):
        x = x_by_market_day[snapshot.market_day]
        eta = float(x @ beta)
        candidate = candidate_probability(snapshot, eta)
        winner_probability = candidate[snapshot.winner]
        if winner_probability <= 0.0:
            raise GateFailure("GATE_3_NUMERICAL", f"zero fitted winner probability: {snapshot.key}")
        loss = -math.log(winner_probability)
        objective += weight * loss
        unpenalized += weight * loss
        mean_r = float(candidate @ snapshot.ordered_coordinate)
        mean_r2 = float(candidate @ (snapshot.ordered_coordinate**2))
        score = mean_r - float(snapshot.ordered_coordinate[snapshot.winner])
        variance = max(0.0, mean_r2 - mean_r * mean_r)
        gradient += weight * score * x
        hessian += weight * variance * np.outer(x, x)
    return objective, gradient, hessian, unpenalized


def objective_only(
    beta: np.ndarray,
    snapshots: list[Snapshot],
    x_by_market_day: dict[tuple[str, str], np.ndarray],
    weights: np.ndarray,
) -> float:
    objective = 0.5 * LAMBDA * float(beta @ beta)
    for weight, snapshot in zip(weights, snapshots, strict=True):
        eta = float(x_by_market_day[snapshot.market_day] @ beta)
        probability = candidate_probability(snapshot, eta)[snapshot.winner]
        if probability <= 0.0:
            return math.inf
        objective -= weight * math.log(probability)
    return objective


def fit_once_from_zeros(
    snapshots: list[Snapshot], x_by_market_day: dict[tuple[str, str], np.ndarray]
) -> FitResult:
    beta = np.zeros(len(FEATURES), dtype=float)
    weights = snapshot_weights(snapshots)
    relative_change = math.inf
    total_halvings = 0
    iterations = 0

    for _ in range(MAX_OPTIMIZER_ITERATIONS + 1):
        objective, gradient, hessian, unpenalized = objective_gradient_hessian(
            beta, snapshots, x_by_market_day, weights
        )
        gradient_norm = float(np.linalg.norm(gradient, ord=np.inf))
        if gradient_norm <= GRADIENT_TOLERANCE and relative_change <= OBJECTIVE_RELATIVE_TOLERANCE:
            return FitResult(
                beta=beta,
                objective=objective,
                unpenalized_nll=unpenalized,
                penalty=0.5 * LAMBDA * float(beta @ beta),
                gradient_inf_norm=gradient_norm,
                iterations=iterations,
                relative_objective_change=relative_change,
                converged=True,
                line_search_halvings=total_halvings,
            )
        if iterations >= MAX_OPTIMIZER_ITERATIONS:
            break
        try:
            direction = np.linalg.solve(hessian, -gradient)
        except np.linalg.LinAlgError as exc:
            raise GateFailure("GATE_3_CONVERGENCE", f"singular Newton Hessian: {exc}") from exc
        directional_derivative = float(gradient @ direction)
        if not math.isfinite(directional_derivative) or directional_derivative >= 0.0:
            raise GateFailure("GATE_3_CONVERGENCE", "Newton direction is not descending")

        step = 1.0
        accepted = False
        for halvings in range(61):
            trial = beta + step * direction
            trial_objective = objective_only(trial, snapshots, x_by_market_day, weights)
            if trial_objective <= objective + 1e-4 * step * directional_derivative:
                accepted = True
                total_halvings += halvings
                break
            step *= 0.5
        if not accepted:
            raise GateFailure("GATE_3_CONVERGENCE", "deterministic line search failed")
        relative_change = abs(objective - trial_objective) / max(1.0, abs(objective))
        beta = trial
        iterations += 1

    final_objective, final_gradient, _, final_unpenalized = objective_gradient_hessian(
        beta, snapshots, x_by_market_day, weights
    )
    return FitResult(
        beta=beta,
        objective=final_objective,
        unpenalized_nll=final_unpenalized,
        penalty=0.5 * LAMBDA * float(beta @ beta),
        gradient_inf_norm=float(np.linalg.norm(final_gradient, ord=np.inf)),
        iterations=iterations,
        relative_objective_change=relative_change,
        converged=False,
        line_search_halvings=total_halvings,
    )


def serialize_fit(fit: FitResult) -> dict[str, object]:
    return {
        "beta": {feature: float(value) for feature, value in zip(FEATURES, fit.beta, strict=True)},
        "objective": fit.objective,
        "unpenalized_weighted_nll": fit.unpenalized_nll,
        "penalty": fit.penalty,
        "gradient_inf_norm": fit.gradient_inf_norm,
        "iterations": fit.iterations,
        "relative_objective_change": fit.relative_objective_change,
        "converged": fit.converged,
        "line_search_halvings": fit.line_search_halvings,
        "initial_beta": [0.0] * len(FEATURES),
        "optimizer_runs": 1,
    }


def assert_converged(fit: FitResult, label: str) -> None:
    if not fit.converged or fit.gradient_inf_norm > GRADIENT_TOLERANCE:
        raise GateFailure(
            "GATE_3_CONVERGENCE",
            f"{label} did not converge: converged={fit.converged} "
            f"gradient_inf={fit.gradient_inf_norm:.17g}",
        )


def score(
    snapshots: list[Snapshot],
    beta: np.ndarray,
    x_by_market_day: dict[tuple[str, str], np.ndarray],
    safety: SafetyAccumulator,
) -> dict[str, float | int]:
    incumbent_sse = 0.0
    candidate_sse = 0.0
    rows = 0
    for snapshot in snapshots:
        candidate = candidate_probability(snapshot, float(x_by_market_day[snapshot.market_day] @ beta))
        safety.update(snapshot, candidate)
        incumbent_sse += float(np.sum((snapshot.incumbent - snapshot.outcome) ** 2))
        candidate_sse += float(np.sum((candidate - snapshot.outcome) ** 2))
        rows += len(snapshot.incumbent)
    return {
        "band_rows": rows,
        "snapshots": len(snapshots),
        "market_days": len({snapshot.market_day for snapshot in snapshots}),
        "incumbent_sse": incumbent_sse,
        "candidate_sse": candidate_sse,
        "incumbent_brier": incumbent_sse / rows,
        "candidate_brier": candidate_sse / rows,
        "improvement": (incumbent_sse - candidate_sse) / rows,
    }


def make_x_map(
    scaled: dict[tuple[str, str], np.ndarray], snapshots: list[Snapshot]
) -> dict[tuple[str, str], np.ndarray]:
    market_days = {snapshot.market_day for snapshot in snapshots}
    missing = sorted(market_days - set(scaled))
    if missing:
        raise GateFailure("GATE_3_FEATURE_COVERAGE", f"missing scaled feature rows: {missing[:3]}")
    return {market_day: scaled[market_day] for market_day in market_days}


def base_result(support: dict[str, object], feature_support: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "pit_field_B_only_screen_result_v1",
        "mission": "-09-63a",
        "protocol": "B_only_screen_before_C_is_accessible",
        "deterministic_seed_audit_identifier": DETERMINISTIC_SEED,
        "rng_invoked": False,
        "lambda": LAMBDA,
        "intercept": False,
        "optimizer": "deterministic damped Newton with analytic gradient/Hessian",
        "gradient_tolerance": GRADIENT_TOLERANCE,
        "objective_relative_tolerance": OBJECTIVE_RELATIVE_TOLERANCE,
        "population_standard_deviation_ddof": 0,
        "scaling_population": "all 12 feature rows on each training B date, separately by market",
        "candidate_input_probability": "repair_probability on raw-prefiltered B rows only",
        "support": support,
        "feature_integrity": feature_support,
        "C_access": {
            "C_outcomes_read": False,
            "C_market_probabilities_read": False,
            "C_candidate_probabilities_read_or_computed": False,
            "C_endpoints_computed": False,
            "C_MDE_computed": False,
            "bootstrap_draws_computed": False,
            "clone_control_computed": False,
            "decision_10_spent": False,
        },
        "campaign_accounting": {
            "alpha_spent": 7,
            "alpha_budget": 20,
            "available": 13,
            "decision_10": "ALLOCATED_UNSPENT",
        },
    }


def write_result(result: dict[str, object]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )


def run(validate_only: bool) -> int:
    snapshots, support = read_b_panel()
    dates = list(support["dates"])
    raw_features, feature_support = read_b_features(dates)
    result = base_result(support, feature_support)

    try:
        full_scaled, full_scaling = scaled_features(raw_features, dates)
    except GateFailure as failure:
        result.update(
            {
                "verdict": "NO_GO_GATE_3",
                "failed_gate": failure.gate,
                "failure": str(failure),
            }
        )
        write_result(result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 3

    result["full_B_scaling"] = {
        "training_dates": len(dates),
        "per_market": full_scaling,
    }
    if validate_only:
        result["verdict"] = "VALIDATION_ONLY_NO_FIT"
        write_result(result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    safety = SafetyAccumulator()
    full_x = make_x_map(full_scaled, snapshots)
    full_fit = fit_once_from_zeros(snapshots, full_x)
    assert_converged(full_fit, "full B fit")
    full_score = score(snapshots, full_fit.beta, full_x, safety)
    safety.assert_pass()
    result["full_B_fit"] = serialize_fit(full_fit)
    result["gate_1_full_B"] = full_score

    # Gate 1 is sequential and fatal.  Do not manufacture a partial win by continuing to OOF.
    if float(full_score["improvement"]) <= 0.0:
        result.update(
            {
                "verdict": "NO_GO_GATE_1",
                "failed_gate": "GATE_1_FULL_B_BRIER",
                "failure": "full-B candidate did not beat incumbent total B Brier",
                "safety": vars(safety),
            }
        )
        write_result(result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 10

    oof_curve: list[dict[str, object]] = []
    oof_incumbent_sse = 0.0
    oof_candidate_sse = 0.0
    oof_rows = 0
    for index in range(10, len(dates)):
        train_dates = dates[:index]
        score_date = dates[index]
        train_snapshots = [snapshot for snapshot in snapshots if snapshot.target_date in train_dates]
        score_snapshots = [snapshot for snapshot in snapshots if snapshot.target_date == score_date]
        fold_scaled, _ = scaled_features(raw_features, train_dates)
        train_x = make_x_map(fold_scaled, train_snapshots)
        fold_fit = fit_once_from_zeros(train_snapshots, train_x)
        assert_converged(fold_fit, f"OOF score date {score_date}")
        # Apply training-only means/SDs to the held-out date.  Never recompute them with score_date.
        held_out_scaled: dict[tuple[str, str], np.ndarray] = {}
        for market in EXPECTED_MARKETS:
            market_matrix = np.stack([raw_features[(market, date)] for date in train_dates])
            mean = market_matrix.mean(axis=0)
            std = market_matrix.std(axis=0, ddof=0)
            held_out_scaled[(market, score_date)] = (
                raw_features[(market, score_date)] - mean
            ) / std
        score_x = make_x_map(held_out_scaled, score_snapshots)
        fold_score = score(score_snapshots, fold_fit.beta, score_x, safety)
        safety.assert_pass()
        oof_incumbent_sse += float(fold_score["incumbent_sse"])
        oof_candidate_sse += float(fold_score["candidate_sse"])
        oof_rows += int(fold_score["band_rows"])
        oof_curve.append(
            {
                "score_date": score_date,
                "training_date_count": len(train_dates),
                "training_date_min": train_dates[0],
                "training_date_max": train_dates[-1],
                **fold_score,
                "cumulative_incumbent_brier": oof_incumbent_sse / oof_rows,
                "cumulative_candidate_brier": oof_candidate_sse / oof_rows,
                "cumulative_improvement": (oof_incumbent_sse - oof_candidate_sse) / oof_rows,
                "fit": serialize_fit(fold_fit),
            }
        )

    oof = {
        "score_dates": len(oof_curve),
        "date_min": oof_curve[0]["score_date"],
        "date_max": oof_curve[-1]["score_date"],
        "band_rows": oof_rows,
        "incumbent_sse": oof_incumbent_sse,
        "candidate_sse": oof_candidate_sse,
        "incumbent_brier": oof_incumbent_sse / oof_rows,
        "candidate_brier": oof_candidate_sse / oof_rows,
        "improvement": (oof_incumbent_sse - oof_candidate_sse) / oof_rows,
    }
    result["gate_2_expanding_window"] = oof
    result["expanding_window_curve"] = oof_curve
    result["safety"] = vars(safety)

    if float(oof["improvement"]) <= 0.0:
        result.update(
            {
                "verdict": "NO_GO_GATE_2",
                "failed_gate": "GATE_2_EXPANDING_WINDOW_BRIER",
                "failure": "13-date expanding-window candidate did not beat incumbent on OOF rows",
            }
        )
        write_result(result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 11

    result.update(
        {
            "verdict": "GO_B_SCREEN_ONLY",
            "failed_gate": None,
            "meaning": "earns only the right to open C later under decision 10",
        }
    )
    write_result(result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="verify hashes, B-only parsing, support, provenance, coverage, and full-B scaling; do not fit",
    )
    args = parser.parse_args()
    try:
        return run(validate_only=args.validate_only)
    except GateFailure as failure:
        result = {
            "schema_version": "pit_field_B_only_screen_result_v1",
            "mission": "-09-63a",
            "verdict": "NO_GO_GATE_3",
            "failed_gate": failure.gate,
            "failure": str(failure),
            "deterministic_seed_audit_identifier": DETERMINISTIC_SEED,
            "C_access": {
                "C_outcomes_read": False,
                "C_market_probabilities_read": False,
                "C_candidate_probabilities_read_or_computed": False,
                "C_endpoints_computed": False,
                "C_MDE_computed": False,
                "bootstrap_draws_computed": False,
                "clone_control_computed": False,
                "decision_10_spent": False,
            },
            "campaign_accounting": {
                "alpha_spent": 7,
                "alpha_budget": 20,
                "available": 13,
                "decision_10": "ALLOCATED_UNSPENT",
            },
        }
        write_result(result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
