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
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$ExpectedGitExecutable = ""
    )

    $query = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root -Arguments $Arguments `
        -ExpectedGitExecutable $ExpectedGitExecutable `
        -Label "integration merge local Git query: $($Arguments -join ' ')"
    return ((@($query.StdoutLines) | ForEach-Object { [string]$_ }) -join
        [Environment]::NewLine).Trim()
}

function Assert-WeatherIntegrationQuietReportBooleanContract {
    param(
        [Parameter(Mandatory = $true)][object]$Report,
        [switch]$RequireAttemptAuthority
    )

    $names = @(
        "ok", "capture_recovery_proved",
        "execution_tape_recovery_required",
        "execution_tape_readoption_expected",
        "execution_tape_rolled_but_inactive_skipped",
        "execution_tape_recovery_proved",
        "documentation_transaction_recorded",
        "publication_acknowledged"
    )
    if ($RequireAttemptAuthority) { $names += "authoritative_attempt_report" }
    foreach ($name in $names) {
        $property = $Report.PSObject.Properties[$name]
        if ($null -eq $property -or $property.Value -isnot [bool]) {
            throw "Quiet merge report property must be a JSON boolean: $name"
        }
    }
}

function Get-WeatherIntegrationTextSha256 {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return (([BitConverter]::ToString($sha.ComputeHash(
            [Text.Encoding]::UTF8.GetBytes($Text)
        ))) -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Get-WeatherIntegrationPublishedSourceFingerprint {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$GitExecutable
    )

    $pathspecs = @(
        "*.py", "*.pyi", "*.pyc", "*.pyo", "*.pyd", "*.so", "*.dll",
        "*.dylib", "sitecustomize.py", "pyproject.toml", "setup.cfg",
        "requirements*.txt"
    )
    $stage = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepositoryRoot `
        -Arguments (@("ls-files", "--stage", "-z", "--") + $pathspecs) `
        -ExpectedGitExecutable $GitExecutable `
        -Label "$Label tracked source stage inventory"
    $flags = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepositoryRoot `
        -Arguments (@("ls-files", "-v", "-z", "--") + $pathspecs) `
        -ExpectedGitExecutable $GitExecutable `
        -Label "$Label tracked source visibility flags"
    $stageRows = @(([string]$stage.Stdout).Split(
        [char]0, [StringSplitOptions]::RemoveEmptyEntries
    ))
    $flagRows = @(([string]$flags.Stdout).Split(
        [char]0, [StringSplitOptions]::RemoveEmptyEntries
    ))
    if ($stageRows.Count -le 0 -or $stageRows.Count -ne $flagRows.Count -or
        $stageRows.Count -gt 100000) {
        throw "$Label tracked source inventory is empty, mismatched, or unbounded."
    }
    $tags = @{}
    foreach ($row in $flagRows) {
        $match = [regex]::Match([string]$row, '^(?<tag>.?) (?<path>.+)$')
        if (-not $match.Success) { throw "$Label source visibility row is unreadable." }
        $tag = [string]$match.Groups["tag"].Value
        $path = [string]$match.Groups["path"].Value
        if ($tag -ceq "S" -or $tag -cmatch '^[a-z]$') {
            throw "$Label refuses source skip-worktree or assume-unchanged flag: $path"
        }
        if ($tags.ContainsKey($path)) {
            throw "$Label source visibility inventory repeats a path."
        }
        $tags[$path] = $tag
    }
    $aggregate = [Security.Cryptography.SHA256]::Create()
    $totalBytes = [int64]0
    try {
        foreach ($row in $stageRows) {
            $match = [regex]::Match(
                [string]$row,
                '^(?<mode>[0-7]{6}) (?<blob>[0-9a-f]{40,64}) 0\t(?<path>.+)$'
            )
            if (-not $match.Success) {
                throw "$Label source stage inventory has a non-stage-zero row."
            }
            $path = [string]$match.Groups["path"].Value
            if (-not $tags.ContainsKey($path) -or [IO.Path]::IsPathRooted($path) -or
                @($path.Replace("\", "/").Split('/') | Where-Object {
                    $_ -in @("", ".", "..")
                }).Count -ne 0) {
                throw "$Label source inventory contains an unsafe or unmatched path."
            }
            $absolute = [IO.Path]::GetFullPath((Join-Path $RepositoryRoot $path))
            Assert-WeatherIntegrationRegularPathAncestry `
                -Path $absolute -Phase "$Label tracked source file"
            $item = Get-Item -LiteralPath $absolute -Force -ErrorAction Stop
            if ($item.PSIsContainer -or
                ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                [int64]$item.Length -gt 67108864) {
                throw "$Label source file is non-regular or exceeds 64 MiB: $path"
            }
            $stream = $null
            $fileSha = [Security.Cryptography.SHA256]::Create()
            try {
                $stream = [IO.File]::Open(
                    $absolute, [IO.FileMode]::Open, [IO.FileAccess]::Read,
                    [IO.FileShare]::Read
                )
                $workingSha = ([BitConverter]::ToString(
                    $fileSha.ComputeHash($stream)
                ) -replace '-', '').ToLowerInvariant()
                $totalBytes += [int64]$stream.Length
                if ($totalBytes -gt 134217728) {
                    throw "$Label tracked source bytes exceed the 128 MiB bound."
                }
                $line = (
                    "$path`t$([string]$match.Groups['mode'].Value)" +
                    "`t$([string]$match.Groups['blob'].Value)" +
                    "`t$([string]$tags[$path])`t$([int64]$stream.Length)" +
                    "`t$workingSha`n"
                )
                [byte[]]$bytes = [Text.Encoding]::UTF8.GetBytes($line)
                [void]$aggregate.TransformBlock(
                    $bytes, 0, $bytes.Length, $bytes, 0
                )
            }
            finally {
                if ($null -ne $stream) { $stream.Dispose() }
                $fileSha.Dispose()
            }
        }
        [void]$aggregate.TransformFinalBlock([byte[]]@(), 0, 0)
        $sha256 = ([BitConverter]::ToString($aggregate.Hash) `
            -replace '-', '').ToLowerInvariant()
    }
    finally { $aggregate.Dispose() }
    $closingStage = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepositoryRoot `
        -Arguments (@("ls-files", "--stage", "-z", "--") + $pathspecs) `
        -ExpectedGitExecutable $GitExecutable `
        -Label "$Label closing tracked source stage inventory"
    $closingFlags = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepositoryRoot `
        -Arguments (@("ls-files", "-v", "-z", "--") + $pathspecs) `
        -ExpectedGitExecutable $GitExecutable `
        -Label "$Label closing tracked source visibility flags"
    if ([string]$closingStage.StdoutSha256 -cne [string]$stage.StdoutSha256 -or
        [string]$closingFlags.StdoutSha256 -cne [string]$flags.StdoutSha256) {
        throw "$Label source index identity changed during byte fingerprinting."
    }
    return [pscustomobject]@{
        Sha256 = $sha256
        FileCount = $stageRows.Count
        TotalBytes = $totalBytes
        IndexSha256 = [string]$stage.StdoutSha256
        FlagsSha256 = [string]$flags.StdoutSha256
    }
}

function Get-WeatherIntegrationPublishedProbeTuple {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedCommit,
        [Parameter(Mandatory = $true)][string]$ExpectedOriginUrl,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$GitExecutable
    )

    $expected = $ExpectedCommit.ToLowerInvariant()
    if ($expected -cnotmatch '^[0-9a-f]{40}$') {
        throw "$Label expected commit is invalid"
    }
    $sourceFingerprint = Get-WeatherIntegrationPublishedSourceFingerprint `
        -RepositoryRoot $RepositoryRoot -Label "$Label source boundary" `
        -GitExecutable $GitExecutable
    $statusQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepositoryRoot `
        -Arguments @(
            "status", "--porcelain=v2", "--branch", "--untracked-files=all"
        ) `
        -ExpectedGitExecutable $GitExecutable `
        -Label "$Label exact worktree status"
    $rows = @($statusQuery.StdoutLines | ForEach-Object { [string]$_ })
    $oidRows = @($rows | Where-Object { $_ -match '^# branch\.oid ' })
    $branchRows = @($rows | Where-Object { $_ -match '^# branch\.head ' })
    $bodyRows = @($rows | Where-Object { -not $_.StartsWith("# ") })
    if ($oidRows.Count -ne 1 -or $branchRows.Count -ne 1 -or
        $bodyRows.Count -ne 0) {
        throw "$Label requires one exact clean tracked/untracked production worktree"
    }
    $head = ($oidRows[0] -replace '^# branch\.oid\s+', '').Trim().ToLowerInvariant()
    $branch = ($branchRows[0] -replace '^# branch\.head\s+', '').Trim()
    $originMaster = (Invoke-WeatherIntegrationGitLine `
        -Root $RepositoryRoot `
        -Arguments @("rev-parse", "refs/remotes/origin/master^{commit}") `
        -ExpectedGitExecutable $GitExecutable
    ).ToLowerInvariant()
    Assert-WeatherIntegrationNoIgnoredImportArtifacts `
        -WorktreeRoot $RepositoryRoot -Phase "$Label final ignored namespace" |
        Out-Null
    $liveMaster = Get-WeatherIntegrationCanonicalRemoteTip `
        -Root $RepositoryRoot -ExpectedUrl $ExpectedOriginUrl `
        -RemoteRef "refs/heads/master" `
        -ExpectedGitExecutable $GitExecutable `
        -Label "$Label canonical live master"
    if ($head -cne $expected -or $branch -cne "master" -or
        $originMaster -cne $expected -or $liveMaster -cne $expected) {
        throw "$Label does not bind HEAD/master tracking/live master to $expected"
    }
    return [pscustomobject]@{
        Head = $head
        Branch = $branch
        OriginMaster = $originMaster
        LiveMaster = $liveMaster
        StatusSha256 = Get-WeatherIntegrationTextSha256 `
            -Text ([string]$statusQuery.Stdout)
        SourceSha256 = [string]$sourceFingerprint.Sha256
        SourceFileCount = [int]$sourceFingerprint.FileCount
        SourceTotalBytes = [int64]$sourceFingerprint.TotalBytes
        SourceIndexSha256 = [string]$sourceFingerprint.IndexSha256
        SourceFlagsSha256 = [string]$sourceFingerprint.FlagsSha256
    }
}

function Assert-WeatherIntegrationPublishedProbeTupleUnchanged {
    param(
        [Parameter(Mandatory = $true)][object]$Before,
        [Parameter(Mandatory = $true)][object]$After
    )

    foreach ($property in @(
        "Head", "Branch", "OriginMaster", "LiveMaster", "StatusSha256",
        "SourceSha256", "SourceFileCount", "SourceTotalBytes",
        "SourceIndexSha256", "SourceFlagsSha256"
    )) {
        if ([string]$Before.$property -cne [string]$After.$property) {
            throw "Post-publication capture probe changed authority field $property."
        }
    }
}

function Assert-WeatherIntegrationCaptureExecutionIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedCommit
    )

    $executionProperty = $Payload.PSObject.Properties["execution_identity"]
    $execution = if ($null -ne $executionProperty) {
        $executionProperty.Value
    }
    else { $null }
    $runtime = if ($null -ne $execution) { $execution.runtime_identity } else { $null }
    if ($null -eq $execution -or $execution -is [System.Array] -or
        $null -eq $runtime -or $runtime -is [System.Array]) {
        throw "Post-publication capture proof omitted its execution identity."
    }
    $expectedModule = [IO.Path]::GetFullPath((Join-Path $RepositoryRoot `
        "src\weather\operations\capture_recovery_check.py"))
    try {
        $actualModule = [IO.Path]::GetFullPath([string]$execution.module_path)
        $actualRoot = [IO.Path]::GetFullPath([string]$runtime.repo_root)
    }
    catch { throw "Post-publication capture execution identity has invalid paths." }
    $scopeFiles = @($runtime.source_scope_files | ForEach-Object { [string]$_ })
    $uniqueScopeFiles = @($scopeFiles | Sort-Object -Unique)
    if (-not $actualModule.Equals(
            $expectedModule, [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not $actualRoot.Equals(
            [IO.Path]::GetFullPath($RepositoryRoot),
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [string]$runtime.schema_version -cne "runtime_identity_v0.1" -or
        [string]$runtime.git_branch -cne "master" -or
        [string]$runtime.git_commit -cne
            $ExpectedCommit.ToLowerInvariant().Substring(0, 12) -or
        [string]$runtime.source_scope -cne "loaded_modules" -or
        [string]$runtime.source_fingerprint -cnotmatch '^[0-9a-f]{16}$' -or
        [int]$runtime.source_file_count -ne $scopeFiles.Count -or
        $scopeFiles.Count -le 0 -or
        $scopeFiles.Count -ne $uniqueScopeFiles.Count -or
        ($scopeFiles -join "`n") -cne ($uniqueScopeFiles -join "`n") -or
        $scopeFiles -cnotcontains
            "src/weather/operations/capture_recovery_check.py") {
        throw "Post-publication capture execution identity is not bound to the published source."
    }
    foreach ($relativePath in $scopeFiles) {
        if ([string]::IsNullOrWhiteSpace($relativePath) -or
            $relativePath.Contains("\") -or
            [IO.Path]::IsPathRooted($relativePath) -or
            @($relativePath.Split('/') | Where-Object { $_ -eq ".." }).Count -ne 0 -or
            $relativePath -cnotmatch
                '^(?:app\.py|sitecustomize\.py|(?:app|src|weather)/.+\.py)$') {
            throw "Post-publication capture loaded-source scope escapes canonical roots."
        }
    }
    $currentLoadedSource = Get-WeatherIntegrationPublishedLoadedSourceFingerprint `
        -RepositoryRoot $RepositoryRoot -RelativePaths $scopeFiles `
        -Label "post-publication capture execution identity"
    if ([string]$currentLoadedSource.Fingerprint -cne
            [string]$runtime.source_fingerprint -or
        [int]$currentLoadedSource.FileCount -ne [int]$runtime.source_file_count) {
        throw (
            "Post-publication capture loaded-source fingerprint does not " +
            "match the retained published bytes."
        )
    }
    return $currentLoadedSource
}

function Get-WeatherIntegrationPublishedLoadedSourceFingerprint {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string[]]$RelativePaths,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $sortedPaths = @($RelativePaths | Sort-Object -Unique)
    if ($sortedPaths.Count -le 0 -or $sortedPaths.Count -gt 4096 -or
        $sortedPaths.Count -ne $RelativePaths.Count) {
        throw "$Label scope is empty, duplicated, or exceeds 4096 files."
    }
    $aggregate = [Security.Cryptography.SHA256]::Create()
    $totalBytes = [int64]0
    try {
        foreach ($relativePath in $sortedPaths) {
            if ([string]::IsNullOrWhiteSpace($relativePath) -or
                $relativePath.Contains("\") -or
                [IO.Path]::IsPathRooted($relativePath) -or
                @($relativePath.Split('/') | Where-Object {
                    $_ -in @("", ".", "..")
                }).Count -ne 0 -or
                $relativePath -cnotmatch
                    '^(?:app\.py|sitecustomize\.py|(?:app|src|weather)/.+\.py)$') {
                throw "$Label scope escapes canonical Python source roots."
            }
            $absolute = [IO.Path]::GetFullPath(
                (Join-Path $RepositoryRoot ($relativePath -replace '/', '\'))
            )
            Assert-WeatherIntegrationRegularPathAncestry `
                -Path $absolute -Phase "$Label loaded-source file"
            $item = Get-Item -LiteralPath $absolute -Force -ErrorAction Stop
            if ($item.PSIsContainer -or
                ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                [int64]$item.Length -gt 67108864) {
                throw "$Label source file is non-regular or exceeds 64 MiB."
            }
            $stream = $null
            try {
                $stream = [IO.File]::Open(
                    $absolute, [IO.FileMode]::Open, [IO.FileAccess]::Read,
                    [IO.FileShare]::Read
                )
                [byte[]]$nameBytes = [Text.Encoding]::UTF8.GetBytes($relativePath)
                [void]$aggregate.TransformBlock(
                    $nameBytes, 0, $nameBytes.Length, $nameBytes, 0
                )
                [byte[]]$separator = @(0)
                [void]$aggregate.TransformBlock($separator, 0, 1, $separator, 0)
                [byte[]]$buffer = New-Object byte[] 65536
                while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    [void]$aggregate.TransformBlock($buffer, 0, $read, $buffer, 0)
                    $totalBytes += $read
                    if ($totalBytes -gt 134217728) {
                        throw "$Label bytes exceed the 128 MiB bound."
                    }
                }
                [void]$aggregate.TransformBlock($separator, 0, 1, $separator, 0)
            }
            finally {
                if ($null -ne $stream) { $stream.Dispose() }
            }
        }
        [void]$aggregate.TransformFinalBlock([byte[]]@(), 0, 0)
        $fingerprint = (([BitConverter]::ToString($aggregate.Hash)) `
            -replace '-', '').ToLowerInvariant().Substring(0, 16)
    }
    finally { $aggregate.Dispose() }
    return [pscustomobject]@{
        Fingerprint = $fingerprint
        FileCount = $sortedPaths.Count
        TotalBytes = $totalBytes
    }
}

function Invoke-WeatherIntegrationPostPublicationCaptureProbe {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExecutable,
        [Parameter(Mandatory = $true)][string]$ExpectedPythonSha256,
        [Parameter(Mandatory = $true)][string]$GitExecutable,
        [Parameter(Mandatory = $true)][string]$ExpectedGitSha256,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedCommit,
        [Parameter(Mandatory = $true)][string]$ExpectedOriginUrl
    )

    $blockedPythonControls = @(
        "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONHOME", "PYTHONPATH",
        "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONBREAKPOINT",
        "PYTHONOPTIMIZE", "PYTHONWARNINGS", "PYTHONINSPECT",
        "PYTHONSAFEPATH", "PYTHONCASEOK", "PYTHONEXECUTABLE",
        "PYTHONPLATLIBDIR", "PYTHONPYCACHEPREFIX",
        "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED", "PYTHONUTF8",
        "PYTHONIOENCODING", "PYTHONDEVMODE", "PYTHONMALLOC",
        "PYTHONPROFILEIMPORTTIME", "PYTHONTRACEMALLOC",
        "PYTHONFAULTHANDLER", "PYTHONCOERCECLOCALE",
        "PYTHONLEGACYWINDOWSSTDIO", "PYTHONLEGACYWINDOWSFSENCODING",
        "PYTHONWARNDEFAULTENCODING", "PYTHONINTMAXSTRDIGITS",
        "__PYVENV_LAUNCHER__", "COVERAGE_PROCESS_START"
    )
    $ambient = @($blockedPythonControls | Where-Object {
        $null -ne [Environment]::GetEnvironmentVariable(
            $_, [EnvironmentVariableTarget]::Process
        )
    })
    if ($ambient.Count -ne 0) {
        throw "Post-publication capture refuses ambient Python controls: $($ambient -join ', ')"
    }
    $cacheRoot = Join-Path ([IO.Path]::GetTempPath()) (
        "weather-attempt-capture-" + [guid]::NewGuid().ToString("N")
    )
    $primaryFailure = $null
    $gitIdentityStream = $null
    try {
        if (Test-Path -LiteralPath $cacheRoot) {
            throw "Post-publication unique Python cache root already exists."
        }
        [void][IO.Directory]::CreateDirectory($cacheRoot)
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $cacheRoot `
            -Phase "post-publication Python cache root"
        $cacheItem = Get-Item -LiteralPath $cacheRoot -Force -ErrorAction Stop
        if (-not $cacheItem.PSIsContainer -or
            ($cacheItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            @([IO.Directory]::EnumerateFileSystemEntries($cacheRoot)).Count -ne 0) {
            throw "Post-publication Python cache root is not one empty regular directory."
        }
        $resolvedGitExecutable = Get-WeatherIntegrationGitExecutablePath `
            -Phase "post-publication capture Git identity" `
            -ExpectedPath $GitExecutable
        $gitIdentityStream = [IO.File]::Open(
            $resolvedGitExecutable, [IO.FileMode]::Open,
            [IO.FileAccess]::Read, [IO.FileShare]::Read
        )
        $gitHash = [Security.Cryptography.SHA256]::Create()
        try {
            $actualGitSha256 = ([BitConverter]::ToString(
                $gitHash.ComputeHash($gitIdentityStream)
            ) -replace '-', '').ToLowerInvariant()
        }
        finally { $gitHash.Dispose() }
        $expectedGitSha256Lower = $ExpectedGitSha256.Trim().ToLowerInvariant()
        if ($expectedGitSha256Lower -cnotmatch '^[0-9a-f]{64}$' -or
            $actualGitSha256 -cne $expectedGitSha256Lower) {
            throw "Post-publication Git executable changed after suite qualification."
        }
        $before = Get-WeatherIntegrationPublishedProbeTuple `
            -RepositoryRoot $RepositoryRoot -ExpectedCommit $ExpectedCommit `
            -ExpectedOriginUrl $ExpectedOriginUrl -Label "capture probe before" `
            -GitExecutable $resolvedGitExecutable
        $environment = @{
            PYTHONPATH = (Join-Path $RepositoryRoot "src")
            PYTHONNOUSERSITE = "1"
            PYTHONSAFEPATH = "1"
            PYTHONPYCACHEPREFIX = $cacheRoot
            PYTHONDONTWRITEBYTECODE = "1"
            PYTHONHASHSEED = "0"
            PYTHONUTF8 = "1"
            PYTHONIOENCODING = "utf-8"
            GIT_NO_REPLACE_OBJECTS = "1"
            GIT_OPTIONAL_LOCKS = "0"
            GIT_CONFIG_NOSYSTEM = "1"
            GIT_CONFIG_SYSTEM = "NUL"
            GIT_CONFIG_GLOBAL = "NUL"
            GIT_CONFIG_COUNT = "0"
            GIT_ALLOW_PROTOCOL = "file"
            GIT_TERMINAL_PROMPT = "0"
            LC_ALL = "C"
            LANG = "C"
        }
        $result = Invoke-WeatherIntegrationBoundedProcess `
            -Executable $PythonExecutable `
            -ExpectedExecutableSha256 $ExpectedPythonSha256 `
            -Arguments @(
                "-P", "-B", "-m", "weather.operations.capture_recovery_check",
                "--repo-root", $RepositoryRoot, "--json"
            ) `
            -WorkingDirectory $RepositoryRoot `
            -TimeoutSeconds 60 `
            -Label "post-publication capture recovery proof" `
            -AllowedExitCodes @(0, 2) `
            -MaxOutputBytes 1048576 `
            -RemoveEnvironmentVariables @(
                @($blockedPythonControls) +
                @(Get-WeatherIntegrationBlockedGitEnvironmentNames) |
                    Sort-Object -Unique
            ) `
            -Environment $environment
        if (@([IO.Directory]::EnumerateFileSystemEntries($cacheRoot)).Count -ne 0) {
            throw "Post-publication Python child populated its forbidden cache root."
        }
        $after = Get-WeatherIntegrationPublishedProbeTuple `
            -RepositoryRoot $RepositoryRoot -ExpectedCommit $ExpectedCommit `
            -ExpectedOriginUrl $ExpectedOriginUrl -Label "capture probe after" `
            -GitExecutable $resolvedGitExecutable
        Assert-WeatherIntegrationPublishedProbeTupleUnchanged `
            -Before $before -After $after
        if ([string]::IsNullOrWhiteSpace([string]$result.Stdout) -or
            [string]$result.StdoutSha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "Post-publication capture returned no retained stdout binding."
        }
        try {
            $payload = [string]$result.Stdout | ConvertFrom-Json -ErrorAction Stop
        }
        catch { throw "Post-publication capture returned unreadable JSON." }
        $loadedSource = Assert-WeatherIntegrationCaptureExecutionIdentity `
            -Payload $payload -RepositoryRoot $RepositoryRoot `
            -ExpectedCommit $ExpectedCommit
        return [pscustomobject]@{
            ExitCode = [int]$result.ExitCode
            Payload = $payload
            ExecutableSha256 = [string]$result.ExecutableSha256
            GitExecutableSha256 = $actualGitSha256
            StdoutSha256 = [string]$result.StdoutSha256
            StderrSha256 = [string]$result.StderrSha256
            GitStatusSha256 = [string]$after.StatusSha256
            SourceSha256 = [string]$after.SourceSha256
            SourceFileCount = [int]$after.SourceFileCount
            SourceTotalBytes = [int64]$after.SourceTotalBytes
            SourceIndexSha256 = [string]$after.SourceIndexSha256
            SourceFlagsSha256 = [string]$after.SourceFlagsSha256
            LoadedSourceTotalBytes = [int64]$loadedSource.TotalBytes
        }
    }
    catch {
        $primaryFailure = $_
        throw
    }
    finally {
        $cleanupFailures = New-Object System.Collections.Generic.List[string]
        if ($null -ne $gitIdentityStream) {
            try { $gitIdentityStream.Dispose() }
            catch {
                $cleanupFailures.Add(
                    "retained Git executable: $($_.Exception.Message)"
                )
            }
        }
        try {
            if (Test-Path -LiteralPath $cacheRoot) {
                $cleanupItem = Get-Item -LiteralPath $cacheRoot -Force `
                    -ErrorAction Stop
                if (-not $cleanupItem.PSIsContainer -or
                    ($cleanupItem.Attributes -band
                        [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                    @([IO.Directory]::EnumerateFileSystemEntries(
                        $cacheRoot
                    )).Count -ne 0) {
                    throw "owned cache root changed identity or is nonempty"
                }
                Remove-Item -LiteralPath $cacheRoot -Force -ErrorAction Stop
                if (Test-Path -LiteralPath $cacheRoot) {
                    throw "owned cache-root removal was not proved"
                }
            }
        }
        catch { $cleanupFailures.Add($_.Exception.Message) }
        if ($cleanupFailures.Count -ne 0) {
            $cleanupFailure = $cleanupFailures -join " | "
            if ($null -ne $primaryFailure) {
                $primaryFailure.Exception.Data["weather_cleanup_failure"] =
                    $cleanupFailure
                Write-Warning $cleanupFailure -WarningAction Continue
            }
            else { throw "Post-publication capture cleanup failed: $cleanupFailure" }
        }
    }
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
    if ([datetime]$taskInfo.LastRunTime -lt
            (Get-WeatherIntegrationScheduleLocalNow).Date) {
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

    $receiptStarted = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$SuiteReceiptContract.Receipt.started_at_local) `
        -Label "suite receipt started_at_local"
    $taskLastRunInstant = ConvertTo-WeatherIntegrationLocalInstant `
        -Value ([datetime]$taskInfo.LastRunTime) -Label "suite task LastRunTime"
    if ([math]::Abs((
            $receiptStarted.UtcDateTime - $taskLastRunInstant.UtcDateTime
        ).TotalMinutes) -gt 5) {
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
    $suiteAt = if ([string]$manifest.schema -ceq
        $script:WeatherIntegrationAttemptManifestSchema) {
        [datetime](Assert-WeatherIntegrationScheduleEvidence `
            -Schedule $manifest.schedule `
            -Label "merge-wait manifest schedule").SuiteAtLocal
    }
    else {
        ConvertFrom-WeatherIntegrationLocalTimestamp `
            -Value ([string]$manifest.schedule.suite_at_local) `
            -Label "suite_at_local"
    }
    $deadline = $suiteAt.Date.AddMinutes(220)
    $waitStartedAt = Get-WeatherIntegrationScheduleLocalNow
    $waitMaximumSeconds = [math]::Max(
        0,
        [double](Get-WeatherIntegrationLocalElapsedSeconds `
            -StartLocal $waitStartedAt `
            -EndLocal $deadline `
            -StartLabel "merge wait start" `
            -EndLabel "03:40 merge reserve" `
            -TimeZone (Get-WeatherIntegrationScheduleTimeZone))
    )
    $waitRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()
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
        $passReceiptCompletedAt = [datetime]::MinValue
        if ($receiptExists) {
            $receiptStatus = [string](Read-WeatherIntegrationSharedJson -Path $receiptPath).status
            if ($receiptStatus -eq "PASS") {
                $validatedPassReceipt = Assert-WeatherIntegrationSuiteReceipt `
                    -AttemptContract $AttemptContract
                $passReceiptCompletedAt = (
                    $validatedPassReceipt.CompletedAtLocal
                ).LocalDateTime
            }
        }
        $now = Get-WeatherIntegrationScheduleLocalNow
        $decisionNow = if (
            $waitRuntimeStopwatch.Elapsed.TotalSeconds -ge $waitMaximumSeconds
        ) { $deadline } else { $now }
        $decision = Get-WeatherIntegrationSuiteWaitDecision `
            -TaskState ([string]$binding.Task.State) `
            -LastRunTime ([datetime]$binding.Info.LastRunTime) `
            -LastTaskResult ([int]$binding.Info.LastTaskResult) `
            -ReceiptExists ([bool]$receiptExists) `
            -ReceiptStatus $receiptStatus `
            -Now $decisionNow `
            -Deadline $deadline `
            -PassReceiptCompletedAt $passReceiptCompletedAt
        $passExitGraceProperty = $decision.PSObject.Properties["PassExitGrace"]
        if ($null -ne $passExitGraceProperty -and [bool]$passExitGraceProperty.Value -and
            $null -eq $script:suitePassExitGraceEvidence) {
            $script:suitePassExitGraceEvidence = [ordered]@{
                observed_at_local = $now.ToString("o")
                receipt_completed_at_local = ([datetime]$decision.GraceStartedAt).ToString("o")
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
            Assert-WeatherIntegrationSchedulerMutationAllowed `
                -CommandName "Stop-ScheduledTask" `
                -Phase "suite-task merge-deadline stop"
            Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop
            $stopDeadline = [datetimeoffset]::UtcNow.AddMinutes(2)
            $stopRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()
            do {
                Start-Sleep -Seconds 2
                $binding = Assert-WeatherIntegrationSuiteTaskBinding `
                    -AttemptContract $AttemptContract `
                    -SuiteScript $SuiteScript `
                    -PowerShellExecutable $PowerShellExecutable
            } while ([string]$binding.Task.State -notin @("Ready", "Disabled") -and
                [datetimeoffset]::UtcNow -lt $stopDeadline -and
                $stopRuntimeStopwatch.Elapsed.TotalSeconds -lt 120)
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
    if ($null -eq $taskInfo -or [datetime]$taskInfo.LastRunTime -lt
            (Get-WeatherIntegrationScheduleLocalNow).Date) {
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
        [Parameter(Mandatory = $true)][string]$ExpectedOriginUrl,
        [Parameter(Mandatory = $true)][string]$AttemptReportPath,
        [Parameter(Mandatory = $true)][string]$ExpectedQuietMergeSha256,
        [hashtable]$ExpectedDependencySha256 = @{}
    )

    $resolvedQuietMergeScript = Resolve-WeatherIntegrationPath -Path $QuietMergeScript
    if (-not (Test-Path -LiteralPath $resolvedQuietMergeScript -PathType Leaf)) {
        throw "Quiet merge child script is missing: $resolvedQuietMergeScript"
    }
    $tokens = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $resolvedQuietMergeScript,
        "-Branch", $Branch,
        "-ExpectedTip", $ExpectedTip,
        "-ExpectedBaseline", $ExpectedBaseline,
        "-ExpectedOriginUrl", $ExpectedOriginUrl,
        "-RepoRoot", $RepoRoot,
        "-AttemptReportPath", $AttemptReportPath,
        "-ExpectedSelfSha256", $ExpectedQuietMergeSha256,
        "-ExpectedRemoteGitSha256", [string]$ExpectedDependencySha256["remote_git"],
        "-ExpectedJobContainmentSha256", [string]$ExpectedDependencySha256["job_containment"],
        "-ExpectedWorkloadAdmissionSha256", [string]$ExpectedDependencySha256["workload_admission"],
        "-ExpectedQuietMergePreflightSha256", [string]$ExpectedDependencySha256["quiet_merge_preflight"],
        "-ExpectedRollVerdictSha256", [string]$ExpectedDependencySha256["roll_verdict"],
        "-ExpectedGitExecutableSha256", [string]$ExpectedDependencySha256["git_executable"],
        "-ExpectedGitLfsExecutableSha256", [string]$ExpectedDependencySha256["git_lfs_executable"],
        "-ExpectedPythonExecutableSha256", [string]$ExpectedDependencySha256["python_executable"],
        "-RequireLiveOrigin",
        "-SettleSeconds", [string]$SettleSeconds
    )
    $argumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
    $job = $null
    $process = $null
    $scriptStream = $null
    $powerShellStream = $null
    $primaryFailure = $null
    $observedChildExitCode = $null
    try {
        # Bind verification and execution to one file generation. FileShare.Read
        # permits powershell.exe -File to open the script while denying a
        # write/delete/rename swap until the complete Job tree has drained.
        $scriptStream = [IO.File]::Open(
            $resolvedQuietMergeScript,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        $scriptItem = Get-Item -LiteralPath $resolvedQuietMergeScript -Force
        if ($scriptItem.PSIsContainer -or
            ($scriptItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$scriptItem.FullName) `
                -Right $resolvedQuietMergeScript)) {
            throw "Quiet merge child script is not one stable regular file."
        }
        $scriptHash = [Security.Cryptography.SHA256]::Create()
        try {
            $actualQuietMergeSha256 = (
                [BitConverter]::ToString($scriptHash.ComputeHash($scriptStream)) -replace '-', ''
            ).ToLowerInvariant()
        }
        finally { $scriptHash.Dispose() }
        if ($actualQuietMergeSha256 -cne $ExpectedQuietMergeSha256.ToLowerInvariant()) {
            throw "Quiet merge child script changed after its immutable binding was frozen."
        }
        $expectedPowerShellSha256 = [string]$ExpectedDependencySha256[
            "powershell_executable"
        ]
        if ($expectedPowerShellSha256 -and
            $expectedPowerShellSha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "Expected PowerShell executable SHA256 is invalid."
        }
        $resolvedPowerShellExecutable = Resolve-WeatherIntegrationPath `
            -Path $PowerShellExecutable
        $powerShellStream = [IO.File]::Open(
            $resolvedPowerShellExecutable,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        $powerShellItem = Get-Item -LiteralPath $resolvedPowerShellExecutable `
            -Force -ErrorAction Stop
        if ($powerShellItem.PSIsContainer -or
            ($powerShellItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$powerShellItem.FullName) `
                -Right $resolvedPowerShellExecutable)) {
            throw "Quiet merge PowerShell executable is not one stable regular file."
        }
        $powerShellHash = [Security.Cryptography.SHA256]::Create()
        try {
            $actualPowerShellSha256 = (
                [BitConverter]::ToString(
                    $powerShellHash.ComputeHash($powerShellStream)
                ) -replace '-', ''
            ).ToLowerInvariant()
        }
        finally { $powerShellHash.Dispose() }
        if ($expectedPowerShellSha256 -and
            $actualPowerShellSha256 -cne $expectedPowerShellSha256) {
            throw "PowerShell executable changed after suite toolchain qualification."
        }
        $outerHardStop = (Get-WeatherIntegrationScheduleLocalNow).Date.AddHours(5)
        $outerStartLocal = Get-WeatherIntegrationScheduleLocalNow
        $outerMaximumSeconds = [double](
            Get-WeatherIntegrationLocalElapsedSeconds `
                -StartLocal $outerStartLocal `
                -EndLocal $outerHardStop `
                -StartLabel "quiet merge child start" `
                -EndLabel "quiet merge 05:00 containment boundary" `
                -TimeZone (Get-WeatherIntegrationScheduleTimeZone)
        )
        if ($outerMaximumSeconds -le 0) {
            throw "Quiet merge child has no time before the 05:00 containment boundary."
        }
        $outerRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()
        $job = New-WeatherKillOnCloseJob
        $process = Start-WeatherProcessInJob `
            -Job $job `
            -FilePath $resolvedPowerShellExecutable `
            -ArgumentString $argumentString `
            -WorkingDirectory $RepoRoot
        while (-not $process.HasExited) {
            if ((Get-WeatherIntegrationScheduleLocalNow) -ge $outerHardStop -or
                $outerRuntimeStopwatch.Elapsed.TotalSeconds -ge
                    $outerMaximumSeconds) {
                $job.TerminateAndWaitForEmpty(5000)
                $job = $null
                throw (
                    "Quiet merge child exceeded the 05:00 containment boundary; " +
                    "terminating its kill-on-close Job and observing an empty " +
                    "active-process count proved its child tree was terminated."
                )
            }
            Start-Sleep -Seconds 2
            $process.Refresh()
        }
        $process.WaitForExit()
        $observedChildExitCode = [int]$process.ExitCode
        # The wrapper exit alone is not a child-tree termination proof. Do not
        # accept its exit code until the Job reports zero assigned processes
        # and the checked Job-handle close succeeds.
        $job.TerminateAndWaitForEmpty(5000)
        $job = $null
        return [int]$observedChildExitCode
    }
    catch {
        $failure = $_
        if ($null -ne $observedChildExitCode -and
            [int]$observedChildExitCode -ne 0) {
            $postExitFailure = $failure
            $combinedException = [InvalidOperationException]::new(
                (
                    "Quiet merge child exited with code $observedChildExitCode; " +
                    "post-exit containment also failed: " +
                    $postExitFailure.Exception.Message
                ),
                $postExitFailure.Exception
            )
            $combinedException.Data["weather_observed_child_exit_code"] =
                [int]$observedChildExitCode
            $combinedException.Data["weather_post_exit_failure"] =
                $postExitFailure.Exception.Message
            $failure = [Management.Automation.ErrorRecord]::new(
                $combinedException,
                "WeatherQuietMergeChildPostExitFailure",
                [Management.Automation.ErrorCategory]::OperationStopped,
                $resolvedQuietMergeScript
            )
        }
        if ($job) {
            try {
                $job.TerminateAndWaitForEmpty(5000)
                $job = $null
            }
            catch {
                $drainMessage = (
                    "Quiet merge child Job drain after primary failure also failed: " +
                    $_.Exception.Message
                )
                $failure.Exception.Data["weather_drain_failure"] = $drainMessage
                Write-Warning $drainMessage -WarningAction Continue
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
            catch { $cleanupFailures.Add("process wrapper: $($_.Exception.Message)") }
        }
        if ($scriptStream) {
            try { $scriptStream.Dispose() }
            catch { $cleanupFailures.Add("verified quiet-merge script handle: $($_.Exception.Message)") }
        }
        if ($powerShellStream) {
            try { $powerShellStream.Dispose() }
            catch { $cleanupFailures.Add("verified PowerShell executable handle: $($_.Exception.Message)") }
        }
        if ($cleanupFailures.Count -ne 0) {
            $cleanupMessage = "Quiet merge child cleanup failed: $($cleanupFailures -join ' | ')"
            if ($null -ne $primaryFailure) {
                $primaryFailure.Exception.Data["weather_cleanup_failure"] = $cleanupMessage
                Write-Warning $cleanupMessage -WarningAction Continue
            }
            elseif ($null -ne $observedChildExitCode -and
                [int]$observedChildExitCode -ne 0) {
                Write-Warning $cleanupMessage -WarningAction Continue
            }
            else { throw $cleanupMessage }
        }
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
    $markerSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $markerPath -MaximumBytes 2097152 -ContentType Json
    $markerSha256 = [string]$markerSnapshot.Sha256
    $markerRaw = [string]$markerSnapshot.Text
    $marker = $markerSnapshot.Payload
    $originUrlProperty = $attempt.baseline.PSObject.Properties["origin_url"]
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
        ($null -ne $originUrlProperty -and
            [string]$marker.origin_url -cne [string]$originUrlProperty.Value) -or
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
    $mergeHeadPathQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepositoryRoot `
        -Arguments @("rev-parse", "--git-path", "MERGE_HEAD") `
        -Label "integration merge active-marker MERGE_HEAD path query"
    $mergeHeadPathOutput = @($mergeHeadPathQuery.StdoutLines)
    if ($mergeHeadPathOutput.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$mergeHeadPathOutput[0])) {
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
    if ((Read-WeatherIntegrationEvidenceSnapshot -Path $markerPath -MaximumBytes 2097152 -ContentType Bytes).Sha256 -ne $markerSha256) {
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
$preparationAuthorization = Assert-WeatherIntegrationPreparationExecutionAuthorization `
    -AttemptContract $contract
$activationReceipt = Assert-WeatherIntegrationActivationReceipt `
    -AttemptContract $contract
$manifest = $contract.Manifest
$requiresAttemptReportAuthority = (
    [string]$manifest.schema -ceq $script:WeatherIntegrationAttemptManifestSchema
)
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

$startedAt = Get-WeatherIntegrationScheduleLocalNow
$startedAtEvidence = [datetimeoffset]::Now
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
$captureExecutableSha256 = $null
$captureGitExecutableSha256 = $null
$captureStdoutSha256 = $null
$captureStderrSha256 = $null
$captureGitStatusSha256 = $null
$captureSourceSha256 = $null
$captureSourceFileCount = $null
$captureSourceTotalBytes = $null
$captureSourceIndexSha256 = $null
$captureSourceFlagsSha256 = $null
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
    if ([string]$manifest.schema -ceq
            $script:WeatherIntegrationAttemptManifestSchema) {
        Assert-WeatherIntegrationSchedulerHostTimeZone | Out-Null
        $mergeSchedule = Assert-WeatherIntegrationScheduleEvidence `
            -Schedule $manifest.schedule -Label "merge manifest schedule"
        $mergeAt = [datetime]$mergeSchedule.MergeAtLocal
    }
    else {
        $mergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
            -Value ([string]$manifest.schedule.merge_at_local) `
            -Label "merge_at_local"
    }
    if ($startedAt.Date -ne $mergeAt.Date) {
        throw "Integration-attempt merge may run only on its immutable scheduled local date."
    }
    $localMinute = ($startedAt.Hour * 60) + $startedAt.Minute
    if ($localMinute -lt 60 -or $localMinute -ge 240) {
        throw "Integration-attempt merge must start inside the 01:00-04:00 quiet window."
    }

    Assert-WeatherIntegrationMergeTask `
        -AttemptContract $contract `
        -MergeScript $PSCommandPath `
        -PowerShellExecutable $powerShellExecutable

    Assert-WeatherIntegrationLiveOriginBaseline `
        -AttemptContract $contract -Phase "merge wait" `
        -RefreshTrackingMaster | Out-Null
    Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase "merge wait" | Out-Null
    Wait-WeatherIntegrationSuiteTerminal `
        -AttemptContract $contract `
        -SuiteScript $suiteScript `
        -PowerShellExecutable $powerShellExecutable
    Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract
    Assert-WeatherIntegrationLiveOriginBaseline `
        -AttemptContract $contract -Phase "guarded merge" `
        -RefreshTrackingMaster | Out-Null
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
    $quietDependencySha256 = @{}
    foreach ($dependencyName in @(
        "remote_git", "job_containment", "workload_admission",
        "quiet_merge_preflight", "roll_verdict"
    )) {
        $dependencyProperty = $manifest.orchestration.PSObject.Properties[
            $dependencyName
        ]
        if ($null -ne $dependencyProperty -and
            $null -ne $dependencyProperty.Value) {
            $quietDependencySha256[$dependencyName] =
                [string]$dependencyProperty.Value.sha256
        }
    }
    $suiteResultsProperty =
        $suiteReceiptContract.Receipt.logs.full_suite.PSObject.Properties[
            "test_results"
        ]
    if ($null -ne $suiteResultsProperty -and
        $null -ne $suiteResultsProperty.Value) {
        $quietDependencySha256["git_executable"] =
            [string]$suiteResultsProperty.Value.toolchain_git_sha256
        $quietDependencySha256["git_lfs_executable"] =
            [string]$suiteResultsProperty.Value.toolchain_git_lfs_sha256
        $quietDependencySha256["powershell_executable"] =
            [string]$suiteResultsProperty.Value.toolchain_powershell_sha256
        $toolchainPostSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path ([string]$suiteResultsProperty.Value.toolchain_post_path) `
            -MaximumBytes 1048576 -ContentType Json
        if ([string]$toolchainPostSnapshot.Sha256 -cne
                [string]$suiteResultsProperty.Value.toolchain_sha256 -or
            [string]$toolchainPostSnapshot.Payload.schema_version -cne
                "integration_toolchain_fingerprint_v1" -or
            [string]$toolchainPostSnapshot.Payload.git.executable_sha256 -cne
                [string]$quietDependencySha256["git_executable"] -or
            [string]$toolchainPostSnapshot.Payload.git_lfs.executable_sha256 -cne
                [string]$quietDependencySha256["git_lfs_executable"] -or
            [string]$toolchainPostSnapshot.Payload.powershell.executable_sha256 -cne
                [string]$quietDependencySha256["powershell_executable"]) {
            throw "Qualified toolchain sidecar changed or is malformed before quiet merge."
        }
        $qualifiedGitPath = Resolve-WeatherIntegrationPath `
            -Path ([string]$toolchainPostSnapshot.Payload.git.executable)
        [void](Get-WeatherIntegrationGitExecutablePath `
            -Phase "qualified integration-merge Git executable" `
            -ExpectedPath $qualifiedGitPath)
        # This second retained snapshot is an intentional last-use stability
        # recheck of the qualification sidecar before its interpreter hash is
        # handed to the contained quiet child.
        $pythonEnvironmentPostSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path ([string]$suiteResultsProperty.Value.python_environment_post_path) `
            -MaximumBytes 16777216 -ContentType Json
        if ([string]$pythonEnvironmentPostSnapshot.Sha256 -cne
                [string]$suiteResultsProperty.Value.python_environment_sha256 -or
            [string]$pythonEnvironmentPostSnapshot.Payload.schema_version -cne
                "python_environment_fingerprint_v1" -or
            [string]$pythonEnvironmentPostSnapshot.Payload.executable_sha256 -cnotmatch
                '^[0-9a-f]{64}$') {
            throw "Qualified Python-environment sidecar changed or is malformed before quiet merge."
        }
        $qualifiedPythonPath = Resolve-WeatherIntegrationPath `
            -Path ([string]$pythonEnvironmentPostSnapshot.Payload.executable)
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left $qualifiedPythonPath -Right $python)) {
            throw "Qualified Python interpreter path is not the attempt repository interpreter."
        }
        $quietDependencySha256["python_executable"] =
            [string]$pythonEnvironmentPostSnapshot.Payload.executable_sha256
    }
    if ([string]$manifest.schema -ceq
            $script:WeatherIntegrationAttemptManifestSchema -and
        (@($quietDependencySha256.Keys).Count -ne 9 -or
         @($quietDependencySha256.Values | Where-Object {
            [string]$_ -cnotmatch '^[0-9a-f]{64}$'
         }).Count -ne 0)) {
        throw "Strict v2 quiet merge lacks one complete frozen dependency/toolchain hash set."
    }
    Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $contract | Out-Null
    $quietMergeExitCode = Invoke-WeatherQuietMergeChild `
        -QuietMergeScript $quietMergeScript `
        -PowerShellExecutable $powerShellExecutable `
        -RepoRoot $repoRoot `
        -Branch ([string]$manifest.branch_ref) `
        -ExpectedTip ([string]$manifest.expected_tip) `
        -ExpectedBaseline ([string]$manifest.baseline.master) `
        -ExpectedOriginUrl ([string]$manifest.baseline.origin_url) `
        -AttemptReportPath $attemptQuietReportPath `
        -ExpectedQuietMergeSha256 ([string]$manifest.orchestration.quiet_merge.sha256) `
        -ExpectedDependencySha256 $quietDependencySha256
    if ($quietMergeExitCode -ne 0) {
        throw "Guarded quiet merge failed with exit code $quietMergeExitCode."
    }
    if (-not (Test-Path -LiteralPath $quietReportPath -PathType Leaf)) {
        throw "Guarded quiet merge returned success without a report."
    }
    $quietReportSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $quietReportPath -MaximumBytes 2097152 -ContentType Json
    $quietReport = $quietReportSnapshot.Payload
    $quietReportSha256 = [string]$quietReportSnapshot.Sha256
    Assert-WeatherIntegrationQuietReportBooleanContract `
        -Report $quietReport `
        -RequireAttemptAuthority:$requiresAttemptReportAuthority
    $quietReportTimestamp = (
        ConvertFrom-WeatherIntegrationEvidenceTimestamp `
            -Value ([string]$quietReport.ts) `
            -Label "quiet merge report ts"
    )
    if ($quietReportTimestamp -lt $startedAtEvidence.AddSeconds(-5)) {
        throw "Quiet merge report predates this attempt."
    }
    if ([string]$quietReport.schema -ne "quiet_window_merge_report_v0.2" -or
        ($requiresAttemptReportAuthority -and
            ($quietReport.authoritative_attempt_report -ne $true -or
             [string]$quietReport.compatibility_outputs_authority -cne
                "DIAGNOSTIC_ONLY")) -or
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
        [string]$quietReport.origin_url -cne [string]$manifest.baseline.origin_url -or
        [string]$quietReport.baseline_commit -ne [string]$manifest.baseline.master -or
        [string]$quietReport.pre_merge_commit -notmatch '^[0-9a-f]{40}$' -or
        [string]$quietReport.resolved_branch_tip -ne [string]$manifest.expected_tip) {
        throw "Quiet merge report identity does not match this attempt."
    }
    if ([string]$quietReport.python_executable_sha256 -cne
            [string]$quietDependencySha256["python_executable"]) {
        throw "Quiet merge report used a different Python executable than the qualified suite."
    }
    $pythonStageProofs = @($quietReport.python_stage_proofs)
    $requiredPythonStages = @(
        [pscustomobject]@{
            Label = "pre-merge capture-recovery probe"
            Module = "src/weather/operations/capture_recovery_check.py"
            Head = [string]$quietReport.pre_merge_commit
            MergeHead = ""
        },
        [pscustomobject]@{
            Label = "staged-merge capture-recovery probe"
            Module = "src/weather/operations/capture_recovery_check.py"
            Head = [string]$quietReport.pre_merge_commit
            MergeHead = [string]$manifest.expected_tip
        },
        [pscustomobject]@{
            Label = "post-merge documentation-transaction begin"
            Module = "src/weather/operations/documentation_transaction.py"
            Head = [string]$quietReport.merge_commit
            MergeHead = ""
        },
        [pscustomobject]@{
            Label = "pre-publication capture-recovery probe"
            Module = "src/weather/operations/capture_recovery_check.py"
            Head = [string]$quietReport.merge_commit
            MergeHead = ""
        }
    )
    if ([bool]$quietReport.execution_tape_recovery_required) {
        $requiredPythonStages += @(
            [pscustomobject]@{
                Label = "pre-merge execution-tape status probe"
                Module = "src/weather/operations/execution_tape_supervisor.py"
                Head = [string]$quietReport.pre_merge_commit
                MergeHead = ""
            },
            [pscustomobject]@{
                Label = "staged-merge execution-tape status probe"
                Module = "src/weather/operations/execution_tape_supervisor.py"
                Head = [string]$quietReport.pre_merge_commit
                MergeHead = [string]$manifest.expected_tip
            },
            [pscustomobject]@{
                Label = "pre-publication execution-tape status probe"
                Module = "src/weather/operations/execution_tape_supervisor.py"
                Head = [string]$quietReport.merge_commit
                MergeHead = ""
            }
        )
    }
    foreach ($requiredPythonStage in $requiredPythonStages) {
        $matches = @($pythonStageProofs | Where-Object {
            [string]$_.label -ceq [string]$requiredPythonStage.Label
        })
        if ($matches.Count -ne 1) {
            throw "Quiet merge report lacks one exact Python proof: $($requiredPythonStage.Label)"
        }
        $proof = $matches[0]
        if ([string]$proof.module -cne [string]$requiredPythonStage.Module -or
            [int]$proof.exit_code -ne 0 -or
            [string]$proof.executable_sha256 -cne
                [string]$quietDependencySha256["python_executable"] -or
            [string]$proof.stdout_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            [string]$proof.stderr_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            [string]$proof.git_status_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            [string]$proof.tracked_content_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            [string]$proof.index_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            [string]$proof.index_flags_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            [string]$proof.lfs_identity_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            [int]$proof.tracked_file_count -le 0 -or
            [int64]$proof.tracked_total_bytes -le 0 -or
            [int]$proof.lfs_count -ne
                ([int]$proof.hydrated_lfs_count + [int]$proof.pointer_lfs_count) -or
            [string]$proof.source_fingerprint -cnotmatch '^[0-9a-f]{16}$' -or
            [int]$proof.source_file_count -le 0 -or
            [string]$proof.git_head -cne
                ([string]$requiredPythonStage.Head).ToLowerInvariant() -or
            [string]$proof.merge_head -cne
                ([string]$requiredPythonStage.MergeHead).ToLowerInvariant()) {
            throw "Quiet merge Python-stage proof is malformed: $($requiredPythonStage.Label)"
        }
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
        $documentationSnapshotRelative -cne $expectedDocumentationSnapshotRelative) {
        throw "Quiet merge report does not bind its immutable documentation transaction snapshot."
    }
    $documentationEvidenceSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $documentationSnapshotPath -MaximumBytes 2097152 -ContentType Json
    if ([string]$documentationEvidenceSnapshot.Sha256 -ne $documentationPendingSha256) {
        throw "Quiet merge report does not bind its immutable documentation transaction snapshot."
    }
    $documentationSnapshot = $documentationEvidenceSnapshot.Payload
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
    $quietReportSha256 = [string]$quietReportSnapshot.Sha256

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
    Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repoRoot `
        -Arguments @(
            "merge-base", "--is-ancestor",
            [string]$manifest.expected_tip, $productionHead
        ) `
        -Label "integration merge published source-ancestry proof" | Out-Null
    $sourceTipIntegrated = $true

    $captureProbeResult = Invoke-WeatherIntegrationPostPublicationCaptureProbe `
        -PythonExecutable $python `
        -ExpectedPythonSha256 ([string]$quietDependencySha256["python_executable"]) `
        -GitExecutable $qualifiedGitPath `
        -ExpectedGitSha256 ([string]$quietDependencySha256["git_executable"]) `
        -RepositoryRoot $repoRoot `
        -ExpectedCommit $productionHead `
        -ExpectedOriginUrl ([string]$manifest.baseline.origin_url)
    $captureExitCode = [int]$captureProbeResult.ExitCode
    $captureProof = $captureProbeResult.Payload
    $captureExecutableSha256 = [string]$captureProbeResult.ExecutableSha256
    $captureGitExecutableSha256 = [string]$captureProbeResult.GitExecutableSha256
    $captureStdoutSha256 = [string]$captureProbeResult.StdoutSha256
    $captureStderrSha256 = [string]$captureProbeResult.StderrSha256
    $captureGitStatusSha256 = [string]$captureProbeResult.GitStatusSha256
    $captureSourceSha256 = [string]$captureProbeResult.SourceSha256
    $captureSourceFileCount = [int]$captureProbeResult.SourceFileCount
    $captureSourceTotalBytes = [int64]$captureProbeResult.SourceTotalBytes
    $captureSourceIndexSha256 = [string]$captureProbeResult.SourceIndexSha256
    $captureSourceFlagsSha256 = [string]$captureProbeResult.SourceFlagsSha256
    $captureLoadedSourceTotalBytes = [int64]$captureProbeResult.LoadedSourceTotalBytes
    $captureRequiredProperties = @(
        "schema_version", "repo_root", "ok", "workers"
    )
    if ($null -eq $captureProof -or $captureProof -is [System.Array] -or
        @($captureRequiredProperties | Where-Object {
            $null -eq $captureProof.PSObject.Properties[$_]
        }).Count -ne 0 -or
        [string]$captureProof.schema_version -cne "capture_recovery_check_v1" -or
        $captureProof.ok -isnot [bool]) {
        throw "Post-publication capture recovery proof returned the wrong object shape."
    }
    try {
        $captureRepoRoot = [IO.Path]::GetFullPath([string]$captureProof.repo_root)
    }
    catch { throw "Post-publication capture recovery proof has an invalid repo_root." }
    if (-not $captureRepoRoot.Equals(
        [IO.Path]::GetFullPath($repoRoot),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Post-publication capture recovery proof is bound to another repository."
    }
    $captureWorkers = @($captureProof.workers)
    $expectedCaptureWorkers = @(
        "snapshot_tracker", "market_microstructure", "observation_trigger"
    )
    if ($captureWorkers.Count -ne 3 -or
        @($captureWorkers | Where-Object {
            $null -eq $_ -or
            $null -eq $_.PSObject.Properties["name"] -or
            $null -eq $_.PSObject.Properties["ok"] -or
            $null -eq $_.PSObject.Properties["reasons"] -or
            $_.ok -isnot [bool]
        }).Count -ne 0 -or
        (@($captureWorkers | ForEach-Object { [string]$_.name } | Sort-Object) -join "`n") -cne
            (@($expectedCaptureWorkers | Sort-Object) -join "`n")) {
        throw "Post-publication capture recovery proof has the wrong worker shape."
    }
    $unhealthyWorkers = @($captureWorkers | Where-Object { -not [bool]$_.ok })
    if ($captureExitCode -ne 0 -or -not [bool]$captureProof.ok -or
        $unhealthyWorkers.Count -ne 0) {
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
            $candidateReportSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $quietReportPath -MaximumBytes 2097152 -ContentType Json
            $candidateReport = $candidateReportSnapshot.Payload
            $candidateTimestamp = (
                ConvertFrom-WeatherIntegrationEvidenceTimestamp `
                    -Value ([string]$candidateReport.ts) `
                    -Label "candidate quiet merge report ts"
            )
            Assert-WeatherIntegrationQuietReportBooleanContract `
                -Report $candidateReport `
                -RequireAttemptAuthority:$requiresAttemptReportAuthority
            if ($candidateTimestamp -ge $startedAtEvidence.AddSeconds(-5) -and
                (-not $requiresAttemptReportAuthority -or
                    ($candidateReport.authoritative_attempt_report -eq $true -and
                     [string]$candidateReport.compatibility_outputs_authority -ceq
                        "DIAGNOSTIC_ONLY")) -and
                [string]$candidateReport.branch -eq [string]$manifest.branch_ref -and
                [string]$candidateReport.expected_tip -eq [string]$manifest.expected_tip -and
                [string]$candidateReport.origin_url -ceq [string]$manifest.baseline.origin_url -and
                [string]$candidateReport.expected_baseline -eq [string]$manifest.baseline.master) {
                $quietReport = $candidateReport
                $quietReportSha256 = [string]$candidateReportSnapshot.Sha256
            }
        }
        catch { }
    }
    if ($null -ne $quietReport -and
        [string]$quietReport.schema -eq "quiet_window_merge_report_v0.2" -and
        (-not $requiresAttemptReportAuthority -or
            ($quietReport.authoritative_attempt_report -eq $true -and
             [string]$quietReport.compatibility_outputs_authority -ceq
                "DIAGNOSTIC_ONLY")) -and
        [bool]$quietReport.ok -and
        [string]$quietReport.stage -eq "pushed" -and
        [bool]$quietReport.publication_acknowledged -and
        [bool]$quietReport.capture_recovery_proved -and
        (-not [bool]$quietReport.execution_tape_recovery_required -or
            [bool]$quietReport.execution_tape_recovery_proved) -and
        [string]$quietReport.branch -eq [string]$manifest.branch_ref -and
        [string]$quietReport.expected_tip -eq [string]$manifest.expected_tip -and
        [string]$quietReport.origin_url -ceq [string]$manifest.baseline.origin_url -and
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
                $ancestryQuery = Invoke-WeatherIntegrationCheckedLocalGit `
                    -Root $repoRoot `
                    -Arguments @(
                        "merge-base", "--is-ancestor",
                        [string]$manifest.expected_tip, $productionHead
                    ) `
                    -AllowedExitCodes @(0, 1) `
                    -Label "integration merge recovery source-ancestry probe"
                if ([int]$ancestryQuery.ExitCode -eq 0) {
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
        (-not $requiresAttemptReportAuthority -or
            ($quietReport.authoritative_attempt_report -eq $true -and
             [string]$quietReport.compatibility_outputs_authority -ceq
                "DIAGNOSTIC_ONLY")) -and
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
        origin_url = [string]$manifest.baseline.origin_url
        suite_receipt_path = [string]$manifest.evidence.suite_receipt
        suite_receipt_sha256 = $suiteReceiptSha256
        started_at_local = $startedAtEvidence.ToString("o")
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
        capture_execution = [ordered]@{
            executable_sha256 = $captureExecutableSha256
            git_executable_sha256 = $captureGitExecutableSha256
            stdout_sha256 = $captureStdoutSha256
            stderr_sha256 = $captureStderrSha256
            git_status_sha256 = $captureGitStatusSha256
            source_sha256 = $captureSourceSha256
            source_file_count = $captureSourceFileCount
            source_total_bytes = $captureSourceTotalBytes
            source_index_sha256 = $captureSourceIndexSha256
            source_flags_sha256 = $captureSourceFlagsSha256
            loaded_source_total_bytes = $captureLoadedSourceTotalBytes
        }
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
        Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $contract | Out-Null
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
