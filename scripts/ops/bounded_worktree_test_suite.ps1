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
    [int]$MaxFilesPerChunk = 25,
    [ValidateRange(1.0, 99.0)]
    [double]$StartCommitPercent = 64.0,
    [ValidateRange(1.0, 99.0)]
    [double]$AbortCommitPercent = 66.0,
    [ValidateRange(60, 5400)]
    [int]$MaxRuntimeSeconds = 5400,
    [string]$AdditionalPythonPath = "",
    [string]$GitExecutablePath = "",
    [string]$ExpectedGitExecutableSha256 = "",
    [string]$ExpectedGitExecutableFileVersion = "",
    [switch]$RequireLiveSdkContract,
    [switch]$PreflightOnly,
    [switch]$SmokeTest,
    [switch]$IntegrationPreflight,
    # L5 (owner decision 2026-10-06): the reconciler execution file runs only when the
    # tip touches its surface (scripts/ops/reconciler_surface.ps1). The predicate needs
    # the base this tip is measured against; without one the file is always included,
    # so callers that pass nothing (integration attempts) run exactly as before.
    [ValidatePattern("^$|^[0-9a-fA-F]{40}$")]
    [string]$ReconcilerSurfaceBase = "",
    # Forces the reconciler file in (the once-a-night run on the final tip).
    [switch]$IncludeReconciler,
    # Host Python upgrade prep: an absolute path to a staged venv's python.exe
    # that runs the probe and every chunk instead of RepoRoot\venv. RepoRoot
    # still owns admission, capture state and the shared heavy-workload lease.
    # Empty (the default) keeps the production venv exactly as before.
    [string]$InterpreterPath = "",
    # With -InterpreterPath only: the exact sys.version_info triple the staged
    # interpreter must report (for example 3.11.9). Empty accepts any 3.11.x.
    [ValidatePattern("^$|^[0-9]+\.[0-9]+\.[0-9]+$")]
    [string]$ExpectedInterpreterVersion = ""
)

