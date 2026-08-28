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
#   physical RAM available < 1.5 GiB -> log a WARNING with the top
#                     working-set processes. This is observability only;
#                     termination decisions remain commit-based.
#   commit >= 85%  -> log a WARNING with the top private-memory processes.
#   commit >= 92%  -> kill the single largest ungoverned offender above
#                     8 GB private bytes. This includes ad-hoc Python and a
#                     Codex/ChatGPT-owned process tree. Production
#                     `-m weather.*` workers are excluded by ancestry and
#                     command identity.
#   every run      -> outside 00:30-09:00, terminate Codex-owned pytest,
#                     compileall, inline/bare Python, and recursive scans.
#                     Inside that window, retain at most one such tool tree.
#   every run      -> orphan sweep: kill `python -` / `python -c` processes
#                     whose parent is gone and which are older than 30 min.
#                     A stdin/-c job's script and output have no owner once
#                     the parent dies; the 2026-07-12 incident's second
#                     process idled at only 1.3 GB (below every memory
#                     threshold) while reading 113 GB from the data disk.
#                     Orphaned bare-script python is logged but not killed
#                     (detached-by-design launchers exist in this repo).
#
# Registered by register_memory_commit_guard.ps1 (every minute).

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$ExpectedExecutionHostId = "",
    [double]$WarnPercent = 85.0,
    [double]$ActPercent = 92.0,
    [long]$MinKillPrivateBytes = 8GB,
    [double]$OrphanGraceMinutes = 30.0,
    [long]$WarnFreePhysicalBytes = 1536MB,
    [ValidateRange(0.0, 3600.0)]
    [double]$AgentWorkloadGraceSeconds = 15.0,
    [ValidateRange(0, 64)]
    [int]$MaxConcurrentAgentHeavyWorkloads = 1
)

function Get-MemoryGuardExecutionHostId {
    $machineGuid = [string](Get-ItemPropertyValue `
        -LiteralPath "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography" `
        -Name "MachineGuid" `
        -ErrorAction Stop)
    $machineGuid = $machineGuid.Trim().ToLowerInvariant()
    if (-not $machineGuid) {
        throw "memory guard execution-host identity is unavailable"
    }
    $material = "international_live_execution_host_v2`0$machineGuid"
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return -join ($hasher.ComputeHash(
            [Text.Encoding]::UTF8.GetBytes($material)
        ) | ForEach-Object { $_.ToString("x2") })
    }
    finally { $hasher.Dispose() }
}

# Existing production registrations predate the immutable host binding and
# retain their protection until the separately authorized registrar is rerun.
# Every new registration supplies the exact validated capture-host ID.
if ($ExpectedExecutionHostId) {
    if ($ExpectedExecutionHostId -cnotmatch '\A[0-9a-f]{64}\z') {
        throw "memory guard expected execution-host identity is invalid"
    }
    $guardExecutionHostId = Get-MemoryGuardExecutionHostId
    if ($guardExecutionHostId -cne $ExpectedExecutionHostId) {
        Write-Output (
            "SKIPPED: memory commit guard is restricted to its registered " +
            "dedicated capture host"
        )
        exit 0
    }
}

$logDir = Join-Path $RepoRoot "data\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$logPath = Join-Path $logDir "memory_commit_guard.log"
$statusPath = Join-Path $logDir "memory_commit_guard_status.json"
$historyPath = Join-Path $logDir "memory_commit_guard_history.jsonl"

function Write-GuardLog([string]$Level, [string]$Message) {
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Level, $Message
    Add-Content -Path $logPath -Value $line -Encoding utf8
}

$agentRootNames = @("codex.exe", "chatgpt.exe", "claude.exe")
$agentShellNames = @("powershell.exe", "pwsh.exe", "cmd.exe")
$terminationPerformed = $false
$guardActions = New-Object System.Collections.Generic.List[string]

function Test-GovernedWeatherProcess($ProcessRow) {
    $name = ([string]$ProcessRow.Name).ToLowerInvariant()
    $cmd = [string]$ProcessRow.CommandLine
    return ($name -match '^pythonw?\.exe$') -and ($cmd -match '(?i)(?:^|\s)-m\s+weather\.')
}

