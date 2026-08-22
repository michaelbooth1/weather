import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
CONTRACT = OPS / "integration_attempt_contract.ps1"
REGISTRAR = OPS / "register_integration_attempt.ps1"
CREATOR = OPS / "new_integration_attempt.ps1"


def _run_powershell(script: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_REGISTRATION_CONTRACT": str(CONTRACT),
            "WEATHER_REGISTRATION_ROOT": str(ROOT),
            **extra_env,
        }
    )
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_registrar_journals_before_mutation_and_binds_complete_task_identity() -> None:
    registrar = REGISTRAR.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    creator = CREATOR.read_text(encoding="utf-8-sig")

    assert registrar.index("Write-WeatherIntegrationImmutableJson -Path $registrationIntentPath") < registrar.index(
        "Register-ScheduledTask"
    )
    assert registrar.count("-WakeToRun") == 2
    # Omission at creation deliberately preserves the missed-one-shot policy;
    # the shared live validator proves the resulting setting is false.
    assert "StartWhenAvailable" not in registrar
    assert "Assert-WeatherIntegrationScheduledTaskBinding" in registrar
    assert "Assert-WeatherIntegrationRegistrationReceipt" in registrar
    assert "registration_intent_sha256" in registrar
    assert "trigger = $suiteBinding.trigger" in registrar
    assert "settings = $suiteBinding.settings" in registrar

    assert "weather_integration_attempt_registration_intent_v1" in contract
    assert "Assert-WeatherIntegrationAttemptTaskBinding" in contract
    assert "StartWhenAvailable" in contract
    assert "WakeToRun" in contract
    assert "ExecutionTimeLimit" in contract
    assert "MSFT_TaskTimeTrigger" in contract
    assert "ConvertFrom-WeatherIntegrationEvidenceTimestamp" in contract
    assert "pre-registration intent" in contract

    assert "AdditionalPythonPath is unsupported" in creator
    assert creator.index("AdditionalPythonPath is unsupported") < creator.index(
        "New-Item -ItemType Directory -Path $AttemptRoot"
    )
    assert 'registration_intent = Join-Path $AttemptRoot "registration-intent.json"' in creator
    assert "boot_recovery.ps1" in creator
    assert "boot_recovery.ps1" in contract
    assert "register_boot_recovery.ps1" in creator
    assert "register_boot_recovery.ps1" in contract
    assert 'LockLeaf "integration_attempt_terminal.lock"' in registrar
    terminal_lock = registrar.index('LockLeaf "integration_attempt_terminal.lock"')
    terminal_check = registrar.index("Assert-WeatherIntegrationAttemptNotTerminal", terminal_lock)
    intent_write = registrar.index(
        "Write-WeatherIntegrationImmutableJson -Path $registrationIntentPath"
    )
    first_scheduler_write = registrar.index("Register-ScheduledTask")
    assert terminal_lock < terminal_check < intent_write < first_scheduler_write


