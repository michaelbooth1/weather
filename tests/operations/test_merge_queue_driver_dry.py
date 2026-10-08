"""Executes merge_queue_driver.ps1 -Dry against a fake repo with every mutation stubbed.

Guards: the M6 merge-train dry pilot (owner approval 2026-10-05, "3 dry nights, owner signs"):
dry mode takes no lease, registers/starts no task, merges, fetches and pushes nothing; an
unsigned or tampered queue is refused; gates read the lease and Scheduler LastRunTime and
LastTaskResult, never a guessed attempt name or time (2026-10-05 mis-gated 91a wait).
"""
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
SCRIPT = REPO_ROOT / "scripts" / "ops" / "merge_queue_driver.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")


def _find_keygen() -> str | None:
    candidates = [r"C:\Windows\System32\OpenSSH\ssh-keygen.exe", r"C:\Program Files\Git\usr\bin\ssh-keygen.exe"]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return shutil.which("ssh-keygen")


KEYGEN = _find_keygen()

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(
        sys.platform != "win32" or POWERSHELL is None or shutil.which("git") is None or KEYGEN is None,
        reason="Windows PowerShell 5.1, git and ssh-keygen are required",
    ),
]

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}

# Functions win over cmdlets and applications in PowerShell command lookup, so the driver,
# invoked in this session, talks to these shadows. Every mutating Scheduler cmdlet, the guarded
# merge child process and the lease entry points record a MUTATION line; git is forwarded to the
# real executable so ancestry is real, and every git argv is journalled.
WRAPPER = r"""
function global:Journal([string]$line) { Add-Content -LiteralPath $env:FAKE_JOURNAL -Value $line -Encoding UTF8 }
$global:RealGit = (Get-Command git -CommandType Application | Select-Object -First 1).Source
function global:git { Journal ("GIT " + ($args -join " ")); & $global:RealGit @args }
foreach ($name in @("Register-ScheduledTask", "Unregister-ScheduledTask", "Start-ScheduledTask",
        "Stop-ScheduledTask", "Enable-ScheduledTask", "Disable-ScheduledTask", "Set-ScheduledTask",
        "New-ScheduledTaskAction", "New-ScheduledTaskTrigger", "powershell.exe", "pwsh")) {
    $body = [scriptblock]::Create("Journal 'MUTATION $name'; `$global:LASTEXITCODE = 0")
    Set-Item -Path ("function:global:" + $name) -Value $body
}
function global:Get-ScheduledTask { [CmdletBinding()] param([string]$TaskName)
    $tasks = $env:FAKE_TASKS | ConvertFrom-Json
    $row = $tasks.PSObject.Properties[$TaskName]
    if ($null -eq $row) { throw "task not found: $TaskName" }
    [pscustomobject]@{ TaskName = $TaskName; State = $row.Value.State } }
function global:Get-ScheduledTaskInfo { [CmdletBinding()] param([string]$TaskName)
    $row = ($env:FAKE_TASKS | ConvertFrom-Json).PSObject.Properties[$TaskName].Value
    [pscustomobject]@{ LastRunTime = [datetime]$row.LastRunTime; LastTaskResult = [int64]$row.LastTaskResult } }
& $env:FAKE_SCRIPT @args
exit $LASTEXITCODE
"""

# The fake repository's workload_admission.ps1: the lease state is read from the environment and
# any acquisition is a recorded mutation.
FAKE_ADMISSION = r"""
function Get-WeatherHeavyWorkloadLeaseState { param([string]$RepoRoot)
    if ($env:FAKE_LEASE -eq "held") {
        return [pscustomobject]@{ Active = $true; Path = "x"; Owner = [pscustomobject]@{ workload = "integration_suite"; pid = 4242 } } }
    return [pscustomobject]@{ Active = $false; Path = "x"; Owner = $null } }
function Enter-WeatherHeavyWorkloadLease { Journal "MUTATION Enter-WeatherHeavyWorkloadLease" }
function Enter-WeatherHeavyWorkloadLeaseQueued { Journal "MUTATION Enter-WeatherHeavyWorkloadLeaseQueued" }
"""
FAKE_MERGE = 'Journal "MUTATION quiet_window_merge"\nexit 0\n'

