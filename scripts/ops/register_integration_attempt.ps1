# Register the two one-shot tasks for an immutable integration attempt. This
# script does not start either task and does not create downstream work.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedManifestSha256,
    [ValidateRange(1, 120)]
    [int]$MinimumSuiteLeadMinutes = 1,
    [switch]$StageDisabled
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

$RepoRoot = Resolve-WeatherIntegrationPath -Path $RepoRoot
$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract
$preparationAuthorization = `
    Assert-WeatherIntegrationRegistrationPreparationState `
        -AttemptContract $contract
if (-not $StageDisabled) {
    throw "Integration-attempt tasks must be registered through the disabled staging transaction."
}
Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase "attempt registration" | Out-Null
$manifest = $contract.Manifest
if (-not (Test-WeatherIntegrationPathEqual -Left $RepoRoot -Right ([string]$manifest.repo_root))) {
    throw "Registrar RepoRoot does not match the immutable attempt manifest."
}

$terminalMutex = Enter-WeatherIntegrationControlMutex `
    -RepositoryRoot $RepoRoot `
    -LockLeaf "integration_attempt_terminal.lock" `
    -Owner "register_integration_attempt:$($manifest.attempt_id)"
if ($null -eq $terminalMutex) {
    throw "Another registrar/close/reconciliation owns the integration-attempt terminal mutex."
}
try {
Assert-WeatherIntegrationAttemptNotTerminal `
    -AttemptContract $contract -Operation "Integration-attempt registration"

$registrationReceiptPath = [string]$manifest.evidence.registration_receipt
if (Test-Path -LiteralPath $registrationReceiptPath) {
    throw "Immutable registration receipt already exists and will not be replaced: $registrationReceiptPath"
}
$registrationIntentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $contract
if (Test-Path -LiteralPath $registrationIntentPath) {
    throw "Immutable pre-registration intent already exists and will not be replaced: $registrationIntentPath"
}

$tokenContractScript = Join-Path $RepoRoot "scripts\ops\training_window_contract.ps1"
$suiteScript = Join-Path $RepoRoot "scripts\ops\integration_attempt_suite.ps1"
$mergeScript = Join-Path $RepoRoot "scripts\ops\integration_attempt_merge.ps1"
foreach ($requiredScript in @($tokenContractScript, $suiteScript, $mergeScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "Required integration-attempt registration script is missing: $requiredScript"
    }
}
. $tokenContractScript

$powerShellExecutable = Join-Path $PSHOME "powershell.exe"
if (-not (Test-Path -LiteralPath $powerShellExecutable -PathType Leaf)) {
    throw "Windows PowerShell executable is missing: $powerShellExecutable"
}
if ([string]::IsNullOrWhiteSpace($env:USERNAME)) {
    throw "USERNAME is unavailable; cannot construct the S4U task principal."
}

$suiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
    -Value ([string]$manifest.schedule.suite_at_local) `
    -Label "suite_at_local"
$mergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
    -Value ([string]$manifest.schedule.merge_at_local) `
    -Label "merge_at_local"
$now = Get-Date
if ($suiteAt -le $now.AddMinutes(1) -or $mergeAt -le $suiteAt) {
    throw "Attempt task triggers must be future one-shot times with suite before merge."
}
if ($suiteAt.Date -ne $mergeAt.Date) {
    throw "Attempt tasks must run on the same local calendar day."
}
$suiteMinute = ($suiteAt.Hour * 60) + $suiteAt.Minute
$mergeMinute = ($mergeAt.Hour * 60) + $mergeAt.Minute
if ($suiteMinute -lt 30 -or $suiteMinute -ge (9 * 60)) {
    throw "Suite trigger is outside the admitted 00:30-09:00 local host window."
}
if ($mergeMinute -lt 60 -or $mergeMinute -ge 220) {
    throw "Merge trigger is outside the guarded 01:00-03:40 quiet window."
}
if (($mergeAt - $suiteAt) -lt [TimeSpan]::FromMinutes(30)) {
    throw "Merge trigger must remain at least 30 minutes after the suite trigger."
}

$suiteTaskName = [string]$manifest.schedule.suite_task_name
$mergeTaskName = [string]$manifest.schedule.merge_task_name
$schedulerSnapshot = @(Get-ScheduledTask -ErrorAction Stop)
foreach ($taskName in @($suiteTaskName, $mergeTaskName)) {
    if ($taskName -notmatch '^WeatherIntegration(?:Suite|Merge)_[A-Za-z0-9][A-Za-z0-9._-]{0,47}$') {
        throw "Manifest task name is unsafe: $taskName"
    }
    if (@($schedulerSnapshot | Where-Object {
            [string]$_.TaskName -ieq $taskName -and [string]$_.TaskPath -ieq "\"
        }).Count -ne 0) {
        throw "Attempt task already exists and will not be replaced: $taskName"
    }
}

