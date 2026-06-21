"""Implementation slice extracted from src/weather/reporting/hourly_model_performance.py."""

from weather.reporting.hourly_model_context import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def fmt_num(value, decimals=4):
    if value is None:
        return "-"
    try:
        if math.isnan(float(value)):
            return "-"
    except (TypeError, ValueError):
        return "-"
    return f"{float(value):.{decimals}f}"


def fmt_pct(value):
    if value is None:
        return "-"
    try:
        if math.isnan(float(value)):
            return "-"
    except (TypeError, ValueError):
        return "-"
    return f"{float(value) * 100:.1f}%"


def fmt_signed(value, decimals=4):
    if value is None:
        return "-"
    try:
        if math.isnan(float(value)):
            return "-"
    except (TypeError, ValueError):
        return "-"
    return f"{float(value):+.{decimals}f}"


def hour_table_rows(rows):
    return [
        [
            row.get("hour_label"),
            row.get("n"),
            row.get("market_days"),
            row.get("markets"),
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("brier_delta")),
            fmt_num(row.get("model_logloss")),
            fmt_signed(row.get("logloss_delta")),
            fmt_num(row.get("model_ece")),
            fmt_pct(row.get("winner_model_probability")),
            fmt_pct(row.get("loser_model_probability")),
            fmt_num(row.get("mean_feature_forecast_gap"), 2),
        ]
        for row in rows
    ]


def remediation_table_rows(rows, parameter_label):
    output = []
    for row in rows:
        best = row.get("best") or {}
        output.append([
            row.get("hour_label"),
            fmt_num(row.get("base_model_brier")),
            best.get("parameter"),
            fmt_num(best.get("model_brier")),
            fmt_signed(best.get("brier_delta_vs_base")),
            fmt_num(best.get("model_logloss")),
            fmt_signed(best.get("logloss_delta_vs_base")),
            parameter_label,
        ])
    return output


def regime_table_rows(rows):
    return [
        [
            row.get("regime_label"),
            row.get("n"),
            row.get("market_days"),
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("brier_delta")),
            fmt_signed(row.get("partition_winner_probability_gap")),
            fmt_num(row.get("partition_model_effective_bands"), 2),
            fmt_num(row.get("partition_market_effective_bands"), 2),
            fmt_signed(row.get("partition_effective_band_gap"), 2),
            fmt_pct(row.get("partition_model_top_probability")),
            fmt_pct(row.get("partition_market_top_probability")),
        ]
        for row in rows
    ]


def early_market_delta_table_rows(rows):
    return [
        [
            row.get("market_id"),
            row.get("status"),
            ",".join(row.get("blocking_gates") or []) or "-",
            row.get("n"),
            row.get("market_days"),
            row.get("snapshots"),
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("brier_delta")),
            fmt_num(row.get("model_logloss")),
            fmt_num(row.get("market_logloss")),
            fmt_signed(row.get("logloss_delta")),
            fmt_num(row.get("model_ece")),
            fmt_pct(row.get("winner_model_probability")),
            fmt_pct(row.get("winner_market_probability")),
        ]
        for row in rows
    ]


def spread_table_rows(rows):
    return [
        [
            row.get("hour_label"),
            fmt_num(row.get("partition_model_effective_bands"), 2),
            fmt_num(row.get("partition_market_effective_bands"), 2),
            fmt_signed(row.get("partition_effective_band_gap"), 2),
            fmt_pct(row.get("partition_model_top_probability")),
            fmt_pct(row.get("partition_market_top_probability")),
            fmt_signed(row.get("partition_top_probability_gap"), 3),
            fmt_pct(row.get("partition_model_top_is_winner_rate")),
            fmt_pct(row.get("partition_market_top_is_winner_rate")),
            fmt_signed(row.get("partition_winner_rank_gap"), 2),
        ]
        for row in rows
    ]


