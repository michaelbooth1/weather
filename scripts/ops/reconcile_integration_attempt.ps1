# Reviewed terminal reconciliation for an attempt that reached production but
# could not finish its original post-publication proof. This never upgrades the
# immutable merge receipt to PASS and never authorizes downstream work.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true, ParameterSetName = "MergeReceipt")]
    [ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedMergeReceiptSha256,
    [Parameter(Mandatory = $true, ParameterSetName = "QuietReport")]
    [ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedQuietMergeReportSha256,
    [Parameter(Mandatory = $true, ParameterSetName = "ActiveMarker")]
    [ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedActiveMarkerSha256,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [string]$Notes = "",
    [switch]$ResumePublication
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")
$script:WeatherReconciliationPythonExecutions =
    [Collections.Generic.List[object]]::new()

function Invoke-WeatherReconciliationGitLine {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $query = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root -Arguments $Arguments `
        -Label "integration reconciliation local Git query: $($Arguments -join ' ')"
    $output = @($query.StdoutLines)
    if ($output.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$output[0])) {
        throw "Reconciliation local Git query did not return exactly one line: $($Arguments -join ' ')"
    }
    return ([string]$output[0]).Trim().ToLowerInvariant()
}

function Get-WeatherReconciliationPythonBinding {
    param([Parameter(Mandatory = $true)][object]$AttemptContract)

    $attempt = $AttemptContract.Manifest
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$attempt.repo_root)
    $pythonPath = Resolve-WeatherIntegrationPath `
        -Path (Join-Path $repoRoot "venv\Scripts\python.exe")
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Repository virtual-environment interpreter is missing: $pythonPath"
    }
    Assert-WeatherIntegrationRegularPathAncestry `
        -Path $pythonPath -Phase "reconciliation Python executable"
    $pythonItem = Get-Item -LiteralPath $pythonPath -Force -ErrorAction Stop
    if ($pythonItem.PSIsContainer -or
        ($pythonItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Reconciliation Python executable must be one regular file."
    }
    $expectedSha256 = Get-WeatherIntegrationFileSha256 -Path $pythonPath
    $bindingAuthority = "CURRENT_LEGACY_INTERPRETER"
    if ([string]$attempt.schema -ceq
            $script:WeatherIntegrationAttemptManifestSchema) {
        $suiteContract = Assert-WeatherIntegrationSuiteReceipt `
            -AttemptContract $AttemptContract
        $testResultsProperty =
            $suiteContract.Receipt.logs.full_suite.PSObject.Properties[
                "test_results"
            ]
        if ($null -eq $testResultsProperty -or
            $null -eq $testResultsProperty.Value) {
            throw "Current reconciliation requires the qualified full-suite environment binding."
        }
        $testResults = $testResultsProperty.Value
        $environmentSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path ([string]$testResults.python_environment_post_path) `
            -MaximumBytes 16777216 -ContentType Json
        if ([string]$environmentSnapshot.Sha256 -cne
                [string]$testResults.python_environment_sha256 -or
            [string]$environmentSnapshot.Sha256 -cne
                [string]$attempt.suite.expected_python_environment_sha256 -or
            [string]$environmentSnapshot.Payload.schema_version -cne
                "python_environment_fingerprint_v1" -or
            [string]$environmentSnapshot.Payload.executable_sha256 -cnotmatch
                '^[0-9a-f]{64}$' -or
            [string]$environmentSnapshot.Payload.executable_sha256 -cne
                $expectedSha256 -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$environmentSnapshot.Payload.executable) `
                -Right $pythonPath)) {
            throw "Qualified Python environment cannot bind the reconciliation interpreter."
        }
        $expectedSha256 =
            [string]$environmentSnapshot.Payload.executable_sha256
        $bindingAuthority = "IMMUTABLE_FULL_SUITE_ENVIRONMENT"
    }
    return [pscustomobject][ordered]@{
        Path = $pythonPath
        Sha256 = $expectedSha256
        Authority = $bindingAuthority
    }
}

function Get-WeatherReconciliationPythonGitTuple {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Assert-WeatherIntegrationNoIgnoredImportArtifacts `
        -WorktreeRoot $RepositoryRoot -Phase "$Label ignored namespace" | Out-Null
    $branchBefore = Invoke-WeatherReconciliationGitLine `
        -Root $RepositoryRoot `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
    $refs = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepositoryRoot `
        -Arguments @(
            "rev-parse", "--end-of-options",
            "HEAD^{commit}", "master^{commit}", "origin/master^{commit}"
        ) `
        -Label "$Label exact Git refs").StdoutLines)
    $status = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepositoryRoot `
        -Arguments @("status", "--porcelain") `
        -Label "$Label exact Git status").StdoutLines)
    $branchAfter = Invoke-WeatherReconciliationGitLine `
        -Root $RepositoryRoot `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
    if ($branchBefore -cne "master" -or $branchAfter -cne $branchBefore -or
        $refs.Count -ne 3 -or
        @($refs | Where-Object {
            ([string]$_).Trim() -cnotmatch '^[0-9a-fA-F]{40}$'
        }).Count -ne 0 -or
        ([string]$refs[0]).Trim().ToLowerInvariant() -cne
            ([string]$refs[1]).Trim().ToLowerInvariant()) {
        throw "$Label requires one stable checked-out production master tuple."
    }
    return [pscustomobject][ordered]@{
        Branch = $branchAfter
        Head = ([string]$refs[0]).Trim().ToLowerInvariant()
        Master = ([string]$refs[1]).Trim().ToLowerInvariant()
        OriginMaster = ([string]$refs[2]).Trim().ToLowerInvariant()
        Status = ($status -join "`n")
    }
}

function Assert-WeatherReconciliationPythonGitTupleUnchanged {
    param(
        [Parameter(Mandatory = $true)][object]$Before,
        [Parameter(Mandatory = $true)][object]$After,
        [Parameter(Mandatory = $true)][string]$Label
    )

    foreach ($name in @("Branch", "Head", "Master", "OriginMaster", "Status")) {
        if ([string]$Before.$name -cne [string]$After.$name) {
            throw "$Label production Git tuple changed at $name across the Python child."
        }
    }
}

