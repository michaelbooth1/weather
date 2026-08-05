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

# Free space is a point-in-time number and tells me nothing about how long I have. The
# tape/CLOB history means "195 GB free" can be comfortable or two weeks from an outage
# depending on the slope, so keep a cheap sample trail and report the 24h burn. Sampling
# Get-PSDrive costs nothing -- deliberately NOT a recursive size walk of data\, which has
# starved capture before (see the codex-scan hazard) and must never run from a monitor.
$diskDelta = $null
$diskDaysLeft = $null
try {
    $trail = Join-Path $repo "data\alerts\disk_free_trail.jsonl"
    $old = @()
    if (Test-Path $trail) { $old = @(Get-Content $trail -Tail 400 | Where-Object { $_ }) }
    $cut = (Get-Date).AddHours(-24)
    $ref = $null
    foreach ($line in $old) {
        try {
            $s = $line | ConvertFrom-Json
            if ([datetime]$s.ts -le $cut) { $ref = $s }   # newest sample at least 24h old
        }
        catch {}
    }
    if ($ref) {
        $hrs = ((Get-Date) - [datetime]$ref.ts).TotalHours
        if ($hrs -gt 0) {
            $diskDelta = [math]::Round((($freeDiskGB - $ref.free_gb) / $hrs) * 24, 1)   # GB/day, negative = filling
            if ($diskDelta -lt 0) { $diskDaysLeft = [math]::Round($freeDiskGB / [math]::Abs($diskDelta), 0) }
        }
    }
    $new = @($old) + @(([ordered]@{ ts = (Get-Date).ToString("o"); free_gb = $freeDiskGB } | ConvertTo-Json -Compress))
    Set-Content -Path $trail -Value ($new | Select-Object -Last 400) -Encoding utf8
}
catch {}
if ($null -ne $diskDaysLeft -and $diskDaysLeft -lt 21) {
    $flags.Add("disk filling at $([math]::Abs($diskDelta)) GB/day - about $diskDaysLeft days of headroom left")
}
elseif ($null -ne $diskDaysLeft -and $diskDaysLeft -lt 60) {
    $warns.Add("disk filling at $([math]::Abs($diskDelta)) GB/day - about $diskDaysLeft days left")
}

