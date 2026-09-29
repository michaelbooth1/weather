"""Execute only fixture alarm logic and mocked Scheduler commands."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell qualification")


def run_ps(source, **environment):
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", source],
        env={**os.environ, "FIXTURE_OPS": str(OPS), **environment},
        capture_output=True, text=True, timeout=40,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_status_settlement_flag_reaches_watchdog_critical_and_tiering_formats():
    rows = run_ps(r"""
$ErrorActionPreference = 'Stop'
$statusText = [IO.File]::ReadAllText((Join-Path $env:FIXTURE_OPS 'status.ps1'))
$watchdogText = [IO.File]::ReadAllText((Join-Path $env:FIXTURE_OPS 'health_watchdog.ps1'))
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($statusText, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'status parse failed' }
$format = @($ast.FindAll({param($n)
    $n -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
    $n.Value -like 'SETTLEMENT HOLE:*'
}, $true))[0].Value
$tiering = @($ast.FindAll({param($n)
    $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $n.Left.Extent.Text -eq '$tieringMessage'
}, $true))[0]
$tieringSkippedToday = @('fixture_projection')
Invoke-Expression $tiering.Extent.Text
$ast = [System.Management.Automation.Language.Parser]::ParseInput($watchdogText, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'watchdog parse failed' }
foreach ($name in @('Get-FlagClass', 'Get-FlagAction')) {
    $fn = @($ast.FindAll({param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name
    }, $true))[0]
    Invoke-Expression $fn.Extent.Text
}
$classify = ($watchdogText -split '\$entries = @\(\)', 2)[1] -split '\$rank =', 2 | Select-Object -First 1
$inCapture = $false; $inRollover = $false; $inChain = $false
$rows = foreach ($count in @(1, 2, 12)) {
    $entries = @()
    $status = @{flags=@(($format -f $count, 7, 'fixture-dates', 'fixture-age', 2, 12))}
    Invoke-Expression $classify
    @{count=$count; severity=$entries[0].severity; flag=$entries[0].flag}
}
@{rows=@($rows); tiering=$tieringMessage} | ConvertTo-Json -Depth 5 -Compress
""")
    assert [row["severity"] for row in rows["rows"]] == ["HIGH", "CRITICAL", "CRITICAL"]
    assert "fixture_projection" in rows["tiering"]
    assert "{0}" not in rows["tiering"]


@pytest.mark.parametrize("binding", ["valid", "missing", "wrong", "unbound_source"])
def test_watchdog_registrar_requires_reviewed_pins_before_mock_scheduler(tmp_path, binding):
    watchdog = tmp_path / "health_watchdog.ps1"
    status = tmp_path / "status.ps1"
    watchdog.write_bytes((OPS / watchdog.name).read_bytes())
    status.write_bytes((OPS / status.name).read_bytes())
    if binding == "unbound_source":
        watchdog.write_text("param()\n", encoding="utf-8")
    self_hash = hashlib.sha256(watchdog.read_bytes()).hexdigest()
    status_hash = hashlib.sha256(status.read_bytes()).hexdigest()
    if binding == "missing":
        self_hash = ""
    if binding == "wrong":
        status_hash = "0" * 64
    result = run_ps(r"""
$ErrorActionPreference = 'Stop'
$global:fixtureMutations = 0
function New-ScheduledTaskAction { param($Execute,$Argument,$WorkingDirectory)
    $global:fixtureAction = [pscustomobject]@{Execute=$Execute;Arguments=$Argument;WorkingDirectory=$WorkingDirectory}
    $global:fixtureAction
}
function New-ScheduledTaskTrigger { param([switch]$Once,$At,$RepetitionInterval) @{} }
function New-ScheduledTaskPrincipal { param($UserId,$LogonType,$RunLevel)
    $global:fixturePrincipal = [pscustomobject]@{UserId=$UserId;LogonType=$LogonType;RunLevel=$RunLevel}
    $global:fixturePrincipal
}
function New-ScheduledTaskSettingsSet {
    param([switch]$AllowStartIfOnBatteries,[switch]$DontStopIfGoingOnBatteries,
        [switch]$StartWhenAvailable,$ExecutionTimeLimit,$MultipleInstances) @{}
}
function Register-ScheduledTask { param($TaskName,$Action,$Trigger,$Principal,$Settings,[switch]$Force,$Description)
        $global:fixtureMutations++
}
function Get-ScheduledTask { param($TaskName)
    [pscustomobject]@{Actions=@($global:fixtureAction);Principal=$global:fixturePrincipal;State='Ready';
        Settings=@{ExecutionTimeLimit='PT5M'}}
}
$failure = ''
try {
    $null = & (Join-Path $env:FIXTURE_OPS 'register_health_watchdog.ps1') -RepoRoot $env:FIXTURE_ROOT -WatchdogScriptPath $env:FIXTURE_WATCHDOG -StatusScriptPath $env:FIXTURE_STATUS -ExpectedSelfSha256 $env:FIXTURE_SELF_HASH -ExpectedStatusScriptSha256 $env:FIXTURE_STATUS_HASH
} catch { $failure = $_.Exception.Message }
@{mutations=$global:fixtureMutations;error=$failure;arguments=$global:fixtureAction.Arguments} | ConvertTo-Json -Compress
""", FIXTURE_ROOT=str(tmp_path), FIXTURE_WATCHDOG=str(watchdog), FIXTURE_STATUS=str(status),
        FIXTURE_SELF_HASH=self_hash, FIXTURE_STATUS_HASH=status_hash)
    if binding == "valid":
        assert result["mutations"] == 1, result
        assert result["error"] == ""
        assert self_hash in result["arguments"] and status_hash in result["arguments"]
        assert "-RepoRoot" in result["arguments"]
    else:
        assert result["mutations"] == 0
        assert result["error"]
