"""Markdown rendering for pooled candidate replay reports."""

from __future__ import annotations

import json
from pathlib import Path

from weather.reporting.formatting import fmt_num, fmt_pct, fmt_signed, markdown_table

def _fmt_delta(value):
    return fmt_signed(value, 4)


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


def write_report(report, out_path):
    artifact = report.get("artifact") or {}
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
            ["Trained at", artifact.get("trained_at") or "-"],
            ["Support", f"{artifact.get('support_min')}-{artifact.get('support_max')}"],
            ["Hour models", ", ".join(str(hour) for hour in artifact.get("hour_models") or []) or "-"],
            ["Adjacent calibration contexts", artifact.get("adjacent_calibration_contexts") or 0],
            ["Current blend default alpha", fmt_num(artifact.get("current_blend_default_alpha"))],
            [
                "Current blend market alpha",
                json.dumps(artifact.get("current_blend_market_alpha") or {}, sort_keys=True),
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
                ["Eligible CLOB rows", micro_diag.get("eligible_rows", 0)],
                ["OOF predicted rows", micro_diag.get("predicted_rows", 0)],
                ["OOF folds", micro_diag.get("fold_count", 0)],
                ["Skipped folds", len(micro_diag.get("skipped_folds") or [])],
                ["Casebook", casebook.get("path") or "-"],
                ["Casebook refs", casebook.get("refs", 0)],
                ["Casebook-matched rows", micro_diag.get("casebook_matched_rows", 0)],
                ["Gate allowed taxonomies", ", ".join((microstructure.get("gate") or {}).get("allowed_taxonomies") or []) or "-"],
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
    lines += _slice_markdown("By Band Type", report.get("by_bin_type") or [])
    lines += _slice_markdown("By Settlement Distance", report.get("by_settlement_distance") or [])
    lines += _slice_markdown("By Source Freshness", report.get("by_source_freshness") or [])

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

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
