# Consume one immutable PASS suite receipt, invoke the existing guarded quiet
# merge, and emit a per-attempt PASS/FAIL receipt. Downstream work may bind only
# to this receipt; a generic task exit code or mutable latest-report slot is not
# sufficient evidence.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedManifestSha256,
    [ValidateRange(60, 1800)]
    [int]$SettleSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

function Invoke-WeatherIntegrationGitLine {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = @(& git -C $Root @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "git -C $Root $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    return (($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
}

function Assert-WeatherIntegrationSuiteTaskBinding {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$SuiteScript,
        [Parameter(Mandatory = $true)][string]$PowerShellExecutable
    )

    # The shared validator retains the old fail-closed diagnostic contract:
    # "Suite task arguments are not exactly bound" remains the meaning of any
    # action mismatch, now extended to principal, trigger, and settings drift.
    return Assert-WeatherIntegrationAttemptTaskBinding `
        -AttemptContract $AttemptContract `
        -Role "suite" `
        -IncludeTaskInfo
}

function Assert-WeatherIntegrationSuiteTask {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][object]$SuiteReceiptContract,
        [Parameter(Mandatory = $true)][string]$SuiteScript,
        [Parameter(Mandatory = $true)][string]$PowerShellExecutable
    )

    $binding = Assert-WeatherIntegrationSuiteTaskBinding `
        -AttemptContract $AttemptContract `
        -SuiteScript $SuiteScript `
        -PowerShellExecutable $PowerShellExecutable
    $task = $binding.Task
    $taskInfo = $binding.Info
    $taskName = [string]$AttemptContract.Manifest.schedule.suite_task_name
    if ([string]$task.State -eq "Running") { throw "Suite task is still running: $taskName" }
    if ([string]$task.State -notin @("Ready", "Disabled")) {
        throw "Suite task is not terminal: $taskName state=$($task.State)"
    }
    if ([datetime]$taskInfo.LastRunTime -lt (Get-Date).Date) {
        throw "Suite task did not run on the current local day."
    }
    # SuiteReceiptContract has already passed the complete immutable receipt,
    # log-hash, exact-verdict, and frozen-plan validation. On a terminal task,
    # Scheduler's running/not-run codes can lag State; every other nonzero
    # result remains authoritative failure evidence.
    $staleTerminalResult = [int]$taskInfo.LastTaskResult -in @(0x41301, 0x41303)
    if ([int]$taskInfo.LastTaskResult -ne 0 -and -not $staleTerminalResult) {
        throw ("Suite task result is 0x{0:X}, not success." -f [int]$taskInfo.LastTaskResult)
    }

    $receiptStarted = [datetime]::Parse([string]$SuiteReceiptContract.Receipt.started_at_local)
    if ([math]::Abs(($receiptStarted - [datetime]$taskInfo.LastRunTime).TotalMinutes) -gt 5) {
        throw "Suite task LastRunTime does not correlate to the immutable receipt."
    }
}

