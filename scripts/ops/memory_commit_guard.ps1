# Commit-charge watchdog for the dedicated weather-capture host.
#
# 2026-07-12 incident: an ad-hoc `python -` analysis job grew to 36 GB of
# private commit on a 15.7 GB RAM / 48 GB pagefile host. Commit charge hit
# 99.4% (63.3/63.7 GB), the pagefile thrashed the data disk at 100%, and the
# snapshot + CLOB capture loops stalled for ~75 minutes before the process was
# killed manually. Scheduled `-m weather.*` pipelines are already governed by
# working-set caps and the capture-resource admission gate; ad-hoc interpreter
# jobs are the ungoverned class this guard covers.
#
# Policy:
#   commit >= 85%  -> log a WARNING with the top private-memory processes.
#   commit >= 92%  -> kill the single largest AD-HOC python offender above
#                     8 GB private bytes. Ad-hoc means `python -`, `python -c`,
#                     or a bare script invocation. NEVER kills `-m weather.*`
#                     module processes (capture loops, bots, chains) or any
#                     non-python process; if no eligible offender exists it
#                     logs CRITICAL and takes no action.
#   every run      -> orphan sweep: kill `python -` / `python -c` processes
#                     whose parent is gone and which are older than 30 min.
#                     A stdin/-c job's script and output have no owner once
#                     the parent dies; the 2026-07-12 incident's second
#                     process idled at only 1.3 GB (below every memory
#                     threshold) while reading 113 GB from the data disk.
#                     Orphaned bare-script python is logged but not killed
#                     (detached-by-design launchers exist in this repo).
#
# Registered by register_memory_commit_guard.ps1 (every 5 minutes).

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [double]$WarnPercent = 85.0,
    [double]$ActPercent = 92.0,
    [long]$MinKillPrivateBytes = 8GB,
    [double]$OrphanGraceMinutes = 30.0
)

$logDir = Join-Path $RepoRoot "data\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$logPath = Join-Path $logDir "memory_commit_guard.log"
$statusPath = Join-Path $logDir "memory_commit_guard_status.json"

function Write-GuardLog([string]$Level, [string]$Message) {
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Level, $Message
    Add-Content -Path $logPath -Value $line -Encoding utf8
}

$os = Get-CimInstance Win32_OperatingSystem
$commitTotalMB = [double]$os.TotalVirtualMemorySize / 1024.0
$commitUsedMB = ([double]$os.TotalVirtualMemorySize - [double]$os.FreeVirtualMemory) / 1024.0
$commitPercent = if ($commitTotalMB -gt 0) { 100.0 * $commitUsedMB / $commitTotalMB } else { 0.0 }
$freeRamMB = [double]$os.FreePhysicalMemory / 1024.0

$status = @{
    checked_at = (Get-Date -Format "o")
    commit_used_mb = [math]::Round($commitUsedMB, 0)
    commit_total_mb = [math]::Round($commitTotalMB, 0)
    commit_percent = [math]::Round($commitPercent, 1)
    free_ram_mb = [math]::Round($freeRamMB, 0)
    warn_percent = $WarnPercent
    act_percent = $ActPercent
    action = "none"
}

