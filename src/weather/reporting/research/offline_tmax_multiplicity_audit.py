"""Program-level multiplicity audit for sealed offline Tmax MAE families."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from weather.io import write_json_atomic
from weather.reporting.research.cfsv2_pressure_research import sha256_file, utc_iso
from weather.reporting.research.offline_tmax_predictor_evaluation import (
    resolve_paths_outside_read_only_root,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("offline_tmax_multiplicity_audit")
DEFAULT_REPLICATES = 200_000
DEFAULT_SEED = 20_260_722


def stable_family_seed(base_seed: int, label: str) -> int:
    """Derive a deterministic family seed independent of CLI argument order."""

    label_digest = hashlib.sha256(label.encode("utf-8")).digest()
    label_offset = int.from_bytes(label_digest[:8], byteorder="big", signed=False)
    return (int(base_seed) + label_offset) % (2**63 - 1)


def clustered_sign_flip_pvalue(
    date_rows: Sequence[Mapping[str, Any]],
    *,
    replicates: int = DEFAULT_REPLICATES,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Two-sided wild-cluster randomization evidence for weighted MAE delta.

    Each fleet date contributes its total paired absolute-error difference,
    ``market_dates * mae_delta``.  Randomly flipping whole date contributions
    keeps all within-date city dependence intact and targets the same
    market-date-weighted primary point estimate.
    """

    contributions = np.asarray(
        [
            float(row["mae_delta_c"]) * int(row["market_dates"])
            for row in date_rows
        ],
        dtype=float,
    )
    if not len(contributions) or int(replicates) <= 0:
        raise ValueError("clustered sign-flip audit requires dates and replicates")
    if not np.isfinite(contributions).all():
        raise ValueError("clustered sign-flip contributions are not finite")
    observed_sum = float(contributions.sum())
    observed_delta = observed_sum / sum(int(row["market_dates"]) for row in date_rows)
    threshold = abs(observed_sum) - 1e-15
    rng = np.random.default_rng(int(seed))
    extreme = 0
    remaining = int(replicates)
    chunk_size = 10_000
    while remaining:
        size = min(chunk_size, remaining)
        signs = rng.integers(0, 2, size=(size, len(contributions)), dtype=np.int8)
        signed_sums = (signs * 2 - 1).astype(float) @ contributions
        extreme += int(np.count_nonzero(np.abs(signed_sums) >= threshold))
        remaining -= size
    pvalue = (extreme + 1.0) / (int(replicates) + 1.0)
    return {
        "method": "two-sided fleet-date wild-cluster sign-flip randomization",
        "cluster_unit": "fleet_target_date",
        "estimand": "market-date-weighted MAE delta C",
        "clusters": len(contributions),
        "replicates": int(replicates),
        "seed": int(seed),
        "observed_mae_delta_c": observed_delta,
        "extreme_replicates": extreme,
        "p_two_sided": pvalue,
    }


def holm_adjust(pvalues: Mapping[str, float]) -> dict[str, dict[str, Any]]:
    ordered = sorted(pvalues, key=lambda key: (float(pvalues[key]), key))
    count = len(ordered)
    prior = 0.0
    output = {}
    for rank, key in enumerate(ordered, start=1):
        adjusted = min(1.0, (count - rank + 1) * float(pvalues[key]))
        adjusted = max(prior, adjusted)
        prior = adjusted
        output[key] = {
            "holm_rank": rank,
            "raw_p_two_sided": float(pvalues[key]),
            "holm_adjusted_p": adjusted,
            "reject_fwer_0_05": adjusted <= 0.05,
        }
    return output


