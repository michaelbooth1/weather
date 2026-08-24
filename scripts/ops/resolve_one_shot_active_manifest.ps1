[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true)]
    [ValidateSet("TERMINAL", "SUPERSEDED")]
    [string]$Status,
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [string]$SuccessorSourceManifestPath = "",
    [ValidatePattern("^$|^[0-9a-f]{64}$")]
    [string]$ExpectedSuccessorManifestSha256 = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-WeatherOneShotAtomicResolution {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][byte[]]$Bytes
    )

    Remove-WeatherOneShotExactAtomicDebris `
        -Destination $Destination -ExpectedBytes $Bytes
    $directory = Split-Path -Parent $Destination
    $leaf = [IO.Path]::GetFileName($Destination)
    $temporary = Join-Path $directory (
        ".{0}.{1}.tmp" -f $leaf, [guid]::NewGuid().ToString("N")
    )
    $stream = $null
    $moved = $false
    try {
        $stream = [IO.FileStream]::new(
            $temporary,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
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

function Get-WeatherOneShotResolutionTerminalState {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$TaskPath
    )

    try {
        $tasks = @(
            Get-ScheduledTask -ErrorAction Stop |
                Where-Object {
                    [string]$_.TaskName -ieq $TaskName -and
                    [string]$_.TaskPath -ieq $TaskPath
                }
        )
    }
    catch {
        throw "Task Scheduler enumeration failed; task absence cannot be proved."
    }
    if ($tasks.Count -gt 1) {
        throw "Exact one-shot task identity resolved more than one Scheduler task."
    }
    if ($tasks.Count -eq 0) {
        return [pscustomobject][ordered]@{
            terminal = $true
            exists = $false
            state = "ABSENT"
            next_run_time = $null
            last_run_time = $null
            last_task_result = $null
        }
    }

    try {
        $info = Get-ScheduledTaskInfo -InputObject $tasks[0] -ErrorAction Stop
    }
    catch {
        throw "Exact one-shot task runtime state could not be queried."
    }
    $state = [string]$tasks[0].State
    return [pscustomobject][ordered]@{
        # Null NextRunTime does not defeat demand start after settings drift.
        # Resolution therefore accepts only proven absence or Disabled state.
        terminal = ($state -ceq "Disabled")
        exists = $true
        state = $state
        next_run_time = if ($null -eq $info.NextRunTime) {
            $null
        }
        else { ([datetime]$info.NextRunTime).ToString("o") }
        last_run_time = if ($null -eq $info.LastRunTime) {
            $null
        }
        else { ([datetime]$info.LastRunTime).ToString("o") }
        last_task_result = [int]$info.LastTaskResult
    }
}

function Assert-WeatherOneShotResolutionActivationMarker {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RegistryRoot
    )

    $snapshot = Read-WeatherOneShotRegularFileSnapshot `
        -Path $Path -MaximumBytes 1MB `
        -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
        -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -Label "One-shot registry activation marker"
    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $text = $utf8.GetString([byte[]]$snapshot.bytes)
        $marker = $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "One-shot registry activation marker is not valid bounded UTF-8 JSON."
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
        [IO.Path]::GetFullPath([string]$marker.registry_root) -ine $RegistryRoot -or
        [string]$marker.authority -cnotin @(
            "CREATE_ONLY_ONE_SHOT_ACTIVE_REGISTRY",
            "REVIEWED_EMPTY_REGISTRY_ACTIVATION_RECOVERY"
        ) -or
        [string]$marker.activated_at_local -notmatch
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$') {
        throw "One-shot registry activation marker does not match its exact contract."
    }
    try {
        [void][DateTimeOffset]::Parse(
            [string]$marker.activated_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch {
        throw "One-shot registry activation timestamp is invalid."
    }
}

function Read-WeatherOneShotExactStoredResolution {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][string]$Reason,
        [Parameter(Mandatory = $true)][string]$ReviewReference,
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$TaskPath,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ManifestSha256,
        [AllowNull()][string]$SuccessorManifestPath,
        [AllowNull()][string]$SuccessorManifestSha256
    )

    $snapshot = Read-WeatherOneShotRegularFileSnapshot `
        -Path $Path -MaximumBytes 1MB `
        -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
        -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -Label "Existing one-shot resolution"
    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $text = $utf8.GetString([byte[]]$snapshot.bytes)
        $stored = $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Existing one-shot resolution is not valid bounded UTF-8 JSON."
    }
    if (-not (Test-WeatherOneShotExactPropertySet `
            -Value $stored `
            -ExpectedNames @(
                "schema_version", "status", "resolved_at_local",
                "review_reference", "reason", "task_name", "task_path",
                "manifest_path", "manifest_sha256", "successor_manifest_path",
                "successor_manifest_sha256", "task_terminal_proof", "authority"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $stored.task_terminal_proof `
            -ExpectedNames @(
                "observed_at_local", "exists", "state", "next_run_time",
                "last_run_time", "last_task_result", "cannot_execute"
            )) -or
        [string]$stored.schema_version -cne
            "weather_one_shot_readiness_resolution_v1" -or
        [string]$stored.status -cne $Status -or
        [string]$stored.reason -cne $Reason -or
        [string]$stored.review_reference -cne $ReviewReference -or
        [string]$stored.task_name -cne $TaskName -or
        [string]$stored.task_path -cne $TaskPath -or
        [IO.Path]::GetFullPath([string]$stored.manifest_path) -ine
            [IO.Path]::GetFullPath($ManifestPath) -or
        [string]$stored.manifest_sha256 -cne $ManifestSha256 -or
        [string]$stored.successor_manifest_path -ine
            [string]$SuccessorManifestPath -or
        [string]$stored.successor_manifest_sha256 -cne
            [string]$SuccessorManifestSha256 -or
        $stored.task_terminal_proof.exists -isnot [bool] -or
        $stored.task_terminal_proof.cannot_execute -isnot [bool] -or
        -not [bool]$stored.task_terminal_proof.cannot_execute -or
        [string]$stored.authority -cne
            "REVIEWED_CREATE_ONLY_ONE_SHOT_RESOLUTION_NO_SCHEDULER_MUTATION") {
        throw "Existing one-shot resolution does not exactly match this recovery request."
    }
    try {
        $resolvedAt = [DateTimeOffset]::Parse(
            [string]$stored.resolved_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
        $observedAt = [DateTimeOffset]::Parse(
            [string]$stored.task_terminal_proof.observed_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch {
        throw "Existing one-shot resolution timestamps are invalid."
    }
    $proofExists = [bool]$stored.task_terminal_proof.exists
    $proofState = [string]$stored.task_terminal_proof.state
    if ([string]$stored.resolved_at_local -notmatch
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$' -or
        [string]$stored.task_terminal_proof.observed_at_local -notmatch
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$' -or
        $observedAt -gt $resolvedAt -or
        ($resolvedAt - $observedAt) -gt [TimeSpan]::FromMinutes(5) -or
        $resolvedAt -gt [DateTimeOffset]::Now.AddMinutes(5) -or
        (-not $proofExists -and $proofState -cne "ABSENT") -or
        ($proofExists -and $proofState -cne "Disabled")) {
        throw "Existing one-shot resolution terminal proof is incoherent."
    }
    return $stored
}

function Publish-WeatherOneShotExactSuccessor {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][string]$TaskName
    )

    if (Test-Path -LiteralPath $Destination -PathType Leaf -ErrorAction Stop) {
        $existing = Read-WeatherOneShotRegularFileSnapshot `
            -Path $Destination -MaximumBytes 64KB `
            -UnavailableCode "MANIFEST_UNAVAILABLE" `
            -UnsafeCode "MANIFEST_UNSAFE_PATH" `
            -TooLargeCode "MANIFEST_UNSAFE_PATH" `
            -Label "Existing successor one-shot manifest"
        if ([string]$existing.sha256 -cne $ExpectedSha256) {
            throw "Existing successor anchor does not contain the reviewed bytes."
        }
    }
    else {
        Write-WeatherOneShotAtomicResolution `
            -Destination $Destination -Bytes $Bytes
    }
    Write-WeatherOneShotManifestIndexEvent `
        -ManifestPath $Destination -ManifestSha256 $ExpectedSha256 `
        -TaskName $TaskName | Out-Null
    Read-WeatherOneShotReadinessManifest `
        -Path $Destination -ExpectedSha256 $ExpectedSha256 | Out-Null
}

if ([string]::IsNullOrWhiteSpace($Reason) -or $Reason.Length -gt 4096 -or
    [string]::IsNullOrWhiteSpace($ReviewReference) -or
    $ReviewReference.Length -gt 4096) {
    throw "Reason and ReviewReference must be non-empty and no longer than 4096 characters."
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$registryLockPath = Join-Path $RepoRoot "one_shot_registry.lock"
$registryLock = [IO.FileStream]::new(
    $registryLockPath,
    [IO.FileMode]::Open,
    [IO.FileAccess]::ReadWrite,
    [IO.FileShare]::None
)
try {
$registryLockItem = Get-Item -LiteralPath $registryLockPath -ErrorAction Stop
if ($registryLockItem.PSIsContainer -or
    ($registryLockItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "One-shot registry lock must be a regular non-reparse file."
}
$registryRoot = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "data\one_shot_readiness\active")
)
$registryItem = Get-Item -LiteralPath $registryRoot -ErrorAction Stop
if (-not $registryItem.PSIsContainer -or
    ($registryItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "Active one-shot registry must be a regular non-reparse directory."
}
$ManifestPath = [IO.Path]::GetFullPath($ManifestPath)
if ((Split-Path -Parent $ManifestPath) -ine $registryRoot) {
    throw "ManifestPath must be a canonical active one-shot registry entry."
}
$leaf = [IO.Path]::GetFileName($ManifestPath)
if ($leaf -cnotmatch
    '^(?<task>Weather[A-Za-z0-9._-]{1,119})\.(?<sha>[0-9a-f]{64})\.manifest\.json$' -or
    [string]$Matches.sha -cne $ExpectedManifestSha256) {
    throw "Manifest filename does not bind the exact task and reviewed hash."
}
$taskName = [string]$Matches.task
$validator = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "scripts\ops\one_shot_readiness.ps1")
)
if ($validator -ine [IO.Path]::GetFullPath(
        (Join-Path $PSScriptRoot "one_shot_readiness.ps1")
    )) {
    throw "RepoRoot must identify the repository containing this resolver."
}
$requestedManifestPath = $ManifestPath
$requestedManifestSha256 = $ExpectedManifestSha256
. $validator -LibraryOnly
$ManifestPath = $requestedManifestPath
$ExpectedManifestSha256 = $requestedManifestSha256
Assert-WeatherOneShotResolutionActivationMarker `
    -Path (Join-Path $RepoRoot "one_shot_registry_activation.json") `
    -RegistryRoot $registryRoot
$contract = Read-WeatherOneShotReadinessManifest `
    -Path $ManifestPath -ExpectedSha256 $ExpectedManifestSha256 `
    -AllowResolvedManifest -AllowResolutionIndexRepair
if ([string]$contract.Manifest.task.task_name -cne $taskName) {
    throw "Registry filename task identity disagrees with the manifest."
}

$resolutionPath = $ManifestPath.Substring(
    0,
    $ManifestPath.Length - ".manifest.json".Length
) + ".resolution.json"

$successorPath = $null
$successorSha256 = $null
$successorBytes = $null
$successorPendingPath = $null
if ($Status -eq "SUPERSEDED") {
    if ($ExpectedSuccessorManifestSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "SUPERSEDED resolution requires an exact reviewed successor SHA-256."
    }
    if ($ExpectedSuccessorManifestSha256 -ceq $ExpectedManifestSha256) {
        throw "Successor hash must differ from the resolved manifest hash."
    }
    $successorPendingPath = Join-Path $registryRoot `
        "$taskName.$ExpectedSuccessorManifestSha256.successor.pending.json"
    if (-not (Test-Path -LiteralPath $successorPendingPath -PathType Leaf)) {
        if ([string]::IsNullOrWhiteSpace($SuccessorSourceManifestPath)) {
            throw "SUPERSEDED requires a source until its exact pending successor is durably staged."
        }
        $successorSource = [IO.Path]::GetFullPath($SuccessorSourceManifestPath)
        $sourceSnapshot = Read-WeatherOneShotRegularFileSnapshot `
            -Path $successorSource -MaximumBytes 64KB `
            -UnavailableCode "MANIFEST_UNAVAILABLE" `
            -UnsafeCode "MANIFEST_UNSAFE_PATH" `
            -TooLargeCode "MANIFEST_UNSAFE_PATH" `
            -Label "Reviewed successor one-shot manifest"
        if ([string]$sourceSnapshot.sha256 -cne
            $ExpectedSuccessorManifestSha256) {
            throw "Successor source does not match its reviewed SHA-256."
        }
        $reviewedSuccessorContract = Read-WeatherOneShotReadinessManifest `
            -Path $successorSource `
            -ExpectedSha256 $ExpectedSuccessorManifestSha256 `
            -AllowUnanchoredSource
        if ([string]$reviewedSuccessorContract.Manifest.task.task_name -cne
                $taskName -or
            [string]$reviewedSuccessorContract.Manifest.task.task_path -cne
                [string]$contract.Manifest.task.task_path) {
            throw "A supersession must preserve the exact Scheduler task identity before durable staging."
        }
        Write-WeatherOneShotAtomicResolution `
            -Destination $successorPendingPath `
            -Bytes ([byte[]]$sourceSnapshot.bytes)
    }
    $successorSnapshot = Read-WeatherOneShotRegularFileSnapshot `
        -Path $successorPendingPath -MaximumBytes 64KB `
        -UnavailableCode "MANIFEST_UNAVAILABLE" `
        -UnsafeCode "MANIFEST_UNSAFE_PATH" `
        -TooLargeCode "MANIFEST_UNSAFE_PATH" `
        -Label "Durably staged successor one-shot manifest"
    if ([string]$successorSnapshot.sha256 -cne
        $ExpectedSuccessorManifestSha256) {
        throw "Durably staged successor does not match its reviewed SHA-256."
    }
    $successorContract = Read-WeatherOneShotReadinessManifest `
        -Path $successorPendingPath `
        -ExpectedSha256 $ExpectedSuccessorManifestSha256 `
        -AllowUnanchoredSource
    if ([string]$successorContract.Manifest.task.task_name -cne $taskName -or
        [string]$successorContract.Manifest.task.task_path -cne
            [string]$contract.Manifest.task.task_path) {
        throw "A supersession must preserve the exact Scheduler task identity."
    }
    $successorPath = Join-Path $registryRoot `
        "$taskName.$ExpectedSuccessorManifestSha256.manifest.json"
    $successorSha256 = $ExpectedSuccessorManifestSha256
    $successorBytes = [byte[]]$successorSnapshot.bytes
    if (Test-Path -LiteralPath $successorPath -PathType Leaf) {
        # Detect wrong or already-resolved destination state before freezing
        # the predecessor's immutable supersession receipt.
        Publish-WeatherOneShotExactSuccessor `
            -Destination $successorPath `
            -Bytes $successorBytes `
            -ExpectedSha256 $successorSha256 -TaskName $taskName
    }
}
elseif (-not [string]::IsNullOrWhiteSpace($SuccessorSourceManifestPath) -or
    -not [string]::IsNullOrWhiteSpace($ExpectedSuccessorManifestSha256)) {
    throw "TERMINAL resolution may not name a successor."
}

