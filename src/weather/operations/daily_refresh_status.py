"""Status aggregation helpers for daily refresh runs."""

from __future__ import annotations

import time
import traceback

from weather.operations.daily_refresh_locks import DiskPreflightError, stale_lock_repair_command, utc_iso
from weather.operations.daily_refresh_settled_day import SettledDayAnalysisBarrierError
from weather.reporting.daily import daily_rollup_freshness
from weather.schema_registry import schema_version


def build_rollup_freshness_status(args, *, generated_at_overrides=None):
    return daily_rollup_freshness.build_rollup_freshness(
        args.backtest_root,
        snapshots_root=args.snapshots_root,
        generated_at_overrides=generated_at_overrides or {},
        repair_command=stale_lock_repair_command(args),
    )


def run_step(name, runner, args):
    started = time.time()
    row = {
        "name": name,
        "status": "running",
        "started_at_utc": utc_iso(),
    }
    try:
        row["result"] = runner(args)
        row["status"] = "ok"
    except DiskPreflightError as exc:
        row["status"] = "error"
        row["error"] = str(exc)
        row["root_cause_class"] = "blocked_by_disk"
        row["result"] = exc.payload
    except SettledDayAnalysisBarrierError as exc:
        row["status"] = "error"
        row["error"] = str(exc)
        row["root_cause_class"] = "settled_day_analysis_barrier"
        row["result"] = exc.payload
    except Exception as exc:  # noqa: BLE001
        row["status"] = "error"
        row["error"] = str(exc)
        row["traceback"] = traceback.format_exc()
        if not args.continue_on_error:
            raise
    finally:
        row["finished_at_utc"] = utc_iso()
        row["duration_seconds"] = round(time.time() - started, 3)
    return row


