"""Exact Git and working-byte inventories for isolated off-host qualification."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

from .records import checked_root, digest, distinct_paths, open_record, require


MAX_TRACKED_FILES = 20_000
MAX_TRACKED_BYTES = 2 * 1024**3
MAX_SINGLE_FILE_BYTES = 512 * 1024**2


def git_environment():
    # Inherited credentials remain with the outer publisher/importer, never a
    # candidate subprocess. This metadata helper itself performs no remote I/O.
    return {**{key: value for key, value in os.environ.items()
               if not key.upper().startswith(("GIT_", "GH_", "GITHUB_", "PYTHON"))},
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", "LC_ALL": "C"}


def git_argv(git: Path, root: Path, *arguments):
    require(Path(git).is_absolute(), "absolute reviewed Git executable required")
    checked_root(root)
    return [str(git), "--no-replace-objects", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
            "-c", "core.hooksPath=" + os.devnull, "-C", str(root), *arguments]


def git_output(git, root, *arguments, maximum=8 * 1024**2):
    # The enclosing CI/host wrapper owns the entire tree and output/deadline caps.
    result = subprocess.run(git_argv(git, root, *arguments), env=git_environment(),
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)
    require(result.returncode == 0, "Git identity/inventory command failed")
    require(len(result.stdout) <= maximum and len(result.stderr) <= 65536, "Git metadata exceeds bound")
    return result.stdout


def identity(git, root, *, source, baseline):
    digest(source, git=True)
    digest(baseline, git=True)
    require(source != baseline, "candidate must advance baseline")
    head = git_output(git, root, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
    require(head == source, "checkout is not the reviewed candidate")
    tree = git_output(git, root, "rev-parse", "--verify", source + "^{tree}").decode("ascii").strip()
    digest(tree, git=True)
    git_output(git, root, "merge-base", "--is-ancestor", baseline, source)
    return {"commit": head, "tree": tree, "baseline": baseline}


def _read_exact(handle, count):
    parts, remaining = [], count
    while remaining:
        part = handle.read(min(remaining, 1024 * 1024))
        require(bool(part), "truncated Git blob stream")
        parts.append(part)
        remaining -= len(part)
    return b"".join(parts)


def inventory(git, root, commit, *, verify_working=False):
    digest(commit, git=True)
    listing = git_output(git, root, "ls-tree", "-rz", "--full-tree", commit)
    require(listing.endswith(b"\0"), "empty/incomplete tracked file inventory")
    entries = []
    for entry in listing[:-1].split(b"\0"):
        metadata, path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split(" ")
        require(kind == "blob" and mode in {"100644", "100755"}, "tracked symlink/submodule is not admissible")
        entries.append((mode, digest(oid, git=True), path.decode("utf-8")))
    require(0 < len(entries) <= MAX_TRACKED_FILES, "tracked inventory limit exceeded")
    distinct_paths([path for _, _, path in entries])
    files, total_bytes = [], 0
    process = subprocess.Popen(git_argv(git, root, "cat-file", "--batch"), env=git_environment(),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for mode, oid, path in entries:
            process.stdin.write((oid + "\n").encode("ascii"))
            process.stdin.flush()
            header = process.stdout.readline(256).decode("ascii").strip().split(" ")
            require(len(header) == 3 and header[:2] == [oid, "blob"] and header[2].isdigit(), "invalid Git blob header")
            size = int(header[2])
            total_bytes += size
            require(size <= MAX_SINGLE_FILE_BYTES and total_bytes <= MAX_TRACKED_BYTES, "tracked bytes exceed reviewed limit")
            hasher, remaining = hashlib.sha256(), size
            while remaining:
                part = process.stdout.read(min(remaining, 1024 * 1024))
                require(bool(part), "truncated Git source blob")
                hasher.update(part)
                remaining -= len(part)
            require(process.stdout.read(1) == b"\n", "missing Git blob terminator")
            expected = hasher.hexdigest()
            if verify_working:
                hasher, observed = hashlib.sha256(), 0
                with open_record(root, path) as handle:
                    while part := handle.read(min(1024 * 1024, size + 1 - observed)):
                        observed += len(part)
                        require(observed <= size, "working file larger than reviewed blob")
                        hasher.update(part)
                require(observed == size and hasher.hexdigest() == expected, "working bytes differ from Git source")
            files.append({"path": path, "sha256": expected, "size": size, "mode": mode})
        process.stdin.close()
        require(process.wait(timeout=10) == 0, "Git blob inventory did not finish")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        process.stdout.close()
        if not process.stdin.closed:
            process.stdin.close()
    return {"schema": "qualification_source_inventory_v2", "files": files}


def clean_checkout(git, root):
    status = git_output(git, root, "status", "--porcelain=v1", "--untracked-files=all", "-z")
    require(status == b"", "qualification checkout is dirty")
    require(not (Path(root) / "data").exists(), "off-host regression checkout contains runtime data")
    require(not (Path(root) / "venv").exists() and not (Path(root) / ".venv").exists(),
            "qualification environment must be outside source checkout")
    # Bytecode from a prior process could disagree with source without changing Git status.
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = [name for name in names if name != ".git"]
        require("__pycache__" not in names and not any(name.endswith((".pyc", ".pyo")) for name in files),
                "checkout contains unbound cached bytecode")
    return True