def cutoff_context_table_rows(rows):
    return [
        [
            row.get("regime"),
            row.get("evidence_status"),
            fmt_pct(row.get("forecast_component_weight")),
            fmt_pct(row.get("observed_component_weight")),
            fmt_pct(row.get("forecast_family_weight")),
            fmt_pct(row.get("observed_path_weight")),
            fmt_pct(row.get("source_state_weight")),
            fmt_signed(row.get("candidate_delta_vs_current")),
            fmt_signed(row.get("candidate_delta_vs_market")),
            row.get("status") or "-",
        ]
        for row in rows
    ]


def forecast_profile_slice_rows(rows):
    return [
        [
            row.get("regime"),
            row.get("n"),
            fmt_num(row.get("candidate_brier")),
            fmt_num(row.get("current_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_current")),
            fmt_signed(row.get("delta_vs_market")),
        ]
        for row in rows
    ]


def forecast_profile_subfamily_rows(rows):
    return [
        [
            row.get("subfamily"),
            fmt_num(row.get("positive_delta_mae_sum"), 4),
            row.get("best_feature"),
            fmt_num(row.get("best_feature_delta_mae"), 4),
            fmt_num(row.get("min_hgb_importance_q"), 4),
        ]
        for row in rows
    ]


def _row_by_key(rows, key, value):
    for row in rows:
        if row.get(key) == value:
            return row
    return None


def generated_interpretation(payload):
    diagnostics = payload.get("deep_diagnostics") or {}
    variable_context = diagnostics.get("variable_weight_context") or {}
    regimes = payload.get("by_hour_regime") or []
    early = _row_by_key(regimes, "regime", "early_morning")
    lock_in = _row_by_key(regimes, "regime", "lock_in")
    worst = payload.get("worst_hours") or []
    notes = []

    if early and lock_in:
        notes.append(
            "Early morning trails the market because winner recognition is weak before the day develops: "
            f"the model gives the eventual winner {fmt_pct(early.get('partition_model_winner_probability'))} "
            f"versus the market's {fmt_pct(early.get('partition_market_winner_probability'))}, "
            f"and ranks the winner {fmt_signed(early.get('partition_winner_rank_gap'), 2)} bands worse."
        )
        notes.append(
            "The spread story is mixed: early model effective bands are "
            f"{fmt_num(early.get('partition_model_effective_bands'), 2)} versus market "
            f"{fmt_num(early.get('partition_market_effective_bands'), 2)} "
            f"({fmt_signed(early.get('partition_effective_band_gap'), 2)}). "
            "So the question is not just whether probabilities are sharper; it is whether the partition is centered on the right bands."
        )
        notes.append(
            "The best late hours are best because the model itself has mostly collapsed to a narrow partition "
            f"({fmt_num(lock_in.get('partition_model_effective_bands'), 2)} effective bands) with high top probability "
            f"({fmt_pct(lock_in.get('partition_model_top_probability'))}), even though market prices are still more certain."
        )

    if worst:
        worst_labels = ", ".join(row.get("hour_label") for row in worst)
        worst_gap = mean(row.get("partition_winner_probability_gap") for row in worst)
        worst_rank = mean(row.get("partition_winner_rank_gap") for row in worst)
        notes.append(
            f"The worst hours ({worst_labels}) show the market assigning more probability to the eventual winner "
            f"({fmt_signed(worst_gap, 3)} model-minus-market winner gap) and ranking the winner "
            f"{fmt_signed(worst_rank, 2)} bands worse on average."
        )

    remediation = payload.get("remediation_candidates") or {}
    partition_rows = (remediation.get("partition_power") or {}).get("early_hours") or []
    if partition_rows:
        best_delta = mean((row.get("best") or {}).get("brier_delta_vs_base") for row in partition_rows)
        notes.append(
            "The partition-power probe remains the falsification test for simple reshaping: "
            f"average early-hour Brier change is only {fmt_signed(best_delta)}, so broad sharpening/softening is not the main fix."
        )

    cutoff = variable_context.get("cutoff_regime_weighting") or {}
    if cutoff.get("available"):
        weights = cutoff.get("regime_family_weights") or []
        early_weight = _row_by_key(weights, "regime", "early")
        late_weight = _row_by_key(weights, "regime", "late")
        if early_weight and late_weight:
            notes.append(
                "Variable weight should change through the day: companion evidence assigns "
                f"{fmt_pct(early_weight.get('forecast_component_weight'))} forecast weight early and "
                f"{fmt_pct(late_weight.get('observed_component_weight'))} observed-path weight late."
            )
        acceptance = cutoff.get("acceptance") or {}
        if acceptance.get("status"):
            notes.append(
                "The current regime-weighted candidate is still "
                f"{acceptance.get('status')}: it improves current Brier modestly but remains outside the market tolerance."
            )

    forecast_profile = variable_context.get("forecast_profile_calibration") or {}
    if forecast_profile.get("available"):
        top_subfamilies = forecast_profile.get("top_subfamilies") or []
        if top_subfamilies:
            names = ", ".join(row.get("subfamily") for row in top_subfamilies[:3])
            notes.append(
                "Within the forecast lane, the useful signal is concentrated in "
                f"{names}; low-marginal subfamilies should adjust confidence rather than override forecast_high."
            )

    return notes


