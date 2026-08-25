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
    [string]$AdditionalPythonPath = "",
    [switch]$RequireLiveSdkContract,
    [switch]$PreflightOnly,
    [switch]$SmokeTest,
    [switch]$IntegrationPreflight
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
$selectedModes = @(@($PreflightOnly.IsPresent, $SmokeTest.IsPresent, $IntegrationPreflight.IsPresent) |
    Where-Object { $_ })
if ($selectedModes.Count -gt 1) {
    throw "PreflightOnly, SmokeTest, and IntegrationPreflight are mutually exclusive."
}
if ($WorktreeRoot -eq $RepoRoot) {
    throw "bounded suite must use an isolated worktree, not production"
}
$additionalPythonRoots = @()
if (-not [string]::IsNullOrWhiteSpace($AdditionalPythonPath)) {
    $additionalPythonRoots = @(
        $AdditionalPythonPath.Split([IO.Path]::PathSeparator) |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object {
                (Resolve-Path -LiteralPath $_ -ErrorAction Stop).Path
            }
    )
    if ($additionalPythonRoots.Count -eq 0 -or @(
        $additionalPythonRoots | Where-Object {
            -not (Test-Path -LiteralPath $_ -PathType Container)
        }
    ).Count -ne 0) {
        throw "AdditionalPythonPath must contain only existing directories"
    }
}

$contractScript = Join-Path $RepoRoot "scripts\ops\training_window_contract.ps1"
$jobScript = Join-Path $RepoRoot "scripts\ops\windows_kill_on_close_job.ps1"
$workloadLeaseScript = Join-Path $RepoRoot "scripts\ops\workload_admission.ps1"
foreach ($requiredScript in @($contractScript, $jobScript, $workloadLeaseScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "required suite helper is missing: $requiredScript"
    }
}
. $contractScript
. $jobScript
. $workloadLeaseScript