function Get-WeatherReconciliationLoadedSourceFingerprint {
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

function Assert-WeatherReconciliationPythonExecutionIdentity {
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
        throw "$Label execution identity is not bound to the published source."
    }
    $current = Get-WeatherReconciliationLoadedSourceFingerprint `
        -RepositoryRoot $RepositoryRoot -RelativePaths $scopeFiles -Label $Label
    if ([string]$current.Fingerprint -cne
            [string]$runtime.source_fingerprint -or
        [int]$current.FileCount -ne [int]$runtime.source_file_count) {
        throw "$Label loaded-source fingerprint does not match retained production bytes."
    }
    return $current
}

function Invoke-WeatherReconciliationPythonJson {
    param(
        [Parameter(Mandatory = $true)][object]$PythonBinding,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$ModuleRelativePath,
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
        throw "$Label refuses ambient Python controls: $($ambient -join ', ')"
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
        "weather-reconciliation-python-" + [guid]::NewGuid().ToString("N")
    )
    $primaryFailure = $null
    try {
        if (Test-Path -LiteralPath $cacheRoot) {
            throw "$Label unique Python cache root already exists."
        }
        [void][IO.Directory]::CreateDirectory($cacheRoot)
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $cacheRoot `
            -Phase "$Label Python cache root"
        $cacheItem = Get-Item -LiteralPath $cacheRoot -Force -ErrorAction Stop
        if (-not $cacheItem.PSIsContainer -or
            ($cacheItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            @([IO.Directory]::EnumerateFileSystemEntries($cacheRoot)).Count -ne 0) {
            throw "$Label Python cache root is not one empty regular directory."
        }
        $before = Get-WeatherReconciliationPythonGitTuple `
            -RepositoryRoot $RepositoryRoot -Label "$Label before"
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
        $loadedSource = Assert-WeatherReconciliationPythonExecutionIdentity `
            -Payload $payload -RepositoryRoot $RepositoryRoot `
            -ModuleRelativePath $ModuleRelativePath `
            -ExpectedCommit ([string]$before.Head) -Label $Label
        $after = Get-WeatherReconciliationPythonGitTuple `
            -RepositoryRoot $RepositoryRoot -Label "$Label after"
        Assert-WeatherReconciliationPythonGitTupleUnchanged `
            -Before $before -After $after -Label $Label
        $script:WeatherReconciliationPythonExecutions.Add(
            [pscustomobject][ordered]@{
                label = $Label
                module_path = $ModuleRelativePath
                python_path = [string]$PythonBinding.Path
                python_sha256 = [string]$PythonBinding.Sha256
                python_binding_authority = [string]$PythonBinding.Authority
                exit_code = [int]$result.ExitCode
                stdout_sha256 = [string]$result.StdoutSha256
                stderr_sha256 = [string]$result.StderrSha256
                source_fingerprint = [string]$loadedSource.Fingerprint
                source_file_count = [int]$loadedSource.FileCount
                source_total_bytes = [int64]$loadedSource.TotalBytes
                production_head = [string]$before.Head
            }
        )
        return [pscustomobject]@{
            Payload = $payload
            ExitCode = [int]$result.ExitCode
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
                    '^weather-reconciliation-python-[0-9a-f]{32}$') {
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

function Assert-WeatherReconciliationDocumentationProof {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][object]$PublicationRecord
    )

    $attempt = $AttemptContract.Manifest
    $pendingSha256 = ([string]$PublicationRecord.documentation_transaction_pending_sha256).ToLowerInvariant()
    $snapshotRelative = ([string]$PublicationRecord.documentation_transaction_snapshot_path).Replace('\', '/')
    $expectedRelative = "data/alerts/documentation_transactions/pending-$pendingSha256.json"
    if ($pendingSha256 -notmatch '^[0-9a-f]{64}$' -or $snapshotRelative -cne $expectedRelative) {
        throw "Documentation transaction snapshot identity is missing or non-canonical."
    }
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$attempt.repo_root)
    $snapshotPath = Join-Path $repoRoot ($snapshotRelative -replace '/', '\')
    $snapshotEvidence = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $snapshotPath -MaximumBytes 2097152 -ContentType Json
    if ([string]$snapshotEvidence.Sha256 -ne $pendingSha256) {
        throw "Documentation transaction snapshot hash does not match publication evidence."
    }
    $snapshot = $snapshotEvidence.Payload
    $matchingEntries = @($snapshot.integrations | Where-Object {
        ([string]$_.integration_tip).ToLowerInvariant() -eq
            ([string]$PublicationRecord.merge_commit).ToLowerInvariant() -and
        [string]$_.branch -ceq [string]$attempt.branch_ref -and
        ([string]$_.expected_tip).ToLowerInvariant() -eq [string]$attempt.expected_tip
    })
    if ([string]$snapshot.schema_version -ne "documentation_transaction_pending_v0.1" -or
        [string]$snapshot.status -ne "PENDING" -or
        ([string]$snapshot.latest_integration_tip).ToLowerInvariant() -ne
            ([string]$PublicationRecord.merge_commit).ToLowerInvariant() -or
        $matchingEntries.Count -ne 1) {
        throw "Documentation transaction snapshot does not bind the exact merge, branch, and source tip."
    }
    return [pscustomobject]@{
        PendingSha256 = $pendingSha256
        SnapshotRelativePath = $snapshotRelative
        SnapshotPath = $snapshotPath
        Payload = $snapshot
    }
}

function Assert-WeatherReconciliationQuietReport {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [switch]$AllowMergedUnpushed,
        [switch]$AllowPreDocumentation,
        [AllowNull()][object]$EvidenceSnapshot = $null
    )

    $attempt = $AttemptContract.Manifest
    $reportPath = Resolve-WeatherIntegrationPath -Path ([string]$attempt.evidence.quiet_merge_report)
    $reportSnapshot = if ($null -eq $EvidenceSnapshot) {
        Read-WeatherIntegrationEvidenceSnapshot `
            -Path $reportPath -MaximumBytes 2097152 -ContentType Json
    }
    else { $EvidenceSnapshot }
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$reportSnapshot.Path) -Right $reportPath)) {
        throw "Quiet-merge report snapshot path does not match the attempt evidence path."
    }
    $actualSha256 = [string]$reportSnapshot.Sha256
    if ($actualSha256 -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "Quiet-merge report hash mismatch. Expected $ExpectedSha256; got $actualSha256"
    }
    $report = $reportSnapshot.Payload
    $requiresAttemptReportAuthority = (
        [string]$attempt.schema -ceq $script:WeatherIntegrationAttemptManifestSchema
    )
    $reportBooleanNames = @(
        "ok", "capture_recovery_proved", "execution_tape_recovery_required",
        "execution_tape_readoption_expected",
        "execution_tape_rolled_but_inactive_skipped",
        "execution_tape_recovery_proved", "documentation_transaction_recorded",
        "publication_acknowledged"
    )
    if ($requiresAttemptReportAuthority) {
        $reportBooleanNames += "authoritative_attempt_report"
    }
    Assert-WeatherIntegrationBooleanProperties `
        -Object $report -Names $reportBooleanNames `
        -Label "reconciliation quiet-merge report"
    $isPushedReport = ([string]$report.stage -eq "pushed")
    $isRecoveredUnpushedReport = (
        $AllowMergedUnpushed.IsPresent -and
        [string]$report.stage -eq "merged_unpushed"
    )
    if ([string]$report.schema -ne "quiet_window_merge_report_v0.2" -or
        ($requiresAttemptReportAuthority -and
            ($report.authoritative_attempt_report -ne $true -or
             [string]$report.compatibility_outputs_authority -cne
                "DIAGNOSTIC_ONLY")) -or
        -not [bool]$report.ok -or
        (-not $isPushedReport -and -not $isRecoveredUnpushedReport) -or
        [string]$report.branch -ne [string]$attempt.branch_ref -or
        [string]$report.expected_tip -ne [string]$attempt.expected_tip -or
        [string]$report.expected_baseline -ne [string]$attempt.baseline.master -or
        [string]$report.baseline_commit -ne [string]$attempt.baseline.master -or
        [string]$report.resolved_branch_tip -ne [string]$attempt.expected_tip -or
        [string]$report.pre_merge_commit -notmatch '^[0-9a-f]{40}$' -or
        [string]$report.merge_commit -notmatch '^[0-9a-f]{40}$' -or
        -not [bool]$report.capture_recovery_proved -or
        ([bool]$report.execution_tape_recovery_required -and
            -not [bool]$report.execution_tape_recovery_proved) -or
        (-not [bool]$report.documentation_transaction_recorded -and
            -not $AllowPreDocumentation.IsPresent) -or
        ($isPushedReport -and -not [bool]$report.publication_acknowledged)) {
        throw "Hash-bound quiet-merge report does not prove this exact attempt's recovered integration commit."
    }
    if ([bool]$report.documentation_transaction_recorded) {
        Assert-WeatherReconciliationDocumentationProof `
            -AttemptContract $AttemptContract -PublicationRecord $report | Out-Null
    }
    elseif ($isPushedReport) {
        throw "A pushed report cannot omit the exact documentation transaction proof."
    }
    return [pscustomobject]@{
        Report = $report
        ReportPath = $reportPath
        ReportSha256 = $actualSha256
    }
}

function Assert-WeatherReconciliationPriorMarkerAbortReport {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [AllowNull()][object]$EvidenceSnapshot = $null
    )

    $attempt = $AttemptContract.Manifest
    $path = Resolve-WeatherIntegrationPath -Path ([string]$attempt.evidence.quiet_merge_report)
    $reportSnapshot = if ($null -eq $EvidenceSnapshot) {
        Read-WeatherIntegrationEvidenceSnapshot `
            -Path $path -MaximumBytes 2097152 -ContentType Json
    }
    else { $EvidenceSnapshot }
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$reportSnapshot.Path) -Right $path)) {
        throw "Prior-marker abort report snapshot path does not match the attempt evidence path."
    }
    $sha256 = [string]$reportSnapshot.Sha256
    $raw = [string]$reportSnapshot.Text
    $report = $reportSnapshot.Payload
    $abortBooleanNames = @(
        "ok", "capture_recovery_proved", "execution_tape_recovery_required",
        "execution_tape_readoption_expected",
        "execution_tape_rolled_but_inactive_skipped",
        "execution_tape_recovery_proved", "documentation_transaction_recorded",
        "publication_acknowledged"
    )
    $requiresAttemptReportAuthority = (
        [string]$attempt.schema -ceq $script:WeatherIntegrationAttemptManifestSchema
    )
    if ($requiresAttemptReportAuthority) {
        $abortBooleanNames += "authoritative_attempt_report"
    }
    Assert-WeatherIntegrationBooleanProperties `
        -Object $report `
        -Names $abortBooleanNames `
        -Label "prior-marker abort report"
    $expectedDetail = "a prior quiet-window merge marker still exists - let WeatherBootRecovery reconcile it before another merge"
    $rollbackProperties = @($report.rollback_content_sha256.PSObject.Properties)
    if ([string]$report.schema -ne "quiet_window_merge_report_v0.2" -or
        ($requiresAttemptReportAuthority -and
            ($report.authoritative_attempt_report -ne $true -or
             [string]$report.compatibility_outputs_authority -cne
                "DIAGNOSTIC_ONLY")) -or
        [bool]$report.ok -or [string]$report.stage -ne "abort" -or
        [string]$report.detail -cne $expectedDetail -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$report.repo_root) -Right ([string]$attempt.repo_root)) -or
        [string]$report.branch -ne [string]$attempt.branch_ref -or
        [string]$report.expected_tip -ne [string]$attempt.expected_tip -or
        [string]$report.expected_baseline -ne [string]$attempt.baseline.master -or
        -not [string]::IsNullOrWhiteSpace([string]$report.resolved_branch_tip) -or
        -not [string]::IsNullOrWhiteSpace([string]$report.baseline_commit) -or
        -not [string]::IsNullOrWhiteSpace([string]$report.pre_merge_commit) -or
        -not [string]::IsNullOrWhiteSpace([string]$report.merge_commit) -or
        $rollbackProperties.Count -ne 0 -or
        [bool]$report.capture_recovery_proved -or
        ([bool]$report.execution_tape_recovery_required -and
            [bool]$report.execution_tape_rolled_but_inactive_skipped) -or
        ([bool]$report.execution_tape_rolled_but_inactive_skipped -and
            -not [bool]$report.execution_tape_readoption_expected) -or
        [bool]$report.execution_tape_recovery_proved -or
        $null -ne $report.execution_tape_source_before -or
        [bool]$report.documentation_transaction_recorded -or
        -not [string]::IsNullOrWhiteSpace([string]$report.documentation_transaction_pending_sha256) -or
        -not [string]::IsNullOrWhiteSpace([string]$report.documentation_transaction_snapshot_path) -or
        [bool]$report.publication_acknowledged -or
        @($report.log | Where-Object { [string]$_ -like "*ABORT: $expectedDetail" }).Count -ne 1) {
        throw "Only the exact evidence-free prior-marker refusal report may be weaker than an active post-commit marker."
    }
    return [pscustomobject]@{
        Report = $report
        ReportPath = $path
        ReportSha256 = $sha256
        RawText = $raw
    }
}

