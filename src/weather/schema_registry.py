"""Central schema-version registry and migration audit tooling.

The registry is intentionally dependency-free: producer modules import schema
constants from here, while this module never imports producers.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


SCHEMA_REGISTRY_SCHEMA_VERSION = "schema_registry_v0.1"


@dataclass(frozen=True)
class SchemaSpec:
    name: str
    version: str
    owner: str
    status: str
    description: str = ""
    supersedes: tuple[str, ...] = ()
    migration_notes: str = ""


REGISTERED_SCHEMAS = (
    SchemaSpec(
        "schema_registry",
        SCHEMA_REGISTRY_SCHEMA_VERSION,
        "weather.schema_registry",
        "active",
        "Inventory of public artifact schema versions and migration status.",
    ),
    SchemaSpec(
        "feature_store",
        "toronto_feature_store_v1.6",
        "weather.model.feature_store",
        "active",
        "Shared train/serve feature vector schema.",
        supersedes=("toronto_feature_store_v1.5",),
        migration_notes="Predictors must select by trained feature_names, not by newest column order.",
    ),
    SchemaSpec(
        "historical_coverage",
        "historical_coverage_v1",
        "weather.sources.historical_coverage",
        "active",
        "Fleet source-coverage payload across WU, GHCNh, reanalysis, and supplemental sources.",
    ),
    SchemaSpec(
        "historical_coverage_dashboard",
        "historical_coverage_dashboard_v0.1",
        "weather.sources.historical_coverage",
        "active",
        "Flattened historical coverage, gap, and source-freshness SLA dashboard.",
    ),
    SchemaSpec(
        "market_registry",
        "market_registry_v0.1",
        "weather.market.market_registry",
        "active",
        "External market registry overlay schema.",
    ),
    SchemaSpec("marine_context", "marine_context_v0.1", "weather.sources.marine_context", "active"),
    SchemaSpec(
        "wu_daily",
        "wu_daily_native_v2",
        "weather.sources.daily_summary",
        "active",
        "Unit-explicit WU normalized daily summary rows.",
        supersedes=("wu_daily_native_v1",),
    ),
    SchemaSpec(
        "settlement_ledger",
        "settlement_ledger_v1",
        "weather.backtesting.settlement_ledger",
        "active",
        "Frozen settlement labels.",
    ),
    SchemaSpec(
        "resolution_spec",
        "resolution_spec_v1",
        "weather.backtesting.settlement_ledger",
        "active",
        "Per-market resolution rules attached to settlement ledgers.",
    ),
    SchemaSpec(
        "daily_refresh",
        "daily_refresh_v0.4",
        "weather.operations.daily_refresh",
        "active",
        "Daily settlement, promotion, audit, and snapshot-evaluation status artifact.",
    ),
    SchemaSpec(
        "observation_trigger",
        "observation_trigger_v0.1",
        "weather.operations.observation_trigger",
        "active",
        "Fast observation-trigger watcher status and event schema.",
    ),
    SchemaSpec(
        "observation_trigger_replay",
        "observation_trigger_replay_v0.1",
        "weather.operations.observation_trigger",
        "active",
        "Triggered-row replay comparison artifact.",
    ),
    SchemaSpec("adjacent_market_hour_floor_gap", "adjacent_market_hour_floor_gap_v1", "weather.calibration.pooled_feature_model", "active"),
    SchemaSpec("asos_1min", "asos_1min_v0.1", "weather.sources.asos_one_minute", "active"),
    SchemaSpec("artifact_provenance_manifest", "artifact_provenance_manifest_v0.1", "weather.artifacts", "active"),
    SchemaSpec("calibrated_weights", "calibrated_weights_v0.1", "weather.calibration.intraday_calibration", "active"),
    SchemaSpec(
        "blocked_validation",
        "blocked_validation_v0.1",
        "weather.calibration.blocked_validation",
        "active",
        "Leakage-audit summary for market-day and blocked-date validation splits.",
    ),
    SchemaSpec(
        "blocked_candidate_validation_gate",
        "blocked_candidate_validation_gate_v0.1",
        "weather.calibration.pooled_candidate_scoring",
        "active",
        "Promotion gate requiring daily-first blocked candidate validation.",
    ),
    SchemaSpec("canonical_history_guardrails", "canonical_history_guardrails_v0.1", "weather.sources.canonical_history_guardrails", "active"),
    SchemaSpec("clob_microstructure_overlay", "clob_microstructure_overlay_v0.2", "weather.calibration.pooled_candidate_replay", "active"),
    SchemaSpec(
        "clob_book_recon",
        "clob_book_recon_v0.1",
        "weather.market.clob_recon",
        "active",
        "Offline CLOB book recon, reward competition, executable depth, and passive-flow toxicity artifact.",
    ),
    SchemaSpec("clob_microstructure_taxonomy_gate", "clob_microstructure_taxonomy_gate_v0.1", "weather.calibration.pooled_candidate_replay", "active"),
    SchemaSpec("conservative_bridge_policy", "conservative_bridge_policy_v0.1", "weather.calibration.pooled_candidate_replay", "active"),
    SchemaSpec(
        "cross_hub_readiness",
        "cross_hub_readiness_v0.1",
        "weather.reporting.cross_hub_readiness",
        "active",
        "Per-market readiness labels that separate source redundancy, trust, model edge, quoteability, and live-forward plumbing.",
    ),
    SchemaSpec(
        "source_state_ablation",
        "source_state_ablation_v0.1",
        "weather.calibration.pooled_candidate_scoring",
        "active",
        "Shadow-variant ablation comparing no-source-state serving control with dynamic source-state candidate probabilities.",
    ),
    SchemaSpec(
        "source_family_ablation",
        "source_family_ablation_v0.1",
        "weather.backtesting.replay_ablation",
        "active",
        "Settlement-scored source-family knockout replay artifact used by input promotion preflight.",
    ),
    SchemaSpec(
        "source_family_inventory",
        "source_family_inventory_v0.1",
        "weather.reporting.source_family_inventory",
        "active",
        "Weather-input family inventory with lineage, train/serve parity, ablation, missingness, and promotion decisions.",
    ),
    SchemaSpec("daily_source_truth", "daily_source_truth_v0.3", "weather.reporting.source_redundancy", "active"),
    SchemaSpec("data_layer_audit", "data_layer_audit_v0.3", "weather.reporting.data_layer_audit", "active"),
    SchemaSpec(
        "daily_learning",
        "daily_learning_v0.1",
        "weather.reporting.daily_learning",
        "active",
        "Daily distilled log-learning artifact for retrain and promotion decisions.",
    ),
    SchemaSpec("disagreement_casebook", "disagreement_casebook_v0.1", "weather.reporting.disagreement_casebook", "active"),
    SchemaSpec("eccc_gridded", "eccc_gridded_v0.1", "weather.sources.eccc_gridded", "active"),
    SchemaSpec("family_secondary_artifacts", "family_secondary_artifacts_v0.1", "weather.calibration.family_secondary_artifacts", "active"),
    SchemaSpec("feature_model_coefs", "feature_model_coefs_v0.1", "weather.calibration.feature_model", "active"),
    SchemaSpec("feature_model_hgb_legacy", "feature_model_hgb_v0.1", "weather.calibration.feature_model", "legacy"),
    SchemaSpec("feature_model_hgb", "feature_model_hgb_v0.2", "weather.calibration.feature_model", "active"),
    SchemaSpec("item27_feature_value_gate", "item27_feature_value_gate_v0.1", "weather.calibration.feature_model", "active"),
    SchemaSpec("fleet_collection_health", "fleet_collection_health_v0.1", "weather.collection.collection_health", "active"),
    SchemaSpec("fleet_observability", "fleet_observability_v0.1", "weather.reporting.fleet_observability", "active"),
    SchemaSpec("forecast_daily_legacy", "forecast_daily_legacy_v1", "weather.sources.forecast_history", "legacy"),
    SchemaSpec("forecast_ensemble_features", "forecast_ensemble_features_v0.1", "weather.sources.forecast_history", "active"),
    SchemaSpec(
        "forecast_history_coverage",
        "forecast_history_coverage_v0.1",
        "weather.sources.forecast_history",
        "active",
        "Fleet coverage payload for rich Open-Meteo forecast-history archives.",
    ),
    SchemaSpec("forecast_history_daily_issue", "forecast_history_daily_issue_v1", "weather.sources.forecast_history", "active"),
    SchemaSpec("forecast_history_long_legacy", "forecast_history_long_v2", "weather.sources.forecast_history", "legacy"),
    SchemaSpec(
        "forecast_history_long",
        "forecast_history_long_v3",
        "weather.sources.forecast_history",
        "active",
        supersedes=("forecast_history_long_v2",),
        migration_notes="Adds expanded rich hourly forecast fields for previous-run forecast history.",
    ),
    SchemaSpec("grib_probe", "grib_probe_v0.1", "weather.sources.grib_probe", "active"),
    SchemaSpec("ghcnh_composite_daily_view", "ghcnh_composite_daily_view_v0.1", "weather.sources.noaa_ghcnh_history", "active"),
    SchemaSpec("historical_backfill_plan", "historical_backfill_plan_v1", "weather.collection.historical_backfill_plan", "active"),
    SchemaSpec("historical_backfill_run", "historical_backfill_run_v1", "weather.collection.historical_backfill_runner", "active"),
    SchemaSpec("historical_backfill_status", "historical_backfill_status_v1", "weather.collection.historical_backfill_runner", "active"),
    SchemaSpec("historical_fallbacks", "historical_fallbacks_v0.1", "weather.sources.historical_fallbacks", "active"),
    SchemaSpec("historical_daily_native", "historical_daily_native_v1", "weather.sources.historical_schema", "active"),
    SchemaSpec("historical_data_audit_fleet", "historical_data_audit_fleet_v0.1", "weather.reporting.data_auditor", "active"),
    SchemaSpec("historical_hourly_native", "historical_hourly_native_v1", "weather.sources.historical_schema", "active"),
    SchemaSpec("historical_source_manifest", "historical_source_manifest_v1", "weather.sources.historical_schema", "active"),
    SchemaSpec("ingest_quality_gate", "ingest_quality_gate_v0.1", "weather.operations.daily_refresh", "active"),
    SchemaSpec("late_day_model_coefs", "late_day_model_coefs_v0.1", "weather.calibration.feature_model", "active"),
    SchemaSpec("live_forward_slo", "live_forward_slo_v0.1", "weather.reporting.fleet_observability", "active"),
    SchemaSpec(
        "live_source_status_cases",
        "live_source_status_cases_v0.1",
        "weather.reporting.source_redundancy",
        "active",
        "Generated cases explaining live source freshness, failure, and stale-source status.",
    ),
    SchemaSpec(
        "info_event_calendar",
        "info_event_calendar_v0.1",
        "weather.market.info_event_calendar",
        "active",
        "Per-market scheduled information-event calendar and quote-pull gate state.",
    ),
    SchemaSpec("mm_known_edge_map", "mm_known_edge_map_v0.2", "weather.market.mm_paper", "active"),
    SchemaSpec("mm_known_edge_map_legacy", "mm_known_edge_map_v0.1", "weather.market.mm_paper", "legacy"),
    SchemaSpec(
        "mm_exchange_adapter",
        "mm_exchange_adapter_v0.1",
        "weather.market.mm_exchange",
        "active",
        "Keyless exchange-adapter diagnostics, live-gate checks, and reconciliation artifact.",
    ),
    SchemaSpec("mm_negative_risk_simulation", "mm_negative_risk_simulation_v0.1", "weather.market.mm_risk", "active"),
    SchemaSpec("mm_paper", "mm_paper_v0.1", "weather.market.mm_paper", "active"),
    SchemaSpec(
        "mm_platform_verification",
        "mm_platform_verification_v0.1",
        "weather.market.market_making_run",
        "active",
        "Live-pilot platform, account, wallet, fee, reward, and API-semantics verification evidence.",
    ),
    SchemaSpec("mm_policy", "mm_policy_v0.2", "weather.market.mm_policy", "active", supersedes=("mm_policy_v0.1",)),
    SchemaSpec("mm_policy_legacy", "mm_policy_v0.1", "weather.market.mm_policy", "legacy"),
    SchemaSpec("mm_quote_intent", "mm_quote_intent_v0.2", "weather.market.mm_policy", "active", supersedes=("mm_quote_intent_v0.1",)),
    SchemaSpec("mm_quote_intent_legacy", "mm_quote_intent_v0.1", "weather.market.mm_policy", "legacy"),
    SchemaSpec("mm_run", "mm_run_v0.2", "weather.market.market_making_run", "active"),
    SchemaSpec("mm_run_legacy", "mm_run_v0.1", "weather.market.market_making_run", "legacy", supersedes=()),
    SchemaSpec(
        "live_forward_gate",
        "live_forward_gate_v0.2",
        "weather.market.live_forward_gate",
        "active",
        "Live-forward countability gate with evidence-mode adjustment fields.",
        supersedes=("live_forward_gate_v0.1",),
    ),
    SchemaSpec("live_forward_gate_legacy", "live_forward_gate_v0.1", "weather.market.live_forward_gate", "legacy"),
    SchemaSpec("mrms_precip", "mrms_precip_v0.1", "weather.sources.mrms_precip", "active"),
    SchemaSpec(
        "toronto_official_source_health",
        "toronto_official_source_health_v0.1",
        "weather.model.model_sources",
        "active",
        "Toronto official-source health artifact for ECCC runtime hardening and fallback diagnostics.",
    ),
    SchemaSpec(
        "reanalysis_synoptic_features",
        "reanalysis_synoptic_features_v0.3",
        "weather.sources.reanalysis_synoptic",
        "active",
        "Gated ERA5/reanalysis antecedent-state, soil, cloud, radiation, pressure, pressure-level, teleconnection, and static city-context feature sidecar.",
        supersedes=("reanalysis_synoptic_features_v0.2",),
    ),
    SchemaSpec("model_artifact_registry", "model_artifact_registry_v0.1", "weather.artifacts", "active"),
    SchemaSpec("model_variant_registry", "model_variant_registry_v0.1", "weather.reporting.variant_registry", "active"),
    SchemaSpec("model_variant_evidence_growth", "model_variant_evidence_growth_v0.1", "weather.reporting.variant_evidence_growth", "active"),
    SchemaSpec(
        "independent_evidence_sla",
        "independent_evidence_sla_v0.1",
        "weather.reporting.variant_evidence_growth",
        "active",
        "Independent settled-evidence growth and sample-SLA artifact for variant evaluation.",
    ),
    SchemaSpec("nightly_retrain", "nightly_retrain_v0.1", "weather.operations.nightly_retrain", "active"),
    SchemaSpec(
        "settled_day_freshness",
        "settled_day_freshness_v0.1",
        "weather.operations.settled_day_freshness",
        "active",
        "Freshness and repair artifact for newly settled market-day labels, ledgers, and folder-local settlement copies.",
    ),
    SchemaSpec(
        "nightly_retrain_sla_status",
        "nightly_retrain_sla_status_v0.1",
        "weather.operations.nightly_retrain",
        "active",
    ),
    SchemaSpec(
        "loop_artifact_integrity",
        "loop_artifact_integrity_v0.1",
        "weather.reporting.fleet_observability",
        "active",
    ),
    SchemaSpec(
        "loop_jsonl_repair",
        "loop_jsonl_repair_v0.1",
        "weather.operations.loop_jsonl_repair",
        "active",
        "Audit and quarantine artifact for malformed loop JSONL/log lines.",
    ),
    SchemaSpec(
        "model_history_cache_legacy",
        "model_history_cache_v0.1",
        "weather.reporting.model_history",
        "legacy",
    ),
    SchemaSpec(
        "model_history_cache",
        "model_history_cache_v0.2",
        "weather.reporting.model_history",
        "active",
        supersedes=("model_history_cache_v0.1",),
        migration_notes="Adds winner-band catch-up diagnostics by location, day, and location-hour.",
    ),
    SchemaSpec("multi_variant_shadow", "multi_variant_shadow_v0.1", "weather.reporting.multi_variant_shadow", "active"),
    SchemaSpec("pooled_feature_band_hgb_exact_winner", "pooled_feature_band_hgb_v0.4", "weather.calibration.pooled_feature_model", "active"),
    SchemaSpec("pooled_feature_band_hgb_dynamic_source", "pooled_feature_band_hgb_v0.5", "weather.calibration.pooled_feature_model", "active"),
    SchemaSpec("pooled_feature_band_hgb", "pooled_feature_band_hgb_v0.3", "weather.calibration.pooled_feature_model", "active"),
    SchemaSpec(
        "pooled_continuous_density_hgb",
        "pooled_continuous_density_hgb_v0.2",
        "weather.calibration.pooled_feature_model",
        "active",
        "All-market canonical-F continuous-density candidate artifact with holdout-residual sigma.",
        supersedes=("pooled_continuous_density_hgb_v0.1",),
    ),
    SchemaSpec("pooled_continuous_density_hgb_legacy", "pooled_continuous_density_hgb_v0.1", "weather.calibration.pooled_feature_model", "legacy"),
    SchemaSpec("pooled_feature_hgb", "pooled_feature_hgb_v0.1", "weather.calibration.pooled_feature_model", "legacy"),
    SchemaSpec("progress_audit", "progress_audit_v0.1", "weather.reporting.progress_audit", "active"),
    SchemaSpec(
        "core_model_trend_claim",
        "core_model_trend_claim_v0.1",
        "weather.reporting.progress_audit",
        "active",
        "Core model day-over-day skill trend claim and evidence gate artifact.",
    ),
    SchemaSpec("promotion_corpus", "promotion_corpus_v0.1", "weather.reporting.promotion_corpus", "active"),
    SchemaSpec("promotion_refresh", "promotion_refresh_v0.1", "weather.reporting.promotion_refresh", "active"),
    SchemaSpec(
        "market_skill_gap_experiment",
        "market_skill_gap_experiment_v0.1",
        "weather.reporting.promotion_refresh",
        "active",
        "Per-market skill-gap experiment ownership artifact emitted by promotion refresh.",
    ),
    SchemaSpec("runtime_identity", "runtime_identity_v0.1", "weather.operations.runtime_identity", "active"),
    SchemaSpec("long_job_guard", "long_job_guard_v0.1", "weather.operations.long_job_guard", "active"),
    SchemaSpec(
        "replay_input_status",
        "replay_input_status_v0.1",
        "weather.backtesting.replay",
        "active",
        "Status payload describing reconstructed replay inputs and missing replay material.",
    ),
    SchemaSpec(
        "replay_status_backfill",
        "replay_status_backfill_v0.1",
        "weather.operations.replay_status_backfill",
        "active",
        "Repair-command artifact for settled-day replay status backfills.",
    ),
    SchemaSpec(
        "market_making_daily_roll",
        "market_making_daily_roll_v0.2",
        "weather.operations.market_making_daily_roll",
        "active",
        "Daily launcher status for paper-live-forward market-making runs with evidence-mode classification.",
        supersedes=("market_making_daily_roll_v0.1",),
    ),
    SchemaSpec(
        "market_making_daily_roll_legacy",
        "market_making_daily_roll_v0.1",
        "weather.operations.market_making_daily_roll",
        "legacy",
        "Legacy daily launcher status before evidence-mode classification.",
    ),
    SchemaSpec(
        "market_making_tape_encoding",
        "market_making_tape_encoding_v0.1",
        "weather.operations.market_making_tape_encoding",
        "active",
        "Audit and repair artifact for legacy non-UTF-8 market-making and CLOB CSV tapes.",
    ),
    SchemaSpec(
        "tape_backup_manifest",
        "tape_backup_manifest_v0.1",
        "weather.operations.tape_backup",
        "active",
        "Checksum manifest for irreplaceable raw/live evidence tape backups.",
    ),
    SchemaSpec(
        "tape_retention_policy",
        "tape_retention_policy_v0.1",
        "weather.operations.tape_backup",
        "active",
        "Recoverability classes and retention rules for backup manifests.",
    ),
    SchemaSpec(
        "tape_restore_drill",
        "tape_restore_drill_v0.1",
        "weather.operations.tape_backup",
        "active",
        "Restore-drill result for verifying backup hashes, schemas, and tape counts.",
    ),
    SchemaSpec(
        "tape_backup_job",
        "tape_backup_job_v0.1",
        "weather.operations.tape_backup",
        "active",
        "Single tape-backup job status emitted by backup orchestration.",
    ),
    SchemaSpec("shadow_ab_monitor", "shadow_ab_monitor_v0.1", "weather.reporting.shadow_ab_monitor", "active"),
    SchemaSpec("snapshot_evaluation", "snapshot_evaluation_v0.1", "weather.reporting.snapshot_evaluation", "active"),
    SchemaSpec(
        "late_day_warm_side_cases",
        "late_day_warm_side_cases_v0.1",
        "weather.reporting.disagreement_casebook",
        "active",
        "Late-day warm-side disagreement casebook slice artifact.",
    ),
    SchemaSpec("source_redundancy", "source_redundancy_v0.3", "weather.reporting.source_redundancy", "active"),
    SchemaSpec("supplemental_station_registry", "supplemental_station_registry_v0.1", "weather.sources.supplemental_stations", "active"),
    SchemaSpec("supplemental_station_validation", "supplemental_station_validation_v0.1", "weather.sources.supplemental_station_validation", "active"),
    SchemaSpec("distribution_components", "toronto_distribution_components_v0.1", "weather.model.model_distribution", "active"),
    SchemaSpec("reanalysis_synoptic_features_legacy_v0_2", "reanalysis_synoptic_features_v0.2", "weather.sources.reanalysis_synoptic", "legacy"),
    SchemaSpec("reanalysis_synoptic_features_legacy", "reanalysis_synoptic_features_v0.1", "weather.sources.reanalysis_synoptic", "legacy"),
    SchemaSpec("feature_store_legacy_v1_5", "toronto_feature_store_v1.5", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_4", "toronto_feature_store_v1.4", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_2", "toronto_feature_store_v1.2", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_3", "toronto_feature_store_v1.3", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_1", "toronto_feature_store_v1.1", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v1_0", "toronto_feature_store_v1.0", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v0_9", "toronto_feature_store_v0.9", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v0_8", "toronto_feature_store_v0.8", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v0_7", "toronto_feature_store_v0.7", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy", "toronto_feature_store_v0.6", "weather.model.feature_store", "legacy"),
    SchemaSpec("feature_store_legacy_v0_5", "toronto_feature_store_v0.5", "weather.model.feature_store", "legacy"),
    SchemaSpec("replay_inputs_reconstructed", "toronto_replay_inputs_reconstructed_v0.1", "weather.backtesting.replay", "active"),
    SchemaSpec("replay_inputs", "toronto_replay_inputs_v0.1", "weather.collection.snapshot_tracker", "active"),
    SchemaSpec("weather_model_replay_identity", "weather_model_replay_identity_v0.1", "weather.model.model_identity", "active"),
    SchemaSpec("wu_daily_legacy", "wu_daily_native_v1", "weather.sources.daily_summary", "legacy"),
    SchemaSpec("wu_hourly", "wu_hourly_native_v1", "weather.sources.wu_history", "active"),
    SchemaSpec("wu_max_since_7_validation", "wu_max_since_7_validation_v0.1", "weather.reporting.wu_max_since_7_validation", "active"),
)

SCHEMAS_BY_NAME = {spec.name: spec for spec in REGISTERED_SCHEMAS}
SCHEMAS_BY_VERSION = {spec.version: spec for spec in REGISTERED_SCHEMAS}

SCHEMA_LITERAL_RE = re.compile(
    r"""['"]([a-z][a-z0-9]*(?:_[a-z0-9]+)*_v\d+(?:\.\d+)?|toronto_feature_store_v\d+(?:\.\d+)?)['"]"""
)
DEFAULT_SCAN_SUFFIXES = {".py"}
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "artifacts",
    "data",
    "node_modules",
    "venv",
}


