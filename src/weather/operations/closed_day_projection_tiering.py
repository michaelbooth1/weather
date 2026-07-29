"""Manual, fail-closed tiering for finalized closed-day artifacts.

The command is deliberately dry-run-first:

* ``plan`` (also the default command) only reads snapshot folders and writes an
  operator-review manifest outside the snapshot tree.
* ``apply`` requires that manifest to have been externally edited with an
  operator approval bound to the immutable plan hash.
* ``warm-plan`` plans deterministic canonical ``order_books.jsonl`` gzip
  representation replacement outside the code-derived hot window.
* ``warm-apply`` requires the exact externally approved warm plan plus durable
  JSON and Markdown checkpoints before it removes a reviewed plain peer.
* ``rebuild-one`` reconstructs one ``order_books_long.csv`` outside the
  snapshot tree and proves byte parity with the retained projection.

Only ``order_books_long`` is eligible for projection cleanup, and only
``order_books.jsonl`` is eligible for canonical warm compression. Every other
family remains explicitly blocked until its reader contract is proven.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
import stat
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from weather.io import (
    TieredTextConflictError,
    TieredTextError,
    acquire_writer_lock,
    normalize_csv_row,
    open_tiered_text,
    release_writer_lock,
    resolve_tiered_text,
    sha256_file,
)
from weather.market.market_config import date_from_event_slug
from weather.market.market_microstructure_capture import order_book_level_rows
from weather.market.market_microstructure_constants import BOOK_LEVEL_COLUMNS
from weather.operations.cleanup_preflight import (
    CLEANUP_MANIFEST_SCHEMA_VERSION,
    build_cleanup_preflight,
)
from weather.operations.clob_order_book_tiering import (
    MIN_QUIET_SECONDS,
    source_is_quiet,
)
from weather.operations.closed_market_day_archive import (
    ELIGIBLE_FINALIZATION_STATES,
    _finalization_for_folder,
)
from weather.operations.closed_day_projection_registry import (
    ORDER_BOOK_LONG,
    ORDER_BOOK_LONG_GZIP,
    ORDER_BOOK_RAW,
    ORDER_BOOK_RAW_GZIP,
    PROJECTION_FAMILIES_BY_NAME,
    WARM_COMPRESSION_FAMILIES_BY_SOURCE_FILE,
    ProjectionFamilyContract,
    projection_family_registry,
    registry_hash,
    validate_projection_family_registry,
    validate_warm_compression_family_registry,
    warm_compression_family_registry,
    warm_compression_registry_hash,
)
from weather.operations.event_day_manifest import (
    build_event_day_manifest,
    event_day_manifest_path,
    manifest_content_hash,
    manifest_hash_valid,
    read_event_day_manifest,
    validate_deletion_candidates,
    validate_event_day_manifest,
    write_event_day_manifest,
)
from weather.operations.storage_classes import classification_payload
from weather.point_in_time_contract import (
    PRODUCTION_CONTIGUOUS_WINDOW_DAYS,
    PRODUCTION_MAX_LATEST_TARGET_AGE_DAYS,
)
from weather.schema_registry import schema_version


PLAN_SCHEMA_VERSION = schema_version("closed_day_projection_tiering_plan")
RECEIPT_SCHEMA_VERSION = schema_version(
    "closed_day_projection_tiering_receipt"
)
REBUILD_SCHEMA_VERSION = schema_version("closed_day_projection_rebuild")
WARM_PLAN_SCHEMA_VERSION = schema_version("closed_day_warm_tiering_plan")
WARM_RECEIPT_SCHEMA_VERSION = schema_version("closed_day_warm_tiering_receipt")
WRITER = "weather.operations.closed_day_projection_tiering"

RAW_TAPE_WRITER_LOCK = ".clob_raw_tape.writer.lock"

POINT_IN_TIME_CONTIGUOUS_WINDOW_DAYS = (
    PRODUCTION_CONTIGUOUS_WINDOW_DAYS
)
POINT_IN_TIME_MAX_LATEST_TARGET_AGE_DAYS = (
    PRODUCTION_MAX_LATEST_TARGET_AGE_DAYS
)
MIN_WARM_AGE_DAYS = (
    POINT_IN_TIME_CONTIGUOUS_WINDOW_DAYS
    + POINT_IN_TIME_MAX_LATEST_TARGET_AGE_DAYS
)
DEFAULT_WARM_RECOVERY_MARGIN_DAYS = 9
DEFAULT_HOT_WINDOW_DAYS = MIN_WARM_AGE_DAYS + DEFAULT_WARM_RECOVERY_MARGIN_DAYS


class ProjectionTieringError(RuntimeError):
    """A fail-closed tiering contract violation."""


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def _plan_hash_payload(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in plan.items()
        if key not in {"operator_review", "plan_hash"}
    }


def plan_content_hash(plan: dict[str, Any]) -> str:
    return _json_hash(_plan_hash_payload(plan))


def plan_hash_valid(plan: dict[str, Any]) -> bool:
    return bool(plan.get("plan_hash")) and plan["plan_hash"] == plan_content_hash(plan)


def _parse_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _assert_as_of_not_future(
    as_of: date,
    *,
    today_utc: date | None = None,
) -> None:
    current = today_utc or datetime.now(timezone.utc).date()
    if as_of > current:
        raise ProjectionTieringError(
            f"as_of_date cannot be in the future: {as_of} > {current}"
        )


def _parse_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ProjectionTieringError("captured_at_utc is required in every raw book row")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _safe_event_slug(value: str) -> str:
    slug = str(value or "").strip()
    if (
        not slug
        or slug in {".", ".."}
        or "/" in slug
        or "\\" in slug
        or Path(slug).name != slug
    ):
        raise ProjectionTieringError(f"invalid event slug: {value!r}")
    return slug


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return path != root


def _is_reparse_point(path: Path) -> bool:
    """Treat Windows junctions and other reparse points like symlinks."""

    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return path.is_symlink() or bool(attributes & reparse_flag)


def _assert_no_lexical_reparse_points(path: str | Path, label: str) -> None:
    """Check existing lexical components before any ``resolve()`` call."""

    lexical = Path(path).absolute()
    components = list(reversed(lexical.parents)) + [lexical]
    for component in components:
        if component.exists() and _is_reparse_point(component):
            raise ProjectionTieringError(
                f"{label} contains a symlink or reparse point: {component}"
            )


def _resolve_under_root(root: Path, relative: str | Path) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise ProjectionTieringError(f"path must be a normalized relative path: {relative}")
    lexical = root.joinpath(relative_path)
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.exists() and _is_reparse_point(current):
            raise ProjectionTieringError(
                f"symlink or reparse-point path component is not allowed: {current}"
            )
    resolved = lexical.resolve()
    if not _path_is_within(resolved, root):
        raise ProjectionTieringError(f"path escapes snapshots root: {relative}")
    return resolved


def data_root_for_snapshots(snapshots_root: str | Path) -> Path:
    """Infer the protected data/mirror root from its snapshots directory."""

    _assert_no_lexical_reparse_points(snapshots_root, "snapshots root")
    snapshots = Path(snapshots_root).resolve()
    return snapshots.parent if snapshots.name.lower() == "snapshots" else snapshots


def _assert_output_root_is_external(
    output_root: Path,
    protected_root: str | Path | Iterable[str | Path],
) -> None:
    _assert_no_lexical_reparse_points(output_root, "output root")
    output = output_root.resolve()
    if isinstance(protected_root, (str, os.PathLike)):
        protected_values = [protected_root]
    else:
        protected_values = list(protected_root)
    if not protected_values:
        raise ProjectionTieringError(
            "at least one explicit protected data/mirror root is required"
        )
    for value in protected_values:
        _assert_no_lexical_reparse_points(value, "protected data/mirror root")
        protected = Path(value).resolve()
        if (
            output == protected
            or _path_is_within(output, protected)
            or _path_is_within(protected, output)
        ):
            raise ProjectionTieringError(
                "output root must not overlap protected data/mirror root "
                f"{protected}: {output}"
            )
    if output.exists() and _is_reparse_point(output):
        raise ProjectionTieringError(
            f"output root must not be a symlink or reparse point: {output}"
        )


def _file_identity(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    if not path.exists() or not path.is_file() or _is_reparse_point(path):
        raise ProjectionTieringError(
            f"regular non-symlink, non-reparse-point file required: {path}"
        )
    stat = path.stat()
    row = {
        "path": path.relative_to(root).as_posix() if root else str(path),
        "bytes": int(stat.st_size),
        "sha256": sha256_file(path),
        "mtime_ns": int(stat.st_mtime_ns),
        "device": int(stat.st_dev),
        "inode": int(stat.st_ino),
    }
    return row


_IDENTITY_KEYS = ("path", "bytes", "sha256", "mtime_ns", "device", "inode")


def _assert_identity(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    changed = {
        key: {"expected": expected.get(key), "actual": actual.get(key)}
        for key in _IDENTITY_KEYS
        if actual.get(key) != expected.get(key)
    }
    if changed:
        raise ProjectionTieringError(f"{label} identity changed: {changed}")


def _manifest_records(manifest: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for family in manifest.get("artifact_families") or []:
        for record in family.get("files") or []:
            if isinstance(record, dict):
                yield record


def _manifest_record(manifest: dict[str, Any], relative_path: str) -> dict[str, Any] | None:
    normalized = Path(relative_path).as_posix()
    return next(
        (
            record
            for record in _manifest_records(manifest)
            if Path(str(record.get("path") or "")).as_posix() == normalized
        ),
        None,
    )


def _assert_manifest_record_current(
    manifest: dict[str, Any],
    relative_path: str,
    identity: dict[str, Any],
    *,
    expected_storage_class: str,
) -> dict[str, Any]:
    record = _manifest_record(manifest, relative_path)
    if record is None:
        raise ProjectionTieringError(
            f"{relative_path} is not finalized in event_day_manifest.json"
        )
    if int(record.get("bytes") or -1) != int(identity["bytes"]):
        raise ProjectionTieringError(f"{relative_path} manifest byte identity changed")
    if record.get("sha256") != identity["sha256"]:
        raise ProjectionTieringError(f"{relative_path} manifest hash identity changed")
    if record.get("storage_class") != expected_storage_class:
        raise ProjectionTieringError(
            f"{relative_path} must be {expected_storage_class}, got "
            f"{record.get('storage_class')}"
        )
    return record


def _writer_lock_paths(
    folder: Path,
    *,
    exclude: str | Path | None = None,
) -> list[Path]:
    candidates = [folder / ".snapshot.lock"]
    candidates.extend(path for path in folder.glob("*.lock") if path.is_file())
    candidates.extend(path for path in folder.glob(".*.lock") if path.is_file())
    excluded = Path(exclude).resolve() if exclude else None
    return sorted(
        {
            path
            for path in candidates
            if path.exists()
            and (excluded is None or path.resolve() != excluded)
        }
    )


def _acquire_raw_tape_writer_lock(
    folder: Path,
    *,
    action_id: str,
) -> dict[str, Any]:
    lock = acquire_writer_lock(
        folder / "clob_raw_tape",
        owner={
            "resource": "clob_raw_tape",
            "operation": "closed_day_projection_tiering",
            "action_id": action_id,
        },
        attempts=1,
        # Never age-delete an existing producer lock. Ambiguity retains data.
        stale_after_seconds=float("inf"),
        sleep_seconds=0.0,
    )
    if lock is None:
        raise ProjectionTieringError(
            "could not acquire the shared raw-tape writer lock"
        )
    return lock


def _finalization_proof(
    folder: Path,
    event_slug: str,
    *,
    ledger_root: Path,
) -> dict[str, Any]:
    finalization = dict(
        _finalization_for_folder(
            folder,
            event_slug,
            ledger_root=ledger_root,
        )
    )
    state = str(finalization.get("state") or "")
    if state not in ELIGIBLE_FINALIZATION_STATES:
        raise ProjectionTieringError(
            f"finalization state is not archive-eligible: {state or 'missing'}"
        )
    evidence: list[dict[str, Any]] = []
    for raw_path in finalization.get("evidence_paths") or []:
        _assert_no_lexical_reparse_points(
            raw_path,
            "settlement/finalization evidence",
        )
        path = Path(str(raw_path)).resolve()
        evidence.append(_file_identity(path))
    if state.startswith("settled_") and not evidence:
        raise ProjectionTieringError(
            "settled finalization requires hash-bound settlement evidence"
        )
    proof = {
        **finalization,
        "eligible_states": list(ELIGIBLE_FINALIZATION_STATES),
        "archive_contract": (
            "weather.operations.closed_market_day_archive."
            "ELIGIBLE_FINALIZATION_STATES"
        ),
        "evidence": evidence,
        "closed_unlabeled_contract": (
            {
                "status": "PASS",
                "basis": (
                    "target date is before as-of date, event-day manifest is "
                    "current PASS, and all event-folder writer locks are absent"
                ),
            }
            if state == "closed_unlabeled"
            else None
        ),
    }
    proof["proof_hash"] = _json_hash(proof)
    return proof


def _assert_finalization_proof_current(
    expected: dict[str, Any],
    *,
    folder: Path,
    event_slug: str,
    ledger_root: Path,
) -> dict[str, Any]:
    actual = _finalization_proof(
        folder,
        event_slug,
        ledger_root=ledger_root,
    )
    if actual != expected:
        raise ProjectionTieringError(
            "settlement/finalization evidence changed after planning"
        )
    return actual


def _validator_result(
    validator: Callable[..., dict[str, Any]],
    manifest: dict[str, Any],
    folder: Path,
    snapshots_root: Path,
) -> dict[str, Any]:
    return validator(
        manifest,
        folder,
        snapshots_root=snapshots_root,
        check_hashes=True,
        check_row_counts=True,
        fail_on_extra=True,
    )


def _validator_result_allowing_expected_extras(
    validator: Callable[..., dict[str, Any]],
    manifest: dict[str, Any],
    folder: Path,
    snapshots_root: Path,
    *,
    allowed_extras: Iterable[str],
) -> dict[str, Any]:
    """Validate everything while allowing only receipt-bound staged files."""

    validation = validator(
        manifest,
        folder,
        snapshots_root=snapshots_root,
        check_hashes=True,
        check_row_counts=True,
        fail_on_extra=False,
    )
    manifest_paths = {
        str(record.get("path") or "")
        for record in _manifest_records(manifest)
        if record.get("path")
    }
    current_paths = {
        path.relative_to(folder).as_posix()
        for path in folder.rglob("*")
        if path.is_file()
        and path.name != event_day_manifest_path(folder).name
        and not any(
            part.startswith(".")
            for part in path.relative_to(folder).parts
        )
    }
    actual_extras = current_paths - manifest_paths
    expected_extras = {str(value) for value in allowed_extras}
    extra_check = {
        "check": "receipt_bound_staged_extras",
        "status": (
            "PASS" if actual_extras == expected_extras else "BLOCK"
        ),
        "expected": sorted(expected_extras),
        "actual": sorted(actual_extras),
    }
    checks = [*(validation.get("checks") or []), extra_check]
    return {
        **validation,
        "status": (
            "PASS"
            if validation.get("status") == "PASS"
            and extra_check["status"] == "PASS"
            else "BLOCK"
        ),
        "checks": checks,
    }


def _blocked_folder(folder: Path, blockers: list[str]) -> dict[str, Any]:
    return {
        "event_slug": folder.name,
        "folder": str(folder),
        "status": "BLOCK",
        "blockers": blockers,
    }


def _plan_folder(
    folder: Path,
    *,
    snapshots_root: Path,
    as_of: date,
    ledger_root: Path,
    manifest_validator: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    blockers: list[str] = []
    target_date = date_from_event_slug(folder.name)
    if target_date is None:
        return _blocked_folder(folder, ["event_slug_has_no_target_date"]), None
    if target_date >= as_of:
        blockers.append("event_day_is_not_closed_before_as_of_date")

    lock_paths = _writer_lock_paths(folder)
    if lock_paths:
        blockers.append("event_folder_writer_lock_present")
    finalization_proof: dict[str, Any] | None = None
    if target_date < as_of and not lock_paths:
        try:
            finalization_proof = _finalization_proof(
                folder,
                folder.name,
                ledger_root=ledger_root,
            )
        except (OSError, ValueError, RuntimeError, ProjectionTieringError) as exc:
            blockers.append(f"finalization_proof_blocked:{exc}")

    manifest_path = event_day_manifest_path(folder)
    manifest = read_event_day_manifest(manifest_path)
    if manifest is None:
        blockers.append("event_day_manifest_missing_or_invalid_json")
    else:
        if not manifest_hash_valid(manifest):
            blockers.append("event_day_manifest_hash_invalid")
        if (manifest.get("validation") or {}).get("status") != "PASS":
            blockers.append("event_day_manifest_not_finalized_pass")
        manifest_target = str(
            (manifest.get("identity") or {}).get("target_date")
            or (manifest.get("identity") or {}).get("local_date")
            or ""
        )
        if manifest_target != target_date.isoformat():
            blockers.append("event_day_manifest_target_date_mismatch")
        validation = _validator_result(
            manifest_validator,
            manifest,
            folder,
            snapshots_root,
        )
        if validation.get("status") != "PASS":
            blockers.append("event_day_manifest_current_validation_blocked")
    source = folder / ORDER_BOOK_LONG
    gzip_path = folder / ORDER_BOOK_LONG_GZIP
    raw_plain = folder / ORDER_BOOK_RAW
    raw_gzip = folder / ORDER_BOOK_RAW_GZIP
    for path, reason in ((source, "order_books_long_csv_missing"),):
        if not path.exists():
            blockers.append(reason)
        elif not path.is_file() or _is_reparse_point(path):
            blockers.append(f"{reason}_or_not_regular_file")
    raw = None
    if not raw_plain.exists() and not raw_gzip.exists():
        blockers.append("canonical_order_books_tiered_text_missing")
    else:
        try:
            raw_resolution = resolve_tiered_text(raw_plain)
            raw = raw_resolution.selected_path
        except (TieredTextError, OSError, ValueError) as exc:
            blockers.append(f"canonical_order_books_tiered_text_blocked:{exc}")
    if raw is not None and (
        not raw.is_file() or _is_reparse_point(raw)
    ):
        blockers.append("canonical_order_books_tiered_text_not_regular_file")
    if gzip_path.exists() and (
        not gzip_path.is_file() or _is_reparse_point(gzip_path)
    ):
        blockers.append("order_books_long_gzip_not_regular_file")
    if (
        source.exists()
        and source.is_file()
        and not _is_reparse_point(source)
        and not source_is_quiet(source)
    ):
        blockers.append("order_books_long_recently_written")

    if (
        blockers
        or manifest is None
        or finalization_proof is None
        or raw is None
    ):
        return _blocked_folder(folder, blockers), None

    try:
        source_identity = _file_identity(source, root=snapshots_root)
        raw_identity = _file_identity(raw, root=snapshots_root)
        manifest_identity = _file_identity(manifest_path, root=snapshots_root)
        source_record = _assert_manifest_record_current(
            manifest,
            ORDER_BOOK_LONG,
            {**source_identity, "path": ORDER_BOOK_LONG},
            expected_storage_class="analysis_projection",
        )
        raw_record = _assert_manifest_record_current(
            manifest,
            raw.name,
            {**raw_identity, "path": raw.name},
            expected_storage_class="canonical_evidence",
        )
        deletion_validation = validate_deletion_candidates(
            manifest,
            [ORDER_BOOK_LONG],
        )
        if deletion_validation.get("status") != "PASS":
            raise ProjectionTieringError(
                "event_day_manifest deletion-candidate validation blocked"
            )
        gzip_identity = (
            _file_identity(gzip_path, root=snapshots_root)
            if gzip_path.exists()
            else None
        )
    except (OSError, ValueError, ProjectionTieringError) as exc:
        return _blocked_folder(folder, [str(exc)]), None

    rel_source = source.relative_to(snapshots_root).as_posix()
    classification = classification_payload(f"snapshots/{rel_source}")
    if classification.get("storage_class") != "analysis_projection":
        return _blocked_folder(
            folder,
            ["order_books_long_is_not_classified_as_analysis_projection"],
        ), None

    action_seed = {
        "event_slug": folder.name,
        "family": "order_books_long",
        "source_sha256": source_identity["sha256"],
        "raw_sha256": raw_identity["sha256"],
        "event_manifest_hash": manifest.get("manifest_hash"),
    }
    action_id = _json_hash(action_seed)[:24]
    action = {
        "action_id": action_id,
        "action": "gzip_and_remove_uncompressed_projection",
        "projection_family": "order_books_long",
        "deletion_reason": (
            "remove byte-identical uncompressed order_books_long.csv only after "
            "deterministic gzip verification; retain gzip and canonical tiered "
            "raw JSONL"
        ),
        "source": source_identity,
        "gzip": {
            "path": gzip_path.relative_to(snapshots_root).as_posix(),
            "preexisting": gzip_identity is not None,
            "identity": gzip_identity,
        },
        "canonical_rebuild_source": raw_identity,
        "event_manifest": {
            **manifest_identity,
            "manifest_hash": manifest.get("manifest_hash"),
            "validation_status": "PASS",
            "source_record_sha256": source_record.get("sha256"),
            "raw_record_sha256": raw_record.get("sha256"),
        },
        "closed_finalized_proof": {
            "target_date": target_date.isoformat(),
            "as_of_date": as_of.isoformat(),
            "closed_before_as_of": True,
            "event_manifest_current_validation": "PASS",
            "event_manifest_embedded_validation": "PASS",
            "writer_lock_paths": [],
            "writer_locks_absent": True,
            "source_quiescence": {
                "status": "PASS",
                "minimum_quiet_seconds": MIN_QUIET_SECONDS,
            },
            "finalization": finalization_proof,
        },
        "cleanup_candidate": {
            "path": rel_source,
            "data_path": f"snapshots/{rel_source}",
            "storage_class": classification["storage_class"],
            "retention_class": classification["retention_class"],
            "artifact_family": classification["artifact_family"],
            "deletion_reason": (
                "delete verified uncompressed order_books_long.csv projection "
                "while retaining order_books_long.csv.gz and canonical tiered "
                "order-books JSONL"
            ),
            "rebuild_source": (
                f"snapshots/{raw.relative_to(snapshots_root).as_posix()}"
            ),
            "bytes": source_identity["bytes"],
            "sha256": source_identity["sha256"],
        },
    }
    folder_row = {
        "event_slug": folder.name,
        "folder": str(folder),
        "status": "ELIGIBLE",
        "blockers": [],
        "action_id": action_id,
        "target_date": target_date.isoformat(),
    }
    return folder_row, action


def _event_folders(
    snapshots_root: Path,
    event_slugs: Iterable[str] | None,
) -> list[Path]:
    if event_slugs:
        return [
            _resolve_under_root(snapshots_root, _safe_event_slug(slug))
            for slug in event_slugs
        ]
    return [
        _resolve_under_root(snapshots_root, path.name)
        for path in sorted(snapshots_root.iterdir())
        if path.is_dir()
    ]


def warm_window_derivation(
    hot_window_days: int = DEFAULT_HOT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Return the code-bound hot-window derivation used by warm planning."""

    if type(hot_window_days) is not int:
        raise ProjectionTieringError("hot_window_days must be an integer")
    configured = hot_window_days
    if configured < MIN_WARM_AGE_DAYS:
        raise ProjectionTieringError(
            "hot_window_days cannot be shorter than the code-derived "
            f"minimum warm age of {MIN_WARM_AGE_DAYS} days"
        )
    return {
        "configured_hot_window_days": configured,
        "effective_warm_age_days": configured,
        "minimum_warm_age_days": MIN_WARM_AGE_DAYS,
        "default_hot_window_days": DEFAULT_HOT_WINDOW_DAYS,
        "default_recovery_margin_days": DEFAULT_WARM_RECOVERY_MARGIN_DAYS,
        "binding_consumer": "production_point_in_time_evaluation_window",
        "derivation": {
            "contiguous_window_days": POINT_IN_TIME_CONTIGUOUS_WINDOW_DAYS,
            "maximum_latest_target_age_days": (
                POINT_IN_TIME_MAX_LATEST_TARGET_AGE_DAYS
            ),
            "minimum_warm_age_formula": (
                "contiguous_window_days + maximum_latest_target_age_days"
            ),
            "minimum_warm_age_days": MIN_WARM_AGE_DAYS,
            "default_hot_window_formula": (
                "minimum_warm_age_days + default_recovery_margin_days"
            ),
            "default_hot_window_days": DEFAULT_HOT_WINDOW_DAYS,
            "code_evidence": [
                (
                    "weather.point_in_time_contract:"
                    "canonical_contiguous_14_day_window"
                ),
                (
                    "weather.reporting.validation.point_in_time_evaluation:"
                    "PRODUCTION_MAX_LATEST_TARGET_AGE_DAYS"
                ),
            ],
        },
    }


