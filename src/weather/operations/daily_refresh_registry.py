"""Daily refresh step order and resume filtering helpers."""

from __future__ import annotations


LANE_PROMOTION = "promotion"
LANE_LEARNING = "learning"
LANE_CHOICES = (LANE_PROMOTION, LANE_LEARNING)

# Keep both axes beside the canonical registry. The lane says whether a step
# can keep running for evidence/learning when target-day promotion is blocked.
# The boolean says whether its current-run receipt is required before the
# promotion action may execute. Shared producers can therefore remain in the
# learning lane while still failing promotion closed. Adding a step requires
# declaring both properties in the same edit.
STEP_REGISTRY = (
    ("reanalysis_recent_refresh", LANE_LEARNING, False),
    ("ingest_quality_gate", LANE_LEARNING, True),
    ("event_metadata_validation", LANE_LEARNING, False),
    ("public_wu_settlement_restore", LANE_PROMOTION, False),
    ("market_day_labels_finalize", LANE_PROMOTION, False),
    ("exchange_economics_rule_drift", LANE_PROMOTION, False),
    ("taker_finalization_watchdog", LANE_PROMOTION, False),
    ("taker_edge_permission_map", LANE_PROMOTION, False),
    ("taker_tail_casebook", LANE_PROMOTION, False),
    ("maker_paper_score", LANE_PROMOTION, False),
    ("settlement_source_audit", LANE_PROMOTION, False),
    ("observed_floor_safety_monitor", LANE_PROMOTION, False),
    ("trading_evidence", LANE_PROMOTION, False),
    ("clob_order_book_tiering", LANE_LEARNING, False),
    ("replay_status_backfill", LANE_LEARNING, False),
    ("closed_day_parquet_incremental", LANE_LEARNING, False),
    ("hourly_model_performance", LANE_LEARNING, True),
    ("ten_minute_model_performance", LANE_LEARNING, True),
    ("price_free_model_learning", LANE_LEARNING, False),
    ("model_market_disagreement_rehydration", LANE_LEARNING, False),
    ("settled_day_analysis_barrier", LANE_PROMOTION, True),
    ("runtime_identity_reconciliation", LANE_LEARNING, True),
    ("live_variant_settlement_scorecard", LANE_PROMOTION, True),
    ("fleet_observability", LANE_LEARNING, True),
    ("promotion_refresh", LANE_PROMOTION, True),
    ("shadow_ab_monitor", LANE_LEARNING, False),
    ("active_variant_shadow", LANE_LEARNING, False),
    ("proper_scoring_reliability_scorecard", LANE_LEARNING, False),
    ("frozen_baseline_replay_trend", LANE_LEARNING, False),
    ("model_variant_evidence_growth", LANE_LEARNING, False),
    ("progress_audit", LANE_LEARNING, False),
    ("disagreement_casebook", LANE_LEARNING, False),
    ("daily_roll_log_hygiene", LANE_LEARNING, False),
    ("nightly_health_checks", LANE_LEARNING, False),
    ("data_layer_audit", LANE_LEARNING, False),
    ("snapshot_evaluation", LANE_LEARNING, False),
    ("distribution_stage_attribution", LANE_LEARNING, False),
    ("settled_day_root_cause", LANE_LEARNING, False),
    ("winner_rank_parity", LANE_LEARNING, False),
    ("june23_location_bias_repair", LANE_LEARNING, False),
    ("data_retention_inventory", LANE_LEARNING, False),
    ("daily_learning", LANE_LEARNING, False),
    ("market_beating_objective_scoreboard", LANE_LEARNING, False),
    ("daily_flow_analysis", LANE_LEARNING, False),
)

STEP_ORDER = tuple(name for name, _lane, _gate in STEP_REGISTRY)
STEP_LANES = {name: lane for name, lane, _gate in STEP_REGISTRY}
STEP_PROMOTION_GATES = {
    name: blocks_promotion
    for name, _lane, blocks_promotion in STEP_REGISTRY
}

COVERAGE_OWN = "own"
COVERAGE_DEPENDENCIES = "dependencies"
COVERAGE_NOT_APPLICABLE = "not_applicable"
COVERAGE_MODE_CHOICES = (
    COVERAGE_OWN,
    COVERAGE_DEPENDENCIES,
    COVERAGE_NOT_APPLICABLE,
)

