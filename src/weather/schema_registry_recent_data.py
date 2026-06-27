"""Recent static schema records for the schema registry."""

from __future__ import annotations

from weather.schema_registry_types import SchemaSpec


RECENT_REGISTERED_SCHEMAS = (
    SchemaSpec(
        "runtime_identity_evidence",
        "runtime_identity_evidence_v0.1",
        "weather.reporting.serving_gates.runtime_identity_evidence",
        "active",
        "Runtime identity reconciliation evidence over snapshot and trading artifacts.",
    ),
    SchemaSpec(
        "runtime_identity_reconciliation",
        "runtime_identity_reconciliation_v0.1",
        "weather.reporting.serving_gates.runtime_identity_reconciliation",
        "active",
        "Fail-closed reviewed reconciliation surface for mixed runtime identity aggregation.",
    ),
    SchemaSpec(
        "snapshot_core_sidecar_backfill",
        "snapshot_core_sidecar_backfill_v0.1",
        "weather.collection.snapshot_store",
        "active",
        "Snapshot core sidecar backfill report.",
    ),
    SchemaSpec(
        "snapshot_core_sidecar_backfill_batch",
        "snapshot_core_sidecar_backfill_batch_v0.1",
        "weather.collection.snapshot_store",
        "active",
        "Batch snapshot core sidecar backfill report.",
    ),
    SchemaSpec(
        "snapshot_explanation_backfill",
        "snapshot_explanation_backfill_v0.1",
        "weather.collection.snapshot_store",
        "active",
        "Snapshot explanation sidecar backfill report.",
    ),
    SchemaSpec(
        "snapshot_explanation_backfill_batch",
        "snapshot_explanation_backfill_batch_v0.1",
        "weather.collection.snapshot_store",
        "active",
        "Batch snapshot explanation sidecar backfill report.",
    ),
    SchemaSpec(
        "snapshot_explanations",
        "snapshot_explanations_v0.1",
        "weather.collection.snapshot_store",
        "active",
        "Snapshot explanation sidecar artifact.",
    ),
    SchemaSpec(
        "snapshot_sidecar_eligibility",
        "snapshot_sidecar_eligibility_v0.1",
        "weather.calibration.pooled_candidate_replay_diagnostics",
        "active",
        "Snapshot sidecar eligibility diagnostics.",
    ),
    SchemaSpec(
        "source_status_proof",
        "source_status_proof_v0.1",
        "weather.collection.collection_health",
        "active",
        "Proof artifact for source-status freshness and degradation.",
    ),
    SchemaSpec(
        "source_status_proof",
        "source_status_proof_v0.2",
        "weather.collection.collection_health",
        "active",
        "Proof artifact for source-status freshness, degradation, and redacted provider credential presence.",
        supersedes=("source_status_proof_v0.1",),
        migration_notes=(
            "Adds provider_credential_environment and weather_com_credential_* boolean fields "
            "for settlement_source_auth_failure root causes; credential values remain omitted."
        ),
    ),
    SchemaSpec(
        "mm_live_readiness",
        "mm_live_readiness_v0.2",
        "weather.market.market_making_readiness",
        "active",
        "Conservative market-making live-readiness summary and sorted no-go gate evidence.",
    ),
    SchemaSpec(
        "mm_quote_blocker_diagnostics",
        "mm_quote_blocker_diagnostics_v0.8",
        "weather.market.mm_paper",
        "active",
        "Market-making paper quote blocker diagnostics with known-edge and event-gate overlap evidence.",
    ),
    SchemaSpec(
        "mm_quote_intent",
        "mm_quote_intent_v0.3",
        "weather.market.mm_policy",
        "active",
        "Per-row market-making quote intent and no-quote decision schema.",
    ),
    SchemaSpec(
        "mm_reward_score_diagnostics",
        "mm_reward_score_diagnostics_v0.2",
        "weather.market.mm_paper",
        "active",
        "Market-making reward score diagnostics including reward-share and competitor-score evidence.",
    ),
    SchemaSpec(
        "taker_bot_policy",
        "taker_bot_policy_v0.1",
        "weather.market.taker_bot",
        "active",
        "Taker-bot policy/config artifact.",
    ),
    SchemaSpec(
        "taker_clustered_promotion_gate",
        "taker_clustered_promotion_gate_v0.1",
        "weather.market.taker_bot_bakeoff",
        "active",
        "Clustered promotion gate for taker strategy/model variants.",
    ),
    SchemaSpec(
        "taker_counterfactual_tape",
        "taker_counterfactual_tape_v0.1",
        "weather.market.taker_bot_tape_io",
        "active",
        "Counterfactual taker order tape.",
    ),
    SchemaSpec(
        "taker_current_replay_profitability_verification",
        "taker_current_replay_profitability_verification_v0.1",
        "weather.market.taker_bot_bakeoff",
        "active",
        "Current replay profitability verifier for taker strategies.",
    ),
    SchemaSpec(
        "taker_edge_permission_map",
        "taker_edge_permission_map_v0.1",
        "weather.market.taker_edge_permission",
        "active",
        "Per-slice taker edge permission map.",
    ),
    SchemaSpec(
        "taker_model_variant_shadow_bakeoff",
        "taker_model_variant_shadow_bakeoff_v0.1",
        "weather.market.taker_bot_bakeoff",
        "active",
        "Taker model-variant shadow bakeoff report.",
    ),
    SchemaSpec(
        "taker_profitability_artifact_verification_v0_2",
        "taker_profitability_artifact_verification_v0.2",
        "weather.market.taker_bot_bakeoff",
        "active",
        "Version 0.2 taker profitability artifact verifier emitted by bakeoff reports.",
        supersedes=("taker_profitability_artifact_verification_v0.1",),
    ),
)
