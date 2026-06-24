"""Markdown report rendering for daily refresh."""

from __future__ import annotations

import json
from pathlib import Path


def render_report(payload):
    lines = [
        "# Daily Settlement-To-Promotion Refresh",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Duration seconds: `{payload.get('duration_seconds')}`",
        "",
        "## Steps",
        "",
        "| Step | Status | Seconds | Result |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for step in payload.get("steps") or []:
        result = step.get("result") or {}
        if step.get("status") == "error":
            detail = step.get("error") or "-"
        elif step.get("name") == "market_day_labels_finalize":
            detail = f"labels {result.get('label_count')} {result.get('quality_counts')}"
        elif step.get("name") == "replay_status_backfill":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                summary = result.get("summary") or {}
                detail = (
                    f"{result.get('status')}; wrote {summary.get('written_folder_count')}; "
                    f"irreparable {summary.get('irreparable_folder_count')}; "
                    f"training_ready {summary.get('training_ready_folder_count')}"
                )
        elif step.get("name") == "clob_order_book_tiering":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                summary = result.get("summary") or {}
                apply_summary = result.get("apply_summary") or {}
                detail = (
                    f"{result.get('status')}; candidates {summary.get('candidate_files')}; "
                    f"compressed {apply_summary.get('compressed_files')}; "
                    f"deleted {apply_summary.get('deleted_sources')}; "
                    f"blocked {apply_summary.get('insufficient_headroom')}"
                )
        elif step.get("name") == "reanalysis_recent_refresh":
            if result.get("skipped"):
                detail = result.get("reason") or "skipped"
            else:
                detail = f"fetched {result.get('fetched_ranges')} ranges; errors {result.get('error_count')}"
        elif step.get("name") == "ingest_quality_gate":
            if result.get("skipped"):
                detail = result.get("reason") or "skipped"
            else:
                summary = result.get("summary") or {}
                detail = (
                    f"{result.get('status')}; "
                    f"schema {summary.get('markets_with_schema_errors')}; "
                    f"duplicates {summary.get('markets_with_duplicates')}; "
                    f"impossible {summary.get('markets_with_impossible_values')}; "
                    f"missing {summary.get('markets_with_missing_days')}; "
                    f"sparse {summary.get('markets_with_sparse_days')}"
                )
        elif step.get("name") == "taker_finalization_watchdog":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')}; runs {result.get('run_count')}; "
                    f"finalized {result.get('finalized_run_count')}; "
                    f"pending {result.get('pending_finalization_count')}; "
                    f"sla {result.get('sla_breach_count')}; "
                    f"champion {result.get('champion_decision')}"
                )
        elif step.get("name") == "taker_tail_casebook":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')}; runs {result.get('source_run_count')}; "
                    f"tail {result.get('tail_fill_count')}; "
                    f"losing {result.get('losing_tail_fill_count')}; "
                    f"no_go {result.get('no_go_candidate_count')}"
                )
        elif step.get("name") == "maker_paper_score":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('paper_score_freshness_status')}; "
                    f"latest {result.get('latest_completed_active_day') or '-'}; "
                    f"covered {result.get('latest_covered_active_day') or '-'}; "
                    f"fills {result.get('conservative_fills')}; "
                    f"gate {result.get('gate_status')}"
                )
        elif step.get("name") == "settlement_source_audit":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')}; labels {result.get('label_count')}; "
                    f"proof {result.get('proof_grade_label_count')}; "
                    f"blocked {result.get('promotion_blocked_label_count')}; "
                    f"revised {result.get('revised_label_count')}; "
                    f"unreconciled {result.get('unreconciled_label_count')}"
                )
        elif step.get("name") == "trading_evidence":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')}; taker {result.get('taker_quality_status')} "
                    f"{result.get('taker_pnl_evidence_status')}; "
                    f"mm_counts {result.get('mm_counts_toward_live_forward')}; "
                    f"starvation {result.get('mm_evidence_starvation_status')}; "
                    f"paper_score {result.get('mm_paper_score_freshness_status')}"
                )
        elif step.get("name") == "promotion_refresh":
            disk = result.get("disk_preflight") or {}
            if result.get("status") == "BLOCK" and disk:
                detail = (
                    f"disk BLOCK; free {disk.get('free_bytes')}; "
                    f"required {disk.get('required_free_bytes')}; "
                    f"short {disk.get('insufficient_bytes')}"
                )
            else:
                detail = (
                    f"{result.get('candidate_verdict')} / {result.get('cutover_decision')}; "
                    f"actions {result.get('action_counts')}"
                )
        elif step.get("name") == "hourly_model_performance":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                gate = result.get("hourly_performance_gate") or {}
                daily = result.get("daily_summary") or {}
                detail = (
                    f"{gate.get('status')}; blockers {gate.get('blocker_count', 0)}; "
                    f"worst {', '.join(daily.get('worst_hours') or []) or '-'}"
                )
        elif step.get("name") == "ten_minute_model_performance":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                gate = result.get("ten_minute_performance_gate") or {}
                daily = result.get("daily_summary") or {}
                detail = (
                    f"{gate.get('status')}; blockers {gate.get('blocker_count', 0)}; "
                    f"weak {', '.join(daily.get('weak_slots') or []) or '-'}"
                )
        elif step.get("name") == "price_free_model_learning":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                daily = result.get("daily_summary") or {}
                carryover = result.get("current_max_carryover_summary") or {}
                detail = (
                    f"{result.get('status')}; days {daily.get('scored_market_days')}; "
                    f"rows {daily.get('hourly_checkpoint_rows')}; "
                    f"current_max_guarded {carryover.get('risky_or_guarded_count', 0)}"
                )
        elif step.get("name") == "shadow_ab_monitor":
            detail = f"{result.get('status')} {result.get('summary')}"
        elif step.get("name") == "active_variant_shadow":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')} "
                    f"{(result.get('summary') or {}).get('canonical_rows')} rows; "
                    f"missing {len(result.get('missing_active_variant_ids') or [])}"
                )
        elif step.get("name") == "proper_scoring_reliability_scorecard":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')}; "
                    f"scored {result.get('scored_probability_row_count')}; "
                    f"lanes {result.get('lane_count')}; "
                    f"blockers {result.get('blocker_count')}; "
                    f"parity {result.get('served_validated_parity_status')}"
                )
        elif step.get("name") == "frozen_baseline_replay_trend":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            elif result.get("status") == "MISSING":
                detail = f"MISSING; {result.get('reason') or '; '.join(result.get('status_reasons') or []) or '-'}"
            else:
                detail = (
                    f"{result.get('status')} "
                    f"{result.get('shared_observations')} shared obs; "
                    f"cur-base {result.get('brier_delta_current_minus_baseline')}"
                )
        elif step.get("name") == "model_variant_evidence_growth":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')} "
                    f"{(result.get('summary') or {}).get('unique_observation_count')} unique obs; "
                    f"delta {result.get('delta_vs_baseline')}"
                )
        elif step.get("name") == "progress_audit":
            detail = result.get("answer") or "-"
        elif step.get("name") == "disagreement_casebook":
            detail = (
                f"cases {result.get('case_count')}; "
                f"settled {result.get('settled_case_count')}; open {result.get('open_case_count')}"
            )
        elif step.get("name") == "fleet_observability":
            detail = f"{result.get('status')} {result.get('summary')}"
        elif step.get("name") == "nightly_health_checks":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')}; "
                    f"alerts {result.get('alert_count')}; "
                    f"critical {result.get('critical_alerts')}; "
                    f"report {result.get('report_out') or '-'}"
                )
        elif step.get("name") == "data_layer_audit":
            if result.get("skipped"):
                detail = result.get("reason") or "skipped"
            else:
                detail = f"gates {result.get('gate_status')} {result.get('gate_summary')}"
        elif step.get("name") == "snapshot_evaluation":
            detail = (
                f"{result.get('status')} {result.get('gate_counts')}; "
                f"snapshots {result.get('snapshots')}; gaps {result.get('top_gap_count')}"
            )
        elif step.get("name") == "distribution_stage_attribution":
            top_stage = (result.get("top_net_negative_stage") or {}).get("group") or "-"
            detail = (
                f"{result.get('status')}; rows {result.get('attribution_row_count')}; "
                f"net_negative {result.get('net_negative_stage_count')}; top {top_stage}; "
                f"winner_mass_blocks {result.get('bottom_location_winner_mass_blocker_count')}"
            )
        elif step.get("name") == "settled_day_root_cause":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')}; date {result.get('target_date')}; "
                    f"issues {result.get('issue_count')}; taker {result.get('taker_net_pnl_usdc')}"
                )
        elif step.get("name") == "winner_rank_parity":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('parity_gate_status')}; cases {result.get('snapshot_case_count')}; "
                    f"model_top {result.get('model_top_hit_rate')}; "
                    f"market_top {result.get('market_top_hit_rate')}; "
                    f"excess {result.get('market_top_model_miss_excess')}; "
                    f"blockers {result.get('blocker_count')}"
                )
        elif step.get("name") == "data_retention_inventory":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                summary = result.get("summary") or {}
                disk = result.get("disk") or {}
                detail = (
                    f"{result.get('status')}; data {summary.get('total_human')}; "
                    f"recent {summary.get('recent_human')}; free {disk.get('free_human')}; "
                    f"restore_blocks {summary.get('restore_block_count')}"
                )
        elif step.get("name") == "daily_learning":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')}; learnings {result.get('learning_count')}; "
                    f"blockers {result.get('blocker_count')}; "
                    f"training_ready {result.get('training_ready')}"
                )
        elif step.get("name") == "market_beating_objective_scoreboard":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                first = result.get("first_blocker") or {}
                detail = (
                    f"{result.get('headline_status')}; "
                    f"weather {result.get('weather_only_status')}; "
                    f"residual {result.get('residual_edge_status')}; "
                    f"profit {result.get('executable_profitability_status')}; "
                    f"first {first.get('detail') or '-'}"
                )
        elif step.get("name") == "daily_flow_analysis":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')}; actions {result.get('action_count')}; "
                    f"blockers {result.get('blocker_count')}; "
                    f"next {result.get('next_command') or '-'}"
                )
        else:
            detail = "-"
        lines.append(
            f"| {step.get('name')} | {step.get('status')} | "
            f"{step.get('duration_seconds', '-')} | {detail} |"
        )
    hourly_summary = (payload.get("summary") or {}).get("hourly_model_performance") or {}
    hourly_gate = hourly_summary.get("hourly_performance_gate") or {}
    if hourly_gate:
        first = hourly_gate.get("first_blocker") or {}
        daily = hourly_summary.get("daily_summary") or {}
        lines += [
            "",
            "## Hourly Performance Gate",
            "",
            f"Status: `{hourly_gate.get('status')}`",
            f"Best hours: {', '.join(daily.get('best_hours') or []) or '-'}",
            f"Worst hours: {', '.join(daily.get('worst_hours') or []) or '-'}",
            f"First blocker: {first.get('detail') or '-'}",
            f"Remediation: `{first.get('remediation_command') or '-'}`",
            "",
        ]
    ten_minute_summary = (payload.get("summary") or {}).get("ten_minute_model_performance") or {}
    ten_minute_gate = ten_minute_summary.get("ten_minute_performance_gate") or {}
    if ten_minute_gate:
        first = ten_minute_gate.get("first_blocker") or {}
        daily = ten_minute_summary.get("daily_summary") or {}
        candidate_gate = ten_minute_summary.get("candidate_ten_minute_gate") or {}
        lines += [
            "",
            "## 10-Minute Performance Gate",
            "",
            f"Status: `{ten_minute_gate.get('status')}`",
            f"Weak slots: {', '.join(daily.get('weak_slots') or []) or '-'}",
            f"Worst slots: {', '.join(daily.get('worst_slots') or []) or '-'}",
            f"Candidate gate: `{candidate_gate.get('status') or '-'}`",
            f"First blocker: {first.get('detail') or '-'}",
            f"Remediation: `{first.get('remediation_command') or '-'}`",
            "",
        ]
    price_free_summary = (payload.get("summary") or {}).get("price_free_model_learning") or {}
    price_free_daily = price_free_summary.get("daily_summary") or {}
    price_free_carryover = price_free_summary.get("current_max_carryover_summary") or {}
    if price_free_summary.get("status"):
        lines += [
            "",
            "## Price-Free Model Learning",
            "",
            f"Status: `{price_free_summary.get('status')}`",
            f"Scored market-days: `{price_free_daily.get('scored_market_days', 0)}`",
            f"Hourly checkpoint rows: `{price_free_daily.get('hourly_checkpoint_rows', 0)}`",
            f"Final top-hit rate: `{price_free_daily.get('final_top_hit_rate')}`",
            f"Current-max guarded rows: `{price_free_carryover.get('risky_or_guarded_count', 0)}`",
            "",
        ]
    variant_gate = (payload.get("summary") or {}).get("variant_learning_gate") or {}
    if variant_gate:
        first = variant_gate.get("first_blocker") or {}
        lines += [
            "",
            "## Variant Learning Gate",
            "",
            f"Status: `{variant_gate.get('status')}`",
            f"First blocker: {first.get('detail') or '-'}",
            f"Remediation: `{first.get('remediation_command') or '-'}`",
            "",
        ]
    scorecard = (payload.get("summary") or {}).get("proper_scoring_reliability_scorecard") or {}
    if scorecard.get("status"):
        lines += [
            "",
            "## Proper-Scoring Reliability",
            "",
            f"Status: `{scorecard.get('status')}`",
            f"Scored probability rows: `{scorecard.get('scored_probability_row_count')}`",
            f"Lanes: `{scorecard.get('lane_count')}`",
            f"Blockers: `{scorecard.get('blocker_count')}`",
            f"Served-vs-validated parity: `{scorecard.get('served_validated_parity_status')}`",
            "",
        ]
    parity = (payload.get("summary") or {}).get("winner_rank_parity") or {}
    if parity.get("status"):
        first = parity.get("first_blocker") or {}
        lines += [
            "",
            "## Winner-Rank Parity",
            "",
            f"Status: `{parity.get('status')}`",
            f"Gate: `{parity.get('parity_gate_status')}`",
            f"Snapshot cases: `{parity.get('snapshot_case_count')}`",
            f"Model top-hit rate: `{parity.get('model_top_hit_rate')}`",
            f"Market top-hit rate: `{parity.get('market_top_hit_rate')}`",
            f"Market-top/model-miss excess: `{parity.get('market_top_model_miss_excess')}`",
            f"Brier contribution: `{parity.get('brier_contribution')}`",
            f"Candidate guardrail blockers: `{parity.get('candidate_guardrail_block_count')}`",
            f"First blocker: {first.get('detail') or '-'}",
            "",
        ]
    objective = (payload.get("summary") or {}).get("market_beating_objective_scoreboard") or {}
    if objective.get("status"):
        first = objective.get("first_blocker") or {}
        lines += [
            "",
            "## Market-Beating Objective",
            "",
            f"Status: `{objective.get('headline_status') or objective.get('status')}`",
            f"First success lane: `{objective.get('first_success_lane') or '-'}`",
            f"Weather-only: `{objective.get('weather_only_status') or '-'}`",
            f"Residual edge: `{objective.get('residual_edge_status') or '-'}`",
            f"Executable profitability: `{objective.get('executable_profitability_status') or '-'}`",
            f"Anti-anchoring: `{objective.get('anti_anchoring_status') or '-'}`",
            f"First blocker: {first.get('detail') or '-'}",
            "",
        ]
    taker_finalization = (payload.get("summary") or {}).get("taker_finalization_watchdog") or {}
    taker_tail = (payload.get("summary") or {}).get("taker_tail_casebook") or {}
    maker_paper = (payload.get("summary") or {}).get("maker_paper_score") or {}
    truth_audit = (payload.get("summary") or {}).get("settlement_source_audit") or {}
    trading = (payload.get("summary") or {}).get("trading_evidence") or {}
    nightly_health = (payload.get("summary") or {}).get("nightly_health_checks") or {}
    if nightly_health.get("status"):
        first = nightly_health.get("first_alert") or {}
        lines += [
            "",
            "## Nightly Health Checks",
            "",
            f"Status: `{nightly_health.get('status')}`",
            f"Alerts: `{nightly_health.get('alert_count')}`",
            f"Critical: `{nightly_health.get('critical_alerts')}`",
            f"Warning: `{nightly_health.get('warning_alerts')}`",
            f"First alert: {first.get('message') or '-'}",
            f"Report: `{nightly_health.get('report_out') or '-'}`",
            f"Latest report: `{nightly_health.get('latest_report_out') or '-'}`",
            "",
        ]
    if (
        taker_finalization.get("status")
        or taker_tail.get("status")
        or maker_paper.get("status")
        or truth_audit.get("status")
        or trading.get("status")
    ):
        lines += [
            "",
            "## Maker, Taker, And Trading Evidence",
            "",
            "| Artifact | Status | Detail |",
            "| :--- | :--- | :--- |",
        ]
        if taker_finalization.get("status"):
            lines.append(
                "| Finalization watchdog | "
                f"{taker_finalization.get('status')} | "
                f"runs={taker_finalization.get('run_count')}; "
                f"finalized={taker_finalization.get('finalized_run_count')}; "
                f"pending={taker_finalization.get('pending_finalization_count')}; "
                f"sla={taker_finalization.get('sla_breach_count')}; "
                f"champion={taker_finalization.get('champion_decision')} |"
            )
        if taker_tail.get("status"):
            lines.append(
                "| Tail casebook | "
                f"{taker_tail.get('status')} | "
                f"runs={taker_tail.get('source_run_count')}; "
                f"tail={taker_tail.get('tail_fill_count')}; "
                f"losing={taker_tail.get('losing_tail_fill_count')}; "
                f"no_go={taker_tail.get('no_go_candidate_count')} |"
            )
        if maker_paper.get("status"):
            lines.append(
                "| Maker paper score | "
                f"{maker_paper.get('status')} | "
                f"freshness={maker_paper.get('paper_score_freshness_status')}; "
                f"latest={maker_paper.get('latest_completed_active_day') or '-'}; "
                f"covered={maker_paper.get('latest_covered_active_day') or '-'}; "
                f"fills={maker_paper.get('conservative_fills')}; "
                f"gate={maker_paper.get('gate_status')} |"
            )
        if truth_audit.get("status"):
            lines.append(
                "| Settlement source audit | "
                f"{truth_audit.get('status')} | "
                f"labels={truth_audit.get('label_count')}; "
                f"proof={truth_audit.get('proof_grade_label_count')}; "
                f"blocked={truth_audit.get('promotion_blocked_label_count')}; "
                f"revised={truth_audit.get('revised_label_count')}; "
                f"unreconciled={truth_audit.get('unreconciled_label_count')} |"
            )
        if trading.get("status"):
            lines.append(
                "| Trading evidence | "
                f"{trading.get('status')} | "
                f"taker={trading.get('taker_quality_status')} "
                f"{trading.get('taker_pnl_evidence_status')}; "
                f"truth={trading.get('taker_settlement_source_audit_status')}; "
                f"mm_counts={trading.get('mm_counts_toward_live_forward')}; "
                f"starvation={trading.get('mm_evidence_starvation_status')}; "
                f"paper_score={trading.get('mm_paper_score_freshness_status')} |"
            )
    disk_preflights = (payload.get("summary") or {}).get("disk_preflight") or {}
    if disk_preflights:
        lines += ["", "## Disk Preflight", ""]
        disk_rows = []
        for step_name, disk in sorted(disk_preflights.items()):
            disk_rows.append([
                step_name,
                disk.get("status"),
                disk.get("free_bytes"),
                disk.get("required_free_bytes"),
                disk.get("projected_export_bytes"),
                disk.get("insufficient_bytes"),
                disk.get("cleanup_command"),
                disk.get("resume_command"),
            ])
        lines += [
            "| Step | Status | Free Bytes | Required Bytes | Projected Export Bytes | Shortfall | Cleanup Command | Resume Command |",
            "| :--- | :--- | ---: | ---: | ---: | ---: | :--- | :--- |",
        ]
        for row in disk_rows:
            lines.append(
                f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} | {row[6]} | {row[7]} |"
            )
    rollup_freshness = (payload.get("summary") or {}).get("rollup_freshness") or {}
    if rollup_freshness:
        lines += [
            "",
            "## Daily Rollup Freshness",
            "",
            f"Status: `{rollup_freshness.get('status')}`",
            f"Latest granular artifact: `{rollup_freshness.get('latest_required_artifact') or '-'}`",
            f"Repair command: `{rollup_freshness.get('repair_command') or '-'}`",
            "",
        ]
        if rollup_freshness.get("blockers"):
            lines += [
                "| Rollup | Status | Latest Granular Artifact | Rollup Timestamp | Granular Timestamp |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
            for blocker in rollup_freshness.get("blockers") or []:
                lines.append(
                    "| "
                    f"{blocker.get('rollup')} | "
                    f"{blocker.get('status')} | "
                    f"{blocker.get('latest_required_artifact') or '-'} | "
                    f"{blocker.get('rollup_timestamp_utc') or '-'} | "
                    f"{blocker.get('latest_required_timestamp_utc') or '-'} |"
                )
    progress_ledger = payload.get("daily_progress_ledger") or {}
    if progress_ledger:
        lines += [
            "",
            "## Daily Progress Ledger",
            "",
            f"Status: `{progress_ledger.get('status')}`",
            (
                "Market-beating objective: "
                f"`{progress_ledger.get('market_beating_objective_status') or '-'}`"
            ),
            (
                "Market-beating first blocker: "
                f"{progress_ledger.get('market_beating_objective_first_blocker') or '-'}"
            ),
            f"Broad improvement claim allowed: `{progress_ledger.get('broad_improvement_claim_allowed')}`",
            (
                "Claim failures: "
                f"`{', '.join(progress_ledger.get('broad_improvement_claim_failures') or []) or '-'}`"
            ),
            f"JSONL: `{progress_ledger.get('jsonl_out') or '-'}`",
            f"CSV: `{progress_ledger.get('csv_out') or '-'}`",
            f"Report: `{progress_ledger.get('report_out') or '-'}`",
            "",
        ]
    flow = (payload.get("summary") or {}).get("daily_flow_analysis") or {}
    if flow.get("status"):
        lines += [
            "",
            "## Daily Flow Analysis",
            "",
            f"Status: `{flow.get('status')}`",
            f"Actions: `{flow.get('action_count')}`",
            f"Blockers: `{flow.get('blocker_count')}`",
            f"P0/P1: `{flow.get('p0_count')}/{flow.get('p1_count')}`",
            f"Training ready: `{flow.get('training_ready')}`",
            f"Promotion ready: `{flow.get('promotion_ready')}`",
            f"Next command/action: `{flow.get('next_command') or '-'}`",
            "",
        ]
    lines += [
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(payload.get("summary") or {}, indent=2, sort_keys=True, default=str),
        "```",
        "",
    ]
    return "\n".join(lines)


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


