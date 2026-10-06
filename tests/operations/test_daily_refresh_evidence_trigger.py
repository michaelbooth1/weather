"""Stage B's overnight trigger cannot collide with another shared-lease holder.

Guards: Stage B evidence trigger never overlaps a shared-lease holder (docs/operations/HOST_LOAD_POLICY.md; docs/roadmap/agent-report-2026-10-01b-stage-b-trigger.md).

The 00:35 trigger fell inside the cold-snapshot nightly's lease, and a 05:00
trigger would have starved daily CLOB projection and raw-tape tiering, which
skip on a busy lease without retrying. The guard therefore derives lease
holders from source, not from a hand list. These tests re-derive that set
independently, check every daily lease-taking registrar against the Stage B
window, and exercise the registrar's collision check and the wrapper's bounded
lease wait.
"""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
SRC = REPO_ROOT / "src"
CONTRACT = OPS / "daily_refresh_contract.ps1"
WRAPPER = OPS / "daily_refresh.ps1"
REGISTER = OPS / "register_daily_refresh.ps1"
COLD_RUN = OPS / "cold_snapshot_nightly_run.ps1"
CLOB_RUN = OPS / "clob_tiering_run.ps1"

REFERENCE_ONLY = {
    "status.ps1",
    "integration_attempt_contract.ps1",
    "weather.operations.operating_reference",
    "weather.reporting.serving_gates.registration_parameters",
}

windows_only = pytest.mark.skipif(os.name != "nt", reason="PowerShell contract")


def _minute(hhmm):
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _contract_text():
    return CONTRACT.read_text(encoding="utf-8-sig")


def _schedule():
    contract = _contract_text()
    trigger = _minute(re.search(r'TriggerAt = "(\d\d:\d\d)"', contract).group(1))
    limit = int(re.search(r"SchedulerLimitMinutes = (\d+)", contract).group(1))
    return trigger, limit


def _overlaps(start, minutes, other_start, other_minutes):
    return any(
        start + shift < other_start + other_minutes
        and other_start < start + shift + minutes
        for shift in (-1440, 0, 1440)
    )


def _strip_comments(text, *, powershell):
    if powershell:
        text = re.sub(r"(?s)<#.*?#>", "", text)
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


# Defines Enter-WeatherHeavyWorkloadLease(Queued); its queued entry calls the direct one,
# so the library itself (and a script that only dot-sources it) is never a lease holder.
LEASE_LIBRARY = "workload_admission.ps1"


def _independent_lease_entry_points(repo_root=REPO_ROOT):
    """Re-derive the lease-taking entry points without the PowerShell code."""

    code, kind = {}, {}
    for path in (repo_root / "scripts" / "ops").glob("*.ps1"):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        code[path.name.lower()] = _strip_comments(text, powershell=True)
        kind[path.name.lower()] = "ps1"
    for path in (repo_root / "src" / "weather").rglob("*.py"):
        parts = path.relative_to(repo_root / "src").with_suffix("").parts
        node = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        text = path.read_text(encoding="utf-8", errors="replace")
        code[node] = _strip_comments(text, powershell=False)
        kind[node] = "py"

    lease_call = re.compile(
        r"(?m)^(?!\s*function\b)[^#\n]*\bEnter-WeatherHeavyWorkloadLease(?:Queued)?\b"
    )
    path_literal = re.compile(r"""(['"])[^'"\s]*?([A-Za-z0-9_.-]+\.ps1)\1""")
    module_literal = re.compile(r"""(['"])(weather(?:\.\w+)+)\1""")
    from_import = re.compile(
        r"(?m)^\s*from\s+(\.+[\w.]*|weather[\w.]*)\s+import\s+(?:\(([^)]*)\)|([^\n]+))"
    )
    plain_import = re.compile(r"(?m)^\s*import\s+(weather[\w.]*)")

    holders, edges = set(), {}
    for node, text in code.items():
        targets = set()
        if kind[node] == "ps1" and node != LEASE_LIBRARY and lease_call.search(text):
            holders.add(node)
        reference_only = node in REFERENCE_ONLY or (
            kind[node] == "ps1" and node.startswith("register_")
        )
        if not reference_only:
            targets |= {m.group(2).lower() for m in path_literal.finditer(text)}
        if kind[node] == "ps1":
            targets |= {m.group(2) for m in module_literal.finditer(text)}
        else:
            package = node.rsplit(".", 1)[0] if "." in node else node
            for match in from_import.finditer(text):
                base = match.group(1)
                if base.startswith("."):
                    dots = len(base) - len(base.lstrip("."))
                    parent = package.rsplit(".", dots - 1)[0] if dots > 1 else package
                    rest = base.lstrip(".")
                    base = f"{parent}.{rest}" if rest else parent
                targets.add(base)
                names = match.group(2) or match.group(3)
                targets |= {f"{base}.{word}" for word in re.findall(r"\w+", names)}
            targets |= {m.group(1) for m in plain_import.finditer(text)}
        edges[node] = {t for t in targets if t != node and t != LEASE_LIBRARY and t in code}

    grew = True
    while grew:
        grew = False
        for node in code:
            if node not in holders and edges[node] & holders:
                holders.add(node)
                grew = True
    return holders


