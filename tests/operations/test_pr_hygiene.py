import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.operations import pr_hygiene as hygiene

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """Real local repository: merged, conflicting, clean-python and clean-docs branches."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / "shared.txt").write_text("base\n")
    (root / "docs" / "roadmap").mkdir(parents=True)
    (root / "docs" / "roadmap" / "workstation-handoff-2026-09-110z-reward-scan-and-read-tools.md").write_text("h\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    heads = {}

    def branch(name, path, text):
        git(root, "checkout", "-q", "-b", name, "master")
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", name)
        heads[name] = git(root, "rev-parse", "HEAD")
        git(root, "checkout", "-q", "master")

    branch("merged", "docs/merged.md", "m\n")
    git(root, "merge", "-q", "--no-ff", "-m", "land merged", "merged")
    branch("conflict", "shared.txt", "branch side\n")
    branch("codex/reward-scan-20260928", "src/weather/market/reward_scan.py", "x = 1\n")
    branch("docs-only", "docs/note.md", "n\n")
    (root / "shared.txt").write_text("master side\n")
    git(root, "commit", "-q", "-am", "master moves")
    work = root / "docs" / "roadmap" / "work"
    work.mkdir()
    (work / "W-0042.yaml").write_text(json.dumps({"id": "W-0042", "branch": "docs-only", "pr": None}))
    return root, heads


def pr(number, branch, head, *, created="2026-09-27T12:00:00Z", updated="2026-09-28T12:00:00Z", checks=("SUCCESS",),
       title=None):
    return dict(number=number, title=title or branch, headRefName=branch, headRefOid=head, baseRefName="master",
                isDraft=True, createdAt=created, updatedAt=updated, author={"login": "fixture"}, mergeable="UNKNOWN",
                statusCheckRollup=[{"conclusion": c} for c in checks], url=f"https://github.com/o/r/pull/{number}",
                body="")


def runner_with(prs):
    def run(argv, **kwargs):
        if argv[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(prs), stderr="")
        assert argv[0] == "git"
        return subprocess.run(argv, **kwargs)
    return run


def test_report_classifies_ancestry_conflicts_roll_class_links_and_actions(repo):
    root, heads = repo
    prs = [pr(1, "merged", heads["merged"]),
           pr(2, "conflict", heads["conflict"]),
           pr(3, "codex/reward-scan-20260928", heads["codex/reward-scan-20260928"], title="110z part 1: reward scan"),
           pr(4, "docs-only", heads["docs-only"]),
           pr(5, "docs-only", heads["docs-only"], checks=("FAILURE", "SUCCESS")),
           pr(6, "gone", "f" * 40),
           pr(7, "docs-only", heads["docs-only"], updated="2026-09-01T00:00:00Z"),
           pr(8, "docs-only", heads["docs-only"], checks=("IN_PROGRESS",))]
    report = hygiene.build_report(base="master", root=root, now=NOW, runner=runner_with(prs))
    rows = {r["number"]: r for r in report["prs"]}
    assert rows[1]["merged_by_ancestry"] is True and rows[1]["proposed_action"] == "close_as_already_in_base"
    assert rows[2]["conflicts"] is True and rows[2]["conflicted_files"] == ["shared.txt"]
    assert rows[2]["proposed_action"] == "merge_base_into_branch_and_resolve" and rows[2]["behind_base"] == 1
    assert rows[3]["roll_class"] == "possibly_sensitive" and rows[3]["file_classes"] == {"src_python": 1}
    assert rows[3]["handoffs"] == ["docs/roadmap/workstation-handoff-2026-09-110z-reward-scan-and-read-tools.md"]
    assert rows[3]["proposed_action"] == "production_review_then_roll_verdict_and_quiet_window"
    assert rows[4]["roll_class"] == "roll_free" and rows[4]["work_records"] == ["W-0042"]
    assert rows[4]["proposed_action"] == "production_review_then_land_any_hour" and rows[4]["conflicts"] is False
    assert rows[4]["age_days"] == 2.0 and rows[4]["age_days_since_update"] == 1.0
    assert rows[5]["ci"] == "failing" and rows[5]["proposed_action"] == "fix_ci"
    assert rows[6]["head_available"] is False and rows[6]["proposed_action"] == "fetch_then_rerun"
    assert rows[7]["proposed_action"] == "review_or_close_stale"
    assert rows[8]["ci"] == "pending" and rows[8]["proposed_action"] == "wait_for_ci"
    assert report["work_records_available"] is True and report["open_prs"] == 8
    markdown = hygiene.render_markdown(report)
    assert "**close_as_already_in_base**" in markdown and "| [#3](https://github.com/o/r/pull/3)" in markdown
    # Nothing moved: no ref, branch or remote changed.
    assert git(root, "for-each-ref", "--format=%(refname)").splitlines() == sorted(
        ["refs/heads/master", "refs/heads/merged", "refs/heads/conflict", "refs/heads/codex/reward-scan-20260928",
         "refs/heads/docs-only"])


@pytest.mark.parametrize("argv", [
    ["gh", "pr", "close", "1"], ["gh", "pr", "merge", "1"], ["gh", "api", "repos"], ["git", "push", "origin"],
    ["git", "fetch", "origin"], ["git", "merge", "x"], ["git", "branch", "-D", "x"],
    ["git", "merge-base", "--is-ancestor", "f" * 40, "master; rm"],
    ["git", "merge-tree", "--write-tree", "--name-only", "--no-messages", "master", "HEAD"],
    ["git", "rev-list", "--count", "--all"],
    ["gh", "pr", "list", "--state", "all", "--limit", "5", "--json", hygiene.PR_FIELDS],
    ["gh", "pr", "list", "--state", "open", "--limit", "500", "--json", hygiene.PR_FIELDS],
])
def test_allow_list_refuses_mutating_or_malformed_commands(argv):
    def never(*args, **kwargs):
        raise AssertionError("command executed")
    with pytest.raises(hygiene.CommandRefused):
        hygiene.run_readonly(argv, runner=never)


def test_file_class_heuristic():
    assert hygiene.classify_files(["docs/a.md", "README.md", "config/x.json", "scripts/ops/y.ps1", "tests/t.py"])[1] == "roll_free"
    assert hygiene.classify_files(["src/weather/schema_registry_recent_data.py"])[1] == "sensitive_all_closures"
    assert hygiene.classify_files(["requirements.txt"])[1] == "unclassified"
    assert hygiene.classify_files([]) == ({}, "roll_free")


def test_missing_base_or_gh_failure_is_explicit(repo):
    root, _ = repo
    with pytest.raises(hygiene.CommandRefused, match="base_ref_unavailable"):
        hygiene.build_report(base="origin/nothing", root=root, now=NOW, runner=runner_with([]))

    def gh_fails(argv, **kwargs):
        if argv[0] == "gh":
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="auth")
        return subprocess.run(argv, **kwargs)
    with pytest.raises(hygiene.CommandRefused, match="gh_pr_list_failed"):
        hygiene.build_report(base="master", root=root, now=NOW, runner=gh_fails)


def test_cli_writes_json_and_markdown(tmp_path, monkeypatch, capsys):
    report = dict(report="pr_hygiene", generated_at_utc=NOW.isoformat(), base="origin/master", open_prs=0,
                  limit_reached=False, work_records_available=False, action_counts={}, prs=[], notes=[])
    monkeypatch.setattr(hygiene, "build_report", lambda **kw: report)
    assert hygiene.main(["--out", str(tmp_path)]) == 0
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".json", ".md"]
    assert "no work records in this checkout" in capsys.readouterr().out
    assert hygiene.main(["--base", "origin/master; rm", "--out", str(tmp_path)]) == 2
