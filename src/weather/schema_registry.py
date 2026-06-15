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
        "toronto_feature_store_v0.7",
        "weather.model.feature_store",
        "active",
        "Shared train/serve feature vector schema.",
        supersedes=("toronto_feature_store_v0.6",),
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
    SchemaSpec("artifact_provenance_manifest", "artifact_provenance_manifest_v0.1", "weather.artifacts", "active"),
    SchemaSpec("calibrated_weights", "calibrated_weights_v0.1", "weather.calibration.intraday_calibration", "active"),
    SchemaSpec("canonical_history_guardrails", "canonical_history_guardrails_v0.1", "weather.sources.canonical_history_guardrails", "active"),
    SchemaSpec("clob_microstructure_overlay", "clob_microstructure_overlay_v0.2", "weather.calibration.pooled_candidate_replay", "active"),
    SchemaSpec("clob_microstructure_taxonomy_gate", "clob_microstructure_taxonomy_gate_v0.1", "weather.calibration.pooled_candidate_replay", "active"),
    SchemaSpec("daily_source_truth", "daily_source_truth_v0.3", "weather.reporting.source_redundancy", "active"),
    SchemaSpec("data_layer_audit", "data_layer_audit_v0.3", "weather.reporting.data_layer_audit", "active"),
    SchemaSpec("disagreement_casebook", "disagreement_casebook_v0.1", "weather.reporting.disagreement_casebook", "active"),
    SchemaSpec("family_secondary_artifacts", "family_secondary_artifacts_v0.1", "weather.calibration.family_secondary_artifacts", "active"),
    SchemaSpec("feature_model_coefs", "feature_model_coefs_v0.1", "weather.calibration.feature_model", "active"),
    SchemaSpec("feature_model_hgb_legacy", "feature_model_hgb_v0.1", "weather.calibration.feature_model", "legacy"),
    SchemaSpec("feature_model_hgb", "feature_model_hgb_v0.2", "weather.calibration.feature_model", "active"),
    SchemaSpec("fleet_collection_health", "fleet_collection_health_v0.1", "weather.collection.collection_health", "active"),
    SchemaSpec("fleet_observability", "fleet_observability_v0.1", "weather.reporting.fleet_observability", "active"),
    SchemaSpec("forecast_daily_legacy", "forecast_daily_legacy_v1", "weather.sources.forecast_history", "legacy"),
    SchemaSpec("forecast_ensemble_features", "forecast_ensemble_features_v0.1", "weather.sources.forecast_history", "active"),
    SchemaSpec("forecast_history_daily_issue", "forecast_history_daily_issue_v1", "weather.sources.forecast_history", "active"),
    SchemaSpec("forecast_history_long", "forecast_history_long_v2", "weather.sources.forecast_history", "active"),
    SchemaSpec("ghcnh_composite_daily_view", "ghcnh_composite_daily_view_v0.1", "weather.sources.noaa_ghcnh_history", "active"),
    SchemaSpec("historical_backfill_plan", "historical_backfill_plan_v1", "weather.collection.historical_backfill_plan", "active"),
    SchemaSpec("historical_backfill_run", "historical_backfill_run_v1", "weather.collection.historical_backfill_runner", "active"),
    SchemaSpec("historical_backfill_status", "historical_backfill_status_v1", "weather.collection.historical_backfill_runner", "active"),
    SchemaSpec("historical_daily_native", "historical_daily_native_v1", "weather.sources.historical_schema", "active"),
    SchemaSpec("historical_data_audit_fleet", "historical_data_audit_fleet_v0.1", "weather.reporting.data_auditor", "active"),
    SchemaSpec("historical_hourly_native", "historical_hourly_native_v1", "weather.sources.historical_schema", "active"),
    SchemaSpec("historical_source_manifest", "historical_source_manifest_v1", "weather.sources.historical_schema", "active"),
    SchemaSpec("ingest_quality_gate", "ingest_quality_gate_v0.1", "weather.operations.daily_refresh", "active"),
    SchemaSpec("late_day_model_coefs", "late_day_model_coefs_v0.1", "weather.calibration.feature_model", "active"),
    SchemaSpec("live_forward_slo", "live_forward_slo_v0.1", "weather.reporting.fleet_observability", "active"),
    SchemaSpec("mm_known_edge_map", "mm_known_edge_map_v0.2", "weather.market.mm_paper", "active"),
    SchemaSpec("mm_negative_risk_simulation", "mm_negative_risk_simulation_v0.1", "weather.market.mm_risk", "active"),
    SchemaSpec("mm_paper", "mm_paper_v0.1", "weather.market.mm_paper", "active"),
    SchemaSpec("mm_policy", "mm_policy_v0.1", "weather.market.mm_policy", "active"),
    SchemaSpec("mm_quote_intent", "mm_quote_intent_v0.1", "weather.market.mm_policy", "active"),
    SchemaSpec("mm_run", "mm_run_v0.2", "weather.market.market_making_run", "active"),
    SchemaSpec("model_artifact_registry", "model_artifact_registry_v0.1", "weather.artifacts", "active"),
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
    SchemaSpec("pooled_feature_band_hgb", "pooled_feature_band_hgb_v0.3", "weather.calibration.pooled_feature_model", "active"),
    SchemaSpec("pooled_feature_hgb", "pooled_feature_hgb_v0.1", "weather.calibration.pooled_feature_model", "legacy"),
    SchemaSpec("progress_audit", "progress_audit_v0.1", "weather.reporting.progress_audit", "active"),
    SchemaSpec("promotion_corpus", "promotion_corpus_v0.1", "weather.reporting.promotion_corpus", "active"),
    SchemaSpec("promotion_refresh", "promotion_refresh_v0.1", "weather.reporting.promotion_refresh", "active"),
    SchemaSpec("runtime_identity", "runtime_identity_v0.1", "weather.operations.runtime_identity", "active"),
    SchemaSpec("snapshot_evaluation", "snapshot_evaluation_v0.1", "weather.reporting.snapshot_evaluation", "active"),
    SchemaSpec("source_redundancy", "source_redundancy_v0.3", "weather.reporting.source_redundancy", "active"),
    SchemaSpec("supplemental_station_registry", "supplemental_station_registry_v0.1", "weather.sources.supplemental_stations", "active"),
    SchemaSpec("supplemental_station_validation", "supplemental_station_validation_v0.1", "weather.sources.supplemental_station_validation", "active"),
    SchemaSpec("distribution_components", "toronto_distribution_components_v0.1", "weather.model.model_distribution", "active"),
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