function Write-SuiteLog {
    param([Parameter(Mandatory = $true)][string]$Message)

    $timestamp = ([datetime]::Now).ToString(
        "yyyy-MM-dd HH:mm:ss",
        [Globalization.CultureInfo]::InvariantCulture
    )
    $line = "{0}  {1}" -f $timestamp, $Message
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
        # Snapshot normally sleeps for almost its 10-minute cadence. Keep this
        # below the 15-minute streak limit without rejecting a healthy sleeper.
        @{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 720 },
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
Write-SuiteLog "additional_python_roots=$($additionalPythonRoots.Count) require_live_sdk_contract=$($RequireLiveSdkContract.IsPresent) integration_preflight=$($IntegrationPreflight.IsPresent)"

$localNow = Get-Date
$localMinute = ($localNow.Hour * 60) + $localNow.Minute
if ($localMinute -ge (9 * 60) -or $localMinute -lt 30) {
    throw "bounded suite must start inside the 00:30-09:00 heavy-work window"
}
$hardStop = $localNow.Date.AddHours(9)

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
$previousLiveSdkRequirement = $env:WEATHER_REQUIRE_LIVE_SDK_CONTRACT
$previousIntegrationTestOffline = $env:WEATHER_INTEGRATION_TEST_OFFLINE
$previousIntegrationTestProductionRoot = $env:WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT
$previousGitAllowProtocol = $env:GIT_ALLOW_PROTOCOL
$previousGitTerminalPrompt = $env:GIT_TERMINAL_PROMPT
$previousPythonNoUserSite = $env:PYTHONNOUSERSITE
$previousPytestPluginAutoload = $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD
$previousPythonDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE
$previousPythonHashSeed = $env:PYTHONHASHSEED
$previousPythonUtf8 = $env:PYTHONUTF8
$previousPythonIoEncoding = $env:PYTHONIOENCODING
$previousLocation = (Get-Location).Path
$workloadLease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload "bounded_worktree_test_suite"
if ($null -eq $workloadLease) { throw "another heavyweight host workload owns data/logs/heavy_workload.lock" }
try {
    # Bootstrap the safety boundary needed to qualify the hardening revision
    # that will later make these controls part of the strict v2 contract. The
    # marker is set by already-adopted code before candidate Python starts, so
    # unmerged code is never allowed to grant itself external-I/O authority.
    $env:WEATHER_INTEGRATION_TEST_OFFLINE = "1"
    $env:WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT = $RepoRoot
    $env:GIT_ALLOW_PROTOCOL = "file"
    $env:GIT_TERMINAL_PROMPT = "0"
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTHONHASHSEED = "0"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONPATH = Join-Path $WorktreeRoot "src"
    $env:PYTHONPATH = @(
        $WorktreeRoot
        $env:PYTHONPATH
    ) -join [IO.Path]::PathSeparator
    if ($additionalPythonRoots.Count -gt 0) {
        $env:PYTHONPATH = @(
            $env:PYTHONPATH
            $additionalPythonRoots
        ) -join [IO.Path]::PathSeparator
    }
    if ($RequireLiveSdkContract) {
        $env:WEATHER_REQUIRE_LIVE_SDK_CONTRACT = "1"
    }
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

    if ($IntegrationPreflight) {
        # Keep the deterministic ratchets that have repeatedly caught cumulative-tip
        # integration defects ahead of the expensive full suite. This list is
        # repository-owned and deliberately contains no network or live-data tests.
        $testFiles = @(
            "tests/operations/test_schema_registry.py",
            "tests/operations/test_module_size_audit.py",
            "tests/operations/test_import_architecture.py",
            "tests/operations/test_agent_docs_audit.py",
            "tests/operations/test_bounded_worktree_test_suite_script.py",
            "tests/operations/test_integration_attempt_scripts.py",
            "tests/operations/test_integration_attempt_evidence_recovery_hardening.py",
            "tests/operations/test_integration_attempt_registration_safety.py",
            "tests/operations/test_boot_recovery_script.py",
            "tests/operations/test_register_boot_recovery_script.py",
            "tests/operations/test_suite_gated_quiet_merge_script.py",
            "tests/operations/test_quiet_window_merge_script.py",
            "tests/operations/test_host_task_wrappers.py",
            "tests/reporting/test_roadmap_backlog.py",
            "tests/app/test_app_roadmap.py"
        )
        foreach ($relativeTestPath in $testFiles) {
            $absoluteTestPath = Join-Path $WorktreeRoot $relativeTestPath.Replace("/", "\")
            if (-not (Test-Path -LiteralPath $absoluteTestPath -PathType Leaf)) {
                throw "integration preflight ratchet is missing: $relativeTestPath"
            }
        }
    }
    else {
        $trackedTestFiles = @(& git -C $WorktreeRoot ls-files -- tests)
        if ($LASTEXITCODE -ne 0) {
            throw "could not enumerate tracked pytest files from the exact worktree"
        }
        $testFiles = @(
            $trackedTestFiles |
                ForEach-Object { ([string]$_).Replace("\", "/") } |
                Where-Object { $_ -match '^tests/(?:.*/)?test_[^/]*\.py$' } |
                Sort-Object
        )
    }
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
        if ((Get-Date) -ge $hardStop) {
            throw "bounded suite reached the 09:00 hard teardown boundary"
        }
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
            while (-not $child.HasExited) {
                if ((Get-Date) -ge $hardStop) {
                    Write-SuiteLog "chunk $ordinal reached 09:00; killing its complete child tree"
                    throw "bounded suite reached the 09:00 hard teardown boundary"
                }
                Start-Sleep -Seconds 2
                $child.Refresh()
            }
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

    # The worktree, movable branch ref, and tracked test inventory can change
    # while the chunks run. Re-prove all three after the final child exits and
    # before emitting the sole merge-eligible terminal verdict.
    $finalWorktreeTipRows = @(& git -C $WorktreeRoot rev-parse HEAD)
    if ($LASTEXITCODE -ne 0 -or $finalWorktreeTipRows.Count -ne 1) {
        throw "could not re-resolve the exact worktree tip after the final chunk"
    }
    $finalWorktreeTip = ([string]$finalWorktreeTipRows[0]).Trim().ToLowerInvariant()
    $finalBranchTipRows = @(& git -C $RepoRoot rev-parse $BranchRef)
    if ($LASTEXITCODE -ne 0 -or $finalBranchTipRows.Count -ne 1) {
        throw "could not re-resolve BranchRef after the final chunk"
    }
    $finalBranchTip = ([string]$finalBranchTipRows[0]).Trim().ToLowerInvariant()
    if ($finalWorktreeTip -ne $ExpectedTip -or $finalBranchTip -ne $ExpectedTip) {
        throw "exact branch/worktree identity changed while the suite was running"
    }
    $finalDirty = @(& git -C $WorktreeRoot status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $finalDirty.Count -ne 0) {
        throw "suite worktree changed while the suite was running"
    }
    if (-not $SmokeTest -and -not $IntegrationPreflight) {
        $finalTrackedRows = @(& git -C $WorktreeRoot ls-files -- tests)
        if ($LASTEXITCODE -ne 0) {
            throw "could not re-enumerate tracked pytest files after the final chunk"
        }
        $finalTestFiles = @(
            $finalTrackedRows |
                ForEach-Object { ([string]$_).Replace("\", "/") } |
                Where-Object { $_ -match '^tests/(?:.*/)?test_[^/]*\.py$' } |
                Sort-Object
        )
        if ($finalTestFiles.Count -ne $testFiles.Count -or
            @(Compare-Object -ReferenceObject @($testFiles) -DifferenceObject @($finalTestFiles)).Count -ne 0) {
            throw "tracked pytest inventory changed while the suite was running"
        }
    }
    Write-SuiteLog "final exact-tip, clean-worktree, and test-inventory recheck passed"

    if ($SmokeTest) {
        Write-SuiteLog "VERDICT: SMOKE PASSED; full suite not run and merge is not authorized"
        exit 0
    }
    if ($IntegrationPreflight) {
        Write-SuiteLog "VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge is not authorized"
        exit 0
    }
    Write-SuiteLog "VERDICT: ALL CHUNKS PASSED ($($chunks.Count)/$($chunks.Count)); exact tip eligible for separate reviewed merge"
    exit 0
}
finally {
    Set-Location -LiteralPath $previousLocation
    $env:PYTHONPATH = $previousPythonPath
    $env:WEATHER_REQUIRE_LIVE_SDK_CONTRACT = $previousLiveSdkRequirement
    $env:WEATHER_INTEGRATION_TEST_OFFLINE = $previousIntegrationTestOffline
    $env:WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT = $previousIntegrationTestProductionRoot
    $env:GIT_ALLOW_PROTOCOL = $previousGitAllowProtocol
    $env:GIT_TERMINAL_PROMPT = $previousGitTerminalPrompt
    $env:PYTHONNOUSERSITE = $previousPythonNoUserSite
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = $previousPytestPluginAutoload
    $env:PYTHONDONTWRITEBYTECODE = $previousPythonDontWriteBytecode
    $env:PYTHONHASHSEED = $previousPythonHashSeed
    $env:PYTHONUTF8 = $previousPythonUtf8
    $env:PYTHONIOENCODING = $previousPythonIoEncoding
    Exit-WeatherHeavyWorkloadLease -Lease $workloadLease
}
