# Execute one immutable integration attempt: deterministic ratchets first, then
# the exact full suite. The bounded runner owns the heavy-work lease and every
# pytest child tree; this wrapper owns the bounded runner child tree and writes
# one hash-bound, immutable receipt.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedManifestSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

function Get-WeatherAttemptLogVerdict {
    param([Parameter(Mandatory = $true)][string]$Path)

    $lines = @(Read-WeatherIntegrationSharedText -Path $Path -split "`r?`n" |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($lines.Count -eq 0) {
        throw "Attempt log is empty: $Path"
    }
    return [string]$lines[-1]
}

function Invoke-WeatherAttemptSuitePhase {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Phase,
        [Parameter(Mandatory = $true)]
        [string]$LogPath,
        [switch]$IntegrationPreflight
    )

    $tokens = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $boundedSuiteScript,
        "-RepoRoot", [string]$manifest.repo_root,
        "-WorktreeRoot", [string]$manifest.worktree_root,
        "-ExpectedTip", [string]$manifest.expected_tip,
        "-BranchRef", [string]$manifest.branch_ref,
        "-LogPath", $LogPath
    )
    if (-not [string]::IsNullOrWhiteSpace([string]$manifest.suite.additional_python_path)) {
        $tokens += @("-AdditionalPythonPath", [string]$manifest.suite.additional_python_path)
    }
    if ([bool]$manifest.suite.require_live_sdk_contract) {
        $tokens += "-RequireLiveSdkContract"
    }
    if ($IntegrationPreflight) {
        $tokens += "-IntegrationPreflight"
    }

    $argumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
    $job = $null
    $process = $null
    try {
        Write-Host "$Phase starting for attempt $($manifest.attempt_id)"
        $job = New-WeatherKillOnCloseJob
        $process = Start-WeatherProcessInJob `
            -Job $job `
            -FilePath $powerShellExecutable `
            -ArgumentString $argumentString `
            -WorkingDirectory ([string]$manifest.repo_root)
        while (-not $process.HasExited) {
            if ((Get-Date) -ge $hardStop) {
                throw "$Phase reached the 09:00 hard teardown boundary"
            }
            Start-Sleep -Seconds 2
            $process.Refresh()
        }
        $process.WaitForExit()
        return [int]$process.ExitCode
    }
    finally {
        if ($job) { $job.Dispose() }
        if ($process) { $process.Dispose() }
    }
}

$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract
$manifest = $contract.Manifest
$suiteReceiptPath = [string]$manifest.evidence.suite_receipt
$preflightLogPath = [string]$manifest.evidence.preflight_log
$fullSuiteLogPath = [string]$manifest.evidence.full_suite_log

foreach ($freshPath in @($suiteReceiptPath, $preflightLogPath, $fullSuiteLogPath)) {
    if (Test-Path -LiteralPath $freshPath) {
        throw "Attempt suite evidence already exists and will not be appended or replaced: $freshPath"
    }
}

$repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
$boundedSuiteScript = Join-Path $repoRoot "scripts\ops\bounded_worktree_test_suite.ps1"
$tokenContractScript = Join-Path $repoRoot "scripts\ops\training_window_contract.ps1"
$jobScript = Join-Path $repoRoot "scripts\ops\windows_kill_on_close_job.ps1"
foreach ($requiredScript in @($boundedSuiteScript, $tokenContractScript, $jobScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "Required integration-attempt suite script is missing: $requiredScript"
    }
}
. $tokenContractScript
. $jobScript

$powerShellExecutable = Join-Path $PSHOME "powershell.exe"
if (-not (Test-Path -LiteralPath $powerShellExecutable -PathType Leaf)) {
    throw "Windows PowerShell executable is missing: $powerShellExecutable"
}

$localNow = Get-Date
$localMinute = ($localNow.Hour * 60) + $localNow.Minute
if ($localMinute -lt 30 -or $localMinute -ge (9 * 60)) {
    throw "Integration-attempt suite must start inside the 00:30-09:00 heavy-work window."
}
$hardStop = $localNow.Date.AddHours(9)
$startedAt = $localNow.ToString("o")
$status = "FAIL"
$failure = $null
$preflightExitCode = $null
$fullSuiteExitCode = $null
$preflightVerdict = $null
$fullSuiteVerdict = $null

