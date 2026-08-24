param(
    [ValidateSet("Assert", "Inspect", "InspectActive", "InspectAuto")]
    [string]$Mode = "Assert",

    [Alias("ReadinessManifestPath")]
    [string]$ManifestPath = "",

    [Alias("ExpectedReadinessManifestSha256")]
    [ValidatePattern("^$|^[0-9a-fA-F]{64}$")]
    [string]$ExpectedManifestSha256 = "",

    [switch]$LibraryOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:OneShotReadinessManifestSchema = "weather_one_shot_readiness_manifest_v0.4"
$script:OneShotReadinessResultSchema = "weather_one_shot_readiness_result_v0.1"
$script:OneShotReadinessMaximumManifestBytes = 64KB
$script:OneShotReadinessMaximumDependencyBytes = 4MB
$script:OneShotReadinessMaximumDependencyCount = 32
$script:OneShotReadinessMaximumAggregateDependencyBytes = 8MB
$script:OneShotReadinessManifestPathToken = "{READINESS_MANIFEST_PATH}"
$script:OneShotReadinessManifestHashToken = "{EXPECTED_READINESS_MANIFEST_SHA256}"
$script:OneShotReadinessExecutionWindow = [TimeSpan]::FromMinutes(10)
$script:OneShotReadinessScriptPath = [IO.Path]::GetFullPath($PSCommandPath)
$script:OneShotReadinessRepositoryRoot = [IO.Path]::GetFullPath(
    (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)
$script:OneShotWorkloadAdmissionPath = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "workload_admission.ps1")
)
$script:OneShotGuardedLauncherPath = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "one_shot_guarded_launcher.ps1")
)
$script:OneShotPowerShellExecutablePath = [IO.Path]::GetFullPath(
    (Join-Path $PSHOME "powershell.exe")
)
$script:OneShotKillOnCloseJobPath = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1")
)
$script:OneShotReadinessRegistryRoot = [IO.Path]::GetFullPath(
    (Join-Path $script:OneShotReadinessRepositoryRoot `
        "data\one_shot_readiness\active")
)
$script:OneShotReadinessActivationMarkerPath = [IO.Path]::GetFullPath(
    (Join-Path $script:OneShotReadinessRepositoryRoot `
        "one_shot_registry_activation.json")
)
$script:OneShotReadinessActivationIntentPath = [IO.Path]::GetFullPath(
    (Join-Path $script:OneShotReadinessRepositoryRoot `
        "one_shot_registry_activation_intent.json")
)
$script:OneShotReadinessActivationRecoveryPath = [IO.Path]::GetFullPath(
    (Join-Path $script:OneShotReadinessRepositoryRoot `
        "one_shot_registry_activation_recovery.json")
)
$script:OneShotReadinessRegistryLockPath = [IO.Path]::GetFullPath(
    (Join-Path $script:OneShotReadinessRepositoryRoot `
        "one_shot_registry.lock")
)
$script:OneShotRegistryIndexRoot = [IO.Path]::GetFullPath(
    (Join-Path $script:OneShotReadinessRepositoryRoot `
        "one_shot_registry_index")
)
$script:OneShotReadinessRequireActivationMarker = $true
$script:OneShotReadinessSchedulerTimeZone = [TimeZoneInfo]::Local

function New-WeatherOneShotReadinessBlocker {
    param(
        [Parameter(Mandatory = $true)][string]$Code,
        [Parameter(Mandatory = $true)][string]$Detail,
        [AllowNull()][string]$Subject = $null,
        [AllowNull()][string]$Expected = $null,
        [AllowNull()][string]$Actual = $null
    )

    return [pscustomobject][ordered]@{
        code = $Code
        detail = $Detail
        subject = $Subject
        expected = $Expected
        actual = $Actual
    }
}

function Throw-WeatherOneShotReadinessError {
    param(
        [Parameter(Mandatory = $true)][string]$Code,
        [Parameter(Mandatory = $true)][string]$Message
    )

    $exception = [InvalidOperationException]::new($Message)
    $exception.Data["weather_one_shot_readiness_blocker_code"] = $Code
    throw $exception
}

function Test-WeatherOneShotExactPropertySet {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$ExpectedNames
    )

    if ($null -eq $Value) {
        return $false
    }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if ($actual.Count -ne $expected.Count) {
        return $false
    }
    return @(Compare-Object -ReferenceObject $expected -DifferenceObject $actual).Count -eq 0
}

function Get-WeatherOneShotPropertyValue {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($null -eq $Value) {
        return $null
    }
    $property = $Value.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function ConvertTo-WeatherOneShotTaskPath {
    param([AllowNull()][string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return "\"
    }
    $normalized = $Value.Replace("/", "\")
    if (-not $normalized.StartsWith("\", [StringComparison]::Ordinal)) {
        $normalized = "\" + $normalized
    }
    if (-not $normalized.EndsWith("\", [StringComparison]::Ordinal)) {
        $normalized += "\"
    }
    return $normalized
}

function ConvertTo-WeatherOneShotFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith("\\", [StringComparison]::Ordinal)) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness paths must be absolute local paths."
    }
    try {
        return [IO.Path]::GetFullPath($Path)
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness manifest contains an invalid path."
    }
}

function ConvertTo-WeatherOneShotInstant {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$FieldName,
        [switch]$RequireUtc
    )

    $suffixPattern = if ($RequireUtc) { "Z$" } else { "(?:Z|[+-][0-9]{2}:[0-9]{2})$" }
    if ($Value -notmatch $suffixPattern) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "$FieldName must carry an explicit time-zone offset."
    }
    try {
        return [DateTimeOffset]::Parse(
            $Value,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "$FieldName is not a valid timestamp."
    }
}

function ConvertTo-WeatherOneShotUtcText {
    param([Parameter(Mandatory = $true)][DateTimeOffset]$Value)

    return $Value.UtcDateTime.ToString(
        "o",
        [Globalization.CultureInfo]::InvariantCulture
    )
}

function Assert-WeatherOneShotHostLocalInstant {
    param(
        [Parameter(Mandatory = $true)][DateTimeOffset]$Value,
        [Parameter(Mandatory = $true)][string]$FieldName
    )

    $expectedOffset = $script:OneShotReadinessSchedulerTimeZone.GetUtcOffset($Value)
    $localWallClock = [DateTime]::SpecifyKind(
        $Value.DateTime,
        [DateTimeKind]::Unspecified
    )
    if ($script:OneShotReadinessSchedulerTimeZone.IsInvalidTime($localWallClock) -or
        $script:OneShotReadinessSchedulerTimeZone.IsAmbiguousTime($localWallClock)) {
        Throw-WeatherOneShotReadinessError `
            -Code "TASK_LOCAL_TIME_INVALID" `
            -Message "$FieldName is an invalid or ambiguous host-local wall-clock time."
    }
    if ($Value.Offset -ne $expectedOffset) {
        Throw-WeatherOneShotReadinessError `
            -Code "TASK_LOCAL_OFFSET_MISMATCH" `
            -Message "$FieldName does not use the host's local UTC offset at that instant."
    }
    return [TimeZoneInfo]::ConvertTime(
        $Value,
        $script:OneShotReadinessSchedulerTimeZone
    )
}

function Get-WeatherOneShotBytesSha256 {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $algorithm.ComputeHash($Bytes)
    }
    finally {
        $algorithm.Dispose()
    }
    return -join @($digest | ForEach-Object { $_.ToString("x2") })
}

function Read-WeatherOneShotRegularFileSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][long]$MaximumBytes,
        [Parameter(Mandatory = $true)][string]$UnavailableCode,
        [Parameter(Mandatory = $true)][string]$UnsafeCode,
        [Parameter(Mandatory = $true)][string]$TooLargeCode,
        [Parameter(Mandatory = $true)][string]$Label
    )

    try {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code $UnavailableCode `
            -Message "$Label is unavailable."
    }
    if ($item.PSIsContainer -or
        (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        Throw-WeatherOneShotReadinessError `
            -Code $UnsafeCode `
            -Message "$Label is not a regular non-reparse file."
    }

    $stream = $null
    try {
        $stream = [IO.FileStream]::new(
            $item.FullName,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        if ($stream.Length -le 0) {
            Throw-WeatherOneShotReadinessError `
                -Code $UnsafeCode `
                -Message "$Label is empty."
        }
        if ($stream.Length -gt $MaximumBytes) {
            Throw-WeatherOneShotReadinessError `
                -Code $TooLargeCode `
                -Message "$Label exceeds its bounded size contract."
        }
        $bytes = New-Object byte[] ([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $read = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($read -le 0) {
                Throw-WeatherOneShotReadinessError `
                    -Code $UnavailableCode `
                    -Message "$Label could not be read completely."
            }
            $offset += $read
        }
    }
    catch {
        if ($_.Exception.Data.Contains("weather_one_shot_readiness_blocker_code")) {
            throw
        }
        Throw-WeatherOneShotReadinessError `
            -Code $UnavailableCode `
            -Message "$Label could not be opened as one stable read snapshot."
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }

    return [pscustomobject][ordered]@{
        full_name = [string]$item.FullName
        length = [long]$bytes.Length
        bytes = $bytes
        sha256 = Get-WeatherOneShotBytesSha256 -Bytes $bytes
    }
}

function Enter-WeatherOneShotDependencyLeaseSet {
    param(
        [Parameter(Mandatory = $true)][object]$ManifestContract
    )

    # Readiness snapshots prove what existed at one instant. Execution needs a
    # stronger boundary: keep handles that deny write/delete from the final
    # hash through payload teardown, so the child cannot reopen different bytes.
    $leases = New-Object System.Collections.Generic.List[IO.FileStream]
    $currentStream = $null
    [long]$aggregateBytes = 0
    try {
        $dependencies = @(
            @($ManifestContract.Manifest.dependencies) |
                Sort-Object { ([string]$_.path).ToLowerInvariant() }
        )
        if ($dependencies.Count -le 0 -or
            $dependencies.Count -gt $script:OneShotReadinessMaximumDependencyCount) {
            Throw-WeatherOneShotReadinessError `
                -Code "INVALID_MANIFEST" `
                -Message "Execution dependency lease count is outside its manifest bound."
        }
        foreach ($dependency in $dependencies) {
            $path = [IO.Path]::GetFullPath([string]$dependency.path)
            try {
                $currentStream = [IO.FileStream]::new(
                    $path,
                    [IO.FileMode]::Open,
                    [IO.FileAccess]::Read,
                    [IO.FileShare]::Read
                )
                $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
            }
            catch {
                Throw-WeatherOneShotReadinessError `
                    -Code "DEPENDENCY_UNAVAILABLE" `
                    -Message "Manifest-bound dependency could not be leased for execution."
            }
            if ($item.PSIsContainer -or
                (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
                Throw-WeatherOneShotReadinessError `
                    -Code "DEPENDENCY_UNSAFE_PATH" `
                    -Message "Manifest-bound execution dependency is not a regular non-reparse file."
            }
            if ($currentStream.Length -le 0) {
                Throw-WeatherOneShotReadinessError `
                    -Code "DEPENDENCY_UNSAFE_PATH" `
                    -Message "Manifest-bound execution dependency is empty."
            }
            if ($currentStream.Length -gt
                $script:OneShotReadinessMaximumDependencyBytes) {
                Throw-WeatherOneShotReadinessError `
                    -Code "DEPENDENCY_TOO_LARGE" `
                    -Message "Manifest-bound execution dependency exceeds its size bound."
            }
            $aggregateBytes += [long]$currentStream.Length
            if ($aggregateBytes -gt
                $script:OneShotReadinessMaximumAggregateDependencyBytes) {
                Throw-WeatherOneShotReadinessError `
                    -Code "DEPENDENCY_AGGREGATE_TOO_LARGE" `
                    -Message "Manifest-bound execution dependencies exceed their aggregate bound."
            }
            $algorithm = [Security.Cryptography.SHA256]::Create()
            try {
                $digest = $algorithm.ComputeHash($currentStream)
            }
            finally {
                $algorithm.Dispose()
            }
            $actualSha256 = -join @(
                $digest | ForEach-Object { $_.ToString("x2") }
            )
            if ($actualSha256 -cne [string]$dependency.sha256) {
                Throw-WeatherOneShotReadinessError `
                    -Code "STALE_DEPENDENCY_HASH" `
                    -Message "A manifest-bound dependency changed before its execution lease was acquired."
            }
            $leases.Add($currentStream)
            $currentStream = $null
        }
        return [pscustomobject][ordered]@{
            Streams = $leases
            Count = $leases.Count
            AggregateBytes = $aggregateBytes
        }
    }
    catch {
        if ($null -ne $currentStream) {
            $currentStream.Dispose()
        }
        for ($index = $leases.Count - 1; $index -ge 0; $index--) {
            $leases[$index].Dispose()
        }
        throw
    }
}

function Exit-WeatherOneShotDependencyLeaseSet {
    param([AllowNull()][object]$LeaseSet)

    if ($null -eq $LeaseSet) { return }
    $streams = @($LeaseSet.Streams)
    for ($index = $streams.Count - 1; $index -ge 0; $index--) {
        if ($null -ne $streams[$index]) {
            $streams[$index].Dispose()
        }
    }
}

function Remove-WeatherOneShotExactAtomicDebris {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][byte[]]$ExpectedBytes
    )

    $directory = [IO.Path]::GetFullPath((Split-Path -Parent $Destination))
    $leaf = [IO.Path]::GetFileName($Destination)
    $pattern = '^\.' + [regex]::Escape($leaf) + '\.[0-9a-f]{32}\.tmp$'
    $candidates = @(
        Get-ChildItem -LiteralPath $directory -Force -File -ErrorAction Stop |
            Where-Object { [string]$_.Name -cmatch $pattern }
    )
    if ($candidates.Count -gt 16) {
        throw "Atomic publication has more than 16 exact-name crash remnants; reviewed reconciliation is required."
    }
    foreach ($candidate in $candidates) {
        if (($candidate.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Atomic publication crash remnant is a reparse point; reviewed reconciliation is required."
        }
        # A strict destination+GUID temp is never an authority record. The
        # caller holds the registry's exclusive lock, so no live writer can
        # own it. Partial, empty, or timestamped crash remnants are all safe
        # to remove before retrying the exact create-only destination.
        [IO.File]::Delete([string]$candidate.FullName)
        if (Test-Path -LiteralPath ([string]$candidate.FullName) -ErrorAction Stop) {
            throw "Exact atomic publication crash remnant could not be removed."
        }
    }
}

function Write-WeatherOneShotIndexCreateOnlyFile {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][byte[]]$Bytes
    )

    Remove-WeatherOneShotExactAtomicDebris `
        -Destination $Destination -ExpectedBytes $Bytes
    $temporary = Join-Path (Split-Path -Parent $Destination) (
        ".{0}.{1}.tmp" -f [IO.Path]::GetFileName($Destination),
            [guid]::NewGuid().ToString("N")
    )
    $stream = $null
    $moved = $false
    try {
        $stream = [IO.FileStream]::new(
            $temporary, [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write, [IO.FileShare]::None
        )
        $stream.Write($Bytes, 0, $Bytes.Length)
        $stream.Flush($true)
        $stream.Dispose()
        $stream = $null
        [IO.File]::Move($temporary, $Destination)
        $moved = $true
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
        if (-not $moved -and [IO.File]::Exists($temporary)) {
            [IO.File]::Delete($temporary)
        }
    }
}

function Assert-WeatherOneShotRegistryIndexDirectory {
    param([switch]$Create)

    if ($Create -and -not (Test-Path -LiteralPath $script:OneShotRegistryIndexRoot)) {
        New-Item -ItemType Directory -Path $script:OneShotRegistryIndexRoot `
            -ErrorAction Stop | Out-Null
    }
    $item = Get-Item -LiteralPath $script:OneShotRegistryIndexRoot `
        -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "One-shot registry index must be a regular non-reparse directory."
    }
    Assert-WeatherOneShotNonReparseDirectoryTree `
        -Path ([string]$item.FullName) `
        -StopPath $script:OneShotReadinessRepositoryRoot
}

function Get-WeatherOneShotManifestIndexEventPath {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$ManifestSha256
    )
    return Join-Path $script:OneShotRegistryIndexRoot `
        "manifest.$TaskName.$ManifestSha256.json"
}

function Get-WeatherOneShotResolutionIndexEventPath {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$ManifestSha256
    )
    return Join-Path $script:OneShotRegistryIndexRoot `
        "resolution.$TaskName.$ManifestSha256.json"
}

