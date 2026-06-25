"""Markdown rendering for pooled candidate replay reports."""

from __future__ import annotations

import json
from pathlib import Path

from weather.reporting.formatting import fmt_num, fmt_pct, fmt_signed, markdown_table
from weather.reporting.data_quality.artifact_disk_budget import ensure_artifact_disk_headroom

def _fmt_delta(value):
    return fmt_signed(value, 4)


def _count_summary(counts):
    counts = counts or {}
    if not counts:
        return "-"
    return ", ".join(f"{key}: {counts[key]}" for key in sorted(counts)) or "-"


def _candidate_table_rows(items):
    rows = []
    for item in items:
        comp = item.get("comparison") if "comparison" in item else item
        trust = item.get("trust") or {}
        blocked = item.get("blocked_validation") or {}
        rows.append([
            item.get("market_id", item.get("group")),
            item.get("days", "-"),
            item.get("snapshots", "-"),
            comp.get("n", 0) if comp else 0,
            fmt_num((comp or {}).get("candidate_brier")),
            fmt_num((comp or {}).get("current_brier")),
            fmt_num((comp or {}).get("market_brier")),
            _fmt_delta((comp or {}).get("delta_vs_current")),
            _fmt_delta((comp or {}).get("delta_vs_market")),
            fmt_signed((comp or {}).get("candidate_skill"), 3),
            f"{trust.get('trust_score', '-')}/100 {trust.get('grade', '')}".strip() if trust else "-",
            blocked.get("verdict") or "-",
            item.get("verdict", "-"),
            item.get("reason", "-"),
        ])
    return rows


def _group_table_rows(items):
    return [
        [
            str(item.get("group")) if item.get("group") not in (None, "") else "-",
            item.get("n", 0),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            _fmt_delta(item.get("delta_vs_current")),
            _fmt_delta(item.get("delta_vs_market")),
            fmt_signed(item.get("candidate_skill"), 3),
            fmt_pct(item.get("base_rate")),
        ]
        for item in items
    ]


def _microstructure_summary_rows(microstructure):
    if not microstructure:
        return []
    rows = []
    for label, comp in [
        ("Raw OOF CLOB overlay rows", microstructure.get("aggregate") or {}),
        ("Taxonomy-gated overlay rows", (microstructure.get("gated") or {}).get("aggregate") or {}),
    ]:
        if not comp:
            continue
        rows.append([
            label,
            comp.get("n", 0),
            fmt_num(comp.get("micro_brier")),
            fmt_num(comp.get("candidate_brier")),
            fmt_num(comp.get("current_brier")),
            fmt_num(comp.get("market_brier")),
            _fmt_delta(comp.get("delta_vs_candidate")),
            _fmt_delta(comp.get("delta_vs_current")),
            _fmt_delta(comp.get("delta_vs_market")),
            fmt_signed(comp.get("micro_skill"), 3),
            fmt_pct(comp.get("base_rate")),
        ])
    return rows


def _microstructure_group_rows(items):
    return [
        [
            str(item.get("group")) if item.get("group") not in (None, "") else "-",
            item.get("n", 0),
            fmt_num(item.get("micro_brier")),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            _fmt_delta(item.get("delta_vs_candidate")),
            _fmt_delta(item.get("delta_vs_current")),
            _fmt_delta(item.get("delta_vs_market")),
            fmt_signed(item.get("micro_skill"), 3),
            fmt_pct(item.get("base_rate")),
        ]
        for item in items
    ]


def _microstructure_slice_markdown(title, items):
    lines = ["", f"### {title}", ""]
    lines += markdown_table(
        ["Group", "Rows", "Micro Brier", "Base Candidate Brier", "Current Brier",
         "Market Brier", "Delta vs Base", "Delta vs Current", "Delta vs Market",
         "Micro Skill", "Base Rate"],
        _microstructure_group_rows(items),
    )
    return lines


def _microstructure_gate_rows(gate):
    rows = []
    for decision in (gate or {}).get("decisions") or []:
        rows.append([
            decision.get("taxonomy") or "-",
            "ALLOW" if decision.get("allowed") else "BASE",
            decision.get("rows", 0),
            fmt_num(decision.get("micro_brier")),
            fmt_num(decision.get("candidate_brier")),
            fmt_num(decision.get("market_brier")),
            _fmt_delta(decision.get("delta_vs_candidate")),
            _fmt_delta(decision.get("delta_vs_market")),
            decision.get("reason") or "-",
        ])
    return rows