function Assert-WeatherReconciliationPriorMarkerFailReceipt {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][object]$AbortReportContract
    )

    $attempt = $AttemptContract.Manifest
    $path = Resolve-WeatherIntegrationPath -Path ([string]$attempt.evidence.merge_receipt)
    $receiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $path -MaximumBytes 2097152 -ContentType Json
    $sha256 = [string]$receiptSnapshot.Sha256
    $receipt = $receiptSnapshot.Payload
    if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptMergeReceiptSchema -or
        [string]$receipt.status -ne "FAIL" -or
        [string]$receipt.attempt_id -ne [string]$attempt.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256 -or
        [string]$receipt.source_tip -ne [string]$attempt.expected_tip -or
        [string]$receipt.branch_ref -ne [string]$attempt.branch_ref -or
        [string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "Prior-marker FAIL receipt is not the exact non-live attempt receipt."
    }
    foreach ($scriptName in @("attempt_merge", "quiet_merge")) {
        $receiptScript = $receipt.scripts.$scriptName
        $manifestScript = $attempt.orchestration.$scriptName
        if ($null -eq $receiptScript -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$receiptScript.path) -Right ([string]$manifestScript.path)) -or
            [string]$receiptScript.sha256 -ne [string]$manifestScript.sha256) {
            throw "Prior-marker FAIL receipt script binding is invalid: $scriptName"
        }
    }
    $suiteContract = Assert-WeatherIntegrationSuiteReceipt -AttemptContract $AttemptContract
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.suite_receipt_path) -Right $suiteContract.ReceiptPath) -or
        [string]$receipt.suite_receipt_sha256 -ne [string]$suiteContract.ReceiptSha256 -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.quiet_merge_report.path) `
            -Right $AbortReportContract.ReportPath) -or
        [string]$receipt.quiet_merge_report.sha256 -ne [string]$AbortReportContract.ReportSha256) {
        throw "Prior-marker FAIL receipt does not bind its PASS suite and exact abort report."
    }
    $embeddedCanonical = $receipt.quiet_merge_report.payload | ConvertTo-Json -Depth 8 -Compress
    $reportCanonical = $AbortReportContract.Report | ConvertTo-Json -Depth 8 -Compress
    if ($embeddedCanonical -cne $reportCanonical -or
        [bool]$receipt.origin_master_verified -or
        [bool]$receipt.source_tip_integrated -or
        [bool]$receipt.capture_recovery_proved -or
        [bool]$receipt.documentation_transaction_recorded) {
        throw "Prior-marker FAIL receipt embeds contradictory publication evidence."
    }
    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = $path
        ReceiptSha256 = $sha256
    }
}

function Assert-WeatherReconciliationFailedMergeReceipt {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$ExpectedReceiptSha256,
        [switch]$AllowPreDocumentation,
        [AllowNull()][object]$EvidenceSnapshot = $null
    )

    $attempt = $AttemptContract.Manifest
    $receiptPath = Resolve-WeatherIntegrationPath -Path ([string]$attempt.evidence.merge_receipt)
    $receiptSnapshot = if ($null -eq $EvidenceSnapshot) {
        Read-WeatherIntegrationEvidenceSnapshot `
            -Path $receiptPath -MaximumBytes 2097152 -ContentType Json
    }
    else { $EvidenceSnapshot }
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receiptSnapshot.Path) -Right $receiptPath)) {
        throw "Merge receipt snapshot path does not match the attempt evidence path."
    }
    $actualReceiptSha256 = [string]$receiptSnapshot.Sha256
    if ($actualReceiptSha256 -ne $ExpectedReceiptSha256.ToLowerInvariant()) {
        throw "Merge receipt hash mismatch. Expected $ExpectedReceiptSha256; got $actualReceiptSha256"
    }
    $receipt = $receiptSnapshot.Payload
    if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptMergeReceiptSchema -or
        [string]$receipt.status -ne "FAIL" -or
        [string]$receipt.attempt_id -ne [string]$attempt.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256 -or
        [string]$receipt.source_tip -ne [string]$attempt.expected_tip -or
        [string]$receipt.branch_ref -ne [string]$attempt.branch_ref -or
        [string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "Hash-bound FAIL receipt is not the exact non-live integration attempt."
    }
    foreach ($scriptName in @("attempt_merge", "quiet_merge")) {
        $receiptScript = $receipt.scripts.$scriptName
        $manifestScript = $attempt.orchestration.$scriptName
        if ($null -eq $receiptScript -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$receiptScript.path) -Right ([string]$manifestScript.path)) -or
            [string]$receiptScript.sha256 -ne [string]$manifestScript.sha256) {
            throw "FAIL receipt script binding does not match the frozen manifest: $scriptName"
        }
    }

    $suiteContract = Assert-WeatherIntegrationSuiteReceipt -AttemptContract $AttemptContract
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.suite_receipt_path) `
            -Right ([string]$suiteContract.ReceiptPath)) -or
        [string]$receipt.suite_receipt_sha256 -ne [string]$suiteContract.ReceiptSha256) {
        throw "FAIL receipt does not bind the immutable PASS suite receipt it consumed."
    }
    $quietPath = Resolve-WeatherIntegrationPath -Path ([string]$attempt.evidence.quiet_merge_report)
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.quiet_merge_report.path) `
            -Right $quietPath) -or
        [string]$receipt.quiet_merge_report.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "FAIL receipt does not bind the canonical immutable quiet-merge report."
    }
    $quietContract = Assert-WeatherReconciliationQuietReport `
        -AttemptContract $AttemptContract `
        -ExpectedSha256 ([string]$receipt.quiet_merge_report.sha256) `
        -AllowMergedUnpushed `
        -AllowPreDocumentation:($AllowPreDocumentation.IsPresent)
    if ([string]$quietContract.Report.stage -ne "merged_unpushed" -or
        [string]$receipt.quiet_merge_report.payload.schema -ne [string]$quietContract.Report.schema -or
        [string]$receipt.quiet_merge_report.payload.stage -ne [string]$quietContract.Report.stage -or
        [string]$receipt.quiet_merge_report.payload.merge_commit -ne [string]$quietContract.Report.merge_commit -or
        [string]$receipt.quiet_merge_report.payload.expected_tip -ne [string]$quietContract.Report.expected_tip -or
        [string]$receipt.quiet_merge_report.payload.expected_baseline -ne [string]$quietContract.Report.expected_baseline) {
        throw "FAIL receipt does not embed the same recovered-unpushed commit as its hash-bound report."
    }
    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = $receiptPath
        ReceiptSha256 = $actualReceiptSha256
        QuietReport = $quietContract.Report
        QuietReportSha256 = $quietContract.ReportSha256
    }
}

function Assert-WeatherReconciliationActiveMarker {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [switch]$AllowPreDocumentation,
        [AllowNull()][object]$EvidenceSnapshot = $null
    )

    $attempt = $AttemptContract.Manifest
    $repo = Resolve-WeatherIntegrationPath -Path ([string]$attempt.repo_root)
    $markerPath = Join-Path $repo "data\alerts\quiet_window_merge_in_progress.json"
    $markerSnapshot = if ($null -eq $EvidenceSnapshot) {
        Read-WeatherIntegrationEvidenceSnapshot `
            -Path $markerPath -MaximumBytes 2097152 -ContentType Json
    }
    else { $EvidenceSnapshot }
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$markerSnapshot.Path) -Right $markerPath)) {
        throw "Active quiet-merge marker snapshot path is not canonical."
    }
    $actualSha256 = [string]$markerSnapshot.Sha256
    if ($actualSha256 -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "Active quiet-merge marker hash mismatch. Expected $ExpectedSha256; got $actualSha256"
    }
    $markerRaw = [string]$markerSnapshot.Text
    $marker = $markerSnapshot.Payload
    Assert-WeatherIntegrationBooleanProperties `
        -Object $marker `
        -Names @("execution_tape_readoption_expected") `
        -Label "active quiet-merge marker"
    $allowedPhases = @("documented_unpublished", "published")
    if ($AllowPreDocumentation.IsPresent) {
        $allowedPhases = @("merge_committed_unpublished") + $allowedPhases
    }
    if ([string]$marker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$marker.repo_root) -Right $repo) -or
        [string]$marker.phase -notin $allowedPhases -or
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
        ([string]$marker.phase -ne "merge_committed_unpublished" -and
            -not [bool]$marker.documentation_transaction_recorded) -or
        ([string]$marker.phase -eq "merge_committed_unpublished" -and
            [bool]$marker.documentation_transaction_recorded) -or
        ([string]$marker.phase -eq "published" -and
            -not [bool]$marker.publication_acknowledged)) {
        throw "Hash-bound active marker does not prove this exact attempt reached published recovery."
    }
    if ([bool]$marker.documentation_transaction_recorded) {
        Assert-WeatherReconciliationDocumentationProof `
            -AttemptContract $AttemptContract -PublicationRecord $marker | Out-Null
    }
    return [pscustomobject]@{
        Report = $marker
        ReportPath = Resolve-WeatherIntegrationPath -Path $markerPath
        ReportSha256 = $actualSha256
        IsActiveMarker = $true
        RawText = $markerRaw
    }
}

function Get-WeatherReconciliationCaptureProof {
    param(
        [Parameter(Mandatory = $true)][object]$PythonBinding,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot
    )

    $child = Invoke-WeatherReconciliationPythonJson `
        -PythonBinding $PythonBinding -RepositoryRoot $RepositoryRoot `
        -Arguments @(
            "-m", "weather.operations.capture_recovery_check",
            "--repo-root", $RepositoryRoot, "--json"
        ) `
        -ModuleRelativePath "src/weather/operations/capture_recovery_check.py" `
        -Label "reconciliation capture recovery" `
        -AllowedExitCodes @(0, 2)
    $payload = $child.Payload
    if ([int]$child.ExitCode -ne 0 -or -not [bool]$payload.ok -or
        @($payload.workers).Count -ne 3 -or
        @($payload.workers | Where-Object { -not [bool]$_.ok }).Count -ne 0) {
        throw "Current capture state is not healthy for all three workers; reconciliation remains blocked."
    }
    return $payload
}

function Get-WeatherReconciliationExecutionTapeProof {
    param(
        [Parameter(Mandatory = $true)][object]$PythonBinding,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot
    )

    $writerLockPath = Join-Path $RepositoryRoot "data\snapshots\.execution_tape_status.json.writer.lock"
    $child = Invoke-WeatherReconciliationPythonJson `
        -PythonBinding $PythonBinding -RepositoryRoot $RepositoryRoot `
        -Arguments @(
            "-m", "weather.operations.execution_tape_supervisor", "status",
            "--stale-after-seconds", "180"
        ) `
        -ModuleRelativePath "src/weather/operations/execution_tape_supervisor.py" `
        -Label "reconciliation execution-tape status" `
        -AllowedExitCodes @(0, 2)
    try {
        $payload = $child.Payload
        $writerLock = Read-WeatherIntegrationSharedJson -Path $writerLockPath
    }
    catch { throw "Current execution-tape proof or writer lock is unreadable." }
    $health = $payload.health
    $status = $payload.status
    if ([int]$child.ExitCode -ne 0 -or
        [string]$health.state -notin @("RUNNING", "DEGRADED") -or
        $health.pid_alive -ne $true -or
        $health.runtime_identity_matches_current -ne $true -or
        [string]$health.evidence_integrity -ne "PASS" -or
        [string]$status.state -ne "CONNECTED" -or
        [string]$status.market -ne "all" -or
        [string]$status.runner -ne "managed_execution_tape" -or
        $status.managed_process.verified_at_capture -ne $true -or
        [int]$status.pid -le 0 -or
        [int]$status.pid -ne [int]$status.managed_process.pid -or
        [int]$status.pid -ne [int]$writerLock.pid -or
        [int]$status.pid -ne [int]$writerLock.managed_process.pid -or
        [string]$status.managed_process.creation_time_token -cne
            [string]$writerLock.managed_process.creation_time_token) {
        throw "Current canonical execution-tape status/lock/process/source proof is unhealthy."
    }
    return [pscustomobject]@{ payload = $payload; writer_lock = $writerLock }
}

function Assert-WeatherReconciliationMergeShape {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][object]$Attempt,
        [Parameter(Mandatory = $true)][object]$PublicationRecord
    )

    $mergeCommit = ([string]$PublicationRecord.merge_commit).ToLowerInvariant()
    $preMergeCommit = ([string]$PublicationRecord.pre_merge_commit).ToLowerInvariant()
    $resolvedTip = ([string]$PublicationRecord.resolved_branch_tip).ToLowerInvariant()
    $baseline = ([string]$PublicationRecord.baseline_commit).ToLowerInvariant()
    if ($mergeCommit -notmatch '^[0-9a-f]{40}$' -or
        $preMergeCommit -notmatch '^[0-9a-f]{40}$' -or
        $resolvedTip -ne [string]$Attempt.expected_tip -or
        $baseline -ne [string]$Attempt.baseline.master) {
        throw "Publication evidence cannot identify the exact merge/pre-merge/baseline commits."
    }
    $firstParent = Invoke-WeatherReconciliationGitLine `
        -Root $RepositoryRoot -Arguments @("rev-parse", "$mergeCommit^1")
    $secondParent = Invoke-WeatherReconciliationGitLine `
        -Root $RepositoryRoot -Arguments @("rev-parse", "$mergeCommit^2")
    $mergeParentLine = Invoke-WeatherReconciliationGitLine `
        -Root $RepositoryRoot -Arguments @("rev-list", "--parents", "-n", "1", $mergeCommit)
    if (@($mergeParentLine -split '\s+' | Where-Object { $_ }).Count -ne 3 -or
        $firstParent -ne $preMergeCommit -or $secondParent -ne $resolvedTip) {
        throw "Recovered integration commit is not the exact two-parent merge recorded by durable evidence."
    }
    Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepositoryRoot `
        -Arguments @("merge-base", "--is-ancestor", $baseline, $preMergeCommit) `
        -Label "reconciliation pre-merge baseline-ancestry proof" | Out-Null
    if ($preMergeCommit -ne $baseline) {
        $preMergeParent = Invoke-WeatherReconciliationGitLine `
            -Root $RepositoryRoot -Arguments @("rev-parse", "$preMergeCommit^")
        $preMergeParentLine = Invoke-WeatherReconciliationGitLine `
            -Root $RepositoryRoot -Arguments @("rev-list", "--parents", "-n", "1", $preMergeCommit)
        $preMergeChangesQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $RepositoryRoot `
            -Arguments @("diff", "--name-only", $baseline, $preMergeCommit) `
            -Label "reconciliation pre-merge changed-path query"
        $preMergeChanges = @($preMergeChangesQuery.StdoutLines)
        if (@($preMergeParentLine -split '\s+' | Where-Object { $_ }).Count -ne 2 -or
            $preMergeParent -ne $baseline -or
            @($preMergeChanges | Where-Object { $_ }).Count -eq 0 -or
            @($preMergeChanges | Where-Object {
                $_ -and $_ -notin @("config/locations.json", "config/location_market_events.json")
            }).Count -ne 0) {
            throw "Pre-merge preparation is not an exact allowlisted generated-config child of baseline."
        }
    }
}

