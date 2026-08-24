[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [Parameter(Mandatory = $true)]
    [ValidateSet("REVIEWED_RECONCILE_EMPTY_ONE_SHOT_REGISTRY_ACTIVATION")]
    [string]$Confirmation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-WeatherOneShotActivationRecoveryFile {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][byte[]]$Bytes
    )

    Remove-WeatherOneShotExactAtomicDebris `
        -Destination $Destination -ExpectedBytes $Bytes
    $temporary = Join-Path (Split-Path -Parent $Destination) (
        ".{0}.{1}.tmp" -f
            [IO.Path]::GetFileName($Destination),
            [guid]::NewGuid().ToString("N")
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

function Read-WeatherOneShotActivationRecoveryJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $snapshot = Read-WeatherOneShotRegularFileSnapshot `
        -Path $Path -MaximumBytes 64KB `
        -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
        -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -Label $Label
    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        return $utf8.GetString([byte[]]$snapshot.bytes) |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "$Label is not valid bounded UTF-8 JSON."
    }
}

if ([string]::IsNullOrWhiteSpace($Reason) -or $Reason.Length -gt 4096 -or
    [string]::IsNullOrWhiteSpace($ReviewReference) -or
    $ReviewReference.Length -gt 4096) {
    throw "Reason and ReviewReference must be non-empty and no longer than 4096 characters."
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$validator = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "scripts\ops\one_shot_readiness.ps1")
)
if ($validator -ine [IO.Path]::GetFullPath(
        (Join-Path $PSScriptRoot "one_shot_readiness.ps1")
    )) {
    throw "RepoRoot must identify the repository containing this recovery tool."
}
. $validator -LibraryOnly

$registryRoot = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "data\one_shot_readiness\active")
)
$markerPath = Join-Path $RepoRoot "one_shot_registry_activation.json"
$intentPath = Join-Path $RepoRoot "one_shot_registry_activation_intent.json"
$recoveryPath = Join-Path $RepoRoot `
    "one_shot_registry_activation_recovery.json"
