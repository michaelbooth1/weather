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
. (Join-Path $PSScriptRoot "integration_attempt_preparation_contract.ps1")

function Invoke-WeatherAttemptSuitePhase {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Phase,
        [Parameter(Mandatory = $true)]
        [string]$LogPath,
        [switch]$IntegrationPreflight
    )

    $tokens = @(
        "-RepoRoot", [string]$manifest.repo_root,
        "-WorktreeRoot", [string]$manifest.worktree_root,
        "-ExpectedTip", [string]$manifest.expected_tip,
        "-BranchRef", [string]$manifest.branch_ref,
        "-LogPath", $LogPath,
        "-MaxFilesPerChunk", [string]$manifest.suite.max_files_per_chunk
    )
    $monotonicRemainingSeconds = [math]::Floor(
        [double]$suiteMaxRuntimeSeconds -
        [double]$suiteRuntimeStopwatch.Elapsed.TotalSeconds
    )
    $wallRemainingSeconds = [math]::Floor(
        ($suiteSharedDeadlineUtc - [DateTimeOffset]::UtcNow).TotalSeconds
    )
    $phaseRuntimeSeconds = [int][math]::Min(
        $monotonicRemainingSeconds,
        $wallRemainingSeconds
    )
    if ($phaseRuntimeSeconds -lt
            [int]$script:WeatherIntegrationSuiteMinimumPhaseRuntimeSeconds) {
        throw "$Phase has less than the immutable minimum remaining shared suite runtime."
    }
    $tokens += @("-MaxRuntimeSeconds", [string]$phaseRuntimeSeconds)
    if (-not [string]::IsNullOrWhiteSpace([string]$manifest.suite.additional_python_path)) {
        $tokens += @("-AdditionalPythonPath", [string]$manifest.suite.additional_python_path)
    }
    if ([bool]$manifest.suite.require_live_sdk_contract) {
        $tokens += "-RequireLiveSdkContract"
    }
    if ($IntegrationPreflight) {
        $tokens += "-IntegrationPreflight"
    }

    Write-Host "$Phase starting for attempt $($manifest.attempt_id)"
    # The shared contained-child contract hashes the exact bounded runner from
    # one retained FileShare.Read stream and keeps that stream open through Job
    # drain. The -File path therefore cannot be replaced between verification
    # and PowerShell's open, and no descendant can survive the accepted exit.
    $child = Invoke-WeatherIntegrationContainedPowerShellChild `
        -ScriptPath $boundedSuiteScript `
        -ExpectedSha256 ([string]$manifest.orchestration.bounded_suite.sha256) `
        -Arguments $tokens `
        -Label $Phase `
        -WorkingDirectory ([string]$manifest.repo_root) `
        -OutputDirectory ([string]$manifest.attempt_root) `
        -HardStop $suiteSharedHardStopLocal
    if ([double]$suiteRuntimeStopwatch.Elapsed.TotalSeconds -gt
            [double]$suiteMaxRuntimeSeconds) {
        throw "$Phase exceeded the immutable shared suite runtime ceiling."
    }
    return [int]$child.ExitCode
}

function Assert-WeatherAttemptSuiteWorktreeState {
    param(
        [Parameter(Mandatory = $true)][string]$Phase
    )

    Assert-WeatherIntegrationNoIgnoredImportArtifacts `
        -WorktreeRoot ([string]$manifest.worktree_root) `
        -Phase "$Phase initial wrapper boundary" | Out-Null

    $registered = $false
    $worktreeQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root ([string]$manifest.repo_root) `
        -Arguments @("worktree", "list", "--porcelain") `
        -Label "$Phase registered-worktree query"
    $worktreeRows = @($worktreeQuery.StdoutLines)
    foreach ($row in $worktreeRows) {
        if ([string]$row -like "worktree *") {
            $candidate = ([string]$row).Substring("worktree ".Length)
            if (Test-WeatherIntegrationPathEqual -Left $candidate -Right ([string]$manifest.worktree_root)) {
                $registered = $true
                break
            }
        }
    }
    if (-not $registered) {
        throw "$Phase suite worktree is no longer registered by the production repository."
    }

    $worktreeTipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root ([string]$manifest.worktree_root) `
        -Arguments @("rev-parse", "HEAD") `
        -Label "$Phase worktree-tip query"
    $worktreeTipRows = @($worktreeTipQuery.StdoutLines)
    if ($worktreeTipRows.Count -ne 1) {
        throw "$Phase could not resolve the suite worktree HEAD."
    }
    $branchTipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root ([string]$manifest.repo_root) `
        -Arguments @("rev-parse", [string]$manifest.branch_ref) `
        -Label "$Phase frozen-branch query"
    $branchTipRows = @($branchTipQuery.StdoutLines)
    if ($branchTipRows.Count -ne 1) {
        throw "$Phase could not resolve the frozen branch ref."
    }
    $worktreeTip = ([string]$worktreeTipRows[0]).Trim().ToLowerInvariant()
    $branchTip = ([string]$branchTipRows[0]).Trim().ToLowerInvariant()
    if ($worktreeTip -ne [string]$manifest.expected_tip -or
        $branchTip -ne [string]$manifest.expected_tip) {
        throw "$Phase suite worktree or branch no longer resolves to the frozen expected tip."
    }

    $statusQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root ([string]$manifest.worktree_root) `
        -Arguments @("status", "--porcelain") `
        -Label "$Phase clean-worktree query"
    $dirty = @($statusQuery.StdoutLines)
    if ($dirty.Count -ne 0) {
        throw "$Phase suite worktree is not clean."
    }
    $trackedTestQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root ([string]$manifest.worktree_root) `
        -Arguments @("ls-files", "--", "tests") `
        -Label "$Phase frozen-pytest-inventory query"
    $trackedTestRows = @($trackedTestQuery.StdoutLines)
    $trackedTests = @(
        $trackedTestRows |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object { $_ -match '^tests/(?:.*/)?(?:test_[^/]*|[^/]+_test)\.py$' } |
            Sort-Object
    )
    $expectedCount = [int]$manifest.suite.expected_test_file_count
    $expectedChunks = [int]$manifest.suite.expected_chunk_count
    $actualChunks = [int][math]::Ceiling(
        $trackedTests.Count / [double][int]$manifest.suite.max_files_per_chunk
    )
    if ($trackedTests.Count -ne $expectedCount -or $actualChunks -ne $expectedChunks) {
        throw "$Phase tracked pytest inventory no longer matches the frozen manifest."
    }
    if ([string]$manifest.schema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
        $trackedSourceQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root ([string]$manifest.worktree_root) `
            -Arguments @("ls-files", "--", "*.py", "*.ps1") `
            -Label "$Phase frozen-syntax-inventory query"
        $trackedSourceRows = @($trackedSourceQuery.StdoutLines)
        $trackedPython = @($trackedSourceRows |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object { $_ -match '(?i)\.py$' } |
            Sort-Object -Unique)
        $trackedPowerShell = @($trackedSourceRows |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object { $_ -match '(?i)\.ps1$' } |
            Sort-Object -Unique)
        if ((Get-WeatherIntegrationInventorySha256 -Paths $trackedTests) -cne
                [string]$manifest.suite.expected_test_inventory_sha256 -or
            $trackedPython.Count -ne
                [int]$manifest.suite.expected_python_file_count -or
            (Get-WeatherIntegrationInventorySha256 -Paths $trackedPython) -cne
                [string]$manifest.suite.expected_python_inventory_sha256 -or
            $trackedPowerShell.Count -ne
                [int]$manifest.suite.expected_powershell_file_count -or
            (Get-WeatherIntegrationInventorySha256 -Paths $trackedPowerShell) -cne
                [string]$manifest.suite.expected_powershell_inventory_sha256) {
            throw "$Phase exact creator-frozen inventory hashes no longer match the worktree."
        }
    }

    # None of the authority-bearing Git observations above is an atomic Git
    # operation.  Repeat the complete registered-worktree/ref/status/inventory
    # tuple before returning so a transition between individual queries can
    # never be reported as one coherent PASS generation.
    Assert-WeatherIntegrationNoIgnoredImportArtifacts `
        -WorktreeRoot ([string]$manifest.worktree_root) `
        -Phase "$Phase closing wrapper boundary" | Out-Null
    $closingWorktreeQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root ([string]$manifest.repo_root) `
        -Arguments @("worktree", "list", "--porcelain") `
        -Label "$Phase closing registered-worktree query"
    $closingWorktreeRows = @($closingWorktreeQuery.StdoutLines)
    $closingRegistered = $false
    foreach ($row in $closingWorktreeRows) {
        if ([string]$row -like "worktree *" -and
            (Test-WeatherIntegrationPathEqual `
                -Left ([string]$row).Substring("worktree ".Length) `
                -Right ([string]$manifest.worktree_root))) {
            $closingRegistered = $true
            break
        }
    }
    $closingWorktreeTipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root ([string]$manifest.worktree_root) `
        -Arguments @("rev-parse", "HEAD") `
        -Label "$Phase closing worktree-tip query"
    $closingWorktreeTipRows = @($closingWorktreeTipQuery.StdoutLines)
    $closingBranchTipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root ([string]$manifest.repo_root) `
        -Arguments @("rev-parse", [string]$manifest.branch_ref) `
        -Label "$Phase closing frozen-branch query"
    $closingBranchTipRows = @($closingBranchTipQuery.StdoutLines)
    $closingStatusQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root ([string]$manifest.worktree_root) `
        -Arguments @("status", "--porcelain") `
        -Label "$Phase closing clean-worktree query"
    $closingDirty = @($closingStatusQuery.StdoutLines)
    $closingTrackedTestQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root ([string]$manifest.worktree_root) `
        -Arguments @("ls-files", "--", "tests") `
        -Label "$Phase closing frozen-pytest-inventory query"
    $closingTrackedTests = @(
        @($closingTrackedTestQuery.StdoutLines) |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object { $_ -match '^tests/(?:.*/)?(?:test_[^/]*|[^/]+_test)\.py$' } |
            Sort-Object
    )
    if (-not $closingRegistered -or
        ($worktreeRows -join "`n") -cne ($closingWorktreeRows -join "`n") -or
        $closingWorktreeTipRows.Count -ne 1 -or
        $closingBranchTipRows.Count -ne 1 -or
        ([string]$closingWorktreeTipRows[0]).Trim().ToLowerInvariant() -cne
            $worktreeTip -or
        ([string]$closingBranchTipRows[0]).Trim().ToLowerInvariant() -cne
            $branchTip -or
        $closingDirty.Count -ne 0 -or
        ($dirty -join "`n") -cne ($closingDirty -join "`n") -or
        ($trackedTests -join "`n") -cne ($closingTrackedTests -join "`n")) {
        throw "$Phase suite worktree/ref/test tuple changed while it was being validated."
    }
    if ([string]$manifest.schema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
        $closingTrackedSourceQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root ([string]$manifest.worktree_root) `
            -Arguments @("ls-files", "--", "*.py", "*.ps1") `
            -Label "$Phase closing frozen-syntax-inventory query"
        $closingTrackedSourceRows = @($closingTrackedSourceQuery.StdoutLines)
        $closingTrackedPython = @($closingTrackedSourceRows |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object { $_ -match '(?i)\.py$' } |
            Sort-Object -Unique)
        $closingTrackedPowerShell = @($closingTrackedSourceRows |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object { $_ -match '(?i)\.ps1$' } |
            Sort-Object -Unique)
        if (($trackedPython -join "`n") -cne ($closingTrackedPython -join "`n") -or
            ($trackedPowerShell -join "`n") -cne
                ($closingTrackedPowerShell -join "`n")) {
            throw "$Phase Python/PowerShell source tuple changed while it was being validated."
        }
    }
}

