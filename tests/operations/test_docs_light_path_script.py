"""Executes docs_light_path.ps1 against a fake production repo and a fake push task."""
from __future__ import annotations

import hashlib
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
$payload = @{ verdict = $name; branch = $Branch }
# FAKE_ROLL_JSON scripts a defective JSON beside the exit code.
$mode = [string]$env:FAKE_ROLL_JSON
if ($mode -like "verdict=*") { $payload.verdict = $mode.Substring(8) }
if ($mode -like "branch=*") { $payload.branch = $mode.Substring(7) }
if ($mode -eq "garbage") { Set-Content -Path $JsonOut -Value "{ not json" -Encoding utf8 }
elseif ($mode -ne "missing") { $payload | ConvertTo-Json | Set-Content -Path $JsonOut -Encoding utf8 }
"VERDICT: $name"
exit $code
"""

# Cmdlet shadows: functions win over cmdlets in command lookup, so the script
# under test talks to this fake WeatherOneShotPush. A successful "push" moves
# the tracking ref, exactly as a real push does. Get-Date is shadowed with a
# fixed offset so the local clock reads FAKE_NOW_HHMM today at the start and
# keeps running from there (the push wait still reaches its deadline).
WRAPPER = """$global:FakeClockOffset = [TimeSpan]::Zero
if ($env:FAKE_NOW_HHMM) {
    $real = [datetime]::Now
    $target = $real.Date.Add([TimeSpan]::Parse($env:FAKE_NOW_HHMM))
    $global:FakeClockOffset = $target - $real
}
function global:Get-Date { param([string]$Format)
    $d = [datetime]::Now.Add($global:FakeClockOffset)
    if ($Format) { return $d.ToString($Format) }
    return $d }
function global:Get-ScheduledTask { [CmdletBinding()] param([string]$TaskName)
    if ($env:FAKE_TASK_MISSING) { return }
    [pscustomobject]@{ TaskName = $TaskName; State = $env:FAKE_TASK_STATE } }
function global:Get-ScheduledTaskInfo { [CmdletBinding()] param([string]$TaskName)
    $result = [int]$env:FAKE_PUSH_RESULT
    # After the start, the first FAKE_TRANSIENT_POLLS reads return the stale scheduler code.
    if ($null -ne $global:FakePolls) {
        $global:FakePolls++
        if ($global:FakePolls -le [int]$env:FAKE_TRANSIENT_POLLS) { $result = [int]$env:FAKE_TRANSIENT_RESULT }
    }
    [pscustomobject]@{ LastRunTime = $global:FakeLastRun; LastTaskResult = $result } }
function global:Start-ScheduledTask { [CmdletBinding()] param([string]$TaskName)
    $global:FakeLastRun = Get-Date
    $global:FakePolls = 0
    Set-Content -Path $env:FAKE_STARTED -Value "started"
    if ($env:FAKE_PUSH_RESULT -eq "0") { & git -C $env:FAKE_REPO update-ref refs/remotes/origin/master HEAD } }
$global:FakeLastRun = (Get-Date).AddDays(-1)
$global:FakePolls = $null
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
         task_state: str = "Ready", roll_json: str = "", transient_polls: int = 0,
         transient_result: int = 0x41301, now: str = "07:30") -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, **GIT_ENV, FAKE_SCRIPT=str(SCRIPT), FAKE_REPO=str(fx["repo"]), FAKE_NOW_HHMM=now,
               FAKE_STARTED=str(fx["started"]), FAKE_ROLL_EXIT=str(roll_exit), FAKE_ROLL_JSON=roll_json,
               FAKE_PUSH_RESULT=str(push_result), FAKE_TASK_STATE=task_state,
               FAKE_TRANSIENT_POLLS=str(transient_polls), FAKE_TRANSIENT_RESULT=str(transient_result))
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


@pytest.mark.spawns
@pytest.mark.parametrize("now", ["00:30", "07:30", "11:59"])
def test_clock_window_admits_00_30_to_before_12_00(fx: dict[str, object], now: str) -> None:
    # STATE_OF_PLAY: docs-only by the light path before 12:00, never 12:00-00:30.
    # 07:30 is the production agent's morning docs landing and must stay legal.
    tip = _branch(fx, {"docs/a.md": "two\n"})
    result = _run(fx, tip, "-CheckOnly", now=now)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHECK PASS" in result.stdout


@pytest.mark.spawns
@pytest.mark.parametrize("now", ["12:00", "15:00", "18:00", "23:59", "00:00", "00:29"])
@pytest.mark.parametrize("check_only", [True, False])
def test_clock_window_refuses_12_00_to_00_30_and_changes_nothing(
    fx: dict[str, object], now: str, check_only: bool
) -> None:
    tip = _branch(fx, {"docs/a.md": "two\n"})
    result = _run(fx, tip, *(["-CheckOnly"] if check_only else []), now=now)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "outside the light-path window 00:30-12:00" in result.stdout
    repo = fx["repo"]
    assert isinstance(repo, Path)
    assert _git(repo, "rev-parse", "HEAD") == fx["base"]
    assert not Path(str(fx["started"])).exists()
    assert _receipts(fx) == []


