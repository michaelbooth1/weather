"""Retain the adopted control source through candidate staging and recovery.

The selection is code owned: all canonical package Python, all operations
PowerShell/Python, tracked configuration, and the two bootstrap Python files.
Neither a certificate nor a candidate manifest can shrink that import closure.
No function here installs, imports, launches or adopts the retained source.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess

from . import environment, merge_tree, source
from .contracts import fields, record, sequence
from .records import checked_root, digest, distinct_paths, integer, publish, require


MAX_CONTROL_BYTES = 128 * 1024**2


def selected(path):
    return (path in {"sitecustomize.py", "weather/__init__.py"}
            or path.startswith("src/weather/") and path.endswith(".py")
            or path.startswith("scripts/ops/") and path.endswith((".ps1", ".py"))
            or path.startswith("config/") and path.endswith((".json", ".toml", ".yaml", ".yml")))


def selection(git, repository, baseline):
    entries = merge_tree.tree_entries(git, repository, baseline)
    paths = sorted(path for path in entries if selected(path))
    require(paths, "adopted control closure is empty")
    return entries, paths


def freeze(git, repository, baseline, *, destination, evidence_root):
    """Copy exact B blobs into a fresh source-only execution root.

    The owning admitted parent accounts for this copy and its Git child under
    its absolute deadline. The mutable working tree is never the byte source.
    """
    repository = checked_root(repository)
    destination = Path(destination)
    checked_root(destination.parent)
    evidence_root = checked_root(evidence_root)
    require(destination.is_absolute() and not destination.exists(), "frozen control namespace is spent")
    require(not destination.is_relative_to(repository / "src") and not evidence_root.is_relative_to(destination),
            "frozen control/evidence roots overlap source")
    entries, paths = selection(git, repository, baseline)
    destination.mkdir()
    files, total = [], 0
    child = subprocess.Popen(source.git_argv(git, repository, "cat-file", "--batch"), env=source.git_environment(),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for path in paths:
            oid = entries[path]["oid"]
            child.stdin.write((oid + "\n").encode("ascii"))
            child.stdin.flush()
            header = child.stdout.readline(256).decode("ascii").strip().split()
            require(len(header) == 3 and header[:2] == [oid, "blob"] and header[2].isdigit(), "invalid adopted blob header")
            size = int(header[2])
            total += size
            require(size <= 8 * 1024**2 and total <= MAX_CONTROL_BYTES, "adopted control closure exceeds reservation")
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            checked_root(target.parent)
            sha256 = hashlib.sha256()
            git_hash = hashlib.sha1(b"blob " + str(size).encode("ascii") + b"\0")
            remaining = size
            with target.open("xb") as output:
                while remaining:
                    block = child.stdout.read(min(1024 * 1024, remaining))
                    require(bool(block), "truncated adopted control blob")
                    remaining -= len(block)
                    sha256.update(block)
                    git_hash.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            require(child.stdout.read(1) == b"\n" and git_hash.hexdigest() == oid, "adopted Git blob bytes differ")
            os.chmod(target, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            files.append({"path": path, "git_blob": oid, "sha256": sha256.hexdigest(), "size": size,
                          "mode": entries[path]["mode"]})
        child.stdin.close()
        require(child.wait(timeout=10) == 0, "adopted closure Git child did not finish")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        child.stdout.close()
        if not child.stdin.closed:
            child.stdin.close()
    value = {"schema": "qualification_control_closure_v2", "baseline": baseline,
             "tree": merge_tree.tree_id(entries), "files": files, "total_bytes": total}
    ref = publish(evidence_root, "control-closure.json", value)
    validate(git, repository, baseline, destination=destination, value=value)
    return ref


def validate(git, repository, baseline, *, destination, value):
    """Full rehash before deferred launches; reject injected pyc/extra files."""
    value = record(value, "qualification_control_closure_v2", {"baseline", "tree", "files", "total_bytes"})
    require(value["baseline"] == digest(baseline, git=True), "control closure belongs to another baseline")
    entries, paths = selection(git, repository, baseline)
    require(value["tree"] == merge_tree.tree_id(entries), "adopted control tree changed")
    files = sequence(value["files"], minimum=1, maximum=source.MAX_TRACKED_FILES)
    actual_paths = [fields(item, {"path", "git_blob", "sha256", "size", "mode"})["path"] for item in files]
    distinct_paths(actual_paths)
    require(actual_paths == paths and environment.enumerate_files(destination) == paths,
            "incomplete or injected adopted execution closure")
    total = 0
    for item in files:
        path = item["path"]
        require(item["mode"] == entries[path]["mode"] and item["git_blob"] == entries[path]["oid"], "unapproved control blob")
        digest(item["sha256"])
        total += integer(item["size"], maximum=8 * 1024**2)
        require(total <= MAX_CONTROL_BYTES, "adopted execution bytes exceed bound")
        actual = environment.file_identity(destination, path, maximum=8 * 1024**2)
        require(actual["sha256"] == item["sha256"] and actual["size"] == item["size"], "frozen control source changed")
        # The authority is actual B's Git object, not a caller-supplied SHA256
        # adjacent to different copied bytes.
        git_hash = hashlib.sha1(b"blob " + str(item["size"]).encode("ascii") + b"\0")
        from .records import open_record
        with open_record(destination, path, maximum=item["size"]) as handle:
            while block := handle.read(1024 * 1024):
                git_hash.update(block)
        require(git_hash.hexdigest() == item["git_blob"], "frozen bytes do not belong to adopted B")
    require(integer(value["total_bytes"]) == total, "frozen execution byte count differs")
    return value