function Assert-WeatherReconciliationTrackedState {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][object]$PublicationRecord
    )

    $statusQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepositoryRoot `
        -Arguments @("status", "--porcelain", "--untracked-files=no") `
        -Label "reconciliation tracked production-state query"
    $statusRows = @($statusQuery.StdoutLines)
    $statusRows = @($statusRows | Where-Object { $_ })
    if ($statusRows.Count -eq 0) { return @() }
    $allowedPaths = @("config/locations.json", "config/location_market_events.json")
    $dirtyPaths = New-Object System.Collections.Generic.List[string]
    foreach ($row in $statusRows) {
        $statusText = [string]$row
        if ($statusText -notmatch '^(?: M|M |MM)\s+(.+)$') {
            throw "Publication resume rejects staged type changes, deletes, renames, copies, and unmerged paths."
        }
        $relativePath = $Matches[1].Trim().Replace('\', '/')
        if ($relativePath -notin $allowedPaths -or $dirtyPaths.Contains($relativePath)) {
            throw "Publication resume permits only a unique subset of the two generated-config drifts."
        }
        $dirtyPaths.Add($relativePath)
    }
    return @($dirtyPaths | ForEach-Object { $_ })
}

function Assert-WeatherReconciliationRegularSiblingFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedParent,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $resolvedParent = [IO.Path]::GetFullPath($ExpectedParent).TrimEnd('\')
    $actualParent = [IO.Path]::GetFullPath(
        (Split-Path -Parent $resolvedPath)
    ).TrimEnd('\')
    if (-not [string]::Equals(
            $actualParent,
            $resolvedParent,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "$Label is not an exact sibling of the active marker."
    }
    $item = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction Stop
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        -not [string]::Equals(
            [IO.Path]::GetFullPath([string]$item.FullName),
            $resolvedPath,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "$Label is not one exact regular non-reparse file."
    }
    return $item
}

function Write-WeatherReconciliationActiveMarker {
    param(
        [Parameter(Mandatory = $true)][object]$MarkerContract,
        [Parameter(Mandatory = $true)][string]$Phase,
        [Parameter(Mandatory = $true)][bool]$DocumentationRecorded,
        [Parameter(Mandatory = $true)][bool]$PublicationAcknowledged,
        [AllowEmptyString()][string]$DocumentationPendingSha256 = "",
        [AllowEmptyString()][string]$DocumentationSnapshotPath = ""
    )

    # This is an intentional second-time stability read immediately before the
    # replace; its retained bytes are independent of the earlier validation.
    $markerBeforeUpdate = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $MarkerContract.ReportPath -MaximumBytes 2097152 -ContentType Bytes
    if ([string]$markerBeforeUpdate.Sha256 -ne [string]$MarkerContract.ReportSha256) {
        throw "Active quiet-merge marker changed before its reviewed resume transition."
    }
    $marker = $MarkerContract.Report
    if ([string]::IsNullOrWhiteSpace($DocumentationPendingSha256)) {
        $DocumentationPendingSha256 = [string]$marker.documentation_transaction_pending_sha256
    }
    if ([string]::IsNullOrWhiteSpace($DocumentationSnapshotPath)) {
        $DocumentationSnapshotPath = [string]$marker.documentation_transaction_snapshot_path
    }
    $updated = [ordered]@{
        schema = "quiet_window_merge_in_progress_v0.1"
        updated_at = (Get-Date).ToString("o")
        repo_root = [string]$marker.repo_root
        phase = $Phase
        branch = [string]$marker.branch
        expected_tip = [string]$marker.expected_tip
        expected_baseline = [string]$marker.expected_baseline
        resolved_branch_tip = [string]$marker.resolved_branch_tip
        baseline_commit = [string]$marker.baseline_commit
        pre_merge_commit = [string]$marker.pre_merge_commit
        merge_commit = [string]$marker.merge_commit
        capture_recovery_proved = [bool]$marker.capture_recovery_proved
        execution_tape_readoption_expected = [bool]$marker.execution_tape_readoption_expected
        execution_tape_recovery_required = [bool]$marker.execution_tape_recovery_required
        execution_tape_rolled_but_inactive_skipped = [bool]$marker.execution_tape_rolled_but_inactive_skipped
        execution_tape_recovery_proved = [bool]$marker.execution_tape_recovery_proved
        execution_tape_source_before = $marker.execution_tape_source_before
        documentation_transaction_recorded = $DocumentationRecorded
        documentation_transaction_pending_sha256 = $DocumentationPendingSha256
        documentation_transaction_snapshot_path = $DocumentationSnapshotPath
        publication_acknowledged = $PublicationAcknowledged
        auto_refreshed_paths = @($marker.auto_refreshed_paths)
        auto_refreshed_sha256 = $marker.auto_refreshed_sha256
    }
    $raw = $updated | ConvertTo-Json -Depth 8
    $encoder = New-Object Text.UTF8Encoding($false, $true)
    [byte[]]$rawBytes = $encoder.GetBytes($raw)
    $expectedHash = [Security.Cryptography.SHA256]::Create()
    try {
        $expectedSha256 = (
            [BitConverter]::ToString($expectedHash.ComputeHash($rawBytes)) -replace '-', ''
        ).ToLowerInvariant()
    }
    finally { $expectedHash.Dispose() }

    $markerPath = Resolve-WeatherIntegrationPath -Path $MarkerContract.ReportPath
    $parent = [IO.Path]::GetFullPath((Split-Path -Parent $markerPath))
    $parentItem = Get-Item -LiteralPath $parent -Force -ErrorAction Stop
    if (-not $parentItem.PSIsContainer -or
        ($parentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        -not [string]::Equals(
            [IO.Path]::GetFullPath([string]$parentItem.FullName).TrimEnd('\'),
            $parent.TrimEnd('\'),
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "Active-marker parent is not one exact regular directory."
    }
    Assert-WeatherReconciliationRegularSiblingFile `
        -Path $markerPath -ExpectedParent $parent `
        -Label "active quiet-merge marker" | Out-Null
    $leaf = Split-Path -Leaf $markerPath
    $temp = Join-Path $parent (".{0}.{1}.tmp" -f $leaf, [guid]::NewGuid().ToString("N"))
    $backup = Join-Path $parent (".{0}.{1}.bak" -f $leaf, [guid]::NewGuid().ToString("N"))
    if ((Test-Path -LiteralPath $temp) -or (Test-Path -LiteralPath $backup)) {
        throw "Unique active-marker transaction paths unexpectedly already exist."
    }
    $tempStream = $null
    $updatedContract = $null
    $primaryFailure = $null
    $cleanupFailures = New-Object System.Collections.Generic.List[string]
    try {
        $tempStream = [IO.FileStream]::new(
            $temp,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None,
            4096,
            [IO.FileOptions]::WriteThrough
        )
        $tempStream.Write($rawBytes, 0, $rawBytes.Length)
        $tempStream.Flush($true)
        if ($tempStream.Length -ne $rawBytes.Length) {
            throw "Active-marker transaction temp did not retain the exact intended byte count."
        }
        $tempStream.Dispose()
        $tempStream = $null
        Assert-WeatherReconciliationRegularSiblingFile `
            -Path $temp -ExpectedParent $parent `
            -Label "active-marker transaction temp" | Out-Null

        # Re-read the current marker immediately before replacement. The
        # production-mutation mutex serializes repository-owned writers, while
        # this stable snapshot refuses any intervening byte change.
        $markerAtReplace = Read-WeatherIntegrationEvidenceSnapshot `
            -Path $markerPath -MaximumBytes 2097152 -ContentType Bytes
        if ([string]$markerAtReplace.Sha256 -ne [string]$markerBeforeUpdate.Sha256) {
            throw "Active quiet-merge marker changed during its reviewed resume transition."
        }

        [IO.File]::Replace($temp, $markerPath, $backup, $true)
        Assert-WeatherReconciliationRegularSiblingFile `
            -Path $markerPath -ExpectedParent $parent `
            -Label "updated active quiet-merge marker" | Out-Null
        Assert-WeatherReconciliationRegularSiblingFile `
            -Path $backup -ExpectedParent $parent `
            -Label "active-marker transaction backup" | Out-Null
        $backupSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path $backup -MaximumBytes 2097152 -ContentType Bytes
        if ([string]$backupSnapshot.Sha256 -ne [string]$markerBeforeUpdate.Sha256 -or
            [long]$backupSnapshot.Length -ne [long]$markerBeforeUpdate.Length) {
            throw "Active-marker transaction backup does not contain the exact prior marker."
        }
        $updatedSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path $markerPath -MaximumBytes 2097152 -ContentType Json
        if ([string]$updatedSnapshot.Sha256 -ne $expectedSha256 -or
            [long]$updatedSnapshot.Length -ne [long]$rawBytes.Length -or
            [string]$updatedSnapshot.Text -cne $raw) {
            throw "Active-marker transaction readback does not equal the exact retained bytes."
        }
        $updatedContract = [pscustomobject]@{
            Report = $updatedSnapshot.Payload
            ReportPath = $markerPath
            ReportSha256 = [string]$updatedSnapshot.Sha256
            IsActiveMarker = $true
            RawText = [string]$updatedSnapshot.Text
        }
    }
    catch {
        $primaryFailure = $_
    }
    finally {
        if ($null -ne $tempStream) {
            try { $tempStream.Dispose() }
            catch { $cleanupFailures.Add("temp stream: $($_.Exception.Message)") }
        }
        foreach ($ownedPath in @($temp, $backup)) {
            if (-not (Test-Path -LiteralPath $ownedPath)) { continue }
            try {
                Assert-WeatherReconciliationRegularSiblingFile `
                    -Path $ownedPath -ExpectedParent $parent `
                    -Label "owned active-marker transaction artifact" | Out-Null
                Remove-Item -LiteralPath $ownedPath -Force -ErrorAction Stop
                if (Test-Path -LiteralPath $ownedPath) {
                    throw "owned transaction artifact still exists after removal: $ownedPath"
                }
            }
            catch { $cleanupFailures.Add("${ownedPath}: $($_.Exception.Message)") }
        }
        if ($cleanupFailures.Count -ne 0) {
            $cleanupMessage = (
                "Active-marker transaction cleanup failed: " +
                ($cleanupFailures -join " | ")
            )
            if ($null -ne $primaryFailure) {
                $primaryFailure.Exception.Data["weather_cleanup_failure"] = $cleanupMessage
                Write-Warning $cleanupMessage -WarningAction Continue
            }
            else { throw $cleanupMessage }
        }
    }
    if ($null -ne $primaryFailure) { throw $primaryFailure }
    return $updatedContract
}

function Assert-WeatherReconciliationOneShotPushTask {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot)

    $pushTasks = @(Get-ScheduledTask -TaskName "WeatherOneShotPush" -ErrorAction Stop)
    if ($pushTasks.Count -ne 1) {
        throw "WeatherOneShotPush must resolve to exactly one root scheduled task."
    }
    $pushTask = $pushTasks[0]
    $pushActions = @($pushTask.Actions)
    $pushTriggers = @($pushTask.Triggers | Where-Object { $null -ne $_ })
    try {
        $pushTaskXml = [string](Export-ScheduledTask `
            -TaskName "WeatherOneShotPush" -TaskPath "\" -ErrorAction Stop)
    }
    catch {
        throw "WeatherOneShotPush exact XML could not be exported: $($_.Exception.Message)"
    }
    $pushTaskXmlHash = [Security.Cryptography.SHA256]::Create()
    try {
        $pushTaskXmlSha256 = ([BitConverter]::ToString(
            $pushTaskXmlHash.ComputeHash([Text.Encoding]::UTF8.GetBytes($pushTaskXml))
        ) -replace '-', '').ToLowerInvariant()
    }
    finally { $pushTaskXmlHash.Dispose() }
    $expectedPushTaskXmlSha256 = "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
    $expectedPushSid = "S-1-5-21-1525964525-1566663060-3901869365-1001"
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $expectedWorkingDirectory = [IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
    $actualWorkingDirectory = if ($pushActions.Count -eq 1) {
        try { [IO.Path]::GetFullPath([string]$pushActions[0].WorkingDirectory).TrimEnd('\') }
        catch { "" }
    }
    else { "" }
    $expectedPushArguments = '/c git -C c:\Users\micha\Desktop\github\weather push origin master > C:\Users\micha\ops\logs\push-oneshot.log 2>&1'
    if ([string]$pushTask.TaskPath -cne "\" -or
        [string]$pushTask.State -cne "Ready" -or
        $pushTask.Settings.Enabled -ne $true -or
        [string]$pushTask.Settings.MultipleInstances -cne "IgnoreNew" -or
        [string]$pushTask.Settings.ExecutionTimeLimit -cne "PT15M" -or
        [bool]$pushTask.Settings.StartWhenAvailable -or
        $pushTriggers.Count -ne 0 -or
        $pushTaskXmlSha256 -cne $expectedPushTaskXmlSha256 -or
        [string]$pushTask.Principal.UserId -ine "micha" -or
        $currentSid -cne $expectedPushSid -or
        [string]$pushTask.Principal.LogonType -cne "Interactive" -or
        [string]$pushTask.Principal.RunLevel -cne "Limited" -or
        $pushActions.Count -ne 1 -or
        [string]$pushActions[0].Execute -ine "cmd.exe" -or
        [string]$pushActions[0].Arguments -ine $expectedPushArguments -or
        $actualWorkingDirectory -ine $expectedWorkingDirectory) {
        throw "WeatherOneShotPush is not exactly bound to the enabled current-user Interactive/Limited git-push contract."
    }
    return $pushTask
}

function Assert-WeatherReconciliationResumeEvidenceBoundary {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][object]$PublicationContract,
        [AllowNull()][object]$CurrentMarkerContract,
        [Parameter(Mandatory = $true)][string]$MergeCommit,
        [Parameter(Mandatory = $true)][string]$DocumentationPendingSha256,
        [Parameter(Mandatory = $true)][string]$DocumentationSnapshotPath
    )

    $isMutableMarker = (
        $null -ne $PublicationContract.PSObject.Properties["IsActiveMarker"] -and
        [bool]$PublicationContract.IsActiveMarker
    )
    if (-not $isMutableMarker) {
        # Intentional boundary recheck: prove the immutable report still has
        # the bytes validated before the publication-side mutation begins.
        $publicationBoundarySnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path $PublicationContract.ReportPath -MaximumBytes 2097152 -ContentType Bytes
        if ([string]$publicationBoundarySnapshot.Sha256 -ne
            [string]$PublicationContract.ReportSha256) {
            throw "Hash-bound immutable publication report changed during publication resume."
        }
    }
    if ($null -ne $CurrentMarkerContract) {
        # Intentional boundary recheck: hash, raw text, and the structural
        # validation below all consume this one newly retained snapshot.
        $currentMarkerSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path $CurrentMarkerContract.ReportPath -MaximumBytes 2097152 -ContentType Json
        if ([string]$currentMarkerSnapshot.Sha256 -ne
                [string]$CurrentMarkerContract.ReportSha256 -or
            [string]$currentMarkerSnapshot.Text -cne
                [string]$CurrentMarkerContract.RawText) {
            throw "Current active marker changed during publication resume."
        }
        Assert-WeatherReconciliationActiveMarker `
            -AttemptContract $AttemptContract `
            -ExpectedSha256 ([string]$CurrentMarkerContract.ReportSha256) `
            -AllowPreDocumentation `
            -EvidenceSnapshot $currentMarkerSnapshot | Out-Null
    }
    $documentationRecord = [pscustomobject]@{
        merge_commit = $MergeCommit
        documentation_transaction_pending_sha256 = $DocumentationPendingSha256
        documentation_transaction_snapshot_path = $DocumentationSnapshotPath
    }
    Assert-WeatherReconciliationDocumentationProof `
        -AttemptContract $AttemptContract `
        -PublicationRecord $documentationRecord | Out-Null
}

function Invoke-WeatherReconciliationPublicationResume {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][object]$PublicationContract,
        [AllowNull()][object]$MarkerContract,
        [Parameter(Mandatory = $true)][object]$PythonBinding
    )

    $attempt = $AttemptContract.Manifest
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$attempt.repo_root)
    $publication = $PublicationContract.Report
    $mergeCommit = ([string]$publication.merge_commit).ToLowerInvariant()
        $branch = Invoke-WeatherReconciliationGitLine `
            -Root $repoRoot -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
        $head = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "HEAD")
        $master = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "master")
        $origin = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "origin/master")
        $mergeHeadQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $repoRoot `
            -Arguments @("rev-parse", "--git-path", "MERGE_HEAD") `
            -Label "reconciliation publication-resume MERGE_HEAD path query"
        $mergeHeadPath = @($mergeHeadQuery.StdoutLines)
        if ($mergeHeadPath.Count -ne 1 -or
            [string]::IsNullOrWhiteSpace([string]$mergeHeadPath[0])) {
            throw "Could not resolve MERGE_HEAD while resuming publication."
        }
        $resolvedMergeHeadPath = [string]$mergeHeadPath[0]
        if (-not [IO.Path]::IsPathRooted($resolvedMergeHeadPath)) {
            $resolvedMergeHeadPath = Join-Path $repoRoot $resolvedMergeHeadPath
        }
        if ($branch -ne "master" -or
            $head -ne $mergeCommit -or $master -ne $mergeCommit -or
            $origin -notin @([string]$attempt.baseline.origin_master, $mergeCommit) -or
            (Test-Path -LiteralPath $resolvedMergeHeadPath -PathType Leaf)) {
            throw "Publication resume requires checked-out master at the exact recovered merge, with origin still at baseline or that merge."
        }
        Assert-WeatherReconciliationMergeShape `
            -RepositoryRoot $repoRoot -Attempt $attempt -PublicationRecord $publication
        Assert-WeatherReconciliationTrackedState `
            -RepositoryRoot $repoRoot -PublicationRecord $publication | Out-Null
        $captureBefore = Get-WeatherReconciliationCaptureProof `
            -PythonBinding $PythonBinding -RepositoryRoot $repoRoot
        $executionTapeBefore = $null
        if ([bool]$publication.execution_tape_recovery_required) {
            $executionTapeBefore = Get-WeatherReconciliationExecutionTapeProof `
                -PythonBinding $PythonBinding -RepositoryRoot $repoRoot
        }
        Assert-WeatherReconciliationOneShotPushTask -RepositoryRoot $repoRoot | Out-Null

        $workingMarker = $MarkerContract
        $documentationStarted = $false
        $documentationPendingSha256 = [string]$publication.documentation_transaction_pending_sha256
        $documentationSnapshotPath = [string]$publication.documentation_transaction_snapshot_path
        if (-not [bool]$publication.documentation_transaction_recorded) {
            if ($null -eq $workingMarker -or
                [string]$workingMarker.Report.phase -ne "merge_committed_unpublished") {
                throw "Only an exact merge_committed_unpublished marker can resume missing documentation."
            }
            $documentationArgs = @(
                "-m", "weather.operations.documentation_transaction",
                "--repo-root", $repoRoot,
                "begin",
                "--integration-tip", $mergeCommit,
                "--branch", [string]$attempt.branch_ref,
                "--expected-tip", [string]$attempt.expected_tip
            )
            $documentationChild = Invoke-WeatherReconciliationPythonJson `
                -PythonBinding $PythonBinding -RepositoryRoot $repoRoot `
                -Arguments $documentationArgs `
                -ModuleRelativePath `
                    "src/weather/operations/documentation_transaction.py" `
                -Label "reconciliation documentation transaction begin" `
                -AllowedExitCodes @(0, 1)
            if ([int]$documentationChild.ExitCode -ne 0) {
                throw "Documentation transaction begin failed during publication resume."
            }
            $documentationPayload = $documentationChild.Payload
            $documentationPendingSha256 = ([string]$documentationPayload.pending_sha256).ToLowerInvariant()
            $documentationSnapshotPath = "data/alerts/documentation_transactions/pending-$documentationPendingSha256.json"
            $documentationPendingPath = Join-Path $repoRoot "data\alerts\documentation_transaction_pending.json"
            if ($documentationPendingSha256 -notmatch '^[0-9a-f]{64}$' -or
                (Get-WeatherIntegrationFileSha256 -Path $documentationPendingPath) -ne
                    $documentationPendingSha256) {
                throw "Documentation transaction begin did not leave exact canonical pending bytes."
            }
            $documentationProofRecord = [pscustomobject]@{
                merge_commit = $mergeCommit
                documentation_transaction_pending_sha256 = $documentationPendingSha256
                documentation_transaction_snapshot_path = $documentationSnapshotPath
            }
            Assert-WeatherReconciliationDocumentationProof `
                -AttemptContract $AttemptContract `
                -PublicationRecord $documentationProofRecord | Out-Null
            $documentationStarted = $true
        }
        else {
            $documentationProof = Assert-WeatherReconciliationDocumentationProof `
                -AttemptContract $AttemptContract `
                -PublicationRecord $publication
            $documentationPendingSha256 = $documentationProof.PendingSha256
            $documentationSnapshotPath = $documentationProof.SnapshotRelativePath
        }
        if ($null -ne $workingMarker -and
            [string]$workingMarker.Report.phase -eq "merge_committed_unpublished") {
            # The child may have durably begun documentation and then died
            # before advancing the marker. The immutable report/snapshot is
            # stronger than that lagging marker boolean; advance it without
            # assuming begin had not already happened.
            $workingMarker = Write-WeatherReconciliationActiveMarker `
                -MarkerContract $workingMarker `
                -Phase "documented_unpublished" `
                -DocumentationRecorded $true `
                -PublicationAcknowledged $false `
                -DocumentationPendingSha256 $documentationPendingSha256 `
                -DocumentationSnapshotPath $documentationSnapshotPath
        }
        elseif ($null -ne $workingMarker -and
            [string]$workingMarker.Report.phase -notin @("documented_unpublished", "published")) {
            throw "Marker phase is not eligible for reviewed publication resume."
        }

        if ($origin -ne $mergeCommit) {
            # Documentation begin is idempotent but may take time. Re-prove the
            # exact publication boundary immediately before starting the only
            # credential-bearing push task.
            $branch = Invoke-WeatherReconciliationGitLine `
                -Root $repoRoot -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
            $head = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "HEAD")
            $master = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "master")
            $origin = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "origin/master")
            if ($branch -ne "master" -or
                $head -ne $mergeCommit -or $master -ne $mergeCommit -or
                $origin -notin @([string]$attempt.baseline.origin_master, $mergeCommit)) {
                throw "Production Git changed while preparing reviewed publication resume."
            }
            Assert-WeatherReconciliationMergeShape `
                -RepositoryRoot $repoRoot -Attempt $attempt -PublicationRecord $publication
            Assert-WeatherReconciliationTrackedState `
                -RepositoryRoot $repoRoot -PublicationRecord $publication | Out-Null
            $captureBefore = Get-WeatherReconciliationCaptureProof `
                -PythonBinding $PythonBinding -RepositoryRoot $repoRoot
            if ([bool]$publication.execution_tape_recovery_required) {
                $executionTapeBefore = Get-WeatherReconciliationExecutionTapeProof `
                    -PythonBinding $PythonBinding -RepositoryRoot $repoRoot
            }
            Assert-WeatherReconciliationOneShotPushTask -RepositoryRoot $repoRoot | Out-Null
            Assert-WeatherReconciliationResumeEvidenceBoundary `
                -AttemptContract $AttemptContract `
                -PublicationContract $PublicationContract `
                -CurrentMarkerContract $workingMarker `
                -MergeCommit $mergeCommit `
                -DocumentationPendingSha256 $documentationPendingSha256 `
                -DocumentationSnapshotPath $documentationSnapshotPath
            Assert-WeatherIntegrationSchedulerMutationAllowed `
                -CommandName "Start-ScheduledTask" `
                -Phase "reviewed WeatherOneShotPush reconciliation resume"
            Start-ScheduledTask -TaskName "WeatherOneShotPush" -ErrorAction Stop
            $published = $false
            for ($poll = 0; $poll -lt 18; $poll++) {
                Start-Sleep -Seconds 10
                $origin = Invoke-WeatherReconciliationGitLine `
                    -Root $repoRoot -Arguments @("rev-parse", "origin/master")
                if ($origin -eq $mergeCommit) { $published = $true; break }
            }
            if (-not $published) {
                throw "WeatherOneShotPush did not acknowledge the exact recovered merge within three minutes."
            }
        }
        if ($null -ne $workingMarker) {
            $workingMarker = Write-WeatherReconciliationActiveMarker `
                -MarkerContract $workingMarker `
                -Phase "published" `
                -DocumentationRecorded $true `
                -PublicationAcknowledged $true
        }
        return [pscustomobject]@{
            publication_resumed = $true
            documentation_started = $documentationStarted
            capture_before = $captureBefore
            execution_tape_before = $executionTapeBefore
            marker = $workingMarker
        }
}

if ([string]::IsNullOrWhiteSpace($ReviewReference)) {
    throw "ReviewReference is required for MERGED_UNVERIFIED reconciliation."
}
$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
$manifest = $contract.Manifest
$pythonBinding = Get-WeatherReconciliationPythonBinding `
    -AttemptContract $contract
$terminalMutexRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
$terminalMutex = Enter-WeatherIntegrationControlMutex `
    -RepositoryRoot $terminalMutexRoot `
    -LockLeaf "integration_attempt_terminal.lock" `
    -Owner "reconcile_integration_attempt:$($manifest.attempt_id)"
if ($null -eq $terminalMutex) {
    throw "Another close/reconciliation owns the integration-attempt terminal mutex."
}
$reconciliationGitMutex = $null
$primaryError = $null
try {
if ($ResumePublication.IsPresent) {
    $workloadScript = Resolve-WeatherIntegrationPath -Path ([string]$manifest.orchestration.workload_admission.path)
    if ((Get-WeatherIntegrationFileSha256 -Path $workloadScript) -ne
        [string]$manifest.orchestration.workload_admission.sha256) {
        throw "Publication resume workload-admission script no longer matches the frozen manifest."
    }
    . $workloadScript
    $policyWindow = Get-WeatherHeavyWorkloadPolicyWindow
    if ($null -eq $policyWindow) {
        throw "Publication resume is outside the repository-owned heavy-work window."
    }
}
$reconciliationGitMutex = Enter-WeatherIntegrationControlMutex `
    -RepositoryRoot $terminalMutexRoot `
    -LockLeaf "heavy_workload.lock" `
    -Owner "reconcile_integration_attempt:$($manifest.attempt_id)"
if ($null -eq $reconciliationGitMutex) {
    throw "A guarded merge or other production mutation owns the shared workload mutex; reconciliation leaves all marker/evidence state intact."
}
$reconciliationPath = [string]$manifest.evidence.reconciliation_receipt
$closurePath = [string]$manifest.evidence.closure_receipt
if (Test-Path -LiteralPath $closurePath -PathType Leaf) {
    throw "A closure receipt already terminally abandoned this attempt; reconciliation cannot create a conflicting terminal receipt."
}
if (Test-Path -LiteralPath $reconciliationPath) {
    if ($PSCmdlet.ParameterSetName -eq "ActiveMarker") {
        $existing = Read-WeatherIntegrationSharedJson -Path $reconciliationPath
        $cleanupMarker = Assert-WeatherReconciliationActiveMarker `
            -AttemptContract $contract `
            -ExpectedSha256 $ExpectedActiveMarkerSha256
        $markerPath = $cleanupMarker.ReportPath
        $cleanupRepoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
        $cleanupHead = Invoke-WeatherReconciliationGitLine -Root $cleanupRepoRoot -Arguments @("rev-parse", "HEAD")
        $cleanupMaster = Invoke-WeatherReconciliationGitLine -Root $cleanupRepoRoot -Arguments @("rev-parse", "master")
        $cleanupOrigin = Invoke-WeatherReconciliationGitLine -Root $cleanupRepoRoot -Arguments @("rev-parse", "origin/master")
        $cleanupBranch = Invoke-WeatherReconciliationGitLine `
            -Root $cleanupRepoRoot -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
        $cleanupCapture = Get-WeatherReconciliationCaptureProof `
            -PythonBinding $pythonBinding -RepositoryRoot $cleanupRepoRoot
        Assert-WeatherReconciliationMergeShape `
            -RepositoryRoot $cleanupRepoRoot `
            -Attempt $manifest `
            -PublicationRecord $cleanupMarker.Report
        if ([bool]$cleanupMarker.Report.execution_tape_recovery_required) {
            Get-WeatherReconciliationExecutionTapeProof `
                -PythonBinding $pythonBinding `
                -RepositoryRoot $cleanupRepoRoot | Out-Null
        }
        $cleanupUsesResumeMarker = (
            [bool]$existing.publication_resume.performed -and
            [string]$existing.publication_resume.final_marker_sha256 -eq
                $ExpectedActiveMarkerSha256.ToLowerInvariant()
        )
        $cleanupUsesSupportingMarker = (
            -not $cleanupUsesResumeMarker -and
            [string]$existing.publication_evidence.supporting_active_marker_sha256 -eq
                $ExpectedActiveMarkerSha256.ToLowerInvariant()
        )
        $embeddedMarkerRaw = if ($cleanupUsesResumeMarker) {
            [string]$existing.publication_resume.final_marker_raw
        }
        elseif ($cleanupUsesSupportingMarker) {
            [string]$existing.publication_evidence.supporting_active_marker_raw
        }
        else { [string]$existing.publication_evidence.active_marker_raw }
        $embeddedMarkerSha256 = if ($cleanupUsesResumeMarker) {
            [string]$existing.publication_resume.final_marker_sha256
        }
        elseif ($cleanupUsesSupportingMarker) {
            [string]$existing.publication_evidence.supporting_active_marker_sha256
        }
        else { [string]$existing.publication_evidence.active_marker_sha256 }
        $markerEvidenceKindValid = (
            [string]$existing.publication_evidence.kind -eq "active_marker" -or
            $cleanupUsesResumeMarker -or $cleanupUsesSupportingMarker
        )
        if ([string]$existing.schema -ne $script:WeatherIntegrationAttemptReconciliationReceiptSchema -or
            [string]$existing.status -ne "MERGED_RECONCILED" -or
            [string]$existing.attempt_id -ne [string]$manifest.attempt_id -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$existing.manifest_path) -Right $contract.ManifestPath) -or
            [string]$existing.manifest_sha256 -ne [string]$contract.ManifestSha256 -or
            -not $markerEvidenceKindValid -or
            $embeddedMarkerSha256 -ne $ExpectedActiveMarkerSha256.ToLowerInvariant() -or
            $embeddedMarkerRaw -ne [string]$cleanupMarker.RawText -or
            [string]$existing.publication_evidence.published_integration_commit -ne
                [string]$cleanupMarker.Report.merge_commit -or
            [bool]$existing.historical_proof_upgraded -or [bool]$existing.downstream_authorized -or
            [string]$existing.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
            [bool]$existing.safety.credential_value_access_authorized -or
            [bool]$existing.safety.live_exchange_mutation_authorized -or
            @($existing.tasks | Where-Object { [bool]$_.exists -and -not [bool]$_.disabled }).Count -ne 0 -or
            $cleanupBranch -ne "master" -or $cleanupHead -ne [string]$cleanupMarker.Report.merge_commit -or
            $cleanupMaster -ne $cleanupHead -or $cleanupOrigin -ne $cleanupHead -or
            -not [bool]$cleanupCapture.ok -or
            @($cleanupCapture.workers).Count -ne 3 -or
            @($cleanupCapture.workers | Where-Object { -not [bool]$_.ok }).Count -ne 0) {
            throw "Existing reconciliation receipt cannot authorize active-marker cleanup."
        }
        Remove-Item -LiteralPath $markerPath -Force -ErrorAction Stop
        Write-Host "Removed the already-reconciled active quiet-merge marker for attempt $($manifest.attempt_id)."
        exit 0
    }
    throw "Immutable reconciliation receipt already exists and will not be replaced: $reconciliationPath"
}
$mergeContract = $null
$quietReportContract = $null
$activeMarkerContract = $null
$supportingActiveMarkerContract = $null
$supportingQuietReportContract = $null
$supportingPriorMarkerAbortContract = $null
$resumeMarkerContract = $null
$publicationResume = $null
$mergeReceipt = $null
$failedMergeReceiptRecovery = $false
$mergeReceiptPath = [string]$manifest.evidence.merge_receipt
if ($PSCmdlet.ParameterSetName -eq "MergeReceipt") {
    $candidateMergeReceiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $mergeReceiptPath -MaximumBytes 2097152 -ContentType Json
    $candidateMergeReceiptSha256 = [string]$candidateMergeReceiptSnapshot.Sha256
    if ($candidateMergeReceiptSha256 -ne $ExpectedMergeReceiptSha256.ToLowerInvariant()) {
        throw "Merge receipt hash mismatch. Expected $ExpectedMergeReceiptSha256; got $candidateMergeReceiptSha256"
    }
    $candidateMergeReceipt = $candidateMergeReceiptSnapshot.Payload
    if ([string]$candidateMergeReceipt.status -eq "MERGED_UNVERIFIED") {
        if ($ResumePublication.IsPresent) {
            throw "ResumePublication is invalid for a receipt that already proves publication."
        }
        $mergeContract = Assert-WeatherIntegrationMergedUnverifiedReceipt `
            -AttemptContract $contract `
            -ExpectedReceiptSha256 $ExpectedMergeReceiptSha256
    }
    elseif ([string]$candidateMergeReceipt.status -eq "FAIL") {
        # quiet_window_merge may durably record a fully recovered local commit,
        # fail to receive the one-shot push acknowledgement, and return 3. A
        # later reviewed push is recoverable only from this exact receipt/report
        # pair plus current HEAD == master == origin at the recorded commit.
        $mergeContract = Assert-WeatherReconciliationFailedMergeReceipt `
            -AttemptContract $contract `
            -ExpectedReceiptSha256 $ExpectedMergeReceiptSha256 `
            -AllowPreDocumentation:($ResumePublication.IsPresent) `
            -EvidenceSnapshot $candidateMergeReceiptSnapshot
        $failedMergeReceiptRecovery = $true
    }
    else {
        throw "Reconciliation requires a MERGED_UNVERIFIED receipt or a hash-bound FAIL receipt for a recovered unpushed commit."
    }
    $mergeReceipt = $mergeContract.Receipt
    $quietReportContract = [pscustomobject]@{
        Report = $mergeContract.QuietReport
        ReportPath = [string]$manifest.evidence.quiet_merge_report
        ReportSha256 = $mergeContract.QuietReportSha256
    }
    Assert-WeatherReconciliationQuietReport `
        -AttemptContract $contract `
        -ExpectedSha256 $mergeContract.QuietReportSha256 `
        -AllowMergedUnpushed:$failedMergeReceiptRecovery `
        -AllowPreDocumentation:($ResumePublication.IsPresent) | Out-Null
    if ($ResumePublication.IsPresent -and -not $failedMergeReceiptRecovery) {
        throw "ResumePublication requires recovered-unpushed evidence, not an acknowledged publication."
    }
}
elseif ($PSCmdlet.ParameterSetName -eq "QuietReport") {
    if (Test-Path -LiteralPath $mergeReceiptPath -PathType Leaf) {
        throw "A merge receipt exists; reconciliation must bind its exact SHA256 instead of bypassing it with report-only evidence."
    }
    # A hard kill can occur after quiet_window_merge durably records and
    # publishes its exact attempt-local report but before this parent writes
    # merge-receipt.json. The report hash is then the immutable recovery input.
    $quietReportContract = Assert-WeatherReconciliationQuietReport `
        -AttemptContract $contract `
        -ExpectedSha256 $ExpectedQuietMergeReportSha256 `
        -AllowMergedUnpushed:($ResumePublication.IsPresent) `
        -AllowPreDocumentation:($ResumePublication.IsPresent)
    if ($ResumePublication.IsPresent -and
        [string]$quietReportContract.Report.stage -ne "merged_unpushed") {
        throw "Report-only publication resume requires an exact merged_unpushed report."
    }
    Assert-WeatherIntegrationSuiteReceipt -AttemptContract $contract | Out-Null
}
else {
    $activeMarkerContract = Assert-WeatherReconciliationActiveMarker `
        -AttemptContract $contract `
        -ExpectedSha256 $ExpectedActiveMarkerSha256 `
        -AllowPreDocumentation:($ResumePublication.IsPresent)
    $quietReportContract = $activeMarkerContract
    $quietReportPath = [string]$manifest.evidence.quiet_merge_report
    if (Test-Path -LiteralPath $quietReportPath -PathType Leaf) {
        $candidateQuietReportSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path $quietReportPath -MaximumBytes 2097152 -ContentType Json
        $candidateQuietReport = $candidateQuietReportSnapshot.Payload
        if ([string]$candidateQuietReport.stage -eq "abort") {
            $supportingPriorMarkerAbortContract = `
                Assert-WeatherReconciliationPriorMarkerAbortReport `
                    -AttemptContract $contract `
                    -EvidenceSnapshot $candidateQuietReportSnapshot
        }
        else {
            if (-not $ResumePublication.IsPresent) {
                throw "A terminal quiet report exists; reconciliation must bind that stronger immutable evidence."
            }
            $supportingQuietReportContract = Assert-WeatherReconciliationQuietReport `
                -AttemptContract $contract `
                -ExpectedSha256 ([string]$candidateQuietReportSnapshot.Sha256) `
                -AllowMergedUnpushed `
                -AllowPreDocumentation `
                -EvidenceSnapshot $candidateQuietReportSnapshot
            if ([string]$supportingQuietReportContract.Report.stage -ne "merged_unpushed" -or
                [string]$supportingQuietReportContract.Report.merge_commit -ne
                    [string]$activeMarkerContract.Report.merge_commit) {
                throw "Active marker and immutable merged_unpushed report do not identify the same recovered commit."
            }
        }
    }
    if (Test-Path -LiteralPath $mergeReceiptPath -PathType Leaf) {
        if ($null -eq $supportingPriorMarkerAbortContract) {
            throw "A terminal merge receipt exists; reconciliation must bind that stronger immutable evidence."
        }
        $mergeContract = Assert-WeatherReconciliationPriorMarkerFailReceipt `
            -AttemptContract $contract `
            -AbortReportContract $supportingPriorMarkerAbortContract
        $mergeReceipt = $mergeContract.Receipt
    }
    Assert-WeatherIntegrationSuiteReceipt -AttemptContract $contract | Out-Null
}
$globalActiveMarkerPath = Join-Path `
    (Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)) `
    "data\alerts\quiet_window_merge_in_progress.json"
if ($null -eq $activeMarkerContract -and
    (Test-Path -LiteralPath $globalActiveMarkerPath -PathType Leaf)) {
    # A report/receipt is stronger immutable evidence, but it does not make the
    # global crash marker disposable. Bind its exact current bytes, require the
    # same recovered commit, record it in the receipt, and retire only after the
    # receipt is durable.
    $supportingActiveMarkerSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $globalActiveMarkerPath -MaximumBytes 2097152 -ContentType Json
    $supportingActiveMarkerContract = Assert-WeatherReconciliationActiveMarker `
        -AttemptContract $contract `
        -ExpectedSha256 ([string]$supportingActiveMarkerSnapshot.Sha256) `
        -AllowPreDocumentation `
        -EvidenceSnapshot $supportingActiveMarkerSnapshot
    if ([string]$supportingActiveMarkerContract.Report.merge_commit -ne
        [string]$quietReportContract.Report.merge_commit) {
        throw "Active crash marker does not match the immutable report/receipt commit."
    }
    if (-not $ResumePublication.IsPresent -and
        -not [bool]$quietReportContract.Report.documentation_transaction_recorded) {
        throw "Lagging documentation evidence requires reviewed ResumePublication before reconciliation."
    }
}
$repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)

if ($ResumePublication.IsPresent) {
    if ($PSCmdlet.ParameterSetName -eq "ActiveMarker") {
        $resumeMarkerContract = $activeMarkerContract
    }
    elseif ($failedMergeReceiptRecovery) {
        $resumeMarkerContract = $supportingActiveMarkerContract
    }
    elseif ($PSCmdlet.ParameterSetName -eq "QuietReport") {
        $resumeMarkerContract = $supportingActiveMarkerContract
    }
    $resumePublicationContract = if ($null -ne $supportingQuietReportContract) {
        $supportingQuietReportContract
    }
    else { $quietReportContract }
    $publicationResume = Invoke-WeatherReconciliationPublicationResume `
        -AttemptContract $contract `
        -PublicationContract $resumePublicationContract `
        -MarkerContract $resumeMarkerContract `
        -PythonBinding $pythonBinding
}

$productionHead = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "HEAD")
$masterTip = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "master")
$originMaster = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "origin/master")
$productionBranch = Invoke-WeatherReconciliationGitLine `
    -Root $repoRoot -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
if ($productionBranch -ne "master" -or $productionHead -ne $masterTip -or $masterTip -ne $originMaster) {
    throw "Reconciliation requires exact checked-out production master equal to origin/master."
}
$publishedIntegrationCommit = if ($null -ne $activeMarkerContract) {
    [string]$activeMarkerContract.Report.merge_commit
}
elseif ($null -ne $mergeReceipt -and -not $failedMergeReceiptRecovery) {
    [string]$mergeReceipt.production_head
}
else {
    [string]$quietReportContract.Report.merge_commit
}
Assert-WeatherReconciliationMergeShape `
    -RepositoryRoot $repoRoot `
    -Attempt $manifest `
    -PublicationRecord $quietReportContract.Report