$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract
$preparationAuthorization = Assert-WeatherIntegrationPreparationExecutionAuthorization `
    -AttemptContract $contract -RequireLiveQualificationInputs
$activationReceipt = Assert-WeatherIntegrationActivationReceipt `
    -AttemptContract $contract
$manifest = $contract.Manifest
$suiteMaxRuntimeSeconds = if ([string]$manifest.schema -ceq
        $script:WeatherIntegrationAttemptManifestSchema) {
    [int]$manifest.suite.bounded_suite_max_runtime_seconds
}
else {
    [int]$script:WeatherIntegrationBoundedSuiteMaximumRuntimeSeconds
}
$suiteTeardownAllowanceSeconds = if ([string]$manifest.schema -ceq
        $script:WeatherIntegrationAttemptManifestSchema) {
    [int]$manifest.suite.suite_wrapper_teardown_allowance_seconds
}
else {
    [int]$script:WeatherIntegrationSuiteWrapperTeardownAllowanceSeconds
}
$suiteTaskExecutionLimitSeconds = if ([string]$manifest.schema -ceq
        $script:WeatherIntegrationAttemptManifestSchema) {
    [int]$manifest.suite.suite_task_execution_time_limit_seconds
}
else {
    # V1 remains structurally readable; the wrapper still uses the current
    # bounded runtime even though its historical task setting was PT8H.
    [int]$script:WeatherIntegrationSuiteTaskExecutionLimitSeconds
}
Assert-WeatherIntegrationAttemptNotTerminal `
    -AttemptContract $contract -Operation "Integration-attempt suite execution"
if (-not [string]::IsNullOrWhiteSpace([string]$manifest.suite.additional_python_path)) {
    throw "AdditionalPythonPath is unsupported for immutable integration attempts."
}
$suiteTaskBinding = Assert-WeatherIntegrationAttemptTaskBinding `
    -AttemptContract $contract `
    -Role "suite" `
    -IncludeTaskInfo
