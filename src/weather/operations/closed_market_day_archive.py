"""Closed market-day Parquet archive contract.

This module owns the static contract for Item 243. It intentionally does not
convert or delete snapshot tapes; Item 244 owns the backfill writer.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from weather.backtesting.settlement_ledger import ledger_label_for_slug
from weather.market.market_config import date_from_event_slug, market_id_from_slug
from weather.operations.event_day_manifest import (
    event_day_manifest_path,
    read_event_day_manifest,
    validate_event_day_manifest,
)
from weather.paths import data_path
from weather.schema_registry import schema_version


MANIFEST_SCHEMA_VERSION = schema_version("closed_market_day_archive_manifest")
BACKFILL_SCHEMA_VERSION = schema_version("closed_market_day_parquet_backfill")
INCREMENTAL_SCHEMA_VERSION = schema_version("closed_market_day_parquet_incremental")
ARCHIVE_ROOT_VERSION = "v0.1"
DEFAULT_ARCHIVE_ROOT = data_path("archive", "closed_market_days", ARCHIVE_ROOT_VERSION)
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_BACKFILL_JSON = data_path("backtest", "closed_market_day_parquet_backfill.json")
DEFAULT_BACKFILL_REPORT = data_path("backtest", "closed_market_day_parquet_backfill_report.md")
DEFAULT_INCREMENTAL_JSON = data_path("backtest", "closed_market_day_parquet_incremental.json")
DEFAULT_INCREMENTAL_REPORT = data_path("backtest", "closed_market_day_parquet_incremental_report.md")
DEFAULT_INCREMENTAL_CURSOR = data_path("backtest", "closed_market_day_parquet_incremental_cursor.json")
MANIFEST_FILENAME = "closed_market_day_archive_manifest.json"
DATASET_FILENAME = "data.parquet"
DEFAULT_PARQUET_CODEC = "zstd"
BACKFILL_WRITER_VERSION = "closed_market_day_parquet_backfill_v0.1"

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


@dataclass(frozen=True)
class ArtifactReadProvenance:
    artifact_family: str
    source_mode: str
    row_count: int
    path: str | None = None
    snapshots_root: str | None = None
    archive_root: str | None = None
    manifest_path: str | None = None
    manifest_hash: str | None = None
    source_file_hash: str | None = None
    parquet_file_hash: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class ArtifactReadResult:
    frame: pd.DataFrame
    provenance: ArtifactReadProvenance


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
        ("price_history.jsonl", "price_history_raw_manifest.jsonl", "price_history_raw/*.json", "price_history_raw/**/*.json"),
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
        (
            "clob_features.jsonl",
            "order_books.jsonl",
            "price_history.jsonl",
            "price_history_raw_manifest.jsonl",
            "price_history_raw/*.json",
            "price_history_raw/**/*.json",
            "clob_tokens.jsonl",
        ),
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


def archive_partition_for_folder(
    folder: str | Path,
    *,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
) -> Path | None:
    """Return the archive partition for a snapshot folder, if its slug is known."""

    event_slug = Path(folder).name
    target_date = date_from_event_slug(event_slug)
    market_id = market_id_from_slug(event_slug)
    if target_date is None or market_id is None:
        return None
    return archive_partition_path(
        target_date.isoformat(),
        market_id,
        event_slug,
        root=archive_root,
    )


def _combine_fallback_reasons(*reasons: str | None) -> str | None:
    parts = [str(reason) for reason in reasons if reason]
    return ";".join(parts) if parts else None


def _family_manifest(manifest: dict[str, Any], artifact_family: str) -> dict[str, Any] | None:
    return next(
        (
            family
            for family in manifest.get("artifact_families") or []
            if family.get("artifact_family") == artifact_family
        ),
        None,
    )


def _analysis_source_record(family_manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if not family_manifest:
        return None
    sources = family_manifest.get("source_files") or []
    return next(
        (
            source
            for source in sources
            if "analysis_source" in str(source.get("role") or "")
        ),
        sources[0] if sources else None,
    )


def _source_paths_for_family(folder: Path, family: ArtifactFamilyContract) -> tuple[list[Path], list[Path]]:
    paths = _find_paths(folder, family.source_patterns)
    gzip_paths = [path for path in paths if path.name.lower().endswith(".csv.gz")]
    text_paths = [path for path in paths if path not in gzip_paths]
    return gzip_paths, text_paths


def _read_source_artifact_result(
    folder: Path,
    family: ArtifactFamilyContract,
    *,
    snapshots_root: Path,
    archive_root: Path,
    fallback_reason: str | None,
    manifest_path: Path | None = None,
    manifest_hash: str | None = None,
) -> ArtifactReadResult:
    gzip_paths, text_paths = _source_paths_for_family(folder, family)
    if gzip_paths:
        source_path = gzip_paths[0]
        source_mode = "gzip_tiered_text"
    elif text_paths:
        source_path = text_paths[0]
        source_mode = "text_tape"
    else:
        reason = _combine_fallback_reasons(fallback_reason, "source_missing")
        frame = pd.DataFrame()
        return ArtifactReadResult(
            frame=frame,
            provenance=ArtifactReadProvenance(
                artifact_family=family.name,
                source_mode="text_tape",
                row_count=0,
                snapshots_root=str(snapshots_root),
                archive_root=str(archive_root),
                manifest_path=str(manifest_path) if manifest_path else None,
                manifest_hash=manifest_hash,
                fallback_reason=reason,
            ),
        )

    frame = _read_source_frame(source_path)
    reader_fallback = frame.attrs.get("reader_fallback_reason")
    return ArtifactReadResult(
        frame=frame,
        provenance=ArtifactReadProvenance(
            artifact_family=family.name,
            source_mode=source_mode,
            row_count=len(frame),
            path=str(source_path),
            snapshots_root=str(snapshots_root),
            archive_root=str(archive_root),
            manifest_path=str(manifest_path) if manifest_path else None,
            manifest_hash=manifest_hash,
            source_file_hash=sha256_file(source_path),
            fallback_reason=_combine_fallback_reasons(fallback_reason, reader_fallback),
        ),
    )


def _archive_read_blocker(
    folder: Path,
    *,
    prefer_archive: bool,
    as_of_date: str | date | datetime | None,
) -> str | None:
    if not prefer_archive:
        return "archive_disabled"
    target_date = date_from_event_slug(folder.name)
    market_id = market_id_from_slug(folder.name)
    if target_date is None or market_id is None:
        return "unknown_event_slug"
    if target_date >= _parse_date(as_of_date):
        return "active_or_future_target_date"
    return None


def read_market_day_artifact(
    folder: str | Path,
    artifact_family: str,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    as_of_date: str | date | datetime | None = None,
    prefer_archive: bool = True,
) -> ArtifactReadResult:
    """Read a market-day artifact with closed-day Parquet preference.

    The returned frame is safe for existing pandas-based reports. Provenance
    tells callers whether the rows came from validated Parquet, gzip-tiered
    text, or the original CSV/JSONL tape.
    """

    if artifact_family not in ARTIFACT_FAMILIES_BY_NAME:
        raise KeyError(f"unknown archive artifact family: {artifact_family}")

    folder = Path(folder)
    snapshots_root = Path(snapshots_root)
    archive_root = Path(archive_root)
    family = ARTIFACT_FAMILIES_BY_NAME[artifact_family]

    blocker = _archive_read_blocker(
        folder,
        prefer_archive=prefer_archive,
        as_of_date=as_of_date,
    )
    partition_root = archive_partition_for_folder(folder, archive_root=archive_root)
    manifest_path = manifest_path_for_partition(partition_root) if partition_root else None
    if blocker:
        return _read_source_artifact_result(
            folder,
            family,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            fallback_reason=blocker,
            manifest_path=manifest_path,
        )

    if manifest_path is None:
        return _read_source_artifact_result(
            folder,
            family,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            fallback_reason="unknown_archive_partition",
        )

    manifest = _read_json(manifest_path)
    if not manifest:
        return _read_source_artifact_result(
            folder,
            family,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            fallback_reason="missing_archive_manifest",
            manifest_path=manifest_path,
        )
    manifest_hash = str(manifest.get("manifest_hash") or "")

    if not manifest_hash_valid(manifest):
        return _read_source_artifact_result(
            folder,
            family,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            fallback_reason="invalid_manifest_hash",
            manifest_path=manifest_path,
            manifest_hash=manifest_hash,
        )
    if not parquet_reader_allowed(manifest):
        return _read_source_artifact_result(
            folder,
            family,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            fallback_reason="manifest_validation_not_pass",
            manifest_path=manifest_path,
            manifest_hash=manifest_hash,
        )

    family_manifest = _family_manifest(manifest, artifact_family)
    parquet = (family_manifest or {}).get("parquet") or {}
    if not family_manifest or family_manifest.get("status") != "parquet" or not parquet:
        return _read_source_artifact_result(
            folder,
            family,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            fallback_reason="parquet_family_unavailable",
            manifest_path=manifest_path,
            manifest_hash=manifest_hash,
        )

    parquet_path = Path(manifest_path).parent / str(parquet.get("path") or "")
    if not parquet_path.exists():
        return _read_source_artifact_result(
            folder,
            family,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            fallback_reason="missing_parquet_dataset",
            manifest_path=manifest_path,
            manifest_hash=manifest_hash,
        )
    parquet_hash = sha256_file(parquet_path)
    if parquet.get("sha256") != parquet_hash:
        return _read_source_artifact_result(
            folder,
            family,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            fallback_reason="parquet_hash_mismatch",
            manifest_path=manifest_path,
            manifest_hash=manifest_hash,
        )
    parquet_rows = int(pq.ParquetFile(parquet_path).metadata.num_rows)
    expected_rows = int(parquet.get("row_count") or -1)
    if parquet_rows != expected_rows:
        return _read_source_artifact_result(
            folder,
            family,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            fallback_reason="parquet_row_count_mismatch",
            manifest_path=manifest_path,
            manifest_hash=manifest_hash,
        )

    frame = pd.read_parquet(parquet_path)
    if len(frame) != expected_rows:
        return _read_source_artifact_result(
            folder,
            family,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            fallback_reason="parquet_frame_row_count_mismatch",
            manifest_path=manifest_path,
            manifest_hash=manifest_hash,
        )
    source_record = _analysis_source_record(family_manifest)
    return ArtifactReadResult(
        frame=frame,
        provenance=ArtifactReadProvenance(
            artifact_family=family.name,
            source_mode="validated_parquet",
            row_count=len(frame),
            path=str(parquet_path),
            snapshots_root=str(snapshots_root),
            archive_root=str(archive_root),
            manifest_path=str(manifest_path),
            manifest_hash=manifest_hash,
            source_file_hash=(source_record or {}).get("sha256"),
            parquet_file_hash=parquet_hash,
        ),
    )


def read_artifact_frame(
    folder: str | Path,
    artifact_family: str,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    as_of_date: str | date | datetime | None = None,
    prefer_archive: bool = True,
    include_provenance: bool = False,
) -> pd.DataFrame | ArtifactReadResult:
    """Compatibility wrapper returning only the frame unless provenance is requested."""

    result = read_market_day_artifact(
        folder,
        artifact_family,
        snapshots_root=snapshots_root,
        archive_root=archive_root,
        as_of_date=as_of_date,
        prefer_archive=prefer_archive,
    )
    return result if include_provenance else result.frame


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_content_hash(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_hash", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def manifest_hash_valid(manifest: dict[str, Any]) -> bool:
    return bool(manifest.get("manifest_hash")) and manifest.get("manifest_hash") == manifest_content_hash(manifest)


def _read_json(path: str | Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _parse_date(value: str | date | datetime | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _source_record(path: Path, *, root: Path, role: str) -> dict[str, Any]:
    path = Path(path)
    try:
        display_path = path.relative_to(root).as_posix()
    except ValueError:
        display_path = path.as_posix()
    stat = path.stat()
    return {
        "path": display_path,
        "bytes": int(stat.st_size),
        "sha256": sha256_file(path),
        "role": role,
    }


def _find_paths(folder: Path, patterns: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(folder.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def _json_safe_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def _read_jsonl_frame(path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            item = json.loads(text)
            if not isinstance(item, dict):
                item = {"value": item}
            rows.append({key: _json_safe_cell(value) for key, value in item.items()})
    return pd.DataFrame(rows)


def _csv_text_handle(path: Path):
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def _read_csv_parser_fallback_frame(path: Path, exc: Exception) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    malformed_rows = 0
    extra_fields = 0
    with _csv_text_handle(path) as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            extras = row.pop(None, None)
            if extras:
                malformed_rows += 1
                extra_fields += len(extras)
            rows.append({key: value for key, value in row.items() if key is not None})
    frame = pd.DataFrame(rows, columns=fieldnames)
    frame.attrs["reader_fallback_reason"] = "csv_parser_fallback_bad_lines"
    frame.attrs["reader_error"] = f"{type(exc).__name__}: {exc}"
    frame.attrs["malformed_csv_row_count"] = malformed_rows
    frame.attrs["malformed_csv_extra_field_count"] = extra_fields
    return frame


def _read_source_frame(path: Path) -> pd.DataFrame:
    name = path.name.lower()
    if name.endswith(".jsonl"):
        return _read_jsonl_frame(path)
    if name.endswith(".csv") or name.endswith(".csv.gz"):
        try:
            return pd.read_csv(path)
        except pd.errors.ParserError as exc:
            return _read_csv_parser_fallback_frame(path, exc)
    raise ValueError(f"unsupported archive source format: {path}")


def _schema_fingerprint(table: pa.Table) -> str:
    encoded = str(table.schema).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _writer_lock_paths(folder: Path) -> list[Path]:
    candidates = [folder / ".snapshot.lock"]
    candidates.extend(path for path in folder.glob("*.lock") if path.is_file())
    candidates.extend(path for path in folder.glob(".*.lock") if path.is_file())
    return sorted({path for path in candidates if path.exists()})


def _finalization_for_folder(
    folder: Path,
    event_slug: str,
    *,
    ledger_root: str | Path | None = None,
) -> dict[str, Any]:
    evidence_paths: list[str] = []
    label = _read_json(folder / "settlement.json")
    if label:
        evidence_paths.append(str(folder / "settlement.json"))
    else:
        label = ledger_label_for_slug(event_slug, ledger_root=ledger_root)
        if label and label.get("ledger_path"):
            evidence_paths.append(str(label.get("ledger_path")))
    if label:
        quality_grade = label.get("quality_grade")
        countable = quality_grade in COUNTABLE_QUALITY_GRADES
        return {
            "state": "settled_countable" if countable else "settled_non_countable",
            "quality_grade": quality_grade,
            "countable": bool(countable),
            "evidence_paths": evidence_paths,
            "settlement_bucket": label.get("settlement_bucket"),
            "settlement_source": label.get("settlement_source"),
        }
    return {
        "state": "closed_unlabeled",
        "quality_grade": "missing_settlement",
        "countable": False,
        "evidence_paths": evidence_paths,
    }


def _planned_family(folder: Path, family: ArtifactFamilyContract, *, snapshots_root: Path) -> dict[str, Any]:
    source_paths = _find_paths(folder, family.source_patterns)
    raw_paths = _find_paths(folder, family.raw_evidence_patterns)
    source_files: list[dict[str, Any]] = []
    if source_paths:
        source_files.append(_source_record(source_paths[0], root=snapshots_root, role="analysis_source"))
    for raw_path in raw_paths:
        role = "raw_evidence"
        if source_paths and raw_path == source_paths[0]:
            role = "analysis_source_and_raw_evidence"
        source_files.append(_source_record(raw_path, root=snapshots_root, role=role))
    if source_paths and family.parquet_default_for_closed_days:
        status = "planned_parquet"
    elif source_files and raw_paths:
        status = "raw_reference_only"
    elif source_files:
        status = "skipped"
    else:
        status = "missing_source"
    return {
        "artifact_family": family.name,
        "status": status,
        "source_path": str(source_paths[0]) if source_paths else None,
        "source_files": source_files,
        "raw_evidence_count": len(raw_paths),
    }


def _event_day_manifest_status(folder: Path, *, snapshots_root: Path) -> dict[str, Any]:
    path = event_day_manifest_path(folder)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "status": "MISSING",
        }
    manifest = read_event_day_manifest(path)
    if manifest is None:
        return {
            "path": str(path),
            "exists": True,
            "status": "UNREADABLE",
        }
    validation = validate_event_day_manifest(
        manifest,
        folder,
        snapshots_root=snapshots_root,
        check_hashes=True,
        fail_on_extra=True,
    )
    return {
        "path": str(path),
        "exists": True,
        "status": validation.get("status"),
        "manifest_hash": manifest.get("manifest_hash"),
        "validation": validation,
    }


def _source_signature_from_families(families: list[dict[str, Any]]) -> list[tuple[str, int, str, str]]:
    signature: list[tuple[str, int, str, str]] = []
    for family in families:
        for source in family.get("source_files") or []:
            signature.append((
                str(source.get("path") or ""),
                int(source.get("bytes") or 0),
                str(source.get("sha256") or ""),
                str(source.get("role") or ""),
            ))
    return sorted(signature)


def _parquet_records_available(manifest: dict[str, Any], partition_root: Path) -> bool:
    for family in manifest.get("artifact_families") or []:
        if family.get("status") != "parquet":
            continue
        parquet = family.get("parquet") or {}
        parquet_path = partition_root / str(parquet.get("path") or "")
        if not parquet_path.exists():
            return False
        if parquet.get("sha256") != sha256_file(parquet_path):
            return False
    return True


def _existing_manifest_current(
    manifest: dict[str, Any] | None,
    families: list[dict[str, Any]],
    partition_root: Path,
) -> bool:
    if not manifest or validate_manifest_shape(manifest):
        return False
    if (manifest.get("validation") or {}).get("status") != "PASS":
        return False
    if not manifest_hash_valid(manifest):
        return False
    if not _parquet_records_available(manifest, partition_root):
        return False
    return _source_signature_from_families(manifest.get("artifact_families") or []) == _source_signature_from_families(families)


def plan_market_day(
    folder: str | Path,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    as_of_date: str | date | datetime | None = None,
    ledger_root: str | Path | None = None,
) -> dict[str, Any]:
    folder = Path(folder)
    snapshots_root = Path(snapshots_root)
    archive_root = Path(archive_root)
    event_slug = folder.name
    target_date = date_from_event_slug(event_slug)
    market_id = market_id_from_slug(event_slug)
    as_of = _parse_date(as_of_date)
    blockers: list[str] = []
    if target_date is None or market_id is None:
        blockers.append("unknown_event_slug")
    elif target_date >= as_of:
        blockers.append("active_or_future_target_date")
    lock_paths = _writer_lock_paths(folder)
    if lock_paths:
        blockers.append("active_writer_lock")
    event_day_manifest = _event_day_manifest_status(folder, snapshots_root=snapshots_root)
    if event_day_manifest.get("exists") and event_day_manifest.get("status") != "PASS":
        blockers.append("stale_event_day_manifest")

    families = [
        _planned_family(folder, family, snapshots_root=snapshots_root)
        for family in ARTIFACT_FAMILIES
    ]
    convertible_count = sum(1 for family in families if family.get("status") == "planned_parquet")
    if convertible_count == 0:
        blockers.append("no_convertible_artifact_families")
    local_date = target_date.isoformat() if target_date else ""
    partition_root = archive_partition_path(
        local_date or "unknown",
        market_id or "unknown",
        event_slug,
        root=archive_root,
    )
    existing_manifest = _read_json(manifest_path_for_partition(partition_root))
    action = "blocked"
    status = "blocked"
    if not blockers:
        if _existing_manifest_current(existing_manifest, families, partition_root):
            action = "skip_current_manifest"
            status = "skipped"
        else:
            action = "rewrite_stale_manifest" if existing_manifest else "convert"
            status = "planned"
    return {
        "event_slug": event_slug,
        "market_id": market_id,
        "local_date": local_date or None,
        "target_date": target_date.isoformat() if target_date else None,
        "source_folder": str(folder),
        "partition_root": str(partition_root),
        "status": status,
        "action": action,
        "blockers": blockers,
        "writer_lock_paths": [str(path) for path in lock_paths],
        "event_day_manifest": event_day_manifest,
        "finalization": (
            _finalization_for_folder(folder, event_slug, ledger_root=ledger_root)
            if not blockers or blockers == ["no_convertible_artifact_families"]
            else {}
        ),
        "artifact_families": families,
        "convertible_family_count": convertible_count,
        "source_bytes": sum(
            int(source.get("bytes") or 0)
            for family in families
            for source in family.get("source_files") or []
        ),
    }


def _remove_tree_within(path: Path, root: Path) -> None:
    path = Path(path)
    root = Path(root)
    if not path.exists():
        return
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved == root_resolved or root_resolved not in resolved.parents:
        raise ValueError(f"refusing to remove path outside archive root: {path}")
    shutil.rmtree(path)


def _manifest_family_for_plan(
    family_plan: dict[str, Any],
    *,
    tmp_partition_root: Path,
    snapshots_root: Path,
    codec: str,
) -> dict[str, Any]:
    name = family_plan["artifact_family"]
    status = family_plan["status"]
    manifest_family = {
        "artifact_family": name,
        "status": "missing_source",
        "source_files": family_plan.get("source_files") or [],
    }
    if status == "missing_source":
        return manifest_family
    if status in {"raw_reference_only", "skipped"}:
        manifest_family["status"] = status
        return manifest_family
    source_path = Path(family_plan["source_path"])
    frame = _read_source_frame(source_path)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    dataset_path = family_dataset_path(tmp_partition_root, name)
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, dataset_path, compression=codec)
    parquet_file = pq.ParquetFile(dataset_path)
    row_count = int(parquet_file.metadata.num_rows)
    if row_count != len(frame):
        raise ValueError(
            f"row count mismatch for {name}: source={len(frame)} parquet={row_count}"
        )
    manifest_family["status"] = "parquet"
    manifest_family["parquet"] = {
        "path": dataset_path.relative_to(tmp_partition_root).as_posix(),
        "bytes": int(dataset_path.stat().st_size),
        "sha256": sha256_file(dataset_path),
        "row_count": row_count,
        "codec": codec,
        "schema_fingerprint": _schema_fingerprint(table),
    }
    return manifest_family


def apply_market_day(
    plan: dict[str, Any],
    *,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    codec: str = DEFAULT_PARQUET_CODEC,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if plan.get("blockers"):
        return dict(plan)
    if plan.get("action") == "skip_current_manifest":
        row = dict(plan)
        row["status"] = "skipped"
        row["reason"] = "manifest_current"
        return row
    archive_root = Path(archive_root)
    snapshots_root = Path(snapshots_root)
    partition_root = Path(plan["partition_root"])
    tmp_partition_root = partition_root.with_name(partition_root.name + ".tmp")
    _remove_tree_within(tmp_partition_root, archive_root)
    tmp_partition_root.mkdir(parents=True, exist_ok=True)
    try:
        manifest_families = [
            _manifest_family_for_plan(
                family,
                tmp_partition_root=tmp_partition_root,
                snapshots_root=snapshots_root,
                codec=codec,
            )
            for family in plan.get("artifact_families") or []
        ]
        parquet_count = sum(1 for family in manifest_families if family.get("status") == "parquet")
        validation_checks = [
            {"check": "eligible_closed_market_day", "status": "PASS"},
            {"check": "parquet_family_count", "status": "PASS", "value": parquet_count},
            {"check": "source_files_preserved", "status": "PASS", "deleted_source_count": 0},
        ]
        event_manifest = plan.get("event_day_manifest") or {}
        if event_manifest.get("exists"):
            validation_checks.append({
                "check": "event_day_manifest_current",
                "status": "PASS",
                "manifest_hash": event_manifest.get("manifest_hash"),
            })
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "archive_root_version": ARCHIVE_ROOT_VERSION,
            "generated_at_utc": generated_at_utc or utc_iso(),
            "writer": "weather.operations.closed_market_day_archive",
            "writer_version": BACKFILL_WRITER_VERSION,
            "source_folder": plan.get("source_folder"),
            "manifest_hash": "",
            "partition": {
                "local_date": plan.get("local_date"),
                "market_id": plan.get("market_id"),
                "event_slug": plan.get("event_slug"),
            },
            "finalization": plan.get("finalization") or {},
            "event_day_manifest": (
                {
                    "path": event_manifest.get("path"),
                    "manifest_hash": event_manifest.get("manifest_hash"),
                    "status": event_manifest.get("status"),
                }
                if event_manifest.get("exists")
                else None
            ),
            "validation": {
                "status": "PASS",
                "checks": validation_checks,
            },
            "artifact_families": manifest_families,
        }
        manifest["manifest_hash"] = manifest_content_hash(manifest)
        shape_errors = validate_manifest_shape(manifest)
        if shape_errors:
            raise ValueError("manifest validation failed: " + "; ".join(shape_errors))
        _write_json(manifest_path_for_partition(tmp_partition_root), manifest)
        _remove_tree_within(partition_root, archive_root)
        partition_root.parent.mkdir(parents=True, exist_ok=True)
        tmp_partition_root.replace(partition_root)
        row = dict(plan)
        row.update({
            "status": "converted",
            "manifest_path": str(manifest_path_for_partition(partition_root)),
            "manifest_hash": manifest["manifest_hash"],
            "converted_family_count": parquet_count,
            "artifact_families": manifest_families,
            "parquet_bytes": sum(
                int((family.get("parquet") or {}).get("bytes") or 0)
                for family in manifest_families
            ),
            "source_deleted_count": 0,
        })
        return row
    except Exception as exc:
        _remove_tree_within(tmp_partition_root, archive_root)
        row = dict(plan)
        row.update({"status": "failed", "error": str(exc)})
        return row


def iter_snapshot_folders(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    event_slugs: list[str] | tuple[str, ...] | None = None,
    limit: int | None = None,
) -> list[Path]:
    root = Path(snapshots_root)
    if event_slugs:
        folders = [root / slug for slug in event_slugs]
    else:
        folders = sorted(path for path in root.iterdir() if path.is_dir()) if root.exists() else []
    folders = [folder for folder in folders if folder.exists() and folder.is_dir()]
    if limit is not None:
        folders = folders[: int(limit)]
    return folders


def build_backfill_payload(
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    apply: bool = False,
    as_of_date: str | date | datetime | None = None,
    event_slugs: list[str] | tuple[str, ...] | None = None,
    limit: int | None = None,
    codec: str = DEFAULT_PARQUET_CODEC,
    generated_at_utc: str | None = None,
    ledger_root: str | Path | None = None,
) -> dict[str, Any]:
    snapshots_root = Path(snapshots_root)
    archive_root = Path(archive_root)
    as_of = _parse_date(as_of_date)
    generated = generated_at_utc or utc_iso()
    market_days: list[dict[str, Any]] = []
    for folder in iter_snapshot_folders(snapshots_root, event_slugs=event_slugs, limit=limit):
        plan = plan_market_day(
            folder,
            snapshots_root=snapshots_root,
            archive_root=archive_root,
            as_of_date=as_of,
            ledger_root=ledger_root,
        )
        market_days.append(
            apply_market_day(
                plan,
                archive_root=archive_root,
                snapshots_root=snapshots_root,
                codec=codec,
                generated_at_utc=generated,
            )
            if apply and plan.get("action") != "blocked"
            else plan
        )
    counts = {
        "planned": sum(1 for row in market_days if row.get("status") == "planned"),
        "converted": sum(1 for row in market_days if row.get("status") == "converted"),
        "skipped": sum(1 for row in market_days if row.get("status") == "skipped"),
        "blocked": sum(1 for row in market_days if row.get("status") == "blocked"),
        "failed": sum(1 for row in market_days if row.get("status") == "failed"),
    }
    return {
        "schema_version": BACKFILL_SCHEMA_VERSION,
        "generated_at_utc": generated,
        "mode": "apply" if apply else "dry_run",
        "status": "BLOCK" if counts["failed"] else "PASS",
        "snapshots_root": str(snapshots_root),
        "archive_root": str(archive_root),
        "as_of_date": as_of.isoformat(),
        "codec": codec,
        "summary": {
            **counts,
            "market_day_count": len(market_days),
            "source_deleted_count": sum(int(row.get("source_deleted_count") or 0) for row in market_days),
            "converted_family_count": sum(int(row.get("converted_family_count") or 0) for row in market_days),
            "source_bytes": sum(int(row.get("source_bytes") or 0) for row in market_days),
            "parquet_bytes": sum(int(row.get("parquet_bytes") or 0) for row in market_days),
        },
        "market_days": market_days,
    }


def _load_incremental_cursor(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = _read_json(path)
    return payload if isinstance(payload, dict) else {}


def _event_manifest_signature(folder: Path) -> dict[str, Any] | None:
    manifest = _read_json(event_day_manifest_path(folder))
    if not manifest:
        return None
    manifest_hash = manifest.get("manifest_hash")
    if not manifest_hash:
        return None
    return {
        "mode": "event_day_manifest",
        "manifest_hash": manifest_hash,
        "artifact_count": len(manifest.get("artifacts") or []),
        "artifact_family_count": len(manifest.get("artifact_families") or []),
    }


def _source_stat_signature(folder: Path, snapshots_root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for family in ARTIFACT_FAMILIES:
        for pattern in (*family.source_patterns, *family.raw_evidence_patterns):
            for path in folder.glob(pattern):
                if not path.is_file() or path in seen:
                    continue
                seen.add(path)
                stat = path.stat()
                try:
                    rel = path.relative_to(snapshots_root).as_posix()
                except ValueError:
                    rel = path.as_posix()
                rows.append({
                    "path": rel,
                    "bytes": int(stat.st_size),
                    "mtime_ns": int(stat.st_mtime_ns),
                })
    return {"mode": "source_file_stats", "files": sorted(rows, key=lambda row: row["path"])}


def incremental_folder_signature(
    folder: str | Path,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    as_of_date: str | date | datetime | None = None,
) -> dict[str, Any]:
    folder = Path(folder)
    snapshots_root = Path(snapshots_root)
    as_of = _parse_date(as_of_date).isoformat()
    detail = _event_manifest_signature(folder) or _source_stat_signature(folder, snapshots_root)
    payload = {
        "event_slug": folder.name,
        "as_of_date": as_of,
        "signature": detail,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return {
        "mode": detail.get("mode"),
        "as_of_date": as_of,
        "signature_hash": hashlib.sha256(encoded).hexdigest(),
        "detail": detail,
    }


def _incremental_window(
    snapshots_root: Path,
    *,
    cursor: dict[str, Any],
    event_slugs: list[str] | tuple[str, ...] | None = None,
    max_scan_folders: int | None = 25,
) -> tuple[list[Path], dict[str, Any]]:
    folders = iter_snapshot_folders(snapshots_root, event_slugs=event_slugs)
    total = len(folders)
    if event_slugs:
        return folders, {
            "start_index": 0,
            "next_index": 0,
            "total_folders": total,
            "remaining_folders": 0,
            "event_slug_filter": list(event_slugs),
        }
    if max_scan_folders is None:
        max_scan_folders = total
    max_scan_folders = max(1, int(max_scan_folders))
    start = int(((cursor.get("scan") or {}).get("next_index") or 0))
    if total <= 0:
        return [], {"start_index": 0, "next_index": 0, "total_folders": 0, "remaining_folders": 0}
    if start < 0 or start >= total:
        start = 0
    window = folders[start:start + max_scan_folders]
    next_index = start + len(window)
    if next_index >= total:
        next_index = 0
    remaining = max(0, total - (start + len(window)))
    return window, {
        "start_index": start,
        "next_index": next_index,
        "total_folders": total,
        "remaining_folders": remaining,
        "max_scan_folders": max_scan_folders,
    }


def _unchanged_incremental_row(
    folder: Path,
    *,
    prior: dict[str, Any],
    signature: dict[str, Any],
    archive_root: Path,
) -> dict[str, Any]:
    partition_root = archive_partition_for_folder(folder, archive_root=archive_root)
    return {
        "event_slug": folder.name,
        "market_id": market_id_from_slug(folder.name),
        "local_date": date_from_event_slug(folder.name).isoformat() if date_from_event_slug(folder.name) else None,
        "source_folder": str(folder),
        "partition_root": str(partition_root) if partition_root else None,
        "status": "skipped",
        "action": "skip_unchanged",
        "blockers": prior.get("blockers") or [],
        "signature": signature,
        "prior_status": prior.get("status"),
        "prior_action": prior.get("action"),
        "manifest_hash": prior.get("manifest_hash"),
        "converted_family_count": int(prior.get("converted_family_count") or 0),
        "source_bytes": int(prior.get("source_bytes") or 0),
        "parquet_bytes": int(prior.get("parquet_bytes") or 0),
    }


def _cursor_entry_for_row(row: dict[str, Any], signature: dict[str, Any], scanned_at_utc: str) -> dict[str, Any]:
    return {
        "signature_hash": signature.get("signature_hash"),
        "signature_mode": signature.get("mode"),
        "as_of_date": signature.get("as_of_date"),
        "status": row.get("status"),
        "action": row.get("action"),
        "blockers": row.get("blockers") or [],
        "manifest_hash": row.get("manifest_hash"),
        "converted_family_count": int(row.get("converted_family_count") or 0),
        "source_bytes": int(row.get("source_bytes") or 0),
        "parquet_bytes": int(row.get("parquet_bytes") or 0),
        "scanned_at_utc": scanned_at_utc,
    }


def _incremental_backlog_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_market: dict[str, dict[str, Any]] = {}
    for row in rows:
        market_id = row.get("market_id") or "unknown"
        item = by_market.setdefault(
            market_id,
            {
                "market_id": market_id,
                "planned": 0,
                "converted": 0,
                "blocked": 0,
                "failed": 0,
                "source_bytes": 0,
                "parquet_bytes": 0,
            },
        )
        status = row.get("status")
        if status in {"planned", "converted", "blocked", "failed"}:
            item[status] += 1
        item["source_bytes"] += int(row.get("source_bytes") or 0)
        item["parquet_bytes"] += int(row.get("parquet_bytes") or 0)
    return sorted(by_market.values(), key=lambda row: row["market_id"])


def build_incremental_payload(
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    apply: bool = False,
    as_of_date: str | date | datetime | None = None,
    event_slugs: list[str] | tuple[str, ...] | None = None,
    max_scan_folders: int | None = 25,
    cursor_path: str | Path | None = DEFAULT_INCREMENTAL_CURSOR,
    cursor: dict[str, Any] | None = None,
    codec: str = DEFAULT_PARQUET_CODEC,
    generated_at_utc: str | None = None,
    ledger_root: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    snapshots_root = Path(snapshots_root)
    archive_root = Path(archive_root)
    as_of = _parse_date(as_of_date)
    generated = generated_at_utc or utc_iso()
    prior_cursor = dict(cursor or _load_incremental_cursor(cursor_path))
    prior_folders = dict(prior_cursor.get("folders") or {})
    folders, scan_state = _incremental_window(
        snapshots_root,
        cursor=prior_cursor,
        event_slugs=event_slugs,
        max_scan_folders=max_scan_folders,
    )
    market_days: list[dict[str, Any]] = []
    next_folder_cursor = dict(prior_folders)
    changed_count = 0
    unchanged_count = 0
    for folder in folders:
        signature = incremental_folder_signature(folder, snapshots_root=snapshots_root, as_of_date=as_of)
        prior = prior_folders.get(folder.name) or {}
        unchanged = (
            not force
            and prior.get("signature_hash") == signature.get("signature_hash")
            and prior.get("status") != "failed"
        )
        if unchanged:
            row = _unchanged_incremental_row(folder, prior=prior, signature=signature, archive_root=archive_root)
            unchanged_count += 1
        else:
            changed_count += 1
            plan = plan_market_day(
                folder,
                snapshots_root=snapshots_root,
                archive_root=archive_root,
                as_of_date=as_of,
                ledger_root=ledger_root,
            )
            row = (
                apply_market_day(
                    plan,
                    archive_root=archive_root,
                    snapshots_root=snapshots_root,
                    codec=codec,
                    generated_at_utc=generated,
                )
                if apply and plan.get("action") != "blocked"
                else plan
            )
            row["signature"] = signature
        market_days.append(row)
        next_folder_cursor[folder.name] = _cursor_entry_for_row(row, signature, generated)

    counts = {
        "planned": sum(1 for row in market_days if row.get("status") == "planned"),
        "converted": sum(1 for row in market_days if row.get("status") == "converted"),
        "skipped": sum(1 for row in market_days if row.get("status") == "skipped"),
        "blocked": sum(1 for row in market_days if row.get("status") == "blocked"),
        "failed": sum(1 for row in market_days if row.get("status") == "failed"),
    }
    blocker_counts = Counter(
        blocker
        for row in market_days
        for blocker in (row.get("blockers") or [])
    )
    family_status_counts = Counter(
        family.get("status")
        for row in market_days
        for family in (row.get("artifact_families") or [])
        if family.get("status")
    )
    next_cursor = {
        "schema_version": INCREMENTAL_SCHEMA_VERSION,
        "updated_at_utc": generated,
        "snapshots_root": str(snapshots_root),
        "archive_root": str(archive_root),
        "as_of_date": as_of.isoformat(),
        "scan": scan_state,
        "folders": next_folder_cursor,
    }
    return {
        "schema_version": INCREMENTAL_SCHEMA_VERSION,
        "generated_at_utc": generated,
        "mode": "apply" if apply else "dry_run",
        "status": "BLOCK" if counts["failed"] else "PASS",
        "snapshots_root": str(snapshots_root),
        "archive_root": str(archive_root),
        "as_of_date": as_of.isoformat(),
        "codec": codec,
        "cursor_path": str(cursor_path) if cursor_path else None,
        "scan": scan_state,
        "summary": {
            **counts,
            "scanned": len(market_days),
            "changed": changed_count,
            "unchanged": unchanged_count,
            "market_day_count": len(market_days),
            "remaining_scan_backlog": scan_state.get("remaining_folders", 0),
            "source_deleted_count": sum(int(row.get("source_deleted_count") or 0) for row in market_days),
            "converted_family_count": sum(int(row.get("converted_family_count") or 0) for row in market_days),
            "source_bytes": sum(int(row.get("source_bytes") or 0) for row in market_days),
            "parquet_bytes": sum(int(row.get("parquet_bytes") or 0) for row in market_days),
        },
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "family_status_counts": dict(sorted(family_status_counts.items())),
        "backlog_by_market": _incremental_backlog_rows(market_days),
        "market_days": market_days,
        "cursor": next_cursor,
    }


def render_incremental_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Incremental Closed Market-Day Parquet Conversion",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Mode: `{payload.get('mode')}`",
        f"Status: `{payload.get('status')}`",
        f"Cursor: `{payload.get('cursor_path')}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| :--- | ---: |",
    ]
    for key in (
        "scanned",
        "changed",
        "unchanged",
        "planned",
        "converted",
        "skipped",
        "blocked",
        "failed",
        "remaining_scan_backlog",
        "converted_family_count",
        "source_bytes",
        "parquet_bytes",
    ):
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines += [
        "",
        "## Blockers",
        "",
        "| Blocker | Count |",
        "| :--- | ---: |",
    ]
    for blocker, count in (payload.get("blocker_counts") or {}).items():
        lines.append(f"| {blocker} | {count} |")
    if not payload.get("blocker_counts"):
        lines.append("| - | 0 |")
    lines += [
        "",
        "## Market Backlog",
        "",
        "| Market | Planned | Converted | Blocked | Failed | Source Bytes | Parquet Bytes |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("backlog_by_market") or []:
        lines.append(
            "| "
            + " | ".join([
                str(row.get("market_id") or ""),
                str(row.get("planned") or 0),
                str(row.get("converted") or 0),
                str(row.get("blocked") or 0),
                str(row.get("failed") or 0),
                str(row.get("source_bytes") or 0),
                str(row.get("parquet_bytes") or 0),
            ])
            + " |"
        )
    lines += [
        "",
        "Source snapshot tapes are never deleted or rewritten by this command.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_incremental_outputs(
    payload: dict[str, Any],
    *,
    json_path: str | Path = DEFAULT_INCREMENTAL_JSON,
    report_path: str | Path = DEFAULT_INCREMENTAL_REPORT,
    cursor_path: str | Path = DEFAULT_INCREMENTAL_CURSOR,
) -> tuple[Path, Path, Path]:
    json_out = _write_json(json_path, payload)
    report_out = Path(report_path)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(render_incremental_report(payload), encoding="utf-8")
    cursor_out = _write_json(cursor_path, payload.get("cursor") or {})
    return json_out, report_out, cursor_out


def render_backfill_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Closed Market-Day Parquet Backfill",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Mode: `{payload.get('mode')}`",
        f"Status: `{payload.get('status')}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| :--- | ---: |",
    ]
    for key in (
        "market_day_count",
        "planned",
        "converted",
        "skipped",
        "blocked",
        "failed",
        "converted_family_count",
        "source_deleted_count",
        "source_bytes",
        "parquet_bytes",
    ):
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines += [
        "",
        "## Market Days",
        "",
        "| Event Slug | Status | Action | Families | Blockers |",
        "| :--- | :--- | :--- | ---: | :--- |",
    ]
    for row in payload.get("market_days") or []:
        blockers = ", ".join(row.get("blockers") or []) or "-"
        lines.append(
            "| "
            + " | ".join([
                str(row.get("event_slug") or ""),
                str(row.get("status") or ""),
                str(row.get("action") or ""),
                str(row.get("converted_family_count") or row.get("convertible_family_count") or 0),
                blockers,
            ])
            + " |"
        )
    lines += [
        "",
        "Source snapshot tapes are never deleted or rewritten by this command.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_backfill_outputs(
    payload: dict[str, Any],
    *,
    json_path: str | Path = DEFAULT_BACKFILL_JSON,
    report_path: str | Path = DEFAULT_BACKFILL_REPORT,
) -> tuple[Path, Path]:
    json_out = _write_json(json_path, payload)
    report_out = Path(report_path)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(render_backfill_report(payload), encoding="utf-8")
    return json_out, report_out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply closed market-day snapshot Parquet backfills."
    )
    parser.add_argument("mode", choices=("plan", "apply", "incremental-plan", "incremental-apply"))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--event-slug", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-scan-folders", type=int, default=25)
    parser.add_argument("--cursor", default=str(DEFAULT_INCREMENTAL_CURSOR))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--codec", default=DEFAULT_PARQUET_CODEC)
    parser.add_argument("--out", default=str(DEFAULT_BACKFILL_JSON))
    parser.add_argument("--report", default=str(DEFAULT_BACKFILL_REPORT))
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode in {"incremental-plan", "incremental-apply"}:
        out = args.out
        report = args.report
        if out == str(DEFAULT_BACKFILL_JSON):
            out = str(DEFAULT_INCREMENTAL_JSON)
        if report == str(DEFAULT_BACKFILL_REPORT):
            report = str(DEFAULT_INCREMENTAL_REPORT)
        payload = build_incremental_payload(
            snapshots_root=args.snapshots_root,
            archive_root=args.archive_root,
            apply=args.mode == "incremental-apply",
            as_of_date=args.as_of_date,
            event_slugs=args.event_slug or None,
            max_scan_folders=args.max_scan_folders,
            cursor_path=args.cursor,
            codec=args.codec,
            force=args.force,
        )
        json_out, report_out, cursor_out = write_incremental_outputs(
            payload,
            json_path=out,
            report_path=report,
            cursor_path=args.cursor,
        )
        print(
            "Incremental closed market-day Parquet conversion: "
            f"{payload['status']} mode={payload['mode']} "
            f"scanned={payload['summary']['scanned']} "
            f"changed={payload['summary']['changed']} "
            f"converted={payload['summary']['converted']} "
            f"blocked={payload['summary']['blocked']} "
            f"failed={payload['summary']['failed']}"
        )
        print(f"JSON written to {json_out}")
        print(f"Report written to {report_out}")
        print(f"Cursor written to {cursor_out}")
        return payload
    payload = build_backfill_payload(
        snapshots_root=args.snapshots_root,
        archive_root=args.archive_root,
        apply=args.mode == "apply",
        as_of_date=args.as_of_date,
        event_slugs=args.event_slug or None,
        limit=args.limit,
        codec=args.codec,
    )
    json_out, report_out = write_backfill_outputs(payload, json_path=args.out, report_path=args.report)
    print(
        "Closed market-day Parquet backfill: "
        f"{payload['status']} mode={payload['mode']} "
        f"converted={payload['summary']['converted']} "
        f"planned={payload['summary']['planned']} "
        f"blocked={payload['summary']['blocked']} "
        f"failed={payload['summary']['failed']}"
    )
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return payload


if __name__ == "__main__":
    main()
