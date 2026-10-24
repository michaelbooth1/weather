"""Executes a generated night sequencer script against a fake production repository.

Guards: INTEGRATION_ATTEMPT_RUNBOOK "Create and register attempt N": exact tip, production master equal to
origin/master, binding roll_verdict.ps1 (never derived by hand), suite/merge windows (merge 01:00-03:40,
>= 30 min after the suite), and "registration is an external scheduler change and requires explicit
operator authorization": the generated script never registers, starts or stops a task. Stacked heads wait
for their base to land; a head whose base master has moved past is refused (OD35).
"""

from __future__ import annotations

import codecs
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from weather.operations import night_sequencer as ns
from weather.operations.landing_preflight import plan_content_sha256

POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
GIT = shutil.which("git")

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None or GIT is None,
                       reason="Windows PowerShell 5.1 and git are required"),
]

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}

# Functions win over cmdlets in PowerShell command lookup: every Scheduler mutation is journalled,
# and Get-ScheduledTask reports the running tasks named in FAKE_RUNNING.
WRAPPER = r"""
function global:Journal([string]$line) { Add-Content -LiteralPath $env:FAKE_JOURNAL -Value $line -Encoding UTF8 }
foreach ($name in @("Register-ScheduledTask", "Unregister-ScheduledTask", "Start-ScheduledTask",
        "Stop-ScheduledTask", "Enable-ScheduledTask", "Disable-ScheduledTask", "Set-ScheduledTask")) {
    $body = [scriptblock]::Create("Journal 'MUTATION $name'")
    Set-Item -Path ("function:global:" + $name) -Value $body
}
function global:Get-ScheduledTask { [CmdletBinding()] param([string]$TaskName)
    foreach ($n in @(($env:FAKE_RUNNING -split ",") | Where-Object { $_ })) {
        [pscustomobject]@{ TaskName = $n; State = "Running" } } }
& $env:FAKE_SCRIPT @args
exit $LASTEXITCODE
"""

FAKE_ADMISSION = r"""
function Get-WeatherHeavyWorkloadLeaseState { param([string]$RepoRoot)
    return [pscustomobject]@{ Active = ($env:FAKE_LEASE -eq "held"); Path = "x"; Owner = $null } }
function Enter-WeatherHeavyWorkloadLease { Journal "MUTATION Enter-WeatherHeavyWorkloadLease" }
"""
FAKE_ROLL = 'param([string]$Branch, [string]$Base = "master")\nJournal "ROLL $Branch"\nexit [int]$env:FAKE_ROLL_EXIT\n'
FAKE_NEW_ATTEMPT = r"""
param([string]$AttemptRoot, [string]$AttemptId, [string]$BranchRef, [string]$WorktreeRoot, [string]$ExpectedTip,
      [string]$GitExecutablePath, [datetime]$SuiteAtLocal, [datetime]$MergeAtLocal, [string]$ReviewReference)
New-Item -ItemType Directory -Path $AttemptRoot | Out-Null
Set-Content -LiteralPath (Join-Path $AttemptRoot "manifest.json") -Value "{}" -Encoding ASCII
Journal ("CREATE {0} {1} {2} {3:HH:mm} {4:HH:mm} wt={5}" -f $AttemptId, $BranchRef, $ExpectedTip, $SuiteAtLocal, $MergeAtLocal, (Test-Path $WorktreeRoot))
Write-Host ("Manifest SHA256: " + ("ab" * 32))
"""
FAKE_REGISTER = 'Journal "MUTATION register_integration_attempt"\n'


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run([GIT, "-C", str(repo), *args], capture_output=True, text=True,
                            env=dict(os.environ, **GIT_ENV))
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}"
    return result.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _pregate(base: str) -> dict:
    return {"verdict": "PASS", "receipt_sha256": "e" * 64, "base": base, "base_is_ancestor": True}