def _warm_folder_row(
    folder: Path,
    *,
    status: str,
    blockers: Iterable[str] = (),
    target_date: date | None = None,
    age_days: int | None = None,
    representation: dict[str, Any] | None = None,
    action_id: str | None = None,
) -> dict[str, Any]:
    return {
        "event_slug": folder.name,
        "folder": str(folder),
        "status": status,
        "blockers": list(blockers),
        "target_date": target_date.isoformat() if target_date else None,
        "age_days": age_days,
        "warm_family": "order_books_jsonl",
        "representation": representation,
        "action_id": action_id,
    }


def _plan_warm_folder(
    folder: Path,
    *,
    snapshots_root: Path,
    as_of: date,
    ledger_root: Path,
    window: dict[str, Any],
    manifest_validator: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    blockers: list[str] = []
    target_date = date_from_event_slug(folder.name)
    if target_date is None:
        return _warm_folder_row(
            folder,
            status="BLOCK",
            blockers=["event_slug_has_no_target_date"],
        ), None

    age_days = (as_of - target_date).days
    if target_date >= as_of:
        blockers.append("event_day_is_not_closed_before_as_of_date")
    if age_days < int(window["effective_warm_age_days"]):
        blockers.append("event_day_inside_hot_window")

    lock_paths = _writer_lock_paths(folder)
    if lock_paths:
        blockers.append("event_folder_writer_lock_present")
    finalization_proof: dict[str, Any] | None = None
    if target_date < as_of and not lock_paths:
        try:
            finalization_proof = _finalization_proof(
                folder,
                folder.name,
                ledger_root=ledger_root,
            )
        except (OSError, ValueError, RuntimeError, ProjectionTieringError) as exc:
            blockers.append(f"finalization_proof_blocked:{exc}")

    manifest_path = event_day_manifest_path(folder)
    manifest = read_event_day_manifest(manifest_path)
    if manifest is None:
        blockers.append("event_day_manifest_missing_or_invalid_json")
    else:
        if not manifest_hash_valid(manifest):
            blockers.append("event_day_manifest_hash_invalid")
        if (manifest.get("validation") or {}).get("status") != "PASS":
            blockers.append("event_day_manifest_not_finalized_pass")
        manifest_target = str(
            (manifest.get("identity") or {}).get("target_date")
            or (manifest.get("identity") or {}).get("local_date")
            or ""
        )
        if manifest_target != target_date.isoformat():
            blockers.append("event_day_manifest_target_date_mismatch")
        validation = _validator_result(
            manifest_validator,
            manifest,
            folder,
            snapshots_root,
        )
        if validation.get("status") != "PASS":
            blockers.append("event_day_manifest_current_validation_blocked")
        protection = manifest.get("protection") or {}
        if (
            protection.get("status") != "PASS"
            or (protection.get("backup") or {}).get("status") != "PASS"
            or (protection.get("restore") or {}).get("status") != "PASS"
        ):
            blockers.append(
                "event_day_manifest_backup_restore_protection_not_pass"
            )

    source = folder / ORDER_BOOK_RAW
    gzip_path = folder / ORDER_BOOK_RAW_GZIP
    existing_paths = [path for path in (source, gzip_path) if path.exists()]
    if not existing_paths:
        blockers.append("canonical_order_books_tiered_text_missing")
    for path in existing_paths:
        if not path.is_file() or _is_reparse_point(path):
            blockers.append(f"{path.name}_not_regular_file")
        elif not source_is_quiet(path):
            blockers.append(f"{path.name}_recently_written")

    representation: dict[str, Any] | None = None
    resolution = None
    if existing_paths and not any(
        blocker.endswith("_not_regular_file") for blocker in blockers
    ):
        try:
            resolution = resolve_tiered_text(source)
            representation = {
                "plain_path": source.relative_to(snapshots_root).as_posix(),
                "gzip_path": gzip_path.relative_to(snapshots_root).as_posix(),
                "plain_exists": source.exists(),
                "gzip_exists": gzip_path.exists(),
                "selected_path": resolution.selected_path.relative_to(
                    snapshots_root
                ).as_posix(),
                "selected_representation": resolution.representation,
                "transitional_pair": resolution.transitional_pair,
                "reader_boundary": "weather.io.resolve_tiered_text",
            }
            if resolution.compressed:
                representation["gzip_payload"] = _gzip_payload_identity(
                    resolution.selected_path
                )
        except TieredTextConflictError as exc:
            blockers.append(f"tiered_text_conflict:{exc}")
        except (TieredTextError, OSError, ValueError) as exc:
            blockers.append(f"tiered_text_resolution_blocked:{exc}")

    fatal_blockers = [
        blocker
        for blocker in blockers
        if blocker != "event_day_inside_hot_window"
    ]
    if (
        fatal_blockers
        or manifest is None
        or finalization_proof is None
        or resolution is None
        or representation is None
    ):
        return _warm_folder_row(
            folder,
            status="BLOCK",
            blockers=blockers,
            target_date=target_date,
            age_days=age_days,
            representation=representation,
        ), None

    selected = resolution.selected_path
    try:
        selected_identity = _file_identity(selected, root=snapshots_root)
        manifest_identity = _file_identity(
            manifest_path,
            root=snapshots_root,
        )
        selected_record = _assert_manifest_record_current(
            manifest,
            selected.name,
            {**selected_identity, "path": selected.name},
            expected_storage_class="canonical_evidence",
        )
        plain_identity = (
            _file_identity(source, root=snapshots_root)
            if source.exists()
            else None
        )
        gzip_identity = (
            _file_identity(gzip_path, root=snapshots_root)
            if gzip_path.exists()
            else None
        )
    except (OSError, ValueError, ProjectionTieringError) as exc:
        blockers.append(str(exc))
        return _warm_folder_row(
            folder,
            status="BLOCK",
            blockers=blockers,
            target_date=target_date,
            age_days=age_days,
            representation=representation,
        ), None

    representation["plain_identity"] = plain_identity
    representation["gzip_identity"] = gzip_identity
    if (
        resolution.transitional_pair
        and plain_identity is not None
        and gzip_identity is not None
    ):
        deterministic_identity = _deterministic_gzip_stream_identity(source)
        representation["deterministic_gzip_identity"] = (
            deterministic_identity
        )
        if (
            gzip_identity["bytes"] != deterministic_identity["bytes"]
            or gzip_identity["sha256"] != deterministic_identity["sha256"]
        ):
            blockers.append(
                "preexisting_gzip_is_not_the_deterministic_mtime_zero_"
                "representation"
            )
            return _warm_folder_row(
                folder,
                status="BLOCK",
                blockers=blockers,
                target_date=target_date,
                age_days=age_days,
                representation=representation,
            ), None
    closed_finalized_proof = {
        "target_date": target_date.isoformat(),
        "as_of_date": as_of.isoformat(),
        "age_days": age_days,
        "closed_before_as_of": True,
        "warm_window": window,
        "event_manifest_current_validation": "PASS",
        "event_manifest_embedded_validation": "PASS",
        "writer_lock_paths": [],
        "writer_locks_absent": True,
        "source_quiescence": {
            "status": "PASS",
            "minimum_quiet_seconds": MIN_QUIET_SECONDS,
            "paths": [
                path.relative_to(snapshots_root).as_posix()
                for path in existing_paths
            ],
        },
        "finalization": finalization_proof,
    }

    if "event_day_inside_hot_window" in blockers:
        return _warm_folder_row(
            folder,
            status="WAIT_HOT_WINDOW",
            blockers=blockers,
            target_date=target_date,
            age_days=age_days,
            representation=representation,
        ), None
    if resolution.compressed:
        return _warm_folder_row(
            folder,
            status="ALREADY_WARM",
            target_date=target_date,
            age_days=age_days,
            representation=representation,
        ), None
    if plain_identity is None:
        return _warm_folder_row(
            folder,
            status="BLOCK",
            blockers=["canonical_order_books_jsonl_missing"],
            target_date=target_date,
            age_days=age_days,
            representation=representation,
        ), None
    action_seed = {
        "event_slug": folder.name,
        "family": "order_books_jsonl",
        "source_sha256": plain_identity["sha256"],
        "event_manifest_hash": manifest.get("manifest_hash"),
        "hot_window_days": window["configured_hot_window_days"],
    }
    action_id = _json_hash(action_seed)[:24]
    source_relative = source.relative_to(snapshots_root).as_posix()
    classification = classification_payload(
        f"snapshots/{source_relative}"
    )
    if classification.get("storage_class") != "canonical_evidence":
        return _warm_folder_row(
            folder,
            status="BLOCK",
            blockers=[
                "order_books_jsonl_is_not_classified_as_canonical_evidence"
            ],
            target_date=target_date,
            age_days=age_days,
            representation=representation,
        ), None
    action = {
        "action_id": action_id,
        "action": (
            "remove_verified_identical_plain_peer"
            if resolution.transitional_pair
            else "deterministic_gzip_canonical_evidence"
        ),
        "warm_family": "order_books_jsonl",
        "source": plain_identity,
        "gzip": {
            "path": gzip_path.relative_to(snapshots_root).as_posix(),
            "preexisting": gzip_identity is not None,
            "identity": gzip_identity,
            "deterministic_mtime": 0,
            "verification": "decompressed_byte_sha256_and_length",
        },
        "reader_boundary": "weather.io.open_tiered_text",
        "source_retention": (
            "replace only the exact reviewed uncompressed representation "
            "after a byte-identical deterministic gzip representation and "
            "durable pre-unlink receipt are verified"
        ),
        "event_manifest": {
            **manifest_identity,
            "manifest_hash": manifest.get("manifest_hash"),
            "validation_status": "PASS",
            "validation": json.loads(
                json.dumps(manifest.get("validation") or {})
            ),
            "protection": json.loads(
                json.dumps(manifest.get("protection") or {})
            ),
            "source_record_sha256": selected_record.get("sha256"),
        },
        "closed_finalized_proof": closed_finalized_proof,
        "cleanup_candidate": {
            "path": source_relative,
            "data_path": f"snapshots/{source_relative}",
            "storage_class": classification["storage_class"],
            "retention_class": classification["retention_class"],
            "artifact_family": classification["artifact_family"],
            "deletion_reason": (
                "remove only the exact reviewed plain representation after "
                "retaining a byte-identical canonical gzip peer"
            ),
            "bytes": plain_identity["bytes"],
            "sha256": plain_identity["sha256"],
        },
    }
    return _warm_folder_row(
        folder,
        status=(
            "ELIGIBLE_IDENTICAL_TRANSITION"
            if resolution.transitional_pair
            else "ELIGIBLE"
        ),
        target_date=target_date,
        age_days=age_days,
        representation=representation,
        action_id=action_id,
    ), action


def build_warm_plan(
    snapshots_root: str | Path,
    *,
    as_of_date: str | date | datetime,
    hot_window_days: int = DEFAULT_HOT_WINDOW_DAYS,
    event_slugs: Iterable[str] | None = None,
    ledger_root: str | Path | None = None,
    generated_at_utc: str | None = None,
    manifest_validator: Callable[..., dict[str, Any]] | None = None,
    today_utc: date | None = None,
) -> dict[str, Any]:
    """Build a read-only canonical warm-compression plan."""

    _assert_no_lexical_reparse_points(snapshots_root, "snapshots root")
    root = Path(snapshots_root).resolve()
    if not root.exists() or not root.is_dir():
        raise ProjectionTieringError(f"snapshots root does not exist: {root}")
    as_of = _parse_date(as_of_date)
    _assert_as_of_not_future(as_of, today_utc=today_utc)
    window = warm_window_derivation(hot_window_days)
    ledger_value = ledger_root or data_root_for_snapshots(root) / "settlements"
    _assert_no_lexical_reparse_points(
        ledger_value,
        "settlement ledger root",
    )
    resolved_ledger_root = Path(ledger_value).resolve()
    registry_errors = validate_warm_compression_family_registry()
    validator = manifest_validator or validate_event_day_manifest

    folder_rows: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    if not registry_errors:
        for folder in _event_folders(root, event_slugs):
            folder_row, action = _plan_warm_folder(
                folder,
                snapshots_root=root,
                as_of=as_of,
                ledger_root=resolved_ledger_root,
                window=window,
                manifest_validator=validator,
            )
            folder_rows.append(folder_row)
            if action is not None:
                actions.append(action)

    blocked_count = sum(
        row.get("status") == "BLOCK" for row in folder_rows
    )
    if registry_errors or blocked_count:
        status = "BLOCK"
    elif actions:
        status = "PASS"
    else:
        status = "NOT_DONE"
    plan = {
        "schema_version": WARM_PLAN_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "writer": WRITER,
        "plan_kind": "canonical_warm_compression",
        "mode": "dry_run",
        "status": status,
        "snapshots_root": str(root),
        "data_root": str(data_root_for_snapshots(root)),
        "ledger_root": str(resolved_ledger_root),
        "as_of_date": as_of.isoformat(),
        "hot_window": window,
        "warm_compression_registry_hash": warm_compression_registry_hash(),
        "warm_compression_family_registry": (
            warm_compression_family_registry()
        ),
        "registry_errors": registry_errors,
        "summary": {
            "folder_count": len(folder_rows),
            "eligible_action_count": len(actions),
            "blocked_folder_count": blocked_count,
            "inside_hot_window_count": sum(
                row.get("status") == "WAIT_HOT_WINDOW"
                for row in folder_rows
            ),
            "already_warm_count": sum(
                row.get("status") == "ALREADY_WARM"
                for row in folder_rows
            ),
            "identical_transitional_pair_count": sum(
                row.get("status") == "ELIGIBLE_IDENTICAL_TRANSITION"
                for row in folder_rows
            ),
            "planned_source_bytes": sum(
                int(action["source"]["bytes"]) for action in actions
            ),
        },
        "folders": folder_rows,
        "actions": actions,
        "operator_review": {
            "approved": False,
            "approved_by": "",
            "approved_at_utc": "",
            "approved_plan_hash": "",
            "note": "",
        },
        "plan_hash": "",
    }
    plan["plan_hash"] = plan_content_hash(plan)
    return plan


def build_plan(
    snapshots_root: str | Path,
    *,
    as_of_date: str | date | datetime,
    event_slugs: Iterable[str] | None = None,
    ledger_root: str | Path | None = None,
    generated_at_utc: str | None = None,
    manifest_validator: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a read-only plan; no snapshot artifact is written or changed."""

    _assert_no_lexical_reparse_points(snapshots_root, "snapshots root")
    root = Path(snapshots_root).resolve()
    if not root.exists() or not root.is_dir():
        raise ProjectionTieringError(f"snapshots root does not exist: {root}")
    as_of = _parse_date(as_of_date)
    ledger_value = ledger_root or data_root_for_snapshots(root) / "settlements"
    _assert_no_lexical_reparse_points(
        ledger_value,
        "settlement ledger root",
    )
    resolved_ledger_root = Path(ledger_value).resolve()
    registry_errors = validate_projection_family_registry()
    validator = manifest_validator or validate_event_day_manifest

    folder_rows: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    if not registry_errors:
        for folder in _event_folders(root, event_slugs):
            folder_row, action = _plan_folder(
                folder,
                snapshots_root=root,
                as_of=as_of,
                ledger_root=resolved_ledger_root,
                manifest_validator=validator,
            )
            folder_rows.append(folder_row)
            if action is not None:
                actions.append(action)

    status = "BLOCK" if registry_errors else ("PASS" if actions else "NOT_DONE")
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "writer": WRITER,
        "mode": "dry_run",
        "status": status,
        "snapshots_root": str(root),
        "data_root": str(data_root_for_snapshots(root)),
        "ledger_root": str(resolved_ledger_root),
        "as_of_date": as_of.isoformat(),
        "registry_hash": registry_hash(),
        "projection_family_registry": projection_family_registry(),
        "registry_errors": registry_errors,
        "summary": {
            "folder_count": len(folder_rows),
            "eligible_action_count": len(actions),
            "blocked_folder_count": sum(
                row.get("status") == "BLOCK" for row in folder_rows
            ),
            "planned_source_bytes": sum(
                int(action["source"]["bytes"]) for action in actions
            ),
        },
        "folders": folder_rows,
        "actions": actions,
        "operator_review": {
            "approved": False,
            "approved_by": "",
            "approved_at_utc": "",
            "approved_plan_hash": "",
            "note": "",
        },
        "plan_hash": "",
    }
    plan["plan_hash"] = plan_content_hash(plan)
    return plan


def _operator_review_errors(plan: dict[str, Any]) -> list[str]:
    review = plan.get("operator_review") or {}
    errors: list[str] = []
    if review.get("approved") is not True:
        errors.append("operator_review.approved must be true")
    if not str(review.get("approved_by") or "").strip():
        errors.append("operator_review.approved_by is required")
    if not str(review.get("approved_at_utc") or "").strip():
        errors.append("operator_review.approved_at_utc is required")
    if not str(review.get("note") or "").strip():
        errors.append("operator_review.note is required")
    if review.get("approved_plan_hash") != plan.get("plan_hash"):
        errors.append("operator_review.approved_plan_hash must bind this plan")
    return errors


def _approved_plan_errors(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        errors.append("approved manifest has the wrong schema version")
    if plan.get("writer") != WRITER or plan.get("mode") != "dry_run":
        errors.append("approved manifest was not produced by the dry-run planner")
    if not plan_hash_valid(plan):
        errors.append("approved manifest plan_hash is invalid")
    if plan.get("registry_hash") != registry_hash():
        errors.append("approved manifest registry hash is stale")
    if plan.get("projection_family_registry") != projection_family_registry():
        errors.append("approved manifest registry payload is stale")
    if plan.get("status") != "PASS":
        errors.append("approved manifest status must be PASS")
    if not plan.get("actions"):
        errors.append("approved manifest contains no actions")
    try:
        snapshots_value = str(plan.get("snapshots_root") or "")
        if not snapshots_value:
            raise ProjectionTieringError("approved manifest snapshots_root is missing")
        _assert_no_lexical_reparse_points(
            snapshots_value,
            "approved snapshots root",
        )
        snapshots_root = Path(snapshots_value).resolve()
        if plan.get("data_root") != str(data_root_for_snapshots(snapshots_root)):
            errors.append("approved manifest data_root does not match snapshots root")
        ledger_value = str(plan.get("ledger_root") or "")
        if not ledger_value:
            raise ProjectionTieringError("approved manifest ledger_root is missing")
        _assert_no_lexical_reparse_points(
            ledger_value,
            "approved settlement ledger root",
        )
    except (OSError, ValueError, ProjectionTieringError) as exc:
        errors.append(f"approved manifest path boundary is invalid: {exc}")
    errors.extend(_operator_review_errors(plan))
    return errors


def _approved_warm_plan_errors(
    plan: dict[str, Any],
    *,
    today_utc: date | None = None,
) -> list[str]:
    errors: list[str] = []
    if plan.get("schema_version") != WARM_PLAN_SCHEMA_VERSION:
        errors.append("approved warm manifest has the wrong schema version")
    if (
        plan.get("writer") != WRITER
        or plan.get("mode") != "dry_run"
        or plan.get("plan_kind") != "canonical_warm_compression"
    ):
        errors.append(
            "approved warm manifest was not produced by the warm dry-run planner"
        )
    if not plan_hash_valid(plan):
        errors.append("approved warm manifest plan_hash is invalid")
    if (
        plan.get("warm_compression_registry_hash")
        != warm_compression_registry_hash()
    ):
        errors.append("approved warm manifest registry hash is stale")
    if (
        plan.get("warm_compression_family_registry")
        != warm_compression_family_registry()
    ):
        errors.append("approved warm manifest registry payload is stale")
    if plan.get("status") != "PASS":
        errors.append("approved warm manifest status must be PASS")
    actions = plan.get("actions") or []
    if not actions:
        errors.append("approved warm manifest contains no actions")
    action_ids = [str(action.get("action_id") or "") for action in actions]
    if any(not action_id for action_id in action_ids):
        errors.append("approved warm manifest action_id is required")
    if len(action_ids) != len(set(action_ids)):
        errors.append("approved warm manifest action_id values must be unique")
    for action in actions:
        if action.get("warm_family") != "order_books_jsonl":
            errors.append("only order_books_jsonl warm actions are permitted")
        if action.get("action") not in {
            "deterministic_gzip_canonical_evidence",
            "remove_verified_identical_plain_peer",
        }:
            errors.append("approved warm manifest contains an unknown action")
        approved_event_manifest = action.get("event_manifest") or {}
        approved_validation = (
            approved_event_manifest.get("validation") or {}
        )
        approved_protection = (
            approved_event_manifest.get("protection") or {}
        )
        if approved_validation.get("status") != "PASS":
            errors.append(
                "approved warm action lacks exact PASS manifest validation"
            )
        if (
            approved_protection.get("status") != "PASS"
            or (approved_protection.get("backup") or {}).get("status")
            != "PASS"
            or (approved_protection.get("restore") or {}).get("status")
            != "PASS"
        ):
            errors.append(
                "approved warm action lacks exact PASS backup/restore "
                "protection"
            )
    try:
        snapshots_value = str(plan.get("snapshots_root") or "")
        if not snapshots_value:
            raise ProjectionTieringError(
                "approved warm manifest snapshots_root is missing"
            )
        _assert_no_lexical_reparse_points(
            snapshots_value,
            "approved warm snapshots root",
        )
        snapshots_root = Path(snapshots_value).resolve()
        if plan.get("data_root") != str(
            data_root_for_snapshots(snapshots_root)
        ):
            errors.append(
                "approved warm manifest data_root does not match snapshots root"
            )
        ledger_value = str(plan.get("ledger_root") or "")
        if not ledger_value:
            raise ProjectionTieringError(
                "approved warm manifest ledger_root is missing"
            )
        _assert_no_lexical_reparse_points(
            ledger_value,
            "approved warm settlement ledger root",
        )
        as_of = _parse_date(plan.get("as_of_date"))
        _assert_as_of_not_future(as_of, today_utc=today_utc)
        configured_window = int(
            (plan.get("hot_window") or {}).get(
                "configured_hot_window_days"
            )
        )
        if plan.get("hot_window") != warm_window_derivation(
            configured_window
        ):
            errors.append("approved warm manifest hot-window proof is stale")
    except (OSError, TypeError, ValueError, ProjectionTieringError) as exc:
        errors.append(f"approved warm manifest boundary is invalid: {exc}")
    errors.extend(_operator_review_errors(plan))
    return errors


def _approved_manifest_identity_errors(
    plan: dict[str, Any],
    identity: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(identity, dict):
        return ["exact approved manifest file identity is required"]
    expected_keys = ("path", "bytes", "sha256", "mtime_ns", "device", "inode")
    if any(identity.get(key) in (None, "") for key in expected_keys):
        return ["approved manifest file identity is incomplete"]
    try:
        _assert_no_lexical_reparse_points(
            str(identity["path"]),
            "approved manifest",
        )
        loaded, current = _read_json_with_identity(Path(str(identity["path"])))
    except (OSError, ValueError, ProjectionTieringError) as exc:
        return [f"approved manifest file identity cannot be reverified: {exc}"]
    if loaded != plan:
        return ["approved manifest file payload does not match the apply plan"]
    changed = {
        key: {"expected": identity.get(key), "actual": current.get(key)}
        for key in expected_keys
        if identity.get(key) != current.get(key)
    }
    if changed:
        return [f"approved manifest file identity changed: {changed}"]
    return []


def _gzip_payload_identity(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    byte_count = 0
    line_count = 0
    with gzip.open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            byte_count += len(chunk)
            line_count += chunk.count(b"\n")
    return {
        "payload_bytes": byte_count,
        "payload_sha256": digest.hexdigest(),
        "payload_line_count": line_count,
    }


class _DigestWriter:
    """Minimal binary sink for hashing deterministic gzip output in memory."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self._bytes = 0

    def write(self, payload: bytes) -> int:
        self._digest.update(payload)
        self._bytes += len(payload)
        return len(payload)

    def flush(self) -> None:
        return None

    def tell(self) -> int:
        return self._bytes

    def identity(self) -> dict[str, Any]:
        return {
            "bytes": self._bytes,
            "sha256": self._digest.hexdigest(),
        }


def _deterministic_gzip_stream_identity(source: Path) -> dict[str, Any]:
    sink = _DigestWriter()
    with source.open("rb") as source_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=sink,
            mtime=0,
        ) as gzip_handle:
            shutil.copyfileobj(
                source_handle,
                gzip_handle,
                length=1024 * 1024,
            )
    return sink.identity()


def _write_deterministic_gzip(source: Path, temporary: Path) -> None:
    if temporary.exists():
        raise ProjectionTieringError(f"temporary gzip already exists: {temporary}")
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as raw_handle:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_handle,
                mtime=0,
            ) as gzip_handle:
                shutil.copyfileobj(source_handle, gzip_handle, length=1024 * 1024)
            raw_handle.flush()
            os.fsync(raw_handle.fileno())
    except BaseException:
        if (
            temporary.exists()
            and temporary.is_file()
            and not _is_reparse_point(temporary)
        ):
            temporary.unlink()
        raise


