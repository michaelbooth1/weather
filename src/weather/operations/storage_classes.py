"""Shared storage-class contract for durable data and log artifacts."""

from __future__ import annotations

import fnmatch
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CANONICAL_EVIDENCE = "canonical_evidence"
ANALYSIS_PROJECTION = "analysis_projection"
OPERATOR_CACHE = "operator_cache"
UNCLASSIFIED = "unclassified"

STORAGE_CLASSES = (CANONICAL_EVIDENCE, ANALYSIS_PROJECTION, OPERATOR_CACHE)


@dataclass(frozen=True)
class StorageClassContract:
    name: str
    description: str
    allowed_formats: tuple[str, ...]
    retention_default: str
    protection_requirement: str
    deletion_prerequisite: str


@dataclass(frozen=True)
class ArtifactFamilyClassification:
    artifact_family: str
    owner: str
    storage_class: str
    patterns: tuple[str, ...]
    retention_class: str
    rebuild_source: str
    delete_gate: str
    protected: bool
    durable: bool = True
    examples: tuple[str, ...] = ()
    notes: str = ""


STORAGE_CLASS_CONTRACTS = (
    StorageClassContract(
        CANONICAL_EVIDENCE,
        "Append-only or source-of-truth evidence that cannot be safely rebuilt after the fact.",
        ("jsonl", "json", "csv", "raw", "csv.gz"),
        "Permanent archive; local copies stay until a reviewed cleanup manifest exists.",
        "Must be named by a reviewed cleanup manifest before local deletion.",
        "Reviewed cleanup manifest with exact path, class, reason, operator, and checksum.",
    ),
    StorageClassContract(
        ANALYSIS_PROJECTION,
        "Derived tables or partitions built from canonical evidence for fast analysis.",
        ("parquet", "csv", "csv.gz", "json", "sqlite3"),
        "Keep while actively queried; local copies may be rebuilt from named canonical evidence.",
        "Projection cleanup must name its rebuild source.",
        "Reviewed cleanup manifest plus current rebuild source.",
    ),
    StorageClassContract(
        OPERATOR_CACHE,
        "Reports, dashboards, status files, logs, provider caches, and local workflow outputs.",
        ("md", "html", "json", "csv", "log", "txt"),
        "TTL or cleanup-manifest driven, except incident-linked operator evidence.",
        "Archive only incident-linked or explicitly pinned operator evidence.",
        "TTL expiry or reviewed cleanup manifest; never use raw directory size alone.",
    ),
)

CONTRACTS_BY_CLASS = {contract.name: contract for contract in STORAGE_CLASS_CONTRACTS}


