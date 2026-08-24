[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$DebrisPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedDebrisSha256,
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [Parameter(Mandatory = $true)]
    [ValidateSet("REVIEWED_REMOVE_INVALID_ONE_SHOT_SUCCESSOR_PENDING")]
    [string]$Confirmation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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
    throw "RepoRoot must identify the repository containing this reconciler."
}
. $validator -LibraryOnly

$registryRoot = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "data\one_shot_readiness\active")
)
$DebrisPath = [IO.Path]::GetFullPath($DebrisPath)
if ((Split-Path -Parent $DebrisPath) -ine $registryRoot) {
    throw "DebrisPath must be one direct canonical active-registry child."
}
$leaf = [IO.Path]::GetFileName($DebrisPath)
if ($leaf -cnotmatch
    '^(?<task>Weather[A-Za-z0-9._-]{1,119})\.(?<sha>[0-9a-f]{64})\.successor\.pending\.json$' -or
    [string]$Matches.sha -cne $ExpectedDebrisSha256) {
    throw "Debris filename does not bind the reviewed pending hash."
}
$taskName = [string]$Matches.task
$receiptPath = Join-Path $script:OneShotRegistryIndexRoot `
    "debris.successor_pending.$taskName.$ExpectedDebrisSha256.json"

$registryLock = [IO.FileStream]::new(
    (Join-Path $RepoRoot "one_shot_registry.lock"),
    [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None
)
try {
    Assert-WeatherOneShotRegistryIndexDirectory
    $debrisExists = Test-Path -LiteralPath $DebrisPath -PathType Leaf
    $receiptExists = Test-Path -LiteralPath $receiptPath -PathType Leaf
    if (-not $debrisExists -and -not $receiptExists) {
        throw "Reviewed successor-pending debris and its reconciliation receipt are both absent."
    }

    try { $schedulerSnapshot = @(Get-ScheduledTask -ErrorAction Stop) }
    catch {
        throw "Task Scheduler inventory failed; invalid pending debris cannot be reconciled."
    }
    $matchingTasks = @($schedulerSnapshot | Where-Object {
            [string]$_.TaskName -ieq $taskName
        })
    if (@($matchingTasks | Where-Object {
                [string]$_.State -cne "Disabled"
            }).Count -ne 0) {
        throw "Pending-debris reconciliation requires every same-name task to be absent or Disabled."
    }

    if ($debrisExists) {
        $snapshot = Read-WeatherOneShotRegularFileSnapshot `
            -Path $DebrisPath -MaximumBytes 64KB `
            -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -Label "Reviewed successor-pending debris"
        if ([string]$snapshot.sha256 -cne $ExpectedDebrisSha256) {
            throw "Successor-pending debris does not match its reviewed hash."
        }
        $pendingContract = $null
        try {
            $fullPendingContract = Read-WeatherOneShotReadinessManifest `
                -Path $DebrisPath -ExpectedSha256 $ExpectedDebrisSha256 `
                -AllowUnanchoredSource
            $pendingContract = [pscustomobject]@{
                TaskName = [string]$fullPendingContract.Manifest.task.task_name
                TaskPath = [string]$fullPendingContract.Manifest.task.task_path
            }
        }
        catch {
            $blockerCode = [string]$_.Exception.Data[
                "weather_one_shot_readiness_blocker_code"
            ]
            if ($blockerCode -in @(
                    "TASK_EXECUTABLE_UNAVAILABLE",
                    "TASK_WORKING_DIRECTORY_UNAVAILABLE"
                )) {
                # Availability can recover without changing immutable bytes.
                # Preserve a structurally exact same-identity transaction.
                $structuralPendingContract = `
                    Read-WeatherOneShotReadinessManifest `
                        -Path $DebrisPath `
                        -ExpectedSha256 $ExpectedDebrisSha256 `
                        -AllowUnanchoredSource `
                        -SkipCurrentAvailabilityChecks
                $pendingContract = [pscustomobject]@{
                    TaskName = [string]$structuralPendingContract.Manifest.task.task_name
                    TaskPath = [string]$structuralPendingContract.Manifest.task.task_path
                }
            }
            else {
                # Immutable contract failure proves these reviewed bytes can
                # never be resumed. The receipt preserves them before removal.
                $pendingContract = $null
            }
        }
        $unresolvedPredecessors = @(
            Get-ChildItem -LiteralPath $registryRoot -File -Force `
                -Filter "$taskName.*.manifest.json" -ErrorAction Stop |
                Where-Object {
                    $candidateResolution = $_.FullName.Substring(
                        0, $_.FullName.Length - ".manifest.json".Length
                    ) + ".resolution.json"
                    -not (Test-Path -LiteralPath $candidateResolution `
                        -PathType Leaf)
                }
        )
        $isValidTransaction = $false
        if ($null -ne $pendingContract -and
            $unresolvedPredecessors.Count -eq 1) {
            $predecessorLeaf = [string]$unresolvedPredecessors[0].Name
            if ($predecessorLeaf -cmatch
                '^(?<task>Weather[A-Za-z0-9._-]{1,119})\.(?<sha>[0-9a-f]{64})\.manifest\.json$') {
                try {
                    $predecessorContract = `
                        Read-WeatherOneShotReadinessManifest `
                            -Path ([string]$unresolvedPredecessors[0].FullName) `
                            -ExpectedSha256 ([string]$Matches.sha) `
                            -AllowUnanchoredSource `
                            -SkipCurrentAvailabilityChecks
                    $isValidTransaction = (
                        [string]$pendingContract.TaskName -ceq
                            $taskName -and
                        [string]$pendingContract.TaskPath -ceq
                            [string]$predecessorContract.Manifest.task.task_path
                    )
                }
                catch {
                    $isValidTransaction = $false
                }
            }
        }
        if ($isValidTransaction) {
            throw "Pending successor is a valid resumable resolver transaction; reconciliation is refused."
        }
        $debrisBytes = [byte[]]$snapshot.bytes
    }

    if ($receiptExists) {
        $receiptSnapshot = Read-WeatherOneShotRegularFileSnapshot `
            -Path $receiptPath -MaximumBytes 128KB `
            -UnavailableCode "REGISTRY_EVIDENCE_UNAVAILABLE" `
            -UnsafeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -TooLargeCode "REGISTRY_EVIDENCE_UNSAFE" `
            -Label "Pending-debris reconciliation receipt"
        try {
            $receipt = [Text.UTF8Encoding]::new($false, $true).GetString(
                [byte[]]$receiptSnapshot.bytes
            ) | ConvertFrom-Json -ErrorAction Stop
            $storedBytes = [Convert]::FromBase64String(
                [string]$receipt.debris_bytes_base64
            )
        }
        catch { throw "Pending-debris reconciliation receipt is malformed." }
        if (-not (Test-WeatherOneShotExactPropertySet -Value $receipt `
                -ExpectedNames @(
                    "schema_version", "status", "reconciled_at_local",
                    "reason", "review_reference", "confirmation", "task_name",
                    "debris_path", "debris_sha256", "debris_bytes_base64",
                    "authority"
                )) -or
            [string]$receipt.schema_version -cne
                "weather_one_shot_registry_debris_reconciliation_v1" -or
            [string]$receipt.status -cne "REMOVED" -or
            [string]$receipt.reason -cne $Reason -or
            [string]$receipt.review_reference -cne $ReviewReference -or
            [string]$receipt.confirmation -cne $Confirmation -or
            [string]$receipt.task_name -cne $taskName -or
            [IO.Path]::GetFullPath([string]$receipt.debris_path) -ine
                $DebrisPath -or
            [string]$receipt.debris_sha256 -cne $ExpectedDebrisSha256 -or
            (Get-WeatherOneShotBytesSha256 -Bytes $storedBytes) -cne
                $ExpectedDebrisSha256 -or
            [string]$receipt.authority -cne
                "REVIEWED_ONE_SHOT_DEBRIS_RECONCILIATION_NO_SCHEDULER_MUTATION") {
            throw "Existing pending-debris receipt does not match this reviewed request."
        }
        try {
            $reconciledAt = [DateTimeOffset]::Parse(
                [string]$receipt.reconciled_at_local
            )
        }
        catch { throw "Pending-debris receipt timestamp is invalid." }
        if ($reconciledAt -gt [DateTimeOffset]::Now.AddMinutes(5)) {
            throw "Pending-debris receipt is future-dated."
        }
    }
    else {
        $receipt = [ordered]@{
            schema_version = "weather_one_shot_registry_debris_reconciliation_v1"
            status = "REMOVED"
            reconciled_at_local = [DateTimeOffset]::Now.ToString("o")
            reason = $Reason
            review_reference = $ReviewReference
            confirmation = $Confirmation
            task_name = $taskName
            debris_path = $DebrisPath
            debris_sha256 = $ExpectedDebrisSha256
            debris_bytes_base64 = [Convert]::ToBase64String($debrisBytes)
            authority = "REVIEWED_ONE_SHOT_DEBRIS_RECONCILIATION_NO_SCHEDULER_MUTATION"
        }
        $receiptBytes = [Text.UTF8Encoding]::new($false).GetBytes(
            ($receipt | ConvertTo-Json -Depth 5)
        )
        Write-WeatherOneShotIndexCreateOnlyFile `
            -Destination $receiptPath -Bytes $receiptBytes
    }

    try { $schedulerSnapshot = @(Get-ScheduledTask -ErrorAction Stop) }
    catch { throw "Task Scheduler revalidation failed before debris removal." }
    if (@($schedulerSnapshot | Where-Object {
                [string]$_.TaskName -ieq $taskName -and
                [string]$_.State -cne "Disabled"
            }).Count -ne 0) {
        throw "Same-name task became executable before debris removal."
    }
    if ($debrisExists) { [IO.File]::Delete($DebrisPath) }
    if (Test-Path -LiteralPath $DebrisPath) {
        throw "Reviewed invalid pending debris remains after reconciliation."
    }
    $receipt | ConvertTo-Json -Depth 5 -Compress
}
finally {
    $registryLock.Dispose()
}
