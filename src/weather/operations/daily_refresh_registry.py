"""Daily refresh step order and resume filtering helpers."""

from __future__ import annotations


STEP_ORDER = (
    "reanalysis_recent_refresh",
    "ingest_quality_gate",
    "event_metadata_validation",
    "public_wu_settlement_restore",
    "market_day_labels_finalize",
    "exchange_economics_rule_drift",
    "taker_finalization_watchdog",
    "taker_edge_permission_map",
    "taker_tail_casebook",
    "maker_paper_score",
    "settlement_source_audit",
    "trading_evidence",
    "clob_order_book_tiering",
    "replay_status_backfill",
    "closed_day_parquet_incremental",
    "hourly_model_performance",
    "ten_minute_model_performance",
    "price_free_model_learning",
    "model_market_disagreement_rehydration",
    "settled_day_analysis_barrier",
    "runtime_identity_reconciliation",
    "fleet_observability",
    "promotion_refresh",
    "shadow_ab_monitor",
    "active_variant_shadow",
    "proper_scoring_reliability_scorecard",
    "frozen_baseline_replay_trend",
    "model_variant_evidence_growth",
    "progress_audit",
    "disagreement_casebook",
    "daily_roll_log_hygiene",
    "nightly_health_checks",
    "data_layer_audit",
    "snapshot_evaluation",
    "distribution_stage_attribution",
    "settled_day_root_cause",
    "winner_rank_parity",
    "june23_location_bias_repair",
    "data_retention_inventory",
    "daily_learning",
    "market_beating_objective_scoreboard",
    "daily_flow_analysis",
)


def planned_steps():
    return [
        {"name": name, "status": "planned"}
        for name in STEP_ORDER
    ]


def filter_runners_for_resume(runners, resume_from_step=""):
    if not resume_from_step:
        return list(runners)
    if resume_from_step not in STEP_ORDER:
        raise ValueError(f"unknown resume step: {resume_from_step}")
    start = STEP_ORDER.index(resume_from_step)
    allowed = set(STEP_ORDER[start:])
    return [(name, runner) for name, runner in runners if name in allowed]