$ErrorActionPreference = "Stop"
$launchJournal = $null
$launchStatus = "FAIL"
$launchFailure = $null
trap {
    Close-WeatherLaunchDiagnostics -Journal $launchJournal -Status "FAIL" -Failure $_
    throw
}
. (Join-Path $PSScriptRoot "integration_launch_diagnostics.ps1")
$launchJournal = New-WeatherLaunchDiagnostics `
    -Path ($LogPath + ".bootstrap.jsonl") -Operation "bounded_suite" `
    -ScriptPath $PSCommandPath -Binding ([ordered]@{
        expected_tip = $ExpectedTip
        branch_ref = $BranchRef
        log_path = $LogPath
    })
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
if (-not [string]::IsNullOrEmpty($InterpreterPath) -or
    -not [string]::IsNullOrEmpty($ExpectedInterpreterVersion)) {
    # Interpreter override only: the probe's sidecar outputs are create-new, so
    # a retry with the same LogPath gets this clean refusal instead.
    if ([string]::IsNullOrEmpty($InterpreterPath)) {
        throw "ExpectedInterpreterVersion requires InterpreterPath"
    }
    foreach ($interpreterProbeSidecar in @(
        ($LogPath + ".interpreter.stdout.log"), ($LogPath + ".interpreter.stderr.log")
    )) {
        if (Test-Path -LiteralPath $interpreterProbeSidecar) {
            throw "bounded suite refuses to replace an existing interpreter probe output: $interpreterProbeSidecar"
        }
    }
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
# A candidate may qualify before production has this new read-only helper.
# Admission, containment and workload ownership still come from the production root.
$gitIdentityScript = Join-Path $PSScriptRoot "git_executable_identity.ps1"
foreach ($requiredScript in @($contractScript, $jobScript, $workloadLeaseScript, $gitIdentityScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "required suite helper is missing: $requiredScript"
    }
}
. $contractScript
. $jobScript
. $workloadLeaseScript
. $gitIdentityScript

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
    param(
        [string]$Path = "",
        [string]$ExpectedSha256 = "",
        [string]$ExpectedFileVersion = ""
    )

    if (-not [string]::IsNullOrWhiteSpace($Path) -or
        -not [string]::IsNullOrWhiteSpace($ExpectedSha256) -or
        -not [string]::IsNullOrWhiteSpace($ExpectedFileVersion)) {
        return Assert-WeatherGitExecutableIdentity -Identity ([pscustomobject]@{
            path = $Path
            sha256 = $ExpectedSha256
            file_version = $ExpectedFileVersion
        })
    }
    # Legacy direct invocations retain their strict PATH resolution. New
    # immutable attempts always pass a reviewed path/hash/version binding.
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
        "diff" {
            $Arguments.Count -eq 5 -and
                [string]$Arguments[1] -ceq "--name-only" -and
                [string]$Arguments[2] -ceq "--no-renames" -and
                [string]$Arguments[3] -cmatch '^[0-9a-f]{40}$' -and
                [string]$Arguments[4] -cmatch '^[0-9a-f]{40}$'
        }
        default { $false }
    }
    if (-not $valid) { throw "$Label refused an unsupported local Git query" }
    $resolvedRoot = [IO.Path]::GetFullPath($Root)
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        throw "$Label repository root is missing"
    }
    $gitExecutable = Get-SuiteGitExecutable `
        -Path $GitExecutablePath `
        -ExpectedSha256 $ExpectedGitExecutableSha256 `
        -ExpectedFileVersion $ExpectedGitExecutableFileVersion
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

function Enter-SuiteChunkTemp {
    param([Parameter(Mandatory = $true)][string]$Root)

    $saved = @{ TEMP = $env:TEMP; TMP = $env:TMP }
    $childTemp = Join-Path $Root "temp"
    New-Item -ItemType Directory -Path $childTemp -ErrorAction Stop | Out-Null
    $env:TEMP = $childTemp
    $env:TMP = $childTemp
    return $saved
}

function Exit-SuiteChunkTemp {
    param([Parameter(Mandatory = $true)][hashtable]$Saved)

    $env:TEMP = $Saved.TEMP
    $env:TMP = $Saved.TMP
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

function Read-SuiteFileTimingTable {
    # The exact-tip worktree carries a checked-in per-file timing table. It only
    # decides which files share a chunk; it can never add, drop or duplicate a
    # file, raise the per-chunk cap, or change the chunk count. A malformed table
    # fails closed; an absent table (older candidates) packs every file at the
    # same weight.
    param([Parameter(Mandatory = $true)][string]$Path)

    $seconds = New-Object 'System.Collections.Generic.Dictionary[string,double]' ([StringComparer]::Ordinal)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]@{
            Present = $false; Sha256 = ""; DefaultSeconds = [double]1.0; Seconds = $seconds
        }
    }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        [int64]$item.Length -le 0 -or [int64]$item.Length -gt 1048576) {
        throw "suite file timing table is not one bounded regular file: $Path"
    }
    $bytes = [IO.File]::ReadAllBytes($item.FullName)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = (($sha256.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join "")
    }
    finally { $sha256.Dispose() }
    try {
        $table = (New-Object Text.UTF8Encoding($false, $true)).GetString($bytes) |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch { throw "suite file timing table is not valid UTF-8 JSON: $Path" }
    $numberTypes = @([int], [long], [double], [decimal])
    if ($null -eq $table -or
        @($table.PSObject.Properties.Name) -notcontains "format_version" -or
        [string]$table.format_version -cne "1" -or
        @($table.PSObject.Properties.Name) -notcontains "default_seconds" -or
        @($table.PSObject.Properties.Name) -notcontains "files" -or
        $null -eq $table.files -or
        $table.files -isnot [Management.Automation.PSCustomObject]) {
        throw "suite file timing table does not match format_version 1: $Path"
    }
    $default = $table.default_seconds
    if ($null -eq $default -or @($numberTypes | Where-Object { $default -is $_ }).Count -eq 0 -or
        [double]$default -le 0 -or [double]$default -gt 3600) {
        throw "suite file timing table default_seconds must be in (0, 3600]"
    }
    foreach ($property in @($table.files.PSObject.Properties)) {
        $value = $property.Value
        if ([string]$property.Name -notmatch '^tests/(?:.*/)?test_[^/]*\.py$' -or
            $null -eq $value -or @($numberTypes | Where-Object { $value -is $_ }).Count -eq 0 -or
            [double]$value -lt 0 -or [double]$value -gt 86400 -or
            $seconds.ContainsKey([string]$property.Name)) {
            throw "suite file timing table has an invalid entry: $($property.Name)"
        }
        $seconds[[string]$property.Name] = [double]$value
    }
    return [pscustomobject]@{
        Present = $true; Sha256 = $digest; DefaultSeconds = [double]$default; Seconds = $seconds
    }
}

function Get-SuiteTimePackedChunks {
    # Deterministic longest-processing-time packing under a hard file cap. The
    # chunk count stays ceil(files / MaxFilesPerChunk), exactly as the integration
    # manifest expects; only the grouping changes so chunk wall times even out.
    # Ties break on file count, then chunk index; files sort by weight then
    # ordinal path, and each chunk lists its files in ordinal path order.
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$TestFiles,
        [Parameter(Mandatory = $true)][ValidateRange(1, 25)][int]$MaxFilesPerChunk,
        [Parameter(Mandatory = $true)][object]$TimingTable
    )

    $fileCount = $TestFiles.Count
    if ($fileCount -eq 0) { return ,@() }
    $chunkCount = [int][math]::Ceiling($fileCount / [double]$MaxFilesPerChunk)
    $weighted = New-Object 'System.Collections.Generic.List[object]'
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    foreach ($file in $TestFiles) {
        if (-not $seen.Add([string]$file)) { throw "suite test inventory repeats a file: $file" }
        $value = [double]$TimingTable.DefaultSeconds
        if ($TimingTable.Seconds.ContainsKey([string]$file)) { $value = $TimingTable.Seconds[[string]$file] }
        $weighted.Add([pscustomobject]@{
            Path = [string]$file
            Milliseconds = [int64][math]::Round($value * 1000.0, [MidpointRounding]::AwayFromZero)
        })
    }
    $weighted.Sort([Comparison[object]]{
        param($left, $right)
        $byWeight = $right.Milliseconds.CompareTo($left.Milliseconds)
        if ($byWeight -ne 0) { return $byWeight }
        return [string]::CompareOrdinal($left.Path, $right.Path)
    })
    $loads = New-Object 'int64[]' $chunkCount
    $members = @()
    for ($index = 0; $index -lt $chunkCount; $index++) {
        $members += ,(New-Object 'System.Collections.Generic.List[string]')
    }
    foreach ($entry in $weighted) {
        $target = -1
        for ($index = 0; $index -lt $chunkCount; $index++) {
            if ($members[$index].Count -ge $MaxFilesPerChunk) { continue }
            if ($target -lt 0 -or
                $loads[$index] -lt $loads[$target] -or
                ($loads[$index] -eq $loads[$target] -and
                    $members[$index].Count -lt $members[$target].Count)) {
                $target = $index
            }
        }
        if ($target -lt 0) { throw "suite chunk packing ran out of capacity" }
        $members[$target].Add($entry.Path)
        $loads[$target] += $entry.Milliseconds
    }
    $chunks = @()
    $placed = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    for ($index = 0; $index -lt $chunkCount; $index++) {
        $chunkFiles = $members[$index].ToArray()
        [Array]::Sort($chunkFiles, [StringComparer]::Ordinal)
        if ($chunkFiles.Count -lt 1 -or $chunkFiles.Count -gt $MaxFilesPerChunk) {
            throw "suite chunk packing produced a chunk outside 1..$MaxFilesPerChunk files"
        }
        foreach ($file in $chunkFiles) {
            if (-not $placed.Add($file)) { throw "suite chunk packing placed a file twice: $file" }
        }
        $chunks += ,@($chunkFiles)
    }
    if ($placed.Count -ne $fileCount -or $chunks.Count -ne $chunkCount) {
        throw "suite chunk packing did not place every test file exactly once"
    }
    return ,$chunks
}

function Get-SuiteDosDeviceTarget {
    # The DOS device a drive letter names: \Device\... for a real volume,
    # \??\<path> for a subst letter. $null when the letter is not defined.
    param([Parameter(Mandatory = $true)][string]$DriveName)

    if (-not ('Weather.Operations.SuiteDosDevice' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
namespace Weather.Operations {
    public static class SuiteDosDevice {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint QueryDosDeviceW(string deviceName, StringBuilder targetPath, int max);
        public static string Query(string deviceName) {
            StringBuilder buffer = new StringBuilder(32768);
            uint length = QueryDosDeviceW(deviceName, buffer, buffer.Capacity);
            if (length == 0) { return null; }
            return buffer.ToString();
        }
    }
}
'@
    }
    return [Weather.Operations.SuiteDosDevice]::Query($DriveName)
}

function Assert-SuiteInterpreterLocalDrive {
    # A local fixed volume: DriveType Fixed and a \Device\ DOS target, so a
    # mapped network letter and a subst letter (\??\<path>) are both refused.
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $root = [IO.Path]::GetPathRoot($Path)
    $driveType = $null
    try { $driveType = ([IO.DriveInfo]::new($root)).DriveType } catch { }
    $dosTarget = $null
    try { $dosTarget = Get-SuiteDosDeviceTarget -DriveName $root.Substring(0, 2) } catch { }
    if ($driveType -ne [IO.DriveType]::Fixed -or $null -eq $dosTarget -or
        -not $dosTarget.StartsWith('\Device\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must be on a local fixed drive, not a mapped or subst letter: $root ($driveType, $dosTarget)"
    }
}

function Assert-SuiteInterpreterLocalRegularFile {
    # A regular file with no reparse point on the file or any parent directory.
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $root = [IO.Path]::GetPathRoot($Path)
    $cursor = $root
    $item = $null
    foreach ($component in $Path.Substring($root.Length).Split(
        [char[]]@('\'), [StringSplitOptions]::RemoveEmptyEntries
    )) {
        $cursor = Join-Path $cursor $component
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($null -eq $item) { throw "$Label does not exist: $Path" }
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label traverses a reparse point: $cursor"
        }
    }
    if ($null -eq $item -or $item.PSIsContainer) {
        throw "$Label is not a regular file: $Path"
    }
}

function Get-SuiteInterpreterOverrideHashes {
    # The bytes an override run depends on: the venv's python.exe (launcher),
    # its pyvenv.cfg and the base interpreter that pyvenv.cfg selects.
    param([Parameter(Mandatory = $true)][object]$Override)

    return [ordered]@{
        interpreter_sha256 = (Get-FileHash -LiteralPath $Override.interpreter_path -Algorithm SHA256).Hash.ToLowerInvariant()
        pyvenv_cfg_sha256 = (Get-FileHash -LiteralPath $Override.pyvenv_cfg_path -Algorithm SHA256).Hash.ToLowerInvariant()
        base_executable_sha256 = (Get-FileHash -LiteralPath $Override.base_executable -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Assert-SuiteInterpreterOverrideUnchanged {
    # Re-hash before the verdict: an interpreter swapped after the probe must
    # not inherit a qualification earned by different bytes.
    param([Parameter(Mandatory = $true)][object]$Override)

    $now = $null
    try { $now = Get-SuiteInterpreterOverrideHashes -Override $Override } catch { }
    if ($null -eq $now) {
        throw "interpreter override changed while the suite was running (unreadable)"
    }
    foreach ($name in @($now.Keys)) {
        if ([string]$now[$name] -cne [string]$Override.$name) {
            throw "interpreter override changed while the suite was running ($name)"
        }
    }
}

function Resolve-SuiteInterpreterOverride {
    # -InterpreterPath (host Python upgrade prep). Accepts only an absolute,
    # normalized path on a local fixed (not subst) drive to an existing regular
    # python.exe with no reparse point anywhere on it, whose contained probe
    # proves a Python 3.11 virtual environment rooted at <venv>\Scripts\.. with
    # its own pyvenv.cfg. Records what will actually run: the path, sys.version,
    # sys.prefix/base_prefix/executable and the SHA-256 of the launcher,
    # pyvenv.cfg and the base interpreter.
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ProbeOutputPrefix,
        [Parameter(Mandatory = $true)][string]$LeaseRepoRoot,
        [AllowEmptyString()][string]$ExpectedVersion = "",
        [ValidateRange(1, 300)][int]$ProbeTimeoutSeconds = 30
    )

    $normalized = $null
    try { $normalized = [IO.Path]::GetFullPath($Path) } catch { }
    if ($Path -notmatch '^[A-Za-z]:\\' -or $null -eq $normalized -or
        -not [string]::Equals($normalized, $Path, [StringComparison]::OrdinalIgnoreCase)) {
        throw "InterpreterPath must be an absolute, normalized local path: $Path"
    }
    if (-not [string]::Equals(
        [IO.Path]::GetFileName($Path), "python.exe", [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "InterpreterPath must name a python.exe: $Path"
    }
    if (-not [string]::IsNullOrEmpty($ExpectedVersion) -and $ExpectedVersion -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
        throw "ExpectedInterpreterVersion must be an exact N.N.N version: $ExpectedVersion"
    }
    Assert-SuiteInterpreterLocalDrive -Path $Path -Label "InterpreterPath"
    Assert-SuiteInterpreterLocalRegularFile -Path $Path -Label "InterpreterPath"
    $venvRoot = Split-Path -Parent (Split-Path -Parent $Path)

    # -I ignores PYTHON* variables, the user site and the working directory.
    # json.dumps keeps the record ASCII whatever the console code page.
    $probeArguments = ConvertTo-ScheduledTaskArgumentString `
        -Tokens @("-I", "-c", (
            "import sys, json; sys.stdout.write(json.dumps(dict(" +
            "version=sys.version, version_info=list(sys.version_info[:3]), " +
            "executable=sys.executable, prefix=sys.prefix, base_prefix=sys.base_prefix, " +
            "base_executable=getattr(sys, '_base_executable', ''))))"
        ))
    $probeJob = $null
    $probe = $null
    $probeOutput = $null
    $exitCode = $null
    try {
        $probeJob = New-WeatherKillOnCloseJob
        $probeOutput = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new(
            ($ProbeOutputPrefix + ".stdout.log"), ($ProbeOutputPrefix + ".stderr.log"), 65536
        )
        try {
            $probe = Start-WeatherProcessInJob `
                -Job $probeJob -FilePath $Path -ArgumentString $probeArguments `
                -WorkingDirectory (Split-Path -Parent $Path) -OutputCapture $probeOutput
        }
        catch {
            throw "InterpreterPath version probe could not start: $($_.Exception.Message)"
        }
        $probeDeadline = [Diagnostics.Stopwatch]::StartNew()
        while (-not $probe.HasExited) {
            if ($probeDeadline.Elapsed.TotalSeconds -ge $ProbeTimeoutSeconds) {
                throw "InterpreterPath version probe exceeded its bounded runtime"
            }
            $probeOutput.Drain()
            Start-Sleep -Milliseconds 50
            $probe.Refresh()
        }
        $probe.WaitForExit()
        $exitCode = [int]$probe.ExitCode
        $probeJob.TerminateAndWait(5000)
        $probeOutput.Complete(2000)
    }
    finally {
        if ($probeOutput) { $probeOutput.Dispose() }
        if ($probeJob) { $probeJob.Dispose() }
        if ($probe) { $probe.Dispose() }
    }
    $probeText = [IO.File]::ReadAllText($ProbeOutputPrefix + ".stdout.log")
    $record = $null
    if ($probeText.Length -le 16384) {
        try { $record = $probeText | ConvertFrom-Json } catch { $record = $null }
    }
    $triple = $null
    if ($null -ne $record) {
        $parts = @($record.version_info)
        if ($parts.Count -eq 3 -and @($parts | Where-Object { $_ -isnot [int] }).Count -eq 0 -and
            $record.version -is [string] -and $record.prefix -is [string] -and
            $record.base_prefix -is [string] -and $record.executable -is [string] -and
            $record.base_executable -is [string]) {
            $triple = "{0}.{1}.{2}" -f $parts[0], $parts[1], $parts[2]
        }
    }
    if ($exitCode -ne 0 -or $null -eq $triple) {
        throw "InterpreterPath version probe did not identify a Python interpreter (exit=$exitCode)"
    }
    # sys.version is interpreter-controlled text (a site .pth can rewrite it), so
    # the log records only the validated N.N.N triple and a hash of the raw string.
    if ($triple -notmatch '^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,6}$') {
        throw "InterpreterPath version probe did not identify a Python interpreter (exit=$exitCode)"
    }
    $versionHasher = [Security.Cryptography.SHA256]::Create()
    try {
        $versionSha256 = -join ($versionHasher.ComputeHash(
            [Text.Encoding]::UTF8.GetBytes([string]$record.version)
        ) | ForEach-Object { $_.ToString("x2") })
    }
    finally { $versionHasher.Dispose() }

    $sameFull = {
        param([string]$Left, [string]$Right)
        $l = $null
        $r = $null
        try {
            $l = [IO.Path]::GetFullPath($Left).TrimEnd('\')
            $r = [IO.Path]::GetFullPath($Right).TrimEnd('\')
        }
        catch { return $false }
        return [string]::Equals($l, $r, [StringComparison]::OrdinalIgnoreCase)
    }
    $venvRefusal = $null
    if (-not (& $sameFull $record.prefix $venvRoot)) {
        $venvRefusal = "sys.prefix $($record.prefix) is not the venv root $venvRoot"
    }
    elseif (& $sameFull $record.prefix $record.base_prefix) {
        $venvRefusal = "sys.prefix equals sys.base_prefix"
    }
    elseif (-not (& $sameFull $record.executable $Path)) {
        $venvRefusal = "sys.executable $($record.executable) is not InterpreterPath"
    }
    if ($null -ne $venvRefusal) {
        throw "InterpreterPath is not a virtual environment interpreter: $venvRefusal"
    }
    $pyvenvCfg = Join-Path $venvRoot "pyvenv.cfg"
    Assert-SuiteInterpreterLocalRegularFile -Path $pyvenvCfg -Label "InterpreterPath pyvenv.cfg"
    $baseExecutable = [string]$record.base_executable
    if ($baseExecutable -notmatch '^[A-Za-z]:\\' -or -not (Test-Path -LiteralPath $baseExecutable -PathType Leaf) -or
        (& $sameFull $baseExecutable $Path)) {
        throw "InterpreterPath base interpreter is not a separate local regular file: $baseExecutable"
    }
    # The base interpreter gets the same locality proof as InterpreterPath.
    Assert-SuiteInterpreterLocalDrive -Path $baseExecutable -Label "InterpreterPath base interpreter"
    Assert-SuiteInterpreterLocalRegularFile -Path $baseExecutable -Label "InterpreterPath base interpreter"
    if ($triple -notmatch '^3\.11\.[0-9]+$') {
        throw "InterpreterPath is not Python 3.11: $triple"
    }
    if (-not [string]::IsNullOrEmpty($ExpectedVersion) -and $triple -cne $ExpectedVersion) {
        throw "InterpreterPath is Python $triple, not the expected $ExpectedVersion"
    }

    $override = [pscustomobject][ordered]@{
        interpreter_path = $Path
        interpreter_sha256 = $null
        python_version = $triple
        python_version_sha256 = $versionSha256
        python_version_triple = $triple
        expected_version = $ExpectedVersion
        sys_executable = [string]$record.executable
        sys_prefix = [string]$record.prefix
        sys_base_prefix = [string]$record.base_prefix
        pyvenv_cfg_path = $pyvenvCfg
        pyvenv_cfg_sha256 = $null
        base_executable = $baseExecutable
        base_executable_sha256 = $null
        lease_repo_root = $LeaseRepoRoot
    }
    $hashes = Get-SuiteInterpreterOverrideHashes -Override $override
    foreach ($name in @($hashes.Keys)) { $override.$name = $hashes[$name] }
    return $override
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

Write-WeatherLaunchDiagnostic -Journal $launchJournal -Event "VALIDATING_GIT" -Detail ([ordered]@{
    selected_path = $GitExecutablePath
    expected_sha256 = $ExpectedGitExecutableSha256
    expected_file_version = $ExpectedGitExecutableFileVersion
})
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
$dirty = @((Invoke-SuiteCheckedLocalGit `
    -Root $WorktreeRoot -Arguments @("status", "--porcelain") `
    -Label "initial exact worktree status").Rows)
if ($dirty.Count -ne 0) {
    throw "suite worktree is dirty; exact-tip evidence would be ambiguous"
}

if ([string]::IsNullOrEmpty($InterpreterPath)) {
    $interpreterOverride = $null
    $python = Join-Path $RepoRoot "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "production venv interpreter is missing: $python"
    }
    $python = (Resolve-Path -LiteralPath $python).Path
}
else {
    # Only the interpreter changes: RepoRoot (admission, capture state and the
    # shared data\logs\heavy_workload.lock lease below) stays production.
    $interpreterOverride = Resolve-SuiteInterpreterOverride `
        -Path $InterpreterPath -ProbeOutputPrefix ($LogPath + ".interpreter") `
        -LeaseRepoRoot $RepoRoot -ExpectedVersion $ExpectedInterpreterVersion
    $python = $interpreterOverride.interpreter_path
    Write-WeatherLaunchDiagnostic -Journal $launchJournal -Event "INTERPRETER_OVERRIDE" `
        -Detail $interpreterOverride
}

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
    Write-SuiteLog "selected_git=$($worktreeQuery.Executable) expected_git_sha256=$ExpectedGitExecutableSha256 expected_git_file_version=$ExpectedGitExecutableFileVersion"
    Write-SuiteLog "worktree=$WorktreeRoot branch=$BranchRef expected_tip=$ExpectedTip"
    Write-SuiteLog "additional_python_roots=$($additionalPythonRoots.Count) require_live_sdk_contract=$($RequireLiveSdkContract.IsPresent) integration_preflight=$($IntegrationPreflight.IsPresent)"
    if ($null -ne $interpreterOverride) {
        Write-SuiteLog ("interpreter_override " + ($interpreterOverride | ConvertTo-Json -Compress))
    }
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
        $launchStatus = "PASS"
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
        $trackedTestFiles = @((Invoke-SuiteCheckedLocalGit `
            -Root $WorktreeRoot -Arguments @("ls-files", "--", "tests") `
            -Label "tracked pytest inventory selection").Rows)
        $testFiles = @(
            $trackedTestFiles |
                ForEach-Object { ([string]$_).Replace("\", "/") } |
                Where-Object { $_ -match '^tests/(?:.*/)?test_[^/]*\.py$' } |
                Sort-Object
        )
    }
    if ($testFiles.Count -eq 0) { throw "no pytest files found in exact worktree" }
    $inventoryTestFiles = @($testFiles)
    $reconcilerTestFile = "tests/operations/test_production_baseline_reconciler_execution.py"
    if (-not $IntegrationPreflight -and $testFiles -contains $reconcilerTestFile) {
        $reconcilerInclude = $true
        $reconcilerTouched = @()
        $reconcilerSurfaceCount = "n/a"
        if ($IncludeReconciler) {
            $reconcilerReason = "forced by -IncludeReconciler"
        }
        elseif (-not $ReconcilerSurfaceBase) {
            $reconcilerReason = "no -ReconcilerSurfaceBase supplied"
        }
        else {
            try {
                . (Join-Path $PSScriptRoot "reconciler_surface.ps1")
                $changedPaths = @((Invoke-SuiteCheckedLocalGit `
                    -Root $WorktreeRoot `
                    -Arguments @("diff", "--name-only", "--no-renames",
                        $ReconcilerSurfaceBase.ToLowerInvariant(), $ExpectedTip.ToLowerInvariant()) `
                    -Label "reconciler surface diff").Rows)
                $decision = Get-WeatherReconcilerDecision -Root $WorktreeRoot -ChangedPaths $changedPaths
                $reconcilerInclude = [bool]$decision.Include
                $reconcilerReason = [string]$decision.Reason
                $reconcilerTouched = @($decision.Touched)
                $reconcilerSurfaceCount = [string]$decision.SurfaceCount
            }
            catch {
                # Fail closed: a predicate that cannot be evaluated includes the file.
                $reconcilerInclude = $true
                $reconcilerReason = "predicate unavailable ($($_.Exception.Message))"
            }
        }
        if (-not $reconcilerInclude) {
            $testFiles = @($testFiles | Where-Object { $_ -ne $reconcilerTestFile })
        }
        Write-SuiteLog (
            "reconciler: $(if ($reconcilerInclude) { 'INCLUDED' } else { 'SKIPPED' }) " +
            "reason=$reconcilerReason base=$(if ($ReconcilerSurfaceBase) { $ReconcilerSurfaceBase.ToLowerInvariant() } else { 'none' }) " +
            "surface_paths=$reconcilerSurfaceCount touched=$(@($reconcilerTouched) -join ',')"
        )
    }
    if ($SmokeTest) {
        $testFiles = @($testFiles | Select-Object -First ([math]::Min(2, $testFiles.Count)))
    }

    $timingTable = Read-SuiteFileTimingTable `
        -Path (Join-Path $WorktreeRoot "tests\bounded_suite_file_timings.json")
    $chunks = Get-SuiteTimePackedChunks `
        -TestFiles $testFiles -MaxFilesPerChunk $MaxFilesPerChunk -TimingTable $timingTable
    Write-SuiteLog "planned chunks=$($chunks.Count) files=$($testFiles.Count) max_files=$MaxFilesPerChunk"
    $projectedChunkSeconds = @($chunks | ForEach-Object {
        $chunkSeconds = 0.0
        foreach ($file in @($_)) {
            $chunkSeconds += if ($timingTable.Seconds.ContainsKey([string]$file)) {
                $timingTable.Seconds[[string]$file]
            } else { $timingTable.DefaultSeconds }
        }
        $chunkSeconds
    })
    $defaultedFiles = @($testFiles | Where-Object { -not $timingTable.Seconds.ContainsKey([string]$_) }).Count
    Write-SuiteLog (
        "chunk packing=time_lpt_v1 timing_table_present=$($timingTable.Present) " +
        "timing_table_sha256=$($timingTable.Sha256) defaulted_files=$defaultedFiles " +
        "projected_max_s=$([math]::Round(($projectedChunkSeconds | Measure-Object -Maximum).Maximum, 1)) " +
        "projected_min_s=$([math]::Round(($projectedChunkSeconds | Measure-Object -Minimum).Minimum, 1))"
    )

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
        # Both pytest and tempfile stay in this chunk's short, cleaned root.
        # Without it pytest keeps its temp trees in %TEMP% (2026-09-23: ~2.6 GB
        # after 10 chunks pushed the host under this suite's own disk floor).
        $chunkBaseTempParent = Join-Path $env:SystemDrive "pt"
        $chunkBaseTemp = Join-Path $chunkBaseTempParent ("bs-{0}-{1:D3}" -f $runTag, $ordinal)
        if (-not (Test-Path -LiteralPath $chunkBaseTempParent)) {
            New-Item -ItemType Directory -Path $chunkBaseTempParent -ErrorAction Stop | Out-Null
        }
        if (Test-Path -LiteralPath $chunkBaseTemp) {
            throw "chunk $ordinal pytest basetemp unexpectedly already exists: $chunkBaseTemp"
        }
        # Pytest clears --basetemp on first use. Keep TEMP/TMP in a sibling
        # beneath the chunk root so that cleanup cannot erase the active TEMP.
        $chunkPytestBaseTemp = Join-Path $chunkBaseTemp "pytest"
        $tokens = @(
            "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--junitxml", $junitTempPath
        ) + @("--basetemp", $chunkPytestBaseTemp) + @($chunks[$index])
        $argumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
        Write-SuiteLog "chunk $ordinal/$($chunks.Count) starting files=$($chunks[$index].Count) junit=$junitPath"

        $childJob = $null
        $child = $null
        $exitCode = $null
        $chunkTempEnvironment = $null
        try {
            $chunkTempEnvironment = Enter-SuiteChunkTemp -Root $chunkBaseTemp
            $childJob = New-WeatherKillOnCloseJob
            $child = Start-WeatherProcessInJob `
                -Job $childJob `
                -FilePath $python `
                -ArgumentString $argumentString `
                -WorkingDirectory $WorktreeRoot
            $nextChunkAdmissionSeconds = $suiteRuntimeStopwatch.Elapsed.TotalSeconds + 5
            while (-not $child.HasExited) {
                if ($suiteRuntimeStopwatch.Elapsed.TotalSeconds -ge $MaxRuntimeSeconds -or
                    (Get-Date) -ge $suiteDeadline) {
                    Write-SuiteLog "chunk $ordinal reached the suite deadline; killing its complete child tree"
                    throw "bounded suite reached its runtime or 09:00 hard teardown boundary"
                }
                if ($suiteRuntimeStopwatch.Elapsed.TotalSeconds -ge $nextChunkAdmissionSeconds) {
                    Assert-SuiteDiskHeadroom
                    Assert-HostAdmission -CommitCeiling $AbortCommitPercent -Phase "chunk-$ordinal-running"
                    $nextChunkAdmissionSeconds = $suiteRuntimeStopwatch.Elapsed.TotalSeconds + 5
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
            if ($null -ne $chunkTempEnvironment) {
                Exit-SuiteChunkTemp -Saved $chunkTempEnvironment
            }
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
            $chunkTempToRemove = Get-Variable -Name chunkBaseTemp -ValueOnly -ErrorAction SilentlyContinue
            if ($chunkTempToRemove -and (Test-Path -LiteralPath $chunkTempToRemove)) {
                $chunkBaseTemp = $chunkTempToRemove
                $chunkBaseTempItem = Get-Item -LiteralPath $chunkBaseTemp -Force -ErrorAction Stop
                if (-not $chunkBaseTempItem.PSIsContainer -or
                    ($chunkBaseTempItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                    throw "refusing unsafe pytest basetemp cleanup: $chunkBaseTemp"
                }
                # rmdir /s removes junctions inside the tree without following them;
                # Remove-Item -Recurse on Windows PowerShell 5.1 can follow them.
                & cmd.exe /d /c "rmdir /s /q `"$chunkBaseTemp`"" | Out-Null
                if (Test-Path -LiteralPath $chunkBaseTemp) {
                    Write-SuiteLog "chunk $ordinal pytest basetemp could not be fully removed: $chunkBaseTemp"
                }
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
    $finalWorktreeTipRows = @((Invoke-SuiteCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}") `
        -Label "final exact worktree tip query").Rows)
    if ($finalWorktreeTipRows.Count -ne 1) {
        throw "could not re-resolve the exact worktree tip after the final chunk"
    }
    $finalWorktreeTip = ([string]$finalWorktreeTipRows[0]).Trim().ToLowerInvariant()
    $finalBranchTipRows = @((Invoke-SuiteCheckedLocalGit `
        -Root $RepoRoot `
        -Arguments @("rev-parse", "--verify", "--end-of-options", "${BranchRef}^{commit}") `
        -Label "final exact branch tip query").Rows)
    if ($finalBranchTipRows.Count -ne 1) {
        throw "could not re-resolve BranchRef after the final chunk"
    }
    $finalBranchTip = ([string]$finalBranchTipRows[0]).Trim().ToLowerInvariant()
    if ($finalWorktreeTip -ne $ExpectedTip -or $finalBranchTip -ne $ExpectedTip) {
        throw "exact branch/worktree identity changed while the suite was running"
    }
    $finalDirty = @((Invoke-SuiteCheckedLocalGit `
        -Root $WorktreeRoot -Arguments @("status", "--porcelain") `
        -Label "final exact worktree status").Rows)
    if ($finalDirty.Count -ne 0) {
        throw "suite worktree changed while the suite was running"
    }
    if (-not $SmokeTest -and -not $IntegrationPreflight) {
        $finalTrackedRows = @((Invoke-SuiteCheckedLocalGit `
            -Root $WorktreeRoot -Arguments @("ls-files", "--", "tests") `
            -Label "final tracked pytest inventory").Rows)
        $finalTestFiles = @(
            $finalTrackedRows |
                ForEach-Object { ([string]$_).Replace("\", "/") } |
                Where-Object { $_ -match '^tests/(?:.*/)?test_[^/]*\.py$' } |
                Sort-Object
        )
        if ($finalTestFiles.Count -ne $inventoryTestFiles.Count -or
            @(Compare-Object -ReferenceObject @($inventoryTestFiles) -DifferenceObject @($finalTestFiles)).Count -ne 0) {
            throw "tracked pytest inventory changed while the suite was running"
        }
    }
    Write-SuiteLog "final exact-tip, clean-worktree, and test-inventory recheck passed"
    if ($null -ne $interpreterOverride) {
        Assert-SuiteInterpreterOverrideUnchanged -Override $interpreterOverride
        Write-SuiteLog "interpreter override re-hash matched: interpreter, pyvenv.cfg and base executable unchanged"
    }

    if ($SmokeTest) {
        Write-SuiteLog "VERDICT: SMOKE PASSED; full suite not run and merge is not authorized"
        $launchStatus = "PASS"
        exit 0
    }
    if ($IntegrationPreflight) {
        Write-SuiteLog "VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge is not authorized"
        $launchStatus = "PASS"
        exit 0
    }
    if ($null -ne $interpreterOverride) {
        # A staged interpreter qualifies itself, never the production venv, so
        # this verdict must not contain the merge-eligible phrase that the
        # merge gates, attempt contract and bundle packager accept.
        Write-SuiteLog (
            "VERDICT: INTERPRETER QUALIFICATION PASSED ($($chunks.Count)/$($chunks.Count)); " +
            "interpreter override sha256=$($interpreterOverride.interpreter_sha256) " +
            "python=$($interpreterOverride.python_version_triple); NOT merge evidence"
        )
        $launchStatus = "PASS"
        exit 0
    }
    Write-SuiteLog "VERDICT: ALL CHUNKS PASSED ($($chunks.Count)/$($chunks.Count)); exact tip eligible for separate reviewed merge"
    $launchStatus = "PASS"
    exit 0
}
catch {
    $launchFailure = $_
    throw
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
        Close-WeatherLaunchDiagnostics -Journal $launchJournal -Status $launchStatus -Failure $launchFailure
    }
}
