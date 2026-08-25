Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "integration_attempt_remote_git.ps1")

$script:WeatherIntegrationAttemptLegacyManifestSchema = "weather_integration_attempt_manifest_v1"
$script:WeatherIntegrationAttemptManifestSchema = "weather_integration_attempt_manifest_v2"
$script:WeatherIntegrationAttemptSuiteReceiptSchema = "weather_integration_attempt_suite_receipt_v1"
$script:WeatherIntegrationAttemptMergeReceiptSchema = "weather_integration_attempt_merge_receipt_v1"
$script:WeatherIntegrationAttemptRegistrationReceiptSchema = "weather_integration_attempt_registration_receipt_v2"
$script:WeatherIntegrationAttemptRegistrationIntentSchema = "weather_integration_attempt_registration_intent_v2"
$script:WeatherIntegrationAttemptTaskBindingContract = "weather_integration_attempt_exact_task_binding_v2"
$script:WeatherIntegrationAttemptLegacyRegistrationReceiptSchema = "weather_integration_attempt_registration_receipt_v1"
$script:WeatherIntegrationAttemptLegacyRegistrationIntentSchema = "weather_integration_attempt_registration_intent_v1"
$script:WeatherIntegrationAttemptLegacyTaskBindingContract = "weather_integration_attempt_exact_task_binding_v1"
$script:WeatherIntegrationAttemptClosureReceiptSchema = "weather_integration_attempt_closure_receipt_v1"
$script:WeatherIntegrationAttemptSuccessorClaimSchema = "weather_integration_attempt_successor_claim_v1"
$script:WeatherIntegrationAttemptRecoveryDispatchSchema = "weather_integration_attempt_recovery_dispatch_v1"
$script:WeatherIntegrationAttemptReconciliationReceiptSchema = "weather_integration_attempt_reconciliation_receipt_v1"
$script:WeatherIntegrationAttemptPreparationAuthorizationSchema = "weather_integration_attempt_preparation_authorization_v1"
$script:WeatherIntegrationAttemptPrearmingQualificationSchema =
    "weather_integration_attempt_prearming_qualification_receipt_v1"
$script:WeatherIntegrationPrearmingPlanningCeilingSeconds = 5400
$script:WeatherIntegrationPrearmingSafetyMarginSeconds = 600
$script:WeatherIntegrationSchedulerLaunchGraceSeconds = 300
$script:WeatherIntegrationBoundedSuiteMaximumRuntimeSeconds = 5400
$script:WeatherIntegrationSuiteWrapperTeardownAllowanceSeconds = 300
$script:WeatherIntegrationSuiteTaskExecutionLimitSeconds =
    $script:WeatherIntegrationBoundedSuiteMaximumRuntimeSeconds +
    $script:WeatherIntegrationSuiteWrapperTeardownAllowanceSeconds
$script:WeatherIntegrationSuiteMinimumPhaseRuntimeSeconds = 60
$script:WeatherIntegrationTaskRetirementReceiptSchema =
    "weather_integration_attempt_task_retirement_receipt_v1"
$script:WeatherIntegrationTaskRetirementConfirmation =
    "RETIRE_EXACT_TERMINAL_INTEGRATION_TASKS"
$script:WeatherLegacyBootstrapRetirementSchema =
    "weather_legacy_integration_bootstrap_task_retirement_v1"
$script:WeatherLegacyBootstrapRetirementConfirmation =
    "RETIRE_EXACT_EXPIRED_LEGACY_INTEGRATION_TASK"
$script:WeatherIntegrationScheduleTimeZoneId = "Eastern Standard Time"
$script:WeatherIntegrationScheduleTimeZoneSchema =
    "weather_integration_schedule_time_zone_v1"

if ($null -eq ("WeatherIntegrationFileIdentity" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class WeatherIntegrationFileIdentity
{
    [StructLayout(LayoutKind.Sequential)]
    private struct BY_HANDLE_FILE_INFORMATION
    {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle handle,
        out BY_HANDLE_FILE_INFORMATION information
    );

    public static string FromHandle(SafeFileHandle handle)
    {
        BY_HANDLE_FILE_INFORMATION information;
        if (handle == null || handle.IsInvalid ||
            !GetFileInformationByHandle(handle, out information))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        return String.Format(
            System.Globalization.CultureInfo.InvariantCulture,
            "{0:x8}:{1:x8}{2:x8}",
            information.VolumeSerialNumber,
            information.FileIndexHigh,
            information.FileIndexLow
        );
    }
}
'@
}

function Get-WeatherIntegrationFileHandleIdentity {
    param(
        [Parameter(Mandatory = $true)]
        [IO.FileStream]$Stream,
        [Parameter(Mandatory = $true)][string]$Label
    )

    try {
        return [WeatherIntegrationFileIdentity]::FromHandle(
            $Stream.SafeFileHandle
        )
    }
    catch { throw "$Label file identity query failed: $($_.Exception.Message)" }
}

function Read-WeatherIntegrationEvidenceSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 268435456)]
        [long]$MaximumBytes,
        [ValidateSet("Bytes", "Text", "Json")]
        [string]$ContentType = "Bytes"
    )

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $pathIdentityStream = $null
    $closingPathStream = $null
    try {
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $resolvedPath -Phase "Evidence snapshot before open"
        $item = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction Stop
    }
    catch {
        throw "Required evidence file is missing: $resolvedPath"
    }
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Evidence must be a regular non-reparse file: $resolvedPath"
    }

    $stream = $null
    $pathIdentityStream = $null
    $closingPathStream = $null
    try {
        # Denying write/delete sharing makes the bytes below one stable read
        # snapshot. Hashing, decoding, and parsing must all use this one buffer.
        $stream = [IO.FileStream]::new(
            [string]$item.FullName,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        $openedIdentity = Get-WeatherIntegrationFileHandleIdentity `
            -Stream $stream -Label "Evidence snapshot retained handle"
        $pathIdentityStream = [IO.File]::Open(
            $resolvedPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        $pathIdentity = Get-WeatherIntegrationFileHandleIdentity `
            -Stream $pathIdentityStream -Label "Evidence snapshot current path"
        if ($pathIdentity -cne $openedIdentity) {
            throw "Evidence pathname names a different file than the retained handle: $resolvedPath"
        }
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $resolvedPath -Phase "Evidence snapshot after open"
        $openedItem = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction Stop
        if ($openedItem.PSIsContainer -or
            ($openedItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not [string]::Equals(
                [IO.Path]::GetFullPath([string]$openedItem.FullName),
                $resolvedPath,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw "Evidence path changed or became a reparse point while opening: $resolvedPath"
        }
        if ($stream.Length -le 0) {
            throw "Evidence is empty: $resolvedPath"
        }
        if ($stream.Length -gt $MaximumBytes) {
            throw "Evidence exceeds its bounded read limit of $MaximumBytes bytes: $resolvedPath"
        }
        $bytes = [byte[]]::new([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $read = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($read -le 0) {
                throw "Evidence could not be read completely from one open handle: $resolvedPath"
            }
            $offset += $read
        }
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $resolvedPath -Phase "Evidence snapshot after read"
        $closingPathStream = [IO.File]::Open(
            $resolvedPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        $closingIdentity = Get-WeatherIntegrationFileHandleIdentity `
            -Stream $closingPathStream -Label "Evidence snapshot closing path"
        if ($closingIdentity -cne $openedIdentity) {
            throw "Evidence pathname changed files during the retained read: $resolvedPath"
        }
    }
    catch {
        throw "Could not open one stable evidence snapshot from ${resolvedPath}: $($_.Exception.Message)"
    }
    finally {
        if ($null -ne $closingPathStream) { $closingPathStream.Dispose() }
        if ($null -ne $pathIdentityStream) { $pathIdentityStream.Dispose() }
        if ($null -ne $stream) { $stream.Dispose() }
    }

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $sha256 = ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }

    $text = $null
    $payload = $null
    if ($ContentType -ne "Bytes") {
        try {
            $decoder = New-Object Text.UTF8Encoding($false, $true)
            $text = $decoder.GetString($bytes)
            if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) {
                $text = $text.Substring(1)
            }
        }
        catch {
            throw "Evidence is not strict UTF-8 text: ${resolvedPath}: $($_.Exception.Message)"
        }
    }
    if ($ContentType -eq "Json") {
        try { $payload = $text | ConvertFrom-Json -ErrorAction Stop }
        catch { throw "Could not parse JSON from ${resolvedPath}: $($_.Exception.Message)" }
    }

    return [pscustomobject][ordered]@{
        Path = $resolvedPath
        Length = [long]$bytes.Length
        Bytes = $bytes
        Text = $text
        Payload = $payload
        Sha256 = $sha256
    }
}

function Get-WeatherIntegrationFileSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 268435456)]
        [long]$MaximumBytes = 268435456
    )

    return [string](Read-WeatherIntegrationEvidenceSnapshot `
        -Path $Path -MaximumBytes $MaximumBytes -ContentType Bytes).Sha256
}

function Get-WeatherIntegrationInventorySha256 {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string[]]$Paths
    )

    [byte[]]$bytes = [Text.Encoding]::UTF8.GetBytes(
        (@($Paths) -join "`n") + "`n"
    )
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return (([BitConverter]::ToString($sha.ComputeHash($bytes))) `
            -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Get-WeatherIntegrationTrackedWorktreeDigest {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Entries
    )

    $builder = New-Object Text.StringBuilder
    foreach ($entry in @($Entries)) {
        $path = [string]$entry.path
        $mode = [string]$entry.mode
        $blobOid = [string]$entry.blob_oid
        $worktreeSha = [string]$entry.worktree_sha256
        $lfsOid = if ($null -eq $entry.lfs_oid -or
            [string]::IsNullOrWhiteSpace([string]$entry.lfs_oid)) {
            "-"
        }
        else { [string]$entry.lfs_oid }
        $lfsSize = if ($null -eq $entry.lfs_size) {
            "-"
        }
        else { [string][long]$entry.lfs_size }
        if ([string]::IsNullOrWhiteSpace($path) -or
            $path.IndexOfAny([char[]]@("`t", "`r", "`n", [char]0)) -ge 0 -or
            $mode -cnotmatch '^100(?:644|755)$' -or
            $blobOid -cnotmatch '^[0-9a-f]{40}$' -or
            [long]$entry.worktree_length -lt 0 -or
            $worktreeSha -cnotmatch '^[0-9a-f]{64}$' -or
            ($lfsOid -cne "-" -and $lfsOid -cnotmatch '^[0-9a-f]{64}$') -or
            ($lfsSize -cne "-" -and [long]$lfsSize -lt 0)) {
            throw "Tracked-worktree fingerprint entry is malformed: $path"
        }
        [void]$builder.Append($path).Append("`t").Append($mode).Append("`t").
            Append($blobOid).Append("`t").Append([long]$entry.worktree_length).
            Append("`t").Append($worktreeSha).Append("`t").Append($lfsOid).
            Append("`t").Append($lfsSize).Append("`n")
    }
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($builder.ToString())
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return (([BitConverter]::ToString($sha.ComputeHash($bytes))) `
            -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function ConvertFrom-WeatherIntegrationNulRows {
    param(
        [AllowEmptyString()][string]$Text,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ([string]::IsNullOrEmpty($Text)) { return @() }
    if ($Text[$Text.Length - 1] -ne [char]0) {
        throw "$Label did not end at an exact NUL record boundary."
    }
    $rows = @($Text.Split([char]0))
    if ($rows.Count -eq 0 -or $rows[$rows.Count - 1] -cne "") {
        throw "$Label returned malformed NUL records."
    }
    if ($rows.Count -eq 1) { return @() }
    return @($rows[0..($rows.Count - 2)])
}

function Get-WeatherIntegrationRepositoryMetadataTuple {
    param(
        [Parameter(Mandatory = $true)][string]$WorktreeRoot,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    $resolvedRoot = Resolve-WeatherIntegrationPath -Path $WorktreeRoot
    $shallowRows = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $resolvedRoot -Arguments @("rev-parse", "--is-shallow-repository") `
        -Label "$Phase shallow-state query").StdoutLines)
    $replaceRows = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $resolvedRoot `
        -Arguments @("for-each-ref", "--format=%(refname)", "refs/replace/") `
        -Label "$Phase replacement-ref query").StdoutLines)
    if ($shallowRows.Count -ne 1 -or
        ([string]$shallowRows[0]).Trim() -cne "false" -or
        @($replaceRows | Where-Object {
            -not [string]::IsNullOrWhiteSpace([string]$_)
        }).Count -ne 0) {
        throw "$Phase refuses shallow history or replacement refs."
    }
    $configRows = [ordered]@{}
    foreach ($key in @(
        "core.worktree", "core.bare", "core.sparseCheckout",
        "core.sparseCheckoutCone", "extensions.worktreeConfig"
    )) {
        $query = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $resolvedRoot -Arguments @("config", "--get", $key) `
            -AllowedExitCodes @(0, 1) -Label "$Phase $key query"
        $rows = @($query.StdoutLines | Where-Object {
            -not [string]::IsNullOrWhiteSpace([string]$_)
        })
        if ($rows.Count -gt 1) {
            throw "$Phase repository configuration repeats $key."
        }
        $configRows[$key] = if ($rows.Count -eq 0) { "" } else {
            ([string]$rows[0]).Trim()
        }
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$configRows["core.worktree"]) -or
        [string]$configRows["core.bare"] -cnotin @("", "false") -or
        [string]$configRows["core.sparseCheckout"] -cnotin @("", "false") -or
        [string]$configRows["core.sparseCheckoutCone"] -cnotin @("", "false") -or
        [string]$configRows["extensions.worktreeConfig"] -cnotin @("", "false")) {
        throw "$Phase refuses worktree redirection, bare, sparse, or worktree-local configuration."
    }
    $gitPaths = [ordered]@{}
    foreach ($name in @(
        "info/grafts", "info/attributes", "info/sparse-checkout", "shallow",
        "objects/info/alternates"
    )) {
        $rows = @((Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $resolvedRoot -Arguments @("rev-parse", "--git-path", $name) `
            -Label "$Phase $name path query").StdoutLines)
        if ($rows.Count -ne 1 -or
            [string]::IsNullOrWhiteSpace([string]$rows[0])) {
            throw "$Phase could not resolve repository metadata path $name."
        }
        $candidate = ([string]$rows[0]).Trim()
        if (-not [IO.Path]::IsPathRooted($candidate)) {
            $candidate = Join-Path $resolvedRoot $candidate
        }
        $gitPaths[$name] = [IO.Path]::GetFullPath($candidate)
    }
    foreach ($forbidden in @(
        "info/grafts", "info/attributes", "info/sparse-checkout", "shallow"
    )) {
        if (Test-Path -LiteralPath ([string]$gitPaths[$forbidden])) {
            throw "$Phase refuses repository-local $forbidden metadata."
        }
    }
    $alternatesSha = "absent"
    $alternatesPath = [string]$gitPaths["objects/info/alternates"]
    if (Test-Path -LiteralPath $alternatesPath) {
        $alternates = Read-WeatherIntegrationEvidenceSnapshot `
            -Path $alternatesPath -MaximumBytes 65536 -ContentType Text
        $alternatesSha = [string]$alternates.Sha256
    }
    return (
        "shallow=false`nreplace_refs=0`n" +
        (($configRows.Keys | ForEach-Object {
            "$_=$([string]$configRows[$_])"
        }) -join "`n") + "`nalternates=$alternatesSha"
    )
}

function Get-WeatherIntegrationTrackedWorktreeFingerprint {
    param(
        [Parameter(Mandatory = $true)][string]$WorktreeRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [string]$Phase = "tracked-worktree fingerprint",
        [AllowNull()]
        [Collections.Generic.List[IDisposable]]$RetainedStreams = $null
    )

    $resolvedRoot = Resolve-WeatherIntegrationPath -Path $WorktreeRoot
    $retainedStartCount = if ($null -eq $RetainedStreams) {
        0
    }
    else { [int]$RetainedStreams.Count }
    if ($ExpectedHead -cnotmatch '^[0-9a-f]{40}$') {
        throw "$Phase expected HEAD must be one lowercase 40-character commit id."
    }
    Assert-WeatherIntegrationRegularPathAncestry `
        -Path $resolvedRoot -Phase "$Phase root"
    $initialMetadata = Get-WeatherIntegrationRepositoryMetadataTuple `
        -WorktreeRoot $resolvedRoot -Phase "$Phase opening metadata"
    $headBefore = @((Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $resolvedRoot `
        -Arguments @("rev-parse", "--verify", "HEAD^{commit}") `
        -Label "$Phase initial HEAD query").StdoutLines)
    if ($headBefore.Count -ne 1 -or
        ([string]$headBefore[0]).Trim().ToLowerInvariant() -cne $ExpectedHead) {
        throw "$Phase worktree HEAD differs from the frozen commit."
    }
    $initialStageText = [string](Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $resolvedRoot -Arguments @("ls-files", "--stage", "-z") `
        -Label "$Phase staged-index query").Stdout
    $initialFlagText = [string](Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $resolvedRoot -Arguments @("ls-files", "-v", "-z") `
        -Label "$Phase index-flag query").Stdout
    $initialLfsText = [string](Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $resolvedRoot `
        -Arguments @("ls-files", "-z", "--", ":(attr:filter=lfs)") `
        -Label "$Phase LFS attribute query").Stdout
    $stageRows = @(ConvertFrom-WeatherIntegrationNulRows `
        -Text $initialStageText `
        -Label "$Phase staged-index query")
    $flagRows = @(ConvertFrom-WeatherIntegrationNulRows `
        -Text $initialFlagText `
        -Label "$Phase index-flag query")
    $lfsRows = @(ConvertFrom-WeatherIntegrationNulRows `
        -Text $initialLfsText `
        -Label "$Phase LFS attribute query")
    if ($stageRows.Count -le 0 -or $stageRows.Count -gt 20000 -or
        $flagRows.Count -ne $stageRows.Count) {
        throw "$Phase tracked-file count is empty, inconsistent, or above 20000."
    }

    $stageByPath = [Collections.Generic.Dictionary[string, object]]::new(
        [StringComparer]::Ordinal
    )
    $windowsPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($row in $stageRows) {
        $match = [regex]::Match(
            [string]$row,
            '^(?<mode>100(?:644|755)) (?<oid>[0-9a-f]{40}) 0\t(?<path>.+)$',
            [Text.RegularExpressions.RegexOptions]::CultureInvariant
        )
        if (-not $match.Success) {
            throw "$Phase refuses a non-regular, unmerged, or malformed index entry."
        }
        $path = [string]$match.Groups["path"].Value
        $segments = @($path.Split('/'))
        if ($path.Contains("\") -or $path.Contains(":") -or
            [IO.Path]::IsPathRooted($path) -or
            $segments.Count -eq 0 -or @($segments | Where-Object {
                [string]::IsNullOrWhiteSpace($_) -or $_ -cin @(".", "..") -or
                $_.EndsWith(" ", [StringComparison]::Ordinal) -or
                $_.EndsWith(".", [StringComparison]::Ordinal) -or
                ([string]$_).Split('.')[0] -imatch
                    '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$'
            }).Count -ne 0 -or
            $path.IndexOfAny([char[]]@("`t", "`r", "`n", [char]0)) -ge 0 -or
            $stageByPath.ContainsKey($path) -or -not $windowsPaths.Add($path)) {
            throw "$Phase refuses an unsafe or duplicate tracked path: $path"
        }
        $stageByPath.Add($path, [pscustomobject][ordered]@{
            Mode = [string]$match.Groups["mode"].Value
            BlobOid = [string]$match.Groups["oid"].Value
        })
    }
    $flagPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($row in $flagRows) {
        $match = [regex]::Match(
            [string]$row,
            '^H (?<path>.+)$',
            [Text.RegularExpressions.RegexOptions]::CultureInvariant
        )
        if (-not $match.Success -or
            -not $stageByPath.ContainsKey([string]$match.Groups["path"].Value) -or
            -not $flagPaths.Add([string]$match.Groups["path"].Value)) {
            throw "$Phase refuses skip-worktree, assume-unchanged, nonordinary, or malformed index flags."
        }
    }
    if ($flagPaths.Count -ne $stageByPath.Count) {
        throw "$Phase index-stage and ordinary-flag inventories disagree."
    }
    $lfsPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($path in $lfsRows) {
        if (-not $stageByPath.ContainsKey([string]$path) -or
            -not $lfsPaths.Add([string]$path)) {
            throw "$Phase LFS attribute inventory is malformed or not tracked."
        }
    }

    $sortedPaths = [string[]]@($stageByPath.Keys)
    [Array]::Sort($sortedPaths, [StringComparer]::Ordinal)
    $entries = New-Object System.Collections.Generic.List[object]
    $absolutePaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    [long]$totalBytes = 0
    try {
        foreach ($path in $sortedPaths) {
            $absolute = [IO.Path]::GetFullPath((Join-Path $resolvedRoot $path))
            $rootPrefix = $resolvedRoot.TrimEnd(
                [IO.Path]::DirectorySeparatorChar,
                [IO.Path]::AltDirectorySeparatorChar
            ) + [IO.Path]::DirectorySeparatorChar
            if (-not $absolute.StartsWith(
                    $rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "$Phase tracked path escaped the worktree: $path"
            }
            if (-not $absolutePaths.Add($absolute)) {
                throw "$Phase tracked paths alias one Windows file: $path"
            }
            Assert-WeatherIntegrationRegularPathAncestry `
                -Path $absolute -Phase "$Phase tracked file $path"
            $item = Get-Item -LiteralPath $absolute -Force -ErrorAction Stop
            if ($item.PSIsContainer -or
                ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Phase tracked input is not a regular file: $path"
            }
            $stream = $null
            $transferred = $false
            try {
                $stream = [IO.File]::Open(
                    $absolute, [IO.FileMode]::Open,
                    [IO.FileAccess]::Read, [IO.FileShare]::Read
                )
                if ($stream.Length -gt 536870912) {
                    throw "$Phase tracked input exceeds 512 MiB: $path"
                }
                $totalBytes += [long]$stream.Length
                if ($totalBytes -gt 2147483648) {
                    throw "$Phase tracked inputs exceed the 2 GiB aggregate bound."
                }
                $sha = [Security.Cryptography.SHA256]::Create()
                try {
                    $worktreeSha = (([BitConverter]::ToString(
                        $sha.ComputeHash($stream)
                    )) -replace '-', '').ToLowerInvariant()
                }
                finally { $sha.Dispose() }
                $stream.Position = 0
                $lfsOid = $null
                $lfsSize = $null
                if ($lfsPaths.Contains($path)) {
                    $pointerResult = Invoke-WeatherIntegrationCheckedLocalGit `
                        -Root $resolvedRoot `
                        -Arguments @(
                            "cat-file", "blob", [string]$stageByPath[$path].BlobOid
                        ) `
                        -Label "$Phase LFS pointer query for $path"
                    $pointer = [string]$pointerResult.Stdout
                    $pointerMatch = [regex]::Match(
                        $pointer,
                        '^version https://git-lfs.github.com/spec/v1\noid sha256:(?<oid>[0-9a-f]{64})\nsize (?<size>0|[1-9][0-9]*)\n$',
                        [Text.RegularExpressions.RegexOptions]::CultureInvariant
                    )
                    if (-not $pointerMatch.Success) {
                        throw "$Phase tracked LFS index blob is not one strict canonical pointer: $path"
                    }
                    $lfsOid = [string]$pointerMatch.Groups["oid"].Value
                    [long]$lfsSize = [long]::Parse(
                        [string]$pointerMatch.Groups["size"].Value,
                        [Globalization.CultureInfo]::InvariantCulture
                    )
                    if ([long]$stream.Length -ne $lfsSize -or
                        $worktreeSha -cne $lfsOid) {
                        throw "$Phase tracked LFS input is absent, unhydrated, or differs from its pointer: $path"
                    }
                }
                $entries.Add([pscustomobject][ordered]@{
                    path = $path
                    mode = [string]$stageByPath[$path].Mode
                    blob_oid = [string]$stageByPath[$path].BlobOid
                    worktree_length = [long]$stream.Length
                    worktree_sha256 = $worktreeSha
                    lfs_oid = $lfsOid
                    lfs_size = $lfsSize
                })
                if ($null -ne $RetainedStreams) {
                    $RetainedStreams.Add($stream)
                    $transferred = $true
                }
            }
            finally {
                if ($null -ne $stream -and -not $transferred) {
                    $stream.Dispose()
                }
            }
        }
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $resolvedRoot -Phase "$Phase closing root"
        $closingMetadata = Get-WeatherIntegrationRepositoryMetadataTuple `
            -WorktreeRoot $resolvedRoot -Phase "$Phase closing metadata"
        $closingStage = [string](Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $resolvedRoot -Arguments @("ls-files", "--stage", "-z") `
            -Label "$Phase closing staged-index query").Stdout
        $closingFlags = [string](Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $resolvedRoot -Arguments @("ls-files", "-v", "-z") `
            -Label "$Phase closing index-flag query").Stdout
        $closingLfs = [string](Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $resolvedRoot `
            -Arguments @("ls-files", "-z", "--", ":(attr:filter=lfs)") `
            -Label "$Phase closing LFS attribute query").Stdout
        $headAfter = @((Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $resolvedRoot `
            -Arguments @("rev-parse", "--verify", "HEAD^{commit}") `
            -Label "$Phase closing HEAD query").StdoutLines)
        if ($closingMetadata -cne $initialMetadata -or
            $closingStage -cne $initialStageText -or
            $closingFlags -cne $initialFlagText -or
            $closingLfs -cne $initialLfsText -or
            $headAfter.Count -ne 1 -or
            ([string]$headAfter[0]).Trim().ToLowerInvariant() -cne $ExpectedHead) {
            throw "$Phase Git index or HEAD changed across the retained snapshot."
        }
        $digest = Get-WeatherIntegrationTrackedWorktreeDigest -Entries @($entries)
        return [pscustomobject][ordered]@{
            schema_version = "tracked_worktree_content_fingerprint_v1"
            content_sha256 = $digest
            head = $ExpectedHead
            root = $resolvedRoot
            file_count = [int]$entries.Count
            total_bytes = $totalBytes
            lfs_file_count = [int]$lfsPaths.Count
            entries = @($entries)
        }
    }
    catch {
        if ($null -ne $RetainedStreams) {
            for ($index = $RetainedStreams.Count - 1;
                $index -ge $retainedStartCount; $index--) {
                try { $RetainedStreams[$index].Dispose() } catch { }
                $RetainedStreams.RemoveAt($index)
            }
        }
        throw
    }
}

function Assert-WeatherIntegrationTrackedWorktreeFingerprintPayload {
    param(
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][string]$ExpectedRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedHead,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][int]$ExpectedFileCount,
        [Parameter(Mandatory = $true)][long]$ExpectedTotalBytes,
        [Parameter(Mandatory = $true)][int]$ExpectedLfsFileCount,
        [string]$Label = "tracked-worktree fingerprint"
    )

    $topNames = @(
        "schema_version", "content_sha256", "head", "root", "file_count",
        "total_bytes", "lfs_file_count", "entries"
    ) | Sort-Object
    $actualTopNames = @($Payload.PSObject.Properties.Name | Sort-Object)
    $entries = @($Payload.entries)
    if (($actualTopNames -join "`n") -cne ($topNames -join "`n") -or
        [string]$Payload.schema_version -cne
            "tracked_worktree_content_fingerprint_v1" -or
        [string]$Payload.content_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        [string]$Payload.head -cnotmatch '^[0-9a-f]{40}$' -or
        [int]$Payload.file_count -le 0 -or [int]$Payload.file_count -gt 20000 -or
        [long]$Payload.total_bytes -lt 0 -or
        [long]$Payload.total_bytes -gt 2147483648 -or
        [int]$Payload.lfs_file_count -lt 0 -or
        [int]$Payload.lfs_file_count -gt [int]$Payload.file_count -or
        $entries.Count -ne [int]$Payload.file_count) {
        throw "$Label has an invalid top-level schema or bounds."
    }
    $expectedRootPath = Resolve-WeatherIntegrationPath -Path $ExpectedRoot
    $payloadRoot = Resolve-WeatherIntegrationPath -Path ([string]$Payload.root)
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left $payloadRoot -Right $expectedRootPath) -or
        [string]$Payload.head -cne $ExpectedHead -or
        [string]$Payload.content_sha256 -cne $ExpectedSha256 -or
        [int]$Payload.file_count -ne $ExpectedFileCount -or
        [long]$Payload.total_bytes -ne $ExpectedTotalBytes -or
        [int]$Payload.lfs_file_count -ne $ExpectedLfsFileCount) {
        throw "$Label does not match its frozen root, commit, digest, or counts."
    }
    [string]$priorPath = ""
    [long]$observedBytes = 0
    [int]$observedLfs = 0
    foreach ($entry in $entries) {
        $entryNames = @($entry.PSObject.Properties.Name | Sort-Object)
        $requiredEntryNames = @(
            "path", "mode", "blob_oid", "worktree_length",
            "worktree_sha256", "lfs_oid", "lfs_size"
        ) | Sort-Object
        $path = [string]$entry.path
        if (($entryNames -join "`n") -cne ($requiredEntryNames -join "`n") -or
            (-not [string]::IsNullOrEmpty($priorPath) -and
                [StringComparer]::Ordinal.Compare($priorPath, $path) -ge 0)) {
            throw "$Label entries are not exact-schema, unique, ordinal-sorted rows."
        }
        # The digest helper performs the strict scalar validation too.
        [void](Get-WeatherIntegrationTrackedWorktreeDigest -Entries @($entry))
        $observedBytes += [long]$entry.worktree_length
        if ($null -ne $entry.lfs_oid) {
            if ([string]$entry.lfs_oid -cnotmatch '^[0-9a-f]{64}$' -or
                $null -eq $entry.lfs_size -or [long]$entry.lfs_size -lt 0 -or
                [string]$entry.worktree_sha256 -cne [string]$entry.lfs_oid -or
                [long]$entry.worktree_length -ne [long]$entry.lfs_size) {
                throw "$Label has invalid hydrated LFS evidence for $path."
            }
            $observedLfs++
        }
        elseif ($null -ne $entry.lfs_size) {
            throw "$Label has a partial LFS entry for $path."
        }
        $priorPath = $path
    }
    if ($observedBytes -ne [long]$Payload.total_bytes -or
        $observedLfs -ne [int]$Payload.lfs_file_count -or
        (Get-WeatherIntegrationTrackedWorktreeDigest -Entries $entries) -cne
            [string]$Payload.content_sha256) {
        throw "$Label entry totals or canonical digest disagree."
    }
    return $Payload
}

function ConvertFrom-WeatherIntegrationRecordSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Digest,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Digest -cnotmatch '^[A-Za-z0-9_-]{43}=?$') {
        throw "$Label is not one URL-safe base64 SHA-256 digest."
    }
    $base64 = $Digest.Replace('-', '+').Replace('_', '/')
    while (($base64.Length % 4) -ne 0) { $base64 += "=" }
    try { $bytes = [Convert]::FromBase64String($base64) }
    catch { throw "$Label is not valid URL-safe base64." }
    if ($bytes.Length -ne 32) {
        throw "$Label did not decode to one SHA-256 digest."
    }
    return (([BitConverter]::ToString($bytes)) -replace '-', '').ToLowerInvariant()
}

function Get-WeatherIntegrationOpenFileIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(0, 536870912)][long]$MaximumBytes = 536870912
    )

    $resolved = Resolve-WeatherIntegrationPath -Path $Path
    Assert-WeatherIntegrationRegularPathAncestry -Path $resolved -Phase $Label
    $item = Get-Item -LiteralPath $resolved -Force -ErrorAction Stop
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Label is not a regular non-reparse file: $resolved"
    }
    $stream = $null
    $pathIdentityStream = $null
    $closingPathStream = $null
    try {
        $stream = [IO.File]::Open(
            $resolved, [IO.FileMode]::Open,
            [IO.FileAccess]::Read, [IO.FileShare]::Read
        )
        if ($stream.Length -gt $MaximumBytes) {
            throw "$Label exceeds its $MaximumBytes-byte bound: $resolved"
        }
        $openedIdentity = Get-WeatherIntegrationFileHandleIdentity `
            -Stream $stream -Label "$Label retained handle"
        $pathIdentityStream = [IO.File]::Open(
            $resolved, [IO.FileMode]::Open,
            [IO.FileAccess]::Read, [IO.FileShare]::Read
        )
        $pathIdentity = Get-WeatherIntegrationFileHandleIdentity `
            -Stream $pathIdentityStream -Label "$Label current path"
        if ($pathIdentity -cne $openedIdentity) {
            throw "$Label pathname differs from its retained file: $resolved"
        }
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $digest = (([BitConverter]::ToString($sha.ComputeHash($stream))) `
                -replace '-', '').ToLowerInvariant()
        }
        finally { $sha.Dispose() }
        Assert-WeatherIntegrationRegularPathAncestry `
            -Path $resolved -Phase "$Label closing ancestry"
        $closingPathStream = [IO.File]::Open(
            $resolved, [IO.FileMode]::Open,
            [IO.FileAccess]::Read, [IO.FileShare]::Read
        )
        $closingIdentity = Get-WeatherIntegrationFileHandleIdentity `
            -Stream $closingPathStream -Label "$Label closing path"
        if ($closingIdentity -cne $openedIdentity) {
            throw "$Label pathname changed files during verification: $resolved"
        }
        return [pscustomobject]@{
            Path = $resolved
            Length = [long]$stream.Length
            Sha256 = $digest
        }
    }
    finally {
        if ($null -ne $closingPathStream) { $closingPathStream.Dispose() }
        if ($null -ne $pathIdentityStream) { $pathIdentityStream.Dispose() }
        if ($null -ne $stream) { $stream.Dispose() }
    }
}

function Assert-WeatherIntegrationPythonEnvironmentFingerprintPayload {
    param(
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutableSha256,
        [Parameter(Mandatory = $true)][int]$ExpectedDistributionCount,
        [Parameter(Mandatory = $true)][int]$ExpectedFileCount,
        [Parameter(Mandatory = $true)][long]$ExpectedTotalBytes,
        [string]$Label = "Python environment fingerprint",
        [switch]$VerifyCurrentFiles
    )

    $requiredTop = @(
        "schema_version", "executable", "executable_sha256",
        "python_version", "implementation", "cache_tag", "platform",
        "prefix", "base_prefix", "sys_path", "controls", "distributions",
        "runtime_files", "pth_files", "file_count", "total_bytes"
    ) | Sort-Object
    $actualTop = @($Payload.PSObject.Properties.Name | Sort-Object)
    if (($actualTop -join "`n") -cne ($requiredTop -join "`n") -or
        [string]$Payload.schema_version -cne
            "python_environment_fingerprint_v2" -or
        [string]$Payload.executable_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        [string]::IsNullOrWhiteSpace([string]$Payload.python_version) -or
        [string]::IsNullOrWhiteSpace([string]$Payload.implementation) -or
        [string]::IsNullOrWhiteSpace([string]$Payload.platform) -or
        [int]$Payload.file_count -le 0 -or [int]$Payload.file_count -gt 50000 -or
        [long]$Payload.total_bytes -le 0 -or
        [long]$Payload.total_bytes -gt 2147483648) {
        throw "$Label has an invalid v2 top-level schema or bounds."
    }
    $executable = Resolve-WeatherIntegrationPath -Path ([string]$Payload.executable)
    $expectedExecutablePath = Resolve-WeatherIntegrationPath -Path $ExpectedExecutable
    $prefix = Resolve-WeatherIntegrationPath -Path ([string]$Payload.prefix)
    $basePrefix = Resolve-WeatherIntegrationPath -Path ([string]$Payload.base_prefix)
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left $executable -Right $expectedExecutablePath) -or
        [string]$Payload.executable_sha256 -cne $ExpectedExecutableSha256 -or
        @($Payload.distributions).Count -ne $ExpectedDistributionCount -or
        [int]$Payload.file_count -ne $ExpectedFileCount -or
        [long]$Payload.total_bytes -ne $ExpectedTotalBytes) {
        throw "$Label does not match its frozen executable, digest, or counts."
    }
    $pathPrefixes = @($prefix, $basePrefix | ForEach-Object {
        $_.TrimEnd(
            [IO.Path]::DirectorySeparatorChar,
            [IO.Path]::AltDirectorySeparatorChar
        ) + [IO.Path]::DirectorySeparatorChar
    } | Sort-Object -Unique)
    $isUnderRuntime = {
        param([string]$Candidate)
        foreach ($candidatePrefix in $pathPrefixes) {
            if ($Candidate.StartsWith(
                    $candidatePrefix, [StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
        }
        return ((Test-WeatherIntegrationPathEqual `
            -Left $Candidate -Right $executable) -or
            (Test-WeatherIntegrationPathEqual `
                -Left $Candidate -Right $prefix) -or
            (Test-WeatherIntegrationPathEqual `
                -Left $Candidate -Right $basePrefix))
    }
    $sysPaths = @($Payload.sys_path)
    if ($sysPaths.Count -eq 0 -or @($sysPaths | Where-Object {
        [string]::IsNullOrWhiteSpace([string]$_) -or
        -not [IO.Path]::IsPathRooted([string]$_)
    }).Count -ne 0) {
        throw "$Label has invalid sys.path evidence."
    }
    $controlNames = @($Payload.controls.PSObject.Properties.Name | Sort-Object)
    $requiredControls = @(
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
    if (($controlNames -join "`n") -cne ($requiredControls -join "`n") -or
        [string]$Payload.controls.pythonhashseed -cne "0" -or
        [string]$Payload.controls.pythonutf8 -cne "1" -or
        [string]$Payload.controls.pythonioencoding -cne "utf-8" -or
        [string]$Payload.controls.git_allow_protocol -cne "file" -or
        [string]$Payload.controls.git_terminal_prompt -cne "0" -or
        [string]$Payload.controls.git_config_nosystem -cne "1" -or
        [string]$Payload.controls.git_config_system -cne "NUL" -or
        [string]$Payload.controls.git_config_global -cne "NUL" -or
        [string]$Payload.controls.git_config_count -cne "0" -or
        [string]$Payload.controls.git_attr_nosystem -cne "1" -or
        [string]$Payload.controls.git_protocol_from_user -cne "0" -or
        [string]$Payload.controls.git_optional_locks -cne "0" -or
        $Payload.controls.git_topology_environment_clear -isnot [bool] -or
        -not [bool]$Payload.controls.git_topology_environment_clear -or
        [int]$Payload.controls.git_topology_environment_count -ne 0 -or
        [string]$Payload.controls.offline -cne "1" -or
        -not [string]::IsNullOrEmpty(
            [string]$Payload.controls.allowed_write_root
        ) -or
        -not [IO.Path]::IsPathRooted([string]$Payload.controls.candidate_root) -or
        [string]$Payload.controls.secret_policy -cne "conservative_v1" -or
        $Payload.controls.secret_environment_clear -isnot [bool] -or
        -not [bool]$Payload.controls.secret_environment_clear -or
        [int]$Payload.controls.secret_environment_count -ne 0 -or
        [string]$Payload.controls.temp_policy -cne "system_temp_unique_v1" -or
        [string]$Payload.controls.setuptools_use_distutils -cne "stdlib" -or
        $Payload.controls.read_only_production_probe -isnot [bool] -or
        [bool]$Payload.controls.read_only_production_probe -or
        -not [IO.Path]::IsPathRooted(
            [string]$Payload.controls.python_executable
        ) -or
        -not [IO.Path]::IsPathRooted(
            [string]$Payload.controls.git_executable
        ) -or
        -not [IO.Path]::IsPathRooted(
            [string]$Payload.controls.powershell_executable
        ) -or
        -not [IO.Path]::IsPathRooted([string]$Payload.controls.production_root) -or
        -not [IO.Path]::IsPathRooted([string]$Payload.controls.evidence_root)) {
        throw "$Label has invalid deterministic runtime controls."
    }

    $expectedPthRoot = Resolve-WeatherIntegrationPath -Path (
        Join-Path $prefix "Lib\site-packages"
    )
    $pthRows = @($Payload.pth_files)
    [string]$priorPthPath = ""
    $pthNames = [Collections.Generic.List[string]]::new()
    if ($pthRows.Count -ne 2) {
        throw "$Label must bind exactly two reviewed Python .pth bootstrap files."
    }
    foreach ($pthRow in $pthRows) {
        $pthProperties = @($pthRow.PSObject.Properties.Name | Sort-Object)
        $requiredPthProperties = @("length", "path", "sha256") | Sort-Object
        $pthPath = Resolve-WeatherIntegrationPath -Path ([string]$pthRow.path)
        if (($pthProperties -join "`n") -cne
                ($requiredPthProperties -join "`n") -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left (Split-Path -Parent $pthPath) -Right $expectedPthRoot) -or
            [IO.Path]::GetExtension($pthPath) -cne ".pth" -or
            (-not [string]::IsNullOrEmpty($priorPthPath) -and
                [StringComparer]::OrdinalIgnoreCase.Compare(
                    $priorPthPath, $pthPath
                ) -ge 0) -or
            [long]$pthRow.length -le 0 -or [long]$pthRow.length -gt 1048576 -or
            [string]$pthRow.sha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "$Label has malformed or unsorted Python .pth bootstrap evidence."
        }
        $pthNames.Add([IO.Path]::GetFileName($pthPath))
        if ($VerifyCurrentFiles) {
            $currentPth = Get-WeatherIntegrationOpenFileIdentity `
                -Path $pthPath -Label "$Label current Python .pth bootstrap"
            if ([long]$currentPth.Length -ne [long]$pthRow.length -or
                [string]$currentPth.Sha256 -cne [string]$pthRow.sha256) {
                throw "$Label current Python .pth bootstrap file drifted: $pthPath"
            }
        }
        $priorPthPath = $pthPath
    }
    if ($pthNames -cnotcontains "distutils-precedence.pth" -or
        @($pthNames | Where-Object {
            $_ -cmatch '^__editable__\.weather_market-[0-9A-Za-z._-]+\.pth$'
        }).Count -ne 1) {
        throw "$Label Python .pth bootstrap names are not the reviewed pair."
    }

    $seenPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    [long]$observedBytes = 0
    [int]$observedFiles = 0
    [string]$priorDistributionKey = ""
    foreach ($distribution in @($Payload.distributions)) {
        $distributionNames = @($distribution.PSObject.Properties.Name | Sort-Object)
        $requiredDistributionNames = @(
            "name", "version", "location", "record_path", "record_sha256",
            "installer_sha256", "files"
        ) | Sort-Object
        $location = Resolve-WeatherIntegrationPath -Path ([string]$distribution.location)
        $recordPath = Resolve-WeatherIntegrationPath -Path ([string]$distribution.record_path)
        $distributionKey = (
            [string]$distribution.name + "`t" + [string]$distribution.version +
            "`t" + $location
        )
        if (($distributionNames -join "`n") -cne
                ($requiredDistributionNames -join "`n") -or
            [string]$distribution.name -cnotmatch
                '^[a-z0-9]+(?:-[a-z0-9]+)*$' -or
            [string]::IsNullOrWhiteSpace([string]$distribution.version) -or
            [string]$distribution.record_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            ($null -ne $distribution.installer_sha256 -and
                [string]$distribution.installer_sha256 -cnotmatch
                    '^[0-9a-f]{64}$') -or
            -not (& $isUnderRuntime $location) -or
            -not (& $isUnderRuntime $recordPath) -or
            [IO.Path]::GetFileName($recordPath) -cne "RECORD" -or
            (-not [string]::IsNullOrEmpty($priorDistributionKey) -and
                [StringComparer]::Ordinal.Compare(
                    $priorDistributionKey, $distributionKey
                ) -ge 0)) {
            throw "$Label has malformed or unsorted distribution evidence."
        }
        [string]$priorFilePath = ""
        $sawRecord = $false
        $recordRowSha256 = $null
        $installerRowSha256 = $null
        foreach ($file in @($distribution.files)) {
            $fileNames = @($file.PSObject.Properties.Name | Sort-Object)
            $requiredFileNames = @(
                "path", "length", "sha256", "record_algorithm",
                "record_digest", "record_size"
            ) | Sort-Object
            $path = Resolve-WeatherIntegrationPath -Path ([string]$file.path)
            if (($fileNames -join "`n") -cne ($requiredFileNames -join "`n") -or
                -not (& $isUnderRuntime $path) -or
                -not $seenPaths.Add($path) -or
                (-not [string]::IsNullOrEmpty($priorFilePath) -and
                    [StringComparer]::OrdinalIgnoreCase.Compare(
                        $priorFilePath, $path
                    ) -ge 0) -or
                [long]$file.length -lt 0 -or
                [long]$file.length -gt 536870912 -or
                [string]$file.sha256 -cnotmatch '^[0-9a-f]{64}$') {
                throw "$Label has malformed, duplicate, or unsorted distribution files."
            }
            $recordFieldsNull = ($null -eq $file.record_algorithm -and
                $null -eq $file.record_digest -and $null -eq $file.record_size)
            $mayLackRecordHash = (
                Test-WeatherIntegrationPathEqual -Left $path -Right $recordPath
            ) -or (([IO.Path]::GetExtension($path)) -ieq ".pyc")
            if (Test-WeatherIntegrationPathEqual -Left $path -Right $recordPath) {
                $sawRecord = $true
                $recordRowSha256 = [string]$file.sha256
            }
            $installerPath = Join-Path (Split-Path -Parent $recordPath) "INSTALLER"
            if (Test-WeatherIntegrationPathEqual -Left $path -Right $installerPath) {
                if ($null -ne $installerRowSha256) {
                    throw "$Label distribution repeats its INSTALLER row: $path"
                }
                $installerRowSha256 = [string]$file.sha256
            }
            if ($recordFieldsNull) {
                if (-not $mayLackRecordHash) {
                    throw "$Label has an unverifiable RECORD entry: $path"
                }
            }
            elseif ($null -eq $file.record_algorithm -or
                $null -eq $file.record_digest -or $null -eq $file.record_size -or
                [string]$file.record_algorithm -cne "sha256" -or
                [long]$file.record_size -ne [long]$file.length -or
                (ConvertFrom-WeatherIntegrationRecordSha256 `
                    -Digest ([string]$file.record_digest) `
                    -Label "$Label RECORD digest for $path") -cne
                        [string]$file.sha256) {
                throw "$Label RECORD hash or size does not verify: $path"
            }
            if ($VerifyCurrentFiles) {
                $current = Get-WeatherIntegrationOpenFileIdentity `
                    -Path $path -Label "$Label current distribution file"
                if ([long]$current.Length -ne [long]$file.length -or
                    [string]$current.Sha256 -cne [string]$file.sha256) {
                    throw "$Label current distribution file drifted: $path"
                }
            }
            $observedBytes += [long]$file.length
            $observedFiles++
            $priorFilePath = $path
        }
        if (-not $sawRecord -or
            [string]$recordRowSha256 -cne
                [string]$distribution.record_sha256 -or
            (($null -eq $installerRowSha256) -ne
                ($null -eq $distribution.installer_sha256)) -or
            ($null -ne $installerRowSha256 -and
             [string]$installerRowSha256 -cne
                [string]$distribution.installer_sha256)) {
            throw "$Label distribution RECORD/INSTALLER evidence disagrees with its file rows."
        }
        $priorDistributionKey = $distributionKey
    }
    [int]$executableRows = 0
    [int]$runtimeDllRows = 0
    [int]$launcherRows = 0
    [string]$priorRuntimePath = ""
    foreach ($file in @($Payload.runtime_files)) {
        $fileNames = @($file.PSObject.Properties.Name | Sort-Object)
        $requiredFileNames = @("kind", "path", "length", "sha256") | Sort-Object
        $path = Resolve-WeatherIntegrationPath -Path ([string]$file.path)
        if (($fileNames -join "`n") -cne ($requiredFileNames -join "`n") -or
            [string]$file.kind -cnotmatch
                '^(executable|launcher|runtime_dll|runtime_config|native_library|stdlib)$' -or
            -not (& $isUnderRuntime $path) -or -not $seenPaths.Add($path) -or
            (-not [string]::IsNullOrEmpty($priorRuntimePath) -and
                [StringComparer]::OrdinalIgnoreCase.Compare(
                    $priorRuntimePath, $path
                ) -ge 0) -or
            [long]$file.length -lt 0 -or [long]$file.length -gt 536870912 -or
            [string]$file.sha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "$Label has malformed, duplicate, or unsorted runtime files."
        }
        if ([string]$file.kind -ceq "executable") {
            $executableRows++
            if (-not (Test-WeatherIntegrationPathEqual `
                    -Left $path -Right $executable) -or
                [string]$file.sha256 -cne [string]$Payload.executable_sha256) {
                throw "$Label runtime executable row disagrees with its identity."
            }
        }
        elseif ([string]$file.kind -ceq "runtime_dll") { $runtimeDllRows++ }
        elseif ([string]$file.kind -ceq "launcher") {
            $launcherRows++
            $expectedLauncher = Join-Path `
                (Split-Path -Parent $executable) "pythonw.exe"
            if (-not (Test-WeatherIntegrationPathEqual `
                    -Left $path -Right $expectedLauncher)) {
                throw "$Label Python Scheduler launcher path is not canonical."
            }
        }
        if ($VerifyCurrentFiles) {
            $current = Get-WeatherIntegrationOpenFileIdentity `
                -Path $path -Label "$Label current runtime file"
            if ([long]$current.Length -ne [long]$file.length -or
                [string]$current.Sha256 -cne [string]$file.sha256) {
                throw "$Label current runtime file drifted: $path"
            }
        }
        $observedBytes += [long]$file.length
        $observedFiles++
        $priorRuntimePath = $path
    }
    if ($executableRows -ne 1 -or $launcherRows -ne 1 -or
        $runtimeDllRows -lt 1 -or
        $observedFiles -ne [int]$Payload.file_count -or
        $observedBytes -ne [long]$Payload.total_bytes) {
        throw "$Label file totals or mandatory runtime identities disagree."
    }
    return $Payload
}

function Assert-WeatherIntegrationCurrentQualifiedRuntimeFingerprints {
    param(
        [Parameter(Mandatory = $true)][object]$Summary,
        [Parameter(Mandatory = $true)][object]$Expected,
        [string]$Label = "qualified runtime"
    )

    $pythonPath = Resolve-WeatherIntegrationPath `
        -Path ([string]$Summary.python_environment_post_path)
    $pythonSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $pythonPath -MaximumBytes 16777216 -ContentType Json
    if ([string]$pythonSnapshot.Sha256 -cne
            [string]$Expected.expected_python_environment_sha256 -or
        [string]$pythonSnapshot.Payload.schema_version -cne
            [string]$Expected.expected_python_environment_schema) {
        throw "$Label Python environment sidecar differs from qualification."
    }
    Assert-WeatherIntegrationPythonEnvironmentFingerprintPayload `
        -Payload $pythonSnapshot.Payload `
        -ExpectedExecutable ([string]$pythonSnapshot.Payload.executable) `
        -ExpectedExecutableSha256 ([string]$Summary.python_executable_sha256) `
        -ExpectedDistributionCount (
            [int]$Expected.expected_python_environment_distributions
        ) `
        -ExpectedFileCount ([int]$Expected.expected_python_environment_files) `
        -ExpectedTotalBytes ([long]$Expected.expected_python_environment_bytes) `
        -Label "$Label Python environment" -VerifyCurrentFiles | Out-Null

    $toolchainPath = Resolve-WeatherIntegrationPath `
        -Path ([string]$Summary.toolchain_post_path)
    $toolchainSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $toolchainPath -MaximumBytes 1048576 -ContentType Json
    $toolchain = $toolchainSnapshot.Payload
    Assert-WeatherIntegrationRequiredProperties `
        -Object $toolchain -Names @(
            "schema_version", "git", "git_lfs", "powershell", "controls"
        ) -Label "$Label toolchain sidecar"
    foreach ($name in @("git", "git_lfs", "powershell")) {
        Assert-WeatherIntegrationRequiredProperties `
            -Object $toolchain.$name `
            -Names @("executable", "executable_sha256") `
            -Label "$Label $name toolchain identity"
    }
    $toolchainControlNames = @(
        $toolchain.controls.PSObject.Properties.Name | Sort-Object
    )
    $requiredToolchainControls = @(
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
    if ([string]$toolchainSnapshot.Sha256 -cne
            [string]$Expected.expected_toolchain_sha256 -or
        [string]$toolchain.schema_version -cne
            "integration_toolchain_fingerprint_v1" -or
        [string]$toolchain.git.executable_sha256 -cne
            [string]$Summary.toolchain_git_sha256 -or
        [string]$toolchain.git_lfs.executable_sha256 -cne
            [string]$Summary.toolchain_git_lfs_sha256 -or
        [string]$toolchain.powershell.executable_sha256 -cne
            [string]$Summary.toolchain_powershell_sha256 -or
        ($toolchainControlNames -join "`n") -cne
            ($requiredToolchainControls -join "`n") -or
        [string]$toolchain.controls.pythonhashseed -cne "0" -or
        [string]$toolchain.controls.pythonutf8 -cne "1" -or
        [string]$toolchain.controls.pythonioencoding -cne "utf-8" -or
        [string]$toolchain.controls.git_allow_protocol -cne "file" -or
        [string]$toolchain.controls.git_terminal_prompt -cne "0" -or
        [string]$toolchain.controls.git_config_nosystem -cne "1" -or
        [string]$toolchain.controls.git_config_system -cne "NUL" -or
        [string]$toolchain.controls.git_config_global -cne "NUL" -or
        [string]$toolchain.controls.git_config_count -cne "0" -or
        [string]$toolchain.controls.git_attr_nosystem -cne "1" -or
        [string]$toolchain.controls.git_protocol_from_user -cne "0" -or
        [string]$toolchain.controls.git_optional_locks -cne "0" -or
        $toolchain.controls.git_topology_environment_clear -isnot [bool] -or
        -not [bool]$toolchain.controls.git_topology_environment_clear -or
        [int]$toolchain.controls.git_topology_environment_count -ne 0 -or
        [string]$toolchain.controls.offline -cne "1" -or
        -not [string]::IsNullOrEmpty(
            [string]$toolchain.controls.allowed_write_root
        ) -or
        -not [IO.Path]::IsPathRooted(
            [string]$toolchain.controls.candidate_root
        ) -or
        -not [IO.Path]::IsPathRooted(
            [string]$toolchain.controls.production_root
        ) -or
        -not [IO.Path]::IsPathRooted(
            [string]$toolchain.controls.evidence_root
        ) -or
        [string]$toolchain.controls.secret_policy -cne "conservative_v1" -or
        $toolchain.controls.secret_environment_clear -isnot [bool] -or
        -not [bool]$toolchain.controls.secret_environment_clear -or
        [int]$toolchain.controls.secret_environment_count -ne 0 -or
        [string]$toolchain.controls.temp_policy -cne "system_temp_unique_v1" -or
        [string]$toolchain.controls.setuptools_use_distutils -cne "stdlib" -or
        $toolchain.controls.read_only_production_probe -isnot [bool] -or
        [bool]$toolchain.controls.read_only_production_probe -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$toolchain.controls.python_executable) `
            -Right ([string]$pythonSnapshot.Payload.executable)) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$toolchain.controls.git_executable) `
            -Right ([string]$toolchain.git.executable)) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$toolchain.controls.powershell_executable) `
            -Right ([string]$toolchain.powershell.executable)) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$pythonSnapshot.Payload.controls.python_executable) `
            -Right ([string]$pythonSnapshot.Payload.executable)) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$pythonSnapshot.Payload.controls.git_executable) `
            -Right ([string]$toolchain.git.executable)) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$pythonSnapshot.Payload.controls.powershell_executable) `
            -Right ([string]$toolchain.powershell.executable)) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$pythonSnapshot.Payload.controls.evidence_root) `
            -Right ([string]$toolchain.controls.evidence_root))) {
        throw "$Label toolchain sidecar differs from qualification."
    }
    $resolvedGit = Get-WeatherIntegrationGitExecutablePath `
        -Phase "$Label Git identity" `
        -ExpectedPath ([string]$toolchain.git.executable)
    $resolvedGitLfs = Get-WeatherIntegrationGitLfsExecutablePath `
        -Phase "$Label Git LFS identity" -GitExecutable $resolvedGit
    $expectedPowerShell = Resolve-WeatherIntegrationPath `
        -Path (Join-Path $PSHOME "powershell.exe")
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left $resolvedGitLfs -Right ([string]$toolchain.git_lfs.executable)) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left $expectedPowerShell `
            -Right ([string]$toolchain.powershell.executable))) {
        throw "$Label currently resolves a different qualified toolchain path."
    }
    foreach ($row in @(
        [pscustomobject]@{
            Name = "Git"; Path = $resolvedGit
            Sha = [string]$toolchain.git.executable_sha256
        },
        [pscustomobject]@{
            Name = "Git LFS"; Path = $resolvedGitLfs
            Sha = [string]$toolchain.git_lfs.executable_sha256
        },
        [pscustomobject]@{
            Name = "PowerShell"; Path = $expectedPowerShell
            Sha = [string]$toolchain.powershell.executable_sha256
        }
    )) {
        $current = Get-WeatherIntegrationOpenFileIdentity `
            -Path ([string]$row.Path) -Label "$Label current $($row.Name)"
        if ([string]$current.Sha256 -cne [string]$row.Sha) {
            throw "$Label current $($row.Name) bytes differ from qualification."
        }
    }
    return [pscustomobject]@{
        PythonEnvironmentPath = $pythonPath
        ToolchainPath = $toolchainPath
    }
}

function Assert-WeatherIntegrationNoIgnoredImportArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$WorktreeRoot,
        [string]$Phase = "integration-attempt boundary"
    )

    # Scope ignored-file discovery to paths Python/pytest can actually consume
    # in an attempt. In particular, do not walk the ignored data/ evidence tree.
    # AdditionalPythonPath is forbidden for attempts, so there is no external
    # import root to add here.
    $blockedExtensions = @(
        ".py", ".pyi", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib"
    )
    $blockedControlNames = @(
        "sitecustomize.py", "conftest.py", "pytest.ini", "pyproject.toml",
        "tox.ini", "setup.cfg"
    )
    # Root itself is on sys.path. Derive every established top-level Python
    # namespace from the tracked inventory, then add the canonical import/test
    # roots. This catches tools and future tracked namespace packages without
    # walking unrelated ignored trees.
    $trackedNamespaceQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root (Resolve-WeatherIntegrationPath -Path $WorktreeRoot) `
        -Arguments (@("ls-files", "--") + @(
            "*.py", "*.pyi", "*.pyd", "*.so", "*.dll", "*.dylib"
        )) `
        -Label "$Phase tracked Python/native namespace query"
    $trackedImportRoots = @(
        @($trackedNamespaceQuery.StdoutLines) |
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
        @($blockedControlNames) + $rootExtensionPathspecs + $importRootPathspecs
    )
    $query = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root (Resolve-WeatherIntegrationPath -Path $WorktreeRoot) `
        -Arguments (@(
            "ls-files", "--others", "--ignored", "--exclude-standard", "--"
        ) + $importControlPathspecs) `
        -Label "$Phase ignored import/config namespace query"
    $blocked = @(
        @($query.StdoutLines) |
            ForEach-Object { ([string]$_).Replace("\", "/") } |
            Where-Object {
                if ([string]::IsNullOrWhiteSpace($_)) { return $false }
                $leaf = [IO.Path]::GetFileName([string]$_)
                $extension = [IO.Path]::GetExtension([string]$_)
                $isRootControl = ([string]$_ -notmatch '/' -and
                    $blockedControlNames -icontains $leaf)
                $isRootExtension = ([string]$_ -notmatch '/' -and
                    $blockedExtensions -icontains $extension)
                $topLevel = if ([string]$_ -match '/') {
                    ([string]$_ -split '/', 2)[0]
                }
                else { "" }
                $isImportRootArtifact = ($importRoots -icontains $topLevel) -and
                    ($blockedControlNames -icontains $leaf -or
                     $blockedExtensions -icontains $extension)
                return (
                    $isRootControl -or $isRootExtension -or
                    $isImportRootArtifact
                )
            } |
            Sort-Object -Unique
    )
    if ($blocked.Count -ne 0) {
        $sample = @($blocked | Select-Object -First 10) -join ", "
        throw "$Phase refuses ignored Python/native import or test-config artifacts: $sample"
    }
    return [pscustomobject]@{ Count = 0; Paths = @() }
}

function Read-WeatherIntegrationSharedText {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 268435456)]
        [long]$MaximumBytes = 67108864
    )

    return [string](Read-WeatherIntegrationEvidenceSnapshot `
        -Path $Path -MaximumBytes $MaximumBytes -ContentType Text).Text
}

function Enter-WeatherIntegrationControlMutex {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet("heavy_workload.lock", "integration_attempt_terminal.lock")]
        [string]$LockLeaf,
        [Parameter(Mandatory = $true)][string]$Owner
    )

    $logRoot = Join-Path (Resolve-WeatherIntegrationPath -Path $RepositoryRoot) "data\logs"
    if (-not (Test-Path -LiteralPath $logRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    }
    $lockPath = Join-Path $logRoot $LockLeaf
    try {
        $stream = [IO.File]::Open(
            $lockPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::Read
        )
    }
    catch [IO.IOException] { return $null }
    try {
        $stream.SetLength(0)
        $payload = [ordered]@{
            schema = "weather_integration_control_mutex_v1"
            owner = $Owner
            pid = $PID
            acquired_at = (Get-Date).ToUniversalTime().ToString("o")
        }
        $writer = New-Object IO.StreamWriter(
            $stream,
            (New-Object Text.UTF8Encoding($false)),
            1024,
            $true
        )
        try {
            $writer.Write(($payload | ConvertTo-Json -Compress))
            $writer.Flush()
            $stream.Flush()
        }
        finally { $writer.Dispose() }
        return [pscustomobject]@{ Path = $lockPath; Stream = $stream }
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Exit-WeatherIntegrationControlMutex {
    param(
        [AllowNull()][object]$Mutex,
        [AllowNull()][Management.Automation.ErrorRecord]$PrimaryError
    )
    if ($null -eq $Mutex -or $null -eq $Mutex.Stream) { return }
    try { $Mutex.Stream.Dispose() }
    catch {
        $cleanupMessage = "Integration control mutex cleanup failed: $($_.Exception.Message)"
        if ($null -ne $PrimaryError) {
            $priorCleanup = [string]$PrimaryError.Exception.Data[
                "weather_cleanup_failure"
            ]
            $combinedCleanup = if ([string]::IsNullOrWhiteSpace($priorCleanup)) {
                $cleanupMessage
            }
            else { "$priorCleanup | $cleanupMessage" }
            $PrimaryError.Exception.Data["weather_cleanup_failure"] =
                $combinedCleanup
            $existingDetail = if ($null -eq $PrimaryError.ErrorDetails) {
                ""
            }
            else { [string]$PrimaryError.ErrorDetails.Message }
            $combinedDetail = if ([string]::IsNullOrWhiteSpace($existingDetail)) {
                "$($PrimaryError.Exception.Message); $cleanupMessage"
            }
            else { "$existingDetail; $cleanupMessage" }
            $PrimaryError.ErrorDetails =
                [Management.Automation.ErrorDetails]::new($combinedDetail)
            Write-Warning $cleanupMessage -WarningAction Continue
            return
        }
        throw $cleanupMessage
    }
}

function Get-WeatherIntegrationScheduledTaskSnapshot {
    # A full successful enumeration is an explicit prerequisite for treating an
    # exact task as absent during rollback or closure.
    return @(Get-ScheduledTask -ErrorAction Stop)
}

function Assert-WeatherIntegrationAttemptNotTerminal {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$Operation
    )

    $attempt = $AttemptContract.Manifest
    foreach ($terminal in @(
        [pscustomobject]@{ Label = "closure"; Path = [string]$attempt.evidence.closure_receipt },
        [pscustomobject]@{ Label = "reconciliation"; Path = [string]$attempt.evidence.reconciliation_receipt }
    )) {
        if (Test-Path -LiteralPath $terminal.Path) {
            throw "$Operation is forbidden because the attempt already has a terminal $($terminal.Label) receipt: $($terminal.Path)"
        }
    }
}

function Get-WeatherIntegrationLogVerdict {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [AllowNull()][object]$EvidenceSnapshot = $null
    )

    $resolvedPath = Resolve-WeatherIntegrationPath -Path $Path
    $snapshot = if ($null -eq $EvidenceSnapshot) {
        Read-WeatherIntegrationEvidenceSnapshot -Path $resolvedPath -MaximumBytes 67108864 -ContentType Text
    }
    else { $EvidenceSnapshot }
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$snapshot.Path) -Right $resolvedPath)) {
        throw "Retained log snapshot uses the wrong path: $resolvedPath"
    }
    $lines = @(
        ([string]$snapshot.Text) -split "`r?`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($lines.Count -eq 0) {
        throw "Attempt log is empty: $Path"
    }
    return [string]$lines[-1]
}

function Assert-WeatherIntegrationFullSuiteVerdict {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Verdict,
        [ValidateRange(0, 100000)]
        [int]$ExpectedChunkCount = 0
    )

    $match = [regex]::Match(
        $Verdict,
        '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}  VERDICT: ALL CHUNKS PASSED \((?<passed>[0-9]+)/(?<planned>[0-9]+)\); exact tip eligible for separate reviewed merge$'
    )
    if (-not $match.Success) {
        throw "Full suite log is missing its exact PASS verdict."
    }
    $passed = [int]$match.Groups["passed"].Value
    $planned = [int]$match.Groups["planned"].Value
    if ($passed -le 0 -or $passed -ne $planned -or
        ($ExpectedChunkCount -gt 0 -and $planned -ne $ExpectedChunkCount)) {
        throw "Full suite PASS verdict has an invalid chunk ratio: $passed/$planned"
    }
    return $planned
}

function Assert-WeatherIntegrationPreflightVerdict {
    param(
        [Parameter(Mandatory = $true)][string]$Verdict
    )

    if ($Verdict -notmatch '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}  VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge is not authorized$') {
        throw "Integration preflight log is missing its exact PASS verdict."
    }
}

function Assert-WeatherIntegrationFullSuiteLogPlan {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateRange(1, 1000000)][int]$ExpectedTestFileCount,
        [Parameter(Mandatory = $true)][ValidateRange(1, 25)][int]$ExpectedMaxFilesPerChunk,
        [Parameter(Mandatory = $true)][ValidateRange(1, 100000)][int]$ExpectedChunkCount,
        [AllowNull()][object]$EvidenceSnapshot = $null
    )

    $plan = Get-WeatherIntegrationSuiteLogDeclaredPlan `
        -Path $Path -EvidenceSnapshot $EvidenceSnapshot
    if ([int]$plan.Files -ne $ExpectedTestFileCount -or
        [int]$plan.MaxFilesPerChunk -ne $ExpectedMaxFilesPerChunk -or
        [int]$plan.Chunks -ne $ExpectedChunkCount) {
        throw (
            "Full suite test plan does not match the frozen manifest: " +
            "chunks=$($plan.Chunks) files=$($plan.Files) " +
            "max_files=$($plan.MaxFilesPerChunk)"
        )
    }
    return $plan
}

function Get-WeatherIntegrationSuiteLogDeclaredPlan {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [AllowNull()][object]$EvidenceSnapshot = $null
    )

    $resolvedPath = Resolve-WeatherIntegrationPath -Path $Path
    $snapshot = if ($null -eq $EvidenceSnapshot) {
        Read-WeatherIntegrationEvidenceSnapshot `
            -Path $resolvedPath -MaximumBytes 67108864 -ContentType Text
    }
    else { $EvidenceSnapshot }
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$snapshot.Path) -Right $resolvedPath)) {
        throw "Retained suite-plan snapshot uses the wrong path: $resolvedPath"
    }
    $matches = [regex]::Matches(
        [string]$snapshot.Text,
        '(?m)^.*?  planned chunks=(?<chunks>[0-9]+) files=(?<files>[0-9]+) max_files=(?<max>[0-9]+)\r?$'
    )
    if ($matches.Count -ne 1) {
        throw "Suite log must contain exactly one immutable test plan."
    }
    $chunks = [int]$matches[0].Groups["chunks"].Value
    $files = [int]$matches[0].Groups["files"].Value
    $maxFiles = [int]$matches[0].Groups["max"].Value
    if ($chunks -le 0 -or $files -le 0 -or $maxFiles -le 0 -or
        $chunks -ne [int][math]::Ceiling($files / [double]$maxFiles)) {
        throw "Suite log immutable test plan has an invalid file/chunk ratio."
    }
    return [pscustomobject]@{
        Chunks = $chunks
        Files = $files
        MaxFilesPerChunk = $maxFiles
    }
}

function Get-WeatherIntegrationJUnitFileSummary {
    param([Parameter(Mandatory = $true)][string]$Path)

    $resolvedPath = Resolve-WeatherIntegrationPath -Path $Path
    $snapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $resolvedPath -MaximumBytes 67108864 -ContentType Text
    if ([long]$snapshot.Length -le 0) {
        throw "Suite JUnit evidence is not a bounded regular file: $resolvedPath"
    }
    $settings = New-Object System.Xml.XmlReaderSettings
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $textReader = New-Object IO.StringReader([string]$snapshot.Text)
    $reader = [System.Xml.XmlReader]::Create($textReader, $settings)
    try {
        $document = New-Object System.Xml.XmlDocument
        $document.XmlResolver = $null
        $document.Load($reader)
    }
    finally {
        $reader.Dispose()
        $textReader.Dispose()
    }
    $suiteNodes = if ($document.DocumentElement.Name -ceq "testsuite") {
        @($document.DocumentElement)
    }
    elseif ($document.DocumentElement.Name -ceq "testsuites") {
        @($document.DocumentElement.SelectNodes("./testsuite"))
    }
    else { @() }
    if ($suiteNodes.Count -eq 0) {
        throw "Suite JUnit evidence has no top-level testsuite: $resolvedPath"
    }
    $summary = [ordered]@{
        tests = 0
        failures = 0
        errors = 0
        skipped = 0
        deselected = 0
    }
    foreach ($suiteNode in $suiteNodes) {
        foreach ($name in $summary.Keys) {
            $attribute = $suiteNode.Attributes[$name]
            if ($null -eq $attribute) {
                if ($name -eq "tests") {
                    throw "Suite JUnit testsuite is missing its tests count: $resolvedPath"
                }
                continue
            }
            if ([string]$attribute.Value -notmatch '^[0-9]+$') {
                throw "Suite JUnit testsuite has an invalid $name count: $resolvedPath"
            }
            $summary[$name] += [int]$attribute.Value
        }
    }
    $summary["sha256"] = [string]$snapshot.Sha256
    return [pscustomobject]$summary
}

function Get-WeatherIntegrationSuiteEvidenceSummary {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$ExpectedChunkCount,
        [Parameter(Mandatory = $true)][int]$ExpectedPlannedFiles,
        [AllowNull()][object]$EvidenceSnapshot = $null,
        [switch]$RequireRuntimeFingerprint
    )

    $resolvedPath = Resolve-WeatherIntegrationPath -Path $Path
    $snapshot = if ($null -eq $EvidenceSnapshot) {
        Read-WeatherIntegrationEvidenceSnapshot `
            -Path $resolvedPath -MaximumBytes 67108864 -ContentType Text
    }
    else { $EvidenceSnapshot }
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$snapshot.Path) -Right $resolvedPath)) {
        throw "Retained suite-evidence snapshot uses the wrong path: $resolvedPath"
    }
    $text = [string]$snapshot.Text
    $syntaxMatches = [regex]::Matches(
        $text,
        '(?m)^.*?  syntax python_files=(?<python>[0-9]+) python_inventory_sha256=(?<python_sha>[0-9a-f]{64}) python_list=(?<python_list>.+?) powershell_files=(?<powershell>[0-9]+) powershell_inventory_sha256=(?<powershell_sha>[0-9a-f]{64}) powershell_list=(?<powershell_list>.+?) python_exit=(?<python_exit>-?[0-9]+) powershell_errors=(?<powershell_errors>[0-9]+)\r?$'
    )
    $aggregateMatches = [regex]::Matches(
        $text,
        '(?m)^.*?  aggregate tests=(?<tests>[0-9]+) failures=(?<failures>[0-9]+) errors=(?<errors>[0-9]+) skipped=(?<skipped>[0-9]+) deselected=(?<deselected>[0-9]+) planned_files=(?<files>[0-9]+) inventory_sha256=(?<inventory_sha>[0-9a-f]{64}) inventory_path=(?<inventory_path>.+?)\r?$'
    )
    $junitMatches = [regex]::Matches(
        $text,
        '(?m)^.*?  chunk (?<ordinal>[0-9]+)/(?<chunks>[0-9]+) junit_summary path=(?<path>.+?) sha256=(?<sha>[0-9a-f]{64}) tests=(?<tests>[0-9]+) failures=(?<failures>[0-9]+) errors=(?<errors>[0-9]+) skipped=(?<skipped>[0-9]+) deselected=(?<deselected>[0-9]+)\r?$'
    )
    $pythonEnvironmentMatches = [regex]::Matches(
        $text,
        '(?m)^.*?  python_environment phase=(?<phase>pre|post) schema=(?<schema>python_environment_fingerprint_v[12]) sha256=(?<sha>[0-9a-f]{64}) distributions=(?<distributions>[0-9]+)(?: files=(?<files>[0-9]+) bytes=(?<bytes>[0-9]+))? path=(?<path>.+?)\r?$'
    )
    $pythonEnvironmentStableMatches = [regex]::Matches(
        $text,
        '(?m)^.*?  python_environment stable=true pre_sha256=(?<pre_sha>[0-9a-f]{64}) post_sha256=(?<post_sha>[0-9a-f]{64}) distributions=(?<distributions>[0-9]+)(?: files=(?<files>[0-9]+) bytes=(?<bytes>[0-9]+))?\r?$'
    )
    $toolchainMatches = [regex]::Matches(
        $text,
        '(?m)^.*?  integration_toolchain phase=(?<phase>pre|post) schema=(?<schema>integration_toolchain_fingerprint_v1) sha256=(?<sha>[0-9a-f]{64}) git_sha256=(?<git_sha>[0-9a-f]{64}) git_lfs_sha256=(?<git_lfs_sha>[0-9a-f]{64}) powershell_sha256=(?<powershell_sha>[0-9a-f]{64}) path=(?<path>.+?)\r?$'
    )
    $toolchainStableMatches = [regex]::Matches(
        $text,
        '(?m)^.*?  integration_toolchain stable=true pre_sha256=(?<pre_sha>[0-9a-f]{64}) post_sha256=(?<post_sha>[0-9a-f]{64})\r?$'
    )
    $trackedWorktreeMatches = [regex]::Matches(
        $text,
        '(?m)^.*?  tracked_worktree phase=(?<phase>pre|post) schema=(?<schema>tracked_worktree_content_fingerprint_v1) sha256=(?<sha>[0-9a-f]{64}) files=(?<files>[0-9]+) bytes=(?<bytes>[0-9]+) lfs_files=(?<lfs_files>[0-9]+) path=(?<path>.+?)\r?$'
    )
    $trackedWorktreeStableMatches = [regex]::Matches(
        $text,
        '(?m)^.*?  tracked_worktree stable=true pre_sha256=(?<pre_sha>[0-9a-f]{64}) post_sha256=(?<post_sha>[0-9a-f]{64}) files=(?<files>[0-9]+) bytes=(?<bytes>[0-9]+) lfs_files=(?<lfs_files>[0-9]+)\r?$'
    )
    $runtimeFingerprintRecordCount = $pythonEnvironmentMatches.Count +
        $pythonEnvironmentStableMatches.Count + $toolchainMatches.Count +
        $toolchainStableMatches.Count
    if ($syntaxMatches.Count -ne 1 -or $aggregateMatches.Count -ne 1 -or
        $junitMatches.Count -ne $ExpectedChunkCount) {
        throw "Suite log lacks one exact syntax/aggregate record and every JUnit binding."
    }
    $hasRuntimeFingerprint = ($runtimeFingerprintRecordCount -ne 0)
    if (($RequireRuntimeFingerprint -or $hasRuntimeFingerprint) -and
        ($pythonEnvironmentMatches.Count -ne 2 -or
         $pythonEnvironmentStableMatches.Count -ne 1 -or
         $toolchainMatches.Count -ne 2 -or
         $toolchainStableMatches.Count -ne 1)) {
        throw "Suite log lacks one complete exact Python-environment/toolchain fingerprint."
    }
    $trackedFingerprintRecordCount = $trackedWorktreeMatches.Count +
        $trackedWorktreeStableMatches.Count
    $hasTrackedFingerprint = ($trackedFingerprintRecordCount -ne 0)
    if (($RequireRuntimeFingerprint -or $hasTrackedFingerprint) -and
        ($trackedWorktreeMatches.Count -ne 2 -or
         $trackedWorktreeStableMatches.Count -ne 1)) {
        throw "Suite log lacks one complete exact tracked-worktree content fingerprint."
    }
    $pythonEnvironmentByPhase = @{}
    $toolchainByPhase = @{}
    $pythonEnvironmentSnapshots = @{}
    $trackedWorktreeByPhase = @{}
    $trackedWorktreeSnapshots = @{}
    if ($hasRuntimeFingerprint) {
        foreach ($match in $pythonEnvironmentMatches) {
            $phase = [string]$match.Groups["phase"].Value
            if ($pythonEnvironmentByPhase.ContainsKey($phase)) {
                throw "Suite log repeats its Python environment $phase record."
            }
            $pythonEnvironmentByPhase[$phase] = $match.Groups
        }
        foreach ($match in $toolchainMatches) {
            $phase = [string]$match.Groups["phase"].Value
            if ($toolchainByPhase.ContainsKey($phase)) {
                throw "Suite log repeats its integration toolchain $phase record."
            }
            $toolchainByPhase[$phase] = $match.Groups
        }
        if (-not $pythonEnvironmentByPhase.ContainsKey("pre") -or
            -not $pythonEnvironmentByPhase.ContainsKey("post") -or
            -not $toolchainByPhase.ContainsKey("pre") -or
            -not $toolchainByPhase.ContainsKey("post")) {
            throw "Suite log lacks exact pre/post runtime fingerprint records."
        }
        $pythonEnvironmentPre = $pythonEnvironmentByPhase["pre"]
        $pythonEnvironmentPost = $pythonEnvironmentByPhase["post"]
        $pythonEnvironmentStable = $pythonEnvironmentStableMatches[0].Groups
        $toolchainPre = $toolchainByPhase["pre"]
        $toolchainPost = $toolchainByPhase["post"]
        $toolchainStable = $toolchainStableMatches[0].Groups
        $pythonSchema = [string]$pythonEnvironmentPre["schema"].Value
        if ([string]$pythonEnvironmentPre["sha"].Value -cne
                [string]$pythonEnvironmentPost["sha"].Value -or
            [string]$pythonEnvironmentStable["pre_sha"].Value -cne
                [string]$pythonEnvironmentPre["sha"].Value -or
            [string]$pythonEnvironmentStable["post_sha"].Value -cne
                [string]$pythonEnvironmentPost["sha"].Value -or
            [int]$pythonEnvironmentPre["distributions"].Value -ne
                [int]$pythonEnvironmentPost["distributions"].Value -or
            [int]$pythonEnvironmentStable["distributions"].Value -ne
                [int]$pythonEnvironmentPost["distributions"].Value -or
            [string]$toolchainPre["sha"].Value -cne
                [string]$toolchainPost["sha"].Value -or
            [string]$toolchainStable["pre_sha"].Value -cne
                [string]$toolchainPre["sha"].Value -or
            [string]$toolchainStable["post_sha"].Value -cne
                [string]$toolchainPost["sha"].Value) {
            throw "Suite log does not prove stable runtime fingerprints."
        }
        if ([string]$pythonEnvironmentPost["schema"].Value -cne $pythonSchema -or
            ($RequireRuntimeFingerprint -and $pythonSchema -cne
                "python_environment_fingerprint_v2") -or
            ($pythonSchema -ceq "python_environment_fingerprint_v2" -and
                ([int]$pythonEnvironmentPre["files"].Value -le 0 -or
                 [int]$pythonEnvironmentPre["files"].Value -ne
                    [int]$pythonEnvironmentPost["files"].Value -or
                 [int]$pythonEnvironmentStable["files"].Value -ne
                    [int]$pythonEnvironmentPost["files"].Value -or
                 [long]$pythonEnvironmentPre["bytes"].Value -le 0 -or
                 [long]$pythonEnvironmentPre["bytes"].Value -ne
                    [long]$pythonEnvironmentPost["bytes"].Value -or
                 [long]$pythonEnvironmentStable["bytes"].Value -ne
                    [long]$pythonEnvironmentPost["bytes"].Value))) {
            throw "Suite log does not prove one stable verified Python v2 content fingerprint."
        }
        foreach ($phase in @("pre", "post")) {
            $pythonGroups = $pythonEnvironmentByPhase[$phase]
            $toolchainGroups = $toolchainByPhase[$phase]
            $pythonPath = Resolve-WeatherIntegrationPath `
                -Path ([string]$pythonGroups["path"].Value)
            $toolchainPath = Resolve-WeatherIntegrationPath `
                -Path ([string]$toolchainGroups["path"].Value)
            $expectedPythonPath = "$resolvedPath.python-environment.$phase.json"
            $expectedToolchainPath = "$resolvedPath.integration-toolchain.$phase.json"
            if (-not (Test-WeatherIntegrationPathEqual `
                    -Left $pythonPath -Right $expectedPythonPath) -or
                -not (Test-WeatherIntegrationPathEqual `
                    -Left $toolchainPath -Right $expectedToolchainPath)) {
                throw "Suite runtime fingerprint sidecar path is not canonical for $phase."
            }
            $pythonSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
                -Path $pythonPath -MaximumBytes 16777216 -ContentType Json
            $pythonEnvironmentSnapshots[$phase] = $pythonSnapshot
            $toolchainSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
                -Path $toolchainPath -MaximumBytes 1048576 -ContentType Json
            if ([string]$pythonSnapshot.Sha256 -cne
                    [string]$pythonGroups["sha"].Value -or
                [string]$pythonSnapshot.Payload.schema_version -cne
                    [string]$pythonGroups["schema"].Value -or
                [string]$pythonSnapshot.Payload.executable_sha256 -cnotmatch
                    '^[0-9a-f]{64}$' -or
                [string]::IsNullOrWhiteSpace(
                    [string]$pythonSnapshot.Payload.executable
                ) -or
                @($pythonSnapshot.Payload.distributions).Count -ne
                    [int]$pythonGroups["distributions"].Value -or
                [string]$toolchainSnapshot.Sha256 -cne
                    [string]$toolchainGroups["sha"].Value -or
                [string]$toolchainSnapshot.Payload.schema_version -cne
                    "integration_toolchain_fingerprint_v1" -or
                [string]$toolchainSnapshot.Payload.git.executable_sha256 -cne
                    [string]$toolchainGroups["git_sha"].Value -or
                [string]$toolchainSnapshot.Payload.git_lfs.executable_sha256 -cne
                    [string]$toolchainGroups["git_lfs_sha"].Value -or
                [string]$toolchainSnapshot.Payload.powershell.executable_sha256 -cne
                    [string]$toolchainGroups["powershell_sha"].Value) {
                throw "Suite runtime fingerprint sidecar is malformed or changed for $phase."
            }
            if ([string]$pythonGroups["schema"].Value -ceq
                    "python_environment_fingerprint_v2") {
                Assert-WeatherIntegrationPythonEnvironmentFingerprintPayload `
                    -Payload $pythonSnapshot.Payload `
                    -ExpectedExecutable ([string]$pythonSnapshot.Payload.executable) `
                    -ExpectedExecutableSha256 (
                        [string]$pythonSnapshot.Payload.executable_sha256
                    ) `
                    -ExpectedDistributionCount (
                        [int]$pythonGroups["distributions"].Value
                    ) `
                    -ExpectedFileCount ([int]$pythonGroups["files"].Value) `
                    -ExpectedTotalBytes ([long]$pythonGroups["bytes"].Value) `
                    -Label "Suite Python environment $phase sidecar" | Out-Null
            }
            $toolchainControls = $toolchainSnapshot.Payload.controls
            $toolchainControlNames = @(
                $toolchainControls.PSObject.Properties.Name | Sort-Object
            )
            $requiredToolchainControls = @(
                "allowed_write_root", "candidate_root", "git_allow_protocol",
                "git_terminal_prompt", "offline", "production_root",
                "pythonhashseed", "pythonioencoding", "pythonutf8",
                "secret_environment_clear", "secret_environment_count",
                "secret_policy", "temp_policy"
            ) | Sort-Object
            if (($toolchainControlNames -join "`n") -cne
                    ($requiredToolchainControls -join "`n") -or
                [string]$toolchainControls.pythonhashseed -cne "0" -or
                [string]$toolchainControls.pythonutf8 -cne "1" -or
                [string]$toolchainControls.pythonioencoding -cne "utf-8" -or
                [string]$toolchainControls.git_allow_protocol -cne "file" -or
                [string]$toolchainControls.git_terminal_prompt -cne "0" -or
                [string]$toolchainControls.offline -cne "1" -or
                -not [string]::IsNullOrEmpty(
                    [string]$toolchainControls.allowed_write_root
                ) -or
                -not [IO.Path]::IsPathRooted(
                    [string]$toolchainControls.candidate_root
                ) -or
                -not [IO.Path]::IsPathRooted(
                    [string]$toolchainControls.production_root
                ) -or
                [string]$toolchainControls.secret_policy -cne
                    "conservative_v1" -or
                $toolchainControls.secret_environment_clear -isnot [bool] -or
                -not [bool]$toolchainControls.secret_environment_clear -or
                [int]$toolchainControls.secret_environment_count -ne 0 -or
                [string]$toolchainControls.temp_policy -cne
                    "system_temp_unique_v1" -or
                -not (Test-WeatherIntegrationPathEqual `
                    -Left ([string]$toolchainControls.candidate_root) `
                    -Right ([string]$pythonSnapshot.Payload.controls.candidate_root)) -or
                -not (Test-WeatherIntegrationPathEqual `
                    -Left ([string]$toolchainControls.production_root) `
                    -Right ([string]$pythonSnapshot.Payload.controls.production_root))) {
                throw "Suite toolchain $phase sidecar has invalid or inconsistent deterministic controls."
            }
        }
    }
    if ($hasTrackedFingerprint) {
        foreach ($match in $trackedWorktreeMatches) {
            $phase = [string]$match.Groups["phase"].Value
            if ($trackedWorktreeByPhase.ContainsKey($phase)) {
                throw "Suite log repeats its tracked-worktree $phase record."
            }
            $trackedWorktreeByPhase[$phase] = $match.Groups
        }
        if (-not $trackedWorktreeByPhase.ContainsKey("pre") -or
            -not $trackedWorktreeByPhase.ContainsKey("post")) {
            throw "Suite log lacks exact pre/post tracked-worktree records."
        }
        $trackedPre = $trackedWorktreeByPhase["pre"]
        $trackedPost = $trackedWorktreeByPhase["post"]
        $trackedStable = $trackedWorktreeStableMatches[0].Groups
        if ([string]$trackedPre["sha"].Value -cne
                [string]$trackedPost["sha"].Value -or
            [string]$trackedStable["pre_sha"].Value -cne
                [string]$trackedPre["sha"].Value -or
            [string]$trackedStable["post_sha"].Value -cne
                [string]$trackedPost["sha"].Value -or
            [int]$trackedPre["files"].Value -ne
                [int]$trackedPost["files"].Value -or
            [int]$trackedStable["files"].Value -ne
                [int]$trackedPost["files"].Value -or
            [long]$trackedPre["bytes"].Value -ne
                [long]$trackedPost["bytes"].Value -or
            [long]$trackedStable["bytes"].Value -ne
                [long]$trackedPost["bytes"].Value -or
            [int]$trackedPre["lfs_files"].Value -ne
                [int]$trackedPost["lfs_files"].Value -or
            [int]$trackedStable["lfs_files"].Value -ne
                [int]$trackedPost["lfs_files"].Value) {
            throw "Suite log does not prove stable tracked-worktree content."
        }
        foreach ($phase in @("pre", "post")) {
            $groups = $trackedWorktreeByPhase[$phase]
            $sidecarPath = Resolve-WeatherIntegrationPath `
                -Path ([string]$groups["path"].Value)
            $expectedSidecarPath = "$resolvedPath.tracked-worktree.$phase.json"
            if (-not (Test-WeatherIntegrationPathEqual `
                    -Left $sidecarPath -Right $expectedSidecarPath)) {
                throw "Suite tracked-worktree sidecar path is not canonical for $phase."
            }
            $sidecarSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
                -Path $sidecarPath -MaximumBytes 16777216 -ContentType Json
            $trackedWorktreeSnapshots[$phase] = $sidecarSnapshot
            Assert-WeatherIntegrationTrackedWorktreeFingerprintPayload `
                -Payload $sidecarSnapshot.Payload `
                -ExpectedRoot ([string]$sidecarSnapshot.Payload.root) `
                -ExpectedHead ([string]$sidecarSnapshot.Payload.head) `
                -ExpectedSha256 ([string]$groups["sha"].Value) `
                -ExpectedFileCount ([int]$groups["files"].Value) `
                -ExpectedTotalBytes ([long]$groups["bytes"].Value) `
                -ExpectedLfsFileCount ([int]$groups["lfs_files"].Value) `
                -Label "Suite tracked-worktree $phase sidecar" | Out-Null
        }
        $prePayload = $trackedWorktreeSnapshots["pre"].Payload
        $postPayload = $trackedWorktreeSnapshots["post"].Payload
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$prePayload.root) `
                -Right ([string]$postPayload.root)) -or
            [string]$prePayload.head -cne [string]$postPayload.head) {
            throw "Suite tracked-worktree pre/post sidecars bind different roots or commits."
        }
    }
    $syntax = $syntaxMatches[0].Groups
    $aggregate = $aggregateMatches[0].Groups
    $pythonListPath = Resolve-WeatherIntegrationPath -Path ([string]$syntax["python_list"].Value)
    $powerShellListPath = Resolve-WeatherIntegrationPath -Path ([string]$syntax["powershell_list"].Value)
    $inventoryPath = Resolve-WeatherIntegrationPath -Path ([string]$aggregate["inventory_path"].Value)
    foreach ($binding in @(
        [pscustomobject]@{ Path = $pythonListPath; Sha = [string]$syntax["python_sha"].Value; Count = [int]$syntax["python"].Value },
        [pscustomobject]@{ Path = $powerShellListPath; Sha = [string]$syntax["powershell_sha"].Value; Count = [int]$syntax["powershell"].Value },
        [pscustomobject]@{ Path = $inventoryPath; Sha = [string]$aggregate["inventory_sha"].Value; Count = [int]$aggregate["files"].Value }
    )) {
        $inventorySnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path $binding.Path -MaximumBytes 67108864 -ContentType Text
        $rows = @(([string]$inventorySnapshot.Text) -split "`r?`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($binding.Count -le 0 -or $rows.Count -ne $binding.Count -or
            [string]$inventorySnapshot.Sha256 -ne $binding.Sha) {
            throw "Suite inventory binding changed or is incomplete: $($binding.Path)"
        }
    }
    $junitRows = New-Object System.Collections.Generic.List[object]
    $sumTests = 0
    $sumFailures = 0
    $sumErrors = 0
    $sumSkipped = 0
    $sumDeselected = 0
    for ($index = 0; $index -lt $junitMatches.Count; $index++) {
        $groups = $junitMatches[$index].Groups
        $junitPath = Resolve-WeatherIntegrationPath -Path ([string]$groups["path"].Value)
        $tests = [int]$groups["tests"].Value
        $failures = [int]$groups["failures"].Value
        $errors = [int]$groups["errors"].Value
        $skipped = [int]$groups["skipped"].Value
        $deselected = [int]$groups["deselected"].Value
        $junitSummary = Get-WeatherIntegrationJUnitFileSummary -Path $junitPath
        if ([int]$groups["ordinal"].Value -ne ($index + 1) -or
            [int]$groups["chunks"].Value -ne $ExpectedChunkCount -or
            $tests -le 0 -or ($tests - $skipped) -le 0 -or
            $failures -ne 0 -or $errors -ne 0 -or $deselected -ne 0 -or
            [int]$junitSummary.tests -ne $tests -or
            [int]$junitSummary.failures -ne $failures -or
            [int]$junitSummary.errors -ne $errors -or
            [int]$junitSummary.skipped -ne $skipped -or
            [int]$junitSummary.deselected -ne $deselected -or
            [string]$junitSummary.sha256 -ne
                [string]$groups["sha"].Value) {
            throw "Suite JUnit binding does not prove one exact executed PASS chunk."
        }
        $sumTests += $tests
        $sumFailures += $failures
        $sumErrors += $errors
        $sumSkipped += $skipped
        $sumDeselected += $deselected
        $junitRows.Add([ordered]@{
            ordinal = $index + 1
            path = $junitPath
            sha256 = [string]$groups["sha"].Value
            tests = $tests
            failures = $failures
            errors = $errors
            skipped = $skipped
            deselected = $deselected
        })
    }
    if ([int]$syntax["python_exit"].Value -ne 0 -or
        [int]$syntax["powershell_errors"].Value -ne 0 -or
        [int]$aggregate["files"].Value -ne $ExpectedPlannedFiles -or
        [int]$aggregate["tests"].Value -ne $sumTests -or
        [int]$aggregate["failures"].Value -ne $sumFailures -or
        [int]$aggregate["errors"].Value -ne $sumErrors -or
        [int]$aggregate["skipped"].Value -ne $sumSkipped -or
        [int]$aggregate["deselected"].Value -ne $sumDeselected) {
        throw "Suite aggregate/syntax evidence does not match its bound inventories and JUnits."
    }
    $result = [ordered]@{
        planned_files = [int]$aggregate["files"].Value
        inventory_path = $inventoryPath
        inventory_sha256 = [string]$aggregate["inventory_sha"].Value
        tests = $sumTests
        failures = $sumFailures
        errors = $sumErrors
        skipped = $sumSkipped
        deselected = $sumDeselected
        python_files = [int]$syntax["python"].Value
        python_inventory_path = $pythonListPath
        python_inventory_sha256 = [string]$syntax["python_sha"].Value
        powershell_files = [int]$syntax["powershell"].Value
        powershell_inventory_path = $powerShellListPath
        powershell_inventory_sha256 = [string]$syntax["powershell_sha"].Value
        junit = @($junitRows)
    }
    if ($hasRuntimeFingerprint) {
        $result["python_environment_schema"] =
            [string]$pythonEnvironmentPre["schema"].Value
        $result["python_environment_sha256"] =
            [string]$pythonEnvironmentPre["sha"].Value
        $result["python_environment_distributions"] =
            [int]$pythonEnvironmentPre["distributions"].Value
        if ([string]$pythonEnvironmentPre["schema"].Value -ceq
                "python_environment_fingerprint_v2") {
            $result["python_environment_files"] =
                [int]$pythonEnvironmentPre["files"].Value
            $result["python_environment_bytes"] =
                [long]$pythonEnvironmentPre["bytes"].Value
        }
        $pythonPostSnapshot = $pythonEnvironmentSnapshots["post"]
        $result["python_executable_sha256"] =
            [string]$pythonPostSnapshot.Payload.executable_sha256
        $result["python_environment_pre_path"] = Resolve-WeatherIntegrationPath `
            -Path ([string]$pythonEnvironmentPre["path"].Value)
        $result["python_environment_post_path"] = Resolve-WeatherIntegrationPath `
            -Path ([string]$pythonEnvironmentPost["path"].Value)
        $result["python_environment_candidate_root"] = Resolve-WeatherIntegrationPath `
            -Path ([string]$pythonPostSnapshot.Payload.controls.candidate_root)
        $result["python_environment_production_root"] = Resolve-WeatherIntegrationPath `
            -Path ([string]$pythonPostSnapshot.Payload.controls.production_root)
        $result["toolchain_schema"] = [string]$toolchainPre["schema"].Value
        $result["toolchain_sha256"] = [string]$toolchainPre["sha"].Value
        $result["toolchain_git_sha256"] = [string]$toolchainPre["git_sha"].Value
        $result["toolchain_git_lfs_sha256"] =
            [string]$toolchainPre["git_lfs_sha"].Value
        $result["toolchain_powershell_sha256"] =
            [string]$toolchainPre["powershell_sha"].Value
        $result["toolchain_pre_path"] = Resolve-WeatherIntegrationPath `
            -Path ([string]$toolchainPre["path"].Value)
        $result["toolchain_post_path"] = Resolve-WeatherIntegrationPath `
            -Path ([string]$toolchainPost["path"].Value)
    }
    if ($hasTrackedFingerprint) {
        $result["tracked_worktree_schema"] = [string]$trackedPre["schema"].Value
        $result["tracked_worktree_sha256"] = [string]$trackedPre["sha"].Value
        $result["tracked_worktree_file_count"] = [int]$trackedPre["files"].Value
        $result["tracked_worktree_total_bytes"] = [long]$trackedPre["bytes"].Value
        $result["tracked_worktree_lfs_file_count"] =
            [int]$trackedPre["lfs_files"].Value
        $result["tracked_worktree_root"] = Resolve-WeatherIntegrationPath `
            -Path ([string]$trackedWorktreeSnapshots["pre"].Payload.root)
        $result["tracked_worktree_head"] =
            [string]$trackedWorktreeSnapshots["pre"].Payload.head
        $result["tracked_worktree_pre_path"] = Resolve-WeatherIntegrationPath `
            -Path ([string]$trackedPre["path"].Value)
        $result["tracked_worktree_post_path"] = Resolve-WeatherIntegrationPath `
            -Path ([string]$trackedPost["path"].Value)
    }
    return [pscustomobject]$result
}

function Assert-WeatherIntegrationRepeatedSuiteSummary {
    param(
        [Parameter(Mandatory = $true)][object]$QualificationSummary,
        [Parameter(Mandatory = $true)][object]$RepeatedSummary,
        [Parameter(Mandatory = $true)][string]$Label
    )

    foreach ($name in @(
        "planned_files", "inventory_sha256", "tests", "failures", "errors",
        "skipped", "deselected", "python_files", "python_inventory_sha256",
        "powershell_files", "powershell_inventory_sha256",
        "python_environment_schema", "python_environment_sha256",
        "python_environment_distributions", "python_environment_files",
        "python_environment_bytes", "python_executable_sha256",
        "python_environment_candidate_root",
        "python_environment_production_root",
        "toolchain_schema",
        "toolchain_sha256", "toolchain_git_sha256", "toolchain_git_lfs_sha256",
        "toolchain_powershell_sha256", "tracked_worktree_schema",
        "tracked_worktree_sha256", "tracked_worktree_file_count",
        "tracked_worktree_total_bytes", "tracked_worktree_lfs_file_count"
    )) {
        if ([string]$QualificationSummary.$name -cne [string]$RepeatedSummary.$name) {
            throw "$Label repeated run disagrees with pre-arming qualification field $name."
        }
    }
    if (@($QualificationSummary.junit).Count -ne @($RepeatedSummary.junit).Count) {
        throw "$Label repeated run has a different exact JUnit chunk count."
    }
    return $RepeatedSummary
}

function Assert-WeatherIntegrationExpectedSuiteInventories {
    param(
        [Parameter(Mandatory = $true)][object]$Summary,
        [Parameter(Mandatory = $true)][object]$Expected,
        [Parameter(Mandatory = $true)][string]$ExpectedRepoRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedWorktreeRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedTip,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$IncludeTestInventory
    )

    foreach ($binding in @(
        [pscustomobject]@{
            CountName = "python_files"
            HashName = "python_inventory_sha256"
            ExpectedCountName = "expected_python_file_count"
            ExpectedHashName = "expected_python_inventory_sha256"
        },
        [pscustomobject]@{
            CountName = "powershell_files"
            HashName = "powershell_inventory_sha256"
            ExpectedCountName = "expected_powershell_file_count"
            ExpectedHashName = "expected_powershell_inventory_sha256"
        }
    )) {
        if ([int]$Summary.($binding.CountName) -ne
                [int]$Expected.($binding.ExpectedCountName) -or
            [string]$Summary.($binding.HashName) -cne
                [string]$Expected.($binding.ExpectedHashName)) {
            throw "$Label does not match the creator-frozen $($binding.CountName) inventory."
        }
    }
    if ($IncludeTestInventory -and
        ([int]$Summary.planned_files -ne [int]$Expected.expected_test_file_count -or
         [string]$Summary.inventory_sha256 -cne
            [string]$Expected.expected_test_inventory_sha256)) {
        throw "$Label does not match the creator-frozen pytest inventory."
    }
    if ([string]$Summary.tracked_worktree_schema -cne
            [string]$Expected.expected_tracked_worktree_schema -or
        [string]$Summary.tracked_worktree_sha256 -cne
            [string]$Expected.expected_tracked_worktree_sha256 -or
        [int]$Summary.tracked_worktree_file_count -ne
            [int]$Expected.expected_tracked_worktree_file_count -or
        [long]$Summary.tracked_worktree_total_bytes -ne
            [long]$Expected.expected_tracked_worktree_total_bytes -or
        [int]$Summary.tracked_worktree_lfs_file_count -ne
            [int]$Expected.expected_tracked_worktree_lfs_file_count -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$Summary.tracked_worktree_root) `
            -Right $ExpectedWorktreeRoot) -or
        [string]$Summary.tracked_worktree_head -cne
            $ExpectedTip) {
        throw "$Label does not match the creator-frozen tracked working inputs."
    }
    if ([string]$Summary.python_environment_schema -cne
            [string]$Expected.expected_python_environment_schema -or
        [string]$Summary.python_environment_sha256 -cne
            [string]$Expected.expected_python_environment_sha256 -or
        [int]$Summary.python_environment_distributions -ne
            [int]$Expected.expected_python_environment_distributions -or
        [int]$Summary.python_environment_files -ne
            [int]$Expected.expected_python_environment_files -or
        [long]$Summary.python_environment_bytes -ne
            [long]$Expected.expected_python_environment_bytes -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$Summary.python_environment_candidate_root) `
            -Right $ExpectedWorktreeRoot) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$Summary.python_environment_production_root) `
            -Right $ExpectedRepoRoot)) {
        throw "$Label does not match the qualification-frozen Python environment."
    }
    if ([string]$Summary.toolchain_schema -cne
            [string]$Expected.expected_toolchain_schema -or
        [string]$Summary.toolchain_sha256 -cne
            [string]$Expected.expected_toolchain_sha256) {
        throw "$Label does not match the qualification-frozen integration toolchain."
    }
    return $Summary
}

function Read-WeatherIntegrationSharedJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 268435456)]
        [long]$MaximumBytes = 2097152
    )

    return (Read-WeatherIntegrationEvidenceSnapshot `
        -Path $Path -MaximumBytes $MaximumBytes -ContentType Json).Payload
}

function Assert-WeatherIntegrationJsonPayloadDepth {
    param(
        [AllowNull()][object]$Value,
        [ValidateRange(1, 100)][int]$MaximumDepth = 64,
        [int]$Depth = 0
    )

    if ($null -eq $Value -or $Value -is [string] -or
        $Value -is [char] -or $Value -is [bool] -or
        $Value -is [datetime] -or $Value -is [datetimeoffset] -or
        $Value -is [guid] -or $Value -is [timespan] -or
        $Value.GetType().IsPrimitive -or $Value -is [decimal] -or
        $Value.GetType().IsEnum) {
        return
    }
    if ($Depth -ge $MaximumDepth) {
        throw "Immutable JSON payload exceeds the supported depth of $MaximumDepth."
    }

    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($child in $Value.Values) {
            Assert-WeatherIntegrationJsonPayloadDepth `
                -Value $child -MaximumDepth $MaximumDepth -Depth ($Depth + 1)
        }
        return
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        foreach ($child in $Value) {
            Assert-WeatherIntegrationJsonPayloadDepth `
                -Value $child -MaximumDepth $MaximumDepth -Depth ($Depth + 1)
        }
        return
    }
    foreach ($property in @($Value.PSObject.Properties | Where-Object {
        $_.MemberType -in @("NoteProperty", "Property", "AliasProperty")
    })) {
        Assert-WeatherIntegrationJsonPayloadDepth `
            -Value $property.Value -MaximumDepth $MaximumDepth -Depth ($Depth + 1)
    }
}

function Write-WeatherIntegrationImmutableJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [object]$Payload
    )

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    if ([string]::IsNullOrWhiteSpace([IO.Path]::GetFileName($resolvedPath))) {
        throw "Immutable evidence path must name a file: $Path"
    }
    if (Test-Path -LiteralPath $resolvedPath) {
        throw "Immutable evidence already exists and will not be replaced: $resolvedPath"
    }

    $parent = [IO.Path]::GetDirectoryName($resolvedPath)
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "Evidence parent directory is missing: $parent"
    }
    $parentItem = Get-Item -LiteralPath $parent -Force -ErrorAction Stop
    if (-not $parentItem.PSIsContainer -or
        ($parentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$parentItem.FullName) -Right $parent)) {
        throw "Evidence parent must be an exact non-reparse directory: $parent"
    }

    # ConvertTo-Json otherwise warns and silently stringifies deeper values.
    # Reject an unsupported graph before any sibling temp is created.
    Assert-WeatherIntegrationJsonPayloadDepth -Value $Payload -MaximumDepth 64
    $json = $Payload | ConvertTo-Json -Depth 100 -ErrorAction Stop
    try { $null = $json | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "Immutable JSON serialization did not round-trip as JSON: $($_.Exception.Message)" }
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    [byte[]]$bytes = $encoding.GetBytes($json + [Environment]::NewLine)
    if ($bytes.Length -le 0 -or $bytes.Length -gt 268435456) {
        throw "Immutable JSON serialization is empty or exceeds the 256 MiB evidence bound."
    }
    $expectedHash = [Security.Cryptography.SHA256]::Create()
    try {
        $expectedSha256 = (([BitConverter]::ToString(
            $expectedHash.ComputeHash($bytes)
        )) -replace '-', '').ToLowerInvariant()
    }
    finally { $expectedHash.Dispose() }
    $temporaryPath = Join-Path $parent (
        ".{0}.{1}.tmp" -f [IO.Path]::GetFileName($resolvedPath),
            [guid]::NewGuid().ToString("N")
    )
    $temporaryStream = $null
    $temporaryCreated = $false
    $published = $false
    $primaryError = $null
    $cleanupErrors = New-Object System.Collections.Generic.List[string]
    try {
        $temporaryStream = [IO.File]::Open(
            $temporaryPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        $temporaryCreated = $true
        $temporaryStream.Write($bytes, 0, $bytes.Length)
        $temporaryStream.Flush($true)
        $temporaryStream.Dispose()
        $temporaryStream = $null
        $temporaryItem = Get-Item -LiteralPath $temporaryPath -Force -ErrorAction Stop
        if ($temporaryItem.PSIsContainer -or
            ($temporaryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$temporaryItem.FullName) -Right $temporaryPath)) {
            throw "Temporary evidence path is not an exact plain file: $temporaryPath"
        }
        # File.Move is one same-volume create-if-absent operation. It never
        # replaces an existing destination, including under concurrent claimers.
        [IO.File]::Move($temporaryPath, $resolvedPath)
        $published = $true
        $publishedItem = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction Stop
        if ($publishedItem.PSIsContainer -or
            ($publishedItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$publishedItem.FullName) -Right $resolvedPath)) {
            throw "Published immutable evidence is not an exact plain file: $resolvedPath"
        }
        $publishedSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path $resolvedPath -MaximumBytes 268435456 -ContentType Bytes
        if ([long]$publishedSnapshot.Length -ne [long]$bytes.Length -or
            [string]$publishedSnapshot.Sha256 -cne $expectedSha256) {
            throw "Published immutable evidence bytes do not match the in-memory serialization: $resolvedPath"
        }
    }
    catch {
        $primaryError = $_
    }
    finally {
        if ($null -ne $temporaryStream) {
            try { $temporaryStream.Dispose() }
            catch {
                $cleanupErrors.Add(
                    "temporary stream disposal failed: $($_.Exception.Message)"
                )
            }
        }
        if ($temporaryCreated -and -not $published) {
            try {
                if (-not (Test-Path -LiteralPath $temporaryPath)) {
                    throw "Temporary evidence disappeared before cleanup proof: $temporaryPath"
                }
                $cleanupItem = Get-Item -LiteralPath $temporaryPath -Force -ErrorAction Stop
                if ($cleanupItem.PSIsContainer -or
                    ($cleanupItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                    -not (Test-WeatherIntegrationPathEqual `
                        -Left ([string]$cleanupItem.FullName) -Right $temporaryPath)) {
                    throw "Temporary evidence cleanup refused a non-plain path: $temporaryPath"
                }
                Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction Stop
                if (Test-Path -LiteralPath $temporaryPath) {
                    throw "Temporary evidence cleanup was not proved: $temporaryPath"
                }
            }
            catch {
                $cleanupErrors.Add([string]$_.Exception.Message)
            }
        }
    }
    if ($null -ne $primaryError) {
        if ($cleanupErrors.Count -ne 0) {
            $cleanupMessage = $cleanupErrors -join "; "
            $primaryError.Exception.Data["immutable_json_cleanup_failure"] =
                $cleanupMessage
            $primaryError.ErrorDetails = [Management.Automation.ErrorDetails]::new(
                "$($primaryError.Exception.Message) Cleanup also failed: $cleanupMessage"
            )
        }
        throw $primaryError
    }
    if ($cleanupErrors.Count -ne 0) {
        throw "Immutable JSON cleanup failed: $($cleanupErrors -join '; ')"
    }
}

function Resolve-WeatherIntegrationPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
}

function Get-WeatherLegacyBootstrapTaskXmlSha256 {
    param([Parameter(Mandatory = $true)][string]$Xml)

    # Export-ScheduledTask adds Settings/Enabled after disable. Remove only
    # that task-level switch so the frozen XML identity survives retirement;
    # trigger-level Enabled values remain bound.
    $settingsEnabled = New-Object Text.RegularExpressions.Regex(
        '(<Settings>.*?)(^[ \t]*<Enabled>(?:true|false)</Enabled>\r?\n)(.*?</Settings>)',
        ([Text.RegularExpressions.RegexOptions]::Singleline -bor
            [Text.RegularExpressions.RegexOptions]::Multiline)
    )
    if ($Xml -notmatch '<Settings>') {
        throw "Legacy bootstrap task XML lacks its Settings block."
    }
    $canonicalXml = $settingsEnabled.Replace($Xml, '${1}${3}', 1)
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($canonicalXml)
        return (([BitConverter]::ToString($hash.ComputeHash($bytes))) -replace '-', '').ToLowerInvariant()
    }
    finally { $hash.Dispose() }
}

function Test-WeatherIntegrationPathEqual {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Left,
        [Parameter(Mandatory = $true)]
        [string]$Right
    )

    $leftPath = Resolve-WeatherIntegrationPath -Path $Left
    $rightPath = Resolve-WeatherIntegrationPath -Path $Right
    return [string]::Equals($leftPath, $rightPath, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-WeatherIntegrationNonReparseDirectoryChain {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$StopPath,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $fullPath = Resolve-WeatherIntegrationPath -Path $Path
    $fullStop = Resolve-WeatherIntegrationPath -Path $StopPath
    if (-not (Test-WeatherIntegrationPathEqual -Left $fullPath -Right $fullStop) -and
        -not $fullPath.StartsWith(
            $fullStop + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "$Label escapes its canonical root: $fullPath"
    }

    $chain = New-Object System.Collections.Generic.List[string]
    $chain.Add($fullStop)
    if (-not (Test-WeatherIntegrationPathEqual -Left $fullPath -Right $fullStop)) {
        $relative = $fullPath.Substring($fullStop.Length).TrimStart(
            [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
        )
        $cursor = $fullStop
        foreach ($segment in @($relative -split '[\\/]' | Where-Object { $_ })) {
            $cursor = Join-Path $cursor $segment
            $chain.Add((Resolve-WeatherIntegrationPath -Path $cursor))
        }
    }

    foreach ($candidatePath in $chain) {
        $candidate = Get-Item -LiteralPath $candidatePath -Force -ErrorAction Stop
        if (-not $candidate.PSIsContainer -or
            ($candidate.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$candidate.FullName) -Right $candidatePath)) {
            throw "$Label must use only exact non-reparse directory ancestors: $candidatePath"
        }
    }
    return $fullPath
}

function Assert-WeatherIntegrationCanonicalAttemptRoot {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$AttemptRoot,
        [Parameter(Mandatory = $true)][string]$AttemptId,
        [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
        [switch]$RequireAttemptRoot,
        [switch]$RequirePreparationRoot
    )

    $repoRoot = Resolve-WeatherIntegrationPath -Path $RepositoryRoot
    $expectedRoot = Resolve-WeatherIntegrationPath -Path (
        Join-Path $repoRoot (
            "data\integration_attempts\{0}\{1}" -f
                $SuiteAtLocal.ToString("yyyy-MM-dd"), $AttemptId
        )
    )
    if (-not (Test-WeatherIntegrationPathEqual -Left $AttemptRoot -Right $expectedRoot)) {
        throw "AttemptRoot must be the canonical dated repository evidence path: $expectedRoot"
    }

    $attemptParent = Resolve-WeatherIntegrationPath -Path (Split-Path -Parent $expectedRoot)
    Assert-WeatherIntegrationNonReparseDirectoryChain `
        -Path $attemptParent -StopPath $repoRoot `
        -Label "Integration-attempt evidence ancestor" | Out-Null
    if ($RequireAttemptRoot) {
        Assert-WeatherIntegrationNonReparseDirectoryChain `
            -Path $expectedRoot -StopPath $repoRoot `
            -Label "Integration-attempt evidence root" | Out-Null
    }
    if ($RequirePreparationRoot) {
        Assert-WeatherIntegrationNonReparseDirectoryChain `
            -Path ($expectedRoot + ".preparation") -StopPath $repoRoot `
            -Label "Integration-attempt preparation root" | Out-Null
    }
    return $expectedRoot
}

function Assert-WeatherIntegrationRuntimeEvidenceNamespace {
    param([Parameter(Mandatory = $true)][object]$AttemptContract)

    $manifest = $AttemptContract.Manifest
    if ([string]$manifest.schema -ne $script:WeatherIntegrationAttemptManifestSchema) {
        # Historical v1 manifests remain structurally readable and retain their
        # original path contract. New runtime-authorizing writers emit only v2.
        return [pscustomobject]@{ Required = $false; Legacy = $true }
    }
    $suiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$manifest.schedule.suite_at_local) `
        -Label "suite_at_local"
    $root = Assert-WeatherIntegrationCanonicalAttemptRoot `
        -RepositoryRoot ([string]$manifest.repo_root) `
        -AttemptRoot ([string]$AttemptContract.AttemptRoot) `
        -AttemptId ([string]$manifest.attempt_id) `
        -SuiteAtLocal $suiteAt `
        -RequireAttemptRoot `
        -RequirePreparationRoot
    return [pscustomobject]@{
        Required = $true
        Legacy = $false
        AttemptRoot = $root
        PreparationRoot = Resolve-WeatherIntegrationPath -Path ($root + ".preparation")
    }
}

function Assert-WeatherIntegrationPrearmingQualificationIntent {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][string]$AttemptRoot,
        [Parameter(Mandatory = $true)][string]$BoundedSuitePath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedBoundedSuiteSha256,
        [Parameter(Mandatory = $true)][bool]$RequireLiveSdkContract
    )

    Assert-WeatherIntegrationRequiredProperties `
        -Object $Intent -Names @("publication", "authorization") `
        -Label "Preparation intent authorization"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $Intent.publication -Names @("confirmation") `
        -Label "Preparation publication authorization"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $Intent.authorization `
        -Names @("scheduler_confirmation", "activation_confirmation") `
        -Label "Preparation Scheduler authorization"
    if ([string]$Intent.publication.confirmation -cne
            "AUTHORIZE_EXACT_NON_FORCE_TOPIC_PUBLICATION" -or
        [string]$Intent.authorization.scheduler_confirmation -cne
            "AUTHORIZE_DISABLED_INTEGRATION_TASK_REGISTRATION" -or
        [string]$Intent.authorization.activation_confirmation -cne
            "AUTHORIZE_EXACT_INTEGRATION_TASK_ACTIVATION") {
        throw "Preparation intent does not bind all exact case-sensitive mutation confirmations."
    }

    $qualificationProperty = $Intent.PSObject.Properties["qualification"]
    if ($null -eq $qualificationProperty -or $null -eq $qualificationProperty.Value) {
        throw "Preparation intent is missing its mandatory pre-arming qualification plan."
    }
    $qualification = $qualificationProperty.Value
    Assert-WeatherIntegrationRequiredProperties `
        -Object $qualification `
        -Names @(
            "required", "receipt_path", "integration_preflight_log_path",
            "full_suite_log_path", "bounded_suite_path", "bounded_suite_sha256",
            "require_live_sdk_contract", "rerun_at_suite_trigger",
            "planning_ceiling_seconds", "safety_margin_seconds",
            "launch_grace_seconds"
        ) `
        -Label "Pre-arming qualification plan"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $qualification `
        -Names @(
            "required", "require_live_sdk_contract", "rerun_at_suite_trigger"
        ) `
        -Label "Pre-arming qualification plan"
    if (-not [bool]$qualification.required -or
        -not [bool]$qualification.rerun_at_suite_trigger -or
        [int]$qualification.planning_ceiling_seconds -ne
            [int]$script:WeatherIntegrationPrearmingPlanningCeilingSeconds -or
        [int]$qualification.safety_margin_seconds -ne
            [int]$script:WeatherIntegrationPrearmingSafetyMarginSeconds -or
        [int]$qualification.launch_grace_seconds -ne
            [int]$script:WeatherIntegrationSchedulerLaunchGraceSeconds -or
        [bool]$qualification.require_live_sdk_contract -ne $RequireLiveSdkContract) {
        throw "Pre-arming qualification plan does not require both qualification and overnight revalidation."
    }

    $preparationRoot = Resolve-WeatherIntegrationPath -Path (
        (Resolve-WeatherIntegrationPath -Path $AttemptRoot) + ".preparation"
    )
    $expectedReceiptPath = Join-Path $preparationRoot "prearming-qualification-receipt.json"
    $expectedPreflightLogPath = Join-Path $preparationRoot "prearming-integration-preflight.log"
    $expectedFullSuiteLogPath = Join-Path $preparationRoot "prearming-full-suite.log"
    $resolvedBoundedSuitePath = Resolve-WeatherIntegrationPath -Path $BoundedSuitePath
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$qualification.receipt_path) -Right $expectedReceiptPath) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$qualification.integration_preflight_log_path) `
            -Right $expectedPreflightLogPath) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$qualification.full_suite_log_path) `
            -Right $expectedFullSuiteLogPath) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$qualification.bounded_suite_path) `
            -Right $resolvedBoundedSuitePath) -or
        [string]$qualification.bounded_suite_sha256 -ne
            $ExpectedBoundedSuiteSha256.ToLowerInvariant()) {
        throw "Pre-arming qualification plan does not bind its canonical receipt, logs, and bounded-suite implementation."
    }
    return [pscustomobject]@{
        ReceiptPath = Resolve-WeatherIntegrationPath -Path $expectedReceiptPath
        IntegrationPreflightLogPath = Resolve-WeatherIntegrationPath `
            -Path $expectedPreflightLogPath
        FullSuiteLogPath = Resolve-WeatherIntegrationPath -Path $expectedFullSuiteLogPath
        BoundedSuitePath = $resolvedBoundedSuitePath
        BoundedSuiteSha256 = $ExpectedBoundedSuiteSha256.ToLowerInvariant()
    }
}

function Assert-WeatherIntegrationPrearmingQualificationEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$PreparationIntentPath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedPreparationIntentSha256,
        [Parameter(Mandatory = $true)][string]$AttemptRoot,
        [Parameter(Mandatory = $true)][string]$AttemptId,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$WorktreeRoot,
        [Parameter(Mandatory = $true)][string]$BranchRef,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{40}$")]
        [string]$ExpectedTip,
        [Parameter(Mandatory = $true)][string]$BoundedSuitePath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedBoundedSuiteSha256,
        [Parameter(Mandatory = $true)][int]$ExpectedTestFileCount,
        [Parameter(Mandatory = $true)][int]$ExpectedChunkCount,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedTestInventorySha256,
        [Parameter(Mandatory = $true)][int]$ExpectedPythonFileCount,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedPythonInventorySha256,
        [Parameter(Mandatory = $true)][int]$ExpectedPowerShellFileCount,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedPowerShellInventorySha256,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedTrackedWorktreeSchema,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedTrackedWorktreeSha256,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 20000)][int]$ExpectedTrackedWorktreeFileCount,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, 2147483648)]
        [long]$ExpectedTrackedWorktreeTotalBytes,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, 20000)][int]$ExpectedTrackedWorktreeLfsFileCount,
        [Parameter(Mandatory = $true)][bool]$RequireLiveSdkContract,
        [ValidatePattern("^$|^[0-9a-fA-F]{64}$")]
        [string]$ExpectedReceiptSha256 = "",
        [switch]$RequireLiveWorktreeImport,
        [switch]$AllowMissing,
        [AllowNull()][object]$PreparationIntentSnapshot = $null,
        [AllowNull()][object]$ReceiptSnapshot = $null,
        [AllowNull()][System.Collections.IDictionary]$RunLogSnapshots = $null
    )

    $intentPath = Resolve-WeatherIntegrationPath -Path $PreparationIntentPath
    $intentSnapshot = if ($null -ne $PreparationIntentSnapshot) {
        $PreparationIntentSnapshot
    }
    else {
        Read-WeatherIntegrationEvidenceSnapshot `
            -Path $intentPath -MaximumBytes 65536 -ContentType Json
    }
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$intentSnapshot.Path) -Right $intentPath)) {
        throw "Retained pre-arming preparation-intent snapshot uses the wrong path."
    }
    if ([string]$intentSnapshot.Sha256 -ne
            $ExpectedPreparationIntentSha256.ToLowerInvariant()) {
        throw "Pre-arming qualification preparation-intent hash mismatch."
    }
    $intent = $intentSnapshot.Payload
    $plan = Assert-WeatherIntegrationPrearmingQualificationIntent `
        -Intent $intent `
        -AttemptRoot $AttemptRoot `
        -BoundedSuitePath $BoundedSuitePath `
        -ExpectedBoundedSuiteSha256 $ExpectedBoundedSuiteSha256 `
        -RequireLiveSdkContract $RequireLiveSdkContract
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent -Names @("schedule") `
        -Label "Pre-arming qualification preparation intent"
    $intentSchedule = Assert-WeatherIntegrationScheduleEvidence `
        -Schedule $intent.schedule -Label "Pre-arming qualification schedule"
    $intentSuiteAt = [datetime]$intentSchedule.SuiteAtLocal
    Assert-WeatherIntegrationCanonicalAttemptRoot `
        -RepositoryRoot $RepoRoot `
        -AttemptRoot $AttemptRoot `
        -AttemptId $AttemptId `
        -SuiteAtLocal $intentSuiteAt `
        -RequirePreparationRoot | Out-Null
    if ($null -eq $ReceiptSnapshot -and
        -not (Test-Path -LiteralPath $plan.ReceiptPath -PathType Leaf)) {
        if ($AllowMissing) {
            return [pscustomobject]@{
                Required = $true
                Present = $false
                Path = $plan.ReceiptPath
                Plan = $plan
            }
        }
        throw "Exact pre-arming qualification PASS receipt is missing: $($plan.ReceiptPath)"
    }
    $receiptSnapshot = if ($null -ne $ReceiptSnapshot) {
        $ReceiptSnapshot
    }
    else {
        Read-WeatherIntegrationEvidenceSnapshot `
            -Path $plan.ReceiptPath -MaximumBytes 65536 -ContentType Json
    }
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receiptSnapshot.Path) -Right $plan.ReceiptPath)) {
        throw "Retained pre-arming qualification-receipt snapshot uses the wrong path."
    }
    $receiptSha256 = [string]$receiptSnapshot.Sha256
    if (-not [string]::IsNullOrWhiteSpace($ExpectedReceiptSha256) -and
        $receiptSha256 -ne $ExpectedReceiptSha256.ToLowerInvariant()) {
        throw "Pre-arming qualification receipt hash does not match the manifest."
    }
    $receipt = $receiptSnapshot.Payload
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt `
        -Names @(
            "schema", "status", "attempt_id", "repo_root", "worktree_root",
            "branch_ref", "expected_tip", "started_at_local", "completed_at_local",
            "duration_seconds",
            "bounded_suite", "require_live_sdk_contract",
            "expected_test_file_count", "max_files_per_chunk",
            "expected_chunk_count", "expected_test_inventory_sha256",
            "expected_python_file_count", "expected_python_inventory_sha256",
            "expected_powershell_file_count",
            "expected_powershell_inventory_sha256",
            "expected_tracked_worktree_schema",
            "expected_tracked_worktree_sha256",
            "expected_tracked_worktree_file_count",
            "expected_tracked_worktree_total_bytes",
            "expected_tracked_worktree_lfs_file_count",
            "expected_python_environment_schema",
            "expected_python_environment_sha256",
            "expected_python_environment_distributions",
            "expected_python_environment_files",
            "expected_python_environment_bytes",
            "expected_toolchain_schema", "expected_toolchain_sha256",
            "runs", "feasibility", "safety"
        ) `
        -Label "Pre-arming qualification receipt"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt -Names @("require_live_sdk_contract") `
        -Label "Pre-arming qualification receipt"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.bounded_suite -Names @("path", "sha256") `
        -Label "Pre-arming qualification bounded suite"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.runs `
        -Names @("integration_preflight", "full_suite") `
        -Label "Pre-arming qualification runs"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.safety `
        -Names @(
            "authority", "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) `
        -Label "Pre-arming qualification safety boundary"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.feasibility `
        -Names @(
            "measured_duration_seconds", "planning_ceiling_seconds",
            "safety_margin_seconds", "required_runtime_seconds",
            "launch_grace_seconds", "required_schedule_seconds",
            "bounded_suite_max_runtime_seconds",
            "suite_wrapper_teardown_allowance_seconds",
            "suite_task_execution_time_limit_seconds",
            "suite_to_merge_seconds", "suite_to_hard_stop_seconds", "eligible"
        ) `
        -Label "Pre-arming qualification schedule feasibility"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt.feasibility -Names @("eligible") `
        -Label "Pre-arming qualification schedule feasibility"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt.safety `
        -Names @(
            "credential_value_access_authorized", "live_exchange_mutation_authorized"
        ) `
        -Label "Pre-arming qualification safety boundary"

    if ([string]$receipt.schema -ne
            $script:WeatherIntegrationAttemptPrearmingQualificationSchema -or
        [string]$receipt.status -ne "PASS" -or
        [string]$receipt.attempt_id -ne $AttemptId -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.repo_root) -Right $RepoRoot) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.worktree_root) -Right $WorktreeRoot) -or
        [string]$receipt.branch_ref -cne $BranchRef -or
        [string]$receipt.expected_tip -ne $ExpectedTip.ToLowerInvariant() -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.bounded_suite.path) -Right $plan.BoundedSuitePath) -or
        [string]$receipt.bounded_suite.sha256 -ne $plan.BoundedSuiteSha256 -or
        [bool]$receipt.require_live_sdk_contract -ne $RequireLiveSdkContract -or
        [int]$receipt.expected_test_file_count -ne $ExpectedTestFileCount -or
        [int]$receipt.max_files_per_chunk -ne 20 -or
        [int]$receipt.expected_chunk_count -ne $ExpectedChunkCount -or
        [string]$receipt.expected_test_inventory_sha256 -cne
            $ExpectedTestInventorySha256.ToLowerInvariant() -or
        [int]$receipt.expected_python_file_count -ne $ExpectedPythonFileCount -or
        [string]$receipt.expected_python_inventory_sha256 -cne
            $ExpectedPythonInventorySha256.ToLowerInvariant() -or
        [int]$receipt.expected_powershell_file_count -ne
            $ExpectedPowerShellFileCount -or
        [string]$receipt.expected_powershell_inventory_sha256 -cne
            $ExpectedPowerShellInventorySha256.ToLowerInvariant() -or
        [string]$receipt.expected_tracked_worktree_schema -cne
            $ExpectedTrackedWorktreeSchema -or
        [string]$receipt.expected_tracked_worktree_sha256 -cne
            $ExpectedTrackedWorktreeSha256.ToLowerInvariant() -or
        [int]$receipt.expected_tracked_worktree_file_count -ne
            $ExpectedTrackedWorktreeFileCount -or
        [long]$receipt.expected_tracked_worktree_total_bytes -ne
            $ExpectedTrackedWorktreeTotalBytes -or
        [int]$receipt.expected_tracked_worktree_lfs_file_count -ne
            $ExpectedTrackedWorktreeLfsFileCount -or
        [string]$receipt.expected_python_environment_schema -cne
            "python_environment_fingerprint_v2" -or
        [string]$receipt.expected_python_environment_sha256 -cnotmatch
            '^[0-9a-f]{64}$' -or
        [int]$receipt.expected_python_environment_distributions -lt 0 -or
        [int]$receipt.expected_python_environment_files -le 0 -or
        [int]$receipt.expected_python_environment_files -gt 50000 -or
        [long]$receipt.expected_python_environment_bytes -le 0 -or
        [long]$receipt.expected_python_environment_bytes -gt 2147483648 -or
        [string]$receipt.expected_toolchain_schema -cne
            "integration_toolchain_fingerprint_v1" -or
        [string]$receipt.expected_toolchain_sha256 -cnotmatch
            '^[0-9a-f]{64}$' -or
        [string]$receipt.safety.authority -ne
            "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "Pre-arming qualification receipt does not bind the exact prepared attempt."
    }

    $expectedRuns = [ordered]@{
        integration_preflight = [pscustomobject]@{
            LogPath = $plan.IntegrationPreflightLogPath
            Verdict = "VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge is not authorized"
        }
        full_suite = [pscustomobject]@{
            LogPath = $plan.FullSuiteLogPath
            Verdict = (
                "VERDICT: ALL CHUNKS PASSED ($ExpectedChunkCount/$ExpectedChunkCount); " +
                "exact tip eligible for separate reviewed merge"
            )
        }
    }
    $qualificationSummaries = @{}
    foreach ($mode in $expectedRuns.Keys) {
        $run = $receipt.runs.PSObject.Properties[[string]$mode].Value
        Assert-WeatherIntegrationRequiredProperties `
            -Object $run `
            -Names @(
                "mode", "log_path", "log_sha256", "exit_code", "verdict",
                "weather_import_path", "weather_import_sha256",
                "test_results", "evidence_validation_error",
                "started_at_local", "completed_at_local",
                "duration_seconds"
            ) `
            -Label "Pre-arming $mode run"
        $expectedRun = $expectedRuns[$mode]
        $logPath = Resolve-WeatherIntegrationPath -Path ([string]$expectedRun.LogPath)
        $logSnapshot = if ($null -ne $RunLogSnapshots -and
            $RunLogSnapshots.Contains([string]$mode)) {
            $RunLogSnapshots[[string]$mode]
        }
        else {
            Read-WeatherIntegrationEvidenceSnapshot `
                -Path $logPath -MaximumBytes 4194304 -ContentType Text
        }
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$logSnapshot.Path) -Right $logPath)) {
            throw "Retained pre-arming $mode log snapshot uses the wrong path."
        }
        $logText = [string]$logSnapshot.Text
        $verdictMatches = [regex]::Matches(
            $logText,
            '(?m)^.*?  (?<verdict>VERDICT: .+?)\r?$'
        )
        $importMatches = [regex]::Matches(
            $logText,
            '(?m)^.*?  weather_import=(?<path>.+?) weather_import_sha256=(?<sha>[0-9a-f]{64})\r?$'
        )
        $resolvedImportPath = Resolve-WeatherIntegrationPath `
            -Path ([string]$run.weather_import_path)
        $allowedImportPaths = @(
            Resolve-WeatherIntegrationPath -Path (
                Join-Path $WorktreeRoot "weather\__init__.py"
            )
            Resolve-WeatherIntegrationPath -Path (
                Join-Path $WorktreeRoot "src\weather\__init__.py"
            )
        )
        if ($verdictMatches.Count -ne 1 -or
            $importMatches.Count -ne 1 -or
            [string]$run.mode -cne [string]$mode -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$run.log_path) -Right $logPath) -or
            [string]$run.log_sha256 -ne [string]$logSnapshot.Sha256 -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left $resolvedImportPath `
                -Right ([string]$importMatches[0].Groups["path"].Value)) -or
            $allowedImportPaths.Where({
                Test-WeatherIntegrationPathEqual -Left $_ -Right $resolvedImportPath
            }).Count -ne 1 -or
            [string]$importMatches[0].Groups["sha"].Value -ne
                [string]$run.weather_import_sha256 -or
            [int]$run.exit_code -ne 0 -or
            $null -ne $run.evidence_validation_error -or
            [string]$run.verdict -cne [string]$expectedRun.Verdict -or
            [string]$verdictMatches[0].Groups["verdict"].Value -cne
                [string]$expectedRun.Verdict) {
            throw "Pre-arming $mode evidence does not prove its exact PASS verdict."
        }
        if ($RequireLiveWorktreeImport -and
            [string]$run.weather_import_sha256 -ne
                (Get-WeatherIntegrationFileSha256 -Path $resolvedImportPath)) {
            throw "Pre-arming $mode live worktree import changed or disappeared."
        }
        if ($mode -eq "full_suite") {
            Assert-WeatherIntegrationFullSuiteLogPlan `
                -Path $logPath `
                -ExpectedTestFileCount $ExpectedTestFileCount `
                -ExpectedMaxFilesPerChunk 20 `
                -ExpectedChunkCount $ExpectedChunkCount `
                -EvidenceSnapshot $logSnapshot | Out-Null
            $runExpectedChunks = $ExpectedChunkCount
            $runExpectedFiles = $ExpectedTestFileCount
        }
        else {
            # The bounded runner is the sole owner of the deterministic
            # integration-preflight inventory. Bind its count and chunking
            # from this same retained log snapshot instead of copying a
            # second count into orchestration code.
            $declaredPlan = Get-WeatherIntegrationSuiteLogDeclaredPlan `
                -Path $logPath -EvidenceSnapshot $logSnapshot
            if ([int]$declaredPlan.MaxFilesPerChunk -ne 20) {
                throw "Integration-preflight log changed its bounded chunk size."
            }
            $runExpectedChunks = [int]$declaredPlan.Chunks
            $runExpectedFiles = [int]$declaredPlan.Files
        }
        $logSummary = Get-WeatherIntegrationSuiteEvidenceSummary `
            -Path $logPath `
            -ExpectedChunkCount $runExpectedChunks `
            -ExpectedPlannedFiles $runExpectedFiles `
            -EvidenceSnapshot $logSnapshot `
            -RequireRuntimeFingerprint
        if (($run.test_results | ConvertTo-Json -Depth 20 -Compress) -cne
            ($logSummary | ConvertTo-Json -Depth 20 -Compress)) {
            throw "Pre-arming $mode receipt does not bind its exact syntax/inventory/JUnit evidence."
        }
        Assert-WeatherIntegrationExpectedSuiteInventories `
            -Summary $logSummary `
            -Expected $receipt `
            -ExpectedRepoRoot $RepoRoot `
            -ExpectedWorktreeRoot $WorktreeRoot `
            -ExpectedTip $ExpectedTip `
            -Label "Pre-arming $mode" `
            -IncludeTestInventory:($mode -eq "full_suite") | Out-Null
        $qualificationSummaries[[string]$mode] = $logSummary
        $runStarted = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
            -Value ([string]$run.started_at_local) -Label "pre-arming $mode started_at_local"
        $runCompleted = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
            -Value ([string]$run.completed_at_local) -Label "pre-arming $mode completed_at_local"
        if ($runCompleted -lt $runStarted) {
            throw "Pre-arming $mode completion precedes its start."
        }
        if ([double]$run.duration_seconds -lt 0 -or
            [math]::Abs(
                [double]$run.duration_seconds - ($runCompleted - $runStarted).TotalSeconds
            ) -gt 0.01) {
            throw "Pre-arming $mode measured duration disagrees with its timestamps."
        }
    }
    foreach ($name in @(
        "python_environment_schema", "python_environment_sha256",
        "python_environment_distributions", "python_environment_files",
        "python_environment_bytes", "toolchain_schema",
        "toolchain_sha256", "tracked_worktree_schema",
        "tracked_worktree_sha256", "tracked_worktree_file_count",
        "tracked_worktree_total_bytes", "tracked_worktree_lfs_file_count"
    )) {
        if ([string]$qualificationSummaries["integration_preflight"].$name -cne
                [string]$qualificationSummaries["full_suite"].$name) {
            throw "Pre-arming runs used different Python environment field $name."
        }
    }
    $qualificationStarted = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.started_at_local) `
        -Label "pre-arming qualification started_at_local"
    $qualificationCompleted = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.completed_at_local) `
        -Label "pre-arming qualification completed_at_local"
    $preflightCompleted = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.runs.integration_preflight.completed_at_local) `
        -Label "pre-arming integration preflight completion"
    $fullSuiteStarted = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.runs.full_suite.started_at_local) `
        -Label "pre-arming full suite start"
    $preflightStarted = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.runs.integration_preflight.started_at_local) `
        -Label "pre-arming integration preflight start"
    $fullSuiteCompleted = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.runs.full_suite.completed_at_local) `
        -Label "pre-arming full suite completion"
    if ($qualificationCompleted -lt $qualificationStarted -or
        $preflightStarted -lt $qualificationStarted -or
        $fullSuiteStarted -lt $preflightCompleted -or
        $fullSuiteCompleted -gt $qualificationCompleted) {
        throw "Pre-arming qualification run ordering is invalid."
    }
    if ([double]$receipt.duration_seconds -lt 0 -or
        [math]::Abs(
            [double]$receipt.duration_seconds -
                ($qualificationCompleted - $qualificationStarted).TotalSeconds
        ) -gt 0.01) {
        throw "Pre-arming qualification measured duration disagrees with its timestamps."
    }
    $validatedSchedule = Assert-WeatherIntegrationScheduleEvidence `
        -Schedule $intent.schedule -Label "Pre-arming qualification schedule"
    $suiteAt = [datetime]$validatedSchedule.SuiteAtLocal
    $mergeAt = [datetime]$validatedSchedule.MergeAtLocal
    $requiredRuntimeSeconds = [math]::Max(
        [int]$script:WeatherIntegrationPrearmingPlanningCeilingSeconds,
        [int][math]::Ceiling([double]$receipt.duration_seconds)
    ) + [int]$script:WeatherIntegrationPrearmingSafetyMarginSeconds
    $launchGraceSeconds = [int]$script:WeatherIntegrationSchedulerLaunchGraceSeconds
    $requiredScheduleSeconds = $requiredRuntimeSeconds + $launchGraceSeconds
    $suiteHardStop = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $suiteAt.Date.AddHours(9) -Label "pre-arming suite hard stop"
    $suiteToMergeSeconds = [int][math]::Floor(
        (Get-WeatherIntegrationLocalElapsedSeconds `
            -StartLocal $suiteAt -EndLocal $mergeAt `
            -StartLabel "pre-arming suite_at_local" `
            -EndLabel "pre-arming merge_at_local")
    )
    $suiteToHardStopSeconds = [int][math]::Floor(
        (Get-WeatherIntegrationLocalElapsedSeconds `
            -StartLocal $suiteAt -EndLocal $suiteHardStop `
            -StartLabel "pre-arming suite_at_local" `
            -EndLabel "pre-arming suite hard stop")
    )
    if (-not [bool]$receipt.feasibility.eligible -or
        [double]$receipt.feasibility.measured_duration_seconds -ne
            [double]$receipt.duration_seconds -or
        [int]$receipt.feasibility.planning_ceiling_seconds -ne
            [int]$script:WeatherIntegrationPrearmingPlanningCeilingSeconds -or
        [int]$receipt.feasibility.safety_margin_seconds -ne
            [int]$script:WeatherIntegrationPrearmingSafetyMarginSeconds -or
        [int]$receipt.feasibility.required_runtime_seconds -ne
            $requiredRuntimeSeconds -or
        [int]$receipt.feasibility.launch_grace_seconds -ne
            $launchGraceSeconds -or
        [int]$receipt.feasibility.required_schedule_seconds -ne
            $requiredScheduleSeconds -or
        [int]$receipt.feasibility.bounded_suite_max_runtime_seconds -ne
            [int]$script:WeatherIntegrationBoundedSuiteMaximumRuntimeSeconds -or
        [int]$receipt.feasibility.suite_wrapper_teardown_allowance_seconds -ne
            [int]$script:WeatherIntegrationSuiteWrapperTeardownAllowanceSeconds -or
        [int]$receipt.feasibility.suite_task_execution_time_limit_seconds -ne
            [int]$script:WeatherIntegrationSuiteTaskExecutionLimitSeconds -or
        [int]$receipt.feasibility.suite_task_execution_time_limit_seconds -ne
            ([int]$receipt.feasibility.bounded_suite_max_runtime_seconds +
             [int]$receipt.feasibility.suite_wrapper_teardown_allowance_seconds) -or
        [double]$receipt.duration_seconds -gt
            [double]$receipt.feasibility.bounded_suite_max_runtime_seconds -or
        [int]$receipt.feasibility.suite_to_merge_seconds -ne
            $suiteToMergeSeconds -or
        [int]$receipt.feasibility.suite_to_hard_stop_seconds -ne
            $suiteToHardStopSeconds -or
        $suiteToMergeSeconds -lt $requiredScheduleSeconds -or
        $suiteToHardStopSeconds -lt $requiredScheduleSeconds) {
        throw "Pre-arming qualification does not prove a feasible repeated overnight run."
    }
    return [pscustomobject]@{
        Required = $true
        Present = $true
        Path = $plan.ReceiptPath
        Sha256 = $receiptSha256
        Receipt = $receipt
        Plan = $plan
    }
}

function Get-WeatherIntegrationPreparationAuthorizationPayload {
    param(
        [Parameter(Mandatory = $true)][string]$AttemptId,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ExpectedTip,
        [Parameter(Mandatory = $true)][string]$PreparationIntentPath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$PreparationIntentSha256,
        [Parameter(Mandatory = $true)][string]$SuiteTaskName,
        [Parameter(Mandatory = $true)][string]$MergeTaskName
    )

    return [ordered]@{
        schema = $script:WeatherIntegrationAttemptPreparationAuthorizationSchema
        status = "PASS"
        attempt_id = $AttemptId
        manifest_path = Resolve-WeatherIntegrationPath -Path $ManifestPath
        expected_tip = $ExpectedTip.ToLowerInvariant()
        preparation_intent_path = Resolve-WeatherIntegrationPath -Path $PreparationIntentPath
        preparation_intent_sha256 = $PreparationIntentSha256.ToLowerInvariant()
        suite_task_name = $SuiteTaskName
        merge_task_name = $MergeTaskName
        authority = "PREPARATION_CHECKS_PASSED_TASK_EXECUTION_AUTHORIZED"
        credential_value_access_authorized = $false
        live_exchange_mutation_authorized = $false
    }
}

function Get-WeatherIntegrationImmutableJsonSha256 {
    param(
        [Parameter(Mandatory = $true)][object]$Payload
    )

    $json = $Payload | ConvertTo-Json -Depth 20
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $bytes = $encoding.GetBytes($json + [Environment]::NewLine)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-WeatherIntegrationPreparationAuthorizationPlan {
    param(
        [Parameter(Mandatory = $true)][string]$AttemptRoot,
        [Parameter(Mandatory = $true)][string]$AttemptId,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ExpectedTip,
        [Parameter(Mandatory = $true)][string]$PreparationIntentPath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$PreparationIntentSha256,
        [Parameter(Mandatory = $true)][string]$SuiteTaskName,
        [Parameter(Mandatory = $true)][string]$MergeTaskName
    )

    $authorizationPath = Resolve-WeatherIntegrationPath -Path (
        Join-Path ((Resolve-WeatherIntegrationPath -Path $AttemptRoot) + ".preparation") `
            "execution-authorization.json"
    )
    $payload = Get-WeatherIntegrationPreparationAuthorizationPayload `
        -AttemptId $AttemptId `
        -ManifestPath $ManifestPath `
        -ExpectedTip $ExpectedTip `
        -PreparationIntentPath $PreparationIntentPath `
        -PreparationIntentSha256 $PreparationIntentSha256 `
        -SuiteTaskName $SuiteTaskName `
        -MergeTaskName $MergeTaskName
    return [pscustomobject]@{
        Path = $authorizationPath
        Payload = $payload
        Sha256 = Get-WeatherIntegrationImmutableJsonSha256 -Payload $payload
    }
}

function Assert-WeatherIntegrationPreparationAuthorizationStructure {
    param([Parameter(Mandatory = $true)][object]$AttemptContract)

    $manifest = $AttemptContract.Manifest
    $preparationProperty = $manifest.authorization.PSObject.Properties["preparation"]
    if ($null -eq $preparationProperty) {
        # Historical v1 manifests frozen before composite preparation did not
        # contain this property at all. New creators must never emit null.
        return [pscustomobject]@{ Required = $false }
    }
    if ($null -eq $preparationProperty.Value) {
        throw "An explicit null preparation record is invalid; only property-absent historical manifests use the legacy contract."
    }
    $record = $preparationProperty.Value
    $manifestSchema = [string]$manifest.schema
    if ($manifestSchema -cnotin @(
            $script:WeatherIntegrationAttemptLegacyManifestSchema,
            $script:WeatherIntegrationAttemptManifestSchema
        )) {
        throw "Preparation authorization belongs to an unsupported manifest schema."
    }
    $recordProperties = @(
        "required", "execution_authorization_path",
        "execution_authorization_sha256", "preparation_intent_path",
        "preparation_intent_sha256"
    )
    if ($manifestSchema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
        $recordProperties += @(
            "prearming_qualification_path", "prearming_qualification_sha256",
            "creator_preflight_plan_path", "creator_preflight_plan_sha256"
        )
    }
    Assert-WeatherIntegrationRequiredProperties `
        -Object $record `
        -Names $recordProperties `
        -Label "Integration preparation execution authorization"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $record -Names @("required") `
        -Label "Integration preparation execution authorization"
    if (-not [bool]$record.required) {
        throw "A present preparation execution-authorization record must be required."
    }
    if ($manifestSchema -ceq $script:WeatherIntegrationAttemptManifestSchema -and
        ([string]$record.prearming_qualification_sha256 -notmatch '^[0-9a-f]{64}$' -or
         [string]$record.creator_preflight_plan_sha256 -notmatch '^[0-9a-f]{64}$')) {
        throw "Attempt manifest must bind exact creator-preflight and qualification receipt hashes."
    }

    $expectedIntentPath = Resolve-WeatherIntegrationPath -Path (
        Join-Path ($AttemptContract.AttemptRoot + ".preparation") "preparation-intent.json"
    )
    $plan = Get-WeatherIntegrationPreparationAuthorizationPlan `
        -AttemptRoot $AttemptContract.AttemptRoot `
        -AttemptId ([string]$manifest.attempt_id) `
        -ManifestPath $AttemptContract.ManifestPath `
        -ExpectedTip ([string]$manifest.expected_tip) `
        -PreparationIntentPath $expectedIntentPath `
        -PreparationIntentSha256 ([string]$record.preparation_intent_sha256) `
        -SuiteTaskName ([string]$manifest.schedule.suite_task_name) `
        -MergeTaskName ([string]$manifest.schedule.merge_task_name)
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$record.preparation_intent_path) -Right $expectedIntentPath) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$record.execution_authorization_path) -Right $plan.Path) -or
        [string]$record.execution_authorization_sha256 -ne $plan.Sha256) {
        throw "Attempt manifest does not bind the canonical deterministic preparation authorization."
    }
    $qualificationPath = $null
    $creatorPreflightPlanPath = $null
    if ($manifestSchema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
        $qualificationPath = Resolve-WeatherIntegrationPath -Path (
            Join-Path ($AttemptContract.AttemptRoot + ".preparation") `
                "prearming-qualification-receipt.json"
        )
        $creatorPreflightPlanPath = Resolve-WeatherIntegrationPath -Path (
            Join-Path ($AttemptContract.AttemptRoot + ".preparation") `
                "creator-preflight-plan.json"
        )
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$record.prearming_qualification_path) `
                -Right $qualificationPath) -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$record.creator_preflight_plan_path) `
                -Right $creatorPreflightPlanPath)) {
            throw "Attempt manifest does not bind canonical creator-preflight and qualification paths."
        }
    }
    return [pscustomobject]@{
        Required = $true
        Record = $record
        ManifestSchema = $manifestSchema
        ExpectedIntentPath = $expectedIntentPath
        Plan = $plan
        QualificationPath = $qualificationPath
        CreatorPreflightPlanPath = $creatorPreflightPlanPath
    }
}

function Assert-WeatherIntegrationPreparationExecutionAuthorization {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [switch]$AllowMissing,
        [switch]$RequireLiveQualificationInputs
    )

    $manifest = $AttemptContract.Manifest
    $structure = Assert-WeatherIntegrationPreparationAuthorizationStructure `
        -AttemptContract $AttemptContract
    if (-not [bool]$structure.Required) {
        return [pscustomobject]@{ Required = $false; Present = $false }
    }
    Assert-WeatherIntegrationRuntimeEvidenceNamespace `
        -AttemptContract $AttemptContract | Out-Null
    $record = $structure.Record
    $manifestSchema = [string]$structure.ManifestSchema
    $expectedIntentPath = [string]$structure.ExpectedIntentPath
    $plan = $structure.Plan
    $intentSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $expectedIntentPath -MaximumBytes 65536 -ContentType Json
    if ([string]$intentSnapshot.Sha256 -ne
            [string]$record.preparation_intent_sha256) {
        throw "Preparation intent changed after the attempt manifest was frozen."
    }
    $qualification = $null
    if ($manifestSchema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
        $creatorPreflightSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path ([string]$structure.CreatorPreflightPlanPath) `
            -MaximumBytes 65536 -ContentType Json
        if ([string]$creatorPreflightSnapshot.Sha256 -cne
                [string]$record.creator_preflight_plan_sha256) {
            throw "Creator preflight plan changed after the attempt manifest was frozen."
        }
        $qualification = Assert-WeatherIntegrationPrearmingQualificationEvidence `
            -PreparationIntentPath $expectedIntentPath `
            -ExpectedPreparationIntentSha256 ([string]$record.preparation_intent_sha256) `
            -AttemptRoot $AttemptContract.AttemptRoot `
            -AttemptId ([string]$manifest.attempt_id) `
            -RepoRoot ([string]$manifest.repo_root) `
            -WorktreeRoot ([string]$manifest.worktree_root) `
            -BranchRef ([string]$manifest.branch_ref) `
            -ExpectedTip ([string]$manifest.expected_tip) `
            -BoundedSuitePath ([string]$manifest.orchestration.bounded_suite.path) `
            -ExpectedBoundedSuiteSha256 (
                [string]$manifest.orchestration.bounded_suite.sha256
            ) `
            -ExpectedTestFileCount ([int]$manifest.suite.expected_test_file_count) `
            -ExpectedChunkCount ([int]$manifest.suite.expected_chunk_count) `
            -ExpectedTestInventorySha256 (
                [string]$manifest.suite.expected_test_inventory_sha256
            ) `
            -ExpectedPythonFileCount (
                [int]$manifest.suite.expected_python_file_count
            ) `
            -ExpectedPythonInventorySha256 (
                [string]$manifest.suite.expected_python_inventory_sha256
            ) `
            -ExpectedPowerShellFileCount (
                [int]$manifest.suite.expected_powershell_file_count
            ) `
            -ExpectedPowerShellInventorySha256 (
                [string]$manifest.suite.expected_powershell_inventory_sha256
            ) `
            -ExpectedTrackedWorktreeSchema (
                [string]$manifest.suite.expected_tracked_worktree_schema
            ) `
            -ExpectedTrackedWorktreeSha256 (
                [string]$manifest.suite.expected_tracked_worktree_sha256
            ) `
            -ExpectedTrackedWorktreeFileCount (
                [int]$manifest.suite.expected_tracked_worktree_file_count
            ) `
            -ExpectedTrackedWorktreeTotalBytes (
                [long]$manifest.suite.expected_tracked_worktree_total_bytes
            ) `
            -ExpectedTrackedWorktreeLfsFileCount (
                [int]$manifest.suite.expected_tracked_worktree_lfs_file_count
            ) `
            -RequireLiveSdkContract ([bool]$manifest.suite.require_live_sdk_contract) `
            -ExpectedReceiptSha256 ([string]$record.prearming_qualification_sha256) `
            -RequireLiveWorktreeImport:$RequireLiveQualificationInputs
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$record.prearming_qualification_path) `
                -Right ([string]$qualification.Path))) {
            throw "Attempt manifest does not bind the canonical pre-arming qualification receipt."
        }
        $qualifiedReserve = $qualification.Receipt.feasibility
        if ([double]$manifest.suite.prearming_measured_duration_seconds -ne
                [double]$qualifiedReserve.measured_duration_seconds -or
            [int]$manifest.suite.prearming_planning_ceiling_seconds -ne
                [int]$qualifiedReserve.planning_ceiling_seconds -or
            [int]$manifest.suite.prearming_safety_margin_seconds -ne
                [int]$qualifiedReserve.safety_margin_seconds -or
            [int]$manifest.suite.prearming_required_runtime_seconds -ne
                [int]$qualifiedReserve.required_runtime_seconds -or
            [int]$manifest.suite.prearming_launch_grace_seconds -ne
                [int]$qualifiedReserve.launch_grace_seconds -or
            [int]$manifest.suite.prearming_required_schedule_seconds -ne
                [int]$qualifiedReserve.required_schedule_seconds -or
            [int]$manifest.suite.bounded_suite_max_runtime_seconds -ne
                [int]$qualifiedReserve.bounded_suite_max_runtime_seconds -or
            [int]$manifest.suite.suite_wrapper_teardown_allowance_seconds -ne
                [int]$qualifiedReserve.suite_wrapper_teardown_allowance_seconds -or
            [int]$manifest.suite.suite_task_execution_time_limit_seconds -ne
                [int]$qualifiedReserve.suite_task_execution_time_limit_seconds -or
            [string]$manifest.suite.expected_python_environment_schema -cne
                [string]$qualification.Receipt.expected_python_environment_schema -or
            [string]$manifest.suite.expected_python_environment_sha256 -cne
                [string]$qualification.Receipt.expected_python_environment_sha256 -or
            [int]$manifest.suite.expected_python_environment_distributions -ne
                [int]$qualification.Receipt.expected_python_environment_distributions -or
            [int]$manifest.suite.expected_python_environment_files -ne
                [int]$qualification.Receipt.expected_python_environment_files -or
            [long]$manifest.suite.expected_python_environment_bytes -ne
                [long]$qualification.Receipt.expected_python_environment_bytes -or
            [string]$manifest.suite.expected_toolchain_schema -cne
                [string]$qualification.Receipt.expected_toolchain_schema -or
            [string]$manifest.suite.expected_toolchain_sha256 -cne
                [string]$qualification.Receipt.expected_toolchain_sha256) {
            throw "Attempt manifest runtime, environment, toolchain, or launch reserves do not match qualification."
        }
        if ($RequireLiveQualificationInputs) {
            Assert-WeatherIntegrationCurrentQualifiedRuntimeFingerprints `
                -Summary $qualification.Receipt.runs.full_suite.test_results `
                -Expected $manifest.suite `
                -Label "Current manifest-bound qualification runtime" | Out-Null
        }
    }
    if (-not (Test-Path -LiteralPath $plan.Path -PathType Leaf)) {
        if ($AllowMissing) {
            return [pscustomobject]@{
                Required = $true
                Present = $false
                Path = $plan.Path
                Sha256 = $plan.Sha256
                Payload = $plan.Payload
            }
        }
        throw "Exact preparation PASS authorization is missing: $($plan.Path)"
    }
    $authorizationSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $plan.Path -MaximumBytes 16384 -ContentType Json
    if ([string]$authorizationSnapshot.Sha256 -ne $plan.Sha256) {
        throw "Preparation PASS authorization hash does not match the manifest."
    }
    $payload = $authorizationSnapshot.Payload
    $expectedJson = $plan.Payload | ConvertTo-Json -Depth 20 -Compress
    $actualJson = $payload | ConvertTo-Json -Depth 20 -Compress
    if ($actualJson -cne $expectedJson) {
        throw "Preparation PASS authorization payload does not exactly match the manifest-bound plan."
    }
    return [pscustomobject]@{
        Required = $true
        Present = $true
        Path = $plan.Path
        Sha256 = $plan.Sha256
        Payload = $payload
        Qualification = $qualification
    }
}

function Assert-WeatherIntegrationRegistrationPreparationState {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract
    )

    # Registration is the disabled-staging step.  The manifest must already
    # bind the deterministic execution-authorization plan, but readiness has
    # not run yet and therefore the token must not exist.  Requiring the token
    # here creates an impossible registrar -> readiness dependency; accepting
    # a pre-existing token would let stale authority cross into a new staging
    # transaction.
    $authorization = Assert-WeatherIntegrationPreparationExecutionAuthorization `
        -AttemptContract $AttemptContract `
        -AllowMissing `
        -RequireLiveQualificationInputs
    if (-not [bool]$authorization.Required) {
        throw "New integration-attempt registration requires a manifest-bound composite preparation authorization plan."
    }
    if ([bool]$authorization.Present) {
        throw "Disabled integration-attempt registration must precede execution authorization creation."
    }
    return $authorization
}

function Assert-WeatherIntegrationActivationReceipt {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract
    )

    $manifest = $AttemptContract.Manifest
    $authorization = Assert-WeatherIntegrationPreparationExecutionAuthorization `
        -AttemptContract $AttemptContract
    if (-not [bool]$authorization.Required) {
        # Legacy attempts never used a separate activation transaction.
        return [pscustomobject]@{ Required = $false; Present = $false }
    }
    $preparationRoot = Resolve-WeatherIntegrationPath -Path (
        $AttemptContract.AttemptRoot + ".preparation"
    )
    $intentPath = Join-Path $preparationRoot "preparation-intent.json"
    $readinessReceiptPath = Join-Path $preparationRoot "readiness-receipt.json"
    $activationPath = Join-Path $preparationRoot "preparation-receipt.json"
    $activationSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $activationPath -MaximumBytes 65536 -ContentType Json
    $readinessSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $readinessReceiptPath -MaximumBytes 65536 -ContentType Json
    $intentSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $intentPath -MaximumBytes 65536 -ContentType Json
    $receipt = $activationSnapshot.Payload
    $receiptSha256 = [string]$activationSnapshot.Sha256
    $readinessReceiptSha256 = [string]$readinessSnapshot.Sha256
    $readinessReceipt = $readinessSnapshot.Payload
    $taskNames = @($receipt.tasks | ForEach-Object {
        [string]$_.task_name
    } | Sort-Object -Unique)
    $suiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$manifest.schedule.suite_at_local) -Label "suite_at_local"
    $mergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$manifest.schedule.merge_at_local) -Label "merge_at_local"
    $activatedAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.activated_at_local) `
        -Label "preparation activated_at_local"
    if ([string]$readinessReceipt.schema -ne
            "weather_integration_attempt_readiness_receipt_v1" -or
        [string]$readinessReceipt.status -ne "PASS" -or
        [string]$readinessReceipt.stage -ne "READY" -or
        [string]$readinessReceipt.attempt_id -ne [string]$manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$readinessReceipt.manifest_path) `
            -Right $AttemptContract.ManifestPath) -or
        [string]$readinessReceipt.manifest_sha256 -ne
            [string]$AttemptContract.ManifestSha256 -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$readinessReceipt.preparation_intent_path) `
            -Right $intentPath) -or
        [string]$readinessReceipt.preparation_intent_sha256 -ne
            [string]$intentSnapshot.Sha256 -or
        [string]$receipt.schema -ne "weather_integration_attempt_preparation_receipt_v1" -or
        [string]$receipt.status -ne "PASS" -or
        [string]$receipt.stage -ne "READY" -or
        [string]$receipt.attempt_id -ne [string]$manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256 -or
        [string]$receipt.branch_ref -cne [string]$manifest.branch_ref -or
        [string]$receipt.expected_tip -ne [string]$manifest.expected_tip -or
        [string]$receipt.origin_url -cne [string]$manifest.baseline.origin_url -or
        [string]$readinessReceipt.remote.origin_url -cne
            [string]$manifest.baseline.origin_url -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.preparation_intent_path) -Right $intentPath) -or
        [string]$receipt.preparation_intent_sha256 -ne
            [string]$intentSnapshot.Sha256 -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.readiness_receipt_path) `
            -Right $readinessReceiptPath) -or
        [string]$receipt.readiness_receipt_sha256 -ne $readinessReceiptSha256 -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.execution_authorization_path) `
            -Right ([string]$authorization.Path)) -or
        [string]$receipt.execution_authorization_sha256 -ne
            [string]$authorization.Sha256 -or
        $taskNames.Count -ne 2 -or
        $taskNames -cnotcontains [string]$manifest.schedule.suite_task_name -or
        $taskNames -cnotcontains [string]$manifest.schedule.merge_task_name -or
        @($receipt.tasks | Where-Object {
            $expectedAt = if ([string]$_.role -eq "suite") { $suiteAt }
                elseif ([string]$_.role -eq "merge") { $mergeAt }
                else { $null }
            $null -eq $expectedAt -or [string]$_.task_path -ne "\" -or
            [string]$_.state -ne "Ready" -or -not [bool]$_.enabled -or
            [datetime]$_.trigger_at_local -ne $expectedAt -or
            [datetime]$_.next_run_time -ne $expectedAt
        }).Count -ne 0 -or
        @($receipt.rollback_tasks).Count -ne 0 -or
        -not [string]::IsNullOrWhiteSpace([string]$receipt.failure) -or
        [string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "Activation receipt does not prove the exact post-authorization enabled task pair."
    }
    return [pscustomobject]@{
        Required = $true
        Present = $true
        Path = $activationPath
        Sha256 = $receiptSha256
        Receipt = $receipt
        Authorization = $authorization
    }
}

function ConvertTo-WeatherIntegrationScheduledTaskArgumentString {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Tokens
    )

    $encoded = foreach ($token in $Tokens) {
        $value = [string]$token
        if ($value.Contains('"')) {
            throw "Integration-attempt task action tokens may not contain a double quote: $value"
        }
        if ($value -match '\s') {
            if ($value.EndsWith('\')) {
                throw "A quoted integration-attempt task action token may not end in a backslash: $value"
            }
            '"{0}"' -f $value
        }
        elseif ($value.Length -eq 0) {
            '""'
        }
        else {
            $value
        }
    }
    return ($encoded -join " ")
}

function Get-WeatherIntegrationRegistrationIntentPath {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AttemptContract
    )

    $expectedPath = Join-Path (Resolve-WeatherIntegrationPath -Path $AttemptContract.AttemptRoot) "registration-intent.json"
    $pathProperty = $AttemptContract.Manifest.evidence.PSObject.Properties["registration_intent"]
    if ($null -ne $pathProperty -and
        -not [string]::IsNullOrWhiteSpace([string]$pathProperty.Value) -and
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$pathProperty.Value) -Right $expectedPath)) {
        throw "Attempt registration-intent path is not canonical. Expected $expectedPath"
    }
    return Resolve-WeatherIntegrationPath -Path $expectedPath
}

function ConvertTo-WeatherIntegrationCanonicalPrincipalSid {
    param(
        [Parameter(Mandatory = $true)][string]$UserId,
        [string]$Label = "Windows principal"
    )

    if ([string]::IsNullOrWhiteSpace($UserId) -or $UserId -ne $UserId.Trim()) {
        throw "$Label user id is empty or has surrounding whitespace."
    }
    try {
        $sid = if ($UserId -cmatch '^S-[0-9]+(?:-[0-9]+)+$') {
            [Security.Principal.SecurityIdentifier]::new($UserId)
        }
        else {
            ([Security.Principal.NTAccount]::new($UserId)).Translate(
                [Security.Principal.SecurityIdentifier]
            )
        }
    }
    catch {
        throw "$Label user id cannot be resolved to one Windows SID: $UserId"
    }
    $value = [string]$sid.Value
    if ($value -cnotmatch '^S-[0-9]+(?:-[0-9]+)+$') {
        throw "$Label resolved to an invalid Windows SID."
    }
    return $value
}

function Get-WeatherIntegrationCanonicalWindowsIdentity {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    try {
        if ($null -eq $identity -or $null -eq $identity.User) {
            throw "The current Windows identity has no user SID."
        }
        $sid = [string]$identity.User.Value
        $accountName = [string]$identity.Name
        $accountMatch = [regex]::Match(
            $accountName,
            '^(?<authority>[^\\\x00-\x1f]+)\\(?<name>[^\\\x00-\x1f]+)$',
            [Text.RegularExpressions.RegexOptions]::CultureInvariant
        )
        if ($sid -cnotmatch '^S-[0-9]+(?:-[0-9]+)+$' -or
            -not $accountMatch.Success -or $accountName -ne $accountName.Trim()) {
            throw "The current Windows identity is not one canonical authority-qualified account."
        }
        $translatedSid = ConvertTo-WeatherIntegrationCanonicalPrincipalSid `
            -UserId $accountName -Label "current Windows identity"
        if ($translatedSid -cne $sid) {
            throw "The current Windows identity name and SID disagree."
        }
        $machineName = [string][Environment]::MachineName
        $userDomainName = [string][Environment]::UserDomainName
        if ($machineName -cnotmatch '^[^\\\x00-\x1f]{1,255}$' -or
            $userDomainName -cnotmatch '^[^\\\x00-\x1f]{1,255}$') {
            throw "The current Windows machine/domain identity is empty or malformed."
        }
        return [pscustomobject][ordered]@{
            UserId = $accountName
            Sid = $sid
            AccountName = $accountName
            Authority = [string]$accountMatch.Groups["authority"].Value
            MachineName = $machineName
            UserDomainName = $userDomainName
        }
    }
    finally {
        if ($null -ne $identity) { $identity.Dispose() }
    }
}

function Assert-WeatherIntegrationCanonicalWindowsIdentityBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Principal,
        [string]$Label = "Windows principal binding",
        [switch]$RequireCurrentIdentity
    )

    Assert-WeatherIntegrationRequiredProperties `
        -Object $Principal `
        -Names @(
            "user_id", "sid", "account_name", "authority",
            "machine_name", "user_domain_name"
        ) `
        -Label $Label
    $userId = [string]$Principal.user_id
    $sid = [string]$Principal.sid
    $accountName = [string]$Principal.account_name
    $authority = [string]$Principal.authority
    $machineName = [string]$Principal.machine_name
    $userDomainName = [string]$Principal.user_domain_name
    $accountMatch = [regex]::Match(
        $accountName,
        '^(?<authority>[^\\\x00-\x1f]+)\\(?<name>[^\\\x00-\x1f]+)$',
        [Text.RegularExpressions.RegexOptions]::CultureInvariant
    )
    if ($userId -cne $accountName -or -not $accountMatch.Success -or
        $accountName -ne $accountName.Trim() -or
        [string]$accountMatch.Groups["authority"].Value -cne $authority -or
        $sid -cnotmatch '^S-[0-9]+(?:-[0-9]+)+$' -or
        $machineName -cnotmatch '^[^\\\x00-\x1f]{1,255}$' -or
        $userDomainName -cnotmatch '^[^\\\x00-\x1f]{1,255}$') {
        throw "$Label is not one canonical authority-qualified Windows identity."
    }
    $resolvedSid = ConvertTo-WeatherIntegrationCanonicalPrincipalSid `
        -UserId $accountName -Label $Label
    if ($resolvedSid -cne $sid) {
        throw "$Label account name and SID disagree."
    }
    if ($RequireCurrentIdentity) {
        $current = Get-WeatherIntegrationCanonicalWindowsIdentity
        foreach ($pair in @(
            [pscustomobject]@{ Current = "UserId"; Evidence = "user_id" },
            [pscustomobject]@{ Current = "Sid"; Evidence = "sid" },
            [pscustomobject]@{ Current = "AccountName"; Evidence = "account_name" },
            [pscustomobject]@{ Current = "Authority"; Evidence = "authority" },
            [pscustomobject]@{ Current = "MachineName"; Evidence = "machine_name" },
            [pscustomobject]@{ Current = "UserDomainName"; Evidence = "user_domain_name" }
        )) {
            if (-not [string]::Equals(
                    [string]$current.($pair.Current),
                    [string]$Principal.($pair.Evidence),
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                throw "$Label does not identify the current Windows principal at $($pair.Evidence)."
            }
        }
    }
    return [pscustomobject]@{
        UserId = $userId
        Sid = $sid
        AccountName = $accountName
        Authority = $authority
        MachineName = $machineName
        UserDomainName = $userDomainName
    }
}

function Get-WeatherIntegrationExpectedTaskBinding {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][ValidateSet("suite", "merge")][string]$Role,
        [Parameter(Mandatory = $true)][string]$UserId,
        [string]$BindingContract = $script:WeatherIntegrationAttemptTaskBindingContract,
        [string]$PowerShellExecutable = (Join-Path $PSHOME "powershell.exe")
    )

    if ([string]::IsNullOrWhiteSpace($UserId)) {
        throw "Integration-attempt task binding requires a non-empty principal user id."
    }
    if ($BindingContract -notin @(
            $script:WeatherIntegrationAttemptTaskBindingContract,
            $script:WeatherIntegrationAttemptLegacyTaskBindingContract
        )) {
        throw "Integration-attempt task binding contract is unsupported: $BindingContract"
    }
    $manifest = $AttemptContract.Manifest
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
    if ($Role -eq "suite") {
        $taskName = [string]$manifest.schedule.suite_task_name
        $atLocal = ConvertFrom-WeatherIntegrationLocalTimestamp `
            -Value ([string]$manifest.schedule.suite_at_local) `
            -Label "suite_at_local"
        $scriptPath = Join-Path $repoRoot "scripts\ops\integration_attempt_suite.ps1"
        $scriptRecord = $manifest.orchestration.attempt_suite
        $executionTimeLimit = if ([string]$manifest.schema -ceq
                $script:WeatherIntegrationAttemptManifestSchema) {
            "PT1H35M"
        }
        else {
            # Historical task evidence retains its original structural setting.
            "PT8H"
        }
        $description = "Immutable integration attempt $($manifest.attempt_id): preflight and full suite"
    }
    else {
        $taskName = [string]$manifest.schedule.merge_task_name
        $atLocal = ConvertFrom-WeatherIntegrationLocalTimestamp `
            -Value ([string]$manifest.schedule.merge_at_local) `
            -Label "merge_at_local"
        $scriptPath = Join-Path $repoRoot "scripts\ops\integration_attempt_merge.ps1"
        $scriptRecord = $manifest.orchestration.attempt_merge
        $executionTimeLimit = "PT4H"
        $description = "Immutable integration attempt $($manifest.attempt_id): guarded merge"
    }
    if ($null -eq $scriptRecord -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$scriptRecord.path) -Right $scriptPath) -or
        [string]$scriptRecord.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Attempt manifest is missing the canonical $Role task script binding."
    }

    $tokens = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $scriptPath,
        "-ManifestPath", $AttemptContract.ManifestPath,
        "-ExpectedManifestSha256", $AttemptContract.ManifestSha256
    )
    return [pscustomobject][ordered]@{
        task_name = $taskName
        task_path = "\"
        description = $description
        action_id = ""
        executable = Resolve-WeatherIntegrationPath -Path $PowerShellExecutable
        arguments = ConvertTo-WeatherIntegrationScheduledTaskArgumentString -Tokens $tokens
        working_directory = $repoRoot
        script_sha256 = [string]$scriptRecord.sha256
        trigger = [pscustomobject][ordered]@{
            type = "Once"
            id = ""
            at_local = $atLocal.ToString("o")
            enabled = $true
            end_boundary = ""
            random_delay = ""
            execution_time_limit = ""
            repetition_interval = ""
            repetition_duration = ""
            repetition_stop_at_duration_end = $false
        }
        settings = [pscustomobject][ordered]@{
            multiple_instances = "IgnoreNew"
            compatibility = "Win7"
            # These immutable one-shots may run only from their exact frozen
            # Scheduler trigger.  A later manual Start-ScheduledTask must not
            # resurrect a missed or closed attempt.
            allow_demand_start = (
                $BindingContract -eq
                    $script:WeatherIntegrationAttemptLegacyTaskBindingContract
            )
            allow_hard_terminate = $true
            delete_expired_task_after = ""
            execution_time_limit = $executionTimeLimit
            hidden = $false
            priority = 7
            restart_count = 0
            restart_interval = ""
            wake_to_run = $true
            start_when_available = $false
            allow_start_if_on_batteries = $true
            stop_if_going_on_batteries = $false
            run_only_if_idle = $false
            run_only_if_network_available = $false
            disallow_start_on_remote_app_session = $false
            use_unified_scheduling_engine = $true
            volatile = $false
            maintenance_settings = ""
            idle_duration = "PT10M"
            idle_restart = $false
            idle_stop_on_end = $true
            idle_wait_timeout = "PT1H"
            network_id = ""
            network_name = ""
        }
    }
}

function Assert-WeatherIntegrationRequiredProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string[]]$Names,
        [Parameter(Mandatory = $true)][string]$Label
    )

    foreach ($name in $Names) {
        if ($null -eq $Object.PSObject.Properties[$name]) {
            throw "$Label is missing required property: $name"
        }
    }
}

function Assert-WeatherIntegrationBooleanProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string[]]$Names,
        [Parameter(Mandatory = $true)][string]$Label
    )

    foreach ($name in $Names) {
        $property = $Object.PSObject.Properties[$name]
        if ($null -eq $property -or $property.Value -isnot [bool]) {
            throw "$Label property must be a JSON boolean: $name"
        }
    }
}

function Assert-WeatherIntegrationTaskBindingRecord {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][ValidateSet("suite", "merge")][string]$Role,
        [Parameter(Mandatory = $true)][object]$Record,
        [Parameter(Mandatory = $true)][string]$UserId,
        [string]$BindingContract = $script:WeatherIntegrationAttemptTaskBindingContract
    )

    Assert-WeatherIntegrationRequiredProperties `
        -Object $Record `
        -Names @("task_name", "task_path", "description", "action_id", "executable", "arguments", "working_directory", "script_sha256", "trigger", "settings") `
        -Label "$Role task binding"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $Record.trigger `
        -Names @("type", "id", "at_local", "enabled", "end_boundary", "random_delay", "execution_time_limit", "repetition_interval", "repetition_duration", "repetition_stop_at_duration_end") `
        -Label "$Role trigger binding"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $Record.settings `
        -Names @("multiple_instances", "compatibility", "allow_demand_start", "allow_hard_terminate", "delete_expired_task_after", "execution_time_limit", "hidden", "priority", "restart_count", "restart_interval", "wake_to_run", "start_when_available", "allow_start_if_on_batteries", "stop_if_going_on_batteries", "run_only_if_idle", "run_only_if_network_available", "disallow_start_on_remote_app_session", "use_unified_scheduling_engine", "volatile", "maintenance_settings", "idle_duration", "idle_restart", "idle_stop_on_end", "idle_wait_timeout", "network_id", "network_name") `
        -Label "$Role settings binding"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $Record.trigger `
        -Names @("enabled", "repetition_stop_at_duration_end") `
        -Label "$Role trigger binding"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $Record.settings `
        -Names @("allow_demand_start", "allow_hard_terminate", "hidden", "wake_to_run", "start_when_available", "allow_start_if_on_batteries", "stop_if_going_on_batteries", "run_only_if_idle", "run_only_if_network_available", "disallow_start_on_remote_app_session", "use_unified_scheduling_engine", "volatile", "idle_restart", "idle_stop_on_end") `
        -Label "$Role settings binding"
    $expected = Get-WeatherIntegrationExpectedTaskBinding `
        -AttemptContract $AttemptContract `
        -Role $Role `
        -UserId $UserId `
        -BindingContract $BindingContract
    if ([string]$Record.task_name -ne [string]$expected.task_name -or
        [string]$Record.task_path -ne [string]$expected.task_path -or
        [string]$Record.description -ne [string]$expected.description -or
        -not [string]::IsNullOrEmpty([string]$Record.action_id) -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$Record.executable) -Right ([string]$expected.executable)) -or
        [string]$Record.arguments -ne [string]$expected.arguments -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$Record.working_directory) -Right ([string]$expected.working_directory)) -or
        [string]$Record.script_sha256 -ne [string]$expected.script_sha256) {
        throw "$Role registration evidence does not bind the exact task identity and action."
    }
    if ([string]$Record.trigger.type -ne "Once" -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.id) -or
        [string]$Record.trigger.at_local -ne [string]$expected.trigger.at_local -or
        -not [bool]$Record.trigger.enabled -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.end_boundary) -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.random_delay) -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.execution_time_limit) -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.repetition_interval) -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.repetition_duration) -or
        [bool]$Record.trigger.repetition_stop_at_duration_end) {
        throw "$Role registration evidence does not bind the exact one-shot trigger."
    }
    if ([string]$Record.settings.multiple_instances -ne "IgnoreNew" -or
        [string]$Record.settings.compatibility -ne "Win7" -or
        [bool]$Record.settings.allow_demand_start -ne
            [bool]$expected.settings.allow_demand_start -or
        -not [bool]$Record.settings.allow_hard_terminate -or
        -not [string]::IsNullOrEmpty([string]$Record.settings.delete_expired_task_after) -or
        [string]$Record.settings.execution_time_limit -ne [string]$expected.settings.execution_time_limit -or
        [bool]$Record.settings.hidden -or
        [int]$Record.settings.priority -ne 7 -or
        [int]$Record.settings.restart_count -ne 0 -or
        -not [string]::IsNullOrEmpty([string]$Record.settings.restart_interval) -or
        -not [bool]$Record.settings.wake_to_run -or
        [bool]$Record.settings.start_when_available -or
        -not [bool]$Record.settings.allow_start_if_on_batteries -or
        [bool]$Record.settings.stop_if_going_on_batteries -or
        [bool]$Record.settings.run_only_if_idle -or
        [bool]$Record.settings.run_only_if_network_available -or
        [bool]$Record.settings.disallow_start_on_remote_app_session -or
        -not [bool]$Record.settings.use_unified_scheduling_engine -or
        [bool]$Record.settings.volatile -or
        -not [string]::IsNullOrEmpty([string]$Record.settings.maintenance_settings) -or
        [string]$Record.settings.idle_duration -ne "PT10M" -or
        [bool]$Record.settings.idle_restart -or
        -not [bool]$Record.settings.idle_stop_on_end -or
        [string]$Record.settings.idle_wait_timeout -ne "PT1H" -or
        -not [string]::IsNullOrEmpty([string]$Record.settings.network_id) -or
        -not [string]::IsNullOrEmpty([string]$Record.settings.network_name)) {
        throw "$Role registration evidence does not bind the required fail-closed task settings."
    }
    return $expected
}

function Assert-WeatherIntegrationRegistrationIntent {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [string]$ExpectedSha256 = ""
    )

    $intentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $AttemptContract
    $intentSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $intentPath -MaximumBytes 1048576 -ContentType Json
    $actualSha256 = [string]$intentSnapshot.Sha256
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and
        ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$' -or
            $actualSha256 -ne $ExpectedSha256.ToLowerInvariant())) {
        throw "Registration intent hash mismatch. Expected $ExpectedSha256; got $actualSha256"
    }
    $intent = $intentSnapshot.Payload
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent `
        -Names @("schema", "status", "binding_contract", "attempt_id", "intent_path", "manifest_path", "manifest_sha256", "prepared_at_local", "principal", "suite", "merge", "safety") `
        -Label "Registration intent"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent.principal `
        -Names @("user_id", "logon_type", "run_level", "id", "display_name", "group_id", "process_token_sid_type", "required_privileges") `
        -Label "Registration intent principal"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent.safety `
        -Names @("authority", "credential_value_access_authorized", "live_exchange_mutation_authorized") `
        -Label "Registration intent safety boundary"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $intent.safety `
        -Names @("credential_value_access_authorized", "live_exchange_mutation_authorized") `
        -Label "Registration intent safety boundary"
    $currentContract = (
        [string]$intent.schema -eq
            $script:WeatherIntegrationAttemptRegistrationIntentSchema -and
        [string]$intent.binding_contract -eq
            $script:WeatherIntegrationAttemptTaskBindingContract
    )
    $legacyContract = (
        [string]$intent.schema -eq
            $script:WeatherIntegrationAttemptLegacyRegistrationIntentSchema -and
        [string]$intent.binding_contract -eq
            $script:WeatherIntegrationAttemptLegacyTaskBindingContract
    )
    if (-not ($currentContract -or $legacyContract) -or
        [string]$intent.status -ne "PREPARED" -or
        [string]$intent.attempt_id -ne [string]$AttemptContract.Manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$intent.intent_path) -Right $intentPath) -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$intent.manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$intent.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256) {
        throw "Registration intent does not bind this exact immutable attempt."
    }
    if ($currentContract) {
        Assert-WeatherIntegrationCanonicalWindowsIdentityBinding `
            -Principal $intent.principal `
            -Label "Registration intent principal" | Out-Null
    }
    if ([string]::IsNullOrWhiteSpace([string]$intent.principal.user_id) -or
        [string]$intent.principal.logon_type -ne "S4U" -or
        [string]$intent.principal.run_level -ne "Limited" -or
        [string]$intent.principal.id -ne "Author" -or
        -not [string]::IsNullOrEmpty([string]$intent.principal.display_name) -or
        -not [string]::IsNullOrEmpty([string]$intent.principal.group_id) -or
        [string]$intent.principal.process_token_sid_type -ne "Default" -or
        @($intent.principal.required_privileges).Count -ne 0) {
        throw "Registration intent does not bind the required S4U/Limited principal."
    }
    $preparedAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$intent.prepared_at_local) `
        -Label "registration intent prepared_at_local"
    Assert-WeatherIntegrationTaskBindingRecord `
        -AttemptContract $AttemptContract `
        -Role "suite" `
        -Record $intent.suite `
        -UserId ([string]$intent.principal.user_id) `
        -BindingContract ([string]$intent.binding_contract) | Out-Null
    Assert-WeatherIntegrationTaskBindingRecord `
        -AttemptContract $AttemptContract `
        -Role "merge" `
        -Record $intent.merge `
        -UserId ([string]$intent.principal.user_id) `
        -BindingContract ([string]$intent.binding_contract) | Out-Null
    if ([string]$intent.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$intent.safety.credential_value_access_authorized -or
        [bool]$intent.safety.live_exchange_mutation_authorized) {
        throw "Registration intent violates the attempt safety boundary."
    }
    return [pscustomobject]@{
        Intent = $intent
        IntentPath = $intentPath
        IntentSha256 = $actualSha256
    }
}

function Assert-WeatherIntegrationRegistrationReceipt {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [switch]$RequirePass
    )

    $receiptPath = Resolve-WeatherIntegrationPath -Path ([string]$AttemptContract.Manifest.evidence.registration_receipt)
    $receiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $receiptPath -MaximumBytes 1048576 -ContentType Json
    $receipt = $receiptSnapshot.Payload
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt `
        -Names @("schema", "status", "binding_contract", "attempt_id", "manifest_path", "manifest_sha256", "registration_intent_path", "registration_intent_sha256", "registered_at_local", "principal", "suite", "merge", "downstream_tasks_created", "safety") `
        -Label "Registration receipt"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.principal `
        -Names @("user_id", "logon_type", "run_level", "id", "display_name", "group_id", "process_token_sid_type", "required_privileges") `
        -Label "Registration receipt principal"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.safety `
        -Names @("authority", "credential_value_access_authorized", "live_exchange_mutation_authorized") `
        -Label "Registration receipt safety boundary"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt `
        -Names @("downstream_tasks_created") `
        -Label "Registration receipt"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt.safety `
        -Names @("credential_value_access_authorized", "live_exchange_mutation_authorized") `
        -Label "Registration receipt safety boundary"
    $currentContract = (
        [string]$receipt.schema -eq
            $script:WeatherIntegrationAttemptRegistrationReceiptSchema -and
        [string]$receipt.binding_contract -eq
            $script:WeatherIntegrationAttemptTaskBindingContract
    )
    $legacyContract = (
        [string]$receipt.schema -eq
            $script:WeatherIntegrationAttemptLegacyRegistrationReceiptSchema -and
        [string]$receipt.binding_contract -eq
            $script:WeatherIntegrationAttemptLegacyTaskBindingContract
    )
    if (-not ($currentContract -or $legacyContract) -or
        [string]$receipt.attempt_id -ne [string]$AttemptContract.Manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256) {
        throw "Registration receipt does not bind the exact task contract for this attempt."
    }
    if ($currentContract) {
        Assert-WeatherIntegrationCanonicalWindowsIdentityBinding `
            -Principal $receipt.principal `
            -Label "Registration receipt principal" | Out-Null
    }
    if ($RequirePass -and [string]$receipt.status -ne "PASS") {
        throw "Integration-attempt runtime requires an immutable PASS registration receipt."
    }
    if ([string]$receipt.status -notin @("PASS", "FAIL")) {
        throw "Registration receipt status is unsupported: $($receipt.status)"
    }
    $registeredAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.registered_at_local) `
        -Label "registration receipt registered_at_local"
    if ([bool]$receipt.downstream_tasks_created -or
        [string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "Registration receipt violates the attempt safety boundary."
    }
    $intentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $AttemptContract
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.registration_intent_path) -Right $intentPath)) {
        throw "Registration receipt does not bind the canonical pre-registration intent."
    }
    if ([string]$receipt.registration_intent_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Registration receipt has an invalid pre-registration intent hash."
    }
    $intentContract = Assert-WeatherIntegrationRegistrationIntent `
        -AttemptContract $AttemptContract `
        -ExpectedSha256 ([string]$receipt.registration_intent_sha256)
    if ([string]$receipt.binding_contract -ne
        [string]$intentContract.Intent.binding_contract) {
        throw "Registration receipt and intent use different task binding contracts."
    }
    $preparedAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$intentContract.Intent.prepared_at_local) `
        -Label "registration intent prepared_at_local"
    if ($registeredAt -lt $preparedAt) {
        throw "Registration receipt predates its immutable pre-registration intent."
    }
    if ([string]$receipt.principal.user_id -ne [string]$intentContract.Intent.principal.user_id -or
        [string]$receipt.principal.logon_type -ne "S4U" -or
        [string]$receipt.principal.run_level -ne "Limited" -or
        [string]$receipt.principal.id -ne "Author" -or
        -not [string]::IsNullOrEmpty([string]$receipt.principal.display_name) -or
        -not [string]::IsNullOrEmpty([string]$receipt.principal.group_id) -or
        [string]$receipt.principal.process_token_sid_type -ne "Default" -or
        @($receipt.principal.required_privileges).Count -ne 0) {
        throw "Registration receipt principal disagrees with its immutable intent."
    }
    if ($currentContract) {
        foreach ($name in @(
            "sid", "account_name", "authority", "machine_name",
            "user_domain_name"
        )) {
            if (-not [string]::Equals(
                    [string]$receipt.principal.$name,
                    [string]$intentContract.Intent.principal.$name,
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                throw "Registration receipt principal identity disagrees with its immutable intent at $name."
            }
        }
    }
    foreach ($role in @("suite", "merge")) {
        $record = $receipt.PSObject.Properties[$role].Value
        Assert-WeatherIntegrationRequiredProperties `
            -Object $record `
            -Names @("registered", "trigger_at_local") `
            -Label "$role registration receipt"
        Assert-WeatherIntegrationBooleanProperties `
            -Object $record `
            -Names @("registered") `
            -Label "$role registration receipt"
        Assert-WeatherIntegrationTaskBindingRecord `
            -AttemptContract $AttemptContract `
            -Role $role `
            -Record $record `
            -UserId ([string]$receipt.principal.user_id) `
            -BindingContract ([string]$receipt.binding_contract) | Out-Null
        $intentRecord = $intentContract.Intent.PSObject.Properties[$role].Value
        if ([string]$record.arguments -ne [string]$intentRecord.arguments -or
            [string]$record.trigger_at_local -ne [string]$intentRecord.trigger.at_local -or
            [string]$record.trigger.at_local -ne [string]$intentRecord.trigger.at_local -or
            [string]$record.settings.execution_time_limit -ne [string]$intentRecord.settings.execution_time_limit) {
            throw "$role registration receipt disagrees with its immutable intent."
        }
        if ($RequirePass -and -not [bool]$record.registered) {
            throw "PASS registration receipt does not prove that the $role task was registered."
        }
    }
    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = $receiptPath
        ReceiptSha256 = [string]$receiptSnapshot.Sha256
        Intent = $intentContract.Intent
        IntentPath = $intentContract.IntentPath
        IntentSha256 = $intentContract.IntentSha256
    }
}

function Assert-WeatherIntegrationScheduledTaskObject {
    param(
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][object]$BindingEvidence,
        [Parameter(Mandatory = $true)][ValidateSet("suite", "merge")][string]$Role
    )

    $record = $BindingEvidence.PSObject.Properties[$Role].Value
    $principal = $BindingEvidence.principal
    $actions = @($Task.Actions)
    $triggers = @($Task.Triggers)
    $requiredPrivileges = @(
        $Task.Principal.RequiredPrivilege |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
    )
    if ($actions.Count -ne 1 -or
        -not [string]::IsNullOrEmpty([string]$actions[0].Id) -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].Execute) -Right ([string]$record.executable)) -or
        [string]$actions[0].Arguments -ne [string]$record.arguments -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].WorkingDirectory) -Right ([string]$record.working_directory))) {
        throw "$Role task action is not exactly bound to the immutable registration evidence."
    }
    if ([string]$Task.TaskPath -ine [string]$record.task_path -or
        [string]$Task.Description -ne [string]$record.description) {
        throw "$Role task path or description does not match the immutable registration evidence."
    }
    $currentPrincipalContract = (
        [string]$BindingEvidence.binding_contract -ceq
            $script:WeatherIntegrationAttemptTaskBindingContract
    )
    if ($currentPrincipalContract) {
        Assert-WeatherIntegrationCanonicalWindowsIdentityBinding `
            -Principal $principal `
            -Label "$Role immutable task principal" | Out-Null
        $taskPrincipalSid = ConvertTo-WeatherIntegrationCanonicalPrincipalSid `
            -UserId ([string]$Task.Principal.UserId) `
            -Label "$Role Scheduler readback principal"
        if ($taskPrincipalSid -cne [string]$principal.sid) {
            throw "$Role Scheduler readback principal SID differs from immutable registration evidence."
        }
    }
    if (-not [string]::Equals(
            [string]$Task.Principal.UserId,
            [string]$principal.user_id,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        [string]$Task.Principal.LogonType -ne "S4U" -or
        [string]$Task.Principal.RunLevel -ne "Limited" -or
        [string]$Task.Principal.Id -ne "Author" -or
        -not [string]::IsNullOrEmpty([string]$Task.Principal.DisplayName) -or
        -not [string]::IsNullOrEmpty([string]$Task.Principal.GroupId) -or
        [string]$Task.Principal.ProcessTokenSidType -ne "Default" -or
        $requiredPrivileges.Count -ne 0) {
        throw "$Role task principal is not the exact S4U/Limited registration principal."
    }
    if ($triggers.Count -ne 1 -or
        [string]$triggers[0].CimClass.CimClassName -ne "MSFT_TaskTimeTrigger" -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].Id) -or
        -not [bool]$triggers[0].Enabled) {
        throw "$Role task must have exactly one enabled one-shot time trigger."
    }
    try {
        $actualBoundary = [string]$triggers[0].StartBoundary
        if ($actualBoundary -notmatch '[+-][0-9]{2}:[0-9]{2}$') {
            throw "Task Scheduler trigger boundary does not carry an explicit local UTC offset."
        }
        $actualTrigger = [datetimeoffset]::Parse(
            $actualBoundary,
            [Globalization.CultureInfo]::InvariantCulture
        )
        $actualTriggerAt = $actualTrigger.DateTime
        $expectedTriggerAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
            -Value ([string]$record.trigger.at_local) `
            -Label "$Role trigger_at_local"
        $expectedOffset = (Get-WeatherIntegrationScheduleTimeZone).
            GetUtcOffset($expectedTriggerAt)
    }
    catch {
        throw "$Role task trigger boundary is unreadable."
    }
    if ($actualTriggerAt -ne $expectedTriggerAt -or
        $actualTrigger.Offset -ne $expectedOffset -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].EndBoundary) -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].RandomDelay) -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].ExecutionTimeLimit) -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].Repetition.Interval) -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].Repetition.Duration) -or
        [bool]$triggers[0].Repetition.StopAtDurationEnd) {
        throw "$Role task trigger does not match the exact non-repeating local trigger."
    }
    $settings = $Task.Settings
    if ([string]$settings.MultipleInstances -ne [string]$record.settings.multiple_instances -or
        [string]$settings.Compatibility -ne [string]$record.settings.compatibility -or
        [bool]$settings.AllowDemandStart -ne [bool]$record.settings.allow_demand_start -or
        [bool]$settings.AllowHardTerminate -ne [bool]$record.settings.allow_hard_terminate -or
        [string]$settings.DeleteExpiredTaskAfter -ne [string]$record.settings.delete_expired_task_after -or
        [string]$settings.ExecutionTimeLimit -ne [string]$record.settings.execution_time_limit -or
        [bool]$settings.Hidden -ne [bool]$record.settings.hidden -or
        [int]$settings.Priority -ne [int]$record.settings.priority -or
        [int]$settings.RestartCount -ne [int]$record.settings.restart_count -or
        [string]$settings.RestartInterval -ne [string]$record.settings.restart_interval -or
        [bool]$settings.WakeToRun -ne [bool]$record.settings.wake_to_run -or
        [bool]$settings.StartWhenAvailable -ne [bool]$record.settings.start_when_available -or
        [bool]$settings.DisallowStartIfOnBatteries -eq [bool]$record.settings.allow_start_if_on_batteries -or
        [bool]$settings.StopIfGoingOnBatteries -ne [bool]$record.settings.stop_if_going_on_batteries -or
        [bool]$settings.RunOnlyIfIdle -ne [bool]$record.settings.run_only_if_idle -or
        [bool]$settings.RunOnlyIfNetworkAvailable -ne [bool]$record.settings.run_only_if_network_available -or
        [bool]$settings.DisallowStartOnRemoteAppSession -ne [bool]$record.settings.disallow_start_on_remote_app_session -or
        [bool]$settings.UseUnifiedSchedulingEngine -ne [bool]$record.settings.use_unified_scheduling_engine -or
        [bool]$settings.volatile -ne [bool]$record.settings.volatile -or
        [string]$settings.MaintenanceSettings -ne [string]$record.settings.maintenance_settings -or
        [string]$settings.IdleSettings.IdleDuration -ne [string]$record.settings.idle_duration -or
        [bool]$settings.IdleSettings.RestartOnIdle -ne [bool]$record.settings.idle_restart -or
        [bool]$settings.IdleSettings.StopOnIdleEnd -ne [bool]$record.settings.idle_stop_on_end -or
        [string]$settings.IdleSettings.WaitTimeout -ne [string]$record.settings.idle_wait_timeout -or
        [string]$settings.NetworkSettings.Id -ne [string]$record.settings.network_id -or
        [string]$settings.NetworkSettings.Name -ne [string]$record.settings.network_name) {
        throw "$Role task settings disagree with the exact registration contract."
    }
    return $Task
}

function Assert-WeatherIntegrationScheduledTaskBinding {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][ValidateSet("suite", "merge")][string]$Role,
        [Parameter(Mandatory = $true)][object]$BindingEvidence,
        [switch]$IncludeTaskInfo
    )

    $record = $BindingEvidence.PSObject.Properties[$Role].Value
    $matches = @(Get-ScheduledTask `
        -TaskName ([string]$record.task_name) `
        -TaskPath ([string]$record.task_path) `
        -ErrorAction Stop)
    if ($matches.Count -ne 1) {
        throw "$Role task lookup must resolve exactly one task; found $($matches.Count)."
    }
    $task = $matches[0]
    Assert-WeatherIntegrationScheduledTaskObject `
        -Task $task `
        -BindingEvidence $BindingEvidence `
        -Role $Role | Out-Null
    $info = $null
    if ($IncludeTaskInfo) {
        $info = Get-ScheduledTaskInfo `
            -TaskName ([string]$record.task_name) `
            -TaskPath ([string]$record.task_path) `
            -ErrorAction Stop
    }
    return [pscustomobject]@{
        Task = $task
        Info = $info
        BindingEvidence = $BindingEvidence
    }
}

function Assert-WeatherIntegrationAttemptTaskBinding {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][ValidateSet("suite", "merge")][string]$Role,
        [switch]$IncludeTaskInfo
    )

    $registration = Assert-WeatherIntegrationRegistrationReceipt `
        -AttemptContract $AttemptContract `
        -RequirePass
    $binding = Assert-WeatherIntegrationScheduledTaskBinding `
        -AttemptContract $AttemptContract `
        -Role $Role `
        -BindingEvidence $registration.Intent `
        -IncludeTaskInfo:$IncludeTaskInfo
    return [pscustomobject]@{
        Task = $binding.Task
        Info = $binding.Info
        RegistrationReceipt = $registration.Receipt
        RegistrationReceiptSha256 = $registration.ReceiptSha256
        RegistrationIntent = $registration.Intent
        RegistrationIntentSha256 = $registration.IntentSha256
    }
}

function Get-WeatherIntegrationRepairAllowedPatterns {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("retry_unchanged", "schema_registry", "ownership_metadata", "orchestration_wrapper", "manual_reviewed_change")]
        [string]$RepairClass
    )

    $patterns = switch ($RepairClass) {
        "retry_unchanged" { @() }
        "schema_registry" {
            @(
                '^src/weather/schema_registry_data\.py$',
                '^src/weather/schema_registry_recent_data\.py$',
                '^src/weather/schema_registry_types\.py$'
            )
        }
        "ownership_metadata" {
            @(
                '^docs/operations/module-ownership-map\.md$',
                '^tests/operations/test_module_size_audit\.py$'
            )
        }
        "orchestration_wrapper" {
            @(
                '^scripts/ops/(integration_attempt_contract|integration_attempt_remote_git|integration_attempt_preparation_contract|integration_attempt_quiet_merge_preflight|prepare_integration_attempt|assert_integration_attempt_ready|activate_integration_attempt|new_integration_attempt|register_integration_attempt|close_integration_attempt|retire_integration_attempt_tasks|dispatch_integration_attempt_recovery|integration_attempt_suite|integration_attempt_merge|assert_integration_attempt_success|reconcile_integration_attempt|bounded_worktree_test_suite|quiet_window_merge|boot_recovery|register_boot_recovery)\.ps1$',
                '^tests/operations/test_(integration_attempt_scripts|integration_attempt_preparation_scripts|integration_attempt_registration_safety|integration_attempt_evidence_recovery_hardening|bounded_worktree_test_suite_script|suite_gated_quiet_merge_script|quiet_window_merge_script|boot_recovery_script|register_boot_recovery_script|host_task_wrappers|status_script|ci_workflow_contract|offline_test_boundary)\.py$',
                '^docs/operations/(INTEGRATION_ATTEMPT_RUNBOOK|OPERATIONS_DESIGN)\.md$',
                '^docs/ops/streak-soak\.md$',
                '^(AGENTS\.md|scripts/ops/AGENTS\.md|tests/AGENTS\.md|docs/AGENTS\.md)$'
            )
        }
        "manual_reviewed_change" { @('^.+$') }
    }
    return @($patterns)
}

function Assert-WeatherIntegrationRepairTipPolicy {
    param(
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-f]{40}$")][string]$PriorTip,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-f]{40}$")][string]$ExpectedTip,
        [Parameter(Mandatory = $true)][bool]$PriorIsAncestor,
        [Parameter(Mandatory = $true)]
        [ValidateSet("retry_unchanged", "schema_registry", "ownership_metadata", "orchestration_wrapper", "manual_reviewed_change")]
        [string]$RepairClass,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()][string[]]$ChangeRows
    )

    if (-not $PriorIsAncestor) {
        throw "A repair tip must descend from the exact failed tip $PriorTip."
    }
    if ($RepairClass -eq "retry_unchanged" -and $ExpectedTip -ne $PriorTip) {
        throw "retry_unchanged requires the exact same commit id as the failed attempt."
    }
    if ($RepairClass -ne "retry_unchanged" -and $ChangeRows.Count -eq 0) {
        throw "Repair attempt does not contain a change from prior tip $PriorTip."
    }

    $changedPaths = New-Object System.Collections.Generic.List[string]
    foreach ($row in $ChangeRows) {
        if ([string]::IsNullOrWhiteSpace($row)) { continue }
        $columns = @($row -split "`t")
        $changeKind = [string]$columns[0]
        if ($columns.Count -lt 2 -or [string]::IsNullOrWhiteSpace([string]$columns[1])) {
            throw "Repair diff contains malformed name-status evidence."
        }
        if ($RepairClass -ne "manual_reviewed_change" -and
            $changeKind -notmatch '^[AM]$') {
            throw "Bounded repair classes permit only added or modified files; got $changeKind."
        }
        foreach ($path in @($columns | Select-Object -Skip 1)) {
            $changedPaths.Add(([string]$path).Replace("\", "/"))
        }
    }

    if ($RepairClass -eq "retry_unchanged" -and $changedPaths.Count -ne 0) {
        throw "retry_unchanged cannot contain changed paths."
    }
    $allowedPatterns = @(Get-WeatherIntegrationRepairAllowedPatterns `
        -RepairClass $RepairClass)
    foreach ($path in $changedPaths) {
        $matchingPolicies = @($allowedPatterns | Where-Object { $path -match $_ })
        if ($matchingPolicies.Count -eq 0) {
            throw "RepairClass $RepairClass does not authorize changed path: $path"
        }
    }
    return [pscustomobject]@{
        PriorTip = $PriorTip
        ExpectedTip = $ExpectedTip
        RepairClass = $RepairClass
        ChangedPaths = @($changedPaths)
    }
}

function Get-WeatherIntegrationScheduleTimeZone {
    try {
        $timeZone = [TimeZoneInfo]::FindSystemTimeZoneById(
            $script:WeatherIntegrationScheduleTimeZoneId
        )
    }
    catch {
        throw "The canonical America/Toronto Windows time zone is unavailable: $($script:WeatherIntegrationScheduleTimeZoneId)"
    }
    if ($null -eq $timeZone -or
        [string]$timeZone.Id -cne $script:WeatherIntegrationScheduleTimeZoneId) {
        throw "The canonical America/Toronto Windows time zone resolved ambiguously."
    }
    return $timeZone
}

function ConvertTo-WeatherIntegrationTimeZoneTransitionRow {
    param(
        [Parameter(Mandatory = $true)]
        [TimeZoneInfo+TransitionTime]$Transition
    )

    return ((
        @(
            if ($Transition.IsFixedDateRule) { "fixed" } else { "floating" },
            [string][int]$Transition.Month,
            [string][int]$Transition.Day,
            [string][int]$Transition.Week,
            [string][int]$Transition.DayOfWeek,
            [string][long]$Transition.TimeOfDay.TimeOfDay.Ticks
        ) -join ","
    ))
}

function Get-WeatherIntegrationScheduleTimeZoneBinding {
    param(
        [TimeZoneInfo]$TimeZone = (Get-WeatherIntegrationScheduleTimeZone)
    )

    if ([string]$TimeZone.Id -cne $script:WeatherIntegrationScheduleTimeZoneId) {
        throw "Integration schedules require the canonical America/Toronto Windows time zone."
    }
    $rows = New-Object System.Collections.Generic.List[string]
    $rows.Add("id=$([string]$TimeZone.Id)")
    $rows.Add("base_utc_offset_ticks=$([long]$TimeZone.BaseUtcOffset.Ticks)")
    $rows.Add("supports_daylight_saving=$([bool]$TimeZone.SupportsDaylightSavingTime)")
    foreach ($rule in @($TimeZone.GetAdjustmentRules())) {
        $baseDeltaTicks = if ($null -eq
            $rule.PSObject.Properties["BaseUtcOffsetDelta"]) {
            0L
        }
        else { [long]$rule.BaseUtcOffsetDelta.Ticks }
        $rows.Add((
            "rule=" + $rule.DateStart.ToString("yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture) +
            "," + $rule.DateEnd.ToString("yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture) +
            "," + [long]$rule.DaylightDelta.Ticks +
            "," + $baseDeltaTicks +
            "," + (ConvertTo-WeatherIntegrationTimeZoneTransitionRow `
                -Transition $rule.DaylightTransitionStart) +
            "," + (ConvertTo-WeatherIntegrationTimeZoneTransitionRow `
                -Transition $rule.DaylightTransitionEnd)
        ))
    }
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes((@($rows) -join "`n") + "`n")
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $rulesSha = (([BitConverter]::ToString($sha.ComputeHash($bytes))) `
            -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
    return [pscustomobject][ordered]@{
        schema_version = $script:WeatherIntegrationScheduleTimeZoneSchema
        windows_time_zone_id = [string]$TimeZone.Id
        base_utc_offset_minutes = [int]$TimeZone.BaseUtcOffset.TotalMinutes
        supports_daylight_saving_time = [bool]$TimeZone.SupportsDaylightSavingTime
        adjustment_rules_sha256 = $rulesSha
    }
}

function Assert-WeatherIntegrationScheduleTimeZoneBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Binding,
        [string]$Label = "integration schedule time zone"
    )

    Assert-WeatherIntegrationRequiredProperties `
        -Object $Binding `
        -Names @(
            "schema_version", "windows_time_zone_id",
            "base_utc_offset_minutes", "supports_daylight_saving_time",
            "adjustment_rules_sha256"
        ) `
        -Label $Label
    Assert-WeatherIntegrationBooleanProperties `
        -Object $Binding -Names @("supports_daylight_saving_time") -Label $Label
    $expected = Get-WeatherIntegrationScheduleTimeZoneBinding
    foreach ($name in @(
        "schema_version", "windows_time_zone_id", "base_utc_offset_minutes",
        "supports_daylight_saving_time", "adjustment_rules_sha256"
    )) {
        if ([string]$Binding.$name -cne [string]$expected.$name) {
            throw "$Label differs from the canonical America/Toronto rule at $name."
        }
    }
    return $expected
}

function Get-WeatherIntegrationScheduleLocalNow {
    param(
        [datetimeoffset]$UtcNow = [datetimeoffset]::UtcNow,
        [TimeZoneInfo]$TimeZone = (Get-WeatherIntegrationScheduleTimeZone)
    )

    if ([string]$TimeZone.Id -cne $script:WeatherIntegrationScheduleTimeZoneId) {
        throw "Integration schedule observations require America/Toronto."
    }
    return [datetime]::SpecifyKind(
        [TimeZoneInfo]::ConvertTime($UtcNow, $TimeZone).DateTime,
        [DateTimeKind]::Unspecified
    )
}

function Assert-WeatherIntegrationSchedulerHostTimeZone {
    $canonical = Get-WeatherIntegrationScheduleTimeZoneBinding
    if ([string][TimeZoneInfo]::Local.Id -cne
            [string]$canonical.windows_time_zone_id) {
        throw "Task Scheduler mutation requires the host local time zone to be Eastern Standard Time."
    }
    $localBinding = Get-WeatherIntegrationScheduleTimeZoneBinding `
        -TimeZone ([TimeZoneInfo]::Local)
    if ([string]$localBinding.adjustment_rules_sha256 -cne
            [string]$canonical.adjustment_rules_sha256) {
        throw "Task Scheduler host time-zone rules differ from the frozen America/Toronto contract."
    }
    return $canonical
}

function ConvertTo-WeatherIntegrationUtcTimestamp {
    param(
        [Parameter(Mandatory = $true)][datetimeoffset]$Value
    )

    return $Value.UtcDateTime.ToString(
        "yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'",
        [Globalization.CultureInfo]::InvariantCulture
    )
}

function Get-WeatherIntegrationScheduleEvidence {
    param(
        [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
        [Parameter(Mandatory = $true)][datetime]$MergeAtLocal
    )

    $timeZone = Get-WeatherIntegrationScheduleTimeZone
    $suiteAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $SuiteAtLocal -Label "suite_at_local" -TimeZone $timeZone
    $mergeAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $MergeAtLocal -Label "merge_at_local" -TimeZone $timeZone
    $suiteInstant = ConvertTo-WeatherIntegrationLocalInstant `
        -Value $suiteAt -Label "suite_at_local" -TimeZone $timeZone
    $mergeInstant = ConvertTo-WeatherIntegrationLocalInstant `
        -Value $mergeAt -Label "merge_at_local" -TimeZone $timeZone
    return [pscustomobject][ordered]@{
        time_zone = Get-WeatherIntegrationScheduleTimeZoneBinding -TimeZone $timeZone
        suite_at_local = $suiteAt.ToString("o")
        suite_at_utc = ConvertTo-WeatherIntegrationUtcTimestamp -Value $suiteInstant
        merge_at_local = $mergeAt.ToString("o")
        merge_at_utc = ConvertTo-WeatherIntegrationUtcTimestamp -Value $mergeInstant
    }
}

function Assert-WeatherIntegrationScheduleEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Schedule,
        [string]$Label = "integration schedule"
    )

    Assert-WeatherIntegrationRequiredProperties `
        -Object $Schedule `
        -Names @(
            "time_zone", "suite_at_local", "suite_at_utc",
            "merge_at_local", "merge_at_utc"
        ) `
        -Label $Label
    $timeZone = Get-WeatherIntegrationScheduleTimeZone
    Assert-WeatherIntegrationScheduleTimeZoneBinding `
        -Binding $Schedule.time_zone -Label "$Label time zone" | Out-Null
    $suiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$Schedule.suite_at_local) `
        -Label "$Label suite_at_local" -TimeZone $timeZone
    $mergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$Schedule.merge_at_local) `
        -Label "$Label merge_at_local" -TimeZone $timeZone
    $suiteInstant = ConvertTo-WeatherIntegrationLocalInstant `
        -Value $suiteAt -Label "$Label suite_at_local" -TimeZone $timeZone
    $mergeInstant = ConvertTo-WeatherIntegrationLocalInstant `
        -Value $mergeAt -Label "$Label merge_at_local" -TimeZone $timeZone
    if ([string]$Schedule.suite_at_utc -cne
            (ConvertTo-WeatherIntegrationUtcTimestamp -Value $suiteInstant) -or
        [string]$Schedule.merge_at_utc -cne
            (ConvertTo-WeatherIntegrationUtcTimestamp -Value $mergeInstant)) {
        throw "$Label local wall clocks and frozen UTC instants disagree."
    }
    return [pscustomobject]@{
        SuiteAtLocal = $suiteAt
        MergeAtLocal = $mergeAt
        SuiteInstant = $suiteInstant
        MergeInstant = $mergeInstant
        TimeZone = $timeZone
    }
}

function Assert-WeatherIntegrationScheduledSuiteLaunchReserve {
    param(
        [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
        [Parameter(Mandatory = $true)][datetime]$MergeAtLocal,
        [Parameter(Mandatory = $true)][datetime]$Now,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 86400)][int]$RequiredExecutionSeconds,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, 3600)][int]$LaunchGraceSeconds,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 90000)][int]$RequiredScheduleSeconds,
        [TimeZoneInfo]$TimeZone = (Get-WeatherIntegrationScheduleTimeZone)
    )

    $suiteAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $SuiteAtLocal -Label "SuiteAtLocal" -TimeZone $TimeZone
    $mergeAt = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $MergeAtLocal -Label "MergeAtLocal" -TimeZone $TimeZone
    $localNow = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $Now -Label "Now" -TimeZone $TimeZone
    if ($LaunchGraceSeconds -ne
            [int]$script:WeatherIntegrationSchedulerLaunchGraceSeconds -or
        $RequiredScheduleSeconds -ne
            ($RequiredExecutionSeconds + $LaunchGraceSeconds)) {
        throw "Scheduled suite launch reserve does not match its frozen grace contract."
    }
    if ($localNow.Date -ne $suiteAt.Date -or $mergeAt.Date -ne $suiteAt.Date) {
        throw "Scheduled suite launch must remain on the immutable local schedule date."
    }
    $launchDelaySeconds = Get-WeatherIntegrationLocalElapsedSeconds `
        -StartLocal $suiteAt -EndLocal $localNow `
        -StartLabel "SuiteAtLocal" -EndLabel "Now" -TimeZone $TimeZone
    if ($launchDelaySeconds -lt 0) {
        throw "Scheduled suite may not launch before its immutable trigger."
    }
    if ($launchDelaySeconds -gt $LaunchGraceSeconds) {
        throw "Scheduled suite exceeded its frozen Scheduler launch grace."
    }
    $hardStop = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $suiteAt.Date.AddHours(9) -Label "suite hard stop" `
        -TimeZone $TimeZone
    $remainingToMergeSeconds = Get-WeatherIntegrationLocalElapsedSeconds `
        -StartLocal $localNow -EndLocal $mergeAt `
        -StartLabel "Now" -EndLabel "MergeAtLocal" -TimeZone $TimeZone
    $remainingToHardStopSeconds = Get-WeatherIntegrationLocalElapsedSeconds `
        -StartLocal $localNow -EndLocal $hardStop `
        -StartLabel "Now" -EndLabel "suite hard stop" -TimeZone $TimeZone
    if ($remainingToMergeSeconds -lt $RequiredExecutionSeconds -or
        $remainingToHardStopSeconds -lt $RequiredExecutionSeconds) {
        throw "Remaining overnight window cannot contain the frozen execution reserve."
    }
    return [pscustomobject][ordered]@{
        checked_at_local = $localNow
        launch_delay_seconds = [math]::Round($launchDelaySeconds, 3)
        launch_grace_seconds = $LaunchGraceSeconds
        required_execution_seconds = $RequiredExecutionSeconds
        required_schedule_seconds = $RequiredScheduleSeconds
        remaining_to_merge_seconds = [math]::Floor($remainingToMergeSeconds)
        remaining_to_hard_stop_seconds = [math]::Floor($remainingToHardStopSeconds)
    }
}

function Get-WeatherIntegrationSuiteWaitDecision {
    param(
        [Parameter(Mandatory = $true)][string]$TaskState,
        [Parameter(Mandatory = $true)][datetime]$LastRunTime,
        [Parameter(Mandatory = $true)][int]$LastTaskResult,
        [Parameter(Mandatory = $true)][bool]$ReceiptExists,
        [AllowEmptyString()][string]$ReceiptStatus = "",
        [Parameter(Mandatory = $true)][datetime]$Now,
        [Parameter(Mandatory = $true)][datetime]$Deadline,
        [datetime]$PassReceiptCompletedAt = [datetime]::MinValue
    )

    if ($ReceiptExists -and $ReceiptStatus -eq "FAIL") {
        return [pscustomobject]@{ Action = "FAIL"; Reason = "suite emitted an immutable FAIL receipt" }
    }
    if ($TaskState -eq "Running") {
        if ($ReceiptExists -and $ReceiptStatus -eq "PASS") {
            if ($PassReceiptCompletedAt -eq [datetime]::MinValue -or
                $PassReceiptCompletedAt -gt $Now) {
                return [pscustomobject]@{
                    Action = "FAIL"
                    Reason = "suite PASS receipt has no valid completion time for its task-exit grace"
                }
            }
            $graceUntil = $PassReceiptCompletedAt.AddSeconds(120)
            $maximumGraceUntil = $Deadline.AddSeconds(120)
            if ($graceUntil -gt $maximumGraceUntil) {
                $graceUntil = $maximumGraceUntil
            }
            if ($Now -lt $graceUntil) {
                return [pscustomobject]@{
                    Action = "WAIT"
                    Reason = "suite emitted PASS and has a bounded two-minute task-exit grace"
                    PassExitGrace = $true
                    GraceStartedAt = $PassReceiptCompletedAt
                    GraceUntil = $graceUntil
                }
            }
            return [pscustomobject]@{
                Action = "STOP"
                Reason = "suite remained running past its PASS-receipt task-exit grace"
            }
        }
        if ($Now -ge $Deadline) {
            return [pscustomobject]@{ Action = "STOP"; Reason = "suite remained running through the merge-wait deadline" }
        }
        return [pscustomobject]@{ Action = "WAIT"; Reason = "suite task is still running" }
    }
    if ($TaskState -eq "Disabled" -and -not $ReceiptExists) {
        return [pscustomobject]@{ Action = "FAIL"; Reason = "suite task is disabled and can no longer run" }
    }
    if ($TaskState -notin @("Ready", "Disabled")) {
        if ($Now -ge $Deadline) {
            return [pscustomobject]@{ Action = "STOP"; Reason = "suite task remained non-terminal through the merge-wait deadline: $TaskState" }
        }
        return [pscustomobject]@{ Action = "WAIT"; Reason = "suite task state is not terminal yet: $TaskState" }
    }
    if ($LastRunTime -lt $Now.Date) {
        if ($Now -ge $Deadline) {
            return [pscustomobject]@{ Action = "FAIL"; Reason = "suite task did not run before the merge-wait deadline" }
        }
        return [pscustomobject]@{ Action = "WAIT"; Reason = "suite task has not run on the current local day" }
    }
    if ($ReceiptExists -and $ReceiptStatus -eq "PASS" -and
        $LastTaskResult -in @(0x41301, 0x41303)) {
        return [pscustomobject]@{
            Action = "READY"
            Reason = "suite task is terminal with immutable PASS evidence; Scheduler result is a stale transient"
            StaleSchedulerResult = $true
        }
    }
    if ($LastTaskResult -ne 0) {
        return [pscustomobject]@{ Action = "FAIL"; Reason = ("suite task result is 0x{0:X}" -f $LastTaskResult) }
    }
    if (-not $ReceiptExists) {
        return [pscustomobject]@{ Action = "FAIL"; Reason = "suite task returned success without an immutable receipt" }
    }
    if ($ReceiptStatus -ne "PASS") {
        return [pscustomobject]@{ Action = "FAIL"; Reason = "suite receipt status is unsupported or unreadable" }
    }
    return [pscustomobject]@{ Action = "READY"; Reason = "suite task and receipt are terminal PASS" }
}

function Assert-WeatherIntegrationLocalScheduleTime {
    param(
        [Parameter(Mandatory = $true)][datetime]$Value,
        [Parameter(Mandatory = $true)][string]$Label,
        [TimeZoneInfo]$TimeZone = (Get-WeatherIntegrationScheduleTimeZone)
    )

    if ($Value.Kind -eq [DateTimeKind]::Utc) {
        throw "$Label must be a local wall-clock value without a UTC marker."
    }
    $wallClock = [datetime]::SpecifyKind($Value, [DateTimeKind]::Unspecified)
    if ($TimeZone.IsInvalidTime($wallClock)) {
        throw "$Label falls in a daylight-saving gap and will not run: $($wallClock.ToString('o'))"
    }
    if ($TimeZone.IsAmbiguousTime($wallClock)) {
        throw "$Label falls in an ambiguous daylight-saving hour and is not safe for a one-shot: $($wallClock.ToString('o'))"
    }
    return $wallClock
}

function ConvertTo-WeatherIntegrationLocalInstant {
    param(
        [Parameter(Mandatory = $true)][datetime]$Value,
        [Parameter(Mandatory = $true)][string]$Label,
        [TimeZoneInfo]$TimeZone = (Get-WeatherIntegrationScheduleTimeZone)
    )

    $wallClock = Assert-WeatherIntegrationLocalScheduleTime `
        -Value $Value -Label $Label -TimeZone $TimeZone
    return [DateTimeOffset]::new(
        $wallClock,
        $TimeZone.GetUtcOffset($wallClock)
    )
}

function Get-WeatherIntegrationLocalElapsedSeconds {
    param(
        [Parameter(Mandatory = $true)][datetime]$StartLocal,
        [Parameter(Mandatory = $true)][datetime]$EndLocal,
        [string]$StartLabel = "interval start",
        [string]$EndLabel = "interval end",
        [TimeZoneInfo]$TimeZone = (Get-WeatherIntegrationScheduleTimeZone)
    )

    $startInstant = ConvertTo-WeatherIntegrationLocalInstant `
        -Value $StartLocal -Label $StartLabel -TimeZone $TimeZone
    $endInstant = ConvertTo-WeatherIntegrationLocalInstant `
        -Value $EndLocal -Label $EndLabel -TimeZone $TimeZone
    return ($endInstant.UtcDateTime - $startInstant.UtcDateTime).TotalSeconds
}

function ConvertFrom-WeatherIntegrationLocalTimestamp {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label,
        [TimeZoneInfo]$TimeZone = (Get-WeatherIntegrationScheduleTimeZone)
    )

    if ($Value -match '(?i)(?:Z|[+-][0-9]{2}:[0-9]{2})$') {
        throw "$Label must not carry a UTC marker or numeric offset; use the local wall clock."
    }
    try {
        $parsed = [datetime]::ParseExact(
            $Value,
            [string[]]@("o", "yyyy-MM-dd'T'HH:mm:ss"),
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None
        )
    }
    catch {
        throw "$Label is not a supported invariant local timestamp."
    }
    return Assert-WeatherIntegrationLocalScheduleTime `
        -Value $parsed -Label $Label -TimeZone $TimeZone
}

function ConvertFrom-WeatherIntegrationEvidenceTimestamp {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -notmatch '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,7})?(?:Z|[+-][0-9]{2}:[0-9]{2})$') {
        throw "$Label must be an invariant ISO-8601 timestamp with an explicit UTC offset."
    }
    try {
        return [datetimeoffset]::Parse(
            $Value,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch {
        throw "$Label is not a valid invariant ISO-8601 timestamp."
    }
}

function Assert-WeatherIntegrationGitBaseline {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    $manifest = $AttemptContract.Manifest
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
    $branchBeforeQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repoRoot `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
        -Label "$Phase production branch-before query"
    $refsQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repoRoot `
        -Arguments @(
            "rev-parse", "HEAD", "refs/heads/master",
            "refs/remotes/origin/master"
        ) `
        -Label "$Phase production ref-tuple query"
    $closingRefsQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repoRoot `
        -Arguments @(
            "rev-parse", "HEAD", "refs/heads/master",
            "refs/remotes/origin/master"
        ) `
        -Label "$Phase closing production ref-tuple query"
    $branchAfterQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $repoRoot `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
        -Label "$Phase production branch-after query"
    $branchBefore = @($branchBeforeQuery.StdoutLines)
    $refs = @($refsQuery.StdoutLines)
    $closingRefs = @($closingRefsQuery.StdoutLines)
    $branchAfter = @($branchAfterQuery.StdoutLines)
    if ($branchBefore.Count -ne 1 -or $branchAfter.Count -ne 1) {
        throw "$Phase production working tree is detached instead of checked out on master."
    }
    if ($refs.Count -ne 3 -or $closingRefs.Count -ne 3 -or
        @($refs | Where-Object {
            ([string]$_).Trim() -cnotmatch '^[0-9a-fA-F]{40}$'
        }).Count -ne 0 -or
        @($closingRefs | Where-Object {
            ([string]$_).Trim() -cnotmatch '^[0-9a-fA-F]{40}$'
        }).Count -ne 0) {
        throw "$Phase could not resolve one exact HEAD/master/origin tuple."
    }
    $branchName = ([string]$branchBefore[0]).Trim()
    $finalBranchName = ([string]$branchAfter[0]).Trim()
    $headTip = ([string]$refs[0]).Trim().ToLowerInvariant()
    $masterTip = ([string]$refs[1]).Trim().ToLowerInvariant()
    $originTip = ([string]$refs[2]).Trim().ToLowerInvariant()
    if ($branchName -cne $finalBranchName -or
        (@($refs | ForEach-Object {
            ([string]$_).Trim().ToLowerInvariant()
        }) -join "`n") -cne
            (@($closingRefs | ForEach-Object {
                ([string]$_).Trim().ToLowerInvariant()
            }) -join "`n")) {
        throw "$Phase production branch/ref tuple changed while it was sampled."
    }
    if ($branchName -ne "master" -or
        $headTip -ne [string]$manifest.baseline.master -or
        $masterTip -ne [string]$manifest.baseline.master -or
        $originTip -ne [string]$manifest.baseline.origin_master) {
        throw "$Phase baseline changed after attempt freeze. Expected $($manifest.baseline.master); branch=$branchName HEAD=$headTip master=$masterTip origin/master=$originTip"
    }
    return [pscustomobject]@{ Branch = $branchName; Head = $headTip; Master = $masterTip; OriginMaster = $originTip }
}

function Assert-WeatherIntegrationLiveOriginBaseline {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$Phase,
        [switch]$RefreshTrackingMaster
    )

    $manifest = $AttemptContract.Manifest
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
    $originIdentity = Assert-WeatherIntegrationOriginIdentity `
        -AttemptContract $AttemptContract -Phase $Phase
    $branchRef = [string]$manifest.branch_ref
    if ($branchRef -cnotmatch '^origin/(?<topic>[A-Za-z0-9][A-Za-z0-9._/-]{0,192})$') {
        throw "$Phase cannot derive an exact live topic ref from $branchRef."
    }
    if ([string]$Matches.topic -cin @("master", "main")) {
        throw "$Phase refuses to use a production branch as an integration topic."
    }
    $topicRef = "refs/heads/$([string]$Matches.topic)"
    $wantedRefs = @("refs/heads/master", $topicRef)
    $remoteQuery = if ([bool]$originIdentity.Legacy) {
        Invoke-WeatherIntegrationBoundedRemoteGit `
            -Root $repoRoot `
            -Arguments (@("ls-remote", "--heads", "origin") + $wantedRefs) `
            -Label "$Phase legacy live origin query"
    }
    else {
        Invoke-WeatherIntegrationCanonicalLsRemote `
            -Root $repoRoot `
            -ExpectedUrl ([string]$originIdentity.OriginUrl) `
            -RemoteRefs $wantedRefs `
            -Label "$Phase live canonical origin query"
    }
    $rows = @($remoteQuery.StdoutLines)
    $observed = @{}
    foreach ($row in $rows) {
        $columns = @(([string]$row).Trim() -split "`t")
        if ($columns.Count -ne 2 -or
            [string]$columns[0] -cnotmatch '^[0-9a-fA-F]{40}$' -or
            $wantedRefs -cnotcontains [string]$columns[1] -or
            $observed.ContainsKey([string]$columns[1])) {
            throw "$Phase received ambiguous live origin ref evidence."
        }
        $observed[[string]$columns[1]] = ([string]$columns[0]).ToLowerInvariant()
    }
    if ($observed.Count -ne 2 -or
        [string]$observed["refs/heads/master"] -ne
            [string]$manifest.baseline.master -or
        [string]$observed[$topicRef] -ne [string]$manifest.expected_tip) {
        throw "$Phase live origin no longer matches the frozen baseline/topic."
    }
    if ($RefreshTrackingMaster) {
        $fetchRemote = if ([bool]$originIdentity.Legacy) {
            "origin"
        }
        else { [string]$originIdentity.OriginUrl }
        Invoke-WeatherIntegrationBoundedRemoteGit `
            -Root $repoRoot `
            -Arguments @(
                "fetch", "--no-tags", $fetchRemote,
                "refs/heads/master:refs/remotes/origin/master"
            ) `
            -Label "$Phase origin/master refresh" | Out-Null
        $trackingQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $repoRoot `
            -Arguments @("rev-parse", "refs/remotes/origin/master") `
            -Label "$Phase refreshed origin/master query"
        $trackingRows = @($trackingQuery.StdoutLines)
        if ($trackingRows.Count -ne 1 -or
            ([string]$trackingRows[0]).Trim().ToLowerInvariant() -ne
                [string]$manifest.baseline.master) {
            throw "$Phase refreshed origin/master does not equal the frozen baseline."
        }
    }
    return [pscustomobject]@{
        Master = [string]$observed["refs/heads/master"]
        TopicRef = $topicRef
        Topic = [string]$observed[$topicRef]
        TrackingMasterRefreshed = [bool]$RefreshTrackingMaster
    }
}

function Assert-WeatherIntegrationCurrentAuthorityTuple {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    $manifest = $AttemptContract.Manifest
    if ([string]$manifest.schema -cne
            $script:WeatherIntegrationAttemptManifestSchema) {
        throw "$Phase complete authority tuple is required only for strict v2 attempts."
    }
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
    $worktreeRoot = Resolve-WeatherIntegrationPath `
        -Path ([string]$manifest.worktree_root)
    $topicBranch = Get-WeatherIntegrationTopicBranchName `
        -BranchRef ([string]$manifest.branch_ref)
    $observations = New-Object System.Collections.Generic.List[object]
    foreach ($pass in 1..2) {
        $live = Assert-WeatherIntegrationLiveOriginBaseline `
            -AttemptContract $AttemptContract -Phase "$Phase pass $pass"
        $baseline = Assert-WeatherIntegrationGitBaseline `
            -AttemptContract $AttemptContract -Phase "$Phase pass $pass"
        $trackingQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $repoRoot `
            -Arguments @("rev-parse", [string]$manifest.branch_ref) `
            -Label "$Phase pass $pass tracking-topic query"
        $registrationQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $repoRoot `
            -Arguments @("worktree", "list", "--porcelain") `
            -Label "$Phase pass $pass registered-worktree query"
        $worktreeBranchQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $worktreeRoot -Arguments @("branch", "--show-current") `
            -Label "$Phase pass $pass worktree-branch query"
        $worktreeTipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $worktreeRoot `
            -Arguments @("rev-parse", "--verify", "HEAD^{commit}") `
            -Label "$Phase pass $pass worktree-tip query"
        $worktreeStatusQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $worktreeRoot -Arguments @("status", "--porcelain") `
            -Label "$Phase pass $pass worktree-status query"
        $testQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $worktreeRoot -Arguments @("ls-files", "--", "tests") `
            -Label "$Phase pass $pass tracked-test inventory query"
        $sourceQuery = Invoke-WeatherIntegrationCheckedLocalGit `
            -Root $worktreeRoot `
            -Arguments @("ls-files", "--", "*.py", "*.ps1") `
            -Label "$Phase pass $pass tracked-source inventory query"
        Assert-WeatherIntegrationNoIgnoredImportArtifacts `
            -WorktreeRoot $worktreeRoot -Phase "$Phase pass $pass" | Out-Null
        $trackedWorktree = Get-WeatherIntegrationTrackedWorktreeFingerprint `
            -WorktreeRoot $worktreeRoot `
            -ExpectedHead ([string]$manifest.expected_tip) `
            -Phase "$Phase pass $pass tracked inputs"

        $trackingRows = @($trackingQuery.StdoutLines)
        $worktreeBranches = @($worktreeBranchQuery.StdoutLines)
        $worktreeTips = @($worktreeTipQuery.StdoutLines)
        $worktreeStatus = @($worktreeStatusQuery.StdoutLines)
        $registeredPaths = @(
            @($registrationQuery.StdoutLines) |
                Where-Object { [string]$_ -like "worktree *" } |
                ForEach-Object {
                    Resolve-WeatherIntegrationPath `
                        -Path ([string]$_).Substring("worktree ".Length)
                } |
                Where-Object {
                    Test-WeatherIntegrationPathEqual `
                        -Left $_ -Right $worktreeRoot
                }
        )
        $tests = @(
            @($testQuery.StdoutLines) |
                ForEach-Object { ([string]$_).Replace("\", "/") } |
                Where-Object {
                    $_ -match '^tests/(?:.*/)?(?:test_[^/]*|[^/]+_test)\.py$'
                } |
                Sort-Object -Unique
        )
        $sources = @(
            @($sourceQuery.StdoutLines) |
                ForEach-Object { ([string]$_).Replace("\", "/") } |
                Sort-Object -Unique
        )
        $python = @($sources | Where-Object { $_ -match '(?i)\.py$' })
        $powerShell = @($sources | Where-Object { $_ -match '(?i)\.ps1$' })
        if ($trackingRows.Count -ne 1 -or $worktreeBranches.Count -ne 1 -or
            $worktreeTips.Count -ne 1 -or $registeredPaths.Count -ne 1 -or
            $worktreeStatus.Count -ne 0 -or $tests.Count -le 0 -or
            $python.Count -le 0 -or $powerShell.Count -le 0) {
            throw "$Phase could not observe one complete clean registered worktree tuple."
        }
        $observation = [pscustomobject][ordered]@{
            ProductionBranch = [string]$baseline.Branch
            Head = [string]$baseline.Head
            Master = [string]$baseline.Master
            OriginMaster = [string]$baseline.OriginMaster
            LiveMaster = [string]$live.Master
            LiveTopic = [string]$live.Topic
            TrackingTopic = ([string]$trackingRows[0]).Trim().ToLowerInvariant()
            WorktreeBranch = ([string]$worktreeBranches[0]).Trim()
            WorktreeHead = ([string]$worktreeTips[0]).Trim().ToLowerInvariant()
            TestFileCount = $tests.Count
            TestInventorySha256 = Get-WeatherIntegrationInventorySha256 -Paths $tests
            PythonFileCount = $python.Count
            PythonInventorySha256 = Get-WeatherIntegrationInventorySha256 -Paths $python
            PowerShellFileCount = $powerShell.Count
            PowerShellInventorySha256 =
                Get-WeatherIntegrationInventorySha256 -Paths $powerShell
            TrackedWorktreeSchema = [string]$trackedWorktree.schema_version
            TrackedWorktreeSha256 = [string]$trackedWorktree.content_sha256
            TrackedWorktreeFileCount = [int]$trackedWorktree.file_count
            TrackedWorktreeTotalBytes = [long]$trackedWorktree.total_bytes
            TrackedWorktreeLfsFileCount = [int]$trackedWorktree.lfs_file_count
        }
        if ([string]$observation.LiveMaster -ne [string]$manifest.baseline.master -or
            [string]$observation.LiveTopic -ne [string]$manifest.expected_tip -or
            [string]$observation.TrackingTopic -ne [string]$manifest.expected_tip -or
            [string]$observation.WorktreeBranch -cne $topicBranch -or
            [string]$observation.WorktreeHead -ne [string]$manifest.expected_tip -or
            [int]$observation.TestFileCount -ne
                [int]$manifest.suite.expected_test_file_count -or
            [string]$observation.TestInventorySha256 -cne
                [string]$manifest.suite.expected_test_inventory_sha256 -or
            [int]$observation.PythonFileCount -ne
                [int]$manifest.suite.expected_python_file_count -or
            [string]$observation.PythonInventorySha256 -cne
                [string]$manifest.suite.expected_python_inventory_sha256 -or
            [int]$observation.PowerShellFileCount -ne
                [int]$manifest.suite.expected_powershell_file_count -or
            [string]$observation.PowerShellInventorySha256 -cne
                [string]$manifest.suite.expected_powershell_inventory_sha256 -or
            [string]$observation.TrackedWorktreeSchema -cne
                [string]$manifest.suite.expected_tracked_worktree_schema -or
            [string]$observation.TrackedWorktreeSha256 -cne
                [string]$manifest.suite.expected_tracked_worktree_sha256 -or
            [int]$observation.TrackedWorktreeFileCount -ne
                [int]$manifest.suite.expected_tracked_worktree_file_count -or
            [long]$observation.TrackedWorktreeTotalBytes -ne
                [long]$manifest.suite.expected_tracked_worktree_total_bytes -or
            [int]$observation.TrackedWorktreeLfsFileCount -ne
                [int]$manifest.suite.expected_tracked_worktree_lfs_file_count) {
            throw "$Phase current live/local/worktree/inventory tuple differs from the v2 manifest."
        }
        $observations.Add($observation)
    }
    foreach ($name in @($observations[0].PSObject.Properties.Name)) {
        if ([string]$observations[0].$name -cne
                [string]$observations[1].$name) {
            throw "$Phase authority tuple changed between complete observations at field $name."
        }
    }
    return $observations[1]
}

function Assert-WeatherIntegrationOriginIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    $manifest = $AttemptContract.Manifest
    $originUrlProperty = $manifest.baseline.PSObject.Properties["origin_url"]
    if ($null -eq $originUrlProperty -or
        [string]::IsNullOrWhiteSpace([string]$originUrlProperty.Value)) {
        $preparationProperty = $manifest.authorization.PSObject.Properties["preparation"]
        if ($null -ne $preparationProperty -and $null -ne $preparationProperty.Value) {
            throw "$Phase composite attempt is missing its frozen origin URL."
        }
        return [pscustomobject]@{ Legacy = $true; OriginUrl = $null }
    }
    $originUrl = [string]$originUrlProperty.Value
    Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root ([string]$manifest.repo_root) `
        -ExpectedUrl $originUrl `
        -Phase $Phase | Out-Null
    return [pscustomobject]@{ Legacy = $false; OriginUrl = $originUrl }
}

function Assert-WeatherIntegrationEvidencePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AttemptRoot,
        [Parameter(Mandatory = $true)]
        [string]$ActualPath,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedName
    )

    $expectedPath = Join-Path (Resolve-WeatherIntegrationPath -Path $AttemptRoot) $ExpectedName
    if (-not (Test-WeatherIntegrationPathEqual -Left $ActualPath -Right $expectedPath)) {
        throw "Attempt evidence path for $ExpectedName is not canonical. Expected $expectedPath; got $ActualPath"
    }
    return $expectedPath
}

function Assert-WeatherIntegrationAttemptManifest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ManifestPath,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha256
    )

    $resolvedManifestPath = Resolve-WeatherIntegrationPath -Path $ManifestPath
    if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Expected manifest SHA256 must be exactly 64 hexadecimal characters."
    }
    $manifestSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $resolvedManifestPath -MaximumBytes 1048576 -ContentType Json
    $actualSha256 = [string]$manifestSnapshot.Sha256
    if ($actualSha256 -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "Attempt manifest hash mismatch. Expected $ExpectedSha256; got $actualSha256"
    }

    $manifest = $manifestSnapshot.Payload
    if ([string]$manifest.schema -cnotin @(
            $script:WeatherIntegrationAttemptLegacyManifestSchema,
            $script:WeatherIntegrationAttemptManifestSchema
        )) {
        throw "Unsupported integration-attempt manifest schema: $($manifest.schema)"
    }
    if ([string]$manifest.attempt_id -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$') {
        throw "Attempt id is missing or unsafe: $($manifest.attempt_id)"
    }
    if ([string]$manifest.expected_tip -notmatch '^[0-9a-f]{40}$') {
        throw "Attempt expected tip must be a lowercase 40-character commit id."
    }
    if ([string]$manifest.branch_ref -cnotmatch '^origin/(?<topic>[A-Za-z0-9][A-Za-z0-9._/-]{0,192})$' -or
        [string]$Matches.topic -cin @("master", "main")) {
        throw "Attempt branch ref is missing or unsafe: $($manifest.branch_ref)"
    }
    if ([string]::IsNullOrWhiteSpace([string]$manifest.authorization.review_reference)) {
        throw "Attempt is missing its review reference."
    }
    if ([string]$manifest.schema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
        $qualifiedPreparation = $manifest.authorization.PSObject.Properties["preparation"]
        if ($null -eq $qualifiedPreparation -or $null -eq $qualifiedPreparation.Value) {
            throw "A v2 integration attempt must bind pre-arming qualification evidence."
        }
        Assert-WeatherIntegrationRequiredProperties `
            -Object $qualifiedPreparation.Value `
            -Names @(
                "prearming_qualification_path",
                "prearming_qualification_sha256"
            ) `
            -Label "v2 integration-attempt qualification binding"
        if ([string]$qualifiedPreparation.Value.prearming_qualification_sha256 -notmatch
                '^[0-9a-f]{64}$') {
            throw "A v2 integration attempt must bind an exact qualification receipt hash."
        }
    }
    $expectedSuiteTaskName = "WeatherIntegrationSuite_$($manifest.attempt_id)"
    $expectedMergeTaskName = "WeatherIntegrationMerge_$($manifest.attempt_id)"
    if ([string]$manifest.schedule.suite_task_name -ne $expectedSuiteTaskName -or
        [string]$manifest.schedule.merge_task_name -ne $expectedMergeTaskName) {
        throw "Attempt task names are not the canonical names derived from attempt_id."
    }
    try {
        if ([string]$manifest.schema -ceq
                $script:WeatherIntegrationAttemptManifestSchema) {
            $scheduleEvidence = Assert-WeatherIntegrationScheduleEvidence `
                -Schedule $manifest.schedule -Label "v2 integration schedule"
            $suiteAt = [datetime]$scheduleEvidence.SuiteAtLocal
            $mergeAt = [datetime]$scheduleEvidence.MergeAtLocal
        }
        else {
            # Historical v1 manifests had no explicit zone/rule/UTC binding.
            # Interpret their wall clocks in the canonical policy zone solely
            # so they remain structurally readable and exactly closeable.
            $suiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
                -Value ([string]$manifest.schedule.suite_at_local) `
                -Label "suite_at_local"
            $mergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
                -Value ([string]$manifest.schedule.merge_at_local) `
                -Label "merge_at_local"
        }
    }
    catch {
        throw "Attempt schedule timestamps are invalid."
    }
    $suiteMinute = ($suiteAt.Hour * 60) + $suiteAt.Minute
    $mergeMinute = ($mergeAt.Hour * 60) + $mergeAt.Minute
    $suiteToMergeSeconds = if ([string]$manifest.schema -ceq
            $script:WeatherIntegrationAttemptManifestSchema) {
        Get-WeatherIntegrationLocalElapsedSeconds `
            -StartLocal $suiteAt -EndLocal $mergeAt `
            -StartLabel "suite_at_local" -EndLabel "merge_at_local"
    }
    else {
        # Historical v1 manifests retain their original structural wall-clock
        # schedule contract so exact-task closure stays readable.
        ($mergeAt - $suiteAt).TotalSeconds
    }
    if ($suiteAt.Date -ne $mergeAt.Date -or
        $suiteMinute -lt 30 -or $suiteMinute -ge 540 -or
        $mergeMinute -lt 60 -or $mergeMinute -ge 220 -or
        $suiteToMergeSeconds -lt 1800) {
        throw "Attempt schedule violates the suite or quiet-window contract."
    }
    if ([string]$manifest.baseline.master -notmatch '^[0-9a-f]{40}$' -or
        [string]$manifest.baseline.master -ne [string]$manifest.baseline.origin_master) {
        throw "Attempt baseline does not bind equal production and origin tips."
    }
    $originUrlProperty = $manifest.baseline.PSObject.Properties["origin_url"]
    if ($null -ne $originUrlProperty) {
        $originUrl = [string]$originUrlProperty.Value
        if ([string]::IsNullOrWhiteSpace($originUrl) -or
            (ConvertTo-WeatherIntegrationCanonicalOriginUrl -Url $originUrl) -cne
                $originUrl) {
            throw "Attempt baseline origin URL is absent or non-canonical."
        }
    }
    $expectedTestFileCount = [int]$manifest.suite.expected_test_file_count
    $maxFilesPerChunk = [int]$manifest.suite.max_files_per_chunk
    $expectedChunkCount = [int]$manifest.suite.expected_chunk_count
    if (-not [string]::IsNullOrWhiteSpace([string]$manifest.suite.additional_python_path)) {
        throw "Integration attempts do not support AdditionalPythonPath because external Python content is not frozen by the manifest."
    }
    if ($expectedTestFileCount -le 0 -or $maxFilesPerChunk -lt 1 -or
        $maxFilesPerChunk -gt 25 -or $expectedChunkCount -le 0 -or
        $expectedChunkCount -ne [int][math]::Ceiling($expectedTestFileCount / [double]$maxFilesPerChunk)) {
        throw "Attempt suite inventory is missing or internally inconsistent."
    }
    if ([string]$manifest.schema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
        Assert-WeatherIntegrationRequiredProperties `
            -Object $manifest.suite `
            -Names @(
                "expected_test_inventory_sha256",
                "expected_python_file_count", "expected_python_inventory_sha256",
                "expected_powershell_file_count",
                "expected_powershell_inventory_sha256",
                "expected_tracked_worktree_schema",
                "expected_tracked_worktree_sha256",
                "expected_tracked_worktree_file_count",
                "expected_tracked_worktree_total_bytes",
                "expected_tracked_worktree_lfs_file_count",
                "expected_python_environment_schema",
                "expected_python_environment_sha256",
                "expected_python_environment_distributions",
                "expected_python_environment_files",
                "expected_python_environment_bytes",
                "expected_toolchain_schema", "expected_toolchain_sha256",
                "prearming_measured_duration_seconds",
                "prearming_planning_ceiling_seconds",
                "prearming_safety_margin_seconds",
                "prearming_required_runtime_seconds",
                "prearming_launch_grace_seconds",
                "prearming_required_schedule_seconds",
                "bounded_suite_max_runtime_seconds",
                "suite_wrapper_teardown_allowance_seconds",
                "suite_task_execution_time_limit_seconds"
            ) `
            -Label "v2 integration-attempt runtime reserve"
        if ([string]$manifest.suite.expected_test_inventory_sha256 -cnotmatch
                '^[0-9a-f]{64}$' -or
            [int]$manifest.suite.expected_python_file_count -le 0 -or
            [string]$manifest.suite.expected_python_inventory_sha256 -cnotmatch
                '^[0-9a-f]{64}$' -or
            [int]$manifest.suite.expected_powershell_file_count -le 0 -or
            [string]$manifest.suite.expected_powershell_inventory_sha256 -cnotmatch
                '^[0-9a-f]{64}$' -or
            [string]$manifest.suite.expected_tracked_worktree_schema -cne
                "tracked_worktree_content_fingerprint_v1" -or
            [string]$manifest.suite.expected_tracked_worktree_sha256 -cnotmatch
                '^[0-9a-f]{64}$' -or
            [int]$manifest.suite.expected_tracked_worktree_file_count -le 0 -or
            [int]$manifest.suite.expected_tracked_worktree_file_count -gt 20000 -or
            [long]$manifest.suite.expected_tracked_worktree_total_bytes -lt 0 -or
            [long]$manifest.suite.expected_tracked_worktree_total_bytes -gt
                2147483648 -or
            [int]$manifest.suite.expected_tracked_worktree_lfs_file_count -lt 0 -or
            [int]$manifest.suite.expected_tracked_worktree_lfs_file_count -gt
                [int]$manifest.suite.expected_tracked_worktree_file_count -or
            [string]$manifest.suite.expected_python_environment_schema -cne
                "python_environment_fingerprint_v2" -or
            [string]$manifest.suite.expected_python_environment_sha256 -cnotmatch
                '^[0-9a-f]{64}$' -or
            [int]$manifest.suite.expected_python_environment_distributions -lt 0 -or
            [int]$manifest.suite.expected_python_environment_files -le 0 -or
            [int]$manifest.suite.expected_python_environment_files -gt 50000 -or
            [long]$manifest.suite.expected_python_environment_bytes -le 0 -or
            [long]$manifest.suite.expected_python_environment_bytes -gt 2147483648) {
            throw "v2 integration-attempt creator/environment inventories are invalid."
        }
        if ([string]$manifest.suite.expected_toolchain_schema -cne
                "integration_toolchain_fingerprint_v1" -or
            [string]$manifest.suite.expected_toolchain_sha256 -cnotmatch
                '^[0-9a-f]{64}$') {
            throw "v2 integration-attempt qualification-frozen toolchain is invalid."
        }
        $expectedRequiredRuntime = [math]::Max(
            [int]$script:WeatherIntegrationPrearmingPlanningCeilingSeconds,
            [int][math]::Ceiling(
                [double]$manifest.suite.prearming_measured_duration_seconds
            )
        ) + [int]$script:WeatherIntegrationPrearmingSafetyMarginSeconds
        $expectedLaunchGrace =
            [int]$script:WeatherIntegrationSchedulerLaunchGraceSeconds
        $expectedRequiredSchedule = $expectedRequiredRuntime + $expectedLaunchGrace
        $suiteHardStop = Assert-WeatherIntegrationLocalScheduleTime `
            -Value $suiteAt.Date.AddHours(9) -Label "suite hard stop"
        $suiteToHardStopSeconds = Get-WeatherIntegrationLocalElapsedSeconds `
            -StartLocal $suiteAt -EndLocal $suiteHardStop `
            -StartLabel "suite_at_local" -EndLabel "suite hard stop"
        if ([double]$manifest.suite.prearming_measured_duration_seconds -lt 0 -or
            [int]$manifest.suite.prearming_planning_ceiling_seconds -ne
                [int]$script:WeatherIntegrationPrearmingPlanningCeilingSeconds -or
            [int]$manifest.suite.prearming_safety_margin_seconds -ne
                [int]$script:WeatherIntegrationPrearmingSafetyMarginSeconds -or
            [int]$manifest.suite.prearming_required_runtime_seconds -ne
                $expectedRequiredRuntime -or
            [int]$manifest.suite.prearming_launch_grace_seconds -ne
                $expectedLaunchGrace -or
            [int]$manifest.suite.prearming_required_schedule_seconds -ne
                $expectedRequiredSchedule -or
            [int]$manifest.suite.bounded_suite_max_runtime_seconds -ne
                [int]$script:WeatherIntegrationBoundedSuiteMaximumRuntimeSeconds -or
            [int]$manifest.suite.suite_wrapper_teardown_allowance_seconds -ne
                [int]$script:WeatherIntegrationSuiteWrapperTeardownAllowanceSeconds -or
            [int]$manifest.suite.suite_task_execution_time_limit_seconds -ne
                [int]$script:WeatherIntegrationSuiteTaskExecutionLimitSeconds -or
            [int]$manifest.suite.suite_task_execution_time_limit_seconds -ne
                ([int]$manifest.suite.bounded_suite_max_runtime_seconds +
                 [int]$manifest.suite.suite_wrapper_teardown_allowance_seconds) -or
            [double]$manifest.suite.prearming_measured_duration_seconds -gt
                [double]$manifest.suite.bounded_suite_max_runtime_seconds -or
            $suiteToMergeSeconds -lt $expectedRequiredSchedule -or
            $suiteToHardStopSeconds -lt $expectedRequiredSchedule) {
            throw "v2 integration-attempt runtime reserve is missing or infeasible."
        }
    }

    $attemptRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.attempt_root)
    $manifestParent = Resolve-WeatherIntegrationPath -Path (Split-Path -Parent $resolvedManifestPath)
    if (-not (Test-WeatherIntegrationPathEqual -Left $attemptRoot -Right $manifestParent)) {
        throw "Manifest attempt_root does not match the manifest parent directory."
    }
    if (Test-WeatherIntegrationPathEqual -Left ([string]$manifest.repo_root) -Right ([string]$manifest.worktree_root)) {
        throw "An integration attempt may not use the production repository as its suite worktree."
    }

    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.preflight_log) -ExpectedName "preflight.log" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.full_suite_log) -ExpectedName "full-suite.log" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.suite_receipt) -ExpectedName "suite-receipt.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.merge_receipt) -ExpectedName "merge-receipt.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.quiet_merge_report) -ExpectedName "quiet-merge-report.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.registration_receipt) -ExpectedName "registration-receipt.json" | Out-Null
    $registrationIntentProperty = $manifest.evidence.PSObject.Properties["registration_intent"]
    if ($null -ne $registrationIntentProperty -and
        -not [string]::IsNullOrWhiteSpace([string]$registrationIntentProperty.Value)) {
        Assert-WeatherIntegrationEvidencePath `
            -AttemptRoot $attemptRoot `
            -ActualPath ([string]$registrationIntentProperty.Value) `
            -ExpectedName "registration-intent.json" | Out-Null
    }
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.closure_receipt) -ExpectedName "closure-receipt.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.recovery_dispatch) -ExpectedName "recovery-dispatch.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.reconciliation_receipt) -ExpectedName "reconciliation-receipt.json" | Out-Null

    $contract = [pscustomobject]@{
        Manifest = $manifest
        ManifestPath = $resolvedManifestPath
        ManifestSha256 = $actualSha256
        AttemptRoot = $attemptRoot
    }
    Assert-WeatherIntegrationPreparationAuthorizationStructure `
        -AttemptContract $contract | Out-Null
    # Cleanup must remain possible after external qualification or predecessor
    # evidence is lost.  Runtime boundaries call the strict validator separately.
    Assert-WeatherIntegrationRepairClaimStructure -AttemptContract $contract | Out-Null
    return $contract
}

function Disable-WeatherIntegrationAttemptTasks {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract
    )

    $manifest = $AttemptContract.Manifest
    $registrationReceiptPath = [string]$manifest.evidence.registration_receipt
    $registrationReceipt = $null
    $strictRegistration = $null
    $strictBindingSource = $null
    $registrationReceiptError = $null
    $registrationIntentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $AttemptContract
    if (Test-Path -LiteralPath $registrationIntentPath -PathType Leaf) {
        # This is the first durable registrar write and is independently
        # derivable from the manifest. Prefer it as the crash-recovery floor;
        # a torn or missing later receipt must not strand exact tasks.
        $strictRegistration = Assert-WeatherIntegrationRegistrationIntent -AttemptContract $AttemptContract
        $strictBindingSource = "pre_registration_intent"
    }
    if (Test-Path -LiteralPath $registrationReceiptPath -PathType Leaf) {
        try {
            $registrationReceipt = Read-WeatherIntegrationSharedJson -Path $registrationReceiptPath
            if ([string]$registrationReceipt.schema -notin @(
                    $script:WeatherIntegrationAttemptRegistrationReceiptSchema,
                    $script:WeatherIntegrationAttemptLegacyRegistrationReceiptSchema
                ) -or
                [string]$registrationReceipt.attempt_id -ne [string]$manifest.attempt_id -or
                -not (Test-WeatherIntegrationPathEqual -Left ([string]$registrationReceipt.manifest_path) -Right $AttemptContract.ManifestPath) -or
                [string]$registrationReceipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256) {
                throw "Registration receipt does not bind this exact attempt."
            }
            $bindingContractProperty = $registrationReceipt.PSObject.Properties["binding_contract"]
            if ($null -ne $bindingContractProperty -and
                [string]$bindingContractProperty.Value -in @(
                    $script:WeatherIntegrationAttemptTaskBindingContract,
                    $script:WeatherIntegrationAttemptLegacyTaskBindingContract
                )) {
                $strictRegistration = Assert-WeatherIntegrationRegistrationReceipt -AttemptContract $AttemptContract
                $strictBindingSource = "registration_receipt"
            }
            elseif ($null -ne $strictRegistration) {
                throw "Registration receipt lacks the exact task-binding contract recorded by its intent."
            }
        }
        catch {
            if ($null -eq $strictRegistration) {
                throw
            }
            $registrationReceiptError = $_.Exception.Message
            $registrationReceipt = $null
            $strictBindingSource = "pre_registration_intent_receipt_unusable"
        }
    }

    $taskSpecs = @(
        [pscustomobject]@{ name = [string]$manifest.schedule.suite_task_name; role = "suite" },
        [pscustomobject]@{ name = [string]$manifest.schedule.merge_task_name; role = "merge" }
    )
    $taskEvidence = New-Object System.Collections.Generic.List[object]
    # A successful full enumeration is the absence proof. SilentlyContinue on
    # a targeted lookup conflates a missing task with Scheduler/service access
    # failure and could falsely certify rollback while an enabled task remains.
    $schedulerSnapshot = @(Get-WeatherIntegrationScheduledTaskSnapshot)
    foreach ($spec in $taskSpecs) {
        $taskMatches = @($schedulerSnapshot | Where-Object {
            [string]$_.TaskName -ieq [string]$spec.name -and
            [string]$_.TaskPath -ieq "\"
        })
        if ($taskMatches.Count -eq 0) {
            $taskEvidence.Add([ordered]@{ task_name = $spec.name; exists = $false; disabled = $false })
            continue
        }
        if ($taskMatches.Count -ne 1) {
            throw "Refusing to disable ambiguous attempt task name: $($spec.name)"
        }
        $task = $taskMatches[0]
        if ([string]$task.State -notin @("Ready", "Disabled")) {
            # Do not turn an unknown/future Scheduler state into terminal
            # closure evidence.  In particular, disabling an ambiguously
            # observed task could hide a live process while authorizing a
            # successor attempt.
            throw "Attempt task is not provably terminal and may not be disabled: $($spec.name) state=$($task.State)"
        }
        if ($null -eq $registrationReceipt -and $null -eq $strictRegistration) {
            throw "Refusing to disable an existing task without its immutable registration receipt or pre-registration intent: $($spec.name)"
        }
        $registeredAction = $null
        $bindingEvidence = $null
        if ($null -ne $strictRegistration) {
            $bindingEvidence = if ($null -ne $strictRegistration.PSObject.Properties["Intent"]) {
                $strictRegistration.Intent
            }
            else {
                throw "Strict task-closing evidence is missing its registration intent."
            }
            Assert-WeatherIntegrationScheduledTaskBinding `
                -AttemptContract $AttemptContract `
                -Role ([string]$spec.role) `
                -BindingEvidence $bindingEvidence | Out-Null
            if ($null -ne $registrationReceipt) {
                $registeredAction = $registrationReceipt.PSObject.Properties[[string]$spec.role].Value
            }
        }
        else {
            # Backward-compatible close support for attempts registered before
            # exact trigger/settings intents existed. New receipts always take
            # the strict branch above; legacy tasks retain their prior action
            # and S4U/Limited close boundary rather than becoming stranded.
            $registeredActionProperty = $registrationReceipt.PSObject.Properties[[string]$spec.role]
            $registeredAction = if ($null -eq $registeredActionProperty) { $null } else { $registeredActionProperty.Value }
            if ($null -eq $registeredAction -or [string]$registeredAction.task_name -ne [string]$spec.name) {
                throw "Registration receipt does not bind this exact task action: $($spec.name)"
            }
            $actions = @($task.Actions)
            if ($actions.Count -ne 1 -or
                -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].Execute) -Right ([string]$registeredAction.executable)) -or
                [string]$actions[0].Arguments -ne [string]$registeredAction.arguments -or
                -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].WorkingDirectory) -Right ([string]$registeredAction.working_directory)) -or
                [string]$task.Principal.UserId -ne [string]$registrationReceipt.principal.user_id -or
                [string]$task.Principal.LogonType -ne "S4U" -or
                [string]$task.Principal.RunLevel -ne "Limited") {
                throw "Refusing to disable task whose action is not exactly bound to this attempt: $($spec.name)"
            }
        }
        if ([string]$task.State -ne "Disabled") {
            Assert-WeatherIntegrationSchedulerMutationAllowed `
                -CommandName "Disable-ScheduledTask" `
                -Phase "exact integration-task closure"
            if ($null -ne $strictRegistration) {
                Disable-ScheduledTask -TaskName $spec.name -TaskPath "\" -ErrorAction Stop | Out-Null
            }
            else {
                Disable-ScheduledTask -TaskName $spec.name -ErrorAction Stop | Out-Null
            }
        }
        if ($null -ne $strictRegistration) {
            $disabledBinding = Assert-WeatherIntegrationScheduledTaskBinding `
                -AttemptContract $AttemptContract `
                -Role ([string]$spec.role) `
                -BindingEvidence $bindingEvidence
            $disabledTask = $disabledBinding.Task
        }
        else {
            $disabledTask = Get-ScheduledTask -TaskName $spec.name -ErrorAction Stop
        }
        if ([string]$disabledTask.State -ne "Disabled") {
            throw "Attempt task did not enter Disabled state: $($spec.name)"
        }
        $info = if ($null -ne $strictRegistration) {
            Get-ScheduledTaskInfo -TaskName $spec.name -TaskPath "\" -ErrorAction Stop
        }
        else {
            Get-ScheduledTaskInfo -TaskName $spec.name -ErrorAction Stop
        }
        $taskEvidence.Add([ordered]@{
            task_name = $spec.name
            exists = $true
            disabled = $true
            binding_source = if ($null -eq $strictBindingSource) { "legacy_registration_receipt" } else { $strictBindingSource }
            registration_receipt_error = $registrationReceiptError
            registration_receipt_registered = if ($null -eq $registeredAction) { $null } else { [bool]$registeredAction.registered }
            registration_receipt_disagreed = if ($null -eq $registeredAction) { $null } else { -not [bool]$registeredAction.registered }
            last_run_time = if ($null -eq $info) { $null } else { ([datetime]$info.LastRunTime).ToString("o") }
            last_task_result = if ($null -eq $info) { $null } else { [int]$info.LastTaskResult }
        })
    }
    $finalSchedulerSnapshot = @(Get-WeatherIntegrationScheduledTaskSnapshot)
    foreach ($spec in $taskSpecs) {
        $priorEvidence = @($taskEvidence | Where-Object {
            [string]$_.task_name -ceq [string]$spec.name
        })
        if ($priorEvidence.Count -ne 1) {
            throw "Final task terminality proof lost its exact evidence row: $($spec.name)"
        }
        $finalMatches = @($finalSchedulerSnapshot | Where-Object {
            [string]$_.TaskName -ieq [string]$spec.name -and
            [string]$_.TaskPath -ieq "\"
        })
        if ($finalMatches.Count -gt 1) {
            throw "Final task terminality proof found an ambiguous exact task: $($spec.name)"
        }
        if (-not [bool]$priorEvidence[0].exists) {
            if ($finalMatches.Count -ne 0) {
                throw "An exact task appeared after its absence proof: $($spec.name)"
            }
            continue
        }
        if ($finalMatches.Count -ne 1 -or
            [string]$finalMatches[0].State -ne "Disabled") {
            throw "Final task terminality proof did not retain Disabled state: $($spec.name)"
        }
        if ($null -ne $strictRegistration) {
            Assert-WeatherIntegrationScheduledTaskObject `
                -Task $finalMatches[0] `
                -BindingEvidence $strictRegistration.Intent `
                -Role ([string]$spec.role) | Out-Null
        }
    }
    return @($taskEvidence | ForEach-Object { $_ })
}

function Assert-WeatherIntegrationRepairClaimStructure {
    param([Parameter(Mandatory = $true)][object]$AttemptContract)

    $manifest = $AttemptContract.Manifest
    $repairClass = [string]$manifest.authorization.repair_class
    $repairOfProperty = $manifest.authorization.PSObject.Properties["repair_of"]
    $repairOf = if ($null -eq $repairOfProperty) { $null } else { $repairOfProperty.Value }
    if ($null -eq $repairOf) {
        if ($repairClass -ne "initial") {
            throw "A non-initial attempt is missing its predecessor receipt and successor claim."
        }
        return [pscustomobject]@{ Required = $false }
    }
    if ($repairClass -eq "initial") {
        throw "An initial attempt may not carry predecessor repair evidence."
    }
    Assert-WeatherIntegrationRequiredProperties `
        -Object $repairOf `
        -Names @(
            "receipt_path", "receipt_sha256", "receipt_schema",
            "prior_attempt_id", "claim_path", "dispatch_path", "dispatch_sha256"
        ) `
        -Label "Integration successor repair binding"
    if ([string]$repairOf.receipt_schema -ne
            $script:WeatherIntegrationAttemptClosureReceiptSchema -or
        [string]$repairOf.prior_attempt_id -notmatch
            '^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$' -or
        [string]$repairOf.receipt_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$repairOf.dispatch_sha256 -notmatch '^[0-9a-f]{64}$' -or
        (Split-Path -Leaf ([string]$repairOf.receipt_path)) -cne
            "closure-receipt.json" -or
        (Split-Path -Leaf ([string]$repairOf.claim_path)) -cne
            "successor-claim.json" -or
        (Split-Path -Leaf ([string]$repairOf.dispatch_path)) -cne
            "recovery-dispatch.json") {
        throw "Integration successor repair binding is structurally invalid."
    }
    return [pscustomobject]@{ Required = $true; RepairOf = $repairOf }
}

function Assert-WeatherIntegrationRepairClaim {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AttemptContract
    )

    Assert-WeatherIntegrationRepairClaimStructure `
        -AttemptContract $AttemptContract | Out-Null
    $manifest = $AttemptContract.Manifest
    $repairOfProperty = $manifest.authorization.PSObject.Properties["repair_of"]
    $repairOf = if ($null -eq $repairOfProperty) { $null } else { $repairOfProperty.Value }
    if ($null -eq $repairOf) {
        if ([string]$manifest.authorization.repair_class -ne "initial") {
            throw "A non-initial attempt is missing its predecessor receipt and successor claim."
        }
        return
    }
    if ([string]$manifest.authorization.repair_class -eq "initial") {
        throw "An initial attempt may not carry predecessor repair evidence."
    }

    $receiptPath = Resolve-WeatherIntegrationPath -Path ([string]$repairOf.receipt_path)
    $receiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $receiptPath -MaximumBytes 2097152 -ContentType Json
    $receiptSha256 = [string]$receiptSnapshot.Sha256
    if ($receiptSha256 -ne [string]$repairOf.receipt_sha256) {
        throw "The predecessor FAIL receipt changed after the successor was frozen."
    }
    $priorReceipt = $receiptSnapshot.Payload
    if ([string]$priorReceipt.schema -ne $script:WeatherIntegrationAttemptClosureReceiptSchema -or
        [string]$priorReceipt.status -ne "FAIL") {
        throw "A successor attempt must bind an immutable closure FAIL receipt."
    }
    if ([string]$priorReceipt.attempt_id -ne [string]$repairOf.prior_attempt_id) {
        throw "The predecessor closure receipt attempt id does not match the successor manifest."
    }

    $dispatchPath = Resolve-WeatherIntegrationPath -Path ([string]$repairOf.dispatch_path)
    $dispatchSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $dispatchPath -MaximumBytes 2097152 -ContentType Json
    $dispatchSha256 = [string]$dispatchSnapshot.Sha256
    if ($dispatchSha256 -ne [string]$repairOf.dispatch_sha256) {
        throw "The predecessor recovery dispatch changed after the successor was frozen."
    }
    $dispatch = $dispatchSnapshot.Payload
    if ([string]$dispatch.schema -ne $script:WeatherIntegrationAttemptRecoveryDispatchSchema -or
        [string]$dispatch.status -ne "READY_FOR_SUCCESSOR_REVIEW" -or
        [string]$dispatch.repair_class -ne [string]$manifest.authorization.repair_class -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$dispatch.closure_receipt_path) -Right $receiptPath) -or
        [string]$dispatch.closure_receipt_sha256 -ne $receiptSha256) {
        throw "The predecessor recovery dispatch does not authorize this successor."
    }

    $priorManifestPath = Resolve-WeatherIntegrationPath -Path ([string]$priorReceipt.manifest_path)
    $priorManifestSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $priorManifestPath -MaximumBytes 1048576 -ContentType Json
    $priorManifestSha256 = [string]$priorManifestSnapshot.Sha256
    if ($priorManifestSha256 -ne [string]$priorReceipt.manifest_sha256) {
        throw "The predecessor manifest changed after closure."
    }
    $priorManifest = $priorManifestSnapshot.Payload
    $priorAttemptRoot = Resolve-WeatherIntegrationPath -Path ([string]$priorManifest.attempt_root)
    $expectedClaimPath = Join-Path $priorAttemptRoot "successor-claim.json"
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$repairOf.claim_path) -Right $expectedClaimPath)) {
        throw "The successor claim path is not canonical for the predecessor attempt."
    }
    $claimSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $expectedClaimPath -MaximumBytes 2097152 -ContentType Json
    $claim = $claimSnapshot.Payload
    if ([string]$claim.schema -ne $script:WeatherIntegrationAttemptSuccessorClaimSchema -or
        [string]$claim.status -ne "CLAIMED") {
        throw "The predecessor successor claim is unsupported."
    }
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$claim.predecessor_receipt_path) -Right $receiptPath) -or
        [string]$claim.predecessor_receipt_sha256 -ne $receiptSha256 -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$claim.recovery_dispatch_path) -Right $dispatchPath) -or
        [string]$claim.recovery_dispatch_sha256 -ne $dispatchSha256 -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$claim.successor_manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$claim.successor_manifest_sha256 -ne [string]$AttemptContract.ManifestSha256 -or
        [string]$claim.successor_attempt_id -ne [string]$manifest.attempt_id -or
        [string]$claim.successor_expected_tip -ne [string]$manifest.expected_tip -or
        [string]$claim.repair_class -ne [string]$manifest.authorization.repair_class) {
        throw "The predecessor successor claim does not bind this exact successor manifest."
    }
}

function Assert-WeatherIntegrationOrchestrationFiles {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AttemptContract
    )

    $manifest = $AttemptContract.Manifest
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
    $expectedFiles = [ordered]@{
        contract = Join-Path $repoRoot "scripts\ops\integration_attempt_contract.ps1"
        attempt_creator = Join-Path $repoRoot "scripts\ops\new_integration_attempt.ps1"
        attempt_registrar = Join-Path $repoRoot "scripts\ops\register_integration_attempt.ps1"
        attempt_closer = Join-Path $repoRoot "scripts\ops\close_integration_attempt.ps1"
        bounded_suite = Join-Path $repoRoot "scripts\ops\bounded_worktree_test_suite.ps1"
        attempt_suite = Join-Path $repoRoot "scripts\ops\integration_attempt_suite.ps1"
        attempt_merge = Join-Path $repoRoot "scripts\ops\integration_attempt_merge.ps1"
        attempt_success_gate = Join-Path $repoRoot "scripts\ops\assert_integration_attempt_success.ps1"
        attempt_recovery_dispatch = Join-Path $repoRoot "scripts\ops\dispatch_integration_attempt_recovery.ps1"
        boot_recovery = Join-Path $repoRoot "scripts\ops\boot_recovery.ps1"
        register_boot_recovery = Join-Path $repoRoot "scripts\ops\register_boot_recovery.ps1"
        quiet_merge = Join-Path $repoRoot "scripts\ops\quiet_window_merge.ps1"
        token_contract = Join-Path $repoRoot "scripts\ops\training_window_contract.ps1"
        job_containment = Join-Path $repoRoot "scripts\ops\windows_kill_on_close_job.ps1"
        workload_admission = Join-Path $repoRoot "scripts\ops\workload_admission.ps1"
        roll_verdict = Join-Path $repoRoot "scripts\ops\roll_verdict.ps1"
    }
    foreach ($name in $expectedFiles.Keys) {
        $record = $manifest.orchestration.$name
        if ($null -eq $record) {
            throw "Attempt manifest is missing the orchestration binding for $name."
        }
        $expectedPath = [string]$expectedFiles[$name]
        if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$record.path) -Right $expectedPath)) {
            throw "Attempt orchestration path for $name is not canonical."
        }
        $actualSha256 = Get-WeatherIntegrationFileSha256 -Path $expectedPath
        if ($actualSha256 -ne [string]$record.sha256) {
            throw "Attempt orchestration file changed after freeze: $name"
        }
    }
    $quietPreflightProperty = $manifest.orchestration.PSObject.Properties[
        "quiet_merge_preflight"
    ]
    if ($null -ne $quietPreflightProperty) {
        $quietPreflightPath = Join-Path $repoRoot `
            "scripts\ops\integration_attempt_quiet_merge_preflight.ps1"
        $quietPreflightRecord = $quietPreflightProperty.Value
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$quietPreflightRecord.path) `
                -Right $quietPreflightPath) -or
            [string]$quietPreflightRecord.sha256 -ne
                (Get-WeatherIntegrationFileSha256 -Path $quietPreflightPath)) {
            throw "Attempt orchestration file changed after freeze: quiet_merge_preflight"
        }
    }
    $activatorProperty = $manifest.orchestration.PSObject.Properties["attempt_activator"]
    if ($null -ne $activatorProperty) {
        $activatorPath = Join-Path $repoRoot "scripts\ops\activate_integration_attempt.ps1"
        $activatorRecord = $activatorProperty.Value
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$activatorRecord.path) -Right $activatorPath) -or
            [string]$activatorRecord.sha256 -ne
                (Get-WeatherIntegrationFileSha256 -Path $activatorPath)) {
            throw "Attempt orchestration file changed after freeze: attempt_activator"
        }
    }
    $remoteGitProperty = $manifest.orchestration.PSObject.Properties["remote_git"]
    $preparationProperty = $manifest.authorization.PSObject.Properties["preparation"]
    if ($null -eq $remoteGitProperty -and $null -ne $preparationProperty -and
        $null -ne $preparationProperty.Value) {
        throw "A composite integration attempt is missing the remote_git orchestration binding."
    }
    if ($null -ne $remoteGitProperty) {
        $remoteGitPath = Join-Path $repoRoot "scripts\ops\integration_attempt_remote_git.ps1"
        $remoteGitRecord = $remoteGitProperty.Value
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$remoteGitRecord.path) -Right $remoteGitPath) -or
            [string]$remoteGitRecord.sha256 -ne
                (Get-WeatherIntegrationFileSha256 -Path $remoteGitPath)) {
            throw "Attempt orchestration file changed after freeze: remote_git"
        }
    }
}

function Assert-WeatherIntegrationSuiteReceipt {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AttemptContract
    )

    $manifest = $AttemptContract.Manifest
    $receiptPath = [string]$manifest.evidence.suite_receipt
    $receiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $receiptPath -MaximumBytes 2097152 -ContentType Json
    $receipt = $receiptSnapshot.Payload
    if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptSuiteReceiptSchema) {
        throw "Unsupported integration-attempt suite receipt schema: $($receipt.schema)"
    }
    if ([string]$receipt.status -ne "PASS") {
        throw "The integration-attempt suite did not pass. Receipt status: $($receipt.status)"
    }
    if ([string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256) {
        throw "Suite receipt is not bound to the selected manifest hash."
    }
    $registration = Assert-WeatherIntegrationRegistrationReceipt `
        -AttemptContract $AttemptContract `
        -RequirePass
    if ([string]$receipt.registration_receipt_sha256 -ne [string]$registration.ReceiptSha256 -or
        [string]$receipt.registration_intent_sha256 -ne [string]$registration.IntentSha256) {
        throw "Suite receipt does not bind the exact registration receipt and pre-registration intent."
    }
    if ([string]$receipt.expected_tip -ne [string]$manifest.expected_tip) {
        throw "Suite receipt expected tip does not match the manifest."
    }
    if ([string]$receipt.branch_ref -ne [string]$manifest.branch_ref) {
        throw "Suite receipt branch does not match the manifest."
    }
    $originUrlProperty = $manifest.baseline.PSObject.Properties["origin_url"]
    if ($null -ne $originUrlProperty -and
        [string]$receipt.origin_url -cne [string]$originUrlProperty.Value) {
        throw "Suite receipt origin URL does not match the manifest."
    }
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.worktree_root) -Right ([string]$manifest.worktree_root))) {
        throw "Suite receipt worktree does not match the manifest."
    }
    if (-not [bool]$receipt.full_suite_started -or
        [string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "Suite receipt is missing full-suite proof or violates the attempt safety boundary."
    }
    $startedAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.started_at_local) `
        -Label "suite receipt started_at_local"
    $completedAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.completed_at_local) `
        -Label "suite receipt completed_at_local"
    if ($completedAt -lt $startedAt) {
        throw "Suite receipt completion precedes its start."
    }
    if ([string]$manifest.schema -ceq
            $script:WeatherIntegrationAttemptManifestSchema) {
        Assert-WeatherIntegrationRequiredProperties `
            -Object $receipt -Names @("runtime") `
            -Label "v2 suite receipt"
        Assert-WeatherIntegrationRequiredProperties `
            -Object $receipt.runtime -Names @(
                "bounded_suite_max_runtime_seconds",
                "suite_wrapper_teardown_allowance_seconds",
                "suite_task_execution_time_limit_seconds",
                "minimum_phase_runtime_seconds", "shared_deadline_utc",
                "elapsed_seconds"
            ) -Label "v2 suite receipt runtime"
        $sharedDeadline = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
            -Value ([string]$receipt.runtime.shared_deadline_utc) `
            -Label "suite receipt shared_deadline_utc"
        if ([string]$receipt.runtime.shared_deadline_utc -cnotmatch 'Z$' -or
            [int]$receipt.runtime.bounded_suite_max_runtime_seconds -ne
                [int]$manifest.suite.bounded_suite_max_runtime_seconds -or
            [int]$receipt.runtime.suite_wrapper_teardown_allowance_seconds -ne
                [int]$manifest.suite.suite_wrapper_teardown_allowance_seconds -or
            [int]$receipt.runtime.suite_task_execution_time_limit_seconds -ne
                [int]$manifest.suite.suite_task_execution_time_limit_seconds -or
            [int]$receipt.runtime.minimum_phase_runtime_seconds -ne
                [int]$script:WeatherIntegrationSuiteMinimumPhaseRuntimeSeconds -or
            [double]$receipt.runtime.elapsed_seconds -lt 0 -or
            [double]$receipt.runtime.elapsed_seconds -gt
                [double]$manifest.suite.bounded_suite_max_runtime_seconds -or
            $sharedDeadline -lt $startedAt -or
            $completedAt -gt $sharedDeadline -or
            ($completedAt - $startedAt).TotalSeconds -gt
                [double]$manifest.suite.suite_task_execution_time_limit_seconds) {
            throw "V2 suite receipt does not prove the shared runtime and Scheduler execution bounds."
        }
    }

    $logSnapshots = @{}
    $derivedLogVerdicts = @{}
    foreach ($logName in @("preflight", "full_suite")) {
        $logRecord = $receipt.logs.$logName
        if ($null -eq $logRecord) {
            throw "Suite receipt is missing the $logName log binding."
        }
        $logPath = [string]$logRecord.path
        $expectedPath = if ($logName -eq "preflight") { [string]$manifest.evidence.preflight_log } else { [string]$manifest.evidence.full_suite_log }
        if (-not (Test-WeatherIntegrationPathEqual -Left $logPath -Right $expectedPath)) {
            throw "Suite receipt $logName log path does not match the manifest."
        }
        $logSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
            -Path $logPath -MaximumBytes 67108864 -ContentType Text
        $logSnapshots[$logName] = $logSnapshot
        if ([string]$logSnapshot.Sha256 -ne [string]$logRecord.sha256) {
            throw "Suite receipt $logName log hash does not match the current file."
        }
        if ([int]$logRecord.exit_code -ne 0) {
            throw "Suite receipt $logName phase did not exit successfully."
        }
        $validationErrorProperty =
            $logRecord.PSObject.Properties["evidence_validation_error"]
        if ([string]$manifest.schema -ceq
                $script:WeatherIntegrationAttemptManifestSchema -and
            ($null -eq $validationErrorProperty -or
             $null -ne $validationErrorProperty.Value)) {
            throw "Suite receipt $logName has missing or failed evidence validation."
        }
        $derivedVerdict = Get-WeatherIntegrationLogVerdict `
            -Path $logPath -EvidenceSnapshot $logSnapshot
        if ([string]$logRecord.verdict -cne [string]$derivedVerdict) {
            throw "Suite receipt $logName verdict does not match its retained log."
        }
        if ($logName -eq "full_suite") {
            Assert-WeatherIntegrationFullSuiteLogPlan `
                -Path $logPath `
                -ExpectedTestFileCount ([int]$manifest.suite.expected_test_file_count) `
                -ExpectedMaxFilesPerChunk ([int]$manifest.suite.max_files_per_chunk) `
                -ExpectedChunkCount ([int]$manifest.suite.expected_chunk_count) `
                -EvidenceSnapshot $logSnapshot | Out-Null
            $expectedLogChunks = [int]$manifest.suite.expected_chunk_count
            $expectedLogFiles = [int]$manifest.suite.expected_test_file_count
        }
        else {
            # The preflight inventory is owned by the bounded runner. Derive it
            # from this same retained log instead of copying another count into
            # either manifest schema.
            $declaredPlan = Get-WeatherIntegrationSuiteLogDeclaredPlan `
                -Path $logPath -EvidenceSnapshot $logSnapshot
            if ([int]$declaredPlan.MaxFilesPerChunk -ne
                    [int]$manifest.suite.max_files_per_chunk) {
                throw "Suite receipt preflight log changed its bounded chunk size."
            }
            $expectedLogChunks = [int]$declaredPlan.Chunks
            $expectedLogFiles = [int]$declaredPlan.Files
        }
        $testResultsProperty = $logRecord.PSObject.Properties["test_results"]
        if ($null -eq $testResultsProperty) {
            # Historical v1 receipts predate the copied summary. Their retained
            # logs still have to prove their actual verdict and immutable plan,
            # but they cannot be retrofitted with JUnit bindings they never
            # emitted.
            if ([string]$manifest.schema -cne
                    $script:WeatherIntegrationAttemptLegacyManifestSchema) {
                throw "Suite receipt $logName is missing its derived result summary."
            }
        }
        else {
            $derivedSummary = Get-WeatherIntegrationSuiteEvidenceSummary `
                -Path $logPath `
                -ExpectedChunkCount $expectedLogChunks `
                -ExpectedPlannedFiles $expectedLogFiles `
                -EvidenceSnapshot $logSnapshot `
                -RequireRuntimeFingerprint:([string]$manifest.schema -ceq
                    $script:WeatherIntegrationAttemptManifestSchema)
            if ($null -eq $testResultsProperty.Value -or
                ($testResultsProperty.Value | ConvertTo-Json -Depth 20 -Compress) -cne
                    ($derivedSummary | ConvertTo-Json -Depth 20 -Compress)) {
                throw "Suite receipt $logName result summary does not match its retained log/JUnit/inventory evidence."
            }
            if ([string]$manifest.schema -ceq
                    $script:WeatherIntegrationAttemptManifestSchema) {
                Assert-WeatherIntegrationExpectedSuiteInventories `
                    -Summary $derivedSummary `
                    -Expected $manifest.suite `
                    -ExpectedRepoRoot ([string]$manifest.repo_root) `
                    -ExpectedWorktreeRoot ([string]$manifest.worktree_root) `
                    -ExpectedTip ([string]$manifest.expected_tip) `
                    -Label "Suite receipt $logName" `
                    -IncludeTestInventory:($logName -eq "full_suite") | Out-Null
            }
        }
        $derivedLogVerdicts[$logName] = [string]$derivedVerdict
    }
    Assert-WeatherIntegrationPreflightVerdict `
        -Verdict ([string]$derivedLogVerdicts["preflight"])
    Assert-WeatherIntegrationFullSuiteVerdict `
        -Verdict ([string]$derivedLogVerdicts["full_suite"]) `
        -ExpectedChunkCount ([int]$manifest.suite.expected_chunk_count) | Out-Null

    $scriptBindings = [ordered]@{
        bounded_suite = $manifest.orchestration.bounded_suite
        integration_suite = $manifest.orchestration.attempt_suite
    }
    foreach ($scriptName in $scriptBindings.Keys) {
        $manifestScript = $scriptBindings[$scriptName]
        $receiptScript = $receipt.scripts.$scriptName
        if ($null -eq $receiptScript -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$receiptScript.path) -Right ([string]$manifestScript.path)) -or
            [string]$receiptScript.sha256 -ne [string]$manifestScript.sha256) {
            throw "Suite receipt script binding does not match the frozen manifest: $scriptName"
        }
    }

    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = Resolve-WeatherIntegrationPath -Path $receiptPath
        ReceiptSha256 = [string]$receiptSnapshot.Sha256
        StartedAtLocal = $startedAt
        CompletedAtLocal = $completedAt
    }
}

function Assert-WeatherIntegrationQuietReportDocumentation {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][object]$QuietReport
    )

    $manifest = $AttemptContract.Manifest
    $pendingSha256 = ([string]$QuietReport.documentation_transaction_pending_sha256).ToLowerInvariant()
    $snapshotRelative = ([string]$QuietReport.documentation_transaction_snapshot_path).Replace('\', '/')
    $expectedRelative = "data/alerts/documentation_transactions/pending-$pendingSha256.json"
    $snapshotPath = Join-Path ([string]$manifest.repo_root) ($snapshotRelative -replace '/', '\')
    if ($pendingSha256 -notmatch '^[0-9a-f]{64}$' -or
        $snapshotRelative -cne $expectedRelative) {
        throw "Quiet-merge documentation transaction snapshot identity/hash is invalid."
    }
    $documentationSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $snapshotPath -MaximumBytes 2097152 -ContentType Json
    if ([string]$documentationSnapshot.Sha256 -ne $pendingSha256) {
        throw "Quiet-merge documentation transaction snapshot identity/hash is invalid."
    }
    $snapshot = $documentationSnapshot.Payload
    $matchingEntries = @($snapshot.integrations | Where-Object {
        ([string]$_.integration_tip).ToLowerInvariant() -eq
            ([string]$QuietReport.merge_commit).ToLowerInvariant() -and
        [string]$_.branch -ceq [string]$manifest.branch_ref -and
        ([string]$_.expected_tip).ToLowerInvariant() -eq [string]$manifest.expected_tip
    })
    if ([string]$snapshot.schema_version -ne "documentation_transaction_pending_v0.1" -or
        [string]$snapshot.status -ne "PENDING" -or
        ([string]$snapshot.latest_integration_tip).ToLowerInvariant() -ne
            ([string]$QuietReport.merge_commit).ToLowerInvariant() -or
        $matchingEntries.Count -ne 1) {
        throw "Quiet-merge documentation snapshot does not bind the exact merge, branch, and source tip."
    }
    return [pscustomobject]@{
        PendingSha256 = $pendingSha256
        SnapshotPath = Resolve-WeatherIntegrationPath -Path $snapshotPath
    }
}

function Assert-WeatherIntegrationMergeReceipt {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AttemptContract,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedReceiptSha256
    )

    if ($ExpectedReceiptSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Expected merge receipt SHA256 must be exactly 64 hexadecimal characters."
    }
    $manifest = $AttemptContract.Manifest
    $receiptPath = [string]$manifest.evidence.merge_receipt
    $receiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $receiptPath -MaximumBytes 2097152 -ContentType Json
    $actualReceiptSha256 = [string]$receiptSnapshot.Sha256
    if ($actualReceiptSha256 -ne $ExpectedReceiptSha256.ToLowerInvariant()) {
        throw "Merge receipt hash mismatch. Expected $ExpectedReceiptSha256; got $actualReceiptSha256"
    }

    $receipt = $receiptSnapshot.Payload
    if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptMergeReceiptSchema) {
        throw "Unsupported integration-attempt merge receipt schema: $($receipt.schema)"
    }
    if ([string]$receipt.status -ne "PASS") {
        throw "Integration-attempt merge receipt is not PASS: $($receipt.status)"
    }
    $originUrlProperty = $manifest.baseline.PSObject.Properties["origin_url"]
    if ([string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256 -or
        [string]$receipt.source_tip -ne [string]$manifest.expected_tip -or
        [string]$receipt.branch_ref -ne [string]$manifest.branch_ref -or
        ($null -ne $originUrlProperty -and
            [string]$receipt.origin_url -cne [string]$originUrlProperty.Value)) {
        throw "Merge receipt identity does not match the immutable attempt manifest."
    }
    if (-not [bool]$receipt.origin_master_verified -or
        -not [bool]$receipt.source_tip_integrated -or
        -not [bool]$receipt.capture_recovery_proved -or
        -not [bool]$receipt.documentation_transaction_recorded) {
        throw "Merge receipt is missing one or more required integration proofs."
    }
    if ([string]$receipt.production_head -notmatch '^[0-9a-f]{40}$' -or
        [string]$receipt.production_head -ne [string]$receipt.origin_master) {
        throw "Merge receipt does not bind equal production and origin tips."
    }
    if ([string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "Merge receipt violates the no-credential/no-live-exchange boundary."
    }
    foreach ($scriptName in @("attempt_merge", "quiet_merge")) {
        $receiptScript = $receipt.scripts.$scriptName
        $manifestScript = $manifest.orchestration.$scriptName
        if ($null -eq $receiptScript -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$receiptScript.path) -Right ([string]$manifestScript.path)) -or
            [string]$receiptScript.sha256 -ne [string]$manifestScript.sha256) {
            throw "Merge receipt script binding does not match the frozen manifest: $scriptName"
        }
    }

    $quietReportPath = [string]$manifest.evidence.quiet_merge_report
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.quiet_merge_report.path) -Right $quietReportPath)) {
        throw "Merge receipt quiet-report path does not match the attempt manifest."
    }
    $quietReportSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $quietReportPath -MaximumBytes 2097152 -ContentType Json
    $quietReportSha256 = [string]$quietReportSnapshot.Sha256
    if ($quietReportSha256 -ne [string]$receipt.quiet_merge_report.sha256) {
        throw "Immutable quiet-merge report hash does not match the merge receipt."
    }
    $quietReport = $quietReportSnapshot.Payload
    if ([string]$manifest.schema -ceq
            $script:WeatherIntegrationAttemptManifestSchema -and
        (($null -eq $quietReport.PSObject.Properties["authoritative_attempt_report"]) -or
         $quietReport.authoritative_attempt_report -isnot [bool] -or
         -not [bool]$quietReport.authoritative_attempt_report -or
         [string]$quietReport.compatibility_outputs_authority -cne
            "DIAGNOSTIC_ONLY")) {
        throw "Current quiet-merge evidence is not the immutable authoritative attempt report."
    }
    $originUrlProperty = $manifest.baseline.PSObject.Properties["origin_url"]
    if ([string]$quietReport.schema -ne "quiet_window_merge_report_v0.2" -or
        -not [bool]$quietReport.ok -or [string]$quietReport.stage -ne "pushed" -or
        [string]$quietReport.expected_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.expected_baseline -ne [string]$manifest.baseline.master -or
        ($null -ne $originUrlProperty -and
            [string]$quietReport.origin_url -cne [string]$originUrlProperty.Value) -or
        [string]$quietReport.baseline_commit -ne [string]$manifest.baseline.master -or
        [string]$quietReport.resolved_branch_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.branch -ne [string]$manifest.branch_ref -or
        -not [bool]$quietReport.capture_recovery_proved -or
        ([bool]$quietReport.execution_tape_recovery_required -and
            -not [bool]$quietReport.execution_tape_recovery_proved) -or
        -not [bool]$quietReport.publication_acknowledged -or
        -not [bool]$quietReport.documentation_transaction_recorded -or
        [string]$quietReport.merge_commit -ne [string]$receipt.production_head) {
        throw "Immutable quiet-merge report does not prove the frozen source tip was pushed."
    }
    Assert-WeatherIntegrationQuietReportDocumentation `
        -AttemptContract $AttemptContract -QuietReport $quietReport | Out-Null

    $suiteReceiptPath = [string]$manifest.evidence.suite_receipt
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.suite_receipt_path) -Right $suiteReceiptPath)) {
        throw "Merge receipt suite-receipt path does not match the attempt manifest."
    }
    $suiteReceiptSha256 = [string](Read-WeatherIntegrationEvidenceSnapshot `
        -Path $suiteReceiptPath -MaximumBytes 2097152 -ContentType Json).Sha256
    if ($suiteReceiptSha256 -ne [string]$receipt.suite_receipt_sha256) {
        throw "Suite receipt changed after the merge gate consumed it."
    }

    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = Resolve-WeatherIntegrationPath -Path $receiptPath
        ReceiptSha256 = $actualReceiptSha256
        QuietReport = $quietReport
        QuietReportSha256 = $quietReportSha256
    }
}

function Assert-WeatherIntegrationTaskRetirementReceipt {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)]
        [ValidateSet("suite", "merge")][string]$Role
    )

    $receiptPath = Join-Path (
        Resolve-WeatherIntegrationPath -Path $AttemptContract.AttemptRoot
    ) "task-retirement-receipt.json"
    $receiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $receiptPath -MaximumBytes 2097152 -ContentType Json
    $receipt = $receiptSnapshot.Payload
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt `
        -Names @(
            "schema", "status", "classification", "attempt_id",
            "manifest_path", "manifest_sha256", "merge_receipt_path",
            "merge_receipt_sha256", "retired_at_local", "review_reference",
            "confirmation", "pre_disable", "post_disable", "safety"
        ) `
        -Label "Attempt task-retirement receipt"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.safety `
        -Names @(
            "authority", "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) `
        -Label "Attempt task-retirement safety boundary"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt.safety `
        -Names @(
            "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) `
        -Label "Attempt task-retirement safety boundary"
    if ([string]$receipt.schema -ne
            $script:WeatherIntegrationTaskRetirementReceiptSchema -or
        [string]$receipt.status -ne "PASS" -or
        [string]$receipt.classification -ne
            "SUCCESSFUL_ATTEMPT_TASKS_RETIRED" -or
        [string]$receipt.attempt_id -ne
            [string]$AttemptContract.Manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.manifest_path) `
            -Right $AttemptContract.ManifestPath) -or
        [string]$receipt.manifest_sha256 -ne
            [string]$AttemptContract.ManifestSha256 -or
        [string]::IsNullOrWhiteSpace([string]$receipt.review_reference) -or
        [string]$receipt.confirmation -cne
            $script:WeatherIntegrationTaskRetirementConfirmation -or
        [string]$receipt.safety.authority -ne
            "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "Attempt task-retirement receipt does not bind this exact safe retirement."
    }
    ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.retired_at_local) `
        -Label "task-retirement receipt retired_at_local" | Out-Null

    $expectedMergePath = Resolve-WeatherIntegrationPath `
        -Path ([string]$AttemptContract.Manifest.evidence.merge_receipt)
    $mergeSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $expectedMergePath -MaximumBytes 2097152 -ContentType Json
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.merge_receipt_path) `
            -Right $expectedMergePath) -or
        [string]$receipt.merge_receipt_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$mergeSnapshot.Sha256 -ne
            [string]$receipt.merge_receipt_sha256) {
        throw "Attempt task-retirement receipt lost its immutable PASS merge binding."
    }
    $mergeReceipt = $mergeSnapshot.Payload
    if ([string]$mergeReceipt.schema -ne
            $script:WeatherIntegrationAttemptMergeReceiptSchema -or
        [string]$mergeReceipt.status -ne "PASS" -or
        [string]$mergeReceipt.manifest_sha256 -ne
            [string]$AttemptContract.ManifestSha256) {
        throw "Attempt task-retirement receipt does not reference a PASS merge receipt."
    }

    $preRows = @($receipt.pre_disable)
    $postRows = @($receipt.post_disable)
    if ($preRows.Count -ne 2 -or $postRows.Count -ne 2) {
        throw "Attempt task-retirement receipt must prove exactly two task roles."
    }
    foreach ($expectedRole in @("suite", "merge")) {
        $expectedName = if ($expectedRole -eq "suite") {
            [string]$AttemptContract.Manifest.schedule.suite_task_name
        }
        else { [string]$AttemptContract.Manifest.schedule.merge_task_name }
        $pre = @($preRows | Where-Object {
            [string]$_.role -ceq $expectedRole -and
            [string]$_.task_name -ceq $expectedName
        })
        $post = @($postRows | Where-Object {
            [string]$_.task_name -ceq $expectedName
        })
        if ($pre.Count -ne 1 -or $post.Count -ne 1) {
            throw "Attempt task-retirement receipt lost exact $expectedRole task evidence."
        }
        Assert-WeatherIntegrationRequiredProperties `
            -Object $pre[0] `
            -Names @(
                "role", "task_name", "state", "enabled",
                "allow_demand_start", "last_run_time", "last_task_result"
            ) `
            -Label "$expectedRole pre-disable retirement evidence"
        Assert-WeatherIntegrationBooleanProperties `
            -Object $pre[0] -Names @("enabled", "allow_demand_start") `
            -Label "$expectedRole pre-disable retirement evidence"
        Assert-WeatherIntegrationRequiredProperties `
            -Object $post[0] `
            -Names @("task_name", "exists", "disabled", "last_task_result") `
            -Label "$expectedRole post-disable retirement evidence"
        Assert-WeatherIntegrationBooleanProperties `
            -Object $post[0] -Names @("exists", "disabled") `
            -Label "$expectedRole post-disable retirement evidence"
        if ([string]$pre[0].state -notin @("Ready", "Disabled") -or
            [int]$pre[0].last_task_result -ne 0 -or
            -not [bool]$post[0].exists -or
            -not [bool]$post[0].disabled -or
            [int]$post[0].last_task_result -ne 0) {
            throw "Attempt task-retirement receipt does not prove terminal $expectedRole state."
        }
    }

    $expectedCurrentTaskName = if ($Role -eq "suite") {
        [string]$AttemptContract.Manifest.schedule.suite_task_name
    }
    else { [string]$AttemptContract.Manifest.schedule.merge_task_name }
    if ([string]$Task.TaskName -cne $expectedCurrentTaskName -or
        [string]$Task.TaskPath -cne "\" -or
        [string]$Task.State -ne "Disabled" -or
        $null -eq $Task.Settings.PSObject.Properties["Enabled"] -or
        [bool]$Task.Settings.Enabled) {
        throw "Current $Role task is not the exact Disabled retired task."
    }
    $registration = Assert-WeatherIntegrationRegistrationReceipt `
        -AttemptContract $AttemptContract -RequirePass
    Assert-WeatherIntegrationScheduledTaskObject `
        -Task $Task -BindingEvidence $registration.Intent -Role $Role | Out-Null
    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = Resolve-WeatherIntegrationPath -Path $receiptPath
        ReceiptSha256 = [string]$receiptSnapshot.Sha256
    }
}

function Assert-WeatherIntegrationFailClosureReceipt {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [AllowNull()][object]$Task = $null,
        [Parameter(Mandatory = $true)]
        [ValidateSet("suite", "merge")][string]$Role
    )

    $closurePath = Resolve-WeatherIntegrationPath `
        -Path ([string]$AttemptContract.Manifest.evidence.closure_receipt)
    $closureSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $closurePath -MaximumBytes 2097152 -ContentType Json
    $receipt = $closureSnapshot.Payload
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt `
        -Names @(
            "schema", "status", "classification", "attempt_id",
            "manifest_path", "manifest_sha256", "expected_tip",
            "closed_at_local", "reason", "review_reference", "tasks",
            "post_disable_proof", "registration_evidence",
            "preserved_evidence", "safety"
        ) `
        -Label "Integration-attempt FAIL closure receipt"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.post_disable_proof `
        -Names @(
            "tasks_terminal_and_disabled", "merge_head_absent",
            "checked_out_branch", "head", "master", "origin_master",
            "source_in_master", "source_in_origin"
        ) `
        -Label "Integration-attempt FAIL closure proof"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt.post_disable_proof `
        -Names @(
            "tasks_terminal_and_disabled", "merge_head_absent",
            "source_in_master", "source_in_origin"
        ) `
        -Label "Integration-attempt FAIL closure proof"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.registration_evidence `
        -Names @(
            "registration_intent_path", "registration_intent_sha256",
            "registration_receipt_path", "registration_receipt_sha256"
        ) `
        -Label "Integration-attempt FAIL closure registration evidence"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.safety `
        -Names @(
            "authority", "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) `
        -Label "Integration-attempt FAIL closure safety boundary"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt.safety `
        -Names @(
            "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) `
        -Label "Integration-attempt FAIL closure safety boundary"
    $manifest = $AttemptContract.Manifest
    if ([string]$receipt.schema -ne
            $script:WeatherIntegrationAttemptClosureReceiptSchema -or
        [string]$receipt.status -ne "FAIL" -or
        [string]$receipt.classification -ne "ABANDONED" -or
        [string]$receipt.attempt_id -cne [string]$manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.manifest_path) `
            -Right $AttemptContract.ManifestPath) -or
        [string]$receipt.manifest_sha256 -ne
            [string]$AttemptContract.ManifestSha256 -or
        [string]$receipt.expected_tip -ne [string]$manifest.expected_tip -or
        [string]::IsNullOrWhiteSpace([string]$receipt.reason) -or
        [string]::IsNullOrWhiteSpace([string]$receipt.review_reference) -or
        -not [bool]$receipt.post_disable_proof.tasks_terminal_and_disabled -or
        -not [bool]$receipt.post_disable_proof.merge_head_absent -or
        [string]$receipt.post_disable_proof.checked_out_branch -ne "master" -or
        [string]$receipt.post_disable_proof.head -ne
            [string]$manifest.baseline.master -or
        [string]$receipt.post_disable_proof.master -ne
            [string]$manifest.baseline.master -or
        [string]$receipt.post_disable_proof.origin_master -ne
            [string]$manifest.baseline.origin_master -or
        [bool]$receipt.post_disable_proof.source_in_master -or
        [bool]$receipt.post_disable_proof.source_in_origin -or
        [string]$receipt.safety.authority -ne
            "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "FAIL closure receipt does not prove this exact non-integrated attempt."
    }
    ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.closed_at_local) `
        -Label "FAIL closure closed_at_local" | Out-Null

    $taskRows = @($receipt.tasks)
    if ($taskRows.Count -ne 2) {
        throw "FAIL closure receipt must account for exactly two attempt tasks."
    }
    foreach ($expectedRole in @("suite", "merge")) {
        $expectedName = if ($expectedRole -eq "suite") {
            [string]$manifest.schedule.suite_task_name
        }
        else { [string]$manifest.schedule.merge_task_name }
        $rows = @($taskRows | Where-Object {
            [string]$_.task_name -ceq $expectedName
        })
        if ($rows.Count -ne 1) {
            throw "FAIL closure receipt lost exact $expectedRole task accounting."
        }
        Assert-WeatherIntegrationRequiredProperties `
            -Object $rows[0] `
            -Names @("task_name", "exists", "disabled") `
            -Label "$expectedRole FAIL closure task evidence"
        Assert-WeatherIntegrationBooleanProperties `
            -Object $rows[0] -Names @("exists", "disabled") `
            -Label "$expectedRole FAIL closure task evidence"
        if ([bool]$rows[0].exists -ne [bool]$rows[0].disabled) {
            throw "FAIL closure task evidence is not absent or exactly Disabled."
        }
    }

    # Closure can be the recovery authority for a registrar crash after the
    # immutable intent and one task were written but before a usable receipt
    # existed. It also supports a failure immediately after manifest creation,
    # before the registrar's first durable intent write, but only when both
    # exact task rows prove absence and the receipt claims no intent hash.
    $registrationIntentPath = Get-WeatherIntegrationRegistrationIntentPath `
        -AttemptContract $AttemptContract
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.registration_evidence.registration_intent_path) `
            -Right $registrationIntentPath)) {
        throw "FAIL closure receipt uses a non-canonical registration-intent path."
    }
    $registrationIntentExists = Test-Path `
        -LiteralPath $registrationIntentPath -PathType Leaf
    $registrationIntent = $null
    if ($registrationIntentExists) {
        $registrationIntent = Assert-WeatherIntegrationRegistrationIntent `
            -AttemptContract $AttemptContract
        if ([string]$receipt.registration_evidence.registration_intent_sha256 -ne
                [string]$registrationIntent.IntentSha256) {
            throw "FAIL closure receipt lost its immutable registration evidence."
        }
    }
    else {
        if (-not [string]::IsNullOrEmpty(
                [string]$receipt.registration_evidence.registration_intent_sha256
            ) -or
            @($taskRows | Where-Object { [bool]$_.exists }).Count -ne 0) {
            throw "FAIL closure without registration intent must prove both exact tasks absent."
        }
    }
    $registrationReceiptPath = Resolve-WeatherIntegrationPath `
        -Path ([string]$manifest.evidence.registration_receipt)
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$receipt.registration_evidence.registration_receipt_path) `
            -Right $registrationReceiptPath)) {
        throw "FAIL closure receipt uses a non-canonical registration-receipt path."
    }
    $registrationReceiptExists = Test-Path `
        -LiteralPath $registrationReceiptPath -PathType Leaf
    $registrationReceiptSha256 = [string]$receipt.registration_evidence.registration_receipt_sha256
    if ($registrationReceiptExists) {
        if (-not $registrationIntentExists -or
            $registrationReceiptSha256 -notmatch '^[0-9a-f]{64}$' -or
            (Get-WeatherIntegrationFileSha256 -Path $registrationReceiptPath) -ne
                $registrationReceiptSha256) {
            throw "FAIL closure receipt lost its preserved registrar output."
        }
    }
    elseif (-not [string]::IsNullOrEmpty($registrationReceiptSha256)) {
        throw "FAIL closure claims a registration receipt that is absent."
    }
    $preserved = @($receipt.preserved_evidence)
    if ($preserved.Count -lt 1 -and
        ($registrationIntentExists -or $registrationReceiptExists -or
            @($taskRows | Where-Object { [bool]$_.exists }).Count -ne 0)) {
        throw "FAIL closure receipt has no complete preserved-evidence set."
    }
    foreach ($row in $preserved) {
        Assert-WeatherIntegrationRequiredProperties `
            -Object $row -Names @("path", "sha256") `
            -Label "FAIL closure preserved evidence"
        if ([string]$row.sha256 -notmatch '^[0-9a-f]{64}$' -or
            (Get-WeatherIntegrationFileSha256 -Path ([string]$row.path)) -ne
                [string]$row.sha256) {
            throw "FAIL closure preserved evidence changed: $($row.path)"
        }
    }
    $requiredPreservedEvidence = @()
    if ($registrationIntentExists) {
        $requiredPreservedEvidence += [pscustomobject]@{
            Path = $registrationIntent.IntentPath
            Sha256 = $registrationIntent.IntentSha256
        }
    }
    if ($registrationReceiptExists) {
        $requiredPreservedEvidence += [pscustomobject]@{
            Path = $registrationReceiptPath
            Sha256 = $registrationReceiptSha256
        }
    }
    foreach ($required in $requiredPreservedEvidence) {
        $matches = @($preserved | Where-Object {
            (Test-WeatherIntegrationPathEqual `
                -Left ([string]$_.path) -Right $required.Path) -and
            [string]$_.sha256 -eq [string]$required.Sha256
        })
        if ($matches.Count -ne 1) {
            throw "FAIL closure did not preserve exact registration evidence."
        }
    }

    $expectedCurrentTaskName = if ($Role -eq "suite") {
        [string]$manifest.schedule.suite_task_name
    }
    else { [string]$manifest.schedule.merge_task_name }
    $currentRow = @($taskRows | Where-Object {
        [string]$_.task_name -ceq $expectedCurrentTaskName
    })
    if ($currentRow.Count -ne 1) {
        throw "FAIL closure receipt lost exact $Role task accounting."
    }
    if (-not [bool]$currentRow[0].exists) {
        if ($null -ne $Task) {
            throw "Current task appeared after the FAIL closure proved exact absence."
        }
    }
    else {
        if ($null -eq $Task -or
            -not [bool]$currentRow[0].disabled -or
            [string]$Task.TaskName -cne $expectedCurrentTaskName -or
            [string]$Task.TaskPath -cne "\" -or
            [string]$Task.State -ne "Disabled" -or
            $null -eq $Task.Settings.PSObject.Properties["Enabled"] -or
            [bool]$Task.Settings.Enabled) {
            throw "Current task does not match the exact Disabled FAIL closure evidence."
        }
        if ($null -eq $registrationIntent) {
            throw "A present FAIL-closed task has no immutable registration intent."
        }
        Assert-WeatherIntegrationScheduledTaskObject `
            -Task $Task -BindingEvidence $registrationIntent.Intent -Role $Role | Out-Null
    }
    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = $closurePath
        ReceiptSha256 = [string]$closureSnapshot.Sha256
    }
}

function Assert-WeatherIntegrationCurrentFailClosure {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract
    )

    $manifest = $AttemptContract.Manifest
    # One complete successful inventory is the shared observation for both
    # roles. It distinguishes exact absence from Scheduler/service failure and
    # prevents the two role checks from certifying different points in time.
    $schedulerSnapshot = @(Get-WeatherIntegrationScheduledTaskSnapshot)
    $proofs = [ordered]@{}
    foreach ($role in @("suite", "merge")) {
        $taskName = if ($role -eq "suite") {
            [string]$manifest.schedule.suite_task_name
        }
        else { [string]$manifest.schedule.merge_task_name }
        $matches = @($schedulerSnapshot | Where-Object {
            [string]$_.TaskName -ieq $taskName -and
            [string]$_.TaskPath -ieq "\"
        })
        if ($matches.Count -gt 1) {
            throw "Predecessor $role task lookup is ambiguous in the current Scheduler snapshot."
        }
        $proofs[$role] = Assert-WeatherIntegrationFailClosureReceipt `
            -AttemptContract $AttemptContract `
            -Task $(if ($matches.Count -eq 1) { $matches[0] } else { $null }) `
            -Role $role
    }
    if ([string]$proofs.suite.ReceiptSha256 -ne
            [string]$proofs.merge.ReceiptSha256) {
        throw "Predecessor task roles do not bind one exact FAIL closure receipt."
    }
    return [pscustomobject]@{
        Suite = $proofs.suite
        Merge = $proofs.merge
    }
}

function Assert-WeatherLegacyBootstrapRetirementReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][object]$Task
    )

    $taskName = [string]$Task.TaskName
    if ($taskName -cnotin @(
            "WeatherIntegrationRecoveryBootstrapSuiteFixed0822",
            "WeatherIntegrationRecoveryBootstrapMergeFixed0822"
        ) -or
        [string]$Task.TaskPath -cne "\" -or
        [string]$Task.State -ne "Disabled" -or
        $null -eq $Task.Settings.PSObject.Properties["Enabled"] -or
        [bool]$Task.Settings.Enabled) {
        throw "Legacy retirement evidence requires one exact Disabled bootstrap task."
    }
    $repoRoot = Resolve-WeatherIntegrationPath -Path $RepositoryRoot
    $receiptPath = Join-Path $repoRoot (
        "data\integration_attempts\legacy-task-retirements\$taskName.json"
    )
    $receiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $receiptPath -MaximumBytes 2097152 -ContentType Json
    $receipt = $receiptSnapshot.Payload
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt `
        -Names @(
            "schema", "status", "classification", "task_name",
            "task_xml_sha256", "trigger_at", "last_run_time",
            "last_task_result", "retired_at_local", "review_reference",
            "confirmation", "state", "enabled", "safety"
        ) `
        -Label "Legacy bootstrap task-retirement receipt"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt -Names @("enabled") `
        -Label "Legacy bootstrap task-retirement receipt"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.safety `
        -Names @(
            "authority", "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) `
        -Label "Legacy bootstrap task-retirement safety boundary"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt.safety `
        -Names @(
            "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) `
        -Label "Legacy bootstrap task-retirement safety boundary"
    if ([string]$receipt.schema -ne
            $script:WeatherLegacyBootstrapRetirementSchema -or
        [string]$receipt.status -ne "PASS" -or
        [string]$receipt.classification -ne
            "EXPIRED_LEGACY_BOOTSTRAP_TASK_RETIRED" -or
        [string]$receipt.task_name -cne $taskName -or
        [string]$receipt.task_xml_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$receipt.state -ne "Disabled" -or
        [bool]$receipt.enabled -or
        [string]::IsNullOrWhiteSpace([string]$receipt.review_reference) -or
        [string]$receipt.confirmation -cne
            $script:WeatherLegacyBootstrapRetirementConfirmation -or
        [string]$receipt.safety.authority -ne
            "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "Legacy bootstrap task-retirement receipt is not exact and safe."
    }
    $receiptTrigger = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.trigger_at) -Label "legacy retirement trigger_at"
    $receiptLastRun = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.last_run_time) -Label "legacy retirement last_run_time"
    ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.retired_at_local) `
        -Label "legacy retirement retired_at_local" | Out-Null
    $xml = Export-ScheduledTask `
        -TaskName $taskName -TaskPath "\" -ErrorAction Stop
    if ((Get-WeatherLegacyBootstrapTaskXmlSha256 -Xml $xml) -ne
        [string]$receipt.task_xml_sha256) {
        throw "Legacy bootstrap task changed after its retirement receipt."
    }
    $info = Get-ScheduledTaskInfo `
        -TaskName $taskName -TaskPath "\" -ErrorAction Stop
    if ([datetime]$info.LastRunTime -ne $receiptLastRun.LocalDateTime -or
        [int]$info.LastTaskResult -ne [int]$receipt.last_task_result) {
        throw "Legacy bootstrap task terminal result changed after retirement."
    }
    $triggers = @($Task.Triggers)
    if ($triggers.Count -ne 1) {
        throw "Legacy bootstrap retired task no longer has one exact trigger."
    }
    try { $taskTrigger = [DateTimeOffset]::Parse([string]$triggers[0].StartBoundary) }
    catch { throw "Legacy bootstrap retired task trigger is unreadable." }
    if ($taskTrigger -ne $receiptTrigger -or $taskTrigger -ge [DateTimeOffset]::Now) {
        throw "Legacy bootstrap retired task trigger disagrees with its receipt."
    }
    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = Resolve-WeatherIntegrationPath -Path $receiptPath
        ReceiptSha256 = [string]$receiptSnapshot.Sha256
    }
}

function Assert-WeatherIntegrationMergedUnverifiedReceipt {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$ExpectedReceiptSha256
    )

    if ($ExpectedReceiptSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Expected merge receipt SHA256 must be exactly 64 hexadecimal characters."
    }
    $manifest = $AttemptContract.Manifest
    $receiptPath = [string]$manifest.evidence.merge_receipt
    $receiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $receiptPath -MaximumBytes 2097152 -ContentType Json
    $actualReceiptSha256 = [string]$receiptSnapshot.Sha256
    if ($actualReceiptSha256 -ne $ExpectedReceiptSha256.ToLowerInvariant()) {
        throw "Merge receipt hash mismatch. Expected $ExpectedReceiptSha256; got $actualReceiptSha256"
    }
    $receipt = $receiptSnapshot.Payload
    if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptMergeReceiptSchema -or
        [string]$receipt.status -ne "MERGED_UNVERIFIED") {
        throw "Reconciliation requires an immutable MERGED_UNVERIFIED merge receipt."
    }
    if ([string]$receipt.attempt_id -ne [string]$manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256 -or
        [string]$receipt.source_tip -ne [string]$manifest.expected_tip -or
        [string]$receipt.branch_ref -ne [string]$manifest.branch_ref -or
        -not [bool]$receipt.origin_master_verified -or
        -not [bool]$receipt.source_tip_integrated) {
        throw "MERGED_UNVERIFIED receipt does not prove this exact attempt reached production."
    }
    if ([string]$receipt.production_head -notmatch '^[0-9a-f]{40}$' -or
        [string]$receipt.production_head -ne [string]$receipt.origin_master) {
        throw "MERGED_UNVERIFIED receipt does not bind equal published production and origin tips."
    }
    if ([string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "MERGED_UNVERIFIED receipt violates the no-credential/no-live-exchange boundary."
    }
    foreach ($scriptName in @("attempt_merge", "quiet_merge")) {
        $receiptScript = $receipt.scripts.$scriptName
        $manifestScript = $manifest.orchestration.$scriptName
        if ($null -eq $receiptScript -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$receiptScript.path) -Right ([string]$manifestScript.path)) -or
            [string]$receiptScript.sha256 -ne [string]$manifestScript.sha256) {
            throw "MERGED_UNVERIFIED receipt script binding does not match the frozen manifest: $scriptName"
        }
    }

    $quietReportPath = [string]$manifest.evidence.quiet_merge_report
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.quiet_merge_report.path) -Right $quietReportPath)) {
        throw "MERGED_UNVERIFIED receipt quiet-report path does not match the attempt manifest."
    }
    $quietReportSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $quietReportPath -MaximumBytes 2097152 -ContentType Json
    $quietReportSha256 = [string]$quietReportSnapshot.Sha256
    if ($quietReportSha256 -ne [string]$receipt.quiet_merge_report.sha256) {
        throw "Immutable quiet-merge report hash does not match the MERGED_UNVERIFIED receipt."
    }
    $quietReport = $quietReportSnapshot.Payload
    if ([string]$manifest.schema -ceq
            $script:WeatherIntegrationAttemptManifestSchema -and
        (($null -eq $quietReport.PSObject.Properties["authoritative_attempt_report"]) -or
         $quietReport.authoritative_attempt_report -isnot [bool] -or
         -not [bool]$quietReport.authoritative_attempt_report -or
         [string]$quietReport.compatibility_outputs_authority -cne
            "DIAGNOSTIC_ONLY")) {
        throw "Current MERGED_UNVERIFIED evidence is not the immutable authoritative attempt report."
    }
    if ([string]$quietReport.schema -ne "quiet_window_merge_report_v0.2" -or
        -not [bool]$quietReport.ok -or [string]$quietReport.stage -ne "pushed" -or
        [string]$quietReport.expected_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.expected_baseline -ne [string]$manifest.baseline.master -or
        [string]$quietReport.baseline_commit -ne [string]$manifest.baseline.master -or
        [string]$quietReport.resolved_branch_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.branch -ne [string]$manifest.branch_ref -or
        -not [bool]$quietReport.capture_recovery_proved -or
        ([bool]$quietReport.execution_tape_recovery_required -and
            -not [bool]$quietReport.execution_tape_recovery_proved) -or
        -not [bool]$quietReport.publication_acknowledged -or
        -not [bool]$quietReport.documentation_transaction_recorded -or
        [string]$quietReport.merge_commit -ne [string]$receipt.production_head) {
        throw "Immutable quiet-merge report does not prove the MERGED_UNVERIFIED publication."
    }
    Assert-WeatherIntegrationQuietReportDocumentation `
        -AttemptContract $AttemptContract -QuietReport $quietReport | Out-Null
    $suiteReceiptPath = [string]$manifest.evidence.suite_receipt
    $suiteReceiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $suiteReceiptPath -MaximumBytes 2097152 -ContentType Json
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.suite_receipt_path) -Right $suiteReceiptPath) -or
        [string]$suiteReceiptSnapshot.Sha256 -ne [string]$receipt.suite_receipt_sha256) {
        throw "Suite receipt changed after the MERGED_UNVERIFIED merge consumed it."
    }

    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = Resolve-WeatherIntegrationPath -Path $receiptPath
        ReceiptSha256 = $actualReceiptSha256
        QuietReport = $quietReport
        QuietReportSha256 = $quietReportSha256
    }
}
