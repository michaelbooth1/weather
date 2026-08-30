# Cross-process lease for heavyweight production-host work.
#
# Resource thresholds answer "can this job fit?"; this lease answers the independent
# question "is another heavyweight job already running?". The open file handle is the
# authority. Metadata is diagnostic only, so an unclean process exit releases ownership
# automatically even if old JSON remains on disk.

function Get-WeatherExecutionHostId {
    [CmdletBinding()]
    param()

    $machineGuid = [string](Get-ItemPropertyValue `
        -LiteralPath "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography" `
        -Name "MachineGuid" `
        -ErrorAction Stop)
    $machineGuid = $machineGuid.Trim().ToLowerInvariant()
    if (-not $machineGuid) {
        throw "execution host identity is unavailable"
    }
    $material = "international_live_execution_host_v2`0$machineGuid"
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($material)
        return -join ($hasher.ComputeHash($bytes) | ForEach-Object {
            $_.ToString("x2")
        })
    }
    finally { $hasher.Dispose() }
}


function Get-WeatherExecutionPrincipalId {
    [CmdletBinding()]
    param()

    $sid = [string]([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
    $sid = $sid.Trim().ToLowerInvariant()
    if (-not $sid) {
        throw "execution principal identity is unavailable"
    }
    $material = "international_live_execution_principal_v1`0$sid"
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($material)
        return -join ($hasher.ComputeHash($bytes) | ForEach-Object {
            $_.ToString("x2")
        })
    }
    finally { $hasher.Dispose() }
}


function Get-WeatherExecutionHostAssignment {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $path = Join-Path $RepoRoot "config\international_live_execution_host.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "execution-host assignment is absent"
    }
    try {
        $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
        if ($item.Length -le 0 -or $item.Length -gt 16384 -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "assignment is not a bounded regular file"
        }
        $assignment = [IO.File]::ReadAllText($item.FullName) | ConvertFrom-Json
    }
    catch {
        throw "execution-host assignment is not readable exact JSON"
    }
    $expectedNames = @(
        "active_portable_execution_host_id",
        "active_portable_execution_principal_id",
        "assignment_status",
        "dedicated_capture_execution_host_id",
        "reassignment_requires_new_production_tip",
        "schema_version"
    ) | Sort-Object
    $observedNames = @($assignment.PSObject.Properties.Name | Sort-Object)
    if (
        $observedNames.Count -ne $expectedNames.Count -or
        @(Compare-Object $expectedNames $observedNames).Count -ne 0 -or
        [string]$assignment.schema_version -cne
            "international_live_execution_host_assignment_v0.1" -or
        [string]$assignment.dedicated_capture_execution_host_id -cnotmatch
            '\A[0-9a-f]{64}\z' -or
        $assignment.reassignment_requires_new_production_tip -ne $true -or
        [string]$assignment.assignment_status -cnotin @("UNASSIGNED", "ASSIGNED")
    ) {
        throw "execution-host assignment contract is invalid"
    }
    if ([string]$assignment.assignment_status -ceq "UNASSIGNED") {
        if ($null -ne $assignment.active_portable_execution_host_id -or
            $null -ne $assignment.active_portable_execution_principal_id) {
            throw "unassigned execution-host registry contains an active identity"
        }
    }
    elseif (
        [string]$assignment.active_portable_execution_host_id -cnotmatch
            '\A[0-9a-f]{64}\z' -or
        [string]$assignment.active_portable_execution_principal_id -cnotmatch
            '\A[0-9a-f]{64}\z' -or
        [string]$assignment.active_portable_execution_host_id -ceq
            [string]$assignment.dedicated_capture_execution_host_id
    ) {
        throw "assigned portable execution-host identity is invalid"
    }
    return $assignment
}


