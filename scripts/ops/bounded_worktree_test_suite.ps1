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
    [ValidateRange(60, 5400)]
    [int]$MaxRuntimeSeconds = 5400,
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
if (Test-Path -LiteralPath $LogPath) {
    throw "bounded suite refuses to append to or replace an existing log: $LogPath"
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

function Test-WeatherQualificationSensitiveEnvironmentName {
    param([Parameter(Mandatory = $true)][string]$Name)

    $upper = $Name.ToUpperInvariant()
    if ($upper -ceq "WEATHER_INTEGRATION_TEST_SECRET_POLICY") { return $false }
    if ($upper -in @(
        "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL",
        "UV_INDEX_URL", "UV_EXTRA_INDEX_URL",
        "GH_TOKEN", "GITHUB_TOKEN", "HF_TOKEN",
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "PIP_CERT",
        "PIP_PROXY", "PIP_TRUSTED_HOST",
        "SSH_AUTH_SOCK", "GIT_ASKPASS", "SSH_ASKPASS",
        "GIT_SSH", "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND"
    )) { return $true }
    if ($upper -match '^(POLYMARKET_|POLYMM_|OPENAI_|ANTHROPIC_|CLOUDFLARE_|AWS_|AZURE_|GOOGLE_|GCM_|GIT_SSL_)') {
        return $true
    }
    return $upper -match (
        '(?:^|_)(?:TOKEN|PASSWORD|PASSWD|SECRET|PRIVATE_KEY|API_KEY|' +
        'ACCESS_KEY|CLIENT_SECRET|CREDENTIALS?|CONNECTION_STRING|' +
        'URL|URI|DSN|AUTH|COOKIE|KEY|CERT)(?:$|_)'
    )
}

function Test-SuiteGitAmbientEnvironmentName {
    param([Parameter(Mandatory = $true)][string]$Name)

    $upper = $Name.ToUpperInvariant()
    return (
        $upper.StartsWith("GIT_") -or
        $upper.StartsWith("GCM_") -or
        $upper.StartsWith("SSH_") -or
        $upper -in @(
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
            "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "PAGER", "EDITOR", "VISUAL",
            "LC_ALL", "LANG"
        )
    )
}

function Get-SuiteGitExecutable {
    $commands = @(Get-Command git.exe -CommandType Application -All -ErrorAction Stop)
    $paths = New-Object System.Collections.Generic.List[string]
    foreach ($command in $commands) {
        if ([string]$command.CommandType -cne "Application" -or
            [string]::IsNullOrWhiteSpace([string]$command.Source)) {
            throw "bounded suite refuses a non-Application or pathless git.exe"
        }
        $path = [IO.Path]::GetFullPath([string]$command.Source)
        $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
        if ($item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "bounded suite refuses a directory or reparse-point git.exe"
        }
        if (@($paths | Where-Object {
            $_.Equals($path, [StringComparison]::OrdinalIgnoreCase)
        }).Count -eq 0) {
            $paths.Add($path)
        }
    }
    if ($paths.Count -ne 1) {
        throw "bounded suite requires exactly one distinct regular git.exe Application"
    }
    return [string]$paths[0]
}

function Invoke-SuiteCheckedLocalGit {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label,
        [int[]]$AllowedExitCodes = @(0)
    )

    $valid = switch ([string]$Arguments[0]) {
        "worktree" {
            $Arguments.Count -eq 3 -and
                [string]$Arguments[1] -ceq "list" -and
                [string]$Arguments[2] -ceq "--porcelain"
        }
        "rev-parse" {
            $Arguments.Count -eq 4 -and
                [string]$Arguments[1] -ceq "--verify" -and
                [string]$Arguments[2] -ceq "--end-of-options" -and
                [string]$Arguments[3] -match '\^\{commit\}$'
        }
        "status" {
            $Arguments.Count -eq 2 -and
                [string]$Arguments[1] -ceq "--porcelain"
        }
        "ls-files" {
            $Arguments.Count -eq 3 -and
                [string]$Arguments[1] -ceq "--" -and
                [string]$Arguments[2] -ceq "tests"
        }
        default { $false }
    }
    if (-not $valid) { throw "$Label refused an unsupported local Git query" }
    $resolvedRoot = [IO.Path]::GetFullPath($Root)
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        throw "$Label repository root is missing"
    }
    $gitExecutable = Get-SuiteGitExecutable
    $saved = @{}
    foreach ($name in @(
        [Environment]::GetEnvironmentVariables(
            [EnvironmentVariableTarget]::Process
        ).Keys | ForEach-Object { [string]$_ }
    )) {
        if ((Test-SuiteGitAmbientEnvironmentName -Name $name) -or
            (Test-WeatherQualificationSensitiveEnvironmentName -Name $name)) {
            $saved[$name] = [Environment]::GetEnvironmentVariable(
                $name,
                [EnvironmentVariableTarget]::Process
            )
            [Environment]::SetEnvironmentVariable(
                $name,
                $null,
                [EnvironmentVariableTarget]::Process
            )
        }
    }
    try {
        $env:GIT_NO_REPLACE_OBJECTS = "1"
        $env:GIT_OPTIONAL_LOCKS = "0"
        $env:GIT_ALLOW_PROTOCOL = "file"
        $env:GIT_TERMINAL_PROMPT = "0"
        $env:GIT_CONFIG_NOSYSTEM = "1"
        $env:GIT_CONFIG_SYSTEM = "NUL"
        $env:GIT_CONFIG_GLOBAL = "NUL"
        $env:GIT_CONFIG_COUNT = "0"
        $env:LC_ALL = "C"
        $env:LANG = "C"
        $gitArguments = @(
            "-C", $resolvedRoot,
            "-c", "core.fsmonitor=false",
            "-c", "core.hooksPath=NUL"
        ) + @($Arguments)
        $rows = @(& $gitExecutable @gitArguments 2>&1)
        $exitCode = [int]$LASTEXITCODE
        if ($exitCode -notin $AllowedExitCodes) {
            throw "$Label failed with Git exit $exitCode"
        }
        return [pscustomobject]@{
            ExitCode = $exitCode
            Rows = @($rows | ForEach-Object { [string]$_ })
            Executable = $gitExecutable
        }
    }
    finally {
        foreach ($name in @(
            [Environment]::GetEnvironmentVariables(
                [EnvironmentVariableTarget]::Process
            ).Keys | ForEach-Object { [string]$_ }
        )) {
            if ((Test-SuiteGitAmbientEnvironmentName -Name $name) -or
                (Test-WeatherQualificationSensitiveEnvironmentName -Name $name)) {
                [Environment]::SetEnvironmentVariable(
                    $name,
                    $null,
                    [EnvironmentVariableTarget]::Process
                )
            }
        }
        foreach ($name in @($saved.Keys)) {
            [Environment]::SetEnvironmentVariable(
                [string]$name,
                [string]$saved[$name],
                [EnvironmentVariableTarget]::Process
            )
        }
    }
}