def _prepare_gzip(
    action: dict[str, Any],
    *,
    snapshots_root: Path,
    allow_adopt_existing: bool = False,
) -> dict[str, Any]:
    source = _resolve_under_root(snapshots_root, action["source"]["path"])
    gzip_path = _resolve_under_root(snapshots_root, action["gzip"]["path"])
    temporary = gzip_path.with_name(
        f".{gzip_path.name}.{action['action_id']}.tmp"
    )
    _write_deterministic_gzip(source, temporary)
    try:
        temporary_payload = _gzip_payload_identity(temporary)
        if (
            temporary_payload["payload_bytes"] != action["source"]["bytes"]
            or temporary_payload["payload_sha256"] != action["source"]["sha256"]
        ):
            raise ProjectionTieringError(
                "deterministic gzip payload is not byte-identical to source"
            )
        temporary_identity = _file_identity(temporary)
        created = False
        adopted_from_intent = False
        if gzip_path.exists():
            expected = action["gzip"].get("identity")
            if not action["gzip"].get("preexisting") or not expected:
                if not allow_adopt_existing:
                    raise ProjectionTieringError(
                        "gzip appeared after planning; refusing to overwrite"
                    )
                adopted_from_intent = True
            else:
                current = _file_identity(gzip_path, root=snapshots_root)
                _assert_identity(current, expected, "preexisting gzip")
            if sha256_file(gzip_path) != temporary_identity["sha256"]:
                raise ProjectionTieringError(
                    "preexisting gzip is not the deterministic representation"
                )
        else:
            if action["gzip"].get("preexisting"):
                raise ProjectionTieringError("planned gzip disappeared before apply")
            os.replace(temporary, gzip_path)
            created = True

        gzip_identity = _file_identity(gzip_path, root=snapshots_root)
        payload = _gzip_payload_identity(gzip_path)
        if (
            payload["payload_bytes"] != action["source"]["bytes"]
            or payload["payload_sha256"] != action["source"]["sha256"]
        ):
            raise ProjectionTieringError(
                "retained gzip failed decompressed byte-parity verification"
            )
        return {
            "status": "PASS",
            "created": created,
            "adopted_from_durable_intent": adopted_from_intent,
            "deterministic_mtime": 0,
            "compressed_identity": gzip_identity,
            **payload,
        }
    finally:
        if (
            temporary.exists()
            and temporary.is_file()
            and not _is_reparse_point(temporary)
        ):
            temporary.unlink()


def _assert_action_shape(action: dict[str, Any], snapshots_root: Path) -> dict[str, Path]:
    if action.get("projection_family") != "order_books_long":
        raise ProjectionTieringError("only order_books_long actions are permitted")
    source = _resolve_under_root(snapshots_root, action["source"]["path"])
    gzip_path = _resolve_under_root(snapshots_root, action["gzip"]["path"])
    raw = _resolve_under_root(
        snapshots_root,
        action["canonical_rebuild_source"]["path"],
    )
    manifest_path = _resolve_under_root(
        snapshots_root,
        action["event_manifest"]["path"],
    )
    if source.name != ORDER_BOOK_LONG:
        raise ProjectionTieringError("source must be exact order_books_long.csv")
    if gzip_path.name != ORDER_BOOK_LONG_GZIP:
        raise ProjectionTieringError("gzip target must be exact order_books_long.csv.gz")
    if raw.name not in {ORDER_BOOK_RAW, ORDER_BOOK_RAW_GZIP}:
        raise ProjectionTieringError(
            "canonical source must be exact order_books.jsonl or "
            "order_books.jsonl.gz"
        )
    if manifest_path.name != event_day_manifest_path(source.parent).name:
        raise ProjectionTieringError("event manifest path is not exact")
    if not (source.parent == gzip_path.parent == raw.parent == manifest_path.parent):
        raise ProjectionTieringError("action paths must share one event folder")
    source_relative = source.relative_to(snapshots_root).as_posix()
    raw_relative = raw.relative_to(snapshots_root).as_posix()
    cleanup_candidate = action.get("cleanup_candidate") or {}
    expected_classification = classification_payload(
        f"snapshots/{source_relative}"
    )
    expected_cleanup_fields = {
        "path": source_relative,
        "data_path": f"snapshots/{source_relative}",
        "storage_class": expected_classification["storage_class"],
        "retention_class": expected_classification["retention_class"],
        "artifact_family": expected_classification["artifact_family"],
        "rebuild_source": f"snapshots/{raw_relative}",
        "bytes": action["source"].get("bytes"),
        "sha256": action["source"].get("sha256"),
    }
    mismatches = {
        key: {
            "expected": expected,
            "actual": cleanup_candidate.get(key),
        }
        for key, expected in expected_cleanup_fields.items()
        if cleanup_candidate.get(key) != expected
    }
    if mismatches:
        raise ProjectionTieringError(
            f"cleanup candidate is not bound to exact source action: {mismatches}"
        )
    return {
        "source": source,
        "gzip": gzip_path,
        "raw": raw,
        "manifest": manifest_path,
    }


