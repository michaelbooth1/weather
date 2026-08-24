# Disable one of the two exact expired bootstrap tasks that predate immutable
# integration-attempt manifests.  The caller must bind the complete exported
# Task Scheduler XML and terminal run result; no name-only cleanup is allowed.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "WeatherIntegrationRecoveryBootstrapSuiteFixed0822",
        "WeatherIntegrationRecoveryBootstrapMergeFixed0822"
    )]
    [string]$TaskName,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedTaskXmlSha256,
    [Parameter(Mandatory = $true)][datetime]$ExpectedLastRunTime,
    [Parameter(Mandatory = $true)][int]$ExpectedLastTaskResult,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [string]$Confirmation = "",
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

function Assert-WeatherLegacyBootstrapTask {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedXmlSha256,
        [Parameter(Mandatory = $true)][datetime]$ExpectedRunTime,
        [Parameter(Mandatory = $true)][int]$ExpectedResult
    )

    $snapshot = @(Get-WeatherIntegrationScheduledTaskSnapshot)
    $matches = @($snapshot | Where-Object {
        [string]$_.TaskName -ceq $Name -and [string]$_.TaskPath -ceq "\"
    })
    if ($matches.Count -ne 1) {
        throw "Legacy bootstrap task must resolve exactly once at the root path: $Name"
    }
    $task = $matches[0]
    if ([string]$task.State -notin @("Ready", "Disabled")) {
        throw "Legacy bootstrap task is not terminal and may not be retired: $Name state=$($task.State)"
    }
    $xml = Export-ScheduledTask -TaskName $Name -TaskPath "\" -ErrorAction Stop
    $xmlSha256 = Get-WeatherLegacyBootstrapTaskXmlSha256 -Xml $xml
    if ($xmlSha256 -ne $ExpectedXmlSha256.ToLowerInvariant()) {
        throw "Legacy bootstrap task XML hash mismatch: $Name"
    }
    $info = Get-ScheduledTaskInfo -TaskName $Name -TaskPath "\" -ErrorAction Stop
    $lastRunTime = [datetime]$info.LastRunTime
    if ($lastRunTime -ne $ExpectedRunTime -or
        [int]$info.LastTaskResult -ne $ExpectedResult) {
        throw "Legacy bootstrap task terminal run evidence changed: $Name"
    }
    if ($null -ne $info.NextRunTime -and [datetime]$info.NextRunTime -gt (Get-Date)) {
        throw "Legacy bootstrap task still has a future run and may not be retired: $Name"
    }
    $triggers = @($task.Triggers)
    if ($triggers.Count -ne 1) {
        throw "Legacy bootstrap task must retain one exact expired trigger: $Name"
    }
    try { $triggerAt = [DateTimeOffset]::Parse([string]$triggers[0].StartBoundary) }
    catch { throw "Legacy bootstrap task trigger is unreadable: $Name" }
    if ($triggerAt -ge [DateTimeOffset]::Now) {
        throw "Legacy bootstrap task trigger has not expired: $Name"
    }
    return [pscustomobject]@{
        Task = $task
        Info = $info
        XmlSha256 = $xmlSha256
        TriggerAt = $triggerAt
    }
}

if ([string]::IsNullOrWhiteSpace($ReviewReference)) {
    throw "ReviewReference is required for legacy bootstrap retirement."
}
if (-not $PreflightOnly.IsPresent -and
    $Confirmation -cne $script:WeatherLegacyBootstrapRetirementConfirmation) {
    throw ("Legacy bootstrap retirement requires the exact confirmation literal: " +
        $script:WeatherLegacyBootstrapRetirementConfirmation)
}

$RepoRoot = Resolve-WeatherIntegrationPath -Path $RepoRoot
$ExpectedTaskXmlSha256 = $ExpectedTaskXmlSha256.ToLowerInvariant()
$evidenceRoot = Join-Path $RepoRoot "data\integration_attempts\legacy-task-retirements"
$receiptPath = Join-Path $evidenceRoot "$TaskName.json"
if (Test-Path -LiteralPath $receiptPath) {
    throw "Immutable legacy task-retirement receipt already exists: $receiptPath"
}
$preflight = Assert-WeatherLegacyBootstrapTask `
    -Name $TaskName `
    -ExpectedXmlSha256 $ExpectedTaskXmlSha256 `
    -ExpectedRunTime $ExpectedLastRunTime `
    -ExpectedResult $ExpectedLastTaskResult

