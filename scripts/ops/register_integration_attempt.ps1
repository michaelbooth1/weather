# Register the two one-shot tasks for an immutable integration attempt. This
# script does not start either task and does not create downstream work.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedManifestSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

$RepoRoot = Resolve-WeatherIntegrationPath -Path $RepoRoot
$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract
Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase "attempt registration" | Out-Null
$manifest = $contract.Manifest
if (-not (Test-WeatherIntegrationPathEqual -Left $RepoRoot -Right ([string]$manifest.repo_root))) {
    throw "Registrar RepoRoot does not match the immutable attempt manifest."
}

$registrationReceiptPath = [string]$manifest.evidence.registration_receipt
if (Test-Path -LiteralPath $registrationReceiptPath) {
    throw "Immutable registration receipt already exists and will not be replaced: $registrationReceiptPath"
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

$suiteAt = [datetime]::Parse([string]$manifest.schedule.suite_at_local)
$mergeAt = [datetime]::Parse([string]$manifest.schedule.merge_at_local)
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
foreach ($taskName in @($suiteTaskName, $mergeTaskName)) {
    if ($taskName -notmatch '^WeatherIntegration(?:Suite|Merge)_[A-Za-z0-9][A-Za-z0-9._-]{0,47}$') {
        throw "Manifest task name is unsafe: $taskName"
    }
    if ($null -ne (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
        throw "Attempt task already exists and will not be replaced: $taskName"
    }
}

$suiteTokens = @(
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-File", $suiteScript,
    "-ManifestPath", $contract.ManifestPath,
    "-ExpectedManifestSha256", $contract.ManifestSha256
)
$mergeTokens = @(
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-File", $mergeScript,
    "-ManifestPath", $contract.ManifestPath,
    "-ExpectedManifestSha256", $contract.ManifestSha256
)
$suiteArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $suiteTokens
$mergeArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $mergeTokens

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
$suiteSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$mergeSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$status = "FAIL"
$failure = $null
$mergeRegistered = $false
$suiteRegistered = $false
try {
    # Register the fail-closed consumer first. If suite registration then fails,
    # the merge task has no PASS receipt to consume and cannot mutate the tree.
    Register-ScheduledTask `
        -TaskName $mergeTaskName `
        -Action $mergeAction `
        -Trigger $mergeTrigger `
        -Principal $principal `
        -Settings $mergeSettings `
        -Description "Immutable integration attempt $($manifest.attempt_id): guarded merge" | Out-Null
    $mergeRegistered = $null -ne (Get-ScheduledTask -TaskName $mergeTaskName -ErrorAction SilentlyContinue)
    if (-not $mergeRegistered) { throw "Merge task registration did not take effect." }

    Register-ScheduledTask `
        -TaskName $suiteTaskName `
        -Action $suiteAction `
        -Trigger $suiteTrigger `
        -Principal $principal `
        -Settings $suiteSettings `
        -Description "Immutable integration attempt $($manifest.attempt_id): preflight and full suite" | Out-Null
    $suiteRegistered = $null -ne (Get-ScheduledTask -TaskName $suiteTaskName -ErrorAction SilentlyContinue)
    if (-not $suiteRegistered) { throw "Suite task registration did not take effect." }
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
        attempt_id = [string]$manifest.attempt_id
        manifest_path = $contract.ManifestPath
        manifest_sha256 = $contract.ManifestSha256
        registered_at_local = (Get-Date).ToString("o")
        principal = [ordered]@{
            user_id = $env:USERNAME
            logon_type = "S4U"
            run_level = "Limited"
        }
        suite = [ordered]@{
            task_name = $suiteTaskName
            trigger_at_local = $suiteAt.ToString("o")
            registered = $suiteRegistered
            executable = $powerShellExecutable
            arguments = $suiteArguments
            working_directory = $RepoRoot
            script_sha256 = Get-WeatherIntegrationFileSha256 -Path $suiteScript
        }
        merge = [ordered]@{
            task_name = $mergeTaskName
            trigger_at_local = $mergeAt.ToString("o")
            registered = $mergeRegistered
            executable = $powerShellExecutable
            arguments = $mergeArguments
            working_directory = $RepoRoot
            script_sha256 = Get-WeatherIntegrationFileSha256 -Path $mergeScript
        }
        downstream_tasks_created = $false
        failure = $failure
        credential_value_read = $false
        live_exchange_mutation_attempted = $false
    }
    Write-WeatherIntegrationImmutableJson -Path $registrationReceiptPath -Payload $receipt
}

if ($status -ne "PASS") {
    Write-Host "Integration attempt registration failed. Existing task state was not replaced; use a new attempt id after review."
    exit 1
}

Write-Host "Registered immutable attempt $($manifest.attempt_id): $suiteTaskName then $mergeTaskName"
Write-Host "No task was started and no downstream task was created."
exit 0
