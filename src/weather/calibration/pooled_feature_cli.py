"""Implementation slice extracted from src/weather/calibration/pooled_feature_model.py."""

# ruff: noqa: F405 - implementation slices intentionally share facade globals

import sys

from weather.calibration.pooled_reporting import *  # noqa: F403
from weather.artifacts import (
    CandidateArtifactPathError,
    DEFAULT_CANDIDATE_ARTIFACT_ROOT,
    DEFAULT_IMMUTABLE_RELEASE_ROOT,
    training_artifact_output_policy,
)

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def parse_hours(value):
    if not value:
        return tuple(INTRADAY_CUTOFF_HOURS)
    return tuple(int(item.strip()) for item in str(value).split(",") if item.strip())


def training_output_paths(args):
    if args.objective == "density":
        return (
            args.artifact or str(DEFAULT_DENSITY_ARTIFACT),
            args.out or str(DEFAULT_DENSITY_REPORT),
        )
    if args.objective == "band":
        artifact = args.artifact or str(
            DEFAULT_FORECAST_RADIATION_BAND_ARTIFACT
            if args.feature_subset == FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION else
            DEFAULT_MARINE_CONTRAST_BAND_ARTIFACT
            if args.feature_subset == FEATURE_SUBSET_MARINE_WATER_CONTRAST else
            DEFAULT_FORECAST_PROFILE_BAND_ARTIFACT
            if args.feature_subset == FEATURE_SUBSET_FORECAST_PROFILE else
            DEFAULT_EXACT_WINNER_ARTIFACT
            if args.exact_winner_catchup else
            DEFAULT_DYNAMIC_SOURCE_ARTIFACT
            if args.dynamic_source_state else
            DEFAULT_BAND_ARTIFACT
        )
        report = args.out or str(
            DEFAULT_FORECAST_RADIATION_BAND_REPORT
            if args.feature_subset == FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION else
            DEFAULT_MARINE_CONTRAST_BAND_REPORT
            if args.feature_subset == FEATURE_SUBSET_MARINE_WATER_CONTRAST else
            DEFAULT_FORECAST_PROFILE_BAND_REPORT
            if args.feature_subset == FEATURE_SUBSET_FORECAST_PROFILE else
            DEFAULT_EXACT_WINNER_REPORT
            if args.exact_winner_catchup else
            DEFAULT_DYNAMIC_SOURCE_REPORT
            if args.dynamic_source_state else
            DEFAULT_BAND_REPORT
        )
        return artifact, report
    return (
        args.artifact or str(DEFAULT_ARTIFACT),
        args.out or str(DEFAULT_REPORT),
    )


def preflight_training_artifacts(
    artifact_path,
    report_path,
    min_free_bytes=DEFAULT_ARTIFACT_EXPORT_MIN_FREE_BYTES,
):
    min_free_bytes = int(min_free_bytes or 0)
    if not min_free_bytes:
        return []
    checks = []
    checks.append(ensure_artifact_disk_headroom(
        artifact_path,
        estimated_bytes=DEFAULT_TRAINING_OUTPUT_ESTIMATED_BYTES,
        min_free_bytes=min_free_bytes,
        context="pooled feature model training outputs",
    ))
    artifact_parent = Path(artifact_path).parent.resolve()
    report_parent = Path(report_path).parent.resolve()
    if report_parent != artifact_parent:
        checks.append(ensure_artifact_disk_headroom(
            report_path,
            estimated_bytes=1_000_000,
            min_free_bytes=min_free_bytes,
            context="pooled feature model training report",
        ))
    return [check for check in checks if check is not None]


