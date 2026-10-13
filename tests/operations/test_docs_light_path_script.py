"""Executes docs_light_path.ps1 against a fake production repo and a fake push task."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "docs_light_path.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None or shutil.which("git") is None,
    reason="Windows PowerShell 5.1 and git are required",
)

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}

ROLL_VERDICT_STUB = """param([string]$Branch, [string]$JsonOut)
$code = [int]$env:FAKE_ROLL_EXIT
$name = if ($code -eq 0) { "ROLL-FREE" } else { "ROLL-SENSITIVE" }
@{ verdict = $name; branch = $Branch } | ConvertTo-Json | Set-Content -Path $JsonOut -Encoding utf8
"VERDICT: $name"
exit $code
"""

# Cmdlet shadows: functions win over cmdlets in command lookup, so the script
# under test talks to this fake WeatherOneShotPush. A successful "push" moves
# the tracking ref, exactly as a real push does.
WRAPPER = """function global:Get-ScheduledTask { [CmdletBinding()] param([string]$TaskName)
    if ($env:FAKE_TASK_MISSING) { return }
    [pscustomobject]@{ TaskName = $TaskName; State = $env:FAKE_TASK_STATE } }
function global:Get-ScheduledTaskInfo { [CmdletBinding()] param([string]$TaskName)
    [pscustomobject]@{ LastRunTime = $global:FakeLastRun; LastTaskResult = [int]$env:FAKE_PUSH_RESULT } }
function global:Start-ScheduledTask { [CmdletBinding()] param([string]$TaskName)
    $global:FakeLastRun = Get-Date
    Set-Content -Path $env:FAKE_STARTED -Value "started"
    if ($env:FAKE_PUSH_RESULT -eq "0") { & git -C $env:FAKE_REPO update-ref refs/remotes/origin/master HEAD } }
$global:FakeLastRun = (Get-Date).AddDays(-1)
& $env:FAKE_SCRIPT @args
exit $LASTEXITCODE
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            env=dict(os.environ, **GIT_ENV))
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}"
    return result.stdout.strip()


@pytest.fixture()
def fx(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    (repo / "scripts" / "ops").mkdir(parents=True)
    (repo / "scripts" / "ops" / "roll_verdict.ps1").write_text(ROLL_VERDICT_STUB, encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("one\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "locations.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    base = _git(repo, "rev-parse", "HEAD")
    # The remote URL is unreachable, so fetch and ls-remote fail and the script
    # falls back to the tracking ref (a real push under basetemp exceeds MAX_PATH).
    _git(repo, "remote", "add", "origin", str(tmp_path / "missing-origin.git"))
    _git(repo, "update-ref", "refs/remotes/origin/master", base)
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(WRAPPER, encoding="utf-8")
    return {"repo": repo, "base": base, "wrapper": wrapper, "started": tmp_path / "started.txt"}


def _branch(fx: dict[str, object], files: dict[str, str]) -> str:
    repo = fx["repo"]
    assert isinstance(repo, Path)
    _git(repo, "checkout", "-q", "-b", "codex/x")
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "branch")
    tip = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "master")
    _git(repo, "update-ref", "refs/remotes/origin/codex/x", tip)
    return tip


def _run(fx: dict[str, object], tip: str, *extra: str, roll_exit: int = 0, push_result: int = 0,
         task_state: str = "Ready") -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, **GIT_ENV, FAKE_SCRIPT=str(SCRIPT), FAKE_REPO=str(fx["repo"]),
               FAKE_STARTED=str(fx["started"]), FAKE_ROLL_EXIT=str(roll_exit),
               FAKE_PUSH_RESULT=str(push_result), FAKE_TASK_STATE=task_state)
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(fx["wrapper"]),
         "-Branch", "origin/codex/x", "-ExpectedTip", tip, "-RepoRoot", str(fx["repo"]), "-PollSeconds", "1", *extra],
        capture_output=True, text=True, env=env, timeout=120,
    )


def _receipts(fx: dict[str, object]) -> list[dict[str, object]]:
    repo = fx["repo"]
    assert isinstance(repo, Path)
    folder = repo / "data" / "alerts" / "quiet_window_merge_reconciliations"
    if not folder.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("docs-light-*.json"))]