if ($PreflightOnly.IsPresent) {
    [pscustomobject]@{
        status = "PASS"
        mutation = $false
        task_name = $TaskName
        state = [string]$preflight.Task.State
        enabled = [bool]$preflight.Task.Settings.Enabled
        allow_demand_start = [bool]$preflight.Task.Settings.AllowDemandStart
        task_xml_sha256 = $preflight.XmlSha256
        trigger_at = $preflight.TriggerAt.ToString("o")
        last_run_time = ([datetime]$preflight.Info.LastRunTime).ToString("o")
        last_task_result = [int]$preflight.Info.LastTaskResult
        retirement_receipt_path = $receiptPath
        safety_authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
    } | ConvertTo-Json -Depth 5
    exit 0
}

$terminalMutex = Enter-WeatherIntegrationControlMutex `
    -RepositoryRoot $RepoRoot `
    -LockLeaf "integration_attempt_terminal.lock" `
    -Owner "retire_legacy_integration_bootstrap_task:$TaskName"
if ($null -eq $terminalMutex) {
    throw "Another integration-attempt terminal transaction owns the control mutex."
}
try {
    if (Test-Path -LiteralPath $receiptPath) {
        throw "Immutable legacy retirement receipt appeared during mutex acquisition."
    }
    $preDisable = Assert-WeatherLegacyBootstrapTask `
        -Name $TaskName `
        -ExpectedXmlSha256 $ExpectedTaskXmlSha256 `
        -ExpectedRunTime $ExpectedLastRunTime `
        -ExpectedResult $ExpectedLastTaskResult
    if ([string]$preDisable.Task.State -ne "Disabled") {
        Disable-ScheduledTask -TaskName $TaskName -TaskPath "\" `
            -ErrorAction Stop | Out-Null
    }
    $postDisable = Assert-WeatherLegacyBootstrapTask `
        -Name $TaskName `
        -ExpectedXmlSha256 $ExpectedTaskXmlSha256 `
        -ExpectedRunTime $ExpectedLastRunTime `
        -ExpectedResult $ExpectedLastTaskResult
    if ([string]$postDisable.Task.State -ne "Disabled" -or
        [bool]$postDisable.Task.Settings.Enabled) {
        throw "Legacy bootstrap task did not remain exactly Disabled: $TaskName"
    }
    if (-not (Test-Path -LiteralPath $evidenceRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $evidenceRoot -Force `
            -ErrorAction Stop | Out-Null
    }
    $receipt = [ordered]@{
        schema = $script:WeatherLegacyBootstrapRetirementSchema
        status = "PASS"
        classification = "EXPIRED_LEGACY_BOOTSTRAP_TASK_RETIRED"
        task_name = $TaskName
        task_xml_sha256 = $postDisable.XmlSha256
        trigger_at = $postDisable.TriggerAt.ToString("o")
        last_run_time = ([datetime]$postDisable.Info.LastRunTime).ToString("o")
        last_task_result = [int]$postDisable.Info.LastTaskResult
        retired_at_local = (Get-Date).ToString("o")
        review_reference = $ReviewReference
        confirmation = $Confirmation
        state = [string]$postDisable.Task.State
        enabled = [bool]$postDisable.Task.Settings.Enabled
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    Write-WeatherIntegrationImmutableJson -Path $receiptPath -Payload $receipt
    Assert-WeatherLegacyBootstrapRetirementReceipt `
        -RepositoryRoot $RepoRoot -Task $postDisable.Task | Out-Null
}
finally {
    Exit-WeatherIntegrationControlMutex -Mutex $terminalMutex
}

Write-Host "Retired exact expired legacy bootstrap task $TaskName; receipt: $receiptPath"
