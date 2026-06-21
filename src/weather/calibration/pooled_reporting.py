"""Implementation slice extracted from src/weather/calibration/pooled_feature_model.py."""

from weather.calibration.pooled_artifact_io import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def training_metric_rows(validation_rows):
    rows = []
    for row in validation_rows:
        metrics = row.get("training_metrics") or {}
        if not metrics:
            continue
        rows.append([
            f"{row['hour']:02d}:00",
            metrics.get("matrix_rows"),
            metrics.get("matrix_columns"),
            fmt_num(metrics.get("matrix_build_seconds"), 6),
            fmt_num(metrics.get("model_fit_seconds"), 6),
            metrics.get("performance_warning_count", 0),
        ])
    return rows


def blocked_validation_metric_rows(validation_rows):
    rows = []
    for row in validation_rows:
        audit = row.get("blocked_validation") or {}
        rows.append([
            f"{row['hour']:02d}:00",
            "PASS" if audit.get("ok") else "FAIL",
            audit.get("market_day_count", 0),
            audit.get("target_date_count", 0),
            audit.get("split_count", 0),
            audit.get("leak_count", 0),
        ])
    return rows


def write_report(path, records, counts, validation_rows, holdout_year, artifact_path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# F-Family Pooled Feature Model",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"Artifact: `{artifact_path}`",
        f"Holdout year: {holdout_year or '-'}",
        "",
        "## Dataset",
        "",
    ]
    lines += markdown_table(
        ["Market", "Rows"],
        [[market_id, count] for market_id, count in sorted(counts.items())],
    )
    lines += [
        "",
        f"Total rows: {len(records)}",
        "",
        "## Training Throughput",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Matrix Rows", "Matrix Columns", "Build Seconds", "Fit Seconds", "Warnings"],
        training_metric_rows(validation_rows),
    )
    lines += [
        "",
        "## Blocked Validation Audit",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Audit", "Market Days", "Target Dates", "Splits", "Leaks"],
        blocked_validation_metric_rows(validation_rows),
    )
    lines += [
        "",
        "## Hourly Validation",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Train Rows", "Eval Rows", "Eval LogLoss", "Winning-Bucket Brier"],
        [
            [
                f"{row['hour']:02d}:00",
                row["train_rows"],
                row["eval_rows"],
                fmt_num((row.get("eval_score") or {}).get("logloss")),
                fmt_num((row.get("eval_score") or {}).get("winning_bucket_brier")),
            ]
            for row in validation_rows
        ],
    )
    lines += ["", "## Holdout By Market", ""]
    market_rows = []
    for row in validation_rows:
        for score in row.get("market_scores") or []:
            market_rows.append([
                score["market_id"],
                f"{row['hour']:02d}:00",
                score["n"],
                fmt_num(score.get("logloss")),
                fmt_num(score.get("winning_bucket_brier")),
            ])
    lines += markdown_table(
        ["Market", "Hour", "Rows", "LogLoss", "Winning-Bucket Brier"],
        market_rows,
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_density_report(path, records, counts, validation_rows, holdout_year, artifact_path, artifact=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = artifact or {}
    density_postprocess = artifact.get("density_postprocess") or {}
    lines = [
        "# Pooled Continuous-Density Model",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Schema: `{artifact.get('schema_version') or 'pooled_continuous_density_hgb_v0.7'}`",
        f"Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"Artifact: `{artifact_path}`",
        f"Holdout year: {holdout_year or '-'}",
        f"Grid: `{artifact.get('grid_low_f')}` to `{artifact.get('grid_high_f')}` F "
        f"step `{artifact.get('grid_step_f')}`",
        "",
        "## Objective",
        "",
        "This candidate trains one pooled regressor over all configured markets,",
        "converts temperature-like features and targets to canonical Fahrenheit,",
        "and emits a continuous density on the canonical-F grid. Market C/F",
        "bands are projected only at serving/replay time through",
        "`continuous_density_f` payloads.",
        "v0.4 estimates the final Gaussian width by grid-searching holdout",
        "market-band Brier on synthetic native eq/lte/gte bands when enough",
        "holdout rows exist, falling back to in-sample residuals only when",
        "validation evidence is too sparse.",
        "v0.5 extends that search to density-shape policies, including modest",
        "tail mixtures and forecast/climatology anchor mixtures, while retaining",
        "Gaussian fallback when holdout evidence is too sparse.",
        "v0.6 fits a holdout market-band postprocess for density projections,",
        "using exact-winner catch-up and adjacent-band shrinkage before replay",
        "partition normalization.",
        "v0.7 adds a holdout-selected forecast-relative calibration layer for",
        "band-vs-forecast pressure, forecast disagreement, source count, hour,",
        "market, and floor-gap contexts.",
        "",
        "## Dataset",
        "",
    ]
    lines += markdown_table(
        ["Market", "Source Rows"],
        [[market_id, count] for market_id, count in sorted(counts.items())],
    )
    lines += [
        "",
        f"Total source rows: {len(records)}",
        "",
        "## Density Market-Band Postprocess",
        "",
    ]
    exact = density_postprocess.get("exact_winner_catchup") or {}
    adjacent = density_postprocess.get("adjacent_calibration") or {}
    forecast_relative = density_postprocess.get("forecast_relative_calibration") or {}
    selection = density_postprocess.get("selection") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Schema", density_postprocess.get("schema_version") or "-"],
            ["Enabled", bool(density_postprocess.get("enabled"))],
            ["Selected policy", density_postprocess.get("policy_id") or "-"],
            ["Baseline band Brier", fmt_num(selection.get("baseline_market_band_brier"))],
            ["Selected band Brier", fmt_num(selection.get("selected_market_band_brier"))],
            ["Calibration rows", density_postprocess.get("calibration_rows", 0)],
            ["Adjacent contexts", adjacent.get("context_count", 0)],
            ["Exact-winner contexts", exact.get("context_count", 0)],
            ["Exact selected strength", fmt_num(exact.get("strength"))],
            ["Forecast-relative enabled", bool(density_postprocess.get("forecast_relative_calibration_enabled"))],
            ["Forecast-relative contexts", forecast_relative.get("context_count", 0)],
            ["Forecast-relative strength", fmt_num(forecast_relative.get("strength"))],
            ["Partition normalization", bool(density_postprocess.get("partition_normalization_enabled"))],
            ["Partition gamma", fmt_num(density_postprocess.get("partition_normalization_gamma"))],
        ],
    )
    lines += [
        "",
        "## Training Throughput",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Matrix Rows", "Matrix Columns", "Build Seconds", "Fit Seconds", "Warnings"],
        training_metric_rows(validation_rows),
    )
    lines += [
        "",
        "## Blocked Validation Audit",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Audit", "Market Days", "Target Dates", "Splits", "Leaks"],
        blocked_validation_metric_rows(validation_rows),
    )
    lines += [
        "",
        "## Hourly Holdout Validation",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Train Rows", "Eval Rows", "RMSE Sigma F", "Final Sigma F", "Shape", "Sigma Source",
         "RMSE Band Brier", "Tuned Band Brier", "Winner Brier", "Density LogLoss", "MAE F"],
        [
            [
                f"{row['hour']:02d}:00",
                row["train_rows"],
                row["eval_rows"],
                fmt_num(row.get("sigma_f")),
                fmt_num(row.get("final_sigma_f")),
                row.get("final_density_shape_id") or "gaussian",
                row.get("final_sigma_source") or "-",
                fmt_num((row.get("baseline_eval_score") or {}).get("market_band_brier")),
                fmt_num((row.get("eval_score") or {}).get("market_band_brier")),
                fmt_num((row.get("eval_score") or {}).get("winning_bucket_brier")),
                fmt_num((row.get("eval_score") or {}).get("density_logloss")),
                fmt_num((row.get("eval_score") or {}).get("mean_absolute_error_f")),
            ]
            for row in validation_rows
        ],
    )
    lines += ["", "## Holdout By Market", ""]
    market_rows = []
    for row in validation_rows:
        for score in row.get("market_scores") or []:
            market_rows.append([
                score["market_id"],
                f"{row['hour']:02d}:00",
                score["n"],
                score.get("density_shape_id") or row.get("final_density_shape_id") or "gaussian",
                fmt_num(score.get("market_band_brier")),
                fmt_num(score.get("density_logloss")),
                fmt_num(score.get("winning_bucket_brier")),
                fmt_num(score.get("mean_absolute_error_f")),
            ])
    lines += markdown_table(
        ["Market", "Hour", "Rows", "Shape", "Band Brier", "Density LogLoss", "Winner Brier", "MAE F"],
        market_rows,
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_band_report(path, records, counts, validation_rows, holdout_year, artifact_path, artifact=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = artifact or {}
    postprocess = artifact.get("postprocess") or {}
    schema = artifact.get("schema_version") or "pooled_feature_band_hgb_v0.3"
    family_unit = artifact.get("family_unit") or "F"
    family_label = "All-Market" if str(family_unit).lower() == "all" else f"{family_unit}-Family"
    subset_contract = artifact.get("feature_subset_contract") or feature_subset_contract(
        artifact.get("feature_subset") or FEATURE_SUBSET_ALL
    )
    lines = [
        f"# {family_label} Pooled Band Model {schema}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"Artifact: `{artifact_path}`",
        f"Family unit: `{family_unit}`",
        f"Objective: `{artifact.get('objective') or 'binary_market_band_brier_source_reliability'}`",
        f"Feature subset: `{subset_contract.get('name')}`",
        f"Holdout year: {holdout_year or '-'}",
        "",
        "## Objective",
        "",
        "This candidate trains a binary model directly on market-band outcomes",
        "(`eq`/range, `lte`, and `gte`) instead of training an exact-bucket",
        "classifier and summing it after the fact. Training rows are generated",
        "from historical WU feature records and synthetic market-style bands;",
        "the pinned promotion corpus remains out-of-sample replay evidence.",
        "",
        "Hard WU-floor rules are applied deterministically, and a late-day",
        "lock-in blend concentrates probabilities toward the printed high when",
        "the day is late and cooling.",
        "",
        "v0.3 adds static per-market source-reliability priors learned from",
        "WU-vs-METAR/ASOS/GHCNh/reanalysis daily overlaps. These are source",
        "trust features, not same-day final redundant highs, so the candidate",
        "does not leak settlement information into intraday training rows.",
        "",
        "Exact-winner catch-up is "
        f"{'enabled' if postprocess.get('exact_winner_catchup_enabled') else 'disabled'}"
        " for this artifact.",
        "Dynamic source-state features are "
        f"{'enabled' if artifact.get('dynamic_source_state_enabled') else 'disabled'}"
        " for this artifact.",
        "",
        "## Feature Subset Contract",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Subset", subset_contract.get("name")],
            ["Schema", subset_contract.get("schema_version")],
            ["Anchor", subset_contract.get("anchor_feature") or "-"],
            ["Description", subset_contract.get("description") or "-"],
            ["Allowed families", ", ".join(subset_contract.get("allowed_feature_families") or []) or "-"],
            ["Blocked families", ", ".join(subset_contract.get("blocked_feature_families") or []) or "-"],
            ["Postprocess policy", subset_contract.get("postprocess_policy") or "-"],
        ],
    )
    market_bias = postprocess.get("market_bias_calibration") or {}
    market_bias_selection = market_bias.get("selection") or {}
    lines += [
        "",
        "## Postprocess Calibration",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Adjacent calibration contexts", (postprocess.get("adjacent_calibration") or {}).get("context_count", 0)],
            ["Market bias calibration enabled", bool(postprocess.get("market_bias_calibration_enabled"))],
            ["Market bias calibration contexts", market_bias.get("context_count", 0)],
            [
                "Market bias holdout Brier",
                (
                    f"{fmt_num(market_bias_selection.get('baseline_brier'))} -> "
                    f"{fmt_num(market_bias_selection.get('candidate_brier'))}"
                ),
            ],
            ["Market bias holdout delta", fmt_num(market_bias_selection.get("delta_brier"))],
            ["Market bias disabled reason", market_bias.get("disabled_reason") or "-"],
        ],
    )
    lines += [
        "",
        "## Training Throughput",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Matrix Rows", "Matrix Columns", "Build Seconds", "Fit Seconds", "Warnings"],
        training_metric_rows(validation_rows),
    )
    lines.append("")
    weak_preflight = artifact.get("weak_input_family_preflight") or {}
    lines += [
        "## Weak Input-Family Preflight",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", weak_preflight.get("status") or "-"],
            ["Features checked", weak_preflight.get("feature_count", 0)],
            ["Diagnostic families", ", ".join(weak_preflight.get("diagnostic_only_families") or []) or "-"],
            ["Warning count", len(weak_preflight.get("warnings") or [])],
        ],
    )
    if weak_preflight.get("warnings"):
        lines += ["", "### Weak-Family Warnings", ""]
        lines += markdown_table(
            ["Family", "Disposition", "Features", "Reasons"],
            [
                [
                    row.get("family"),
                    row.get("disposition"),
                    row.get("feature_count"),
                    "; ".join(row.get("reasons") or []),
                ]
                for row in weak_preflight.get("warnings") or []
            ],
        )
    lines.append("")
    lines += [
        "## Blocked Validation Audit",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Audit", "Market Days", "Target Dates", "Splits", "Leaks"],
        blocked_validation_metric_rows(validation_rows),
    )
    lines.append("")
    exact_calibration = postprocess.get("exact_winner_catchup") or {}
    strength_diagnostics = exact_calibration.get("strength_diagnostics") or {}
    selected_strength = strength_diagnostics.get("selected") or {}
    baseline_strength = strength_diagnostics.get("baseline") or {}
    if postprocess.get("exact_winner_catchup_enabled"):
        lines += [
            "## Exact-Winner Catch-Up Guardrail",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Contexts", exact_calibration.get("context_count", 0)],
                ["Selected strength", fmt_num(exact_calibration.get("strength"))],
                ["One-above tolerance", fmt_num(strength_diagnostics.get("one_above_tolerance"))],
                ["Normalization gamma", fmt_num(strength_diagnostics.get("normalization_gamma"))],
                ["Baseline settlement-distance-0 Brier", fmt_num(baseline_strength.get("distance0_brier"))],
                ["Selected settlement-distance-0 delta", fmt_num(selected_strength.get("distance0_delta_vs_base"))],
                ["Baseline one-above Brier", fmt_num(baseline_strength.get("one_above_brier"))],
                ["Selected one-above delta", fmt_num(selected_strength.get("one_above_delta_vs_base"))],
                ["Baseline exact-band Brier", fmt_num(baseline_strength.get("eq_brier"))],
                ["Selected exact-band delta", fmt_num(selected_strength.get("eq_delta_vs_base"))],
            ],
        )
        lines += ["", "### Strength Candidates", ""]
        lines += markdown_table(
            [
                "Strength", "Passed", "Distance-0 Brier", "Distance-0 Delta",
                "One-Above Brier", "One-Above Delta", "EQ Brier", "EQ Delta",
            ],
            [
                [
                    fmt_num(row.get("strength")),
                    "yes" if row.get("passed") else "no",
                    fmt_num(row.get("distance0_brier")),
                    fmt_num(row.get("distance0_delta_vs_base")),
                    fmt_num(row.get("one_above_brier")),
                    fmt_num(row.get("one_above_delta_vs_base")),
                    fmt_num(row.get("eq_brier")),
                    fmt_num(row.get("eq_delta_vs_base")),
                ]
                for row in strength_diagnostics.get("candidates") or []
            ],
        )
        lines += [""]
    lines += [
        "## Dataset",
        "",
    ]
    lines += markdown_table(
        ["Market", "Source Rows"],
        [[market_id, count] for market_id, count in sorted(counts.items())],
    )
    lines += [
        "",
        f"Total source rows: {len(records)}",
        "",
        "## Hourly Holdout Validation",
        "",
    ]
    lines += markdown_table(
        [
            "Hour", "Source Train", "Band Train", "Source Eval",
            "Temp", "Raw Brier", "Post Brier", "LogLoss",
            "Positive Mean P", "Exact Winner Mean P", "Late Brier",
        ],
        [
            [
                f"{row['hour']:02d}:00",
                row["source_train_rows"],
                row["band_train_rows"],
                row["source_eval_rows"],
                fmt_num(row.get("temperature")),
                fmt_num((row.get("raw_eval_score") or {}).get("brier")),
                fmt_num((row.get("eval_score") or {}).get("brier")),
                fmt_num((row.get("eval_score") or {}).get("logloss")),
                fmt_num((row.get("eval_score") or {}).get("positive_mean_p")),
                fmt_num((row.get("eval_score") or {}).get("exact_winner_mean_p")),
                fmt_num((row.get("eval_score") or {}).get("late_brier")),
            ]
            for row in validation_rows
        ],
    )
    lines += ["", "## Holdout By Market", ""]
    market_rows = []
    for row in validation_rows:
        for score in row.get("market_scores") or []:
            market_rows.append([
                score["market_id"],
                f"{row['hour']:02d}:00",
                score["n"],
                fmt_num(score.get("brier")),
                fmt_num(score.get("logloss")),
                fmt_num(score.get("positive_mean_p")),
                fmt_num(score.get("exact_winner_mean_p")),
                fmt_num(score.get("late_brier")),
            ])
    lines += markdown_table(
        ["Market", "Hour", "Rows", "Brier", "LogLoss", "Positive Mean P",
         "Exact Winner Mean P", "Late Brier"],
        market_rows,
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
