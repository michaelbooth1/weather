# Run a full pytest suite from an exact, clean Git worktree without endangering
# production capture. This runner never merges, pushes, checks out, registers a
# task, or writes under production data/. Each Python child is assigned before
# resume to a kill-on-close Windows Job so stopping the scheduled wrapper cannot
# leave a Python process behind. Probe results cross the process boundary as
# bounded stdout bytes read from the same retained no-delete/no-write handle;
# their ephemeral backing files are never reopened as readiness evidence.

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
$logParentItem = Get-Item -LiteralPath $logParent -Force -ErrorAction Stop
if (($logParentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "suite log parent must be a regular directory: $logParent"
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
$suiteFrozenPythonGitControls = [ordered]@{
    GIT_CONFIG_NOSYSTEM = "1"
    GIT_CONFIG_SYSTEM = "NUL"
    GIT_CONFIG_GLOBAL = "NUL"
    GIT_CONFIG_COUNT = "0"
    GIT_ATTR_NOSYSTEM = "1"
    GIT_PROTOCOL_FROM_USER = "0"
    GIT_OPTIONAL_LOCKS = "0"
}
$suiteRejectedPythonGitControls = @(
    "GIT_CONFIG_PARAMETERS", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_EXEC_PATH", "GIT_TEMPLATE_DIR"
)
$blockedPythonControls = @(
    "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONHOME", "PYTHONPATH",
    "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONBREAKPOINT",
    "PYTHONOPTIMIZE", "PYTHONWARNINGS", "PYTHONINSPECT",
    "PYTHONSAFEPATH", "PYTHONCASEOK", "PYTHONEXECUTABLE",
    "PYTHONPLATLIBDIR", "PYTHONPYCACHEPREFIX",
    "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED", "PYTHONUTF8",
    "PYTHONIOENCODING", "COVERAGE_PROCESS_START",
    "GIT_ALLOW_PROTOCOL", "GIT_TERMINAL_PROMPT",
    @($suiteFrozenPythonGitControls.Keys),
    @($suiteRejectedPythonGitControls),
    "WEATHER_INTEGRATION_TEST_OFFLINE",
    "WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT",
    "WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT",
    "WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT",
    "WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT",
    "WEATHER_INTEGRATION_TEST_SECRET_POLICY",
    "WEATHER_INTEGRATION_TEST_TEMP_POLICY",
    "WEATHER_INTEGRATION_TEST_PYTHON_EXECUTABLE",
    "WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE",
    "WEATHER_INTEGRATION_TEST_POWERSHELL_EXECUTABLE",
    "WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE",
    "SETUPTOOLS_USE_DISTUTILS"
)

function Test-SuiteSecretBearingEnvironmentName {
    param([Parameter(Mandatory = $true)][string]$Name)

    if ($Name -ceq "WEATHER_INTEGRATION_TEST_SECRET_POLICY") { return $false }
    if ($Name -in @(
        "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL",
        "UV_INDEX_URL", "UV_EXTRA_INDEX_URL",
        "GH_TOKEN", "GITHUB_TOKEN", "HF_TOKEN",
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "PIP_CERT",
        "PIP_PROXY", "PIP_TRUSTED_HOST",
        "GIT_SSL_NO_VERIFY", "GIT_SSL_CAINFO", "GIT_SSL_CAPATH",
        "GIT_ASKPASS", "SSH_ASKPASS", "SSH_AUTH_SOCK", "GIT_SSH",
        "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND"
    )) { return $true }
    if ($Name -match '^(?i:POLYMARKET_|POLYMM_|OPENAI_|ANTHROPIC_|CLOUDFLARE_|AWS_|AZURE_|GOOGLE_|GCM_|GIT_SSL_|GIT_SSH)') {
        return $true
    }
    return ($Name -match
        '(?i)(?:^|_)(?:TOKEN|PASSWORD|PASSWD|SECRET|PRIVATE_KEY|API_KEY|ACCESS_KEY|CLIENT_SECRET|CREDENTIALS?|CONNECTION_STRING|URL|URI|DSN|AUTH|COOKIE|KEY|CERT)(?:$|_)')
}

function Get-SuiteSecretBearingEnvironmentNames {
    $names = @(
        [Environment]::GetEnvironmentVariables(
            [EnvironmentVariableTarget]::Process
        ).Keys |
            ForEach-Object { [string]$_ } |
            Where-Object { Test-SuiteSecretBearingEnvironmentName -Name $_ } |
            Sort-Object -Unique
    )
    return $names
}

function Assert-SuiteNoAmbientControls {
    param([Parameter(Mandatory = $true)][string[]]$Names)

    $presentControls = @($Names | Where-Object {
        $null -ne [Environment]::GetEnvironmentVariable(
            $_,
            [EnvironmentVariableTarget]::Process
        )
    })
    if ($presentControls.Count -ne 0) {
        throw "Ambient Python/test controls are forbidden: $($presentControls -join ', ')"
    }
}

function Assert-SuitePythonGitTopologyClear {
    param([Parameter(Mandatory = $true)][string]$Phase)

    $presentTopology = @($suiteRejectedPythonGitControls | Where-Object {
        $null -ne [Environment]::GetEnvironmentVariable(
            [string]$_,
            [EnvironmentVariableTarget]::Process
        )
    })
    if ($presentTopology.Count -ne 0) {
        throw (
            "$Phase refuses Python-child Git topology or helper redirects: " +
            ($presentTopology -join ", ")
        )
    }
}

function Assert-SuiteQualifiedPythonGitEnvironment {
    param([Parameter(Mandatory = $true)][string]$Phase)

    Assert-SuitePythonGitTopologyClear -Phase $Phase
    foreach ($name in @($suiteFrozenPythonGitControls.Keys)) {
        $actual = [Environment]::GetEnvironmentVariable(
            [string]$name,
            [EnvironmentVariableTarget]::Process
        )
        if ($actual -cne [string]$suiteFrozenPythonGitControls[$name]) {
            throw "$Phase protected Python-child Git environment changed: $name"
        }
    }
    if ([string]$env:GIT_ALLOW_PROTOCOL -cne "file" -or
        [string]$env:GIT_TERMINAL_PROMPT -cne "0") {
        throw "$Phase protected Python-child Git protocol controls changed"
    }
}

function Enter-SuiteQualifiedPythonGitEnvironment {
    param([Parameter(Mandatory = $true)][string]$Phase)

    Assert-SuitePythonGitTopologyClear -Phase $Phase
    $values = [ordered]@{
        GIT_ALLOW_PROTOCOL = "file"
        GIT_TERMINAL_PROMPT = "0"
    }
    foreach ($name in @($suiteFrozenPythonGitControls.Keys)) {
        $values[[string]$name] = [string]$suiteFrozenPythonGitControls[$name]
    }
    $restorations = [Collections.Generic.List[object]]::new()
    $completed = $false
    $primaryFailure = $null
    try {
        foreach ($name in @($values.Keys)) {
            $restorations.Add([pscustomobject]@{
                Name = [string]$name
                Value = [Environment]::GetEnvironmentVariable(
                    [string]$name,
                    [EnvironmentVariableTarget]::Process
                )
            })
            [Environment]::SetEnvironmentVariable(
                [string]$name,
                [string]$values[$name],
                [EnvironmentVariableTarget]::Process
            )
        }
        Assert-SuiteQualifiedPythonGitEnvironment -Phase $Phase
        $completed = $true
        return @($restorations)
    }
    catch {
        $primaryFailure = $_
        throw
    }
    finally {
        if (-not $completed) {
            $cleanupFailures = [Collections.Generic.List[string]]::new()
            foreach ($restoration in @($restorations)) {
                try {
                    [Environment]::SetEnvironmentVariable(
                        [string]$restoration.Name,
                        $restoration.Value,
                        [EnvironmentVariableTarget]::Process
                    )
                }
                catch { $cleanupFailures.Add([string]$restoration.Name) }
            }
            if ($cleanupFailures.Count -gt 0) {
                $message = "$Phase Python-child Git environment setup cleanup failed"
                if ($null -ne $primaryFailure) {
                    $primaryFailure.Exception.Data[
                        "weather_git_environment_cleanup_failure"
                    ] = $message
                    Write-Warning $message -WarningAction Continue
                }
                else { throw $message }
            }
        }
    }
}

function Exit-SuiteQualifiedPythonGitEnvironment {
    param(
        [Parameter(Mandatory = $true)][object[]]$Restorations,
        [Parameter(Mandatory = $true)][string]$Phase,
        [AllowNull()][Management.Automation.ErrorRecord]$PrimaryError
    )

    $cleanupFailures = [Collections.Generic.List[string]]::new()
    foreach ($restoration in @($Restorations)) {
        try {
            [Environment]::SetEnvironmentVariable(
                [string]$restoration.Name,
                $restoration.Value,
                [EnvironmentVariableTarget]::Process
            )
            $restored = [Environment]::GetEnvironmentVariable(
                [string]$restoration.Name,
                [EnvironmentVariableTarget]::Process
            )
            if ($restored -cne $restoration.Value) {
                throw "restored value was not observed"
            }
        }
        catch { $cleanupFailures.Add([string]$restoration.Name) }
    }
    if ($cleanupFailures.Count -gt 0) {
        $message = "$Phase Python-child Git environment restoration failed"
        if ($null -ne $PrimaryError) {
            $PrimaryError.Exception.Data[
                "weather_git_environment_cleanup_failure"
            ] = $message
            Write-Warning $message -WarningAction Continue
            return
        }
        throw $message
    }
    try { Assert-SuitePythonGitTopologyClear -Phase "$Phase restoration" }
    catch {
        $message = "$Phase Python-child Git topology restoration failed"
        if ($null -ne $PrimaryError) {
            $PrimaryError.Exception.Data[
                "weather_git_environment_cleanup_failure"
            ] = $message
            Write-Warning $message -WarningAction Continue
            return
        }
        throw
    }
}
Assert-SuiteNoAmbientControls -Names $blockedPythonControls

$contractScript = Join-Path $RepoRoot "scripts\ops\training_window_contract.ps1"
$jobScript = Join-Path $RepoRoot "scripts\ops\windows_kill_on_close_job.ps1"
$localGitScript = Join-Path $RepoRoot "scripts\ops\integration_attempt_remote_git.ps1"
$workloadLeaseScript = Join-Path $RepoRoot "scripts\ops\workload_admission.ps1"
$quietMergePreflightScript = Join-Path $RepoRoot `
    "scripts\ops\integration_attempt_quiet_merge_preflight.ps1"
foreach ($requiredScript in @(
    $contractScript,
    $jobScript,
    $localGitScript,
    $workloadLeaseScript,
    $quietMergePreflightScript
)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "required suite helper is missing: $requiredScript"
    }
}
. $contractScript
. $localGitScript
. $workloadLeaseScript
. $quietMergePreflightScript
$repoRootPrefix = $RepoRoot.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
) + [IO.Path]::DirectorySeparatorChar
if (-not $logParent.StartsWith(
        $repoRootPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "bounded offline suite evidence must remain beneath exact RepoRoot"
}
Assert-WeatherIntegrationRegularPathAncestry `
    -Path $logParent -Phase "bounded suite evidence root"
$evidenceRoot = [IO.Path]::GetFullPath($logParent).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)

function ConvertTo-SuiteCanonicalRegularDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or
        -not [IO.Path]::IsPathRooted($Path)) {
        throw "$Phase must be a nonempty absolute directory path"
    }
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $volumeRoot = [IO.Path]::GetPathRoot($fullPath).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    if ([string]::IsNullOrWhiteSpace($fullPath) -or
        $fullPath.Equals($volumeRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $fullPath -PathType Container)) {
        throw "$Phase must be an existing non-volume-root directory"
    }
    Assert-WeatherIntegrationRegularPathAncestry -Path $fullPath -Phase $Phase
    $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Phase must be a regular non-reparse directory"
    }
    return $fullPath
}