def test_publishes_docs_only_branch_with_receipt(fx: dict[str, object]) -> None:
    repo = fx["repo"]
    assert isinstance(repo, Path)
    tip = _branch(fx, {"docs/a.md": "two\n", "docs/sub/b.md": "new\n"})
    # Fleet-generated drift outside docs/ is left exactly as found.
    (repo / "config" / "locations.json").write_text('{"refreshed": true}\n', encoding="utf-8")

    result = _run(fx, tip)

    assert result.returncode == 0, result.stdout + result.stderr
    head = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "rev-parse", "HEAD^1", "HEAD^2").split() == [fx["base"], tip]
    assert _git(repo, "rev-parse", "origin/master") == head
    assert _git(repo, "log", "-1", "--format=%s") == "Merge codex/x into master (fail-forward light path, docs only)"
    assert (repo / "config" / "locations.json").read_text(encoding="utf-8") == '{"refreshed": true}\n'
    [receipt] = _receipts(fx)
    assert receipt["schema"] == "docs_light_path_receipt_v0.1"
    assert receipt["stage"] == "pushed" and receipt["ok"] is True
    assert receipt["expected_tip"] == tip
    assert receipt["pre_merge_head"] == fx["base"] == receipt["origin_master_before"]
    assert receipt["merge_commit"] == receipt["published_commit"] == head
    assert receipt["publication_verified_by"] == "tracking_ref"
    assert sorted(receipt["branch_diff_paths"]) == ["docs/a.md", "docs/sub/b.md"]
    assert receipt["unrelated_dirty_paths"] == ["config/locations.json"]
    assert receipt["roll_verdict"]["exit_code"] == 0
    assert receipt["push"]["completed"] is True and receipt["push"]["last_task_result"] == 0


def test_check_only_changes_nothing(fx: dict[str, object]) -> None:
    tip = _branch(fx, {"docs/a.md": "two\n"})
    result = _run(fx, tip, "-CheckOnly")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHECK PASS" in result.stdout
    repo = fx["repo"]
    assert isinstance(repo, Path)
    assert _git(repo, "rev-parse", "HEAD") == fx["base"]
    assert not Path(str(fx["started"])).exists()
    assert _receipts(fx) == []


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("code_file", "not docs/**/*.md only: src/x.py"),
        ("docs_non_markdown", "not docs/**/*.md only: docs/img.png"),
        ("roll_sensitive", "not ROLL-FREE"),
        ("wrong_tip", "expected 0000000000000000000000000000000000000000"),
        ("marker", "quiet-merge marker exists"),
        ("behind_origin", "is not origin/master"),
        ("task_running", "WeatherOneShotPush is Running"),
        ("dirty_docs", "tracked docs files are modified"),
    ],
)
def test_refusals_change_nothing(fx: dict[str, object], case: str, message: str) -> None:
    repo = fx["repo"]
    assert isinstance(repo, Path)
    files = {"docs/a.md": "two\n"}
    if case == "code_file":
        files["src/x.py"] = "x = 1\n"
    if case == "docs_non_markdown":
        files["docs/img.png"] = "png\n"
    tip = _branch(fx, files)
    kwargs: dict[str, object] = {}
    if case == "roll_sensitive":
        kwargs["roll_exit"] = 3
    if case == "wrong_tip":
        tip = "0" * 40
    if case == "marker":
        (repo / "data" / "alerts").mkdir(parents=True)
        (repo / "data" / "alerts" / "quiet_window_merge_in_progress.json").write_text("{}", encoding="utf-8")
    if case == "behind_origin":
        _git(repo, "update-ref", "refs/remotes/origin/master", _git(repo, "rev-parse", "origin/codex/x"))
    if case == "task_running":
        kwargs["task_state"] = "Running"
    if case == "dirty_docs":
        (repo / "docs" / "a.md").write_text("local edit\n", encoding="utf-8")

    result = _run(fx, tip, **kwargs)  # type: ignore[arg-type]

    assert result.returncode == 1, result.stdout + result.stderr
    assert "REFUSED" in result.stdout and message in result.stdout, result.stdout
    assert _git(repo, "rev-parse", "HEAD") == fx["base"]
    assert not Path(str(fx["started"])).exists()
    assert _receipts(fx) == []


def test_failed_push_leaves_merge_unpublished_with_receipt(fx: dict[str, object]) -> None:
    repo = fx["repo"]
    assert isinstance(repo, Path)
    tip = _branch(fx, {"docs/a.md": "two\n"})

    result = _run(fx, tip, push_result=1)

    assert result.returncode == 3, result.stdout + result.stderr
    head = _git(repo, "rev-parse", "HEAD")
    assert head != fx["base"]
    assert _git(repo, "rev-parse", "origin/master") == fx["base"]
    [receipt] = _receipts(fx)
    assert receipt["stage"] == "merged_unpushed" and receipt["ok"] is False
    assert receipt["merge_commit"] == head
    assert receipt["push"]["last_task_result"] == 1


def test_script_text_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "quiet_window_merge_in_progress.json" in text
    assert "--no-ff" in text
    # Publication is only ever the credential-bearing task, never a direct push.
    assert "git push" not in text and '"push"' not in text
    assert "--force" not in text and "reset --hard" not in text
    assert text.index('"--no-ff"') < text.index("Start-ScheduledTask -TaskName $pushTaskName")
