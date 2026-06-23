"""Closed market-day Parquet archive contract.

This module owns the static contract for Item 243. It intentionally does not
convert or delete snapshot tapes; Item 244 owns the backfill writer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.schema_registry import schema_version


MANIFEST_SCHEMA_VERSION = schema_version("closed_market_day_archive_manifest")
ARCHIVE_ROOT_VERSION = "v0.1"
DEFAULT_ARCHIVE_ROOT = data_path("archive", "closed_market_days", ARCHIVE_ROOT_VERSION)
MANIFEST_FILENAME = "closed_market_day_archive_manifest.json"
DATASET_FILENAME = "data.parquet"
DEFAULT_PARQUET_CODEC = "zstd"

MARKET_DAY_PARTITION_KEYS = ("local_date", "market_id", "event_slug")
ARTIFACT_FAMILY_PARTITION_KEY = "artifact_family"
COUNTABLE_QUALITY_GRADES = ("complete", "manual_override")
ELIGIBLE_FINALIZATION_STATES = (
    "settled_countable",
    "settled_non_countable",
    "closed_unlabeled",
)
READER_FALLBACK_ORDER = ("validated_parquet", "gzip_tiered_text", "text_tape")


@dataclass(frozen=True)
class ArtifactFamilyContract:
    name: str
    parquet_dataset: str
    source_patterns: tuple[str, ...]
    raw_evidence_patterns: tuple[str, ...]
    parquet_default_for_closed_days: bool = True
    raw_evidence_permanent: bool = True
    notes: str = ""


ARTIFACT_FAMILIES = (
    ArtifactFamilyContract(
        "snapshots_long",
        DATASET_FILENAME,
        ("snapshots_long.csv", "snapshots_long.csv.gz"),
        ("snapshots.jsonl",),
        notes="Primary model/market probability long table.",
    ),
    ArtifactFamilyContract(
        "features_long",
        DATASET_FILENAME,
        ("features_long.csv", "features_long.csv.gz"),
        ("features.jsonl",),
        notes="Derived feature rows; raw JSONL remains source evidence.",
    ),
    ArtifactFamilyContract(
        "components_long",
        DATASET_FILENAME,
        ("components_long.csv", "components_long.csv.gz"),
        ("components.jsonl",),
        notes="Distribution component rows.",
    ),
    ArtifactFamilyContract(
        "forecasts_long",
        DATASET_FILENAME,
        ("forecasts_long.csv", "forecasts_long.csv.gz"),
        ("forecasts.jsonl",),
        notes="Normalized forecast rows.",
    ),
    ArtifactFamilyContract(
        "forecast_payloads_long",
        DATASET_FILENAME,
        ("forecast_payloads_long.csv", "forecast_payloads_long.csv.gz"),
        ("forecast_payloads.jsonl", "*_weather_forecast_*_reconstructed.json", "*_open_meteo_*_reconstructed.json"),
        notes="Forecast payload analysis table with raw payload references.",
    ),
    ArtifactFamilyContract(
        "source_status_long",
        DATASET_FILENAME,
        ("source_status_long.csv", "source_status_long.csv.gz"),
        ("source_status.jsonl", "replay_inputs.jsonl", "replay_inputs_reconstructed.jsonl"),
        notes="Source freshness/degradation table.",
    ),
    ArtifactFamilyContract(
        "replay_inputs",
        DATASET_FILENAME,
        ("replay_inputs.jsonl", "replay_inputs_reconstructed.jsonl"),
        ("replay_inputs.jsonl", "replay_inputs_reconstructed.jsonl", "replay_input_status.json"),
        notes="Replay inputs may be normalized to Parquet only when schema-safe.",
    ),
    ArtifactFamilyContract(
        "replay_input_status",
        DATASET_FILENAME,
        ("replay_input_status_long.csv", "replay_input_status_long.csv.gz"),
        ("replay_input_status.json",),
        parquet_default_for_closed_days=False,
        notes="Small status artifact; Parquet is optional unless row counts justify it.",
    ),
    ArtifactFamilyContract(
        "clob_tokens",
        DATASET_FILENAME,
        ("clob_tokens.csv", "clob_tokens.csv.gz"),
        ("clob_tokens.jsonl",),
        notes="Token and condition id join keys.",
    ),
    ArtifactFamilyContract(
        "order_books_summary",
        DATASET_FILENAME,
        ("order_books_summary.csv", "order_books_summary.csv.gz"),
        ("order_books.jsonl",),
        notes="Book summary analysis table backed by raw book payloads.",
    ),
    ArtifactFamilyContract(
        "order_books_long",
        DATASET_FILENAME,
        ("order_books_long.csv", "order_books_long.csv.gz"),
        ("order_books.jsonl",),
        notes="Full-depth CLOB book long table and highest-byte archive target.",
    ),
    ArtifactFamilyContract(
        "price_history",
        DATASET_FILENAME,
        ("price_history.csv", "price_history.csv.gz"),
        ("price_history.jsonl",),
        notes="CLOB price history analysis table.",
    ),
    ArtifactFamilyContract(
        "market_ws_events",
        DATASET_FILENAME,
        ("market_ws_events.csv", "market_ws_events.csv.gz"),
        ("market_ws.jsonl",),
        notes="WebSocket event summary table.",
    ),
    ArtifactFamilyContract(
        "clob_features_long",
        DATASET_FILENAME,
        ("clob_features_long.csv", "clob_features_long.csv.gz"),
        ("clob_features.jsonl", "order_books.jsonl", "price_history.jsonl", "clob_tokens.jsonl"),
        notes="Derived market microstructure features.",
    ),
    ArtifactFamilyContract(
        "variant_predictions_long",
        DATASET_FILENAME,
        ("variant_predictions_long.csv", "variant_predictions_long.csv.gz"),
        ("live_variant_predictions.jsonl",),
        notes="Variant probability shadow rows when present.",
    ),
)

ARTIFACT_FAMILY_NAMES = tuple(family.name for family in ARTIFACT_FAMILIES)
ARTIFACT_FAMILIES_BY_NAME = {family.name: family for family in ARTIFACT_FAMILIES}


def _partition_value(value: str) -> str:
    text = str(value or "").strip()
    if not text or "/" in text or "\\" in text or text in {".", ".."} or ".." in text:
        raise ValueError(f"invalid archive partition value: {value!r}")
    return text


def archive_partition_path(
    local_date: str,
    market_id: str,
    event_slug: str,
    *,
    root: str | Path = DEFAULT_ARCHIVE_ROOT,
) -> Path:
    """Return the market-day archive partition root."""

    return (
        Path(root)
        / f"local_date={_partition_value(local_date)}"
        / f"market_id={_partition_value(market_id)}"
        / f"event_slug={_partition_value(event_slug)}"
    )


def manifest_path_for_partition(partition_root: str | Path) -> Path:
    return Path(partition_root) / MANIFEST_FILENAME


def family_dataset_path(partition_root: str | Path, family_name: str) -> Path:
    if family_name not in ARTIFACT_FAMILIES_BY_NAME:
        raise KeyError(f"unknown archive artifact family: {family_name}")
    return Path(partition_root) / f"{ARTIFACT_FAMILY_PARTITION_KEY}={family_name}" / DATASET_FILENAME


def artifact_family_contract_rows() -> list[dict[str, Any]]:
    return [asdict(family) for family in ARTIFACT_FAMILIES]


def validate_manifest_shape(manifest: dict[str, Any]) -> list[str]:
    """Validate the v0.1 manifest shape, not source-file contents."""

    errors: list[str] = []
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("schema_version must be closed_market_day_archive_manifest_v0.1")
    if manifest.get("archive_root_version") != ARCHIVE_ROOT_VERSION:
        errors.append(f"archive_root_version must be {ARCHIVE_ROOT_VERSION}")
    for key in ("generated_at_utc", "writer", "writer_version", "source_folder", "manifest_hash"):
        if not manifest.get(key):
            errors.append(f"{key} is required")

    partition = manifest.get("partition")
    if not isinstance(partition, dict):
        errors.append("partition must be an object")
    else:
        for key in MARKET_DAY_PARTITION_KEYS:
            if not partition.get(key):
                errors.append(f"partition.{key} is required")

    finalization = manifest.get("finalization")
    if not isinstance(finalization, dict):
        errors.append("finalization must be an object")
    else:
        state = finalization.get("state")
        if state not in ELIGIBLE_FINALIZATION_STATES:
            errors.append(
                "finalization.state must be one of "
                + ", ".join(ELIGIBLE_FINALIZATION_STATES)
            )
        if "countable" not in finalization:
            errors.append("finalization.countable is required")
        if state == "settled_countable" and finalization.get("quality_grade") not in COUNTABLE_QUALITY_GRADES:
            errors.append("settled_countable finalization requires a countable quality_grade")

    validation = manifest.get("validation")
    if not isinstance(validation, dict):
        errors.append("validation must be an object")
    elif validation.get("status") not in {"PASS", "WARN", "BLOCK"}:
        errors.append("validation.status must be PASS, WARN, or BLOCK")

    families = manifest.get("artifact_families")
    if not isinstance(families, list) or not families:
        errors.append("artifact_families must be a non-empty list")
        return errors

    for index, family in enumerate(families):
        if not isinstance(family, dict):
            errors.append(f"artifact_families[{index}] must be an object")
            continue
        name = family.get("artifact_family")
        if name not in ARTIFACT_FAMILIES_BY_NAME:
            errors.append(f"artifact_families[{index}].artifact_family is unknown")
        status = family.get("status")
        if status not in {"parquet", "raw_reference_only", "missing_source", "skipped"}:
            errors.append(f"artifact_families[{index}].status is invalid")
        if status in {"parquet", "raw_reference_only"} and not family.get("source_files"):
            errors.append(f"artifact_families[{index}].source_files is required")

        for source_index, source in enumerate(family.get("source_files") or []):
            for key in ("path", "bytes", "sha256", "role"):
                if key not in source:
                    errors.append(
                        f"artifact_families[{index}].source_files[{source_index}].{key} is required"
                    )

        if status == "parquet":
            parquet = family.get("parquet")
            if not isinstance(parquet, dict):
                errors.append(f"artifact_families[{index}].parquet is required")
            else:
                for key in ("path", "bytes", "sha256", "row_count", "codec", "schema_fingerprint"):
                    if key not in parquet:
                        errors.append(f"artifact_families[{index}].parquet.{key} is required")

    return errors


def parquet_reader_allowed(manifest: dict[str, Any]) -> bool:
    """Return whether a reader may prefer this manifest over text tapes."""

    return not validate_manifest_shape(manifest) and (manifest.get("validation") or {}).get("status") == "PASS"