def test_clock_is_checked_again_immediately_before_the_merge() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    step0 = text.index('Assert-LightPathClock "start"')
    step1 = text.index("# ---- 1. repository state")
    pre_merge = text.index('Assert-LightPathClock "before the merge"')
    merge = text.index('$merge = Invoke-Git @("merge", "--no-ff"')
    assert step0 < step1 < pre_merge < merge
    assert "$lightPathWindowStartMinute = 30" in text
    assert "$lightPathWindowEndMinute = 12 * 60" in text


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


@pytest.mark.parametrize(
    "roll_json",
    ["missing", "garbage", "verdict=ROLL-SENSITIVE", "branch=" + "0" * 40, "branch=origin/codex/x"],
    ids=["json-missing", "json-unparseable", "json-verdict-mismatch", "json-other-tip", "json-movable-ref"],
)
@pytest.mark.spawns
def test_exit_zero_without_a_matching_roll_free_json_refuses(fx: dict[str, object], roll_json: str) -> None:
    # Exit 0 alone is not ROLL-FREE: the JSON must name ROLL-FREE for the exact tip.
    repo = fx["repo"]
    assert isinstance(repo, Path)
    tip = _branch(fx, {"docs/a.md": "two\n"})

    result = _run(fx, tip, "-CheckOnly", roll_exit=0, roll_json=roll_json)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "REFUSED: roll verdict JSON" in result.stdout and "CHECK PASS" not in result.stdout, result.stdout
    assert _git(repo, "rev-parse", "HEAD") == fx["base"]
    assert not Path(str(fx["started"])).exists()
    assert _receipts(fx) == []


@pytest.mark.spawns
def test_uncaught_error_exits_one_and_still_prints_it(fx: dict[str, object]) -> None:
    # The default-fail exit is issued from the final finally, which would discard
    # an uncaught error; the error is printed first and the code stays 1.
    repo = fx["repo"]
    assert isinstance(repo, Path)
    tip = _branch(fx, {"docs/a.md": "two\n"})
    # Without the tracking ref, Get-GitCommit throws (no Refuse wraps it).
    _git(repo, "update-ref", "-d", "refs/remotes/origin/master")

    result = _run(fx, tip)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "refs/remotes/origin/master^{commit} failed (exit" in result.stderr, result.stderr
    assert _git(repo, "rev-parse", "HEAD") == fx["base"]
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


@pytest.mark.spawns
@pytest.mark.parametrize("transient", [0x41301, 0x41303])
def test_stale_scheduler_result_in_ready_keeps_polling_until_rc0(fx: dict[str, object], transient: int) -> None:
    # 11-01 07:27: LastTaskResult still read 267009 (0x41301) with State Ready, and the
    # script exited 3 although WeatherOneShotPush finished rc 0 seconds later.
    repo = fx["repo"]
    assert isinstance(repo, Path)
    tip = _branch(fx, {"docs/a.md": "two\n"})

    result = _run(fx, tip, transient_polls=2, transient_result=transient)

    assert result.returncode == 0, result.stdout + result.stderr
    head = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "rev-parse", "origin/master") == head
    [receipt] = _receipts(fx)
    assert receipt["stage"] == "pushed" and receipt["ok"] is True
    assert receipt["push"]["completed"] is True and receipt["push"]["last_task_result"] == 0
    assert receipt["push"]["stale_scheduler_result"] is False


@pytest.mark.spawns
def test_stale_scheduler_result_through_deadline_is_decided_by_origin(fx: dict[str, object]) -> None:
    repo = fx["repo"]
    assert isinstance(repo, Path)
    tip = _branch(fx, {"docs/a.md": "two\n"})

    # The push lands (tracking ref moves) but the result never leaves 0x41301.
    result = _run(fx, tip, "-PushTimeoutSeconds", "30", transient_polls=10_000)

    assert result.returncode == 0, result.stdout + result.stderr
    head = _git(repo, "rev-parse", "HEAD")
    [receipt] = _receipts(fx)
    assert receipt["stage"] == "pushed" and receipt["ok"] is True
    assert receipt["published_commit"] == head
    assert receipt["push"]["completed"] is False
    assert receipt["push"]["stale_scheduler_result"] is True
    assert receipt["push"]["last_task_result"] == 0x41301


@pytest.mark.spawns
def test_stale_scheduler_result_through_deadline_still_fails_on_origin_mismatch(fx: dict[str, object]) -> None:
    repo = fx["repo"]
    assert isinstance(repo, Path)
    tip = _branch(fx, {"docs/a.md": "two\n"})

    # Nothing was published: the step-8 origin/master check must still fail.
    result = _run(fx, tip, "-PushTimeoutSeconds", "30", push_result=0x41301)

    assert result.returncode == 3, result.stdout + result.stderr
    assert _git(repo, "rev-parse", "origin/master") == fx["base"]
    [receipt] = _receipts(fx)
    assert receipt["stage"] == "merged_unpushed" and receipt["ok"] is False
    assert receipt["push"]["stale_scheduler_result"] is True
    assert "not the merge commit" in receipt["detail"]