function Write-SuiteLog {
    param([Parameter(Mandatory = $true)][string]$Message)

    if ($null -eq $suiteLogWriter) {
        throw "bounded suite log writer is not open"
    }
    $timestamp = ([datetime]::Now).ToString(
        "yyyy-MM-dd HH:mm:ss",
        [Globalization.CultureInfo]::InvariantCulture
    )
    $line = "{0}  {1}" -f $timestamp, $Message
    $suiteLogWriter.WriteLine($line)
    $suiteLogWriter.Flush()
    Write-Output $line
}

function Get-CommitPercent {
    $limit = (Get-Counter "\Memory\Commit Limit").CounterSamples[0].CookedValue
    $used = (Get-Counter "\Memory\Committed Bytes").CounterSamples[0].CookedValue
    if ($limit -le 0 -or $used -lt 0) { throw "invalid Windows commit counters" }
    return [math]::Round(100.0 * $used / $limit, 2)
}

function Assert-SuiteDiskHeadroom {
    $minimumFreeBytes = [int64]53687091200
    $volumeRoots = @(
        $RepoRoot,
        $WorktreeRoot,
        $LogPath,
        [IO.Path]::GetTempPath()
    ) | ForEach-Object {
        $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath([string]$_))
        if ([string]::IsNullOrWhiteSpace($root)) {
            throw "could not resolve a local volume for suite path: $_"
        }
        $root
    } | Sort-Object -Unique
    foreach ($root in $volumeRoots) {
        $drive = [IO.DriveInfo]::new($root)
        if (-not $drive.IsReady -or
            [int64]$drive.AvailableFreeSpace -lt $minimumFreeBytes) {
            throw (
                "bounded suite requires at least 50 GiB free on $root; " +
                "observed $([int64]$drive.AvailableFreeSpace) bytes"
            )
        }
    }
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