# Learning coverage is a separate concern from execution and promotion gating.
# Own-corpus steps must prove their dated output; dependency-derived steps must
# surface the weakest named input; operational steps must not claim settlement
# coverage at all.
STEP_LEARNING_COVERAGE_MODES = {
    "reanalysis_recent_refresh": COVERAGE_NOT_APPLICABLE,
    "ingest_quality_gate": COVERAGE_NOT_APPLICABLE,
    "event_metadata_validation": COVERAGE_NOT_APPLICABLE,
    "clob_order_book_tiering": COVERAGE_NOT_APPLICABLE,
    "replay_status_backfill": COVERAGE_NOT_APPLICABLE,
    "closed_day_parquet_incremental": COVERAGE_NOT_APPLICABLE,
    "hourly_model_performance": COVERAGE_OWN,
    "ten_minute_model_performance": COVERAGE_OWN,
    "price_free_model_learning": COVERAGE_OWN,
    "model_market_disagreement_rehydration": COVERAGE_OWN,
    "runtime_identity_reconciliation": COVERAGE_OWN,
    "fleet_observability": COVERAGE_NOT_APPLICABLE,
    "shadow_ab_monitor": COVERAGE_DEPENDENCIES,
    "active_variant_shadow": COVERAGE_OWN,
    "proper_scoring_reliability_scorecard": COVERAGE_DEPENDENCIES,
    "frozen_baseline_replay_trend": COVERAGE_OWN,
    "model_variant_evidence_growth": COVERAGE_OWN,
    "progress_audit": COVERAGE_DEPENDENCIES,
    "disagreement_casebook": COVERAGE_OWN,
    "daily_roll_log_hygiene": COVERAGE_NOT_APPLICABLE,
    "nightly_health_checks": COVERAGE_NOT_APPLICABLE,
    "data_layer_audit": COVERAGE_NOT_APPLICABLE,
    "snapshot_evaluation": COVERAGE_DEPENDENCIES,
    "distribution_stage_attribution": COVERAGE_OWN,
    "settled_day_root_cause": COVERAGE_OWN,
    "winner_rank_parity": COVERAGE_OWN,
    "june23_location_bias_repair": COVERAGE_NOT_APPLICABLE,
    "data_retention_inventory": COVERAGE_NOT_APPLICABLE,
    "daily_learning": COVERAGE_OWN,
    "market_beating_objective_scoreboard": COVERAGE_DEPENDENCIES,
    "daily_flow_analysis": COVERAGE_DEPENDENCIES,
}

STEP_LEARNING_COVERAGE_DEPENDENCIES = {
    "shadow_ab_monitor": ("promotion_refresh",),
    "proper_scoring_reliability_scorecard": (
        "active_variant_shadow",
        "hourly_model_performance",
        "ten_minute_model_performance",
    ),
    "progress_audit": ("promotion_refresh",),
    "snapshot_evaluation": ("promotion_refresh",),
    "market_beating_objective_scoreboard": (
        "proper_scoring_reliability_scorecard",
        "winner_rank_parity",
        "trading_evidence",
    ),
    "daily_flow_analysis": (
        "daily_learning",
        "market_beating_objective_scoreboard",
    ),
}

# These are the direct current-run artifacts available before model promotion.
# Earlier target-day producers are summarized by the settled-day barrier, so
# gating on them again here would change its documented advisory/policy
# semantics. `data_layer_audit` and `daily_learning` run after promotion and
# remain explicit prior-run inputs to the canonical promotion adapter; they
# cannot be same-run receipt gates without breaking the existing dependency
# cycle (daily learning itself consumes promotion output).
#
# `known_statuses` identifies a real adapter receipt. `action_statuses` says the
# expensive promotion action may consume it. A known negative verdict is
# reported distinctly from an unknown/malformed receipt, and both fail closed.
STEP_PROMOTION_RECEIPT_POLICIES = {
    "ingest_quality_gate": {
        "known_statuses": frozenset({"PASS", "WARN", "FAIL", "SKIPPED"}),
        "action_statuses": frozenset({"PASS"}),
    },
    "hourly_model_performance": {
        "known_statuses": frozenset({"PASS", "BLOCK", "SKIPPED"}),
        # A current-model BLOCK can be cleared only by the canonical matching
        # candidate mitigation inside promotion refresh.
        "action_statuses": frozenset({"PASS", "BLOCK"}),
        "target_fields": ("last_scored_target_date",),
    },
    "ten_minute_model_performance": {
        "known_statuses": frozenset({"PASS", "BLOCK", "SKIPPED"}),
        "action_statuses": frozenset({"PASS", "BLOCK"}),
        "target_fields": ("last_scored_target_date",),
    },
    "settled_day_analysis_barrier": {
        "known_statuses": frozenset(
            {"PASS", "BLOCK", "DIAGNOSTIC_ONLY", "SKIPPED"}
        ),
        "action_statuses": frozenset({"PASS"}),
        "target_fields": ("target_date",),
    },
    "runtime_identity_reconciliation": {
        "known_statuses": frozenset({"PASS", "BLOCK"}),
        "action_statuses": frozenset({"PASS"}),
        "target_fields": ("target_date",),
        "positive_count_fields": ("snapshot_row_count",),
    },
    "live_variant_settlement_scorecard": {
        "known_statuses": frozenset(
            {"PASS", "BLOCK", "SKIPPED", "DIAGNOSTIC"}
        ),
        "action_statuses": frozenset({"PASS"}),
        "target_fields": ("target_date",),
        "positive_count_fields": (
            "source_row_count",
            "valid_prediction_partition_count",
        ),
    },
    "fleet_observability": {
        "known_statuses": frozenset({"OK", "WARN", "CRITICAL"}),
        "action_statuses": frozenset({"OK"}),
    },
    "promotion_refresh": {
        "known_statuses": frozenset({"OK", "BLOCK"}),
        "action_statuses": frozenset({"OK"}),
    },
}


def step_lane(name):
    """Return the declared execution lane for a registered step."""
    return STEP_LANES[name]


def step_blocks_promotion(name):
    """Return whether promotion requires this step's current-run receipt."""
    return STEP_PROMOTION_GATES[name]

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
        {
            "name": name,
            "lane": STEP_LANES[name],
            "blocks_promotion": STEP_PROMOTION_GATES[name],
            "status": "planned",
        }
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
