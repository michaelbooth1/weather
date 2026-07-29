"""Folder-level manifests for market-day snapshot evidence and projections."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from weather.io import TieredTextError, open_tiered_text, sha256_file
from weather.forecast_payload_contracts import (
    NBM_NBP_ENCODING,
    NBM_NBP_MEDIA_TYPE,
)
from weather.collection.forecast_payload_cas import (
    ForecastPayloadCASIntegrityError,
    RAW_BYTES_HASH_ALGORITHM,
    SHARED_FORECAST_PAYLOAD_CAS_KIND,
    SHARED_FORECAST_PAYLOAD_CAS_ROOT,
    SHARED_FORECAST_PAYLOAD_SCOPE,
    shared_payload_ref,
    validate_nbm_shared_manifest_identity,
)
from weather.market.market_config import date_from_event_slug, market_id_from_slug
from weather.operations import event_metadata_validation
from weather.operations.storage_classes import classification_payload
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("event_day_manifest")
BACKFILL_SCHEMA_VERSION = "event_day_manifest_backfill_v0.1"
WRITER_VERSION = schema_version("event_day_manifest_writer")
MANIFEST_FILENAME = "event_day_manifest.json"
DEFAULT_MIN_GROWTH_HEADROOM_DAYS = 30.0
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_BACKFILL_JSON = data_path("backtest", "event_day_manifest_backfill.json")
DEFAULT_BACKFILL_REPORT = data_path("backtest", "event_day_manifest_backfill_report.md")
DEFAULT_EVENT_METADATA_VALIDATION = data_path("backtest", "event_metadata_validation.json")
PAYLOAD_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
PAYLOAD_BLOB_LINK_FAMILIES = (
    ("forecast_payloads", "forecast_payloads"),
    ("observation_payloads", "observation_payloads"),
)


@dataclass(frozen=True)
class EventDayArtifactFamily:
    name: str
    patterns: tuple[str, ...]
    required: bool = False
    requires_canonical_evidence: bool = False
    required_member_patterns: tuple[str, ...] = ()
    description: str = ""


EVENT_DAY_ARTIFACT_FAMILIES = (
    EventDayArtifactFamily(
        "snapshots",
        ("snapshots*.jsonl", "snapshots*.csv", "snapshots*.csv.gz"),
        required=True,
        requires_canonical_evidence=True,
        required_member_patterns=("snapshots*.jsonl",),
        description="Serving-time snapshot tape and its analysis projections.",
    ),
    EventDayArtifactFamily("features", ("features*.jsonl", "features*.csv", "features*.csv.gz")),
    EventDayArtifactFamily("components", ("components*.jsonl", "components*.csv", "components*.csv.gz")),
    EventDayArtifactFamily("forecasts", ("forecasts*.jsonl", "forecasts*.csv", "forecasts*.csv.gz")),
    EventDayArtifactFamily(
        "forecast_payloads",
        ("forecast_payloads*.jsonl", "forecast_payloads*.csv", "forecast_payloads/**/*.json"),
        required=True,
        requires_canonical_evidence=True,
        required_member_patterns=(
            "forecast_payloads*.jsonl",
            "forecast_payloads/sha256/*/*.json",
            "forecast_payloads/**/*.json",
        ),
        description="First-seen forecast payload evidence and its analysis projection.",
    ),
    EventDayArtifactFamily(
        "observation_payloads",
        (
            "observation_payloads*.jsonl",
            "observation_payloads*.csv",
            "observation_payloads/**/*.json",
        ),
        required=True,
        requires_canonical_evidence=True,
        required_member_patterns=(
            "observation_payloads/sha256/*/*.json",
            "observation_payloads/*.json",
            "observation_payloads/**/*.json",
        ),
        description="Raw provider observation payloads used to reconstruct settlement-valid labels.",
    ),
    EventDayArtifactFamily(
        "source_status",
        ("source_status*.jsonl", "source_status*.csv", "source_status*.csv.gz"),
        required=True,
        requires_canonical_evidence=True,
        required_member_patterns=("source_status*.jsonl",),
        description="Serving-time source availability, freshness, and degradation state.",
    ),
    EventDayArtifactFamily(
        "replay_inputs",
        ("replay_inputs*.jsonl", "replay_input_status.json"),
        required=True,
        requires_canonical_evidence=True,
        required_member_patterns=("replay_inputs*.jsonl",),
        description="Point-in-time replay inputs and reconstruction status.",
    ),
    EventDayArtifactFamily(
        "clob_capture_status",
        ("clob_capture_status*.jsonl", "clob_capture_status*.csv", "clob_capture_status*.csv.gz"),
        required=True,
        requires_canonical_evidence=True,
        required_member_patterns=("clob_capture_status*.jsonl",),
        description="Attempt-level CLOB capture health, including named failures and empty captures.",
    ),
    EventDayArtifactFamily("clob_tokens", ("clob_tokens.csv", "clob_tokens.jsonl")),
    EventDayArtifactFamily(
        "order_books",
        (
            "order_books.jsonl",
            "order_books.jsonl.gz",
            "order_books_summary.csv",
            "order_books_long.csv",
            "order_books_long.csv.gz",
        ),
    ),
    EventDayArtifactFamily(
        "price_history",
        (
            "price_history.jsonl",
            "price_history_raw_manifest.jsonl",
            "price_history_raw/**/*.json",
            "price_history_raw/*.json",
            "price_history.csv",
            "price_history.csv.gz",
            "price_history_deduped.csv",
        ),
    ),
    EventDayArtifactFamily("market_ws_events", ("market_ws.jsonl", "market_ws_events.csv", "market_ws_events.csv.gz")),
    EventDayArtifactFamily("clob_features", ("clob_features*.jsonl", "clob_features*.csv", "clob_features*.csv.gz")),
    EventDayArtifactFamily(
        "snapshot_explanations",
        ("snapshot_explanations*.jsonl", "snapshot_explanations*.csv", "snapshot_explanations*.csv.gz"),
    ),
    EventDayArtifactFamily("variant_predictions", ("variant_predictions*.jsonl", "variant_predictions*.csv", "variant_predictions*.csv.gz")),
    EventDayArtifactFamily("settlement", ("settlement.json", "settlement*.jsonl", "settlement*.csv")),
    EventDayArtifactFamily("market_making_runs", ("mm_runs/**/*", "market_making/**/*", "paper_trading/**/*")),
    EventDayArtifactFamily("taker_runs", ("taker_runs/**/*",)),
)

REQUIRED_EVENT_DAY_ARTIFACT_FAMILY_NAMES = tuple(
    family.name for family in EVENT_DAY_ARTIFACT_FAMILIES if family.required
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: str | Path, text: str) -> Path:
    """Durably replace ``path`` without exposing a partial JSON document."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def _atomic_write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    return _atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


def event_day_manifest_path(folder: str | Path) -> Path:
    return Path(folder) / MANIFEST_FILENAME


def _data_relative_path(path: Path, snapshots_root: Path) -> str:
    data_root = snapshots_root.parent
    try:
        return path.relative_to(data_root).as_posix()
    except ValueError:
        return path.as_posix()


def _folder_relative_path(path: Path, folder: Path) -> str:
    return path.relative_to(folder).as_posix()


_SOURCE_KEYS = ("source", "source_id", "source_family", "provider")
_RELEASE_KEYS = (
    "release_id",
    "serving_release_id",
    "model_release_id",
    "model_version",
    "artifact_hash",
    "postprocess_config_hash",
    "calibration_hash",
    "configuration_hash",
)
_MAX_PROVENANCE_VALUES = 25
_MAX_NESTED_METADATA_OBJECTS = 10_000


def _scalar_text(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, (dict, list, tuple, set)):
        return None
    return str(value)


def _runtime_identity_from_mapping(row: dict[str, Any]) -> dict[str, Any] | None:
    nested = row.get("runtime_identity")
    if isinstance(nested, dict):
        if isinstance(nested.get("current_identity"), dict):
            nested = nested["current_identity"]
        if isinstance(nested.get("process_identity"), dict):
            nested = nested["process_identity"]
    else:
        nested = {}
    runtime = {
        "schema_version": (
            nested.get("schema_version")
            or row.get("runtime_identity_schema_version")
        ),
        "git_branch": nested.get("git_branch") or row.get("runtime_git_branch"),
        "git_commit": nested.get("git_commit") or row.get("runtime_git_commit"),
        "git_dirty": nested.get("git_dirty") if "git_dirty" in nested else row.get("runtime_git_dirty"),
        "dirty_fingerprint": nested.get("dirty_fingerprint") or row.get("runtime_dirty_fingerprint"),
        "source_fingerprint": nested.get("source_fingerprint") or row.get("runtime_source_fingerprint"),
        "python_version": nested.get("python_version") or row.get("runtime_python_version"),
        "runtime_code_state": row.get("runtime_code_state"),
    }
    runtime = {key: value for key, value in runtime.items() if value not in (None, "")}
    if not runtime:
        return None
    commit = runtime.get("git_commit") or "unknown_commit"
    source = runtime.get("source_fingerprint") or "unknown_source"
    dirty = runtime.get("dirty_fingerprint")
    if not dirty and runtime.get("git_dirty") not in (None, "", False, "false", "False", 0):
        dirty = "dirty"
    runtime["runtime_key"] = f"{commit}|dirty:{dirty or 'clean_or_unknown'}|src:{source}"
    return runtime


def _release_identity_from_mapping(row: dict[str, Any]) -> dict[str, Any] | None:
    release = {
        key: _scalar_text(row.get(key))
        for key in _RELEASE_KEYS
        if _scalar_text(row.get(key)) is not None
    }
    return release or None


def _walk_metadata_mappings(payload: Any):
    pending = [payload]
    visited = 0
    while pending and visited < _MAX_NESTED_METADATA_OBJECTS:
        item = pending.pop()
        if isinstance(item, dict):
            visited += 1
            yield item
            pending.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            pending.extend(reversed(item))