function Read-WeatherOneShotIndexJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $snapshot = Read-WeatherOneShotRegularFileSnapshot `
        -Path $Path -MaximumBytes 64KB `
        -UnavailableCode "REGISTRY_INDEX_INVALID" `
        -UnsafeCode "REGISTRY_INDEX_INVALID" `
        -TooLargeCode "REGISTRY_INDEX_INVALID" -Label $Label
    try {
        return [Text.UTF8Encoding]::new($false, $true).GetString(
            [byte[]]$snapshot.bytes
        ) | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_INDEX_INVALID" `
            -Message "$Label is not valid bounded UTF-8 JSON."
    }
}

function Assert-WeatherOneShotManifestIndexEvent {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ManifestSha256,
        [Parameter(Mandatory = $true)][string]$TaskName
    )
    Assert-WeatherOneShotRegistryIndexDirectory
    $eventPath = Get-WeatherOneShotManifestIndexEventPath `
        -TaskName $TaskName -ManifestSha256 $ManifestSha256
    $event = Read-WeatherOneShotIndexJson `
        -Path $eventPath -Label "One-shot manifest index event"
    if (-not (Test-WeatherOneShotExactPropertySet -Value $event `
            -ExpectedNames @(
                "schema_version", "kind", "recorded_at_local", "task_name",
                "manifest_path", "manifest_sha256", "authority"
            )) -or
        [string]$event.schema_version -cne "weather_one_shot_registry_index_v1" -or
        [string]$event.kind -cne "MANIFEST_ANCHOR" -or
        [string]$event.task_name -cne $TaskName -or
        [IO.Path]::GetFullPath([string]$event.manifest_path) -ine
            [IO.Path]::GetFullPath($ManifestPath) -or
        [string]$event.manifest_sha256 -cne $ManifestSha256 -or
        [string]$event.recorded_at_local -notmatch
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$' -or
        [string]$event.authority -cne
            "CREATE_ONLY_ONE_SHOT_REGISTRY_INDEX") {
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_INDEX_INVALID" `
            -Message "One-shot manifest index event does not bind its exact anchor."
    }
    try { [void][DateTimeOffset]::Parse([string]$event.recorded_at_local) }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_INDEX_INVALID" `
            -Message "One-shot manifest index timestamp is invalid."
    }
    return $event
}

function Write-WeatherOneShotManifestIndexEvent {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ManifestSha256,
        [Parameter(Mandatory = $true)][string]$TaskName
    )
    Assert-WeatherOneShotRegistryIndexDirectory -Create
    $eventPath = Get-WeatherOneShotManifestIndexEventPath `
        -TaskName $TaskName -ManifestSha256 $ManifestSha256
    if (-not (Test-Path -LiteralPath $eventPath -PathType Leaf)) {
        $event = [ordered]@{
            schema_version = "weather_one_shot_registry_index_v1"
            kind = "MANIFEST_ANCHOR"
            recorded_at_local = [DateTimeOffset]::Now.ToString("o")
            task_name = $TaskName
            manifest_path = [IO.Path]::GetFullPath($ManifestPath)
            manifest_sha256 = $ManifestSha256
            authority = "CREATE_ONLY_ONE_SHOT_REGISTRY_INDEX"
        }
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes(
            ($event | ConvertTo-Json -Depth 4)
        )
        Write-WeatherOneShotIndexCreateOnlyFile `
            -Destination $eventPath -Bytes $bytes
    }
    Assert-WeatherOneShotManifestIndexEvent `
        -ManifestPath $ManifestPath -ManifestSha256 $ManifestSha256 `
        -TaskName $TaskName | Out-Null
    return $eventPath
}

function Write-WeatherOneShotResolutionIndexEvent {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ManifestSha256,
        [Parameter(Mandatory = $true)][string]$ResolutionPath,
        [Parameter(Mandatory = $true)][string]$ResolutionSha256,
        [Parameter(Mandatory = $true)][string]$TaskName
    )
    Assert-WeatherOneShotRegistryIndexDirectory -Create
    $eventPath = Get-WeatherOneShotResolutionIndexEventPath `
        -TaskName $TaskName -ManifestSha256 $ManifestSha256
    if (-not (Test-Path -LiteralPath $eventPath -PathType Leaf)) {
        $event = [ordered]@{
            schema_version = "weather_one_shot_registry_index_v1"
            kind = "RESOLUTION"
            recorded_at_local = [DateTimeOffset]::Now.ToString("o")
            task_name = $TaskName
            manifest_path = [IO.Path]::GetFullPath($ManifestPath)
            manifest_sha256 = $ManifestSha256
            resolution_path = [IO.Path]::GetFullPath($ResolutionPath)
            resolution_sha256 = $ResolutionSha256
            authority = "CREATE_ONLY_ONE_SHOT_REGISTRY_INDEX"
        }
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes(
            ($event | ConvertTo-Json -Depth 4)
        )
        Write-WeatherOneShotIndexCreateOnlyFile `
            -Destination $eventPath -Bytes $bytes
    }
    $stored = Read-WeatherOneShotIndexJson `
        -Path $eventPath -Label "One-shot resolution index event"
    if (-not (Test-WeatherOneShotExactPropertySet -Value $stored `
            -ExpectedNames @(
                "schema_version", "kind", "recorded_at_local", "task_name",
                "manifest_path", "manifest_sha256", "resolution_path",
                "resolution_sha256", "authority"
            )) -or
        [string]$stored.schema_version -cne "weather_one_shot_registry_index_v1" -or
        [string]$stored.kind -cne "RESOLUTION" -or
        [string]$stored.task_name -cne $TaskName -or
        [IO.Path]::GetFullPath([string]$stored.manifest_path) -ine
            [IO.Path]::GetFullPath($ManifestPath) -or
        [string]$stored.manifest_sha256 -cne $ManifestSha256 -or
        [IO.Path]::GetFullPath([string]$stored.resolution_path) -ine
            [IO.Path]::GetFullPath($ResolutionPath) -or
        [string]$stored.resolution_sha256 -cne $ResolutionSha256 -or
        [string]$stored.authority -cne
            "CREATE_ONLY_ONE_SHOT_REGISTRY_INDEX") {
        throw "One-shot resolution index event does not bind exact history."
    }
    return $eventPath
}

function Assert-WeatherOneShotExecutableAvailable {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "TASK_EXECUTABLE_UNAVAILABLE" `
            -Message "The manifest-bound executable is unavailable."
    }
    if ($item.PSIsContainer -or
        (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        Throw-WeatherOneShotReadinessError `
            -Code "TASK_EXECUTABLE_UNAVAILABLE" `
            -Message "The manifest-bound executable is not a regular non-reparse file."
    }
}

function Assert-WeatherOneShotWorkingDirectoryAvailable {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "TASK_WORKING_DIRECTORY_UNAVAILABLE" `
            -Message "The manifest-bound working directory is unavailable."
    }
    if (-not $item.PSIsContainer -or
        (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        Throw-WeatherOneShotReadinessError `
            -Code "TASK_WORKING_DIRECTORY_UNAVAILABLE" `
            -Message "The manifest-bound working directory is not a non-reparse directory."
    }
}