function Get-WeatherHeavyWorkloadPolicyWindow {
    [CmdletBinding()]
    param(
        [datetime]$Now = (Get-Date),
        [switch]$AllowStageAWindow,
        [string]$OwnerApprovedException = ""
    )

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
        [string]$ExecutionHostProfile = "capture_colocated_v1",
        [string]$ExpectedExecutionHostId = ""
    )

    $executionHostId = Get-WeatherExecutionHostId
    $executionPrincipalId = $null
    if ($ExecutionHostProfile -ceq "portable_execution_v1") {
        $executionPrincipalId = Get-WeatherExecutionPrincipalId
        $assignment = Get-WeatherExecutionHostAssignment -RepoRoot $RepoRoot
        if ($executionHostId -ceq
            [string]$assignment.dedicated_capture_execution_host_id) {
            throw (
                "portable execution-host admission is forbidden on the " +
                "dedicated capture host"
            )
        }
        if (
            [string]$assignment.assignment_status -cne "ASSIGNED" -or
            $executionHostId -cne
                [string]$assignment.active_portable_execution_host_id -or
            $executionPrincipalId -cne
                [string]$assignment.active_portable_execution_principal_id
        ) {
            throw "this host and Windows principal are not the active portable executor"
        }
        if ($AllowStageAWindow -or $OwnerApprovedException) {
            throw (
                "portable execution-host admission cannot combine with Stage-A " +
                "or owner-approved exceptions"
            )
        }
        if (
            $Workload.Length -gt 96 -or
            $Workload -cnotmatch (
                '\AInternationalLive-(?:stage0|stage1_cancel_all|stage1_dead_man)-' +
                '[A-Za-z0-9._-]+-[0-9a-f]{12}\z'
            )
        ) {
            throw "portable execution-host admission requires a canonical International live workload"
        }
        if (
            $ExpectedExecutionHostId -cnotmatch '\A[0-9a-f]{64}\z' -or
            $ExpectedExecutionHostId -cne $executionHostId
        ) {
            throw "portable execution-host identity does not match the sealed host binding"
        }
        $policyWindow = "portable_execution"
    }
    elseif ($ExecutionHostProfile -ceq "capture_colocated_v1") {
        if ($Workload -cmatch '\AInternationalLive-') {
            $assignment = Get-WeatherExecutionHostAssignment -RepoRoot $RepoRoot
            if ($executionHostId -cne
                [string]$assignment.dedicated_capture_execution_host_id) {
                throw (
                    "capture-colocated International live admission is restricted " +
                    "to the dedicated capture host"
                )
            }
            if ([string]$assignment.assignment_status -ceq "ASSIGNED") {
                throw (
                    "capture-colocated International live admission is disabled " +
                    "while a portable executor is assigned"
                )
            }
        }
        if (
            $ExpectedExecutionHostId -and
            ($ExpectedExecutionHostId -cnotmatch '\A[0-9a-f]{64}\z' -or
             $ExpectedExecutionHostId -cne $executionHostId)
        ) {
            throw "capture-colocated execution-host identity does not match the sealed host binding"
        }
        if ($OwnerApprovedException -and $Workload -cne "quiet_window_merge") {
            throw "owner-approved workload exception is restricted to quiet_window_merge"
        }
        $policyWindow = Get-WeatherHeavyWorkloadPolicyWindow `
            -AllowStageAWindow:$AllowStageAWindow `
            -OwnerApprovedException $OwnerApprovedException
        if ($null -eq $policyWindow) {
            throw (
                "heavy workload '{0}' is outside the 00:30-09:00 window; " +
                "only the explicit Stage-A lane may acquire the lease at 09:30-11:55"
            ) -f $Workload
        }
    }
    else {
        throw "execution-host profile is unsupported"
    }

    $mutex = $null
    $mutexOwned = $false
    try {
        $mutex = [Threading.Mutex]::new(
            $false,
            "Global\WeatherProjectHeavyWorkloadV1"
        )
        try { $mutexOwned = $mutex.WaitOne(0, $false) }
        catch [Threading.AbandonedMutexException] { $mutexOwned = $true }
        if (-not $mutexOwned) {
            $mutex.Dispose()
            return $null
        }
    }
    catch {
        if ($mutexOwned -and $mutex) {
            try { $mutex.ReleaseMutex() } catch { }
        }
        if ($mutex) { $mutex.Dispose() }
        throw "host-global workload mutex could not be acquired"
    }

    try {
        $logRoot = Join-Path $RepoRoot "data\logs"
        if (-not (Test-Path -LiteralPath $logRoot)) {
            New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
        }
        $path = Join-Path $logRoot "heavy_workload.lock"
    }
    catch {
        if ($mutexOwned) {
            try { $mutex.ReleaseMutex() } catch { }
        }
        $mutex.Dispose()
        throw
    }
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
    catch [System.IO.IOException] {
        $mutex.ReleaseMutex()
        $mutex.Dispose()
        return $null
    }
    catch {
        $mutex.ReleaseMutex()
        $mutex.Dispose()
        throw
    }

    try {
        $stream.SetLength(0)
        $record = [ordered]@{
            schema_version = "weather_heavy_workload_lease_v2"
            workload = $Workload
            pid = $PID
            acquired_at = (Get-Date).ToUniversalTime().ToString("o")
            policy_window = $policyWindow
            host = [Environment]::MachineName
            execution_host_profile = $ExecutionHostProfile
            execution_host_id = $executionHostId
            execution_principal_id = $executionPrincipalId
            host_global_mutex = "Global\WeatherProjectHeavyWorkloadV1"
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
            Mutex = $mutex
            MutexOwned = $mutexOwned
            ExecutionHostProfile = $ExecutionHostProfile
            ExecutionHostId = $executionHostId
            ExecutionPrincipalId = $executionPrincipalId
        }
    }
    catch {
        $stream.Dispose()
        if ($mutexOwned) {
            try { $mutex.ReleaseMutex() } catch { }
        }
        $mutex.Dispose()
        throw
    }
}


function Exit-WeatherHeavyWorkloadLease {
    [CmdletBinding()]
    param($Lease)
    try {
        if ($null -ne $Lease -and
            $Lease.PSObject.Properties.Name -contains "Stream" -and
            $null -ne $Lease.Stream) {
            $Lease.Stream.Dispose()
        }
    }
    finally {
        if ($null -ne $Lease -and
            $Lease.PSObject.Properties.Name -contains "MutexOwned" -and
            $Lease.PSObject.Properties.Name -contains "Mutex" -and
            $Lease.MutexOwned -and $null -ne $Lease.Mutex) {
            try { $Lease.Mutex.ReleaseMutex() }
            finally { $Lease.Mutex.Dispose() }
        }
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
