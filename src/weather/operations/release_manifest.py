"""Immutable release construction and verification.

A release is a directory that is written exactly once from a candidate folder.
Every regular file is included in the manifest inventory, including files that
were not assigned a serving role.  Consumers must call :func:`verify_release`
before opening/deserializing any artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.paths import REPO_ROOT
from weather.release_artifacts import (
    ARTIFACT_KINDS,
    DEFAULT_RELEASES_ROOT,
    RELEASE_MANIFEST_NAME,
    RELEASE_MANIFEST_SCHEMA_VERSION,
    ReleaseArtifactVerificationError,
    canonical_payload_sha256,
    capture_runtime_versions,
    load_release_manifest as load_release_manifest,
    manifest_content_sha256,
    safe_relative_artifact_path,
    sha256_file,
    validate_code_runtime_alignment,
    validate_release_id,
    verify_release as verify_release,
)
from weather.runtime_identity import get_runtime_identity


ReleaseLifecycleError = ReleaseArtifactVerificationError


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ReleaseLifecycleError(f"immutable file already exists: {path}") from exc


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Durably replace ``path`` using a temporary file in the same directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    text = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_handle = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_handle = None
        if directory_handle is not None:
            try:
                os.fsync(directory_handle)
            finally:
                os.close(directory_handle)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _run_git(repo_root: Path, *args: str, text: bool = True) -> str | bytes:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        creationflags=creationflags,
    )
    return result.stdout


def capture_code_identity(repo_root: str | Path = REPO_ROOT) -> dict[str, Any]:
    """Capture a full git revision plus a reproducible dirty-state attestation.

    Generated candidate/release state and ignored data do not make source code
    dirty.  All other tracked/untracked repository changes are attested.
    """

    repo_root = Path(repo_root).resolve()
    try:
        commit = str(_run_git(repo_root, "rev-parse", "HEAD")).strip()
        branch = str(_run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")).strip()
        raw_status = _run_git(
            repo_root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            ".",
            ":(exclude)artifacts/releases/**",
            ":(exclude)artifacts/candidates/**",
            ":(exclude)data/**",
            text=False,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseLifecycleError(f"cannot attest git code identity for {repo_root}: {exc}") from exc
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        raise ReleaseLifecycleError(f"git returned an invalid commit identity: {commit!r}")
    status_bytes = bytes(raw_status)
    return {
        "git_commit": commit.lower(),
        "git_branch": branch or "detached",
        "git_dirty": bool(status_bytes),
        "dirty_fingerprint": hashlib.sha256(status_bytes).hexdigest() if status_bytes else None,
        "dirty_entry_count": sum(bool(row) for row in status_bytes.split(b"\0")),
    }


def _normalize_declarations(declarations: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    by_path: dict[str, dict[str, str]] = {}
    roles: set[str] = set()
    for declaration in declarations:
        path = safe_relative_artifact_path(str(declaration.get("path") or ""))
        role = str(declaration.get("role") or "").strip()
        kind = str(declaration.get("kind") or "").strip()
        if not role or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", role):
            raise ReleaseLifecycleError(f"invalid artifact role for {path}: {role!r}")
        if kind not in ARTIFACT_KINDS:
            raise ReleaseLifecycleError(f"invalid artifact kind for {path}: {kind!r}")
        if path in by_path:
            raise ReleaseLifecycleError(f"artifact path declared more than once: {path}")
        if role in roles:
            raise ReleaseLifecycleError(f"artifact role declared more than once: {role}")
        roles.add(role)
        by_path[path] = {"role": role, "kind": kind}
    kinds = {row["kind"] for row in by_path.values()}
    missing = {"model", "config"} - kinds
    if missing:
        raise ReleaseLifecycleError(f"release must declare at least one model and config artifact; missing {sorted(missing)}")
    return by_path


def _candidate_inventory(candidate_dir: Path) -> dict[str, dict[str, Any]]:
    if not candidate_dir.exists() or not candidate_dir.is_dir():
        raise ReleaseLifecycleError(f"candidate directory does not exist: {candidate_dir}")
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(candidate_dir.rglob("*")):
        if path.is_symlink():
            raise ReleaseLifecycleError(f"candidate contains a symlink, which is not allowed: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ReleaseLifecycleError(f"candidate contains a non-regular file: {path}")
        rel = path.relative_to(candidate_dir).as_posix()
        if path.name == RELEASE_MANIFEST_NAME:
            raise ReleaseLifecycleError(f"candidate contains reserved file name: {rel}")
        stat = path.stat()
        rows[rel] = {
            "path": rel,
            "bytes": int(stat.st_size),
            "sha256": sha256_file(path),
        }
    if not rows:
        raise ReleaseLifecycleError("candidate directory contains no artifacts")
    return rows


def _manifest_inventory(
    source_inventory: Mapping[str, Mapping[str, Any]],
    declarations: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    missing = sorted(set(declarations) - set(source_inventory))
    if missing:
        raise ReleaseLifecycleError(f"declared artifacts are missing from candidate: {missing}")
    rows = []
    for rel, source in sorted(source_inventory.items()):
        declaration = declarations.get(rel)
        rows.append(
            {
                **source,
                "declared": declaration is not None,
                "kind": declaration["kind"] if declaration else "other",
                "role": declaration["role"] if declaration else None,
            }
        )
    return rows


def create_release(
    *,
    release_id: str,
    candidate_dir: str | Path,
    declarations: Sequence[Mapping[str, Any]],
    route: Mapping[str, Any],
    expected_live_runtimes: Sequence[str],
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    repo_root: str | Path = REPO_ROOT,
    parent_release: str | None = None,
    rollback_target: str | None = None,
    lineage: Mapping[str, Any] | None = None,
    code_identity: Mapping[str, Any] | None = None,
    runtime_versions: Mapping[str, Any] | None = None,
    runtime_identity: Mapping[str, Any] | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Copy a candidate into a new immutable release directory.

    The function never activates the result and never overwrites an existing
    release, including one left by a concurrent creator.
    """

    release_id = validate_release_id(release_id)
    if parent_release is not None:
        parent_release = validate_release_id(parent_release)
    if rollback_target is not None:
        rollback_target = validate_release_id(rollback_target)
    if not isinstance(route, Mapping) or not route:
        raise ReleaseLifecycleError("release route metadata is required")
    runtimes = sorted({str(value).strip() for value in expected_live_runtimes if str(value).strip()})
    if not runtimes:
        raise ReleaseLifecycleError("at least one expected live runtime is required")
    declarations_by_path = _normalize_declarations(declarations)
    candidate_input = Path(candidate_dir)
    if candidate_input.is_symlink():
        raise ReleaseLifecycleError(f"candidate directory must not be a symlink: {candidate_input}")
    candidate_dir = candidate_input.resolve()
    releases_root = Path(releases_root).resolve()
    repo_root = Path(repo_root).resolve()
    release_dir = releases_root / release_id
    if release_dir.exists():
        raise ReleaseLifecycleError(f"immutable release already exists: {release_dir}")
    try:
        candidate_dir.relative_to(releases_root)
    except ValueError:
        pass
    else:
        raise ReleaseLifecycleError("candidate directory must not be inside the immutable releases root")

    source_inventory = _candidate_inventory(candidate_dir)
    inventory = _manifest_inventory(source_inventory, declarations_by_path)
    code = dict(code_identity if code_identity is not None else capture_code_identity(repo_root))
    versions = dict(runtime_versions if runtime_versions is not None else capture_runtime_versions(repo_root))
    identity = dict(runtime_identity if runtime_identity is not None else get_runtime_identity(repo_root))
    for required in ("git_commit", "git_branch", "git_dirty", "dirty_fingerprint"):
        if required not in code:
            raise ReleaseLifecycleError(f"code identity is missing required field: {required}")
    if not identity.get("source_fingerprint"):
        raise ReleaseLifecycleError("runtime identity is missing source_fingerprint")
    identity.update(
        {
            "git_commit": code["git_commit"],
            "git_branch": code["git_branch"],
            "git_dirty": code["git_dirty"],
            "dirty_fingerprint": code["dirty_fingerprint"],
        }
    )
    validate_code_runtime_alignment(code, identity)
    kind_counts = Counter(row["kind"] for row in inventory)
    config_hashes = {
        str(row["role"]): row["sha256"]
        for row in inventory
        if row["declared"] and row["kind"] == "config"
    }
    manifest: dict[str, Any] = {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "release_id": release_id,
        "state": "IMMUTABLE_CANDIDATE",
        "created_at_utc": created_at_utc or utc_now_iso(),
        "candidate_source": {
            "directory": str(candidate_dir),
            "file_count": len(source_inventory),
            "content_sha256": canonical_payload_sha256(source_inventory),
        },
        "code": code,
        "runtime_versions": versions,
        "runtime_identity": identity,
        "route": dict(route),
        "route_sha256": canonical_payload_sha256(route),
        "expected_live_runtimes": runtimes,
        "parent_release": parent_release,
        "rollback_target": rollback_target,
        "lineage": dict(lineage or {}),
        "artifacts": {
            "file_count": len(inventory),
            "total_bytes": sum(int(row["bytes"]) for row in inventory),
            "kind_counts": dict(sorted(kind_counts.items())),
            "inventory": inventory,
        },
        "config_hashes": dict(sorted(config_hashes.items())),
    }
    manifest["manifest_sha256"] = manifest_content_sha256(manifest)

    releases_root.mkdir(parents=True, exist_ok=True)
    # The target mkdir is the fail-if-exists reservation.  The manifest is
    # written last and is the commit marker, so a concurrent consumer will
    # reject an in-progress or crash-interrupted release rather than observe a
    # partial artifact set as usable.
    owns_release_dir = False
    try:
        try:
            release_dir.mkdir(parents=False, exist_ok=False)
            owns_release_dir = True
        except FileExistsError as exc:
            raise ReleaseLifecycleError(f"immutable release already exists: {release_dir}") from exc
        for rel, expected in source_inventory.items():
            source = candidate_dir / rel
            destination = release_dir / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination, follow_symlinks=False)
            if destination.is_symlink():
                raise ReleaseLifecycleError(f"release copy unexpectedly produced a symlink: {rel}")
            if destination.stat().st_size != expected["bytes"] or sha256_file(destination) != expected["sha256"]:
                raise ReleaseLifecycleError(f"candidate changed while release was being copied: {rel}")
        if code_identity is None and runtime_identity is None:
            final_code = capture_code_identity(repo_root)
            final_identity = get_runtime_identity(repo_root)
            if final_code != code:
                raise ReleaseLifecycleError("repository code identity changed while release was being built")
            if final_identity.get("source_fingerprint") != identity.get("source_fingerprint"):
                raise ReleaseLifecycleError("runtime source identity changed while release was being built")
        _write_json_exclusive(release_dir / RELEASE_MANIFEST_NAME, manifest)
    except Exception:
        # Cleanup is safe only because this process won the exclusive mkdir and
        # the manifest (the release commit marker) has not been published.
        if owns_release_dir and not (release_dir / RELEASE_MANIFEST_NAME).exists():
            shutil.rmtree(release_dir, ignore_errors=True)
        raise
    return {
        "status": "CREATED",
        "release_id": release_id,
        "release_dir": str(release_dir),
        "manifest_path": str(release_dir / RELEASE_MANIFEST_NAME),
        "manifest_sha256": manifest["manifest_sha256"],
        "file_count": len(inventory),
    }
