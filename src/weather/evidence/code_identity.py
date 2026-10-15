"""PL-4 code/config identity: ``{repo path: git blob sha1}`` of the files a process loaded.

Computed in-process from the working-tree bytes (no ``git`` spawn), stored once as a gzip JSON
object in ``<evidence root>/identity/<sha256>.json.gz`` and referenced by its sha256
(``code_manifest_sha``) from journal rows and status. ``disk_drift`` recomputes the same paths from
disk so status can show running-vs-disk identity (DECISION_LOG 2026-10-15 Q11: new families adopt
code by explicit restart).
"""
from __future__ import annotations

import gzip
import hashlib
import sys
from pathlib import Path

from weather.evidence.envelope import canonical, sha256_hex
from weather.evidence.journal import atomic_bytes
from weather.schema_families import schema_version

IDENTITY_SCHEMA = schema_version("evidence_code_identity")
HASH_KIND = "git_blob_sha1_of_worktree_bytes"


def git_blob_sha1(raw: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def loaded_repo_files(repo_root, modules=None) -> list[str]:
    """Repo-relative paths of loaded modules' source files under ``repo_root``."""
    repo_root = Path(repo_root).resolve()
    paths = set()
    for module in list((modules if modules is not None else sys.modules).values()):
        source = getattr(module, "__file__", None)
        if not source or not str(source).endswith(".py"):
            continue
        try:
            relative = Path(source).resolve().relative_to(repo_root)
        except (ValueError, OSError):
            continue
        paths.add(relative.as_posix())
    return sorted(paths)


def identity_manifest(repo_root, paths) -> dict:
    repo_root = Path(repo_root)
    files = {}
    for relative in sorted(set(paths)):
        path = repo_root / relative
        files[relative] = git_blob_sha1(path.read_bytes()) if path.is_file() else None
    return {"schema_version": IDENTITY_SCHEMA, "hash_kind": HASH_KIND, "files": files}


def store_identity(evidence_root, manifest) -> str:
    raw = canonical(manifest)
    digest = sha256_hex(raw)
    path = Path(evidence_root) / "identity" / f"{digest}.json.gz"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_bytes(path, gzip.compress(raw, compresslevel=6, mtime=0))
    return digest


def capture_identity(evidence_root, repo_root, config_paths=()) -> tuple[str, dict]:
    """Identity of this process now: loaded repo modules plus the named config files."""
    repo_root = Path(repo_root)
    paths = loaded_repo_files(repo_root)
    for config in config_paths:
        try:
            paths.append(Path(config).resolve().relative_to(repo_root.resolve()).as_posix())
        except ValueError:
            continue
    manifest = identity_manifest(repo_root, paths)
    return store_identity(evidence_root, manifest), manifest


def disk_drift(repo_root, manifest) -> list[str]:
    """Paths whose working-tree bytes no longer match the running identity."""
    repo_root = Path(repo_root)
    drift = []
    for relative, expected in manifest["files"].items():
        path = repo_root / relative
        actual = git_blob_sha1(path.read_bytes()) if path.is_file() else None
        if actual != expected:
            drift.append(relative)
    return drift