# ---- daily chain ----
$chain = $null
$cf = Join-Path $repo "data\backtest\daily_refresh_status.json"
if (Test-Path $cf) { try { $chain = Get-Content $cf -Raw | ConvertFrom-Json } catch {} }
$chainStatus = if ($chain) { [string]$chain.status } else { "?" }
$chainTerm = if ($chain -and $chain.terminal) { "terminal" } else { "running/unknown" }
# A `critical` run with every step OK is NOT a broken chain: it is the production-readiness
# gate correctly reporting that no release pointer exists yet, which is the standing
# pre-release state (2026-07-26: 24/24 steps ok, SLA pass, 69 blockers led by
# active_release_verification_failed). Reporting that as breakage is the same false-positive
# trap as the old 0x2 exit code, so name what it actually means.
$chainGate = $null
if ($chain -and $chain.production_readiness) {
    $pr = $chain.production_readiness
    if ([string]$pr.status -eq "SKIPPED") {
        # A SKIPPED readiness gate carries `reason` + `pipeline_status`, NOT stage/
        # blocker_count/first_blocker. The generic format below therefore rendered it as
        # "readiness SKIPPED/, 0 blockers -> " -- three empty fields and a zero, which reads
        # as benign. It is the opposite: SKIPPED means the gate never ran at all because the
        # pipeline upstream of it did not succeed. Name that reason. (2026-08-03.)
        $chainGate = "readiness SKIPPED - {0} (pipeline {1})" -f [string]$pr.reason, [string]$pr.pipeline_status
    }
    else {
        $chainGate = "readiness {0}/{1}, {2} blockers -> {3}" -f [string]$pr.status, [string]$pr.stage,
        [int]$pr.blocker_count, [string]$pr.first_blocker.code
    }
}
# Every step can be `ok` while the run still did not succeed. A step's STEP status only says
# it EXECUTED; its PAYLOAD carries the verdict, and the two disagree routinely. On 2026-08-03
# all 23 steps were `ok` and the chain still terminated `deferred /
# upstream_pipeline_not_successful`, because live_variant_settlement_scorecard,
# hourly_model_performance, ten_minute_model_performance, rollup_freshness and
# trading_evidence were each BLOCK inside $chain.summary. Reading step status alone says
# "the chain is healthy" and is wrong -- surface the payload verdicts too.
$chainBlocked = $null
if ($chain -and $chain.summary) {
    $blocked = @($chain.summary.PSObject.Properties |
        Where-Object { $_.Value -and [string]$_.Value.status -eq "BLOCK" } |
        ForEach-Object { $_.Name })
    if ($blocked.Count -gt 0) { $chainBlocked = "{0} step(s) BLOCK in payload: {1}" -f $blocked.Count, ($blocked -join ", ") }
}
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
        # WHEN it failed matters as much as what failed: a step that broke this morning and
        # was fixed this afternoon still sits in this file until the next run, so an ageless
        # "FAILING" reads as live breakage (2026-07-25: the MemoryError shown here predated
        # its own budget fix by 4.5h). Always say how old the failure is.
        $failAge = ""
        $stepFin = $null
        try {
            if ($f.finished_at_utc) {
                $stepFin = ([datetime]$f.finished_at_utc).ToLocalTime()
                $failAge = " [{0:HH:mm}, {1:N1}h ago]" -f $stepFin, ((Get-Date) - $stepFin).TotalHours
            }
        }
        catch {}
        if ([string]$f.status -eq "deferred") {
            $chainFail = "deferred at {0} ({1}) - heavy steps wait for a quieter host" -f $f.name, $why
        }
        else {
            $chainFail = "FAILING {0}{1} -> {2}" -f $f.name, $failAge, $why
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
$expDisabled = @("WeatherNightlyRetrainValidatePromote", "WeatherAgentQuietWindow")
$taskCount = 0
$interactiveTasks = 0
# Work that is ARMED but has not happened yet is invisible to every other check here: a
# one-shot scheduled for tonight can be deleted, disabled or silently mis-scheduled and
# nothing would say so until the morning it fails to have run. Surface the queue instead.
# List[psobject], not List[object]: `@($list)` throws "Argument types do not match" for a
# generic List[object] on this host. The -Json path only survives it because a pipeline
# enumerates the list first, which is luck rather than design.
$upcoming = New-Object System.Collections.Generic.List[psobject]
Get-ScheduledTask | Where-Object { $_.TaskName -like "Weather*" } | ForEach-Object {
    $taskCount++
    # Both one-shots are deliberately left Interactive: they push (to origin, and to the
    # off-host mirror) and pushing needs the credential vault, which an S4U task in session 0
    # cannot reach -- proved 2026-08-01, "direct push failed (no credential vault under S4U);
    # handing off to WeatherOneShotPush". Neither is unattended-critical (commits simply queue),
    # so neither must keep the reboot-exposure flag lit forever. Do NOT "fix" them to S4U.
    $deliberatelyInteractive = @("WeatherOneShotPush", "WeatherOneShotMirror")
    if ([string]$_.Principal.LogonType -eq "Interactive" -and $deliberatelyInteractive -notcontains $_.TaskName) {
        $interactiveTasks++
    }
    $ti = $_ | Get-ScheduledTaskInfo
    $res = "0x{0:X}" -f ($ti.LastTaskResult)
    $st = [string]$_.State
    $name = $_.TaskName
    # A task due soon on a one-shot trigger is armed work -- the quiet-window merge, a
    # chain recovery run. That is exactly what I want to see queued.
    #
    # Keying this on "never run" (0x41303) alone was wrong and hid real armed work: RE-ARMING
    # an existing one-shot leaves its last result 0x0, so it vanished from this list. Caught
    # 2026-07-27, when the merge task was re-pointed at a new branch for 01:15 and did not
    # appear. MSFT_TaskTimeTrigger is a `-Once` trigger; recurring work uses Daily/Weekly/
    # Logon/Boot classes, so this stays quiet about the routine fleet.
    # Repetition.Interval must be excluded too: the loop supervisors and guards are all
    # registered as a time trigger that then repeats every couple of minutes, so matching
    # the trigger class alone flagged nine recurring tasks as armed one-shot work.
    $oneShot = @($_.Triggers | Where-Object {
            $_.CimClass.CimClassName -eq "MSFT_TaskTimeTrigger" -and -not $_.Repetition.Interval
        }).Count -gt 0
    if ($ti.NextRunTime -and ($res -eq "0x41303" -or $oneShot)) {
        $hrs = ([datetime]$ti.NextRunTime - (Get-Date)).TotalHours
        if ($hrs -gt 0 -and $hrs -lt 16) {
            $upcoming.Add([PSCustomObject]@{
                    name = $name; at = ([datetime]$ti.NextRunTime); in_hours = [math]::Round($hrs, 1)
                    state = $st
                })
            # Armed work that is disabled will never fire, and silence is the failure mode.
            if ($st -eq "Disabled") { $flags.Add("$name is armed for $($ti.NextRunTime) but DISABLED - it will not fire") }
            # Armed work landing inside 12:00-18:00 would roll the fleet in the graded window.
            # quiet_window_merge and chain_recovery_run both refuse there, but a mis-scheduled
            # trigger should be visible here rather than relying on the callee to save us.
            $atHour = ([datetime]$ti.NextRunTime).Hour
            if ($atHour -ge 12 -and $atHour -lt 18) {
                $flags.Add("$name is armed for $($ti.NextRunTime), inside the 12:00-18:00 graded window")
            }
        }
    }
    if ($st -eq "Disabled") {
        # A one-shot that FIRED, SUCCEEDED and then disabled itself is completed work, not an
        # anomaly. Every guarded agent runner (lock day, quiet window, post-merge watchdog,
        # morning briefing) ends with Disable-ScheduledTask by design so it cannot re-fire on a
        # later boot. On 2026-08-05 that raised three simultaneous "unexpectedly DISABLED" flags
        # for three tasks that had each done exactly what they were built to do. Same lesson as
        # the spent-FAILED case below: a monitor that flags success trains us to ignore it.
        $selfDisarmed = ($oneShot -and -not $ti.NextRunTime -and $res -eq "0x0" -and $ti.LastRunTime)
        if ($selfDisarmed) {
            $warns.Add("$name ran $($ti.LastRunTime) and self-disarmed cleanly (spent one-shot, exit 0x0) - completed work, no action")
        }
        elseif ($expDisabled -notcontains $name) { $flags.Add("$name unexpectedly DISABLED") }
    }
    else {
        $ok = ($res -eq "0x0")
        # 0x41301 = SCHED_S_TASK_RUNNING: we sampled the task mid-execution (the
        # every-minute supervisors make this a routine race). The task is healthy
        # by definition while running; its next completed result is what matters.
        if (-not $ok -and $res -eq "0x41301") { $ok = $true }
        # 0x41303 = SCHED_S_TASK_HAS_NOT_RUN: a scheduled one-shot that has not fired yet.
        # Normal for freshly registered work, and flagging it would train us to ignore flags.
        if (-not $ok -and $res -eq "0x41303") { $ok = $true }
        if (-not $ok -and $expNonZero.ContainsKey($name)) { $ok = ($expNonZero[$name] -contains $res) }
        # A SPENT one-shot -- it fired, has no NextRunTime, and last ran over a day ago -- is
        # finished work, not current breakage. Its exit code is history and would otherwise burn
        # a FLAG forever: the three WeatherQuietWindowMerge tasks were still flagging 0x1 from
        # 2026-08-01 two days later, long after a manual re-run had completed the merge. Keep the
        # failure visible, but report it as what it is -- an old run nobody re-armed -- so it
        # cannot masquerade as a live fault and train us to ignore the flag list.
        if (-not $ok -and $oneShot -and -not $ti.NextRunTime -and $ti.LastRunTime -and
            ([datetime]$ti.LastRunTime) -lt (Get-Date).AddHours(-24)) {
            $warns.Add("$name last FAILED $res on $($ti.LastRunTime) and is NOT re-armed (spent one-shot) - re-register it if that work still needs to run")
            $ok = $true
        }
        if (-not $ok) { $flags.Add("$name $res unexpected (last run $($ti.LastRunTime))") }
    }
}

# ---- unattended resilience ----
# HISTORY, because the comment here outlived the fact and produced a false alarm for ten
# days. Before 2026-07-24 almost every Weather* task was LogonType=Interactive, so the fleet
# only ran while a user session existed and a reboot left this host DARK until somebody
# logged in. That was fixed: measured 2026-08-03, every capture-critical task
# (WeatherSnapshotLoopSupervisor, WeatherClobBookLoopSupervisor,
# WeatherObservationTriggerSupervisor, WeatherCapturePriorityGuard) is S4U with a time
# trigger, and WeatherBootRecovery is S4U on a boot trigger. The ONLY Interactive tasks left
# are the two credential-vault one-shots excluded above, neither of which captures anything.
# So $interactiveTasks is now normally 0 and the honest branch is the S4U one at the bottom.
# The exposure is still surfaced continuously, because the monitoring cannot warn about the
# one failure that would disable the monitoring.
#
# NOT YET PROVEN: the S4U fix has never survived a real reboot (uptime was 322 h on
# 2026-08-03; the fix landed 07-24, last boot 07-21). Configuration says capture self-recovers.
# That is not the same as measured. Worth a deliberate 01:00-04:00 reboot test after the lock.
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

# robocopy's exit code says a copy RAN, not that what landed can be restored. With the tape
# backup's restore drill disabled since 2026-06-30, nothing proved the mirror readable until
# verify_mirror_restore.ps1 pulled files back and hashed them. Surface that separately from
# mirror freshness -- "copied recently" and "restorable" are different claims.
$restore = $null
$restoreAgeH = $null
$rf = Join-Path $repo "data\alerts\mirror_restore_verify.json"
if (Test-Path $rf) {
    try {
        $restore = Get-Content $rf -Raw | ConvertFrom-Json
        $restoreAgeH = [math]::Round(((Get-Date) - [datetime]$restore.ts).TotalHours, 1)
    }
    catch {}
}
# No versioned backup exists (the tape subsystem was deleted 2026-07-07, commit 3ebca26e) and
# the nightly /MIR mirror is a replica rather than a backup. That is an ACCEPTED operator
# decision as of 2026-07-26 -- durability work waits until the model is profitable -- so it is
# deliberately NOT reported here. The cheap checks below stay because they already run.
if ($null -eq $restore) { $warns.Add("mirror has never been restore-verified - run scripts\ops\verify_mirror_restore.ps1") }
elseif (-not $restore.ok) { $flags.Add("MIRROR RESTORE VERIFY FAILED: $($restore.problems) problem file(s) - the off-host copy may not be restorable") }
elseif ($restoreAgeH -gt 48) { $warns.Add("mirror restore-verify stale (${restoreAgeH}h) - restorability unproven since then") }

# ---- host stability (this machine loses power) ----
# Event-log forensics on 2026-07-25 found five unexpected shutdowns in 90 days, four of them
# bugcheck=0 / powerButton=0 -- abrupt power loss, not a crash. That is roughly one every
# three weeks against a 14-day contiguous streak, and none of them were ever visible here:
# the digest reported a healthy host either side of a 29-minute outage on 2026-07-21, which
# was day 1 of the current streak. An outage inside 12:00-18:00 ends the streak, so a recent
# one is a FLAG -- it means today's grade needs checking, not just today's process list.
$uptimeH = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1)
$lastCrash = $null
$crashes90 = 0
try {
    $ev = @(Get-WinEvent -FilterHashtable @{LogName = 'System'; Id = 41; StartTime = (Get-Date).AddDays(-90) } -MaxEvents 20 -EA SilentlyContinue)
    $crashes90 = $ev.Count
    if ($ev.Count -gt 0) { $lastCrash = $ev[0].TimeCreated }
}
catch {}
if ($lastCrash -and ((Get-Date) - $lastCrash).TotalHours -lt 24) {
    $flags.Add("UNEXPECTED SHUTDOWN $lastCrash - verify today's capture grade; an outage inside 12:00-18:00 ends the streak")
}
elseif ($crashes90 -ge 3) {
    $warns.Add("$crashes90 unexpected shutdowns in 90d (most recent $lastCrash) - power loss is the top uncontrolled streak risk; a UPS would remove it")
}

