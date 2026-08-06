"""Closed-day projection rebuild and reader-fallback contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from weather.market.mm_paper_constants import (
    EXECUTION_CANONICAL_TAPE_FILENAME,
    EXECUTION_RAW_TAPE_FILENAME,
    EXECUTION_SESSION_FILENAME,
)
from weather.operations.closed_market_day_archive import ARTIFACT_FAMILY_NAMES


ORDER_BOOK_LONG = "order_books_long.csv"
ORDER_BOOK_LONG_GZIP = "order_books_long.csv.gz"
ORDER_BOOK_RAW = "order_books.jsonl"


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
        (ORDER_BOOK_RAW,),
        (
            f"canonical_jsonl:{ORDER_BOOK_RAW}",
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
        "maker_execution_tape",
        (
            EXECUTION_RAW_TAPE_FILENAME,
            EXECUTION_CANONICAL_TAPE_FILENAME,
            EXECUTION_SESSION_FILENAME,
        ),
        (
            EXECUTION_RAW_TAPE_FILENAME,
            EXECUTION_CANONICAL_TAPE_FILENAME,
            EXECUTION_SESSION_FILENAME,
        ),
        (
            f"canonical_jsonl:{EXECUTION_RAW_TAPE_FILENAME}",
            f"canonical_csv:{EXECUTION_CANONICAL_TAPE_FILENAME}",
            f"canonical_jsonl:{EXECUTION_SESSION_FILENAME}",
        ),
        False,
        "canonical_evidence_is_not_a_projection_cleanup_candidate",
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
