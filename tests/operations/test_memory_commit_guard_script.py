import json
import os
from pathlib import Path
import re
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "memory_commit_guard.ps1"
REGISTER = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ops"
    / "register_memory_commit_guard.ps1"
)


def test_memory_guard_warns_below_1_5_gib_with_top_working_sets():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "[long]$WarnFreePhysicalBytes = 1536MB" in text
    physical_start = text.index("if ($freeRamMB -lt $warnFreePhysicalMB)")
    commit_warning_start = text.index("if ($commitPercent -ge $WarnPercent)")
    physical_block = text[physical_start:commit_warning_start]
    assert "Sort-Object WorkingSet64 -Descending" in physical_block
    assert "top working set" in physical_block
    assert "$status.physical_warning = $true" in physical_block
    assert "Stop-Process" not in physical_block


def test_memory_guard_warning_cannot_disable_the_critical_action_path():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    warning_start = text.index("if ($commitPercent -ge $WarnPercent)")
    act_start = text.index("if ($commitPercent -ge $ActPercent -and -not $terminationPerformed)")
    warning_block = text[warning_start:act_start]
    act_block = text[act_start:text.index("# ---- Orphan sweep")]
    assert '$status.memory_warning = $true' in warning_block
    assert '$status.action = "warned"' not in warning_block
    assert '$status.action -eq "none"' not in text
    assert "Test-GovernedWeatherProcess" in act_block
    assert "pytest|compileall|coverage|tox|nox" in act_block
    assert "Stop-VerifiedProcessTree $target.RootRow" in act_block


def test_memory_guard_attributes_and_reaps_codex_heavy_tool_trees():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    start = text.index("$agentRootNames =")
    end = text.index("# A scheduled PowerShell wrapper")
    block = text[start:end]
    assert '"codex.exe", "chatgpt.exe", "claude.exe"' in block
    assert "function Get-AgentToolRoot" in block
    assert "function Stop-VerifiedProcessTree" in block
    assert "ProcessId = {0}" in block
    assert "CreationDate -ne" in block
    assert "$minuteOfDay -ge 30.0" in block
    assert "$minuteOfDay -lt 540.0" in block
    assert "$MaxConcurrentAgentHeavyWorkloads" in block
    assert "Codex heavy workload is outside the 00:30-09:00 host window" in block
    assert "Test-GovernedWeatherProcess" in block
    assert "Get-ChildItem" in block
    assert "-Recurse" in block
    assert "daily_refresh|score_all" in block
    assert "Get-ProcessTreePrivateBytes" in block
    assert "$agentTreeBytes" in block
    assert "$MinKillPrivateBytes" in block
    assert "Stop-VerifiedProcessTree $target $allProcesses $reason $true" in block


def test_memory_guard_preserves_event_history_without_raw_commands():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    start = text.index("# Preserve incident-bearing samples")
    block = text[start:]
    assert "memory_commit_guard_history.jsonl" in text
    assert "agent_heavy_workload_count" in block
    assert "actions = @($guardActions)" in block
    assert "CommandLine" not in block
    assert "Move-Item -LiteralPath $statusTempPath" in block


def test_memory_guard_is_registered_every_minute():
    text = REGISTER.read_text(encoding="utf-8-sig")

    assert "[int]$IntervalMinutes = 1" in text
    assert "-RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)" in text
    assert "-MultipleInstances IgnoreNew" in text


def test_memory_guard_reaps_only_unowned_evidence_refresh_inside_protected_window():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    start = text.index('$evidenceTaskName = "WeatherEveningEvidenceRefresh"')
    end = text.index("if ($freeRamMB -lt $warnFreePhysicalMB)")
    block = text[start:end]
    assert "$localNow.Hour -ge 12 -and $localNow.Hour -lt 18" in block
    assert '[string]$evidenceTask.State -ne "Running"' in block
    assert "weather\\.operations\\.daily_refresh" in block
    assert "--scheduler-task-name" in block
    assert "$ageMinutes -lt 2" in block
    assert "Sort-Object PrivateBytes -Descending" in block
    assert "Stop-Process -Id $target.Id" in block


