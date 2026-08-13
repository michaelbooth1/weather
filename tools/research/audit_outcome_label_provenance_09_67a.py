"""Audit the sealed B/C score panel by settlement-label provenance.

This is a one-off descriptive harness. It fits no parameter, creates no
candidate, changes no outcome, excludes no row, and has no accept rule. It
joins the verified -09-66a served-floor score surface to the production-built
settlement-provenance extract, then reports B and C separately with crossed
target-date x market pigeonhole intervals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
DEFAULT_SEED = Path(__file__).with_name("outcome_label_audit_09_67a_seed.json")
DEFAULT_OUTPUT = REPO / "scratch" / "runs" / "outcome-label-audit-2026-09-67a"

BAND_KEY = [
    "stratum",
    "market_id",
    "target_date",
    "snapshot_id",
    "record_hash",
    "band_index",
]
SNAPSHOT_KEY = ["stratum", "market_id", "target_date", "snapshot_id", "record_hash"]
DAY_KEY = ["stratum", "market_id", "target_date"]
CELL_GROUPS = DAY_KEY + ["coverage_bucket", "settlement_source"]
METRICS = (
    "incumbent_brier",
    "market_brier",
    "gap",
    "incumbent_centre_error_c_eq",
    "market_centre_error_c_eq",
    "incumbent_centre_error_outward_c_eq",
    "market_centre_error_outward_c_eq",
)


class IntegrityFailure(RuntimeError):
    """A pinned input or population contract failed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrityFailure(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(seed: dict[str, Any], name: str) -> Path:
    return REPO / seed["inputs"][name]["relative_path"]


def verify_inputs(seed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for name, expected in seed["inputs"].items():
        path = resolve(seed, name)
        require(path.is_file(), f"missing pinned input: {path}")
        actual_hash = sha256(path)
        require(actual_hash == expected["sha256"], f"{name} SHA-256 drifted: {actual_hash}")
        require(path.stat().st_size == int(expected["bytes"]), f"{name} byte size drifted")
        receipts[name] = {
            "path": str(path),
            "sha256": actual_hash,
            "bytes": path.stat().st_size,
        }
    return receipts


def coverage_bucket(value: float) -> str:
    require(math.isfinite(value) and value >= 0.0, f"invalid material gap: {value!r}")
    if value == 0.0:
        return "0"
    if value < 30.0:
        return "(0,30)"
    return "[30,inf)"


def load_panel(seed: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    score_columns = [
        *BAND_KEY,
        "outcome",
        "market_probability",
        "original_probability",
        "portable_baseline_probability",
        "served_floor_probability",
    ]
    identity_columns = [
        *BAND_KEY,
        "range_label",
        "bin_kind",
        "bin_value",
        "bin_value_hi",
        "outcome",
        "market_probability",
    ]
    provenance_columns = [
        *DAY_KEY,
        "settlement_source",
        "settlement_high",
        "max_gap_minutes",
        "material_coverage_max_gap_minutes",
        "daily_max_window",
    ]
    scores = pd.read_csv(
        resolve(seed, "served_floor_band_rows"),
        usecols=score_columns,
        dtype={"snapshot_id": str, "record_hash": str, "target_date": str},
    )
    identities = pd.read_csv(
        resolve(seed, "band_identity"),
        usecols=identity_columns,
        dtype={"snapshot_id": str, "record_hash": str, "target_date": str},
    )
    provenance = pd.read_csv(
        resolve(seed, "settlement_provenance"),
        usecols=provenance_columns,
        dtype={"target_date": str},
    )

    expected_rows = int(seed["inputs"]["served_floor_band_rows"]["band_rows"])
    require(len(scores) == expected_rows, f"served-floor score rows {len(scores)} != {expected_rows}")
    require(len(identities) == expected_rows, f"band identity rows {len(identities)} != {expected_rows}")
    require(len(provenance) == int(seed["inputs"]["settlement_provenance"]["market_days"]), "provenance row count drifted")
    require(not scores.duplicated(BAND_KEY).any(), "duplicate served-floor band key")
    require(not identities.duplicated(BAND_KEY).any(), "duplicate band identity key")
    require(not provenance.duplicated(DAY_KEY).any(), "duplicate settlement-provenance market-day")

    joined = scores.merge(
        identities,
        on=BAND_KEY,
        how="left",
        validate="one_to_one",
        suffixes=("", "_identity"),
    )
    require(not joined["bin_kind"].isna().any(), "band identity join missed rows")
    require(np.array_equal(joined["outcome"].to_numpy(), joined["outcome_identity"].to_numpy()), "outcome identity drifted")
    market_identity_delta = np.abs(
        joined["market_probability"].to_numpy(dtype=float)
        - joined["market_probability_identity"].to_numpy(dtype=float)
    )
    require(
        float(market_identity_delta.max()) <= float(seed["comparison_tolerance"]),
        "market probability identity drifted beyond numeric representation tolerance",
    )
    c_rows = joined["stratum"].eq("C")
    require(
        np.array_equal(
            joined.loc[c_rows, "portable_baseline_probability"].to_numpy(dtype=float),
            joined.loc[c_rows, "served_floor_probability"].to_numpy(dtype=float),
        ),
        "C moved after the verified served-floor control",
    )
    require(set(joined["stratum"]) == {"B", "C"}, "unexpected stratum")
    require((joined["target_date"] < seed["regime_boundary"]).all(), "panel crossed the 2026-07-31 boundary")
    require(set(joined["market_id"]) == set(seed["unit_factor_to_c"]), "market population drifted")

    for column in ("outcome", "market_probability", "served_floor_probability"):
        require(np.isfinite(joined[column].to_numpy(dtype=float)).all(), f"non-finite {column}")
    require(joined["outcome"].isin([0, 1]).all(), "non-binary outcome")
    require(joined["market_probability"].between(0.0, 1.0).all(), "invalid market probability")
    require(joined["served_floor_probability"].between(0.0, 1.0).all(), "invalid incumbent probability")

    joined = joined.merge(provenance, on=DAY_KEY, how="left", validate="many_to_one")
    require(not joined["settlement_source"].isna().any(), "settlement provenance join missed rows")
    require(set(provenance["settlement_source"]) <= set(seed["settlement_sources"]), "unexpected settlement source")
    provenance["coverage_bucket"] = provenance["material_coverage_max_gap_minutes"].map(coverage_bucket)
    joined["coverage_bucket"] = joined["material_coverage_max_gap_minutes"].map(coverage_bucket)

    require(
        int(provenance["settlement_source"].eq("daily_summary").sum())
        == int(seed["expected_provenance_counts"]["daily_summary"]),
        "daily_summary count drifted",
    )
    require(
        int(provenance["settlement_source"].eq("snapshot_high").sum())
        == int(seed["expected_provenance_counts"]["snapshot_high"]),
        "snapshot_high count drifted",
    )
    require(
        int(provenance["material_coverage_max_gap_minutes"].ge(30.0).sum())
        == int(seed["expected_provenance_counts"]["material_gap_ge_30_minutes"]),
        "material-gap count drifted",
    )

    joined["incumbent_squared_error"] = (
        joined["served_floor_probability"] - joined["outcome"]
    ) ** 2
    joined["market_squared_error"] = (joined["market_probability"] - joined["outcome"]) ** 2
    snapshot_counts = joined.groupby(SNAPSHOT_KEY, sort=False).size()
    require((snapshot_counts == 11).all(), "band count per snapshot drifted from 11")
    winner_counts = joined.groupby(SNAPSHOT_KEY, sort=False)["outcome"].sum()
    require((winner_counts == 1).all(), "realized band count per snapshot drifted")

    high = joined["bin_value_hi"].fillna(joined["bin_value"]).to_numpy(dtype=float)
    low = joined["bin_value"].to_numpy(dtype=float)
    kind = joined["bin_kind"].astype(str).to_numpy()
    representative = np.where(kind == "eq", (low + high) / 2.0, low)
    outward = representative.copy()
    outward[kind == "lte"] = low[kind == "lte"] - 1.0
    outward[kind == "gte"] = low[kind == "gte"] + 1.0
    joined["incumbent_weighted_centre"] = joined["served_floor_probability"] * representative
    joined["market_weighted_centre"] = joined["market_probability"] * representative
    joined["incumbent_weighted_centre_outward"] = joined["served_floor_probability"] * outward
    joined["market_weighted_centre_outward"] = joined["market_probability"] * outward

    snapshots = (
        joined.groupby(
            SNAPSHOT_KEY
            + [
                "coverage_bucket",
                "settlement_source",
                "settlement_high",
                "material_coverage_max_gap_minutes",
            ],
            sort=True,
            observed=True,
        )
        .agg(
            incumbent_mass=("served_floor_probability", "sum"),
            market_mass=("market_probability", "sum"),
            incumbent_weighted_centre=("incumbent_weighted_centre", "sum"),
            market_weighted_centre=("market_weighted_centre", "sum"),
            incumbent_weighted_centre_outward=("incumbent_weighted_centre_outward", "sum"),
            market_weighted_centre_outward=("market_weighted_centre_outward", "sum"),
        )
        .reset_index()
    )
    require(np.allclose(snapshots["incumbent_mass"], 1.0, atol=1e-12, rtol=0.0), "incumbent mass drifted")
    require((snapshots["market_mass"] > 0.0).all(), "market mass is non-positive")
    factor = snapshots["market_id"].map(seed["unit_factor_to_c"]).to_numpy(dtype=float)
    settlement = snapshots["settlement_high"].to_numpy(dtype=float)
    snapshots["incumbent_centre_error_c_eq"] = (
        snapshots["incumbent_weighted_centre"] / snapshots["incumbent_mass"] - settlement
    ) * factor
    snapshots["market_centre_error_c_eq"] = (
        snapshots["market_weighted_centre"] / snapshots["market_mass"] - settlement
    ) * factor
    snapshots["incumbent_centre_error_outward_c_eq"] = (
        snapshots["incumbent_weighted_centre_outward"] / snapshots["incumbent_mass"] - settlement
    ) * factor
    snapshots["market_centre_error_outward_c_eq"] = (
        snapshots["market_weighted_centre_outward"] / snapshots["market_mass"] - settlement
    ) * factor

    band_cells = (
        joined.groupby(CELL_GROUPS, sort=True, observed=True)
        .agg(
            band_rows=("outcome", "size"),
            snapshot_rows=("snapshot_id", "nunique"),
            incumbent_sse=("incumbent_squared_error", "sum"),
            market_sse=("market_squared_error", "sum"),
        )
        .reset_index()
    )
    centre_cells = (
        snapshots.groupby(CELL_GROUPS, sort=True, observed=True)
        .agg(
            centre_snapshot_rows=("snapshot_id", "size"),
            incumbent_centre_error_sum=("incumbent_centre_error_c_eq", "sum"),
            market_centre_error_sum=("market_centre_error_c_eq", "sum"),
            incumbent_centre_error_outward_sum=("incumbent_centre_error_outward_c_eq", "sum"),
            market_centre_error_outward_sum=("market_centre_error_outward_c_eq", "sum"),
        )
        .reset_index()
    )
    cells = band_cells.merge(centre_cells, on=CELL_GROUPS, how="inner", validate="one_to_one")
    require((cells["snapshot_rows"] == cells["centre_snapshot_rows"]).all(), "snapshot denominator drifted")

    support: dict[str, Any] = {}
    tolerance = float(seed["comparison_tolerance"])
    for stratum in ("B", "C"):
        scoped = joined[joined["stratum"].eq(stratum)]
        days = provenance[provenance["stratum"].eq(stratum)]
        snapshots_scoped = snapshots[snapshots["stratum"].eq(stratum)]
        expected = seed["expected_support"][stratum]
        actual = {
            "date_clusters": int(days["target_date"].nunique()),
            "market_clusters": int(days["market_id"].nunique()),
            "market_days": int(len(days)),
            "snapshot_rows": int(len(snapshots_scoped)),
            "band_rows": int(len(scoped)),
        }
        for name, value in actual.items():
            require(value == int(expected[name]), f"{stratum} {name} drifted: {value}")
        bucket_counts = days["coverage_bucket"].value_counts().to_dict()
        source_counts = days["settlement_source"].value_counts().to_dict()
        for bucket, value in expected["coverage_bucket_market_days"].items():
            require(int(bucket_counts.get(bucket, 0)) == int(value), f"{stratum} bucket {bucket} drifted")
        for source, value in expected["settlement_source_market_days"].items():
            require(int(source_counts.get(source, 0)) == int(value), f"{stratum} source {source} drifted")
        incumbent = float(scoped["incumbent_squared_error"].mean())
        market = float(scoped["market_squared_error"].mean())
        reference = seed["overall_references"][stratum]
        require(abs(incumbent - float(reference["incumbent_brier"])) <= tolerance, f"{stratum} incumbent reference drifted")
        require(abs(market - float(reference["market_brier"])) <= tolerance, f"{stratum} market reference drifted")
        require(abs((incumbent - market) - float(reference["gap"])) <= tolerance, f"{stratum} gap reference drifted")
        support[stratum] = actual
    return joined, snapshots, cells, support


def group_definitions(seed: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("overall", "all"),
        *(("coverage_bucket", value) for value in seed["coverage_buckets"]),
        *(("settlement_source", value) for value in seed["settlement_sources"]),
    ]


def group_mask(frame: pd.DataFrame, dimension: str, group: str) -> np.ndarray:
    if dimension == "overall":
        return np.ones(len(frame), dtype=bool)
    return frame[dimension].eq(group).to_numpy()


def point_metrics(scoped: pd.DataFrame, mask: np.ndarray) -> dict[str, Any] | None:
    selected = scoped.loc[mask]
    if selected.empty:
        return None
    band_rows = float(selected["band_rows"].sum())
    snapshot_rows = float(selected["snapshot_rows"].sum())
    incumbent_brier = float(selected["incumbent_sse"].sum() / band_rows)
    market_brier = float(selected["market_sse"].sum() / band_rows)
    return {
        "support": {
            "date_clusters": int(selected["target_date"].nunique()),
            "market_clusters": int(selected["market_id"].nunique()),
            "market_days": int(len(selected)),
            "snapshot_rows": int(snapshot_rows),
            "band_rows": int(band_rows),
        },
        "incumbent_brier": incumbent_brier,
        "market_brier": market_brier,
        "gap": incumbent_brier - market_brier,
        "incumbent_centre_error_c_eq": float(selected["incumbent_centre_error_sum"].sum() / snapshot_rows),
        "market_centre_error_c_eq": float(selected["market_centre_error_sum"].sum() / snapshot_rows),
        "incumbent_centre_error_outward_c_eq": float(selected["incumbent_centre_error_outward_sum"].sum() / snapshot_rows),
        "market_centre_error_outward_c_eq": float(selected["market_centre_error_outward_sum"].sum() / snapshot_rows),
    }


def count_matrix(rng: np.random.Generator, replicates: int, cluster_count: int) -> np.ndarray:
    draws = rng.integers(0, cluster_count, size=(replicates, cluster_count))
    return np.eye(cluster_count, dtype=np.int16)[draws].sum(axis=1)


def divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    result = np.full(len(denominator), np.nan, dtype=float)
    np.divide(numerator, denominator, out=result, where=denominator > 0.0)
    return result


def bootstrap_levels(
    cells: pd.DataFrame,
    seed: dict[str, Any],
) -> dict[tuple[str, str, str], dict[str, np.ndarray]]:
    replicates = int(seed["bootstrap"]["replicates"])
    rng = np.random.default_rng(int(seed["bootstrap"]["seed"]))
    markets = sorted(cells["market_id"].unique())
    market_map = {value: index for index, value in enumerate(markets)}
    market_counts = count_matrix(rng, replicates, len(markets))
    output: dict[tuple[str, str, str], dict[str, np.ndarray]] = {}
    for stratum in ("B", "C"):
        scoped = cells[cells["stratum"].eq(stratum)].reset_index(drop=True)
        dates = sorted(scoped["target_date"].unique())
        date_map = {value: index for index, value in enumerate(dates)}
        date_counts = count_matrix(rng, replicates, len(dates))
        date_index = np.asarray([date_map[value] for value in scoped["target_date"]], dtype=int)
        market_index = np.asarray([market_map[value] for value in scoped["market_id"]], dtype=int)
        weights = date_counts[:, date_index] * market_counts[:, market_index]
        for dimension, group in group_definitions(seed):
            mask = group_mask(scoped, dimension, group)
            if not mask.any():
                continue
            weighted = weights[:, mask]
            band_rows = scoped.loc[mask, "band_rows"].to_numpy(dtype=float)
            snapshot_rows = scoped.loc[mask, "snapshot_rows"].to_numpy(dtype=float)
            band_denominator = weighted @ band_rows
            snapshot_denominator = weighted @ snapshot_rows
            incumbent_brier = divide(
                weighted @ scoped.loc[mask, "incumbent_sse"].to_numpy(dtype=float),
                band_denominator,
            )
            market_brier = divide(
                weighted @ scoped.loc[mask, "market_sse"].to_numpy(dtype=float),
                band_denominator,
            )
            output[(stratum, dimension, group)] = {
                "band_denominator": band_denominator,
                "snapshot_denominator": snapshot_denominator,
                "incumbent_brier": incumbent_brier,
                "market_brier": market_brier,
                "gap": incumbent_brier - market_brier,
                "incumbent_centre_error_c_eq": divide(
                    weighted @ scoped.loc[mask, "incumbent_centre_error_sum"].to_numpy(dtype=float),
                    snapshot_denominator,
                ),
                "market_centre_error_c_eq": divide(
                    weighted @ scoped.loc[mask, "market_centre_error_sum"].to_numpy(dtype=float),
                    snapshot_denominator,
                ),
                "incumbent_centre_error_outward_c_eq": divide(
                    weighted @ scoped.loc[mask, "incumbent_centre_error_outward_sum"].to_numpy(dtype=float),
                    snapshot_denominator,
                ),
                "market_centre_error_outward_c_eq": divide(
                    weighted @ scoped.loc[mask, "market_centre_error_outward_sum"].to_numpy(dtype=float),
                    snapshot_denominator,
                ),
            }
    return output


def interval(point: float, draws: np.ndarray, seed: dict[str, Any]) -> dict[str, Any]:
    finite = draws[np.isfinite(draws)]
    require(len(finite) > 0, "bootstrap metric has no finite draws")
    lower_q, upper_q = seed["bootstrap"]["interval_quantiles"]
    return {
        "point": float(point),
        "crossed_95_interval": [float(np.quantile(finite, lower_q)), float(np.quantile(finite, upper_q))],
        "crossed_standard_error": float(finite.std(ddof=1)),
        "bootstrap_replicates": int(len(draws)),
        "finite_draws": int(len(finite)),
        "zero_support_or_nonfinite_draws": int(len(draws) - len(finite)),
        "bootstrap_seed": int(seed["bootstrap"]["seed"]),
    }


def build_results(
    cells: pd.DataFrame,
    draws: dict[tuple[str, str, str], dict[str, np.ndarray]],
    seed: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    stratified: dict[str, Any] = {"B": {}, "C": {}}
    metric_rows: list[dict[str, Any]] = []
    points: dict[tuple[str, str, str], dict[str, Any] | None] = {}
    for stratum in ("B", "C"):
        scoped = cells[cells["stratum"].eq(stratum)].reset_index(drop=True)
        for dimension, group in group_definitions(seed):
            mask = group_mask(scoped, dimension, group)
            point = point_metrics(scoped, mask)
            points[(stratum, dimension, group)] = point
            stratified[stratum].setdefault(dimension, {})
            if point is None:
                stratified[stratum][dimension][group] = {
                    "status": "NOT_ESTIMABLE_NO_ROWS",
                    "support": {"market_days": 0},
                }
                continue
            draw = draws[(stratum, dimension, group)]
            result = {"status": "PASS", "support": point["support"], "metrics": {}}
            for metric in METRICS:
                measured = interval(float(point[metric]), draw[metric], seed)
                result["metrics"][metric] = measured
                metric_rows.append(
                    {
                        "stratum": stratum,
                        "dimension": dimension,
                        "group": group,
                        "metric": metric,
                        "point": measured["point"],
                        "crossed_95_lower": measured["crossed_95_interval"][0],
                        "crossed_95_upper": measured["crossed_95_interval"][1],
                        **point["support"],
                        "finite_draws": measured["finite_draws"],
                        "zero_support_or_nonfinite_draws": measured["zero_support_or_nonfinite_draws"],
                    }
                )
            stratified[stratum][dimension][group] = result

    contrast_specs = [
        ("coverage_bucket", "(0,30)", "0", "minor_minus_clean"),
        ("coverage_bucket", "[30,inf)", "0", "material_minus_clean"),
        ("settlement_source", "snapshot_high", "daily_summary", "snapshot_high_minus_daily_summary"),
    ]
    contrasts: dict[str, Any] = {"B": {}, "C": {}}
    contrast_rows: list[dict[str, Any]] = []
    for stratum in ("B", "C"):
        for dimension, left, right, name in contrast_specs:
            left_point = points.get((stratum, dimension, left))
            right_point = points.get((stratum, dimension, right))
            if left_point is None or right_point is None:
                contrasts[stratum][name] = {"status": "NOT_ESTIMABLE_NO_ROWS"}
                continue
            left_draw = draws[(stratum, dimension, left)]
            right_draw = draws[(stratum, dimension, right)]
            result = {
                "status": "PASS",
                "dimension": dimension,
                "left": left,
                "right": right,
                "metrics": {},
            }
            for metric in METRICS:
                point = float(left_point[metric]) - float(right_point[metric])
                measured = interval(point, left_draw[metric] - right_draw[metric], seed)
                result["metrics"][metric] = measured
                contrast_rows.append(
                    {
                        "stratum": stratum,
                        "contrast": name,
                        "metric": metric,
                        "point": measured["point"],
                        "crossed_95_lower": measured["crossed_95_interval"][0],
                        "crossed_95_upper": measured["crossed_95_interval"][1],
                        "finite_draws": measured["finite_draws"],
                        "zero_support_or_nonfinite_draws": measured["zero_support_or_nonfinite_draws"],
                    }
                )
            contrasts[stratum][name] = result

    c_overall_point = points[("C", "overall", "all")]
    c_clean_point = points[("C", "coverage_bucket", seed["attribution_diagnostic"]["clean_bucket"])]
    c_gapped_point = points[("C", "coverage_bucket", seed["attribution_diagnostic"]["gapped_bucket"])]
    require(c_overall_point is not None and c_clean_point is not None and c_gapped_point is not None, "C diagnostic support missing")
    c_overall_draw = draws[("C", "overall", "all")]
    c_clean_draw = draws[("C", "coverage_bucket", seed["attribution_diagnostic"]["clean_bucket"])]
    c_gapped_draw = draws[("C", "coverage_bucket", seed["attribution_diagnostic"]["gapped_bucket"])]
    c_cells = cells[cells["stratum"].eq("C")]
    point_weight = float(
        c_cells.loc[c_cells["coverage_bucket"].eq(seed["attribution_diagnostic"]["gapped_bucket"]), "band_rows"].sum()
        / c_cells["band_rows"].sum()
    )
    draw_weight = divide(c_gapped_draw["band_denominator"], c_overall_draw["band_denominator"])
    observed_gap = float(c_overall_point["gap"])
    counterfactual_gap = observed_gap - point_weight * (float(c_gapped_point["gap"]) - float(c_clean_point["gap"]))
    attributable_gap = observed_gap - counterfactual_gap
    attributable_share = attributable_gap / observed_gap
    counterfactual_draw = c_overall_draw["gap"] - draw_weight * (c_gapped_draw["gap"] - c_clean_draw["gap"])
    attributable_draw = c_overall_draw["gap"] - counterfactual_draw
    share_draw = attributable_draw / c_overall_draw["gap"]
    diagnostic = {
        "label": seed["attribution_diagnostic"]["label"],
        "formula": seed["attribution_diagnostic"]["formula"],
        "clean_bucket": seed["attribution_diagnostic"]["clean_bucket"],
        "gapped_bucket": seed["attribution_diagnostic"]["gapped_bucket"],
        "gapped_band_row_share": interval(point_weight, draw_weight, seed),
        "observed_C_gap": interval(observed_gap, c_overall_draw["gap"], seed),
        "counterfactual_C_gap": interval(counterfactual_gap, counterfactual_draw, seed),
        "gap_attributable_to_material_bucket": interval(attributable_gap, attributable_draw, seed),
        "share_of_C_gap_attributable": interval(attributable_share, share_draw, seed),
    }
    return {"stratified": stratified, "contrasts": contrasts, "C_attribution_diagnostic": diagnostic}, metric_rows, contrast_rows


def market_day_rows(cells: pd.DataFrame) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in cells.sort_values(DAY_KEY).to_dict(orient="records"):
        band_rows = float(row["band_rows"])
        snapshot_rows = float(row["snapshot_rows"])
        incumbent = float(row["incumbent_sse"] / band_rows)
        market = float(row["market_sse"] / band_rows)
        result.append(
            {
                "stratum": row["stratum"],
                "market_id": row["market_id"],
                "target_date": row["target_date"],
                "coverage_bucket": row["coverage_bucket"],
                "settlement_source": row["settlement_source"],
                "snapshot_rows": int(snapshot_rows),
                "band_rows": int(band_rows),
                "incumbent_brier": incumbent,
                "market_brier": market,
                "gap": incumbent - market,
                "incumbent_centre_error_c_eq": float(row["incumbent_centre_error_sum"] / snapshot_rows),
                "market_centre_error_c_eq": float(row["market_centre_error_sum"] / snapshot_rows),
                "incumbent_centre_error_outward_c_eq": float(row["incumbent_centre_error_outward_sum"] / snapshot_rows),
                "market_centre_error_outward_c_eq": float(row["market_centre_error_outward_sum"] / snapshot_rows),
            }
        )
    return result


def write_json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(rows, f"refusing to write empty CSV: {path}")
    pd.DataFrame(rows).to_csv(path, index=False, lineterminator="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed_path = args.seed.resolve()
    output_dir = args.output_dir.resolve()
    require(seed_path.is_file(), f"missing seed: {seed_path}")
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    require(seed.get("schema_version") == "outcome_label_audit_seed_v1", "seed schema drifted")
    require(not output_dir.exists(), f"refusing to overwrite evidence directory: {output_dir}")
    output_dir.mkdir(parents=True)

    receipts = verify_inputs(seed)
    _, _, cells, support = load_panel(seed)
    draws = bootstrap_levels(cells, seed)
    results, metric_rows, contrast_rows = build_results(cells, draws, seed)
    day_rows = market_day_rows(cells)
    day_path = output_dir / "market-day-metrics.csv"
    metric_path = output_dir / "stratified-metrics.csv"
    contrast_path = output_dir / "contrasts.csv"
    write_csv(day_path, day_rows)
    write_csv(metric_path, metric_rows)
    write_csv(contrast_path, contrast_rows)
    payload = {
        "schema_version": "outcome_label_audit_result_v1",
        "status": "PASS",
        "mission": seed["mission"],
        "interpretation": {
            "kind": "descriptive_label_provenance_stratification",
            "C_access": seed["campaign"]["C_access"],
            "candidate": False,
            "fitted_parameter": False,
            "accept_rule": False,
            "alpha_allocated_or_spent": False,
            "correction_or_exclusion_rule": False,
            "pooled_across_2026_07_31": False,
            "serving_floor_changed": False,
        },
        "campaign": seed["campaign"],
        "support": support,
        "bootstrap": seed["bootstrap"],
        **results,
        "provenance": {
            "seed_path": str(seed_path),
            "seed_sha256": sha256(seed_path),
            "inputs": receipts,
        },
        "outputs": {
            "market_day_metrics": {"filename": day_path.name, "sha256": sha256(day_path), "rows": len(day_rows)},
            "stratified_metrics": {"filename": metric_path.name, "sha256": sha256(metric_path), "rows": len(metric_rows)},
            "contrasts": {"filename": contrast_path.name, "sha256": sha256(contrast_path), "rows": len(contrast_rows)},
        },
        "explicitly_not_done": [
            "no label correction, relabelling, exclusion, or re-score of a spent decision",
            "no candidate, fit, parameter selection, accept rule, alpha allocation, or promotion",
            "no settlement, daily-max window, collection schedule, serving floor, model, or production code change",
            "no production write, registration, restart, merge, provider call, exchange action, or live trade",
        ],
    }
    summary_path = output_dir / "summary.json"
    write_json(summary_path, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "summary": str(summary_path),
                "summary_sha256": sha256(summary_path),
                "C_attribution_diagnostic": payload["C_attribution_diagnostic"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IntegrityFailure as exc:
        print(json.dumps({"status": "INTEGRITY_FAILURE", "error": str(exc)}, indent=2))
        raise SystemExit(3) from exc