def render_report(payload):
    corpus = payload.get("corpus") or {}
    inputs = payload.get("inputs") or {}
    overall = ((payload.get("overall") or {}).get("hourly_checkpoint") or {})
    best = payload.get("best_hours") or []
    worst = payload.get("worst_hours") or []
    notes = payload.get("driver_notes") or {}
    remediation = payload.get("remediation_candidates") or {}
    remediation_registry = payload.get("remediation_registry") or {}
    hourly_gate = payload.get("hourly_performance_gate") or {}
    daily_summary = payload.get("daily_summary") or {}
    diagnostics = payload.get("deep_diagnostics") or {}
    variable_context = diagnostics.get("variable_weight_context") or {}
    rerun = (
        ".\\venv\\Scripts\\python.exe -m weather.reporting.hourly_model_performance"
    )
    if inputs.get("quality_grades") != list(DEFAULT_QUALITY_GRADES):
        rerun += f" --quality-grades {','.join(inputs.get('quality_grades') or [])}"

    lines = [
        "# Hourly Model Performance Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Corpus",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Labels selected", corpus.get("selected_label_count", 0)],
            ["Scored market-days", corpus.get("scored_market_days", 0)],
            ["Markets", ", ".join(corpus.get("markets") or []) or "-"],
            ["Date range", f"{corpus.get('date_min') or '-'} to {corpus.get('date_max') or '-'}"],
            ["Quality grades", ", ".join(inputs.get("quality_grades") or []) or "-"],
            ["All snapshot rows", corpus.get("all_snapshot_rows", 0)],
            ["Hourly checkpoint rows", corpus.get("hourly_checkpoint_rows", 0)],
            ["Skipped labels", json.dumps(corpus.get("skipped_labels") or {}, sort_keys=True)],
            ["Score errors", len(corpus.get("score_errors") or [])],
        ],
    )

    lines += [
        "",
        "## How To Rerun",
        "",
        "```powershell",
        rerun,
        "```",
        "",
        (
            "Headline rows use the first available snapshot in each local hour for each "
            "market-day-band. This avoids overweighting hours that happened to collect "
            "more snapshots."
        ),
        "",
        "## Headline Score",
        "",
    ]
    lines += markdown_table(
        ["Scope", "Rows", "Market-days", "Model Brier", "Market Brier", "Brier Delta", "Model LogLoss", "LogLoss Delta", "Model ECE"],
        [[
            "Hourly checkpoints",
            overall.get("n", 0),
            overall.get("market_days", 0),
            fmt_num(overall.get("model_brier")),
            fmt_num(overall.get("market_brier")),
            fmt_signed(overall.get("brier_delta")),
            fmt_num(overall.get("model_logloss")),
            fmt_signed(overall.get("logloss_delta")),
            fmt_num(overall.get("model_ece")),
        ]],
    )
    lines += [
        "",
        "## Hourly Performance Gate",
        "",
    ]
    first_blocker = hourly_gate.get("first_blocker") or {}
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Status", hourly_gate.get("status") or "-"],
            ["Blockers", hourly_gate.get("blocker_count", 0)],
            ["First blocker", first_blocker.get("gate") or "-"],
            ["First blocker detail", first_blocker.get("detail") or "-"],
            ["Best hours", ", ".join(daily_summary.get("best_hours") or []) or "-"],
            ["Worst hours", ", ".join(daily_summary.get("worst_hours") or []) or "-"],
            ["Active remediation owners", ", ".join(daily_summary.get("active_remediation_owners") or []) or "-"],
        ],
    )
    blockers = hourly_gate.get("blockers") or []
    if blockers:
        lines += ["", "### Gate Blockers", ""]
        lines += markdown_table(
            ["Gate", "Detail", "Remediation"],
            [
                [
                    row.get("gate"),
                    row.get("detail"),
                    row.get("remediation_command"),
                ]
                for row in blockers
            ],
        )
    early_market_deltas = remediation_registry.get("early_hour_market_deltas") or []
    if early_market_deltas:
        early_market_summary = remediation_registry.get("summary") or {}
        lines += [
            "",
            "### Early-Hour Per-Market Deltas",
            "",
        ]
        lines += markdown_table(
            ["Metric", "Value"],
            [
                ["Markets scored", early_market_summary.get("early_hour_market_delta_count", 0)],
                ["Blocked markets", early_market_summary.get("early_hour_blocked_market_count", 0)],
                ["Brier-blocked markets", early_market_summary.get("early_hour_brier_blocked_market_count", 0)],
                ["LogLoss-blocked markets", early_market_summary.get("early_hour_logloss_blocked_market_count", 0)],
                ["Worst markets", ", ".join(early_market_summary.get("early_hour_worst_markets") or []) or "-"],
            ],
        )
        lines += markdown_table(
            [
                "Market",
                "Status",
                "Blocking Gates",
                "Rows",
                "Days",
                "Snapshots",
                "Model Brier",
                "Market Brier",
                "Brier Delta",
                "Model LogLoss",
                "Market LogLoss",
                "LogLoss Delta",
                "Model ECE",
                "Winner Model P",
                "Winner Market P",
            ],
            early_market_delta_table_rows(early_market_deltas),
        )

    lines += [
        "",
        "## Hour By Hour",
        "",
    ]
    lines += markdown_table(
        [
            "Hour",
            "Rows",
            "Days",
            "Markets",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Model LogLoss",
            "LogLoss Delta",
            "Model ECE",
            "Winner Model P",
            "Loser Model P",
            "Mean Forecast Gap",
        ],
        hour_table_rows(payload.get("by_hour") or []),
    )

    lines += [
        "",
        "## Best Hours",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Rows", "Days", "Model Brier", "Market Brier", "Winner Model P", "Loser Model P", "Mean Forecast Gap"],
        [
            [
                row.get("hour_label"),
                row.get("n"),
                row.get("market_days"),
                fmt_num(row.get("model_brier")),
                fmt_num(row.get("market_brier")),
                fmt_pct(row.get("winner_model_probability")),
                fmt_pct(row.get("loser_model_probability")),
                fmt_num(row.get("mean_feature_forecast_gap"), 2),
            ]
            for row in best
        ],
    )

    lines += [
        "",
        "## Worst Hours",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Rows", "Days", "Model Brier", "Market Brier", "Winner Model P", "Loser Model P", "Mean Forecast Gap"],
        [
            [
                row.get("hour_label"),
                row.get("n"),
                row.get("market_days"),
                fmt_num(row.get("model_brier")),
                fmt_num(row.get("market_brier")),
                fmt_pct(row.get("winner_model_probability")),
                fmt_pct(row.get("loser_model_probability")),
                fmt_num(row.get("mean_feature_forecast_gap"), 2),
            ]
            for row in worst
        ],
    )

    lines += ["", "## Driver Notes", ""]
    if notes.get("best"):
        lines.append("Best-hour drivers:")
        lines.extend(f"- {item}" for item in notes["best"])
        lines.append("")
    if notes.get("worst"):
        lines.append("Worst-hour drivers:")
        lines.extend(f"- {item}" for item in notes["worst"])
        lines.append("")
    if not notes.get("best") and not notes.get("worst"):
        lines.append("No hours met the minimum-row threshold for driver notes.")
        lines.append("")

    interpretation = generated_interpretation(payload)
    lines += ["## Deep Diagnostics", ""]
    if interpretation:
        lines.append("Generated interpretation:")
        lines.extend(f"- {item}" for item in interpretation)
        lines.append("")

    lines += [
        "### Hour Regimes",
        "",
    ]
    lines += markdown_table(
        [
            "Window",
            "Rows",
            "Days",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Winner P Gap",
            "Model Eff Bands",
            "Market Eff Bands",
            "Eff Gap",
            "Model Top P",
            "Market Top P",
        ],
        regime_table_rows(payload.get("by_hour_regime") or []),
    )

    lines += [
        "",
        "### Spread And Winner Recognition",
        "",
        (
            "Effective bands are computed per snapshot after normalizing the partition. "
            "Higher effective bands means probability is spread over more bands. "
            "Winner rank gap is model rank minus market rank, so positive means the model ranks the eventual winner worse."
        ),
        "",
    ]
    lines += markdown_table(
        [
            "Hour",
            "Model Eff Bands",
            "Market Eff Bands",
            "Eff Gap",
            "Model Top P",
            "Market Top P",
            "Top P Gap",
            "Model Top Winner",
            "Market Top Winner",
            "Winner Rank Gap",
        ],
        spread_table_rows(payload.get("by_hour") or []),
    )

    cutoff_context = variable_context.get("cutoff_regime_weighting") or {}
    forecast_context = variable_context.get("forecast_profile_calibration") or {}
    lines += [
        "",
        "### Variable Weight Evidence",
        "",
    ]
    if cutoff_context.get("available"):
        lines.append(
            "Cutoff-regime context from "
            f"`{relative_to_repo(cutoff_context.get('path'))}`."
        )
        lines.append("")
        lines += markdown_table(
            [
                "Regime",
                "Evidence",
                "Forecast Wt",
                "Observed Wt",
                "Forecast Family",
                "Observed Path",
                "Source State",
                "Delta Current",
                "Delta Market",
                "Status",
            ],
            cutoff_context_table_rows(cutoff_context.get("regime_family_weights") or []),
        )
        reasons = (cutoff_context.get("acceptance") or {}).get("reasons") or []
        if reasons:
            lines.append("")
            lines.append("Cutoff-regime blockers:")
            lines.extend(f"- {reason}" for reason in reasons)
    else:
        lines.append(f"Cutoff-regime context not found at `{cutoff_context.get('path')}`.")

    lines += ["", "Forecast-profile candidate context:", ""]
    if forecast_context.get("available"):
        status = forecast_context.get("status") or "-"
        reasons = forecast_context.get("reasons") or []
        lines.append(
            f"Status `{status}` from `{relative_to_repo(forecast_context.get('path'))}`."
        )
        if reasons:
            lines.extend(f"- {reason}" for reason in reasons)
        lines.append("")
        lines += markdown_table(
            ["Regime", "Rows", "Candidate Brier", "Current Brier", "Market Brier", "Delta Current", "Delta Market"],
            forecast_profile_slice_rows(forecast_context.get("required_slices") or []),
        )
        lines += ["", "Top forecast-profile subfamilies after the forecast_high anchor:", ""]
        lines += markdown_table(
            ["Subfamily", "Positive Delta MAE", "Best Feature", "Best Delta MAE", "Min q"],
            forecast_profile_subfamily_rows(forecast_context.get("top_subfamilies") or []),
        )
    else:
        lines.append(f"Forecast-profile context not found at `{forecast_context.get('path')}`.")
    lines.append("")

    market_blend = remediation.get("market_blend") or {}
    partition_power = remediation.get("partition_power") or {}
    lines += [
        "## Remediation Probes",
        "",
        (
            "These are replay-only probes. They do not change serving behavior; "
            "they indicate which remediation families are worth promoting into a "
            "candidate lane."
        ),
        "",
        "### Market-Price Blend",
        "",
        (
            "This is an operational de-risking probe, not a pure weather-model "
            "improvement. It uses market prices, so a high alpha reduces model "
            "error by leaning toward the benchmark we are trying to beat."
        ),
        "",
    ]
    lines += markdown_table(
        ["Hour", "Base Brier", "Best Alpha", "Best Brier", "Brier Change", "Best LogLoss", "LogLoss Change", "Parameter"],
        remediation_table_rows(market_blend.get("early_hours") or [], "alpha"),
    )
    lines += [
        "",
        "### Remediation Registry",
        "",
    ]
    registry_rows = []
    for row in remediation_registry.get("rows") or []:
        registry_rows.append([
            row.get("probe_name"),
            row.get("hour_regime"),
            row.get("row_count"),
            row.get("market_count"),
            fmt_signed(row.get("metric_delta")),
            fmt_signed(row.get("logloss_delta")),
            row.get("uses_market_prices"),
            row.get("owner"),
            row.get("serving_mitigation_status"),
            row.get("interpretation"),
        ])
    lines += markdown_table(
        [
            "Probe", "Regime", "Rows", "Markets", "Brier Delta", "LogLoss Delta",
            "Uses Market", "Owner", "Mitigation", "Interpretation",
        ],
        registry_rows,
    )
    lines += [
        "",
        "### Partition Power",
        "",
        (
            "This pure model-output probe asks whether the issue is just "
            "distribution sharpness. `gamma < 1` softens the partition and "
            "`gamma > 1` sharpens it."
        ),
        "",
    ]
    lines += markdown_table(
        ["Hour", "Base Brier", "Best Gamma", "Best Brier", "Brier Change", "Best LogLoss", "LogLoss Change", "Parameter"],
        remediation_table_rows(partition_power.get("early_hours") or [], "gamma"),
    )

    lines += [
        "",
        "## Caveats",
        "",
        "- Default scope includes only complete/manual-override settlement labels.",
        "- Intraday rows from the same market day remain correlated even after hourly checkpointing.",
        "- Temperature and forecast-gap driver averages are native-unit fields across mixed C/F markets, so use them directionally.",
        "- `Brier Delta` is market Brier minus model Brier, so positive means the model beat the market benchmark.",
        "",
    ]
    return "\n".join(lines)


