"""Measure whether frozen Gate 3 is satisfiable as the panel grows.

This is a deterministic, read-only research harness.  It consumes the retained
09-66a served-floor re-score, the tracked 09-66a/09-67a evidence, and three
captured production books.  It does not fit a candidate or modify any serving
or settlement contract.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_SEED = SCRIPT_PATH.with_name("gate_3_satisfiability_09_68a_seed.json")
SNAPSHOT_KEYS = ("stratum", "market_id", "target_date", "snapshot_id")
MARKET_DAY_KEYS = ("stratum", "market_id", "target_date")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_file(path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required evidence is missing: {path}")
    actual_bytes = path.stat().st_size
    actual_sha256 = _sha256(path)
    if actual_bytes != int(spec["bytes"]):
        raise RuntimeError(
            f"byte-size mismatch for {path}: {actual_bytes} != {spec['bytes']}"
        )
    if actual_sha256 != spec["sha256"]:
        raise RuntimeError(
            f"SHA-256 mismatch for {path}: {actual_sha256} != {spec['sha256']}"
        )
    return {
        "relative_path": spec["relative_path"],
        "bytes": actual_bytes,
        "sha256": actual_sha256,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _key(row: dict[str, str], fields: Iterable[str]) -> tuple[str, ...]:
    return tuple(row[field] for field in fields)


def _maybe_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def _bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"not a CSV boolean: {value!r}")


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot take a quantile of an empty sample")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _crossed_market_day_interval(
    cells: dict[tuple[str, str], int],
    *,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    dates = sorted({target_date for target_date, _ in cells})
    markets = sorted({market_id for _, market_id in cells})
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(replicates):
        date_weights = Counter(rng.choices(dates, k=len(dates)))
        market_weights = Counter(rng.choices(markets, k=len(markets)))
        numerator = 0.0
        denominator = 0.0
        for (target_date, market_id), event in cells.items():
            weight = date_weights[target_date] * market_weights[market_id]
            numerator += weight * event
            denominator += weight
        if denominator <= 0:
            raise RuntimeError("crossed bootstrap produced an empty product draw")
        draws.append(numerator / denominator)
    return {
        "point": sum(cells.values()) / len(cells),
        "crossed_95_interval": [
            _quantile(draws, 0.025),
            _quantile(draws, 0.975),
        ],
        "zero_draws": sum(value == 0.0 for value in draws),
        "replicates": replicates,
        "seed": seed,
        "date_clusters": len(dates),
        "market_clusters": len(markets),
        "market_days": len(cells),
    }


def _strict_threshold_size(rate: float, threshold: float) -> int:
    if not 0.0 < rate < 1.0:
        raise ValueError("rate must be strictly between zero and one")
    if not 0.0 < threshold < 1.0:
        raise ValueError("threshold must be strictly between zero and one")
    candidate = math.floor(math.log1p(-threshold) / math.log1p(-rate)) + 1
    while 1.0 - (1.0 - rate) ** candidate <= threshold:
        candidate += 1
    while candidate > 1 and 1.0 - (1.0 - rate) ** (candidate - 1) > threshold:
        candidate -= 1
    return candidate


def _raw_book_check(
    evidence_root: Path,
    spec: dict[str, Any],
    *,
    mass_tolerance: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = evidence_root / spec["relative_path"]
    receipt = _verify_file(path, spec)
    rows = [
        row
        for row in _read_csv(path)
        if row["snapshot_id"] == spec["snapshot_id"]
    ]
    if not rows:
        raise RuntimeError(f"snapshot {spec['snapshot_id']} absent from {path}")
    total_mass = sum(float(row["model_probability"]) for row in rows)
    if abs(total_mass - 1.0) > mass_tolerance:
        raise RuntimeError(
            f"raw production book mass failure for {spec['snapshot_id']}: {total_mass}"
        )
    realized = [
        row
        for row in rows
        if row["bin_kind"] == spec["bin_kind"]
        and int(float(row["bin_value_c"])) == int(spec["bin_value"])
    ]
    if len(realized) != 1:
        raise RuntimeError(
            f"expected one realized band in {spec['snapshot_id']}, got {len(realized)}"
        )
    row = realized[0]
    return receipt, {
        "market_id": spec["market_id"],
        "target_date": spec["target_date"],
        "snapshot_id": spec["snapshot_id"],
        "bin_kind": spec["bin_kind"],
        "bin_value": int(spec["bin_value"]),
        "range_label": row["range_label"],
        "model_probability": float(row["model_probability"]),
        "book_probability_mass": total_mass,
        "book_band_rows": len(rows),
    }


def _load_seed(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        seed = json.load(handle)
    if seed.get("schema_version") != "gate_3_satisfiability_seed_v1":
        raise RuntimeError(f"unexpected seed schema: {seed.get('schema_version')!r}")
    return seed


def analyze(
    *,
    repo_root: Path,
    evidence_root: Path,
    seed_path: Path,
) -> dict[str, Any]:
    seed = _load_seed(seed_path)
    receipts: dict[str, Any] = {}
    input_rows: dict[str, list[dict[str, str]]] = {}
    for name, spec in seed["inputs"].items():
        root = evidence_root if name.startswith("rescored_") else repo_root
        path = root / spec["relative_path"]
        receipts[name] = _verify_file(path, spec)
        rows = _read_csv(path)
        if len(rows) != int(spec["rows"]):
            raise RuntimeError(
                f"row-count mismatch for {path}: {len(rows)} != {spec['rows']}"
            )
        input_rows[name] = rows

    snapshot_rows = input_rows["rescored_snapshot_rows"]
    served_floor_rows = input_rows["served_floor"]
    settlement_rows = input_rows["settlement_provenance"]

    snapshot_by_key = {_key(row, SNAPSHOT_KEYS): row for row in snapshot_rows}
    floor_by_key = {_key(row, SNAPSHOT_KEYS): row for row in served_floor_rows}
    if len(snapshot_by_key) != len(snapshot_rows):
        raise RuntimeError("duplicate snapshot key in retained re-score")
    if len(floor_by_key) != len(served_floor_rows):
        raise RuntimeError("duplicate snapshot key in tracked served-floor evidence")
    if set(snapshot_by_key) != set(floor_by_key):
        raise RuntimeError("retained re-score and served-floor evidence keys differ")

    settlement_by_key = {
        _key(row, MARKET_DAY_KEYS): float(row["settlement_high"])
        for row in settlement_rows
    }
    if len(settlement_by_key) != len(settlement_rows):
        raise RuntimeError("duplicate market-day key in settlement provenance")
    snapshot_market_days = {
        key[:3]
        for key in snapshot_by_key
    }
    if snapshot_market_days != set(settlement_by_key):
        raise RuntimeError("snapshot and settlement market-day populations differ")

    for key, row in snapshot_by_key.items():
        snapshot_floor = _maybe_float(row["served_floor_bucket"])
        tracked_floor = _maybe_float(floor_by_key[key]["served_floor_bucket"])
        if snapshot_floor != tracked_floor:
            raise RuntimeError(
                f"served-floor mismatch for {key}: {snapshot_floor} != {tracked_floor}"
            )

    sensitivity_exclusions = {
        ("B", "chicago", "2026-06-14", "20260614T011002-0400"),
        ("B", "san-francisco", "2026-06-09", "20260609T170137-0400"),
    }
    reference = seed["reference_values"]
    mass_tolerance = float(reference["mass_tolerance"])
    probability_tolerance = float(reference["probability_tolerance"])
    b_snapshot_rows = [row for row in snapshot_rows if row["stratum"] == "B"]
    b_band_rows = int(seed["expected_support"]["B"]["band_rows"])
    if b_band_rows != len(b_snapshot_rows) * 11:
        raise RuntimeError("B retained support is not an 11-band book per snapshot")
    b_brier_sum = sum(float(row["served_floor_brier_sum"]) for row in b_snapshot_rows)
    computed_b_brier = b_brier_sum / b_band_rows
    expected_b_brier = float(reference["B_served_floor_incumbent_brier"])
    if abs(computed_b_brier - expected_b_brier) > probability_tolerance:
        raise RuntimeError(
            f"B Brier mismatch: {computed_b_brier} != {expected_b_brier}"
        )
    sensitivity_brier_sum = sum(
        float(row["served_floor_brier_sum"])
        for row in b_snapshot_rows
        if _key(row, SNAPSHOT_KEYS) not in sensitivity_exclusions
    )
    sensitivity_band_rows = b_band_rows - 11 * len(sensitivity_exclusions)

    support: dict[str, dict[str, int]] = {}
    crossing_rows: dict[str, list[dict[str, Any]]] = {"B": [], "C": []}
    zero_rows: dict[str, list[dict[str, Any]]] = {"B": [], "C": []}
    market_day_cells: dict[str, dict[tuple[str, str], int]] = {"B": {}, "C": {}}
    for stratum in ("B", "C"):
        scoped = [row for row in snapshot_rows if row["stratum"] == stratum]
        dates = {row["target_date"] for row in scoped}
        markets = {row["market_id"] for row in scoped}
        market_days = {(row["target_date"], row["market_id"]) for row in scoped}
        floor_rows = [row for row in scoped if _maybe_float(row["served_floor_bucket"]) is not None]
        support[stratum] = {
            "date_clusters": len(dates),
            "market_clusters": len(markets),
            "market_days": len(market_days),
            "snapshot_rows": len(scoped),
            "served_floor_snapshot_rows": len(floor_rows),
        }
        if stratum == "B":
            support[stratum]["band_rows"] = b_band_rows
        if support[stratum] != seed["expected_support"][stratum]:
            raise RuntimeError(
                f"{stratum} support mismatch: {support[stratum]} != "
                f"{seed['expected_support'][stratum]}"
            )
        for target_date, market_id in market_days:
            market_day_cells[stratum][(target_date, market_id)] = 0
        for row in scoped:
            key = _key(row, SNAPSHOT_KEYS)
            floor = _maybe_float(row["served_floor_bucket"])
            settlement_high = settlement_by_key[key[:3]]
            served_zero = _bool(row["served_floor_realized_zero"])
            if served_zero:
                zero_rows[stratum].append(
                    {
                        "market_id": row["market_id"],
                        "target_date": row["target_date"],
                        "snapshot_id": row["snapshot_id"],
                        "served_floor_bucket": floor,
                        "settlement_high": settlement_high,
                    }
                )
            if floor is None:
                continue
            crossed = floor > settlement_high
            if crossed != served_zero:
                raise RuntimeError(
                    f"floor-cross/served-zero identity failed for {key}: "
                    f"crossed={crossed}, zero={served_zero}"
                )
            if crossed:
                record = {
                    "market_id": row["market_id"],
                    "target_date": row["target_date"],
                    "snapshot_id": row["snapshot_id"],
                    "served_floor_bucket": floor,
                    "settlement_high": settlement_high,
                }
                crossing_rows[stratum].append(record)
                market_day_cells[stratum][(row["target_date"], row["market_id"])] = 1

    panel_support = {
        "market_days": sum(item["market_days"] for item in support.values()),
        "snapshot_rows": len(snapshot_rows),
        "served_floor_snapshot_rows": sum(
            item["served_floor_snapshot_rows"] for item in support.values()
        ),
    }
    if panel_support != seed["expected_support"]["panel"]:
        raise RuntimeError(
            f"panel support mismatch: {panel_support} != {seed['expected_support']['panel']}"
        )

    b_zero_rows = sorted(
        zero_rows["B"],
        key=lambda item: (item["target_date"], item["market_id"], item["snapshot_id"]),
    )
    if len(b_zero_rows) != 3:
        raise RuntimeError(f"expected three B zero rows, got {len(b_zero_rows)}")
    blank_b_zero_rows = [row for row in b_zero_rows if row["served_floor_bucket"] is None]
    if len(blank_b_zero_rows) != 1:
        raise RuntimeError(
            f"expected exactly one blank-floor B zero, got {len(blank_b_zero_rows)}"
        )
    if len(crossing_rows["B"]) != 2 or len(crossing_rows["C"]) != 1:
        raise RuntimeError(
            "expected two B floor crossings and one C floor crossing; "
            f"got B={len(crossing_rows['B'])}, C={len(crossing_rows['C'])}"
        )

    raw_book_receipts: dict[str, Any] = {}
    raw_book_checks: dict[str, Any] = {}
    for name, spec in seed["raw_snapshot_books"].items():
        receipt, check = _raw_book_check(
            evidence_root,
            spec,
            mass_tolerance=mass_tolerance,
        )
        raw_book_receipts[name] = receipt
        raw_book_checks[name] = check

    denver = raw_book_checks["denver_2026_06_08"]
    if abs(denver["model_probability"] - reference["denver_realized_probability"]) > probability_tolerance:
        raise RuntimeError("Denver retained production probability does not reproduce")
    denver_key = (
        "B",
        denver["market_id"],
        denver["target_date"],
        denver["snapshot_id"],
    )
    denver_floor = _maybe_float(snapshot_by_key[denver_key]["served_floor_bucket"])
    denver_settlement = settlement_by_key[denver_key[:3]]
    if denver_floor is None or denver_floor > denver_settlement:
        raise RuntimeError("Denver served floor unexpectedly zeros the realized band")

    bootstrap = seed["bootstrap"]
    market_day_rates = {
        stratum: _crossed_market_day_interval(
            market_day_cells[stratum],
            replicates=int(bootstrap["replicates"]),
            seed=int(bootstrap[f"seed_{stratum}"]),
        )
        for stratum in ("B", "C")
    }
    for stratum in ("B", "C"):
        market_day_rates[stratum]["crossed_market_days"] = sum(
            market_day_cells[stratum].values()
        )

    b_rate = market_day_rates["B"]["point"]
    panel_projection: list[dict[str, Any]] = []
    for market_days in seed["projection"]["panel_market_days"]:
        probability_no_fire = (1.0 - b_rate) ** market_days
        panel_projection.append(
            {
                "market_days": int(market_days),
                "expected_gate_3_zero_market_days": market_days * b_rate,
                "probability_gate_3_does_not_fire": probability_no_fire,
                "probability_gate_3_fires": 1.0 - probability_no_fire,
            }
        )
    observed_b_market_days = support["B"]["market_days"]
    observed_b_probability_no_fire = (1.0 - b_rate) ** observed_b_market_days
    observed_b_panel_projection = {
        "market_days": observed_b_market_days,
        "expected_gate_3_zero_market_days": observed_b_market_days * b_rate,
        "probability_gate_3_does_not_fire": observed_b_probability_no_fire,
        "probability_gate_3_fires": 1.0 - observed_b_probability_no_fire,
    }
    break_even = {
        str(threshold): {
            "first_market_day_count_strictly_above": _strict_threshold_size(
                b_rate, float(threshold)
            )
        }
        for threshold in seed["projection"]["fire_probability_thresholds"]
    }

    b_crossings = len(crossing_rows["B"])
    c_crossings = len(crossing_rows["C"])
    sensitivity_brier = sensitivity_brier_sum / sensitivity_band_rows
    result = {
        "schema_version": "gate_3_satisfiability_result_v1",
        "status": "PASS",
        "verdict": "GATE_3_IS_A_PANEL_SIZE_LIMIT",
        "mission": seed["mission"],
        "method": {
            "floor_crossing": "served_floor_bucket > settlement_high",
            "gate_3_event": "at least one realized-band zero in a B market-day",
            "uncertainty": bootstrap["method"],
            "projection": seed["projection"]["model"],
            "B_and_C_bootstrapped_separately": True,
            "pooled_across_2026_07_31": False,
        },
        "support": {"B": support["B"], "C": support["C"], "panel": panel_support},
        "reconciliation": {
            "B_served_floor_realized_zero_rows": b_zero_rows,
            "blank_floor_zero_rows": blank_b_zero_rows,
            "third_zero_has_blank_served_floor_bucket": True,
            "B_actual_floor_crossing_rows": sorted(
                crossing_rows["B"],
                key=lambda item: (item["target_date"], item["market_id"]),
            ),
            "denver": {
                **denver,
                "served_floor_bucket": denver_floor,
                "settlement_high": denver_settlement,
                "served_floor_zeros_realized_band": False,
            },
        },
        "snapshot_rates": {
            "requested_B_crossings_over_all_panel_served_floor_snapshots": {
                "numerator": b_crossings,
                "denominator": panel_support["served_floor_snapshot_rows"],
                "rate": b_crossings / panel_support["served_floor_snapshot_rows"],
                "denominator_note": "reproduces the handoff's 2/10,936 panel-served-floor denominator",
            },
            "B_within_stratum": {
                "numerator": b_crossings,
                "denominator": support["B"]["served_floor_snapshot_rows"],
                "rate": b_crossings / support["B"]["served_floor_snapshot_rows"],
            },
            "C_contrast_only": {
                "numerator": c_crossings,
                "denominator": support["C"]["served_floor_snapshot_rows"],
                "rate": c_crossings / support["C"]["served_floor_snapshot_rows"],
            },
            "C_crossings_over_all_panel_served_floor_snapshots": {
                "numerator": c_crossings,
                "denominator": panel_support["served_floor_snapshot_rows"],
                "rate": c_crossings / panel_support["served_floor_snapshot_rows"],
                "denominator_note": "direct contrast to the handoff's panel-served-floor denominator",
            },
        },
        "market_day_rates": market_day_rates,
        "panel_projection": panel_projection,
        "observed_B_panel_projection": observed_b_panel_projection,
        "break_even": break_even,
        "C_contrast": {
            "read_scope": "contrast rate only; no candidate, fitted parameter, or C endpoint",
            "crossing_rows": crossing_rows["C"],
        },
        "sensitivity_check_not_an_exclusion_rule": {
            "excluded_B_snapshots": sorted(
                [
                    {
                        **row,
                        "pre_floor_probability_on_realized_band": raw_book_checks[
                            "chicago_2026_06_14"
                            if row["market_id"] == "chicago"
                            else "san_francisco_2026_06_09"
                        ]["model_probability"],
                    }
                    for row in crossing_rows["B"]
                ],
                key=lambda item: (item["target_date"], item["market_id"]),
            ),
            "B_served_floor_brier_all_snapshots": computed_b_brier,
            "B_served_floor_brier_without_two_snapshots": sensitivity_brier,
            "signed_change": sensitivity_brier - computed_b_brier,
            "remaining_band_rows": sensitivity_band_rows,
            "licenses_exclusion_rule": False,
        },
        "evidence": {
            "inputs": receipts,
            "raw_snapshot_books": raw_book_receipts,
            "seed": {
                "relative_path": str(seed_path.relative_to(repo_root)).replace("\\", "/"),
                "bytes": seed_path.stat().st_size,
                "sha256": _sha256(seed_path),
            },
        },
        "campaign": seed["campaign"],
        "explicitly_not_done": [
            "no fitting, candidate, beta vector, Gate-1/Gate-2 computation, or C endpoint",
            "no alpha allocation or decision-10 reassignment",
            "no protocol, serving floor, high_so_far, collection, or settlement change",
            "no production write, registration, restart, merge, provider call, or exchange action",
        ],
    }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="checkout containing the tracked 09-66a/09-67a evidence",
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="workstation repository root containing ignored retained evidence and data",
    )
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    repo_root = args.repo_root.resolve()
    evidence_root = args.evidence_root.resolve()
    seed_path = args.seed.resolve()
    result = analyze(
        repo_root=repo_root,
        evidence_root=evidence_root,
        seed_path=seed_path,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "summary.json"
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "verdict": result["verdict"],
        "summary": str(output_path),
        "B_snapshot_rate": result["snapshot_rates"][
            "requested_B_crossings_over_all_panel_served_floor_snapshots"
        ],
        "B_market_day_rate": result["market_day_rates"]["B"],
        "break_even": result["break_even"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