Assert-WeatherReconciliationTrackedState `
    -RepositoryRoot $repoRoot `
    -PublicationRecord $quietReportContract.Report | Out-Null
Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $repoRoot `
    -Arguments @(
        "merge-base", "--is-ancestor", $publishedIntegrationCommit, $masterTip
    ) `
    -Label "reconciliation published-commit ancestry proof" | Out-Null
if (($null -ne $activeMarkerContract -or $failedMergeReceiptRecovery -or
        $ResumePublication.IsPresent) -and
    $masterTip -ne $publishedIntegrationCommit) {
    throw "Recovered-publication reconciliation requires HEAD == master == origin/master == the hash-bound merge_commit."
}
Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $repoRoot `
    -Arguments @(
        "merge-base", "--is-ancestor", [string]$manifest.expected_tip, $masterTip
    ) `
    -Label "reconciliation frozen-source ancestry proof" | Out-Null

$capture = Get-WeatherReconciliationCaptureProof `
    -PythonBinding $pythonBinding -RepositoryRoot $repoRoot
$executionTapeCurrent = $null
if ([bool]$quietReportContract.Report.execution_tape_recovery_required) {
    $executionTapeCurrent = Get-WeatherReconciliationExecutionTapeProof `
        -PythonBinding $pythonBinding -RepositoryRoot $repoRoot
}