function Assert-WeatherOneShotNonReparseDirectoryTree {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$StopPath
    )

    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullStop = [IO.Path]::GetFullPath($StopPath)
    try {
        $cursor = Get-Item -LiteralPath $fullPath -ErrorAction Stop
        while ($null -ne $cursor) {
            $cursorPath = [IO.Path]::GetFullPath([string]$cursor.FullName)
            if ($cursor -isnot [IO.DirectoryInfo] -or
                (($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
                Throw-WeatherOneShotReadinessError `
                    -Code "MANIFEST_NOT_REGISTRY_ANCHORED" `
                    -Message "The active registry path contains a non-directory or reparse ancestor."
            }
            if ($cursorPath -ieq $fullStop) { return }
            if (-not $cursorPath.StartsWith(
                    $fullStop + [IO.Path]::DirectorySeparatorChar,
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                Throw-WeatherOneShotReadinessError `
                    -Code "MANIFEST_NOT_REGISTRY_ANCHORED" `
                    -Message "The active registry path escapes its repository root."
            }
            $cursor = $cursor.Parent
        }
    }
    catch {
        if ($_.Exception.Data.Contains("weather_one_shot_readiness_blocker_code")) {
            throw
        }
        Throw-WeatherOneShotReadinessError `
            -Code "MANIFEST_NOT_REGISTRY_ANCHORED" `
            -Message "The active registry directory tree could not be verified."
    }
    Throw-WeatherOneShotReadinessError `
        -Code "MANIFEST_NOT_REGISTRY_ANCHORED" `
        -Message "The active registry directory tree does not reach its repository root."
}

function Assert-WeatherOneShotRegistryActivationMarker {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RegistryRoot
    )

    $snapshot = Read-WeatherOneShotRegularFileSnapshot `
        -Path $Path -MaximumBytes 64KB `
        -UnavailableCode "REGISTRY_ACTIVATION_UNAVAILABLE" `
        -UnsafeCode "REGISTRY_ACTIVATION_INVALID" `
        -TooLargeCode "REGISTRY_ACTIVATION_INVALID" `
        -Label "One-shot registry activation marker"
    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $text = $utf8.GetString([byte[]]$snapshot.bytes)
        $marker = $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_ACTIVATION_INVALID" `
            -Message "One-shot registry activation marker is not valid bounded UTF-8 JSON."
    }
    if (-not (Test-WeatherOneShotExactPropertySet `
            -Value $marker `
            -ExpectedNames @(
                "schema_version", "status", "registry_root",
                "activated_at_local", "authority"
            )) -or
        [string]$marker.schema_version -cne
            "weather_one_shot_registry_activation_v1" -or
        [string]$marker.status -cne "ACTIVE" -or
        [IO.Path]::GetFullPath([string]$marker.registry_root) -ine
            [IO.Path]::GetFullPath($RegistryRoot) -or
        [string]$marker.authority -cnotin @(
            "CREATE_ONLY_ONE_SHOT_ACTIVE_REGISTRY",
            "REVIEWED_EMPTY_REGISTRY_ACTIVATION_RECOVERY"
        ) -or
        [string]$marker.activated_at_local -notmatch
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$') {
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_ACTIVATION_INVALID" `
            -Message "One-shot registry activation marker does not match its exact contract."
    }
    try {
        [void][DateTimeOffset]::Parse(
            [string]$marker.activated_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_ACTIVATION_INVALID" `
            -Message "One-shot registry activation timestamp is invalid."
    }
}

function Assert-WeatherOneShotRegistryActivationIntent {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RegistryRoot
    )

    $snapshot = Read-WeatherOneShotRegularFileSnapshot `
        -Path $Path -MaximumBytes 64KB `
        -UnavailableCode "REGISTRY_ACTIVATION_UNAVAILABLE" `
        -UnsafeCode "REGISTRY_ACTIVATION_INVALID" `
        -TooLargeCode "REGISTRY_ACTIVATION_INVALID" `
        -Label "One-shot registry activation intent"
    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $intent = $utf8.GetString([byte[]]$snapshot.bytes) |
            ConvertFrom-Json -ErrorAction Stop
        $createdAt = [DateTimeOffset]::Parse(
            [string]$intent.created_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_ACTIVATION_INVALID" `
            -Message "One-shot registry activation intent is not valid bounded evidence."
    }
    if (-not (Test-WeatherOneShotExactPropertySet `
            -Value $intent `
            -ExpectedNames @(
                "schema_version", "status", "registry_root",
                "created_at_local", "authority"
            )) -or
        [string]$intent.schema_version -cne
            "weather_one_shot_registry_activation_intent_v1" -or
        [string]$intent.status -cne "ACTIVATION_INTENDED" -or
        [IO.Path]::GetFullPath([string]$intent.registry_root) -ine
            [IO.Path]::GetFullPath($RegistryRoot) -or
        [string]$intent.authority -cne
            "DURABLE_ONE_SHOT_REGISTRY_ACTIVATION_INTENT" -or
        [string]$intent.created_at_local -notmatch
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$' -or
        $createdAt -gt [DateTimeOffset]::Now.AddMinutes(5)) {
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_ACTIVATION_INVALID" `
            -Message "One-shot registry activation intent does not match its exact contract."
    }
}

function Assert-WeatherOneShotRegistryRecoveryReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$IntentPath,
        [Parameter(Mandatory = $true)][string]$MarkerPath,
        [Parameter(Mandatory = $true)][string]$RegistryRoot
    )

    foreach ($evidencePath in @($Path, $IntentPath, $MarkerPath)) {
        if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf `
                -ErrorAction Stop)) {
            Throw-WeatherOneShotReadinessError `
                -Code "REGISTRY_ACTIVATION_INVALID" `
                -Message "Recovered one-shot activation evidence is incomplete."
        }
    }
    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $receiptSnapshot = Read-WeatherOneShotRegularFileSnapshot `
            -Path $Path -MaximumBytes 64KB `
            -UnavailableCode "REGISTRY_ACTIVATION_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_ACTIVATION_INVALID" `
            -TooLargeCode "REGISTRY_ACTIVATION_INVALID" `
            -Label "One-shot registry activation recovery receipt"
        $intentSnapshot = Read-WeatherOneShotRegularFileSnapshot `
            -Path $IntentPath -MaximumBytes 64KB `
            -UnavailableCode "REGISTRY_ACTIVATION_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_ACTIVATION_INVALID" `
            -TooLargeCode "REGISTRY_ACTIVATION_INVALID" `
            -Label "One-shot registry activation intent"
        $markerSnapshot = Read-WeatherOneShotRegularFileSnapshot `
            -Path $MarkerPath -MaximumBytes 64KB `
            -UnavailableCode "REGISTRY_ACTIVATION_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_ACTIVATION_INVALID" `
            -TooLargeCode "REGISTRY_ACTIVATION_INVALID" `
            -Label "One-shot registry activation marker"
        $receipt = $utf8.GetString([byte[]]$receiptSnapshot.bytes) |
            ConvertFrom-Json -ErrorAction Stop
        $storedIntent = $utf8.GetString([byte[]]$intentSnapshot.bytes) |
            ConvertFrom-Json -ErrorAction Stop
        $storedMarker = $utf8.GetString([byte[]]$markerSnapshot.bytes) |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        if ($_.Exception.Data.Contains("weather_one_shot_readiness_blocker_code")) {
            throw
        }
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_ACTIVATION_INVALID" `
            -Message "One-shot activation recovery evidence is not valid bounded UTF-8 JSON."
    }
    if (-not (Test-WeatherOneShotExactPropertySet `
            -Value $receipt `
            -ExpectedNames @(
                "schema_version", "status", "registry_root", "reason",
                "review_reference", "confirmation", "activation_intent",
                "activation_marker", "authority"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $receipt.activation_intent `
            -ExpectedNames @(
                "schema_version", "status", "registry_root",
                "created_at_local", "authority"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $receipt.activation_marker `
            -ExpectedNames @(
                "schema_version", "status", "registry_root",
                "activated_at_local", "authority"
            )) -or
        [string]$receipt.schema_version -cne
            "weather_one_shot_registry_activation_recovery_v1" -or
        [string]$receipt.status -cne "PASS" -or
        [IO.Path]::GetFullPath([string]$receipt.registry_root) -ine
            [IO.Path]::GetFullPath($RegistryRoot) -or
        [string]::IsNullOrWhiteSpace([string]$receipt.reason) -or
        ([string]$receipt.reason).Length -gt 4096 -or
        [string]::IsNullOrWhiteSpace([string]$receipt.review_reference) -or
        ([string]$receipt.review_reference).Length -gt 4096 -or
        [string]$receipt.confirmation -cne
            "REVIEWED_RECONCILE_EMPTY_ONE_SHOT_REGISTRY_ACTIVATION" -or
        [string]$receipt.authority -cne
            "REVIEWED_EMPTY_REGISTRY_ACTIVATION_RECOVERY_NO_SCHEDULER_AUTHORITY") {
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_ACTIVATION_INVALID" `
            -Message "One-shot activation recovery receipt does not match its exact contract."
    }
    foreach ($field in @(
            "schema_version", "status", "registry_root",
            "created_at_local", "authority"
        )) {
        if ([string]$receipt.activation_intent.$field -cne
            [string]$storedIntent.$field) {
            Throw-WeatherOneShotReadinessError `
                -Code "REGISTRY_ACTIVATION_INVALID" `
                -Message "One-shot recovery receipt does not bind the stored activation intent."
        }
    }
    foreach ($field in @(
            "schema_version", "status", "registry_root",
            "activated_at_local", "authority"
        )) {
        if ([string]$receipt.activation_marker.$field -cne
            [string]$storedMarker.$field) {
            Throw-WeatherOneShotReadinessError `
                -Code "REGISTRY_ACTIVATION_INVALID" `
                -Message "One-shot recovery receipt does not bind the stored activation marker."
        }
    }
}

function Expand-WeatherOneShotArgumentsTemplate {
    param(
        [Parameter(Mandatory = $true)][string]$Template,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ManifestSha256
    )

    if ([string]::IsNullOrWhiteSpace($Template) -or $Template.Length -gt 32768 -or
        [regex]::Matches(
            $Template,
            [regex]::Escape($script:OneShotReadinessManifestPathToken)
        ).Count -ne 1 -or
        [regex]::Matches(
            $Template,
            [regex]::Escape($script:OneShotReadinessManifestHashToken)
        ).Count -ne 1) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot arguments_template must contain each readiness placeholder exactly once."
    }
    return $Template.Replace(
        $script:OneShotReadinessManifestPathToken,
        $ManifestPath
    ).Replace(
        $script:OneShotReadinessManifestHashToken,
        $ManifestSha256.ToLowerInvariant()
    )
}