def _assert_action_current_before_compression(
    action: dict[str, Any],
    *,
    plan: dict[str, Any],
    snapshots_root: Path,
    manifest_validator: Callable[..., dict[str, Any]],
) -> dict[str, Path]:
    paths = _assert_action_shape(action, snapshots_root)
    if _writer_lock_paths(paths["source"].parent):
        raise ProjectionTieringError("event-folder writer lock appeared after planning")
    source_identity = _file_identity(paths["source"], root=snapshots_root)
    raw_identity = _file_identity(paths["raw"], root=snapshots_root)
    manifest_identity = _file_identity(paths["manifest"], root=snapshots_root)
    _assert_identity(source_identity, action["source"], "source")
    _assert_identity(raw_identity, action["canonical_rebuild_source"], "canonical raw")
    expected_manifest_identity = {
        key: action["event_manifest"].get(key) for key in _IDENTITY_KEYS
    }
    _assert_identity(
        manifest_identity,
        expected_manifest_identity,
        "event manifest",
    )

    manifest = read_event_day_manifest(paths["manifest"])
    if manifest is None or not manifest_hash_valid(manifest):
        raise ProjectionTieringError("event manifest is missing or hash-invalid")
    if manifest.get("manifest_hash") != action["event_manifest"].get("manifest_hash"):
        raise ProjectionTieringError("event manifest content changed after planning")
    if (manifest.get("validation") or {}).get("status") != "PASS":
        raise ProjectionTieringError("event manifest is no longer finalized PASS")
    validation = _validator_result(
        manifest_validator,
        manifest,
        paths["source"].parent,
        snapshots_root,
    )
    if validation.get("status") != "PASS":
        raise ProjectionTieringError("event manifest is no longer current")
    target_date = date_from_event_slug(paths["source"].parent.name)
    if target_date is None or target_date >= _parse_date(plan["as_of_date"]):
        raise ProjectionTieringError("event day is not closed before approved as-of date")
    _assert_finalization_proof_current(
        (action.get("closed_finalized_proof") or {}).get("finalization") or {},
        folder=paths["source"].parent,
        event_slug=paths["source"].parent.name,
        ledger_root=Path(plan["ledger_root"]).resolve(),
    )
    _assert_manifest_record_current(
        manifest,
        ORDER_BOOK_LONG,
        {**source_identity, "path": ORDER_BOOK_LONG},
        expected_storage_class="analysis_projection",
    )
    _assert_manifest_record_current(
        manifest,
        paths["raw"].name,
        {**raw_identity, "path": paths["raw"].name},
        expected_storage_class="canonical_evidence",
    )
    return paths


def _cleanup_manifest(
    plan: dict[str, Any],
    action: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": CLEANUP_MANIFEST_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "root": plan["snapshots_root"],
        "operator_review": dict(plan.get("operator_review") or {}),
        "candidates": [dict(action["cleanup_candidate"])],
    }