def _new_timespan_minutes(text):
    hours = re.search(r"-Hours (\d+)", text)
    minutes = re.search(r"-Minutes (\d+)", text)
    return (int(hours.group(1)) if hours else 0) * 60 + (
        int(minutes.group(1)) if minutes else 0
    )


def _daily_windows(registrar_text):
    """Yield (start minute, limit minutes) for each -Daily trigger."""

    lines = registrar_text.splitlines()
    for index, line in enumerate(lines):
        trigger = re.search(r"New-ScheduledTaskTrigger -Daily -At (\S+)", line)
        if not trigger:
            continue
        token = trigger.group(1).strip("'\"),")
        if token.startswith("$"):
            default = re.search(
                r"\[string\]\$" + re.escape(token[1:]) + r' = "(\d\d:\d\d)"',
                registrar_text,
            )
            assert default, f"cannot resolve daily trigger time {token}"
            token = default.group(1)
        assert re.fullmatch(r"\d\d:\d\d", token), token
        limit = next(
            (
                _new_timespan_minutes(later)
                for later in lines[index + 1:]
                if "-ExecutionTimeLimit (New-TimeSpan" in later
            ),
            None,
        )
        assert limit, f"no execution limit follows the {token} trigger"
        yield _minute(token), limit


def test_every_daily_lease_registrar_clears_the_stage_b_window():
    """Fails when a new or moved daily lease-taking task overlaps Stage B."""

    holders = _independent_lease_entry_points()
    trigger, limit = _schedule()
    checked = {}
    for registrar in sorted(OPS.glob("register_*.ps1")):
        if registrar.name == REGISTER.name:
            continue
        text = registrar.read_text(encoding="utf-8-sig")
        if "-Daily" not in text:
            continue
        code = _strip_comments(text, powershell=True)
        named = {name for name in holders if name in code}
        if not named:
            continue
        for start, minutes in _daily_windows(text):
            checked[registrar.name] = (start, minutes)
            assert not _overlaps(start, minutes, trigger, limit), (
                f"{registrar.name} daily window at {start // 60:02d}:{start % 60:02d} "
                f"for {minutes} min overlaps Stage B"
            )

    # The review's two missed holders and the original collision are covered.
    assert checked["register_clob_tiering.ps1"] == (_minute("05:00"), 31)
    assert checked["register_clob_raw_tape_tiering.ps1"] == (_minute("06:00"), 41)
    assert checked["register_cold_snapshot_nightly.ps1"] == (_minute("00:30"), 255)
    assert "register_training_window.ps1" in checked


