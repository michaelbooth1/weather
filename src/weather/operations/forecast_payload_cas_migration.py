"""Inventory-only migration and partial reachability scan for the shared CAS.

This command intentionally has no apply, rewrite, garbage-collection, or delete
mode.  It proves what *could* be migrated while legacy evidence remains intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from weather.collection.forecast_payload_cas import (
    RAW_BYTES_HASH_ALGORITHM,
    SHARED_FORECAST_PAYLOAD_CAS_KIND,
    SHARED_FORECAST_PAYLOAD_SCOPE,
    ForecastPayloadCASIntegrityError,
    SharedForecastPayloadCAS,
    shared_payload_ref,
    validate_sha256,
    validate_nbm_shared_manifest_identity,
)
from weather.forecast_payload_contracts import NBM_NBP_ENCODING, NBM_NBP_MEDIA_TYPE
from weather.paths import data_path
from weather.sources.nbm_probabilistic_tmax import replay_nbp_shared_payload


SCHEMA_VERSION = "forecast_payload_cas_migration_dry_run_v0.2"
DEFAULT_SNAPSHOT_ROOT = data_path("snapshots")
DEFAULT_SHARED_CAS_ROOT = data_path("forecast_payload_cas")
DEFAULT_JSON_OUT = data_path("backtest", "forecast_payload_cas_migration_dry_run.json")
DEFAULT_REPORT_OUT = data_path(
    "backtest", "forecast_payload_cas_migration_dry_run_report.md"
)
DEFAULT_MAX_MANIFEST_COUNT = 2_500
DEFAULT_MAX_MANIFEST_ROW_COUNT = 100_000
DEFAULT_MAX_PAYLOAD_BYTES_READ = 8 * 1024 * 1024 * 1024
DEFAULT_MAX_ELAPSED_SECONDS = 300.0
DEFAULT_CANDIDATE_DETAIL_LIMIT = 1_000
DEFAULT_MAX_PHYSICAL_BLOB_COUNT = 250_000
DEFAULT_MAX_DIRECTORY_COUNT = 100_000
DEFAULT_MAX_TREE_ENTRY_COUNT = 1_000_000
DEFAULT_MAX_JSONL_LINE_BYTES = 1024 * 1024
DEFAULT_MAX_MANIFEST_BYTES_READ = 256 * 1024 * 1024
DEFAULT_MAX_SINGLE_PAYLOAD_BYTES = 128 * 1024 * 1024
_MONTH_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})")


class InventoryLimitReached(RuntimeError):
    def __init__(self, reason: str, cursor: Mapping[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.cursor = dict(cursor or {}) or None


@dataclass
class InventoryBudget:
    monotonic_fn: Callable[[], float]
    started: float
    max_elapsed_seconds: float
    max_directory_count: int
    max_tree_entry_count: int
    max_jsonl_line_bytes: int
    max_manifest_bytes_read: int
    max_payload_bytes_read: int
    max_single_payload_bytes: int
    directory_count: int = 0
    tree_entry_count: int = 0
    manifest_bytes_read: int = 0
    payload_bytes_read: int = 0

    def check_time(self, cursor: Mapping[str, Any] | None = None) -> None:
        if self.monotonic_fn() - self.started >= self.max_elapsed_seconds:
            raise InventoryLimitReached("max_elapsed_seconds", cursor)

    def enter_directory(self, path: Path) -> None:
        cursor = {"directory_path": str(path)}
        self.check_time(cursor)
        if self.directory_count >= self.max_directory_count:
            raise InventoryLimitReached("max_directory_count", cursor)
        self.directory_count += 1

    def observe_tree_entry(self, path: Path) -> None:
        cursor = {"tree_entry_path": str(path)}
        self.check_time(cursor)
        if self.tree_entry_count >= self.max_tree_entry_count:
            raise InventoryLimitReached("max_tree_entry_count", cursor)
        self.tree_entry_count += 1

    def read_manifest_line(
        self,
        handle,
        *,
        manifest_path: Path,
        line_number: int,
    ) -> bytes:
        cursor = {
            "manifest_path": str(manifest_path),
            "line_number": line_number,
        }
        self.check_time(cursor)
        remaining = self.max_manifest_bytes_read - self.manifest_bytes_read
        if remaining <= 0:
            if handle.tell() >= os.fstat(handle.fileno()).st_size:
                return b""
            raise InventoryLimitReached("max_manifest_bytes_read", cursor)
        read_limit = min(self.max_jsonl_line_bytes, remaining)
        line = handle.readline(read_limit)
        if not line:
            self.check_time(cursor)
            return b""
        self.manifest_bytes_read += len(line)
        # Do not read a sentinel byte beyond either configured byte ceiling.
        # A regular-file size check tells us whether readline stopped at EOF or
        # because the current JSONL record continues beyond the allowed bytes.
        if (
            len(line) == read_limit
            and not line.endswith(b"\n")
            and handle.tell() < os.fstat(handle.fileno()).st_size
        ):
            if self.max_jsonl_line_bytes <= remaining:
                raise InventoryLimitReached("max_jsonl_line_bytes", {
                    **cursor,
                    "observed_line_bytes_lower_bound": len(line) + 1,
                })
            raise InventoryLimitReached("max_manifest_bytes_read", {
                **cursor,
                "observed_manifest_bytes_lower_bound": (
                    self.manifest_bytes_read + 1
                ),
            })
        self.check_time(cursor)
        return line

    def preflight_payload(self, path: Path, size: int, cursor: Mapping[str, Any]) -> None:
        self.check_time(cursor)
        if size > self.max_single_payload_bytes:
            raise InventoryLimitReached("max_single_payload_bytes", {
                **dict(cursor),
                "payload_path": str(path),
                "payload_bytes": size,
            })
        if self.payload_bytes_read + size > self.max_payload_bytes_read:
            raise InventoryLimitReached("max_payload_bytes_read", {
                **dict(cursor),
                "payload_path": str(path),
                "next_payload_bytes": size,
            })


def _iter_jsonl(
    path: Path,
    budget: InventoryBudget,
) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("rb") as handle:
        line_number = 0
        while True:
            line_number += 1
            line = budget.read_manifest_line(
                handle,
                manifest_path=path,
                line_number=line_number,
            )
            if not line:
                break
            try:
                text = line.decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                yield line_number, {"_read_error": f"invalid_utf8:{exc.reason}"}
                continue
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                yield line_number, {"_read_error": f"invalid_json:{exc.msg}"}
                continue
            budget.check_time({"manifest_path": str(path), "line_number": line_number})
            if not isinstance(row, dict):
                yield line_number, {"_read_error": "row_not_object"}
                continue
            yield line_number, row


def _iter_tree_files(
    root: Path,
    *,
    budget: InventoryBudget,
    predicate: Callable[[str], bool],
) -> Iterable[Path]:
    """Traverse deterministically with directory, entry, and time ceilings."""

    root_cursor = {"directory_path": str(root)}
    budget.check_time(root_cursor)
    try:
        root_stat = os.stat(root, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise InventoryLimitReached("tree_scan_error", {
            **root_cursor,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }) from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise InventoryLimitReached("tree_root_not_directory", root_cursor)
    budget.check_time(root_cursor)
    pending = [root]
    while pending:
        folder = pending.pop()
        budget.enter_directory(folder)
        child_directories: list[Path] = []
        matched_files: list[Path] = []
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    entry_path = Path(entry.path)
                    budget.observe_tree_entry(entry_path)
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except FileNotFoundError as exc:
                        raise InventoryLimitReached(
                            "tree_changed_during_inventory",
                            {"tree_entry_path": str(entry_path)},
                        ) from exc
                    except OSError as exc:
                        raise InventoryLimitReached("tree_scan_error", {
                            "tree_entry_path": str(entry_path),
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }) from exc
                    if stat.S_ISDIR(entry_stat.st_mode):
                        child_directories.append(entry_path)
                    elif (
                        stat.S_ISREG(entry_stat.st_mode)
                        and predicate(entry.name)
                    ):
                        matched_files.append(entry_path)
                    budget.check_time({"tree_entry_path": str(entry_path)})
        except FileNotFoundError as exc:
            raise InventoryLimitReached("tree_changed_during_inventory", {
                "directory_path": str(folder),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }) from exc
        except OSError as exc:
            raise InventoryLimitReached("tree_scan_error", {
                "directory_path": str(folder),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }) from exc
        budget.check_time({"directory_path": str(folder)})
        for path in sorted(matched_files):
            budget.check_time({"matched_path": str(path)})
            yield path
        pending.extend(reversed(sorted(child_directories)))


def _iter_named_files(
    root: Path,
    filename: str,
    *,
    budget: InventoryBudget,
) -> Iterable[Path]:
    yield from _iter_tree_files(
        root,
        budget=budget,
        predicate=lambda candidate: candidate == filename,
    )


def _iter_physical_blobs(
    root: Path,
    *,
    budget: InventoryBudget,
) -> Iterable[Path]:
    yield from _iter_tree_files(
        root,
        budget=budget,
        predicate=lambda candidate: candidate.endswith(".blob"),
    )


def _inventory_month(row: Mapping[str, Any]) -> str:
    for field in (
        "captured_at_utc",
        "captured_at_local",
        "fetched_at",
        "target_date",
    ):
        match = _MONTH_RE.match(str(row.get(field) or ""))
        if match and 1 <= int(match.group("month")) <= 12:
            return match.group(0)
    snapshot_id = str(row.get("snapshot_id") or "")
    if len(snapshot_id) >= 6 and snapshot_id[:6].isdigit():
        month = int(snapshot_id[4:6])
        if 1 <= month <= 12:
            return f"{snapshot_id[:4]}-{snapshot_id[4:6]}"
    return "unknown"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _resolve_legacy_payload_path(
    row: Mapping[str, Any],
    *,
    manifest_path: Path,
    snapshot_root: Path,
) -> Path:
    raw_path_text = str(row.get("raw_payload_path") or "").strip()
    if not raw_path_text:
        raise ForecastPayloadCASIntegrityError("market-local payload path missing")
    resolved_snapshot_root = snapshot_root.resolve()
    resolved_event_folder = manifest_path.parent.resolve()
    if not _is_relative_to(resolved_event_folder, resolved_snapshot_root):
        raise ForecastPayloadCASIntegrityError(
            "legacy_manifest_event_folder_outside_snapshot_root"
        )
    raw_path = Path(raw_path_text)
    candidate = raw_path if raw_path.is_absolute() else manifest_path.parent / raw_path
    if candidate.is_symlink():
        raise ForecastPayloadCASIntegrityError(
            f"legacy_payload_symlink_forbidden:{candidate}"
        )
    resolved = candidate.resolve()
    if not _is_relative_to(resolved, resolved_snapshot_root):
        raise ForecastPayloadCASIntegrityError(
            f"legacy_path_outside_snapshot_root:{resolved}"
        )
    if not _is_relative_to(resolved, resolved_event_folder):
        raise ForecastPayloadCASIntegrityError(
            f"legacy_path_outside_event_folder:{resolved}"
        )
    return resolved


def _bounded_read_payload(
    path: Path,
    *,
    budget: InventoryBudget,
    cursor: Mapping[str, Any],
) -> tuple[bytes, os.stat_result]:
    path = Path(path)
    read_cursor = {**dict(cursor), "payload_path": str(path)}
    budget.check_time(read_cursor)
    if path.is_symlink():
        raise ForecastPayloadCASIntegrityError(
            f"payload symlink forbidden: {path}"
        )
    if not path.is_file():
        raise ForecastPayloadCASIntegrityError(f"payload missing: {path}")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ForecastPayloadCASIntegrityError(f"payload is not a file: {path}")
    budget.preflight_payload(path, before.st_size, read_cursor)

    payload = bytearray()
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise ForecastPayloadCASIntegrityError(
                f"payload changed file type before read: {path}"
            )
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
        ) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ):
            raise ForecastPayloadCASIntegrityError(
                f"payload changed before read: {path}"
            )
        budget.preflight_payload(path, opened.st_size, read_cursor)
        remaining = opened.st_size
        while remaining:
            budget.check_time(read_cursor)
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ForecastPayloadCASIntegrityError(
                    f"payload ended before its declared file size: {path}"
                )
            payload.extend(chunk)
            budget.payload_bytes_read += len(chunk)
            remaining -= len(chunk)
            budget.check_time(read_cursor)
        after = os.fstat(handle.fileno())
    if (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise ForecastPayloadCASIntegrityError(f"payload changed during read: {path}")
    budget.check_time(read_cursor)
    return bytes(payload), after


def _expected_payload_bytes(row: Mapping[str, Any]) -> int | None:
    value = row.get("payload_bytes")
    if value in (None, ""):
        return None
    expected = int(value)
    if expected < 0:
        raise ForecastPayloadCASIntegrityError(
            "payload byte count cannot be negative"
        )
    return expected


def _read_legacy_payload_bytes(
    row: Mapping[str, Any],
    *,
    manifest_path: Path,
    snapshot_root: Path,
    budget: InventoryBudget,
    cursor: Mapping[str, Any],
) -> tuple[bytes, Path, os.stat_result]:
    path = _resolve_legacy_payload_path(
        row,
        manifest_path=manifest_path,
        snapshot_root=snapshot_root,
    )
    stored, path_stat = _bounded_read_payload(path, budget=budget, cursor=cursor)
    canonical = stored[:-1] if stored.endswith(b"\n") else stored
    expected_digest = validate_sha256(str(row.get("payload_hash") or ""))
    actual_digest = hashlib.sha256(canonical).hexdigest()
    if actual_digest != expected_digest:
        raise ForecastPayloadCASIntegrityError(
            f"market-local payload hash mismatch: {path}"
        )
    expected_bytes = _expected_payload_bytes(row)
    if expected_bytes is not None and len(canonical) != expected_bytes:
        raise ForecastPayloadCASIntegrityError(
            f"market-local payload byte-count mismatch: {path}"
        )
    return canonical, path, path_stat


def _read_shared_blob(
    path: Path,
    digest: str,
    *,
    expected_bytes: int | None,
    budget: InventoryBudget,
    cursor: Mapping[str, Any],
) -> bytes:
    payload, _path_stat = _bounded_read_payload(path, budget=budget, cursor=cursor)
    actual_digest = hashlib.sha256(payload).hexdigest()
    if actual_digest != digest:
        raise ForecastPayloadCASIntegrityError(
            f"shared payload hash mismatch: path={path} "
            f"expected={digest} actual={actual_digest}"
        )
    if expected_bytes is not None and len(payload) != expected_bytes:
        raise ForecastPayloadCASIntegrityError(
            f"shared payload byte-count mismatch: path={path} "
            f"expected={expected_bytes} actual={len(payload)}"
        )
    return payload


def _read_shared_reference_bytes(
    row: Mapping[str, Any],
    *,
    shared_cas: SharedForecastPayloadCAS,
    budget: InventoryBudget,
    cursor: Mapping[str, Any],
) -> tuple[bytes, str, dict[str, str]]:
    if row.get("schema_version") != "forecast_payload_manifest_v2":
        raise ForecastPayloadCASIntegrityError(
            "active shared reference requires forecast_payload_manifest_v2"
        )
    if row.get("payload_storage_scope") != SHARED_FORECAST_PAYLOAD_SCOPE:
        raise ForecastPayloadCASIntegrityError("shared payload storage scope mismatch")
    if row.get("payload_cas_kind") != SHARED_FORECAST_PAYLOAD_CAS_KIND:
        raise ForecastPayloadCASIntegrityError("shared payload CAS kind mismatch")
    if row.get("payload_hash_algorithm") != RAW_BYTES_HASH_ALGORITHM:
        raise ForecastPayloadCASIntegrityError(
            "shared payload hash algorithm mismatch"
        )
    if str(row.get("payload_encoding") or "").lower() != NBM_NBP_ENCODING:
        raise ForecastPayloadCASIntegrityError("shared payload encoding mismatch")
    if row.get("payload_media_type") != NBM_NBP_MEDIA_TYPE:
        raise ForecastPayloadCASIntegrityError("shared payload media type mismatch")
    if row.get("raw_payload_retained") is not True:
        raise ForecastPayloadCASIntegrityError(
            "shared payload row must retain its raw CAS reference"
        )

    digest = validate_sha256(str(row.get("payload_hash") or ""))
    expected_ref = shared_payload_ref(digest)
    if str(row.get("payload_ref") or "") != expected_ref:
        raise ForecastPayloadCASIntegrityError(
            "shared payload ref does not match its digest"
        )
    identity = validate_nbm_shared_manifest_identity(row)
    declared_path_text = str(row.get("raw_payload_path") or "").strip()
    declared_path = Path(declared_path_text)
    expected_path = shared_cas.path_for(digest)
    if (
        not declared_path_text
        or not declared_path.is_absolute()
        or declared_path.resolve() != expected_path.resolve()
    ):
        raise ForecastPayloadCASIntegrityError(
            "shared payload path does not match the inventoried CAS root"
        )
    payload = _read_shared_blob(
        expected_path,
        digest,
        expected_bytes=_expected_payload_bytes(row),
        budget=budget,
        cursor=cursor,
    )
    return payload, digest, identity


def _legacy_physical_blob_key(path: Path, path_stat: os.stat_result) -> str:
    if path_stat.st_ino:
        return f"inode:{path_stat.st_dev}:{path_stat.st_ino}"
    return f"path:{os.path.normcase(str(path.resolve()))}"


def _preferred_month(current: str, candidate: str) -> str:
    if current == "unknown":
        return candidate
    if candidate == "unknown":
        return current
    return min(current, candidate)


def _legacy_candidate(
    row: dict[str, Any],
    *,
    manifest_path: Path,
    line_number: int,
    snapshot_root: Path,
    shared_cas: SharedForecastPayloadCAS,
    budget: InventoryBudget,
) -> dict[str, Any]:
    base = {
        "candidate_kind": "legacy_migration_candidate",
        "manifest_path": str(manifest_path),
        "line_number": line_number,
        "snapshot_id": row.get("snapshot_id"),
        "event_slug": row.get("event_slug") or manifest_path.parent.name,
        "source": row.get("source"),
        "legacy_payload_hash": row.get("payload_hash"),
        "legacy_payload_path": row.get("raw_payload_path"),
        "inventory_month": _inventory_month(row),
    }
    issues: list[str] = []
    cursor = {
        "manifest_path": str(manifest_path),
        "line_number": line_number,
    }
    try:
        wrapper_bytes, legacy_path, legacy_stat = _read_legacy_payload_bytes(
            row,
            manifest_path=manifest_path,
            snapshot_root=snapshot_root,
            budget=budget,
            cursor=cursor,
        )
    except (ForecastPayloadCASIntegrityError, OSError, ValueError) as exc:
        return {
            **base,
            "status": "BLOCK",
            "issues": [f"legacy_hash_or_restore_failed:{type(exc).__name__}:{exc}"],
        }
    try:
        wrapper = json.loads(wrapper_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            **base,
            "status": "BLOCK",
            "issues": [f"legacy_payload_invalid_json:{type(exc).__name__}:{exc}"],
        }
    budget.check_time(cursor)
    if not isinstance(wrapper, dict):
        issues.append("legacy_payload_not_object")
        text = None
    else:
        text = wrapper.get("text")
    if not isinstance(text, str):
        issues.append("nbm_national_text_missing")
        body_bytes = b""
    else:
        body_bytes = text.encode("utf-8")
    digest = hashlib.sha256(body_bytes).hexdigest() if body_bytes else ""
    identity = {
        "station_id": (wrapper or {}).get("station_id") if isinstance(wrapper, dict) else None,
        "target_date": (wrapper or {}).get("target_date") if isinstance(wrapper, dict) else None,
    }
    replay_status = "NOT_RUN"
    if not issues:
        try:
            replayed = replay_nbp_shared_payload(
                body_bytes,
                identity,
                source_url=(wrapper or {}).get("source_url"),
                fetched_at=(wrapper or {}).get("fetched_at"),
            )
            if (
                replayed.get("station_id") != identity["station_id"]
                or replayed.get("target_date") != identity["target_date"]
            ):
                raise ValueError("replayed extraction identity changed")
            replay_status = "PASS"
        except Exception as exc:  # noqa: BLE001 - dry-run report retains exact failure
            issues.append(f"replay_proof_failed:{type(exc).__name__}:{exc}")
            replay_status = "BLOCK"
        budget.check_time(cursor)
    shared_path = shared_cas.path_for(digest) if digest else None
    shared_status = "ABSENT"
    if shared_path is not None and (shared_path.exists() or shared_path.is_symlink()):
        try:
            _read_shared_blob(
                shared_path,
                digest,
                expected_bytes=len(body_bytes),
                budget=budget,
                cursor=cursor,
            )
            shared_status = "VERIFIED"
        except (ForecastPayloadCASIntegrityError, OSError, ValueError) as exc:
            shared_status = "CORRUPT"
            issues.append(f"shared_blob_invalid:{exc}")
    budget.check_time(cursor)
    return {
        **base,
        "status": "PASS" if not issues else "BLOCK",
        "issues": issues,
        "legacy_payload_bytes": len(wrapper_bytes),
        "legacy_physical_bytes": legacy_stat.st_size,
        "legacy_payload_resolved_path": str(legacy_path),
        "legacy_physical_blob_key": _legacy_physical_blob_key(
            legacy_path,
            legacy_stat,
        ),
        "shared_payload_hash": digest or None,
        "shared_payload_bytes": len(body_bytes),
        "shared_payload_ref": shared_payload_ref(digest) if digest else None,
        "shared_payload_path": str(shared_path) if shared_path is not None else None,
        "shared_blob_status": shared_status,
        "extraction_identity": identity,
        "restore_hash_status": "PASS",
        "replay_status": replay_status,
        "would_copy": bool(shared_status == "ABSENT" and not issues),
        "would_rewrite_manifest": False,
        "would_delete_legacy_blob": False,
    }


def _shared_reference_candidate(
    row: dict[str, Any],
    *,
    manifest_path: Path,
    line_number: int,
    shared_cas: SharedForecastPayloadCAS,
    budget: InventoryBudget,
) -> dict[str, Any]:
    base = {
        "candidate_kind": "active_shared_reference",
        "manifest_path": str(manifest_path),
        "line_number": line_number,
        "snapshot_id": row.get("snapshot_id"),
        "event_slug": row.get("event_slug") or manifest_path.parent.name,
        "market_id": row.get("market_id"),
        "source": row.get("source"),
        "payload_hash": row.get("payload_hash"),
        "payload_ref": row.get("payload_ref"),
        "raw_payload_path": row.get("raw_payload_path"),
        "inventory_month": _inventory_month(row),
    }
    issues: list[str] = []
    payload_bytes = b""
    identity: dict[str, str] | None = None
    replay_status = "NOT_RUN"
    cursor = {
        "manifest_path": str(manifest_path),
        "line_number": line_number,
    }
    try:
        payload_bytes, _digest, identity = _read_shared_reference_bytes(
            row,
            shared_cas=shared_cas,
            budget=budget,
            cursor=cursor,
        )
        replayed = replay_nbp_shared_payload(
            payload_bytes,
            identity,
            source_url=row.get("source_url"),
            fetched_at=row.get("fetched_at"),
        )
        if (
            replayed.get("station_id") != identity["station_id"]
            or replayed.get("target_date") != identity["target_date"]
            or (
                row.get("target_date")
                and row.get("target_date") != identity["target_date"]
            )
        ):
            raise ForecastPayloadCASIntegrityError(
                "shared payload replay identity changed"
            )
        replay_status = "PASS"
    except (ForecastPayloadCASIntegrityError, OSError, TypeError, ValueError) as exc:
        issues.append(f"shared_reference_verification_failed:{type(exc).__name__}:{exc}")
        replay_status = "BLOCK"
    budget.check_time(cursor)

    return {
        **base,
        "status": "PASS" if not issues else "BLOCK",
        "issues": issues,
        "shared_payload_bytes": len(payload_bytes),
        "shared_blob_status": "VERIFIED" if not issues else "BLOCK",
        "extraction_identity": identity,
        "restore_hash_status": "PASS" if not issues else "BLOCK",
        "replay_status": replay_status,
        "would_copy": False,
        "would_rewrite_manifest": False,
        "would_delete_legacy_blob": False,
    }


def build_migration_dry_run(
    *,
    snapshot_root: str | Path = DEFAULT_SNAPSHOT_ROOT,
    shared_cas_root: str | Path = DEFAULT_SHARED_CAS_ROOT,
    month: str | None = None,
    max_manifest_count: int = DEFAULT_MAX_MANIFEST_COUNT,
    max_manifest_row_count: int = DEFAULT_MAX_MANIFEST_ROW_COUNT,
    max_payload_bytes_read: int = DEFAULT_MAX_PAYLOAD_BYTES_READ,
    max_elapsed_seconds: float = DEFAULT_MAX_ELAPSED_SECONDS,
    candidate_detail_limit: int = DEFAULT_CANDIDATE_DETAIL_LIMIT,
    max_physical_blob_count: int = DEFAULT_MAX_PHYSICAL_BLOB_COUNT,
    max_directory_count: int = DEFAULT_MAX_DIRECTORY_COUNT,
    max_tree_entry_count: int = DEFAULT_MAX_TREE_ENTRY_COUNT,
    max_jsonl_line_bytes: int = DEFAULT_MAX_JSONL_LINE_BYTES,
    max_manifest_bytes_read: int = DEFAULT_MAX_MANIFEST_BYTES_READ,
    max_single_payload_bytes: int = DEFAULT_MAX_SINGLE_PAYLOAD_BYTES,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    snapshot_root = Path(snapshot_root)
    shared_cas = SharedForecastPayloadCAS(shared_cas_root)
    month = str(month or "").strip() or None
    if month is not None and not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", month):
        raise ValueError("month must use YYYY-MM")
    max_manifest_count = max(1, int(max_manifest_count))
    max_manifest_row_count = max(1, int(max_manifest_row_count))
    max_payload_bytes_read = max(0, int(max_payload_bytes_read))
    max_elapsed_seconds = max(0.001, float(max_elapsed_seconds))
    candidate_detail_limit = max(0, int(candidate_detail_limit))
    max_physical_blob_count = max(1, int(max_physical_blob_count))
    max_directory_count = max(1, int(max_directory_count))
    max_tree_entry_count = max(1, int(max_tree_entry_count))
    max_jsonl_line_bytes = max(1, int(max_jsonl_line_bytes))
    max_manifest_bytes_read = max(1, int(max_manifest_bytes_read))
    max_single_payload_bytes = max(0, int(max_single_payload_bytes))

    started = monotonic_fn()
    budget = InventoryBudget(
        monotonic_fn=monotonic_fn,
        started=started,
        max_elapsed_seconds=max_elapsed_seconds,
        max_directory_count=max_directory_count,
        max_tree_entry_count=max_tree_entry_count,
        max_jsonl_line_bytes=max_jsonl_line_bytes,
        max_manifest_bytes_read=max_manifest_bytes_read,
        max_payload_bytes_read=max_payload_bytes_read,
        max_single_payload_bytes=max_single_payload_bytes,
    )
    candidates: list[dict[str, Any]] = []
    candidate_detail_omitted_count = 0
    manifest_error_count = 0
    active_shared_digests: set[str] = set()
    unique_payloads: dict[str, int] = {}
    month_state: dict[str, dict[str, Any]] = {}
    manifest_count = 0
    scanned_manifest_row_count = 0
    relevant_row_count = 0
    filtered_relevant_row_count = 0
    legacy_row_count = 0
    verified_legacy_row_count = 0
    blocked_legacy_row_count = 0
    shared_row_count = 0
    verified_shared_row_count = 0
    blocked_shared_row_count = 0
    logical_bytes = 0
    legacy_physical_blobs: dict[str, dict[str, Any]] = {}
    pending_verified_legacy_rows: list[dict[str, Any]] = []
    inconsistent_legacy_physical_blob_count = 0
    stop_reasons: list[str] = []
    resume_cursor: dict[str, Any] | None = None
    inventory_record_count = 0

    def retain_detail(candidate: dict[str, Any]) -> bool:
        nonlocal candidate_detail_omitted_count
        if len(candidates) < candidate_detail_limit:
            candidates.append(candidate)
            return True
        candidate_detail_omitted_count += 1
        return False

    def bucket_for(candidate_month: str) -> dict[str, Any]:
        return month_state.setdefault(candidate_month, {
            "candidate_row_count": 0,
            "verified_candidate_row_count": 0,
            "blocked_candidate_row_count": 0,
            "verified_legacy_stored_bytes": 0,
            "logical_shared_payload_bytes": 0,
            "unique_payloads": {},
        })

    def record_limit(exc: InventoryLimitReached) -> None:
        nonlocal resume_cursor
        if exc.reason not in stop_reasons:
            stop_reasons.append(exc.reason)
        if resume_cursor is None and exc.cursor is not None:
            resume_cursor = exc.cursor

    stop_manifest_scan = False
    current_manifest_path: Path | None = None
    try:
        manifest_paths = _iter_named_files(
            snapshot_root,
            "forecast_payloads.jsonl",
            budget=budget,
        )
        for manifest_path in manifest_paths:
            current_manifest_path = manifest_path
            manifest_cursor = {
                "manifest_path": str(manifest_path),
                "line_number": 1,
            }
            if manifest_count >= max_manifest_count:
                record_limit(InventoryLimitReached(
                    "max_manifest_count",
                    manifest_cursor,
                ))
                break
            budget.check_time(manifest_cursor)
            manifest_count += 1
            for line_number, row in _iter_jsonl(manifest_path, budget):
                row_cursor = {
                    "manifest_path": str(manifest_path),
                    "line_number": line_number,
                }
                if scanned_manifest_row_count >= max_manifest_row_count:
                    record_limit(InventoryLimitReached(
                        "max_manifest_row_count",
                        row_cursor,
                    ))
                    stop_manifest_scan = True
                    break
                budget.check_time(row_cursor)
                scanned_manifest_row_count += 1
                if row.get("_read_error"):
                    manifest_error_count += 1
                    inventory_record_count += 1
                    retain_detail({
                        "manifest_path": str(manifest_path),
                        "line_number": line_number,
                        "status": "BLOCK",
                        "issues": [row["_read_error"]],
                    })
                    continue
                is_shared = (
                    row.get("payload_storage_scope")
                    == SHARED_FORECAST_PAYLOAD_SCOPE
                )
                is_legacy = (
                    not is_shared
                    and row.get("source") == "nbm_probabilistic_tmax"
                )
                if not is_shared and not is_legacy:
                    continue
                relevant_row_count += 1
                candidate_month = _inventory_month(row)
                if month is not None and candidate_month != month:
                    filtered_relevant_row_count += 1
                    continue

                payload_bytes_before = budget.payload_bytes_read
                if is_shared:
                    candidate = _shared_reference_candidate(
                        row,
                        manifest_path=manifest_path,
                        line_number=line_number,
                        shared_cas=shared_cas,
                        budget=budget,
                    )
                    candidate["inventory_payload_bytes_read"] = (
                        budget.payload_bytes_read - payload_bytes_before
                    )
                    inventory_record_count += 1
                    shared_row_count += 1
                    retain_detail(candidate)
                    if candidate.get("status") == "PASS":
                        verified_shared_row_count += 1
                        active_shared_digests.add(
                            str(candidate.get("payload_hash") or "")
                        )
                    else:
                        blocked_shared_row_count += 1
                    continue

                candidate = _legacy_candidate(
                    row,
                    manifest_path=manifest_path,
                    line_number=line_number,
                    snapshot_root=snapshot_root,
                    shared_cas=shared_cas,
                    budget=budget,
                )
                candidate["inventory_payload_bytes_read"] = (
                    budget.payload_bytes_read - payload_bytes_before
                )
                inventory_record_count += 1
                legacy_row_count += 1
                candidate_retained = retain_detail(candidate)
                bucket = bucket_for(candidate_month)
                bucket["candidate_row_count"] += 1
                if candidate.get("status") == "PASS":
                    physical_key = str(
                        candidate.get("legacy_physical_blob_key") or ""
                    )
                    if not physical_key:
                        candidate["status"] = "BLOCK"
                        candidate["issues"].append(
                            "legacy_physical_identity_missing"
                        )
                        blocked_legacy_row_count += 1
                        bucket["blocked_candidate_row_count"] += 1
                        continue
                    pending_verified_legacy_rows.append({
                        "candidate": candidate if candidate_retained else None,
                        "month": candidate_month,
                        "digest": candidate.get("shared_payload_hash"),
                        "shared_bytes": int(
                            candidate.get("shared_payload_bytes") or 0
                        ),
                        "physical_key": physical_key,
                        "physical_bytes": int(
                            candidate.get("legacy_physical_bytes") or 0
                        ),
                        "legacy_payload_hash": str(
                            candidate.get("legacy_payload_hash") or ""
                        ),
                    })
                else:
                    blocked_legacy_row_count += 1
                    bucket["blocked_candidate_row_count"] += 1
            if stop_manifest_scan:
                break
    except InventoryLimitReached as exc:
        record_limit(exc)
        stop_manifest_scan = True
    except OSError as exc:
        record_limit(InventoryLimitReached("manifest_read_error", {
            "manifest_path": (
                str(current_manifest_path)
                if current_manifest_path is not None
                else None
            ),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }))
        stop_manifest_scan = True

    physical_identity_evidence: dict[str, set[tuple[int, str]]] = {}
    for row in pending_verified_legacy_rows:
        physical_identity_evidence.setdefault(
            str(row["physical_key"]),
            set(),
        ).add((
            int(row["physical_bytes"]),
            str(row["legacy_payload_hash"]),
        ))
    inconsistent_physical_keys = {
        key
        for key, evidence in physical_identity_evidence.items()
        if len(evidence) != 1
    }
    inconsistent_legacy_physical_blob_count = len(inconsistent_physical_keys)
    for row in pending_verified_legacy_rows:
        candidate_month = str(row["month"])
        bucket = bucket_for(candidate_month)
        physical_key = str(row["physical_key"])
        if physical_key in inconsistent_physical_keys:
            blocked_legacy_row_count += 1
            bucket["blocked_candidate_row_count"] += 1
            retained_candidate = row.get("candidate")
            if retained_candidate is not None:
                retained_candidate["status"] = "BLOCK"
                retained_candidate["issues"].append(
                    "legacy_physical_identity_changed_during_inventory"
                )
            continue

        verified_legacy_row_count += 1
        bucket["verified_candidate_row_count"] += 1
        digest = row.get("digest")
        shared_bytes = int(row["shared_bytes"])
        logical_bytes += shared_bytes
        bucket["logical_shared_payload_bytes"] += shared_bytes
        if digest:
            unique_payloads.setdefault(str(digest), shared_bytes)
            bucket["unique_payloads"].setdefault(str(digest), shared_bytes)
        known_blob = legacy_physical_blobs.get(physical_key)
        if known_blob is None:
            legacy_physical_blobs[physical_key] = {
                "bytes": int(row["physical_bytes"]),
                "month": candidate_month,
            }
        else:
            known_blob["month"] = _preferred_month(
                str(known_blob["month"]),
                candidate_month,
            )

    projected_physical_bytes = sum(unique_payloads.values())
    legacy_stored_bytes = sum(
        int(blob["bytes"])
        for blob in legacy_physical_blobs.values()
    )
    for blob in legacy_physical_blobs.values():
        bucket_for(str(blob["month"]))["verified_legacy_stored_bytes"] += int(
            blob["bytes"]
        )
    monthly_rows = []
    for candidate_month in sorted(month_state):
        bucket = month_state[candidate_month]
        monthly_physical = sum(bucket.pop("unique_payloads").values())
        monthly_rows.append({
            "month": candidate_month,
            **bucket,
            "projected_shared_physical_bytes": monthly_physical,
            "projected_reclaimable_legacy_bytes": max(
                0,
                bucket["verified_legacy_stored_bytes"] - monthly_physical,
            ),
        })

    physical_digests: set[str] = set()
    physical_blob_scan_count = 0
    invalid_physical_blob_name_count = 0
    physical_blob_scan_truncated = False
    try:
        budget.check_time({"shared_cas_root": str(shared_cas.root)})
        for path in _iter_physical_blobs(shared_cas.root, budget=budget):
            if physical_blob_scan_count >= max_physical_blob_count:
                raise InventoryLimitReached(
                    "max_physical_blob_count",
                    {"physical_blob_path": str(path)},
                )
            physical_blob_scan_count += 1
            try:
                physical_digests.add(validate_sha256(path.stem))
            except ForecastPayloadCASIntegrityError:
                invalid_physical_blob_name_count += 1
    except InventoryLimitReached as exc:
        physical_blob_scan_truncated = True
        record_limit(exc)
    unreferenced_within_scanned_scope = sorted(
        physical_digests - active_shared_digests
    )
    verified_active_shared_digests = sorted(active_shared_digests)
    terminal_elapsed_seconds = max(0.0, monotonic_fn() - started)
    if terminal_elapsed_seconds >= max_elapsed_seconds:
        record_limit(InventoryLimitReached(
            "max_elapsed_seconds",
            {"phase": "finalize"},
        ))
    bounds_status = "TRUNCATED" if stop_reasons else "COMPLETE"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "inventory_dry_run",
        "inventory_scope": "snapshot_forecast_payload_jsonl_only",
        "authoritative_for_garbage_collection": False,
        "mutation_performed": False,
        "manifest_rewrite_enabled": False,
        "garbage_collection_enabled": False,
        "deletion_enabled": False,
        "snapshot_root": str(snapshot_root),
        "shared_cas_root": str(shared_cas.root),
        "month_filter": month,
        "bounds": {
            "status": bounds_status,
            "stop_reasons": stop_reasons,
            "resume_cursor": resume_cursor,
            "configured": {
                "max_manifest_count": max_manifest_count,
                "max_manifest_row_count": max_manifest_row_count,
                "max_payload_bytes_read": max_payload_bytes_read,
                "max_elapsed_seconds": max_elapsed_seconds,
                "candidate_detail_limit": candidate_detail_limit,
                "max_physical_blob_count": max_physical_blob_count,
                "max_directory_count": max_directory_count,
                "max_tree_entry_count": max_tree_entry_count,
                "max_jsonl_line_bytes": max_jsonl_line_bytes,
                "max_manifest_bytes_read": max_manifest_bytes_read,
                "max_single_payload_bytes": max_single_payload_bytes,
            },
            "observed": {
                "manifest_count": manifest_count,
                "scanned_manifest_row_count": scanned_manifest_row_count,
                "manifest_bytes_read": budget.manifest_bytes_read,
                "payload_bytes_read": budget.payload_bytes_read,
                # Compatibility alias for v0.2 draft consumers. This is now
                # the exact observed count, not a preflight estimate.
                "payload_bytes_read_estimate": budget.payload_bytes_read,
                "directory_count": budget.directory_count,
                "tree_entry_count": budget.tree_entry_count,
                "candidate_detail_count": len(candidates),
                "candidate_detail_omitted_count": (
                    candidate_detail_omitted_count
                ),
                "physical_blob_scan_count": physical_blob_scan_count,
                "invalid_physical_blob_name_count": (
                    invalid_physical_blob_name_count
                ),
                "physical_blob_scan_truncated": physical_blob_scan_truncated,
                "elapsed_seconds": round(terminal_elapsed_seconds, 6),
            },
        },
        "summary": {
            "manifest_count": manifest_count,
            "scanned_manifest_row_count": scanned_manifest_row_count,
            "relevant_manifest_row_count": relevant_row_count,
            "filtered_relevant_row_count": filtered_relevant_row_count,
            "inventory_row_count": inventory_record_count,
            "candidate_row_count": legacy_row_count,
            "verified_candidate_row_count": verified_legacy_row_count,
            "blocked_candidate_row_count": blocked_legacy_row_count,
            "manifest_error_count": manifest_error_count,
            "shared_reference_row_count": shared_row_count,
            "verified_shared_reference_row_count": verified_shared_row_count,
            "blocked_shared_reference_row_count": blocked_shared_row_count,
            "unique_shared_payload_count": len(unique_payloads),
            "unique_legacy_physical_blob_count": len(legacy_physical_blobs),
            "inconsistent_legacy_physical_blob_count": (
                inconsistent_legacy_physical_blob_count
            ),
            "logical_referenced_bytes": logical_bytes,
            "verified_legacy_stored_bytes": legacy_stored_bytes,
            "projected_physical_bytes": projected_physical_bytes,
            "projected_avoided_bytes": max(0, logical_bytes - projected_physical_bytes),
            "projected_reclaimable_legacy_bytes": max(
                0,
                legacy_stored_bytes - projected_physical_bytes,
            ),
            "active_shared_reference_count": len(active_shared_digests),
            "physical_shared_blob_count": len(physical_digests),
            "unreferenced_within_scanned_scope_observation_count": len(
                unreferenced_within_scanned_scope
            ),
        },
        "legacy_duplicate_bytes_by_month": monthly_rows,
        "reachability": {
            "status": (
                "BOUNDED_PARTIAL_INVENTORY_ONLY"
                if bounds_status == "TRUNCATED"
                else "PARTIAL_INVENTORY_ONLY"
            ),
            "scope": "snapshot_forecast_payload_jsonl_only",
            "authoritative_for_garbage_collection": False,
            "verified_active_shared_digests": verified_active_shared_digests,
            "unreferenced_within_scanned_scope_observations": (
                unreferenced_within_scanned_scope
            ),
            "delete_candidates": [],
            "note": (
                "This scan is not global reachability. Unreferenced values are "
                "non-authoritative observations only; deletion remains disabled."
            ),
        },
        "candidates": candidates,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    bounds = payload.get("bounds") or {}
    lines = [
        "# Shared Forecast Payload CAS Migration Dry Run",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        "",
        (
            "This report is partial inventory only. It did not copy, rewrite, "
            "garbage-collect, or delete evidence."
        ),
        "",
        f"- Inventory scope: {payload.get('inventory_scope')}",
        f"- Month filter: {payload.get('month_filter') or 'all'}",
        f"- Bounded scan status: {bounds.get('status')}",
        (
            "- Stop reasons: "
            + (", ".join(bounds.get("stop_reasons") or []) or "none")
        ),
        (
            "- Authoritative for garbage collection: "
            f"{payload.get('authoritative_for_garbage_collection')}"
        ),
        f"- Candidate manifest rows: {summary.get('candidate_row_count', 0)}",
        f"- Verified candidates: {summary.get('verified_candidate_row_count', 0)}",
        f"- Blocked candidates: {summary.get('blocked_candidate_row_count', 0)}",
        (
            "- Verified active shared-reference rows: "
            f"{summary.get('verified_shared_reference_row_count', 0)}"
        ),
        (
            "- Blocked shared-reference rows: "
            f"{summary.get('blocked_shared_reference_row_count', 0)}"
        ),
        f"- Unique shared payloads: {summary.get('unique_shared_payload_count', 0)}",
        f"- Logical referenced bytes: {summary.get('logical_referenced_bytes', 0)}",
        f"- Projected physical bytes: {summary.get('projected_physical_bytes', 0)}",
        f"- Projected avoided bytes: {summary.get('projected_avoided_bytes', 0)}",
        (
            "- Verified legacy stored bytes: "
            f"{summary.get('verified_legacy_stored_bytes', 0)}"
        ),
        (
            "- Projected reclaimable legacy bytes: "
            f"{summary.get('projected_reclaimable_legacy_bytes', 0)}"
        ),
        (
            "- Unreferenced within scanned scope (non-authoritative, no deletion): "
            f"{summary.get('unreferenced_within_scanned_scope_observation_count', 0)}"
        ),
        "",
        "## Legacy Duplicate Bytes By Month",
        "",
        (
            "Only verified legacy rows contribute bytes. Repeated references "
            "to one physical legacy file count once, assigned to the earliest "
            "observed month. Monthly one-copy projections are not additive. "
            "A truncated bounded scan is partial evidence and must not be "
            "extrapolated silently."
        ),
        "",
        "| Month | Rows | Verified | Blocked | Legacy bytes | One-copy bytes | Reclaimable bytes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("legacy_duplicate_bytes_by_month") or []:
        lines.append(
            "| {month} | {candidate_row_count} | {verified_candidate_row_count} | "
            "{blocked_candidate_row_count} | {verified_legacy_stored_bytes} | "
            "{projected_shared_physical_bytes} | "
            "{projected_reclaimable_legacy_bytes} |".format(**row)
        )
    if not payload.get("legacy_duplicate_bytes_by_month"):
        lines.append("| - | 0 | 0 | 0 | 0 | 0 | 0 |")
    lines.append("")
    return "\n".join(lines)


def _write_text(path: str | Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory legacy NBM payloads for a future additive shared-CAS migration."
    )
    parser.add_argument("--snapshot-root", default=str(DEFAULT_SNAPSHOT_ROOT))
    parser.add_argument("--shared-cas-root", default=str(DEFAULT_SHARED_CAS_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--month", help="Limit verified legacy-byte inventory to YYYY-MM.")
    parser.add_argument(
        "--max-manifests",
        type=int,
        default=DEFAULT_MAX_MANIFEST_COUNT,
    )
    parser.add_argument(
        "--max-manifest-rows",
        type=int,
        default=DEFAULT_MAX_MANIFEST_ROW_COUNT,
    )
    parser.add_argument(
        "--max-payload-bytes-read",
        type=int,
        default=DEFAULT_MAX_PAYLOAD_BYTES_READ,
    )
    parser.add_argument(
        "--max-elapsed-seconds",
        type=float,
        default=DEFAULT_MAX_ELAPSED_SECONDS,
    )
    parser.add_argument(
        "--candidate-detail-limit",
        type=int,
        default=DEFAULT_CANDIDATE_DETAIL_LIMIT,
    )
    parser.add_argument(
        "--max-physical-blobs",
        type=int,
        default=DEFAULT_MAX_PHYSICAL_BLOB_COUNT,
    )
    parser.add_argument(
        "--max-directories",
        type=int,
        default=DEFAULT_MAX_DIRECTORY_COUNT,
    )
    parser.add_argument(
        "--max-tree-entries",
        type=int,
        default=DEFAULT_MAX_TREE_ENTRY_COUNT,
    )
    parser.add_argument(
        "--max-jsonl-line-bytes",
        type=int,
        default=DEFAULT_MAX_JSONL_LINE_BYTES,
    )
    parser.add_argument(
        "--max-manifest-bytes-read",
        type=int,
        default=DEFAULT_MAX_MANIFEST_BYTES_READ,
    )
    parser.add_argument(
        "--max-single-payload-bytes",
        type=int,
        default=DEFAULT_MAX_SINGLE_PAYLOAD_BYTES,
    )
    args = parser.parse_args(argv)
    payload = build_migration_dry_run(
        snapshot_root=args.snapshot_root,
        shared_cas_root=args.shared_cas_root,
        month=args.month,
        max_manifest_count=args.max_manifests,
        max_manifest_row_count=args.max_manifest_rows,
        max_payload_bytes_read=args.max_payload_bytes_read,
        max_elapsed_seconds=args.max_elapsed_seconds,
        candidate_detail_limit=args.candidate_detail_limit,
        max_physical_blob_count=args.max_physical_blobs,
        max_directory_count=args.max_directories,
        max_tree_entry_count=args.max_tree_entries,
        max_jsonl_line_bytes=args.max_jsonl_line_bytes,
        max_manifest_bytes_read=args.max_manifest_bytes_read,
        max_single_payload_bytes=args.max_single_payload_bytes,
    )
    _write_text(args.json_out, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _write_text(args.report_out, render_markdown(payload))
    bounds = payload["bounds"]
    complete = bounds["status"] == "COMPLETE"
    print(json.dumps({
        "status": "ok" if complete else "partial",
        "bounds_status": bounds["status"],
        "stop_reasons": bounds["stop_reasons"],
        "resume_cursor": bounds["resume_cursor"],
        "summary": payload["summary"],
    }, sort_keys=True))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