$mutexIdentityBytes = [Text.UTF8Encoding]::new($false).GetBytes(
    ([IO.Path]::GetFullPath($RepoRoot).ToLowerInvariant() + "|" +
        $taskName.ToLowerInvariant())
)
$mutexIdentity = Get-WeatherOneShotBytesSha256 -Bytes $mutexIdentityBytes
$taskMutex = [Threading.Mutex]::new(
    $false,
    "Local\WeatherOneShotRegistry_$mutexIdentity"
)
$taskMutexHeld = $false
try {
    try {
        $taskMutexHeld = $taskMutex.WaitOne([TimeSpan]::FromSeconds(30))
    }
    catch [Threading.AbandonedMutexException] {
        $taskMutexHeld = $true
    }
    if (-not $taskMutexHeld) {
        throw "Timed out waiting for the exact one-shot task registry mutex."
    }

    if (Test-Path -LiteralPath $resolutionPath -PathType Leaf -ErrorAction Stop) {
        $storedResolution = Read-WeatherOneShotExactStoredResolution `
            -Path $resolutionPath `
            -Status $Status `
            -Reason $Reason `
            -ReviewReference $ReviewReference `
            -TaskName $taskName `
            -TaskPath ([string]$contract.Manifest.task.task_path) `
            -ManifestPath $ManifestPath `
            -ManifestSha256 $ExpectedManifestSha256 `
            -SuccessorManifestPath $successorPath `
            -SuccessorManifestSha256 $successorSha256
        $storedResolutionSnapshot = Read-WeatherOneShotRegularFileSnapshot `
            -Path $resolutionPath -MaximumBytes 1MB `
            -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -Label "Existing one-shot resolution"
        Write-WeatherOneShotResolutionIndexEvent `
            -ManifestPath $ManifestPath `
            -ManifestSha256 $ExpectedManifestSha256 `
            -ResolutionPath $resolutionPath `
            -ResolutionSha256 ([string]$storedResolutionSnapshot.sha256) `
            -TaskName $taskName | Out-Null
        $retryTerminalState = Get-WeatherOneShotResolutionTerminalState `
            -TaskName $taskName `
            -TaskPath ([string]$contract.Manifest.task.task_path)
        if (-not [bool]$retryTerminalState.terminal) {
            throw "Resolved one-shot task is executable; recovery publication is refused."
        }
        $retryTerminalState = Get-WeatherOneShotResolutionTerminalState `
            -TaskName $taskName `
            -TaskPath ([string]$contract.Manifest.task.task_path)
        if (-not [bool]$retryTerminalState.terminal) {
            throw "Resolved one-shot task became executable; recovery publication is refused."
        }
        if ($Status -eq "SUPERSEDED") {
            Publish-WeatherOneShotExactSuccessor `
                -Destination $successorPath `
                -Bytes $successorBytes `
                -ExpectedSha256 $successorSha256 -TaskName $taskName
            if (Test-Path -LiteralPath $successorPendingPath -PathType Leaf) {
                [IO.File]::Delete($successorPendingPath)
            }
        }
        $storedResolution | ConvertTo-Json -Depth 8 -Compress
        return
    }

    # A successful complete inventory query is the only proof that an exact
    # task is absent. The second sample closes the proof-to-publication gap.
    $terminalState = Get-WeatherOneShotResolutionTerminalState `
        -TaskName $taskName -TaskPath ([string]$contract.Manifest.task.task_path)
    if (-not [bool]$terminalState.terminal) {
        throw "Exact one-shot task is still executable; immutable resolution is refused."
    }
    $terminalState = Get-WeatherOneShotResolutionTerminalState `
        -TaskName $taskName -TaskPath ([string]$contract.Manifest.task.task_path)
    if (-not [bool]$terminalState.terminal) {
        throw "Exact one-shot task became executable; immutable resolution is refused."
    }

    $observedAt = [DateTimeOffset]::Now
    $resolvedAt = [DateTimeOffset]::Now
    $payload = [ordered]@{
        schema_version = "weather_one_shot_readiness_resolution_v1"
        status = $Status
        resolved_at_local = $resolvedAt.ToString("o")
        review_reference = $ReviewReference
        reason = $Reason
        task_name = $taskName
        task_path = [string]$contract.Manifest.task.task_path
        manifest_path = $ManifestPath
        manifest_sha256 = $ExpectedManifestSha256
        successor_manifest_path = $successorPath
        successor_manifest_sha256 = $successorSha256
        task_terminal_proof = [ordered]@{
            observed_at_local = $observedAt.ToString("o")
            exists = [bool]$terminalState.exists
            state = [string]$terminalState.state
            next_run_time = $terminalState.next_run_time
            last_run_time = $terminalState.last_run_time
            last_task_result = $terminalState.last_task_result
            cannot_execute = $true
        }
        authority = "REVIEWED_CREATE_ONLY_ONE_SHOT_RESOLUTION_NO_SCHEDULER_MUTATION"
    }
    $json = $payload | ConvertTo-Json -Depth 8
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
    if ($bytes.Length -le 0 -or $bytes.Length -gt 1MB) {
        throw "One-shot resolution exceeds its bounded evidence contract."
    }
    Write-WeatherOneShotAtomicResolution `
        -Destination $resolutionPath -Bytes $bytes

    $stored = Read-WeatherOneShotRegularFileSnapshot `
        -Path $resolutionPath `
        -MaximumBytes 1MB `
        -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
        -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -Label "One-shot resolution"
    if ([string]$stored.sha256 -cne
        (Get-WeatherOneShotBytesSha256 -Bytes $bytes)) {
        throw "Create-only one-shot resolution failed exact post-write verification."
    }
    Write-WeatherOneShotResolutionIndexEvent `
        -ManifestPath $ManifestPath `
        -ManifestSha256 $ExpectedManifestSha256 `
        -ResolutionPath $resolutionPath `
        -ResolutionSha256 ([string]$stored.sha256) `
        -TaskName $taskName | Out-Null

    # Resolution is published first. Runtime validation now refuses the old
    # manifest; successor publication is idempotent so a crash can resume.
    if ($Status -eq "SUPERSEDED") {
        Publish-WeatherOneShotExactSuccessor `
            -Destination $successorPath `
            -Bytes $successorBytes `
            -ExpectedSha256 $successorSha256 -TaskName $taskName
        if (Test-Path -LiteralPath $successorPendingPath -PathType Leaf) {
            [IO.File]::Delete($successorPendingPath)
        }
    }
    $payload | ConvertTo-Json -Depth 8 -Compress
}
finally {
    if ($taskMutexHeld) { [void]$taskMutex.ReleaseMutex() }
    $taskMutex.Dispose()
}
}
finally {
    $registryLock.Dispose()
}
