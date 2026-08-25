Set-StrictMode -Version Latest

$weatherIntegrationJobHelper = Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1"
if (-not (Test-Path -LiteralPath $weatherIntegrationJobHelper -PathType Leaf)) {
    throw "Integration remote-Git Job helper is missing: $weatherIntegrationJobHelper"
}
. $weatherIntegrationJobHelper

$script:WeatherIntegrationBlockedGitEnvironmentExact = @(
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE", "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE",
    "GIT_ATTR_SOURCE", "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS",
    "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS",
    "GIT_ALLOW_PROTOCOL", "GIT_PROTOCOL_FROM_USER",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_CONFIG", "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_NOSYSTEM", "GIT_EXEC_PATH", "GIT_SSL_NO_VERIFY",
    "GIT_SSL_CAINFO", "GIT_SSL_CAPATH", "GIT_ASKPASS", "GIT_ASKPASS_REQUIRE",
    "SSH_ASKPASS", "SSH_ASKPASS_REQUIRE", "GIT_PROXY_COMMAND", "GIT_SSH",
    "GIT_SSH_COMMAND",
    "GIT_SSH_VARIANT", "GIT_CURL_VERBOSE", "GIT_REDIRECT_STDERR",
    "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS", "GIT_PAGER", "PAGER",
    "GIT_NO_REPLACE_OBJECTS",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
    "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
    "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_MERGE_AUTOEDIT",
    "EDITOR", "VISUAL"
)
$script:WeatherIntegrationApprovedOfflineGitEnvironment = [ordered]@{
    GIT_ALLOW_PROTOCOL = "file"
    GIT_TERMINAL_PROMPT = "0"
    GIT_PROTOCOL_FROM_USER = "0"
    GIT_CONFIG_NOSYSTEM = "1"
    GIT_CONFIG_SYSTEM = "NUL"
    GIT_CONFIG_GLOBAL = "NUL"
    GIT_CONFIG_COUNT = "0"
    GIT_ATTR_NOSYSTEM = "1"
    GIT_OPTIONAL_LOCKS = "0"
}

function Get-WeatherIntegrationBlockedGitEnvironmentNames {
    $processEnvironment = [Environment]::GetEnvironmentVariables(
        [EnvironmentVariableTarget]::Process
    )
    return @(
        @($script:WeatherIntegrationBlockedGitEnvironmentExact) +
        @($processEnvironment.Keys | ForEach-Object { [string]$_ } | Where-Object {
            $_ -match '^GIT_' -or $_ -match '^GCM_'
        }) |
            Sort-Object -Unique
    )
}

function Assert-WeatherIntegrationSafeGitEnvironment {
    param([Parameter(Mandatory = $true)][string]$Phase)

    $offline = [Environment]::GetEnvironmentVariable(
        "WEATHER_INTEGRATION_TEST_OFFLINE",
        [EnvironmentVariableTarget]::Process
    ) -ceq "1"
    $blocked = New-Object System.Collections.Generic.List[string]
    foreach ($name in @(Get-WeatherIntegrationBlockedGitEnvironmentNames)) {
        $value = [Environment]::GetEnvironmentVariable(
            $name,
            [EnvironmentVariableTarget]::Process
        )
        if ($null -eq $value) { continue }
        if ($offline -and
            $script:WeatherIntegrationApprovedOfflineGitEnvironment.Contains(
                [string]$name
            )) {
            $expected = [string]$script:WeatherIntegrationApprovedOfflineGitEnvironment[
                [string]$name
            ]
            $matches = if ([string]$name -cin @(
                    "GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL"
                )) {
                [string]$value -ieq $expected
            }
            else { [string]$value -ceq $expected }
            if ($matches) { continue }
        }
        $blocked.Add([string]$name)
    }
    if ($blocked.Count -ne 0) {
        throw (
            "$Phase refuses ambient Git identity, transport, helper, or trace controls: " +
            ($blocked -join ", ")
        )
    }
}

