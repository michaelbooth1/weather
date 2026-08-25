# Re-arm the read-only public execution-tape producer only after an exact,
# successful guarded merge. Any failed post-start proof stops the exact managed
# worker through its supervisor and disables the recurring task again.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExpectedTip,
    [Parameter(Mandatory = $true)][string]$MergeTaskName,
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$SupervisorTaskName = "WeatherExecutionTapeSupervisor",
    [int]$StaleAfterSeconds = 180,
    [string]$AttemptManifestPath = "",
    [string]$ExpectedManifestSha256 = "",
    [string]$ExpectedMergeReceiptSha256 = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$canonicalOpsRoot = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "scripts\ops")
)
if (-not [IO.Path]::GetFullPath($PSScriptRoot).Equals(
        $canonicalOpsRoot, [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Execution-tape adoption must run from the canonical target repository ops directory."
}
$schedulerBoundaryScript = Join-Path $canonicalOpsRoot `
    "integration_attempt_remote_git.ps1"
if (-not (Test-Path -LiteralPath $schedulerBoundaryScript -PathType Leaf)) {
    throw "Scheduler mutation boundary helper is missing: $schedulerBoundaryScript"
}
$schedulerBoundaryPreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Stop"
    Remove-Item `
        -LiteralPath Function:\Assert-WeatherIntegrationSchedulerMutationAllowed `
        -Force -ErrorAction SilentlyContinue
    . $schedulerBoundaryScript
    $schedulerBoundaryCommand = Get-Command `
        Assert-WeatherIntegrationSchedulerMutationAllowed `
        -CommandType Function -ErrorAction Stop
}
catch {
    throw "Scheduler mutation boundary helper could not be loaded from its canonical file."
}
finally {
    $ErrorActionPreference = $schedulerBoundaryPreviousErrorActionPreference
}
if ([string]::IsNullOrWhiteSpace([string]$schedulerBoundaryCommand.ScriptBlock.File) -or
    -not [IO.Path]::GetFullPath(
        [string]$schedulerBoundaryCommand.ScriptBlock.File
    ).Equals(
        [IO.Path]::GetFullPath($schedulerBoundaryScript),
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not [string]::IsNullOrWhiteSpace([string]$schedulerBoundaryCommand.ModuleName) -or
    -not [string]::IsNullOrWhiteSpace([string]$schedulerBoundaryCommand.Source)) {
    throw "Scheduler mutation boundary helper did not load from its canonical file."
}
$attemptContractScript = Join-Path $canonicalOpsRoot `
    "integration_attempt_contract.ps1"
if (-not (Test-Path -LiteralPath $attemptContractScript -PathType Leaf)) {
    throw "Integration-attempt contract helper is missing from the target repository."
}
. $attemptContractScript
$ignoredBoundaryCommand = Get-Command `
    Assert-WeatherIntegrationNoIgnoredImportArtifacts `
    -CommandType Function -ErrorAction Stop
if ([string]::IsNullOrWhiteSpace([string]$ignoredBoundaryCommand.ScriptBlock.File) -or
    -not [IO.Path]::GetFullPath(
        [string]$ignoredBoundaryCommand.ScriptBlock.File
    ).Equals(
        $attemptContractScript, [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Ignored import/control boundary did not load from the canonical contract."
}
$preparationContractScript = Join-Path $canonicalOpsRoot `
    "integration_attempt_preparation_contract.ps1"
if (-not (Test-Path -LiteralPath $preparationContractScript -PathType Leaf)) {
    throw "Integration-attempt contained-child helper is missing from the target repository."
}
. $preparationContractScript
$containedChildCommand = Get-Command `
    Invoke-WeatherIntegrationContainedPowerShellChild `
    -CommandType Function -ErrorAction Stop
if ([string]::IsNullOrWhiteSpace([string]$containedChildCommand.ScriptBlock.File) -or
    -not [IO.Path]::GetFullPath(
        [string]$containedChildCommand.ScriptBlock.File
    ).Equals(
        $preparationContractScript, [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Contained PowerShell child helper did not load from its canonical file."
}
$ExpectedTip = $ExpectedTip.Trim().ToLowerInvariant()
$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$pythonw = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
$expectedArguments = "-m weather.operations.execution_tape_supervisor ensure --market all --stale-after-seconds $StaleAfterSeconds"
$enabledByThisRun = $false
$script:adoptionGitExecutable = $null
$script:adoptionPythonBinding = $null
$script:adoptionPythonwBinding = $null
$script:adoptionSupervisorBinding = $null
$script:adoptionExpectedCommit = $null
$script:adoptionRefusalInProgress = $false
$script:WeatherAdoptionPythonExecutions =
    [Collections.Generic.List[object]]::new()
$expectedQualifiedPythonSha256 = ""
$expectedQualifiedPythonwSha256 = ""
$attemptContract = $null
$attemptOriginIdentity = $null
$canonicalOriginUrl = ""
$attemptInputs = @(@($AttemptManifestPath, $ExpectedManifestSha256, $ExpectedMergeReceiptSha256) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
if ($attemptInputs.Count -ne 0 -and $attemptInputs.Count -ne 3) {
    throw "AttemptManifestPath and both expected SHA256 values must be supplied together."
}
$attemptMode = $attemptInputs.Count -eq 3

function Invoke-WeatherAdoptionGitLine {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $query = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root -Arguments $Arguments -Label $Label `
        -ExpectedGitExecutable $script:adoptionGitExecutable
    $rows = @($query.StdoutLines)
    if ($rows.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$rows[0])) {
        throw "$Label did not return exactly one nonempty line."
    }
    return ([string]$rows[0]).Trim()
}

function Get-WeatherAdoptionGitTuple {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Assert-WeatherIntegrationNoIgnoredImportArtifacts `
        -WorktreeRoot $Root -Phase "$Label ignored import/control boundary" |
        Out-Null
    $branch = Invoke-WeatherAdoptionGitLine `
        -Root $Root `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
        -Label "$Label branch"
    $refs = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root `
        -Arguments @(
            "rev-parse", "--end-of-options",
            "HEAD^{commit}", "master^{commit}", "origin/master^{commit}"
        ) `
        -Label "$Label refs" `
        -ExpectedGitExecutable $script:adoptionGitExecutable).StdoutLines)
    $status = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root -Arguments @("status", "--porcelain") `
        -Label "$Label status" `
        -ExpectedGitExecutable $script:adoptionGitExecutable).StdoutLines)
    $sourceStatus = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root `
        -Arguments @(
            "status", "--porcelain", "--untracked-files=all", "--",
            "app.py", "sitecustomize.py", "app", "scripts", "src",
            "tests", "tools", "weather"
        ) `
        -Label "$Label executable-source status" `
        -ExpectedGitExecutable $script:adoptionGitExecutable).StdoutLines)
    $flagText = [string](Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root -Arguments @("ls-files", "-v", "-z") `
        -Label "$Label index flags" `
        -ExpectedGitExecutable $script:adoptionGitExecutable).Stdout
    $flagRows = @(ConvertFrom-WeatherIntegrationNulRows `
        -Text $flagText -Label "$Label index flags")
    if ($branch -cne "master" -or $refs.Count -ne 3 -or
        $sourceStatus.Count -ne 0 -or $flagRows.Count -le 0 -or
        @($flagRows | Where-Object {
            [string]$_ -cnotmatch '^H .+$'
        }).Count -ne 0 -or
        @($refs | Where-Object {
            ([string]$_).Trim() -cnotmatch '^[0-9a-fA-F]{40}$'
        }).Count -ne 0) {
        throw (
            "$Label did not resolve one canonical production master tuple " +
            "with clean executable sources and ordinary index flags."
        )
    }
    $head = ([string]$refs[0]).Trim().ToLowerInvariant()
    $master = ([string]$refs[1]).Trim().ToLowerInvariant()
    $origin = ([string]$refs[2]).Trim().ToLowerInvariant()
    if ($head -cne $master -or $master -cne $origin) {
        throw "$Label requires HEAD == master == origin/master."
    }
    return [pscustomobject][ordered]@{
        Branch = $branch
        Head = $head
        Master = $master
        OriginMaster = $origin
        Status = ($status -join "`n")
    }
}

