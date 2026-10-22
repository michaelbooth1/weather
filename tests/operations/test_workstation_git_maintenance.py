"""Fixture checks for the fixed workstation Git-maintenance operation.

Guards: workstation handoff 2026-09-110o D4-4; preserve refs, worktrees,
reflogs and the complete object inventory without pruning or touching Git LFS.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weather.operations import workstation_git_maintenance as maintenance


OID_A = "a" * 40
OID_B = "b" * 40


def _fixture_git(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    mutate_after: str = "",
    linked_operation: str = "",
) -> list[list[str]]:
    git_dir = root / ".git"
    (git_dir / "objects" / "info").mkdir(parents=True)
    linked_root = root / "linked-worktree"
    linked_git_dir = git_dir / "worktrees" / "linked-worktree"
    if linked_operation:
        linked_root.mkdir()
        linked_git_dir.mkdir(parents=True)
        marker = linked_git_dir / linked_operation
        if linked_operation.endswith("-merge"):
            marker.mkdir()
        else:
            marker.write_text("in progress\n", encoding="ascii")
    calls: list[list[str]] = []
    completed = False
    counts = 0

    def run_git(arguments, *, cwd):
        nonlocal completed, counts
        values = list(arguments)
        calls.append(values)
        if values == ["rev-parse", "--show-toplevel"]:
            return str(root)
        if values == ["rev-parse", "--is-bare-repository"]:
            return "false\n"
        if values == ["rev-parse", "--verify", "HEAD"]:
            return f"{OID_A}\n"
        if values == ["rev-parse", "--path-format=absolute", "--git-dir"]:
            return f"{linked_git_dir if cwd == linked_root else git_dir}\n"
        if values == ["rev-parse", "--path-format=absolute", "--git-common-dir"]:
            return f"{git_dir}\n"
        if values == ["worktree", "list", "--porcelain"]:
            if linked_operation:
                return (
                    f"worktree {root}\nHEAD {OID_A}\nbranch refs/heads/main\n\n"
                    f"worktree {linked_root}\nHEAD {OID_A}\ndetached\n"
                )
            if completed and mutate_after == "worktrees":
                return f"worktree {root}\nHEAD {OID_B}\nbranch refs/heads/other\n"
            return f"worktree {root}\nHEAD {OID_A}\nbranch refs/heads/main\n"
        if values[0] == "count-objects":
            counts += 1
            return f"count: {counts}\nin-pack: 2\n"
        if values[0] == "for-each-ref":
            oid = OID_B if completed and mutate_after == "refs" else OID_A
            return f"refs/heads/main\0{oid}\0\n"
        if values[0] == "reflog":
            oid = OID_B if completed and mutate_after == "reflogs" else OID_A
            return f"HEAD@{{0}}\0{oid}\0commit: fixture\n"
        if values[0] == "cat-file":
            ids = [OID_A, OID_B] if completed and mutate_after == "objects" else [OID_A]
            return "".join(f"{oid}\n" for oid in ids)
        if values == ["repack", "-a", "-d", "--keep-unreachable"]:
            return ""
        if values == [
            "-c",
            "gc.reflogExpire=never",
            "-c",
            "gc.reflogExpireUnreachable=never",
            "-c",
            "gc.worktreePruneExpire=never",
            "gc",
            "--no-prune",
            "--no-detach",
        ]:
            completed = True
            return ""
        raise AssertionError(f"unexpected Git command: {values!r}")

    monkeypatch.setattr(maintenance, "_run_git", run_git)
    return calls


def test_fixed_route_keeps_refs_worktrees_reflogs_and_every_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fixture_git(monkeypatch, tmp_path)
    monkeypatch.setenv("WEATHER_WORKSTATION_WRAPPER_ACTIVE", "1")
    monkeypatch.setenv("WEATHER_WORKSTATION_WORKLOAD_KIND", "git_maintenance")

    report = maintenance.run_maintenance(root=tmp_path)

    assert report["schema"] == "workstation_git_maintenance_v1"
    assert all(report["preservation"].values())
    assert report["git_lfs_accessed"] is False
    assert report["history_rewritten"] is False
    assert report["prune_now"] is False
    assert calls[-2:] == [
        ["repack", "-a", "-d", "--keep-unreachable"],
        [
            "-c",
            "gc.reflogExpire=never",
            "-c",
            "gc.reflogExpireUnreachable=never",
            "-c",
            "gc.worktreePruneExpire=never",
            "gc",
            "--no-prune",
            "--no-detach",
        ],
    ]
    assert all("lfs" not in " ".join(command).lower() for command in calls)


@pytest.mark.parametrize("mutated", ("refs", "worktrees", "reflogs", "objects"))
def test_route_fails_closed_if_preserved_state_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutated: str
) -> None:
    _fixture_git(monkeypatch, tmp_path, mutate_after=mutated)
    monkeypatch.setenv("WEATHER_WORKSTATION_WRAPPER_ACTIVE", "1")
    monkeypatch.setenv("WEATHER_WORKSTATION_WORKLOAD_KIND", "git_maintenance")

    with pytest.raises(maintenance.MaintenanceVerificationError, match="changed") as exc_info:
        maintenance.run_maintenance(root=tmp_path)

    assert exc_info.value.report is not None


@pytest.mark.parametrize("marker", ("MERGE_HEAD", "rebase-merge", "index.lock"))
def test_route_refuses_an_in_progress_operation_before_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, marker: str
) -> None:
    calls = _fixture_git(monkeypatch, tmp_path)
    git_dir = tmp_path / ".git"
    path = git_dir / marker
    if marker.endswith("-merge"):
        path.mkdir()
    else:
        path.write_text("in progress\n", encoding="ascii")
    monkeypatch.setenv("WEATHER_WORKSTATION_WRAPPER_ACTIVE", "1")
    monkeypatch.setenv("WEATHER_WORKSTATION_WORKLOAD_KIND", "git_maintenance")

    with pytest.raises(maintenance.MaintenanceVerificationError, match="in-progress Git operation"):
        maintenance.run_maintenance(root=tmp_path)

    assert not any(command and command[0] == "repack" for command in calls)


def test_route_refuses_an_in_progress_linked_worktree_before_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fixture_git(monkeypatch, tmp_path, linked_operation="rebase-merge")
    monkeypatch.setenv("WEATHER_WORKSTATION_WRAPPER_ACTIVE", "1")
    monkeypatch.setenv("WEATHER_WORKSTATION_WORKLOAD_KIND", "git_maintenance")

    with pytest.raises(maintenance.MaintenanceVerificationError, match="in-progress Git operation"):
        maintenance.run_maintenance(root=tmp_path)

    assert not any(command and command[0] == "repack" for command in calls)


def test_route_refuses_object_alternates_before_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fixture_git(monkeypatch, tmp_path)
    alternates = tmp_path / ".git/objects/info/alternates"
    alternates.write_text("shared-object-database\n", encoding="ascii")
    monkeypatch.setenv("WEATHER_WORKSTATION_WRAPPER_ACTIVE", "1")
    monkeypatch.setenv("WEATHER_WORKSTATION_WORKLOAD_KIND", "git_maintenance")

    with pytest.raises(maintenance.MaintenanceVerificationError, match="alternates"):
        maintenance.run_maintenance(root=tmp_path)

    assert not any(command and command[0] == "repack" for command in calls)


def test_route_rejects_direct_invocation_before_git_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        maintenance,
        "_run_git",
        lambda arguments, *, cwd: calls.append(list(arguments)) or "",
    )
    monkeypatch.delenv("WEATHER_WORKSTATION_WRAPPER_ACTIVE", raising=False)
    monkeypatch.delenv("WEATHER_WORKSTATION_WORKLOAD_KIND", raising=False)

    with pytest.raises(maintenance.MaintenanceVerificationError, match="workstation_heavy"):
        maintenance.run_maintenance(root=tmp_path)

    assert calls == []


def test_route_rejects_a_different_git_worktree_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other_root = tmp_path / "elsewhere"
    other_root.mkdir()
    _fixture_git(monkeypatch, other_root)
    monkeypatch.setenv("WEATHER_WORKSTATION_WRAPPER_ACTIVE", "1")
    monkeypatch.setenv("WEATHER_WORKSTATION_WORKLOAD_KIND", "git_maintenance")

    with pytest.raises(maintenance.MaintenanceVerificationError, match="not the Git worktree root"):
        maintenance.run_maintenance(root=tmp_path)