function ConvertTo-WeatherOneShotProcessArgumentString {
    param([Parameter(Mandatory = $true)][string[]]$Tokens)

    $encoded = foreach ($token in $Tokens) {
        $value = [string]$token
        if ($value.Contains('"')) {
            throw "One-shot process argument tokens may not contain a double quote."
        }
        if ($value -match '\s') {
            if ($value.EndsWith('\')) {
                throw "A quoted one-shot process argument may not end in a backslash."
            }
            '"{0}"' -f $value
        }
        elseif ($value.Length -eq 0) { '""' }
        else { $value }
    }
    $argumentString = $encoded -join " "
    if ($argumentString.Length -gt 30000) {
        throw "One-shot process arguments exceed the conservative Windows command-line bound."
    }
    return $argumentString
}

function Read-WeatherOneShotReadinessManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{64}$")]
        [string]$ExpectedSha256,
        [switch]$AllowUnanchoredSource,
        [switch]$AllowResolvedManifest,
        [switch]$AllowResolutionIndexRepair,
        [switch]$SkipCurrentAvailabilityChecks
    )

    $fileSnapshot = Read-WeatherOneShotRegularFileSnapshot `
        -Path $Path `
        -MaximumBytes $script:OneShotReadinessMaximumManifestBytes `
        -UnavailableCode "MANIFEST_UNAVAILABLE" `
        -UnsafeCode "MANIFEST_UNSAFE_PATH" `
        -TooLargeCode "MANIFEST_UNSAFE_PATH" `
        -Label "One-shot readiness manifest"
    $actualSha256 = [string]$fileSnapshot.sha256
    if ($actualSha256 -cne $ExpectedSha256.ToLowerInvariant()) {
        Throw-WeatherOneShotReadinessError `
            -Code "MANIFEST_HASH_MISMATCH" `
            -Message "One-shot readiness manifest hash does not match the reviewed value."
    }

    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $manifestText = $utf8.GetString([byte[]]$fileSnapshot.bytes)
        if ($manifestText.Length -gt 0 -and $manifestText[0] -eq [char]0xfeff) {
            $manifestText = $manifestText.Substring(1)
        }
        $manifest = $manifestText | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness manifest is not valid JSON."
    }

    if (-not (Test-WeatherOneShotExactPropertySet `
            -Value $manifest `
            -ExpectedNames @(
                "schema_version", "task", "principal", "settings",
                "admission", "boot_identity", "dependencies"
            )) -or
        [string]$manifest.schema_version -cne $script:OneShotReadinessManifestSchema -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $manifest.task `
            -ExpectedNames @(
                "task_name", "task_path", "executable", "arguments_template",
                "working_directory", "action_file", "payload_file",
                "payload_arguments", "trigger_at_local"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $manifest.principal `
            -ExpectedNames @("user_id", "logon_type", "run_level")) -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $manifest.settings `
            -ExpectedNames @(
                "multiple_instances", "execution_time_limit",
                "start_when_available", "allow_demand_start", "wake_to_run",
                "restart_count", "restart_interval",
                "allow_start_if_on_batteries", "stop_if_going_on_batteries",
                "run_only_if_idle", "run_only_if_network_available"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $manifest.admission `
            -ExpectedNames @(
                "workload_class", "earliest_at_local", "teardown_deadline_at_local"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $manifest.boot_identity `
            -ExpectedNames @("last_boot_up_time_utc"))) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness manifest does not match its exact schema."
    }

    $taskName = [string]$manifest.task.task_name
    if ([string]::IsNullOrWhiteSpace($taskName) -or
        $taskName.Contains("\") -or
        $taskName.Contains("/")) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness task_name must be one unqualified task name."
    }
    if (-not $AllowUnanchoredSource) {
        try {
            $registryRootItem = Get-Item `
                -LiteralPath $script:OneShotReadinessRegistryRoot `
                -ErrorAction Stop
        }
        catch {
            Throw-WeatherOneShotReadinessError `
                -Code "MANIFEST_NOT_REGISTRY_ANCHORED" `
                -Message "The canonical active one-shot manifest registry is unavailable."
        }
        $expectedLeaf = "$taskName.$actualSha256.manifest.json"
        if (-not $registryRootItem.PSIsContainer -or
            (($registryRootItem.Attributes -band
                    [IO.FileAttributes]::ReparsePoint) -ne 0) -or
            (Split-Path -Parent ([string]$fileSnapshot.full_name)) -ine
                [string]$registryRootItem.FullName -or
            [IO.Path]::GetFileName([string]$fileSnapshot.full_name) -cne
                $expectedLeaf) {
            Throw-WeatherOneShotReadinessError `
                -Code "MANIFEST_NOT_REGISTRY_ANCHORED" `
                -Message "One-shot readiness requires the exact filename-hash-bound active registry copy."
        }
        Assert-WeatherOneShotNonReparseDirectoryTree `
            -Path ([string]$registryRootItem.FullName) `
            -StopPath $script:OneShotReadinessRepositoryRoot
        if ($script:OneShotReadinessRequireActivationMarker) {
            Assert-WeatherOneShotRegistryActivationMarker `
                -Path $script:OneShotReadinessActivationMarkerPath `
                -RegistryRoot ([string]$registryRootItem.FullName)
            Assert-WeatherOneShotRegistryActivationIntent `
                -Path $script:OneShotReadinessActivationIntentPath `
                -RegistryRoot ([string]$registryRootItem.FullName)
            try {
                $markerSnapshot = Read-WeatherOneShotRegularFileSnapshot `
                    -Path $script:OneShotReadinessActivationMarkerPath `
                    -MaximumBytes 64KB `
                    -UnavailableCode "REGISTRY_ACTIVATION_UNAVAILABLE" `
                    -UnsafeCode "REGISTRY_ACTIVATION_INVALID" `
                    -TooLargeCode "REGISTRY_ACTIVATION_INVALID" `
                    -Label "One-shot registry activation marker"
                $markerJson = [Text.UTF8Encoding]::new(
                    $false, $true
                ).GetString([byte[]]$markerSnapshot.bytes) |
                    ConvertFrom-Json -ErrorAction Stop
                $recoveryExists = Test-Path `
                    -LiteralPath $script:OneShotReadinessActivationRecoveryPath `
                    -PathType Leaf -ErrorAction Stop
            }
            catch {
                if ($_.Exception.Data.Contains(
                        "weather_one_shot_readiness_blocker_code"
                    )) {
                    throw
                }
                Throw-WeatherOneShotReadinessError `
                    -Code "REGISTRY_ACTIVATION_INVALID" `
                    -Message "One-shot registry recovery mode could not be verified."
            }
            if ([string]$markerJson.authority -ceq
                "REVIEWED_EMPTY_REGISTRY_ACTIVATION_RECOVERY") {
                if (-not $recoveryExists) {
                    Throw-WeatherOneShotReadinessError `
                        -Code "REGISTRY_ACTIVATION_INVALID" `
                        -Message "Recovered one-shot registry lacks its immutable review receipt."
                }
                Assert-WeatherOneShotRegistryRecoveryReceipt `
                    -Path $script:OneShotReadinessActivationRecoveryPath `
                    -IntentPath $script:OneShotReadinessActivationIntentPath `
                    -MarkerPath $script:OneShotReadinessActivationMarkerPath `
                    -RegistryRoot ([string]$registryRootItem.FullName)
            }
            elseif ($recoveryExists) {
                Throw-WeatherOneShotReadinessError `
                    -Code "REGISTRY_ACTIVATION_INVALID" `
                    -Message "A recovery receipt exists for a normally activated one-shot registry."
            }
        }
        Assert-WeatherOneShotManifestIndexEvent `
            -ManifestPath ([string]$fileSnapshot.full_name) `
            -ManifestSha256 $actualSha256 -TaskName $taskName | Out-Null
        $resolutionPath = [string]$fileSnapshot.full_name
        $resolutionPath = $resolutionPath.Substring(
            0,
            $resolutionPath.Length - ".manifest.json".Length
        ) + ".resolution.json"
        if ($AllowResolutionIndexRepair -and -not $AllowResolvedManifest) {
            Throw-WeatherOneShotReadinessError `
                -Code "INVALID_ARGUMENT" `
                -Message "Resolution-index repair requires resolved-manifest review mode."
        }
        $resolutionPathExists = Test-Path -LiteralPath $resolutionPath `
            -ErrorAction Stop
        $resolutionExists = Test-Path -LiteralPath $resolutionPath `
            -PathType Leaf -ErrorAction Stop
        $resolutionEventPath = Get-WeatherOneShotResolutionIndexEventPath `
            -TaskName $taskName -ManifestSha256 $actualSha256
        $resolutionEventPathExists = Test-Path `
            -LiteralPath $resolutionEventPath -ErrorAction Stop
        $resolutionEventExists = Test-Path -LiteralPath $resolutionEventPath `
            -PathType Leaf -ErrorAction Stop
        if (($resolutionPathExists -and -not $resolutionExists) -or
            ($resolutionEventPathExists -and -not $resolutionEventExists)) {
            Throw-WeatherOneShotReadinessError `
                -Code "REGISTRY_INDEX_INVALID" `
                -Message "One-shot resolution continuity includes a wrong-type filesystem object."
        }
        if ($resolutionExists -and -not $resolutionEventExists -and
            $AllowResolutionIndexRepair) {
            # The resolver owns the exclusive registry lock and will validate
            # and create-only repair this one missing event immediately after
            # the manifest read. No execution path receives this switch.
        }
        elseif ($resolutionExists -ne $resolutionEventExists) {
            Throw-WeatherOneShotReadinessError `
                -Code "REGISTRY_INDEX_INVALID" `
                -Message "One-shot resolution and immutable resolution-index continuity disagree."
        }
        if ($resolutionEventExists) {
            $resolutionEvent = Read-WeatherOneShotIndexJson `
                -Path $resolutionEventPath `
                -Label "One-shot resolution index event"
            if (-not (Test-WeatherOneShotExactPropertySet `
                    -Value $resolutionEvent `
                    -ExpectedNames @(
                        "schema_version", "kind", "recorded_at_local",
                        "task_name", "manifest_path", "manifest_sha256",
                        "resolution_path", "resolution_sha256", "authority"
                    )) -or
                [string]$resolutionEvent.schema_version -cne
                    "weather_one_shot_registry_index_v1" -or
                [string]$resolutionEvent.kind -cne "RESOLUTION" -or
                [string]$resolutionEvent.task_name -cne $taskName -or
                [IO.Path]::GetFullPath(
                    [string]$resolutionEvent.manifest_path
                ) -ine [IO.Path]::GetFullPath(
                    [string]$fileSnapshot.full_name
                ) -or
                [string]$resolutionEvent.manifest_sha256 -cne $actualSha256 -or
                [IO.Path]::GetFullPath(
                    [string]$resolutionEvent.resolution_path
                ) -ine [IO.Path]::GetFullPath($resolutionPath) -or
                [string]$resolutionEvent.resolution_sha256 -cnotmatch
                    '^[0-9a-f]{64}$' -or
                [string]$resolutionEvent.authority -cne
                    "CREATE_ONLY_ONE_SHOT_REGISTRY_INDEX") {
                Throw-WeatherOneShotReadinessError `
                    -Code "REGISTRY_INDEX_INVALID" `
                    -Message "One-shot resolution index event is malformed or misbound."
            }
            $resolutionSnapshot = Read-WeatherOneShotRegularFileSnapshot `
                -Path $resolutionPath -MaximumBytes 1MB `
                -UnavailableCode "REGISTRY_INDEX_INVALID" `
                -UnsafeCode "REGISTRY_INDEX_INVALID" `
                -TooLargeCode "REGISTRY_INDEX_INVALID" `
                -Label "Indexed one-shot resolution"
            if ([string]$resolutionSnapshot.sha256 -cne
                [string]$resolutionEvent.resolution_sha256) {
                Throw-WeatherOneShotReadinessError `
                    -Code "REGISTRY_INDEX_INVALID" `
                    -Message "One-shot resolution bytes disagree with their immutable index event."
            }
        }
        if (-not $AllowResolvedManifest -and $resolutionEventExists) {
            Throw-WeatherOneShotReadinessError `
                -Code "MANIFEST_ALREADY_RESOLVED" `
                -Message "The active one-shot manifest has immutable terminal or supersession evidence."
        }
    }
    $taskPath = ConvertTo-WeatherOneShotTaskPath -Value ([string]$manifest.task.task_path)
    if ([string]$manifest.task.task_path -cne $taskPath) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness task_path must use canonical leading and trailing backslashes."
    }

    $executable = ConvertTo-WeatherOneShotFullPath -Path ([string]$manifest.task.executable)
    if ([string]$manifest.task.executable -cne $executable) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness executable must be a canonical absolute path."
    }
    if (-not $SkipCurrentAvailabilityChecks) {
        Assert-WeatherOneShotExecutableAvailable -Path $executable
    }
    if ($executable -ine $script:OneShotPowerShellExecutablePath) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot task executable must be the current canonical Windows PowerShell host."
    }
    $workingDirectory = ConvertTo-WeatherOneShotFullPath `
        -Path ([string]$manifest.task.working_directory)
    if ([string]$manifest.task.working_directory -cne $workingDirectory) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness working_directory must be a canonical absolute path."
    }
    if (-not $SkipCurrentAvailabilityChecks) {
        Assert-WeatherOneShotWorkingDirectoryAvailable -Path $workingDirectory
    }
    $actionFile = ConvertTo-WeatherOneShotFullPath -Path ([string]$manifest.task.action_file)
    if ([string]$manifest.task.action_file -cne $actionFile) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness action_file must be a canonical absolute path."
    }
    if ($actionFile -ine $script:OneShotGuardedLauncherPath) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "Every one-shot task must execute the repository-owned guarded launcher."
    }
    $payloadFile = ConvertTo-WeatherOneShotFullPath `
        -Path ([string]$manifest.task.payload_file)
    if ([string]$manifest.task.payload_file -cne $payloadFile -or
        $payloadFile -ieq $actionFile -or
        [IO.Path]::GetExtension($payloadFile) -ine ".ps1") {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot payload_file must be a distinct canonical absolute path."
    }
    $payloadArguments = @($manifest.task.payload_arguments)
    if ($null -eq $manifest.task.payload_arguments -or
        $payloadArguments.Count -gt 64) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot payload_arguments must contain at most 64 strings."
    }
    $payloadArgumentCharacters = 0
    foreach ($payloadArgument in $payloadArguments) {
        if ($payloadArgument -isnot [string] -or
            ([string]$payloadArgument).Length -gt 4096 -or
            ([string]$payloadArgument).Contains('"') -or
            (([string]$payloadArgument -match '\s') -and
                ([string]$payloadArgument).EndsWith('\'))) {
            Throw-WeatherOneShotReadinessError `
                -Code "INVALID_MANIFEST" `
                -Message "Every one-shot payload argument must be a bounded string."
        }
        $payloadArgumentCharacters += ([string]$payloadArgument).Length
    }
    if ($payloadArgumentCharacters -gt 32768) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot payload arguments exceed the aggregate character bound."
    }
    try {
        [void](ConvertTo-WeatherOneShotProcessArgumentString -Tokens (@(
                    "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                    "Bypass", "-File", $payloadFile
                ) + [string[]]$payloadArguments))
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message ("One-shot payload arguments are not safely representable: " +
                $_.Exception.Message)
    }
    $trigger = Assert-WeatherOneShotHostLocalInstant `
        -Value (ConvertTo-WeatherOneShotInstant `
            -Value ([string]$manifest.task.trigger_at_local) `
            -FieldName "task.trigger_at_local") `
        -FieldName "task.trigger_at_local"
    $boot = ConvertTo-WeatherOneShotInstant `
        -Value ([string]$manifest.boot_identity.last_boot_up_time_utc) `
        -FieldName "boot_identity.last_boot_up_time_utc" `
        -RequireUtc

    $principalUserId = [string]$manifest.principal.user_id
    if ([string]::IsNullOrWhiteSpace($principalUserId) -or
        [string]$manifest.principal.logon_type -cne "S4U" -or
        [string]$manifest.principal.run_level -cne "Limited") {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness principal must name one exact S4U/Limited user."
    }
    $restartCountValue = $manifest.settings.restart_count
    $restartCountIsInteger = (
        $restartCountValue -is [int] -or
        $restartCountValue -is [long]
    )
    if ($manifest.settings.start_when_available -isnot [bool] -or
        $manifest.settings.allow_demand_start -isnot [bool] -or
        $manifest.settings.wake_to_run -isnot [bool] -or
        $manifest.settings.allow_start_if_on_batteries -isnot [bool] -or
        $manifest.settings.stop_if_going_on_batteries -isnot [bool] -or
        $manifest.settings.run_only_if_idle -isnot [bool] -or
        $manifest.settings.run_only_if_network_available -isnot [bool] -or
        -not $restartCountIsInteger -or
        [string]$manifest.settings.multiple_instances -cne "IgnoreNew" -or
        [bool]$manifest.settings.start_when_available -or
        [bool]$manifest.settings.allow_demand_start -or
        -not [bool]$manifest.settings.wake_to_run -or
        [int]$manifest.settings.restart_count -ne 0 -or
        -not [string]::IsNullOrEmpty([string]$manifest.settings.restart_interval) -or
        -not [bool]$manifest.settings.allow_start_if_on_batteries -or
        [bool]$manifest.settings.stop_if_going_on_batteries -or
        [bool]$manifest.settings.run_only_if_idle -or
        [bool]$manifest.settings.run_only_if_network_available) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness settings require IgnoreNew, no retry/late/demand/idle/network gate, WakeToRun, and fail-open battery continuity."
    }
    try {
        $executionTimeLimit = [Xml.XmlConvert]::ToTimeSpan(
            [string]$manifest.settings.execution_time_limit
        )
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness execution_time_limit is not a valid duration."
    }
    if ($executionTimeLimit -le [TimeSpan]::Zero -or
        $executionTimeLimit -gt [TimeSpan]::FromHours(8)) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness execution_time_limit must be positive and no longer than eight hours."
    }
    $workloadClass = [string]$manifest.admission.workload_class
    if ($workloadClass -cnotin @("heavy", "light")) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness workload_class must be heavy or light."
    }
    $admissionEarliest = Assert-WeatherOneShotHostLocalInstant `
        -Value (ConvertTo-WeatherOneShotInstant `
            -Value ([string]$manifest.admission.earliest_at_local) `
            -FieldName "admission.earliest_at_local") `
        -FieldName "admission.earliest_at_local"
    $teardownDeadline = Assert-WeatherOneShotHostLocalInstant `
        -Value (ConvertTo-WeatherOneShotInstant `
            -Value ([string]$manifest.admission.teardown_deadline_at_local) `
            -FieldName "admission.teardown_deadline_at_local") `
        -FieldName "admission.teardown_deadline_at_local"
    if ($admissionEarliest.UtcDateTime.Ticks -gt $trigger.UtcDateTime.Ticks -or
        $trigger.Add($executionTimeLimit).UtcDateTime.Ticks -gt
            $teardownDeadline.UtcDateTime.Ticks) {
        Throw-WeatherOneShotReadinessError `
            -Code "TASK_OUTSIDE_ADMISSION_WINDOW" `
            -Message "The trigger plus maximum runtime does not fit inside the reviewed admission window."
    }
    if ([string]$taskName -like "WeatherSettlementBackfill*" -and
        $workloadClass -cne "heavy") {
        Throw-WeatherOneShotReadinessError `
            -Code "TASK_OUTSIDE_ADMISSION_WINDOW" `
            -Message "Settlement backfills must be classified as heavy work."
    }
    if ($workloadClass -ceq "heavy" -and
        ($admissionEarliest.Date -ne $trigger.Date -or
            $teardownDeadline.Date -ne $trigger.Date -or
            $admissionEarliest.TimeOfDay -lt [TimeSpan]::FromMinutes(30) -or
            $teardownDeadline.TimeOfDay -gt [TimeSpan]::FromHours(9))) {
        Throw-WeatherOneShotReadinessError `
            -Code "TASK_OUTSIDE_ADMISSION_WINDOW" `
            -Message "Heavy one-shots must fit the same-date 00:30-09:00 host admission window."
    }
    $expandedArguments = Expand-WeatherOneShotArgumentsTemplate `
        -Template ([string]$manifest.task.arguments_template) `
        -ManifestPath ([string]$fileSnapshot.full_name) `
        -ManifestSha256 $actualSha256
    $expandedManifestPath = Resolve-WeatherOneShotArgumentValue `
        -Arguments $expandedArguments -Name "ReadinessManifestPath"
    $expandedManifestSha256 = Resolve-WeatherOneShotArgumentValue `
        -Arguments $expandedArguments -Name "ExpectedReadinessManifestSha256"
    $resolvedExpandedManifestPath = $null
    try {
        $resolvedExpandedManifestPath = [IO.Path]::GetFullPath($expandedManifestPath)
    }
    catch { }
    if ([string]::IsNullOrWhiteSpace($resolvedExpandedManifestPath) -or
        $resolvedExpandedManifestPath -ine [string]$fileSnapshot.full_name -or
        $expandedManifestSha256 -ine $actualSha256) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot arguments_template must expand to its exact readiness manifest path and hash."
    }
    $expectedArgumentsTemplate = (
        '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" ' +
        '-ReadinessManifestPath "{1}" ' +
        '-ExpectedReadinessManifestSha256 {2}'
    ) -f $script:OneShotGuardedLauncherPath,
        $script:OneShotReadinessManifestPathToken,
        $script:OneShotReadinessManifestHashToken
    if ([string]$manifest.task.arguments_template -cne
        $expectedArgumentsTemplate) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot arguments_template must invoke only the canonical guarded launcher contract."
    }

    $dependencies = @($manifest.dependencies)
    if ($dependencies.Count -eq 0) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness manifest must bind at least the action file dependency."
    }
    if ($dependencies.Count -gt $script:OneShotReadinessMaximumDependencyCount) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "One-shot readiness manifest exceeds the bounded dependency count."
    }
    $seenPaths = New-Object 'System.Collections.Generic.HashSet[string]' `
        ([StringComparer]::OrdinalIgnoreCase)
    $actionDependencyCount = 0
    $validatorDependencyCount = 0
    $workloadAdmissionDependencyCount = 0
    $payloadDependencyCount = 0
    $jobContainmentDependencyCount = 0
    $normalizedDependencies = New-Object System.Collections.Generic.List[object]
    foreach ($dependency in $dependencies) {
        if (-not (Test-WeatherOneShotExactPropertySet `
                -Value $dependency `
                -ExpectedNames @("path", "sha256")) -or
            [string]$dependency.sha256 -cnotmatch "^[0-9a-f]{64}$") {
            Throw-WeatherOneShotReadinessError `
                -Code "INVALID_MANIFEST" `
                -Message "Every one-shot dependency must contain only canonical path and lowercase sha256 fields."
        }
        $dependencyPath = ConvertTo-WeatherOneShotFullPath -Path ([string]$dependency.path)
        if ([string]$dependency.path -cne $dependencyPath -or -not $seenPaths.Add($dependencyPath)) {
            Throw-WeatherOneShotReadinessError `
                -Code "INVALID_MANIFEST" `
                -Message "One-shot readiness dependency paths must be canonical and unique."
        }
        if ($dependencyPath -ieq $actionFile) {
            $actionDependencyCount += 1
        }
        if ($dependencyPath -ieq $script:OneShotReadinessScriptPath) {
            $validatorDependencyCount += 1
        }
        if ($dependencyPath -ieq $script:OneShotWorkloadAdmissionPath) {
            $workloadAdmissionDependencyCount += 1
        }
        if ($dependencyPath -ieq $payloadFile) {
            $payloadDependencyCount += 1
        }
        if ($dependencyPath -ieq $script:OneShotKillOnCloseJobPath) {
            $jobContainmentDependencyCount += 1
        }
        $normalizedDependencies.Add([pscustomobject][ordered]@{
            path = $dependencyPath
            sha256 = [string]$dependency.sha256
        })
    }
    if ($actionDependencyCount -ne 1) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "The exact action_file must appear once in dependencies so its bytes are hash-bound."
    }
    if ($validatorDependencyCount -ne 1) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "The canonical one-shot readiness validator must appear once in dependencies."
    }
    if ($payloadDependencyCount -ne 1) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "The exact payload_file must appear once in dependencies so its bytes are hash-bound."
    }
    if ($jobContainmentDependencyCount -ne 1) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "Every one-shot must hash-bind the canonical kill-on-close Job helper."
    }
    if ($workloadClass -ceq "heavy" -and
        $workloadAdmissionDependencyCount -ne 1) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_MANIFEST" `
            -Message "Heavy one-shots must bind the canonical workload-admission script once."
    }

    return [pscustomobject][ordered]@{
        ManifestPath = [string]$fileSnapshot.full_name
        ManifestSha256 = $actualSha256
        Manifest = [pscustomobject][ordered]@{
            schema_version = $script:OneShotReadinessManifestSchema
            task = [pscustomobject][ordered]@{
                task_name = $taskName
                task_path = $taskPath
                executable = $executable
                arguments_template = [string]$manifest.task.arguments_template
                working_directory = $workingDirectory
                action_file = $actionFile
                payload_file = $payloadFile
                payload_arguments = [string[]]$payloadArguments
                trigger_at_local = $trigger.ToString("o")
            }
            principal = [pscustomobject][ordered]@{
                user_id = $principalUserId
                logon_type = "S4U"
                run_level = "Limited"
            }
            settings = [pscustomobject][ordered]@{
                multiple_instances = "IgnoreNew"
                execution_time_limit = [string]$manifest.settings.execution_time_limit
                start_when_available = $false
                allow_demand_start = $false
                wake_to_run = $true
                restart_count = 0
                restart_interval = ""
                allow_start_if_on_batteries = $true
                stop_if_going_on_batteries = $false
                run_only_if_idle = $false
                run_only_if_network_available = $false
            }
            admission = [pscustomobject][ordered]@{
                workload_class = $workloadClass
                earliest_at_local = $admissionEarliest.ToString("o")
                teardown_deadline_at_local = $teardownDeadline.ToString("o")
            }
            boot_identity = [pscustomobject][ordered]@{
                last_boot_up_time_utc = ConvertTo-WeatherOneShotUtcText -Value $boot
            }
            dependencies = $normalizedDependencies.ToArray()
        }
    }
}