function Assert-WeatherAdoptionGitTupleUnchanged {
    param(
        [Parameter(Mandatory = $true)][object]$Before,
        [Parameter(Mandatory = $true)][object]$After,
        [Parameter(Mandatory = $true)][string]$Label
    )

    foreach ($name in @("Branch", "Head", "Master", "OriginMaster", "Status")) {
        if ([string]$Before.$name -cne [string]$After.$name) {
            throw "$Label production Git tuple changed at $name."
        }
    }
}

function Get-WeatherAdoptionPythonBinding {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$ExpectedSha256 = "",
        [string]$Label = "execution-tape adoption Python executable"
    )

    $resolved = [IO.Path]::GetFullPath($Path)
    Assert-WeatherIntegrationRegularPathAncestry `
        -Path $resolved -Phase $Label
    $item = Get-Item -LiteralPath $resolved -Force -ErrorAction Stop
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        [int64]$item.Length -le 0) {
        throw "$Label is not one regular nonempty file."
    }
    $stream = $null
    $hash = $null
    $retainStream = $false
    try {
        $stream = [IO.File]::Open(
            $resolved, [IO.FileMode]::Open, [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try {
            $hash = (([BitConverter]::ToString(
                $algorithm.ComputeHash($stream)
            )) -replace '-', '').ToLowerInvariant()
        }
        finally { $algorithm.Dispose() }
        $authority = "CURRENT_LEGACY_INTERPRETER"
        if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256)) {
            $expected = $ExpectedSha256.Trim().ToLowerInvariant()
            if ($expected -cnotmatch '^[0-9a-f]{64}$' -or $hash -cne $expected) {
                throw "$Label disagrees with qualification."
            }
            $authority = "IMMUTABLE_FULL_SUITE_ENVIRONMENT"
        }
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $resolved -Phase "$Label retained-handle recheck"
        $retainStream = $true
        return [pscustomobject][ordered]@{
            Path = $resolved
            Sha256 = $hash
            Authority = $authority
            Stream = $stream
        }
    }
    finally {
        if (-not $retainStream -and $null -ne $stream) { $stream.Dispose() }
    }
}

function Close-WeatherAdoptionExecutableBinding {
    param(
        [AllowNull()][object]$Binding,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($null -eq $Binding -or $null -eq $Binding.Stream) { return }
    try { $Binding.Stream.Dispose() }
    catch { throw "$Label retained executable handle cleanup failed." }
}

function Get-WeatherAdoptionLoadedSourceFingerprint {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string[]]$RelativePaths,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $sortedPaths = @($RelativePaths | Sort-Object -Unique)
    if ($sortedPaths.Count -le 0 -or $sortedPaths.Count -gt 4096 -or
        $sortedPaths.Count -ne $RelativePaths.Count) {
        throw "$Label source scope is empty, duplicated, or too large."
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
                throw "$Label source scope escapes canonical Python roots."
            }
            $absolute = [IO.Path]::GetFullPath(
                (Join-Path $RepositoryRoot ($relativePath -replace '/', '\'))
            )
            Assert-WeatherIntegrationRegularPathAncestry `
                -Path $absolute -Phase "$Label loaded source"
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
                        throw "$Label source bytes exceed 128 MiB."
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