function Test-AgentHeavyProcess($ProcessRow) {
    $name = ([string]$ProcessRow.Name).ToLowerInvariant()
    $cmd = [string]$ProcessRow.CommandLine
    if ([string]::IsNullOrWhiteSpace($cmd)) { return $false }

    if ($name -match '^pythonw?\.exe$') {
        if (Test-GovernedWeatherProcess $ProcessRow) { return $false }
        return ($cmd -match '(?i)(?:^|\s)-m\s+(?:pytest|compileall|coverage|tox|nox)(?:\s|$)') -or
            ($cmd -match '(?i)pythonw?(?:\.exe)?"?\s+-\s*$') -or
            ($cmd -match '(?i)pythonw?(?:\.exe)?"?\s+-c\s') -or
            ($cmd -match '(?i)pythonw?(?:\.exe)?"?\s+[^-]\S*\.py(?:\s|$)')
    }

    if ($agentShellNames -contains $name) {
        $normalized = $cmd.Replace('/', '\')
        return ($cmd -match '(?i)(?:^|\s)-m\s+(?:pytest|compileall|coverage|tox|nox)(?:\s|$)') -or
            ($cmd -match '(?i)(?:^|\s)-m\s+weather\.[^\s]*(?:retrain|training|replay|backtest|daily_refresh|score_all)') -or
            (($cmd -match '(?i)Get-ChildItem') -and ($cmd -match '(?i)-Recurse')) -or
            (($cmd -match '(?i)(?:^|[\s;&|])rg(?:\.exe)?(?:\s|$)') -and
                ($normalized -match '(?i)(?:^|[\s"''])(?:\.\\)?data(?:\\|[\s"''])'))
    }

    return ($name -eq 'pytest.exe')
}

function Get-AgentToolRoot($ProcessRow, $ProcessByPid) {
    $path = New-Object System.Collections.Generic.List[object]
    $current = $ProcessRow
    for ($depth = 0; $depth -lt 32 -and $null -ne $current; $depth++) {
        $path.Add($current)
        $name = ([string]$current.Name).ToLowerInvariant()
        if ($agentRootNames -contains $name) {
            if ($path.Count -lt 2) { return $null }
            return $path[$path.Count - 2]
        }
        $parentId = [uint32]$current.ParentProcessId
        if (-not $ProcessByPid.ContainsKey($parentId)) { return $null }
        $parent = $ProcessByPid[$parentId]
        if ([datetime]$parent.CreationDate -gt [datetime]$current.CreationDate) { return $null }
        $current = $parent
    }
    return $null
}

function Get-ProcessTreeRows($RootRow, $AllProcesses) {
    $selected = @{}
    $queue = New-Object System.Collections.Generic.Queue[object]
    $queue.Enqueue($RootRow)
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        $key = [uint32]$current.ProcessId
        if ($selected.ContainsKey($key)) { continue }
        $selected[$key] = $current
        foreach ($child in $AllProcesses) {
            if ([uint32]$child.ParentProcessId -ne $key) { continue }
            if ([datetime]$child.CreationDate -lt [datetime]$current.CreationDate) { continue }
            $queue.Enqueue($child)
        }
    }
    return @($selected.Values)
}

function Stop-VerifiedProcessTree(
    $RootRow,
    $AllProcesses,
    [string]$Reason,
    [bool]$AllowWeatherDescendants = $false
) {
    $tree = @(Get-ProcessTreeRows $RootRow $AllProcesses)
    $governed = @($tree | Where-Object { Test-GovernedWeatherProcess $_ })
    if (-not $AllowWeatherDescendants -and $governed.Count -gt 0) {
        Write-GuardLog "CRITICAL" ("refusing agent-tree termination for pid {0}: tree contains {1} governed weather process(es)" -f $RootRow.ProcessId, $governed.Count)
        return $false
    }

    $depthByPid = @{}
    $depthByPid[[uint32]$RootRow.ProcessId] = 0
    $pending = @($tree | Where-Object { [uint32]$_.ProcessId -ne [uint32]$RootRow.ProcessId })
    while ($pending.Count -gt 0) {
        $progress = $false
        $next = @()
        foreach ($row in $pending) {
            $parentId = [uint32]$row.ParentProcessId
            if (-not $depthByPid.ContainsKey($parentId)) { $next += $row; continue }
            $depthByPid[[uint32]$row.ProcessId] = 1 + [int]$depthByPid[$parentId]
            $progress = $true
        }
        if (-not $progress) { break }
        $pending = @($next)
    }

    $ok = $true
    $ordered = @($tree | Sort-Object @{ Expression = {
        $pid = [uint32]$_.ProcessId
        if ($depthByPid.ContainsKey($pid)) { -[int]$depthByPid[$pid] } else { 0 }
    } })
    Write-GuardLog "ACTION" ("{0}; terminating verified process tree root pid {1} members {2}" -f $Reason, $RootRow.ProcessId, $tree.Count)
    foreach ($row in $ordered) {
        $pid = [uint32]$row.ProcessId
        $current = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $pid) -ErrorAction SilentlyContinue
        if (-not $current) { continue }
        if ([datetime]$current.CreationDate -ne [datetime]$row.CreationDate) {
            Write-GuardLog "ERROR" ("pid {0} creation identity changed before termination" -f $pid)
            $ok = $false
            continue
        }
        try {
            Stop-Process -Id $pid -Force -Confirm:$false -ErrorAction Stop
        }
        catch {
            Write-GuardLog "ERROR" ("failed to terminate pid {0}: {1}" -f $pid, $_.Exception.Message)
            $ok = $false
        }
    }
    return $ok
}