def test_memory_guard_and_registrar_are_exact_capture_host_bound_before_side_effects():
    guard = SCRIPT.read_text(encoding="utf-8-sig")
    register = REGISTER.read_text(encoding="utf-8-sig")

    guard_gate = guard.index("$guardExecutionHostId = Get-MemoryGuardExecutionHostId")
    assert "ExpectedExecutionHostId" in guard[:guard_gate]
    assert '"international_live_execution_host_v2`0$machineGuid"' in guard
    assert "restricted to its registered" in guard[guard_gate:]
    assert 'if ($guardExecutionHostId -cne $ExpectedExecutionHostId)' in guard
    assert "exit 0" in guard[guard_gate:guard.index('$logDir = Join-Path')]
    assert "Existing production registrations predate" in guard[:guard_gate]
    assert "Get-WeatherExecutionHostAssignment" not in guard
    assert guard_gate < guard.index('$logDir = Join-Path $RepoRoot "data\\logs"')
    assert guard_gate < guard.index("Get-CimInstance Win32_OperatingSystem")
    assert guard_gate < guard.index("Stop-Process")

    registrar_gate = register.index(
        "$registrarExecutionHostId = Get-WeatherExecutionHostId"
    )
    assert "Get-WeatherExecutionHostAssignment" in register[registrar_gate:]
    assert "dedicated_capture_execution_host_id" in register[registrar_gate:]
    assert "only on the tracked dedicated capture host" in register[registrar_gate:]
    assert "-ExpectedExecutionHostId $registrarExecutionHostId" in register
    assert registrar_gate < register.index("New-ScheduledTaskAction")
    assert registrar_gate < register.index("Register-ScheduledTask")


# Constant or read-only PowerShell automatic variables. Names are case-insensitive, so
# `$pid = ...` targets $PID. The assignment raises a statement-terminating error that the
# default Continue preference swallows, and the script carries on with the OLD value. That
# made every memory-guard tree kill inert from 2026-08-23 to 2026-09-19: the parse ratchet
# cannot see it, because the statement parses cleanly.
_READ_ONLY_AUTOMATIC_VARIABLES = (
    "pid",
    "host",
    "home",
    "pshome",
    "shellid",
    "error",
    "executioncontext",
    "psversiontable",
    "psculture",
    "psuiculture",
    "psedition",
    "true",
    "false",
)
_READ_ONLY_ASSIGNMENT = re.compile(
    r"(?im)(?:^|[\s;({])\$(?:" + "|".join(_READ_ONLY_AUTOMATIC_VARIABLES) + r")\s*=(?!=)"
)


def test_no_ops_script_assigns_to_a_read_only_automatic_variable():
    offenders = []
    for script in sorted(SCRIPT.parent.rglob("*.ps1")):
        lines = script.read_text(encoding="utf-8-sig").splitlines()
        for number, line in enumerate(lines, start=1):
            code = line.split("#", 1)[0]
            if _READ_ONLY_ASSIGNMENT.search(code):
                offenders.append(f"{script.name}:{number}: {line.strip()}")

    assert offenders == []


@pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell")
def test_stop_verified_process_tree_terminates_members_children_first(tmp_path):
    # Executes the real function against synthetic rows. Every other test in this module
    # is a substring assertion, which is how a kill path that never killed shipped.
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_GUARD_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'memory guard script did not parse' }
foreach ($name in @(
    'Test-GovernedWeatherProcess',
    'Get-ProcessTreeRows',
    'Stop-VerifiedProcessTree'
)) {
    $functionAst = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)) | Select-Object -First 1
    if ($null -eq $functionAst) { throw "missing function $name" }
    Invoke-Expression $functionAst.Extent.Text
}
# The production script runs under the default preference; keep the test honest.
$ErrorActionPreference = 'Continue'
$script:stopped = New-Object System.Collections.Generic.List[int]
$script:logged = New-Object System.Collections.Generic.List[string]
$born = [datetime]'2026-09-19T01:00:00'
$rows = @(
    [pscustomobject]@{ ProcessId = 4100; ParentProcessId = 9; Name = 'powershell.exe'; CommandLine = 'powershell -m pytest'; CreationDate = $born },
    [pscustomobject]@{ ProcessId = 4200; ParentProcessId = 4100; Name = 'python.exe'; CommandLine = 'python -m pytest'; CreationDate = $born.AddSeconds(1) },
    [pscustomobject]@{ ProcessId = 4300; ParentProcessId = 4200; Name = 'python.exe'; CommandLine = 'python -c pass'; CreationDate = $born.AddSeconds(2) }
)
function Write-GuardLog([string]$Level, [string]$Message) { $script:logged.Add("$Level $Message") }
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    $wanted = [int]($Filter -replace '\D', '')
    return $rows | Where-Object { [int]$_.ProcessId -eq $wanted } | Select-Object -First 1
}
function Stop-Process {
    param($Id, [switch]$Force, $Confirm, $ErrorAction)
    $script:stopped.Add([int]$Id)
}
$ok = Stop-VerifiedProcessTree $rows[0] $rows 'synthetic' $true
[pscustomobject]@{
    ok = [bool]$ok
    stopped = @($script:stopped)
    guard_pid = [int]$PID
    errors = @($script:logged | Where-Object { $_ -like 'ERROR*' -or $_ -like 'CRITICAL*' })
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "WEATHER_GUARD_SCRIPT": str(SCRIPT)},
    )

    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["errors"] == []
    assert outcome["ok"] is True
    assert outcome["stopped"] == [4300, 4200, 4100]
    assert outcome["guard_pid"] not in outcome["stopped"]