function Test-SuitePathsOverlap {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    $leftFull = [IO.Path]::GetFullPath($Left).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $rightFull = [IO.Path]::GetFullPath($Right).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    return (
        $leftFull.Equals($rightFull, [StringComparison]::OrdinalIgnoreCase) -or
        $leftFull.StartsWith(
            $rightFull + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        $rightFull.StartsWith(
            $leftFull + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Get-SuiteCanonicalSystemTempRoot {
    param([Parameter(Mandatory = $true)][string]$Phase)

    $runtimeTemp = ConvertTo-SuiteCanonicalRegularDirectory `
        -Path ([IO.Path]::GetTempPath()) -Phase "$Phase GetTempPath"
    foreach ($name in @("TEMP", "TMP")) {
        $value = [Environment]::GetEnvironmentVariable(
            $name,
            [EnvironmentVariableTarget]::Process
        )
        $environmentTemp = ConvertTo-SuiteCanonicalRegularDirectory `
            -Path ([string]$value) -Phase "$Phase $name"
        if (-not $environmentTemp.Equals(
                $runtimeTemp,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw "$Phase requires GetTempPath, TEMP, and TMP to resolve to one directory"
        }
    }
    $pythonTemp = [Environment]::GetEnvironmentVariable(
        "TMPDIR",
        [EnvironmentVariableTarget]::Process
    )
    if (-not [string]::IsNullOrWhiteSpace([string]$pythonTemp)) {
        $canonicalPythonTemp = ConvertTo-SuiteCanonicalRegularDirectory `
            -Path ([string]$pythonTemp) -Phase "$Phase TMPDIR"
        if (-not $canonicalPythonTemp.Equals(
                $runtimeTemp,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw "$Phase requires ambient TMPDIR to equal the frozen system temp"
        }
    }
    return $runtimeTemp
}

function Assert-SuiteFrozenSystemTempRoot {
    param([Parameter(Mandatory = $true)][string]$Phase)

    if ([string]::IsNullOrWhiteSpace([string]$suiteSystemTempRoot)) {
        throw "$Phase frozen system-temp root is unavailable"
    }
    $current = Get-SuiteCanonicalSystemTempRoot -Phase $Phase
    if (-not $current.Equals(
            $suiteSystemTempRoot,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "$Phase system-temp authority changed after entry"
    }
    foreach ($protected in ([ordered]@{
        production = $RepoRoot
        worktree = $WorktreeRoot
        evidence = $evidenceRoot
    }).GetEnumerator()) {
        if (Test-SuitePathsOverlap `
                -Left $suiteSystemTempRoot -Right ([string]$protected.Value)) {
            throw (
                "$Phase frozen system-temp root overlaps the " +
                "$([string]$protected.Key) authority root"
            )
        }
    }
}
$suiteSystemTempRoot = Get-SuiteCanonicalSystemTempRoot `
    -Phase "bounded suite entry"
Assert-SuiteFrozenSystemTempRoot -Phase "bounded suite entry"

function Open-SuiteRetainedLog {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    if (Test-Path -LiteralPath $fullPath) {
        throw "bounded suite refuses to append to or replace an existing log: $fullPath"
    }
    $stream = $null
    try {
        $stream = [IO.File]::Open(
            $fullPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::Read
        )
        $writer = New-Object IO.StreamWriter(
            $stream,
            (New-Object Text.UTF8Encoding($false, $true)),
            4096,
            $true
        )
        $writer.AutoFlush = $true
        return [pscustomobject]@{
            Path = $fullPath
            Stream = $stream
            Writer = $writer
        }
    }
    catch {
        if ($null -ne $stream) { $stream.Dispose() }
        throw
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

function Write-SuiteRetainedByteSidecar {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][byte[]]$Bytes
    )

    $fullPath = [IO.Path]::GetFullPath($Path)
    if (Test-Path -LiteralPath $fullPath) {
        throw "bounded suite refuses to replace an existing evidence sidecar: $fullPath"
    }
    $stream = $null
    try {
        $stream = [IO.File]::Open(
            $fullPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::Read
        )
        $stream.Write($Bytes, 0, $Bytes.Length)
        $stream.Flush($true)
        $stream.Position = 0
        [byte[]]$retainedBytes = [byte[]]::new($Bytes.Length)
        $retainedOffset = 0
        while ($retainedOffset -lt $retainedBytes.Length) {
            $retainedRead = $stream.Read(
                $retainedBytes,
                $retainedOffset,
                $retainedBytes.Length - $retainedOffset
            )
            if ($retainedRead -le 0) {
                throw "bounded suite evidence sidecar ended before its exact retained readback"
            }
            $retainedOffset += $retainedRead
        }
        if (-not [System.Collections.StructuralComparisons]::StructuralEqualityComparer.Equals(
            $Bytes,
            $retainedBytes
        )) {
            throw "bounded suite evidence sidecar failed its exact retained readback"
        }
        $stream.Position = $stream.Length
        $suiteSidecarStreams.Add($stream)
        return $fullPath
    }
    catch {
        if ($null -ne $stream) { $stream.Dispose() }
        throw
    }
}

function Write-SuiteRetainedSidecar {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text
    )

    [byte[]]$bytes = (New-Object Text.UTF8Encoding($false, $true)).GetBytes($Text)
    return Write-SuiteRetainedByteSidecar -Path $Path -Bytes $bytes
}

function Get-SuiteInventorySha256 {
    param([Parameter(Mandatory = $true)][string[]]$Paths)

    $bytes = [Text.Encoding]::UTF8.GetBytes((@($Paths) -join "`n") + "`n")
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        return (([BitConverter]::ToString($hash.ComputeHash($bytes))) -replace '-', '').ToLowerInvariant()
    }
    finally { $hash.Dispose() }
}

function Assert-SuitePythonCacheRoot {
    Assert-SuiteFrozenSystemTempRoot -Phase "suite-owned Python cache root"
    if ([string]::IsNullOrWhiteSpace([string]$pythonCacheRoot) -or
        -not (Test-Path -LiteralPath $pythonCacheRoot -PathType Container)) {
        throw "suite-owned Python cache root is missing"
    }
    $fullPath = [IO.Path]::GetFullPath($pythonCacheRoot)
    if (-not [IO.Path]::GetDirectoryName($fullPath).Equals(
            $suiteSystemTempRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [IO.Path]::GetFileName($fullPath) -cnotmatch
            '^weather-bounded-python-cache-[0-9a-f]{32}$') {
        throw "suite-owned Python cache root escaped frozen system temp"
    }
    $cacheItem = Get-Item -LiteralPath $pythonCacheRoot -Force -ErrorAction Stop
    if (($cacheItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "suite-owned Python cache root became a reparse point: $pythonCacheRoot"
    }
    if (@([IO.Directory]::EnumerateFileSystemEntries($pythonCacheRoot)).Count -ne 0) {
        throw "suite-owned Python cache root is not empty: $pythonCacheRoot"
    }
}

function Remove-SuiteOwnedPythonCacheRoot {
    if ([string]::IsNullOrWhiteSpace([string]$pythonCacheRoot)) { return }
    $fullPath = [IO.Path]::GetFullPath($pythonCacheRoot)
    $actualParent = [IO.Path]::GetDirectoryName($fullPath)
    $actualName = [IO.Path]::GetFileName($fullPath)
    if (-not $actualParent.Equals(
            $suiteSystemTempRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        $actualName -cnotmatch '^weather-bounded-python-cache-[0-9a-f]{32}$') {
        throw "refusing to clean a non-owned Python cache root: $fullPath"
    }
    if (-not (Test-Path -LiteralPath $fullPath)) { return }
    if (-not (Test-Path -LiteralPath $fullPath -PathType Container)) {
        throw "refusing to clean non-directory Python cache root: $fullPath"
    }
    $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        @([IO.Directory]::EnumerateFileSystemEntries($fullPath)).Count -ne 0) {
        throw "refusing to clean nonempty or reparse-point Python cache root: $fullPath"
    }
    Remove-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $fullPath) {
        throw "suite-owned Python cache-root cleanup was not proved: $fullPath"
    }
}

function New-SuiteByteSnapshot {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes
    )

    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        $sha256 = (
            ([BitConverter]::ToString($hash.ComputeHash($Bytes))) -replace '-', ''
        ).ToLowerInvariant()
    }
    finally { $hash.Dispose() }
    return [pscustomobject]@{
        Bytes = $Bytes
        Length = [int]$Bytes.Length
        Sha256 = $sha256
    }
}

function New-SuiteUtf8Snapshot {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $snapshot = New-SuiteByteSnapshot -Bytes $Bytes
    try {
        $text = (New-Object Text.UTF8Encoding($false, $true)).GetString($Bytes)
    }
    catch {
        throw "$Label output is not strict UTF-8"
    }
    return [pscustomobject]@{
        Bytes = $snapshot.Bytes
        Length = $snapshot.Length
        Sha256 = $snapshot.Sha256
        Text = $text
    }
}

function Open-SuiteBoundedFileReadHandle {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateRange(1, 67108864)][int]$MaxBytes,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$AllowEmpty
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label did not create its exact output file: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Label output is a reparse point: $Path"
    }
    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read
    )
    try {
        if ($stream.Length -lt 0 -or
            ($stream.Length -eq 0 -and -not $AllowEmpty.IsPresent) -or
            $stream.Length -gt $MaxBytes) {
            throw "$Label output is not a bounded nonempty file: $Path"
        }
        return [pscustomobject]@{
            Stream = $stream
            Length = [int]$stream.Length
        }
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Read-SuiteBoundedFileHandleSnapshot {
    param(
        [Parameter(Mandatory = $true)][object]$Handle,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $stream = $Handle.Stream
    if ($null -eq $stream -or -not $stream.CanRead -or -not $stream.CanSeek -or
        [int]$stream.Length -ne [int]$Handle.Length) {
        throw "$Label retained handle is invalid or changed length"
    }
    try {
        $stream.Position = 0
        $bytes = [byte[]]::new([int]$Handle.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $read = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($read -le 0) { throw "$Label output ended before its declared length" }
            $offset += $read
        }
        if ([int]$stream.Length -ne [int]$Handle.Length) {
            throw "$Label output changed length during its retained read"
        }
        $snapshot = New-SuiteByteSnapshot -Bytes $bytes
        return [pscustomobject]@{
            Stream = $stream
            Bytes = $snapshot.Bytes
            Length = $snapshot.Length
            Sha256 = $snapshot.Sha256
        }
    }
    finally { $stream.Position = 0 }
}

function Open-SuiteBoundedFileSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateRange(1, 67108864)][int]$MaxBytes,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$AllowEmpty
    )

    $handle = Open-SuiteBoundedFileReadHandle `
        -Path $Path -MaxBytes $MaxBytes -Label $Label -AllowEmpty:$AllowEmpty
    try {
        return Read-SuiteBoundedFileHandleSnapshot -Handle $handle -Label $Label
    }
    catch {
        $handle.Stream.Dispose()
        throw
    }
}

function Open-SuiteQualifiedPthBootstrap {
    $sitePackages = [IO.Path]::GetFullPath(
        (Join-Path $RepoRoot "venv\Lib\site-packages")
    )
    if (-not (Test-Path -LiteralPath $sitePackages -PathType Container)) {
        throw "production venv site-packages is missing"
    }
    Assert-WeatherIntegrationRegularPathAncestry `
        -Path $sitePackages -Phase "bounded suite .pth bootstrap directory"
    $siteItem = Get-Item -LiteralPath $sitePackages -Force -ErrorAction Stop
    if (-not $siteItem.PSIsContainer -or
        ($siteItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "production venv site-packages is not a regular directory"
    }
    $paths = @([IO.Directory]::EnumerateFiles(
        $sitePackages, "*", [IO.SearchOption]::TopDirectoryOnly
    ) | Where-Object {
        [IO.Path]::GetExtension([string]$_).Equals(
            ".pth", [StringComparison]::OrdinalIgnoreCase
        )
    } | Sort-Object)
    if ($paths.Count -ne 2) {
        throw "qualified Python bootstrap requires exactly two reviewed .pth files"
    }

    $expectedSource = [IO.Path]::GetFullPath((Join-Path $RepoRoot "src"))
    if (-not (Test-Path -LiteralPath $expectedSource -PathType Container)) {
        throw "qualified Python editable source root is missing"
    }
    Assert-WeatherIntegrationRegularPathAncestry `
        -Path $expectedSource -Phase "qualified Python editable source root"
    $canonicalDistutils =
        "import os; var = 'SETUPTOOLS_USE_DISTUTILS'; enabled = os.environ.get(var, 'local') == 'local'; enabled and __import__('_distutils_hack').add_shim();"
    $snapshots = [Collections.Generic.List[object]]::new()
    $rows = [Collections.Generic.List[object]]::new()
    $editableCount = 0
    $distutilsCount = 0
    $transferred = $false
    $primaryFailure = $null
    try {
        foreach ($path in $paths) {
            $snapshot = Open-SuiteBoundedFileSnapshot `
                -Path $path -MaxBytes 1048576 -Label "Python .pth bootstrap file"
            $snapshots.Add($snapshot)
            $decoder = New-Object Text.UTF8Encoding($false, $true)
            try { $text = $decoder.GetString([byte[]]$snapshot.Bytes) }
            catch { throw "Python .pth bootstrap file is not strict UTF-8" }
            if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) {
                $text = $text.Substring(1)
            }
            if ($text.Contains([char]0)) {
                throw "Python .pth bootstrap file contains NUL"
            }
            $activeLines = @($text -split "`r?`n" | ForEach-Object {
                ([string]$_).Trim()
            } | Where-Object { $_ -and -not $_.StartsWith("#") })
            if ($activeLines.Count -ne 1) {
                throw "each reviewed Python .pth bootstrap file must have one active line"
            }
            $fileName = [IO.Path]::GetFileName([string]$path)
            $line = [string]$activeLines[0]
            $kind = ""
            if ($fileName -ceq "distutils-precedence.pth" -and
                $line -ceq $canonicalDistutils) {
                $kind = "distutils_precedence_guarded"
                $distutilsCount++
            }
            elseif ($fileName -cmatch '^__editable__\.weather_market-[0-9A-Za-z._-]+\.pth$' -and
                [IO.Path]::IsPathRooted($line) -and
                [IO.Path]::GetFullPath($line).Equals(
                    $expectedSource, [StringComparison]::OrdinalIgnoreCase
                )) {
                $kind = "editable_exact_production_src"
                $editableCount++
            }
            else {
                throw "Python .pth bootstrap contains unreviewed executable or path semantics"
            }
            $rows.Add([pscustomobject][ordered]@{
                path = [IO.Path]::GetFullPath([string]$path)
                length = [int]$snapshot.Length
                sha256 = [string]$snapshot.Sha256
                kind = $kind
            })
        }
        if ($editableCount -ne 1 -or $distutilsCount -ne 1) {
            throw "Python .pth bootstrap does not contain one exact editable path and one guarded distutils line"
        }
        $orderedRows = @($rows | Sort-Object { [string]$_.path })
        $canonicalJson = $orderedRows | ConvertTo-Json -Depth 4 -Compress
        $digest = [Security.Cryptography.SHA256]::Create()
        try {
            $sha256 = (([BitConverter]::ToString($digest.ComputeHash(
                [Text.Encoding]::UTF8.GetBytes($canonicalJson)
            ))) -replace '-', '').ToLowerInvariant()
        }
        finally { $digest.Dispose() }
        foreach ($snapshot in @($snapshots)) {
            $suiteEvidenceReadStreams.Add($snapshot.Stream)
        }
        $transferred = $true
        return [pscustomobject]@{
            SitePackages = $sitePackages
            Rows = $orderedRows
            FileCount = $orderedRows.Count
            Sha256 = $sha256
        }
    }
    catch {
        $primaryFailure = $_
        throw
    }
    finally {
        if (-not $transferred) {
            $cleanupFailures = [Collections.Generic.List[string]]::new()
            foreach ($snapshot in @($snapshots)) {
                try { $snapshot.Stream.Dispose() }
                catch { $cleanupFailures.Add($_.Exception.Message) }
            }
            if ($cleanupFailures.Count -gt 0) {
                $cleanupMessage =
                    "Python .pth retained-handle cleanup failed: $($cleanupFailures -join '; ')"
                if ($null -ne $primaryFailure) {
                    $primaryFailure.Exception.Data[
                        "weather_pth_cleanup_failure"
                    ] = $cleanupMessage
                    Write-Warning $cleanupMessage -WarningAction Continue
                }
                else { throw $cleanupMessage }
            }
        }
    }
}

function Assert-SuiteQualifiedPthBootstrapUnchanged {
    param([Parameter(Mandatory = $true)][string]$Phase)

    if ($null -eq $suitePthBootstrap) {
        throw "$Phase qualified .pth bootstrap binding is unavailable"
    }
    $currentPaths = @([IO.Directory]::EnumerateFiles(
        [string]$suitePthBootstrap.SitePackages,
        "*", [IO.SearchOption]::TopDirectoryOnly
    ) | Where-Object {
        [IO.Path]::GetExtension([string]$_).Equals(
            ".pth", [StringComparison]::OrdinalIgnoreCase
        )
    } | ForEach-Object { [IO.Path]::GetFullPath([string]$_) } | Sort-Object)
    $expectedPaths = @($suitePthBootstrap.Rows | ForEach-Object {
        [string]$_.path
    })
    if (($currentPaths -join "`n") -cne ($expectedPaths -join "`n")) {
        throw "$Phase Python .pth namespace changed after qualification"
    }
    foreach ($row in @($suitePthBootstrap.Rows)) {
        $current = Open-SuiteBoundedFileSnapshot `
            -Path ([string]$row.path) -MaxBytes 1048576 `
            -Label "$Phase Python .pth recheck"
        try {
            if ([int]$current.Length -ne [int]$row.length -or
                [string]$current.Sha256 -cne [string]$row.sha256) {
                throw "$Phase Python .pth bytes changed after qualification"
            }
        }
        finally { $current.Stream.Dispose() }
    }
}

function Remove-SuiteOwnedPythonChildOutput {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    $ownedPrefix = [IO.Path]::GetFullPath($LogPath) + ".python-child."
    if (-not $fullPath.StartsWith($ownedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        ($fullPath -cnotmatch '\.(stdout|stderr)\.txt$')) {
        throw "refusing to clean a non-owned Python child output: $fullPath"
    }
    if (-not (Test-Path -LiteralPath $fullPath)) { return }
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "refusing to clean non-file Python child output: $fullPath"
    }
    $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "refusing to clean reparse-point Python child output: $fullPath"
    }
    Remove-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $fullPath) {
        throw "suite-owned Python child output cleanup was not proved: $fullPath"
    }
}

function New-SuiteChildOutputRoot {
    Assert-SuiteFrozenSystemTempRoot -Phase "suite child-output root creation"
    $root = Join-Path $suiteSystemTempRoot (
        "weather-bounded-suite-output-{0}" -f ([guid]::NewGuid().ToString("N"))
    )
    if (Test-Path -LiteralPath $root) {
        throw "unique suite child-output root already exists: $root"
    }
    [void][IO.Directory]::CreateDirectory($root)
    $item = Get-Item -LiteralPath $root -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        @([IO.Directory]::EnumerateFileSystemEntries($root)).Count -ne 0) {
        throw "suite child-output root is not a new empty regular directory"
    }
    return [IO.Path]::GetFullPath($root)
}

function Remove-SuiteOwnedJUnitTemp {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([string]::IsNullOrWhiteSpace([string]$suiteChildOutputRoot)) {
        throw "suite child-output root is unavailable"
    }
    $fullRoot = [IO.Path]::GetFullPath($suiteChildOutputRoot)
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not [IO.Path]::GetDirectoryName($fullPath).Equals(
            $fullRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [IO.Path]::GetFileName($fullPath) -cnotmatch
            '^chunk-[0-9]{3}-[0-9a-f]{32}\.xml$') {
        throw "refusing to clean a non-owned test-child JUnit file: $fullPath"
    }
    if (-not (Test-Path -LiteralPath $fullPath)) { return }
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "refusing to clean a non-file test-child JUnit path: $fullPath"
    }
    $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "refusing to clean a reparse-point test-child JUnit file"
    }
    Remove-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $fullPath) {
        throw "test-child JUnit cleanup was not proved: $fullPath"
    }
}

function Remove-SuiteChildOutputRoot {
    if ([string]::IsNullOrWhiteSpace([string]$suiteChildOutputRoot)) { return }
    $fullRoot = [IO.Path]::GetFullPath($suiteChildOutputRoot)
    if (-not [IO.Path]::GetDirectoryName($fullRoot).Equals(
            $suiteSystemTempRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [IO.Path]::GetFileName($fullRoot) -cnotmatch
            '^weather-bounded-suite-output-[0-9a-f]{32}$') {
        throw "refusing to clean a non-owned suite child-output root: $fullRoot"
    }
    if (-not (Test-Path -LiteralPath $fullRoot)) { return }
    $item = Get-Item -LiteralPath $fullRoot -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "refusing to clean a non-directory or reparse-point suite child-output root"
    }
    foreach ($entry in @([IO.Directory]::EnumerateFileSystemEntries($fullRoot))) {
        Remove-SuiteOwnedJUnitTemp -Path $entry
    }
    if (@([IO.Directory]::EnumerateFileSystemEntries($fullRoot)).Count -ne 0) {
        throw "suite child-output root remained nonempty after exact-file cleanup"
    }
    Remove-Item -LiteralPath $fullRoot -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $fullRoot) {
        throw "suite child-output root cleanup was not proved: $fullRoot"
    }
}

function New-SuitePytestTempRoot {
    Assert-SuiteFrozenSystemTempRoot -Phase "suite pytest-temp root creation"
    $root = Join-Path $suiteSystemTempRoot (
        "weather-bounded-pytest-temp-{0}" -f ([guid]::NewGuid().ToString("N"))
    )
    if (Test-Path -LiteralPath $root) {
        throw "unique suite pytest-temp root already exists: $root"
    }
    [void][IO.Directory]::CreateDirectory($root)
    $item = Get-Item -LiteralPath $root -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        @([IO.Directory]::EnumerateFileSystemEntries($root)).Count -ne 0) {
        throw "suite pytest-temp root is not a new empty regular directory"
    }
    return [IO.Path]::GetFullPath($root)
}

function Assert-SuiteMinimumFreeBytes {
    param(
        [Parameter(Mandatory = $true)][int64]$AvailableBytes,
        [Parameter(Mandatory = $true)][int64]$RequiredBytes,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($RequiredBytes -ne 53687091200) {
        throw "$Label did not use the canonical 50-GiB free-space floor"
    }
    if ($AvailableBytes -lt $RequiredBytes) {
        throw "$Label requires at least 50 GiB of available local disk"
    }
}

function Assert-SuiteRelevantVolumeFreeSpace {
    param([Parameter(Mandatory = $true)][string]$Phase)

    $relevantPaths = [ordered]@{
        worktree = $WorktreeRoot
        production_data = (Join-Path $RepoRoot "data")
        evidence_log = $logParent
        pytest_temp = if ([string]::IsNullOrWhiteSpace(
                [string]$suitePytestTempRoot
            )) {
                $suiteSystemTempRoot
            }
            else { $suitePytestTempRoot }
        system_temp = $suiteSystemTempRoot
    }
    foreach ($role in $relevantPaths.Keys) {
        $path = [IO.Path]::GetFullPath([string]$relevantPaths[$role])
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            throw "$Phase free-space path for $role is missing: $path"
        }
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $path -Phase "$Phase free-space $role"
        $volumeRoot = [IO.Path]::GetPathRoot($path)
        if ([string]::IsNullOrWhiteSpace($volumeRoot)) {
            throw "$Phase could not resolve the $role volume"
        }
        $drive = [IO.DriveInfo]::new($volumeRoot)
        if (-not $drive.IsReady) {
            throw "$Phase $role volume is not ready: $volumeRoot"
        }
        $availableBytes = [int64]$drive.AvailableFreeSpace
        Assert-SuiteMinimumFreeBytes `
            -AvailableBytes $availableBytes -RequiredBytes 53687091200 `
            -Label "$Phase $role volume $volumeRoot"
        Write-SuiteLog (
            "disk_free phase=$Phase role=$role volume=$volumeRoot " +
            "required_bytes=53687091200 available_bytes=$availableBytes passed=true"
        )
    }
}

function Remove-SuiteOwnedPytestTemp {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([string]::IsNullOrWhiteSpace([string]$suitePytestTempRoot)) {
        throw "suite pytest-temp root is unavailable"
    }
    $fullRoot = [IO.Path]::GetFullPath($suitePytestTempRoot)
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not [IO.Path]::GetDirectoryName($fullPath).Equals(
            $fullRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [IO.Path]::GetFileName($fullPath) -cnotmatch
            '^chunk-[0-9]{3}-[0-9a-f]{32}$') {
        throw "refusing to clean a non-owned pytest temp path: $fullPath"
    }
    if (-not (Test-Path -LiteralPath $fullPath)) { return }
    $rootItem = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (-not $rootItem.PSIsContainer -or
        ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "refusing to clean a non-directory or reparse-point pytest temp path"
    }
    [int]$entryCount = 0
    [int64]$totalBytes = 0
    $pendingDirectories = [Collections.Generic.Stack[string]]::new()
    $pendingDirectories.Push($fullPath)
    while ($pendingDirectories.Count -gt 0) {
        $directory = $pendingDirectories.Pop()
        foreach ($entry in [IO.Directory]::EnumerateFileSystemEntries($directory)) {
            $entryCount++
            if ($entryCount -gt 100000) {
                throw "pytest temp exceeded its 100000-entry cleanup bound"
            }
            $item = Get-Item -LiteralPath $entry -Force -ErrorAction Stop
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "pytest temp contains a forbidden reparse point"
            }
            if ($item.PSIsContainer) {
                # Inspect a directory's attributes before ever handing it to
                # another enumeration call; recursive enumeration can follow
                # a reparse point before the caller gets to reject its entry.
                $pendingDirectories.Push([string]$item.FullName)
                continue
            }
            $totalBytes += [int64]$item.Length
            if ($totalBytes -gt 1073741824) {
                throw "pytest temp exceeded its 1-GiB cleanup bound"
            }
        }
    }
    Remove-Item -LiteralPath $fullPath -Recurse -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $fullPath) {
        throw "pytest temp cleanup was not proved: $fullPath"
    }
    Write-SuiteLog (
        "pytest_temp_cleanup policy=system_temp_unique_v1 " +
        "entries=$entryCount bytes=$totalBytes proved=true"
    )
}

function Remove-SuitePytestTempRoot {
    if ([string]::IsNullOrWhiteSpace([string]$suitePytestTempRoot)) { return }
    $fullRoot = [IO.Path]::GetFullPath($suitePytestTempRoot)
    if (-not [IO.Path]::GetDirectoryName($fullRoot).Equals(
            $suiteSystemTempRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [IO.Path]::GetFileName($fullRoot) -cnotmatch
            '^weather-bounded-pytest-temp-[0-9a-f]{32}$') {
        throw "refusing to clean a non-owned suite pytest-temp root: $fullRoot"
    }
    if (-not (Test-Path -LiteralPath $fullRoot)) { return }
    $item = Get-Item -LiteralPath $fullRoot -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "refusing to clean a non-directory or reparse-point suite pytest-temp root"
    }
    foreach ($entry in @([IO.Directory]::EnumerateFileSystemEntries($fullRoot))) {
        Remove-SuiteOwnedPytestTemp -Path $entry
    }
    if (@([IO.Directory]::EnumerateFileSystemEntries($fullRoot)).Count -ne 0) {
        throw "suite pytest-temp root remained nonempty after exact cleanup"
    }
    Remove-Item -LiteralPath $fullRoot -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $fullRoot) {
        throw "suite pytest-temp root cleanup was not proved: $fullRoot"
    }
}

function Invoke-SuitePythonChild {
    param(
        [Parameter(Mandatory = $true)][object[]]$Tokens,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Phase,
        [ValidateRange(1024, 16777216)][int]$MaxOutputBytes = 1048576
    )

    Assert-SuitePythonCacheRoot
    Assert-SuitePythonGitTopologyClear -Phase $Phase
    Assert-SuiteQualifiedPthBootstrapUnchanged -Phase $Phase
    if ((Get-Date) -ge $hardStop) {
        throw "$Phase cannot start at or after the 09:00 hard teardown boundary"
    }
    if (Test-SuiteRuntimeCeilingReached) {
        throw "$Phase cannot start at or after the bounded-suite runtime ceiling"
    }
    $argumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $Tokens
    $outputTag = [guid]::NewGuid().ToString("N")
    $stdoutPath = "$LogPath.python-child.$outputTag.stdout.txt"
    $stderrPath = "$LogPath.python-child.$outputTag.stderr.txt"
    if ((Test-Path -LiteralPath $stdoutPath) -or
        (Test-Path -LiteralPath $stderrPath)) {
        throw "$Phase unique redirected output already exists"
    }
    $job = $null
    $process = $null
    $primaryFailure = $null
    $observedChildExitCode = $null
    try {
        $job = New-WeatherKillOnCloseJob
        $pythonGitEnvironment = $null
        $launchFailure = $null
        try {
            $pythonGitEnvironment = @(
                Enter-SuiteQualifiedPythonGitEnvironment -Phase $Phase
            )
            $process = Start-WeatherProcessInJobWithRedirectedOutput `
                -Job $job -FilePath $python `
                -ArgumentString $argumentString -WorkingDirectory $WorkingDirectory `
                -StandardOutputPath $stdoutPath -StandardErrorPath $stderrPath
        }
        catch {
            $launchFailure = $_
            throw
        }
        finally {
            if ($null -ne $pythonGitEnvironment) {
                Exit-SuiteQualifiedPythonGitEnvironment `
                    -Restorations @($pythonGitEnvironment) -Phase $Phase `
                    -PrimaryError $launchFailure
            }
        }
        while (-not $process.WaitForExit(200)) {
            if ((Get-Date) -ge $hardStop) {
                Write-SuiteLog "$Phase reached 09:00; killing its complete child tree"
                throw "$Phase reached the 09:00 hard teardown boundary"
            }
            if (Test-SuiteRuntimeCeilingReached) {
                Write-SuiteLog "$Phase reached its runtime ceiling; killing its complete child tree"
                throw "$Phase reached the bounded-suite runtime ceiling"
            }
            $stdoutLength = [int64]$process.GetStandardOutputLength()
            $stderrLength = [int64]$process.GetStandardErrorLength()
            if ($stdoutLength -gt $MaxOutputBytes -or $stderrLength -gt $MaxOutputBytes) {
                throw (
                    "$Phase redirected output exceeded its $MaxOutputBytes-byte contract " +
                    "(stdout=$stdoutLength stderr=$stderrLength)"
                )
            }
        }
        $process.WaitForExit()
        $exitCode = [int]$process.ExitCode
        $observedChildExitCode = $exitCode
        # A top-level exit is not a child-tree proof. Drain the Job's active
        # process count before treating retained stdout/stderr as immutable.
        $job.TerminateAndWaitForEmpty(5000)
        $job = $null
        Assert-SuitePythonCacheRoot
        [byte[]]$stdoutBytes = $process.ReadStandardOutputBytes($MaxOutputBytes)
        [byte[]]$stderrBytes = $process.ReadStandardErrorBytes($MaxOutputBytes)
        $stdoutSnapshot = New-SuiteUtf8Snapshot -Bytes $stdoutBytes -Label "$Phase stdout"
        $stderrSnapshot = New-SuiteUtf8Snapshot -Bytes $stderrBytes -Label "$Phase stderr"
        $stdoutEvidencePath = "$LogPath.python-diagnostic.$outputTag.stdout.txt"
        $stderrEvidencePath = "$LogPath.python-diagnostic.$outputTag.stderr.txt"
        Write-SuiteRetainedByteSidecar `
            -Path $stdoutEvidencePath -Bytes $stdoutSnapshot.Bytes | Out-Null
        Write-SuiteRetainedByteSidecar `
            -Path $stderrEvidencePath -Bytes $stderrSnapshot.Bytes | Out-Null
        Write-SuiteLog (
            "python_child phase=$Phase exit=$exitCode " +
            "stdout_path=$stdoutEvidencePath stdout_sha256=$($stdoutSnapshot.Sha256) " +
            "stderr_path=$stderrEvidencePath stderr_sha256=$($stderrSnapshot.Sha256)"
        )
        return [pscustomobject]@{
            ExitCode = $exitCode
            Stdout = $stdoutSnapshot.Text
            Stderr = $stderrSnapshot.Text
            StdoutSha256 = $stdoutSnapshot.Sha256
            StderrSha256 = $stderrSnapshot.Sha256
            StdoutPath = $stdoutEvidencePath
            StderrPath = $stderrEvidencePath
        }
    }
    catch {
        $failure = $_
        if ($null -ne $observedChildExitCode -and $observedChildExitCode -ne 0) {
            $postExitMessage = $failure.Exception.Message
            $combinedException = [InvalidOperationException]::new(
                (
                    "$Phase child exited with code $observedChildExitCode; " +
                    "post-exit containment or evidence processing failed: $postExitMessage"
                ),
                $failure.Exception
            )
            $combinedException.Data["weather_observed_child_exit_code"] =
                [int]$observedChildExitCode
            $combinedException.Data["weather_post_exit_failure"] = $postExitMessage
            $failure = [Management.Automation.ErrorRecord]::new(
                $combinedException,
                "WeatherSuiteChildExitAndPostExitFailure",
                [Management.Automation.ErrorCategory]::OperationStopped,
                $null
            )
        }
        if ($job) {
            try {
                $job.TerminateAndWaitForEmpty(5000)
                $job = $null
            }
            catch {
                $drainMessage = $_.Exception.Message
                $failure.Exception.Data["weather_tree_drain_failure"] = $drainMessage
                Write-Warning "$Phase child-tree drain retry failed: $drainMessage" `
                    -WarningAction Continue
            }
        }
        $primaryFailure = $failure
        throw $failure
    }
    finally {
        $cleanupFailures = New-Object System.Collections.Generic.List[string]
        if ($job) {
            try { $job.Dispose() }
            catch { $cleanupFailures.Add("Job handle: $($_.Exception.Message)") }
        }
        if ($process) {
            try { $process.Dispose() }
            catch {
                $cleanupFailures.Add(
                    "retained process/output handles: $($_.Exception.Message)"
                )
            }
        }
        foreach ($path in @($stdoutPath, $stderrPath)) {
            try { Remove-SuiteOwnedPythonChildOutput -Path $path }
            catch { $cleanupFailures.Add("output file: $($_.Exception.Message)") }
        }
        if ($cleanupFailures.Count -ne 0) {
            $cleanupMessage = "$Phase cleanup failed: $($cleanupFailures -join ' | ')"
            if ($null -ne $primaryFailure) {
                $primaryFailure.Exception.Data["weather_cleanup_failure"] = $cleanupMessage
                Write-Warning $cleanupMessage -WarningAction Continue
            }
            elseif ($null -ne $observedChildExitCode -and $observedChildExitCode -ne 0) {
                $exitFailure = [InvalidOperationException]::new(
                    "$Phase child exited with code $observedChildExitCode; $cleanupMessage"
                )
                $exitFailure.Data["weather_observed_child_exit_code"] =
                    [int]$observedChildExitCode
                $exitFailure.Data["weather_cleanup_failure"] = $cleanupMessage
                throw $exitFailure
            }
            else { throw $cleanupMessage }
        }
    }
}

function Assert-NoIgnoredPythonImportArtifacts {
    # The fresh PYTHONPYCACHEPREFIX isolates ordinary cache lookup, but ignored
    # source/config shadows, legacy sourceless bytecode, and native extensions
    # can still alter import or pytest behavior. Scope discovery to the root
    # singleton controls and Python/pytest import roots; ignored data/ is
    # runtime evidence, not executable test authority. `--exclude-standard`
    # includes repository, info/exclude, and global excludes.
    $blockedExtensions = @(
        ".py", ".pyi", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib",
        ".pem", ".key", ".p12", ".pfx"
    )
    $blockedControlNames = @(
        "sitecustomize.py", "usercustomize.py", "conftest.py", "pytest.ini",
        "pyproject.toml", "tox.ini", "setup.cfg", ".python-version", ".env",
        ".netrc", "pip.ini", ".pypirc"
    )
    $trackedNamespaceQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments (@("ls-files", "-z", "--") + @(
            "*.py", "*.pyi", "*.pyd", "*.so", "*.dll", "*.dylib"
        )) `
        -MaxOutputBytes 16777216 `
        -Label "tracked Python/native namespace query"
    if (-not [string]::IsNullOrWhiteSpace([string]$trackedNamespaceQuery.Stderr)) {
        throw "tracked Python/native namespace query emitted unexpected stderr"
    }
    $trackedImportRoots = @(
        @(Split-SuiteNulRecords `
            -Text ([string]$trackedNamespaceQuery.Stdout) `
            -Label "tracked Python/native namespace query") |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object { $_ -match '/' } |
            ForEach-Object { ([string]$_ -split '/', 2)[0] } |
            Where-Object {
                $_ -and $_ -notin @("data", "venv", ".venv", ".git")
            }
    )
    $importRoots = @(
        @("app", "src", "tests", "weather", "tools", "scripts", "__pycache__") +
        @($trackedImportRoots) | Sort-Object -Unique
    )
    $rootExtensionPathspecs = @($blockedExtensions | ForEach-Object {
        ":(glob)*$_"
    })
    $importRootPathspecs = @($importRoots | ForEach-Object {
        ":(glob)$_/**"
    })
    $importControlPathspecs = @(
        @($blockedControlNames) + @(
            ":(glob).env.*", ":(glob)*credential*", ":(glob)credentials*",
            ":(glob)id_rsa*", ":(glob)id_ed25519*"
        ) + $rootExtensionPathspecs + $importRootPathspecs
    )
    $candidateRows = [Collections.Generic.List[string]]::new()
    foreach ($querySpec in @(
        [pscustomobject]@{
            Arguments = @(
                "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--"
            ) + $importControlPathspecs
            Label = "ignored candidate autoload/secret namespace query"
        },
        [pscustomobject]@{
            Arguments = @(
                "ls-files", "--others", "--exclude-standard", "-z", "--"
            ) + $importControlPathspecs
            Label = "untracked candidate autoload/secret namespace query"
        }
    )) {
        $query = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $WorktreeRoot -Arguments @($querySpec.Arguments) `
            -MaxOutputBytes 16777216 -Label ([string]$querySpec.Label)
        if (-not [string]::IsNullOrWhiteSpace([string]$query.Stderr)) {
            throw "$([string]$querySpec.Label) emitted unexpected stderr"
        }
        foreach ($row in @(Split-SuiteNulRecords `
            -Text ([string]$query.Stdout) -Label ([string]$querySpec.Label))) {
            $candidateRows.Add([string]$row)
        }
    }
    $ignoredArtifacts = @(
        $candidateRows |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object {
                if ([string]::IsNullOrWhiteSpace($_)) { return $false }
                $leaf = [IO.Path]::GetFileName([string]$_)
                $extension = [IO.Path]::GetExtension([string]$_)
                $isRootControl = ([string]$_ -notmatch '/' -and
                    ($blockedControlNames -icontains $leaf -or
                     $leaf -imatch '^\.env\..+' -or
                     $leaf -imatch '(?:credential|credentials|id_rsa|id_ed25519)'))
                $isRootExtension = ([string]$_ -notmatch '/' -and
                    $blockedExtensions -icontains $extension)
                $isImportRootArtifact = ([string]$_ -match
                    ("^(?i:" + (($importRoots | ForEach-Object {
                        [regex]::Escape([string]$_)
                    }) -join '|') + ")/") -and
                    ($blockedControlNames -icontains $leaf -or
                     $blockedExtensions -icontains $extension -or
                     $leaf -imatch '^\.env(?:\..+)?$' -or
                     $leaf -imatch '(?:credential|credentials|id_rsa|id_ed25519)'))
                return ($isRootControl -or $isRootExtension -or $isImportRootArtifact)
            } |
            Sort-Object -Unique
    )
    if ($ignoredArtifacts.Count -ne 0) {
        $sample = @($ignoredArtifacts | Select-Object -First 10) -join ", "
        throw "ignored/untracked candidate autoload, import, or secret artifacts are forbidden: $sample"
    }
}

function Split-SuiteNulRecords {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ([string]::IsNullOrEmpty($Text)) { return }
    if ($Text[$Text.Length - 1] -cne [char]0) {
        throw "$Label did not end at an exact NUL record boundary"
    }
    $parts = @($Text.Split([char]0))
    if ($parts.Count -lt 2 -or
        -not [string]::IsNullOrEmpty([string]$parts[$parts.Count - 1])) {
        throw "$Label has malformed NUL record framing"
    }
    if ($parts.Count -gt 1) { return @($parts[0..($parts.Count - 2)]) }
}

function Get-SuiteRetainedStreamSha256 {
    param(
        [Parameter(Mandatory = $true)][IO.FileStream]$Stream,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not $Stream.CanRead -or -not $Stream.CanSeek) {
        throw "$Label retained stream is no longer readable and seekable"
    }
    $declaredLength = [int64]$Stream.Length
    $Stream.Position = 0
    $sha = [Security.Cryptography.SHA256]::Create()
    [byte[]]$buffer = [byte[]]::new(1048576)
    [int64]$observedLength = 0
    try {
        while ($true) {
            if ((Get-Date) -ge $hardStop) {
                throw "$Label reached the 09:00 hard teardown boundary while hashing"
            }
            if (Test-SuiteRuntimeCeilingReached) {
                throw "$Label reached the bounded-suite runtime ceiling while hashing"
            }
            $read = $Stream.Read($buffer, 0, $buffer.Length)
            if ($read -eq 0) { break }
            if ($read -lt 0) { throw "$Label returned a negative retained read length" }
            [void]$sha.TransformBlock($buffer, 0, $read, $buffer, 0)
            $observedLength += $read
        }
        [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
        if ($observedLength -ne $declaredLength -or
            [int64]$Stream.Length -ne $declaredLength) {
            throw "$Label length changed during its retained hash"
        }
        return (([BitConverter]::ToString($sha.Hash)) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $Stream.Position = 0
        $sha.Dispose()
    }
}

function Test-SuiteRuntimeCeilingReached {
    if ($null -eq $runtimeStopwatch) {
        throw "bounded-suite monotonic runtime clock is unavailable"
    }
    return (
        [double]$runtimeStopwatch.Elapsed.TotalSeconds -ge
            [double]$MaxRuntimeSeconds
    )
}

function Get-SuiteTrackedWorktreeFingerprint {
    param(
        [Parameter(Mandatory = $true)][string]$Phase,
        [switch]$RetainStreams,
        [switch]$ReuseRetainedStreams
    )

    if ($RetainStreams.IsPresent -and $ReuseRetainedStreams.IsPresent) {
        throw "tracked-worktree fingerprint cannot both create and reuse retained streams"
    }
    if ($RetainStreams.IsPresent -and $suiteTrackedBaseline.Count -ne 0) {
        throw "tracked-worktree baseline streams were already created"
    }
    if ($ReuseRetainedStreams.IsPresent -and $suiteTrackedBaseline.Count -eq 0) {
        throw "tracked-worktree baseline streams are missing"
    }

    $headRows = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}") `
        -Label "tracked-worktree $Phase exact HEAD query").StdoutLines)
    if ($headRows.Count -ne 1 -or
        ([string]$headRows[0]).Trim().ToLowerInvariant() -ne $ExpectedTip) {
        throw "tracked-worktree $Phase HEAD does not match ExpectedTip"
    }

    $stageQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("ls-files", "--stage", "-z") `
        -MaxOutputBytes 16777216 `
        -Label "tracked-worktree $Phase staged inventory"
    $flagQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("ls-files", "-v", "-z") `
        -MaxOutputBytes 16777216 `
        -Label "tracked-worktree $Phase index-flag inventory"
    $lfsQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("ls-files", "-z", "--", ":(attr:filter=lfs)") `
        -MaxOutputBytes 16777216 `
        -Label "tracked-worktree $Phase LFS inventory"
    foreach ($queryResult in @($stageQuery, $flagQuery, $lfsQuery)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$queryResult.Stderr)) {
            throw "tracked-worktree $Phase Git inventory emitted unexpected stderr"
        }
    }

    $stageByPath = [Collections.Generic.Dictionary[string, object]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($row in @(Split-SuiteNulRecords `
        -Text ([string]$stageQuery.Stdout) -Label "tracked staged inventory")) {
        if ([string]$row -cnotmatch
            '^(?<mode>[0-9]{6}) (?<oid>(?:[0-9a-f]{40}|[0-9a-f]{64})) (?<stage>[0-3])\t(?<path>.+)$') {
            throw "tracked-worktree $Phase staged inventory contains a malformed row"
        }
        $relativePath = [string]$Matches.path
        if ([string]$Matches.stage -cne "0" -or
            [string]$Matches.mode -notin @("100644", "100755")) {
            throw "tracked-worktree $Phase refuses non-stage-zero or non-regular tracked entries"
        }
        if ($stageByPath.ContainsKey($relativePath)) {
            throw "tracked-worktree $Phase staged inventory contains a duplicate path"
        }
        $stageByPath.Add($relativePath, [pscustomobject]@{
            Mode = [string]$Matches.mode
            BlobOid = [string]$Matches.oid
        })
    }
    if ($stageByPath.Count -lt 1 -or $stageByPath.Count -gt 20000) {
        throw "tracked-worktree $Phase file count is outside the 1..20000 bound"
    }

    $flagByPath = [Collections.Generic.Dictionary[string, string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($row in @(Split-SuiteNulRecords `
        -Text ([string]$flagQuery.Stdout) -Label "tracked index-flag inventory")) {
        if ([string]$row -cnotmatch '^(?<flag>.) (?<path>.+)$') {
            throw "tracked-worktree $Phase index-flag inventory contains a malformed row"
        }
        $relativePath = [string]$Matches.path
        if ([string]$Matches.flag -cne "H") {
            throw (
                "tracked-worktree $Phase refuses assume-unchanged, skip-worktree, " +
                "or nonordinary index flags"
            )
        }
        if ($flagByPath.ContainsKey($relativePath)) {
            throw "tracked-worktree $Phase index-flag inventory contains a duplicate path"
        }
        $flagByPath.Add($relativePath, [string]$Matches.flag)
    }
    if ($flagByPath.Count -ne $stageByPath.Count) {
        throw "tracked-worktree $Phase staged and index-flag inventories disagree"
    }
    foreach ($relativePath in $stageByPath.Keys) {
        if (-not $flagByPath.ContainsKey($relativePath)) {
            throw "tracked-worktree $Phase index-flag inventory omitted a tracked path"
        }
    }

    $lfsPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($row in @(Split-SuiteNulRecords `
        -Text ([string]$lfsQuery.Stdout) -Label "tracked LFS inventory")) {
        $relativePath = [string]$row
        if ([string]::IsNullOrWhiteSpace($relativePath) -or
            -not $stageByPath.ContainsKey($relativePath) -or
            -not $lfsPaths.Add($relativePath)) {
            throw "tracked-worktree $Phase LFS inventory is malformed or inconsistent"
        }
    }

    [string[]]$sortedPaths = @($stageByPath.Keys)
    [Array]::Sort($sortedPaths, [StringComparer]::Ordinal)
    $rootPrefix = $WorktreeRoot.TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    ) + [IO.Path]::DirectorySeparatorChar
    $entries = [Collections.Generic.List[object]]::new()
    $digestRows = [Text.StringBuilder]::new()
    [int64]$totalBytes = 0
    [int]$lfsFileCount = 0
    foreach ($relativePath in $sortedPaths) {
        if ([string]$relativePath -match '[\x00-\x1f\x7f]' -or
            [string]$relativePath -match '\\' -or
            [IO.Path]::IsPathRooted([string]$relativePath) -or
            @(([string]$relativePath).Split('/') | Where-Object {
                [string]$_ -in @("", ".", "..")
            }).Count -ne 0) {
            throw "tracked-worktree $Phase refuses a noncanonical tracked path"
        }
        $fullPath = [IO.Path]::GetFullPath(
            (Join-Path $WorktreeRoot ([string]$relativePath).Replace('/', '\'))
        )
        if (-not $fullPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            throw "tracked-worktree $Phase tracked path escaped or is missing: $relativePath"
        }
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $fullPath -Phase "tracked-worktree $Phase file"
        $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        if ($item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            [int64]$item.Length -lt 0 -or [int64]$item.Length -gt 2147483648) {
            throw "tracked-worktree $Phase refuses a nonregular or oversized tracked file"
        }
        $totalBytes += [int64]$item.Length
        if ($totalBytes -gt 4294967296) {
            throw "tracked-worktree $Phase aggregate bytes exceed the 4-GiB bound"
        }

        $stream = $null
        $disposeStream = $false
        if ($ReuseRetainedStreams.IsPresent) {
            if (-not $suiteTrackedBaseline.ContainsKey($relativePath)) {
                throw "tracked-worktree $Phase retained baseline omitted a tracked path"
            }
            $baseline = $suiteTrackedBaseline[$relativePath]
            if (-not ([string]$baseline.FullPath).Equals(
                    $fullPath,
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                throw "tracked-worktree $Phase retained path identity changed"
            }
            $stream = $baseline.Stream
        }
        else {
            $stream = [IO.File]::Open(
                $fullPath,
                [IO.FileMode]::Open,
                [IO.FileAccess]::Read,
                [IO.FileShare]::Read
            )
            $disposeStream = $true
        }
        try {
            if ([int64]$stream.Length -ne [int64]$item.Length) {
                throw "tracked-worktree $Phase retained/file namespace length disagrees"
            }
            $worktreeSha256 = Get-SuiteRetainedStreamSha256 `
                -Stream $stream -Label "tracked-worktree $Phase $relativePath"
            $stageIdentity = $stageByPath[$relativePath]
            $lfsOid = $null
            $lfsSize = $null
            if ($lfsPaths.Contains($relativePath)) {
                $lfsFileCount++
                if ($ReuseRetainedStreams.IsPresent) {
                    $lfsOid = [string]$baseline.LfsOid
                    $lfsSize = [int64]$baseline.LfsSize
                    if ([string]::IsNullOrWhiteSpace($lfsOid) -or
                        $lfsOid -cnotmatch '^[0-9a-f]{64}$' -or
                        [string]$baseline.BlobOid -cne [string]$stageIdentity.BlobOid) {
                        throw "tracked-worktree $Phase retained LFS pointer identity changed"
                    }
                }
                else {
                    $pointerQuery = Invoke-WeatherIntegrationCheckedLocalGit `
                        -Root $WorktreeRoot `
                        -Arguments @("cat-file", "blob", [string]$stageIdentity.BlobOid) `
                        -MaxOutputBytes 4096 `
                        -Label "tracked-worktree $Phase LFS pointer $relativePath"
                    if (-not [string]::IsNullOrWhiteSpace([string]$pointerQuery.Stderr) -or
                        [string]$pointerQuery.Stdout -cnotmatch
                            '\Aversion https://git-lfs\.github\.com/spec/v1\noid sha256:(?<oid>[0-9a-f]{64})\nsize (?<size>0|[1-9][0-9]*)\n\z') {
                        throw "tracked-worktree $Phase LFS index blob is not a canonical pointer"
                    }
                    $lfsOid = [string]$Matches.oid
                    $parsedLfsSize = [int64]0
                    if (-not [int64]::TryParse(
                            [string]$Matches.size,
                            [Globalization.NumberStyles]::None,
                            [Globalization.CultureInfo]::InvariantCulture,
                            [ref]$parsedLfsSize
                        )) {
                        throw "tracked-worktree $Phase LFS pointer size is invalid"
                    }
                    $lfsSize = $parsedLfsSize
                }
                if ([int64]$item.Length -ne [int64]$lfsSize -or
                    $worktreeSha256 -cne $lfsOid) {
                    throw "tracked-worktree $Phase LFS worktree bytes do not match the index pointer"
                }
            }
            elseif ($ReuseRetainedStreams.IsPresent -and
                -not [string]::IsNullOrWhiteSpace([string]$baseline.LfsOid)) {
                throw "tracked-worktree $Phase LFS attribute membership changed"
            }

            $entry = [ordered]@{
                path = [string]$relativePath
                mode = [string]$stageIdentity.Mode
                blob_oid = [string]$stageIdentity.BlobOid
                worktree_length = [int64]$item.Length
                worktree_sha256 = $worktreeSha256
                lfs_oid = $lfsOid
                lfs_size = $lfsSize
            }
            $entries.Add([pscustomobject]$entry)
            $lfsOidToken = if ($null -eq $lfsOid) { "-" } else { [string]$lfsOid }
            $lfsSizeToken = if ($null -eq $lfsSize) { "-" } else {
                ([int64]$lfsSize).ToString([Globalization.CultureInfo]::InvariantCulture)
            }
            [void]$digestRows.AppendFormat(
                [Globalization.CultureInfo]::InvariantCulture,
                "{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}`n",
                [string]$relativePath,
                [string]$stageIdentity.Mode,
                [string]$stageIdentity.BlobOid,
                [int64]$item.Length,
                $worktreeSha256,
                $lfsOidToken,
                $lfsSizeToken
            )
            if ($RetainStreams.IsPresent) {
                $suiteEvidenceReadStreams.Add($stream)
                $suiteTrackedBaseline.Add($relativePath, [pscustomobject]@{
                    FullPath = $fullPath
                    Stream = $stream
                    BlobOid = [string]$stageIdentity.BlobOid
                    LfsOid = $lfsOid
                    LfsSize = $lfsSize
                })
                $stream = $null
            }
        }
        finally {
            if ($null -ne $stream -and $disposeStream) { $stream.Dispose() }
        }
    }
    if ($ReuseRetainedStreams.IsPresent -and
        $suiteTrackedBaseline.Count -ne $stageByPath.Count) {
        throw "tracked-worktree $Phase retained baseline contains a different path set"
    }

    $digestSnapshot = New-SuiteUtf8Snapshot `
        -Bytes ((New-Object Text.UTF8Encoding($false, $true)).GetBytes(
            $digestRows.ToString()
        )) `
        -Label "tracked-worktree $Phase canonical rows"
    $payload = [ordered]@{
        schema_version = "tracked_worktree_content_fingerprint_v1"
        content_sha256 = [string]$digestSnapshot.Sha256
        head = $ExpectedTip
        root = $WorktreeRoot
        file_count = [int]$entries.Count
        total_bytes = [int64]$totalBytes
        lfs_file_count = [int]$lfsFileCount
        entries = @($entries)
    }
    return [pscustomobject]@{
        Sha256 = [string]$digestSnapshot.Sha256
        FileCount = [int]$entries.Count
        TotalBytes = [int64]$totalBytes
        LfsFileCount = [int]$lfsFileCount
        Json = ($payload | ConvertTo-Json -Compress -Depth 6)
        Payload = [pscustomobject]$payload
    }
}

function Get-SuiteWorktreeAuthorityTuple {
    param([Parameter(Mandatory = $true)][string]$Phase)

    $registrationRows = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepoRoot `
        -Arguments @("worktree", "list", "--porcelain") `
        -Label "$Phase registered-worktree query").StdoutLines)
    $registeredMatches = @(
        $registrationRows |
            Where-Object { [string]$_ -clike "worktree *" } |
            ForEach-Object { [IO.Path]::GetFullPath(([string]$_).Substring(9)) } |
            Where-Object {
                $_.Equals($WorktreeRoot, [StringComparison]::OrdinalIgnoreCase)
            }
    )
    $worktreeTipRows = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}") `
        -Label "$Phase exact worktree-tip query").StdoutLines)
    $branchTipRows = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepoRoot `
        -Arguments @("rev-parse", "--verify", "--end-of-options", "${BranchRef}^{commit}") `
        -Label "$Phase exact branch-tip query").StdoutLines)
    $dirtyRows = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("status", "--porcelain=v1", "--untracked-files=all") `
        -Label "$Phase clean-worktree query").StdoutLines)
    Assert-NoIgnoredPythonImportArtifacts
    if ($registeredMatches.Count -ne 1 -or
        $worktreeTipRows.Count -ne 1 -or $branchTipRows.Count -ne 1 -or
        ([string]$worktreeTipRows[0]).Trim().ToLowerInvariant() -ne $ExpectedTip -or
        ([string]$branchTipRows[0]).Trim().ToLowerInvariant() -ne $ExpectedTip -or
        $dirtyRows.Count -ne 0) {
        throw "$Phase exact worktree/ref/clean authority tuple is invalid"
    }
    return [pscustomobject]@{
        WorktreeTip = ([string]$worktreeTipRows[0]).Trim().ToLowerInvariant()
        BranchTip = ([string]$branchTipRows[0]).Trim().ToLowerInvariant()
        RegisteredCount = [int]$registeredMatches.Count
        DirtyCount = [int]$dirtyRows.Count
        Canonical = (
            "worktree=$(([string]$worktreeTipRows[0]).Trim().ToLowerInvariant())`n" +
            "branch=$(([string]$branchTipRows[0]).Trim().ToLowerInvariant())`n" +
            "registered=$($registeredMatches.Count)`ndirty=$($dirtyRows.Count)`nignored=0`n"
        )
    }
}

