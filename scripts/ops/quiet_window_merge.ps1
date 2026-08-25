# Merge a validated topic branch into master during the quiet window, verifying that the
# capture fleet survives the code roll BEFORE anything is published.
#
#   .\scripts\ops\quiet_window_merge.ps1 -Branch origin/codex/... `
#       [-ExpectedTip <full-commit-sha>] [-ExpectedBaseline <full-master-sha>] `
#       [-Force] [-DryRun] [-OwnerApprovedException <one-time-token>]
#
# Why this exists: merging a branch that touches modules the capture loops have imported
# makes the supervisors readopt the new code (STALE_CODE restart). If that code is bad,
# capture dies. Doing the merge locally first, proving capture recovers, and only then
# publishing means a bad merge is undone by resetting to the exact pre-merge commit with nothing
# published and no history to rewrite.
#
# Refuses to run outside 01:00-04:00 without -Force: a roll inside the 12:00-18:00 graded
# window can cost the streak day. See docs/ops/streak-soak.md.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [string]$ExpectedTip = "",
    [string]$ExpectedBaseline = "",
    [string]$ExpectedOriginUrl = "",
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$AttemptReportPath = "",
    [string]$ExpectedSelfSha256 = "",
    [string]$ExpectedRemoteGitSha256 = "",
    [string]$ExpectedJobContainmentSha256 = "",
    [string]$ExpectedWorkloadAdmissionSha256 = "",
    [string]$ExpectedQuietMergePreflightSha256 = "",
    [string]$ExpectedRollVerdictSha256 = "",
    [string]$ExpectedGitExecutableSha256 = "",
    [string]$ExpectedGitLfsExecutableSha256 = "",
    [string]$ExpectedPythonExecutableSha256 = "",
    [string]$OwnerApprovedException = "",
    [switch]$RequireLiveOrigin,
    [switch]$Force,
    [switch]$DryRun,
    [int]$SettleSeconds = 300,
    [ValidateRange(60, 3600)][int]$RollbackRecoverySeconds = 1200
)

$ErrorActionPreference = "Stop"
function Get-WeatherQuietMergeScheduleLocalNow {
    try {
        $timeZone = [TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
    }
    catch {
        throw "Quiet merge cannot resolve the canonical America/Toronto Windows time zone."
    }
    if ([string]$timeZone.Id -cne "Eastern Standard Time") {
        throw "Quiet merge resolved an unexpected schedule time zone."
    }
    return [datetime]::SpecifyKind(
        [TimeZoneInfo]::ConvertTime([datetimeoffset]::UtcNow, $timeZone).DateTime,
        [DateTimeKind]::Unspecified
    )
}

function Assert-WeatherQuietMergeRegularPathAncestry {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $current = [IO.DirectoryInfo]::new((Split-Path -Parent $resolvedPath))
    while ($null -ne $current) {
        $expectedDirectory = [IO.Path]::GetFullPath([string]$current.FullName)
        $item = Get-Item -LiteralPath $expectedDirectory -Force -ErrorAction Stop
        if (-not $item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            [IO.Path]::GetFullPath([string]$item.FullName) -ine $expectedDirectory) {
            throw "$Label has a missing, non-directory, or reparse-point ancestor: $expectedDirectory"
        }
        $current = $current.Parent
    }
}

function Open-WeatherQuietMergePinnedScript {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$ExpectedSha256 = "",
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1, 16777216)][int]$MaximumBytes = 8388608
    )

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $expected = $ExpectedSha256.Trim().ToLowerInvariant()
    if ($expected -and $expected -cnotmatch '^[0-9a-f]{64}$') {
        throw "$Label expected SHA256 must be exactly 64 lowercase hexadecimal characters."
    }
    $stream = $null
    $primaryError = $null
    try {
        Assert-WeatherQuietMergeRegularPathAncestry `
            -Path $resolvedPath -Label $Label
        $item = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction Stop
        if ($item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            [IO.Path]::GetFullPath([string]$item.FullName) -ine $resolvedPath) {
            throw "$Label must be one exact regular non-reparse script."
        }
        # The script may be opened for execution, but no writer/deleter can
        # replace this generation until the retained handle is disposed.
        $stream = [IO.FileStream]::new(
            $resolvedPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        # Repeat after the open so an ancestor swap during path resolution is
        # detected before this retained generation can become authoritative.
        Assert-WeatherQuietMergeRegularPathAncestry `
            -Path $resolvedPath -Label $Label
        $openedItem = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction Stop
        if ($openedItem.PSIsContainer -or
            ($openedItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            [IO.Path]::GetFullPath([string]$openedItem.FullName) -ine $resolvedPath -or
            $stream.Length -le 0 -or $stream.Length -gt $MaximumBytes) {
            throw "$Label changed identity or exceeds its bounded script contract."
        }
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $actual = ([BitConverter]::ToString(
                $sha.ComputeHash($stream)
            ) -replace '-', '').ToLowerInvariant()
        }
        finally { $sha.Dispose() }
        if ($expected -and $actual -cne $expected) {
            throw "$Label changed after its immutable dependency binding was frozen."
        }
        return [pscustomobject]@{
            Path = $resolvedPath
            Sha256 = $actual
            Stream = $stream
            Label = $Label
        }
    }
    catch {
        $primaryError = $_
        if ($null -ne $stream) {
            try { $stream.Dispose() }
            catch {
                $primaryError.Exception.Data["weather_cleanup_failure"] =
                    "$Label retained-handle cleanup failed: $($_.Exception.Message)"
            }
        }
        throw $primaryError
    }
}

function Get-WeatherQuietBytesSha256 {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return (([BitConverter]::ToString($sha.ComputeHash($Bytes))) `
            -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function ConvertFrom-WeatherQuietStrictUtf8Bytes {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $offset = if (
        $Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and
        $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF
    ) { 3 } else { 0 }
    try {
        $decoder = New-Object Text.UTF8Encoding($false, $true)
        return $decoder.GetString($Bytes, $offset, $Bytes.Length - $offset)
    }
    catch { throw "$Label is not strict UTF-8: $($_.Exception.Message)" }
}

function Read-WeatherQuietRetainedSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1, 16777216)][int]$MaximumBytes = 2097152,
        [switch]$Json
    )

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $stream = $null
    $primaryError = $null
    try {
        Assert-WeatherQuietMergeRegularPathAncestry `
            -Path $resolvedPath -Label $Label
        $item = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction Stop
        if ($item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            [IO.Path]::GetFullPath([string]$item.FullName) -ine $resolvedPath) {
            throw "$Label is not one exact regular file."
        }
        $stream = [IO.FileStream]::new(
            $resolvedPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read,
            4096,
            [IO.FileOptions]::SequentialScan
        )
        Assert-WeatherQuietMergeRegularPathAncestry `
            -Path $resolvedPath -Label $Label
        $openedItem = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction Stop
        if ($openedItem.PSIsContainer -or
            ($openedItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            [IO.Path]::GetFullPath([string]$openedItem.FullName) -ine $resolvedPath -or
            $stream.Length -le 0 -or $stream.Length -gt $MaximumBytes) {
            throw "$Label changed identity or exceeds its retained byte bound."
        }
        [byte[]]$bytes = New-Object byte[] ([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $read = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($read -le 0) { throw "$Label ended during its retained read." }
            $offset += $read
        }
        if ($stream.Position -ne $stream.Length) {
            throw "$Label retained read did not consume the exact file generation."
        }
        $text = ConvertFrom-WeatherQuietStrictUtf8Bytes -Bytes $bytes -Label $Label
        $payload = $null
        if ($Json.IsPresent) {
            try { $payload = $text | ConvertFrom-Json -ErrorAction Stop }
            catch { throw "$Label is not exact JSON: $($_.Exception.Message)" }
            if ($null -eq $payload -or $payload -is [Array]) {
                throw "$Label must contain exactly one JSON object."
            }
        }
        return [pscustomobject]@{
            Path = $resolvedPath
            Bytes = $bytes
            Length = [long]$bytes.Length
            Sha256 = Get-WeatherQuietBytesSha256 -Bytes $bytes
            Text = $text
            Payload = $payload
        }
    }
    catch {
        $primaryError = $_
        throw
    }
    finally {
        if ($null -ne $stream) {
            try { $stream.Dispose() }
            catch {
                $cleanupMessage = "$Label retained handle cleanup failed: $($_.Exception.Message)"
                if ($null -ne $primaryError) {
                    $primaryError.Exception.Data["weather_cleanup_failure"] =
                        $cleanupMessage
                    Write-Warning $cleanupMessage -WarningAction Continue
                }
                else { throw $cleanupMessage }
            }
        }
    }
}

function Write-WeatherQuietImmutableJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$JsonText,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1, 16777216)][int]$MaximumBytes = 2097152
    )

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    Assert-WeatherQuietMergeRegularPathAncestry `
        -Path $resolvedPath -Label $Label
    if (Test-Path -LiteralPath $resolvedPath) {
        throw "$Label is immutable and already exists: $resolvedPath"
    }
    $encoder = New-Object Text.UTF8Encoding($false, $true)
    [byte[]]$bytes = $encoder.GetBytes($JsonText)
    if ($bytes.Length -le 0 -or $bytes.Length -gt $MaximumBytes) {
        throw "$Label encoded byte count is outside its immutable bound."
    }
    $expectedSha256 = Get-WeatherQuietBytesSha256 -Bytes $bytes
    $stream = $null
    $primaryError = $null
    try {
        # Create the authoritative destination itself. A crash can leave an
        # invalid partial file, but it can never expose a valid-looking older
        # generation or overwrite evidence from an earlier attempt.
        $stream = [IO.FileStream]::new(
            $resolvedPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::Read,
            4096,
            [IO.FileOptions]::WriteThrough
        )
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        Assert-WeatherQuietMergeRegularPathAncestry `
            -Path $resolvedPath -Label $Label
        $item = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction Stop
        if ($item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            [IO.Path]::GetFullPath([string]$item.FullName) -ine $resolvedPath -or
            $stream.Length -ne $bytes.Length) {
            throw "$Label did not retain the exact newly created byte generation."
        }
        $stream.Position = 0
        [byte[]]$readback = New-Object byte[] ([int]$bytes.Length)
        $offset = 0
        while ($offset -lt $readback.Length) {
            $read = $stream.Read(
                $readback,
                $offset,
                $readback.Length - $offset
            )
            if ($read -le 0) { throw "$Label ended during same-handle readback." }
            $offset += $read
        }
        $readbackText = ConvertFrom-WeatherQuietStrictUtf8Bytes `
            -Bytes $readback -Label $Label
        try { $payload = $readbackText | ConvertFrom-Json -ErrorAction Stop }
        catch { throw "$Label same-handle bytes are not exact JSON: $($_.Exception.Message)" }
        if ($null -eq $payload -or $payload -is [Array] -or
            (Get-WeatherQuietBytesSha256 -Bytes $readback) -cne $expectedSha256 -or
            $readbackText -cne $JsonText) {
            throw "$Label same-handle hash, text, or JSON readback disagrees."
        }
        return [pscustomobject]@{
            Path = $resolvedPath
            Length = [long]$readback.Length
            Sha256 = $expectedSha256
            Text = $readbackText
            Payload = $payload
        }
    }
    catch {
        $primaryError = $_
        throw
    }
    finally {
        if ($null -ne $stream) {
            try { $stream.Dispose() }
            catch {
                $cleanupMessage = "$Label retained write/read handle cleanup failed: $($_.Exception.Message)"
                if ($null -ne $primaryError) {
                    $primaryError.Exception.Data["weather_cleanup_failure"] =
                        $cleanupMessage
                    Write-Warning $cleanupMessage -WarningAction Continue
                }
                else { throw $cleanupMessage }
            }
        }
    }
}

$quietPinnedScripts = New-Object System.Collections.Generic.List[object]
$selfPin = Open-WeatherQuietMergePinnedScript `
    -Path $PSCommandPath `
    -ExpectedSha256 $ExpectedSelfSha256 `
    -Label "quiet-window merge script"
$quietPinnedScripts.Add($selfPin)
$jobContainmentPin = Open-WeatherQuietMergePinnedScript `
    -Path (Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1") `
    -ExpectedSha256 $ExpectedJobContainmentSha256 `
    -Label "quiet-window Job-containment dependency"
$quietPinnedScripts.Add($jobContainmentPin)
$powerShellExecutable = [IO.Path]::GetFullPath(
    [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
)
$powerShellExecutablePin = Open-WeatherQuietMergePinnedScript `
    -Path $powerShellExecutable `
    -Label "quiet-window PowerShell executable" `
    -MaximumBytes 16777216
$quietPinnedScripts.Add($powerShellExecutablePin)
$remoteGitPin = Open-WeatherQuietMergePinnedScript `
    -Path (Join-Path $PSScriptRoot "integration_attempt_remote_git.ps1") `
    -ExpectedSha256 $ExpectedRemoteGitSha256 `
    -Label "quiet-window remote-Git dependency"
$quietPinnedScripts.Add($remoteGitPin)
. $remoteGitPin.Path
Assert-WeatherIntegrationSafeGitEnvironment -Phase "quiet-window merge entry"
$gitExecutable = Get-WeatherIntegrationGitExecutablePath `
    -Phase "quiet-window merge entry"
$gitExecutablePin = Open-WeatherQuietMergePinnedScript `
    -Path $gitExecutable `
    -ExpectedSha256 $ExpectedGitExecutableSha256 `
    -Label "quiet-window Git executable" `
    -MaximumBytes 16777216
$quietPinnedScripts.Add($gitExecutablePin)
$gitLfsExecutable = Get-WeatherIntegrationGitLfsExecutablePath `
    -Phase "quiet-window Git LFS executable" `
    -GitExecutable $gitExecutable
$gitLfsExecutablePin = Open-WeatherQuietMergePinnedScript `
    -Path $gitLfsExecutable `
    -ExpectedSha256 $ExpectedGitLfsExecutableSha256 `
    -Label "quiet-window Git LFS executable" `
    -MaximumBytes 16777216
$quietPinnedScripts.Add($gitLfsExecutablePin)
$repo = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
Assert-WeatherQuietMergeRegularPathAncestry `
    -Path $repo -Label "quiet-window repository root"
Assert-WeatherIntegrationSafeRepositoryGitConfiguration `
    -Root $repo -Label "quiet-window merge entry" `
    -ExpectedGitExecutable $gitExecutable `
    -ExpectedGitExecutableSha256 ([string]$gitExecutablePin.Sha256) | Out-Null

# Freeze the repository-local Git configuration generation before any Git
# read or mutation can influence the merge. System/global configuration is
# suppressed for every actual operation; the frozen user identity below is
# passed explicitly so commits do not need ambient config. Includes and
# worktree-specific config are rejected by the shared safe-config validator.
$quietGitConfigQuery = Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $repo `
    -Arguments @("rev-parse", "--git-path", "config") `
    -ExpectedGitExecutable $gitExecutable `
    -ExpectedGitExecutableSha256 ([string]$gitExecutablePin.Sha256) `
    -Label "quiet-window repository config-path query"
$quietGitConfigRows = @($quietGitConfigQuery.StdoutLines)
if ($quietGitConfigRows.Count -ne 1 -or
    [string]::IsNullOrWhiteSpace([string]$quietGitConfigRows[0])) {
    throw "quiet-window repository config-path query did not return one path"
}
$quietGitConfigPath = [string]$quietGitConfigRows[0]
if (-not [IO.Path]::IsPathRooted($quietGitConfigPath)) {
    $quietGitConfigPath = Join-Path $repo $quietGitConfigPath
}
$quietGitConfigPath = [IO.Path]::GetFullPath($quietGitConfigPath)
$quietGitDirectory = [IO.Path]::GetFullPath((Join-Path $repo ".git"))
Assert-WeatherQuietMergeRegularPathAncestry `
    -Path $quietGitDirectory -Label "quiet-window ordinary .git directory"
$quietGitDirectoryItem = Get-Item -LiteralPath $quietGitDirectory `
    -Force -ErrorAction Stop
if (-not $quietGitDirectoryItem.PSIsContainer -or
    ($quietGitDirectoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "quiet-window merge requires .git to be one ordinary regular directory"
}
$expectedQuietGitConfigPath = [IO.Path]::GetFullPath(
    (Join-Path $quietGitDirectory "config")
)
if (-not $quietGitConfigPath.Equals(
        $expectedQuietGitConfigPath,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw (
        "quiet-window merge requires one ordinary in-tree .git directory; " +
        "Git resolved its config outside that identity: $quietGitConfigPath"
    )
}
$quietGitConfigPin = Open-WeatherQuietMergePinnedScript `
    -Path $quietGitConfigPath `
    -Label "quiet-window repository-local Git configuration" `
    -MaximumBytes 4194304
$quietPinnedScripts.Add($quietGitConfigPin)

$quietGitForbiddenControlPaths = @(
    (Join-Path $quietGitDirectory "commondir"),
    (Join-Path $quietGitDirectory "objects\info\alternates"),
    (Join-Path $quietGitDirectory "info\grafts")
) | ForEach-Object { [IO.Path]::GetFullPath($_) }
foreach ($forbiddenPath in $quietGitForbiddenControlPaths) {
    if (Test-Path -LiteralPath $forbiddenPath) {
        throw (
            "quiet-window merge refuses redirected Git object/ref authority: " +
            $forbiddenPath
        )
    }
}

$quietGitInfoAttributesQuery = Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $repo `
    -Arguments @("rev-parse", "--git-path", "info/attributes") `
    -ExpectedGitExecutable $gitExecutable `
    -ExpectedGitExecutableSha256 ([string]$gitExecutablePin.Sha256) `
    -Label "quiet-window repository info-attributes path query"
$quietGitInfoAttributesRows = @($quietGitInfoAttributesQuery.StdoutLines)
if ($quietGitInfoAttributesRows.Count -ne 1 -or
    [string]::IsNullOrWhiteSpace([string]$quietGitInfoAttributesRows[0])) {
    throw "quiet-window info-attributes path query did not return one path"
}
$quietGitInfoAttributesPath = [string]$quietGitInfoAttributesRows[0]
if (-not [IO.Path]::IsPathRooted($quietGitInfoAttributesPath)) {
    $quietGitInfoAttributesPath = Join-Path $repo $quietGitInfoAttributesPath
}
$quietGitInfoAttributesPath = [IO.Path]::GetFullPath($quietGitInfoAttributesPath)
$expectedQuietGitInfoAttributesPath = [IO.Path]::GetFullPath(
    (Join-Path $quietGitDirectory "info\attributes")
)
if (-not $quietGitInfoAttributesPath.Equals(
        $expectedQuietGitInfoAttributesPath,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw (
        "quiet-window merge refuses redirected repository info/attributes " +
        "authority: $quietGitInfoAttributesPath"
    )
}
if (Test-Path -LiteralPath $quietGitInfoAttributesPath) {
    throw (
        "quiet-window merge refuses repository-local info/attributes because " +
        "it is untracked executable Git behavior: $quietGitInfoAttributesPath"
    )
}

function Get-WeatherQuietGitIdentityValue {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("user.name", "user.email")]
        [string]$Key
    )

    $query = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repo `
        -Arguments @("config", "--get", $Key) `
        -UseEffectiveConfig `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 ([string]$gitExecutablePin.Sha256) `
        -Label "quiet-window frozen $Key query"
    $rows = @($query.StdoutLines)
    if ($rows.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$rows[0]) -or
        ([string]$rows[0]).IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0) {
        throw "quiet-window merge requires one safe configured $Key value"
    }
    return [string]$rows[0]
}

$script:quietGitExecutable = $gitExecutable
$script:quietGitExecutableSha256 = [string]$gitExecutablePin.Sha256
$script:quietGitLfsExecutable = $gitLfsExecutable
$script:quietGitConfigPin = $quietGitConfigPin
$script:quietGitInfoAttributesPath = $quietGitInfoAttributesPath
$script:quietGitForbiddenControlPaths = @($quietGitForbiddenControlPaths)
$script:quietGitAuthorName = Get-WeatherQuietGitIdentityValue -Key "user.name"
$script:quietGitAuthorEmail = Get-WeatherQuietGitIdentityValue -Key "user.email"

function Assert-WeatherQuietGitArguments {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $command = [string]$Arguments[0]
    $safeRef = '^(?:HEAD|master|origin/master|MERGE_HEAD|[0-9a-f]{40}(?:\^[12])?|(?:refs/remotes/)?origin/[A-Za-z0-9][A-Za-z0-9._/-]{0,192}(?:\^\{commit\})?)$'
    switch ($command) {
        "rev-parse" {
            if ($Arguments.Count -eq 3 -and
                [string]$Arguments[1] -ceq "--git-path" -and
                [string]$Arguments[2] -cin @("MERGE_HEAD", "config", "info/attributes")) {
                return $false
            }
            if ($Arguments.Count -eq 2 -and
                [string]$Arguments[1] -cmatch $safeRef) {
                return $false
            }
            if ($Arguments.Count -eq 3 -and
                [string]$Arguments[1] -ceq "--verify" -and
                [string]$Arguments[2] -cmatch $safeRef) {
                return $false
            }
            throw "$Label received an unsafe quiet-window rev-parse query"
        }
        "status" {
            if ($Arguments.Count -ne 2 -or
                [string]$Arguments[1] -cne "--porcelain") {
                throw "$Label permits only git status --porcelain"
            }
            return $false
        }
        "symbolic-ref" {
            if (($Arguments -join "`n") -cne
                    (@("symbolic-ref", "--quiet", "--short", "HEAD") -join "`n")) {
                throw "$Label permits only the exact current-branch symbolic-ref query"
            }
            return $false
        }
        "merge-base" {
            if ($Arguments.Count -ne 4 -or
                [string]$Arguments[1] -cne "--is-ancestor" -or
                [string]$Arguments[2] -cnotmatch '^[0-9a-f]{40}$' -or
                [string]$Arguments[3] -cnotmatch '^[0-9a-f]{40}$') {
                throw "$Label received an unsafe merge-base query"
            }
            return $false
        }
        "check-ref-format" {
            if ($Arguments.Count -ne 2 -or
                [string]$Arguments[1] -cnotmatch
                    '^refs/(?:heads|remotes/origin)/[A-Za-z0-9][A-Za-z0-9._/-]{0,192}$') {
                throw "$Label received an unsafe check-ref-format query"
            }
            return $false
        }
        "diff" {
            if (($Arguments -join "`n") -cne
                    (@("diff", "--name-only", "--diff-filter=U") -join "`n")) {
                throw "$Label permits only the exact unmerged-path diff query"
            }
            return $false
        }
        "reset" {
            if ($Arguments.Count -ne 3 -or
                [string]$Arguments[1] -cnotin @("--mixed", "--hard") -or
                [string]$Arguments[2] -cnotmatch '^[0-9a-f]{40}$') {
                throw "$Label received an unsafe reset mutation"
            }
            return $true
        }
        "add" {
            $expectedPaths = @(
                "config/location_market_events.json",
                "config/locations.json"
            )
            $actualPaths = if ($Arguments.Count -gt 2) {
                @($Arguments[2..($Arguments.Count - 1)] | Sort-Object)
            }
            else { @() }
            if ($Arguments.Count -ne 4 -or
                [string]$Arguments[1] -cne "--" -or
                ($actualPaths -join "`n") -cne (($expectedPaths | Sort-Object) -join "`n")) {
                throw "$Label received an unsafe staging mutation"
            }
            return $true
        }
        "commit" {
            if ($Arguments.Count -ne 3 -or [string]$Arguments[1] -cne "-m" -or
                ([string]$Arguments[2] -cne
                    "ops: preserve fleet-generated drift (pre-merge, automated)" -and
                 [string]$Arguments[2] -cnotmatch
                    '^Merge origin/[A-Za-z0-9][A-Za-z0-9._/-]{0,192} into master$')) {
                throw "$Label received an unsafe commit mutation"
            }
            return $true
        }
        "merge" {
            if ($Arguments.Count -eq 2 -and [string]$Arguments[1] -ceq "--abort") {
                return $true
            }
            if ($Arguments.Count -ne 4 -or
                [string]$Arguments[1] -cne "--no-commit" -or
                [string]$Arguments[2] -cne "--no-ff" -or
                [string]$Arguments[3] -cnotmatch '^[0-9a-f]{40}$') {
                throw "$Label received an unsafe merge mutation"
            }
            return $true
        }
        default { throw "$Label received unsupported quiet-window Git command $command" }
    }
}