# ---- the watchdog itself (who watches the watcher) ----
# health_watchdog.ps1 is what alerts overnight while nobody is awake. If IT dies, every
# window-aware alert silently stops and the first symptom is a morning with no briefing.
# Nothing else here would notice, so check its heartbeat explicitly. It runs every 15 min.
$wd = $null
$wdAgeMin = $null
$wdf = Join-Path $repo "data\alerts\host_health_latest.json"
if (Test-Path $wdf) {
    try {
        $wd = Get-Content $wdf -Raw | ConvertFrom-Json
        $wdAgeMin = [math]::Round(((Get-Date) - [datetime]$wd.ts).TotalMinutes, 0)
    }
    catch {}
}
if ($null -eq $wd) { $flags.Add("health watchdog has never reported - overnight alerting is NOT running") }
elseif ($wdAgeMin -gt 45) { $flags.Add("health watchdog stale by ${wdAgeMin} min (runs every 15) - overnight alerting may be dead") }

# ---- last guarded quiet-window merge ----
# Merges happen at 01:30 while I am not watching; the outcome must be waiting in the morning.
$qw = $null
$qwf = Join-Path $repo "data\alerts\quiet_window_merge_last.json"
if (Test-Path $qwf) {
    try {
        $qw = Get-Content $qwf -Raw | ConvertFrom-Json
        $qwAgeH = ((Get-Date) - [datetime]$qw.ts).TotalHours
        # A rollback means capture did not survive the code roll -- streak-critical, and the
        # branch still needs a human decision. Never let that scroll past in a log file.
        if ($qw.stage -eq "rolled_back" -and $qwAgeH -lt 36) {
            $flags.Add("quiet-window merge ROLLED BACK ($($qw.detail)) - capture did not recover; branch unmerged")
        }
        elseif ($qw.stage -eq "merged_unpushed" -and $qwAgeH -lt 36) {
            $warns.Add("quiet-window merge committed locally but NOT pushed - run WeatherOneShotPush")
        }
    }
    catch {}
}