function Assert-SuiteWorktreeCheckpoint {
    param([Parameter(Mandatory = $true)][string]$Phase)

    if ($null -eq $trackedWorktreePre) {
        throw "$Phase tracked-worktree baseline is missing"
    }
    $authorityBefore = Get-SuiteWorktreeAuthorityTuple -Phase "$Phase before"
    $fingerprint = Get-SuiteTrackedWorktreeFingerprint `
        -Phase $Phase -ReuseRetainedStreams
    $authorityAfter = Get-SuiteWorktreeAuthorityTuple -Phase "$Phase after"
    if ([string]$authorityBefore.Canonical -cne [string]$authorityAfter.Canonical) {
        throw "$Phase worktree authority tuple changed across its retained byte sample"
    }
    if ([string]$fingerprint.Sha256 -cne [string]$trackedWorktreePre.Sha256 -or
        [int]$fingerprint.FileCount -ne [int]$trackedWorktreePre.FileCount -or
        [int64]$fingerprint.TotalBytes -ne [int64]$trackedWorktreePre.TotalBytes -or
        [int]$fingerprint.LfsFileCount -ne [int]$trackedWorktreePre.LfsFileCount) {
        throw "$Phase tracked worktree content changed from the retained baseline"
    }
    Write-SuiteLog (
        "tracked_worktree_checkpoint phase=$Phase " +
        "sha256=$($fingerprint.Sha256) files=$($fingerprint.FileCount) " +
        "bytes=$($fingerprint.TotalBytes) lfs_files=$($fingerprint.LfsFileCount) " +
        "exact_tip=true clean=true ignored_import_artifacts=0"
    )
    return $fingerprint
}

function Get-SuitePythonEnvironmentFingerprint {
    param([Parameter(Mandatory = $true)][string]$Phase)

    $fingerprintCode = @'
import base64
import hashlib
import importlib.metadata as metadata
import json
import os
import pathlib
import platform
import re
import stat
import sys
import sysconfig

MAX_FILES = 120000
MAX_FILE_BYTES = 2147483648
MAX_TOTAL_BYTES = 8589934592
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
prefix_lexical = pathlib.Path(os.path.abspath(sys.prefix))
base_prefix_lexical = pathlib.Path(os.path.abspath(sys.base_prefix))
prefix = prefix_lexical.resolve(strict=True)
base_prefix = base_prefix_lexical.resolve(strict=True)
allowed_roots = tuple(dict.fromkeys((prefix, base_prefix)))
seen_content_paths = set()
totals = {"files": 0, "bytes": 0}

def fail(message):
    raise RuntimeError(message)

def normalized_name(value):
    result = re.sub(r"[-_.]+", "-", (value or "").strip().lower())
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", result):
        fail("distribution has an invalid normalized name")
    return result

def below(candidate, root):
    try:
        return os.path.commonpath((os.path.normcase(str(candidate)), os.path.normcase(str(root)))) == os.path.normcase(str(root))
    except ValueError:
        return False

def assert_regular_file(candidate, label):
    lexical = pathlib.Path(os.path.abspath(os.fspath(candidate)))
    resolved = lexical.resolve(strict=True)
    if not any(below(lexical, root) and below(resolved, root) for root in allowed_roots):
        fail(label + " escapes the approved Python roots")
    for authority_path in (lexical, resolved):
        current = pathlib.Path(authority_path.anchor)
        for part in authority_path.parts[1:]:
            current = current / part
            info = current.lstat()
            if getattr(info, "st_file_attributes", 0) & REPARSE:
                fail(label + " crosses a reparse point")
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size < 0 or info.st_size > MAX_FILE_BYTES:
        fail(label + " is not a bounded regular file")
    return resolved, info.st_size

def assert_regular_directory(candidate, expected, label):
    lexical = pathlib.Path(os.path.abspath(os.fspath(candidate)))
    resolved = lexical.resolve(strict=True)
    if resolved != expected or not any(
        below(lexical, root) and below(resolved, root) for root in allowed_roots
    ):
        fail(label + " escapes the approved Python roots")
    for authority_path in (lexical, resolved):
        current = pathlib.Path(authority_path.anchor)
        for part in authority_path.parts[1:]:
            current = current / part
            info = current.lstat()
            if getattr(info, "st_file_attributes", 0) & REPARSE:
                fail(label + " crosses a reparse point")
    if not resolved.is_dir():
        fail(label + " is not a regular directory")
    return lexical

prefix_lexical = assert_regular_directory(prefix_lexical, prefix, "Python prefix")
base_prefix_lexical = assert_regular_directory(
    base_prefix_lexical, base_prefix, "Python base prefix"
)

def content_row(candidate, label, record_hash=None, record_size=None, allow_blank=False):
    resolved, length = assert_regular_file(candidate, label)
    key = os.path.normcase(str(resolved))
    if key in seen_content_paths:
        fail("Python content inventory contains a duplicate path")
    seen_content_paths.add(key)
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        while True:
            block = handle.read(1048576)
            if not block:
                break
            digest.update(block)
    actual_sha256 = digest.hexdigest()
    record_algorithm = None
    record_digest = None
    normalized_record_size = None
    if record_hash is None or record_size is None:
        if not allow_blank or record_hash is not None or record_size is not None:
            fail(label + " has incomplete RECORD hash/size evidence")
    else:
        if record_hash.mode != "sha256" or not record_hash.value:
            fail(label + " does not use a RECORD sha256 digest")
        try:
            encoded = record_hash.value.encode("ascii")
            padding = b"=" * ((4 - len(encoded) % 4) % 4)
            declared = base64.b64decode(encoded + padding, altchars=b"-_", validate=True).hex()
        except Exception as error:
            raise RuntimeError(label + " has an unreadable RECORD digest") from error
        if not re.fullmatch(r"[0-9a-f]{64}", declared):
            fail(label + " has a non-SHA256 RECORD digest")
        try:
            normalized_record_size = int(record_size)
        except (TypeError, ValueError) as error:
            raise RuntimeError(label + " has an invalid RECORD size") from error
        if normalized_record_size != length or declared != actual_sha256:
            fail(label + " bytes do not match RECORD")
        record_algorithm = "sha256"
        record_digest = declared
    totals["files"] += 1
    totals["bytes"] += length
    if totals["files"] > MAX_FILES or totals["bytes"] > MAX_TOTAL_BYTES:
        fail("Python content inventory exceeded its global bounds")
    return {
        "path": str(resolved),
        "length": length,
        "sha256": actual_sha256,
        "record_algorithm": record_algorithm,
        "record_digest": record_digest,
        "record_size": normalized_record_size,
    }

distributions = []
seen_distributions = set()
for distribution in metadata.distributions():
    name = normalized_name(distribution.metadata.get("Name") or "")
    version = distribution.version or ""
    if not version:
        fail("distribution version is empty")
    location = pathlib.Path(distribution.locate_file("")).resolve(strict=True)
    if not any(below(location, root) for root in allowed_roots):
        fail("distribution location escapes approved Python roots")
    package_paths = list(distribution.files or ())
    if not package_paths:
        fail("distribution has no RECORD-backed files")
    record_candidates = [
        item for item in package_paths
        if pathlib.PurePosixPath(str(item).replace("\\", "/")).name == "RECORD"
        and pathlib.PurePosixPath(str(item).replace("\\", "/")).parent.name.endswith(".dist-info")
    ]
    if len(record_candidates) != 1:
        fail("distribution does not have one exact dist-info RECORD")
    record_path = pathlib.Path(distribution.locate_file(record_candidates[0])).resolve(strict=True)
    distribution_key = (name, version, os.path.normcase(str(location)), os.path.normcase(str(record_path)))
    if distribution_key in seen_distributions:
        fail("duplicate distribution identity")
    seen_distributions.add(distribution_key)
    rows = []
    for package_path in package_paths:
        text_path = str(package_path).replace("\\", "/")
        pure_path = pathlib.PurePosixPath(text_path)
        if pure_path.is_absolute() or "\x00" in text_path:
            fail("RECORD contains a non-relative or NUL path")
        candidate = pathlib.Path(distribution.locate_file(package_path))
        resolved = candidate.resolve(strict=True)
        allow_blank = resolved == record_path or resolved.suffix.lower() == ".pyc"
        rows.append(content_row(
            candidate,
            "distribution RECORD file",
            package_path.hash,
            package_path.size,
            allow_blank,
        ))
    rows.sort(key=lambda item: os.path.normcase(item["path"]))
    row_by_path = {os.path.normcase(item["path"]): item for item in rows}
    record_row = row_by_path.get(os.path.normcase(str(record_path)))
    if record_row is None:
        fail("distribution RECORD self-row is absent")
    installer_rows = [
        item for item in rows
        if pathlib.Path(item["path"]).name == "INSTALLER"
        and pathlib.Path(item["path"]).parent == record_path.parent
    ]
    if len(installer_rows) > 1:
        fail("distribution has multiple INSTALLER rows")
    distributions.append({
        "name": name,
        "version": version,
        "location": str(location),
        "record_path": str(record_path),
        "record_sha256": record_row["sha256"],
        "installer_sha256": installer_rows[0]["sha256"] if installer_rows else None,
        "files": rows,
    })
distributions.sort(key=lambda item: (item["name"], item["version"], os.path.normcase(item["location"]), os.path.normcase(item["record_path"])))
if not distributions:
    fail("no installed distributions were found")

runtime_candidates = {}
def add_runtime(candidate, kind):
    lexical = pathlib.Path(os.path.abspath(os.fspath(candidate)))
    if not lexical.is_file():
        return
    resolved = lexical.resolve(strict=True)
    key = os.path.normcase(str(resolved))
    prior = runtime_candidates.get(key)
    if prior is not None and prior[1] != kind:
        fail("runtime file has conflicting kinds")
    runtime_candidates[key] = (lexical, kind)

executable = pathlib.Path(sys.executable).resolve(strict=True)
add_runtime(executable, "executable")
add_runtime(executable.with_name("pythonw.exe"), "launcher")
for root in dict.fromkeys((prefix_lexical, base_prefix_lexical)):
    for candidate in root.glob("*.dll"):
        add_runtime(candidate, "runtime_dll")
    add_runtime(root / "pyvenv.cfg", "runtime_config")

stdlib_candidate = pathlib.Path(os.path.abspath(sysconfig.get_path("stdlib")))
stdlib_root = stdlib_candidate.resolve(strict=True)
stdlib_candidate = assert_regular_directory(
    stdlib_candidate, stdlib_root, "Python stdlib root"
)
walk_roots = [
    (stdlib_candidate, "stdlib"),
    (base_prefix_lexical / "DLLs", "native_library"),
]
for walk_root, kind in walk_roots:
    if not walk_root.is_dir():
        continue
    for directory, dirnames, filenames in os.walk(walk_root, topdown=True, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames
            if name.casefold() not in {"site-packages", "dist-packages", "__pycache__"}
        )
        for dirname in dirnames:
            info = (pathlib.Path(directory) / dirname).lstat()
            if getattr(info, "st_file_attributes", 0) & REPARSE:
                fail("runtime inventory crosses a reparse-point directory")
        for filename in sorted(filenames):
            add_runtime(pathlib.Path(directory) / filename, kind)

runtime_files = []
for key in sorted(runtime_candidates):
    candidate, kind = runtime_candidates[key]
    row = content_row(candidate, "Python runtime file")
    runtime_files.append({
        "kind": kind,
        "path": row["path"],
        "length": row["length"],
        "sha256": row["sha256"],
    })

pth_files = []
pth_root = prefix_lexical / "Lib" / "site-packages"
assert_regular_directory(pth_root, pth_root.resolve(strict=True), "Python .pth root")
for candidate in sorted(
    (item for item in pth_root.iterdir() if item.suffix.casefold() == ".pth"),
    key=lambda item: os.path.normcase(str(item)),
):
    resolved, length = assert_regular_file(candidate, "Python .pth bootstrap file")
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        while True:
            block = handle.read(1048576)
            if not block:
                break
            digest.update(block)
    pth_files.append({
        "path": str(resolved),
        "length": length,
        "sha256": digest.hexdigest(),
    })

secret_exact = {
    "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL",
    "GH_TOKEN", "GITHUB_TOKEN", "HF_TOKEN", "HTTP_PROXY", "HTTPS_PROXY",
    "ALL_PROXY", "NO_PROXY", "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "PIP_CERT", "PIP_PROXY",
    "PIP_TRUSTED_HOST", "GIT_SSL_NO_VERIFY",
    "GIT_SSL_CAINFO", "GIT_SSL_CAPATH", "GIT_ASKPASS", "SSH_ASKPASS",
    "SSH_AUTH_SOCK", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND",
}
secret_prefix = re.compile(r"^(?:POLYMARKET_|POLYMM_|OPENAI_|ANTHROPIC_|CLOUDFLARE_|AWS_|AZURE_|GOOGLE_|GCM_|GIT_SSL_|GIT_SSH)", re.I)
secret_generic = re.compile(r"(?:^|_)(?:TOKEN|PASSWORD|PASSWD|SECRET|PRIVATE_KEY|API_KEY|ACCESS_KEY|CLIENT_SECRET|CREDENTIALS?|CONNECTION_STRING|URL|URI|DSN|AUTH|COOKIE|KEY|CERT)(?:$|_)", re.I)
remaining_secret_names = [
    name for name in os.environ
    if name != "WEATHER_INTEGRATION_TEST_SECRET_POLICY"
    and (name.upper() in secret_exact or secret_prefix.search(name) or secret_generic.search(name))
]
git_topology_names = {
    "GIT_CONFIG_PARAMETERS", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_EXEC_PATH", "GIT_TEMPLATE_DIR",
}
remaining_git_topology_names = sorted(
    name for name in os.environ if name.upper() in git_topology_names
)

payload = {
    "schema_version": "python_environment_fingerprint_v2",
    "executable": str(executable),
    "executable_sha256": next(item["sha256"] for item in runtime_files if item["kind"] == "executable" and os.path.normcase(item["path"]) == os.path.normcase(str(executable))),
    "python_version": sys.version,
    "implementation": sys.implementation.name,
    "cache_tag": sys.implementation.cache_tag or "",
    "platform": platform.platform(),
    "prefix": str(prefix),
    "base_prefix": str(base_prefix),
    "sys_path": [str(pathlib.Path(value or pathlib.Path.cwd()).resolve()) for value in sys.path],
    "controls": {
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "pythonutf8": os.environ.get("PYTHONUTF8"),
        "pythonioencoding": os.environ.get("PYTHONIOENCODING"),
        "git_allow_protocol": os.environ.get("GIT_ALLOW_PROTOCOL"),
        "git_terminal_prompt": os.environ.get("GIT_TERMINAL_PROMPT"),
        "git_config_nosystem": os.environ.get("GIT_CONFIG_NOSYSTEM"),
        "git_config_system": os.environ.get("GIT_CONFIG_SYSTEM"),
        "git_config_global": os.environ.get("GIT_CONFIG_GLOBAL"),
        "git_config_count": os.environ.get("GIT_CONFIG_COUNT"),
        "git_attr_nosystem": os.environ.get("GIT_ATTR_NOSYSTEM"),
        "git_protocol_from_user": os.environ.get("GIT_PROTOCOL_FROM_USER"),
        "git_optional_locks": os.environ.get("GIT_OPTIONAL_LOCKS"),
        "git_topology_environment_clear": not remaining_git_topology_names,
        "git_topology_environment_count": len(remaining_git_topology_names),
        "offline": os.environ.get("WEATHER_INTEGRATION_TEST_OFFLINE"),
        "production_root": str(pathlib.Path(os.environ["WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"]).resolve()),
        "evidence_root": str(pathlib.Path(os.environ["WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT"]).resolve()),
        "allowed_write_root": os.environ.get("WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT") or "",
        "candidate_root": str(pathlib.Path(os.environ["WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT"]).resolve()),
        "secret_policy": os.environ.get("WEATHER_INTEGRATION_TEST_SECRET_POLICY"),
        "secret_environment_clear": not remaining_secret_names,
        "secret_environment_count": len(remaining_secret_names),
        "temp_policy": os.environ.get("WEATHER_INTEGRATION_TEST_TEMP_POLICY"),
        "temp": str(pathlib.Path(os.environ["TEMP"]).resolve(strict=True)),
        "tmp": str(pathlib.Path(os.environ["TMP"]).resolve(strict=True)),
        "tmpdir": str(pathlib.Path(os.environ["TMPDIR"]).resolve(strict=True)),
        "python_executable": str(pathlib.Path(os.environ["WEATHER_INTEGRATION_TEST_PYTHON_EXECUTABLE"]).resolve(strict=True)),
        "git_executable": str(pathlib.Path(os.environ["WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE"]).resolve(strict=True)),
        "powershell_executable": str(pathlib.Path(os.environ["WEATHER_INTEGRATION_TEST_POWERSHELL_EXECUTABLE"]).resolve(strict=True)),
        "setuptools_use_distutils": os.environ.get("SETUPTOOLS_USE_DISTUTILS"),
        "read_only_production_probe": os.environ.get("WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE") == "1",
    },
    "file_count": totals["files"],
    "total_bytes": totals["bytes"],
    "runtime_files": runtime_files,
    "pth_files": pth_files,
    "distributions": distributions,
}
sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
'@
    $result = Invoke-SuitePythonChild `
        -Tokens @("-c", $fingerprintCode) `
        -WorkingDirectory $WorktreeRoot `
        -Phase "Python environment fingerprint $Phase" `
        -MaxOutputBytes 16777216
    if ([int]$result.ExitCode -ne 0) {
        throw "Python environment fingerprint $Phase failed with exit $($result.ExitCode)"
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$result.Stderr)) {
        throw "Python environment fingerprint $Phase emitted unexpected stderr"
    }
    try { $payload = [string]$result.Stdout | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "Python environment fingerprint $Phase returned unreadable JSON" }
    $requiredProperties = @(
        "schema_version", "executable", "executable_sha256", "python_version",
        "implementation", "cache_tag", "platform", "prefix", "base_prefix",
        "sys_path", "controls", "file_count", "total_bytes", "runtime_files",
        "pth_files",
        "distributions"
    )
    $actualProperties = @($payload.PSObject.Properties.Name | Sort-Object)
    if ($null -eq $payload -or $payload -is [System.Array] -or
        ($actualProperties -join "`n") -cne
            (@($requiredProperties | Sort-Object) -join "`n") -or
        [string]$payload.schema_version -cne "python_environment_fingerprint_v2") {
        throw "Python environment fingerprint $Phase has the wrong top-level schema"
    }
    try {
        $fingerprintExecutable = [IO.Path]::GetFullPath([string]$payload.executable)
        $fingerprintPrefix = [IO.Path]::GetFullPath([string]$payload.prefix)
        $fingerprintBasePrefix = [IO.Path]::GetFullPath([string]$payload.base_prefix)
    }
    catch { throw "Python environment fingerprint $Phase contains an invalid path" }
    if (-not $fingerprintExecutable.Equals(
        $python,
        [StringComparison]::OrdinalIgnoreCase
    ) -or [string]$payload.executable_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        [string]$payload.executable_sha256 -cne $pythonExecutableSha256 -or
        [string]::IsNullOrWhiteSpace([string]$payload.python_version) -or
        [string]::IsNullOrWhiteSpace([string]$payload.implementation) -or
        [string]::IsNullOrWhiteSpace([string]$payload.platform) -or
        [string]::IsNullOrWhiteSpace($fingerprintPrefix) -or
        [string]::IsNullOrWhiteSpace($fingerprintBasePrefix)) {
        throw "Python environment fingerprint $Phase has invalid runtime identity"
    }
    $sysPathRows = @($payload.sys_path)
    if ($sysPathRows.Count -eq 0 -or @($sysPathRows | Where-Object {
        [string]::IsNullOrWhiteSpace([string]$_) -or
        -not [IO.Path]::IsPathRooted([string]$_)
    }).Count -ne 0) {
        throw "Python environment fingerprint $Phase has invalid sys.path evidence"
    }
    $controlProperties = @($payload.controls.PSObject.Properties.Name | Sort-Object)
    $expectedControlProperties = @(
        "allowed_write_root", "candidate_root", "git_allow_protocol",
        "git_terminal_prompt", "git_config_nosystem", "git_config_system",
        "git_config_global", "git_config_count", "git_attr_nosystem",
        "git_protocol_from_user", "git_optional_locks", "git_topology_environment_clear",
        "git_topology_environment_count", "offline", "production_root", "evidence_root", "pythonhashseed",
        "pythonioencoding", "pythonutf8", "secret_environment_clear",
        "secret_environment_count", "secret_policy", "temp_policy",
        "python_executable", "git_executable", "powershell_executable",
        "setuptools_use_distutils", "read_only_production_probe"
    ) | Sort-Object
    if (($controlProperties -join "`n") -cne
            ($expectedControlProperties -join "`n") -or
        [string]$payload.controls.pythonhashseed -cne "0" -or
        [string]$payload.controls.pythonutf8 -cne "1" -or
        [string]$payload.controls.pythonioencoding -cne "utf-8" -or
        [string]$payload.controls.git_allow_protocol -cne "file" -or
        [string]$payload.controls.git_terminal_prompt -cne "0" -or
        [string]$payload.controls.git_config_nosystem -cne "1" -or
        [string]$payload.controls.git_config_system -cne "NUL" -or
        [string]$payload.controls.git_config_global -cne "NUL" -or
        [string]$payload.controls.git_config_count -cne "0" -or
        [string]$payload.controls.git_attr_nosystem -cne "1" -or
        [string]$payload.controls.git_protocol_from_user -cne "0" -or
        [string]$payload.controls.git_optional_locks -cne "0" -or
        $payload.controls.git_topology_environment_clear -ne $true -or
        [int]$payload.controls.git_topology_environment_count -ne 0 -or
        [string]$payload.controls.offline -cne "1" -or
        -not [string]::IsNullOrEmpty([string]$payload.controls.allowed_write_root) -or
        -not ([IO.Path]::GetFullPath([string]$payload.controls.candidate_root)).Equals(
            $WorktreeRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [string]$payload.controls.secret_policy -cne "conservative_v1" -or
        $payload.controls.secret_environment_clear -ne $true -or
        [int]$payload.controls.secret_environment_count -ne 0 -or
        [string]$payload.controls.temp_policy -cne "system_temp_unique_v1" -or
        [string]$payload.controls.setuptools_use_distutils -cne "stdlib" -or
        $payload.controls.read_only_production_probe -isnot [bool] -or
        [bool]$payload.controls.read_only_production_probe -or
        -not ([IO.Path]::GetFullPath(
            [string]$payload.controls.python_executable
        )).Equals($python, [StringComparison]::OrdinalIgnoreCase) -or
        -not ([IO.Path]::GetFullPath(
            [string]$payload.controls.git_executable
        )).Equals($suiteBoundGitPath, [StringComparison]::OrdinalIgnoreCase) -or
        -not ([IO.Path]::GetFullPath(
            [string]$payload.controls.powershell_executable
        )).Equals(
            $suiteBoundPowerShellPath,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not ([IO.Path]::GetFullPath([string]$payload.controls.production_root)).Equals(
            $RepoRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not ([IO.Path]::GetFullPath([string]$payload.controls.evidence_root)).Equals(
            $evidenceRoot,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "Python environment fingerprint $Phase has invalid deterministic controls"
    }
    $pthRows = @($payload.pth_files)
    $expectedPthRows = @($suitePthBootstrap.Rows)
    if ($pthRows.Count -ne $expectedPthRows.Count -or $pthRows.Count -ne 2) {
        throw "Python environment fingerprint $Phase has the wrong .pth bootstrap inventory"
    }
    for ($pthIndex = 0; $pthIndex -lt $pthRows.Count; $pthIndex++) {
        $pthRow = $pthRows[$pthIndex]
        $expectedPth = $expectedPthRows[$pthIndex]
        $pthProperties = @($pthRow.PSObject.Properties.Name | Sort-Object)
        if (($pthProperties -join "`n") -cne
                ((@("length", "path", "sha256") | Sort-Object) -join "`n") -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$pthRow.path) -Right ([string]$expectedPth.path)) -or
            [int]$pthRow.length -ne [int]$expectedPth.length -or
            [string]$pthRow.sha256 -cne [string]$expectedPth.sha256) {
            throw "Python environment fingerprint $Phase .pth bytes differ from the retained bootstrap"
        }
    }
    $distributionRows = @($payload.distributions)
    if ($distributionRows.Count -eq 0) {
        throw "Python environment fingerprint $Phase found no installed distributions"
    }
    $seenContentPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    [int]$observedFileCount = 0
    [int64]$observedTotalBytes = 0
    foreach ($distribution in $distributionRows) {
        $distributionProperties = @($distribution.PSObject.Properties.Name | Sort-Object)
        $expectedDistributionProperties = @(
            "files", "installer_sha256", "location", "name", "record_path",
            "record_sha256", "version"
                ) | Sort-Object
        if (($distributionProperties -join "`n") -cne
                ($expectedDistributionProperties -join "`n") -or
            [string]$distribution.name -cnotmatch '^[a-z0-9]+(?:-[a-z0-9]+)*$' -or
            [string]::IsNullOrWhiteSpace([string]$distribution.version) -or
            -not [IO.Path]::IsPathRooted([string]$distribution.location) -or
            -not [IO.Path]::IsPathRooted([string]$distribution.record_path) -or
            [string]$distribution.record_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            ($null -ne $distribution.installer_sha256 -and
                [string]$distribution.installer_sha256 -cnotmatch '^[0-9a-f]{64}$')) {
            throw "Python environment fingerprint $Phase has invalid distribution evidence"
        }
        $distributionFiles = @($distribution.files)
        if ($distributionFiles.Count -eq 0) {
            throw "Python environment fingerprint $Phase has an empty distribution file set"
        }
        $recordRowSha256 = $null
        $installerRowSha256 = $null
        foreach ($fileRow in $distributionFiles) {
            $fileProperties = @($fileRow.PSObject.Properties.Name | Sort-Object)
            $expectedFileProperties = @(
                "length", "path", "record_algorithm", "record_digest",
                "record_size", "sha256"
            ) | Sort-Object
            if (($fileProperties -join "`n") -cne ($expectedFileProperties -join "`n") -or
                -not [IO.Path]::IsPathRooted([string]$fileRow.path) -or
                -not $seenContentPaths.Add([IO.Path]::GetFullPath([string]$fileRow.path)) -or
                [int64]$fileRow.length -lt 0 -or
                [int64]$fileRow.length -gt 2147483648 -or
                [string]$fileRow.sha256 -cnotmatch '^[0-9a-f]{64}$') {
                throw "Python environment fingerprint $Phase has an invalid distribution file row"
            }
            $recordBlankAllowed = (
                [IO.Path]::GetFullPath([string]$fileRow.path).Equals(
                    [IO.Path]::GetFullPath([string]$distribution.record_path),
                    [StringComparison]::OrdinalIgnoreCase
                ) -or
                [IO.Path]::GetExtension([string]$fileRow.path) -ieq ".pyc"
            )
            $hasRecordEvidence = $null -ne $fileRow.record_algorithm
            if ($hasRecordEvidence) {
                if ([string]$fileRow.record_algorithm -cne "sha256" -or
                    [string]$fileRow.record_digest -cnotmatch '^[0-9a-f]{64}$' -or
                    [int64]$fileRow.record_size -ne [int64]$fileRow.length -or
                    [string]$fileRow.record_digest -cne [string]$fileRow.sha256) {
                    throw "Python environment fingerprint $Phase has unverifiable RECORD evidence"
                }
            }
            elseif (-not $recordBlankAllowed -or
                $null -ne $fileRow.record_digest -or $null -ne $fileRow.record_size) {
                throw "Python environment fingerprint $Phase has forbidden blank RECORD evidence"
            }
            if ([IO.Path]::GetFullPath([string]$fileRow.path).Equals(
                    [IO.Path]::GetFullPath([string]$distribution.record_path),
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                $recordRowSha256 = [string]$fileRow.sha256
            }
            if ([IO.Path]::GetFileName([string]$fileRow.path) -ceq "INSTALLER" -and
                [IO.Path]::GetDirectoryName([string]$fileRow.path).Equals(
                    [IO.Path]::GetDirectoryName([string]$distribution.record_path),
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                if ($null -ne $installerRowSha256) {
                    throw "Python environment fingerprint $Phase has duplicate INSTALLER rows"
                }
                $installerRowSha256 = [string]$fileRow.sha256
            }
            $observedFileCount++
            $observedTotalBytes += [int64]$fileRow.length
        }
        if ([string]$recordRowSha256 -cne [string]$distribution.record_sha256 -or
            (($null -eq $installerRowSha256) -ne
                ($null -eq $distribution.installer_sha256)) -or
            ($null -ne $installerRowSha256 -and
                [string]$installerRowSha256 -cne
                    [string]$distribution.installer_sha256)) {
            throw "Python environment fingerprint $Phase distribution metadata hashes disagree"
        }
    }
    $runtimeRows = @($payload.runtime_files)
    if ($runtimeRows.Count -eq 0) {
        throw "Python environment fingerprint $Phase has no runtime file evidence"
    }
    $sawExecutableRuntime = $false
    $sawLauncherRuntime = $false
    foreach ($runtimeRow in $runtimeRows) {
        $runtimeProperties = @($runtimeRow.PSObject.Properties.Name | Sort-Object)
        $expectedRuntimeProperties = @("kind", "length", "path", "sha256") | Sort-Object
        if (($runtimeProperties -join "`n") -cne ($expectedRuntimeProperties -join "`n") -or
            [string]$runtimeRow.kind -notin @(
                "executable", "launcher", "native_library", "runtime_config",
                "runtime_dll", "stdlib"
            ) -or
            -not [IO.Path]::IsPathRooted([string]$runtimeRow.path) -or
            -not $seenContentPaths.Add([IO.Path]::GetFullPath([string]$runtimeRow.path)) -or
            [int64]$runtimeRow.length -lt 0 -or
            [int64]$runtimeRow.length -gt 2147483648 -or
            [string]$runtimeRow.sha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "Python environment fingerprint $Phase has invalid runtime file evidence"
        }
        if ([string]$runtimeRow.kind -ceq "executable" -and
            ([IO.Path]::GetFullPath([string]$runtimeRow.path)).Equals(
                $python,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            [string]$runtimeRow.sha256 -ceq $pythonExecutableSha256) {
            $sawExecutableRuntime = $true
        }
        if ([string]$runtimeRow.kind -ceq "launcher" -and
            ([IO.Path]::GetFullPath([string]$runtimeRow.path)).Equals(
                $pythonw,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            [string]$runtimeRow.sha256 -ceq $pythonwExecutableSha256) {
            $sawLauncherRuntime = $true
        }
        $observedFileCount++
        $observedTotalBytes += [int64]$runtimeRow.length
    }
    if (-not $sawExecutableRuntime -or -not $sawLauncherRuntime -or
        $observedFileCount -ne [int]$payload.file_count -or
        $observedTotalBytes -ne [int64]$payload.total_bytes -or
        $observedFileCount -lt 1 -or $observedFileCount -gt 120000 -or
        $observedTotalBytes -lt 1 -or $observedTotalBytes -gt 8589934592) {
        throw "Python environment fingerprint $Phase aggregate content evidence disagrees"
    }
    return [pscustomobject]@{
        Sha256 = [string]$result.StdoutSha256
        DistributionCount = [int]$distributionRows.Count
        FileCount = [int]$observedFileCount
        TotalBytes = [int64]$observedTotalBytes
        Json = [string]$result.Stdout
        Payload = $payload
    }
}

function Get-SuiteIntegrationToolchainFingerprint {
    param([Parameter(Mandatory = $true)][string]$Phase)

    Assert-WeatherIntegrationSafeGitEnvironment `
        -Phase "integration toolchain fingerprint $Phase"
    $gitPath = Get-WeatherIntegrationGitExecutablePath `
        -Phase "integration toolchain fingerprint $Phase" `
        -ExpectedPath $suiteBoundGitPath
    $gitItem = Get-Item -LiteralPath $gitPath -Force -ErrorAction Stop
    if (-not $gitItem.PSIsContainer -and
        ($gitItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $gitPath -Phase "integration toolchain Git executable"
        $gitSnapshot = Open-SuiteBoundedFileSnapshot `
            -Path $gitPath -MaxBytes 67108864 -Label "Git executable"
    }
    else { throw "integration toolchain Git executable is not a regular file" }
    $gitSnapshotRetained = $false
    try {
        $gitSha256 = [string]$gitSnapshot.Sha256
        $suiteEvidenceReadStreams.Add($gitSnapshot.Stream)
        $gitSnapshotRetained = $true
    }
    finally {
        if (-not $gitSnapshotRetained) { $gitSnapshot.Stream.Dispose() }
    }
    $gitVersionResult = Invoke-WeatherIntegrationBoundedProcess `
        -Executable $gitPath `
        -Arguments @("-c", "core.fsmonitor=false", "--version") `
        -WorkingDirectory $WorktreeRoot `
        -TimeoutSeconds 30 `
        -Label "Git toolchain version $Phase" `
        -ExpectedExecutableSha256 $gitSha256 `
        -RemoveEnvironmentVariables @(Get-WeatherIntegrationBlockedGitEnvironmentNames) `
        -Environment @{
            GIT_CONFIG_NOSYSTEM = "1"
            GIT_CONFIG_SYSTEM = "NUL"
            GIT_CONFIG_GLOBAL = "NUL"
            GIT_CONFIG_COUNT = "0"
            GIT_NO_REPLACE_OBJECTS = "1"
            GIT_OPTIONAL_LOCKS = "0"
            LC_ALL = "C"
            LANG = "C"
        }
    $gitVersion = ([string]$gitVersionResult.Stdout).Trim()
    if ($gitVersion -cnotmatch '^git version [0-9][0-9A-Za-z.+-]*$' -or
        -not [string]::IsNullOrWhiteSpace([string]$gitVersionResult.Stderr)) {
        throw "integration toolchain Git version output is not canonical"
    }

    $repositoryGitSafety = Assert-WeatherIntegrationSafeRepositoryGitConfiguration `
        -Root $WorktreeRoot `
        -Label "integration toolchain fingerprint $Phase" `
        -ExpectedGitExecutable $gitPath
    $gitLfsPath = [string]$repositoryGitSafety.GitLfsExecutable
    if ([string]::IsNullOrWhiteSpace($gitLfsPath)) {
        throw "integration toolchain requires the approved Git LFS executable"
    }
    $gitLfsSnapshot = Open-SuiteBoundedFileSnapshot `
        -Path $gitLfsPath -MaxBytes 67108864 -Label "Git LFS executable"
    $gitLfsSnapshotRetained = $false
    try {
        $gitLfsSha256 = [string]$gitLfsSnapshot.Sha256
        $suiteEvidenceReadStreams.Add($gitLfsSnapshot.Stream)
        $gitLfsSnapshotRetained = $true
    }
    finally {
        if (-not $gitLfsSnapshotRetained) { $gitLfsSnapshot.Stream.Dispose() }
    }
    $gitLfsVersionResult = Invoke-WeatherIntegrationBoundedProcess `
        -Executable $gitLfsPath `
        -ExpectedExecutableSha256 $gitLfsSha256 `
        -Arguments @("version") `
        -WorkingDirectory $WorktreeRoot `
        -TimeoutSeconds 30 `
        -Label "Git LFS toolchain version $Phase" `
        -RemoveEnvironmentVariables @(Get-WeatherIntegrationBlockedGitEnvironmentNames) `
        -Environment @{
            GIT_NO_REPLACE_OBJECTS = "1"
            LC_ALL = "C"
            LANG = "C"
        }
    $gitLfsVersion = ([string]$gitLfsVersionResult.Stdout).Trim()
    if ($gitLfsVersion -cnotmatch '^git-lfs/[0-9][^\r\n]*$' -or
        -not [string]::IsNullOrWhiteSpace([string]$gitLfsVersionResult.Stderr)) {
        throw "integration toolchain Git LFS version output is not canonical"
    }

    $currentProcess = [Diagnostics.Process]::GetCurrentProcess()
    try { $powerShellPath = [IO.Path]::GetFullPath($currentProcess.MainModule.FileName) }
    finally { $currentProcess.Dispose() }
    if (-not $powerShellPath.Equals(
            $suiteBoundPowerShellPath,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "integration toolchain PowerShell path changed after entry binding"
    }
    $powerShellItem = Get-Item -LiteralPath $powerShellPath -Force -ErrorAction Stop
    if ($powerShellItem.PSIsContainer -or
        ($powerShellItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "integration toolchain PowerShell executable is not a regular file"
    }
    Assert-WeatherIntegrationRegularPathAncestry `
        -Path $powerShellPath -Phase "integration toolchain PowerShell executable"
    $powerShellSnapshot = Open-SuiteBoundedFileSnapshot `
        -Path $powerShellPath -MaxBytes 67108864 -Label "PowerShell executable"
    $powerShellSnapshotRetained = $false
    try {
        $powerShellSha256 = [string]$powerShellSnapshot.Sha256
        $suiteEvidenceReadStreams.Add($powerShellSnapshot.Stream)
        $powerShellSnapshotRetained = $true
    }
    finally {
        if (-not $powerShellSnapshotRetained) {
            $powerShellSnapshot.Stream.Dispose()
        }
    }
    $powerShellVersion = [string]$PSVersionTable.PSVersion
    $clrVersion = [string]$PSVersionTable.CLRVersion
    $powerShellEdition = [string]$PSVersionTable.PSEdition
    $processArchitecture = if ([IntPtr]::Size -eq 8) { "x64" } else { "x86" }
    if ([string]::IsNullOrWhiteSpace($powerShellVersion) -or
        [string]::IsNullOrWhiteSpace($clrVersion) -or
        [string]::IsNullOrWhiteSpace($powerShellEdition)) {
        throw "integration toolchain PowerShell runtime identity is incomplete"
    }
    $payload = [ordered]@{
        schema_version = "integration_toolchain_fingerprint_v1"
        git = [ordered]@{
            executable = $gitPath
            executable_sha256 = $gitSha256
            version = $gitVersion
        }
        git_lfs = [ordered]@{
            executable = $gitLfsPath
            executable_sha256 = $gitLfsSha256
            version = $gitLfsVersion
        }
        powershell = [ordered]@{
            executable = $powerShellPath
            executable_sha256 = $powerShellSha256
            version = $powerShellVersion
            edition = $powerShellEdition
            clr_version = $clrVersion
            architecture = $processArchitecture
        }
        controls = [ordered]@{
            pythonhashseed = [string]$env:PYTHONHASHSEED
            pythonutf8 = [string]$env:PYTHONUTF8
            pythonioencoding = [string]$env:PYTHONIOENCODING
            git_allow_protocol = "file"
            git_terminal_prompt = "0"
            git_config_nosystem = [string]$suiteFrozenPythonGitControls[
                "GIT_CONFIG_NOSYSTEM"
            ]
            git_config_system = [string]$suiteFrozenPythonGitControls[
                "GIT_CONFIG_SYSTEM"
            ]
            git_config_global = [string]$suiteFrozenPythonGitControls[
                "GIT_CONFIG_GLOBAL"
            ]
            git_config_count = [string]$suiteFrozenPythonGitControls[
                "GIT_CONFIG_COUNT"
            ]
            git_attr_nosystem = [string]$suiteFrozenPythonGitControls[
                "GIT_ATTR_NOSYSTEM"
            ]
            git_protocol_from_user = [string]$suiteFrozenPythonGitControls[
                "GIT_PROTOCOL_FROM_USER"
            ]
            git_optional_locks = [string]$suiteFrozenPythonGitControls[
                "GIT_OPTIONAL_LOCKS"
            ]
            git_topology_environment_clear = (@(
                $suiteRejectedPythonGitControls | Where-Object {
                    $null -ne [Environment]::GetEnvironmentVariable(
                        [string]$_,
                        [EnvironmentVariableTarget]::Process
                    )
                }
            ).Count -eq 0)
            git_topology_environment_count = @(
                $suiteRejectedPythonGitControls | Where-Object {
                    $null -ne [Environment]::GetEnvironmentVariable(
                        [string]$_,
                        [EnvironmentVariableTarget]::Process
                    )
                }
            ).Count
            offline = [string]$env:WEATHER_INTEGRATION_TEST_OFFLINE
            production_root = [IO.Path]::GetFullPath(
                [string]$env:WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT
            )
            evidence_root = [IO.Path]::GetFullPath(
                [string]$env:WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT
            )
            allowed_write_root = [string]$env:WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT
            candidate_root = [IO.Path]::GetFullPath(
                [string]$env:WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT
            )
            secret_policy = [string]$env:WEATHER_INTEGRATION_TEST_SECRET_POLICY
            secret_environment_clear = (
                @(Get-SuiteSecretBearingEnvironmentNames).Count -eq 0
            )
            secret_environment_count = @(
                Get-SuiteSecretBearingEnvironmentNames
            ).Count
            temp_policy = [string]$env:WEATHER_INTEGRATION_TEST_TEMP_POLICY
            temp = $suiteSystemTempRoot
            tmp = $suiteSystemTempRoot
            tmpdir = $suiteSystemTempRoot
            python_executable = [IO.Path]::GetFullPath(
                [string]$env:WEATHER_INTEGRATION_TEST_PYTHON_EXECUTABLE
            )
            git_executable = [IO.Path]::GetFullPath(
                [string]$env:WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE
            )
            powershell_executable = [IO.Path]::GetFullPath(
                [string]$env:WEATHER_INTEGRATION_TEST_POWERSHELL_EXECUTABLE
            )
            setuptools_use_distutils = [string]$env:SETUPTOOLS_USE_DISTUTILS
            read_only_production_probe = (
                [string]$env:WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE -ceq "1"
            )
        }
    }
    if ($payload.controls.pythonhashseed -cne "0" -or
        $payload.controls.pythonutf8 -cne "1" -or
        $payload.controls.pythonioencoding -cne "utf-8" -or
        $payload.controls.git_allow_protocol -cne "file" -or
        $payload.controls.git_terminal_prompt -cne "0" -or
        $payload.controls.git_config_nosystem -cne "1" -or
        $payload.controls.git_config_system -cne "NUL" -or
        $payload.controls.git_config_global -cne "NUL" -or
        $payload.controls.git_config_count -cne "0" -or
        $payload.controls.git_attr_nosystem -cne "1" -or
        $payload.controls.git_protocol_from_user -cne "0" -or
        $payload.controls.git_optional_locks -cne "0" -or
        $payload.controls.git_topology_environment_clear -ne $true -or
        [int]$payload.controls.git_topology_environment_count -ne 0 -or
        $payload.controls.offline -cne "1" -or
        -not [string]::IsNullOrEmpty($payload.controls.allowed_write_root) -or
        -not $payload.controls.candidate_root.Equals(
            $WorktreeRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not $payload.controls.evidence_root.Equals(
            $evidenceRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        $payload.controls.secret_policy -cne "conservative_v1" -or
        $payload.controls.secret_environment_clear -ne $true -or
        [int]$payload.controls.secret_environment_count -ne 0 -or
        $payload.controls.temp_policy -cne "system_temp_unique_v1" -or
        $payload.controls.setuptools_use_distutils -cne "stdlib" -or
        $payload.controls.read_only_production_probe -isnot [bool] -or
        [bool]$payload.controls.read_only_production_probe -or
        -not $payload.controls.python_executable.Equals(
            $python, [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not $payload.controls.git_executable.Equals(
            $gitPath, [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not $payload.controls.powershell_executable.Equals(
            $powerShellPath, [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not $payload.controls.production_root.Equals(
            $RepoRoot,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "integration toolchain deterministic controls are not frozen"
    }
    $json = $payload | ConvertTo-Json -Compress -Depth 6
    $fingerprint = New-SuiteUtf8Snapshot `
        -Bytes ((New-Object Text.UTF8Encoding($false, $true)).GetBytes($json)) `
        -Label "integration toolchain fingerprint $Phase"
    return [pscustomobject]@{
        Sha256 = $fingerprint.Sha256
        GitSha256 = $gitSha256
        GitLfsSha256 = $gitLfsSha256
        PowerShellSha256 = $powerShellSha256
        GitPath = $gitPath
        PowerShellPath = $powerShellPath
        Json = $json
        Payload = $payload
    }
}

function Get-SuiteJUnitSummary {
    param(
        [Parameter(Mandatory = $true)][object]$Snapshot,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$EvidencePath
    )

    $snapshot = $Snapshot
    $settings = New-Object System.Xml.XmlReaderSettings
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $memory = New-Object IO.MemoryStream
    $memory.Write($snapshot.Bytes, 0, $snapshot.Bytes.Length)
    $memory.Position = 0
    $reader = [System.Xml.XmlReader]::Create($memory, $settings)
    try {
        $document = New-Object System.Xml.XmlDocument
        $document.XmlResolver = $null
        $document.Load($reader)
    }
    finally {
        $reader.Dispose()
        $memory.Dispose()
    }
    $suiteNodes = if ($document.DocumentElement.Name -ceq "testsuite") {
        @($document.DocumentElement)
    }
    elseif ($document.DocumentElement.Name -ceq "testsuites") {
        @($document.DocumentElement.SelectNodes("./testsuite"))
    }
    else { @() }
    if ($suiteNodes.Count -eq 0) {
        throw "JUnit file has no top-level suite: $Path"
    }
    $summary = [ordered]@{ tests = 0; failures = 0; errors = 0; skipped = 0; deselected = 0 }
    foreach ($suiteNode in $suiteNodes) {
        foreach ($name in $summary.Keys) {
            $attribute = $suiteNode.Attributes[$name]
            if ($null -eq $attribute) {
                if ($name -eq "tests") {
                    throw "JUnit testsuite is missing its tests count: $Path"
                }
                continue
            }
            if ([string]$attribute.Value -notmatch '^[0-9]+$') {
                throw "JUnit testsuite has an invalid $name count: $Path"
            }
            $summary[$name] += [int]$attribute.Value
        }
    }
    if ([int]$summary.tests -le 0 -or
        ([int]$summary.tests - [int]$summary.skipped) -le 0 -or
        [int]$summary.failures -ne 0 -or [int]$summary.errors -ne 0 -or
        [int]$summary.deselected -ne 0) {
        throw "JUnit does not prove a nonempty, executed, zero-failure chunk: $Path"
    }
    Write-SuiteRetainedByteSidecar `
        -Path $EvidencePath -Bytes $snapshot.Bytes | Out-Null
    $summary["sha256"] = $snapshot.Sha256
    $summary["length"] = $snapshot.Length
    $summary["path"] = [IO.Path]::GetFullPath($EvidencePath)
    return [pscustomobject]$summary
}

function Get-CommitPercent {
    $limit = (Get-Counter "\Memory\Commit Limit").CounterSamples[0].CookedValue
    $used = (Get-Counter "\Memory\Committed Bytes").CounterSamples[0].CookedValue
    if ($limit -le 0 -or $used -lt 0) { throw "invalid Windows commit counters" }
    return [math]::Round(100.0 * $used / $limit, 2)
}

function Get-CaptureRecoveryState {
    # Admission must trust the production recovery implementation, not a
    # candidate module from the worktree being qualified. The canonical check
    # proves status/lock PID, process creation token, exact command, heartbeat,
    # and loaded-source identity together, closing the PID-reuse hole in the
    # former duplicate counter.
    $capturePreviousPythonPath = $env:PYTHONPATH
    $capturePreviousCandidateRoot = $env:WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT
    $capturePreviousReadOnlyProductionProbe =
        $env:WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE
    $capturePreviousLocation = (Get-Location).Path
    $captureTipBeforeRows = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepoRoot `
        -Arguments @("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}") `
        -Label "canonical capture recovery pre-child production tip").StdoutLines)
    if ($captureTipBeforeRows.Count -ne 1 -or
        [string]$captureTipBeforeRows[0] -cnotmatch '^[0-9a-f]{40}$') {
        throw "canonical capture recovery could not bind its pre-child production tip"
    }
    $captureTipBefore = ([string]$captureTipBeforeRows[0]).Trim().ToLowerInvariant()
    $capturePrimaryFailure = $null
    try {
        $env:PYTHONPATH = Join-Path $RepoRoot "src"
        $env:WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT = $RepoRoot
        $env:WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE = "1"
        if (-not ([IO.Path]::GetFullPath(
                    [string]$env:WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT
                )).Equals($RepoRoot, [StringComparison]::OrdinalIgnoreCase) -or
            [string]$env:WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE -cne "1") {
            throw "canonical capture recovery read-only production probe was not armed"
        }
        Set-Location -LiteralPath $RepoRoot
        $captureProcess = Invoke-SuitePythonChild `
            -Tokens @(
                "-m", "weather.operations.capture_recovery_check",
                "--repo-root", $RepoRoot, "--json"
            ) `
            -WorkingDirectory $RepoRoot `
            -Phase "canonical capture recovery"
        $captureExitCode = [int]$captureProcess.ExitCode
    }
    catch {
        $capturePrimaryFailure = $_
        throw
    }
    finally {
        $captureCleanupFailures = [Collections.Generic.List[string]]::new()
        try { Set-Location -LiteralPath $capturePreviousLocation }
        catch { $captureCleanupFailures.Add("working directory") }
        foreach ($restoration in @(
            [pscustomobject]@{
                Name = "PYTHONPATH"
                Value = $capturePreviousPythonPath
            },
            [pscustomobject]@{
                Name = "WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT"
                Value = $capturePreviousCandidateRoot
            },
            [pscustomobject]@{
                Name = "WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE"
                Value = $capturePreviousReadOnlyProductionProbe
            }
        )) {
            try {
                [Environment]::SetEnvironmentVariable(
                    [string]$restoration.Name,
                    $restoration.Value,
                    [EnvironmentVariableTarget]::Process
                )
                if ([Environment]::GetEnvironmentVariable(
                        [string]$restoration.Name,
                        [EnvironmentVariableTarget]::Process
                    ) -cne $restoration.Value) {
                    throw "restored value was not observed"
                }
            }
            catch { $captureCleanupFailures.Add([string]$restoration.Name) }
        }
        if ($captureCleanupFailures.Count -gt 0) {
            $captureCleanupMessage =
                "canonical capture recovery environment restoration failed"
            if ($null -ne $capturePrimaryFailure) {
                $capturePrimaryFailure.Exception.Data[
                    "weather_capture_environment_cleanup_failure"
                ] = $captureCleanupMessage
                Write-Warning $captureCleanupMessage -WarningAction Continue
            }
            else { throw $captureCleanupMessage }
        }
    }
    $captureTipAfterRows = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepoRoot `
        -Arguments @("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}") `
        -Label "canonical capture recovery post-child production tip").StdoutLines)
    if ($captureTipAfterRows.Count -ne 1 -or
        ([string]$captureTipAfterRows[0]).Trim().ToLowerInvariant() -cne
            $captureTipBefore) {
        throw "canonical capture recovery production tip changed across its child"
    }
    $captureJson = [string]$captureProcess.Stdout
    $captureJsonSha256 = [string]$captureProcess.StdoutSha256
    if (-not [string]::IsNullOrWhiteSpace([string]$captureProcess.Stderr)) {
        throw "canonical capture recovery emitted unexpected stderr"
    }
    if ([string]::IsNullOrWhiteSpace($captureJson)) {
        throw "canonical capture recovery returned no JSON object"
    }
    try {
        $capturePayload = ($captureJson | ConvertFrom-Json -ErrorAction Stop)
    }
    catch {
        throw "canonical capture recovery returned unreadable JSON"
    }
    $requiredPayloadProperties = @(
        "schema_version", "checked_at", "execution_identity", "repo_root", "ok",
        "workers"
    )
    $actualPayloadProperties = @(
        $capturePayload.PSObject.Properties.Name | Sort-Object
    )
    if ($null -eq $capturePayload -or $capturePayload -is [System.Array] -or
        ($actualPayloadProperties -join "`n") -cne
            ((@($requiredPayloadProperties) | Sort-Object) -join "`n")) {
        throw "canonical capture recovery JSON has the wrong object shape"
    }
    if ([string]$capturePayload.schema_version -cne "capture_recovery_check_v1" -or
        $capturePayload.ok -isnot [bool]) {
        throw "canonical capture recovery JSON has the wrong schema"
    }
    try {
        if ([string]::IsNullOrWhiteSpace([string]$capturePayload.repo_root)) {
            throw "missing repo_root"
        }
        $captureRepoRoot = [IO.Path]::GetFullPath([string]$capturePayload.repo_root)
    }
    catch {
        throw "canonical capture recovery JSON has an invalid repo_root"
    }
    if (-not $captureRepoRoot.Equals(
        [IO.Path]::GetFullPath($RepoRoot),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "canonical capture recovery JSON is bound to a different repo_root"
    }
    $executionIdentity = $capturePayload.execution_identity
    $executionProperties = @(
        $executionIdentity.PSObject.Properties.Name | Sort-Object
    )
    if ($null -eq $executionIdentity -or $executionIdentity -is [System.Array] -or
        ($executionProperties -join "`n") -cne
            ((@("module_path", "runtime_identity") | Sort-Object) -join "`n")) {
        throw "canonical capture recovery JSON has invalid execution identity"
    }
    $expectedCaptureModule = [IO.Path]::GetFullPath(
        (Join-Path $RepoRoot "src\weather\operations\capture_recovery_check.py")
    )
    try {
        $captureModulePath = [IO.Path]::GetFullPath(
            [string]$executionIdentity.module_path
        )
        $captureRuntimeRoot = [IO.Path]::GetFullPath(
            [string]$executionIdentity.runtime_identity.repo_root
        )
    }
    catch { throw "canonical capture recovery execution identity has invalid paths" }
    $captureRuntimeIdentity = $executionIdentity.runtime_identity
    $captureScopeFiles = @($captureRuntimeIdentity.source_scope_files)
    if (-not $captureModulePath.Equals(
            $expectedCaptureModule,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not $captureRuntimeRoot.Equals(
            [IO.Path]::GetFullPath($RepoRoot),
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [string]$captureRuntimeIdentity.git_commit -cnotmatch '^[0-9a-f]{12}$' -or
        [string]$captureRuntimeIdentity.git_commit -cne
            $captureTipBefore.Substring(0, 12) -or
        [string]$captureRuntimeIdentity.source_fingerprint -cnotmatch
            '^[0-9a-f]{16}$' -or
        [string]$captureRuntimeIdentity.source_scope -cne "loaded_modules" -or
        [int]$captureRuntimeIdentity.source_file_count -ne $captureScopeFiles.Count -or
        $captureScopeFiles.Count -lt 1 -or
        $captureScopeFiles -notcontains
            "src/weather/operations/capture_recovery_check.py") {
        throw "canonical capture recovery execution identity is not production-bound"
    }
    $captureWorkers = @($capturePayload.workers)
    $expectedWorkerNames = @(
        "snapshot_tracker", "market_microstructure", "observation_trigger"
    )
    if ($captureWorkers.Count -ne 3 -or
        @($captureWorkers | Where-Object {
            $null -eq $_ -or
            $null -eq $_.PSObject.Properties["name"] -or
            $null -eq $_.PSObject.Properties["ok"] -or
            $null -eq $_.PSObject.Properties["reasons"] -or
            $null -eq $_.PSObject.Properties["recorded_source_fingerprint"] -or
            $null -eq $_.PSObject.Properties["current_source_fingerprint"] -or
            $null -eq $_.PSObject.Properties["runtime_identity_matches_current"] -or
            $_.ok -isnot [bool] -or
            $_.runtime_identity_matches_current -isnot [bool] -or
            ($_.ok -eq $true -and (
                $_.runtime_identity_matches_current -ne $true -or
                [string]$_.recorded_source_fingerprint -cnotmatch '^[0-9a-f]{16}$' -or
                [string]$_.current_source_fingerprint -cnotmatch '^[0-9a-f]{16}$' -or
                [string]$_.recorded_source_fingerprint -cne
                    [string]$_.current_source_fingerprint
            ))
        }).Count -ne 0 -or
        (@($captureWorkers | ForEach-Object { [string]$_.name } | Sort-Object) -join "`n") -cne
            (@($expectedWorkerNames | Sort-Object) -join "`n")) {
        throw "canonical capture recovery JSON has the wrong worker shape"
    }
    return [pscustomobject]@{
        ExitCode = [int]$captureExitCode
        Payload = $capturePayload
        JsonSha256 = $captureJsonSha256
    }
}

function Assert-HostAdmission {
    param(
        [Parameter(Mandatory = $true)][double]$CommitCeiling,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    # Manifest-bound callers hash this production helper before launch. Run it
    # before importing production Python so tracked code drift cannot weaken the
    # canonical capture checker, and re-run it for every chunk admission.
    $quietMergePreflight = Assert-WeatherIntegrationQuietMergePreconditions `
        -RepositoryRoot $RepoRoot
    $captureRecovery = Get-CaptureRecoveryState
    $captureRows = @($captureRecovery.Payload.workers)
    $workers = @($captureRows | Where-Object { $_.ok -eq $true }).Count
    $commit = Get-CommitPercent
    Write-SuiteLog (
        "$Phase admission: quiet_merge_preflight=PASS " +
        "tracked_drift=$(@($quietMergePreflight.tracked_drift).Count) " +
        "capture_recovery_ok=$($captureRecovery.Payload.ok) " +
        "capture_workers=$workers/$($captureRows.Count) commit=$commit% " +
        "ceiling=$CommitCeiling% capture_stdout_sha256=$($captureRecovery.JsonSha256)"
    )
    if ($captureRecovery.ExitCode -ne 0 -or
        $captureRecovery.Payload.ok -ne $true -or
        $captureRows.Count -ne 3 -or $workers -ne 3) {
        $captureReasons = @(
            $captureRows | Where-Object { $_.ok -ne $true } | ForEach-Object {
                "$($_.name)=$(@($_.reasons) -join ',')"
            }
        ) -join "; "
        if ([string]::IsNullOrWhiteSpace($captureReasons)) {
            $captureReasons = "exit=$($captureRecovery.ExitCode) workers=$workers/$($captureRows.Count)"
        }
        throw "$Phase refused: canonical three-worker capture recovery failed: $captureReasons"
    }
    if ($commit -gt $CommitCeiling) {
        throw "$Phase refused: commit $commit% exceeds $CommitCeiling%"
    }
}

$suiteLogHandle = Open-SuiteRetainedLog -Path $LogPath
$suiteLogWriter = $suiteLogHandle.Writer
$suiteSidecarStreams = [System.Collections.Generic.List[System.IO.FileStream]]::new()
$suiteEvidenceReadStreams = [System.Collections.Generic.List[System.IO.FileStream]]::new()
$suitePthBootstrap = $null
$suiteTrackedBaseline = [Collections.Generic.Dictionary[string, object]]::new(
    [StringComparer]::Ordinal
)
$trackedWorktreePre = $null
$secretEnvironmentRestorations = `
    [Collections.Generic.List[object]]::new()
$suiteOuterFailure = $null
try {
foreach ($secretName in @(Get-SuiteSecretBearingEnvironmentNames)) {
    $secretEnvironmentRestorations.Add([pscustomobject]@{
        Name = [string]$secretName
        Value = [Environment]::GetEnvironmentVariable(
            [string]$secretName,
            [EnvironmentVariableTarget]::Process
        )
    })
    [Environment]::SetEnvironmentVariable(
        [string]$secretName,
        $null,
        [EnvironmentVariableTarget]::Process
    )
}
if (@(Get-SuiteSecretBearingEnvironmentNames).Count -ne 0) {
    throw "secret-bearing environment removal was not proved before qualification"
}
Assert-WeatherIntegrationSafeGitEnvironment -Phase "bounded suite entry"
Write-SuiteLog "=== bounded worktree suite starting ==="
Write-SuiteLog "worktree=$WorktreeRoot branch=$BranchRef expected_tip=$ExpectedTip"
Write-SuiteLog "additional_python_roots=$($additionalPythonRoots.Count) require_live_sdk_contract=$($RequireLiveSdkContract.IsPresent) integration_preflight=$($IntegrationPreflight.IsPresent)"

$localNow = Get-Date
$localMinute = ($localNow.Hour * 60) + $localNow.Minute
if ($localMinute -ge (9 * 60) -or $localMinute -lt 30) {
    throw "bounded suite must start inside the 00:30-09:00 heavy-work window"
}
$hardStop = $localNow.Date.AddHours(9)
$runtimeStopwatch = [Diagnostics.Stopwatch]::StartNew()
$runtimeDeadline = $localNow.AddSeconds($MaxRuntimeSeconds)
if ($runtimeDeadline -gt $hardStop) { $runtimeDeadline = $hardStop }
Write-SuiteLog (
    "runtime_ceiling_seconds=$MaxRuntimeSeconds " +
    "runtime_clock=monotonic_stopwatch " +
    "runtime_deadline_local=$($runtimeDeadline.ToString('o')) " +
    "absolute_hard_stop_local=$($hardStop.ToString('o'))"
)
Assert-SuiteRelevantVolumeFreeSpace -Phase "entry"

$worktreeQuery = Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $RepoRoot -Arguments @("worktree", "list", "--porcelain") `
    -Label "registered worktree enumeration"
$registeredWorktrees = @(
    $worktreeQuery.StdoutLines |
        Where-Object { $_ -like "worktree *" } |
        ForEach-Object { [IO.Path]::GetFullPath($_.Substring(9)) }
)
if (-not ($registeredWorktrees | Where-Object {
    $_.Equals($WorktreeRoot, [StringComparison]::OrdinalIgnoreCase)
})) {
    throw "WorktreeRoot is not registered by the production repository"
}

$worktreeTipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $WorktreeRoot `
    -Arguments @("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}") `
    -Label "exact worktree tip query"
$branchTipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $RepoRoot `
    -Arguments @("rev-parse", "--verify", "--end-of-options", "${BranchRef}^{commit}") `
    -Label "exact branch tip query"
$worktreeTipRows = @($worktreeTipQuery.StdoutLines)
$branchTipRows = @($branchTipQuery.StdoutLines)
if ($worktreeTipRows.Count -ne 1 -or $branchTipRows.Count -ne 1) {
    throw "exact branch/worktree identity queries did not return one commit each"
}
$worktreeTip = ([string]$worktreeTipRows[0]).Trim().ToLowerInvariant()
$branchTip = ([string]$branchTipRows[0]).Trim().ToLowerInvariant()
if ($worktreeTip -ne $ExpectedTip -or $branchTip -ne $ExpectedTip) {
    throw "exact branch/worktree identity does not match ExpectedTip"
}
$dirtyQuery = Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $WorktreeRoot `
    -Arguments @("status", "--porcelain=v1", "--untracked-files=all") `
    -Label "initial clean-worktree query"
$dirty = @($dirtyQuery.StdoutLines)
if ($dirty.Count -ne 0) {
    throw "suite worktree is dirty; exact-tip evidence would be ambiguous"
}

$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$pythonw = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "production venv Python interpreter or Scheduler launcher is missing"
}
$python = (Resolve-Path -LiteralPath $python).Path
$pythonw = (Resolve-Path -LiteralPath $pythonw).Path
Assert-WeatherIntegrationRegularPathAncestry `
    -Path $python -Phase "bounded suite Python executable"
Assert-WeatherIntegrationRegularPathAncestry `
    -Path $pythonw -Phase "bounded suite Pythonw Scheduler executable"
$pythonExecutableSnapshot = Open-SuiteBoundedFileSnapshot `
    -Path $python -MaxBytes 67108864 -Label "Python executable"
$pythonwExecutableSnapshot = Open-SuiteBoundedFileSnapshot `
    -Path $pythonw -MaxBytes 67108864 -Label "Pythonw Scheduler executable"
$pythonExecutableSnapshotRetained = $false
$pythonwExecutableSnapshotRetained = $false
try {
    $pythonExecutableSha256 = [string]$pythonExecutableSnapshot.Sha256
    $pythonwExecutableSha256 = [string]$pythonwExecutableSnapshot.Sha256
    $suiteEvidenceReadStreams.Add($pythonExecutableSnapshot.Stream)
    $pythonExecutableSnapshotRetained = $true
    $suiteEvidenceReadStreams.Add($pythonwExecutableSnapshot.Stream)
    $pythonwExecutableSnapshotRetained = $true
}
finally {
    if (-not $pythonExecutableSnapshotRetained) {
        $pythonExecutableSnapshot.Stream.Dispose()
    }
    if (-not $pythonwExecutableSnapshotRetained) {
        $pythonwExecutableSnapshot.Stream.Dispose()
    }
}
$suiteBoundGitPath = Get-WeatherIntegrationGitExecutablePath `
    -Phase "bounded suite retained Git executable binding"
$suiteBoundGitSnapshot = Open-SuiteBoundedFileSnapshot `
    -Path $suiteBoundGitPath -MaxBytes 67108864 -Label "retained Git executable"
$suiteBoundPowerShellProcess = [Diagnostics.Process]::GetCurrentProcess()
try {
    $suiteBoundPowerShellPath = [IO.Path]::GetFullPath(
        $suiteBoundPowerShellProcess.MainModule.FileName
    )
}
finally { $suiteBoundPowerShellProcess.Dispose() }
Assert-WeatherIntegrationRegularPathAncestry `
    -Path $suiteBoundPowerShellPath `
    -Phase "bounded suite retained PowerShell executable binding"
$suiteBoundPowerShellSnapshot = Open-SuiteBoundedFileSnapshot `
    -Path $suiteBoundPowerShellPath -MaxBytes 67108864 `
    -Label "retained PowerShell executable"
$suiteBoundToolStreamsRetained = $false
try {
    $suiteBoundGitSha256 = [string]$suiteBoundGitSnapshot.Sha256
    $suiteBoundPowerShellSha256 = [string]$suiteBoundPowerShellSnapshot.Sha256
    $suiteEvidenceReadStreams.Add($suiteBoundGitSnapshot.Stream)
    $suiteEvidenceReadStreams.Add($suiteBoundPowerShellSnapshot.Stream)
    $suiteBoundToolStreamsRetained = $true
}
finally {
    if (-not $suiteBoundToolStreamsRetained) {
        $suiteBoundGitSnapshot.Stream.Dispose()
        $suiteBoundPowerShellSnapshot.Stream.Dispose()
    }
}
$previousPythonPath = $env:PYTHONPATH
$previousTmpDir = $env:TMPDIR
$previousLiveSdkRequirement = $env:WEATHER_REQUIRE_LIVE_SDK_CONTRACT
$previousNoUserSite = $env:PYTHONNOUSERSITE
$previousPluginAutoload = $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD
$previousPycachePrefix = $env:PYTHONPYCACHEPREFIX
$previousDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE
$previousPythonHashSeed = $env:PYTHONHASHSEED
$previousPythonUtf8 = $env:PYTHONUTF8
$previousPythonIoEncoding = $env:PYTHONIOENCODING
$previousGitAllowProtocol = $env:GIT_ALLOW_PROTOCOL
$previousGitTerminalPrompt = $env:GIT_TERMINAL_PROMPT
$previousGitConfigNoSystem = $env:GIT_CONFIG_NOSYSTEM
$previousGitConfigSystem = $env:GIT_CONFIG_SYSTEM
$previousGitConfigGlobal = $env:GIT_CONFIG_GLOBAL
$previousGitConfigCount = $env:GIT_CONFIG_COUNT
$previousGitAttrNoSystem = $env:GIT_ATTR_NOSYSTEM
$previousGitProtocolFromUser = $env:GIT_PROTOCOL_FROM_USER
$previousGitOptionalLocks = $env:GIT_OPTIONAL_LOCKS
$previousIntegrationTestOffline = $env:WEATHER_INTEGRATION_TEST_OFFLINE
$previousIntegrationTestProductionRoot = $env:WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT
$previousIntegrationTestEvidenceRoot = $env:WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT
$previousIntegrationTestAllowedWriteRoot = `
    $env:WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT
$previousIntegrationTestCandidateRoot = $env:WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT
$previousIntegrationTestSecretPolicy = $env:WEATHER_INTEGRATION_TEST_SECRET_POLICY
$previousIntegrationTestTempPolicy = $env:WEATHER_INTEGRATION_TEST_TEMP_POLICY
$previousIntegrationTestPythonExecutable =
    $env:WEATHER_INTEGRATION_TEST_PYTHON_EXECUTABLE
$previousIntegrationTestGitExecutable =
    $env:WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE
$previousIntegrationTestPowerShellExecutable =
    $env:WEATHER_INTEGRATION_TEST_POWERSHELL_EXECUTABLE
$previousIntegrationTestReadOnlyProductionProbe =
    $env:WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE
$previousSetuptoolsUseDistutils = $env:SETUPTOOLS_USE_DISTUTILS
$previousLocation = (Get-Location).Path
$workloadLease = $null
$pythonCacheRoot = $null
$suiteChildOutputRoot = $null
$suitePytestTempRoot = $null
$suiteExecutionFailure = $null
try {
    $workloadLease = Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $RepoRoot -Workload "bounded_worktree_test_suite"
    if ($null -eq $workloadLease) {
        throw "another heavyweight host workload owns data/logs/heavy_workload.lock"
    }
    $suitePthBootstrap = Open-SuiteQualifiedPthBootstrap
    $suiteChildOutputRoot = New-SuiteChildOutputRoot
    $suitePytestTempRoot = New-SuitePytestTempRoot
    Assert-SuiteRelevantVolumeFreeSpace -Phase "post-lease"
    Assert-SuiteFrozenSystemTempRoot -Phase "suite Python cache-root creation"
    $pythonCacheRoot = Join-Path $suiteSystemTempRoot (
        "weather-bounded-python-cache-{0}" -f ([guid]::NewGuid().ToString("N"))
    )
    if (Test-Path -LiteralPath $pythonCacheRoot) {
        throw "unique suite-owned Python cache root already exists: $pythonCacheRoot"
    }
    [void][IO.Directory]::CreateDirectory($pythonCacheRoot)
    Assert-SuitePythonCacheRoot
    $env:PYTHONPATH = @(
        $WorktreeRoot,
        (Join-Path $WorktreeRoot "src")
    ) -join [IO.Path]::PathSeparator
    $env:TMPDIR = $suiteSystemTempRoot
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    $env:PYTHONPYCACHEPREFIX = $pythonCacheRoot
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTHONHASHSEED = "0"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:WEATHER_INTEGRATION_TEST_OFFLINE = "1"
    $env:WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT = $RepoRoot
    $env:WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT = $evidenceRoot
    [Environment]::SetEnvironmentVariable(
        "WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT",
        $null,
        [EnvironmentVariableTarget]::Process
    )
    $env:WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT = $WorktreeRoot
    $env:WEATHER_INTEGRATION_TEST_SECRET_POLICY = "conservative_v1"
    $env:WEATHER_INTEGRATION_TEST_TEMP_POLICY = "system_temp_unique_v1"
    $env:WEATHER_INTEGRATION_TEST_PYTHON_EXECUTABLE = $python
    $env:WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE = $suiteBoundGitPath
    $env:WEATHER_INTEGRATION_TEST_POWERSHELL_EXECUTABLE =
        $suiteBoundPowerShellPath
    $env:SETUPTOOLS_USE_DISTUTILS = "stdlib"
    if ($additionalPythonRoots.Count -gt 0) {
        $env:PYTHONPATH = @($env:PYTHONPATH, $additionalPythonRoots) -join `
            [IO.Path]::PathSeparator
    }
    if ($RequireLiveSdkContract) {
        $env:WEATHER_REQUIRE_LIVE_SDK_CONTRACT = "1"
    }
    Write-SuiteLog (
        "python_cache_prefix=$pythonCacheRoot python_dont_write_bytecode=1 " +
        "python_hash_seed=0 python_utf8=1 python_io_encoding=utf-8 " +
        "git_allow_protocol=file git_terminal_prompt=0 " +
        "git_child_environment_isolated=true git_topology_controls_clear=true " +
        "integration_test_offline=1 integration_test_production_root=$RepoRoot " +
        "integration_test_evidence_root_protected=true " +
        "integration_test_allowed_write_root=none " +
        "integration_test_candidate_root=$WorktreeRoot " +
        "integration_test_secret_policy=conservative_v1 secret_environment_scrubbed=true " +
        "secret_environment_count=0 " +
        "integration_test_temp_policy=system_temp_unique_v1 " +
        "system_temp_root_frozen=true system_temp_root_disjoint=true " +
        "integration_test_python_executable=$python " +
        "integration_test_git_executable=$suiteBoundGitPath " +
        "integration_test_powershell_executable=$suiteBoundPowerShellPath " +
        "setuptools_use_distutils=stdlib " +
        "pythonpath_worktree_root=true pythonpath_worktree_src=true " +
        "cache_initially_empty=true"
    )
    Write-SuiteLog (
        "python_executable_sha256=$pythonExecutableSha256 " +
        "pythonw_executable_sha256=$pythonwExecutableSha256 " +
        "git_executable_sha256=$suiteBoundGitSha256 " +
        "powershell_executable_sha256=$suiteBoundPowerShellSha256 " +
        "pth_bootstrap_sha256=$($suitePthBootstrap.Sha256) " +
        "pth_bootstrap_files=$($suitePthBootstrap.FileCount) " +
        "ancestry_regular=true handles_retained=true"
    )
    Assert-HostAdmission -CommitCeiling $StartCommitPercent -Phase "entry"
    Assert-NoIgnoredPythonImportArtifacts
    Write-SuiteLog "ignored_python_native_import_artifacts=0"
    Set-Location -LiteralPath $WorktreeRoot
    $trackedWorktreePre = Get-SuiteTrackedWorktreeFingerprint `
        -Phase "pre" -RetainStreams
    $trackedWorktreePrePath = "$LogPath.tracked-worktree.pre.json"
    Write-SuiteRetainedSidecar `
        -Path $trackedWorktreePrePath -Text ([string]$trackedWorktreePre.Json) | Out-Null
    Write-SuiteLog (
        "tracked_worktree phase=pre schema=tracked_worktree_content_fingerprint_v1 " +
        "sha256=$($trackedWorktreePre.Sha256) files=$($trackedWorktreePre.FileCount) " +
        "bytes=$($trackedWorktreePre.TotalBytes) " +
        "lfs_files=$($trackedWorktreePre.LfsFileCount) path=$trackedWorktreePrePath"
    )
    $toolchainPre = Get-SuiteIntegrationToolchainFingerprint -Phase "pre"
    $toolchainPrePath = "$LogPath.integration-toolchain.pre.json"
    Write-SuiteRetainedSidecar `
        -Path $toolchainPrePath -Text ([string]$toolchainPre.Json) | Out-Null
    Write-SuiteLog (
        "integration_toolchain phase=pre schema=integration_toolchain_fingerprint_v1 " +
        "sha256=$($toolchainPre.Sha256) git_sha256=$($toolchainPre.GitSha256) " +
        "git_lfs_sha256=$($toolchainPre.GitLfsSha256) " +
        "powershell_sha256=$($toolchainPre.PowerShellSha256) " +
        "git_path=$($toolchainPre.GitPath) " +
        "powershell_path=$($toolchainPre.PowerShellPath) path=$toolchainPrePath"
    )
    $pythonEnvironmentPre = Get-SuitePythonEnvironmentFingerprint -Phase "pre"
    $pythonEnvironmentPrePath = "$LogPath.python-environment.pre.json"
    Write-SuiteRetainedSidecar `
        -Path $pythonEnvironmentPrePath -Text ([string]$pythonEnvironmentPre.Json) | Out-Null
    Write-SuiteLog (
        "python_environment phase=pre schema=python_environment_fingerprint_v2 " +
        "sha256=$($pythonEnvironmentPre.Sha256) " +
        "distributions=$($pythonEnvironmentPre.DistributionCount) " +
        "files=$($pythonEnvironmentPre.FileCount) bytes=$($pythonEnvironmentPre.TotalBytes) " +
        "path=$pythonEnvironmentPrePath"
    )
    $importProbeCode = (
        "import hashlib,json,pathlib,sys,weather; " +
        "p=pathlib.Path(weather.__file__).resolve(); " +
        "result={'schema_version':'weather_import_probe_v1'," +
        "'weather_file':str(p),'weather_file_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}; " +
        "sys.stdout.write(json.dumps(result,sort_keys=True,separators=(',',':')))"
    )
    $importProbeProcess = Invoke-SuitePythonChild `
        -Tokens @("-c", $importProbeCode) `
        -WorkingDirectory $WorktreeRoot `
        -Phase "exact-worktree import probe"
    $importProbeExit = [int]$importProbeProcess.ExitCode
    if ($importProbeExit -ne 0) {
        $importDiagnostic = (@(
            [string]$importProbeProcess.Stderr,
            [string]$importProbeProcess.Stdout
        ) | ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -First 1)
        if ([string]::IsNullOrWhiteSpace([string]$importDiagnostic)) {
            $importDiagnostic = "no bounded child diagnostic output"
        }
        if ($importDiagnostic.Length -gt 512) {
            $importDiagnostic = $importDiagnostic.Substring(0, 512)
        }
        throw "exact-worktree import probe failed with exit code ${importProbeExit}: $importDiagnostic"
    }
    $importProbeText = [string]$importProbeProcess.Stdout
    try { $importProbe = $importProbeText | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "exact-worktree import probe returned unreadable JSON" }
    if ($null -eq $importProbe -or $importProbe -is [System.Array] -or
        [string]$importProbe.schema_version -cne "weather_import_probe_v1" -or
        [string]::IsNullOrWhiteSpace([string]$importProbe.weather_file) -or
        [string]$importProbe.weather_file_sha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "exact-worktree import probe returned the wrong object shape"
    }
    $resolvedImport = [string]$importProbe.weather_file
    $resolvedImport = (Resolve-Path -LiteralPath $resolvedImport -ErrorAction Stop).Path
    $expectedWeatherImport = (
        Resolve-Path -LiteralPath (
            Join-Path $WorktreeRoot "src\weather\__init__.py"
        ) -ErrorAction Stop
    ).Path
    if (-not $resolvedImport.Equals(
        $expectedWeatherImport,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "suite imports do not resolve from the exact worktree: $resolvedImport"
    }
    $resolvedImportSha256 = [string]$importProbe.weather_file_sha256
    $importProbeSha256 = [string]$importProbeProcess.StdoutSha256
    Write-SuiteLog (
        "weather_import=$resolvedImport weather_import_sha256=$resolvedImportSha256 " +
        "import_probe_stdout_sha256=$importProbeSha256"
    )
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
            "tests/operations/test_ci_workflow_contract.py",
            "tests/operations/test_offline_test_boundary.py",
            "tests/operations/test_integration_attempt_scripts.py",
            "tests/operations/test_integration_attempt_preparation_scripts.py",
            "tests/operations/test_integration_attempt_evidence_recovery_hardening.py",
            "tests/operations/test_integration_attempt_registration_safety.py",
            "tests/operations/test_one_shot_readiness_script.py",
            "tests/operations/test_one_shot_registry_scripts.py",
            "tests/operations/test_status_script.py",
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
        $trackedTestQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $WorktreeRoot -Arguments @("ls-files", "--", "tests") `
            -Label "tracked pytest inventory query"
        $trackedTestFiles = @($trackedTestQuery.StdoutLines)
        $testFiles = @(
            $trackedTestFiles |
                ForEach-Object { ([string]$_).Replace("\", "/") } |
                Where-Object { $_ -match '^tests/(?:.*/)?(?:test_[^/]*|[^/]+_test)\.py$' } |
                Sort-Object
        )
    }
    if ($testFiles.Count -eq 0) { throw "no pytest files found in exact worktree" }
    if ($SmokeTest) {
        $testFiles = @($testFiles | Select-Object -First ([math]::Min(2, $testFiles.Count)))
    }

    $trackedSourceQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("ls-files", "--", "*.py", "*.ps1") `
        -Label "tracked syntax inventory query"
    $trackedSourceRows = @($trackedSourceQuery.StdoutLines)
    $trackedPythonFiles = @($trackedSourceRows | ForEach-Object {
        ([string]$_).Replace("\", "/")
    } | Where-Object { $_ -match '(?i)\.py$' } | Sort-Object -Unique)
    $trackedPowerShellFiles = @($trackedSourceRows | ForEach-Object {
        ([string]$_).Replace("\", "/")
    } | Where-Object { $_ -match '(?i)\.ps1$' } | Sort-Object -Unique)
    if ($trackedPythonFiles.Count -eq 0 -or $trackedPowerShellFiles.Count -eq 0) {
        throw "tracked syntax inventory is unexpectedly empty"
    }
    $pythonInventorySha256 = Get-SuiteInventorySha256 -Paths $trackedPythonFiles
    $powerShellInventorySha256 = Get-SuiteInventorySha256 -Paths $trackedPowerShellFiles
    $pythonListPath = "$LogPath.python-syntax-inventory.txt"
    $powerShellListPath = "$LogPath.powershell-syntax-inventory.txt"
    Write-SuiteRetainedSidecar `
        -Path $pythonListPath `
        -Text ((@($trackedPythonFiles) -join "`n") + "`n") | Out-Null
    Write-SuiteRetainedSidecar `
        -Path $powerShellListPath `
        -Text ((@($trackedPowerShellFiles) -join "`n") + "`n") | Out-Null
    $syntaxCode = "import pathlib,sys; r=pathlib.Path(sys.argv[2]); [compile((r/p).read_bytes(),p,'exec') for p in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines()]"
    $syntaxProcessResult = Invoke-SuitePythonChild `
        -Tokens @("-c", $syntaxCode, $pythonListPath, $WorktreeRoot) `
        -WorkingDirectory $WorktreeRoot `
        -Phase "tracked Python syntax validation"
    $syntaxExitCode = [int]$syntaxProcessResult.ExitCode
    if ($syntaxExitCode -ne 0) {
        throw "exact tracked Python syntax validation failed"
    }
    $powerShellParseErrors = New-Object System.Collections.Generic.List[string]
    foreach ($relativePath in $trackedPowerShellFiles) {
        if (Test-SuiteRuntimeCeilingReached) {
            throw "tracked PowerShell syntax validation reached the runtime ceiling"
        }
        $tokens = $null
        $parseErrors = $null
        [Management.Automation.Language.Parser]::ParseFile(
            (Join-Path $WorktreeRoot $relativePath.Replace("/", "\")),
            [ref]$tokens,
            [ref]$parseErrors
        ) | Out-Null
        foreach ($parseError in @($parseErrors)) {
            $powerShellParseErrors.Add("${relativePath}: $($parseError.Message)")
        }
    }
    if ($powerShellParseErrors.Count -ne 0) {
        throw "exact tracked PowerShell syntax validation failed: $($powerShellParseErrors -join ' | ')"
    }
    Write-SuiteLog (
        "syntax python_files=$($trackedPythonFiles.Count) " +
        "python_inventory_sha256=$pythonInventorySha256 python_list=$pythonListPath " +
        "powershell_files=$($trackedPowerShellFiles.Count) " +
        "powershell_inventory_sha256=$powerShellInventorySha256 " +
        "powershell_list=$powerShellListPath python_exit=$syntaxExitCode powershell_errors=0"
    )

    $chunks = @()
    for ($offset = 0; $offset -lt $testFiles.Count; $offset += $MaxFilesPerChunk) {
        $last = [math]::Min($offset + $MaxFilesPerChunk - 1, $testFiles.Count - 1)
        $chunks += ,@($testFiles[$offset..$last])
    }
    Write-SuiteLog "planned chunks=$($chunks.Count) files=$($testFiles.Count) max_files=$MaxFilesPerChunk"
    $testInventorySha256 = Get-SuiteInventorySha256 -Paths $testFiles
    $testInventoryPath = "$LogPath.test-inventory.txt"
    Write-SuiteRetainedSidecar `
        -Path $testInventoryPath `
        -Text ((@($testFiles) -join "`n") + "`n") | Out-Null

    $runTag = "{0}-{1}" -f `
        (Get-Date -Format "yyyyMMddTHHmmss"), ([guid]::NewGuid().ToString("N"))
    $failedChunks = 0
    $aggregateTests = 0
    $aggregateFailures = 0
    $aggregateErrors = 0
    $aggregateSkipped = 0
    $aggregateDeselected = 0
    for ($index = 0; $index -lt $chunks.Count; $index++) {
        $ordinal = $index + 1
        if ((Get-Date) -ge $hardStop) {
            throw "bounded suite reached the 09:00 hard teardown boundary"
        }
        if (Test-SuiteRuntimeCeilingReached) {
            throw "bounded suite reached its runtime ceiling"
        }
        Assert-HostAdmission -CommitCeiling $AbortCommitPercent -Phase "chunk-$ordinal"
        Assert-SuiteWorktreeCheckpoint -Phase ("chunk-{0:D3}-pre" -f $ordinal) |
            Out-Null
        Assert-SuiteRelevantVolumeFreeSpace -Phase ("chunk-{0:D3}" -f $ordinal)
        $pytestTempPath = Join-Path $suitePytestTempRoot (
            "chunk-{0:D3}-{1}" -f $ordinal, ([guid]::NewGuid().ToString("N"))
        )
        if (Test-Path -LiteralPath $pytestTempPath) {
            throw "unique per-chunk pytest temp path already exists"
        }
        $junitEvidencePath = "{0}.{1}.chunk-{2:D3}.xml" -f `
            $LogPath, $runTag, $ordinal
        $junitTempPath = Join-Path $suiteChildOutputRoot (
            "chunk-{0:D3}-{1}.xml" -f $ordinal, ([guid]::NewGuid().ToString("N"))
        )
        if ((Test-Path -LiteralPath $junitEvidencePath) -or
            (Test-Path -LiteralPath $junitTempPath)) {
            throw "unique test-child JUnit path already exists"
        }
        $tokens = @(
            "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--basetemp", $pytestTempPath, "--junitxml", $junitTempPath
        ) + @($chunks[$index])
        Write-SuiteLog (
            "chunk $ordinal/$($chunks.Count) starting " +
            "files=$($chunks[$index].Count) junit_evidence=$junitEvidencePath"
        )

        $childResult = $null
        $childInvocationFailure = $null
        try {
            $childResult = Invoke-SuitePythonChild `
                -Tokens $tokens `
                -WorkingDirectory $WorktreeRoot `
                -Phase "pytest chunk $ordinal"
        }
        catch { $childInvocationFailure = $_ }

        # Acquire the JUnit generation immediately after the complete child
        # tree has drained. Keep this no-write/no-delete handle across the
        # post-child authority checkpoint, then hash and parse only its held
        # bytes. No evidence decision below reopens the pathname.
        $junitReadHandle = $null
        $junitOpenFailure = $null
        try {
            $junitReadHandle = Open-SuiteBoundedFileReadHandle `
                -Path $junitTempPath -MaxBytes 67108864 `
                -Label "pytest chunk $ordinal JUnit"
        }
        catch { $junitOpenFailure = $_ }
        $postCheckpointFailure = $null
        try {
            Assert-SuiteWorktreeCheckpoint `
                -Phase ("chunk-{0:D3}-post" -f $ordinal) | Out-Null
        }
        catch { $postCheckpointFailure = $_ }
        if ($null -ne $childInvocationFailure -or
            $null -ne $postCheckpointFailure) {
            $primaryPostChildFailure = if ($null -ne $childInvocationFailure) {
                $childInvocationFailure
            }
            else { $postCheckpointFailure }
            if ($null -ne $childInvocationFailure -and
                $null -ne $postCheckpointFailure) {
                $primaryPostChildFailure.Exception.Data[
                    "weather_post_child_checkpoint_failure"
                ] = $postCheckpointFailure.Exception.Message
            }
            if ($null -ne $junitOpenFailure) {
                $primaryPostChildFailure.Exception.Data["weather_junit_open_failure"] =
                    $junitOpenFailure.Exception.Message
            }
            if ($null -ne $junitReadHandle) {
                try { $junitReadHandle.Stream.Dispose() }
                catch {
                    $primaryPostChildFailure.Exception.Data[
                        "weather_junit_handle_cleanup_failure"
                    ] =
                        $_.Exception.Message
                }
            }
            throw $primaryPostChildFailure
        }
        $exitCode = [int]$childResult.ExitCode
        Write-SuiteLog "chunk $ordinal/$($chunks.Count) exit=$exitCode"
        $junitValidationFailure = $null
        try {
            if ($null -ne $junitOpenFailure) { throw $junitOpenFailure }
            $junitSnapshot = Read-SuiteBoundedFileHandleSnapshot `
                -Handle $junitReadHandle -Label "pytest chunk $ordinal JUnit"
            $junitSummary = Get-SuiteJUnitSummary `
                -Snapshot $junitSnapshot `
                -Path $junitTempPath -EvidencePath $junitEvidencePath
            $junitSha256 = $junitSummary.sha256
            Write-SuiteLog (
                "chunk $ordinal/$($chunks.Count) junit_summary path=$junitEvidencePath " +
                "sha256=$junitSha256 tests=$($junitSummary.tests) " +
                "failures=$($junitSummary.failures) errors=$($junitSummary.errors) " +
                "skipped=$($junitSummary.skipped) deselected=$($junitSummary.deselected)"
            )
            $aggregateTests += [int]$junitSummary.tests
            $aggregateFailures += [int]$junitSummary.failures
            $aggregateErrors += [int]$junitSummary.errors
            $aggregateSkipped += [int]$junitSummary.skipped
            $aggregateDeselected += [int]$junitSummary.deselected
        }
        catch {
            $junitValidationFailure = $_
            Write-SuiteLog "chunk $ordinal/$($chunks.Count) JUnit validation failed: $($_.Exception.Message)"
            $failedChunks++
        }
        finally {
            if ($null -ne $junitReadHandle) {
                try { $junitReadHandle.Stream.Dispose() }
                catch {
                    $junitHandleCleanupMessage = $_.Exception.Message
                    if ($null -ne $junitValidationFailure) {
                        $junitValidationFailure.Exception.Data[
                            "weather_junit_handle_cleanup_failure"
                        ] = $junitHandleCleanupMessage
                        Write-SuiteLog (
                            "chunk $ordinal/$($chunks.Count) JUnit handle cleanup " +
                            "also failed: $junitHandleCleanupMessage"
                        )
                    }
                    else {
                        throw (
                            "chunk $ordinal JUnit handle cleanup failed: " +
                            $junitHandleCleanupMessage
                        )
                    }
                }
            }
        }
        try { Remove-SuiteOwnedJUnitTemp -Path $junitTempPath }
        catch {
            $junitCleanupMessage = $_.Exception.Message
            if ($null -ne $junitValidationFailure) {
                $junitValidationFailure.Exception.Data["weather_cleanup_failure"] =
                    $junitCleanupMessage
                Write-SuiteLog (
                    "chunk $ordinal/$($chunks.Count) JUnit cleanup also failed: " +
                    $junitCleanupMessage
                )
                $failedChunks++
            }
            else {
                throw "chunk $ordinal JUnit cleanup failed: $junitCleanupMessage"
            }
        }
        try { Remove-SuiteOwnedPytestTemp -Path $pytestTempPath }
        catch {
            $pytestCleanupMessage = $_.Exception.Message
            if ($null -ne $junitValidationFailure -or $exitCode -ne 0) {
                if ($null -ne $junitValidationFailure) {
                    $junitValidationFailure.Exception.Data["weather_pytest_temp_cleanup_failure"] =
                        $pytestCleanupMessage
                }
                Write-SuiteLog (
                    "chunk $ordinal/$($chunks.Count) pytest-temp cleanup also failed: " +
                    $pytestCleanupMessage
                )
                $failedChunks++
            }
            else { throw "chunk $ordinal pytest-temp cleanup failed: $pytestCleanupMessage" }
        }
        if ($exitCode -ne 0) { $failedChunks++ }
    }

    Write-SuiteLog (
        "aggregate tests=$aggregateTests failures=$aggregateFailures " +
        "errors=$aggregateErrors skipped=$aggregateSkipped " +
        "deselected=$aggregateDeselected planned_files=$($testFiles.Count) " +
        "inventory_sha256=$testInventorySha256 inventory_path=$testInventoryPath"
    )

    if ($failedChunks -ne 0) {
        Write-SuiteLog "VERDICT: $failedChunks CHUNK(S) FAILED; do not merge"
        exit 1
    }

    # The worktree, movable branch ref, and tracked test inventory can change
    # while the chunks run. Re-prove all three after the final child exits and
    # before emitting the sole merge-eligible terminal verdict.
    $finalWorktreeTipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}") `
        -Label "final exact worktree tip query"
    $finalWorktreeTipRows = @($finalWorktreeTipQuery.StdoutLines)
    if ($finalWorktreeTipRows.Count -ne 1) {
        throw "could not re-resolve the exact worktree tip after the final chunk"
    }
    $finalWorktreeTip = ([string]$finalWorktreeTipRows[0]).Trim().ToLowerInvariant()
    $finalBranchTipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepoRoot `
        -Arguments @(
            "rev-parse", "--verify", "--end-of-options", "${BranchRef}^{commit}"
        ) `
        -Label "final exact branch tip query"
    $finalBranchTipRows = @($finalBranchTipQuery.StdoutLines)
    if ($finalBranchTipRows.Count -ne 1) {
        throw "could not re-resolve BranchRef after the final chunk"
    }
    $finalBranchTip = ([string]$finalBranchTipRows[0]).Trim().ToLowerInvariant()
    if ($finalWorktreeTip -ne $ExpectedTip -or $finalBranchTip -ne $ExpectedTip) {
        throw "exact branch/worktree identity changed while the suite was running"
    }
    $finalDirtyQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot `
        -Arguments @("status", "--porcelain=v1", "--untracked-files=all") `
        -Label "final clean-worktree query"
    $finalDirty = @($finalDirtyQuery.StdoutLines)
    if ($finalDirty.Count -ne 0) {
        throw "suite worktree changed while the suite was running"
    }
    Assert-NoIgnoredPythonImportArtifacts
    Write-SuiteLog "final_ignored_python_native_import_artifacts=0"
    if (-not $SmokeTest -and -not $IntegrationPreflight) {
        $finalTrackedQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $WorktreeRoot -Arguments @("ls-files", "--", "tests") `
            -Label "final tracked pytest inventory query"
        $finalTrackedRows = @($finalTrackedQuery.StdoutLines)
        $finalTestFiles = @(
            $finalTrackedRows |
                ForEach-Object { ([string]$_).Replace("\", "/") } |
                Where-Object { $_ -match '^tests/(?:.*/)?(?:test_[^/]*|[^/]+_test)\.py$' } |
                Sort-Object
        )
        if ($finalTestFiles.Count -ne $testFiles.Count -or
            @(Compare-Object -ReferenceObject @($testFiles) -DifferenceObject @($finalTestFiles)).Count -ne 0) {
            throw "tracked pytest inventory changed while the suite was running"
        }
    }
    $trackedWorktreePost = Get-SuiteTrackedWorktreeFingerprint `
        -Phase "post" -ReuseRetainedStreams
    $trackedWorktreePostPath = "$LogPath.tracked-worktree.post.json"
    Write-SuiteRetainedSidecar `
        -Path $trackedWorktreePostPath -Text ([string]$trackedWorktreePost.Json) | Out-Null
    Write-SuiteLog (
        "tracked_worktree phase=post schema=tracked_worktree_content_fingerprint_v1 " +
        "sha256=$($trackedWorktreePost.Sha256) files=$($trackedWorktreePost.FileCount) " +
        "bytes=$($trackedWorktreePost.TotalBytes) " +
        "lfs_files=$($trackedWorktreePost.LfsFileCount) path=$trackedWorktreePostPath"
    )
    if ([string]$trackedWorktreePost.Sha256 -cne [string]$trackedWorktreePre.Sha256 -or
        [int]$trackedWorktreePost.FileCount -ne [int]$trackedWorktreePre.FileCount -or
        [int64]$trackedWorktreePost.TotalBytes -ne [int64]$trackedWorktreePre.TotalBytes -or
        [int]$trackedWorktreePost.LfsFileCount -ne [int]$trackedWorktreePre.LfsFileCount) {
        throw "tracked worktree content changed while the bounded suite was running"
    }
    $toolchainPost = Get-SuiteIntegrationToolchainFingerprint -Phase "post"
    $toolchainPostPath = "$LogPath.integration-toolchain.post.json"
    Write-SuiteRetainedSidecar `
        -Path $toolchainPostPath -Text ([string]$toolchainPost.Json) | Out-Null
    Write-SuiteLog (
        "integration_toolchain phase=post schema=integration_toolchain_fingerprint_v1 " +
        "sha256=$($toolchainPost.Sha256) git_sha256=$($toolchainPost.GitSha256) " +
        "git_lfs_sha256=$($toolchainPost.GitLfsSha256) " +
        "powershell_sha256=$($toolchainPost.PowerShellSha256) " +
        "git_path=$($toolchainPost.GitPath) " +
        "powershell_path=$($toolchainPost.PowerShellPath) path=$toolchainPostPath"
    )
    if ([string]$toolchainPost.Sha256 -cne [string]$toolchainPre.Sha256 -or
        -not ([string]$toolchainPost.GitPath).Equals(
            [string]$toolchainPre.GitPath,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not ([string]$toolchainPost.PowerShellPath).Equals(
            [string]$toolchainPre.PowerShellPath,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "integration toolchain changed while the bounded suite was running"
    }
    $pythonEnvironmentPost = Get-SuitePythonEnvironmentFingerprint -Phase "post"
    $pythonEnvironmentPostPath = "$LogPath.python-environment.post.json"
    Write-SuiteRetainedSidecar `
        -Path $pythonEnvironmentPostPath -Text ([string]$pythonEnvironmentPost.Json) | Out-Null
    Write-SuiteLog (
        "python_environment phase=post schema=python_environment_fingerprint_v2 " +
        "sha256=$($pythonEnvironmentPost.Sha256) " +
        "distributions=$($pythonEnvironmentPost.DistributionCount) " +
        "files=$($pythonEnvironmentPost.FileCount) bytes=$($pythonEnvironmentPost.TotalBytes) " +
        "path=$pythonEnvironmentPostPath"
    )
    if ([string]$pythonEnvironmentPost.Sha256 -cne
            [string]$pythonEnvironmentPre.Sha256 -or
        [int]$pythonEnvironmentPost.DistributionCount -ne
            [int]$pythonEnvironmentPre.DistributionCount -or
        [int]$pythonEnvironmentPost.FileCount -ne [int]$pythonEnvironmentPre.FileCount -or
        [int64]$pythonEnvironmentPost.TotalBytes -ne
            [int64]$pythonEnvironmentPre.TotalBytes) {
        throw "Python environment changed while the bounded suite was running"
    }

    # The post fingerprint is itself a contained Python child. Re-prove the
    # exact ref/worktree and ignored namespace after it exits before PASS.
    $postFingerprintWorktreeTip = @(
        (Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $WorktreeRoot `
            -Arguments @(
                "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"
            ) `
            -Label "post-fingerprint worktree tip query").StdoutLines
    )
    $postFingerprintBranchTip = @(
        (Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $RepoRoot `
            -Arguments @(
                "rev-parse", "--verify", "--end-of-options", "${BranchRef}^{commit}"
            ) `
            -Label "post-fingerprint branch tip query").StdoutLines
    )
    if ($postFingerprintWorktreeTip.Count -ne 1 -or
        $postFingerprintBranchTip.Count -ne 1 -or
        ([string]$postFingerprintWorktreeTip[0]).Trim().ToLowerInvariant() -ne
            $ExpectedTip -or
        ([string]$postFingerprintBranchTip[0]).Trim().ToLowerInvariant() -ne
            $ExpectedTip) {
        throw "exact branch/worktree identity changed during the post fingerprint"
    }
    $postFingerprintDirty = @(
        (Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $WorktreeRoot `
            -Arguments @("status", "--porcelain=v1", "--untracked-files=all") `
            -Label "post-fingerprint clean-worktree query").StdoutLines
    )
    if ($postFingerprintDirty.Count -ne 0) {
        throw "suite worktree changed during the post fingerprint"
    }
    Assert-NoIgnoredPythonImportArtifacts
    Write-SuiteLog (
        "python_environment stable=true " +
        "pre_sha256=$($pythonEnvironmentPre.Sha256) " +
        "post_sha256=$($pythonEnvironmentPost.Sha256) " +
        "distributions=$($pythonEnvironmentPost.DistributionCount) " +
        "files=$($pythonEnvironmentPost.FileCount) bytes=$($pythonEnvironmentPost.TotalBytes)"
    )
    Write-SuiteLog (
        "integration_toolchain stable=true " +
        "pre_sha256=$($toolchainPre.Sha256) post_sha256=$($toolchainPost.Sha256)"
    )
    Write-SuiteLog (
        "tracked_worktree stable=true " +
        "pre_sha256=$($trackedWorktreePre.Sha256) " +
        "post_sha256=$($trackedWorktreePost.Sha256) " +
        "files=$($trackedWorktreePost.FileCount) bytes=$($trackedWorktreePost.TotalBytes) " +
        "lfs_files=$($trackedWorktreePost.LfsFileCount)"
    )
    Assert-SuitePythonGitTopologyClear -Phase "final PASS boundary"
    Assert-SuiteQualifiedPthBootstrapUnchanged -Phase "final PASS boundary"
    Write-SuiteLog (
        "python_pth_bootstrap stable=true sha256=$($suitePthBootstrap.Sha256) " +
        "files=$($suitePthBootstrap.FileCount) handles_retained=true"
    )
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
catch {
    $suiteExecutionFailure = $_
    throw
}
finally {
    $cleanupFailures = New-Object System.Collections.Generic.List[string]
    try { Set-Location -LiteralPath $previousLocation }
    catch { $cleanupFailures.Add("working directory: $($_.Exception.Message)") }
    foreach ($restoration in @(
        [pscustomobject]@{ Name = "PYTHONPATH"; Value = $previousPythonPath }
        [pscustomobject]@{ Name = "TMPDIR"; Value = $previousTmpDir }
        [pscustomobject]@{
            Name = "WEATHER_REQUIRE_LIVE_SDK_CONTRACT"
            Value = $previousLiveSdkRequirement
        }
        [pscustomobject]@{ Name = "PYTHONNOUSERSITE"; Value = $previousNoUserSite }
        [pscustomobject]@{
            Name = "PYTEST_DISABLE_PLUGIN_AUTOLOAD"
            Value = $previousPluginAutoload
        }
        [pscustomobject]@{
            Name = "PYTHONPYCACHEPREFIX"
            Value = $previousPycachePrefix
        }
        [pscustomobject]@{
            Name = "PYTHONDONTWRITEBYTECODE"
            Value = $previousDontWriteBytecode
        }
        [pscustomobject]@{ Name = "PYTHONHASHSEED"; Value = $previousPythonHashSeed }
        [pscustomobject]@{ Name = "PYTHONUTF8"; Value = $previousPythonUtf8 }
        [pscustomobject]@{
            Name = "PYTHONIOENCODING"
            Value = $previousPythonIoEncoding
        }
        [pscustomobject]@{
            Name = "GIT_ALLOW_PROTOCOL"
            Value = $previousGitAllowProtocol
        }
        [pscustomobject]@{
            Name = "GIT_TERMINAL_PROMPT"
            Value = $previousGitTerminalPrompt
        }
        [pscustomobject]@{
            Name = "GIT_CONFIG_NOSYSTEM"
            Value = $previousGitConfigNoSystem
        }
        [pscustomobject]@{
            Name = "GIT_CONFIG_SYSTEM"
            Value = $previousGitConfigSystem
        }
        [pscustomobject]@{
            Name = "GIT_CONFIG_GLOBAL"
            Value = $previousGitConfigGlobal
        }
        [pscustomobject]@{
            Name = "GIT_CONFIG_COUNT"
            Value = $previousGitConfigCount
        }
        [pscustomobject]@{
            Name = "GIT_ATTR_NOSYSTEM"
            Value = $previousGitAttrNoSystem
        }
        [pscustomobject]@{
            Name = "GIT_PROTOCOL_FROM_USER"
            Value = $previousGitProtocolFromUser
        }
        [pscustomobject]@{
            Name = "GIT_OPTIONAL_LOCKS"
            Value = $previousGitOptionalLocks
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_OFFLINE"
            Value = $previousIntegrationTestOffline
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"
            Value = $previousIntegrationTestProductionRoot
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT"
            Value = $previousIntegrationTestEvidenceRoot
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT"
            Value = $previousIntegrationTestAllowedWriteRoot
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT"
            Value = $previousIntegrationTestCandidateRoot
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_SECRET_POLICY"
            Value = $previousIntegrationTestSecretPolicy
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_TEMP_POLICY"
            Value = $previousIntegrationTestTempPolicy
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_PYTHON_EXECUTABLE"
            Value = $previousIntegrationTestPythonExecutable
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE"
            Value = $previousIntegrationTestGitExecutable
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_POWERSHELL_EXECUTABLE"
            Value = $previousIntegrationTestPowerShellExecutable
        }
        [pscustomobject]@{
            Name = "WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE"
            Value = $previousIntegrationTestReadOnlyProductionProbe
        }
        [pscustomobject]@{
            Name = "SETUPTOOLS_USE_DISTUTILS"
            Value = $previousSetuptoolsUseDistutils
        }
    )) {
        try {
            [Environment]::SetEnvironmentVariable(
                [string]$restoration.Name,
                $restoration.Value,
                [EnvironmentVariableTarget]::Process
            )
        }
        catch {
            $cleanupFailures.Add(
                "environment $([string]$restoration.Name): $($_.Exception.Message)"
            )
        }
    }
    try { Remove-SuiteOwnedPythonCacheRoot }
    catch { $cleanupFailures.Add("Python cache root: $($_.Exception.Message)") }
    try { Remove-SuiteChildOutputRoot }
    catch { $cleanupFailures.Add("suite child-output root: $($_.Exception.Message)") }
    try { Remove-SuitePytestTempRoot }
    catch { $cleanupFailures.Add("suite pytest-temp root: $($_.Exception.Message)") }
    if ($null -ne $workloadLease) {
        try { Exit-WeatherHeavyWorkloadLease -Lease $workloadLease }
        catch { $cleanupFailures.Add("heavy-workload lease: $($_.Exception.Message)") }
    }
    if ($cleanupFailures.Count -ne 0) {
        $cleanupMessage = "bounded suite cleanup failed: $($cleanupFailures -join ' | ')"
        if ($null -ne $suiteExecutionFailure) {
            $suiteExecutionFailure.Exception.Data["weather_cleanup_failure"] = $cleanupMessage
            Write-Warning $cleanupMessage -WarningAction Continue
        }
        else { throw $cleanupMessage }
    }
}
}
catch {
    $suiteOuterFailure = $_
    throw
}
finally {
    $outerCleanupFailures = New-Object System.Collections.Generic.List[string]
    foreach ($secretRestoration in @($secretEnvironmentRestorations)) {
        try {
            [Environment]::SetEnvironmentVariable(
                [string]$secretRestoration.Name,
                $secretRestoration.Value,
                [EnvironmentVariableTarget]::Process
            )
        }
        catch {
            $outerCleanupFailures.Add(
                "secret-bearing environment restoration failed"
            )
        }
    }
    foreach ($sidecarStream in @($suiteSidecarStreams)) {
        try { $sidecarStream.Dispose() }
        catch {
            $outerCleanupFailures.Add(
                "retained evidence sidecar handle: $($_.Exception.Message)"
            )
        }
    }
    foreach ($readStream in @($suiteEvidenceReadStreams)) {
        try { $readStream.Dispose() }
        catch {
            $outerCleanupFailures.Add(
                "retained evidence read handle: $($_.Exception.Message)"
            )
        }
    }
    if ($null -ne $suiteLogWriter) {
        try {
            $suiteLogWriter.Flush()
            $suiteLogHandle.Stream.Flush($true)
        }
        catch { $outerCleanupFailures.Add("suite log flush: $($_.Exception.Message)") }
        try { $suiteLogWriter.Dispose() }
        catch { $outerCleanupFailures.Add("suite log writer: $($_.Exception.Message)") }
    }
    if ($null -ne $suiteLogHandle -and $null -ne $suiteLogHandle.Stream) {
        try { $suiteLogHandle.Stream.Dispose() }
        catch { $outerCleanupFailures.Add("suite log handle: $($_.Exception.Message)") }
    }
    if ($outerCleanupFailures.Count -ne 0) {
        $outerCleanupMessage = (
            "bounded suite retained evidence cleanup failed: " +
            ($outerCleanupFailures -join " | ")
        )
        if ($null -ne $suiteOuterFailure) {
            $suiteOuterFailure.Exception.Data["weather_evidence_cleanup_failure"] =
                $outerCleanupMessage
            Write-Warning $outerCleanupMessage -WarningAction Continue
        }
        else { throw $outerCleanupMessage }
    }
}