function Get-ProcessTreePrivateBytes($RootRow, $AllProcesses, $RuntimeByPid) {
    $privateBytes = [long]0
    foreach ($member in @(Get-ProcessTreeRows $RootRow $AllProcesses)) {
        $runtime = $RuntimeByPid[[uint32]$member.ProcessId]
        if ($runtime) { $privateBytes += [long]$runtime.PrivateMemorySize64 }
    }
    return $privateBytes
}

$os = Get-CimInstance Win32_OperatingSystem
$commitTotalMB = [double]$os.TotalVirtualMemorySize / 1024.0
$commitUsedMB = ([double]$os.TotalVirtualMemorySize - [double]$os.FreeVirtualMemory) / 1024.0
$commitPercent = if ($commitTotalMB -gt 0) { 100.0 * $commitUsedMB / $commitTotalMB } else { 0.0 }
$freeRamMB = [double]$os.FreePhysicalMemory / 1024.0
$warnFreePhysicalMB = [double]$WarnFreePhysicalBytes / 1MB
$allProcesses = @(Get-CimInstance Win32_Process)
$processByPid = @{}
$runtimeByPid = @{}
foreach ($row in $allProcesses) {
    $processByPid[[uint32]$row.ProcessId] = $row
    $runtimeByPid[[uint32]$row.ProcessId] = Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
}

$status = @{
    checked_at = (Get-Date -Format "o")
    commit_used_mb = [math]::Round($commitUsedMB, 0)
    commit_total_mb = [math]::Round($commitTotalMB, 0)
    commit_percent = [math]::Round($commitPercent, 1)
    free_ram_mb = [math]::Round($freeRamMB, 0)
    physical_warn_below_mb = [math]::Round($warnFreePhysicalMB, 0)
    physical_warning = $false
    memory_warning = $false
    warn_percent = $WarnPercent
    act_percent = $ActPercent
    action = "none"
    actions = @()
    agent_heavy_process_count = 0
    agent_heavy_workload_count = 0
    agent_heavy_max_private_mb = 0
    agent_heavy_window_allowed = $false
}

# A previous Codex session launched 42 pytest/compile invocations across
# concurrent agents inside the protected window. Enforce the existing host
# policy from OS process ancestry, not from model compliance. Each distinct
# direct tool subtree is one workload; a PID is accepted only while its parent
# creation identity is older, which closes the Windows PID-reuse hole.
$localNow = Get-Date
$minuteOfDay = (60 * $localNow.Hour) + $localNow.Minute + ($localNow.Second / 60.0)
$agentHeavyWindowAllowed = ($minuteOfDay -ge 30.0) -and ($minuteOfDay -lt 540.0)
$status.agent_heavy_window_allowed = $agentHeavyWindowAllowed
$heavyToolRoots = @{}
foreach ($row in $allProcesses) {
    if (-not (Test-AgentHeavyProcess $row)) { continue }
    $ageSeconds = ($localNow - [datetime]$row.CreationDate).TotalSeconds
    if ($ageSeconds -lt $AgentWorkloadGraceSeconds) { continue }
    $toolRoot = Get-AgentToolRoot $row $processByPid
    if (-not $toolRoot) { continue }
    $key = "{0}|{1}" -f $toolRoot.ProcessId, ([datetime]$toolRoot.CreationDate).ToUniversalTime().Ticks
    if (-not $heavyToolRoots.ContainsKey($key)) { $heavyToolRoots[$key] = $toolRoot }
}
$agentHeavyRows = @($allProcesses | Where-Object {
    if (-not (Test-AgentHeavyProcess $_)) { return $false }
    return $null -ne (Get-AgentToolRoot $_ $processByPid)
})
$status.agent_heavy_process_count = $agentHeavyRows.Count
$status.agent_heavy_workload_count = $heavyToolRoots.Count

