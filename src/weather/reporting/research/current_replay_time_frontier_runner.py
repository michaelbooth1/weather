"""CLI orchestration and artifact writing for the current-replay frontier."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.io import (
    write_csv_rows_atomic,
    write_json_atomic,
    write_text_atomic,
)
from weather.reporting.research.current_replay_time_frontier import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    H1_SCHEMA_VERSION,
    MAX_AGGREGATE_GROUPS,
    MAX_ALIGNMENT_KEYS,
    METRIC_NAMES,
    MODEL_NAMES,
    SCHEMA_VERSION,
    ExperimentConfigurationError,
    analyze_split_units,
    build_cache_plan,
    build_complete_panel_fleet_date_rows,
    build_fleet_date_rows,
    build_summaries,
    configured_markets_by_unit,
    derive_breakpoints,
    load_h1_selection,
    read_dates,
    sha256_file,
    sha256_stable_file,
    validate_cache_plan,
    validate_path_contract,
    _resolved,
)
from weather.reporting.research.current_replay_time_frontier_history import (
    compare_historical_pattern,
    load_historical_hourly_context,
)
from weather.reporting.research.current_replay_time_frontier_report import (
    render_report,
)
from weather.reporting.research.current_replay_time_frontier_sharpness import (
    analyze_holdout_sharpness,
)


def _atomic_write_text(path: Path, text: str) -> None:
    write_text_atomic(path, text, newline="\n")


def _atomic_write_json(path: Path, payload: Any) -> None:
    write_json_atomic(path, payload, trailing_newline=True)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    write_csv_rows_atomic(path, fieldnames, rows)


def _flat_summary_rows(
    summaries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for row in summaries:
        flat = {
            key: row[key]
            for key in (
                "schema_version",
                "split",
                "evidence_role",
                "unit",
                "market_id",
                "scope",
                "panel_scope",
                "selected_weight",
                "fleet_dates",
                "markets",
                "snapshots",
                "band_rows",
                "selected_effect_disposition",
            )
        }
        for statistic in ("minimum", "mean", "maximum"):
            flat[f"markets_per_fleet_date_{statistic}"] = row[
                "market_coverage_per_fleet_date"
            ][statistic]
            flat[f"snapshots_per_fleet_date_{statistic}"] = row[
                "snapshots_per_fleet_date"
            ][statistic]
        for model in MODEL_NAMES:
            for metric in METRIC_NAMES:
                flat[f"{model}_{metric}"] = row["metrics"][model][metric]
        for metric in METRIC_NAMES:
            delta = row["selected_vs_current"][metric]
            ci = delta["paired_fleet_date_bootstrap_95ci"]
            sign = delta["paired_fleet_date_sign_test"]
            flat[f"selected_current_{metric}_delta"] = delta["mean_delta"]
            flat[f"selected_current_{metric}_ci_low"] = ci["low"]
            flat[f"selected_current_{metric}_ci_high"] = ci["high"]
            flat[f"selected_current_{metric}_favorable_dates"] = sign["favorable"]
            flat[f"selected_current_{metric}_unfavorable_dates"] = sign[
                "unfavorable"
            ]
            flat[f"selected_current_{metric}_ties"] = sign["ties"]
            flat[f"selected_current_{metric}_sign_p"] = sign["two_sided_p"]
        for model in ("current", "selected"):
            for metric in METRIC_NAMES:
                comparison = row[f"{model}_vs_market_inference"][metric]
                ci = comparison["paired_fleet_date_bootstrap_95ci"]
                sign = comparison["paired_fleet_date_sign_test"]
                flat[f"{model}_market_{metric}_delta"] = comparison["mean_delta"]
                flat[f"{model}_market_{metric}_ci_low"] = ci["low"]
                flat[f"{model}_market_{metric}_ci_high"] = ci["high"]
                flat[f"{model}_market_{metric}_favorable_dates"] = sign["favorable"]
                flat[f"{model}_market_{metric}_unfavorable_dates"] = sign[
                    "unfavorable"
                ]
                flat[f"{model}_market_{metric}_ties"] = sign["ties"]
                flat[f"{model}_market_{metric}_sign_p"] = sign["two_sided_p"]
        output.append(flat)
    return output


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    """Run the frozen-arm analysis and write only outside read-only roots."""

    allow_blocked_tune_only = bool(
        getattr(args, "allow_blocked_tune_only", False)
    )
    paths = validate_path_contract(
        h1_result=args.h1_result,
        cache_root=args.cache_root,
        tune_dates_file=args.tune_dates_file,
        holdout_dates_file=args.holdout_dates_file,
        output_root=args.output_root,
        report_out=args.report_out,
        historical_hourly_json=getattr(args, "historical_hourly_json", None),
        read_only_roots=args.read_only_root or (),
    )
    date_manifest_stats = {
        "tune": paths["tune_dates_file"].stat(),
        "holdout": paths["holdout_dates_file"].stat(),
    }
    tune_dates = read_dates(paths["tune_dates_file"])
    holdout_dates = read_dates(paths["holdout_dates_file"])
    date_manifest_hashes = {
        split: {
            "path": str(paths[f"{split}_dates_file"]),
            "size_bytes": date_manifest_stats[split].st_size,
            "sha256": sha256_stable_file(
                paths[f"{split}_dates_file"],
                expected_size_bytes=date_manifest_stats[split].st_size,
                expected_mtime_ns=date_manifest_stats[split].st_mtime_ns,
            ),
        }
        for split in ("tune", "holdout")
    }
    selection = load_h1_selection(
        paths["h1_result"],
        tune_dates=tune_dates,
        holdout_dates=holdout_dates,
        allow_blocked_tune_only=allow_blocked_tune_only,
    )
    historical_context = (
        load_historical_hourly_context(paths["historical_hourly_json"])
        if "historical_hourly_json" in paths
        else None
    )
    selected_weights = selection["selected_weights"]
    analyzed_splits = (
        ("tune",) if allow_blocked_tune_only else ("tune", "holdout")
    )
    h1_cache_root_raw = (selection["payload"].get("outputs") or {}).get(
        "cache_root"
    )
    if not h1_cache_root_raw:
        raise ExperimentConfigurationError("H1 result does not attest its cache root")
    h1_cache_root = _resolved(h1_cache_root_raw)
    if h1_cache_root != paths["cache_root"]:
        raise ExperimentConfigurationError(
            f"H1 result cache root {h1_cache_root} differs from requested "
            f"{paths['cache_root']}"
        )
    plan = build_cache_plan(
        cache_root=paths["cache_root"],
        selected_weights=selected_weights,
        splits=analyzed_splits,
    )
    metadata = validate_cache_plan(plan)

    all_market_date_rows: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}
    analysis_blockers: list[str] = []
    manifests = {"tune": tune_dates, "holdout": holdout_dates}
    for split in analyzed_splits:
        current_cache = plan[split]["0.0"]
        positive_weights = sorted(
            {
                float(weight)
                for weight in selected_weights.values()
                if float(weight) > 0.0
            }
        )
        selected_caches = {
            weight: plan[split][str(weight)] for weight in positive_weights
        }
        print(
            f"time-frontier {split}: current=0.00 "
            f"C={selected_weights['C']:.2f} F={selected_weights['F']:.2f} "
            f"unique_cache_scans={1 + len(selected_caches)}",
            flush=True,
        )
        failure_diagnostics: dict[str, Any] = {}
        try:
            rows, split_diagnostics = analyze_split_units(
                split=split,
                current_cache=current_cache,
                selected_caches_by_weight=selected_caches,
                selected_weights=selected_weights,
                expected_dates=manifests[split],
                failure_diagnostics=failure_diagnostics,
            )
        except ExperimentConfigurationError as exc:
            if not allow_blocked_tune_only:
                raise
            analysis_blockers.append(str(exc))
            diagnostics[split] = {
                **failure_diagnostics,
                "status": "BLOCK",
                "blocker": str(exc),
            }
            break
        all_market_date_rows.extend(rows)
        diagnostics[split] = split_diagnostics

    fleet_date_rows = build_fleet_date_rows(all_market_date_rows)
    summaries = build_summaries(all_market_date_rows, fleet_date_rows)
    configured_panel = configured_markets_by_unit()
    complete_panel_rows, complete_panel_coverage = (
        build_complete_panel_fleet_date_rows(
            all_market_date_rows,
            configured=configured_panel,
            splits=analyzed_splits,
        )
    )
    complete_panel_summaries = build_summaries([], complete_panel_rows)
    complete_panel_breakpoints = derive_breakpoints(complete_panel_summaries)
    breakpoints = derive_breakpoints(summaries)
    sharpness_mechanics = None
    if not allow_blocked_tune_only and not analysis_blockers:
        holdout_positive_weights = sorted(
            {
                float(weight)
                for weight in selected_weights.values()
                if float(weight) > 0.0
            }
        )
        print("time-frontier holdout: distribution-sharpness mechanics", flush=True)
        sharpness_mechanics = analyze_holdout_sharpness(
            current_cache=plan["holdout"]["0.0"],
            selected_caches_by_weight={
                weight: plan["holdout"][str(weight)]
                for weight in holdout_positive_weights
            },
            selected_weights=selected_weights,
            expected_dates=holdout_dates,
        )
    evidence_split = "tune" if allow_blocked_tune_only else "holdout"
    historical_reproduction = compare_historical_pattern(
        historical_context,
        summaries,
        breakpoints,
        evidence_split=evidence_split,
    )
    denver_present = any(
        row["market_id"] == "denver"
        and row["target_date"] == "2026-07-19"
        and row["scope"] == "all_hours"
        for row in all_market_date_rows
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "BLOCK" if allow_blocked_tune_only else "COMPLETE",
        "analysis_status": (
            "BLOCKED_INPUT_INTEGRITY"
            if analysis_blockers
            else (
                "COMPLETE_TUNE_ONLY_EXPLORATORY"
                if allow_blocked_tune_only
                else "COMPLETE_HOLDOUT"
            )
        ),
        "research_only": True,
        "promotion_authorized": False,
        "serving_change": False,
        "inputs": {
            "h1": selection["payload"].get("inputs") or {},
            "h1_result": selection["path"],
            "cache_root": str(paths["cache_root"]),
            "tune_dates_file": str(paths["tune_dates_file"]),
            "holdout_dates_file": str(paths["holdout_dates_file"]),
            "date_manifests": date_manifest_hashes,
            "historical_hourly_json": (
                str(paths["historical_hourly_json"])
                if "historical_hourly_json" in paths
                else None
            ),
            "read_only_roots": [
                str(_resolved(root)) for root in (args.read_only_root or ())
            ],
            "opened_read_only": True,
        },
        "selection": {
            "h1_result_path": selection["path"],
            "h1_result_sha256": selection["sha256"],
            "h1_schema_version": H1_SCHEMA_VERSION,
            "selection_uses_holdout": False,
            "evidence_mode": selection["evidence_mode"],
            "selected_weights": selected_weights,
            "selection_details": selection["payload"]["tune"].get("selection")
            or {},
            "holdout_dispositions": selection["payload"]["holdout"].get(
                "dispositions"
            )
            or {},
            "actual_current_weight": 0.0,
            "tune_arms_opened": sorted(
                {0.0} | {w for w in selected_weights.values() if w > 0.0}
            ),
            "holdout_arms_opened": (
                []
                if allow_blocked_tune_only
                else sorted(
                    {0.0} | {w for w in selected_weights.values() if w > 0.0}
                )
            ),
        },
        "split": {
            "tune_dates": list(tune_dates),
            "tune_evidence_role": "EXPLORATORY_SELECTION_CONTEXT",
            "holdout_dates": list(holdout_dates),
            "holdout_evidence_role": (
                "SEALED_NOT_TOUCHED"
                if allow_blocked_tune_only
                else "UNTOUCHED_HOLDOUT"
            ),
            "analyzed_splits": list(analyzed_splits),
            "primary_evidence_split": evidence_split,
        },
        "method": {
            "row_alignment": "exact H1 replay identity key before scoring",
            "snapshot_score": (
                "mean binary band Brier/log-loss plus realized-winner probability"
            ),
            "market_benchmark": (
                "captured raw market_yes probabilities; not ex-post renormalized"
            ),
            "model_mass_gate": (
                "current and selected band probabilities sum to one within 1e-6"
            ),
            "primary_weighting": (
                "snapshot -> market-date mean -> fleet-date equal-market mean -> "
                "equal fleet-date mean"
            ),
            "complete_panel_sensitivity": (
                "retain only native-unit date/slots with every configured market "
                "(1 C + 11 F; 12 total); no imputation"
            ),
            "predawn_window_local": "03:00-05:59",
            "predawn_ten_minute_slots": (
                "fixed 03:00-05:50 local starts by floor(capture_minute/10); "
                "all 18 reported, no slot selection"
            ),
            "evening_window_local": "15:00-23:59",
            "bootstrap_unit": "paired fleet date",
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "bootstrap_seed_base": BOOTSTRAP_SEED,
            "maximum_aggregate_groups": MAX_AGGREGATE_GROUPS,
            "maximum_alignment_keys": MAX_ALIGNMENT_KEYS,
            "retained_stream_state": (
                "capped scoring-key/projection index plus snapshot/market-date/"
                "fleet-date aggregates; no full replay rows"
            ),
            "duplicate_identity_policy": (
                "KEEP_FIRST_ONLY_IF_CANONICALLY_SCORE_EQUIVALENT_ELSE_BLOCK"
            ),
            "sharpness_mechanics": (
                "descriptive exact bucket distributions on untouched holdout; "
                "never used for selection or a promotion gate"
            ),
            "full_cache_loaded": False,
        },
        "h1_gate": {
            "h1_status": selection["payload"].get("status"),
            "tune_status": (selection["payload"].get("tune") or {}).get("status"),
            "holdout_status": (selection["payload"].get("holdout") or {}).get(
                "status"
            ),
            "technical_blocker_count": len(selection["technical_blockers"]),
            "technical_blocker_examples": selection["technical_blockers"][:8],
            "weight_zero_determinism": (
                (selection["payload"].get("tune") or {}).get(
                    "weight_zero_determinism"
                )
                or {}
            ),
        },
        "analysis_blockers": analysis_blockers,
        "cache_metadata": {
            key: value.as_dict() for key, value in metadata.items()
        },
        "reader_diagnostics": diagnostics,
        "summaries": summaries,
        "complete_panel_sensitivity": {
            "panel_scope": "COMPLETE_CONFIGURED_NATIVE_UNIT_PANEL",
            "configured_market_count": sum(
                len(values) for values in configured_panel.values()
            ),
            "configured_markets_by_unit": {
                unit: list(values) for unit, values in configured_panel.items()
            },
            "imputation_used": False,
            "coverage": complete_panel_coverage,
            "summaries": complete_panel_summaries,
            "breakpoints": complete_panel_breakpoints,
        },
        "sharpness_mechanics": sharpness_mechanics,
        "breakpoints": breakpoints,
        "historical_context": historical_context,
        "historical_pattern_reproduction": historical_reproduction,
        "denver_2026_07_19_case": {
            "in_h1_scored_split": denver_present,
            "interpretation": (
                "Denver 2026-07-19 is in the H1 scored split and is reported "
                "only as a bounded per-market case."
                if denver_present
                else (
                    "Denver 2026-07-19 is outside both predeclared H1 splits, so "
                    "this experiment does not manufacture a post-hoc H1 score. "
                    "The dated taker report localizes cool-tail leakage only as "
                    "motivation, not evidence about the H1 selected arm."
                )
            ),
        },
        "outputs": {},
    }

    cache_hashes = {}
    for identity, item in metadata.items():
        print(f"hashing immutable cache {identity}", flush=True)
        cache_hashes[identity] = {
            **item.as_dict(),
            "sha256": sha256_stable_file(
                item.path,
                expected_size_bytes=item.size_bytes,
                expected_mtime_ns=item.mtime_ns,
            ),
        }
    payload["immutable_input_caches"] = cache_hashes

    output_root = paths["output_root"]
    output_root.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "result_json": output_root / "current_replay_time_frontier.json",
        "market_date_csv": output_root / "market_date_metrics.csv",
        "fleet_date_csv": output_root / "fleet_date_metrics.csv",
        "summary_csv": output_root / "summary_metrics.csv",
        "complete_panel_fleet_date_csv": (
            output_root / "complete_panel_fleet_date_metrics.csv"
        ),
        "complete_panel_summary_csv": (
            output_root / "complete_panel_summary_metrics.csv"
        ),
        "complete_panel_coverage_json": output_root / "complete_panel_coverage.json",
        "sharpness_mechanics_json": output_root / "sharpness_mechanics.json",
        "breakpoints_json": output_root / "breakpoints.json",
        "report": paths["report_out"],
    }
    integrity_path = output_root / "integrity_manifest.json"
    for output in output_paths.values():
        if output.exists():
            raise ExperimentConfigurationError(f"refusing to overwrite output: {output}")
    payload["outputs"] = {
        **{key: str(path) for key, path in output_paths.items()},
        "integrity_manifest": str(integrity_path),
    }
    _atomic_write_json(output_paths["result_json"], payload)
    _write_csv(output_paths["market_date_csv"], all_market_date_rows)
    _write_csv(output_paths["fleet_date_csv"], fleet_date_rows)
    _write_csv(output_paths["summary_csv"], _flat_summary_rows(summaries))
    _write_csv(output_paths["complete_panel_fleet_date_csv"], complete_panel_rows)
    _write_csv(
        output_paths["complete_panel_summary_csv"],
        _flat_summary_rows(complete_panel_summaries),
    )
    _atomic_write_json(
        output_paths["complete_panel_coverage_json"], complete_panel_coverage
    )
    _atomic_write_json(
        output_paths["sharpness_mechanics_json"], sharpness_mechanics
    )
    _atomic_write_json(output_paths["breakpoints_json"], breakpoints)
    _atomic_write_text(output_paths["report"], render_report(payload))

    integrity = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": payload["status"],
        "analysis_status": payload["analysis_status"],
        "evidence_mode": selection["evidence_mode"],
        "holdout_arms_opened": payload["selection"]["holdout_arms_opened"],
        "h1_result": {"path": selection["path"], "sha256": selection["sha256"]},
        "date_manifests": date_manifest_hashes,
        "historical_context": (
            {
                "path": historical_context["path"],
                "sha256": historical_context["sha256"],
                "schema_version": historical_context["schema_version"],
                "evidence_role": historical_context["evidence_role"],
            }
            if historical_context
            else None
        ),
        "immutable_input_caches": cache_hashes,
        "outputs": {
            key: {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for key, path in output_paths.items()
        },
        "data_written": False,
        "full_cache_loaded": False,
    }
    _atomic_write_json(integrity_path, integrity)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Memory-bounded current-replay time frontier for tune-selected H1 arms."
        )
    )
    parser.add_argument("--h1-result", required=True)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--tune-dates-file", required=True)
    parser.add_argument("--holdout-dates-file", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--report-out", required=True)
    parser.add_argument(
        "--allow-blocked-tune-only",
        action="store_true",
        help=(
            "Consume only finalized tune incumbent/selected caches from an H1 "
            "BLOCK whose holdout is NOT_TOUCHED; output remains BLOCK research."
        ),
    )
    parser.add_argument(
        "--historical-hourly-json",
        help="Optional read-only hourly_model_performance_v0.3 dated comparator.",
    )
    parser.add_argument(
        "--read-only-root",
        action="append",
        required=True,
        help="Input root beneath which every write is prohibited; repeatable.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_experiment(args)
    print(
        "current-replay time frontier "
        f"{payload['status']}: {payload['analysis_status']} -> "
        f"{payload['outputs']['result_json']}",
        flush=True,
    )
    return 0


__all__ = ["build_parser", "main", "run_experiment"]