function Get-WeatherOneShotCurrentBootIdentity {
    try {
        $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        return ConvertTo-WeatherOneShotUtcText `
            -Value ([DateTimeOffset]$operatingSystem.LastBootUpTime)
    }
    catch {
        Throw-WeatherOneShotReadinessError `
            -Code "BOOT_IDENTITY_UNAVAILABLE" `
            -Message "Current Windows boot identity could not be measured."
    }
}

function Resolve-WeatherOneShotActionFile {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [AllowNull()][string]$Arguments
    )

    $argumentText = if ($null -eq $Arguments) { "" } else { $Arguments }
    $filePattern = '(?i)(?:^|\s)-File(?:\s+|:)(?:"(?<double>[^"]+)"|''(?<single>[^'']+)''|(?<bare>\S+))'
    $matches = [regex]::Matches($argumentText, $filePattern)
    if ($matches.Count -gt 1) {
        return $null
    }
    if ($matches.Count -eq 1) {
        foreach ($groupName in @("double", "single", "bare")) {
            $candidate = $matches[0].Groups[$groupName]
            if ($candidate.Success -and -not [string]::IsNullOrWhiteSpace($candidate.Value)) {
                try {
                    return [IO.Path]::GetFullPath($candidate.Value)
                }
                catch {
                    return $null
                }
            }
        }
        return $null
    }
    try {
        return [IO.Path]::GetFullPath($Executable)
    }
    catch {
        return $null
    }
}

function Resolve-WeatherOneShotArgumentValue {
    param(
        [AllowNull()][string]$Arguments,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $argumentText = if ($null -eq $Arguments) { "" } else { $Arguments }
    $pattern = '(?i)(?:^|\s)-' + [regex]::Escape($Name) +
        '(?:\s+|:)(?:"(?<double>[^"]+)"|''(?<single>[^'']+)''|(?<bare>\S+))'
    $matches = [regex]::Matches($argumentText, $pattern)
    if ($matches.Count -ne 1) {
        return $null
    }
    foreach ($groupName in @("double", "single", "bare")) {
        $candidate = $matches[0].Groups[$groupName]
        if ($candidate.Success -and -not [string]::IsNullOrWhiteSpace($candidate.Value)) {
            return $candidate.Value
        }
    }
    return $null
}

function Get-WeatherOneShotTaskObservation {
    param([Parameter(Mandatory = $true)][object]$ManifestContract)

    $manifest = $ManifestContract.Manifest
    $blockers = New-Object System.Collections.Generic.List[object]
    try {
        $tasks = @(Get-ScheduledTask `
            -TaskName ([string]$manifest.task.task_name) `
            -TaskPath ([string]$manifest.task.task_path) `
            -ErrorAction Stop)
    }
    catch {
        $tasks = @()
    }
    if ($tasks.Count -eq 0) {
        $blockers.Add((New-WeatherOneShotReadinessBlocker `
            -Code "TASK_NOT_FOUND" `
            -Detail "The manifest-bound scheduled task does not exist." `
            -Subject ([string]$manifest.task.task_name)))
        return [pscustomobject]@{ Snapshot = $null; Blockers = $blockers.ToArray() }
    }
    if ($tasks.Count -ne 1) {
        $blockers.Add((New-WeatherOneShotReadinessBlocker `
            -Code "TASK_NOT_UNIQUE" `
            -Detail "The manifest-bound task lookup did not resolve exactly one task." `
            -Subject ([string]$manifest.task.task_name) `
            -Expected "1" `
            -Actual ([string]$tasks.Count)))
        return [pscustomobject]@{ Snapshot = $null; Blockers = $blockers.ToArray() }
    }

    $task = $tasks[0]
    $actions = @($task.Actions)
    if ($actions.Count -ne 1 -or
        ($actions.Count -eq 1 -and
            -not [string]::IsNullOrEmpty([string]$actions[0].Id))) {
        $blockers.Add((New-WeatherOneShotReadinessBlocker `
            -Code "TASK_ACTION_MISMATCH" `
            -Detail "The manifest-bound task must have exactly one action." `
            -Subject ([string]$manifest.task.task_name) `
            -Expected "1" `
            -Actual ([string]$actions.Count)))
    }
    $triggers = @($task.Triggers)
    $trigger = if ($triggers.Count -eq 1) { $triggers[0] } else { $null }
    $cimClass = Get-WeatherOneShotPropertyValue -Value $trigger -Name "CimClass"
    $repetition = Get-WeatherOneShotPropertyValue -Value $trigger -Name "Repetition"
    $repetitionInterval = [string](
        Get-WeatherOneShotPropertyValue -Value $repetition -Name "Interval"
    )
    $repetitionDuration = [string](
        Get-WeatherOneShotPropertyValue -Value $repetition -Name "Duration"
    )
    $repetitionStops = [bool](
        Get-WeatherOneShotPropertyValue -Value $repetition -Name "StopAtDurationEnd"
    )
    $isOneShot = ($null -ne $trigger -and
        [string](Get-WeatherOneShotPropertyValue -Value $cimClass -Name "CimClassName") -ceq
            "MSFT_TaskTimeTrigger" -and
        [bool](Get-WeatherOneShotPropertyValue -Value $trigger -Name "Enabled") -and
        [string]::IsNullOrEmpty([string](
            Get-WeatherOneShotPropertyValue -Value $trigger -Name "Id"
        )) -and
        [string]::IsNullOrEmpty([string](
            Get-WeatherOneShotPropertyValue -Value $trigger -Name "EndBoundary"
        )) -and
        [string]::IsNullOrEmpty([string](
            Get-WeatherOneShotPropertyValue -Value $trigger -Name "RandomDelay"
        )) -and
        [string]::IsNullOrEmpty([string](
            Get-WeatherOneShotPropertyValue -Value $trigger -Name "ExecutionTimeLimit"
        )) -and
        [string]::IsNullOrEmpty($repetitionInterval) -and
        [string]::IsNullOrEmpty($repetitionDuration) -and
        -not $repetitionStops)
    if (-not $isOneShot) {
        $blockers.Add((New-WeatherOneShotReadinessBlocker `
            -Code "TASK_TRIGGER_NOT_ONE_SHOT" `
            -Detail "The manifest-bound task must have one enabled time trigger." `
            -Subject ([string]$manifest.task.task_name)))
    }
    if ($blockers.Count -ne 0) {
        return [pscustomobject]@{ Snapshot = $null; Blockers = $blockers.ToArray() }
    }

    $actionFile = Resolve-WeatherOneShotActionFile `
        -Executable ([string]$actions[0].Execute) `
        -Arguments ([string]$actions[0].Arguments)
    if ([string]::IsNullOrWhiteSpace($actionFile)) {
        $blockers.Add((New-WeatherOneShotReadinessBlocker `
            -Code "TASK_ACTION_MISMATCH" `
            -Detail "The registered action file could not be resolved unambiguously." `
            -Subject ([string]$manifest.task.task_name)))
        return [pscustomobject]@{ Snapshot = $null; Blockers = $blockers.ToArray() }
    }
    $readinessManifestPath = Resolve-WeatherOneShotArgumentValue `
        -Arguments ([string]$actions[0].Arguments) `
        -Name "ReadinessManifestPath"
    $readinessManifestSha256 = Resolve-WeatherOneShotArgumentValue `
        -Arguments ([string]$actions[0].Arguments) `
        -Name "ExpectedReadinessManifestSha256"
    try {
        $triggerAt = [DateTimeOffset]::Parse(
            [string](Get-WeatherOneShotPropertyValue `
                -Value $trigger -Name "StartBoundary"),
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::AssumeLocal
        ).ToString("o")
    }
    catch {
        $blockers.Add((New-WeatherOneShotReadinessBlocker `
            -Code "TASK_TRIGGER_MISMATCH" `
            -Detail "The registered one-shot trigger time is unreadable." `
            -Subject ([string]$manifest.task.task_name)))
        return [pscustomobject]@{ Snapshot = $null; Blockers = $blockers.ToArray() }
    }
    try {
        $taskInfo = $task | Get-ScheduledTaskInfo -ErrorAction Stop
    }
    catch {
        $blockers.Add((New-WeatherOneShotReadinessBlocker `
            -Code "TASK_INFO_UNAVAILABLE" `
            -Detail "Task Scheduler next-run information is unavailable." `
            -Subject ([string]$manifest.task.task_name)))
        return [pscustomobject]@{ Snapshot = $null; Blockers = $blockers.ToArray() }
    }
    $nextRunTime = $null
    if ($null -ne $taskInfo.NextRunTime -and
        [datetime]$taskInfo.NextRunTime -gt [datetime]::MinValue) {
        $nextRunTime = ([DateTimeOffset][datetime]$taskInfo.NextRunTime).ToString("o")
    }
    $actionExecutable = $null
    try { $actionExecutable = [IO.Path]::GetFullPath([string]$actions[0].Execute) }
    catch { }
    $workingDirectory = $null
    try {
        $workingDirectory = [IO.Path]::GetFullPath(
            [string]$actions[0].WorkingDirectory
        )
    }
    catch { }
    $lastRunTime = $null
    if ($null -ne $taskInfo.LastRunTime -and
        [datetime]$taskInfo.LastRunTime -gt [datetime]::MinValue) {
        $lastRunTime = ([DateTimeOffset][datetime]$taskInfo.LastRunTime).ToString("o")
    }

    return [pscustomobject]@{
        Snapshot = [pscustomobject][ordered]@{
            task_name = [string]$task.TaskName
            task_path = ConvertTo-WeatherOneShotTaskPath -Value ([string]$task.TaskPath)
            enabled = [bool]$task.Settings.Enabled
            state = [string]$task.State
            principal_user_id = [string]$task.Principal.UserId
            principal_logon_type = [string]$task.Principal.LogonType
            principal_run_level = [string]$task.Principal.RunLevel
            principal_id = [string]$task.Principal.Id
            principal_display_name = [string]$task.Principal.DisplayName
            principal_group_id = [string]$task.Principal.GroupId
            principal_process_token_sid_type = [string]$task.Principal.ProcessTokenSidType
            principal_required_privilege_count = @(
                $task.Principal.RequiredPrivilege |
                    Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
            ).Count
            settings_multiple_instances = [string]$task.Settings.MultipleInstances
            settings_execution_time_limit = [string]$task.Settings.ExecutionTimeLimit
            settings_start_when_available = [bool]$task.Settings.StartWhenAvailable
            settings_allow_demand_start = [bool]$task.Settings.AllowDemandStart
            settings_wake_to_run = [bool]$task.Settings.WakeToRun
            settings_restart_count = [int]$task.Settings.RestartCount
            settings_restart_interval = [string]$task.Settings.RestartInterval
            settings_allow_start_if_on_batteries = -not [bool]$task.Settings.DisallowStartIfOnBatteries
            settings_stop_if_going_on_batteries = [bool]$task.Settings.StopIfGoingOnBatteries
            settings_run_only_if_idle = [bool]$task.Settings.RunOnlyIfIdle
            settings_run_only_if_network_available = [bool]$task.Settings.RunOnlyIfNetworkAvailable
            action_executable = $actionExecutable
            action_arguments = [string]$actions[0].Arguments
            working_directory = $workingDirectory
            action_file = $actionFile
            trigger_at_local = $triggerAt
            repetition_interval = $repetitionInterval
            next_run_time = $nextRunTime
            last_run_time = $lastRunTime
            readiness_manifest_path = $readinessManifestPath
            expected_readiness_manifest_sha256 = $readinessManifestSha256
        }
        Blockers = @()
    }
}