$indexRoot = Join-Path $RepoRoot "one_shot_registry_index"
$lockPath = Join-Path $RepoRoot "one_shot_registry.lock"
$lockPreexisted = $true
$registryLock = [IO.FileStream]::new(
    $lockPath,
    [IO.FileMode]::Open,
    [IO.FileAccess]::ReadWrite,
    [IO.FileShare]::None
)
try {
    $lockItem = Get-Item -LiteralPath $lockPath -ErrorAction Stop
    if ($lockItem.PSIsContainer -or
        ($lockItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "One-shot registry lock must be a regular non-reparse file."
    }
    Assert-WeatherOneShotNonReparseDirectoryTree `
        -Path $RepoRoot -StopPath $RepoRoot
    $registryPathExists = Test-Path -LiteralPath $registryRoot -ErrorAction Stop
    $registryExists = Test-Path `
        -LiteralPath $registryRoot -PathType Container -ErrorAction Stop
    $markerExists = Test-Path `
        -LiteralPath $markerPath -PathType Leaf -ErrorAction Stop
    $markerPathExists = Test-Path -LiteralPath $markerPath -ErrorAction Stop
    $intentExists = Test-Path `
        -LiteralPath $intentPath -PathType Leaf -ErrorAction Stop
    $intentPathExists = Test-Path -LiteralPath $intentPath -ErrorAction Stop
    $recoveryExists = Test-Path `
        -LiteralPath $recoveryPath -PathType Leaf -ErrorAction Stop
    $recoveryPathExists = Test-Path -LiteralPath $recoveryPath -ErrorAction Stop
    $indexExists = Test-Path `
        -LiteralPath $indexRoot -PathType Container -ErrorAction Stop
    $indexPathExists = Test-Path -LiteralPath $indexRoot -ErrorAction Stop
    if (($registryPathExists -and -not $registryExists) -or
        ($markerPathExists -and -not $markerExists) -or
        ($intentPathExists -and -not $intentExists) -or
        ($recoveryPathExists -and -not $recoveryExists) -or
        ($indexPathExists -and -not $indexExists)) {
        throw "Activation recovery evidence contains a wrong-type filesystem object."
    }
    if (-not $lockPreexisted -and -not $registryExists -and
        -not $markerExists -and -not $intentExists -and -not $recoveryExists) {
        throw "No durable interrupted-activation evidence exists to review or recover."
    }
    if ($registryExists) {
        Assert-WeatherOneShotNonReparseDirectoryTree `
            -Path $registryRoot -StopPath $RepoRoot
        $registryEntries = @(
            Get-ChildItem -LiteralPath $registryRoot -Force -ErrorAction Stop
        )
        if ($registryEntries.Count -ne 0) {
            throw "Activation recovery is limited to an exactly empty active registry."
        }
    }
    if ($indexExists) {
        Assert-WeatherOneShotRegistryIndexDirectory
        $indexEntries = @(
            Get-ChildItem -LiteralPath $indexRoot -Force -ErrorAction Stop
        )
        if ($indexEntries.Count -ne 0) {
            throw "Activation recovery is limited to an exactly empty one-shot registry index."
        }
    }
    if ($recoveryExists -and
        (-not $registryExists -or -not $intentExists -or -not $indexExists)) {
        throw "Existing recovery evidence proves later continuity loss; first-activation recovery cannot recreate it."
    }

    # First-activation recovery is safe only when a complete Scheduler
    # inventory proves no task could already refer to the missing registry
    # history. Enabled and Disabled orphan actions are equally disqualifying.
    try {
        $schedulerSnapshot = @(Get-ScheduledTask -ErrorAction Stop)
    }
    catch {
        throw "Task Scheduler inventory failed; an empty registry cannot be classified as first-activation debris."
    }
    foreach ($scheduledTask in $schedulerSnapshot) {
        foreach ($scheduledAction in @($scheduledTask.Actions)) {
            $scheduledExecute = [string]$scheduledAction.Execute
            $scheduledArguments = [string]$scheduledAction.Arguments
            $namesOneShotEntry = (
                $scheduledArguments -match
                    '(?i)(?:one_shot_guarded_launcher|one_shot_readiness)\.ps1(?:"|\s|$)' -or
                $scheduledExecute -match
                    '(?i)(?:one_shot_guarded_launcher|one_shot_readiness)\.ps1(?:"|\s|$)'
            )
            if ($scheduledArguments -match
                    '(?i)(?:^|\s)-(?:ReadinessManifestPath|ExpectedReadinessManifestSha256)(?::|\s|$)' -or
                $namesOneShotEntry) {
                throw "A Scheduler task still carries one-shot readiness binding flags; activation history loss cannot be recovered as a first activation."
            }
        }
    }

    $receipt = $null
    if ($markerExists -and -not $recoveryExists) {
        throw "Registry activation is already complete; recovery will not manufacture retrospective authority."
    }
    if ($recoveryExists) {
        $receipt = Read-WeatherOneShotActivationRecoveryJson `
            -Path $recoveryPath -Label "One-shot activation recovery receipt"
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
                $registryRoot -or
            [string]$receipt.reason -cne $Reason -or
            [string]$receipt.review_reference -cne $ReviewReference -or
            [string]$receipt.confirmation -cne $Confirmation -or
            [string]$receipt.authority -cne
                "REVIEWED_EMPTY_REGISTRY_ACTIVATION_RECOVERY_NO_SCHEDULER_AUTHORITY") {
            throw "Existing activation recovery receipt does not match this reviewed request."
        }
        $intentObject = [ordered]@{
            schema_version = [string]$receipt.activation_intent.schema_version
            status = [string]$receipt.activation_intent.status
            registry_root = [string]$receipt.activation_intent.registry_root
            created_at_local = [string]$receipt.activation_intent.created_at_local
            authority = [string]$receipt.activation_intent.authority
        }
        $markerObject = [ordered]@{
            schema_version = [string]$receipt.activation_marker.schema_version
            status = [string]$receipt.activation_marker.status
            registry_root = [string]$receipt.activation_marker.registry_root
            activated_at_local = [string]$receipt.activation_marker.activated_at_local
            authority = [string]$receipt.activation_marker.authority
        }
    }
    else {
        if ($intentExists) {
            Assert-WeatherOneShotRegistryActivationIntent `
                -Path $intentPath -RegistryRoot $registryRoot
            $storedIntentObject = Read-WeatherOneShotActivationRecoveryJson `
                -Path $intentPath -Label "One-shot registry activation intent"
            $intentObject = [ordered]@{
                schema_version = [string]$storedIntentObject.schema_version
                status = [string]$storedIntentObject.status
                registry_root = [string]$storedIntentObject.registry_root
                created_at_local = [string]$storedIntentObject.created_at_local
                authority = [string]$storedIntentObject.authority
            }
        }
        else {
            $intentObject = [ordered]@{
                schema_version = "weather_one_shot_registry_activation_intent_v1"
                status = "ACTIVATION_INTENDED"
                registry_root = $registryRoot
                created_at_local = [DateTimeOffset]::Now.ToString("o")
                authority = "DURABLE_ONE_SHOT_REGISTRY_ACTIVATION_INTENT"
            }
        }
        $markerObject = [ordered]@{
            schema_version = "weather_one_shot_registry_activation_v1"
            status = "ACTIVE"
            registry_root = $registryRoot
            activated_at_local = [DateTimeOffset]::Now.ToString("o")
            authority = "REVIEWED_EMPTY_REGISTRY_ACTIVATION_RECOVERY"
        }
        $receiptObject = [ordered]@{
            schema_version = "weather_one_shot_registry_activation_recovery_v1"
            status = "PASS"
            registry_root = $registryRoot
            reason = $Reason
            review_reference = $ReviewReference
            confirmation = $Confirmation
            activation_intent = $intentObject
            activation_marker = $markerObject
            authority = "REVIEWED_EMPTY_REGISTRY_ACTIVATION_RECOVERY_NO_SCHEDULER_AUTHORITY"
        }
        $receipt = $receiptObject
    }

    if (-not $registryExists) {
        New-Item -ItemType Directory -Path $registryRoot -Force `
            -ErrorAction Stop | Out-Null
        Assert-WeatherOneShotNonReparseDirectoryTree `
            -Path $registryRoot -StopPath $RepoRoot
        $registryExists = $true
    }
    if (-not $indexExists) {
        Assert-WeatherOneShotRegistryIndexDirectory -Create
        $indexExists = $true
    }
    $intentBytes = [Text.UTF8Encoding]::new($false).GetBytes(
        ($intentObject | ConvertTo-Json -Depth 3)
    )
    if ($intentExists) {
        $storedIntent = Read-WeatherOneShotRegularFileSnapshot `
            -Path $intentPath -MaximumBytes 64KB `
            -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -Label "One-shot registry activation intent"
        if ([string]$storedIntent.sha256 -cne
            (Get-WeatherOneShotBytesSha256 -Bytes $intentBytes)) {
            throw "Existing activation intent does not match its reviewed recovery receipt."
        }
    }
    else {
        Write-WeatherOneShotActivationRecoveryFile `
            -Destination $intentPath -Bytes $intentBytes
        $intentExists = $true
    }
    Assert-WeatherOneShotRegistryActivationIntent `
        -Path $intentPath -RegistryRoot $registryRoot

    if (-not $recoveryExists) {
        $receiptBytes = [Text.UTF8Encoding]::new($false).GetBytes(
            ($receipt | ConvertTo-Json -Depth 5)
        )
        Write-WeatherOneShotActivationRecoveryFile `
            -Destination $recoveryPath -Bytes $receiptBytes
        $recoveryExists = $true
    }

    $markerBytes = [Text.UTF8Encoding]::new($false).GetBytes(
        ($markerObject | ConvertTo-Json -Depth 3)
    )
    if ($markerExists) {
        Assert-WeatherOneShotRegistryActivationMarker `
            -Path $markerPath -RegistryRoot $registryRoot
        $storedMarker = Read-WeatherOneShotRegularFileSnapshot `
            -Path $markerPath -MaximumBytes 64KB `
            -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -Label "One-shot registry activation marker"
        if ([string]$storedMarker.sha256 -cne
            (Get-WeatherOneShotBytesSha256 -Bytes $markerBytes)) {
            throw "Existing activation marker does not match its reviewed recovery receipt."
        }
    }
    else {
        Write-WeatherOneShotActivationRecoveryFile `
            -Destination $markerPath -Bytes $markerBytes
        Assert-WeatherOneShotRegistryActivationMarker `
            -Path $markerPath -RegistryRoot $registryRoot
    }
    Assert-WeatherOneShotRegistryRecoveryReceipt `
        -Path $recoveryPath `
        -IntentPath $intentPath `
        -MarkerPath $markerPath `
        -RegistryRoot $registryRoot

    [pscustomobject][ordered]@{
        schema_version = "weather_one_shot_registry_activation_recovery_result_v1"
        status = "PASS"
        registry_root = $registryRoot
        marker_path = $markerPath
        recovery_receipt_path = $recoveryPath
        authority = "REVIEWED_EMPTY_REGISTRY_ACTIVATION_RECOVERY_NO_SCHEDULER_AUTHORITY"
    } | ConvertTo-Json -Compress
}
finally {
    $registryLock.Dispose()
}
