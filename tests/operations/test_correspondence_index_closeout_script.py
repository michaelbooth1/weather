"""Executes correspondence_index_closeout.ps1 against a throwaway repo and bare origin.

Guards: option D of the correspondence-index design (branches never commit the
generated index; the closeout regenerates it in one idempotent command).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "correspondence_index_closeout.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
PACKAGE_FILES = (
    "src/weather/__init__.py", "src/weather/paths.py", "src/weather/reporting/__init__.py",
    "src/weather/reporting/roadmap/__init__.py", "src/weather/reporting/roadmap/correspondence_index.py",
)
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_DATE": "2026-09-24T12:00:00+00:00",
           "GIT_COMMITTER_DATE": "2026-09-24T12:00:00+00:00"}

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None or shutil.which("git") is None,
                       reason="Windows PowerShell 5.1 and git are required"),
]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            env=dict(os.environ, **GIT_ENV))
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}"
    return result.stdout.strip()


def _closeout(repo: Path, worktrees: Path) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-RepoRoot", str(repo), "-PythonPath", sys.executable, "-WorktreeRoot", str(worktrees)],
        capture_output=True, text=True, timeout=300, env=dict(env, **GIT_ENV),
    )


def _value(output: str, key: str) -> str:
    return next(line.split("=", 1)[1] for line in output.splitlines() if line.startswith(key + "="))


@pytest.fixture()
def fx(tmp_path: Path) -> dict[str, Path]:
    origin = tmp_path / "o.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "master", str(origin))
    repo = tmp_path / "r"
    _git(tmp_path, "init", "-q", "-b", "master", str(repo))
    for relative in PACKAGE_FILES:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    report = repo / "docs" / "roadmap" / "agent-report-2026-09-24a-topic.md"
    report.parent.mkdir(parents=True)
    report.write_text("# Topic\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "a report lands without the index (option D)")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "master")
    return {"repo": repo, "origin": origin, "worktrees": tmp_path / "w"}


def test_closeout_regenerates_pushes_a_branch_and_is_idempotent(fx):
    repo, worktrees = fx["repo"], fx["worktrees"]
    first = _closeout(repo, worktrees)
    assert first.returncode == 0, first.stdout + first.stderr
    branch, tip = _value(first.stdout, "CLOSEOUT_BRANCH"), _value(first.stdout, "CLOSEOUT_TIP")
    base = _git(repo, "rev-parse", "origin/master")
    assert branch == f"origin/docs/correspondence-index-closeout-{base[:12]}"
    remote_tip = _git(fx["origin"], "rev-parse", branch.removeprefix("origin/"))
    assert remote_tip == tip
    changed = _git(fx["origin"], "diff", "--name-only", f"{base}..{tip}").splitlines()
    assert changed == ["docs/roadmap/correspondence-index.md",
                       "docs/roadmap/correspondence-index/2026-09.md"]
    assert "agent-report-2026-09-24a-topic.md" in _git(
        fx["origin"], "show", f"{tip}:docs/roadmap/correspondence-index/2026-09.md")
    # The temporary worktree is always removed.
    assert _git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1

    # Same origin/master: reuses the pushed branch, same tip.
    again = _closeout(repo, worktrees)
    assert again.returncode == 0, again.stdout + again.stderr
    assert _value(again.stdout, "CLOSEOUT_TIP") == tip
    assert "reusing" in again.stdout

    # After the closeout lands, the command is a no-op.
    _git(fx["origin"], "update-ref", "refs/heads/master", tip)
    landed = _closeout(repo, worktrees)
    assert landed.returncode == 0, landed.stdout + landed.stderr
    assert "unchanged" in landed.stdout
    assert "CLOSEOUT_TIP" not in landed.stdout


def test_closeout_refuses_a_branch_name_that_carries_another_tree(fx):
    repo, worktrees = fx["repo"], fx["worktrees"]
    base = _git(repo, "rev-parse", "origin/master")
    # Someone pushed a different commit under the deterministic closeout name.
    _git(fx["origin"], "update-ref", f"refs/heads/docs/correspondence-index-closeout-{base[:12]}", base)
    result = _closeout(repo, worktrees)
    assert result.returncode == 1
    assert "different tree" in result.stdout
    assert _git(fx["origin"], "rev-parse", f"docs/correspondence-index-closeout-{base[:12]}") == base