def test_exact_task_binding_rejects_trigger_principal_and_setting_drift() -> None:
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REGISTRATION_CONTRACT
$root = $env:WEATHER_REGISTRATION_ROOT
$invalidTimestampAccepted = $false
try {
    ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value '2026-08-21T20:00:00' `
        -Label 'test timestamp' | Out-Null
    $invalidTimestampAccepted = $true
}
catch { }
if ($invalidTimestampAccepted) {
    throw 'Evidence timestamp without an explicit offset was accepted.'
}
$manifest = [pscustomobject]@{
    attempt_id = 'binding-test'
    attempt_root = (Join-Path $root 'data\binding-test')
    repo_root = $root
    schedule = [pscustomobject]@{
        suite_task_name = 'WeatherIntegrationSuite_binding-test'
        merge_task_name = 'WeatherIntegrationMerge_binding-test'
        suite_at_local = '2026-08-22T00:35:00'
        merge_at_local = '2026-08-22T01:30:00'
    }
    orchestration = [pscustomobject]@{
        attempt_suite = [pscustomobject]@{
            path = (Join-Path $root 'scripts\ops\integration_attempt_suite.ps1')
            sha256 = ('a' * 64)
        }
        attempt_merge = [pscustomobject]@{
            path = (Join-Path $root 'scripts\ops\integration_attempt_merge.ps1')
            sha256 = ('b' * 64)
        }
    }
    evidence = [pscustomobject]@{}
}
$contract = [pscustomobject]@{
    Manifest = $manifest
    ManifestPath = (Join-Path $root 'data\binding-test\manifest.json')
    ManifestSha256 = ('c' * 64)
    AttemptRoot = (Join-Path $root 'data\binding-test')
}
$suite = Get-WeatherIntegrationExpectedTaskBinding `
    -AttemptContract $contract -Role suite -UserId 'integration-user'
$merge = Get-WeatherIntegrationExpectedTaskBinding `
    -AttemptContract $contract -Role merge -UserId 'integration-user'
$evidence = [pscustomobject]@{
    principal = [pscustomobject]@{
        user_id = 'integration-user'
        logon_type = 'S4U'
        run_level = 'Limited'
        id = 'Author'
        display_name = ''
        group_id = ''
        process_token_sid_type = 'Default'
        required_privileges = @()
    }
    suite = $suite
    merge = $merge
}
function New-ExactTask {
    $triggerWallClock = [datetime]::SpecifyKind(
        [datetime]'2026-08-22T00:35:00',
        [DateTimeKind]::Unspecified
    )
    $triggerOffset = [TimeZoneInfo]::Local.GetUtcOffset($triggerWallClock)
    $startBoundary = ([datetimeoffset]::new($triggerWallClock, $triggerOffset)).ToString(
        'yyyy-MM-ddTHH:mm:sszzz',
        [Globalization.CultureInfo]::InvariantCulture
    )
    $trigger = [pscustomobject]@{
        CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskTimeTrigger' }
        Id = ''
        Enabled = $true
        StartBoundary = $startBoundary
        EndBoundary = ''
        RandomDelay = ''
        ExecutionTimeLimit = ''
        Repetition = [pscustomobject]@{
            Interval = ''
            Duration = ''
            StopAtDurationEnd = $false
        }
    }
    return [pscustomobject]@{
        State = 'Ready'
        TaskPath = '\'
        Description = [string]$suite.description
        Actions = @([pscustomobject]@{
            Id = ''
            Execute = [string]$suite.executable
            Arguments = [string]$suite.arguments
            WorkingDirectory = [string]$suite.working_directory
        })
        Principal = [pscustomobject]@{
            UserId = 'integration-user'
            LogonType = 'S4U'
            RunLevel = 'Limited'
            Id = 'Author'
            DisplayName = ''
            GroupId = ''
            ProcessTokenSidType = 'Default'
            RequiredPrivilege = @()
        }
        Triggers = @($trigger)
        Settings = [pscustomobject]@{
            MultipleInstances = 'IgnoreNew'
            Compatibility = 'Win7'
            AllowDemandStart = $true
            AllowHardTerminate = $true
            DeleteExpiredTaskAfter = ''
            ExecutionTimeLimit = 'PT8H'
            Hidden = $false
            Priority = 7
            RestartCount = 0
            RestartInterval = ''
            WakeToRun = $true
            StartWhenAvailable = $false
            DisallowStartIfOnBatteries = $false
            StopIfGoingOnBatteries = $false
            RunOnlyIfIdle = $false
            RunOnlyIfNetworkAvailable = $false
            DisallowStartOnRemoteAppSession = $false
            UseUnifiedSchedulingEngine = $true
            volatile = $false
            MaintenanceSettings = ''
            IdleSettings = [pscustomobject]@{
                IdleDuration = 'PT10M'
                RestartOnIdle = $false
                StopOnIdleEnd = $true
                WaitTimeout = 'PT1H'
            }
            NetworkSettings = [pscustomobject]@{ Id = ''; Name = '' }
        }
    }
}

Assert-WeatherIntegrationScheduledTaskObject `
    -Task (New-ExactTask) -BindingEvidence $evidence -Role suite | Out-Null

$cases = @(
    [pscustomobject]@{ Name = 'wake'; Mutate = { param($t) $t.Settings.WakeToRun = $false } },
    [pscustomobject]@{ Name = 'late-start'; Mutate = { param($t) $t.Settings.StartWhenAvailable = $true } },
    [pscustomobject]@{ Name = 'parallel'; Mutate = { param($t) $t.Settings.MultipleInstances = 'Parallel' } },
    [pscustomobject]@{ Name = 'limit'; Mutate = { param($t) $t.Settings.ExecutionTimeLimit = 'PT7H' } },
    [pscustomobject]@{ Name = 'restart'; Mutate = { param($t) $t.Settings.RestartCount = 1 } },
    [pscustomobject]@{ Name = 'principal'; Mutate = { param($t) $t.Principal.UserId = 'other-user' } },
    [pscustomobject]@{ Name = 'principal-token'; Mutate = { param($t) $t.Principal.ProcessTokenSidType = 'Unrestricted' } },
    [pscustomobject]@{ Name = 'trigger'; Mutate = { param($t) $t.Triggers[0].StartBoundary = '2026-08-22T00:36:00-04:00' } },
    [pscustomobject]@{ Name = 'offset'; Mutate = {
        param($t)
        $wall = [datetime]::SpecifyKind([datetime]'2026-08-22T00:35:00', [DateTimeKind]::Unspecified)
        $expected = [TimeZoneInfo]::Local.GetUtcOffset($wall)
        $wrong = if ($expected -ne [TimeSpan]::FromHours(12)) {
            [TimeSpan]::FromHours(12)
        }
        else {
            [TimeSpan]::FromHours(-12)
        }
        $t.Triggers[0].StartBoundary = ([datetimeoffset]::new($wall, $wrong)).ToString(
            'yyyy-MM-ddTHH:mm:sszzz',
            [Globalization.CultureInfo]::InvariantCulture
        )
    } },
    [pscustomobject]@{ Name = 'repeat'; Mutate = { param($t) $t.Triggers[0].Repetition.Interval = 'PT1M' } },
    [pscustomobject]@{ Name = 'path'; Mutate = { param($t) $t.TaskPath = '\Other\' } },
    [pscustomobject]@{ Name = 'action'; Mutate = { param($t) $t.Actions[0].Arguments += ' -Injected' } },
    [pscustomobject]@{ Name = 'action-id'; Mutate = { param($t) $t.Actions[0].Id = 'other-action' } }
)
foreach ($case in $cases) {
    $candidate = New-ExactTask
    & $case.Mutate $candidate
    $rejected = $false
    try {
        Assert-WeatherIntegrationScheduledTaskObject `
            -Task $candidate -BindingEvidence $evidence -Role suite | Out-Null
    }
    catch {
        $rejected = $true
    }
    if (-not $rejected) {
        throw "Exact task validator accepted drift case: $($case.Name)"
    }
}
"PASS"
"""
    result = _run_powershell(script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS"


def test_pre_registration_intent_can_close_tasks_after_registrar_crash(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt"
    attempt_root.mkdir()
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REGISTRATION_CONTRACT
$root = $env:WEATHER_REGISTRATION_ROOT
$attemptRoot = $env:WEATHER_REGISTRATION_ATTEMPT_ROOT
$intentPath = Join-Path $attemptRoot 'registration-intent.json'
$manifest = [pscustomobject]@{
    attempt_id = 'crash-test'
    attempt_root = $attemptRoot
    repo_root = $root
    schedule = [pscustomobject]@{
        suite_task_name = 'WeatherIntegrationSuite_crash-test'
        merge_task_name = 'WeatherIntegrationMerge_crash-test'
        suite_at_local = '2026-08-22T00:35:00'
        merge_at_local = '2026-08-22T01:30:00'
    }
    orchestration = [pscustomobject]@{
        attempt_suite = [pscustomobject]@{
            path = (Join-Path $root 'scripts\ops\integration_attempt_suite.ps1')
            sha256 = ('a' * 64)
        }
        attempt_merge = [pscustomobject]@{
            path = (Join-Path $root 'scripts\ops\integration_attempt_merge.ps1')
            sha256 = ('b' * 64)
        }
    }
    evidence = [pscustomobject]@{
        registration_intent = $intentPath
        registration_receipt = (Join-Path $attemptRoot 'registration-receipt.json')
    }
}
$contract = [pscustomobject]@{
    Manifest = $manifest
    ManifestPath = (Join-Path $attemptRoot 'manifest.json')
    ManifestSha256 = ('c' * 64)
    AttemptRoot = $attemptRoot
}
$suite = Get-WeatherIntegrationExpectedTaskBinding `
    -AttemptContract $contract -Role suite -UserId 'integration-user'
$merge = Get-WeatherIntegrationExpectedTaskBinding `
    -AttemptContract $contract -Role merge -UserId 'integration-user'
$intent = [ordered]@{
    schema = $script:WeatherIntegrationAttemptRegistrationIntentSchema
    status = 'PREPARED'
    binding_contract = $script:WeatherIntegrationAttemptTaskBindingContract
    attempt_id = 'crash-test'
    intent_path = $intentPath
    manifest_path = $contract.ManifestPath
    manifest_sha256 = $contract.ManifestSha256
    prepared_at_local = '2026-08-21T20:00:00.0000000-04:00'
    principal = [ordered]@{
        user_id = 'integration-user'
        logon_type = 'S4U'
        run_level = 'Limited'
        id = 'Author'
        display_name = ''
        group_id = ''
        process_token_sid_type = 'Default'
        required_privileges = @()
    }
    suite = $suite
    merge = $merge
    safety = [ordered]@{
        authority = 'NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY'
        credential_value_access_authorized = $false
        live_exchange_mutation_authorized = $false
    }
}
Write-WeatherIntegrationImmutableJson -Path $intentPath -Payload $intent

function New-CrashTask([object]$record) {
    $wallClock = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$record.trigger.at_local) `
        -Label 'test trigger'
    $offset = [TimeZoneInfo]::Local.GetUtcOffset($wallClock)
    $startBoundary = ([datetimeoffset]::new($wallClock, $offset)).ToString(
        'yyyy-MM-ddTHH:mm:sszzz',
        [Globalization.CultureInfo]::InvariantCulture
    )
    return [pscustomobject]@{
        State = 'Ready'
        TaskPath = '\'
        Description = [string]$record.description
        Actions = @([pscustomobject]@{
            Id = ''
            Execute = [string]$record.executable
            Arguments = [string]$record.arguments
            WorkingDirectory = [string]$record.working_directory
        })
        Principal = [pscustomobject]@{
            UserId = 'integration-user'
            LogonType = 'S4U'
            RunLevel = 'Limited'
            Id = 'Author'
            DisplayName = ''
            GroupId = ''
            ProcessTokenSidType = 'Default'
            RequiredPrivilege = @()
        }
        Triggers = @([pscustomobject]@{
            CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskTimeTrigger' }
            Id = ''
            Enabled = $true
            StartBoundary = $startBoundary
            EndBoundary = ''
            RandomDelay = ''
            ExecutionTimeLimit = ''
            Repetition = [pscustomobject]@{
                Interval = ''
                Duration = ''
                StopAtDurationEnd = $false
            }
        })
        Settings = [pscustomobject]@{
            MultipleInstances = 'IgnoreNew'
            Compatibility = 'Win7'
            AllowDemandStart = $true
            AllowHardTerminate = $true
            DeleteExpiredTaskAfter = ''
            ExecutionTimeLimit = [string]$record.settings.execution_time_limit
            Hidden = $false
            Priority = 7
            RestartCount = 0
            RestartInterval = ''
            WakeToRun = $true
            StartWhenAvailable = $false
            DisallowStartIfOnBatteries = $false
            StopIfGoingOnBatteries = $false
            RunOnlyIfIdle = $false
            RunOnlyIfNetworkAvailable = $false
            DisallowStartOnRemoteAppSession = $false
            UseUnifiedSchedulingEngine = $true
            volatile = $false
            MaintenanceSettings = ''
            IdleSettings = [pscustomobject]@{
                IdleDuration = 'PT10M'
                RestartOnIdle = $false
                StopOnIdleEnd = $true
                WaitTimeout = 'PT1H'
            }
            NetworkSettings = [pscustomobject]@{ Id = ''; Name = '' }
        }
    }
}
$global:crashTasks = @{
    'WeatherIntegrationSuite_crash-test' = New-CrashTask $suite
    'WeatherIntegrationMerge_crash-test' = New-CrashTask $merge
}
function Get-ScheduledTask {
    param([string]$TaskName, $ErrorAction)
    return $global:crashTasks[$TaskName]
}
function Disable-ScheduledTask {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    $global:crashTasks[$TaskName].State = 'Disabled'
    return $global:crashTasks[$TaskName]
}
function Get-ScheduledTaskInfo {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    return [pscustomobject]@{
        LastRunTime = [datetime]'1999-11-30T00:00:00'
        LastTaskResult = 0x41303
    }
}
$evidence = @(Disable-WeatherIntegrationAttemptTasks -AttemptContract $contract)
if ($evidence.Count -ne 2 -or
    @($evidence | Where-Object { -not $_.disabled }).Count -ne 0 -or
    @($evidence | Where-Object { $_.binding_source -ne 'pre_registration_intent' }).Count -ne 0) {
    throw 'Crash-close evidence did not prove both intent-bound tasks disabled.'
}
foreach ($task in $global:crashTasks.Values) {
    $task.State = 'Ready'
}
function New-ReceiptTaskRecord([object]$record) {
    return [ordered]@{
        task_name = [string]$record.task_name
        trigger_at_local = [string]$record.trigger.at_local
        registered = $true
        task_path = [string]$record.task_path
        description = [string]$record.description
        action_id = [string]$record.action_id
        executable = [string]$record.executable
        arguments = [string]$record.arguments
        working_directory = [string]$record.working_directory
        script_sha256 = [string]$record.script_sha256
        trigger = $record.trigger
        settings = $record.settings
    }
}
$receipt = [ordered]@{
    schema = $script:WeatherIntegrationAttemptRegistrationReceiptSchema
    status = 'PASS'
    binding_contract = $script:WeatherIntegrationAttemptTaskBindingContract
    attempt_id = 'crash-test'
    manifest_path = $contract.ManifestPath
    manifest_sha256 = $contract.ManifestSha256
    registration_intent_path = $intentPath
    registration_intent_sha256 = Get-WeatherIntegrationFileSha256 -Path $intentPath
    registered_at_local = '2026-08-21T20:01:00.0000000-04:00'
    principal = $intent.principal
    suite = New-ReceiptTaskRecord $suite
    merge = New-ReceiptTaskRecord $merge
    downstream_tasks_created = $false
    failure = $null
    safety = $intent.safety
}
Write-WeatherIntegrationImmutableJson `
    -Path ([string]$manifest.evidence.registration_receipt) `
    -Payload $receipt
$runtimeBinding = Assert-WeatherIntegrationAttemptTaskBinding `
    -AttemptContract $contract `
    -Role suite `
    -IncludeTaskInfo
if ([string]$runtimeBinding.Task.State -ne 'Ready' -or
    [string]$runtimeBinding.RegistrationReceipt.status -ne 'PASS' -or
    [string]::IsNullOrWhiteSpace([string]$runtimeBinding.RegistrationIntentSha256)) {
    throw 'Runtime binding did not consume the exact PASS receipt and intent.'
}
[System.IO.File]::WriteAllText(
    [string]$manifest.evidence.registration_receipt,
    '{',
    (New-Object System.Text.UTF8Encoding($false))
)
$tornReceiptEvidence = @(Disable-WeatherIntegrationAttemptTasks -AttemptContract $contract)
if ($tornReceiptEvidence.Count -ne 2 -or
    @($tornReceiptEvidence | Where-Object { -not $_.disabled }).Count -ne 0 -or
    @($tornReceiptEvidence | Where-Object { $_.binding_source -ne 'pre_registration_intent_receipt_unusable' }).Count -ne 0 -or
    @($tornReceiptEvidence | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.registration_receipt_error) }).Count -ne 0) {
    throw 'A torn final receipt stranded tasks despite a valid pre-registration intent.'
}
"PASS"
"""
    result = _run_powershell(
        script,
        WEATHER_REGISTRATION_ATTEMPT_ROOT=str(attempt_root),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS"