# ---- alerts ----
$alertLast = $null
$af = Join-Path $repo "data\alerts\streak_capture_alerts.jsonl"
if (Test-Path $af) {
    $l = Get-Content $af -Tail 1
    if ($l) {
        try {
            $j = $l | ConvertFrom-Json
            # Show the AGE. Without it a two-day-old AT_RISK reads as current alarm, which is
            # both frightening and wrong -- the entry is historical the moment the day recovers.
            $ageH = ((Get-Date) - [datetime]$j.ts).TotalHours
            $alertLast = "{0}  {1}  ({2:N0}h ago{3})" -f $j.ts, $j.level, $ageH,
                $(if ($ageH -ge 24) { ", historical" } else { "" })
            # Alerts are written to a file nobody watches; a fresh one must reach the digest.
            if ($ageH -lt 24) {
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
        disk     = @{ free_gb = $freeDiskGB; delta_gb_per_day = $diskDelta; days_left = $diskDaysLeft }
        chain    = @{ status = $chainStatus; terminal = $chainTerm; failing_step = $chainFail; payload_blocked = $chainBlocked }
        git      = @{ unpushed = $unpushed; dirty = $dirtyCount; last = $lastCommit }
        mirror   = @{ ok = $(if ($mirror) { [bool]$mirror.ok } else { $null }); age_hours = $mirrorAgeH
            restore_verified = $(if ($restore) { [bool]$restore.ok } else { $null })
            restore_verify_age_hours = $restoreAgeH
            restore_identical = $(if ($restore) { $restore.verified_identical } else { $null })
        }
        watchdog = @{ age_min = $wdAgeMin; verdict = $(if ($wd) { [string]$wd.verdict } else { $null }) }
        merge    = @{ stage = $(if ($qw) { [string]$qw.stage } else { $null }); ts = $(if ($qw) { [string]$qw.ts } else { $null }) }
        upcoming = @($upcoming | Sort-Object at | ForEach-Object {
                @{ name = $_.name; at = $_.at.ToString("yyyy-MM-dd HH:mm"); in_hours = $_.in_hours }
            })
        resilience = @{ reboot_pending = $rebootPending; auto_logon = ($autoLogon -eq "1");
            interactive_tasks = $interactiveTasks; uptime_hours = $uptimeH
            unexpected_shutdowns_90d = $crashes90
            last_unexpected_shutdown = $(if ($lastCrash) { $lastCrash.ToString("o") } else { $null })
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
$diskTrend = if ($null -eq $diskDelta) { "" }
elseif ($diskDelta -lt 0) { "  ({0} GB/day, ~{1}d left)" -f $diskDelta, $diskDaysLeft }
else { "  (+{0} GB/day)" -f $diskDelta }
Write-Output ("  RESOURCES : RAM {0}/{1} GB free    Disk C: {2} GB free{3}" -f $freeRamGB, $totRamGB, $freeDiskGB, $diskTrend)
$chainNote = if ($chainStatus -eq "critical" -and -not $chainFail) { "all steps OK - 'critical' is the readiness gate, expected pre-release" }
else { "0x2 = gates BLOCK, expected pre-release" }
Write-Output ("  CHAIN     : {0} / {1}   ({2})" -f $chainStatus, $chainTerm, $chainNote)
if ($chainFail) { Write-Output ("              step: {0}" -f $chainFail) }
if ($chainGate) { Write-Output ("              gate: {0}" -f $chainGate) }
if ($chainBlocked) { Write-Output ("              {0}" -f $chainBlocked) }
$mirrorStr = if ($null -eq $mirror) { "unreadable" }
elseif ($mirror.ok) { "ok, {0}h ago" -f $mirrorAgeH }
else { "FAILED (exit $($mirror.robocopy_exit))" }
if ($restore) {
    $mirrorStr += if ($restore.ok) { " [restore-verified {0}/{1} {2}h ago]" -f $restore.verified_identical, $restore.checked, $restoreAgeH }
    else { " [RESTORE VERIFY FAILED]" }
}
else { $mirrorStr += " [never restore-verified]" }
Write-Output ("  OFF-HOST  : mirror {0}    |  reboot pending: {1}   logon-dependent tasks: {2}" -f $mirrorStr, $rebootPending, $interactiveTasks)
$crashStr = if ($lastCrash) { "{0} unexpected shutdown(s)/90d, last {1:MM-dd HH:mm}" -f $crashes90, $lastCrash } else { "no unexpected shutdowns in 90d" }
Write-Output ("  STABILITY : up {0}h   |  {1}" -f $uptimeH, $crashStr)
Write-Output ("  GIT       : {0} unpushed | {1} dirty | {2}" -f $unpushed, $dirtyCount, $lastCommit)
Write-Output ("  TASKS     : {0} Weather tasks scanned (anomalies -> FLAGS)" -f $taskCount)
$wdStr = if ($null -eq $wd) { "NEVER REPORTED" } else { "{0}, {1} min ago" -f ([string]$wd.verdict), $wdAgeMin }
$qwStr = if ($null -eq $qw) { "none" } else { "{0} ({1:yyyy-MM-dd HH:mm})" -f $qw.stage, ([datetime]$qw.ts) }
Write-Output ("  WATCHDOG  : {0}    |  last merge attempt: {1}" -f $wdStr, $qwStr)
Write-Output ("  ALERTS    : last {0}" -f $alertStr)
if ($upcoming.Count -gt 0) {
    Write-Output "  ARMED     : (scheduled, not yet run)"
    foreach ($u in ($upcoming | Sort-Object at)) {
        Write-Output ("              {0:HH:mm} (+{1}h)  {2}" -f $u.at, $u.in_hours, $u.name)
    }
}
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