function Assert-WeatherAdoptionPythonExecutionIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$ModuleRelativePath,
        [Parameter(Mandatory = $true)][string]$ExpectedCommit,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $executionProperty = $Payload.PSObject.Properties["execution_identity"]
    $execution = if ($null -ne $executionProperty) {
        $executionProperty.Value
    }
    else { $null }
    $runtime = if ($null -ne $execution) { $execution.runtime_identity } else { $null }
    if ($null -eq $execution -or $execution -is [System.Array] -or
        $null -eq $runtime -or $runtime -is [System.Array]) {
        throw "$Label omitted its execution identity."
    }
    $expectedModule = [IO.Path]::GetFullPath(
        (Join-Path $RepositoryRoot ($ModuleRelativePath -replace '/', '\'))
    )
    try {
        $actualModule = [IO.Path]::GetFullPath([string]$execution.module_path)
        $actualRoot = [IO.Path]::GetFullPath([string]$runtime.repo_root)
    }
    catch { throw "$Label execution identity contains invalid paths." }
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
        [string]$runtime.identity_source -cne "git_filesystem" -or
        [string]$runtime.git_branch -cne "master" -or
        [string]$runtime.git_commit -cne
            $ExpectedCommit.ToLowerInvariant().Substring(0, 12) -or
        [string]$runtime.source_scope -cne "loaded_modules" -or
        [string]$runtime.source_fingerprint -cnotmatch '^[0-9a-f]{16}$' -or
        [int]$runtime.source_file_count -ne $scopeFiles.Count -or
        $scopeFiles.Count -le 0 -or
        $scopeFiles.Count -ne $uniqueScopeFiles.Count -or
        ($scopeFiles -join "`n") -cne ($uniqueScopeFiles -join "`n") -or
        $scopeFiles -cnotcontains $ModuleRelativePath) {
        throw "$Label is not bound to the published Python source generation."
    }
    $current = Get-WeatherAdoptionLoadedSourceFingerprint `
        -RepositoryRoot $RepositoryRoot -RelativePaths $scopeFiles -Label $Label
    if ([string]$current.Fingerprint -cne [string]$runtime.source_fingerprint -or
        [int]$current.FileCount -ne [int]$runtime.source_file_count) {
        throw "$Label loaded-source fingerprint disagrees with retained production bytes."
    }
    return $current
}

function Invoke-WeatherAdoptionPythonJson {
    param(
        [Parameter(Mandatory = $true)][object]$PythonBinding,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$ModuleRelativePath,
        [Parameter(Mandatory = $true)][string]$ExpectedCommit,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1, 300)][int]$TimeoutSeconds = 60,
        [int[]]$AllowedExitCodes = @(0)
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
        "__PYVENV_LAUNCHER__", "COVERAGE_PROCESS_START",
        "WEATHER_INTEGRATION_TEST_OFFLINE"
    )
    $ambient = @($blockedPythonControls | Where-Object {
        $null -ne [Environment]::GetEnvironmentVariable(
            $_, [EnvironmentVariableTarget]::Process
        )
    })
    if ($ambient.Count -ne 0) {
        throw "$Label refuses ambient Python controls: $($ambient -join ', ')."
    }
    $secretEnvironmentNames = @(
        [Environment]::GetEnvironmentVariables(
            [EnvironmentVariableTarget]::Process
        ).Keys |
            ForEach-Object { [string]$_ } |
            Where-Object {
                $_ -in @(
                    "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_PROXY",
                    "PIP_TRUSTED_HOST", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL",
                    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                    "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR",
                    "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "PIP_CERT",
                    "SSH_AUTH_SOCK"
                ) -or
                $_ -match '^(?i:POLYMARKET_|POLYMM_|OPENAI_|ANTHROPIC_|AWS_|AZURE_|GOOGLE_|GCM_)' -or
                $_ -match '(?i)(?:^|_)(?:TOKEN|PASSWORD|PASSWD|SECRET|PRIVATE_KEY|API_KEY|ACCESS_KEY|CLIENT_SECRET|CREDENTIALS?|CONNECTION_STRING|URL|URI|COOKIE|DSN|AUTH|KEY|CERT)(?:$|_)'
            } |
            Sort-Object -Unique
    )
    $cacheRoot = Join-Path ([IO.Path]::GetTempPath()) (
        "weather-adoption-python-" + [guid]::NewGuid().ToString("N")
    )
    $primaryFailure = $null
    try {
        if (Test-Path -LiteralPath $cacheRoot) {
            throw "$Label unique Python cache root already exists."
        }
        [void][IO.Directory]::CreateDirectory($cacheRoot)
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $cacheRoot -Phase "$Label Python cache root"
        $cacheItem = Get-Item -LiteralPath $cacheRoot -Force -ErrorAction Stop
        if (-not $cacheItem.PSIsContainer -or
            ($cacheItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            @([IO.Directory]::EnumerateFileSystemEntries($cacheRoot)).Count -ne 0) {
            throw "$Label Python cache root is not one empty regular directory."
        }
        $before = Get-WeatherAdoptionGitTuple `
            -Root $RepositoryRoot -Label "$Label before"
        if ([string]$before.Head -cne $ExpectedCommit.ToLowerInvariant()) {
            throw "$Label production tip changed before the Python child."
        }
        $result = Invoke-WeatherIntegrationBoundedProcess `
            -Executable ([string]$PythonBinding.Path) `
            -ExpectedExecutableSha256 ([string]$PythonBinding.Sha256) `
            -Arguments (@("-P", "-B") + $Arguments) `
            -WorkingDirectory $RepositoryRoot `
            -TimeoutSeconds $TimeoutSeconds `
            -Label $Label `
            -AllowedExitCodes $AllowedExitCodes `
            -MaxOutputBytes 2097152 `
            -RemoveEnvironmentVariables @(
                @($blockedPythonControls) + @($secretEnvironmentNames) +
                @(Get-WeatherIntegrationBlockedGitEnvironmentNames) |
                    Sort-Object -Unique
            ) `
            -Environment @{
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
        if (@([IO.Directory]::EnumerateFileSystemEntries($cacheRoot)).Count -ne 0) {
            throw "$Label Python child populated its forbidden cache root."
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$result.Stderr) -or
            [string]::IsNullOrWhiteSpace([string]$result.Stdout) -or
            [string]$result.StdoutSha256 -cnotmatch '^[0-9a-f]{64}$' -or
            [string]$result.StderrSha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "$Label did not return one clean retained JSON stdout channel."
        }
        try {
            $payload = [string]$result.Stdout | ConvertFrom-Json -ErrorAction Stop
        }
        catch { throw "$Label returned unreadable JSON." }
        if ($null -eq $payload -or $payload -is [System.Array]) {
            throw "$Label JSON root is not one object."
        }
        $source = Assert-WeatherAdoptionPythonExecutionIdentity `
            -Payload $payload -RepositoryRoot $RepositoryRoot `
            -ModuleRelativePath $ModuleRelativePath `
            -ExpectedCommit $ExpectedCommit -Label $Label
        $after = Get-WeatherAdoptionGitTuple `
            -Root $RepositoryRoot -Label "$Label after"
        Assert-WeatherAdoptionGitTupleUnchanged `
            -Before $before -After $after -Label $Label
        $script:WeatherAdoptionPythonExecutions.Add(
            [pscustomobject][ordered]@{
                label = $Label
                module_path = $ModuleRelativePath
                python_path = [string]$PythonBinding.Path
                python_sha256 = [string]$PythonBinding.Sha256
                python_binding_authority = [string]$PythonBinding.Authority
                exit_code = [int]$result.ExitCode
                stdout_sha256 = [string]$result.StdoutSha256
                stderr_sha256 = [string]$result.StderrSha256
                source_fingerprint = [string]$source.Fingerprint
                source_file_count = [int]$source.FileCount
                source_total_bytes = [int64]$source.TotalBytes
                production_head = [string]$before.Head
            }
        )
        return [pscustomobject]@{
            Payload = $payload
            ExitCode = [int]$result.ExitCode
            StdoutSha256 = [string]$result.StdoutSha256
            StderrSha256 = [string]$result.StderrSha256
            Source = $source
        }
    }
    catch {
        $primaryFailure = $_
        throw
    }
    finally {
        try {
            $fullCacheRoot = [IO.Path]::GetFullPath($cacheRoot)
            $tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd(
                [IO.Path]::DirectorySeparatorChar,
                [IO.Path]::AltDirectorySeparatorChar
            )
            if (-not [IO.Path]::GetDirectoryName($fullCacheRoot).Equals(
                    $tempParent, [StringComparison]::OrdinalIgnoreCase
                ) -or
                [IO.Path]::GetFileName($fullCacheRoot) -cnotmatch
                    '^weather-adoption-python-[0-9a-f]{32}$') {
                throw "$Label refuses non-owned Python cache cleanup."
            }
            if (Test-Path -LiteralPath $fullCacheRoot) {
                $item = Get-Item -LiteralPath $fullCacheRoot -Force -ErrorAction Stop
                if (-not $item.PSIsContainer -or
                    ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                    @([IO.Directory]::EnumerateFileSystemEntries($fullCacheRoot)).Count -ne 0) {
                    throw "$Label refuses nonempty or reparse-point Python cache cleanup."
                }
                Remove-Item -LiteralPath $fullCacheRoot -Force -ErrorAction Stop
                if (Test-Path -LiteralPath $fullCacheRoot) {
                    throw "$Label Python cache cleanup was not proved."
                }
            }
        }
        catch {
            $cleanupMessage = "$Label cleanup failed: $($_.Exception.Message)"
            if ($null -ne $primaryFailure) {
                $primaryFailure.Exception.Data[
                    "weather_python_cleanup_failure"
                ] = $cleanupMessage
                Write-Warning $cleanupMessage -WarningAction Continue
            }
            else { throw $cleanupMessage }
        }
    }
}

function Invoke-WeatherAdoptionAttemptSuccessGate {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$ManifestSha256,
        [Parameter(Mandatory = $true)][string]$MergeReceiptSha256
    )

    Assert-WeatherIntegrationOrchestrationFiles `
        -AttemptContract $AttemptContract
    $manifest = $AttemptContract.Manifest
    $gateRecord = $manifest.orchestration.attempt_success_gate
    $gatePath = [IO.Path]::GetFullPath(
        (Join-Path $script:RepoRoot "scripts\ops\assert_integration_attempt_success.ps1")
    )
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$gateRecord.path) -Right $gatePath) -or
        [string]$gateRecord.sha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "Integration-attempt success gate lacks its canonical immutable binding."
    }

    # The gate script itself is held by the contained-child helper. Retain the
    # three scripts it dot-sources/uses for containment so their pathnames
    # cannot be replaced between the manifest check and child execution.
    $dependencyBindings = [Collections.Generic.List[object]]::new()
    $primaryFailure = $null
    try {
        foreach ($name in @("contract", "remote_git", "job_containment")) {
            $record = $manifest.orchestration.$name
            if ($name -ceq "remote_git" -and $null -eq $record -and
                [string]$manifest.schema -ceq
                    $script:WeatherIntegrationAttemptLegacyManifestSchema) {
                # Legacy manifests predate the remote_git hash field. Retain
                # the canonical current helper generation across the gate
                # child so the compatibility path remains contained without
                # inventing immutable authority that v1 never carried.
                $record = [pscustomobject]@{
                    path = Join-Path $script:RepoRoot `
                        "scripts\ops\integration_attempt_remote_git.ps1"
                    sha256 = ""
                }
            }
            if ($null -eq $record -or
                ($name -cne "remote_git" -and
                    [string]$record.sha256 -cnotmatch '^[0-9a-f]{64}$') -or
                ($name -ceq "remote_git" -and
                    -not [string]::IsNullOrWhiteSpace([string]$record.sha256) -and
                    [string]$record.sha256 -cnotmatch '^[0-9a-f]{64}$')) {
                throw "Integration-attempt success gate dependency binding is missing: $name"
            }
            $dependencyBindings.Add((Get-WeatherAdoptionPythonBinding `
                -Path ([string]$record.path) `
                -ExpectedSha256 ([string]$record.sha256) `
                -Label "execution-tape adoption gate dependency $name"))
        }
        $child = Invoke-WeatherIntegrationContainedPowerShellChild `
            -ScriptPath $gatePath `
            -ExpectedSha256 ([string]$gateRecord.sha256) `
            -Arguments @(
                "-ManifestPath", [string]$AttemptContract.ManifestPath,
                "-ExpectedManifestSha256", $ManifestSha256,
                "-ExpectedMergeReceiptSha256", $MergeReceiptSha256
            ) `
            -Label "execution-tape adoption immutable success gate" `
            -WorkingDirectory $script:RepoRoot `
            -OutputDirectory ([IO.Path]::GetTempPath()) `
            -HardStop ((Get-WeatherIntegrationScheduleLocalNow).AddMinutes(5))
        if ([int]$child.ExitCode -ne 0 -or
            -not [string]::IsNullOrEmpty([string]$child.Stderr) -or
            [string]::IsNullOrWhiteSpace([string]$child.Stdout) -or
            [string]$child.ScriptSha256 -cne [string]$gateRecord.sha256 -or
            [string]$child.Containment -cne
                "WINDOWS_JOB_KILL_ON_CLOSE_RETAINED_OUTPUT") {
            throw "Immutable integration-attempt success gate did not exit cleanly under containment."
        }
        try {
            $proof = [string]$child.Stdout | ConvertFrom-Json -ErrorAction Stop
        }
        catch { throw "Immutable integration-attempt success gate returned unreadable JSON." }
        if ($null -eq $proof -or $proof -is [System.Array]) {
            throw "Immutable integration-attempt success gate JSON root is not one object."
        }
        $required = @(
            "authorized", "attempt_id", "source_tip", "merge_task_name",
            "integration_tip", "python_executable", "python_executable_sha256",
            "pythonw_executable", "pythonw_executable_sha256",
            "python_binding_authority", "manifest_sha256",
            "merge_receipt_sha256", "quiet_merge_report_sha256",
            "canonical_origin_url", "canonical_origin_legacy",
            "capture_workers", "final_local_git", "final_live_master",
            "safety_authority", "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) | Sort-Object
        $actual = @($proof.PSObject.Properties.Name | Sort-Object)
        if (($actual -join "`n") -cne ($required -join "`n") -or
            $proof.authorized -isnot [bool] -or -not [bool]$proof.authorized -or
            $proof.canonical_origin_legacy -isnot [bool] -or
            $proof.credential_value_access_authorized -isnot [bool] -or
            [bool]$proof.credential_value_access_authorized -or
            $proof.live_exchange_mutation_authorized -isnot [bool] -or
            [bool]$proof.live_exchange_mutation_authorized -or
            [string]$proof.safety_authority -cne
                "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
            [string]$proof.manifest_sha256 -cne $ManifestSha256 -or
            [string]$proof.merge_receipt_sha256 -cne $MergeReceiptSha256 -or
            [string]$proof.source_tip -cne $script:ExpectedTip -or
            [string]$proof.merge_task_name -cne $script:MergeTaskName -or
            [string]$proof.integration_tip -cnotmatch '^[0-9a-f]{40}$' -or
            [int]$proof.capture_workers -ne 3) {
            throw "Immutable integration-attempt success gate returned a non-authoritative proof."
        }
        Assert-WeatherIntegrationRequiredProperties `
            -Object $proof.final_local_git `
            -Names @("branch", "head", "master", "origin_master") `
            -Label "execution-tape adoption gate final local Git"
        if ([string]$proof.final_local_git.branch -cne "master" -or
            [string]$proof.final_local_git.head -cne [string]$proof.integration_tip -or
            [string]$proof.final_local_git.master -cne [string]$proof.integration_tip -or
            [string]$proof.final_local_git.origin_master -cne
                [string]$proof.integration_tip -or
            [string]$proof.final_live_master -cne [string]$proof.integration_tip) {
            throw "Immutable integration-attempt success gate Git/live tuple is inconsistent."
        }
        Assert-WeatherIntegrationOrchestrationFiles `
            -AttemptContract $AttemptContract
        return [pscustomobject]@{
            Proof = $proof
            Execution = [pscustomobject][ordered]@{
                script_path = [string]$child.ScriptPath
                script_sha256 = [string]$child.ScriptSha256
                stdout_sha256 = [string]$child.StdoutSha256
                stderr_sha256 = [string]$child.StderrSha256
                exit_code = [int]$child.ExitCode
                containment = [string]$child.Containment
            }
        }
    }
    catch {
        $primaryFailure = $_
        throw
    }
    finally {
        $cleanupFailures = [Collections.Generic.List[string]]::new()
        foreach ($binding in @($dependencyBindings)) {
            try {
                Close-WeatherAdoptionExecutableBinding `
                    -Binding $binding `
                    -Label "execution-tape adoption gate dependency"
            }
            catch { $cleanupFailures.Add($_.Exception.Message) }
        }
        if ($cleanupFailures.Count -gt 0) {
            $message = "Success-gate retained dependency cleanup failed: $($cleanupFailures -join '; ')"
            if ($null -ne $primaryFailure) {
                $primaryFailure.Exception.Data[
                    "weather_gate_dependency_cleanup_failure"
                ] = $message
                Write-Warning $message -WarningAction Continue
            }
            else { throw $message }
        }
    }
}

function Get-WeatherAdoptionLiveMaster {
    param([Parameter(Mandatory = $true)][string]$Label)

    return Get-WeatherIntegrationCanonicalRemoteTip `
        -Root $script:RepoRoot `
        -ExpectedUrl $script:canonicalOriginUrl `
        -RemoteRef "refs/heads/master" `
        -Label $Label `
        -ExpectedGitExecutable $script:adoptionGitExecutable
}

