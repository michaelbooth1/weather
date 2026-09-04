"""Verified, create-only cold archives for one synthetic market-day fixture.

This module is intentionally unable to operate on the repository ``data/``
tree or an unmarked root.  Production selection evidence and cloud transport
remain separate adapters.  The only mutating surfaces here create immutable
archive objects, verification/restore receipts, scratch restores, and reviewed
cleanup manifests under a marked synthetic fixture root.  There is no source
unlink or deletion executor.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import stat
import subprocess
import tarfile
import time
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from weather.io import sha256_file
from weather.market.market_config import date_from_event_slug, market_id_from_slug
from weather.operations.cleanup_preflight import (
    CLEANUP_MANIFEST_SCHEMA_VERSION,
    cleanup_manifest_for_paths,
)
from weather.operations.event_day_manifest import (
    MANIFEST_FILENAME as EVENT_DAY_MANIFEST_FILENAME,
    manifest_hash_valid as event_day_manifest_hash_valid,
    validate_event_day_manifest,
)
from weather.operations.release_manifest import capture_code_identity
from weather.paths import DATA_ROOT, REPO_ROOT
from weather.schema_registry import schema_version


SELECTION_PROOF_SCHEMA_VERSION = schema_version(
    "verified_cold_archive_selection_proof"
)
PLAN_SCHEMA_VERSION = schema_version("verified_cold_archive_plan")
MANIFEST_SCHEMA_VERSION = schema_version("verified_cold_archive_manifest")
VERIFICATION_RECEIPT_SCHEMA_VERSION = schema_version(
    "verified_cold_archive_verification_receipt"
)
RESTORE_RECEIPT_SCHEMA_VERSION = schema_version(
    "verified_cold_archive_restore_receipt"
)

ARCHIVE_FORMAT = schema_version("verified_cold_archive_format")
TOOL = "weather.operations.verified_cold_archive"
FIXTURE_MARKER = ".verified-cold-archive-fixture-root.json"
FIXTURE_ROOT_PREFIX = "vca-"
FIXTURE_MARKER_PURPOSE = "synthetic_tmp_path_fixture_only"
DEFAULT_HOT_WINDOW_DAYS = 30
MINIMUM_HOT_WINDOW_DAYS = 30
HASH_BLOCK_SIZE = 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_SELECTION_CHECKS = (
    "market_day_closed",
    "settlement_final",
    "barriers_clear",
    "queues_clear",
    "point_in_time_windows_clear",
)
FINAL_SETTLEMENT_STATES = frozenset(
    {"settled_countable", "settled_non_countable"}
)


class ColdArchiveError(RuntimeError):
    """A fail-closed verified cold-archive contract violation."""


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _content_hash(payload: Mapping[str, Any], hash_key: str) -> str:
    unsigned = dict(payload)
    unsigned.pop(hash_key, None)
    return hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()


def _hash_is_valid(payload: Mapping[str, Any], hash_key: str) -> bool:
    declared = str(payload.get(hash_key) or "")
    return bool(SHA256_RE.fullmatch(declared)) and declared == _content_hash(
        payload, hash_key
    )


def _nonnegative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ColdArchiveError(f"{label} must be a non-negative integer")
    if value < 0:
        raise ColdArchiveError(f"{label} must be a non-negative integer")
    return value


def _iso_date(value: Any, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ColdArchiveError(f"{label} must be ISO YYYY-MM-DD") from exc


def selection_proof_content_hash(payload: Mapping[str, Any]) -> str:
    return _content_hash(payload, "proof_hash")


def plan_content_hash(payload: Mapping[str, Any]) -> str:
    return _content_hash(payload, "plan_hash")


def manifest_content_hash(payload: Mapping[str, Any]) -> str:
    return _content_hash(payload, "manifest_hash")


def verification_receipt_content_hash(payload: Mapping[str, Any]) -> str:
    return _content_hash(payload, "verification_receipt_hash")


def restore_receipt_content_hash(payload: Mapping[str, Any]) -> str:
    return _content_hash(payload, "restore_receipt_hash")


def cleanup_plan_content_hash(payload: Mapping[str, Any]) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key not in {"cleanup_plan_hash", "operator_review"}
    }
    return hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()


def _object_pairs_no_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ColdArchiveError(f"duplicate JSON key is not allowed: {key}")
        result[key] = value
    return result


def _read_json_strict(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_object_pairs_no_duplicates,
        )
    except ColdArchiveError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ColdArchiveError(f"unreadable JSON document: {source}") from exc
    if not isinstance(payload, dict):
        raise ColdArchiveError(f"JSON document must contain an object: {source}")
    return payload


def _write_json_create_only(path: str | Path, payload: Mapping[str, Any]) -> Path:
    destination = Path(path)
    _assert_no_reparse_components(destination.parent, "JSON destination parent")
    if not destination.parent.is_dir():
        raise ColdArchiveError(
            f"JSON destination parent must already exist: {destination.parent}"
        )
    encoded = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8") + b"\n"
    try:
        with destination.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ColdArchiveError(f"create-only collision: {destination}") from exc
    return destination


def _is_reparse_point(path: Path) -> bool:
    try:
        result = path.lstat()
    except OSError as exc:
        raise ColdArchiveError(f"cannot inspect path identity: {path}") from exc
    attributes = int(getattr(result, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(result.st_mode) or bool(attributes & reparse_flag)


def _absolute_lexical(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _assert_no_reparse_components(path: str | Path, label: str) -> None:
    lexical = _absolute_lexical(path)
    for component in [*reversed(lexical.parents), lexical]:
        if component.exists() and _is_reparse_point(component):
            raise ColdArchiveError(
                f"{label} contains a symlink or reparse point: {component}"
            )


def _strict_relative_path(value: str | Path, *, label: str) -> PurePosixPath:
    text = str(value or "")
    if "\\" in text:
        raise ColdArchiveError(f"{label} must use normalized POSIX separators")
    candidate = PurePosixPath(text)
    if (
        not text
        or candidate.is_absolute()
        or text != candidate.as_posix()
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or re.match(r"^[A-Za-z]:", text)
    ):
        raise ColdArchiveError(f"{label} must be a normalized relative path")
    return candidate


def _resolve_inside(
    root: str | Path,
    candidate: str | Path,
    *,
    label: str,
    allow_root: bool = False,
) -> Path:
    root_path = _absolute_lexical(root)
    raw_candidate = Path(candidate)
    if raw_candidate.drive and not raw_candidate.is_absolute():
        raise ColdArchiveError(f"{label} must not use a drive-relative path")
    candidate_path = _absolute_lexical(
        raw_candidate if raw_candidate.is_absolute() else root_path / raw_candidate
    )
    _assert_no_reparse_components(root_path, f"{label} root")
    _assert_no_reparse_components(candidate_path, label)
    try:
        root_resolved = root_path.resolve(strict=True)
        candidate_resolved = candidate_path.resolve(strict=False)
        relative = candidate_resolved.relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise ColdArchiveError(f"{label} escapes its required root") from exc
    if not allow_root and relative == Path("."):
        raise ColdArchiveError(f"{label} must be below its required root")
    return candidate_resolved


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve(strict=False)
    right = right.resolve(strict=False)
    return left == right or left in right.parents or right in left.parents


def _assert_not_repo_data(path: Path, label: str) -> None:
    candidate = path.resolve(strict=False)
    protected = DATA_ROOT.resolve(strict=False)
    if candidate == protected or protected in candidate.parents or candidate in protected.parents:
        raise ColdArchiveError(f"{label} must not overlap repository data/")


def validate_fixture_root(path: str | Path) -> Path:
    root = _absolute_lexical(path)
    _assert_no_reparse_components(root, "fixture root")
    if not root.is_dir() or not root.name.startswith(FIXTURE_ROOT_PREFIX):
        raise ColdArchiveError(
            f"fixture root must be an existing {FIXTURE_ROOT_PREFIX}* directory"
        )
    _assert_not_repo_data(root, "fixture root")
    marker_path = root / FIXTURE_MARKER
    if not marker_path.is_file() or _is_reparse_point(marker_path):
        raise ColdArchiveError(f"synthetic fixture marker is missing: {marker_path}")
    marker = _read_json_strict(marker_path)
    if marker != {
        "allow_real_data": False,
        "purpose": FIXTURE_MARKER_PURPOSE,
    }:
        raise ColdArchiveError("synthetic fixture marker content is invalid")
    return root.resolve(strict=True)


def _relative_to_fixture(path: Path, fixture_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(fixture_root).as_posix()
    except ValueError as exc:
        raise ColdArchiveError("path escapes synthetic fixture root") from exc


def _filesystem_identity(path: Path) -> dict[str, int]:
    try:
        result = path.stat()
    except OSError as exc:
        raise ColdArchiveError(f"cannot stat source file: {path}") from exc
    if not stat.S_ISREG(result.st_mode) or _is_reparse_point(path):
        raise ColdArchiveError(f"source member is not a regular non-link file: {path}")
    return {
        "device": int(result.st_dev),
        "inode": int(result.st_ino),
        "bytes": int(result.st_size),
        "mtime_ns": int(result.st_mtime_ns),
        "ctime_ns": int(result.st_ctime_ns),
    }


def _stable_file_record(path: Path, *, relative_to: Path) -> dict[str, Any]:
    before = _filesystem_identity(path)
    digest = sha256_file(path)
    after = _filesystem_identity(path)
    if before != after:
        raise ColdArchiveError(f"source changed while it was hashed: {path}")
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "bytes": before["bytes"],
        "sha256": digest,
        "filesystem_identity": before,
    }


def _source_inventory(folder: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for member in sorted(folder.rglob("*"), key=lambda item: item.relative_to(folder).as_posix()):
        if _is_reparse_point(member):
            raise ColdArchiveError(f"source tree contains a link or reparse point: {member}")
        try:
            mode = member.lstat().st_mode
        except OSError as exc:
            raise ColdArchiveError(f"cannot inspect source tree member: {member}") from exc
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ColdArchiveError(f"source tree contains a special file: {member}")
        records.append(_stable_file_record(member, relative_to=folder))
    second_paths = [
        member.relative_to(folder).as_posix()
        for member in sorted(folder.rglob("*"), key=lambda item: item.relative_to(folder).as_posix())
        if member.is_file()
    ]
    if second_paths != [record["path"] for record in records]:
        raise ColdArchiveError("source tree changed while it was inventoried")
    return records


def _identity_projection(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(record.get("path") or ""),
            "bytes": int(record.get("bytes") or 0),
            "sha256": str(record.get("sha256") or ""),
        }
        for record in records
    ]


def _read_stream_hash(handle) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    while True:
        block = handle.read(HASH_BLOCK_SIZE)
        if not block:
            break
        total += len(block)
        digest.update(block)
    return total, digest.hexdigest()


def _gzip_uncompressed_identity(path: Path) -> tuple[int, str]:
    try:
        with gzip.open(path, "rb") as handle:
            return _read_stream_hash(handle)
    except (OSError, EOFError) as exc:
        raise ColdArchiveError(f"split gzip representation is unreadable: {path}") from exc


def _validate_split_representations(
    folder: Path, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    by_path = {str(row["path"]): row for row in records}
    proofs: list[dict[str, Any]] = []
    for gzip_path in sorted(path for path in by_path if path.endswith(".gz")):
        plain_path = gzip_path[:-3]
        plain = by_path.get(plain_path)
        if plain is None:
            continue
        unpacked_bytes, unpacked_sha = _gzip_uncompressed_identity(folder / gzip_path)
        if (
            unpacked_bytes != int(plain["bytes"])
            or unpacked_sha != plain["sha256"]
        ):
            raise ColdArchiveError(
                "split representations cannot be proven byte-complete: "
                f"{plain_path} and {gzip_path}"
            )
        proofs.append(
            {
                "plain_path": plain_path,
                "gzip_path": gzip_path,
                "relationship": "gzip_expands_to_exact_plain_bytes",
                "uncompressed_bytes": unpacked_bytes,
                "uncompressed_sha256": unpacked_sha,
                "status": "PASS",
            }
        )
    return proofs


def _selection_check_rows(proof: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = proof.get("checks")
    if not isinstance(raw, list):
        raise ColdArchiveError("selection proof checks must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in raw:
        if not isinstance(row, dict):
            raise ColdArchiveError("selection proof check must be an object")
        name = str(row.get("check") or "")
        if name in result:
            raise ColdArchiveError(f"duplicate selection proof check: {name}")
        result[name] = row
    if set(result) != set(REQUIRED_SELECTION_CHECKS):
        raise ColdArchiveError("selection proof does not contain the exact required checks")
    return result


def _validate_selection_check_semantics(
    checks: Mapping[str, Mapping[str, Any]],
) -> None:
    for name in REQUIRED_SELECTION_CHECKS:
        if checks[name].get("status") != "PASS":
            raise ColdArchiveError(f"selection proof check did not pass: {name}")
    if checks["market_day_closed"].get("closed") is not True:
        raise ColdArchiveError("market day is not proven closed")
    settlement = checks["settlement_final"]
    if (
        settlement.get("settled") is not True
        or settlement.get("settlement_state") not in FINAL_SETTLEMENT_STATES
    ):
        raise ColdArchiveError("market day is active or unsettled")
    for name in (
        "barriers_clear",
        "queues_clear",
        "point_in_time_windows_clear",
    ):
        if checks[name].get("open_references") != []:
            raise ColdArchiveError(f"selection proof has open references: {name}")


def _validate_proof_evidence(
    rows: Mapping[str, Mapping[str, Any]], fixture_root: Path
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for check_name in REQUIRED_SELECTION_CHECKS:
        evidence = rows[check_name].get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ColdArchiveError(f"{check_name} has no required evidence identity")
        normalized_evidence: list[dict[str, Any]] = []
        for declared in evidence:
            if not isinstance(declared, dict):
                raise ColdArchiveError(f"{check_name} evidence must be an object")
            relative = _strict_relative_path(
                str(declared.get("path") or ""), label=f"{check_name} evidence path"
            )
            path = _resolve_inside(
                fixture_root,
                fixture_root.joinpath(*relative.parts),
                label=f"{check_name} evidence",
            )
            current = _stable_file_record(path, relative_to=fixture_root)
            expected = _validate_identity_record(
                declared, label=f"{check_name} evidence"
            )
            if _identity_projection([current])[0] != expected:
                raise ColdArchiveError(f"{check_name} evidence identity changed")
            normalized_evidence.append(expected)
        normalized.append({"check": check_name, "evidence": normalized_evidence})
    return normalized


def _validate_selection_proof(
    proof_path: Path,
    *,
    fixture_root: Path,
    source_folder_relative: str,
    event_slug: str,
    target_date: str,
    event_manifest_hash: str,
) -> dict[str, Any]:
    if not proof_path.is_file() or _is_reparse_point(proof_path):
        raise ColdArchiveError("required selection proof is absent or redirected")
    proof = _read_json_strict(proof_path)
    if proof.get("schema_version") != SELECTION_PROOF_SCHEMA_VERSION:
        raise ColdArchiveError("selection proof schema version is invalid")
    if not _hash_is_valid(proof, "proof_hash"):
        raise ColdArchiveError("selection proof hash is invalid")
    expected_source = {
        "event_day_manifest_hash": event_manifest_hash,
        "event_slug": event_slug,
        "source_folder": source_folder_relative,
        "target_date": target_date,
    }
    if proof.get("source") != expected_source:
        raise ColdArchiveError("selection proof source binding is invalid")
    checks = _selection_check_rows(proof)
    _validate_selection_check_semantics(checks)
    evidence = _validate_proof_evidence(checks, fixture_root)
    proof_record = _stable_file_record(proof_path, relative_to=fixture_root)
    return {
        "schema_version": SELECTION_PROOF_SCHEMA_VERSION,
        "path": proof_record["path"],
        "bytes": proof_record["bytes"],
        "sha256": proof_record["sha256"],
        "proof_hash": proof["proof_hash"],
        "checks": [dict(checks[name]) for name in REQUIRED_SELECTION_CHECKS],
        "evidence_identities": evidence,
    }


def _load_current_event_manifest(
    folder: Path, snapshots_root: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = folder / EVENT_DAY_MANIFEST_FILENAME
    if not manifest_path.is_file() or _is_reparse_point(manifest_path):
        raise ColdArchiveError("required event_day_manifest.json is absent")
    manifest = _read_json_strict(manifest_path)
    if not event_day_manifest_hash_valid(manifest):
        raise ColdArchiveError("event-day manifest hash is invalid")
    validation = validate_event_day_manifest(
        manifest,
        folder,
        snapshots_root=snapshots_root,
        check_hashes=True,
        check_row_counts=True,
        fail_on_extra=True,
    )
    if validation.get("status") != "PASS":
        raise ColdArchiveError("event-day manifest is incomplete or stale")
    if list(manifest.get("shared_payload_dependencies") or []):
        raise ColdArchiveError(
            "event-day archive has external shared payload dependencies and is not self-contained"
        )
    return manifest, validation


def _validate_tool_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "tool": TOOL,
        "archive_format": ARCHIVE_FORMAT,
        "git_dirty": False,
    }
    for key, expected in required.items():
        if identity.get(key) != expected:
            raise ColdArchiveError(f"tool identity field is invalid: {key}")
    commit = str(identity.get("git_commit") or "")
    tree = str(identity.get("git_tree") or "")
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit) or not re.fullmatch(
        r"[0-9a-f]{40,64}", tree
    ):
        raise ColdArchiveError("tool Git identity is invalid")
    return dict(identity)


def capture_tool_identity(repo_root: str | Path = REPO_ROOT) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    code = capture_code_identity(root)
    if code.get("git_dirty") is not False:
        raise ColdArchiveError("verified cold-archive commands require a clean Git tree")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        ).stdout.strip().lower()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ColdArchiveError("cannot capture verified cold-archive Git tree") from exc
    return _validate_tool_identity(
        {
            "tool": TOOL,
            "archive_format": ARCHIVE_FORMAT,
            "git_commit": str(code["git_commit"]),
            "git_tree": tree,
            "git_branch": str(code["git_branch"]),
            "git_dirty": False,
        }
    )


def _source_folder(
    fixture_root: Path, source_folder: str | Path
) -> tuple[Path, Path, str, date, str]:
    folder = _resolve_inside(
        fixture_root, source_folder, label="source market-day folder"
    )
    if not folder.is_dir():
        raise ColdArchiveError("source market-day folder does not exist")
    relative = folder.relative_to(fixture_root)
    if len(relative.parts) != 2 or relative.parts[0] != "snapshots":
        raise ColdArchiveError("source must be one snapshots/<event-slug> fixture folder")
    event_slug = folder.name
    target = date_from_event_slug(event_slug)
    market_id = market_id_from_slug(event_slug)
    if target is None or market_id is None:
        raise ColdArchiveError("source folder name is not a recognized market-day slug")
    return folder, fixture_root / "snapshots", event_slug, target, market_id


def _lock_paths(records: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        str(record["path"])
        for record in records
        if Path(str(record["path"])).name.casefold().endswith(".lock")
    )


def plan_market_day(
    *,
    fixture_root: str | Path,
    source_folder: str | Path,
    selection_proof: str | Path,
    as_of_date: str | date,
    hot_window_days: int = DEFAULT_HOT_WINDOW_DAYS,
    tool_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one deterministic, non-mutating market-day archive plan."""

    fixture = validate_fixture_root(fixture_root)
    folder, snapshots_root, event_slug, target, market_id = _source_folder(
        fixture, source_folder
    )
    as_of = (
        as_of_date
        if type(as_of_date) is date
        else _iso_date(as_of_date, label="as-of date")
    )
    if (
        isinstance(hot_window_days, bool)
        or not isinstance(hot_window_days, int)
        or hot_window_days < MINIMUM_HOT_WINDOW_DAYS
    ):
        raise ColdArchiveError(
            f"hot window must be at least {MINIMUM_HOT_WINDOW_DAYS} days"
        )
    age_days = (as_of - target).days
    if age_days <= hot_window_days:
        raise ColdArchiveError("market day is active, future, or inside the hot window")

    event_manifest, event_validation = _load_current_event_manifest(folder, snapshots_root)
    records = _source_inventory(folder)
    locks = _lock_paths(records)
    if locks:
        raise ColdArchiveError("source market day has an open writer lock")
    split_proofs = _validate_split_representations(folder, records)
    event_manifest_identity = next(
        (
            record
            for record in records
            if record["path"] == EVENT_DAY_MANIFEST_FILENAME
        ),
        None,
    )
    if event_manifest_identity is None:
        raise ColdArchiveError("event-day manifest disappeared during selection")

    proof_path = _resolve_inside(
        fixture,
        selection_proof,
        label="selection proof",
    )
    if _paths_overlap(folder, proof_path):
        raise ColdArchiveError("selection proof must be outside the source market-day folder")
    source_relative = folder.relative_to(fixture).as_posix()
    proof_summary = _validate_selection_proof(
        proof_path,
        fixture_root=fixture,
        source_folder_relative=source_relative,
        event_slug=event_slug,
        target_date=target.isoformat(),
        event_manifest_hash=str(event_manifest["manifest_hash"]),
    )
    identity = _validate_tool_identity(tool_identity or capture_tool_identity())
    archive_key = f"{target.isoformat()}--{event_slug}.tar.gz"
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "status": "PASS",
        "plan_hash": "",
        "source": {
            "folder": source_relative,
            "event_slug": event_slug,
            "market_id": market_id,
            "target_date": target.isoformat(),
            "event_day_manifest": {
                "path": event_manifest_identity["path"],
                "bytes": event_manifest_identity["bytes"],
                "sha256": event_manifest_identity["sha256"],
                "manifest_hash": event_manifest["manifest_hash"],
                "validation_status": event_validation["status"],
            },
        },
        "selection": {
            "as_of_date": as_of.isoformat(),
            "hot_window_days": hot_window_days,
            "minimum_hot_window_days": MINIMUM_HOT_WINDOW_DAYS,
            "age_days": age_days,
            "selection_proof": proof_summary,
            "split_representation_proofs": split_proofs,
            "writer_locks": [],
            "external_shared_dependency_count": 0,
        },
        "files": _identity_projection(records),
        "totals": {
            "file_count": len(records),
            "bytes": sum(int(row["bytes"]) for row in records),
        },
        "destination": {
            "archive_key": archive_key,
            "manifest_key": f"{archive_key}.manifest.json",
        },
        "tool_identity": identity,
    }
    plan["plan_hash"] = plan_content_hash(plan)
    return plan