if ([string]$suiteTaskBinding.Task.State -ne "Running") {
    throw "Integration-attempt suite may run only as its exact registered one-shot task."
}
$suiteReceiptPath = [string]$manifest.evidence.suite_receipt
$preflightLogPath = [string]$manifest.evidence.preflight_log
$fullSuiteLogPath = [string]$manifest.evidence.full_suite_log

foreach ($freshPath in @($suiteReceiptPath, $preflightLogPath, $fullSuiteLogPath)) {
    if (Test-Path -LiteralPath $freshPath) {
        throw "Attempt suite evidence already exists and will not be appended or replaced: $freshPath"
    }
}

$repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
Assert-WeatherIntegrationGitControlSafety `
    -RepositoryRoots @($repoRoot, [string]$manifest.worktree_root)
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

$localNow = Get-WeatherIntegrationScheduleLocalNow
if ([string]$manifest.schema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
    Assert-WeatherIntegrationSchedulerHostTimeZone | Out-Null
    $scheduleEvidence = Assert-WeatherIntegrationScheduleEvidence `
        -Schedule $manifest.schedule -Label "suite manifest schedule"
    $suiteAt = [datetime]$scheduleEvidence.SuiteAtLocal
}
else {
    $suiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$manifest.schedule.suite_at_local) `
        -Label "suite_at_local"
    $mergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$manifest.schedule.merge_at_local) `
        -Label "merge_at_local"
}
if ($localNow.Date -ne $suiteAt.Date) {
    throw "Integration-attempt suite may run only on its immutable scheduled local date."
}
$localMinute = ($localNow.Hour * 60) + $localNow.Minute
if ($localMinute -lt 30 -or $localMinute -ge (9 * 60)) {
    throw "Integration-attempt suite must start inside the 00:30-09:00 heavy-work window."
}
$suiteHardStopLocal = $localNow.Date.AddHours(9)
if ([string]$manifest.schema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
    $requiredRuntimeSeconds = [int]$manifest.suite.prearming_required_runtime_seconds
    $mergeAt = [datetime]$scheduleEvidence.MergeAtLocal
    Assert-WeatherIntegrationScheduledSuiteLaunchReserve `
        -SuiteAtLocal $suiteAt `
        -MergeAtLocal $mergeAt `
        -Now $localNow `
        -RequiredExecutionSeconds $requiredRuntimeSeconds `
        -LaunchGraceSeconds ([int]$manifest.suite.prearming_launch_grace_seconds) `
        -RequiredScheduleSeconds (
            [int]$manifest.suite.prearming_required_schedule_seconds
        ) | Out-Null
}
$scheduleTimeZone = Get-WeatherIntegrationScheduleTimeZone
$suiteHardStopInstant = ConvertTo-WeatherIntegrationLocalInstant `
    -Value $suiteHardStopLocal -Label "suite 09:00 hard stop" `
    -TimeZone $scheduleTimeZone