def guard_training_artifact_output(args, artifact_path):
    try:
        result = training_artifact_output_policy(
            artifact_path,
            candidates_root=args.candidates_root,
            releases_root=args.releases_root,
            allow_legacy_serving_output=args.allow_legacy_serving_output,
        )
    except CandidateArtifactPathError as exc:
        raise SystemExit(
            f"Candidate-only training output required: {exc}. "
            "Choose --artifact below --candidates-root; the temporary "
            "--allow-legacy-serving-output flag is quarantined and cannot build a release."
        ) from exc
    if not result["release_eligible"]:
        print(
            "WARNING: legacy serving-path output is quarantined and ineligible for release construction.",
            file=sys.stderr,
        )
    return result


def main():
    parser = argparse.ArgumentParser(description="Train the F-family pooled feature model starter.")
    parser.add_argument("--family-unit", default=None, choices=["F", "all"])
    parser.add_argument("--objective", default="bucket", choices=["bucket", "band", "density"],
                        help=("bucket=v0.1 exact-bucket classifier; band=v0.2 direct market-band "
                              "classifier; density=canonical-F continuous-density candidate."))
    parser.add_argument("--hours", default=",".join(str(hour) for hour in INTRADAY_CUTOFF_HOURS))
    parser.add_argument("--max-days-per-market", type=int, default=0,
                        help="Optional newest-day cap for quick research/smoke runs; 0 uses all days.")
    parser.add_argument("--holdout-year", type=int, default=2025)
    parser.add_argument("--exact-winner-catchup", action="store_true",
                        help="Train the opt-in exact/range winner catch-up postprocess variant.")
    parser.add_argument("--dynamic-source-state", action="store_true",
                        help="Train the opt-in dynamic source-state feature variant.")
    parser.add_argument("--source-freshness-guardrail", action="store_true",
                        help="Blend non-all-fresh replay rows fully back to current serving.")
    parser.add_argument("--feature-subset", default=FEATURE_SUBSET_ALL, choices=FEATURE_SUBSET_CHOICES,
                        help=("Optional band-model feature subset. Use forecast_profile for roadmap item 134 "
                              "forecast_cloud_solar_radiation for roadmap item 187, or "
                              "marine_water_contrast for roadmap item 191."))
    parser.add_argument("--reanalysis-lane-json", default=None,
                        help="Source-family inventory JSON or promotion-lane JSON for Item 32 allowed-market masking.")
    parser.add_argument("--min-artifact-free-bytes", type=int, default=DEFAULT_ARTIFACT_EXPORT_MIN_FREE_BYTES,
                        help="Require this much free disk headroom before fitting and writing model artifacts. Use 0 to disable.")
    parser.add_argument("--write-merge-payload", action="store_true",
                        help="Embed holdout band rows/probabilities needed to merge hour-sharded band artifacts.")
    parser.add_argument("--merge-band-shards", nargs="+", default=None,
                        help="Merge hour-sharded band artifacts trained with --write-merge-payload.")
    parser.add_argument("--artifact", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--candidates-root", default=str(DEFAULT_CANDIDATE_ARTIFACT_ROOT))
    parser.add_argument("--releases-root", default=str(DEFAULT_IMMUTABLE_RELEASE_ROOT))
    parser.add_argument(
        "--allow-legacy-serving-output",
        action="store_true",
        help="Temporary compatibility only; output is quarantined and cannot become a release.",
    )
    args = parser.parse_args()
    if args.merge_band_shards:
        required_hours = parse_hours(args.hours)
        artifact_path_arg = args.artifact or str(DEFAULT_BAND_ARTIFACT)
        report_path_arg = args.out or str(DEFAULT_BAND_REPORT)
        guard_training_artifact_output(args, artifact_path_arg)
        preflight_training_artifacts(
            artifact_path_arg,
            report_path_arg,
            min_free_bytes=args.min_artifact_free_bytes,
        )
        artifact = merge_pooled_band_artifact_shards(
            args.merge_band_shards,
            required_hours=required_hours,
        )
        artifact_path = write_artifact(artifact, artifact_path_arg)
        report_path = write_band_shard_merge_report(
            report_path_arg,
            artifact,
            artifact_path,
        )
        print(
            f"Merged {len(args.merge_band_shards)} pooled band shard(s) into {artifact_path} "
            f"and report {report_path}."
        )
        return
    if args.exact_winner_catchup and args.dynamic_source_state:
        raise SystemExit("--exact-winner-catchup and --dynamic-source-state are separate shadow variants")
    if args.source_freshness_guardrail and args.objective != "band":
        raise SystemExit("--source-freshness-guardrail is currently supported only with --objective band")
    if args.source_freshness_guardrail and args.dynamic_source_state:
        raise SystemExit("--source-freshness-guardrail and --dynamic-source-state are separate guardrails")
    if args.feature_subset != FEATURE_SUBSET_ALL and args.objective != "band":
        raise SystemExit("--feature-subset is currently supported only with --objective band")
    if args.feature_subset != FEATURE_SUBSET_ALL and (args.exact_winner_catchup or args.dynamic_source_state):
        raise SystemExit("--feature-subset lanes cannot be combined with exact/dynamic source variants")
    reanalysis_promotion_lane = load_reanalysis_promotion_lane(args.reanalysis_lane_json)
    family_unit = args.family_unit or ("all" if args.objective == "density" else "F")
    if args.objective == "bucket" and family_unit != "F":
        raise SystemExit("--family-unit all is currently only supported with --objective band or density")
    if (
        args.objective == "band"
        and str(family_unit).lower() == "all"
        and (
            args.dynamic_source_state
            or args.feature_subset != FEATURE_SUBSET_ALL
            or args.reanalysis_lane_json
        )
    ):
        raise SystemExit(
            "--family-unit all --objective band is an Item 35 direct-band baseline "
            "and cannot be combined with F-family shadow lanes"
        )

    artifact_path_arg, report_path_arg = training_output_paths(args)
    guard_training_artifact_output(args, artifact_path_arg)
    preflight_training_artifacts(
        artifact_path_arg,
        report_path_arg,
        min_free_bytes=args.min_artifact_free_bytes,
    )

    records, counts = build_family_dataset(
        unit=family_unit,
        cutoff_hours=parse_hours(args.hours),
        max_days_per_market=args.max_days_per_market or None,
        reanalysis_promotion_lane=reanalysis_promotion_lane,
    )
    if not records:
        raise SystemExit("No pooled family records available.")
    if args.objective == "density":
        artifact, validation_rows = train_pooled_density_models(
            records,
            holdout_year=args.holdout_year,
        )
        artifact_path = write_artifact(artifact, artifact_path_arg)
        report_path = write_density_report(
            report_path_arg,
            records,
            counts,
            validation_rows,
            args.holdout_year,
            artifact_path,
            artifact=artifact,
        )
    elif args.objective == "band":
        artifact, validation_rows = train_pooled_band_models(
            records,
            holdout_year=args.holdout_year,
            exact_winner_catchup=args.exact_winner_catchup,
            dynamic_source_state=args.dynamic_source_state,
            feature_subset=args.feature_subset,
            reanalysis_promotion_lane=reanalysis_promotion_lane,
            family_unit=family_unit,
            source_freshness_guardrail=args.source_freshness_guardrail,
            write_merge_payload=args.write_merge_payload,
        )
        artifact_path = write_artifact(artifact, artifact_path_arg)
        report_path = write_band_report(
            report_path_arg,
            records,
            counts,
            validation_rows,
            args.holdout_year,
            artifact_path,
            artifact=artifact,
        )
    else:
        artifact, validation_rows = train_pooled_models(records, holdout_year=args.holdout_year)
        artifact_path = write_artifact(artifact, artifact_path_arg)
        report_path = write_report(
            report_path_arg,
            records,
            counts,
            validation_rows,
            args.holdout_year,
            artifact_path,
        )
    print(
        f"Wrote pooled {family_unit}-family {args.objective} artifact to {artifact_path} "
        f"and report to {report_path} over {len(records)} rows."
    )


if __name__ == "__main__":
    main()

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
