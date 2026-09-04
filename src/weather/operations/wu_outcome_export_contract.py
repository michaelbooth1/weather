"""Build WU gap contracts and own the bounded production-export CLI.

The gap inventory stays outcome blind.  The production command delegates its
filesystem transaction to a small operations helper, then this module validates
the resulting two-file, research-only artifact.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any, Iterable, Mapping, Sequence


GAP_SCHEMA = "wu_outcome_gap_manifest_v1"
SPEC_SCHEMA = "wu_outcome_production_export_spec_v1"
EXPORT_MANIFEST_SCHEMA = "wu_outcome_production_export_manifest_v1"
EXPORT_ROW_SCHEMA = "wu_outcome_production_export_row_v1"
VALIDATION_SCHEMA = "wu_outcome_production_export_validation_v1"
MIN_WU_ROWS = 18
BOUNDARY_DATE = date(2026, 7, 31)
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_EXPORT_BYTES = 1024 * 1024
MAX_EXPORT_FILES = 2
EXPORT_FILENAMES = frozenset({"manifest.json", "wu-outcomes.jsonl"})
GAP_STATUSES = frozenset(
    {"present_admissible", "present_below_threshold", "missing"}
)
OUTCOME_KEY_FRAGMENTS = (
    "outcome",
    "temperature_value",
    "settlement_high",
    "settlement_bucket",
    "max_temp",
    "min_temp",
    "avg_temp",
    "dewpoint",
)
EXPORT_ROW_FIELDS = frozenset(
    {
        "schema_version",
        "market",
        "target_date",
        "provenance_side",
        "settlement_bucket_native",
        "settlement_unit",
        "wu_daily_row_count",
        "settlement_source",
        "resolution_source_type",
        "resolution_wu_history_id",
        "resolution_station",
        "resolution_timezone",
        "source_event_slug",
        "source_revision_id",
        "source_revision_number",
        "source_recorded_at_utc",
        "source_label_hash",
        "source_ledger_relative_path",
        "source_ledger_sha256",
        "source_daily_summary_relative_path",
        "source_daily_summary_sha256",
    }
)


class ContractError(ValueError):
    """Raised when an input or export fails the closed contract."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def self_hash(payload: Mapping[str, Any], field: str) -> str:
    copy = dict(payload)
    copy.pop(field, None)
    return canonical_sha256(copy)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, max_bytes: int = MAX_JSON_BYTES) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ContractError(f"required JSON is unavailable: {path}") from exc
    if size <= 0 or size > max_bytes:
        raise ContractError(f"JSON byte bound failed: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"JSON is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ContractError(f"JSON root must be an object: {path}")
    return payload


def _require_sha(value: Any, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ContractError(f"{label} is not a lowercase SHA-256")
    return text


def _require_utc_timestamp(value: Any, label: str) -> str:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContractError(f"{label} is not UTC")
    return text


def _portable_relative(value: Any, label: str) -> PurePosixPath:
    text = str(value or "")
    path = PurePosixPath(text)
    if (
        not text
        or "\\" in text
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ContractError(f"{label} is not a portable relative path")
    return path


def _is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    return bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _require_non_reparse_tree(path: Path, *, include_leaf: bool = True) -> None:
    candidate = path.absolute()
    parts = list(candidate.parents)
    parts.reverse()
    if include_leaf:
        parts.append(candidate)
    for part in parts:
        if part.exists() and _is_reparse(part):
            raise ContractError(f"reparse point is forbidden: {part}")


def _contained(root: Path, relative: Any, label: str) -> Path:
    portable = _portable_relative(relative, label)
    _require_non_reparse_tree(root)
    candidate = root.joinpath(*portable.parts)
    _require_non_reparse_tree(candidate)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ContractError(f"{label} escapes its declared root") from exc
    return candidate


def write_json_create_only(path: Path, payload: Mapping[str, Any]) -> Path:
    path = path.absolute()
    if path.exists():
        raise ContractError(f"create-only output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    _require_non_reparse_tree(path.parent)
    raw = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True).encode(
        "utf-8"
    ) + b"\n"
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ContractError(f"create-only output already exists: {path}") from exc
    return path


def _date_range(start: date, end: date) -> Iterable[date]:
    if end < start:
        raise ContractError("cohort end precedes cohort start")
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _cohort_contract(amendment: Mapping[str, Any]) -> list[tuple[str, date, date]]:
    if amendment.get("schema_version") != "multiyear_nwp_residual_external_amendment_v1":
        raise ContractError("frozen amendment schema differs")
    if amendment.get("amendment_sha256") != self_hash(amendment, "amendment_sha256"):
        raise ContractError("frozen amendment self-hash mismatch")
    boundary = amendment.get("provenance_boundary")
    if not isinstance(boundary, dict) or boundary.get("first_post_boundary_date") != BOUNDARY_DATE.isoformat():
        raise ContractError("frozen provenance boundary differs")
    if boundary.get("cohorts_must_never_be_pooled") is not True:
        raise ContractError("frozen cohort separation is not mandatory")
    cohorts = amendment.get("cohorts")
    if not isinstance(cohorts, dict) or set(cohorts) != {
        "pre_boundary",
        "post_boundary_directional",
    }:
        raise ContractError("frozen amendment cohort set differs")
    result: list[tuple[str, date, date]] = []
    for side in ("pre_boundary", "post_boundary_directional"):
        value = cohorts.get(side)
        if not isinstance(value, dict):
            raise ContractError(f"frozen cohort is invalid: {side}")
        try:
            start = date.fromisoformat(str(value["start_date"]))
            end = date.fromisoformat(str(value["end_date"]))
        except (KeyError, ValueError) as exc:
            raise ContractError(f"frozen cohort dates are invalid: {side}") from exc
        if side == "pre_boundary" and end >= BOUNDARY_DATE:
            raise ContractError("pre-boundary cohort crosses the boundary")
        if side == "post_boundary_directional" and start != BOUNDARY_DATE:
            raise ContractError("post-boundary cohort does not start at the anchor")
        result.append((side, start, end))
    return result


def _validate_frozen_sources(
    design_path: Path,
    amendment_path: Path,
    transfer_manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    design = _read_json(design_path)
    amendment = _read_json(amendment_path)
    transfer = _read_json(transfer_manifest_path)
    binding = amendment.get("frozen_identity")
    input_binding = amendment.get("input_binding")
    if not isinstance(binding, dict) or not isinstance(input_binding, dict):
        raise ContractError("frozen amendment bindings are missing")
    if sha256_file(design_path) != binding.get("design_file_sha256"):
        raise ContractError("frozen design file hash mismatch")
    if design.get("design_sha256") != binding.get("design_sha256"):
        raise ContractError("frozen design identity mismatch")
    if sha256_file(transfer_manifest_path) != input_binding.get("transfer_manifest_sha256"):
        raise ContractError("2026 transfer manifest file hash mismatch")
    if transfer.get("schema_version") != "pit_12field_transfer_manifest_v0.1":
        raise ContractError("2026 transfer manifest schema differs")
    if (
        transfer.get("market_count") != 12
        or transfer.get("field_count") != 12
        or transfer.get("leads") != [1, 2, 3, 4, 5, 6, 7]
        or transfer.get("combined_rows") != 1_645_056
    ):
        raise ContractError("2026 NWP transfer is incomplete")
    files = transfer.get("files")
    if not isinstance(files, list) or len(files) != transfer.get("required_file_count"):
        raise ContractError("2026 NWP transfer inventory differs")
    transfer_root = transfer_manifest_path.parent
    for row in files:
        if not isinstance(row, dict):
            raise ContractError("2026 NWP transfer inventory row is invalid")
        source = _contained(transfer_root, row.get("relative_path"), "transfer file")
        if not source.is_file() or source.stat().st_size != row.get("bytes"):
            raise ContractError(f"2026 NWP transfer file differs: {source}")
        if sha256_file(source) != row.get("sha256"):
            raise ContractError(f"2026 NWP transfer hash mismatch: {source}")
    _cohort_contract(amendment)
    return design, amendment, transfer


def _read_wu_support(path: Path, expected_unit: str) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    revisions: dict[str, int] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"schema_version", "local_date", "temperature_unit", "row_count"}
        if not required.issubset(reader.fieldnames or ()):
            raise ContractError(f"WU daily-summary support columns are missing: {path}")
        for ordinal, row in enumerate(reader, start=1):
            target = str(row.get("local_date") or "")
            try:
                date.fromisoformat(target)
            except ValueError as exc:
                raise ContractError(f"WU local_date is invalid: {path}:{ordinal}") from exc
            unit = str(row.get("temperature_unit") or "")
            if unit != expected_unit:
                raise ContractError(f"WU settlement unit differs: {path}:{ordinal}")
            try:
                row_count = int(str(row.get("row_count") or ""))
            except ValueError as exc:
                raise ContractError(f"WU row_count is invalid: {path}:{ordinal}") from exc
            if row_count < 0:
                raise ContractError(f"WU row_count is negative: {path}:{ordinal}")
            revision_text = str(row.get("revision_number") or "").strip()
            try:
                revision = int(revision_text) if revision_text else ordinal
            except ValueError as exc:
                raise ContractError(f"WU revision_number is invalid: {path}:{ordinal}") from exc
            revisions[target] = revisions.get(target, 0) + 1
            current = selected.get(target)
            candidate = {
                "row_count": row_count,
                "revision": revision,
                "ordinal": ordinal,
                "schema_version": str(row.get("schema_version") or ""),
            }
            if current is None or (revision, ordinal) > (
                current["revision"],
                current["ordinal"],
            ):
                selected[target] = candidate
    for target, row in selected.items():
        row["revision_count"] = revisions[target]
    return selected


def classify_wu_support(source_row: Mapping[str, Any] | None) -> tuple[str, str]:
    """Classify WU availability without accessing any settlement-value field."""

    if source_row is None:
        return "missing", "no_frozen_wu_daily_summary_row"
    row_count = source_row.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        raise ContractError("WU support row_count is invalid")
    if row_count < MIN_WU_ROWS:
        return "present_below_threshold", "wu_daily_row_count_below_18"
    return "present_admissible", "wu_daily_row_count_at_least_18"


def _assert_outcome_blind(value: Any, *, trail: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in OUTCOME_KEY_FRAGMENTS):
                raise ContractError(
                    "outcome-bearing field is forbidden in the gap manifest: "
                    + ".".join((*trail, str(key)))
                )
            _assert_outcome_blind(child, trail=(*trail, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_outcome_blind(child, trail=(*trail, str(index)))


def build_gap_manifest(
    *,
    mission_id: str,
    design_path: Path,
    amendment_path: Path,
    transfer_manifest_path: Path,
    wu_root: Path,
    expected_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Build the complete market/date support matrix without reading WU values."""

    _, amendment, _ = _validate_frozen_sources(
        design_path, amendment_path, transfer_manifest_path
    )
    input_binding = amendment["input_binding"]
    inventory = input_binding.get("outcome_source_file_inventory")
    units = amendment.get("methods", {}).get("native_units")
    if not isinstance(inventory, list) or not isinstance(units, dict):
        raise ContractError("frozen WU inventory or native-unit map is missing")
    if len(inventory) != 12 or len(units) != 12:
        raise ContractError("frozen WU inventory must contain exactly twelve markets")
    markets = [str(row.get("market") or "") for row in inventory if isinstance(row, dict)]
    if len(markets) != 12 or len(set(markets)) != 12:
        raise ContractError("frozen WU market identities are duplicate or missing")
    if len({market.casefold() for market in markets}) != len(markets):
        raise ContractError("frozen WU market identities have a case collision")
    if set(markets) != set(units):
        raise ContractError("frozen WU market and unit identities differ")

    support_by_market: dict[str, dict[str, dict[str, Any]]] = {}
    source_files = []
    for row in sorted(inventory, key=lambda item: str(item["market"])):
        market = str(row["market"])
        source = _contained(wu_root, row.get("relative_path"), "WU source file")
        if not source.is_file() or source.stat().st_size != row.get("bytes"):
            raise ContractError(f"frozen WU source file differs: {market}")
        digest = sha256_file(source)
        if digest != row.get("sha256"):
            raise ContractError(f"frozen WU source hash mismatch: {market}")
        support_by_market[market] = _read_wu_support(source, str(units[market]))
        source_files.append(
            {
                "market": market,
                "station": str(row.get("station") or ""),
                "relative_path": str(row["relative_path"]).replace("\\", "/"),
                "bytes": int(row["bytes"]),
                "sha256": digest,
            }
        )

    entries: list[dict[str, Any]] = []
    side_summary: dict[str, dict[str, Any]] = {}
    for side, start, end in _cohort_contract(amendment):
        counts = {status: 0 for status in sorted(GAP_STATUSES)}
        complete_dates = 0
        supported_dates = 0
        for target in _date_range(start, end):
            statuses = []
            for market in sorted(markets):
                source_row = support_by_market[market].get(target.isoformat())
                status, reason = classify_wu_support(source_row)
                if source_row is None:
                    row_count = None
                    revision_count = 0
                    selected_ordinal = None
                else:
                    row_count = source_row["row_count"]
                    revision_count = source_row["revision_count"]
                    selected_ordinal = source_row["ordinal"]
                statuses.append(status)
                counts[status] += 1
                inventory_row = next(item for item in inventory if item["market"] == market)
                entries.append(
                    {
                        "market": market,
                        "target_date": target.isoformat(),
                        "provenance_side": side,
                        "status": status,
                        "reason": reason,
                        "authority": "configured_wunderground_daily_summary",
                        "station": str(inventory_row["station"]),
                        "settlement_unit": str(units[market]),
                        "row_count": row_count,
                        "revision_count": revision_count,
                        "selected_revision_ordinal": selected_ordinal,
                    }
                )
            if all(status == "present_admissible" for status in statuses):
                complete_dates += 1
            if any(status == "present_admissible" for status in statuses):
                supported_dates += 1
        requested = sum(counts.values())
        side_summary[side] = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "requested_dates": (end - start).days + 1,
            "requested_market_days": requested,
            "admissible_market_days": counts["present_admissible"],
            "below_threshold_market_days": counts["present_below_threshold"],
            "missing_market_days": counts["missing"],
            "fully_complete_dates": complete_dates,
            "dates_with_any_admissible_market": supported_dates,
        }
    totals = {
        "requested_dates": sum(row["requested_dates"] for row in side_summary.values()),
        "requested_market_days": len(entries),
        "admissible_market_days": sum(
            row["admissible_market_days"] for row in side_summary.values()
        ),
        "below_threshold_market_days": sum(
            row["below_threshold_market_days"] for row in side_summary.values()
        ),
        "missing_market_days": sum(
            row["missing_market_days"] for row in side_summary.values()
        ),
        "fully_complete_dates": sum(
            row["fully_complete_dates"] for row in side_summary.values()
        ),
        "dates_with_any_admissible_market": sum(
            row["dates_with_any_admissible_market"] for row in side_summary.values()
        ),
        "maximum_attainable_complete_dates": sum(
            row["requested_dates"] for row in side_summary.values()
        ),
        "maximum_attainable_market_days": len(entries),
    }
    if expected_counts:
        for key, expected in expected_counts.items():
            if totals.get(key) != expected:
                raise ContractError(
                    f"frozen WU aggregate contradiction for {key}: "
                    f"expected {expected}, observed {totals.get(key)}"
                )
    payload: dict[str, Any] = {
        "schema_version": GAP_SCHEMA,
        "mission_id": mission_id,
        "status": "COMPLETE_OUTCOME_BLIND_INVENTORY",
        "minimum_wu_daily_row_count": MIN_WU_ROWS,
        "source_bindings": {
            "design": {
                "path": str(design_path.absolute()),
                "bytes": design_path.stat().st_size,
                "sha256": sha256_file(design_path),
            },
            "amendment": {
                "path": str(amendment_path.absolute()),
                "bytes": amendment_path.stat().st_size,
                "sha256": sha256_file(amendment_path),
                "self_hash": amendment["amendment_sha256"],
            },
            "transfer_manifest": {
                "path": str(transfer_manifest_path.absolute()),
                "bytes": transfer_manifest_path.stat().st_size,
                "sha256": sha256_file(transfer_manifest_path),
            },
            "wu_root": str(wu_root.absolute()),
            "wu_source_files": source_files,
        },
        "provenance_boundary": {
            "anchor": amendment["provenance_boundary"]["anchor"],
            "first_post_boundary_date": BOUNDARY_DATE.isoformat(),
            "cohorts_kept_separate": True,
        },
        "summary_by_provenance_side": side_summary,
        "totals": totals,
        "entries": entries,
        "outcome_values_read": 0,
        "outcome_fields_accessed": [],
        "substitute_sources_used": [],
    }
    _assert_outcome_blind({key: value for key, value in payload.items() if key not in {"outcome_values_read", "outcome_fields_accessed"}})
    payload["gap_manifest_sha256"] = self_hash(payload, "gap_manifest_sha256")
    return payload


def _validate_gap(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != GAP_SCHEMA:
        raise ContractError("gap manifest schema differs")
    if payload.get("gap_manifest_sha256") != self_hash(payload, "gap_manifest_sha256"):
        raise ContractError("gap manifest self-hash mismatch")
    if payload.get("outcome_values_read") != 0 or payload.get("outcome_fields_accessed") != []:
        raise ContractError("gap manifest is not outcome blind")
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) != 816:
        raise ContractError("gap manifest must contain all 816 market-date keys")
    _assert_outcome_blind(
        {key: value for key, value in payload.items() if key not in {"outcome_values_read", "outcome_fields_accessed"}}
    )


def _load_context_manifest(path: Path, role: str) -> dict[str, Any]:
    payload = _read_json(path)
    counts = payload.get("counts")
    rollups = payload.get("coverage_rollups")
    if not isinstance(counts, dict) or not isinstance(rollups, dict):
        raise ContractError(f"{role} coverage manifest is incomplete")
    if payload.get("corpus_manifest_sha256") != self_hash(
        payload, "corpus_manifest_sha256"
    ):
        raise ContractError(f"{role} coverage manifest self-hash mismatch")
    count_rollups = {
        dimension: [
            {
                key: value
                for key, value in row.items()
                if key != "coverage_fraction"
            }
            for row in rows
        ]
        for dimension, rows in rollups.items()
        if isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
    }
    return {
        "role": role,
        "path": str(path.absolute()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "self_hash": payload.get("corpus_manifest_sha256"),
        "counts": counts,
        "coverage_count_rollups": count_rollups,
    }


def build_export_spec(
    *,
    mission_id: str,
    gap_path: Path,
    multiyear_manifest_path: Path,
    calendar_manifest_path: Path,
) -> dict[str, Any]:
    """Build the minimal machine contract for a missing production exporter."""

    gap = _read_json(gap_path)
    _validate_gap(gap)
    requests = [
        {
            "market": row["market"],
            "target_date": row["target_date"],
            "provenance_side": row["provenance_side"],
            "local_status": row["status"],
            "station": row["station"],
            "settlement_unit": row["settlement_unit"],
        }
        for row in gap["entries"]
        if row["status"] != "present_admissible"
    ]
    if len(requests) != 96:
        raise ContractError("production request set must contain exactly 96 WU gaps")
    multiyear = _load_context_manifest(multiyear_manifest_path, "multiyear_2021_2025")
    calendar = _load_context_manifest(calendar_manifest_path, "calendar_extension_2024_2025")
    payload: dict[str, Any] = {
        "schema_version": SPEC_SCHEMA,
        "mission_id": mission_id,
        "status": "PRODUCTION_EXPORTER_REQUIRED",
        "production_entry_point": {
            "status_at_source_tip": "ABSENT",
            "command": None,
            "reason": "no reviewed read-only WU settlement export entry point exists",
            "smallest_missing_implementation": (
                "read verified settlement ledgers, select authoritative revisions, "
                "and create the two-file artifact defined here"
            ),
        },
        "gap_binding": {
            "path": str(gap_path.absolute()),
            "bytes": gap_path.stat().st_size,
            "file_sha256": sha256_file(gap_path),
            "self_hash": gap["gap_manifest_sha256"],
        },
        "request": {
            "requested_rows": len(requests),
            "keys": requests,
            "all_twelve_markets_required": True,
            "missing_or_below_threshold_only": True,
            "absence_is_terminal": True,
        },
        "boundary": {
            "first_post_boundary_date": BOUNDARY_DATE.isoformat(),
            "pre_and_post_rows_must_remain_separate": True,
            "pooling_permitted": False,
        },
        "authoritative_source": {
            "ledger_pattern": "data/settlements/<market>/ledger.jsonl",
            "deduplication_key": ["market_id", "target_date"],
            "latest_revision_order": ["revision_number", "append_order"],
            "equal_explicit_revision_conflict": "FAIL_CLOSED",
            "market_case_collision": "FAIL_CLOSED",
            "required_settlement_source": "daily_summary",
            "required_resolution_source_type": "wunderground_history",
            "minimum_evidence_summary_row_count": MIN_WU_ROWS,
            "configured_station_and_native_unit_match_required": True,
            "substitute_weather_sources_permitted": [],
            "ledger_history_verification_required": True,
        },
        "source_stability": {
            "pre_and_post_sha256_required": True,
            "pre_and_post_bytes_required": True,
            "identical_pre_and_post_identity_required": True,
            "bound_files": ["settlement_ledger", "wu_daily_summary"],
        },
        "destination": {
            "create_only": True,
            "must_not_exist_before_start": True,
            "must_be_non_reparse": True,
            "all_ancestors_must_be_non_reparse": True,
            "portable_relative_names_only": True,
            "exact_filenames": sorted(EXPORT_FILENAMES),
            "maximum_files": MAX_EXPORT_FILES,
            "maximum_total_bytes": MAX_EXPORT_BYTES,
            "acl_proof_required": True,
            "acl_proof_fields": ["owner", "sddl", "sddl_sha256"],
        },
        "payload": {
            "filename": "wu-outcomes.jsonl",
            "schema_version": EXPORT_ROW_SCHEMA,
            "encoding": "UTF-8",
            "allowed_fields": sorted(EXPORT_ROW_FIELDS),
            "maximum_rows": len(requests),
            "exact_request_key_coverage_required": True,
            "duplicate_keys": "FAIL_CLOSED",
            "extra_keys": "FAIL_CLOSED",
        },
        "manifest": {
            "filename": "manifest.json",
            "schema_version": EXPORT_MANIFEST_SCHEMA,
            "canonical_self_hash": {
                "algorithm": "sha256",
                "serialization": "sorted keys, compact separators, ASCII JSON",
                "excluded_field": "manifest_sha256",
            },
            "per_file_sha256_and_bytes_required": True,
        },
        "prohibited_content": [
            "credentials",
            "provider requests",
            "market prices",
            "predictions",
            "probabilities",
            "model coefficients",
            "evaluation metrics",
        ],
        "nwp_coverage_context_only": {
            "kept_separate_from_wu_gap": True,
            "multiyear": multiyear,
            "calendar_extension": calendar,
            "2026_target_transfer": {
                "status": "COMPLETE",
                "rows": 1_645_056,
                "markets": 12,
                "fields": 12,
                "leads": [1, 2, 3, 4, 5, 6, 7],
                "missing_rows": 0,
            },
        },
        "downstream_authority": {
            "model_refit_authorized": False,
            "probability_generation_authorized": False,
            "scoring_authorized": False,
            "promotion_authorized": False,
            "live_use_authorized": False,
        },
    }
    payload["spec_sha256"] = self_hash(payload, "spec_sha256")
    return payload


def latest_authoritative_ledger_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Select current rows by market/date while refusing ambiguous revisions."""

    selected: dict[tuple[str, str], tuple[int, int, Mapping[str, Any]]] = {}
    seen_case: dict[str, str] = {}
    explicit_revisions: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    for ordinal, row in enumerate(rows, start=1):
        market = str(row.get("market_id") or "")
        folded = market.casefold()
        if not market or (folded in seen_case and seen_case[folded] != market):
            raise ContractError("settlement ledger market case collision")
        seen_case[folded] = market
        if market != folded:
            raise ContractError("settlement ledger market must use canonical lowercase")
        target = str(row.get("target_date") or "")
        try:
            date.fromisoformat(target)
        except ValueError as exc:
            raise ContractError("settlement ledger target date is invalid") from exc
        raw_revision = row.get("revision_number")
        if raw_revision is None:
            revision = 0
        elif isinstance(raw_revision, bool) or not isinstance(raw_revision, int) or raw_revision < 1:
            raise ContractError("explicit settlement revision number is invalid")
        else:
            revision = raw_revision
            revision_key = (market, target, revision)
            prior = explicit_revisions.get(revision_key)
            if prior is not None and canonical_sha256(prior) != canonical_sha256(row):
                raise ContractError("conflicting duplicate explicit settlement revision")
            explicit_revisions[revision_key] = row
        key = (market, target)
        current = selected.get(key)
        if current is None or (revision, ordinal) > (current[0], current[1]):
            selected[key] = (revision, ordinal, row)
    return {key: value[2] for key, value in selected.items()}


def _validate_acl_proof(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"owner", "sddl", "sddl_sha256"}:
        raise ContractError("export ACL proof fields differ")
    owner = str(value.get("owner") or "")
    sddl = str(value.get("sddl") or "")
    if not owner or not sddl:
        raise ContractError("export ACL proof is empty")
    if value.get("sddl_sha256") != hashlib.sha256(sddl.encode("utf-8")).hexdigest():
        raise ContractError("export ACL proof hash mismatch")


def validate_export(*, spec_path: Path, export_root: Path) -> dict[str, Any]:
    """Validate a bounded future production artifact without reporting outcomes."""

    spec = _read_json(spec_path)
    if spec.get("schema_version") != SPEC_SCHEMA:
        raise ContractError("export spec schema differs")
    if spec.get("spec_sha256") != self_hash(spec, "spec_sha256"):
        raise ContractError("export spec self-hash mismatch")
    export_root = export_root.absolute()
    if not export_root.is_dir():
        raise ContractError("export root is missing")
    _require_non_reparse_tree(export_root)
    files = [path for path in export_root.iterdir() if path.is_file()]
    if any(path.is_dir() for path in export_root.iterdir()):
        raise ContractError("export root contains a directory")
    names = [path.name for path in files]
    if len({name.casefold() for name in names}) != len(names):
        raise ContractError("export filenames have a case collision")
    if set(names) != EXPORT_FILENAMES or len(files) != MAX_EXPORT_FILES:
        raise ContractError("export root does not contain the exact two files")
    if sum(path.stat().st_size for path in files) > MAX_EXPORT_BYTES:
        raise ContractError("export byte bound exceeded")
    for path in files:
        _require_non_reparse_tree(path)

    manifest_path = export_root / "manifest.json"
    payload_path = export_root / "wu-outcomes.jsonl"
    manifest = _read_json(manifest_path)
    canonical_manifest = json.dumps(
        manifest, indent=2, sort_keys=True, ensure_ascii=True
    ).encode("utf-8") + b"\n"
    if manifest_path.read_bytes() != canonical_manifest:
        raise ContractError("export manifest encoding is not canonical")
    if manifest.get("schema_version") != EXPORT_MANIFEST_SCHEMA:
        raise ContractError("export manifest schema differs")
    if manifest.get("manifest_sha256") != self_hash(manifest, "manifest_sha256"):
        raise ContractError("export manifest self-hash mismatch")
    if manifest.get("spec_sha256") != spec["spec_sha256"]:
        raise ContractError("export manifest spec binding differs")
    if manifest.get("gap_manifest_sha256") != spec["gap_binding"]["self_hash"]:
        raise ContractError("export manifest gap binding differs")
    if manifest.get("status") != "COMPLETE_CREATE_ONLY_EXPORT":
        raise ContractError("export manifest is not terminal complete")
    if manifest.get("requested_rows") != spec["request"]["requested_rows"]:
        raise ContractError("export requested-row count differs")
    if manifest.get("exported_rows") != spec["request"]["requested_rows"]:
        raise ContractError("export row coverage is incomplete")
    if "downstream_authority" in spec and manifest.get("downstream_authority") != spec.get(
        "downstream_authority"
    ):
        raise ContractError("export downstream authority differs")
    _validate_acl_proof(manifest.get("destination_acl_proof"))
    if os.name == "nt":
        from weather.operations.wu_outcome_production_exporter import (
            _windows_acl_proof,
        )

        if manifest.get("destination_acl_proof") != _windows_acl_proof(export_root):
            raise ContractError("export ACL proof does not match the destination")
    payload_binding = manifest.get("payload_file")
    if not isinstance(payload_binding, dict) or set(payload_binding) != {
        "relative_path",
        "bytes",
        "sha256",
        "rows",
    }:
        raise ContractError("export payload binding differs")
    if _portable_relative(payload_binding["relative_path"], "payload file") != PurePosixPath("wu-outcomes.jsonl"):
        raise ContractError("export payload filename differs")
    if payload_binding.get("bytes") != payload_path.stat().st_size:
        raise ContractError("export payload byte count differs")
    if payload_binding.get("sha256") != sha256_file(payload_path):
        raise ContractError("export payload hash mismatch")

    source_files = manifest.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise ContractError("export source-file bindings are absent")
    source_bindings: dict[tuple[str, str], str] = {}
    for row in source_files:
        if not isinstance(row, dict) or set(row) != {
            "role",
            "relative_path",
            "bytes_before",
            "bytes_after",
            "sha256_before",
            "sha256_after",
        }:
            raise ContractError("export source-file binding fields differ")
        if row.get("role") not in {"settlement_ledger", "wu_daily_summary"}:
            raise ContractError("export source-file role differs")
        relative = _portable_relative(row.get("relative_path"), "source file").as_posix()
        binding_key = (str(row["role"]), relative.casefold())
        if binding_key in source_bindings:
            raise ContractError("export source-file bindings are duplicate or case-colliding")
        if row.get("bytes_before") != row.get("bytes_after"):
            raise ContractError("export source file changed bytes during export")
        before = _require_sha(row.get("sha256_before"), "source pre-hash")
        if before != _require_sha(row.get("sha256_after"), "source post-hash"):
            raise ContractError("export source file changed hash during export")
        source_bindings[binding_key] = before

    request_rows = spec.get("request", {}).get("keys")
    if not isinstance(request_rows, list) or not request_rows:
        raise ContractError("export request keys are absent")
    requests: dict[tuple[str, str], Mapping[str, Any]] = {}
    request_market_case: dict[str, str] = {}
    for request in request_rows:
        if not isinstance(request, dict):
            raise ContractError("export request row is invalid")
        market = str(request.get("market") or "")
        folded = market.casefold()
        if not market or (folded in request_market_case and request_market_case[folded] != market):
            raise ContractError("export request markets have a case collision")
        request_market_case[folded] = market
        target = str(request.get("target_date") or "")
        try:
            date.fromisoformat(target)
        except ValueError as exc:
            raise ContractError("export request target date is invalid") from exc
        request_key = (market, target)
        if request_key in requests:
            raise ContractError("export request contains a duplicate market/date key")
        requests[request_key] = request
    if len(requests) != spec["request"].get("requested_rows"):
        raise ContractError("export request count differs")
    expected_source_bindings = {
        ("settlement_ledger", f"data/settlements/{market}/ledger.jsonl".casefold())
        for market, _target in requests
    }
    expected_source_bindings.update(
        {
            (
                "wu_daily_summary",
                (
                    "data/wunderground/"
                    f"{str(request['station']).casefold()}/daily/daily_summary.csv"
                ).casefold(),
            )
            for request in requests.values()
        }
    )
    if set(source_bindings) != expected_source_bindings:
        raise ContractError("export source-file binding set differs")
    from weather.market.market_registry import BUILTIN_SPECS

    configured_markets = {item.id: item for item in BUILTIN_SPECS}
    seen: set[tuple[str, str]] = set()
    market_case: dict[str, str] = {}
    row_count = 0
    with payload_path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ContractError("export payload contains a blank row")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractError(f"export payload JSON is invalid at line {line_number}") from exc
            if not isinstance(row, dict) or set(row) != EXPORT_ROW_FIELDS:
                raise ContractError(f"export payload fields differ at line {line_number}")
            if line.encode("utf-8") != canonical_json_bytes(row) + b"\n":
                raise ContractError(f"export payload encoding differs at line {line_number}")
            if row.get("schema_version") != EXPORT_ROW_SCHEMA:
                raise ContractError("export row schema differs")
            market = str(row.get("market") or "")
            folded = market.casefold()
            if folded in market_case and market_case[folded] != market:
                raise ContractError("export market identities have a case collision")
            market_case[folded] = market
            target = str(row.get("target_date") or "")
            key = (market, target)
            request = requests.get(key)
            if request is None:
                raise ContractError("export contains an unrequested key")
            if key in seen:
                raise ContractError("export contains a duplicate market/date key")
            seen.add(key)
            expected_side = (
                "post_boundary_directional"
                if date.fromisoformat(target) >= BOUNDARY_DATE
                else "pre_boundary"
            )
            if row.get("provenance_side") != expected_side or expected_side != request["provenance_side"]:
                raise ContractError("export row crosses the provenance boundary")
            if row.get("settlement_unit") != request["settlement_unit"]:
                raise ContractError("export row native unit differs")
            if str(row.get("resolution_station") or "").casefold() != str(request["station"]).casefold():
                raise ContractError("export row station differs")
            if row.get("settlement_source") != "daily_summary" or row.get("resolution_source_type") != "wunderground_history":
                raise ContractError("export row is not authoritative WU evidence")
            if not str(row.get("resolution_wu_history_id") or ""):
                raise ContractError("export row WU history identity is absent")
            if not str(row.get("resolution_timezone") or ""):
                raise ContractError("export row timezone is absent")
            configured = configured_markets.get(market)
            if configured is None:
                raise ContractError("export row market is not configured")
            expected_slug = (
                f"{configured.slug_prefix}-"
                f"{date.fromisoformat(target).strftime('%B').lower()}-"
                f"{date.fromisoformat(target).day}-{date.fromisoformat(target).year}"
            )
            if (
                row.get("resolution_wu_history_id") != configured.wu_history_id
                or str(row.get("resolution_station") or "").casefold()
                != configured.icao.casefold()
                or row.get("resolution_timezone") != configured.timezone
                or row.get("settlement_unit") != configured.display_unit
                or row.get("source_event_slug") != expected_slug
            ):
                raise ContractError("export row configured resolution identity differs")
            if isinstance(row.get("wu_daily_row_count"), bool) or not isinstance(row.get("wu_daily_row_count"), int) or row["wu_daily_row_count"] < MIN_WU_ROWS:
                raise ContractError("export row WU support is below threshold")
            bucket = row.get("settlement_bucket_native")
            if isinstance(bucket, bool) or not isinstance(bucket, int):
                raise ContractError("export row native settlement bucket is invalid")
            if isinstance(row.get("source_revision_number"), bool) or not isinstance(row.get("source_revision_number"), int) or row["source_revision_number"] < 0:
                raise ContractError("export row revision number is invalid")
            if not str(row.get("source_revision_id") or ""):
                raise ContractError("export row revision identity is absent")
            _require_utc_timestamp(row.get("source_recorded_at_utc"), "export row revision time")
            _require_sha(row.get("source_label_hash"), "export row label hash")
            if not str(row.get("source_event_slug") or ""):
                raise ContractError("export row event slug is absent")
            expected_ledger_path = f"data/settlements/{market}/ledger.jsonl"
            expected_daily_path = (
                "data/wunderground/"
                f"{str(request['station']).casefold()}/daily/daily_summary.csv"
            )
            if row.get("source_ledger_relative_path") != expected_ledger_path:
                raise ContractError("export row ledger path differs")
            if row.get("source_daily_summary_relative_path") != expected_daily_path:
                raise ContractError("export row daily-summary path differs")
            for key_name in (
                "source_ledger_sha256",
                "source_daily_summary_sha256",
            ):
                _require_sha(row.get(key_name), key_name)
            for path_name in (
                "source_ledger_relative_path",
                "source_daily_summary_relative_path",
            ):
                _portable_relative(row.get(path_name), path_name)
            for role, path_name, hash_name in (
                (
                    "settlement_ledger",
                    "source_ledger_relative_path",
                    "source_ledger_sha256",
                ),
                (
                    "wu_daily_summary",
                    "source_daily_summary_relative_path",
                    "source_daily_summary_sha256",
                ),
            ):
                identity_key = (role, str(row[path_name]).casefold())
                if source_bindings.get(identity_key) != row[hash_name]:
                    raise ContractError("export row source identity is not manifest-bound")
            row_count += 1
    if seen != set(requests):
        raise ContractError("export does not cover every requested market/date key")
    if payload_binding.get("rows") != row_count:
        raise ContractError("export payload row binding differs")
    return {
        "schema_version": VALIDATION_SCHEMA,
        "status": "PASS",
        "spec_sha256": spec["spec_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "payload_sha256": payload_binding["sha256"],
        "requested_rows": len(requests),
        "validated_rows": row_count,
        "outcome_values_reported": 0,
    }


def _parse_expected_counts(value: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in value.split(","):
        key, separator, raw = item.partition("=")
        if not separator:
            raise argparse.ArgumentTypeError("expected counts must use key=integer")
        try:
            result[key] = int(raw)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("expected count is not an integer") from exc
    return result


def export_production(
    *, repo_root: Path, spec_path: Path, destination: Path
) -> dict[str, Any]:
    """Create one reviewed, fail-closed production WU outcome export."""

    from weather.operations.wu_outcome_production_exporter import (
        export_production as _export_production,
    )

    return _export_production(
        repo_root=repo_root,
        spec_path=spec_path,
        destination=destination,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    gap = commands.add_parser("build-gap")
    gap.add_argument("--mission-id", required=True)
    gap.add_argument("--design", type=Path, required=True)
    gap.add_argument("--amendment", type=Path, required=True)
    gap.add_argument("--transfer-manifest", type=Path, required=True)
    gap.add_argument("--wu-root", type=Path, required=True)
    gap.add_argument("--expected-counts", type=_parse_expected_counts, required=True)
    gap.add_argument("--output", type=Path, required=True)
    spec = commands.add_parser("build-spec")
    spec.add_argument("--mission-id", required=True)
    spec.add_argument("--gap", type=Path, required=True)
    spec.add_argument("--multiyear-manifest", type=Path, required=True)
    spec.add_argument("--calendar-manifest", type=Path, required=True)
    spec.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate-export")
    validate.add_argument("--spec", type=Path, required=True)
    validate.add_argument("--export-root", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    production = commands.add_parser("export-production")
    production.add_argument("--repo-root", type=Path, required=True)
    production.add_argument("--spec", type=Path, required=True)
    production.add_argument("--destination", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build-gap":
            payload = build_gap_manifest(
                mission_id=args.mission_id,
                design_path=args.design,
                amendment_path=args.amendment,
                transfer_manifest_path=args.transfer_manifest,
                wu_root=args.wu_root,
                expected_counts=args.expected_counts,
            )
            write_json_create_only(args.output, payload)
            print(
                f"WU gap manifest created: {args.output} "
                f"sha256={payload['gap_manifest_sha256']}"
            )
        elif args.command == "build-spec":
            payload = build_export_spec(
                mission_id=args.mission_id,
                gap_path=args.gap,
                multiyear_manifest_path=args.multiyear_manifest,
                calendar_manifest_path=args.calendar_manifest,
            )
            write_json_create_only(args.output, payload)
            print(
                f"WU export spec created: {args.output} "
                f"sha256={payload['spec_sha256']}"
            )
        elif args.command == "validate-export":
            payload = validate_export(spec_path=args.spec, export_root=args.export_root)
            if args.output:
                payload["validation_sha256"] = self_hash(
                    payload, "validation_sha256"
                )
                write_json_create_only(args.output, payload)
            print(
                f"WU export validation PASS: rows={payload['validated_rows']} "
                f"payload_sha256={payload['payload_sha256']}"
            )
        else:
            payload = export_production(
                repo_root=args.repo_root,
                spec_path=args.spec,
                destination=args.destination,
            )
            print(
                "WU production export PASS: "
                f"destination={payload['destination']} "
                f"rows={payload['exported_rows']} "
                f"manifest_sha256={payload['manifest_sha256']} "
                f"payload_sha256={payload['payload_sha256']}"
            )
    except (ContractError, OSError, TypeError, ValueError) as exc:
        print(f"WU outcome export contract BLOCK: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