@pytest.mark.spawns
def test_real_nonzero_after_stale_transient_still_exits_3(fx: dict[str, object]) -> None:
    repo = fx["repo"]
    assert isinstance(repo, Path)
    tip = _branch(fx, {"docs/a.md": "two\n"})

    result = _run(fx, tip, push_result=1, transient_polls=1)

    assert result.returncode == 3, result.stdout + result.stderr
    assert _git(repo, "rev-parse", "origin/master") == fx["base"]
    [receipt] = _receipts(fx)
    assert receipt["stage"] == "merged_unpushed" and receipt["ok"] is False
    assert receipt["push"]["completed"] is True and receipt["push"]["last_task_result"] == 1
    assert receipt["push"]["stale_scheduler_result"] is False


def test_script_text_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "quiet_window_merge_in_progress.json" in text
    assert "--no-ff" in text
    # Publication is only ever the credential-bearing task, never a direct push.
    assert "git push" not in text and '"push"' not in text
    assert "--force" not in text and "reset --hard" not in text
    assert text.index('"--no-ff"') < text.index("Start-ScheduledTask -TaskName $pushTaskName")


# ---- step 3b: frozen bindings (R14) ----

def _frozen_registry(record_sha: str) -> str:
    return json.dumps({"schema": "frozen_bindings/1", "holds": [{
        "id": "B-1", "records": {"docs/rule.md": record_sha},
        "record_globs": ["docs/**/b1-clarification-*.md"],
        "frozen_prefixes": ["docs/bound/"],
        "code": {}, "release_record": "docs/record/b-look-record.md"}]}, indent=1) + "\n"


def _commit_on_master(fx: dict[str, object], files: dict[str, str]) -> None:
    repo = fx["repo"]
    assert isinstance(repo, Path)
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "frozen baseline")
    fx["base"] = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/master", str(fx["base"]))


def _frozen_fx(fx: dict[str, object]) -> None:
    rule = "# rule\n"
    _commit_on_master(fx, {
        "docs/rule.md": rule,
        "docs/x/b1-clarification-1-a.md": "c1\n",
        "docs/bound/plan.md": "plan\n",
        "config/frozen_bindings.json": _frozen_registry(hashlib.sha256(rule.encode()).hexdigest()),
    })


@pytest.mark.spawns
@pytest.mark.parametrize(("files", "message"), [
    ({"docs/rule.md": "# edited rule\n"}, "record docs/rule.md is changed (M)"),
    ({"docs/x/b1-clarification-1-a.md": "c1 edited\n"}, "record docs/x/b1-clarification-1-a.md is changed (M)"),
    ({"docs/bound/new.md": "new\n"}, "docs/bound/new.md is under the frozen prefix docs/bound/"),
], ids=["record", "existing-clarification", "frozen-prefix"])
def test_frozen_binding_refusal_changes_nothing(fx: dict[str, object], files: dict[str, str], message: str) -> None:
    _frozen_fx(fx)
    repo = fx["repo"]
    assert isinstance(repo, Path)
    tip = _branch(fx, files)

    result = _run(fx, tip)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "REFUSED: frozen binding" in result.stdout and message in result.stdout, result.stdout
    assert _git(repo, "rev-parse", "HEAD") == fx["base"]
    assert not Path(str(fx["started"])).exists()
    assert _receipts(fx) == []


@pytest.mark.spawns
def test_frozen_binding_new_clarification_passes(fx: dict[str, object]) -> None:
    _frozen_fx(fx)
    tip = _branch(fx, {"docs/y/b1-clarification-4-coverage-2026-11-02.md": "new clarification\n"})

    result = _run(fx, tip, "-CheckOnly")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "frozen bindings pass (registry present; active holds: B-1)" in result.stdout, result.stdout
    assert "CHECK PASS" in result.stdout


@pytest.mark.spawns
def test_frozen_binding_malformed_registry_refuses(fx: dict[str, object]) -> None:
    _commit_on_master(fx, {"config/frozen_bindings.json": "{ not json\n"})
    repo = fx["repo"]
    assert isinstance(repo, Path)
    tip = _branch(fx, {"docs/a.md": "two\n"})

    result = _run(fx, tip, "-CheckOnly")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "REFUSED: frozen binding: frozen-binding guard: registry config/frozen_bindings.json at" in result.stdout
    assert "is not JSON" in result.stdout, result.stdout
    assert _git(repo, "rev-parse", "HEAD") == fx["base"]


@pytest.mark.spawns
def test_frozen_binding_absent_registry_is_no_holds(fx: dict[str, object]) -> None:
    tip = _branch(fx, {"docs/a.md": "two\n"})
    result = _run(fx, tip, "-CheckOnly")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "frozen bindings pass (registry absent; active holds: )" in result.stdout, result.stdout
