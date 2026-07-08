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

STAGE_ALL = "all"
STAGE_SETTLEMENT = "settlement"
STAGE_EVIDENCE = "evidence"
STAGE_CHOICES = (STAGE_ALL, STAGE_SETTLEMENT, STAGE_EVIDENCE)
STAGE_A_END_STEP = "fleet_observability"
STAGE_B_START_STEP = "promotion_refresh"


def step_names_for_stage(stage="all"):
    stage = stage or STAGE_ALL
    if stage == STAGE_ALL:
        return tuple(STEP_ORDER)
    if stage == STAGE_SETTLEMENT:
        end = STEP_ORDER.index(STAGE_A_END_STEP) + 1
        return tuple(STEP_ORDER[:end])
    if stage == STAGE_EVIDENCE:
        start = STEP_ORDER.index(STAGE_B_START_STEP)
        return tuple(STEP_ORDER[start:])
    raise ValueError(f"unknown daily refresh stage: {stage}")


def planned_steps(stage="all"):
    return [
        {"name": name, "status": "planned"}
        for name in step_names_for_stage(stage)
    ]


def filter_runners_for_resume(runners, resume_from_step=""):
    if not resume_from_step:
        return list(runners)
    if resume_from_step not in STEP_ORDER:
        raise ValueError(f"unknown resume step: {resume_from_step}")
    start = STEP_ORDER.index(resume_from_step)
    allowed = set(STEP_ORDER[start:])
    return [(name, runner) for name, runner in runners if name in allowed]


def filter_runners_for_stage(runners, stage="all"):
    if (stage or STAGE_ALL) == STAGE_ALL:
        return list(runners)
    allowed = set(step_names_for_stage(stage))
    return [(name, runner) for name, runner in runners if name in allowed]


def filter_runners_for_stage_and_resume(runners, stage="all", resume_from_step=""):
    return filter_runners_for_resume(
        filter_runners_for_stage(runners, stage),
        resume_from_step=resume_from_step,
    )


def carried_forward_steps(prior_steps, resume_from_step=""):
    """Prior-run steps that precede the resume point, marked as carried.

    A resumed run re-executes only the tail of the pipeline, but consumers
    such as the settled-day analysis barrier and the pipeline summary need
    the completed head steps' results; without carrying them forward a
    resumed barrier sees only step_missing dependencies and the advertised
    resume command cannot work.
    """
    if not resume_from_step:
        return []
    if resume_from_step not in STEP_ORDER:
        raise ValueError(f"unknown resume step: {resume_from_step}")
    allowed = set(STEP_ORDER[: STEP_ORDER.index(resume_from_step)])
    carried = []
    for step in prior_steps or []:
        if step.get("name") in allowed:
            row = dict(step)
            row["carried_forward"] = True
            carried.append(row)
    return carried


def carried_forward_stage_head(prior_steps, stage="all"):
    if stage != STAGE_EVIDENCE:
        return []
    allowed = set(step_names_for_stage(STAGE_SETTLEMENT))
    carried = []
    for step in prior_steps or []:
        if step.get("name") in allowed:
            row = dict(step)
            row["carried_forward"] = True
            row["carried_forward_source_stage"] = STAGE_SETTLEMENT
            carried.append(row)
    return carried