Assert-SuiteDiskHeadroom

$localNow = Get-Date
$localMinute = ($localNow.Hour * 60) + $localNow.Minute
if ($localMinute -ge (9 * 60) -or $localMinute -lt 30) {
    throw "bounded suite must start inside the 00:30-09:00 heavy-work window"
}
$hardStop = $localNow.Date.AddHours(9)
$runtimeStop = $localNow.AddSeconds($MaxRuntimeSeconds)
$suiteDeadline = if ($runtimeStop -lt $hardStop) { $runtimeStop } else { $hardStop }
$suiteRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()

$worktreeQuery = Invoke-SuiteCheckedLocalGit `
    -Root $RepoRoot -Arguments @("worktree", "list", "--porcelain") `
    -Label "registered worktree enumeration"
$registeredWorktrees = @(
    $worktreeQuery.Rows |
        Where-Object { $_ -like "worktree *" } |
        ForEach-Object { [IO.Path]::GetFullPath($_.Substring(9)) }
)
if (-not ($registeredWorktrees | Where-Object {
    $_.Equals($WorktreeRoot, [StringComparison]::OrdinalIgnoreCase)
})) {
    throw "WorktreeRoot is not registered by the production repository"
}

$worktreeTipQuery = Invoke-SuiteCheckedLocalGit `
    -Root $WorktreeRoot `
    -Arguments @("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}") `
    -Label "exact worktree tip query"
$branchTipQuery = Invoke-SuiteCheckedLocalGit `
    -Root $RepoRoot `
    -Arguments @("rev-parse", "--verify", "--end-of-options", "${BranchRef}^{commit}") `
    -Label "exact branch tip query"
$worktreeTip = ([string]$worktreeTipQuery.Rows[0]).Trim().ToLowerInvariant()
$branchTip = ([string]$branchTipQuery.Rows[0]).Trim().ToLowerInvariant()
if ($worktreeTipQuery.Rows.Count -ne 1 -or $branchTipQuery.Rows.Count -ne 1 -or
    $worktreeTip -ne $ExpectedTip -or $branchTip -ne $ExpectedTip) {
    throw "exact branch/worktree identity does not match ExpectedTip"
}
$dirtyQuery = Invoke-SuiteCheckedLocalGit `
    -Root $WorktreeRoot -Arguments @("status", "--porcelain") `
    -Label "initial exact worktree status"