def pipeline_summary(steps):
    by_name = {step["name"]: step for step in steps}
    ingest = ((by_name.get("ingest_quality_gate") or {}).get("result") or {})
    event_metadata = ((by_name.get("event_metadata_validation") or {}).get("result") or {})
    wu_restore = ((by_name.get("public_wu_settlement_restore") or {}).get("result") or {})
    finalize = ((by_name.get("market_day_labels_finalize") or {}).get("result") or {})
    taker_finalization = ((by_name.get("taker_finalization_watchdog") or {}).get("result") or {})
    taker_edge_permission = ((by_name.get("taker_edge_permission_map") or {}).get("result") or {})
    taker_tail = ((by_name.get("taker_tail_casebook") or {}).get("result") or {})
    maker_paper = ((by_name.get("maker_paper_score") or {}).get("result") or {})
    truth_audit = ((by_name.get("settlement_source_audit") or {}).get("result") or {})
    trading = ((by_name.get("trading_evidence") or {}).get("result") or {})
    clob_tiering = ((by_name.get("clob_order_book_tiering") or {}).get("result") or {})
    replay_backfill = ((by_name.get("replay_status_backfill") or {}).get("result") or {})
    promotion = ((by_name.get("promotion_refresh") or {}).get("result") or {})
    hourly = ((by_name.get("hourly_model_performance") or {}).get("result") or {})
    ten_minute = ((by_name.get("ten_minute_model_performance") or {}).get("result") or {})
    price_free = ((by_name.get("price_free_model_learning") or {}).get("result") or {})
    disagreement_rehydration = (
        (by_name.get("model_market_disagreement_rehydration") or {}).get("result") or {}
    )
    settled_barrier = ((by_name.get("settled_day_analysis_barrier") or {}).get("result") or {})
    shadow_ab = ((by_name.get("shadow_ab_monitor") or {}).get("result") or {})
    active_variant_shadow = ((by_name.get("active_variant_shadow") or {}).get("result") or {})
    proper_scorecard = ((by_name.get("proper_scoring_reliability_scorecard") or {}).get("result") or {})
    frozen_baseline = ((by_name.get("frozen_baseline_replay_trend") or {}).get("result") or {})
    variant_evidence = ((by_name.get("model_variant_evidence_growth") or {}).get("result") or {})
    progress = ((by_name.get("progress_audit") or {}).get("result") or {})
    casebook = ((by_name.get("disagreement_casebook") or {}).get("result") or {})
    fleet = ((by_name.get("fleet_observability") or {}).get("result") or {})
    log_hygiene = ((by_name.get("daily_roll_log_hygiene") or {}).get("result") or {})
    nightly_health = ((by_name.get("nightly_health_checks") or {}).get("result") or {})
    audit = ((by_name.get("data_layer_audit") or {}).get("result") or {})
    evaluation = ((by_name.get("snapshot_evaluation") or {}).get("result") or {})
    stage_attribution = ((by_name.get("distribution_stage_attribution") or {}).get("result") or {})
    root_cause = ((by_name.get("settled_day_root_cause") or {}).get("result") or {})
    parity = ((by_name.get("winner_rank_parity") or {}).get("result") or {})
    june23_repair = ((by_name.get("june23_location_bias_repair") or {}).get("result") or {})
    learning = ((by_name.get("daily_learning") or {}).get("result") or {})
    market_objective = ((by_name.get("market_beating_objective_scoreboard") or {}).get("result") or {})
    flow = ((by_name.get("daily_flow_analysis") or {}).get("result") or {})
    variant_learning_gate = variant_learning_gate_from_steps(steps)
    disk_preflights = {
        step.get("name"): (step.get("result") or {}).get("disk_preflight")
        for step in steps
        if (step.get("result") or {}).get("disk_preflight")
    }
    return {
        "labels": {
            "total": finalize.get("label_count"),
            "quality_counts": finalize.get("quality_counts") or {},
            "reconciliation_counts": finalize.get("reconciliation_counts") or {},
        },
        "ingest_quality_gate": {
            "status": ingest.get("status"),
            "summary": ingest.get("summary") or {},
            "fail_reasons": ingest.get("fail_reasons") or [],
            "warn_reasons": ingest.get("warn_reasons") or [],
        },
        "event_metadata_validation": {
            "status": event_metadata.get("status"),
            "target_date": event_metadata.get("target_date"),
            "validation_hash": event_metadata.get("validation_hash"),
            "summary": event_metadata.get("summary") or {},
            "first_blocker": event_metadata.get("first_blocker") or {},
        },
        "public_wu_settlement_restore": {
            "status": wu_restore.get("status"),
            "target_date": wu_restore.get("target_date"),
            "market_count": wu_restore.get("market_count"),
            "restored_market_count": wu_restore.get("restored_market_count"),
            "reused_raw_market_count": wu_restore.get("reused_raw_market_count"),
            "fetched_range_count": wu_restore.get("fetched_range_count"),
            "error_count": wu_restore.get("error_count"),
            "blocked_market_count": wu_restore.get("blocked_market_count"),
            "blocked_markets": wu_restore.get("blocked_markets") or [],
        },
        "taker_finalization_watchdog": {
            "status": taker_finalization.get("status"),
            "run_count": taker_finalization.get("run_count"),
            "labelable_run_count": taker_finalization.get("labelable_run_count"),
            "needs_finalization_count": taker_finalization.get("needs_finalization_count"),
            "finalized_run_count": taker_finalization.get("finalized_run_count"),
            "sla_breach_count": taker_finalization.get("sla_breach_count"),
            "pending_finalization_count": taker_finalization.get("pending_finalization_count"),
            "bakeoff_created_count": taker_finalization.get("bakeoff_created_count"),
            "bakeoff_fresh_count": taker_finalization.get("bakeoff_fresh_count"),
            "champion_decision": taker_finalization.get("champion_decision"),
            "champion_recommended_strategy_id": taker_finalization.get("champion_recommended_strategy_id"),
        },
        "taker_edge_permission_map": {
            "status": taker_edge_permission.get("status"),
            "source_tape_count": taker_edge_permission.get("source_tape_count"),
            "record_count": taker_edge_permission.get("record_count"),
            "edge_allowed_count": taker_edge_permission.get("edge_allowed_count"),
            "observe_count": taker_edge_permission.get("observe_count"),
            "deny_count": taker_edge_permission.get("deny_count"),
        },
        "taker_tail_casebook": {
            "status": taker_tail.get("status"),
            "source_run_count": taker_tail.get("source_run_count"),
            "tail_fill_count": taker_tail.get("tail_fill_count"),
            "losing_tail_fill_count": taker_tail.get("losing_tail_fill_count"),
            "low_price_tail_fill_count": taker_tail.get("low_price_tail_fill_count"),
            "warm_tail_fill_count": taker_tail.get("warm_tail_fill_count"),
            "no_go_candidate_count": taker_tail.get("no_go_candidate_count"),
        },
        "maker_paper_score": {
            "status": maker_paper.get("status"),
            "paper_score_freshness_status": maker_paper.get("paper_score_freshness_status"),
            "latest_completed_active_day": maker_paper.get("latest_completed_active_day"),
            "latest_covered_active_day": maker_paper.get("latest_covered_active_day"),
            "completed_active_run_count": maker_paper.get("completed_active_run_count"),
            "covered_active_run_count": maker_paper.get("covered_active_run_count"),
            "live_forward_day_count": maker_paper.get("live_forward_day_count"),
            "conservative_fills": maker_paper.get("conservative_fills"),
            "net_pnl_after_fees_incentives_usdc": maker_paper.get("net_pnl_after_fees_incentives_usdc"),
            "gate_status": maker_paper.get("gate_status"),
            "blocks_maker_evidence_countability": maker_paper.get("blocks_maker_evidence_countability"),
        },
        "settlement_source_audit": {
            "status": truth_audit.get("status"),
            "target_date": truth_audit.get("target_date"),
            "target_date_gate_blockers": truth_audit.get("target_date_gate_blockers") or [],
            "global_status": truth_audit.get("global_status"),
            "label_count": truth_audit.get("label_count"),
            "finalized_label_count": truth_audit.get("finalized_label_count"),
            "provisional_label_count": truth_audit.get("provisional_label_count"),
            "revised_label_count": truth_audit.get("revised_label_count"),
            "source_disagreement_label_count": truth_audit.get("source_disagreement_label_count"),
            "unreconciled_label_count": truth_audit.get("unreconciled_label_count"),
            "proof_grade_label_count": truth_audit.get("proof_grade_label_count"),
            "promotion_blocked_label_count": truth_audit.get("promotion_blocked_label_count"),
        },
        "trading_evidence": {
            "status": trading.get("status"),
            "mm_evidence_mode": trading.get("mm_evidence_mode"),
            "mm_counts_toward_live_forward": trading.get("mm_counts_toward_live_forward"),
            "mm_maker_countability_gate_status": trading.get("mm_maker_countability_gate_status"),
            "mm_maker_countability_blockers": trading.get("mm_maker_countability_blockers") or [],
            "mm_blocks_maker_evidence_countability": trading.get("mm_blocks_maker_evidence_countability"),
            "mm_evidence_starvation_status": trading.get("mm_evidence_starvation_status"),
            "mm_paper_score_freshness_status": trading.get("mm_paper_score_freshness_status"),
            "mm_paper_latest_completed_active_day": trading.get("mm_paper_latest_completed_active_day"),
            "mm_paper_latest_covered_active_day": trading.get("mm_paper_latest_covered_active_day"),
            "mm_paper_conservative_fills": trading.get("mm_paper_conservative_fills"),
            "mm_paper_gate_status": trading.get("mm_paper_gate_status"),
            "taker_run_id": trading.get("taker_run_id"),
            "taker_quality_status": trading.get("taker_quality_status"),
            "taker_pnl_evidence_status": trading.get("taker_pnl_evidence_status"),
            "taker_settlement_source_audit_status": trading.get("taker_settlement_source_audit_status"),
            "taker_settlement_source_audit_blockers": trading.get("taker_settlement_source_audit_blockers") or [],
            "taker_net_pnl_usdc": trading.get("taker_net_pnl_usdc"),
            "taker_settled_order_count": trading.get("taker_settled_order_count"),
            "taker_unsettled_order_count": trading.get("taker_unsettled_order_count"),
        },
        "promotion": {
            "candidate_verdict": promotion.get("candidate_verdict"),
            "cutover_decision": promotion.get("cutover_decision"),
            "action_counts": promotion.get("action_counts") or {},
            "promote_markets": promotion.get("promote_markets") or [],
            "shadow_markets": promotion.get("shadow_markets") or [],
            "blocked_markets": promotion.get("blocked_markets") or [],
        },
        "clob_order_book_tiering": {
            "status": clob_tiering.get("status"),
            "settled_before": clob_tiering.get("settled_before"),
            "summary": clob_tiering.get("summary") or {},
            "apply_summary": clob_tiering.get("apply_summary") or {},
            "delete_source": clob_tiering.get("delete_source"),
        },
        "hourly_model_performance": {
            "status": hourly.get("status"),
            "daily_summary": hourly.get("daily_summary") or {},
            "hourly_performance_gate": hourly.get("hourly_performance_gate") or {},
            "remediation_registry_summary": hourly.get("remediation_registry_summary") or {},
            "last_scored_target_date": hourly.get("last_scored_target_date"),
            "latest_settled_label_date": hourly.get("latest_settled_label_date"),
            "scoring_liveness_status": hourly.get("scoring_liveness_status"),
            "scoring_liveness": hourly.get("scoring_liveness") or {},
        },
        "ten_minute_model_performance": {
            "status": ten_minute.get("status"),
            "daily_summary": ten_minute.get("daily_summary") or {},
            "ten_minute_performance_gate": ten_minute.get("ten_minute_performance_gate") or {},
            "candidate_ten_minute_gate": ten_minute.get("candidate_ten_minute_gate") or {},
            "weak_slots": ten_minute.get("weak_slots") or [],
            "variant_ids": ten_minute.get("variant_ids") or [],
            "last_scored_target_date": ten_minute.get("last_scored_target_date"),
            "latest_settled_label_date": ten_minute.get("latest_settled_label_date"),
            "scoring_liveness_status": ten_minute.get("scoring_liveness_status"),
            "scoring_liveness": ten_minute.get("scoring_liveness") or {},
        },
        "price_free_model_learning": {
            "status": price_free.get("status"),
            "daily_summary": price_free.get("daily_summary") or {},
            "corpus": price_free.get("corpus") or {},
            "current_max_carryover_summary": price_free.get("current_max_carryover_summary") or {},
            "last_scored_target_date": price_free.get("last_scored_target_date"),
            "latest_settled_label_date": price_free.get("latest_settled_label_date"),
            "scoring_liveness_status": price_free.get("scoring_liveness_status"),
            "scoring_liveness": price_free.get("scoring_liveness") or {},
        },
        "model_market_disagreement_rehydration": {
            "status": disagreement_rehydration.get("status"),
            "target_date": disagreement_rehydration.get("target_date"),
            "target_row_count": disagreement_rehydration.get("target_row_count"),
            "pending_before_count": disagreement_rehydration.get("pending_before_count"),
            "rehydrated_count": disagreement_rehydration.get("rehydrated_count"),
            "model_closer_rehydrated_count": disagreement_rehydration.get("model_closer_rehydrated_count"),
            "market_closer_rehydrated_count": disagreement_rehydration.get("market_closer_rehydrated_count"),
            "excluded_partial_label_count": disagreement_rehydration.get("excluded_partial_label_count"),
            "excluded_missing_label_count": disagreement_rehydration.get("excluded_missing_label_count"),
            "pending_after_count": disagreement_rehydration.get("pending_after_count"),
            "unresolved_after_rehydrate_count": disagreement_rehydration.get("unresolved_after_rehydrate_count"),
            "blocker_count": disagreement_rehydration.get("blocker_count"),
            "blockers": disagreement_rehydration.get("blockers") or [],
            "report_out": disagreement_rehydration.get("report_out"),
        },
        "settled_day_analysis_barrier": {
            "status": settled_barrier.get("status"),
            "target_date": settled_barrier.get("target_date"),
            "blocker_count": settled_barrier.get("blocker_count"),
            "blockers": settled_barrier.get("blockers") or [],
            "policy_verdict_count": settled_barrier.get("policy_verdict_count"),
            "policy_verdicts": settled_barrier.get("policy_verdicts") or [],
            "label_countability": settled_barrier.get("label_countability") or {},
            "settled_day_freshness": settled_barrier.get("settled_day_freshness") or {},
            "resume_command": settled_barrier.get("resume_command"),
        },
        "replay_status_backfill": {
            "status": replay_backfill.get("status"),
            "summary": replay_backfill.get("summary") or {},
        },
        "shadow_ab_monitor": {
            "status": shadow_ab.get("status"),
            "summary": shadow_ab.get("summary") or {},
        },
        "active_variant_shadow": {
            "status": active_variant_shadow.get("status"),
            "summary": active_variant_shadow.get("summary") or {},
            "missing_active_variant_ids": active_variant_shadow.get("missing_active_variant_ids") or [],
            "blockers": active_variant_shadow.get("blockers") or [],
        },
        "proper_scoring_reliability_scorecard": {
            "status": proper_scorecard.get("status"),
            "source_row_count": proper_scorecard.get("source_row_count"),
            "scored_probability_row_count": proper_scorecard.get("scored_probability_row_count"),
            "lane_count": proper_scorecard.get("lane_count"),
            "blocker_count": proper_scorecard.get("blocker_count"),
            "lane_statuses": proper_scorecard.get("lane_statuses") or {},
            "served_validated_parity_status": proper_scorecard.get("served_validated_parity_status"),
        },
        "frozen_baseline_replay_trend": {
            "status": frozen_baseline.get("status"),
            "baseline_id": frozen_baseline.get("baseline_id"),
            "current_variant_id": frozen_baseline.get("current_variant_id"),
            "baseline_variant_id": frozen_baseline.get("baseline_variant_id"),
            "shared_observations": frozen_baseline.get("shared_observations"),
            "shared_market_days": frozen_baseline.get("shared_market_days"),
            "brier_delta_current_minus_baseline": frozen_baseline.get(
                "brier_delta_current_minus_baseline"
            ),
            "brier_delta_current_minus_market": frozen_baseline.get(
                "brier_delta_current_minus_market"
            ),
            "status_reasons": frozen_baseline.get("status_reasons") or [],
        },
        "model_variant_evidence_growth": {
            "status": variant_evidence.get("status"),
            "summary": variant_evidence.get("summary") or {},
            "delta_vs_baseline": variant_evidence.get("delta_vs_baseline"),
            "evidence_sla": variant_evidence.get("evidence_sla") or {},
            "no_growth_reasons": variant_evidence.get("no_growth_reasons") or [],
            "trend": variant_evidence.get("trend") or [],
        },
        "variant_learning_gate": variant_learning_gate,
        "progress_answer": progress.get("answer"),
        "casebook": {
            "case_count": casebook.get("case_count"),
            "settled_case_count": casebook.get("settled_case_count"),
            "open_case_count": casebook.get("open_case_count"),
        },
        "fleet": {
            "status": fleet.get("status"),
            "summary": fleet.get("summary") or {},
        },
        "daily_roll_log_hygiene": {
            "status": log_hygiene.get("status"),
            "current_blocker_count": log_hygiene.get("current_blocker_count"),
            "historical_error_count": log_hygiene.get("historical_error_count"),
            "archived_incident_count": log_hygiene.get("archived_incident_count"),
            "recurring_incident_count": log_hygiene.get("recurring_incident_count"),
            "missing_log_count": log_hygiene.get("missing_log_count"),
            "current_category_counts": log_hygiene.get("current_category_counts") or {},
            "first_current_blocker": log_hygiene.get("first_current_blocker") or {},
            "current_log_root": log_hygiene.get("current_log_root"),
            "incidents_out": log_hygiene.get("incidents_out"),
        },
        "nightly_health_checks": {
            "status": nightly_health.get("status"),
            "alert_count": nightly_health.get("alert_count"),
            "critical_alerts": nightly_health.get("critical_alerts"),
            "warning_alerts": nightly_health.get("warning_alerts"),
            "first_alert": nightly_health.get("first_alert") or {},
            "alert_root": nightly_health.get("alert_root"),
            "report_out": nightly_health.get("report_out"),
            "latest_report_out": nightly_health.get("latest_report_out"),
        },
        "data_layer_audit": {
            "gate_status": audit.get("gate_status"),
            "gate_summary": audit.get("gate_summary") or {},
            "recommendation_counts": audit.get("recommendation_counts") or {},
        },
        "snapshot_evaluation": {
            "status": evaluation.get("status"),
            "gate_counts": evaluation.get("gate_counts") or {},
            "snapshot_folders": evaluation.get("snapshot_folders"),
            "snapshots": evaluation.get("snapshots"),
            "top_gap_count": evaluation.get("top_gap_count"),
        },
        "distribution_stage_attribution": {
            "status": stage_attribution.get("status"),
            "settled_folder_count": stage_attribution.get("settled_folder_count"),
            "attribution_row_count": stage_attribution.get("attribution_row_count"),
            "net_negative_stage_count": stage_attribution.get("net_negative_stage_count"),
            "top_net_negative_stage": stage_attribution.get("top_net_negative_stage") or {},
        },
        "settled_day_root_cause": {
            "status": root_cause.get("status"),
            "target_date": root_cause.get("target_date"),
            "market_count": root_cause.get("market_count"),
            "snapshot_count": root_cause.get("snapshot_count"),
            "issue_count": root_cause.get("issue_count"),
            "issue_counts": root_cause.get("issue_counts") or {},
            "taker_net_pnl_usdc": root_cause.get("taker_net_pnl_usdc"),
            "mm_run_count": root_cause.get("mm_run_count"),
            "last_scored_target_date": root_cause.get("last_scored_target_date"),
            "latest_settled_label_date": root_cause.get("latest_settled_label_date"),
            "scoring_liveness_status": root_cause.get("scoring_liveness_status"),
            "scoring_liveness": root_cause.get("scoring_liveness") or {},
        },
        "winner_rank_parity": {
            "status": parity.get("status"),
            "parity_gate_status": parity.get("parity_gate_status"),
            "source_row_count": parity.get("source_row_count"),
            "candidate_row_count": parity.get("candidate_row_count"),
            "snapshot_case_count": parity.get("snapshot_case_count"),
            "variant_count": parity.get("variant_count"),
            "blocker_count": parity.get("blocker_count"),
            "first_blocker": parity.get("first_blocker") or {},
            "model_top_hit_rate": parity.get("model_top_hit_rate"),
            "market_top_hit_rate": parity.get("market_top_hit_rate"),
            "market_top_model_miss_excess": parity.get("market_top_model_miss_excess"),
            "winner_probability_gap_market_minus_model": parity.get("winner_probability_gap_market_minus_model"),
            "brier_contribution": parity.get("brier_contribution"),
            "candidate_guardrail_block_count": parity.get("candidate_guardrail_block_count"),
        },
        "june23_location_bias_repair": {
            "status": june23_repair.get("status"),
            "target_date": june23_repair.get("target_date"),
            "cases_scored": june23_repair.get("cases_scored"),
            "repair_manifest_count": june23_repair.get("repair_manifest_count"),
            "eligible_repair_manifest_count": june23_repair.get("eligible_repair_manifest_count"),
            "repair_replay_status": june23_repair.get("repair_replay_status"),
            "repair_improvement_count": june23_repair.get("repair_improvement_count"),
            "protected_regression_count": june23_repair.get("protected_regression_count"),
        },
        "market_beating_objective_scoreboard": {
            "status": market_objective.get("status"),
            "headline_status": market_objective.get("headline_status"),
            "first_success_lane": market_objective.get("first_success_lane"),
            "first_blocker": market_objective.get("first_blocker") or {},
            "weather_only_status": market_objective.get("weather_only_status"),
            "residual_edge_status": market_objective.get("residual_edge_status"),
            "executable_profitability_status": market_objective.get("executable_profitability_status"),
            "anti_anchoring_status": market_objective.get("anti_anchoring_status"),
            "blocker_count": market_objective.get("blocker_count"),
        },
        "daily_learning": {
            "status": learning.get("status"),
            "learning_count": learning.get("learning_count"),
            "blocker_count": learning.get("blocker_count"),
            "high_priority_learning_count": learning.get("high_priority_learning_count"),
            "retrain_input_count": learning.get("retrain_input_count"),
            "training_ready": learning.get("training_ready"),
            "promotion_ready": learning.get("promotion_ready"),
        },
        "daily_flow_analysis": {
            "status": flow.get("status"),
            "action_count": flow.get("action_count"),
            "blocker_count": flow.get("blocker_count"),
            "p0_count": flow.get("p0_count"),
            "p1_count": flow.get("p1_count"),
            "training_ready": flow.get("training_ready"),
            "promotion_ready": flow.get("promotion_ready"),
            "next_command": flow.get("next_command"),
        },
        "disk_preflight": disk_preflights,
    }


