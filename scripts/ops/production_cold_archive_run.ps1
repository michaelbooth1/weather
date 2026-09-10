# Attended, bounded staging, transfer, or separately evidence-gated exact original reclaim.
# Source may be a clean reviewed worktree; production capture source is untouched.
param(
    [Parameter(Mandatory = $true)][string]$ProductionRepoRoot,
    [Parameter(Mandatory = $true)][string]$RequestPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RequestSha256,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    [ValidateSet('stage', 'transfer', 'upload', 'download', 'reclaim')][string]$Operation = 'stage'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$isReclaim = $Operation -eq 'reclaim'
$isTransfer = $Operation -in @('transfer', 'upload', 'download')
$expectedUpload = $Operation -ne 'download'
$expectedDownload = $Operation -ne 'upload'
$expectedPhase = 'upload_and_independent_download'
$proofProperty = 'transport_receipt_sha256'
if ($Operation -eq 'upload') { $expectedPhase = 'upload_only'; $proofProperty = 'upload_receipt_sha256' }
if ($Operation -eq 'download') { $expectedPhase = 'download_and_verify' }
$workload = 'production_cold_archive_stage'
$module = 'weather.operations.production_cold_archive_stage_cli'
$outputDirectory = 'scratch\production_cold_archive'
if ($isTransfer) {
    $workload = 'production_cold_archive_transfer'
    if ($Operation -ne 'transfer') { $workload += '_' + $Operation }
    $module = 'weather.operations.production_cold_archive_transfer'
    $outputDirectory = 'scratch\production_cold_archive_transfer'
}
if ($isReclaim) {
    $workload = 'production_cold_archive_reclaim'
    $module = 'weather.operations.production_cold_archive_reclaim_cli'
    $outputDirectory = 'scratch\production_cold_archive_reclaim'
}
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$localNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
$minute = $localNow.Hour * 60 + $localNow.Minute
if ($minute -lt 30 -or $minute -ge 540) {
    throw 'REFUSED: archive operations are restricted to 00:30-09:00 America/Toronto'
}
if ($minute -ge 285 -and $minute -lt 405) {
    throw 'REFUSED: 04:45-06:45 is reserved for scheduled tiering jobs'
}
$windowEnd = [TimeZoneInfo]::ConvertTimeToUtc($localNow.Date.AddHours(9), $zone)
if ($minute -lt 285) {
    $windowEnd = [TimeZoneInfo]::ConvertTimeToUtc($localNow.Date.AddMinutes(285), $zone)
}
$deadline = [DateTime]::UtcNow.AddSeconds(300)
if ($deadline -gt $windowEnd.AddSeconds(-15)) { $deadline = $windowEnd.AddSeconds(-15) }
if (($deadline - [DateTime]::UtcNow).TotalSeconds -lt 30) {
    throw 'REFUSED: insufficient time for a bounded child and teardown'
}

foreach ($path in @($ProductionRepoRoot, $RequestPath, $OutputRoot)) {
    if (-not [IO.Path]::IsPathRooted($path) -or $path -match '["\r\n]' -or
        [IO.Path]::GetFullPath($path).TrimEnd('\') -cne $path.TrimEnd('\')) {
        throw 'absolute normalized paths without quotes or newlines are required'
    }
}

function Assert-ArchiveEvidenceAncestors {
    param([string]$Path)
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'evidence ancestors must be ordinary directories without reparse points'
            }
        }
        $current = Split-Path -Parent $current
    }
}