$dirty = @($dirtyQuery.Rows)
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
$previousIntegrationTestCandidateRoot = $env:WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT
$previousIntegrationTestAllowedWriteRoot = $env:WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT
$previousGitAllowProtocol = $env:GIT_ALLOW_PROTOCOL
$previousGitTerminalPrompt = $env:GIT_TERMINAL_PROMPT
$previousPythonNoUserSite = $env:PYTHONNOUSERSITE
$previousPytestPluginAutoload = $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD
$previousPythonDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE
$previousPythonHashSeed = $env:PYTHONHASHSEED
$previousPythonUtf8 = $env:PYTHONUTF8
$previousPythonIoEncoding = $env:PYTHONIOENCODING
$previousSecretPolicy = $env:WEATHER_INTEGRATION_TEST_SECRET_POLICY
$scrubbedSensitiveEnvironment = @{}
$previousLocation = (Get-Location).Path
$suiteLogStream = $null
$suiteLogWriter = $null
$workloadLease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload "bounded_worktree_test_suite"
if ($null -eq $workloadLease) { throw "another heavyweight host workload owns data/logs/heavy_workload.lock" }
try {
    $suiteLogStream = [IO.File]::Open(
        $LogPath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read
    )
    $suiteLogWriter = New-Object IO.StreamWriter(
        $suiteLogStream,
        (New-Object Text.UTF8Encoding($false, $true)),
        4096,
        $true
    )
    $suiteLogWriter.AutoFlush = $true
    Write-SuiteLog "=== bounded worktree suite starting ==="
    Write-SuiteLog "worktree=$WorktreeRoot branch=$BranchRef expected_tip=$ExpectedTip"
    Write-SuiteLog "additional_python_roots=$($additionalPythonRoots.Count) require_live_sdk_contract=$($RequireLiveSdkContract.IsPresent) integration_preflight=$($IntegrationPreflight.IsPresent)"
    # Bootstrap the safety boundary needed to qualify the hardening revision
    # that will later make these controls part of the strict v2 contract. The
    # marker is set by already-adopted code before candidate Python starts, so
    # unmerged code is never allowed to grant itself external-I/O authority.
    foreach ($environmentName in @(
        [Environment]::GetEnvironmentVariables(
            [EnvironmentVariableTarget]::Process
        ).Keys | ForEach-Object { [string]$_ }
    )) {
        if (Test-WeatherQualificationSensitiveEnvironmentName `
                -Name $environmentName) {
            $scrubbedSensitiveEnvironment[$environmentName] =
                [Environment]::GetEnvironmentVariable(
                    $environmentName,
                    [EnvironmentVariableTarget]::Process
                )
            [Environment]::SetEnvironmentVariable(
                $environmentName,
                $null,
                [EnvironmentVariableTarget]::Process
            )
        }
    }
    $env:WEATHER_INTEGRATION_TEST_OFFLINE = "1"
    $env:WEATHER_INTEGRATION_TEST_SECRET_POLICY = "conservative_v1"
    $env:WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT = $RepoRoot
    $env:WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT = $WorktreeRoot
    $env:WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT = $null
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
    $importProbeCode = @(
        "import os, weather"
        "actual = os.path.normcase(os.path.realpath(weather.__file__))"
        "expected = os.path.normcase(os.path.realpath(os.environ['WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT']))"
        "raise SystemExit(0 if os.path.commonpath((actual, expected)) == expected else 3)"
    ) -join "; "
    $importProbeArguments = ConvertTo-ScheduledTaskArgumentString `
        -Tokens @("-c", $importProbeCode)
    $importProbeJob = $null
    $importProbe = $null
    try {
        $importProbeJob = New-WeatherKillOnCloseJob
        $importProbe = Start-WeatherProcessInJob `
            -Job $importProbeJob -FilePath $python `
            -ArgumentString $importProbeArguments `
            -WorkingDirectory $WorktreeRoot
        $importProbeDeadline = [Diagnostics.Stopwatch]::StartNew()
        while (-not $importProbe.WaitForExit(200)) {
            if ($importProbeDeadline.Elapsed.TotalSeconds -ge 30 -or
                $suiteRuntimeStopwatch.Elapsed.TotalSeconds -ge $MaxRuntimeSeconds -or
                (Get-Date) -ge $suiteDeadline) {
                throw "suite exact-worktree import probe exceeded its bounded runtime"
            }
        }
        $importProbe.WaitForExit()
        if ([int]$importProbe.ExitCode -ne 0) {
            throw (
                "suite imports do not resolve from the exact worktree; " +
                "contained probe exit=$([int]$importProbe.ExitCode)"
            )
        }
    }
    finally {
        if ($importProbeJob) { $importProbeJob.Dispose() }
        if ($importProbe) { $importProbe.Dispose() }
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
        $trackedTestFilesQuery = Invoke-SuiteCheckedLocalGit `
            -Root $WorktreeRoot -Arguments @("ls-files", "--", "tests") `
            -Label "tracked pytest inventory selection"
        $trackedTestFiles = @($trackedTestFilesQuery.Rows)
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
        if ($suiteRuntimeStopwatch.Elapsed.TotalSeconds -ge $MaxRuntimeSeconds -or
            (Get-Date) -ge $suiteDeadline) {
            throw "bounded suite reached its runtime or 09:00 hard teardown boundary"
        }
        Assert-SuiteDiskHeadroom
        Assert-HostAdmission -CommitCeiling $AbortCommitPercent -Phase "chunk-$ordinal"
        $junitPath = "{0}.{1}.chunk-{2:D3}.xml" -f $LogPath, $runTag, $ordinal
        $junitTempPath = Join-Path ([IO.Path]::GetTempPath()) (
            "weather-integration-junit-{0}.xml" -f [guid]::NewGuid().ToString("N")
        )
        if ((Test-Path -LiteralPath $junitTempPath) -or
            (Test-Path -LiteralPath $junitPath)) {
            throw "chunk $ordinal JUnit path unexpectedly already exists"
        }
        if (-not [string]::Equals(
            [IO.Path]::GetPathRoot($junitTempPath),
            [IO.Path]::GetPathRoot($junitPath),
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "chunk $ordinal JUnit temp/evidence paths must share one volume"
        }
        $tokens = @(
            "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--junitxml", $junitTempPath
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
                if ($suiteRuntimeStopwatch.Elapsed.TotalSeconds -ge $MaxRuntimeSeconds -or
                    (Get-Date) -ge $suiteDeadline) {
                    Write-SuiteLog "chunk $ordinal reached the suite deadline; killing its complete child tree"
                    throw "bounded suite reached its runtime or 09:00 hard teardown boundary"
                }
                Start-Sleep -Seconds 2
                $child.Refresh()
            }
            $child.WaitForExit()
            $exitCode = $child.ExitCode
            $junitTempItem = Get-Item -LiteralPath $junitTempPath `
                -Force -ErrorAction Stop
            if ($junitTempItem.PSIsContainer -or
                ($junitTempItem.Attributes -band
                    [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                [int64]$junitTempItem.Length -le 0 -or
                [int64]$junitTempItem.Length -gt 67108864) {
                throw "chunk $ordinal JUnit temp output is not one bounded regular file"
            }
            # The child cannot write production. The already-adopted parent
            # publishes the closed, same-volume file with create-if-absent
            # rename semantics; File.Move never replaces prior evidence.
            [IO.File]::Move($junitTempPath, $junitPath)
            $junitItem = Get-Item -LiteralPath $junitPath -Force -ErrorAction Stop
            if ($junitItem.PSIsContainer -or
                ($junitItem.Attributes -band
                    [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                [int64]$junitItem.Length -ne [int64]$junitTempItem.Length) {
                throw "chunk $ordinal published JUnit evidence is not exact"
            }
        }
        finally {
            if ($childJob) { $childJob.Dispose() }
            if ($child) { $child.Dispose() }
            if (Test-Path -LiteralPath $junitTempPath) {
                $leftoverJunit = Get-Item -LiteralPath $junitTempPath `
                    -Force -ErrorAction Stop
                if ($leftoverJunit.PSIsContainer -or
                    ($leftoverJunit.Attributes -band
                        [IO.FileAttributes]::ReparsePoint) -ne 0) {
                    throw "refusing unsafe JUnit temp cleanup: $junitTempPath"
                }
                Remove-Item -LiteralPath $junitTempPath -Force -ErrorAction Stop
            }
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
    $finalWorktreeTipQuery = Invoke-SuiteCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}") `
        -Label "final exact worktree tip query"
    $finalWorktreeTipRows = @($finalWorktreeTipQuery.Rows)
    if ($finalWorktreeTipRows.Count -ne 1) {
        throw "could not re-resolve the exact worktree tip after the final chunk"
    }
    $finalWorktreeTip = ([string]$finalWorktreeTipRows[0]).Trim().ToLowerInvariant()
    $finalBranchTipQuery = Invoke-SuiteCheckedLocalGit `
        -Root $RepoRoot `
        -Arguments @("rev-parse", "--verify", "--end-of-options", "${BranchRef}^{commit}") `
        -Label "final exact branch tip query"
    $finalBranchTipRows = @($finalBranchTipQuery.Rows)
    if ($finalBranchTipRows.Count -ne 1) {
        throw "could not re-resolve BranchRef after the final chunk"
    }
    $finalBranchTip = ([string]$finalBranchTipRows[0]).Trim().ToLowerInvariant()
    if ($finalWorktreeTip -ne $ExpectedTip -or $finalBranchTip -ne $ExpectedTip) {
        throw "exact branch/worktree identity changed while the suite was running"
    }
    $finalDirtyQuery = Invoke-SuiteCheckedLocalGit `
        -Root $WorktreeRoot -Arguments @("status", "--porcelain") `
        -Label "final exact worktree status"
    $finalDirty = @($finalDirtyQuery.Rows)
    if ($finalDirty.Count -ne 0) {
        throw "suite worktree changed while the suite was running"
    }
    if (-not $SmokeTest -and -not $IntegrationPreflight) {
        $finalTrackedRowsQuery = Invoke-SuiteCheckedLocalGit `
            -Root $WorktreeRoot -Arguments @("ls-files", "--", "tests") `
            -Label "final tracked pytest inventory"
        $finalTrackedRows = @($finalTrackedRowsQuery.Rows)
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
    try {
        if ($null -ne $suiteLogWriter) {
            $suiteLogWriter.Flush()
            $suiteLogWriter.Dispose()
        }
        if ($null -ne $suiteLogStream) {
            $suiteLogStream.Flush($true)
            $suiteLogStream.Dispose()
        }
    }
    finally {
        Set-Location -LiteralPath $previousLocation
        $env:PYTHONPATH = $previousPythonPath
        $env:WEATHER_REQUIRE_LIVE_SDK_CONTRACT = $previousLiveSdkRequirement
        $env:WEATHER_INTEGRATION_TEST_OFFLINE = $previousIntegrationTestOffline
        $env:WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT = $previousIntegrationTestProductionRoot
        $env:WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT = $previousIntegrationTestCandidateRoot
        $env:WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT = $previousIntegrationTestAllowedWriteRoot
        $env:GIT_ALLOW_PROTOCOL = $previousGitAllowProtocol
        $env:GIT_TERMINAL_PROMPT = $previousGitTerminalPrompt
        $env:PYTHONNOUSERSITE = $previousPythonNoUserSite
        $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = $previousPytestPluginAutoload
        $env:PYTHONDONTWRITEBYTECODE = $previousPythonDontWriteBytecode
        $env:PYTHONHASHSEED = $previousPythonHashSeed
        $env:PYTHONUTF8 = $previousPythonUtf8
        $env:PYTHONIOENCODING = $previousPythonIoEncoding
        $env:WEATHER_INTEGRATION_TEST_SECRET_POLICY = $previousSecretPolicy
        foreach ($environmentName in @($scrubbedSensitiveEnvironment.Keys)) {
            [Environment]::SetEnvironmentVariable(
                [string]$environmentName,
                [string]$scrubbedSensitiveEnvironment[$environmentName],
                [EnvironmentVariableTarget]::Process
            )
        }
        Exit-WeatherHeavyWorkloadLease -Lease $workloadLease
    }
}
