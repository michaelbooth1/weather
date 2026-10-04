"""Windows parser and mocked registrar/teardown checks; never touches Scheduler."""
import base64
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell required")


def ps(source):
    encoded = base64.b64encode((source + "\nexit 0").encode("utf-16le")).decode("ascii")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def parse(path):
    return ("$ErrorActionPreference='Stop';$tokens=$null;$errors=$null;"
            f"$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors);"
            "if(@($errors).Count){throw ($errors|Out-String)};")


@pytest.mark.parametrize("name", ["replay_bundle_export_nightly.ps1", "register_replay_bundle_export_nightly.ps1"])
def test_parse(name):
    ps(parse(OPS / name))


def test_deadline_uses_toronto_and_reserves_teardown_across_dst():
    source = parse(OPS / "replay_bundle_export_nightly.ps1") + """
    $fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $n.Name -eq 'Get-ReplayExportDeadline'},$true)
    Invoke-Expression $fn.Extent.Text
    foreach($utc in @('2030-01-10T05:29:00Z','2030-01-10T09:54:00Z',
                      '2030-07-10T04:29:00Z','2030-07-10T08:54:00Z')) {
        $refused=$false
        try { Get-ReplayExportDeadline ([datetime]::Parse($utc).ToUniversalTime()) | Out-Null }
        catch { $refused=$true }
        if(-not $refused){throw "window accepted $utc"}
    }
    foreach($utc in @('2030-01-10T09:53:59Z','2030-07-10T08:53:59Z')) {
        $now=[datetime]::Parse($utc).ToUniversalTime()
        $deadline=Get-ReplayExportDeadline $now
        if(($deadline-$now).TotalSeconds -ne 46){throw 'teardown reserve wrong'}
    }
    $start=[datetime]::Parse('2030-01-10T05:30:00Z').ToUniversalTime()
    if(((Get-ReplayExportDeadline $start)-$start).TotalSeconds -ne 2730){throw 'runtime not bounded'}
    """
    ps(source)


@pytest.mark.parametrize("teardown_fails", [False, True])
def test_lease_release_follows_proved_job_teardown(teardown_fails):
    source = parse(OPS / "replay_bundle_export_nightly.ps1") + """
    $outer=$ast.EndBlock.Statements | Where-Object {$_ -is [Management.Automation.Language.TryStatementAst]}
    $script:events=[Collections.Generic.List[string]]::new()
    $job=New-Object psobject
    $job | Add-Member ScriptMethod TerminateAndWait {param($ms) $script:events.Add('terminate'); FAIL }
    $job | Add-Member ScriptMethod Dispose {$script:events.Add('close_job')}
    $child=New-Object psobject
    $child | Add-Member ScriptMethod Dispose {$script:events.Add('close_child')}
    function Exit-WeatherHeavyWorkloadLease {param($Lease) $script:events.Add('release')}
    function Set-WeatherHeavyWorkloadLeasePoisoned {param($Lease) $script:events.Add('poison')}
    $lease='fixture';$teardownProved=$false
    try { & ([scriptblock]::Create($outer.Finally.Statements.Extent.Text -join "`n")) } catch { }
    if(($script:events -join ',') -cne 'EXPECTED'){throw ($script:events -join ',')}
    """
    source = source.replace("FAIL", "throw 'fixture teardown failure'" if teardown_fails else "")
    source = source.replace("EXPECTED", "terminate,close_child,close_job," + ("poison" if teardown_fails else "release"))
    ps(source)


