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
# Name the failing STEP and its reason. A bare "error" costs a manual dig through
# daily_refresh_status.json every single time, which is exactly what this script exists
# to avoid (2026-07-24: "error" was maker_paper_input_budget_exceeded, 20 min to find).
$chainFail = $null
if ($chain -and $chain.steps) {
    $bad = @($chain.steps | Where-Object { $_.status -and $_.status -notin @("ok", "skipped") })
    if ($bad.Count -gt 0) {
        $f = $bad[0]
        $why = [string]$f.result.reason
        if (-not $why) { $why = [string]$f.error }
        if (-not $why) { $why = [string]$f.result.status }
        if (-not $why) { $why = [string]$f.status }
        # A deferral is the resource gates working as designed (heavy steps refusing to run
        # beside live capture), not a fault. Say so, or every quiet-window-bound run looks broken.
        if ([string]$f.status -eq "deferred") {
            $chainFail = "deferred at {0} ({1}) - heavy steps wait for a quieter host" -f $f.name, $why
        }
        else {
            $chainFail = "FAILING {0} -> {1}" -f $f.name, $why
            $warns.Add("chain step $chainFail")
        }
    }
}
# `terminal` describes the LAST completed run and goes stale the moment a resume starts,
# so trust the live step state instead: a running step means a run is in flight now.
if ($chain -and $chain.current_step -and [string]$chain.current_step.status -like "running*") {
    $chainTerm = "RUNNING NOW: $($chain.current_step.name)"
    $chainFail = $null
}
elseif ($chain -and -not $chain.terminal) {
    $chainTerm = "running/unknown"
}

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
    # 0x41306 = we terminated a wedged push. Pushes need an interactive logon session,
    # so this task legitimately fails when nobody is logged on; the honest health signal
    # is the unpushed-commit count below, not this exit code.
    "WeatherOneShotPush"                     = @("0x1", "0x0", "0x41306")
}
$expDisabled = @("WeatherNightlyRetrainValidatePromote", "WeatherAgentQuietWindow",
    "WeatherTapeBackupAndRestoreDrill")
$taskCount = 0
$interactiveTasks = 0
Get-ScheduledTask | Where-Object { $_.TaskName -like "Weather*" } | ForEach-Object {
    $taskCount++
    # WeatherOneShotPush is deliberately left Interactive: pushing needs the credential
    # vault, which an S4U task in session 0 cannot reach. It is not unattended-critical
    # (commits simply queue), so it must not keep the reboot-exposure flag lit forever.
    if ([string]$_.Principal.LogonType -eq "Interactive" -and $_.TaskName -ne "WeatherOneShotPush") {
        $interactiveTasks++
    }
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

# ---- unattended resilience ----
# Almost every Weather* task is LogonType=Interactive, so the fleet only runs while a
# user session exists. With no auto-logon, a reboot leaves this host DARK -- capture,
# chain, streak monitor and these very alerts all stop -- until somebody logs in. The
# monitoring cannot warn about the one failure that disables the monitoring, so surface
# the exposure continuously instead.
$rebootPending = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
$autoLogon = ""
try {
    $autoLogon = [string](Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -ErrorAction SilentlyContinue).AutoAdminLogon
}
catch {}
if ($interactiveTasks -gt 0 -and $autoLogon -ne "1") {
    if ($rebootPending) {
        $flags.Add("REBOOT PENDING + $interactiveTasks logon-dependent tasks + no auto-logon: a restart leaves the whole fleet DOWN until someone logs in")
    }
    else {
        $warns.Add("$interactiveTasks Weather tasks are LogonType=Interactive with no auto-logon - none of them run after an unattended reboot")
    }
}
elseif ($rebootPending) {
    # The fleet is S4U now, so a restart self-recovers; still worth knowing one is queued
    # because it costs a short capture gap whenever it happens.
    $warns.Add("reboot pending - fleet is S4U so it self-recovers, but expect a brief capture gap; avoid restarting inside 12:00-18:00")
}

# ---- off-host mirror (the only copy of data\ that is not on this disk) ----
$mirror = $null
$mirrorAgeH = $null
$mf = "C:\Users\micha\ops\mirror_status.json"
if (Test-Path $mf) {
    try {
        $mirror = Get-Content $mf -Raw | ConvertFrom-Json
        $mirrorAgeH = [math]::Round(((Get-Date) - [datetime]$mirror.last_run).TotalHours, 1)
    }
    catch {}
}
if ($null -eq $mirror) { $warns.Add("mirror status unreadable - off-host copy unverified") }
elseif (-not $mirror.ok) { $flags.Add("mirror last run FAILED (robocopy exit $($mirror.robocopy_exit))") }
elseif ($mirrorAgeH -gt 30) { $flags.Add("mirror stale: last good run ${mirrorAgeH}h ago (nightly 04:30)") }

# ---- alerts ----
$alertLast = $null
$af = Join-Path $repo "data\alerts\streak_capture_alerts.jsonl"
if (Test-Path $af) {
    $l = Get-Content $af -Tail 1
    if ($l) {
        try {
            $j = $l | ConvertFrom-Json
            $alertLast = "$($j.ts)  $($j.level)"
            # Alerts are written to a file nobody watches; a fresh one must reach the digest.
            if (((Get-Date) - [datetime]$j.ts).TotalHours -lt 24) {
                $flags.Add("capture alert raised in the last 24h: $alertLast")
            }
        }
        catch {}
    }
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
        chain    = @{ status = $chainStatus; terminal = $chainTerm; failing_step = $chainFail }
        git      = @{ unpushed = $unpushed; dirty = $dirtyCount; last = $lastCommit }
        mirror   = @{ ok = $(if ($mirror) { [bool]$mirror.ok } else { $null }); age_hours = $mirrorAgeH }
        resilience = @{ reboot_pending = $rebootPending; auto_logon = ($autoLogon -eq "1");
            interactive_tasks = $interactiveTasks
        }
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
if ($chainFail) { Write-Output ("              step: {0}" -f $chainFail) }
$mirrorStr = if ($null -eq $mirror) { "unreadable" }
elseif ($mirror.ok) { "ok, {0}h ago" -f $mirrorAgeH }
else { "FAILED (exit $($mirror.robocopy_exit))" }
Write-Output ("  OFF-HOST  : mirror {0}    |  reboot pending: {1}   logon-dependent tasks: {2}" -f $mirrorStr, $rebootPending, $interactiveTasks)
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