CSV_COLUMNS = [
    "hour",
    "hour_label",
    "n",
    "market_days",
    "markets",
    "snapshots",
    "model_brier",
    "market_brier",
    "brier_delta",
    "brier_skill_score",
    "model_logloss",
    "market_logloss",
    "logloss_delta",
    "model_ece",
    "market_ece",
    "base_rate",
    "winner_model_probability",
    "winner_market_probability",
    "loser_model_probability",
    "loser_market_probability",
    "partition_snapshots",
    "partition_mean_band_count",
    "partition_model_effective_bands",
    "partition_market_effective_bands",
    "partition_effective_band_gap",
    "partition_model_norm_entropy",
    "partition_market_norm_entropy",
    "partition_norm_entropy_gap",
    "partition_model_top_probability",
    "partition_market_top_probability",
    "partition_top_probability_gap",
    "partition_winner_probability_gap",
    "partition_model_winner_rank",
    "partition_market_winner_rank",
    "partition_winner_rank_gap",
    "partition_model_top_is_winner_rate",
    "partition_market_top_is_winner_rate",
    "partition_model_adjacent_winner_mass",
    "partition_market_adjacent_winner_mass",
    "partition_adjacent_winner_mass_gap",
    "mean_feature_forecast_gap",
    "mean_feature_high_so_far",
    "mean_feature_current_temp",
]

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
