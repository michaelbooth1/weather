# Safely abandon an attempt whose wrapper crashed or whose operator has chosen
# not to continue. Exact attempt tasks are disabled first; only then is an
# immutable FAIL receipt emitted so a replacement attempt can reference it.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$ReviewReference
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

if ([string]::IsNullOrWhiteSpace($Reason) -or [string]::IsNullOrWhiteSpace($ReviewReference)) {
    throw "Reason and ReviewReference are required to close an immutable attempt."
}
$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
$manifest = $contract.Manifest
$closurePath = [string]$manifest.evidence.closure_receipt
if (Test-Path -LiteralPath $closurePath) {
    throw "Immutable closure receipt already exists and will not be replaced: $closurePath"
}

$mergeReceiptPath = [string]$manifest.evidence.merge_receipt
if (Test-Path -LiteralPath $mergeReceiptPath -PathType Leaf) {
    $mergeReceipt = Read-WeatherIntegrationSharedJson -Path $mergeReceiptPath
    if ([string]$mergeReceipt.status -eq "PASS") {
        throw "A successfully merged attempt cannot be abandoned."
    }
}

$repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
$registrationReceiptPath = [string]$manifest.evidence.registration_receipt
$registrationReceipt = $null
if (Test-Path -LiteralPath $registrationReceiptPath -PathType Leaf) {
    $registrationReceipt = Read-WeatherIntegrationSharedJson -Path $registrationReceiptPath
    if ([string]$registrationReceipt.schema -ne $script:WeatherIntegrationAttemptRegistrationReceiptSchema -or
        [string]$registrationReceipt.attempt_id -ne [string]$manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$registrationReceipt.manifest_path) -Right $contract.ManifestPath) -or
        [string]$registrationReceipt.manifest_sha256 -ne [string]$contract.ManifestSha256) {
        throw "Registration receipt does not bind this exact attempt."
    }
}
$taskSpecs = @(
    [pscustomobject]@{
        name = [string]$manifest.schedule.suite_task_name
        role = "suite"
    },
    [pscustomobject]@{
        name = [string]$manifest.schedule.merge_task_name
        role = "merge"
    }
)

$taskEvidence = New-Object System.Collections.Generic.List[object]
foreach ($spec in $taskSpecs) {
    $task = Get-ScheduledTask -TaskName $spec.name -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        $taskEvidence.Add([ordered]@{ task_name = $spec.name; exists = $false; disabled = $false })
        continue
    }
    if ([string]$task.State -eq "Running") {
        throw "Attempt task is still running and may not be closed: $($spec.name)"
    }
    if ($null -eq $registrationReceipt) {
        throw "Refusing to disable an existing task without its immutable registration receipt: $($spec.name)"
    }
    $registeredActionProperty = $registrationReceipt.PSObject.Properties[[string]$spec.role]
    $registeredAction = if ($null -eq $registeredActionProperty) { $null } else { $registeredActionProperty.Value }
    if ($null -eq $registeredAction -or
        -not [bool]$registeredAction.registered -or
        [string]$registeredAction.task_name -ne [string]$spec.name) {
        throw "Registration receipt does not prove this exact task was created: $($spec.name)"
    }
    $actions = @($task.Actions)
    if ($actions.Count -ne 1 -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].Execute) -Right ([string]$registeredAction.executable)) -or
        [string]$actions[0].Arguments -ne [string]$registeredAction.arguments -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].WorkingDirectory) -Right ([string]$registeredAction.working_directory)) -or
        [string]$task.Principal.UserId -ne [string]$registrationReceipt.principal.user_id -or
        [string]$task.Principal.LogonType -ne "S4U" -or
        [string]$task.Principal.RunLevel -ne "Limited") {
        throw "Refusing to disable task whose action is not exactly bound to this attempt: $($spec.name)"
    }
    Disable-ScheduledTask -TaskName $spec.name -ErrorAction Stop | Out-Null
    $disabledTask = Get-ScheduledTask -TaskName $spec.name -ErrorAction Stop
    if ([string]$disabledTask.State -ne "Disabled") {
        throw "Attempt task did not enter Disabled state: $($spec.name)"
    }
    $info = Get-ScheduledTaskInfo -TaskName $spec.name -ErrorAction SilentlyContinue
    $taskEvidence.Add([ordered]@{
        task_name = $spec.name
        exists = $true
        disabled = $true
        last_run_time = if ($null -eq $info) { $null } else { ([datetime]$info.LastRunTime).ToString("o") }
        last_task_result = if ($null -eq $info) { $null } else { [int]$info.LastTaskResult }
    })
}

$existingEvidence = New-Object System.Collections.Generic.List[object]
foreach ($path in @(
    [string]$manifest.evidence.registration_receipt,
    [string]$manifest.evidence.preflight_log,
    [string]$manifest.evidence.full_suite_log,
    [string]$manifest.evidence.suite_receipt,
    [string]$manifest.evidence.quiet_merge_report,
    [string]$manifest.evidence.merge_receipt
)) {
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $existingEvidence.Add([ordered]@{
            path = Resolve-WeatherIntegrationPath -Path $path
            sha256 = Get-WeatherIntegrationFileSha256 -Path $path
        })
    }
}

$receipt = [ordered]@{
    schema = $script:WeatherIntegrationAttemptClosureReceiptSchema
    status = "FAIL"
    classification = "ABANDONED"
    attempt_id = [string]$manifest.attempt_id
    manifest_path = $contract.ManifestPath
    manifest_sha256 = $contract.ManifestSha256
    expected_tip = [string]$manifest.expected_tip
    closed_at_local = (Get-Date).ToString("o")
    reason = $Reason
    review_reference = $ReviewReference
    tasks = @($taskEvidence | ForEach-Object { $_ })
    preserved_evidence = @($existingEvidence | ForEach-Object { $_ })
    credential_value_read = $false
    live_exchange_mutation_attempted = $false
}
Write-WeatherIntegrationImmutableJson -Path $closurePath -Payload $receipt

Write-Host "Closed integration attempt $($manifest.attempt_id). Exact tasks are disabled and evidence is frozen."
Write-Host "A replacement attempt may bind this FAIL receipt: $closurePath"