def _bridge_summary_rows(bridge):
    comp = (bridge or {}).get("aggregate") or {}
    if not comp:
        return []
    return [[
        "Conservative bridge rows",
        comp.get("n", 0),
        fmt_num(comp.get("bridge_brier")),
        fmt_num(comp.get("candidate_brier")),
        fmt_num(comp.get("current_brier")),
        fmt_num(comp.get("market_brier")),
        _fmt_delta(comp.get("delta_vs_candidate")),
        _fmt_delta(comp.get("delta_vs_current")),
        _fmt_delta(comp.get("delta_vs_market")),
        fmt_signed(comp.get("bridge_skill"), 3),
        fmt_pct(comp.get("base_rate")),
    ]]


def _bridge_group_rows(items):
    return [
        [
            str(item.get("group")) if item.get("group") not in (None, "") else "-",
            item.get("n", 0),
            fmt_num(item.get("bridge_brier")),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            _fmt_delta(item.get("delta_vs_candidate")),
            _fmt_delta(item.get("delta_vs_current")),
            _fmt_delta(item.get("delta_vs_market")),
            fmt_signed(item.get("bridge_skill"), 3),
            fmt_pct(item.get("base_rate")),
        ]
        for item in items
    ]


def _bridge_slice_markdown(title, items):
    lines = ["", f"### {title}", ""]
    lines += markdown_table(
        ["Group", "Rows", "Bridge Brier", "Base Candidate Brier", "Current Brier",
         "Market Brier", "Delta vs Base", "Delta vs Current", "Delta vs Market",
         "Bridge Skill", "Base Rate"],
        _bridge_group_rows(items),
    )
    return lines


def _source_state_summary_rows(source_state):
    gate = (source_state or {}).get("gate") or {}
    rows = []
    for label, comp in [
        ("Aggregate paired rows", gate.get("aggregate") or {}),
        ("Daily-first equal-day average", gate.get("daily_first") or {}),
        ("All-fresh rows", gate.get("all_fresh") or {}),
        ("Degraded-source rows", gate.get("degraded_source") or {}),
    ]:
        if not comp:
            continue
        rows.append([
            label,
            comp.get("n_days", "-"),
            comp.get("n", 0),
            fmt_num(comp.get("candidate_brier")),
            fmt_num(comp.get("current_brier")),
            fmt_num(comp.get("market_brier")),
            _fmt_delta(comp.get("delta_vs_current")),
            _fmt_delta(comp.get("delta_vs_market")),
            fmt_signed(comp.get("candidate_skill"), 3),
            fmt_pct(comp.get("base_rate")),
        ])
    return rows


def _source_state_group_rows(items):
    return [
        [
            str(item.get("group")) if item.get("group") not in (None, "") else "-",
            item.get("n", 0),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            _fmt_delta(item.get("delta_vs_current")),
            _fmt_delta(item.get("delta_vs_market")),
            fmt_signed(item.get("candidate_skill"), 3),
            fmt_pct(item.get("base_rate")),
        ]
        for item in items
    ]


def _source_state_slice_markdown(title, items):
    lines = ["", f"### {title}", ""]
    lines += markdown_table(
        ["Group", "Rows", "Dynamic Source Brier", "Current Brier",
         "Market Brier", "Delta vs Current", "Delta vs Market",
         "Dynamic Source Skill", "Base Rate"],
        _source_state_group_rows(items),
    )
    return lines


def _market_list(rows, verdict):
    return ", ".join(row["market_id"] for row in rows if row["verdict"] == verdict) or "-"


def _family_scope_label(report):
    artifact = report.get("artifact") or {}
    coverage = report.get("coverage") or {}
    family_unit = artifact.get("family_unit") or coverage.get("family_unit") or "F"
    if str(family_unit).lower() == "all":
        return "All market rows"
    return f"{family_unit}-family rows"


def _excluded_scope_label(report):
    artifact = report.get("artifact") or {}
    coverage = report.get("coverage") or {}
    family_unit = artifact.get("family_unit") or coverage.get("family_unit") or "F"
    if str(family_unit).lower() == "all":
        return "Excluded non-market rows"
    return f"Excluded non-{family_unit} rows"