function Test-WeatherOneShotReadinessSnapshot {
    param(
        [Parameter(Mandatory = $true)][object]$ManifestContract,
        [AllowNull()][object]$ObservedTaskSnapshot,
        [Parameter(Mandatory = $true)][string]$CurrentBootIdentity,
        [object[]]$InitialBlockers = @(),
        [DateTimeOffset]$ObservedAtLocal = [DateTimeOffset]::Now,
        [ValidateSet("PreTrigger", "Execution", "Active")]
        [string]$ObservationMode = "PreTrigger"
    )

    $manifest = $ManifestContract.Manifest
    $blockers = New-Object System.Collections.Generic.List[object]
    foreach ($blocker in @($InitialBlockers)) {
        if ($null -ne $blocker) {
            $blockers.Add($blocker)
        }
    }

    try {
        $expectedBoot = ConvertTo-WeatherOneShotInstant `
            -Value ([string]$manifest.boot_identity.last_boot_up_time_utc) `
            -FieldName "boot_identity.last_boot_up_time_utc" `
            -RequireUtc
        $actualBoot = ConvertTo-WeatherOneShotInstant `
            -Value $CurrentBootIdentity `
            -FieldName "current boot identity" `
            -RequireUtc
        if ($expectedBoot.UtcDateTime.Ticks -ne $actualBoot.UtcDateTime.Ticks) {
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code "STALE_BOOT_IDENTITY" `
                -Detail "The one-shot was reviewed for a different Windows boot." `
                -Subject "boot_identity.last_boot_up_time_utc" `
                -Expected (ConvertTo-WeatherOneShotUtcText -Value $expectedBoot) `
                -Actual (ConvertTo-WeatherOneShotUtcText -Value $actualBoot)))
        }
    }
    catch {
        $code = [string]$_.Exception.Data["weather_one_shot_readiness_blocker_code"]
        if ([string]::IsNullOrWhiteSpace($code)) {
            $code = "BOOT_IDENTITY_UNAVAILABLE"
        }
        $blockers.Add((New-WeatherOneShotReadinessBlocker `
            -Code $code `
            -Detail $_.Exception.Message `
            -Subject "boot_identity.last_boot_up_time_utc"))
    }

    $dependencyFiles = New-Object System.Collections.Generic.List[object]
    [long]$aggregateDependencyBytes = 0
    foreach ($dependency in @($manifest.dependencies)) {
        $path = [string]$dependency.path
        try {
            $remainingBytes = (
                $script:OneShotReadinessMaximumAggregateDependencyBytes -
                $aggregateDependencyBytes
            )
            if ($remainingBytes -le 0) {
                $blockers.Add((New-WeatherOneShotReadinessBlocker `
                    -Code "DEPENDENCY_AGGREGATE_TOO_LARGE" `
                    -Detail "Manifest-bound dependencies exceed the aggregate readiness hash budget." `
                    -Subject "dependencies"))
                break
            }
            $readLimit = [Math]::Min(
                [long]$script:OneShotReadinessMaximumDependencyBytes,
                [long]$remainingBytes
            )
            $tooLargeCode = if ($remainingBytes -lt
                $script:OneShotReadinessMaximumDependencyBytes) {
                "DEPENDENCY_AGGREGATE_TOO_LARGE"
            }
            else {
                "DEPENDENCY_TOO_LARGE"
            }
            $snapshot = Read-WeatherOneShotRegularFileSnapshot `
                -Path $path `
                -MaximumBytes $readLimit `
                -UnavailableCode "DEPENDENCY_UNAVAILABLE" `
                -UnsafeCode "DEPENDENCY_UNSAFE_PATH" `
                -TooLargeCode $tooLargeCode `
                -Label "Manifest-bound dependency"
            $aggregateDependencyBytes += [long]$snapshot.length
            $dependencyFiles.Add([pscustomobject]@{
                Dependency = $dependency
                Sha256 = [string]$snapshot.sha256
            })
            $snapshot.bytes = $null
        }
        catch {
            $code = [string]$_.Exception.Data["weather_one_shot_readiness_blocker_code"]
            if ([string]::IsNullOrWhiteSpace($code)) {
                $code = "DEPENDENCY_UNAVAILABLE"
            }
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code $code `
                -Detail $_.Exception.Message `
                -Subject $path))
            if ($code -ceq "DEPENDENCY_AGGREGATE_TOO_LARGE") {
                break
            }
        }
    }
    if ($aggregateDependencyBytes -gt
        $script:OneShotReadinessMaximumAggregateDependencyBytes) {
        $blockers.Add((New-WeatherOneShotReadinessBlocker `
            -Code "DEPENDENCY_AGGREGATE_TOO_LARGE" `
            -Detail "Manifest-bound dependencies exceed the aggregate readiness hash budget." `
            -Subject "dependencies" `
            -Expected ("<={0}" -f $script:OneShotReadinessMaximumAggregateDependencyBytes) `
            -Actual ([string]$aggregateDependencyBytes)))
    }
    else {
        foreach ($record in $dependencyFiles) {
            $dependency = $record.Dependency
            $actualHash = [string]$record.Sha256
            if ($actualHash -cne [string]$dependency.sha256) {
                $blockers.Add((New-WeatherOneShotReadinessBlocker `
                    -Code "STALE_DEPENDENCY_HASH" `
                    -Detail "A manifest-bound dependency changed after review." `
                    -Subject ([string]$dependency.path) `
                    -Expected ([string]$dependency.sha256) `
                    -Actual $actualHash))
            }
        }
    }

    if ($null -ne $ObservedTaskSnapshot) {
        if ([string]$ObservedTaskSnapshot.task_name -ine [string]$manifest.task.task_name -or
            (ConvertTo-WeatherOneShotTaskPath -Value ([string]$ObservedTaskSnapshot.task_path)) -ine
                [string]$manifest.task.task_path) {
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code "TASK_IDENTITY_MISMATCH" `
                -Detail "The observed task identity differs from the manifest." `
                -Subject ([string]$manifest.task.task_name)))
        }
        if (-not [bool]$ObservedTaskSnapshot.enabled) {
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code "TASK_DISABLED" `
                -Detail "The manifest-bound one-shot task is disabled." `
                -Subject ([string]$manifest.task.task_name)))
        }
        if ($ObservationMode -ceq "PreTrigger") {
            if ([string]$ObservedTaskSnapshot.state -cne "Ready") {
                $blockers.Add((New-WeatherOneShotReadinessBlocker `
                    -Code "TASK_NOT_READY" `
                    -Detail "The manifest-bound one-shot must be in Scheduler Ready state before its trigger." `
                    -Subject ([string]$manifest.task.task_name) `
                    -Expected "Ready" `
                    -Actual ([string]$ObservedTaskSnapshot.state)))
            }
        }
        elseif ([string]$ObservedTaskSnapshot.state -cne "Running") {
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code "TASK_NOT_RUNNING" `
                -Detail "The execution-entry gate requires the manifest-bound task to be running." `
                -Subject ([string]$manifest.task.task_name) `
                -Expected "Running" `
                -Actual ([string]$ObservedTaskSnapshot.state)))
        }
        if ([string]$ObservedTaskSnapshot.principal_user_id -ine
                [string]$manifest.principal.user_id -or
            [string]$ObservedTaskSnapshot.principal_logon_type -cne
                [string]$manifest.principal.logon_type -or
            [string]$ObservedTaskSnapshot.principal_run_level -cne
                [string]$manifest.principal.run_level -or
            [string]$ObservedTaskSnapshot.principal_id -cne "Author" -or
            -not [string]::IsNullOrEmpty(
                [string]$ObservedTaskSnapshot.principal_display_name
            ) -or
            -not [string]::IsNullOrEmpty(
                [string]$ObservedTaskSnapshot.principal_group_id
            ) -or
            [string]$ObservedTaskSnapshot.principal_process_token_sid_type -cne
                "Default" -or
            [int]$ObservedTaskSnapshot.principal_required_privilege_count -ne 0) {
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code "TASK_PRINCIPAL_MISMATCH" `
                -Detail "The registered task principal is not the exact reviewed S4U/Limited principal." `
                -Subject ([string]$manifest.task.task_name)))
        }
        if ([string]$ObservedTaskSnapshot.settings_multiple_instances -cne
                [string]$manifest.settings.multiple_instances -or
            [string]$ObservedTaskSnapshot.settings_execution_time_limit -cne
                [string]$manifest.settings.execution_time_limit -or
            [bool]$ObservedTaskSnapshot.settings_start_when_available -ne
                [bool]$manifest.settings.start_when_available -or
            [bool]$ObservedTaskSnapshot.settings_allow_demand_start -ne
                [bool]$manifest.settings.allow_demand_start -or
            [bool]$ObservedTaskSnapshot.settings_wake_to_run -ne
                [bool]$manifest.settings.wake_to_run -or
            [int]$ObservedTaskSnapshot.settings_restart_count -ne
                [int]$manifest.settings.restart_count -or
            [string]$ObservedTaskSnapshot.settings_restart_interval -cne
                [string]$manifest.settings.restart_interval -or
            [bool]$ObservedTaskSnapshot.settings_allow_start_if_on_batteries -ne
                [bool]$manifest.settings.allow_start_if_on_batteries -or
            [bool]$ObservedTaskSnapshot.settings_stop_if_going_on_batteries -ne
                [bool]$manifest.settings.stop_if_going_on_batteries -or
            [bool]$ObservedTaskSnapshot.settings_run_only_if_idle -ne
                [bool]$manifest.settings.run_only_if_idle -or
            [bool]$ObservedTaskSnapshot.settings_run_only_if_network_available -ne
                [bool]$manifest.settings.run_only_if_network_available) {
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code "TASK_SETTINGS_MISMATCH" `
                -Detail "The registered task safety settings differ from the reviewed manifest." `
                -Subject ([string]$manifest.task.task_name)))
        }
        if (-not [string]::IsNullOrWhiteSpace(
                [string]$ObservedTaskSnapshot.repetition_interval)) {
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code "TASK_REPETITION_CONFIGURED" `
                -Detail "The manifest-bound one-shot may not have a repetition interval." `
                -Subject ([string]$manifest.task.task_name) `
                -Expected "" `
                -Actual ([string]$ObservedTaskSnapshot.repetition_interval)))
        }
        $observedAction = $null
        try {
            $observedAction = [IO.Path]::GetFullPath([string]$ObservedTaskSnapshot.action_file)
        }
        catch { }
        $actionFileMatches = (
            -not [string]::IsNullOrWhiteSpace($observedAction) -and
            $observedAction -ieq [string]$manifest.task.action_file
        )
        $expectedArguments = $null
        try {
            $expectedArguments = Expand-WeatherOneShotArgumentsTemplate `
                -Template ([string]$manifest.task.arguments_template) `
                -ManifestPath ([string]$ManifestContract.ManifestPath) `
                -ManifestSha256 ([string]$ManifestContract.ManifestSha256)
        }
        catch { }
        if (-not $actionFileMatches -or
            [string]$ObservedTaskSnapshot.action_executable -ine
                [string]$manifest.task.executable -or
            [string]$ObservedTaskSnapshot.action_arguments -cne $expectedArguments -or
            [string]$ObservedTaskSnapshot.working_directory -ine
                [string]$manifest.task.working_directory) {
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code "TASK_ACTION_MISMATCH" `
                -Detail "The registered executable, complete arguments, or working directory differs from the reviewed manifest." `
                -Subject ([string]$manifest.task.task_name)))
        }
        $observedReadinessManifest = $null
        try {
            $observedReadinessManifest = [IO.Path]::GetFullPath(
                [string]$ObservedTaskSnapshot.readiness_manifest_path
            )
        }
        catch { }
        if ([string]::IsNullOrWhiteSpace($observedReadinessManifest) -or
            $observedReadinessManifest -ine [string]$ManifestContract.ManifestPath -or
            [string]$ObservedTaskSnapshot.expected_readiness_manifest_sha256 -ine
                [string]$ManifestContract.ManifestSha256) {
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code "TASK_READINESS_BINDING_MISMATCH" `
                -Detail "The registered action does not carry the exact readiness manifest path and hash." `
                -Subject ([string]$manifest.task.task_name)))
        }
        $expectedTrigger = $null
        try {
            $expectedTrigger = ConvertTo-WeatherOneShotInstant `
                -Value ([string]$manifest.task.trigger_at_local) `
                -FieldName "task.trigger_at_local"
            $observedTrigger = ConvertTo-WeatherOneShotInstant `
                -Value ([string]$ObservedTaskSnapshot.trigger_at_local) `
                -FieldName "observed task trigger"
            if ($expectedTrigger.UtcDateTime.Ticks -ne $observedTrigger.UtcDateTime.Ticks) {
                $blockers.Add((New-WeatherOneShotReadinessBlocker `
                    -Code "TASK_TRIGGER_MISMATCH" `
                    -Detail "The registered task trigger differs from the reviewed manifest." `
                    -Subject ([string]$manifest.task.task_name) `
                    -Expected $expectedTrigger.ToString("o") `
                    -Actual $observedTrigger.ToString("o")))
            }
        }
        catch {
            $blockers.Add((New-WeatherOneShotReadinessBlocker `
                -Code "TASK_TRIGGER_MISMATCH" `
                -Detail "The registered task trigger could not be compared to the manifest." `
                -Subject ([string]$manifest.task.task_name)))
        }
        if ($ObservationMode -ceq "PreTrigger") {
            if ([string]::IsNullOrWhiteSpace(
                    [string]$ObservedTaskSnapshot.next_run_time
                )) {
                $blockers.Add((New-WeatherOneShotReadinessBlocker `
                    -Code "TASK_NEXT_RUN_UNAVAILABLE" `
                    -Detail "Task Scheduler does not report a future run for the manifest-bound one-shot." `
                    -Subject ([string]$manifest.task.task_name)))
            }
            else {
                try {
                    $observedNextRun = ConvertTo-WeatherOneShotInstant `
                        -Value ([string]$ObservedTaskSnapshot.next_run_time) `
                        -FieldName "observed task next_run_time"
                    if ($null -eq $expectedTrigger -or
                        $expectedTrigger.UtcDateTime.Ticks -ne
                            $observedNextRun.UtcDateTime.Ticks) {
                        $blockers.Add((New-WeatherOneShotReadinessBlocker `
                            -Code "TASK_NEXT_RUN_MISMATCH" `
                            -Detail "Task Scheduler next run differs from the reviewed trigger." `
                            -Subject ([string]$manifest.task.task_name) `
                            -Expected ([string]$manifest.task.trigger_at_local) `
                            -Actual $observedNextRun.ToString("o")))
                    }
                    if ($observedNextRun.UtcDateTime.Ticks -le
                        $ObservedAtLocal.UtcDateTime.Ticks) {
                        $blockers.Add((New-WeatherOneShotReadinessBlocker `
                            -Code "TASK_NEXT_RUN_NOT_FUTURE" `
                            -Detail "Task Scheduler next run is not in the future." `
                            -Subject ([string]$manifest.task.task_name) `
                            -Expected (">{0}" -f $ObservedAtLocal.ToString("o")) `
                            -Actual $observedNextRun.ToString("o")))
                    }
                }
                catch {
                    $blockers.Add((New-WeatherOneShotReadinessBlocker `
                        -Code "TASK_NEXT_RUN_UNAVAILABLE" `
                        -Detail "Task Scheduler next-run time could not be compared." `
                        -Subject ([string]$manifest.task.task_name)))
                }
            }
            if ([string]::IsNullOrWhiteSpace(
                    [string]$ObservedTaskSnapshot.last_run_time
                )) {
                $blockers.Add((New-WeatherOneShotReadinessBlocker `
                    -Code "TASK_LAST_RUN_UNAVAILABLE" `
                    -Detail "Task Scheduler does not expose the one-shot's prior-run state." `
                    -Subject ([string]$manifest.task.task_name)))
            }
            else {
                try {
                    $lastRun = ConvertTo-WeatherOneShotInstant `
                        -Value ([string]$ObservedTaskSnapshot.last_run_time) `
                        -FieldName "observed task last_run_time"
                    if ($lastRun.UtcDateTime -ge [datetime]'2000-01-01T00:00:00Z') {
                        $blockers.Add((New-WeatherOneShotReadinessBlocker `
                            -Code "TASK_ALREADY_RAN" `
                            -Detail "The manifest-bound one-shot has already run and is spent." `
                            -Subject ([string]$manifest.task.task_name) `
                            -Actual $lastRun.ToString("o")))
                    }
                }
                catch {
                    $blockers.Add((New-WeatherOneShotReadinessBlocker `
                        -Code "TASK_LAST_RUN_UNAVAILABLE" `
                        -Detail "Task Scheduler prior-run time could not be compared." `
                        -Subject ([string]$manifest.task.task_name)))
                }
            }
        }
        else {
            $entryDeadline = $null
            $observationDeadline = $null
            if ($null -ne $expectedTrigger) {
                $entryDeadline = $expectedTrigger.Add(
                    $script:OneShotReadinessExecutionWindow
                )
                $teardownDeadline = ConvertTo-WeatherOneShotInstant `
                    -Value ([string]$manifest.admission.teardown_deadline_at_local) `
                    -FieldName "admission.teardown_deadline_at_local"
                if ($teardownDeadline.UtcDateTime.Ticks -lt
                    $entryDeadline.UtcDateTime.Ticks) {
                    $entryDeadline = $teardownDeadline
                }
                $observationDeadline = $entryDeadline
                if ($ObservationMode -ceq "Active") {
                    $runtimeLimit = [Xml.XmlConvert]::ToTimeSpan(
                        [string]$manifest.settings.execution_time_limit
                    )
                    $observationDeadline = $expectedTrigger.Add($runtimeLimit)
                    if ($teardownDeadline.UtcDateTime.Ticks -lt
                        $observationDeadline.UtcDateTime.Ticks) {
                        $observationDeadline = $teardownDeadline
                    }
                }
                if ($ObservedAtLocal.UtcDateTime.Ticks -lt
                        $expectedTrigger.UtcDateTime.Ticks -or
                    $ObservedAtLocal.UtcDateTime.Ticks -gt
                        $observationDeadline.UtcDateTime.Ticks) {
                    $blockers.Add((New-WeatherOneShotReadinessBlocker `
                        -Code "TASK_TRIGGER_OUTSIDE_EXECUTION_WINDOW" `
                        -Detail "The runtime observation was not inside the reviewed execution window." `
                        -Subject ([string]$manifest.task.task_name) `
                        -Expected ("{0}..{1}" -f
                            $expectedTrigger.ToString("o"),
                            $observationDeadline.ToString("o")) `
                        -Actual $ObservedAtLocal.ToString("o")))
                }
            }
            if ([string]::IsNullOrWhiteSpace(
                    [string]$ObservedTaskSnapshot.last_run_time
                )) {
                $blockers.Add((New-WeatherOneShotReadinessBlocker `
                    -Code "TASK_CURRENT_RUN_MISMATCH" `
                    -Detail "Task Scheduler does not expose a current run correlated to this trigger." `
                    -Subject ([string]$manifest.task.task_name)))
            }
            else {
                try {
                    $lastRun = ConvertTo-WeatherOneShotInstant `
                        -Value ([string]$ObservedTaskSnapshot.last_run_time) `
                        -FieldName "observed task last_run_time"
                    if ($null -eq $expectedTrigger -or
                        $null -eq $entryDeadline -or
                        $lastRun.UtcDateTime.Ticks -lt
                            $expectedTrigger.UtcDateTime.Ticks -or
                        $lastRun.UtcDateTime.Ticks -gt
                            $entryDeadline.UtcDateTime.Ticks -or
                        $lastRun.UtcDateTime.Ticks -gt
                            $ObservedAtLocal.UtcDateTime.Ticks) {
                        $blockers.Add((New-WeatherOneShotReadinessBlocker `
                            -Code "TASK_CURRENT_RUN_MISMATCH" `
                            -Detail "Task Scheduler's current run does not correlate to the reviewed trigger window." `
                            -Subject ([string]$manifest.task.task_name) `
                            -Actual $lastRun.ToString("o")))
                    }
                }
                catch {
                    $blockers.Add((New-WeatherOneShotReadinessBlocker `
                        -Code "TASK_CURRENT_RUN_MISMATCH" `
                        -Detail "Task Scheduler current-run time could not be compared." `
                        -Subject ([string]$manifest.task.task_name)))
                }
            }
        }
    }

    $ready = $blockers.Count -eq 0
    $blockerArray = $blockers.ToArray()
    $blockerCodes = [string[]]::new($blockerArray.Length)
    for ($index = 0; $index -lt $blockerArray.Length; $index += 1) {
        $blockerCodes[$index] = [string]$blockerArray[$index].code
    }
    return [pscustomobject][ordered]@{
        schema_version = $script:OneShotReadinessResultSchema
        status = if ($ready) { "PASS" } else { "BLOCKED" }
        ready = $ready
        observation_mode = $ObservationMode
        observed_at_local = $ObservedAtLocal.ToString("o")
        manifest_path = [string]$ManifestContract.ManifestPath
        manifest_sha256 = [string]$ManifestContract.ManifestSha256
        task_name = [string]$manifest.task.task_name
        task_path = [string]$manifest.task.task_path
        blocker_codes = $blockerCodes
        blockers = $blockerArray
        authority = "READ_ONLY_NO_SCHEDULER_MUTATION"
    }
}

function New-WeatherOneShotReadinessFailureResult {
    param(
        [Parameter(Mandatory = $true)][string]$Code,
        [Parameter(Mandatory = $true)][string]$Detail,
        [AllowNull()][string]$Path,
        [AllowNull()][string]$Sha256,
        [ValidateSet("PreTrigger", "Execution", "Active")]
        [string]$ObservationMode = "PreTrigger"
    )

    $blocker = New-WeatherOneShotReadinessBlocker -Code $Code -Detail $Detail
    return [pscustomobject][ordered]@{
        schema_version = $script:OneShotReadinessResultSchema
        status = "BLOCKED"
        ready = $false
        observation_mode = $ObservationMode
        observed_at_local = (Get-Date).ToString("o")
        manifest_path = $Path
        manifest_sha256 = $Sha256
        task_name = $null
        task_path = $null
        blocker_codes = @($Code)
        blockers = @($blocker)
        authority = "READ_ONLY_NO_SCHEDULER_MUTATION"
    }
}

if ($LibraryOnly) {
    return
}

$result = $null
$registryLock = $null
$observationMode = if ($Mode -ceq "Assert") {
    "Execution"
}
elseif ($Mode -ceq "InspectActive") {
    "Active"
}
else {
    "PreTrigger"
}
try {
    if ([string]::IsNullOrWhiteSpace($ManifestPath) -or
        [string]::IsNullOrWhiteSpace($ExpectedManifestSha256)) {
        Throw-WeatherOneShotReadinessError `
            -Code "INVALID_ARGUMENT" `
            -Message "ManifestPath and ExpectedManifestSha256 are required."
    }
    try {
        $registryLockDeadline = [DateTime]::UtcNow.AddSeconds(5)
        do {
            try {
                # Validators are concurrent readers. Writer/resolver/recovery
                # own FileShare.None, so this still forms one resolution
                # barrier without allowing status to block an execution Assert.
                $registryLock = [IO.FileStream]::new(
                    $script:OneShotReadinessRegistryLockPath,
                    [IO.FileMode]::Open,
                    [IO.FileAccess]::Read,
                    [IO.FileShare]::Read
                )
            }
            catch [IO.IOException] {
                if ([DateTime]::UtcNow -ge $registryLockDeadline) { throw }
                Start-Sleep -Milliseconds 100
            }
        } while ($null -eq $registryLock)
        $registryLockItem = Get-Item `
            -LiteralPath $script:OneShotReadinessRegistryLockPath `
            -Force -ErrorAction Stop
        if ($registryLockItem.PSIsContainer -or
            ($registryLockItem.Attributes -band
                [IO.FileAttributes]::ReparsePoint)) {
            throw "registry lock is not a regular non-reparse file"
        }
    }
    catch {
        if ($null -ne $registryLock) {
            $registryLock.Dispose()
            $registryLock = $null
        }
        Throw-WeatherOneShotReadinessError `
            -Code "REGISTRY_LOCK_UNAVAILABLE" `
            -Message "The one-shot registry transaction lock could not be acquired."
    }
    $contract = Read-WeatherOneShotReadinessManifest `
        -Path $ManifestPath `
        -ExpectedSha256 $ExpectedManifestSha256
    $bootIdentity = Get-WeatherOneShotCurrentBootIdentity
    $taskObservation = Get-WeatherOneShotTaskObservation -ManifestContract $contract
    if ($Mode -ceq "InspectAuto" -and
        $null -ne $taskObservation.Snapshot -and
        [string]$taskObservation.Snapshot.state -ceq "Running") {
        $observationMode = "Active"
    }
    $result = Test-WeatherOneShotReadinessSnapshot `
        -ManifestContract $contract `
        -ObservedTaskSnapshot $taskObservation.Snapshot `
        -CurrentBootIdentity $bootIdentity `
        -InitialBlockers @($taskObservation.Blockers) `
        -ObservationMode $observationMode
}
catch {
    $code = [string]$_.Exception.Data["weather_one_shot_readiness_blocker_code"]
    if ([string]::IsNullOrWhiteSpace($code)) {
        $code = "VALIDATOR_ERROR"
    }
    $result = New-WeatherOneShotReadinessFailureResult `
        -Code $code `
        -Detail $_.Exception.Message `
        -Path $ManifestPath `
        -Sha256 $ExpectedManifestSha256.ToLowerInvariant() `
        -ObservationMode $observationMode
}

try {
    $result | ConvertTo-Json -Depth 6 -Compress
    $resultExitCode = if (
        $Mode -eq "Assert" -and -not [bool]$result.ready
    ) { 2 } else { 0 }
}
finally {
    if ($null -ne $registryLock) {
        $registryLock.Dispose()
    }
}
exit $resultExitCode