$mergeInstant = ConvertTo-WeatherIntegrationLocalInstant `
    -Value $mergeAt -Label "suite merge deadline" -TimeZone $scheduleTimeZone
$suiteRuntimeStartedAtUtc = [DateTimeOffset]::UtcNow
$suiteRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()
$suiteRuntimeDeadlineUtc = $suiteRuntimeStartedAtUtc.AddSeconds(
    [int]$suiteMaxRuntimeSeconds
)
$suiteSharedDeadlineUtc = $suiteRuntimeDeadlineUtc
foreach ($candidateDeadline in @($suiteHardStopInstant, $mergeInstant)) {
    if ($candidateDeadline.UtcDateTime -lt $suiteSharedDeadlineUtc.UtcDateTime) {
        $suiteSharedDeadlineUtc = $candidateDeadline.ToUniversalTime()
    }
}
$suiteSharedHardStopLocal = [datetime]::SpecifyKind(
    [TimeZoneInfo]::ConvertTime(
        $suiteSharedDeadlineUtc,
        $scheduleTimeZone
    ).DateTime,
    [DateTimeKind]::Unspecified
)
if (($suiteSharedDeadlineUtc - [DateTimeOffset]::UtcNow).TotalSeconds -lt
        [int]$script:WeatherIntegrationSuiteMinimumPhaseRuntimeSeconds) {
    throw "Integration-attempt suite has no bounded shared runtime remaining."
}
$startedAt = [datetimeoffset]::Now.ToString("o")
$status = "FAIL"
$failure = $null
$preflightExitCode = $null
$fullSuiteExitCode = $null
$preflightVerdict = $null
$fullSuiteVerdict = $null
$preflightTestResults = $null
$fullSuiteTestResults = $null
$preflightLogSnapshot = $null
$fullSuiteLogSnapshot = $null
$preflightEvidenceValidationError = $null
$fullSuiteEvidenceValidationError = $null
$evidenceValidationPhase = $null

try {
    Assert-WeatherIntegrationLiveOriginBaseline `
        -AttemptContract $contract `
        -Phase "integration preflight" `
        -RefreshTrackingMaster | Out-Null
    Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase "integration preflight" | Out-Null
    Assert-WeatherAttemptSuiteWorktreeState -Phase "integration preflight"
    Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $contract | Out-Null
    $preflightExitCode = Invoke-WeatherAttemptSuitePhase `
        -Phase "integration preflight" `
        -LogPath $preflightLogPath `
        -IntegrationPreflight
    if ($preflightExitCode -ne 0) {
        throw "Integration preflight failed with exit code $preflightExitCode; full suite was not started."
    }
    $evidenceValidationPhase = "preflight"
    $preflightLogSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $preflightLogPath -MaximumBytes 67108864 -ContentType Text
    $preflightVerdict = Get-WeatherIntegrationLogVerdict -Path $preflightLogPath -EvidenceSnapshot $preflightLogSnapshot
    Assert-WeatherIntegrationPreflightVerdict -Verdict $preflightVerdict
    $preflightDeclaredPlan = Get-WeatherIntegrationSuiteLogDeclaredPlan `
        -Path $preflightLogPath -EvidenceSnapshot $preflightLogSnapshot
    if ([int]$preflightDeclaredPlan.MaxFilesPerChunk -ne 20) {
        throw "Integration-preflight log changed its bounded chunk size."
    }
    $preflightTestResults = Get-WeatherIntegrationSuiteEvidenceSummary `
        -Path $preflightLogPath `
        -ExpectedChunkCount ([int]$preflightDeclaredPlan.Chunks) `
        -ExpectedPlannedFiles ([int]$preflightDeclaredPlan.Files) `
        -EvidenceSnapshot $preflightLogSnapshot `
        -RequireRuntimeFingerprint:([string]$manifest.schema -ceq
            $script:WeatherIntegrationAttemptManifestSchema)
    if ([string]$manifest.schema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
        Assert-WeatherIntegrationExpectedSuiteInventories `
            -Summary $preflightTestResults `
            -Expected $manifest.suite `
            -ExpectedRepoRoot ([string]$manifest.repo_root) `
            -ExpectedWorktreeRoot ([string]$manifest.worktree_root) `
            -ExpectedTip ([string]$manifest.expected_tip) `
            -Label "Integration preflight" | Out-Null
        Assert-WeatherIntegrationRepeatedSuiteSummary `
            -QualificationSummary (
                $preparationAuthorization.Qualification.Receipt.runs.integration_preflight.test_results
            ) `
            -RepeatedSummary $preflightTestResults `
            -Label "integration preflight" | Out-Null
    }
    $evidenceValidationPhase = $null

    Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase "full-suite start" | Out-Null
    Assert-WeatherAttemptSuiteWorktreeState -Phase "full-suite start"
    Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $contract | Out-Null
    $fullSuiteExitCode = Invoke-WeatherAttemptSuitePhase `
        -Phase "full suite" `
        -LogPath $fullSuiteLogPath
    if ($fullSuiteExitCode -ne 0) {
        throw "Full suite failed with exit code $fullSuiteExitCode."
    }
    $evidenceValidationPhase = "full_suite"
    $fullSuiteLogSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $fullSuiteLogPath -MaximumBytes 67108864 -ContentType Text
    $fullSuiteVerdict = Get-WeatherIntegrationLogVerdict -Path $fullSuiteLogPath -EvidenceSnapshot $fullSuiteLogSnapshot
    Assert-WeatherIntegrationFullSuiteVerdict `
        -Verdict $fullSuiteVerdict `
        -ExpectedChunkCount ([int]$manifest.suite.expected_chunk_count) | Out-Null
    Assert-WeatherIntegrationFullSuiteLogPlan `
        -Path $fullSuiteLogPath `
        -ExpectedTestFileCount ([int]$manifest.suite.expected_test_file_count) `
        -ExpectedMaxFilesPerChunk ([int]$manifest.suite.max_files_per_chunk) `
        -ExpectedChunkCount ([int]$manifest.suite.expected_chunk_count) `
        -EvidenceSnapshot $fullSuiteLogSnapshot | Out-Null
    $fullSuiteTestResults = Get-WeatherIntegrationSuiteEvidenceSummary `
        -Path $fullSuiteLogPath `
        -ExpectedChunkCount ([int]$manifest.suite.expected_chunk_count) `
        -ExpectedPlannedFiles ([int]$manifest.suite.expected_test_file_count) `
        -EvidenceSnapshot $fullSuiteLogSnapshot `
        -RequireRuntimeFingerprint:([string]$manifest.schema -ceq
            $script:WeatherIntegrationAttemptManifestSchema)
    if ([string]$manifest.schema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
        Assert-WeatherIntegrationExpectedSuiteInventories `
            -Summary $fullSuiteTestResults `
            -Expected $manifest.suite `
            -ExpectedRepoRoot ([string]$manifest.repo_root) `
            -ExpectedWorktreeRoot ([string]$manifest.worktree_root) `
            -ExpectedTip ([string]$manifest.expected_tip) `
            -Label "Full suite" `
            -IncludeTestInventory | Out-Null
        Assert-WeatherIntegrationRepeatedSuiteSummary `
            -QualificationSummary (
                $preparationAuthorization.Qualification.Receipt.runs.full_suite.test_results
            ) `
            -RepeatedSummary $fullSuiteTestResults `
            -Label "full suite" | Out-Null
    }
    $evidenceValidationPhase = $null
    Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase "full-suite completion" | Out-Null
    Assert-WeatherAttemptSuiteWorktreeState -Phase "full-suite completion"
    Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract
    if ([double]$suiteRuntimeStopwatch.Elapsed.TotalSeconds -gt
            [double]$suiteMaxRuntimeSeconds -or
        [DateTimeOffset]::UtcNow.UtcDateTime -gt
            $suiteSharedDeadlineUtc.UtcDateTime) {
        throw "Integration-attempt suite exhausted its one shared phase deadline before PASS."
    }
    $status = "PASS"
}
catch {
    $failure = $_.Exception.Message
    $boundedEvidenceError = [string]$failure
    if ($boundedEvidenceError.Length -gt 1024) {
        $boundedEvidenceError = $boundedEvidenceError.Substring(0, 1024)
    }
    if ($evidenceValidationPhase -eq "preflight") {
        $preflightEvidenceValidationError = $boundedEvidenceError
    }
    elseif ($evidenceValidationPhase -eq "full_suite") {
        $fullSuiteEvidenceValidationError = $boundedEvidenceError
    }
    Write-Error $failure -ErrorAction Continue
}
finally {
    if ($status -eq "PASS" -and
        ([double]$suiteRuntimeStopwatch.Elapsed.TotalSeconds -gt
            [double]$suiteMaxRuntimeSeconds -or
         [DateTimeOffset]::UtcNow.UtcDateTime -gt
            $suiteSharedDeadlineUtc.UtcDateTime)) {
        $status = "FAIL"
        $failure = "Integration-attempt suite exhausted its one shared phase deadline before immutable receipt publication."
    }
    $preflightLogRecord = $null
    if (Test-Path -LiteralPath $preflightLogPath -PathType Leaf) {
        try {
            if ($null -eq $preflightLogSnapshot) {
                $preflightLogSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $preflightLogPath -MaximumBytes 67108864 -ContentType Text
            }
            if ($null -eq $preflightVerdict) {
                $preflightVerdict = Get-WeatherIntegrationLogVerdict `
                    -Path $preflightLogPath `
                    -EvidenceSnapshot $preflightLogSnapshot
            }
        }
        catch {
            if ($null -eq $preflightEvidenceValidationError) {
                $preflightEvidenceValidationError = [string]$_.Exception.Message
                if ($preflightEvidenceValidationError.Length -gt 1024) {
                    $preflightEvidenceValidationError = `
                        $preflightEvidenceValidationError.Substring(0, 1024)
                }
            }
        }
        $preflightLogRecord = [ordered]@{
            path = $preflightLogPath
            sha256 = if ($null -ne $preflightLogSnapshot) {
                [string]$preflightLogSnapshot.Sha256
            } else { $null }
            exit_code = $preflightExitCode
            verdict = $preflightVerdict
            test_results = $preflightTestResults
            evidence_validation_error = $preflightEvidenceValidationError
        }
    }

    $fullSuiteLogRecord = $null
    if (Test-Path -LiteralPath $fullSuiteLogPath -PathType Leaf) {
        try {
            if ($null -eq $fullSuiteLogSnapshot) {
                $fullSuiteLogSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $fullSuiteLogPath -MaximumBytes 67108864 -ContentType Text
            }
            if ($null -eq $fullSuiteVerdict) {
                $fullSuiteVerdict = Get-WeatherIntegrationLogVerdict `
                    -Path $fullSuiteLogPath `
                    -EvidenceSnapshot $fullSuiteLogSnapshot
            }
        }
        catch {
            if ($null -eq $fullSuiteEvidenceValidationError) {
                $fullSuiteEvidenceValidationError = [string]$_.Exception.Message
                if ($fullSuiteEvidenceValidationError.Length -gt 1024) {
                    $fullSuiteEvidenceValidationError = `
                        $fullSuiteEvidenceValidationError.Substring(0, 1024)
                }
            }
        }
        $fullSuiteLogRecord = [ordered]@{
            path = $fullSuiteLogPath
            sha256 = if ($null -ne $fullSuiteLogSnapshot) {
                [string]$fullSuiteLogSnapshot.Sha256
            } else { $null }
            exit_code = $fullSuiteExitCode
            verdict = $fullSuiteVerdict
            test_results = $fullSuiteTestResults
            evidence_validation_error = $fullSuiteEvidenceValidationError
        }
    }

    $completedAtEvidence = [datetimeoffset]::Now
    $completedElapsedSeconds = [math]::Round(
        [double]$suiteRuntimeStopwatch.Elapsed.TotalSeconds,
        3
    )
    if ($status -eq "PASS" -and
        ([double]$completedElapsedSeconds -gt
            [double]$suiteMaxRuntimeSeconds -or
         $completedAtEvidence.UtcDateTime -gt
            $suiteSharedDeadlineUtc.UtcDateTime)) {
        $status = "FAIL"
        $failure = "Integration-attempt suite exhausted its one shared phase deadline while validating final evidence."
    }
    $receipt = [ordered]@{
        schema = $script:WeatherIntegrationAttemptSuiteReceiptSchema
        status = $status
        attempt_id = [string]$manifest.attempt_id
        manifest_path = $contract.ManifestPath
        manifest_sha256 = $contract.ManifestSha256
        registration_receipt_sha256 = $suiteTaskBinding.RegistrationReceiptSha256
        registration_intent_sha256 = $suiteTaskBinding.RegistrationIntentSha256
        branch_ref = [string]$manifest.branch_ref
        expected_tip = [string]$manifest.expected_tip
        origin_url = [string]$manifest.baseline.origin_url
        worktree_root = [string]$manifest.worktree_root
        started_at_local = $startedAt
        completed_at_local = $completedAtEvidence.ToString("o")
        failure = $failure
        runtime = [ordered]@{
            bounded_suite_max_runtime_seconds =
                [int]$suiteMaxRuntimeSeconds
            suite_wrapper_teardown_allowance_seconds =
                [int]$suiteTeardownAllowanceSeconds
            suite_task_execution_time_limit_seconds =
                [int]$suiteTaskExecutionLimitSeconds
            minimum_phase_runtime_seconds =
                [int]$script:WeatherIntegrationSuiteMinimumPhaseRuntimeSeconds
            shared_deadline_utc = ConvertTo-WeatherIntegrationUtcTimestamp `
                -Value $suiteSharedDeadlineUtc
            elapsed_seconds = [math]::Round(
                [double]$completedElapsedSeconds, 3
            )
        }
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
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $contract | Out-Null
    Write-WeatherIntegrationImmutableJson -Path $suiteReceiptPath -Payload $receipt
}

if ($status -ne "PASS") {
    Write-Host "Integration attempt $($manifest.attempt_id) failed. Evidence is frozen; repair by creating a new attempt bound to this FAIL receipt."
    exit 1
}

Write-Host "Integration attempt $($manifest.attempt_id) suite passed. Merge remains separately gated."
exit 0