$outputParent = Join-Path $ProductionRepoRoot $outputDirectory
if ((Split-Path -Parent $OutputRoot) -ine $outputParent) {
    throw "output must be a new attempt under production $outputDirectory"
}
if (Test-Path -LiteralPath $OutputRoot) { throw 'spent output attempt: use a new reviewed request' }
Assert-ArchiveEvidenceAncestors -Path (Split-Path -Parent $OutputRoot)
$requestInfo = Get-Item -LiteralPath $RequestPath
if ($requestInfo.Length -gt 32768 -or
    ($requestInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'request is too large or is a reparse point'
}
if ((Get-FileHash -LiteralPath $RequestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $RequestSha256) {
    throw 'request SHA-256 mismatch'
}
$tip = [string](git -C $sourceRoot rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $tip.Trim() -cne $ExpectedSourceTip) { throw 'source tip mismatch' }
$dirty = @(git -C $sourceRoot status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw 'source worktree must be clean' }

. (Join-Path $sourceRoot 'scripts\ops\workload_admission.ps1')
. (Join-Path $sourceRoot 'scripts\ops\windows_kill_on_close_job.ps1')
. (Join-Path $sourceRoot 'scripts\ops\training_window_contract.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $sourceRoot
$hostIdentity = Get-WeatherExecutionHostId
if ($hostIdentity -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'this runner is restricted to the assigned dedicated capture host'
}
$python = Join-Path $ProductionRepoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'production project interpreter missing' }
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $ProductionRepoRoot `
    -Workload $workload -ExpectedExecutionHostId $hostIdentity
if ($null -eq $lease) { throw 'REFUSED: shared workload lease is busy' }

$job = $null
$process = $null
$exitCode = 1
$teardownProved = $false
$oldPythonPath = $env:PYTHONPATH
$oldSource = $env:WEATHER_PRODUCTION_ARCHIVE_SOURCE_ROOT
$oldOwner = $env:WEATHER_PRODUCTION_ARCHIVE_OWNER_PID
$oldDeadline = $env:WEATHER_PRODUCTION_ARCHIVE_DEADLINE_UTC
$receipt = [ordered]@{
    source_git_sha = $ExpectedSourceTip; request_sha256 = $RequestSha256
    execution_host_id = $hostIdentity; operation = $Operation
    started_at_utc = [DateTime]::UtcNow.ToString('o'); status = 'FAILED'
    hard_stop = $false; teardown_proved = $false; deleted_files = 0
    reclaimed_bytes = 0; cleanup_eligible = $false; source_retained = $true; upload_performed = $false
}
if ($isReclaim) {
    $receipt.deleted_files = $null
    $receipt.reclaimed_bytes = $null
    $receipt.source_retained = $null
    $receipt.reclaim_state = 'UNKNOWN'
}
if ($isTransfer) {
    # A terminated or malformed child cannot prove that a remote upload did not occur.
    $receipt.upload_performed = $null
    $receipt.upload_state = 'UNKNOWN'
    $receipt.remote_side_effect_possible = $true
}
try {
    # Identity, time and live lease precede even create-only attempt evidence.
    $null = New-Item -ItemType Directory -Path $OutputRoot
    $env:PYTHONPATH = Join-Path $sourceRoot 'src'
    $env:WEATHER_PRODUCTION_ARCHIVE_SOURCE_ROOT = $sourceRoot
    $env:WEATHER_PRODUCTION_ARCHIVE_OWNER_PID = [string]$PID
    $env:WEATHER_PRODUCTION_ARCHIVE_DEADLINE_UTC = $deadline.ToString('o')
    $arguments = @('-m', $module, $Operation,
        '--production-repo-root', $ProductionRepoRoot, '--request', $RequestPath,
        '--request-sha256', $RequestSha256, '--output-root', $OutputRoot,
        '--source-git-sha', $ExpectedSourceTip)
    $job = New-WeatherKillOnCloseJob
    $process = Start-WeatherProcessInJob -Job $job -FilePath $python `
        -ArgumentString (ConvertTo-ScheduledTaskArgumentString -Tokens $arguments) `
        -WorkingDirectory $sourceRoot
    $null = $process.Handle
    $process.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
    while (-not $process.HasExited) {
        if ([DateTime]::UtcNow -ge $deadline -or
            $process.PrivateMemorySize64 -gt 384MB -or $process.WorkingSet64 -gt 384MB) {
            $receipt.hard_stop = $true
            $receipt.error = 'child deadline or monitored process memory ceiling reached'
            break
        }
        Start-Sleep -Milliseconds 500
        $process.Refresh()
    }
    if (-not $receipt.hard_stop) {
        $process.WaitForExit()
        $exitCode = $process.ExitCode
        if ($null -eq $exitCode) { $exitCode = 1 }
    }
    $job.TerminateAndWait(5000)
    $teardownProved = $true
    $resultPath = Join-Path $OutputRoot 'result.json'
    if ($exitCode -eq 0 -and -not $receipt.hard_stop -and (Test-Path -LiteralPath $resultPath)) {
        if ((Get-Item -LiteralPath $resultPath).Length -gt 65536) { throw 'oversized child receipt' }
        $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
        if ($result.status -cne 'PASS' -or $result.request_sha256 -cne $RequestSha256 -or
            $result.source_git_sha -cne $ExpectedSourceTip -or
            $result.cleanup_eligible -ne $false -or
            $result.execution_host_id -cne $hostIdentity) { throw 'child receipt binding mismatch' }
        if ($isReclaim) {
            if ($result.operation -cne 'reclaim' -or $result.upload_performed -ne $false -or
                ($result.deleted_files -isnot [int] -and $result.deleted_files -isnot [long]) -or
                ($result.reclaimed_bytes -isnot [int] -and $result.reclaimed_bytes -isnot [long]) -or
                $result.deleted_files -lt 1 -or $result.deleted_files -gt 256 -or
                $result.reclaimed_bytes -lt 0 -or $result.reclaimed_bytes -gt 1TB -or
                $result.source_retained -isnot [bool] -or $result.source_retained -ne $false -or
                $result.reclaim_receipt_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
                $result.archive_id -isnot [string] -or $result.chunk_id -cnotmatch '^chunk-[0-9]{5}$' -or
                $result.attempt_id -isnot [string] -or $result.attempt_id -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$') {
                throw 'reclaim child receipt verification mismatch'
            }
            $reclaimReceiptPath = [IO.Path]::GetFullPath([string]$result.reclaim_receipt_path)
            $reclaimParent = Join-Path $ProductionRepoRoot 'data\cold_archive\catalog\reclaims'
            if (-not $reclaimReceiptPath.StartsWith($reclaimParent + '\', [StringComparison]::OrdinalIgnoreCase) -or
                (Split-Path -Leaf $reclaimReceiptPath) -cne 'receipt.json') {
                throw 'reclaim receipt escaped the production catalog'
            }
            Assert-ArchiveEvidenceAncestors -Path (Split-Path -Parent $reclaimReceiptPath)
            $reclaimInfo = Get-Item -LiteralPath $reclaimReceiptPath
            if (($reclaimInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                $reclaimInfo.Length -gt 2MB -or
                (Get-FileHash -LiteralPath $reclaimReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $result.reclaim_receipt_sha256) {
                throw 'reclaim receipt readback mismatch'
            }
        }
        elseif ($result.deleted_files -ne 0 -or $result.reclaimed_bytes -ne 0 -or
                $result.source_retained -ne $true) {
            throw 'retaining operation reported source deletion'
        }
        if ($isTransfer) {
            if ($result.upload_performed -isnot [bool] -or $result.upload_performed -ne $expectedUpload -or
                $result.independent_download -isnot [bool] -or $result.independent_download -ne $expectedDownload -or
                $result.operation -cne $expectedPhase -or
                $result.source_retained -isnot [bool] -or $result.cleanup_eligible -isnot [bool] -or
                $result.deleted_files -isnot [ValueType] -or $result.deleted_files -is [bool] -or
                $result.reclaimed_bytes -isnot [ValueType] -or $result.reclaimed_bytes -is [bool] -or
                $result.chunk_id -isnot [string] -or [string]::IsNullOrWhiteSpace($result.chunk_id) -or
                $result.archive_id -isnot [string] -or [string]::IsNullOrWhiteSpace($result.archive_id) -or
                ($result.ciphertext_bytes -isnot [int] -and $result.ciphertext_bytes -isnot [long]) -or
                $result.ciphertext_bytes -le 0 -or
                $result.crypt_receipt_sha256 -isnot [string] -or $result.crypt_receipt_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
                $result.$proofProperty -isnot [string] -or $result.$proofProperty -cnotmatch '^[0-9a-f]{64}$') {
                throw 'transfer child receipt verification mismatch'
            }
        }
        elseif ($result.upload_performed -ne $false) { throw 'stage child receipt claimed upload' }
        $finalTip = [string](git -C $sourceRoot rev-parse HEAD)
        if ($LASTEXITCODE -ne 0 -or $finalTip.Trim() -cne $ExpectedSourceTip) { throw 'source tip changed during operation' }
        $finalDirty = @(git -C $sourceRoot status --porcelain)
        if ($LASTEXITCODE -ne 0 -or $finalDirty.Count -ne 0) { throw 'source worktree changed during operation' }
        if ((Get-FileHash -LiteralPath $RequestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $RequestSha256) {
            throw 'approved request changed during operation'
        }
        $receipt.child_result_sha256 = (Get-FileHash -LiteralPath $resultPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $receipt.reclaimed_bytes = 0
        if ($isReclaim) {
            $receipt.deleted_files = $result.deleted_files
            $receipt.reclaimed_bytes = $result.reclaimed_bytes
            $receipt.source_retained = $false
            $receipt.reclaim_state = 'VERIFIED'
            $receipt.archive_id = $result.archive_id
            $receipt.attempt_id = $result.attempt_id
            $receipt.reclaim_receipt_sha256 = $result.reclaim_receipt_sha256
        }
        $receipt.chunk_id = $result.chunk_id
        if ($isTransfer) {
            $receipt.archive_id = $result.archive_id
            $receipt.ciphertext_bytes = $result.ciphertext_bytes
            $receipt.crypt_receipt_sha256 = $result.crypt_receipt_sha256
            $receipt[$proofProperty] = $result.$proofProperty
            $receipt.independent_download = $expectedDownload
            $receipt.upload_performed = $expectedUpload
            $receipt.upload_state = 'VERIFIED'
            if ($Operation -eq 'upload') { $receipt.upload_state = 'UPLOADED_NOT_DOWNLOADED' }
            if ($Operation -eq 'download') { $receipt.upload_state = 'NOT_PERFORMED' }
        }
        elseif (-not $isReclaim) {
            $receipt.logical_source_bytes = $result.logical_source_bytes
            $receipt.source_file_count = $result.source_file_count
            $receipt.core_receipt_sha256 = $result.core_receipt_sha256
        }
        $receipt.status = 'PASS'
    }
    else {
        if (-not $receipt.Contains('error')) { $receipt.error = 'child did not produce PASS; retain attempt and inspect child receipts' }
        $exitCode = 1
    }
}
catch {
    $receipt.status = 'FAILED'
    if ($isReclaim) {
        $receipt.deleted_files = $null; $receipt.reclaimed_bytes = $null
        $receipt.source_retained = $null; $receipt.reclaim_state = 'UNKNOWN'
    }
    if ($isTransfer) { $receipt.upload_performed = $null; $receipt.upload_state = 'UNKNOWN' }
    $receipt.error = $_.Exception.Message
    $exitCode = 1
}
finally {
    try {
        if ($job -and -not $teardownProved) { $job.TerminateAndWait(5000); $teardownProved = $true }
        if (-not $job) { $teardownProved = $true }
    }
    finally {
        $receipt.teardown_proved = $teardownProved
        $receipt.completed_at_utc = [DateTime]::UtcNow.ToString('o')
        if (-not $teardownProved) {
            $receipt.status = 'TEARDOWN_UNPROVED'; $exitCode = 1
            if ($isReclaim) {
                $receipt.deleted_files = $null; $receipt.reclaimed_bytes = $null
                $receipt.source_retained = $null; $receipt.reclaim_state = 'UNKNOWN'
            }
            if ($isTransfer) { $receipt.upload_performed = $null; $receipt.upload_state = 'UNKNOWN' }
        }
        if ($job) { $job.Dispose() }
        if ($process) { $process.Dispose() }
        $env:PYTHONPATH = $oldPythonPath
        $env:WEATHER_PRODUCTION_ARCHIVE_SOURCE_ROOT = $oldSource
        $env:WEATHER_PRODUCTION_ARCHIVE_OWNER_PID = $oldOwner
        $env:WEATHER_PRODUCTION_ARCHIVE_DEADLINE_UTC = $oldDeadline
        if ($teardownProved) { Exit-WeatherHeavyWorkloadLease -Lease $lease }
        else { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease }
        if (Test-Path -LiteralPath $OutputRoot -PathType Container) {
            Assert-ArchiveEvidenceAncestors -Path $OutputRoot
            $receiptPath = Join-Path $OutputRoot 'wrapper-result.json'
            $stream = [IO.File]::Open($receiptPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
            try {
                $bytes = [Text.Encoding]::UTF8.GetBytes(($receipt | ConvertTo-Json -Depth 8) + [Environment]::NewLine)
                $stream.Write($bytes, 0, $bytes.Length)
                $stream.Flush($true)
            }
            finally { $stream.Dispose() }
        }
    }
}
Write-Output ($receipt | ConvertTo-Json -Depth 8 -Compress)
exit $exitCode