$agentTreeBytes = @{}
foreach ($entry in $heavyToolRoots.GetEnumerator()) {
    $agentTreeBytes[$entry.Key] = Get-ProcessTreePrivateBytes $entry.Value $allProcesses $runtimeByPid
}
if ($agentTreeBytes.Count -gt 0) {
    $status.agent_heavy_max_private_mb = [math]::Round(
        (($agentTreeBytes.Values | Measure-Object -Maximum).Maximum / 1MB),
        0
    )
}

$agentTargetMap = @{}
if (-not $agentHeavyWindowAllowed) {
    foreach ($entry in $heavyToolRoots.GetEnumerator()) { $agentTargetMap[$entry.Key] = $entry.Value }
}
elseif ($heavyToolRoots.Count -gt $MaxConcurrentAgentHeavyWorkloads) {
    $orderedRoots = @($heavyToolRoots.Values | Sort-Object CreationDate, ProcessId)
    foreach ($root in @($orderedRoots | Select-Object -Skip $MaxConcurrentAgentHeavyWorkloads)) {
        $key = "{0}|{1}" -f $root.ProcessId, ([datetime]$root.CreationDate).ToUniversalTime().Ticks
        $agentTargetMap[$key] = $root
    }
}
foreach ($entry in $heavyToolRoots.GetEnumerator()) {
    if ([long]$agentTreeBytes[$entry.Key] -ge $MinKillPrivateBytes) {
        $agentTargetMap[$entry.Key] = $entry.Value
    }
}
foreach ($entry in $agentTargetMap.GetEnumerator()) {
    $target = $entry.Value
    $treePrivateMB = [math]::Round(([long]$agentTreeBytes[$entry.Key] / 1MB), 0)
    $reason = if ([long]$agentTreeBytes[$entry.Key] -ge $MinKillPrivateBytes) {
        "Codex tool tree exceeds the $([math]::Round($MinKillPrivateBytes / 1MB, 0)) MB private budget (observed ${treePrivateMB} MB)"
    } elseif ($agentHeavyWindowAllowed) {
        "Codex heavy-workload concurrency exceeds $MaxConcurrentAgentHeavyWorkloads"
    } else {
        "Codex heavy workload is outside the 00:30-09:00 host window"
    }
    if (Stop-VerifiedProcessTree $target $allProcesses $reason $true) {
        $action = "killed_agent_tree_pid_$($target.ProcessId)"
        $guardActions.Add($action)
        $terminationPerformed = $true
    } else {
        $guardActions.Add("kill_failed_agent_tree_pid_$($target.ProcessId)")
    }
}

