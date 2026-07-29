"""Manual, fail-closed tiering for finalized closed-day projections.

The command is deliberately dry-run-first:

* ``plan`` (also the default command) only reads snapshot folders and writes an
  operator-review manifest outside the snapshot tree.
* ``apply`` requires that manifest to have been externally edited with an
  operator approval bound to the immutable plan hash.
* ``rebuild-one`` reconstructs one ``order_books_long.csv`` outside the
  snapshot tree and proves byte parity with the retained projection.

Only ``order_books_long`` is eligible.  Every other family in
``closed_market_day_archive.ARTIFACT_FAMILIES`` is represented explicitly and
blocked until its canonical rebuild and all gzip reader fallbacks are proven.
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
    acquire_writer_lock,
    normalize_csv_row,
    release_writer_lock,
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
    PROJECTION_FAMILIES_BY_NAME,
    ProjectionFamilyContract,
    projection_family_registry,
    registry_hash,
    validate_projection_family_registry,
)
from weather.operations.event_day_manifest import (
    event_day_manifest_path,
    manifest_hash_valid,
    read_event_day_manifest,
    validate_deletion_candidates,
    validate_event_day_manifest,
    write_event_day_manifest,
)
from weather.operations.storage_classes import classification_payload
from weather.schema_registry import schema_version


PLAN_SCHEMA_VERSION = schema_version("closed_day_projection_tiering_plan")
RECEIPT_SCHEMA_VERSION = schema_version(
    "closed_day_projection_tiering_receipt"
)
REBUILD_SCHEMA_VERSION = schema_version("closed_day_projection_rebuild")
WRITER = "weather.operations.closed_day_projection_tiering"

RAW_TAPE_WRITER_LOCK = ".clob_raw_tape.writer.lock"


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
    raw = folder / ORDER_BOOK_RAW
    for path, reason in (
        (source, "order_books_long_csv_missing"),
        (raw, "canonical_order_books_jsonl_missing"),
    ):
        if not path.exists():
            blockers.append(reason)
        elif not path.is_file() or _is_reparse_point(path):
            blockers.append(f"{reason}_or_not_regular_file")
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

    if blockers or manifest is None or finalization_proof is None:
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
            ORDER_BOOK_RAW,
            {**raw_identity, "path": ORDER_BOOK_RAW},
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
            "deterministic gzip verification; retain gzip and canonical raw JSONL"
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
                "while retaining order_books_long.csv.gz and order_books.jsonl"
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
        if gzip_path.exists():
            expected = action["gzip"].get("identity")
            if not action["gzip"].get("preexisting") or not expected:
                raise ProjectionTieringError(
                    "gzip appeared after planning; refusing to overwrite"
                )
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
    if raw.name != ORDER_BOOK_RAW:
        raise ProjectionTieringError("canonical source must be exact order_books.jsonl")
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
        ORDER_BOOK_RAW,
        {**raw_identity, "path": ORDER_BOOK_RAW},
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
    if not {ORDER_BOOK_LONG_GZIP, ORDER_BOOK_RAW}.issubset(refreshed_paths):
        raise ProjectionTieringError(
            "refreshed event manifest lacks retained gzip or canonical raw source"
        )
    if (
        (folder / ORDER_BOOK_LONG).exists()
        or not (folder / ORDER_BOOK_LONG_GZIP).is_file()
        or not (folder / ORDER_BOOK_RAW).is_file()
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
        "canonical_raw_present": (folder / ORDER_BOOK_RAW).is_file(),
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
    raw = source_folder / ORDER_BOOK_RAW
    if not raw.exists() or not raw.is_file() or _is_reparse_point(raw):
        raise ProjectionTieringError(f"canonical raw source is unavailable: {raw}")
    reference = source_folder / ORDER_BOOK_LONG
    if not reference.exists():
        reference = source_folder / ORDER_BOOK_LONG_GZIP
    if (
        not reference.exists()
        or not reference.is_file()
        or _is_reparse_point(reference)
    ):
        raise ProjectionTieringError(
            "order_books_long.csv or order_books_long.csv.gz is required for parity"
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
        with raw.open("r", encoding="utf-8") as raw_handle, temporary.open(
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
    lines = [
        f"# Closed-Day Projection Tiering — {mode}",
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
                f"| Planned source bytes | {summary.get('planned_source_bytes', 0)} |",
                "",
                "## Family registry",
                "",
                "| Family | Eligible | Canonical rebuild source | Accepted reads | Blocker |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in payload.get("projection_family_registry") or []:
            lines.append(
                "| {family} | {eligible} | {sources} | {reads} | {blocker} |".format(
                    family=row.get("family"),
                    eligible=row.get("eligible"),
                    sources="<br>".join(row.get("canonical_rebuild_sources") or []),
                    reads="<br>".join(row.get("accepted_read_representations") or []),
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
    elif mode == "apply":
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
            lines.append(
                f"| {row.get('action_id')} | {row.get('projection_family')} | "
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
        _atomic_write_text(
            json_path,
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        )
        _atomic_write_text(report_path, render_report(payload))

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
            "Dry-run-first closed-day projection tiering. The default command "
            "is plan; apply requires an externally approved plan manifest."
        )
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("plan", "apply", "rebuild-one"),
        default="plan",
    )
    parser.add_argument("--snapshots-root")
    parser.add_argument("--event-slug", action="append", default=[])
    parser.add_argument("--as-of-date")
    parser.add_argument("--approved-manifest")
    parser.add_argument("--folder")
    parser.add_argument("--ledger-root")
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
    print(f"Closed-day projection tiering {payload['mode']}: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Markdown written to {report_path}")
    return 0 if payload.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