ARTIFACT_FAMILIES = (
    ArtifactFamilyClassification(
        "shared_forecast_payload_cas",
        "collection/sources",
        CANONICAL_EVIDENCE,
        ("forecast_payload_cas/**/*.blob",),
        "permanent_shared_forecast_source_evidence",
        "not rebuildable with the original provider bytes and point-in-time per-market manifests",
        "shared_forecast_payload_gc_disabled",
        True,
        examples=(
            "data/forecast_payload_cas/sha256/<prefix>/<sha256>.blob",
        ),
        notes="Reachability is global across per-market manifests; never infer orphan status from one event folder.",
    ),
    ArtifactFamilyClassification(
        "observation_payload_evidence",
        "collection/sources",
        CANONICAL_EVIDENCE,
        (
            "snapshots/*/observation_payloads.jsonl",
            "snapshots/*/observation_payloads/*.json",
            "snapshots/*/observation_payloads/**/*.json",
        ),
        "permanent_first_seen_observation_payloads",
        "not rebuildable with the original provider response, first-seen time, and parser state",
        "canonical_evidence_review_gate",
        True,
        examples=(
            "data/snapshots/<event>/observation_payloads.jsonl",
            "data/snapshots/<event>/observation_payloads/<snapshot>_<source>_<hash>.json",
        ),
        notes="Settlement and PIT evidence; must be covered by event manifests, backup, and restore proof.",
    ),
    ArtifactFamilyClassification(
        "clob_capture_status_evidence",
        "market",
        CANONICAL_EVIDENCE,
        (
            "snapshots/*/clob_capture_status.jsonl",
            "snapshots/*/clob_capture_status*.jsonl",
        ),
        "permanent_clob_capture_health_tape",
        "not rebuildable; records whether a live capture succeeded, failed, or returned no usable market state",
        "canonical_evidence_review_gate",
        True,
        examples=("data/snapshots/<event>/clob_capture_status.jsonl",),
        notes="A named failure is valid evidence; an absent status tape is not.",
    ),
    ArtifactFamilyClassification(
        "snapshot_jsonl_evidence",
        "collection/model/market",
        CANONICAL_EVIDENCE,
        (
            "snapshots/*/snapshots*.jsonl",
            "snapshots/*/features*.jsonl",
            "snapshots/*/components*.jsonl",
            "snapshots/*/forecasts*.jsonl",
            "snapshots/*/source_status*.jsonl",
            "snapshots/*/forecast_payloads*.jsonl",
            "snapshots/*/forecast_payloads/**/*.json",
            "snapshots/*/snapshot_explanations.jsonl",
            "snapshots/*/variant_predictions.jsonl",
            "snapshots/*/live_variant_predictions.jsonl",
            "snapshots/diagnostics.jsonl",
            "snapshots/observation_trigger*.json",
            "snapshots/observation_trigger*.jsonl",
            "snapshots/observation_triggers.jsonl",
            "snapshots/*/observation_trigger*.jsonl",
        ),
        "permanent_live_snapshot_tape",
        "not rebuildable from providers with the same live timing and source state",
        "canonical_evidence_review_gate",
        True,
        examples=(
            "data/snapshots/<event>/snapshots.jsonl",
            "data/snapshots/<event>/features.jsonl",
            "data/snapshots/<event>/snapshot_explanations.jsonl",
            "data/snapshots/<event>/variant_predictions.jsonl",
        ),
    ),
    ArtifactFamilyClassification(
        "replay_inputs",
        "backtesting/collection",
        CANONICAL_EVIDENCE,
        (
            "snapshots/*/replay_inputs.jsonl",
            "snapshots/*/replay_inputs_reconstructed.jsonl",
            "snapshots/*/replay_input_status.json",
        ),
        "permanent_replay_contract",
        "not safely rebuildable without the original snapshot/source-status payloads",
        "canonical_evidence_review_gate",
        True,
        examples=("data/snapshots/<event>/replay_inputs.jsonl",),
    ),
    ArtifactFamilyClassification(
        "clob_raw_evidence",
        "market",
        CANONICAL_EVIDENCE,
        (
            "snapshots/clob*.json",
            "snapshots/clob*.jsonl",
            "snapshots/*/clob_tokens.jsonl",
            "snapshots/*/order_books.jsonl",
            "snapshots/*/price_history.jsonl",
            "snapshots/*/price_history_raw_manifest.jsonl",
            "snapshots/*/price_history_raw/**/*.json",
            "snapshots/*/price_history_raw/*.json",
            "snapshots/*/market_ws.jsonl",
        ),
        "permanent_clob_source_evidence",
        "not rebuildable; CLOB book, price, and websocket state is live-only",
        "canonical_evidence_review_gate",
        True,
        examples=("data/snapshots/<event>/order_books.jsonl", "data/snapshots/<event>/market_ws.jsonl"),
    ),
    ArtifactFamilyClassification(
        "clob_token_map",
        "market",
        CANONICAL_EVIDENCE,
        ("snapshots/*/clob_tokens.csv",),
        "permanent_clob_join_key",
        "not rebuildable without the original Gamma/CLOB token mapping",
        "canonical_evidence_review_gate",
        True,
        examples=("data/snapshots/<event>/clob_tokens.csv",),
    ),
    ArtifactFamilyClassification(
        "settlement_ledgers",
        "backtesting/market",
        CANONICAL_EVIDENCE,
        (
            "settlements/**",
            "backtest/market_day_labels.csv",
            "backtest/*settlement*.json",
            "backtest/*settlement*.csv",
            "snapshots/*/settlement.json",
            "snapshots/*/settlement*.jsonl",
            "snapshots/*/settlement*.csv",
        ),
        "permanent_settlement_label_evidence",
        "not safely rebuildable without source history and manual overrides",
        "canonical_evidence_review_gate",
        True,
        examples=("data/settlements/<market>.jsonl", "data/backtest/market_day_labels.csv"),
    ),
    ArtifactFamilyClassification(
        "market_making_lifecycle_risk",
        "market",
        CANONICAL_EVIDENCE,
        (
            "mm_runs/**/*.jsonl",
            "mm_runs/**/*order*",
            "mm_runs/**/*lifecycle*",
            "mm_runs/**/*risk*",
            "mm_runs/**/*budget*",
            "mm_runs/**/*remediation*",
            "snapshots/*/mm_runs/**/*.jsonl",
            "snapshots/*/mm_runs/**/*order*",
            "snapshots/*/mm_runs/**/*lifecycle*",
            "snapshots/*/mm_runs/**/*risk*",
            "snapshots/*/mm_runs/**/*budget*",
            "snapshots/*/mm_runs/**/*remediation*",
            "snapshots/*/market_making/**/*.jsonl",
            "snapshots/*/paper_trading/**/*.jsonl",
        ),
        "permanent_live_forward_market_making_evidence",
        "not rebuildable because quote, fill, risk, and markout timing is live-only",
        "canonical_evidence_review_gate",
        True,
        examples=("data/mm_runs/<run>/order_lifecycle.jsonl", "data/mm_runs/<run>/risk_events.jsonl"),
    ),
    ArtifactFamilyClassification(
        "taker_run_evidence",
        "market",
        CANONICAL_EVIDENCE,
        (
            "taker_runs/**/*.jsonl",
            "taker_runs/**/*.json",
            "taker_runs/**/*.csv",
            "snapshots/*/taker_runs/**/*.jsonl",
            "snapshots/*/taker_runs/**/*.json",
            "snapshots/*/taker_runs/**/*.csv",
        ),
        "permanent_taker_strategy_evidence",
        "not rebuildable because fills, account snapshots, and decisions are live-only",
        "canonical_evidence_review_gate",
        True,
        examples=("data/taker_runs/<run>/orders.jsonl",),
    ),
    ArtifactFamilyClassification(
        "taker_incremental_checkpoint",
        "market",
        ANALYSIS_PROJECTION,
        (
            "taker_runs/**/incremental_state.sqlite3",
            "taker_runs/**/incremental_state.sqlite3-*",
            "snapshots/*/taker_runs/**/incremental_state.sqlite3",
            "snapshots/*/taker_runs/**/incremental_state.sqlite3-*",
        ),
        "rebuildable_taker_incremental_index",
        "append-only taker orders and counterfactual CSV tapes",
        "projection_rebuild_source_gate",
        False,
        examples=("data/taker_runs/<date>/<run>/incremental_state.sqlite3",),
        notes="Intent index and cumulative checkpoint; CSV tapes remain canonical evidence.",
    ),
    ArtifactFamilyClassification(
        "historical_source_rows",
        "sources",
        CANONICAL_EVIDENCE,
        (
            "wunderground/**",
            "metar/**",
            "asos/**",
            "ghcnh/**",
            "noaa_ghcnh/**",
            "power/**",
            "nasa_power/**",
            "meteostat/**",
            "eccc/**",
            "eccc_swob/**",
        ),
        "source_history_with_provenance",
        "partially backfillable, but canonical settled-source provenance is not assumed rebuildable",
        "canonical_evidence_review_gate",
        True,
        examples=("data/wunderground/<station>/daily.csv", "data/eccc_swob/<station>/manifest.json"),
    ),
    ArtifactFamilyClassification(
        "promotion_corpora_and_decisions",
        "reporting/calibration",
        CANONICAL_EVIDENCE,
        (
            "backtest/promotion_corpus*.json",
            "backtest/*promotion_refresh*.json",
            "backtest/*promotion_gauntlet*.json",
            "backtest/*promotion_replay*.json",
            "backtest/location_trust.json",
            "backtest/*known_edge*.json",
        ),
        "pinned_promotion_evidence",
        "not equivalent if regenerated after model, source, or market state changes",
        "canonical_evidence_review_gate",
        True,
        examples=("data/backtest/promotion_corpus.json", "data/backtest/location_trust.json"),
    ),
    ArtifactFamilyClassification(
        "observation_payload_projection",
        "collection/sources",
        ANALYSIS_PROJECTION,
        (
            "snapshots/*/observation_payloads*.csv",
            "snapshots/*/observation_payloads*.csv.gz",
        ),
        "rebuildable_observation_payload_projection",
        "observation_payload_evidence",
        "projection_rebuild_source_gate",
        False,
        examples=("data/snapshots/<event>/observation_payloads_long.csv",),
    ),
    ArtifactFamilyClassification(
        "snapshot_csv_long_tables",
        "collection/model/market",
        ANALYSIS_PROJECTION,
        (
            "snapshots/*/snapshots*.csv",
            "snapshots/*/features*.csv",
            "snapshots/*/components*.csv",
            "snapshots/*/forecasts*.csv",
            "snapshots/*/source_status*.csv",
            "snapshots/*/forecast_payloads*.csv",
            "snapshots/*/*_long.csv",
            "snapshots/*/*_long.csv.gz",
        ),
        "rebuildable_snapshot_projection",
        "snapshot_jsonl_evidence",
        "projection_rebuild_source_gate",
        False,
        examples=("data/snapshots/<event>/snapshots_long.csv", "data/snapshots/<event>/features_long.csv"),
    ),
    ArtifactFamilyClassification(
        "clob_analysis_tables",
        "market",
        ANALYSIS_PROJECTION,
        (
            "snapshots/*/order_books_summary.csv",
            "snapshots/*/order_books_long.csv",
            "snapshots/*/order_books_long.csv.gz",
            "snapshots/*/price_history.csv",
            "snapshots/*/price_history_deduped.csv",
            "snapshots/*/market_ws_events.csv",
            "snapshots/*/clob_features*.csv",
            "snapshots/*/clob_features*.jsonl",
        ),
        "rebuildable_clob_projection",
        "clob_raw_evidence",
        "projection_rebuild_source_gate",
        False,
        examples=("data/snapshots/<event>/order_books_long.csv", "data/snapshots/<event>/price_history.csv"),
    ),
    ArtifactFamilyClassification(
        "closed_market_day_parquet_archive",
        "operations",
        ANALYSIS_PROJECTION,
        (
            "archive/closed_market_days/**/artifact_family=*/data.parquet",
            "archive/closed_market_days/**/closed_market_day_archive_manifest.json",
        ),
        "rebuildable_closed_day_projection",
        "event_day_manifest and canonical snapshot/forecast/observation/CLOB-status tapes",
        "projection_rebuild_source_gate",
        False,
        examples=("data/archive/closed_market_days/v0.1/local_date=.../artifact_family=order_books_long/data.parquet",),
    ),
    ArtifactFamilyClassification(
        "event_day_manifest",
        "operations",
        ANALYSIS_PROJECTION,
        ("snapshots/*/event_day_manifest.json",),
        "rebuildable_event_day_folder_manifest",
        "current snapshot folder files and storage-class registry",
        "projection_rebuild_source_gate",
        False,
        examples=("data/snapshots/<event>/event_day_manifest.json",),
    ),
    ArtifactFamilyClassification(
        "backtest_row_exports",
        "reporting/calibration",
        ANALYSIS_PROJECTION,
        (
            "backtest/*_long.csv",
            "backtest/*_long.csv.gz",
            "backtest/*.parquet",
            "backtest/*rows*.csv",
            "backtest/*corpus*.csv",
            "backtest/*shadow_variants*.csv",
            "backtest/*source_state_ablation*.csv",
            "backtest/*variant_rows.csv",
            "backtest/*variant_export*.csv",
        ),
        "rebuildable_backtest_projection",
        "promotion corpora, model artifacts, and source evidence named by paired reports",
        "projection_rebuild_source_gate",
        False,
        examples=("data/backtest/active_variant_shadow_long.csv",),
    ),
    ArtifactFamilyClassification(
        "model_artifacts_and_manifests",
        "calibration",
        ANALYSIS_PROJECTION,
        ("artifacts/**/*.json", "artifacts/**/*.pkl", "artifacts/manifests/**/*"),
        "operationally_pinned_model_projection",
        "training data, config, and model build manifest",
        "projection_rebuild_source_gate",
        False,
        examples=("artifacts/models/hgb/feature_model_hgb.pkl",),
    ),
    ArtifactFamilyClassification(
        "operator_status_json",
        "operations/reporting",
        OPERATOR_CACHE,
        (
            "backtest/daily_refresh_status.json",
            "backtest/fleet_observability.json",
            "backtest/artifact_provenance_manifest.json",
            "backtest/data_layer_audit.json",
            "backtest/snapshot_evaluation.json",
            "backtest/shadow_ab_monitor.json",
            "backtest/progress_audit.json",
            "backtest/*status*.json",
            "ops/**/*.json",
        ),
        "latest_operator_status",
        "daily refresh, fleet observability, or source reports",
        "ttl_or_reviewed_cleanup_manifest",
        False,
        examples=("data/backtest/fleet_observability.json", "data/ops/daily_status.json"),
    ),
    ArtifactFamilyClassification(
        "generated_reports",
        "operations/reporting",
        OPERATOR_CACHE,
        ("backtest/*.md", "backtest/*report*.json", "ops/**/*.md", "ops/**/*.csv"),
        "generated_operator_report",
        "underlying status JSON, manifests, or canonical evidence",
        "ttl_or_reviewed_cleanup_manifest",
        False,
        examples=("data/backtest/data_retention_inventory_report.md",),
    ),
    ArtifactFamilyClassification(
        "provider_and_runtime_cache",
        "sources/model",
        OPERATOR_CACHE,
        (
            "forecast_archive/**",
            "forecast_history/**",
            "cache/**",
            "open_meteo/**",
            "weather_com/**",
            "source_cache/**",
            "reanalysis/**",
        ),
        "ttl_or_manifest_backed_source_cache",
        "provider history when available, or canonical forecast/source evidence when pinned",
        "ttl_or_lineage_review_gate",
        False,
        examples=("data/cache/open_meteo/*.json", "data/reanalysis/*.nc"),
    ),
    ArtifactFamilyClassification(
        "console_and_runtime_logs",
        "operations",
        OPERATOR_CACHE,
        ("logs/**", "snapshots/**/*.log", "snapshots/*.log", "ops/**/*.log", "**/*.log"),
        "operator_log",
        "routine logs are regenerated; incident-linked logs must be named in an incident manifest",
        "ttl_or_reviewed_cleanup_manifest",
        False,
        examples=("data/logs/daily_refresh.log", "data/snapshots/clob_loop_console.log"),
    ),
)