function Invoke-WeatherQuietGit {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1, 300)][int]$TimeoutSeconds = 60,
        [ValidateRange(1024, 16777216)][int]$MaxOutputBytes = 4194304
    )

    $isMutation = [bool](Assert-WeatherQuietGitArguments `
        -Arguments $Arguments -Label $Label)
    Assert-WeatherIntegrationSafeGitEnvironment -Phase $Label
    $currentGit = Get-WeatherIntegrationGitExecutablePath `
        -Phase $Label -ExpectedPath $script:quietGitExecutable
    if ($null -eq $script:quietGitConfigPin -or
        $null -eq $script:quietGitConfigPin.Stream -or
        -not $script:quietGitConfigPin.Stream.CanRead -or
        $script:quietGitConfigPin.Stream.Length -le 0) {
        throw "$Label lost the retained repository-local Git configuration generation"
    }
    if (Test-Path -LiteralPath $script:quietGitInfoAttributesPath) {
        throw "$Label refuses a newly appeared repository-local info/attributes file"
    }
    foreach ($forbiddenPath in @($script:quietGitForbiddenControlPaths)) {
        if (Test-Path -LiteralPath $forbiddenPath) {
            throw "$Label refuses newly appeared redirected Git object/ref authority: $forbiddenPath"
        }
    }
    Assert-WeatherIntegrationSafeRepositoryGitConfiguration `
        -Root $repo -Label "$Label immediate configuration boundary" `
        -ExpectedGitExecutable $currentGit `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 | Out-Null

    $quotedGitLfs = '"' + $script:quietGitLfsExecutable.Replace('\', '/') + '"'
    $fixedArguments = @(
        "--no-pager", "-C", $repo,
        "-c", "core.fsmonitor=false",
        "-c", "core.hooksPath=NUL",
        "-c", "core.attributesFile=NUL",
        "-c", "core.askPass=",
        "-c", "core.editor=NUL",
        "-c", "core.pager=",
        "-c", "sequence.editor=NUL",
        "-c", "commit.gpgSign=false",
        "-c", "tag.gpgSign=false",
        "-c", "merge.autoEdit=no",
        "-c", "merge.autoStash=false",
        "-c", "merge.verifySignatures=false",
        "-c", "rerere.enabled=false",
        "-c", "submodule.recurse=false",
        "-c", "fetch.recurseSubmodules=false",
        "-c", "protocol.allow=never",
        "-c", "diff.external=",
        "-c", "credential.helper=",
        "-c", "filter.lfs.clean=$quotedGitLfs clean -- %f",
        "-c", "filter.lfs.smudge=$quotedGitLfs smudge -- %f",
        "-c", "filter.lfs.process=$quotedGitLfs filter-process",
        "-c", "filter.lfs.required=true"
    )
    if ([string]$Arguments[0] -ceq "diff") {
        $Arguments = @("diff", "--no-ext-diff", "--no-textconv") +
            @($Arguments[1..($Arguments.Count - 1)])
    }
    $result = Invoke-WeatherIntegrationBoundedProcess `
        -Executable $currentGit `
        -ExpectedExecutableSha256 $script:quietGitExecutableSha256 `
        -Arguments ($fixedArguments + @($Arguments)) `
        -WorkingDirectory $repo `
        -TimeoutSeconds $TimeoutSeconds `
        -Label $Label `
        -AllowedExitCodes @(0..255) `
        -MaxOutputBytes $MaxOutputBytes `
        -RemoveEnvironmentVariables @(Get-WeatherIntegrationBlockedGitEnvironmentNames) `
        -Environment @{
            GIT_CONFIG_NOSYSTEM = "1"
            GIT_CONFIG_SYSTEM = "NUL"
            GIT_CONFIG_GLOBAL = "NUL"
            GIT_CONFIG_COUNT = "0"
            GIT_NO_REPLACE_OBJECTS = "1"
            GIT_OPTIONAL_LOCKS = if ($isMutation) { "1" } else { "0" }
            GIT_TERMINAL_PROMPT = "0"
            GCM_INTERACTIVE = "Never"
            GIT_AUTHOR_NAME = $script:quietGitAuthorName
            GIT_AUTHOR_EMAIL = $script:quietGitAuthorEmail
            GIT_COMMITTER_NAME = $script:quietGitAuthorName
            GIT_COMMITTER_EMAIL = $script:quietGitAuthorEmail
            LC_ALL = "C"
            LANG = "C"
        }
    if ([string]$result.ExecutableSha256 -cne
            $script:quietGitExecutableSha256) {
        throw "$Label executed a different Git generation than the retained pin"
    }
    return $result
}
$offlineQualification = [Environment]::GetEnvironmentVariable(
    "WEATHER_INTEGRATION_TEST_OFFLINE",
    [EnvironmentVariableTarget]::Process
)
if ($offlineQualification -ceq "1") {
    if (-not $DryRun.IsPresent) {
        throw "offline integration qualification refuses every non-DryRun quiet merge"
    }
    $boundProductionRoot = [Environment]::GetEnvironmentVariable(
        "WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT",
        [EnvironmentVariableTarget]::Process
    )
    if ([string]::IsNullOrWhiteSpace($boundProductionRoot) -or
        -not [IO.Path]::IsPathRooted($boundProductionRoot)) {
        throw (
            "offline integration qualification requires an absolute " +
            "WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT binding"
        )
    }
    $resolvedProductionRoot = (
        Resolve-Path -LiteralPath $boundProductionRoot -ErrorAction Stop
    ).Path
    $productionRootItem = Get-Item -LiteralPath $resolvedProductionRoot `
        -Force -ErrorAction Stop
    if (-not $productionRootItem.PSIsContainer -or
        ($productionRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "offline integration qualification production-root binding is not a regular directory"
    }
}
if ([string]::IsNullOrWhiteSpace($ExpectedOriginUrl)) {
    $ExpectedOriginUrl = Get-WeatherIntegrationCanonicalOriginUrl `
        -Root $repo -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256
}
else {
    Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root $repo -ExpectedUrl $ExpectedOriginUrl `
        -Phase "quiet-window merge" `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 | Out-Null
}
$py = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {
    throw "quiet-window production Python interpreter is missing: $py"
}
$py = [IO.Path]::GetFullPath($py)
$pythonExecutablePin = Open-WeatherQuietMergePinnedScript `
    -Path $py `
    -ExpectedSha256 $ExpectedPythonExecutableSha256 `
    -Label "quiet-window Python executable"
$quietPinnedScripts.Add($pythonExecutablePin)
$pythonExecutableSha256 = [string]$pythonExecutablePin.Sha256
$quietPythonBlockedControls = @(
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
    "WEATHER_INTEGRATION_GIT_EXECUTABLE"
)
$ambientPythonControls = @($quietPythonBlockedControls | Where-Object {
    $null -ne [Environment]::GetEnvironmentVariable(
        $_, [EnvironmentVariableTarget]::Process
    )
})
if ($ambientPythonControls.Count -ne 0) {
    throw (
        "quiet-window merge refuses ambient Python execution controls: " +
        ($ambientPythonControls -join ", ")
    )
}
$quietPythonEnvironment = @{
    PYTHONPATH = (Join-Path $repo "src")
    PYTHONNOUSERSITE = "1"
    PYTHONSAFEPATH = "1"
    PYTHONPYCACHEPREFIX = ""
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
    WEATHER_INTEGRATION_GIT_EXECUTABLE = $gitExecutable
}
$quietPythonRemoveEnvironmentVariables = @(
    @($quietPythonBlockedControls) +
    @(Get-WeatherIntegrationBlockedGitEnvironmentNames) |
        Sort-Object -Unique
)
$quietPythonCacheRoot = $null
if ($OwnerApprovedException) {
    if (
        $OwnerApprovedException -cne
            "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" -or
        (Get-WeatherQuietMergeScheduleLocalNow).ToString("yyyy-MM-dd") -cne
            "2026-08-23"
    ) {
        throw "owner-approved protected-window exception is invalid or expired"
    }
    $workloadLeaseScript = Join-Path $PSScriptRoot "workload_admission.ps1"
    $expectedWorkloadLeaseSha256 =
        "3e2de64fb02e98e3016c71163bd7b297cf72488bbdfa593b38b237441f396389"
    if ($ExpectedWorkloadAdmissionSha256 -and
        $ExpectedWorkloadAdmissionSha256.Trim().ToLowerInvariant() -cne
            $expectedWorkloadLeaseSha256) {
        throw "owner-approved workload admission binding contradicts the reviewed exception"
    }
    $ExpectedWorkloadAdmissionSha256 = $expectedWorkloadLeaseSha256
}
else {
    $workloadLeaseScript = Join-Path $repo "scripts\ops\workload_admission.ps1"
}
$workloadAdmissionPin = Open-WeatherQuietMergePinnedScript `
    -Path $workloadLeaseScript `
    -ExpectedSha256 $ExpectedWorkloadAdmissionSha256 `
    -Label "quiet-window workload-admission dependency"
$quietPinnedScripts.Add($workloadAdmissionPin)
if ($OwnerApprovedException -and
    [string]$workloadAdmissionPin.Sha256 -cne $expectedWorkloadLeaseSha256) {
        throw "owner-approved workload admission source changed"
}
. $workloadAdmissionPin.Path
$quietPreflightPin = Open-WeatherQuietMergePinnedScript `
    -Path (Join-Path $repo "scripts\ops\integration_attempt_quiet_merge_preflight.ps1") `
    -ExpectedSha256 $ExpectedQuietMergePreflightSha256 `
    -Label "quiet-window preflight dependency"
$quietPinnedScripts.Add($quietPreflightPin)
. $quietPreflightPin.Path
$reportPath = Join-Path $repo "data\alerts\quiet_window_merge_last.json"
$historyPath = Join-Path $repo "data\alerts\quiet_window_merge_history.jsonl"
$activeMarkerPath = Join-Path $repo "data\alerts\quiet_window_merge_in_progress.json"
$log = New-Object System.Collections.Generic.List[string]
$resolvedBranchTip = $null
$mergeTarget = $Branch
$mergeCommit = $null
$baselineCommit = $null
$preMerge = $null
$rollbackContentSha256 = [ordered]@{}
$captureRecoveryProved = $false
$executionTapeRecoveryRequired = $false
$executionTapeReadoptionExpected = $false
$executionTapeRolledButInactiveSkipped = $false
$executionTapeRecoveryProved = $false
$executionTapeSourceBefore = $null
$publicationAcknowledged = $false
$documentationTransactionRecorded = $false
$documentationTransactionPendingSha256 = $null
$documentationTransactionSnapshotPath = $null
$documentedMarkerSha256 = $null
$activeMarkerOwned = $false
$script:quietActiveMarkerSha256 = $null
$quietPythonStageProofs = New-Object System.Collections.Generic.List[object]
$quietMergeHeadPath = $null
$quietPythonAuthorityRoots = @("app", "scripts", "src", "tests", "tools", "weather")
function Note($m) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $m
    $log.Add($line); Write-Output $line
}
function Fail($m) {
    Note "ABORT: $m"
    Save-Report -ok $false -stage "abort" -detail $m
    exit 1
}
function Save-Report($ok, $stage, $detail) {
    $record = [ordered]@{
        schema = "quiet_window_merge_report_v0.2"
        ts = (Get-Date).ToString("o"); repo_root = $repo; branch = $Branch; ok = $ok
        expected_tip = $ExpectedTip; expected_baseline = $ExpectedBaseline
        origin_url = $ExpectedOriginUrl
        resolved_branch_tip = $resolvedBranchTip
        baseline_commit = $baselineCommit
        pre_merge_commit = $preMerge
        rollback_content_sha256 = $rollbackContentSha256
        merge_commit = $mergeCommit
        capture_recovery_proved = $captureRecoveryProved
        execution_tape_recovery_required = $executionTapeRecoveryRequired
        execution_tape_readoption_expected = $executionTapeReadoptionExpected
        execution_tape_rolled_but_inactive_skipped = $executionTapeRolledButInactiveSkipped
        execution_tape_recovery_proved = $executionTapeRecoveryProved
        execution_tape_source_before = $executionTapeSourceBefore
        documentation_transaction_recorded = $documentationTransactionRecorded
        documentation_transaction_pending_sha256 = $documentationTransactionPendingSha256
        documentation_transaction_snapshot_path = $documentationTransactionSnapshotPath
        python_executable_sha256 = $pythonExecutableSha256
        python_stage_proofs = @($quietPythonStageProofs)
        publication_acknowledged = $publicationAcknowledged
        authoritative_attempt_report = -not [string]::IsNullOrWhiteSpace(
            $AttemptReportPath
        )
        compatibility_outputs_authority = "DIAGNOSTIC_ONLY"
        stage = $stage; detail = $detail; log = @($log)
    }
    $json = $record | ConvertTo-Json -Depth 8
    $reportPersisted = $false
    $attemptReportPersisted = $false
    $attemptReportExpectedSha256 = $null
    # An integration attempt supplies its own unused evidence path. Create the
    # destination itself with CreateNew, flush it through one retained
    # read/write handle, and parse/hash the same bytes before touching mutable
    # compatibility diagnostics. A crash may leave invalid partial evidence,
    # but it can never overwrite or borrow another generation.
    if ($AttemptReportPath) {
        $attemptSnapshot = Write-WeatherQuietImmutableJson `
            -Path $AttemptReportPath -JsonText $json `
            -Label "attempt-local immutable quiet-merge report"
        $attemptReportExpectedSha256 = [string]$attemptSnapshot.Sha256
        $attemptReportPersisted = $true
        $reportPersisted = $true
    }
    try {
        $json | Set-Content -Path $reportPath -Encoding utf8
        $reportPersisted = $true
    }
    catch {}
    # $reportPath is a single most-recent slot, so a later run ERASES an earlier one. On
    # 2026-08-01 three scheduled merges aborted at 01:15/01:50/02:25 (the config-drift trap)
    # and a manual re-run at 02:55 succeeded and overwrote all three -- leaving no on-disk
    # trace of the failures at all, only the task exit codes. That is exactly how the aborts
    # were later mis-read as a cosmetic exit code. Append every outcome so history survives.
    try {
        ($record | ConvertTo-Json -Depth 8 -Compress) | Add-Content -Path $historyPath -Encoding utf8
        $reportPersisted = $true
    }
    catch {}
    if ($AttemptReportPath -and -not $attemptReportPersisted) {
        throw "attempt-local immutable quiet-window terminal report could not be persisted"
    }
    if (-not $reportPersisted) {
        throw "quiet-window terminal report could not be persisted"
    }
    # Retire the durable marker only after a terminal report proves publication
    # or an exact baseline restoration. Merged-unpushed and unproven rollback
    # states retain it so boot/status/reconciliation cannot lose the recovery
    # target merely because a failure report was written.
    $markerCanRetire = (
        ($stage -eq "pushed" -and $publicationAcknowledged) -or
        $stage -eq "rolled_back" -or
        $stage -eq "abort" -or
        $stage -eq "dry_run"
    )
    if ($activeMarkerOwned -and $markerCanRetire) {
        if ($AttemptReportPath) {
            $retirementReport = Read-WeatherQuietRetainedSnapshot `
                -Path $AttemptReportPath `
                -Label "attempt-local report before active-marker retirement" `
                -Json
            if ([string]$retirementReport.Sha256 -cne
                    $attemptReportExpectedSha256) {
                throw "attempt-local immutable report changed before active-marker retirement"
            }
        }
        $retirementMarker = Read-WeatherQuietRetainedSnapshot `
            -Path $activeMarkerPath `
            -Label "active marker before terminal retirement" `
            -Json
        if ([string]::IsNullOrWhiteSpace(
                [string]$script:quietActiveMarkerSha256
            ) -or [string]$retirementMarker.Sha256 -cne
                [string]$script:quietActiveMarkerSha256) {
            throw "active quiet-merge marker changed before terminal retirement"
        }
        Remove-Item -LiteralPath $activeMarkerPath -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $activeMarkerPath) {
            throw "active quiet-merge marker still exists after terminal retirement"
        }
    }
}

function Write-QuietMergeMarker {
    param([Parameter(Mandatory = $true)][string]$Phase)

    $marker = [ordered]@{
        schema = "quiet_window_merge_in_progress_v0.1"
        updated_at = (Get-Date).ToString("o")
        repo_root = $repo
        phase = $Phase
        branch = $Branch
        expected_tip = $ExpectedTip
        expected_baseline = $ExpectedBaseline
        origin_url = $ExpectedOriginUrl
        resolved_branch_tip = $resolvedBranchTip
        baseline_commit = $baselineCommit
        pre_merge_commit = $preMerge
        merge_commit = $mergeCommit
        capture_recovery_proved = $captureRecoveryProved
        execution_tape_recovery_required = $executionTapeRecoveryRequired
        execution_tape_readoption_expected = $executionTapeReadoptionExpected
        execution_tape_rolled_but_inactive_skipped = $executionTapeRolledButInactiveSkipped
        execution_tape_recovery_proved = $executionTapeRecoveryProved
        execution_tape_source_before = $executionTapeSourceBefore
        documentation_transaction_recorded = $documentationTransactionRecorded
        documentation_transaction_pending_sha256 = $documentationTransactionPendingSha256
        documentation_transaction_snapshot_path = $documentationTransactionSnapshotPath
        publication_acknowledged = $publicationAcknowledged
        auto_refreshed_paths = @(
            "config/locations.json",
            "config/location_market_events.json"
        )
        auto_refreshed_sha256 = $rollbackContentSha256
    }
    $raw = $marker | ConvertTo-Json -Depth 8
    $encoder = New-Object Text.UTF8Encoding($false, $true)
    [byte[]]$rawBytes = $encoder.GetBytes($raw)
    if ($rawBytes.Length -le 0 -or $rawBytes.Length -gt 2097152) {
        throw "Active quiet-merge marker exceeds its bounded JSON contract."
    }
    $expectedSha256 = Get-WeatherQuietBytesSha256 -Bytes $rawBytes
    $parent = [IO.Path]::GetFullPath((Split-Path -Parent $activeMarkerPath))
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        [void][IO.Directory]::CreateDirectory($parent)
    }
    Assert-WeatherQuietMergeRegularPathAncestry `
        -Path (Join-Path $parent "marker-child") `
        -Label "active quiet-merge marker parent"
    $parentItem = Get-Item -LiteralPath $parent -Force -ErrorAction Stop
    if (-not $parentItem.PSIsContainer -or
        ($parentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        [IO.Path]::GetFullPath([string]$parentItem.FullName).TrimEnd('\') -ine
            $parent.TrimEnd('\')) {
        throw "Active quiet-merge marker parent is not one exact regular directory."
    }
    $leaf = Split-Path -Leaf $activeMarkerPath
    $temp = Join-Path $parent (".{0}.{1}.tmp" -f $leaf, [guid]::NewGuid().ToString("N"))
    $backup = Join-Path $parent (".{0}.{1}.bak" -f $leaf, [guid]::NewGuid().ToString("N"))
    if ((Test-Path -LiteralPath $temp) -or (Test-Path -LiteralPath $backup)) {
        throw "Unique active-marker transaction paths unexpectedly exist."
    }
    $priorSnapshot = $null
    if (Test-Path -LiteralPath $activeMarkerPath) {
        $priorSnapshot = Read-WeatherQuietRetainedSnapshot `
            -Path $activeMarkerPath -Label "prior active quiet-merge marker" `
            -Json
        if ([string]::IsNullOrWhiteSpace(
                [string]$script:quietActiveMarkerSha256
            ) -or [string]$priorSnapshot.Sha256 -cne
                [string]$script:quietActiveMarkerSha256) {
            throw "Active quiet-merge marker changed outside its owned transaction."
        }
    }
    elseif (-not [string]::IsNullOrWhiteSpace(
            [string]$script:quietActiveMarkerSha256
        )) {
        throw "Owned active quiet-merge marker disappeared before its update."
    }
    $tempStream = $null
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
            throw "Active-marker transaction temp has the wrong durable byte count."
        }
        $tempStream.Position = 0
        [byte[]]$tempReadback = New-Object byte[] ([int]$rawBytes.Length)
        $tempOffset = 0
        while ($tempOffset -lt $tempReadback.Length) {
            $read = $tempStream.Read(
                $tempReadback,
                $tempOffset,
                $tempReadback.Length - $tempOffset
            )
            if ($read -le 0) { throw "Active-marker temp ended during retained readback." }
            $tempOffset += $read
        }
        $tempText = ConvertFrom-WeatherQuietStrictUtf8Bytes `
            -Bytes $tempReadback -Label "active-marker transaction temp"
        try { $tempPayload = $tempText | ConvertFrom-Json -ErrorAction Stop }
        catch { throw "Active-marker temp JSON readback failed: $($_.Exception.Message)" }
        if ($null -eq $tempPayload -or $tempPayload -is [Array] -or
            (Get-WeatherQuietBytesSha256 -Bytes $tempReadback) -cne
                $expectedSha256 -or $tempText -cne $raw) {
            throw "Active-marker temp same-handle bytes disagree with the intended marker."
        }
        $tempStream.Dispose()
        $tempStream = $null
        $frozenTemp = Read-WeatherQuietRetainedSnapshot `
            -Path $temp -Label "active-marker transaction temp" -Json
        if ([string]$frozenTemp.Sha256 -cne $expectedSha256 -or
            [string]$frozenTemp.Text -cne $raw) {
            throw "Active-marker transaction temp changed before publication."
        }
        if ($null -ne $priorSnapshot) {
            $markerAtReplace = Read-WeatherQuietRetainedSnapshot `
                -Path $activeMarkerPath `
                -Label "active marker at transactional replacement" `
                -Json
            if ([string]$markerAtReplace.Sha256 -cne
                    [string]$priorSnapshot.Sha256 -or
                [string]$markerAtReplace.Text -cne [string]$priorSnapshot.Text) {
                throw "Active quiet-merge marker changed during its transaction."
            }
            [IO.File]::Replace($temp, $activeMarkerPath, $backup, $true)
        }
        else {
            if (Test-Path -LiteralPath $activeMarkerPath) {
                throw "Active quiet-merge marker appeared during initial creation."
            }
            [IO.File]::Move($temp, $activeMarkerPath)
        }
        $updatedSnapshot = Read-WeatherQuietRetainedSnapshot `
            -Path $activeMarkerPath -Label "updated active quiet-merge marker" `
            -Json
        if ([string]$updatedSnapshot.Sha256 -cne $expectedSha256 -or
            [long]$updatedSnapshot.Length -ne [long]$rawBytes.Length -or
            [string]$updatedSnapshot.Text -cne $raw) {
            throw "Active-marker transaction readback differs from its exact intended bytes."
        }
        if ($null -ne $priorSnapshot) {
            $backupSnapshot = Read-WeatherQuietRetainedSnapshot `
                -Path $backup -Label "active-marker transaction backup" -Json
            if ([string]$backupSnapshot.Sha256 -cne
                    [string]$priorSnapshot.Sha256 -or
                [long]$backupSnapshot.Length -ne [long]$priorSnapshot.Length -or
                [string]$backupSnapshot.Text -cne [string]$priorSnapshot.Text) {
                throw "Active-marker transaction backup differs from the prior marker."
            }
        }
        $script:quietActiveMarkerSha256 = $expectedSha256
    }
    catch { $primaryFailure = $_ }
    finally {
        if ($null -ne $tempStream) {
            try { $tempStream.Dispose() }
            catch { $cleanupFailures.Add("temp handle: $($_.Exception.Message)") }
        }
        foreach ($ownedPath in @($temp, $backup)) {
            if (-not (Test-Path -LiteralPath $ownedPath)) { continue }
            try {
                Assert-WeatherQuietMergeRegularPathAncestry `
                    -Path $ownedPath -Label "owned active-marker transaction artifact"
                $ownedItem = Get-Item -LiteralPath $ownedPath -Force -ErrorAction Stop
                if ($ownedItem.PSIsContainer -or
                    ($ownedItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                    [IO.Path]::GetFullPath([string]$ownedItem.DirectoryName).TrimEnd('\') -ine
                        $parent.TrimEnd('\')) {
                    throw "Owned marker artifact changed identity: $ownedPath"
                }
                Remove-Item -LiteralPath $ownedPath -Force -ErrorAction Stop
                if (Test-Path -LiteralPath $ownedPath) {
                    throw "Owned marker artifact remains after removal: $ownedPath"
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
                $primaryFailure.Exception.Data["weather_cleanup_failure"] =
                    $cleanupMessage
                Write-Warning $cleanupMessage -WarningAction Continue
            }
            else { throw $cleanupMessage }
        }
    }
    if ($null -ne $primaryFailure) { throw $primaryFailure }
}

function Test-ExecutionTapeActive {
    # Mirror roll_verdict.ps1's activation contract without changing task
    # state. A disabled optional task is skipped only when no detached writer
    # remains active; this must never enable an intentionally held producer.
    $task = Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor" -ErrorAction SilentlyContinue
    if ($task -and [string]$task.State -ne "Disabled") { return $true }
    $statusPath = Join-Path $repo "data\snapshots\execution_tape_status.json"
    $writerLockPath = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
    if (Test-Path -LiteralPath $writerLockPath -PathType Leaf) { return $true }
    if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
        try {
            $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
            if ([string]$status.state -eq "STOPPED" -or [int]$status.pid -le 0) {
                return $false
            }
            # A retained CONNECTED status is not a live writer. With the task
            # disabled and no lock, require the recorded PID to still exist
            # before treating the optional producer as rollable.
            return $null -ne (Get-Process -Id ([int]$status.pid) -ErrorAction SilentlyContinue)
        }
        catch { return $false }
    }
    return $false
}

function Assert-OneShotPushTask {
    # Publication is deliberately delegated to the one interactive task whose
    # account can reach Windows Credential Manager. Prove that dependency before
    # any ref or working-tree mutation; discovering a disabled, S4U, renamed, or
    # command-drifted task after the recovery-proved commit would strand master
    # locally ahead of origin by design.
    try {
        $pushTasks = @(Get-ScheduledTask -TaskName "WeatherOneShotPush" -ErrorAction Stop)
    }
    catch {
        throw "WeatherOneShotPush is unavailable: $($_.Exception.Message)"
    }
    if ($pushTasks.Count -ne 1) {
        throw "WeatherOneShotPush must resolve to exactly one scheduled task; found $($pushTasks.Count)"
    }
    $pushTask = $pushTasks[0]
    $expectedPushTaskXmlSha256 = "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
    try {
        $pushTaskXml = [string](Export-ScheduledTask -TaskName "WeatherOneShotPush" -TaskPath "\" -ErrorAction Stop)
        $pushTaskSha = [Security.Cryptography.SHA256]::Create()
        try {
            $actualPushTaskXmlSha256 = ([BitConverter]::ToString(
                    $pushTaskSha.ComputeHash([Text.Encoding]::UTF8.GetBytes($pushTaskXml))
                ) -replace '-', '').ToLowerInvariant()
        }
        finally { $pushTaskSha.Dispose() }
    }
    catch {
        throw "WeatherOneShotPush definition could not be hash-verified: $($_.Exception.Message)"
    }
    if ($actualPushTaskXmlSha256 -ne $expectedPushTaskXmlSha256) {
        throw "WeatherOneShotPush task XML changed from the reviewed trigger/settings/action contract"
    }
    $pushActions = @($pushTask.Actions)
    $expectedPushSid = "S-1-5-21-1525964525-1566663060-3901869365-1001"
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $expectedWorkingDirectory = [IO.Path]::GetFullPath($repo).TrimEnd('\')
    $actualWorkingDirectory = try {
        [IO.Path]::GetFullPath([string]$pushActions[0].WorkingDirectory).TrimEnd('\')
    }
    catch { "" }
    $expectedPushArguments = '/c git -C c:\Users\micha\Desktop\github\weather push origin master > C:\Users\micha\ops\logs\push-oneshot.log 2>&1'
    $pushTaskBound = (
        [string]$pushTask.TaskPath -ceq "\" -and
        [string]$pushTask.State -ceq "Ready" -and
        $pushTask.Settings.Enabled -eq $true -and
        [string]$pushTask.Principal.UserId -ieq "micha" -and
        $currentSid -ceq $expectedPushSid -and
        [string]$pushTask.Principal.LogonType -ceq "Interactive" -and
        [string]$pushTask.Principal.RunLevel -ceq "Limited" -and
        $pushActions.Count -eq 1 -and
        [string]$pushActions[0].Execute -ieq "cmd.exe" -and
        [string]$pushActions[0].Arguments -ieq $expectedPushArguments -and
        $actualWorkingDirectory -ieq $expectedWorkingDirectory
    )
    if (-not $pushTaskBound) {
        throw "WeatherOneShotPush is not exactly bound to the enabled current-user Interactive/Limited git-push contract"
    }
    Note "WeatherOneShotPush exact publication binding passed"
}

if ($AttemptReportPath) {
    if (-not [IO.Path]::IsPathRooted($AttemptReportPath)) {
        throw "AttemptReportPath must be an absolute path"
    }
    $AttemptReportPath = [IO.Path]::GetFullPath($AttemptReportPath)
    $attemptReportParent = Split-Path -Parent $AttemptReportPath
    if (-not (Test-Path -LiteralPath $attemptReportParent -PathType Container)) {
        throw "AttemptReportPath parent directory does not exist: $attemptReportParent"
    }
    if (Test-Path -LiteralPath $AttemptReportPath) {
        throw "AttemptReportPath is immutable and already exists: $AttemptReportPath"
    }
    if ($AttemptReportPath -ieq $reportPath -or $AttemptReportPath -ieq $historyPath) {
        throw "AttemptReportPath must not reuse a mutable quiet-merge report path"
    }
}

$ExpectedTip = $ExpectedTip.Trim().ToLowerInvariant()
if ($ExpectedTip -and $ExpectedTip -notmatch '^[0-9a-f]{40}$') {
    Fail "ExpectedTip must be a full 40-character hexadecimal commit SHA"
}
$ExpectedBaseline = $ExpectedBaseline.Trim().ToLowerInvariant()
if ($ExpectedBaseline -and $ExpectedBaseline -notmatch '^[0-9a-f]{40}$') {
    Fail "ExpectedBaseline must be a full 40-character hexadecimal commit SHA"
}

$ownerProtectedWindowException = $false
if ($OwnerApprovedException) {
    $authorizedRoot = "71f7e46690e822a498f80412c11d550bcee949d2"
    $authorizedBaseline = "9d54f94760855a5f91ac603f3f14b02ba06ae239"
    $ownerAncestorExit = 1
    if ($ExpectedTip -match '^[0-9a-f]{40}$') {
        $ownerAncestorResult = Invoke-WeatherQuietGit `
            -Arguments @(
                "merge-base", "--is-ancestor", $authorizedRoot, $ExpectedTip
            ) `
            -Label "owner-exception exact lineage query"
        $ownerAncestorExit = [int]$ownerAncestorResult.ExitCode
    }
    if (
        $OwnerApprovedException -cne
            "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" -or
        -not $Force -or
        (Get-WeatherQuietMergeScheduleLocalNow).ToString("yyyy-MM-dd") -cne
            "2026-08-23" -or
        $Branch -cne "origin/codex/live-readiness-closure-20260823" -or
        $ExpectedBaseline -cne $authorizedBaseline -or
        $ownerAncestorExit -ne 0
    ) {
        Fail "owner-approved protected-window exception is invalid, unbound, or expired"
    }
    $ownerProtectedWindowException = $true
    Note "one-time repository-owner protected-window exception accepted for exact branch lineage and baseline"
}

# The broad host windows do not depend on the roll verdict. Refuse them before
# taking the shared lease, then serialize the verdict and every subsequent Git,
# recovery, documentation, and publication decision under that one OS handle.
$quietScheduleNow = Get-WeatherQuietMergeScheduleLocalNow
$h = $quietScheduleNow.Hour + ($quietScheduleNow.Minute / 60.0)
if (-not $ownerProtectedWindowException -and $h -ge 12 -and $h -lt 18) {
    Fail "inside the 12:00-18:00 graded capture window - never merge here"
}
if (-not $ownerProtectedWindowException -and ($h -ge 18 -or $h -lt 0.5)) {
    Fail ("inside the 18:00-00:30 protected near-close window (now {0:N2}) - no heavy work here" -f $h)
}
$workloadLease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $repo `
    -Workload "quiet_window_merge" `
    -OwnerApprovedException $OwnerApprovedException
if ($null -eq $workloadLease) { Fail "another heavyweight host workload owns data/logs/heavy_workload.lock" }
$quietMutationPrimaryError = $null
try {

# ---- window guard, proportional to the branch's actual roll verdict ----
# This used to demand 01:00-04:00 for EVERY branch, including branches that cannot roll
# anything. That is a guard against a risk the branch does not carry, and it was the real
# reason the merge queue backed up: 25 unmerged branches queued for three hours a night,
# most of them roll-free. A guard that costs more than the risk it prevents gets worked
# around, and then it protects nothing.
#
# So ask first. roll_verdict.ps1 derives the answer from the live closures rather than by
# hand -- exit 0 roll-free, 2 roll-free-only-while-a-loop-stays-dormant, 3 roll-sensitive,
# 1 undecidable. Anything that is not a clean 0 is treated as roll-sensitive: the cost of a
# wrong "free" is a streak day, the cost of a wrong "sensitive" is waiting until 01:00.
$verdictScript = Join-Path $repo "scripts\ops\roll_verdict.ps1"
$rollFree = $false
$rollVerdictReadable = $false
$executionTapeActive = Test-ExecutionTapeActive
if (-not $ExpectedTip) {
    # Classify the exact already-fetched object. A later fetch that moves the
    # branch then fails the equality check instead of borrowing this verdict.
    $preVerdictCommitRef = "{0}^{{commit}}" -f $Branch
    $preVerdictResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "--verify", $preVerdictCommitRef) `
        -Label "pre-verdict exact branch-tip query"
    $preVerdictBranchTip = @($preVerdictResult.StdoutLines)
    if ([int]$preVerdictResult.ExitCode -ne 0 -or
        $preVerdictBranchTip.Count -ne 1 -or
        ([string]$preVerdictBranchTip[0]).Trim().ToLowerInvariant() -notmatch '^[0-9a-f]{40}$') {
        Fail "branch is not locally resolvable before roll classification: $Branch"
    }
    $ExpectedTip = ([string]$preVerdictBranchTip[0]).Trim().ToLowerInvariant()
    Note "observed branch tip frozen before roll classification: $Branch -> $ExpectedTip"
}
$verdictRef = $ExpectedTip
if (Test-Path -LiteralPath $verdictScript) {
    $rollVerdictPin = Open-WeatherQuietMergePinnedScript `
        -Path $verdictScript `
        -ExpectedSha256 $ExpectedRollVerdictSha256 `
        -Label "quiet-window roll-verdict dependency"
    $quietPinnedScripts.Add($rollVerdictPin)
    $verdictTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $verdictTempRootItem = Get-Item -LiteralPath $verdictTempRoot `
        -Force -ErrorAction Stop
    if (-not $verdictTempRootItem.PSIsContainer -or
        ($verdictTempRootItem.Attributes -band
            [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Fail "roll-verdict temp root is not a regular non-reparse directory"
    }
    $verdictJsonPath = Join-Path $verdictTempRoot (
        "weather-roll-verdict-{0}.json" -f [guid]::NewGuid().ToString("N")
    )
    $verdictSeedStream = $null
    $verdictSharedReadStream = $null
    $verdictFrozenReadStream = $null
    $verdictExitCode = 1
    $verdictProcessingFailure = $null
    try {
        # Create the GUID-named output with CreateNew, then retain a read handle
        # that denies delete/rename while still sharing child writes.  After the
        # in-process verdict script returns, acquire a second read-only-share
        # handle before releasing the shared-write handle.  This freezes the
        # exact file object and generation before any JSON byte is parsed.
        $verdictSeedStream = [IO.FileStream]::new(
            $verdictJsonPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::ReadWrite,
            4096,
            [IO.FileOptions]::WriteThrough
        )
        $verdictSharedReadStream = [IO.FileStream]::new(
            $verdictJsonPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::ReadWrite,
            4096,
            [IO.FileOptions]::SequentialScan
        )
        $verdictSeedStream.Dispose()
        $verdictSeedStream = $null
        $verdictJsonItem = Get-Item -LiteralPath $verdictJsonPath `
            -Force -ErrorAction Stop
        if ($verdictJsonItem.PSIsContainer -or
            ($verdictJsonItem.Attributes -band
                [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            [IO.Path]::GetFullPath($verdictJsonItem.DirectoryName).TrimEnd(
                [IO.Path]::DirectorySeparatorChar,
                [IO.Path]::AltDirectorySeparatorChar
            ) -cne $verdictTempRoot) {
            throw "roll-verdict output is not the exact regular temp-root child"
        }
        $rollVerdictResult = Invoke-WeatherIntegrationBoundedProcess `
            -Executable $powerShellExecutable `
            -ExpectedExecutableSha256 ([string]$powerShellExecutablePin.Sha256) `
            -Arguments @(
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", $rollVerdictPin.Path,
                "-Branch", $verdictRef,
                "-JsonOut", $verdictJsonPath,
                "-GitExecutable", $gitExecutable,
                "-ExpectedGitExecutableSha256", $script:quietGitExecutableSha256,
                "-ExpectedRemoteGitSha256", ([string]$remoteGitPin.Sha256),
                "-ExpectedJobContainmentSha256", ([string]$jobContainmentPin.Sha256)
            ) `
            -WorkingDirectory $repo `
            -TimeoutSeconds 120 `
            -Label "quiet-window pinned roll-verdict execution" `
            -AllowedExitCodes @(0, 1, 2, 3) `
            -MaxOutputBytes 1048576 `
            -RemoveEnvironmentVariables @(
                Get-WeatherIntegrationBlockedGitEnvironmentNames
            ) `
            -Environment @{
                LC_ALL = "C"
                LANG = "C"
            }
        foreach ($verdictLine in @($rollVerdictResult.StdoutLines)) {
            Note "roll_verdict: $verdictLine"
        }
        foreach ($verdictErrorLine in @(
            ([string]$rollVerdictResult.Stderr) -split "`r?`n" |
                Where-Object { $_ -ne "" }
            )) {
            Note "roll_verdict(stderr): $verdictErrorLine"
        }
        $verdictExitCode = [int]$rollVerdictResult.ExitCode
        $rollFree = ($verdictExitCode -eq 0)

        $verdictFrozenReadStream = [IO.FileStream]::new(
            $verdictJsonPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read,
            4096,
            [IO.FileOptions]::SequentialScan
        )
        $verdictSharedReadStream.Dispose()
        $verdictSharedReadStream = $null
        if ($verdictFrozenReadStream.Length -le 0 -or
            $verdictFrozenReadStream.Length -gt 1048576) {
            throw "roll-verdict JSON length is outside its bounded contract"
        }
        $verdictMemory = New-Object IO.MemoryStream
        try {
            $verdictFrozenReadStream.Position = 0
            $verdictFrozenReadStream.CopyTo($verdictMemory)
            $verdictBytes = $verdictMemory.ToArray()
        }
        finally { $verdictMemory.Dispose() }
        if ($verdictBytes.Length -ne $verdictFrozenReadStream.Length) {
            throw "roll-verdict retained byte count changed while reading"
        }
        $verdictBomOffset = if (
            $verdictBytes.Length -ge 3 -and
            $verdictBytes[0] -eq 0xEF -and
            $verdictBytes[1] -eq 0xBB -and
            $verdictBytes[2] -eq 0xBF
        ) { 3 } else { 0 }
        $strictUtf8 = New-Object Text.UTF8Encoding($false, $true)
        $verdictText = $strictUtf8.GetString(
            $verdictBytes,
            $verdictBomOffset,
            $verdictBytes.Length - $verdictBomOffset
        )
        $verdictPayload = $verdictText | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $verdictPayload -or
            $verdictPayload.PSObject.Properties.Name -notcontains "files") {
            throw "roll-verdict JSON is missing its files array"
        }
        foreach ($verdictFile in @($verdictPayload.files)) {
            if ($null -eq $verdictFile -or
                $verdictFile.PSObject.Properties.Name -notcontains "rolls" -or
                $verdictFile.rolls -isnot [bool] -or
                $verdictFile.PSObject.Properties.Name -notcontains "closures") {
                throw "roll-verdict JSON contains an invalid file record"
            }
        }
        $verdictSha = [Security.Cryptography.SHA256]::Create()
        try {
            $verdictJsonSha256 = ([BitConverter]::ToString(
                $verdictSha.ComputeHash($verdictBytes)
            )).Replace("-", "").ToLowerInvariant()
        }
        finally { $verdictSha.Dispose() }
        $rollVerdictReadable = $true
        $executionTapeReadoptionExpected = @(
            $verdictPayload.files |
                Where-Object {
                    $_.rolls -eq $true -and
                    @($_.closures) -contains "execution_tape"
                }
        ).Count -gt 0
        Note "roll-verdict retained JSON SHA256: $verdictJsonSha256"
        Note ("roll verdict exit {0} -> {1}" -f $verdictExitCode, $(if ($rollFree) { "ROLL-FREE" } else { "treated as ROLL-SENSITIVE" }))
    }
    catch {
        $verdictProcessingFailure = $_
        $rollFree = $false
        Note (
            "WARNING: roll-verdict JSON was unreadable or unbound; " +
            "treating the branch as roll-sensitive and gating any active " +
            "execution tape conservatively: $($_.Exception.Message)"
        )
    }
    finally {
        $verdictCleanupFailures = New-Object System.Collections.Generic.List[string]
        foreach ($streamRecord in @(
            [pscustomobject]@{ label = "frozen read"; stream = $verdictFrozenReadStream },
            [pscustomobject]@{ label = "shared read"; stream = $verdictSharedReadStream },
            [pscustomobject]@{ label = "seed"; stream = $verdictSeedStream }
        )) {
            if ($null -ne $streamRecord.stream) {
                try { $streamRecord.stream.Dispose() }
                catch {
                    $verdictCleanupFailures.Add(
                        "$($streamRecord.label) handle: $($_.Exception.Message)"
                    )
                }
            }
        }
        try {
            if (Test-Path -LiteralPath $verdictJsonPath) {
                $cleanupVerdictItem = Get-Item -LiteralPath $verdictJsonPath `
                    -Force -ErrorAction Stop
                if ($cleanupVerdictItem.PSIsContainer -or
                    ($cleanupVerdictItem.Attributes -band
                        [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                    [IO.Path]::GetFullPath(
                        $cleanupVerdictItem.DirectoryName
                    ).TrimEnd(
                        [IO.Path]::DirectorySeparatorChar,
                        [IO.Path]::AltDirectorySeparatorChar
                    ) -cne $verdictTempRoot) {
                    throw "roll-verdict cleanup target changed identity"
                }
                Remove-Item -LiteralPath $verdictJsonPath `
                    -Force -ErrorAction Stop
                if (Test-Path -LiteralPath $verdictJsonPath) {
                    throw "roll-verdict cleanup target still exists"
                }
            }
        }
        catch {
            $verdictCleanupFailures.Add(
                "owned output cleanup: $($_.Exception.Message)"
            )
        }
        if ($verdictCleanupFailures.Count -ne 0) {
            $verdictCleanupMessage = (
                "roll-verdict retained-output cleanup failed: " +
                ($verdictCleanupFailures -join " | ")
            )
            if ($null -ne $verdictProcessingFailure) {
                $verdictProcessingFailure.Exception.Data[
                    "weather_cleanup_failure"
                ] = $verdictCleanupMessage
                throw (
                    "$verdictCleanupMessage; original roll-verdict failure: " +
                    $verdictProcessingFailure.Exception.Message
                )
            }
            throw $verdictCleanupMessage
        }
    }
}
elseif ($ExpectedRollVerdictSha256) {
    throw "Immutable quiet-window roll-verdict dependency is missing."
}
else { Note "roll_verdict.ps1 not found - treating branch as ROLL-SENSITIVE" }

# Gate the auxiliary producer exactly when its live closure rolls. If the
# mechanical verdict could not emit its structured closure proof, fail safe by
# gating an active producer; do not start or enable a disabled inactive task.
$executionTapeRecoveryRequired = ($executionTapeReadoptionExpected -and $executionTapeActive) -or
    ($executionTapeActive -and -not $rollVerdictReadable)
$executionTapeRolledButInactiveSkipped = $executionTapeReadoptionExpected -and -not $executionTapeActive
if ($executionTapeRecoveryRequired) {
    Note ("execution-tape recovery proof required ({0})" -f $(if ($executionTapeReadoptionExpected) { "closure rolls" } else { "active producer with unreadable closure verdict" }))
}
elseif ($executionTapeRolledButInactiveSkipped) {
    Note "execution-tape closure was listed but the optional producer is held inactive; leaving it disabled and skipping recovery proof"
}

if (-not $rollFree -and -not $Force -and -not ($h -ge 1 -and $h -lt 4)) {
    Fail ("roll-sensitive branch outside the 01:00-04:00 quiet window (now {0:N2}); use -Force only if you are certain a capture roll is safe right now" -f $h)
}
if ($rollFree) { Note ("roll-free branch: 01:00-04:00 not required (now {0:N2})" -f $h) }

# ---- preconditions ----
Set-Location $repo
# Never start on top of a merge that is already in progress. WeatherBootRecovery cleans one
# up after a power loss, but if that has not run yet the tree still holds unreviewed merged
# code, and merging again on top of it would bury the problem instead of surfacing it.
if (Test-Path -LiteralPath $activeMarkerPath -PathType Leaf) {
    $priorMarkerReason = "a prior quiet-window merge marker still exists - let WeatherBootRecovery reconcile it before another merge"
    Note "ABORT: $priorMarkerReason"
    if ($AttemptReportPath) {
        # A stronger post-commit crash marker may belong to this same attempt.
        # Do not poison its still-unused immutable report path with a weaker
        # retry-time abort; the parent/reconciler must inspect the marker.
        throw $priorMarkerReason
    }
    Save-Report -ok $false -stage "abort" -detail $priorMarkerReason
    exit 1
}
$existingMergeHeadResult = Invoke-WeatherQuietGit `
    -Arguments @("rev-parse", "--git-path", "MERGE_HEAD") `
    -Label "existing MERGE_HEAD path query"
$existingMergeHeadRows = @($existingMergeHeadResult.StdoutLines)
$existingMergeHeadExit = [int]$existingMergeHeadResult.ExitCode
if ($existingMergeHeadExit -ne 0 -or $existingMergeHeadRows.Count -ne 1) {
    Fail "could not resolve the existing MERGE_HEAD path"
}
$existingMergeHeadPath = ([string]$existingMergeHeadRows[0]).Trim()
if (-not [IO.Path]::IsPathRooted($existingMergeHeadPath)) {
    $existingMergeHeadPath = Join-Path $repo $existingMergeHeadPath
}
$script:quietMergeHeadPath = [IO.Path]::GetFullPath($existingMergeHeadPath)
if (-not $script:quietMergeHeadPath.Equals(
        ([IO.Path]::GetFullPath((Join-Path $quietGitDirectory "MERGE_HEAD"))),
        [StringComparison]::OrdinalIgnoreCase
    )) {
    Fail "Git redirected MERGE_HEAD outside the frozen ordinary .git directory"
}
if (Test-Path -LiteralPath $existingMergeHeadPath -PathType Leaf) {
    Fail "a merge is already in progress (.git/MERGE_HEAD exists) - resolve or abort it first; see data/alerts/boot_events.jsonl for an interrupted-merge record"
}
try {
    Assert-WeatherIntegrationQuietMergePreconditions -RepositoryRoot $repo |
        Out-Null
    Note "shared quiet-merge production preflight passed"
}
catch { Fail $_.Exception.Message }
try { Assert-OneShotPushTask }
catch { Fail $_.Exception.Message }
# WeatherLocationConfigRefresh rewrites the two config files every 6 hours, including once
# just before this window. Refusing that generated drift would make this tool abort on an
# otherwise normal production tree. The guard exists so a rollback cannot destroy WORK;
# these two files are fleet-regenerated state, not authored work. Commit them rather than
# ignore them, which both cleans the tree and preserves the drift, and only then take the
# rollback point. Keep this list exact: no other dirty tracked path may pass automatically.
$autoRefreshed = @(
    "config/locations.json",
    "config/location_market_events.json"
)
$dirtyTrackedResult = Invoke-WeatherQuietGit `
    -Arguments @("status", "--porcelain") `
    -Label "pre-merge tracked worktree-status query"
$dirtyTracked = @($dirtyTrackedResult.StdoutLines | Where-Object {
    $_ -and $_ -notmatch '^\?\?'
})
if ([int]$dirtyTrackedResult.ExitCode -ne 0) {
    Fail "could not inspect tracked worktree state before merge"
}
$unexpected = @($dirtyTracked | Where-Object {
        $p = ($_ -replace '^..\s*', '').Trim()
        $autoRefreshed -notcontains $p
    })
if ($unexpected.Count -gt 0) {
    Fail "tracked files are modified outside the fleet-generated drift set; commit or stash first so rollback cannot lose work:`n$($unexpected -join "`n")"
}

# Every production merge consumes freshly queried canonical live refs. A
# failed live query or exact-ref fetch is a blocker for both manifest and
# direct/manual callers; no mutation may continue from a stale tracking ref.
$gitFetchExit = 0
$gitFetchFailure = $null
try {
    if ($Branch -cnotmatch
            '^origin/(?<topic>[A-Za-z0-9][A-Za-z0-9._/-]{0,192})$') {
        throw "Production quiet merge requires Branch in exact origin/<topic> form."
    }
    $topicName = [string]$Matches.topic
    $topicRemoteRef = "refs/heads/$topicName"
    $topicTrackingRef = "refs/remotes/origin/$topicName"
    $topicRefCheckResult = Invoke-WeatherQuietGit `
        -Arguments @("check-ref-format", $topicRemoteRef) `
        -Label "exact topic ref-format query"
    $topicRefCheckExit = [int]$topicRefCheckResult.ExitCode
    if ($topicRefCheckExit -ne 0) {
        throw "Production integration topic ref is not a safe Git heads ref."
    }
    if ($ExpectedTip -notmatch '^[0-9a-f]{40}$') {
        throw "Production integration requires an exact expected topic commit id."
    }

    # Fetching a URL without a refspec updates only FETCH_HEAD; it does not
    # refresh refs/remotes/origin/*. Prove both live heads independently,
    # then update the exact two tracking refs that the merge consumes.
    $liveTopicTip = Get-WeatherIntegrationCanonicalRemoteTip `
        -Root $repo -ExpectedUrl $ExpectedOriginUrl `
        -RemoteRef $topicRemoteRef `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
        -Label "quiet-window canonical live topic verification"
    if ($liveTopicTip -ne $ExpectedTip) {
        throw (
            "Live topic moved before guarded merge. Expected $ExpectedTip; " +
            "got $liveTopicTip"
        )
    }
    $liveMasterTip = Get-WeatherIntegrationCanonicalRemoteTip `
        -Root $repo -ExpectedUrl $ExpectedOriginUrl `
        -RemoteRef "refs/heads/master" `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
        -Label "quiet-window canonical live master verification"
    if (-not $ExpectedBaseline) {
        $ExpectedBaseline = $liveMasterTip
        Note "canonical live master bound as direct-call baseline: $ExpectedBaseline"
    }
    elseif ($liveMasterTip -ne $ExpectedBaseline) {
        throw (
            "Live master moved before guarded merge. Expected " +
            "$ExpectedBaseline; got $liveMasterTip"
        )
    }
    $topicFetchRefspec = "+${topicRemoteRef}:${topicTrackingRef}"
    $masterFetchRefspec = "+refs/heads/master:refs/remotes/origin/master"
    Invoke-WeatherIntegrationBoundedRemoteGit `
        -Root $repo `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
        -Arguments @(
            "fetch", "--no-tags", $ExpectedOriginUrl,
            $topicFetchRefspec, $masterFetchRefspec
        ) `
        -Label "quiet-window exact live tracking-ref refresh" | Out-Null
}
catch {
    $gitFetchExit = 1
    $gitFetchFailure = $_.Exception.Message
}
if ($gitFetchExit -ne 0) {
    Fail "production integration requires a successful canonical live origin refresh immediately before merge: $gitFetchFailure"
}
$branchCommitRef = "{0}^{{commit}}" -f $Branch
$branchVerifyResult = Invoke-WeatherQuietGit `
    -Arguments @("rev-parse", "--verify", $branchCommitRef) `
    -Label "post-fetch branch existence query"
$branchVerifyExit = [int]$branchVerifyResult.ExitCode
if ($branchVerifyExit -ne 0) { Fail "branch not found: $Branch" }
$resolvedBranchTipResult = Invoke-WeatherQuietGit `
    -Arguments @("rev-parse", $branchCommitRef) `
    -Label "post-fetch exact branch-tip query"
$resolvedBranchTipRows = @($resolvedBranchTipResult.StdoutLines)
$resolvedBranchTip = if ($resolvedBranchTipRows.Count -eq 1) {
    ([string]$resolvedBranchTipRows[0]).Trim().ToLowerInvariant()
}
else { "" }
$resolvedBranchTipExit = [int]$resolvedBranchTipResult.ExitCode
if ($resolvedBranchTipExit -ne 0 -or $resolvedBranchTip -ne $ExpectedTip) {
    Fail "branch tip moved: $Branch resolves to $resolvedBranchTip, expected reviewed tip $ExpectedTip"
}
Note "exact-tip binding passed: $Branch -> $resolvedBranchTip"
# Merge the immutable object, not the movable ref, even for an interactive
# caller that omitted ExpectedTip. A later ref update cannot change the tree.
$mergeTarget = $resolvedBranchTip
$headResult = Invoke-WeatherQuietGit `
    -Arguments @("rev-parse", "HEAD") -Label "pre-merge HEAD query"
$headRows = @($headResult.StdoutLines)
$head = if ($headRows.Count -eq 1) { ([string]$headRows[0]).Trim() } else { "" }
$headExit = [int]$headResult.ExitCode
$originMasterResult = Invoke-WeatherQuietGit `
    -Arguments @("rev-parse", "origin/master") `
    -Label "pre-merge origin/master query"
$originMasterRows = @($originMasterResult.StdoutLines)
$originMaster = if ($originMasterRows.Count -eq 1) {
    ([string]$originMasterRows[0]).Trim()
}
else { "" }
$originMasterExit = [int]$originMasterResult.ExitCode
$currentBranchResult = Invoke-WeatherQuietGit `
    -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
    -Label "pre-merge current-branch query"
$currentBranchOutput = @($currentBranchResult.StdoutLines)
$currentBranchExit = [int]$currentBranchResult.ExitCode
$currentBranch = if ($currentBranchOutput.Count -eq 0) { "" } else { ([string]$currentBranchOutput[-1]).Trim() }
if ($headExit -ne 0 -or $originMasterExit -ne 0 -or
    $currentBranchExit -ne 0 -or $currentBranch -ne "master") {
    Fail "production working tree must have master checked out; current branch is $currentBranch"
}
if ($head -ne $originMaster) { Fail "local master ($head) != origin/master ($originMaster); reconcile first" }
if ($ExpectedBaseline -and ($head.ToLowerInvariant() -ne $ExpectedBaseline -or
    $originMaster.ToLowerInvariant() -ne $ExpectedBaseline)) {
    Fail "production baseline moved: master=$head origin/master=$originMaster expected=$ExpectedBaseline"
}
$baselineCommit = $head.ToLowerInvariant()
if (-not $ExpectedBaseline) {
    # Direct/manual callers historically omitted the frozen baseline. Once the
    # synchronized local/remote identity is proved under the workload lease,
    # bind that observed baseline into every crash marker and terminal report.
    $ExpectedBaseline = $baselineCommit
    Note "observed synchronized baseline bound for crash recovery: $ExpectedBaseline"
}
foreach ($relativePath in $autoRefreshed) {
    $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
    if (Test-Path -LiteralPath $absolutePath -PathType Leaf) {
        $rollbackContentSha256[$relativePath] = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
if ($rollbackContentSha256.Count -ne $autoRefreshed.Count) {
    Fail "both fleet-generated config files must exist before merge preparation"
}

function Restore-PreparedBaseline {
    $resetResult = Invoke-WeatherQuietGit `
        -Arguments @("reset", "--mixed", $baselineCommit) `
        -Label "prepared-baseline mixed reset"
    $resetExit = [int]$resetResult.ExitCode
    $actualHeadResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "HEAD") `
        -Label "prepared-baseline restored HEAD query"
    $actualHeadRows = @($actualHeadResult.StdoutLines)
    $actualHead = if ($actualHeadRows.Count -eq 1) {
        ([string]$actualHeadRows[0]).Trim().ToLowerInvariant()
    }
    else { "" }
    $headQueryExit = [int]$actualHeadResult.ExitCode
    $trackedResult = Invoke-WeatherQuietGit `
        -Arguments @("status", "--porcelain") `
        -Label "prepared-baseline restored status query"
    $tracked = @($trackedResult.StdoutLines | Where-Object {
        $_ -and $_ -notmatch '^\?\?'
    })
    $statusQueryExit = [int]$trackedResult.ExitCode
    $unexpectedPaths = @($tracked | Where-Object {
            $path = ($_ -replace '^..\s*', '').Trim()
            $autoRefreshed -notcontains $path
        })
    $contentMismatch = @()
    foreach ($relativePath in $rollbackContentSha256.Keys) {
        $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                [string]$rollbackContentSha256[$relativePath]) {
            $contentMismatch += $relativePath
        }
    }
    return [PSCustomObject]@{
        ok = ($resetExit -eq 0 -and $headQueryExit -eq 0 -and
            $statusQueryExit -eq 0 -and $actualHead -eq $baselineCommit -and
            $unexpectedPaths.Count -eq 0 -and $contentMismatch.Count -eq 0)
        git_exit = $resetExit
        head_query_exit = $headQueryExit
        status_query_exit = $statusQueryExit
        actual_head = $actualHead
        unexpected_paths = @($unexpectedPaths)
        content_mismatch = @($contentMismatch)
    }
}

function Stop-AfterPreparationFailure {
    param([Parameter(Mandatory = $true)][string]$Reason)

    try {
        $restored = Restore-PreparedBaseline
    }
    catch {
        $detail = (
            "pre-merge failure could not execute its bounded baseline recovery; " +
            "recovery_error=$($_.Exception.Message); original=$Reason"
        )
        Note $detail
        try {
            Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        }
        catch {
            Note "rollback-failure report persistence also failed: $($_.Exception.Message)"
        }
        exit 4
    }
    if (-not $restored.ok) {
        $detail = "pre-merge failure could not restore successor-resumable baseline $baselineCommit; git_exit=$($restored.git_exit) head=$($restored.actual_head) unexpected_dirty=$(@($restored.unexpected_paths).Count) content_mismatch=$(@($restored.content_mismatch) -join ','); original=$Reason"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }
    Note "ABORT: $Reason; synchronized baseline restored with generated config preserved as allowlisted drift"
    Save-Report -ok $false -stage "abort" -detail $Reason
    exit 1
}

# Journal before the optional generated-config commit. A hard kill after git
# add or commit but before the later prepared-phase update can then restore the
# synchronized baseline with the exact pre-recorded config bytes intact.
$preMerge = $baselineCommit
try {
    Write-QuietMergeMarker -Phase "preparing"
    $activeMarkerOwned = $true
}
catch {
    Stop-AfterPreparationFailure "durable quiet-merge preparation marker could not be created"
}

if ($dirtyTracked.Count -gt 0) {
    Note "committing $($dirtyTracked.Count) fleet-generated drift file(s) so the merge starts clean"
    try {
        $gitAddResult = Invoke-WeatherQuietGit `
            -Arguments (@("add", "--") + @($autoRefreshed)) `
            -Label "fleet-generated drift staging"
    }
    catch {
        Stop-AfterPreparationFailure (
            "bounded generated-drift staging failed: $($_.Exception.Message)"
        )
    }
    $gitAddExit = [int]$gitAddResult.ExitCode
    if ($gitAddExit -ne 0) {
        Stop-AfterPreparationFailure (
            "failed to stage fleet-generated drift (git exit $gitAddExit)"
        )
    }
    try {
        $gitCommitResult = Invoke-WeatherQuietGit `
            -Arguments @(
                "commit", "-m",
                "ops: preserve fleet-generated drift (pre-merge, automated)"
            ) `
            -Label "fleet-generated drift commit"
    }
    catch {
        Stop-AfterPreparationFailure (
            "bounded generated-drift commit failed: $($_.Exception.Message)"
        )
    }
    $gitCommitExit = [int]$gitCommitResult.ExitCode
    if ($gitCommitExit -ne 0) {
        Stop-AfterPreparationFailure (
            "failed to commit fleet-generated drift (git exit $gitCommitExit)"
        )
    }
}
# Take the immediate rollback point after the drift commit. Failure first
# restores this exact tree, then mixed-resets the original baseline so the
# generated contents survive as allowlisted working-tree drift.
try {
    $preMergeResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "HEAD") `
        -Label "exact pre-merge commit query"
}
catch {
    Stop-AfterPreparationFailure (
        "bounded exact pre-merge identity query failed: $($_.Exception.Message)"
    )
}
$preMergeRows = @($preMergeResult.StdoutLines)
$preMerge = if ($preMergeRows.Count -eq 1) {
    ([string]$preMergeRows[0]).Trim()
}
else { "" }
$preMergeQueryExit = [int]$preMergeResult.ExitCode
if ($preMergeQueryExit -ne 0 -or $preMerge -notmatch '^[0-9a-fA-F]{40}$') {
    Stop-AfterPreparationFailure "could not freeze the exact pre-merge commit"
}
try {
    # Refresh the preparation journal with the exact temporary config commit,
    # but do not call it prepared until the pre-roll producer identities below
    # are durable too. In particular, an active execution tape needs its old
    # source fingerprint recorded before a staged merge can touch the tree.
    Write-QuietMergeMarker -Phase "preparing"
}
catch {
    # If the optional generated-drift commit succeeded but its crash marker
    # could not be persisted, restore synchronized master while retaining the
    # generated contents as the same two allowlisted working-tree changes.
    Stop-AfterPreparationFailure "durable quiet-merge crash marker could not be created"
}
# NEVER redirect a native command's stderr here (no *>$null, no 2>&1). Under
# $ErrorActionPreference='Stop', PowerShell 5.1 wraps each redirected stderr line in a
# NativeCommandError and terminates -- and git writes routine notices to stderr, so a
# harmless "CRLF will be replaced by LF" warning killed a dry run mid-merge and left the
# tree in a half-merged state (2026-07-25). Send stdout to Out-Null and let stderr print.
Note "pre-merge HEAD $preMerge; merging $Branch ($($resolvedBranchTip.Substring(0, 12)))"

# ---- capture baseline (what we will require to still be true afterwards) ----
# Command lines are hidden for S4U-owned processes, and one fresh snapshot heartbeat says
# nothing about the CLOB or observation workers. The checker validates all three workers'
# status + writer-lock PID, process liveness, heartbeat freshness, and loaded-source
# fingerprint against the current tree. That is the same recovery contract supervisors own.
function Get-WeatherQuietTextSha256 {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        [byte[]]$bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return (([BitConverter]::ToString($sha.ComputeHash($bytes))) `
            -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Assert-WeatherQuietPythonCacheRoot {
    if ([string]::IsNullOrWhiteSpace($script:quietPythonCacheRoot)) {
        throw "quiet-window Python cache root was not initialized"
    }
    $expectedParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $actualParent = [IO.Path]::GetFullPath(
        (Split-Path -Parent $script:quietPythonCacheRoot)
    ).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    if ($actualParent -ine $expectedParent -or
        (Split-Path -Leaf $script:quietPythonCacheRoot) -cnotmatch
            '^weather-quiet-python-[0-9a-f]{32}$') {
        throw "quiet-window Python cache root is outside its exact owned namespace"
    }
    Assert-WeatherQuietMergeRegularPathAncestry `
        -Path (Join-Path $script:quietPythonCacheRoot "cache-entry") `
        -Label "quiet-window Python cache root"
    $item = Get-Item -LiteralPath $script:quietPythonCacheRoot `
        -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        @([IO.Directory]::EnumerateFileSystemEntries(
            $script:quietPythonCacheRoot
        )).Count -ne 0) {
        throw "quiet-window Python cache root is not one empty regular directory"
    }
}

function Initialize-WeatherQuietPythonCacheRoot {
    if (-not [string]::IsNullOrWhiteSpace($script:quietPythonCacheRoot)) {
        Assert-WeatherQuietPythonCacheRoot
        return
    }
    $candidate = Join-Path ([IO.Path]::GetTempPath()) (
        "weather-quiet-python-" + [guid]::NewGuid().ToString("N")
    )
    if (Test-Path -LiteralPath $candidate) {
        throw "quiet-window unique Python cache root already exists"
    }
    [void][IO.Directory]::CreateDirectory($candidate)
    $script:quietPythonCacheRoot = [IO.Path]::GetFullPath($candidate)
    $script:quietPythonEnvironment["PYTHONPYCACHEPREFIX"] =
        $script:quietPythonCacheRoot
    Assert-WeatherQuietPythonCacheRoot
}

function Remove-WeatherQuietPythonCacheRoot {
    if ([string]::IsNullOrWhiteSpace($script:quietPythonCacheRoot)) { return }
    Assert-WeatherQuietPythonCacheRoot
    Remove-Item -LiteralPath $script:quietPythonCacheRoot `
        -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $script:quietPythonCacheRoot) {
        throw "quiet-window Python cache-root cleanup was not proved"
    }
    $script:quietPythonCacheRoot = $null
}

function Test-WeatherQuietPythonAuthorityArtifact {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $normalized = $RelativePath.Replace("\", "/")
    $leaf = [IO.Path]::GetFileName($normalized)
    $extension = [IO.Path]::GetExtension($normalized)
    $controlNames = @(
        "sitecustomize.py", "conftest.py", "pytest.ini", "pyproject.toml",
        "tox.ini", "setup.cfg"
    )
    $extensions = @(
        ".py", ".pyi", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib"
    )
    $isRootControl = ($normalized -notmatch '/' -and
        ($controlNames -icontains $leaf -or $extensions -icontains $extension))
    $topLevel = @($normalized.Split('/'))[0]
    $isImportArtifact = ($normalized -match '/' -and
        $script:quietPythonAuthorityRoots -icontains $topLevel -and
        ($controlNames -icontains $leaf -or $extensions -icontains $extension))
    return ($isRootControl -or $isImportArtifact)
}

function Get-WeatherQuietMergeHead {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $path = [IO.Path]::GetFullPath($script:quietMergeHeadPath)
    if (-not (Test-Path -LiteralPath $path)) {
        if ($Expected) { throw "$Label expected MERGE_HEAD is absent" }
        return ""
    }
    Assert-WeatherQuietMergeRegularPathAncestry -Path $path -Label "$Label MERGE_HEAD"
    $stream = $null
    try {
        $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
        if ($item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label MERGE_HEAD is not one regular file"
        }
        $stream = [IO.File]::Open(
            $path, [IO.FileMode]::Open, [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        if ($stream.Length -le 0 -or $stream.Length -gt 256) {
            throw "$Label MERGE_HEAD exceeds its one-commit contract"
        }
        [byte[]]$bytes = New-Object byte[] ([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $read = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($read -le 0) { throw "$Label MERGE_HEAD ended during retained read" }
            $offset += $read
        }
        $decoder = New-Object Text.UTF8Encoding($false, $true)
        $actual = $decoder.GetString($bytes).Trim().ToLowerInvariant()
        if ($actual -cnotmatch '^[0-9a-f]{40}$' -or
            (-not [string]::IsNullOrWhiteSpace($Expected) -and
                $actual -cne $Expected.ToLowerInvariant())) {
            throw "$Label MERGE_HEAD does not equal the exact expected merge tip"
        }
        if ([string]::IsNullOrWhiteSpace($Expected)) {
            throw "$Label unexpectedly has MERGE_HEAD"
        }
        return $actual
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
    }
}

function Invoke-WeatherQuietGitLfsInventory {
    param([Parameter(Mandatory = $true)][string]$Label)

    Assert-WeatherIntegrationSafeGitEnvironment -Phase $Label
    return Invoke-WeatherIntegrationBoundedProcess `
        -Executable $gitLfsExecutable `
        -ExpectedExecutableSha256 ([string]$gitLfsExecutablePin.Sha256) `
        -Arguments @("ls-files", "--long") `
        -WorkingDirectory $repo `
        -TimeoutSeconds 60 `
        -Label $Label `
        -MaxOutputBytes 1048576 `
        -RemoveEnvironmentVariables @(Get-WeatherIntegrationBlockedGitEnvironmentNames) `
        -Environment @{
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
}

function Get-WeatherQuietLoadedSourceFingerprint {
    param(
        [Parameter(Mandatory = $true)][string[]]$RelativePaths,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $sortedPaths = @($RelativePaths | Sort-Object -Unique)
    if ($sortedPaths.Count -le 0 -or $sortedPaths.Count -gt 4096 -or
        $sortedPaths.Count -ne $RelativePaths.Count) {
        throw "$Label loaded-source scope is empty, duplicated, or exceeds 4096 files"
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
                throw "$Label loaded-source scope escapes canonical Python source roots"
            }
            $absolute = [IO.Path]::GetFullPath(
                (Join-Path $repo ($relativePath -replace '/', '\'))
            )
            Assert-WeatherQuietMergeRegularPathAncestry `
                -Path $absolute -Label "$Label loaded-source file"
            $item = Get-Item -LiteralPath $absolute -Force -ErrorAction Stop
            if ($item.PSIsContainer -or
                ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                [int64]$item.Length -gt 67108864) {
                throw "$Label loaded-source file is non-regular or exceeds 64 MiB"
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
                        throw "$Label loaded-source bytes exceed the 128 MiB bound"
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

function Get-WeatherQuietTrackedContentFingerprint {
    param([Parameter(Mandatory = $true)][string]$Label)

    $stageQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repo -Arguments @("ls-files", "--stage", "-z") `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
        -Label "$Label index stage inventory"
    $flagQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repo -Arguments @("ls-files", "-v", "-z") `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
        -Label "$Label index visibility flags"
    $lfsQuery = Invoke-WeatherQuietGitLfsInventory -Label "$Label Git LFS inventory"
    $stageRows = @(([string]$stageQuery.Stdout).Split(
        [char]0, [StringSplitOptions]::RemoveEmptyEntries
    ))
    $flagRows = @(([string]$flagQuery.Stdout).Split(
        [char]0, [StringSplitOptions]::RemoveEmptyEntries
    ))
    if ($stageRows.Count -le 0 -or $flagRows.Count -ne $stageRows.Count -or
        $stageRows.Count -gt 100000) {
        throw "$Label tracked inventory is empty, mismatched, or exceeds 100000 files"
    }
    $indexRows = @{}
    $derivedRoots = New-Object System.Collections.Generic.List[string]
    foreach ($row in $stageRows) {
        $match = [regex]::Match(
            [string]$row,
            '^(?<mode>[0-7]{6}) (?<blob>[0-9a-f]{40,64}) (?<stage>[0-3])\t(?<path>.+)$'
        )
        if (-not $match.Success -or [string]$match.Groups["stage"].Value -cne "0") {
            throw "$Label tracked index has an unreadable or non-stage-zero entry"
        }
        $path = [string]$match.Groups["path"].Value
        if ([string]::IsNullOrWhiteSpace($path) -or
            $path.IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0 -or
            [IO.Path]::IsPathRooted($path) -or
            @($path.Replace("\", "/").Split('/') | Where-Object {
                $_ -in @("", ".", "..")
            }).Count -ne 0 -or $indexRows.ContainsKey($path)) {
            throw "$Label tracked index contains an unsafe or duplicate path"
        }
        $indexRows[$path] = [pscustomobject]@{
            Mode = [string]$match.Groups["mode"].Value
            Blob = [string]$match.Groups["blob"].Value
            Path = $path.Replace("\", "/")
        }
        $extension = [IO.Path]::GetExtension($path)
        if ($extension -in @(
                ".py", ".pyi", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib"
            ) -and $path -match '/') {
            $rootName = $path.Replace("\", "/").Split('/')[0]
            if ($rootName -ine "data" -and
                -not $derivedRoots.Contains($rootName)) {
                $derivedRoots.Add($rootName)
            }
        }
    }
    $script:quietPythonAuthorityRoots = @(
        @("app", "scripts", "src", "tests", "tools", "weather") +
        @($derivedRoots) | Sort-Object -Unique
    )
    $flagByPath = @{}
    foreach ($row in $flagRows) {
        $match = [regex]::Match([string]$row, '^(?<tag>.?) (?<path>.+)$')
        if (-not $match.Success) {
            throw "$Label index flag inventory is unreadable"
        }
        $tag = [string]$match.Groups["tag"].Value
        $path = [string]$match.Groups["path"].Value
        if ($tag -ceq "S" -or $tag -cmatch '^[a-z]$') {
            throw "$Label refuses skip-worktree or assume-unchanged index flags: $path"
        }
        if (-not $indexRows.ContainsKey($path) -or $flagByPath.ContainsKey($path)) {
            throw "$Label index flag inventory does not match the stage inventory"
        }
        $flagByPath[$path] = $tag
    }
    $lfsByPath = @{}
    foreach ($row in @($lfsQuery.StdoutLines)) {
        $match = [regex]::Match(
            [string]$row, '^(?<oid>[0-9a-f]{64}) (?<kind>[*-]) (?<path>.+)$'
        )
        if (-not $match.Success) {
            throw "$Label Git LFS inventory is unreadable"
        }
        $path = [string]$match.Groups["path"].Value
        if (-not $indexRows.ContainsKey($path) -or $lfsByPath.ContainsKey($path)) {
            throw "$Label Git LFS inventory does not map one-to-one to tracked paths"
        }
        $lfsByPath[$path] = [pscustomobject]@{
            Oid = [string]$match.Groups["oid"].Value
            Kind = [string]$match.Groups["kind"].Value
        }
    }
    $aggregate = [Security.Cryptography.SHA256]::Create()
    $totalBytes = [int64]0
    $hydratedLfs = 0
    $pointerLfs = 0
    try {
        foreach ($path in @($indexRows.Keys | Sort-Object)) {
            $index = $indexRows[$path]
            $absolute = [IO.Path]::GetFullPath(
                (Join-Path $repo ($path -replace '/', '\'))
            )
            if (-not $absolute.StartsWith(
                    [IO.Path]::GetFullPath($repo).TrimEnd('\') + '\',
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                throw "$Label tracked working path escaped the repository"
            }
            Assert-WeatherQuietMergeRegularPathAncestry `
                -Path $absolute -Label "$Label tracked working file"
            $item = Get-Item -LiteralPath $absolute -Force -ErrorAction Stop
            if ($item.PSIsContainer -or
                ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                [int64]$item.Length -gt 268435456) {
                throw "$Label tracked working file is non-regular or exceeds 256 MiB: $path"
            }
            $stream = $null
            $fileSha = [Security.Cryptography.SHA256]::Create()
            $prefix = New-Object IO.MemoryStream
            try {
                $stream = [IO.File]::Open(
                    $absolute, [IO.FileMode]::Open, [IO.FileAccess]::Read,
                    [IO.FileShare]::Read
                )
                [byte[]]$buffer = New-Object byte[] 65536
                while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    [void]$fileSha.TransformBlock($buffer, 0, $read, $buffer, 0)
                    if ($prefix.Length -lt 2048) {
                        $prefixWrite = [Math]::Min(
                            $read, [int](2048 - $prefix.Length)
                        )
                        $prefix.Write($buffer, 0, $prefixWrite)
                    }
                    $totalBytes += $read
                    if ($totalBytes -gt 1073741824) {
                        throw "$Label tracked working bytes exceed the 1 GiB bound"
                    }
                }
                [void]$fileSha.TransformFinalBlock([byte[]]@(), 0, 0)
                $workingSha = ([BitConverter]::ToString($fileSha.Hash) `
                    -replace '-', '').ToLowerInvariant()
                $length = [int64]$stream.Length
                $lfsKind = "none"
                $lfsOid = "-"
                $lfsSize = "-"
                if ($lfsByPath.ContainsKey($path)) {
                    $lfs = $lfsByPath[$path]
                    $lfsOid = [string]$lfs.Oid
                    $pointerQuery = Invoke-WeatherIntegrationCheckedLocalGit `
                        -Root $repo `
                        -Arguments @(
                            "cat-file", "blob", [string]$index.Blob
                        ) `
                        -ExpectedGitExecutable $gitExecutable `
                        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
                        -Label "$Label LFS index pointer for $path"
                    $pointerText = ([string]$pointerQuery.Stdout).Replace("`r`n", "`n")
                    $pointerMatch = [regex]::Match(
                        $pointerText,
                        ('\Aversion https://git-lfs\.github\.com/spec/v1\n' +
                         'oid sha256:(?<oid>[0-9a-f]{64})\n' +
                         'size (?<size>0|[1-9][0-9]*)\n\z'),
                        [Text.RegularExpressions.RegexOptions]::CultureInvariant
                    )
                    $parsedLfsSize = [int64]0
                    if (-not [string]::IsNullOrWhiteSpace(
                            [string]$pointerQuery.Stderr
                        ) -or
                        -not $pointerMatch.Success -or
                        [string]$pointerMatch.Groups["oid"].Value -cne $lfsOid -or
                        -not [int64]::TryParse(
                            [string]$pointerMatch.Groups["size"].Value,
                            [Globalization.NumberStyles]::None,
                            [Globalization.CultureInfo]::InvariantCulture,
                            [ref]$parsedLfsSize
                        )) {
                        throw "$Label LFS index blob is not the exact canonical reported pointer: $path"
                    }
                    $lfsSize = $parsedLfsSize.ToString(
                        [Globalization.CultureInfo]::InvariantCulture
                    )
                    if ([string]$lfs.Kind -ceq "-" -or
                        $workingSha -cne $lfsOid -or
                        $length -ne $parsedLfsSize) {
                        throw (
                            "$Label LFS worktree bytes do not match the index pointer " +
                            "OID and canonical size: $path"
                        )
                    }
                    $hydratedLfs++
                    $lfsKind = "hydrated"
                }
                $manifestLine = (
                    "$path`t$([string]$index.Mode)`t$([string]$index.Blob)" +
                    "`t$([string]$flagByPath[$path])`t$lfsKind`t$lfsOid" +
                    "`t$lfsSize`t$length`t$workingSha`n"
                )
                [byte[]]$manifestBytes = [Text.Encoding]::UTF8.GetBytes($manifestLine)
                [void]$aggregate.TransformBlock(
                    $manifestBytes, 0, $manifestBytes.Length, $manifestBytes, 0
                )
            }
            finally {
                if ($null -ne $stream) { $stream.Dispose() }
                $prefix.Dispose()
                $fileSha.Dispose()
            }
        }
        [void]$aggregate.TransformFinalBlock([byte[]]@(), 0, 0)
        $fingerprint = ([BitConverter]::ToString($aggregate.Hash) `
            -replace '-', '').ToLowerInvariant()
    }
    finally { $aggregate.Dispose() }

    $closingStage = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repo -Arguments @("ls-files", "--stage", "-z") `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
        -Label "$Label closing index stage inventory"
    $closingFlags = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repo -Arguments @("ls-files", "-v", "-z") `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
        -Label "$Label closing index visibility flags"
    $closingLfs = Invoke-WeatherQuietGitLfsInventory `
        -Label "$Label closing Git LFS inventory"
    if ([string]$closingStage.StdoutSha256 -cne
            [string]$stageQuery.StdoutSha256 -or
        [string]$closingFlags.StdoutSha256 -cne
            [string]$flagQuery.StdoutSha256 -or
        [string]$closingLfs.StdoutSha256 -cne
            [string]$lfsQuery.StdoutSha256) {
        throw "$Label index or LFS identity changed during tracked-byte fingerprinting"
    }
    return [pscustomobject]@{
        Sha256 = $fingerprint
        FileCount = $stageRows.Count
        TotalBytes = $totalBytes
        LfsCount = $lfsByPath.Count
        HydratedLfsCount = $hydratedLfs
        PointerLfsCount = $pointerLfs
        IndexSha256 = [string]$stageQuery.StdoutSha256
        IndexFlagsSha256 = [string]$flagQuery.StdoutSha256
        LfsIdentitySha256 = [string]$lfsQuery.StdoutSha256
    }
}

function Get-WeatherQuietGitStageObservation {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [AllowEmptyString()][string]$ExpectedMergeHead = "",
        [Parameter(Mandatory = $true)][string]$Label
    )

    $expectedHeadLower = $ExpectedHead.Trim().ToLowerInvariant()
    if ($expectedHeadLower -cnotmatch '^[0-9a-f]{40}$' -or
        ($ExpectedMergeHead -and
            $ExpectedMergeHead.Trim().ToLowerInvariant() -cnotmatch
                '^[0-9a-f]{40}$')) {
        throw "$Label received an invalid expected Git-stage identity"
    }
    $trackedFingerprint = Get-WeatherQuietTrackedContentFingerprint `
        -Label "$Label tracked-content boundary"
    $statusQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repo `
        -Arguments @(
            "status", "--porcelain=v2", "--branch", "--untracked-files=all"
        ) `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
        -Label "$Label exact Git status"
    $statusRows = @($statusQuery.StdoutLines | ForEach-Object { [string]$_ })
    $oidRows = @($statusRows | Where-Object { $_ -match '^# branch\.oid ' })
    $branchRows = @($statusRows | Where-Object { $_ -match '^# branch\.head ' })
    if ($oidRows.Count -ne 1 -or $branchRows.Count -ne 1) {
        throw "$Label Git status lacks one exact branch OID and name"
    }
    $actualHead = ($oidRows[0] -replace '^# branch\.oid\s+', '').Trim().ToLowerInvariant()
    $actualBranch = ($branchRows[0] -replace '^# branch\.head\s+', '').Trim()
    if ($actualHead -cne $expectedHeadLower -or $actualBranch -cne "master") {
        throw "$Label expected checked-out master at $expectedHeadLower"
    }
    $ambiguousUntracked = @($statusRows | Where-Object { $_ -match '^\?\s+"' })
    if ($ambiguousUntracked.Count -ne 0) {
        throw "$Label refuses quoted/ambiguous untracked path evidence"
    }
    $untrackedAuthority = @(
        $statusRows |
            Where-Object { $_ -match '^\?\s+' } |
            ForEach-Object { $_ -replace '^\?\s+', '' } |
            Where-Object { Test-WeatherQuietPythonAuthorityArtifact -RelativePath $_ }
    )
    if ($untrackedAuthority.Count -ne 0) {
        throw (
            "$Label refuses untracked Python/native import or test-config artifacts: " +
            (@($untrackedAuthority | Select-Object -First 10) -join ", ")
        )
    }
    $rootExtensionPathspecs = @(
        ".py", ".pyi", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib"
    ) | ForEach-Object { ":(top,glob)*$_" }
    $derivedRootPathspecs = @($script:quietPythonAuthorityRoots | ForEach-Object {
        ":(top,glob)$_/**"
    })
    $importControlPathspecs = @(
        "sitecustomize.py", "conftest.py", "pytest.ini", "pyproject.toml",
        "tox.ini", "setup.cfg"
    ) + $rootExtensionPathspecs + $derivedRootPathspecs
    $ignoredQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repo `
        -Arguments (@(
            "ls-files", "--others", "--ignored", "--exclude-standard", "--"
        ) + $importControlPathspecs) `
        -ExpectedGitExecutable $gitExecutable `
        -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
        -Label "$Label ignored import/config namespace"
    $ignoredAuthority = @(
        @($ignoredQuery.StdoutLines) |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object {
                Test-WeatherQuietPythonAuthorityArtifact -RelativePath $_
            }
    )
    if ($ignoredAuthority.Count -ne 0) {
        throw (
            "$Label refuses ignored Python/native import or test-config artifacts: " +
            (@($ignoredAuthority | Select-Object -First 10) -join ", ")
        )
    }
    $mergeHead = Get-WeatherQuietMergeHead `
        -Expected $ExpectedMergeHead -Label $Label
    return [pscustomobject]@{
        Head = $actualHead
        Branch = $actualBranch
        MergeHead = $mergeHead
        StatusSha256 = Get-WeatherQuietTextSha256 -Text ([string]$statusQuery.Stdout)
        TrackedContentSha256 = [string]$trackedFingerprint.Sha256
        TrackedFileCount = [int]$trackedFingerprint.FileCount
        TrackedTotalBytes = [int64]$trackedFingerprint.TotalBytes
        LfsCount = [int]$trackedFingerprint.LfsCount
        HydratedLfsCount = [int]$trackedFingerprint.HydratedLfsCount
        PointerLfsCount = [int]$trackedFingerprint.PointerLfsCount
        IndexSha256 = [string]$trackedFingerprint.IndexSha256
        IndexFlagsSha256 = [string]$trackedFingerprint.IndexFlagsSha256
        LfsIdentitySha256 = [string]$trackedFingerprint.LfsIdentitySha256
    }
}

function Assert-WeatherQuietGitStageUnchanged {
    param(
        [Parameter(Mandatory = $true)][object]$Before,
        [Parameter(Mandatory = $true)][object]$After,
        [Parameter(Mandatory = $true)][string]$Label
    )

    foreach ($property in @(
        "Head", "Branch", "MergeHead", "StatusSha256",
        "TrackedContentSha256", "TrackedFileCount", "TrackedTotalBytes",
        "LfsCount", "HydratedLfsCount", "PointerLfsCount", "IndexSha256",
        "IndexFlagsSha256", "LfsIdentitySha256"
    )) {
        if ([string]$Before.$property -cne [string]$After.$property) {
            throw "$Label changed exact Git stage field $property while the child ran"
        }
    }
}

function Assert-WeatherQuietPythonExecutionIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][string]$ModuleRelativePath,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $executionIdentityProperty = $Payload.PSObject.Properties["execution_identity"]
    if ($null -eq $executionIdentityProperty -or
        $null -eq $executionIdentityProperty.Value -or
        $executionIdentityProperty.Value -is [System.Array]) {
        throw "$Label omitted its execution_identity object"
    }
    $executionIdentity = $executionIdentityProperty.Value
    $runtime = $executionIdentity.runtime_identity
    if ($null -eq $runtime -or $runtime -is [System.Array]) {
        throw "$Label omitted its runtime identity object"
    }
    $expectedModulePath = [IO.Path]::GetFullPath(
        (Join-Path $repo ($ModuleRelativePath -replace '/', '\'))
    )
    try {
        $actualModulePath = [IO.Path]::GetFullPath(
            [string]$executionIdentity.module_path
        )
        $actualRepoRoot = [IO.Path]::GetFullPath([string]$runtime.repo_root)
    }
    catch { throw "$Label returned an invalid module or repository path" }
    $requiredRuntimeFields = @(
        "schema_version", "repo_root", "git_branch", "git_commit",
        "source_fingerprint", "source_file_count", "source_scope",
        "source_scope_files", "identity_source", "python_version"
    )
    if (@($requiredRuntimeFields | Where-Object {
        $null -eq $runtime.PSObject.Properties[$_]
    }).Count -ne 0 -or
        -not $actualModulePath.Equals(
            $expectedModulePath, [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not $actualRepoRoot.Equals(
            [IO.Path]::GetFullPath($repo),
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [string]$runtime.schema_version -cne "runtime_identity_v0.1" -or
        [string]$runtime.git_branch -cne "master" -or
        [string]$runtime.git_commit -cne
            $ExpectedHead.ToLowerInvariant().Substring(0, 12) -or
        [string]$runtime.source_fingerprint -cnotmatch '^[0-9a-f]{16}$' -or
        [string]$runtime.source_scope -cne "loaded_modules" -or
        [string]$runtime.identity_source -cne "git_filesystem" -or
        [string]::IsNullOrWhiteSpace([string]$runtime.python_version)) {
        throw "$Label execution identity is not bound to the expected production stage"
    }
    $scopeFiles = @($runtime.source_scope_files | ForEach-Object { [string]$_ })
    $uniqueScopeFiles = @($scopeFiles | Sort-Object -Unique)
    $expectedModuleRelative = $ModuleRelativePath.Replace("\", "/")
    if ($scopeFiles.Count -le 0 -or
        [int]$runtime.source_file_count -ne $scopeFiles.Count -or
        $uniqueScopeFiles.Count -ne $scopeFiles.Count -or
        ($scopeFiles -join "`n") -cne ($uniqueScopeFiles -join "`n") -or
        $scopeFiles -cnotcontains $expectedModuleRelative) {
        throw "$Label loaded-source scope is incomplete, duplicated, or missing its module"
    }
    foreach ($relativePath in $scopeFiles) {
        if ([string]::IsNullOrWhiteSpace($relativePath) -or
            $relativePath.Contains("\") -or
            [IO.Path]::IsPathRooted($relativePath) -or
            @($relativePath.Split('/') | Where-Object { $_ -eq ".." }).Count -ne 0 -or
            $relativePath -cnotmatch
                '^(?:app\.py|sitecustomize\.py|(?:app|src|weather)/.+\.py)$') {
            throw "$Label loaded-source scope escapes canonical Python source roots"
        }
    }
    $currentLoadedSource = Get-WeatherQuietLoadedSourceFingerprint `
        -RelativePaths $scopeFiles -Label $Label
    if ([string]$currentLoadedSource.Fingerprint -cne
            [string]$runtime.source_fingerprint -or
        [int]$currentLoadedSource.FileCount -ne [int]$runtime.source_file_count) {
        throw "$Label loaded-source fingerprint does not match the retained stage bytes"
    }
    return [pscustomobject]@{
        SourceFingerprint = [string]$runtime.source_fingerprint
        SourceFileCount = [int]$runtime.source_file_count
        SourceTotalBytes = [int64]$currentLoadedSource.TotalBytes
    }
}

function Invoke-WeatherQuietPythonJson {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$ModuleRelativePath,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [AllowEmptyString()][string]$ExpectedMergeHead = "",
        [Parameter(Mandatory = $true)][string]$Label,
        [int[]]$AllowedExitCodes = @(0),
        [ValidateRange(1, 300)][int]$TimeoutSeconds = 60
    )

    Initialize-WeatherQuietPythonCacheRoot
    Assert-WeatherQuietPythonCacheRoot
    $beforeStage = Get-WeatherQuietGitStageObservation `
        -ExpectedHead $ExpectedHead -ExpectedMergeHead $ExpectedMergeHead `
        -Label "$Label before"
    $result = $null
    $primaryFailure = $null
    try {
        $result = Invoke-WeatherIntegrationBoundedProcess `
            -Executable $py `
            -ExpectedExecutableSha256 $pythonExecutableSha256 `
            -Arguments (@("-P", "-B") + $Arguments) `
            -WorkingDirectory $repo `
            -TimeoutSeconds $TimeoutSeconds `
            -Label $Label `
            -AllowedExitCodes $AllowedExitCodes `
            -MaxOutputBytes 1048576 `
            -RemoveEnvironmentVariables $quietPythonRemoveEnvironmentVariables `
            -Environment $quietPythonEnvironment
    }
    catch { $primaryFailure = $_ }
    $afterStage = $null
    try {
        Assert-WeatherQuietPythonCacheRoot
        $afterStage = Get-WeatherQuietGitStageObservation `
            -ExpectedHead $ExpectedHead -ExpectedMergeHead $ExpectedMergeHead `
            -Label "$Label after"
        Assert-WeatherQuietGitStageUnchanged `
            -Before $beforeStage -After $afterStage -Label $Label
    }
    catch {
        if ($null -ne $primaryFailure) {
            $primaryFailure.Exception.Data["weather_stage_recheck_failure"] =
                $_.Exception.Message
            throw $primaryFailure
        }
        throw
    }
    if ($null -ne $primaryFailure) { throw $primaryFailure }
    if ([string]::IsNullOrWhiteSpace([string]$result.Stdout) -or
        [string]$result.StdoutSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "$Label returned no exact retained JSON stdout binding"
    }
    try { $payload = [string]$result.Stdout | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "$Label returned unreadable retained JSON: $($_.Exception.Message)" }
    if ($null -eq $payload -or $payload -is [System.Array]) {
        throw "$Label retained JSON is not one object"
    }
    $identity = Assert-WeatherQuietPythonExecutionIdentity `
        -Payload $payload -ModuleRelativePath $ModuleRelativePath `
        -ExpectedHead $ExpectedHead -Label $Label
    $quietPythonStageProofs.Add([ordered]@{
        label = $Label
        module = $ModuleRelativePath.Replace("\", "/")
        exit_code = [int]$result.ExitCode
        executable_sha256 = [string]$result.ExecutableSha256
        stdout_sha256 = [string]$result.StdoutSha256
        stderr_sha256 = [string]$result.StderrSha256
        git_head = [string]$afterStage.Head
        merge_head = [string]$afterStage.MergeHead
        git_status_sha256 = [string]$afterStage.StatusSha256
        tracked_content_sha256 = [string]$afterStage.TrackedContentSha256
        tracked_file_count = [int]$afterStage.TrackedFileCount
        tracked_total_bytes = [int64]$afterStage.TrackedTotalBytes
        index_sha256 = [string]$afterStage.IndexSha256
        index_flags_sha256 = [string]$afterStage.IndexFlagsSha256
        lfs_identity_sha256 = [string]$afterStage.LfsIdentitySha256
        lfs_count = [int]$afterStage.LfsCount
        hydrated_lfs_count = [int]$afterStage.HydratedLfsCount
        pointer_lfs_count = [int]$afterStage.PointerLfsCount
        source_fingerprint = [string]$identity.SourceFingerprint
        source_file_count = [int]$identity.SourceFileCount
        source_total_bytes = [int64]$identity.SourceTotalBytes
    })
    return [pscustomobject]@{
        Payload = $payload
        ExitCode = [int]$result.ExitCode
        StdoutSha256 = [string]$result.StdoutSha256
        Stderr = [string]$result.Stderr
    }
}

function Get-CaptureState {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [AllowEmptyString()][string]$ExpectedMergeHead = ""
    )

    try {
        $probe = Invoke-WeatherQuietPythonJson `
            -Arguments @(
                "-m", "weather.operations.capture_recovery_check",
                "--repo-root", $repo, "--json"
            ) `
            -ModuleRelativePath "src/weather/operations/capture_recovery_check.py" `
            -ExpectedHead $ExpectedHead -ExpectedMergeHead $ExpectedMergeHead `
            -Label "$Stage capture-recovery probe" `
            -AllowedExitCodes @(0, 2)
        $state = $probe.Payload
        if ([int]$probe.ExitCode -ne 0) { $state.ok = $false }
        return $state
    }
    catch {
        return [PSCustomObject]@{ ok = $false; workers = @(); error = $_.Exception.Message }
    }
}

function Get-ExecutionTapeState {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [AllowEmptyString()][string]$ExpectedMergeHead = ""
    )

    $writerLockPath = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
    try {
        $probe = Invoke-WeatherQuietPythonJson `
            -Arguments @(
                "-m", "weather.operations.execution_tape_supervisor",
                "status", "--stale-after-seconds", "180"
            ) `
            -ModuleRelativePath "src/weather/operations/execution_tape_supervisor.py" `
            -ExpectedHead $ExpectedHead -ExpectedMergeHead $ExpectedMergeHead `
            -Label "$Stage execution-tape status probe" `
            -AllowedExitCodes @(0, 2)
        $exitCode = [int]$probe.ExitCode
        $payload = $probe.Payload
        $health = $payload.health
        $status = $payload.status
        $reasons = New-Object System.Collections.Generic.List[string]
        if ($exitCode -ne 0) { $reasons.Add("status_exit_$exitCode") }
        if (@("RUNNING", "DEGRADED") -notcontains [string]$health.state) {
            $reasons.Add("health_$([string]$health.state)")
        }
        if ($health.pid_alive -ne $true) { $reasons.Add("pid_not_alive") }
        if ($health.runtime_identity_matches_current -ne $true) { $reasons.Add("runtime_identity_stale") }
        if ([string]$health.evidence_integrity -ne "PASS") { $reasons.Add("evidence_integrity_$([string]$health.evidence_integrity)") }
        if ([string]$status.state -ne "CONNECTED") { $reasons.Add("capture_$([string]$status.state)") }
        if ([string]$status.market -ne "all" -or [string]$status.runner -ne "managed_execution_tape") {
            $reasons.Add("managed_scope_mismatch")
        }
        if ($status.managed_process.verified_at_capture -ne $true) {
            $reasons.Add("managed_process_unverified")
        }
        if (-not (Test-Path -LiteralPath $writerLockPath -PathType Leaf)) {
            $reasons.Add("writer_lock_missing")
            $writerLock = $null
        }
        else {
            $writerLock = Get-Content -LiteralPath $writerLockPath -Raw | ConvertFrom-Json
            if ([int]$status.pid -le 0 -or
                [int]$status.pid -ne [int]$status.managed_process.pid -or
                [int]$status.pid -ne [int]$writerLock.pid -or
                [int]$status.pid -ne [int]$writerLock.managed_process.pid -or
                [string]$status.managed_process.creation_time_token -cne
                    [string]$writerLock.managed_process.creation_time_token) {
                $reasons.Add("writer_identity_mismatch")
            }
        }
        $lastHeartbeat = if ($status.last_heartbeat) {
            [string]$status.last_heartbeat
        }
        else {
            [string]$status.updated_at_utc
        }
        return [PSCustomObject]@{
            ok = ($reasons.Count -eq 0)
            pid = [int]$status.pid
            last_heartbeat = $lastHeartbeat
            recorded_source_fingerprint = [string]$status.runtime_identity.source_fingerprint
            reasons = @($reasons)
            health = $health
            status = $status
            writer_lock = $writerLock
        }
    }
    catch {
        return [PSCustomObject]@{
            ok = $false
            pid = 0
            last_heartbeat = $null
            recorded_source_fingerprint = $null
            reasons = @($_.Exception.Message)
            health = $null
            status = $null
            writer_lock = $null
        }
    }
}

function Invoke-RollbackAndProve {
    param(
        [Parameter(Mandatory = $true)][string[]]$Reasons,
        [ValidateSet("rolled_back", "dry_run")][string]$RecoveredStage = "rolled_back",
        [bool]$RecoveredOk = $false,
        [ValidateSet(0, 2)][int]$RecoveredExitCode = 2
    )

    $primaryDetail = ($Reasons | Where-Object { $_ }) -join "; "
    if (-not $primaryDetail) { $primaryDetail = "guarded merge did not complete" }
    Note "merge will not be committed: $primaryDetail"

    try {
    $mergeHeadPathResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "--git-path", "MERGE_HEAD") `
        -Label "rollback MERGE_HEAD path query"
    $mergeHeadPathRows = @($mergeHeadPathResult.StdoutLines)
    $mergeHeadPathExit = [int]$mergeHeadPathResult.ExitCode
    if ($mergeHeadPathExit -ne 0 -or $mergeHeadPathRows.Count -ne 1) {
        $detail = "merge rollback could not resolve MERGE_HEAD; original=$primaryDetail"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }
    $mergeHeadPath = ([string]$mergeHeadPathRows[0]).Trim()
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) {
        $mergeHeadPath = Join-Path $repo $mergeHeadPath
    }
    $restoreExit = 0
    if (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) {
        $restoreResult = Invoke-WeatherQuietGit `
            -Arguments @("merge", "--abort") `
            -Label "guarded merge abort"
        $restoreExit = [int]$restoreResult.ExitCode
    }
    else {
        # A successful explicit commit removes MERGE_HEAD. This path is used
        # only if a later structural check on that unpublished commit failed.
        $restoreResult = Invoke-WeatherQuietGit `
            -Arguments @("reset", "--hard", $preMerge) `
            -Label "post-commit structural-failure hard reset"
        $restoreExit = [int]$restoreResult.ExitCode
    }
    if ($restoreExit -ne 0) {
        $restoreResult = Invoke-WeatherQuietGit `
            -Arguments @("reset", "--hard", $preMerge) `
            -Label "guarded merge rollback hard-reset fallback"
        $restoreExit = [int]$restoreResult.ExitCode
    }

    $restoredHeadResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "HEAD") `
        -Label "rollback restored HEAD query"
    $restoredHeadRows = @($restoredHeadResult.StdoutLines)
    $restoredHead = if ($restoredHeadRows.Count -eq 1) {
        ([string]$restoredHeadRows[0]).Trim().ToLowerInvariant()
    }
    else { "" }
    $restoredHeadExit = [int]$restoredHeadResult.ExitCode
    $remainingMergeHead = Test-Path -LiteralPath $mergeHeadPath -PathType Leaf
    $remainingTrackedResult = Invoke-WeatherQuietGit `
        -Arguments @("status", "--porcelain") `
        -Label "rollback restored worktree-status query"
    $remainingTracked = @($remainingTrackedResult.StdoutLines | Where-Object {
        $_ -and $_ -notmatch '^\?\?'
    })
    $remainingTrackedExit = [int]$remainingTrackedResult.ExitCode
    if ($restoreExit -ne 0 -or $restoredHeadExit -ne 0 -or
        $remainingTrackedExit -ne 0 -or
        $restoredHead -ne $preMerge.ToLowerInvariant() -or
        $remainingMergeHead -or $remainingTracked.Count -ne 0) {
        $detail = "merge rollback could not restore exact pre-merge tree $preMerge; git_exit=$restoreExit head=$restoredHead merge_head=$remainingMergeHead dirty=$($remainingTracked.Count); original=$primaryDetail"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }

    # The automatic generated-config commit is a temporary merge preparation,
    # not a new production baseline. Move master back to the originally
    # synchronized commit with a mixed reset so the exact generated contents
    # survive as the same two allowlisted working-tree changes. A successor can
    # then re-run without first reconciling an unpublished local commit.
    if ($preMerge.ToLowerInvariant() -ne $baselineCommit.ToLowerInvariant()) {
        $baselineResetResult = Invoke-WeatherQuietGit `
            -Arguments @("reset", "--mixed", $baselineCommit) `
            -Label "rollback synchronized-baseline mixed reset"
        $baselineResetExit = [int]$baselineResetResult.ExitCode
        if ($baselineResetExit -ne 0) {
            $detail = "merge rollback reached $preMerge but could not restore synchronized baseline $baselineCommit; git_exit=$baselineResetExit; original=$primaryDetail"
            Note $detail
            Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
            exit 4
        }
    }
    $finalRollbackHeadResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "HEAD") `
        -Label "final rollback HEAD query"
    $finalRollbackHeadRows = @($finalRollbackHeadResult.StdoutLines)
    $finalRollbackHead = if ($finalRollbackHeadRows.Count -eq 1) {
        ([string]$finalRollbackHeadRows[0]).Trim().ToLowerInvariant()
    }
    else { "" }
    $finalRollbackHeadExit = [int]$finalRollbackHeadResult.ExitCode
    $finalTrackedResult = Invoke-WeatherQuietGit `
        -Arguments @("status", "--porcelain") `
        -Label "final rollback worktree-status query"
    $finalTracked = @($finalTrackedResult.StdoutLines | Where-Object {
        $_ -and $_ -notmatch '^\?\?'
    })
    $finalTrackedExit = [int]$finalTrackedResult.ExitCode
    $unexpectedRollbackPaths = @($finalTracked | Where-Object {
            $path = ($_ -replace '^..\s*', '').Trim()
            $autoRefreshed -notcontains $path
        })
    $contentMismatch = @()
    foreach ($relativePath in $rollbackContentSha256.Keys) {
        $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                [string]$rollbackContentSha256[$relativePath]) {
            $contentMismatch += $relativePath
        }
    }
    if ($finalRollbackHeadExit -ne 0 -or $finalTrackedExit -ne 0 -or
        $finalRollbackHead -ne $baselineCommit.ToLowerInvariant() -or
        $unexpectedRollbackPaths.Count -ne 0 -or $contentMismatch.Count -ne 0) {
        $detail = "merge rollback did not leave a successor-resumable baseline; expected_head=$baselineCommit actual_head=$finalRollbackHead unexpected_dirty=$($unexpectedRollbackPaths.Count) content_mismatch=$($contentMismatch -join ','); original=$primaryDetail"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }

    Note "rolled back to synchronized baseline $baselineCommit with generated config preserved as allowlisted drift; nothing was pushed. Waiting up to ${RollbackRecoverySeconds}s for every affected producer to re-adopt the rollback..."
    $rollbackDeadline = [datetimeoffset]::UtcNow.AddSeconds(
        $RollbackRecoverySeconds
    )
    $rollbackStopwatch = [Diagnostics.Stopwatch]::StartNew()
    try {
        do {
            $rollbackState = Get-CaptureState `
                -Stage "rollback" -ExpectedHead $baselineCommit
            $rollbackCoreOk = $rollbackState.ok -and @($rollbackState.workers).Count -eq 3
            $rollbackExecutionState = $null
            $rollbackExecutionOk = $true
            if ($executionTapeRecoveryRequired) {
                $rollbackExecutionState = Get-ExecutionTapeState `
                    -Stage "rollback" -ExpectedHead $baselineCommit
                $rollbackExecutionOk = $rollbackExecutionState.ok -and
                    [string]$rollbackExecutionState.recorded_source_fingerprint -ceq
                        [string]$executionBefore.recorded_source_fingerprint
            }
            if ($rollbackCoreOk -and $rollbackExecutionOk) { break }
            $rollbackWallTimeRemaining = (
                [datetimeoffset]::UtcNow -lt $rollbackDeadline
            )
            $rollbackMonotonicTimeRemaining = (
                $rollbackStopwatch.Elapsed.TotalSeconds -lt
                    [double]$RollbackRecoverySeconds
            )
            if ($rollbackWallTimeRemaining -and $rollbackMonotonicTimeRemaining) {
                Start-Sleep -Seconds 15
            }
        } while ($rollbackWallTimeRemaining -and $rollbackMonotonicTimeRemaining)
    }
    finally {
        $rollbackStopwatch.Stop()
    }

    if (-not $rollbackCoreOk -or -not $rollbackExecutionOk) {
        $rollbackWhy = @(
            $rollbackState.workers |
                Where-Object { -not $_.ok } |
                ForEach-Object { "$($_.name)=$($_.reasons -join ',')" }
        )
        if ($rollbackState.error) { $rollbackWhy += [string]$rollbackState.error }
        if ($executionTapeRecoveryRequired -and -not $rollbackExecutionOk) {
            $rollbackWhy += "execution_tape=$(@($rollbackExecutionState.reasons) -join ','); expected_source=$($executionBefore.recorded_source_fingerprint); actual_source=$($rollbackExecutionState.recorded_source_fingerprint)"
        }
        if ($rollbackWhy.Count -eq 0) { $rollbackWhy += "recovery contract unreadable" }
        $detail = "merge recovery failed: $primaryDetail; rollback recovery unproven: $($rollbackWhy -join '; ')"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }

    Note "every affected producer re-adopted the rollback and satisfies its exact recovery contract"
    Save-Report -ok $RecoveredOk -stage $RecoveredStage -detail $primaryDetail
    exit $RecoveredExitCode
    }
    catch {
        $detail = (
            "merge rollback control failed after its contained Git child was drained; " +
            "recovery_error=$($_.Exception.Message); original=$primaryDetail"
        )
        Note $detail
        try {
            Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        }
        catch {
            Note "rollback-failure report persistence also failed: $($_.Exception.Message)"
        }
        exit 4
    }
}

$before = Get-CaptureState -Stage "pre-merge" -ExpectedHead $preMerge
Note "capture before: ok=$($before.ok), workers=$(@($before.workers).Count)"
if (-not $before.ok -or @($before.workers).Count -ne 3) {
    $detail = @($before.workers | Where-Object { -not $_.ok } | ForEach-Object { "$($_.name)=$($_.reasons -join ',')" }) -join "; "
    if (-not $detail) { $detail = [string]$before.error }
    Stop-AfterPreparationFailure "capture recovery contract is not healthy before merge: $detail"
}
$executionBefore = $null
if ($executionTapeRecoveryRequired) {
    $executionBefore = Get-ExecutionTapeState `
        -Stage "pre-merge" -ExpectedHead $preMerge
    Note "execution tape before: ok=$($executionBefore.ok), pid=$($executionBefore.pid), source=$($executionBefore.recorded_source_fingerprint)"
    if (-not $executionBefore.ok) {
        Stop-AfterPreparationFailure "execution-tape recovery contract is not healthy before merge: $(@($executionBefore.reasons) -join ',')"
    }
    $executionTapeSourceBefore = [string]$executionBefore.recorded_source_fingerprint
}
try {
    Write-QuietMergeMarker -Phase "prepared"
}
catch {
    Stop-AfterPreparationFailure "durable quiet-merge marker could not bind the pre-roll recovery identities"
}

if ($DryRun) {
    $dryControlFailure = $null
    $dryMergeExit = 255
    $conflictQueryExit = 255
    $conflicts = @()
    try {
    $dryMergeResult = Invoke-WeatherQuietGit `
        -Arguments @("merge", "--no-commit", "--no-ff", $mergeTarget) `
        -Label "dry-run no-commit merge" `
        -TimeoutSeconds 300
    $dryMergeExit = [int]$dryMergeResult.ExitCode
    $conflictResult = Invoke-WeatherQuietGit `
        -Arguments @("diff", "--name-only", "--diff-filter=U") `
        -Label "dry-run unmerged-path query"
    $conflicts = @($conflictResult.StdoutLines | Where-Object { $_ })
    $conflictQueryExit = [int]$conflictResult.ExitCode
    # Always unwind: leaving a half-merged tree changes loop-loaded modules on disk and
    # provokes a STALE_CODE readoption roll. `merge --abort` restores the pre-merge state
    # including uncommitted config drift. At this point tracked drift has already been
    # committed, so a hard reset to the exact pre-merge point is a safe fallback.
    $dryAbortResult = Invoke-WeatherQuietGit `
        -Arguments @("merge", "--abort") `
        -Label "dry-run merge abort"
    $dryAbortExit = [int]$dryAbortResult.ExitCode
    if ($dryAbortExit -ne 0) {
        $dryAbortResult = Invoke-WeatherQuietGit `
            -Arguments @("reset", "--hard", $preMerge) `
            -Label "dry-run hard-reset fallback"
        $dryAbortExit = [int]$dryAbortResult.ExitCode
    }
    $dryRestoredHeadResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "HEAD") `
        -Label "dry-run restored HEAD query"
    $dryRestoredHeadRows = @($dryRestoredHeadResult.StdoutLines)
    $dryRestoredHead = if ($dryRestoredHeadRows.Count -eq 1) {
        ([string]$dryRestoredHeadRows[0]).Trim()
    }
    else { "" }
    $dryRestoredHeadExit = [int]$dryRestoredHeadResult.ExitCode
    if ($dryAbortExit -ne 0 -or $dryRestoredHeadExit -ne 0 -or
        $dryRestoredHead -ne $preMerge) {
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail "dry-run merge could not restore $preMerge"
        exit 4
    }
    $dryRestore = Restore-PreparedBaseline
    if (-not $dryRestore.ok) {
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail "dry-run merge could not restore synchronized baseline $baselineCommit with generated bytes intact"
        exit 4
    }
    }
    catch {
        $dryControlFailure = $_.Exception.Message
    }
    if ($dryControlFailure) {
        Invoke-RollbackAndProve -Reasons @(
            "dry-run bounded Git control failed: $dryControlFailure"
        )
    }
    Note "DRY RUN: conflicts=$($conflicts.Count)"
    # Staging the dry merge exposed target bytes to the same supervisors as a
    # real merge. Do not retire its marker merely because Git was restored;
    # prove every affected producer has re-adopted the rollback first.
    $dryRunOk = ($dryMergeExit -eq 0 -and $conflictQueryExit -eq 0)
    $dryRunExitCode = if ($dryRunOk) { 0 } else { 2 }
    Invoke-RollbackAndProve `
        -Reasons @(
            "dry-run merge_exit=$dryMergeExit conflict_query_exit=$conflictQueryExit " +
            "conflicts=$($conflicts.Count)"
        ) `
        -RecoveredStage "dry_run" `
        -RecoveredOk $dryRunOk `
        -RecoveredExitCode $dryRunExitCode
}

# ---- stage locally without committing (this triggers the readoption roll) ----
# MERGE_HEAD is the durable crash marker. Keep it present through the complete
# recovery proof so WeatherBootRecovery can always abort an interrupted,
# unverified roll after power loss. Only a successful proof earns the explicit
# merge commit below.
$mergeCommitted = $false
try {
    $mergeResult = Invoke-WeatherQuietGit `
        -Arguments @("merge", "--no-commit", "--no-ff", $mergeTarget) `
        -Label "guarded no-commit merge" `
        -TimeoutSeconds 300
    $mergeExit = [int]$mergeResult.ExitCode
    if ($mergeExit -ne 0) {
        Invoke-RollbackAndProve -Reasons @("merge failed or conflicted (git exit $mergeExit)")
    }
    $mergeHeadPathResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "--git-path", "MERGE_HEAD") `
        -Label "staged merge MERGE_HEAD path query"
    $mergeHeadPathRows = @($mergeHeadPathResult.StdoutLines)
    $mergeHeadPath = if ($mergeHeadPathRows.Count -eq 1) {
        ([string]$mergeHeadPathRows[0]).Trim()
    }
    else { "" }
    $mergeHeadPathExit = [int]$mergeHeadPathResult.ExitCode
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) {
        $mergeHeadPath = Join-Path $repo $mergeHeadPath
    }
    $stagedHeadResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "HEAD") `
        -Label "staged merge HEAD query"
    $stagedHeadRows = @($stagedHeadResult.StdoutLines)
    $stagedHead = if ($stagedHeadRows.Count -eq 1) {
        ([string]$stagedHeadRows[0]).Trim()
    }
    else { "" }
    $stagedHeadExit = [int]$stagedHeadResult.ExitCode
    if ($mergeHeadPathExit -ne 0 -or $stagedHeadExit -ne 0 -or
        -not (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) -or
        $stagedHead -ne $preMerge) {
        Invoke-RollbackAndProve -Reasons @("no-commit merge did not preserve MERGE_HEAD and the exact pre-merge HEAD")
    }
    Write-QuietMergeMarker -Phase "merge_uncommitted"
    Note "merge staged with MERGE_HEAD preserved (NOT committed or pushed)"

    # ---- wait for every affected producer to readopt, then prove recovery ----
    Note "waiting ${SettleSeconds}s for supervisors to readopt the new code..."
    Start-Sleep -Seconds $SettleSeconds
    $after = Get-CaptureState `
        -Stage "staged-merge" -ExpectedHead $preMerge `
        -ExpectedMergeHead $resolvedBranchTip
    Note "capture after: ok=$($after.ok), workers=$(@($after.workers).Count)"

    $ok = $true
    $why = @()
    if (-not $after.ok -or @($after.workers).Count -ne 3) {
        $ok = $false
        $why += @($after.workers | Where-Object { -not $_.ok } | ForEach-Object { "$($_.name)=$($_.reasons -join ',')" })
        if ($after.error) { $why += [string]$after.error }
    }
    foreach ($beforeWorker in @($before.workers)) {
        $afterWorker = @($after.workers | Where-Object { $_.name -eq $beforeWorker.name }) | Select-Object -First 1
        if (-not $afterWorker) {
            $ok = $false; $why += "$($beforeWorker.name) missing after merge"; continue
        }
        # The snapshot worker normally heartbeats once per roughly ten-minute cycle, longer
        # than the default five-minute settle. Requiring every healthy worker to advance here
        # made a CLOB-only roll depend on where the unrelated snapshot sleep happened to fall.
        # The recovery checker above still requires every worker to be fresh, live, locked by
        # the matching PID, and loaded from the current tree. Require heartbeat advancement in
        # addition when this worker actually readopted (PID or recorded source identity changed).
        $workerReadopted = (
            [int]$afterWorker.pid -ne [int]$beforeWorker.pid -or
            [string]$afterWorker.recorded_source_fingerprint -ne [string]$beforeWorker.recorded_source_fingerprint
        )
        if (-not $workerReadopted) { continue }
        try {
            if ([datetime]$afterWorker.last_heartbeat -le [datetime]$beforeWorker.last_heartbeat) {
                $ok = $false
                $why += "$($beforeWorker.name) readopted but heartbeat did not advance ($($beforeWorker.last_heartbeat) -> $($afterWorker.last_heartbeat))"
            }
        }
        catch { $ok = $false; $why += "$($beforeWorker.name) readoption heartbeat comparison failed" }
    }

    $executionAfter = $null
    if ($executionTapeRecoveryRequired) {
        $executionAfter = Get-ExecutionTapeState `
            -Stage "staged-merge" -ExpectedHead $preMerge `
            -ExpectedMergeHead $resolvedBranchTip
        Note "execution tape after: ok=$($executionAfter.ok), pid=$($executionAfter.pid), source=$($executionAfter.recorded_source_fingerprint)"
        if (-not $executionAfter.ok) {
            $ok = $false
            $why += "execution_tape=$(@($executionAfter.reasons) -join ',')"
        }
        if ($executionTapeReadoptionExpected) {
            if ([string]$executionAfter.recorded_source_fingerprint -ceq
                [string]$executionBefore.recorded_source_fingerprint) {
                $ok = $false
                $why += "execution_tape closure rolled but loaded-source fingerprint did not change"
            }
            try {
                if ([datetime]$executionAfter.last_heartbeat -le [datetime]$executionBefore.last_heartbeat) {
                    $ok = $false
                    $why += "execution_tape readopted but heartbeat did not advance ($($executionBefore.last_heartbeat) -> $($executionAfter.last_heartbeat))"
                }
            }
            catch {
                $ok = $false
                $why += "execution_tape readoption heartbeat comparison failed"
            }
        }
    }

    if (-not $ok) {
        Invoke-RollbackAndProve -Reasons $why
    }
    $captureRecoveryProved = $true
    if ($executionTapeRecoveryRequired) { $executionTapeRecoveryProved = $true }
    Write-QuietMergeMarker -Phase "capture_recovered_uncommitted"

    # Recovery is proved while MERGE_HEAD still makes the operation boot-
    # recoverable. Commit only now, then verify the exact two-parent identity.
    $mergeCommitResult = Invoke-WeatherQuietGit `
        -Arguments @("commit", "-m", "Merge $Branch into master") `
        -Label "recovery-proved merge commit"
    $mergeCommitExit = [int]$mergeCommitResult.ExitCode
    if ($mergeCommitExit -ne 0) {
        Invoke-RollbackAndProve -Reasons @("recovery passed but explicit merge commit failed (git exit $mergeCommitExit)")
    }
    $candidateMergeCommitResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "HEAD") `
        -Label "candidate merge-commit query"
    $candidateMergeCommitRows = @($candidateMergeCommitResult.StdoutLines)
    $candidateMergeCommit = if ($candidateMergeCommitRows.Count -eq 1) {
        ([string]$candidateMergeCommitRows[0]).Trim().ToLowerInvariant()
    }
    else { "" }
    $candidateMergeCommitExit = [int]$candidateMergeCommitResult.ExitCode
    $firstParentResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "$candidateMergeCommit^1") `
        -Label "candidate merge first-parent query"
    $firstParentRows = @($firstParentResult.StdoutLines)
    $firstParent = if ($firstParentRows.Count -eq 1) {
        ([string]$firstParentRows[0]).Trim().ToLowerInvariant()
    }
    else { "" }
    $firstParentExit = [int]$firstParentResult.ExitCode
    $secondParentResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "$candidateMergeCommit^2") `
        -Label "candidate merge second-parent query"
    $secondParentRows = @($secondParentResult.StdoutLines)
    $secondParent = if ($secondParentRows.Count -eq 1) {
        ([string]$secondParentRows[0]).Trim().ToLowerInvariant()
    }
    else { "" }
    $secondParentExit = [int]$secondParentResult.ExitCode
    if ($candidateMergeCommitExit -ne 0 -or $firstParentExit -ne 0 -or
        $secondParentExit -ne 0 -or
        (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) -or
        $firstParent -ne $preMerge.ToLowerInvariant() -or
        $secondParent -ne $resolvedBranchTip.ToLowerInvariant()) {
        Invoke-RollbackAndProve -Reasons @("explicit merge commit did not bind the exact pre-merge and reviewed-tip parents")
    }
    $mergeCommit = $candidateMergeCommit
    Write-QuietMergeMarker -Phase "merge_committed_unpublished"
    $mergeCommitted = $true
    Note "recovery-proved merge committed locally as $mergeCommit (NOT pushed yet)"
}
catch {
    if (-not $mergeCommitted) {
        Invoke-RollbackAndProve -Reasons @(
            "unexpected pre-commit failure: " +
            "$($_.Exception.GetType().Name): $($_.Exception.Message)"
        )
    }
    throw
}

# ---- bind the post-integration documentation transaction before publication ----
# The documentation closeout cannot truthfully finish until the exact merge and live recovery
# exist. Record that debt now, before publication, so a missing morning closeout is visible in
# status and a later transaction can cover the exact pending-state hash. Stacked overnight
# merges append to the same bounded transaction.
$documentationArgs = @(
    "-m", "weather.operations.documentation_transaction",
    "--repo-root", $repo,
    "begin",
    "--integration-tip", $mergeCommit,
    "--branch", $Branch
)
if ($ExpectedTip) { $documentationArgs += @("--expected-tip", $ExpectedTip) }
try {
    $documentationProbe = Invoke-WeatherQuietPythonJson `
        -Arguments $documentationArgs `
        -ModuleRelativePath "src/weather/operations/documentation_transaction.py" `
        -ExpectedHead $mergeCommit `
        -Label "post-merge documentation-transaction begin" `
        -AllowedExitCodes @(0, 1)
    $documentationPayload = $documentationProbe.Payload
    $documentationExit = [int]$documentationProbe.ExitCode
}
catch {
    Note "documentation transaction could not be contained or proved: $($_.Exception.Message)"
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation transaction begin containment or identity failed for local commit $mergeCommit; reviewed resume required"
    exit 3
}
if ($documentationExit -ne 0) {
    Note "documentation transaction could not be recorded: $([string]$documentationPayload.detail)"
    # `begin` atomically updates a shared pending transaction and then its
    # content-addressed snapshot. A nonzero child can therefore be ambiguous
    # about whether that durable mutation happened. Without a compensating
    # transaction it is unsafe to delete the merge it may now reference.
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation transaction begin failed or was ambiguous for local commit $mergeCommit; reviewed resume required"
    exit 3
}
try {
    $pendingSha256 = ([string]$documentationPayload.pending_sha256).ToLowerInvariant()
    $matchingDocumentationEntry = @(
        $documentationPayload.integrations |
            Where-Object {
                ([string]$_.integration_tip).ToLowerInvariant() -eq $mergeCommit -and
                [string]$_.branch -ceq $Branch
            }
    ) | Select-Object -First 1
    if ($pendingSha256 -notmatch '^[0-9a-f]{64}$' -or
        ([string]$documentationPayload.latest_integration_tip).ToLowerInvariant() -ne $mergeCommit -or
        $null -eq $matchingDocumentationEntry -or
        ($ExpectedTip -and ([string]$matchingDocumentationEntry.expected_tip).ToLowerInvariant() -ne $ExpectedTip)) {
        throw "documentation transaction output did not bind the exact integration"
    }
    $documentationPendingPath = Join-Path $repo "data\alerts\documentation_transaction_pending.json"
    $documentationSnapshotRelative = "data/alerts/documentation_transactions/pending-$pendingSha256.json"
    $documentationSnapshotPath = Join-Path $repo ($documentationSnapshotRelative -replace '/', '\')
    $documentationPendingSnapshot = Read-WeatherQuietRetainedSnapshot `
        -Path $documentationPendingPath `
        -Label "documentation transaction mutable pending state" `
        -Json
    $documentationImmutableSnapshot = Read-WeatherQuietRetainedSnapshot `
        -Path $documentationSnapshotPath `
        -Label "documentation transaction immutable snapshot" `
        -Json
    if ([string]$documentationPendingSnapshot.Sha256 -cne $pendingSha256 -or
        [string]$documentationImmutableSnapshot.Sha256 -cne $pendingSha256 -or
        [string]$documentationPendingSnapshot.Text -cne
            [string]$documentationImmutableSnapshot.Text) {
        throw "documentation transaction pending state and immutable snapshot do not match"
    }
    $documentationTransactionPendingSha256 = $pendingSha256
    $documentationTransactionSnapshotPath = $documentationSnapshotRelative
    $documentationTransactionRecorded = $true
}
catch {
    Note "documentation transaction returned success without exact durable identity: $($_.Exception.Message)"
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation transaction identity is ambiguous for local commit $mergeCommit; reviewed resume required"
    exit 3
}
Note "documentation transaction recorded for $mergeCommit"
try {
    Write-QuietMergeMarker -Phase "documented_unpublished"
    $documentedMarkerSha256 = [string]$script:quietActiveMarkerSha256
}
catch {
    # The pending documentation transaction now names this merge. Preserve both
    # and the prior merge_committed_unpublished marker for reviewed, idempotent
    # reconciliation; resetting would create an orphan transaction.
    Note "documentation succeeded but its durable merge marker could not be updated; preserving local merge for reviewed resume"
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation marker update failed for local commit $mergeCommit; reviewed resume required"
    exit 3
}

# ---- only now publish, through the credential-bearing scheduled task ----
# Interactive git push is forbidden on this host. The scheduled task owns the credential
# context, and origin/master is the acknowledgement that the immutable merge commit landed.
$prePublicationFailure = $null
try {
    if (-not [string]::IsNullOrWhiteSpace($ExpectedOriginUrl)) {
        Assert-WeatherIntegrationCanonicalOriginUrl `
            -Root $repo -ExpectedUrl $ExpectedOriginUrl `
            -Phase "quiet-window pre-publication boundary" `
            -ExpectedGitExecutable $gitExecutable `
            -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 | Out-Null
    }
    $finalHeadResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "HEAD") `
        -Label "pre-publication HEAD query"
    $finalHeadRows = @($finalHeadResult.StdoutLines)
    $finalHead = if ($finalHeadRows.Count -eq 1) {
        ([string]$finalHeadRows[0]).Trim().ToLowerInvariant()
    }
    else { "" }
    $finalHeadExit = [int]$finalHeadResult.ExitCode
    $finalMasterResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "master") `
        -Label "pre-publication master query"
    $finalMasterRows = @($finalMasterResult.StdoutLines)
    $finalMaster = if ($finalMasterRows.Count -eq 1) {
        ([string]$finalMasterRows[0]).Trim().ToLowerInvariant()
    }
    else { "" }
    $finalMasterExit = [int]$finalMasterResult.ExitCode
    $finalOriginMasterResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "origin/master") `
        -Label "pre-publication origin/master query"
    $finalOriginMasterRows = @($finalOriginMasterResult.StdoutLines)
    $finalOriginMaster = if ($finalOriginMasterRows.Count -eq 1) {
        ([string]$finalOriginMasterRows[0]).Trim().ToLowerInvariant()
    }
    else { "" }
    $finalOriginMasterExit = [int]$finalOriginMasterResult.ExitCode
    $finalBranchResult = Invoke-WeatherQuietGit `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
        -Label "pre-publication current-branch query"
    $finalBranchRows = @($finalBranchResult.StdoutLines)
    $finalBranch = if ($finalBranchRows.Count -eq 1) {
        ([string]$finalBranchRows[0]).Trim()
    }
    else { "" }
    $finalBranchExit = [int]$finalBranchResult.ExitCode
    $finalMergeHeadPathResult = Invoke-WeatherQuietGit `
        -Arguments @("rev-parse", "--git-path", "MERGE_HEAD") `
        -Label "pre-publication MERGE_HEAD path query"
    $finalMergeHeadPathRows = @($finalMergeHeadPathResult.StdoutLines)
    $finalMergeHeadPath = if ($finalMergeHeadPathRows.Count -eq 1) {
        ([string]$finalMergeHeadPathRows[0]).Trim()
    }
    else { "" }
    $finalMergeHeadPathExit = [int]$finalMergeHeadPathResult.ExitCode
    if (-not [IO.Path]::IsPathRooted($finalMergeHeadPath)) {
        $finalMergeHeadPath = Join-Path $repo $finalMergeHeadPath
    }
    if ($finalHeadExit -ne 0 -or $finalMasterExit -ne 0 -or
        $finalOriginMasterExit -ne 0 -or $finalBranchExit -ne 0 -or
        $finalMergeHeadPathExit -ne 0 -or
        $finalBranch -ne "master" -or $finalHead -ne $mergeCommit -or
        $finalMaster -ne $mergeCommit -or
        $finalOriginMaster -notin @($baselineCommit, $mergeCommit) -or
        (Test-Path -LiteralPath $finalMergeHeadPath -PathType Leaf)) {
        throw "Git identity changed after recovery proof"
    }

    $finalMarkerSnapshot = Read-WeatherQuietRetainedSnapshot `
        -Path $activeMarkerPath `
        -Label "durable merge/documentation marker at publication boundary" `
        -Json
    if (-not $documentedMarkerSha256 -or
        [string]$finalMarkerSnapshot.Sha256 -cne $documentedMarkerSha256) {
        throw "durable merge/documentation marker changed after recovery proof"
    }
    $finalMarker = $finalMarkerSnapshot.Payload
    if ([string]$finalMarker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
        [string]$finalMarker.phase -ne "documented_unpublished" -or
        ([string]$finalMarker.merge_commit).ToLowerInvariant() -ne $mergeCommit -or
        ([string]$finalMarker.baseline_commit).ToLowerInvariant() -ne $baselineCommit -or
        ([string]$finalMarker.resolved_branch_tip).ToLowerInvariant() -ne $resolvedBranchTip -or
        $finalMarker.documentation_transaction_recorded -ne $true -or
        ([string]$finalMarker.documentation_transaction_pending_sha256).ToLowerInvariant() -ne
            $documentationTransactionPendingSha256 -or
        [string]$finalMarker.documentation_transaction_snapshot_path -cne
            $documentationTransactionSnapshotPath -or
        $finalMarker.publication_acknowledged -eq $true) {
        throw "durable merge/documentation marker changed after recovery proof"
    }
    $finalDocumentationSnapshotPath = Join-Path $repo (
        $documentationTransactionSnapshotPath -replace '/', '\'
    )
    $finalDocumentationPendingSnapshot = Read-WeatherQuietRetainedSnapshot `
        -Path $documentationPendingPath `
        -Label "documentation pending state at publication boundary" `
        -Json
    $finalDocumentationSnapshot = Read-WeatherQuietRetainedSnapshot `
        -Path $finalDocumentationSnapshotPath `
        -Label "documentation immutable snapshot at publication boundary" `
        -Json
    if ([string]$finalDocumentationPendingSnapshot.Sha256 -cne
            $documentationTransactionPendingSha256 -or
        [string]$finalDocumentationSnapshot.Sha256 -cne
            $documentationTransactionPendingSha256 -or
        [string]$finalDocumentationPendingSnapshot.Text -cne
            [string]$finalDocumentationSnapshot.Text) {
        throw "immutable documentation transaction snapshot changed before publication"
    }

    $finalCapture = Get-CaptureState `
        -Stage "pre-publication" -ExpectedHead $mergeCommit
    if (-not $finalCapture.ok -or @($finalCapture.workers).Count -ne 3) {
        throw "exact three-worker capture recovery no longer passes"
    }
    if ($executionTapeRecoveryRequired) {
        $finalExecutionTape = Get-ExecutionTapeState `
            -Stage "pre-publication" -ExpectedHead $mergeCommit
        if (-not $finalExecutionTape.ok) {
            throw "execution-tape recovery no longer passes: $(@($finalExecutionTape.reasons) -join ',')"
        }
    }
}
catch {
    $prePublicationFailure = $_.Exception.Message
}
if ($prePublicationFailure) {
    Note "publication boundary proof failed: $prePublicationFailure"
    Save-Report -ok $true -stage "merged_unpushed" -detail "publication boundary proof failed; commit $mergeCommit is local: $prePublicationFailure"
    exit 3
}
try { Assert-OneShotPushTask }
catch {
    Note "WeatherOneShotPush changed after its pre-mutation check: $($_.Exception.Message)"
    Save-Report -ok $true -stage "merged_unpushed" -detail "push task binding changed before publication; commit $mergeCommit is local"
    exit 3
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedOriginUrl)) {
    try {
        Assert-WeatherIntegrationCanonicalOriginUrl `
            -Root $repo -ExpectedUrl $ExpectedOriginUrl `
            -Phase "quiet-window immediate pre-push origin identity" `
            -ExpectedGitExecutable $gitExecutable `
            -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 | Out-Null
    }
    catch {
        Note "canonical origin identity changed before WeatherOneShotPush: $($_.Exception.Message)"
        Save-Report -ok $true -stage "merged_unpushed" -detail (
            "canonical origin identity changed at the exact publication boundary; " +
            "commit $mergeCommit is local"
        )
        exit 3
    }
}
Note "capture healthy after the roll; handing $mergeCommit to WeatherOneShotPush"
try {
    Assert-WeatherIntegrationSchedulerMutationAllowed `
        -CommandName "Start-ScheduledTask" `
        -Phase "quiet-window WeatherOneShotPush publication"
    Start-ScheduledTask -TaskName WeatherOneShotPush -ErrorAction Stop
}
catch {
    Note "could not start WeatherOneShotPush: $($_.Exception.Message)"
    Save-Report -ok $true -stage "merged_unpushed" -detail "push task start failed; commit $mergeCommit is local"
    exit 3
}
$pushed = $false
$publishedTrackingFailure = $null
$publicationDeadline = [datetimeoffset]::UtcNow.AddSeconds(180)
$publicationStopwatch = [Diagnostics.Stopwatch]::StartNew()
try {
    for ($i = 0; $i -lt 18; $i++) {
        $publicationWallTimeRemaining = (
            [datetimeoffset]::UtcNow -lt $publicationDeadline
        )
        $publicationMonotonicTimeRemaining = (
            $publicationStopwatch.Elapsed.TotalSeconds -lt 180.0
        )
        if (-not $publicationWallTimeRemaining -or
            -not $publicationMonotonicTimeRemaining) {
            break
        }
        try {
            $publishedTrackingResult = Invoke-WeatherQuietGit `
                -Arguments @("rev-parse", "origin/master") `
                -Label "post-push origin/master tracking query" `
                -TimeoutSeconds 5
            $publishedTrackingRows = @($publishedTrackingResult.StdoutLines)
            $publishedTrackingExit = [int]$publishedTrackingResult.ExitCode
            if ($publishedTrackingExit -eq 0 -and
                $publishedTrackingRows.Count -eq 1 -and
                ([string]$publishedTrackingRows[0]).Trim() -eq $mergeCommit) {
                $pushed = $true
                break
            }
        }
        catch {
            $publishedTrackingFailure = $_.Exception.Message
            Note (
                "post-push tracking query failed safely; publication remains " +
                "unacknowledged: $publishedTrackingFailure"
            )
        }
        if ($i -lt 17) {
            Start-Sleep -Seconds 10
        }
    }
}
finally {
    $publicationStopwatch.Stop()
}
if (-not $pushed) {
    Note "WeatherOneShotPush did not publish within 3 min. Merge is committed locally and capture is healthy."
    $publicationDetail = "push task did not acknowledge commit $mergeCommit"
    if ($publishedTrackingFailure) {
        $publicationDetail += "; last bounded tracking failure=$publishedTrackingFailure"
    }
    Save-Report -ok $true -stage "merged_unpushed" -detail $publicationDetail
    exit 3
}
$canonicalPublishedTip = $null
if (-not [string]::IsNullOrWhiteSpace($ExpectedOriginUrl)) {
    try {
        $canonicalPublishedTip = Get-WeatherIntegrationCanonicalRemoteTip `
            -Root $repo -ExpectedUrl $ExpectedOriginUrl `
            -RemoteRef "refs/heads/master" `
            -ExpectedGitExecutable $gitExecutable `
            -ExpectedGitExecutableSha256 $script:quietGitExecutableSha256 `
            -Label "quiet-window post-push canonical origin/master verification"
    }
    catch {
        Note "WeatherOneShotPush canonical origin verification failed: $($_.Exception.Message)"
    }
    if ($canonicalPublishedTip -ne $mergeCommit) {
        Save-Report -ok $true -stage "merged_unpushed" -detail (
            "push task updated local origin/master but config-independent canonical " +
            "origin/master did not prove commit $mergeCommit"
        )
        exit 3
    }
}
$publicationAcknowledged = $true
try {
    Write-QuietMergeMarker -Phase "published"
}
catch {
    # The remote acknowledgement plus the attempt-local terminal report below
    # are authoritative. If that report also fails, the previous durable
    # documented_unpublished marker remains for Git-backed reconciliation.
    Note "WARNING: publication succeeded but the durable marker phase could not be advanced"
}
Note "pushed $mergeCommit via WeatherOneShotPush"
Save-Report -ok $true -stage "pushed" -detail "$mergeCommit (via WeatherOneShotPush)"
exit 0
}
catch {
    $quietMutationPrimaryError = $_
    throw
}
finally {
    $dependencyCleanupFailures = New-Object System.Collections.Generic.List[string]
    try { Exit-WeatherHeavyWorkloadLease -Lease $workloadLease }
    catch {
        $dependencyCleanupFailures.Add(
            "heavy-workload lease: $($_.Exception.Message)"
        )
    }
    try { Remove-WeatherQuietPythonCacheRoot }
    catch {
        $dependencyCleanupFailures.Add(
            "owned Python cache root: $($_.Exception.Message)"
        )
    }
    for ($pinIndex = $quietPinnedScripts.Count - 1; $pinIndex -ge 0; $pinIndex--) {
        $pin = $quietPinnedScripts[$pinIndex]
        if ($null -eq $pin -or $null -eq $pin.Stream) { continue }
        try { $pin.Stream.Dispose() }
        catch {
            $dependencyCleanupFailures.Add(
                "$([string]$pin.Label) retained handle: $($_.Exception.Message)"
            )
        }
    }
    if ($dependencyCleanupFailures.Count -ne 0) {
        $dependencyCleanupMessage = (
            "quiet-window dependency cleanup failed: " +
            ($dependencyCleanupFailures -join " | ")
        )
        if ($null -ne $quietMutationPrimaryError) {
            $quietMutationPrimaryError.Exception.Data[
                "weather_cleanup_failure"
            ] = $dependencyCleanupMessage
            Write-Warning $dependencyCleanupMessage -WarningAction Continue
        }
        else { throw $dependencyCleanupMessage }
    }
}