@pytest.fixture()
def fx(tmp_path: Path) -> dict:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "master", str(origin))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    ops = repo / "scripts" / "ops"
    ops.mkdir(parents=True)
    for name, text in (("workload_admission.ps1", FAKE_ADMISSION), ("roll_verdict.ps1", FAKE_ROLL),
                       ("new_integration_attempt.ps1", FAKE_NEW_ATTEMPT),
                       ("register_integration_attempt.ps1", FAKE_REGISTER)):
        (ops / name).write_text(text, encoding="utf-8")
    (repo / ".gitignore").write_text("data/\n", encoding="utf-8")
    base = _commit(repo, "base.txt")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "master")
    rs_head, rf_head, alone_head = (f"claude/integration-20261014-n9-{n}" for n in ("rs", "rf", "rf-alone"))
    _git(repo, "checkout", "-q", "-b", rs_head, base)
    rs = _commit(repo, "rs.txt")
    _git(repo, "checkout", "-q", "-b", rf_head)
    rf = _commit(repo, "rf.txt")
    _git(repo, "checkout", "-q", "-b", alone_head, base)
    alone = _commit(repo, "alone.txt")
    _git(repo, "checkout", "-q", "master")
    _git(repo, "push", "-q", "origin", rs_head, rf_head, alone_head)

    plan = {
        "schema": "landing_night_plan_v0.1", "night": "2026-10-14", "master_sha": base,
        "fallback_heads": [{"head": alone_head, "sha": alone, "stacked_on": f"master {base}",
                            "expected_roll_class": "ROLL-FREE", "pregate": _pregate(base)}],
        "slots": [
            {"kind": "rs_guarded_merge", "head": rs_head, "sha": rs, "exec": 1, "stacked_on": f"master {base}",
             "expected_roll_class": "ROLL-SENSITIVE", "pregate": _pregate(base)},
            {"kind": "rf_guarded_merge", "head": rf_head, "sha": rf, "exec": 2, "stacked_on": f"{rs_head} {rs}",
             "expected_roll_class": "ROLL-FREE", "pregate": _pregate(base)},
        ],
    }
    plan["plan_sha256"] = plan_content_sha256(plan)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    out = tmp_path / "out"
    assert ns.generate(plan_path, out)["blocking"] is False
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(WRAPPER, encoding="utf-8")
    return {"tmp": tmp_path, "repo": repo, "script": out / "sequencer-2026-10-14.ps1", "wrapper": wrapper,
            "journal": tmp_path / "journal.txt", "rs": rs, "rf": rf, "alone": alone, "rs_head": rs_head,
            "base": base, "plan": plan, "out": out}


def _run(fx: dict, unit: str, *, now: str = "2026-10-14T00:10:00", roll: int = 3, lease: str = "free",
         running: str = "", execute: bool = False, extra: tuple[str, ...] = ()) -> tuple[int, str, list[str]]:
    env = dict(os.environ, **GIT_ENV, FAKE_SCRIPT=str(fx["script"]), FAKE_JOURNAL=str(fx["journal"]),
               FAKE_ROLL_EXIT=str(roll), FAKE_LEASE=lease, FAKE_RUNNING=running)
    argv = [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(fx["wrapper"]),
            "-Unit", unit, "-WorktreeParent", str(fx["tmp"] / "wt"), "-GitExecutablePath", GIT, "-Now", now]
    if execute:
        argv.append("-Execute")
    argv.extend(extra)
    result = subprocess.run(argv, cwd=fx["repo"], capture_output=True, text=True, env=env, timeout=120)
    journal = fx["journal"].read_text(encoding="utf-8-sig").splitlines() if fx["journal"].exists() else []
    return result.returncode, result.stdout + result.stderr, journal


def _land(fx: dict, sha: str) -> None:
    _git(fx["repo"], "merge", "-q", "--no-ff", "-m", "land", sha)
    _git(fx["repo"], "push", "-q", "origin", "master")


def test_generated_script_is_bom_utf8_and_refuses_an_unknown_unit(fx):
    raw = fx["script"].read_bytes()
    assert raw.startswith(codecs.BOM_UTF8)
    assert f"requires_landed = @('{fx['rs']}')" in raw.decode("utf-8-sig")
    code, out, _ = _run(fx, "nope")
    assert code != 0 and "Unknown unit 'nope'" in out


def test_dry_run_is_ready_with_runbook_windows_and_creates_nothing(fx):
    code, out, journal = _run(fx, "n9-rs")
    assert code == 0, out
    assert "VERDICT=READY dry; nothing created" in out
    assert "suite=2026-10-14T00:35:00 merge=2026-10-14T01:05:00" in out  # first suite at 00:35
    assert "attempt=20261014-n9-rs-a1" in out
    assert journal == ["ROLL origin/claude/integration-20261014-n9-rs"]
    assert not (fx["repo"] / "data").exists() and not (fx["tmp"] / "wt").exists()


def test_stacked_unit_waits_for_its_base_then_execute_creates_but_never_registers(fx):
    code, out, _ = _run(fx, "n9-rf", roll=0)
    assert code == 3 and "VERDICT=WAIT prerequisite" in out, out
    _land(fx, fx["rs"])
    code, out, journal = _run(fx, "n9-rf", roll=0, now="2026-10-14T01:40:20", execute=True)
    assert code == 0 and "VERDICT=CREATED" in out, out
    create = [line for line in journal if line.startswith("CREATE ")]
    # 01:40:20 + 3 min, rounded up to the minute -> 01:44; merge 30 minutes later.
    assert create == [f"CREATE 20261014-n9-rf-a1 origin/claude/integration-20261014-n9-rf {fx['rf']} 01:44 02:14 wt=True"]
    assert not [line for line in journal if line.startswith("MUTATION")]
    assert "register_integration_attempt.ps1 -ManifestPath" in out and "ab" * 32 in out
    assert (fx["repo"] / "data" / "integration_attempts" / "2026-10-14" / "20261014-n9-rf-a1" / "manifest.json").exists()
    code, out, _ = _run(fx, "n9-rf", roll=0, now="2026-10-14T01:50:00")
    assert code == 4 and "attempt root exists" in out, out