function Get-WeatherAdoptionSupervisorTaskBinding {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateSet("Disabled", "Ready", "Running", "Any")]
        [string]$ExpectedState = "Any"
    )

    $matches = @(Get-ScheduledTask `
        -TaskName $script:SupervisorTaskName -TaskPath "\" -ErrorAction Stop)
    if ($matches.Count -ne 1) {
        throw "$Label must resolve exactly one root Scheduler task."
    }
    $task = $matches[0]
    $actions = @($task.Actions)
    $triggers = @($task.Triggers)
    $logonTriggers = @($triggers | Where-Object {
        [string]$_.CimClass.CimClassName -ceq "MSFT_TaskLogonTrigger"
    })
    $timeTriggers = @($triggers | Where-Object {
        [string]$_.CimClass.CimClassName -ceq "MSFT_TaskTimeTrigger"
    })
    $currentIdentity = Get-WeatherIntegrationCanonicalWindowsIdentity
    $principalSid = ConvertTo-WeatherIntegrationCanonicalPrincipalSid `
        -UserId ([string]$task.Principal.UserId) `
        -Label "$Label Scheduler principal"
    $logonSid = if ($logonTriggers.Count -eq 1) {
        ConvertTo-WeatherIntegrationCanonicalPrincipalSid `
            -UserId ([string]$logonTriggers[0].UserId) `
            -Label "$Label logon trigger principal"
    }
    else { "" }
    if ([string]$task.TaskName -cne $script:SupervisorTaskName -or
        [string]$task.TaskPath -cne "\" -or
        [string]$task.Description -cne
            "Keeps the read-only International Polymarket public execution-tape producer alive; no credential or order path." -or
        $actions.Count -ne 1 -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$actions[0].Execute) `
            -Right ([string]$script:adoptionPythonwBinding.Path)) -or
        [string]$actions[0].Arguments -cne $script:expectedArguments -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$actions[0].WorkingDirectory) `
            -Right $script:RepoRoot) -or
        [string]$task.Principal.LogonType -cne "S4U" -or
        [string]$task.Principal.RunLevel -cne "Limited" -or
        [string]$principalSid -cne [string]$currentIdentity.Sid -or
        [int]$task.Settings.Priority -ne 7 -or
        [string]$task.Settings.MultipleInstances -cne "IgnoreNew" -or
        [string]$task.Settings.ExecutionTimeLimit -cne "PT2M" -or
        -not [bool]$task.Settings.Hidden -or
        -not [bool]$task.Settings.StartWhenAvailable -or
        -not [bool]$task.Settings.WakeToRun -or
        [bool]$task.Settings.DisallowStartIfOnBatteries -or
        [bool]$task.Settings.StopIfGoingOnBatteries -or
        $triggers.Count -ne 2 -or
        $logonTriggers.Count -ne 1 -or $timeTriggers.Count -ne 1 -or
        [string]$logonSid -cne [string]$currentIdentity.Sid -or
        [string]$timeTriggers[0].Repetition.Interval -cne "PT1M" -or
        [string]$timeTriggers[0].Repetition.Duration -cne "P3650D" -or
        [bool]$timeTriggers[0].Repetition.StopAtDurationEnd -or
        [string]::IsNullOrWhiteSpace([string]$timeTriggers[0].StartBoundary) -or
        @($triggers | Where-Object {
            [string]$_.CimClass.CimClassName -cnotin @(
                "MSFT_TaskLogonTrigger", "MSFT_TaskTimeTrigger"
            )
        }).Count -ne 0 -or
        @($triggers | Where-Object { -not [bool]$_.Enabled }).Count -ne 0) {
        throw "$Label execution-tape supervisor binding is not exact."
    }
    if ($ExpectedState -cne "Any" -and
        [string]$task.State -cne $ExpectedState) {
        throw "$Label expected state $ExpectedState; observed $($task.State)."
    }
    $triggerRows = @($triggers | ForEach-Object {
        [ordered]@{
            type = [string]$_.CimClass.CimClassName
            user_id = [string]$_.UserId
            start_boundary = [string]$_.StartBoundary
            interval = [string]$_.Repetition.Interval
            duration = [string]$_.Repetition.Duration
            stop_at_duration_end = [bool]$_.Repetition.StopAtDurationEnd
            enabled = [bool]$_.Enabled
        }
    } | Sort-Object { [string]$_.type })
    $binding = [ordered]@{
        task_name = [string]$task.TaskName
        task_path = [string]$task.TaskPath
        execute = [IO.Path]::GetFullPath([string]$actions[0].Execute)
        execute_sha256 = [string]$script:adoptionPythonwBinding.Sha256
        arguments = [string]$actions[0].Arguments
        working_directory = [IO.Path]::GetFullPath(
            [string]$actions[0].WorkingDirectory
        )
        principal_sid = [string]$principalSid
        principal_logon_type = [string]$task.Principal.LogonType
        principal_run_level = [string]$task.Principal.RunLevel
        priority = [int]$task.Settings.Priority
        multiple_instances = [string]$task.Settings.MultipleInstances
        execution_time_limit = [string]$task.Settings.ExecutionTimeLimit
        hidden = [bool]$task.Settings.Hidden
        start_when_available = [bool]$task.Settings.StartWhenAvailable
        wake_to_run = [bool]$task.Settings.WakeToRun
        disallow_start_if_on_batteries =
            [bool]$task.Settings.DisallowStartIfOnBatteries
        stop_if_going_on_batteries = [bool]$task.Settings.StopIfGoingOnBatteries
        triggers = $triggerRows
    }
    $bindingJson = $binding | ConvertTo-Json -Depth 8 -Compress
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bindingSha256 = (([BitConverter]::ToString($sha.ComputeHash(
            [Text.Encoding]::UTF8.GetBytes($bindingJson)
        ))) -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
    return [pscustomobject]@{
        Task = $task
        State = [string]$task.State
        BindingSha256 = $bindingSha256
        Binding = [pscustomobject]$binding
    }
}

function Assert-WeatherAdoptionSupervisorBindingUnchanged {
    param(
        [Parameter(Mandatory = $true)][object]$Expected,
        [Parameter(Mandatory = $true)][object]$Actual,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ([string]$Expected.BindingSha256 -cne [string]$Actual.BindingSha256) {
        throw "$Label execution-tape supervisor task binding changed."
    }
}

function Refuse-Adoption {
    param([Parameter(Mandatory = $true)][string]$Reason)

    if ($script:adoptionRefusalInProgress) {
        [Console]::Error.WriteLine(
            "Execution-tape adoption encountered a recursive refusal; producer remains unauthorized."
        )
        exit 1
    }
    $script:adoptionRefusalInProgress = $true
    $cleanup = $null
    $cleanupFailures = [Collections.Generic.List[object]]::new()
    if ($script:enabledByThisRun) {
        # Remove future launch authority first, prove the exact task is held,
        # and only then stop the currently managed worker. A recurring task
        # must not be able to recreate the worker during rollback.
        try {
            Assert-WeatherIntegrationSchedulerMutationAllowed `
                -CommandName "Disable-ScheduledTask" `
                -Phase "execution-tape adoption rollback"
            Disable-ScheduledTask `
                -TaskName $script:SupervisorTaskName -TaskPath "\" `
                -ErrorAction Stop | Out-Null
            $disabledBinding = Get-WeatherAdoptionSupervisorTaskBinding `
                -Label "execution-tape adoption rollback disabled readback" `
                -ExpectedState "Disabled"
            if ($null -ne $script:adoptionSupervisorBinding) {
                Assert-WeatherAdoptionSupervisorBindingUnchanged `
                    -Expected $script:adoptionSupervisorBinding `
                    -Actual $disabledBinding `
                    -Label "execution-tape adoption rollback"
            }
        }
        catch {
            $cleanupFailures.Add([pscustomobject]@{
                phase = "disable_supervisor_task"
                error_type = $_.Exception.GetType().Name
            })
        }
        try {
            if ($null -eq $script:adoptionPythonBinding -or
                [string]::IsNullOrWhiteSpace($script:adoptionExpectedCommit)) {
                throw "Pinned adoption Python identity is unavailable."
            }
            $cleanupRun = Invoke-WeatherAdoptionPythonJson `
                -PythonBinding $script:adoptionPythonBinding `
                -RepositoryRoot $script:RepoRoot `
                -Arguments @(
                    "-m", "weather.operations.execution_tape_supervisor", "stop"
                ) `
                -ModuleRelativePath `
                    "src/weather/operations/execution_tape_supervisor.py" `
                -ExpectedCommit $script:adoptionExpectedCommit `
                -Label "execution-tape adoption rollback stop" `
                -TimeoutSeconds 60 -AllowedExitCodes @(0, 1)
            $stoppedProperty = $cleanupRun.Payload.PSObject.Properties["stopped"]
            $cleanup = [PSCustomObject]@{
                exit_code = [int]$cleanupRun.ExitCode
                stopped = if ($null -ne $stoppedProperty -and
                    $stoppedProperty.Value -is [bool]) {
                    [bool]$stoppedProperty.Value
                }
                else { $false }
                stdout_sha256 = [string]$cleanupRun.StdoutSha256
                stderr_sha256 = [string]$cleanupRun.StderrSha256
                source_fingerprint = [string]$cleanupRun.Source.Fingerprint
                disabled_before_stop = @($cleanupFailures | Where-Object {
                    [string]$_.phase -eq "disable_supervisor_task"
                }).Count -eq 0
            }
            if ([int]$cleanupRun.ExitCode -ne 0 -or
                $null -eq $stoppedProperty -or
                $stoppedProperty.Value -isnot [bool] -or
                -not [bool]$stoppedProperty.Value) {
                $cleanupFailures.Add([pscustomobject]@{
                    phase = "managed_stop"
                    error_type = "ManagedStopNotConfirmed"
                })
            }
        }
        catch {
            $cleanupFailures.Add([pscustomobject]@{
                phase = "managed_stop"
                error_type = $_.Exception.GetType().Name
            })
        }
        if ($null -eq $cleanup) {
            $cleanup = [pscustomobject]@{
                exit_code = $null
                stopped = $false
                stdout_sha256 = $null
                stderr_sha256 = $null
                source_fingerprint = $null
                disabled_before_stop = @($cleanupFailures | Where-Object {
                    [string]$_.phase -eq "disable_supervisor_task"
                }).Count -eq 0
            }
        }
    }
    foreach ($bindingRow in @(
        [pscustomobject]@{
            Binding = $script:adoptionPythonwBinding
            Label = "pythonw Scheduler launcher"
        },
        [pscustomobject]@{
            Binding = $script:adoptionPythonBinding
            Label = "Python interpreter"
        }
    )) {
        try {
            Close-WeatherAdoptionExecutableBinding `
                -Binding $bindingRow.Binding -Label $bindingRow.Label
        }
        catch {
            $cleanupFailures.Add([pscustomobject]@{
                phase = "retained_executable_handle_cleanup"
                error_type = $_.Exception.GetType().Name
            })
        }
    }
    if ($null -ne $cleanup) {
        $cleanup | Add-Member -NotePropertyName failures `
            -NotePropertyValue @($cleanupFailures) -Force
    }
    elseif ($cleanupFailures.Count -gt 0) {
        $cleanup = [pscustomobject]@{ failures = @($cleanupFailures) }
    }
    Write-Output ([PSCustomObject]@{
            adopted = $false
            reason = $Reason
            cleanup = $cleanup
        } | ConvertTo-Json -Depth 8)
    exit 1
}

# Convert unexpected parser, scheduler, filesystem, or process-inspection errors
# into the same fail-closed teardown. Report only the exception type; raw error
# text can contain host paths or command lines and is not needed for authority.
trap {
    Refuse-Adoption ("unexpected adoption failure: {0}" -f $_.Exception.GetType().Name)
}

if ($ExpectedTip -notmatch "^[0-9a-f]{40}$") {
    Refuse-Adoption "ExpectedTip must be a full 40-character hexadecimal commit SHA"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    Refuse-Adoption "repository virtual-environment interpreters are missing"
}

$script:adoptionGitExecutable = Get-WeatherIntegrationGitExecutablePath `
    -Phase "execution-tape adoption entry Git identity"
$attemptGateExecution = $null
$attemptProof = $null
if ($attemptMode) {
    try {
        $attemptContract = Assert-WeatherIntegrationAttemptManifest `
            -ManifestPath $AttemptManifestPath `
            -ExpectedSha256 $ExpectedManifestSha256
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$attemptContract.Manifest.repo_root) `
                -Right $RepoRoot) -or
            [string]$attemptContract.Manifest.expected_tip -cne $ExpectedTip -or
            [string]$attemptContract.Manifest.schedule.merge_task_name -cne
                $MergeTaskName) {
            throw "Selected integration-attempt manifest does not bind this adoption request."
        }
        $attemptOriginIdentity = Assert-WeatherIntegrationOriginIdentity `
            -AttemptContract $attemptContract `
            -Phase "execution-tape adoption origin identity"
        $mergeBinding = Assert-WeatherIntegrationAttemptTaskBinding `
            -AttemptContract $attemptContract -Role "merge" -IncludeTaskInfo
        $mergeTask = $mergeBinding.Task
        $mergeInfo = $mergeBinding.Info
        $gateResult = Invoke-WeatherAdoptionAttemptSuccessGate `
            -AttemptContract $attemptContract `
            -ManifestSha256 $ExpectedManifestSha256.ToLowerInvariant() `
            -MergeReceiptSha256 $ExpectedMergeReceiptSha256.ToLowerInvariant()
        $attemptProof = $gateResult.Proof
        $attemptGateExecution = $gateResult.Execution
    }
    catch {
        Refuse-Adoption "immutable integration-attempt success proof failed"
    }
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$attemptProof.python_executable) -Right $python) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$attemptProof.pythonw_executable) -Right $pythonw)) {
        Refuse-Adoption "integration-attempt proof does not bind both production Python launchers"
    }
    if ([string]$attemptContract.Manifest.schema -ceq
            $script:WeatherIntegrationAttemptManifestSchema) {
        if ([string]$attemptProof.python_binding_authority -cne
                "IMMUTABLE_FULL_SUITE_ENVIRONMENT") {
            Refuse-Adoption "current integration-attempt proof lacks qualified runtime authority"
        }
        $expectedQualifiedPythonSha256 =
            ([string]$attemptProof.python_executable_sha256).ToLowerInvariant()
        $expectedQualifiedPythonwSha256 =
            ([string]$attemptProof.pythonw_executable_sha256).ToLowerInvariant()
        if ($expectedQualifiedPythonSha256 -cnotmatch '^[0-9a-f]{64}$' -or
            $expectedQualifiedPythonwSha256 -cnotmatch '^[0-9a-f]{64}$') {
            Refuse-Adoption "integration-attempt proof omitted a qualified Python launcher hash"
        }
    }
    elseif ([string]$attemptProof.python_binding_authority -cne
            "CURRENT_LEGACY_INTERPRETER" -or
        -not [string]::IsNullOrWhiteSpace(
            [string]$attemptProof.python_executable_sha256
        ) -or
        -not [string]::IsNullOrWhiteSpace(
            [string]$attemptProof.pythonw_executable_sha256
        )) {
        Refuse-Adoption "integration-attempt proof has an unsupported Python binding authority"
    }
    if ([bool]$attemptOriginIdentity.Legacy -ne
            [bool]$attemptProof.canonical_origin_legacy -or
        (-not [bool]$attemptOriginIdentity.Legacy -and
            [string]$attemptProof.canonical_origin_url -cne
                [string]$attemptOriginIdentity.OriginUrl)) {
        Refuse-Adoption "integration-attempt proof origin identity disagrees with its manifest"
    }
}
else {
    $mergeMatches = @(Get-ScheduledTask `
        -TaskName $MergeTaskName -TaskPath "\" -ErrorAction SilentlyContinue)
    if ($mergeMatches.Count -ne 1) {
        Refuse-Adoption "guarded merge task is unavailable or ambiguous"
    }
    $mergeTask = $mergeMatches[0]
    $mergeInfo = Get-ScheduledTaskInfo `
        -TaskName $MergeTaskName -TaskPath "\" -ErrorAction SilentlyContinue
    if ($null -eq $mergeInfo) {
        Refuse-Adoption "guarded merge task info is unavailable"
    }
    $mergeActions = @($mergeTask.Actions)
    if ($mergeActions.Count -ne 1) {
        Refuse-Adoption "guarded merge task must have exactly one action"
    }
    if ([string]$mergeActions[0].Arguments -notlike "*suite_gated_quiet_merge.ps1*") {
        Refuse-Adoption "merge task is not bound to the suite-gated quiet-window wrapper"
    }
    $tipPattern = "(?i)(?:^|\s)-ExpectedTip\s+" + [regex]::Escape($ExpectedTip) + "(?:\s|$)"
    if ([string]$mergeActions[0].Arguments -notmatch $tipPattern) {
        Refuse-Adoption "merge task is not bound to ExpectedTip"
    }
}

if ([string]$mergeTask.State -eq "Running") {
    Refuse-Adoption "guarded merge task is still running"
}
if ([datetime]$mergeInfo.LastRunTime -lt (Get-Date).Date -or
    [int]$mergeInfo.LastTaskResult -ne 0) {
    Refuse-Adoption "guarded merge did not complete successfully on the current local day"
}

$script:adoptionPythonBinding = Get-WeatherAdoptionPythonBinding `
    -Path $python -ExpectedSha256 $expectedQualifiedPythonSha256 `
    -Label "execution-tape adoption Python interpreter"
$script:adoptionPythonwBinding = Get-WeatherAdoptionPythonBinding `
    -Path $pythonw -ExpectedSha256 $expectedQualifiedPythonwSha256 `
    -Label "execution-tape adoption pythonw Scheduler launcher"
if ($attemptMode -and -not [bool]$attemptOriginIdentity.Legacy) {
    $script:canonicalOriginUrl = Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root $RepoRoot `
        -ExpectedUrl ([string]$attemptOriginIdentity.OriginUrl) `
        -Phase "execution-tape adoption frozen origin" `
        -ExpectedGitExecutable $script:adoptionGitExecutable
}
else {
    $script:canonicalOriginUrl = Get-WeatherIntegrationCanonicalOriginUrl `
        -Root $RepoRoot `
        -ExpectedGitExecutable $script:adoptionGitExecutable
}
$initialGit = Get-WeatherAdoptionGitTuple `
    -Root $RepoRoot -Label "execution-tape adoption initial production Git"
$initialLiveMaster = Get-WeatherAdoptionLiveMaster `
    -Label "execution-tape adoption initial canonical live master"
$script:adoptionExpectedCommit = [string]$initialGit.Head
if ([string]$initialLiveMaster -cne [string]$initialGit.Master -or
    ($attemptMode -and
        ([string]$attemptProof.integration_tip -cne [string]$initialGit.Master -or
         [string]$attemptProof.final_local_git.head -cne [string]$initialGit.Head -or
         [string]$attemptProof.final_local_git.master -cne [string]$initialGit.Master -or
         [string]$attemptProof.final_local_git.origin_master -cne
            [string]$initialGit.OriginMaster -or
         [string]$attemptProof.final_live_master -cne [string]$initialLiveMaster))) {
    Refuse-Adoption "production Git and canonical live master disagree with the adoption authority"
}
$ancestry = Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $RepoRoot `
    -Arguments @("merge-base", "--is-ancestor", $ExpectedTip, "master") `
    -AllowedExitCodes @(0, 1) `
    -Label "execution-tape adoption source-tip ancestry" `
    -ExpectedGitExecutable $script:adoptionGitExecutable
if ([int]$ancestry.ExitCode -ne 0) {
    Refuse-Adoption "ExpectedTip is not in local master history"
}
$masterTip = [string]$initialGit.Master
$originTip = [string]$initialGit.OriginMaster

$captureRun = Invoke-WeatherAdoptionPythonJson `
    -PythonBinding $script:adoptionPythonBinding `
    -RepositoryRoot $RepoRoot `
    -Arguments @(
        "-m", "weather.operations.capture_recovery_check",
        "--repo-root", $RepoRoot, "--json"
    ) `
    -ModuleRelativePath "src/weather/operations/capture_recovery_check.py" `
    -ExpectedCommit $script:adoptionExpectedCommit `
    -Label "execution-tape adoption initial capture recovery" `
    -TimeoutSeconds 90
$capture = $captureRun.Payload
$captureOkProperty = $capture.PSObject.Properties["ok"]
if ($null -eq $captureOkProperty -or
    $captureOkProperty.Value -isnot [bool] -or
    -not [bool]$captureOkProperty.Value -or
    @($capture.workers).Count -ne 3 -or
    @($capture.workers | Where-Object {
        $_.PSObject.Properties["ok"].Value -isnot [bool] -or
        -not [bool]$_.ok
    }).Count -ne 0) {
    Refuse-Adoption "core capture is not healthy for all three workers"
}

try {
    $script:adoptionSupervisorBinding =
        Get-WeatherAdoptionSupervisorTaskBinding `
            -Label "execution-tape adoption initial supervisor" `
            -ExpectedState "Any"
}
catch {
    Refuse-Adoption "execution-tape supervisor binding is unavailable or inexact"
}
if ([string]$script:adoptionSupervisorBinding.State -cne "Disabled") {
    # The exact task identity is proven above. Treat an unexpected pre-enabled
    # task as cleanup-required too; refusing while leaving its producer able to
    # run would not restore the reviewed held state.
    $script:enabledByThisRun = $true
    Refuse-Adoption "execution-tape supervisor was not held Disabled before adoption"
}

Assert-WeatherIntegrationSchedulerMutationAllowed `
    -CommandName "Enable-ScheduledTask" -Phase "execution-tape adoption activation"
$script:enabledByThisRun = $true
Enable-ScheduledTask `
    -TaskName $SupervisorTaskName -TaskPath "\" -ErrorAction Stop | Out-Null
$enabledBinding = Get-WeatherAdoptionSupervisorTaskBinding `
    -Label "execution-tape adoption enabled supervisor" `
    -ExpectedState "Ready"
Assert-WeatherAdoptionSupervisorBindingUnchanged `
    -Expected $script:adoptionSupervisorBinding -Actual $enabledBinding `
    -Label "execution-tape adoption enabled readback"
$preStartBinding = Get-WeatherAdoptionSupervisorTaskBinding `
    -Label "execution-tape adoption immediate pre-start supervisor" `
    -ExpectedState "Ready"
Assert-WeatherAdoptionSupervisorBindingUnchanged `
    -Expected $script:adoptionSupervisorBinding -Actual $preStartBinding `
    -Label "execution-tape adoption pre-start re-attestation"
$before = Get-ScheduledTaskInfo `
    -TaskName $SupervisorTaskName -TaskPath "\" -ErrorAction Stop
Assert-WeatherIntegrationSchedulerMutationAllowed `
    -CommandName "Start-ScheduledTask" -Phase "execution-tape adoption first ensure"
Start-ScheduledTask `
    -TaskName $SupervisorTaskName -TaskPath "\" -ErrorAction Stop
$deadline = (Get-Date).AddSeconds(60)
$deadlineStopwatch = [Diagnostics.Stopwatch]::StartNew()
do {
    Start-Sleep -Milliseconds 500
    $supervisorMatches = @(Get-ScheduledTask `
        -TaskName $SupervisorTaskName -TaskPath "\" -ErrorAction Stop)
    if ($supervisorMatches.Count -ne 1) {
        Refuse-Adoption "execution-tape supervisor became unavailable or ambiguous"
    }
    $supervisorTask = $supervisorMatches[0]
    $after = Get-ScheduledTaskInfo `
        -TaskName $SupervisorTaskName -TaskPath "\" -ErrorAction Stop
    $completedThisRun = [datetime]$after.LastRunTime -gt [datetime]$before.LastRunTime
} while ((-not $completedThisRun -or [string]$supervisorTask.State -eq "Running") -and
    (Get-Date) -lt $deadline -and $deadlineStopwatch.Elapsed.TotalSeconds -lt 60)
$deadlineStopwatch.Stop()
if (-not $completedThisRun -or [string]$supervisorTask.State -eq "Running" -or
    [int]$after.LastTaskResult -ne 0) {
    Refuse-Adoption "first supervised ensure did not complete successfully"
}
$completedBinding = Get-WeatherAdoptionSupervisorTaskBinding `
    -Label "execution-tape adoption completed supervisor" `
    -ExpectedState "Ready"
Assert-WeatherAdoptionSupervisorBindingUnchanged `
    -Expected $script:adoptionSupervisorBinding -Actual $completedBinding `
    -Label "execution-tape adoption completed re-attestation"

$healthRun = Invoke-WeatherAdoptionPythonJson `
    -PythonBinding $script:adoptionPythonBinding `
    -RepositoryRoot $RepoRoot `
    -Arguments @(
        "-m", "weather.operations.execution_tape_supervisor", "status",
        "--stale-after-seconds", [string]$StaleAfterSeconds
    ) `
    -ModuleRelativePath "src/weather/operations/execution_tape_supervisor.py" `
    -ExpectedCommit $script:adoptionExpectedCommit `
    -Label "execution-tape adoption managed status" `
    -TimeoutSeconds 90
$healthPayload = $healthRun.Payload
$health = $healthPayload.health
$status = $healthPayload.status
$writerLockPath = Join-Path $RepoRoot "data\snapshots\.execution_tape_status.json.writer.lock"
$writerLockSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
    -Path $writerLockPath -MaximumBytes 1048576 -ContentType Json
$writerLock = $writerLockSnapshot.Payload
if ($null -eq $writerLock -or $writerLock -is [System.Array] -or
    $null -eq $writerLock.managed_process -or
    $writerLock.managed_process -is [System.Array]) {
    Refuse-Adoption "managed execution-tape writer lock is not one retained JSON object"
}
if (@("RUNNING", "DEGRADED") -notcontains [string]$health.state -or
    $health.pid_alive -ne $true -or
    $health.runtime_identity_matches_current -ne $true -or
    [string]$health.evidence_integrity -ne "PASS" -or
    [string]$status.state -ne "CONNECTED" -or
    [string]$status.market -ne "all" -or
    [string]$status.runner -ne "managed_execution_tape" -or
    $status.managed_process.verified_at_capture -ne $true -or
    [int]$status.pid -le 0 -or
    [int]$status.managed_process.pid -le 0 -or
    [int]$writerLock.pid -le 0 -or
    [int]$writerLock.managed_process.pid -le 0 -or
    [int]$status.pid -ne [int]$status.managed_process.pid -or
    [int]$status.pid -ne [int]$writerLock.pid -or
    [int]$status.pid -ne [int]$writerLock.managed_process.pid -or
    [string]$status.managed_process.creation_time_token -cne
        [string]$writerLock.managed_process.creation_time_token) {
    Refuse-Adoption "managed worker, status, lock, source, or evidence contract disagrees"
}

$captureAfterRun = Invoke-WeatherAdoptionPythonJson `
    -PythonBinding $script:adoptionPythonBinding `
    -RepositoryRoot $RepoRoot `
    -Arguments @(
        "-m", "weather.operations.capture_recovery_check",
        "--repo-root", $RepoRoot, "--json"
    ) `
    -ModuleRelativePath "src/weather/operations/capture_recovery_check.py" `
    -ExpectedCommit $script:adoptionExpectedCommit `
    -Label "execution-tape adoption final capture recovery" `
    -TimeoutSeconds 90
$captureAfter = $captureAfterRun.Payload
$captureAfterOkProperty = $captureAfter.PSObject.Properties["ok"]
if ($null -eq $captureAfterOkProperty -or
    $captureAfterOkProperty.Value -isnot [bool] -or
    -not [bool]$captureAfterOkProperty.Value -or
    @($captureAfter.workers).Count -ne 3 -or
    @($captureAfter.workers | Where-Object {
        $_.PSObject.Properties["ok"].Value -isnot [bool] -or
        -not [bool]$_.ok
    }).Count -ne 0) {
    Refuse-Adoption "core capture did not remain healthy after adoption"
}

$finalGit = Get-WeatherAdoptionGitTuple `
    -Root $RepoRoot -Label "execution-tape adoption final production Git"
$finalLiveMaster = Get-WeatherAdoptionLiveMaster `
    -Label "execution-tape adoption final canonical live master"
Assert-WeatherAdoptionGitTupleUnchanged `
    -Before $initialGit -After $finalGit `
    -Label "execution-tape adoption complete authority sandwich"
if ([string]$finalLiveMaster -cne [string]$initialLiveMaster -or
    [string]$finalLiveMaster -cne [string]$finalGit.Master) {
    Refuse-Adoption "canonical live master changed during execution-tape adoption"
}
$finalSupervisorBinding = Get-WeatherAdoptionSupervisorTaskBinding `
    -Label "execution-tape adoption final supervisor" `
    -ExpectedState "Ready"
Assert-WeatherAdoptionSupervisorBindingUnchanged `
    -Expected $script:adoptionSupervisorBinding -Actual $finalSupervisorBinding `
    -Label "execution-tape adoption final re-attestation"
if ($attemptMode) {
    $finalMergeBinding = Assert-WeatherIntegrationAttemptTaskBinding `
        -AttemptContract $attemptContract -Role "merge" -IncludeTaskInfo
    if ([string]$finalMergeBinding.Task.TaskName -cne $MergeTaskName -or
        [int]$finalMergeBinding.Info.LastTaskResult -ne 0 -or
        [datetime]$finalMergeBinding.Info.LastRunTime -ne
            [datetime]$mergeInfo.LastRunTime) {
        Refuse-Adoption "immutable integration-attempt merge task changed during adoption"
    }
}

$pythonBindingAuthority = [string]$script:adoptionPythonBinding.Authority
$pythonSha256 = [string]$script:adoptionPythonBinding.Sha256
$pythonwSha256 = [string]$script:adoptionPythonwBinding.Sha256
$supervisorBindingSha256 = [string]$script:adoptionSupervisorBinding.BindingSha256
$successJson = [PSCustomObject]@{
    adopted = $true
    expected_tip = $ExpectedTip
    master = $masterTip
    merge_task = $MergeTaskName
    supervisor_task = $SupervisorTaskName
    supervisor_result = ("0x{0:X}" -f [uint32]$after.LastTaskResult)
    state = $health.state
    capture_state = $status.state
    evidence_integrity = $health.evidence_integrity
    price_path_evidence_usable = $health.price_path_evidence_usable
    runtime_identity_matches_current = $health.runtime_identity_matches_current
    worker_pid = [int]$status.pid
    writer_lock_pid = [int]$writerLock.pid
    writer_lock_sha256 = [string]$writerLockSnapshot.Sha256
    core_capture_workers = @($capture.workers).Count
    canonical_live_master = [string]$finalLiveMaster
    canonical_origin_url = [string]$script:canonicalOriginUrl
    supervisor_binding_sha256 = $supervisorBindingSha256
    python_binding_authority = $pythonBindingAuthority
    python_sha256 = $pythonSha256
    pythonw_sha256 = $pythonwSha256
    attempt_success_gate = $attemptGateExecution
    python_executions = @($script:WeatherAdoptionPythonExecutions)
} | ConvertTo-Json -Depth 8
try {
    Close-WeatherAdoptionExecutableBinding `
        -Binding $script:adoptionPythonwBinding `
        -Label "execution-tape adoption pythonw Scheduler launcher"
    $script:adoptionPythonwBinding = $null
    Close-WeatherAdoptionExecutableBinding `
        -Binding $script:adoptionPythonBinding `
        -Label "execution-tape adoption Python interpreter"
    $script:adoptionPythonBinding = $null
}
catch {
    Refuse-Adoption "retained executable handles could not be closed after adoption proof"
}

Write-Output $successJson
exit 0