def test_retired_triggers_collide_with_the_holders_they_starved():
    windows = {
        "cold": (_minute("00:30"), 255),
        "clob": (_minute("05:00"), 31),
        "raw": (_minute("06:00"), 41),
    }
    old_limit = 8 * 60 + 40
    assert _overlaps(*windows["cold"], _minute("00:35"), old_limit)
    assert _overlaps(*windows["clob"], _minute("05:00"), 255)
    assert _overlaps(*windows["raw"], _minute("05:00"), 255)
    trigger, limit = _schedule()
    assert not any(_overlaps(*w, trigger, limit) for w in windows.values())
    cold_hard_stop = int(
        re.search(r"AddMinutes\((\d+)\)", COLD_RUN.read_text(encoding="utf-8-sig")).group(1)
    )
    assert cold_hard_stop <= trigger


def test_independent_scan_finds_known_holders_and_skips_references():
    holders = _independent_lease_entry_points()

    for expected in (
        "clob_tiering_run.ps1",
        "clob_raw_tape_tiering_run.ps1",
        "cold_snapshot_compression_run.ps1",
        "cold_snapshot_nightly_run.ps1",
        "training_window.ps1",
        "daily_refresh.ps1",
        "quiet_window_merge.ps1",
        "integration_attempt_suite.ps1",
        "integration_attempt_merge.ps1",
        "storage_recovery_night_run.ps1",
        "weather.operations.storage_recovery_night",
    ):
        assert expected in holders, expected
    for reference in (
        "health_watchdog.ps1",
        "status.ps1",
        "memory_commit_guard.ps1",
        "workload_admission.ps1",
        "register_clob_tiering.ps1",
        "weather.operations.operating_reference",
    ):
        assert reference not in holders, reference
    # Tiering skips rather than waits, which is why it must never share a slot.
    clob = CLOB_RUN.read_text(encoding="utf-8-sig")
    assert "SKIPPED_WORKLOAD_LEASE_BUSY" in clob


def test_evidence_lease_wait_stays_inside_scheduler_correlation():
    contract = _contract_text()
    wait = int(re.search(r"LeaseWaitSeconds = (\d+)", contract).group(1))
    retry = int(re.search(r"LeaseRetrySeconds = (\d+)", contract).group(1))
    correlation = int(
        re.search(r'"--scheduler-correlation-seconds", "(\d+)"', contract).group(1)
    )

    assert 0 < retry < wait < correlation
    assert correlation - wait >= 60


def test_wrapper_waits_for_the_lease_only_on_the_evidence_stage():
    wrapper = WRAPPER.read_text(encoding="utf-8-sig")
    evidence_branch = wrapper.split('if ($Stage -eq "evidence") {\n    # Absorb', 1)[1]
    evidence_branch = evidence_branch.split("} else {", 1)[0]

    assert "Enter-DailyRefreshLeaseWithin -Acquire $acquireLease" in evidence_branch
    assert "$evidenceSchedule.LeaseWaitSeconds" in evidence_branch
    assert "$workloadLease = & $acquireLease" in wrapper
    assert wrapper.index("Enter-DailyRefreshLeaseWithin") < wrapper.index(
        "Start-WeatherProcessInJob"
    )


def test_registration_derives_holders_and_refuses_before_registering():
    registration = REGISTER.read_text(encoding="utf-8-sig")

    check = registration.index("Get-DailyRefreshEvidenceTriggerCollisions")
    assert check < registration.index("Register-ScheduledTask")
    assert "-Tasks @(Get-ScheduledTask)" in registration
    assert "Get-WeatherSharedLeaseEntryPoints -RepoRoot $RepoRoot" in registration
    assert "-ExcludeTaskNames @($EvidenceTaskName)" in registration
    assert "overlaps an enabled shared-lease holder" in registration
    assert "OvernightLeaseHolderTaskPatterns" not in _contract_text()


