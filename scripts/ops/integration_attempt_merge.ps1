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

    $attempt = $AttemptContract.Manifest
    $taskName = [string]$attempt.schedule.suite_task_name
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) { throw "Suite task not found: $taskName" }
    $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $taskInfo) { throw "Suite task info is unreadable: $taskName" }

    $actions = @($task.Actions)
    if ($actions.Count -ne 1) { throw "Suite task must have exactly one action." }
    $expectedTokens = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $SuiteScript,
        "-ManifestPath", $AttemptContract.ManifestPath,
        "-ExpectedManifestSha256", $AttemptContract.ManifestSha256
    )
    $expectedArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $expectedTokens
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].Execute) -Right $PowerShellExecutable)) {
        throw "Suite task executable does not match the repository registration contract."
    }
    if ([string]$actions[0].Arguments -ne $expectedArguments) {
        throw "Suite task arguments are not exactly bound to this manifest path and hash."
    }
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].WorkingDirectory) -Right ([string]$attempt.repo_root))) {
        throw "Suite task working directory is not the frozen repository root."
    }
    if ([string]$task.Principal.LogonType -ne "S4U" -or [string]$task.Principal.RunLevel -ne "Limited") {
        throw "Suite task must run under S4U with Limited privileges."
    }

    return [pscustomobject]@{ Task = $task; Info = $taskInfo }
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
    if ([datetime]$taskInfo.LastRunTime -lt (Get-Date).Date) {
        throw "Suite task did not run on the current local day."
    }
    if ([int]$taskInfo.LastTaskResult -ne 0) {
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
    $suiteAt = [datetime]::Parse([string]$manifest.schedule.suite_at_local)
    $deadline = $suiteAt.Date.AddMinutes(220)
    $lastNotice = [datetime]::MinValue
    while ($true) {
        $binding = Assert-WeatherIntegrationSuiteTaskBinding `
            -AttemptContract $AttemptContract `
            -SuiteScript $SuiteScript `
            -PowerShellExecutable $PowerShellExecutable
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
        if ([string]$decision.Action -eq "READY") { return }
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
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) { throw "Merge task not found: $taskName" }
    $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $taskInfo -or [datetime]$taskInfo.LastRunTime -lt (Get-Date).Date) {
        throw "Merge task did not start on the current local day."
    }
    if ([string]$task.State -ne "Running") {
        throw "Integration-attempt merge may run only as its registered one-shot task."
    }
    $actions = @($task.Actions)
    if ($actions.Count -ne 1) { throw "Merge task must have exactly one action." }
    $expectedTokens = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $MergeScript,
        "-ManifestPath", $AttemptContract.ManifestPath,
        "-ExpectedManifestSha256", $AttemptContract.ManifestSha256
    )
    $expectedArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $expectedTokens
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].Execute) -Right $PowerShellExecutable) -or
        [string]$actions[0].Arguments -ne $expectedArguments -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].WorkingDirectory) -Right ([string]$attempt.repo_root))) {
        throw "Merge task action is not exactly bound to this manifest path and hash."
    }
    if ([string]$task.Principal.LogonType -ne "S4U" -or [string]$task.Principal.RunLevel -ne "Limited") {
        throw "Merge task must run under S4U with Limited privileges."
    }
}

function Invoke-WeatherQuietMergeChild {
    param(
        [Parameter(Mandatory = $true)][string]$QuietMergeScript,
        [Parameter(Mandatory = $true)][string]$PowerShellExecutable,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Branch,
        [Parameter(Mandatory = $true)][string]$ExpectedTip,
        [Parameter(Mandatory = $true)][string]$ExpectedBaseline
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

$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract
$manifest = $contract.Manifest
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
$quietReportPath = Join-Path $repoRoot "data\alerts\quiet_window_merge_last.json"
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

    $quietMergeExitCode = Invoke-WeatherQuietMergeChild `
        -QuietMergeScript $quietMergeScript `
        -PowerShellExecutable $powerShellExecutable `
        -RepoRoot $repoRoot `
        -Branch ([string]$manifest.branch_ref) `
        -ExpectedTip ([string]$manifest.expected_tip) `
        -ExpectedBaseline ([string]$manifest.baseline.master)
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
    if (-not [bool]$quietReport.ok -or [string]$quietReport.stage -ne "pushed") {
        throw "Quiet merge report is not a pushed success."
    }
    if ([string]$quietReport.branch -ne [string]$manifest.branch_ref -or
        [string]$quietReport.expected_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.expected_baseline -ne [string]$manifest.baseline.master -or
        [string]$quietReport.resolved_branch_tip -ne [string]$manifest.expected_tip) {
        throw "Quiet merge report identity does not match this attempt."
    }
    $documentationTransactionRecorded = @($quietReport.log | Where-Object {
        [string]$_ -like "*documentation transaction recorded*"
    }).Count -gt 0
    if (-not $documentationTransactionRecorded) {
        throw "Quiet merge report does not prove the documentation transaction was recorded."
    }
    Write-WeatherIntegrationImmutableJson -Path $attemptQuietReportPath -Payload $quietReport
    $quietReportSha256 = Get-WeatherIntegrationFileSha256 -Path $attemptQuietReportPath

    $productionHead = (Invoke-WeatherIntegrationGitLine -Root $repoRoot -Arguments @("rev-parse", "master")).ToLowerInvariant()
    $originMaster = (Invoke-WeatherIntegrationGitLine -Root $repoRoot -Arguments @("rev-parse", "origin/master")).ToLowerInvariant()
    if ($productionHead -ne $originMaster) {
        throw "Production master and origin/master do not acknowledge the same integration commit."
    }
    & git -C $repoRoot merge-base --is-ancestor ([string]$manifest.expected_tip) $productionHead
    if ($LASTEXITCODE -ne 0) {
        throw "The frozen source tip is not an ancestor of the published integration commit."
    }

    $captureRaw = @(& $python -m weather.operations.capture_recovery_check --repo-root $repoRoot --json)
    $captureExitCode = $LASTEXITCODE
    $captureProof = (($captureRaw -join "`n") | ConvertFrom-Json)
    if ($captureExitCode -ne 0 -or -not [bool]$captureProof.ok -or @($captureProof.workers).Count -ne 3) {
        throw "Post-publication capture recovery proof is not healthy for all three workers."
    }
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
                Write-WeatherIntegrationImmutableJson -Path $attemptQuietReportPath -Payload $quietReport
                $quietReportSha256 = Get-WeatherIntegrationFileSha256 -Path $attemptQuietReportPath
            }
        }
        catch { }
    }
}
finally {
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
                sha256 = [string]$manifest.orchestration.quiet_merge.sha256
            }
        }
        production_head = $productionHead
        origin_master = $originMaster
        origin_master_verified = ($status -eq "PASS" -and $productionHead -eq $originMaster)
        source_tip_integrated = ($status -eq "PASS")
        capture_recovery_proved = ($status -eq "PASS")
        capture = $captureProof
        documentation_transaction_recorded = $documentationTransactionRecorded
        failure = $failure
        credential_value_read = $false
        live_exchange_mutation_attempted = $false
    }
    Write-WeatherIntegrationImmutableJson -Path $mergeReceiptPath -Payload $receipt
}

if ($status -ne "PASS") {
    Write-Host "Integration attempt $($manifest.attempt_id) merge failed. Its evidence is frozen; a repair must use a new attempt."
    exit 1
}

Write-Host "Integration attempt $($manifest.attempt_id) merged, recovered, documented, and was acknowledged by origin/master."
exit 0