FAMILIES_BY_NAME = {family.artifact_family: family for family in ARTIFACT_FAMILIES}

UNCLASSIFIED_FAMILY = ArtifactFamilyClassification(
    UNCLASSIFIED,
    "owner-review",
    UNCLASSIFIED,
    (),
    "unclassified",
    "unknown",
    "manual_owner_review_required",
    False,
    durable=True,
    notes="Compatibility fallback. Durable writers should register a concrete artifact family.",
)


def _normalize_path(path: str | Path) -> str:
    normalized = Path(path).as_posix().lstrip("./")
    if normalized.startswith("data/"):
        normalized = normalized[len("data/") :]
    return normalized


def _matches_any(rel_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in patterns)


def classify_storage_path(path: str | Path) -> ArtifactFamilyClassification:
    """Return the first registered storage classification for a data/repo path."""

    rel_path = _normalize_path(path)
    for family in ARTIFACT_FAMILIES:
        if _matches_any(rel_path, family.patterns):
            return family
    return UNCLASSIFIED_FAMILY


def storage_class_contracts_payload() -> list[dict[str, Any]]:
    return [asdict(contract) for contract in STORAGE_CLASS_CONTRACTS]


def artifact_family_registry_payload() -> list[dict[str, Any]]:
    return [asdict(family) for family in ARTIFACT_FAMILIES]