def _run_contract(body, extra_env=None):
    env = os.environ.copy()
    env["WEATHER_DAILY_CONTRACT"] = str(CONTRACT)
    env.update(extra_env or {})
    script = "$ErrorActionPreference = 'Stop'\n. $env:WEATHER_DAILY_CONTRACT\n" + body
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@windows_only
@pytest.mark.spawns
def test_powershell_scan_matches_the_independent_scan():
    names = _run_contract(
        "@(Get-WeatherSharedLeaseEntryPoints -RepoRoot $env:WEATHER_REPO) | ConvertTo-Json -Compress",
        {"WEATHER_REPO": str(REPO_ROOT)},
    )

    assert set(names) == _independent_lease_entry_points()


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@windows_only
@pytest.mark.spawns
def test_new_lease_taking_task_is_detected_without_a_hand_list(tmp_path):
    ops = tmp_path / "scripts" / "ops"
    _write(ops / "new_job_run.ps1", "$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $r -Workload 'x'\n")
    _write(ops / "launcher.ps1", "$a = @('-File', (Join-Path $PSScriptRoot 'new_job_run.ps1'))\n")
    _write(ops / "mention.ps1", "# new_job_run.ps1 runs nightly\n$m = \"see new_job_run.ps1 tonight\"\n")
    _write(ops / "py_launcher.ps1", "$args = @('-m', 'weather.ops_mod')\n")
    _write(tmp_path / "src" / "weather" / "__init__.py", "")
    _write(tmp_path / "src" / "weather" / "ops_mod.py", "from weather import ops_steps\n")
    _write(tmp_path / "src" / "weather" / "ops_steps.py", "SCRIPT = 'new_job_run.ps1'\n")

    result = _run_contract(
        r"""
$names = @(Get-WeatherSharedLeaseEntryPoints -RepoRoot $env:WEATHER_REPO)
function Task($name, $arguments, $class, $start, $limit, $state = 'Ready') {
    [pscustomobject]@{
        TaskName = $name; State = $state
        Actions = @([pscustomobject]@{ Execute = 'powershell.exe'; Arguments = $arguments })
        Settings = [pscustomobject]@{ ExecutionTimeLimit = $limit }
        Triggers = @([pscustomobject]@{
            Enabled = $true; StartBoundary = $start; Repetition = $null
            CimClass = [pscustomobject]@{ CimClassName = $class }
        })
    }
}
$tasks = @(
    (Task 'Launcher' '-File C:\x\scripts\ops\launcher.ps1' 'MSFT_TaskDailyTrigger' '2026-09-01T06:30:00-04:00' 'PT30M'),
    (Task 'PyTask' '-m weather.ops_mod --go' 'MSFT_TaskTimeTrigger' '2026-10-02T07:00:00' 'PT1H'),
    (Task 'Logon' '-File "C:\x\new_job_run.ps1"' 'MSFT_TaskLogonTrigger' $null 'PT1H'),
    (Task 'Mention' '-File C:\x\scripts\ops\mention.ps1' 'MSFT_TaskDailyTrigger' '2026-09-01T07:00:00' 'PT1H'),
    (Task 'Off' '-File C:\x\launcher.ps1' 'MSFT_TaskDailyTrigger' '2026-09-01T07:00:00' 'PT1H' 'Disabled'),
    (Task 'Self' '-File C:\x\launcher.ps1' 'MSFT_TaskDailyTrigger' '2026-09-01T07:00:00' 'PT1H')
)
$holders = @(Get-DailyRefreshEvidenceLeaseHolders -Tasks $tasks -LeaseEntryPoints $names -ExcludeTaskNames @('Self'))
$collisions = @(Get-DailyRefreshEvidenceTriggerCollisions -Holders $holders -EvidenceAt '06:45' `
    -EvidenceLimitMinutes 150 -Now ([datetime]'2026-10-01T12:00:00'))
[ordered]@{
    names = $names
    holders = @($holders | ForEach-Object { [ordered]@{
        task = $_.TaskName; start = $_.StartBoundary.ToString('HH:mm')
        recurring = $_.Recurring; limit = $_.ExecutionTimeLimit } })
    collisions = @($collisions | ForEach-Object { $_.TaskName })
} | ConvertTo-Json -Compress -Depth 4
""",
        {"WEATHER_REPO": str(tmp_path)},
    )

    assert set(result["names"]) == {
        "new_job_run.ps1",
        "launcher.ps1",
        "py_launcher.ps1",
        "weather.ops_mod",
        "weather.ops_steps",
    }
    holders = {row["task"]: row for row in result["holders"]}
    assert set(holders) == {"Launcher", "PyTask", "Logon"}
    # Wall clock as registered, independent of the offset's DST conversion.
    assert holders["Launcher"]["start"] == "06:30"
    assert holders["Launcher"]["recurring"] is True
    assert holders["PyTask"]["recurring"] is False
    assert holders["Logon"]["limit"] == ""
    assert sorted(result["collisions"]) == ["Launcher", "Logon", "PyTask"]