def _comparison_summary_rows(report):
    rows = []
    for label, comp in [
        (_family_scope_label(report), report.get("aggregate")),
        ("Daily-first equal-day average", report.get("daily_first")),
    ]:
        if not comp:
            continue
        rows.append([
            label,
            comp.get("n_days", "-"),
            comp.get("n", 0),
            fmt_num(comp.get("candidate_brier")),
            fmt_num(comp.get("current_brier")),
            fmt_num(comp.get("recorded_brier")),
            fmt_num(comp.get("market_brier")),
            _fmt_delta(comp.get("delta_vs_current")),
            _fmt_delta(comp.get("delta_vs_market")),
            fmt_signed(comp.get("candidate_skill"), 3),
            fmt_pct(comp.get("base_rate")),
        ])
    return rows


def _sidecar_market_rows(items):
    return [
        [
            row.get("market_id") or "-",
            row.get("days", 0),
            row.get("training_ready_days", 0),
            row.get("explanation_ready_days", 0),
            row.get("market_aware_ready_days", 0),
            row.get("variant_ready_days", 0),
            row.get("latest_target_date") or "-",
        ]
        for row in items
    ]


def _sidecar_exclusion_rows(items):
    rows = []
    for item in items:
        commands = item.get("backfill_commands") or []
        rows.append([
            item.get("market_id") or "-",
            item.get("target_date") or "-",
            item.get("primary_label") or "-",
            "; ".join(item.get("promotion_exclusion_reasons") or []) or "-",
            "; ".join(item.get("market_aware_exclusion_reasons") or []) or "-",
            ", ".join(command.get("artifact") or "unknown" for command in commands) or "-",
        ])
    return rows


def _blocked_validation_rows(blocked_validation):
    blocked_validation = blocked_validation or {}
    split_audit = blocked_validation.get("split_audit") or {}
    daily_first = blocked_validation.get("daily_first") or {}
    return [
        ["Verdict", blocked_validation.get("verdict") or "-"],
        ["Required split", blocked_validation.get("split_mode") or "-"],
        ["Daily-first days", daily_first.get("n_days", 0)],
        ["Daily-first rows", daily_first.get("n", 0)],
        ["Leakage audit", "PASS" if split_audit.get("ok") else "FAIL"],
        ["Audited splits", split_audit.get("split_count", 0)],
        ["Leak count", split_audit.get("leak_count", 0)],
        ["Reasons", "; ".join(blocked_validation.get("reasons") or []) or "-"],
    ]


def _blocked_split_rows(blocked_validation):
    split_audit = (blocked_validation or {}).get("split_audit") or {}
    return [
        [
            row.get("mode"),
            row.get("partition_key") or "-",
            row.get("split_count", 0),
            row.get("train_rows_min", 0),
            row.get("validation_rows_min", 0),
            row.get("validation_rows_max", 0),
            ", ".join(row.get("held_out_dates_sample") or []) or "-",
        ]
        for row in split_audit.get("split_modes") or []
    ]


def _slice_markdown(title, items):
    lines = ["", f"### {title}", ""]
    lines += markdown_table(
        ["Group", "Rows", "Candidate Brier", "Current Brier", "Market Brier",
         "Delta vs Current", "Delta vs Market", "Candidate Skill", "Base Rate"],
        _group_table_rows(items),
    )
    return lines


def _exact_winner_scope_rows(items):
    rows = []
    for item in items:
        exact = item.get("exact_winner") or {}
        rows.append([
            item.get("slice") or item.get("group") or "-",
            item.get("n", 0),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            _fmt_delta(item.get("delta_vs_current")),
            _fmt_delta(item.get("delta_vs_market")),
            fmt_num(item.get("candidate_ece")),
            fmt_num(item.get("current_ece")),
            fmt_num(item.get("market_ece")),
            exact.get("winner_rows", 0),
            fmt_num(exact.get("candidate_mean_probability")),
            fmt_num(exact.get("current_mean_probability")),
            fmt_num(exact.get("market_mean_probability")),
        ])
    return rows


def _exact_winner_day_rows(items):
    return [
        [
            item.get("group") or "-",
            item.get("n", 0),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            _fmt_delta(item.get("delta_vs_current")),
            _fmt_delta(item.get("delta_vs_market")),
            fmt_num(item.get("candidate_ece")),
            fmt_pct(item.get("base_rate")),
        ]
        for item in items
    ]