def schema_version(name: str) -> str:
    """Return the active schema version for a registered schema name."""
    try:
        return SCHEMAS_BY_NAME[name].version
    except KeyError as exc:
        raise KeyError(f"unknown schema registry name: {name}") from exc


def registered_schema(name: str) -> dict:
    return asdict(SCHEMAS_BY_NAME[name])


def registry_payload() -> dict:
    return {
        "schema_version": SCHEMA_REGISTRY_SCHEMA_VERSION,
        "schemas": [asdict(spec) for spec in REGISTERED_SCHEMAS],
    }


def validate_schema_version(name: str, version: str) -> bool:
    return schema_version(name) == version


def _iter_scan_files(paths, suffixes=DEFAULT_SCAN_SUFFIXES):
    for item in paths:
        path = Path(item)
        if not path.exists():
            continue
        if path.is_file():
            if path.suffix in suffixes:
                yield path
            continue
        for child in path.rglob("*"):
            if any(part in DEFAULT_IGNORE_DIRS for part in child.parts):
                continue
            if child.is_file() and child.suffix in suffixes:
                yield child


def scan_schema_literals(paths=("src",), suffixes=DEFAULT_SCAN_SUFFIXES):
    """Find schema-looking string literals in source files."""
    rows = []
    for path in sorted(set(_iter_scan_files(paths, suffixes=suffixes))):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            for match in SCHEMA_LITERAL_RE.finditer(line):
                version = match.group(1)
                spec = SCHEMAS_BY_VERSION.get(version)
                rows.append({
                    "path": str(path),
                    "line": line_no,
                    "version": version,
                    "registered": spec is not None,
                    "schema_name": spec.name if spec else None,
                })
    return rows