$taskEvidence = @(Disable-WeatherIntegrationAttemptTasks -AttemptContract $contract)
$registrationIntentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $contract
$registrationIntentSha256 = Get-WeatherIntegrationFileSha256 -Path $registrationIntentPath
$registrationReceiptPath = Resolve-WeatherIntegrationPath -Path ([string]$manifest.evidence.registration_receipt)
$registrationReceiptSha256 = if (Test-Path -LiteralPath $registrationReceiptPath -PathType Leaf) {
    Get-WeatherIntegrationFileSha256 -Path $registrationReceiptPath
}
else { $null }
$publicationEvidenceKind = if ($failedMergeReceiptRecovery) {
    "failed_merge_receipt"
}
elseif ($null -ne $activeMarkerContract) {
    "active_marker"
}
elseif ($null -ne $mergeReceipt) {
    "merge_receipt"
}
else { "quiet_merge_report" }
$historicalMergeStatus = if ($failedMergeReceiptRecovery) {
    "PUBLISHED_AFTER_FAILED_PUSH_ACK"
}
elseif ($null -ne $activeMarkerContract) {
    "PUBLISHED_WITHOUT_PASS_MERGE_RECEIPT"
}
elseif ($null -ne $mergeReceipt) {
    "MERGED_UNVERIFIED"
}
else {
    "PUBLISHED_WITHOUT_MERGE_RECEIPT"
}
$missingHistoricalProofs = if ($failedMergeReceiptRecovery) {
    @("pass_merge_receipt", "original_publication_acknowledgement")
}
elseif ($null -ne $activeMarkerContract) {
    @("pass_merge_receipt", "quiet_merge_report")
}
elseif ($null -ne $mergeReceipt) {
    @(
        foreach ($proofName in @(
            "origin_master_verified",
            "source_tip_integrated",
            "capture_recovery_proved",
            "documentation_transaction_recorded"
        )) {
            if (-not [bool]$mergeReceipt.$proofName) { $proofName }
        }
    )
}
else {
    @("merge_receipt")
}
$boundMergeReceiptPath = if ($null -eq $mergeContract) { $null } else { $mergeContract.ReceiptPath }
$boundMergeReceiptSha256 = if ($null -eq $mergeContract) { $null } else { $mergeContract.ReceiptSha256 }
$boundQuietReportPath = if ($null -ne $activeMarkerContract) { $null } else { $quietReportContract.ReportPath }
$boundQuietReportSha256 = if ($null -ne $activeMarkerContract) { $null } else { $quietReportContract.ReportSha256 }
$boundActiveMarkerPath = if ($null -eq $activeMarkerContract) { $null } else { $activeMarkerContract.ReportPath }
$boundActiveMarkerSha256 = if ($null -eq $activeMarkerContract) { $null } else { $activeMarkerContract.ReportSha256 }
$markerToRetireContract = if ($null -ne $publicationResume -and
    $null -ne $publicationResume.marker) {
    $publicationResume.marker
}
elseif ($null -ne $activeMarkerContract) { $activeMarkerContract }
elseif ($null -ne $resumeMarkerContract) { $resumeMarkerContract }
elseif ($null -ne $supportingActiveMarkerContract) { $supportingActiveMarkerContract }
else { $null }
$receipt = [ordered]@{
    schema = $script:WeatherIntegrationAttemptReconciliationReceiptSchema
    status = "MERGED_RECONCILED"
    reconciled_at_local = (Get-Date).ToString("o")
    attempt_id = [string]$manifest.attempt_id
    manifest_path = $contract.ManifestPath
    manifest_sha256 = $contract.ManifestSha256
    merge_receipt_path = $boundMergeReceiptPath
    merge_receipt_sha256 = $boundMergeReceiptSha256
    quiet_merge_report_path = $boundQuietReportPath
    quiet_merge_report_sha256 = $boundQuietReportSha256
    active_marker_path = $boundActiveMarkerPath
    active_marker_sha256 = $boundActiveMarkerSha256
    publication_evidence = [ordered]@{
        kind = $publicationEvidenceKind
        merge_receipt_path = $boundMergeReceiptPath
        merge_receipt_sha256 = $boundMergeReceiptSha256
        quiet_merge_report_path = $boundQuietReportPath
        quiet_merge_report_sha256 = $boundQuietReportSha256
        active_marker_path = $boundActiveMarkerPath
        active_marker_sha256 = $boundActiveMarkerSha256
        active_marker_payload = if ($null -eq $activeMarkerContract) { $null } else { $activeMarkerContract.Report }
        active_marker_raw = if ($null -eq $activeMarkerContract) { $null } else { $activeMarkerContract.RawText }
        supporting_active_marker_path = if ($null -eq $supportingActiveMarkerContract) { $null } else { $supportingActiveMarkerContract.ReportPath }
        supporting_active_marker_sha256 = if ($null -eq $supportingActiveMarkerContract) { $null } else { $supportingActiveMarkerContract.ReportSha256 }
        supporting_active_marker_raw = if ($null -eq $supportingActiveMarkerContract) { $null } else { $supportingActiveMarkerContract.RawText }
        supporting_quiet_merge_report_path = if ($null -eq $supportingQuietReportContract) { $null } else { $supportingQuietReportContract.ReportPath }
        supporting_quiet_merge_report_sha256 = if ($null -eq $supportingQuietReportContract) { $null } else { $supportingQuietReportContract.ReportSha256 }
        supporting_prior_marker_abort_path = if ($null -eq $supportingPriorMarkerAbortContract) { $null } else { $supportingPriorMarkerAbortContract.ReportPath }
        supporting_prior_marker_abort_sha256 = if ($null -eq $supportingPriorMarkerAbortContract) { $null } else { $supportingPriorMarkerAbortContract.ReportSha256 }
        supporting_prior_marker_abort_raw = if ($null -eq $supportingPriorMarkerAbortContract) { $null } else { $supportingPriorMarkerAbortContract.RawText }
        published_integration_commit = $publishedIntegrationCommit
    }
    publication_resume = [ordered]@{
        requested = [bool]$ResumePublication.IsPresent
        performed = ($null -ne $publicationResume)
        documentation_started = if ($null -eq $publicationResume) { $false } else { [bool]$publicationResume.documentation_started }
        original_marker_path = if ($null -eq $resumeMarkerContract) { $null } else { $resumeMarkerContract.ReportPath }
        original_marker_sha256 = if ($null -eq $resumeMarkerContract) { $null } else { $resumeMarkerContract.ReportSha256 }
        original_marker_raw = if ($null -eq $resumeMarkerContract) { $null } else { $resumeMarkerContract.RawText }
        final_marker_path = if ($null -eq $markerToRetireContract -or $null -eq $publicationResume) { $null } else { $markerToRetireContract.ReportPath }
        final_marker_sha256 = if ($null -eq $markerToRetireContract -or $null -eq $publicationResume) { $null } else { $markerToRetireContract.ReportSha256 }
        final_marker_raw = if ($null -eq $markerToRetireContract -or $null -eq $publicationResume) { $null } else { $markerToRetireContract.RawText }
    }
    registration_evidence = [ordered]@{
        intent_path = $registrationIntentPath
        intent_sha256 = $registrationIntentSha256
        receipt_path = $registrationReceiptPath
        receipt_sha256 = $registrationReceiptSha256
    }
    historical_merge_status = $historicalMergeStatus
    missing_historical_proofs = $missingHistoricalProofs
    historical_proof_upgraded = $false
    downstream_authorized = $false
    review_reference = $ReviewReference
    notes = $Notes
    current_proofs = [ordered]@{
        checked_out_master_equals_origin = $true
        published_integration_commit_in_history = $true
        frozen_source_tip_in_history = $true
        capture_recovery_current = $true
        exact_merge_parents_current = $true
        execution_tape_recovery_required = [bool]$quietReportContract.Report.execution_tape_recovery_required
        execution_tape_recovery_current = (-not [bool]$quietReportContract.Report.execution_tape_recovery_required -or $null -ne $executionTapeCurrent)
        production_head = $productionHead
        origin_master = $originMaster
        capture = $capture
        execution_tape = $executionTapeCurrent
    }
    python_executions = @(
        $script:WeatherReconciliationPythonExecutions | ForEach-Object { $_ }
    )
    tasks = @($taskEvidence)
    scripts = [ordered]@{
        reconciliation = [ordered]@{
            path = $PSCommandPath
            sha256 = Get-WeatherIntegrationFileSha256 -Path $PSCommandPath
        }
        contract = [ordered]@{
            path = Join-Path $PSScriptRoot "integration_attempt_contract.ps1"
            sha256 = Get-WeatherIntegrationFileSha256 -Path (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")
        }
    }
    safety = [ordered]@{
        authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
        credential_value_access_authorized = $false
        live_exchange_mutation_authorized = $false
    }
}
Write-WeatherIntegrationImmutableJson -Path $reconciliationPath -Payload $receipt
if ($null -ne $markerToRetireContract) {
    # Receipt publication happens first. A kill before marker removal is safe:
    # rerunning with the same expected marker hash performs only the validated,
    # idempotent cleanup path above.
    if ((Get-WeatherIntegrationFileSha256 -Path $markerToRetireContract.ReportPath) -ne
        [string]$markerToRetireContract.ReportSha256) {
        throw "Active quiet-merge marker changed after reconciliation receipt publication."
    }
    Remove-Item -LiteralPath $markerToRetireContract.ReportPath -Force -ErrorAction Stop
}
Write-Host "Reconciled attempt $($manifest.attempt_id) as non-authorizing MERGED_RECONCILED evidence."
Write-Host "No historical proof was upgraded; downstream work remains blocked."
}
catch {
    $primaryError = $_
    throw
}
finally {
    $cleanupOnlyError = $null
    try {
        Exit-WeatherIntegrationControlMutex `
            -Mutex $reconciliationGitMutex -PrimaryError $primaryError
    }
    catch { $cleanupOnlyError = $_ }
    $effectivePrimary = if ($null -ne $primaryError) {
        $primaryError
    }
    else { $cleanupOnlyError }
    try {
        Exit-WeatherIntegrationControlMutex `
            -Mutex $terminalMutex -PrimaryError $effectivePrimary
    }
    catch {
        if ($null -eq $cleanupOnlyError) { $cleanupOnlyError = $_ }
        elseif ($null -ne $effectivePrimary) {
            $effectivePrimary.Exception.Data["weather_additional_cleanup_failure"] =
                $_.Exception.Message
        }
    }
    if ($null -eq $primaryError -and $null -ne $cleanupOnlyError) {
        throw $cleanupOnlyError
    }
}