def _provenance_accumulator() -> dict[str, Any]:
    return {
        "schema_versions": set(),
        "source_ids": set(),
        "release_identities": {},
        "runtime_identities": {},
        "metadata_object_count": 0,
        "metadata_scan_truncated": False,
    }


def _collect_mapping_provenance(
    accumulator: dict[str, Any],
    row: dict[str, Any],
    *,
    collect_schema: bool = True,
) -> None:
    accumulator["metadata_object_count"] += 1
    schema = _scalar_text(row.get("schema_version")) if collect_schema else None
    if schema:
        accumulator["schema_versions"].add(schema)
    for key in _SOURCE_KEYS:
        value = _scalar_text(row.get(key))
        if value:
            accumulator["source_ids"].add(value)
    release = _release_identity_from_mapping(row)
    if release:
        key = json.dumps(release, sort_keys=True, separators=(",", ":"))
        accumulator["release_identities"][key] = release
    runtime = _runtime_identity_from_mapping(row)
    if runtime:
        accumulator["runtime_identities"][runtime["runtime_key"]] = runtime


def _collect_payload_provenance(accumulator: dict[str, Any], payload: Any) -> None:
    before = accumulator["metadata_object_count"]
    schema_roots = {id(payload)} if isinstance(payload, dict) else {
        id(item) for item in payload if isinstance(item, dict)
    } if isinstance(payload, list) else set()
    for row in _walk_metadata_mappings(payload):
        _collect_mapping_provenance(
            accumulator,
            row,
            collect_schema=id(row) in schema_roots,
        )
    if accumulator["metadata_object_count"] - before >= _MAX_NESTED_METADATA_OBJECTS:
        accumulator["metadata_scan_truncated"] = True


def _inspection_payload(
    accumulator: dict[str, Any],
    *,
    row_count: int | None,
    validation_status: str,
    validation_detail: str | None = None,
    schema_applicable: bool = True,
) -> dict[str, Any]:
    schema_versions = sorted(accumulator["schema_versions"])[:_MAX_PROVENANCE_VALUES]
    source_ids = sorted(accumulator["source_ids"])[:_MAX_PROVENANCE_VALUES]
    releases = [
        accumulator["release_identities"][key]
        for key in sorted(accumulator["release_identities"])[:_MAX_PROVENANCE_VALUES]
    ]
    runtimes = [
        accumulator["runtime_identities"][key]
        for key in sorted(accumulator["runtime_identities"])[:_MAX_PROVENANCE_VALUES]
    ]
    if not schema_applicable:
        schema_status = "NOT_APPLICABLE"
    elif schema_versions:
        schema_status = "DECLARED"
    else:
        schema_status = "MISSING"
    return {
        "row_count": row_count,
        "schema_version": schema_versions[0] if len(schema_versions) == 1 else None,
        "schema_versions": schema_versions,
        "schema_status": schema_status,
        "validation_status": validation_status,
        "validation_detail": validation_detail,
        "source_ids": source_ids,
        "release_identities": releases,
        "runtime_identities": runtimes,
        "metadata_object_count": accumulator["metadata_object_count"],
        "metadata_scan_truncated": accumulator["metadata_scan_truncated"],
    }