if ($commitPercent -ge $WarnPercent) {
    $top = Get-Process | Sort-Object PrivateMemorySize64 -Descending | Select-Object -First 5 |
        ForEach-Object { "{0}(pid {1})={2}MB" -f $_.Name, $_.Id, [math]::Round($_.PrivateMemorySize64 / 1MB, 0) }
    Write-GuardLog "WARNING" ("commit at {0}% ({1}/{2} MB); top: {3}" -f `
        [math]::Round($commitPercent, 1), [math]::Round($commitUsedMB, 0), [math]::Round($commitTotalMB, 0), ($top -join ", "))
    $status.action = "warned"
}

if ($commitPercent -ge $ActPercent) {
    $candidates = Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ForEach-Object {
        $proc = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
        if ($null -eq $proc) { return }
        $cmd = [string]$_.CommandLine
        # Governed weather modules are never eligible.
        if ($cmd -match "-m\s+weather\.") { return }
        # Ad-hoc profiles: stdin script, inline -c, or bare script path.
        $adhoc = ($cmd -match '(?i)python[w]?(\.exe)?"?\s+-\s*$') -or
                 ($cmd -match '(?i)python[w]?(\.exe)?"?\s+-c\s') -or
                 ($cmd -match '(?i)python[w]?(\.exe)?"?\s+[^-]\S*\.py')
        if (-not $adhoc) { return }
        if ($proc.PrivateMemorySize64 -lt $MinKillPrivateBytes) { return }
        [pscustomobject]@{
            Id = $_.ProcessId
            PrivateMB = [math]::Round($proc.PrivateMemorySize64 / 1MB, 0)
            CommandLine = $cmd.Substring(0, [Math]::Min(200, $cmd.Length))
        }
    } | Where-Object { $null -ne $_ } | Sort-Object PrivateMB -Descending

    $target = $candidates | Select-Object -First 1
    if ($null -ne $target) {
        Write-GuardLog "ACTION" ("commit at {0}%: killing ad-hoc python pid {1} ({2} MB): {3}" -f `
            [math]::Round($commitPercent, 1), $target.Id, $target.PrivateMB, $target.CommandLine)
        try {
            Stop-Process -Id $target.Id -Force -Confirm:$false -ErrorAction Stop
            $status.action = "killed_pid_$($target.Id)"
            Write-GuardLog "ACTION" ("pid {0} terminated" -f $target.Id)
        } catch {
            $status.action = "kill_failed_pid_$($target.Id)"
            Write-GuardLog "ERROR" ("failed to kill pid {0}: {1}" -f $target.Id, $_.Exception.Message)
        }
    } else {
        Write-GuardLog "CRITICAL" ("commit at {0}% but no eligible ad-hoc python offender above {1} MB; manual attention required" -f `
            [math]::Round($commitPercent, 1), [math]::Round($MinKillPrivateBytes / 1MB, 0))
        $status.action = "no_eligible_target"
    }
}

# ---- Orphan sweep: runs every invocation, independent of commit level ----
$orphanActions = @()
$allProcs = Get-CimInstance Win32_Process -Filter "Name like 'python%'"
$pidTable = @{}
Get-CimInstance Win32_Process | ForEach-Object { $pidTable[[uint32]$_.ProcessId] = $_.CreationDate }
foreach ($row in $allProcs) {
    $cmd = [string]$row.CommandLine
    if ($cmd -match "-m\s+weather\.") { continue }
    $isStdin = $cmd -match '(?i)python[w]?(\.exe)?"?\s+-\s*$'
    $isInline = $cmd -match '(?i)python[w]?(\.exe)?"?\s+-c\s'
    $isBareScript = $cmd -match '(?i)python[w]?(\.exe)?"?\s+[^-]\S*\.py'
    if (-not ($isStdin -or $isInline -or $isBareScript)) { continue }
    $ageMinutes = ((Get-Date) - $row.CreationDate).TotalMinutes
    if ($ageMinutes -lt $OrphanGraceMinutes) { continue }
    $ppid = [uint32]$row.ParentProcessId
    $parentBirth = $pidTable[$ppid]
    # Parent gone, or its PID was reused by a younger process.
    $orphaned = ($null -eq $parentBirth) -or ($parentBirth -gt $row.CreationDate)
    if (-not $orphaned) { continue }
    $proc = Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
    $privateMB = 0
    if ($proc) { $privateMB = [math]::Round($proc.PrivateMemorySize64 / 1MB, 0) }
    $readGB = [math]::Round([double]$row.ReadTransferCount / 1GB, 1)
    $summary = "pid {0} age {1}m private {2}MB read {3}GB: {4}" -f `
        $row.ProcessId, [math]::Round($ageMinutes, 0), $privateMB, $readGB, `
        $cmd.Substring(0, [Math]::Min(160, $cmd.Length))
    if ($isStdin -or $isInline) {
        Write-GuardLog "ACTION" ("orphaned ad-hoc python (parent {0} gone): killing {1}" -f $ppid, $summary)
        try {
            Stop-Process -Id $row.ProcessId -Force -Confirm:$false -ErrorAction Stop
            $orphanActions += "killed_pid_$($row.ProcessId)"
            Write-GuardLog "ACTION" ("pid {0} terminated" -f $row.ProcessId)
        } catch {
            $orphanActions += "kill_failed_pid_$($row.ProcessId)"
            Write-GuardLog "ERROR" ("failed to kill orphan pid {0}: {1}" -f $row.ProcessId, $_.Exception.Message)
        }
    } else {
        Write-GuardLog "WARNING" ("orphaned bare-script python left running (detached launchers are legitimate): {0}" -f $summary)
        $orphanActions += "warned_pid_$($row.ProcessId)"
    }
}
$status.orphan_sweep = if ($orphanActions.Count -gt 0) { $orphanActions -join "," } else { "clean" }

$status | ConvertTo-Json | Out-File -FilePath $statusPath -Encoding utf8