$suiteBinding = Get-WeatherIntegrationExpectedTaskBinding `
    -AttemptContract $contract `
    -Role "suite" `
    -UserId $env:USERNAME `
    -PowerShellExecutable $powerShellExecutable
$mergeBinding = Get-WeatherIntegrationExpectedTaskBinding `
    -AttemptContract $contract `
    -Role "merge" `
    -UserId $env:USERNAME `
    -PowerShellExecutable $powerShellExecutable
$suiteArguments = [string]$suiteBinding.arguments
$mergeArguments = [string]$mergeBinding.arguments

$suiteAction = New-ScheduledTaskAction `
    -Execute $powerShellExecutable `
    -Argument $suiteArguments `
    -WorkingDirectory $RepoRoot
$mergeAction = New-ScheduledTaskAction `
    -Execute $powerShellExecutable `
    -Argument $mergeArguments `
    -WorkingDirectory $RepoRoot
$suiteTrigger = New-ScheduledTaskTrigger -Once -At $suiteAt
$mergeTrigger = New-ScheduledTaskTrigger -Once -At $mergeAt
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited
$suiteSettingsParameters = @{
    MultipleInstances = "IgnoreNew"
    ExecutionTimeLimit = (New-TimeSpan -Hours 8)
    WakeToRun = $true
    DisallowDemandStart = $true
    AllowStartIfOnBatteries = $true
    DontStopIfGoingOnBatteries = $true
}
$mergeSettingsParameters = @{
    MultipleInstances = "IgnoreNew"
    ExecutionTimeLimit = (New-TimeSpan -Hours 4)
    WakeToRun = $true
    DisallowDemandStart = $true
    AllowStartIfOnBatteries = $true
    DontStopIfGoingOnBatteries = $true
}
if ($StageDisabled) {
    # The task definitions enter Scheduler disabled in their first and only
    # registration mutation. A process kill after either Register call cannot
    # leave a runnable task without final preparation authorization.
    $suiteSettingsParameters.Disable = $true
    $mergeSettingsParameters.Disable = $true
}
$suiteSettings = New-ScheduledTaskSettingsSet @suiteSettingsParameters
$mergeSettings = New-ScheduledTaskSettingsSet @mergeSettingsParameters
$expectedRegisteredState = if ($StageDisabled) { "Disabled" } else { "Ready" }
$expectedRegisteredEnabled = -not [bool]$StageDisabled

# This immutable journal is durably created before the first Scheduler
# mutation. If the registrar process is interrupted at any later instruction,
# the closer can still validate and disable only these exact task definitions.
$intent = [ordered]@{
    schema = $script:WeatherIntegrationAttemptRegistrationIntentSchema
    status = "PREPARED"
    binding_contract = $script:WeatherIntegrationAttemptTaskBindingContract
    attempt_id = [string]$manifest.attempt_id
    intent_path = $registrationIntentPath
    manifest_path = $contract.ManifestPath
    manifest_sha256 = $contract.ManifestSha256
    prepared_at_local = (Get-Date).ToString("o")
    principal = [ordered]@{
        user_id = $env:USERNAME
        logon_type = "S4U"
        run_level = "Limited"
        id = "Author"
        display_name = ""
        group_id = ""
        process_token_sid_type = "Default"
        required_privileges = @()
    }
    suite = $suiteBinding
    merge = $mergeBinding
    safety = [ordered]@{
        authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
        credential_value_access_authorized = $false
        live_exchange_mutation_authorized = $false
    }
}
Write-WeatherIntegrationImmutableJson -Path $registrationIntentPath -Payload $intent
$intentContract = Assert-WeatherIntegrationRegistrationIntent -AttemptContract $contract
$intentSha256 = [string]$intentContract.IntentSha256