def _inspect_file(path: Path) -> dict[str, Any]:
    """Validate a structured artifact and extract bounded provenance metadata."""

    accumulator = _provenance_accumulator()
    name = path.name.lower()
    suffix = path.suffix.lower()
    try:
        if suffix == ".jsonl" or name.endswith(".jsonl.gz"):
            row_count = 0
            with open_tiered_text(path, encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError as exc:
                        return _inspection_payload(
                            accumulator,
                            row_count=row_count,
                            validation_status="BLOCK",
                            validation_detail=f"invalid JSON on line {line_number}: {exc.msg}",
                        )
                    row_count += 1
                    _collect_payload_provenance(accumulator, payload)
            return _inspection_payload(accumulator, row_count=row_count, validation_status="PASS")
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            _collect_payload_provenance(accumulator, payload)
            if isinstance(payload, list):
                row_count = len(payload)
            else:
                row_count = 1 if payload else 0
            return _inspection_payload(accumulator, row_count=row_count, validation_status="PASS")
        if suffix == ".csv" or name.endswith(".csv.gz"):
            row_count = 0
            with open_tiered_text(
                path,
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    return _inspection_payload(
                        accumulator,
                        row_count=0,
                        validation_status="BLOCK",
                        validation_detail="CSV header is missing",
                    )
                for row in reader:
                    row_count += 1
                    _collect_mapping_provenance(accumulator, row)
            return _inspection_payload(accumulator, row_count=row_count, validation_status="PASS")
        if suffix == ".parquet":
            import pyarrow.parquet as pq

            row_count = int(pq.ParquetFile(path).metadata.num_rows)
            return _inspection_payload(
                accumulator,
                row_count=row_count,
                validation_status="PASS",
                schema_applicable=False,
            )
    except TieredTextError as exc:
        return _inspection_payload(
            accumulator,
            row_count=0,
            validation_status="BLOCK",
            validation_detail=f"{type(exc).__name__}: {exc}",
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error, ValueError) as exc:
        return _inspection_payload(
            accumulator,
            row_count=None,
            validation_status="BLOCK",
            validation_detail=f"{type(exc).__name__}: {exc}",
        )
    return _inspection_payload(
        accumulator,
        row_count=_row_count(path),
        validation_status="NOT_APPLICABLE",
        schema_applicable=False,
    )


def _row_count(path: Path) -> int | None:
    name = path.name.lower()
    suffix = path.suffix.lower()
    try:
        if suffix == ".jsonl" or name.endswith(".jsonl.gz"):
            with open_tiered_text(path, encoding="utf-8") as handle:
                return sum(1 for line in handle if line.strip())
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return len(payload)
            return 1 if payload else 0
        if suffix == ".csv" or name.endswith(".csv.gz"):
            with open_tiered_text(
                path,
                encoding="utf-8",
                newline="",
            ) as handle:
                rows = sum(1 for _ in csv.reader(handle))
            return max(0, rows - 1)
        if suffix == ".parquet":
            import pyarrow.parquet as pq

            return int(pq.ParquetFile(path).metadata.num_rows)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        csv.Error,
        TieredTextError,
    ):
        return None
    return None


def _matches_family(path: Path, family: EventDayArtifactFamily) -> bool:
    rel = path.as_posix()
    return any(path.match(pattern) or Path(rel).match(pattern) for pattern in family.patterns)


def _iter_family_files(folder: Path, family: EventDayArtifactFamily) -> list[Path]:
    files: set[Path] = set()
    for pattern in family.patterns:
        files.update(path for path in folder.glob(pattern) if path.is_file())
    return sorted(files)


def _file_record(
    path: Path,
    *,
    folder: Path,
    snapshots_root: Path,
    previous_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stat = path.stat()
    data_rel = _data_relative_path(path, snapshots_root)
    classification = classification_payload(data_rel)
    if (
        previous_record
        and previous_record.get("path") == _folder_relative_path(path, folder)
        and previous_record.get("data_path") == data_rel
        and int(previous_record.get("bytes") or -1) == int(stat.st_size)
        and int(previous_record.get("modified_at_ns") or -1) == int(stat.st_mtime_ns)
        and previous_record.get("storage_class") == classification["storage_class"]
        and previous_record.get("artifact_family") == classification["artifact_family"]
        and previous_record.get("validation_status") != "BLOCK"
        and len(str(previous_record.get("sha256") or "")) == 64
    ):
        # Fast incremental mode trusts nanosecond mtime + size for unchanged
        # local append-only tapes.  A non-incremental audit always re-hashes.
        return dict(previous_record)
    inspection = _inspect_file(path)
    return {
        "path": _folder_relative_path(path, folder),
        "data_path": data_rel,
        "role": classification["storage_class"],
        "storage_class": classification["storage_class"],
        "artifact_family": classification["artifact_family"],
        "source": inspection["source_ids"],
        "schema_version": inspection["schema_version"],
        "schema_versions": inspection["schema_versions"],
        "schema_status": inspection["schema_status"],
        "validation_status": inspection["validation_status"],
        "validation_detail": inspection["validation_detail"],
        "row_count": inspection["row_count"],
        "release_identities": inspection["release_identities"],
        "runtime_identities": inspection["runtime_identities"],
        "metadata_scan_truncated": inspection["metadata_scan_truncated"],
        "bytes": int(stat.st_size),
        "sha256": sha256_file(path),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "modified_at_ns": int(stat.st_mtime_ns),
        "retention_class": classification["retention_class"],
        "rebuild_source": classification["rebuild_source"],
        "protected": classification["protected"],
    }


def _manifest_hash_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "manifest_hash"}


def manifest_content_hash(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(_manifest_hash_payload(manifest), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def manifest_hash_valid(manifest: dict[str, Any]) -> bool:
    return bool(manifest.get("manifest_hash")) and manifest.get("manifest_hash") == manifest_content_hash(manifest)


def _event_metadata_validation_proof(
    *,
    market_id: str | None,
    target_date: date | None,
    event_slug: str,
    path: str | Path | None = DEFAULT_EVENT_METADATA_VALIDATION,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(path) if path else None
    if payload is None and path and path.exists():
        payload = event_metadata_validation.load_validation_payload(path)
    if not payload:
        return {
            "status": "MISSING",
            "required": False,
            "path": str(path) if path else None,
            "reason": "event metadata validation artifact not available",
            "validation_hash": None,
        }
    gate = event_metadata_validation.gate_for_market(payload, market_id or "")
    target_text = target_date.isoformat() if target_date else None
    target_matches = not target_text or gate.get("target_date") == target_text
    event_matches = not gate.get("event_slug") or gate.get("event_slug") == event_slug
    # The default operational proof is for one current fleet date. It is not a
    # negative assertion about every retained historical day. Treat a proof
    # for another target date as explicitly out of scope; if the target date
    # does match, an event/market disagreement remains a hard blocker.
    if target_text and gate.get("target_date") and not target_matches:
        status = "NOT_APPLICABLE"
        required = False
        reason = "event metadata validation artifact covers a different target date"
    else:
        status = "PASS" if gate.get("ok") and event_matches else "BLOCK"
        required = True
        reason = (
            "event metadata validation row passes"
            if status == "PASS"
            else gate.get("reason")
        )
    return {
        "status": status,
        "required": required,
        "path": str(path) if path else None,
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "validation_hash": payload.get("validation_hash"),
        "target_date": payload.get("target_date"),
        "market_id": market_id,
        "event_slug": event_slug,
        "gate": gate,
        "target_matches": target_matches,
        "event_matches": event_matches,
        "reason": reason,
    }


def release_runtime_identity_summary(file_records: list[dict[str, Any]]) -> dict[str, Any]:
    sources: set[str] = set()
    releases: dict[str, dict[str, Any]] = {}
    runtimes: dict[str, dict[str, Any]] = {}
    for record in file_records:
        sources.update(str(value) for value in record.get("source") or [] if value not in (None, ""))
        for release in record.get("release_identities") or []:
            key = json.dumps(release, sort_keys=True, separators=(",", ":"))
            releases[key] = release
        for runtime in record.get("runtime_identities") or []:
            key = str(runtime.get("runtime_key") or json.dumps(runtime, sort_keys=True))
            runtimes[key] = runtime
    observed_release_rows = [releases[key] for key in sorted(releases)]
    runtime_rows = [runtimes[key] for key in sorted(runtimes)]
    release_aliases = ("release_id", "serving_release_id", "model_release_id")
    releases_by_id: dict[str, dict[str, Any]] = {}
    partial_release_rows = []
    for row in observed_release_rows:
        explicit_values = {
            str(row.get(key))
            for key in release_aliases
            if row.get(key) not in (None, "")
        }
        if not explicit_values:
            partial_release_rows.append(row)
            continue
        for release_id in sorted(explicit_values):
            summary = releases_by_id.setdefault(
                release_id,
                {
                    "release_id": release_id,
                    "identity_aliases": set(),
                    "evidence_row_count": 0,
                },
            )
            summary["evidence_row_count"] += 1
            summary["identity_aliases"].update(
                key for key in release_aliases if str(row.get(key) or "") == release_id
            )
    release_rows = [
        {
            **releases_by_id[release_id],
            "identity_aliases": sorted(releases_by_id[release_id]["identity_aliases"]),
        }
        for release_id in sorted(releases_by_id)
    ]
    if not release_rows:
        release_status = "MISSING" if not observed_release_rows else "INCOMPLETE"
    elif len(release_rows) == 1:
        release_status = "SINGLE"
    else:
        release_status = "MIXED"
    if not runtime_rows:
        runtime_status = "MISSING"
    elif len(runtime_rows) > 1:
        runtime_status = "MIXED"
    elif not runtime_rows[0].get("git_commit") or not runtime_rows[0].get("source_fingerprint"):
        runtime_status = "INCOMPLETE"
    else:
        runtime_status = "SINGLE"
    proof_grade_blockers = []
    if release_status != "SINGLE":
        proof_grade_blockers.append(f"release_identity_{release_status.lower()}")
    if runtime_status != "SINGLE":
        proof_grade_blockers.append(f"runtime_identity_{runtime_status.lower()}")
    return {
        "source_ids": sorted(sources),
        "release_identity_status": release_status,
        "release_identity_count": len(release_rows),
        "release_identities": release_rows,
        "partial_release_identity_count": len(partial_release_rows),
        "partial_release_identities": partial_release_rows,
        "runtime_identity_status": runtime_status,
        "runtime_identity_count": len(runtime_rows),
        "mixed_runtime_identity": len(runtime_rows) > 1,
        "runtime_identities": runtime_rows,
        "proof_grade_status": "PASS" if not proof_grade_blockers else "BLOCK",
        "proof_grade_blockers": proof_grade_blockers,
    }


def _qualifying_canonical_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return nonempty, structurally valid canonical records for a required family."""

    qualifying = []
    for record in records:
        if (
            record.get("storage_class") != "canonical_evidence"
            or record.get("validation_status") != "PASS"
        ):
            continue
        row_count = record.get("row_count")
        if row_count is not None:
            try:
                if int(row_count) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
        qualifying.append(record)
    return qualifying


def _required_family_evidence(
    family: EventDayArtifactFamily,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    canonical = _qualifying_canonical_records(records)
    required_members = [
        record
        for record in canonical
        if not family.required_member_patterns
        or any(
            Path(str(record.get("path") or "")).match(pattern)
            for pattern in family.required_member_patterns
        )
    ]
    if not family.required:
        status = "NOT_REQUIRED"
    elif not records:
        status = "MISSING"
    elif family.requires_canonical_evidence and not canonical:
        status = "CANONICAL_EVIDENCE_MISSING_OR_EMPTY"
    elif family.required_member_patterns and not required_members:
        status = "REQUIRED_CANONICAL_MEMBER_MISSING_OR_EMPTY"
    else:
        status = "PASS"
    return {
        "status": status,
        "requires_canonical_evidence": family.requires_canonical_evidence,
        "required_member_patterns": list(family.required_member_patterns),
        "canonical_file_count": sum(
            1 for record in records if record.get("storage_class") == "canonical_evidence"
        ),
        "qualifying_canonical_file_count": len(canonical),
        "qualifying_required_member_count": len(required_members),
    }


def _canonical_payload_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _payload_blob_link_validation(
    folder: Path,
    *,
    shared_cas_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify manifest-row links to immutable content-addressed payloads.

    File-level inventory hashes are not enough here: the JSONL row must name
    the one canonical path implied by its payload hash, and those exact bytes
    must recompute the same hash. Unreferenced blobs fail closed as orphans.
    """

    folder = folder.resolve()
    expected_shared_cas_root = Path(
        shared_cas_root or SHARED_FORECAST_PAYLOAD_CAS_ROOT
    ).resolve()
    family_results: list[dict[str, Any]] = []
    total_rows = 0
    total_blobs = 0
    total_linked = 0
    total_shared_linked = 0
    total_issues = 0
    shared_dependencies_by_digest: dict[str, dict[str, Any]] = {}
    for artifact_family, path_prefix in PAYLOAD_BLOB_LINK_FAMILIES:
        manifest_paths = sorted(
            path
            for path in folder.glob(f"{path_prefix}*.jsonl")
            if path.is_file() and not path.is_symlink()
        )
        blob_root = folder / path_prefix
        blob_paths = sorted(
            path
            for path in blob_root.rglob("*.json")
            if path.is_file() or path.is_symlink()
        ) if blob_root.exists() else []
        issues: list[dict[str, Any]] = []
        referenced_paths: set[Path] = set()
        shared_linked_count = 0
        row_count = 0

        if not manifest_paths:
            issues.append({
                "code": "payload_manifest_missing",
                "artifact_family": artifact_family,
            })

        for manifest_path in manifest_paths:
            manifest_rel = _folder_relative_path(manifest_path, folder)
            try:
                handle = manifest_path.open("r", encoding="utf-8")
            except OSError as exc:
                issues.append({
                    "code": "payload_manifest_unreadable",
                    "artifact_family": artifact_family,
                    "manifest_path": manifest_rel,
                    "detail": f"{type(exc).__name__}: {exc}",
                })
                continue
            with handle:
                for line_number, line in enumerate(handle, start=1):
                    text = line.strip()
                    if not text:
                        continue
                    row_count += 1
                    try:
                        row = json.loads(text)
                    except json.JSONDecodeError as exc:
                        issues.append({
                            "code": "payload_manifest_row_invalid_json",
                            "artifact_family": artifact_family,
                            "manifest_path": manifest_rel,
                            "line_number": line_number,
                            "detail": exc.msg,
                        })
                        continue
                    if not isinstance(row, dict):
                        issues.append({
                            "code": "payload_manifest_row_not_object",
                            "artifact_family": artifact_family,
                            "manifest_path": manifest_rel,
                            "line_number": line_number,
                        })
                        continue

                    digest = str(row.get("payload_hash") or "")
                    raw_path_text = str(row.get("raw_payload_path") or "").strip()
                    shared_reference = (
                        artifact_family == "forecast_payloads"
                        and row.get("payload_storage_scope")
                        == SHARED_FORECAST_PAYLOAD_SCOPE
                    )
                    row_ref = {
                        "artifact_family": artifact_family,
                        "manifest_path": manifest_rel,
                        "line_number": line_number,
                        "snapshot_id": row.get("snapshot_id"),
                        "source": row.get("source"),
                    }
                    if not PAYLOAD_HASH_RE.fullmatch(digest):
                        issues.append({**row_ref, "code": "payload_hash_invalid"})
                        continue
                    if not raw_path_text:
                        issues.append({**row_ref, "code": "raw_payload_path_missing"})
                        continue

                    raw_path = Path(raw_path_text)
                    candidate = (
                        raw_path.resolve()
                        if raw_path.is_absolute()
                        else (folder / raw_path).resolve()
                    )
                    if shared_reference:
                        expected_ref = shared_payload_ref(digest)
                        declared_ref = str(row.get("payload_ref") or "")
                        expected_shared_path = expected_shared_cas_root.joinpath(
                            *expected_ref.split("/")
                        ).resolve()
                        if (
                            row.get("payload_cas_kind")
                            != SHARED_FORECAST_PAYLOAD_CAS_KIND
                            or row.get("payload_hash_algorithm")
                            != RAW_BYTES_HASH_ALGORITHM
                            or str(row.get("payload_encoding") or "").lower()
                            != NBM_NBP_ENCODING
                            or row.get("payload_media_type")
                            != NBM_NBP_MEDIA_TYPE
                            or row.get("raw_payload_retained") is not True
                            or declared_ref != expected_ref
                            or not raw_path.is_absolute()
                            or candidate != expected_shared_path
                        ):
                            issues.append({
                                **row_ref,
                                "code": "shared_payload_reference_invalid",
                                "raw_payload_path": raw_path_text,
                                "expected_ref": expected_ref,
                            })
                            continue
                        try:
                            validate_nbm_shared_manifest_identity(row)
                        except ForecastPayloadCASIntegrityError as exc:
                            issues.append({
                                **row_ref,
                                "code": "shared_payload_identity_invalid",
                                "detail": str(exc),
                            })
                            continue
                    else:
                        try:
                            candidate.relative_to(folder)
                        except ValueError:
                            issues.append({
                                **row_ref,
                                "code": "raw_payload_path_outside_event_folder",
                                "raw_payload_path": raw_path_text,
                            })
                            continue

                        expected = (
                            blob_root
                            / "sha256"
                            / digest[:2]
                            / f"{digest}.json"
                        ).resolve()
                        if candidate != expected:
                            issues.append({
                                **row_ref,
                                "code": "raw_payload_path_not_content_addressed",
                                "raw_payload_path": _folder_relative_path(candidate, folder),
                                "expected_path": _folder_relative_path(expected, folder),
                            })
                            continue
                        referenced_paths.add(candidate)
                    candidate_display = (
                        candidate.as_posix()
                        if shared_reference
                        else _folder_relative_path(candidate, folder)
                    )
                    if candidate.is_symlink():
                        issues.append({
                            **row_ref,
                            "code": "raw_payload_blob_symlink_forbidden",
                            "raw_payload_path": candidate_display,
                        })
                        continue
                    if not candidate.is_file():
                        issues.append({
                            **row_ref,
                            "code": "raw_payload_blob_missing",
                            "raw_payload_path": candidate_display,
                        })
                        continue
                    try:
                        stored = candidate.read_bytes()
                    except OSError as exc:
                        issues.append({
                            **row_ref,
                            "code": "raw_payload_blob_unreadable",
                            "raw_payload_path": candidate_display,
                            "detail": f"{type(exc).__name__}: {exc}",
                        })
                        continue
                    canonical_bytes = (
                        stored
                        if shared_reference
                        else (stored[:-1] if stored.endswith(b"\n") else stored)
                    )
                    actual_digest = hashlib.sha256(canonical_bytes).hexdigest()
                    if actual_digest != digest:
                        issues.append({
                            **row_ref,
                            "code": "raw_payload_blob_hash_mismatch",
                            "raw_payload_path": candidate_display,
                            "actual_payload_hash": actual_digest,
                        })
                        continue
                    if not shared_reference:
                        try:
                            decoded = json.loads(canonical_bytes.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                            issues.append({
                                **row_ref,
                                "code": "raw_payload_blob_invalid_json",
                                "raw_payload_path": candidate_display,
                                "detail": f"{type(exc).__name__}: {exc}",
                            })
                            continue
                        if _canonical_payload_bytes(decoded) != canonical_bytes:
                            issues.append({
                                **row_ref,
                                "code": "raw_payload_blob_not_canonical_json",
                                "raw_payload_path": candidate_display,
                            })
                            continue
                    declared_bytes = row.get("payload_bytes")
                    if declared_bytes not in (None, ""):
                        try:
                            bytes_match = int(declared_bytes) == len(canonical_bytes)
                        except (TypeError, ValueError):
                            bytes_match = False
                        if not bytes_match:
                            issues.append({
                                **row_ref,
                                "code": "payload_bytes_mismatch",
                                "raw_payload_path": candidate_display,
                                "actual_payload_bytes": len(canonical_bytes),
                            })
                            continue
                    if shared_reference:
                        shared_linked_count += 1
                        dependency = shared_dependencies_by_digest.get(digest)
                        if dependency is None:
                            dependency_data_path = candidate.relative_to(
                                expected_shared_cas_root.parent
                            ).as_posix()
                            shared_dependencies_by_digest[digest] = {
                                "path": candidate.as_posix(),
                                "data_path": dependency_data_path,
                                "raw_payload_path": candidate.as_posix(),
                                "payload_ref": expected_ref,
                                "payload_hash": digest,
                                "sha256": digest,
                                "bytes": len(canonical_bytes),
                                "storage_class": "canonical_evidence",
                                "artifact_family": "shared_forecast_payload_cas",
                                "reference_count": 1,
                            }
                        elif dependency["raw_payload_path"] != candidate.as_posix():
                            issues.append({
                                **row_ref,
                                "code": "shared_payload_digest_has_multiple_paths",
                                "raw_payload_path": candidate.as_posix(),
                                "first_raw_payload_path": dependency[
                                    "raw_payload_path"
                                ],
                            })
                        else:
                            dependency["reference_count"] += 1

        blob_path_set = {path.resolve() for path in blob_paths}
        for orphan in sorted(blob_path_set - referenced_paths):
            issues.append({
                "code": "raw_payload_blob_orphan",
                "artifact_family": artifact_family,
                "raw_payload_path": _folder_relative_path(orphan, folder),
            })

        result = {
            "artifact_family": artifact_family,
            "status": "PASS" if row_count > 0 and not issues else "BLOCK",
            "manifest_paths": [
                _folder_relative_path(path, folder) for path in manifest_paths
            ],
            "manifest_row_count": row_count,
            "blob_count": len(blob_path_set),
            "linked_blob_count": len(blob_path_set & referenced_paths),
            "shared_linked_blob_count": shared_linked_count,
            "issue_count": len(issues),
            "issues": issues,
        }
        family_results.append(result)
        total_rows += row_count
        total_blobs += len(blob_path_set)
        total_linked += len(blob_path_set & referenced_paths)
        total_shared_linked += shared_linked_count
        total_issues += len(issues)

    return {
        "status": (
            "PASS"
            if family_results
            and all(row["status"] == "PASS" for row in family_results)
            else "BLOCK"
        ),
        "families": family_results,
        "shared_dependencies": [
            shared_dependencies_by_digest[digest]
            for digest in sorted(shared_dependencies_by_digest)
        ],
        "summary": {
            "manifest_row_count": total_rows,
            "blob_count": total_blobs,
            "linked_blob_count": total_linked,
            "shared_linked_blob_count": total_shared_linked,
            "shared_dependency_count": len(shared_dependencies_by_digest),
            "issue_count": total_issues,
        },
    }


def _backup_verification(
    file_records: list[dict[str, Any]],
    backup_root: str | Path | None,
) -> dict[str, Any]:
    canonical = [record for record in file_records if record.get("storage_class") == "canonical_evidence"]
    expected_bytes = sum(int(record.get("bytes") or 0) for record in canonical)
    base = Path(backup_root) if backup_root else None
    if not canonical:
        return {
            "status": "NOT_APPLICABLE",
            "backup_root": str(base) if base else None,
            "expected_file_count": 0,
            "expected_bytes": 0,
            "verified_file_count": 0,
            "verified_bytes": 0,
            "missing_files": [],
            "changed_files": [],
        }
    if base is None:
        return {
            "status": "NOT_CONFIGURED",
            "backup_root": None,
            "expected_file_count": len(canonical),
            "expected_bytes": expected_bytes,
            "verified_file_count": 0,
            "verified_bytes": 0,
            "missing_files": [],
            "changed_files": [],
        }
    missing: list[str] = []
    changed: list[str] = []
    verified_count = 0
    verified_bytes = 0
    for record in canonical:
        rel = str(record.get("data_path") or record.get("path") or "")
        mirror = base / Path(rel)
        if not mirror.is_file():
            missing.append(rel)
            continue
        try:
            size_matches = int(mirror.stat().st_size) == int(record.get("bytes") or 0)
            hash_matches = size_matches and sha256_file(mirror) == record.get("sha256")
        except OSError:
            hash_matches = False
        if not hash_matches:
            changed.append(rel)
            continue
        verified_count += 1
        verified_bytes += int(record.get("bytes") or 0)
    return {
        "status": "PASS" if not missing and not changed else "BLOCK",
        "backup_root": str(base),
        "expected_file_count": len(canonical),
        "expected_bytes": expected_bytes,
        "verified_file_count": verified_count,
        "verified_bytes": verified_bytes,
        "missing_files": missing,
        "changed_files": changed,
    }


def _load_optional_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _restore_proof_verification(
    file_records: list[dict[str, Any]],
    *,
    event_slug: str,
    restore_proof_path: str | Path | None = None,
    restore_proof_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical = [record for record in file_records if record.get("storage_class") == "canonical_evidence"]
    if restore_proof_payload is None:
        restore_proof_payload = _load_optional_json(restore_proof_path)
    base = {
        "path": str(restore_proof_path) if restore_proof_path else None,
        "expected_file_count": len(canonical),
        "verified_file_count": 0,
        "missing_or_changed_files": [],
    }
    if not canonical:
        return {**base, "status": "NOT_APPLICABLE", "reason": "no canonical evidence files"}
    if not restore_proof_payload:
        return {**base, "status": "NOT_CONFIGURED", "reason": "restore proof not supplied"}
    if str(restore_proof_payload.get("status") or "").upper() != "PASS":
        return {**base, "status": "BLOCK", "reason": "restore proof status is not PASS"}
    if restore_proof_payload.get("event_slug") != event_slug:
        return {**base, "status": "BLOCK", "reason": "restore proof event_slug mismatch"}
    proof_files: dict[str, str] = {}
    for row in restore_proof_payload.get("files") or []:
        if not isinstance(row, dict):
            continue
        path = str(row.get("data_path") or row.get("path") or "")
        digest = str(row.get("sha256") or "")
        if path and digest:
            proof_files[path] = digest
    missing_or_changed = []
    verified_count = 0
    for record in canonical:
        data_rel = str(record.get("data_path") or "")
        folder_rel = str(record.get("path") or "")
        digest = proof_files.get(data_rel) or proof_files.get(folder_rel)
        if digest != record.get("sha256"):
            missing_or_changed.append(data_rel or folder_rel)
        else:
            verified_count += 1
    return {
        **base,
        "status": "PASS" if not missing_or_changed else "BLOCK",
        "reason": "all canonical hashes restored and verified" if not missing_or_changed else "restore proof is incomplete or stale",
        "verified_file_count": verified_count,
        "missing_or_changed_files": missing_or_changed,
        "proof_generated_at_utc": restore_proof_payload.get("generated_at_utc"),
        "proof_hash": hashlib.sha256(
            json.dumps(restore_proof_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def _inventory_hash_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": manifest.get("schema_version"),
        "writer_version": manifest.get("writer_version"),
        "identity": manifest.get("identity"),
        "event_metadata_validation": manifest.get("event_metadata_validation"),
        "release_runtime_identity": manifest.get("release_runtime_identity"),
        "payload_blob_links": manifest.get("payload_blob_links"),
        "artifact_families": manifest.get("artifact_families"),
    }


def inventory_content_hash(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(_inventory_hash_payload(manifest), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_event_day_manifest(
    folder: str | Path,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    event_metadata_validation_payload: dict[str, Any] | None = None,
    event_metadata_validation_path: str | Path | None = DEFAULT_EVENT_METADATA_VALIDATION,
    backup_root: str | Path | None = None,
    restore_proof_path: str | Path | None = None,
    restore_proof_payload: dict[str, Any] | None = None,
    previous_manifest: dict[str, Any] | None = None,
    reuse_unchanged: bool = False,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    folder = Path(folder)
    snapshots_root = Path(snapshots_root)
    event_slug = folder.name
    target_date = date_from_event_slug(event_slug)
    market_id = market_id_from_slug(event_slug)
    previous_records = (
        {str(row.get("path")): row for row in _manifest_file_records(previous_manifest or {}) if row.get("path")}
        if reuse_unchanged and previous_manifest and manifest_hash_valid(previous_manifest)
        else {}
    )
    families = []
    seen_paths: set[Path] = set()
    for family in EVENT_DAY_ARTIFACT_FAMILIES:
        files = _iter_family_files(folder, family)
        seen_paths.update(files)
        records = [
            _file_record(
                path,
                folder=folder,
                snapshots_root=snapshots_root,
                previous_record=previous_records.get(_folder_relative_path(path, folder)),
            )
            for path in files
        ]
        required_evidence = _required_family_evidence(family, records)
        families.append({
            "artifact_family": family.name,
            "required": family.required,
            "requires_canonical_evidence": family.requires_canonical_evidence,
            "required_member_patterns": list(family.required_member_patterns),
            "required_evidence": required_evidence,
            "status": (
                "present"
                if records and (not family.required or required_evidence["status"] == "PASS")
                else ("missing_required" if family.required else "missing_optional")
            ),
            "description": family.description,
            "files": records,
            "file_count": len(records),
            "bytes": sum(int(row.get("bytes") or 0) for row in records),
        })

    extra_files = [
        path
        for path in sorted(folder.rglob("*"))
        if path.is_file()
        and path.name != MANIFEST_FILENAME
        and path not in seen_paths
        and not any(part.startswith(".") for part in path.relative_to(folder).parts)
    ]
    if extra_files:
        records = [
            _file_record(
                path,
                folder=folder,
                snapshots_root=snapshots_root,
                previous_record=previous_records.get(_folder_relative_path(path, folder)),
            )
            for path in extra_files
        ]
        status = "present"
        if any(row.get("storage_class") == "unclassified" for row in records):
            status = "unclassified_present"
        families.append({
            "artifact_family": "other_registered_artifacts",
            "required": False,
            "status": status,
            "description": "Files not matched by a first-class event-day family.",
            "files": records,
            "file_count": len(records),
            "bytes": sum(int(row.get("bytes") or 0) for row in records),
        })

    file_records = [record for family in families for record in family.get("files") or []]
    event_metadata_proof = _event_metadata_validation_proof(
        market_id=market_id,
        target_date=target_date,
        event_slug=event_slug,
        path=event_metadata_validation_path,
        payload=event_metadata_validation_payload,
    )
    release_runtime_identity = release_runtime_identity_summary(file_records)
    payload_blob_links = _payload_blob_link_validation(
        folder,
        shared_cas_root=snapshots_root.parent / "forecast_payload_cas",
    )
    shared_payload_dependencies = list(
        payload_blob_links.get("shared_dependencies") or []
    )
    protection_records = file_records + shared_payload_dependencies
    backup_verification = _backup_verification(protection_records, backup_root)
    restore_verification = _restore_proof_verification(
        protection_records,
        event_slug=event_slug,
        restore_proof_path=restore_proof_path,
        restore_proof_payload=restore_proof_payload,
    )
    protection_statuses = {
        backup_verification.get("status"),
        restore_verification.get("status"),
    }
    if "BLOCK" in protection_statuses:
        protection_status = "BLOCK"
    elif protection_statuses <= {"PASS", "NOT_APPLICABLE"}:
        protection_status = "PASS"
    else:
        protection_status = "NOT_READY"
    checks = [
        {"check": "manifest_hash", "status": "PENDING"},
        {
            "check": "unclassified_files",
            "status": "PASS" if not any(row.get("storage_class") == "unclassified" for row in file_records) else "BLOCK",
        },
        {
            "check": "file_validation",
            "status": "PASS" if not any(row.get("validation_status") == "BLOCK" for row in file_records) else "BLOCK",
            "blocked_files": sorted(
                str(row.get("path"))
                for row in file_records
                if row.get("validation_status") == "BLOCK"
            ),
        },
        {
            "check": "release_identity",
            "status": (
                "PASS"
                if release_runtime_identity.get("release_identity_status") == "SINGLE"
                else "BLOCK"
            ),
            "release_identity_status": release_runtime_identity.get("release_identity_status"),
            "release_identity_count": release_runtime_identity.get("release_identity_count"),
        },
        {
            "check": "runtime_identity",
            "status": (
                "PASS"
                if release_runtime_identity.get("runtime_identity_status") == "SINGLE"
                else "BLOCK"
            ),
            "runtime_identity_status": release_runtime_identity.get("runtime_identity_status"),
            "runtime_identity_count": release_runtime_identity.get("runtime_identity_count"),
        },
        {
            "check": "required_families",
            "status": "PASS" if not any(family.get("status") == "missing_required" for family in families) else "BLOCK",
        },
        {
            "check": "payload_blob_links",
            "status": payload_blob_links.get("status"),
            "issue_count": (payload_blob_links.get("summary") or {}).get(
                "issue_count"
            ),
        },
        {
            "check": "shared_payload_backup_restore",
            "status": (
                "PASS"
                if not shared_payload_dependencies
                or (
                    backup_verification.get("status") == "PASS"
                    and restore_verification.get("status") == "PASS"
                )
                else "BLOCK"
            ),
            "shared_dependency_count": len(shared_payload_dependencies),
            "backup_status": backup_verification.get("status"),
            "restore_status": restore_verification.get("status"),
        },
        {
            "check": "event_metadata_validation",
            "status": (
                "PASS"
                if event_metadata_proof.get("status") in {"PASS", "MISSING", "NOT_APPLICABLE"}
                else "BLOCK"
            ),
            "validation_hash": event_metadata_proof.get("validation_hash"),
            "reason": event_metadata_proof.get("reason"),
        },
        {
            "check": "off_machine_backup",
            "status": (
                "BLOCK" if backup_verification.get("status") == "BLOCK"
                else "PASS" if backup_verification.get("status") in {"PASS", "NOT_APPLICABLE"}
                else "WARN"
            ),
            "detail": backup_verification.get("status"),
        },
        {
            "check": "restore_proof",
            "status": (
                "BLOCK" if restore_verification.get("status") == "BLOCK"
                else "PASS" if restore_verification.get("status") in {"PASS", "NOT_APPLICABLE"}
                else "WARN"
            ),
            "detail": restore_verification.get("status"),
        },
    ]
    if any(check["status"] == "BLOCK" for check in checks):
        validation_status = "BLOCK"
    elif any(check["status"] == "WARN" for check in checks):
        validation_status = "WARN"
    else:
        validation_status = "PASS"
    class_bytes = {
        storage_class: sum(
            int(row.get("bytes") or 0)
            for row in file_records
            if row.get("storage_class") == storage_class
        )
        for storage_class in ("canonical_evidence", "analysis_projection", "operator_cache", "unclassified")
    }
    shared_dependency_bytes = sum(
        int(row.get("bytes") or 0) for row in shared_payload_dependencies
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "writer": "weather.operations.event_day_manifest",
        "writer_version": WRITER_VERSION,
        "inventory_hash": "",
        "manifest_hash": "",
        "folder": str(folder),
        "identity": {
            "event_slug": event_slug,
            "market_id": market_id,
            "local_date": target_date.isoformat() if target_date else None,
            "target_date": target_date.isoformat() if target_date else None,
        },
        "summary": {
            "artifact_family_count": len(families),
            "file_count": len(file_records),
            "total_bytes": sum(int(row.get("bytes") or 0) for row in file_records),
            "canonical_evidence_files": sum(1 for row in file_records if row.get("storage_class") == "canonical_evidence"),
            "analysis_projection_files": sum(1 for row in file_records if row.get("storage_class") == "analysis_projection"),
            "operator_cache_files": sum(1 for row in file_records if row.get("storage_class") == "operator_cache"),
            "unclassified_files": sum(1 for row in file_records if row.get("storage_class") == "unclassified"),
            "canonical_evidence_bytes": class_bytes["canonical_evidence"],
            "analysis_projection_bytes": class_bytes["analysis_projection"],
            "operator_cache_bytes": class_bytes["operator_cache"],
            "unclassified_bytes": class_bytes["unclassified"],
            "external_canonical_dependency_files": len(
                shared_payload_dependencies
            ),
            "external_canonical_dependency_bytes": shared_dependency_bytes,
            "bytes_requiring_off_machine_backup": (
                class_bytes["canonical_evidence"] + shared_dependency_bytes
            ),
            "backup_status": backup_verification.get("status"),
            "restore_status": restore_verification.get("status"),
            "event_metadata_validation_hash": event_metadata_proof.get("validation_hash"),
            "payload_blob_link_status": payload_blob_links.get("status"),
            "payload_blob_link_issue_count": (
                payload_blob_links.get("summary") or {}
            ).get("issue_count"),
        },
        "event_metadata_validation": event_metadata_proof,
        "release_runtime_identity": release_runtime_identity,
        "payload_blob_links": payload_blob_links,
        "shared_payload_dependencies": shared_payload_dependencies,
        "protection": {
            "status": protection_status,
            "backup": backup_verification,
            "restore": restore_verification,
        },
        "validation": {
            "status": validation_status,
            "checks": checks,
        },
        "artifact_families": families,
    }
    manifest["inventory_hash"] = inventory_content_hash(manifest)
    manifest["manifest_hash"] = manifest_content_hash(manifest)
    manifest["validation"]["checks"][0]["status"] = "PASS"
    manifest["manifest_hash"] = manifest_content_hash(manifest)
    return manifest


def write_event_day_manifest(
    folder: str | Path,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    event_metadata_validation_payload: dict[str, Any] | None = None,
    event_metadata_validation_path: str | Path | None = DEFAULT_EVENT_METADATA_VALIDATION,
    backup_root: str | Path | None = None,
    restore_proof_path: str | Path | None = None,
    restore_proof_payload: dict[str, Any] | None = None,
    incremental: bool = False,
    generated_at_utc: str | None = None,
) -> Path:
    path = event_day_manifest_path(folder)
    existing = read_event_day_manifest(path) if incremental else None
    manifest = build_event_day_manifest(
        folder,
        snapshots_root=snapshots_root,
        event_metadata_validation_payload=event_metadata_validation_payload,
        event_metadata_validation_path=event_metadata_validation_path,
        backup_root=backup_root,
        restore_proof_path=restore_proof_path,
        restore_proof_payload=restore_proof_payload,
        previous_manifest=existing,
        reuse_unchanged=incremental,
        generated_at_utc=generated_at_utc,
    )
    if (
        existing
        and existing.get("writer_version") == WRITER_VERSION
        and existing.get("inventory_hash") == manifest.get("inventory_hash")
        and manifest_hash_valid(existing)
        and (
            (backup_root is None and restore_proof_path is None and restore_proof_payload is None)
            or existing.get("protection") == manifest.get("protection")
        )
    ):
        return path
    _atomic_write_json(path, manifest)
    return path


def _manifest_file_records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        record
        for family in manifest.get("artifact_families") or []
        for record in family.get("files") or []
    ]


def validate_event_day_manifest(
    manifest: dict[str, Any],
    folder: str | Path,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    check_hashes: bool = True,
    check_row_counts: bool = True,
    fail_on_extra: bool = True,
) -> dict[str, Any]:
    folder = Path(folder)
    snapshots_root = Path(snapshots_root)
    checks: list[dict[str, Any]] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        checks.append({"check": "schema_version", "status": "BLOCK", "detail": manifest.get("schema_version")})
    else:
        checks.append({"check": "schema_version", "status": "PASS"})
    if manifest_hash_valid(manifest):
        checks.append({"check": "manifest_hash", "status": "PASS"})
    else:
        checks.append({"check": "manifest_hash", "status": "BLOCK"})
    inventory_hash = manifest.get("inventory_hash")
    if inventory_hash:
        checks.append({
            "check": "inventory_hash",
            "status": "PASS" if inventory_hash == inventory_content_hash(manifest) else "BLOCK",
        })
    else:
        checks.append({"check": "inventory_hash", "status": "WARN", "detail": "legacy manifest"})

    declared_payload_links = manifest.get("payload_blob_links")
    current_payload_links = _payload_blob_link_validation(
        folder,
        shared_cas_root=snapshots_root.parent / "forecast_payload_cas",
    )
    current_shared_dependencies = list(
        current_payload_links.get("shared_dependencies") or []
    )
    if not isinstance(declared_payload_links, dict):
        checks.append({
            "check": "payload_blob_links_declared",
            "status": "BLOCK",
            "detail": "payload blob link evidence is missing",
        })
    elif declared_payload_links != current_payload_links:
        checks.append({
            "check": "payload_blob_links_current",
            "status": "BLOCK",
            "detail": "payload blob link evidence changed or does not recompute",
        })
    elif current_payload_links.get("status") != "PASS":
        checks.append({
            "check": "payload_blob_links_current",
            "status": "BLOCK",
            "detail": "payload manifest-to-blob links are not complete and valid",
            "issues": [
                issue
                for family in current_payload_links.get("families") or []
                for issue in family.get("issues") or []
            ],
        })
    else:
        checks.append({"check": "payload_blob_links_current", "status": "PASS"})
    checks.append({
        "check": "shared_payload_dependencies",
        "status": (
            "PASS"
            if list(manifest.get("shared_payload_dependencies") or [])
            == current_shared_dependencies
            else "BLOCK"
        ),
        "shared_dependency_count": len(current_shared_dependencies),
    })

    records = _manifest_file_records(manifest)
    manifest_paths = {row.get("path") for row in records if row.get("path")}
    for record in records:
        rel = record.get("path")
        path = folder / str(rel or "")
        if not rel or not path.exists():
            checks.append({"check": "file_exists", "status": "BLOCK", "path": rel})
            continue
        size = int(path.stat().st_size)
        if size != int(record.get("bytes") or 0):
            checks.append({"check": "file_size", "status": "BLOCK", "path": rel, "expected": record.get("bytes"), "actual": size})
        elif check_hashes and sha256_file(path) != record.get("sha256"):
            checks.append({"check": "file_hash", "status": "BLOCK", "path": rel})
        else:
            checks.append({"check": "file_current", "status": "PASS", "path": rel})
        current_row_count = _row_count(path) if check_row_counts else record.get("row_count")
        if check_row_counts and record.get("row_count") is not None and current_row_count != record.get("row_count"):
            checks.append({
                "check": "row_count",
                "status": "BLOCK",
                "path": rel,
                "expected": record.get("row_count"),
                "actual": current_row_count,
            })
        current_classification = classification_payload(_data_relative_path(path, snapshots_root))
        if current_classification["storage_class"] != record.get("storage_class"):
            checks.append({
                "check": "storage_class",
                "status": "BLOCK",
                "path": rel,
                "expected": record.get("storage_class"),
                "actual": current_classification["storage_class"],
            })
        if record.get("storage_class") == "unclassified":
            checks.append({"check": "unclassified_file", "status": "BLOCK", "path": rel})
        if record.get("validation_status") == "BLOCK":
            checks.append({
                "check": "file_validation",
                "status": "BLOCK",
                "path": rel,
                "detail": record.get("validation_detail"),
            })
        if record.get("storage_class") == "analysis_projection" and not record.get("rebuild_source"):
            checks.append({"check": "projection_rebuild_source", "status": "BLOCK", "path": rel})

    if fail_on_extra:
        current_paths = {
            path.relative_to(folder).as_posix()
            for path in folder.rglob("*")
            if path.is_file() and path.name != MANIFEST_FILENAME and not any(part.startswith(".") for part in path.relative_to(folder).parts)
        }
        extra = sorted(current_paths - manifest_paths)
        if extra:
            checks.append({"check": "extra_files", "status": "BLOCK", "paths": extra[:20], "count": len(extra)})
        else:
            checks.append({"check": "extra_files", "status": "PASS"})

    manifest_families = manifest.get("artifact_families") or []
    family_rows_by_name: dict[str, list[dict[str, Any]]] = {}
    for family_row in manifest_families:
        if isinstance(family_row, dict):
            family_rows_by_name.setdefault(str(family_row.get("artifact_family") or ""), []).append(family_row)
    required_family_failures: list[dict[str, Any]] = []
    for family_contract in EVENT_DAY_ARTIFACT_FAMILIES:
        if not family_contract.required:
            continue
        matches = family_rows_by_name.get(family_contract.name) or []
        if len(matches) != 1:
            required_family_failures.append({
                "artifact_family": family_contract.name,
                "reason": "missing_family" if not matches else "duplicate_family",
                "family_count": len(matches),
            })
            continue
        family_row = matches[0]
        family_records = [
            record for record in family_row.get("files") or [] if isinstance(record, dict)
        ]
        evidence = _required_family_evidence(family_contract, family_records)
        if (
            family_row.get("required") is not True
            or family_row.get("requires_canonical_evidence")
            is not family_contract.requires_canonical_evidence
            or family_row.get("required_member_patterns")
            != list(family_contract.required_member_patterns)
            or family_row.get("status") != "present"
            or evidence.get("status") != "PASS"
            or family_row.get("required_evidence") != evidence
        ):
            required_family_failures.append({
                "artifact_family": family_contract.name,
                "reason": "required_evidence_incomplete",
                "declared_status": family_row.get("status"),
                "evidence": evidence,
            })
    checks.append({
        "check": "required_families",
        "status": "BLOCK" if required_family_failures else "PASS",
        "required_families": list(REQUIRED_EVENT_DAY_ARTIFACT_FAMILY_NAMES),
        "failures": required_family_failures,
    })

    declared_identity = manifest.get("release_runtime_identity") or {}
    runtime_identity = release_runtime_identity_summary(records)
    identity_fields = (
        "release_identity_status",
        "release_identity_count",
        "release_identities",
        "partial_release_identity_count",
        "partial_release_identities",
        "runtime_identity_status",
        "runtime_identity_count",
        "runtime_identities",
        "proof_grade_status",
        "proof_grade_blockers",
    )
    identity_summary_current = all(
        declared_identity.get(field) == runtime_identity.get(field)
        for field in identity_fields
    )
    checks.append({
        "check": "release_runtime_identity_summary",
        "status": "PASS" if identity_summary_current else "BLOCK",
    })
    checks.append({
        "check": "release_identity",
        "status": "PASS" if runtime_identity.get("release_identity_status") == "SINGLE" else "BLOCK",
        "release_identity_status": runtime_identity.get("release_identity_status"),
        "release_identity_count": runtime_identity.get("release_identity_count"),
    })
    checks.append({
        "check": "runtime_identity",
        "status": "PASS" if runtime_identity.get("runtime_identity_status") == "SINGLE" else "BLOCK",
        "runtime_identity_status": runtime_identity.get("runtime_identity_status"),
        "runtime_identity_count": runtime_identity.get("runtime_identity_count"),
    })
    event_metadata_proof = manifest.get("event_metadata_validation") or {}
    event_metadata_status = str(event_metadata_proof.get("status") or "MISSING")
    event_metadata_required = bool(event_metadata_proof.get("required"))
    event_metadata_pass = event_metadata_status == "PASS" or (
        event_metadata_status in {"MISSING", "NOT_APPLICABLE"}
        and not event_metadata_required
    )
    checks.append({
        "check": "event_metadata_validation",
        "status": "PASS" if event_metadata_pass else "BLOCK",
        "detail": event_metadata_status,
        "required": event_metadata_required,
        "target_matches": event_metadata_proof.get("target_matches"),
        "event_matches": event_metadata_proof.get("event_matches"),
        "validation_hash": event_metadata_proof.get("validation_hash"),
    })
    embedded_validation = manifest.get("validation") or {}
    if embedded_validation:
        embedded_status = str(embedded_validation.get("status") or "MISSING")
        checks.append({
            "check": "embedded_manifest_validation",
            "status": "BLOCK" if embedded_status == "BLOCK" else "PASS",
            "detail": embedded_status,
        })
    protection = manifest.get("protection") or {}
    for check_name in ("backup", "restore"):
        proof = protection.get(check_name) or {}
        proof_status = proof.get("status")
        checks.append({
            "check": f"{check_name}_proof",
            "status": (
                "BLOCK"
                if proof_status == "BLOCK"
                or (current_shared_dependencies and proof_status != "PASS")
                else "PASS"
            ),
            "detail": proof_status or "legacy_not_recorded",
        })
    status = "BLOCK" if any(check.get("status") == "BLOCK" for check in checks) else "PASS"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "folder": str(folder),
        "manifest_hash": manifest.get("manifest_hash"),
        "checks": checks,
    }


def validate_deletion_candidates(
    manifest: dict[str, Any],
    candidate_paths: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Fail closed unless every deletion candidate is manifest-backed and safe."""

    records = {
        str(record.get("path")): record
        for record in _manifest_file_records(manifest)
        if record.get("path")
    }
    checks: list[dict[str, Any]] = []
    for candidate in candidate_paths:
        normalized = Path(candidate).as_posix()
        record = records.get(normalized)
        if record is None:
            checks.append({
                "check": "candidate_manifest_record",
                "status": "BLOCK",
                "path": normalized,
                "detail": "deletion candidate is not listed in event_day_manifest.json",
            })
            continue
        storage_class = record.get("storage_class")
        if storage_class == "analysis_projection" and not record.get("rebuild_source"):
            checks.append({
                "check": "projection_rebuild_source",
                "status": "BLOCK",
                "path": normalized,
                "detail": "projection candidate lacks a rebuild source",
            })
            continue
        checks.append({
            "check": "candidate_manifest_record",
            "status": "PASS",
            "path": normalized,
            "storage_class": storage_class,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCK" if any(check.get("status") == "BLOCK" for check in checks) else "PASS",
        "manifest_hash": manifest.get("manifest_hash"),
        "checks": checks,
    }


def read_event_day_manifest(path_or_folder: str | Path) -> dict[str, Any] | None:
    path = Path(path_or_folder)
    if path.is_dir():
        path = event_day_manifest_path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def summarize_event_day_manifests(
    snapshots_root: str | Path,
    *,
    check_hashes: bool = False,
) -> dict[str, Any]:
    root = Path(snapshots_root)
    rows = []
    if root.exists():
        for path in sorted(root.glob(f"*/{MANIFEST_FILENAME}")):
            manifest = read_event_day_manifest(path)
            folder = path.parent
            if manifest is None:
                rows.append({"path": str(path), "folder": str(folder), "status": "UNREADABLE"})
                continue
            validation = validate_event_day_manifest(
                manifest,
                folder,
                snapshots_root=root,
                check_hashes=check_hashes,
                fail_on_extra=False,
            )
            rows.append({
                "path": str(path),
                "folder": str(folder),
                "event_slug": (manifest.get("identity") or {}).get("event_slug"),
                "target_date": (manifest.get("identity") or {}).get("target_date"),
                "manifest_hash": manifest.get("manifest_hash"),
                "inventory_hash": manifest.get("inventory_hash"),
                "status": validation.get("status"),
                "file_count": (manifest.get("summary") or {}).get("file_count"),
                "total_bytes": (manifest.get("summary") or {}).get("total_bytes"),
                "canonical_evidence_files": (manifest.get("summary") or {}).get("canonical_evidence_files"),
                "canonical_evidence_bytes": (manifest.get("summary") or {}).get("canonical_evidence_bytes"),
                "analysis_projection_files": (manifest.get("summary") or {}).get("analysis_projection_files"),
                "unclassified_files": (manifest.get("summary") or {}).get("unclassified_files"),
                "backup_status": ((manifest.get("protection") or {}).get("backup") or {}).get("status"),
                "restore_status": ((manifest.get("protection") or {}).get("restore") or {}).get("status"),
                "runtime_identity_count": (manifest.get("release_runtime_identity") or {}).get("runtime_identity_count"),
            })
    target_dates = sorted({str(row.get("target_date")) for row in rows if row.get("target_date")})
    return {
        "snapshots_root": str(root),
        "manifest_count": len(rows),
        "pass_count": sum(1 for row in rows if row.get("status") == "PASS"),
        "block_count": sum(1 for row in rows if row.get("status") == "BLOCK"),
        "unreadable_count": sum(1 for row in rows if row.get("status") == "UNREADABLE"),
        "target_date_count": len(target_dates),
        "oldest_target_date": target_dates[0] if target_dates else None,
        "newest_target_date": target_dates[-1] if target_dates else None,
        "total_bytes": sum(int(row.get("total_bytes") or 0) for row in rows),
        "canonical_evidence_bytes": sum(int(row.get("canonical_evidence_bytes") or 0) for row in rows),
        "unclassified_file_count": sum(int(row.get("unclassified_files") or 0) for row in rows),
        "backup_pass_count": sum(1 for row in rows if row.get("backup_status") == "PASS"),
        "backup_block_count": sum(1 for row in rows if row.get("backup_status") == "BLOCK"),
        "backup_not_configured_count": sum(1 for row in rows if row.get("backup_status") == "NOT_CONFIGURED"),
        "restore_pass_count": sum(1 for row in rows if row.get("restore_status") == "PASS"),
        "restore_block_count": sum(1 for row in rows if row.get("restore_status") == "BLOCK"),
        "restore_not_configured_count": sum(1 for row in rows if row.get("restore_status") == "NOT_CONFIGURED"),
        "manifests": rows[:50],
    }


def iter_snapshot_folders(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    event_slugs: list[str] | tuple[str, ...] | None = None,
    target_dates: list[str] | tuple[str, ...] | None = None,
    limit: int | None = None,
) -> list[Path]:
    root = Path(snapshots_root)
    folders = [root / slug for slug in event_slugs] if event_slugs else sorted(path for path in root.iterdir() if path.is_dir()) if root.exists() else []
    folders = [folder for folder in folders if folder.exists() and folder.is_dir()]
    if target_dates:
        allowed_dates = {str(value) for value in target_dates}
        folders = [
            folder
            for folder in folders
            if date_from_event_slug(folder.name)
            and date_from_event_slug(folder.name).isoformat() in allowed_dates
        ]
    return folders[: int(limit)] if limit is not None else folders


def _restore_proof_path_for_folder(
    restore_proof_root: str | Path | None,
    folder: Path,
) -> Path | None:
    if not restore_proof_root:
        return None
    return Path(restore_proof_root) / f"{folder.name}.json"


def _existing_manifest_state(
    existing: dict[str, Any] | None,
    candidate: dict[str, Any],
    folder: Path,
    *,
    snapshots_root: Path,
    path_exists: bool,
    compare_protection: bool,
    full_audit: bool,
) -> tuple[str, dict[str, Any] | None]:
    if not path_exists:
        return "MISSING", None
    if existing is None:
        return "UNREADABLE", None
    existing_validation = validate_event_day_manifest(
        existing,
        folder,
        snapshots_root=snapshots_root,
        check_hashes=full_audit,
        check_row_counts=full_audit,
        fail_on_extra=True,
    )
    inventory_matches = (
        existing.get("writer_version") == WRITER_VERSION
        and existing.get("inventory_hash") == candidate.get("inventory_hash")
        and manifest_hash_valid(existing)
    )
    protection_matches = (
        not compare_protection
        or existing.get("protection") == candidate.get("protection")
    )
    if inventory_matches and protection_matches and existing_validation.get("status") == "PASS":
        return "CURRENT", existing_validation
    return "CHANGED", existing_validation


def _storage_gate_summary(
    rows: list[dict[str, Any]],
    *,
    usage_path: Path,
    daily_growth_bytes: int | None,
    min_growth_headroom_days: float,
) -> dict[str, Any]:
    usage = shutil.disk_usage(usage_path if usage_path.exists() else usage_path.parent)
    growth = int(daily_growth_bytes) if daily_growth_bytes is not None else None
    headroom_days = float(usage.free) / growth if growth and growth > 0 else None
    if headroom_days is None:
        headroom_status = "NOT_EVALUATED"
    elif headroom_days >= float(min_growth_headroom_days):
        headroom_status = "PASS"
    else:
        headroom_status = "BLOCK"
    backup_statuses = {str(row.get("backup_status") or "NOT_CONFIGURED") for row in rows}
    restore_statuses = {str(row.get("restore_status") or "NOT_CONFIGURED") for row in rows}
    if "BLOCK" in backup_statuses or "BLOCK" in restore_statuses or headroom_status == "BLOCK":
        status = "BLOCK"
    elif (
        headroom_status == "PASS"
        and backup_statuses <= {"PASS", "NOT_APPLICABLE"}
        and restore_statuses <= {"PASS", "NOT_APPLICABLE"}
    ):
        status = "PASS"
    else:
        status = "NOT_READY"
    return {
        "status": status,
        "required_growth_headroom_days": float(min_growth_headroom_days),
        "daily_growth_bytes": growth,
        "disk_total_bytes": int(usage.total),
        "disk_used_bytes": int(usage.used),
        "disk_free_bytes": int(usage.free),
        "growth_headroom_days": headroom_days,
        "growth_headroom_status": headroom_status,
        "event_day_bytes": sum(int(row.get("total_bytes") or 0) for row in rows),
        "canonical_evidence_bytes": sum(int(row.get("canonical_evidence_bytes") or 0) for row in rows),
        "bytes_requiring_off_machine_backup": sum(
            int(row.get("canonical_evidence_bytes") or 0)
            for row in rows
            if row.get("backup_status") not in {"PASS", "NOT_APPLICABLE"}
        ),
        "backup_pass_count": sum(1 for row in rows if row.get("backup_status") == "PASS"),
        "backup_block_count": sum(1 for row in rows if row.get("backup_status") == "BLOCK"),
        "backup_not_configured_count": sum(1 for row in rows if row.get("backup_status") == "NOT_CONFIGURED"),
        "restore_pass_count": sum(1 for row in rows if row.get("restore_status") == "PASS"),
        "restore_block_count": sum(1 for row in rows if row.get("restore_status") == "BLOCK"),
        "restore_not_configured_count": sum(1 for row in rows if row.get("restore_status") == "NOT_CONFIGURED"),
    }


def build_backfill_payload(
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    apply: bool = False,
    mode: str | None = None,
    incremental: bool = False,
    event_slugs: list[str] | tuple[str, ...] | None = None,
    target_dates: list[str] | tuple[str, ...] | None = None,
    backup_root: str | Path | None = None,
    restore_proof_root: str | Path | None = None,
    daily_growth_bytes: int | None = None,
    min_growth_headroom_days: float = DEFAULT_MIN_GROWTH_HEADROOM_DAYS,
    limit: int | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(snapshots_root)
    generated = generated_at_utc or utc_iso()
    effective_mode = mode or ("apply" if apply else "plan")
    if effective_mode not in {"audit", "plan", "apply"}:
        raise ValueError(f"unsupported event-day manifest mode: {effective_mode}")
    should_apply = effective_mode == "apply"
    rows = []
    folders = iter_snapshot_folders(
        root,
        event_slugs=event_slugs,
        target_dates=target_dates,
        limit=limit,
    )
    for folder in folders:
        proof_path = _restore_proof_path_for_folder(restore_proof_root, folder)
        path = event_day_manifest_path(folder)
        existing = read_event_day_manifest(path)
        manifest = build_event_day_manifest(
            folder,
            snapshots_root=root,
            backup_root=backup_root,
            restore_proof_path=proof_path,
            previous_manifest=existing,
            reuse_unchanged=incremental,
            generated_at_utc=generated,
        )
        validation = validate_event_day_manifest(
            manifest,
            folder,
            snapshots_root=root,
            check_hashes=False,
            check_row_counts=False,
        )
        state, existing_validation = _existing_manifest_state(
            existing,
            manifest,
            folder,
            snapshots_root=root,
            path_exists=path.exists(),
            compare_protection=backup_root is not None or restore_proof_root is not None,
            full_audit=not incremental,
        )
        audit_status = "PASS" if state == "CURRENT" and validation["status"] == "PASS" else "BLOCK"
        row_status = audit_status if effective_mode == "audit" else validation["status"]
        summary = manifest.get("summary") or {}
        row = {
            "event_slug": folder.name,
            "target_date": (manifest.get("identity") or {}).get("target_date"),
            "folder": str(folder),
            "path": str(path),
            "status": row_status,
            "candidate_validation_status": validation["status"],
            "existing_validation_status": (existing_validation or {}).get("status"),
            "manifest_state": state,
            "manifest_hash": manifest.get("manifest_hash"),
            "inventory_hash": manifest.get("inventory_hash"),
            "file_count": summary.get("file_count"),
            "total_bytes": summary.get("total_bytes"),
            "canonical_evidence_files": summary.get("canonical_evidence_files"),
            "canonical_evidence_bytes": summary.get("canonical_evidence_bytes"),
            "analysis_projection_files": summary.get("analysis_projection_files"),
            "unclassified_files": summary.get("unclassified_files"),
            "backup_status": summary.get("backup_status"),
            "restore_status": summary.get("restore_status"),
            "runtime_identity_count": (manifest.get("release_runtime_identity") or {}).get("runtime_identity_count"),
            "written": False,
            "action": "audit_only" if effective_mode == "audit" else "would_write",
        }
        write_needed = not incremental or state != "CURRENT"
        if should_apply and write_needed:
            _atomic_write_json(path, manifest)
            row["written"] = True
            row["action"] = "written"
        elif should_apply:
            row["action"] = "reused_current"
        elif effective_mode == "plan" and incremental and state == "CURRENT":
            row["action"] = "reuse_current"
        rows.append(row)
    storage_gate = _storage_gate_summary(
        rows,
        usage_path=root,
        daily_growth_bytes=daily_growth_bytes,
        min_growth_headroom_days=min_growth_headroom_days,
    )
    return {
        "schema_version": BACKFILL_SCHEMA_VERSION,
        "generated_at_utc": generated,
        "mode": effective_mode,
        "incremental": bool(incremental),
        "status": "BLOCK" if any(row.get("status") == "BLOCK" for row in rows) else "PASS",
        "snapshots_root": str(root),
        "backup_root": str(backup_root) if backup_root else None,
        "restore_proof_root": str(restore_proof_root) if restore_proof_root else None,
        "storage_gate": storage_gate,
        "summary": {
            "folder_count": len(rows),
            "pass_count": sum(1 for row in rows if row.get("status") == "PASS"),
            "block_count": sum(1 for row in rows if row.get("status") == "BLOCK"),
            "missing_manifest_count": sum(1 for row in rows if row.get("manifest_state") == "MISSING"),
            "changed_manifest_count": sum(1 for row in rows if row.get("manifest_state") == "CHANGED"),
            "unreadable_manifest_count": sum(1 for row in rows if row.get("manifest_state") == "UNREADABLE"),
            "current_manifest_count": sum(1 for row in rows if row.get("manifest_state") == "CURRENT"),
            "unclassified_file_count": sum(int(row.get("unclassified_files") or 0) for row in rows),
            "canonical_evidence_bytes": storage_gate["canonical_evidence_bytes"],
            "written_count": sum(1 for row in rows if row.get("written")),
            "reused_count": sum(1 for row in rows if row.get("action") in {"reused_current", "reuse_current"}),
        },
        "market_days": rows,
    }


def render_backfill_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    storage_gate = payload.get("storage_gate") or {}
    lines = [
        "# Event-Day Manifest Backfill",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Mode: `{payload.get('mode')}`",
        f"Status: `{payload.get('status')}`",
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [[key, value] for key, value in summary.items()],
        ),
        "",
        "## Production Storage Gate Inputs",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [[key, value] for key, value in storage_gate.items()],
        ),
        "",
        "## Market Days",
        "",
        *markdown_table(
            ["Event Slug", "Status", "State", "Files", "Canonical", "Backup", "Restore", "Action"],
            [
                [
                    row.get("event_slug"),
                    row.get("status"),
                    row.get("manifest_state"),
                    row.get("file_count"),
                    row.get("canonical_evidence_files"),
                    row.get("backup_status"),
                    row.get("restore_status"),
                    row.get("action"),
                ]
                for row in payload.get("market_days") or []
            ],
        ),
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_backfill_outputs(
    payload: dict[str, Any],
    *,
    json_path: str | Path = DEFAULT_BACKFILL_JSON,
    report_path: str | Path = DEFAULT_BACKFILL_REPORT,
) -> tuple[Path, Path]:
    json_path = Path(json_path)
    report_path = Path(report_path)
    _atomic_write_json(json_path, payload)
    _atomic_write_text(report_path, render_backfill_report(payload))
    return json_path, report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit, plan, or atomically write event-day evidence manifests."
    )
    parser.add_argument(
        "mode",
        choices=("audit", "plan", "apply"),
        help="audit performs no writes; plan writes only the aggregate report; apply writes manifests atomically.",
    )
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--event-slug", action="append", default=[])
    parser.add_argument("--target-date", action="append", default=[])
    parser.add_argument("--incremental", action="store_true", help="Reuse a current manifest instead of rewriting it.")
    parser.add_argument(
        "--backup-root",
        default=None,
        help="Optional off-machine data-root mirror; canonical files are verified by relative path and SHA-256.",
    )
    parser.add_argument(
        "--restore-proof-root",
        default=None,
        help="Optional folder containing <event-slug>.json restore proofs with per-file SHA-256 values.",
    )
    parser.add_argument("--daily-growth-bytes", type=int, default=None)
    parser.add_argument("--min-growth-headroom-days", type=float, default=DEFAULT_MIN_GROWTH_HEADROOM_DAYS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=str(DEFAULT_BACKFILL_JSON))
    parser.add_argument("--report", default=str(DEFAULT_BACKFILL_REPORT))
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = build_backfill_payload(
        snapshots_root=args.snapshots_root,
        mode=args.mode,
        incremental=args.incremental,
        event_slugs=args.event_slug or None,
        target_dates=args.target_date or None,
        backup_root=args.backup_root,
        restore_proof_root=args.restore_proof_root,
        daily_growth_bytes=args.daily_growth_bytes,
        min_growth_headroom_days=args.min_growth_headroom_days,
        limit=args.limit,
    )
    json_out = report_out = None
    if args.mode != "audit":
        json_out, report_out = write_backfill_outputs(payload, json_path=args.out, report_path=args.report)
    print(
        "Event-day manifest backfill: "
        f"{payload['status']} mode={payload['mode']} "
        f"folders={payload['summary']['folder_count']} "
        f"written={payload['summary']['written_count']}"
    )
    if json_out and report_out:
        print(f"JSON written to {json_out}")
        print(f"Report written to {report_out}")
    else:
        print("Audit-only mode: no files written")
    return payload


if __name__ == "__main__":
    main()