def write_report(report, out_path, min_free_bytes=0):
    artifact = report.get("artifact") or {}
    density_postprocess = artifact.get("density_postprocess") or {}
    corpus = report.get("corpus") or {}
    coverage = report.get("coverage") or {}
    diagnostics = report.get("diagnostics") or {}
    title = (
        "Pooled All-Market Candidate Replay"
        if str(artifact.get("family_unit") or "").lower() == "all"
        else "Pooled F-Family Candidate Replay"
    )
    lines = [
        f"# {title}",
        "",
        f"Generated: {report['generated_at']}",
        f"Validation verdict: **{report['verdict']}**",
        f"Market-only verdict: **{report.get('candidate_market_verdict')}**",
        f"Cutover decision: **{report['cutover_decision']}**",
        "",
        "> Candidate features are rebuilt from pinned `replay_inputs.jsonl` with",
        "> the current extractor. Archived `features_long.csv` vectors are not used",
        "> for candidate scoring, because older F-market tapes can carry stale",
        "> feature schema/unit names.",
        "",
        "## Artifact",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Path", artifact.get("path") or "-"],
            ["Schema", artifact.get("schema_version") or "-"],
            ["Feature schema", artifact.get("feature_schema_version") or "-"],
            ["Family unit", artifact.get("family_unit") or "-"],
            ["Prediction mode", artifact.get("prediction_mode") or "-"],
            ["Objective", artifact.get("objective") or "-"],
            ["Feature subset", artifact.get("feature_subset") or "-"],
            ["Trained at", artifact.get("trained_at") or "-"],
            ["Support", f"{artifact.get('support_min')}-{artifact.get('support_max')}"],
            ["Hour models", ", ".join(str(hour) for hour in artifact.get("hour_models") or []) or "-"],
            ["Adjacent calibration contexts", artifact.get("adjacent_calibration_contexts") or 0],
            ["Density postprocess", density_postprocess.get("policy_id") or "-"],
            ["Density postprocess enabled", bool(density_postprocess.get("enabled"))],
            ["Density postprocess rows", density_postprocess.get("calibration_rows", 0)],
            ["Density postprocess Brier", (
                f"{fmt_num(density_postprocess.get('baseline_market_band_brier'))} -> "
                f"{fmt_num(density_postprocess.get('selected_market_band_brier'))}"
            )],
            ["Density forecast-relative enabled", bool(density_postprocess.get("forecast_relative_calibration_enabled"))],
            ["Density forecast-relative contexts", density_postprocess.get("forecast_relative_contexts", 0)],
            ["Density forecast-relative strength", fmt_num(density_postprocess.get("forecast_relative_strength"))],
            ["Current blend default alpha", fmt_num(artifact.get("current_blend_default_alpha"))],
            [
                "Current blend market alpha",
                json.dumps(artifact.get("current_blend_market_alpha") or {}, sort_keys=True),
            ],
            [
                "Current blend source-freshness default alpha",
                fmt_num(artifact.get("current_blend_source_freshness_default_alpha")),
            ],
            [
                "Current blend source-freshness alpha",
                json.dumps(artifact.get("current_blend_source_freshness_alpha") or {}, sort_keys=True),
            ],
            [
                "Current blend context alpha",
                json.dumps(artifact.get("current_blend_context_alpha") or [], sort_keys=True),
            ],
            ["Market bias calibration enabled", bool(artifact.get("market_bias_calibration_enabled"))],
            ["Market bias calibration contexts", artifact.get("market_bias_calibration_contexts") or 0],
            [
                "Market bias holdout Brier",
                (
                    f"{fmt_num(artifact.get('market_bias_baseline_brier'))} -> "
                    f"{fmt_num(artifact.get('market_bias_candidate_brier'))}"
                ),
            ],
            ["Market bias holdout delta", fmt_signed(artifact.get("market_bias_delta_brier"))],
            [
                "Market bias excluded markets",
                ", ".join(artifact.get("market_bias_excluded_markets") or []) or "-",
            ],
            [
                "Market bias allowed source states",
                ", ".join(artifact.get("market_bias_allowed_source_freshness_states") or []) or "-",
            ],
            ["Forecast centering enabled", bool(artifact.get("forecast_centering_enabled"))],
            ["Forecast centering sigma", fmt_num(artifact.get("forecast_centering_sigma"))],
            ["Forecast centering early alpha", fmt_num(artifact.get("forecast_centering_early_alpha"))],
            [
                "Forecast centering alpha by hour",
                json.dumps(artifact.get("forecast_centering_alpha_by_hour") or {}, sort_keys=True),
            ],
        ],
    )
    lines += ["", "## Corpus And Coverage", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Corpus hash", corpus.get("corpus_hash") or "-"],
            ["As of", corpus.get("as_of") or "-"],
            ["Market days", corpus.get("market_day_count") or 0],
            ["Pinned snapshots", corpus.get("snapshot_count") or 0],
            ["Pinned band rows", corpus.get("band_row_count") or 0],
            ["Feature-quality excluded snapshots", corpus.get("feature_quality_excluded_snapshot_count") or 0],
            ["Feature-quality excluded band rows", corpus.get("feature_quality_excluded_band_row_count") or 0],
            ["Replay rows", coverage.get("total_replay_rows", 0)],
            [_family_scope_label(report), coverage.get("family_rows", 0)],
            ["Candidate-scored rows", coverage.get("candidate_rows", 0)],
            [_excluded_scope_label(report), coverage.get("excluded_non_family_rows", 0)],
            ["Missing candidate rows", coverage.get("missing_candidate_rows", 0)],
            ["Candidate snapshots", diagnostics.get("candidate_snapshots", 0)],
            ["Predicted snapshots", diagnostics.get("predicted_snapshots", 0)],
            ["Source-freshness snapshots", diagnostics.get("source_freshness_snapshots", 0)],
            ["CLOB feature folders", diagnostics.get("clob_feature_folders", 0)],
            ["CLOB feature rows", diagnostics.get("clob_feature_rows", 0)],
            ["CLOB available rows", diagnostics.get("clob_feature_available_rows", 0)],
        ],
    )
    sidecar = report.get("sidecar_eligibility") or {}
    feature_quality = sidecar.get("feature_quality_quarantine") or {}
    lines += [
        "",
        "## Snapshot Sidecar Eligibility",
        "",
        (
            "These counts separate fully explainable candidate evidence from "
            "score-only or evaluation-only legacy folders before replay metrics."
        ),
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Audit status", sidecar.get("status") or "missing"],
            ["Audit JSON", sidecar.get("source_path") or "-"],
            ["Candidate variant", sidecar.get("candidate_variant_id") or "-"],
            ["Candidate family", sidecar.get("candidate_variant_family") or "-"],
            ["Snapshot folders", sidecar.get("snapshot_folder_count", 0)],
            ["Primary labels", _count_summary(sidecar.get("primary_label_counts"))],
            ["Readiness labels", _count_summary(sidecar.get("readiness_label_counts"))],
            ["Missing artifacts", _count_summary(sidecar.get("missing_artifact_counts"))],
            ["Non-reconstructable gaps", _count_summary(sidecar.get("non_reconstructable_gap_counts"))],
            ["Backfill commands", _count_summary(sidecar.get("backfill_command_counts"))],
            ["Backfill candidate folders", sidecar.get("backfill_candidate_folder_count", 0)],
            ["Active-day sidecar regressions", sidecar.get("active_day_sidecar_regression_count", 0)],
            ["Feature-quality quarantined rows", feature_quality.get("quarantine_row_count", 0)],
            ["Feature-quality training exclusions", feature_quality.get("training_excluded_row_count", 0)],
            ["Feature-quality backfill candidates", feature_quality.get("backfill_candidate_row_count", 0)],
            ["Feature-quality reasons", _count_summary(feature_quality.get("reason_counts"))],
        ],
    )
    if sidecar.get("by_market"):
        lines += ["", "### Sidecar Mix By Market", ""]
        lines += markdown_table(
            ["Market", "Days", "Training Ready", "Explanation Ready", "Market Aware", "Variant Ready", "Latest Date"],
            _sidecar_market_rows(sidecar.get("by_market") or []),
        )
    if sidecar.get("promotion_exclusion_sample"):
        lines += ["", "### Promotion And Market-Aware Exclusions", ""]
        lines += markdown_table(
            ["Market", "Date", "Primary Label", "Promotion Exclusions", "Market-Aware Exclusions", "Backfills"],
            _sidecar_exclusion_rows(sidecar.get("promotion_exclusion_sample") or []),
        )
    gate = report.get("replay_gate") or {}
    lines += ["", "## Global Replay Gate", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [
            ["Corpus pin", "PASS" if gate.get("corpus_ok") else "FAIL", gate.get("corpus_message") or "-"],
            ["Replay fidelity", "PASS" if gate.get("fidelity_ok") else "FAIL", gate.get("fidelity_message") or "-"],
        ],
    )
    blocked_validation = report.get("blocked_validation") or {}
    lines += ["", "## Blocked Validation Gate", ""]
    lines += markdown_table(
        ["Field", "Value"],
        _blocked_validation_rows(blocked_validation),
    )
    lines += ["", "### Split Audit", ""]
    lines += markdown_table(
        ["Mode", "Partition", "Splits", "Min Train Rows", "Min Validation Rows", "Max Validation Rows", "Held-Out Dates Sample"],
        _blocked_split_rows(blocked_validation),
    )
    lines += ["", "## Aggregate Replay", ""]
    lines += markdown_table(
        ["Scope", "Days", "Rows", "Candidate Brier", "Current Brier",
         "Recorded Brier", "Market Brier", "Delta vs Current",
         "Delta vs Market", "Candidate Skill", "Base Rate"],
        _comparison_summary_rows(report),
    )
    candidate_shadow = report.get("candidate_shadow_variants")
    if candidate_shadow:
        lines += ["", "## Candidate Shadow Variant", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Variant", candidate_shadow.get("variant_id") or "-"],
                ["Family", candidate_shadow.get("variant_family") or "-"],
                ["Uses market features", candidate_shadow.get("uses_market_features")],
                ["Control", candidate_shadow.get("is_control")],
                ["Shadow variant rows", candidate_shadow.get("rows", 0)],
                ["Shadow variant CSV", candidate_shadow.get("path") or "-"],
            ],
        )
    exact_winner = report.get("exact_winner_diagnostics")
    if exact_winner:
        daily = exact_winner.get("daily_first") or {}
        lines += [
            "",
            "## Exact-Winner Catch-Up Diagnostics",
            "",
            "These no-market diagnostics target item 70's failure slices and",
            "the one-above guardrail before any promotion decision.",
            "",
        ]
        lines += markdown_table(
            [
                "Slice", "Rows", "Candidate Brier", "Current Brier", "Market Brier",
                "Delta vs Current", "Delta vs Market", "Candidate ECE",
                "Current ECE", "Market ECE", "Exact Winner Rows",
                "Exact Winner Candidate P", "Exact Winner Current P",
                "Exact Winner Market P",
            ],
            _exact_winner_scope_rows(exact_winner.get("scopes") or []),
        )
        lines += ["", "### Daily-First Paired Brier", ""]
        lines += markdown_table(
            ["Scope", "Days", "Rows", "Candidate Brier", "Current Brier",
             "Market Brier", "Delta vs Current", "Delta vs Market"],
            [[
                "Daily-first equal-day average",
                daily.get("n_days", "-"),
                daily.get("n", 0),
                fmt_num(daily.get("candidate_brier")),
                fmt_num(daily.get("current_brier")),
                fmt_num(daily.get("market_brier")),
                _fmt_delta(daily.get("delta_vs_current")),
                _fmt_delta(daily.get("delta_vs_market")),
            ]] if daily else [],
        )
        lines += ["", "### Worst Daily Current Regressions", ""]
        lines += markdown_table(
            ["Market Day", "Rows", "Candidate Brier", "Current Brier",
             "Market Brier", "Delta vs Current", "Delta vs Market",
             "Candidate ECE", "Base Rate"],
            _exact_winner_day_rows(exact_winner.get("worst_daily_current_regressions") or []),
        )
    source_state = report.get("source_state_ablation")
    if source_state and source_state.get("enabled"):
        gate = source_state.get("gate") or {}
        shadow = source_state.get("shadow_variants") or {}
        feature_groups = source_state.get("feature_groups") or {}
        lines += [
            "",
            "## Source-State Feature Ablation",
            "",
            "This non-serving item 105 section treats current serving as the",
            "no-source-state control and the candidate artifact as the dynamic",
            "source-state variant. Promotion remains blocked unless paired",
            "all-fresh and degraded-source slices clear the replay gate.",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Schema", source_state.get("schema_version") or "-"],
                ["Gate verdict", gate.get("verdict") or "-"],
                ["Reasons", "; ".join(gate.get("reasons") or []) or "-"],
                ["Feature groups", json.dumps(feature_groups, sort_keys=True)],
                ["Shadow variant rows", shadow.get("rows", 0)],
                ["Shadow variant CSV", shadow.get("path") or "-"],
                ["Variant IDs", ", ".join(shadow.get("variant_ids") or []) or "-"],
            ],
        )
        lines += ["", "### Gate Scores", ""]
        lines += markdown_table(
            ["Scope", "Days", "Rows", "Dynamic Source Brier", "Current Brier",
             "Market Brier", "Delta vs Current", "Delta vs Market",
             "Dynamic Source Skill", "Base Rate"],
            _source_state_summary_rows(source_state),
        )
        lines += _source_state_slice_markdown(
            "By Source Degradation",
            source_state.get("by_degradation") or [],
        )
        lines += _source_state_slice_markdown(
            "By Source Freshness",
            source_state.get("by_source_freshness") or [],
        )
    microstructure = report.get("microstructure")
    if microstructure:
        micro_diag = microstructure.get("diagnostics") or {}
        casebook = micro_diag.get("casebook") or {}
        claim_lanes = micro_diag.get("claim_lanes") or {}
        quote_lane = claim_lanes.get("market_informed_quote_risk") or {}
        weather_lane = claim_lanes.get("weather_only_core_model") or {}
        gate = microstructure.get("gate") or {}
        lines += [
            "",
            "## Microstructure Shadow Overlay",
            "",
            "This is a non-serving, out-of-fold CLOB overlay scored behind the",
            "promotion gauntlet. Base candidate promotion decisions above are",
            "unchanged; this section only measures whether book features add",
            "settlement-scored value on the pinned rows and casebook slices.",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Schema", microstructure.get("schema_version") or "-"],
                ["Claim lane", "market_informed_quote_risk"],
                ["Weather-only core claim rows", weather_lane.get("rows", 0)],
                ["Market-informed quote-risk rows", quote_lane.get("rows", 0)],
                ["Counts toward weather-only promotion", quote_lane.get("counts_toward_weather_model_promotion", False)],
                ["Quote-risk eligible rows", quote_lane.get("quote_risk_eligible_rows", 0)],
                ["Eligible CLOB rows", micro_diag.get("eligible_rows", 0)],
                ["OOF predicted rows", micro_diag.get("predicted_rows", 0)],
                ["OOF folds", micro_diag.get("fold_count", 0)],
                ["Skipped folds", len(micro_diag.get("skipped_folds") or [])],
                ["Casebook", casebook.get("path") or "-"],
                ["Casebook refs", casebook.get("refs", 0)],
                ["Casebook-matched rows", micro_diag.get("casebook_matched_rows", 0)],
                ["Gate policy", gate.get("policy") or "-"],
                ["Gate allowed taxonomies", ", ".join(gate.get("allowed_taxonomies") or []) or "-"],
                ["Feature coverage threshold", "clob_feature_available == 1 and overlay probability present"],
                ["Spread/liquidity thresholds", "diagnostic features only; taxonomy gate controls quote-risk eligibility"],
                ["Gated overlay rows", micro_diag.get("gated_overlay_rows", 0)],
                ["Gated base-fallback rows", micro_diag.get("gated_base_rows", 0)],
                ["Artifact", micro_diag.get("artifact_path") or "-"],
                ["Artifact train rows", micro_diag.get("artifact_train_rows") or 0],
            ],
        )
        lines += ["", "### Aggregate", ""]
        lines += markdown_table(
            ["Scope", "Rows", "Micro Brier", "Base Candidate Brier", "Current Brier",
            "Market Brier", "Delta vs Base", "Delta vs Current", "Delta vs Market",
             "Micro Skill", "Base Rate"],
            _microstructure_summary_rows(microstructure),
        )
        lines += ["", "### Taxonomy Gate", ""]
        lines += markdown_table(
            ["Taxonomy", "Action", "Rows", "Micro Brier", "Base Brier",
             "Market Brier", "Delta Base", "Delta Market", "Reason"],
            _microstructure_gate_rows(microstructure.get("gate") or {}),
        )
        lines += _microstructure_slice_markdown(
            "Raw Target Casebook Slices",
            microstructure.get("target_slices") or [],
        )
        lines += _microstructure_slice_markdown(
            "Gated Target Casebook Slices",
            ((microstructure.get("gated") or {}).get("target_slices")) or [],
        )
        lines += _microstructure_slice_markdown(
            "By Casebook Taxonomy",
            microstructure.get("by_taxonomy") or [],
        )
    bridge = report.get("conservative_bridge")
    if bridge:
        bridge_diag = bridge.get("diagnostics") or {}
        bridge_policy = bridge.get("policy") or {}
        lines += [
            "",
            "## Conservative Bridge Shadow Policy",
            "",
            "This is a non-serving per-market blend of the pooled candidate and",
            "current serving probabilities. It is scored as an operational policy",
            "variant and does not replace the model diagnostics above.",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Schema", bridge.get("schema_version") or "-"],
                ["Policy", bridge_policy.get("policy_id") or "-"],
                ["Alpha schedule", json.dumps(bridge_policy.get("alpha_by_market") or {}, sort_keys=True)],
                ["Shadow variant rows", bridge_diag.get("shadow_variant_rows", 0)],
                ["Shadow variant CSV", bridge_diag.get("shadow_variant_path") or "-"],
            ],
        )
        lines += ["", "### Aggregate", ""]
        lines += markdown_table(
            ["Scope", "Rows", "Bridge Brier", "Base Candidate Brier", "Current Brier",
             "Market Brier", "Delta vs Base", "Delta vs Current", "Delta vs Market",
             "Bridge Skill", "Base Rate"],
            _bridge_summary_rows(bridge),
        )
        lines += _bridge_slice_markdown("Bridge By Market", bridge.get("by_market") or [])
    lines += [
        "",
        "## Per-Market Action",
        "",
    ]
    lines += markdown_table(
        ["Action", "Markets"],
        [
            ["Candidate cutover ready", _market_list(report["market_rows"], "PASS")],
            ["Continue shadow", _market_list(report["market_rows"], "SHADOW")],
            ["Blocked", _market_list(report["market_rows"], "BLOCK")],
        ],
    )
    lines += ["", "### Market Details", ""]
    lines += markdown_table(
        ["Market", "Days", "Snaps", "Rows", "Candidate Brier", "Current Brier",
         "Market Brier", "Delta vs Current", "Delta vs Market", "Candidate Skill",
         "Trust", "Blocked Validation", "Verdict", "Reason"],
        _candidate_table_rows(report["market_rows"]),
    )
    lines += ["", "## Slices", ""]
    lines += _slice_markdown("By Market", report.get("by_market") or [])
    lines += _slice_markdown("By Candidate Cutoff Hour", report.get("by_hour") or [])
    lines += _slice_markdown("By Cutoff Regime", report.get("by_cutoff_regime") or [])
    lines += _slice_markdown("By Band Type", report.get("by_bin_type") or [])
    lines += _slice_markdown("By Settlement Distance", report.get("by_settlement_distance") or [])
    lines += _slice_markdown("By Source Freshness", report.get("by_source_freshness") or [])
    if report.get("by_forecast_source_count"):
        lines += _slice_markdown("By Forecast Source Count", report.get("by_forecast_source_count") or [])
    if report.get("by_forecast_disagreement"):
        lines += _slice_markdown("By Forecast Disagreement", report.get("by_forecast_disagreement") or [])
    if report.get("by_forecast_bucket_pressure"):
        lines += _slice_markdown("By Forecast-Relative Bucket Pressure", report.get("by_forecast_bucket_pressure") or [])
    if report.get("by_current_max_boundary"):
        lines += _slice_markdown("By Current-Max Boundary", report.get("by_current_max_boundary") or [])
    if report.get("by_marine_breeze_slice"):
        lines += _slice_markdown("By Marine Breeze Slice", report.get("by_marine_breeze_slice") or [])

    guardrails = report.get("forecast_profile_guardrails") or {}
    guardrail_rows = guardrails.get("rows") or []
    if guardrail_rows:
        lines += ["", "## Forecast-Profile High-Disagreement Guardrails", ""]
        lines += markdown_table(
            ["Market", "Status", "Rows", "Candidate Brier", "Current Brier", "Market Brier", "Delta Current", "Delta Market", "Reasons"],
            [
                [
                    row.get("market_id"),
                    row.get("status"),
                    (row.get("comparison") or {}).get("n", 0),
                    fmt_num((row.get("comparison") or {}).get("candidate_brier")),
                    fmt_num((row.get("comparison") or {}).get("current_brier")),
                    fmt_num((row.get("comparison") or {}).get("market_brier")),
                    _fmt_delta((row.get("comparison") or {}).get("delta_vs_current")),
                    _fmt_delta((row.get("comparison") or {}).get("delta_vs_market")),
                    "; ".join(row.get("reasons") or []) or "-",
                ]
                for row in guardrail_rows
            ],
        )

    warnings = (report.get("replay_summary") or {}).get("corpus_warnings") or []
    if warnings:
        lines += ["", "## Corpus Warnings", ""]
        lines += [f"- {warning}" for warning in warnings[:50]]
        if len(warnings) > 50:
            lines.append(f"- ... {len(warnings) - 50} more")

    errors = diagnostics.get("feature_errors") or []
    if errors:
        lines += ["", "## Feature Rebuild Errors", ""]
        lines += [
            f"- {item.get('market_id')} {item.get('snapshot_id')}: {item.get('error')}"
            for item in errors
        ]

    text = "\n".join(lines) + "\n"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_artifact_disk_headroom(
        out_path,
        estimated_bytes=len(text.encode("utf-8")),
        min_free_bytes=min_free_bytes,
        context="pooled candidate Markdown report export",
    )
    out_path.write_text(text, encoding="utf-8")
    return out_path
