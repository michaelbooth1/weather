# Cross-process lease for heavyweight production-host work.
#
# Resource thresholds answer "can this job fit?"; this lease answers the independent
# question "is another heavyweight job already running?". The open file handle is the
# authority. Metadata is diagnostic only, so an unclean process exit releases ownership
# automatically even if old JSON remains on disk.

function Resolve-WeatherOwnerApprovedShortTask {
    [CmdletBinding()]
    param(
        [datetime]$Now = (Get-Date),
        [string]$Workload = "",
        [switch]$OwnerApprovedShortTask,
        [string]$OwnerApprovalId = "",
        [string]$OwnerApprovalReason = "",
        [int]$OwnerApprovalMinutes = 0,
        [switch]$AllowStageAWindow,
        [string]$OwnerApprovedException = ""
    )

    $hasOwnerShortTaskInput = (
        $OwnerApprovedShortTask -or
        -not [string]::IsNullOrWhiteSpace($OwnerApprovalId) -or
        -not [string]::IsNullOrWhiteSpace($OwnerApprovalReason) -or
        $OwnerApprovalMinutes -ne 0
    )
    if (-not $hasOwnerShortTaskInput) { return $null }

    if (-not $OwnerApprovedShortTask) {
        throw "owner short-task fields require -OwnerApprovedShortTask"
    }
    if ($AllowStageAWindow -or $OwnerApprovedException) {
        throw "owner short-task approval cannot be combined with another workload exception"
    }
    if ([string]::IsNullOrWhiteSpace($Workload)) {
        throw "owner short-task approval requires an exact workload name"
    }

    $approvalId = $OwnerApprovalId.Trim()
    if ($approvalId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$') {
        throw "owner short-task approval ID must be 3-64 safe identifier characters"
    }

    $reason = $OwnerApprovalReason.Trim()
    if (
        $reason.Length -lt 8 -or
        $reason.Length -gt 256 -or
        $reason.Contains("`r") -or
        $reason.Contains("`n")
    ) {
        throw "owner short-task reason must be a single line of 8-256 characters"
    }
    if ($OwnerApprovalMinutes -lt 1 -or $OwnerApprovalMinutes -gt 30) {
        throw "owner short-task approval must be between 1 and 30 minutes"
    }

    $expiresAtUtc = $Now.ToUniversalTime().AddMinutes($OwnerApprovalMinutes)
    return [PSCustomObject]@{
        PolicyWindow = "owner_approved_short_task"
        ApprovalId = $approvalId
        Reason = $reason
        MaxMinutes = $OwnerApprovalMinutes
        ExpiresAtUtc = $expiresAtUtc
    }
}

function Get-WeatherHeavyWorkloadPolicyWindow {
    [CmdletBinding()]
    param(
        [datetime]$Now = (Get-Date),
        [string]$Workload = "",
        [switch]$AllowStageAWindow,
        [string]$OwnerApprovedException = "",
        [switch]$OwnerApprovedShortTask,
        [string]$OwnerApprovalId = "",
        [string]$OwnerApprovalReason = "",
        [int]$OwnerApprovalMinutes = 0
    )

    $ownerShortTask = Resolve-WeatherOwnerApprovedShortTask `
        -Now $Now `
        -Workload $Workload `
        -OwnerApprovedShortTask:$OwnerApprovedShortTask `
        -OwnerApprovalId $OwnerApprovalId `
        -OwnerApprovalReason $OwnerApprovalReason `
        -OwnerApprovalMinutes $OwnerApprovalMinutes `
        -AllowStageAWindow:$AllowStageAWindow `
        -OwnerApprovedException $OwnerApprovedException
    if ($null -ne $ownerShortTask) { return $ownerShortTask.PolicyWindow }

    if ($OwnerApprovedException) {
        if (
            $OwnerApprovedException -cne
                "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" -or
            $Now.ToString("yyyy-MM-dd") -cne "2026-08-23"
        ) {
            throw "owner-approved workload exception is invalid or expired"
        }
        return "owner_approved_merge_20260823"
    }

    $localMinute = ($Now.Hour * 60) + $Now.Minute
    if ($localMinute -ge 30 -and $localMinute -lt (9 * 60)) {
        return "agent_heavy"
    }
    if (
        $AllowStageAWindow -and
        $localMinute -ge (9 * 60 + 30) -and
        $localMinute -lt (11 * 60 + 55)
    ) {
        return "stage_a"
    }
    return $null
}


