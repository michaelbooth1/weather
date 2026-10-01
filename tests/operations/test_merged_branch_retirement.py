from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from weather.operations import merged_branch_retirement as retirement

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _git(repo: Path, *args: str, when: str | None = None) -> str:
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.invalid",
    )
    if when:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _commit(repo: Path, name: str, when: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name, when=when)
    return _git(repo, "rev-parse", "HEAD")


def _merge(repo: Path, branch: str, when: str) -> None:
    _git(repo, "checkout", "-q", "master")
    _git(repo, "merge", "-q", "--no-ff", "-m", f"merge {branch}", branch, when=when)


def _publish(repo: Path, *branches: str) -> None:
    for branch in branches:
        _git(repo, "update-ref", f"refs/remotes/origin/{branch}", branch)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _commit(repo, "base", "2026-09-01T00:00:00+00:00")
    for branch, work_day, merge_day in (
        ("codex/old-landed", "09-10", "09-12"),
        ("codex/recent-landed", "09-10", "09-27"),
    ):
        _git(repo, "checkout", "-q", "-b", branch, "master")
        _commit(repo, branch.replace("/", "-"), f"2026-{work_day}T00:00:00+00:00")
        _merge(repo, branch, f"2026-{merge_day}T00:00:00+00:00")
    _git(repo, "checkout", "-q", "-b", "codex/unmerged", "master")
    _commit(repo, "unmerged", "2026-09-05T00:00:00+00:00")
    _git(repo, "checkout", "-q", "-b", "preserve/kept", "master~1")
    _git(repo, "checkout", "-q", "master")
    _publish(
        repo,
        "master",
        "codex/old-landed",
        "codex/recent-landed",
        "codex/unmerged",
        "preserve/kept",
    )
    return repo


def test_only_branches_landed_before_the_cutoff_are_overdue(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    payload = retirement.find_overdue_branches(repo, now=NOW)

    assert payload["ok"] is True
    assert payload["merged_count"] == 2
    assert [row["branch"] for row in payload["overdue"]] == ["codex/old-landed"]
    assert payload["overdue"][0]["tip"] == _git(repo, "rev-parse", "codex/old-landed")


def test_age_is_measured_from_landing_not_from_the_branch_tip(tmp_path: Path) -> None:
    # Both branches were last committed on 09-10; only the landing date differs.
    repo = _repo(tmp_path)

    payload = retirement.find_overdue_branches(repo, now=NOW, max_age_days=1)

    assert [row["branch"] for row in payload["overdue"]] == [
        "codex/old-landed",
        "codex/recent-landed",
    ]


def test_master_younger_than_the_window_has_nothing_overdue(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    payload = retirement.find_overdue_branches(repo, now=NOW, max_age_days=60)

    assert payload["cutoff_base_commit"] is None
    assert payload["overdue"] == []


def test_cli_json_and_failure_are_machine_readable(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)

    assert retirement.main(["--repo-root", str(repo), "--json", "--max-age-days", "0"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["merged_count"] == 2

    assert retirement.main(["--repo-root", str(tmp_path / "missing"), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
