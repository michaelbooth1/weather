[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedResolutionSha256,
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [Parameter(Mandatory = $true)]
    [ValidateSet("REVIEWED_COMPACT_RESOLVED_ONE_SHOT_HISTORY")]
    [string]$Confirmation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-WeatherOneShotCompactionTerminalProof {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$TaskPath
    )
    try { $tasks = @(Get-ScheduledTask -ErrorAction Stop) }
    catch {
        throw "Task Scheduler inventory failed; compaction cannot prove terminal state."
    }
    $matches = @($tasks | Where-Object {
            [string]$_.TaskName -ieq $TaskName -and
            [string]$_.TaskPath -ieq $TaskPath
        })
    if ($matches.Count -gt 1) {
        throw "Exact one-shot task identity resolved more than one Scheduler task."
    }
    if ($matches.Count -eq 0) {
        return [ordered]@{
            observed_at_local = [DateTimeOffset]::Now.ToString("o")
            exists = $false
            state = "ABSENT"
            cannot_execute = $true
        }
    }
    throw "One-shot compaction requires the exact Scheduler task to be absent; Disabled tasks retain their active anchor."
}

function Assert-WeatherOneShotCompactionResolution {
    param(
        [Parameter(Mandatory = $true)][object]$Resolution,
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$TaskPath,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ManifestSha256
    )
    if (-not (Test-WeatherOneShotExactPropertySet -Value $Resolution `
            -ExpectedNames @(
                "schema_version", "status", "resolved_at_local",
                "review_reference", "reason", "task_name", "task_path",
                "manifest_path", "manifest_sha256", "successor_manifest_path",
                "successor_manifest_sha256", "task_terminal_proof", "authority"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $Resolution.task_terminal_proof `
            -ExpectedNames @(
                "observed_at_local", "exists", "state", "next_run_time",
                "last_run_time", "last_task_result", "cannot_execute"
            )) -or
        [string]$Resolution.schema_version -cne
            "weather_one_shot_readiness_resolution_v1" -or
        [string]$Resolution.status -cnotin @("TERMINAL", "SUPERSEDED") -or
        [string]::IsNullOrWhiteSpace([string]$Resolution.reason) -or
        [string]::IsNullOrWhiteSpace([string]$Resolution.review_reference) -or
        [string]$Resolution.task_name -cne $TaskName -or
        [string]$Resolution.task_path -cne $TaskPath -or
        [IO.Path]::GetFullPath([string]$Resolution.manifest_path) -ine
            [IO.Path]::GetFullPath($ManifestPath) -or
        [string]$Resolution.manifest_sha256 -cne $ManifestSha256 -or
        $Resolution.task_terminal_proof.exists -isnot [bool] -or
        $Resolution.task_terminal_proof.cannot_execute -isnot [bool] -or
        -not [bool]$Resolution.task_terminal_proof.cannot_execute -or
        [string]$Resolution.authority -cne
            "REVIEWED_CREATE_ONLY_ONE_SHOT_RESOLUTION_NO_SCHEDULER_MUTATION") {
        throw "Compaction resolution does not match the exact immutable contract."
    }
    try {
        $resolvedAt = [DateTimeOffset]::Parse(
            [string]$Resolution.resolved_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
        $observedAt = [DateTimeOffset]::Parse(
            [string]$Resolution.task_terminal_proof.observed_at_local,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch { throw "Compaction resolution timestamps are invalid." }
    if ([string]$Resolution.resolved_at_local -notmatch
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$' -or
        [string]$Resolution.task_terminal_proof.observed_at_local -notmatch
            '(?:Z|[+-][0-9]{2}:[0-9]{2})$' -or
        $observedAt -gt $resolvedAt -or
        ($resolvedAt - $observedAt) -gt [TimeSpan]::FromMinutes(5) -or
        $resolvedAt -gt [DateTimeOffset]::Now.AddMinutes(5) -or
        ([bool]$Resolution.task_terminal_proof.exists -and
            [string]$Resolution.task_terminal_proof.state -cne "Disabled") -or
        (-not [bool]$Resolution.task_terminal_proof.exists -and
            [string]$Resolution.task_terminal_proof.state -cne "ABSENT")) {
        throw "Compaction resolution terminal proof is incoherent."
    }
    if ([string]$Resolution.status -ceq "SUPERSEDED") {
        $successorSha256 = [string]$Resolution.successor_manifest_sha256
        $successorPath = [IO.Path]::GetFullPath(
            [string]$Resolution.successor_manifest_path
        )
        if ($successorSha256 -cnotmatch '^[0-9a-f]{64}$' -or
            $successorSha256 -ceq $ManifestSha256 -or
            (Split-Path -Parent $successorPath) -ine
                [IO.Path]::GetFullPath((Split-Path -Parent $ManifestPath)) -or
            [IO.Path]::GetFileName($successorPath) -cne
                "$TaskName.$successorSha256.manifest.json") {
            throw "Compaction supersession resolution does not bind a canonical successor."
        }
    }
    elseif (-not [string]::IsNullOrWhiteSpace(
            [string]$Resolution.successor_manifest_path
        ) -or -not [string]::IsNullOrWhiteSpace(
            [string]$Resolution.successor_manifest_sha256
        )) {
        throw "Compaction terminal resolution may not name a successor."
    }
}

function Assert-WeatherOneShotCompactedSuccessorHistory {
    param(
        [Parameter(Mandatory = $true)][string]$SuccessorPath,
        [Parameter(Mandatory = $true)][string]$SuccessorSha256,
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$TaskPath
    )
    Assert-WeatherOneShotManifestIndexEvent `
        -ManifestPath $SuccessorPath -ManifestSha256 $SuccessorSha256 `
        -TaskName $TaskName | Out-Null
    $resolutionEventPath = Get-WeatherOneShotResolutionIndexEventPath `
        -TaskName $TaskName -ManifestSha256 $SuccessorSha256
    $resolutionEvent = Read-WeatherOneShotIndexJson `
        -Path $resolutionEventPath -Label "Compacted successor resolution index"
    $expectedResolutionPath = $SuccessorPath.Substring(
        0, $SuccessorPath.Length - ".manifest.json".Length
    ) + ".resolution.json"
    if (-not (Test-WeatherOneShotExactPropertySet -Value $resolutionEvent `
            -ExpectedNames @(
                "schema_version", "kind", "recorded_at_local", "task_name",
                "manifest_path", "manifest_sha256", "resolution_path",
                "resolution_sha256", "authority"
            )) -or
        [string]$resolutionEvent.schema_version -cne
            "weather_one_shot_registry_index_v1" -or
        [string]$resolutionEvent.kind -cne "RESOLUTION" -or
        [string]$resolutionEvent.task_name -cne $TaskName -or
        [IO.Path]::GetFullPath([string]$resolutionEvent.manifest_path) -ine
            [IO.Path]::GetFullPath($SuccessorPath) -or
        [string]$resolutionEvent.manifest_sha256 -cne $SuccessorSha256 -or
        [IO.Path]::GetFullPath([string]$resolutionEvent.resolution_path) -ine
            [IO.Path]::GetFullPath($expectedResolutionPath) -or
        [string]$resolutionEvent.resolution_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        [string]$resolutionEvent.authority -cne
            "CREATE_ONLY_ONE_SHOT_REGISTRY_INDEX") {
        throw "Compacted successor resolution index is invalid."
    }
    $receiptPath = Join-Path $script:OneShotRegistryIndexRoot `
        "compaction.$TaskName.$SuccessorSha256.json"
    $snapshot = Read-WeatherOneShotRegularFileSnapshot `
        -Path $receiptPath -MaximumBytes 2MB `
        -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
        -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
        -Label "Compacted successor receipt"
    try {
        $receipt = [Text.UTF8Encoding]::new($false, $true).GetString(
            [byte[]]$snapshot.bytes
        ) | ConvertFrom-Json -ErrorAction Stop
        $manifestBytes = [Convert]::FromBase64String(
            [string]$receipt.manifest_bytes_base64
        )
        $embeddedManifest = [Text.UTF8Encoding]::new(
            $false, $true
        ).GetString($manifestBytes) | ConvertFrom-Json -ErrorAction Stop
        $resolutionBytes = [Convert]::FromBase64String(
            [string]$receipt.resolution_bytes_base64
        )
        $embeddedResolution = [Text.UTF8Encoding]::new(
            $false, $true
        ).GetString($resolutionBytes) | ConvertFrom-Json -ErrorAction Stop
    }
    catch { throw "Compacted successor receipt is malformed." }
    if (-not (Test-WeatherOneShotExactPropertySet -Value $receipt `
            -ExpectedNames @(
                "schema_version", "status", "compacted_at_local", "reason",
                "review_reference", "confirmation", "task_name", "task_path",
                "manifest_path", "manifest_sha256", "manifest_bytes_base64",
                "resolution_path", "resolution_sha256",
                "resolution_bytes_base64", "task_terminal_proof", "authority"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet `
            -Value $receipt.task_terminal_proof `
            -ExpectedNames @(
                "observed_at_local", "exists", "state", "cannot_execute"
            )) -or
        [string]$receipt.schema_version -cne
            "weather_one_shot_registry_compaction_v1" -or
        [string]$receipt.status -cne "COMPACTED" -or
        [string]::IsNullOrWhiteSpace([string]$receipt.reason) -or
        [string]::IsNullOrWhiteSpace([string]$receipt.review_reference) -or
        [string]$receipt.confirmation -cne
            "REVIEWED_COMPACT_RESOLVED_ONE_SHOT_HISTORY" -or
        [string]$receipt.task_name -cne $TaskName -or
        [string]$receipt.task_path -cne $TaskPath -or
        [IO.Path]::GetFullPath([string]$receipt.manifest_path) -ine
            [IO.Path]::GetFullPath($SuccessorPath) -or
        [string]$receipt.manifest_sha256 -cne $SuccessorSha256 -or
        [string]$receipt.resolution_sha256 -cne
            [string]$resolutionEvent.resolution_sha256 -or
        [IO.Path]::GetFullPath([string]$receipt.resolution_path) -ine
            [IO.Path]::GetFullPath($expectedResolutionPath) -or
        (Get-WeatherOneShotBytesSha256 -Bytes $manifestBytes) -cne
            $SuccessorSha256 -or
        (Get-WeatherOneShotBytesSha256 -Bytes $resolutionBytes) -cne
            [string]$receipt.resolution_sha256 -or
        -not (Test-WeatherOneShotExactPropertySet -Value $embeddedManifest `
            -ExpectedNames @(
                "schema_version", "task", "principal", "settings",
                "admission", "boot_identity", "dependencies"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet -Value $embeddedManifest.task `
            -ExpectedNames @(
                "task_name", "task_path", "executable", "arguments_template",
                "working_directory", "action_file", "payload_file",
                "payload_arguments", "trigger_at_local"
            )) -or
        [string]$embeddedManifest.schema_version -cne
            "weather_one_shot_readiness_manifest_v0.4" -or
        [string]$embeddedManifest.task.task_name -cne $TaskName -or
        [string]$embeddedManifest.task.task_path -cne $TaskPath -or
        $receipt.task_terminal_proof.exists -isnot [bool] -or
        [bool]$receipt.task_terminal_proof.exists -or
        $receipt.task_terminal_proof.cannot_execute -isnot [bool] -or
        -not [bool]$receipt.task_terminal_proof.cannot_execute -or
        [string]$receipt.task_terminal_proof.state -cne "ABSENT" -or
        [string]$receipt.authority -cne
            "REVIEWED_ONE_SHOT_HISTORY_COMPACTION_NO_SCHEDULER_MUTATION") {
        throw "Compacted successor receipt does not preserve exact immutable continuity."
    }
    Assert-WeatherOneShotCompactionResolution `
        -Resolution $embeddedResolution -TaskName $TaskName -TaskPath $TaskPath `
        -ManifestPath $SuccessorPath -ManifestSha256 $SuccessorSha256
    try {
        $compactedAt = [DateTimeOffset]::Parse(
            [string]$receipt.compacted_at_local
        )
        $observedAt = [DateTimeOffset]::Parse(
            [string]$receipt.task_terminal_proof.observed_at_local
        )
    }
    catch { throw "Compacted successor receipt timestamps are invalid." }
    if ($observedAt -gt $compactedAt -or
        ($compactedAt - $observedAt) -gt [TimeSpan]::FromMinutes(5) -or
        $compactedAt -gt [DateTimeOffset]::Now.AddMinutes(5)) {
        throw "Compacted successor receipt proof ordering is invalid."
    }
}

if ([string]::IsNullOrWhiteSpace($Reason) -or $Reason.Length -gt 4096 -or
    [string]::IsNullOrWhiteSpace($ReviewReference) -or
    $ReviewReference.Length -gt 4096) {
    throw "Reason and ReviewReference must be non-empty and bounded."
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$validator = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "scripts\ops\one_shot_readiness.ps1")
)
if ($validator -ine [IO.Path]::GetFullPath(
        (Join-Path $PSScriptRoot "one_shot_readiness.ps1")
    )) {
    throw "RepoRoot must identify the repository containing this compactor."
}
$requestedManifestPath = $ManifestPath
$requestedManifestSha256 = $ExpectedManifestSha256
. $validator -LibraryOnly
$ManifestPath = $requestedManifestPath
$ExpectedManifestSha256 = $requestedManifestSha256

$registryRoot = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "data\one_shot_readiness\active")
)
$ManifestPath = [IO.Path]::GetFullPath($ManifestPath)
if ((Split-Path -Parent $ManifestPath) -ine $registryRoot) {
    throw "ManifestPath must be one direct canonical active-registry anchor."
}
$manifestLeaf = [IO.Path]::GetFileName($ManifestPath)
if ($manifestLeaf -cnotmatch
    '^(?<task>Weather[A-Za-z0-9._-]{1,119})\.(?<sha>[0-9a-f]{64})\.manifest\.json$' -or
    [string]$Matches.sha -cne $ExpectedManifestSha256) {
    throw "Manifest filename does not bind the reviewed task and hash."
}
$taskName = [string]$Matches.task
$resolutionPath = $ManifestPath.Substring(
    0, $ManifestPath.Length - ".manifest.json".Length
) + ".resolution.json"
$receiptPath = Join-Path $script:OneShotRegistryIndexRoot `
    "compaction.$taskName.$ExpectedManifestSha256.json"

$registryLock = [IO.FileStream]::new(
    (Join-Path $RepoRoot "one_shot_registry.lock"),
    [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None
)
try {
    Assert-WeatherOneShotRegistryIndexDirectory

    $receiptExists = Test-Path -LiteralPath $receiptPath -PathType Leaf
    $manifestExists = Test-Path -LiteralPath $ManifestPath -PathType Leaf
    $resolutionExists = Test-Path -LiteralPath $resolutionPath -PathType Leaf
    $manifestBytes = $null
    $resolutionBytes = $null
    $taskPath = $null
    $resolvedHistory = $null
    $newReceiptBytes = $null

    if ($receiptExists) {
        $receiptSnapshot = Read-WeatherOneShotRegularFileSnapshot `
            -Path $receiptPath -MaximumBytes 2MB `
            -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -Label "One-shot compaction receipt"
        try {
            $receipt = [Text.UTF8Encoding]::new($false, $true).GetString(
                [byte[]]$receiptSnapshot.bytes
            ) | ConvertFrom-Json -ErrorAction Stop
            $manifestBytes = [Convert]::FromBase64String(
                [string]$receipt.manifest_bytes_base64
            )
            $resolutionBytes = [Convert]::FromBase64String(
                [string]$receipt.resolution_bytes_base64
            )
        }
        catch { throw "Existing one-shot compaction receipt is malformed." }
        if (-not (Test-WeatherOneShotExactPropertySet -Value $receipt `
                -ExpectedNames @(
                    "schema_version", "status", "compacted_at_local",
                    "reason", "review_reference", "confirmation",
                    "task_name", "task_path", "manifest_path",
                    "manifest_sha256", "manifest_bytes_base64",
                    "resolution_path", "resolution_sha256",
                    "resolution_bytes_base64", "task_terminal_proof",
                    "authority"
                )) -or
            [string]$receipt.schema_version -cne
                "weather_one_shot_registry_compaction_v1" -or
            [string]$receipt.status -cne "COMPACTED" -or
            [string]$receipt.reason -cne $Reason -or
            [string]$receipt.review_reference -cne $ReviewReference -or
            [string]$receipt.confirmation -cne $Confirmation -or
            [string]$receipt.task_name -cne $taskName -or
            [IO.Path]::GetFullPath([string]$receipt.manifest_path) -ine
                $ManifestPath -or
            [string]$receipt.manifest_sha256 -cne $ExpectedManifestSha256 -or
            [IO.Path]::GetFullPath([string]$receipt.resolution_path) -ine
                $resolutionPath -or
            [string]$receipt.resolution_sha256 -cne
                $ExpectedResolutionSha256 -or
            (Get-WeatherOneShotBytesSha256 -Bytes $manifestBytes) -cne
                $ExpectedManifestSha256 -or
            (Get-WeatherOneShotBytesSha256 -Bytes $resolutionBytes) -cne
                $ExpectedResolutionSha256 -or
            [string]$receipt.authority -cne
                "REVIEWED_ONE_SHOT_HISTORY_COMPACTION_NO_SCHEDULER_MUTATION") {
            throw "Existing compaction receipt does not match this exact reviewed request."
        }
        if (-not (Test-WeatherOneShotExactPropertySet `
                -Value $receipt.task_terminal_proof `
                -ExpectedNames @(
                    "observed_at_local", "exists", "state", "cannot_execute"
                )) -or
            $receipt.task_terminal_proof.exists -isnot [bool] -or
            $receipt.task_terminal_proof.cannot_execute -isnot [bool] -or
            -not [bool]$receipt.task_terminal_proof.cannot_execute -or
            [bool]$receipt.task_terminal_proof.exists -or
            [string]$receipt.task_terminal_proof.state -cne "ABSENT") {
            throw "Existing compaction receipt terminal proof is incoherent."
        }
        try {
            $compactedAt = [DateTimeOffset]::Parse(
                [string]$receipt.compacted_at_local
            )
            $receiptObservedAt = [DateTimeOffset]::Parse(
                [string]$receipt.task_terminal_proof.observed_at_local
            )
        }
        catch { throw "Existing compaction receipt timestamps are invalid." }
        if ($receiptObservedAt -gt $compactedAt -or
            ($compactedAt - $receiptObservedAt) -gt
                [TimeSpan]::FromMinutes(5) -or
            $compactedAt -gt [DateTimeOffset]::Now.AddMinutes(5)) {
            throw "Existing compaction receipt proof ordering is invalid."
        }
        $taskPath = [string]$receipt.task_path
        try {
            $resolvedHistory = [Text.UTF8Encoding]::new(
                $false, $true
            ).GetString($resolutionBytes) | ConvertFrom-Json -ErrorAction Stop
        }
        catch { throw "Compaction receipt embeds malformed resolution history." }
    }
    else {
        if (-not $manifestExists -or -not $resolutionExists) {
            throw "Compaction requires both immutable source files until its receipt exists."
        }
        $manifestSnapshot = Read-WeatherOneShotRegularFileSnapshot `
            -Path $ManifestPath -MaximumBytes 64KB `
            -UnavailableCode "MANIFEST_UNAVAILABLE" `
            -UnsafeCode "MANIFEST_UNSAFE_PATH" `
            -TooLargeCode "MANIFEST_UNSAFE_PATH" `
            -Label "One-shot manifest selected for compaction"
        $resolutionSnapshot = Read-WeatherOneShotRegularFileSnapshot `
            -Path $resolutionPath -MaximumBytes 1MB `
            -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -Label "One-shot resolution selected for compaction"
        if ([string]$manifestSnapshot.sha256 -cne $ExpectedManifestSha256 -or
            [string]$resolutionSnapshot.sha256 -cne
                $ExpectedResolutionSha256) {
            throw "Compaction source bytes do not match both reviewed hashes."
        }
        $contract = Read-WeatherOneShotReadinessManifest `
            -Path $ManifestPath -ExpectedSha256 $ExpectedManifestSha256 `
            -AllowResolvedManifest
        $taskPath = [string]$contract.Manifest.task.task_path
        try {
            $resolution = [Text.UTF8Encoding]::new($false, $true).GetString(
                [byte[]]$resolutionSnapshot.bytes
            ) | ConvertFrom-Json -ErrorAction Stop
        }
        catch { throw "Resolution selected for compaction is malformed." }
        $resolvedHistory = $resolution
        Write-WeatherOneShotResolutionIndexEvent `
            -ManifestPath $ManifestPath `
            -ManifestSha256 $ExpectedManifestSha256 `
            -ResolutionPath $resolutionPath `
            -ResolutionSha256 $ExpectedResolutionSha256 `
            -TaskName $taskName | Out-Null

        $proof = Get-WeatherOneShotCompactionTerminalProof `
            -TaskName $taskName -TaskPath $taskPath
        $proof = Get-WeatherOneShotCompactionTerminalProof `
            -TaskName $taskName -TaskPath $taskPath
        $manifestBytes = [byte[]]$manifestSnapshot.bytes
        $resolutionBytes = [byte[]]$resolutionSnapshot.bytes
        $receipt = [ordered]@{
            schema_version = "weather_one_shot_registry_compaction_v1"
            status = "COMPACTED"
            compacted_at_local = [DateTimeOffset]::Now.ToString("o")
            reason = $Reason
            review_reference = $ReviewReference
            confirmation = $Confirmation
            task_name = $taskName
            task_path = $taskPath
            manifest_path = $ManifestPath
            manifest_sha256 = $ExpectedManifestSha256
            manifest_bytes_base64 = [Convert]::ToBase64String($manifestBytes)
            resolution_path = $resolutionPath
            resolution_sha256 = $ExpectedResolutionSha256
            resolution_bytes_base64 = [Convert]::ToBase64String($resolutionBytes)
            task_terminal_proof = $proof
            authority = "REVIEWED_ONE_SHOT_HISTORY_COMPACTION_NO_SCHEDULER_MUTATION"
        }
        $receiptBytes = [Text.UTF8Encoding]::new($false).GetBytes(
            ($receipt | ConvertTo-Json -Depth 8)
        )
        if ($receiptBytes.Length -gt 2MB) {
            throw "One-shot compaction receipt exceeds its bounded evidence contract."
        }
        $newReceiptBytes = $receiptBytes
    }

    Assert-WeatherOneShotCompactionResolution `
        -Resolution $resolvedHistory -TaskName $taskName -TaskPath $taskPath `
        -ManifestPath $ManifestPath -ManifestSha256 $ExpectedManifestSha256
    try {
        $embeddedManifest = [Text.UTF8Encoding]::new(
            $false, $true
        ).GetString($manifestBytes) | ConvertFrom-Json -ErrorAction Stop
    }
    catch { throw "Compaction manifest history is malformed." }
    if (-not (Test-WeatherOneShotExactPropertySet -Value $embeddedManifest `
            -ExpectedNames @(
                "schema_version", "task", "principal", "settings",
                "admission", "boot_identity", "dependencies"
            )) -or
        -not (Test-WeatherOneShotExactPropertySet -Value $embeddedManifest.task `
            -ExpectedNames @(
                "task_name", "task_path", "executable", "arguments_template",
                "working_directory", "action_file", "payload_file",
                "payload_arguments", "trigger_at_local"
            )) -or
        [string]$embeddedManifest.schema_version -cne
            "weather_one_shot_readiness_manifest_v0.4" -or
        [string]$embeddedManifest.task.task_name -cne $taskName -or
        [string]$embeddedManifest.task.task_path -cne $taskPath) {
        throw "Compaction manifest history does not bind exact task identity."
    }
    Assert-WeatherOneShotManifestIndexEvent `
        -ManifestPath $ManifestPath -ManifestSha256 $ExpectedManifestSha256 `
        -TaskName $taskName | Out-Null
    $resolutionIndexPath = Get-WeatherOneShotResolutionIndexEventPath `
        -TaskName $taskName -ManifestSha256 $ExpectedManifestSha256
    $resolutionIndex = Read-WeatherOneShotIndexJson `
        -Path $resolutionIndexPath -Label "Compaction source resolution index"
    if (-not (Test-WeatherOneShotExactPropertySet -Value $resolutionIndex `
            -ExpectedNames @(
                "schema_version", "kind", "recorded_at_local", "task_name",
                "manifest_path", "manifest_sha256", "resolution_path",
                "resolution_sha256", "authority"
            )) -or
        [string]$resolutionIndex.schema_version -cne
            "weather_one_shot_registry_index_v1" -or
        [string]$resolutionIndex.kind -cne "RESOLUTION" -or
        [string]$resolutionIndex.task_name -cne $taskName -or
        [IO.Path]::GetFullPath([string]$resolutionIndex.manifest_path) -ine
            $ManifestPath -or
        [string]$resolutionIndex.manifest_sha256 -cne
            $ExpectedManifestSha256 -or
        [IO.Path]::GetFullPath([string]$resolutionIndex.resolution_path) -ine
            $resolutionPath -or
        [string]$resolutionIndex.resolution_sha256 -cne
            $ExpectedResolutionSha256 -or
        [string]$resolutionIndex.authority -cne
            "CREATE_ONLY_ONE_SHOT_REGISTRY_INDEX") {
        throw "Compaction resolution index contradicts reviewed source history."
    }
    $pendingFiles = @(
        Get-ChildItem -LiteralPath $registryRoot -File -Force `
            -Filter "$taskName.*.successor.pending.json" -ErrorAction Stop
    )
    if ($pendingFiles.Count -ne 0) {
        throw "One-shot compaction refuses while a same-task successor transaction is pending."
    }
    if ([string]$resolvedHistory.status -ceq "SUPERSEDED") {
        $successorPath = [IO.Path]::GetFullPath(
            [string]$resolvedHistory.successor_manifest_path
        )
        $successorSha256 = [string]$resolvedHistory.successor_manifest_sha256
        if ((Split-Path -Parent $successorPath) -ine $registryRoot -or
            $successorPath -ieq $ManifestPath -or
            $successorSha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw "Supersession history does not bind a distinct canonical successor."
        }
        if (Test-Path -LiteralPath $successorPath -PathType Leaf) {
            $successorContract = Read-WeatherOneShotReadinessManifest `
                -Path $successorPath -ExpectedSha256 $successorSha256 `
                -AllowResolvedManifest
            if ([string]$successorContract.Manifest.task.task_name -cne
                    $taskName -or
                [string]$successorContract.Manifest.task.task_path -cne
                    $taskPath) {
                throw "Supersession successor does not preserve exact task identity."
            }
        }
        else {
            Assert-WeatherOneShotCompactedSuccessorHistory `
                -SuccessorPath $successorPath `
                -SuccessorSha256 $successorSha256 `
                -TaskName $taskName -TaskPath $taskPath
        }
    }
    elseif ([string]$resolvedHistory.status -ceq "TERMINAL") {
        if (-not [string]::IsNullOrWhiteSpace(
                [string]$resolvedHistory.successor_manifest_path
            ) -or -not [string]::IsNullOrWhiteSpace(
                [string]$resolvedHistory.successor_manifest_sha256
            )) {
            throw "Terminal resolution may not name a successor."
        }
    }
    else {
        throw "Compaction requires TERMINAL or complete SUPERSEDED history."
    }
    if ($null -ne $newReceiptBytes) {
        Write-WeatherOneShotIndexCreateOnlyFile `
            -Destination $receiptPath -Bytes $newReceiptBytes
    }

    # Reprove terminal state immediately before each idempotent destructive
    # step. The receipt is durable first, so any power loss is resumable.
    [void](Get-WeatherOneShotCompactionTerminalProof `
        -TaskName $taskName -TaskPath $taskPath)
    if ($resolutionExists) {
        $liveResolution = Read-WeatherOneShotRegularFileSnapshot `
            -Path $resolutionPath -MaximumBytes 1MB `
            -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -Label "Live resolution before compaction delete"
        if ([string]$liveResolution.sha256 -cne $ExpectedResolutionSha256) {
            throw "Live resolution changed before compaction deletion."
        }
        [IO.File]::Delete($resolutionPath)
    }
    [void](Get-WeatherOneShotCompactionTerminalProof `
        -TaskName $taskName -TaskPath $taskPath)
    if ($manifestExists) {
        $liveManifest = Read-WeatherOneShotRegularFileSnapshot `
            -Path $ManifestPath -MaximumBytes 64KB `
            -UnavailableCode "MANIFEST_UNAVAILABLE" `
            -UnsafeCode "MANIFEST_UNSAFE_PATH" `
            -TooLargeCode "MANIFEST_UNSAFE_PATH" `
            -Label "Live manifest before compaction delete"
        if ([string]$liveManifest.sha256 -cne $ExpectedManifestSha256) {
            throw "Live manifest changed before compaction deletion."
        }
        [IO.File]::Delete($ManifestPath)
    }
    if ((Test-Path -LiteralPath $resolutionPath) -or
        (Test-Path -LiteralPath $ManifestPath)) {
        throw "Compacted active-registry files remain after deletion."
    }

    [pscustomobject][ordered]@{
        schema_version = "weather_one_shot_registry_compaction_result_v1"
        status = "PASS"
        task_name = $taskName
        manifest_sha256 = $ExpectedManifestSha256
        resolution_sha256 = $ExpectedResolutionSha256
        compaction_receipt_path = $receiptPath
        authority = "REVIEWED_ONE_SHOT_HISTORY_COMPACTION_NO_SCHEDULER_MUTATION"
    } | ConvertTo-Json -Compress
}
finally {
    $registryLock.Dispose()
}
