[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$SourceManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedSourceSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-WeatherOneShotRegistryDirectoryTree {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$StopPath
    )

    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullStop = [IO.Path]::GetFullPath($StopPath)
    $cursor = Get-Item -LiteralPath $fullPath -ErrorAction Stop
    while ($null -ne $cursor) {
        $cursorPath = [IO.Path]::GetFullPath([string]$cursor.FullName)
        if ($cursor -isnot [IO.DirectoryInfo] -or
            (($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw "One-shot registry directories through the repository root must be non-reparse directories."
        }
        if ($cursorPath -ieq $fullStop) { return }
        if (-not $cursorPath.StartsWith(
                $fullStop + [IO.Path]::DirectorySeparatorChar,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw "One-shot registry path escaped the repository root."
        }
        $cursor = $cursor.Parent
    }
    throw "One-shot registry directory tree does not reach the repository root."
}

function Write-WeatherOneShotAtomicCreateOnlyFile {
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

function Read-WeatherOneShotRegistryJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $snapshot = Read-WeatherOneShotRegularFileSnapshot `
        -Path $Path `
        -MaximumBytes 1MB `
        -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
        -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -Label $Label
    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $text = $utf8.GetString([byte[]]$snapshot.bytes)
        if ($text.Length -gt 0 -and $text[0] -eq [char]0xfeff) {
            $text = $text.Substring(1)
        }
        return $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "$Label is not valid bounded UTF-8 JSON."
    }
}

function Assert-WeatherOneShotRegistryActivation {
    param(
        [Parameter(Mandatory = $true)][string]$MarkerPath,
        [Parameter(Mandatory = $true)][string]$RegistryRoot
    )

    $marker = Read-WeatherOneShotRegistryJson `
        -Path $MarkerPath -Label "One-shot registry activation marker"
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

function Assert-WeatherOneShotWriterRegistryActivationIntent {
    param(
        [Parameter(Mandatory = $true)][string]$IntentPath,
        [Parameter(Mandatory = $true)][string]$RegistryRoot
    )

    $intent = Read-WeatherOneShotRegistryJson `
        -Path $IntentPath -Label "One-shot registry activation intent"
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
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$') {
        throw "One-shot registry activation intent does not match its exact contract."
    }
    try {
        $createdAt = [DateTimeOffset]::Parse(
            [string]$intent.created_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch {
        throw "One-shot registry activation-intent timestamp is invalid."
    }
    if ($createdAt -gt [DateTimeOffset]::Now.AddMinutes(5)) {
        throw "One-shot registry activation intent is future-dated."
    }
}

function Assert-WeatherOneShotWriterRegistryRecoveryReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$RecoveryPath,
        [Parameter(Mandatory = $true)][string]$IntentPath,
        [Parameter(Mandatory = $true)][string]$MarkerPath,
        [Parameter(Mandatory = $true)][string]$RegistryRoot
    )

    $receipt = Read-WeatherOneShotRegistryJson `
        -Path $RecoveryPath -Label "One-shot registry activation recovery receipt"
    if (-not (Test-WeatherOneShotExactPropertySet `
            -Value $receipt `
            -ExpectedNames @(
                "schema_version", "status", "registry_root", "reason",
                "review_reference", "confirmation", "activation_intent",
                "activation_marker", "authority"
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
        throw "One-shot registry activation recovery receipt does not match its exact contract."
    }
    if (-not (Test-WeatherOneShotExactPropertySet `
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
            ))) {
        throw "One-shot registry activation recovery receipt embeds malformed activation evidence."
    }
    $storedIntent = Read-WeatherOneShotRegistryJson `
        -Path $IntentPath -Label "One-shot registry activation intent"
    $storedMarker = Read-WeatherOneShotRegistryJson `
        -Path $MarkerPath -Label "One-shot registry activation marker"
    foreach ($field in @(
            "schema_version", "status", "registry_root",
            "created_at_local", "authority"
        )) {
        if ([string]$receipt.activation_intent.$field -cne
            [string]$storedIntent.$field) {
            throw "One-shot recovery receipt does not bind the stored activation intent."
        }
    }
    foreach ($field in @(
            "schema_version", "status", "registry_root",
            "activated_at_local", "authority"
        )) {
        if ([string]$receipt.activation_marker.$field -cne
            [string]$storedMarker.$field) {
            throw "One-shot recovery receipt does not bind the stored activation marker."
        }
    }
}

function Get-WeatherOneShotExactTaskTerminalState {
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
        return [pscustomobject]@{ Terminal = $true }
    }
    try {
        $info = Get-ScheduledTaskInfo -InputObject $tasks[0] -ErrorAction Stop
    }
    catch {
        throw "Exact one-shot task runtime state could not be queried."
    }
    $state = [string]$tasks[0].State
    return [pscustomobject]@{
        # A spent Ready task may still be demand-startable after settings drift.
        # Only exact absence or Scheduler's Disabled state proves no execution.
        Terminal = ($state -ceq "Disabled")
    }
}

function Assert-WeatherOneShotPriorResolution {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ResolutionPath,
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$ManifestSha256,
        [Parameter(Mandatory = $true)][string]$RegistryRoot
    )

    $resolution = Read-WeatherOneShotRegistryJson `
        -Path $ResolutionPath -Label "Prior one-shot resolution"
    if (-not (Test-WeatherOneShotExactPropertySet `
            -Value $resolution `
            -ExpectedNames @(
                "schema_version", "status", "resolved_at_local",
                "review_reference", "reason", "task_name", "task_path",
                "manifest_path", "manifest_sha256", "successor_manifest_path",
                "successor_manifest_sha256", "task_terminal_proof", "authority"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $resolution.task_terminal_proof `
            -ExpectedNames @(
                "observed_at_local", "exists", "state", "next_run_time",
                "last_run_time", "last_task_result", "cannot_execute"
            )) -or
        [string]$resolution.schema_version -cne
            "weather_one_shot_readiness_resolution_v1" -or
        [string]$resolution.status -cnotin @("TERMINAL", "SUPERSEDED") -or
        [string]::IsNullOrWhiteSpace([string]$resolution.review_reference) -or
        [string]::IsNullOrWhiteSpace([string]$resolution.reason) -or
        [string]$resolution.task_name -cne $TaskName -or
        [IO.Path]::GetFullPath([string]$resolution.manifest_path) -ine
            [IO.Path]::GetFullPath($ManifestPath) -or
        [string]$resolution.manifest_sha256 -cne $ManifestSha256 -or
        $resolution.task_terminal_proof.exists -isnot [bool] -or
        $resolution.task_terminal_proof.cannot_execute -isnot [bool] -or
        -not [bool]$resolution.task_terminal_proof.cannot_execute -or
        [string]$resolution.authority -cne
            "REVIEWED_CREATE_ONLY_ONE_SHOT_RESOLUTION_NO_SCHEDULER_MUTATION") {
        throw "Prior one-shot resolution does not bind exact immutable terminal history."
    }

    try {
        $resolvedAt = [DateTimeOffset]::Parse(
            [string]$resolution.resolved_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
        $observedAt = [DateTimeOffset]::Parse(
            [string]$resolution.task_terminal_proof.observed_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch {
        throw "Prior one-shot resolution timestamps are invalid."
    }
    if ([string]$resolution.resolved_at_local -notmatch
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$' -or
        [string]$resolution.task_terminal_proof.observed_at_local -notmatch
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$' -or
        $observedAt -gt $resolvedAt -or
        ($resolvedAt - $observedAt) -gt [TimeSpan]::FromMinutes(5) -or
        ([bool]$resolution.task_terminal_proof.exists -and
            [string]$resolution.task_terminal_proof.state -cne "Disabled") -or
        (-not [bool]$resolution.task_terminal_proof.exists -and
            [string]$resolution.task_terminal_proof.state -cne "ABSENT") -or
        $resolvedAt -gt [DateTimeOffset]::Now.AddMinutes(5)) {
        throw "Prior one-shot resolution terminal proof is incoherent or stale."
    }

    $priorContract = Read-WeatherOneShotReadinessManifest `
        -Path $ManifestPath -ExpectedSha256 $ManifestSha256 `
        -AllowResolvedManifest
    $taskPath = [string]$priorContract.Manifest.task.task_path
    if ([string]$resolution.task_path -cne $taskPath) {
        throw "Prior one-shot resolution task path disagrees with the manifest."
    }
    if ([string]$resolution.status -ceq "SUPERSEDED") {
        $successorPath = [IO.Path]::GetFullPath(
            [string]$resolution.successor_manifest_path
        )
        $successorSha256 = [string]$resolution.successor_manifest_sha256
        if ((Split-Path -Parent $successorPath) -ine
                [IO.Path]::GetFullPath($RegistryRoot) -or
            $successorPath -ieq [IO.Path]::GetFullPath($ManifestPath) -or
            $successorSha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "Prior one-shot supersession does not bind a distinct active manifest."
        }
        Read-WeatherOneShotReadinessManifest `
            -Path $successorPath -ExpectedSha256 $successorSha256 `
            -AllowResolvedManifest | Out-Null
    }
    elseif (-not [string]::IsNullOrWhiteSpace(
            [string]$resolution.successor_manifest_path
        ) -or -not [string]::IsNullOrWhiteSpace(
            [string]$resolution.successor_manifest_sha256
        )) {
        throw "Prior terminal resolution may not name a successor."
    }

    $live = Get-WeatherOneShotExactTaskTerminalState `
        -TaskName $TaskName -TaskPath $taskPath
    if (-not [bool]$live.Terminal) {
        throw "Prior resolved task can still execute; a replacement anchor is refused."
    }
}

$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$SourceManifestPath = [IO.Path]::GetFullPath($SourceManifestPath)
$validator = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "scripts\ops\one_shot_readiness.ps1")
)
if ($validator -ine [IO.Path]::GetFullPath(
        (Join-Path $PSScriptRoot "one_shot_readiness.ps1")
    )) {
    throw "RepoRoot must identify the repository containing this writer."
}
. $validator -LibraryOnly

$sourceSnapshot = Read-WeatherOneShotRegularFileSnapshot `
    -Path $SourceManifestPath `
    -MaximumBytes $script:OneShotReadinessMaximumManifestBytes `
    -UnavailableCode "MANIFEST_UNAVAILABLE" `
    -UnsafeCode "MANIFEST_UNSAFE_PATH" `
    -TooLargeCode "MANIFEST_UNSAFE_PATH" `
    -Label "Source one-shot readiness manifest"
if ([string]$sourceSnapshot.sha256 -cne $ExpectedSourceSha256) {
    throw "Source one-shot manifest does not match its reviewed SHA-256."
}
$contract = Read-WeatherOneShotReadinessManifest `
    -Path $SourceManifestPath `
    -ExpectedSha256 $ExpectedSourceSha256 `
    -AllowUnanchoredSource
$taskName = [string]$contract.Manifest.task.task_name
if ($taskName -notmatch '^Weather[A-Za-z0-9._-]{1,119}$') {
    throw "One-shot manifest task identity is unsafe for the active registry."
}

$registryLockPath = Join-Path $RepoRoot "one_shot_registry.lock"
$registryLock = $null
$preexistingRegistryContinuity = (
    (Test-Path -LiteralPath (Join-Path $RepoRoot `
        "one_shot_registry_activation_intent.json") -ErrorAction Stop) -or
    (Test-Path -LiteralPath (Join-Path $RepoRoot `
        "one_shot_registry_activation.json") -ErrorAction Stop) -or
    (Test-Path -LiteralPath (Join-Path $RepoRoot `
        "one_shot_registry_activation_recovery.json") -ErrorAction Stop) -or
    (Test-Path -LiteralPath (Join-Path $RepoRoot `
        "data\one_shot_readiness\active") -ErrorAction Stop) -or
    (Test-Path -LiteralPath (Join-Path $RepoRoot `
        "one_shot_registry_index") -ErrorAction Stop)
)
$registryLockPreexisted = $preexistingRegistryContinuity
if ($preexistingRegistryContinuity) {
    $registryLock = [IO.FileStream]::new(
        $registryLockPath,
        [IO.FileMode]::Open,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None
    )
}
else {
    $registryLock = [IO.FileStream]::new(
        $registryLockPath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None
    )
}
try {
$registryLockItem = Get-Item -LiteralPath $registryLockPath -ErrorAction Stop
if ($registryLockItem.PSIsContainer -or
    ($registryLockItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "One-shot registry lock must be a regular non-reparse file."
}

$registryParent = Join-Path $RepoRoot "data\one_shot_readiness"
$registryRoot = Join-Path $registryParent "active"
$activationMarker = Join-Path $RepoRoot "one_shot_registry_activation.json"
$activationIntent = Join-Path $RepoRoot `
    "one_shot_registry_activation_intent.json"
$activationRecovery = Join-Path $RepoRoot `
    "one_shot_registry_activation_recovery.json"
$registryIndex = Join-Path $RepoRoot "one_shot_registry_index"
if ([IO.Path]::GetFullPath($script:OneShotReadinessRegistryRoot) -ine
    [IO.Path]::GetFullPath($registryRoot)) {
    throw "Writer and validator disagree on the canonical active registry path."
}
Assert-WeatherOneShotRegistryDirectoryTree -Path $RepoRoot -StopPath $RepoRoot
$dataRoot = Join-Path $RepoRoot "data"
if (Test-Path -LiteralPath $dataRoot) {
    Assert-WeatherOneShotRegistryDirectoryTree -Path $dataRoot -StopPath $RepoRoot
}
if (Test-Path -LiteralPath $registryParent) {
    Assert-WeatherOneShotRegistryDirectoryTree `
        -Path $registryParent -StopPath $RepoRoot
}
$registryExists = Test-Path `
    -LiteralPath $registryRoot -PathType Container -ErrorAction Stop
$registryPathExists = Test-Path -LiteralPath $registryRoot -ErrorAction Stop
$markerExists = Test-Path `
    -LiteralPath $activationMarker -PathType Leaf -ErrorAction Stop
$markerPathExists = Test-Path -LiteralPath $activationMarker -ErrorAction Stop
$intentExists = Test-Path `
    -LiteralPath $activationIntent -PathType Leaf -ErrorAction Stop
$intentPathExists = Test-Path -LiteralPath $activationIntent -ErrorAction Stop
$recoveryExists = Test-Path `
    -LiteralPath $activationRecovery -PathType Leaf -ErrorAction Stop
$recoveryPathExists = Test-Path -LiteralPath $activationRecovery -ErrorAction Stop
$indexExists = Test-Path `
    -LiteralPath $registryIndex -PathType Container -ErrorAction Stop
$indexPathExists = Test-Path -LiteralPath $registryIndex -ErrorAction Stop
if ($registryPathExists -and -not $registryExists) {
    throw "Canonical one-shot active registry path exists but is not a directory."
}
if ($markerPathExists -and -not $markerExists) {
    throw "Canonical one-shot registry activation path exists but is not a file."
}
if ($intentPathExists -and -not $intentExists) {
    throw "Canonical one-shot registry activation-intent path exists but is not a file."
}
if ($recoveryPathExists -and -not $recoveryExists) {
    throw "Canonical one-shot activation-recovery path exists but is not a file."
}
if ($indexPathExists -and -not $indexExists) {
    throw "Canonical one-shot registry index exists but is not a directory."
}
if (-not $registryExists -and -not $markerExists -and -not $intentExists -and
    -not $recoveryExists -and $registryLockPreexisted) {
    throw "A durable one-shot registry lock predates all activation evidence; reviewed recovery is required."
}
if (($registryExists -or $markerExists -or $intentExists -or $recoveryExists -or
        $indexExists) -and
    (-not $registryExists -or -not $markerExists -or -not $intentExists -or
        -not $indexExists)) {
    throw "One-shot registry activation continuity is incomplete; ordinary publication will not repair or erase the incident."
}

if (-not $registryExists) {
    $intent = [ordered]@{
        schema_version = "weather_one_shot_registry_activation_intent_v1"
        status = "ACTIVATION_INTENDED"
        registry_root = [IO.Path]::GetFullPath($registryRoot)
        created_at_local = [DateTimeOffset]::Now.ToString("o")
        authority = "DURABLE_ONE_SHOT_REGISTRY_ACTIVATION_INTENT"
    }
    $intentBytes = [Text.UTF8Encoding]::new($false).GetBytes(
        ($intent | ConvertTo-Json -Depth 3)
    )
    Write-WeatherOneShotAtomicCreateOnlyFile `
        -Destination $activationIntent -Bytes $intentBytes
    $createdRegistryRoot = $false
    if (-not (Test-Path -LiteralPath $registryParent)) {
        New-Item -ItemType Directory -Path $registryParent -Force -ErrorAction Stop |
            Out-Null
    }
    New-Item -ItemType Directory -Path $registryRoot -ErrorAction Stop | Out-Null
    $createdRegistryRoot = $true
    Assert-WeatherOneShotRegistryDirectoryTree `
        -Path $registryRoot -StopPath $RepoRoot
    Assert-WeatherOneShotRegistryIndexDirectory -Create
    $activation = [ordered]@{
        schema_version = "weather_one_shot_registry_activation_v1"
        status = "ACTIVE"
        registry_root = [IO.Path]::GetFullPath($registryRoot)
        activated_at_local = [DateTimeOffset]::Now.ToString("o")
        authority = "CREATE_ONLY_ONE_SHOT_ACTIVE_REGISTRY"
    }
    $activationBytes = [Text.UTF8Encoding]::new($false).GetBytes(
        ($activation | ConvertTo-Json -Depth 3)
    )
    try {
        Write-WeatherOneShotAtomicCreateOnlyFile `
            -Destination $activationMarker -Bytes $activationBytes
    }
    catch {
        if ($createdRegistryRoot -and
            (Test-Path -LiteralPath $registryRoot -PathType Container)) {
            $activationDebris = @(
                Get-ChildItem -LiteralPath $registryRoot -Force -ErrorAction Stop
            )
            if ($activationDebris.Count -eq 0) {
                [IO.Directory]::Delete($registryRoot, $false)
            }
        }
        throw "Initial one-shot registry activation did not complete atomically; reviewed recovery is required: $($_.Exception.Message)"
    }
}
else {
    Assert-WeatherOneShotRegistryDirectoryTree `
        -Path $registryRoot -StopPath $RepoRoot
}
Assert-WeatherOneShotRegistryIndexDirectory
Assert-WeatherOneShotWriterRegistryActivationIntent `
    -IntentPath $activationIntent -RegistryRoot $registryRoot
Assert-WeatherOneShotRegistryActivation `
    -MarkerPath $activationMarker -RegistryRoot $registryRoot
$storedActivationMarker = Read-WeatherOneShotRegistryJson `
    -Path $activationMarker -Label "One-shot registry activation marker"
if ($recoveryExists) {
    if ([string]$storedActivationMarker.authority -cne
        "REVIEWED_EMPTY_REGISTRY_ACTIVATION_RECOVERY") {
        throw "A recovery receipt exists for a normally activated one-shot registry."
    }
    Assert-WeatherOneShotWriterRegistryRecoveryReceipt `
        -RecoveryPath $activationRecovery `
        -IntentPath $activationIntent `
        -MarkerPath $activationMarker `
        -RegistryRoot $registryRoot
}
elseif ([string]$storedActivationMarker.authority -cne
    "CREATE_ONLY_ONE_SHOT_ACTIVE_REGISTRY") {
    throw "Recovered one-shot registry activation lacks its immutable review receipt."
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

    $destination = Join-Path $registryRoot `
        "$taskName.$ExpectedSourceSha256.manifest.json"
    $destinationExists = Test-Path `
        -LiteralPath $destination -PathType Leaf -ErrorAction Stop
    foreach ($prior in @(Get-ChildItem -LiteralPath $registryRoot `
            -Filter "$taskName.*.manifest.json" -File -Force -ErrorAction Stop)) {
        if ($prior.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Prior active one-shot registry entry is unsafe."
        }
        $priorLeaf = [IO.Path]::GetFileName([string]$prior.FullName)
        if ($priorLeaf -cnotmatch
            '^(?<priorTask>Weather[A-Za-z0-9._-]{1,119})\.(?<priorSha>[0-9a-f]{64})\.manifest\.json$') {
            throw "Prior active manifest anchor filename is invalid."
        }
        $priorTaskName = [string]$Matches.priorTask
        $priorSha256 = [string]$Matches.priorSha
        if ([IO.Path]::GetFullPath([string]$prior.FullName) -ieq
            [IO.Path]::GetFullPath($destination)) {
            continue
        }
        $resolution = $prior.FullName.Substring(
            0,
            $prior.FullName.Length - ".manifest.json".Length
        ) + ".resolution.json"
        if (-not (Test-Path -LiteralPath $resolution -PathType Leaf)) {
            throw "Task $taskName already has an unresolved active manifest anchor."
        }
        Assert-WeatherOneShotPriorResolution `
            -ManifestPath ([string]$prior.FullName) `
            -ResolutionPath $resolution `
            -TaskName $priorTaskName `
            -ManifestSha256 $priorSha256 `
            -RegistryRoot $registryRoot
    }

    $publicationStatus = "FROZEN"
    if ($destinationExists) {
        $existing = Read-WeatherOneShotRegularFileSnapshot `
            -Path $destination `
            -MaximumBytes $script:OneShotReadinessMaximumManifestBytes `
            -UnavailableCode "MANIFEST_UNAVAILABLE" `
            -UnsafeCode "MANIFEST_UNSAFE_PATH" `
            -TooLargeCode "MANIFEST_UNSAFE_PATH" `
            -Label "Existing active one-shot manifest"
        if ([string]$existing.sha256 -cne $ExpectedSourceSha256) {
            throw "Existing exact-name anchor does not contain the reviewed bytes."
        }
        $publicationStatus = "ALREADY_FROZEN"
    }
    else {
        Write-WeatherOneShotAtomicCreateOnlyFile `
            -Destination $destination -Bytes ([byte[]]$sourceSnapshot.bytes)
    }
    Write-WeatherOneShotManifestIndexEvent `
        -ManifestPath $destination -ManifestSha256 $ExpectedSourceSha256 `
        -TaskName $taskName | Out-Null
    try {
        Read-WeatherOneShotReadinessManifest `
            -Path $destination `
            -ExpectedSha256 $ExpectedSourceSha256 | Out-Null
    }
    catch {
        throw "Create-only active one-shot manifest anchor failed post-write verification: $($_.Exception.Message)"
    }

    [pscustomobject][ordered]@{
        schema_version = "weather_one_shot_active_manifest_anchor_v1"
        status = $publicationStatus
        task_name = $taskName
        manifest_path = $destination
        manifest_sha256 = $ExpectedSourceSha256
        authority = "CREATE_ONLY_BEFORE_TASK_REGISTRATION_NO_SCHEDULER_AUTHORITY"
    } | ConvertTo-Json -Compress
}
finally {
    if ($taskMutexHeld) { [void]$taskMutex.ReleaseMutex() }
    $taskMutex.Dispose()
}
}
finally {
    $registryLock.Dispose()
}
