# Cross-process lease for heavyweight production-host work.
#
# Resource thresholds answer "can this job fit?"; this lease answers the independent
# question "is another heavyweight job already running?". The open file handle is the
# authority. Metadata is diagnostic only, so an unclean process exit releases ownership
# automatically even if old JSON remains on disk.

function Get-WeatherHeavyWorkloadPolicyWindow {
    [CmdletBinding()]
    param(
        [datetime]$Now = (Get-Date),
        [switch]$AllowStageAWindow
    )

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
        [switch]$AllowStageAWindow
    )

    $policyWindow = Get-WeatherHeavyWorkloadPolicyWindow `
        -AllowStageAWindow:$AllowStageAWindow
    if ($null -eq $policyWindow) {
        throw (
            "heavy workload '{0}' is outside the 00:30-09:00 window; " +
            "only the explicit Stage-A lane may acquire the lease at 09:30-11:55"
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
            schema_version = "weather_heavy_workload_lease_v1"
            workload = $Workload
            pid = $PID
            acquired_at = (Get-Date).ToUniversalTime().ToString("o")
            policy_window = $policyWindow
            host = $env:COMPUTERNAME
        }
        $encoding = New-Object System.Text.UTF8Encoding($false)
        $writer = New-Object System.IO.StreamWriter($stream, $encoding, 1024, $true)
        try {
            $writer.Write(($record | ConvertTo-Json -Compress))
            $writer.Flush()
            $stream.Flush()
        }
        finally { $writer.Dispose() }
        return [PSCustomObject]@{ Path = $path; Workload = $Workload; Stream = $stream }
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
