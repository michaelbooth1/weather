# Retire the exact Scheduled Task pair for a successfully integrated historical
# attempt.  This is distinct from FAIL closure: the PASS merge receipt remains
# the terminal integration authority and is never replaced or reclassified.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedMergeReceiptSha256,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [string]$Confirmation = "",
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

function Assert-WeatherIntegrationRetirementTask {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)]
        [ValidateSet("suite", "merge")][string]$Role,
        [Parameter(Mandatory = $true)][datetime]$ExpectedStartedAt
    )

    $binding = Assert-WeatherIntegrationAttemptTaskBinding `
        -AttemptContract $AttemptContract `
        -Role $Role `
        -IncludeTaskInfo
    if ([string]$binding.Task.State -notin @("Ready", "Disabled")) {
        throw "Successful-attempt retirement requires an exact terminal task: role=$Role state=$($binding.Task.State)"
    }
    if ([int]$binding.Info.LastTaskResult -ne 0) {
        throw ("Successful-attempt retirement requires Scheduler result 0 for " +
            "$Role; got 0x{0:X}." -f [int]$binding.Info.LastTaskResult)
    }
    $lastRunTime = [datetime]$binding.Info.LastRunTime
    if ($lastRunTime -eq [datetime]::MinValue -or
        [math]::Abs(($lastRunTime - $ExpectedStartedAt).TotalMinutes) -gt 5) {
        throw "Successful-attempt retirement cannot correlate the $Role task run to its immutable receipt."
    }
    $nextRunTime = $binding.Info.NextRunTime
    if ($null -ne $nextRunTime -and [datetime]$nextRunTime -gt (Get-Date)) {
        throw "Successful-attempt retirement refuses a task with a future trigger: $Role"
    }
    return [pscustomobject]@{
        Role = $Role
        Name = [string]$binding.Task.TaskName
        State = [string]$binding.Task.State
        Enabled = [bool]$binding.Task.Settings.Enabled
        AllowDemandStart = [bool]$binding.Task.Settings.AllowDemandStart
        LastRunTime = $lastRunTime
        LastTaskResult = [int]$binding.Info.LastTaskResult
    }
}

if ([string]::IsNullOrWhiteSpace($ReviewReference)) {
    throw "ReviewReference is required for successful-attempt task retirement."
}
if (-not $PreflightOnly.IsPresent -and
    $Confirmation -cne $script:WeatherIntegrationTaskRetirementConfirmation) {
    throw ("Task retirement requires the exact confirmation literal: " +
        $script:WeatherIntegrationTaskRetirementConfirmation)
}

$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
$manifest = $contract.Manifest
$mergeContract = Assert-WeatherIntegrationMergeReceipt `
    -AttemptContract $contract `
    -ExpectedReceiptSha256 $ExpectedMergeReceiptSha256
$suiteContract = Assert-WeatherIntegrationSuiteReceipt `
    -AttemptContract $contract
$retirementPath = Join-Path $contract.AttemptRoot "task-retirement-receipt.json"
if (Test-Path -LiteralPath $retirementPath) {
    throw "Immutable task-retirement receipt already exists and will not be replaced: $retirementPath"
}

$suiteStartedAt = $suiteContract.StartedAtLocal.LocalDateTime
$mergeStartedAt = (
    ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$mergeContract.Receipt.started_at_local) `
        -Label "merge receipt started_at_local"
).LocalDateTime
$preflightRows = @(
    Assert-WeatherIntegrationRetirementTask `
        -AttemptContract $contract -Role "suite" `
        -ExpectedStartedAt $suiteStartedAt
    Assert-WeatherIntegrationRetirementTask `
        -AttemptContract $contract -Role "merge" `
        -ExpectedStartedAt $mergeStartedAt
)

if ($PreflightOnly.IsPresent) {
    [pscustomobject]@{
        status = "PASS"
        mutation = $false
        attempt_id = [string]$manifest.attempt_id
        manifest_sha256 = [string]$contract.ManifestSha256
        merge_receipt_sha256 = [string]$mergeContract.ReceiptSha256
        retirement_receipt_path = Resolve-WeatherIntegrationPath `
            -Path $retirementPath
        tasks = @($preflightRows | ForEach-Object {
            [ordered]@{
                role = [string]$_.Role
                task_name = [string]$_.Name
                state = [string]$_.State
                enabled = [bool]$_.Enabled
                allow_demand_start = [bool]$_.AllowDemandStart
                last_run_time = ([datetime]$_.LastRunTime).ToString("o")
                last_task_result = [int]$_.LastTaskResult
            }
        })
        safety_authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
    } | ConvertTo-Json -Depth 6
    exit 0
}

$repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
$terminalMutex = Enter-WeatherIntegrationControlMutex `
    -RepositoryRoot $repoRoot `
    -LockLeaf "integration_attempt_terminal.lock" `
    -Owner "retire_integration_attempt_tasks:$($manifest.attempt_id)"
if ($null -eq $terminalMutex) {
    throw "Another integration-attempt terminal transaction owns the control mutex."
}
try {
    if (Test-Path -LiteralPath $retirementPath) {
        throw "Immutable task-retirement receipt appeared during mutex acquisition."
    }

    # Revalidate all load-bearing evidence and task state under the terminal
    # mutex.  The preflight above is diagnostic only and grants no mutation
    # authority across this boundary.
    $mergeContract = Assert-WeatherIntegrationMergeReceipt `
        -AttemptContract $contract `
        -ExpectedReceiptSha256 $ExpectedMergeReceiptSha256
    $suiteContract = Assert-WeatherIntegrationSuiteReceipt `
        -AttemptContract $contract
    $preDisableRows = @(
        Assert-WeatherIntegrationRetirementTask `
            -AttemptContract $contract -Role "suite" `
            -ExpectedStartedAt $suiteContract.StartedAtLocal.LocalDateTime
        Assert-WeatherIntegrationRetirementTask `
            -AttemptContract $contract -Role "merge" `
            -ExpectedStartedAt $mergeStartedAt
    )

    $disableEvidence = @(Disable-WeatherIntegrationAttemptTasks `
        -AttemptContract $contract)
    foreach ($role in @("suite", "merge")) {
        $taskName = if ($role -eq "suite") {
            [string]$manifest.schedule.suite_task_name
        }
        else { [string]$manifest.schedule.merge_task_name }
        $row = @($disableEvidence | Where-Object {
            [string]$_.task_name -ceq $taskName
        })
        if ($row.Count -ne 1 -or -not [bool]$row[0].exists -or
            -not [bool]$row[0].disabled -or
            [int]$row[0].last_task_result -ne 0) {
            throw "Task retirement lacks exact successful post-disable evidence: $taskName"
        }
    }

    $receipt = [ordered]@{
        schema = $script:WeatherIntegrationTaskRetirementReceiptSchema
        status = "PASS"
        classification = "SUCCESSFUL_ATTEMPT_TASKS_RETIRED"
        attempt_id = [string]$manifest.attempt_id
        manifest_path = [string]$contract.ManifestPath
        manifest_sha256 = [string]$contract.ManifestSha256
        merge_receipt_path = [string]$mergeContract.ReceiptPath
        merge_receipt_sha256 = [string]$mergeContract.ReceiptSha256
        retired_at_local = (Get-Date).ToString("o")
        review_reference = $ReviewReference
        confirmation = $Confirmation
        pre_disable = @($preDisableRows | ForEach-Object {
            [ordered]@{
                role = [string]$_.Role
                task_name = [string]$_.Name
                state = [string]$_.State
                enabled = [bool]$_.Enabled
                allow_demand_start = [bool]$_.AllowDemandStart
                last_run_time = ([datetime]$_.LastRunTime).ToString("o")
                last_task_result = [int]$_.LastTaskResult
            }
        })
        post_disable = @($disableEvidence | ForEach-Object { $_ })
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    Write-WeatherIntegrationImmutableJson `
        -Path $retirementPath -Payload $receipt
    foreach ($role in @("suite", "merge")) {
        $taskName = if ($role -eq "suite") {
            [string]$manifest.schedule.suite_task_name
        }
        else { [string]$manifest.schedule.merge_task_name }
        $task = @(Get-ScheduledTask `
            -TaskName $taskName -TaskPath "\" -ErrorAction Stop)
        if ($task.Count -ne 1) {
            throw "Task-retirement readback lost the exact $role task."
        }
        Assert-WeatherIntegrationTaskRetirementReceipt `
            -AttemptContract $contract -Task $task[0] -Role $role | Out-Null
    }
}
finally {
    Exit-WeatherIntegrationControlMutex -Mutex $terminalMutex
}

Write-Host (
    "Retired exact successful-attempt tasks for $($manifest.attempt_id); " +
    "immutable receipt: $retirementPath"
)