function Wait-WeatherIntegrationSuiteTerminal {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$SuiteScript,
        [Parameter(Mandatory = $true)][string]$PowerShellExecutable
    )

    $manifest = $AttemptContract.Manifest
    $receiptPath = [string]$manifest.evidence.suite_receipt
    $suiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$manifest.schedule.suite_at_local) `
        -Label "suite_at_local"
    $deadline = $suiteAt.Date.AddMinutes(220)
    $lastNotice = [datetime]::MinValue
    while ($true) {
        $binding = Assert-WeatherIntegrationSuiteTaskBinding `
            -AttemptContract $AttemptContract `
            -SuiteScript $SuiteScript `
            -PowerShellExecutable $PowerShellExecutable
        if ([string]$binding.Task.State -ne "Running" -and
            [int]$binding.Info.LastTaskResult -in @(0x41301, 0x41303)) {
            Start-Sleep -Seconds 1
            $binding = Assert-WeatherIntegrationSuiteTaskBinding `
                -AttemptContract $AttemptContract `
                -SuiteScript $SuiteScript `
                -PowerShellExecutable $PowerShellExecutable
        }
        $receiptExists = Test-Path -LiteralPath $receiptPath -PathType Leaf
        $receiptStatus = ""
        if ($receiptExists) {
            $receiptStatus = [string](Read-WeatherIntegrationSharedJson -Path $receiptPath).status
        }
        $now = Get-Date
        $decision = Get-WeatherIntegrationSuiteWaitDecision `
            -TaskState ([string]$binding.Task.State) `
            -LastRunTime ([datetime]$binding.Info.LastRunTime) `
            -LastTaskResult ([int]$binding.Info.LastTaskResult) `
            -ReceiptExists ([bool]$receiptExists) `
            -ReceiptStatus $receiptStatus `
            -Now $now `
            -Deadline $deadline
        $passExitGraceProperty = $decision.PSObject.Properties["PassExitGrace"]
        if ($null -ne $passExitGraceProperty -and [bool]$passExitGraceProperty.Value -and
            $null -eq $script:suitePassExitGraceEvidence) {
            $script:suitePassExitGraceEvidence = [ordered]@{
                observed_at_local = $now.ToString("o")
                task_name = [string]$manifest.schedule.suite_task_name
                reason = [string]$decision.Reason
                grace_until_local = ([datetime]$decision.GraceUntil).ToString("o")
            }
        }
        $staleSchedulerResultProperty = $decision.PSObject.Properties["StaleSchedulerResult"]
        if ($null -ne $staleSchedulerResultProperty -and
            [bool]$staleSchedulerResultProperty.Value -and
            $null -eq $script:suiteStaleSchedulerResultEvidence) {
            $script:suiteStaleSchedulerResultEvidence = [ordered]@{
                observed_at_local = $now.ToString("o")
                task_name = [string]$manifest.schedule.suite_task_name
                task_state = [string]$binding.Task.State
                last_task_result = [int]$binding.Info.LastTaskResult
                receipt_status = $receiptStatus
                reason = [string]$decision.Reason
            }
        }
        if ([string]$decision.Action -eq "READY") { return }
        if ([string]$decision.Action -eq "STOP") {
            $taskName = [string]$manifest.schedule.suite_task_name
            $script:suiteDeadlineStopEvidence = [ordered]@{
                requested = $true
                requested_at_local = $now.ToString("o")
                task_name = $taskName
                reason = [string]$decision.Reason
                stopped = $false
                final_state = [string]$binding.Task.State
                last_task_result = [int]$binding.Info.LastTaskResult
            }
            Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop
            $stopDeadline = (Get-Date).AddMinutes(2)
            do {
                Start-Sleep -Seconds 2
                $binding = Assert-WeatherIntegrationSuiteTaskBinding `
                    -AttemptContract $AttemptContract `
                    -SuiteScript $SuiteScript `
                    -PowerShellExecutable $PowerShellExecutable
            } while ([string]$binding.Task.State -notin @("Ready", "Disabled") -and (Get-Date) -lt $stopDeadline)
            $script:suiteDeadlineStopEvidence.final_state = [string]$binding.Task.State
            $script:suiteDeadlineStopEvidence.last_task_result = [int]$binding.Info.LastTaskResult
            $script:suiteDeadlineStopEvidence.stopped = ([string]$binding.Task.State -in @("Ready", "Disabled"))
            if (-not [bool]$script:suiteDeadlineStopEvidence.stopped) {
                throw "Suite reached the merge-wait deadline and its exact task could not be stopped within two minutes."
            }
            throw "Suite cannot authorize merge: $($decision.Reason); its exact task was stopped and recorded for closure."
        }
        if ([string]$decision.Action -eq "FAIL") {
            throw "Suite cannot authorize merge: $($decision.Reason)"
        }
        if (($now - $lastNotice).TotalSeconds -ge 60) {
            Write-Host "Waiting for terminal suite evidence until $($deadline.ToString('o')): $($decision.Reason)"
            $lastNotice = $now
        }
        Start-Sleep -Seconds 5
    }
}

function Assert-WeatherIntegrationMergeTask {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$MergeScript,
        [Parameter(Mandatory = $true)][string]$PowerShellExecutable
    )

    $attempt = $AttemptContract.Manifest
    $taskName = [string]$attempt.schedule.merge_task_name
    $binding = Assert-WeatherIntegrationAttemptTaskBinding `
        -AttemptContract $AttemptContract `
        -Role "merge" `
        -IncludeTaskInfo
    $task = $binding.Task
    $taskInfo = $binding.Info
    if ($null -eq $taskInfo -or [datetime]$taskInfo.LastRunTime -lt (Get-Date).Date) {
        throw "Merge task did not start on the current local day."
    }
    if ([string]$task.State -ne "Running") {
        throw "Integration-attempt merge may run only as its registered one-shot task."
    }
}

function Invoke-WeatherQuietMergeChild {
    param(
        [Parameter(Mandatory = $true)][string]$QuietMergeScript,
        [Parameter(Mandatory = $true)][string]$PowerShellExecutable,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Branch,
        [Parameter(Mandatory = $true)][string]$ExpectedTip,
        [Parameter(Mandatory = $true)][string]$ExpectedBaseline,
        [Parameter(Mandatory = $true)][string]$AttemptReportPath,
        [Parameter(Mandatory = $true)][string]$ExpectedQuietMergeSha256
    )

    $tokens = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $QuietMergeScript,
        "-Branch", $Branch,
        "-ExpectedTip", $ExpectedTip,
        "-ExpectedBaseline", $ExpectedBaseline,
        "-RepoRoot", $RepoRoot,
        "-AttemptReportPath", $AttemptReportPath,
        "-ExpectedSelfSha256", $ExpectedQuietMergeSha256,
        "-SettleSeconds", [string]$SettleSeconds
    )
    $argumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
    $job = $null
    $process = $null
    try {
        $job = New-WeatherKillOnCloseJob
        $process = Start-WeatherProcessInJob `
            -Job $job `
            -FilePath $PowerShellExecutable `
            -ArgumentString $argumentString `
            -WorkingDirectory $RepoRoot
        $outerHardStop = (Get-Date).Date.AddHours(5)
        while (-not $process.HasExited) {
            if ((Get-Date) -ge $outerHardStop) {
                throw "Quiet merge child exceeded the 05:00 containment boundary."
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

function Get-WeatherIntegrationRecoverableActiveMarker {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot
    )

    $attempt = $AttemptContract.Manifest
    $markerPath = Join-Path $RepositoryRoot "data\alerts\quiet_window_merge_in_progress.json"
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        return $null
    }
    $markerSha256 = Get-WeatherIntegrationFileSha256 -Path $markerPath
    $markerRaw = Read-WeatherIntegrationSharedText -Path $markerPath
    try { $marker = $markerRaw | ConvertFrom-Json }
    catch { throw "Active quiet-merge marker JSON is unreadable after child failure." }
    if ([string]$marker.operation_mode -ceq "production_baseline_reconciliation_v0.1") {
        throw "Production-baseline reconciliation markers are one-shot and cannot enter generic integration-attempt recovery."
    }
    Assert-WeatherIntegrationBooleanProperties `
        -Object $marker `
        -Names @("execution_tape_readoption_expected") `
        -Label "active quiet-merge marker"
    if ([string]$marker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$marker.repo_root) -Right $RepositoryRoot) -or
        [string]$marker.phase -notin @(
            "merge_committed_unpublished", "documented_unpublished", "published"
        ) -or
        [string]$marker.branch -ne [string]$attempt.branch_ref -or
        [string]$marker.expected_tip -ne [string]$attempt.expected_tip -or
        [string]$marker.expected_baseline -ne [string]$attempt.baseline.master -or
        [string]$marker.resolved_branch_tip -ne [string]$attempt.expected_tip -or
        [string]$marker.baseline_commit -ne [string]$attempt.baseline.master -or
        [string]$marker.pre_merge_commit -notmatch '^[0-9a-f]{40}$' -or
        [string]$marker.merge_commit -notmatch '^[0-9a-f]{40}$' -or
        -not [bool]$marker.capture_recovery_proved -or
        ([bool]$marker.execution_tape_recovery_required -and
            -not [bool]$marker.execution_tape_recovery_proved) -or
        ([string]$marker.phase -eq "merge_committed_unpublished" -and
            [bool]$marker.documentation_transaction_recorded) -or
        ([string]$marker.phase -ne "merge_committed_unpublished" -and
            -not [bool]$marker.documentation_transaction_recorded) -or
        ([string]$marker.phase -eq "published" -and
            -not [bool]$marker.publication_acknowledged)) {
        throw "Active quiet-merge marker is not exact post-commit recovery evidence for this attempt."
    }
    if ([bool]$marker.documentation_transaction_recorded) {
        Assert-WeatherIntegrationQuietReportDocumentation `
            -AttemptContract $AttemptContract -QuietReport $marker | Out-Null
    }

    $branch = Invoke-WeatherIntegrationGitLine `
        -Root $RepositoryRoot -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
    $head = (Invoke-WeatherIntegrationGitLine -Root $RepositoryRoot -Arguments @("rev-parse", "HEAD")).ToLowerInvariant()
    $master = (Invoke-WeatherIntegrationGitLine -Root $RepositoryRoot -Arguments @("rev-parse", "master")).ToLowerInvariant()
    $origin = (Invoke-WeatherIntegrationGitLine -Root $RepositoryRoot -Arguments @("rev-parse", "origin/master")).ToLowerInvariant()
    $mergeCommit = ([string]$marker.merge_commit).ToLowerInvariant()
    if ($branch -ne "master" -or $head -ne $mergeCommit -or $master -ne $mergeCommit -or
        $origin -notin @([string]$attempt.baseline.origin_master, $mergeCommit)) {
        throw "Active quiet-merge marker does not match current checked-out master/origin state."
    }
    $mergeHeadPathOutput = @(& git -C $RepositoryRoot rev-parse --git-path MERGE_HEAD)
    if ($LASTEXITCODE -ne 0 -or $mergeHeadPathOutput.Count -ne 1) {
        throw "Could not resolve MERGE_HEAD while binding active recovery evidence."
    }
    $mergeHeadPath = ([string]$mergeHeadPathOutput[0]).Trim()
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) {
        $mergeHeadPath = Join-Path $RepositoryRoot $mergeHeadPath
    }
    if (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) {
        throw "Active quiet-merge marker is post-commit but MERGE_HEAD is still present."
    }
    $parentLine = Invoke-WeatherIntegrationGitLine `
        -Root $RepositoryRoot -Arguments @("rev-list", "--parents", "-n", "1", $mergeCommit)
    $firstParent = (Invoke-WeatherIntegrationGitLine `
        -Root $RepositoryRoot -Arguments @("rev-parse", "$mergeCommit^1")).ToLowerInvariant()
    $secondParent = (Invoke-WeatherIntegrationGitLine `
        -Root $RepositoryRoot -Arguments @("rev-parse", "$mergeCommit^2")).ToLowerInvariant()
    if (@($parentLine -split '\s+' | Where-Object { $_ }).Count -ne 3 -or
        $firstParent -ne ([string]$marker.pre_merge_commit).ToLowerInvariant() -or
        $secondParent -ne [string]$attempt.expected_tip) {
        throw "Active quiet-merge marker does not bind the exact two-parent attempt merge."
    }
    if ((Get-WeatherIntegrationFileSha256 -Path $markerPath) -ne $markerSha256) {
        throw "Active quiet-merge marker changed while the parent was binding recovery evidence."
    }
    return [pscustomobject]@{
        Path = Resolve-WeatherIntegrationPath -Path $markerPath
        Sha256 = $markerSha256
        RawText = $markerRaw
        Payload = $marker
    }
}

$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract
$manifest = $contract.Manifest
Assert-WeatherIntegrationAttemptNotTerminal `
    -AttemptContract $contract -Operation "Integration-attempt merge execution"
$mergeReceiptPath = [string]$manifest.evidence.merge_receipt
$attemptQuietReportPath = [string]$manifest.evidence.quiet_merge_report
foreach ($freshPath in @($mergeReceiptPath, $attemptQuietReportPath)) {
    if (Test-Path -LiteralPath $freshPath) {
        throw "Immutable merge evidence already exists and will not be replaced: $freshPath"
    }
}

$repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
$suiteScript = Join-Path $repoRoot "scripts\ops\integration_attempt_suite.ps1"
$quietMergeScript = Join-Path $repoRoot "scripts\ops\quiet_window_merge.ps1"
$tokenContractScript = Join-Path $repoRoot "scripts\ops\training_window_contract.ps1"
$jobScript = Join-Path $repoRoot "scripts\ops\windows_kill_on_close_job.ps1"
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
$quietReportPath = $attemptQuietReportPath
foreach ($requiredPath in @($suiteScript, $quietMergeScript, $tokenContractScript, $jobScript, $python)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required integration-attempt merge dependency is missing: $requiredPath"
    }
}
. $tokenContractScript
. $jobScript

$powerShellExecutable = Join-Path $PSHOME "powershell.exe"
if (-not (Test-Path -LiteralPath $powerShellExecutable -PathType Leaf)) {
    throw "Windows PowerShell executable is missing: $powerShellExecutable"
}

$startedAt = Get-Date
$status = "FAIL"
$failure = $null
$suiteReceiptContract = $null
$suiteReceiptSha256 = $null
$quietMergeExitCode = $null
$quietReport = $null
$quietReportSha256 = $null
$productionHead = $null
$originMaster = $null
$captureProof = $null
$documentationTransactionRecorded = $false
$publicationAcknowledged = $false
$sourceTipIntegrated = $false
$captureRecoveryProved = $false
$quietMergeLaunchSha256 = $null
$script:suiteDeadlineStopEvidence = $null
$script:suitePassExitGraceEvidence = $null
$script:suiteStaleSchedulerResultEvidence = $null
$deferredMergeReceiptMarker = $null
$preserveQuietReportForReconciliation = $false

try {
    $localMinute = ($startedAt.Hour * 60) + $startedAt.Minute
    if ($localMinute -lt 60 -or $localMinute -ge 240) {
        throw "Integration-attempt merge must start inside the 01:00-04:00 quiet window."
    }

    Assert-WeatherIntegrationMergeTask `
        -AttemptContract $contract `
        -MergeScript $PSCommandPath `
        -PowerShellExecutable $powerShellExecutable

    Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase "merge wait" | Out-Null
    Wait-WeatherIntegrationSuiteTerminal `
        -AttemptContract $contract `
        -SuiteScript $suiteScript `
        -PowerShellExecutable $powerShellExecutable
    Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract
    Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase "guarded merge" | Out-Null
    $suiteReceiptContract = Assert-WeatherIntegrationSuiteReceipt -AttemptContract $contract
    $suiteReceiptSha256 = $suiteReceiptContract.ReceiptSha256
    Assert-WeatherIntegrationSuiteTask `
        -AttemptContract $contract `
        -SuiteReceiptContract $suiteReceiptContract `
        -SuiteScript $suiteScript `
        -PowerShellExecutable $powerShellExecutable

    $branchTip = (Invoke-WeatherIntegrationGitLine `
        -Root $repoRoot `
        -Arguments @("rev-parse", [string]$manifest.branch_ref)).ToLowerInvariant()
    if ($branchTip -ne [string]$manifest.expected_tip) {
        throw "Branch moved after suite PASS. Expected $($manifest.expected_tip); got $branchTip"
    }

    $quietMergeLaunchSha256 = Get-WeatherIntegrationFileSha256 -Path $quietMergeScript
    if ($quietMergeLaunchSha256 -ne [string]$manifest.orchestration.quiet_merge.sha256) {
        throw "Quiet-merge script changed immediately before child launch."
    }
    $quietMergeExitCode = Invoke-WeatherQuietMergeChild `
        -QuietMergeScript $quietMergeScript `
        -PowerShellExecutable $powerShellExecutable `
        -RepoRoot $repoRoot `
        -Branch ([string]$manifest.branch_ref) `
        -ExpectedTip ([string]$manifest.expected_tip) `
        -ExpectedBaseline ([string]$manifest.baseline.master) `
        -AttemptReportPath $attemptQuietReportPath `
        -ExpectedQuietMergeSha256 ([string]$manifest.orchestration.quiet_merge.sha256)
    if ($quietMergeExitCode -ne 0) {
        throw "Guarded quiet merge failed with exit code $quietMergeExitCode."
    }
    if (-not (Test-Path -LiteralPath $quietReportPath -PathType Leaf)) {
        throw "Guarded quiet merge returned success without a report."
    }
    $quietReport = Read-WeatherIntegrationSharedJson -Path $quietReportPath
    $quietReportSha256 = Get-WeatherIntegrationFileSha256 -Path $quietReportPath
    $quietReportTimestamp = [datetime]::Parse([string]$quietReport.ts)
    if ($quietReportTimestamp -lt $startedAt.AddSeconds(-5)) {
        throw "Quiet merge report predates this attempt."
    }
    if ([string]$quietReport.schema -ne "quiet_window_merge_report_v0.2" -or
        -not [bool]$quietReport.ok -or [string]$quietReport.stage -ne "pushed" -or
        -not [bool]$quietReport.capture_recovery_proved -or
        ([bool]$quietReport.execution_tape_recovery_required -and
            -not [bool]$quietReport.execution_tape_recovery_proved) -or
        -not [bool]$quietReport.publication_acknowledged) {
        throw "Quiet merge report is not a pushed success."
    }
    if ([string]$quietReport.branch -ne [string]$manifest.branch_ref -or
        [string]$quietReport.expected_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.expected_baseline -ne [string]$manifest.baseline.master -or
        [string]$quietReport.baseline_commit -ne [string]$manifest.baseline.master -or
        [string]$quietReport.pre_merge_commit -notmatch '^[0-9a-f]{40}$' -or
        [string]$quietReport.resolved_branch_tip -ne [string]$manifest.expected_tip) {
        throw "Quiet merge report identity does not match this attempt."
    }
    $documentationTransactionRecorded = [bool]$quietReport.documentation_transaction_recorded
    if (-not $documentationTransactionRecorded) {
        throw "Quiet merge report does not prove the documentation transaction was recorded."
    }
    $documentationPendingSha256 = ([string]$quietReport.documentation_transaction_pending_sha256).ToLowerInvariant()
    $documentationSnapshotRelative = ([string]$quietReport.documentation_transaction_snapshot_path).Replace('\', '/')
    $expectedDocumentationSnapshotRelative = "data/alerts/documentation_transactions/pending-$documentationPendingSha256.json"
    $documentationSnapshotPath = Join-Path $repoRoot ($documentationSnapshotRelative -replace '/', '\')
    if ($documentationPendingSha256 -notmatch '^[0-9a-f]{64}$' -or
        $documentationSnapshotRelative -cne $expectedDocumentationSnapshotRelative -or
        (Get-WeatherIntegrationFileSha256 -Path $documentationSnapshotPath) -ne
            $documentationPendingSha256) {
        throw "Quiet merge report does not bind its immutable documentation transaction snapshot."
    }
    $documentationSnapshot = Read-WeatherIntegrationSharedJson -Path $documentationSnapshotPath
    $documentationMatches = @($documentationSnapshot.integrations | Where-Object {
        ([string]$_.integration_tip).ToLowerInvariant() -eq
            ([string]$quietReport.merge_commit).ToLowerInvariant() -and
        [string]$_.branch -ceq [string]$manifest.branch_ref -and
        ([string]$_.expected_tip).ToLowerInvariant() -eq [string]$manifest.expected_tip
    })
    if ([string]$documentationSnapshot.schema_version -ne "documentation_transaction_pending_v0.1" -or
        [string]$documentationSnapshot.status -ne "PENDING" -or
        ([string]$documentationSnapshot.latest_integration_tip).ToLowerInvariant() -ne
            ([string]$quietReport.merge_commit).ToLowerInvariant() -or
        $documentationMatches.Count -ne 1) {
        throw "Documentation transaction snapshot does not bind this exact attempt merge."
    }
    $quietReportSha256 = Get-WeatherIntegrationFileSha256 -Path $attemptQuietReportPath

    $productionHead = (Invoke-WeatherIntegrationGitLine -Root $repoRoot -Arguments @("rev-parse", "master")).ToLowerInvariant()
    $originMaster = (Invoke-WeatherIntegrationGitLine -Root $repoRoot -Arguments @("rev-parse", "origin/master")).ToLowerInvariant()
    $checkedOutHead = (Invoke-WeatherIntegrationGitLine -Root $repoRoot -Arguments @("rev-parse", "HEAD")).ToLowerInvariant()
    $checkedOutBranch = Invoke-WeatherIntegrationGitLine `
        -Root $repoRoot `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
    if ($checkedOutBranch -ne "master" -or $checkedOutHead -ne $productionHead -or
        $productionHead -ne $originMaster) {
        throw "Publication proof requires checked-out branch master with HEAD == master == origin/master."
    }
    if ([string]$quietReport.merge_commit -notmatch '^[0-9a-fA-F]{40}$' -or
        [string]$quietReport.merge_commit -ine $productionHead) {
        throw "Quiet merge report does not bind the published integration commit."
    }
    $mergeFirstParent = (Invoke-WeatherIntegrationGitLine `
        -Root $repoRoot -Arguments @("rev-parse", "$productionHead^1")).ToLowerInvariant()
    $mergeSecondParent = (Invoke-WeatherIntegrationGitLine `
        -Root $repoRoot -Arguments @("rev-parse", "$productionHead^2")).ToLowerInvariant()
    $mergeParentLine = (Invoke-WeatherIntegrationGitLine `
        -Root $repoRoot -Arguments @("rev-list", "--parents", "-n", "1", $productionHead))
    if (@($mergeParentLine -split '\s+' | Where-Object { $_ }).Count -ne 3 -or
        $mergeFirstParent -ne ([string]$quietReport.pre_merge_commit).ToLowerInvariant() -or
        $mergeSecondParent -ne [string]$manifest.expected_tip) {
        throw "Published integration commit is not the exact two-parent merge proved by the quiet report."
    }
    $publicationAcknowledged = $true
    & git -C $repoRoot merge-base --is-ancestor ([string]$manifest.expected_tip) $productionHead
    if ($LASTEXITCODE -ne 0) {
        throw "The frozen source tip is not an ancestor of the published integration commit."
    }
    $sourceTipIntegrated = $true

    $captureRaw = @(& $python -m weather.operations.capture_recovery_check --repo-root $repoRoot --json)
    $captureExitCode = $LASTEXITCODE
    $captureProof = (($captureRaw -join "`n") | ConvertFrom-Json)
    $unhealthyWorkers = @($captureProof.workers | Where-Object { -not [bool]$_.ok })
    if ($captureExitCode -ne 0 -or -not [bool]$captureProof.ok -or
        @($captureProof.workers).Count -ne 3 -or $unhealthyWorkers.Count -ne 0) {
        throw "Post-publication capture recovery proof is not healthy for all three workers."
    }
    $captureRecoveryProved = $true
    $status = "PASS"
}
catch {
    $failure = $_.Exception.Message
    Write-Error $failure -ErrorAction Continue
    if (Test-Path -LiteralPath $quietReportPath -PathType Leaf) {
        try {
            $candidateReport = Read-WeatherIntegrationSharedJson -Path $quietReportPath
            $candidateTimestamp = [datetime]::Parse([string]$candidateReport.ts)
            if ($candidateTimestamp -ge $startedAt.AddSeconds(-5) -and
                [string]$candidateReport.branch -eq [string]$manifest.branch_ref -and
                [string]$candidateReport.expected_tip -eq [string]$manifest.expected_tip -and
                [string]$candidateReport.expected_baseline -eq [string]$manifest.baseline.master) {
                $quietReport = $candidateReport
                $quietReportSha256 = Get-WeatherIntegrationFileSha256 -Path $attemptQuietReportPath
            }
        }
        catch { }
    }
    if ($null -ne $quietReport -and
        [string]$quietReport.schema -eq "quiet_window_merge_report_v0.2" -and
        [bool]$quietReport.ok -and
        [string]$quietReport.stage -eq "pushed" -and
        [bool]$quietReport.publication_acknowledged -and
        [bool]$quietReport.capture_recovery_proved -and
        (-not [bool]$quietReport.execution_tape_recovery_required -or
            [bool]$quietReport.execution_tape_recovery_proved) -and
        [string]$quietReport.branch -eq [string]$manifest.branch_ref -and
        [string]$quietReport.expected_tip -eq [string]$manifest.expected_tip -and
        [string]$quietReport.expected_baseline -eq [string]$manifest.baseline.master -and
        [string]$quietReport.baseline_commit -eq [string]$manifest.baseline.master -and
        [string]$quietReport.resolved_branch_tip -eq [string]$manifest.expected_tip -and
        [string]$quietReport.pre_merge_commit -match '^[0-9a-f]{40}$' -and
        [string]$quietReport.merge_commit -match '^[0-9a-f]{40}$' -and
        [bool]$quietReport.documentation_transaction_recorded) {
        try {
            # A valid immutable pushed report is stronger than a generic FAIL
            # receipt. Preserve the report-only reconciliation path unless the
            # sampled production refs prove an exact MERGED_UNVERIFIED receipt.
            Assert-WeatherIntegrationQuietReportDocumentation `
                -AttemptContract $contract -QuietReport $quietReport | Out-Null
            $preserveQuietReportForReconciliation = $true
            $productionHead = (Invoke-WeatherIntegrationGitLine -Root $repoRoot -Arguments @("rev-parse", "master")).ToLowerInvariant()
            $originMaster = (Invoke-WeatherIntegrationGitLine -Root $repoRoot -Arguments @("rev-parse", "origin/master")).ToLowerInvariant()
            $candidateHead = (Invoke-WeatherIntegrationGitLine -Root $repoRoot -Arguments @("rev-parse", "HEAD")).ToLowerInvariant()
            $candidateBranch = Invoke-WeatherIntegrationGitLine `
                -Root $repoRoot `
                -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
            if ($candidateBranch -eq "master" -and $candidateHead -eq $productionHead -and
                $productionHead -eq $originMaster -and
                ([string]$quietReport.merge_commit).ToLowerInvariant() -eq $productionHead) {
                $publicationAcknowledged = $true
                & git -C $repoRoot merge-base --is-ancestor ([string]$manifest.expected_tip) $productionHead
                if ($LASTEXITCODE -eq 0) {
                    $sourceTipIntegrated = $true
                    $status = "MERGED_UNVERIFIED"
                }
            }
        }
        catch { }
    }
}
finally {
    $reportAlreadyBindsRecoveredCommit = (
        $null -ne $quietReport -and
        [string]$quietReport.schema -eq "quiet_window_merge_report_v0.2" -and
        [bool]$quietReport.ok -and
        [string]$quietReport.stage -in @("pushed", "merged_unpushed") -and
        [bool]$quietReport.capture_recovery_proved -and
        (-not [bool]$quietReport.execution_tape_recovery_required -or
            [bool]$quietReport.execution_tape_recovery_proved)
    )
    if (-not $reportAlreadyBindsRecoveredCommit) {
        try {
            $deferredMergeReceiptMarker = Get-WeatherIntegrationRecoverableActiveMarker `
                -AttemptContract $contract -RepositoryRoot $repoRoot
        }
        catch {
            $markerFailure = $_.Exception.Message
            $failure = if ([string]::IsNullOrWhiteSpace([string]$failure)) {
                $markerFailure
            }
            else { "$failure; active-marker inspection: $markerFailure" }
        }
    }
    $receipt = [ordered]@{
        schema = $script:WeatherIntegrationAttemptMergeReceiptSchema
        status = $status
        attempt_id = [string]$manifest.attempt_id
        manifest_path = $contract.ManifestPath
        manifest_sha256 = $contract.ManifestSha256
        branch_ref = [string]$manifest.branch_ref
        source_tip = [string]$manifest.expected_tip
        suite_receipt_path = [string]$manifest.evidence.suite_receipt
        suite_receipt_sha256 = $suiteReceiptSha256
        started_at_local = $startedAt.ToString("o")
        completed_at_local = (Get-Date).ToString("o")
        quiet_merge_exit_code = $quietMergeExitCode
        quiet_merge_report = [ordered]@{
            path = $attemptQuietReportPath
            sha256 = $quietReportSha256
            payload = $quietReport
        }
        scripts = [ordered]@{
            attempt_merge = [ordered]@{
                path = [string]$manifest.orchestration.attempt_merge.path
                sha256 = [string]$manifest.orchestration.attempt_merge.sha256
            }
            quiet_merge = [ordered]@{
                path = [string]$manifest.orchestration.quiet_merge.path
                sha256 = $quietMergeLaunchSha256
            }
        }
        production_head = $productionHead
        origin_master = $originMaster
        origin_master_verified = $publicationAcknowledged
        source_tip_integrated = $sourceTipIntegrated
        capture_recovery_proved = $captureRecoveryProved
        capture = $captureProof
        documentation_transaction_recorded = $documentationTransactionRecorded
        suite_deadline_stop = $script:suiteDeadlineStopEvidence
        suite_pass_exit_grace = $script:suitePassExitGraceEvidence
        suite_stale_scheduler_result = $script:suiteStaleSchedulerResultEvidence
        failure = $failure
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    if ($null -eq $deferredMergeReceiptMarker -and
        (-not $preserveQuietReportForReconciliation -or $status -eq "MERGED_UNVERIFIED")) {
        Write-WeatherIntegrationImmutableJson -Path $mergeReceiptPath -Payload $receipt
    }
    elseif ($null -ne $deferredMergeReceiptMarker) {
        # A hard kill after the child committed can leave no child report. A
        # generic FAIL receipt would outrank and strand the stronger global
        # recovery journal. Leave the receipt path absent so reviewed
        # ActiveMarker reconciliation can hash-bind that exact durable state.
        Write-Warning (
            "Withholding generic FAIL receipt because exact post-commit active " +
            "marker $($deferredMergeReceiptMarker.Sha256) requires reconciliation."
        )
    }
    else {
        Write-Warning (
            "Withholding merge receipt because immutable pushed report " +
            "$quietReportSha256 is the only exact publication evidence; reconcile that report."
        )
    }
}

if ($status -ne "PASS") {
    if ($null -ne $deferredMergeReceiptMarker) {
        Write-Host "Integration attempt $($manifest.attempt_id) has an exact post-commit recovery marker and no terminal report. Do not close or retry it; reconcile the marker SHA256 $($deferredMergeReceiptMarker.Sha256)."
    }
    elseif ($preserveQuietReportForReconciliation -and $status -ne "MERGED_UNVERIFIED") {
        Write-Host "Integration attempt $($manifest.attempt_id) has an exact pushed report but production advanced before a matching receipt could be proved. Do not close or retry it; reconcile quiet-report SHA256 $quietReportSha256."
    }
    elseif ($status -eq "MERGED_UNVERIFIED") {
        Write-Host "Integration attempt $($manifest.attempt_id) was published but its final proof is incomplete. Do not close or retry it; reconcile production from this receipt."
    }
    else {
        Write-Host "Integration attempt $($manifest.attempt_id) merge failed. Its evidence is frozen; a repair must use a new attempt."
    }
    exit 1
}

Write-Host "Integration attempt $($manifest.attempt_id) merged, recovered, documented, and was acknowledged by origin/master."
exit 0
