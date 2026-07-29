"""Closed-day projection cleanup and canonical warm-compression contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from weather.operations.closed_market_day_archive import ARTIFACT_FAMILY_NAMES


ORDER_BOOK_LONG = "order_books_long.csv"
ORDER_BOOK_LONG_GZIP = "order_books_long.csv.gz"
ORDER_BOOK_RAW = "order_books.jsonl"
ORDER_BOOK_RAW_GZIP = "order_books.jsonl.gz"


@dataclass(frozen=True)
class ProjectionFamilyContract:
    """Exact rebuild and read contract for one archive artifact family."""

    family: str
    projection_files: tuple[str, ...]
    canonical_rebuild_sources: tuple[str, ...]
    accepted_read_representations: tuple[str, ...]
    eligible: bool
    blocker: str | None
    rebuild_callable: str | None = None


@dataclass(frozen=True)
class WarmCompressionFamilyContract:
    """Exact reader gate for one high-payoff warm-compression family."""

    family: str
    source_file: str
    gzip_file: str
    readers: tuple[str, ...]
    accepted_read_representations: tuple[str, ...]
    eligible: bool
    reader_boundary: str | None
    blocker: str | None


_GZIP_UNPROVEN = "all_direct_readers_do_not_yet_have_proven_csv_gzip_fallback"


PROJECTION_FAMILIES = (
    ProjectionFamilyContract(
        "snapshots_long",
        ("snapshots_long.csv", "snapshots_long.csv.gz"),
        ("snapshots.jsonl",),
        (
            "validated_parquet:artifact_family=snapshots_long/data.parquet",
            "gzip_tiered_text:snapshots_long.csv.gz",
            "text_tape:snapshots_long.csv",
        ),
        False,
        _GZIP_UNPROVEN,
    ),
    ProjectionFamilyContract(
        "features_long",
        ("features_long.csv", "features_long.csv.gz"),
        ("features.jsonl",),
        (
            "validated_parquet:artifact_family=features_long/data.parquet",
            "gzip_tiered_text:features_long.csv.gz",
            "text_tape:features_long.csv",
        ),
        False,
        _GZIP_UNPROVEN,
    ),
    ProjectionFamilyContract(
        "components_long",
        ("components_long.csv", "components_long.csv.gz"),
        ("components.jsonl",),
        (
            "validated_parquet:artifact_family=components_long/data.parquet",
            "gzip_tiered_text:components_long.csv.gz",
            "text_tape:components_long.csv",
        ),
        False,
        _GZIP_UNPROVEN,
    ),
    ProjectionFamilyContract(
        "forecasts_long",
        ("forecasts_long.csv", "forecasts_long.csv.gz"),
        ("forecasts.jsonl",),
        (
            "validated_parquet:artifact_family=forecasts_long/data.parquet",
            "gzip_tiered_text:forecasts_long.csv.gz",
            "text_tape:forecasts_long.csv",
        ),
        False,
        _GZIP_UNPROVEN,
    ),
    ProjectionFamilyContract(
        "forecast_payloads_long",
        ("forecast_payloads_long.csv", "forecast_payloads_long.csv.gz"),
        (
            "forecast_payloads.jsonl",
            "forecast_payloads/*.json",
            "forecast_payloads/**/*.json",
            "*_weather_forecast_*_reconstructed.json",
            "*_open_meteo_*_reconstructed.json",
        ),
        (
            "validated_parquet:artifact_family=forecast_payloads_long/data.parquet",
            "gzip_tiered_text:forecast_payloads_long.csv.gz",
            "text_tape:forecast_payloads_long.csv",
        ),
        False,
        _GZIP_UNPROVEN,
    ),
    ProjectionFamilyContract(
        "observation_payloads_long",
        ("observation_payloads_long.csv", "observation_payloads_long.csv.gz"),
        (
            "observation_payloads.jsonl",
            "observation_payloads/*.json",
            "observation_payloads/**/*.json",
        ),
        (
            "validated_parquet:artifact_family=observation_payloads_long/data.parquet",
            "gzip_tiered_text:observation_payloads_long.csv.gz",
            "text_tape:observation_payloads_long.csv",
        ),
        False,
        _GZIP_UNPROVEN,
    ),
    ProjectionFamilyContract(
        "source_status_long",
        ("source_status_long.csv", "source_status_long.csv.gz"),
        ("source_status.jsonl",),
        (
            "validated_parquet:artifact_family=source_status_long/data.parquet",
            "gzip_tiered_text:source_status_long.csv.gz",
            "text_tape:source_status_long.csv",
        ),
        False,
        _GZIP_UNPROVEN,
    ),
    ProjectionFamilyContract(
        "replay_inputs",
        ("replay_inputs.jsonl", "replay_inputs_reconstructed.jsonl"),
        ("replay_inputs.jsonl", "replay_inputs_reconstructed.jsonl"),
        (
            "validated_parquet:artifact_family=replay_inputs/data.parquet",
            "canonical_jsonl:replay_inputs.jsonl",
            "canonical_jsonl:replay_inputs_reconstructed.jsonl",
        ),
        False,
        "canonical_evidence_is_not_a_projection_cleanup_candidate",
    ),
    ProjectionFamilyContract(
        "replay_input_status",
        ("replay_input_status_long.csv", "replay_input_status_long.csv.gz"),
        (
            "snapshots.jsonl",
            "replay_inputs.jsonl",
            "replay_inputs_reconstructed.jsonl",
        ),
        (
            "validated_parquet:artifact_family=replay_input_status/data.parquet",
            "gzip_tiered_text:replay_input_status_long.csv.gz",
            "text_tape:replay_input_status_long.csv",
        ),
        False,
        "row_level_rebuild_and_all_csv_gzip_reader_fallbacks_are_unproven",
        "weather.backtesting.replay.replay_input_status_rows",
    ),
    ProjectionFamilyContract(
        "clob_capture_status",
        ("clob_capture_status.jsonl",),
        ("clob_capture_status.jsonl",),
        (
            "validated_parquet:artifact_family=clob_capture_status/data.parquet",
            "canonical_jsonl:clob_capture_status.jsonl",
        ),
        False,
        "canonical_evidence_is_not_a_projection_cleanup_candidate",
    ),
    ProjectionFamilyContract(
        "clob_tokens",
        ("clob_tokens.csv", "clob_tokens.csv.gz"),
        ("clob_tokens.jsonl",),
        (
            "validated_parquet:artifact_family=clob_tokens/data.parquet",
            "gzip_tiered_text:clob_tokens.csv.gz",
            "text_tape:clob_tokens.csv",
        ),
        False,
        (
            "storage_class_contract_still_marks_csv_canonical_and_"
            "gzip_fallback_is_unproven"
        ),
    ),
    ProjectionFamilyContract(
        "order_books_summary",
        ("order_books_summary.csv", "order_books_summary.csv.gz"),
        ("order_books.jsonl",),
        (
            "validated_parquet:artifact_family=order_books_summary/data.parquet",
            "gzip_tiered_text:order_books_summary.csv.gz",
            "text_tape:order_books_summary.csv",
        ),
        False,
        "current_market_making_and_clob_readers_require_uncompressed_summary_csv",
        "weather.market.market_microstructure_capture.summarize_order_book",
    ),
    ProjectionFamilyContract(
        "order_books_long",
        (ORDER_BOOK_LONG, ORDER_BOOK_LONG_GZIP),
        (ORDER_BOOK_RAW, ORDER_BOOK_RAW_GZIP),
        (
            f"canonical_jsonl:{ORDER_BOOK_RAW}",
            f"canonical_jsonl_gzip:{ORDER_BOOK_RAW_GZIP}",
            "validated_parquet:artifact_family=order_books_long/data.parquet",
            f"gzip_tiered_text:{ORDER_BOOK_LONG_GZIP}",
            f"text_tape:{ORDER_BOOK_LONG}",
        ),
        True,
        None,
        "weather.market.market_microstructure_capture.order_book_level_rows",
    ),
    ProjectionFamilyContract(
        "price_history",
        ("price_history.csv", "price_history.csv.gz"),
        (
            "price_history.jsonl",
            "price_history_raw_manifest.jsonl",
            "price_history_raw/*.json",
            "price_history_raw/**/*.json",
        ),
        (
            "validated_parquet:artifact_family=price_history/data.parquet",
            "gzip_tiered_text:price_history.csv.gz",
            "text_tape:price_history.csv",
        ),
        False,
        (
            "dedupe_upsert_rebuild_semantics_and_all_csv_gzip_"
            "fallbacks_are_unproven"
        ),
        "weather.market.market_microstructure_capture.price_history_rows",
    ),
    ProjectionFamilyContract(
        "market_ws_events",
        ("market_ws_events.csv", "market_ws_events.csv.gz"),
        ("market_ws.jsonl",),
        (
            "validated_parquet:artifact_family=market_ws_events/data.parquet",
            "gzip_tiered_text:market_ws_events.csv.gz",
            "text_tape:market_ws_events.csv",
        ),
        False,
        _GZIP_UNPROVEN,
        "weather.market.market_microstructure_capture.ws_summary_rows",
    ),
    ProjectionFamilyContract(
        "clob_features_long",
        ("clob_features_long.csv", "clob_features_long.csv.gz"),
        (
            "clob_features.jsonl",
            "order_books.jsonl",
            "price_history.jsonl",
            "price_history_raw_manifest.jsonl",
            "price_history_raw/*.json",
            "price_history_raw/**/*.json",
            "clob_tokens.jsonl",
        ),
        (
            "validated_parquet:artifact_family=clob_features_long/data.parquet",
            "gzip_tiered_text:clob_features_long.csv.gz",
            "text_tape:clob_features_long.csv",
        ),
        False,
        _GZIP_UNPROVEN,
    ),
    ProjectionFamilyContract(
        "variant_predictions_long",
        ("variant_predictions_long.csv", "variant_predictions_long.csv.gz"),
        ("variant_predictions.jsonl", "live_variant_predictions.jsonl"),
        (
            "validated_parquet:artifact_family=variant_predictions_long/data.parquet",
            "gzip_tiered_text:variant_predictions_long.csv.gz",
            "text_tape:variant_predictions_long.csv",
        ),
        False,
        "all_csv_gzip_reader_fallbacks_and_raw_rebuild_parity_are_unproven",
    ),
)

PROJECTION_FAMILIES_BY_NAME = {
    contract.family: contract for contract in PROJECTION_FAMILIES
}

# Ordered by the measured per-market-day reclaim recorded for Item 325.  This
# registry is deliberately distinct from PROJECTION_FAMILIES: these are
# canonical/evidence tapes being represented as deterministic gzip, not
# rebuildable projections being considered for cleanup.
WARM_COMPRESSION_FAMILIES = (
    WarmCompressionFamilyContract(
        "order_books_jsonl",
        ORDER_BOOK_RAW,
        ORDER_BOOK_RAW_GZIP,
        (
            "content:weather.market.order_book_tape.iter_raw_jsonl_level_rows",
            (
                "content:weather.operations.closed_day_projection_tiering."
                "rebuild_one_order_books_long"
            ),
            "content:weather.operations.event_day_manifest._inspect_file",
            "content:weather.operations.event_day_manifest._row_count",
            "delegated:weather.market.order_book_tape.iter_full_book_rows",
            "delegated:weather.market.order_book_tape.rebuild_long_csv",
            (
                "discovery:weather.market.order_book_tape."
                "resolve_full_book_representation"
            ),
            (
                "discovery:weather.operations.closed_day_projection_tiering."
                "_plan_folder"
            ),
            (
                "discovery:weather.operations.closed_day_projection_tiering."
                "_plan_warm_folder"
            ),
            (
                "discovery:weather.operations.closed_day_projection_tiering."
                "_assert_action_shape"
            ),
            (
                "discovery:weather.operations.closed_day_projection_tiering."
                "_assert_action_current_before_compression"
            ),
            (
                "discovery:weather.operations.closed_day_projection_tiering."
                "_refresh_and_validate_event_manifest"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "ARTIFACT_FAMILIES"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "_planned_family"
            ),
            (
                "discovery:weather.operations.event_day_manifest."
                "EVENT_DAY_ARTIFACT_FAMILIES"
            ),
            "discovery:weather.operations.event_day_manifest._iter_family_files",
            "discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES",
            (
                "discovery:weather.operations.clob_order_book_tiering."
                "discover_rows"
            ),
            (
                "discovery:weather.reporting.data_quality.clob_coverage_audit."
                "audit_folder"
            ),
            (
                "discovery:weather.reporting.data_quality."
                "data_layer_audit_collectors.snapshot_folder_audit"
            ),
            (
                "discovery:weather.reporting.source_gates."
                "source_family_inventory.clob_raw_tape_present"
            ),
            (
                "discovery:weather.reporting.source_gates."
                "source_family_inventory.scan_clob"
            ),
            (
                "writer:weather.market.market_microstructure_capture."
                "MarketMicrostructureStore.write_books"
            ),
        ),
        (
            f"tiered_text:{ORDER_BOOK_RAW}",
            f"tiered_text:{ORDER_BOOK_RAW_GZIP}",
        ),
        True,
        "weather.io.open_tiered_text",
        None,
    ),
    WarmCompressionFamilyContract(
        "clob_tokens_jsonl",
        "clob_tokens.jsonl",
        "clob_tokens.jsonl.gz",
        (
            "content:weather.operations.event_day_manifest._inspect_file",
            "content:weather.operations.event_day_manifest._row_count",
            (
                "discovery:weather.operations.closed_market_day_archive."
                "ARTIFACT_FAMILIES"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "_planned_family"
            ),
            (
                "discovery:weather.operations.event_day_manifest."
                "EVENT_DAY_ARTIFACT_FAMILIES"
            ),
            "discovery:weather.operations.event_day_manifest._iter_family_files",
            "discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES",
            (
                "discovery:weather.operations.clob_order_book_tiering."
                "discover_rows"
            ),
            (
                "discovery:weather.reporting.data_quality.clob_coverage_audit."
                "audit_folder"
            ),
            (
                "discovery:weather.reporting.data_quality."
                "data_layer_audit_collectors.snapshot_folder_audit"
            ),
            (
                "writer:weather.market.market_microstructure_capture."
                "MarketMicrostructureStore.write_token_rows"
            ),
        ),
        ("text_tape:clob_tokens.jsonl",),
        False,
        None,
        (
            "clob_coverage_audit_and_data_layer_audit_collectors_require_"
            "plain_clob_tokens_jsonl"
        ),
    ),
    WarmCompressionFamilyContract(
        "replay_inputs_jsonl",
        "replay_inputs.jsonl",
        "replay_inputs.jsonl.gz",
        (
            "content:weather.backtesting.replay._read_jsonl",
            (
                "content:weather.calibration.pooled_candidate_replay."
                "_bounded_preselection_file_bytes"
            ),
            (
                "content:weather.calibration.pooled_candidate_replay."
                "_bounded_preselection_replay_records"
            ),
            (
                "content:weather.calibration.residual_distribution_corpus."
                "read_jsonl"
            ),
            "content:weather.collection.snapshot_store.SnapshotStore.read_jsonl",
            "content:weather.collection.snapshot_tracker.read_jsonl_records",
            (
                "content:weather.market.worker_release_binding."
                "_matching_replay_inputs"
            ),
            (
                "content:weather.operations.density_live_replay_parity."
                "_read_jsonl_prefix"
            ),
            "content:weather.operations.observation_trigger.read_jsonl",
            (
                "content:weather.reporting.casebooks.disagreement_casebook."
                "read_jsonl"
            ),
            (
                "content:weather.reporting.data_quality."
                "feature_quality_quarantine.annotate_replay_presence"
            ),
            (
                "content:weather.reporting.scorecards."
                "captured_input_parity_evidence._read_rows_strict"
            ),
            (
                "content:weather.sources.official_guidance_collection."
                "collect_official_guidance_from_replay_inputs"
            ),
            "delegated:weather.backtesting.replay.load_replay_records",
            (
                "delegated:weather.backtesting.replay_backtest."
                "run_replay_backtest"
            ),
            "delegated:weather.backtesting.replay_ablation.run_ablation",
            (
                "delegated:weather.calibration.pooled_candidate_replay."
                "load_bounded_preselection_folder_inputs"
            ),
            (
                "delegated:weather.calibration.pooled_candidate_replay."
                "iter_bounded_preselection_source_market_days"
            ),
            (
                "delegated:weather.collection.snapshot_store."
                "SnapshotStore.replay_inputs_by_snapshot"
            ),
            (
                "delegated:weather.collection.snapshot_tracker."
                "backfill_source_status_for_folder"
            ),
            (
                "delegated:weather.collection.snapshot_tracker."
                "backfill_forecast_payloads_for_folder"
            ),
            (
                "delegated:weather.reporting.promotion.promotion_corpus."
                "build_promotion_corpus"
            ),
            (
                "delegated:weather.reporting.validation."
                "wu_max_since_7_validation.collect_validation_rows"
            ),
            (
                "discovery:weather.calibration.residual_distribution_corpus."
                "_folder_input_lineage"
            ),
            (
                "discovery:weather.calibration.residual_distribution_corpus."
                "materialize_market_day_rows"
            ),
            (
                "discovery:weather.collection.snapshot_tracker."
                "replay_inputs_path_for_folder"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "ARTIFACT_FAMILIES"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "read_market_day_artifact"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "_read_source_frame"
            ),
            (
                "discovery:weather.operations.event_day_manifest."
                "EVENT_DAY_ARTIFACT_FAMILIES"
            ),
            "discovery:weather.operations.event_day_manifest._iter_family_files",
            (
                "discovery:weather.operations.replay_cache_retention."
                "_stable_source"
            ),
            (
                "discovery:weather.operations.replay_status_backfill."
                "folder_evidence"
            ),
            (
                "discovery:weather.operations.settled_day_freshness."
                "market_row"
            ),
            "discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES",
            (
                "discovery:weather.reporting.data_quality."
                "data_layer_audit_collectors.snapshot_folder_audit"
            ),
            (
                "discovery:weather.reporting.scorecards.snapshot_evaluation."
                "snapshot_folder_summary"
            ),
            (
                "discovery:weather.sources.official_guidance_collection."
                "_replay_paths"
            ),
            "writer:weather.collection.snapshot_store.SnapshotStore.write",
            (
                "writer:weather.collection.snapshot_store."
                "SnapshotStore.write_replay_input"
            ),
        ),
        ("text_tape:replay_inputs.jsonl",),
        False,
        None,
        (
            "replay_snapshot_tracker_and_pooled_candidate_replay_require_"
            "plain_replay_inputs_jsonl"
        ),
    ),
    WarmCompressionFamilyContract(
        "variant_predictions_jsonl",
        "variant_predictions.jsonl",
        "variant_predictions.jsonl.gz",
        (
            (
                "content:weather.calibration.residual_distribution_corpus."
                "captured_comparator_probabilities"
            ),
            (
                "content:weather.calibration.residual_distribution_corpus."
                "read_jsonl"
            ),
            (
                "content:weather.operations.density_live_replay_parity."
                "_read_variant_rows"
            ),
            (
                "content:weather.reporting.scorecards."
                "captured_input_parity_evidence._read_rows_strict"
            ),
            (
                "discovery:weather.calibration.residual_distribution_corpus."
                "_folder_input_lineage"
            ),
            (
                "discovery:weather.calibration.residual_distribution_corpus."
                "materialize_market_day_rows"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "ARTIFACT_FAMILIES"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "_planned_family"
            ),
            (
                "discovery:weather.operations.event_day_manifest."
                "EVENT_DAY_ARTIFACT_FAMILIES"
            ),
            "discovery:weather.operations.event_day_manifest._iter_family_files",
            "discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES",
            (
                "discovery:weather.reporting.data_quality."
                "data_layer_audit_collectors.snapshot_folder_audit"
            ),
            "writer:weather.collection.snapshot_store.SnapshotStore.write",
        ),
        ("text_tape:variant_predictions.jsonl",),
        False,
        None,
        (
            "density_parity_residual_corpus_and_captured_input_parity_"
            "require_plain_variant_predictions_jsonl"
        ),
    ),
    WarmCompressionFamilyContract(
        "order_books_summary_csv",
        "order_books_summary.csv",
        "order_books_summary.csv.gz",
        (
            "content:weather.market.clob_recon.load_book_rows",
            (
                "content:weather.market.market_latest_inputs."
                "load_latest_market_inputs"
            ),
            (
                "content:weather.market.market_making_run_support."
                "latest_book_rows"
            ),
            (
                "content:weather.market.market_making_run_support."
                "preflight_csv_encoding_diagnostics"
            ),
            "content:weather.market.market_microstructure.book_capture_times",
            (
                "content:weather.market.market_microstructure_features."
                "clob_feature_rows_for_folder"
            ),
            "content:weather.market.mm_paper_scoring.load_book_rows",
            "content:weather.market.mm_paper_scoring.load_mark_rows",
            "content:weather.market.taker_bot_scoring.load_mark_rows",
            (
                "content:weather.reporting.casebooks.disagreement_casebook."
                "load_clob_context"
            ),
            (
                "delegated:weather.calibration.pooled_candidate_replay."
                "build_clob_feature_index"
            ),
            (
                "delegated:weather.market.market_making_run_support."
                "preflight_market"
            ),
            "delegated:weather.market.mm_paper.load_or_build_clob_recon",
            "discovery:weather.market.clob_recon.discover_snapshot_folders",
            (
                "discovery:weather.market.market_making_preflight."
                "remediation_last_good_artifact"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "ARTIFACT_FAMILIES"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "read_market_day_artifact"
            ),
            (
                "discovery:weather.operations.event_day_manifest."
                "EVENT_DAY_ARTIFACT_FAMILIES"
            ),
            "discovery:weather.operations.event_day_manifest._iter_family_files",
            (
                "discovery:weather.operations.clob_order_book_tiering."
                "discover_rows"
            ),
            (
                "discovery:weather.operations.market_making_tape_encoding."
                "discover_files"
            ),
            (
                "discovery:weather.operations.replay_cache_retention."
                "OPTIONAL_EVENT_REBUILD_INPUTS"
            ),
            "discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES",
            (
                "discovery:weather.reporting.data_quality.clob_coverage_audit."
                "audit_folder"
            ),
            (
                "discovery:weather.reporting.data_quality."
                "data_layer_audit_collectors.snapshot_folder_audit"
            ),
            (
                "discovery:weather.reporting.scorecards.snapshot_evaluation."
                "snapshot_folder_summary"
            ),
            (
                "discovery:weather.reporting.source_gates."
                "source_family_inventory.clob_raw_tape_present"
            ),
            (
                "writer:weather.market.market_microstructure_capture."
                "MarketMicrostructureStore.write_books"
            ),
        ),
        ("text_tape:order_books_summary.csv",),
        False,
        None,
        (
            "market_latest_inputs_microstructure_features_and_mm_scoring_"
            "require_plain_order_books_summary_csv"
        ),
    ),
    WarmCompressionFamilyContract(
        "clob_tokens_csv",
        "clob_tokens.csv",
        "clob_tokens.csv.gz",
        (
            (
                "content:weather.market.market_latest_inputs."
                "load_latest_market_inputs"
            ),
            (
                "content:weather.market.market_making_run_support."
                "preflight_csv_encoding_diagnostics"
            ),
            (
                "content:weather.market.market_making_run_support."
                "preflight_market"
            ),
            (
                "content:weather.market.taker_bot_strategy_evaluation."
                "preflight_summary_for_market"
            ),
            (
                "discovery:weather.market.market_making_preflight."
                "remediation_last_good_artifact"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "ARTIFACT_FAMILIES"
            ),
            (
                "discovery:weather.operations.closed_market_day_archive."
                "read_market_day_artifact"
            ),
            (
                "discovery:weather.operations.event_day_manifest."
                "EVENT_DAY_ARTIFACT_FAMILIES"
            ),
            "discovery:weather.operations.event_day_manifest._iter_family_files",
            (
                "discovery:weather.operations.clob_order_book_tiering."
                "discover_rows"
            ),
            (
                "discovery:weather.operations.market_making_tape_encoding."
                "discover_files"
            ),
            "discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES",
            (
                "discovery:weather.reporting.data_quality.clob_coverage_audit."
                "audit_folder"
            ),
            (
                "discovery:weather.reporting.data_quality."
                "data_layer_audit_collectors.snapshot_folder_audit"
            ),
            (
                "writer:weather.market.market_microstructure_capture."
                "MarketMicrostructureStore.write_token_rows"
            ),
        ),
        ("text_tape:clob_tokens.csv",),
        False,
        None,
        (
            "market_latest_inputs_market_making_run_support_and_taker_"
            "strategy_evaluation_require_plain_clob_tokens_csv"
        ),
    ),
)

WARM_COMPRESSION_FAMILIES_BY_NAME = {
    contract.family: contract for contract in WARM_COMPRESSION_FAMILIES
}
WARM_COMPRESSION_FAMILIES_BY_SOURCE_FILE = {
    contract.source_file: contract for contract in WARM_COMPRESSION_FAMILIES
}


def projection_family_registry() -> list[dict[str, Any]]:
    """Return a JSON-native registry suitable for signed plan payloads."""

    return [
        {
            **asdict(contract),
            "projection_files": list(contract.projection_files),
            "canonical_rebuild_sources": list(
                contract.canonical_rebuild_sources
            ),
            "accepted_read_representations": list(
                contract.accepted_read_representations
            ),
        }
        for contract in PROJECTION_FAMILIES
    ]


def validate_projection_family_registry() -> list[str]:
    errors: list[str] = []
    names = [contract.family for contract in PROJECTION_FAMILIES]
    if len(names) != len(set(names)):
        errors.append("duplicate projection family")
    archive_names = set(ARTIFACT_FAMILY_NAMES)
    registry_names = set(names)
    if registry_names != archive_names:
        missing = sorted(archive_names - registry_names)
        extra = sorted(registry_names - archive_names)
        errors.append(
            f"archive registry mismatch: missing={missing}, extra={extra}"
        )
    eligible = [
        contract.family for contract in PROJECTION_FAMILIES if contract.eligible
    ]
    if eligible != ["order_books_long"]:
        errors.append(f"only order_books_long may be eligible, got {eligible}")
    for contract in PROJECTION_FAMILIES:
        if not contract.projection_files:
            errors.append(f"{contract.family}: projection_files is empty")
        if not contract.canonical_rebuild_sources:
            errors.append(
                f"{contract.family}: canonical_rebuild_sources is empty"
            )
        if not contract.accepted_read_representations:
            errors.append(
                f"{contract.family}: accepted_read_representations is empty"
            )
        if contract.eligible and contract.blocker:
            errors.append(f"{contract.family}: eligible family has blocker")
        if not contract.eligible and not contract.blocker:
            errors.append(f"{contract.family}: ineligible family lacks blocker")
    return errors


def registry_hash() -> str:
    encoded = json.dumps(
        projection_family_registry(),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def warm_compression_family_registry() -> list[dict[str, Any]]:
    """Return the ordered, JSON-native canonical warm-tier reader registry."""

    return [
        {
            **asdict(contract),
            "readers": list(contract.readers),
            "accepted_read_representations": list(
                contract.accepted_read_representations
            ),
        }
        for contract in WARM_COMPRESSION_FAMILIES
    ]


def validate_warm_compression_family_registry() -> list[str]:
    errors: list[str] = []
    names = [contract.family for contract in WARM_COMPRESSION_FAMILIES]
    source_files = [
        contract.source_file for contract in WARM_COMPRESSION_FAMILIES
    ]
    gzip_files = [contract.gzip_file for contract in WARM_COMPRESSION_FAMILIES]
    if len(names) != len(set(names)):
        errors.append("duplicate warm-compression family")
    if len(source_files) != len(set(source_files)):
        errors.append("duplicate warm-compression source file")
    if len(gzip_files) != len(set(gzip_files)):
        errors.append("duplicate warm-compression gzip file")
    if len(WARM_COMPRESSION_FAMILIES) != 6:
        errors.append(
            "warm-compression registry must contain the six measured payoff families"
        )
    eligible = [
        contract.source_file
        for contract in WARM_COMPRESSION_FAMILIES
        if contract.eligible
    ]
    if eligible != [ORDER_BOOK_RAW]:
        errors.append(
            f"only {ORDER_BOOK_RAW} may be warm-compression eligible, got {eligible}"
        )
    for contract in WARM_COMPRESSION_FAMILIES:
        if contract.gzip_file != f"{contract.source_file}.gz":
            errors.append(
                f"{contract.family}: gzip file is not the source .gz peer"
            )
        if not contract.readers:
            errors.append(f"{contract.family}: reader inventory is empty")
        if not contract.accepted_read_representations:
            errors.append(
                f"{contract.family}: accepted_read_representations is empty"
            )
        if contract.eligible:
            if contract.blocker:
                errors.append(f"{contract.family}: eligible family has blocker")
            if not contract.reader_boundary:
                errors.append(
                    f"{contract.family}: eligible family lacks reader boundary"
                )
        else:
            if not contract.blocker:
                errors.append(
                    f"{contract.family}: ineligible family lacks specific blocker"
                )
            if contract.reader_boundary:
                errors.append(
                    f"{contract.family}: blocked family claims reader boundary"
                )
    return errors


def warm_compression_registry_hash() -> str:
    encoded = json.dumps(
        warm_compression_family_registry(),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