try {
    $preflightExitCode = Invoke-WeatherAttemptSuitePhase `
        -Phase "integration preflight" `
        -LogPath $preflightLogPath `
        -IntegrationPreflight
    if ($preflightExitCode -ne 0) {
        throw "Integration preflight failed with exit code $preflightExitCode; full suite was not started."
    }
    $preflightVerdict = Get-WeatherAttemptLogVerdict -Path $preflightLogPath
    if ($preflightVerdict -notlike "*VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge is not authorized") {
        throw "Integration preflight log is missing its exact PASS verdict."
    }

    $fullSuiteExitCode = Invoke-WeatherAttemptSuitePhase `
        -Phase "full suite" `
        -LogPath $fullSuiteLogPath
    if ($fullSuiteExitCode -ne 0) {
        throw "Full suite failed with exit code $fullSuiteExitCode."
    }
    $fullSuiteVerdict = Get-WeatherAttemptLogVerdict -Path $fullSuiteLogPath
    if ($fullSuiteVerdict -notmatch 'VERDICT: ALL CHUNKS PASSED \([0-9]+/[0-9]+\); exact tip eligible for separate reviewed merge$') {
        throw "Full suite log is missing its exact PASS verdict."
    }
    $status = "PASS"
}
catch {
    $failure = $_.Exception.Message
    Write-Error $failure -ErrorAction Continue
}
finally {
    $preflightLogRecord = $null
    if (Test-Path -LiteralPath $preflightLogPath -PathType Leaf) {
        if ($null -eq $preflightVerdict) {
            try { $preflightVerdict = Get-WeatherAttemptLogVerdict -Path $preflightLogPath } catch { }
        }
        $preflightLogRecord = [ordered]@{
            path = $preflightLogPath
            sha256 = Get-WeatherIntegrationFileSha256 -Path $preflightLogPath
            exit_code = $preflightExitCode
            verdict = $preflightVerdict
        }
    }

    $fullSuiteLogRecord = $null
    if (Test-Path -LiteralPath $fullSuiteLogPath -PathType Leaf) {
        if ($null -eq $fullSuiteVerdict) {
            try { $fullSuiteVerdict = Get-WeatherAttemptLogVerdict -Path $fullSuiteLogPath } catch { }
        }
        $fullSuiteLogRecord = [ordered]@{
            path = $fullSuiteLogPath
            sha256 = Get-WeatherIntegrationFileSha256 -Path $fullSuiteLogPath
            exit_code = $fullSuiteExitCode
            verdict = $fullSuiteVerdict
        }
    }

    $receipt = [ordered]@{
        schema = $script:WeatherIntegrationAttemptSuiteReceiptSchema
        status = $status
        attempt_id = [string]$manifest.attempt_id
        manifest_path = $contract.ManifestPath
        manifest_sha256 = $contract.ManifestSha256
        branch_ref = [string]$manifest.branch_ref
        expected_tip = [string]$manifest.expected_tip
        worktree_root = [string]$manifest.worktree_root
        started_at_local = $startedAt
        completed_at_local = (Get-Date).ToString("o")
        failure = $failure
        scripts = [ordered]@{
            bounded_suite = [ordered]@{
                path = $boundedSuiteScript
                sha256 = Get-WeatherIntegrationFileSha256 -Path $boundedSuiteScript
            }
            integration_suite = [ordered]@{
                path = $PSCommandPath
                sha256 = Get-WeatherIntegrationFileSha256 -Path $PSCommandPath
            }
        }
        logs = [ordered]@{
            preflight = $preflightLogRecord
            full_suite = $fullSuiteLogRecord
        }
        full_suite_started = ($null -ne $fullSuiteExitCode -or (Test-Path -LiteralPath $fullSuiteLogPath -PathType Leaf))
        credential_value_read = $false
        live_exchange_mutation_attempted = $false
    }
    Write-WeatherIntegrationImmutableJson -Path $suiteReceiptPath -Payload $receipt
}

if ($status -ne "PASS") {
    Write-Host "Integration attempt $($manifest.attempt_id) failed. Evidence is frozen; repair by creating a new attempt bound to this FAIL receipt."
    exit 1
}

Write-Host "Integration attempt $($manifest.attempt_id) suite passed. Merge remains separately gated."
exit 0