@pytest.mark.parametrize("mode", ["whatif", "register", "wrong_hash", "bad_module_pin", "bad_readback"])
def test_pinned_registrar_with_mock_scheduler(tmp_path, mode):
    (tmp_path / "data").mkdir()
    (tmp_path / "releases").mkdir()
    ops = tmp_path / "scripts" / "ops"
    ops.mkdir(parents=True)
    runner = ops / "replay_bundle_export_nightly.ps1"
    runner.write_bytes((OPS / runner.name).read_bytes())
    registrar = ops / "register_replay_bundle_export_nightly.ps1"
    registrar.write_bytes((OPS / registrar.name).read_bytes())
    (ops / "workload_admission.ps1").write_text("""
function Get-WeatherExecutionHostAssignment {param($RepoRoot) return @{dedicated_capture_execution_host_id='fixture'}}
function Get-WeatherExecutionHostId {return 'fixture'}
""")
    (ops / "training_window_contract.ps1").write_text("""
function ConvertTo-ScheduledTaskArgumentString {param($Tokens) return ($Tokens -join '|')}
""")
    expected = hashlib.sha256(runner.read_bytes()).hexdigest()
    source = r"""
    $ErrorActionPreference='Stop'
    $script:registered=0
    function git { throw 'the export is pinned by wrapper and module hashes, never a Git tip' }
    function Get-TimeZone { return @{Id='Eastern Standard Time'} }
    function New-ScheduledTaskAction {param($Execute,$Argument,$WorkingDirectory)
        return @{Execute=$Execute;Arguments=$Argument;WorkingDirectory=$WorkingDirectory}}
    function New-ScheduledTaskTrigger {param([switch]$Daily,$At)
        return @{CimClass=@{CimClassName='MSFT_TaskDailyTrigger'}; DaysInterval=1; Enabled=$true;
            StartBoundary="2030-01-10T${At}:00"; Repetition=@{Interval=''}}}
    function New-ScheduledTaskSettingsSet {
        param($MultipleInstances,[switch]$Hidden,[switch]$WakeToRun,$ExecutionTimeLimit,
              [switch]$AllowStartIfOnBatteries,[switch]$DontStopIfGoingOnBatteries)
        return @{MultipleInstances=$MultipleInstances;Hidden=[bool]$Hidden;WakeToRun=[bool]$WakeToRun;
            ExecutionTimeLimit='PT50M';StartWhenAvailable=$false;
            DisallowStartIfOnBatteries=-not [bool]$AllowStartIfOnBatteries;
            StopIfGoingOnBatteries=-not [bool]$DontStopIfGoingOnBatteries}}
    function New-ScheduledTaskPrincipal {param($UserId,$LogonType,$RunLevel)
        return @{UserId=$UserId;LogonType=$LogonType;RunLevel=$RunLevel}}
    function Register-ScheduledTask {param($TaskName,$Action,$Trigger,$Settings,$Principal,$Description,[switch]$Force)
        $script:registered++
        $script:task=@{TaskPath=[string][char]92;State='Ready';Actions=@($Action);Triggers=@($Trigger);
            Settings=$Settings;Principal=$Principal}
        if($Action.Arguments -notlike ('*-ExpectedSelfSha256|*') -or
           $Action.Arguments -notlike ('*-ExpectedModuleSha256|' + ('c'*64) + '*') -or
           $Action.Arguments -like '*ExpectedSourceTip*' -or
           $Action.Arguments -like '*05:00-08:00*' -or $Action.Arguments -like '*ExcludeUtc*'){throw 'missing pins'}
    }
    function Get-ScheduledTask {param($TaskName,$ErrorAction)
        BAD_READBACK
        return $script:task
    }
    $failed=$false
    try { INVOKE } catch { $failed=$true; Write-Output $_.Exception.Message }
    if($failed -ne EXPECT_FAILURE){Write-Output ($script:task|ConvertTo-Json -Depth 8);throw 'unexpected result'}
    if($script:registered -ne EXPECT_COUNT){throw 'unexpected Scheduler mutation'}
    """
    invoke = (f"& '{registrar}' -RepoRoot '{tmp_path}' -DataRoot '{tmp_path / 'data'}' "
              f"-ReleaseRoot '{tmp_path / 'releases'}' -OutputRoot '{tmp_path / 'panel'}' "
              f"-ExpectedModuleSha256 '{'g'*64 if mode == 'bad_module_pin' else 'c'*64}' "
              f"-ExpectedRunnerSha256 '{'0'*64 if mode == 'wrong_hash' else expected}' "
              + ("-WhatIf" if mode == "whatif" else ""))
    source = source.replace("$script:", "$global:")
    source = source.replace("INVOKE", invoke).replace("EXPECT_FAILURE", "$true" if mode in
                           {"wrong_hash", "bad_module_pin", "bad_readback"} else "$false")
    source = source.replace("EXPECT_COUNT", "1" if mode in {"register", "bad_readback"} else "0")
    source = source.replace("BAD_READBACK", "$script:task.Settings.StartWhenAvailable=$true" if mode == "bad_readback" else "")
    ps(source)


def test_runner_pins_modules_not_a_git_tip_and_has_no_interval_flag():
    text = (OPS / "replay_bundle_export_nightly.ps1").read_text(encoding="utf-8")
    assert "'--expected-module-sha256', $ExpectedModuleSha256" in text and "'--max-seconds'" in text
    for retired in ("ExpectedSourceTip", "rev-parse", "--exclude-utc", "ExcludeUtc"):
        assert retired not in text
