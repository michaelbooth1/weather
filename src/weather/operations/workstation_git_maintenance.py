"""Preserving object-database maintenance for the assigned workstation.

Guards: the 2026-09-110o D4-4 handoff. This fixed route is only reachable through
workstation_heavy.ps1's workstation_offline_v1 lease and kill-on-close Job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Sequence


SCHEMA = "workstation_git_maintenance_v1"
_REF_FORMAT = "%(refname)%00%(objectname)%00%(symref)"
_REFLOG_FORMAT = "%gD%x00%H%x00%gs"
_OBJECT_FORMAT = "%(objectname)"
_OPERATION_MARKERS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_LOG",
    "index.lock",
    "HEAD.lock",
    "rebase-apply",
    "rebase-merge",
    "sequencer",
)


class MaintenanceVerificationError(RuntimeError):
    """Raised when the fixed maintenance command cannot prove preservation."""

    def __init__(self, message: str, report: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.report = report


def _run_git(arguments: Sequence[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if completed.returncode:
        raise MaintenanceVerificationError(
            f"git {' '.join(arguments)} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def _reject_in_progress_operation(git_dirs: Sequence[Path]) -> None:
    for git_dir in git_dirs:
        for name in _OPERATION_MARKERS:
            marker = git_dir / name
            if marker.exists():
                raise MaintenanceVerificationError(
                    f"repository or linked worktree has an in-progress Git operation: {marker}"
                )
    for common_dir in git_dirs[-1:]:
        if (common_dir / "gc.pid").exists() or (common_dir / "maintenance.pid").exists():
            raise MaintenanceVerificationError(
                "repository already has a Git maintenance process"
            )


def _worktree_paths(output: str) -> list[Path]:
    """Extract registered paths from porcelain output (including linked trees)."""

    return [
        Path(line.removeprefix("worktree "))
        for line in output.splitlines()
        if line.startswith("worktree ")
    ]


def _registered_git_dirs(worktree_output: str) -> list[Path]:
    """Resolve each worktree's private gitdir so its operation locks are checked."""

    result: list[Path] = []
    for worktree in _worktree_paths(worktree_output):
        git_dir = Path(
            _run_git(
                ["rev-parse", "--path-format=absolute", "--git-dir"],
                cwd=worktree,
            ).strip()
        ).resolve(strict=True)
        result.append(git_dir)
    if not result:
        raise MaintenanceVerificationError("could not resolve registered worktree gitdirs")
    return result


def _objects_digest(output: str) -> tuple[int, str]:
    object_ids = sorted(line.strip() for line in output.splitlines() if line.strip())
    digest = hashlib.sha256("\n".join(object_ids).encode("ascii")).hexdigest()
    return len(object_ids), digest


def _snapshot(*, root: Path, worktree_output: str | None = None) -> dict[str, object]:
    refs = _run_git(["for-each-ref", f"--format={_REF_FORMAT}"], cwd=root)
    worktrees = worktree_output or _run_git(
        ["worktree", "list", "--porcelain"], cwd=root
    )
    reflogs = [
        _run_git(["reflog", "show", "--all", f"--format={_REFLOG_FORMAT}"], cwd=root)
    ]
    # --all covers shared refs, but HEAD reflogs belong to individual worktrees.
    for worktree in _worktree_paths(worktrees):
        reflogs.append(
            _run_git(
                ["reflog", "show", "HEAD", f"--format={_REFLOG_FORMAT}"],
                cwd=worktree,
            )
        )
    objects = _run_git(
        ["cat-file", "--batch-all-objects", f"--batch-check={_OBJECT_FORMAT}"],
        cwd=root,
    )
    object_count, object_digest = _objects_digest(objects)
    return {
        "refs": refs,
        "worktrees": worktrees,
        "reflogs": "\0WORKTREE\0".join(reflogs),
        "object_count": object_count,
        "objects_sha256": object_digest,
    }


def run_maintenance(*, root: Path | None = None) -> dict[str, object]:
    """Run only the fixed, non-pruning, preservation-checked Git maintenance."""

    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") != "1":
        raise MaintenanceVerificationError("must run through workstation_heavy.ps1")
    if os.environ.get("WEATHER_WORKSTATION_WORKLOAD_KIND") != "git_maintenance":
        raise MaintenanceVerificationError("must use the git_maintenance wrapper kind")

    repo_root = (root or Path.cwd()).resolve(strict=True)
    actual_root = Path(_run_git(["rev-parse", "--show-toplevel"], cwd=repo_root).strip())
    if not _same_path(repo_root, actual_root):
        raise MaintenanceVerificationError("current directory is not the Git worktree root")
    if _run_git(["rev-parse", "--is-bare-repository"], cwd=repo_root).strip() != "false":
        raise MaintenanceVerificationError("bare repositories are outside this maintenance route")
    if not _run_git(["rev-parse", "--verify", "HEAD"], cwd=repo_root).strip():
        raise MaintenanceVerificationError("repository has no verifiable HEAD")

    git_dir = Path(
        _run_git(["rev-parse", "--path-format=absolute", "--git-dir"], cwd=repo_root).strip()
    ).resolve(strict=True)
    common_dir = Path(
        _run_git(
            ["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=repo_root
        ).strip()
    ).resolve(strict=True)
    worktree_output = _run_git(["worktree", "list", "--porcelain"], cwd=repo_root)
    if not worktree_output.strip():
        raise MaintenanceVerificationError("could not enumerate worktree metadata")
    worktree_git_dirs = _registered_git_dirs(worktree_output)
    _reject_in_progress_operation([*worktree_git_dirs, common_dir])

    alternates = common_dir / "objects" / "info" / "alternates"
    if alternates.exists():
        raise MaintenanceVerificationError(
            "object alternates are configured; maintenance refuses to compact a shared object store"
        )

    count_before = _run_git(["count-objects", "-vH"], cwd=repo_root)
    before = _snapshot(root=repo_root, worktree_output=worktree_output)
    repack_args = ["repack", "-a", "-d", "--keep-unreachable"]
    gc_args = [
        "-c",
        "gc.reflogExpire=never",
        "-c",
        "gc.reflogExpireUnreachable=never",
        "-c",
        "gc.worktreePruneExpire=never",
        "gc",
        "--no-prune",
        "--no-detach",
    ]
    _run_git(repack_args, cwd=repo_root)
    _run_git(gc_args, cwd=repo_root)
    after = _snapshot(root=repo_root)
    count_after = _run_git(["count-objects", "-vH"], cwd=repo_root)

    preserved = {
        key: before[key] == after[key]
        for key in ("refs", "worktrees", "reflogs", "object_count", "objects_sha256")
    }
    report: dict[str, object] = {
        "schema": SCHEMA,
        "repository": str(repo_root),
        "commands": [
            ["git", *repack_args],
            ["git", *gc_args],
        ],
        "count_objects_before": count_before,
        "count_objects_after": count_after,
        "preservation": preserved,
        "object_count_before": before["object_count"],
        "object_count_after": after["object_count"],
        "objects_sha256_before": before["objects_sha256"],
        "objects_sha256_after": after["objects_sha256"],
        "git_lfs_accessed": False,
        "history_rewritten": False,
        "prune_now": False,
    }
    if not all(preserved.values()):
        raise MaintenanceVerificationError(
            "Git maintenance changed refs, worktrees, reflogs, or the object inventory", report
        )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        report = run_maintenance()
    except MaintenanceVerificationError as exc:
        print(json.dumps({"schema": SCHEMA, "error": str(exc), "report": exc.report}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