function Enter-WeatherHeavyWorkloadLease {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Workload,
        [switch]$AllowStageAWindow,
        [string]$OwnerApprovedException = "",
        [switch]$OwnerApprovedShortTask,
        [string]$OwnerApprovalId = "",
        [string]$OwnerApprovalReason = "",
        [int]$OwnerApprovalMinutes = 0
    )

    if ($OwnerApprovedException -and $Workload -cne "quiet_window_merge") {
        throw "owner-approved workload exception is restricted to quiet_window_merge"
    }
    $now = Get-Date
    $ownerShortTask = Resolve-WeatherOwnerApprovedShortTask `
        -Now $now `
        -Workload $Workload `
        -OwnerApprovedShortTask:$OwnerApprovedShortTask `
        -OwnerApprovalId $OwnerApprovalId `
        -OwnerApprovalReason $OwnerApprovalReason `
        -OwnerApprovalMinutes $OwnerApprovalMinutes `
        -AllowStageAWindow:$AllowStageAWindow `
        -OwnerApprovedException $OwnerApprovedException
    $policyWindow = Get-WeatherHeavyWorkloadPolicyWindow `
        -Now $now `
        -Workload $Workload `
        -AllowStageAWindow:$AllowStageAWindow `
        -OwnerApprovedException $OwnerApprovedException `
        -OwnerApprovedShortTask:$OwnerApprovedShortTask `
        -OwnerApprovalId $OwnerApprovalId `
        -OwnerApprovalReason $OwnerApprovalReason `
        -OwnerApprovalMinutes $OwnerApprovalMinutes
    if ($null -eq $policyWindow) {
        throw (
            "heavy workload '{0}' is outside the 00:30-09:00 window; " +
            "only the explicit Stage-A lane at 09:30-11:55 or a complete " +
            "owner-approved short-task grant may acquire the lease"
        ) -f $Workload
    }

    $logRoot = Join-Path $RepoRoot "data\logs"
    if (-not (Test-Path -LiteralPath $logRoot)) {
        New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    }
    $path = Join-Path $logRoot "heavy_workload.lock"
    $stream = $null
    try {
        # Readers may inspect the owner record, but a second ReadWrite owner cannot open it.
        $stream = [System.IO.File]::Open(
            $path,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::Read
        )
    }
    catch [System.IO.IOException] { return $null }

    try {
        $stream.SetLength(0)
        $record = [ordered]@{
            schema_version = "weather_heavy_workload_lease_v2"
            workload = $Workload
            pid = $PID
            acquired_at = $now.ToUniversalTime().ToString("o")
            policy_window = $policyWindow
            host = $env:COMPUTERNAME
        }
        if ($null -ne $ownerShortTask) {
            $record.owner_approval = [ordered]@{
                approval_id = $ownerShortTask.ApprovalId
                reason = $ownerShortTask.Reason
                max_minutes = $ownerShortTask.MaxMinutes
                expires_at_utc = $ownerShortTask.ExpiresAtUtc.ToString("o")
            }
        }
        $encoding = New-Object System.Text.UTF8Encoding($false)
        $writer = New-Object System.IO.StreamWriter($stream, $encoding, 1024, $true)
        try {
            $writer.Write(($record | ConvertTo-Json -Compress))
            $writer.Flush()
            $stream.Flush()
        }
        finally { $writer.Dispose() }
        return [PSCustomObject]@{
            Path = $path
            Workload = $Workload
            Stream = $stream
            PolicyWindow = $policyWindow
            OwnerApproval = $ownerShortTask
            ExpiresAtUtc = if ($null -ne $ownerShortTask) {
                $ownerShortTask.ExpiresAtUtc
            } else { $null }
        }
    }
    catch {
        $stream.Dispose()
        throw
    }
}


function Exit-WeatherHeavyWorkloadLease {
    [CmdletBinding()]
    param($Lease)
    if ($null -ne $Lease -and $null -ne $Lease.Stream) {
        $Lease.Stream.Dispose()
    }
}


function Get-WeatherHeavyWorkloadLeaseState {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $path = Join-Path $RepoRoot "data\logs\heavy_workload.lock"
    if (-not (Test-Path -LiteralPath $path)) {
        return [PSCustomObject]@{ Active = $false; Path = $path; Owner = $null }
    }

    $probe = $null
    try {
        # The owner permits readers but not writers. A no-op write-capable open therefore
        # distinguishes an active OS-held lease from stale diagnostic JSON.
        $probe = [System.IO.File]::Open(
            $path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::ReadWrite
        )
        return [PSCustomObject]@{ Active = $false; Path = $path; Owner = $null }
    }
    catch [System.IO.IOException] {
        $owner = $null
        try { $owner = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch {}
        return [PSCustomObject]@{ Active = $true; Path = $path; Owner = $owner }
    }
    finally { if ($probe) { $probe.Dispose() } }
}
