"""Audit exact zeros on the realized band in the sealed repaired panel.

This is a deterministic panel-integrity census. It fits no parameter, constructs
no candidate, and has no accept rule. The crossed bootstrap intervals describe
cluster dispersion only; they do not allocate or spend campaign alpha.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
DEFAULT_SEED = Path(__file__).with_name("repair_zero_audit_09_64a_seed.json")
DEFAULT_OUTPUT = REPO / "scratch" / "runs" / "repair-zero-audit-2026-09-64a"

SNAPSHOT_KEYS = [
    "snapshot_id",
    "record_hash",
    "target_date",
    "stratum",
    "market_id",
    "capture_hour",
    "effective_cutoff_hour",
]
CELL_KEYS = ["stratum", "target_date", "market_id"]
REQUIRED_COLUMNS = SNAPSHOT_KEYS + [
    "band_index",
    "outcome",
    "market_probability",
    "market_squared_error",
    "control_probability",
    "repair_probability",
    "control_squared_error",
    "repair_squared_error",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-manifest", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_seed(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(payload.get("schema_version") == "repair_zero_audit_seed_v1", "wrong seed schema")
    return payload


def load_and_validate(input_path: Path, seed: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    expected = seed["input"]
    actual_hash = sha256(input_path)
    require(actual_hash == expected["sha256"], f"input SHA-256 mismatch: {actual_hash}")

    frame = pd.read_csv(
        input_path,
        dtype={
            "snapshot_id": str,
            "record_hash": str,
            "target_date": str,
            "stratum": str,
            "market_id": str,
        },
    )
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    require(not missing, f"missing required columns: {missing}")
    frame = frame[REQUIRED_COLUMNS].sort_values(SNAPSHOT_KEYS + ["band_index"]).reset_index(drop=True)
    require(len(frame) == expected["expected_band_rows"], "band-row count mismatch")
    require(set(frame["stratum"].unique()) == {"B", "C"}, "unexpected strata")
    require((frame["target_date"] < seed["regime_boundary"]).all(), "row crosses 2026-07-31 boundary")

    books = (
        frame.groupby(SNAPSHOT_KEYS, sort=False)
        .agg(
            band_rows=("outcome", "size"),
            outcome_sum=("outcome", "sum"),
            market_mass=("market_probability", "sum"),
            control_mass=("control_probability", "sum"),
            repair_mass=("repair_probability", "sum"),
        )
        .reset_index()
    )
    require(len(books) == expected["expected_snapshot_rows"], "snapshot count mismatch")
    require((books["band_rows"] == 11).all(), "a snapshot does not carry exactly 11 bands")
    require((books["outcome_sum"] == 1).all(), "a snapshot does not carry exactly one realized band")
    tolerance = float(seed["probability"]["mass_tolerance"])
    # Market rows are captured yes prices and are not normalized categorical
    # probabilities. Only the two model surfaces carry a unit-mass contract.
    for column in ("control_mass", "repair_mass"):
        require(float((books[column] - 1.0).abs().max()) <= tolerance, f"probability mass failed: {column}")

    for probability, squared_error in (
        ("market_probability", "market_squared_error"),
        ("control_probability", "control_squared_error"),
        ("repair_probability", "repair_squared_error"),
    ):
        reconstructed = (frame[probability] - frame["outcome"]) ** 2
        require(
            bool(np.allclose(reconstructed, frame[squared_error], rtol=0.0, atol=1e-12)),
            f"squared-error identity failed: {squared_error}",
        )

    winners = frame.loc[frame["outcome"] == 1].copy()
    require(len(winners) == len(books), "winner extraction did not return one row per snapshot")

    support = {
        "band_rows": int(len(frame)),
        "snapshot_rows": int(len(winners)),
        "date_clusters": int(frame["target_date"].nunique()),
        "market_clusters": int(frame["market_id"].nunique()),
        "market_days": int(frame[["target_date", "market_id"]].drop_duplicates().shape[0]),
        "max_mass_error": {
            column: float((books[column] - 1.0).abs().max())
            for column in ("control_mass", "repair_mass")
        },
        "market_price_sum_range": [
            float(books["market_mass"].min()),
            float(books["market_mass"].max()),
        ],
    }
    for key in ("band_rows", "snapshot_rows", "date_clusters", "market_clusters", "market_days"):
        require(support[key] == expected[f"expected_{key}"], f"support mismatch: {key}")

    for stratum, stratum_expected in expected["expected_strata"].items():
        scoped = frame[frame["stratum"] == stratum]
        scoped_winners = winners[winners["stratum"] == stratum]
        observed = {
            "band_rows": int(len(scoped)),
            "snapshot_rows": int(len(scoped_winners)),
            "date_clusters": int(scoped["target_date"].nunique()),
            "market_clusters": int(scoped["market_id"].nunique()),
            "market_days": int(scoped[["target_date", "market_id"]].drop_duplicates().shape[0]),
        }
        require(observed == stratum_expected, f"stratum support mismatch: {stratum}: {observed}")
        support[stratum] = observed
    return frame, winners, support


def attach_zero_snapshot_flag(frame: pd.DataFrame, winners: pd.DataFrame) -> pd.DataFrame:
    zero_keys = winners.loc[winners["repair_probability"] == 0.0, SNAPSHOT_KEYS].copy()
    zero_keys["repair_zero_snapshot"] = True
    flagged = frame.merge(zero_keys, on=SNAPSHOT_KEYS, how="left", validate="many_to_one")
    flagged["repair_zero_snapshot"] = flagged["repair_zero_snapshot"].fillna(False).astype(bool)
    flagged["kept_band"] = (~flagged["repair_zero_snapshot"]).astype(int)
    for surface in ("market", "control", "repair"):
        flagged[f"kept_{surface}_sse"] = np.where(
            flagged["repair_zero_snapshot"],
            0.0,
            flagged[f"{surface}_squared_error"],
        )
    return flagged


def build_cells(frame: pd.DataFrame, winners: pd.DataFrame) -> pd.DataFrame:
    winner_cells = (
        winners.assign(
            repair_zero=(winners["repair_probability"] == 0.0).astype(int),
            control_zero=(winners["control_probability"] == 0.0).astype(int),
        )
        .groupby(CELL_KEYS, sort=True)
        .agg(
            snapshot_count=("outcome", "size"),
            repair_zero_count=("repair_zero", "sum"),
            control_zero_count=("control_zero", "sum"),
        )
        .reset_index()
    )
    band_cells = (
        frame.groupby(CELL_KEYS, sort=True)
        .agg(
            band_count=("outcome", "size"),
            repair_sse=("repair_squared_error", "sum"),
            control_sse=("control_squared_error", "sum"),
            market_sse=("market_squared_error", "sum"),
            kept_band_count=("kept_band", "sum"),
            kept_repair_sse=("kept_repair_sse", "sum"),
            kept_control_sse=("kept_control_sse", "sum"),
            kept_market_sse=("kept_market_sse", "sum"),
        )
        .reset_index()
    )
    return band_cells.merge(winner_cells, on=CELL_KEYS, validate="one_to_one")


def crossed_draws(cells: pd.DataFrame, seed: dict[str, Any]) -> pd.DataFrame:
    replicates = int(seed["bootstrap"]["replicates"])
    base_seed = int(seed["bootstrap"]["seed"])
    rows: list[dict[str, Any]] = []
    value_columns = [
        "band_count",
        "repair_sse",
        "control_sse",
        "market_sse",
        "kept_band_count",
        "kept_repair_sse",
        "kept_control_sse",
        "kept_market_sse",
        "snapshot_count",
        "repair_zero_count",
        "control_zero_count",
    ]
    for stratum_offset, stratum in enumerate(("B", "C")):
        scoped = cells[cells["stratum"] == stratum].reset_index(drop=True)
        dates = sorted(scoped["target_date"].unique())
        markets = sorted(scoped["market_id"].unique())
        date_map = {value: index for index, value in enumerate(dates)}
        market_map = {value: index for index, value in enumerate(markets)}
        date_index = np.asarray([date_map[value] for value in scoped["target_date"]], dtype=int)
        market_index = np.asarray([market_map[value] for value in scoped["market_id"]], dtype=int)
        values = {column: scoped[column].to_numpy(dtype=float) for column in value_columns}
        rng = np.random.default_rng(base_seed + stratum_offset)
        accepted = 0
        attempts = 0
        while accepted < replicates:
            attempts += 1
            require(attempts <= replicates * 2, f"too many empty crossed draws: {stratum}")
            date_counts = np.bincount(rng.integers(0, len(dates), len(dates)), minlength=len(dates))
            market_counts = np.bincount(
                rng.integers(0, len(markets), len(markets)), minlength=len(markets)
            )
            weights = date_counts[date_index] * market_counts[market_index]
            band_count = float(np.dot(weights, values["band_count"]))
            kept_band_count = float(np.dot(weights, values["kept_band_count"]))
            snapshot_count = float(np.dot(weights, values["snapshot_count"]))
            if min(band_count, kept_band_count, snapshot_count) <= 0.0:
                continue
            repair_brier = float(np.dot(weights, values["repair_sse"]) / band_count)
            control_brier = float(np.dot(weights, values["control_sse"]) / band_count)
            market_brier = float(np.dot(weights, values["market_sse"]) / band_count)
            kept_repair_brier = float(np.dot(weights, values["kept_repair_sse"]) / kept_band_count)
            kept_control_brier = float(np.dot(weights, values["kept_control_sse"]) / kept_band_count)
            kept_market_brier = float(np.dot(weights, values["kept_market_sse"]) / kept_band_count)
            repair_zero_count = float(np.dot(weights, values["repair_zero_count"]))
            control_zero_count = float(np.dot(weights, values["control_zero_count"]))
            gap = repair_brier - market_brier
            kept_gap = kept_repair_brier - kept_market_brier
            rows.append(
                {
                    "stratum": stratum,
                    "replicate": accepted,
                    "repair_zero_rate": repair_zero_count / snapshot_count,
                    "control_zero_rate": control_zero_count / snapshot_count,
                    "zero_rate_delta": (repair_zero_count - control_zero_count) / snapshot_count,
                    "repair_zero_brier_contribution": repair_zero_count / band_count,
                    "repair_brier": repair_brier,
                    "control_brier": control_brier,
                    "market_brier": market_brier,
                    "gap": gap,
                    "diagnostic_gap_excluding_zero_snapshots": kept_gap,
                    "diagnostic_gap_delta": kept_gap - gap,
                    "diagnostic_control_gap_excluding_repair_zero_snapshots": (
                        kept_control_brier - kept_market_brier
                    ),
                }
            )
            accepted += 1
    return pd.DataFrame(rows)


def interval(draws: pd.DataFrame, column: str, seed: dict[str, Any]) -> list[float]:
    low, high = (float(value) for value in seed["bootstrap"]["interval_quantiles"])
    return [float(draws[column].quantile(low)), float(draws[column].quantile(high))]


def surface_zero_summary(
    scoped: pd.DataFrame,
    probability_column: str,
    draws: pd.DataFrame,
    draw_column: str,
    upper: float,
    seed: dict[str, Any],
) -> dict[str, Any]:
    exact = scoped[probability_column] == 0.0
    small = (scoped[probability_column] > 0.0) & (scoped[probability_column] < upper)
    affected = scoped.loc[exact]
    return {
        "exact_zero_count": int(exact.sum()),
        "exact_zero_rate": float(exact.mean()),
        "exact_zero_rate_crossed_95_interval": interval(draws, draw_column, seed),
        "between_zero_and_1e_6_count": int(small.sum()),
        "between_zero_and_1e_6_rate": float(small.mean()),
        "affected_dates": sorted(affected["target_date"].unique().tolist()),
        "affected_date_clusters": int(affected["target_date"].nunique()),
        "affected_markets": sorted(affected["market_id"].unique().tolist()),
        "affected_market_clusters": int(affected["market_id"].nunique()),
        "affected_market_days": int(
            affected[["target_date", "market_id"]].drop_duplicates().shape[0]
        ),
    }


def overlap_summary(scoped: pd.DataFrame) -> dict[str, Any]:
    repair = scoped["repair_probability"] == 0.0
    control = scoped["control_probability"] == 0.0
    control_days = set(
        map(tuple, scoped.loc[control, ["target_date", "market_id"]].itertuples(index=False, name=None))
    )
    repair_days = set(
        map(tuple, scoped.loc[repair, ["target_date", "market_id"]].itertuples(index=False, name=None))
    )
    repair_on_control_day = scoped.apply(
        lambda row: bool(repair.loc[row.name]) and (row["target_date"], row["market_id"]) in control_days,
        axis=1,
    )
    repair_only = repair & ~control
    repair_only_on_control_day = scoped.apply(
        lambda row: bool(repair_only.loc[row.name])
        and (row["target_date"], row["market_id"]) in control_days,
        axis=1,
    )
    return {
        "snapshot_counts": {
            "both_zero": int((repair & control).sum()),
            "repair_only_zero": int(repair_only.sum()),
            "control_only_zero": int((control & ~repair).sum()),
            "neither_zero": int((~repair & ~control).sum()),
            "repair_zero_on_control_affected_market_day": int(repair_on_control_day.sum()),
            "repair_only_zero_on_control_affected_market_day": int(
                repair_only_on_control_day.sum()
            ),
        },
        "market_day_counts": {
            "repair_affected": len(repair_days),
            "control_affected": len(control_days),
            "intersection": len(repair_days & control_days),
            "repair_only": len(repair_days - control_days),
            "control_only": len(control_days - repair_days),
            "union": len(repair_days | control_days),
        },
        "repair_affected_market_days_all_already_control_affected": bool(
            repair_days <= control_days
        ),
    }


def main() -> None:
    args = parse_args()
    seed_path = args.seed_manifest.resolve()
    seed = load_seed(seed_path)
    input_path = (args.input or (REPO / seed["input"]["relative_path"])).resolve()
    output_dir = args.output_dir.resolve()
    frame, winners, support = load_and_validate(input_path, seed)
    frame = attach_zero_snapshot_flag(frame, winners)
    cells = build_cells(frame, winners)
    draws = crossed_draws(cells, seed)

    celsius = set(seed["units"]["celsius_markets"])
    winners["unit"] = np.where(winners["market_id"].isin(celsius), "C", "F")
    upper = float(seed["probability"]["empty_interval_upper_exclusive"])
    served_rate = (
        float(seed["references"]["served_realized_zero_count"])
        / float(seed["references"]["served_snapshot_count"])
    )

    by_market = (
        winners.assign(
            repair_zero=(winners["repair_probability"] == 0.0).astype(int),
            control_zero=(winners["control_probability"] == 0.0).astype(int),
            repair_small=(
                (winners["repair_probability"] > 0.0)
                & (winners["repair_probability"] < upper)
            ).astype(int),
            control_small=(
                (winners["control_probability"] > 0.0)
                & (winners["control_probability"] < upper)
            ).astype(int),
        )
        .groupby(["stratum", "unit", "market_id"], sort=True)
        .agg(
            snapshots=("outcome", "size"),
            repair_exact_zero=("repair_zero", "sum"),
            control_exact_zero=("control_zero", "sum"),
            repair_between_zero_and_1e_6=("repair_small", "sum"),
            control_between_zero_and_1e_6=("control_small", "sum"),
            dates=("target_date", "nunique"),
        )
        .reset_index()
    )
    by_market["repair_exact_zero_rate"] = by_market["repair_exact_zero"] / by_market["snapshots"]
    by_market["control_exact_zero_rate"] = by_market["control_exact_zero"] / by_market["snapshots"]

    by_date = (
        winners.assign(
            repair_zero=(winners["repair_probability"] == 0.0).astype(int),
            control_zero=(winners["control_probability"] == 0.0).astype(int),
        )
        .groupby(["stratum", "target_date"], sort=True)
        .agg(
            snapshots=("outcome", "size"),
            markets=("market_id", "nunique"),
            repair_exact_zero=("repair_zero", "sum"),
            control_exact_zero=("control_zero", "sum"),
        )
        .reset_index()
    )
    by_date["repair_exact_zero_rate"] = by_date["repair_exact_zero"] / by_date["snapshots"]
    by_date["control_exact_zero_rate"] = by_date["control_exact_zero"] / by_date["snapshots"]

    affected_market_days = (
        winners.assign(
            repair_zero=(winners["repair_probability"] == 0.0).astype(int),
            control_zero=(winners["control_probability"] == 0.0).astype(int),
        )
        .groupby(["stratum", "unit", "target_date", "market_id"], sort=True)
        .agg(
            snapshots=("outcome", "size"),
            repair_exact_zero=("repair_zero", "sum"),
            control_exact_zero=("control_zero", "sum"),
        )
        .reset_index()
    )
    affected_market_days = affected_market_days[
        (affected_market_days["repair_exact_zero"] > 0)
        | (affected_market_days["control_exact_zero"] > 0)
    ].reset_index(drop=True)

    result: dict[str, Any] = {
        "schema_version": "repair_zero_audit_result_v1",
        "status": "PASS",
        "mission": seed["mission"],
        "interpretation": {
            "kind": "panel_integrity_audit",
            "candidate": False,
            "fitted_parameter": False,
            "endpoint_comparison": False,
            "accept_rule": False,
            "alpha_spent": 0.0,
            "campaign_alpha_state": "7 of 20 spent, 13 available",
            "decision_10": "CLOSED UNUSED; not reassigned",
            "diagnostic_exclusion": seed["diagnostic_exclusion"],
        },
        "provenance": {
            "input_path": str(input_path),
            "input_sha256": sha256(input_path),
            "seed_manifest_path": str(seed_path),
            "seed_manifest_sha256": sha256(seed_path),
            "bootstrap_seed_B": int(seed["bootstrap"]["seed"]),
            "bootstrap_seed_C": int(seed["bootstrap"]["seed"]) + 1,
            "bootstrap_replicates_per_stratum": int(seed["bootstrap"]["replicates"]),
            "uncertainty": seed["bootstrap"]["method"],
        },
        "support": support,
        "served_reference": {
            **seed["references"],
            "served_exact_zero_rate": served_rate,
            "same_market_day_list_available_in_seed": False,
        },
        "strata": {},
    }

    for stratum in ("B", "C"):
        scoped_winners = winners[winners["stratum"] == stratum].copy()
        scoped_frame = frame[frame["stratum"] == stratum]
        scoped_draws = draws[draws["stratum"] == stratum]
        repair_zero = scoped_winners["repair_probability"] == 0.0
        control_zero = scoped_winners["control_probability"] == 0.0
        keep = ~scoped_frame["repair_zero_snapshot"]

        repair_brier = float(scoped_frame["repair_squared_error"].mean())
        control_brier = float(scoped_frame["control_squared_error"].mean())
        market_brier = float(scoped_frame["market_squared_error"].mean())
        gap = repair_brier - market_brier
        diagnostic_repair_brier = float(scoped_frame.loc[keep, "repair_squared_error"].mean())
        diagnostic_control_brier = float(scoped_frame.loc[keep, "control_squared_error"].mean())
        diagnostic_market_brier = float(scoped_frame.loc[keep, "market_squared_error"].mean())
        diagnostic_gap = diagnostic_repair_brier - diagnostic_market_brier
        zero_contribution = float(repair_zero.sum() / len(scoped_frame))

        unit_split: dict[str, Any] = {}
        for unit in ("F", "C"):
            unit_rows = scoped_winners[scoped_winners["unit"] == unit]
            unit_split[unit] = {
                "snapshots": int(len(unit_rows)),
                "repair_exact_zero_count": int((unit_rows["repair_probability"] == 0.0).sum()),
                "repair_exact_zero_rate": float((unit_rows["repair_probability"] == 0.0).mean()),
                "control_exact_zero_count": int((unit_rows["control_probability"] == 0.0).sum()),
                "control_exact_zero_rate": float((unit_rows["control_probability"] == 0.0).mean()),
            }

        result["strata"][stratum] = {
            "repair": surface_zero_summary(
                scoped_winners,
                "repair_probability",
                scoped_draws,
                "repair_zero_rate",
                upper,
                seed,
            ),
            "control": surface_zero_summary(
                scoped_winners,
                "control_probability",
                scoped_draws,
                "control_zero_rate",
                upper,
                seed,
            ),
            "repair_minus_control": {
                "exact_zero_count": int(repair_zero.sum() - control_zero.sum()),
                "exact_zero_rate": float(repair_zero.mean() - control_zero.mean()),
                "exact_zero_rate_crossed_95_interval": interval(
                    scoped_draws, "zero_rate_delta", seed
                ),
            },
            "repair_minus_served_reference": {
                "exact_zero_rate": float(repair_zero.mean() - served_rate),
                "reference_rate": served_rate,
            },
            "overlap": overlap_summary(scoped_winners),
            "unit_split": unit_split,
            "brier": {
                "band_rows": int(len(scoped_frame)),
                "repair_total": repair_brier,
                "control_total": control_brier,
                "market_total": market_brier,
                "repair_gap_vs_market": gap,
                "repair_realized_zero_sse": int(repair_zero.sum()),
                "repair_realized_zero_contribution_to_total_brier": zero_contribution,
                "repair_realized_zero_contribution_crossed_95_interval": interval(
                    scoped_draws, "repair_zero_brier_contribution", seed
                ),
                "repair_realized_zero_share_of_repair_total_brier": zero_contribution
                / repair_brier,
                "repair_realized_zero_share_of_reference_c_gap": (
                    zero_contribution / float(seed["references"]["c_gap"])
                ),
            },
            "diagnostic_excluding_complete_repair_zero_snapshots": {
                "excluded_snapshots": int(repair_zero.sum()),
                "excluded_band_rows": int((~keep).sum()),
                "remaining_snapshots": int((~repair_zero).sum()),
                "remaining_band_rows": int(keep.sum()),
                "repair_brier": diagnostic_repair_brier,
                "control_brier": diagnostic_control_brier,
                "market_brier": diagnostic_market_brier,
                "repair_gap_vs_market": diagnostic_gap,
                "gap_delta_from_full_panel": diagnostic_gap - gap,
                "repair_gap_crossed_95_interval": interval(
                    scoped_draws, "diagnostic_gap_excluding_zero_snapshots", seed
                ),
                "gap_delta_crossed_95_interval": interval(
                    scoped_draws, "diagnostic_gap_delta", seed
                ),
                "control_gap_vs_market_on_same_rows": diagnostic_control_brier
                - diagnostic_market_brier,
            },
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    by_market.to_csv(output_dir / "by-market.csv", index=False, lineterminator="\n")
    by_date.to_csv(output_dir / "by-date.csv", index=False, lineterminator="\n")
    affected_market_days.to_csv(
        output_dir / "affected-market-days.csv", index=False, lineterminator="\n"
    )
    draws.to_csv(output_dir / "crossed-draws.csv", index=False, lineterminator="\n")
    result["outputs"] = {
        name: {"path": str(output_dir / name), "sha256": sha256(output_dir / name)}
        for name in (
            "by-market.csv",
            "by-date.csv",
            "affected-market-days.csv",
            "crossed-draws.csv",
        )
    }
    summary_path = output_dir / "audit-summary.json"
    summary_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