@windows_only
@pytest.mark.spawns
def test_queued_lease_callers_count_and_the_defining_library_does_not(tmp_path):
    """Master's workload_admission.ps1 enters the lease inside its own queued function, so a
    scan that counted the library would make every script that dot-sources it a holder."""
    ops = tmp_path / "scripts" / "ops"
    _write(ops / "workload_admission.ps1",
           "function Enter-WeatherHeavyWorkloadLease { param($RepoRoot) }\n"
           "function Enter-WeatherHeavyWorkloadLeaseQueued {\n"
           "    $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot\n"
           "}\n")
    _write(ops / "queued_job.ps1",
           ". (Join-Path $PSScriptRoot 'workload_admission.ps1')\n"
           "$lease = Enter-WeatherHeavyWorkloadLeaseQueued -RepoRoot $r -Workload 'q'\n")
    _write(ops / "direct_job.ps1",
           ". (Join-Path $PSScriptRoot 'workload_admission.ps1')\n"
           "$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $r -Workload 'd'\n")
    _write(ops / "sourcer_only.ps1",
           ". (Join-Path $PSScriptRoot 'workload_admission.ps1')\n" "$x = Get-WeatherBootSessionId\n")
    _write(tmp_path / "src" / "weather" / "__init__.py", "")

    names = _run_contract(
        "@(Get-WeatherSharedLeaseEntryPoints -RepoRoot $env:WEATHER_REPO) | ConvertTo-Json -Compress",
        {"WEATHER_REPO": str(tmp_path)},
    )
    expected = {"queued_job.ps1", "direct_job.ps1"}
    assert set(names) == expected
    assert _independent_lease_entry_points(tmp_path) == expected