@pytest.mark.parametrize(
    "kwargs, verdict, needle",
    [
        ({"lease": "held"}, "WAIT", "lease is held"),
        ({"running": "WeatherIntegrationSuite_x"}, "WAIT", "WeatherIntegrationSuite_x"),
        ({"roll": 1}, "STOP", "roll_verdict.ps1 failed"),
        # Default 52-minute suite: 02:44 -> suite 02:48, ends 03:40 exactly; one minute later it would be stopped.
        ({"now": "2026-10-14T02:44:00"}, "READY", "suite=2026-10-14T02:48:00 merge=2026-10-14T03:18:00"),
        ({"now": "2026-10-14T02:45:00"}, "STOP_FOR_NIGHT", "suite would end 03:41 (52 min), past 03:40"),
        # A short suite reaches the merge-trigger reserve first.
        ({"now": "2026-10-14T03:06:00", "extra": ("-SuiteMinutes", "20")}, "READY", "merge=2026-10-14T03:40:00"),
        ({"now": "2026-10-14T03:07:00", "extra": ("-SuiteMinutes", "20")}, "STOP_FOR_NIGHT", "03:40 reserve"),
    ],
)
def test_gates_for_the_first_unit(fx, kwargs, verdict, needle):
    code, out, _ = _run(fx, "n9-rs", **kwargs)
    assert f"VERDICT={verdict} " in out and needle in out, out
    assert code == {"READY": 0, "WAIT": 3}.get(verdict, 4)


def test_roll_free_plan_with_a_sensitive_binding_verdict_stops(fx):
    _land(fx, fx["rs"])
    code, out, _ = _run(fx, "n9-rf", roll=3)
    assert code == 4 and "binding verdict is ROLL-SENSITIVE" in out, out


def test_moved_head_stops(fx):
    _git(fx["repo"], "checkout", "-q", fx["rs_head"])
    _commit(fx["repo"], "late.txt")
    _git(fx["repo"], "push", "-q", "origin", fx["rs_head"])
    _git(fx["repo"], "checkout", "-q", "master")
    code, out, _ = _run(fx, "n9-rs")
    assert code == 4 and "the head moved" in out, out


def test_fallback_refused_once_master_moved_past_its_base_and_landed_unit_is_done(fx):
    _land(fx, fx["rs"])
    code, out, _ = _run(fx, "n9-rf-alone", roll=0)
    assert code == 4 and "which the tip was not tested with" in out, out
    code, out, _ = _run(fx, "n9-rs")
    assert code == 0 and "VERDICT=DONE" in out, out


def test_local_master_behind_origin_stops(fx):
    _git(fx["repo"], "push", "-q", "origin", f"{fx['rs']}:refs/heads/master")
    code, out, _ = _run(fx, "n9-rs")
    assert code == 4 and "!= origin/master" in out, out


def test_stacked_unit_stops_when_master_carries_an_untested_commit(fx):
    _land(fx, fx["rs"])
    _commit(fx["repo"], "docs-light.txt")  # e.g. a docs light-path landing after the base
    _git(fx["repo"], "push", "-q", "origin", "master")
    code, out, _ = _run(fx, "n9-rf", roll=0)
    assert code == 4 and "which the tip was not tested with" in out, out


def _make_rf_direct(fx: dict) -> None:
    plan = dict(fx["plan"], slots=[dict(slot) for slot in fx["plan"]["slots"]])
    plan["slots"][1]["landing_path"] = "direct_rf"
    plan["plan_sha256"] = plan_content_sha256(plan)
    plan_path = fx["tmp"] / "plan-direct.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    assert ns.generate(plan_path, fx["out"])["blocking"] is False


def test_direct_rf_unit_after_0340_is_ready_and_prints_the_guarded_merge_only(fx):
    _make_rf_direct(fx)
    _land(fx, fx["rs"])
    code, out, journal = _run(fx, "n9-rf", roll=0, now="2026-10-14T03:50:00", execute=True)
    assert code == 0 and "VERDICT=READY direct path; nothing created" in out, out
    assert "path=direct_rf suite_from=2026-10-14T03:54:00 land_by=2026-10-14T04:54:00" in out
    assert "bounded_worktree_test_suite.ps1" in out and f"-ExpectedTip {fx['rf']}" in out
    assert f"quiet_window_merge.ps1 -Branch origin/claude/integration-20261014-n9-rf -ExpectedTip {fx['rf']}" in out
    assert not [line for line in journal if line.startswith(("CREATE ", "MUTATION"))]
    assert not (fx["repo"] / "data").exists() and not (fx["tmp"] / "wt").exists()


def test_direct_rf_unit_stops_for_the_night_past_the_0900_close(fx):
    _make_rf_direct(fx)
    _land(fx, fx["rs"])
    code, out, _ = _run(fx, "n9-rf", roll=0, now="2026-10-14T08:00:00")  # 08:04 + 52 + 8 = 09:04
    assert code == 4 and "VERDICT=STOP_FOR_NIGHT" in out and "09:00 heavy-work close" in out, out


def test_direct_rf_unit_still_stops_on_a_sensitive_binding_verdict(fx):
    _make_rf_direct(fx)
    _land(fx, fx["rs"])
    code, out, _ = _run(fx, "n9-rf", roll=3, now="2026-10-14T03:50:00")
    assert code == 4 and "binding verdict is ROLL-SENSITIVE" in out, out