def _validate_identity_record(record: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ColdArchiveError(f"{label} is invalid")
    path = _strict_relative_path(record.get("path", ""), label=f"{label} path")
    size = _nonnegative_int(record.get("bytes"), label=f"{label} bytes")
    digest = str(record.get("sha256") or "")
    if not SHA256_RE.fullmatch(digest):
        raise ColdArchiveError(f"{label} SHA-256 is invalid")
    return {"path": path.as_posix(), "bytes": size, "sha256": digest}


def _validate_embedded_selection(
    source: Mapping[str, Any], selection: Any
) -> None:
    if not isinstance(selection, dict):
        raise ColdArchiveError("archive selection contract is absent")
    target = _iso_date(source.get("target_date"), label="source target date")
    as_of = _iso_date(selection.get("as_of_date"), label="selection as-of date")
    hot_window = _nonnegative_int(
        selection.get("hot_window_days"), label="selection hot window"
    )
    if hot_window < MINIMUM_HOT_WINDOW_DAYS:
        raise ColdArchiveError(
            f"hot window must be at least {MINIMUM_HOT_WINDOW_DAYS} days"
        )
    if selection.get("minimum_hot_window_days") != MINIMUM_HOT_WINDOW_DAYS:
        raise ColdArchiveError("selection minimum hot window is invalid")
    age_days = _nonnegative_int(selection.get("age_days"), label="selection age")
    if age_days != (as_of - target).days or age_days <= hot_window:
        raise ColdArchiveError("selection age does not prove the day outside the hot window")
    if selection.get("writer_locks") != []:
        raise ColdArchiveError("archive selection has open writer locks")
    if selection.get("external_shared_dependency_count") != 0:
        raise ColdArchiveError("archive selection has external shared dependencies")

    proof = selection.get("selection_proof")
    if not isinstance(proof, dict):
        raise ColdArchiveError("archive selection proof is absent")
    if proof.get("schema_version") != SELECTION_PROOF_SCHEMA_VERSION:
        raise ColdArchiveError("archive selection proof schema version is invalid")
    _validate_identity_record(proof, label="archive selection proof")
    if not SHA256_RE.fullmatch(str(proof.get("proof_hash") or "")):
        raise ColdArchiveError("archive selection proof hash identity is invalid")
    checks = _selection_check_rows(proof)
    _validate_selection_check_semantics(checks)
    normalized_evidence: list[dict[str, Any]] = []
    for name in REQUIRED_SELECTION_CHECKS:
        raw_evidence = checks[name].get("evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise ColdArchiveError(f"{name} has no required evidence identity")
        evidence = [
            _validate_identity_record(row, label=f"{name} evidence")
            for row in raw_evidence
        ]
        normalized_evidence.append({"check": name, "evidence": evidence})
    if proof.get("evidence_identities") != normalized_evidence:
        raise ColdArchiveError("archive selection evidence identities are inconsistent")

    split_proofs = selection.get("split_representation_proofs")
    if not isinstance(split_proofs, list):
        raise ColdArchiveError("split representation proofs must be a list")
    previous_pair: tuple[str, str] | None = None
    for split in split_proofs:
        if not isinstance(split, dict):
            raise ColdArchiveError("split representation proof is invalid")
        plain = _strict_relative_path(
            split.get("plain_path", ""), label="split plain path"
        ).as_posix()
        compressed = _strict_relative_path(
            split.get("gzip_path", ""), label="split gzip path"
        ).as_posix()
        pair = (plain, compressed)
        if (
            compressed != f"{plain}.gz"
            or split.get("relationship") != "gzip_expands_to_exact_plain_bytes"
            or split.get("status") != "PASS"
            or not SHA256_RE.fullmatch(str(split.get("uncompressed_sha256") or ""))
        ):
            raise ColdArchiveError("split representation proof is invalid")
        _nonnegative_int(
            split.get("uncompressed_bytes"), label="split uncompressed bytes"
        )
        if previous_pair is not None and pair <= previous_pair:
            raise ColdArchiveError("split representation proofs are not unique and sorted")
        previous_pair = pair


def _validate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION or plan.get("status") != "PASS":
        raise ColdArchiveError("archive plan is not an eligible PASS plan")
    if not _hash_is_valid(plan, "plan_hash"):
        raise ColdArchiveError("archive plan hash is invalid")
    files = plan.get("files")
    if not isinstance(files, list) or not files:
        raise ColdArchiveError("archive plan has no source files")
    expected_paths = []
    for record in files:
        expected_paths.append(
            _validate_identity_record(record, label="archive plan file")["path"]
        )
    if expected_paths != sorted(expected_paths) or len(set(expected_paths)) != len(expected_paths):
        raise ColdArchiveError("archive plan file paths are not unique and sorted")
    totals = plan.get("totals")
    if not isinstance(totals, dict) or _nonnegative_int(
        totals.get("file_count"), label="archive plan file count"
    ) != len(files) or _nonnegative_int(
        totals.get("bytes"), label="archive plan total bytes"
    ) != sum(record["bytes"] for record in files):
        raise ColdArchiveError("archive plan totals are invalid")
    source = plan.get("source")
    if not isinstance(source, dict):
        raise ColdArchiveError("archive plan source identity is absent")
    source_folder = _strict_relative_path(
        source.get("folder", ""), label="archive plan source folder"
    )
    if len(source_folder.parts) != 2 or source_folder.parts[0] != "snapshots":
        raise ColdArchiveError("archive plan source must be one market-day folder")
    event_slug = str(source.get("event_slug") or "")
    target = _iso_date(source.get("target_date"), label="archive plan target date")
    if (
        source_folder.name != event_slug
        or date_from_event_slug(event_slug) != target
        or market_id_from_slug(event_slug) != source.get("market_id")
    ):
        raise ColdArchiveError("archive plan source slug/date identity is invalid")
    event_manifest = source.get("event_day_manifest")
    if not isinstance(event_manifest, dict):
        raise ColdArchiveError("archive plan event-day manifest identity is absent")
    _validate_identity_record(event_manifest, label="archive plan event-day manifest")
    if (
        event_manifest.get("path") != EVENT_DAY_MANIFEST_FILENAME
        or event_manifest.get("validation_status") != "PASS"
        or not SHA256_RE.fullmatch(str(event_manifest.get("manifest_hash") or ""))
    ):
        raise ColdArchiveError("archive plan event-day manifest identity is invalid")
    _validate_embedded_selection(source, plan.get("selection"))
    _validate_tool_identity(plan.get("tool_identity") or {})
    destination = plan.get("destination") or {}
    for key in ("archive_key", "manifest_key"):
        relative = _strict_relative_path(destination.get(key, ""), label=key)
        if len(relative.parts) != 1:
            raise ColdArchiveError(f"{key} must be a single filename")
    if destination["manifest_key"] != f"{destination['archive_key']}.manifest.json":
        raise ColdArchiveError("archive and manifest destination keys are inconsistent")
    expected_archive_key = f"{target.isoformat()}--{event_slug}.tar.gz"
    if destination["archive_key"] != expected_archive_key:
        raise ColdArchiveError("archive destination key is not source-derived")
    return dict(plan)


def _validate_current_plan_inputs(
    plan: Mapping[str, Any], fixture_root: Path, tool_identity: Mapping[str, Any]
) -> tuple[Path, list[dict[str, Any]]]:
    planned_identity = _validate_tool_identity(plan.get("tool_identity") or {})
    if _validate_tool_identity(tool_identity) != planned_identity:
        raise ColdArchiveError("archive tool/code identity changed since planning")
    source = plan.get("source") or {}
    folder, snapshots_root, event_slug, target, market_id = _source_folder(
        fixture_root, fixture_root / str(source.get("folder") or "")
    )
    if (
        event_slug != source.get("event_slug")
        or target.isoformat() != source.get("target_date")
        or market_id != source.get("market_id")
    ):
        raise ColdArchiveError("planned source identity changed")
    event_manifest, _ = _load_current_event_manifest(folder, snapshots_root)
    if event_manifest.get("manifest_hash") != (
        source.get("event_day_manifest") or {}
    ).get("manifest_hash"):
        raise ColdArchiveError("event-day finalization manifest changed since planning")
    current_records = _source_inventory(folder)
    if _identity_projection(current_records) != plan["files"]:
        raise ColdArchiveError("source drifted since archive planning")
    selection = plan.get("selection") or {}
    current_split_proofs = _validate_split_representations(folder, current_records)
    if current_split_proofs != selection.get("split_representation_proofs"):
        raise ColdArchiveError("split representation proof drifted since archive planning")
    proof = selection.get("selection_proof") or {}
    proof_path = fixture_root / str(proof.get("path") or "")
    current_proof = _validate_selection_proof(
        proof_path,
        fixture_root=fixture_root,
        source_folder_relative=str(source["folder"]),
        event_slug=event_slug,
        target_date=target.isoformat(),
        event_manifest_hash=str(event_manifest["manifest_hash"]),
    )
    if current_proof != proof:
        raise ColdArchiveError("selection proof drifted since archive planning")
    return folder, current_records


def _destination_root(fixture_root: Path, destination_root: str | Path) -> Path:
    destination = _resolve_inside(
        fixture_root,
        destination_root,
        label="archive destination root",
    )
    if not destination.is_dir():
        raise ColdArchiveError("archive destination root must already exist")
    _assert_not_repo_data(destination, "archive destination root")
    return destination


def destination_preflight(
    *,
    fixture_root: str | Path,
    destination_root: str | Path,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    fixture = validate_fixture_root(fixture_root)
    validated = _validate_plan(plan)
    destination = _destination_root(fixture, destination_root)
    source = fixture / str((validated.get("source") or {}).get("folder") or "")
    if _paths_overlap(destination, source):
        raise ColdArchiveError("archive destination must not overlap source folder")
    keys = validated["destination"]
    paths = [destination / keys["archive_key"], destination / keys["manifest_key"]]
    for path in paths:
        if path.exists():
            raise ColdArchiveError(f"append-only destination collision: {path}")
        _assert_no_reparse_components(path.parent, "archive destination")
    return {
        "status": "PASS",
        "plan_hash": validated["plan_hash"],
        "archive_key": keys["archive_key"],
        "manifest_key": keys["manifest_key"],
        "collision_count": 0,
        "append_only": True,
    }


class _HashingReader:
    def __init__(self, handle):
        self.handle = handle
        self.digest = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        block = self.handle.read(size)
        self.bytes_read += len(block)
        self.digest.update(block)
        return block

    def hexdigest(self) -> str:
        return self.digest.hexdigest()


def _write_archive_partial(
    partial_path: Path,
    *,
    source_folder: Path,
    records: Sequence[Mapping[str, Any]],
) -> None:
    try:
        raw = partial_path.open("xb")
    except FileExistsError as exc:
        raise ColdArchiveError(f"archive partial collision: {partial_path}") from exc
    try:
        with raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw,
                mtime=0,
            ) as compressed:
                with tarfile.open(
                    mode="w",
                    fileobj=compressed,
                    format=tarfile.PAX_FORMAT,
                ) as archive:
                    for record in records:
                        path = source_folder / str(record["path"])
                        before = _filesystem_identity(path)
                        if before != record.get("filesystem_identity"):
                            raise ColdArchiveError(
                                f"source drift before archive read: {record['path']}"
                            )
                        info = tarfile.TarInfo(str(record["path"]))
                        info.size = int(record["bytes"])
                        info.mtime = 0
                        info.mode = 0o644
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        with path.open("rb") as source_handle:
                            hashing_reader = _HashingReader(source_handle)
                            archive.addfile(info, hashing_reader)
                        if (
                            hashing_reader.bytes_read != int(record["bytes"])
                            or hashing_reader.hexdigest() != record["sha256"]
                            or _filesystem_identity(path) != before
                        ):
                            raise ColdArchiveError(
                                f"source changed during archive read: {record['path']}"
                            )
            raw.flush()
            os.fsync(raw.fileno())
    except BaseException:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _publish_create_only(partial_path: Path, destination: Path) -> None:
    try:
        os.link(partial_path, destination)
    except FileExistsError as exc:
        raise ColdArchiveError(f"append-only destination collision: {destination}") from exc
    except OSError as exc:
        raise ColdArchiveError(f"cannot publish create-only object: {destination}") from exc
    finally:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass


def build_archive(
    *,
    fixture_root: str | Path,
    plan: Mapping[str, Any] | str | Path,
    destination_root: str | Path,
    tool_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one deterministic archive plus sidecar without overwriting."""

    fixture = validate_fixture_root(fixture_root)
    if isinstance(plan, (str, Path)):
        plan_path = _resolve_inside(fixture, plan, label="archive plan")
        if not plan_path.is_file() or _is_reparse_point(plan_path):
            raise ColdArchiveError("archive plan is absent or redirected")
        plan_payload = _read_json_strict(plan_path)
    else:
        plan_path = None
        plan_payload = dict(plan)
    validated = _validate_plan(plan_payload)
    current_tool = _validate_tool_identity(tool_identity or capture_tool_identity())
    source_folder, current_records = _validate_current_plan_inputs(
        validated, fixture, current_tool
    )
    if plan_path is not None and _paths_overlap(source_folder, plan_path):
        raise ColdArchiveError("archive plan must be outside the source market-day folder")
    destination = _destination_root(fixture, destination_root)
    destination_preflight(
        fixture_root=fixture,
        destination_root=destination,
        plan=validated,
    )
    archive_path = destination / validated["destination"]["archive_key"]
    manifest_path = destination / validated["destination"]["manifest_key"]
    partial_path = destination / (
        f".{archive_path.name}.partial.{os.getpid()}.{time.time_ns()}"
    )
    _write_archive_partial(
        partial_path,
        source_folder=source_folder,
        records=current_records,
    )
    final_records = _source_inventory(source_folder)
    if _identity_projection(final_records) != validated["files"]:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ColdArchiveError("source drifted before archive publication")
    archive_identity = {
        "format": ARCHIVE_FORMAT,
        "bytes": int(partial_path.stat().st_size),
        "sha256": sha256_file(partial_path),
    }
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_hash": "",
        "archive": {
            **archive_identity,
            "object_key": archive_path.name,
        },
        "source": {
            **dict(validated["source"]),
            "plan_schema_version": PLAN_SCHEMA_VERSION,
            "plan_hash": validated["plan_hash"],
            "files": _identity_projection(validated["files"]),
        },
        "selection_proofs": dict(validated["selection"]),
        "totals": dict(validated["totals"]),
        "tool_identity": current_tool,
        "append_only": True,
    }
    manifest["manifest_hash"] = manifest_content_hash(manifest)
    _publish_create_only(partial_path, archive_path)
    try:
        _write_json_create_only(manifest_path, manifest)
    except BaseException:
        # The archive is intentionally retained as an append-only orphan.  It
        # is never overwritten or mistaken for verified without its sidecar.
        raise
    return {
        "status": "PASS",
        "archive_path": str(archive_path),
        "manifest_path": str(manifest_path),
        "manifest_hash": manifest["manifest_hash"],
        "archive": archive_identity,
        "file_count": validated["totals"]["file_count"],
        "source_deleted_count": 0,
    }


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ColdArchiveError("cold-archive manifest schema version is invalid")
    if not _hash_is_valid(manifest, "manifest_hash"):
        raise ColdArchiveError("cold-archive manifest hash is invalid")
    if manifest.get("append_only") is not True:
        raise ColdArchiveError("cold-archive manifest is not append-only")
    archive = manifest.get("archive")
    if not isinstance(archive, dict) or archive.get("format") != ARCHIVE_FORMAT:
        raise ColdArchiveError("cold-archive format is invalid")
    archive_key = _strict_relative_path(
        archive.get("object_key", ""), label="archive object key"
    )
    if len(archive_key.parts) != 1:
        raise ColdArchiveError("archive object key must be a single filename")
    if not SHA256_RE.fullmatch(str(archive.get("sha256") or "")):
        raise ColdArchiveError("cold-archive object identity is invalid")
    if _nonnegative_int(archive.get("bytes"), label="cold-archive object bytes") == 0:
        raise ColdArchiveError("cold-archive object must not be empty")
    source = manifest.get("source")
    if (
        not isinstance(source, dict)
        or source.get("plan_schema_version") != PLAN_SCHEMA_VERSION
        or not SHA256_RE.fullmatch(str(source.get("plan_hash") or ""))
    ):
        raise ColdArchiveError("cold-archive source plan identity is invalid")
    files = source.get("files") if isinstance(source, dict) else None
    if not isinstance(files, list) or not files:
        raise ColdArchiveError("cold-archive manifest has no file identities")
    paths: list[str] = []
    for record in files:
        paths.append(_validate_identity_record(record, label="cold-archive file")["path"])
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise ColdArchiveError("cold-archive file paths are not unique and sorted")
    totals = manifest.get("totals")
    if not isinstance(totals, dict) or _nonnegative_int(
        totals.get("file_count"), label="cold-archive file count"
    ) != len(files) or _nonnegative_int(
        totals.get("bytes"), label="cold-archive total bytes"
    ) != sum(record["bytes"] for record in files):
        raise ColdArchiveError("cold-archive manifest totals are invalid")
    source_folder = _strict_relative_path(
        source.get("folder", ""), label="cold-archive source folder"
    )
    if len(source_folder.parts) != 2 or source_folder.parts[0] != "snapshots":
        raise ColdArchiveError("cold-archive source folder identity is invalid")
    event_slug = str(source.get("event_slug") or "")
    target = _iso_date(source.get("target_date"), label="cold-archive target date")
    if (
        source_folder.name != event_slug
        or date_from_event_slug(event_slug) != target
        or market_id_from_slug(event_slug) != source.get("market_id")
        or archive_key.as_posix() != f"{target.isoformat()}--{event_slug}.tar.gz"
    ):
        raise ColdArchiveError("cold-archive source/archive identity is inconsistent")
    if not isinstance(source.get("event_day_manifest"), dict):
        raise ColdArchiveError("cold-archive event-day manifest identity is absent")
    event_manifest = source["event_day_manifest"]
    _validate_identity_record(
        event_manifest, label="cold-archive event-day manifest"
    )
    if (
        event_manifest.get("path") != EVENT_DAY_MANIFEST_FILENAME
        or event_manifest.get("validation_status") != "PASS"
        or not SHA256_RE.fullmatch(str(event_manifest.get("manifest_hash") or ""))
    ):
        raise ColdArchiveError("cold-archive event-day manifest identity is invalid")
    _validate_embedded_selection(source, manifest.get("selection_proofs"))
    _validate_tool_identity(manifest.get("tool_identity") or {})


def _archive_member_name(name: str) -> str:
    return _strict_relative_path(name, label="archive member path").as_posix()


def _verify_archive_members(
    archive_path: Path, expected_files: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    expected = {str(row["path"]): row for row in expected_files}
    observed: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive:
                name = _archive_member_name(member.name)
                if name in seen:
                    raise ColdArchiveError(f"duplicate archive member: {name}")
                seen.add(name)
                if not member.isfile() or member.issym() or member.islnk():
                    raise ColdArchiveError(f"archive links/special members are forbidden: {name}")
                declared = expected.get(name)
                if declared is None:
                    raise ColdArchiveError(f"unexpected archive member: {name}")
                if int(member.size) != int(declared["bytes"]):
                    raise ColdArchiveError(f"archive member size mismatch: {name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ColdArchiveError(f"archive member is unreadable: {name}")
                with extracted:
                    member_bytes, member_hash = _read_stream_hash(extracted)
                if (
                    member_bytes != int(declared["bytes"])
                    or member_hash != declared["sha256"]
                ):
                    raise ColdArchiveError(f"archive member hash mismatch: {name}")
                observed.append(
                    {"path": name, "bytes": member_bytes, "sha256": member_hash}
                )
    except ColdArchiveError:
        raise
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ColdArchiveError("archive is truncated or structurally invalid") from exc
    if set(expected) != seen:
        missing = sorted(set(expected) - seen)
        raise ColdArchiveError(f"archive members are missing: {missing[:10]}")
    if observed != list(expected_files):
        raise ColdArchiveError("archive member order or manifest parity is invalid")
    return observed


def verify_destination(
    *,
    fixture_root: str | Path,
    destination_root: str | Path,
    manifest_path: str | Path,
    receipt_path: str | Path | None = None,
    verified_at_utc: str | None = None,
    tool_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify one immutable sidecar/object pair and optionally write a receipt."""

    fixture = validate_fixture_root(fixture_root)
    destination = _destination_root(fixture, destination_root)
    manifest_file = _resolve_inside(
        destination,
        manifest_path,
        label="cold-archive manifest",
    )
    if not manifest_file.is_file() or _is_reparse_point(manifest_file):
        raise ColdArchiveError("cold-archive manifest is absent or redirected")
    manifest = _read_json_strict(manifest_file)
    _validate_manifest_shape(manifest)
    archive = manifest["archive"]
    try:
        manifest_relative = manifest_file.relative_to(destination)
    except ValueError as exc:
        raise ColdArchiveError("cold-archive manifest escapes its destination") from exc
    if (
        len(manifest_relative.parts) != 1
        or manifest_relative.name != f"{archive['object_key']}.manifest.json"
    ):
        raise ColdArchiveError("cold-archive sidecar name does not match its object")
    archive_path = _resolve_inside(
        destination,
        destination / str(archive["object_key"]),
        label="cold-archive object",
    )
    if not archive_path.is_file() or _is_reparse_point(archive_path):
        raise ColdArchiveError("cold-archive object is absent or redirected")
    current_archive = {
        "format": ARCHIVE_FORMAT,
        "bytes": int(archive_path.stat().st_size),
        "sha256": sha256_file(archive_path),
    }
    if current_archive != {
        "format": archive["format"],
        "bytes": int(archive["bytes"]),
        "sha256": archive["sha256"],
    }:
        raise ColdArchiveError("cold-archive destination drift detected")
    files = _verify_archive_members(archive_path, manifest["source"]["files"])
    current_tool = _validate_tool_identity(tool_identity or capture_tool_identity())
    receipt: dict[str, Any] = {
        "schema_version": VERIFICATION_RECEIPT_SCHEMA_VERSION,
        "status": "PASS",
        "verified_at_utc": verified_at_utc or utc_iso(),
        "verification_receipt_hash": "",
        "destination": {
            "root": _relative_to_fixture(destination, fixture),
            "manifest_path": _relative_to_fixture(manifest_file, fixture),
        },
        "manifest_hash": manifest["manifest_hash"],
        "archive": {
            **current_archive,
            "object_key": archive["object_key"],
        },
        "files": files,
        "totals": dict(manifest["totals"]),
        "tool_identity": current_tool,
        "append_only": True,
    }
    receipt["verification_receipt_hash"] = verification_receipt_content_hash(
        receipt
    )
    if receipt_path is not None:
        output = _resolve_inside(
            fixture,
            receipt_path,
            label="verification receipt",
        )
        source_folder = fixture / str(manifest["source"]["folder"])
        if _paths_overlap(source_folder, output):
            raise ColdArchiveError("verification receipt must be outside the source folder")
        _write_json_create_only(output, receipt)
    return receipt


def _safe_output_member(root: Path, relative: str) -> Path:
    normalized = _archive_member_name(relative)
    destination = root.joinpath(*PurePosixPath(normalized).parts)
    resolved = _resolve_inside(root, destination, label="restore member")
    return resolved


def _inventory_restored(root: Path) -> list[dict[str, Any]]:
    records = _source_inventory(root)
    return _identity_projection(records)


def restore_archive(
    *,
    fixture_root: str | Path,
    destination_root: str | Path,
    manifest_path: str | Path,
    scratch_root: str | Path,
    receipt_path: str | Path,
    restored_at_utc: str | None = None,
    tool_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Restore one verified archive into a new scratch tree and leave a receipt."""

    fixture = validate_fixture_root(fixture_root)
    current_tool = _validate_tool_identity(tool_identity or capture_tool_identity())
    destination = _destination_root(fixture, destination_root)
    manifest_file = _resolve_inside(
        destination, manifest_path, label="restore manifest"
    )
    verification = verify_destination(
        fixture_root=fixture,
        destination_root=destination,
        manifest_path=manifest_file,
        tool_identity=current_tool,
        verified_at_utc=restored_at_utc,
    )
    manifest = _read_json_strict(manifest_file)
    archive_path = destination / str(manifest["archive"]["object_key"])
    scratch = _resolve_inside(fixture, scratch_root, label="restore scratch root")
    _assert_not_repo_data(scratch, "restore scratch root")
    if scratch.exists():
        raise ColdArchiveError("restore scratch root must not already exist")
    receipt = _resolve_inside(fixture, receipt_path, label="restore receipt")
    if receipt.exists():
        raise ColdArchiveError("restore receipt create-only collision")
    if receipt == scratch or scratch in receipt.parents:
        raise ColdArchiveError("restore receipt must be outside restored bytes")
    if _paths_overlap(scratch, destination):
        raise ColdArchiveError("restore scratch root must not overlap archive destination")
    source_folder = fixture / str(manifest["source"]["folder"])
    if _paths_overlap(scratch, source_folder) or _paths_overlap(receipt, source_folder):
        raise ColdArchiveError("restore scratch and receipt must be outside the source folder")
    scratch.mkdir()
    expected = {row["path"]: row for row in manifest["source"]["files"]}
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            seen: set[str] = set()
            for member in archive:
                name = _archive_member_name(member.name)
                if name in seen:
                    raise ColdArchiveError(f"duplicate archive member: {name}")
                seen.add(name)
                if not member.isfile() or member.issym() or member.islnk():
                    raise ColdArchiveError(f"archive links/special members are forbidden: {name}")
                declared = expected.get(name)
                if declared is None:
                    raise ColdArchiveError(f"unexpected archive member: {name}")
                target = _safe_output_member(scratch, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                _assert_no_reparse_components(target.parent, "restore member parent")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ColdArchiveError(f"archive member is unreadable: {name}")
                digest = hashlib.sha256()
                total = 0
                try:
                    with target.open("xb") as output, extracted:
                        while True:
                            block = extracted.read(HASH_BLOCK_SIZE)
                            if not block:
                                break
                            output.write(block)
                            digest.update(block)
                            total += len(block)
                        output.flush()
                        os.fsync(output.fileno())
                except FileExistsError as exc:
                    raise ColdArchiveError(f"restore path collision: {name}") from exc
                if total != int(declared["bytes"]) or digest.hexdigest() != declared["sha256"]:
                    raise ColdArchiveError(f"restored member hash mismatch: {name}")
    except ColdArchiveError:
        raise
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ColdArchiveError("archive restore failed closed") from exc
    restored_files = _inventory_restored(scratch)
    if restored_files != manifest["source"]["files"]:
        raise ColdArchiveError("restored tree does not have exact manifest parity")
    result: dict[str, Any] = {
        "schema_version": RESTORE_RECEIPT_SCHEMA_VERSION,
        "status": "PASS",
        "restored_at_utc": restored_at_utc or utc_iso(),
        "restore_receipt_hash": "",
        "manifest_hash": manifest["manifest_hash"],
        "archive": dict(verification["archive"]),
        "source": {
            "folder": manifest["source"]["folder"],
            "event_slug": manifest["source"]["event_slug"],
            "target_date": manifest["source"]["target_date"],
        },
        "restored_root": _relative_to_fixture(scratch, fixture),
        "files": restored_files,
        "totals": dict(manifest["totals"]),
        "verification_receipt_hash": verification["verification_receipt_hash"],
        "tool_identity": current_tool,
    }
    result["restore_receipt_hash"] = restore_receipt_content_hash(result)
    _write_json_create_only(receipt, result)
    return result


def _validate_restore_receipt(
    receipt: Mapping[str, Any], manifest: Mapping[str, Any]
) -> None:
    if (
        receipt.get("schema_version") != RESTORE_RECEIPT_SCHEMA_VERSION
        or receipt.get("status") != "PASS"
        or not _hash_is_valid(receipt, "restore_receipt_hash")
    ):
        raise ColdArchiveError("restore receipt is not a valid PASS receipt")
    if (
        receipt.get("manifest_hash") != manifest.get("manifest_hash")
        or receipt.get("archive") != {
            **dict(manifest["archive"]),
        }
        or receipt.get("files") != manifest["source"]["files"]
        or receipt.get("totals") != manifest.get("totals")
    ):
        raise ColdArchiveError("restore receipt does not match archive identity")


def generate_cleanup_manifest(
    *,
    fixture_root: str | Path,
    destination_root: str | Path,
    manifest_path: str | Path,
    restore_receipt_path: str | Path,
    output_path: str | Path,
    generated_at_utc: str | None = None,
    tool_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a review-only exact-source cleanup plan after restore parity."""

    fixture = validate_fixture_root(fixture_root)
    current_tool = _validate_tool_identity(tool_identity or capture_tool_identity())
    destination = _destination_root(fixture, destination_root)
    manifest_file = _resolve_inside(
        destination, manifest_path, label="cleanup archive manifest"
    )
    verify_destination(
        fixture_root=fixture,
        destination_root=destination,
        manifest_path=manifest_file,
        tool_identity=current_tool,
        verified_at_utc=generated_at_utc,
    )
    manifest = _read_json_strict(manifest_file)
    receipt_path = _resolve_inside(
        fixture, restore_receipt_path, label="cleanup restore receipt"
    )
    restore_receipt = _read_json_strict(receipt_path)
    _validate_restore_receipt(restore_receipt, manifest)
    restored_root = _resolve_inside(
        fixture,
        fixture / str(restore_receipt.get("restored_root") or ""),
        label="restored proof tree",
    )
    if _inventory_restored(restored_root) != manifest["source"]["files"]:
        raise ColdArchiveError("restored proof tree drifted after its receipt")
    source_root = _resolve_inside(
        fixture,
        fixture / str(manifest["source"]["folder"]),
        label="cleanup source folder",
    )
    current_source = _source_inventory(source_root)
    if _identity_projection(current_source) != manifest["source"]["files"]:
        raise ColdArchiveError("source drift blocks cleanup-plan generation")
    review = {
        "approved": False,
        "approved_by": "",
        "approved_at_utc": "",
        "note": "",
        "approved_plan_hash": "",
    }
    payload = cleanup_manifest_for_paths(
        [record["path"] for record in manifest["source"]["files"]],
        root=source_root,
        classification_prefix=f"snapshots/{manifest['source']['event_slug']}",
        deletion_reason="verified encrypted cold-archive offload candidate",
        operator_review=review,
        generated_at_utc=generated_at_utc or utc_iso(),
    )
    if payload.get("schema_version") != CLEANUP_MANIFEST_SCHEMA_VERSION:
        raise ColdArchiveError("cleanup manifest helper returned an unknown schema")
    for candidate in payload["candidates"]:
        candidate["source_path"] = str(
            (source_root / str(candidate["path"])).resolve(strict=True)
        )
    payload.update(
        {
            "cleanup_plan_hash": "",
            "generator": TOOL,
            "tool_identity": current_tool,
            "archive_identity": {
                "manifest_path": _relative_to_fixture(manifest_file, fixture),
                "manifest_hash": manifest["manifest_hash"],
                "archive": dict(manifest["archive"]),
            },
            "restore_identity": {
                "receipt_path": _relative_to_fixture(receipt_path, fixture),
                "restore_receipt_hash": restore_receipt["restore_receipt_hash"],
                "restored_root": restore_receipt["restored_root"],
                "status": "PASS",
            },
            "selection_proofs": dict(manifest["selection_proofs"]),
            "executor_present": False,
        }
    )
    payload["cleanup_plan_hash"] = cleanup_plan_content_hash(payload)
    output = _resolve_inside(fixture, output_path, label="cleanup manifest output")
    if _paths_overlap(output, source_root) or _paths_overlap(output, restored_root):
        raise ColdArchiveError("cleanup manifest output must be outside source and restore trees")
    _write_json_create_only(output, payload)
    return payload


def _load_plan(path: str | Path) -> dict[str, Any]:
    return _validate_plan(_read_json_strict(path))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fixture-only verified cold market-day archives."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="plan one closed market day")
    plan_parser.add_argument("--fixture-root", required=True)
    plan_parser.add_argument("--source-folder", required=True)
    plan_parser.add_argument("--selection-proof", required=True)
    plan_parser.add_argument("--as-of-date", required=True)
    plan_parser.add_argument(
        "--hot-window-days", type=int, default=DEFAULT_HOT_WINDOW_DAYS
    )
    plan_parser.add_argument("--output", required=True)

    build_parser = subparsers.add_parser("build", help="build one create-only object")
    build_parser.add_argument("--fixture-root", required=True)
    build_parser.add_argument("--plan", required=True)
    build_parser.add_argument("--destination-root", required=True)

    verify_parser = subparsers.add_parser("verify", help="verify destination bytes")
    verify_parser.add_argument("--fixture-root", required=True)
    verify_parser.add_argument("--destination-root", required=True)
    verify_parser.add_argument("--manifest", required=True)
    verify_parser.add_argument("--receipt", required=True)

    restore_parser = subparsers.add_parser("restore", help="run a restore drill")
    restore_parser.add_argument("--fixture-root", required=True)
    restore_parser.add_argument("--destination-root", required=True)
    restore_parser.add_argument("--manifest", required=True)
    restore_parser.add_argument("--scratch-root", required=True)
    restore_parser.add_argument("--receipt", required=True)

    cleanup_parser = subparsers.add_parser(
        "cleanup-plan", help="generate a reviewed cleanup manifest; never delete"
    )
    cleanup_parser.add_argument("--fixture-root", required=True)
    cleanup_parser.add_argument("--destination-root", required=True)
    cleanup_parser.add_argument("--manifest", required=True)
    cleanup_parser.add_argument("--restore-receipt", required=True)
    cleanup_parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            fixture = validate_fixture_root(args.fixture_root)
            output = _resolve_inside(fixture, args.output, label="plan output")
            source_folder, _, _, _, _ = _source_folder(
                fixture, args.source_folder
            )
            if _paths_overlap(output, source_folder):
                raise ColdArchiveError("plan output must be outside the source folder")
            payload = plan_market_day(
                fixture_root=fixture,
                source_folder=args.source_folder,
                selection_proof=args.selection_proof,
                as_of_date=args.as_of_date,
                hot_window_days=args.hot_window_days,
            )
            _write_json_create_only(output, payload)
        elif args.command == "build":
            payload = build_archive(
                fixture_root=args.fixture_root,
                plan=args.plan,
                destination_root=args.destination_root,
            )
        elif args.command == "verify":
            payload = verify_destination(
                fixture_root=args.fixture_root,
                destination_root=args.destination_root,
                manifest_path=args.manifest,
                receipt_path=args.receipt,
            )
        elif args.command == "restore":
            payload = restore_archive(
                fixture_root=args.fixture_root,
                destination_root=args.destination_root,
                manifest_path=args.manifest,
                scratch_root=args.scratch_root,
                receipt_path=args.receipt,
            )
        else:
            payload = generate_cleanup_manifest(
                fixture_root=args.fixture_root,
                destination_root=args.destination_root,
                manifest_path=args.manifest,
                restore_receipt_path=args.restore_receipt,
                output_path=args.output,
            )
    except ColdArchiveError as exc:
        print(json.dumps({"status": "BLOCK", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARCHIVE_FORMAT",
    "DEFAULT_HOT_WINDOW_DAYS",
    "FIXTURE_MARKER",
    "FIXTURE_MARKER_PURPOSE",
    "FIXTURE_ROOT_PREFIX",
    "MANIFEST_SCHEMA_VERSION",
    "MINIMUM_HOT_WINDOW_DAYS",
    "PLAN_SCHEMA_VERSION",
    "RESTORE_RECEIPT_SCHEMA_VERSION",
    "SELECTION_PROOF_SCHEMA_VERSION",
    "VERIFICATION_RECEIPT_SCHEMA_VERSION",
    "ColdArchiveError",
    "build_archive",
    "cleanup_plan_content_hash",
    "destination_preflight",
    "generate_cleanup_manifest",
    "manifest_content_hash",
    "plan_content_hash",
    "plan_market_day",
    "restore_archive",
    "restore_receipt_content_hash",
    "selection_proof_content_hash",
    "validate_fixture_root",
    "verification_receipt_content_hash",
    "verify_destination",
]