def _step_result(steps, name):
    for step in steps:
        if step.get("name") == name:
            return step.get("result") or {}
    return {}


def _variant_blocker(component, gate, detail, remediation_command, extra=None):
    return {
        "component": component,
        "gate": gate,
        "detail": detail,
        "remediation_command": remediation_command,
        "suggested_command": remediation_command,
        **(extra or {}),
    }


def _first_no_growth_remediation(evidence):
    for row in evidence.get("no_growth_reasons") or []:
        if row.get("status") in {"BLOCK", "WARN"} and row.get("action"):
            return row.get("action")
    for alert in evidence.get("alerts") or []:
        if alert.get("action"):
            return alert.get("action")
    return "Collect new independent settled market-day evidence before making a broad promotion claim."


def variant_learning_gate_from_steps(steps):
    active = _step_result(steps, "active_variant_shadow")
    evidence = _step_result(steps, "model_variant_evidence_growth")
    blockers = []
    active_status = active.get("status")
    evidence_status = evidence.get("status")

    if active_status in {"BLOCK", "ERROR"}:
        detail = "; ".join(active.get("blockers") or []) or f"active variant shadow status {active_status}"
        missing = active.get("missing_active_variant_ids") or []
        if missing:
            detail = f"{detail}; missing active variants: {', '.join(missing)}"
        blockers.append(_variant_blocker(
            "active_variant_shadow",
            "active_variant_shadow_coverage",
            detail,
            "python -m weather.operations.daily_refresh run --active-variant-shadow-sources <current-active-variant-exports>",
            {"missing_active_variant_ids": missing},
        ))

    if evidence_status == "SKIPPED" and evidence.get("reason") == "missing_current_variant_evidence":
        missing = evidence.get("missing_paths") or []
        blockers.append(_variant_blocker(
            "model_variant_evidence_growth",
            "variant_evidence_missing",
            "current active-variant evidence is missing: " + (", ".join(missing) or "-"),
            "python -m weather.operations.daily_refresh run --active-variant-shadow-sources <current-active-variant-exports>",
            {"missing_paths": missing},
        ))
    elif evidence_status == "ALERT":
        sla = evidence.get("evidence_sla") or {}
        reasons = sla.get("reasons") or []
        detail = "; ".join(reasons) or "model_variant_evidence_growth is ALERT"
        blockers.append(_variant_blocker(
            "model_variant_evidence_growth",
            "variant_evidence_sla",
            detail,
            _first_no_growth_remediation(evidence),
            {
                "evidence_sla_status": sla.get("status"),
                "no_growth_reasons": evidence.get("no_growth_reasons") or [],
            },
        ))

    if blockers:
        status = "BLOCK"
    elif active_status == "SKIPPED" or evidence_status == "SKIPPED":
        status = "SKIPPED"
    elif active or evidence:
        status = "PASS"
    else:
        status = "SKIPPED"
    return {
        "schema_version": schema_version("variant_learning_operational_gate"),
        "status": status,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "active_variant_shadow_status": active_status,
        "model_variant_evidence_growth_status": evidence_status,
    }



