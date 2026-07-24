# Overall host health check for the weather production PC -- one command that both
# GATHERS and INTERPRETS state, so a status update is a single tool call.
#
#   .\scripts\ops\status.ps1          # compact human digest (default)
#   .\scripts\ops\status.ps1 -Json     # machine-readable; exit 2 if any FLAG
#
# It delegates the streak to the authoritative checker (streak_status.py, which reads
# the ledger) and adds capture-loop priority, resources, the daily chain, git/push
# state, scheduled-task health, and recent alerts. Crucially it encodes what is
# EXPECTED vs anomalous (e.g. the daily chain exiting 0x2 = model-skill gates BLOCK
# pre-release, the tape backup being broken since Jun 30) so only genuine problems
# land in FLAGS. Pure host tooling, imports nothing from a capture loop -> roll-free.
# See docs/ops/streak-soak.md.
[CmdletBinding()]
param([switch]$Json)

$ErrorActionPreference = "SilentlyContinue"
$repo = "C:\Users\micha\Desktop\github\weather"
$py = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$flags = New-Object System.Collections.Generic.List[string]
$warns = New-Object System.Collections.Generic.List[string]

# ---- streak (delegate to the authoritative ledger-based checker) ----
$streak = $null
try { $streak = & $py (Join-Path $repo "scripts\ops\streak_status.py") --json | ConvertFrom-Json } catch {}
if ($null -eq $streak) { $flags.Add("streak checker failed to run") }
$today = $streak.today_health
if ($today -and $today.verdict -eq "AT_RISK") { $flags.Add("TODAY capture AT_RISK: $($today.reason)") }

# ---- capture workers + priority (persistent loop must be alive & AboveNormal) ----
# Match the FULL module path (as capture_priority_guard.ps1 does), NOT the short name,
# and SKIP the short-lived per-cycle "hot capture" subprocesses the loop spawns to do
# the actual fetch. Those children run at Normal for a few seconds by design (I/O-bound,
# transient) and the 5-min guard rarely coincides with them; counting them would falsely
# report "not all AboveNormal" every capture cycle. The persistent loop is what matters.
$caps = [ordered]@{
    "snapshot_tracker"      = "weather.collection.snapshot_tracker"
    "market_microstructure" = "weather.market.market_microstructure"
    "observation_trigger"   = "weather.operations.observation_trigger"
}
$transientMarks = @("--expected-runtime-fingerprint", "hot_capture", "result.json")
$capState = @{}
foreach ($c in $caps.Keys) { $capState[$c] = @() }
Get-CimInstance Win32_Process | Where-Object { $_.Name -in @("python.exe", "pythonw.exe") } | ForEach-Object {
    $cl = [string]$_.CommandLine
    $skip = $false
    foreach ($tm in $transientMarks) { if ($cl -like "*$tm*") { $skip = $true; break } }
    if ($skip) { return }   # per-cycle capture child, not the persistent loop
    foreach ($label in $caps.Keys) {
        if ($cl -like "*$($caps[$label])*") {
            $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
            if ($p) { $capState[$label] += [string]$p.PriorityClass }
            break
        }
    }
}
foreach ($c in $caps.Keys) {
    if ($capState[$c].Count -eq 0) {
        $flags.Add("capture loop DOWN: $c")   # a dead capture loop is streak-critical
    }
    else {
        $low = @($capState[$c] | Where-Object { $_ -notin @("AboveNormal", "High", "RealTime") })
        if ($low.Count -gt 0) {
            $warns.Add("$c not all AboveNormal ($($capState[$c] -join ',')) - guard re-asserts within 5 min")
        }
    }
}

# ---- resources ----
$os = Get-CimInstance Win32_OperatingSystem
$freeRamGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$totRamGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
$freeDiskGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
if ($freeRamGB -lt 1.5) { $flags.Add("LOW RAM: $freeRamGB GB free (streak-critical)") }
elseif ($freeRamGB -lt 2.5) { $warns.Add("RAM tightening: $freeRamGB GB free") }
if ($freeDiskGB -lt 25) { $flags.Add("LOW DISK: $freeDiskGB GB free") }
elseif ($freeDiskGB -lt 60) { $warns.Add("disk headroom low: $freeDiskGB GB free") }

# ---- daily chain ----
$chain = $null
$cf = Join-Path $repo "data\backtest\daily_refresh_status.json"
if (Test-Path $cf) { try { $chain = Get-Content $cf -Raw | ConvertFrom-Json } catch {} }
$chainStatus = if ($chain) { [string]$chain.status } else { "?" }
$chainTerm = if ($chain -and $chain.terminal) { "terminal" } else { "running/unknown" }

# ---- git / push ----
$unpushed = & git -C $repo rev-list --count origin/master..master 2>$null
if (-not $unpushed) { $unpushed = "?" }
$dirty = @(& git -C $repo status --porcelain 2>$null)
$dirtyCount = ($dirty | Where-Object { $_ }).Count
$lastCommit = & git -C $repo log -1 --format="%h %s" 2>$null
if (($unpushed -ne "?") -and ([int]$unpushed -gt 0)) { $warns.Add("$unpushed commit(s) unpushed (run WeatherOneShotPush)") }