@windows_only
@pytest.mark.spawns
def test_collision_check_classifies_lease_holder_windows():
    rows = _run_contract(r"""
$now = [datetime]'2026-10-01T12:00:00'
function Holder($name, $start, $recurring, $limit) {
    [pscustomobject]@{
        TaskName = $name; StartBoundary = [datetime]$start
        Recurring = $recurring; ExecutionTimeLimit = $limit
    }
}
$cases = [ordered]@{
    nightly_at_0645 = @{ at = '06:45'; holders = @(Holder 'Cold' '2026-09-30T00:30:00' $true 'PT4H15M') }
    nightly_at_0035 = @{ at = '00:35'; holders = @(Holder 'Cold' '2026-09-30T00:30:00' $true 'PT4H15M') }
    clob_at_0500 = @{ at = '05:00'; holders = @(Holder 'Clob' '2026-09-30T05:00:00' $true 'PT31M') }
    raw_at_0500 = @{ at = '05:00'; holders = @(Holder 'Raw' '2026-09-30T06:00:00' $true 'PT41M') }
    tiering_at_0645 = @{ at = '06:45'; holders = @(
        (Holder 'Clob' '2026-09-30T05:00:00' $true 'PT31M'),
        (Holder 'Raw' '2026-09-30T06:00:00' $true 'PT41M')) }
    past_suite_once = @{ at = '06:45'; holders = @(Holder 'Suite' '2026-09-30T00:30:00' $false 'PT8H') }
    future_suite_once = @{ at = '06:45'; holders = @(Holder 'Suite' '2026-10-02T00:30:00' $false 'PT8H') }
    unbounded = @{ at = '06:45'; holders = @(Holder 'Loose' '2026-09-30T02:00:00' $true '') }
    zero_limit = @{ at = '06:45'; holders = @(Holder 'Loose' '2026-09-30T02:00:00' $true 'PT0S') }
    wraps_midnight = @{ at = '06:45'; holders = @(Holder 'Late' '2026-09-30T23:00:00' $true 'PT8H') }
    ends_at_trigger = @{ at = '06:45'; holders = @(Holder 'Edge' '2026-09-30T06:00:00' $true 'PT45M') }
    stage_a = @{ at = '06:45'; holders = @(Holder 'StageA' '2026-09-30T09:30:00' $true 'PT4H') }
    none = @{ at = '06:45'; holders = @() }
}
$out = [ordered]@{}
foreach ($key in $cases.Keys) {
    $found = @(Get-DailyRefreshEvidenceTriggerCollisions -Holders $cases[$key].holders `
        -EvidenceAt $cases[$key].at -EvidenceLimitMinutes 150 -Now $now)
    $out[$key] = @($found | ForEach-Object { $_.TaskName })
}
$out | ConvertTo-Json -Compress
""")

    assert rows["nightly_at_0645"] == []
    assert rows["nightly_at_0035"] == ["Cold"]
    assert rows["clob_at_0500"] == ["Clob"]
    assert rows["raw_at_0500"] == ["Raw"]
    assert rows["tiering_at_0645"] == []
    assert rows["past_suite_once"] == []
    assert rows["future_suite_once"] == ["Suite"]
    assert rows["unbounded"] == ["Loose"]
    assert rows["zero_limit"] == ["Loose"]
    assert rows["wraps_midnight"] == ["Late"]
    assert rows["ends_at_trigger"] == []
    assert rows["stage_a"] == []
    assert rows["none"] == []


@windows_only
@pytest.mark.spawns
def test_lease_wait_retries_then_acquires_or_refuses_within_budget():
    result = _run_contract(r"""
function Run-Case([int]$freeAfter, [int]$wait, [int]$retry) {
    $state = @{ now = [datetime]'2026-10-02T09:00:00Z'; calls = 0; slept = @() }
    $lease = Enter-DailyRefreshLeaseWithin `
        -Acquire { $state.calls += 1; if ($state.calls -gt $freeAfter) { 'LEASE' } else { $null } }.GetNewClosure() `
        -WaitSeconds $wait -RetrySeconds $retry `
        -Sleep { param($s) $state.slept += $s; $state.now = $state.now.AddSeconds($s) }.GetNewClosure() `
        -Clock { $state.now }.GetNewClosure()
    [ordered]@{
        lease = $lease; calls = $state.calls
        slept = @($state.slept); total = ($state.slept | Measure-Object -Sum).Sum
    }
}
[ordered]@{
    immediate = Run-Case 0 240 15
    after_three = Run-Case 3 240 15
    never = Run-Case 1000 240 15
    uneven = Run-Case 1000 40 15
} | ConvertTo-Json -Compress -Depth 4
""")

    assert result["immediate"]["lease"] == "LEASE"
    assert result["immediate"]["calls"] == 1
    assert result["immediate"]["slept"] == []

    assert result["after_three"]["lease"] == "LEASE"
    assert result["after_three"]["calls"] == 4
    assert result["after_three"]["slept"] == [15, 15, 15]

    assert result["never"]["lease"] is None
    assert result["never"]["total"] == 240
    assert result["never"]["calls"] == 240 // 15 + 1

    assert result["uneven"]["lease"] is None
    assert result["uneven"]["slept"] == [15, 15, 10]
