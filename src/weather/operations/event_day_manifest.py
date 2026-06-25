"""Folder-level manifests for market-day snapshot evidence and projections."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from weather.market.market_config import date_from_event_slug, market_id_from_slug
from weather.operations import event_metadata_validation
from weather.operations.storage_classes import classification_payload, classify_storage_path
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("event_day_manifest")
BACKFILL_SCHEMA_VERSION = "event_day_manifest_backfill_v0.1"
WRITER_VERSION = "event_day_manifest_writer_v0.1"
MANIFEST_FILENAME = "event_day_manifest.json"
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_BACKFILL_JSON = data_path("backtest", "event_day_manifest_backfill.json")
DEFAULT_BACKFILL_REPORT = data_path("backtest", "event_day_manifest_backfill_report.md")
DEFAULT_EVENT_METADATA_VALIDATION = data_path("backtest", "event_metadata_validation.json")


@dataclass(frozen=True)
class EventDayArtifactFamily:
    name: str
    patterns: tuple[str, ...]
    required: bool = False
    description: str = ""


EVENT_DAY_ARTIFACT_FAMILIES = (
    EventDayArtifactFamily("snapshots", ("snapshots*.jsonl", "snapshots*.csv", "snapshots*.csv.gz")),
    EventDayArtifactFamily("features", ("features*.jsonl", "features*.csv", "features*.csv.gz")),
    EventDayArtifactFamily("components", ("components*.jsonl", "components*.csv", "components*.csv.gz")),
    EventDayArtifactFamily("forecasts", ("forecasts*.jsonl", "forecasts*.csv", "forecasts*.csv.gz")),
    EventDayArtifactFamily(
        "forecast_payloads",
        ("forecast_payloads*.jsonl", "forecast_payloads*.csv", "forecast_payloads/**/*.json"),
    ),
    EventDayArtifactFamily("source_status", ("source_status*.jsonl", "source_status*.csv", "source_status*.csv.gz")),
    EventDayArtifactFamily("replay_inputs", ("replay_inputs*.jsonl", "replay_input_status.json")),
    EventDayArtifactFamily("clob_tokens", ("clob_tokens.csv", "clob_tokens.jsonl")),
    EventDayArtifactFamily(
        "order_books",
        ("order_books.jsonl", "order_books_summary.csv", "order_books_long.csv", "order_books_long.csv.gz"),
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
    EventDayArtifactFamily("variant_predictions", ("variant_predictions*.jsonl", "variant_predictions*.csv", "variant_predictions*.csv.gz")),
    EventDayArtifactFamily("settlement", ("settlement.json", "settlement*.jsonl", "settlement*.csv")),
    EventDayArtifactFamily("market_making_runs", ("mm_runs/**/*", "market_making/**/*", "paper_trading/**/*")),
    EventDayArtifactFamily("taker_runs", ("taker_runs/**/*",)),
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _json_schema_version(path: Path) -> str | None:
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload.get("schema_version") if isinstance(payload, dict) else None
        if path.suffix.lower() == ".jsonl":
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    payload = json.loads(text)
                    return payload.get("schema_version") if isinstance(payload, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return None


def _row_count(path: Path) -> int | None:
    name = path.name.lower()
    suffix = path.suffix.lower()
    try:
        if suffix == ".jsonl":
            with path.open("r", encoding="utf-8") as handle:
                return sum(1 for line in handle if line.strip())
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return len(payload)
            return 1 if payload else 0
        if suffix == ".csv" or name.endswith(".csv.gz"):
            opener = gzip.open if name.endswith(".csv.gz") else open
            with opener(path, "rt", encoding="utf-8", newline="") as handle:
                rows = sum(1 for _ in csv.reader(handle))
            return max(0, rows - 1)
        if suffix == ".parquet":
            import pyarrow.parquet as pq

            return int(pq.ParquetFile(path).metadata.num_rows)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error):
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


def _backup_state(
    data_rel_path: str,
    classification: dict[str, Any],
    *,
    backup_manifest: dict[str, Any] | None = None,
    restore_drill: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_files = {
        row.get("path"): row
        for row in (backup_manifest or {}).get("files") or []
        if row.get("path")
    }
    backed_entry = manifest_files.get(f"data/{data_rel_path}") or manifest_files.get(data_rel_path)
    return {
        "expected": bool(classification.get("backup_required")),
        "backed_up": bool(backed_entry) if backup_manifest else None,
        "backup_manifest_hash": (backup_manifest or {}).get("manifest_hash"),
        "restore_drill_status": (restore_drill or {}).get("status") or "unknown",
    }


def _file_record(
    path: Path,
    *,
    folder: Path,
    snapshots_root: Path,
    backup_manifest: dict[str, Any] | None,
    restore_drill: dict[str, Any] | None,
) -> dict[str, Any]:
    stat = path.stat()
    data_rel = _data_relative_path(path, snapshots_root)
    classification = classification_payload(data_rel)
    return {
        "path": _folder_relative_path(path, folder),
        "data_path": data_rel,
        "role": classification["storage_class"],
        "storage_class": classification["storage_class"],
        "artifact_family": classification["artifact_family"],
        "schema_version": _json_schema_version(path),
        "row_count": _row_count(path),
        "bytes": int(stat.st_size),
        "sha256": sha256_file(path),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "retention_class": classification["retention_class"],
        "rebuild_source": classification["rebuild_source"],
        "backup_required": classification["backup_required"],
        "backup": _backup_state(
            data_rel,
            classification,
            backup_manifest=backup_manifest,
            restore_drill=restore_drill,
        ),
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
    status = "PASS" if gate.get("ok") and target_matches and event_matches else "BLOCK"
    return {
        "status": status,
        "required": True,
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
        "reason": "event metadata validation row passes" if status == "PASS" else gate.get("reason"),
    }


def build_event_day_manifest(
    folder: str | Path,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    backup_manifest: dict[str, Any] | None = None,
    restore_drill: dict[str, Any] | None = None,
    event_metadata_validation_payload: dict[str, Any] | None = None,
    event_metadata_validation_path: str | Path | None = DEFAULT_EVENT_METADATA_VALIDATION,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    folder = Path(folder)
    snapshots_root = Path(snapshots_root)
    event_slug = folder.name
    target_date = date_from_event_slug(event_slug)
    market_id = market_id_from_slug(event_slug)
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
                backup_manifest=backup_manifest,
                restore_drill=restore_drill,
            )
            for path in files
        ]
        families.append({
            "artifact_family": family.name,
            "required": family.required,
            "status": "present" if records else ("missing_required" if family.required else "missing_optional"),
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
                backup_manifest=backup_manifest,
                restore_drill=restore_drill,
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
    checks = [
        {"check": "manifest_hash", "status": "PENDING"},
        {
            "check": "unclassified_files",
            "status": "PASS" if not any(row.get("storage_class") == "unclassified" for row in file_records) else "BLOCK",
        },
        {
            "check": "required_families",
            "status": "PASS" if not any(family.get("status") == "missing_required" for family in families) else "BLOCK",
        },
        {
            "check": "event_metadata_validation",
            "status": (
                "PASS"
                if event_metadata_proof.get("status") in {"PASS", "MISSING"}
                else "BLOCK"
            ),
            "validation_hash": event_metadata_proof.get("validation_hash"),
            "reason": event_metadata_proof.get("reason"),
        },
    ]
    validation_status = "BLOCK" if any(check["status"] == "BLOCK" for check in checks) else "PASS"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "writer": "weather.operations.event_day_manifest",
        "writer_version": WRITER_VERSION,
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
            "event_metadata_validation_hash": event_metadata_proof.get("validation_hash"),
        },
        "event_metadata_validation": event_metadata_proof,
        "validation": {
            "status": validation_status,
            "checks": checks,
        },
        "artifact_families": families,
    }
    manifest["manifest_hash"] = manifest_content_hash(manifest)
    manifest["validation"]["checks"][0]["status"] = "PASS"
    manifest["manifest_hash"] = manifest_content_hash(manifest)
    return manifest


def write_event_day_manifest(
    folder: str | Path,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    backup_manifest: dict[str, Any] | None = None,
    restore_drill: dict[str, Any] | None = None,
    event_metadata_validation_payload: dict[str, Any] | None = None,
    event_metadata_validation_path: str | Path | None = DEFAULT_EVENT_METADATA_VALIDATION,
    generated_at_utc: str | None = None,
) -> Path:
    manifest = build_event_day_manifest(
        folder,
        snapshots_root=snapshots_root,
        backup_manifest=backup_manifest,
        restore_drill=restore_drill,
        event_metadata_validation_payload=event_metadata_validation_payload,
        event_metadata_validation_path=event_metadata_validation_path,
        generated_at_utc=generated_at_utc,
    )
    path = event_day_manifest_path(folder)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
        current_row_count = _row_count(path)
        if record.get("row_count") is not None and current_row_count != record.get("row_count"):
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

    missing_required = [
        family.get("artifact_family")
        for family in manifest.get("artifact_families") or []
        if family.get("status") == "missing_required"
    ]
    if missing_required:
        checks.append({"check": "required_families", "status": "BLOCK", "families": missing_required})
    else:
        checks.append({"check": "required_families", "status": "PASS"})
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
        backup = record.get("backup") or {}
        if storage_class == "canonical_evidence" and backup.get("backed_up") is not True:
            checks.append({
                "check": "canonical_backup_proof",
                "status": "BLOCK",
                "path": normalized,
                "detail": "canonical evidence candidate lacks backup manifest coverage",
            })
            continue
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
                "manifest_hash": manifest.get("manifest_hash"),
                "status": validation.get("status"),
                "file_count": (manifest.get("summary") or {}).get("file_count"),
                "canonical_evidence_files": (manifest.get("summary") or {}).get("canonical_evidence_files"),
                "analysis_projection_files": (manifest.get("summary") or {}).get("analysis_projection_files"),
            })
    return {
        "snapshots_root": str(root),
        "manifest_count": len(rows),
        "pass_count": sum(1 for row in rows if row.get("status") == "PASS"),
        "block_count": sum(1 for row in rows if row.get("status") == "BLOCK"),
        "unreadable_count": sum(1 for row in rows if row.get("status") == "UNREADABLE"),
        "manifests": rows[:50],
    }


def iter_snapshot_folders(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    event_slugs: list[str] | tuple[str, ...] | None = None,
    limit: int | None = None,
) -> list[Path]:
    root = Path(snapshots_root)
    folders = [root / slug for slug in event_slugs] if event_slugs else sorted(path for path in root.iterdir() if path.is_dir()) if root.exists() else []
    folders = [folder for folder in folders if folder.exists() and folder.is_dir()]
    return folders[: int(limit)] if limit is not None else folders


def build_backfill_payload(
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    apply: bool = False,
    event_slugs: list[str] | tuple[str, ...] | None = None,
    limit: int | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(snapshots_root)
    generated = generated_at_utc or utc_iso()
    rows = []
    for folder in iter_snapshot_folders(root, event_slugs=event_slugs, limit=limit):
        manifest = build_event_day_manifest(folder, snapshots_root=root, generated_at_utc=generated)
        validation = validate_event_day_manifest(manifest, folder, snapshots_root=root, check_hashes=True)
        row = {
            "event_slug": folder.name,
            "folder": str(folder),
            "status": validation["status"],
            "manifest_hash": manifest.get("manifest_hash"),
            "file_count": (manifest.get("summary") or {}).get("file_count"),
            "canonical_evidence_files": (manifest.get("summary") or {}).get("canonical_evidence_files"),
            "analysis_projection_files": (manifest.get("summary") or {}).get("analysis_projection_files"),
            "written": False,
        }
        if apply:
            event_day_manifest_path(folder).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            row["written"] = True
            row["path"] = str(event_day_manifest_path(folder))
        rows.append(row)
    return {
        "schema_version": BACKFILL_SCHEMA_VERSION,
        "generated_at_utc": generated,
        "mode": "apply" if apply else "plan",
        "status": "BLOCK" if any(row.get("status") == "BLOCK" for row in rows) else "PASS",
        "snapshots_root": str(root),
        "summary": {
            "folder_count": len(rows),
            "pass_count": sum(1 for row in rows if row.get("status") == "PASS"),
            "block_count": sum(1 for row in rows if row.get("status") == "BLOCK"),
            "written_count": sum(1 for row in rows if row.get("written")),
        },
        "market_days": rows,
    }


def render_backfill_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
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
        "## Market Days",
        "",
        *markdown_table(
            ["Event Slug", "Status", "Files", "Canonical", "Projection", "Written"],
            [
                [
                    row.get("event_slug"),
                    row.get("status"),
                    row.get("file_count"),
                    row.get("canonical_evidence_files"),
                    row.get("analysis_projection_files"),
                    row.get("written"),
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
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_backfill_report(payload), encoding="utf-8")
    return json_path, report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or backfill event-day snapshot folder manifests.")
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--event-slug", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=str(DEFAULT_BACKFILL_JSON))
    parser.add_argument("--report", default=str(DEFAULT_BACKFILL_REPORT))
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = build_backfill_payload(
        snapshots_root=args.snapshots_root,
        apply=args.mode == "apply",
        event_slugs=args.event_slug or None,
        limit=args.limit,
    )
    json_out, report_out = write_backfill_outputs(payload, json_path=args.out, report_path=args.report)
    print(
        "Event-day manifest backfill: "
        f"{payload['status']} mode={payload['mode']} "
        f"folders={payload['summary']['folder_count']} "
        f"written={payload['summary']['written_count']}"
    )
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return payload


if __name__ == "__main__":
    main()
