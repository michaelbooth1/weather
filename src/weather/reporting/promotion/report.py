"""Implementation slice extracted from src/weather/reporting/promotion_refresh.py."""

from weather.reporting.promotion.gap_analysis import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def write_report(path, payload, min_free_bytes=0):
    path = Path(path)
    corpus = payload.get("corpus") or {}
    candidate = payload.get("candidate") or {}
    candidate_agg = candidate.get("aggregate") or {}
    replay_gate = candidate.get("replay_gate") or {}
    decisions = payload.get("decisions") or {}
    allowlist = payload.get("promotion_allowlist") or {}
    serving = payload.get("serving_gauntlet")
    readiness = payload.get("readiness") or {}

    lines = [
        f"# {_family_title(payload.get('family_unit'))} Promotion Refresh",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Family unit: `{payload.get('family_unit')}`",
        "",
        "## Decision Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Candidate verdict", candidate.get("verdict") or "-"],
            ["Candidate market-only verdict", candidate.get("candidate_market_verdict") or "-"],
            ["Cutover decision", candidate.get("cutover_decision") or "-"],
            ["Blocked validation", (candidate.get("blocked_validation") or {}).get("verdict") or "-"],
            ["Readiness status", readiness.get("status") or "-"],
            ["Promotion allowlist", allowlist.get("path") or "-"],
            ["Promote", ", ".join(decisions.get("promote_markets") or []) or "-"],
            ["Shadow", ", ".join(decisions.get("shadow_markets") or []) or "-"],
            ["Blocked", ", ".join(decisions.get("blocked_markets") or []) or "-"],
        ],
    )
    if allowlist:
        lines += [
            "",
            "## F-Family Promotion Allowlist",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Schema", allowlist.get("schema_version") or "-"],
                ["Candidate id", allowlist.get("candidate_id") or "-"],
                ["Generated", allowlist.get("generated_at_utc") or "-"],
                ["Policy", (allowlist.get("policy") or {}).get("permission_gate") or "-"],
            ],
        )
        lines += markdown_table(
            [
                "Market",
                "Action",
                "Serving",
                "Permission",
                "Candidate Brier",
                "Current Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Blocker/Reason",
            ],
            [
                [
                    row.get("market_id"),
                    row.get("action"),
                    row.get("serving_behavior"),
                    row.get("permission_behavior"),
                    fmt_num(row.get("candidate_brier")),
                    fmt_num(row.get("current_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_current"), 4),
                    fmt_signed(row.get("delta_vs_market"), 4),
                    row.get("blocker_reason") or row.get("reason") or "-",
                ]
                for row in allowlist.get("markets") or []
            ],
        )
    source_missingness = payload.get("source_missingness_location_gate") or {}
    if source_missingness:
        summary = source_missingness.get("summary") or {}
        lines += [
            "",
            "## Market Source/Missingness Location Gate",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", source_missingness.get("status") or "-"],
                ["Candidate shadow export", source_missingness.get("candidate_shadow_variant_path") or "-"],
                ["Market tolerance", fmt_num(source_missingness.get("market_tolerance"), 4)],
                ["Minimum rows", source_missingness.get("min_rows")],
                ["Bottom markets", ", ".join(source_missingness.get("bottom_markets") or []) or "-"],
                ["Decoded missingness hashes", summary.get("decoded_missingness_hash_count", 0)],
                ["Blockers", summary.get("blocker_count", 0)],
            ],
        )
        blockers = source_missingness.get("blockers") or []
        if blockers:
            lines += markdown_table(
                ["Category", "Market", "Detail"],
                [
                    [row.get("category"), row.get("market_id") or "-", row.get("detail")]
                    for row in blockers[:12]
                ],
            )
        source_rows = [
            row for row in source_missingness.get("market_source_freshness") or []
            if row.get("market_id") in set(source_missingness.get("bottom_markets") or [])
        ][:12]
        if source_rows:
            lines += ["", "### Bottom-Market Source Freshness Slices", ""]
            lines += markdown_table(
                ["Market", "Source State", "Status", "Rows", "Candidate Brier", "Market Brier", "Delta Market"],
                [
                    [
                        row.get("market_id"),
                        row.get("source_freshness_state"),
                        row.get("status"),
                        row.get("n"),
                        fmt_num(row.get("candidate_brier"), 4),
                        fmt_num(row.get("market_brier"), 4),
                        fmt_signed(row.get("delta_vs_market"), 4),
                    ]
                    for row in source_rows
                ],
            )
        count_rows = [
            row for row in source_missingness.get("market_forecast_source_count") or []
            if row.get("market_id") in set(source_missingness.get("bottom_markets") or [])
        ][:12]
        if count_rows:
            lines += ["", "### Bottom-Market Forecast Source Count Slices", ""]
            lines += markdown_table(
                ["Market", "Source Count", "Status", "Rows", "Candidate Brier", "Market Brier", "Delta Market"],
                [
                    [
                        row.get("market_id"),
                        row.get("forecast_source_count_bucket"),
                        row.get("status"),
                        row.get("n"),
                        fmt_num(row.get("candidate_brier"), 4),
                        fmt_num(row.get("market_brier"), 4),
                        fmt_signed(row.get("delta_vs_market"), 4),
                    ]
                    for row in count_rows
                ],
            )
        missingness_rows = [
            row for row in source_missingness.get("market_feature_missingness") or []
            if row.get("market_id") in set(source_missingness.get("bottom_markets") or [])
        ][:12]
        if missingness_rows:
            lines += ["", "### Bottom-Market Feature Missingness Slices", ""]
            lines += markdown_table(
                ["Market", "Missingness Hash", "Status", "Rows", "Delta Market", "Decoded Missing Features"],
                [
                    [
                        row.get("market_id"),
                        row.get("feature_missingness_hash"),
                        row.get("status"),
                        row.get("n"),
                        fmt_signed(row.get("delta_vs_market"), 4),
                        ", ".join(row.get("missing_features") or []) or "-",
                    ]
                    for row in missingness_rows
                ],
            )
    lines += [
        "",
        "## Promotion Readiness Blockers",
        "",
    ]
    lines += markdown_table(
        ["Category", "Severity", "Detail"],
        _readiness_table_rows(readiness),
    )
    readiness_details = _readiness_market_detail_rows(readiness)
    if readiness_details:
        lines += [
            "",
            "### Shadow/Block Explanation Detail",
            "",
        ]
        lines += markdown_table(
            [
                "Market",
                "Action",
                "Candidate Brier",
                "Current Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Reason",
            ],
            readiness_details,
        )
    runtime_evidence = payload.get("runtime_identity_evidence") or {}
    runtime_segments = ((runtime_evidence.get("snapshots") or {}).get("segments") or [])
    lines += [
        "",
        "## Runtime Identity Evidence",
        "",
        f"Status: **{runtime_evidence.get('status') or '-'}**",
        f"Mixed runtime identity: `{runtime_evidence.get('mixed_runtime_identity')}`",
        f"Runtime identities: `{runtime_evidence.get('runtime_identity_count')}`",
        f"Snapshot rows: `{runtime_evidence.get('snapshot_row_count')}`",
        f"Blocking reason: `{runtime_evidence.get('blocking_reason') or '-'}`",
        f"Reconciliation: `{runtime_evidence.get('reconciliation_status') or '-'}`",
        "",
    ]
    lines += markdown_table(
        ["Commit", "Rows", "Snapshots", "Markets", "Target Dates", "Source Fingerprint"],
        [
            [
                row.get("runtime_git_commit") or row.get("runtime_key"),
                row.get("row_count"),
                row.get("snapshot_count"),
                row.get("market_count"),
                row.get("target_date_count"),
                row.get("runtime_source_fingerprint") or "-",
            ]
            for row in runtime_segments
        ],
    )
    operational_gate_rows = _operational_gate_rows(payload)
    if operational_gate_rows:
        lines += [
            "",
            "## Operational Promotion Gates",
            "",
        ]
        lines += markdown_table(
            ["Gate", "Status", "Detail"],
            operational_gate_rows,
        )
    early_hour_blocker = payload.get("early_hour_promotion_blocker") or {}
    if early_hour_blocker:
        production = early_hour_blocker.get("production_readiness") or {}
        lines += [
            "",
            "## Early-Hour Promotion Blocker",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", early_hour_blocker.get("status") or "-"],
                ["Promotion allowed", early_hour_blocker.get("promotion_allowed")],
                ["Blockers", early_hour_blocker.get("blocker_count", 0)],
                [
                    "Current hourly gate",
                    (early_hour_blocker.get("current_gates") or {}).get("hourly_status") or "-",
                ],
                [
                    "Current 10-minute gate",
                    (early_hour_blocker.get("current_gates") or {}).get("ten_minute_status") or "-",
                ],
                [
                    "Broad replay within market tolerance",
                    (early_hour_blocker.get("broad_replay") or {}).get("within_market_tolerance"),
                ],
                [
                    "Live-forward SLO",
                    (early_hour_blocker.get("production_readiness") or {}).get("live_forward_slo_status") or "-",
                ],
                [
                    "Current-code soak",
                    production.get("current_code_soak_status") or "-",
                ],
                [
                    "Clean active-day countability",
                    production.get("clean_active_day_countability_status") or "-",
                ],
                [
                    "Counts toward early-hour evidence",
                    production.get("counts_toward_early_hour_evidence"),
                ],
                [
                    "Early-hour coverage",
                    (
                        f"{production.get('early_hour_coverage_status') or '-'}; "
                        f"markets={production.get('early_hour_coverage_countable_markets')}; "
                        f"snapshots={production.get('early_hour_coverage_total_snapshots')}"
                    ),
                ],
            ],
        )
        blockers = early_hour_blocker.get("blockers") or []
        if blockers:
            lines += [
                "",
                "### Early-Hour Blocker Detail",
                "",
            ]
            lines += markdown_table(
                ["Category", "Severity", "Detail"],
                [
                    [row.get("category"), row.get("severity"), row.get("detail")]
                    for row in blockers
                ],
            )
    extra_transfer = payload.get("extra_location_transfer") or {}
    if extra_transfer:
        extra_gate = extra_transfer.get("promotion_gate") or {}
        extra_evidence = extra_transfer.get("evidence_accounting") or {}
        lines += [
            "",
            "## No-Market Extra-Location Shadow Lane",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Report", extra_transfer.get("path") or "-"],
                ["Exists", extra_transfer.get("exists")],
                ["Status", extra_transfer.get("status") or "-"],
                ["Gate", extra_gate.get("status") or "-"],
                ["Serving promotion allowed", extra_gate.get("serving_promotion_allowed")],
                ["Target market-days scored", extra_evidence.get("target_market_days_scored", 0)],
                ["Extra location-days", extra_evidence.get("extra_location_days", 0)],
                ["Row multiplier", fmt_num(extra_evidence.get("row_multiplier"))],
                ["Reasons", "; ".join(extra_gate.get("reasons") or []) or "-"],
            ],
        )
    lines += [
        "",
        "## Refresh Artifacts",
        "",
    ]
    lines += markdown_table(
        ["Artifact", "Path / Hash"],
        [
            ["Promotion corpus", f"{corpus.get('path')} / {corpus.get('corpus_hash')}"],
            ["Location trust", (payload.get("trust") or {}).get("path") or "-"],
            ["Candidate JSON", candidate.get("json_path") or "-"],
            ["Candidate report", candidate.get("report_path") or "-"],
            ["Serving gauntlet", (serving or {}).get("report_path") or "skipped"],
            ["Promotion allowlist", allowlist.get("path") or "-"],
            ["Candidate hourly performance", (payload.get("candidate_hourly_performance") or {}).get("path") or "-"],
            ["10-minute performance", (payload.get("ten_minute_performance") or {}).get("path") or "-"],
            ["Candidate 10-minute performance", (payload.get("candidate_ten_minute_performance") or {}).get("path") or "-"],
            ["Source family inventory", (payload.get("source_family_inventory") or {}).get("path") or "-"],
            ["Physical family ratchet", (payload.get("physical_feature_family_ratchet") or {}).get("path") or "-"],
            ["Fleet observability", (payload.get("fleet_observability") or {}).get("path") or "-"],
            ["Settled-day freshness", (payload.get("settled_day_freshness") or {}).get("path") or "-"],
            ["Data-layer audit", (payload.get("data_layer_audit") or {}).get("path") or "-"],
            ["Ingest quality gate", (payload.get("ingest_quality_gate") or {}).get("path") or "-"],
            ["Daily learning", (payload.get("daily_learning") or {}).get("path") or "-"],
            [
                "Per-location artifact quarantine",
                (payload.get("per_location_artifact_quarantine") or {}).get("path") or "-",
            ],
            [
                "Disk headroom",
                (
                    (payload.get("disk_headroom") or {}).get("path")
                    or (payload.get("disk_headroom") or {}).get("status")
                    or "-"
                ),
            ],
        ],
    )
    lines += [
        "",
        "## Corpus",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["As of", corpus.get("as_of") or "-"],
            ["Market days", corpus.get("market_day_count", 0)],
            ["Pinned snapshots", corpus.get("snapshot_count", 0)],
            ["Band rows", corpus.get("band_row_count", 0)],
            ["Identity records", corpus.get("identity_record_count", 0)],
            ["Skipped folders", corpus.get("skipped_count", 0)],
        ],
    )
    lines += [
        "",
        "## Candidate Replay",
        "",
    ]
    candidate_evidence = candidate.get("evidence_accounting") or {}
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Rows", candidate_agg.get("rows", 0)],
            ["Unique observations", candidate_evidence.get("unique_observation_count", candidate_agg.get("rows", 0))],
            ["Snapshots", candidate_evidence.get("snapshot_count", 0)],
            ["Market-days", candidate_evidence.get("market_day_count", 0)],
            ["Row multiplier", fmt_num(candidate_evidence.get("row_multiplier"))],
            ["Blocked validation", (candidate.get("blocked_validation") or {}).get("verdict") or "-"],
            ["Blocked validation split", (candidate.get("blocked_validation") or {}).get("split_mode") or "-"],
            ["Candidate Brier", fmt_num(candidate_agg.get("candidate_brier"))],
            ["Current Brier", fmt_num(candidate_agg.get("current_brier"))],
            ["Recorded Brier", fmt_num(candidate_agg.get("recorded_brier"))],
            ["Market Brier", fmt_num(candidate_agg.get("market_brier"))],
            ["Delta vs current", fmt_signed(candidate_agg.get("delta_vs_current"), 4)],
            ["Delta vs market", fmt_signed(candidate_agg.get("delta_vs_market"), 4)],
        ],
    )
    candidate_artifact = candidate.get("artifact") or {}
    if candidate_artifact.get("feature_subset") == "forecast_profile":
        guardrails = candidate.get("forecast_profile_guardrails") or {}
        contract = candidate_artifact.get("feature_subset_contract") or {}
        lines += [
            "",
            "### Forecast-Profile Calibration Lane",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Subset", candidate_artifact.get("feature_subset")],
                ["Anchor", contract.get("anchor_feature") or "forecast_high"],
                ["Allowed families", ", ".join(contract.get("allowed_feature_families") or []) or "-"],
                ["Blocked high-disagreement markets", ", ".join(guardrails.get("blocked_markets") or []) or "-"],
                ["Promotion blocker", (candidate_artifact.get("forecast_profile_calibration") or {}).get("promotion_blocker") or "-"],
            ],
        )
        if (candidate.get("slices") or {}).get("by_cutoff_regime"):
            lines += ["", "#### Cutoff-Regime Replay", ""]
            lines += markdown_table(
                [
                    "Regime",
                    "Rows",
                    "Candidate Brier",
                    "Current Brier",
                    "Market Brier",
                    "Delta Current",
                    "Delta Market",
                ],
                [
                    [
                        row.get("group") or "-",
                        row.get("n", 0),
                        fmt_num(row.get("candidate_brier")),
                        fmt_num(row.get("current_brier")),
                        fmt_num(row.get("market_brier")),
                        fmt_signed(row.get("delta_vs_current"), 4),
                        fmt_signed(row.get("delta_vs_market"), 4),
                    ]
                    for row in (candidate.get("slices") or {}).get("by_cutoff_regime") or []
                ],
            )
    gap_drivers = _candidate_gap_driver_rows(candidate)
    lines += [
        "",
        "### Candidate Gap Drivers",
        "",
    ]
    lines += markdown_table(
        [
            "Slice",
            "Group",
            "Rows",
            "Candidate/Micro Brier",
            "Market Brier",
            "Delta Current",
            "Delta Market",
            "Excess Brier Rows",
        ],
        _gap_driver_table_rows(gap_drivers),
    )
    gap_owner_rows = payload.get("gap_owner_table") or build_gap_owner_table(gap_drivers, decisions)
    claims = payload.get("model_skill_claims") or model_skill_claims(candidate, gap_owner_rows)
    lines += [
        "",
        "### Model-Skill Claim Lanes",
        "",
    ]
    lines += markdown_table(
        ["Lane", "Core Claim Allowed / Counts", "Quote Gating", "Delta Market", "Reason"],
        _model_skill_claim_rows(claims),
    )
    if gap_owner_rows:
        lines += [
            "",
            "### Gap Owner Experiments",
            "",
        ]
        lines += markdown_table(
            [
                "Slice",
                "Group",
                "Weighted Gap",
                "Affected Markets",
                "Owner",
                "Roadmap",
                "Next Experiment",
                "Artifact",
                "Claim Lane",
                "Core Claim Credit",
                "Clearance Rule",
            ],
            _gap_owner_table_rows(gap_owner_rows),
        )
    market_diagnostics = payload.get("market_skill_diagnostics") or market_skill_diagnostics(candidate, decisions)
    if market_diagnostics:
        lines += [
            "",
            "### Market-Skill Diagnostics",
            "",
        ]
        lines += markdown_table(
            [
                "Market",
                "Action",
                "Candidate Brier",
                "Current Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Next Experiment",
                "Reason",
            ],
            _market_skill_diagnostic_rows(market_diagnostics),
        )
    source_freshness_rows = _candidate_source_freshness_rows(candidate)
    if source_freshness_rows:
        lines += [
            "",
            "### Source Freshness Slice",
            "",
        ]
        lines += markdown_table(
            [
                "Group",
                "Rows",
                "Candidate/Micro Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Excess Brier Rows",
            ],
            _gap_driver_table_rows(source_freshness_rows, include_slice=False),
        )
    else:
        lines += [
            "",
            "Source-freshness gap drivers are not available in the candidate replay rows yet.",
        ]
    micro = candidate.get("microstructure") or {}
    micro_agg = micro.get("aggregate") or {}
    micro_gated_agg = micro.get("gated_aggregate") or {}
    micro_gate = micro.get("gate") or {}
    if micro:
        lines += [
            "",
            "## Item 38 Microstructure Shadow Score",
            "",
        ]
        lines += markdown_table(
            ["Metric", "Value"],
            [
                ["Eligible CLOB rows", micro.get("eligible_rows", 0)],
                ["OOF predicted rows", micro.get("predicted_rows", 0)],
                ["OOF folds", micro.get("fold_count", 0)],
                ["Casebook-matched rows", micro.get("casebook_matched_rows", 0)],
                ["Gate allowed taxonomies", ", ".join(micro_gate.get("allowed_taxonomies") or []) or "-"],
                ["Gated overlay rows", micro.get("gated_overlay_rows", 0)],
                ["Gated base-fallback rows", micro.get("gated_base_rows", 0)],
                ["Artifact", micro.get("artifact_path") or "-"],
            ],
        )
        lines += ["", "### Aggregate", ""]
        lines += markdown_table(
            ["Scope", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market"],
            [
                [
                    "Raw overlay",
                    micro_agg.get("rows", 0),
                    fmt_num(micro_agg.get("micro_brier")),
                    fmt_num(micro_agg.get("candidate_brier")),
                    fmt_num(micro_agg.get("market_brier")),
                    fmt_signed(micro_agg.get("delta_vs_candidate"), 4),
                    fmt_signed(micro_agg.get("delta_vs_market"), 4),
                ],
                [
                    "Taxonomy-gated overlay",
                    micro_gated_agg.get("rows", 0),
                    fmt_num(micro_gated_agg.get("micro_brier")),
                    fmt_num(micro_gated_agg.get("candidate_brier")),
                    fmt_num(micro_gated_agg.get("market_brier")),
                    fmt_signed(micro_gated_agg.get("delta_vs_candidate"), 4),
                    fmt_signed(micro_gated_agg.get("delta_vs_market"), 4),
                ],
            ],
        )
        lines += ["", "### Taxonomy Gate", ""]
        lines += markdown_table(
            ["Taxonomy", "Action", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market", "Reason"],
            [
                [
                    row.get("taxonomy") or "-",
                    "ALLOW" if row.get("allowed") else "BASE",
                    row.get("rows", 0),
                    fmt_num(row.get("micro_brier")),
                    fmt_num(row.get("candidate_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_candidate"), 4),
                    fmt_signed(row.get("delta_vs_market"), 4),
                    row.get("reason") or "-",
                ]
                for row in micro_gate.get("decisions") or []
            ],
        )
        lines += ["", "### Raw Target Slices", ""]
        lines += markdown_table(
            ["Taxonomy", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market"],
            [
                [
                    row.get("group") or "-",
                    row.get("n", 0),
                    fmt_num(row.get("micro_brier")),
                    fmt_num(row.get("candidate_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_candidate"), 4),
                    fmt_signed(row.get("delta_vs_market"), 4),
                ]
                for row in micro.get("target_slices") or []
            ],
        )
        lines += ["", "### Gated Target Slices", ""]
        lines += markdown_table(
            ["Taxonomy", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market"],
            [
                [
                    row.get("group") or "-",
                    row.get("n", 0),
                    fmt_num(row.get("micro_brier")),
                    fmt_num(row.get("candidate_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_candidate"), 4),
                    fmt_signed(row.get("delta_vs_market"), 4),
                ]
                for row in micro.get("gated_target_slices") or []
            ],
        )
    lines += [
        "",
        "## Global Replay Gate",
        "",
    ]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [
            ["Corpus pin", "PASS" if replay_gate.get("corpus_ok") else "FAIL", replay_gate.get("corpus_message") or "-"],
            ["Replay fidelity", "PASS" if replay_gate.get("fidelity_ok") else "FAIL", replay_gate.get("fidelity_message") or "-"],
        ],
    )
    if serving:
        lines += [
            "",
            "## Current-Serving Gauntlet",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Verdict", serving.get("verdict") or "-"],
                ["Corpus OK", serving.get("corpus_ok")],
                ["Fidelity OK", serving.get("fidelity_ok")],
                ["Regression OK", serving.get("baseline_ok")],
                ["Forecast tracker", (serving.get("forecast_tracker") or {}).get("message") or "-"],
            ],
        )
        lines += ["", "### Serving Gauntlet Markets", ""]
        lines += markdown_table(
            [
                "Market", "Verdict", "Rows", "Replayed Brier", "Recorded Brier",
                "Market Brier", "Code Effect", "Reason",
            ],
            _serving_table_rows(serving),
        )
        blocking_source_rows = _serving_blocking_source_freshness_rows(serving)
        if blocking_source_rows:
            lines += ["", "### Serving Blocking Source Freshness", ""]
            lines += markdown_table(
                [
                    "Market",
                    "Group",
                    "Rows",
                    "Replayed Brier",
                    "Recorded Brier",
                    "Market Brier",
                    "Code Effect",
                    "Excess Brier Rows",
                ],
                blocking_source_rows,
            )
    lines += [
        "",
        "## Per-Market Decisions",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Days", "Snaps", "Rows", "Trust", "Candidate Brier",
            "Current Brier", "Market Brier", "Delta Current",
            "Delta Market", "Blocked Validation", "Action", "Reason",
        ],
        _decision_table_rows(decisions.get("markets") or []),
    )
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_artifact_disk_headroom(
        path,
        estimated_bytes=len(text.encode("utf-8")),
        min_free_bytes=min_free_bytes,
        context="promotion refresh Markdown report export",
    )
    path.write_text(text, encoding="utf-8")
    return path

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]