def analyze(
    evaluations: Mapping[str, tuple[str | Path, Mapping[str, Any]]],
    *,
    replicates: int = DEFAULT_REPLICATES,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    families = []
    pvalues = {}
    for label in sorted(evaluations):
        path, payload = evaluations[label]
        experiment = payload.get("experiment") or {}
        metrics = ((payload.get("evaluation") or {}).get("holdout") or {}).get("metrics") or {}
        date_rows = list(metrics.get("paired_fleet_date_errors") or [])
        if not date_rows:
            raise ValueError(f"{label} has no sealed holdout date summaries")
        evidence = clustered_sign_flip_pvalue(
            date_rows,
            replicates=replicates,
            seed=stable_family_seed(seed, label),
        )
        difference = abs(float(evidence["observed_mae_delta_c"]) - float(metrics["mae_delta_c"]))
        if difference > 1e-12:
            raise ValueError(f"{label} date summaries do not reproduce primary MAE")
        primary_bootstrap = metrics["fleet_date_cluster_bootstrap"]
        pvalues[label] = float(evidence["p_two_sided"])
        families.append(
            {
                "label": label,
                "family": experiment.get("family"),
                "evaluation_path": str(Path(path).resolve(strict=True)),
                "evaluation_sha256": sha256_file(path),
                "holdout_fleet_dates": metrics["fleet_dates"],
                "holdout_market_dates": metrics["market_dates"],
                "primary_mae_delta_c": metrics["mae_delta_c"],
                "primary_mae_delta_c_95ci": primary_bootstrap["mae_delta_c_95ci"],
                "primary_bootstrap_replicates": primary_bootstrap["replicates"],
                "primary_bootstrap_seed": primary_bootstrap["seed"],
                "clustered_two_sided_evidence": evidence,
                "secondary_only": {
                    "rmse_delta_c": metrics["rmse_delta_c"],
                    "rmse_delta_c_95ci": primary_bootstrap["rmse_delta_c_95ci"],
                    "fleet_date_sign_test": metrics.get("fleet_date_sign_counts"),
                    "market_date_sign_test": metrics.get("market_date_sign_counts"),
                },
            }
        )
    adjusted = holm_adjust(pvalues)
    for item in families:
        item["multiplicity"] = adjusted[item["label"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "program_level_primary_mae_multiplicity_audit",
        "generated_at_utc": utc_iso(),
        "research_only": True,
        "post_hoc_program_audit": True,
        "base_seed": int(seed),
        "family_seed_derivation": (
            "(base_seed + uint64_be(sha256(UTF-8 label)[:8])) mod (2^63 - 1); "
            "families sorted by label"
        ),
        "family_count": len(families),
        "primary_metric_only": "holdout market-date-weighted MAE delta C",
        "raw_evidence": (
            "uniform two-sided fleet-date wild-cluster sign-flip randomization; "
            "whole-date contributions preserve within-date city dependence"
        ),
        "adjustment": "Holm step-down family-wise error control at alpha=0.05",
        "dependence_note": (
            "families share settlements and overlapping dates; Holm controls FWER "
            "without requiring independent tests"
        ),
        "source_contract_note": (
            "different provider/issue-time contracts are sensitivity evidence, not "
            "independent outcome confirmation"
        ),
        "rmse_and_sign_tests_secondary_only": True,
        "families": families,
        "holm_rejection_count": sum(item["multiplicity"]["reject_fwer_0_05"] for item in families),
    }


def _parse_evaluation(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if not separator or not label.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("expected LABEL=PATH")
    return label.strip(), Path(raw_path.strip())


def run(args: argparse.Namespace) -> dict[str, Any]:
    read_only_root, guarded_paths = resolve_paths_outside_read_only_root(
        read_only_root=args.read_only_data_root,
        paths={"out": args.out},
    )
    output = guarded_paths["out"]
    evaluations = {}
    for label, path in args.evaluation:
        resolved = path.resolve(strict=True)
        aliases_evaluation = output == resolved
        if not aliases_evaluation and output.exists():
            try:
                aliases_evaluation = output.samefile(resolved)
            except OSError:
                aliases_evaluation = False
        if aliases_evaluation:
            raise ValueError(
                "multiplicity output must not overwrite an evaluation artifact"
            )
        if label in evaluations:
            raise ValueError(f"duplicate multiplicity label: {label}")
        evaluations[label] = (
            resolved,
            json.loads(resolved.read_text(encoding="utf-8")),
        )
    result = analyze(evaluations, replicates=args.replicates, seed=args.seed)
    result["read_only_data_root"] = str(read_only_root)
    write_json_atomic(output, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Holm-adjust primary MAE evidence across sealed Tmax families."
    )
    parser.add_argument(
        "--read-only-data-root",
        required=True,
        help="Explicit mirrored data root that this command must never write below.",
    )
    parser.add_argument("--evaluation", action="append", type=_parse_evaluation, required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    result = run(build_parser().parse_args(argv))
    print(
        f"Offline Tmax multiplicity audit: {result['family_count']} families, "
        f"{result['holm_rejection_count']} Holm rejections"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