def _refresh_and_validate_event_manifest(
    folder: Path,
    *,
    snapshots_root: Path,
    manifest_validator: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    path = write_event_day_manifest(
        folder,
        snapshots_root=snapshots_root,
        incremental=False,
        generated_at_utc=utc_iso(),
    )
    manifest = read_event_day_manifest(path)
    if manifest is None or not manifest_hash_valid(manifest):
        raise ProjectionTieringError(
            "refreshed event_day_manifest.json is unreadable or hash-invalid"
        )
    validation = _validator_result(
        manifest_validator,
        manifest,
        folder,
        snapshots_root,
    )
    if validation.get("status") != "PASS":
        raise ProjectionTieringError(
            "refreshed event_day_manifest.json did not validate PASS"
        )
    refreshed_paths = {
        str(record.get("path") or "")
        for record in _manifest_records(manifest)
    }
    if ORDER_BOOK_LONG in refreshed_paths:
        raise ProjectionTieringError(
            "refreshed event manifest still lists removed source CSV"
        )
    raw_resolution = resolve_tiered_text(folder / ORDER_BOOK_RAW)
    raw_path = raw_resolution.selected_path
    if not {ORDER_BOOK_LONG_GZIP, raw_path.name}.issubset(refreshed_paths):
        raise ProjectionTieringError(
            "refreshed event manifest lacks retained gzip or canonical raw source"
        )
    if (
        (folder / ORDER_BOOK_LONG).exists()
        or not (folder / ORDER_BOOK_LONG_GZIP).is_file()
        or not raw_path.is_file()
    ):
        raise ProjectionTieringError(
            "refreshed event manifest does not match retained artifact state"
        )
    return {
        "status": "PASS",
        "manifest": _file_identity(path, root=snapshots_root),
        "manifest_hash": manifest.get("manifest_hash"),
        "validation": validation,
        "source_csv_absent": not (folder / ORDER_BOOK_LONG).exists(),
        "gzip_present": (folder / ORDER_BOOK_LONG_GZIP).is_file(),
        "canonical_raw_present": raw_path.is_file(),
        "canonical_raw_representation": raw_path.name,
    }


def _final_reverification(
    action: dict[str, Any],
    paths: dict[str, Path],
    gzip_proof: dict[str, Any],
    *,
    plan: dict[str, Any],
    snapshots_root: Path,
    held_lock: dict[str, Any],
) -> dict[str, Any]:
    held_lock_path = Path(str(held_lock.get("path") or ""))
    if _writer_lock_paths(paths["source"].parent, exclude=held_lock_path):
        raise ProjectionTieringError("event-folder writer lock appeared before unlink")
    source_identity = _file_identity(paths["source"], root=snapshots_root)
    raw_identity = _file_identity(paths["raw"], root=snapshots_root)
    gzip_identity = _file_identity(paths["gzip"], root=snapshots_root)
    manifest_identity = _file_identity(paths["manifest"], root=snapshots_root)
    _assert_identity(source_identity, action["source"], "source final reverify")
    _assert_identity(
        raw_identity,
        action["canonical_rebuild_source"],
        "canonical raw final reverify",
    )
    _assert_identity(
        gzip_identity,
        gzip_proof["compressed_identity"],
        "gzip final reverify",
    )
    _assert_identity(
        manifest_identity,
        {key: action["event_manifest"].get(key) for key in _IDENTITY_KEYS},
        "event manifest final reverify",
    )
    payload = _gzip_payload_identity(paths["gzip"])
    if (
        payload["payload_bytes"] != source_identity["bytes"]
        or payload["payload_sha256"] != source_identity["sha256"]
    ):
        raise ProjectionTieringError(
            "gzip payload parity changed immediately before unlink"
        )
    finalization = _assert_finalization_proof_current(
        (action.get("closed_finalized_proof") or {}).get("finalization") or {},
        folder=paths["source"].parent,
        event_slug=paths["source"].parent.name,
        ledger_root=Path(plan["ledger_root"]).resolve(),
    )
    return {
        "status": "PASS",
        "verified_at_utc": utc_iso(),
        "source": source_identity,
        "canonical_rebuild_source": raw_identity,
        "gzip": gzip_identity,
        "gzip_payload": payload,
        "event_manifest": manifest_identity,
        "competing_writer_locks_absent": True,
        "raw_tape_writer_lock_held": {
            "path": str(held_lock_path),
            "owner": held_lock.get("owner") or {},
        },
        "finalization": finalization,
    }


def _apply_one(
    plan: dict[str, Any],
    action: dict[str, Any],
    action_receipt: dict[str, Any],
    *,
    snapshots_root: Path,
    manifest_validator: Callable[..., dict[str, Any]],
    manifest_refresher: Callable[..., dict[str, Any]],
    persist_receipt: Callable[[], None],
) -> None:
    paths = _assert_action_current_before_compression(
        action,
        plan=plan,
        snapshots_root=snapshots_root,
        manifest_validator=manifest_validator,
    )
    action_receipt["pre_apply_validation"] = {
        "status": "PASS",
        "closed_finalized_proof": action["closed_finalized_proof"],
    }

    cleanup_manifest = _cleanup_manifest(plan, action)
    preflight = build_cleanup_preflight(
        cleanup_manifest,
        root=snapshots_root,
    )
    action_receipt["cleanup_preflight"] = preflight
    if preflight.get("status") != "PASS" or preflight.get("delete_permission") is not True:
        raise ProjectionTieringError("cleanup_preflight denied deletion")
    persist_receipt()

    # No compression or other snapshot-tree mutation occurs before the shared
    # cleanup preflight has granted permission for the exact source identity.
    held_lock = _acquire_raw_tape_writer_lock(
        paths["source"].parent,
        action_id=str(action["action_id"]),
    )
    action_receipt["raw_tape_writer_lock"] = {
        "status": "HELD",
        "path": held_lock.get("path"),
        "owner": held_lock.get("owner") or {},
    }
    persist_receipt()
    try:
        if not source_is_quiet(paths["source"]):
            raise ProjectionTieringError(
                "order_books_long is no longer writer-quiescent for the "
                f"required {MIN_QUIET_SECONDS:g} seconds"
            )
        action_receipt["source_quiescence"] = {
            "status": "PASS",
            "minimum_quiet_seconds": MIN_QUIET_SECONDS,
            "checked_under_raw_tape_writer_lock": True,
        }
        gzip_proof = _prepare_gzip(action, snapshots_root=snapshots_root)
        action_receipt["compression"] = gzip_proof
        persist_receipt()

        final_reverification = _final_reverification(
            action,
            paths,
            gzip_proof,
            plan=plan,
            snapshots_root=snapshots_root,
            held_lock=held_lock,
        )
        action_receipt["final_reverification"] = final_reverification
        action_receipt["deletion"] = {
            "status": "AUTHORIZED_PENDING",
            "path": action["source"]["path"],
            "exact_file_only": True,
            "source_identity": final_reverification["source"],
            "gzip_identity": final_reverification["gzip"],
            "canonical_raw_identity": final_reverification[
                "canonical_rebuild_source"
            ],
        }
        action_receipt["event_day_manifest_refresh_required"] = True
        action_receipt["status"] = "UNLINK_PENDING"
        # This write-ahead action ledger makes a crash immediately after unlink
        # distinguishable from an unreviewed or unstarted action.
        persist_receipt()

        # The receipt write is necessarily between authorization and unlink.
        # Re-pin every identity, finalization proof, and competing-lock check
        # once more after that durable checkpoint, while the shared writer lock
        # remains held, so the next operation is the exact-file unlink.
        immediate_reverification = _final_reverification(
            action,
            paths,
            gzip_proof,
            plan=plan,
            snapshots_root=snapshots_root,
            held_lock=held_lock,
        )
        action_receipt["immediate_pre_unlink_reverification"] = (
            immediate_reverification
        )

        # Exact-file deletion only.  No glob, recursion, directory removal, or
        # missing_ok semantics are permitted here.
        paths["source"].unlink()
        if paths["source"].exists():
            raise ProjectionTieringError("exact source unlink did not remove the file")
        if not paths["gzip"].is_file() or not paths["raw"].is_file():
            raise ProjectionTieringError(
                "retained gzip or canonical raw source disappeared after unlink"
            )
        action_receipt["deletion"] = {
            "status": "UNLINKED_MANIFEST_REFRESH_PENDING",
            "path": action["source"]["path"],
            "exact_file_only": True,
            "source_absent": True,
            "gzip_retained": True,
            "canonical_raw_retained": True,
        }
        action_receipt["status"] = "MANIFEST_REFRESH_PENDING"
        persist_receipt()

        refresh = manifest_refresher(
            paths["source"].parent,
            snapshots_root=snapshots_root,
            manifest_validator=manifest_validator,
        )
        if refresh.get("status") != "PASS":
            raise ProjectionTieringError(
                "event_day_manifest refresh did not return PASS"
            )
        action_receipt["event_day_manifest_refresh"] = refresh
        action_receipt["deletion"]["status"] = "PASS"
        action_receipt["event_day_manifest_refresh_required"] = False
        action_receipt["status"] = "APPLIED"
        persist_receipt()
    finally:
        release_writer_lock(held_lock)
        action_receipt["raw_tape_writer_lock"]["status"] = "RELEASED"


def _update_apply_summary(
    receipt: dict[str, Any],
    *,
    planned: int,
) -> None:
    actions = receipt.get("actions") or []
    receipt["summary"] = {
        "planned": planned,
        "attempted": len(actions),
        "applied": sum(row.get("status") == "APPLIED" for row in actions),
        "failed": sum(row.get("status") == "BLOCK" for row in actions),
        "not_attempted": planned - len(actions),
        "gzip_retained": sum(row.get("status") == "APPLIED" for row in actions),
        "uncompressed_sources_removed": sum(
            row.get("status") == "APPLIED" for row in actions
        ),
    }


def apply_approved_plan(
    plan: dict[str, Any],
    *,
    generated_at_utc: str | None = None,
    manifest_validator: Callable[..., dict[str, Any]] | None = None,
    manifest_refresher: Callable[..., dict[str, Any]] | None = None,
    persist_receipt: Callable[[dict[str, Any]], None] | None = None,
    approved_manifest_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply an externally approved plan, stopping on the first failure."""

    errors = _approved_plan_errors(plan)
    errors.extend(
        _approved_manifest_identity_errors(
            plan,
            approved_manifest_identity,
        )
    )
    if not errors and persist_receipt is None:
        errors.append(
            "durable JSON+Markdown receipt persistence is required before apply"
        )
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "writer": WRITER,
        "mode": "apply",
        "status": "BLOCK" if errors else "RUNNING",
        "plan_hash": plan.get("plan_hash"),
        "snapshots_root": plan.get("snapshots_root"),
        "approved_manifest_identity": approved_manifest_identity,
        "operator_review": dict(plan.get("operator_review") or {}),
        "approval_errors": errors,
        "stop_on_first_failure": True,
        "actions": [],
    }
    planned_count = len(plan.get("actions") or [])
    _update_apply_summary(receipt, planned=planned_count)

    def _persist() -> None:
        if persist_receipt is not None:
            persist_receipt(receipt)

    # Persist the approved-plan identity and zero-action starting state before
    # any candidate validation, compression, or unlink attempt.
    _persist()
    if errors:
        _persist()
        return receipt

    snapshots_root = Path(plan["snapshots_root"]).resolve()
    validator = manifest_validator or validate_event_day_manifest
    refresher = manifest_refresher or _refresh_and_validate_event_manifest
    actions = list(plan.get("actions") or [])
    for index, action in enumerate(actions):
        action_receipt: dict[str, Any] = {
            "action_id": action.get("action_id"),
            "projection_family": action.get("projection_family"),
            "source": action.get("source"),
            "status": "RUNNING",
        }
        receipt["actions"].append(action_receipt)
        _update_apply_summary(receipt, planned=len(actions))
        _persist()
        try:
            _apply_one(
                plan,
                action,
                action_receipt,
                snapshots_root=snapshots_root,
                manifest_validator=validator,
                manifest_refresher=refresher,
                persist_receipt=_persist,
            )
        except Exception as exc:  # noqa: BLE001 - receipt first, then fail closed
            action_receipt["status"] = "BLOCK"
            action_receipt["failure"] = {
                "type": type(exc).__name__,
                "detail": str(exc),
            }
            try:
                paths = _assert_action_shape(action, snapshots_root)
                action_receipt["failure_state"] = {
                    "source_exists": paths["source"].exists(),
                    "gzip_exists": paths["gzip"].exists(),
                    "canonical_raw_exists": paths["raw"].exists(),
                }
            except Exception:
                action_receipt["failure_state"] = {
                    "source_exists": None,
                    "gzip_exists": None,
                    "canonical_raw_exists": None,
                }
            receipt["status"] = "BLOCK"
            receipt["stopped_at_action_index"] = index
            _update_apply_summary(receipt, planned=len(actions))
            _persist()
            break
        _update_apply_summary(receipt, planned=len(actions))
        _persist()
    else:
        receipt["status"] = "PASS"

    _update_apply_summary(receipt, planned=len(actions))
    _persist()
    return receipt


def _assert_warm_action_shape(
    action: dict[str, Any],
    snapshots_root: Path,
) -> dict[str, Path]:
    if action.get("warm_family") != "order_books_jsonl":
        raise ProjectionTieringError(
            "only order_books_jsonl warm actions are permitted"
        )
    source = _resolve_under_root(
        snapshots_root,
        action["source"]["path"],
    )
    gzip_path = _resolve_under_root(
        snapshots_root,
        action["gzip"]["path"],
    )
    manifest_path = _resolve_under_root(
        snapshots_root,
        action["event_manifest"]["path"],
    )
    if source.name != ORDER_BOOK_RAW:
        raise ProjectionTieringError(
            "warm source must be exact order_books.jsonl"
        )
    if gzip_path.name != ORDER_BOOK_RAW_GZIP:
        raise ProjectionTieringError(
            "warm target must be exact order_books.jsonl.gz"
        )
    if manifest_path.name != event_day_manifest_path(source.parent).name:
        raise ProjectionTieringError("warm event manifest path is not exact")
    if not (
        source.parent == gzip_path.parent == manifest_path.parent
    ):
        raise ProjectionTieringError(
            "warm action paths must share one event folder"
        )
    source_relative = source.relative_to(snapshots_root).as_posix()
    cleanup_candidate = action.get("cleanup_candidate") or {}
    classification = classification_payload(
        f"snapshots/{source_relative}"
    )
    expected_fields = {
        "path": source_relative,
        "data_path": f"snapshots/{source_relative}",
        "storage_class": classification["storage_class"],
        "retention_class": classification["retention_class"],
        "artifact_family": classification["artifact_family"],
        "bytes": action["source"].get("bytes"),
        "sha256": action["source"].get("sha256"),
    }
    mismatches = {
        key: {"expected": expected, "actual": cleanup_candidate.get(key)}
        for key, expected in expected_fields.items()
        if cleanup_candidate.get(key) != expected
    }
    if classification.get("storage_class") != "canonical_evidence":
        mismatches["storage_class_contract"] = {
            "expected": "canonical_evidence",
            "actual": classification.get("storage_class"),
        }
    if mismatches:
        raise ProjectionTieringError(
            "warm cleanup candidate is not bound to the exact canonical "
            f"source action: {mismatches}"
        )
    return {
        "source": source,
        "gzip": gzip_path,
        "manifest": manifest_path,
    }


def _assert_warm_action_current(
    action: dict[str, Any],
    *,
    plan: dict[str, Any],
    snapshots_root: Path,
    manifest_validator: Callable[..., dict[str, Any]],
    resume_compression: dict[str, Any] | None = None,
    compression_intent: dict[str, Any] | None = None,
) -> dict[str, Path]:
    paths = _assert_warm_action_shape(action, snapshots_root)
    if _writer_lock_paths(paths["source"].parent):
        raise ProjectionTieringError(
            "event-folder writer lock appeared after warm planning"
        )
    source_identity = _file_identity(
        paths["source"],
        root=snapshots_root,
    )
    _assert_identity(source_identity, action["source"], "warm source")
    if not source_is_quiet(paths["source"]):
        raise ProjectionTieringError(
            "order_books.jsonl is no longer writer-quiescent for the "
            f"required {MIN_QUIET_SECONDS:g} seconds"
        )

    allow_staged_gzip_extra = False
    if paths["gzip"].exists():
        current_gzip = _file_identity(
            paths["gzip"],
            root=snapshots_root,
        )
        expected_gzip = action["gzip"].get("identity")
        if action["gzip"].get("preexisting") and expected_gzip:
            _assert_identity(
                current_gzip,
                expected_gzip,
                "preexisting warm gzip",
            )
        else:
            resumed_identity = (
                (resume_compression or {}).get("compressed_identity")
            )
            if not isinstance(resumed_identity, dict):
                if not _warm_compression_intent_matches(
                    action,
                    compression_intent,
                ):
                    raise ProjectionTieringError(
                        "warm gzip appeared after planning without a durable "
                        "compression checkpoint or exact compression intent"
                    )
                allow_staged_gzip_extra = True
            else:
                _assert_identity(
                    current_gzip,
                    resumed_identity,
                    "resumed warm gzip",
                )
                allow_staged_gzip_extra = True
    elif action["gzip"].get("preexisting"):
        raise ProjectionTieringError(
            "planned preexisting warm gzip disappeared before apply"
        )

    resolution = resolve_tiered_text(paths["source"])
    if resolution.selected_path != paths["source"]:
        raise ProjectionTieringError(
            "plain warm source must remain selected until exact unlink"
        )
    manifest_identity = _file_identity(
        paths["manifest"],
        root=snapshots_root,
    )
    _assert_identity(
        manifest_identity,
        {
            key: action["event_manifest"].get(key)
            for key in _IDENTITY_KEYS
        },
        "warm event manifest",
    )
    manifest = read_event_day_manifest(paths["manifest"])
    if manifest is None or not manifest_hash_valid(manifest):
        raise ProjectionTieringError(
            "warm event manifest is missing or hash-invalid"
        )
    if (
        manifest.get("manifest_hash")
        != action["event_manifest"].get("manifest_hash")
    ):
        raise ProjectionTieringError(
            "warm event manifest content changed after planning"
        )
    if (manifest.get("validation") or {}).get("status") != "PASS":
        raise ProjectionTieringError(
            "warm event manifest is no longer finalized PASS"
        )
    if (
        manifest.get("validation")
        != action["event_manifest"].get("validation")
        or manifest.get("protection")
        != action["event_manifest"].get("protection")
    ):
        raise ProjectionTieringError(
            "warm event manifest validation or protection proof changed "
            "after planning"
        )
    if allow_staged_gzip_extra:
        validation = _validator_result_allowing_expected_extras(
            manifest_validator,
            manifest,
            paths["source"].parent,
            snapshots_root,
            allowed_extras=[ORDER_BOOK_RAW_GZIP],
        )
    else:
        validation = _validator_result(
            manifest_validator,
            manifest,
            paths["source"].parent,
            snapshots_root,
        )
    if validation.get("status") != "PASS":
        raise ProjectionTieringError(
            "warm event manifest is no longer current"
        )
    _assert_manifest_record_current(
        manifest,
        ORDER_BOOK_RAW,
        {**source_identity, "path": ORDER_BOOK_RAW},
        expected_storage_class="canonical_evidence",
    )
    target_date = date_from_event_slug(paths["source"].parent.name)
    as_of = _parse_date(plan["as_of_date"])
    minimum_age = int(
        (plan.get("hot_window") or {}).get(
            "configured_hot_window_days"
        )
    )
    if (
        target_date is None
        or target_date >= as_of
        or (as_of - target_date).days < minimum_age
    ):
        raise ProjectionTieringError(
            "event day is no longer outside the approved warm window"
        )
    _assert_finalization_proof_current(
        (action.get("closed_finalized_proof") or {}).get(
            "finalization"
        )
        or {},
        folder=paths["source"].parent,
        event_slug=paths["source"].parent.name,
        ledger_root=Path(plan["ledger_root"]).resolve(),
    )
    return paths


def _warm_compression_intent(
    action: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "COMPRESSION_PENDING",
        "action_id": action.get("action_id"),
        "source": dict(action.get("source") or {}),
        "gzip_path": (action.get("gzip") or {}).get("path"),
        "deterministic_mtime": 0,
        "verification": "compressed_sha256_plus_decompressed_byte_parity",
    }


def _warm_compression_intent_matches(
    action: dict[str, Any],
    intent: dict[str, Any] | None,
) -> bool:
    return isinstance(intent, dict) and intent == _warm_compression_intent(
        action
    )


def _prepare_or_resume_warm_gzip(
    action: dict[str, Any],
    *,
    snapshots_root: Path,
    resume_compression: dict[str, Any] | None,
    compression_intent: dict[str, Any] | None,
) -> dict[str, Any]:
    gzip_path = _resolve_under_root(
        snapshots_root,
        action["gzip"]["path"],
    )
    if (
        gzip_path.exists()
        and not action["gzip"].get("preexisting")
    ):
        expected = (
            (resume_compression or {}).get("compressed_identity")
        )
        if not isinstance(expected, dict):
            if _warm_compression_intent_matches(
                action,
                compression_intent,
            ):
                return _prepare_gzip(
                    action,
                    snapshots_root=snapshots_root,
                    allow_adopt_existing=True,
                )
            raise ProjectionTieringError(
                "unplanned warm gzip lacks a durable compression checkpoint "
                "or exact compression intent"
            )
        current = _file_identity(gzip_path, root=snapshots_root)
        _assert_identity(current, expected, "resumed warm gzip")
        payload = _gzip_payload_identity(gzip_path)
        if (
            payload["payload_bytes"] != action["source"]["bytes"]
            or payload["payload_sha256"] != action["source"]["sha256"]
        ):
            raise ProjectionTieringError(
                "resumed warm gzip failed decompressed byte parity"
            )
        return {
            "status": "PASS",
            "created": bool(
                (resume_compression or {}).get("created")
            ),
            "resumed_from_durable_checkpoint": True,
            "deterministic_mtime": 0,
            "compressed_identity": current,
            **payload,
        }
    return _prepare_gzip(
        action,
        snapshots_root=snapshots_root,
        allow_adopt_existing=(
            gzip_path.exists()
            and _warm_compression_intent_matches(
                action,
                compression_intent,
            )
        ),
    )


def _warm_final_reverification(
    action: dict[str, Any],
    paths: dict[str, Path],
    gzip_proof: dict[str, Any],
    *,
    plan: dict[str, Any],
    snapshots_root: Path,
    held_lock: dict[str, Any],
) -> dict[str, Any]:
    held_lock_path = Path(str(held_lock.get("path") or ""))
    if _writer_lock_paths(
        paths["source"].parent,
        exclude=held_lock_path,
    ):
        raise ProjectionTieringError(
            "event-folder writer lock appeared before warm unlink"
        )
    source_identity = _file_identity(
        paths["source"],
        root=snapshots_root,
    )
    gzip_identity = _file_identity(
        paths["gzip"],
        root=snapshots_root,
    )
    manifest_identity = _file_identity(
        paths["manifest"],
        root=snapshots_root,
    )
    _assert_identity(
        source_identity,
        action["source"],
        "warm source final reverify",
    )
    _assert_identity(
        gzip_identity,
        gzip_proof["compressed_identity"],
        "warm gzip final reverify",
    )
    _assert_identity(
        manifest_identity,
        {
            key: action["event_manifest"].get(key)
            for key in _IDENTITY_KEYS
        },
        "warm event manifest final reverify",
    )
    resolution = resolve_tiered_text(paths["source"])
    if not resolution.transitional_pair:
        raise ProjectionTieringError(
            "warm plain/gzip pair is not byte-identical before unlink"
        )
    payload = _gzip_payload_identity(paths["gzip"])
    if (
        payload["payload_bytes"] != source_identity["bytes"]
        or payload["payload_sha256"] != source_identity["sha256"]
    ):
        raise ProjectionTieringError(
            "warm gzip payload parity changed immediately before unlink"
        )
    finalization = _assert_finalization_proof_current(
        (action.get("closed_finalized_proof") or {}).get(
            "finalization"
        )
        or {},
        folder=paths["source"].parent,
        event_slug=paths["source"].parent.name,
        ledger_root=Path(plan["ledger_root"]).resolve(),
    )
    return {
        "status": "PASS",
        "verified_at_utc": utc_iso(),
        "source": source_identity,
        "gzip": gzip_identity,
        "gzip_payload": payload,
        "event_manifest": manifest_identity,
        "competing_writer_locks_absent": True,
        "raw_tape_writer_lock_held": {
            "path": str(held_lock_path),
            "owner": held_lock.get("owner") or {},
        },
        "finalization": finalization,
    }


def _warm_representation_rebind_proof(
    action: dict[str, Any],
    *,
    gzip_identity: dict[str, Any],
    gzip_payload: dict[str, Any],
) -> dict[str, Any]:
    """Bind the approved protected plain bytes to the retained gzip payload."""

    source = dict(action.get("source") or {})
    if (
        gzip_payload.get("payload_bytes") != source.get("bytes")
        or gzip_payload.get("payload_sha256") != source.get("sha256")
    ):
        raise ProjectionTieringError(
            "warm protection rebind requires exact decompressed source parity"
        )
    approved_event_manifest = action.get("event_manifest") or {}
    approved_protection = approved_event_manifest.get("protection") or {}
    approved_validation = approved_event_manifest.get("validation") or {}
    if (
        approved_validation.get("status") != "PASS"
        or approved_protection.get("status") != "PASS"
        or (approved_protection.get("backup") or {}).get("status") != "PASS"
        or (approved_protection.get("restore") or {}).get("status") != "PASS"
    ):
        raise ProjectionTieringError(
            "warm protection rebind lacks approved PASS backup/restore proof"
        )
    proof = {
        "status": "PASS",
        "proof_kind": "canonical_gzip_semantic_representation_rebind",
        "approved_event_manifest_hash": approved_event_manifest.get(
            "manifest_hash"
        ),
        "approved_event_manifest_identity": {
            key: approved_event_manifest.get(key)
            for key in _IDENTITY_KEYS
        },
        "approved_validation_hash": _json_hash(approved_validation),
        "approved_backup_proof_hash": _json_hash(
            approved_protection.get("backup") or {}
        ),
        "approved_restore_proof_hash": _json_hash(
            approved_protection.get("restore") or {}
        ),
        "protected_plain_source": source,
        "retained_gzip": dict(gzip_identity),
        "retained_gzip_decompressed_payload": dict(gzip_payload),
        "semantic_identity": {
            "bytes": source.get("bytes"),
            "sha256": source.get("sha256"),
        },
        "reason": (
            "the exact approved off-machine backup and restore proof protects "
            "the plain canonical byte stream; the retained deterministic gzip "
            "was reverified to decompress to that same byte length and SHA-256"
        ),
    }
    proof["proof_hash"] = _json_hash(proof)
    return proof


def _rebind_warm_manifest_protection(
    manifest: dict[str, Any],
    action: dict[str, Any],
    *,
    gzip_identity: dict[str, Any],
    gzip_payload: dict[str, Any],
) -> dict[str, Any]:
    """Attach an auditable semantic protection proof to a refreshed manifest."""

    approved_event_manifest = action.get("event_manifest") or {}
    approved_protection = approved_event_manifest.get("protection") or {}
    approved_validation = approved_event_manifest.get("validation") or {}
    proof = _warm_representation_rebind_proof(
        action,
        gzip_identity=gzip_identity,
        gzip_payload=gzip_payload,
    )
    proof_hash = proof["proof_hash"]
    manifest["protection"] = {
        "status": "PASS",
        "semantics": "canonical_gzip_semantic_representation_rebind",
        "backup": {
            "status": "PASS",
            "basis": (
                "approved exact plain-source backup proof plus verified "
                "decompressed gzip parity"
            ),
            "pre_replacement_proof": json.loads(
                json.dumps(approved_protection.get("backup") or {})
            ),
            "representation_rebind_proof_hash": proof_hash,
        },
        "restore": {
            "status": "PASS",
            "basis": (
                "approved exact plain-source restore proof plus verified "
                "decompressed gzip parity"
            ),
            "pre_replacement_proof": json.loads(
                json.dumps(approved_protection.get("restore") or {})
            ),
            "representation_rebind_proof_hash": proof_hash,
        },
        "pre_replacement_protection": json.loads(
            json.dumps(approved_protection)
        ),
        "warm_representation_rebind": proof,
    }
    approved_checks = {
        str(check.get("check") or ""): check
        for check in approved_validation.get("checks") or []
        if isinstance(check, dict)
    }
    checks = json.loads(
        json.dumps((manifest.get("validation") or {}).get("checks") or [])
    )
    protection_check_names = {
        "shared_payload_backup_restore",
        "off_machine_backup",
        "restore_proof",
    }
    for check in checks:
        check_name = str(check.get("check") or "")
        if check_name not in protection_check_names:
            continue
        approved_check = approved_checks.get(check_name)
        if not approved_check or approved_check.get("status") != "PASS":
            raise ProjectionTieringError(
                "approved manifest lacks a PASS protection check required "
                f"for semantic rebind: {check_name}"
            )
        check["status"] = "PASS"
        check["detail"] = "canonical_gzip_semantic_representation_rebind"
        check["approved_check_hash"] = _json_hash(approved_check)
        check["representation_rebind_proof_hash"] = proof_hash
    checks.extend(
        [
            {
                "check": "pre_replacement_manifest_validation",
                "status": "PASS",
                "approved_event_manifest_hash": (
                    approved_event_manifest.get("manifest_hash")
                ),
                "approved_validation_hash": _json_hash(
                    approved_validation
                ),
            },
            {
                "check": "canonical_warm_representation_rebind",
                "status": "PASS",
                "proof_hash": proof_hash,
                "semantic_identity": dict(proof["semantic_identity"]),
                "retained_gzip_path": gzip_identity.get("path"),
            },
        ]
    )
    if any(check.get("status") == "BLOCK" for check in checks):
        validation_status = "BLOCK"
    elif any(check.get("status") == "WARN" for check in checks):
        validation_status = "WARN"
    else:
        validation_status = "PASS"
    manifest["validation"] = {
        "status": validation_status,
        "checks": checks,
    }
    summary = manifest.setdefault("summary", {})
    summary["backup_status"] = "PASS"
    summary["restore_status"] = "PASS"
    summary["warm_representation_rebind_proof_hash"] = proof_hash
    return proof


def _assert_warm_manifest_protection_rebound(
    manifest: dict[str, Any],
    action: dict[str, Any],
    *,
    gzip_identity: dict[str, Any],
    gzip_payload: dict[str, Any],
) -> dict[str, Any]:
    expected = _warm_representation_rebind_proof(
        action,
        gzip_identity=gzip_identity,
        gzip_payload=gzip_payload,
    )
    protection = manifest.get("protection") or {}
    actual = protection.get("warm_representation_rebind")
    if actual != expected:
        raise ProjectionTieringError(
            "refreshed warm manifest protection rebind proof is stale or "
            "does not bind the approved source to the retained gzip"
        )
    approved_protection = (
        (action.get("event_manifest") or {}).get("protection") or {}
    )
    if (
        protection.get("status") != "PASS"
        or (protection.get("backup") or {}).get("pre_replacement_proof")
        != approved_protection.get("backup")
        or (protection.get("restore") or {}).get("pre_replacement_proof")
        != approved_protection.get("restore")
        or protection.get("pre_replacement_protection")
        != approved_protection
    ):
        raise ProjectionTieringError(
            "refreshed warm manifest did not preserve the exact approved "
            "backup/restore protection proof"
        )
    validation = manifest.get("validation") or {}
    rebind_checks = [
        check
        for check in validation.get("checks") or []
        if check.get("check") == "canonical_warm_representation_rebind"
    ]
    if (
        validation.get("status") != "PASS"
        or len(rebind_checks) != 1
        or rebind_checks[0].get("status") != "PASS"
        or rebind_checks[0].get("proof_hash") != expected["proof_hash"]
    ):
        raise ProjectionTieringError(
            "refreshed warm manifest validation does not bind the protection "
            "rebind proof"
        )
    return expected


def _refresh_and_validate_warm_event_manifest(
    folder: Path,
    *,
    snapshots_root: Path,
    manifest_validator: Callable[..., dict[str, Any]],
    action: dict[str, Any],
) -> dict[str, Any]:
    gzip_path = folder / ORDER_BOOK_RAW_GZIP
    gzip_identity = _file_identity(gzip_path, root=snapshots_root)
    gzip_payload = _gzip_payload_identity(gzip_path)
    manifest = build_event_day_manifest(
        folder,
        snapshots_root=snapshots_root,
        generated_at_utc=utc_iso(),
    )
    rebind = _rebind_warm_manifest_protection(
        manifest,
        action,
        gzip_identity=gzip_identity,
        gzip_payload=gzip_payload,
    )
    manifest["manifest_hash"] = ""
    manifest["manifest_hash"] = manifest_content_hash(manifest)
    path = event_day_manifest_path(folder)
    _atomic_write_text(
        path,
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
    )
    manifest = read_event_day_manifest(path)
    if manifest is None or not manifest_hash_valid(manifest):
        raise ProjectionTieringError(
            "refreshed warm event manifest is unreadable or hash-invalid"
        )
    _assert_warm_manifest_protection_rebound(
        manifest,
        action,
        gzip_identity=gzip_identity,
        gzip_payload=gzip_payload,
    )
    validation = _validator_result(
        manifest_validator,
        manifest,
        folder,
        snapshots_root,
    )
    if validation.get("status") != "PASS":
        raise ProjectionTieringError(
            "refreshed warm event manifest did not validate PASS"
        )
    paths = {
        str(record.get("path") or "")
        for record in _manifest_records(manifest)
    }
    if ORDER_BOOK_RAW in paths:
        raise ProjectionTieringError(
            "refreshed warm manifest still lists removed plain source"
        )
    if ORDER_BOOK_RAW_GZIP not in paths:
        raise ProjectionTieringError(
            "refreshed warm manifest lacks canonical gzip source"
        )
    if (
        (folder / ORDER_BOOK_RAW).exists()
        or not (folder / ORDER_BOOK_RAW_GZIP).is_file()
    ):
        raise ProjectionTieringError(
            "refreshed warm manifest does not match retained artifact state"
        )
    return {
        "status": "PASS",
        "manifest": _file_identity(path, root=snapshots_root),
        "manifest_hash": manifest.get("manifest_hash"),
        "validation": validation,
        "plain_source_absent": True,
        "canonical_gzip_present": True,
        "protection_rebind": rebind,
    }


def _post_refresh_warm_manifest_validation(
    folder: Path,
    action: dict[str, Any],
    *,
    snapshots_root: Path,
    manifest_validator: Callable[..., dict[str, Any]],
    expected_gzip_identity: dict[str, Any],
) -> dict[str, Any]:
    """Re-read and independently prove the callback-published manifest."""

    source = folder / ORDER_BOOK_RAW
    gzip_path = folder / ORDER_BOOK_RAW_GZIP
    path = event_day_manifest_path(folder)
    if source.exists():
        raise ProjectionTieringError(
            "post-refresh warm validation found the removed plain source"
        )
    current_gzip = _file_identity(gzip_path, root=snapshots_root)
    _assert_identity(
        current_gzip,
        expected_gzip_identity,
        "post-refresh warm gzip",
    )
    payload = _gzip_payload_identity(gzip_path)
    if (
        payload["payload_bytes"] != action["source"]["bytes"]
        or payload["payload_sha256"] != action["source"]["sha256"]
    ):
        raise ProjectionTieringError(
            "post-refresh warm gzip failed decompressed source parity"
        )
    manifest = read_event_day_manifest(path)
    if manifest is None or not manifest_hash_valid(manifest):
        raise ProjectionTieringError(
            "post-refresh warm manifest is unreadable or hash-invalid"
        )
    if (manifest.get("validation") or {}).get("status") != "PASS":
        raise ProjectionTieringError(
            "post-refresh warm manifest is not embedded-validation PASS"
        )
    validation = _validator_result(
        manifest_validator,
        manifest,
        folder,
        snapshots_root,
    )
    if validation.get("status") != "PASS":
        raise ProjectionTieringError(
            "post-refresh warm manifest is not current"
        )
    manifest_paths = {
        str(record.get("path") or "")
        for record in _manifest_records(manifest)
    }
    if ORDER_BOOK_RAW in manifest_paths or ORDER_BOOK_RAW_GZIP not in (
        manifest_paths
    ):
        raise ProjectionTieringError(
            "post-refresh warm manifest representation is inconsistent"
        )
    _assert_manifest_record_current(
        manifest,
        ORDER_BOOK_RAW_GZIP,
        {**current_gzip, "path": ORDER_BOOK_RAW_GZIP},
        expected_storage_class="canonical_evidence",
    )
    rebind = _assert_warm_manifest_protection_rebound(
        manifest,
        action,
        gzip_identity=current_gzip,
        gzip_payload=payload,
    )
    return {
        "status": "PASS",
        "manifest": _file_identity(path, root=snapshots_root),
        "manifest_hash": manifest.get("manifest_hash"),
        "validation": validation,
        "gzip": current_gzip,
        "gzip_payload": payload,
        "protection_rebind": rebind,
        "plain_source_absent": True,
    }


def _receipt_path_errors(
    *,
    snapshots_root: Path,
    receipt_json_path: str | Path | None,
    receipt_report_path: str | Path | None,
) -> list[str]:
    if receipt_json_path is None or receipt_report_path is None:
        return [
            "durable JSON+Markdown receipt paths are required before warm apply"
        ]
    try:
        json_path = Path(receipt_json_path).resolve()
        report_path = Path(receipt_report_path).resolve()
        if json_path == report_path:
            raise ProjectionTieringError(
                "warm receipt JSON and Markdown paths must be distinct"
            )
        if json_path.parent != report_path.parent:
            raise ProjectionTieringError(
                "warm receipt JSON and Markdown must share one output root"
            )
        _assert_output_root_is_external(
            json_path.parent,
            [data_root_for_snapshots(snapshots_root)],
        )
        for path in (json_path, report_path):
            if path.exists() and _is_reparse_point(path):
                raise ProjectionTieringError(
                    f"warm receipt path is a reparse point: {path}"
                )
    except (OSError, ValueError, ProjectionTieringError) as exc:
        return [f"warm receipt path boundary is invalid: {exc}"]
    return []


def _read_verified_warm_receipt_files(
    *,
    receipt_json_path: Path,
    receipt_report_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        loaded, identity = _read_json_with_identity(receipt_json_path)
    except (OSError, ValueError, ProjectionTieringError) as exc:
        raise ProjectionTieringError(
            f"durable warm receipt checkpoint could not be re-read: {exc}"
        ) from exc
    if not receipt_report_path.is_file() or _is_reparse_point(
        receipt_report_path
    ):
        raise ProjectionTieringError(
            "durable warm receipt Markdown checkpoint is missing"
        )
    try:
        report_bytes = receipt_report_path.read_bytes()
    except OSError as exc:
        raise ProjectionTieringError(
            f"durable warm receipt Markdown could not be re-read: {exc}"
        ) from exc
    expected_report = render_report(loaded).encode("utf-8")
    if report_bytes != expected_report:
        raise ProjectionTieringError(
            "durable warm receipt Markdown does not match the checkpoint payload"
        )
    return loaded, identity


def _persist_verified_receipt(
    receipt: dict[str, Any],
    *,
    persist_receipt: Callable[[dict[str, Any]], None],
    receipt_json_path: Path,
    receipt_report_path: Path,
) -> dict[str, Any]:
    persist_receipt(receipt)
    loaded, identity = _read_verified_warm_receipt_files(
        receipt_json_path=receipt_json_path,
        receipt_report_path=receipt_report_path,
    )
    if loaded != receipt:
        raise ProjectionTieringError(
            "durable warm receipt JSON does not match the checkpoint payload"
        )
    return identity


def _rollback_created_warm_gzip_if_safe(
    action: dict[str, Any],
    action_receipt: dict[str, Any],
    *,
    paths: dict[str, Path],
    snapshots_root: Path,
) -> dict[str, Any] | None:
    """Restore the approved plain-only state after a pre-unlink failure."""

    compression = action_receipt.get("compression") or {}
    if (
        compression.get("created") is not True
        or not paths["source"].is_file()
        or not paths["gzip"].exists()
    ):
        return None
    if not paths["gzip"].is_file() or _is_reparse_point(paths["gzip"]):
        raise ProjectionTieringError(
            "tool-created staged gzip cannot be safely rolled back"
        )
    expected = compression.get("compressed_identity")
    if not isinstance(expected, dict):
        raise ProjectionTieringError(
            "tool-created staged gzip lacks an exact rollback identity"
        )
    current = _file_identity(paths["gzip"], root=snapshots_root)
    _assert_identity(current, expected, "staged warm gzip rollback")
    source = _file_identity(paths["source"], root=snapshots_root)
    _assert_identity(source, action["source"], "warm source rollback")
    payload = _gzip_payload_identity(paths["gzip"])
    if (
        payload["payload_bytes"] != source["bytes"]
        or payload["payload_sha256"] != source["sha256"]
    ):
        raise ProjectionTieringError(
            "tool-created staged gzip no longer matches the retained source"
        )
    paths["gzip"].unlink()
    if paths["gzip"].exists():
        raise ProjectionTieringError(
            "tool-created staged gzip rollback did not remove the exact file"
        )
    rollback = {
        "status": "PASS",
        "path": action["gzip"]["path"],
        "exact_tool_created_file_only": True,
        "plain_source_retained": True,
        "removed_identity": current,
    }
    action_receipt["staged_gzip_rollback"] = rollback
    intent = action_receipt.get("compression_intent")
    if isinstance(intent, dict):
        intent["status"] = "ROLLED_BACK_AFTER_PRE_UNLINK_FAILURE"
    return rollback


def _apply_one_warm(
    plan: dict[str, Any],
    action: dict[str, Any],
    action_receipt: dict[str, Any],
    *,
    snapshots_root: Path,
    manifest_validator: Callable[..., dict[str, Any]],
    manifest_refresher: Callable[..., dict[str, Any]] | None,
    persist_checkpoint: Callable[[], dict[str, Any]],
) -> None:
    resume_compression = action_receipt.get("compression")
    compression_intent = action_receipt.get("compression_intent")
    paths = _assert_warm_action_current(
        action,
        plan=plan,
        snapshots_root=snapshots_root,
        manifest_validator=manifest_validator,
        resume_compression=(
            resume_compression
            if isinstance(resume_compression, dict)
            else None
        ),
        compression_intent=(
            compression_intent
            if isinstance(compression_intent, dict)
            else None
        ),
    )
    action_receipt["pre_apply_validation"] = {
        "status": "PASS",
        "closed_finalized_proof": action["closed_finalized_proof"],
    }
    preflight = build_cleanup_preflight(
        _cleanup_manifest(plan, action),
        root=snapshots_root,
    )
    action_receipt["cleanup_preflight"] = preflight
    if (
        preflight.get("status") != "PASS"
        or preflight.get("delete_permission") is not True
    ):
        raise ProjectionTieringError(
            "cleanup_preflight denied warm representation replacement"
        )
    persist_checkpoint()

    held_lock = _acquire_raw_tape_writer_lock(
        paths["source"].parent,
        action_id=str(action["action_id"]),
    )
    action_receipt["raw_tape_writer_lock"] = {
        "status": "HELD",
        "path": held_lock.get("path"),
        "owner": held_lock.get("owner") or {},
    }
    try:
        persist_checkpoint()
        if not source_is_quiet(paths["source"]):
            raise ProjectionTieringError(
                "order_books.jsonl is no longer writer-quiescent for the "
                f"required {MIN_QUIET_SECONDS:g} seconds"
            )
        action_receipt["source_quiescence"] = {
            "status": "PASS",
            "minimum_quiet_seconds": MIN_QUIET_SECONDS,
            "checked_under_raw_tape_writer_lock": True,
        }
        if (
            not isinstance(resume_compression, dict)
            and not action["gzip"].get("preexisting")
        ):
            if not isinstance(compression_intent, dict):
                compression_intent = _warm_compression_intent(action)
                action_receipt["compression_intent"] = compression_intent
            if not _warm_compression_intent_matches(
                action,
                compression_intent,
            ):
                raise ProjectionTieringError(
                    "durable warm compression intent is not bound to the "
                    "exact approved action"
                )
            action_receipt["status"] = "COMPRESSION_PENDING"
            persist_checkpoint()
        gzip_proof = _prepare_or_resume_warm_gzip(
            action,
            snapshots_root=snapshots_root,
            resume_compression=(
                resume_compression
                if isinstance(resume_compression, dict)
                else None
            ),
            compression_intent=(
                compression_intent
                if isinstance(compression_intent, dict)
                else None
            ),
        )
        action_receipt["compression"] = gzip_proof
        if isinstance(compression_intent, dict):
            compression_intent["status"] = "COMPRESSION_VERIFIED"
            compression_intent["compressed_identity"] = (
                gzip_proof["compressed_identity"]
            )
        action_receipt["status"] = "RUNNING"
        persist_checkpoint()

        final_reverification = _warm_final_reverification(
            action,
            paths,
            gzip_proof,
            plan=plan,
            snapshots_root=snapshots_root,
            held_lock=held_lock,
        )
        action_receipt["final_reverification"] = final_reverification
        action_receipt["representation_replacement"] = {
            "status": "AUTHORIZED_PENDING",
            "path": action["source"]["path"],
            "exact_file_only": True,
            "source_identity": final_reverification["source"],
            "gzip_identity": final_reverification["gzip"],
        }
        action_receipt["event_day_manifest_refresh_required"] = True
        action_receipt["status"] = "UNLINK_PENDING"
        pre_unlink_checkpoint = persist_checkpoint()

        action_receipt["immediate_pre_unlink_reverification"] = (
            _warm_final_reverification(
                action,
                paths,
                gzip_proof,
                plan=plan,
                snapshots_root=snapshots_root,
                held_lock=held_lock,
            )
        )
        paths["source"].unlink()
        if paths["source"].exists():
            raise ProjectionTieringError(
                "exact warm source unlink did not remove the file"
            )
        if not paths["gzip"].is_file():
            raise ProjectionTieringError(
                "canonical warm gzip disappeared after source unlink"
            )
        action_receipt["durable_pre_unlink_checkpoint"] = (
            pre_unlink_checkpoint
        )
        action_receipt["representation_replacement"] = {
            "status": "UNLINKED_MANIFEST_REFRESH_PENDING",
            "path": action["source"]["path"],
            "exact_file_only": True,
            "source_absent": True,
            "canonical_gzip_retained": True,
        }
        action_receipt["status"] = "MANIFEST_REFRESH_PENDING"
        persist_checkpoint()

        if manifest_refresher is None:
            refresh = _refresh_and_validate_warm_event_manifest(
                paths["source"].parent,
                snapshots_root=snapshots_root,
                manifest_validator=manifest_validator,
                action=action,
            )
        else:
            refresh = manifest_refresher(
                paths["source"].parent,
                snapshots_root=snapshots_root,
                manifest_validator=manifest_validator,
                action=action,
            )
        if refresh.get("status") != "PASS":
            raise ProjectionTieringError(
                "warm event-day manifest refresh did not return PASS"
            )
        post_refresh = _post_refresh_warm_manifest_validation(
            paths["source"].parent,
            action,
            snapshots_root=snapshots_root,
            manifest_validator=manifest_validator,
            expected_gzip_identity=gzip_proof["compressed_identity"],
        )
        action_receipt["event_day_manifest_refresh"] = refresh
        action_receipt["event_day_manifest_post_refresh_validation"] = (
            post_refresh
        )
        action_receipt["representation_replacement"]["status"] = "PASS"
        action_receipt["event_day_manifest_refresh_required"] = False
        action_receipt["status"] = "APPLIED"
        persist_checkpoint()
    except BaseException as exc:
        try:
            _rollback_created_warm_gzip_if_safe(
                action,
                action_receipt,
                paths=paths,
                snapshots_root=snapshots_root,
            )
        except Exception as rollback_exc:
            action_receipt["staged_gzip_rollback"] = {
                "status": "BLOCK",
                "detail": str(rollback_exc),
            }
            raise ProjectionTieringError(
                f"{exc}; staged gzip rollback also blocked: {rollback_exc}"
            ) from exc
        raise
    finally:
        release_writer_lock(held_lock)
        action_receipt["raw_tape_writer_lock"]["status"] = "RELEASED"


def _recover_warm_manifest_refresh(
    plan: dict[str, Any],
    action: dict[str, Any],
    action_receipt: dict[str, Any],
    *,
    snapshots_root: Path,
    manifest_validator: Callable[..., dict[str, Any]],
    manifest_refresher: Callable[..., dict[str, Any]] | None,
    persist_checkpoint: Callable[[], dict[str, Any]],
) -> None:
    paths = _assert_warm_action_shape(action, snapshots_root)
    if paths["source"].exists():
        raise ProjectionTieringError(
            "warm manifest recovery requires the exact plain source to be absent"
        )
    if _writer_lock_paths(paths["gzip"].parent):
        raise ProjectionTieringError(
            "event-folder writer lock blocks warm manifest recovery"
        )
    compression = action_receipt.get("compression") or {}
    expected_gzip = compression.get("compressed_identity")
    if not isinstance(expected_gzip, dict):
        expected_gzip = action["gzip"].get("identity")
    if not isinstance(expected_gzip, dict):
        raise ProjectionTieringError(
            "warm manifest recovery lacks a receipt-bound gzip identity"
        )
    current_gzip = _file_identity(
        paths["gzip"],
        root=snapshots_root,
    )
    _assert_identity(
        current_gzip,
        expected_gzip,
        "warm recovery gzip",
    )
    payload = _gzip_payload_identity(paths["gzip"])
    if (
        payload["payload_bytes"] != action["source"]["bytes"]
        or payload["payload_sha256"] != action["source"]["sha256"]
    ):
        raise ProjectionTieringError(
            "warm recovery gzip failed decompressed byte parity"
        )
    target_date = date_from_event_slug(paths["gzip"].parent.name)
    as_of = _parse_date(plan["as_of_date"])
    minimum_age = int(
        (plan.get("hot_window") or {}).get(
            "configured_hot_window_days"
        )
    )
    if (
        target_date is None
        or target_date >= as_of
        or (as_of - target_date).days < minimum_age
    ):
        raise ProjectionTieringError(
            "warm recovery event is not outside the approved hot window"
        )
    _assert_finalization_proof_current(
        (action.get("closed_finalized_proof") or {}).get(
            "finalization"
        )
        or {},
        folder=paths["gzip"].parent,
        event_slug=paths["gzip"].parent.name,
        ledger_root=Path(plan["ledger_root"]).resolve(),
    )
    held_lock = _acquire_raw_tape_writer_lock(
        paths["gzip"].parent,
        action_id=str(action["action_id"]),
    )
    action_receipt["raw_tape_writer_lock"] = {
        "status": "HELD_RECOVERY",
        "path": held_lock.get("path"),
        "owner": held_lock.get("owner") or {},
    }
    try:
        persist_checkpoint()
        if manifest_refresher is None:
            refresh = _refresh_and_validate_warm_event_manifest(
                paths["gzip"].parent,
                snapshots_root=snapshots_root,
                manifest_validator=manifest_validator,
                action=action,
            )
        else:
            refresh = manifest_refresher(
                paths["gzip"].parent,
                snapshots_root=snapshots_root,
                manifest_validator=manifest_validator,
                action=action,
            )
        if refresh.get("status") != "PASS":
            raise ProjectionTieringError(
                "warm recovery manifest refresh did not return PASS"
            )
        post_refresh = _post_refresh_warm_manifest_validation(
            paths["gzip"].parent,
            action,
            snapshots_root=snapshots_root,
            manifest_validator=manifest_validator,
            expected_gzip_identity=current_gzip,
        )
        action_receipt["event_day_manifest_refresh"] = refresh
        action_receipt["event_day_manifest_post_refresh_validation"] = (
            post_refresh
        )
        action_receipt["representation_replacement"] = {
            "status": "PASS",
            "path": action["source"]["path"],
            "exact_file_only": True,
            "source_absent": True,
            "canonical_gzip_retained": True,
            "recovered_after_interruption": True,
        }
        action_receipt["event_day_manifest_refresh_required"] = False
        action_receipt["status"] = "APPLIED"
        persist_checkpoint()
    finally:
        release_writer_lock(held_lock)
        action_receipt["raw_tape_writer_lock"]["status"] = "RELEASED"


def _update_warm_apply_summary(
    receipt: dict[str, Any],
    *,
    planned: int,
) -> None:
    actions = receipt.get("actions") or []
    receipt["summary"] = {
        "planned": planned,
        "attempted": len(actions),
        "applied": sum(
            row.get("status") == "APPLIED" for row in actions
        ),
        "failed": sum(
            row.get("status") == "BLOCK" for row in actions
        ),
        "not_attempted": planned - len(actions),
        "canonical_gzip_retained": sum(
            row.get("status") == "APPLIED" for row in actions
        ),
        "plain_representations_removed": sum(
            row.get("status") == "APPLIED" for row in actions
        ),
    }


def _existing_warm_receipt_binding_errors(
    receipt: dict[str, Any],
    *,
    plan: dict[str, Any],
    approved_manifest_identity: dict[str, Any] | None,
) -> list[str]:
    errors: list[str] = []
    expected_top_level = {
        "schema_version": WARM_RECEIPT_SCHEMA_VERSION,
        "writer": WRITER,
        "mode": "warm_apply",
        "plan_hash": plan.get("plan_hash"),
        "snapshots_root": plan.get("snapshots_root"),
        "approved_manifest_identity": approved_manifest_identity,
    }
    for key, expected in expected_top_level.items():
        if receipt.get(key) != expected:
            errors.append(
                f"existing warm receipt {key} is not bound to this plan"
            )

    planned_actions = list(plan.get("actions") or [])
    planned_by_id = {
        str(action.get("action_id") or ""): action
        for action in planned_actions
    }
    receipt_actions = receipt.get("actions")
    if not isinstance(receipt_actions, list):
        return [*errors, "existing warm receipt actions must be a list"]
    receipt_ids = [
        str(row.get("action_id") or "")
        for row in receipt_actions
        if isinstance(row, dict)
    ]
    if len(receipt_ids) != len(receipt_actions):
        errors.append("existing warm receipt action rows must be objects")
        return errors
    if any(not action_id for action_id in receipt_ids):
        errors.append("existing warm receipt action_id is required")
    if len(receipt_ids) != len(set(receipt_ids)):
        errors.append("existing warm receipt action_id values must be unique")
    planned_ids = [
        str(action.get("action_id") or "") for action in planned_actions
    ]
    if receipt_ids != planned_ids[: len(receipt_ids)]:
        errors.append(
            "existing warm receipt actions are not the exact approved-plan "
            "prefix"
        )
    allowed_statuses = {
        "RUNNING",
        "BLOCK",
        "COMPRESSION_PENDING",
        "UNLINK_PENDING",
        "MANIFEST_REFRESH_PENDING",
        "APPLIED",
    }
    for row in receipt_actions:
        action_id = str(row.get("action_id") or "")
        action = planned_by_id.get(action_id)
        if action is None:
            continue
        if row.get("warm_family") != action.get("warm_family"):
            errors.append(
                f"existing warm receipt action {action_id} family changed"
            )
        if row.get("source") != action.get("source"):
            errors.append(
                f"existing warm receipt action {action_id} source changed"
            )
        if row.get("status") not in allowed_statuses:
            errors.append(
                f"existing warm receipt action {action_id} has invalid status"
            )
    return errors


def _verify_completed_warm_action(
    plan: dict[str, Any],
    action: dict[str, Any],
    action_receipt: dict[str, Any],
    *,
    snapshots_root: Path,
    manifest_validator: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    paths = _assert_warm_action_shape(action, snapshots_root)
    locks = _writer_lock_paths(paths["gzip"].parent)
    if locks:
        raise ProjectionTieringError(
            "completed warm action has an event-folder writer lock: "
            f"{[str(path) for path in locks]}"
        )
    if paths["source"].exists():
        raise ProjectionTieringError(
            "completed warm action unexpectedly retains the plain source"
        )
    if not paths["gzip"].is_file() or _is_reparse_point(paths["gzip"]):
        raise ProjectionTieringError(
            "completed warm action canonical gzip is missing or not regular"
        )
    compression = action_receipt.get("compression") or {}
    expected_gzip = compression.get("compressed_identity")
    if not isinstance(expected_gzip, dict):
        raise ProjectionTieringError(
            "completed warm action lacks a receipt-bound gzip identity"
        )
    current_gzip = _file_identity(paths["gzip"], root=snapshots_root)
    _assert_identity(
        current_gzip,
        expected_gzip,
        "completed warm gzip",
    )
    payload = _gzip_payload_identity(paths["gzip"])
    if (
        payload["payload_bytes"] != action["source"]["bytes"]
        or payload["payload_sha256"] != action["source"]["sha256"]
    ):
        raise ProjectionTieringError(
            "completed warm action gzip failed decompressed byte parity"
        )
    manifest = read_event_day_manifest(paths["manifest"])
    if manifest is None or not manifest_hash_valid(manifest):
        raise ProjectionTieringError(
            "completed warm action manifest is missing or hash-invalid"
        )
    if (manifest.get("validation") or {}).get("status") != "PASS":
        raise ProjectionTieringError(
            "completed warm action manifest is not finalized PASS"
        )
    protection_rebind = _assert_warm_manifest_protection_rebound(
        manifest,
        action,
        gzip_identity=current_gzip,
        gzip_payload=payload,
    )
    validation = _validator_result(
        manifest_validator,
        manifest,
        paths["gzip"].parent,
        snapshots_root,
    )
    if validation.get("status") != "PASS":
        raise ProjectionTieringError(
            "completed warm action manifest is no longer current"
        )
    manifest_paths = {
        str(record.get("path") or "")
        for record in _manifest_records(manifest)
    }
    if ORDER_BOOK_RAW in manifest_paths or ORDER_BOOK_RAW_GZIP not in (
        manifest_paths
    ):
        raise ProjectionTieringError(
            "completed warm action manifest representation is inconsistent"
        )
    _assert_manifest_record_current(
        manifest,
        ORDER_BOOK_RAW_GZIP,
        {**current_gzip, "path": ORDER_BOOK_RAW_GZIP},
        expected_storage_class="canonical_evidence",
    )
    if action_receipt.get("event_day_manifest_refresh_required") is not False:
        raise ProjectionTieringError(
            "completed warm action still requires manifest refresh"
        )
    if (
        (action_receipt.get("representation_replacement") or {}).get("status")
        != "PASS"
    ):
        raise ProjectionTieringError(
            "completed warm action lacks a PASS representation receipt"
        )
    _assert_finalization_proof_current(
        (action.get("closed_finalized_proof") or {}).get("finalization")
        or {},
        folder=paths["gzip"].parent,
        event_slug=paths["gzip"].parent.name,
        ledger_root=Path(plan["ledger_root"]).resolve(),
    )
    target_date = date_from_event_slug(paths["gzip"].parent.name)
    as_of = _parse_date(plan["as_of_date"])
    minimum_age = int(
        (plan.get("hot_window") or {}).get(
            "configured_hot_window_days"
        )
    )
    if (
        target_date is None
        or target_date >= as_of
        or (as_of - target_date).days < minimum_age
    ):
        raise ProjectionTieringError(
            "completed warm action is not outside its approved hot window"
        )
    return {
        "status": "PASS",
        "verified_at_utc": utc_iso(),
        "source_absent": True,
        "gzip": current_gzip,
        "gzip_payload": payload,
        "manifest_hash": manifest.get("manifest_hash"),
        "manifest_validation": validation,
        "protection_rebind": protection_rebind,
        "writer_locks_absent": True,
    }


def apply_approved_warm_plan(
    plan: dict[str, Any],
    *,
    generated_at_utc: str | None = None,
    manifest_validator: Callable[..., dict[str, Any]] | None = None,
    manifest_refresher: Callable[..., dict[str, Any]] | None = None,
    persist_receipt: Callable[[dict[str, Any]], None] | None = None,
    receipt_json_path: str | Path | None = None,
    receipt_report_path: str | Path | None = None,
    approved_manifest_identity: dict[str, Any] | None = None,
    existing_receipt: dict[str, Any] | None = None,
    today_utc: date | None = None,
) -> dict[str, Any]:
    """Apply an approved canonical warm plan with durable checkpoints."""

    errors = _approved_warm_plan_errors(
        plan,
        today_utc=today_utc,
    )
    errors.extend(
        _approved_manifest_identity_errors(
            plan,
            approved_manifest_identity,
        )
    )
    snapshots_value = str(plan.get("snapshots_root") or "")
    snapshots_root = (
        Path(snapshots_value).resolve()
        if snapshots_value
        else Path.cwd().resolve()
    )
    errors.extend(
        _receipt_path_errors(
            snapshots_root=snapshots_root,
            receipt_json_path=receipt_json_path,
            receipt_report_path=receipt_report_path,
        )
    )
    if persist_receipt is None:
        errors.append(
            "durable JSON+Markdown receipt persistence is required before "
            "warm apply"
        )

    json_path = (
        Path(receipt_json_path).resolve()
        if receipt_json_path is not None
        else None
    )
    report_path = (
        Path(receipt_report_path).resolve()
        if receipt_report_path is not None
        else None
    )
    approved_path = (
        Path(str((approved_manifest_identity or {}).get("path"))).resolve()
        if (approved_manifest_identity or {}).get("path")
        else None
    )
    if (
        json_path is not None
        and report_path is not None
        and approved_path is not None
        and approved_path in {json_path, report_path}
    ):
        raise ProjectionTieringError(
            "warm receipt paths must not overwrite the exact approved manifest"
        )
    if existing_receipt is None and any(
        path is not None and path.exists()
        for path in (json_path, report_path)
    ):
        raise ProjectionTieringError(
            "warm receipt target already exists without a verified resumable "
            "receipt"
        )
    if existing_receipt is not None:
        binding_errors = _existing_warm_receipt_binding_errors(
            existing_receipt,
            plan=plan,
            approved_manifest_identity=approved_manifest_identity,
        )
        if binding_errors:
            raise ProjectionTieringError(
                "refusing to overwrite unbound existing warm receipt: "
                f"{binding_errors}"
            )
        if json_path is None or report_path is None:
            raise ProjectionTieringError(
                "existing warm receipt requires exact JSON+Markdown paths"
            )
        loaded_receipt, _ = _read_verified_warm_receipt_files(
            receipt_json_path=json_path,
            receipt_report_path=report_path,
        )
        if loaded_receipt != existing_receipt:
            raise ProjectionTieringError(
                "existing warm receipt argument does not match its durable "
                "JSON+Markdown checkpoint"
            )

    receipt = (
        existing_receipt
        if existing_receipt is not None
        else {
            "schema_version": WARM_RECEIPT_SCHEMA_VERSION,
            "generated_at_utc": generated_at_utc or utc_iso(),
            "writer": WRITER,
            "mode": "warm_apply",
            "status": "BLOCK" if errors else "RUNNING",
            "plan_hash": plan.get("plan_hash"),
            "snapshots_root": plan.get("snapshots_root"),
            "approved_manifest_identity": approved_manifest_identity,
            "operator_review": dict(plan.get("operator_review") or {}),
            "approval_errors": errors,
            "stop_on_first_failure": True,
            "actions": [],
        }
    )
    actions = list(plan.get("actions") or [])
    _update_warm_apply_summary(receipt, planned=len(actions))

    def _persist() -> dict[str, Any]:
        if (
            persist_receipt is None
            or json_path is None
            or report_path is None
        ):
            raise ProjectionTieringError(
                "durable warm receipt persistence is unavailable"
            )
        return _persist_verified_receipt(
            receipt,
            persist_receipt=persist_receipt,
            receipt_json_path=json_path,
            receipt_report_path=report_path,
        )

    if errors:
        receipt["status"] = "BLOCK"
        receipt["approval_errors"] = errors
        _update_warm_apply_summary(receipt, planned=len(actions))
        if (
            persist_receipt is not None
            and json_path is not None
            and report_path is not None
            and not _receipt_path_errors(
                snapshots_root=snapshots_root,
                receipt_json_path=json_path,
                receipt_report_path=report_path,
            )
        ):
            _persist()
        return receipt

    receipt["status"] = "RUNNING"
    receipt["approval_errors"] = []
    _persist()
    validator = manifest_validator or validate_event_day_manifest
    refresher = manifest_refresher
    existing_by_id = {
        str(row.get("action_id") or ""): row
        for row in receipt.get("actions") or []
    }
    for index, action in enumerate(actions):
        action_id = str(action.get("action_id") or "")
        action_receipt = existing_by_id.get(action_id)
        if action_receipt is None:
            action_receipt = {
                "action_id": action_id,
                "warm_family": action.get("warm_family"),
                "source": action.get("source"),
                "status": "RUNNING",
            }
            receipt["actions"].append(action_receipt)
        was_completed = (
            action_receipt.get("status") == "APPLIED"
            or action_receipt.get("resume_state") == "APPLIED"
        )
        previous_status = str(
            action_receipt.get("resume_state")
            or action_receipt.get("status")
            or ""
        )
        if not was_completed:
            action_receipt.pop("failure", None)
            action_receipt.pop("failure_state", None)
            action_receipt["status"] = "RUNNING"
        _update_warm_apply_summary(receipt, planned=len(actions))
        _persist()
        try:
            if was_completed:
                action_receipt["completed_state_reverification"] = (
                    _verify_completed_warm_action(
                        plan,
                        action,
                        action_receipt,
                        snapshots_root=snapshots_root,
                        manifest_validator=validator,
                    )
                )
                action_receipt["status"] = "APPLIED"
                action_receipt.pop("resume_state", None)
                action_receipt.pop("failure", None)
                action_receipt.pop("failure_state", None)
            else:
                paths = _assert_warm_action_shape(action, snapshots_root)
                if not paths["source"].exists():
                    if previous_status not in {
                        "UNLINK_PENDING",
                        "MANIFEST_REFRESH_PENDING",
                    } and not action_receipt.get(
                        "event_day_manifest_refresh_required"
                    ):
                        raise ProjectionTieringError(
                            "plain source is absent without a recoverable "
                            "durable warm receipt state"
                        )
                    _recover_warm_manifest_refresh(
                        plan,
                        action,
                        action_receipt,
                        snapshots_root=snapshots_root,
                        manifest_validator=validator,
                        manifest_refresher=refresher,
                        persist_checkpoint=_persist,
                    )
                else:
                    _apply_one_warm(
                        plan,
                        action,
                        action_receipt,
                        snapshots_root=snapshots_root,
                        manifest_validator=validator,
                        manifest_refresher=refresher,
                        persist_checkpoint=_persist,
                    )
        except Exception as exc:  # noqa: BLE001 - persist fail-closed receipt
            action_receipt["resume_state"] = action_receipt.get("status")
            action_receipt["status"] = "BLOCK"
            action_receipt["failure"] = {
                "type": type(exc).__name__,
                "detail": str(exc),
            }
            try:
                paths = _assert_warm_action_shape(
                    action,
                    snapshots_root,
                )
                action_receipt["failure_state"] = {
                    "source_exists": paths["source"].exists(),
                    "gzip_exists": paths["gzip"].exists(),
                }
            except Exception:
                action_receipt["failure_state"] = {
                    "source_exists": None,
                    "gzip_exists": None,
                }
            receipt["status"] = "BLOCK"
            receipt["stopped_at_action_index"] = index
            _update_warm_apply_summary(receipt, planned=len(actions))
            _persist()
            break
        _update_warm_apply_summary(receipt, planned=len(actions))
        _persist()
    else:
        receipt["status"] = "PASS"

    _update_warm_apply_summary(receipt, planned=len(actions))
    _persist()
    return receipt


def _reference_csv_identity(path: Path) -> dict[str, Any]:
    if path.name.endswith(".csv.gz"):
        payload = _gzip_payload_identity(path)
        return {
            "path": str(path),
            "bytes": payload["payload_bytes"],
            "sha256": payload["payload_sha256"],
            "line_count": payload["payload_line_count"],
            "mode": "gzip_tiered_text",
        }
    identity = _file_identity(path)
    with path.open("rb") as handle:
        line_count = sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1024 * 1024), b""))
    return {
        "path": str(path),
        "bytes": identity["bytes"],
        "sha256": identity["sha256"],
        "line_count": line_count,
        "mode": "text_tape",
    }


def rebuild_one_order_books_long(
    folder: str | Path,
    *,
    output_root: str | Path,
    protected_roots: Iterable[str | Path] = (),
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Rebuild one long table from raw JSONL and prove exact byte parity."""

    _assert_no_lexical_reparse_points(folder, "rebuild source folder")
    _assert_no_lexical_reparse_points(output_root, "rebuild output root")
    source_folder = Path(folder).resolve()
    output = Path(output_root).resolve()
    _assert_output_root_is_external(
        output,
        [
            data_root_for_snapshots(source_folder.parent),
            *protected_roots,
        ],
    )
    try:
        raw_resolution = resolve_tiered_text(
            source_folder / ORDER_BOOK_RAW
        )
        reference_resolution = resolve_tiered_text(
            source_folder / ORDER_BOOK_LONG
        )
    except (TieredTextError, OSError, ValueError) as exc:
        raise ProjectionTieringError(
            f"tiered rebuild source is unavailable or conflicting: {exc}"
        ) from exc
    raw = raw_resolution.selected_path
    reference = reference_resolution.selected_path
    for path in (raw, reference):
        if not path.is_file() or _is_reparse_point(path):
            raise ProjectionTieringError(
                f"regular tiered rebuild input is required: {path}"
            )

    destination_dir = output / "rebuild-one" / _safe_event_slug(source_folder.name)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / ORDER_BOOK_LONG
    temporary = destination.with_name(f".{destination.name}.tmp")
    if destination.exists() or temporary.exists():
        raise ProjectionTieringError(
            f"rebuild output already exists; refusing overwrite: {destination}"
        )

    raw_rows = 0
    rebuilt_rows = 0
    try:
        with open_tiered_text(raw, encoding="utf-8") as raw_handle, temporary.open(
            "x",
            encoding="utf-8",
            newline="",
        ) as output_handle:
            writer = csv.DictWriter(
                output_handle,
                fieldnames=BOOK_LEVEL_COLUMNS,
                extrasaction="ignore",
                restval="",
            )
            writer.writeheader()
            for line_number, line in enumerate(raw_handle, start=1):
                if not line.strip():
                    continue
                raw_rows += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProjectionTieringError(
                        f"invalid order_books.jsonl line {line_number}: {exc}"
                    ) from exc
                if not isinstance(record, dict):
                    raise ProjectionTieringError(
                        f"order_books.jsonl line {line_number} is not an object"
                    )
                book = record.get("book")
                token = record.get("token")
                capture_id = record.get("capture_id")
                if not isinstance(book, dict) or not isinstance(token, dict) or not capture_id:
                    raise ProjectionTieringError(
                        f"order_books.jsonl line {line_number} lacks book/token/capture_id"
                    )
                rows = order_book_level_rows(
                    book,
                    token,
                    _parse_datetime(record.get("captured_at_utc")),
                    str(capture_id),
                )
                writer.writerows(normalize_csv_row(row) for row in rows)
                rebuilt_rows += len(rows)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        if (
            temporary.exists()
            and temporary.is_file()
            and not _is_reparse_point(temporary)
        ):
            temporary.unlink()
        raise

    rebuilt_identity = _reference_csv_identity(destination)
    reference_identity = _reference_csv_identity(reference)
    parity = (
        rebuilt_identity["bytes"] == reference_identity["bytes"]
        and rebuilt_identity["sha256"] == reference_identity["sha256"]
        and rebuilt_identity["line_count"] == reference_identity["line_count"]
    )
    return {
        "schema_version": REBUILD_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "writer": WRITER,
        "mode": "rebuild_one",
        "status": "PASS" if parity else "BLOCK",
        "projection_family": "order_books_long",
        "source_folder": str(source_folder),
        "canonical_rebuild_source": _file_identity(raw),
        "reference": reference_identity,
        "rebuilt": rebuilt_identity,
        "raw_record_count": raw_rows,
        "rebuilt_row_count": rebuilt_rows,
        "parity": {
            "status": "PASS" if parity else "BLOCK",
            "bytes_equal": rebuilt_identity["bytes"] == reference_identity["bytes"],
            "sha256_equal": rebuilt_identity["sha256"] == reference_identity["sha256"],
            "line_count_equal": (
                rebuilt_identity["line_count"] == reference_identity["line_count"]
            ),
            "ordered_columns": list(BOOK_LEVEL_COLUMNS),
        },
    }


def render_report(payload: dict[str, Any]) -> str:
    mode = str(payload.get("mode") or "unknown")
    warm = (
        payload.get("plan_kind") == "canonical_warm_compression"
        or mode == "warm_apply"
    )
    subject = "Warm Tiering" if warm else "Projection Tiering"
    lines = [
        f"# Closed-Day {subject} - {mode}",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: **{payload.get('status')}**",
        f"Writer: `{payload.get('writer')}`",
        "",
    ]
    if mode == "dry_run":
        summary = payload.get("summary") or {}
        lines.extend(
            [
                "## Dry-run summary",
                "",
                "| Metric | Value |",
                "| --- | ---: |",
                f"| Folders | {summary.get('folder_count', 0)} |",
                f"| Eligible actions | {summary.get('eligible_action_count', 0)} |",
                f"| Blocked folders | {summary.get('blocked_folder_count', 0)} |",
                f"| Inside hot window | {summary.get('inside_hot_window_count', 0)} |",
                f"| Already warm | {summary.get('already_warm_count', 0)} |",
                f"| Planned source bytes | {summary.get('planned_source_bytes', 0)} |",
                "",
                "## Family registry",
                "",
            ]
        )
        if warm:
            lines.extend(
                [
                    "| Family | Eligible | Source -> gzip | Readers | Blocker |",
                    "| --- | --- | --- | ---: | --- |",
                ]
            )
            for row in payload.get("warm_compression_family_registry") or []:
                lines.append(
                    "| {family} | {eligible} | {source} -> {gzip} | "
                    "{readers} | {blocker} |".format(
                        family=row.get("family"),
                        eligible=row.get("eligible"),
                        source=row.get("source_file"),
                        gzip=row.get("gzip_file"),
                        readers=len(row.get("readers") or []),
                        blocker=row.get("blocker") or "-",
                    )
                )
            window = payload.get("hot_window") or {}
            lines.extend(
                [
                    "",
                    "## Hot-window proof",
                    "",
                    "| Configured | Minimum | Recovery margin | Binding consumer |",
                    "| ---: | ---: | ---: | --- |",
                    f"| {window.get('configured_hot_window_days')} | "
                    f"{window.get('minimum_warm_age_days')} | "
                    f"{window.get('default_recovery_margin_days')} | "
                    f"{window.get('binding_consumer')} |",
                ]
            )
        else:
            lines.extend(
                [
                    "| Family | Eligible | Canonical rebuild source | Accepted reads | Blocker |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for row in payload.get("projection_family_registry") or []:
                lines.append(
                    "| {family} | {eligible} | {sources} | {reads} | {blocker} |".format(
                        family=row.get("family"),
                        eligible=row.get("eligible"),
                        sources="<br>".join(
                            row.get("canonical_rebuild_sources") or []
                        ),
                        reads="<br>".join(
                            row.get("accepted_read_representations") or []
                        ),
                        blocker=row.get("blocker") or "-",
                    )
                )
        lines.extend(
            [
                "",
                "## Folder decisions",
                "",
                "| Event | Status | Action | Blockers |",
                "| --- | --- | --- | --- |",
            ]
        )
        for row in payload.get("folders") or []:
            lines.append(
                f"| {row.get('event_slug')} | {row.get('status')} | "
                f"{row.get('action_id') or '-'} | "
                f"{'; '.join(row.get('blockers') or []) or '-'} |"
            )
        lines.extend(
            [
                "",
                "## Operator review",
                "",
                "Apply remains blocked until `operator_review` is completed externally "
                "and `approved_plan_hash` exactly equals the plan hash.",
            ]
        )
    elif mode in {"apply", "warm_apply"}:
        summary = payload.get("summary") or {}
        lines.extend(
            [
                "## Apply summary",
                "",
                "| Planned | Attempted | Applied | Failed | Not attempted |",
                "| ---: | ---: | ---: | ---: | ---: |",
                f"| {summary.get('planned', 0)} | {summary.get('attempted', 0)} | "
                f"{summary.get('applied', 0)} | {summary.get('failed', 0)} | "
                f"{summary.get('not_attempted', 0)} |",
                "",
                "## Per-action receipt",
                "",
                "| Action | Family | Source | Status | Failure |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in payload.get("actions") or []:
            family = row.get("warm_family") or row.get("projection_family")
            lines.append(
                f"| {row.get('action_id')} | {family} | "
                f"{(row.get('source') or {}).get('path')} | {row.get('status')} | "
                f"{(row.get('failure') or {}).get('detail') or '-'} |"
            )
    elif mode == "rebuild_one":
        parity = payload.get("parity") or {}
        lines.extend(
            [
                "## Rebuild parity",
                "",
                "| Field | Value |",
                "| --- | --- |",
                f"| Canonical source | {(payload.get('canonical_rebuild_source') or {}).get('path')} |",
                f"| Reference | {(payload.get('reference') or {}).get('path')} |",
                f"| Rebuilt | {(payload.get('rebuilt') or {}).get('path')} |",
                f"| Rows | {payload.get('rebuilt_row_count')} |",
                f"| Bytes equal | {parity.get('bytes_equal')} |",
                f"| SHA-256 equal | {parity.get('sha256_equal')} |",
                f"| Line count equal | {parity.get('line_count_equal')} |",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _atomic_write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        raise ProjectionTieringError(f"output temporary file exists: {temporary}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        if (
            temporary.exists()
            and temporary.is_file()
            and not _is_reparse_point(temporary)
        ):
            temporary.unlink()
        raise
    return path


def write_outputs(
    payload: dict[str, Any],
    *,
    output_root: str | Path,
    stem: str,
    protected_root: str | Path | Iterable[str | Path],
) -> tuple[Path, Path]:
    _assert_output_root_is_external(
        Path(output_root),
        protected_root,
    )
    output = Path(output_root).resolve()
    json_path = output / f"{stem}.json"
    report_path = output / f"{stem}.md"
    _atomic_write_text(
        json_path,
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
    )
    _atomic_write_text(report_path, render_report(payload))
    return json_path, report_path


def make_receipt_persister(
    *,
    output_root: str | Path,
    stem: str,
    protected_root: str | Path | Iterable[str | Path],
) -> tuple[Callable[[dict[str, Any]], None], Path, Path]:
    """Return an atomic JSON+Markdown writer suitable for apply checkpoints."""

    _assert_output_root_is_external(
        Path(output_root),
        protected_root,
    )
    output = Path(output_root).resolve()
    json_path = output / f"{stem}.json"
    report_path = output / f"{stem}.md"

    def _persist(payload: dict[str, Any]) -> None:
        # The JSON file is the checkpoint commit marker. Publish the rendered
        # companion first so a committed JSON checkpoint never points at an
        # older Markdown receipt.
        _atomic_write_text(report_path, render_report(payload))
        _atomic_write_text(
            json_path,
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        )

    return _persist, json_path, report_path


def _read_json_with_identity(
    path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read and hash the exact approved-manifest bytes in one stable handle."""

    manifest_path = Path(path)
    if _is_reparse_point(manifest_path):
        raise ProjectionTieringError(
            "approved manifest must not be a symlink or reparse point"
        )
    with manifest_path.open("rb") as handle:
        initial = os.fstat(handle.fileno())
        raw = handle.read()
        final = os.fstat(handle.fileno())
    stat_fields = ("st_size", "st_mtime_ns", "st_dev", "st_ino")
    if any(getattr(initial, field) != getattr(final, field) for field in stat_fields):
        raise ProjectionTieringError(
            "approved manifest changed while it was being read"
        )
    def reject_duplicates(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"duplicate JSON key {key!r}")
            payload[key] = value
        return payload

    def reject_non_finite(value):
        raise ValueError(f"non-finite JSON constant {value!r}")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_non_finite,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProjectionTieringError(
            f"approved manifest is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProjectionTieringError("manifest must contain one JSON object")
    identity = {
        "path": str(manifest_path.resolve()),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mtime_ns": int(final.st_mtime_ns),
        "device": int(final.st_dev),
        "inode": int(final.st_ino),
    }
    return payload, identity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run-first closed-day projection and canonical warm tiering. "
            "The default command is plan; every apply requires an externally "
            "approved plan manifest."
        )
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("plan", "apply", "warm-plan", "warm-apply", "rebuild-one"),
        default="plan",
    )
    parser.add_argument("--snapshots-root")
    parser.add_argument("--event-slug", action="append", default=[])
    parser.add_argument("--as-of-date")
    parser.add_argument("--approved-manifest")
    parser.add_argument("--folder")
    parser.add_argument("--ledger-root")
    parser.add_argument(
        "--hot-window-days",
        type=int,
        default=DEFAULT_HOT_WINDOW_DAYS,
        help=(
            "Warm-plan retention window in days; cannot be below the "
            f"code-derived minimum of {MIN_WARM_AGE_DAYS} "
            f"(default: {DEFAULT_HOT_WINDOW_DAYS})."
        ),
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--protected-root",
        action="append",
        required=True,
        help=(
            "Explicit data or mirror root protected from output writes; repeat "
            "for every source and mirror boundary."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "plan":
        if not args.snapshots_root or not args.as_of_date:
            parser.error("plan requires --snapshots-root and --as-of-date")
        payload = build_plan(
            args.snapshots_root,
            as_of_date=args.as_of_date,
            event_slugs=args.event_slug,
            ledger_root=args.ledger_root,
        )
        json_path, report_path = write_outputs(
            payload,
            output_root=args.output_root,
            stem="closed_day_projection_tiering_plan",
            protected_root=[
                data_root_for_snapshots(args.snapshots_root),
                *args.protected_root,
            ],
        )
    elif args.command == "warm-plan":
        if not args.snapshots_root or not args.as_of_date:
            parser.error(
                "warm-plan requires --snapshots-root and --as-of-date"
            )
        payload = build_warm_plan(
            args.snapshots_root,
            as_of_date=args.as_of_date,
            hot_window_days=args.hot_window_days,
            event_slugs=args.event_slug,
            ledger_root=args.ledger_root,
        )
        json_path, report_path = write_outputs(
            payload,
            output_root=args.output_root,
            stem="closed_day_warm_tiering_plan",
            protected_root=[
                data_root_for_snapshots(args.snapshots_root),
                *args.protected_root,
            ],
        )
    elif args.command == "apply":
        if not args.approved_manifest:
            parser.error("apply requires --approved-manifest")
        _assert_no_lexical_reparse_points(
            args.approved_manifest,
            "approved manifest",
        )
        approved_manifest_path = Path(args.approved_manifest).resolve()
        approved_plan, approved_manifest_identity = _read_json_with_identity(
            approved_manifest_path
        )
        approved_snapshots_root = approved_plan.get("snapshots_root")
        if not isinstance(approved_snapshots_root, str) or not approved_snapshots_root:
            raise ProjectionTieringError(
                "approved manifest snapshots_root is required before receipt setup"
            )
        _assert_no_lexical_reparse_points(
            approved_snapshots_root,
            "approved snapshots root",
        )
        persist, json_path, report_path = make_receipt_persister(
            output_root=args.output_root,
            stem="closed_day_projection_tiering_apply_receipt",
            # Never trust the manifest's claimed data_root to establish the
            # write boundary. Derive it from the snapshots root and let apply
            # reject any inconsistent claimed data_root afterward.
            protected_root=[
                data_root_for_snapshots(approved_snapshots_root),
                *args.protected_root,
            ],
        )
        payload = apply_approved_plan(
            approved_plan,
            persist_receipt=persist,
            approved_manifest_identity=approved_manifest_identity,
        )
    elif args.command == "warm-apply":
        if not args.approved_manifest:
            parser.error("warm-apply requires --approved-manifest")
        _assert_no_lexical_reparse_points(
            args.approved_manifest,
            "approved warm manifest",
        )
        approved_manifest_path = Path(args.approved_manifest).resolve()
        approved_plan, approved_manifest_identity = _read_json_with_identity(
            approved_manifest_path
        )
        approved_snapshots_root = approved_plan.get("snapshots_root")
        if (
            not isinstance(approved_snapshots_root, str)
            or not approved_snapshots_root
        ):
            raise ProjectionTieringError(
                "approved warm manifest snapshots_root is required before "
                "receipt setup"
            )
        _assert_no_lexical_reparse_points(
            approved_snapshots_root,
            "approved warm snapshots root",
        )
        persist, json_path, report_path = make_receipt_persister(
            output_root=args.output_root,
            stem="closed_day_warm_tiering_apply_receipt",
            protected_root=[
                data_root_for_snapshots(approved_snapshots_root),
                *args.protected_root,
            ],
        )
        receipt_lock = acquire_writer_lock(
            json_path,
            owner={
                "resource": "closed_day_warm_tiering_apply_receipt",
                "operation": "warm_apply",
                "plan_hash": approved_plan.get("plan_hash"),
            },
            attempts=1,
            stale_after_seconds=float("inf"),
            sleep_seconds=0.0,
        )
        if receipt_lock is None:
            raise ProjectionTieringError(
                "another warm-apply process owns the receipt checkpoint"
            )
        try:
            existing_receipt = None
            if json_path.exists():
                existing_receipt, _ = _read_json_with_identity(json_path)
            payload = apply_approved_warm_plan(
                approved_plan,
                persist_receipt=persist,
                receipt_json_path=json_path,
                receipt_report_path=report_path,
                approved_manifest_identity=approved_manifest_identity,
                existing_receipt=existing_receipt,
            )
        finally:
            release_writer_lock(receipt_lock)
    else:
        if not args.folder:
            parser.error("rebuild-one requires --folder")
        payload = rebuild_one_order_books_long(
            args.folder,
            output_root=args.output_root,
            protected_roots=args.protected_root,
        )
        json_path, report_path = write_outputs(
            payload,
            output_root=args.output_root,
            stem="closed_day_projection_rebuild_one",
            protected_root=[
                data_root_for_snapshots(Path(args.folder).resolve().parent),
                *args.protected_root,
            ],
        )
    print(f"Closed-day tiering {payload['mode']}: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Markdown written to {report_path}")
    return 0 if payload.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