$status = "FAIL"
$failure = $null
$mergeRegistered = $false
$suiteRegistered = $false
$schedulerBoundaryCheckedAt = $null
try {
    # Validation and intent journaling above can consume the caller's reserve.
    # Recheck at the actual external-mutation boundary, before either exact
    # Scheduler task can exist.
    $schedulerBoundaryCheckedAt = Get-Date
    if ($suiteAt -lt $schedulerBoundaryCheckedAt.AddMinutes($MinimumSuiteLeadMinutes)) {
        throw "Suite trigger no longer retains the required $MinimumSuiteLeadMinutes-minute lead at the Scheduler registration boundary."
    }
    # Register the fail-closed consumer first. If suite registration then fails,
    # the merge task has no PASS receipt to consume and cannot mutate the tree.
    Register-ScheduledTask `
        -TaskName $mergeTaskName `
        -Action $mergeAction `
        -Trigger $mergeTrigger `
        -Principal $principal `
        -Settings $mergeSettings `
        -Description ([string]$mergeBinding.description) | Out-Null
    $mergeRegistered = $true
    $registeredMerge = Assert-WeatherIntegrationScheduledTaskBinding `
        -AttemptContract $contract `
        -Role "merge" `
        -BindingEvidence $intentContract.Intent
    if ([string]$registeredMerge.Task.State -ne $expectedRegisteredState -or
        [bool]$registeredMerge.Task.Settings.Enabled -ne $expectedRegisteredEnabled) {
        throw "Merge task registration did not produce the exact staged state $expectedRegisteredState."
    }

    Register-ScheduledTask `
        -TaskName $suiteTaskName `
        -Action $suiteAction `
        -Trigger $suiteTrigger `
        -Principal $principal `
        -Settings $suiteSettings `
        -Description ([string]$suiteBinding.description) | Out-Null
    $suiteRegistered = $true
    $registeredSuite = Assert-WeatherIntegrationScheduledTaskBinding `
        -AttemptContract $contract `
        -Role "suite" `
        -BindingEvidence $intentContract.Intent
    if ([string]$registeredSuite.Task.State -ne $expectedRegisteredState -or
        [bool]$registeredSuite.Task.Settings.Enabled -ne $expectedRegisteredEnabled) {
        throw "Suite task registration did not produce the exact staged state $expectedRegisteredState."
    }
    $status = "PASS"
}
catch {
    $failure = $_.Exception.Message
    Write-Error $failure -ErrorAction Continue
}
finally {
    $receipt = [ordered]@{
        schema = $script:WeatherIntegrationAttemptRegistrationReceiptSchema
        status = $status
        binding_contract = $script:WeatherIntegrationAttemptTaskBindingContract
        attempt_id = [string]$manifest.attempt_id
        manifest_path = $contract.ManifestPath
        manifest_sha256 = $contract.ManifestSha256
        registration_intent_path = $registrationIntentPath
        registration_intent_sha256 = $intentSha256
        registered_at_local = (Get-Date).ToString("o")
        scheduler_boundary_checked_at_local = $schedulerBoundaryCheckedAt.ToString("o")
        minimum_suite_lead_minutes = $MinimumSuiteLeadMinutes
        staged_disabled = [bool]$StageDisabled
        principal = [ordered]@{
            user_id = $env:USERNAME
            logon_type = "S4U"
            run_level = "Limited"
            id = "Author"
            display_name = ""
            group_id = ""
            process_token_sid_type = "Default"
            required_privileges = @()
        }
        suite = [ordered]@{
            task_name = $suiteTaskName
            trigger_at_local = $suiteAt.ToString("o")
            registered = $suiteRegistered
            task_path = [string]$suiteBinding.task_path
            description = [string]$suiteBinding.description
            action_id = [string]$suiteBinding.action_id
            executable = [string]$suiteBinding.executable
            arguments = [string]$suiteBinding.arguments
            working_directory = [string]$suiteBinding.working_directory
            script_sha256 = [string]$suiteBinding.script_sha256
            trigger = $suiteBinding.trigger
            settings = $suiteBinding.settings
        }
        merge = [ordered]@{
            task_name = $mergeTaskName
            trigger_at_local = $mergeAt.ToString("o")
            registered = $mergeRegistered
            task_path = [string]$mergeBinding.task_path
            description = [string]$mergeBinding.description
            action_id = [string]$mergeBinding.action_id
            executable = [string]$mergeBinding.executable
            arguments = [string]$mergeBinding.arguments
            working_directory = [string]$mergeBinding.working_directory
            script_sha256 = [string]$mergeBinding.script_sha256
            trigger = $mergeBinding.trigger
            settings = $mergeBinding.settings
        }
        downstream_tasks_created = $false
        failure = $failure
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    Write-WeatherIntegrationImmutableJson -Path $registrationReceiptPath -Payload $receipt
}

if ($status -ne "PASS") {
    Write-Host "Integration attempt registration failed. Existing task state was not replaced; use a new attempt id after review."
    exit 1
}

$registrationContract = Assert-WeatherIntegrationRegistrationReceipt `
    -AttemptContract $contract `
    -RequirePass
foreach ($role in @("suite", "merge")) {
    $registeredTask = Assert-WeatherIntegrationScheduledTaskBinding `
        -AttemptContract $contract `
        -Role $role `
        -BindingEvidence $registrationContract.Intent
    if ([string]$registeredTask.Task.State -ne $expectedRegisteredState -or
        [bool]$registeredTask.Task.Settings.Enabled -ne $expectedRegisteredEnabled) {
        throw "$role task changed state before registration verification completed."
    }
}

Write-Host "Registered immutable attempt $($manifest.attempt_id): $suiteTaskName then $mergeTaskName (staged_disabled=$([bool]$StageDisabled))"
Write-Host "No task was started and no downstream task was created."
exit 0
}
finally {
    Exit-WeatherIntegrationControlMutex -Mutex $terminalMutex
}