def classification_payload(path: str | Path) -> dict[str, Any]:
    family = classify_storage_path(path)
    return {
        "storage_class": family.storage_class,
        "artifact_family": family.artifact_family,
        "retention_class": family.retention_class,
        "rebuild_source": family.rebuild_source,
        "delete_gate": family.delete_gate,
        "protected": family.protected,
        "storage_owner": family.owner,
    }


def delete_gate_for_storage_class(storage_class: str) -> dict[str, Any]:
    if storage_class == CANONICAL_EVIDENCE:
        return {
            "status": "REVIEW_REQUIRED",
            "delete_permission": "allowed_only_with_reviewed_cleanup_manifest",
            "detail": "canonical evidence cleanup requires an explicit reviewed cleanup manifest",
        }
    if storage_class == ANALYSIS_PROJECTION:
        return {
            "status": "REVIEW_REQUIRED",
            "delete_permission": "allowed_with_rebuild_source_and_reviewed_cleanup_manifest",
            "detail": "projection cleanup requires a named rebuild source and reviewed cleanup manifest",
        }
    if storage_class == OPERATOR_CACHE:
        return {
            "status": "NOT_REQUIRED",
            "delete_permission": "allowed_by_ttl_or_reviewed_cleanup_manifest",
            "detail": "operator/cache cleanup does not replace canonical evidence",
        }
    return {
        "status": "BLOCK",
        "delete_permission": "blocked_until_storage_classified",
        "detail": "unclassified durable artifacts require owner review before deletion",
    }


def summarize_storage_class_entries(
    entries: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    size_key: str = "size",
) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {
        contract.name: {
            "file_count": 0,
            "total_bytes": 0,
            "protected_files": 0,
            "protected_bytes": 0,
            "artifact_families": [],
        }
        for contract in STORAGE_CLASS_CONTRACTS
    }
    families_by_class: dict[str, set[str]] = {name: set() for name in summaries}
    for entry in entries or []:
        storage_class = str(entry.get("storage_class") or UNCLASSIFIED)
        summary = summaries.setdefault(
            storage_class,
            {
                "file_count": 0,
                "total_bytes": 0,
                "protected_files": 0,
                "protected_bytes": 0,
                "artifact_families": [],
            },
        )
        size = int(entry.get(size_key) or entry.get("bytes") or 0)
        summary["file_count"] += 1
        summary["total_bytes"] += size
        if entry.get("protected"):
            summary["protected_files"] += 1
            summary["protected_bytes"] += size
        family = entry.get("artifact_family")
        if family:
            families_by_class.setdefault(storage_class, set()).add(str(family))
    for storage_class, summary in summaries.items():
        summary["artifact_families"] = sorted(families_by_class.get(storage_class, set()))
    return summaries
