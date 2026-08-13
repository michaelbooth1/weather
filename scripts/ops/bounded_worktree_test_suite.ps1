# Run a full pytest suite from an exact, clean Git worktree without endangering
# production capture. This runner never merges, pushes, checks out, registers a
# task, or writes under production data/. Each pytest child is assigned before
# resume to a kill-on-close Windows Job so stopping the scheduled wrapper cannot
# leave a test process behind.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $true)]
    [string]$WorktreeRoot,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$ExpectedTip,
    [Parameter(Mandatory = $true)]
    [string]$BranchRef,
    [Parameter(Mandatory = $true)]
    [string]$LogPath,
    [ValidateRange(1, 25)]
    [int]$MaxFilesPerChunk = 20,
    [ValidateRange(1.0, 99.0)]
    [double]$StartCommitPercent = 64.0,
    [ValidateRange(1.0, 99.0)]
    [double]$AbortCommitPercent = 66.0,
    [switch]$PreflightOnly,
    [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$WorktreeRoot = (Resolve-Path -LiteralPath $WorktreeRoot -ErrorAction Stop).Path
$ExpectedTip = $ExpectedTip.ToLowerInvariant()
$LogPath = [IO.Path]::GetFullPath($LogPath)
$logParent = Split-Path -Parent $LogPath
if (-not (Test-Path -LiteralPath $logParent -PathType Container)) {
    throw "suite log parent does not exist: $logParent"
}
if ($StartCommitPercent -ge $AbortCommitPercent) {
    throw "StartCommitPercent must be lower than AbortCommitPercent"
}
if ($WorktreeRoot -eq $RepoRoot) {
    throw "bounded suite must use an isolated worktree, not production"
}

$contractScript = Join-Path $RepoRoot "scripts\ops\training_window_contract.ps1"
$jobScript = Join-Path $RepoRoot "scripts\ops\windows_kill_on_close_job.ps1"
foreach ($requiredScript in @($contractScript, $jobScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "required suite helper is missing: $requiredScript"
    }
}
. $contractScript
. $jobScript

function Write-SuiteLog {
    param([Parameter(Mandatory = $true)][string]$Message)

    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    Write-Output $line
}

function Get-CommitPercent {
    $limit = (Get-Counter "\Memory\Commit Limit").CounterSamples[0].CookedValue
    $used = (Get-Counter "\Memory\Committed Bytes").CounterSamples[0].CookedValue
    if ($limit -le 0 -or $used -lt 0) { throw "invalid Windows commit counters" }
    return [math]::Round(100.0 * $used / $limit, 2)
}

function Get-HealthyCaptureWorkerCount {
    $snapshotRoot = Join-Path $RepoRoot "data\snapshots"
    $specs = @(
        @{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 300 },
        @{ Status = "clob_loop_status.json"; Lock = ".clob_loop_status.json.writer.lock"; MaxAge = 180 },
        @{ Status = "observation_trigger_status.json"; Lock = ".observation_trigger_status.json.writer.lock"; MaxAge = 180 }
    )
    $healthy = 0
    foreach ($spec in $specs) {
        try {
            $status = Get-Content -LiteralPath (Join-Path $snapshotRoot $spec.Status) -Raw |
                ConvertFrom-Json
            $lock = Get-Content -LiteralPath (Join-Path $snapshotRoot $spec.Lock) -Raw |
                ConvertFrom-Json
            $pidValue = [int]$status.pid
            $ageSeconds = ((Get-Date) - [datetime]$status.last_heartbeat).TotalSeconds
            $alive = $null -ne (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
            if (
                $pidValue -gt 0 -and
                [int]$lock.pid -eq $pidValue -and
                $alive -and
                $ageSeconds -ge 0 -and
                $ageSeconds -le [double]$spec.MaxAge
            ) {
                $healthy++
            }
        }
        catch { }
    }
    return $healthy
}

function Assert-HostAdmission {
    param(
        [Parameter(Mandatory = $true)][double]$CommitCeiling,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    $workers = Get-HealthyCaptureWorkerCount
    $commit = Get-CommitPercent
    Write-SuiteLog "$Phase admission: capture_workers=$workers commit=$commit% ceiling=$CommitCeiling%"
    if ($workers -ne 3) {
        throw "$Phase refused: expected three healthy capture workers, found $workers"
    }
    if ($commit -gt $CommitCeiling) {
        throw "$Phase refused: commit $commit% exceeds $CommitCeiling%"
    }
}

Write-SuiteLog "=== bounded worktree suite starting ==="
Write-SuiteLog "worktree=$WorktreeRoot branch=$BranchRef expected_tip=$ExpectedTip"

$localHour = (Get-Date).Hour
if ($localHour -ge 12 -and $localHour -lt 18) {
    throw "bounded suite is prohibited during the 12:00-18:00 graded window"
}

$registeredWorktrees = @(
    & git -C $RepoRoot worktree list --porcelain |
        Where-Object { $_ -like "worktree *" } |
        ForEach-Object { [IO.Path]::GetFullPath($_.Substring(9)) }
)
if (-not ($registeredWorktrees | Where-Object {
    $_.Equals($WorktreeRoot, [StringComparison]::OrdinalIgnoreCase)
})) {
    throw "WorktreeRoot is not registered by the production repository"
}

$worktreeTip = (& git -C $WorktreeRoot rev-parse HEAD).Trim().ToLowerInvariant()
$branchTip = (& git -C $RepoRoot rev-parse $BranchRef).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $worktreeTip -ne $ExpectedTip -or $branchTip -ne $ExpectedTip) {
    throw "exact branch/worktree identity does not match ExpectedTip"
}
$dirty = @(& git -C $WorktreeRoot status --porcelain)
if ($dirty.Count -ne 0) {
    throw "suite worktree is dirty; exact-tip evidence would be ambiguous"
}

$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "production venv interpreter is missing: $python"
}
$python = (Resolve-Path -LiteralPath $python).Path
$previousPythonPath = $env:PYTHONPATH
$previousLocation = (Get-Location).Path
$env:PYTHONPATH = Join-Path $WorktreeRoot "src"
try {
    Set-Location -LiteralPath $WorktreeRoot
    $resolvedImport = (& $python -c "import weather; print(weather.__file__)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $resolvedImport.StartsWith(
        $WorktreeRoot,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "suite imports do not resolve from the exact worktree: $resolvedImport"
    }
    Assert-HostAdmission -CommitCeiling $StartCommitPercent -Phase "preflight"
    if ($PreflightOnly) {
        Write-SuiteLog "VERDICT: PREFLIGHT PASSED; no tests run"
        exit 0
    }

    $testRoot = Join-Path $WorktreeRoot "tests"
    $testFiles = @(
        Get-ChildItem -LiteralPath $testRoot -Recurse -File -Filter "test_*.py" |
            Sort-Object FullName |
            ForEach-Object {
                $_.FullName.Substring($WorktreeRoot.Length + 1).Replace("\", "/")
            }
    )
    if ($testFiles.Count -eq 0) { throw "no pytest files found in exact worktree" }
    if ($SmokeTest) {
        $testFiles = @($testFiles | Select-Object -First ([math]::Min(2, $testFiles.Count)))
    }

    $chunks = @()
    for ($offset = 0; $offset -lt $testFiles.Count; $offset += $MaxFilesPerChunk) {
        $last = [math]::Min($offset + $MaxFilesPerChunk - 1, $testFiles.Count - 1)
        $chunks += ,@($testFiles[$offset..$last])
    }
    Write-SuiteLog "planned chunks=$($chunks.Count) files=$($testFiles.Count) max_files=$MaxFilesPerChunk"

    $runTag = Get-Date -Format "yyyyMMddTHHmmss"
    $failedChunks = 0
    for ($index = 0; $index -lt $chunks.Count; $index++) {
        $ordinal = $index + 1
        Assert-HostAdmission -CommitCeiling $AbortCommitPercent -Phase "chunk-$ordinal"
        $junitPath = "{0}.{1}.chunk-{2:D3}.xml" -f $LogPath, $runTag, $ordinal
        $tokens = @(
            "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--junitxml", $junitPath
        ) + @($chunks[$index])
        $argumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
        Write-SuiteLog "chunk $ordinal/$($chunks.Count) starting files=$($chunks[$index].Count) junit=$junitPath"

        $childJob = $null
        $child = $null
        $exitCode = $null
        try {
            $childJob = New-WeatherKillOnCloseJob
            $child = Start-WeatherProcessInJob `
                -Job $childJob `
                -FilePath $python `
                -ArgumentString $argumentString `
                -WorkingDirectory $WorktreeRoot
            $child.WaitForExit()
            $exitCode = $child.ExitCode
        }
        finally {
            if ($childJob) { $childJob.Dispose() }
            if ($child) { $child.Dispose() }
        }
        Write-SuiteLog "chunk $ordinal/$($chunks.Count) exit=$exitCode"
        if ($exitCode -ne 0) { $failedChunks++ }
    }

    if ($failedChunks -ne 0) {
        Write-SuiteLog "VERDICT: $failedChunks CHUNK(S) FAILED; do not merge"
        exit 1
    }
    if ($SmokeTest) {
        Write-SuiteLog "VERDICT: SMOKE PASSED; full suite not run and merge is not authorized"
        exit 0
    }
    Write-SuiteLog "VERDICT: ALL CHUNKS PASSED ($($chunks.Count)/$($chunks.Count)); exact tip eligible for separate reviewed merge"
    exit 0
}
finally {
    Set-Location -LiteralPath $previousLocation
    $env:PYTHONPATH = $previousPythonPath
}