READ_ONLY_GIT = {"rev-parse", "merge-base"}
NIGHT = "2026-10-07"
GATE_OK = {"GateA": {"State": "Ready", "LastRunTime": "2026-10-07T00:31:00", "LastTaskResult": 0}}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            env=dict(os.environ, **GIT_ENV))
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}"
    return result.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _keygen(*args: str, stdin: bytes | None = None) -> None:
    result = subprocess.run([KEYGEN, *args], input=stdin, capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


@pytest.fixture()
def fx(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    ops = repo / "scripts" / "ops"
    ops.mkdir(parents=True)
    (ops / "workload_admission.ps1").write_text(FAKE_ADMISSION, encoding="utf-8")
    (ops / "quiet_window_merge.ps1").write_text(FAKE_MERGE, encoding="utf-8")
    base = _commit(repo, "base.txt")
    tips = []
    for name in ("one", "two"):
        _git(repo, "checkout", "-q", "-b", f"codex/{name}", base)
        tips.append(_commit(repo, f"{name}.txt"))
    _git(repo, "checkout", "-q", "master")
    for name, tip in zip(("one", "two"), tips):
        _git(repo, "update-ref", f"refs/remotes/origin/codex/{name}", tip)
    _git(repo, "update-ref", "refs/remotes/origin/master", base)

    keys = tmp_path / "keys"
    keys.mkdir()
    for who in ("owner", "agent"):
        _keygen("-q", "-t", "ed25519", "-N", "", "-C", who, "-f", str(keys / who))
    pub = (keys / "owner.pub").read_text(encoding="utf-8").split()
    allowed = keys / "allowed_signers"
    allowed.write_text(f'owner namespaces="weather-merge-queue" {pub[0]} {pub[1]}\n', encoding="utf-8")

    queue_dir = tmp_path / "queue"
    (queue_dir / "receipts").mkdir(parents=True)
    entries = []
    for order, (name, tip) in enumerate(zip(("one", "two"), tips), start=1):
        receipt = queue_dir / "receipts" / f"{name}.json"
        receipt.write_text(json.dumps({"head_sha": tip, "verdict": "PASS"}), encoding="utf-8")
        entries.append({
            "order": order, "branch": f"origin/codex/{name}", "expected_tip": tip,
            "roll_class": "ROLL-SENSITIVE" if order == 1 else "ROLL-FREE", "approved": True,
            "approval_ref": f"owner instruction for {name}", "preflight_receipt": f"receipts/{name}.json",
            "preflight_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        })
    queue = {"schema_version": "weather_exact_tip_merge_queue_v1", "night": NIGHT, "base_sha": base,
             "plan_sha256": "a" * 64, "on_failure": "stop_night", "entries": entries}
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(WRAPPER, encoding="utf-8")
    return {"tmp": tmp_path, "repo": repo, "base": base, "tips": tips, "keys": keys, "allowed": allowed,
            "queue_dir": queue_dir, "queue": queue, "wrapper": wrapper, "journal": tmp_path / "journal.txt"}


def _write_queue(fx: dict, payload: dict | None = None, signer: str | None = "owner") -> Path:
    path = fx["queue_dir"] / "queue.json"
    path.write_bytes(json.dumps(payload or fx["queue"], indent=2).encode("utf-8"))
    sig = Path(str(path) + ".sig")
    if sig.exists():
        sig.unlink()
    if signer:
        _keygen("-Y", "sign", "-f", str(fx["keys"] / signer), "-n", "weather-merge-queue", str(path))
    return path


def _run(fx: dict, queue: Path, *extra: str, dry: bool = True, lease: str = "free",
         tasks: dict | None = None, evaluated_at: str = "2026-10-07T01:10:00") -> tuple[int, dict | None, list[str]]:
    receipt = fx["tmp"] / "receipt.json"
    if receipt.exists():
        receipt.unlink()
    args = [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(fx["wrapper"]),
            "-RepoRoot", str(fx["repo"]), "-QueueFile", str(queue), "-LogFile", str(fx["tmp"] / "driver.log"),
            "-AllowedSignersFile", str(fx["allowed"]), "-SshKeygenPath", KEYGEN, *extra]
    if dry:
        args += ["-Dry", "-ReceiptOut", str(receipt), "-EvaluatedAt", evaluated_at, "-GateTaskName", "GateA"]
    env = dict(os.environ, **GIT_ENV, FAKE_JOURNAL=str(fx["journal"]), FAKE_SCRIPT=str(SCRIPT),
               FAKE_LEASE=lease, FAKE_TASKS=json.dumps(GATE_OK if tasks is None else tasks))
    result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=120)
    journal = fx["journal"].read_text(encoding="utf-8-sig").splitlines() if fx["journal"].exists() else []
    payload = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else None
    if fx["journal"].exists():
        fx["journal"].unlink()
    assert payload is not None or not dry, result.stdout + result.stderr
    return result.returncode, payload, journal


def _assert_read_only(journal: list[str]) -> None:
    assert [line for line in journal if line.startswith("MUTATION")] == []
    verbs = {line.split()[3] for line in journal if line.startswith("GIT ")}
    assert verbs <= READ_ONLY_GIT, verbs


def test_signed_queue_with_open_gates_would_run_first_entry_without_any_mutation(fx):
    code, receipt, journal = _run(fx, _write_queue(fx))

    assert code == 0
    assert receipt["schema_version"] == "weather_merge_train_dry_receipt_v1"
    assert receipt["verdict"] == "WOULD_RUN"
    assert receipt["signature"]["verified"] is True
    assert receipt["signature"]["key_fingerprint"].startswith("SHA256:")
    run = receipt["would_run"]
    assert run["expected_tip"] == fx["tips"][0] and run["order"] == 1
    assert run["suite_at_local"] == "2026-10-07T01:10:00"
    assert run["merge_at_local"] == "2026-10-07T01:40:00"
    assert [e["status"] for e in receipt["entries"]] == ["next", "pending"]
    assert receipt["gate_tasks"][0]["decision"] == "succeeded_tonight"
    assert receipt["master_sha"] == fx["base"]
    _assert_read_only(journal)
    assert any(line.startswith("GIT ") for line in journal)  # the git shadow really intercepts


@pytest.mark.parametrize("signer", [None, "agent"])
def test_unsigned_or_wrongly_signed_queue_is_refused_before_any_git_read(fx, signer):
    code, receipt, journal = _run(fx, _write_queue(fx, signer=signer))

    assert code == 4
    assert receipt["verdict"] == "REFUSED_UNSIGNED"
    assert receipt["signature"]["verified"] is False
    assert receipt["would_run"] is None
    assert [line for line in journal if line.startswith("MUTATION")] == []
    assert not any(line.startswith("GIT merge-base") for line in journal)


def test_queue_edited_after_owner_signature_is_refused(fx):
    queue = _write_queue(fx)
    tampered = dict(fx["queue"], plan_sha256="b" * 64)
    queue.write_bytes(json.dumps(tampered, indent=2).encode("utf-8"))

    code, receipt, _ = _run(fx, queue)

    assert code == 4 and receipt["verdict"] == "REFUSED_UNSIGNED"


def test_allowed_signers_without_a_key_refuses_every_queue(fx):
    fx["allowed"].write_text("# no key yet\n", encoding="utf-8")

    code, receipt, _ = _run(fx, _write_queue(fx))

    assert code == 4 and receipt["verdict"] == "REFUSED_UNSIGNED"


def test_held_lease_waits_and_names_the_holder(fx):
    code, receipt, journal = _run(fx, _write_queue(fx), lease="held")

    assert code == 0
    assert receipt["verdict"] == "WAIT"
    assert receipt["blocked_by"] == ["lease_held:integration_suite"]
    assert receipt["lease"]["pid"] == 4242
    _assert_read_only(journal)


@pytest.mark.parametrize(
    ("task", "verdict", "blocked"),
    [
        ({"State": "Ready", "LastRunTime": "2026-10-06T00:31:00", "LastTaskResult": 0}, "WAIT",
         "gate_task_not_run_tonight:GateA"),
        ({"State": "Running", "LastRunTime": "2026-10-07T00:31:00", "LastTaskResult": 0x41301}, "WAIT",
         "gate_task_running:GateA"),
        ({"State": "Ready", "LastRunTime": "2026-10-07T00:31:00", "LastTaskResult": 1}, "STOP_FOR_NIGHT",
         "gate_task_failed:GateA"),
    ],
)
def test_gate_task_state_comes_from_scheduler_last_run_and_result(fx, task, verdict, blocked):
    code, receipt, journal = _run(fx, _write_queue(fx), tasks={"GateA": task})

    assert code == 0
    assert receipt["verdict"] == verdict
    assert blocked in receipt["blocked_by"]
    assert receipt["would_run"] is None
    _assert_read_only(journal)


def test_missing_gate_task_stops_the_night(fx):
    code, receipt, _ = _run(fx, _write_queue(fx), tasks={})

    assert code == 0 and receipt["verdict"] == "STOP_FOR_NIGHT"
    assert "gate_task_missing:GateA" in receipt["blocked_by"]


def test_merge_window_boundary(fx):
    queue = _write_queue(fx)
    _, inside, _ = _run(fx, queue, evaluated_at="2026-10-07T03:10:00")
    _, outside, _ = _run(fx, queue, evaluated_at="2026-10-07T03:11:00")
    _, early, _ = _run(fx, queue, evaluated_at="2026-10-07T00:10:00")

    assert inside["verdict"] == "WOULD_RUN" and inside["would_run"]["merge_at_local"] == "2026-10-07T03:40:00"
    assert outside["verdict"] == "STOP_FOR_NIGHT" and "merge_window_exhausted" in outside["blocked_by"]
    assert early["would_run"]["suite_at_local"] == "2026-10-07T00:30:00"
    assert early["would_run"]["merge_at_local"] == "2026-10-07T01:00:00"


def test_wrong_night_is_refused(fx):
    code, receipt, _ = _run(fx, _write_queue(fx), evaluated_at="2026-10-07T13:00:00")

    assert code == 4 and receipt["verdict"] == "REFUSED"
    assert any("night 2026-10-07" in item and "2026-10-08" in item for item in receipt["refusals"])


def test_moved_tip_moved_master_and_bad_receipt_are_refused(fx):
    queue = _write_queue(fx)
    _git(fx["repo"], "update-ref", "refs/remotes/origin/codex/two", fx["base"])
    code, receipt, _ = _run(fx, queue)
    assert code == 4 and any("exact-tip preflight failed for origin/codex/two" in r for r in receipt["refusals"])
    _git(fx["repo"], "update-ref", "refs/remotes/origin/codex/two", fx["tips"][1])

    (fx["queue_dir"] / "receipts" / "one.json").write_text("{}", encoding="utf-8")
    code, receipt, _ = _run(fx, queue)
    assert code == 4 and "preflight receipt hash mismatch for origin/codex/one" in receipt["refusals"]

    payload = json.loads(json.dumps(fx["queue"]))
    (fx["queue_dir"] / "receipts" / "one.json").write_text(json.dumps({"head_sha": fx["tips"][0]}), encoding="utf-8")
    payload["entries"][0]["preflight_receipt_sha256"] = hashlib.sha256(
        (fx["queue_dir"] / "receipts" / "one.json").read_bytes()).hexdigest()
    queue = _write_queue(fx, payload)
    _commit(fx["repo"], "foreign.txt")
    code, receipt, _ = _run(fx, queue)
    assert code == 4
    assert "master moved since signing and no queue entry explains it" in receipt["refusals"]


def test_merged_entries_advance_the_train_and_finish_done(fx):
    queue = _write_queue(fx)
    _git(fx["repo"], "merge", "-q", "--no-edit", "--no-ff", fx["tips"][0])
    _, receipt, journal = _run(fx, queue)
    assert receipt["verdict"] == "WOULD_RUN"
    assert [e["status"] for e in receipt["entries"]] == ["merged", "next"]
    assert receipt["would_run"]["order"] == 2
    _assert_read_only(journal)

    _git(fx["repo"], "merge", "-q", "--no-edit", "--no-ff", fx["tips"][1])
    code, receipt, _ = _run(fx, queue)
    assert code == 0 and receipt["verdict"] == "DONE"


def test_live_mode_controls_prove_the_stubs_catch_real_calls(fx):
    queue = _write_queue(fx, signer=None)
    code, _, journal = _run(fx, queue, dry=False)
    assert code != 0
    assert [line for line in journal if line.startswith("MUTATION")] == []

    # Positive control: a signed live run reaches the guarded merge child, which the shadow records.
    queue = _write_queue(fx)
    code, _, journal = _run(fx, queue, dry=False)
    assert code == 0
    assert journal.count("MUTATION powershell.exe") == 2

    code, _, _ = _run(fx, queue, "-EvaluatedAt", "2026-10-07T01:10:00", dry=False)
    assert code != 0


# --- "test the train once" (M6 follow-up): one suite on the final tip, then merge in order ---

def _train_queue(fx: dict, verdicts=("PASS", "PASS"), roll=("ROLL-FREE", "ROLL-FREE")) -> Path:
    payload = json.loads(json.dumps(fx["queue"]))
    for entry, verdict, roll_class, name in zip(payload["entries"], verdicts, roll, ("one", "two")):
        receipt = fx["queue_dir"] / "receipts" / f"{name}.json"
        # The landing preflight writes an object verdict; the pilot's older fixtures a string.
        receipt.write_text(json.dumps({"head_sha": entry["expected_tip"], "verdict": {"status": verdict}}),
                           encoding="utf-8")
        entry["preflight_receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        entry["roll_class"] = roll_class
    return _write_queue(fx, payload)


def test_train_once_plans_one_suite_on_the_final_tip_then_merges_in_order(fx):
    code, receipt, journal = _run(fx, _train_queue(fx), "-TrainOnce")

    assert code == 0 and receipt["verdict"] == "WOULD_RUN"
    train = receipt["train"]
    assert train["eligible"] is True and train["ineligible_reason"] is None
    assert train["pending_orders"] == [1, 2]
    assert train["suites_planned"] == 1 and train["suites_saved"] == 1
    assert train["final_tip"] == fx["tips"][1]
    assert train["intermediate_failed_where_final_passed"] is False
    run = receipt["would_run"]
    assert run["train_once"] is True and run["merge_orders"] == [1, 2]
    assert run["suite_tip"]["final_tip"] == fx["tips"][1] and run["suite_tip"]["base"] == fx["base"]
    assert run["summary"].startswith("would have run ONE bounded suite on the final tip of 2 heads")
    _assert_read_only(journal)


def test_train_once_reports_an_intermediate_tip_that_failed_where_the_final_passed(fx):
    code, receipt, _ = _run(fx, _train_queue(fx, verdicts=("FAIL", "PASS")), "-TrainOnce")

    assert code == 0
    train = receipt["train"]
    assert train["intermediate_failures"] == [1]
    assert train["intermediate_failed_where_final_passed"] is True
    assert [v["verdict"] for v in train["receipt_verdicts"]] == ["FAIL", "PASS"]


@pytest.mark.parametrize(("verdicts", "roll", "reason"), [
    (("PASS", "PASS"), ("ROLL-SENSITIVE", "ROLL-FREE"), "ROLL-SENSITIVE entries: 1"),
    (("PASS", "FAIL"), ("ROLL-FREE", "ROLL-FREE"), "the final tip's chained preflight is FAIL"),
])
def test_train_once_falls_back_to_per_head_when_ineligible(fx, verdicts, roll, reason):
    code, receipt, journal = _run(fx, _train_queue(fx, verdicts=verdicts, roll=roll), "-TrainOnce")

    assert code == 0 and receipt["verdict"] == "WOULD_RUN"
    assert receipt["train"]["eligible"] is False
    assert receipt["train"]["ineligible_reason"] == reason
    assert "train_once" not in receipt["would_run"] and receipt["would_run"]["order"] == 1
    _assert_read_only(journal)


def test_train_once_counts_only_unmerged_heads(fx):
    queue = _train_queue(fx, verdicts=("FAIL", "PASS"))
    _git(fx["repo"], "merge", "-q", "--no-edit", "--no-ff", fx["tips"][0])
    _, receipt, _ = _run(fx, queue, "-TrainOnce")

    train = receipt["train"]
    assert train["pending_orders"] == [2] and train["suites_saved"] == 0
    assert train["intermediate_failures"] == [] and train["intermediate_failed_where_final_passed"] is False


def test_train_once_is_a_dry_only_parameter(fx):
    code, _, journal = _run(fx, _train_queue(fx), "-TrainOnce", dry=False)
    assert code != 0
    assert [line for line in journal if line.startswith("MUTATION")] == []