def audit_payload(paths=("src",)) -> dict:
    discovered = scan_schema_literals(paths)
    unregistered_versions = sorted({
        row["version"] for row in discovered if not row["registered"]
    })
    return {
        "schema_version": SCHEMA_REGISTRY_SCHEMA_VERSION,
        "registered_count": len(REGISTERED_SCHEMAS),
        "discovered_literal_count": len(discovered),
        "unregistered_version_count": len(unregistered_versions),
        "registered_schemas": [asdict(spec) for spec in REGISTERED_SCHEMAS],
        "unregistered_versions": unregistered_versions,
        "discovered_literals": discovered,
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_list(args):
    payload = registry_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for spec in REGISTERED_SCHEMAS:
        print(f"{spec.name}: {spec.version} ({spec.status})")


def cmd_audit(args):
    payload = audit_payload(args.paths)
    if args.out:
        write_json(args.out, payload)
        print(f"Wrote schema registry audit to {args.out}")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    print(
        "registered={registered_count} discovered={discovered_literal_count} "
        "unregistered_versions={unregistered_version_count}".format(**payload)
    )
    if args.strict and payload["unregistered_version_count"]:
        raise SystemExit(1)


def build_parser():
    parser = argparse.ArgumentParser(description="Schema registry and migration audit tooling.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    audit_cmd = sub.add_parser("audit")
    audit_cmd.add_argument("--paths", nargs="+", default=["src"])
    audit_cmd.add_argument("--out", default="")
    audit_cmd.add_argument("--strict", action="store_true")
    audit_cmd.set_defaults(func=cmd_audit)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
