"""Implementation slice extracted from src/weather/reporting/fleet/fleet_observability.py."""

from collections import Counter

from weather.reporting.fleet.fleet_observability_payload import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.


def _summarize_messages(messages, limit=3):
    counts = Counter(str(message) for message in messages if message)
    if not counts:
        return "ok"
    top = counts.most_common(limit)
    parts = [
        f"{message} (x{count})" if count > 1 else message
        for message, count in top
    ]
    remaining = sum(counts.values()) - sum(count for _, count in top)
    if remaining:
        parts.append(f"{remaining} more message(s)")
    return "; ".join(parts)

def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown(path, payload):
    collection_rows = []
    trust = payload.get("trust_readiness") or {}
    collection = payload.get("collection") or {}
    for row in (payload.get("collection") or {}).get("markets") or []:
        trust_row = trust.get(row["market_id"]) or {}
        collection_rows.append([
            row["market_id"],
            row.get("state"),
            row.get("snapshots"),
            row.get("reason"),
            trust_row.get("trust_score"),
            trust_row.get("settled_days"),
            trust_row.get("trust_gap"),
            trust_row.get("settled_day_gap"),
        ])
    source_status_proof = collection.get("source_status_proof") or {}
    source_status_summary = (
        source_status_proof.get("summary")
        or ((collection.get("summary") or {}).get("source_family_degradation") or {})
    )
    source_status_rows = [
        [
            row.get("market_id"),
            row.get("snapshot_id") or "-",
            row.get("model_review_allowed"),
            row.get("paper_trading_allowed"),
            row.get("live_trade_permission_allowed"),
            row.get("promotion_readiness_allowed"),
            row.get("affected_family_count"),
            row.get("blocking_family_count"),
            row.get("provider_cooldown_source_count"),
            row.get("expected_unavailable_source_count"),
            row.get("top_degraded_family") or "-",
            _format_source_family_detail(row.get("affected_families") or []),
            row.get("repair_command") or "-",
        ]
        for row in source_status_proof.get("markets") or []
    ]
    audit_rows = []
    gap_coverage = (payload.get("historical_gap_coverage") or {}).get("markets") or {}
    for market_id, audit in sorted((payload.get("historical_audits") or {}).items()):
        coverage_row = gap_coverage.get(market_id) or {}
        audit_rows.append([
            market_id,
            len(audit.get("missing_days") or []) if audit else "-",
            len(audit.get("sparse_days") or []) if audit else "-",
            coverage_row.get("covered_issue_days", "-"),
            len(coverage_row.get("unresolved_issue_days") or []),
            len(audit.get("duplicate_timestamps") or []) if audit else "-",
            len(audit.get("impossible_values") or []) if audit else "-",
            audit.get("hourly_days_audited") if audit else "-",
        ])
    artifact_rows = []
    provenance = payload.get("artifact_provenance") or {}
    for market_id, market in sorted((provenance.get("markets") or {}).items()):
        artifacts = market.get("artifacts") or {}
        artifact_rows.append([
            market_id,
            sum(1 for item in artifacts.values() if item.get("exists")),
            sum(1 for item in artifacts.values() if item.get("schema_status") == "ok"),
            sum(1 for item in artifacts.values() if item.get("schema_status") != "ok"),
        ])
    alert_rows = [
        [
            row.get("severity"),
            row.get("market_id"),
            row.get("category"),
            row.get("message"),
        ]
        for row in payload.get("alerts") or []
    ]
    lines = [
        "# Fleet Observability Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Critical alerts: `{(payload.get('summary') or {}).get('critical_alerts')}`",
        f"Warning alerts: `{(payload.get('summary') or {}).get('warning_alerts')}`",
        "",
        "## Collection And Trust",
        "",
    ]
    lines += markdown_table(
        ["Market", "State", "Snapshots", "Reason", "Trust", "Days", "Trust Gap", "Day Gap"],
        collection_rows,
    )
    lines += [
        "",
        "## Source Status Proof",
        "",
        f"Trading blocked markets: `{source_status_summary.get('source_status_blocked_market_count')}`",
        f"Live-trade blocked markets: `{source_status_summary.get('live_trade_permission_blocked_market_count')}`",
        f"Top degraded family: `{source_status_summary.get('top_degraded_family') or '-'}`",
        f"Provider-cooldown sources: `{source_status_summary.get('provider_cooldown_source_count')}`",
        f"Settlement-auth failure sources: `{source_status_summary.get('settlement_auth_failure_source_count')}`",
        f"Expected current-day unavailable sources: `{source_status_summary.get('expected_unavailable_source_count')}`",
        f"Repair command: `{source_status_proof.get('repair_command') or SOURCE_STATUS_BACKFILL_COMMAND}`",
        f"Verification command: `{source_status_proof.get('verification_command') or SOURCE_PROVIDER_STATUS_COMMAND}`",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Snapshot", "Model Review", "Paper", "Live Trade", "Promotion",
            "Affected Families", "Blocking Families", "Cooldown Sources", "Expected Unavailable", "Top Family",
            "Family Detail", "Repair Command",
        ],
        source_status_rows,
    )
    trading = payload.get("trading_evidence") or {}
    mm_trading = trading.get("market_making") or {}
    taker_trading = trading.get("taker") or {}
    lines += [
        "",
        "## Trading Risk Gates",
        "",
        f"MM current-high trust no-quotes: `{mm_trading.get('current_high_trust_no_quote_count')}`",
        f"Taker current-high trust no-trades: `{taker_trading.get('current_high_trust_no_trade_count')}`",
        f"Taker P&L evidence: `{taker_trading.get('pnl_evidence_status') or '-'}`",
        f"Taker tail quality: `{taker_trading.get('tail_fill_quality_status') or '-'}`",
        "",
    ]
    runtime_evidence = payload.get("runtime_identity_evidence") or {}
    runtime_snapshots = runtime_evidence.get("snapshots") or {}
    runtime_rows = [
        [
            row.get("runtime_git_commit") or row.get("runtime_key"),
            row.get("row_count"),
            row.get("snapshot_count"),
            row.get("market_count"),
            row.get("runtime_source_fingerprint") or "-",
            row.get("runtime_code_states") or {},
        ]
        for row in runtime_snapshots.get("segments") or []
    ]
    lines += [
        "",
        "## Runtime Identity Evidence",
        "",
        f"Status: **{runtime_evidence.get('status') or '-'}**",
        f"Target date: `{runtime_evidence.get('target_date') or '-'}`",
        f"Mixed runtime identity: `{runtime_evidence.get('mixed_runtime_identity')}`",
        f"Runtime identities: `{runtime_evidence.get('runtime_identity_count')}`",
        f"Snapshot rows: `{runtime_evidence.get('snapshot_row_count')}`",
        f"Blocking reason: `{runtime_evidence.get('blocking_reason') or '-'}`",
        f"Reconciliation: `{runtime_evidence.get('reconciliation_status') or '-'}`",
        "",
    ]
    lines += markdown_table(
        ["Commit", "Rows", "Snapshots", "Markets", "Source Fingerprint", "Code States"],
        runtime_rows,
    )
    lines += ["", "## Historical Data Audits", ""]
    lines += markdown_table(
        [
            "Market", "WU Missing", "WU Sparse", "Redundant Covered",
            "Unresolved", "Duplicates", "Impossible", "Hourly Days",
        ],
        audit_rows,
    )
    lines += ["", "## Artifact Provenance", ""]
    lines += markdown_table(
        ["Market", "Artifacts", "Internal Schema OK", "Needs Schema/Manifest Attention"],
        artifact_rows,
    )
    clob = payload.get("clob") or {}
    clob_loop = clob.get("loop") or {}
    clob_rows = [
        [
            row.get("market_id"),
            "OK" if row.get("ok") else "GAP",
            row.get("captures"),
            row.get("median_gap_seconds"),
            row.get("max_gap_seconds"),
            row.get("startup_gaps_ignored") or 0,
            row.get("trailing_age_seconds"),
            row.get("reason") or "-",
        ]
        for row in (clob.get("books") or {}).get("markets") or []
    ]
    lines += [
        "",
        "## CLOB Book Capture",
        "",
        f"Loop state: **{clob_loop.get('state')}** "
        f"(heartbeat age {clob_loop.get('heartbeat_age_seconds')}s, "
        f"last books age {clob_loop.get('last_books_age_seconds')}s)",
        "",
    ]
    lines += markdown_table(
        ["Market", "Tape", "Captures", "Median Gap s", "Max Gap s", "Startup Ignored", "Trailing s", "Reason"],
        clob_rows,
    )
    observation = payload.get("observation_trigger") or {}
    live_forward_slo = payload.get("live_forward_slo") or {}
    optional_streams = live_forward_slo.get("optional_market_event_streams") or {}
    slo_rows = [
        [
            row.get("name"),
            "PASS" if row.get("ok") else "BLOCK",
            row.get("severity"),
            _summarize_messages(row.get("messages") or []),
        ]
        for row in live_forward_slo.get("gates") or []
    ]
    concrete_slo_rows = [
        [
            row.get("name"),
            "PASS" if row.get("ok") else "BLOCK",
            row.get("blocked_market_count"),
            row.get("owner") or "-",
            row.get("repair_command") or "-",
            _summarize_messages(row.get("messages") or []),
        ]
        for row in live_forward_slo.get("concrete_gates") or []
    ]
    recovery_rows = [
        [
            row.get("market_id"),
            row.get("component"),
            row.get("gate"),
            row.get("owner"),
            row.get("before"),
            row.get("repair_command"),
            row.get("verification_command"),
            row.get("after"),
        ]
        for row in live_forward_slo.get("recovery_checklist") or []
    ]
    optional_stream_rows = [
        [
            row.get("market_id"),
            row.get("stream"),
            row.get("severity"),
            row.get("detail"),
        ]
        for row in optional_streams.get("issues") or []
    ]
    snapshot_cadence = (
        live_forward_slo.get("snapshot_cadence_proof")
        or ((payload.get("collection") or {}).get("snapshot_cadence_proof") or {})
    )
    snapshot_cadence_summary = snapshot_cadence.get("summary") or {}
    snapshot_cadence_rows = [
        [
            row.get("market_id"),
            row.get("status"),
            ", ".join(row.get("blocking_gates") or []) or "-",
            row.get("snapshot_count"),
            row.get("gap_count"),
            row.get("max_gap_minutes"),
            row.get("latest_age_minutes"),
            row.get("root_cause"),
            row.get("recoverable_same_day"),
            _format_gap_windows(row.get("gap_windows") or []),
        ]
        for row in snapshot_cadence.get("markets") or []
    ]
    first_slo_blocker = live_forward_slo.get("first_blocker") or {}
    clean_day = payload.get("clean_active_day_countability") or {}
    clean_first_blocker = clean_day.get("first_blocker") or {}
    early_hour_proof = (
        clean_day.get("early_hour_coverage_proof")
        or collection.get("early_hour_coverage_proof")
        or {}
    )
    early_hour_summary = early_hour_proof.get("summary") or {}
    clean_gate_rows = [
        [
            row.get("name"),
            row.get("status"),
            row.get("ok"),
            row.get("detail") or "-",
        ]
        for row in clean_day.get("gates") or []
    ]
    early_hour_rows = [
        [
            row.get("market_id"),
            row.get("status"),
            row.get("snapshot_count"),
            row.get("minimum_snapshot_count"),
            row.get("expected_snapshot_count"),
            row.get("coverage_ratio"),
            row.get("gap_count"),
            row.get("max_gap_minutes"),
            row.get("first_snapshot_at_local") or "-",
            row.get("last_snapshot_at_local") or "-",
            row.get("reason") or "-",
        ]
        for row in early_hour_proof.get("markets") or []
    ]
    lines += [
        "",
        "## Live-Forward SLO Gate",
        "",
        f"Status: **{live_forward_slo.get('status')}**",
        f"Counts toward live-forward gate: `{live_forward_slo.get('counts_toward_live_forward_gate')}`",
        f"Reason: {live_forward_slo.get('reason') or '-'}",
        f"Observation watcher: **{observation.get('state')}** "
        f"(heartbeat age {observation.get('heartbeat_age_seconds')}s)",
        "",
    ]
    lines += markdown_table(
        ["Gate", "Verdict", "Severity", "Detail"],
        slo_rows,
    )
    lines += [
        "",
        "### Optional Market Event Streams",
        "",
        f"Status: **{optional_streams.get('status') or '-'}**",
        f"Blocks core model review: `{optional_streams.get('blocks_core_model_review')}`",
        f"Reason: {optional_streams.get('reason') or '-'}",
        "",
    ]
    lines += markdown_table(
        ["Market", "Stream", "Severity", "Detail"],
        optional_stream_rows,
    )
    lines += ["", "### Broad Recovery Gates", ""]
    lines += markdown_table(
        ["Concrete Gate", "Verdict", "Blocked Markets", "Owner", "Repair Command", "Detail"],
        concrete_slo_rows,
    )
    lines += [
        "",
        "### Snapshot Cadence Proof",
        "",
        f"Status: **{snapshot_cadence_summary.get('status') or '-'}**",
        (
            "Snapshot coverage-gap blocked markets: "
            f"`{snapshot_cadence_summary.get('snapshot_coverage_gap_blocked_market_count')}`"
        ),
        f"Recoverable same-day markets: `{snapshot_cadence_summary.get('recoverable_same_day_market_count')}`",
        (
            "Nonrecoverable active-day blocked markets: "
            f"`{snapshot_cadence_summary.get('nonrecoverable_active_day_blocked_market_count')}`"
        ),
        f"Clean active day required: `{snapshot_cadence_summary.get('clean_active_day_required')}`",
        f"Next unblock action: `{snapshot_cadence_summary.get('next_unblock_action') or '-'}`",
        f"Status command: `{snapshot_cadence.get('status_command') or SNAPSHOT_STATUS_COMMAND}`",
        f"Repair command: `{snapshot_cadence.get('repair_command') or SNAPSHOT_RESTART_COMMAND}`",
        f"Verification command: `{snapshot_cadence.get('verification_command') or BROAD_SLO_VERIFY_COMMAND}`",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Status", "Blocking Gates", "Snapshots", "Gaps", "Max Gap min",
            "Latest Age min", "Root Cause", "Recoverable Same Day", "Gap Windows",
        ],
        snapshot_cadence_rows,
    )
    lines += [
        "",
        "### Broad Recovery Checklist",
        "",
        f"First blocker: `{first_slo_blocker.get('market_id') or '-'}` "
        f"`{first_slo_blocker.get('component') or '-'}` "
        f"`{first_slo_blocker.get('gate') or '-'}`",
        f"First repair command: `{first_slo_blocker.get('repair_command') or '-'}`",
        f"Rerun command: `{live_forward_slo.get('rerun_command') or BROAD_SLO_VERIFY_COMMAND}`",
        "",
    ]
    lines += markdown_table(
        ["Market", "Component", "Gate", "Owner", "Before", "Repair Command", "Verification", "After"],
        recovery_rows,
    )
    if clean_day:
        lines += [
            "",
            "## Clean Active-Day Countability",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", clean_day.get("status") or "-"],
                ["Target date", clean_day.get("target_date") or "-"],
                ["Counts toward clean active day", clean_day.get("counts_toward_clean_active_day")],
                [
                    "Counts toward early-hour evidence",
                    clean_day.get("counts_toward_early_hour_evidence"),
                ],
                ["Operational blockers", clean_day.get("operational_blocker_count")],
                ["First blocker", clean_first_blocker.get("name") or "-"],
                ["First blocker detail", clean_first_blocker.get("detail") or "-"],
                ["Model-skill blockers separate", clean_day.get("model_skill_blockers_separate")],
            ],
        )
        if clean_gate_rows:
            lines += markdown_table(["Gate", "Status", "OK", "Detail"], clean_gate_rows)
        lines += [
            "",
            "### Early-Hour Coverage Proof",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", early_hour_summary.get("status") or "-"],
                ["Countable markets", early_hour_summary.get("countable_market_count")],
                ["Blocked markets", early_hour_summary.get("blocked_market_count")],
                ["Total snapshots", early_hour_summary.get("total_snapshot_count")],
                ["Minimum snapshots", early_hour_summary.get("minimum_snapshot_count")],
                ["Missing snapshots", early_hour_summary.get("total_missing_snapshot_count")],
                ["Total gaps", early_hour_summary.get("total_gap_count")],
                ["Max gap minutes", early_hour_summary.get("max_gap_minutes")],
                ["Next unblock action", early_hour_summary.get("next_unblock_action") or "-"],
            ],
        )
        if early_hour_rows:
            lines += markdown_table(
                [
                    "Market", "Status", "Snaps", "Min", "Expected", "Coverage",
                    "Gaps", "Max Gap min", "First", "Last", "Reason",
                ],
                early_hour_rows,
            )
    mm_paper = payload.get("mm_paper_evidence") or {}
    mm_classes = mm_paper.get("by_class") or {}
    if mm_classes:
        lines += [
            "",
            "## Per-Market MM Paper Evidence",
            "",
            f"Source: `{mm_paper.get('path')}`",
            "",
        ]
        lines += markdown_table(
            ["Evidence Class", "Countable", "Blocked", "All Selected Count", "First Blocked", "Owner"],
            [
                [
                    evidence_class,
                    row.get("countable_market_count"),
                    row.get("blocked_market_count"),
                    row.get("all_selected_markets_count"),
                    row.get("first_blocked_market") or "-",
                    row.get("first_blocked_owner") or "-",
                ]
                for evidence_class, row in sorted(mm_classes.items())
            ],
        )
    mm_starvation = payload.get("mm_evidence_starvation") or {}
    if mm_starvation:
        latest_starvation = mm_starvation.get("latest") or {}
        latest_starved = mm_starvation.get("latest_starved") or {}
        lines += [
            "",
            "## MM Evidence Starvation",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", mm_starvation.get("status")],
                ["Countable paper market-days", mm_starvation.get("countable_paper_market_day_count")],
                ["Starved active-day streak", mm_starvation.get("starved_active_day_streak")],
                ["Unrecovered starved streak", mm_starvation.get("unrecovered_starved_active_day_streak")],
                ["Recovered starved days", mm_starvation.get("recovered_starved_active_day_count")],
                ["Unrecovered starved days", mm_starvation.get("unrecovered_starved_active_day_count")],
                ["Recovery-attempted starved days", mm_starvation.get("recovery_attempted_starved_active_day_count")],
                ["Latest run", latest_starvation.get("run_id") or "-"],
                ["Latest starved run", latest_starved.get("run_id") or "-"],
                ["Latest starved target date", latest_starved.get("target_date") or "-"],
                ["Preflight blocked markets", (
                    f"{(latest_starved or latest_starvation).get('preflight_blocked_market_count')}/"
                    f"{(latest_starved or latest_starvation).get('preflight_market_count')}"
                )],
                ["Blocked fraction", (latest_starved or latest_starvation).get("preflight_blocked_market_fraction")],
                ["Stale loop", (latest_starved or latest_starvation).get("max_stale_input_gate") or "-"],
                ["Stale age seconds", (latest_starved or latest_starvation).get("max_stale_input_age_seconds")],
                ["Owner items", ",".join((latest_starved or latest_starvation).get("recovery_owner_items") or []) or "-"],
                ["Recovery command", (latest_starved or latest_starvation).get("recovery_command") or "-"],
                [
                    "Recovery closeout",
                    (latest_starved or latest_starvation).get("preflight_recovery_closeout_status") or "-",
                ],
                [
                    "Recovery artifact",
                    (latest_starved or latest_starvation).get("preflight_recovery_closeout_path") or "-",
                ],
                [
                    "Post-repair preflight",
                    (latest_starved or latest_starvation).get("post_repair_preflight_status") or "-",
                ],
                [
                    "Post-repair counts",
                    (latest_starved or latest_starvation).get("post_repair_counts_toward_live_forward_gate"),
                ],
            ],
        )
    loop_integrity = payload.get("loop_integrity") or {}
    integrity_rows = [
        [
            row.get("name"),
            "OK" if row.get("ok") else "CHECK",
            row.get("malformed_lines"),
            row.get("duplicate_writer"),
            (row.get("writer_lock") or {}).get("pid") or "-",
            (row.get("status_writer") or {}).get("pid") or "-",
            row.get("repair_command") or "-",
        ]
        for row in loop_integrity.get("rows") or []
    ]
    sample_rows = []
    for row in loop_integrity.get("rows") or []:
        for sample in row.get("malformed_samples") or []:
            sample_rows.append([
                row.get("name"),
                sample.get("source"),
                sample.get("path"),
                sample.get("line"),
                sample.get("classification"),
                sample.get("text"),
            ])
    lines += [
        "",
        "## Loop Artifact Integrity",
        "",
        f"Malformed lines: `{(loop_integrity.get('summary') or {}).get('malformed_lines')}`",
        f"Duplicate writers: `{(loop_integrity.get('summary') or {}).get('duplicate_writer_count')}`",
        "",
    ]
    lines += markdown_table(
        ["Loop", "Status", "Malformed Lines", "Duplicate Writer", "Lock PID", "Status PID", "Repair Command"],
        integrity_rows,
    )
    if sample_rows:
        lines += ["", "### Malformed Line Samples", ""]
        lines += markdown_table(
            ["Loop", "Source", "Path", "Line", "Class", "Sample"],
            sample_rows[:12],
        )
    current_soak = payload.get("current_code_soak") or {}
    current_soak_summary = current_soak.get("summary") or {}
    if current_soak:
        soak_rows = [
            [
                row.get("name"),
                row.get("status"),
                row.get("state"),
                row.get("runtime_code_state"),
                row.get("single_writer"),
                row.get("restart_count"),
                row.get("restart_budget"),
                row.get("restart_budget_clears_at_utc") or "-",
                row.get("duplicate_writer_incidents"),
                row.get("diagnostic_duplicate_writer_incidents"),
                row.get("benign_duplicate_writer_blocks"),
                row.get("malformed_lines"),
                row.get("blocking_owner") or "-",
                "; ".join(row.get("immediate_repair_commands") or []) or "-",
                row.get("consecutive_errors"),
                "; ".join(row.get("blocking_reasons") or []) or "-",
            ]
            for row in current_soak.get("loops") or []
        ]
        taxonomy_rows = [
            [name, count]
            for name, count in sorted((current_soak_summary.get("diagnostic_class_counts") or {}).items())
        ]
        restart_taxonomy_rows = [
            [name, count]
            for name, count in sorted((current_soak_summary.get("restart_class_counts") or {}).items())
        ]
        lines += [
            "",
            "## Current-Code Soak Proof",
            "",
            f"Status: **{current_soak.get('status')}**",
            f"Counts toward active day: `{current_soak.get('counts_toward_active_day')}`",
            f"Window days: `{current_soak.get('window_days')}`",
            f"Cadence SLO: `{current_soak.get('cadence_slo_status')}`",
            f"Cadence reason: {current_soak.get('cadence_slo_reason') or '-'}",
            f"Immediate repair loops: `{current_soak_summary.get('immediate_repair_loop_count')}`",
            f"Aging blocker loops: `{current_soak_summary.get('aging_blocker_loop_count')}`",
            f"First immediate repair: `{current_soak_summary.get('first_immediate_repair_command') or '-'}`",
            f"Latest aging blocker clears: `{current_soak_summary.get('latest_aging_blocker_clears_at_utc') or '-'}`",
            f"Current code: `{format_runtime_identity(current_soak.get('current_identity') or {})}`",
            f"Verification command: `{current_soak.get('verification_command') or BROAD_SLO_VERIFY_COMMAND}`",
            "",
        ]
        lines += markdown_table(
            [
                "Loop", "Status", "State", "Code", "Single Writer", "Restarts",
                "Budget", "Restarts Clear At", "Dup Incidents", "7d Dup Incidents",
                "Benign Dup Blocks", "Malformed", "Owner", "Immediate Repair",
                "Errors", "Blocking Reasons",
            ],
            soak_rows,
        )
        if restart_taxonomy_rows:
            lines += ["", "Restart taxonomy:"]
            lines += markdown_table(["Class", "Restart Events"], restart_taxonomy_rows)
        if taxonomy_rows:
            lines += ["", "Diagnostic taxonomy:"]
            lines += markdown_table(["Class", "Events"], taxonomy_rows)
    parquet_incremental = payload.get("closed_day_parquet_incremental") or {}
    parquet_summary = parquet_incremental.get("summary") or {}
    parquet_rows = [
        ["Status", parquet_incremental.get("status") or "-"],
        ["Mode", parquet_incremental.get("mode") or "-"],
        ["Generated", parquet_incremental.get("generated_at_utc") or "-"],
        ["Scanned", parquet_summary.get("scanned", 0)],
        ["Changed", parquet_summary.get("changed", 0)],
        ["Converted", parquet_summary.get("converted", 0)],
        ["Blocked", parquet_summary.get("blocked", 0)],
        ["Failed", parquet_summary.get("failed", 0)],
        ["Remaining scan backlog", parquet_summary.get("remaining_scan_backlog", 0)],
        ["Source bytes", parquet_summary.get("source_bytes", 0)],
        ["Parquet bytes", parquet_summary.get("parquet_bytes", 0)],
    ]
    lines += ["", "## Closed-Day Parquet Incremental Status", ""]
    lines += markdown_table(["Metric", "Value"], parquet_rows)
    backup = payload.get("tape_backup") or {}
    restore = backup.get("last_restore_drill") or {}
    cleanup_gate = payload.get("cleanup_deletion_gate") or {}
    canonical_cleanup_gate = cleanup_gate.get("canonical_evidence") or {}
    backup_rows = [
        ["Status", backup.get("status")],
        ["Status cache", backup.get("status_cache_path") or "-"],
        ["Status cache loaded", backup.get("status_cache_loaded")],
        ["Backup root", backup.get("backup_root")],
        ["Manifest age hours", backup.get("age_hours")],
        ["Files", backup.get("file_count")],
        ["Missing critical classes", ", ".join(backup.get("missing_critical_classes") or []) or "-"],
        ["Checksum failures", len(backup.get("checksum_failures") or [])],
        ["Restore SLA", backup.get("restore_drill_sla_status") or "-"],
        ["Restore SLA detail", backup.get("restore_drill_sla_detail") or "-"],
        ["Last restore drill", restore.get("status") or "-"],
        ["Restore generated", restore.get("generated_at_utc") or "-"],
        ["Canonical cleanup gate", cleanup_gate.get("status") or "-"],
        ["Canonical delete permission", canonical_cleanup_gate.get("delete_permission") or "-"],
        ["Cleanup missing critical files", cleanup_gate.get("missing_critical_files") or 0],
    ]
    lines += ["", "## Tape Backup And Restore", ""]
    lines += markdown_table(["Metric", "Value"], backup_rows)
    lines += ["", "## Alerts", ""]
    lines += markdown_table(
        ["Severity", "Market", "Category", "Message"],
        alert_rows,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