# A scheduled PowerShell wrapper can be terminated while its delegated Python
# child survives in the S4U session. That happened to the evidence refresh on
# 2026-08-13: Task Scheduler no longer owned the run, but the orphaned
# weather.operations.daily_refresh child exhausted host commit and starved
# every snapshot market inside the graded window. The ordinary commit rule
# deliberately exempts governed weather modules, so handle this narrower case
# from scheduler truth: during the protected window, an evidence-refresh child
# older than two minutes cannot be legitimate when its owning task is not
# Running. Stop children before shims by sorting on private bytes.
$evidenceTaskName = "WeatherEveningEvidenceRefresh"
if ($localNow.Hour -ge 12 -and $localNow.Hour -lt 18) {
    $evidenceTask = Get-ScheduledTask -TaskName $evidenceTaskName -ErrorAction SilentlyContinue
    if ($evidenceTask -and [string]$evidenceTask.State -ne "Running") {
        $escapedTaskName = [regex]::Escape($evidenceTaskName)
        $orphanedEvidence = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
            ForEach-Object {
                $cmd = [string]$_.CommandLine
                $ageMinutes = ($localNow - $_.CreationDate).TotalMinutes
                if ($ageMinutes -lt 2) { return }
                if ($cmd -notmatch '(?i)-m\s+weather\.operations\.daily_refresh') { return }
                if ($cmd -notmatch "(?i)--scheduler-task-name\s+$escapedTaskName(?:\s|$)") { return }
                $proc = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
                if (-not $proc) { return }
                [pscustomobject]@{
                    Id = $_.ProcessId
                    PrivateBytes = $proc.PrivateMemorySize64
                    PrivateMB = [math]::Round($proc.PrivateMemorySize64 / 1MB, 0)
                    AgeMinutes = [math]::Round($ageMinutes, 0)
                }
            } | Where-Object { $null -ne $_ } | Sort-Object PrivateBytes -Descending)
        foreach ($target in $orphanedEvidence) {
            Write-GuardLog "ACTION" ("owning task {0} is {1} inside protected window; killing orphaned daily-refresh pid {2} age {3}m private {4}MB" -f `
                $evidenceTaskName, $evidenceTask.State, $target.Id, $target.AgeMinutes, $target.PrivateMB)
            try {
                Stop-Process -Id $target.Id -Force -Confirm:$false -ErrorAction Stop
                $guardActions.Add("killed_orphaned_evidence_pid_$($target.Id)")
                $terminationPerformed = $true
                Write-GuardLog "ACTION" ("pid {0} terminated" -f $target.Id)
            }
            catch {
                $guardActions.Add("kill_failed_orphaned_evidence_pid_$($target.Id)")
                Write-GuardLog "ERROR" ("failed to kill orphaned daily-refresh pid {0}: {1}" -f $target.Id, $_.Exception.Message)
            }
        }
    }
}

if ($freeRamMB -lt $warnFreePhysicalMB) {
    $topWorkingSet = Get-Process -ErrorAction SilentlyContinue |
        Sort-Object WorkingSet64 -Descending | Select-Object -First 5 |
        ForEach-Object { "{0}(pid {1})={2}MB" -f $_.Name, $_.Id, [math]::Round($_.WorkingSet64 / 1MB, 0) }
    Write-GuardLog "WARNING" ("physical RAM available at {0} MB, below {1} MB; top working set: {2}" -f `
        [math]::Round($freeRamMB, 0), [math]::Round($warnFreePhysicalMB, 0), ($topWorkingSet -join ", "))
    $status.physical_warning = $true
}

if ($commitPercent -ge $WarnPercent) {
    $top = Get-Process | Sort-Object PrivateMemorySize64 -Descending | Select-Object -First 5 |
        ForEach-Object { "{0}(pid {1})={2}MB" -f $_.Name, $_.Id, [math]::Round($_.PrivateMemorySize64 / 1MB, 0) }
    Write-GuardLog "WARNING" ("commit at {0}% ({1}/{2} MB); top: {3}" -f `
        [math]::Round($commitPercent, 1), [math]::Round($commitUsedMB, 0), [math]::Round($commitTotalMB, 0), ($top -join ", "))
    $status.memory_warning = $true
}

if ($commitPercent -ge $ActPercent -and -not $terminationPerformed) {
    $candidates = @($allProcesses | Where-Object { ([string]$_.Name) -like 'python*' } | ForEach-Object {
        $proc = $runtimeByPid[[uint32]$_.ProcessId]
        if ($null -eq $proc) { return }
        $cmd = [string]$_.CommandLine
        # Governed weather modules are never eligible.
        if (Test-GovernedWeatherProcess $_) { return }
        # Ad-hoc profiles: pytest/compile, stdin script, inline -c, or bare script path.
        $adhoc = ($cmd -match '(?i)python[w]?(\.exe)?"?\s+-\s*$') -or
                 ($cmd -match '(?i)python[w]?(\.exe)?"?\s+-c\s') -or
                 ($cmd -match '(?i)python[w]?(\.exe)?"?\s+[^-]\S*\.py') -or
                 ($cmd -match '(?i)(?:^|\s)-m\s+(?:pytest|compileall|coverage|tox|nox)(?:\s|$)')
        if (-not $adhoc) { return }
        if ($proc.PrivateMemorySize64 -lt $MinKillPrivateBytes) { return }
        [pscustomobject]@{
            Kind = "python"
            Id = $_.ProcessId
            CreationDate = $_.CreationDate
            RootRow = $_
            PrivateBytes = $proc.PrivateMemorySize64
            PrivateMB = [math]::Round($proc.PrivateMemorySize64 / 1MB, 0)
            CommandLine = $cmd.Substring(0, [Math]::Min(200, $cmd.Length))
        }
    } | Where-Object { $null -ne $_ })

    # An agent can spread one runaway over several PowerShell/Python children,
    # each below 8 GiB. Attribute aggregate private bytes to the verified
    # Codex/ChatGPT root and treat the tree as one offender.
    foreach ($root in @($allProcesses | Where-Object { $agentRootNames -contains ([string]$_.Name).ToLowerInvariant() })) {
        $tree = @(Get-ProcessTreeRows $root $allProcesses)
        $privateBytes = [long]0
        foreach ($member in $tree) {
            $runtime = $runtimeByPid[[uint32]$member.ProcessId]
            if ($runtime) { $privateBytes += [long]$runtime.PrivateMemorySize64 }
        }
        if ($privateBytes -lt $MinKillPrivateBytes) { continue }
        $candidates += [pscustomobject]@{
            Kind = "agent_tree"
            Id = $root.ProcessId
            CreationDate = $root.CreationDate
            RootRow = $root
            PrivateBytes = $privateBytes
            PrivateMB = [math]::Round($privateBytes / 1MB, 0)
            CommandLine = "agent process tree"
        }
    }

    $target = $candidates | Sort-Object PrivateBytes -Descending | Select-Object -First 1
    if ($null -ne $target) {
        $reason = "commit at {0}%: {1} pid {2} private {3} MB" -f `
            [math]::Round($commitPercent, 1), $target.Kind, $target.Id, $target.PrivateMB
        $allowWeather = $target.Kind -eq "agent_tree"
        if (Stop-VerifiedProcessTree $target.RootRow $allProcesses $reason $allowWeather) {
            $guardActions.Add("killed_$($target.Kind)_pid_$($target.Id)")
            $terminationPerformed = $true
        }
        else {
            $guardActions.Add("kill_failed_$($target.Kind)_pid_$($target.Id)")
        }
    } else {
        Write-GuardLog "CRITICAL" ("commit at {0}% but no eligible ungoverned offender above {1} MB; manual attention required" -f `
            [math]::Round($commitPercent, 1), [math]::Round($MinKillPrivateBytes / 1MB, 0))
        $guardActions.Add("no_eligible_target")
    }
}

# ---- Orphan sweep: runs every invocation, independent of commit level ----
$orphanActions = @()
$allProcs = @($allProcesses | Where-Object { ([string]$_.Name) -like 'python*' })
$pidTable = @{}
$allProcesses | ForEach-Object { $pidTable[[uint32]$_.ProcessId] = $_.CreationDate }
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
            $guardActions.Add("killed_orphan_pid_$($row.ProcessId)")
            $terminationPerformed = $true
            Write-GuardLog "ACTION" ("pid {0} terminated" -f $row.ProcessId)
        } catch {
            $orphanActions += "kill_failed_pid_$($row.ProcessId)"
            $guardActions.Add("kill_failed_orphan_pid_$($row.ProcessId)")
            Write-GuardLog "ERROR" ("failed to kill orphan pid {0}: {1}" -f $row.ProcessId, $_.Exception.Message)
        }
    } else {
        Write-GuardLog "WARNING" ("orphaned bare-script python left running (detached launchers are legitimate): {0}" -f $summary)
        $orphanActions += "warned_pid_$($row.ProcessId)"
    }
}
$status.orphan_sweep = if ($orphanActions.Count -gt 0) { $orphanActions -join "," } else { "clean" }
$status.actions = @($guardActions)
$status.action = if ($guardActions.Count -gt 0) { $guardActions -join "," } else { "none" }

# Preserve incident-bearing samples without raw command lines. The mutable
# latest status is still atomic and cheap for monitors; history is event-only.
if ($status.physical_warning -or $status.memory_warning -or $guardActions.Count -gt 0 -or $status.agent_heavy_workload_count -gt 0) {
    $history = [ordered]@{
        checked_at = $status.checked_at
        commit_percent = $status.commit_percent
        free_ram_mb = $status.free_ram_mb
        agent_heavy_window_allowed = $status.agent_heavy_window_allowed
        agent_heavy_process_count = $status.agent_heavy_process_count
        agent_heavy_workload_count = $status.agent_heavy_workload_count
        agent_heavy_max_private_mb = $status.agent_heavy_max_private_mb
        actions = @($guardActions)
    }
    Add-Content -LiteralPath $historyPath -Value ($history | ConvertTo-Json -Compress) -Encoding utf8
}

$statusTempPath = "{0}.{1}.tmp" -f $statusPath, [guid]::NewGuid().ToString("N")
try {
    $status | ConvertTo-Json | Out-File -LiteralPath $statusTempPath -Encoding utf8
    Move-Item -LiteralPath $statusTempPath -Destination $statusPath -Force
}
finally {
    if (Test-Path -LiteralPath $statusTempPath) { Remove-Item -LiteralPath $statusTempPath -Force }
}