function Assert-WeatherIntegrationRegularPathAncestry {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    $current = [IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Phase refuses reparse-point path ancestry: $current"
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ([string]::IsNullOrWhiteSpace($parent) -or
            $parent.Equals($current, [StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $current = $parent
    }
}

function Get-WeatherIntegrationGitExecutablePath {
    param(
        [Parameter(Mandatory = $true)][string]$Phase,
        [string]$ExpectedPath = ""
    )

    Assert-WeatherIntegrationSafeGitEnvironment -Phase $Phase
    $gitCommands = @(
        Get-Command git.exe -CommandType Application -All -ErrorAction Stop
    )
    if ($gitCommands.Count -eq 0) {
        throw "$Phase could not resolve git.exe as an Application."
    }
    $gitPaths = New-Object System.Collections.Generic.List[string]
    foreach ($gitCommand in $gitCommands) {
        if ([string]$gitCommand.CommandType -cne "Application" -or
            [string]::IsNullOrWhiteSpace([string]$gitCommand.Source)) {
            throw "$Phase refuses a non-Application or pathless git.exe command."
        }
        $candidatePath = [IO.Path]::GetFullPath([string]$gitCommand.Source)
        if (-not (Test-Path -LiteralPath $candidatePath -PathType Leaf)) {
            throw "$Phase resolved Git executable is missing: $candidatePath"
        }
        $candidateItem = Get-Item -LiteralPath $candidatePath -Force -ErrorAction Stop
        if ($candidateItem.PSIsContainer -or
            ($candidateItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Phase refuses a directory or reparse-point Git executable: $candidatePath"
        }
        if (@($gitPaths | Where-Object {
            $_.Equals($candidatePath, [StringComparison]::OrdinalIgnoreCase)
        }).Count -eq 0) {
            $gitPaths.Add($candidatePath)
        }
    }
    if ($gitPaths.Count -ne 1) {
        throw (
            "$Phase requires exactly one distinct regular git.exe Application path; " +
            "found $($gitPaths.Count)."
        )
    }
    $gitPath = [string]$gitPaths[0]
    Assert-WeatherIntegrationRegularPathAncestry `
        -Path $gitPath -Phase "$Phase Git executable"
    if (-not [string]::IsNullOrWhiteSpace($ExpectedPath)) {
        $expectedFullPath = [IO.Path]::GetFullPath($ExpectedPath)
        if (-not $gitPath.Equals(
            $expectedFullPath,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "$Phase resolved a different Git executable than its frozen entry identity."
        }
    }
    return $gitPath
}

function Get-WeatherIntegrationGitLfsExecutablePath {
    param(
        [Parameter(Mandatory = $true)][string]$Phase,
        [Parameter(Mandatory = $true)][string]$GitExecutable
    )

    Assert-WeatherIntegrationSafeGitEnvironment -Phase $Phase
    $resolvedGit = [IO.Path]::GetFullPath($GitExecutable)
    $gitInstallRoot = [IO.Path]::GetDirectoryName(
        [IO.Path]::GetDirectoryName($resolvedGit)
    ).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $gitInstallPrefix = $gitInstallRoot + [IO.Path]::DirectorySeparatorChar
    $commands = @(
        Get-Command git-lfs.exe -CommandType Application -All -ErrorAction Stop
    )
    if ($commands.Count -eq 0) {
        throw "$Phase could not resolve git-lfs.exe as an Application."
    }
    foreach ($command in $commands) {
        if ([string]$command.CommandType -cne "Application" -or
            [string]::IsNullOrWhiteSpace([string]$command.Source)) {
            throw "$Phase refuses a non-Application or pathless git-lfs.exe command."
        }
        $candidate = [IO.Path]::GetFullPath([string]$command.Source)
        $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
        if ($item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not $candidate.StartsWith(
                $gitInstallPrefix,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw "$Phase refuses git-lfs.exe outside the regular Git installation."
        }
    }
    # Git for Windows exposes a small cmd\git-lfs.exe dispatcher, while Git's
    # own filters resolve the real program under mingw64\bin. Bind and execute
    # that actual binary rather than merely hashing the shared dispatcher.
    $gitLfsPath = [IO.Path]::GetFullPath(
        (Join-Path $gitInstallRoot "mingw64\bin\git-lfs.exe")
    )
    if (-not (Test-Path -LiteralPath $gitLfsPath -PathType Leaf)) {
        throw "$Phase canonical Git LFS executable is missing: $gitLfsPath"
    }
    Assert-WeatherIntegrationRegularPathAncestry `
        -Path $gitLfsPath -Phase "$Phase Git LFS executable"
    return $gitLfsPath
}

function Assert-WeatherIntegrationSchedulerMutationAllowed {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "Register-ScheduledTask",
            "Enable-ScheduledTask",
            "Disable-ScheduledTask",
            "Stop-ScheduledTask",
            "Start-ScheduledTask",
            "Unregister-ScheduledTask",
            "Set-ScheduledTask"
        )]
        [string]$CommandName,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    $offline = [Environment]::GetEnvironmentVariable(
        "WEATHER_INTEGRATION_TEST_OFFLINE",
        [EnvironmentVariableTarget]::Process
    )
    if ($offline -cne "1") { return }
    $resolved = Get-Command $CommandName -ErrorAction Stop
    if ([string]$resolved.Name -cne $CommandName -or
        [string]$resolved.CommandType -cne "Function" -or
        -not [string]::IsNullOrWhiteSpace([string]$resolved.ModuleName) -or
        -not [string]::IsNullOrWhiteSpace([string]$resolved.Source) -or
        -not [string]::IsNullOrWhiteSpace([string]$resolved.ScriptBlock.File)) {
        throw (
            "$Phase refuses actual Scheduler mutation during offline integration " +
            "qualification; $CommandName must resolve directly to an in-process Function mock."
        )
    }
}

function ConvertTo-WeatherIntegrationCanonicalOriginUrl {
    param([Parameter(Mandatory = $true)][string]$Url)

    $candidate = $Url.Trim()
    if ($candidate -cnotmatch
        '^https://github\.com/(?<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?<repository>[A-Za-z0-9._-]{1,100})\.git$') {
        throw (
            "Integration origin must use the canonical credential-free GitHub HTTPS " +
            "form https://github.com/<owner>/<repository>.git."
        )
    }
    return (
        "https://github.com/$([string]$Matches.owner)/" +
        "$([string]$Matches.repository).git"
    ).ToLowerInvariant()
}

function Get-WeatherIntegrationCanonicalOriginUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [string]$ExpectedGitExecutable = "",
        [string]$ExpectedGitExecutableSha256 = ""
    )

    Assert-WeatherIntegrationSafeGitEnvironment -Phase "canonical origin inspection"
    $resolvedRoot = [IO.Path]::GetFullPath($Root)
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        throw "Integration repository root is missing: $resolvedRoot"
    }
    $originQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $resolvedRoot `
        -Arguments @("config", "--get-all", "remote.origin.url") `
        -UseEffectiveConfig `
        -ExpectedGitExecutable $ExpectedGitExecutable `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256 `
        -Label "canonical origin fetch-URL inspection"
    $rows = @($originQuery.StdoutLines)
    if ($rows.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$rows[0])) {
        throw "Integration repository must define exactly one origin fetch URL."
    }
    $originUrl = ConvertTo-WeatherIntegrationCanonicalOriginUrl -Url ([string]$rows[0])

    # `git push origin` prefers remote.origin.pushurl over the fetch URL.  URL
    # insteadOf/pushInsteadOf rules can also redirect an apparently canonical
    # command after the manifest has frozen its repository identity.  Reject
    # every effective config scope; a string comparison of remote.origin.url
    # alone is not a transport-identity proof.
    $pushUrlQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $resolvedRoot `
        -Arguments @("config", "--get-all", "remote.origin.pushurl") `
        -AllowedExitCodes @(0, 1) `
        -UseEffectiveConfig `
        -ExpectedGitExecutable $ExpectedGitExecutable `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256 `
        -Label "canonical origin push-URL inspection"
    $pushUrls = @($pushUrlQuery.StdoutLines)
    $pushUrlExit = [int]$pushUrlQuery.ExitCode
    if ($pushUrlExit -eq 0 -or $pushUrls.Count -gt 0) {
        throw "Integration repository must not define remote.origin.pushurl."
    }
    $rewriteQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $resolvedRoot `
        -Arguments @(
            "config", "--show-origin", "--show-scope", "--get-regexp",
            '^url\..*\.(insteadof|pushinsteadof)$'
        ) `
        -AllowedExitCodes @(0, 1) `
        -UseEffectiveConfig `
        -ExpectedGitExecutable $ExpectedGitExecutable `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256 `
        -Label "canonical origin URL-rewrite inspection"
    $rewrites = @($rewriteQuery.StdoutLines)
    $rewriteExit = [int]$rewriteQuery.ExitCode
    if ($rewriteExit -eq 0 -or $rewrites.Count -gt 0) {
        throw (
            "Integration repository refuses url.*.insteadOf/pushInsteadOf rules " +
            "because they can redirect the frozen origin identity."
        )
    }
    return $originUrl
}

function Assert-WeatherIntegrationCanonicalOriginUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedUrl,
        [Parameter(Mandatory = $true)][string]$Phase,
        [string]$ExpectedGitExecutable = "",
        [string]$ExpectedGitExecutableSha256 = ""
    )

    $expected = ConvertTo-WeatherIntegrationCanonicalOriginUrl -Url $ExpectedUrl
    if ($expected -cne $ExpectedUrl) {
        throw "$Phase expected origin URL is not stored in canonical form."
    }
    $actual = Get-WeatherIntegrationCanonicalOriginUrl `
        -Root $Root -ExpectedGitExecutable $ExpectedGitExecutable `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256
    if ($actual -cne $expected) {
        throw "$Phase origin URL changed after freeze. Expected $expected; got $actual"
    }
    return $actual
}

function ConvertTo-WeatherIntegrationProcessArgumentString {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$Tokens
    )

    # StartAssigned ultimately supplies one CreateProcessW command line. Encode
    # each argv token with the inverse of the standard Windows argv parser:
    # backslashes before a literal quote are doubled plus one, and trailing
    # backslashes inside a quoted token are doubled before its closing quote.
    # This is required for pinned executable config values such as
    # filter.lfs.process="C:/Program Files/Git/.../git-lfs.exe" filter-process.
    $encoded = foreach ($token in $Tokens) {
        $value = [string]$token
        if ($value.IndexOfAny([char[]]@([char]0, "`r", "`n")) -ge 0) {
            throw "Bounded child-process arguments may not contain NUL, CR, or LF."
        }
        if ($value.Length -gt 0 -and $value -notmatch '[\s"]') {
            $value
            continue
        }

        $builder = New-Object Text.StringBuilder
        [void]$builder.Append([char]'"')
        $backslashCount = 0
        foreach ($character in $value.ToCharArray()) {
            if ($character -eq [char]'\') {
                $backslashCount++
                continue
            }
            if ($character -eq [char]'"') {
                [void]$builder.Append(
                    [char]'\', ((2 * $backslashCount) + 1)
                )
                [void]$builder.Append([char]'"')
                $backslashCount = 0
                continue
            }
            if ($backslashCount -gt 0) {
                [void]$builder.Append([char]'\', $backslashCount)
                $backslashCount = 0
            }
            [void]$builder.Append($character)
        }
        if ($backslashCount -gt 0) {
            [void]$builder.Append([char]'\', (2 * $backslashCount))
        }
        [void]$builder.Append([char]'"')
        $builder.ToString()
    }
    $argumentString = $encoded -join " "
    if ($argumentString.Length -gt 30000) {
        throw "Bounded child-process command line exceeds its 30000-character bound."
    }
    return $argumentString
}

function ConvertFrom-WeatherIntegrationRetainedOutput {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes,
        [Parameter(Mandatory = $true)][string]$Label
    )

    try { return (New-Object Text.UTF8Encoding($false, $true)).GetString($Bytes) }
    catch { throw "$Label retained output is not strict UTF-8" }
}

function Get-WeatherIntegrationByteSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes
    )

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return (([BitConverter]::ToString($sha.ComputeHash($Bytes))) `
            -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Remove-WeatherIntegrationOwnedBoundedOutputRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$OutputPaths
    )

    $fullRoot = [IO.Path]::GetFullPath($Root)
    $expectedParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    if (-not [IO.Path]::GetDirectoryName($fullRoot).Equals(
        $expectedParent,
        [StringComparison]::OrdinalIgnoreCase
    ) -or [IO.Path]::GetFileName($fullRoot) -cnotmatch
        '^weather-bounded-process-[0-9a-f]{32}$') {
        throw "refusing to clean a non-owned bounded-process output root: $fullRoot"
    }
    foreach ($path in $OutputPaths) {
        $fullPath = [IO.Path]::GetFullPath($path)
        if (-not [IO.Path]::GetDirectoryName($fullPath).Equals(
            $fullRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or [IO.Path]::GetFileName($fullPath) -cnotmatch '^(stdout|stderr)\.txt$') {
            throw "refusing to clean a non-owned bounded-process output: $fullPath"
        }
        if (-not (Test-Path -LiteralPath $fullPath)) { continue }
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            throw "refusing to clean a non-file bounded-process output: $fullPath"
        }
        $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "refusing to clean a reparse-point bounded-process output: $fullPath"
        }
        Remove-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $fullPath) {
            throw "bounded-process output cleanup was not proved: $fullPath"
        }
    }
    if (-not (Test-Path -LiteralPath $fullRoot)) { return }
    if (-not (Test-Path -LiteralPath $fullRoot -PathType Container)) {
        throw "refusing to clean a non-directory bounded-process output root: $fullRoot"
    }
    $rootItem = Get-Item -LiteralPath $fullRoot -Force -ErrorAction Stop
    if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        @([IO.Directory]::EnumerateFileSystemEntries($fullRoot)).Count -ne 0) {
        throw "refusing to clean a nonempty or reparse-point bounded-process output root: $fullRoot"
    }
    Remove-Item -LiteralPath $fullRoot -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $fullRoot) {
        throw "bounded-process output-root cleanup was not proved: $fullRoot"
    }
}

function Invoke-WeatherIntegrationBoundedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 900)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)][string]$Label,
        [hashtable]$Environment = @{},
        [string[]]$RemoveEnvironmentVariables = @(),
        [int[]]$AllowedExitCodes = @(0),
        [ValidateRange(1024, 16777216)][int]$MaxOutputBytes = 1048576,
        [string]$ExpectedExecutableSha256 = ""
    )

    $resolvedWorkingDirectory = [IO.Path]::GetFullPath($WorkingDirectory)
    if (-not (Test-Path -LiteralPath $resolvedWorkingDirectory -PathType Container)) {
        throw "$Label working directory is missing: $resolvedWorkingDirectory"
    }
    $resolvedExecutable = if (Test-Path -LiteralPath $Executable -PathType Leaf) {
        [IO.Path]::GetFullPath($Executable)
    }
    else {
        $command = Get-Command $Executable -CommandType Application -ErrorAction Stop |
            Select-Object -First 1
        [string]$command.Source
    }
    $resolvedExecutable = [IO.Path]::GetFullPath($resolvedExecutable)

    $environmentNames = @(
        @($RemoveEnvironmentVariables) + @($Environment.Keys) |
            ForEach-Object { [string]$_ } |
            Sort-Object -Unique
    )
    foreach ($name in $environmentNames) {
        if ($name -cnotmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw "$Label received an unsafe environment-variable name: $name"
        }
    }
    $argumentString = ConvertTo-WeatherIntegrationProcessArgumentString -Tokens $Arguments
    $outputRoot = Join-Path ([IO.Path]::GetTempPath()) (
        "weather-bounded-process-" + [guid]::NewGuid().ToString("N")
    )
    if (Test-Path -LiteralPath $outputRoot) {
        throw "$Label unique redirected-output root already exists: $outputRoot"
    }
    try {
        [void][IO.Directory]::CreateDirectory($outputRoot)
        $outputRootItem = Get-Item -LiteralPath $outputRoot -Force -ErrorAction Stop
        if (($outputRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            @([IO.Directory]::EnumerateFileSystemEntries($outputRoot)).Count -ne 0) {
            throw "$Label redirected-output root is not a new empty regular directory"
        }
    }
    catch {
        $creationFailure = $_
        try {
            Remove-WeatherIntegrationOwnedBoundedOutputRoot `
                -Root $outputRoot -OutputPaths @()
        }
        catch {
            $creationFailure.Exception.Data["weather_cleanup_failure"] = $_.Exception.Message
            Write-Warning $_.Exception.Message -WarningAction Continue
        }
        throw $creationFailure
    }
    $stdoutPath = Join-Path $outputRoot "stdout.txt"
    $stderrPath = Join-Path $outputRoot "stderr.txt"
    $previousEnvironment = @{}
    foreach ($name in $environmentNames) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable(
            $name,
            [EnvironmentVariableTarget]::Process
        )
    }
    $environmentApplied = $false
    $job = $null
    $process = $null
    $executableIdentityStream = $null
    $executableSha256 = $null
    $primaryFailure = $null
    $observedChildExitCode = $null
    try {
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $resolvedExecutable -Phase "$Label executable identity"
        $executableIdentityStream = [IO.File]::Open(
            $resolvedExecutable,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        $executableHash = [Security.Cryptography.SHA256]::Create()
        try {
            $executableSha256 = (
                ([BitConverter]::ToString(
                    $executableHash.ComputeHash($executableIdentityStream)
                )) -replace '-', ''
            ).ToLowerInvariant()
        }
        finally { $executableHash.Dispose() }
        $executableIdentityStream.Position = 0
        if (-not [string]::IsNullOrWhiteSpace($ExpectedExecutableSha256)) {
            $expectedExecutableHash = $ExpectedExecutableSha256.Trim().ToLowerInvariant()
            if ($expectedExecutableHash -cnotmatch '^[0-9a-f]{64}$') {
                throw "$Label ExpectedExecutableSha256 is not a full lowercase SHA256."
            }
            if ($executableSha256 -cne $expectedExecutableHash) {
                throw "$Label executable changed after its caller froze the launch identity."
            }
        }
        $environmentApplied = $true
        foreach ($name in $RemoveEnvironmentVariables) {
            [Environment]::SetEnvironmentVariable(
                [string]$name,
                $null,
                [EnvironmentVariableTarget]::Process
            )
        }
        foreach ($name in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable(
                [string]$name,
                [string]$Environment[$name],
                [EnvironmentVariableTarget]::Process
            )
        }
        $job = New-WeatherKillOnCloseJob
        $process = Start-WeatherProcessInJobWithRedirectedOutput `
            -Job $job `
            -FilePath $resolvedExecutable `
            -ArgumentString $argumentString `
            -WorkingDirectory $resolvedWorkingDirectory `
            -StandardOutputPath $stdoutPath `
            -StandardErrorPath $stderrPath
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable(
                $name,
                $previousEnvironment[$name],
                [EnvironmentVariableTarget]::Process
            )
        }
        $environmentApplied = $false

        $stopwatch = [Diagnostics.Stopwatch]::StartNew()
        $terminationReason = $null
        while (-not $process.WaitForExit(200)) {
            $stdoutLength = [int64]$process.GetStandardOutputLength()
            $stderrLength = [int64]$process.GetStandardErrorLength()
            if ($stdoutLength -gt $MaxOutputBytes -or $stderrLength -gt $MaxOutputBytes) {
                $terminationReason = (
                    "exceeded its redirected-output bound of $MaxOutputBytes bytes " +
                    "(stdout=$stdoutLength stderr=$stderrLength)"
                )
                break
            }
            if ($stopwatch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                $terminationReason = "timed out after $TimeoutSeconds seconds"
                break
            }
        }
        $stopwatch.Stop()
        if ($null -ne $terminationReason) {
            $job.TerminateAndWaitForEmpty(5000)
            $job = $null
            throw (
                "$Label $terminationReason; TerminateJobObject plus the Job active-process " +
                "count proved its child process tree was terminated."
            )
        }
        $process.WaitForExit()
        $observedChildExitCode = [int]$process.ExitCode
        # The parent exit does not prove it left no helper behind. Terminate the
        # Job and prove its active-process count reached zero before reading so
        # no descendant can retain or mutate the redirected output handles.
        $job.TerminateAndWaitForEmpty(5000)
        $job = $null
        [byte[]]$stdoutBytes = $process.ReadStandardOutputBytes($MaxOutputBytes)
        [byte[]]$stderrBytes = $process.ReadStandardErrorBytes($MaxOutputBytes)
        $stdoutSha256 = Get-WeatherIntegrationByteSha256 -Bytes $stdoutBytes
        $stderrSha256 = Get-WeatherIntegrationByteSha256 -Bytes $stderrBytes
        $stdout = ConvertFrom-WeatherIntegrationRetainedOutput `
            -Bytes $stdoutBytes -Label "$Label stdout"
        $stderr = ConvertFrom-WeatherIntegrationRetainedOutput `
            -Bytes $stderrBytes -Label "$Label stderr"
        $exitCode = [int]$observedChildExitCode
        if ($AllowedExitCodes -notcontains $exitCode) {
            $diagnostic = (@($stderr, $stdout) |
                ForEach-Object { ([string]$_).Trim() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Select-Object -First 1)
            if ([string]::IsNullOrWhiteSpace([string]$diagnostic)) {
                $diagnostic = "no child diagnostic output"
            }
            if ($diagnostic.Length -gt 512) { $diagnostic = $diagnostic.Substring(0, 512) }
            throw "$Label failed with exit code ${exitCode}: $diagnostic"
        }
        return [pscustomobject]@{
            ExitCode = $exitCode
            Stdout = $stdout
            Stderr = $stderr
            StdoutLines = @($stdout -split "`r?`n" | Where-Object { $_ -ne "" })
            StdoutSha256 = $stdoutSha256
            StderrSha256 = $stderrSha256
            ExecutableSha256 = $executableSha256
        }
    }
    catch {
        $failure = $_
        if ($null -ne $observedChildExitCode -and $observedChildExitCode -ne 0) {
            $postExitMessage = $failure.Exception.Message
            $combinedException = [InvalidOperationException]::new(
                (
                    "$Label child exited with code $observedChildExitCode; " +
                    "post-exit containment or evidence processing failed: $postExitMessage"
                ),
                $failure.Exception
            )
            $combinedException.Data["weather_observed_child_exit_code"] =
                [int]$observedChildExitCode
            $combinedException.Data["weather_post_exit_failure"] = $postExitMessage
            $failure = [Management.Automation.ErrorRecord]::new(
                $combinedException,
                "WeatherIntegrationChildExitAndPostExitFailure",
                [Management.Automation.ErrorCategory]::OperationStopped,
                $null
            )
        }
        if ($null -ne $job) {
            try {
                $job.TerminateAndWaitForEmpty(5000)
                $job = $null
            }
            catch {
                $drainMessage = $_.Exception.Message
                $failure.Exception.Data["weather_tree_drain_failure"] = $drainMessage
                Write-Warning "$Label child-tree drain retry failed: $drainMessage" `
                    -WarningAction Continue
            }
        }
        $primaryFailure = $failure
        throw $failure
    }
    finally {
        $cleanupFailures = New-Object System.Collections.Generic.List[string]
        if ($environmentApplied) {
            foreach ($name in $environmentNames) {
                try {
                    [Environment]::SetEnvironmentVariable(
                        $name,
                        $previousEnvironment[$name],
                        [EnvironmentVariableTarget]::Process
                    )
                }
                catch { $cleanupFailures.Add("environment ${name}: $($_.Exception.Message)") }
            }
        }
        if ($null -ne $job) {
            try { $job.Dispose() }
            catch { $cleanupFailures.Add("Job handle: $($_.Exception.Message)") }
        }
        if ($null -ne $process) {
            try { $process.Dispose() }
            catch { $cleanupFailures.Add("retained process/output handles: $($_.Exception.Message)") }
        }
        if ($null -ne $executableIdentityStream) {
            try { $executableIdentityStream.Dispose() }
            catch { $cleanupFailures.Add("retained executable identity: $($_.Exception.Message)") }
        }
        try {
            Remove-WeatherIntegrationOwnedBoundedOutputRoot `
                -Root $outputRoot -OutputPaths @($stdoutPath, $stderrPath)
        }
        catch { $cleanupFailures.Add("output files: $($_.Exception.Message)") }
        if ($cleanupFailures.Count -ne 0) {
            $cleanupMessage = "${Label} cleanup failed: $($cleanupFailures -join ' | ')"
            if ($null -ne $primaryFailure) {
                $primaryFailure.Exception.Data["weather_cleanup_failure"] = $cleanupMessage
                Write-Warning $cleanupMessage -WarningAction Continue
            }
            elseif ($null -ne $observedChildExitCode -and $observedChildExitCode -ne 0) {
                $exitFailure = [InvalidOperationException]::new(
                    "$Label child exited with code $observedChildExitCode; $cleanupMessage"
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

function Assert-WeatherIntegrationLocalGitQueryArguments {
    param(
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $commandName = [string]$Arguments[0]
    $queryCommands = @(
        "worktree", "rev-parse", "status", "ls-files", "config",
        "symbolic-ref", "branch", "merge-base", "diff", "ls-tree",
        "check-ref-format", "rev-list", "for-each-ref", "cat-file"
    )
    # Git for Windows ultimately resolves subcommands through executable names
    # on a case-insensitive filesystem.  Require the reviewed canonical casing
    # here so a spelling such as `Config` cannot pass this allowlist and then
    # skip the case-sensitive command-specific mutation guard below.
    if ($commandName -cnotin $queryCommands) {
        throw (
            "$Label accepts only the canonical checked local Git query commands: " +
            ($queryCommands -join ", ")
        )
    }
    if ($commandName -ceq "worktree") {
        $worktreeOptions = if ($Arguments.Count -gt 2) {
            @($Arguments[2..($Arguments.Count - 1)])
        }
        else { @() }
        if ($Arguments.Count -lt 2 -or [string]$Arguments[1] -cne "list" -or
            @($worktreeOptions | Where-Object {
                [string]$_ -notin @("--porcelain")
            }).Count -ne 0) {
            throw "$Label permits only read-only 'git worktree list --porcelain' queries."
        }
    }
    if ($commandName -ceq "branch" -and
        ($Arguments.Count -ne 2 -or [string]$Arguments[1] -cne "--show-current")) {
        throw "$Label permits only the read-only 'git branch --show-current' query."
    }
    if ($commandName -ceq "symbolic-ref") {
        $symbolicTokens = if ($Arguments.Count -gt 1) {
            @($Arguments[1..($Arguments.Count - 1)])
        }
        else { @() }
        $symbolicOperands = @($symbolicTokens | Where-Object {
            -not ([string]$_).StartsWith("-")
        })
        $symbolicOptions = @($symbolicTokens | Where-Object {
            ([string]$_).StartsWith("-") -and
            [string]$_ -notin @("--quiet", "-q", "--short", "--no-recurse")
        })
        if ($symbolicOperands.Count -ne 1 -or $symbolicOptions.Count -ne 0) {
            throw "$Label permits only a read-only one-ref 'git symbolic-ref' query."
        }
    }
    if ($commandName -ceq "config") {
        $configTokens = if ($Arguments.Count -gt 1) {
            @($Arguments[1..($Arguments.Count - 1)])
        }
        else { @() }
        $queryOptions = @(
            "--get", "--get-all", "--get-regexp", "--get-urlmatch",
            "--list", "-l", "--name-only", "--show-origin", "--show-scope",
            "--null", "-z", "--fixed-value", "--includes", "--no-includes"
        )
        if (@($configTokens | Where-Object {
            ([string]$_).StartsWith("-") -and [string]$_ -notin $queryOptions
        }).Count -ne 0 -or
            @($configTokens | Where-Object {
                [string]$_ -in @(
                    "--get", "--get-all", "--get-regexp", "--get-urlmatch",
                    "--list", "-l"
                )
            }).Count -eq 0) {
            throw "$Label permits only read-only in-repository 'git config' queries."
        }
    }
    if ($commandName -ceq "diff") {
        if (@($Arguments | Where-Object {
            [string]$_ -in @("--ext-diff", "--textconv")
        }).Count -ne 0) {
            throw "$Label refuses external diff or text-conversion execution."
        }
        if (@($Arguments | Where-Object {
            [string]$_ -imatch '^--output(?:=|$)'
        }).Count -ne 0) {
            throw "$Label refuses Git diff output-file redirection."
        }
    }
    if ($commandName -ceq "cat-file" -and
        ($Arguments.Count -ne 3 -or
         [string]$Arguments[1] -cne "blob" -or
         [string]$Arguments[2] -cnotmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$')) {
        throw "$Label permits only a bounded exact-object 'git cat-file blob <oid>' query."
    }
}

function Invoke-WeatherIntegrationCheckedLocalGit {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string[]]$Arguments,
        [ValidateRange(1, 300)][int]$TimeoutSeconds = 30,
        [string]$Label = "checked local Git query",
        [int[]]$AllowedExitCodes = @(0),
        [switch]$UseEffectiveConfig,
        [string]$ExpectedGitExecutable = "",
        [string]$ExpectedGitExecutableSha256 = "",
        [ValidateRange(1024, 16777216)][int]$MaxOutputBytes = 1048576
    )

    Assert-WeatherIntegrationSafeGitEnvironment -Phase $Label
    $resolvedRoot = [IO.Path]::GetFullPath($Root)
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        throw "$Label repository root is missing: $resolvedRoot"
    }
    Assert-WeatherIntegrationLocalGitQueryArguments `
        -Arguments $Arguments -Label $Label
    $gitPath = Get-WeatherIntegrationGitExecutablePath `
        -Phase $Label -ExpectedPath $ExpectedGitExecutable
    $repositorySafety = Assert-WeatherIntegrationSafeRepositoryGitConfiguration `
        -Root $resolvedRoot -Label $Label -ExpectedGitExecutable $gitPath `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256
    $effectiveArguments = @($Arguments)
    if ([string]$effectiveArguments[0] -ceq "diff") {
        $diffTail = if ($effectiveArguments.Count -gt 1) {
            @($effectiveArguments[1..($effectiveArguments.Count - 1)])
        }
        else { @() }
        $effectiveArguments = @(
            "diff", "--no-ext-diff", "--no-textconv"
        ) + $diffTail
    }
    $gitEnvironment = @{
        GIT_NO_REPLACE_OBJECTS = "1"
        GIT_OPTIONAL_LOCKS = "0"
        LC_ALL = "C"
        LANG = "C"
    }
    if (-not $UseEffectiveConfig.IsPresent) {
        $gitEnvironment["GIT_CONFIG_NOSYSTEM"] = "1"
        $gitEnvironment["GIT_CONFIG_SYSTEM"] = "NUL"
        $gitEnvironment["GIT_CONFIG_GLOBAL"] = "NUL"
        $gitEnvironment["GIT_CONFIG_COUNT"] = "0"
    }
    $gitLfsIdentityStream = $null
    $lfsOperationFailure = $null
    try {
        $lfsOverrides = @()
        $gitLfsPath = [string]$repositorySafety.GitLfsExecutable
        if (-not [string]::IsNullOrWhiteSpace($gitLfsPath)) {
            $gitLfsIdentityStream = [IO.File]::Open(
                $gitLfsPath,
                [IO.FileMode]::Open,
                [IO.FileAccess]::Read,
                [IO.FileShare]::Read
            )
            if ($gitLfsIdentityStream.Length -le 0) {
                throw "$Label approved Git LFS executable is empty."
            }
            $quotedGitLfs = '"' + $gitLfsPath.Replace('\', '/') + '"'
            $lfsOverrides = @(
                "-c", "filter.lfs.clean=$quotedGitLfs clean -- %f",
                "-c", "filter.lfs.smudge=$quotedGitLfs smudge -- %f",
                "-c", "filter.lfs.process=$quotedGitLfs filter-process",
                "-c", "filter.lfs.required=true"
            )
        }
        return Invoke-WeatherIntegrationBoundedProcess `
            -Executable $gitPath `
            -Arguments (@(
                "--no-pager", "-C", $resolvedRoot,
                "-c", "core.fsmonitor=false",
                "-c", "core.hooksPath=NUL"
            ) + $lfsOverrides + $effectiveArguments) `
            -WorkingDirectory $resolvedRoot `
            -TimeoutSeconds $TimeoutSeconds `
            -Label $Label `
            -AllowedExitCodes $AllowedExitCodes `
            -ExpectedExecutableSha256 $ExpectedGitExecutableSha256 `
            -MaxOutputBytes $MaxOutputBytes `
            -RemoveEnvironmentVariables @(Get-WeatherIntegrationBlockedGitEnvironmentNames) `
            -Environment $gitEnvironment
    }
    catch {
        $lfsOperationFailure = $_
        throw
    }
    finally {
        if ($null -ne $gitLfsIdentityStream) {
            try { $gitLfsIdentityStream.Dispose() }
            catch {
                $lfsCleanupMessage =
                    "$Label retained Git LFS identity cleanup failed: $($_.Exception.Message)"
                if ($null -ne $lfsOperationFailure) {
                    $lfsOperationFailure.Exception.Data[
                        "weather_lfs_identity_cleanup_failure"
                    ] = $lfsCleanupMessage
                    Write-Warning $lfsCleanupMessage -WarningAction Continue
                }
                else { throw $lfsCleanupMessage }
            }
        }
    }
}

function Assert-WeatherIntegrationSafeRepositoryGitConfiguration {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$ExpectedGitExecutable = "",
        [string]$ExpectedGitExecutableSha256 = ""
    )

    Assert-WeatherIntegrationSafeGitEnvironment -Phase "$Label repository configuration"
    $resolvedRoot = [IO.Path]::GetFullPath($Root)
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        throw "$Label repository root is missing: $resolvedRoot"
    }
    $gitPath = Get-WeatherIntegrationGitExecutablePath `
        -Phase "$Label repository configuration" `
        -ExpectedPath $ExpectedGitExecutable
    $dangerousPattern = (
        '^(include(if)?\..*|' +
        'extensions\.(worktreeconfig|partialclone|objectformat|refstorage)|' +
        'core\.(hookspath|attributesfile|askpass|editor|pager|sshcommand|worktree|' +
        'alternaterefscommand|gitproxy)|' +
        'pager\..*|' +
        'sequence\.editor|commit\.gpgsign|gpg(\.ssh)?\.program|' +
        'merge\..*\.driver|filter\..*\.(clean|smudge|process|required)|' +
        'diff\.external|diff\..*\.(command|textconv)|' +
        'submodule\.recurse|fetch\.recursesubmodules|' +
        'submodule\..*\.(url|update|branch|fetchrecursesubmodules)|' +
        'protocol\..*\.allow|' +
        'remote\..*\.(promisor|partialclonefilter)|' +
        'remote\.origin\.(proxy|uploadpack|receivepack|vcs))$'
    )
    $query = Invoke-WeatherIntegrationBoundedProcess `
        -Executable $gitPath `
        -Arguments @(
            '--no-pager', '-C', $resolvedRoot, '-c', 'core.fsmonitor=false',
            'config', '--null', '--show-origin', '--show-scope',
            '--get-regexp', $dangerousPattern
        ) `
        -WorkingDirectory $resolvedRoot `
        -TimeoutSeconds 30 `
        -Label "$Label effective execution-redirect configuration" `
        -AllowedExitCodes @(0, 1) `
        -ExpectedExecutableSha256 $ExpectedGitExecutableSha256 `
        -RemoveEnvironmentVariables @(Get-WeatherIntegrationBlockedGitEnvironmentNames) `
        -Environment @{
            GIT_NO_REPLACE_OBJECTS = '1'
            GIT_OPTIONAL_LOCKS = '0'
            LC_ALL = 'C'
            LANG = 'C'
        }
    $fields = @(([string]$query.Stdout).Split([char]0))
    if ($fields.Count -eq 1 -and [string]$fields[0] -ceq '') {
        $fields = @()
    }
    elseif ($fields.Count -gt 1 -and [string]$fields[$fields.Count - 1] -ceq '') {
        $fields = @($fields[0..($fields.Count - 2)])
    }
    if (($fields.Count % 3) -ne 0) {
        throw "$Label effective Git configuration returned malformed NUL evidence."
    }
    $approvedLfsValues = @{
        'filter.lfs.clean' = 'git-lfs clean -- %f'
        'filter.lfs.smudge' = 'git-lfs smudge -- %f'
        'filter.lfs.process' = 'git-lfs filter-process'
        'filter.lfs.required' = 'true'
    }
    $observedLfsValues = @{}
    for ($index = 0; $index -lt $fields.Count; $index += 3) {
        $scope = [string]$fields[$index]
        $origin = [string]$fields[$index + 1]
        $keyValue = [string]$fields[$index + 2]
        $separator = $keyValue.IndexOf("`n", [StringComparison]::Ordinal)
        if ($separator -le 0) {
            throw "$Label effective Git configuration returned malformed key/value evidence."
        }
        $key = $keyValue.Substring(0, $separator).ToLowerInvariant()
        $value = $keyValue.Substring($separator + 1)
        if ($approvedLfsValues.ContainsKey($key) -and
            [string]$approvedLfsValues[$key] -ceq $value) {
            if ($observedLfsValues.ContainsKey($key) -and
                [string]$observedLfsValues[$key] -cne $value) {
                throw "$Label refuses conflicting duplicate Git LFS filter values."
            }
            $observedLfsValues[$key] = $value
            continue
        }
        if ($key -ceq 'diff.astextplain.textconv' -and
            $value -ceq 'astextplain' -and $scope -ceq 'system' -and
            $origin -clike 'file:*') {
            $originPath = $origin.Substring(5)
            $resolvedOrigin = (Resolve-Path -LiteralPath $originPath -ErrorAction Stop).Path
            $gitInstallRoot = [IO.Path]::GetDirectoryName(
                [IO.Path]::GetDirectoryName($gitPath)
            ).TrimEnd(
                [IO.Path]::DirectorySeparatorChar,
                [IO.Path]::AltDirectorySeparatorChar
            )
            if ($resolvedOrigin.StartsWith(
                $gitInstallRoot + [IO.Path]::DirectorySeparatorChar,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                continue
            }
        }
        throw (
            "$Label refuses effective Git execution redirect $key " +
            "from scope $scope."
        )
    }
    $gitLfsPath = $null
    if ($observedLfsValues.Count -ne 0) {
        if ($observedLfsValues.Count -ne $approvedLfsValues.Count -or
            @($approvedLfsValues.Keys | Where-Object {
                -not $observedLfsValues.ContainsKey([string]$_)
            }).Count -ne 0) {
            throw (
                "$Label refuses a partial Git LFS filter definition; clean, " +
                "smudge, process, and required=true must all be present."
            )
        }
        $gitLfsPath = Get-WeatherIntegrationGitLfsExecutablePath `
            -Phase "$Label approved Git LFS filter" -GitExecutable $gitPath
    }
    return [pscustomobject]@{
        GitExecutable = $gitPath
        GitLfsExecutable = $gitLfsPath
        LfsFilterEntryCount = [int]$observedLfsValues.Count
        DangerousEntryCount = [int]($fields.Count / 3)
    }
}

function Test-WeatherIntegrationExplicitLocalGitRemote {
    param([Parameter(Mandatory = $true)][string]$Remote)

    $candidate = $Remote.Trim()
    if ([string]::IsNullOrWhiteSpace($candidate)) { return $false }
    if ($candidate -match '^(?i:file://)') {
        try { $uri = [Uri]$candidate }
        catch { return $false }
        return (
            $uri.IsFile -and
            ([string]::IsNullOrWhiteSpace($uri.Host) -or $uri.Host -ieq "localhost")
        )
    }
    if ($candidate.StartsWith("\\")) { return $false }
    if ([IO.Path]::IsPathRooted($candidate)) { return $true }
    return $false
}

function Test-WeatherIntegrationPathAtOrBelow {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    return (
        $fullPath.Equals($fullRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $fullPath.StartsWith(
            $fullRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Test-WeatherIntegrationPathsOverlap {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    return (
        (Test-WeatherIntegrationPathAtOrBelow -Path $Left -Root $Right) -or
        (Test-WeatherIntegrationPathAtOrBelow -Path $Right -Root $Left)
    )
}

function Get-WeatherIntegrationOfflineFixtureBoundary {
    param([Parameter(Mandatory = $true)][string]$Label)

    $tempPolicy = [Environment]::GetEnvironmentVariable(
        "WEATHER_INTEGRATION_TEST_TEMP_POLICY",
        [EnvironmentVariableTarget]::Process
    )
    if ($tempPolicy -cne "system_temp_unique_v1") {
        throw "$Label offline fixture temp policy is absent or malformed."
    }
    $tempRoots = New-Object System.Collections.Generic.List[string]
    foreach ($name in @("TEMP", "TMP", "TMPDIR")) {
        $value = [Environment]::GetEnvironmentVariable(
            $name,
            [EnvironmentVariableTarget]::Process
        )
        if ([string]::IsNullOrWhiteSpace($value) -or
            [string]$value -cnotmatch '^[A-Za-z]:[\\/]') {
            throw "$Label offline fixture $name root is absent or malformed."
        }
        $tempRoots.Add([IO.Path]::GetFullPath($value).TrimEnd(
            [IO.Path]::DirectorySeparatorChar,
            [IO.Path]::AltDirectorySeparatorChar
        ))
    }
    $systemTempRoot = [string]$tempRoots[0]
    if (@($tempRoots | Where-Object {
        -not $_.Equals($systemTempRoot, [StringComparison]::OrdinalIgnoreCase)
    }).Count -ne 0) {
        throw "$Label offline fixture TEMP/TMP/TMPDIR roots disagree."
    }
    $runtimeTempRoot = [IO.Path]::GetFullPath(
        [IO.Path]::GetTempPath()
    ).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    if (-not $runtimeTempRoot.Equals(
            $systemTempRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not (Test-Path -LiteralPath $systemTempRoot -PathType Container)) {
        throw "$Label offline fixture system-temp root is not frozen and canonical."
    }
    $tempItem = Get-Item -LiteralPath $systemTempRoot -Force -ErrorAction Stop
    if (-not $tempItem.PSIsContainer -or
        ($tempItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Label offline fixture system-temp root is not a regular directory."
    }
    Assert-WeatherIntegrationRegularPathAncestry `
        -Path $systemTempRoot -Phase "$Label offline fixture system-temp root"

    $protectedRoots = New-Object System.Collections.Generic.List[string]
    foreach ($name in @(
        "WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT",
        "WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT",
        "WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT"
    )) {
        $value = [Environment]::GetEnvironmentVariable(
            $name,
            [EnvironmentVariableTarget]::Process
        )
        if ([string]::IsNullOrWhiteSpace($value) -or
            [string]$value -cnotmatch '^[A-Za-z]:[\\/]') {
            throw "$Label offline fixture protected root $name is absent or malformed."
        }
        $fullRoot = [IO.Path]::GetFullPath($value).TrimEnd(
            [IO.Path]::DirectorySeparatorChar,
            [IO.Path]::AltDirectorySeparatorChar
        )
        if (-not (Test-Path -LiteralPath $fullRoot -PathType Container)) {
            throw "$Label offline fixture protected root $name is missing."
        }
        $rootItem = Get-Item -LiteralPath $fullRoot -Force -ErrorAction Stop
        if (-not $rootItem.PSIsContainer -or
            ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label offline fixture protected root $name is not regular."
        }
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $fullRoot -Phase "$Label offline fixture protected root $name"
        if (Test-WeatherIntegrationPathsOverlap `
                -Left $systemTempRoot -Right $fullRoot) {
            throw "$Label offline fixture system-temp and protected roots overlap."
        }
        $protectedRoots.Add($fullRoot)
    }
    return [pscustomobject]@{
        SystemTempRoot = $systemTempRoot
        ProtectedRoots = @($protectedRoots)
    }
}

function Resolve-WeatherIntegrationOfflineLocalGitRemotePath {
    param(
        [Parameter(Mandatory = $true)][string]$Remote,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $candidate = $Remote.Trim()
    if ($candidate -match '^(?i:file://)') {
        try { $uri = [Uri]$candidate }
        catch { throw "$Label local file remote URI is malformed." }
        if (-not $uri.IsAbsoluteUri -or -not $uri.IsFile -or $uri.IsUnc -or
            (-not [string]::IsNullOrWhiteSpace($uri.Host) -and
             $uri.Host -ine "localhost") -or
            -not [string]::IsNullOrWhiteSpace($uri.Query) -or
            -not [string]::IsNullOrWhiteSpace($uri.Fragment)) {
            throw "$Label local file remote URI is not canonical and local."
        }
        $candidate = [string]$uri.LocalPath
    }
    if ([string]::IsNullOrWhiteSpace($candidate) -or
        [string]$candidate -cnotmatch '^[A-Za-z]:[\\/]') {
        throw "$Label requires an absolute non-device local fixture remote."
    }
    return [IO.Path]::GetFullPath($candidate).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
}

function Assert-WeatherIntegrationOfflineLocalGitFixture {
    param(
        [Parameter(Mandatory = $true)][string]$Remote,
        [Parameter(Mandatory = $true)][object]$Boundary,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $remotePath = Resolve-WeatherIntegrationOfflineLocalGitRemotePath `
        -Remote $Remote -Label $Label
    foreach ($protectedRoot in @($Boundary.ProtectedRoots)) {
        if (Test-WeatherIntegrationPathsOverlap `
                -Left $remotePath -Right ([string]$protectedRoot)) {
            throw "$Label local remote overlaps a protected repository/evidence root."
        }
    }
    if ($remotePath.Equals(
            [string]$Boundary.SystemTempRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not (Test-WeatherIntegrationPathAtOrBelow `
            -Path $remotePath -Root ([string]$Boundary.SystemTempRoot))) {
        throw "$Label local remote is outside the frozen suite system-temp root."
    }
    if (-not (Test-Path -LiteralPath $remotePath -PathType Container)) {
        throw "$Label local fixture repository is missing: $remotePath"
    }
    $remoteItem = Get-Item -LiteralPath $remotePath -Force -ErrorAction Stop
    if (-not $remoteItem.PSIsContainer -or
        ($remoteItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Label local fixture repository is not one regular non-reparse directory."
    }
    Assert-WeatherIntegrationRegularPathAncestry `
        -Path $remotePath -Phase "$Label local fixture repository"
    if (Test-Path -LiteralPath (Join-Path $remotePath ".git")) {
        throw "$Label local fixture repository must be a direct bare repository."
    }

    foreach ($required in @(
        [pscustomobject]@{ Name = "HEAD"; Type = "Leaf" },
        [pscustomobject]@{ Name = "config"; Type = "Leaf" },
        [pscustomobject]@{ Name = "objects"; Type = "Container" },
        [pscustomobject]@{ Name = "refs"; Type = "Container" }
    )) {
        $requiredPath = Join-Path $remotePath ([string]$required.Name)
        if (-not (Test-Path -LiteralPath $requiredPath -PathType $required.Type)) {
            throw "$Label local fixture repository lacks bare Git marker $($required.Name)."
        }
        $requiredItem = Get-Item -LiteralPath $requiredPath -Force -ErrorAction Stop
        if (($requiredItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label local fixture repository has a reparse-point Git marker."
        }
    }

    [int]$entryCount = 0
    [int64]$totalBytes = 0
    $pendingDirectories = [Collections.Generic.Stack[string]]::new()
    $pendingDirectories.Push($remotePath)
    while ($pendingDirectories.Count -gt 0) {
        $directory = $pendingDirectories.Pop()
        foreach ($entry in [IO.Directory]::EnumerateFileSystemEntries($directory)) {
            $entryCount++
            if ($entryCount -gt 100000) {
                throw "$Label local fixture repository exceeds its 100000-entry bound."
            }
            $entryItem = Get-Item -LiteralPath $entry -Force -ErrorAction Stop
            if (($entryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label local fixture repository contains a reparse point."
            }
            if ($entryItem.PSIsContainer) {
                # Never hand a reparse-point directory to an API that could
                # traverse it before the fixture boundary has inspected it.
                $pendingDirectories.Push([string]$entryItem.FullName)
                continue
            }
            $totalBytes += [int64]$entryItem.Length
            if ($totalBytes -gt 1073741824) {
                throw "$Label local fixture repository exceeds its 1-GiB byte bound."
            }
        }
    }
    foreach ($alternateName in @(
        "objects\info\alternates", "objects\info\http-alternates"
    )) {
        if (Test-Path -LiteralPath (Join-Path $remotePath $alternateName)) {
            throw "$Label local fixture repository contains forbidden object alternates."
        }
    }
    $hooksPath = Join-Path $remotePath "hooks"
    if (Test-Path -LiteralPath $hooksPath) {
        foreach ($hook in @([IO.Directory]::EnumerateFileSystemEntries($hooksPath))) {
            $hookItem = Get-Item -LiteralPath $hook -Force -ErrorAction Stop
            if ($hookItem.PSIsContainer -or
                ($hookItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                [IO.Path]::GetFileName($hook) -cnotmatch '\.sample$') {
                throw "$Label local fixture repository contains an active or ambiguous hook."
            }
        }
    }

    $configPath = Join-Path $remotePath "config"
    $configItem = Get-Item -LiteralPath $configPath -Force -ErrorAction Stop
    if ([int64]$configItem.Length -gt 65536) {
        throw "$Label local fixture repository config exceeds its 64-KiB bound."
    }
    $strictUtf8 = New-Object Text.UTF8Encoding($false, $true)
    try { $configText = [IO.File]::ReadAllText($configPath, $strictUtf8) }
    catch { throw "$Label local fixture repository config is not strict UTF-8." }
    $configSection = ""
    $sawBare = $false
    $sawFormat = $false
    foreach ($rawLine in @($configText -split "`r?`n")) {
        $line = ([string]$rawLine).Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or
            $line.StartsWith("#") -or $line.StartsWith(";")) { continue }
        if ($line -match '^\[(?<section>[A-Za-z0-9.-]+)\]$') {
            $configSection = ([string]$Matches.section).ToLowerInvariant()
            if ($configSection -cne "core") {
                throw "$Label local fixture repository config has a non-core section."
            }
            continue
        }
        if ($configSection -cne "core" -or
            $line -cnotmatch '^(?<key>[A-Za-z][A-Za-z0-9.-]*)\s*=\s*(?<value>.*)$') {
            throw "$Label local fixture repository config is not canonical."
        }
        $key = ([string]$Matches.key).ToLowerInvariant()
        $value = ([string]$Matches.value).Trim().ToLowerInvariant()
        if ($key -cnotin @(
            "repositoryformatversion", "filemode", "bare", "symlinks",
            "ignorecase", "precomposeunicode", "logallrefupdates"
        )) {
            throw "$Label local fixture repository config has an unsupported core key."
        }
        if ($key -ceq "bare") {
            if ($value -cne "true") {
                throw "$Label local fixture repository is not bare."
            }
            $sawBare = $true
        }
        elseif ($key -ceq "repositoryformatversion") {
            if ($value -cne "0") {
                throw "$Label local fixture repository format is unsupported."
            }
            $sawFormat = $true
        }
    }
    if (-not $sawBare -or -not $sawFormat) {
        throw "$Label local fixture repository lacks canonical bare/config evidence."
    }
    $headPath = Join-Path $remotePath "HEAD"
    $headItem = Get-Item -LiteralPath $headPath -Force -ErrorAction Stop
    if ([int64]$headItem.Length -gt 1024) {
        throw "$Label local fixture repository HEAD exceeds its bound."
    }
    try { $headText = [IO.File]::ReadAllText($headPath, $strictUtf8).Trim() }
    catch { throw "$Label local fixture repository HEAD is not strict UTF-8." }
    if ($headText -cnotmatch
            '^(?:ref: refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,192}|[0-9a-f]{40}|[0-9a-f]{64})$') {
        throw "$Label local fixture repository HEAD is not canonical."
    }
    return $remotePath
}

function Assert-WeatherIntegrationOfflineLocalRemoteArguments {
    param(
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Remote,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $commandName = [string]$Arguments[0]
    if ($commandName -cnotin @("ls-remote", "fetch", "push")) {
        throw "$Label local fixture command is not canonical."
    }
    $remoteIndex = -1
    for ($index = 1; $index -lt $Arguments.Count; $index++) {
        if ([string]$Arguments[$index] -ceq $Remote) {
            $remoteIndex = $index
            break
        }
    }
    if ($remoteIndex -lt 1) {
        throw "$Label local fixture remote operand is ambiguous."
    }
    $tail = if (($remoteIndex + 1) -lt $Arguments.Count) {
        @($Arguments[($remoteIndex + 1)..($Arguments.Count - 1)])
    }
    else { @() }
    if (@($tail | Where-Object { ([string]$_).StartsWith("-") }).Count -ne 0) {
        throw "$Label local fixture refuses options after its remote operand."
    }
    switch ($commandName) {
        "ls-remote" {
            if ($tail.Count -gt 32 -or @($tail | Where-Object {
                [string]$_ -cnotmatch
                    '^refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9._/-]{0,192}$'
            }).Count -ne 0) {
                throw "$Label local fixture ls-remote refs are not canonical."
            }
        }
        "fetch" {
            if ($tail.Count -gt 16 -or @($tail | Where-Object {
                [string]$_ -cnotmatch
                    '^\+?refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9._/-]{0,192}(?::refs/(?:remotes/origin|tags)/[A-Za-z0-9][A-Za-z0-9._/-]{0,192})?$'
            }).Count -ne 0) {
                throw "$Label local fixture fetch refspecs are not canonical."
            }
        }
        "push" {
            if ($tail.Count -lt 1 -or $tail.Count -gt 16 -or
                @($tail | Where-Object {
                    [string]$_ -cnotmatch
                        '^\+?(?:HEAD|[0-9a-f]{40}|refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,192}):refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,192}$'
                }).Count -ne 0) {
                throw "$Label local fixture push refspecs are not canonical."
            }
        }
    }
}

function Get-WeatherIntegrationRemoteOperand {
    param(
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $commandName = [string]$Arguments[0]
    $allowedLeadingOptions = switch ($commandName) {
        "ls-remote" { @("--heads", "--tags", "--refs", "--quiet", "-q") }
        "fetch" { @("--no-tags", "--tags", "--prune", "--force", "-f", "--quiet", "-q") }
        "push" { @("--force", "-f", "--dry-run", "--porcelain", "--atomic", "--quiet", "-q") }
        default { @() }
    }
    for ($index = 1; $index -lt $Arguments.Count; $index++) {
        $value = [string]$Arguments[$index]
        if ($value -ceq "--") {
            if (($index + 1) -lt $Arguments.Count) {
                return [string]$Arguments[$index + 1]
            }
            break
        }
        if ($value.StartsWith("-")) {
            if ($allowedLeadingOptions -notcontains $value) {
                throw "$Label refuses unsupported Git option before its remote: $value"
            }
            continue
        }
        return $value
    }
    throw "$Label requires an explicit remote operand."
}

function Assert-WeatherIntegrationSafeRemoteGitConfiguration {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RemoteUrl,
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$ExpectedGitExecutable = "",
        [string]$ExpectedGitExecutableSha256 = ""
    )

    $canonicalUrl = ConvertTo-WeatherIntegrationCanonicalOriginUrl -Url $RemoteUrl
    $gitPath = Get-WeatherIntegrationGitExecutablePath `
        -Phase "$Label transport configuration" `
        -ExpectedPath $ExpectedGitExecutable
    $httpQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root `
        -Arguments @("config", "--get-urlmatch", "http", $canonicalUrl) `
        -AllowedExitCodes @(0, 1) `
        -UseEffectiveConfig `
        -ExpectedGitExecutable $gitPath `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256 `
        -Label "$Label effective HTTP configuration"
    foreach ($row in @($httpQuery.StdoutLines)) {
        if ([string]$row -cnotmatch '^(?<key>[^\s]+)\s+(?<value>.*)$') {
            throw "$Label effective HTTP configuration returned an unreadable row."
        }
        $key = ([string]$Matches.key).ToLowerInvariant()
        $value = ([string]$Matches.value).Trim()
        if ($key -in @("http.proxy", "http.sslcert", "http.extraheader")) {
            throw "$Label refuses effective credential-bearing Git setting $key."
        }
        if ($key -ceq "http.sslverify" -and
            $value.ToLowerInvariant() -notin @("true", "yes", "on", "1")) {
            throw "$Label requires effective http.sslVerify to remain enabled."
        }
        if ($key -ceq "http.sslcainfo") {
            if (-not [IO.Path]::IsPathRooted($value)) {
                throw "$Label refuses a non-absolute effective http.sslCAInfo."
            }
            $resolvedCaInfo = (Resolve-Path -LiteralPath $value -ErrorAction Stop).Path
            $caItem = Get-Item -LiteralPath $resolvedCaInfo -Force -ErrorAction Stop
            $gitInstallRoot = [IO.Path]::GetDirectoryName(
                [IO.Path]::GetDirectoryName($gitPath)
            ).TrimEnd(
                [IO.Path]::DirectorySeparatorChar,
                [IO.Path]::AltDirectorySeparatorChar
            )
            $gitInstallPrefix = $gitInstallRoot + [IO.Path]::DirectorySeparatorChar
            if ($caItem.PSIsContainer -or
                ($caItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                -not $resolvedCaInfo.StartsWith(
                    $gitInstallPrefix,
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                throw "$Label refuses effective http.sslCAInfo outside the regular Git installation."
            }
        }
    }
    $proxyQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root `
        -Arguments @("config", "--get-all", "core.gitproxy") `
        -AllowedExitCodes @(0, 1) `
        -UseEffectiveConfig `
        -ExpectedGitExecutable $gitPath `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256 `
        -Label "$Label effective core.gitProxy inspection"
    if (@($proxyQuery.StdoutLines).Count -ne 0) {
        throw "$Label refuses effective core.gitProxy configuration."
    }
    $credentialQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root `
        -Arguments @("config", "--get-urlmatch", "credential", $canonicalUrl) `
        -AllowedExitCodes @(0, 1) `
        -UseEffectiveConfig `
        -ExpectedGitExecutable $gitPath `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256 `
        -Label "$Label effective credential configuration"
    $credentialHelpers = New-Object System.Collections.Generic.List[string]
    foreach ($row in @($credentialQuery.StdoutLines)) {
        if ([string]$row -cnotmatch '^(?<key>[^\s]+)\s+(?<value>.*)$') {
            throw "$Label effective credential configuration returned an unreadable row."
        }
        $credentialKey = ([string]$Matches.key).ToLowerInvariant()
        $credentialValue = ([string]$Matches.value).Trim()
        if ($credentialKey -cne "credential.helper") {
            throw "$Label refuses effective credential redirect $credentialKey."
        }
        $credentialHelpers.Add($credentialValue)
    }
    if ($credentialHelpers.Count -ne 1 -or
        $credentialHelpers[0].ToLowerInvariant() -notin @("manager", "manager-core")) {
        throw "$Label requires exactly one Git Credential Manager helper."
    }
    return [pscustomobject]@{
        GitExecutable = $gitPath
        CredentialHelper = [string]$credentialHelpers[0]
    }
}

function Assert-WeatherIntegrationOfflineRemoteGitAllowed {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $offline = [Environment]::GetEnvironmentVariable(
        "WEATHER_INTEGRATION_TEST_OFFLINE",
        [EnvironmentVariableTarget]::Process
    )
    if ($offline -cne "1") { return }
    $boundary = Get-WeatherIntegrationOfflineFixtureBoundary `
        -Label "$Label offline remote inspection"
    $remoteOperand = Get-WeatherIntegrationRemoteOperand `
        -Arguments $Arguments -Label "$Label offline remote inspection"
    if (Test-WeatherIntegrationExplicitLocalGitRemote -Remote $remoteOperand) {
        Assert-WeatherIntegrationOfflineLocalRemoteArguments `
            -Arguments $Arguments -Remote $remoteOperand `
            -Label "$Label offline remote inspection"
        Assert-WeatherIntegrationOfflineLocalGitFixture `
            -Remote $remoteOperand -Boundary $boundary `
            -Label "$Label offline remote inspection" | Out-Null
        return
    }
    if ($remoteOperand.StartsWith(".\") -or
        $remoteOperand.StartsWith("..\") -or
        $remoteOperand.StartsWith("./") -or
        $remoteOperand.StartsWith("../")) {
        throw "$Label refuses relative local-remote escape during offline qualification."
    }
    if ($remoteOperand -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
        throw "$Label refuses network or ambiguous remote Git during offline qualification."
    }
    throw (
        "$Label refuses configured remote '$remoteOperand' during offline qualification; " +
        "use one explicit absolute local path or canonical file URI to a verified fixture."
    )
}

function Invoke-WeatherIntegrationBoundedRemoteGit {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string[]]$Arguments,
        [ValidateRange(1, 900)][int]$TimeoutSeconds = 90,
        [string]$Label = "remote Git operation",
        [string]$ExpectedGitExecutable = "",
        [string]$ExpectedGitExecutableSha256 = ""
    )

    Assert-WeatherIntegrationSafeGitEnvironment -Phase $Label
    if ([string]$Arguments[0] -notin @("ls-remote", "fetch", "push")) {
        throw "The bounded remote Git helper accepts only ls-remote, fetch, or push."
    }
    Assert-WeatherIntegrationOfflineRemoteGitAllowed `
        -Root $Root -Arguments $Arguments -Label $Label
    $gitPath = Get-WeatherIntegrationGitExecutablePath `
        -Phase $Label -ExpectedPath $ExpectedGitExecutable
    $repositorySafety = Assert-WeatherIntegrationSafeRepositoryGitConfiguration `
        -Root $Root -Label $Label -ExpectedGitExecutable $gitPath `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256
    $remoteOperand = Get-WeatherIntegrationRemoteOperand `
        -Arguments $Arguments -Label $Label
    $credentialOverrides = @()
    if (-not (Test-WeatherIntegrationExplicitLocalGitRemote -Remote $remoteOperand)) {
        $canonicalUrl = Get-WeatherIntegrationCanonicalOriginUrl `
            -Root $Root -ExpectedGitExecutable $gitPath `
            -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256
        if ($remoteOperand -cne "origin") {
            $explicitUrl = ConvertTo-WeatherIntegrationCanonicalOriginUrl `
                -Url $remoteOperand
            if ($explicitUrl -cne $canonicalUrl) {
                throw "$Label refuses a non-canonical credential-bearing remote."
            }
        }
        $remoteSafety = Assert-WeatherIntegrationSafeRemoteGitConfiguration `
            -Root $Root -RemoteUrl $canonicalUrl -Label $Label `
            -ExpectedGitExecutable $gitPath `
            -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256
        $credentialOverrides = @(
            "-c", "credential.helper=",
            "-c", "credential.helper=$([string]$remoteSafety.CredentialHelper)"
        )
    }
    $gitLfsIdentityStream = $null
    $lfsOperationFailure = $null
    try {
        $lfsOverrides = @()
        $gitLfsPath = [string]$repositorySafety.GitLfsExecutable
        if (-not [string]::IsNullOrWhiteSpace($gitLfsPath)) {
            $gitLfsIdentityStream = [IO.File]::Open(
                $gitLfsPath,
                [IO.FileMode]::Open,
                [IO.FileAccess]::Read,
                [IO.FileShare]::Read
            )
            if ($gitLfsIdentityStream.Length -le 0) {
                throw "$Label approved Git LFS executable is empty."
            }
            $quotedGitLfs = '"' + $gitLfsPath.Replace('\', '/') + '"'
            $lfsOverrides = @(
                "-c", "filter.lfs.clean=$quotedGitLfs clean -- %f",
                "-c", "filter.lfs.smudge=$quotedGitLfs smudge -- %f",
                "-c", "filter.lfs.process=$quotedGitLfs filter-process",
                "-c", "filter.lfs.required=true"
            )
        }
        # Repository/configuration inspection above is intentionally bounded,
        # but it gives another process time to replace a local fixture or add
        # a receive hook.  Re-prove the complete offline remote boundary at the
        # last possible point before the Git child is created.  Online mode is
        # a no-op here.
        Assert-WeatherIntegrationOfflineRemoteGitAllowed `
            -Root $Root -Arguments $Arguments `
            -Label "$Label immediate pre-launch revalidation"
        return Invoke-WeatherIntegrationBoundedProcess `
            -Executable $gitPath `
            -Arguments (@(
                "--no-pager", "-C", ([IO.Path]::GetFullPath($Root)),
                "-c", "core.fsmonitor=false",
                "-c", "core.hooksPath=NUL"
            ) + $lfsOverrides + $credentialOverrides + $Arguments) `
            -WorkingDirectory ([IO.Path]::GetFullPath($Root)) `
            -TimeoutSeconds $TimeoutSeconds `
            -Label $Label `
            -ExpectedExecutableSha256 $ExpectedGitExecutableSha256 `
            -RemoveEnvironmentVariables @(Get-WeatherIntegrationBlockedGitEnvironmentNames) `
            -Environment @{
                GIT_CONFIG_NOSYSTEM = "1"
                GIT_CONFIG_SYSTEM = "NUL"
                GIT_CONFIG_GLOBAL = "NUL"
                GIT_CONFIG_COUNT = "0"
                GIT_TERMINAL_PROMPT = "0"
                GCM_INTERACTIVE = "Never"
                GIT_NO_REPLACE_OBJECTS = "1"
                LC_ALL = "C"
                LANG = "C"
            }
    }
    catch {
        $lfsOperationFailure = $_
        throw
    }
    finally {
        if ($null -ne $gitLfsIdentityStream) {
            try { $gitLfsIdentityStream.Dispose() }
            catch {
                $lfsCleanupMessage =
                    "$Label retained Git LFS identity cleanup failed: $($_.Exception.Message)"
                if ($null -ne $lfsOperationFailure) {
                    $lfsOperationFailure.Exception.Data[
                        "weather_lfs_identity_cleanup_failure"
                    ] = $lfsCleanupMessage
                    Write-Warning $lfsCleanupMessage -WarningAction Continue
                }
                else { throw $lfsCleanupMessage }
            }
        }
    }
}

function Invoke-WeatherIntegrationCanonicalLsRemote {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedUrl,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string[]]$RemoteRefs,
        [ValidateRange(1, 900)][int]$TimeoutSeconds = 90,
        [string]$Label = "canonical remote Git query",
        [string]$ExpectedGitExecutable = "",
        [string]$ExpectedGitExecutableSha256 = ""
    )

    Assert-WeatherIntegrationSafeGitEnvironment -Phase $Label
    # Refuse the explicit network URL before resolving or starting Git. The
    # offline qualification boundary must not need a Git subprocess merely to
    # discover that a canonical remote query would contact the network.
    Assert-WeatherIntegrationOfflineRemoteGitAllowed `
        -Root $Root `
        -Arguments (@("ls-remote", "--heads", $ExpectedUrl) + $RemoteRefs) `
        -Label $Label
    $canonicalUrl = Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root $Root -ExpectedUrl $ExpectedUrl -Phase $Label `
        -ExpectedGitExecutable $ExpectedGitExecutable `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256
    $gitPath = Get-WeatherIntegrationGitExecutablePath `
        -Phase $Label -ExpectedPath $ExpectedGitExecutable
    $remoteSafety = Assert-WeatherIntegrationSafeRemoteGitConfiguration `
        -Root $Root -RemoteUrl $canonicalUrl -Label $Label `
        -ExpectedGitExecutable $gitPath `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256
    foreach ($remoteRef in $RemoteRefs) {
        if ([string]$remoteRef -cnotmatch '^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,192}$') {
            throw "$Label received an unsafe exact remote ref: $remoteRef"
        }
    }

    # Query the frozen URL outside every repository and without system/global
    # Git configuration. This makes the acknowledgement independent of
    # remote names, pushurl, include files, and URL rewrite rules while keeping
    # the ordinary in-repository checks above as a separate fail-closed gate.
    $queryRoot = Join-Path ([IO.Path]::GetTempPath()) (
        "weather-canonical-ls-remote-" + [Guid]::NewGuid().ToString("N")
    )
    $primaryFailure = $null
    $queryRootCreated = $false
    try {
        if (Test-Path -LiteralPath $queryRoot) {
            throw "$Label unique canonical query root already exists"
        }
        New-Item -ItemType Directory -Path $queryRoot -ErrorAction Stop | Out-Null
        $queryRootCreated = $true
        $queryItem = Get-Item -LiteralPath $queryRoot -Force -ErrorAction Stop
        if (($queryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            @([IO.Directory]::EnumerateFileSystemEntries($queryRoot)).Count -ne 0) {
            throw "$Label canonical query root is not a new empty regular directory"
        }
        return Invoke-WeatherIntegrationBoundedProcess `
            -Executable $gitPath `
            -Arguments (@(
                "--no-pager",
                "-c", "core.fsmonitor=false",
                "-c", "core.hooksPath=NUL",
                "-c", "credential.helper=$($remoteSafety.CredentialHelper)",
                "ls-remote", "--heads", $canonicalUrl
            ) + $RemoteRefs) `
            -WorkingDirectory $queryRoot `
            -TimeoutSeconds $TimeoutSeconds `
            -Label $Label `
            -ExpectedExecutableSha256 $ExpectedGitExecutableSha256 `
            -RemoveEnvironmentVariables @(
                Get-WeatherIntegrationBlockedGitEnvironmentNames
            ) `
            -Environment @{
                GIT_TERMINAL_PROMPT = "0"
                GCM_INTERACTIVE = "Never"
                # An explicit Windows device GIT_DIR disables repository
                # discovery for this config-independent query. Even if the
                # ephemeral working-directory namespace is replaced, Git
                # cannot load a newly introduced local repository config.
                GIT_DIR = "NUL"
                GIT_CONFIG_NOSYSTEM = "1"
                GIT_CONFIG_SYSTEM = "NUL"
                GIT_CONFIG_GLOBAL = "NUL"
                GIT_CONFIG_COUNT = "0"
                GIT_NO_REPLACE_OBJECTS = "1"
                LC_ALL = "C"
                LANG = "C"
            }
    }
    catch {
        $primaryFailure = $_
        throw
    }
    finally {
        $cleanupFailure = $null
        try {
            $fullQueryRoot = [IO.Path]::GetFullPath($queryRoot)
            $expectedParent = [IO.Path]::GetFullPath(
                [IO.Path]::GetTempPath()
            ).TrimEnd(
                [IO.Path]::DirectorySeparatorChar,
                [IO.Path]::AltDirectorySeparatorChar
            )
            if (-not [IO.Path]::GetDirectoryName($fullQueryRoot).Equals(
                $expectedParent,
                [StringComparison]::OrdinalIgnoreCase
            ) -or [IO.Path]::GetFileName($fullQueryRoot) -cnotmatch
                '^weather-canonical-ls-remote-[0-9a-f]{32}$') {
                throw "refusing to clean a non-owned canonical query root: $fullQueryRoot"
            }
            if ($queryRootCreated -and (Test-Path -LiteralPath $fullQueryRoot)) {
                if (-not (Test-Path -LiteralPath $fullQueryRoot -PathType Container)) {
                    throw "canonical query cleanup target is not a directory: $fullQueryRoot"
                }
                $cleanupItem = Get-Item -LiteralPath $fullQueryRoot -Force -ErrorAction Stop
                if (($cleanupItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                    @([IO.Directory]::EnumerateFileSystemEntries($fullQueryRoot)).Count -ne 0) {
                    throw "canonical query cleanup target is nonempty or a reparse point"
                }
                Remove-Item -LiteralPath $fullQueryRoot -Force -ErrorAction Stop
                if (Test-Path -LiteralPath $fullQueryRoot) {
                    throw "canonical query-root cleanup was not proved: $fullQueryRoot"
                }
            }
        }
        catch { $cleanupFailure = $_ }
        if ($null -ne $cleanupFailure) {
            if ($null -ne $primaryFailure) {
                $primaryFailure.Exception.Data["weather_cleanup_failure"] =
                    $cleanupFailure.Exception.Message
                Write-Warning $cleanupFailure.Exception.Message -WarningAction Continue
            }
            else { throw $cleanupFailure }
        }
    }
}

function Get-WeatherIntegrationCanonicalRemoteTip {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedUrl,
        [Parameter(Mandatory = $true)][string]$RemoteRef,
        [switch]$AllowMissing,
        [ValidateRange(1, 900)][int]$TimeoutSeconds = 90,
        [string]$Label = "canonical remote Git ref query",
        [string]$ExpectedGitExecutable = "",
        [string]$ExpectedGitExecutableSha256 = ""
    )

    $query = Invoke-WeatherIntegrationCanonicalLsRemote `
        -Root $Root -ExpectedUrl $ExpectedUrl -RemoteRefs @($RemoteRef) `
        -TimeoutSeconds $TimeoutSeconds -Label $Label `
        -ExpectedGitExecutable $ExpectedGitExecutable `
        -ExpectedGitExecutableSha256 $ExpectedGitExecutableSha256
    $rows = @($query.StdoutLines)
    if ($rows.Count -eq 0 -and $AllowMissing.IsPresent) { return $null }
    if ($rows.Count -ne 1) {
        throw "$Label did not return exactly one remote ref."
    }
    $columns = @(([string]$rows[0]).Trim() -split "`t")
    if ($columns.Count -ne 2 -or
        [string]$columns[0] -cnotmatch '^[0-9a-f]{40}$' -or
        [string]$columns[1] -cne $RemoteRef) {
        throw "$Label returned malformed or substituted remote-ref evidence."
    }
    return ([string]$columns[0]).ToLowerInvariant()
}
