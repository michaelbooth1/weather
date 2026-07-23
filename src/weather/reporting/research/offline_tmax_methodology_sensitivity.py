"""No-refit sensitivity checks for sealed offline Tmax holdout predictions.

The primary evaluator resamples fleet dates but computes market-date-weighted
MAE and RMSE inside each replicate.  That is the preserved primary estimand.
This module adds two post-hoc diagnostics from the already sealed per-date
errors: equal weight per fleet date, and the original metric restricted to
dates with all requested markets.  It never refits a model or reads raw
outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.io import write_json_atomic
from weather.reporting.research.cfsv2_pressure_research import utc_iso
from weather.reporting.research.offline_tmax_predictor_evaluation import (
    resolve_paths_outside_read_only_root,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("offline_tmax_methodology_sensitivity")
DEFAULT_REPLICATES = 20_000


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * float(quantile)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _weighted_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | int]:
    market_dates = sum(int(row["market_dates"]) for row in rows)
    if market_dates <= 0:
        raise ValueError("sensitivity cohort has no market-dates")
    baseline_mae = sum(
        float(row["baseline_mae_c"]) * int(row["market_dates"]) for row in rows
    ) / market_dates
    variant_mae = sum(
        float(row["variant_mae_c"]) * int(row["market_dates"]) for row in rows
    ) / market_dates
    baseline_rmse = math.sqrt(
        sum(
            float(row["baseline_rmse_c"]) ** 2 * int(row["market_dates"])
            for row in rows
        )
        / market_dates
    )
    variant_rmse = math.sqrt(
        sum(
            float(row["variant_rmse_c"]) ** 2 * int(row["market_dates"])
            for row in rows
        )
        / market_dates
    )
    return {
        "fleet_dates": len(rows),
        "market_dates": market_dates,
        "baseline_mae_c": baseline_mae,
        "variant_mae_c": variant_mae,
        "mae_delta_c": variant_mae - baseline_mae,
        "baseline_rmse_c": baseline_rmse,
        "variant_rmse_c": variant_rmse,
        "rmse_delta_c": variant_rmse - baseline_rmse,
    }


def _equal_date_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | int]:
    if not rows:
        raise ValueError("equal-date sensitivity cohort is empty")
    return {
        "fleet_dates": len(rows),
        "market_dates": sum(int(row["market_dates"]) for row in rows),
        "mae_delta_c": sum(float(row["mae_delta_c"]) for row in rows) / len(rows),
        "rmse_delta_c": sum(float(row["rmse_delta_c"]) for row in rows) / len(rows),
    }


def _bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    replicates: int,
    metric_fn,
) -> dict[str, Any]:
    if not rows or int(replicates) <= 0:
        raise ValueError("bootstrap requires rows and positive replicates")
    rng = random.Random(int(seed))
    mae = []
    rmse = []
    for _ in range(int(replicates)):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        metrics = metric_fn(sample)
        mae.append(float(metrics["mae_delta_c"]))
        rmse.append(float(metrics["rmse_delta_c"]))
    return {
        "cluster_unit": "fleet_target_date",
        "clusters": len(rows),
        "replicates": int(replicates),
        "seed": int(seed),
        "mae_delta_c_95ci": {
            "low": _percentile(mae, 0.025),
            "high": _percentile(mae, 0.975),
        },
        "rmse_delta_c_95ci": {
            "low": _percentile(rmse, 0.025),
            "high": _percentile(rmse, 0.975),
        },
    }


def _assessment(point: float, interval: Mapping[str, float]) -> str:
    if point < 0.0 and float(interval["high"]) < 0.0:
        return "entire_interval_improvement"
    if point > 0.0 and float(interval["low"]) > 0.0:
        return "entire_interval_regression"
    return "inconclusive_interval_crosses_zero"


def analyze(
    payload: Mapping[str, Any],
    *,
    sensitivity_replicates: int = DEFAULT_REPLICATES,
    sensitivity_seed: int | None = None,
) -> dict[str, Any]:
    evaluation = payload.get("evaluation") or {}
    holdout = (evaluation.get("holdout") or {}).get("metrics") or {}
    rows = list(holdout.get("paired_fleet_date_errors") or [])
    if not rows:
        raise ValueError("evaluation has no sealed holdout fleet-date summaries")
    experiment = payload.get("experiment") or {}
    primary_bootstrap = holdout.get("fleet_date_cluster_bootstrap") or {}
    primary_seed = int(primary_bootstrap.get("seed", experiment.get("bootstrap_seed", 0)))
    primary_replicates = int(primary_bootstrap.get("replicates", 0))
    sensitivity_seed = primary_seed if sensitivity_seed is None else int(sensitivity_seed)
    requested_markets = len(experiment.get("market_ids") or [])
    if requested_markets <= 0:
        requested_markets = max(int(row["market_dates"]) for row in rows)

    primary_point = _weighted_metrics(rows)
    reproduced_primary_bootstrap = _bootstrap(
        rows,
        seed=primary_seed,
        replicates=primary_replicates,
        metric_fn=_weighted_metrics,
    )
    point_differences = {
        key: abs(float(primary_point[key]) - float(holdout[key]))
        for key in (
            "baseline_mae_c",
            "variant_mae_c",
            "mae_delta_c",
            "baseline_rmse_c",
            "variant_rmse_c",
            "rmse_delta_c",
        )
    }
    ci_differences = {
        f"{metric}_{bound}": abs(
            float(reproduced_primary_bootstrap[f"{metric}_delta_c_95ci"][bound])
            - float(primary_bootstrap[f"{metric}_delta_c_95ci"][bound])
        )
        for metric in ("mae", "rmse")
        for bound in ("low", "high")
    }
    max_reproduction_difference = max([*point_differences.values(), *ci_differences.values()])
    if max_reproduction_difference > 1e-12:
        raise ValueError(
            "sealed holdout summaries do not reproduce the primary result: "
            f"max_difference={max_reproduction_difference}"
        )

    primary_20k = _bootstrap(
        rows,
        seed=sensitivity_seed,
        replicates=sensitivity_replicates,
        metric_fn=_weighted_metrics,
    )
    equal_point = _equal_date_metrics(rows)
    equal_bootstrap = _bootstrap(
        rows,
        seed=sensitivity_seed,
        replicates=sensitivity_replicates,
        metric_fn=_equal_date_metrics,
    )
    complete_rows = [
        row for row in rows if int(row["market_dates"]) == requested_markets
    ]
    if not complete_rows:
        raise ValueError("holdout has no exact complete-fleet dates")
    complete_point = _weighted_metrics(complete_rows)
    complete_bootstrap = _bootstrap(
        complete_rows,
        seed=sensitivity_seed,
        replicates=sensitivity_replicates,
        metric_fn=_weighted_metrics,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "sealed_holdout_methodology_sensitivity",
        "generated_at_utc": utc_iso(),
        "research_only": True,
        "post_hoc": True,
        "no_refit": True,
        "raw_outcomes_read": False,
        "original_primary_preserved": True,
        "family": experiment.get("family"),
        "primary_estimand": (
            "market-date-weighted MAE/RMSE with fleet-date cluster bootstrap"
        ),
        "primary_verbatim": {
            "point": {
                key: holdout[key]
                for key in (
                    "fleet_dates",
                    "market_dates",
                    "baseline_mae_c",
                    "variant_mae_c",
                    "mae_delta_c",
                    "baseline_rmse_c",
                    "variant_rmse_c",
                    "rmse_delta_c",
                )
            },
            "bootstrap": primary_bootstrap,
        },
        "primary_reproduction": {
            "point": primary_point,
            "bootstrap": reproduced_primary_bootstrap,
            "point_absolute_differences": point_differences,
            "bootstrap_absolute_differences": ci_differences,
            "max_absolute_difference": max_reproduction_difference,
            "status": "PASS",
        },
        "higher_replicate_primary_sensitivity": {
            "point": primary_point,
            "bootstrap": primary_20k,
            "mae_assessment": _assessment(
                float(primary_point["mae_delta_c"]), primary_20k["mae_delta_c_95ci"]
            ),
            "rmse_assessment": _assessment(
                float(primary_point["rmse_delta_c"]), primary_20k["rmse_delta_c_95ci"]
            ),
        },
        "equal_fleet_date_sensitivity": {
            "estimand": "unweighted mean of per-date MAE and per-date RMSE deltas",
            "point": equal_point,
            "bootstrap": equal_bootstrap,
            "mae_assessment": _assessment(
                float(equal_point["mae_delta_c"]), equal_bootstrap["mae_delta_c_95ci"]
            ),
            "rmse_assessment": _assessment(
                float(equal_point["rmse_delta_c"]), equal_bootstrap["rmse_delta_c_95ci"]
            ),
        },
        "exact_complete_fleet_date_sensitivity": {
            "estimand": "primary metric on dates with exactly every requested market",
            "requested_market_count": requested_markets,
            "included_fleet_dates": len(complete_rows),
            "excluded_incomplete_fleet_dates": len(rows) - len(complete_rows),
            "point": complete_point,
            "bootstrap": complete_bootstrap,
            "mae_assessment": _assessment(
                float(complete_point["mae_delta_c"]), complete_bootstrap["mae_delta_c_95ci"]
            ),
            "rmse_assessment": _assessment(
                float(complete_point["rmse_delta_c"]), complete_bootstrap["rmse_delta_c_95ci"]
            ),
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    read_only_root, guarded_paths = resolve_paths_outside_read_only_root(
        read_only_root=args.read_only_data_root,
        paths={"out": args.out},
    )
    evaluation_path = Path(args.evaluation).resolve(strict=True)
    output_path = guarded_paths["out"]
    aliases_evaluation = output_path == evaluation_path
    if not aliases_evaluation and output_path.exists():
        try:
            aliases_evaluation = output_path.samefile(evaluation_path)
        except OSError:
            aliases_evaluation = False
    if aliases_evaluation:
        raise ValueError("sensitivity output must not overwrite the evaluation artifact")
    payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
    result = analyze(
        payload,
        sensitivity_replicates=args.replicates,
        sensitivity_seed=args.seed,
    )
    result["read_only_data_root"] = str(read_only_root)
    result["evaluation_path"] = str(evaluation_path)
    result["evaluation_sha256"] = sha256_file(evaluation_path)
    write_json_atomic(output_path, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute no-refit weighting/completeness sensitivities from a sealed Tmax evaluation."
    )
    parser.add_argument(
        "--read-only-data-root",
        required=True,
        help="Explicit mirrored data root that this command must never write below.",
    )
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--seed", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run(args)
    print(
        f"Offline Tmax methodology sensitivity: {result['family']} "
        f"({result['exact_complete_fleet_date_sensitivity']['included_fleet_dates']} complete dates)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