# ---- scheduled tasks (classify against what is EXPECTED) ----
# Tasks that exit non-zero BY DESIGN pre-release, and tasks intentionally disabled.
$expNonZero = @{
    "WeatherDailySettlementPromotionRefresh" = @("0x2")   # model-skill gates BLOCK
    "WeatherEveningEvidenceRefresh"          = @("0x2")   # evidence gates BLOCK
    "WeatherTrainingWindow"                  = @("0x2")   # no promotion pre-release
    "WeatherOneShotPush"                     = @("0x1", "0x0") # benign wrapper exit
}
$expDisabled = @("WeatherNightlyRetrainValidatePromote", "WeatherAgentQuietWindow",
    "WeatherTapeBackupAndRestoreDrill")
$taskCount = 0
Get-ScheduledTask | Where-Object { $_.TaskName -like "Weather*" } | ForEach-Object {
    $taskCount++
    $ti = $_ | Get-ScheduledTaskInfo
    $res = "0x{0:X}" -f ($ti.LastTaskResult)
    $st = [string]$_.State
    $name = $_.TaskName
    if ($st -eq "Disabled") {
        if ($expDisabled -notcontains $name) { $flags.Add("$name unexpectedly DISABLED") }
        elseif ($name -eq "WeatherTapeBackupAndRestoreDrill") {
            $warns.Add("tape backup DISABLED ($res) - broken since Jun 30, backups stale")
        }
    }
    else {
        $ok = ($res -eq "0x0")
        # 0x41301 = SCHED_S_TASK_RUNNING: we sampled the task mid-execution (the
        # every-minute supervisors make this a routine race). The task is healthy
        # by definition while running; its next completed result is what matters.
        if (-not $ok -and $res -eq "0x41301") { $ok = $true }
        if (-not $ok -and $expNonZero.ContainsKey($name)) { $ok = ($expNonZero[$name] -contains $res) }
        if (-not $ok) { $flags.Add("$name $res unexpected (last run $($ti.LastRunTime))") }
    }
}

# ---- alerts ----
$alertLast = $null
$af = Join-Path $repo "data\alerts\streak_capture_alerts.jsonl"
if (Test-Path $af) {
    $l = Get-Content $af -Tail 1
    if ($l) { try { $j = $l | ConvertFrom-Json; $alertLast = "$($j.ts)  $($j.level)" } catch {} }
}

# ---- verdict ----
$verdict = if ($flags.Count -gt 0) { "ATTENTION" } else { "OK" }
$exitCode = if ($flags.Count -gt 0) { 2 } else { 0 }

# ---- render ----
$ts = Get-Date -Format "yyyy-MM-dd HH:mm"
$todayStr = if ($null -eq $today) { "already settled" }
else { "{0}  ({1} caps, {2}min max gap)" -f ([string]$today.verdict).ToUpper(), $today.captures, $today.max_window_gap_min }
$capSummary = ($caps.Keys | ForEach-Object {
        $pri = if ($capState[$_].Count) { (($capState[$_] | Select-Object -Unique) -join ",") } else { "DOWN" }
        "{0}={1}" -f $_, $pri
    }) -join "   "
$alertStr = if ($alertLast) { $alertLast } else { "none" }

if ($Json) {
    [PSCustomObject]@{
        ts       = $ts; verdict = $verdict
        flags    = @($flags); warns = @($warns)
        streak   = @{ days = $streak.streak_days; target = $streak.target; start = $streak.streak_start;
            today = $todayStr; lock = $streak.projected_lock_date_if_all_clean;
            settled = $streak.most_recent_settled
        }
        capture  = $capState; ram_free_gb = $freeRamGB; ram_total_gb = $totRamGB; disk_free_gb = $freeDiskGB
        chain    = @{ status = $chainStatus; terminal = $chainTerm }
        git      = @{ unpushed = $unpushed; dirty = $dirtyCount; last = $lastCommit }
        tasks_scanned = $taskCount; alert_last = $alertStr
    } | ConvertTo-Json -Depth 6
    exit $exitCode
}

$bar = "=" * 76
Write-Output $bar
Write-Output ("  WEATHER HOST STATUS   $ts          VERDICT: $verdict")
Write-Output $bar
Write-Output ("  STREAK    : {0}/{1}  day1 {2}    TODAY: {3}" -f $streak.streak_days, $streak.target, $streak.streak_start, $todayStr)
Write-Output ("              lock ~{0} if all clean   |  settled -> {1}" -f $streak.projected_lock_date_if_all_clean, $streak.most_recent_settled)
Write-Output ("  CAPTURE   : {0}" -f $capSummary)
Write-Output ("  RESOURCES : RAM {0}/{1} GB free    Disk C: {2} GB free" -f $freeRamGB, $totRamGB, $freeDiskGB)
Write-Output ("  CHAIN     : {0} / {1}   (0x2 = gates BLOCK, expected pre-release)" -f $chainStatus, $chainTerm)
Write-Output ("  GIT       : {0} unpushed | {1} dirty | {2}" -f $unpushed, $dirtyCount, $lastCommit)
Write-Output ("  TASKS     : {0} Weather tasks scanned (anomalies -> FLAGS)" -f $taskCount)
Write-Output ("  ALERTS    : last {0}" -f $alertStr)
if ($flags.Count -gt 0) {
    Write-Output ("  " + ("-" * 74))
    Write-Output "  FLAGS (need attention):"
    foreach ($f in $flags) { Write-Output "    ! $f" }
}
if ($warns.Count -gt 0) {
    Write-Output ("  " + ("-" * 74))
    Write-Output "  notes (standing / low-priority):"
    foreach ($w in $warns) { Write-Output "    - $w" }
}
Write-Output $bar
exit $exitCode
