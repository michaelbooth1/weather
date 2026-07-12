"""Bounded, self-hashed coverage audit for event-day/archive manifest indexes.

The audit reads only snapshot directory names, manifest JSON files, and the
incremental cursor. It never opens source tapes or Parquet datasets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from weather.io import read_json, write_json_atomic
from weather.market.market_config import date_from_event_slug, market_id_from_slug
from weather.operations.closed_market_day_archive_manifest_contract import (
    manifest_hash_valid as archive_manifest_hash_valid,
    validate_manifest_shape as validate_archive_manifest_shape,
)
from weather.operations.event_day_manifest import (
    EVENT_DAY_ARTIFACT_FAMILIES,
    MANIFEST_FILENAME as EVENT_MANIFEST_FILENAME,
    REQUIRED_EVENT_DAY_ARTIFACT_FAMILY_NAMES,
    inventory_content_hash,
    manifest_hash_valid as event_manifest_hash_valid,
    release_runtime_identity_summary,
)
from weather.paths import data_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("event_day_archive_coverage_audit")
EVENT_MANIFEST_SCHEMA_VERSION = schema_version("event_day_manifest")
ARCHIVE_MANIFEST_SCHEMA_VERSION = schema_version("closed_market_day_archive_manifest")
CURSOR_SCHEMA_VERSION = schema_version("closed_market_day_parquet_incremental")
ARCHIVE_MANIFEST_FILENAME = "closed_market_day_archive_manifest.json"
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_ARCHIVE_ROOT = data_path("archive", "closed_market_days", "v0.1")
DEFAULT_CURSOR = data_path("backtest", "closed_market_day_parquet_incremental_cursor.json")
DEFAULT_OUT = data_path("backtest", "event_day_archive_coverage_audit.json")
DEFAULT_REPORT = data_path("backtest", "event_day_archive_coverage_audit.md")
DEFAULT_CURSOR_MAX_AGE_HOURS = 24.0
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
EVENT_FAMILY_STATUSES = frozenset({"present", "missing_optional", "missing_required"})


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(100.0 * numerator / denominator, 2) if denominator else None


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_hash_valid(payload: Mapping[str, Any]) -> bool:
    expected = str(payload.get("audit_sha256") or "")
    body = dict(payload)
    body.pop("audit_sha256", None)
    return bool(HASH_RE.fullmatch(expected)) and expected == _canonical_hash(body)


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _same_path(left: Any, right: Path) -> bool:
    try:
        return Path(str(left or "")).resolve() == right.resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _event_manifest_shape_errors(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    bounded_file_records: list[dict[str, Any]] = []
    if not payload.get("writer_version"):
        errors.append("writer_version_missing")
    families = payload.get("artifact_families")
    if not isinstance(families, list) or not families:
        errors.append("artifact_families_missing")
    else:
        by_name: dict[str, list[Mapping[str, Any]]] = {}
        for index, family in enumerate(families):
            if not isinstance(family, Mapping):
                errors.append(f"artifact_families[{index}]_invalid")
                continue
            if not str(family.get("artifact_family") or "").strip():
                errors.append(f"artifact_families[{index}].artifact_family_missing")
            else:
                by_name.setdefault(str(family.get("artifact_family")), []).append(family)
            if family.get("status") not in EVENT_FAMILY_STATUSES:
                errors.append(f"artifact_families[{index}].status_invalid")
            files = family.get("files")
            if not isinstance(files, list):
                errors.append(f"artifact_families[{index}].files_invalid")
                continue
            for file_index, row in enumerate(files):
                if not isinstance(row, Mapping):
                    errors.append(f"artifact_families[{index}].files[{file_index}]_invalid")
                    continue
                bounded_file_records.append(dict(row))
                for key in ("path", "bytes", "sha256", "role", "storage_class"):
                    if key not in row:
                        errors.append(
                            f"artifact_families[{index}].files[{file_index}].{key}_missing"
                        )
                if not HASH_RE.fullmatch(str(row.get("sha256") or "")):
                    errors.append(
                        f"artifact_families[{index}].files[{file_index}].sha256_invalid"
                    )
        required_contracts = {
            family.name: family
            for family in EVENT_DAY_ARTIFACT_FAMILIES
            if family.required
        }
        for required_name in REQUIRED_EVENT_DAY_ARTIFACT_FAMILY_NAMES:
            family_contract = required_contracts[required_name]
            matches = by_name.get(required_name) or []
            if len(matches) != 1:
                errors.append(
                    f"required_family.{required_name}."
                    + ("missing" if not matches else "duplicate")
                )
                continue
            family = matches[0]
            qualifying = [
                row
                for row in family.get("files") or []
                if isinstance(row, Mapping)
                and row.get("storage_class") == "canonical_evidence"
                and row.get("validation_status") == "PASS"
                and (
                    not family_contract.required_member_patterns
                    or any(
                        Path(str(row.get("path") or "")).match(pattern)
                        for pattern in family_contract.required_member_patterns
                    )
                )
                and (
                    row.get("row_count") is None
                    or (
                        isinstance(row.get("row_count"), int)
                        and int(row.get("row_count")) > 0
                    )
                )
            ]
            if (
                family.get("required") is not True
                or family.get("requires_canonical_evidence") is not True
                or family.get("required_member_patterns")
                != list(family_contract.required_member_patterns)
                or family.get("status") != "present"
                or not qualifying
            ):
                errors.append(f"required_family.{required_name}.evidence_incomplete")
            declared_evidence = family.get("required_evidence")
            if (
                not isinstance(declared_evidence, Mapping)
                or declared_evidence.get("status") != "PASS"
                or declared_evidence.get("required_member_patterns")
                != list(family_contract.required_member_patterns)
                or not isinstance(
                    declared_evidence.get("qualifying_required_member_count"), int
                )
                or int(declared_evidence.get("qualifying_required_member_count") or 0) <= 0
            ):
                errors.append(f"required_family.{required_name}.evidence_summary_invalid")
    validation = payload.get("validation")
    if not isinstance(validation, Mapping) or validation.get("status") not in {
        "PASS",
        "WARN",
    }:
        errors.append("embedded_validation_not_pass_or_warn")
    payload_blob_links = payload.get("payload_blob_links")
    if not isinstance(payload_blob_links, Mapping):
        errors.append("payload_blob_links_missing")
    else:
        link_families = payload_blob_links.get("families")
        family_names = {
            str(row.get("artifact_family") or "")
            for row in link_families or []
            if isinstance(row, Mapping)
        }
        if (
            payload_blob_links.get("status") != "PASS"
            or not isinstance(link_families, list)
            or family_names != {"forecast_payloads", "observation_payloads"}
            or any(
                not isinstance(row, Mapping)
                or row.get("status") != "PASS"
                or row.get("issue_count") != 0
                for row in link_families or []
            )
        ):
            errors.append("payload_blob_links_not_pass")
    protection = payload.get("protection")
    if not isinstance(protection, Mapping):
        errors.append("protection_missing")
    else:
        for role in ("backup", "restore"):
            if not isinstance(protection.get(role), Mapping) or not (
                protection.get(role) or {}
            ).get("status"):
                errors.append(f"protection.{role}_invalid")
    release_runtime_identity = payload.get("release_runtime_identity")
    if not isinstance(release_runtime_identity, Mapping):
        errors.append("release_runtime_identity_missing")
    else:
        if (
            release_runtime_identity.get("release_identity_status") != "SINGLE"
            or release_runtime_identity.get("release_identity_count") != 1
        ):
            errors.append("release_identity_not_singular")
        if (
            release_runtime_identity.get("runtime_identity_status") != "SINGLE"
            or release_runtime_identity.get("runtime_identity_count") != 1
            or release_runtime_identity.get("mixed_runtime_identity") is not False
        ):
            errors.append("runtime_identity_not_singular")
        if release_runtime_identity.get("proof_grade_status") != "PASS":
            errors.append("release_runtime_identity_not_proof_grade")
        computed_identity = release_runtime_identity_summary(bounded_file_records)
        identity_fields = (
            "release_identity_status",
            "release_identity_count",
            "runtime_identity_status",
            "runtime_identity_count",
            "proof_grade_status",
        )
        if any(
            release_runtime_identity.get(field) != computed_identity.get(field)
            for field in identity_fields
        ):
            errors.append("release_runtime_identity_summary_mismatch")
    inventory_hash = str(payload.get("inventory_hash") or "")
    if not HASH_RE.fullmatch(inventory_hash):
        errors.append("inventory_hash_missing_or_invalid")
    elif inventory_hash != inventory_content_hash(dict(payload)):
        errors.append("inventory_hash_mismatch")
    return errors


def _event_manifest_record(folder: Path) -> dict[str, Any]:
    path = folder / EVENT_MANIFEST_FILENAME
    base = {
        "event_slug": folder.name,
        "path": str(path),
        "file_sha256": _sha256_file(path),
        "manifest_hash": None,
        "state": "MISSING",
        "shape_errors": [],
        "payload": None,
    }
    if not path.exists():
        return base
    payload = read_json(path)
    if not isinstance(payload, dict):
        return {**base, "state": "UNREADABLE"}
    target_date = date_from_event_slug(folder.name)
    market_id = market_id_from_slug(folder.name)
    identity = payload.get("identity")
    shape_errors = _event_manifest_shape_errors(payload)
    if payload.get("schema_version") != EVENT_MANIFEST_SCHEMA_VERSION:
        state = "SCHEMA_MISMATCH"
    elif not isinstance(identity, Mapping) or any(
        (
            identity.get("event_slug") != folder.name,
            identity.get("target_date") != (target_date.isoformat() if target_date else None),
            identity.get("local_date") != (target_date.isoformat() if target_date else None),
            identity.get("market_id") != market_id,
        )
    ):
        state = "IDENTITY_MISMATCH"
    elif shape_errors:
        state = "SHAPE_INVALID"
    elif not event_manifest_hash_valid(payload):
        state = "HASH_INVALID"
    else:
        state = "STRUCTURALLY_VALID"
    return {
        **base,
        "manifest_hash": payload.get("manifest_hash"),
        "state": state,
        "shape_errors": shape_errors,
        "payload": payload,
    }


def _archive_record(path: Path) -> dict[str, Any]:
    path_event = path.parent.name.removeprefix("event_slug=")
    path_market = path.parent.parent.name.removeprefix("market_id=")
    path_date = path.parent.parent.parent.name.removeprefix("local_date=")
    base = {
        "path_event_slug": path_event,
        "event_slug": path_event,
        "path_market_id": path_market,
        "path_local_date": path_date,
        "path": str(path),
        "file_sha256": _sha256_file(path),
        "state": "UNREADABLE",
        "shape_errors": [],
        "payload": None,
    }
    payload = read_json(path)
    if not isinstance(payload, dict):
        return base
    partition = payload.get("partition")
    event_slug = (
        str(partition.get("event_slug") or path_event)
        if isinstance(partition, Mapping)
        else path_event
    )
    shape_errors = validate_archive_manifest_shape(payload)
    if payload.get("schema_version") != ARCHIVE_MANIFEST_SCHEMA_VERSION:
        state = "SCHEMA_MISMATCH"
    elif shape_errors:
        state = "SHAPE_INVALID"
    elif (
        not isinstance(partition, Mapping)
        or partition.get("event_slug") != path_event
        or partition.get("market_id") != path_market
        or partition.get("local_date") != path_date
        or Path(str(payload.get("source_folder") or "")).name != path_event
    ):
        state = "PARTITION_IDENTITY_MISMATCH"
    elif not archive_manifest_hash_valid(payload):
        state = "HASH_INVALID"
    else:
        state = "STRUCTURALLY_VALID"
    return {
        **base,
        "event_slug": event_slug,
        "state": state,
        "shape_errors": shape_errors,
        "declared_validation_status": (payload.get("validation") or {}).get("status"),
        "manifest_hash": payload.get("manifest_hash"),
        "event_manifest_hash": (payload.get("event_day_manifest") or {}).get(
            "manifest_hash"
        ),
        "payload": payload,
    }


def _cursor_contract(
    *,
    cursor_path: Path,
    snapshots_root: Path,
    archive_root: Path,
    as_of: date,
    generated: datetime,
    snapshot_folder_count: int,
    closed_slugs: set[str],
    max_age_hours: float,
) -> tuple[str, dict[str, Any], list[str], dict[str, Any]]:
    payload = read_json(cursor_path)
    file_hash = _sha256_file(cursor_path)
    errors: list[str] = []
    if not cursor_path.exists():
        state = "MISSING"
        payload = {}
        errors.append("cursor_missing")
    elif not isinstance(payload, dict):
        state = "UNREADABLE"
        payload = {}
        errors.append("cursor_unreadable")
    else:
        state = "INVALID"
        if payload.get("schema_version") != CURSOR_SCHEMA_VERSION:
            errors.append("cursor_schema_mismatch")
        if not _same_path(payload.get("snapshots_root"), snapshots_root):
            errors.append("cursor_snapshots_root_mismatch")
        if not _same_path(payload.get("archive_root"), archive_root):
            errors.append("cursor_archive_root_mismatch")
        if payload.get("as_of_date") != as_of.isoformat():
            errors.append("cursor_as_of_date_mismatch")
        updated = _parse_utc(payload.get("updated_at_utc"))
        if updated is None:
            errors.append("cursor_updated_at_invalid")
        elif updated > generated + timedelta(minutes=5):
            errors.append("cursor_updated_at_in_future")
        elif generated - updated > timedelta(hours=max_age_hours):
            errors.append("cursor_stale")
        scan = payload.get("scan")
        if not isinstance(scan, Mapping):
            errors.append("cursor_scan_missing")
        else:
            try:
                total_folders = int(scan.get("total_folders"))
                remaining_folders = int(scan.get("remaining_folders"))
                next_index = int(scan.get("next_index"))
            except (TypeError, ValueError):
                total_folders = remaining_folders = next_index = -1
                errors.append("cursor_scan_values_invalid")
            if total_folders != snapshot_folder_count:
                errors.append("cursor_total_folder_count_mismatch")
            if remaining_folders != 0:
                errors.append("cursor_scan_incomplete")
            if next_index != 0:
                errors.append("cursor_scan_not_at_complete_boundary")
        folders = payload.get("folders")
        if not isinstance(folders, Mapping):
            errors.append("cursor_folders_invalid")
            entries: dict[str, Any] = {}
        else:
            entries = {str(key): value for key, value in folders.items()}
            if closed_slugs - set(entries):
                errors.append("cursor_closed_folder_coverage_incomplete")
        if not errors:
            state = "VALID"
    entries = (
        {str(key): value for key, value in (payload.get("folders") or {}).items()}
        if isinstance(payload.get("folders"), Mapping)
        else {}
    )
    evidence = {
        "path": str(cursor_path),
        "sha256": file_hash,
        "bytes": cursor_path.stat().st_size if cursor_path.exists() else None,
        "updated_at_utc": payload.get("updated_at_utc"),
        "max_age_hours": max_age_hours,
        "state": state,
        "errors": sorted(errors),
    }
    return state, entries, sorted(errors), evidence


def build_payload(
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    cursor_path: str | Path = DEFAULT_CURSOR,
    as_of_date: str | date | None = None,
    generated_at_utc: str | None = None,
    cursor_max_age_hours: float = DEFAULT_CURSOR_MAX_AGE_HOURS,
) -> dict[str, Any]:
    snapshots_root = Path(snapshots_root)
    archive_root = Path(archive_root)
    cursor_path = Path(cursor_path)
    as_of = date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else as_of_date
    as_of = as_of or datetime.now().astimezone().date()
    generated_text = generated_at_utc or datetime.now(timezone.utc).isoformat()
    generated = _parse_utc(generated_text)
    if generated is None:
        raise ValueError("generated_at_utc must be a timezone-aware ISO-8601 timestamp")
    if cursor_max_age_hours <= 0:
        raise ValueError("cursor_max_age_hours must be positive")

    folders = (
        sorted((path for path in snapshots_root.iterdir() if path.is_dir()), key=lambda path: path.name)
        if snapshots_root.exists()
        else []
    )
    snapshot_slugs = {folder.name for folder in folders}
    closed_slugs = {
        folder.name
        for folder in folders
        if (date_from_event_slug(folder.name) and date_from_event_slug(folder.name) < as_of)
    }
    event_records = {folder.name: _event_manifest_record(folder) for folder in folders}
    archive_records = (
        [
            _archive_record(path)
            for path in sorted(
                archive_root.glob(
                    f"local_date=*/market_id=*/event_slug=*/{ARCHIVE_MANIFEST_FILENAME}"
                )
            )
        ]
        if archive_root.exists()
        else []
    )
    archives_by_path_slug: dict[str, list[dict[str, Any]]] = {}
    for record in archive_records:
        archives_by_path_slug.setdefault(str(record["path_event_slug"]), []).append(record)

    cursor_state, cursor_entries, cursor_errors, cursor_evidence = _cursor_contract(
        cursor_path=cursor_path,
        snapshots_root=snapshots_root,
        archive_root=archive_root,
        as_of=as_of,
        generated=generated,
        snapshot_folder_count=len(folders),
        closed_slugs=closed_slugs,
        max_age_hours=float(cursor_max_age_hours),
    )

    rows: list[dict[str, Any]] = []
    for folder in folders:
        target_date = date_from_event_slug(folder.name)
        market_id = market_id_from_slug(folder.name)
        closed_eligible = bool(target_date and target_date < as_of)
        event = event_records[folder.name]
        event_manifest = event.get("payload") or {}
        protection = event_manifest.get("protection") or {}
        backup_status = (protection.get("backup") or {}).get("status")
        restore_status = (protection.get("restore") or {}).get("status")

        matches = archives_by_path_slug.get(folder.name) or []
        archive = matches[0] if len(matches) == 1 else None
        archive_state = (
            "MISSING" if not matches else "DUPLICATE" if len(matches) > 1 else archive["state"]
        )
        archive_declared_ready = bool(
            archive
            and archive_state == "STRUCTURALLY_VALID"
            and archive.get("declared_validation_status") == "PASS"
        )
        event_hash = event.get("manifest_hash")
        linked_hash = archive.get("event_manifest_hash") if archive else None
        if not archive_declared_ready or event.get("state") != "STRUCTURALLY_VALID":
            event_link_state = "NOT_VERIFIABLE"
        elif not linked_hash:
            event_link_state = "MISSING"
        elif linked_hash == event_hash:
            event_link_state = "MATCH"
        else:
            event_link_state = "MISMATCH"

        cursor_entry = cursor_entries.get(folder.name)
        cursor_entry = cursor_entry if isinstance(cursor_entry, Mapping) else {}
        cursor_hash = cursor_entry.get("manifest_hash")
        archive_hash = archive.get("manifest_hash") if archive else None
        if not cursor_entry:
            cursor_link_state = "MISSING_ENTRY"
        elif not archive_declared_ready:
            cursor_link_state = "NOT_VERIFIABLE"
        elif not cursor_hash:
            cursor_link_state = "MISSING_HASH"
        elif cursor_hash == archive_hash:
            cursor_link_state = "MATCH"
        else:
            cursor_link_state = "MISMATCH"
        fully_linked = bool(
            closed_eligible
            and archive_declared_ready
            and event_link_state == "MATCH"
            and cursor_link_state == "MATCH"
        )
        rows.append(
            {
                "event_slug": folder.name,
                "market_id": market_id,
                "target_date": target_date.isoformat() if target_date else None,
                "closed_eligible": closed_eligible,
                "event_manifest_state": event.get("state"),
                "event_manifest_shape_errors": event.get("shape_errors") or [],
                "event_manifest_hash": event_hash,
                "event_manifest_file_sha256": event.get("file_sha256"),
                "backup_status": backup_status,
                "restore_status": restore_status,
                "archive_manifest_state": archive_state,
                "archive_manifest_shape_errors": archive.get("shape_errors") if archive else [],
                "archive_declared_validation_status": (
                    archive.get("declared_validation_status") if archive else None
                ),
                "archive_manifest_hash": archive_hash,
                "archive_manifest_file_sha256": archive.get("file_sha256") if archive else None,
                "archive_manifest_declared_ready": archive_declared_ready,
                "archive_event_manifest_link_state": event_link_state,
                "archive_manifest_paths": [record["path"] for record in matches],
                "cursor_entry_status": cursor_entry.get("status") if cursor_entry else "MISSING",
                "cursor_action": cursor_entry.get("action") if cursor_entry else None,
                "cursor_manifest_hash": cursor_hash,
                "cursor_archive_manifest_link_state": cursor_link_state,
                "fully_linked_archive_evidence": fully_linked,
                "protected_fully_linked_archive_evidence": bool(
                    fully_linked and backup_status == "PASS" and restore_status == "PASS"
                ),
            }
        )

    closed_rows = [row for row in rows if row["closed_eligible"]]
    structural_event_rows = [
        row for row in closed_rows if row["event_manifest_state"] == "STRUCTURALLY_VALID"
    ]
    declared_archive_rows = [
        row for row in closed_rows if row["archive_manifest_declared_ready"]
    ]
    fully_linked_rows = [row for row in closed_rows if row["fully_linked_archive_evidence"]]
    protected_linked_rows = [
        row for row in closed_rows if row["protected_fully_linked_archive_evidence"]
    ]
    cursor_status_counts = Counter(
        str((entry if isinstance(entry, Mapping) else {}).get("status") or "UNKNOWN")
        for entry in cursor_entries.values()
    )
    gaps = {
        "event_manifest_missing": sorted(
            row["event_slug"] for row in closed_rows if row["event_manifest_state"] == "MISSING"
        ),
        "event_manifest_invalid": sorted(
            row["event_slug"]
            for row in closed_rows
            if row["event_manifest_state"] not in {"MISSING", "STRUCTURALLY_VALID"}
        ),
        "closed_without_declared_archive_manifest": sorted(
            row["event_slug"] for row in closed_rows if not row["archive_manifest_declared_ready"]
        ),
        "archive_manifest_invalid": sorted(
            row["event_slug"]
            for row in closed_rows
            if row["archive_manifest_state"] not in {"MISSING", "STRUCTURALLY_VALID"}
        ),
        "archive_event_link_missing_or_mismatch": sorted(
            row["event_slug"]
            for row in declared_archive_rows
            if row["archive_event_manifest_link_state"] != "MATCH"
        ),
        "cursor_archive_hash_missing_or_mismatch": sorted(
            row["event_slug"]
            for row in declared_archive_rows
            if row["cursor_archive_manifest_link_state"] != "MATCH"
        ),
        "backup_not_pass": sorted(
            row["event_slug"] for row in structural_event_rows if row["backup_status"] != "PASS"
        ),
        "restore_not_pass": sorted(
            row["event_slug"] for row in structural_event_rows if row["restore_status"] != "PASS"
        ),
        "closed_missing_cursor_entry": sorted(
            row["event_slug"] for row in closed_rows if row["cursor_entry_status"] == "MISSING"
        ),
        "cursor_blocked_or_failed": sorted(
            slug
            for slug, entry in cursor_entries.items()
            if isinstance(entry, Mapping) and entry.get("status") in {"blocked", "failed"}
        ),
        "archive_without_snapshot_folder": sorted(
            slug for slug in archives_by_path_slug if slug not in snapshot_slugs
        ),
        "cursor_without_snapshot_folder": sorted(
            slug for slug in cursor_entries if slug not in snapshot_slugs
        ),
        "duplicate_archive_manifest": sorted(
            slug for slug, records in archives_by_path_slug.items() if len(records) > 1
        ),
    }
    blockers = sorted(name for name, values in gaps.items() if values)
    if cursor_errors:
        blockers.append("cursor_contract_invalid")
    blockers = sorted(set(blockers))

    snapshot_index = [
        {
            "event_slug": row["event_slug"],
            "market_id": row["market_id"],
            "target_date": row["target_date"],
            "closed_eligible": row["closed_eligible"],
        }
        for row in rows
    ]
    event_index = [
        {
            "event_slug": slug,
            "path": record["path"],
            "state": record["state"],
            "file_sha256": record["file_sha256"],
            "manifest_hash": record["manifest_hash"],
        }
        for slug, record in sorted(event_records.items())
    ]
    archive_index = [
        {
            "path": record["path"],
            "path_event_slug": record["path_event_slug"],
            "path_market_id": record["path_market_id"],
            "path_local_date": record["path_local_date"],
            "state": record["state"],
            "file_sha256": record["file_sha256"],
            "manifest_hash": record.get("manifest_hash"),
        }
        for record in archive_records
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_text,
        "status": "BLOCK" if blockers else "PASS",
        "as_of_date": as_of.isoformat(),
        "snapshots_root": str(snapshots_root),
        "archive_root": str(archive_root),
        "cursor_path": str(cursor_path),
        "scope": {
            "mode": "bounded_manifest_index_only",
            "snapshot_enumeration": "one_level_directories",
            "archive_enumeration": "fixed_depth_manifest_paths",
            "source_tape_walked": False,
            "source_file_hashes_checked": False,
            "parquet_files_opened": False,
            "manifest_shapes_checked": True,
            "manifest_self_hashes_checked": True,
            "manifest_json_files_hashed": True,
            "declared_archive_validation_rechecked": False,
            "coverage_claim": "index_structure_and_hash_linkage_only",
        },
        "input_evidence": {
            "snapshot_folder_index": {
                "count": len(snapshot_index),
                "sha256": _canonical_hash(snapshot_index),
            },
            "event_manifest_index": {
                "file_count": sum(1 for row in event_index if row["file_sha256"]),
                "sha256": _canonical_hash(event_index),
            },
            "archive_manifest_index": {
                "file_count": len(archive_index),
                "sha256": _canonical_hash(archive_index),
            },
            "cursor": cursor_evidence,
        },
        "summary": {
            "snapshot_folder_count": len(rows),
            "parseable_event_folder_count": sum(
                1 for row in rows if row["target_date"] and row["market_id"]
            ),
            "closed_eligible_folder_count": len(closed_rows),
            "closed_event_manifest_structurally_valid_count": len(structural_event_rows),
            "closed_event_manifest_structural_coverage_percent": _percentage(
                len(structural_event_rows), len(closed_rows)
            ),
            "archive_manifest_file_count": len(archive_records),
            "closed_declared_archive_manifest_count": len(declared_archive_rows),
            "closed_declared_archive_manifest_coverage_percent": _percentage(
                len(declared_archive_rows), len(closed_rows)
            ),
            "closed_archive_event_link_match_count": sum(
                1
                for row in declared_archive_rows
                if row["archive_event_manifest_link_state"] == "MATCH"
            ),
            "closed_cursor_archive_hash_match_count": sum(
                1
                for row in declared_archive_rows
                if row["cursor_archive_manifest_link_state"] == "MATCH"
            ),
            "closed_fully_linked_archive_evidence_count": len(fully_linked_rows),
            "closed_fully_linked_archive_evidence_coverage_percent": _percentage(
                len(fully_linked_rows), len(closed_rows)
            ),
            "closed_protected_fully_linked_archive_evidence_count": len(
                protected_linked_rows
            ),
            "closed_protected_fully_linked_archive_evidence_coverage_percent": _percentage(
                len(protected_linked_rows), len(closed_rows)
            ),
            "backup_pass_count": sum(
                1 for row in structural_event_rows if row["backup_status"] == "PASS"
            ),
            "restore_pass_count": sum(
                1 for row in structural_event_rows if row["restore_status"] == "PASS"
            ),
            "protection_denominator": len(structural_event_rows),
            "cursor_state": cursor_state,
            "cursor_contract_error_count": len(cursor_errors),
            "cursor_entry_count": len(cursor_entries),
            "cursor_status_counts": dict(sorted(cursor_status_counts.items())),
            "blocker_count": len(blockers),
        },
        "cursor_contract_errors": cursor_errors,
        "blockers": blockers,
        "gap_counts": {name: len(values) for name, values in gaps.items()},
        "gaps": gaps,
        "market_days": rows,
    }
    payload["audit_sha256"] = _canonical_hash(payload)
    return payload


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Event-Day Manifest And Archive Coverage Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"As of: `{payload.get('as_of_date')}`",
        f"Status: `{payload.get('status')}`",
        f"Audit SHA-256: `{payload.get('audit_sha256')}`",
        "",
        "This is a bounded manifest-index audit. It validates JSON shape, identities, self-hashes,",
        "cursor freshness/completeness, and manifest-to-manifest links. It does not walk or hash",
        "source tapes, open Parquet files, or re-run validation declared by archive manifests.",
        "Declared archive coverage is not a claim that Parquet data was revalidated.",
        "",
        "## Coverage",
        "",
        "| Metric | Value |",
        "| :--- | ---: |",
    ]
    for key, value in summary.items():
        lines.append(
            f"| {key} | {json.dumps(value, sort_keys=True) if isinstance(value, dict) else value} |"
        )
    lines += ["", "## Exact Gap Counts", "", "| Gap | Count |", "| :--- | ---: |"]
    for key, value in (payload.get("gap_counts") or {}).items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "The JSON artifact contains every gap slug, one row per snapshot folder, input-index",
        "digests, the cursor file hash, and a self-hash over the complete audit payload.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    payload: dict[str, Any],
    *,
    out_path: str | Path = DEFAULT_OUT,
    report_path: str | Path = DEFAULT_REPORT,
) -> tuple[Path, Path]:
    if not audit_hash_valid(payload):
        raise ValueError("event-day archive coverage audit self-hash is invalid")
    out = write_json_atomic(out_path, payload, trailing_newline=True)
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    tmp = report.with_name(f"{report.name}.{os.getpid()}.tmp")
    tmp.write_text(render_report(payload), encoding="utf-8")
    tmp.replace(report)
    return out, report


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    parser.add_argument("--cursor", default=str(DEFAULT_CURSOR))
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--cursor-max-age-hours", type=float, default=DEFAULT_CURSOR_MAX_AGE_HOURS)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    payload = build_payload(
        snapshots_root=args.snapshots_root,
        archive_root=args.archive_root,
        cursor_path=args.cursor,
        as_of_date=args.as_of_date,
        cursor_max_age_hours=args.cursor_max_age_hours,
    )
    out, report = write_outputs(payload, out_path=args.out, report_path=args.report)
    print(
        "Event-day/archive coverage: "
        f"{payload['status']} folders={payload['summary']['snapshot_folder_count']} "
        f"event_manifests={payload['summary']['closed_event_manifest_structurally_valid_count']} "
        f"fully_linked={payload['summary']['closed_fully_linked_archive_evidence_count']}"
    )
    print(f"JSON written to {out}")
    print(f"Report written to {report}")
    if args.strict and payload["status"] != "PASS":
        raise SystemExit(2)
    return payload


if __name__ == "__main__":
    main()
