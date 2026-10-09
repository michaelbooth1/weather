"""Windows parser and mocked registrar/teardown checks; never touches Scheduler.

Guards: U6 nightly replay-export runner and registrar contract (docs/operations/maker-replay-bundle.md,
"Scheduled production export"), including the owner-approved 04:10 start slot (2026-10-09), and DST-C1/OD28
(docs/operations/OPERATIONS_DESIGN.md on master): both slots register a local wall-clock daily trigger through
scheduled_task_local_trigger.ps1 and refuse a zoned (fixed-offset) read-back.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
HELPER = OPS / "scheduled_task_local_trigger.ps1"
ZONED = re.compile(r"(Z|[+-]\d\d:\d\d)$")
# Pins TimeZoneInfo.Local to the capture host's zone for this child only (same probe as master's DST ratchet).
PIN_EASTERN = r"""
$staticFlags = [Reflection.BindingFlags]'NonPublic,Static'
$instanceFlags = [Reflection.BindingFlags]'NonPublic,Instance'
$cache = [TimeZoneInfo].GetField('s_cachedData', $staticFlags).GetValue($null)
$cache.GetType().GetField('m_localTimeZone', $instanceFlags).SetValue(
    $cache, [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time'))
$oneYear = $cache.GetType().GetField('m_oneYearLocalFromUtc', $instanceFlags)
if ($oneYear) { $oneYear.SetValue($cache, $null) }
if ([TimeZoneInfo]::Local.Id -ne 'Eastern Standard Time') { throw 'time zone pin failed' }
"""
pytestmark = [pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell required"), pytest.mark.spawns]


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


def run_mock_registrar(tmp_path, mode, at=None, real_trigger_day=None):
    (tmp_path / "data").mkdir()
    (tmp_path / "releases").mkdir()
    deploy = tmp_path / "deploy"  # the exact-tip tree; production must be a disjoint tree
    ops = deploy / "scripts" / "ops"
    ops.mkdir(parents=True)
    runner = ops / "replay_bundle_export_nightly.ps1"
    runner.write_bytes((OPS / runner.name).read_bytes())
    registrar = ops / "register_replay_bundle_export_nightly.ps1"
    registrar.write_bytes((OPS / registrar.name).read_bytes())
    (ops / HELPER.name).write_bytes(HELPER.read_bytes())  # dot-sourced from beside the registrar
    production = tmp_path / "production"
    (production / "scripts" / "ops").mkdir(parents=True)
    (production / "scripts" / "ops" / "workload_admission.ps1").write_text("""
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
    TRIGGER_FIXTURE
    function New-ScheduledTaskSettingsSet {
        param($MultipleInstances,[switch]$Hidden,[switch]$WakeToRun,$ExecutionTimeLimit,
              [switch]$AllowStartIfOnBatteries,[switch]$DontStopIfGoingOnBatteries)
        return @{MultipleInstances=$MultipleInstances;Hidden=[bool]$Hidden;WakeToRun=[bool]$WakeToRun;
            ExecutionTimeLimit=('PT{0}M' -f [int]$ExecutionTimeLimit.TotalMinutes);StartWhenAvailable=$false;
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
           $Action.Arguments -notlike ('*-DeployRoot|DEPLOY|-ProductionRoot|PRODUCTION|*') -or
           $Action.Arguments -notlike '*-MinAvailableMiB|7168' -or $Action.Arguments -like '*-RepoRoot|*' -or
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
    if($script:task){Write-Output ('SLOT ' + $script:task.Triggers[0].StartBoundary + ' ' +
        $script:task.Settings.ExecutionTimeLimit)}
    """
    if real_trigger_day:
        # The real cmdlet and helper under a pinned Eastern zone; only "today" is fixed (summer or winter).
        # Import first: the module's CDXML functions would otherwise replace the Scheduler mocks on auto-load.
        source = "\nImport-Module ScheduledTasks" + source
        trigger_fixture = PIN_EASTERN + f"function Get-Date {{ return [datetime]'{real_trigger_day}' }}"
    else:
        # Like the real cmdlet, the mock returns a zoned (fixed-offset) boundary; the helper must replace it.
        trigger_fixture = """function New-ScheduledTaskTrigger {param([switch]$Daily,$At)
        return @{CimClass=@{CimClassName='MSFT_TaskDailyTrigger'}; DaysInterval=1; Enabled=$true;
            StartBoundary="2030-01-10T${At}:00-04:00"; Repetition=@{Interval=''}}}"""
    source = source.replace("TRIGGER_FIXTURE", trigger_fixture)
    invoke = (f"& '{registrar}' -RepoRoot '{deploy}' -DataRoot '{tmp_path / 'data'}' "
              f"-ReleaseRoot '{tmp_path / 'releases'}' -OutputRoot '{tmp_path / 'panel'}' "
              f"-ExpectedModuleSha256 '{'g'*64 if mode == 'bad_module_pin' else 'c'*64}' "
              f"-ExpectedRunnerSha256 '{'0'*64 if mode == 'wrong_hash' else expected}' "
              f"-ProductionRoot '{production}' -MinAvailableMiB 7168 "
              + (f"-At '{at}' " if at else "")
              + ("-WhatIf" if mode == "whatif" else ""))
    source = source.replace("DEPLOY", str(deploy)).replace("PRODUCTION", str(production))
    source = source.replace("$script:", "$global:")
    source = source.replace("INVOKE", invoke).replace("EXPECT_FAILURE", "$true" if mode in
                           {"wrong_hash", "bad_module_pin", "bad_readback", "zoned_readback"} else "$false")
    source = source.replace("EXPECT_COUNT", "1" if mode in {"register", "bad_readback", "zoned_readback"} else "0")
    bad = {"bad_readback": "$global:task.Settings.StartWhenAvailable=$true",
           # What Task Scheduler stores for a bare `-Daily -At` registered in EDT (DST-C1): same wall time, fixed offset.
           "zoned_readback": "$global:task.Triggers[0].StartBoundary=[string]$global:task.Triggers[0].StartBoundary+'-04:00'"}
    source = source.replace("BAD_READBACK", bad.get(mode, ""))
    return ps(source)


@pytest.mark.parametrize("mode", ["whatif", "register", "wrong_hash", "bad_module_pin", "bad_readback"])
def test_pinned_registrar_with_mock_scheduler(tmp_path, mode):
    out = run_mock_registrar(tmp_path, mode)
    if mode == "bad_readback":
        assert "registration readback differs from pinned nightly contract" in out


@pytest.mark.parametrize(("at", "minutes"), [(None, 50), ("00:35", 50), ("04:10", 45)])
def test_registrar_slot_sets_trigger_and_scheduler_limit(tmp_path, at, minutes):
    # 04:10 + 45 min = 04:55: the Scheduler backstop fires before the 05:00 tiering (owner decision 2026-10-09).
    # The cmdlet's zoned "-04:00" boundary is replaced by an unzoned local one (DST-C1).
    out = run_mock_registrar(tmp_path, "register", at)
    assert re.search(rf"SLOT \d{{4}}-\d\d-\d\dT{at or '00:35'}:00 PT{minutes}M", out), out


@pytest.mark.parametrize("at", ["00:35", "04:10"])
def test_registrar_refuses_a_zoned_trigger_readback(tmp_path, at):
    # A [datetime] cast would read "...T04:10:00-04:00" as 04:10 in EDT and hide the defect; the helper refuses it.
    out = run_mock_registrar(tmp_path, "zoned_readback", at)
    assert "registration readback differs from pinned nightly contract" in out


@pytest.mark.parametrize("day", ["2026-07-10", "2026-12-10"])  # EDT (summer) and EST (winter) registrations
@pytest.mark.parametrize("at", ["00:35", "04:10"])
def test_registrar_real_trigger_is_local_wall_clock_in_summer_and_winter(tmp_path, at, day):
    # Real New-ScheduledTaskTrigger plus the helper; only Register/Get-ScheduledTask are mocked.
    out = run_mock_registrar(tmp_path, "register", at, real_trigger_day=day)
    minutes = 45 if at == "04:10" else 50
    slot = re.search(r"^SLOT (\S+) (\S+)$", out, re.MULTILINE)
    assert slot, out
    assert slot.group(1) == f"{day}T{at}:00" and not ZONED.search(slot.group(1))
    assert slot.group(2) == f"PT{minutes}M"


@pytest.mark.parametrize("day", ["2026-07-10", "2026-12-10"])
@pytest.mark.parametrize("at", ["00:35", "04:10"])
def test_local_trigger_survives_a_task_definition_and_the_bare_cmdlet_is_zoned(at, day):
    # The Task Scheduler definition (built with NewTask, never saved) keeps the boundary unzoned, so it fires at
    # the same Toronto wall time after 2026-11-01; the bare cmdlet's boundary is a fixed instant (the defect).
    source = ("$ErrorActionPreference='Stop'\n" + PIN_EASTERN
              + f"function Get-Date {{ return [datetime]'{day}' }}\n. '{HELPER}'\n" + f"""
    $trigger = New-WeatherLocalDailyTrigger -At '{at}'
    $service = New-Object -ComObject Schedule.Service
    $service.Connect()
    $definition = $service.NewTask(0)
    $com = $definition.Triggers.Create(2)
    $com.StartBoundary = [string]$trigger.StartBoundary
    $com.DaysInterval = 1
    $xml = [xml]$definition.XmlText
    $plain = New-ScheduledTaskTrigger -Daily -At '{at}'
    [pscustomobject]@{{ boundary = [string]$trigger.StartBoundary; cls = [string]$trigger.CimClass.CimClassName
        xml = [string]$xml.Task.Triggers.CalendarTrigger.StartBoundary; plain = [string]$plain.StartBoundary
        readback = [bool](Test-WeatherLocalDailyStartBoundary -StartBoundary ([string]$trigger.StartBoundary) -At '{at}')
        zoned_refused = -not (Test-WeatherLocalDailyStartBoundary -StartBoundary '{day}T{at}:00-04:00' -At '{at}')
    }} | ConvertTo-Json -Compress
    """)
    payload = json.loads([line for line in ps(source).splitlines() if line.strip()][-1])
    assert payload["boundary"] == f"{day}T{at}:00" and payload["cls"] == "MSFT_TaskDailyTrigger"
    assert payload["xml"] == payload["boundary"]
    assert payload["readback"] is True and payload["zoned_refused"] is True
    assert ZONED.search(payload["plain"]), payload["plain"]


@pytest.mark.parametrize("at", ["00:35", "04:10"])
def test_registrar_whatif_names_slot_and_limit_without_scheduler_io(tmp_path, at):
    out = run_mock_registrar(tmp_path, "whatif", at)
    limit = 45 if at == "04:10" else 50
    assert f"Register daily {at} export with a {limit}-minute limit; pin modules {'c' * 64}" in out
    assert "SLOT" not in out


@pytest.mark.parametrize("at", ["00:40", "04:09", "04:15", "05:00"])
def test_registrar_rejects_unapproved_slots(tmp_path, at):
    registrar = OPS / "register_replay_bundle_export_nightly.ps1"
    ps(f"$ErrorActionPreference='Stop'; try {{ & '{registrar}' -RepoRoot '{tmp_path}' -DataRoot '{tmp_path}' "
       f"-ReleaseRoot '{tmp_path}' -OutputRoot '{tmp_path / 'out'}' -ExpectedModuleSha256 '{'c' * 64}' "
       f"-ExpectedRunnerSha256 '{'0' * 64}' -ProductionRoot '{tmp_path}' -MinAvailableMiB 7168 -At '{at}' -WhatIf; "
       "throw 'accepted' } catch { if($_.FullyQualifiedErrorId -notlike 'ParameterArgumentValidationError*'){ throw } }")


def test_0410_slot_composes_with_unchanged_runner_deadline_across_dst():
    # The runner (WRAP unchanged) clamps a 04:10 start to its 04:54:45 boundary: deadline 2,685 s, child budget
    # 2,655 s (< 2,700), teardown (5 s) done before the 45-minute Scheduler limit (04:55) and the 05:00 tiering.
    source = parse(OPS / "replay_bundle_export_nightly.ps1") + """
    $fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $n.Name -eq 'Get-ReplayExportDeadline'},$true)
    Invoke-Expression $fn.Extent.Text
    foreach($utc in @('2030-01-10T09:10:00Z','2030-07-10T08:10:00Z')) {
        $start=[datetime]::Parse($utc).ToUniversalTime()
        $deadline=Get-ReplayExportDeadline $start
        $seconds=($deadline-$start).TotalSeconds
        $budget=[Math]::Floor($seconds) - 30
        if($seconds -ne 2685 -or $budget -ge 2700){throw "04:10 not clamped: $seconds"}
        if($deadline.AddSeconds(5) -ge $start.AddMinutes(45)){throw 'teardown not before the Scheduler limit'}
    }
    """
    ps(source)


def test_runner_pins_modules_not_a_git_tip_and_has_no_interval_flag():
    text = (OPS / "replay_bundle_export_nightly.ps1").read_text(encoding="utf-8")
    assert "'--expected-module-sha256', $ExpectedModuleSha256" in text and "'--max-seconds'" in text
    for retired in ("ExpectedSourceTip", "rev-parse", "--exclude-utc", "ExcludeUtc"):
        assert retired not in text


def test_registrar_refuses_nested_deploy_and_production_trees(tmp_path):
    deploy = tmp_path / "deploy"
    ops = deploy / "scripts" / "ops"
    ops.mkdir(parents=True)
    registrar = ops / "register_replay_bundle_export_nightly.ps1"
    registrar.write_bytes((OPS / registrar.name).read_bytes())
    for name in ("data", "releases"):
        (tmp_path / name).mkdir()
    for production in (deploy, deploy / "inner", tmp_path):
        production.mkdir(exist_ok=True)
        source = (f"$ErrorActionPreference='Stop'; try {{ & '{registrar}' -RepoRoot '{deploy}' "
                  f"-DataRoot '{tmp_path / 'data'}' -ReleaseRoot '{tmp_path / 'releases'}' "
                  f"-OutputRoot '{tmp_path / 'panel'}' -ExpectedModuleSha256 '{'c' * 64}' -ExpectedRunnerSha256 "
                  f"'{'0' * 64}' -ProductionRoot '{production}' -MinAvailableMiB 7168 -WhatIf; throw 'accepted' }} "
                  "catch { if($_.Exception.Message -notlike '*must be disjoint trees*'){ throw } }")
        ps(source)
